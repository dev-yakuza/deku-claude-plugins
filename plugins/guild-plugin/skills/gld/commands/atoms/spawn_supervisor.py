#!/usr/bin/env python3
"""Launch a generated supervisor script DETACHED from the calling session, then stream its log.

`_bash_rules.md` sanctioned exception 1 ("A single bundled Python invocation").

WHY THIS EXISTS
---------------
`sprint/run.md` and `batch.md` used to launch their supervisor as
`bash <generated>.sh` with the Bash tool's `run_in_background: true`. That makes the
supervisor a child in the CALLING SESSION's process group, so whatever terminates that
background task — the session ending, the task being stopped, a harness reap — reaches the
supervisor too.

Measured (`/gld sprint run` #389, 6 members): the supervisor took SIGTERM 37 hours in, while
member 6 of 6 was mid-execute. It died at `guild:execute` with its branch unpushed, and the
run marker was never updated, so the tracker still read `state: "running"` against a dead pid.

That coupling contradicts the flow's own design. `sprint/run.md` step 6 already tells the
human *"완주 통지는 없습니다 — 아침에 `/gld sprint daily`로 확인하십시오"*, and a windowed run
is sized in NIGHTS (`ceil(members × 60min ÷ window minutes)`). A run that is designed to
outlive the session must not be owned by it.

WHAT IT DOES
------------
1. **Double-forks** the supervisor so its `ppid` becomes **1** immediately, then `setsid`s the
   intermediate child so the supervisor also gets its own session and process group.

   ⚠⚠ **`start_new_session=True` ALONE WAS NOT ENOUGH, and the first version shipped with only
   that.** It sets sid/pgid but leaves `ppid` pointing at the launcher — and the launcher stays
   alive to stream, so the supervisor is a direct child for the whole run. A stop that walks
   the process TREE (parent -> children) therefore reaches it. Measured on macOS 25.5:

       launcher pid 86455
       start_new_session=True child -> ppid 86455   <- still in the launcher's tree
       double-forked grandchild     -> ppid 1       <- gone from the tree

   The original note claimed this was "verified", but the verification was
   `kill -TERM -<launcher pgid>` — a **group**-directed kill, i.e. exactly the path that
   already passed. The tree path was never tested, and `/gld sprint run` #389 then took
   SIGTERM ~2 minutes in, three runs in a row.
   ⚠ `setsid(1)` is NOT available on macOS, so the primitive is `os.setsid()` in the
   intermediate child. Do not "simplify" this back into `setsid bash <script>`.
2. Redirects the supervisor's stdout/stderr to a LOG FILE, never to an inherited pipe.
   Inheriting the pipe would re-create the coupling by another route: when the launcher dies
   its end of the pipe closes, and the supervisor's next progress line takes SIGPIPE.
   The log file also makes that progress durable, which it was not before — it existed only
   in the harness's task-output file.
3. Streams the log to its own stdout while it waits, so a live session still sees progress
   exactly as before, and the harness still gets an exit to re-invoke Phase 4 on.
   If the launcher is killed, only the streaming stops. The supervisor keeps running and
   keeps writing to the log.

   ⚠⚠ **The double fork costs us `wait()`.** The supervisor is no longer this process's child,
   so `Popen.poll()` cannot report its exit code — a naive double-fork patch would make this
   launcher return **0 for every run, including failed ones**, and `sprint/run.md` Phase 4
   would read a dead run as a clean one. That is a worse defect than the one being fixed.
   So the exit code travels **through the filesystem**: the supervisor is wrapped in one line
   of `bash -c` that writes `$?` to `<log_dir>/supervisor.rc`, and this launcher polls
   `os.kill(pid, 0)` for liveness and reads that file when the pid is gone.
   ⚠ A stale `.rc` from a previous run is **deleted before the spawn** — reading one would
   report the previous run's outcome for this one.

So the two properties compose rather than trade off:
  session alive  -> identical behaviour to before, plus a durable log
  session killed -> the run survives; the human reads `/gld sprint daily`

PATHS ARE ASSEMBLED, NOT ACCEPTED
---------------------------------
Same contract as `render_supervisor.py`: a free-form `--script <path>` would be a hook-free
exec primitive whose target the same model call supplies. The caller names the repo and which
flow it is; this script derives both paths.

  --human-repo <abs dir> --tracker <digits>  ->  <repo>/.claude/guild/.gld-sprint-<t>.sh
                                                 <repo>/.claude/guild/.sprint-logs/<t>/supervisor.log
  --human-repo <abs dir> --batch             ->  <repo>/.claude/guild/.gld-batch.sh
                                                 <repo>/.claude/guild/.batch-logs/supervisor.log

EXIT CODES
----------
  the supervisor's own exit code, when it ran to completion under this launcher
      (read back from `<log_dir>/supervisor.rc` — see 3 above)
  64  usage / input error (bad argument, missing or empty script, not a directory)
  70  the spawn itself failed
  71  the supervisor finished but left no readable `.rc` — **outcome unknown, not success.**
      Treat it like a failure: Phase 4 must not report a clean run on this.

The caller MUST branch on the printed `spawn_supervisor: pid=<n>` line, not on this process
staying alive — that is the whole point.

⚠ THAT PID IS A LAUNCH RECEIPT, NOT THE STOP HANDLE. Without --caffeinate it happens to be the
supervisor's bash pid; WITH --caffeinate it is `caffeinate`'s, one level above it. The handle a
human uses to stop a run is the supervisor's own `$$`, which the supervisor writes into its
startup banner and into the tracking Issue's `<!-- guild:sprint:run -->` marker — those stay
correct in both cases, and the duplicate-run guard already reads the marker. Do not print this
pid as "stop with `kill <n>`".
"""

