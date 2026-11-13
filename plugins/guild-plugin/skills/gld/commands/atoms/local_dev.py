#!/usr/bin/env python3
"""
local_dev.py — the opt-in local-model developer of the execute stage (implementation only).

A Sonnet developer writes the failing tests (committed, or staged when a pre-commit hook that
runs the suite refuses red tests); this tool asks a model served by a
local Ollama to write the implementation that turns them green, up to `max_attempts` times, and
hands the Issue back to the Sonnet developer when it cannot. The leader never sees an attempt:
it starts a job, waits on it, and reads one result. So a retry costs local time, not Claude
tokens. Contract: `_execute_spine.md` Step 1L · config `local_developer` (`config.md`).

    local_dev.py start  --issue N --base REF --files F [F ...] --tests T [T ...]
                        [--attended] [--note TEXT]
                        check eligibility, then start a detached worker and return at once
    local_dev.py wait   --issue N --max-seconds S
                        block until the job is terminal or S seconds pass; print its state
    local_dev.py status --issue N [--last]
                                      the current job of this Issue on this branch, or none;
                                      --last also returns an acknowledged one, with
                                      `local_code_in_tree` — true while the files still hold
                                      exactly what was committed at `ack` and no `note` has been
                                      written since (a pass is sent back at most once)
    local_dev.py revert --issue N     put the implementation files back as they were before the
                                      job, staged copies included (a refused commit of a pass)
    local_dev.py ack    --issue N     mark the terminal job consumed (the leader acted on it)
    local_dev.py note   --issue N --event TEXT
                                      record what happened to this Issue's newest job AFTER it
                                      ended (a pass rejected in review, a later loop-back)
    local_dev.py report               failure analysis over every run in runs.jsonl

Every subcommand prints a `>>> LOCAL-DEV <<<` sentinel line and then ONE JSON object. `state` is
`queued` (waiting for the model) / `running` (not terminal) or `local_pass` / `fallback`
(terminal) or `none`. A `fallback` carries `reason`: `ineligible:<why>` · `server_down` ·
`queue_busy` (attended only) · `max_attempts` · `context_overflow` (earlier edits grew the
files past what `num_ctx` holds) · `tests_modified` (a check run changed a test file — it is
put back as it was at start) · `total_timeout` · `worker_died` · `worker_error`.
A `local_pass` carries `tree`: `uncommitted` (commit it) · `committed` (a resumed leader already
did) · `restored` (it was reverted).

Why a detached worker: one Bash call is capped (60 min unattended, 10 min attended by default)
and a backgrounded task dies with an unattended turn. The job — queue wait included — can
outlive both, so it runs in its own session and the leader re-calls `wait` until it is done.
A leader session that dies (rate limit) loses nothing: on resume `status` finds the same job.

Liveness is a held `flock`, never a pid. `start` takes `worker.lock` before it spawns the worker
and hands the locked descriptor down, so there is no instant at which a live worker looks dead;
the lock is released only when the worker process is gone (crash, SIGKILL, reboot), and a pid
the OS reuses later cannot hold it. Whoever then takes the lock (`wait`/`status`) is the single
settler of the dead job. The queue tickets use the same rule.

The machine-wide queue (one model, several sprints): every model call takes a ticket in
`~/.cache/guild/local-dev-queue/` (`GLD_LOCAL_DEV_QUEUE_DIR` overrides) and runs only when its
ticket is the oldest live one — first come, first served, which a bare `flock` does not
promise. An unattended job takes a ticket per model call, so while it runs its tests the model
serves the next job. An attended job (`--attended`) never waits: a busy queue at start is an
immediate `queue_busy` fallback, and once started it keeps its ticket until it ends, so a human
is never held behind a sprint between two attempts either.
⚠ Queue wait is NOT counted in `total_timeout_min` — that budget is the job's own active time
(model calls + checks). An unattended job waits as long as the queue needs.

Attempt outcomes (runs.jsonl, per attempt): `pass` · `apply_fail` · `lint_fail` · `test_fail` ·
`output_cap` (the model hit its output cap — every later attempt then runs at
`max_output_tokens_retry`, lowered per job to what `num_ctx` leaves beside the prompt; one cut
off while still reasoning, before any edit, hands the next answered attempt its reasoning's tail
and turns reasoning off for the rest of the job — `think: false`) · `attempt_timeout` (the model call passed
`attempt_timeout_min`) · `model_error`. A fallback restores every `--files` path to its bytes
before the job and saves what the model last wrote as `last-local.diff`; the tests the Sonnet
developer wrote are never touched (edits outside `--files` are refused, whole reply).

Files: `.claude/guild/memory/local-dev/` (gitignored with the rest of memory/):
    runs.jsonl                         one line per finished job (+ `followup` lines from `note`)
    <issue>/<job>/job.json             live state (the worker is its only writer until terminal)
    <issue>/<job>/attempt<k>.prompt.txt · .response.txt · .checks.txt
    <issue>/<job>/last-local.diff      on fallback · test-output.txt on pass · worker.log
    <issue>/<job>/tests-changed/       a test as a check run left it, before it was put back

Exit: 0 ok (the state is in the JSON) · 64 usage · 65 config or repository error.
"""
import argparse
import datetime
import fcntl
import hashlib
import json
import os
import re
import secrets
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

SENTINEL = ">>> LOCAL-DEV <<<"
TERMINAL = ("local_pass", "fallback")
DEFAULTS = {
    "enabled": False,
    "model": None,
    "ollama_url": "http://127.0.0.1:11434",
    "max_attempts": 3,
    "max_output_tokens": 8000,
    "max_output_tokens_retry": 16000,
    "attempt_timeout_min": 20,
    "total_timeout_min": 60,
    "num_ctx": 65536,
    "test_cmd": None,
    "lint_cmd": None,
}
FEEDBACK_CHARS = 6000          # failure output handed back to the model per attempt
FIT_MARGIN = 500               # chat template and estimate slack kept free in num_ctx
CARRY_CHARS = 12000            # tail of a cut-off attempt's reasoning handed to the next one
MIN_CARRY_CHARS = 2000         # less room than this → no carry (and reasoning stays on)
EXCERPT_CHARS = 4000           # failure output kept in runs.jsonl
POLL_SECONDS = 2.0

SYSTEM = """You are the developer of a spec-driven workflow. The design skeleton is fixed and \
the failing tests are already written. Change the implementation so those tests \
pass, following the skeleton.

Rules:
- Edit ONLY the implementation files you are given. Never touch tests.
- Keep the change minimal; do not refactor unrelated code.
- Output edits ONLY as SEARCH/REPLACE blocks in this exact format — nothing else is applied:

path/to/file.ext
<<<<<<< SEARCH
exact existing lines (copied verbatim, enough to be unique)
=======
replacement lines
>>>>>>> REPLACE

- SEARCH must match the current file exactly (whitespace included) and occur exactly once.
  An empty SEARCH is allowed only for an empty file (it then becomes the replacement).
- Several blocks are allowed. Brief reasoning before the blocks is allowed."""

