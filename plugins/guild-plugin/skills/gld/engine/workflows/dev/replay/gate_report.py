#!/usr/bin/env python3
"""replay.gate_report — the §10.2-6 verification gate in code: graded replay results → `verification.json`.

K6 r7 m4 (the shipped `verification.json` and `unverified.py` named this writer before it existed). Offline and
deterministic — no model, no GitHub: it only reads the graded rows the paid held-out replay and the synthetic
scenarios produce (design §10.2-3 / §10.2-6) and decides, per §9.5 group (`valves.GROUPS` spelling), whether the
replay VERIFIED it:

* **replay** — held-out decisions of the group (`set: held-out`, `source: replay`): n ≥ `MIN_N` (20) ∧ agreement
  with the graded answer ≥ `MIN_AGREE` (85 %) ∧ advance / non-advance agreement ≥ `MIN_ADVANCE` (95 %);
* **synthetic** — held-out synthetic scenarios of the group (`set: held-out`, `source: synthetic`, graded against the
  person-approved answer key): n ≥ 1 ∧ wrong ≤ 1 — **wrong 0** for the high-risk groups (`HIGH_RISK`: STAKES · EX-ARB ·
  SPLIT · INTEGRATE · ESCALATE, R5J-m3);
* anything else — tuning rows, an unknown group, a row without its verdict — never verifies ("no synthetic = not
  passed", R4J-m5). An `undeterminable` / `unsure` verdict is no agreement (it counts in n, never as agree).

Input rows (JSON list, or {"rows": [...]}) — one per graded decision:
    {"group": "SPLIT", "set": "held-out", "source": "replay", "agree": true, "advance_agree": true}
    {"group": "STAKES", "set": "held-out", "source": "synthetic", "wrong": false}

    gate_report.py --rows <graded.json> --out <verification.json> [--replay "<what was run>"]

The output keeps `verification.json`'s shape (`about`, `replay`, `release_after`, `verified`) and adds `groups` (per
group: the counts and why it is / is not verified) and the input's sha256.
"""

import argparse
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

MIN_N = 20
MIN_AGREE = 0.85
MIN_ADVANCE = 0.95
SYNTH_MAX_WRONG = 1
HIGH_RISK = ("STAKES", "EX-ARB-dismiss", "EX-ARB-accept", "SPLIT", "INTEGRATE", "ESCALATE")
RELEASE_AFTER = 5
ABOUT = ("design §10.2-6 — the groups the held-out judgment replay verified. Written by replay/gate_report.py from "
         "the replay's graded results; shipped with the release. A group not listed under `verified` is UNVERIFIED: "
         "it runs the conservative path until released (unverified.py — §10.4 G1 group rule).")


def canonical(group):
    """`EX-ARB:dismiss` → `EX-ARB-dismiss` (the valve spelling); a bare `EX-ARB` names both EX-ARB groups."""
    g = str(group or "").strip().replace(":", "-")
    return g


def _groups_of(row):
    g = canonical(row.get("group"))
    return ["EX-ARB-dismiss", "EX-ARB-accept"] if g == "EX-ARB" else [g]


def decide(rows, groups=None):
    """{group: {"verified": bool, "by": "replay"|"synthetic"|None, "why": str, counts…}} for every group of `groups`
    (default `valves.GROUPS`)."""
    if groups is None:
        from guildcore import valves as VALVES
        groups = VALVES.GROUPS
    acc = dict((g, {"replay_n": 0, "replay_agree": 0, "replay_advance": 0, "synthetic_n": 0, "synthetic_wrong": 0,
                    "ignored": 0}) for g in groups)
    unknown = {}
    for r in rows or ():
        if not isinstance(r, dict):
            continue
        for g in _groups_of(r):
            if g not in acc:
                unknown[g] = unknown.get(g, 0) + 1
                continue
            a = acc[g]
            if str(r.get("set") or "").strip().lower() != "held-out":
                a["ignored"] += 1                        # tuning rows never gate
                continue
            src = str(r.get("source") or "").strip().lower()
            if src == "replay":
                a["replay_n"] += 1
                a["replay_agree"] += 1 if r.get("agree") is True else 0
                a["replay_advance"] += 1 if r.get("advance_agree") is True else 0
            elif src == "synthetic":
                a["synthetic_n"] += 1
                # a synthetic row without a verdict is no pass: counted as wrong
                a["synthetic_wrong"] += 0 if r.get("wrong") is False else 1
            else:
                a["ignored"] += 1
    out = {}
    for g in groups:
        a = acc[g]
        n = a["replay_n"]
        ok_replay = n >= MIN_N and a["replay_agree"] >= MIN_AGREE * n and a["replay_advance"] >= MIN_ADVANCE * n
        lim = 0 if g in HIGH_RISK else SYNTH_MAX_WRONG
        ok_synth = a["synthetic_n"] >= 1 and a["synthetic_wrong"] <= lim
        if ok_replay:
            why = "held-out replay n=%d, agreement %d/%d, advance %d/%d" % (n, a["replay_agree"], n,
                                                                            a["replay_advance"], n)
        elif ok_synth:
            why = "held-out synthetic n=%d, wrong %d (≤ %d)" % (a["synthetic_n"], a["synthetic_wrong"], lim)
        else:
            parts = []
            if n < MIN_N:
                parts.append("held-out replay n=%d < %d" % (n, MIN_N))
            else:
                parts.append("held-out replay agreement %d/%d or advance %d/%d below %.0f%% / %.0f%%"
                             % (a["replay_agree"], n, a["replay_advance"], n, MIN_AGREE * 100, MIN_ADVANCE * 100))
            parts.append("no held-out synthetic" if not a["synthetic_n"] else
                         "held-out synthetic wrong %d > %d" % (a["synthetic_wrong"], lim))
            why = "; ".join(parts)
        out[g] = dict(a, verified=bool(ok_replay or ok_synth),
                      by="replay" if ok_replay else "synthetic" if ok_synth else None, why=why)
    if unknown:
        out["_unknown_groups"] = dict(sorted(unknown.items()))
    return out


def report(rows, replay="", raw=b""):
    """The `verification.json` document for `rows`."""
    per = decide(rows)
    verified = sorted(g for g, v in per.items() if isinstance(v, dict) and v.get("verified"))
    return {"about": ABOUT, "replay": replay or "graded replay rows (gate_report.py)", "release_after": RELEASE_AFTER,
            "verified": verified, "groups": dict((g, v) for g, v in sorted(per.items())),
            "criteria": {"min_n": MIN_N, "min_agreement": MIN_AGREE, "min_advance_agreement": MIN_ADVANCE,
                         "synthetic_max_wrong": SYNTH_MAX_WRONG, "synthetic_max_wrong_high_risk": 0,
                         "high_risk": list(HIGH_RISK)},
            "input_sha256": hashlib.sha256(raw).hexdigest() if raw else None}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="gate_report.py")
    ap.add_argument("--rows", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--replay", default="")
    a = ap.parse_args(argv)
    with open(a.rows, "rb") as fh:
        raw = fh.read()
    d = json.loads(raw.decode("utf-8"))
    rows = d.get("rows") if isinstance(d, dict) else d
    rep = report(rows if isinstance(rows, list) else [], a.replay, raw)
    tmp = a.out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:  # fs-ok: the release's verification.json path the person names
        json.dump(rep, fh, indent=2, sort_keys=True, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, a.out)
    print(json.dumps({"verified": rep["verified"], "out": a.out}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
