"""Detached run, Issue lock, resume (design §7.3, §4.3 format/resume, §5.1 quota wait, F4, I10) — U13.

  - The engine always runs detached, the 0.98.7 spawn_supervisor way (double fork, log
    file, rc file), outside the conversation's sandbox: launched through a
    `sandbox.excludedCommands` pattern or one `dangerouslyDisableSandbox` call (F4). The
    conversation only tails engine.log.
  - Issue lock = pid + start time. A live lock refuses dev/resume; a dead pid's lock is
    released automatically. One `/gld dev` per repository at a time (§7.3, Q12).
  - needs_human → record the state and EXIT. `/gld resume` starts a new engine.
  - `dev` with an existing state goes the resume way (no branch/worktree re-creation, I10).
  - resume: show the waiting reason and the §6.3 answers allowed for it (the human sits in
    the leader's seat), note → leader-decision.md, issue.md re-built each resume, §4.4-3
    applied, developer re-entry facts (I7).

Engine-local files of one Issue (all under the engine home `$GLD_ENGINE_HOME`, default
`~/.gld`, never under `/tmp/claude-<uid>` — §7.3, F4; `paths.py` is the layout):

    <home>/records/<owner>/<repo>/repo.lock             repository lock (this module)
    <home>/records/<owner>/<repo>/<N>/lock              Issue lock (this module)
    <home>/records/<owner>/<repo>/<N>/state.json        log.jsonl  engine.log  engine.rc
    <home>/records/<owner>/<repo>/<N>/leader-decision.md   answers given at resume (this module)
    <home>/records/<owner>/<repo>/<N>/runs/<step>/<attempt>/…   attempt folders
    <home>/tmp/<owner>/<repo>/<N>/…                     per-run temp folders
    <home>/cache/<owner>/<repo>/                        Guild cache (kept across Issues)
    <main checkout parent>/.gld-<repo>-<N>/            the Issue worktree, branch gld/<N>

A reset of one Issue removes `records/<owner>/<repo>/<N>/` and `tmp/<owner>/<repo>/<N>/`,
the worktree (`git worktree remove`) and the branch — never while a live lock is held.

Lock file: JSON {format, pid, started, issue, at}. `started` is the process start time as
`ps -o lstart=` prints it (LC_ALL=C) — a pid reused by another process has another start
time, so its lock counts as dead. A lock file that is not valid JSON is treated as held
for LOCK_CORRUPT_GRACE_S after its mtime (a writer may be between create and write), then
as dead.

Stage-1 answers (I10, interpretation — the report lists it): the §6.3 table, minus the
answers that need a planner (`replan`, `close-as-decided`, `approve`: stage 2). Mechanical
stops (security boundary, push checks, infra, engine-error …) accept `rerun` (after the
human fixed the cause) and `escalate`; `absolute-limit`, `format-mismatch`,
`stable-label` and `rule-unfillable` accept only `escalate` (nothing the engine may
lift). `escalate` keeps the Issue stopped (the human takes over outside the engine).

Stage 2 (scope §2.0, §2.7, V6): the row is codes.STAGE2_ALLOWED_ANSWERS (D17 — the human
gets no D4 narrowing; `replan` only with a done plan step, D8). apply_answer serves both
seats: `who=leader` applies a checked leader answer to a needs_leader stop (escalate →
needs_human with the D15 recommendation); a human cannot answer a needs_leader stop (D24 —
resume calls the leader again). plan-gate / done-gate reruns count in `state.counters`.

Stage 3 (stage-3 scope §2.12): the row is codes.STAGE3_ALLOWED_ANSWERS. `continue` at
irreversible-change / step-add-limit / step-removal-request / pr-review leaves the (done)
stopped step as it is; `skip` skips one catalog step; a leader `replan` may defer rows (back to
analyze). Not answers: pr_review_problem / dismiss_problem / apply_dismiss (E31, E32).

Stage 4 (H8, review-q0 D6): a third seat, `sprint` — the supervisor's automatic `rerun` of a quota stop
whose reset has passed, nothing else (sprint_rerun_problem; the engine checks it itself).
"""

import json
import os
import stat
import subprocess
import sys
import time

from . import codes, defaults, fsafe, statemachine, store

LOCK_FORMAT = 1
LOCK_CORRUPT_GRACE_S = 60
REPO_LOCK_NAME = "repo.lock"
LEADER_DECISION_FILE = "leader-decision.md"
NO_DECISION_TEXT = "No leader decision has been made for this Issue.\n"

A = codes.LeaderAnswer
R = codes.StopReason
STAGE2_ANSWERS = frozenset({A.REPLAN.value, A.CLOSE_AS_DECIDED.value, A.APPROVE.value})
ESCALATE_ONLY = frozenset({R.ABSOLUTE_LIMIT.value, R.FORMAT_MISMATCH.value, R.STABLE_LABEL.value,
                           R.RULE_UNFILLABLE.value,
                           # readiness T1: start refusals — never a state.stop; listed so no answer ever fits one
                           R.UNSUPPORTED_EPIC.value, R.OPEN_CLOSING_PR.value, R.DONE_UNCONFIRMED.value})
MECHANICAL_ANSWERS = (A.RERUN.value, A.ESCALATE.value)


class LockHeld(Exception):
    """A live engine holds the Issue (or repository) lock. `.pid`, `.started`."""

    def __init__(self, path, pid=None, started=None, issue=None, why="held by a live engine"):
        self.path = path
        self.pid = pid
        self.started = started
        self.issue = issue
        super().__init__(f"{path}: {why} (pid {pid}, started {started}, issue {issue})")


