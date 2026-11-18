"""guildcore.valves — the soft valves and the kill switch (design §10.5).

Files under `<git-common-dir>/guild/engine/` (shared by every worktree of the clone, kept when a worktree
is removed):
* `HALT` — the kill switch: present = stop. The engine only READS it; `dev valve halt|resume` writes it.
* `overrides.json` = `{"auto": {key: value}, "human": {"set": {key: value}, "release": [key, …]}}` —
  `auto` is written by the engine only (tripwires, count rules), `human` by `dev valve` only.
* `overrides.lock` — every write takes this flock, re-reads, merges ITS OWN area's fields, writes a temp
  file and renames it over (atomic); `overrides.log` — append-only `{at, who, op, key, old, new, reason}`.

Effective value of a valve: `HALT` > `human.set` > `auto` (a key in `human.release` is never re-applied by
auto — the attempt is logged as an alarm) > env `GLD_ENGINE_<KEY>` > the committed config.

The registry of repositories the engine ran in (for `--all`, R5F-m3 / R6C-m3) lives in the config dir:
`${CLAUDE_CONFIG_DIR:-~/.claude}/guild-engine/repos.json` — keys = absolute git common dirs, written under
its own flock with an atomic rename on the first `dev run` in a repository.
"""

import fcntl
import json
import os
import re
import time

from guildcore import journal as J

KEYS = (
    re.compile(r"^kickoff\.confirm_interpretation$"),
    re.compile(r"^exarb\.no_unattended_dismiss$"),
    re.compile(r"^handoff_judge$"),
    re.compile(r"^judges\.[A-Z][A-Z0-9-]*\.model$"),
    re.compile(r"^stakes\.pause_on_partial$"),
    re.compile(r"^split\.require_human$"),
    re.compile(r"^group\.[A-Za-z0-9_-]+\.conservative$"),
    re.compile(r"^grading\.(highrisk_human_rate|grader_rate)$"),
    re.compile(r"^ab\.lever$"),
)
# grading rates may only be LOWERED from the §9.5 defaults, and never below the floor
GRADING_DEFAULT = {"grading.highrisk_human_rate": 0.3, "grading.grader_rate": 0.25}     # after the first sprint
GRADING_FLOOR = {"grading.highrisk_human_rate": 0.2, "grading.grader_rate": 0.15}
HUMAN_ONLY = ("grading.highrisk_human_rate", "grading.grader_rate")
# valve name → the engine config key a stage reads through `Ports.engine_cfg`
ENGINE_KEY = {"kickoff.confirm_interpretation": "attended_confirm_interpretation",
              "handoff_judge": "handoff_judge",
              "exarb.no_unattended_dismiss": "exarb_no_unattended_dismiss",
              "stakes.pause_on_partial": "stakes_pause_on_partial",
              "split.require_human": "split_require_human"}


class ValveError(Exception):
    pass


def valid_key(key):
    return any(rx.match(key or "") for rx in KEYS)


def parse_value(raw):
    """CLI text → JSON value (`true`, `0.5`, `"opus"` …); anything not JSON is a plain string."""
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def check_value(key, value):
    if key in GRADING_FLOOR:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError("%s takes a number" % key)
        if value < GRADING_FLOOR[key] or value > GRADING_DEFAULT[key]:
            raise ValueError("%s may only be lowered, to no less than %s (§9.5)" % (key, GRADING_FLOOR[key]))
    if key.endswith(".conservative") or key in ("exarb.no_unattended_dismiss", "kickoff.confirm_interpretation",
                                                "stakes.pause_on_partial", "split.require_human"):
        if not isinstance(value, bool):
            raise ValueError("%s takes true|false" % key)
    if key == "handoff_judge" and value not in ("default", "always"):
        raise ValueError("handoff_judge takes default|always")
    if key.startswith("judges.") and value not in ("haiku", "sonnet", "opus"):
        raise ValueError("%s takes haiku|sonnet|opus" % key)


def paths(common_dir):
    d = J.engine_dir(common_dir)
    return {"dir": d, "halt": os.path.join(d, "HALT"), "json": os.path.join(d, "overrides.json"),
            "lock": os.path.join(d, "overrides.lock"), "log": os.path.join(d, "overrides.log")}


def halted(common_dir):
    return os.path.exists(paths(common_dir)["halt"])


