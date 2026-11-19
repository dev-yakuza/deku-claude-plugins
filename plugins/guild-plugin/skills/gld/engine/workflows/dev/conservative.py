"""workflows.dev.conservative — THE conservative path of the §9.5 count rule (K5r5-M3, design §9.5 rule 2, §10.5).

`group.<g>.conservative` (an `auto` valve the count rule sets, or a person's) means "that group's decisions go to a
person (ask / pause)". One gate does it for every L0/SJ judgment, whatever stage asked for it:

    Ports.judge(spec) → the judge's Decision → gate(p, spec, d)

* not a gated group, a shadow (`HANDOFF-SHADOW`), the valve off, or the judge already took the group's conservative
  default (§3.1 `judging.UNSURE` — STAKES high, QA block, TEST gap, DE-ARB pause …) → the Decision as it is;
* a person already answered this DECISION POINT's question (`refs: conservative:<G>:#<N>:<stage>:<step>:L<loop>` —
  K5r6-M1: the point, never the judge's input digest) → that answer applies FIRST (the judge's taped decision, no new
  judge call): a Decision carrying the person's choice (`by: human`, `coerced_by: conservative`, `raw_choice` = the
  judge's) — the stage goes on with it, and a `point: applied` block records the application; `stop` → the run holds
  there (`Hold`);
* otherwise `Ask` is raised: the FSM turns it into an attended ask / unattended pause at that stage (`surface`) —
  predict-first (the judge's choice is the sealed recommendation; `raised_by: confirm`, so a different blind answer
  is a §9.5 wrong CANDIDATE — user decision 2026-11-19). The role results the stage got before asking are taped
  (journal) and REPLAYED when the stage runs after the answer (analyze/design/test/qa — no LLM role runs again); the
  execute→test hand-over question is consumed at the test stage's entry (`answered_unapplied`).

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


REPLAY_STAGES = ("analyze", "design", "test", "qa")   # execute/children: roles change the tree — their own re-entry
_MEM = {}                                               # tapes when a port has no journal (tests, the procedure replay)


def _loop_index(p):
    """The loop-back generation of the Issue (numbered blocks of the loop-back record): a decision point re-reached
    after a loop-back is a NEW decision point (a new question); the same point re-reached in the same generation —
    a stage run again after the answer — is the SAME one (K5r6-M1)."""
    from guildcore.records import loopback as LB
    from guildcore.records import markers
    from workflows.dev.stages import base as B
    try:
        c = markers.find(B.records(p), LB.NAME)
        return len(LB.LoopbackRecord.parse(markers.body_of(c)).numbered()) if c is not None else 0
    except Exception:                                    # noqa: BLE001 — an unreadable record is generation 0
        return 0


def point_key(p, spec, bump=True):
    """K5r6-M1: the question's key is the DECISION POINT — issue · stage · step · point · loop-back generation
    (· the n-th such judgment in one stage run) — never the judge's input digest (a stage re-runs its roles, whose
    output differs every run: a digest key asked a new question after every answer)."""
    g = spec.group
    point = str(spec.point or g)
    base = "conservative:%s:#%d:%s:%s:L%d" % (g, int(p.issue), spec.stage or "-", spec.step or "-", _loop_index(p))
    if point != g:
        base += ":" + point
    seen = p.__dict__.setdefault("_cons_seen", {})
    k = seen.get(base, 0) + (1 if bump else 0)
    if bump:
        seen[base] = k
    return base if k <= 1 else "%s#%d" % (base, k)


def key_of(group, d):                                   # pre-r6 keys (input digest) — read by nothing new
    return "conservative:%s:%s" % (group, str(getattr(d, "digest", "") or "")[:12])


def _answer(p, key):
    """(choice, resolution block, applied?) of a person's answer to the question with `refs: key` — or
    (None, None, False). Read by decision point, whatever the Issue's label is now."""
    from guildcore.decisions import DecisionLog
    from workflows.dev.stages import base as B
    log = DecisionLog.load(B.records(p))
    applied = set(b.get("refs") for b in log.blocks if b.get("point") == "applied")
    for blk in reversed(log.blocks):
        if blk.get("kind") != KIND or blk.get("refs") != key or blk.get("status") != "pending-human":
            continue
        res = [b for b in log.blocks if b.get("resolves") == blk.id and b.get("by") == "human" and b.get("choice")]
        if res:
            return res[-1].get("choice"), res[-1], res[-1].id in applied
    return None, None, False


def answered_unapplied(p, group, stage, step, point=None):
    """True when a person answered the question of this decision point (current generation) and no stage applied it
    yet — the FSM's test-entry check for the execute→test hand-over (its label already moved, K5r6-M1)."""
    class _S(object):
        pass
    s = _S()
    s.group, s.stage, s.step, s.point = group, stage, step, point or group
    ans, res, applied = _answer(p, point_key(p, s, bump=False))
    return ans is not None and not applied


# -- the replay tape: a stage that asked is run again after the answer WITHOUT re-running its LLM roles -----------------
def begin(p):
    """A stage run starts (the FSM): forget the per-run counters/tape of a previous run on the same ports."""
    for k in ("_cons_seen", "_cons_live", "_cons_replay"):
        p.__dict__.pop(k, None)