SEARCH_MARK, DIVIDER, REPLACE_MARK = "<<<<<<< SEARCH", "=======", ">>>>>>> REPLACE"
THINK_END = "</think>"
FENCE_RE = re.compile(r"^\s*(```|~~~)")


class RepoError(Exception):
    pass


# --------------------------------------------------------------------------- helpers

def now_iso():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def git(repo, *args, check=True):
    p = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    if check and p.returncode != 0:
        raise RepoError(f"git {' '.join(args)}: {p.stderr.strip()}")
    return p.stdout


def repo_root():
    p = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if p.returncode != 0:
        raise RepoError("not inside a git repository")
    return p.stdout.strip()


def write_json(path, obj):
    tmp = f"{path}.tmp-{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def emit(obj):
    print(SENTINEL)
    print(json.dumps(obj, ensure_ascii=False))


def try_lock(path):
    """An fd holding an exclusive lock on `path`, or None when someone else holds it."""
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    return fd


def load_config(repo):
    path = os.path.join(repo, ".claude", "guild", "config.json")
    try:
        cfg = read_json(path)
    except FileNotFoundError:
        raise RepoError("Guild is not initialized (.claude/guild/config.json missing)")
    except ValueError as exc:
        raise RepoError(f"config.json is not valid JSON: {exc}")
    ld = dict(DEFAULTS)
    ld.update(cfg.get("local_developer") or {})
    for key in ("max_attempts", "max_output_tokens", "max_output_tokens_retry", "num_ctx"):
        if not isinstance(ld[key], int) or isinstance(ld[key], bool) or ld[key] < 1:
            raise RepoError(f"local_developer.{key} must be an integer >= 1")
    for key in ("attempt_timeout_min", "total_timeout_min"):
        if not isinstance(ld[key], (int, float)) or isinstance(ld[key], bool) or ld[key] <= 0:
            raise RepoError(f"local_developer.{key} must be a number > 0")
    if ld["lint_cmd"] is None:
        ld["lint_cmd"] = (cfg.get("commands") or {}).get("lint")
    return ld


def as_cmd_list(value):
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    return [v for v in value if isinstance(v, str) and v]


def estimate_tokens(text):
    """Conservative: ~3 chars/token for ASCII, 1 token per non-ASCII char (CJK runs near 1:1)."""
    non_ascii = sum(1 for ch in text if ord(ch) > 127)
    return (len(text) - non_ascii) // 3 + non_ascii


def state_dir(repo):
    return os.path.join(repo, ".claude", "guild", "memory", "local-dev")


def issue_dir(repo, issue):
    return os.path.join(state_dir(repo), str(issue))


def current_branch(repo):
    return git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()


def job_paths(repo, issue):
    """Job folders of this Issue, newest first (job ids sort by creation time to the ns)."""
    d = issue_dir(repo, issue)
    if not os.path.isdir(d):
        return []
    names = [n for n in os.listdir(d) if os.path.isfile(os.path.join(d, n, "job.json"))]
    return [os.path.join(d, n) for n in sorted(names, reverse=True)]


def find_job(repo, issue, include_consumed=False):
    """The newest job of this Issue on the current branch (None when there is none)."""
    branch = current_branch(repo)
    for jd in job_paths(repo, issue):
        try:
            job = read_json(os.path.join(jd, "job.json"))
        except ValueError:
            continue
        if job.get("branch") != branch:
            continue
        if job.get("consumed") and not include_consumed:
            return None          # the newest job on this branch was already acted on
        return job
    return None


def files_digest(repo, files):
    h = hashlib.sha256()
    for f in files:
        h.update(f.encode() + b"\0")
        try:
            with open(os.path.join(repo, f), "rb") as fh:
                h.update(fh.read())
        except FileNotFoundError:
            h.update(b"<missing>")
        h.update(b"\0")
    return h.hexdigest()


def originals_equal(repo, job):
    jd = os.path.join(repo, job["job_dir"])
    for f in job["files"]:
        with open(os.path.join(jd, "originals", f), "rb") as a, open(os.path.join(repo, f), "rb") as b:
            if a.read() != b.read():
                return False
    return True


def public(repo, job):
    keys = ("job_id", "issue", "state", "reason", "queue_wait_s", "active_s", "evidence",
            "last_diff", "files", "tests", "consumed")
    out = {k: job.get(k) for k in keys if k in job}
    out["attempts"] = [{k: a.get(k) for k in ("n", "outcome", "gen_s", "output_tokens",
                                              "num_predict", "think")}
                       for a in job.get("attempts") or []]
    out["attempt_count"] = len(job.get("attempts") or [])
    out["job_dir"] = job.get("job_dir")
    if job.get("consumed") and job.get("state") == "local_pass":
        # true only while the acked local code is untouched AND has not been sent back yet:
        # the exemption it grants (Step 4, a local pass sent back) is spent by the first note
        out["local_code_in_tree"] = bool(job.get("ack_digest")) and not job.get("sent_back") \
            and files_digest(repo, job["files"]) == job["ack_digest"]
    if job.get("state") == "local_pass":
        if git(repo, "status", "--porcelain", "--", *job["files"]).strip():
            out["tree"] = "uncommitted"
        elif originals_equal(repo, job):
            out["tree"] = "restored"
        else:
            out["tree"] = "committed"
    return out


