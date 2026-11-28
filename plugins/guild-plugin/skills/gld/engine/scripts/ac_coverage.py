#!/usr/bin/env -S python3 -I
"""Plugin check script `ac-coverage` (design §7.1 AC check, I6) — U15.

Same contract as ac_format.py. Passes when every AC of analysis.md is referenced by
docs/specs/<N>/test-cases.md (document-level link only — no test-name ↔ code matching,
§7.1) and test-cases.md references no AC analysis.md does not define. Same parser as
ac-format (gxengine.acparse.check_coverage); an unparseable AC-like token fails
(fail-closed). A reference is a heading or a case tag `(AC #2)` / `(AC #2, #5)` at the end
(or start) of a case line or table cell; the old `[AC #2]` is still read; an AC named only
in prose is reported with a hint (rules: the gxengine.acparse module doc).
Exit 2: unreadable / non-regular file, bad arguments, or a crash.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from gxengine import acparse  # noqa: E402


def parse_args(argv):
    if len(argv) == 2 and argv[0] == "--issue" and argv[1].isascii() and argv[1].isdigit() and int(argv[1]) >= 1:
        return int(argv[1])
    return None


def main(argv):
    issue = parse_args(argv)
    if issue is None:
        sys.stderr.write("usage: ac_coverage.py --issue <N>\n")
        return acparse.EXIT_CANNOT_JUDGE
    try:
        code, lines = acparse.check_coverage(os.getcwd(), issue)
    except Exception as e:
        sys.stderr.write(f"ac-coverage: internal error — NOT judged ({type(e).__name__}: {e})\n")
        return acparse.EXIT_CANNOT_JUDGE
    for line in lines:
        sys.stdout.write(line + "\n")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
