#!/usr/bin/env python3
"""replay.gate_report — the §10.2-6 verification gate in code: graded replay results → `verification.json`.

K6 r7 m4 (the shipped `verification.json` and `unverified.py` named this writer before it existed). Offline and
deterministic — no model, no GitHub: it only reads the graded rows the paid held-out replay and the synthetic
scenarios produce (design §10.2-3 / §10.2-6) and decides, per §9.5 group (`valves.GROUPS` spelling), whether the
replay VERIFIED it:

* **replay** — held-out decisions of the group (`set: held-out`, `source: replay`): n ≥ `MIN_N` (20) ∧ agreement
  with the graded answer ≥ `MIN_AGREE` (85 %) ∧ advance / non-advance agreement ≥ `MIN_ADVANCE` (95 %);
* **synthetic** — held-out synthetic scenarios of the group (`set: held-out`, `source: synthetic`, graded against the
  person-approved answer key): n ≥ the group's PLANNED held-out count (`SYNTH_PLANNED` — half of design §10.2-3's
  synthetic set per group, at least `SYNTH_MIN_N` 2) ∧ wrong < n ∧ wrong ≤ 1 — **wrong 0** for the high-risk groups
  (`HIGH_RISK`: STAKES · EX-ARB · SPLIT · INTEGRATE · ESCALATE, R5J-m3) — and ONLY for a group whose held-out replay
  is short (n < `MIN_N`): a group the replay measured (n ≥ 20) and failed is never covered by synthetic rows (K6 r8
  user decision 1 — it goes back to tuning and a held-out final pass);
* anything else — tuning rows, an unknown group, a row without its verdict — never verifies ("no synthetic = not
  passed", R4J-m5). An `undeterminable` / `unsure` verdict is no agreement (it counts in n, never as agree).

K6 r8 M1 — the rows are checked before they count:
* every row needs an `id` (replay: the decision, `issue/D-id`; synthetic: the scenario id) — a row without one is
  dropped and reported (`_rows_without_id`); a repeated id inside one group's held-out source counts ONCE (the
  worst verdict of its copies; reported as `duplicates`);
* an id that is ALSO a tuning row (any group) is train = test: the group it is held out for cannot be verified
  (`contaminated`, with the ids);
* a bare `EX-ARB` row names its kind (`kind`, else a word of `scenario`): `dismiss` / `dispute` → EX-ARB-dismiss
  (a dispute is the non-accept side exec_audit treats with a dismiss), `accept` → EX-ARB-accept; no kind, or both
  kinds → an unknown group (`EX-ARB?`) — an accept scenario never counts for EX-ARB-dismiss.
K6 r8 user decision 2 — the OPEN groups (KICKOFF · STAKES, `predict.OPEN_GROUPS`) and the INHERENT groups
(`conservative.INHERENT`) are released ONLY by the person's grading-sheet verdicts: their replay / synthetic results
are recorded (`would_pass`) but never put under `verified` (`sheet_only`); `unverified()` ignores them in a shipped
`verified` list too.

Input rows (JSON list, or {"rows": [...]}) — one per graded decision:
    {"id": "#12/D3", "group": "SPLIT", "set": "held-out", "source": "replay", "agree": true, "advance_agree": true}
    {"id": "syn-split-07", "group": "SPLIT", "set": "held-out", "source": "synthetic", "wrong": false}
    {"id": "syn-exarb-03", "group": "EX-ARB", "kind": "dismiss", "set": "held-out", "source": "synthetic", "wrong": false}

    gate_report.py --rows <graded.json> --out <verification.json> [--replay "<what was run>"]

The output keeps `verification.json`'s shape (`about`, `replay`, `release_after`, `verified`) and adds `groups` (per
group: the counts and why it is / is not verified) and the input's sha256.
"""

import argparse
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

MIN_N = 20
MIN_AGREE = 0.85
MIN_ADVANCE = 0.95
SYNTH_MAX_WRONG = 1
SYNTH_MIN_N = 2
# K6 r8 M1: the held-out half of design §10.2-3's synthetic set per group (SPLIT 8, INTEGRATE 6, ESCALATE 10, DE-ARB 6,
# VIS-ENV 5, AN-PO 4, DIRECTIVE 5, STAKES 8, EX-ARB 10 — dismiss·dispute·accept); a group without a planned set
# needs SYNTH_MIN_N. A missing (ungraded, dropped) scenario row lowers n below the plan — no pass.
SYNTH_PLANNED = {"SPLIT": 4, "INTEGRATE": 3, "ESCALATE": 5, "DE-ARB": 3, "VIS-ENV": 2, "AN-PO": 2, "DIRECTIVE": 2,
                 "STAKES": 4, "EX-ARB-dismiss": SYNTH_MIN_N, "EX-ARB-accept": SYNTH_MIN_N}
