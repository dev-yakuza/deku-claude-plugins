#!/usr/bin/env python3
"""Times guard regexes on adversarial inputs (fix-0103 §4, test_guard_regex.RegexBudget). Test tree only.

    regex_budget.py <rows.json>

Each row: {"id", "pattern", "flags", "ops", "bound", "growth", "budget_ms"}. Every input is run under its own 2 s timer (SIGALRM;
CPython's regex engine checks signals while matching). Prints one JSON line per row: the slowest (op, input) at the
row's bound (the first over the budget: the scan stops there), and — when "growth" — every input whose time grows by more than GROWTH_MAX from 4 KB to 32 KB."""

import json
import re
import signal
import sys
import time

sys.dont_write_bytecode = True
LIMIT = 2.0
GROWTH_MAX = 24.0      # linear ≈ 8, quadratic ≈ 64
GROWTH_FLOOR = 0.005   # seconds at 32 KB below which the ratio is noise (a quadratic 0.08 ms at 4 KB is 5 ms)
GROWTH_FROM = 0.0001   # inputs at least this slow at 4 KB are re-timed at 32 KB
GROWTH_TOP = 20
UNITS = ["a", "a ", " ", "\t", "/", "/a", ".", "a.", ",", "a,", "-", "-a", "=", "a=", ":", "@", "%", "_", "0",
         "$a", "${a}", "$aaaaaaaaaaaa", "$aaaaaaaaaaaa$", "\\", "\\a", "'", "'a", '"', '"a', "(", ")", "{", "}", "[a]",
         "~", "*", "?", "<", ">", "|", ";", "&", "#", "!", "`", "\n", "a\n", "x y", "a/b ", "--a=b ", "-n ", "(a)",
         "{a,b}", "[[:a:]]", "a b c=d ", "\0", "\n ", " \n\n", "1\n", "1 ", "( |", "'a=", "e", "(("]
PREFIXES = ["", "(", "arr=(", "${X::=", ": ${X::=", "alias a='", "X=", "git -c a=", "#!/bin/sh\n", "export A=", "'",
            "f "]
SUFFIXES = ["", "!", '"', "\0", "*}", ")x", "'", "`", " \\", "x{"]


class Late(BaseException):
    pass


def _late(signum, frame):
    raise Late()


def _op(p, op, s):
    if op in ("search", "match", "fullmatch"):
        getattr(p, op)(s)
    elif op == "findall":
        p.findall(s)
    elif op == "finditer":
        for _m in p.finditer(s):
            pass
    elif op in ("sub", "subn"):
        p.sub("", s)
    elif op == "split":
        p.split(s)
    else:
        raise ValueError(op)


def timed(p, op, s):
    """Seconds, or None past LIMIT: one input, one timer."""
    signal.setitimer(signal.ITIMER_REAL, LIMIT)
    try:
        t = time.perf_counter()
        _op(p, op, s)
        return time.perf_counter() - t
    except Late:
        return None
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


def best(p, op, s, n=3):
    out = []
    for _i in range(n):
        d = timed(p, op, s)
        if d is None:
            return None
        out.append(d)
    return min(out)


def text(pre, u, suf, size):
    return pre + u * max(1, (size - len(pre) - len(suf)) // len(u)) + suf


def run(row):
    p = re.compile(row["pattern"], row["flags"])
    bound = row["bound"]
    worst = (0.0, "")
    slow = []
    for op in row["ops"]:
        for u in UNITS:
            for pre in PREFIXES:
                for suf in SUFFIXES:
                    s = text(pre, u, suf, bound)
                    d = timed(p, op, s)
                    if d is not None and d > 0.05:
                        d = best(p, op, s)  # a single slow run may be the machine, not the pattern
                    label = "%s %r+%r*n+%r" % (op, pre, u, suf)
                    if d is None:
                        return {"id": row["id"], "worst_ms": None, "case": label, "growth": []}
                    if d * 1000 >= row["budget_ms"]:
                        return {"id": row["id"], "worst_ms": round(d * 1000, 3), "case": label, "growth": []}
                    if d > worst[0]:
                        worst = (d, label)
                    if d >= GROWTH_FROM:
                        slow.append((d, op, pre, u, suf))
    growth = []
    if row["growth"]:
        slow.sort(reverse=True)
        for _d, op, pre, u, suf in slow[:GROWTH_TOP]:
            t4 = best(p, op, text(pre, u, suf, bound))
            t32 = best(p, op, text(pre, u, suf, bound * 8))
            if t4 is not None and t32 is not None and t32 / max(t4, 1e-6) > GROWTH_MAX:
                t4 = best(p, op, text(pre, u, suf, bound), 7)  # once more, before calling it a failure
                t32 = best(p, op, text(pre, u, suf, bound * 8), 7)
            label = "%s %r+%r*n+%r" % (op, pre, u, suf)
            if t4 is None or t32 is None:
                growth.append({"case": label, "t4_ms": t4 and t4 * 1000, "t32_ms": None})
            elif t32 >= GROWTH_FLOOR and t32 / max(t4, 1e-6) > GROWTH_MAX:
                growth.append({"case": label, "t4_ms": round(t4 * 1000, 3), "t32_ms": round(t32 * 1000, 3)})
    return {"id": row["id"], "worst_ms": round(worst[0] * 1000, 3), "case": worst[1], "growth": growth}


def main(argv):
    signal.signal(signal.SIGALRM, _late)
    with open(argv[0], encoding="utf-8") as f:
        rows = json.load(f)
    for row in rows:
        sys.stdout.write(json.dumps(run(row)) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
