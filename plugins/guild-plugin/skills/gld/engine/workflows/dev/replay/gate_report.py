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
  synthetic set per group; K6 r9 M1(a): a group §10.2-3 plans NO synthetic set for — HANDOFF — has no synthetic
  path at all, replay only) ∧ wrong < n ∧ wrong ≤ 1 — **wrong 0** for the high-risk groups
  (`HIGH_RISK`: STAKES · EX-ARB · SPLIT · INTEGRATE · ESCALATE, R5J-m3) — and ONLY for a group the input has NO
  replay row for at all (K6 r11 M1, see below);
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
K6 r9 M1 / m2 / m3 — and checked against each other:
* a replay id must be `issue/D-id` (`^#?<digits>/D…$`; `12/D2` ≡ `#12/D2`) — any other spelling is rejected and reported
  (`_rows_rejected`); a synthetic id is the scenario id as written;
* the replay split unit is the ISSUE (design §10.2-3: the first 30 Issues tune, the last 30 gate): a held-out
  decision of an Issue that has a tuning row is contaminated as a shared id is (`_split_overlap` lists the Issues);
* one held-out decision / scenario counts for ONE group: an id held out under two or more groups is dropped from all
  of them (`_conflicting_groups`);
* an explicit group and a `kind` that disagree (`EX-ARB:dismiss` with kind `accept`, a kind on a non-EX-ARB group)
  reject the row (`_rows_rejected`);
* no tuning rows of a source in the input → train = test is unchecked for it: a group that would pass by that source
  is not verified (`_no_tuning_rows`) — feed the tuning rows too.
K6 r10 M1 / m1 — r9 m2's "latest pass" is gone:
* the copies of one held-out id always count ONCE, their worst verdict — a `pass` field is reported (`passes`), never
  used to drop rows: one held-out set, graded once;
* the tuning Issues are read from EVERY non-held-out row with an `issue/D-id` id — an unknown group, a kind conflict
  or a missing source does not hide its Issue from the split check.
K6 r11 M1 — a replayed group is verified by replay only (K6 r8 user decision 1, without an n ≥ 20 boundary):
* a group is "replayed" when the input has ANY row for it whose `source` is not `synthetic` — held-out, tuning,
  retired, a row without an id, a rejected or a conflicting row alike (read before any check or dedupe; a bare
  `EX-ARB` row without a kind marks both EX-ARB groups). Synthetic rows never verify a replayed group, so a group
  the replay failed stays failed whatever rows are added later — only a held-out replay that meets the bar
  verifies it;
* re-measuring a re-tuned group needs a FRESH held-out set (new Issues); the old held-out rows go in as
  `set: "retired"` (checklist F) — they keep the group "replayed", are not counted for verification, and block their
  Issues and ids like tuning rows do (a fresh held-out decision of a retired Issue is contaminated).