def append_line(repo, rec):
    os.makedirs(state_dir(repo), exist_ok=True)
    with open(os.path.join(state_dir(repo), "runs.jsonl"), "a", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def append_run(repo, job, cfg):
    append_line(repo, {
        "type": "run", "ts": now_iso(), "issue": job["issue"], "job_id": job["job_id"],
        "branch": job.get("branch"), "attended": job.get("attended"),
        "model": cfg.get("model"), "final": job["state"], "reason": job.get("reason"),
        "queue_wait_s": round(job.get("queue_wait_s") or 0, 1),
        "active_s": round(job.get("active_s") or 0, 1),
        "files": job.get("files"), "tests": job.get("tests"),
        "attempts": job.get("attempts") or [],
        "config": {k: cfg.get(k) for k in ("max_attempts", "max_output_tokens",
                                           "max_output_tokens_retry", "attempt_timeout_min",
                                           "total_timeout_min", "num_ctx")},
    })


# --------------------------------------------------------------------------- queue

class Queue:
    """First-come-first-served tickets across every repo on this machine.

    A ticket is a file whose owner holds an flock on it for as long as it waits or runs; a
    ticket nobody holds belongs to a dead process and is removed by whoever sees it."""

    def __init__(self):
        self.dir = os.environ.get("GLD_LOCAL_DEV_QUEUE_DIR") or os.path.join(
            os.path.expanduser("~"), ".cache", "guild", "local-dev-queue")
        os.makedirs(self.dir, exist_ok=True)
        self.lock_path = os.path.join(self.dir, "model.lock")
        self.held = {}             # ticket name -> fd holding its lock

    def take(self, label):
        name = f"{time.time_ns():020d}-{os.getpid()}-{secrets.token_hex(3)}.ticket"
        # Locked under a name live() never reads, THEN renamed into place: a ticket that is
        # visible but not yet locked would read as dead and be unlinked by another process.
        tmp = os.path.join(self.dir, name + ".new")
        fd = os.open(tmp, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX)
        os.write(fd, json.dumps({"pid": os.getpid(), "label": label, "ts": now_iso()}).encode())
        os.rename(tmp, os.path.join(self.dir, name))
        self.held[name] = fd
        return name

    def live(self):
        out = []
        for name in sorted(os.listdir(self.dir)):
            if name.endswith(".ticket.new"):
                try:      # an abandoned half-made ticket (its maker died before the rename)
                    if time.time() - os.path.getmtime(os.path.join(self.dir, name)) > 60:
                        fd = try_lock(os.path.join(self.dir, name))
                        if fd is not None:
                            os.unlink(os.path.join(self.dir, name))
                            os.close(fd)
                except FileNotFoundError:
                    pass
                continue
            if not name.endswith(".ticket"):
                continue
            if name in self.held:
                out.append(name)
                continue
            path = os.path.join(self.dir, name)
            try:
                fd = os.open(path, os.O_RDWR)
            except FileNotFoundError:
                continue
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                out.append(name)              # someone holds it: alive
            else:
                try:
                    os.unlink(path)           # nobody holds it: its owner is gone
                except FileNotFoundError:
                    pass
            finally:
                os.close(fd)
        return out

    def others(self, mine=None):
        return [t for t in self.live() if t != mine]

    def leave(self, name):
        fd = self.held.pop(name, None)
        try:
            os.unlink(os.path.join(self.dir, name))
        except FileNotFoundError:
            pass
        if fd is not None:
            os.close(fd)


# --------------------------------------------------------------------------- start

def check_server(cfg):
    """None when the model is servable, else the fallback reason."""
    try:
        with urllib.request.urlopen(cfg["ollama_url"].rstrip("/") + "/api/tags", timeout=5) as r:
            tags = json.load(r)
    except (urllib.error.URLError, OSError, ValueError):
        return "server_down"
    names = {m.get("name") for m in tags.get("models") or []}
    model = cfg["model"]
    if model in names or (":" not in model and f"{model}:latest" in names):
        return None
    return "ineligible:model_not_pulled"


def normalize(repo, paths):
    """Repo-relative, normalized paths; None for one that escapes the repo."""
    real_repo = os.path.realpath(repo)
    out = []
    for p in paths:
        if os.path.isabs(p):
            return None, p
        rp = os.path.realpath(os.path.join(repo, p))
        if not rp.startswith(real_repo + os.sep):
            return None, p
        out.append(os.path.relpath(rp, real_repo))
    return out, None


def eligibility(repo, cfg, args):
    """(reason, context) — reason None means eligible. Mutates args.files/args.tests to the
    normalized form so every later comparison is on one spelling."""
    if not cfg.get("enabled"):
        return "ineligible:disabled", {}
    if not cfg.get("model"):
        return "ineligible:no_model_configured", {}
    if not as_cmd_list(cfg.get("test_cmd")) or not any("{files}" in c for c in as_cmd_list(cfg["test_cmd"])):
        return "ineligible:no_test_cmd", {}
    files, badf = normalize(repo, args.files)
    if files is None:
        return f"ineligible:file_outside_repo:{badf}", {}
    tests, badt = normalize(repo, args.tests)
    if tests is None:
        return f"ineligible:test_outside_repo:{badt}", {}
    args.files, args.tests = files, tests
    for f in files:
        if f.startswith(".claude" + os.sep) or f == ".claude" or f in tests:
            return f"ineligible:file_not_allowed:{f}", {}
        if os.path.islink(os.path.join(repo, f)) or not os.path.isfile(os.path.join(repo, f)):
            return f"ineligible:file_missing:{f}", {}
        try:
            with open(os.path.join(repo, f), encoding="utf-8", newline="") as fh:
                fh.read()
        except UnicodeDecodeError:
            return f"ineligible:not_utf8:{f}", {}
    for t in tests:
        if not os.path.isfile(os.path.join(repo, t)):
            return f"ineligible:test_missing:{t}", {}
        # committed or staged: a pre-commit hook that runs the test suite refuses a commit of
        # red tests, so they may wait in the index and go into the leader's commit of the pass
        if git(repo, "ls-files", "--error-unmatch", "--", t, check=False) == "":
            return f"ineligible:test_untracked:{t}", {}
        # the model is checked against the working tree, the leader commits the index: they
        # must be the same tests
        if git(repo, "-c", "core.fileMode=false", "diff", "--name-only", "--", t).strip():
            return f"ineligible:tests_unstaged:{t}", {}
    mb = git(repo, "merge-base", args.base, "HEAD", check=False).strip()
    if not mb:
        return "ineligible:no_merge_base", {}
    if not git(repo, "diff", mb, "--", *tests).strip():
        return "ineligible:tests_unchanged_vs_base", {}
    if git(repo, "status", "--porcelain", "--", *files).strip():
        return "ineligible:uncommitted_changes", {}
    # without the skeleton the model has only the tests to go on — measured on a real repo it
    # then reasons until max_output_tokens on every attempt (2026-11, 9 of 9 output_cap)
    skeleton_path = os.path.join(repo, "docs", "specs", str(args.issue), "skeleton.md")
    if not os.path.isfile(skeleton_path):
        return "ineligible:no_skeleton", {}
    with open(skeleton_path, encoding="utf-8") as fh:
        skeleton = fh.read()
    if not skeleton.strip():
        return "ineligible:no_skeleton", {}
    text = SYSTEM + skeleton + (args.note or "") + git(repo, "diff", mb, "--", *tests)
    for f in files:
        with open(os.path.join(repo, f), encoding="utf-8") as fh:
            text += fh.read()
    # a retry repeats the whole prompt plus the failure output — it must fit at the first cap
    room = cfg["num_ctx"] - estimate_tokens(text) - FEEDBACK_CHARS - 1000
    if room < cfg["max_output_tokens"]:
        return "ineligible:context_too_large", {}
    # what is left goes to the raised cap and the reasoning carry (chars count as at least one
    # token each), the carry first: it is what turned a cut-off job into a pass (2026-11). A
    # config that leaves too little for either gets less, never an error — an old num_ctx keeps
    # working as it did before both existed
    retry_cap = max(cfg["max_output_tokens"], min(cfg["max_output_tokens_retry"], room - CARRY_CHARS))
    carry = min(CARRY_CHARS, room - retry_cap)
    return None, {"mb": mb, "skeleton_path": skeleton_path, "retry_cap": retry_cap,
                  "carry_chars": carry if carry >= MIN_CARRY_CHARS else 0}


def new_job_id():
    t = time.time_ns()
    return datetime.datetime.fromtimestamp(t / 1e9).strftime("%Y%m%d-%H%M%S-") + f"{t % 10**9:09d}"


def cmd_start(repo, args):
    cfg = load_config(repo)
    d = issue_dir(repo, args.issue)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, ".start.lock"), "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        existing = find_job(repo, args.issue)
        if existing:                       # a resumed leader re-runs start: never a 2nd job
            emit(public(repo, settle_dead(repo, existing, cfg)))
            return 0
        jd = os.path.join(d, new_job_id())
        os.makedirs(jd)
        # The worker's liveness lock exists before job.json does, so no reader can ever see this
        # job with a free lock while it is being started; it is handed down to the worker.
        wfd = try_lock(os.path.join(jd, "worker.lock"))
        job = {
            "job_id": os.path.basename(jd), "issue": args.issue, "job_dir": os.path.relpath(jd, repo),
            "branch": current_branch(repo), "head": git(repo, "rev-parse", "HEAD").strip(),
            "base": args.base, "files": args.files, "tests": args.tests, "note": args.note,
            "attended": bool(args.attended), "created": now_iso(), "state": "queued",
            "attempts": [], "queue_wait_s": 0.0, "active_s": 0.0, "consumed": False,
        }
        reason, ctx = eligibility(repo, cfg, args)
        job.update(files=args.files, tests=args.tests)
        if reason is None:
            reason = check_server(cfg)
        attended_ticket = None
        queue = Queue() if reason is None else None
        if reason is None and args.attended:
            if queue.others():
                reason = "queue_busy"
            else:                          # hold the model for the whole attended job
                attended_ticket = queue.take(f"{repo}#{args.issue} (attended)")
                if queue.live()[:1] != [attended_ticket]:   # someone got in first meanwhile
                    queue.leave(attended_ticket)
                    attended_ticket, reason = None, "queue_busy"
        if reason:
            job.update(state="fallback", reason=reason, finished=now_iso())
            write_json(os.path.join(jd, "job.json"), job)
            os.close(wfd)
            append_run(repo, job, cfg)
            emit(public(repo, job))
            return 0
        job.update(mb=ctx["mb"], skeleton_path=ctx["skeleton_path"], retry_cap=ctx["retry_cap"],
                   carry_chars=ctx["carry_chars"])
        for f in args.files + args.tests:
            dst = os.path.join(jd, "originals" if f in args.files else "test-originals", f)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(os.path.join(repo, f), "rb") as src, open(dst, "wb") as out:
                out.write(src.read())
        write_json(os.path.join(jd, "job.json"), job)
        pass_fds = [wfd]
        env = dict(os.environ, GLD_LOCAL_DEV_WORKER_FD=str(wfd))
        if attended_ticket:
            tfd = queue.held[attended_ticket]
            pass_fds.append(tfd)
            env.update(GLD_LOCAL_DEV_TICKET=attended_ticket, GLD_LOCAL_DEV_TICKET_FD=str(tfd))
        with open(os.path.join(jd, "worker.log"), "ab") as log:
            subprocess.Popen([sys.executable, os.path.abspath(__file__), "_worker", jd],
                             cwd=repo, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                             start_new_session=True, pass_fds=pass_fds, env=env)
        os.close(wfd)                      # the worker's copy keeps the lock
        if attended_ticket:
            os.close(queue.held.pop(attended_ticket))
        emit(public(repo, job))
        return 0


