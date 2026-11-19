"""workflows.dev.judging — JudgeSpecs for the test/qa groups (§3.1, §3.3, §3.4).

| group     | tier   | tools          | unsure default (§3.1)            | coercions                     |
|-----------|--------|----------------|----------------------------------|-------------------------------|
| TEST      | sonnet | Read,Grep(repo)| overall → gap                    | (code `effective` check runs after, in the stage) |
| QA        | sonnet | —              | verdict → block                  | fixable unsure → no; blocking defect or bar ≠ yes → block |
| VIS-ENV   | sonnet | —              | → env_suspect (NH visual env.)   | —                             |
| DIRECTIVE | sonnet | —              | → out_of_scope (ask / pause)     | —                             |
| RUNNER    | haiku  | —              | stays unsure (env pause, §2.8)   | —                             |
| PRMATCH   | haiku  | —              | → none                           | match without a pr → none     |
| FOLLOWUP  | haiku  | —              | → needs_filing                   | covered without an issue → needs_filing |
| DWC       | haiku  | —              | → partial_read (one re-dispatch) | —                             |
System = `judges/leader-core.md` + the repo leader's `## 프로젝트 특화`/`[J:<group>]` habits (SJ only,
§8.1) + `judges/<group>.md`. Generated decisions go to the decision log (SJ) or the journal (MJ).
"""

import json
import os
import re

from guildcore.judges.runner import JudgeSpec

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "judges")
TIERS = {"TEST": "sonnet", "QA": "sonnet", "VIS-ENV": "sonnet", "DIRECTIVE": "sonnet",
         "RUNNER": "haiku", "PRMATCH": "haiku", "FOLLOWUP": "haiku", "DWC": "haiku",
         # K3 execute (§3.3 EX-ARB — opus when a BLOCKER/MAJOR is in the brief, chosen by the caller;
         # §3.4 IDENT/SAMECAUSE/BRANCH haiku, GATECAST/MUTATION sonnet "MJ+")
         "EX-ARB": "sonnet", "IDENT": "haiku", "SAMECAUSE": "haiku", "BRANCH": "haiku",
         "GATECAST": "sonnet", "MUTATION": "sonnet", "EX-DWC": "sonnet",
         # K4 (§3.1–3.3): L0 KICKOFF/SPLIT/INTEGRATE opus --effort high; SJ-STAKES opus; AN-PO, DE-ARB,
         # HANDOFF sonnet
         "KICKOFF": "opus", "SPLIT": "opus", "INTEGRATE": "opus", "STAKES": "opus", "AN-PO": "sonnet",
         "DE-ARB": "sonnet", "HANDOFF": "sonnet"}
LAYER = {"RUNNER": "MJ", "PRMATCH": "MJ", "FOLLOWUP": "MJ", "DWC": "MJ", "IDENT": "MJ", "SAMECAUSE": "MJ",
         "BRANCH": "MJ", "GATECAST": "MJ+", "MUTATION": "MJ+",
         "KICKOFF": "L0", "SPLIT": "L0", "INTEGRATE": "L0", "STAKES": "SJ-opus"}
CHOICE = {"TEST": "overall", "EX-ARB": "summary", "STAKES": "level", "AN-PO": "action", "DE-ARB": "action",
          "SPLIT": "decision"}
UNSURE = {"TEST": "gap", "QA": "block", "VIS-ENV": "env_suspect", "DIRECTIVE": "out_of_scope",
          "RUNNER": None, "PRMATCH": "none", "FOLLOWUP": "needs_filing", "DWC": "partial_read",
          "EX-ARB": "accept", "IDENT": "different", "SAMECAUSE": "different", "BRANCH": "unrelated",
          "GATECAST": "convene", "MUTATION": "mutation", "EX-DWC": "proceed",
          # K4: §3.1 conservative defaults — KICKOFF not ready, STAKES high, AN-PO re-rate (unclear),
          # DE-ARB pause, SPLIT stays unsure (the stage asks a person), INTEGRATE gap, HANDOFF upstream gap
          "KICKOFF": "not_ready", "STAKES": "high", "AN-PO": "rerate_success", "DE-ARB": "pause",
          "SPLIT": None, "INTEGRATE": "gap", "HANDOFF": "upstream_gap"}
BUDGET = {"SJ": 0.5, "MJ": 0.05, "MJ+": 0.3, "L0": 2.0, "SJ-opus": 1.0}
CAPS = {"SJ": 25000, "MJ": 6000, "MJ+": 12000, "L0": 40000, "SJ-opus": 25000}
NO_ELIDE = {"TEST": ("excerpts",), "DIRECTIVE": ("comments",), "EX-ARB": ("findings", "hunks"),
            # CR-M12: KICKOFF's human comments (and the Issue itself) are never elided
            "KICKOFF": ("issue", "comments")}
