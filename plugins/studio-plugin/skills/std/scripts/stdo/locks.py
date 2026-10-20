"""The machine lock and a character's work lock: places and formats shared with script2video
(`heavy-lock.ts`, `actor-lock.ts`, `shutdown.ts` of s2v 0.12.1; m0c-plan §1, §8, §14)."""

import os
import re
import subprocess

from . import dirlock

HEAVY_TOKEN_ENV = "S2V_HEAVY_LOCK_TOKEN"
ACTOR_TOKEN_ENV = "S2V_ACTOR_LOCK_TOKEN"
EXIT_BUSY = 73
EXIT_ACTOR_BUSY = 74
EXIT_USAGE = 2
WORK = ".work"
ACTOR_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


class UsageError(Exception):
    """Usage or setup problem (exit 2), found before any lock is taken."""


def state_dir(env=None):
    """S2V_STATE_DIR (absolute only) or ~/.s2v."""
    env = os.environ if env is None else env
    v = env.get("S2V_STATE_DIR")
    if v:
        if not os.path.isabs(v):
            raise UsageError("S2V_STATE_DIR must be an absolute path: %s" % v)
        return v
    home = env.get("HOME") or os.path.expanduser("~")
    return os.path.join(home, ".s2v")


def ensure_state_dir(env=None):
    """Create the state folder with 0700 when it is missing (an existing one is left as it is)."""
    d = state_dir(env)
    if not os.path.isdir(d):
        os.makedirs(d, mode=0o700, exist_ok=True)
        os.chmod(d, 0o700)
    return d


def heavy_lock_path(env=None):
    return os.path.join(state_dir(env), "heavy.lock.d")


def actor_lock_path(character_dir):
    return os.path.join(character_dir, WORK, "op.lock.d")


def ensure_gitignore(character_dir):
    """`.work/` stays out of git — byte for byte what s2v's ensureGitignore writes."""
    f = os.path.join(character_dir, ".gitignore")
    if not os.path.exists(f):
        with open(f, "w", encoding="utf-8", newline="") as h:
            h.write(WORK + "/\n")
        return
    with open(f, encoding="utf-8", newline="") as h:
        text = h.read()
    lines = [l.strip() for l in re.split(r"\r?\n", text)]
    if any(l in (WORK, WORK + "/", "/" + WORK, "/" + WORK + "/") for l in lines):
        return
    sep = "" if text == "" or text.endswith("\n") else "\n"
    with open(f, "w", encoding="utf-8", newline="") as h:
        h.write(text + sep + WORK + "/\n")


def actor_dir(repo, studio_root, actor_id):
    """The actor's character folder: exactly one of local and public must exist."""
    if not ACTOR_ID.match(actor_id or ""):
        raise UsageError("not an actor id: %r" % (actor_id,))
    local = os.path.join(repo, studio_root, "local", "cast", actor_id, "character")
    public = os.path.join(repo, studio_root, "cast", actor_id, "character")
    found = [d for d in (local, public) if os.path.isdir(d)]
    if not found:
        raise UsageError("actor %s has no character folder (%s or %s)" % (actor_id, local, public))
    if len(found) == 2:
        raise UsageError("actor %s exists both in local and public cast: %s, %s" % (actor_id, local, public))
    return found[0]


def describe_owner(o):
    kind = dirlock.display_text(o.get("kind"), 20) if isinstance(o.get("kind"), str) else "?"
    return "%s — %s (pid %s, started %s UTC)" % (
        kind, dirlock.display_text(o.get("holder")), o.get("pid"),
        dirlock.display_text(o.get("pid_start"), 40))


def heavy_busy_line(result):
    if result.status == "breaking":
        return ("busy (breaking): another s2v is clearing a stale lock (or died doing it); try "
                "again in a minute\nsee: s2v services status")
    who = describe_owner(result.owner) if result.owner else "an unreadable lock"
    return ("busy (lock): another heavy job holds this machine: %s%s%s\n"
            "run this again when it is done; see: s2v services status" % (
                who, " (cannot check whether it still runs: ps failed)" if result.cannot_check else "",
                "; " + result.note if result.note else ""))


def actor_busy_line(result, key):
    if result.status == "breaking":
        return "actor busy: another s2v is clearing a stale lock of %s; try again" % key
    o = result.owner
    who = ("%s is working on this character (pid %s)" % (dirlock.display_text(o.get("cmd")), o.get("pid"))
           if o else "an unreadable lock is on this character")
    return "actor busy: %s: %s" % (who, key)


def running(character_dir, env=None):
    """Who works on the character now (a live holder), or None — s2v's actorRunning."""
    env = env or dirlock.LockEnv()
    o = dirlock.read_owner(actor_lock_path(character_dir))
    if not o or not dirlock.liveness(o, env)[0]:
        return None
    return {"pid": o["pid"], "pid_start": o["pid_start"], "cmd": dirlock.display_text(o.get("cmd"))}


def heavy_state(env=None, lock_env=None):
    """The machine lock as it is now (nothing changed), without the token."""
    p = heavy_lock_path(env)
    if not os.path.exists(p):
        return None
    o = dirlock.read_owner(p)
    if not o:
        return {"state": "invalid", "kind": None, "pid": None, "pid_start": None, "holder": None,
                "alive": False}
    alive = dirlock.liveness(o, lock_env or dirlock.LockEnv())[0]
    return {"state": "held" if alive else "stale",
            "kind": o.get("kind") if isinstance(o.get("kind"), str) else None,
            "pid": o["pid"], "pid_start": o["pid_start"],
            "holder": dirlock.display_text(o.get("holder")), "alive": alive}


def _kill0(pgid):
    try:
        os.killpg(pgid, 0)
        return False
    except ProcessLookupError:
        return True
    except PermissionError:
        return True  # macOS: only zombies left
    except OSError:
        return False


def ps_groups():
    out = subprocess.run(["ps", "-A", "-o", "pgid=,stat="], env=dict(os.environ, LC_ALL="C"),
                         stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if out.returncode != 0:
        raise OSError("ps failed")
    return out.stdout.decode("utf-8", "replace")


def group_gone(pgid, ps=ps_groups, kill0=_kill0):
    """s2v groupGoneSync: no such group, or only zombies left in it; ps failing counts as not gone."""
    if kill0(pgid):
        return True
    try:
        text = ps()
    except OSError:
        return False
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == str(pgid) and not parts[1].startswith("Z"):
            return False
    return True


def group_members(pgid, ps=ps_groups):
    """Pids still in the group (for the waiting notice)."""
    try:
        out = subprocess.run(["ps", "-A", "-o", "pid=,pgid=,stat="], env=dict(os.environ, LC_ALL="C"),
                             stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL).stdout.decode()
    except OSError:
        return []
    pids = []
    for line in out.splitlines():
        p = line.split()
        if len(p) >= 3 and p[1] == str(pgid) and not p[2].startswith("Z"):
            pids.append(int(p[0]))
    return pids
