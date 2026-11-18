"""workflows.dev.fsm — the Issue FSM (design §2.2, §2.5 resume rules, §3.6 hand-overs, §2.4 exit codes).

`Driver(ports_for, unattended).run(n, only=None) -> Outcome{result, exit_code, line, rl}`

    first contact   a `point: engine-start` decision block BEFORE any label write (R3C-M5)
    resume (§2.5)   every unresolved pending-human block: not alive (`decisions.live`) → a
                    `superseded` block; alive + unattended → the answer channel (`ask.settle`):
                    answered → the stage applies it; label still on → stop (exit 0); label removed
                    without an answer → re-judge (that point's judgment cache is dropped); no
                    unlabel event → the pause died mid-write → finish it (comment, label) with the
                    block's own `cause:`. Attended → the stored question is asked again.
    route           sprint → FAIL (no label) · done → OPEN ∧ closed-as-decided → finish the close
                    (A-F37) · children → 2b/2c (children driven by THIS driver, recursively) · none →
                    analyze (T1) · stage S → its stage
    hand-overs      after analyze/design the stage itself checked (§3.6); after execute the FSM
                    runs `handoff.execute_to_test` (K2/K3 carry-over) and, on a failure, SJ-HANDOFF:
                    ok / ok_with_assumption → on; upstream_gap ∧ fixable_by_execute → the loop-back
                    procedure `from: leader` (cap/stagnation guards) and execute again; otherwise a
                    person (`defect:`). `engine.handoff_judge: always` judges every execute→test too.
    variants        execute = `type:bug` → debug · `type:refactor` → refactor · else implement,
                    re-read from the labels right before every execute (D1.3)
    exit codes      0 terminal (DONE / PAUSE / ASK / prevalidate FAIL) · 3 gh auth · 6 halted
                    (kill switch → `halted: kill-switch`; env prevalidate → `halted: env <reason>`) ·
                    75 rate limit (with the latest `resetsAt`) — the supervisor reads labels, the code
                    only says how the process ended (§2.4). `--only STAGE` runs that one stage.
    NEEDS_CONTEXT   J-DEV-05 as a fixed map: analyze output → analyze, design/skeleton → design;
                    the producer already ran (the Issue is past it) → attended
                    `ask needs-context-producer-ran`, unattended `defect:` pause; never re-run the
                    same stage unchanged.
"""

from guildcore import ask as ASK
from guildcore import decisions as D
from guildcore import pause as PZ
from guildcore import state as ST
from guildcore.adapters.gh import GhError, GhWriteError, classify_error
from guildcore.decisions import DecisionLog
from guildcore.judges.runner import Halted, RateLimited
from guildcore.records import markers
from workflows.dev import handoff as HO
from workflows.dev.stages import base as B

ORDER = ("analyze", "design", "execute", "test", "qa", "done")
MAX_STAGE_RUNS = 24
PRODUCER = (("analyze output", "analyze"), ("analyze/design", "analyze"), ("skeleton", "design"),
            ("design", "design"), ("test-cases", "design"), ("target-structure", "design"))


class ChildEnded(Exception):
    """A child driven by 2b ended without a stage result (exit 1/3/6/75 — the process end): the
    parent's run ends the same way (K4r1-m13)."""

    def __init__(self, outcome):
        Exception.__init__(self, outcome.line)
        self.outcome = outcome


class Outcome(object):
    def __init__(self, result=None, exit_code=0, line=None, rl=None, halted=None):
        self.result = result
        self.exit_code = exit_code
        self.line = line if line is not None else (result.token() if result is not None else "")
        self.rl = rl
        self.halted = halted

    def __repr__(self):
        return "<Outcome %d %s>" % (self.exit_code, self.line)


def variant_of(labels):
    names = ST.label_names(labels)
    if "type:bug" in names:
        return "debug"
    if "type:refactor" in names:
        return "refactor"
    return "implement"


def producer_of(line):
    low = (line or "").lower()
    for key, stage in PRODUCER:
        if key in low:
            return stage
    return None


def _stage_fn(stage):
    from workflows.dev.stages import analyze, design, execute, qa, test
    return {"analyze": analyze.run, "design": design.run, "execute": execute.run, "test": test.run,
            "qa": qa.run}[stage]


