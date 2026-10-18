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

from . import commits, ghstate, integrity, lock, ratelimit
from .config import Config
from .measure import stream_json_usd
from .store import (CLEANUP_REASONS, HOLD_REASONS, bundle_urls, exclusion_reasons, record_published, branch_name, get_topic, load_published, load_topics,
                    paths, read_json_at, save_published, save_topics, set_topic_state, safe_signal as emit_signal,
                    NON_SIGNAL_HOLD_NOTES, work_rel)
from .util import HeraldError, git, git_ok, now_iso, read_json, version_tuple, write_json

CHILDREN = set()  # process-group ids of running children, for the SIGTERM handler


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


def foreign_ahead(root, cfg):
    """Commits on local base that are neither Herald records nor sync merges (a child may have
    moved base with a command the guard did not catch). Checked before every push and deploy."""
    return [c for c in commits.classify_ahead(root, cfg, cfg.base) if not c["ok"]]


LAST_RECORD = {"sha": None}


def remember(sha):
    if sha:
        LAST_RECORD["sha"] = sha
    return sha


def push_base(root, cfg):
    base = cfg.base
    if LAST_RECORD["sha"] and not git_ok(root, "merge-base", "--is-ancestor", LAST_RECORD["sha"], base):
        log("refusing to push: the runner's last record commit %s is no longer on %s (base was reset)"
            % (LAST_RECORD["sha"][:8], base))
        return False
    bad = foreign_ahead(root, cfg)
    if bad:
        log("refusing to push: base carries non-Herald commits %s" % ", ".join(c["sha"][:8] for c in bad))
        return False
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

def run_once(root, cfg, prompt, log_path, budget_usd, extra_env=None, spent=0.0):
    """One child session. Returns (outcome, usd, returncode, log_path); outcome is "budget" or
    "exited:<rc>". The budget is per article: `spent` carries what earlier attempts of this topic
    in this run (usage-limit restarts, the retry child) already cost (plan §3.7). Usage limits
    are judged by the caller from the log (ratelimit.scan), never here."""
    env = dict(os.environ)
    env.pop("HRD_BATCH_TEST_CLOCK", None)  # the runner's test clock never reaches a child
    env.pop("HRD_RESUME_LIMITED", None)    # only the topic the runner itself held gets it
    env.update({"HRD_UNATTENDED": "1"})
    env.update(extra_env or {})
    model = cfg.get("models", "batch_main") or "sonnet"
    cmd = [os.environ.get("HRD_CLAUDE", "claude"), "-p", "--verbose", "--output-format", "stream-json",
           "--model", model, "--dangerously-skip-permissions", prompt]
    prices = cfg.get("models", "prices") or {}
    base_cost = spent
    with open(log_path, "w") as out:
        proc = subprocess.Popen(cmd, cwd=root, stdout=out, stderr=subprocess.STDOUT, env=env,
                                start_new_session=True)
        CHILDREN.add(proc.pid)
        over = False
        while proc.poll() is None:
            time.sleep(5)
            if budget_usd and base_cost + stream_json_usd(log_path, prices) > budget_usd:
                over = True
                if proc.poll() is None:  # an exited (unreaped) group refuses killpg on macOS
                    try:
                        os.killpg(proc.pid, signal.SIGTERM)
                        proc.wait(timeout=60)
                    except subprocess.TimeoutExpired:
                        try:
                            os.killpg(proc.pid, signal.SIGKILL)
                        except OSError:
                            pass
                        proc.wait()
                    except OSError:
                        proc.wait()
                break
    spent = base_cost + stream_json_usd(log_path, prices)
    CHILDREN.discard(proc.pid)
    if over:
        return "budget", spent, proc.returncode, log_path
    return "exited:%d" % proc.returncode, spent, proc.returncode, log_path


def run_child(root, cfg, prompt, log_path, budget_usd, extra_env=None, spent=0.0):
    """One child, no waiting — the ship child (§2.8: never re-run after a usage limit)."""
    outcome, spent, _, _ = run_once(root, cfg, prompt, log_path, budget_usd, extra_env, spent)
    return outcome, spent


# --- usage limits (design/herald/05-batch-rate-limit.md) ---------------------------------------

MAX_SINGLE_WAIT = 5 * 3600     # one wait; a later reset stops the run instead of sleeping
MAX_WAITS = 6                  # usage-limit waits per topic per run
RUN_WAIT_CAP = 12 * 3600       # all waits of one run, overloaded backoffs included
BACKOFF_MIN = [15, 30, 60, 120, 120, 120]  # unknown reset: minutes for the 1st..6th wait
MAX_OVERLOADS = 3
LIMIT_NOTE = "tooling: rate limited"


