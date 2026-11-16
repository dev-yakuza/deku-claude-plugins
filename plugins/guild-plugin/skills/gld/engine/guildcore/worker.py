"""guildcore.worker — the per-Issue lock, the detached worker and its event channel (§2.4, §2.7).

Lock (K0 handoff m5/m18, decided here — k1-notes A1):
* the flock is held on `<engine>/<N>.flock` for the worker's whole life (never renamed, so the
  lock's inode is stable);
* the holder's info `{mode, pid, pgid, started, pstart}` lives in `<engine>/<N>.lock`, written
  atomically (tmp + fsync + rename) right after the flock is taken and removed on release —
  `status running` reads that file without touching the flock and never sees it empty;
* `pstart` is the holder's process start time (`ps -o lstart`): a reader compares it with the
  live pid's start time, so a reused pid does not look like a running engine (K0-m5).
Busy: a second `acquire` fails; unattended exits 4, attended attaches (read-only when the owner is
unattended — no `hold`/`note`, R2C-n6).

Events (`<engine>/<N>/events.jsonl`, append + fsync): `{"seq", "t", "type": progress|ask|
terminal, …}`. `wait(max_s)` returns the events after the caller's cursor and returns at once
on an `ask` or `terminal`. Progress lines for humans go to the side file `progress.log` (never
stdout — the supervisor fence scans wide text, R2F-N6).
`hold`: a flag file the worker checks at every step boundary.
"""

import errno
import fcntl
import json
import os
import subprocess
import sys
import time

from guildcore import journal as J
from guildcore.adapters.claude import process_start

MODES = ("attended", "unattended")


def flock_path(common_dir, issue):
    return os.path.join(J.engine_dir(common_dir), "%d.flock" % int(issue))


class Busy(Exception):
    def __init__(self, holder):
        Exception.__init__(self, "busy: #%s held by %s" % (holder.get("issue"), holder.get("mode")))
        self.holder = holder


class IssueLock(object):
    def __init__(self, common_dir, issue, clock=None):
        self.common_dir = common_dir
        self.issue = int(issue)
        self.info_path = J.lock_path(common_dir, issue)
        self.flock_path = flock_path(common_dir, issue)
        self.fd = None
        self.clock = clock

    def acquire(self, mode):
        if mode not in MODES:
            raise ValueError("lock mode must be attended|unattended")
        os.makedirs(os.path.dirname(self.flock_path), exist_ok=True)
        fd = os.open(self.flock_path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            os.close(fd)
            if e.errno in (errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK):
                raise Busy(dict(self.holder() or {}, issue=self.issue))
            raise
        self.fd = fd
        from guildcore.adapters.clock import Clock
        now = (self.clock or Clock()).now()
        info = {"mode": mode, "pid": os.getpid(), "pgid": os.getpgid(0), "started": now,
                "pstart": process_start(os.getpid()), "issue": self.issue}
        J.atomic_write(self.info_path, json.dumps(info, sort_keys=True))
        return info

    def release(self):
        if self.fd is None:
            return
        try:
            os.unlink(self.info_path)
        except OSError:
            pass
        fcntl.flock(self.fd, fcntl.LOCK_UN)
        os.close(self.fd)
        self.fd = None

    def held_by_other(self):
        """True when another open file description holds the flock (probe with LOCK_NB)."""
        if not os.path.exists(self.flock_path):
            return False
        fd = os.open(self.flock_path, os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return True
        else:
            fcntl.flock(fd, fcntl.LOCK_UN)
            return False
        finally:
            os.close(fd)

    def holder(self):
        try:
            with open(self.info_path, encoding="utf-8") as fh:
                return json.load(fh)
        except (IOError, ValueError):
            return None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.release()


def holder_alive(info):
    """pid alive AND (when recorded) its process start time unchanged — K0-m5 pid reuse."""
    pid = (info or {}).get("pid")
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
    except OSError as e:
        if e.errno != errno.EPERM:
            return False
    if info.get("pstart"):
        return process_start(pid) == info["pstart"]
    return True


class Events(object):
    def __init__(self, common_dir, issue):
        self.dir = J.issue_dir(common_dir, issue)
        self.path = os.path.join(self.dir, "events.jsonl")
        self.progress_path = os.path.join(self.dir, "progress.log")
        self.cursor_path = os.path.join(self.dir, "wait.cursor")
        self.hold_path = os.path.join(self.dir, "hold")

    def read(self):
        out = []
        try:
            with open(self.path, encoding="utf-8") as fh:
                for ln in fh:
                    try:
                        out.append(json.loads(ln))
                    except ValueError:
                        pass
        except IOError:
            pass
        return out

    def emit(self, type_, now, **fields):
        if type_ not in ("progress", "ask", "terminal"):
            raise ValueError("event type must be progress|ask|terminal")
        seq = len(self.read()) + 1
        ev = dict(fields, seq=seq, t=now, type=type_)
        J.fsync_append(self.path, json.dumps(ev, ensure_ascii=False, sort_keys=True))
        if type_ == "progress" and fields.get("line"):
            J.fsync_append(self.progress_path, "%s %s" % (now, fields["line"]))
        return ev

    def cursor(self):
        try:
            with open(self.cursor_path) as fh:
                return int(fh.read().strip() or 0)
        except (IOError, ValueError):
            return 0

    def set_cursor(self, seq):
        J.atomic_write(self.cursor_path, str(int(seq)))

    def wait(self, max_s, sleep=time.sleep, poll_s=1.0, now=time.time):
        """Events after the cursor; returns early on ask/terminal; advances the cursor."""
        start = now()
        cur = self.cursor()
        while True:
            evs = [e for e in self.read() if e.get("seq", 0) > cur]
            if any(e.get("type") in ("ask", "terminal") for e in evs) or now() - start >= max_s:
                if evs:
                    self.set_cursor(evs[-1]["seq"])
                return evs
            sleep(poll_s)

    def request_hold(self):
        J.atomic_write(self.hold_path, "hold\n")

    def hold_requested(self):
        return os.path.exists(self.hold_path)

    def clear_hold(self):
        try:
            os.unlink(self.hold_path)
        except OSError:
            pass


def start_detached(argv, cwd, env, log_path):
    """Start the worker in its own session (survives the driver's death); stdout/stderr go to a
    side log. Returns the pid. The worker takes the IssueLock itself."""
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "ab") as log, open(os.devnull, "rb") as nul:
        p = subprocess.Popen(argv, cwd=cwd, env=env, stdin=nul, stdout=log, stderr=log,
                             start_new_session=True, close_fds=True)
    return p.pid


def attach(common_dir, issue, want_control):
    """(info, read_only) for a running worker; raises LookupError when none runs. An
    unattended-owned run is read-only to an attended driver (no hold/note, R2C-n6)."""
    lk = IssueLock(common_dir, issue)
    info = lk.holder()
    if not lk.held_by_other() or not holder_alive(info):
        raise LookupError("no running worker for #%s" % issue)
    read_only = info.get("mode") == "unattended" and want_control
    return info, read_only


def python():
    return sys.executable or "python3"