class Driver(object):
    """`ports_for(issue, stage, variant=None) -> Ports` (live: workflows.dev.ports.fsm_ports; tests: fakes).
    `stages` overrides the stage functions (tests)."""

    def __init__(self, ports_for, unattended=True, plugin=None, stages=None, events=None, boundary=None,
                 child_lock=None):
        self.ports_for = ports_for
        # K5r1-M1: `child_lock(c) -> (lock, None) | (None, holder)` — a parent drives a child only while it
        # holds THAT child's IssueLock (one writer per Issue, §2.7); a child another run holds stops the
        # parent with exit 4 (busy) — the supervisor waits in place, then `busy-skipped`
        self.child_lock = child_lock
        # K5: `boundary(n) -> Outcome | None`, asked before every stage run (also a child's in 2b) — the kill
        # switch, the active plugin version and an attended `hold` stop the run at a step boundary (§2.4, §10.3)
        self.boundary = boundary
        self.unattended = unattended
        self.plugin = plugin
        self.stages = stages or {}
        self.events = events
        self.depth = 0
        self.active = None              # the Issue whose stage is running (a child's, inside 2b)
        # K5r2-m1: `on_active(n)` — told which Issue's stages run now (a child while 2b drives it, the parent
        # after); the CLI mirrors the runners' pid records into that child's own journal
        self.on_active = None

    # -- the process end -------------------------------------------------------------------------
    def run(self, n, only=None):
        """K4r1-M4: EVERY way the FSM can end maps to the §2.4 contract (`end_of`) — a GitHub read or
        write error by its class (auth → 3, rate limit → 75, transient / unknown → `env: service` pause,
        else `defect: engine FAIL`), any other exception → `defect: engine FAIL — <type>` (exit 0 with
        needs-human; 1 only when that pause cannot be written either).
        K5r1 decision 2: an unattended pause on an Issue create whose landing is unknown ends with exit 75
        at its `retry_at` — the supervisor resumes by itself (never a person's chore, never a re-send)."""
        try:
            out = self._run(n, only)
        except Exception as ex:                                       # noqa: BLE001 — the contract's last line
            out = end_of(ex, lambda reason, cls: self._defect(self.active or n, reason, cls))
        return self.retry_after(out)

    def retry_after(self, out):
        r = out.result
        if not self.unattended or out.exit_code != 0 or r is None or r.kind != B.StageResult.PAUSE \
                or not getattr(r, "retry_at", None):
            return out
        return retry_outcome(r, r.retry_at)

    def _defect(self, n, reason, cls="defect"):
        try:
            if self.ports_for is None:
                raise RuntimeError("no GitHub ports (setup failed before they existed)")
            p = self.ports_for(n, None)
            r = B.fail(p, "engine", reason, cls)
            return Outcome(r, 0)
        except (GhWriteError, GhError) as ex:
            kind = ex.kind if isinstance(ex, GhWriteError) else classify_error(str(ex))
            if kind == "auth":
                return Outcome(None, 3, "gh auth failed — %s" % B.one_line(str(ex), 160))
            if kind == "ratelimit":
                return Outcome(None, 75, "GitHub rate limit — %s" % B.one_line(str(ex), 120))
            if self.unattended and kind in ("transient", "unknown", "ambiguous"):
                return service_wait(reason, ex)
            return Outcome(None, 1, "engine FAIL — %s (pause not written: %s)" % (reason, B.one_line(str(ex), 80)))
        except Exception as ex:                                       # noqa: BLE001
            if self.unattended and cls == "transient":                # e.g. `gh repo view` 502 before any port
                return service_wait(reason, ex)
            return Outcome(None, 1, "engine FAIL — %s (pause not written: %s)" % (reason, B.one_line(str(ex), 80)))

    def _fn(self, stage):
        return self.stages.get(stage) or _stage_fn(stage)

    # -- the FSM ------------------------------------------------------------------------------
    def _run(self, n, only):
        self.active = n
        p0 = self.ports_for(n, None)
        if p0.config is None:
            return self._end(n, B.env_halt("uninitialized", "Guild not initialized (run /gld init)"))
        issue = p0.gh.issue(n)
        if "/pull/" in (issue.get("url") or ""):
            return Outcome(B.StageResult(B.StageResult.FAIL, line="#%d is a pull request, not an Issue" % n,
                                         fail_class="prevalidate"), 0)
        state = ST.derive(issue.get("labels"))
        if state.sprint:
            return Outcome(B.StageResult(B.StageResult.FAIL, fail_class="prevalidate",
                                         line="#%d is a sprint tracking Issue — use /gld sprint daily" % n), 0)
        comments = B.records(p0)
        log = DecisionLog.load(comments)
        if log.engine_start() is None:                                   # R3C-M5 — before any label write
            p0.decisions.record({"point": "engine-start", "by": "code", "stage": state.stage,
                                 "started_at_stage": state.stage, "plugin": self.plugin or p0.plugin or "unknown"})
        stop = self.resume(p0, n, state)
        if stop is not None:
            return stop
        runs = 0
        while True:
            runs += 1
            if runs > MAX_STAGE_RUNS:
                return self._defect(n, "engine stage loop limit (%d runs)" % MAX_STAGE_RUNS)
            if self.boundary is not None:
                stop = self.boundary(n)
                if stop is not None:
                    return stop
            issue = p0.gh.issue(n)
            state = ST.derive(issue.get("labels"))
            stage = state.stage
            if stage == "guild:done" or stage == "done":
                if not only:
                    return self.finish_done(p0, n, issue)
                if only != "test":                                      # K4r1-m2: only test re-verifies a done Issue
                    return Outcome(B.StageResult(B.StageResult.FAIL, fail_class="prevalidate", line=(
                        "#%d is at guild:done — /gld %s does not run on it (use /gld rollback stage to move back)"
                        % (n, only))), 0)
                stage = "test"
            if stage == "children":
                if only:
                    return Outcome(B.StageResult(B.StageResult.FAIL, fail_class="prevalidate", line=(
                        "#%d is a split parent (guild:children) — /gld %s does not run on it" % (n, only))), 0)
                from workflows.dev.stages import children as CH
                pc = self.ports_for(n, "children")
                r = CH.run(pc, self._drive_child)
                return self._end(n, r)
            target = "analyze" if stage == "none" else stage
            if only and target != only and not (only == "test" and stage == "done"):
                return Outcome(B.StageResult(B.StageResult.FAIL, fail_class="prevalidate", line=(
                    "#%d is at guild:%s — /gld %s runs only at guild:%s (use /gld rollback stage to move back)"
                    % (n, stage, only, only))), 0)
            variant = variant_of(issue.get("labels")) if target == "execute" else None
            p = self.ports_for(n, target, variant)
            why = getattr(p, "unavailable", None)
            if why:                                                      # K4r1-B1: e.g. no engine worktree
                if not self.unattended:
                    return Outcome(B.StageResult(B.StageResult.FAIL, line=why, fail_class="defect"), 0)
                return self._end(n, B.pause(p, target, "env", why, "env: other — %s" % why, env_key="other"))
            p.stage_start = p.now()                                       # K3 m4 contract: the FSM passes it
            fn = self._fn(target)
            r = fn(p, variant) if target == "execute" else fn(p, only=only)
            if r.kind == B.StageResult.ADVANCE:
                if target == "execute":
                    r2 = self.after_execute(p, n)
                    if r2 is not None:
                        if r2.kind != B.StageResult.LOOPBACK:
                            return self._end(n, r2)
                if only:
                    return self._end(n, r)
                continue
            if r.kind in (B.StageResult.LOOPBACK, B.StageResult.SPLIT):
                if only:
                    return self._end(n, r)
                continue
            if r.kind == B.StageResult.FAIL and r.fail_class == "needs_context":
                return self._end(n, self.needs_context(p, n, target, r))
            return self._end(n, r)

    def _drive_child(self, c):
        """K5r1-M1/M2: a child runs under its own IssueLock; only an explicit DONE lets the parent go on
        (`children.run` stops on anything else — hold, pause, ask, budget, fail); a process end (exit ≠ 0)
        or a busy child ends the parent's run the same way."""
        lock = None
        if self.child_lock is not None:
            lock, holder = self.child_lock(c)
            if lock is None:
                mode = (holder or {}).get("mode") or "unknown"
                line = "busy: child #%d of #%d is held by an %s run — the parent waits for it" % (c, self.active or 0, mode)
                raise ChildEnded(Outcome(B.StageResult(B.StageResult.HOLD, line=line), 4, line))
        self.depth += 1
        parent = self.active
        if self.on_active is not None:
            self.on_active(c)
        try:
            out = self._run(c, None)
        finally:
            self.depth -= 1
            if self.on_active is not None:
                self.on_active(parent)
            if lock is not None:
                lock.release()
        self.active = parent            # an exception leaves `active` on the child: its pause lands there
        if out.result is None or out.exit_code != 0:
            raise ChildEnded(out)
        return out.result

    def _end(self, n, r):
        if r.kind == B.StageResult.FAIL:
            if r.fail_class == "gh_auth":
                return Outcome(r, 3)
            if r.fail_class == "prevalidate_env":
                note = next((x for x in r.notes if x.startswith("halted: env ")), "halted: env other")
                return Outcome(r, 6, note)
        return Outcome(r, 0)

    # -- done ---------------------------------------------------------------------------------
    def finish_done(self, p, n, issue):
        """A-F37: `guild:done` ∧ OPEN ∧ a closed-as-decided comment → T3 ④ was interrupted: close."""
        if (issue.get("state") or "").upper() == "OPEN":
            recs = B.records(p)
            cd = markers.find(recs, "closed-as-decided")
            ao = markers.find(recs, "analyze:output")
            # K4r1-m6: only while analyze:output STILL says "결정대로 닫음" — a later analyze that went
            # on to work replaced it, and a stale closed-as-decided must not close a worked Issue
            if cd is not None and ao is not None and "결정대로 닫음" in markers.body_of(ao):
                body = markers.body_of(cd)
                reason = "not_planned" if "(not_planned)" in body else "completed"
                p.writer.issue_close(n, reason)
                return Outcome(B.StageResult(B.StageResult.DONE, line="closed-as-decided — close finished"), 0)
        return Outcome(B.StageResult(B.StageResult.DONE), 0)

    # -- §3.6 execute→test --------------------------------------------------------------------
    def after_execute(self, p, n):
        cfg = getattr(p.config, "raw", None) or (p.config if isinstance(p.config, dict) else {})
        comments = B.records(p)
        bad = HO.execute_to_test(comments, p.gh.pr_search(n), n, cfg)
        always = p.engine_cfg("handoff_judge", "default") == "always"
        if not bad and not always:
            return None
        from workflows.dev import analysis as AN
        from guildcore.records import outputs as OUT
        so = OUT.find(comments, "analyze:output")
        ac = "\n".join("%s: %s" % (a["id"], a["text"]) for a in (AN.parse_output(so.body).ac if so else []))
        issue = p.gh.issue(n)
        d = HO.judge(p, "test", "execute→test", bad, [], ac, B.title_text(p, issue, n), "X→T")   # K5r1-m1
        if d.choice in ("ok", "ok_with_assumption"):
            return None
        sig = sorted(set(str(x) for x in (d.fields.get("signature") or []))) or ["handoff:%s" % (bad[0] if bad else "gap")]
        reason = d.fields.get("reason") or "; ".join(bad) or "execute→test gap"
        labels = ST.label_names(issue.get("labels"))
        if d.fields.get("fixable_by_execute") and ("guild:test" in labels or "guild:qa" in labels):
            from workflows.dev.stages import loopback as LP
            pt = self.ports_for(n, "test")
            cur = "guild:test" if "guild:test" in labels else "guild:qa"
            return LP.run(pt, "test" if cur == "guild:test" else "qa", "leader", reason, sig, current_label=cur,
                          capture_role="leader")
        line = "execute→test hand-over gap — %s" % B.one_line(reason, 200)
        if not self.unattended:
            q = ASK.Question("escalation", line, [{"token": "stop", "label": "stop"}])
            return B.ask(p, "test", q, line)
        return B.pause(p, "test", "defect", line, line)

    # -- NEEDS_CONTEXT (J-DEV-05) ---------------------------------------------------------------
    def needs_context(self, p, n, stage, r):
        prod = producer_of(r.line)
        if prod is None:
            line = "NEEDS_CONTEXT outside the fixed map — %s" % B.one_line(r.line, 160)
            return B.pause(p, stage, "defect", "engine unknown state — %s" % line, line) if self.unattended else r
        line = "%s — the producing stage (%s) already ran but left nothing behind" % (B.one_line(r.line, 160), prod)
        q = ASK.Question("needs-context-producer-ran", line, [{"token": "stop", "label": "stop"}])
        return B.ask(p, stage, q, line, {"cause_kind": "defect", "line": line, "token_cause": line})

    # -- §2.5 resume ----------------------------------------------------------------------------
    def resume(self, p, n, state):
        comments = p.gh.comments(n)
        trusted = B.records(p)
        log = DecisionLog.load(trusted)
        pend = log.pending_human()
        if not pend:
            return None
        timeline = p.gh.timeline(n)
        own = list(p.journal.own_label_writes()) if p.journal is not None else []
        labels = ST.label_names(p.gh.issue(n).get("labels"))
        assoc = tuple(p.engine_cfg("answer_associations", D.DEFAULT_ASSOCIATIONS) or D.DEFAULT_ASSOCIATIONS)
        for blk in pend:
            alive, why = D.live(blk, state, timeline, own)
            if not alive:
                # K5r2-M1: the answer channel is READ before a supersede — a member's answer to a question that
                # went stale is named in the superseded block (who, which comment), never silently dropped; it
                # is not applied (the stage that asked is no longer where the Issue is)
                f = {"point": blk.get("point"), "kind": blk.get("kind"), "stage": blk.get("stage"),
                     "by": "code", "status": "superseded", "reason": why}
                if self.unattended:
                    st0, ans, _rej = D.accepted_answer(blk, comments, timeline, True, assoc)
                    if st0 == "answered":
                        f["reason"] = "%s — answer `%s` by %s read, not applied (the question is stale)" % (
                            why, ans.token, ans.author)
                        f["answer_comment"] = ans.comment_id
                p.decisions.resolve(blk.id, f)
                continue
            if not self.unattended:
                opts = [{"token": t, "label": t} for t in blk.options()]
                q = ASK.Question(blk.get("kind"), blk.get("question") or "-", opts, recommended=blk.get("recommended")
                                 if blk.get("recommended") in blk.options() else None)
                if p.events is not None:
                    p.events.emit("ask", p.now(), **q.event(blk.id))
                return Outcome(B.StageResult(B.StageResult.ASK, line=blk.get("question") or "-", qid=blk.id), 0)
            st, _x = ASK.settle(p.decisions, p.writer, n, blk, comments, timeline, True, assoc, journal=p.journal)
            if st == "answered":
                continue
            if st == "conflict" or "guild:needs-human" in labels:
                return Outcome(B.StageResult(B.StageResult.PAUSE, cause="waiting for a human answer to %s" % blk.id), 0)
            since = blk.get("at_server") or blk.get("at") or ""
            unl = [ev for ev in timeline if ev.get("event") == "unlabeled" and
                   ((ev.get("label") or {}).get("name") == "guild:needs-human") and (ev.get("created_at") or "") > since]
            if unl:                                                      # rule 3 — "judge again"
                p.decisions.resolve(blk.id, {"point": blk.get("point"), "kind": blk.get("kind"), "stage": blk.get("stage"),
                                             "by": "code", "status": "superseded",
                                             "reason": "needs-human removed without an answer — re-judge"})
                if p.journal is not None:
                    for point in ("KICKOFF", "STAKES", "SPLIT", "DE-ARB", "INTEGRATE", "HANDOFF", blk.get("point")):
                        p.journal.cache_invalidate(point)
                continue
            cause = blk.get("cause") or "defect: engine pause interrupted — %s" % (blk.get("question") or "-")
            kind, _, rest = cause.partition(": ")
            env_key = None
            if kind == "env":
                env_key, _, rest = rest.partition(" — ")
            pz = PZ.Pause(kind if kind in ("defect", "ambiguity", "env") else "defect", rest or cause, env_key=env_key)
            PZ.complete(p.writer, p.decisions, n, blk, pz)
            return Outcome(B.StageResult(B.StageResult.PAUSE, cause=cause), 0)
        return None


