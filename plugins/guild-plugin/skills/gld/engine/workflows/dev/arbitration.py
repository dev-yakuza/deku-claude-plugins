"""workflows.dev.arbitration — the judgments analyze and design share (§3.2 SJ-STAKES, §3.3 DE-ARB).

* `stakes(p, stage, dim_or_q, question, options, about_to_take, body, areas, irreversible)` — SJ-STAKES
  is asked PER QUESTION and never sees the reasons of the judgment that raised it (R2J-N7 — no
  self-justification). Code: a choice touching an irreversible path is never `low` (→ `medium`);
  `unsure` / no reason → `high` (judging.coerce_stakes). Attended never calls it (§3.2).
* `blocked(p, stage, role, res, ctx, reinvoked, rerun)` — DE-ARB for a BLOCKED / NEEDS_CONTEXT role
  (or a hand-over that still fails after its repair). ONE re-invocation per role per stage
  (`reinvoked`, §4.2 "역할 맥락 재호출 1"); `decide` unattended only after STAKES says low/medium;
  `escalate` / `pause` / `unsure` → a person (attended `ask design-block`, unattended
  `ambiguity:` pause). The G-ESCALATE rung between SJ and the human is not used here: an
  `executor_conflict` / `cross_stage` at analyze/design always ends with a person (more
  conservative than the ladder — K4 note).
Returns ("retry", RoleResult) | ("decided", assumption) | StageResult.
"""

from guildcore import ask as ASK
from workflows.dev import judging as JG
from workflows.dev.stages import base as B

LEVELS = ("low", "medium", "high")


def stakes(p, stage, refs, question, options, about_to_take, body, areas, irreversible_paths, step,
           record_question=None, defer=False):
    brief = [("question", question),
             ("options", "\n".join("- %s" % o for o in options) or "-"),
             ("about_to_take", about_to_take or "-"),
             ("issue", body or ""),
             ("areas", "\n".join("- %s" % a for a in areas) or "-"),
             ("irreversible", "\n".join("- %s" % x for x in irreversible_paths) or "none")]
    d = p.judge(JG.spec(p, "STAKES", brief, stage, step))
    f, _by = JG.coerce_stakes(dict(d.fields, level=d.choice))       # re-applied: never trust the transport
    level = f.get("level") if f.get("level") in LEVELS else "high"
    coerced = None if level == d.choice else "no local/reversible reason → high"
    if irreversible_paths and level == "low":
        level, coerced = "medium", "irreversible path → never low (§3.2)"
    extra = {}
    rq = record_question if record_question is not None else question
    if rq:
        extra["question"] = rq[:300]
    if irreversible_paths:
        extra["irreversible"] = "true"     # K5r5-M3: §9.5 rule 2 — a confirmed wrong here is the irreversible class
    reason = (d.fields.get("local_reversible_reason") or coerced or "")[:300]

    def record(withhold=False):
        """K5r6-m7: `withhold` — a blind question follows in this stage: the judge's free `reason` is not on GitHub
        before the answer (sealed: `reason_sha`, journaled; revealed with the answer — `withhold_for_next`)."""
        ex = dict(extra)
        r = reason
        if withhold:
            from workflows.dev import predict as PF
            # K6 r3 M2: `irreversible` is computed from the CHOSEN reading's areas — when the readings differ in
            # touching an irreversible path it IS the recommendation. Sealed like the reason (always — its absence
            # would say "false"); the value is journaled and revealed on GitHub by the run after the person's answer
            # (`reveal_sealed_stakes`); §9.5 reads the revealed value, and an unrevealed seal as irreversible
            # (`grade.block_irreversible` — the stricter class, fail-safe)
            ex.pop("irreversible", None)
            ex["irreversible_sha"] = PF.sealed(p, "true" if irreversible_paths else "false", IRREVERSIBLE_FIELD)
        if withhold and reason:
            from workflows.dev import predict as PF
            ex["reason_sha"] = PF.sealed(p, reason, "STAKES.reason")
            r = "(withheld until the person's blind answer — predict-first)"
            withhold_for_next(p, "STAKES reason: %s" % reason)
        return B.record_judgment(p, stage, "STAKES", refs, d, choice=level, reason=r, extra=ex or None)
    if defer:
        return level, record
    record()
    return level


