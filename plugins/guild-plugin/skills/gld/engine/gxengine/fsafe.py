"""Link-refusing atomic file writes (design §7.12 S6, §5.1 engine-error) — U2.

Every engine write — state.json, log.jsonl, attempt files, procedure.yaml, worktree
prepare copies — goes through here. The 0.102 `fsafe` method: lstat every parent
component and require a plain directory, create a temp file in the same directory
with O_CREAT|O_EXCL|O_NOFOLLOW, write, fsync, os.replace. A link or a non-regular
file anywhere on the path is a security-boundary stop (StopReason.UNSAFE_PATH).

Paths are absolute. `root` (absolute) is the trusted top: components strictly below it
are checked, `root` itself is not (the engine home and the worktree root are recorded
by the engine). Without `root` every component from `/` down is checked — on macOS
that refuses `/tmp` and `/var` (both links), so callers pass a root or a realpath.
A missing parent directory is FileNotFoundError (use `make_dirs` first), not UnsafePath.
"""

import itertools
import json
import os
import stat

_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_NONBLOCK = getattr(os, "O_NONBLOCK", 0)
_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_TMP_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW | _CLOEXEC
_APPEND_FLAGS = os.O_WRONLY | os.O_APPEND | os.O_CREAT | _NOFOLLOW | _CLOEXEC
_READ_FLAGS = os.O_RDONLY | _NOFOLLOW | _NONBLOCK | _CLOEXEC

_SEQ = itertools.count()


class UnsafePath(Exception):
    """A parent component is a link / not a directory, or the target is not a regular file.

    The caller turns this into a needs_human stop with `codes.StopReason.UNSAFE_PATH`.
    `.path` is the offending component.
    """

    def __init__(self, path, why):
        self.path = path
        self.why = why
        super().__init__(f"{path}: {why}")


# --- path checks ------------------------------------------------------------------

def _components(path, root):
    """(start, [component, …]) — the trusted start and the names below it down to `path`."""
    if not isinstance(path, str) or not os.path.isabs(path):
        raise UnsafePath(path, "not an absolute path")
    if "\0" in path:
        raise UnsafePath(path, "NUL in path")
    norm = os.path.normpath(path)
    if norm != path.rstrip("/") and norm != path:
        # `a/./b`, `a//b`, `a/../b`: refuse rather than guess what the caller meant.
        raise UnsafePath(path, "not a normalised path")
    if root is None:
        start = "/"
    else:
        if not isinstance(root, str) or not os.path.isabs(root):
            raise UnsafePath(root, "root is not an absolute path")
        start = os.path.normpath(root)
    if start == "/":
        rel = norm.lstrip("/")
    else:
        if norm == start:
            return start, []
        if not norm.startswith(start + "/"):
            raise UnsafePath(path, f"outside the root {start}")
        rel = norm[len(start) + 1:]
    return start, [p for p in rel.split("/") if p]


def _lstat(path):
    try:
        return os.lstat(path)
    except FileNotFoundError:
        return None


def check_parents(path, root=None):
    """lstat every component of `path`'s parent (from `root`, if given) and require plain dirs.

    Raises UnsafePath on the first symlink or non-directory. `root` itself is trusted.
    A missing component raises FileNotFoundError.
    """
    start, parts = _components(path, root)
    if not parts:
        raise UnsafePath(path, "the target is the root itself")
    cur = start
    for name in parts[:-1]:
        cur = os.path.join(cur, name)
        st = _lstat(cur)
        if st is None:
            raise FileNotFoundError(cur)
        if stat.S_ISLNK(st.st_mode):
            raise UnsafePath(cur, "symlink on the path")
        if not stat.S_ISDIR(st.st_mode):
            raise UnsafePath(cur, "not a directory")
    return os.path.join(start, *parts)


def _check_leaf(target):
    """An existing target must be a regular file (never a link, dir, fifo, socket, device)."""
    st = _lstat(target)
    if st is None:
        return None
    if stat.S_ISLNK(st.st_mode):
        raise UnsafePath(target, "the target is a symlink")
    if not stat.S_ISREG(st.st_mode):
        raise UnsafePath(target, "the target is not a regular file")
    return st


def _tmp_name(target):
    """A short unique temp name beside `target` (same directory → os.replace is atomic)."""
    return os.path.join(os.path.dirname(target), ".gx-%d-%d-%s.tmp" % (
        os.getpid(), next(_SEQ), os.urandom(3).hex()))


def _fsync_dir(d):
    try:
        fd = os.open(d, os.O_RDONLY | _CLOEXEC)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


# --- writes -----------------------------------------------------------------------

def write_bytes(path, data, root=None, mode=0o644):
    """Atomically replace `path` with `data` (temp O_CREAT|O_EXCL|O_NOFOLLOW → os.replace).

    Refuses (UnsafePath) when a parent is unsafe or an existing `path` is not a regular file.
    """
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("data must be bytes")
    target = check_parents(path, root)
    _check_leaf(target)
    tmp = _tmp_name(target)
    fd = os.open(tmp, _TMP_FLAGS, mode)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        # Re-check just before the swap: os.replace never follows a link at `target`
        # (it replaces the name), but a parent swapped since the first check must stop us.
        check_parents(path, root)
        _check_leaf(target)
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    _fsync_dir(os.path.dirname(target))
    return target


