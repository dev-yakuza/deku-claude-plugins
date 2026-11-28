#!/usr/bin/env -S python3 -I
"""Plugin check script `ac-format` (design §3.1 start procedure, I6) — U15.

Contract of every plugin check script (codes.PluginCommand):
  run by the engine under srt with the developer boundary, cwd = the Issue worktree,
  `python3 -I <plugin root>/skills/gld/engine/scripts/<script>.py --issue <N>`
  (ac-format also takes `--stage <n>` — the engine stage, 2 when absent — and, from stage 3,
  `--deferred R3,R5` — the requirement rows a replan deferred, E30);
  exit 0 = pass, 1 = fail (reasons on stdout, one per line), 2 = cannot judge (also red).
  Writes nothing (the tree must stay clean, §4.4-2).

ac-format: docs/specs/<N>/analysis.md has a parseable AC set and the analysis structure
fields (gxengine.acparse.check_format). on_fail back_to analyze (max 2) — plugin-fixed.
The priority mark is written `(must)` / `(should)` (lint-safe); it is part of the AC text
and not checked, so the old `[must]` still passes.
Exit 2: the file is a link / not a regular file / not UTF-8, bad arguments, or a crash.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from gxengine import acparse  # noqa: E402


USAGE = "usage: ac_format.py --issue <N> [--stage <n>] [--deferred R3,R5]\n"


def _number(text):
    return int(text) if text.isascii() and text.isdigit() and int(text) >= 1 else None


def _rows(text):
    rows = text.split(",")
    return rows if len(set(rows)) == len(rows) and all(acparse.ROW_ID.fullmatch(r) for r in rows) else None


OPTIONS = {"--issue": ("issue", _number), "--stage": ("stage", _number), "--deferred": ("deferred", _rows)}


def parse_args(argv):
    """{"issue", "stage", "deferred"} from `--issue <N> [--stage <n>] [--deferred R3,R5]` (each
    option once, any order; --deferred needs stage ≥ 3); None when the arguments are anything
    else (fail-closed)."""
    if len(argv) % 2:
        return None
    out = {}
    for opt, value in zip(argv[::2], argv[1::2]):
        key, read = OPTIONS.get(opt, (None, None))
        if key is None or key in out:
            return None
        out[key] = read(value)
        if out[key] is None:
            return None
    if "issue" not in out or ("deferred" in out and out.get("stage", 2) < 3):
        return None
    return {"stage": 2, "deferred": [], **out}


def main(argv):
    args = parse_args(argv)
    if args is None:
        sys.stderr.write(USAGE)
        return acparse.EXIT_CANNOT_JUDGE
    try:
        code, lines = acparse.check_format(os.getcwd(), args["issue"], args["stage"], args["deferred"])
    except Exception as e:  # a crash is "cannot judge", never a pass
        sys.stderr.write(f"ac-format: internal error — NOT judged ({type(e).__name__}: {e})\n")
        return acparse.EXIT_CANNOT_JUDGE
    for line in lines:
        sys.stdout.write(line + "\n")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
