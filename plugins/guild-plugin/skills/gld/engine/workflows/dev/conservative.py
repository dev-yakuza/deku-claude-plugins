"""workflows.dev.conservative — THE conservative path of the §9.5 count rule (K5r5-M3, design §9.5 rule 2, §10.5).

`group.<g>.conservative` (an `auto` valve the count rule sets, or a person's) means "that group's decisions go to a
person (ask / pause)". One gate does it for every L0/SJ judgment, whatever stage asked for it:

    Ports.judge(spec) → the judge's Decision → gate(p, spec, d)

* not a gated group, a shadow (`HANDOFF-SHADOW`), a wording-only re-ask (`QA:relint`, K5r8-M1), the valve off, or
  the judge already took the group's conservative default (§3.1 `judging.UNSURE` — STAKES high, QA block, TEST gap,
  DE-ARB pause …) → the Decision as it is;
* a person already answered this DECISION POINT's question (`refs: conservative:<G>:#<N>:<stage>:<step>:L<loop>` —
  K5r6-M1: the point, never the judge's input digest) → that answer applies FIRST (the judge's taped decision, no new
  judge call): a Decision carrying the person's choice (`by: human`, `coerced_by: conservative`, `raw_choice` = the
  judge's; K5r9-M1/M2: the choice run through the group's coercions — `judging.apply_choice` — so the stage's
  outcome is exactly the judge's-choosing-it outcome) — the stage goes on with it, and a `point: applied` block records
  the application once its effect is written (`flush`, K5r9-M2); `stop` → the run holds
  there (`Hold`). K5r7-M1: an answer is CONSUMED by that application — the point re-entered later (a rerun, a
  `/gld rollback`, the resume after the pause the answer led to = §2.5 rule 3) is a new point `<key>:a<k>`, judged and
  asked again; the loop generation `L` only grows (numbered blocks + resets). Only the same stage run, replayed after a
  later question, reuses an applied answer (the tape's `used`) — only while the replay matches (K5r8-M2);
* otherwise `Ask` is raised: the FSM turns it into an attended ask / unattended pause at that stage (`surface`) —
  predict-first (the judge's choice is the sealed recommendation; `raised_by: confirm`, so a different blind answer
  is a §9.5 wrong CANDIDATE — user decision 2026-11-19). The role results the stage got before asking are taped
  (journal) and REPLAYED when the stage runs after the answer (analyze/design/test/qa — no LLM role runs again); the
  execute→test hand-over question is consumed at the test stage's entry (`answered_unapplied`).

K6 (items 33/40) + review-k6-r1: an answer belongs to the stage run that asked. A SAFE answer (`safe_answers`: `stop`,
the group's conservative choice) applies to any run — never re-judged, retired or re-asked. Another answer, reached
by a run that is not the asking one (local tape: replay + brief; another clone: the role-input signatures only), is
judged again and applies when the judge now picks the person's option or the one asked about; otherwise it is
retired (`stale`). K6 r2 M4: on a clone without the asking run's tape the judge is called anyway — that judgment
decides the same way even when the role inputs match (the brief carries what no role input does). A question at a point that already had an answer (`:a<k>`) is never a counted blind judgment
(`after_reveal`). The identity hashes normalise volatile tokens (`normalise`).

EX-ARB is not gated here: its conservative side is the first-sprint coercion (`firstsprint.no_dismiss` →
`coerced_by: conservative`, BLOCKER/MAJOR dismiss → accept). KICKOFF: the interpretation is confirmed with a person
(`analyze` — attended `firstsprint.confirm_interpretation`, unattended a pause; asked openly since K6 r4 — STAKES' gate
question too: `predict.OPEN_GROUPS`). The §10.2-6 unverified groups
(K6 replay output) join through `active` — 0.102.5 (user decision 2026-11-22): a group that is on this path ONLY for
being unverified does not ask (`posthoc`): the judge's decision runs, its block carries `post_hoc` and becomes a
grading-sheet row; a confirmed wrong there sets the valve, and from then on this gate asks as above. Irreversible (§3.2)
and security decisions of an unverified group still ask.
"""

from guildcore import ask as ASK

STALE = "stale"                 # K6 (item 40): the point of the block that retires an answer its run no longer matches
# K6 item 27: the gated groups are DERIVED from the §9.5 group table (`valves.GROUPS`) — every group there is gated
# here unless it has its own conservative side, named with the reason (a new §9.5 group is gated by default, and the
# K5 r9/r10/r11 tables then fail until it has a scenario, its shapes and its expectations)
NOT_GATED = {
    "KICKOFF": "analyze confirms the interpretation with a person, openly (firstsprint.confirm_interpretation)",
    "EX-ARB-dismiss": "BLOCKER/MAJOR dismiss is coerced to accept (firstsprint.no_dismiss)",
    "EX-ARB-accept": "accept is the conservative side of EX-ARB itself",
    "ESCALATE": "no G-ESCALATE judge is wired: every unknown state pauses for a person (k6-notes item 14)",
}


def _gated():
    from guildcore import valves as VALVES
    return tuple(g for g in VALVES.GROUPS if g not in NOT_GATED)


GATED = _gated()
KIND = "group-conservative"
NOT_OPTIONS = ("unsure",)


def nonconservative_options(group):
    """The options of `group` that the gate asks about (its schema's enum without `unsure` and without the group's
    conservative choice `judging.UNSURE`) — or None (no schema)."""
    from workflows.dev import judging as JG
    try:
        prop = ((JG.schema(group) or {}).get("properties") or {}).get(JG.CHOICE.get(group, "verdict")) or {}
    except (IOError, OSError, ValueError):
        return None
    safe = JG.UNSURE.get(group)
    return tuple(x for x in (prop.get("enum") or []) if x not in NOT_OPTIONS and x != safe)


def _inherent():
    out = {}
    for g in GATED:
        nc = nonconservative_options(g) or ()
        if len(nc) == 1:
            out[g] = nc[0]
    return out


# K6 r2 M1: a gated group with exactly ONE non-conservative option (derived from the option tables — INTEGRATE clean,
# TEST all_effective, QA pass, AN-PO record, VIS-ENV regression, EX-DWC loop_back) — its gate asks only when the
# judge chose that option, so the question's EXISTENCE is the recommendation (`predict.INHERENT`'s close-decided case).
# Its answer is never a counted blind judgment (neither an `ok` nor a wrong candidate); the group is released by the
# person's grading-sheet verdicts on those decisions instead (`unverified.SHEET_RELEASED`, `grade` makes the rows).
INHERENT = _inherent()


def inherent(group):
    """The reason `group`'s gate question is inherent (its existence states the recommendation), or None."""
    opt = INHERENT.get(group)
    return ("the gate asks only when the judge chose %s (the group's one non-conservative option)" % opt) if opt \
        else None


class Ask(BaseException):
    """Raised through the stage (BaseException: a stage's own `except Exception` fallback must not swallow it) to the
    FSM, which asks / pauses with `question` at the running stage."""

    def __init__(self, question, line):
        BaseException.__init__(self, line)
        self.question, self.line = question, line


