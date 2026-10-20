"""How lock.py reads its arguments (m0c-plan §6), shared with the guard's scanner (M0d-1a §6.4)
so the guard expands `lock.py run|actor-op … -- <child>` exactly as lock.py does."""


class UsageError(Exception):
    """Usage or setup problem (exit 2), found before any lock is taken (re-exported by locks)."""


def parse(argv):
    """lock.py arguments -> opts dict; raises UsageError (no side effects)."""
    if not argv:
        raise UsageError("usage: lock.py run|actor-op|status …")
    cmd, rest = argv[0], argv[1:]
    child = []
    if "--" in rest:
        i = rest.index("--")
        rest, child = rest[:i], rest[i + 1:]
    opts = {"cmd": cmd, "child": child, "ids": [], "actors": [], "json": False, "kind": None,
            "holder": None}
    it = iter(rest)
    for a in it:
        if cmd == "run" and a == "--kind":
            opts["kind"] = next(it, None)
        elif cmd == "run" and a == "--holder":
            opts["holder"] = next(it, None)
        elif cmd == "status" and a == "--actor":
            opts["actors"].append(next(it, None))
        elif cmd == "status" and a == "--json":
            opts["json"] = True
        elif cmd == "actor-op" and not a.startswith("-"):
            opts["ids"].append(a)
        else:
            raise UsageError("unknown argument for %s: %s" % (cmd, a))
    if cmd == "run":
        if opts["kind"] not in ("tts", "gen"):
            raise UsageError("run needs --kind tts|gen")
    elif cmd == "actor-op":
        if not opts["ids"]:
            raise UsageError("actor-op needs at least one actor id")
    elif cmd != "status":
        raise UsageError("unknown command: %s" % cmd)
    if cmd in ("run", "actor-op") and not child:
        raise UsageError("%s needs the s2v command after --" % cmd)
    return opts
