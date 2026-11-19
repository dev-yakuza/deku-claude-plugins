#!/usr/bin/env python3
"""replay.legacy_rates — the LEGACY side of the §9.4-6 centres from the K2–K4 procedure-replay episodes (K6 item 18).

Only what the legacy logs say by themselves (no engine judgment): KICKOFF `clear` = an analyze episode whose
Readiness is clear on every dimension (K4); loop-back Issues = an Issue with a legacy test/qa LOOPBACK (K2); pause
Issues = an Issue whose execute episode posted a pause (K3). STAKES / EX-ARB / HANDOFF have no legacy counterpart
in the logs (the legacy leader logged no such decision) — None. This is the `--legacy` input of
`dev health --set-centre`; the engine side needs the paid held-out replay.

    legacy_rates.py --measure <design/guild/measure> --out <file>
"""

import argparse
import json
import os
import re
import sys


def rates(measure):
    k2 = json.load(open(os.path.join(measure, "k2-replay", "episodes.json"), encoding="utf-8"))
    k3 = json.load(open(os.path.join(measure, "k3-replay", "execute_episodes.json"), encoding="utf-8"))
    k4 = json.load(open(os.path.join(measure, "k4-replay", "episodes.json"), encoding="utf-8"))

    def issue_of(k):
        m = re.search(r"#(\d+):", k or "")
        return int(m.group(1)) if m else None
    issues = set()
    loop, pause = set(), set()
    for e in k2:
        n = issue_of(e.get("episode"))
        if n is None:
            continue
        issues.add(n)
        if e.get("legacy_outcome") == "LOOPBACK":
            loop.add(n)
    for e in k3:
        n = issue_of(e.get("key"))
        if n is None:
            continue
        issues.add(n)
        if int(e.get("pauses") or 0) > 0:
            pause.add(n)
    rd = [x.get("readiness") or {} for x in k4 if x.get("readiness")]
    clear = sum(1 for r in rd if r and all(v == "clear" for v in r.values()))
    unclear = sum(1 for r in rd if any(v == "unclear" for v in r.values()))
    return {"kickoff_clear": clear / float(len(rd)) if rd else None,
            "kickoff_unclear": unclear / float(len(rd)) if rd else None,
            "loopback_issues": len(loop) / float(len(issues)) if issues else None,
            "pause_issues": len(pause) / float(len(issues)) if issues else None,
            "exarb_dismiss": None, "stakes_low": None, "stakes_high": None, "handoff_ok_with_assumption": None,
            "_n": {"issues": len(issues), "analyze_episodes": len(rd)},
            "_what": "legacy only (K2 test/qa, K3 execute, K4 analyze replay episodes) — the engine centre needs "
                     "the paid held-out replay"}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--measure", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    r = rates(a.measure)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(r, fh, indent=1)
    print(json.dumps(r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