class NeedGrounds(BaseException):
    """K6 (item 39 iv): a person gave the same answer twice and its option still has no grounds — the run stops with
    a pause that asks for the grounds (the answer is consumed; the next entry judges again)."""

    def __init__(self, line):
        BaseException.__init__(self, line)
        self.line = line


class Hold(BaseException):
    """The person answered `stop` to a conservative question — the run holds (nothing more is decided)."""

    def __init__(self, line):
        BaseException.__init__(self, line)
        self.line = line


def active(p, group):
    from workflows.dev import predict as PF
    return bool(group) and PF.conservative(p, group)


def any_active(p):
    """K5r7-m6: the same predicate as `active` over every gated group — a source the K6 `conservative.active` list
    adds to `predict.conservative` reaches the role tape and the hand-over check too (not the valves only)."""
    return any(active(p, g) for g in GATED)


def options_of(spec):
    """The group's choices (its schema's enum for the choice key, without `unsure`) — or None (free-form: not gated)."""
    prop = ((spec.schema or {}).get("properties") or {}).get(spec.choice_key) or {}
    enum = [x for x in (prop.get("enum") or []) if x not in NOT_OPTIONS]
    return enum or None


# execute/children: roles change the tree — their own re-entry. The developer runs only in execute, so it is never
# replayed from a tape (review-0102-5 m1: 0.102.5's `NEVER_REPLAYED` guard could never fire — removed; a test pins
# that no replayed stage calls the developer)
REPLAY_STAGES = ("analyze", "design", "test", "qa")
_MEM = {}                                               # tapes when a port has no journal (tests, the procedure replay)


def _loop_index(p):
    """The loop-back generation of the Issue: a decision point re-reached after a loop-back is a NEW decision point
    (a new question; K5r6-M1). K5r7-M1: MONOTONIC — every numbered heading plus every `### loopback-reset` (a reset
    never brings back an earlier generation's key; the active-block count would)."""
    from guildcore.records import loopback as LB
    from guildcore.records import markers
    from workflows.dev.stages import base as B
    try:
        c = markers.find(B.records(p), LB.NAME)
        if c is None:
            return 0
        rec = LB.LoopbackRecord.parse(markers.body_of(c))
        resets = [b for b in rec.blocks if markers.clean(b.heading) == "### loopback-reset"]
        return len(rec.numbered()) + len(resets)
    except Exception:                                    # noqa: BLE001 — an unreadable record is generation 0
        return 0


def _epoch_key(p, key):
    """K5r7-M1: an answer is CONSUMED once — the decision point re-entered after its answer was applied (a rerun, a
    `/gld rollback`, a resume after the pause the answer led to: §2.5 rule 3 = judge again) is a new point
    `<key>:a<k>` (k = the answers of this point already applied). A crash right after `applied` asks again (the
    conservative side); the same stage run re-entered after a LATER question reuses it through the tape (`used`)."""
    k, cur = 0, key
    while True:
        ans, _res, applied = _answer(p, cur)
        if ans is None or not applied:
            return cur
        k += 1
        cur = "%s:a%d" % (key, k)


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


def _point(p, spec, bump=True):
    """(point, key): the decision point (per stage run) and the key its question goes by now (`_epoch_key`)."""
    pt = point_key(p, spec, bump)
    used = p.__dict__.get("_cons_used_replay") or {}
    return pt, (used.get(pt) or _epoch_key(p, pt))


def key_of(group, d):                                   # pre-r6 keys (input digest) — read by nothing new
    return "conservative:%s:%s" % (group, str(getattr(d, "digest", "") or "")[:12])


def _answer(p, key):
    """(choice, resolution block, applied?) of a person's answer to the question with `refs: key` — or
    (None, None, False). Read by decision point, whatever the Issue's label is now."""
    from guildcore.decisions import DecisionLog
    from workflows.dev.stages import base as B
    log = DecisionLog.load(B.records(p))
    # K6 (item 40): a `stale` answer (its stage run did not reach the gate the same way) is consumed like an applied one
    applied = set(b.get("refs") for b in log.blocks if b.get("point") in ("applied", STALE))
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
    ans, res, applied = _answer(p, _epoch_key(p, point_key(p, s, bump=False)))
    return ans is not None and not applied


# -- the replay tape: a stage that asked is run again after the answer WITHOUT re-running its LLM roles -----------------
def begin(p):
    """A stage run starts (the FSM): forget the per-run counters/tape of a previous run on the same ports."""
    for k in ("_cons_seen", "_cons_live", "_cons_replay", "_cons_used", "_cons_used_replay", "_cons_defer",
              "_cons_diverged", "_cons_guidance", "_cons_remote"):
        p.__dict__.pop(k, None)


def flush(p):
    """K5r7-m4 / K5r9-M2: the `applied` marks the gate deferred (every answered point — its effect is written by the
    stage, or by the FSM after the gate for the execute→test hand-over) are written once that effect is (the caller:
    the result is not FAIL, a hold, or the stage's next question). A crash or a failed write in between leaves the
    answer unapplied: the same point applies it again on the next run (never a consumed answer with no effect)."""
    from workflows.dev.stages import base as B
    for ent in p.__dict__.pop("_cons_defer", None) or []:
        stage, res = ent[0], ent[1]
        B.mark_applied(p, stage, res, extra=ent[2] if len(ent) > 2 else None)


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


_ANSWER_COMMENT = None


def _strip_answers(v):
    """The person's answer line is not a new input (it is what the replay waits for): a comment that is only
    `guild-answer:` lines is dropped from the role inputs before they are hashed; any other text in it is kept."""
    import re
    global _ANSWER_COMMENT
    if _ANSWER_COMMENT is None:
        _ANSWER_COMMENT = (re.compile(r"(?m)^comment \S+ by [^\n]*:\n(?:[ \t]*guild-answer:[^\n]*(?:\n|$))+\n*"),
                           re.compile(r"(?m)^[ \t]*guild-answer:[^\n]*$"))
    if isinstance(v, str):
        return _ANSWER_COMMENT[1].sub("", _ANSWER_COMMENT[0].sub("", v)).strip()
    if isinstance(v, dict):
        return dict((k, _strip_answers(x)) for k, x in v.items())
    if isinstance(v, (list, tuple)):
        return [_strip_answers(x) for x in v]
    return v


# K6 r1 m2: the run-identity hashes (role inputs, the judge's brief) read the text with its VOLATILE tokens normalised —
# a suite's raw output carries elapsed times, clocks and temp paths that differ on every run of the same code (the TEST
# stage was "another run" every time: every TEST answer cost a judge call and could be re-asked). Only the identity
# hash sees this form; the role and the judge get the text unchanged.
_VOLATILE = None


