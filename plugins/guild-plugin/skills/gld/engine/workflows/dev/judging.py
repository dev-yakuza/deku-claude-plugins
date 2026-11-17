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
         "GATECAST": "sonnet", "MUTATION": "sonnet"}
LAYER = {"RUNNER": "MJ", "PRMATCH": "MJ", "FOLLOWUP": "MJ", "DWC": "MJ", "IDENT": "MJ", "SAMECAUSE": "MJ",
         "BRANCH": "MJ", "GATECAST": "MJ+", "MUTATION": "MJ+"}
CHOICE = {"TEST": "overall", "EX-ARB": "summary"}
UNSURE = {"TEST": "gap", "QA": "block", "VIS-ENV": "env_suspect", "DIRECTIVE": "out_of_scope",
          "RUNNER": None, "PRMATCH": "none", "FOLLOWUP": "needs_filing", "DWC": "partial_read",
          "EX-ARB": "accept", "IDENT": "different", "SAMECAUSE": "different", "BRANCH": "unrelated",
          "GATECAST": "convene", "MUTATION": "mutation"}
BUDGET = {"SJ": 0.5, "MJ": 0.05, "MJ+": 0.3}
CAPS = {"SJ": 25000, "MJ": 6000, "MJ+": 12000}
NO_ELIDE = {"TEST": ("excerpts",), "DIRECTIVE": ("comments",), "EX-ARB": ("findings", "hunks")}
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


COERCIONS = {"QA": (coerce_qa,), "PRMATCH": (coerce_prmatch,), "FOLLOWUP": (coerce_followup,)}


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
    tools = "Read,Grep" if group in ("TEST", "EX-ARB") else ""
    m = model
    if m is None and p is not None:
        m = ((p.engine_cfg("judges", {}) or {}).get(group) or {}).get("model")
    return JudgeSpec(group, m or TIERS[group], schema(group), system_parts(p, group), brief_parts,
                     point=point or group, tools=tools, no_elide=NO_ELIDE.get(group, ()),
                     choice_key=CHOICE.get(group, "verdict"), unsure_default=UNSURE[group],
                     coercions=COERCIONS.get(group, ()), budget_usd=BUDGET[layer],
                     cap_chars=CAPS[layer], needs_more_fn=needs_more_fn,
                     cwd=cwd if tools else None, issue=p.issue if p else None, stage=stage,
                     step=step, plugin=p.plugin if p else None)
