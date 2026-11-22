"""workflows.dev.stages.loopback — the shared loop-back procedure (H§B steps 1–7, C §2.L).

    run(p, from_, reason, signature)     unattended: cap (0.102.11: this source's active ≥ 2 or all
                                         active ≥ 3) → pause asking reset / stop; stagnation (this
                                         signature ⊆ the latest active same-`from` block's) →
                                         pause + `stagnation` capture; else timestamp → append
                                         the block (verified) → move the label → LOOPBACK
    run(…, decided_human=True)           the attended answer path: steps 1, 4–7 (no guards),
                                         `decided: human` (+ `override: human` when the
                                         recomputed readings say cap or stagnant)
    readings(…)                          steps 1–3 as readings only (attended asking first)
    interrupted(comments, stage_label)   test/qa Step 0: block appended, label never moved
    finish_interrupted(p, …)             steps 6–7 only

Block-first-label-second is load-bearing (interrupted-loop-back recovery). The signature is
never empty (C-F-7): test passes failing names + uncovered AC ids (a red run without names
signs `suite:red`, a ceiling kill `timeout:<last running>`), qa passes defect ids — so the
STAG-REASON judgment is reached only by a `from: leader` caller with an empty set (K4).
"""

from guildcore.adapters import git as G
from guildcore.records import audit as AU
from guildcore.records import loopback as LB
from guildcore.records import markers
from workflows.dev.stages.base import NEEDS_HUMAN, StageResult, fail, pause, records


def _record(p, comments=None):
    return LB.from_comments(comments if comments is not None else records(p))


def _sig(signature):
    if isinstance(signature, str):
        items = LB.signature_set(signature)
    else:
        items = set(x.strip() for x in signature if x and x.strip())
    return ",".join(sorted(items))


def readings(p, from_, signature, comments=None):
    rec = _record(p, comments)
    return _readings(rec, from_, _sig(signature))


def _readings(rec, from_, sig):
    """0.102.11: `active` / `cap` = this source's active loop-backs and its cap; `total` / `total_cap` = all of them and
    the ceiling; `cap_reached` = either is full."""
    act = len(rec.active()) if rec else 0
    mine = rec.active_from(from_) if rec else 0
    return {"active": mine, "cap": LB.CAP, "total": act, "total_cap": LB.TOTAL_CAP,
            "cap_reached": bool(rec and rec.cap_reached(from_)),
            "stagnant_n": rec.stagnant_with(sig, from_) if rec else None}


def ask_suffix(r):
    s = ""
    if r["cap_reached"]:
        s += " — cap reached; yes overrides it"
    if r["stagnant_n"] is not None:
        s += " — same failure as loop-back %d; yes tries again anyway" % r["stagnant_n"]
    return s


def ask_line(prefix, r):
    """`<prefix>; loop back to execute? (loop-backs so far: <active>/<cap>)[suffixes]` — 0.102.11: this source's count
    and cap (the total ceiling shows as `cap reached`)."""
    return "%s; loop back to execute? (loop-backs so far: %d/%d)%s" % (prefix, r["active"], r["cap"], ask_suffix(r))


def current_branch(p):
    if p.branch:
        return p.branch
    out = G.run(p.root, "rev-parse", "--abbrev-ref", "HEAD", check=False).decode().strip()
    return out or "HEAD"


def run(p, stage, from_, reason, signature, decided_human=False, current_label=None,
        capture_role=None, head=None):
    """The procedure. `stage` = the stage running it (test|qa); `current_label` = the stage
    label the Issue carries now (defaults to guild:<stage>)."""
    inj = (getattr(p, "inject", None) or {}).get("loopback")
    if inj:                                         # replay only (§10.2-2 injection list)
        reason, signature = inj.get("reason") or reason, inj.get("signature") or signature
    sig = _sig(signature)
    if not sig:
        raise ValueError("a loop-back signature is never empty (C-F-7)")
    label = current_label or ("guild:" + stage)
    rec = _record(p)                                                       # step 1
    r = _readings(rec, from_, sig)
    if not decided_human:
        if r["cap_reached"]:                                               # step 2
            return cap_stop(p, stage, from_, reason, sig, r)
        if r["stagnant_n"] is not None:                                    # step 3
            prev = [b for b in rec.active() if LB.NUMBERED_RE.match(b.heading.rstrip("\r")) and
                    int(LB.NUMBERED_RE.match(b.heading.rstrip("\r")).group(1)) == r["stagnant_n"]]
            prev_sig = prev[0].get("signature") if prev else ""
            p.capture("stagnation", stage, capture_role or ("tester" if stage == "test" else "qa"),
                      "stagnant loop-back — %s" % reason, "%s == %s" % (prev_sig, sig), None, True)
            line = "stagnant loop-back — %s" % reason
            return pause(p, stage, "defect", line, line)
    override = decided_human and (r["cap_reached"] or r["stagnant_n"] is not None)
    at = p.now()                                                           # step 4
    n = rec.next_n() if rec else 1
    block = LB.render_block(n, from_, at, current_branch(p), reason, sig,
                            decided="human" if decided_human else None,
                            override="human" if override else None, head=head)
    from guildcore.adapters.gh import GhWriteError
    try:                                                                   # step 5
        p.writer.append_block(
            p.issue, LB.NAME, insert=lambda body: LB.append(body, block),
            present=lambda body: block in body or _same_pending(body, from_, reason, sig, decided_human),
            new_comment=lambda: LB.render_new_record(block),
            count=lambda body: len(LB.LoopbackRecord.parse(body).numbered()))
    except GhWriteError as e:
        if e.kind == "auth":
            raise
        return fail(p, stage, "loop-back record not written", "defect")
    return move_label(p, label, decided_human)                             # steps 6–7