# --------------------------------------------------------------------------- worker

def restore(repo, jd, files):
    for f in files:
        with open(os.path.join(jd, "originals", f), "rb") as src:
            data = src.read()
        with open(os.path.join(repo, f), "wb") as out:
            out.write(data)


def restore_changed_tests(repo, jd, tests):
    """Put back any test whose bytes differ from the start of the job; True when one did.
    Jobs started before test copies were kept have none to compare — nothing changes."""
    changed = False
    for t in tests:
        src = os.path.join(jd, "test-originals", t)
        if not os.path.exists(src):
            continue
        with open(src, "rb") as fh:
            data = fh.read()
        cur = os.path.join(repo, t)
        if not os.path.exists(cur) or open(cur, "rb").read() != data:
            if os.path.exists(cur):        # what changed it is kept, never just overwritten
                keep = os.path.join(jd, "tests-changed", t)
                os.makedirs(os.path.dirname(keep), exist_ok=True)
                with open(cur, "rb") as fh, open(keep, "wb") as out:
                    out.write(fh.read())
            os.makedirs(os.path.dirname(cur) or ".", exist_ok=True)
            with open(cur, "wb") as out:
                out.write(data)
            changed = True
    return changed


def save_diff(repo, jd, files):
    diff = git(repo, "diff", "HEAD", "--", *files, check=False)
    with open(os.path.join(jd, "last-local.diff"), "w", encoding="utf-8") as fh:
        fh.write(diff)


def settle_dead(repo, job, cfg):
    """A non-terminal job whose worker is gone becomes a fallback (files restored).

    The worker holds worker.lock for its whole life; taking it proves the worker is gone and
    makes this caller the only settler."""
    if job["state"] in TERMINAL:
        return job
    jd = os.path.join(repo, job["job_dir"])
    fd = try_lock(os.path.join(jd, "worker.lock"))
    if fd is None:
        return job                         # alive
    try:
        fresh = read_json(os.path.join(jd, "job.json"))
        if fresh["state"] in TERMINAL:
            return fresh
        save_diff(repo, jd, fresh["files"])
        restore(repo, jd, fresh["files"])
        restore_changed_tests(repo, jd, fresh.get("tests", []))
        fresh.update(state="fallback", reason="worker_died", finished=now_iso(),
                     last_diff=os.path.relpath(os.path.join(jd, "last-local.diff"), repo))
        write_json(os.path.join(jd, "job.json"), fresh)
        append_run(repo, fresh, cfg)
        return fresh
    finally:
        os.close(fd)


def drop_tokens(text, n):
    """`text` without the shortest head whose estimate_tokens is at least `n`."""
    units = 0                              # thirds of a token, as estimate_tokens counts
    for i, ch in enumerate(text):
        if units >= 3 * n:
            return text[i:]
        units += 3 if ord(ch) > 127 else 1
    return ""


def with_checked(checked, note):
    """A note about a cut-off or failed call, after what the last check said about the edits
    still in the files — within the same FEEDBACK_CHARS."""
    room = FEEDBACK_CHARS - len(note) - 2
    if not checked or room <= 0:
        return note[:FEEDBACK_CHARS]
    return checked[-room:] + "\n\n" + note


def build_prompt(repo, job, feedback=None, carry=None):
    parts = [f"## Task\nIssue #{job['issue']} — implement against the skeleton so the new "
             f"tests pass."]
    if job.get("note"):
        parts.append("## Note from the test author\n" + job["note"])
    if job.get("skeleton_path"):
        with open(job["skeleton_path"], encoding="utf-8") as fh:
            parts.append("## Design skeleton\n" + fh.read())
    parts.append("## New/changed tests (diff vs base)\n```diff\n"
                 + git(repo, "diff", job["mb"], "--", *job["tests"]) + "\n```")
    for f in job["files"]:
        with open(os.path.join(repo, f), encoding="utf-8") as fh:
            parts.append(f"## Current implementation: {f}\n```\n" + fh.read() + "\n```")
    if feedback:
        parts.append("## Previous attempt failed\nThe files above already contain your previous "
                     "edits. Verification said:\n" + feedback
                     + "\n\nFix it with new SEARCH/REPLACE blocks against the CURRENT files.")
    if carry:
        parts.append("## Your analysis from the attempt that hit the output limit (its last "
                     "part — no edit of it was written)\n" + carry
                     + "\n\nDo not analyse again. Write the SEARCH/REPLACE blocks now, against the "
                     "CURRENT files above.")
    return "\n\n".join(parts)