def _role_dict(r):
    import json
    d = {"status": r.status, "line": r.line, "extras": r.extras, "artifacts": list(r.artifacts or ()),
         "session_id": r.session_id, "denials": list(r.denials or ()), "violations": list(r.violations or ()),
         "run_dir": r.run_dir, "notes": list(r.notes or ())}
    try:
        json.dumps(d)
    except (TypeError, ValueError):
        return None
    return d


def _role_from(d):
    from guildcore.roles.runner import RoleResult
    return RoleResult(d.get("status"), d.get("line"), d.get("extras"), d.get("artifacts") or (), d.get("session_id"),
                      0.0, d.get("denials") or (), d.get("violations") or (), None, d.get("run_dir"),
                      d.get("notes") or ())


def _sig(call):
    return [call.role, call.task, call.step, int(getattr(call, "attempt", 1) or 1)]


def _tapes(p):
    j = getattr(p, "journal", None)
    if j is not None:
        return [e for e in j.entries if e.get("kind") == "event" and e.get("what") == "conservative-tape"]
    return _MEM.get((p.root, int(p.issue)), [])


def _save_tape(p, key, stage, d):
    live = p.__dict__.get("_cons_live")
    rec = {"what": "conservative-tape", "key": key, "stage": stage, "roles": live, "decision": d.as_dict()}
    try:
        import json
        json.dumps(rec)
    except (TypeError, ValueError):
        rec["roles"], rec["decision"] = None, None
    j = getattr(p, "journal", None)
    if j is not None:
        j.append("event", **rec)
    else:
        _MEM.setdefault((p.root, int(p.issue)), []).append(rec)


def _tape_for(p, key):
    for t in reversed(_tapes(p)):
        if t.get("key") == key:
            return t
    return None


def _replay(p, stage):
    """The tape this stage run replays: the latest tape of `stage` whose question is answered and not yet applied."""
    if "_cons_replay" in p.__dict__:
        return p.__dict__["_cons_replay"]
    rp = None
    if any_active(p):
        for t in reversed(_tapes(p)):
            if t.get("stage") != stage or t.get("roles") is None:
                continue
            ans, _res, applied = _answer(p, t.get("key"))
            if ans is not None and not applied:
                rp = {"roles": list(t.get("roles") or []), "at": 0}
            break
    p.__dict__["_cons_replay"] = rp
    return rp


def role(p, call, raw):
    """`Ports.run_role` (K5r6-M1): the role calls a stage made before it asked are replayed — not run again — when the
    stage runs after the person's answer; every call is taped for a question this run may raise."""
    stage = getattr(call, "stage", None)
    if stage not in REPLAY_STAGES or not any_active(p):
        return raw(call)
    live = p.__dict__.setdefault("_cons_live", [])
    rp = _replay(p, stage)
    if rp is not None and rp["at"] < len(rp["roles"]) and rp["roles"][rp["at"]].get("sig") == _sig(call) \
            and rp["roles"][rp["at"]].get("result") is not None:
        ent = rp["roles"][rp["at"]]
        rp["at"] += 1
        live.append(ent)
        if p.journal is not None:
            p.journal.append("event", what="conservative-replay", role=call.role, step=call.step)
        return _role_from(ent["result"])
    if rp is not None:                                   # the run went another way: live from here on
        p.__dict__["_cons_replay"] = None
    r = raw(call)
    live.append({"sig": _sig(call), "result": _role_dict(r)})
    return r


def gate(p, spec, raw):
    """The judge's Decision through the conservative path (see the module doc). `raw` = the judge port."""
    g = getattr(spec, "group", None)
    if g not in GATED or str(getattr(spec, "point", "") or "").endswith("-SHADOW"):
        return raw(spec)
    if not any_active(p) or not active(p, g):
        return raw(spec)
    from guildcore.judges.runner import Decision
    from workflows.dev import judging as JG
    key = point_key(p, spec)
    ans, res, applied = _answer(p, key)
    opts = options_of(spec)
    if ans is not None and (ans == "stop" or (opts and ans in opts)):
        # K5r6-M1: the answer of this decision point applies BEFORE anything is judged again — the judge's decision
        # taped when the question was asked (no new judge call), else (no tape: another clone) the judge's now
        t = _tape_for(p, key)
        d = Decision.from_dict(t["decision"]) if t and t.get("decision") else raw(spec)
        if not applied:
            from workflows.dev.stages import base as B
            B.mark_applied(p, spec.stage or "-", res)
            p.__dict__["_cons_replay"] = None
        if ans == "stop":
            raise Hold("group.%s.conservative: a person answered stop (%s)" % (g, res.id))
        f = dict(d.fields or {})
        f[spec.choice_key] = ans
        return Decision(ans, f, "human", d.digest, unsure=False, coerced=True, coerced_by="conservative",
                        raw_choice=d.choice, cost=0.0, cached=True, model=d.model)
    d = raw(spec)
    if d is None:
        return d
    safe = JG.UNSURE.get(g)
    if d.choice == safe or d.choice is None:
        return d
    if not opts or d.choice not in opts:
        return d
    _save_tape(p, key, spec.stage, d)
    p.__dict__.pop("_cons_live", None)
    p.__dict__.pop("_cons_replay", None)
    p.__dict__.pop("_cons_seen", None)
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
