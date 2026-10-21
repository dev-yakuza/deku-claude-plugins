"""Scripts version mismatch (D-M0-3, m0d2-plan §8): the repository copy of Studio's scripts must be the
guard's version. Read with a regular expression (never imported)."""

import os
import re

from .. import SCRIPTS_VERSION

RE = re.compile(r'^SCRIPTS_VERSION = "(\d+)"\s*$', re.M)


def repo_version(worktree):
    """The copy's version (int), None when there is no copy, "unreadable" otherwise."""
    p = os.path.join(worktree, ".claude", "studio", "scripts", "stdo", "__init__.py")
    if not os.path.exists(os.path.join(worktree, ".claude", "studio", "scripts")):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            m = RE.search(f.read(65536))
    except OSError:
        return "unreadable"
    return int(m.group(1)) if m else "unreadable"


def problem(worktree, uses_repo_copy):
    """A sentence when Studio commands must stop, else None."""
    have = repo_version(worktree)
    mine = int(SCRIPTS_VERSION)
    if have is None:
        if uses_repo_copy:
            return "this repository has no copy of Studio's scripts"
        return None
    if have == "unreadable":
        return "the repository copy of Studio's scripts has no readable SCRIPTS_VERSION"
    if have < mine:
        return ("the repository's Studio scripts are version %d and the plugin's are %d — update them with "
                "/std update (M1; until then copy the plugin's scripts again)" % (have, mine))
    if have > mine:
        return ("the repository's Studio scripts (version %d) are newer than the plugin's (%d) — update the "
                "plugin first" % (have, mine))
    return None