def swallows(search, repl):
    """True when a REPLACE text looks like it holds the head of a further block."""
    s_marks = sum(1 for l in search.split("\n") if l.strip() == SEARCH_MARK)
    r_lines = repl.split("\n")
    r_marks = [n for n, l in enumerate(r_lines) if l.strip() == SEARCH_MARK]
    if len(r_marks) > s_marks:
        return True
    return any(l.rstrip() == DIVIDER for n in r_marks for l in r_lines[n + 1:])


def parse_blocks(text, marked=()):
    """[(path, [search candidates...], replace-candidates aligned)] from a reply.

    Line-based. The path is the nearest non-empty, non-fence line above `<<<<<<< SEARCH`.
    A body with several `=======` lines is ambiguous (a Markdown underline inside SEARCH), so
    every split is kept as a candidate and apply_blocks takes the one that matches once.

    A reasoning model run with reasoning off may still reason inline, drafting blocks before a
    `</think>` line and writing them again after it — only the part after the last such line
    counts when it holds blocks. A line ending in `</think>` is that cut unless it sits inside a
    closed block body (the nearest marker above is a SEARCH, the nearest below a REPLACE), so
    code that contains the tag is edited like any other while a draft left unclosed, or a
    `</think>` glued to a line of prose, still cuts. (Prose in the final answer that ends with
    the tag cuts too — the blocks before it are lost and the tests catch what they did.)

    A SEARCH line before a block's REPLACE is ambiguous — code inside the block, or a new block
    after an unfinished draft — and no reading of it is safe in general (each guess was shown to
    write one block's text into another file). It is read as code only in the one case the file
    itself settles: the file holds such a line (`marked`) and the marker is in the SEARCH text (a
    divider below it), so the SEARCH must match the file, marker included. Any other block with
    a SEARCH line inside is refused with a message asking for each block once, complete — an
    attempt is spent, never wrong code written. (Measured 2026-11: no real reply needed more —
    the drafts it wrote all stood before a `</think>` line, which the cut above handles.) Read
    as code, a replacement holding a marker that could open a further block (more markers than
    the SEARCH, or one with a divider below it) is refused too — so a few genuine edits to such
    an example are refused, and a swallowed draft with no divider of its own is
    indistinguishable from an edit that adds a marker line and is applied as written.

    A block repeated verbatim is the same edit stated twice (measured 2026-11: the second copy
    failed to match and sank a reply that passed every test once deduplicated), so only its
    first occurrence is kept."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    kinds = [l.strip() if l.strip() in (SEARCH_MARK, REPLACE_MARK) else None for l in lines]
    prev_mark, nxt, search_after = [None] * len(lines), [None] * len(lines), [False] * len(lines)
    m = None
    for n, kind in enumerate(kinds):
        prev_mark[n], m = m, kind or m
    m, seen = None, False
    for n in range(len(lines) - 1, -1, -1):
        nxt[n], search_after[n] = m, seen
        m = kinds[n] or m
        seen = seen or kinds[n] == SEARCH_MARK
    cut = None
    for n, line in enumerate(lines):
        if kinds[n] or not line.rstrip().endswith(THINK_END):
            continue
        if prev_mark[n] == SEARCH_MARK and nxt[n] == REPLACE_MARK:
            continue                       # inside a closed block body: it is code
        if search_after[n]:
            cut = n
    if cut is not None:
        lines, kinds = lines[cut + 1:], kinds[cut + 1:]
    blocks, i, last_path = [], 0, None     # last_path: every parsed block's, duplicates too
    while i < len(lines):
        if kinds[i] != SEARCH_MARK:
            i += 1
            continue
        k = i - 1
        while k >= 0 and (not lines[k].strip() or FENCE_RE.match(lines[k])):
            k -= 1
        if k >= 0 and kinds[k] == REPLACE_MARK and last_path is not None:
            path = last_path               # a second block for the same file, name not repeated
        else:
            path = lines[k].strip().strip("`").strip() if k >= 0 else ""
        j = i + 1
        while j < len(lines) and kinds[j] != REPLACE_MARK:
            j += 1
        inner = next((x for x in range(i + 1, j) if kinds[x] == SEARCH_MARK), None)
        if inner is not None and not (
                path in marked and j < len(lines)
                and any(l.rstrip() == DIVIDER for l in lines[inner + 1:j])):
            return None, (f"{'a block for ' + path[:200] if path else 'an unnamed block'} has another {SEARCH_MARK} line before its "
                          f"{REPLACE_MARK} — an unfinished draft? Write each block once, "
                          f"complete, with nothing drafted before it")
        if j >= len(lines):
            return None, "a SEARCH block is not closed by >>>>>>> REPLACE"
        body = lines[i + 1:j]
        divs = [n for n, l in enumerate(body) if l.rstrip() == DIVIDER
                and (inner is None or i + 1 + n > inner)]
        if not divs:
            return None, f"a block for {path[:200]} has no ======= divider"
        cands = [("\n".join(body[:n]), "\n".join(body[n + 1:])) for n in divs]
        if inner is not None:
            # read as code, a split must not carry a later block in as its REPLACE: no more
            # markers there than in its SEARCH, and no marker with a divider below it
            kept = [(a, b) for a, b in cands if not swallows(a, b)]
            if not kept:
                return None, (f"a block for {path[:200]} has a {SEARCH_MARK} line in its "
                              f"replacement that could start another block — ambiguous, so "
                              f"nothing was applied. If a block is unfinished, write each block "
                              f"once, complete; if the file's example really needs that line, "
                              f"make the edit in smaller blocks that leave it unchanged")
            cands = kept
        last_path = path
        if (path, cands) not in blocks:
            blocks.append((path, cands))
        i = j + 1
    if not blocks:
        return None, "no SEARCH/REPLACE blocks found"
    return blocks, None


def apply_blocks(repo, allowed, text):
    """All-or-nothing: (ok, message). Nothing is written unless every block applies.
    Files are read and written byte-exact in their own line-ending style."""
    current = {}
    for f in allowed:
        with open(os.path.join(repo, f), encoding="utf-8", newline="") as fh:
            current[f] = fh.read()
    marked = {f for f, c in current.items() if any(l.strip() == SEARCH_MARK for l in c.splitlines())}
    blocks, err = parse_blocks(text, marked)
    if err:
        return False, err
    ok, msg, pending = plan_blocks(allowed, current, blocks)
    if ok:
        for path, content in pending.items():
            with open(os.path.join(repo, path), "w", encoding="utf-8", newline="") as fh:
                fh.write(content)
    return ok, msg


def plan_blocks(allowed, current, blocks):
    """(ok, message, {path: new content}) — the edits applied in memory."""
    pending, crlf = {}, {}
    for path, cands in blocks:
        if path not in allowed:
            return False, (f"edit to a file outside the allowed set: {path[:200]!r} — the only "
                           f"editable files are {', '.join(allowed)}"), None
        if path not in pending:
            pending[path] = current[path]
            crlf[path] = "\r\n" in pending[path]
        cur = pending[path]
        chosen, counts = None, []
        for search, repl in cands:
            if crlf[path]:
                search, repl = search.replace("\n", "\r\n"), repl.replace("\n", "\r\n")
            if search == "":
                n = 1 if cur.strip() == "" else 0
            else:
                n = cur.count(search)
            counts.append(n)
            # several splits can match once; the longest SEARCH is the most specific reading
            if n == 1 and (chosen is None or len(search) > len(chosen[0])):
                chosen = (search, repl)
        if chosen is None:
            return False, f"SEARCH matched {counts[0]} times in {path}:\n{cands[0][0][:400]}", None
        search, repl = chosen
        pending[path] = repl if search == "" else cur.replace(search, repl, 1)
    return True, f"applied {len(blocks)} block(s) to {len(pending)} file(s)", pending


def kill_group(pid):
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def run_cmds(repo, cmds, budget_s):
    """(ok, output, timed_out, seconds, rc) for commands run in order; stops at the first failure.

    Output goes to a file, not a pipe: a test runner that leaves a background child holding
    stdout must not keep this call open past the runner's own exit."""
    out, t0, rc = [], time.monotonic(), 0
    for c in cmds:
        left = budget_s - (time.monotonic() - t0)
        if left <= 0:
            return False, "\n".join(out), True, time.monotonic() - t0, None
        with tempfile.TemporaryFile() as buf:
            p = subprocess.Popen(c, shell=True, cwd=repo, stdin=subprocess.DEVNULL, stdout=buf,
                                 stderr=subprocess.STDOUT, start_new_session=True)
            try:
                rc = p.wait(timeout=left)
                timed = False
            except subprocess.TimeoutExpired:
                timed = True
            kill_group(p.pid)              # leftovers of the run never outlive it
            if timed:
                p.wait()
            buf.seek(0)
            text = buf.read().decode("utf-8", "replace")
        if timed:
            out.append(f"$ {c}\n{text}\n[killed at the active-time budget]")
            return False, "\n".join(out), True, time.monotonic() - t0, None
        out.append(f"$ {c}\n{text}\n[exit {rc}]")
        if rc != 0:
            return False, "\n".join(out), False, time.monotonic() - t0, rc
    return True, "\n".join(out), False, time.monotonic() - t0, 0


