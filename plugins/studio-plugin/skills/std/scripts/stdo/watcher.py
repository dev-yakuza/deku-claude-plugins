"""lock.py's watcher (m0c-plan §5, §14): the leader of a new session and process group, started
by lock.py with `setsid`; it runs the s2v child in its group and reports how the child ended.

    python3 -B watcher.py --lifeline-fd R --status-fd W -- <child argv…>

- SIGINT / SIGTERM / SIGHUP get a handler that only writes `got <n>` on the status pipe (not
  SIG_IGN: an ignored signal stays ignored across exec, a handled one is reset), so a signal to
  the group never ends the watcher first, the child still gets it as usual, and lock.py learns
  that a tree-wide signal (Claude Code's way of ending a command, m0-measure X10) reached the
  group directly and must not be forwarded again.
- `ready` is written on the status pipe once the handlers are installed and the child has
  exec'd (Popen returns after exec), so no forwarded signal falls between fork and exec.
- The child gets stdin = /dev/null and none of the watcher's pipes.
- Lifeline: when the read end reports EOF, lock.py is gone (even by SIGKILL): the whole group is
  killed at once (the watcher too).
- When the child ends: `exit <code>` or `signal <n>` on the status pipe, then exit 0.

Self-contained (standard library only, imports nothing from stdo).
"""

import os
import select
import signal
import subprocess
import sys


_STATUS = [None]


def _got(signum, frame):
    """Do nothing to the watcher, but tell lock.py that this signal reached the group directly
    (Claude Code ends a command by signalling the whole process tree): lock.py then does not
    forward it a second time."""
    if _STATUS[0] is not None:
        _write(_STATUS[0], "got %d" % signum)


def _write(fd, line):
    try:
        os.write(fd, (line + "\n").encode())
    except OSError:
        pass


def main(argv):
    if "--" not in argv:
        return 2
    i = argv.index("--")
    opts, child_argv = argv[:i], argv[i + 1:]
    lifeline = int(opts[opts.index("--lifeline-fd") + 1])
    status = int(opts[opts.index("--status-fd") + 1])
    _STATUS[0] = status
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, _got)
    try:
        child = subprocess.Popen(child_argv, stdin=subprocess.DEVNULL, close_fds=True)
    except OSError as e:
        sys.stderr.write("std lock: cannot start %s: %s\n" % (child_argv[:1], e))
        _write(status, "ready")
        _write(status, "exit 127")
        return 0
    # ready only once the child has exec'd: a signal forwarded between fork and exec would hit
    # the do-nothing handler inherited by the forked child and be lost
    _write(status, "ready")
    while True:
        try:
            ready, _, _ = select.select([lifeline], [], [], 0.05)
        except InterruptedError:
            ready = []
        if ready:
            try:
                data = os.read(lifeline, 1)
            except OSError:
                data = b""
            if data == b"":
                os.killpg(os.getpgid(0), signal.SIGKILL)
        code = child.poll()
        if code is not None:
            _write(status, "signal %d" % -code if code < 0 else "exit %d" % code)
            return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