K6 r12 M1 — group names are matched case-insensitively (`canonical`), and ONE more rule: when any non-synthetic row
names a group that is not a known group (a typo like `DIRECTVE`, an empty group), the input cannot say which groups
were replayed — so NO group of that input is verified by synthetic (the names under `_unknown_groups`, the reason in
each group's `why`). Fix the rows and run it again.
K6 r8 user decision 2 — the OPEN groups (KICKOFF · STAKES, `predict.OPEN_GROUPS`) and the INHERENT groups
(`conservative.INHERENT`) are released ONLY by the person's grading-sheet verdicts: their replay / synthetic results
are recorded (`would_pass`) but never put under `verified` (`sheet_only`); `unverified()` ignores them in a shipped
`verified` list too.

Input rows (JSON list, or {"rows": [...]}) — one per graded decision:
    {"id": "#12/D3", "group": "SPLIT", "set": "held-out", "source": "replay", "agree": true, "advance_agree": true}
    {"id": "syn-split-07", "group": "SPLIT", "set": "held-out", "source": "synthetic", "wrong": false}
    {"id": "syn-exarb-03", "group": "EX-ARB", "kind": "dismiss", "set": "held-out", "source": "synthetic", "wrong": false}
    {"id": "#3/D1", "group": "SPLIT", "set": "tuning", "source": "replay", "agree": true, "advance_agree": true}
    {"id": "#7/D2", "group": "SPLIT", "set": "retired", "source": "replay", "agree": false, "advance_agree": true}

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
# VIS-ENV 5, AN-PO 4, DIRECTIVE 5, STAKES 8, EX-ARB 10 — dismiss·dispute·accept, no split by kind: SYNTH_MIN_N each).
# K6 r9 M1(a): a group without a planned set (HANDOFF) has no synthetic path. A missing (ungraded, dropped) scenario
# row lowers n below the plan — no pass.
SYNTH_PLANNED = {"SPLIT": 4, "INTEGRATE": 3, "ESCALATE": 5, "DE-ARB": 3, "VIS-ENV": 2, "AN-PO": 2, "DIRECTIVE": 2,
                 "STAKES": 4, "EX-ARB-dismiss": SYNTH_MIN_N, "EX-ARB-accept": SYNTH_MIN_N}
HIGH_RISK = ("STAKES", "EX-ARB-dismiss", "EX-ARB-accept", "SPLIT", "INTEGRATE", "ESCALATE")
RELEASE_AFTER = 5
ABOUT = ("design §10.2-6 — the groups the held-out judgment replay verified. Written by replay/gate_report.py from "
         "the replay's graded results; shipped with the release. A group not listed under `verified` is UNVERIFIED: "
         "it runs the conservative path until released (unverified.py — §10.4 G1 group rule).")


def canonical(group):
    """`EX-ARB:dismiss` → `EX-ARB-dismiss` (the valve spelling). K6 r12 M1: case-insensitive — `directive`,
    `EX-ARB:Dismiss` → `DIRECTIVE`, `EX-ARB-dismiss` (a §9.5 group or the bare `EX-ARB`); any other name as written."""
    g = str(group or "").strip().replace(":", "-")
    from guildcore import valves as VALVES
    return next((x for x in VALVES.GROUPS + ("EX-ARB",) if x.casefold() == g.casefold()), g)


_EXARB_KIND = {"dismiss": "EX-ARB-dismiss", "dispute": "EX-ARB-dismiss", "accept": "EX-ARB-accept"}
_EXARB = ("EX-ARB-dismiss", "EX-ARB-accept")


def _kind_group(row):
    """The EX-ARB group a row's kind names — `kind`, else the kind words of `scenario` — or None (no kind), or
    `EX-ARB?` (an unknown kind, or both kinds)."""
    k = str(row.get("kind") or "").strip().lower()
    if k:
        return _EXARB_KIND.get(k, "EX-ARB?")
    words = set(re.split(r"[^a-z]+", str(row.get("scenario") or "").lower()))
    hit = set(_EXARB_KIND[w] for w in words if w in _EXARB_KIND)
    if not hit:
        return None
    return hit.pop() if len(hit) == 1 else "EX-ARB?"


def _group_of(row):
    """K6 r8 M1(d): the one group a row counts for. A bare `EX-ARB` row goes by its kind (`kind`, else the kind words
    of `scenario`) — dismiss / dispute → EX-ARB-dismiss, accept → EX-ARB-accept; none or both → `EX-ARB?` (unknown).
    K6 r9 M1(e): an explicit group and a kind that disagree (`EX-ARB:dismiss` with kind `accept`, a kind on a
    non-EX-ARB group) → `KIND-CONFLICT` — the row is rejected and reported, never counted for either group."""
    g = canonical(row.get("group"))
    kg = _kind_group(row)
    if g == "EX-ARB":
        return kg or "EX-ARB?"
    if g in _EXARB:
        return g if kg in (None, g) else KIND_CONFLICT
    if str(row.get("kind") or "").strip():
        return KIND_CONFLICT
    return g


KIND_CONFLICT = "KIND-CONFLICT"
# K6 r9 M1(c): a replay row's id is the decision — `issue/D-id`, the `#` optional; canonical `#<issue>/<D-id>`
_REPLAY_ID = re.compile(r"^#?(\d+)/(D[\w:.-]+)$")


def _row_id(row):
    i = row.get("id")
    return str(i).strip() if isinstance(i, (str, int)) and not isinstance(i, bool) and str(i).strip() else None


def _canonical_id(row, src):
    """(canonical id, issue) — replay: `#12/D2` (`12/D2` ≡ `#12/D2`), issue 12; synthetic: the scenario id as written,
    no issue. (None, None) for a replay id that is not `issue/D-id` (K6 r9 M1(c) — rejected, reported)."""
    rid = _row_id(row)
    if rid is None:
        return None, None
    if src != "replay":
        return rid, None
    m = _REPLAY_ID.match(rid)
    if not m:
        return None, None
    return "#%d/%s" % (int(m.group(1)), m.group(2)), int(m.group(1))


def _pass_of(row):
    """The `pass` a row names (an integer ≥ 1), or None — reported only (K6 r10 M1: never used for counting)."""
    p = row.get("pass")
    if isinstance(p, bool):
        return None
    if isinstance(p, int):
        return p if p >= 1 else None
    if isinstance(p, str) and p.strip().isdigit() and int(p.strip()) >= 1:
        return int(p.strip())
    return None


def _replayed_groups(rows):
    """K6 r11 M1: every group some non-synthetic row names — before any check, dedupe or set filter. The row's group
    and the group its `kind` names both count; a bare `EX-ARB` row (or an unknown kind) names both EX-ARB groups."""
    out = set()
    for r in rows:
        if str(r.get("source") or "").strip().lower() == "synthetic":
            continue
        names = set([canonical(r.get("group"))])
        if str(r.get("kind") or "").strip():
            names.add(_kind_group(r))
        if names & set(("EX-ARB", "EX-ARB?")):
            names.update(_EXARB)
        out.update(n for n in names if n)
    return out


def sheet_only():
    """K6 r8 user decision 2: {group: why} — the groups only the grading sheet releases (OPEN + INHERENT)."""
    from workflows.dev import conservative as CONS
    from workflows.dev import predict as PF
    out = dict((canonical(g), "asked openly — released only by grading-sheet verdicts (K6 r8 user decision 2)")
               for g in PF.OPEN_GROUPS)
    for g in CONS.INHERENT:
        out[canonical(g)] = ("INHERENT gate — released only by grading-sheet verdicts (K6 r8 user decision 2)")
    return out


def _bump(d, k):
    d[k] = d.get(k, 0) + 1


def decide(rows, groups=None):
    """{group: {"verified": bool, "by": "replay"|"synthetic"|None, "why": str, counts…}} for every group of `groups`
    (default `valves.GROUPS`), plus the reports `_unknown_groups` / `_rows_without_id` / `_rows_rejected` /
    `_conflicting_groups` / `_split_overlap` / `_no_tuning_rows` when there is something to report."""
    if groups is None:
        from guildcore import valves as VALVES
        groups = VALVES.GROUPS
    sheet = sheet_only()
    rows = [r for r in (rows or ()) if isinstance(r, dict)]
    no_id = 0
    rejected = {}
    unknown = {}
    acc = dict((g, {"replay_n": 0, "replay_agree": 0, "replay_advance": 0, "synthetic_n": 0, "synthetic_wrong": 0,
                    "ignored": 0, "duplicates": 0}) for g in groups)
    # K6 r10 m1: the split unit is the Issue whatever the row's group — read the tuning Issues (and tuning ids) from
    # EVERY tuning row before any group / kind / source check can drop it
    replayed = _replayed_groups(rows)
    # K6 r12 M1: a non-synthetic row naming an unknown group might be a replay of any group — no synthetic path at all
    known = set(groups) | set(("EX-ARB",))
    stray = [canonical(r.get("group")) for r in rows if str(r.get("source") or "").strip().lower() != "synthetic"]
    stray = [x for x in stray if x not in known]
    tuning_issues = set()
    tuning_ids = set()
    for r in rows:
        if str(r.get("set") or "").strip().lower() == "held-out" or _row_id(r) is None:
            continue
        m = _REPLAY_ID.match(_row_id(r))
        if m:
            tuning_issues.add(int(m.group(1)))
            tuning_ids.add(("replay", "#%d/%s" % (int(m.group(1)), m.group(2))))
        if str(r.get("source") or "").strip().lower() != "replay":
            tuning_ids.add(("synthetic", _row_id(r)))
    # every row checked and canonicalised: (row, group, set, source, id, issue)
    kept = []
    for r in rows:
        if _row_id(r) is None:
            no_id += 1                                   # K6 r8 M1(b): no identity — cannot be counted once
            continue
        g = _group_of(r)
        if g == KIND_CONFLICT:
            _bump(rejected, "kind contradicts group")     # K6 r9 M1(e)
            continue
        if g not in acc:
            _bump(unknown, g)
            continue
        st = str(r.get("set") or "").strip().lower()
        st = st if st in ("held-out", "retired") else "tuning"
        src = str(r.get("source") or "").strip().lower()
        if src not in ("replay", "synthetic"):
            acc[g]["ignored"] += 1
            continue
        cid, issue = _canonical_id(r, src)
        if cid is None:
            _bump(rejected, "replay id is not issue/D-id")  # K6 r9 M1(c)
            continue
        kept.append((r, g, st, src, cid, issue))
    # K6 r9 m3: the train = test checks need the tuning rows beside the held-out ones — per source
    tuning_src = set(src for _r, _g, st, src, _c, _i in kept if st == "tuning")
    # K6 r9 M1(d): one held-out decision / scenario belongs to ONE group — an id held out under two or more groups is
    # dropped from all of them and reported
    groups_of = {}
    for _r, g, st, src, cid, _i in kept:
        if st == "held-out":
            groups_of.setdefault((src, cid), set()).add(g)
    conflicting = dict(("%s %s" % k, sorted(v)) for k, v in groups_of.items() if len(v) > 1)
    held = dict((g, {"replay": {}, "synthetic": {}}) for g in groups)
    contaminated = dict((g, set()) for g in groups)
    passes_of = dict((g, {}) for g in groups)
    overlap = set()
    for r, g, st, src, cid, issue in kept:
        a = acc[g]
        if st != "held-out":
            a["ignored"] += 1                            # tuning / retired rows never gate
            continue
        if len(groups_of[(src, cid)]) > 1:
            continue
        if (src, cid) in tuning_ids:
            contaminated[g].add(cid)                     # K6 r8 M1(c): train = test
        elif src == "replay" and issue in tuning_issues:
            contaminated[g].add(cid)                     # K6 r9 M1(b): a held-out decision of a tuning Issue
            overlap.add(issue)
        if src == "replay":
            v = (r.get("agree") is True, r.get("advance_agree") is True)
        else:
            v = (r.get("wrong") is False,)               # a synthetic row without a verdict is no pass (wrong)
        held[g][src].setdefault(cid, []).append(v)
        if _pass_of(r) is not None:
            passes_of[g].setdefault(src, set()).add(_pass_of(r))
    out = {}
    for g in groups:
        a = acc[g]
        passes = dict((src, sorted(p)) for src, p in passes_of[g].items())
        counted = {}
        for src in ("replay", "synthetic"):
            # K6 r8 M1(b) / r10 M1: the copies of one id count once, their worst verdict — whatever `pass` they name
            res = {}
            for cid, vs in held[g][src].items():
                a["duplicates"] += len(vs) - 1
                res[cid] = tuple(all(x) for x in zip(*vs))
            counted[src] = res
        rep, syn = counted["replay"], counted["synthetic"]
        a["replay_n"] = n = len(rep)
        a["replay_agree"] = sum(1 for v in rep.values() if v[0])
        a["replay_advance"] = sum(1 for v in rep.values() if v[1])
        a["synthetic_n"] = sn = len(syn)
        a["synthetic_wrong"] = sw = sum(1 for v in syn.values() if not v[0])
        lim = 0 if g in HIGH_RISK else SYNTH_MAX_WRONG
        planned = SYNTH_PLANNED.get(g)                   # K6 r9 M1(a): no plan in §10.2-3 → no synthetic path
        ok_replay = n >= MIN_N and a["replay_agree"] >= MIN_AGREE * n and a["replay_advance"] >= MIN_ADVANCE * n
        was_replayed = g in replayed                     # K6 r11 M1: replay only, whatever the counts
        ok_synth = (planned is not None and not was_replayed and not stray and sn >= planned and sw < sn
                    and sw <= lim)
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
            if planned is None:
                parts.append("no synthetic set planned for this group in design §10.2-3 — replay only (K6 r9 "
                             "M1(a); %d synthetic row(s) not counted)" % sn if sn else
                             "no synthetic set planned for this group in design §10.2-3 — replay only (K6 r9 M1(a))")
            elif was_replayed:
                parts.append("the input has replay rows for this group — verified by replay only, never by synthetic "
                             "(K6 r8 user decision 1, r11 M1; re-measure with a fresh held-out set, old rows retired)")
            elif stray:
                parts.append("a non-synthetic row names an unknown group (%s) — it may be a replay of this group, so "
                             "no group of this input is verified by synthetic (K6 r12 M1; fix the group names)"
                             % ", ".join(repr(x) for x in sorted(set(stray))))
            elif not sn:
                parts.append("no held-out synthetic")
            elif sn < planned:
                parts.append("held-out synthetic n=%d < planned %d" % (sn, planned))
            else:
                parts.append("held-out synthetic wrong %d > %d" % (sw, lim) if sw > lim else
                             "held-out synthetic all wrong (%d/%d)" % (sw, sn))
        if passes:
            a["passes"] = passes                         # reported only (K6 r10 M1)
        passed = ok_replay or ok_synth
        by = ("replay" if ok_replay else "synthetic") if passed else None
        unchecked = by is not None and by not in tuning_src
        verified = passed
        if contaminated[g]:
            verified = False
            parts.append("contaminated: %d held-out decision(s) / scenario(s) share an id or an Issue with the tuning "
                         "rows (train = test) — cannot be verified" % len(contaminated[g]))
        if unchecked:
            verified = False
            parts.append("no tuning %s rows in the input — train = test unchecked, cannot be verified (K6 r9 m3)"
                         % by)
        if g in sheet:
            verified = False
            parts.append("sheet only: " + sheet[g])
        out[g] = dict(a, verified=verified, by=by if verified else None, why="; ".join(parts), replayed=was_replayed)
        if g in sheet:
            out[g]["sheet_only"] = True
            out[g]["would_pass"] = passed and not contaminated[g] and not unchecked
        if contaminated[g]:
            out[g]["contaminated"] = sorted(contaminated[g])
    for x in set(stray):
        unknown.setdefault(x, stray.count(x))           # a row the checks dropped before naming it (no id …)
    if unknown:
        out["_unknown_groups"] = dict(sorted(unknown.items()))
    if no_id:
        out["_rows_without_id"] = no_id
    if rejected:
        out["_rows_rejected"] = dict(sorted(rejected.items()))
    if conflicting:
        out["_conflicting_groups"] = dict(sorted(conflicting.items()))
    if overlap:
        out["_split_overlap"] = sorted(overlap)
    missing = sorted(set(("replay", "synthetic")) - tuning_src)
    if missing:
        out["_no_tuning_rows"] = missing
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
                         "synthetic_min_n": SYNTH_MIN_N, "synthetic_only_when_never_replayed": True,
                         "synthetic_closed_by_unknown_group": True, "group_case_insensitive": True,
                         "synthetic_unplanned": "replay only", "row_id_required": True,
                         "replay_id": "issue/D-id", "split_unit": "issue", "one_group_per_id": True,
                         "pass_counted": False, "retired_set": "replayed, not counted, blocks its Issues",
                         "copies_of_an_id": "worst verdict", "tuning_rows_required": True,
                         "sheet_only": sorted(sheet_only())},
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
    # K6 r12 M1: the reports on stdout too — not only inside the file
    shown = {"verified": rep["verified"], "out": a.out,
             "replayed": sorted(g for g, v in rep["groups"].items() if isinstance(v, dict) and v.get("replayed"))}
    for k in ("_unknown_groups", "_rows_rejected", "_conflicting_groups"):
        if k in rep["groups"]:
            shown[k] = rep["groups"][k]
    print(json.dumps(shown, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