def load(common_dir):
    try:
        with open(paths(common_dir)["json"], encoding="utf-8") as fh:
            data = json.load(fh)
    except (IOError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("auto", {})
    h = data.setdefault("human", {})
    h.setdefault("set", {})
    h.setdefault("release", [])
    return data


def effective(common_dir, env=None):
    """{valve: value} in force (human.set > auto unless released > env GLD_ENGINE_<KEY>)."""
    env = os.environ if env is None else env
    data = load(common_dir)
    out = {}
    for k, v in env.items():
        if k.startswith("GLD_ENGINE_VALVE_"):
            key = k[len("GLD_ENGINE_VALVE_"):].lower().replace("__", ".")
            if valid_key(key):
                out[key] = parse_value(v)
    released = set(data["human"]["release"])
    for k, v in data["auto"].items():
        if k not in released:
            out[k] = v
    out.update(data["human"]["set"])
    return out


def engine_overlay(valves):
    """The valves a stage reads through `Ports.engine_cfg` (key renamed)."""
    return dict((ENGINE_KEY[k], v) for k, v in (valves or {}).items() if k in ENGINE_KEY)


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class _Locked(object):
    def __init__(self, path):
        self.path = path

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)  # fs-ok: engine state dir under <git-common-dir>/guild/engine (no role can write there)
        self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)  # fs-ok: engine overrides lock (no role can write there)
        fcntl.flock(self.fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *a):
        fcntl.flock(self.fd, fcntl.LOCK_UN)
        os.close(self.fd)


def _log(common_dir, who, op, key, old, new, reason):
    J.fsync_append(paths(common_dir)["log"], json.dumps(
        {"at": _now(), "who": who, "op": op, "key": key, "old": old, "new": new, "reason": reason},
        ensure_ascii=False, sort_keys=True))


def _write(common_dir, data):
    J.atomic_write(paths(common_dir)["json"], json.dumps(data, ensure_ascii=False, sort_keys=True, indent=1))


def human_set(common_dir, key, value, who, reason=""):
    if not valid_key(key):
        raise ValveError("unknown valve %r" % key)
    try:
        check_value(key, value)
    except ValueError as e:
        raise ValveError(str(e))
    with _Locked(paths(common_dir)["lock"]):
        data = load(common_dir)
        old = data["human"]["set"].get(key)
        data["human"]["set"][key] = value
        data["human"]["release"] = [k for k in data["human"]["release"] if k != key]
        _write(common_dir, data)
        _log(common_dir, who, "set", key, old, value, reason)
    return old


def human_clear(common_dir, key, who, reason=""):
    """A person clears a valve: its human value goes, and the key is RELEASED — auto never re-applies it."""
    if not valid_key(key):
        raise ValveError("unknown valve %r" % key)
    with _Locked(paths(common_dir)["lock"]):
        data = load(common_dir)
        old = data["human"]["set"].pop(key, None)
        old_auto = data["auto"].pop(key, None)
        if key not in data["human"]["release"]:
            data["human"]["release"].append(key)
        _write(common_dir, data)
        _log(common_dir, who, "clear", key, old if old is not None else old_auto, None, reason)
    return old


def auto_set(common_dir, key, value, reason=""):
    """The engine's own valve (tripwire / count rule). Never touches `human`; a released key is not re-applied
    — the attempt is logged as an alarm. Returns True when applied."""
    if not valid_key(key) or key in HUMAN_ONLY:
        raise ValveError("not an auto valve: %r" % key)
    with _Locked(paths(common_dir)["lock"]):
        data = load(common_dir)
        if key in data["human"]["release"]:
            _log(common_dir, "engine", "alarm", key, None, value, "released by a person — not re-applied: %s" % reason)
            return False
        old = data["auto"].get(key)
        if old == value:
            return True
        data["auto"][key] = value
        _write(common_dir, data)
        _log(common_dir, "engine", "auto", key, old, value, reason)
    return True


def halt(common_dir, who, reason=""):
    with _Locked(paths(common_dir)["lock"]):
        J.atomic_write(paths(common_dir)["halt"], json.dumps({"at": _now(), "who": who, "reason": reason}) + "\n")
        _log(common_dir, who, "halt", "HALT", None, True, reason)


def resume(common_dir, who, reason=""):
    with _Locked(paths(common_dir)["lock"]):
        try:
            os.unlink(paths(common_dir)["halt"])  # fs-ok: engine kill-switch file (only `dev valve resume` removes it)
            was = True
        except OSError:
            was = False
        _log(common_dir, who, "resume", "HALT", was, False, reason)
    return was


# ---- the config-dir registry ------------------------------------------------------------------------------

def registry_path(env=None):
    env = os.environ if env is None else env
    base = env.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    return os.path.join(base, "guild-engine", "repos.json")


def register(common_dir, env=None):
    """Add this clone's absolute git common dir (flock + atomic rename). Returns True when newly added."""
    path = registry_path(env)
    key = os.path.realpath(common_dir)
    with _Locked(path + ".lock"):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (IOError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        if key in data:
            return False
        data[key] = {"registered": _now()}
        J.atomic_write(path, json.dumps(data, sort_keys=True, indent=1))
    return True


def registered(env=None):
    """[(common_dir, exists)] in the registry."""
    try:
        with open(registry_path(env), encoding="utf-8") as fh:
            data = json.load(fh)
    except (IOError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    return [(k, os.path.isdir(k)) for k in sorted(data)]
