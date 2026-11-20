"""guildcore.fsafe — the ONE way the engine writes into a tree a role (or role-written code) could have
shaped: the Issue worktree, a temp tree materialized from the branch, a check run's tmp (K3r6-B1).

The engine runs unsandboxed; a symlink a role planted (`ln -s ~/.zshrc .cspell.json`, a `dict -> ~/x`
directory, a committed symlink a `git archive` reproduces) must never redirect an engine write out of
the tree. Every operation here:
  * takes `root` + a RELATIVE path (no absolute path, no `..` after normalisation);
  * lstat()s EVERY existing component under `root` and refuses a symlink anywhere on the way (the
    leaf too, unless the operation replaces/removes the link itself);
  * asserts the realpath of the parent is inside realpath(root);
  * writes through a temp file created with O_CREAT|O_EXCL|O_NOFOLLOW in the same directory, then
    `os.replace` (atomic; a link swapped in between is replaced, never followed).
`tests/engine/test_k3_r6.py` lints the engine: no raw write call outside this module unless the line
says `# fs-ok: <why>` (engine-owned, role-unreachable paths only).
"""

import itertools
import os
import shutil
import stat

FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)


class UnsafePath(Exception):
    pass


_SEQ = itertools.count()


def tmp_name(target, tag=""):
    """The temp name beside `target` — unique per CALL (review-k6-r9 m1: a pid-only name collided when two threads of
    one engine wrote the same leaf) and SHORT, whatever the leaf (review-k6-r10 m2: a name carrying the leaf hit
    ENAMETOOLONG for a ~210-byte leaf): `.engine<tag>-<pid>-<process counter>-<6 hex>.tmp`, ≤ ~50 bytes. Same
    directory, so `os.replace` stays atomic (the last writer wins). The one helper for every engine temp name
    (`journal.atomic_write`, the read-only exports of `roles/settings` — review-k6-r10 m5)."""
    return os.path.join(os.path.dirname(target), ".engine%s-%d-%d-%s.tmp" % (
        tag, os.getpid(), next(_SEQ), os.urandom(3).hex()))


def _parts(rel):
    if not rel or os.path.isabs(rel):
        raise UnsafePath("not a relative path: %r" % rel)
    n = os.path.normpath(rel)
    if n == "." or n.startswith("..") or "/../" in "/%s/" % n:
        raise UnsafePath("path escapes the root: %r" % rel)
    return n.split(os.sep)


def resolve(root, rel, leaf_link_ok=False):
    """Absolute target for `rel` under `root` after the checks (missing components are fine)."""
    parts = _parts(rel)
    real_root = os.path.realpath(root)
    cur = root
    for i, part in enumerate(parts):
        cur = os.path.join(cur, part)
        try:
            st = os.lstat(cur)
        except FileNotFoundError:
            break
        if stat.S_ISLNK(st.st_mode) and not (leaf_link_ok and i == len(parts) - 1):
            raise UnsafePath("symlink on the path: %s" % os.path.relpath(cur, root))
    target = os.path.join(root, *parts)
    parent = os.path.realpath(os.path.dirname(target))
    if parent != real_root and not parent.startswith(real_root + os.sep):
        raise UnsafePath("outside the root: %r" % rel)
    return target


def makedirs(root, rel):
    """Create the directories of `rel` (relative to root) one by one, refusing symlinks."""
    if rel in ("", "."):
        return root
    cur = root
    for part in _parts(rel):
        cur = os.path.join(cur, part)
        try:
            st = os.lstat(cur)
            if stat.S_ISLNK(st.st_mode):
                raise UnsafePath("symlink on the path: %s" % os.path.relpath(cur, root))
            if not stat.S_ISDIR(st.st_mode):
                raise UnsafePath("not a directory: %s" % os.path.relpath(cur, root))
        except FileNotFoundError:
            os.mkdir(cur)
    resolve(root, rel)
    return cur


def write_bytes(root, rel, data, mode=0o644, replace_link=False):
    """Atomic write of `data` to root/rel. A symlink leaf is refused (`replace_link`: replaced as a
    link — the target is never written)."""
    target = resolve(root, rel, leaf_link_ok=replace_link)
    d = os.path.dirname(rel)
    if d:
        makedirs(root, d)
    tmp = tmp_name(target, "")
    fd = os.open(tmp, FLAGS, mode)                       # O_EXCL: a name already there is never reused
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return target


def write_text(root, rel, text, mode=0o644):
    return write_bytes(root, rel, text.encode("utf-8"), mode)


def read_nofollow(path, max_bytes=None):
    """K3r7-m3 (defence in depth): read a regular file without following a link swapped in after the
    caller's lstat — O_NOFOLLOW + fstat re-check on the open descriptor. Returns (bytes, st_mode)."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))  # a FIFO never blocks
    except OSError as e:
        raise UnsafePath("cannot open without following links: %s (%s)" % (path, e.__class__.__name__))
    with os.fdopen(fd, "rb") as fh:
        st = os.fstat(fh.fileno())
        if not stat.S_ISREG(st.st_mode):
            raise UnsafePath("not a regular file: %s" % path)
        if max_bytes is not None and st.st_size > max_bytes:
            raise UnsafePath("larger than %d bytes: %s" % (max_bytes, path))
        return fh.read(), st.st_mode


def copy_in(root, rel, src, mode=None):
    """Copy the regular file `src` (never through a link) to root/rel."""
    st = os.lstat(src)
    if not stat.S_ISREG(st.st_mode):
        raise UnsafePath("source is not a regular file: %s" % src)
    data, m = read_nofollow(src)
    return write_bytes(root, rel, data, mode if mode is not None else (m & 0o777))


def copytree_in(root, rel, src, skip=()):
    """Copy a directory tree into root/rel; symlinks inside `src` are skipped, never followed; directory
    names in `skip` are left out."""
    makedirs(root, rel)
    for base, dirs, files in os.walk(src):
        relbase = os.path.relpath(base, src)
        dirs[:] = [x for x in dirs if not os.path.islink(os.path.join(base, x)) and x not in skip]
        for x in dirs:
            makedirs(root, os.path.normpath(os.path.join(rel, relbase, x)))
        for f in files:
            sp = os.path.join(base, f)
            if os.path.islink(sp) or not os.path.isfile(sp):
                continue
            copy_in(root, os.path.normpath(os.path.join(rel, relbase, f)), sp)


def remove(root, rel):
    """Remove the file/link root/rel (a leaf link is removed as a link)."""
    target = resolve(root, rel, leaf_link_ok=True)
    try:
        os.unlink(target)
    except FileNotFoundError:
        pass


def rmtree(root, rel):
    target = resolve(root, rel, leaf_link_ok=True)
    if os.path.islink(target):
        os.unlink(target)
    elif os.path.isdir(target):
        shutil.rmtree(target, True)
    elif os.path.exists(target):
        os.unlink(target)


def symlink(root, rel, dest):
    """Atomically make root/rel a symlink to `dest` (replacing a link or a file — a real directory
    there is removed first)."""
    target = resolve(root, rel, leaf_link_ok=True)
    if os.path.isdir(target) and not os.path.islink(target):
        shutil.rmtree(target, True)
    tmp = tmp_name(target, "-link")
    os.symlink(dest, tmp)                                # fails on an existing name — never follows or reuses one
    try:
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return target