import argparse
import os
import subprocess  # noqa: F401 — 유지: 향후 진단용, 스폰 경로는 fork 기반이다
import sys
import time


def die(msg, code=64):
    sys.stderr.write("spawn_supervisor: %s\n" % msg)
    raise SystemExit(code)


# ⚠ `bash -c '<this>' gld-supervisor <rc_path> <argv...>`. It runs INSIDE the detached
# grandchild, so the exit code is recorded even when this launcher is long gone.
# `set +e` so a failing supervisor still reaches the write.
# ⚠⚠ `$0` is a NAME, not the rc path. The first version passed the rc path as `$0` and bash
#     then prefixed its own diagnostics with it, so a killed supervisor logged
#     `…/supervisor.rc: line 1: 93918 Killed: 9` — which reads as if the rc FILE were a broken
#     script. That line goes into `supervisor.log`, which is what a human opens after a bad
#     night. Measured on the first run of this path.
_RC_WRAPPER = ('set +e; _rc_path="$1"; shift; "$@"; rc=$?; '
               'printf %s "$rc" > "$_rc_path"; exit "$rc"')


def spawn_detached(argv, cwd, log_path):
    """Double-fork `argv` so the grandchild's ppid is 1. Returns the grandchild pid.

    ⚠ The intermediate child `setsid()`s and then exits **immediately**, which is what
    re-parents the grandchild to init. Keeping it alive to `wait()` would put a process back
    in the launcher's tree — the exact thing this exists to remove.
    """
    r, w = os.pipe()
    mid = os.fork()
    if mid == 0:                                  # intermediate child
        try:
            os.close(r)
            os.setsid()
            g = os.fork()
            if g == 0:                            # grandchild — ppid becomes 1
                os.close(w)
                os.chdir(cwd)
                fd = os.open(os.devnull, os.O_RDONLY)
                os.dup2(fd, 0)
                os.close(fd)
                lf = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
                os.dup2(lf, 1)
                os.dup2(lf, 2)
                if lf > 2:
                    os.close(lf)
                os.execvp(argv[0], argv)
                os._exit(127)                     # execvp only returns on failure
            # ⚠ the GRANDCHILD's pid, not `os.getpid()` — that would hand the caller the
            #    intermediate, which is about to exit, and every liveness check would say
            #    "finished" one second later.
            os.write(w, b"%d" % g)
        except BaseException:
            pass
        os._exit(0)
    os.close(w)
    os.waitpid(mid, 0)                            # reap the intermediate — no zombie
    data = os.read(r, 32)
    os.close(r)
    return int(data) if data.strip() else -1


def read_rc(rc_path, tries=20, delay=0.05):
    """Read the exit code the wrapper wrote. **Absence is not success.**

    ⚠ The wrapper writes `$?` and then exits, so the file is normally there the moment the pid
    disappears. It can be a hair late (or missing, if the supervisor was SIGKILLed before the
    write). Retry briefly, then report **71 — outcome unknown**, never 0. Returning 0 here is
    the failure mode this whole path exists to avoid.
    """
    for _ in range(tries):
        try:
            with open(rc_path) as fh:
                txt = fh.read().strip()
            if txt:
                return int(txt)
        except (OSError, ValueError):
            pass
        time.sleep(delay)
    sys.stderr.write("spawn_supervisor: supervisor is gone but %s is unreadable — "
                     "outcome UNKNOWN (exit 71), do not read this as a clean run\n" % rc_path)
    return 71


