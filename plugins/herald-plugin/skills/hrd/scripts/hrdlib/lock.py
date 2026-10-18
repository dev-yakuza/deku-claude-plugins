"""Checkout lock (plan §3.2.1).

Commands run inside an LLM session, so a pid identifies nothing — the owner is a nonce created
when the command starts. `batch` holds the lock for the whole run and hands the nonce to its
children through HRD_LOCK_TOKEN; a matching token re-enters.
"""

import os
import secrets

from .util import HeraldError, now_iso, read_json, write_json
from .store import paths


def lock_path(root):
    return os.path.join(paths(root)["memory"], "lock")


def status(root):
    return read_json(lock_path(root))


def wait_path(root):
    """A batch runner waiting out a usage limit says so here — never in the lock file itself, so
    the lock is only ever written by acquire (no read-modify-write race with --unlock)."""
    return os.path.join(paths(root)["memory"], "lock.wait")


def write_wait(root, token, until_iso, kind="limit"):
    write_json(wait_path(root), {"token": token, "pid": os.getpid(), "until": until_iso, "kind": kind})


def clear_wait(root, token=None):
    cur = read_json(wait_path(root))
    if cur is not None and (token is None or cur.get("token") == token):
        try:
            os.remove(wait_path(root))
        except OSError:
            pass


def _pid_runs_batch(pid):
    import subprocess
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError, TypeError):
        return False
    p = subprocess.run(["ps", "-o", "command=", "-p", str(int(pid))], capture_output=True, text=True)
    return p.returncode == 0 and "batch_runner" in p.stdout


def waiting(root, cur=None):
    """The live usage-limit wait of the batch holding the lock, else None: same token as the lock,
    `until` in the future, and the pid is alive and runs batch_runner (a reused pid is not)."""
    import datetime
    cur = cur if cur is not None else status(root)
    w = read_json(wait_path(root))
    if not cur or not isinstance(w, dict) or w.get("token") != cur.get("token"):
        return None
    try:
        until = datetime.datetime.fromisoformat(str(w.get("until")).replace("Z", "+00:00"))
    except ValueError:
        return None
    if until.tzinfo is None:
        until = until.replace(tzinfo=datetime.timezone.utc)
    if until <= datetime.datetime.now(datetime.timezone.utc) or not _pid_runs_batch(w.get("pid")):
        return None
    return {"pid": w.get("pid"), "until": w.get("until"), "kind": w.get("kind") or "limit"}


def acquire(root, command, token=None):
    token = token or os.environ.get("HRD_LOCK_TOKEN")
    cur = status(root)
    if cur:
        if token and cur.get("token") == token:
            return cur["token"]
        w = waiting(root, cur)
        if w:
            what = "an overloaded API (backoff)" if w["kind"] == "overloaded" else "a usage limit"
            raise HeraldError("checkout is locked: batch (pid %s) is waiting for %s until %s — "
                              "stop it with `kill %s`, or wait." % (w["pid"], what, w["until"], w["pid"]))
        raise HeraldError(
            "checkout is locked by `%s` since %s. If that run is gone, run `/hrd status --unlock`."
            % (cur.get("command"), cur.get("at"))
        )
    token = token or secrets.token_hex(8)
    write_json(lock_path(root), {"token": token, "command": command, "at": now_iso()})
    # Re-read: a concurrent writer may have raced us between the check and the write.
    if (status(root) or {}).get("token") != token:
        raise HeraldError("lost the lock race — another command started at the same moment")
    return token


def release(root, token, owner=False, command=None):
    """Only the command that acquired the lock releases it. A nested command that re-entered
    with the same token (a batch child via HRD_LOCK_TOKEN, `write` inside `refresh`) leaves it
    to the owner (plan §3.2.1). The batch runner passes owner=True."""
    cur = status(root)
    if not cur:
        return False
    if not owner and token == cur.get("token") and (
            (token == os.environ.get("HRD_LOCK_TOKEN") and cur.get("command") == "batch")
            or (command and command != cur.get("command"))):
        return False
    if cur.get("token") != token:
        raise HeraldError("lock is held by another command (%s); not releasing" % cur.get("command"))
    os.remove(lock_path(root))
    return True


def force_unlock(root):
    cur = status(root)
    if cur:
        os.remove(lock_path(root))
    return cur
