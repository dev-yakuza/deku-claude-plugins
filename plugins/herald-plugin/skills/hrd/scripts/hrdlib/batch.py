"""`/hrd batch` runner (plan §3.2.1 batch structure, §3.2.2 batch+auto table, §3.7 budget).

A plain process, not an agent: it is the only writer of base-branch state during a batch.
Children (`claude -p`) run with HRD_UNATTENDED=1 and never write base; they leave result
files in .claude/herald/memory/batch/. Completion is judged from GitHub + result files,
never from a child's exit code (Guild batch.md's exit-0 lesson).
"""

import datetime
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.request

from . import commits, ghstate, integrity, lock
from .config import Config
from .measure import stream_json_usd
from .store import (CLEANUP_REASONS, auto_exclusion, branch_name, get_topic, load_published, load_topics,
                    paths, read_json_at, save_published, save_topics, set_topic_state, signal as emit_signal,
                    work_rel)
from .util import HeraldError, git, git_ok, now_iso, read_json, write_json

RATE_LIMIT_RE = re.compile(r"(rate.?limit|usage limit|429|resets? at)", re.I)
MAX_WAIT = 4 * 3600


def log(msg):
    sys.stdout.write("[hrd batch %s] %s\n" % (datetime.datetime.now().strftime("%H:%M:%S"), msg))
    sys.stdout.flush()


def result_dir(root):
    return os.path.join(paths(root)["memory"], "batch")


def read_result(root, name):
    return read_json(os.path.join(result_dir(root), name + ".json"))


# --- base sync -------------------------------------------------------------------------------

def sync_base(root, cfg):
    commits.sync_base(root, cfg)


def push_base(root, cfg):
    base = cfg.base
    if git_ok(root, "push", "-q", "origin", base):
        return True
    sync_base(root, cfg)
    if git_ok(root, "push", "-q", "origin", base):
        return True
    log("push refused twice — record commits stay unpushed; the next run's step 1 picks them up")
    return False


# --- selection -------------------------------------------------------------------------------

def select_topics(root, cfg, n):
    topics = load_topics(root)
    prs = ghstate.herald_prs(root, cfg)
    busy = {p["topic_id"] for p in prs if p["state"] == "OPEN" or p.get("mergedAt")}
    busy |= {b.split("/", 1)[1].split("--", 1)[0] for b in ghstate.local_branches(root)}
    picked = [t["id"] for t in topics["topics"] if t.get("state") == "queued" and t["id"] not in busy]
    return picked[:n]


# --- child sessions --------------------------------------------------------------------------

def run_child(root, cfg, prompt, log_path, budget_usd, extra_env=None):
    env = dict(os.environ)
    env.update({"HRD_UNATTENDED": "1"})
    env.update(extra_env or {})
    model = cfg.get("models", "batch_main") or "sonnet"
    cmd = [os.environ.get("HRD_CLAUDE", "claude"), "-p", "--verbose", "--output-format", "stream-json",
           "--model", model, "--dangerously-skip-permissions", prompt]
    prices = cfg.get("models", "prices") or {}
    waited = 0
    while True:
        with open(log_path, "w") as out:
            proc = subprocess.Popen(cmd, cwd=root, stdout=out, stderr=subprocess.STDOUT, env=env,
                                    start_new_session=True)
            over = False
            while proc.poll() is None:
                time.sleep(5)
                if budget_usd and stream_json_usd(log_path, prices) > budget_usd:
                    over = True
                    os.killpg(proc.pid, signal.SIGTERM)
                    proc.wait(timeout=60)
                    break
        if over:
            return "budget"
        tail = open(log_path, errors="replace").read()[-4000:]
        if proc.returncode != 0 and RATE_LIMIT_RE.search(tail) and waited < MAX_WAIT:
            delay = 900
            log("rate limited — waiting %ds" % delay)
            time.sleep(delay)
            waited += delay
            continue
        return "exited:%d" % proc.returncode


def preserve_wip(root, cfg, tid):
    """Budget/needs-human: commit the child's leftovers to its herald branch (no push), go back
    to base. The branch keeps the work so a human can judge and `resume` can continue."""
    branch = git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
    if branch.startswith("herald/%s--" % tid):
        if git(root, "status", "--porcelain").strip():
            git(root, "add", "-A")
            git(root, "commit", "-q", "-m", "wip(herald): %s preserved by batch runner" % tid)
    git(root, "checkout", "-q", cfg.base)