TOOLS = {"TEST": "Read,Grep", "EX-ARB": "Read,Grep", "INTEGRATE": "Read,Grep,Glob"}
EFFORT = {"KICKOFF": "high", "SPLIT": "high", "INTEGRATE": "high"}
HEDGES = ("권장", "가능하면", "여유되면", "미검증(참고)")
# K2-m1: removal only where the hedge is a FRAME — parenthesised, or leading the item — never a
# substring of a meaningful word ("권장 설정이 표시되는지" stays; the lint re-ask handles wording)
_HEDGE_PAREN = re.compile(r"\s*\((?:%s|optional|if possible)\)" % "|".join(re.escape(h) for h in HEDGES))
_HEDGE_LEAD = re.compile(r"^(?:%s)\s*[:：]?\s+" % "|".join(re.escape(h) for h in HEDGES))


def _read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as fh:
        return fh.read()


def schema(group):
    return json.loads(_read(os.path.join("schemas", group + ".json")))


def coerce_qa(fields):
    by = None
    for d in fields.get("defects") or []:
        if d.get("fixable_in_code") == "unsure":
            d["fixable_in_code"] = "no"
            by = "rule"
    blocking = any(d.get("blocking") for d in fields.get("defects") or [])
    if fields.get("verdict") == "pass" and (blocking or fields.get("quality_bar_met") != "yes"):
        fields["verdict"] = "block"
        by = "rule"
    return fields, by


def coerce_prmatch(fields):
    if fields.get("verdict") == "match" and not fields.get("pr"):
        fields["verdict"] = "none"
        return fields, "rule"
    return fields, None


def coerce_followup(fields):
    if fields.get("verdict") == "covered" and not fields.get("issue"):
        fields["verdict"] = "needs_filing"
        return fields, "rule"
    return fields, None


def coerce_stakes(fields):
    """§3.2: a low/medium without a reason why it is local AND reversible → high."""
    if fields.get("level") in ("low", "medium") and not (fields.get("local_reversible_reason") or "").strip():
        fields["level"] = "high"
        return fields, "rule"
    return fields, None


def coerce_an_po(fields):
    if fields.get("action") == "rerate_success":
        r = fields.get("rating")
        # K5r10-M1: re-rating means "Success is not settled" — never `clear` (the stage also caps it at KICKOFF's)
        if r not in ("partial", "unclear") or (r == "partial" and not fields.get("anchor")):
            fields["rating"] = "unclear"
            return fields, "rule"
    return fields, None


def coerce_de_arb(fields):
    a = fields.get("action")
    if (a == "reinvoke" and not (fields.get("role") and (fields.get("addendum") or "").strip())) or \
            (a == "decide" and not (fields.get("assumption") or "").strip()):
        fields["action"] = "pause"
        fields.setdefault("cause", "design arbitration without a usable %s" % a)
        return fields, "rule"
    if a == "escalate" and fields.get("reason") not in ("executor_conflict", "cross_stage"):
        fields["action"] = "pause"
        return fields, "rule"
    return fields, None


def coerce_split(fields):
    if fields.get("decision") == "split" and len(fields.get("slices") or []) < 2:
        fields["decision"] = "unsure"
        return fields, "rule"
    return fields, None


def coerce_integrate(fields):
    if fields.get("verdict") == "gap" and not fields.get("gaps"):
        fields["gaps"] = [{"kind": "coverage", "needs_decision": True, "line": "integration judged a gap without naming it"}]
        return fields, "rule"
    return fields, None


def _test_gap(fields, why):
    """TEST `overall: gap` while no AC (and no visual row) is left short of effective/covered: the gap the choice
    names is not in the per-AC verdicts the test stage derives its outcome from (`_judge_coverage`) — every AC the
    verdicts call effective becomes `unsure` (the coverage-gap path: repair once, then uncovered)."""
    acs = [a for a in fields.get("ac") or [] if isinstance(a, dict)]
    rows = [r for r in fields.get("visual_rows") or [] if isinstance(r, dict)]
    if any(a.get("verdict") != "effective" for a in acs) or any(r.get("verdict") != "covered" for r in rows):
        return fields, None
    fields["ac"] = [dict(a, verdict="unsure", why=why) for a in acs]
    return fields, "rule"


def coerce_test(fields):
    """K5r9-M1: the choice and the per-AC verdicts agree — `gap` with every AC effective names no gap the stage can
    see (→ `_test_gap`); `all_effective` with an AC short of effective is a gap."""
    o = fields.get("overall")
    if o == "gap":
        return _test_gap(fields, "the judgment named a gap without an AC")
    acs = [a for a in fields.get("ac") or [] if isinstance(a, dict)]
    if o == "all_effective" and any(a.get("verdict") != "effective" for a in acs):
        fields["overall"] = "gap"
        return fields, "rule"
    return fields, None


