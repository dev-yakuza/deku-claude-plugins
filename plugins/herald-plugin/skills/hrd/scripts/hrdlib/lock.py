"""Checkout lock (plan §3.2.1).

Commands run inside an LLM session, so a pid identifies nothing — the owner is a nonce created
when the command starts. `batch` holds the lock for the whole run and hands the nonce to its
children through HRD_LOCK_TOKEN; a matching token re-enters.

0.20.0 (design/herald/11-ship-consent.md): a `--ship` run marks the lock it creates (`ship`,
`topic`, `attended`) — the only evidence the code and the guard read for "this run may skip a
human's look". The mark lives and dies with the lock (a nested acquire never changes it), and the
merge/deploy pass sits next to it in `lock.pass`, valid only for the lock that wrote it. Both
files are guard-protected.
"""

import datetime
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
    try:
        p = subprocess.run(["ps", "-o", "command=", "-p", str(int(pid))], capture_output=True, text=True)
    except OSError:  # no `ps` on this host: cannot tell — show the ordinary message
        return False
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


def acquire(root, command, token=None, ship=False, topic=None, attended=False):
    """`ship`/`topic`/`attended` are written only when this call creates the lock: a nested
    acquire (same token) returns the lock as it is — the outer command decided (11 §2.1)."""
    token = token or os.environ.get("HRD_LOCK_TOKEN")
    if ship and os.environ.get("HRD_UNATTENDED") == "1":
        raise HeraldError("--ship is a human's request in this session — not allowed in unattended sessions")
    if ship and not topic:
        raise HeraldError("--ship needs --topic <id> (the mark is bound to one topic)")
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
    rec = {"token": token, "command": command, "at": now_iso()}
    if ship:
        rec["ship"] = True
    if topic:
        rec["topic"] = topic
    if attended:
        rec["attended"] = True
    clear_pass(root)  # a pass never outlives the lock it was written for
    write_json(lock_path(root), rec)
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
    clear_pass(root)
    os.remove(lock_path(root))
    return True


def force_unlock(root):
    cur = status(root)
    clear_pass(root)
    if cur:
        os.remove(lock_path(root))
    return cur


# --- the ship mark and the merge/deploy pass (design/herald/11-ship-consent.md §2.1, §2.5) -------

PASS_TTL = 2 * 3600  # seconds a pass stays valid (11 §10 m2)


def _safe_status(root):
    """The lock, or None when it cannot be read — a read failure is "no mark", never an error."""
    try:
        cur = status(root)
    except Exception:  # noqa: BLE001
        return None
    return cur if isinstance(cur, dict) else None


def ship_active(root, topic, cur=None):
    """The lock exists, carries the ship mark and is bound to `topic` (11 §10 R3-1)."""
    cur = cur if cur is not None else _safe_status(root)
    return bool(cur) and cur.get("ship") is True and bool(topic) and cur.get("topic") == topic


def agent_ok(root, topic, cur=None):
    """`--agent` may stand in for a human's look: a ship mark for this topic and no `--attended`
    (attended runs ask the human at every gate — 11 §11 m3)."""
    cur = cur if cur is not None else _safe_status(root)
    return ship_active(root, topic, cur) and not cur.get("attended")


def pass_path(root):
    return os.path.join(paths(root)["memory"], "lock.pass")


def clear_pass(root):
    try:
        os.remove(pass_path(root))
    except OSError:
        pass


def write_pass(root, token, topic, pr, sha):
    """A pass for one merge, then one deploy (implementation review 24 MINOR-4): `merged` is false
    until `HRD lock ship-pass --merged` saw that very PR merged into the base this checkout has —
    the guard allows the merge only before, the deploy only after."""
    rec = {"token": token, "topic": topic, "pr": int(pr), "sha": sha, "at": now_iso(), "merged": False}
    write_json(pass_path(root), rec)
    return rec


def mark_merged(root, rec):
    rec = dict(rec, merged=True, merged_at=now_iso())  # `at` stays: the two hours count from the pass
    write_json(pass_path(root), rec)
    return rec


def valid_pass(root, cur=None, now=None):
    """The pass, when it belongs to the lock now held: same token, the lock carries the ship mark,
    the same topic, written within PASS_TTL. Anything unreadable → None (no pass)."""
    try:
        cur = cur if cur is not None else _safe_status(root)
        p = read_json(pass_path(root))
        if not cur or not isinstance(p, dict) or cur.get("ship") is not True:
            return None
        if not p.get("token") or p.get("token") != cur.get("token") or p.get("topic") != cur.get("topic"):
            return None
        at = datetime.datetime.fromisoformat(str(p.get("at")).replace("Z", "+00:00"))
        if at.tzinfo is None:
            at = at.replace(tzinfo=datetime.timezone.utc)
        age = ((now or datetime.datetime.now(datetime.timezone.utc)) - at).total_seconds()
        if age < 0 or age > PASS_TTL:
            return None
        return p
    except Exception:  # noqa: BLE001
        return None