class _Reset(object):
    def __init__(self, resets_at):
        self.resets_at = int(resets_at)


def retry_outcome(result, at):
    """Exit 75 with `resetsAt` = `at`: the supervisor's wait-and-rerun path (bounded there — 6 waits, then
    `account-rate-limited` blocked, never failed). The result line says what it is: not a rate limit."""
    import time as _t
    line = "create-settle-wait: an Issue create's landing is unknown; the supervisor resumes after %s and re-checks " \
           "it (found → go on, absent → create again) — not a rate limit" % _t.strftime("%Y-%m-%dT%H:%M:%SZ", _t.gmtime(int(at)))
    o = Outcome(result, 75, line, rl=_Reset(at))
    o.retry_at = int(at)
    o.wait_reason = "create-settle"          # K5r2-m2: the stdout event names it — never read as a rate limit
    return o


SERVICE_WAIT_S = 900


def service_wait(reason, ex):
    """K5r2-m8: GitHub is unavailable AND the `env: service` pause could not be written either (or nothing to
    write it with existed yet) — the member is not failed (§2.4 r1-M4: a transient is never a failure): exit 75
    with `reason: gh-service` and `resetsAt = now + 15 min`; the supervisor / batch wait on their own budget,
    then leave the member blocked `gh-unavailable` (re-run picks it up) — never `child-session-failed`."""
    import time as _t
    at = int(_t.time()) + SERVICE_WAIT_S
    line = "gh-service-wait: GitHub unavailable — %s (pause not written: %s) — retry after %s; not a rate limit" % (
        B.one_line(reason, 160), B.one_line(str(ex), 80), _t.strftime("%Y-%m-%dT%H:%M:%SZ", _t.gmtime(at)))
    o = Outcome(None, 75, line, rl=_Reset(at))
    o.wait_reason = "gh-service"
    return o


