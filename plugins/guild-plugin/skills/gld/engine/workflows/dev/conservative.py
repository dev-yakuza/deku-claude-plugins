"""workflows.dev.conservative — THE conservative path of the §9.5 count rule (K5r5-M3, design §9.5 rule 2, §10.5).

`group.<g>.conservative` (an `auto` valve the count rule sets, or a person's) means "that group's decisions go to a
person (ask / pause)". One gate does it for every L0/SJ judgment, whatever stage asked for it:

    Ports.judge(spec) → the judge's Decision → gate(p, spec, d)

* not a gated group, a shadow (`HANDOFF-SHADOW`), the valve off, or the judge already took the group's conservative
  default (§3.1 `judging.UNSURE` — STAKES high, QA block, TEST gap, DE-ARB pause …) → the Decision as it is;
* a person already answered this decision's question (`refs: conservative:<G>:<inputs>`) → a Decision carrying the
  person's choice (`by: human`, `coerced_by: conservative`, `raw_choice` = the judge's) — the stage goes on with it;
  `stop` → the run holds there (`Hold`);
* otherwise `Ask` is raised: the FSM turns it into an attended ask / unattended pause at that stage (`surface`) —
  predict-first (the judge's choice is the sealed recommendation; `raised_by: confirm`, so a different blind answer
  is a §9.5 wrong CANDIDATE — user decision 2026-11-19) — and the stage runs again after the answer (the judge call is
  a journal-cache hit: same inputs, no new cost).

EX-ARB is not gated here: its conservative side is the first-sprint coercion (`firstsprint.no_dismiss` →
`coerced_by: conservative`, BLOCKER/MAJOR dismiss → accept). KICKOFF: the interpretation is confirmed with a person
(`analyze` — attended `firstsprint.confirm_interpretation`, unattended a blind pause). The §10.2-6 unverified groups
(K6 replay output) join through `active`.
"""

from guildcore import ask as ASK

GATED = ("STAKES", "SPLIT", "INTEGRATE", "TEST", "QA", "DE-ARB", "AN-PO", "VIS-ENV", "DIRECTIVE", "HANDOFF", "EX-DWC")
KIND = "group-conservative"
NOT_OPTIONS = ("unsure",)


class Ask(BaseException):
    """Raised through the stage (BaseException: a stage's own `except Exception` fallback must not swallow it) to the
    FSM, which asks / pauses with `question` at the running stage."""

    def __init__(self, question, line):
        BaseException.__init__(self, line)
        self.question, self.line = question, line


class Hold(BaseException):
    """The person answered `stop` to a conservative question — the run holds (nothing more is decided)."""

    def __init__(self, line):
        BaseException.__init__(self, line)
        self.line = line


def active(p, group):
    from workflows.dev import predict as PF
    return bool(group) and PF.conservative(p, group)


def any_active(p):
    v = getattr(p, "valves", None) or {}
    return any(k.startswith("group.") and k.endswith(".conservative") and v.get(k) not in (None, False, "false", "off")
               for k in v)


def options_of(spec):
    """The group's choices (its schema's enum for the choice key, without `unsure`) — or None (free-form: not gated)."""
    prop = ((spec.schema or {}).get("properties") or {}).get(spec.choice_key) or {}
    enum = [x for x in (prop.get("enum") or []) if x not in NOT_OPTIONS]
    return enum or None


def key_of(group, d):
    return "conservative:%s:%s" % (group, str(getattr(d, "digest", "") or "")[:12])


def _answer(p, key):
    """(choice, resolution id) of a person's answer to the question with `refs: key`, or (None, None)."""
    from guildcore.decisions import DecisionLog
    from workflows.dev.stages import base as B
    log = DecisionLog.load(B.records(p))
    for blk in reversed(log.blocks):
        if blk.get("kind") != KIND or blk.get("refs") != key or blk.get("status") != "pending-human":
            continue
        res = [b for b in log.blocks if b.get("resolves") == blk.id and b.get("by") == "human" and b.get("choice")]
        if res:
            return res[-1].get("choice"), res[-1].id
    return None, None


def gate(p, spec, d):
    """The judge's Decision through the conservative path (see the module doc)."""
    g = getattr(spec, "group", None)
    if d is None or g not in GATED or str(getattr(spec, "point", "") or "").endswith("-SHADOW"):
        return d
    if not any_active(p) or not active(p, g):
        return d
    from workflows.dev import judging as JG
    safe = JG.UNSURE.get(g)
    if d.choice == safe or d.choice is None:
        return d
    opts = options_of(spec)
    if not opts or d.choice not in opts:
        return d
    key = key_of(g, d)
    ans, rid = _answer(p, key)
    if ans == "stop":
        raise Hold("group.%s.conservative: a person answered stop (%s)" % (g, rid))
    if ans in opts:
        from guildcore.judges.runner import Decision
        f = dict(d.fields or {})
        f[spec.choice_key] = ans
        return Decision(ans, f, "human", d.digest, unsure=False, coerced=True, coerced_by="conservative",
                        raw_choice=d.choice, cost=0.0, cached=True, model=d.model)
    irr = any(n == "irreversible" and str(t).strip() not in ("", "none") for n, t in (spec.brief_parts or []))
    # stakes high always: a conservative group's answer is a gate answer (§2.5 — the answerer removes the label)
    line = "group.%s.conservative — %s %s 결정을 사람이 정함" % (g, g, spec.step or spec.point or "")
    q = ASK.Question(KIND, line, [{"token": o, "label": o} for o in opts] + [{"token": "stop", "label": "stop"}],
                     recommended=d.choice, recommended_by=d.by, refs=key, group=g, stakes="high",
                     neutral="#%d: group.%s.conservative — %s(%s) 를 어느 쪽으로 정할까요?" % (
                         int(p.issue), g, g, spec.step or spec.point or "-"), raised_by="confirm")
    q.point = "conservative:%s" % g
    q.irreversible = irr
    raise Ask(q, line)


def surface(p, stage, ask):
    """The FSM's side: ask (attended) / pause (unattended) with the gate's question at `stage`."""
    from workflows.dev.stages import base as B
    line = ask.line
    return B.ask(p, stage, ask.question, line, {"cause_kind": "ambiguity", "line": line,
                                                 "token_cause": "ambiguity: %s" % line})


def hold(p, stage, h):
    from workflows.dev.stages import base as B
    return B.StageResult(B.StageResult.HOLD, line=h.line)
