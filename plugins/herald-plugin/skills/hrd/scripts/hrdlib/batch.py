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
from .store import (CLEANUP_REASONS, HOLD_REASONS, auto_exclusion, record_published, branch_name, get_topic, load_published, load_topics,
                    paths, read_json_at, save_published, save_topics, set_topic_state, signal as emit_signal,
                    work_rel)
from .util import HeraldError, git, git_ok, now_iso, read_json, write_json

RATE_LIMIT_RE = re.compile(r"(rate.?limit|usage limit|\b429\b|resets? at)", re.I)
MAX_WAIT = 4 * 3600


def log(msg):
    # progress goes to stderr; stdout carries only the final JSON summary
    sys.stderr.write("[hrd batch %s] %s\n" % (datetime.datetime.now().strftime("%H:%M:%S"), msg))
    sys.stderr.flush()


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
    return ghstate.selectable(root, cfg)[:n]


# --- child sessions --------------------------------------------------------------------------

def run_child(root, cfg, prompt, log_path, budget_usd, extra_env=None, spent=0.0):
    """Returns (outcome, usd). The budget is per article: `spent` carries what earlier attempts
    (rate-limit restarts, the retry child) already cost (plan §3.7)."""
    env = dict(os.environ)
    env.update({"HRD_UNATTENDED": "1"})
    env.update(extra_env or {})
    model = cfg.get("models", "batch_main") or "sonnet"
    cmd = [os.environ.get("HRD_CLAUDE", "claude"), "-p", "--verbose", "--output-format", "stream-json",
           "--model", model, "--dangerously-skip-permissions", prompt]
    prices = cfg.get("models", "prices") or {}
    waited = 0
    while True:
        base_cost = spent
        with open(log_path, "w") as out:
            proc = subprocess.Popen(cmd, cwd=root, stdout=out, stderr=subprocess.STDOUT, env=env,
                                    start_new_session=True)
            over = False
            while proc.poll() is None:
                time.sleep(5)
                if budget_usd and base_cost + stream_json_usd(log_path, prices) > budget_usd:
                    over = True
                    os.killpg(proc.pid, signal.SIGTERM)
                    try:
                        proc.wait(timeout=60)
                    except subprocess.TimeoutExpired:
                        os.killpg(proc.pid, signal.SIGKILL)
                        proc.wait()
                    break
        spent = base_cost + stream_json_usd(log_path, prices)
        if over:
            return "budget", spent
        with open(log_path, errors="replace") as f:
            tail = f.read()[-4000:]
        errors = " ".join(l for l in tail.splitlines() if '"is_error": true' in l or '"is_error":true' in l
                          or not l.lstrip().startswith("{"))
        if proc.returncode != 0 and RATE_LIMIT_RE.search(errors) and waited < MAX_WAIT:
            delay = 900
            log("rate limited — waiting %ds" % delay)
            time.sleep(delay)
            waited += delay
            continue
        return "exited:%d" % proc.returncode, spent


def _topic_branch(root, tid):
    for b in ghstate.local_branches(root):
        if b.startswith("herald/%s--" % tid):
            return b
    return None


def _topic_paths(cfg, tid, slug):
    paths_ = [work_rel(tid)]
    if slug:
        paths_ += [cfg.body_path(slug), cfg.image_dir(slug)]
    return paths_


def _present(root, paths_):
    """Paths that exist on disk or are tracked — `git add` fails on a pathspec matching nothing
    (no image dir without the illustrator, no body before draft)."""
    tracked = set(p for p in git(root, "ls-files", "-z", "--", *paths_).split("\0") if p) if paths_ else set()
    return [p for p in paths_ if os.path.exists(os.path.join(root, p))
            or p in tracked or any(t.startswith(p.rstrip("/") + "/") for t in tracked)]


def _slug_of(root, tid):
    st = read_json(os.path.join(root, work_rel(tid, "state.json"))) or {}
    if st.get("slug"):
        return st["slug"]
    b = _topic_branch(root, tid)
    if b:
        return b.split("--", 1)[1]
    try:
        return get_topic(load_topics(root), tid).get("slug")
    except HeraldError:
        return None