def test_cmds(job, cfg):
    files = " ".join(shlex.quote(t) for t in job["tests"])
    return [c.replace("{files}", files) for c in as_cmd_list(cfg["test_cmd"])]


def chat(cfg, prompt, timeout_s, num_predict, think=None):
    req_body = {
        "model": cfg["model"], "stream": False,
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
        "options": {"num_ctx": cfg["num_ctx"], "num_predict": num_predict,
                    "temperature": 0.2},
    }
    if think is not None:                  # sent only to a model that showed it reasons
        req_body["think"] = think
    body = json.dumps(req_body).encode()
    req = urllib.request.Request(cfg["ollama_url"].rstrip("/") + "/api/chat", body,
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout_s) as r:
        return json.load(r)


class Worker:
    def __init__(self, jd):
        self.jd = jd
        self.repo = repo_root()
        self.cfg = load_config(self.repo)
        self.job = read_json(os.path.join(jd, "job.json"))
        self.job["worker_pid"] = os.getpid()
        self.queue = Queue()
        self.active = 0.0          # seconds of model calls + checks — never queue wait
        self.fixed_ticket = os.environ.get("GLD_LOCAL_DEV_TICKET")
        if self.fixed_ticket:      # an attended job: the ticket start took and handed down
            self.queue.held[self.fixed_ticket] = int(os.environ["GLD_LOCAL_DEV_TICKET_FD"])

    def save(self):
        self.job["active_s"] = round(self.active, 1)
        write_json(os.path.join(self.jd, "job.json"), self.job)

    def budget(self):
        return self.cfg["total_timeout_min"] * 60 - self.active

    def finish(self, state, reason=None):
        # the model cannot edit tests, but its checks run them and the lint command: a snapshot
        # filled in or a formatter's rewrite would change what the pass is judged by — put the
        # tests back as the test author left them, and do not call that a pass
        if restore_changed_tests(self.repo, self.jd, self.job["tests"]) and state == "local_pass":
            state, reason = "fallback", "tests_modified"
        if state == "fallback":
            save_diff(self.repo, self.jd, self.job["files"])
            restore(self.repo, self.jd, self.job["files"])
            self.job["last_diff"] = os.path.relpath(os.path.join(self.jd, "last-local.diff"),
                                                    self.repo)
        self.job.update(state=state, reason=reason, finished=now_iso())
        self.save()
        append_run(self.repo, self.job, self.cfg)
        if self.fixed_ticket:
            self.queue.leave(self.fixed_ticket)

    def wait_turn(self, ticket):
        """Block until `ticket` is the oldest live one; the wait is recorded, never active time."""
        t0 = time.monotonic()
        while True:
            live = self.queue.live()
            if live and live[0] == ticket:
                break
            if self.job["state"] != "queued":
                self.job["state"] = "queued"
                self.save()
            time.sleep(POLL_SECONDS)
        self.job["queue_wait_s"] = round(self.job.get("queue_wait_s", 0) + time.monotonic() - t0, 1)
        self.job["state"] = "running"
        self.save()

    def call_model(self, prompt):
        """(response dict | None, outcome-on-error, seconds) under the queue."""
        ticket = self.fixed_ticket or self.queue.take(f"{self.repo}#{self.job['issue']}")
        try:
            self.wait_turn(ticket)
            timeout = min(self.cfg["attempt_timeout_min"] * 60, self.budget())
            if timeout <= 0:
                return None, "total_timeout", 0.0
            with open(self.queue.lock_path, "w") as lk:
                fcntl.flock(lk, fcntl.LOCK_EX)
                t0 = time.monotonic()
                try:
                    d = chat(self.cfg, prompt, timeout, self.send, self.think)
                    return d, None, time.monotonic() - t0
                except (TimeoutError, OSError) as exc:  # socket timeout, refused, reset
                    secs = time.monotonic() - t0
                    if isinstance(exc, TimeoutError) or "timed out" in str(exc):
                        cap = self.cfg["attempt_timeout_min"] * 60
                        return None, ("attempt_timeout" if timeout >= cap else "total_timeout"), secs
                    return None, f"model_error:{type(exc).__name__}", secs
                except ValueError as exc:
                    return None, f"model_error:{exc.__class__.__name__}", time.monotonic() - t0
        finally:
            if not self.fixed_ticket:
                self.queue.leave(ticket)

    def checks(self):
        """(outcome, output) after an edit was applied."""
        lint = as_cmd_list(self.cfg["lint_cmd"]) if self.job.get("lint_baseline_ok") else []
        if lint:
            ok, out, timed, secs, _ = run_cmds(self.repo, lint, self.budget())
            self.active += secs
            if timed:
                return "total_timeout", out
            if not ok:
                return "lint_fail", out
        ok, out, timed, secs, _ = run_cmds(self.repo, test_cmds(self.job, self.cfg), self.budget())
        self.active += secs
        if timed:
            return "total_timeout", out
        return ("pass" if ok else "test_fail"), out

    def baseline(self):
        """The tests must be red before the model writes anything; lint is used only if green now."""
        lint = as_cmd_list(self.cfg["lint_cmd"])
        if lint:
            ok, _, timed, secs, _ = run_cmds(self.repo, lint, self.budget())
            self.active += secs
            if timed:
                return "total_timeout"
            self.job["lint_baseline_ok"] = ok
        ok, out, timed, secs, rc = run_cmds(self.repo, test_cmds(self.job, self.cfg), self.budget())
        self.active += secs
        with open(os.path.join(self.jd, "baseline.checks.txt"), "w", encoding="utf-8") as fh:
            fh.write(out)
        if timed:
            return "total_timeout"
        if ok:
            return "ineligible:tests_already_green"
        if rc in (126, 127):               # the shell could not run the command at all
            return "ineligible:test_cmd_not_runnable"
        return None

    def run(self):
        self.job["state"] = "running"
        self.save()
        reason = self.baseline()
        if reason:
            return self.finish("fallback", reason)
        if restore_changed_tests(self.repo, self.jd, self.job["tests"]):
            return self.finish("fallback", "tests_modified")   # before a single model call
        feedback = None
        # an attempt cut off at the output cap raises the cap for every later attempt: most
        # passes fit max_output_tokens, a few need more (measured 2026-11: 8 of 10 under 8k,
        # the rest 8.7k and 10.2k), and starting high lets a runaway hold the model for longer
        self.cap = self.cfg["max_output_tokens"]
        retry_cap = self.job.get("retry_cap", self.cfg["max_output_tokens_retry"])
        carry_chars = self.job.get("carry_chars", CARRY_CHARS)
        # a reasoning model cut off before writing any edit has usually reached its answer in
        # the reasoning (measured 2026-11: a fresh retry re-derived it and was cut off again),
        # so the next attempt gets that reasoning's tail and runs with reasoning off; like the
        # raised cap this sticks for the rest of the job
        # the carry stands beside the last verification feedback: an earlier attempt's edits
        # stay in the files, and what the tests said about them still holds
        self.think, carry, checked = None, None, None
        for n in range(1, self.cfg["max_attempts"] + 1):
            prompt = build_prompt(self.repo, self.job, feedback, carry)
            # earlier attempts' edits stay in the files, so a late prompt can outgrow what
            # eligibility measured: shorten the carry, then the cap, never overflow num_ctx
            over = (estimate_tokens(SYSTEM + prompt) + self.cap + FIT_MARGIN
                    - self.cfg["num_ctx"])
            while over > 0 and carry:
                carry = drop_tokens(carry, over)
                prompt = build_prompt(self.repo, self.job, feedback, carry or None)
                over = (estimate_tokens(SYSTEM + prompt) + self.cap + FIT_MARGIN
                        - self.cfg["num_ctx"])
            self.send = self.cap - max(0, over)
            if self.send < min(1000, self.cfg["max_output_tokens"]):
                self.job["attempts"].append({"n": n, "started": now_iso(), "outcome":
                                             "context_overflow", "num_predict": max(0, self.send),
                                             "over_tokens": over})
                return self.finish("fallback", "context_overflow")
            with open(os.path.join(self.jd, f"attempt{n}.prompt.txt"), "w", encoding="utf-8") as fh:
                fh.write(prompt)
            d, err, secs = self.call_model(prompt)
            self.active += secs
            rec = {"n": n, "gen_s": round(secs, 1), "started": now_iso(), "num_predict": self.send,
                   "think": self.think}
            if err == "total_timeout":
                self.job["attempts"].append({**rec, "outcome": err})
                return self.finish("fallback", err)
            if d is None:
                rec["outcome"] = err.split(":")[0]
                rec["error"] = err
                # a carry still pending is retried as it was, with the feedback it came with
                feedback = checked if carry else with_checked(
                    checked, f"The model call failed: {err}. Answer more briefly.")
            else:
                carry = None               # spent only once the model answered
                msg = d.get("message") or {}
                text = msg.get("content") or ""
                with open(os.path.join(self.jd, f"attempt{n}.response.txt"), "w",
                          encoding="utf-8") as fh:
                    fh.write((msg.get("thinking") or "") + "\n\n=====CONTENT=====\n" + text)
                rec.update(prompt_tokens=d.get("prompt_eval_count"),
                           output_tokens=d.get("eval_count"), done_reason=d.get("done_reason"))
                if d.get("done_reason") == "length":
                    rec["outcome"] = "output_cap"
                    self.cap = retry_cap
                    thinking = msg.get("thinking") or ""
                    if thinking.strip() and SEARCH_MARK not in text and carry_chars:
                        self.think, carry = False, thinking[-carry_chars:]
                        feedback = checked
                    else:
                        feedback = with_checked(checked, "Your answer hit the output limit before "
                                                "it finished. Reason less and output only the "
                                                "SEARCH/REPLACE blocks.")
                else:
                    ok, msg_ = apply_blocks(self.repo, self.job["files"], text)
                    if not ok:
                        rec.update(outcome="apply_fail", error=msg_[:EXCERPT_CHARS])
                        feedback = checked = f"Your edits could not be applied: {msg_}"[:FEEDBACK_CHARS]
                    else:
                        outcome, out = self.checks()
                        if restore_changed_tests(self.repo, self.jd, self.job["tests"]):
                            with open(os.path.join(self.jd, f"attempt{n}.checks.txt"), "w",
                                      encoding="utf-8") as fh:
                                fh.write(out)
                            rec["outcome"] = "tests_modified"
                            self.job["attempts"].append(rec)
                            return self.finish("fallback", "tests_modified")
                        with open(os.path.join(self.jd, f"attempt{n}.checks.txt"), "w",
                                  encoding="utf-8") as fh:
                            fh.write(out)
                        rec["outcome"] = outcome
                        if outcome == "pass":
                            with open(os.path.join(self.jd, "test-output.txt"), "w",
                                      encoding="utf-8") as fh:
                                fh.write(out)
                            self.job["evidence"] = os.path.relpath(
                                os.path.join(self.jd, "test-output.txt"), self.repo)
                            self.job["attempts"].append(rec)
                            return self.finish("local_pass")
                        rec["error"] = out[-EXCERPT_CHARS:]
                        if outcome == "total_timeout":
                            self.job["attempts"].append(rec)
                            return self.finish("fallback", "total_timeout")
                        feedback = checked = out[-FEEDBACK_CHARS:]
            self.job["attempts"].append(rec)
            self.save()
            if self.budget() <= 0:
                return self.finish("fallback", "total_timeout")
        return self.finish("fallback", "max_attempts")