def cleanup_branch(root, cfg, tid):
    git(root, "checkout", "-q", "-f", cfg.base)
    git(root, "clean", "-q", "-fd", "--", *(cfg.get("paths", "build_inputs") or []))
    for b in ghstate.local_branches(root):
        if b.startswith("herald/%s--" % tid):
            git(root, "branch", "-q", "-D", b)


def completed(root, cfg, tid):
    res = read_result(root, tid) or {}
    if str(res.get("status", "")).startswith("held:"):
        return res
    for p in ghstate.herald_prs(root, cfg):
        if p["topic_id"] == tid and (p["state"] == "OPEN" or p.get("mergedAt")):
            return {"status": "pr-open", "pr": p["number"]}
    return None


def record_hold(root, cfg, tid, reason, note):
    topics = load_topics(root)
    set_topic_state(get_topic(topics, tid), "held", reason, note)
    save_topics(root, topics)
    emit_signal(root, "hold", tid, {"reason": reason, "note": note, "by": "batch"})


# --- auto publish (③–⑤) ----------------------------------------------------------------------

def auto_published_today(pub):
    today = datetime.date.today().isoformat()
    return sum(1 for a in pub["articles"] if a.get("human_reviewed") is False
               and str(a.get("published_at", "")).startswith(today))


def auto_candidates(root, cfg, pr_results):
    pub = load_published(root)
    room = int(cfg.get("autonomy", "throttle", "max_per_day") or 0) - auto_published_today(pub)
    chosen, skipped = [], []
    for tid, prn in pr_results:
        if room <= 0:
            skipped.append((tid, "throttle"))
            continue
        ref = "refs/remotes/origin/pr-%d" % prn
        git(root, "fetch", "-q", "origin", "pull/%d/head:%s" % (prn, ref), check=False)
        crit = read_json_at(root, ref, work_rel(tid, "critique.json"))
        reasons = auto_exclusion(crit)
        st = read_json_at(root, ref, work_rel(tid, "state.json")) or {}
        img = cfg.image_dir(st.get("slug", "")) + "/"
        files = commits.changed_files(root, "origin/%s" % cfg.base, ref) if st.get("slug") else []
        if st.get("slug") and any(f.startswith(img) for f in files):
            reasons.append("images")
        if reasons:
            skipped.append((tid, ",".join(reasons)))
            continue
        chosen.append((tid, prn))
        room -= 1
    return chosen, skipped


def url_ok(url, timeout_s=600):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(urllib.request.Request(url, method="GET"), timeout=20) as r:
                if 200 <= r.status < 400:
                    return True
        except Exception:
            pass
        time.sleep(15)
    return False


def finish_auto(root, cfg, chosen):
    """⑤: re-derive what really merged (never trust the ship child's report), then integrity,
    deploy, URL check, record."""
    prs = ghstate.herald_prs(root, cfg)
    by_num = {p["number"]: p for p in prs}
    merged = [(tid, n) for tid, n in chosen if by_num.get(n, {}).get("mergedAt")]
    topics = load_topics(root)
    for rv in ghstate.pending_removal_reverts(root, cfg, topics):
        for p in prs:
            if p["topic_id"] == rv["topic_id"] and p.get("mergedAt"):
                ghstate.add_label(root, p["number"], ghstate.REVERTED)
        t = get_topic(topics, rv["topic_id"])
        set_topic_state(t, "held", "reverted", "revert PR #%d" % rv["number"])
        t.setdefault("reverted_by", []).append(rv["number"])
    save_topics(root, topics)
    sync_base(root, cfg)
    prs = ghstate.herald_prs(root, cfg)
    report = integrity.predeploy(root, cfg, prs=prs)
    if not report["ok"]:
        log("pre-deploy integrity failed — not deploying: %s" % json.dumps(
            {k: report[k] for k in ("untracked_build_inputs", "tracked_dirty", "ignored_residue", "flags")}))
        commits.commit_state(root, cfg, "runner", "chore(herald): batch holds (deploy stopped)", "abort",
                             [".claude/herald/topics.json"])
        return False
    deploy = cfg.get("commands", "deploy")
    if merged and deploy:
        proc = subprocess.run(deploy, shell=True, cwd=root)
        if proc.returncode != 0:
            for a in cfg.deploy_artifacts():
                git(root, "checkout", "--", a, check=False)
            log("deploy command failed — merged articles stay merged-unrecorded")
            return False
    pub = load_published(root)
    topics = load_topics(root)
    for tid, n in merged:
        slug = by_num[n]["slug"]
        if not url_ok(cfg.article_url(slug)):
            log("URL check failed for %s — left merged-unrecorded" % slug)
            continue
        art = next((a for a in pub["articles"] if a["slug"] == slug), None)
        if not art:
            art = {"slug": slug, "moved_from": []}
            pub["articles"].append(art)
        art.update({"path": cfg.body_path(slug), "url": cfg.article_url(slug), "origin": "herald",
                    "current_topic_id": tid, "published_at": now_iso(), "human_reviewed": False,
                    "withdrawn": False})
        set_topic_state(get_topic(topics, tid), "published", note="auto PR #%d" % n)
    save_published(root, pub)
    save_topics(root, topics)
    files = [".claude/herald/topics.json", ".claude/herald/published.json"] + cfg.deploy_artifacts()
    commits.commit_state(root, cfg, "runner", "chore(herald): auto publish record", "ship", files)
    push_base(root, cfg)
    return True