HIGH_RISK = ("STAKES", "EX-ARB-dismiss", "EX-ARB-accept", "SPLIT", "INTEGRATE", "ESCALATE")
RELEASE_AFTER = 5
ABOUT = ("design §10.2-6 — the groups the held-out judgment replay verified. Written by replay/gate_report.py from "
         "the replay's graded results; shipped with the release. A group not listed under `verified` is UNVERIFIED: "
         "it runs the conservative path until released (unverified.py — §10.4 G1 group rule).")


def canonical(group):
    """`EX-ARB:dismiss` → `EX-ARB-dismiss` (the valve spelling)."""
    g = str(group or "").strip().replace(":", "-")
    return g


_EXARB_KIND = {"dismiss": "EX-ARB-dismiss", "dispute": "EX-ARB-dismiss", "accept": "EX-ARB-accept"}


def _group_of(row):
    """K6 r8 M1(d): the one group a row counts for. A bare `EX-ARB` row goes by its kind (`kind`, else the kind words
    of `scenario`) — dismiss / dispute → EX-ARB-dismiss, accept → EX-ARB-accept; none or both → `EX-ARB?` (unknown)."""
    g = canonical(row.get("group"))
    if g != "EX-ARB":
        return g
    k = str(row.get("kind") or "").strip().lower()
    if k:
        return _EXARB_KIND.get(k, "EX-ARB?")
    words = set(re.split(r"[^a-z]+", str(row.get("scenario") or "").lower()))
    hit = set(_EXARB_KIND[w] for w in words if w in _EXARB_KIND)
    return hit.pop() if len(hit) == 1 else "EX-ARB?"


def _row_id(row):
    i = row.get("id")
    return str(i).strip() if isinstance(i, (str, int)) and not isinstance(i, bool) and str(i).strip() else None


def sheet_only():
    """K6 r8 user decision 2: {group: why} — the groups only the grading sheet releases (OPEN + INHERENT)."""
    from workflows.dev import conservative as CONS
    from workflows.dev import predict as PF
    out = dict((canonical(g), "asked openly — released only by grading-sheet verdicts (K6 r8 user decision 2)")
               for g in PF.OPEN_GROUPS)
    for g in CONS.INHERENT:
        out[canonical(g)] = ("INHERENT gate — released only by grading-sheet verdicts (K6 r8 user decision 2)")
    return out