class AnswerRefused(ValueError):
    """The answer is not allowed for the current stop (the state is left unchanged)."""


# --- process identity ---------------------------------------------------------------

def process_start(pid):
    """The start time of `pid` as `ps -o lstart=` prints it, or None when there is no such process."""
    if isinstance(pid, bool) or not isinstance(pid, int) or pid < 1:
        return None
    env = {"PATH": "/bin:/usr/bin", "LC_ALL": "C", "LANG": "C"}
    try:
        r = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True,
                           timeout=10, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return None
    out = " ".join(r.stdout.split())
    return out if r.returncode == 0 and out else None


def is_alive(pid, started):
    """True when `pid` runs and (when `started` is known) started at that time."""
    if isinstance(pid, bool) or not isinstance(pid, int) or pid < 1:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    now = process_start(pid)
    if now is None:
        return False
    return started is None or now == started


# --- locks -------------------------------------------------------------------------

def repo_lock_path(paths):
    return os.path.join(paths.records, paths.owner, paths.name, REPO_LOCK_NAME)


def _read_lock(path):
    """(info dict or None, mtime). Raises fsafe.UnsafePath for a link / non-regular file."""
    st = os.lstat(path)
    if not stat.S_ISREG(st.st_mode):
        raise fsafe.UnsafePath(path, "the lock is not a regular file")
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            data = os.read(fd, 64 * 1024)
        finally:
            os.close(fd)
        info = json.loads(data.decode("utf-8"))
        if not isinstance(info, dict):
            info = None
    except (ValueError, UnicodeDecodeError):
        info = None
    return info, st.st_mtime


def _holder_alive(info, mtime, now):
    if info is None:
        return now - mtime < LOCK_CORRUPT_GRACE_S
    return is_alive(info.get("pid"), info.get("started"))


def _take(path, info, root, released):
    fsafe.make_dirs(os.path.dirname(path), root=root)
    fsafe.check_parents(path, root=root)
    data = (json.dumps(info, sort_keys=True) + "\n").encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    for _ in range(3):
        try:
            fd = os.open(path, flags, 0o600)
        except FileExistsError:
            try:
                held, mtime = _read_lock(path)
            except FileNotFoundError:
                continue
            if _holder_alive(held, mtime, time.time()):
                held = held or {}
                raise LockHeld(path, held.get("pid"), held.get("started"), held.get("issue")) from None
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
            released.append({"path": path, "pid": (held or {}).get("pid"),
                             "started": (held or {}).get("started"), "issue": (held or {}).get("issue")})
            continue
        try:
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        return
    raise LockHeld(path, why="lock contention (another engine is starting)")


def acquire_lock(paths):
    """Create the lock (pid + process start time) or raise LockHeld; release dead-pid locks.

    Takes the repository lock first (one engine per repository, §7.3 Q12), then the Issue
    lock. Returns {"pid", "started", "released": [dead locks removed]}.
    """
    pid = os.getpid()
    started = process_start(pid)
    if started is None:
        raise LockHeld(paths.lock, pid, None, paths.issue, why="cannot read this process's start time")
    info = {"format": LOCK_FORMAT, "pid": pid, "started": started, "issue": paths.issue,
            "at": store.now_ts()}
    root = store._root(paths)
    released = []
    _take(repo_lock_path(paths), info, root, released)
    try:
        _take(paths.lock, info, root, released)
    except BaseException:
        _drop(repo_lock_path(paths), pid)
        raise
    return {"pid": pid, "started": started, "released": released}


def _drop(path, pid):
    try:
        held, _ = _read_lock(path)
    except (FileNotFoundError, fsafe.UnsafePath):
        return False
    if held is None or held.get("pid") != pid:
        return False
    try:
        os.unlink(path)
    except FileNotFoundError:
        return False
    return True


def release_lock(paths, pid=None):
    """Remove the Issue lock and the repository lock when this process (or `pid`) holds them."""
    pid = os.getpid() if pid is None else pid
    a = _drop(paths.lock, pid)
    b = _drop(repo_lock_path(paths), pid)
    return a or b


def lock_holder(paths):
    """The live holder {pid, started, issue, path} of the Issue or repository lock, else None."""
    return _live_holder((paths.lock, repo_lock_path(paths)))


def _live_holder(lock_paths):
    for path in lock_paths:
        try:
            info, mtime = _read_lock(path)
        except FileNotFoundError:
            continue
        if _holder_alive(info, mtime, time.time()):
            info = info or {}
            return {"pid": info.get("pid"), "started": info.get("started"), "issue": info.get("issue"),
                    "path": path}
    return None


def acquire_sprint_lock(sp):
    """Stage 4 (H4): one supervisor per repository — the repository's sprint.lock, then the sprint's own lock, the
    same way as acquire_lock (pid + start time; a dead holder's is released). The repository lock of the ENGINES is
    never taken: a human may `dev` / `resume` between two members. `sp` = paths.SprintPaths. LockHeld otherwise."""
    pid = os.getpid()
    started = process_start(pid)
    if started is None:
        raise LockHeld(sp.lock, pid, None, sp.tracker, why="cannot read this process's start time")
    info = {"format": LOCK_FORMAT, "pid": pid, "started": started, "issue": sp.tracker, "at": store.now_ts()}
    root = store._root(sp)
    released = []
    _take(sp.repo_lock, info, root, released)
    try:
        _take(sp.lock, info, root, released)
    except BaseException:
        _drop(sp.repo_lock, pid)
        raise
    return {"pid": pid, "started": started, "released": released}


