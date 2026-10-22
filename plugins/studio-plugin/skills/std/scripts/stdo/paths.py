"""Where Studio keeps its per-user files, and the key of a repository (plan §3.4, m0-plan §2).

Per-user files (`studio-sandbox.json`, `studio-backup/`) live in Claude Code's configuration
folder: `$CLAUDE_CONFIG_DIR` when it is set, else `~/.claude`. `STUDIO_HOME` (tests only)
replaces that folder; the guard refuses agent commands that set it (decision D-M0-4).
"""

import hashlib
import os
import stat
import subprocess

STUDIO_HOME_ENV = "STUDIO_HOME"


def user_dir(env=None):
    """The folder that holds Studio's per-user files (absolute)."""
    env = os.environ if env is None else env
    for name in (STUDIO_HOME_ENV, "CLAUDE_CONFIG_DIR"):
        value = env.get(name)
        if value:
            if not os.path.isabs(value):
                raise ValueError("%s must be an absolute path: %r" % (name, value))
            return os.path.normpath(value)
    home = env.get("HOME") or os.path.expanduser("~")
    return os.path.join(home, ".claude")


def sandbox_file(env=None):
    return os.path.join(user_dir(env), "studio-sandbox.json")


def backup_root(env=None):
    return os.path.join(user_dir(env), "studio-backup")


# git variables that would point these lookups at another repository (a copied .git with its own used-answer record,
# m1-plan §3.2 review U2): Studio's own lookups always ask the work tree they are given
GIT_REDIRECT = ("GIT_DIR", "GIT_COMMON_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
                "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE", "GIT_CEILING_DIRECTORIES",
                "GIT_DISCOVERY_ACROSS_FILESYSTEM")


def git_env(env=None):
    env = dict(os.environ if env is None else env)
    for k in GIT_REDIRECT:
        env.pop(k, None)
    return env


def _git(cwd, *args):
    out = subprocess.run(["git", "-C", cwd] + list(args), capture_output=True, text=True, env=git_env())
    if out.returncode != 0:
        raise RuntimeError("git %s failed in %s: %s" % (" ".join(args), cwd, out.stderr.strip()))
    return out.stdout.strip()


def _key(path):
    return hashlib.sha256(os.path.realpath(path).encode("utf-8")).hexdigest()[:16]


def common_key(repo):
    """Key of a repository shared by its worktrees: hash of the absolute git common dir."""
    common = _git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return _key(common)


def repo_key(repo):
    """Key of one checkout (worktree or clone): hash of its absolute top level."""
    return _key(_git(repo, "rev-parse", "--show-toplevel"))


def marker_path(repo, env=None):
    return os.path.join(backup_root(env), common_key(repo), "marker")


# ---------- the used-answer record (m1-plan §3.2, D-M1-1b) ----------
# One record per repository, shared by its worktrees: `<git common dir>/studio/` (next to the pre-commit runner,
# untracked and protected by the guard as a hook folder). An answer is used once in the whole repository.

CONSUMED_LOG = "consumed-answers.jsonl"
CONSUMED_LOCK = "consumed-answers.lock"


def common_dir(repo):
    return _git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")


def studio_common(repo, common=None):
    """`<git common dir>/studio` (pass `common` when it is known already — the guard runs no git here)."""
    return os.path.join(common if common is not None else common_dir(repo), "studio")


def consumed_log(repo, common=None):
    return os.path.join(studio_common(repo, common), CONSUMED_LOG)


def consumed_lock(repo, common=None):
    return os.path.join(studio_common(repo, common), CONSUMED_LOCK)


# ---------- the machine-local folders (m1-plan §3.1 review U1) ----------
# `.claude/studio/local/` (machine.json, pending-approval.json, commit-ok.json, guard-ran.json) and `<sr>/local/` must
# be real folders inside the work tree. A symbolic link there (a new worktree has no local/ yet) would let anything
# that writes the link's target forge this machine's files, so every reader and writer refuses it (closed).

LOCAL = (".claude", "studio", "local")


class UnsafeLocal(Exception):
    """A machine-local folder (or a folder above it) is a symbolic link or not a folder."""


def local_problem(repo, studio_root=None):
    """None when the machine-local folders are absent or real folders in the work tree; else the reason."""
    chains = [LOCAL]
    if studio_root:
        chains.append(tuple(x for x in studio_root.strip("/").split("/") if x) + ("local",))
    for chain in chains:
        cur = repo
        for part in chain:
            cur = os.path.join(cur, part)
            try:
                st = os.lstat(cur)
            except FileNotFoundError:
                break
            except OSError as e:
                return "cannot check %s (%s)" % (os.path.relpath(cur, repo), e)
            rel = os.path.relpath(cur, repo)
            if stat.S_ISLNK(st.st_mode):
                return ("%s is a symbolic link — Studio does not read or write this machine's files through a link. "
                        "Ask the person to remove the link and create the folder (mkdir) again" % rel)
            if not stat.S_ISDIR(st.st_mode):
                return "%s is not a folder — ask the person to move it away" % rel
    return None


def check_local(repo, studio_root=None):
    why = local_problem(repo, studio_root)
    if why:
        raise UnsafeLocal(why)


def _local_id(repo):
    st = os.lstat(os.path.join(repo, *LOCAL))
    return st.st_dev, st.st_ino


CHANGED = "%s changed while it was read — retry; if it happens again, ask the person to check that folder"


def read_local(repo, name):
    """The bytes of `.claude/studio/local/<name>` (None when absent), read without following a link: the folders are
    checked, the file is opened with O_NOFOLLOW, and the folder is checked again after the open (same device and
    inode) — a link swapped in between is refused (UnsafeLocal)."""
    check_local(repo)
    try:
        before = _local_id(repo)
    except FileNotFoundError:
        return None
    p = os.path.join(repo, *(LOCAL + (name,)))
    try:
        fd = os.open(p, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
    except FileNotFoundError:
        return None
    except OSError as e:
        if os.path.islink(p):
            raise UnsafeLocal("%s is a symbolic link — Studio does not read it" % os.path.join(*(LOCAL + (name,))))
        raise
    try:
        with os.fdopen(fd, "rb") as f:
            fd = None
            data = f.read()
            opened = os.fstat(f.fileno())
    finally:
        if fd is not None:
            os.close(fd)
    check_local(repo)
    try:
        after = _local_id(repo)
        now = os.lstat(p)
    except OSError:
        raise UnsafeLocal(CHANGED % os.path.join(*LOCAL))
    if after != before or (now.st_dev, now.st_ino) != (opened.st_dev, opened.st_ino):
        raise UnsafeLocal(CHANGED % os.path.join(*LOCAL))
    return data
