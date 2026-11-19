"""workflows.dev.dual — the §9.4-7 dual judgment (K6 item 11: "불일치 촉발").

A deterministic share of judge decisions (`config.engine.dual_judge_rate`, default 10 % — the live Ports set
`p.dual_rate`; harness-built Ports have 0) is judged a second time by ANOTHER tier on the same brief. The second
decision never changes the flow — it is monitoring (kind `monitoring`, no cache). The decision block records
`dual: agree|disagree`, `dual_choice`, `dual_model`; a disagreement is a §9.5 trigger (the decision is always graded)
and `dev health` reports the disagreement rate against its band (> 25 %).
Only the §9.5 DECISION groups (`valves.GROUPS` — KICKOFF, STAKES, SPLIT, QA, TEST, EX-ARB …; K6 r1 m4): a helper
judgment (IDENT, SAMECAUSE, PRMATCH, RUNNER, FOLLOWUP, MUTATION, GATECAST, DWC, BRANCH …) is never recorded as a
decision block — doubling it would cost a second tier on every call of a selected Issue for nothing to read.
Not dual-judged: a person's decision, a coerced / cached replay, a shadow, the grader's own calls, a helper.
K6 r2 m2 — what the sample is: a gated group's NON-conservative pick never returns from the gate (it raises the
blind question), so `check` on the gate's result alone sampled only its conservative picks — the conservative gate
now calls `check` itself just before the question (the result rides in the local tape, never on the pending block,
and lands on the applied block; `dev health` counts it against the judge's pick). Remaining bias: a clone without
the tape loses that dual result. Cost: the rate is a share of judge CALLS; the second call runs on `OTHER` (sonnet →
opus), so its cost share is higher than the rate — "+10 %" is a call count, not dollars.
"""

import copy
import hashlib

DEFAULT_RATE = 0.10
OTHER = {"opus": "sonnet", "sonnet": "opus", "haiku": "sonnet"}


def other_tier(model):
    m = str(model or "")
    for k, v in OTHER.items():
        if k in m:
            return v
    return "opus"


def decision_group(group):
    """K6 r1 m4: is `group` a §9.5 decision group (its result is a recorded decision block)?"""
    from guildcore import valves as VALVES
    g = str(group or "")
    return g in VALVES.GROUPS or ("%s-dismiss" % g) in VALVES.GROUPS


def selected(p, spec, rate):
    if not rate or rate <= 0:
        return False
    key = "%s|%s|%s|%s|%s" % (getattr(p, "issue", 0), spec.group, spec.point, spec.stage, spec.step)
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:8], 16) / float(0xFFFFFFFF) < float(rate)


def check(p, spec, d, raw):
    """`d` (the gate's result) with the dual fields when this decision is sampled; the flow uses `d` unchanged."""
    rate = getattr(p, "dual_rate", 0) or 0
    if d is None or not str(getattr(d, "by", "")).startswith("judge:") or getattr(d, "cached", False):
        return d
    if getattr(spec, "kind", "score") != "score" or str(spec.point or "").endswith("-SHADOW"):
        return d
    if not decision_group(getattr(spec, "group", None)):
        return d
    if not selected(p, spec, rate):
        return d
    s2 = copy.copy(spec)
    s2.model = other_tier(spec.model)
    s2.kind = "monitoring"
    s2.brief_parts = list(spec.brief_parts)
    try:
        d2 = raw(s2)
    except Exception as e:                                       # noqa: BLE001 — monitoring never breaks the flow
        if getattr(p, "journal", None) is not None:
            p.journal.append("event", what="dual-judge-failed", point=spec.point, why=str(e)[:200])
        return d
    if d2 is None:
        return d
    d.dual = "agree" if d2.choice == d.choice else "disagree"
    d.dual_choice, d.dual_model = d2.choice, s2.model
    return d