def release_sprint_lock(sp, pid=None):
    """Remove the two sprint locks when this process (or `pid`) holds them."""
    pid = os.getpid() if pid is None else pid
    a, b = _drop(sp.lock, pid), _drop(sp.repo_lock, pid)
    return a or b


def sprint_lock_holder(sp):
    """The live supervisor {pid, started, issue (its tracker), path} of this sprint or of the repository, else None."""
    return _live_holder((sp.lock, sp.repo_lock))


# --- detached run --------------------------------------------------------------------

def _open_log(log_file):
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    return os.open(log_file, flags, 0o600)


def _supervise(argv, log_file, rc_file, env, cwd):
    """Grandchild body: run argv with stdout/stderr → log_file, then write rc_file. Never returns."""
    code = 1
    try:
        devnull = os.open(os.devnull, os.O_RDONLY)
        log = _open_log(log_file)
        os.dup2(devnull, 0)
        os.dup2(log, 1)
        os.dup2(log, 2)
        try:
            p = subprocess.Popen(argv, stdin=0, stdout=1, stderr=2, env=env, cwd=cwd, close_fds=True)
            rc = p.wait()
        except OSError as e:
            os.write(2, f"engine could not start: {e}\n".encode())
            rc = 127
        root = os.path.dirname(rc_file)
        fsafe.write_text(rc_file, f"{rc}\n", root=root, mode=0o600)
        code = 0
    except BaseException as e:  # noqa: BLE001 — a supervisor must end without raising
        try:
            os.write(2, f"supervisor error: {e!r}\n".encode())
        except OSError:
            pass
    os._exit(code)


def spawn_detached(argv, log_file, rc_file, env=None, cwd=None):
    """Double-fork the engine; return the grandchild pid (§7.3).

    The grandchild (a small supervisor in its own session) runs `argv` with stdin
    /dev/null and stdout/stderr appended to `log_file`, waits, and writes the exit code
    to `rc_file` (an existing rc file is removed first, so "no rc file" = still running).
    The caller returns at once.
    """
    argv = [str(a) for a in argv]
    if not argv or not os.path.isabs(argv[0]):
        raise ValueError("spawn_detached needs an absolute executable path first")
    for f in (log_file, rc_file):
        if not os.path.isabs(f):
            raise ValueError(f"not an absolute path: {f!r}")
    try:
        os.unlink(rc_file)
    except FileNotFoundError:
        pass
    env = dict(os.environ if env is None else env)
    r, w = os.pipe()
    pid = os.fork()
    if pid == 0:  # child
        try:
            os.close(r)
            os.setsid()
            pid2 = os.fork()
            if pid2 == 0:  # grandchild
                os.close(w)
                _supervise(argv, log_file, rc_file, env, cwd)
            os.write(w, str(pid2).encode())
            os.close(w)
        finally:
            os._exit(0)
    os.close(w)
    chunks = []
    while True:
        b = os.read(r, 64)
        if not b:
            break
        chunks.append(b)
    os.close(r)
    os.waitpid(pid, 0)
    try:
        return int(b"".join(chunks).decode())
    except ValueError:
        raise OSError("the detached engine did not start") from None


def read_rc(paths):
    """The engine exit code from engine.rc, or None while the detached engine still runs."""
    try:
        text = fsafe.read_bytes(paths.engine_rc, root=store._root(paths), max_bytes=64).decode().strip()
    except FileNotFoundError:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def engine_command_pattern(plugin_root):
    """The excludedCommands pattern to show in the self-check hint, e.g. `python3 -I <root>/…/engine.py:*`."""
    if not isinstance(plugin_root, str) or not os.path.isabs(plugin_root):
        raise ValueError(f"plugin root must be absolute: {plugin_root!r}")
    script = os.path.join(plugin_root, "skills", "gld", "engine", "engine.py")
    return f"python3 -I {script}:*"


def engine_argv(plugin_root, args):
    """[python3, -I, <plugin>/skills/gld/engine/engine.py, *args] for the detached engine."""
    script = os.path.join(plugin_root, "skills", "gld", "engine", "engine.py")
    return [sys.executable, "-I", script, *args]


# --- resume ------------------------------------------------------------------------------

def allowed_answers(reason, state=None, stage=1, soft_answered=False):
    """The answers a human may give for stop `reason` in this stage (see the module docstring).

    The row is codes.allowed_answers_table(stage)[reason] (stage 2: the §6.3 table with
    replan / close-as-decided / approve and the plan-gate rerun — D3, D17; no D4 narrowing).
    Stage 2 also drops `replan` while the plan step is not done (D8: replan = back_to plan,
    which needs a done plan — otherwise an earlier stopped step would block the run)."""
    if reason not in codes.StopReason.values():
        raise ValueError(f"unknown stop reason {reason!r}")
    if reason in ESCALATE_ONLY:
        return [A.ESCALATE.value]
    table = codes.allowed_answers_table(stage)
    if reason in table:
        out = list(table[reason])
    else:
        out = list(MECHANICAL_ANSWERS)
    if stage < 2:
        out = [a for a in out if a not in STAGE2_ANSWERS]
    once = (R.ON_FAIL_EXCEEDED.value, R.SOFT_BUDGET.value)
    if reason in once and A.RERUN.value in out:
        used = soft_answered if reason == R.SOFT_BUDGET.value else any(
            s.get("on_fail_extra", 0) for s in (state or {}).get("steps", ()))
        if used:
            out.remove(A.RERUN.value)
    if A.REPLAN.value in out and not _plan_done(state):
        out.remove(A.REPLAN.value)
    if reason == R.BLOCKED.value and A.CLOSE_AS_DECIDED.value in out and not statemachine.close_allowed(state):
        out.remove(A.CLOSE_AS_DECIDED.value)                  # K8-3: never once a developer step has run
    return out


