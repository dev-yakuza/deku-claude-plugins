"""workflows.dev.health — `dev health [--first-sprint] [--sprint T | --issues N,M]` (design §9.4-6, §10.4, §10.5(c)).

Read-only over GitHub (the trusted decision logs of the Issues) and this clone's engine files (cost.jsonl,
grades.jsonl, grade-state.json, progress logs). It prints:
* the leading-indicator RATES of §9.4-6 (EX-ARB dismiss, KICKOFF clear, STAKES low, HANDOFF
  ok_with_assumption, unsure, coercion — first-sprint / valve coercions excluded —, pause and loop-back
  Issues) against the centre in `<engine>/health-center.json` when one is recorded (the held-out replay
  distribution — written by the K6 replay, never guessed here), with the band of §9.4-6; no centre → the
  rates alone, marked `centre unset`;
* the ABSOLUTE tripwires (any one → "review within 1 day"): a forbidden-command attempt, a role scope
  violation, an engine unknown state, a GitHub write that did not land, a pause without a cause line, the same
  Issue crashing twice;
* the §9.5 count-rule state (watched / conservative groups, confirmed wrongs per group);
* with `--first-sprint`: the written go/no-go DRAFT (G1–G7 — the person decides and posts it as a
  `<!-- guild:note -->` `first-sprint go/no-go` comment on the tracker; nothing is posted here);
* a downgrade RECOMMENDATION when one of §10.5(c)'s computable conditions holds (the person decides).
"""

import json
import os
import re

from guildcore import journal as J
from guildcore import valves as VALVES

# §9.4-6 bands (fixed — known limit Q20): (metric, kind, threshold over the centre)
BANDS = (("exarb_dismiss", "lenient", 0.10), ("kickoff_clear", "lenient", 0.15), ("stakes_low", "lenient", 0.15),
         ("handoff_ok_with_assumption", "absolute", 0.25), ("kickoff_unclear", "strict", 0.15),
         ("stakes_high", "strict", 0.15), ("pause_issues", "strict", 0.10), ("loopback_issues", "strict", 0.10),
         ("unsure", "absolute", 0.20), ("coercion", "absolute", 0.15))
ABSOLUTE = (("forbidden-command", r"forbidden|denied command"), ("scope-violation", r"wrote outside its scope"),
            ("unknown-state", r"engine unknown state"), ("write-not-landed", r"did not land on re-read"))


def _rate(n, d):
    return (float(n) / d) if d else None


def metrics(blocks_by_issue):
    m = {"issues": len(blocks_by_issue)}
    cnt = {}

    def add(k, hit):
        a, b = cnt.get(k, (0, 0))
        cnt[k] = (a + (1 if hit else 0), b + 1)
    pause_issues = loop_issues = 0
    for _n, blocks in blocks_by_issue.items():
        paused = looped = False
        for b in blocks:
            pt, ch = (b.get("point") or ""), (b.get("raw_choice") or b.get("choice") or "")
            judged = (b.get("by") or "").startswith(("judge:", "leader:"))
            if pt.startswith("EX-ARB") and judged:
                add("exarb_dismiss", "dismiss" in ch)
            if pt == "KICKOFF" and judged:
                add("kickoff_clear", ch == "clear" or "ready" == ch)
                add("kickoff_unclear", "unclear" in ch or ch == "not_ready")
            if pt == "STAKES" and judged:
                add("stakes_low", ch == "low")
                add("stakes_high", ch == "high")
            if pt == "HANDOFF" and judged:
                add("handoff_ok_with_assumption", ch == "ok_with_assumption")
            if judged:
                add("unsure", str(b.get("unsure")).lower() == "true")
                add("coercion", str(b.get("coerced")).lower() == "true" and b.get("coerced_by") not in ("first-sprint", "valve"))
            if b.get("status") == "pending-human" or pt.startswith("ask:") or b.get("cause"):
                paused = True
            if pt in ("loopback", "loop-back") or "loop" in pt:
                looped = True
        pause_issues += paused
        loop_issues += looped
    for k, (a, b) in cnt.items():
        m[k] = _rate(a, b)
    m["pause_issues"] = _rate(pause_issues, len(blocks_by_issue))
    m["loopback_issues"] = _rate(loop_issues, len(blocks_by_issue))
    return m


def compare(m, centre):
    """[(metric, value, centre, verdict)] — verdict ok | over | under-warning | n/a."""
    out = []
    for k, kind, th in BANDS:
        v = m.get(k)
        c = (centre or {}).get(k)
        if v is None:
            out.append((k, v, c, "n/a"))
            continue
        if kind == "absolute":
            out.append((k, v, c, "over" if v > th else "ok"))
            continue
        if c is None:
            out.append((k, v, c, "centre unset"))
            continue
        if v - c > th:
            out.append((k, v, c, "over"))
        elif c - v > 0.15:
            out.append((k, v, c, "under-warning"))
        else:
            out.append((k, v, c, "ok"))
    return out


