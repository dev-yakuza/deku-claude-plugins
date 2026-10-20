"""Where Studio keeps its per-user files, and the key of a repository (plan §3.4, m0-plan §2).

Per-user files (`studio-sandbox.json`, `studio-backup/`) live in Claude Code's configuration
folder: `$CLAUDE_CONFIG_DIR` when it is set, else `~/.claude`. `STUDIO_HOME` (tests only)
replaces that folder; the guard refuses agent commands that set it (decision D-M0-4).
"""

import hashlib
import os
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


def _git(cwd, *args):
    out = subprocess.run(["git", "-C", cwd] + list(args), capture_output=True, text=True)
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