def _plan_done(state):
    for s in (state or {}).get("steps", ()):
        if s["id"] == defaults.REPLAN_TARGET:
            return s["status"] == codes.StepStatus.DONE.value
    return False


def running_step(state):
    for s in state.get("steps") or ():
        if s["status"] == codes.StepStatus.RUNNING.value:
            return s["id"]
    return None


def pending_question(state, stage=1, soft_answered=False):
    """For resume: {reason, step, allowed_answers, note} of the current stop.

    Also `status`, `attempt`, `at`, `crashed`. A state without a stop whose step is still
    `running` is an engine that died mid-step (S9): `crashed` true, no answer needed —
    resume reruns that step. None when nothing waits (finished, or simply not running).
    """
    stop = state.get("stop")
    if stop:
        return {"reason": stop["reason"], "status": stop["status"], "step": stop.get("step"),
                "attempt": stop.get("attempt"), "at": stop.get("at"), "note": stop.get("note"),
                "allowed_answers": allowed_answers(stop["reason"], state, stage, soft_answered),
                "crashed": False,
                "leader_turn": stop["status"] == codes.StepStatus.NEEDS_LEADER.value,
                "recommendation": stop.get("recommendation"), "leader_failed": stop.get("leader_failed")}
    run = running_step(state)
    if run is not None:
        return {"reason": None, "status": codes.StepStatus.RUNNING.value, "step": run, "attempt": None,
                "at": None, "note": "the engine stopped while this step was running",
                "allowed_answers": [], "crashed": True, "leader_turn": False,
                "recommendation": None, "leader_failed": None}
    return None


def recover_crashed(state):
    """S9: the step left `running` by a dead engine goes back to pending. Returns log events.

    The attempt folder stays as evidence; the next attempt gets the next number
    (store.new_attempt skips past it). Counters are kept.
    """
    events = []
    if state.get("stop"):
        return events
    for s in state.get("steps") or ():
        if s["status"] == codes.StepStatus.RUNNING.value:
            s["status"] = codes.StepStatus.PENDING.value
            s["output_format_retries"] = s.get("output_format_retries", 0)
            events.append((codes.LogEvent.STATUS.value,
                           {"step": s["id"], "attempt": s.get("latest_attempt"), "from": "running",
                            "to": "pending", "note": "the engine stopped while the step was running; rerun"}))
    return events


def leader_decision_path(paths):
    return os.path.join(paths.issue_dir, LEADER_DECISION_FILE)


def read_leader_decision(paths):
    """leader-decision.md text for the next attempt's in/ (NO_DECISION_TEXT when none yet)."""
    try:
        return fsafe.read_bytes(leader_decision_path(paths), root=store._root(paths),
                                max_bytes=1024 * 1024).decode("utf-8")
    except FileNotFoundError:
        return NO_DECISION_TEXT


def _write_decision(paths, entry, stage=1):
    old = read_leader_decision(paths)
    if old == NO_DECISION_TEXT:
        who = ("Stage 1 has no leader: a human answered in the leader's seat (resume)." if stage < 2 else
               "The leader answered, or a human in the leader's seat (resume).")
        old = (f"Leader decisions\n================\n\n{who} Newest last. "
               "The engine never branches on the note.\n")
    text = old.rstrip("\n") + "\n\n" + entry.rstrip("\n") + "\n"
    root = store._root(paths)
    fsafe.make_dirs(paths.issue_dir, root=root)
    fsafe.write_text(leader_decision_path(paths), text, root=root, mode=0o600)


def _sstep(state, step_id):
    for s in state["steps"]:
        if s["id"] == step_id:
            return s
    raise AnswerRefused(f"step {step_id!r} is not in this Issue's procedure")


HUMAN = codes.Actor.HUMAN.value
LEADER = codes.Actor.LEADER.value
SPRINT = codes.Actor.SPRINT.value
CLOSED_AS_DECIDED = "closed-as-decided"
"""`steps[].reason` of the steps a close-as-decided answer skipped (D18, §5 "skipped needs a reason")."""

_CHECK_ANSWERS = {A.PLAN.value: codes.CheckKind.PLAN_GATE.value, A.APPROVE.value: codes.CheckKind.DONE_GATE.value,
                  A.CLOSE_AS_DECIDED.value: codes.CheckKind.PLAN_GATE.value}
_UNTOUCHED_CONTINUE = frozenset({R.STEP_ADD_LIMIT.value, R.STEP_REMOVAL_REQUEST.value, R.IRREVERSIBLE_CHANGE.value,
                                 R.PR_REVIEW.value})
"""Stage 3: stops recorded AFTER their step was done — `continue` leaves the step as it is."""
_RQ = codes.RequestOutcome
_RQ_REASON = {R.STEP_ADD_LIMIT.value: codes.RequestReason.LIMIT.value,
              R.STEP_REMOVAL_REQUEST.value: codes.RequestReason.REMOVAL.value}
