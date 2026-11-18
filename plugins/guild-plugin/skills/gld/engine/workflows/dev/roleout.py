"""workflows.dev.roleout — reading what a role handed back, and keeping the design specs (K4, P1).

* `read(p, stage, res, rel, cap)` — a role-supplied path is read only when it is relative, has no
  `..`, has no symlink on the way, its realpath is inside THAT run's `out/`, and it is a regular file
  under `cap` bytes; it is opened with O_NOFOLLOW and re-checked with fstat. Anything else → None +
  decision block `role-path-refused` (the engine never follows a path a role chose outside its sandbox).
* `json_out(...)` — the same, parsed as a JSON object (else None + `role-output-invalid`).
* The spec store: the design roles write `out/skeleton.md`, `out/test-cases.md`, `out/<role>.md`,
  `out/split.json`; the engine validates and keeps them in an ENGINE-owned directory
  `<git-common-dir>/guild/engine/<N>/specs/` (never the human's checkout — design is read-only against
  it) and `install()`s them into the execute worktree's `docs/specs/<N>/` through `guildcore.fsafe`
  (the developer commits them with the PR, as the legacy flow did with the working-tree files).
"""

import json
import os
import stat

from guildcore import fsafe as FS
from guildcore.journal import atomic_write
from guildcore.records import markers

MAX_TEXT = 512 * 1024
SPEC_NAMES_RE = r"^[a-z0-9][a-z0-9_.-]{0,60}\.(md|json)$"


def _refuse(p, stage, rel, why):
    from workflows.dev.stages import base as B
    B.record_code(p, stage, "role-path-refused", "refused",
                  reason="%s — %s" % (markers.value(str(rel))[:200], why))
    return None


def resolve(res, rel):
    """(abs path, None) or (None, why)."""
    rd = getattr(res, "run_dir", None)
    if not rel or not isinstance(rel, str) or "\0" in rel:
        return None, "no path"
    if not rd:
        return None, "no run dir"
    norm = os.path.normpath(rel)
    if os.path.isabs(rel) or norm.startswith(".."):
        return None, "not a relative path inside the role's out/"
    if norm == "out" or norm.startswith("out" + os.sep):
        norm = norm[4:]
    out_dir = os.path.join(rd, "out")
    cur = out_dir
    for part in [x for x in norm.split(os.sep) if x]:
        cur = os.path.join(cur, part)
        try:
            st = os.lstat(cur)
        except OSError:
            return None, "missing"
        if stat.S_ISLNK(st.st_mode):
            return None, "symlink"
    if not os.path.realpath(cur).startswith(os.path.realpath(out_dir) + os.sep):
        return None, "outside the role's out/"
    if not stat.S_ISREG(os.lstat(cur).st_mode):
        return None, "not a regular file"
    return cur, None


def read(p, stage, res, rel, cap=MAX_TEXT):
    path, why = resolve(res, rel)
    if path is None:
        return _refuse(p, stage, rel, why)
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))  # a FIFO never blocks
    except OSError as e:
        return _refuse(p, stage, rel, "open: %s" % e.__class__.__name__)
    with os.fdopen(fd, "rb") as fh:
        st = os.fstat(fh.fileno())
        if not stat.S_ISREG(st.st_mode):
            return _refuse(p, stage, rel, "not a regular file")
        if st.st_size > cap:
            return _refuse(p, stage, rel, "larger than %d bytes" % cap)
        return fh.read().decode("utf-8", "replace")


def json_out(p, stage, res, rel, cap=MAX_TEXT):
    text = read(p, stage, res, rel, cap)
    if text is None:
        return None
    try:
        obj = json.loads(text)
    except ValueError:
        obj = None
    if not isinstance(obj, dict):
        from workflows.dev.stages import base as B
        B.record_code(p, stage, "role-output-invalid", "invalid", reason="%s is not a JSON object" % markers.value(rel)[:120])
        return None
    return obj


# ---- the spec store ----------------------------------------------------------------------------

def store_dir(p):
    d = getattr(p, "spec_store", None)
    if d:
        return d
    base = p.git_dir or os.path.join(p.root or ".", ".git")
    return os.path.join(base, "guild", "engine", str(p.issue), "specs")


def put(p, name, text):
    import re
    if not re.match(SPEC_NAMES_RE, name):
        raise ValueError("bad spec name %r" % name)
    d = store_dir(p)
    os.makedirs(d, exist_ok=True)  # fs-ok: engine spec store under <git-common-dir>/guild/engine
    atomic_write(os.path.join(d, name), text)          # engine-owned (git common dir), never a role tree


def get(p, name):
    path = os.path.join(store_dir(p), name)
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except (IOError, OSError):
        return None


def names(p):
    d = store_dir(p)
    try:
        return sorted(x for x in os.listdir(d) if not x.startswith("."))
    except OSError:
        return []


def install(store, worktree, issue, skip=("split.json",)):
    """Copy the stored specs into `<worktree>/docs/specs/<N>/` through fsafe. A file the worktree
    already has is left alone (the branch's committed spec, or a developer's edit, wins). Returns
    (installed, kept)."""
    installed, kept = [], []
    try:
        lst = sorted(os.listdir(store))
    except OSError:
        return installed, kept
    for name in lst:
        if name in skip or name.startswith("."):
            continue
        rel = os.path.join("docs", "specs", str(int(issue)), name)
        if os.path.lexists(os.path.join(worktree, rel)):
            kept.append(rel)
            continue
        with open(os.path.join(store, name), "rb") as fh:
            data = fh.read()
        FS.makedirs(worktree, os.path.dirname(rel))
        FS.write_bytes(worktree, rel, data)
        installed.append(rel)
    return installed, kept
