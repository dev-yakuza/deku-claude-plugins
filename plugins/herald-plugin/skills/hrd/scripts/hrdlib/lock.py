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


def acquire(root, command, token=None):
    token = token or os.environ.get("HRD_LOCK_TOKEN")
    cur = status(root)
    if cur:
        if token and cur.get("token") == token:
            return cur["token"]
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


def release(root, token):
    cur = status(root)
    if not cur:
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