IRREVERSIBLE_FIELD = "STAKES.irreversible"
REVEAL = "reveal"


def reveal_sealed_stakes(p, stage, comments):
    """K6 r3 M2: after a person's answer, every STAKES block of `stage` whose `irreversible` was sealed and is not yet
    revealed gets a reveal block (`point: reveal`, `refs` = the STAKES block, `irreversible` + `nonce`, checked against
    the seal by `grade.block_irreversible`) — from this clone's journal; a seal it cannot open stays sealed (§9.5 then
    reads it as irreversible). Returns the ids written."""
    from guildcore import ask as ASK
    from guildcore.decisions import DecisionLog
    log = DecisionLog.load(comments)
    done = set(b.get("refs") for b in log.blocks if b.get("point") == REVEAL)
    out = []
    for b in log.blocks:
        if b.get("point") != "STAKES" or b.get("stage") != stage or not b.get("irreversible_sha") or b.id in done:
            continue
        v, n = ASK.seal_value(getattr(p, "journal", None), b.get("irreversible_sha"), IRREVERSIBLE_FIELD)
        if v is None:
            continue
        out.append(B.record_code(p, stage, REVEAL, "irreversible", refs=b.id,
                                 extra={"field": "irreversible", "irreversible": v, "nonce": n}))
    return out


def withhold_for_next(p, text):
    """K5r6-m7: a text the next blind question of this run withholds with its own (revealed after the answer)."""
    p.__dict__.setdefault("_withheld_next", []).append(text)


def _ask_or_pause(p, stage, line, options, recommended=None, kind="design-block"):
    toks = []
    for o in options or []:
        t = "".join(ch for ch in str(o).lower().replace(" ", "-") if ch.isalnum() or ch in ":_-")[:30]
        if t and t not in toks and t != "stop":
            toks.append(t)
    opts = [{"token": t, "label": t} for t in toks[:4]] + [{"token": "stop", "label": "stop"}]
    rec = recommended if recommended in [o["token"] for o in opts] else None
    q = ASK.Question(kind, line, opts, recommended=rec, recommended_by="judge:sonnet" if rec else None)
    return B.ask(p, stage, q, line, {"cause_kind": "ambiguity", "line": line, "token_cause": "ambiguity: %s" % line})


def blocked(p, stage, role, res, ctx_parts, reinvoked, rerun, body="", areas=(), irreversible_paths=(), step="E2.1"):
    line = B.one_line(res.line or res.status, 240)
    brief = [("role", "%s returned %s" % (role, res.status)), ("line", line)] + list(ctx_parts)
    d = p.judge(JG.spec(p, "DE-ARB", brief, stage, step))
    act = d.choice
    B.record_judgment(p, stage, "DE-ARB", "J-DE-03", d, choice=act,
                      reason=(d.fields.get("addendum") or d.fields.get("assumption") or d.fields.get("cause") or "")[:300],
                      extra={"role": role})
    if act == "reinvoke" and (d.fields.get("role") or role) == role and role not in reinvoked:
        reinvoked.add(role)
        return ("retry", rerun(d.fields.get("addendum") or ""))
    if act == "decide":
        assumption = d.fields.get("assumption") or ""
        if p.unattended:
            level = stakes(p, stage, "J-DE-03", "%s: %s" % (role, line), [], assumption, body, list(areas),
                           list(irreversible_paths), step)
            if level == "high":
                why = "설계 막힘(%s) — 가정으로 넘기기엔 stakes high: %s" % (role, line)
                return B.pause(p, stage, "ambiguity", why, "ambiguity: %s" % why)
        return ("decided", assumption)
    why = "설계 막힘(%s): %s" % (role, line)
    if act == "escalate":
        why = "%s — %s" % (why, d.fields.get("question") or d.fields.get("reason"))
    return _ask_or_pause(p, stage, B.one_line(why, 280), d.fields.get("options") or [])
