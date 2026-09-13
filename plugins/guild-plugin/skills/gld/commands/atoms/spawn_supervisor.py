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
1. Spawns `bash <script>` with `start_new_session=True` — a new session AND a new process
   group, so a group-directed signal at the launcher cannot reach the supervisor.
   Verified on macOS 25.5: launcher pgid 15989 / child pgid 16017; `kill -TERM -15989` killed
   the launcher and left the child running.
   ⚠ `setsid(1)` is NOT available on macOS, so the portable primitive is this flag, not a
   shell wrapper. Do not "simplify" this back into `setsid bash <script>`.
2. Redirects the supervisor's stdout/stderr to a LOG FILE, never to an inherited pipe.
   Inheriting the pipe would re-create the coupling by another route: when the launcher dies
   its end of the pipe closes, and the supervisor's next progress line takes SIGPIPE.
   The log file also makes that progress durable, which it was not before — it existed only
   in the harness's task-output file.
3. Streams the log to its own stdout while it waits, so a live session still sees progress
   exactly as before, and the harness still gets an exit to re-invoke Phase 4 on.
   If the launcher is killed, only the streaming stops. The supervisor keeps running and
   keeps writing to the log.

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
  64  usage / input error (bad argument, missing or empty script, not a directory)
  70  the spawn itself failed

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
import subprocess
import sys
import time


def die(msg, code=64):
    sys.stderr.write("spawn_supervisor: %s\n" % msg)
    raise SystemExit(code)


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

    argv = ["bash", script]
    if a.caffeinate:
        # Inside the detached session on purpose: wrapping THIS process instead would let the
        # machine sleep the moment the launcher is killed, i.e. exactly when the detachment
        # is doing its job.
        argv = ["caffeinate", "-i"] + argv

    try:
        logf = open(log_path, "ab", buffering=0)
    except OSError as e:
        die("cannot open log %s: %s" % (log_path, e), 70)

    try:
        proc = subprocess.Popen(
            argv,
            cwd=repo,
            stdin=subprocess.DEVNULL,
            stdout=logf,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except OSError as e:
        die("spawn failed (%s): %s" % (" ".join(argv), e), 70)
    finally:
        logf.close()

    sys.stderr.write(
        "spawn_supervisor: pid=%d detached (launch receipt, not the stop handle — "
        "use the run marker's pid; log: %s)\n" % (proc.pid, log_path))
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
            rc = proc.poll()
            if rc is not None:
                # Drain whatever landed between the last read and the exit.
                rest = f.read()
                if rest:
                    sys.stdout.buffer.write(rest)
                    sys.stdout.buffer.flush()
                return rc
            time.sleep(a.poll)


if __name__ == "__main__":
    raise SystemExit(main())
