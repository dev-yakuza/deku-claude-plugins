"""Which commands are script2video calls, and which lock each one needs (m0c-plan §6).

Shared with the guard (M0d-1). A call is accepted only in these forms (`p` = this work tree's s2v path,
`stdo/machine.s2v_path` — `.claude/studio/local/machine.json`, m1-plan §3.1; callers pass it in):
`s2v …`, `node <p>/packages/cli/dist/main.js …`, `yarn --cwd <p> s2v …`, `yarn s2v …` and
`npx s2v …` (cwd = p), `tsx <p>/packages/cli/src/main.ts …`.
A bare `s2v` is accepted by name only: the guard (M0d) must check that it resolves (realpath) to
that path's executable.
"""

import os

TWO_WORD = {"voice", "character", "audio", "takes", "services", "tts-server"}


def _same(a, b):
    return os.path.realpath(a) == os.path.realpath(b)


def s2v_args(argv, s2v_path, cwd):
    """The arguments after the s2v program, or None when argv is not an s2v call."""
    if not argv:
        return None
    prog = argv[0]
    base = os.path.basename(prog)
    p = s2v_path
    if prog == "s2v":
        return list(argv[1:])
    if base == "node" and len(argv) >= 2 and p and _same(argv[1], os.path.join(p, "packages", "cli", "dist", "main.js")):
        return list(argv[2:])
    if base == "tsx" and len(argv) >= 2 and p and _same(argv[1], os.path.join(p, "packages", "cli", "src", "main.ts")):
        return list(argv[2:])
    if base == "yarn":
        rest = list(argv[1:])
        where = cwd
        if len(rest) >= 2 and rest[0] == "--cwd":
            where = rest[1]
            if not os.path.isabs(where):
                where = os.path.join(cwd, where)
            rest = rest[2:]
        if rest and rest[0] == "s2v" and p and _same(where, p):
            return rest[1:]
        return None
    if base == "npx" and len(argv) >= 2 and argv[1] == "s2v" and p and _same(cwd, p):
        return list(argv[2:])
    return None


def split(args):
    """(command words, flag names): flags as `--name` (a `--name=value` counts as `--name`);
    everything after a bare `--` is ignored."""
    words, flags = [], set()
    for a in args:
        if a == "--":
            break
        if a.startswith("--"):
            flags.add(a.split("=", 1)[0])
        elif not a.startswith("-"):
            words.append(a)
    if not words:
        return (), flags
    if words[0] in TWO_WORD and len(words) >= 2:
        return (words[0], words[1]), flags
    return (words[0],), flags


def lock_kind(args):
    """'tts' | 'gen' | 'actor' for the wrapper the call needs, or None (no lock, or unknown)."""
    cmd, flags = split(args)
    frozen = "--frozen-audio" in flags
    if cmd in (("tts",), ("say",), ("import-recording",), ("audio", "prune")):
        return "tts"
    if cmd and cmd[0] == "voice" and cmd[1:] in (("create",), ("check",), ("refs",), ("train",)):
        return "tts"
    if cmd in (("render",), ("snapshot",)):
        return None if frozen else "tts"
    if cmd and cmd[0] == "character" and len(cmd) == 2:
        sub = cmd[1]
        dry, layers = "--dry-run" in flags, "--layers-only" in flags
        if sub in ("setup", "create"):
            return "gen"
        if sub == "build":
            if dry and layers:
                return None
            if dry:
                return None
            return "actor" if layers else "gen"
        if sub in ("approve", "redo", "pick"):
            return "actor"
        if sub == "review":
            return None if "--no-check" in flags else "actor"
        if sub == "missing":
            return "actor" if "--apply" in flags else None
    return None
