"""Merge · cherry-pick · revert · rebase in progress (m0e-plan §5.1): only Studio paths made while resolving
conflicts count as this commit's Studio changes — a path whose index content equals a parent's, or equals
git's own automatic merge result (a clean auto-merge of both sides' edits), is not new. When the automatic
result cannot be computed (an octopus merge, an old git, a missing base), the closed rule stays: differs from
every parent = new."""

import os
import re
import tempfile

from . import spaths
from .gitx import GitError


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return [l.strip() for l in f if l.strip()]
    except OSError:
        return []


def _verify(git, rev):
    out = git.run("rev-parse", "-q", "--verify", rev + "^{commit}", check=False)
    return out.stdout.decode().strip() if out.returncode == 0 else None


def detect(git):
    """(kind, [parent revs besides HEAD], three-way (base, theirs) | None) or (None, [], None)."""
    mh = _read(git.git_path("MERGE_HEAD"))
    if mh:
        return "merge", mh, ((None, mh[0]) if len(mh) == 1 else None)
    cp = _read(git.git_path("CHERRY_PICK_HEAD"))
    if cp:
        return "cherry-pick", cp[:1], (_verify(git, cp[0] + "^"), cp[0])
    rv = _read(git.git_path("REVERT_HEAD"))
    if rv:
        par = _verify(git, rv[0] + "^")
        return "revert", [par] if par else [], (rv[0], par) if par else None
    rb = _read(git.git_path("REBASE_HEAD"))
    if os.path.isdir(git.git_path("rebase-merge")) or os.path.isdir(git.git_path("rebase-apply")) or rb:
        return "rebase", rb[:1], ((_verify(git, rb[0] + "^"), rb[0]) if rb else None)
    return None, [], None


def git_version(git):
    m = re.search(r"(\d+)\.(\d+)", git.text("--version"))
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def auto_merge_blobs(git, head, three, paths):
    """{path: blob | None} of git's automatic merge of HEAD and `theirs` over `base` (None for the merge base),
    or None when it cannot be computed."""
    if not head or not three or not three[1] or not paths:
        return None
    base, theirs = three
    if base is None:
        out = git.run("merge-base", head, theirs, check=False)
        if out.returncode != 0:
            return None
        base = out.stdout.decode().split()[0]
    if git_version(git) >= (2, 40):
        out = git.run("merge-tree", "--write-tree", "--merge-base=%s" % base, head, theirs, check=False)
        if out.returncode in (0, 1):
            tree = out.stdout.decode().split("\n", 1)[0].strip()
            if re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", tree):
                got = git.tree_blobs(tree, paths)
                return {p: got.get(p) for p in paths}
    return _merge_file(git, base, head, theirs, paths)


def _merge_file(git, base, head, theirs, paths):
    trees = [git.tree_blobs(r, paths) for r in (base, head, theirs)]
    out = {}
    with tempfile.TemporaryDirectory(prefix="studio-merge-") as d:
        for p in paths:
            b, o, t = (tr.get(p) for tr in trees)
            if o == t:
                out[p] = o
                continue
            if b == o:
                out[p] = t
                continue
            if b == t:
                out[p] = o
                continue
            if None in (b, o, t):
                return None
            files = []
            for i, sha in enumerate((o, b, t)):
                f = os.path.join(d, str(i))
                with open(f, "wb") as fh:
                    fh.write(git.run("cat-file", "blob", sha).stdout)
                files.append(f)
            r = git.run("merge-file", "-p", *files, check=False)
            if r.returncode < 0 or r.returncode > 127:
                return None
            out[p] = git.text("hash-object", "--stdin", input=r.stdout).strip()
    return out


def new_changes(git, studio_paths, head, others, gitignore_in=False, three=None):
    """The Studio paths whose index content differs from HEAD, every other parent and git's automatic merge
    result; `.gitignore` by its Studio block."""
    revs = ([head] if head else []) + list(others)
    plain = [p for p in studio_paths if p != spaths.GITIGNORE]
    idx = git.index_blobs(plain)
    trees = [git.tree_blobs(r, plain) for r in revs]
    try:
        auto = auto_merge_blobs(git, head, three, plain) or {}
    except GitError:
        auto = {}
    out = []
    for p in plain:
        mine = idx.get(p)
        if mine == "conflict":
            out.append(p)
            continue
        if any(t.get(p) == mine for t in trees):
            continue
        if p in auto and auto[p] == mine:
            continue
        out.append(p)
    if gitignore_in:
        mine = spaths.gitignore_block(git.show(":" + spaths.GITIGNORE))
        if not any(spaths.gitignore_block(git.show("%s:%s" % (r, spaths.GITIGNORE))) == mine for r in revs):
            out.append(spaths.GITIGNORE)
    return sorted(out)
