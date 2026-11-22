"""guildcore.gitshim — the engine's `git` shim (0.102.16, one-man-company #687).

Every engine-run command in a check sandbox and every role gets the engine's rendered global git config
(`GIT_CONFIG_GLOBAL=<run_dir>/in/gitconfig`, `GIT_CONFIG_NOSYSTEM=1` — `settings.render_gitconfig`), because the
sandbox denies reading `~/.gitconfig` and git aborts on an unreadable global config (`fatal: unable to access
'~/.gitconfig': Operation not permitted`, rc 128). A repo's own test helpers that strip every `GIT_*` variable before
spawning git (`includeParentEnvironment: false` + `removeWhere((k, _) => k.startsWith('GIT_'))` — #687's
secret_path_scan_gate / verify_freshness_gate tests) dropped exactly those two variables → 20 env-only failures.

The shim (first on PATH) puts them back, and only then: `GIT_CONFIG_GLOBAL` is UNSET (a caller that set it, even
empty, is left alone) and `HOME` is the real home (a caller that moved HOME reads its own global config). It then
execs the real git, resolved to an absolute path when the shim is written (never through PATH — no self-loop)."""

import os
import shutil

from guildcore import fsafe as FS

NAME = "git"
_TEXT = """#!/bin/sh
# guild engine git shim (0.102.16) — engine-owned. A caller that stripped GIT_* gets the engine's global git config
# back (the sandbox denies ~/.gitconfig); everything else passes through unchanged.
if [ -z "${GIT_CONFIG_GLOBAL+x}" ] && [ "${HOME-}" = %(home)s ]; then
  GIT_CONFIG_GLOBAL=%(cfg)s
  GIT_CONFIG_NOSYSTEM=1
  export GIT_CONFIG_GLOBAL GIT_CONFIG_NOSYSTEM
fi
exec %(real)s "$@"
"""


def _q(s):
    return "'" + str(s).replace("'", "'\\''") + "'"


def real_home():
    """The account's home directory (not `$HOME`, which a caller may have moved)."""
    try:
        import pwd
        return pwd.getpwuid(os.getuid()).pw_dir
    except (ImportError, KeyError):
        return os.path.expanduser("~")


def text(real, gitconfig, home=None):
    return _TEXT % {"real": _q(real), "cfg": _q(gitconfig), "home": _q(home or real_home())}


def resolve(path, exclude_dirs=()):
    """The real git on `path` with `exclude_dirs` (the shim dirs) left out, as an absolute path — or None."""
    ex = set(os.path.realpath(d) for d in exclude_dirs if d)
    search = os.pathsep.join(d for d in (path or "").split(os.pathsep) if d and os.path.realpath(d) not in ex)
    real = shutil.which(NAME, path=search)
    if not real:
        return None
    real = os.path.abspath(real)
    if os.path.realpath(os.path.dirname(real)) in ex:
        return None
    return real


def gitconfig_of(env, run_dir):
    """The engine's rendered global config for this run: the env's `GIT_CONFIG_GLOBAL`, else `<run_dir>/in/gitconfig`
    when it exists, else the empty config (`/dev/null`)."""
    g = (env or {}).get("GIT_CONFIG_GLOBAL")
    if g:
        return g
    p = os.path.join(os.path.abspath(run_dir), "in", "gitconfig")
    return p if os.path.isfile(p) else os.devnull


def write(owner, rel_dir, env, run_dir):
    """Write `<owner>/<rel_dir>/git` (fsafe — never through a link) and return the shim dir, or None when no git is on
    the env's PATH."""
    sdir = os.path.join(os.path.abspath(owner), rel_dir)
    real = resolve((env or {}).get("PATH") or "", (sdir,))
    if not real:
        return None
    FS.write_text(os.path.abspath(owner), os.path.join(rel_dir, NAME), text(real, gitconfig_of(env, run_dir)),
                  mode=0o755)
    return sdir