def end_of(ex, defect):
    """The §2.4 end of an exception (the FSM's and the CLI's setup / restart check — K5r1-M4).
    `defect(reason, cls) -> Outcome` writes the pause (cls transient → `env: service`, else `defect:`)."""
    if isinstance(ex, ChildEnded):
        return ex.outcome
    if isinstance(ex, Halted):
        return Outcome(None, 6, "halted: kill-switch", halted="kill-switch")
    if isinstance(ex, RateLimited):
        return Outcome(None, 75, "rate limited", rl=getattr(ex, "verdict", None))
    if isinstance(ex, GhWriteError):
        if ex.kind == "auth":
            return Outcome(None, 3, "gh auth failed — %s" % B.one_line(str(ex), 160))
        if ex.kind == "ratelimit":
            return Outcome(None, 75, "GitHub rate limit — %s" % B.one_line(str(ex), 120))
        out = defect("gh write failed — %s" % B.one_line(str(ex), 160),
                     "transient" if ex.kind in ("transient", "unknown", "ambiguous") else "defect")
        if ex.kind == "ambiguous" and out.result is not None and out.result.kind == B.StageResult.PAUSE:
            import time as _t
            out.result.retry_at = max(int(getattr(ex, "retry_at", None) or 0), int(_t.time()) + 60)
        return out
    if isinstance(ex, GhError):
        kind = classify_error(str(ex))
        if kind == "auth":
            return Outcome(None, 3, "gh auth failed — %s" % B.one_line(str(ex), 160))
        if kind == "ratelimit":
            return Outcome(None, 75, "GitHub rate limit — %s" % B.one_line(str(ex), 120))
        return defect("gh read failed — %s" % B.one_line(str(ex), 160),
                      "transient" if kind in ("transient", "unknown") else "defect")
    return defect("%s — %s" % (ex.__class__.__name__, B.one_line(str(ex), 160)), "defect")


def final_events(outcome, cost_usd=0.0, out=None):
    """§2.4 stdout contract: ONE synthetic rate_limit_event, then the result line."""
    from guildcore import emit
    if outcome.exit_code == 75:
        import time
        resets = getattr(outcome.rl, "resets_at", None) if outcome.rl is not None else None
        emit.rate_limit_event("rejected", resets or int(time.time()) + 900, out=out,   # §2.4: else now+15 min
                              reason=getattr(outcome, "wait_reason", None))
    else:
        emit.rate_limit_event("allowed", None, out=out)
    emit.stream_result(cost_usd, outcome.exit_code not in (0,), outcome.line, out=out)