def alive(pid):
    """Liveness without `wait()` — the supervisor is not our child any more."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:                       # exists, owned by someone else
        return True
    return True


def main():
    p = argparse.ArgumentParser(add_help=True)
    p.add_argument("--human-repo", required=True,
                   help="absolute path of the human's checkout")
    p.add_argument("--tracker",
                   help="sprint tracking Issue number (digits only) — sprint flow")
    p.add_argument("--batch", action="store_true",
                   help="batch flow instead of sprint")
    p.add_argument("--caffeinate", action="store_true",
                   help="wrap the supervisor in `caffeinate -i` INSIDE the detached session "
                        "(so it lives and dies with the supervisor, not with this launcher)")
    p.add_argument("--poll", type=float, default=1.0,
                   help="seconds between log reads while streaming (default 1.0)")
    a = p.parse_args()

    if bool(a.tracker) == bool(a.batch):
        die("pass exactly one of --tracker <digits> or --batch")
    if a.tracker is not None and not a.tracker.isdigit():
        die("--tracker must be digits only, got %r" % a.tracker)

    repo = a.human_repo
    if not os.path.isabs(repo):
        die("--human-repo must be absolute, got %r" % repo)
    if not os.path.isdir(repo):
        die("--human-repo is not an existing directory: %s" % repo)

    guild = os.path.join(repo, ".claude", "guild")
    if a.batch:
        script = os.path.join(guild, ".gld-batch.sh")
        log_dir = os.path.join(guild, ".batch-logs")
    else:
        script = os.path.join(guild, ".gld-sprint-%s.sh" % a.tracker)
        log_dir = os.path.join(guild, ".sprint-logs", a.tracker)
    log_path = os.path.join(log_dir, "supervisor.log")

    # The render step is supposed to have written this already; say which half is missing
    # rather than letting bash exit 127 into a backgrounded task nobody reads.
    if not os.path.isfile(script):
        die("supervisor script not found: %s — run the render step first" % script)
    if os.path.getsize(script) == 0:
        die("supervisor script is empty: %s — the render failed" % script)

    os.makedirs(log_dir, exist_ok=True)
    rc_path = os.path.join(log_dir, "supervisor.rc")
    # ⚠ **Delete a stale `.rc` BEFORE spawning.** Reading a previous run's code would report
    #    that run's outcome for this one — and a leftover `0` reads as "clean".
    try:
        os.unlink(rc_path)
    except OSError:
        pass

    argv = ["bash", script]
    if a.caffeinate:
        # Inside the detached session on purpose: wrapping THIS process instead would let the
        # machine sleep the moment the launcher is killed, i.e. exactly when the detachment
        # is doing its job.
        argv = ["caffeinate", "-i"] + argv

    # ⚠ **Create the log before spawning.** The grandchild opens it with O_CREAT, but this
    #    launcher opens it for READING a moment later and would lose that race — measured:
    #    `FileNotFoundError` on the very first run of this path. The old code got this for
    #    free because the launcher itself opened the write end before `Popen`.
    try:
        os.close(os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644))
    except OSError as e:
        die("cannot open log %s: %s" % (log_path, e), 70)

    # The rc wrapper runs inside the grandchild, so the code is recorded even when this
    # launcher is killed mid-stream. See `_RC_WRAPPER`.
    argv = ["bash", "-c", _RC_WRAPPER, "gld-supervisor", rc_path] + argv

    try:
        pid = spawn_detached(argv, repo, log_path)
    except OSError as e:
        die("spawn failed (%s): %s" % (" ".join(argv), e), 70)
    if pid <= 0:
        die("spawn failed: no pid came back from the intermediate child", 70)

    sys.stderr.write(
        "spawn_supervisor: pid=%d detached (launch receipt, not the stop handle — "
        "use the run marker's pid; log: %s)\n" % (pid, log_path))
    sys.stderr.flush()

    # Stream the log for as long as we are alive. Being killed here is a supported outcome,
    # not an error: the supervisor is in its own session and keeps going.
    with open(log_path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if chunk:
                sys.stdout.buffer.write(chunk)
                sys.stdout.buffer.flush()
                continue
            if not alive(pid):
                # Drain whatever landed between the last read and the exit.
                rest = f.read()
                if rest:
                    sys.stdout.buffer.write(rest)
                    sys.stdout.buffer.flush()
                return read_rc(rc_path)
            time.sleep(a.poll)


if __name__ == "__main__":
    raise SystemExit(main())