def preserve_wip(root, cfg, tid):
    """Budget/needs-human: commit only this topic's files (PR file scope) to its herald branch
    (no push) and go back to base. The branch keeps the work for a human and `resume`."""
    branch = git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
    if branch.startswith("herald/%s--" % tid):
        slug = branch.split("--", 1)[1]
        targets = _present(root, _topic_paths(cfg, tid, slug))
        if targets:
            git(root, "add", "-A", "--", *targets)
            if git(root, "diff", "--cached", "--name-only", "--", *targets).strip():
                git(root, "commit", "-q", "-m", "wip(herald): %s preserved by batch runner" % tid, "--", *targets)
    git(root, "checkout", "-q", cfg.base)
    # a stray untracked copy of work/<id>/ on base is redundant once the branch holds it
    branch = _topic_branch(root, tid)
    stray = os.path.join(root, work_rel(tid))
    if branch and os.path.isdir(stray) and not git(root, "ls-files", "--", work_rel(tid)).strip():
        same = True
        for dp, _, files in os.walk(stray):
            for fn in files:
                rel = os.path.relpath(os.path.join(dp, fn), root)
                proc = __import__("subprocess").run(["git", "show", "%s:%s" % (branch, rel)], cwd=root,
                                                    capture_output=True)
                with open(os.path.join(dp, fn), "rb") as f:
                    if proc.returncode != 0 or proc.stdout != f.read():
                        same = False
        if same:  # identical to what the branch holds — remove only then
            git(root, "clean", "-q", "-fd", "--", work_rel(tid))


def cleanup_branch(root, cfg, tid):
    """Cleaned holds: remove only this topic's files and branch — never other untracked files."""
    branch = _topic_branch(root, tid)
    slug = _slug_of(root, tid)  # read before work/<id>/ is removed; the child may have deleted the branch
    cur = git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
    targets = _topic_paths(cfg, tid, slug)
    if branch and cur == branch:
        tracked = [p for p in git(root, "ls-files", "-z", "--", *targets).split("\0") if p]
        if tracked:
            git(root, "checkout", "-q", "HEAD", "--", *tracked)
    present = _present(root, targets)
    if present:
        git(root, "clean", "-q", "-fd", "--", *present)
    git(root, "checkout", "-q", cfg.base)
    present = _present(root, targets)
    if present:
        git(root, "clean", "-q", "-fd", "--", *present)
    if branch:
        git(root, "branch", "-q", "-D", branch)


def completed(root, cfg, tid, since=""):
    """An OPEN Herald PR — or one a human merged after this child started — counts as success;
    an old merged PR of a requeued (reverted/withdrawn) topic must not (plan §3.2.1)."""
    res = read_result(root, tid) or {}
    status = str(res.get("status", ""))
    if status.startswith("held:"):
        reason = status.split(":", 1)[1]
        if reason not in HOLD_REASONS:
            res = {"status": "held:needs-human", "note": "child reported unknown hold %r: %s" % (reason, res.get("note"))}
        return res
    for p in ghstate.herald_prs(root, cfg):
        if p["topic_id"] == tid and (p["state"] == "OPEN" or (
                since and (p.get("mergedAt") or "") >= since
                and not (p["label_set"] & {ghstate.REVERTED, ghstate.WITHDRAWN}))):
            return {"status": "pr-open", "pr": p["number"]}
    return None


def record_hold(root, cfg, tid, reason, note):
    """Record and commit each hold immediately (plan §3.2.1): an uncommitted topics.json would be
    lost by the next topic's branch switch and would make the next child's preflight fail."""
    git(root, "checkout", "-q", cfg.base)
    topics = load_topics(root)
    set_topic_state(get_topic(topics, tid), "held", reason, note)
    save_topics(root, topics)
    emit_signal(root, "hold", tid, {"reason": reason, "note": note, "by": "batch"})
    commits.commit_state(root, cfg, "runner", "chore(herald): batch hold %s (%s)" % (tid, reason), "hold",
                         [".claude/herald/topics.json"])
    if cfg.get("autonomy", "publish") != "auto":
        push_base(root, cfg)


# --- auto publish (③–⑤) ----------------------------------------------------------------------

