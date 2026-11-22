"""guildcore.adapters.git — the ONE way engine code runs git (K1r2-M4).

Every engine git call goes through `run()`: hooks are off (`-c core.hooksPath=/dev/null` — a
hook definition a role could edit, tracked `.husky/` or lefthook-installed `.git/hooks/*`, must
never run outside the sandbox on the engine's commit/push), fsmonitor off, no system config, no
prompts. Pushes go to a URL fixed by the caller, never a remote NAME a role could have
re-pointed. `tests/engine/test_k1_review_r2.py` statically asserts no other engine module
spawns a mutating git command.
"""

import os
import re
import subprocess

SAFE_ARGS = ("-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false")
READ_VERBS = ("rev-parse", "show", "cat-file", "archive", "status", "symbolic-ref", "for-each-ref",
              "merge-base", "diff", "config", "remote", "ls-remote", "ls-files", "log", "rev-list")


class GitError(Exception):
    pass


def env(base=None):
    e = dict(os.environ if base is None else base)
    e.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0"})
    return e


def run(cwd, *args, check=True, input=None, timeout=None):
    """`git <SAFE_ARGS> <args>` in cwd → stdout bytes (CalledProcess-style error on failure)."""
    p = subprocess.run(["git"] + list(SAFE_ARGS) + list(args), cwd=cwd, env=env(), input=input,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if check and p.returncode != 0:
        raise GitError("git %s: %s" % (" ".join(args), p.stderr.decode("utf-8", "replace").strip()))
    return p.stdout


def ok(cwd, *args):
    """True when `git <SAFE_ARGS> <args>` exits 0 (an existence probe: `cat-file -e rev:path`)."""
    p = subprocess.run(["git"] + list(SAFE_ARGS) + list(args), cwd=cwd, env=env(),
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return p.returncode == 0


def remote_names(cwd):
    return [x for x in run(cwd, "remote", check=False).decode().split() if x]


def is_fixed_url(cwd, url):
    """A URL, an absolute path or an scp-style `[user@]host:path` (git@github.com:o/r.git,
    git@personal:o/r.git — K1r3-M4) — never the NAME of a configured remote."""
    if not url or url in remote_names(cwd):
        return False
    if "://" in url or os.path.isabs(url):
        return True
    return bool(re.match(r"^(?:[^@/\s]+@)?[^:/\s]+:[^\s]+$", url))


def push(cwd, url, refspec, force=False):
    """The engine's push: to a fixed URL (resolved before any role ran), hooks off."""
    if not is_fixed_url(cwd, url):
        raise GitError("push needs a fixed URL, not a remote name: %r" % url)
    return run(cwd, "push", *(["--force-with-lease"] if force else []), url, refspec)


def commit(cwd, message, paths=None):
    if paths:
        run(cwd, "add", "--", *paths)
    return run(cwd, "commit", "-m", message)


def standalone_repo(tree, names, timeout=600):
    """0.102.16 (one-man-company #687, lead decision 2): an INDEPENDENT git repository in an engine temp tree — a
    pristine copy has no `.git`, and a test that runs `git rev-parse` / `git ls-files` in it (a full-sweep scanner)
    failed outside a work tree. `git init`, then exactly `names` (repo-relative paths of regular files / links present in
    the tree — the worktree's tracked files) added and committed once. No remote, alternates, commondir or any link to
    another repository; no template (no hook samples), hooks off for the commit and in the repo's own config, no
    signing, no auto maintenance / gc. The environment is the engine's with every GIT_* dropped and an empty global and
    no system config, so nothing of the person's or the main repo's git config is read. Returns the number of paths
    committed. Raises GitError on a git failure."""
    e = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    e.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0",
              "GIT_LITERAL_PATHSPECS": "1", "GIT_CEILING_DIRECTORIES": os.path.dirname(os.path.abspath(tree))})
    ident = ["-c", "user.name=engine", "-c", "user.email=engine@guild.invalid", "-c", "commit.gpgsign=false",
             "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-c", "init.defaultBranch=main"]

    def g(*args, inp=None):
        p = subprocess.run(["git"] + ident + list(args), cwd=tree, env=e, input=inp, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=timeout)
        if p.returncode != 0:
            raise GitError("git %s: %s" % (args[0], p.stderr.decode("utf-8", "replace").strip()[:300]))
        return p.stdout
    g("init", "-q", "--template=", ".")
    for k, v in (("core.hooksPath", "/dev/null"), ("maintenance.auto", "false"), ("gc.auto", "0"),
                 ("commit.gpgsign", "false"), ("user.name", "engine"), ("user.email", "engine@guild.invalid")):
        g("config", "--local", k, v)
    names = [n for n in names if n]
    if names:
        g("add", "-f", "--pathspec-from-file=-", "--pathspec-file-nul", inp="\0".join(names).encode("utf-8") + b"\0")
    g("commit", "-q", "--no-verify", "--allow-empty", "-m", "engine: temp tree")
    return len(names)