def cmd_worker(jd):
    # GLD_LOCAL_DEV_WORKER_FD is the inherited worker.lock descriptor: never closed, so the lock
    # lives exactly as long as this process.
    w = Worker(jd)
    try:
        w.run()
    except Exception as exc:  # noqa: BLE001 — any crash must still hand the Issue back
        w.job["worker_error"] = f"{type(exc).__name__}: {exc}"
        try:
            w.finish("fallback", "worker_error")
        except Exception:     # noqa: BLE001
            pass
        raise
    return 0


# --------------------------------------------------------------------------- wait/status/…

def cmd_wait(repo, args):
    cfg = load_config(repo)
    deadline = time.monotonic() + max(0, args.max_seconds)
    while True:
        job = find_job(repo, args.issue)
        if job is None:
            emit({"issue": args.issue, "state": "none"})
            return 0
        job = settle_dead(repo, job, cfg)
        if job["state"] in TERMINAL or time.monotonic() >= deadline:
            emit(public(repo, job))
            return 0
        time.sleep(min(POLL_SECONDS, max(0.1, deadline - time.monotonic())))


def cmd_status(repo, args):
    job = find_job(repo, args.issue, include_consumed=args.last)
    if job is None:
        emit({"issue": args.issue, "state": "none"})
        return 0
    emit(public(repo, settle_dead(repo, job, load_config(repo))))
    return 0


