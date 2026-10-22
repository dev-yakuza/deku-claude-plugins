"""This machine's settings for one work tree (m1-plan §3.1, D-M1-0): `.claude/studio/local/machine.json`
= {"schema": 1, "s2v": {"path": "<absolute path>"}}. The file sits under the ignored `local/` folder, so a
machine's folders never reach a commit; `config.json` keeps only `s2v.min_version`.

Every reader of the s2v path goes through `s2v_path(repo)` (the guard, lock.py, state.py, the s2v wrappers).
Read-only here except `write`, which `/std init` and `/std config s2v.path` (setup.py, with the person's
`설정` answer) and the test harness use."""

import json
import os

from . import paths

SCHEMA = 1
REL = os.path.join(".claude", "studio", "local", "machine.json")
HINT = ("this machine's s2v path is not set for this work tree (.claude/studio/local/machine.json) — run "
        "/std config s2v.path to set it (a new clone or a new worktree needs it once)")


class Missing(Exception):
    """machine.json is absent or has no usable s2v path (Studio commands exit 2 with HINT)."""


def path(repo):
    return os.path.join(repo, REL)


def read(repo):
    """The parsed file (a dict) or None when it is absent or unreadable. paths.UnsafeLocal when `local/` (or a folder
    above it) is a symbolic link: the file is not read through it (closed)."""
    raw = paths.read_local(repo, "machine.json")
    if raw is None:
        return None
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def s2v_path(repo):
    """The absolute s2v repository path of this work tree, or None (absent, wrong schema, not absolute).
    Raises paths.UnsafeLocal (see read)."""
    data = read(repo)
    if data is None or data.get("schema") != SCHEMA:
        return None
    s2v = data.get("s2v")
    p = s2v.get("path") if isinstance(s2v, dict) else None
    if not isinstance(p, str) or not p or not os.path.isabs(p) or "\0" in p:
        return None
    return os.path.normpath(p)


def require_s2v_path(repo):
    p = s2v_path(repo)
    if p is None:
        raise Missing(HINT)
    return p


def write(repo, s2v):
    """Write machine.json (atomic). The caller checks the person's evidence where one is needed."""
    if not isinstance(s2v, str) or not os.path.isabs(s2v):
        raise ValueError("the s2v path must be absolute: %r" % (s2v,))
    paths.check_local(repo)
    p = path(repo)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = "%s.tmp.%d" % (p, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"schema": SCHEMA, "s2v": {"path": os.path.normpath(s2v)}}, f, ensure_ascii=False, indent=2,
                  sort_keys=True)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)
    paths.check_local(repo)  # written through a folder swapped meanwhile: say so (closed)
    return p