class Clock:
    """Wall clock; HRD_BATCH_TEST_CLOCK=<epoch> makes waits advance a fake clock instead (tests
    only — each slice still sleeps 0.05 s so a test can act during a wait)."""

    def __init__(self):
        v = os.environ.get("HRD_BATCH_TEST_CLOCK")
        self.fake = float(v) if v else None

    def now(self):
        return self.fake if self.fake is not None else time.time()

    def sleep(self, secs):
        if self.fake is None:
            time.sleep(secs)
        else:
            time.sleep(0.05)
            self.fake += secs


class LockLost(Exception):
    """The checkout lock changed hands during a wait: leave everything as it is."""


class QuietStop(Exception):
    """Stop the run without touching git (the checkout is a human's now)."""


class RateLimitStop(Exception):
    """A usage limit beyond the run's ceilings: end the run cleanly (not an error)."""

    def __init__(self, info):
        Exception.__init__(self, "usage limit")
        self.info = info


def iso(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def wait_out(root, clock, token, secs, label, kind="limit"):
    """Sleep `secs` in slices until a wall-clock deadline, checking each slice that the lock is
    still ours. lock.wait tells other commands why the checkout is locked."""
    deadline = clock.now() + secs
    lock.write_wait(root, token, iso(deadline) if clock.fake is None else iso(time.time() + secs), kind)
    last_note = clock.now()
    try:
        while True:
            left = deadline - clock.now()
            if left <= 0:
                return
            clock.sleep(min(60, left))
            if (lock.status(root) or {}).get("token") != token:
                raise LockLost()
            if clock.now() - last_note >= 600:
                last_note = clock.now()
                log("%s — %dm left" % (label, max(0, deadline - clock.now()) // 60))
    finally:
        if (lock.status(root) or {}).get("token") == token:
            lock.clear_wait(root, token)


def pr_done(root, cfg, tid, since):
    """completed()'s PR rule: an OPEN Herald PR, or one merged at/after `since` and not
    reverted/withdrawn — an old PR of a requeued topic does not count."""
    for p in ghstate.herald_prs(root, cfg):
        if p["topic_id"] != tid:
            continue
        if p["state"] == "OPEN":
            return {"status": "pr-open", "pr": p["number"]}
        if since and (p.get("mergedAt") or "") >= since and not (p["label_set"] & {ghstate.REVERTED, ghstate.WITHDRAWN}):
            return {"status": "merged-by-human", "pr": p["number"]}
    return None


def limit_hold_of(root, tid, run_id):
    """True when the topic's last history entry is this run's usage-limit hold."""
    try:
        t = get_topic(load_topics(root), tid)
    except HeraldError:
        return False
    h = (t.get("history") or [{}])[-1]
    return (t.get("state") == "held" and h.get("reason") == "needs-human"
            and str(h.get("note") or "").startswith(LIMIT_NOTE) and ("(run %s)" % run_id) in str(h.get("note")))


def release(root, cfg, tid, run_id, summary=None):
    """The topic this run held for a usage limit reached a PR: back to queued (an open PR then
    derives pr-pending). Only if nobody changed it meanwhile (another machine)."""
    preserve_wip(root, cfg, tid)  # whatever the child left on its branch stays there; back to base
    sync_base(root, cfg)
    if not limit_hold_of(root, tid, run_id):
        log("%s reached a PR but its hold changed meanwhile — not released" % tid)
        if summary is not None:
            summary.setdefault("not_released", []).append(tid)
        return False
    topics = load_topics(root)
    set_topic_state(get_topic(topics, tid), "queued", None, "resumed to PR after a usage limit")
    save_topics(root, topics)
    remember(commits.commit_state(root, cfg, "runner", "chore(herald): batch release %s (resumed to PR)" % tid,
                                  "hold", [".claude/herald/topics.json"]))
    push_base(root, cfg)
    if summary is not None and tid in summary.get("rate_limit_held", []):
        summary["rate_limit_held"].remove(tid)  # no longer held: never tell the human to resume it
    return True


def _topic_branch(root, tid):
    for b in ghstate.local_branches(root):
        if b.startswith("herald/%s--" % tid):
            return b
    return None


def _topic_paths(cfg, tid, slug):
    """Everything a cleanup removes: the work dir and the whole bundle (every configured
    translation path too — 01-multilingual.md §5)."""
    paths_ = [work_rel(tid)]
    if slug:
        paths_ += cfg.bundle_paths(slug)
    return paths_


def _discard_out_of_scope(root, cfg, tid, slug, scope):
    """Bundle paths outside the topic's PR scope that changed (a tr- source, a translation of
    another language): saved under memory/wip-discard/<id>/ (tracked: a diff; untracked: a
    copy — `git diff` shows no untracked file), then put back, so nothing follows the switch to
    base (01-multilingual.md §5)."""
    import shutil

    outside = [p for p in cfg.bundle_paths(slug) if p not in scope]
    present = _present(root, outside)
    if not present:
        return
    tracked = [p for p in git(root, "ls-files", "-z", "--", *present).split("\0") if p]
    untracked = [p for p in git(root, "ls-files", "-z", "--others", "--exclude-standard", "--", *present).split("\0") if p]
    diff = git(root, "diff", "HEAD", "--", *tracked) if tracked else ""
    if not diff.strip() and not untracked:
        return
    keep = os.path.join(paths(root)["memory"], "wip-discard", tid)
    os.makedirs(keep, exist_ok=True)
    if diff.strip():
        with open(os.path.join(keep, "tracked.diff"), "w", encoding="utf-8") as f:
            f.write(diff)
    for p in untracked:
        dst = os.path.join(keep, "untracked", p)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(os.path.join(root, p), dst)
    if tracked:
        git(root, "checkout", "-q", "HEAD", "--", *tracked)
    if untracked:
        git(root, "clean", "-q", "-f", "--", *untracked)


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
        # commit the PR scope only (a runner commit passes no guard); then put back the rest
        from .commits import pr_scope_paths, topic_langs
        scope = pr_scope_paths(cfg, tid, slug, topic_langs(root, tid))
        targets = _present(root, scope)
        if targets:
            git(root, "add", "-A", "--", *targets)
            if git(root, "diff", "--cached", "--name-only", "--", *targets).strip():
                git(root, "commit", "-q", "-m", "wip(herald): %s preserved by batch runner" % tid, "--", *targets)
        _discard_out_of_scope(root, cfg, tid, slug, scope)
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
        if p["topic_id"] == tid and p["state"] == "OPEN":
            return {"status": "pr-open", "pr": p["number"]}
        if p["topic_id"] == tid and since and (p.get("mergedAt") or "") >= since \
                and not (p["label_set"] & {ghstate.REVERTED, ghstate.WITHDRAWN}):
            # a human merged it during the run: done, but not an auto candidate (ship records it)
            return {"status": "merged-by-human", "pr": p["number"]}
    return None


def scripts_version(root):
    """SCRIPTS_VERSION of the repo's installed hrd.py (read from the file: base may move)."""
    try:
        with open(os.path.join(root, ".claude", "herald", "scripts", "hrd.py"), encoding="utf-8") as f:
            m = re.search(r'^SCRIPTS_VERSION = "([^"]+)"', f.read(), re.M)
    except OSError:
        return None
    return m.group(1) if m else None


def record_hold(root, cfg, tid, reason, note, push=None):
    """Record and commit each hold immediately (plan §3.2.1): an uncommitted topics.json would be
    lost by the next topic's branch switch and would make the next child's preflight fail.
    push=True pushes in auto mode too (a usage-limit hold before a long wait)."""
    git(root, "checkout", "-q", cfg.base)
    topics = load_topics(root)
    set_topic_state(get_topic(topics, tid), "held", reason, note)
    save_topics(root, topics)
    if not str(note or "").startswith(NON_SIGNAL_HOLD_NOTES):  # a tooling stop is not a writing problem
        emit_signal(root, "hold", tid, {"reason": reason, "note": note, "by": "batch"})
    remember(commits.commit_state(root, cfg, "runner", "chore(herald): batch hold %s (%s)" % (tid, reason), "hold",
                                  [".claude/herald/topics.json"]))
    if push or cfg.get("autonomy", "publish") != "auto":
        push_base(root, cfg)


# --- auto publish (③–⑤) ----------------------------------------------------------------------

def auto_published_today(pub, topics=None):
    """Auto publishes today, plus auto merges not yet recorded as published (they count against
    the daily throttle too)."""
    today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    n = 0
    for a in pub["articles"]:
        if isinstance(a.get("publishes"), list):  # a translation repo: one entry per publish (§5)
            n += sum(1 for e in a["publishes"] if isinstance(e, dict) and e.get("auto")
                     and str(e.get("at", "")).startswith(today))
        elif a.get("human_reviewed") is False and str(a.get("published_at", "")).startswith(today):
            n += 1
    for t in (topics or {}).get("topics", []):
        if t.get("auto_merged_pr") and str(t.get("auto_merged_at", "")).startswith(today) \
                and t.get("state") not in ("published", "withdrawn") and t.get("reason") != "reverted":
            n += 1
    return n


def auto_candidates(root, cfg, pr_results):
    pub = load_published(root)
    room = int(cfg.get("autonomy", "throttle", "max_per_day") or 0) - auto_published_today(pub, load_topics(root))
    chosen, skipped = [], []
    for tid, prn in pr_results:
        if room <= 0:
            skipped.append((tid, "throttle"))
            continue
        ref = "refs/remotes/origin/pr-%d" % prn
        if not git_ok(root, "fetch", "-q", "origin", "+pull/%d/head:%s" % (prn, ref)):
            skipped.append((tid, "fetch-failed"))
            continue
        reasons = exclusion_reasons(root, cfg, tid, ref)  # fails closed on missing files
        from .translation import premerge_problems
        # translated PRs: base source unchanged, no deleted/foreign/withdrawn languages (§5)
        reasons += ["premerge:%s" % re.match(r"[a-z-]*", p).group(0) for p in premerge_problems(root, cfg, tid, ref)]
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
    # record the unattended merges first, in tracked state, before any path can stop: whoever
    # records these articles later must keep human_reviewed=false (plan §3.2.2)
    git(root, "checkout", "-q", cfg.base)
    sync_error = None
    try:
        sync_base(root, cfg)  # origin moved by the GitHub merges: fast-forward before writing records
    except HeraldError as e:
        sync_error = e  # still record the merges locally below; the next run's step 1 carries them
    if merged:
        topics = load_topics(root)
        for tid, n in merged:
            get_topic(topics, tid)["auto_merged_pr"] = n
            get_topic(topics, tid)["auto_merged_at"] = now_iso()
        save_topics(root, topics)
        commits.commit_state(root, cfg, "runner", "chore(herald): auto merges %s" % ", ".join("#%d" % n for _, n in merged),
                             "ship", [".claude/herald/topics.json"])
    if sync_error:
        log("base sync failed after auto merges (%s) — merges recorded locally, not deploying" % sync_error)
        return False
    ship_res = read_result(root, "ship")
    reported = set((ship_res or {}).get("merged") or [])
    if ship_res is None or reported != {n for _, n in merged}:
        log("ship child result missing or disagrees with GitHub (%s vs %s) — not deploying"
            % (sorted(reported), sorted(n for _, n in merged)))
        push_base(root, cfg)  # the auto-merge records must reach origin even when we stop here
        return False
    topics = load_topics(root)
    for rv in ghstate.pending_removal_reverts(root, cfg, topics):
        for p in prs:
            if p["topic_id"] == rv["topic_id"] and p.get("mergedAt"):
                ghstate.add_label(root, p["number"], ghstate.REVERTED)
        t = get_topic(topics, rv["topic_id"])
        set_topic_state(t, "held", "reverted", "revert PR #%d" % rv["number"])
        t.setdefault("reverted_by", []).append(rv["number"])
    save_topics(root, topics)
    # commit revert records before the pre-deploy check (it refuses a dirty tracked tree)
    commits.commit_state(root, cfg, "runner", "chore(herald): revert records", "revert",
                         [".claude/herald/topics.json"])
    prs = ghstate.herald_prs(root, cfg)
    report = integrity.predeploy(root, cfg, prs=prs)
    if not report["ok"]:
        log("pre-deploy integrity failed — not deploying: %s" % json.dumps(
            {k: report[k] for k in ("untracked_build_inputs", "tracked_dirty", "ignored_residue", "flags")}))
        commits.commit_state(root, cfg, "runner", "chore(herald): revert/hold records (deploy stopped)", "abort",
                             [".claude/herald/topics.json"])
        push_base(root, cfg)
        return False
    bad = foreign_ahead(root, cfg)
    if bad:
        log("refusing to deploy: base carries non-Herald commits %s" % ", ".join(c["sha"][:8] for c in bad))
        return False
    deploy = cfg.get("commands", "deploy")
    if (merged or any(r["merged_unrecorded"] for r in report["articles"])) and deploy:
        proc = subprocess.run(deploy, shell=True, cwd=root)
        if proc.returncode != 0:
            for a in cfg.deploy_artifacts():
                git(root, "checkout", "--", a, check=False)
            commits.commit_state(root, cfg, "runner", "chore(herald): revert/hold records (deploy failed)", "abort",
                                 [".claude/herald/topics.json"])
            push_base(root, cfg)
            log("deploy command failed — merged articles stay merged-unrecorded")
            return False
    chosen_slugs = {by_num[n]["slug"] for _, n in merged}
    # base-wide deploy also publishes earlier merged-unrecorded articles that pass integrity
    extra = [(r["ref_topic"], r["slug"]) for r in report["articles"]
             if r["merged_unrecorded"] and r["status"] == "ok" and r["slug"] not in chosen_slugs and r["ref_topic"]]
    for tid, slug in extra:
        if all(url_ok(u) for u in bundle_urls(root, cfg, slug).values()):
            record_published(root, cfg, tid, slug)  # auto_merged_pr on the topic keeps human_reviewed=false
    for tid, n in merged:
        slug = by_num[n]["slug"]
        # the source and every translation: the bundle is published as one (§5)
        if not all(url_ok(u) for u in bundle_urls(root, cfg, slug).values()):
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
    ap.add_argument("--detach", action="store_true", help="fork, setsid, log to memory/batch-logs/")
    ap.add_argument("--expect-version", help="the plugin's version: stop when base's scripts differ")
    a = ap.parse_args(argv)
    from .util import repo_root
    root = repo_root()
    cfg = Config.load_checked(root)
    logs_dir = os.path.join(paths(root)["memory"], "batch-logs")
    os.makedirs(logs_dir, exist_ok=True)
    if a.detach:
        if os.fork():
            print(json.dumps({"detached": True, "pid_file": os.path.join(logs_dir, "runner.pid"),
                              "summary": os.path.join(logs_dir, "runner.out"),
                              "log": os.path.join(logs_dir, "runner.log")}))
            return 0
        os.setsid()
        sys.stdin = open(os.devnull)
        sys.stdout = open(os.path.join(logs_dir, "runner.out.tmp"), "w", buffering=1)
        sys.stderr = open(os.path.join(logs_dir, "runner.log"), "a", buffering=1)
        os.dup2(sys.stdout.fileno(), 1)
        os.dup2(sys.stderr.fileno(), 2)
    try:
        token = lock.acquire(root, "batch")
    except HeraldError as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        raise
    with open(os.path.join(logs_dir, "runner.pid"), "w") as f:  # only once the lock is ours
        f.write(str(os.getpid()))
    os.environ["HRD_LOCK_TOKEN"] = token

    def on_term(signum, frame):  # stopped from outside: end children, free the checkout lock — never git
        for pid in list(CHILDREN):
            try:
                os.killpg(pid, signal.SIGTERM)
            except OSError:
                pass
        if (lock.status(root) or {}).get("token") == token:
            lock.clear_wait(root, token)
            lock.release(root, token, owner=True)
            sys.stderr.write("[hrd batch] stopped by signal %d — lock released\n" % signum)
        else:  # taken by another command during a wait: not ours to release
            sys.stderr.write("[hrd batch] stopped by signal %d — the lock is no longer ours\n" % signum)
        os._exit(130)

    signal.signal(signal.SIGTERM, on_term)
    signal.signal(signal.SIGINT, on_term)
    signal.signal(signal.SIGHUP, signal.SIG_IGN)  # detached runs survive a hangup
    os.makedirs(result_dir(root), exist_ok=True)
    logs = os.path.join(paths(root)["memory"], "batch-logs")
    os.makedirs(logs, exist_ok=True)
    summary = {"pr": [], "held": [], "incomplete": [], "auto": None}
    clock = Clock()
    if clock.fake is not None:
        log("WARNING: HRD_BATCH_TEST_CLOCK is set — usage-limit waits use a fake clock (tests only)")
    run_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lost = {"lock": False}
    if a.detach:  # the summary file is replaced only by a run that holds the lock
        os.replace(os.path.join(logs_dir, "runner.out.tmp"), os.path.join(logs_dir, "runner.out"))
    # the plugin's version (batch.md passes it); else this runner's own scripts, read before any
    # sync — the code this process loaded
    expected = a.expect_version or scripts_version(root)

    def publish_holds():
        # only this run's record commits (record_hold does not push in auto mode); never push what
        # a human deliberately left unpushed when this run recorded nothing
        if cfg.get("autonomy", "publish") == "auto" and LAST_RECORD["sha"]:
            try:
                push_base(root, cfg)
            except HeraldError as e:  # never let a push problem hide why the batch stops
                log("could not push this run's holds: %s" % e)

    def stop(msg):
        publish_holds()
        raise HeraldError(msg)

    def check_version():
        """Children stop at the version gate when base's scripts differ from the plugin: stop the
        batch instead of holding every remaining topic."""
        now = scripts_version(root)
        try:
            want = version_tuple(expected) if expected is not None else None
        except HeraldError:
            stop("malformed --expect-version %r (expected dot-separated integers)" % expected)
        try:
            have = version_tuple(now) if now is not None else (0, 0, 0)  # no SCRIPTS_VERSION = pre-0.3.0
        except HeraldError:
            have = (0, 0, 0)
        if want is None or have != want:
            if not a.expect_version:
                hint = "base's scripts changed since this runner started — run /hrd batch again"
            elif want is not None and have > want:
                hint = "base is newer than the plugin: update the installed plugin and restart, then batch again"
            else:
                hint = "base is older than the plugin: run /hrd update, then batch again"
            stop("Herald scripts on base are %s but this batch expects %s — %s"
                 % (now or "older than 0.3.0", expected or "an unknown version", hint))


    def child_prompt(tid):
        """Restart and retry prompt: a tr- topic always resumes through translate (§7)."""
        if tid.startswith("tr-"):
            return "/hrd translate --resume %s" % tid
        return "/hrd resume %s" % tid if _topic_branch(root, tid) else "/hrd write %s" % tid

    def handle_result(tid, res):
        if res["status"].startswith("held:") and str(res.get("note") or "").startswith("tooling: herald version"):
            # the child stopped at the version gate (at start, or after `HRD branch` / a branch
            # switch). No branch yet → the topic stays queued. A branch exists → keep its work
            # there and hold it (a tooling hold: no growth signal) so `/hrd resume` can continue;
            # a queued topic with a local branch would never be selected again.
            branch = _topic_branch(root, tid)
            if branch:
                preserve_wip(root, cfg, tid)
                record_hold(root, cfg, tid, "needs-human", "tooling: herald version mismatch on %s — "
                            "update, then /hrd resume %s" % (branch, tid))
                summary["held"].append((tid, "needs-human"))
            git(root, "checkout", "-q", cfg.base)
            check_version()
            stop("a child stopped at the Herald version gate (%s) — update so plugin and scripts match, "
                 "then run /hrd batch again" % res.get("note"))
        if res["status"].startswith("held:"):
            reason = res["status"].split(":", 1)[1]
            if reason in CLEANUP_REASONS:
                cleanup_branch(root, cfg, tid)
            else:
                preserve_wip(root, cfg, tid)
            record_hold(root, cfg, tid, reason, res.get("note"))
            summary["held"].append((tid, reason))
        elif res["status"] == "merged-by-human":
            summary.setdefault("merged_by_human", []).append((tid, res["pr"]))
        else:
            summary["pr"].append((tid, res["pr"]))
        git(root, "checkout", "-q", cfg.base)

    def stop_hold(tid, held, why):
        """A topic with a branch must not be left queued (it would never be selected again)."""
        if not held and _topic_branch(root, tid):
            record_hold(root, cfg, tid, "needs-human", "tooling: batch stopped after a usage-limit wait (%s) — "
                        "/hrd resume %s" % (why, tid))
            summary["held"].append((tid, "needs-human"))

    def after_wait(tid, held, started):
        """§2.4 1–3. Returns True to restart; False to drop this topic and go on."""
        head = git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
        dirty = git(root, "status", "--porcelain", "--untracked-files=no").strip()
        if head != cfg.base or dirty:
            raise QuietStop("the checkout changed during a usage-limit wait (%s%s) — left as it is"
                            % (head, ", modified files" if dirty else ""))
        try:
            sync_base(root, cfg)
            check_version()
        except HeraldError:
            stop_hold(tid, held, "base sync or version check failed")
            raise
        if held:
            ok = limit_hold_of(root, tid, run_id)
        else:
            try:
                ok = get_topic(load_topics(root), tid).get("state") == "queued" and not pr_done(root, cfg, tid, started)
            except HeraldError:
                ok = False
        if not ok:
            branch = _topic_branch(root, tid)
            stop_hold(tid, held, "changed elsewhere")
            summary.setdefault("skipped", []).append(
                {"topic": tid, "why": ("local branch %s kept — delete it or /hrd resume %s" % (branch, tid))
                 if branch else "changed or taken elsewhere during the wait"})
        return ok

    def handle_topic(tid):
        p = os.path.join(result_dir(root), tid + ".json")
        git(root, "checkout", "-q", cfg.base)
        sync_base(root, cfg)  # children only fast-forward; keep base current for them
        check_version()  # a /hrd update may have landed on origin mid-batch
        log("write %s" % tid)
        started = now_iso().replace("+00:00", "Z")
        prompt = "/hrd translate --resume %s" % tid if tid.startswith("tr-") else "/hrd write %s" % tid
        spent, waits, overloads, n = 0.0, 0, 0, 0
        retried = held = r7_prev = False
        while True:
            if budget and spent > budget:
                preserve_wip(root, cfg, tid)
                record_hold(root, cfg, tid, "budget", "per-article budget %.2f USD exceeded (incl. retries)" % budget)
                summary["held"].append((tid, "budget"))
                return
            if held:
                done = pr_done(root, cfg, tid, started)
                if done:
                    release(root, cfg, tid, run_id, summary)
                    handle_result(tid, done)
                    return
            if os.path.exists(p):
                os.remove(p)  # every attempt writes its own result
            n += 1
            env = {"HRD_RESUME_LIMITED": run_id} if held else {}
            outcome, spent, rc, logp = run_once(root, cfg, prompt, os.path.join(logs, "%s-%s-%d.jsonl" % (run_id, tid, n)),
                                                budget, env, spent)
            if outcome == "budget":
                preserve_wip(root, cfg, tid)
                record_hold(root, cfg, tid, "budget", "per-article budget %.2f USD exceeded%s"
                            % (budget, " (incl. retries)" if n > 1 else ""))
                summary["held"].append((tid, "budget"))
                return
            if held:  # the PR beats any result file (a child cut off between `gh pr create` and `HRD result`)
                done = pr_done(root, cfg, tid, started)
                if done:
                    release(root, cfg, tid, run_id, summary)
                    handle_result(tid, done)
                    return
            res = completed(root, cfg, tid, since=started)
            demoted = False
            if res and res["status"].startswith("held:") and str(res.get("note") or "").startswith(LIMIT_NOTE):
                sv = ratelimit.scan(logp, rc, clock.now())  # H9: a sub-agent hit a usage limit
                reset = (sv["reset_at"] if sv["limited"] and sv["kind"] == "limit" else None) or \
                    ratelimit.extract_reset(str(res.get("note")), clock.now())
                v = ratelimit.verdict(True, "limit", reset, "result-note", sv.get("info"), str(res.get("note"))[:200])
            elif res:
                if held and not res["status"].startswith("held:"):
                    release(root, cfg, tid, run_id, summary)
                handle_result(tid, res)
                return
            else:
                v = ratelimit.scan(logp, rc, clock.now())
                demoted = v["demoted"]
                if demoted and r7_prev:  # a "passed" reset right after another one: a misread time zone
                    v = ratelimit.verdict(True, "limit", None, v["source"], v["info"], "limit again after a passed reset")
            r7_prev = demoted  # "right after": every attempt resets it
            if v["limited"] and v["kind"] == "limit":
                waits += 1
                now = clock.now()
                reset = v["reset_at"]
                if reset == ratelimit.FAR:
                    secs, far, until = 0, True, "far"
                elif isinstance(reset, int):
                    secs, far, until = max(0, reset - now) + 30, reset - now > MAX_SINGLE_WAIT, iso(reset)
                else:
                    secs, far, until = BACKOFF_MIN[min(waits, len(BACKOFF_MIN)) - 1] * 60, False, "unknown"
                log("rate limited (%s) — %s; reset %s; wait %d/%d; detail=%s; info=%s"
                    % (v["source"], tid, until, waits, MAX_WAITS, v["detail"], json.dumps(v["info"], ensure_ascii=False)))
                if budget and spent > budget:
                    continue  # the loop top holds it for the budget, without sleeping
                preserve_wip(root, cfg, tid)
                if not held and _topic_branch(root, tid):
                    record_hold(root, cfg, tid, "needs-human", "%s until %s (run %s)" % (LIMIT_NOTE, until, run_id),
                                push=True)
                    held = True
                    summary.setdefault("rate_limit_held", []).append(tid)
                if far or waits > MAX_WAITS or waited["s"] + secs > RUN_WAIT_CAP:
                    raise RateLimitStop({"topic": tid, "until": until, "waits": waits,
                                         "why": "reset beyond 5h" if far else "too many waits" if waits > MAX_WAITS
                                         else "12h of waiting in this run"})
                summary.setdefault("rate_limit_waits", []).append(
                    {"topic": tid, "source": v["source"], "kind": "limit", "waited_s": int(secs), "until": until})
                wait_out(root, clock, token, secs, "%s waiting for the usage limit (until %s)" % (tid, until))
                waited["s"] += secs
                if not after_wait(tid, held, started):
                    return
                preserve_wip(root, cfg, tid)
                prompt = child_prompt(tid)
                log("resuming %s: %s" % (tid, prompt))
                continue
            if v["limited"] and v["kind"] == "overloaded" and overloads < MAX_OVERLOADS:
                overloads += 1
                preserve_wip(root, cfg, tid)
                secs = 60 * overloads
                log("API overloaded — %s; backing off %ds (%d/%d)" % (tid, secs, overloads, MAX_OVERLOADS))
                summary.setdefault("rate_limit_waits", []).append(
                    {"topic": tid, "source": v["source"], "kind": "overloaded", "waited_s": secs, "until": None})
                wait_out(root, clock, token, secs, "%s backing off" % tid, kind="overloaded")
                waited["s"] += secs
                git(root, "checkout", "-q", cfg.base)
                prompt = child_prompt(tid)
                continue
            if not retried:
                retried = True
                prompt = child_prompt(tid)
                log("%s incomplete (%s) — one retry: %s" % (tid, outcome, prompt))
                preserve_wip(root, cfg, tid)  # keep the child's untracked work on its branch, not on base
                continue
            preserve_wip(root, cfg, tid)
            record_hold(root, cfg, tid, "needs-human", "tooling: batch child did not finish (%s)" % outcome)
            # context for evolve (listed, never counted): a repo-specific crash pattern stays visible
            emit_signal(root, "incomplete", tid, {"outcome": outcome})
            summary["incomplete"].append(tid)
            return

    waited = {"s": 0}

    try:
        sync_base(root, cfg)
        check_version()
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
            handle_topic(tid)
        auto = cfg.get("autonomy", "publish") == "auto"
        chosen = []
        held_back = set(summary.get("not_released", []))  # its hold changed elsewhere: a human decides
        if auto and [x for x in summary["pr"] if x[0] not in held_back]:
            chosen, skipped = auto_candidates(root, cfg, [x for x in summary["pr"] if x[0] not in held_back])
            summary["auto"] = {"chosen": chosen, "skipped": skipped}
            if chosen:
                sync_base(root, cfg)
                check_version()
                # the ship child only fast-forwards: publish this run's hold commits first so a
                # GitHub merge never leaves its base diverged from origin
                push_base(root, cfg)
                p = os.path.join(result_dir(root), "ship.json")
                if os.path.exists(p):
                    os.remove(p)
                env = {"HRD_AUTO_PRS": " ".join(str(n) for _, n in chosen)}
                _, _, ship_rc, ship_log = run_once(root, cfg, "/hrd ship --auto",
                                                   os.path.join(logs, "%s-ship.jsonl" % run_id), 0, env)
                sv = ratelimit.scan(ship_log, ship_rc, clock.now())
                if sv["limited"]:  # never re-run a ship child (partial merges): record what merged, no deploy
                    summary["auto"]["rate_limited"] = sv["kind"]
                    log("ship child stopped on %s (%s) — not re-run; /hrd ship later"
                        % ("a usage limit" if sv["kind"] == "limit" else "an overloaded API", sv["detail"]))
                git(root, "checkout", "-q", cfg.base)
                ship_res = read_result(root, "ship") or {}
                if str(ship_res.get("note") or "").startswith("tooling: herald version"):
                    stop("the ship child stopped at the Herald version gate — nothing was merged by it; "
                         "update so plugin and scripts match, then /hrd ship")
                summary["auto"]["published"] = finish_auto(root, cfg, chosen)
        if auto and not chosen and (summary["held"] or summary["incomplete"]):
            push_base(root, cfg)  # holds were committed per topic; nothing else will push them
    except RateLimitStop as e:
        # the limit is account-wide: the next topic would hit it too. Holds are recorded; end cleanly.
        summary["rate_limited"] = dict(e.info, held=summary.get("rate_limit_held", []),
                                       prs=[n for _, n in summary["pr"]])
        log("stopping: usage limit (%s) — until %s" % (e.info.get("why"), e.info.get("until")))
        if LAST_RECORD["sha"]:
            try:
                push_base(root, cfg)
            except HeraldError as pe:
                log("could not push this run's records: %s" % pe)
    except QuietStop as e:
        summary["stopped"] = str(e)
        log("stopping without git: %s" % e)
    except LockLost:
        lost["lock"] = True
        summary["error"] = "lock taken during a usage-limit wait — stopped without touching the checkout"
        log(summary["error"])
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 1
    except HeraldError as e:
        summary["error"] = str(e)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        raise
    finally:
        if not lost["lock"]:
            lock.clear_wait(root, token)
            lock.release(root, token, owner=True)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0