def coerce_handoff(fields):
    v = fields.get("verdict")
    if v == "upstream_gap" and fields.get("fixable_by_execute") and not fields.get("signature"):
        fields["fixable_by_execute"] = False
        return fields, "rule"
    if v == "ok_with_assumption" and not (fields.get("line") or "").strip():
        fields["verdict"] = "upstream_gap"
        fields["fixable_by_execute"] = False
        return fields, "rule"
    return fields, None


COERCIONS = {"TEST": (coerce_test,), "QA": (coerce_qa,), "PRMATCH": (coerce_prmatch,), "FOLLOWUP": (coerce_followup,),
             "STAKES": (coerce_stakes,), "AN-PO": (coerce_an_po,), "DE-ARB": (coerce_de_arb,),
             "SPLIT": (coerce_split,), "INTEGRATE": (coerce_integrate,), "HANDOFF": (coerce_handoff,)}


# K5r10-M1/m1: per gated group, the result fields that belong to ONE option — written by a judge only when it chose that
# option. A field listed under several options is shared by them. Fields not listed (reason, coverage, defects, cites …)
# are the judgment's observations and stay whatever was chosen.
OPTION_FIELDS = {
    "AN-PO": {"rerate_success": ("rating", "anchor")},
    "DE-ARB": {"reinvoke": ("role", "addendum"), "decide": ("assumption",),
               "escalate": ("reason", "question", "options"), "pause": ("cause", "options")},
    "SPLIT": {"split": ("slices",)},
    "INTEGRATE": {"gap": ("gaps",)},
    "HANDOFF": {"ok_with_assumption": ("line",), "upstream_gap": ("signature", "fixable_by_execute")},
    "STAKES": {"low": ("local_reversible_reason",), "medium": ("local_reversible_reason",)},
    "QA": {"pass": ("quality_bar_met",)},
    "DIRECTIVE": {"applies": ("applies",), "out_of_scope": ("out_of_scope",)},
    # TEST: the per-AC / visual-row verdicts back the choice — `_human_test_gap`
}


def _person_line(choice, who):
    return {"gap": "사람이 간극으로 판정 (%s)", "applies": "사람이 적용할 지시로 판정 (%s)",
            "out_of_scope": "사람이 범위 밖 지시로 판정 (%s)"}.get(choice, "사람이 " + choice + " 로 판정 (%s)") % who


def _fill(g, x, f, who):
    """The conservative/neutral value of option `x`'s own field when the judge did not choose `x` — the value that
    guarantees `x`'s effect (or, where `x` needs grounds nobody gave, its group's coercion takes the safe path)."""
    if g == "AN-PO" and x == "rerate_success":
        return {"rating": "unclear", "anchor": None}               # → the readiness question / re-rating
    if g == "HANDOFF" and x == "upstream_gap":
        return {"fixable_by_execute": False}                       # → a person / escalation, never an engine fix
    if g == "INTEGRATE" and x == "gap":
        return {"gaps": [{"kind": "coverage", "needs_decision": True, "child_to_fix": None,
                          "line": "사람이 통합 간극으로 판정 (%s)" % who}]}
    if g == "DIRECTIVE" and x in ("applies", "out_of_scope"):
        # the comments the judge read stay (which comment — not what the judge made of it); the line is the person's
        refs = [c.get("comment") for k in ("applies", "out_of_scope") for c in f.get(k) or [] if isinstance(c, dict)]
        return {x: [{"comment": refs[0] if refs else None, "line": _person_line(x, who)}]}
    return {}


def _human_test_gap(f, who):
    """K5r10-m1: a person's `gap` over a judge's `all_effective` — every AC the judge called effective and every visual
    row it called covered becomes `unsure` (stray rows on an Issue without visual cases included: the stage never reads
    those, so the gap is in the ACs)."""
    why = "사람이 커버리지 간극으로 판정 (%s)" % who
    f["ac"] = [dict(a, verdict="unsure", why=why) if a.get("verdict") == "effective" else a
               for a in f.get("ac") or [] if isinstance(a, dict)]
    f["visual_rows"] = [dict(r, verdict="unsure") if r.get("verdict") == "covered" else r
                        for r in f.get("visual_rows") or [] if isinstance(r, dict)]
    return f


