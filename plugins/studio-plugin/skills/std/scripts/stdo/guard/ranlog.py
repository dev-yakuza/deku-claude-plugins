"""The guard-ran record (D-M0-1, m0d1b-plan §9): `.claude/studio/local/guard-ran.json` =
{"schema": 1, "sessions": {session_id: UTC ISO time}}. Written after every decision in each
harness repository the call touches; M0d-2 checks it. Failures are ignored."""

import datetime
import fcntl
import json
import os
import time

from .. import paths

KEEP_DAYS = 30
WAIT = 0.5


def _utcnow():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None, microsecond=0)


def _now():
    return _utcnow().isoformat() + "Z"


def _parse(t):
    try:
        return datetime.datetime.strptime(t, "%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        return None


def record(worktree, session_id, may_create, now=None):
    """Update the record; returns True when written."""
    if not session_id:
        return False
    local = os.path.join(worktree, ".claude", "studio", "local")
    if paths.local_problem(worktree):
        return False  # never through a link (m1-plan §3.1 review U1)
    try:
        if not os.path.isdir(local):
            if not may_create:
                return False
            os.makedirs(local, exist_ok=True)
        lock_path = os.path.join(local, "guard-ran.lock")
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            deadline = time.monotonic() + WAIT
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        return False
                    time.sleep(0.02)
            path = os.path.join(local, "guard-ran.json")
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                sessions = data.get("sessions") if isinstance(data, dict) else None
                if not isinstance(sessions, dict):
                    sessions = {}
            except (OSError, ValueError):
                sessions = {}
            stamp = now or _now()
            sessions[session_id] = stamp
            cut = (_parse(stamp) or _utcnow()) - datetime.timedelta(days=KEEP_DAYS)
            sessions = {k: v for k, v in sessions.items() if (_parse(v) or cut) >= cut or k == session_id}
            tmp = "%s.tmp.%d" % (path, os.getpid())
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"schema": 1, "sessions": sessions}, f, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
            return not paths.local_problem(worktree)
        finally:
            os.close(fd)
    except OSError:
        return False