def decide(rows, groups=None):
    """{group: {"verified": bool, "by": "replay"|"synthetic"|None, "why": str, counts…}} for every group of `groups`
    (default `valves.GROUPS`), plus `_unknown_groups` / `_rows_without_id` when there are such rows."""
    if groups is None:
        from guildcore import valves as VALVES
        groups = VALVES.GROUPS
    sheet = sheet_only()
    rows = [r for r in (rows or ()) if isinstance(r, dict)]
    no_id = 0
    tuning_ids = set()
    for r in rows:
        if str(r.get("set") or "").strip().lower() != "held-out" and _row_id(r):
            tuning_ids.add(_row_id(r))
    acc = dict((g, {"replay_n": 0, "replay_agree": 0, "replay_advance": 0, "synthetic_n": 0, "synthetic_wrong": 0,
                    "ignored": 0, "duplicates": 0}) for g in groups)
    held = dict((g, {"replay": {}, "synthetic": {}}) for g in groups)
    contaminated = dict((g, set()) for g in groups)
    unknown = {}
    for r in rows:
        rid = _row_id(r)
        if rid is None:
            no_id += 1                                   # K6 r8 M1(b): no identity — cannot be counted once
            continue
        g = _group_of(r)
        if g not in acc:
            unknown[g] = unknown.get(g, 0) + 1
            continue
        a = acc[g]
        if str(r.get("set") or "").strip().lower() != "held-out":
            a["ignored"] += 1                            # tuning rows never gate
            continue
        if rid in tuning_ids:
            contaminated[g].add(rid)                     # K6 r8 M1(c): train = test
        src = str(r.get("source") or "").strip().lower()
        if src == "replay":
            v = (r.get("agree") is True, r.get("advance_agree") is True)
        elif src == "synthetic":
            v = (r.get("wrong") is False,)               # a synthetic row without a verdict is no pass (wrong)
        else:
            a["ignored"] += 1
            continue
        seen = held[g][src]
        if rid in seen:
            a["duplicates"] += 1                         # K6 r8 M1(b): counted once, its worst verdict
            seen[rid] = tuple(x and y for x, y in zip(seen[rid], v))
        else:
            seen[rid] = v
    out = {}
    for g in groups:
        a = acc[g]
        rep, syn = held[g]["replay"], held[g]["synthetic"]
        a["replay_n"] = n = len(rep)
        a["replay_agree"] = sum(1 for v in rep.values() if v[0])
        a["replay_advance"] = sum(1 for v in rep.values() if v[1])
        a["synthetic_n"] = sn = len(syn)
        a["synthetic_wrong"] = sw = sum(1 for v in syn.values() if not v[0])
        lim = 0 if g in HIGH_RISK else SYNTH_MAX_WRONG
        planned = SYNTH_PLANNED.get(g, SYNTH_MIN_N)
        ok_replay = n >= MIN_N and a["replay_agree"] >= MIN_AGREE * n and a["replay_advance"] >= MIN_ADVANCE * n
        replay_failed = n >= MIN_N and not ok_replay
        ok_synth = not replay_failed and sn >= planned and sw < sn and sw <= lim
        parts = []
        if ok_replay:
            parts.append("held-out replay n=%d, agreement %d/%d, advance %d/%d" % (n, a["replay_agree"], n,
                                                                                   a["replay_advance"], n))
        elif ok_synth:
            parts.append("held-out synthetic n=%d (planned %d), wrong %d (≤ %d)" % (sn, planned, sw, lim))
        else:
            if n < MIN_N:
                parts.append("held-out replay n=%d < %d" % (n, MIN_N))
            else:
                parts.append("held-out replay agreement %d/%d or advance %d/%d below %.0f%% / %.0f%%"
                             % (a["replay_agree"], n, a["replay_advance"], n, MIN_AGREE * 100, MIN_ADVANCE * 100))
            if replay_failed:
                parts.append("a failed replay is not covered by synthetic (K6 r8 user decision 1 — tuning re-run, "
                             "then a held-out final pass)")
            elif not sn:
                parts.append("no held-out synthetic")
            elif sn < planned:
                parts.append("held-out synthetic n=%d < planned %d" % (sn, planned))
            else:
                parts.append("held-out synthetic wrong %d > %d" % (sw, lim) if sw > lim else
                             "held-out synthetic all wrong (%d/%d)" % (sw, sn))
        passed = ok_replay or ok_synth
        verified = passed
        if contaminated[g]:
            verified = False
            parts.append("contaminated: %d held-out id(s) are tuning rows too (train = test) — cannot be verified"
                         % len(contaminated[g]))
        if g in sheet:
            verified = False
            parts.append("sheet only: " + sheet[g])
        out[g] = dict(a, verified=verified, by=("replay" if ok_replay else "synthetic") if verified else None,
                      why="; ".join(parts))
        if g in sheet:
            out[g]["sheet_only"] = True
            out[g]["would_pass"] = passed and not contaminated[g]
        if contaminated[g]:
            out[g]["contaminated"] = sorted(contaminated[g])
    if unknown:
        out["_unknown_groups"] = dict(sorted(unknown.items()))
    if no_id:
        out["_rows_without_id"] = no_id
    return out


def report(rows, replay="", raw=b""):
    """The `verification.json` document for `rows`."""
    per = decide(rows)
    verified = sorted(g for g, v in per.items() if isinstance(v, dict) and v.get("verified"))
    return {"about": ABOUT, "replay": replay or "graded replay rows (gate_report.py)", "release_after": RELEASE_AFTER,
            "verified": verified, "groups": dict((g, v) for g, v in sorted(per.items())),
            "criteria": {"min_n": MIN_N, "min_agreement": MIN_AGREE, "min_advance_agreement": MIN_ADVANCE,
                         "synthetic_max_wrong": SYNTH_MAX_WRONG, "synthetic_max_wrong_high_risk": 0,
                         "high_risk": list(HIGH_RISK), "synthetic_planned": dict(sorted(SYNTH_PLANNED.items())),
                         "synthetic_min_n": SYNTH_MIN_N, "synthetic_only_when_replay_short": True,
                         "row_id_required": True, "sheet_only": sorted(sheet_only())},
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