_RERUN_COUNTERS = {R.PLAN_GATE.value: "plan_rerun", R.DONE_GATE.value: "done_rerun"}
_CLOSE_AT_STEP = frozenset({R.BLOCKED.value, R.NOT_REPRODUCED.value})
"""Stops whose close-as-decided answers the stopped (unfinished) step itself, which is skipped with the rest:
blocked (K8-3) and not-reproduced (readiness E4 — the human closes an Issue whose bug did not reproduce)."""


def pending_requests(state, situation):
    """Stage 3 (E13, E15): the requests of state.requests that wait for `situation`'s answer — of the
    first waiting step only (one stop per step)."""
    reason = _RQ_REASON.get(situation)
    wait = [q for q in state.get("requests") or () if q["outcome"] == _RQ.PENDING.value and q["reason"] == reason]
    return [q for q in wait if q["from_step"] == wait[0]["from_step"]
            and q["from_attempt"] == wait[0]["from_attempt"]] if reason and wait else []


def _settle_requests(work, situation, skip_step):
    """The answered requests' end: continue → declined (limit / refused); skip X → skipped, the
    others of the same step keep waiting (the stop comes again for them)."""
    for q in pending_requests(work, situation):
        if skip_step is not None:
            if q["step"] == skip_step:
                q["outcome"], q["reason"] = _RQ.SKIPPED.value, None
        elif situation == R.STEP_ADD_LIMIT.value:
            q["outcome"], q["reason"] = _RQ.DECLINED.value, codes.RequestReason.LIMIT.value
        else:
            q["outcome"], q["reason"] = _RQ.DECLINED.value, codes.RequestReason.REFUSED.value


def unapproved_irreversible(state):
    """Stage 3 (E23): the detected human-decision changes no human has approved — by (category, code,
    path): an approved one is never asked again, a new path / code is."""
    irr = state.get("irreversible") or {}
    key = lambda e: (e["category"], e["code"], e["path"])  # noqa: E731
    ok = {key(a) for a in irr.get("approved") or ()}
    return [d for d in irr.get("detected") or ()
            if d["level"] == codes.IrreversibleLevel.HUMAN_DECISION.value and key(d) not in ok]


def _settle_irreversible(work, answer, who):
    """continue = the human approves everything asked; rerun = forget it (what is still there after
    the rerun is detected, and asked, again)."""
    asked = unapproved_irreversible(work)
    irr = work["irreversible"]
    if answer == A.CONTINUE.value:
        at = store.now_ts()
        irr["approved"] += [{"category": d["category"], "code": d["code"], "path": d["path"], "at": at, "who": who}
                            for d in asked]
    else:
        irr["detected"] = [d for d in irr["detected"] if d not in asked]


def _recommendation(rec, reason):
    """D15: the escalate recommendation of a leader answer → state.stop.recommendation."""
    if not isinstance(rec, dict) or rec.get("answer") not in codes.LeaderAnswer.values():
        raise AnswerRefused("a leader escalate carries a recommendation {answer, step, note} (D15)")
    note = rec.get("note")
    return {"answer": rec["answer"], "step": rec.get("step"), "note": note if isinstance(note, str) else "",
            "reason": reason}


def sprint_rerun_problem(state, answer, now):
    """Why the sprint seat may not answer this stop, or None (H8, D6). Only `rerun`, only an infra-stop at
    needs_human with detail quota, and only once its reset time has passed. `stop.note` is never read."""
    stop = (state or {}).get("stop") or {}
    if answer != A.RERUN.value:
        return f"a sprint answers `rerun` only, not {answer!r}"
    if (stop.get("status"), stop.get("reason"), stop.get("detail")) != (
            codes.StepStatus.NEEDS_HUMAN.value, codes.SPRINT_RERUN_REASON, codes.SPRINT_RERUN_DETAIL):
        return "a sprint reruns a quota stop only (stop.detail = quota)"
    reset = stop.get("reset_at")
    if isinstance(reset, bool) or not isinstance(reset, (int, float)):
        return "the quota stop has no reset time"
    if float(now) < float(reset):
        return "the quota has not been reset yet"
    return None


def apply_answer(paths, state, answer, step=None, reason=None, note="", procedure=None, stage=1,
                 soft_answered=False, who=HUMAN, recommendation=None, log_data=None, skip_step=None, skippable=(),
                 defer=None):
    """Record an answer in the leader's seat: leader-decision.md, counters, back_to; return the next action.

    One function for both seats (stage-2 scope §2.0-2): `who` = "human" (resume, I10) or
    "leader" (a checked LeaderResult — stage ≥ 2, only on a needs_leader stop). A human cannot
    answer a needs_leader stop (D24: the leader is called again). Returns:
      "continue"  run the procedure on (rerun / replan / continue / plan / approve);
      "stopped"   escalate — the Issue stays stopped (a leader escalate turns the stop into
                  needs_human with the D15 `recommendation`);
      "closed"    close-as-decided (D18): the plan step is done, every later step skipped (a blocked
                  step — K8-3 — is skipped with them) — the caller has already posted the rationale and closed the Issue.
    Raises AnswerRefused (state unchanged) when the answer does not fit the stop.
    The caller saves `state`; the `answer` log line and leader-decision.md are written here.
    `log_data` is merged into the answer line's `data` (e.g. new-comment `effects`).
    A stage-2 `plan` that attaches the template (D1) is the caller's: here the plan step is done.
    Stage 3: `skip` (step-removal-request, E13) skips `skip_step`, which must be in `skippable`
    (catalog.skippable_steps — the caller's); a human names it as `step`. `defer` (E30, the
    caller has checked the rows) = [{"row", "text"}] a leader's replan leaves out of this Issue:
    back to analyze instead of plan, once per Issue (defaults.DEFER_MAX).
    """
    q, reason = validate_answer(state, answer, step=step, reason=reason, note=note, procedure=procedure,
                                stage=stage, soft_answered=soft_answered, who=who)
    stop_step = q["step"]
    target = None
    events = []
    work = json.loads(json.dumps(state))     # change a copy; commit it only when all checks pass
    return _apply(paths, state, work, q, answer, step, reason, note, procedure, stage, who, recommendation,
                  log_data, stop_step, target, events, skip_step, skippable, defer)


