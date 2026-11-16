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