# --- main -----------------------------------------------------------------------------------

def main(argv):
    import argparse

    ap = argparse.ArgumentParser(prog="batch_runner")
    ap.add_argument("--n", type=int, default=3)
    a = ap.parse_args(argv)
    from .util import repo_root
    root = repo_root()
    cfg = Config.load(root)
    token = lock.acquire(root, "batch")
    os.environ["HRD_LOCK_TOKEN"] = token
    os.makedirs(result_dir(root), exist_ok=True)
    logs = os.path.join(paths(root)["memory"], "batch-logs")
    os.makedirs(logs, exist_ok=True)
    summary = {"pr": [], "held": [], "incomplete": [], "auto": None}
    try:
        sync_base(root, cfg)
        ahead = [c for c in commits.classify_ahead(root, cfg, cfg.base) if not c["ok"]]
        if ahead:
            raise HeraldError("base has unpushed commits that are not Herald records — resolve before batch: %s"
                              % ", ".join(c["sha"][:8] for c in ahead))
        budget = float(cfg.get("budget", "per_article_usd") or 0)
        for tid in select_topics(root, cfg, a.n):
            for f in (tid,):
                p = os.path.join(result_dir(root), f + ".json")
                if os.path.exists(p):
                    os.remove(p)
            log("write %s" % tid)
            outcome = run_child(root, cfg, "/hrd write %s" % tid, os.path.join(logs, tid + ".jsonl"), budget)
            if outcome == "budget":
                preserve_wip(root, cfg, tid)
                record_hold(root, cfg, tid, "budget", "per-article budget %.2f USD exceeded" % budget)
                summary["held"].append((tid, "budget"))
                continue
            res = completed(root, cfg, tid)
            if not res:
                log("%s incomplete (%s) — one resume" % (tid, outcome))
                run_child(root, cfg, "/hrd resume %s" % tid, os.path.join(logs, tid + "-resume.jsonl"), budget)
                res = completed(root, cfg, tid)
            if not res:
                preserve_wip(root, cfg, tid)
                record_hold(root, cfg, tid, "needs-human", "batch child did not finish (%s)" % outcome)
                summary["incomplete"].append(tid)
                continue
            if res["status"].startswith("held:"):
                reason = res["status"].split(":", 1)[1]
                if reason in CLEANUP_REASONS:
                    cleanup_branch(root, cfg, tid)
                else:
                    preserve_wip(root, cfg, tid)
                record_hold(root, cfg, tid, reason, res.get("note"))
                summary["held"].append((tid, reason))
            else:
                summary["pr"].append((tid, res["pr"]))
            git(root, "checkout", "-q", cfg.base)
        sync_base(root, cfg)
        if summary["held"] or summary["incomplete"]:
            commits.commit_state(root, cfg, "runner", "chore(herald): batch holds", "hold",
                                 [".claude/herald/topics.json"])
            if cfg.get("autonomy", "publish") != "auto":
                push_base(root, cfg)
        if cfg.get("autonomy", "publish") == "auto" and summary["pr"]:
            chosen, skipped = auto_candidates(root, cfg, summary["pr"])
            summary["auto"] = {"chosen": chosen, "skipped": skipped}
            if chosen:
                sync_base(root, cfg)
                env = {"HRD_AUTO_PRS": " ".join(str(n) for _, n in chosen)}
                run_child(root, cfg, "/hrd ship --auto", os.path.join(logs, "ship.jsonl"), 0, env)
                git(root, "checkout", "-q", cfg.base)
                finish_auto(root, cfg, chosen)
            elif summary["held"] or summary["incomplete"]:
                push_base(root, cfg)
    finally:
        lock.release(root, token)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0
