"""Temporary git repositories with a local bare remote, for engine tests (scope §6.2).

Real git, isolated from the user's configuration: every call runs with
GIT_CONFIG_GLOBAL=<tmp>/gitconfig (user, init.defaultBranch=main, no signing, hooks off),
GIT_CONFIG_NOSYSTEM=1, and no inherited GIT_* variables. Paths are realpaths (macOS
/var → /private/var), so they compare equal to what git prints.

    with tempfile.TemporaryDirectory() as tmp:
        repo = GitRepo.create(tmp, files={"README.md": "hi\\n"})   # main + bare remote "origin"
        repo.write("src/a.py", "x = 1\\n"); sha = repo.commit("add a")
        wt = repo.add_worktree(os.path.join(tmp, ".gld-repo-42"), "gld/42")
        repo.diverge_remote("gld/42", "other.txt", "x")              # for a non-ff push (E5)
"""

import os
import subprocess

_GITCONFIG = """[user]
\tname = Engine Test
\temail = engine-test@example.invalid
[init]
\tdefaultBranch = main
[commit]
\tgpgsign = false
[tag]
\tgpgsign = false
[core]
\thooksPath = /dev/null
\tfsmonitor = false
[advice]
\tdetachedHead = false
"""


def git_env(tmp, extra=None):
    """An environment for test git calls: isolated config, no inherited GIT_* variables."""
    cfg = os.path.join(tmp, "gitconfig")
    if not os.path.exists(cfg):
        with open(cfg, "w", encoding="utf-8") as f:
            f.write(_GITCONFIG)
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({"GIT_CONFIG_GLOBAL": cfg, "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0"})
    if extra:
        env.update(extra)
    return env


def run_git(cwd, *args, env, check=True, input=None):
    """Run git in `cwd`; return stdout stripped of the trailing newline."""
    p = subprocess.run(["git", *args], cwd=cwd, env=env, input=input, text=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and p.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed ({p.returncode}): {p.stderr.strip()}")
    return p.stdout.rstrip("\n") if check else p


class GitRepo:
    """A working repository (`path`) with an optional bare remote (`remote`, named origin)."""

    def __init__(self, tmp, path, remote=None):
        self.tmp = os.path.realpath(tmp)
        self.path = os.path.realpath(path)
        self.remote = os.path.realpath(remote) if remote else None
        self.env = git_env(self.tmp)

    @classmethod
    def create(cls, tmp, name="repo", files=None, with_remote=True):
        """`git init` + an initial commit of `files` ({relpath: text}); push main to a bare remote."""
        tmp = os.path.realpath(tmp)
        path = os.path.join(tmp, name)
        os.makedirs(path)
        env = git_env(tmp)
        run_git(path, "init", "-q", env=env)
        repo = cls(tmp, path)
        for rel, text in (files or {"README.md": "init\n"}).items():
            repo.write(rel, text)
        repo.commit("initial")
        if with_remote:
            remote = os.path.join(tmp, name + ".git")
            run_git(tmp, "init", "-q", "--bare", remote, env=env)
            run_git(path, "remote", "add", "origin", remote, env=env)
            run_git(path, "push", "-q", "origin", "main", env=env)
            repo.remote = os.path.realpath(remote)
        return repo

    def git(self, *args, cwd=None, check=True, input=None):
        return run_git(cwd or self.path, *args, env=self.env, check=check, input=input)

    def write(self, rel, text, cwd=None):
        full = os.path.join(cwd or self.path, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(text)
        return full

    def commit(self, message, paths=None, cwd=None):
        """Stage `paths` (default: everything) and commit; return the new HEAD SHA."""
        cwd = cwd or self.path
        if paths:
            self.git("add", "--", *paths, cwd=cwd)
        else:
            self.git("add", "-A", cwd=cwd)
        self.git("commit", "-q", "--allow-empty", "-m", message, cwd=cwd)
        return self.head(cwd)

    def head(self, cwd=None):
        return self.git("rev-parse", "HEAD", cwd=cwd)

    def status(self, cwd=None):
        """`git status --porcelain` lines (untracked included, ignored excluded)."""
        out = self.git("status", "--porcelain", "--untracked-files=all", cwd=cwd)
        return [line for line in out.splitlines() if line]

    def add_worktree(self, path, branch, base="HEAD"):
        """`git worktree add -b <branch> <path> <base>`; return the realpath of the worktree."""
        self.git("worktree", "add", "-q", "-b", branch, path, base)
        return os.path.realpath(path)

    def push(self, branch, cwd=None, force=False):
        args = ["push", "-q", "origin", f"HEAD:refs/heads/{branch}" if cwd else branch]
        if force:
            args.insert(1, "--force")
        return self.git(*args, cwd=cwd)

    def try_push(self, refspec, cwd=None):
        """Push without raising; return (returncode, stderr) — for non-fast-forward checks."""
        p = self.git("push", "origin", refspec, cwd=cwd, check=False)
        return p.returncode, p.stderr

    def clone_remote(self, name="other"):
        """A second clone of the bare remote (someone else's checkout)."""
        dest = os.path.join(self.tmp, name)
        run_git(self.tmp, "clone", "-q", self.remote, dest, env=self.env)
        return GitRepo(self.tmp, dest, self.remote)

    def diverge_remote(self, branch, rel, text, name="other"):
        """Push a commit to `branch` on the remote from another clone; return its SHA (E5)."""
        other = self.clone_remote(name)
        if branch in other.git("branch", "-r").replace("origin/", "").split():
            other.git("checkout", "-q", branch)
        else:
            other.git("checkout", "-q", "-b", branch)
        other.write(rel, text)
        sha = other.commit(f"diverge {branch}")
        other.git("push", "-q", "origin", f"{branch}:refs/heads/{branch}")
        return sha

    def remote_head(self, branch):
        """SHA of `branch` on the bare remote, or None."""
        p = run_git(self.remote, "rev-parse", "--verify", "-q", f"refs/heads/{branch}", env=self.env, check=False)
        return p.stdout.strip() or None