def validate_answer(state, answer, step=None, reason=None, note="", procedure=None, stage=1,
                    soft_answered=False, who=HUMAN):
    """The checks apply_answer makes before it changes anything — no side effect. Returns
    (pending question, reason code); raises AnswerRefused. The caller of an answer with an
    outside action first (close-as-decided: the GitHub close, D18) validates with this.
    `who` = sprint (stage ≥ 4): sprint_rerun_problem decides, no step, at this process's clock."""
    q = pending_question(state, stage, soft_answered)
    if q is None or q["crashed"]:
        raise AnswerRefused("nothing waits for an answer (the Issue is not stopped)")
    if who not in (HUMAN, LEADER) and not (who == SPRINT and stage >= codes.STAGE4):
        raise ValueError(f"bad answer seat {who!r}")
    if who == SPRINT:
        problem = sprint_rerun_problem(state, answer, time.time()) or (
            "a sprint names no step" if step is not None else None)
        if problem:
            raise AnswerRefused(problem)
    if who == HUMAN and q["leader_turn"]:
        raise AnswerRefused(f"the leader answers the {q['reason']!r} stop (needs_leader): resume without an "
                            "answer calls the leader again (D24)")
    if who == LEADER and (stage < 2 or not q["leader_turn"]):
        raise AnswerRefused("a leader answer applies only to a needs_leader stop from stage 2")
    if answer not in q["allowed_answers"]:
        raise AnswerRefused(f"answer {answer!r} is not allowed for {q['reason']!r} in stage {stage}; "
                            f"allowed: {', '.join(q['allowed_answers']) or 'none'}")
    if reason is None:
        reason = codes.LeaderReason.OTHER.value
    if reason not in codes.LeaderReason.values():
        raise AnswerRefused(f"unknown reason code {reason!r} ({', '.join(codes.LeaderReason.values())})")
    if not isinstance(note, str):
        raise AnswerRefused("note must be text")
    if procedure is None and answer != A.ESCALATE.value:
        raise ValueError("apply_answer needs the procedure for this answer")
    stop_step = q["step"]
    if answer == A.CLOSE_AS_DECIDED.value and q["reason"] in _CLOSE_AT_STEP:
        if stop_step is None or step not in (None, stop_step):        # the row above says when it is allowed at all
            raise AnswerRefused(f"`{answer}` answers the blocked step {stop_step!r}, not {step!r}")
    elif answer in _CHECK_ANSWERS:
        want = _CHECK_ANSWERS[answer]
        if stop_step is None or step not in (None, stop_step) or procedure.step(stop_step).kind != \
                codes.StepKind.CHECK.value or procedure.step(stop_step).name != want:
            raise AnswerRefused(f"`{answer}` answers a {want} step, not {stop_step!r}")
    return q, reason


