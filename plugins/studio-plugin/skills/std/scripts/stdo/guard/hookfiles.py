"""P-HOOK (m0e-plan v2 §10): the pre-commit hook files Studio installed (m0d1b-plan §5.1 contract).

Fixed candidates, never core.hooksPath. A file is Studio's only while it carries "studio:hook".
- inside the git common dir (the shim, the chained previous hook while the shim exists, the runner folder):
  the whole file is protected — writes, deletes, moves and deleting an ancestor are denied;
- files shared with the team (.husky/pre-commit, lefthook-local.yml): a Write/Edit passes when the studio:hook
  block stays byte-identical (exactly once); Bash writes, deletes and moves are denied."""

import os

from ..hooks.templates import stops_before_block

MARK = "studio:hook"
BEGIN = "# >>> studio:hook >>>"
END = "# <<< studio:hook <<<"
SHARED = (os.path.join(".husky", "pre-commit"), "lefthook-local.yml")


def _read(p):
    try:
        with open(p, encoding="utf-8", errors="surrogateescape") as f:
            return f.read()
    except OSError:
        return None


def _inside(path, root):
    return path == root or path.startswith(root.rstrip("/") + "/")


def items(ri):
    """[(real path, kind)] kind: "shared" | "file" | "chained" | "dir"."""
    wt = os.path.realpath(ri.worktree)
    cd = os.path.realpath(ri.common_dir) if ri.common_dir else None
    out = [(os.path.join(wt, s), "shared") for s in SHARED]
    if cd:
        out += [(os.path.join(cd, "hooks", "pre-commit"), "file"),
                (os.path.join(cd, "hooks", "pre-commit.studio-chained"), "chained"),
                (os.path.join(cd, "studio"), "dir")]
    return out


def _active(path, kind, ri, op):
    if kind == "dir":
        # writing into it is always Studio's business (a planted runner would pass every commit)
        return op != "delete" or os.path.isdir(path)
    if kind == "chained":
        shim = os.path.join(os.path.dirname(path), "pre-commit")
        return os.path.exists(path) and MARK in (_read(shim) or "")
    return MARK in (_read(path) or "")


def hit(ri, real, op):
    """(path, kind) when `op` on `real` touches an active Studio hook file; op: write | delete."""
    if ri is None or real is None:
        return None
    wt = os.path.realpath(ri.worktree)
    for path, kind in items(ri):
        if op == "delete":
            # deleting a folder that holds the file; the work tree itself and its ancestors are the
            # ancestor-deletion rule's (G-DEL) — the guard reports that one
            touch = _inside(real, path) or (_inside(path, real) and not _inside(wt, real))
        else:
            touch = real == path or (kind == "dir" and _inside(real, path))
        if touch and _active(path, kind, ri, op):
            return path, kind
    return None


def block(text):
    """The studio:hook block text, None when absent, False when the markers are broken."""
    lines = (text or "").splitlines(True)
    starts = [i for i, l in enumerate(lines) if l.startswith(BEGIN)]
    ends = [i for i, l in enumerate(lines) if l.startswith(END)]
    if not starts and not ends:
        return None
    if len(starts) != 1 or len(ends) != 1 or ends[0] < starts[0]:
        return False
    return "".join(lines[starts[0]:ends[0] + 1])


def shared_edit_ok(path, new_text):
    """A Write/Edit of a shared hook file keeps Studio's block byte-identical and adds no standalone
    exit/return/exec line before it."""
    cur = _read(path)
    old = block(cur)
    if not old:
        return True  # nothing of Studio's (or already broken): not ours to protect
    if not isinstance(new_text, str) or block(new_text) != old:
        return False
    return stops_before_block(new_text) <= stops_before_block(cur)