def _volatile():
    import re
    global _VOLATILE
    if _VOLATILE is None:
        _VOLATILE = (
            (re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:[.,]\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?"), "<ts>"),
            (re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d+)?\b"), "<clock>"),
            (re.compile(r"\b\d+(?:[.,]\d+)?\s?(?:ms|µs|us|ns|s|sec|secs|seconds?|min|minutes?)\b", re.I), "<dur>"),
            (re.compile(r"(?:/private)?/(?:tmp|var/folders)/[^\s'\":]*"), "<tmp>"),
            (re.compile(r"\b(?:pid|PID)[ =:]?\d+\b"), "<pid>"),
        )
    return _VOLATILE


def normalise(v):
    """The identity form of a role input / brief text (K6 r1 m2): volatile tokens → placeholders."""
    if isinstance(v, str):
        for rx, rep in _volatile():
            v = rx.sub(rep, v)
        return v
    if isinstance(v, dict):
        return dict((k, normalise(x)) for k, x in v.items())
    if isinstance(v, (list, tuple)):
        return [normalise(x) for x in v]
    return v


def _salt(call):
    s = getattr(call, "replay_salt", None)
    if callable(s):
        try:
            s = s()
        except Exception:                                                # noqa: BLE001 — unknown: no salt
            s = None
    return s


def _sig(call):
    """K5r7-m3: the role call's INPUTS are part of it — an Issue edit / note / push between the question and the answer
    changes them, and the run goes live from that call (never a replayed result for other inputs)."""
    import hashlib
    import json
    try:
        parts = [getattr(call, "inputs", None) or {}, getattr(call, "addendum", None)]
        salt = _salt(call)
        if salt:                                                         # K5r8-m2 (qa: HEAD) — absent: as before
            parts.append({"salt": str(salt)})
        ins = json.dumps(normalise(_strip_answers(parts)), sort_keys=True, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        ins = repr((getattr(call, "inputs", None), getattr(call, "addendum", None)))
    return [call.role, call.task, call.step, int(getattr(call, "attempt", 1) or 1),
            hashlib.sha256(ins.encode("utf-8", "replace")).hexdigest()[:16]]


def _tapes(p):
    j = getattr(p, "journal", None)
    if j is not None:
        return [e for e in j.entries if e.get("kind") == "event" and e.get("what") == "conservative-tape"]
    return _MEM.get((p.root, int(p.issue)), [])


def _save_tape(p, key, stage, d, brief=None):
    live = p.__dict__.get("_cons_live")
    rec = {"what": "conservative-tape", "key": key, "stage": stage, "roles": live, "decision": d.as_dict(),
           "used": dict(p.__dict__.get("_cons_used") or {}), "brief": brief}
    if getattr(d, "dual", None):                         # K6 r2 m2: the pre-question dual judgment (local only)
        rec["dual"] = {"dual": d.dual, "dual_choice": d.dual_choice, "dual_model": d.dual_model}
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
        local = False
        for t in reversed(_tapes(p)):
            if t.get("stage") != stage or t.get("roles") is None:
                continue
            local = True
            ans, _res, applied = _answer(p, t.get("key"))
            if ans is not None and not applied:
                rp = {"roles": list(t.get("roles") or []), "at": 0, "key": t.get("key")}
                # K5r7-M1: the answers this stage run had applied before that later question are the same run's —
                # reused, not consumed again (else a stage with two conservative points re-asks the first)
                p.__dict__["_cons_used_replay"] = dict(t.get("used") or {})
            break
        if not local:
            rp = _remote_replay(p, stage)
    p.__dict__["_cons_replay"] = rp
    return rp


def _h(sig):
    """K6 (item 33): one role call's identity on GitHub — a short hash of its `_sig` (role · task · step · attempt ·
    input hash). Never the inputs themselves (the block is public)."""
    import hashlib
    import json
    return hashlib.sha256(json.dumps(sig, sort_keys=True).encode("utf-8")).hexdigest()[:12]


def _run_field(live):
    """`cons_run`: the stage run up to its question, one `h[/h_after]` per role call (K6 item 33)."""
    out = []
    for e in live or []:
        sig = e.get("sig")
        if not sig:
            continue
        x = _h(sig)
        if e.get("sig_after"):
            x += "/" + _h(e["sig_after"])
        out.append(x)
    return ",".join(out)


def _strip_epoch(key):
    import re
    return re.sub(r":a[0-9]+$", "", str(key or ""))


def _remote_replay(p, stage):
    """K6 (items 33/40): no local tape of `stage` (another clone, a lost journal) — the latest pending conservative
    block of `stage` that a person answered and nothing applied yet carries the run's identity (`cons_run`) and the
    answers that run had already applied (`cons_used`). The run then goes LIVE (no role result to replay) but is the
    SAME run only while each role call's identity matches — that keeps the earlier answers (no 2ⁿ−1 re-asks) and
    lets the answered point apply; any difference = a different run (`_cons_diverged`). A block without `cons_run`
    (written before K6) → None: the pre-K6 behaviour (the answer applies to the judge's decision now)."""
    from guildcore.decisions import DecisionLog
    from workflows.dev.stages import base as B
    try:
        log = DecisionLog.load(B.records(p))
    except Exception:                                    # noqa: BLE001 — unreadable: no remote tape
        return None
    for blk in reversed(log.blocks):
        if blk.get("kind") != KIND or blk.get("status") != "pending-human" or blk.get("stage") != stage:
            continue
        ans, _res, applied = _answer(p, blk.get("refs"))
        if ans is None or applied or blk.get("cons_run") is None:
            return None
        roles = []
        for x in str(blk.get("cons_run") or "").split(","):
            if x.strip() and x.strip() != "-":
                h, _s, ha = x.strip().partition("/")
                roles.append({"h": h, "ha": ha or None})
        used = {}
        for k in str(blk.get("cons_used") or "").split(","):
            if k.strip():
                used[_strip_epoch(k.strip())] = k.strip()
        p.__dict__["_cons_used_replay"] = used
        p.__dict__["_cons_remote"] = True
        return {"roles": roles, "at": 0, "remote": True, "key": blk.get("refs")}
    return None


def _open_recommendation(p, key):
    """The recommendation a pending block shows openly (`recommended` — not blind), or None (blind / not found)."""
    from guildcore.decisions import DecisionLog
    from workflows.dev.stages import base as B
    try:
        for blk in reversed(DecisionLog.load(B.records(p)).blocks):
            if blk.get("kind") == KIND and blk.get("refs") == key and blk.get("status") == "pending-human":
                return blk.get("recommended")
    except Exception:                                    # noqa: BLE001
        return None
    return None


def _brief_h(spec):
    """K6 (item 40): the judge's brief at this gate, hashed (a person's answer line is no new input). A run that
    reaches the gate with the same role calls but another brief (rework the roles never saw: the diff, a new CI
    result, an edited comment) is not the run that asked."""
    import hashlib
    import json
    try:
        b = json.dumps(normalise(_strip_answers([list(x) for x in (getattr(spec, "brief_parts", None) or [])])),
                       sort_keys=True, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        b = repr(getattr(spec, "brief_parts", None))
    return hashlib.sha256(b.encode("utf-8", "replace")).hexdigest()[:12]


def _asked_brief(p, key):
    """The brief hash of the run that asked — from the LOCAL tape only (K6 r1 M3). Only a replayed run sees the same
    role OUTPUT the asking run saw; a run whose roles went live (another clone: `_remote_replay`) gets other wording
    from the same inputs, so its brief can never hash the same — its identity is the role-input signatures alone
    (`cons_run`, with qa's HEAD salt for rework). The block's `cons_brief` stays as a record, never compared.
    K6 r2 M4: matching signatures do not apply the answer by themselves there — the judge the run calls anyway (no
    tape to reuse) must pick the person's option or the one asked about (`gate`)."""
    if p.__dict__.get("_cons_remote"):
        return None
    t = _tape_for(p, key)
    return t.get("brief") if t else None


def _asked_choice(p, key, res):
    """The choice the person was asked about (K6 r1 M3): the taped decision, else the recommendation the resolution
    REVEALED (a blind block carries none before the answer), else an open block's `recommended`."""
    t = _tape_for(p, key)
    if t and (t.get("decision") or {}).get("choice"):
        return t["decision"]["choice"]
    if res is not None and res.get("recommended"):
        return res.get("recommended")
    return _open_recommendation(p, key)


def safe_answers(group):
    """K6 r1 M1: the answers that are safe for ANY run of the point — `stop` and the group's conservative choice
    (`judging.UNSURE`: QA block, TEST gap, STAKES high, HANDOFF upstream_gap …). The run-identity check (item 40)
    protects only a non-conservative answer from being applied to a run it was not given for; a safe answer is never
    re-judged, retired or re-asked — `stop` holds wherever it lands."""
    from workflows.dev import judging as JG
    safe = JG.UNSURE.get(group)
    return frozenset(["stop"] + ([safe] if safe else []))


def grounds_line(group, ans, final, rule):
    """K6 (item 39 i): the engine's line for a person's option a rule could not run — which fields it lacked and how
    to give them. Engine text only (after the answer)."""
    from workflows.dev import judging as JG
    need = list((JG.OPTION_FIELDS.get(group) or {}).get(ans, ()))
    what = ", ".join("`%s`" % k for k in need) or "그 선택지의 근거"
    return ("사람 `%s` — %s 없음 → `%s`(%s). 근거는 `dev note`(attended) 또는 Issue 코멘트로 남기고 "
            "`guild:needs-human` 을 지우면 다시 판단합니다" % (ans, what, final, rule))


def _applied_coerced(p, key):
    """K6 r1 m3: the answer of `key` was applied AND a rule replaced it (its `applied` block carries `coerced_to`)."""
    from guildcore.decisions import DecisionLog
    from workflows.dev.stages import base as B
    _ans, res, applied = _answer(p, key)
    if res is None or not applied:
        return False
    try:
        log = DecisionLog.load(B.records(p))
    except Exception:                                    # noqa: BLE001 — unreadable: not shown to be coerced
        return False
    return any(b.get("point") == "applied" and b.get("refs") == res.id and b.get("coerced_to") for b in log.blocks)


def source_label(p, group):
    """K6 r1 M6: why `group` takes the conservative path, as the person can act on it — the valve
    (`group.<G>.conservative`, cleared with `dev valve clear`) or the §10.2-6 unverified state (released by human
    verdicts — `dev health` shows the count; no valve to clear)."""
    from workflows.dev import predict as PF
    return PF.conservative_label(p, group)


def _previous_epoch(key):
    import re
    m = re.match(r"^(.*):a([0-9]+)$", str(key or ""))
    if not m:
        return None
    k = int(m.group(2))
    return m.group(1) if k == 1 else "%s:a%d" % (m.group(1), k - 1)


def _matched(p, spec=None, key=None):
    """K6 (item 40): did this stage run reach the gate the SAME way as the run that asked? — every taped role call
    replayed (or, remote, matched) in order, none left over, and the judge's brief the same. None = nothing to
    compare (a block and tape written before K6)."""
    if p.__dict__.get("_cons_diverged"):
        return False
    was = _asked_brief(p, key) if key else None          # None on a remote run (K6 r1 M3)
    if was and spec is not None and _brief_h(spec) != was:
        return False
    rp = p.__dict__.get("_cons_replay")
    if rp is None:
        return True if (was or p.__dict__.get("_cons_remote")) else None
    return rp["at"] == len(rp["roles"])


def role(p, call, raw):
    """`Ports.run_role` (K5r6-M1): the role calls a stage made before it asked are replayed — not run again — when the
    stage runs after the person's answer; every call is taped for a question this run may raise."""
    stage = getattr(call, "stage", None)
    if stage not in REPLAY_STAGES or not any_active(p):
        return raw(call)
    live = p.__dict__.setdefault("_cons_live", [])
    rp = _replay(p, stage)
    sig = _sig(call)
    if rp is not None and rp.get("remote"):
        # K6 (item 33): the run goes live, and stays "the same run" while each call's identity matches the block's
        want = rp["roles"][rp["at"]] if rp["at"] < len(rp["roles"]) else None
        if want is not None and _h(sig) in (want["h"], want.get("ha")):
            rp["at"] += 1
            r = raw(call)
            ent = {"sig": sig, "result": _role_dict(r)}
            after = _sig(call) if getattr(call, "replay_salt", None) is not None else sig
            if after != sig:
                ent["sig_after"] = after
            live.append(ent)
            return r
        p.__dict__["_cons_replay"] = None
        p.__dict__.pop("_cons_used_replay", None)
        p.__dict__["_cons_diverged"] = True
        rp = None
    if rp is not None and rp["at"] < len(rp["roles"]) and sig in (rp["roles"][rp["at"]].get("sig"),
                                                                  rp["roles"][rp["at"]].get("sig_after")) \
            and rp["roles"][rp["at"]].get("result") is not None:
        ent = rp["roles"][rp["at"]]
        rp["at"] += 1
        live.append(ent)
        if p.journal is not None:
            p.journal.append("event", what="conservative-replay", role=call.role, step=call.step)
        return _role_from(ent["result"])
    if rp is not None:                                   # the run went another way: live from here on
        p.__dict__["_cons_replay"] = None
        # K5r8-M2: no longer the same stage run — the answers it had applied are not reused either (a point
        # reached after the divergence is judged again under `_epoch_key`, never given an old answer)
        p.__dict__.pop("_cons_used_replay", None)
        p.__dict__["_cons_diverged"] = True             # K6 (item 40): its unapplied answer is stale, too
    r = raw(call)
    ent = {"sig": sig, "result": _role_dict(r)}
    if getattr(call, "replay_salt", None) is not None:
        # K5r8-m2: the state the role itself left (qa's own test commits move HEAD) matches as well as the state
        # it started from — only a change someone else made to the worktree (a local commit / reset) runs the role
        # live again (K5r9-m2: a remote push never reaches the worktree — the engine's push after qa fails non-ff)
        after = _sig(call)
        if after != sig:
            ent["sig_after"] = after
    live.append(ent)
    return r


def gate(p, spec, raw):
    """The judge's Decision through the conservative path (see the module doc). `raw` = the judge port."""
    g = getattr(spec, "group", None)
    pt_name = str(getattr(spec, "point", "") or "")
    # K5r8-M1: a `:relint` call re-asks the WORDING only (the verdict stays with the first decision) — no decision,
    # so never a question: a second identical pass/block question would drop a person's `block` and grade nothing
    if g not in GATED or pt_name.endswith("-SHADOW") or pt_name.endswith(":relint"):
        return raw(spec)
    if not any_active(p) or not active(p, g):
        return raw(spec)
    from guildcore.judges.runner import Decision
    from workflows.dev import judging as JG
    if spec.stage in REPLAY_STAGES:
        _replay(p, spec.stage)                           # the run's replay tape (and the answers it already used)
    pt, key = _point(p, spec)
    ans, res, applied = _answer(p, key)
    opts = options_of(spec)
    fresh = None
    same = None
    if ans is not None and not applied and ans not in safe_answers(g) and spec.stage in REPLAY_STAGES:
        same = _matched(p, spec, key)
    # K6 r2 M4: without the asking run's tape (another clone — `_remote_replay` — or a lost journal) the judge is
    # called anyway (no taped decision to reuse), and the role-input signatures cannot see what only the judge's brief
    # carries (TEST: the AC file and the cited test bodies). That judgment decides like a diverged run's: the answer
    # applies only when it picks the person's option or the one asked about. `None` (a pre-K6 block, no identity) keeps
    # the earlier behaviour
    if same is False or (same is not None and _tape_for(p, key) is None):
        # K6 (item 40, review-k5-r10 m3) as fixed by K6 r1 M1–M3: a NON-conservative answer given to a stage run this
        # one no longer is (a crash after the gate, then a rollback / rework / an Issue edit changed a role's inputs
        # or — local tape — the judge's brief). The point is judged again; the answer still applies when the judge
        # now chooses the person's option or the option the person was asked about (the same question, or the
        # person and the judge agree — never a re-ask then). Otherwise it can no longer apply: it is retired
        # (`stale`) and the new judgment goes on — asked again at `:a<k>` when still gated, and that question is
        # never a counted blind judgment (`after_reveal` — the old recommendation is revealed and the `stale` block
        # says the judge moved: the new one is inferable). `stop` and the group's conservative answer never get
        # here (`safe_answers` — safe for any run).
        fresh = raw(spec)
        was = _asked_choice(p, key, res)
        if fresh is None or fresh.choice not in (ans, was):
            from workflows.dev.stages import base as B
            B.record_code(p, spec.stage or "-", STALE, ans, refs=res.id,
                          reason="the stage run that asked is not the run that reached this gate again "
                                 "and the judge now chooses neither the person's option nor the one asked about")
            if getattr(p, "journal", None) is not None:
                p.journal.append("event", what="conservative-stale", key=key, resolution=res.id)
            key = _epoch_key(p, pt)
            ans, res, applied = _answer(p, key)
    if ans is not None and (ans == "stop" or (opts and ans in opts)):
        # K5r6-M1: the answer of this decision point applies BEFORE anything is judged again — the judge's decision
        # taped when the question was asked (no new judge call), else (no tape: another clone) the judge's now.
        # K5r7-M1: applied ONCE — the next entry of this point is a new point (`_epoch_key`), judged again
        t = _tape_for(p, key)
        d = fresh if fresh is not None else (Decision.from_dict(t["decision"]) if t and t.get("decision")
                                             else raw(spec))
        defer = None
        if not applied:
            # K5r7-m4 / K5r9-M2: `applied` is written only after the answer's effect is (the FSM's `flush`: the stage
            # ended without FAIL, held, or went on to its next question) — a crash in between leaves it unapplied
            defer = [spec.stage or "-", res, None]
            p.__dict__.setdefault("_cons_defer", []).append(defer)
            p.__dict__["_cons_replay"] = None
        p.__dict__.setdefault("_cons_used", {})[pt] = key
        if ans == "stop":
            raise Hold("group.%s.conservative: a person answered stop (%s)" % (g, res.id))
        # K5r9-M1/M2: the person's choice goes through the group's own consistency rules (`apply_choice`) — the stage
        # then sees exactly what the judge's choosing it would have given (TEST per-AC verdicts, INTEGRATE gaps)
        f, final, rule = JG.apply_choice(spec, d.fields, ans, who=str(res.id))
        out = Decision(final, f, "human", d.digest, unsure=False, coerced=True, coerced_by="conservative",
                       raw_choice=d.choice, cost=0.0, cached=True, model=d.model)
        if fresh is None and t and t.get("dual") and not applied:
            # K6 r2 m2: the dual judgment of the taped decision (made before the question) rides on the applied block
            out.dual, out.dual_choice, out.dual_model = (t["dual"].get("dual"), t["dual"].get("dual_choice"),
                                                         t["dual"].get("dual_model"))
        if rule and final != ans:
            # K5r10-m2: a rule replaced the person's choice — the log keeps both (the person's answer, the result)
            out.human_choice, out.coerced_to = ans, "%s by rule %s" % (final, rule)
            # K6 (item 39 i): after the answer (the recommendation is revealed by now) the person is told WHY their
            # option could not run and how to give its grounds — on the judgment block and the next pause's prose
            out.grounds = grounds_line(g, ans, final, rule)
            if not applied:
                p.__dict__["_cons_guidance"] = out.grounds
                defer[2] = {"coerced_to": out.coerced_to}      # K6 r1 m3: the `applied` block says it was replaced
                # K6 (item 39 iv): the same option answered at the previous entry of this point, also without its
                # grounds — the question would only come back: stop for the grounds instead (the answer is consumed).
                # K6 r1 m3: only when that previous answer was itself APPLIED and replaced by a rule (its `applied`
                # block carries `coerced_to`) — not one that ran as given, nor one retired `stale` unapplied
                prev = _previous_epoch(key)
                if prev is not None and _answer(p, prev)[0] == ans and _applied_coerced(p, prev):
                    raise NeedGrounds("%s — 같은 답이 두 번 근거 없이 들어왔습니다: 근거를 남긴 뒤 다시 실행하십시오" % out.grounds)
        # K5r9: the same stage run replayed after a later question reuses this answer (its effect already written):
        # the decision is the one already logged — `record_judgment` does not log it a second time
        out.replayed = bool(applied)
        return out
    d = fresh if fresh is not None else raw(spec)
    if d is None:
        return d
    safe = JG.UNSURE.get(g)
    if d.choice == safe or d.choice is None:
        return d
    if not opts or d.choice not in opts:
        return d
    irr = any(n == "irreversible" and str(t).strip() not in ("", "none") for n, t in (spec.brief_parts or []))
    if posthoc(p, g, spec, irr, d):
        # 0.102.5 user decision (2026-11-22, k6-notes "사람 개입 최소화"): a §10.2-6 UNVERIFIED group (no valve set) does not
        # stop for a person — the judge's decision runs and is graded AFTER (`post_hoc` on its decision block → a
        # grading-sheet row, `dev grade`; a confirmed wrong sets `group.<G>.conservative` — this gate then asks again).
        # No blind / predict-first question on this path. Irreversible (§3.2) and security decisions still ask
        d.post_hoc = "unverified %s" % g.replace(":", "-")
        if getattr(p, "journal", None) is not None:
            p.journal.append("event", what="post-hoc", group=g, point=pt_name or g, choice=d.choice)
        return d
    if getattr(p, "dual_rate", 0):
        # K6 r2 m2: the §9.4-7 dual judgment samples the NON-conservative picks too — before the question, into the
        # local tape only (never the pending block: `dual_choice` could show the recommendation); the decision the
        # answer applies carries it (`dual` on the applied block, read by `dev health` against the judge's pick).
        # Without this the sample of a gated group was its conservative picks only (they never reach `Ask`).
        from workflows.dev import dual as DUAL
        DUAL.check(p, spec, d, raw)
    brief = _brief_h(spec)
    _save_tape(p, key, spec.stage, d, brief)
    run_id = _run_field(p.__dict__.get("_cons_live")) if spec.stage in REPLAY_STAGES else None
    used_keys = ",".join(sorted(set((p.__dict__.get("_cons_used") or {}).values())))
    p.__dict__.pop("_cons_live", None)
    p.__dict__.pop("_cons_replay", None)
    p.__dict__.pop("_cons_seen", None)
    p.__dict__.pop("_cons_used", None)
    p.__dict__.pop("_cons_used_replay", None)
    # stakes high always: a conservative group's answer is a gate answer (§2.5 — the answerer removes the label)
    line = "%s — %s %s 결정을 사람이 정함" % (source_label(p, g), g, spec.step or spec.point or "")
    if security(spec, d):
        # 0.102.7 (review-0102-6 M1): why an unverified group's decision is asked — the security reading named
        line += " (보안: %s)" % security_why(spec, d, g)
    q = ASK.Question(KIND, line, [{"token": o, "label": o} for o in opts] + [{"token": "stop", "label": "stop"}],
                     recommended=d.choice, recommended_by=d.by, refs=key, group=g, stakes="high",
                     # K5r11-M1: the neutral wording never carries the group name (`SPLIT` IS the option `split`) —
                     # the issue, the gate and the step only; `predict.leak` also ignores this engine template
                     neutral=_neutral(p, spec), raised_by="confirm")
    q.point = "conservative:%s" % g
    q.irreversible = irr
    if inherent(g):
        # K6 r2 M1: asking states the recommendation — blind or not, never a counted blind judgment
        q.inherent = inherent(g)
    if key != pt:
        # K6 r1 M2: an earlier answer of this decision point exists (applied, or retired `stale`) — its resolution
        # revealed the recommendation of that time (and a `stale` block says the judge moved since). The person can
        # infer this question's recommendation: it stays blind but is never a §9.5 / §10.2-6 blind judgment
        q.after_reveal = "earlier answer at %s" % pt
    if run_id is not None:
        # K6 (item 33): the stage run's identity and the answers it already applied ride on the GitHub block — a clone
        # without the local tape reuses those answers while the run's role calls match (no 2ⁿ−1 re-asks)
        q.extra = {"cons_run": run_id or "-", "cons_used": used_keys, "cons_brief": brief}
    raise Ask(q, line)


SECURITY_ROLE = "security"
# 0.102.6 (review-0102-5 B2): a decision is about security when its INPUTS carry a security concern — derived from the
# brief parts the engine's own call sites build (never from a part name no call site uses):
#   DE-ARB  `arbitration.blocked`  ("role", "<role> returned <status>"), ("line", <the role's blocker>)
#   STAKES  `arbitration.blocked`  → `stakes`  ("question", "<role>: <line>"), ("about_to_take", <assumption>)
#   QA      `stages.qa._judge`     ("qa", "QA report: …"), ("candidates", "Human-QA candidates from qa: …")
#   EX-ARB  `stages.execute.ex_arb` ("findings", <auditor json>), ("roles", "<role> <status> — <why>" lines)
# 0.102.7 (review-0102-6 M1): the PRIMARY signal is language-independent and structured — the judge of every group
# whose decision can run post hoc and may carry a security issue writes `security_concern: true|false` (+ a short
# `security_reason`) in its output (`SECURITY_FIELD_GROUPS`; the judge reads the repo's language). `true`, missing or
# not a boolean → a security decision → a person decides it. Kept beside it:
# (a) the security ROLE as the source: its name opens the `role` / `question` / a `roles` line;
# (b) an EXTRA trigger on the brief text (`security_text`): ISSUE phrases only (a vulnerability, a secret exposed, an
#     auth bypass, a data leak — en / ko / ja), never a feature or bug word (`dependency injection`, `memory leak`,
#     `401 Unauthorized`, `keychain`, `encrypt`) — an auth / storage Issue's routine decisions do not stop.
SECURITY_INPUTS = {
    "DE-ARB": {"role": ("role",), "text": ("line",)},
    "STAKES": {"role": ("question",), "text": ("question", "about_to_take")},
    "QA": {"role": (), "text": ("qa", "candidates")},
    "EX-ARB": {"role": ("roles",), "text": ("findings", "roles")},
}
SECURITY_FIELD = "security_concern"
SECURITY_REASON = "security_reason"
# 0.102.8 (review-0102-7 m1, lead decision 1): EVERY group whose decision can run post hoc carries the field — every
# gated group (`GATED`: STAKES · SPLIT · INTEGRATE · TEST · QA · DE-ARB · AN-PO · VIS-ENV · DIRECTIVE · HANDOFF · EX-DWC)
# and the two not gated here that still proceed on the judge (KICKOFF, EX-ARB); missing / not a boolean → ask
SECURITY_FIELD_GROUPS = tuple(GATED) + ("KICKOFF", "EX-ARB")
# whole-phrase issue patterns (case-insensitive; `\b` only where the script has word boundaries).
# 0.102.8 (review-0102-7 m2): `plain text` / `unencrypted` / `평문` / `平文` are exposure words now (they need a secret
# noun in the same sentence — "render as plain text instead of HTML" is no issue); `취약` / `脆弱` alone are not
# (a flaky test, a weak network) — `취약점` / `脆弱性`; injection / authorization-gap phrases in ko / ja, path
# traversal, IDOR, open redirect and remote code execution are issues
_SEC_ISSUE = (
    r"\binsecure(ly)?\b", r"\bvulnerab(ility|ilities)\b", r"\bvulnerable to\b", r"\bexploit(s|ed|able|ing)?\b",
    r"\b(xss|csrf|ssrf|idor|rce)\b", r"\bcve-\d", r"\binsecure direct object", r"\b(path|directory) traversal\b",
    r"\bopen redirects?\b", r"\b(remote|arbitrary) code execution\b",
    r"\b(sql|command|code|script|html|shell|ldap|header|template|os command) injection\b", r"\bprivilege escalation\b",
    r"\b(auth|authentication|authorization|login|permission|access[- ]control) bypass\b",
    r"\bbypass(es|ed|ing)? (the |a |an )?(auth|authentication|authorization|login|permission|access)",
    r"\bsecurity (issue|problem|hole|flaw|risk|bug|vulnerability|concern|defect|incident)s?\b", r"\(security\)",
    r"\bexposed without\b", r"\bwithout (any )?(auth|authentication|authorization|permission) check",
    r"\bmissing (an? )?(auth|authorization|permission|access) check", r"\bdata (leak|breach)",
    r"\bpersonal data (is |are )?(leaked|exposed|logged)",
    # 0.102.9 (review-0102-8 m1): another user's data reachable
    r"\b(read|see|view|access|modify|edit|delete|fetch)(s|ed|ing)? (the )?(data|records?|\w+) of (another|other) users?\b",
    r"\b(another|other) users'?s? (data|records?|private|personal|\w+ (is|are) (readable|visible|accessible))",
    r"\b(can|could) (read|see|view|access|modify|delete) (another|other) users'?",
    # ko
    "취약점", "취약성", r"보안\s*(문제|취약|위험|결함|이슈|구멍|사고|우려|상의? 문제)", r"\(보안\)",
    "권한 ?우회", "인증 ?우회", "권한 ?상승", "개인 ?정보 ?(유출|노출)",
    r"(sql|커맨드|명령어?|os ?명령어?|스크립트|html|코드|ldap|헤더|셸|쉘) ?(인젝션|주입)",
    r"(권한|인가|인증|접근 ?권한|접근 ?제어) ?(검사|체크|확인) ?(누락|없이|빠짐|부재)", r"(인가|권한) ?누락",
    "경로 ?탐색 ?취약", "오픈 ?리다이렉트", "원격 ?코드 ?실행",
    r"(다른|타) ?(사용자|유저|회원|계정)(의|가)? ?[^.。\n]{0,30}(읽을 수|볼 수|보인다|보이는|조회할 수|조회된다|접근할 수|접근된다|"
    r"수정할 수|삭제할 수|노출)",
    # ja
    "脆弱性", r"セキュリティ(上の)?(問題|リスク|欠陥|ホール|事故|懸念)", r"[（(]セキュリティ[)）]",
    "認証回避", "権限昇格", "個人情報(の)?(漏洩|漏えい|流出)",
    r"(sql|コマンド|os ?コマンド|スクリプト|html|コード|ldap|ヘッダー?|シェル) ?インジェクション",
    "認可漏れ", "認証漏れ", r"(権限|認可|アクセス制御)(の)?(チェック|確認)?漏れ", "パストラバーサル",
    "オープンリダイレクト", "リモートコード実行",
    r"(他|ほか)の?(ユーザー?|利用者|会員|アカウント)の[^。\n]{0,30}(見え|閲覧でき|読め|参照でき|アクセスでき|編集でき|削除でき|取得でき)",
)
# a secret noun and an exposure word in the same sentence — `the token leaks`, `password is sent to analytics`.
# 0.102.8 m2: a bare `token(s)` / `토큰` / `トークン` is a secret noun except as a design / colour / theme token or a
# token COUNT / limit / usage (an LLM or lexer word); `committed` / `커밋` stay exposure words (a key committed)
_SEC_NOUN = (r"\b(secrets?|credentials?|passwords?|passcodes?|api[ _-]?keys?|private keys?|(access|refresh|auth|"
             r"bearer|session|id|jwt|oauth|api) tokens?|pii)\b|"
             r"비밀번호|비밀 ?키|시크릿|(액세스|리프레시|인증|세션|api|jwt) ?토큰|자격 ?증명|api ?키|"
             r"개인 ?키|パスワード|認証情報|(アクセス|リフレッシュ|認証|セッション)トークン|秘密鍵|シークレット|apiキー")
# 0.102.9 (review-0102-8 m1): a BARE token is a secret noun only when its sentence has no design-system context — a
# semantic / spacing / colour token committed or exposed through ThemeData is no secret
_SEC_TOKEN = (r"\btokens?\b(?! ?(count|counts|limit|limits|usage|budget|cost|costs|window|ids?\b))|"
              r"토큰(?! ?(수|개수|사용량|한도))|トークン(?!数)")
_DESIGN_CTX = (r"\b(design|colou?rs?|theme|themedata|semantic|spacing|typography|palette|elevation|radius|radii|motion|"
               r"shadow|font|sizing|style)\b|디자인|컬러|색상|팔레트|테마|간격|타이포|시맨틱|デザイン|カラー|配色|テーマ|"
               r"パレット|余白|タイポ|セマンティック")
# personal data is a secret-like noun only beside a LOG / analytics output (UI '노출' of a privacy link is no issue)
_PII_NOUN = r"\b(personal (data|information)|user data)\b|개인 ?정보|사용자 ?정보|個人情報|ユーザー情報"
_SEC_LOG = (r"\b(logged|logs it|printed to (the )?(log|console)|in (the )?logs?|to (the )?logs?|analytics|crashlytics)\b|"
            r"로그로|로그에|로그 ?출력|ログ出力|ログに|ログへ|ログで")
_SEC_EXPOSE = (r"\b(leak(s|ed|ing)?|logged|logs it|printed|exposed|exposes|committed|hard-?coded|in (the )?logs?|"
               r"analytics|crashlytics|world-readable|publicly|unencrypted|not encrypted|bundled|in the (app )?bundle|"
               r"shipped in)\b|"
               r"유출|노출|로그에|로그로|로그 ?출력|하드코딩|커밋|외부로|암호화되지 않|암호화 없이|번들에 포함|앱에 포함|"
               r"漏洩|漏えい|流出|ログに|ログ出力|ハードコード|露出|公開され|暗号化されていない|バンドルに含|同梱")
# 0.102.9 (review-0102-8 m1): `plain text` / `평문` / `平文` expose a secret except where a show-password control is
# what the sentence is about (an eye icon, a show / reveal toggle) — that is the feature, not a leak
_SEC_PLAIN = r"\bplain[ -]?text\b|평문|平文"
_SHOW_UI = (r"\beye icon\b|\b(show|reveal|unmask)(ing|s)? (the )?password\b|\b(visibility|show|reveal) toggle\b|"
            r"\btoggle\b|보기 ?토글|보기 ?버튼|눈 ?아이콘|표시 ?토글|토글|目のアイコン|表示切り?替|トグル")
# 0.102.9 (review-0102-8 m1): a mobile OS permission (camera / microphone / location …) missing or unchecked is a
# feature defect, not an authorization gap — those phrases are taken out before the issue patterns run
_DEVICE_PERM = (r"\b(camera|microphone|mic|location|notification|photos?|storage|bluetooth|contacts?|calendar|media|"
                r"gallery|recording|audio|runtime|android|ios|os) permissions?\b|"
                r"(카메라|마이크|위치|알림|사진|저장소|저장 ?공간|블루투스|연락처|캘린더|미디어|갤러리|녹음|오디오|런타임|"
                r"안드로이드|android|ios|os|기기|단말) ?권한|"
                r"(カメラ|マイク|位置情報|通知|写真|ストレージ|ブルートゥース|bluetooth|連絡先|カレンダー|メディア|録音|"
                r"オーディオ|ランタイム|android|ios|os|端末)(の|へのアクセス)?権限")
_SENTENCE = r"[.;\n。！？!?]"


def security_text(text):
    """0.102.7: the EXTRA content trigger — an issue phrase (`_SEC_ISSUE`), or a secret noun with an exposure word in
    one sentence. Never the primary signal (that is the judge's `security_concern`)."""
    import re
    t = re.sub(_DEVICE_PERM, "device-permission", text or "", flags=re.I)
    if any(re.search(rx, t, re.I) for rx in _SEC_ISSUE):
        return True
    for sent in re.split(_SENTENCE, t):
        noun = re.search(_SEC_NOUN, sent, re.I) or (re.search(_SEC_TOKEN, sent, re.I)
                                                     and not re.search(_DESIGN_CTX, sent, re.I))
        expose = re.search(_SEC_EXPOSE, sent, re.I) or (re.search(_SEC_PLAIN, sent, re.I)
                                                        and not re.search(_SHOW_UI, sent, re.I))
        if noun and expose:
            return True
        if re.search(_PII_NOUN, sent, re.I) and re.search(_SEC_LOG, sent, re.I):
            return True
    return False


_security_words = security_text                       # 0.102.6 name, kept for readers


def _role_named(text):
    """A brief line that opens with the security role's name (`security returned BLOCKED`, `security: …`,
    `security BLOCKED — …`)."""
    import re
    return any(re.match(r"\s*%s\b(?![-\w])" % SECURITY_ROLE, ln) for ln in (text or "").split("\n"))


def concern_of(decision):
    """0.102.7 (review-0102-6 M1): the judge's structured security reading of `decision` — True (a concern), False
    (none), never None: a missing field or one that is not a boolean is a concern (ask)."""
    f = getattr(decision, "fields", None)
    if not isinstance(f, dict):
        return True
    return f.get(SECURITY_FIELD) is not False


def security(spec=None, decision=None, group=None):
    """A decision about a security concern — never post-hoc: a person decides it (0.102.5 user decision).
    0.102.7: the judge's `security_concern` of `decision` (a group of `SECURITY_FIELD_GROUPS`: true / missing / invalid
    → True), the security role as the source (`SECURITY_INPUTS` role parts), or an issue phrase in the brief text
    (`security_text`, extra). Without a decision (before the judge) only the inputs are read."""
    g = str(group or getattr(spec, "group", "") or "")
    if decision is not None and g in SECURITY_FIELD_GROUPS and concern_of(decision):
        return True
    if spec is None:
        return False
    if "security" in str(getattr(spec, "point", "") or "").lower():
        return True
    if getattr(spec, "security", False):
        return True                                     # a call site that knows its input is a security role's
    want = SECURITY_INPUTS.get(g)
    if not want:
        return False
    for n, t in (getattr(spec, "brief_parts", None) or []):
        if n in want["role"] and _role_named(str(t)):
            return True
        if n in want["text"] and security_text(str(t)):
            return True
    return False


def security_why(spec=None, decision=None, group=None):
    """0.102.8 (review-0102-7 m2): the reason a question line gives for a security decision — from the source that
    made it one: the judge's `security_reason` only when its `security_concern` is what triggered (never its "none"
    reason beside a `false`), else the security role or the brief's issue phrase."""
    g = str(group or getattr(spec, "group", "") or "")
    if decision is not None and g in SECURITY_FIELD_GROUPS and concern_of(decision):
        f = getattr(decision, "fields", None)
        why = f.get(SECURITY_REASON) if isinstance(f, dict) else None
        return " ".join(str(why).split())[:160] if why else "판단의 security_concern 이 false 가 아님"
    for n, t in (getattr(spec, "brief_parts", None) or []):
        if n in (SECURITY_INPUTS.get(g) or {}).get("role", ()) and _role_named(str(t)):
            return "security 역할의 판단"
    return "입력에 보안 사안"


def posthoc(p, group, spec=None, irreversible=False, decision=None):
    """0.102.5: is `group`'s non-conservative decision graded AFTER instead of asked? — only when the group is on the
    conservative side for being §10.2-6 UNVERIFIED (not a valve: a valve = a person or the count rule wants it asked)
    and the decision is neither on an irreversible path (§3.2) nor about security (0.102.7: the judge's
    `security_concern` of `decision` included)."""
    from workflows.dev import predict as PF
    if PF.conservative_source(p, group) != "unverified":
        return False
    return not irreversible and not security(spec, decision, group)


def _neutral(p, spec):
    """The registered blind wording (`predict.neutral_text`) — a step outside its closed slot is shown as `-`."""
    from workflows.dev import predict as PF
    try:
        return PF.neutral_text("conservative", int(p.issue), spec.step or spec.point or "-")
    except ValueError:
        return PF.neutral_text("conservative", int(p.issue), "-")


def guarded(p, stage, thunk):
    """K5r9-M2: one stage run under the conservative path (the FSM's `_guarded`): a gate's `Ask` → the question is
    surfaced at `stage`, `Hold` → the run holds; the `applied` marks the gate deferred are written when the answers'
    effect is — the stage ended without FAIL (`flush`), held, or went on to its next question (`surface`). A FAIL or a
    crash writes none: the same decision point applies the answer again."""
    begin(p)
    try:
        r = thunk()
    except Ask as a:
        return surface(p, stage, a)
    except Hold as h:
        flush(p)
        return hold(p, stage, h)
    except NeedGrounds as ng:
        flush(p)
        p.__dict__.pop("_cons_guidance", None)
        from workflows.dev.stages import base as B
        if not getattr(p, "unattended", False):
            return B.StageResult(B.StageResult.HOLD, line=ng.line)
        return B.pause(p, stage, "ambiguity", ng.line, "ambiguity: %s" % ng.line)
    from workflows.dev.stages import base as B
    if r is None or r.kind != B.StageResult.FAIL:
        flush(p)
    return r


def surface(p, stage, ask):
    """The FSM's side: ask (attended) / pause (unattended) with the gate's question at `stage`. The answers this stage
    run applied before it reached this question took effect (the run went on to it) — their `applied` marks first."""
    from workflows.dev.stages import base as B
    flush(p)
    line = ask.line
    return B.ask(p, stage, ask.question, line, {"cause_kind": "ambiguity", "line": line,
                                                 "token_cause": "ambiguity: %s" % line})


def hold(p, stage, h):
    from workflows.dev.stages import base as B
    return B.StageResult(B.StageResult.HOLD, line=h.line)