def cmd_revert(repo, args):
    job = find_job(repo, args.issue)
    if job is None or job["state"] != "local_pass":
        emit({"issue": args.issue, "state": job["state"] if job else "none",
              "error": "only an un-acknowledged local_pass can be reverted"})
        return 0
    git(repo, "reset", "-q", "HEAD", "--", *job["files"], check=False)   # unstage
    restore(repo, os.path.join(repo, job["job_dir"]), job["files"])
    emit(public(repo, job))
    return 0


def cmd_ack(repo, args):
    job = find_job(repo, args.issue)
    if job is None or job["state"] not in TERMINAL:
        emit({"issue": args.issue, "state": job["state"] if job else "none",
              "error": "nothing terminal to acknowledge"})
        return 0
    if job["state"] == "local_pass" and public(repo, job).get("tree") == "committed":
        job["ack_digest"] = files_digest(repo, job["files"])   # what the leader committed
    job["consumed"] = True
    write_json(os.path.join(repo, job["job_dir"], "job.json"), job)
    emit(public(repo, job))
    return 0


def cmd_note(repo, args):
    job = find_job(repo, args.issue, include_consumed=True)
    if job:
        job["sent_back"] = True        # spends the local-pass exemption (status --last)
        write_json(os.path.join(repo, job["job_dir"], "job.json"), job)
    rec = {"type": "followup", "ts": now_iso(), "issue": args.issue,
           "job_id": job["job_id"] if job else None,
           "job_final": job["state"] if job else None, "event": args.event}
    append_line(repo, rec)
    emit(rec)
    return 0


def cmd_report(repo, args):
    path = os.path.join(state_dir(repo), "runs.jsonl")
    runs, followups = [], {}
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get("type") == "followup":
                    if r.get("job_final") == "local_pass":
                        followups[r["event"].split(":")[0]] = followups.get(r["event"].split(":")[0], 0) + 1
                else:
                    runs.append(r)
    finals, reasons, outcomes, pass_at, raised = {}, {}, {}, {}, {}
    wait = active = 0.0
    tokens = gen = 0.0
    for r in runs:
        finals[r["final"]] = finals.get(r["final"], 0) + 1
        if r["final"] == "fallback":
            parts = (r.get("reason") or "?").split(":")
            key = ":".join(parts[:2]) if parts[0] == "ineligible" else parts[0]
            reasons[key] = reasons.get(key, 0) + 1
        else:
            k = len(r.get("attempts") or [])
            pass_at[k] = pass_at.get(k, 0) + 1
        base_cap = (r.get("config") or {}).get("max_output_tokens")
        for a in r.get("attempts") or []:
            outcomes[a.get("outcome")] = outcomes.get(a.get("outcome"), 0) + 1
            if base_cap and (a.get("num_predict") or 0) > base_cap:
                raised[a.get("outcome")] = raised.get(a.get("outcome"), 0) + 1
            if a.get("output_tokens") and a.get("gen_s"):
                tokens += a["output_tokens"]
                gen += a["gen_s"]
        wait += r.get("queue_wait_s") or 0
        active += r.get("active_s") or 0
    warnings = []
    cfg = load_config(repo)
    if gen:
        # gen_s includes prompt processing, so this rate is a floor — the warning errs early
        rate = tokens / gen
        need = cfg["max_output_tokens_retry"] / rate
        if need > cfg["attempt_timeout_min"] * 60:
            warnings.append(f"max_output_tokens_retry {cfg['max_output_tokens_retry']} needs "
                            f"~{need / 60:.0f} min at the observed {rate:.1f} tok/s — over "
                            f"attempt_timeout_min {cfg['attempt_timeout_min']}")
    emit({"runs": len(runs), "final": finals, "fallback_reasons": reasons,
          "pass_at_attempt": {str(k): v for k, v in sorted(pass_at.items())},
          "attempt_outcomes": outcomes, "raised_cap_outcomes": raised,
          "observed_tok_per_s": round(tokens / gen, 1) if gen else None,
          "warnings": warnings, "after_pass": followups,
          "avg_queue_wait_s": round(wait / len(runs), 1) if runs else 0,
          "avg_active_s": round(active / len(runs), 1) if runs else 0})
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["_worker"] and len(argv) == 2:
        return cmd_worker(argv[1])
    ap = argparse.ArgumentParser(prog="local_dev.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start")
    s.add_argument("--issue", type=int, required=True)
    s.add_argument("--base", required=True)
    s.add_argument("--files", nargs="+", required=True)
    s.add_argument("--tests", nargs="+", required=True)
    s.add_argument("--attended", action="store_true")
    s.add_argument("--note", default=None)
    w = sub.add_parser("wait")
    w.add_argument("--issue", type=int, required=True)
    w.add_argument("--max-seconds", type=float, required=True)
    st = sub.add_parser("status")
    st.add_argument("--issue", type=int, required=True)
    st.add_argument("--last", action="store_true")
    for name in ("ack", "revert"):
        sub.add_parser(name).add_argument("--issue", type=int, required=True)
    nt = sub.add_parser("note")
    nt.add_argument("--issue", type=int, required=True)
    nt.add_argument("--event", required=True)
    sub.add_parser("report")
    try:
        args = ap.parse_args(argv)
    except SystemExit as exc:
        return 64 if exc.code else 0
    try:
        repo = repo_root()
        load_config(repo)      # every subcommand needs an initialized Guild and a valid block
        return {"start": cmd_start, "wait": cmd_wait, "status": cmd_status, "ack": cmd_ack,
                "revert": cmd_revert, "note": cmd_note, "report": cmd_report}[args.cmd](repo, args)
    except RepoError as exc:
        print(f"local_dev.py: {exc}", file=sys.stderr)
        return 65


if __name__ == "__main__":
    sys.exit(main())