def write_text(path, text, root=None, mode=0o644):
    """`write_bytes` with UTF-8 text."""
    if not isinstance(text, str):
        raise TypeError("text must be str")
    return write_bytes(path, text.encode("utf-8"), root=root, mode=mode)


def dumps_json(obj):
    """The engine's JSON text: UTF-8, indent 2, key order kept, trailing newline.

    NaN / Infinity are refused (not JSON).
    """
    return json.dumps(obj, indent=2, ensure_ascii=False, allow_nan=False) + "\n"


def write_json(path, obj, root=None):
    """Atomically write `obj` as UTF-8 JSON (indent 2, sorted keys off, trailing newline)."""
    return write_text(path, dumps_json(obj), root=root)


def append_line(path, line, root=None):
    """Append one line (no newline inside) to an append-only file, O_APPEND|O_NOFOLLOW.

    Used for log.jsonl. Creates the file if missing; refuses links like write_bytes.
    The line is written with one write(2) call so concurrent appenders never interleave.
    """
    if not isinstance(line, str):
        raise TypeError("line must be str")
    if "\n" in line or "\r" in line:
        raise ValueError("a log line must not contain a newline")
    target = check_parents(path, root)
    _check_leaf(target)
    try:
        fd = os.open(target, _APPEND_FLAGS, 0o644)
    except OSError as e:
        # ELOOP: a link appeared at the leaf between the check and the open.
        raise UnsafePath(target, f"cannot open without following links ({e.__class__.__name__})")
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise UnsafePath(target, "the target is not a regular file")
        data = (line + "\n").encode("utf-8")
        n = os.write(fd, data)
        if n != len(data):
            raise OSError(f"short write to {target}: {n} of {len(data)} bytes")
        os.fsync(fd)
    finally:
        os.close(fd)
    return target


def make_dirs(path, root=None, mode=0o700):
    """mkdir -p that refuses to pass through or end at a symlink."""
    start, parts = _components(path, root)
    cur = start
    for name in parts:
        cur = os.path.join(cur, name)
        st = _lstat(cur)
        if st is None:
            try:
                os.mkdir(cur, mode)
            except FileExistsError:
                pass
            st = os.lstat(cur)
        if stat.S_ISLNK(st.st_mode):
            raise UnsafePath(cur, "symlink on the path")
        if not stat.S_ISDIR(st.st_mode):
            raise UnsafePath(cur, "not a directory")
    return cur


# --- reads ------------------------------------------------------------------------

def read_bytes(path, root=None, max_bytes=None):
    """Read a regular file without following a link anywhere on the path.

    Parents are checked like a write; the leaf is opened O_NOFOLLOW|O_NONBLOCK and
    re-checked with fstat (a FIFO never blocks, a swapped-in link fails to open).
    FileNotFoundError when it does not exist.
    """
    target = check_parents(path, root)
    if _check_leaf(target) is None:
        raise FileNotFoundError(target)
    try:
        fd = os.open(target, _READ_FLAGS)
    except FileNotFoundError:
        raise
    except OSError as e:
        raise UnsafePath(target, f"cannot open without following links ({e.__class__.__name__})")
    with os.fdopen(fd, "rb") as fh:
        st = os.fstat(fh.fileno())
        if not stat.S_ISREG(st.st_mode):
            raise UnsafePath(target, "the target is not a regular file")
        if max_bytes is not None and st.st_size > max_bytes:
            raise UnsafePath(target, f"larger than {max_bytes} bytes")
        return fh.read()


def copy_file(src, dst, root=None, src_root=None):
    """Copy one regular file without following links on either side (worktree prepare, S6).

    Refuses (UnsafePath) when `src` is not a regular file or a `dst` parent is unsafe.
    `src_root`, when given, also checks every parent of `src` below it. The copy keeps
    the permission bits of `src` (setuid/setgid/sticky dropped).
    """
    if src_root is not None:
        check_parents(src, src_root)
    elif not os.path.isabs(src):
        raise UnsafePath(src, "not an absolute path")
    st = _lstat(src)
    if st is None:
        raise FileNotFoundError(src)
    if not stat.S_ISREG(st.st_mode):
        raise UnsafePath(src, "the source is not a regular file")
    try:
        fd = os.open(src, _READ_FLAGS)
    except OSError as e:
        raise UnsafePath(src, f"cannot open without following links ({e.__class__.__name__})")
    with os.fdopen(fd, "rb") as fh:
        fst = os.fstat(fh.fileno())
        if not stat.S_ISREG(fst.st_mode):
            raise UnsafePath(src, "the source is not a regular file")
        data = fh.read()
    return write_bytes(dst, data, root=root, mode=fst.st_mode & 0o777)