def _apply(paths, state, work, q, answer, step, reason, note, procedure, stage, who, recommendation,
           log_data, stop_step, target, events, skip_step=None, skippable=(), defer=None):
    log_data = dict(log_data or {})
    if defer and (answer != A.REPLAN.value or who != LEADER or len(work.get("deferred_rows") or ()) >= defaults.DEFER_MAX):
        raise AnswerRefused("rows are deferred only by a leader's `replan`, once per Issue (E30)")
    if answer == A.ESCALATE.value:
        action = "stopped"
        if who == LEADER:
            rec = _recommendation(recommendation, reason)
            events += statemachine.to_human(work, stage, recommendation=rec)
    elif answer == A.REPLAN.value:
        # D8: replan = back_to the plan step (plan-gate again); only when plan is done.
        # E30: with deferred rows the requirements-engineer rewrites the analysis first.
        target = defaults.PLAN_GATE_RERUN_TARGET if defer else defaults.REPLAN_TARGET
        if step not in (None, target):
            raise AnswerRefused(f"`replan` goes back to {target!r}, not {step!r}")
        if not _plan_done(work):
            raise AnswerRefused(f"`replan` needs a done {defaults.REPLAN_TARGET!r} step (D8)")
        if defer:
            at = store.now_ts()
            work.setdefault("deferred_rows", []).extend({"row": d["row"], "text": d["text"], "at": at} for d in defer)
            log_data["defer"] = [d["row"] for d in defer]
        work["stop"] = None
        events += statemachine.back_to(work, procedure, target, cause=stop_step or target,
                                       data={"answer": answer})
        action = "continue"
    elif answer == A.CLOSE_AS_DECIDED.value:
        work["stop"] = None
        s = _sstep(work, stop_step)
        blocked = q["reason"] in _CLOSE_AT_STEP          # K8-3 / E4: the stopped step never finished — skipped too
        if s["status"] != codes.StepStatus.DONE.value and not blocked:
            events.append((codes.LogEvent.STATUS.value,
                           {"step": stop_step, "attempt": s.get("latest_attempt"), "from": s["status"],
                            "to": codes.StepStatus.DONE.value, "note": f"{who} answer {answer}"}))
            s["status"] = codes.StepStatus.DONE.value
        after = False
        for x in work["steps"]:
            if x["id"] == stop_step:
                after = True
                if not blocked:
                    continue
            if after and x["status"] not in (codes.StepStatus.DONE.value, codes.StepStatus.SKIPPED.value):
                events.append((codes.LogEvent.STATUS.value,
                               {"step": x["id"], "attempt": x.get("latest_attempt"), "from": x["status"],
                                "to": codes.StepStatus.SKIPPED.value, "note": CLOSED_AS_DECIDED}))
                x["status"] = codes.StepStatus.SKIPPED.value
                x["reason"] = CLOSED_AS_DECIDED
        action = "closed"
    elif answer == A.RERUN.value:
        target = step or stop_step
        if target is None:
            target = next((s["id"] for s in work["steps"] if s["status"] != codes.StepStatus.DONE.value), None)
        if target is not None:
            _sstep(work, target)
            if stop_step is not None and procedure.index(target) > procedure.index(stop_step):
                raise AnswerRefused(f"rerun target {target!r} is after the stopped step {stop_step!r}")
        if q["reason"] == R.ON_FAIL_EXCEEDED.value:
            try:
                statemachine.grant_rerun(work, stop_step)
            except statemachine.StateError as e:
                raise AnswerRefused(str(e)) from None
        if q["reason"] == R.IRREVERSIBLE_CHANGE.value:
            _settle_irreversible(work, answer, who)
        counter = _RERUN_COUNTERS.get(q["reason"]) if stage >= 2 else None
        if counter:
            c = work.setdefault("counters", {})
            c[counter] = c.get(counter, 0) + 1
        work["stop"] = None
        if target is not None:
            events += statemachine.back_to(work, procedure, target, cause=stop_step or target,
                                           data={"answer": answer})
        action = "continue"
    elif answer == A.SKIP.value:
        skip_step = skip_step or (step if who == HUMAN else None)
        if skip_step not in skippable:
            raise AnswerRefused(f"`skip` names one of {list(skippable) or 'no step'} (--step), not {skip_step!r}: only a "
                                "step the catalog added, requested away, not finished and no mandatory gate")
        s = _sstep(work, skip_step)
        events.append((codes.LogEvent.STATUS.value,
                       {"step": skip_step, "attempt": s.get("latest_attempt"), "from": s["status"],
                        "to": codes.StepStatus.SKIPPED.value, "code": codes.LEADER_SKIP_REASON,
                        "note": f"{who} answer {answer} ({reason})"}))
        s["status"] = codes.StepStatus.SKIPPED.value
        s["reason"], s["detail"] = codes.LEADER_SKIP_REASON, reason
        _settle_requests(work, q["reason"], skip_step)
        work["stop"] = None
        log_data["skip_step"] = skip_step
        action = "continue"
    elif answer == A.CONTINUE.value and q["reason"] in _UNTOUCHED_CONTINUE:
        if step is not None and step != stop_step:
            raise AnswerRefused(f"{answer!r} applies to the stopped step {stop_step!r}, not {step!r}")
        if q["reason"] == R.IRREVERSIBLE_CHANGE.value:
            _settle_irreversible(work, answer, who)
        else:
            _settle_requests(work, q["reason"], None)
        work["stop"] = None
        action = "continue"
    elif answer in (A.CONTINUE.value, A.PLAN.value, A.APPROVE.value):
        if step is not None and step != stop_step:
            raise AnswerRefused(f"{answer!r} applies to the stopped step {stop_step!r}, not {step!r}")
        work["stop"] = None
        if stop_step is not None:
            s = _sstep(work, stop_step)
            frm = s["status"]
            to = codes.StepStatus.PENDING.value if answer == A.CONTINUE.value else codes.StepStatus.DONE.value
            if frm != to:
                s["status"] = to
                events.append((codes.LogEvent.STATUS.value,
                               {"step": stop_step, "attempt": s.get("latest_attempt"), "from": frm, "to": to,
                                "note": f"{who} answer {answer}"}))
        action = "continue"
    else:
        raise AnswerRefused(f"answer {answer!r} is not supported in stage {stage}")

    when = store.now_ts()
    entry = (f"**{when} — {who} answer `{answer}`** for stop `{q['reason']}`"
             + (f" at step `{stop_step}`" if stop_step else "")
             + (f", rerun from `{target}`" if target else "")
             + (f", skipped `{log_data['skip_step']}`" if log_data.get("skip_step") else "") + f" (reason `{reason}`)\n\n"
             + (note.strip() or "(no note)")
             + "".join(f"\n\nDeferred requirement {d['row']} (move it to `## 미룬 요구` as `(deferred {d['row']})`, "
                       f"drop its ACs): {d['text']}" for d in defer or ()))
    _write_decision(paths, entry, stage)
    data = {"answer": answer, "target": target}
    if who == LEADER:
        data.update({"step": target, "situation": q["reason"]})
    data.update(log_data)
    store.append_log(paths, codes.LogEvent.ANSWER.value, who=who, step=stop_step,
                     attempt=q.get("attempt"), code=q["reason"], reason=reason, note=note or None,
                     data=data)
    for ev, fields in events:
        store.append_log(paths, ev, **fields)
    state.clear()
    state.update(work)
    return action


