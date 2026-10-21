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
    # the same version: the copy must be the plugin's (m0f-plan Q15; line ends normalized, not git-read)
    if _manifest(os.path.join(worktree, ".claude", "studio", "scripts", "MANIFEST.sha256")) != \
            _manifest(os.path.join(PLUGIN_SCRIPTS, "MANIFEST.sha256")):
        return ("the repository's copy of Studio's scripts differs from the plugin's of the same version (edited, or "
                "another build) — /std update (M1; until then copy the plugin's scripts again)")
    edited = _edited(os.path.join(worktree, ".claude", "studio", "scripts"))
    if edited:
        return ("the repository's copy of Studio's scripts was edited (%s) — ask the person to restore it in a "
                "terminal (git checkout -- .claude/studio/scripts) or to copy the plugin's scripts again"
                % ", ".join(edited[:3]))
    return None


def _edited(scripts):
    """Files of the work tree's copy that are not what its manifest says (the copy is what Studio commands run)."""
    import hashlib
    from .. import manifest
    try:
        with open(os.path.join(scripts, manifest.NAME), encoding="utf-8") as f:
            files, _v = manifest.parse(f.read())
    except (OSError, ValueError):
        return ["MANIFEST.sha256"]
    out = []
    for rel, sha in sorted(files.items()):
        try:
            with open(os.path.join(scripts, rel), "rb") as f:
                data = f.read()
            # a checkout with CRLF line ends (core.autocrlf) is the same copy
            if hashlib.sha256(data).hexdigest() != sha and \
                    hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest() != sha:
                out.append(rel)
        except OSError:
            out.append(rel)
    return out


PLUGIN_SCRIPTS = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))


def _manifest(p):
    try:
        with open(p, "rb") as f:
            return f.read(1 << 20).replace(b"\r\n", b"\n")
    except OSError:
        return None
