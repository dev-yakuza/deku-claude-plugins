"""The canonical form of a state.py command line (shared with the guard, M0d-2; m0b2-plan §1):
`{"cmd", "pos": [...], "opt": {name: value | true}}` — option order and `--x=v` / `--x v` do not
matter (state.py's CLI accepts both spellings too, so the guard and state.py agree whichever the
agent wrote). Flags that take no value are listed in FLAGS."""

from .hashes import hash_of

FLAGS = frozenset(["--proxy", "--begin", "--end", "--json"])


def canonical(argv):
    if not argv:
        raise ValueError("empty command line")
    cmd, rest = argv[0], list(argv[1:])
    pos, opt = [], {}
    i = 0
    while i < len(rest):
        a = rest[i]
        if a.startswith("--"):
            if "=" in a:
                k, v = a.split("=", 1)
                opt[k] = v
            elif a in FLAGS:
                opt[a] = True
            else:
                if i + 1 >= len(rest):
                    raise ValueError("%s needs a value" % a)
                opt[a] = rest[i + 1]
                i += 1
        else:
            pos.append(a)
        i += 1
    return {"cmd": cmd, "pos": pos, "opt": opt}


def argv_sha(argv):
    return hash_of(canonical(argv))