def auto_published_today(pub):
    today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
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
        if not git_ok(root, "fetch", "-q", "origin", "+pull/%d/head:%s" % (prn, ref)):
            skipped.append((tid, "fetch-failed"))
            continue
        crit = read_json_at(root, ref, work_rel(tid, "critique.json"))
        st = read_json_at(root, ref, work_rel(tid, "state.json"))
        if not crit or not st:
            skipped.append((tid, "missing-critique-or-state"))  # fail closed
            continue
        reasons = auto_exclusion(crit)
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
    ship_res = read_result(root, "ship")
    reported = set((ship_res or {}).get("merged") or [])
    if ship_res is None or reported != {n for _, n in merged}:
        log("ship child result missing or disagrees with GitHub (%s vs %s) — not deploying"
            % (sorted(reported), sorted(n for _, n in merged)))
        return False
    sync_base(root, cfg)  # update first, then write records (refresh → write → commit)
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
        commits.commit_state(root, cfg, "runner", "chore(herald): revert/hold records (deploy stopped)", "abort",
                             [".claude/herald/topics.json"])
        return False
    deploy = cfg.get("commands", "deploy")
    if (merged or any(r["merged_unrecorded"] for r in report["articles"])) and deploy:
        proc = subprocess.run(deploy, shell=True, cwd=root)
        if proc.returncode != 0:
            for a in cfg.deploy_artifacts():
                git(root, "checkout", "--", a, check=False)
            commits.commit_state(root, cfg, "runner", "chore(herald): revert/hold records (deploy failed)", "abort",
                                 [".claude/herald/topics.json"])
            log("deploy command failed — merged articles stay merged-unrecorded")
            return False
    chosen_slugs = {by_num[n]["slug"] for _, n in merged}
    # base-wide deploy also publishes earlier merged-unrecorded articles that pass integrity
    extra = [(r["ref_topic"], r["slug"]) for r in report["articles"]
             if r["merged_unrecorded"] and r["status"] == "ok" and r["slug"] not in chosen_slugs and r["ref_topic"]]
    for tid, slug in extra:
        if url_ok(cfg.article_url(slug)):
            record_published(root, cfg, tid, slug, auto=False)  # merged by a human earlier
    for tid, n in merged:
        slug = by_num[n]["slug"]
        if not url_ok(cfg.article_url(slug)):
            log("URL check failed for %s — left merged-unrecorded" % slug)
            continue
        record_published(root, cfg, tid, slug, pr=n, auto=True)
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
        untracked = integrity.untracked_build_inputs(root, cfg)
        if untracked:
            raise HeraldError("untracked files in build inputs — commit, move or remove them before batch: %s"
                              % ", ".join(untracked[:5]))
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
            git(root, "checkout", "-q", cfg.base)
            sync_base(root, cfg)  # children only fast-forward; keep base current for them
            log("write %s" % tid)
            started = now_iso().replace("+00:00", "Z")
            outcome, spent = run_child(root, cfg, "/hrd write %s" % tid, os.path.join(logs, tid + ".jsonl"), budget)
            if outcome == "budget":
                preserve_wip(root, cfg, tid)
                record_hold(root, cfg, tid, "budget", "per-article budget %.2f USD exceeded" % budget)
                summary["held"].append((tid, "budget"))
                continue
            res = completed(root, cfg, tid, since=started)
            if not res:
                # one retry: resume if the child got as far as a branch, else start over
                retry = "/hrd resume %s" % tid if _topic_branch(root, tid) else "/hrd write %s" % tid
                log("%s incomplete (%s) — one retry: %s" % (tid, outcome, retry))
                preserve_wip(root, cfg, tid)  # keep the child's untracked work on its branch, not on base
                outcome, spent = run_child(root, cfg, retry, os.path.join(logs, tid + "-retry.jsonl"), budget,
                                           spent=spent)
                if outcome == "budget":
                    preserve_wip(root, cfg, tid)
                    record_hold(root, cfg, tid, "budget", "per-article budget %.2f USD exceeded (incl. retry)" % budget)
                    summary["held"].append((tid, "budget"))
                    continue
                res = completed(root, cfg, tid, since=started)
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
        auto = cfg.get("autonomy", "publish") == "auto"
        chosen = []
        if auto and summary["pr"]:
            chosen, skipped = auto_candidates(root, cfg, summary["pr"])
            summary["auto"] = {"chosen": chosen, "skipped": skipped}
            if chosen:
                sync_base(root, cfg)
                # the ship child only fast-forwards: publish this run's hold commits first so a
                # GitHub merge never leaves its base diverged from origin
                push_base(root, cfg)
                p = os.path.join(result_dir(root), "ship.json")
                if os.path.exists(p):
                    os.remove(p)
                env = {"HRD_AUTO_PRS": " ".join(str(n) for _, n in chosen)}
                run_child(root, cfg, "/hrd ship --auto", os.path.join(logs, "ship.jsonl"), 0, env)
                git(root, "checkout", "-q", cfg.base)
                summary["auto"]["published"] = finish_auto(root, cfg, chosen)
        if auto and not chosen and (summary["held"] or summary["incomplete"]):
            push_base(root, cfg)  # holds were committed per topic; nothing else will push them
    finally:
        lock.release(root, token, owner=True)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0