def own_fields(group, x, judged, fields, who):
    """K5r10-M1: the judge chose `judged`, a person chose `x`: the option-specific fields of every option other than
    `x` are dropped (they were written for another choice), `x`'s own fields the judge's choice does not share are
    replaced by `_fill` (or dropped); fields `x` shares with `judged` stay."""
    f = dict(fields or {})
    if x == judged:
        return f
    if group == "TEST" and x == "gap":
        return _human_test_gap(f, who)
    table = OPTION_FIELDS.get(group) or {}
    mine, theirs = set(table.get(x, ())), set(table.get(judged, ()))
    for k in set(k for ks in table.values() for k in ks):
        if not (k in mine and k in theirs):
            f.pop(k, None)
    f.update({k: v for k, v in _fill(group, x, fields or {}, who).items() if k in mine - theirs})
    return f


def apply_choice(spec, fields, choice, who=None):
    """K5r9-M1/M2: a person's answer to a conservative question (conservative.gate) has EXACTLY the downstream effect
    the judge's choosing that option would have had: the choice key is set and the group's coercions run over the
    judge's fields — the same consistency rules the judge's own output went through (runner) — so a stage that derives
    its outcome from other fields (TEST: per-AC verdicts, INTEGRATE: gaps) sees the person's choice there too.
    K5r10-M1: a person's choice never runs on fields the judge wrote for ANOTHER option (`own_fields`).
    `who` (e.g. "D12") names the person's decision in the line a rewrite writes. Returns (fields, final choice, rule) —
    `rule` names the coercion that replaced the person's choice (None when the choice stands)."""
    from guildcore.judges.runner import _get, _set
    g = spec.group
    judged = _get(dict(fields or {}), spec.choice_key)
    f = own_fields(g, choice, judged, fields, who) if who else dict(fields or {})
    _set(f, spec.choice_key, choice)
    if who and g == "TEST" and choice == "gap":
        f, _ = _test_gap(f, "사람이 커버리지 간극으로 판정 (%s)" % who)
    if who and g == "INTEGRATE" and choice == "gap" and not [x for x in f.get("gaps") or [] if isinstance(x, dict)]:
        f["gaps"] = [{"kind": "coverage", "needs_decision": True, "child_to_fix": None,
                      "line": "사람이 통합 간극으로 판정 (%s)" % who}]
    rule = None
    for co in getattr(spec, "coercions", None) or ():
        before = _get(f, spec.choice_key)
        f, b = co(f)
        if b and rule is None and _get(f, spec.choice_key) != before:
            rule = co.__name__
    return f, _get(f, spec.choice_key), rule


def hedged(items):
    return [i for i in items or [] if any(h in i for h in HEDGES)]


def strip_hedges(item):
    out = _HEDGE_LEAD.sub("", _HEDGE_PAREN.sub("", item))
    return " ".join(out.split())


def system_parts(p, group):
    parts = [_read("leader-core.md")]
    if LAYER.get(group) not in ("MJ", "MJ+") and p is not None and p.config is not None and hasattr(p.config, "persona"):
        try:
            per = p.config.persona("leader")
            habits = per.habits(group) if per else []
            if habits:
                parts.append("## 프로젝트 특화 (습관)\n" + "\n".join(habits))
        except Exception:                      # a missing/odd leader persona never blocks a judgment
            pass
    parts.append(_read(group + ".md"))
    return parts


def spec(p, group, brief_parts, stage, step, point=None, model=None, cwd=None, needs_more_fn=None):
    layer = LAYER.get(group, "SJ")
    tools = TOOLS.get(group, "")
    m = model
    valves = dict(getattr(p, "valves", None) or {}) if p is not None else {}
    if m is None and valves.get("judges.%s.model" % group):
        m = valves["judges.%s.model" % group]                    # §10.5 tier valve
    if m is None and p is not None:
        m = ((p.engine_cfg("judges", {}) or {}).get(group) or {}).get("model")
    notes = [d for d in (getattr(p, "directives", None) or []) if d.get("stage") in (None, stage)] if p else []
    if notes:                                                     # §2.6 attended `dev note` — a human directive
        brief_parts = list(brief_parts) + [("directive", "Human directives for this stage (attended `dev note`, "
                                            "by: human — they take precedence over your own reading):\n" +
                                            "\n".join("- %s: %s" % (d.get("id"), d.get("text")) for d in notes))]
    return JudgeSpec(group, m or TIERS[group], schema(group), system_parts(p, group), brief_parts,
                     point=point or group, tools=tools, no_elide=NO_ELIDE.get(group, ()),
                     choice_key=CHOICE.get(group, "verdict"), unsure_default=UNSURE[group],
                     coercions=COERCIONS.get(group, ()), budget_usd=BUDGET[layer],
                     cap_chars=CAPS[layer], needs_more_fn=needs_more_fn,
                     cwd=cwd if tools else None, issue=p.issue if p else None, stage=stage,
                     step=step, plugin=p.plugin if p else None, effort=EFFORT.get(group), valves=valves)