OUTPUTS = {"test": "test:output", "qa": "qa:output"}


def cap_stop(p, stage, from_, reason, sig, r):
    """0.102.11 (lead decision 6): the cap-reached stop asks `reset` (one more round: a `### loopback-reset by: human`
    block, then this loop-back — both on the record) or `stop`. The output carries the loop-back lines the answer
    applies (`apply_answer`)."""
    from guildcore import ask as ASK
    from guildcore.records import outputs as OUT
    from workflows.dev.stages import render as R
    line = "loop-back cap reached — %s" % reason
    name = OUTPUTS.get(stage)
    cur = OUT.find(records(p), name) if name else None
    if cur is None:
        return pause(p, stage, "defect", line, "loop-back cap reached")
    p.writer.upsert_comment(p.issue, name, R.add_loopback_lines(cur.body, name, reason, sig))
    q = ASK.Question("loopback", "%s (%s %d/%d, all %d/%d) — reset the count and loop back once more?" % (
        line, from_, r["active"], r["cap"], r["total"], r["total_cap"]),
        [{"token": "reset", "label": "reset — one more round (recorded)"}, {"token": "stop", "label": "stop"}],
        point="loopback-cap:%s" % stage)
    return pause(p, stage, "defect", line, "loop-back cap reached", question=q)


def reset(p):
    """The `reset` answer: a `### loopback-reset` block (by: human) on the loop-back record."""
    blk = LB.render_reset(p.now(), by="human")
    p.writer.append_block(p.issue, LB.NAME, insert=lambda body: LB.append(body, blk),
                          present=lambda body: blk in body, new_comment=lambda: LB.render_new_record(blk))


def _same_pending(body, from_, reason, sig, decided_human):
    """K2-m5: a resumed write must not append a twin — the latest active block, unconsumed, with
    the same from/reason/signature/decided IS this loop-back (its `at:` differs)."""
    try:
        b = LB.LoopbackRecord.parse(body).latest_active()
    except ValueError:
        return False
    if b is None or b.has("consumed"):
        return False
    return (b.get("from") == from_ and markers.unescape(b.get("reason") or "") == " ".join(reason.split()) and
            LB.signature_set(b.get("signature") or "") == LB.signature_set(sig) and
            (b.get("decided") == "human") == bool(decided_human))


def move_label(p, label, decided_human):
    labels = [x.get("name") if isinstance(x, dict) else x for x in p.gh.issue(p.issue).get("labels") or []]
    remove = [label] if label in labels else []
    if decided_human and NEEDS_HUMAN in labels:
        remove.append(NEEDS_HUMAN)
    p.writer.labels_apply(p.issue, add=["guild:execute"], remove=remove)
    return StageResult(StageResult.LOOPBACK)


def interrupted(comments, stage_label, labels):
    """H§B *Interrupted loop-back*: the latest active block has no `consumed:`, NO audit
    `invocation:` is ≥ its `at:`, and the label is still `stage_label`. Returns the block."""
    if stage_label not in labels:
        return None
    rec = LB.from_comments(comments)
    if rec is None or not rec.not_yet_handled():
        return None
    blk = rec.latest_active()
    at = blk.get("at") or ""
    num = LB.NUMBERED_RE.match(markers.clean(blk.heading)).group(1)
    for ar in AU.all_from_comments(comments):
        # K3 (K2r1-m7): the number an execute consumed outranks the time comparison
        if any(b.loopback == num for b in ar.blocks):
            return None
    for ar in AU.all_from_comments(comments):
        for inv in ar.invocations():
            if inv and inv >= at:
                return None
    return blk


def finish_interrupted(p, stage, blk):
    return move_label(p, "guild:" + stage, (blk.get("decided") or "") == "human")