def absolute_tripwires(common, issues, texts):
    """[(tripwire, issue, evidence)] from the decision-log / needs-human texts and the progress logs."""
    hits = []
    for n in issues:
        t = texts.get(n, "")
        for name, rx in ABSOLUTE:
            if re.search(rx, t, re.I):
                hits.append((name, n, re.search(rx, t, re.I).group(0)))
        if re.search(r"<!-- guild:needs-human -->\s*\n\s*(\n|$)", t):
            hits.append(("pause-without-cause", n, "empty needs-human cause line"))
        try:
            with open(os.path.join(J.issue_dir(common, n), "progress.log"), encoding="utf-8") as fh:
                crashes = sum(1 for ln in fh if re.search(r"end: exit 1\b", ln))
        except IOError:
            crashes = 0
        if crashes >= 2:
            hits.append(("crash-twice", n, "%d runs ended with exit 1" % crashes))
    return hits


def go_no_go(m, trips, cmp, watched, cons, n_issues, cost_rows):
    """The G1–G7 draft lines (§10.4) — values where this clone has them, `n/a (…)` where it does not."""
    lines = ["<!-- guild:note -->", "first-sprint go/no-go (DRAFT — a person decides and posts this)", ""]
    lines.append("- G1 판단 오답: watch=%s conservative=%s — %s" % (
        ",".join(watched) or "none", ",".join(cons) or "none",
        "no-go (conservative groups >= 2)" if len(cons) >= 2 else "see the graded sheet"))
    bad = [t for t in trips if t[0] in ("forbidden-command", "scope-violation")]
    lines.append("- G2 불변식: %s" % ("violations: %s" % "; ".join("#%d %s" % (n, k) for k, n, _e in bad) if bad else "0"))
    lines.append("- G3 권한: n/a (dev denials report)")
    over = [k for k, _v, _c, verdict in cmp if verdict == "over" and k in ("pause_issues", "loopback_issues")]
    lines.append("- G4 흐름: %s" % ("over the first-sprint centre: %s" % ", ".join(over) if over else "within band / centre unset"))
    lines.append("- G5 리뷰: n/a (review.md decision links)")
    crash = [t for t in trips if t[0] == "crash-twice"]
    lines.append("- G6 안정성: %d Issue(s) crashed twice" % len(crash))
    usd = sum(float(r.get("total_cost_usd") or 0) for r in cost_rows)
    lines.append("- G7 비용(보고만): score $%.2f over %d Issue(s)%s" % (
        usd, n_issues, " — fewer than 30 engine Issues: not judged" if n_issues < 30 else ""))
    lines.append("result: <go|no-go — the person writes it>")
    return lines


def downgrade_advice(trips, cmp, gstate, cons_groups):
    """§10.5(c) — the computable conditions only; returns [reason]."""
    out = []
    if len(cons_groups) >= 2:
        out.append("two or more groups are conservative at once")
    if sum(1 for t in trips if t[0] in ("forbidden-command", "write-not-landed")) >= 2:
        out.append("a forbidden command or an unlanded GitHub write repeated")
    return out


def main(d, a):
    from guildcore import cost as COST
    from guildcore import emit
    from guildcore.decisions import DecisionLog
    from guildcore.records import markers
    from workflows.dev import grade as G
    common = d.common()
    gh = d.gh()
    issues = G._issues(d, a, gh) or sorted(set(int(r["issue"]) for r in COST.rows(common) if r.get("issue")))
    by_issue, texts = {}, {}
    for n in issues:
        cs = markers.trusted(gh.comments(n), ())
        log = DecisionLog.load(cs)
        gone = log.resolved_ids()
        by_issue[n] = [b for b in log.blocks if b.id not in gone]
        texts[n] = "\n".join(markers.body_of(c) for c in cs)
    m = metrics(by_issue)
    centre = None
    try:
        with open(os.path.join(J.engine_dir(common), "health-center.json"), encoding="utf-8") as fh:
            centre = json.load(fh)
    except (IOError, ValueError):
        pass
    cmp = compare(m, centre)
    trips = absolute_tripwires(common, issues, texts)
    gstate = G.load_state(common)
    auto = VALVES.load(common)["auto"]
    cons = sorted(k for k, v in auto.items() if k.endswith(".conservative") and v)
    rep = {"issues": issues, "rates": [{"metric": k, "value": v, "centre": c, "verdict": vd} for k, v, c, vd in cmp],
           "absolute_tripwires": [{"tripwire": k, "issue": n, "evidence": e} for k, n, e in trips],
           "review_within_1_day": bool(trips), "watch": sorted(gstate.get("watch", {})), "conservative": cons,
           "downgrade_recommended": downgrade_advice(trips, cmp, gstate, cons)}
    if getattr(a, "first_sprint", False):
        rep["go_no_go_draft"] = go_no_go(m, trips, cmp, rep["watch"], cons, len(issues), COST.rows(common))
    emit.engine(rep, out=d.out)
    return 0