def pr_review_problem(state):
    """E31: why `resume --pr-review` cannot start now, or None. It starts from a finished Issue with a PR."""
    if state.get("stop"):
        return f"the Issue is stopped ({state['stop']['reason']}): answer that first"
    if state.get("closed"):
        return "the Issue was closed as decided - there is no pull request"
    open_steps = [s["id"] for s in state["steps"]
                  if s["status"] not in (codes.StepStatus.DONE.value, codes.StepStatus.SKIPPED.value)]
    if open_steps:
        return f"the Issue is not finished (step {open_steps[0]!r}): resume it without --pr-review"
    if not (state.get("github") or {}).get("pr_number"):
        return "the Issue has no pull request"
    return None


def _attempt_json(paths, step, attempt, name):
    try:
        obj = json.loads(fsafe.read_bytes(paths.attempt_file(step, attempt, name), root=store._root(paths),
                                          max_bytes=store.MAX_RECORD_BYTES).decode("utf-8"))
    except (FileNotFoundError, ValueError, UnicodeDecodeError):
        return {}
    return obj if isinstance(obj, dict) else {}


def dismiss_problem(paths, state, step):
    """E32: why a human cannot dismiss review `step` now, or None. Only the block verdict of the
    review that exceeded its on_fail (a leader's turn first: needs_human) - never a red run, a
    failed mandatory check, a boundary stop or a step whose outputs the engine has not committed."""
    stop = state.get("stop")
    if not stop or stop["reason"] != R.ON_FAIL_EXCEEDED.value or stop.get("step") != step or not stop.get("attempt"):
        return f"only the review whose block stopped the Issue can be dismissed ({R.ON_FAIL_EXCEEDED.value}), not {step!r}"
    if stop["status"] != codes.StepStatus.NEEDS_HUMAN.value:
        return "the leader answers this stop (needs_leader): resume without --dismiss"
    n = stop["attempt"]
    brief, result = (_attempt_json(paths, step, n, f) for f in ("brief.json", "result.json"))
    try:
        out = store.read_facts(paths, step, n).get("outcome") or {}
    except (FileNotFoundError, store.CorruptFile, store.FormatMismatch):
        out = {}
    if brief.get("result_kind") != codes.ResultKind.REVIEW.value or \
            (out.get("code"), out.get("detail")) != (codes.FailureCode.CHECK_FAILED.value,
                                                     codes.CheckFailedReason.VERDICT_BLOCK.value):
        return f"{step!r} did not stop on a review's block verdict ({out.get('code')} / {out.get('detail')})"
    mandatory = set(brief.get("rule_checks") or ())
    if any(c.get("id") in mandatory and c.get("result") != codes.CheckResult.PASS.value
           for c in result.get("checks") or () if isinstance(c, dict)):
        return f"a mandatory check of {step!r} failed - nobody lifts a rule"
    if brief.get("outputs"):
        return f"{step!r} writes outputs the engine commits only when it passes - it cannot be dismissed"
    return None


def apply_dismiss(paths, state, step, reason, head, stage):
    """E32: the human dismisses the current block of `step` at `head`: the step is done, the verdict and
    the reason are kept in state.dismissed (the PR shows them). Code that changes later is judged
    again as always (§4.4-3). AnswerRefused = state unchanged."""
    problem = dismiss_problem(paths, state, step)
    if problem is None and (not isinstance(reason, str) or not reason.strip()):
        problem = "a dismissal needs a reason (--reason-file)"
    if problem is None and store.read_facts(paths, step, state["stop"]["attempt"])["end_head"] != head:
        problem = "the branch moved since that verdict - rerun the review instead"
    if problem is not None:
        raise AnswerRefused(problem)
    stop, n = state["stop"], state["stop"]["attempt"]
    found = [f for f in _attempt_json(paths, step, n, "result.json").get("findings") or () if isinstance(f, dict)
             and f.get("severity") == codes.Severity.BLOCKER.value]
    state.setdefault("dismissed", []).append({
        "step": step, "attempt": n, "head": head, "reason": reason.strip(), "who": HUMAN, "at": store.now_ts(),
        "findings": [" ".join(f"{f['severity']}: {f.get('file')}: {f.get('text')}".split()) for f in found]})
    s = _sstep(state, step)
    frm, s["status"] = s["status"], codes.StepStatus.DONE.value
    state["stop"] = None
    _write_decision(paths, f"**{store.now_ts()} — {HUMAN} dismissed the block of review `{step}`** (attempt {n}, "
                           f"HEAD {head[:12]})\n\n{reason.strip()}", stage)
    store.append_log(paths, codes.LogEvent.ANSWER.value, who=HUMAN, step=step, attempt=n, code=stop["reason"],
                     reason=codes.LeaderReason.OTHER.value, note=reason.strip(), data={"dismiss": step})
    store.append_log(paths, codes.LogEvent.STATUS.value, step=step, attempt=n, **{"from": frm, "to": s["status"]},
                     note=f"{HUMAN} dismissed the block")


def soft_budget_answered(paths):
    """True when a human already gave the once-per-Issue `rerun` for a soft-budget stop (log.jsonl)."""
    for line in store.read_log(paths):
        if (line.get("event") == codes.LogEvent.ANSWER.value and line.get("code") == R.SOFT_BUDGET.value
                and (line.get("data") or {}).get("answer") == A.RERUN.value):
            return True
    return False
