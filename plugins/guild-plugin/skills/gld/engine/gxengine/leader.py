"""Leader sessions and answer checks (stage 2 — scope §2, units V2 · V3).

Fixed by the stage-2 contract change (V1, Q2), bodies by session A (V2 · V3). Session B calls
`call()` through `driver.Units.leader` and gets a test double in its own tests (stage-1
`Units` pattern). Signatures, the LeaderRequest / LeaderResult fields and the rules in these
docstrings are the A ↔ B contract — change them only through README "Changing a contract".

Layer L3 (same layer as session / facts / results). Allowed same-layer imports:
leader → session, facts, statemachine (test_contracts.SAME_LAYER). Never imports driver,
lifecycle or cli (L4) and never writes state.json / log.jsonl / procedure.yaml itself.

What one `call()` does (scope §2.0):
  1. `allowed_answers()` — the §6.3 row (codes.STAGE2_ALLOWED_ANSWERS) minus
     codes.LEADER_REMOVED_ANSWERS minus every codes.NARROWING rule that applies (D3, D4,
     D7, D8, D14). D4 is the CONSERVATIVE variant (coordinator memo, pending A2): risk =
     high removes plan, rerun and close-as-decided, so only escalate is left.
  2. D9: when only `escalate` is left the leader is NOT called — LeaderResult(called=False).
     The caller stops at needs_human with no recommendation.
  3. `build_input()` — in/leader-input.json (schemas/leader-input, V3), plus the other in/
     files of the situation (issue.md, leader-decision.md, failure-summary.md, review.diff).
  4. `render_answer_schema()` — codes.LEADER_ANSWER_SCHEMAS[situation] filled with
     schema.fill_enums (the enum tokens of codes.LEADER_SCHEMA_TOKENS).
  5. One session through `session.run_session` with the judge render (role "leader",
     role class judge, no outputs, defaults.MODEL_EFFORT["leader"], budget key "leader" —
     D10; the judge canary key applies). Brief / result / facts / stream go to the call's
     folder (below).
  6. `check_answer()` — rendered schema → combination rules → situation rules, each
     violation a codes.LeaderFormatReason. A rejected answer is sent back with the errors
     up to defaults.leader_format_retries(situation) times (plan-gate 2, else 1 — D12);
     after that LeaderResult.failed = {"code": "output-format", "detail": <first reason>}.
  7. Failure classes (D12): no structured output / rejected → as 6; session-limit → failed
     {"code": "session-limit"} at once (no re-call); infra quota ≤ INFRA_WAIT_MAX_S →
     LeaderResult.quota_reset_at (the caller waits and calls again with the same situation);
     other infra → stop "infra-stop"; init mismatch / the leader wrote a file / a control
     file changed / an unsafe path → stop = that StopReason (a mechanical stop, needs_human).

Where a call is recorded (D13) — one folder per SESSION (a format re-call is a new session):
  * kind "check" (plan-gate, done-gate): runs/<step>/<attempt>/ — every session is the next
    attempt of the check step (store.new_attempt). This is the only state change call()
    makes: the check step's `latest_attempt`, in memory (the caller saves state).
  * kind "leader" (needs_leader situations): <records>/leader/<k>/ with the same files
    (brief.json, result.json, facts.json, stream.jsonl, stderr.log, settings.json, in/).
    k = 1 + the highest existing folder number (never reused, like store.new_attempt), so
    a re-call after an engine crash lands in leader/<k+1>/ (L21). brief.kind / facts.kind
    = "leader", brief.step / facts.step = LeaderRequest.step, attempt = k.
    Session A adds the leader/<k>/ helpers to paths.py / store.py (owned for that only).
  * budget.issue_cost (session B) sums the facts session cost of both places (D13, L25).

Session A decisions (fail-closed; the V2 · V3 report lists them):

  * The leader's security boundary is judged here, in this order: init mismatch → a
    control-file change during the session → ANY path changed during the session (the
    leader has no outputs, so every write is `judge-wrote-outside-outputs`) → the session
    end. `results` (L3) is not importable from here (test_contracts.SAME_LAYER), so the
    control-file fact is a before / after snapshot of every control entry on disk
    (ignored and untracked included, links never followed); HEAD / index changes show up
    as attempt changes. A contract change to use results.check_control_files is requested.
  * A leader session is judged by the engine and written by it: facts.json (kind check /
    leader, `outcome` = this session's verdict), result.json as received, brief.json.
  * The instruction = instructions.build_leader_instruction (session C: data/frames/leader.md
    + data/tasks/plan-gate.md / done-gate.md / the situation's needs-leader.md section + this
    call) + the call's allowed answers (Q4 wiring).
    The system prompt = CLAUDE.md + .claude/CLAUDE.md + the leader role file at the base SHA
    (`.claude/guild/roles/leader.md`, else the plugin default data/roles/leader.md —
    never the stable .claude/agents/leader.md, D11); no role file → LeaderError.
  * Rerun targets: plan-gate `analyze`; done-gate every role / run step before it;
    blocked / output-format-twice / session-limit / on-fail-exceeded the stopped step (when
    it is a role / run step) and the role / run steps before it; soft-budget and
    new-collaborator-comment (whose `step` is the next step to run) the role / run steps
    before it plus that step itself — rerun of it = go on from it (stage-1 lifecycle meaning).
  * R / D ids are kept stable through the Issue's earlier leader-input.json files (the only
    record of them): a requirement row (text + ACs + occurrence) or a discovery (role, kind,
    where, note, blocks_current_ac) that had an id keeps it; a new one gets max + 1.
  * Stage 3 (session D): the stage-3 values are picked by LeaderRequest.stage only — stage 2 keeps
    its schemas, rows and checks byte for byte (codes.leader_answer_schemas(stage)). plan-gate
    templates = the request's usable ones ∩ the TYPE_TEMPLATES row (E2); an Issue that already
    runs a template (origin_template) is offered neither `adjust` nor `models` (no new revision).
    Done-gate discoveries leave out the included fixes F1..Fn (they are judged as such); the
    follow-up cap counts per Issue, a discovery that already has its follow-up not twice; `session`
    names a role step only; `defer` is offered with two or more rows and once per Issue.
  * Missing driver facts the situation needs (issue.md, review.diff, failure-summary.md,
    templates, new comment ids, issue cost) are a caller bug → LeaderError. A judgment fact
    the engine collects itself (analysis / AC list / requirement map, the step table, a done
    run's exit code, a done review's result) that cannot be read → facts.FactMissing, raised
    before any folder is made or any session spawned.
"""

import hashlib
import json
import os
import stat
import time

from . import (acparse, canary, catalog, codes, defaults, facts, fsafe, gitops, globs, instructions, render,
               repoconfig, schema, session, statemachine, store)

LEADER_ROLE = "leader"
"""The role name of every leader session (budget key, model/effort key, role file name)."""

LEADER_DIR = "leader"
"""<records>/<owner>/<repo>/<N>/leader/<k>/ — needs_leader call folders (D13)."""

CALL_KINDS = (codes.AttemptKind.CHECK.value, codes.AttemptKind.LEADER.value)

LEADER_ROLE_FILE = f"{instructions.ROLE_FILES_DIR}/{LEADER_ROLE}.md"
"""The repository copy of the leader role file, read at the base SHA (D11)."""
PLUGIN_LEADER_ROLE_FILE = os.path.join(instructions.DATA_DIR, "roles", f"{LEADER_ROLE}.md")
"""The plugin default body (session C, V10) used when the repository has no copy."""


NO_DECISION_TEXT = "No leader decision has been made for this Issue.\n"
"""in/leader-decision.md when the caller has none (the same sentence as lifecycle)."""

SR = codes.StopReason
A = codes.LeaderAnswer
_ROLE = codes.StepKind.ROLE.value
_RUN = codes.StepKind.RUN.value
_RERUNNABLE = (_ROLE, _RUN)
_NEXT_STEP_SITUATIONS = (SR.SOFT_BUDGET.value, SR.NEW_COMMENT.value)
_STOPPED_SITUATIONS = (SR.BLOCKED.value, SR.OUTPUT_FORMAT_TWICE.value, SR.SESSION_LIMIT.value,
                       SR.ON_FAIL_EXCEEDED.value)
_REQUEST_SITUATIONS = (SR.STEP_ADD_LIMIT.value, SR.STEP_REMOVAL_REQUEST.value)
_ERRORS_MAX = 20
_DONE_GATE_DOCS = ("analysis", "test-cases", "skeleton", "manual-test-checklist")
_DENIED_WRITE_TOOLS = ("Write", "Edit", "NotebookEdit", "MultiEdit")
_INPUT_FILE = codes.InFile.LEADER_INPUT.value
_S3_ENVELOPE = codes.STAGE3_LEADER_ANSWER_SCHEMAS[SR.BLOCKED.value]
"""The stage-3 common envelope with `defer` / `session` (needs_leader situations)."""


def _now():
    """Wall clock for the quota decision (tests replace it)."""
    return time.time()

_REQUEST_FIELDS = (
    # what and where
    "situation", "kind", "step", "stage", "mode",
    # engine objects (read-only for the leader, except the check step's latest_attempt)
    "paths", "ctx", "procedure", "state", "config", "environ", "plugin_root", "render_paths",
    "cli_version", "limits",
    # facts only the driver has (session B collects them; None where the situation has none)
    "issue_md", "leader_decision", "failure_summary", "review_diff", "templates",
    "decision_marker", "referenced_issues", "new_comments", "issue_cost", "soft_acknowledged",
    "origin_template",
    # stage 3 (contract: None = stage 2; the bodies are session D's)
    "catalog", "requested_steps", "templates_unusable", "plan_role_steps", "requests", "included_fixes",
    "followup_candidates", "deferred_rows", "removal", "add_limit", "pr_review", "pr_review_md",
    # stage 4 (VB9): mutation.rows of the HEAD's record (done-gate; None = nothing declared)
    "mutations",
    # readiness E4: plan-gate {"evidence": [lines], "repro_templates": [names]} of a bug Issue, else None
    "bug_issue",
)
_RESULT_FIELDS = (
    "situation", "called", "answer", "step", "reason", "note", "recommendation", "extra",
    "attempts", "cost_usd", "failed", "stop", "quota_reset_at", "allowed", "sessions", "input", "infra",
)


class LeaderError(Exception):
    """A leader call cannot be made as specified (nothing was spawned) → engine-error (I14)."""


def _stage3(stage):
    return isinstance(stage, int) and not isinstance(stage, bool) and stage >= 3


def _situations(stage):
    """Situation → answer-schema template of the engine stage (the stage-2 table unless stage ≥ 3;
    a stage below 2 or not a number is refused where the call is checked)."""
    return codes.leader_answer_schemas(stage) if _stage3(stage) else codes.LEADER_ANSWER_SCHEMAS


class LeaderRequest:
    """Everything one leader call needs. Built by the driver (session B).

    situation       StopReason value in codes.LEADER_ANSWER_SCHEMAS (rule-unfillable /
                    base-red never come here — D9 is decided before any call).
    kind            "check" (plan-gate / done-gate) or "leader" (needs_leader).
    step            the check step id, or the step the situation is attached to (the stop's
                    step; soft-budget / new comment: the next step to run).
    stage           engine stage (≥ 2). mode: codes.RunMode value.
    paths           paths.EnginePaths of the Issue. ctx: gitops.GitContext (pinned git).
    procedure       procedure.Procedure of the current revision. state: the state dict.
    config          repoconfig settings. environ: the base env. plugin_root: plugin root.
    render_paths    dict for render.RenderInput.paths of THIS session's folder — a callable
                    `render_paths(kind, step, attempt) -> dict` (driver.render_paths with
                    kind "role"), because each re-call is a new folder.
    cli_version     the CLI version the driver checked at engine start. limits: session
                    limits dict ({"wall_clock_s", "no_output_s"}) or None (session defaults).
    issue_md        text for in/issue.md (plan-gate, done-gate, new comment — re-made for the
                    new-comment call; blocked with kind ambiguous, stage 3 blocked before any developer
                    step — K8-3), else None.
    leader_decision text for in/leader-decision.md (lifecycle.read_leader_decision).
    failure_summary text for in/failure-summary.md (§2.3), else None.
    review_diff     text for in/review.diff (done-gate), else None.
    templates       [{"name", "version", "steps": [ids]}] usable templates (plan-gate; stage 2:
                    feature only), else None.
    decision_marker True when a `<!-- guild:plan-decision -->` block exists (D18; plan-gate, K8-3 blocked).
    referenced_issues [{"number", "state", "state_reason"}] (plan-gate), else None.
    new_comments    [{"id", "author_association", "created_at"}] (new comment), else None.
    issue_cost      the Issue cost so far, leader sessions included (budget.issue_cost).
    soft_acknowledged  the soft-budget rerun was used (budget.check soft_acknowledged).
    origin_template L22: the template name already in a stage-1 state's procedure, else None
                    (then the plan enum is that one template and no new revision is written).

    Stage 3 (None before; shapes = the schemas/leader-input sections of the same name):
    catalog         plan-gate: [{"id", "role", "class", "summary", "usable"}].
    requested_steps plan-gate: the deferred-to-plan requests.
    templates_unusable plan-gate: [{"name", "reasons"}]; `templates` may then be empty.
    plan_role_steps plan-gate: role step ids of the usable templates (union).
    requests        done-gate: state.requests (with outcome / reason).
    included_fixes  done-gate: state.included_fixes.
    followup_candidates done-gate: [{"number", "title", "labels"}].
    deferred_rows   state.deferred_rows (done-gate; the needs_leader situations that offer defer).
    removal, add_limit, pr_review   the section of that situation.
    pr_review_md    pr-review: the text of in/pr-review.md (github.build_pr_review_md).
    bug_issue       readiness E4 (plan-gate): {"evidence": [why it is a bug Issue], "repro_templates": [the
                    usable template names with a repro-red step]} — None when it is not a bug Issue.
    """

    def __init__(self, **fields):
        unknown = set(fields) - set(_REQUEST_FIELDS)
        if unknown:
            raise TypeError(f"unknown LeaderRequest fields {sorted(unknown)}")
        for k in _REQUEST_FIELDS:
            setattr(self, k, fields.get(k))
        if self.situation not in _situations(self.stage):
            raise LeaderError(f"no leader call for situation {self.situation!r}")
        if self.kind not in CALL_KINDS:
            raise LeaderError(f"bad leader call kind {self.kind!r}")


class Allowed:
    """The enums of one call (rendered into the answer schema and leader-input.json).

    answers            leader answers after narrowing, in the §6.3 row order.
    rerun_steps        rerun targets (plan-gate: [defaults.PLAN_GATE_RERUN_TARGET]; done-gate:
                       every role / run step before the done-gate step, analyze included —
                       D7; needs_leader: the stopped step and the role / run steps before it).
                       Empty when rerun is not in `answers`.
    human_answers      the human's row (codes.STAGE2_ALLOWED_ANSWERS, D17 — no narrowing):
                       the choices of recommendation.answer.
    human_rerun_steps  the human's rerun targets (same rule, no rerun-count narrowing).
    narrowed           [(NarrowReason value, (removed answers…))] in codes.NARROWING order. A
                       stage-3 reason that takes away a field instead (codes.NARROWING_FIELDS)
                       has no removed answer.
    models, efforts    stage 3: the values this answer may name ([] = none); None in stage 2.
    """

    def __init__(self, answers, rerun_steps, human_answers, human_rerun_steps, narrowed, models=None, efforts=None):
        self.answers = list(answers)
        self.rerun_steps = list(rerun_steps)
        self.human_answers = list(human_answers)
        self.human_rerun_steps = list(human_rerun_steps)
        self.narrowed = [(r, tuple(a)) for r, a in narrowed]
        if (models is None) != (efforts is None):
            raise ValueError("models and efforts come together")
        self.models = None if models is None else list(models)
        self.efforts = None if efforts is None else list(efforts)
        for a in self.answers + self.human_answers:
            if a not in codes.LeaderAnswer.values():
                raise ValueError(f"unknown answer {a!r}")
        for r, _ in self.narrowed:
            if r not in codes.NarrowReason.values():
                raise ValueError(f"unknown narrow reason {r!r}")

    @property
    def escalate_only(self):
        """D9: True when the leader would have nothing to decide (no call)."""
        return self.answers == [codes.LeaderAnswer.ESCALATE.value]

    def to_json(self):
        narrowed = []
        for r, a in self.narrowed:
            n = {"reason": r, "removed": list(a)}
            if r in codes.NARROWING_FIELDS:
                n["field"] = codes.NARROWING_FIELDS[r]
            narrowed.append(n)
        out = {"answers": self.answers, "rerun_steps": self.rerun_steps,
               "human_answers": self.human_answers, "human_rerun_steps": self.human_rerun_steps,
               "narrowed": narrowed}
        if self.models is not None:
            out.update({"models": self.models, "efforts": self.efforts})
        return out


class LeaderResult:
    """What one call() produced. The caller (session B) applies it; leader never does.

    situation       the request's situation.
    called          False = D9 (escalate only), no session ran; every answer field is None.
    answer          LeaderAnswer value of the accepted answer, or None (failed / stop / quota).
    step            rerun target (answer rerun), else None.
    reason          LeaderReason value, or None.
    note            the leader's note ("" when none) — for leader-decision.md / comments only.
    recommendation  escalate only: {"answer", "step", "note"} (D15), else None.
    extra           the situation fields of the accepted answer (plan-gate: requirements,
                    missing_requirements, plan, close; done-gate: ac_verdicts, discoveries;
                    new comment: comments), a dropped empty list read as []; {} otherwise.
                    Stage 3: plan = {template, adjust, models, new_template_candidate}; done-gate
                    discoveries with title / duplicate_of + included_fixes; the leader-answer-s3
                    situations {defer, session} (+ close, blocked close-as-decided, K8-3); step-removal-request {skip_step}; pr-review
                    {reviews} — a field the call did not render reads as [] / None.
    attempts        sessions spawned by this call (0 when not called; 1 + format re-calls).
    cost_usd        the summed session cost (facts) of those sessions, or None if unknown.
    failed          None, or {"code": "output-format" | "session-limit", "detail": str|None}
                    (D12 → state.stop.leader_failed). detail = a LeaderFormatReason value.
    stop            None, or a mechanical StopReason value (judge-wrote-outside-outputs,
                    control-file, unsafe-path, infra-stop) — needs_human.
    quota_reset_at  epoch seconds of a short quota stop (≤ defaults.INFRA_WAIT_MAX_S): the
                    caller waits and calls again with the same situation (D12). Else None.
    allowed         the Allowed of the (last) session.
    sessions        [attempt or k, …] folder numbers of the sessions, in order.
    input           the leader-input.json object of the last session (None when not called).
    infra           with stop = infra-stop: {"detail": InfraReason value, "reset_at": epoch seconds (a
                    quota reset past the wait limit) or None} — state.stop.detail / reset_at from stage 4
                    (H8). None otherwise.
    Exactly one of {answer, failed, stop, quota_reset_at} is set when called is True.
    """

    def __init__(self, **fields):
        unknown = set(fields) - set(_RESULT_FIELDS)
        if unknown:
            raise TypeError(f"unknown LeaderResult fields {sorted(unknown)}")
        for k in _RESULT_FIELDS:
            setattr(self, k, fields.get(k))
        self.called = bool(self.called)
        self.note = self.note or ""
        self.extra = dict(self.extra or {})
        self.attempts = int(self.attempts or 0)
        self.sessions = list(self.sessions or [])
        outcomes = [self.answer is not None, self.failed is not None, self.stop is not None,
                    self.quota_reset_at is not None]
        if self.called and sum(outcomes) != 1:
            raise ValueError("a called LeaderResult carries exactly one of answer / failed / stop / quota_reset_at")
        if not self.called and any(outcomes):
            raise ValueError("an uncalled LeaderResult (D9) carries no outcome")
        if self.answer is not None and self.answer not in codes.LeaderAnswer.values():
            raise ValueError(f"unknown answer {self.answer!r}")
        if self.reason is not None and self.reason not in codes.LeaderReason.values():
            raise ValueError(f"unknown reason {self.reason!r}")
        if self.failed is not None and self.failed.get("code") not in codes.LEADER_FAILED_CODES:
            raise ValueError(f"bad failed code {self.failed!r}")
        if self.stop is not None and self.stop not in codes.StopReason.values():
            raise ValueError(f"unknown stop {self.stop!r}")
        if self.infra is not None and (self.stop != SR.INFRA_STOP.value or set(self.infra) != {"detail", "reset_at"}
                                       or self.infra["detail"] not in codes.STOP_DETAILS):
            raise ValueError(f"bad infra {self.infra!r} (only with stop infra-stop)")

    def __repr__(self):
        return (f"LeaderResult(situation={self.situation!r}, called={self.called}, answer={self.answer!r}, "
                f"step={self.step!r}, failed={self.failed!r}, stop={self.stop!r})")


# --- pure parts (V2) ------------------------------------------------------------------------

def rerun_targets(situation, state, procedure, step, *, human=False, stage=2):
    """Rerun target step ids of `situation` (see Allowed.rerun_steps), in procedure order.

    `step` is the request's step. Check / op steps are never targets; plan is never a done-gate
    target (that is replan). `human` gives the human's list (no count narrowing).

    The list itself never depends on counters, so `human` returns the same list; the leader's
    rerun-count narrowing happens in allowed_answers. Exception to "check / op never": for
    soft-budget and new-collaborator-comment `step` is the NEXT step to run and is itself a
    target whatever its kind (rerun of it = go on from it, the stage-1 soft-budget meaning)."""
    if situation not in _situations(stage):
        raise ValueError(f"no leader rerun targets for situation {situation!r}")
    kinds = {s.id: s.kind for s in procedure.steps}
    order = [s.id for s in procedure.steps]
    if situation == SR.PLAN_GATE.value:
        t = defaults.PLAN_GATE_RERUN_TARGET
        return [t] if kinds.get(t) in _RERUNNABLE else []
    if step not in kinds:
        raise ValueError(f"step {step!r} is not in the procedure")
    before = [s for s in order[:order.index(step)] if kinds[s] in _RERUNNABLE]
    if situation == SR.DONE_GATE.value:
        return before
    if situation in _NEXT_STEP_SITUATIONS:
        return before + [step]
    return before + ([step] if kinds[step] in _RERUNNABLE else [])


def allowed_answers(situation, state, procedure, step, *, mode, analysis=None, decision_marker=False,
                    soft_acknowledged=False, origin_template=None, stage=2, templates=None, models=(),
                    efforts=(), skippable_steps=None, close_risk=False, bug_issue=None):
    """The Allowed of one call — a pure function of its arguments (table test: every cell).

    `analysis` = acparse.parse_analysis(...) for plan-gate (its type / split /
    prerequisite_open / risk fields drive TYPE_NOT_FEATURE, SPLIT_PROPOSED,
    PREREQUISITE_OPEN, RISK_HIGH — the acparse PLAN_REASON_* codes are the same strings).
    Counters come from state: counters.plan_rerun / done_rerun vs defaults.*_RERUN_MAX,
    steps[].on_fail_extra (ON_FAIL_RERUN_USED), `soft_acknowledged`, plan step done (PLAN_NOT_DONE).
    UNATTENDED_NO_DECISION applies when mode is unattended and not decision_marker.
    An empty rerun target list applies NO_RERUN_TARGET. Never narrows the human lists (D17).
    Raises ValueError for a situation outside the stage's answer schemas or stage < 2.

    Stage 3 (codes.STAGE3_ALLOWED_ANSWERS): plan-gate reads `templates` (the usable ones of the
    request) against the analysis row (E2) instead of TYPE_NOT_FEATURE; `models` / `efforts` are
    the repository's allow-lists (E29), offered only where the answer can use them;
    step-removal-request loses `skip` when `skippable_steps` (catalog.skippable_steps) is empty.
    blocked (K8-3) has `close-as-decided` only while no developer step has run (statemachine.
    close_allowed — the human's row too), not with `close_risk` (_close_risk), and unattended only
    with a decision marker (D18).
    Readiness E4 (rule 1): plan-gate loses `plan` when `bug_issue` is given (a bug Issue — history.bug_evidence)
    in a defaults.BUG_GUARD_MODES mode and none of the templates the analysis row offers is in
    `bug_issue["repro_templates"]` (BUG_WITHOUT_REPRO): rerun analyze and escalate stay.

    `narrowed` lists every rule that applies with the answers of the leader's row it removes
    (two rules may name the same answer — both are listed); a rule that removes nothing of the
    row is not listed (a field rule, codes.NARROWING_FIELDS, is). `origin_template` does not narrow answers (it narrows the plan-gate
    template enum — see call / check_answer); it is accepted for the contract signature.
    """
    if isinstance(stage, bool) or not isinstance(stage, int) or stage < 2:
        raise ValueError(f"leader answers exist from stage 2 (got stage {stage!r})")
    if situation not in _situations(stage):
        raise ValueError(f"no leader call for situation {situation!r}")
    if mode not in codes.RunMode.values():
        raise ValueError(f"unknown run mode {mode!r}")
    row = list(codes.allowed_answers_table(stage)[situation])
    static = set(codes.LEADER_REMOVED_ANSWERS.get(situation, ()))
    leader_row = [a for a in row if a not in static]
    targets = rerun_targets(situation, state, procedure, step, stage=stage)
    applies = _narrow_conditions(situation, state, procedure, mode, analysis, decision_marker,
                                 soft_acknowledged, targets)
    if stage >= 3:
        applies = _narrow_conditions_s3(applies, situation, state, analysis, templates, origin_template,
                                        skippable_steps)
        if situation == SR.PLAN_GATE.value and bug_blocks_plan(
                bug_issue, mode, _row_templates(analysis, templates, origin_template)):
            applies.add(codes.NarrowReason.BUG_WITHOUT_REPRO.value)
        if situation == SR.BLOCKED.value:
            N = codes.NarrowReason
            for reason, holds in ((N.UNATTENDED_NO_DECISION, mode == codes.RunMode.UNATTENDED.value and not decision_marker),
                                  (N.DEVELOPER_STARTED, not statemachine.close_allowed(state)), (N.CLOSE_RISK, close_risk)):
                if holds:
                    applies.add(reason.value)
    narrowed, drop = [], set()
    for reason, removes in codes.NARROWING.items():
        if reason not in applies:
            continue
        if situation not in codes.NARROWING_SITUATIONS[reason]:
            raise ValueError(f"narrowing {reason!r} does not apply to {situation!r}")
        gone = [a for a in leader_row if a in removes]
        if gone or reason in codes.NARROWING_FIELDS:
            narrowed.append((reason, gone))
            drop.update(gone)
    answers = [a for a in leader_row if a not in drop]
    if A.REPLAN.value not in answers:            # no replan, no defer field to take away
        narrowed = [(n, g) for n, g in narrowed if n != codes.NarrowReason.DEFER_USED.value]
    if situation == SR.BLOCKED.value and not statemachine.close_allowed(state):
        row = [a for a in row if a != A.CLOSE_AS_DECIDED.value]       # K8-3: structural, both seats (lifecycle)
    human_targets = rerun_targets(situation, state, procedure, step, human=True, stage=stage)
    fields = {}
    if stage >= 3:
        offered = _session_offered(situation, answers, origin_template)
        fields = {"models": models if offered else (), "efforts": efforts if offered else ()}
    return Allowed(answers,
                   targets if A.RERUN.value in answers else [],
                   row,
                   human_targets if A.RERUN.value in row else [],
                   narrowed, **fields)


def bug_blocks_plan(bug_issue, mode, offered):
    """Readiness E4 rule 1 (#1910): True when a plan of the `offered` templates ([{"name", …}] or names) would
    take a bug Issue onto a template without repro-red — the leader may not choose it (a human may)."""
    if not bug_issue or not bug_issue.get("evidence") or mode not in defaults.BUG_GUARD_MODES or not offered:
        return False
    names = [t["name"] if isinstance(t, dict) else t for t in offered]
    return not set(names) & set(bug_issue.get("repro_templates") or ())


def _session_offered(situation, answers, origin_template):
    """May this stage-3 answer name a model / effort? plan-gate `plan.models` (layer 4) — not for an
    Issue that already runs its template (L22: no new revision, so no adjusting either) — and the
    `session` of a needs_leader rerun (layer 5, E28)."""
    if situation == SR.PLAN_GATE.value:
        return A.PLAN.value in answers and origin_template is None
    return codes.STAGE3_LEADER_ANSWER_SCHEMAS[situation] == _S3_ENVELOPE and A.RERUN.value in answers


def _row_templates(analysis, templates, origin_template=None):
    """Stage 3 (E2): the usable templates this analysis may choose — the TYPE_TEMPLATES row of its
    type / safety_net, and only the Issue's own template when it already runs one (L22)."""
    if not isinstance(analysis, dict) or "safety_net" not in analysis:
        raise ValueError("stage 3 plan-gate needs the analysis safety_net field (acparse.parse_analysis stage 3)")
    if templates is None:
        raise ValueError("stage 3 plan-gate needs the usable templates ([] when there is none)")
    row = codes.templates_for(analysis["type"], analysis["safety_net"])
    return [t for t in templates if t["name"] in row and origin_template in (None, t["name"])]


def _counter(state, name):
    v = (state.get("counters") or {}).get(name, 0)
    if isinstance(v, bool) or not isinstance(v, int) or v < 0:
        raise ValueError(f"state counters.{name} is not a count: {v!r}")
    return v


def _step_status(state, step_id):
    for s in state.get("steps") or ():
        if s.get("id") == step_id:
            return s.get("status")
    return None


def _narrow_conditions(situation, state, procedure, mode, analysis, decision_marker, soft_acknowledged,
                       targets):
    """The NarrowReason values whose condition holds (scope D3, D4 conservative, D7, D8, D14, D18)."""
    N = codes.NarrowReason
    out = set()
    if situation == SR.PLAN_GATE.value:
        if not isinstance(analysis, dict):
            raise ValueError("plan-gate narrowing needs the parsed analysis (acparse.parse_analysis)")
        # the I1 codes ARE the NarrowReason values (type / split / prerequisite / risk — D4)
        out.update(acparse.plan_rule_reasons(analysis))
        if mode == codes.RunMode.UNATTENDED.value and not decision_marker:
            out.add(N.UNATTENDED_NO_DECISION.value)
        if _counter(state, "plan_rerun") >= defaults.PLAN_GATE_RERUN_MAX:
            out.add(N.PLAN_RERUN_USED.value)
    if situation == SR.DONE_GATE.value and _counter(state, "done_rerun") >= defaults.DONE_GATE_RERUN_MAX:
        out.add(N.DONE_RERUN_USED.value)
    if situation == SR.ON_FAIL_EXCEEDED.value and any(
            s.get("on_fail_extra", 0) for s in state.get("steps") or ()):
        out.add(N.ON_FAIL_RERUN_USED.value)
    if situation == SR.SOFT_BUDGET.value and soft_acknowledged:
        out.add(N.SOFT_BUDGET_RERUN_USED.value)
    if situation in codes.NARROWING_SITUATIONS[N.PLAN_NOT_DONE.value] and \
            _step_status(state, defaults.REPLAN_TARGET) != codes.StepStatus.DONE.value:
        out.add(N.PLAN_NOT_DONE.value)
    if situation in codes.NARROWING_SITUATIONS[N.NO_RERUN_TARGET.value] and not targets:
        out.add(N.NO_RERUN_TARGET.value)
    unknown = out - set(codes.NarrowReason.values())
    if unknown:
        raise ValueError(f"unknown narrowing codes {sorted(unknown)}")
    return out


def _narrow_conditions_s3(out, situation, state, analysis, templates, origin_template, skippable_steps):
    """`out` (the stage-2 conditions) with the stage-3 rules added (scope §2.1, §2.4, §2.5)."""
    N = codes.NarrowReason
    out = set(out)
    if situation == SR.PLAN_GATE.value:
        out.discard(N.TYPE_NOT_FEATURE.value)            # E2 replaces it
        usable = _row_templates(analysis, templates, origin_template)
        if not codes.templates_for(analysis["type"], analysis["safety_net"]):
            out.add(N.NO_TEMPLATE_FOR_TYPE.value)
        elif not usable:
            out.add(N.TEMPLATE_UNUSABLE.value)
    elif situation == SR.STEP_REMOVAL_REQUEST.value:
        if skippable_steps is None:
            raise ValueError("step-removal-request needs the skippable steps ([] when there is none)")
        if not skippable_steps:
            out.add(N.NO_SKIPPABLE_STEP.value)
    elif situation == SR.DONE_GATE.value and _followups_used(state) >= defaults.FOLLOWUPS_MAX:
        out.add(N.FOLLOWUP_CAP.value)
    if situation in codes.NARROWING_SITUATIONS[N.DEFER_USED.value] and _defer_used(state):
        out.add(N.DEFER_USED.value)
    return out


def _defer_used(state):
    """E30: the Issue's defer is spent (state keeps the deferred rows, not a count; DEFER_MAX is 1)."""
    return int(bool(state.get("deferred_rows"))) >= defaults.DEFER_MAX


def _recommendable(situation, allowed):
    """recommendation.answer choices: the human's row minus what a recommendation cannot carry."""
    gone = codes.RECOMMENDATION_REMOVED_ANSWERS.get(situation, ())
    return [a for a in allowed.human_answers if a not in gone]


def render_answer_schema(situation, allowed, ids=None, *, stage=2):
    """The --json-schema object of one call: the situation's template filled by schema.fill_enums.

    `ids` holds the situation's id lists: {"requirement_rows": ["R1", …], "templates": [names]}
    (plan-gate), {"ac_ids": [ints], "discovery_ids": ["D1", …]} (done-gate),
    {"comment_ids": [ints]} (new comment). Stage 3: every other codes.LEADER_SCHEMA_TOKENS token of
    the stage-3 template too. render.CLI_SCHEMA_DROP keys are dropped by render.
    Missing or unknown id lists → ValueError; fill_enums' own rules raise schema.SchemaError.
    """
    if situation not in _situations(stage):
        raise ValueError(f"no leader answer schema for situation {situation!r}")
    template = schema.load_schema(_situations(stage)[situation])
    values = {"{answers}": list(allowed.answers), "{rerun_steps}": list(allowed.rerun_steps),
              "{human_answers}": _recommendable(situation, allowed),
              "{human_rerun_steps}": list(allowed.human_rerun_steps)}
    ids = dict(ids or {})
    need = {t[1:-1] for t in schema.schema_tokens(template)} - {t[1:-1] for t in values}
    if set(ids) != need:
        raise ValueError(f"{situation}: id lists {sorted(need)} are needed, got {sorted(ids)}")
    for name, vals in ids.items():
        values["{" + name + "}"] = list(vals)
    return schema.fill_enums(template, values)


def check_answer(situation, answer, allowed, ids=None, *, checklist_acs=None, origin_template=None, stage=2,
                 inp=None, followups_made=()):
    """Check a structured answer; return [(LeaderFormatReason value, detail text)] (empty = ok).

    Order: lone surrogates (D9) and the rendered schema (ANSWER_SCHEMA, stop there) → the combination rules
    (RERUN_STEP_MISMATCH, ESCALATE_RECOMMENDATION_MISMATCH; any other answer needs step and
    recommendation null) → the situation rules (D5 plan-gate, D6 done-gate with
    `checklist_acs` = the AC ids manual-test-checklist.md references (acparse), D16 new
    comment, L22 `origin_template`). Free-text fields are never inspected (L20).

    `ids` as for render_answer_schema (the schema is rendered from it again here, so the check
    is exactly the schema the session got). The combination rule also binds the
    recommendation: its answer rerun ⇔ its step ≠ null. `checklist_acs` None (no readable
    checklist) means no AC is referenced — every `manual` verdict fails (fail-closed).

    Stage 3 adds the rules of the stage-3 fields, checked against `inp` — the leader-input.json
    object of the call (required from stage 3), so the rules use exactly the facts the leader saw.
    `followups_made`: the discovery ids this Issue already made a follow-up of (_followup_ids) —
    a PR re-entry judges them again and they do not count twice against FOLLOWUPS_MAX.
    """
    F = codes.LeaderFormatReason
    if _stage3(stage) and not isinstance(inp, dict):
        raise ValueError("a stage-3 answer is checked against its leader-input.json object")
    if answer is None:
        return [(F.NO_STRUCTURED_OUTPUT.value, "the session returned no structured output")]
    bad = schema.surrogate_errors(answer)            # D9: text that is no valid Unicode can go nowhere
    if bad:
        return [(F.ANSWER_SCHEMA.value, e) for e in bad[:_ERRORS_MAX]]
    rendered = render_answer_schema(situation, allowed, ids, stage=stage)
    errs = schema.errors(answer, rendered)
    if errs:
        return [(F.ANSWER_SCHEMA.value, e) for e in errs[:_ERRORS_MAX]]
    out = []
    a = answer["answer"]
    if (a == A.RERUN.value) != (answer["step"] is not None):
        out.append((F.RERUN_STEP_MISMATCH.value, f"answer {a!r} with step {answer['step']!r}: "
                    "step is set exactly when the answer is rerun"))
    rec = answer["recommendation"]
    if (a == A.ESCALATE.value) != (rec is not None):
        out.append((F.ESCALATE_RECOMMENDATION_MISMATCH.value, f"answer {a!r}: recommendation is set "
                    "exactly when the answer is escalate"))
    if rec is not None and (rec["answer"] == A.RERUN.value) != (rec["step"] is not None):
        out.append((F.RERUN_STEP_MISMATCH.value, f"recommendation {rec['answer']!r} with step "
                    f"{rec['step']!r}: step is set exactly when the recommended answer is rerun"))
    if situation == SR.STEP_REMOVAL_REQUEST.value and (a == A.SKIP.value) != (answer["skip_step"] is not None):
        out.append((F.SKIP_STEP_MISMATCH.value, f"answer {a!r} with skip_step {answer['skip_step']!r}: "
                    "skip_step is set exactly when the answer is skip"))
    if _stage3(stage) and _situations(stage)[situation] == _S3_ENVELOPE:
        out += _session_rules(answer, inp) + _defer_rules(answer, inp)
        if (a == A.CLOSE_AS_DECIDED.value) != (answer.get("close") is not None):       # K8-3 (blocked)
            out.append((F.CLOSE_MISMATCH.value, "close is set exactly when the answer is close-as-decided"))
    ids = dict(ids or {})
    if situation == SR.PLAN_GATE.value:
        out += _covering(F.REQUIREMENTS_NOT_COVERING.value, "requirement row",
                         [r["row"] for r in answer["requirements"]], ids["requirement_rows"])
        if a == A.PLAN.value and (any(not r["covered"] for r in answer["requirements"])
                                  or answer["missing_requirements"]):
            out.append((F.PLAN_WITH_GAP.value, f"plan with {sum(not r['covered'] for r in answer['requirements'])} "
                        f"uncovered row(s) and {len(answer['missing_requirements'])} missing requirement(s): "
                        "a gap goes back to analyze (rerun) or to a human (escalate)"))
        plan = answer.get("plan")                   # dropped from the schema when there is no template
        if (a == A.PLAN.value) != (plan is not None):
            out.append((F.PLAN_MISMATCH.value, "plan is set exactly when the answer is plan"))
        if (a == A.CLOSE_AS_DECIDED.value) != (answer["close"] is not None):
            out.append((F.CLOSE_MISMATCH.value, "close is set exactly when the answer is close-as-decided"))
        if origin_template is not None and plan is not None and plan["template"] != origin_template:
            out.append((F.TEMPLATE_MISMATCH.value, f"this Issue already runs template {origin_template!r}"))
        if _stage3(stage) and plan is not None:
            out += _plan_rules(plan, inp)
    elif situation == SR.DONE_GATE.value:
        verdicts = answer["ac_verdicts"]
        disc = answer.get("discoveries", [])        # dropped from the schema when there is none
        out += _covering(F.AC_NOT_COVERING.value, "AC", [v["ac"] for v in verdicts], ids["ac_ids"])
        out += _covering(F.DISCOVERIES_NOT_COVERING.value, "discovery", [d["id"] for d in disc],
                         ids["discovery_ids"])
        if _stage3(stage):
            out += _manual_reason_rules(verdicts)
            out += _summary_rules(answer.get("summary"), a)
            out += _disposition_rules(disc, inp, followups_made)
            fixes = answer.get("included_fixes", [])
            out += _covering(F.FIXES_NOT_COVERING.value, "included fix", [x["id"] for x in fixes], ids["fix_ids"])
            foreign = [x["id"] for x in fixes if x["verdict"] == codes.FixVerdict.OUT_OF_SCOPE.value]
            if a == A.APPROVE.value and foreign:
                out.append((F.APPROVE_WITH_OUT_OF_SCOPE.value, f"approve with out-of-scope fixes {foreign}: rerun the "
                            "developer step to take them out, or escalate"))
        if a == A.APPROVE.value:
            unmet = [v["ac"] for v in verdicts if v["status"] == codes.AcVerdict.UNMET.value]
            if unmet:
                out.append((F.APPROVE_WITH_UNMET.value, "approve with unmet AC " + _ac_list(unmet)))
            inc = [d["id"] for d in disc if d["disposition"] == codes.DiscoveryDisposition.INCLUDE.value]
            if inc:
                out.append((F.APPROVE_WITH_INCLUDE.value, f"approve with discoveries to include {inc}: "
                            "a fix for this PR is `rerun implement`"))
            listed = set(checklist_acs or ())
            manual = [v["ac"] for v in verdicts if v["status"] == codes.AcVerdict.MANUAL.value
                      and v["ac"] not in listed]
            if manual:
                out.append((F.MANUAL_NOT_IN_CHECKLIST.value, "manual AC " + _ac_list(manual)
                            + " not referenced by the Manual Test Checklist"))
    elif situation == SR.NEW_COMMENT.value:
        comments = answer["comments"]
        out += _covering(F.COMMENTS_NOT_COVERING.value, "comment", [c["id"] for c in comments],
                         ids["comment_ids"])
        effects = {c["effect"] for c in comments}
        if a == A.CONTINUE.value and effects - {codes.CommentEffect.NONE.value}:
            out.append((F.CONTINUE_WITH_EFFECT.value, "continue although a comment has an effect"))
        if a == A.RERUN.value and codes.CommentEffect.ADDS_REQUIREMENT.value in effects \
                and answer["step"] != defaults.PLAN_GATE_RERUN_TARGET:
            out.append((F.ADDS_REQUIREMENT_NOT_ANALYZE.value, f"a comment adds a requirement: rerun "
                        f"{defaults.PLAN_GATE_RERUN_TARGET}, not {answer['step']!r}"))
    elif situation == SR.PR_REVIEW.value:
        reviews = answer.get("reviews", [])         # dropped when only commits are new (fast-forward)
        out += _covering(F.REVIEWS_NOT_COVERING.value, "review item", [x["id"] for x in reviews], ids["review_ids"])
        asked = [x["id"] for x in reviews if x["effect"] == codes.ReviewEffect.CHANGE_REQUEST.value]
        if a == A.CONTINUE.value and asked:
            out.append((F.CONTINUE_WITH_CHANGE_REQUEST.value, f"continue although {asked} asks for a change"))
    return out


def manual_reason_problems(verdicts):
    """E5: the AC ids whose `why_not_automated` breaks "set (not blank) exactly when status is manual" — a
    `manual` verdict without a reason, or a reason on a `met` / `unmet` one. Presence only: the reason is free
    text the engine never reads (L20); whether the design proposed an automated check, and whether the reason
    holds, is the leader's judgement (tasks/leader-stage3/done-gate.md)."""
    bad = []
    for v in verdicts or ():
        if not isinstance(v, dict):
            continue
        why = v.get("why_not_automated")
        filled = isinstance(why, str) and bool(why.strip())
        if (v.get("status") == codes.AcVerdict.MANUAL.value) != filled:
            bad.append(v.get("ac"))
    return bad


def _manual_reason_rules(verdicts):
    bad = manual_reason_problems(verdicts)
    if not bad:
        return []
    return [(codes.LeaderFormatReason.MANUAL_REASON_MISMATCH.value, f"why_not_automated of AC {bad}: set (not blank) "
             "exactly when the status is manual — say why no automated check proves it, and why a check the design "
             "documents proposed was not taken; null for met / unmet")]


def _summary_rules(summary, answer):
    """The done-gate `summary` (the top of a stage-4 PR body): at most PR_SUMMARY_LINES_MAX lines, none blank, and at
    least one for an approve. Its words are free text the engine never reads (L20)."""
    lines = list(summary or ())
    most = defaults.PR_SUMMARY_LINES_MAX
    if len(lines) <= most and all(isinstance(x, str) and x.strip() for x in lines) \
            and (lines or answer != A.APPROVE.value):
        return []
    return [(codes.LeaderFormatReason.SUMMARY_INVALID.value, f"summary has {len(lines)} line(s): 1 to {most} lines, "
             f"none blank, are needed for {answer!r} (at most {most} for any answer)")]


def _twice(items):
    return sorted({i for i in items if items.count(i) > 1})


def _plan_rules(plan, inp):
    """E12: what the plan schema cannot say about `adjust` and `models`."""
    F = codes.LeaderFormatReason
    out = []
    name = plan["template"]
    steps = [s for t in inp["plan_gate"]["templates"] if t["name"] == name for s in t["steps"]]
    adds = [a["step"] for a in plan.get("adjust", [])]
    if _twice(adds):
        out.append((F.ADJUST_INVALID.value, f"adjust adds step(s) more than once: {_twice(adds)}"))
    there = sorted(set(adds) & set(steps))
    if there:
        out.append((F.ADJUST_INVALID.value, f"template {name!r} already has step(s) {there}"))
    used, most = inp["counters"]["catalog_adds"], inp["counters"]["catalog_adds_max"]
    if adds and used + len(adds) > most:
        out.append((F.ADJUST_INVALID.value, f"adjust adds {len(adds)} step(s); {used} of at most {most} "
                    "catalog steps are already used"))
    named = [m["step"] for m in plan.get("models", [])]
    if _twice(named):
        out.append((F.MODELS_INVALID.value, f"models names step(s) more than once: {_twice(named)}"))
    foreign = sorted(set(named) - set(steps))
    if foreign:
        out.append((F.MODELS_INVALID.value, f"models names step(s) {foreign}, which template {name!r} does not have"))
    return out


def _disposition_rules(disc, inp, made):
    """E19: what the schema cannot say about the dispositions."""
    F, D = codes.LeaderFormatReason, codes.DiscoveryDisposition
    out = []
    follow = [d for d in disc if d["disposition"] == D.FOLLOWUP.value]
    bad = [d["id"] for d in disc if (d["disposition"] == D.FOLLOWUP.value) != (d["title"] is not None)]
    bad += [d["id"] for d in follow if d["title"] is not None and not d["title"].strip()]      # GitHub needs a title
    if bad:
        out.append((F.FOLLOWUP_TITLE_MISMATCH.value, f"{bad}: title is set exactly when the disposition is followup"))
    bad = [d["id"] for d in disc if (d["disposition"] == D.DUPLICATE.value) != (d["duplicate_of"] is not None)]
    if bad:
        out.append((F.DUPLICATE_MISMATCH.value, f"{bad}: duplicate_of is set exactly when the disposition is duplicate"))
    used, most = inp["counters"]["followups"], inp["counters"]["followups_max"]
    new = {d["id"] for d in follow} - set(made)
    if new and used + len(new) > most:
        out.append((F.FOLLOWUP_OVER_CAP.value, f"{len(new)} new follow-up(s); {used} of at most {most} per Issue are "
                    "already made: make the others ignore or duplicate"))
    return out


_SESSION_REASONS = (codes.LeaderReason.HIGH_COMPLEXITY.value, codes.LeaderReason.REPEATED_FAILURE.value,
                    codes.LeaderReason.OTHER.value)


def _session_rules(answer, inp):
    """E28 (layer 5): `session` only with rerun of a role step (a run has no model), for a model reason."""
    code = codes.LeaderFormatReason.MODELS_INVALID.value
    if answer.get("session") is None:
        return []
    if answer["answer"] != A.RERUN.value:
        return [(code, f"session with answer {answer['answer']!r}: it belongs to rerun")]
    out = []
    if answer["reason"] not in _SESSION_REASONS:
        out.append((code, f"session with reason {answer['reason']!r}: one of {', '.join(_SESSION_REASONS)}"))
    kinds = {x["id"]: x["kind"] for x in inp["steps"]}
    if answer["step"] is not None and kinds.get(answer["step"]) != _ROLE:
        out.append((code, f"session for step {answer['step']!r}, which is no role step"))
    return out


def _defer_rules(answer, inp):
    """E30: `defer` only with replan, at least one row, each once, never every row."""
    code, rows = codes.LeaderFormatReason.DEFER_INVALID.value, answer.get("defer")
    if rows is None:
        return []
    out = []
    if answer["answer"] != A.REPLAN.value:
        out.append((code, f"defer with answer {answer['answer']!r}: it belongs to replan (otherwise null)"))
    if not rows:
        out.append((code, "defer names no row: use null to defer nothing"))
    if _twice(rows):
        out.append((code, f"defer names row(s) more than once: {_twice(rows)}"))
    if not {x["row"] for x in inp["defer"]["requirement_rows"]} - set(rows):
        out.append((code, "defer names every row: that is close-as-decided or a human's decision (escalate)"))
    return out


def _ac_list(ids):
    return ", ".join(f"#{n}" for n in ids)


def _covering(code, what, got, want):
    """Each id of `want` exactly once in `got` (schema enums already exclude unknown ids)."""
    counts = {}
    for g in got:
        counts[g] = counts.get(g, 0) + 1
    missing = [w for w in want if w not in counts]
    twice = [g for g, n in counts.items() if n > 1]
    extra = [g for g in counts if g not in set(want)]
    if not (missing or twice or extra):
        return []
    parts = []
    if missing:
        parts.append(f"missing {what}(s) {missing}")
    if twice:
        parts.append(f"{what}(s) more than once {twice}")
    if extra:
        parts.append(f"unknown {what}(s) {extra}")
    return [(code, "; ".join(parts) + f" — answer every {what} exactly once")]


def build_input(request, allowed, call_attempt, format_retry=0, errors=()):
    """The leader-input.json object (schemas/leader-input) of one session — V3.

    Collected mechanically from request.state / procedure, the attempt facts and results in
    request.paths and acparse. R / D ids are stable within the Issue. Free text is cut at
    defaults.LEADER_INPUT_TEXT_MAX with defaults.LEADER_INPUT_TRUNCATION_MARK. A judgment fact
    that cannot be collected (AC list, requirement map, step table, run exit codes) raises
    facts.FactMissing — the caller stops infra (fact-collection) and does not call (§9.3).

    `errors`: the rejected previous answer's [(LeaderFormatReason value, detail)] (or lines).
    A driver fact the situation needs and the request lacks → LeaderError; the object is
    validated against schemas/leader-input (failure → LeaderError, an engine bug).
    """
    r = request
    _check_request(r)
    if isinstance(call_attempt, bool) or not isinstance(call_attempt, int) or call_attempt < 1:
        raise ValueError(f"bad call attempt {call_attempt!r}")
    if isinstance(format_retry, bool) or not isinstance(format_retry, int) or format_retry < 0:
        raise ValueError(f"bad format retry {format_retry!r}")
    sit = r.situation
    ctx = r.ctx
    head = _fact("head", gitops.head, ctx)
    analysis = _analysis_at(r, head, required=sit in (SR.PLAN_GATE.value, SR.DONE_GATE.value))
    prior = list(_prior_inputs(r.paths))
    stopped = _stopped_section(r) if sit in _STOPPED_SITUATIONS else None
    names = _in_file_names(r, stopped)
    _in_texts(r, names)                        # every needed driver text is there (LeaderError)
    obj = {
        "format": defaults.FORMAT,
        "issue": r.paths.issue,
        "stage": r.stage,
        "situation": sit,
        "call": {"kind": r.kind, "step": r.step, "attempt": call_attempt, "format_retry": format_retry,
                 "errors": [_clip(_error_line(e)) for e in errors][:_ERRORS_MAX]},
        "mode": r.mode,
        "allowed": allowed.to_json(),
        "docs": _docs(r, head, stopped),
        "in_files": names,
        "steps": _step_table(r),
        "counters": _counters(r),
        "cost": _cost(r),
        "plan_gate": None, "done_gate": None, "stopped": stopped, "budget": None, "comments": None,
    }
    if r.stage >= 3:
        obj.update({"defer": None, "removal": None, "add_limit": None, "pr_review": None})
        if _situations(r.stage)[sit] == _S3_ENVELOPE:
            obj["defer"] = _defer_section(r, allowed, analysis, prior)
    if sit == SR.PLAN_GATE.value:
        fields = ("type", "size", "risk", "split", "prerequisite_open") + (("safety_net",) if r.stage >= 3 else ())
        obj["plan_gate"] = {
            "analysis": {k: analysis[k] for k in fields},
            "acs": list(analysis["acs"]),
            "requirement_rows": _requirement_rows(analysis, prior),
            "assumptions": [_clip(a) for a in analysis.get("assumptions") or []],
            "referenced_issues": _referenced(r),
            "templates": _templates(r, analysis),
            "decision_marker": bool(r.decision_marker),
        }
        if r.stage >= 3:
            obj["plan_gate"].update(_plan_gate_s3(r))
    elif sit == SR.DONE_GATE.value:
        obj["done_gate"] = _done_gate_section(r, head, analysis, prior)
    elif sit == SR.SOFT_BUDGET.value:
        obj["budget"] = _budget_section(r)
    elif sit == SR.NEW_COMMENT.value:
        obj["comments"] = _comments_section(r, analysis)
    elif sit == SR.STEP_REMOVAL_REQUEST.value:
        obj["removal"] = _removal_section(r)
    elif sit == SR.STEP_ADD_LIMIT.value:
        obj["add_limit"] = _add_limit_section(r)
    elif sit == SR.PR_REVIEW.value:
        obj["pr_review"] = _pr_review_section(r)
    try:
        schema.validate(obj, "leader-input")
    except schema.ValidationError as e:
        raise LeaderError(f"leader-input.json does not match its schema: {e}") from None
    return obj


# --- leader-input.json pieces (V3) ------------------------------------------------------------

_CHECK_SITUATIONS = (SR.PLAN_GATE.value, SR.DONE_GATE.value)


def _check_request(r):
    """Fail-closed request shape: stage ≥ 2, a known mode, the step in the procedure, and kind
    check exactly for plan-gate / done-gate on a step `check: <that situation>` (LeaderError)."""
    if isinstance(r.stage, bool) or not isinstance(r.stage, int) or r.stage < 2:
        raise LeaderError(f"no leader before stage 2 (stage {r.stage!r})")
    if r.mode not in codes.RunMode.values():
        raise LeaderError(f"unknown run mode {r.mode!r}")
    if r.step not in r.procedure.step_ids:
        raise LeaderError(f"step {r.step!r} is not in the procedure")
    check = r.situation in _CHECK_SITUATIONS
    if check != (r.kind == codes.AttemptKind.CHECK.value):
        raise LeaderError(f"situation {r.situation!r} is called with kind "
                          f"{'check' if check else 'leader'}, not {r.kind!r}")
    if check:
        p = r.procedure.step(r.step)
        if p.kind != codes.StepKind.CHECK.value or p.name != r.situation:
            raise LeaderError(f"step {r.step!r} is not a `check: {r.situation}` step")

def _need(r, name):
    """A stage-3 driver fact of the request (None = the driver did not collect it → LeaderError)."""
    value = getattr(r, name)
    if value is None:
        raise LeaderError(f"{r.situation}: the request has no {name}")
    return value


def _plan_gate_s3(r):
    """Stage 3 (E2, E12, E15-1): the plan-gate facts about steps and templates."""
    return {
        "requested_steps": [{"from_step": q["from_step"], "step": q["step"], "trigger": q["trigger"],
                             "note": _clip(q["note"])} for q in _need(r, "requested_steps")],
        "catalog": [{"id": c["id"], "role": c["role"], "class": c["class"], "summary": _clip(c["summary"]),
                     "usable": bool(c["usable"])} for c in _need(r, "catalog")],
        "templates_unusable": [{"name": t["name"], "reasons": [_clip(x) for x in t["reasons"]]}
                               for t in _need(r, "templates_unusable")],
    }


def _removal_section(r):
    """Stage 3 (E13). Only a step the catalog added outside the mandatory rules, not done yet and named
    by one of the requests may be skipped (§7: nobody lifts a rule) — anything else in the
    driver's list is a caller bug."""
    q = _need(r, "removal")
    skippable = list(q["skippable_steps"])
    named = {x["step"] for x in q["requests"]}
    added = {a["step"] for a in r.state.get("catalog_adds") or []
             if a["source"] != codes.ProcedureSource.MANDATORY_RULE.value}
    bad = [s for s in skippable if s not in named or s not in added or s not in r.procedure.step_ids
           or _step_status(r.state, s) == codes.StepStatus.DONE.value]
    if bad:
        raise LeaderError(f"step-removal-request: step(s) {bad} cannot be skipped")
    return {"from_step": q["from_step"], "skippable_steps": skippable,
            "requests": [{"op": x["op"], "step": x["step"], "trigger": x["trigger"], "note": _clip(x["note"])}
                         for x in q["requests"]]}


def _add_limit_section(r):
    """Stage 3 (E15-5): the requests over the limit."""
    q = _need(r, "add_limit")
    return {"from_step": q["from_step"], "limit": q["limit"], "used": q["used"],
            "requests": [{"step": x["step"], "trigger": x["trigger"], "note": _clip(x["note"]),
                          "summary": _clip(x["summary"])} for x in q["requests"]]}


def _deferred_rows(r):
    """Stage 3 (E30): state.deferred_rows as the input shows them."""
    rows = r.deferred_rows if r.deferred_rows is not None else r.state.get("deferred_rows")
    return [{"row": d["row"], "requirement": _clip(d["text"])} for d in rows or []]


def _defer_section(r, allowed, analysis, prior):
    """Stage 3 (E30): the rows `defer` may name, or None when this call does not offer the field — no
    replan, defer already used, or no row list to choose from (one row cannot be deferred: that
    would be every row)."""
    if A.REPLAN.value not in allowed.answers or _defer_used(r.state):
        return None
    if analysis is None or _analysis_problems(r, analysis) or len(analysis["requirement_map"]) < 2:
        return None
    return {"requirement_rows": _requirement_rows(analysis, prior), "deferred": _deferred_rows(r)}


def _included_fixes(r):
    """Stage 3 (E18): the out-of-scope fixes the engine included (state.included_fixes)."""
    return [{"id": f["id"], "from_step": f["from_step"], "role": f["role"], "kind": f["kind"],
             "where": _clip(f["where"]), "note": _clip(f["note"]), "handled_by": f["handled_by"]}
            for f in _need(r, "included_fixes")]


def _pr_review_section(r):
    """Stage 3 (E31): the new PR review items; the texts are in in/pr-review.md."""
    q = _need(r, "pr_review")
    ff = q["fast_forward"]
    if not q["new"] and ff is None:
        raise LeaderError("pr-review: no new review item and no fast-forward — nothing to decide")
    return {"pr_number": q["pr_number"],
            "new": [{"id": x["id"], "author_association": str(x.get("author_association") or ""),
                     "created_at": str(x.get("created_at") or ""), "state": x.get("state"), "path": x.get("path")}
                    for x in q["new"]],
            "fast_forward": None if ff is None else {k: ff[k] for k in ("from", "to", "commits")}}


def _request_outcomes(r):
    """Stage 3 (E15): every change request of the Issue with how the engine ended it (state.requests)."""
    return [{"from_step": q["from_step"], "op": q["op"], "step": q["step"], "trigger": q["trigger"],
             "note": _clip(q["note"]), "outcome": q["outcome"], "reason": q["reason"]} for q in _need(r, "requests")]


def _fact(name, fn, *args):
    """A judgment fact: a git / file failure → facts.FactMissing; unsafe paths propagate."""
    try:
        return fn(*args)
    except (gitops.UnsafePath, fsafe.UnsafePath):
        raise
    except facts.FactMissing:
        raise
    except (gitops.GitError, OSError, ValueError) as e:
        raise facts.FactMissing(name, str(e)[:500]) from e


def _clip(text, limit=defaults.LEADER_INPUT_TEXT_MAX):
    text = str(text)
    if len(text) <= limit:
        return text
    return text[:limit] + defaults.LEADER_INPUT_TRUNCATION_MARK


def _norm(text):
    return " ".join(str(text).split())


def _error_line(e):
    if isinstance(e, (tuple, list)) and len(e) == 2:
        return f"{e[0]}: {e[1]}" if e[1] else str(e[0])
    return str(e)


def _specs(issue, name):
    return f"{defaults.SPECS_DIR.replace('{issue}', str(issue))}/{name}"


def _blob(ctx, rev, path):
    """(text, blob sha) of a regular file at `rev`, (None, None) when absent; non-regular → UnsafePath."""
    got = gitops.blob(ctx, rev, path)
    if got is None:
        return None, None
    mode, sha, data = got
    if not gitops.is_regular_mode(mode) or data is None:
        raise gitops.UnsafePath(f"{path} at {rev[:12]} is not a regular file (mode {mode})")
    return data.decode("utf-8"), sha


def _analysis_at(r, head, required):
    """acparse.parse_analysis of analysis.md at HEAD; None when absent / unparseable and not required."""
    rel = _specs(r.paths.issue, "analysis.md")
    text, _ = _fact("analysis", _blob, r.ctx, head, rel)
    if text is None:
        if required:
            raise facts.FactMissing("analysis", f"{rel} is not committed")
        return None
    kw = {"stage": r.stage} if r.stage >= 3 else {}        # E36: stages 1–2 read the stage-2 fields only
    try:
        an = acparse.parse_analysis(text, **kw)
    except acparse.AcError as e:
        if required:
            raise facts.FactMissing("analysis", f"{rel}: {e}") from e
        return None
    problems = _analysis_problems(r, an)
    if problems and required:
        raise facts.FactMissing("analysis", f"{rel}: " + "; ".join(problems))
    return an


def _analysis_problems(r, an):
    if r.stage < 3:
        return acparse.check_analysis(an)
    return acparse.check_analysis(an, stage=r.stage, deferred=[d["row"] for d in r.state.get("deferred_rows") or []])


def _state_steps(r):
    out = {}
    for s in r.state.get("steps") or ():
        out[s["id"]] = s
    return out


def _step_table(r):
    st = _state_steps(r)
    rows = []
    for p in r.procedure.steps:
        s = st.get(p.id)
        if s is None:
            raise facts.FactMissing("steps", f"step {p.id!r} is not in state.json")
        rows.append({
            "id": p.id, "kind": p.kind, "name": p.name, "status": s["status"],
            "attempts": s.get("latest_attempt") or 0,
            "on_fail_count": s.get("on_fail_count", 0),
            "on_fail_max": (p.on_fail["max"] + s.get("on_fail_extra", 0)) if p.on_fail else None,
        })
    return rows


def _counters(r):
    calls = r.state.get("leader_calls") or []
    extra = {} if r.stage < 3 else {
        "catalog_adds": len(r.state.get("catalog_adds") or []),
        "catalog_adds_max": defaults.CATALOG_ADDS_MAX,
        "followups": _followups_used(r.state),
        "followups_max": defaults.FOLLOWUPS_MAX,
    }
    return {
        **extra,
        "leader_calls": sum(1 for c in calls if isinstance(c, dict) and c.get("counted")),
        "leader_calls_max": defaults.LEADER_CALLS_MAX,
        "plan_rerun": _counter(r.state, "plan_rerun"),
        "plan_rerun_max": defaults.PLAN_GATE_RERUN_MAX,
        "done_rerun": _counter(r.state, "done_rerun"),
        "done_rerun_max": defaults.DONE_GATE_RERUN_MAX,
        "on_fail_rerun_used": any(s.get("on_fail_extra", 0) for s in r.state.get("steps") or ()),
        "soft_budget_rerun_used": bool(r.soft_acknowledged),
    }


def _followups_used(state):
    """Follow-ups this Issue already made (state.followups entries with disposition followup)."""
    return sum(1 for f in state.get("followups") or []
               if f["disposition"] == codes.DiscoveryDisposition.FOLLOWUP.value)


def _followup_ids(state):
    """The discovery ids (D…) among those follow-ups (state.followups[].key = "<D id>:<hash>")."""
    return {f["key"].split(":", 1)[0] for f in state.get("followups") or []
            if f["disposition"] == codes.DiscoveryDisposition.FOLLOWUP.value}


def _cost(r):
    c = r.issue_cost
    if isinstance(c, bool) or not isinstance(c, (int, float)) or c < 0:
        raise LeaderError(f"the request needs the Issue cost so far (budget.issue_cost), got {c!r}")
    return {"issue_usd": float(c), "soft_usd": float(defaults.SOFT_BUDGET_USD[r.mode]),
            "absolute_usd": float(defaults.ABSOLUTE_BUDGET_USD[r.mode])}


def _in_file_names(r, stopped):
    """The other in/ files of the situation (scope §2.1–§2.5), leader-input.json excluded."""
    I = codes.InFile
    sit = r.situation
    if sit == SR.PLAN_GATE.value:
        return [I.ISSUE.value, I.LEADER_DECISION.value]
    if sit == SR.DONE_GATE.value:
        return [I.ISSUE.value, I.REVIEW_DIFF.value, I.LEADER_DECISION.value]
    if sit in _STOPPED_SITUATIONS:
        ambiguous = bool(stopped and stopped.get("blocked")
                         and stopped["blocked"]["kind"] == codes.BlockedKind.AMBIGUOUS.value)
        # K8-3: whether the Issue is already settled is read in the Issue and its referenced Issues
        close = r.stage >= 3 and sit == SR.BLOCKED.value and statemachine.close_allowed(r.state)
        return ([I.ISSUE.value] if ambiguous or close else []) + [I.LEADER_DECISION.value, I.FAILURE_SUMMARY.value]
    if sit == SR.NEW_COMMENT.value:
        return [I.ISSUE.value, I.LEADER_DECISION.value]
    if sit == SR.PR_REVIEW.value:
        return [I.PR_REVIEW.value, I.LEADER_DECISION.value]
    if sit in _REQUEST_SITUATIONS:         # the Issue text when the driver gives it
        return ([I.ISSUE.value] if r.issue_md is not None else []) + [I.LEADER_DECISION.value]
    return []          # soft-budget: leader-input.json only (§2.4)


def _in_texts(r, names):
    """[(name, text)] for the in/ files; a text the driver must supply and did not → LeaderError."""
    I = codes.InFile
    src = {I.ISSUE.value: r.issue_md, I.REVIEW_DIFF.value: r.review_diff,
           I.FAILURE_SUMMARY.value: r.failure_summary, I.PR_REVIEW.value: r.pr_review_md}
    out = []
    for n in names:
        if n == I.LEADER_DECISION.value:
            text = r.leader_decision if r.leader_decision is not None else NO_DECISION_TEXT
        else:
            text = src.get(n)
        if not isinstance(text, str):
            raise LeaderError(f"{r.situation}: the request has no text for in/{n}")
        out.append((n, text))
    return out


def _docs(r, head, stopped):
    sit = r.situation
    issue = r.paths.issue
    if sit == SR.PLAN_GATE.value:
        return [_specs(issue, "analysis.md")]
    if sit in (SR.DONE_GATE.value, SR.PR_REVIEW.value):
        out = []
        for name in _DONE_GATE_DOCS:
            rel = _specs(issue, name + ".md")
            text, _ = _fact("docs", _blob, r.ctx, head, rel)
            if text is not None:
                out.append(rel)
        return out
    if sit in _STOPPED_SITUATIONS:
        p = r.procedure.step(r.step)
        return list(dict.fromkeys(i for i in p.inputs if not i.startswith(codes.IN_PREFIX)))
    if sit == SR.NEW_COMMENT.value or sit in _REQUEST_SITUATIONS:
        rel = _specs(issue, "analysis.md")
        text, _ = _fact("docs", _blob, r.ctx, head, rel)
        return [rel] if text is not None else []
    return []


def _referenced(r):
    out = []
    for i in r.referenced_issues or []:
        out.append({"number": i["number"], "state": i.get("state"), "state_reason": i.get("state_reason")})
    return out


def _templates(r, analysis):
    got = _row_templates(analysis, _need(r, "templates"), r.origin_template) if r.stage >= 3 else r.templates
    if not got and r.stage < 3:
        raise LeaderError("plan-gate: the request lists no usable template")
    out = [{"name": t["name"], "version": str(t["version"]), "steps": list(t["steps"])} for t in got]
    if r.stage < 3 and r.origin_template is not None:
        out = [t for t in out if t["name"] == r.origin_template]
        if not out:
            raise LeaderError(f"plan-gate: the Issue's template {r.origin_template!r} is not among the usable ones")
    return out


# R / D ids stable through the Issue's earlier leader-input.json files (V3)

def _prior_inputs(paths):
    """Every earlier leader-input.json of the Issue (runs/<step>/<n>/in/ and leader/<k>/in/)."""
    root = store._root(paths)
    files = []
    try:
        steps = sorted(os.listdir(paths.runs))
    except FileNotFoundError:
        steps = []
    for step in steps:
        try:
            sdir = paths.step_dir(step)
        except ValueError:
            continue
        try:
            nums = sorted(int(n) for n in os.listdir(sdir) if n.isdigit() and n == str(int(n)) and int(n) >= 1)
        except (FileNotFoundError, NotADirectoryError):
            continue
        files += [os.path.join(paths.in_dir(step, n), _INPUT_FILE) for n in nums]
    files += [os.path.join(paths.leader_in_dir(k), _INPUT_FILE) for k in store.leader_call_numbers(paths)]
    for f in files:
        if not os.path.lexists(f):
            continue
        try:
            data = fsafe.read_bytes(f, root=root, max_bytes=store.MAX_RECORD_BYTES)
            obj = json.loads(data.decode("utf-8"))
        except (OSError, ValueError, UnicodeDecodeError) as e:
            raise facts.FactMissing("leader ids", f"{os.path.relpath(f, paths.issue_dir)}: {e}") from e
        if isinstance(obj, dict):
            yield obj


def _row_keys(rows):
    """[(key, text, acs)] — key = normalised text + ACs + occurrence (two equal rows differ)."""
    seen = {}
    out = []
    for text, acs in rows:
        base = (_norm(text), tuple(acs))
        seen[base] = seen.get(base, 0) + 1
        out.append((json.dumps([base[0], list(base[1]), seen[base]]), text, list(acs)))
    return out


def _assign(current_keys, known, prefix):
    """Ids for `current_keys` reusing `known` {key: id}; a new key gets max + 1."""
    nums = [int(v[len(prefix):]) for v in known.values() if isinstance(v, str) and v.startswith(prefix)
            and v[len(prefix):].isdigit()]
    nxt = max(nums, default=0) + 1
    used, out = set(), []
    for key in current_keys:
        rid = known.get(key)
        if rid is None or rid in used:
            rid = f"{prefix}{nxt}"
            nxt += 1
        used.add(rid)
        out.append(rid)
    return out


def _requirement_rows(analysis, prior):
    known = {}
    for obj in prior:
        for sec in (obj.get("plan_gate"), obj.get("done_gate"), obj.get("defer")):
            if not isinstance(sec, dict):
                continue
            rows = sec.get("requirement_rows") or []
            keyed = _row_keys([(x.get("requirement", ""), x.get("acs") or []) for x in rows])
            for (key, _, _), x in zip(keyed, rows):
                known.setdefault(key, x.get("row"))
    current = _row_keys([(_clip(req), acs) for req, acs in analysis["requirement_map"]])
    ids = _assign([k for k, _, _ in current], known, "R")
    return [{"row": rid, "requirement": text, "acs": acs} for rid, (_, text, acs) in zip(ids, current)]


def _discovery_key(d):
    return json.dumps([d["role"], d["kind"], _norm(d["where"]), _norm(d["note"]), bool(d["blocks_current_ac"])])


def _discoveries(r, prior, included=()):
    """D1..Dn. `included` (stage 3): the fixes F1..Fn — judged as such, so not discoveries any more."""
    taken = {_discovery_key(dict(f, blocks_current_ac=True)) for f in included}
    known = {}
    for obj in prior:
        sec = obj.get("done_gate")
        if isinstance(sec, dict):
            for d in sec.get("discoveries") or []:
                try:
                    known.setdefault(_discovery_key(d), d.get("id"))
                except (KeyError, TypeError):
                    continue
    found, seen = [], set()
    for p in r.procedure.steps:
        if p.kind != _ROLE:
            continue
        res = _latest_result(r, p.id)
        for d in (res or {}).get("discoveries") or []:
            item = {"kind": d["kind"], "where": _clip(d["where"]), "blocks_current_ac": bool(d["blocks_current_ac"]),
                    "role": p.name, "note": _clip(d["note"])}
            key = _discovery_key(item)
            if key in seen or key in taken:
                continue
            seen.add(key)
            found.append((key, item))
    ids = _assign([k for k, _ in found], known, "D")
    return [dict({"id": i}, **item) for i, (_, item) in zip(ids, found)]


# reading the Issue's records

def _attempt_numbers(r, step_id):
    try:
        names = os.listdir(r.paths.step_dir(step_id))
    except FileNotFoundError:
        return []
    return sorted(int(n) for n in names if n.isdigit() and n == str(int(n)) and int(n) >= 1)


def _read_facts(r, step_id, n, required):
    try:
        return store.read_facts(r.paths, step_id, n)
    except FileNotFoundError:
        if required:
            raise facts.FactMissing("facts", f"runs/{step_id}/{n}/facts.json is missing") from None
        return None
    except (store.CorruptFile, store.FormatMismatch, ValueError) as e:
        if required:
            raise facts.FactMissing("facts", f"runs/{step_id}/{n}/facts.json: {e}") from e
        return None


def _read_json_file(r, path):
    try:
        data = fsafe.read_bytes(path, root=store._root(r.paths), max_bytes=store.MAX_RECORD_BYTES)
        return json.loads(data.decode("utf-8"))
    except FileNotFoundError:
        return None
    except (ValueError, UnicodeDecodeError):
        return None


def _latest_result(r, step_id):
    n = (_state_steps(r).get(step_id) or {}).get("latest_attempt")
    if not n:
        return None
    obj = _read_json_file(r, r.paths.attempt_file(step_id, n, "result.json"))
    return obj if isinstance(obj, dict) else None


def _mutations(r):
    """Stage 4 (VB9): the done-gate `mutations` section from the HEAD's mutation record (None = nothing declared)."""
    m = r.mutations
    if m is None:
        return None
    return {"problem": m["problem"], "control_flaky": bool((m.get("control") or {}).get("flaky")), "rows": [
        dict({k: row[k] for k in ("id", "acs", "path", "status", "detail")},
             **{k: _clip(row[k]) for k in ("find", "replace", "note")},
             # VW3 E2: the first failure block first, then only the END of the log (a record of an older
             # engine has no excerpt: "")
             log_excerpt=_clip(row.get("log_excerpt") or "", defaults.MUTATION_EXCERPT_MAX),
             log_tail=_clip_start(row["log_tail"], defaults.MUTATION_LEADER_TAIL_MAX)) for row in m["rows"]]}


def _clip_start(text, limit):
    """The last `limit` characters, the truncation mark in front when cut (the end of a log is what matters)."""
    if len(text) <= limit:
        return text
    return defaults.LEADER_INPUT_TRUNCATION_MARK + text[-limit:]


def _run_red(run):
    return run is None or run.get("exit_code") != 0 or bool(run.get("timed_out"))


def _done_gate_section(r, head, analysis, prior):
    st = _state_steps(r)
    order = [p.id for p in r.procedure.steps]
    upto = order.index(r.step) if r.step in order else len(order)
    cfg = _config(r)
    quarantined = len(cfg.quarantine())
    runs = []
    for p in r.procedure.steps[:upto]:
        if p.kind != _RUN:
            continue
        s = st.get(p.id) or {}
        if s.get("status") != codes.StepStatus.DONE.value:
            runs.append({"step": p.id, "name": p.name, "exit_code": None, "flaky": False, "base_red": False,
                         "quarantined": quarantined})
            continue
        latest = s.get("latest_attempt")
        fx = _read_facts(r, p.id, latest, required=True) if latest else None
        run = (fx or {}).get("run")
        if not isinstance(run, dict) or "exit_code" not in run:
            raise facts.FactMissing("runs", f"run step {p.id!r} is done without a recorded run exit code")
        flaky = False
        for n in _attempt_numbers(r, p.id):
            f = _read_facts(r, p.id, n, required=False) or {}
            rr = (f.get("run") or {})
            if rr.get("rerun") and _run_red(rr) and not _run_red(rr["rerun"]):
                flaky = True
            if rr.get("head_flaky") is True:     # VW4 O1: a safety-net-proof run not green once, then green — passed
                flaky = True
        base = run.get("base_run")
        runs.append({"step": p.id, "name": p.name, "exit_code": run["exit_code"], "flaky": flaky,
                     "base_red": bool(base) and _run_red(base)
                     and (not run.get("base_rerun") or _run_red(run["base_rerun"])), "quarantined": quarantined})
    reviews, requests = [], []
    for p in r.procedure.steps[:upto]:
        if p.kind != _ROLE:
            continue
        res = _latest_result(r, p.id)
        done = (st.get(p.id) or {}).get("status") == codes.StepStatus.DONE.value
        if p.is_review and done:
            if not isinstance(res, dict) or "verdict" not in res:
                raise facts.FactMissing("reviews", f"review step {p.id!r} is done without its result")
            reviews.append({
                "step": p.id, "role": p.name, "verdict": res["verdict"],
                "checks": [{"id": c["id"], "result": c["result"]} for c in res.get("checks") or []],
                "findings": [{"severity": f["severity"], "file": _clip(f["file"]), "line": f["line"],
                              "text": _clip(f["text"])} for f in res.get("findings") or []],
            })
        for q in ((res or {}).get("requests") or []) if r.stage < 3 else ():
            requests.append({"from_step": p.id, "op": q["op"], "step": _clip(q["step"]), "trigger": q["trigger"],
                             "note": _clip(q["note"])})
    extra, included = {}, []
    if r.stage >= 3:
        requests, included = _request_outcomes(r), _included_fixes(r)
        extra = {"included_fixes": included, "deferred_rows": _deferred_rows(r), "followup_candidates": [
            {"number": c["number"], "title": _clip(c["title"]), "labels": list(c["labels"])}
            for c in _need(r, "followup_candidates")]}
    if r.stage >= codes.STAGE4:
        extra.update({"mutations": _mutations(r), "commits": [
            {"sha": sha, "message": _clip(msg)} for sha, msg in _fact("commit_messages", gitops.commit_messages,
                                                                      r.ctx, head)]})
    changed = _fact("changed_files", gitops.changed_files, r.ctx, head)
    paths_changed = sorted({c["path"] for c in changed} | {c["from"] for c in changed if c.get("from")})
    verification = [p for p in paths_changed if cfg.matches(codes.PathRuleKind.VERIFICATION.value, p)]
    refused = []
    for p in r.procedure.steps:
        if p.kind != _ROLE:
            continue
        for n in _attempt_numbers(r, p.id):
            f = _read_facts(r, p.id, n, required=False) or {}
            for d in ((f.get("session") or {}).get("permission_denials") or []):
                if d.get("tool_name") in _DENIED_WRITE_TOOLS:
                    ti = d.get("tool_input") or {}
                    refused.append(_clip(f"{p.id} attempt {n}: {d['tool_name']} "
                                         f"{ti.get('file_path') or ti.get('path') or '?'}"))
    decisions = []
    for c in r.state.get("leader_calls") or []:
        if isinstance(c, dict) and c.get("situation") == SR.NEW_COMMENT.value and c.get("answer"):
            decisions.append({"answer": c["answer"], "reason": c.get("reason") or codes.LeaderReason.OTHER.value,
                              "step": c.get("step")})
    return {
        "acs": list(analysis["acs"]),
        "requirement_rows": _requirement_rows(analysis, prior),
        "runs": runs,
        "not_checked_locally": [_clip(f"{e['name']} — {e.get('note', '')}") for e in cfg.not_checked_locally()],
        "reviews": reviews,
        "discoveries": _discoveries(r, prior, included),
        "requests": requests,
        **extra,
        "verification_paths_changed": verification,
        "refused_writes": refused,
        "comment_decisions": decisions,
    }


def _config(r):
    c = r.config
    if isinstance(c, repoconfig.RepoConfig):
        return c
    if hasattr(c, "raw") and isinstance(getattr(c, "raw"), dict):
        return c
    try:
        return repoconfig.RepoConfig(c)
    except repoconfig.ConfigError as e:
        raise LeaderError(f"repository settings refused: {e}") from None


def _config_raw(r):
    c = r.config
    return c.raw if hasattr(c, "raw") else c


def _stopped_section(r):
    sit = r.situation
    p = r.procedure.step(r.step)
    s = _state_steps(r).get(r.step)
    if s is None:
        raise facts.FactMissing("steps", f"step {r.step!r} is not in state.json")
    latest = s.get("latest_attempt")
    out = {"step": p.id, "kind": p.kind, "name": p.name, "attempts": latest or 0,
           "on_fail_count": s.get("on_fail_count", 0),
           "on_fail_max": (p.on_fail["max"] + s.get("on_fail_extra", 0)) if p.on_fail else None,
           "blocked": None, "format_errors": [], "session": None, "run": None}
    if sit == SR.BLOCKED.value:
        res = _latest_result(r, p.id)
        b = (res or {}).get("blocked_by")
        if not isinstance(b, dict) or "kind" not in b:
            raise facts.FactMissing("blocked_by", f"step {p.id!r} stopped blocked without a blocked_by in its result")
        out["blocked"] = {"kind": b["kind"], "note": _clip(b.get("note", ""))}
    if sit == SR.OUTPUT_FORMAT_TWICE.value:
        lines = []
        for n in _attempt_numbers(r, p.id):
            oc = (_read_facts(r, p.id, n, required=False) or {}).get("outcome") or {}
            if oc.get("code") == codes.FailureCode.OUTPUT_FORMAT.value:
                lines.append(_clip(f"attempt {n}: {oc['code']}" + (f" / {oc['detail']}" if oc.get("detail") else "")))
        out["format_errors"] = lines[-(defaults.OUTPUT_FORMAT_RETRIES + 1):]
    if sit == SR.SESSION_LIMIT.value and latest:
        brief = _read_json_file(r, r.paths.attempt_file(p.id, latest, "brief.json")) or {}
        fx = _read_facts(r, p.id, latest, required=False) or {}
        cap = (brief.get("session") or {}).get("max_budget_usd")
        cost = (fx.get("session") or {}).get("cost_usd")
        out["session"] = {"max_budget_usd": cap if isinstance(cap, (int, float)) and not isinstance(cap, bool) else None,
                          "cost_usd": cost if isinstance(cost, (int, float)) and not isinstance(cost, bool) else None}
    if p.kind == _RUN and latest:
        fx = _read_facts(r, p.id, latest, required=True)
        run = fx.get("run")
        if not isinstance(run, dict) or "exit_code" not in run:
            raise facts.FactMissing("run", f"run step {p.id!r} has no recorded exit code")
        out["run"] = {"exit_code": run["exit_code"],
                      "rerun_exit_code": (run.get("rerun") or {}).get("exit_code"),
                      # K8-2: an evidence run's second base run is the one that decides
                      "base_exit_code": (run.get("base_rerun") or run.get("base_run") or {}).get("exit_code")}
    return out


def _budget_section(r):
    st = _state_steps(r)
    per = []
    for p in r.procedure.steps:
        total = 0.0
        for n in _attempt_numbers(r, p.id):
            cost = ((_read_facts(r, p.id, n, required=False) or {}).get("session") or {}).get("cost_usd")
            if isinstance(cost, (int, float)) and not isinstance(cost, bool) and cost >= 0:
                total += float(cost)
        per.append({"step": p.id, "cost_usd": round(total, 6)})
    done = (codes.StepStatus.DONE.value, codes.StepStatus.SKIPPED.value)
    remaining = [p.id for p in r.procedure.steps if (st.get(p.id) or {}).get("status") not in done]
    return {"per_step": per, "remaining_steps": remaining, "next_step": r.step}


def _comments_section(r, analysis):
    new = r.new_comments
    if not new:
        raise LeaderError("new-collaborator-comment: the request lists no new comment")
    st = _state_steps(r)
    return {
        "new": [{"id": c["id"], "author_association": str(c.get("author_association") or ""),
                 "created_at": str(c.get("created_at") or "")} for c in new],
        "assumptions": [_clip(a) for a in (analysis or {}).get("assumptions") or []],
        "current_step": r.step,
        "passed_steps": [p.id for p in r.procedure.steps
                         if (st.get(p.id) or {}).get("status") == codes.StepStatus.DONE.value],
    }


def _ids_from_input(situation, inp):
    """The answer-schema id lists of a call, read from its leader-input.json object."""
    if situation == SR.PLAN_GATE.value:
        pg = inp["plan_gate"]
        return {"requirement_rows": [x["row"] for x in pg["requirement_rows"]],
                "templates": [t["name"] for t in pg["templates"]]}
    if situation == SR.DONE_GATE.value:
        dg = inp["done_gate"]
        return {"ac_ids": list(dg["acs"]), "discovery_ids": [d["id"] for d in dg["discoveries"]]}
    if situation == SR.NEW_COMMENT.value:
        return {"comment_ids": [c["id"] for c in inp["comments"]["new"]]}
    if situation == SR.STEP_REMOVAL_REQUEST.value:
        return {"skippable_steps": list(inp["removal"]["skippable_steps"])}
    if situation == SR.PR_REVIEW.value:
        return {"review_ids": [x["id"] for x in inp["pr_review"]["new"]]}
    return {}


def _dispositions(inp):
    """Stage 3 (E19): `followup` while the Issue has not reached its cap, `duplicate` with a candidate."""
    gone = set()
    if any(n.get("field") == codes.DiscoveryDisposition.FOLLOWUP.value for n in inp["allowed"]["narrowed"]):
        gone.add(codes.DiscoveryDisposition.FOLLOWUP.value)
    if not inp["done_gate"]["followup_candidates"]:
        gone.add(codes.DiscoveryDisposition.DUPLICATE.value)
    return [d for d in codes.DiscoveryDisposition.values() if d not in gone]


def _answer_ids(r, inp):
    """The answer-schema id lists of a call: what its leader-input.json object offers (+ the request's
    plan_role_steps, which the object does not repeat)."""
    sit = r.situation
    if r.stage < 3:
        return _ids_from_input(sit, inp)
    al = inp["allowed"]
    if sit == SR.PLAN_GATE.value:
        pg = inp["plan_gate"]
        steps = {s for t in pg["templates"] for s in t["steps"]}
        role_steps = [s for s in _need(r, "plan_role_steps") if s in steps]
        usable = [c["id"] for c in pg["catalog"] if c["usable"] and c["class"] not in catalog.NOT_REQUESTABLE_CLASSES]
        return dict(_ids_from_input(sit, inp), models=al["models"], efforts=al["efforts"],
                    plan_role_steps=role_steps,
                    catalog_steps=usable if r.origin_template is None else [])
    if sit == SR.DONE_GATE.value:
        dg = inp["done_gate"]
        return dict(_ids_from_input(sit, inp), fix_ids=[f["id"] for f in dg["included_fixes"]],
                    dispositions=_dispositions(inp), candidate_issues=[c["number"] for c in dg["followup_candidates"]])
    if _situations(r.stage)[sit] == _S3_ENVELOPE:
        return {"requirement_rows": [x["row"] for x in (inp["defer"] or {"requirement_rows": []})["requirement_rows"]],
                "models": al["models"], "efforts": al["efforts"],
                "close_reasons": codes.CloseReason.values() if A.CLOSE_AS_DECIDED.value in al["answers"] else []}
    return _ids_from_input(sit, inp)


def _checklist_acs(r, head):
    """AC ids the Manual Test Checklist references (acparse reference parser), None if unreadable."""
    rel = None
    for p in r.procedure.steps:
        if p.kind == _ROLE and p.name == "qa":
            rel = next((o for o in p.outputs if not globs.is_glob(o)), None)
            if rel:
                break
    rel = rel or _specs(r.paths.issue, "manual-test-checklist.md")
    text, _ = _fact("checklist", _blob, r.ctx, head, rel)
    if text is None:
        return None
    try:
        return set(acparse.parse_test_case_refs(text))
    except acparse.AcError:
        return None


def call(request):
    """Run one leader call for `request` (a LeaderRequest); return a LeaderResult.

    Steps 1–7 of the module docstring. Raises LeaderError (nothing spawned → engine-error),
    facts.FactMissing (→ infra fact-collection, before any session), session.SessionError
    (→ engine-error). Does not write state.json / log.jsonl and does not apply the answer;
    the caller logs `leader-call` start / end, applies the answer through
    lifecycle.apply_answer(…, who=leader), appends the note to leader-decision.md, records
    state.leader_calls and the counters (session B, V4–V8).

    The caller also checks the judge canary record before the call (the leader is a judge
    session, D10 — canaryrun is L4); the key is recorded in each brief.
    """
    r = request
    if not isinstance(r, LeaderRequest):
        raise LeaderError("call() needs a LeaderRequest")
    _check_request(r)
    sit = r.situation
    analysis = None
    if sit == SR.PLAN_GATE.value:
        analysis = _analysis_at(r, _fact("head", gitops.head, r.ctx), required=True)
    try:
        allowed = allowed_answers(sit, r.state, r.procedure, r.step, mode=r.mode, analysis=analysis,
                                  decision_marker=bool(r.decision_marker),
                                  soft_acknowledged=bool(r.soft_acknowledged),
                                  origin_template=r.origin_template, stage=r.stage, **_allowed_fields(r))
    except ValueError as e:
        raise LeaderError(str(e)) from None
    if allowed.escalate_only:                    # D9: nothing to decide — no session
        return LeaderResult(situation=sit, called=False, allowed=allowed)
    probe = build_input(r, allowed, 1)           # FactMissing / LeaderError before anything is made
    _answer_schema(sit, allowed, _answer_ids(r, probe), r.stage)
    sysprompt, sources = _system_prompt(r.ctx)
    version = r.cli_version or session.cli_version("claude", r.environ)
    key = canary.canary_key(version, render.template_hash(_JUDGE), _JUDGE,
                            canary.account_tag(canary.claude_config_dir(r.environ)))
    checklist = _checklist_acs(r, _fact("head", gitops.head, r.ctx)) if sit == SR.DONE_GATE.value else None
    sessions, costs, errors, inp = [], [], [], None
    for retry in range(defaults.leader_format_retries(sit) + 1):
        n = _new_folder(r)
        sessions.append(n)
        if retry == 0:                            # nothing was written since the probe
            inp = probe
            inp["call"]["attempt"] = n
        else:
            inp = build_input(r, allowed, n, retry, errors)
        ids = _answer_ids(r, inp)
        verdict, value, cost = _session(r, allowed, n, retry, errors, inp, ids,
                                        _answer_schema(sit, allowed, ids, r.stage), sysprompt, sources, version,
                                        key, checklist)
        costs.append(cost)
        common = {"situation": sit, "called": True, "attempts": len(sessions), "cost_usd": _sum_cost(costs),
                  "allowed": allowed, "sessions": sessions, "input": inp}
        if verdict == "answer":
            return LeaderResult(answer=value["answer"], step=value["step"], reason=value["reason"],
                                note=value["note"], recommendation=value["recommendation"],
                                extra=_extra(sit, value, r.stage), **common)
        if verdict == "format":
            errors = value
            continue
        if verdict == "failed":
            return LeaderResult(failed={"code": value, "detail": None}, **common)
        if verdict == "quota":
            return LeaderResult(quota_reset_at=value, **common)
        if verdict == "infra":
            return LeaderResult(stop=SR.INFRA_STOP.value, infra=value, **common)
        return LeaderResult(stop=value, **common)
    return LeaderResult(situation=sit, called=True, attempts=len(sessions), cost_usd=_sum_cost(costs),
                        allowed=allowed, sessions=sessions, input=inp,
                        failed={"code": codes.FailureCode.OUTPUT_FORMAT.value, "detail": errors[0][0]})


# --- one leader session -----------------------------------------------------------------------

_JUDGE = codes.RoleClass.JUDGE.value
_CHECK = codes.AttemptKind.CHECK.value


class _NoOutputs:
    """The step facts.finish_facts collects for: a check-kind step without outputs (a leader
    session writes nothing; its `kind` is set to check / leader afterwards)."""
    kind = codes.StepKind.CHECK.value
    outputs = ()

    def __init__(self, step_id):
        self.id = step_id


def _allowed_fields(r):
    """The stage-3 arguments of allowed_answers (nothing before stage 3)."""
    if r.stage < 3:
        return {}
    cfg = _config(r)
    out = {"models": cfg.allowed_models(), "efforts": cfg.allowed_efforts()}
    if r.situation == SR.PLAN_GATE.value:
        out["templates"] = _need(r, "templates")
        out["bug_issue"] = r.bug_issue
    elif r.situation == SR.STEP_REMOVAL_REQUEST.value:
        out["skippable_steps"] = _removal_section(r)["skippable_steps"]
    elif r.situation == SR.BLOCKED.value:
        out["close_risk"] = _close_risk(r)
    return out


def _close_risk(r):
    """K8-3 (A2 for blocked): the analysis committed at HEAD says risk high, or no risk can be read from
    it → closing is a human's decision. No committed analysis (analyze itself blocked) → False."""
    head = _fact("head", gitops.head, r.ctx)
    text, _ = _fact("analysis", _blob, r.ctx, head, _specs(r.paths.issue, "analysis.md"))
    if text is None:
        return False
    an = _analysis_at(r, head, required=False)
    return an is None or an.get("risk") != codes.Risk.LOW.value


def _answer_schema(situation, allowed, ids, stage=2):
    try:
        return render_answer_schema(situation, allowed, ids, stage=stage)
    except (ValueError, schema.SchemaError) as e:
        raise LeaderError(f"{situation}: no answerable schema: {e}") from None


def _sum_cost(costs):
    known = [c for c in costs if isinstance(c, (int, float)) and not isinstance(c, bool)]
    return round(sum(known), 6) if known else None


def _extra(situation, ans, stage=2):
    if situation == SR.PLAN_GATE.value:
        plan = ans.get("plan")
        if _stage3(stage) and plan is not None:
            plan = {"template": plan["template"], "adjust": plan.get("adjust", []), "models": plan.get("models", []),
                    "new_template_candidate": plan["new_template_candidate"]}
        return {"requirements": ans["requirements"], "missing_requirements": ans["missing_requirements"],
                "plan": plan, "close": ans["close"]}
    if situation == SR.DONE_GATE.value:
        out = {"ac_verdicts": ans["ac_verdicts"], "discoveries": ans.get("discoveries", [])}
        if _stage3(stage):
            out["included_fixes"] = ans.get("included_fixes", [])
        return out
    if situation == SR.NEW_COMMENT.value:
        return {"comments": ans["comments"]}
    if situation == SR.STEP_REMOVAL_REQUEST.value:
        return {"skip_step": ans["skip_step"]}
    if situation == SR.PR_REVIEW.value:
        return {"reviews": ans.get("reviews", [])}
    if _stage3(stage) and _situations(stage)[situation] == _S3_ENVELOPE:
        out = {"defer": ans.get("defer"), "session": ans.get("session")}
        if ans.get("close") is not None:
            out["close"] = ans["close"]
        return out
    return {}


def _new_folder(r):
    if r.kind == _CHECK:
        return store.new_attempt(r.paths, r.state, r.step)
    return store.new_leader_call(r.paths)


def _folder(r, n):
    return r.paths.attempt_dir(r.step, n) if r.kind == _CHECK else r.paths.leader_dir(n)


def _in_dir(r, n):
    return r.paths.in_dir(r.step, n) if r.kind == _CHECK else r.paths.leader_in_dir(n)


def _write_in(r, n, name, text):
    if r.kind == _CHECK:
        return store.write_in_file(r.paths, r.step, n, name, text)
    return store.write_leader_in_file(r.paths, n, name, text)


def _write_brief(r, n, brief):
    if r.kind == _CHECK:
        return store.write_brief(r.paths, r.step, n, brief)
    return store.write_leader_brief(r.paths, r.step, n, brief)


def _write_result(r, n, result):
    if r.kind == _CHECK:
        return store.write_result(r.paths, r.step, n, result)
    return store.write_leader_result(r.paths, n, result)


def _write_facts(r, n, fx):
    if r.kind == _CHECK:
        return store.write_facts(r.paths, r.step, n, fx)
    return store.write_leader_facts(r.paths, r.step, n, fx)


def _system_prompt(ctx):
    """(text, sources): CLAUDE.md + .claude/CLAUDE.md + the leader role file, base-SHA blobs."""
    base = ctx.base_sha
    parts, sources = [], []
    for path in ("CLAUDE.md", ".claude/CLAUDE.md"):
        text, sha = _blob(ctx, base, path)
        parts.append(text)
        if text is not None:
            sources.append({"path": path, "blob": sha})
    body, sha = _blob(ctx, base, LEADER_ROLE_FILE)
    if body is not None:
        sources.append({"path": LEADER_ROLE_FILE, "blob": sha})
    elif os.path.isfile(PLUGIN_LEADER_ROLE_FILE):
        with open(PLUGIN_LEADER_ROLE_FILE, encoding="utf-8") as f:
            body = f.read()
    else:
        raise LeaderError(f"no leader role file: {LEADER_ROLE_FILE} at the base SHA nor the plugin default")
    try:
        return instructions.system_prompt(parts[0], parts[1], body), sources
    except ValueError as e:
        raise LeaderError(f"leader role file: {e}") from None


def _bullets(items):
    return "\n".join(f"- `{i}`" for i in items)


def _instruction(r, allowed, in_dir, in_files, docs, n, retry, errors):
    """The `-p` text: the leader frame + the situation's task text + this call
    (instructions.build_leader_instruction, session C — scope §2.0, §4.1), then the allowed
    answers of this call (the same lists as the schema enums and leader-input.json `allowed`)."""
    try:
        base = instructions.build_leader_instruction(r.situation, {
            "issue": r.paths.issue, "step": r.step, "attempt": n, "in_dir": in_dir, "in_files": in_files,
            "docs": docs, "format_retry": retry,
            "errors": [_clip(_error_line(e)) for e in errors[:_ERRORS_MAX]]}, stage=r.stage)
    except (ValueError, OSError) as e:
        raise LeaderError(f"leader instruction: {e}") from None
    where = (f"check step `{r.step}` attempt {n}" if r.kind == _CHECK
             else f"leader call {n} (situation attached to step `{r.step}`)")
    ans = ["## Your answer", "", f"This session: {where}.", "",
           "### Outputs", "", "None: you write no file. Writing any file stops the Issue (security boundary).", "",
           "### Allowed answers", "",
           "Return the structured output only (its schema is given separately). The engine acts on the "
           "enum fields only — `answer`, `reason`, `step`, `recommendation` and the situation fields — and "
           "never on `note`, `evidence` or any other free text: those are for the human and the next role.",
           "", "Allowed answers for this call:", "", _bullets(allowed.answers)]
    if allowed.rerun_steps:
        ans += ["", "Steps `rerun` may name:", "", _bullets(allowed.rerun_steps)]
    if allowed.narrowed:
        ans += ["", "Removed by the engine (not yours to choose):", ""]
        ans += [f"- `{', '.join(a) or codes.NARROWING_FIELDS[reason]}` — {reason}" for reason, a in allowed.narrowed]
    if A.ESCALATE.value in allowed.answers:
        ans += ["", "With `escalate`, `recommendation` names the answer you recommend to the human (one of "
                + ", ".join(f"`{a}`" for a in _recommendable(r.situation, allowed)) + ")."]
    return base.rstrip() + "\n\n" + "\n".join(ans) + "\n"


def _control_entry(path):
    st = os.lstat(path)
    if stat.S_ISREG(st.st_mode):
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 16), b""):
                h.update(chunk)
        return f"file:{'x' if st.st_mode & 0o111 else '-'}:{h.hexdigest()}"
    if stat.S_ISLNK(st.st_mode):
        return "link:" + os.readlink(path)
    return "other"


def _control_snapshot(ctx, issue):
    """{worktree-relative path: identity} of every control entry on disk (ignored and untracked
    too; real directories descended, links never followed) — compared before / after a session."""
    out = {}
    stack = [(ctx.work_tree, "")]
    while stack:
        d, rel = stack.pop()
        try:
            entries = list(os.scandir(d))
        except (FileNotFoundError, NotADirectoryError):
            continue
        for e in entries:
            rp = e.name if not rel else rel + "/" + e.name
            if not rel and e.name == ".git":
                continue
            try:
                is_dir = e.is_dir(follow_symlinks=False)
            except OSError:
                is_dir = False
            if is_dir:
                stack.append((e.path, rp))
            elif globs.is_control_file(rp, issue) or e.name.lower() in globs.CONTROL_FOLDERS:
                try:
                    out[rp] = _control_entry(e.path)
                except FileNotFoundError:
                    continue
    return out


def _session(r, allowed, n, retry, errors, inp, ids, answer_schema, sysprompt, sources, version, key, checklist):
    """One leader session in folder n → (verdict, value, cost_usd).

    verdict "answer" (value: the accepted answer), "format" ([(code, detail)]), "failed"
    (a LEADER_FAILED_CODES value), "quota" (reset epoch seconds), "infra" ({"detail", "reset_at"}: an
    infra-stop, LeaderResult.infra), "stop" (another StopReason value)."""
    ctx = r.ctx
    issue = r.paths.issue
    in_dir = _in_dir(r, n)
    _write_in(r, n, _INPUT_FILE, json.dumps(inp, ensure_ascii=False, indent=1) + "\n")
    for name, text in _in_texts(r, inp["in_files"]):
        _write_in(r, n, name, text)
    in_files = [_INPUT_FILE] + list(inp["in_files"])
    model, effort = defaults.MODEL_EFFORT[LEADER_ROLE]
    tools = list(defaults.TOOLS[_JUDGE])
    max_usd = session.session_budget(LEADER_ROLE)
    instruction = _instruction(r, allowed, in_dir, in_files, inp["docs"], n, retry, errors)
    rpaths = dict(r.render_paths(r.kind, r.step, n))
    rpaths["in_dir"] = in_dir                    # this session's own in/ (check: runs/…, leader: leader/<k>/)
    try:
        rin = render.RenderInput(
            kind="role", role=LEADER_ROLE, role_class=_JUDGE, step=r.step, attempt=n, issue=issue, outputs=[],
            paths=rpaths, config=_config_raw(r), model=model, effort=effort, tools=tools, max_budget_usd=max_usd,
            json_schema=answer_schema, instruction=instruction, system_prompt=sysprompt, resume=None,
            bash_timeout_ms=defaults.RUN_TIMEOUT_MIN * 60 * 1000)
        lim = session.session_limits(rin, r.limits)
    except (render.RenderError, session.SessionError) as e:
        raise LeaderError(f"leader session render: {e}") from None
    head = _fact("start_head", gitops.head, ctx)
    brief = {
        "format": defaults.FORMAT, "issue": issue, "step": r.step, "attempt": n, "kind": r.kind,
        "base_sha": ctx.base_sha, "start_head": head, "created_at": store.now_ts(),
        "role": LEADER_ROLE, "role_class": _JUDGE, "result_kind": "leader",
        "leader": {"situation": r.situation, "schema": _situations(r.stage)[r.situation],
                   "allowed_answers": list(allowed.answers), "format_retry": retry},
        "instruction": instruction, "system_prompt_sources": sources,
        "inputs": list(inp["docs"]), "in_dir": in_dir, "in_files": in_files, "outputs": [], "checks": [],
        "rule_checks": [], "facts": {}, "returned": None, "reentry": None,
        "session": {"model": model, "effort": effort, "tools": tools, "max_budget_usd": max_usd,
                    "wall_clock_s": int(lim["wall_clock_s"]), "no_output_s": int(lim["no_output_s"]),
                    "resume": None, "cli_version": version, "canary_key": key},
        "run": None,
    }
    _write_brief(r, n, brief)
    start = facts.start_facts(ctx, r.step, n, issue, codes.StepKind.CHECK.value)
    before = _fact("control_files", _control_snapshot, ctx, issue)
    sres = session.run_session(rin, _folder(r, n), r.environ, limits=r.limits, version=version)
    structured = sres.structured
    if structured is not None:
        _write_result(r, n, structured)
    try:
        fx = facts.finish_facts(ctx, start, r.procedure, _NoOutputs(r.step))
        fx["kind"] = r.kind
        warnings = fx["warnings"]
        sess = facts._session_part(sres, warnings)
        facts._record_effort(sess, model, effort, warnings)
        fx["session"] = sess
        fx["exit_code"] = sres.exit_code
        fx["judge_writes_outside"] = _fact("attempt_changes", facts.attempt_changes, ctx, fx["start_head"],
                                           fx["end_head"], fx["end_tree"])
        after = _fact("control_files", _control_snapshot, ctx, issue)
        moved = sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p))
        fx["control_files"] = {"ok": not moved, "changed": moved}
    except (gitops.UnsafePath, fsafe.UnsafePath):
        return "stop", SR.UNSAFE_PATH.value, None
    cost = sess.get("cost_usd")
    verdict, value, outcome = _judge(r, sres, fx, structured, allowed, ids, checklist, inp)
    fx["outcome"] = outcome
    _write_facts(r, n, fx)
    return verdict, value, cost


def _outcome(status, code=None, detail=None, stop=None):
    return {"status": status, "code": code, "detail": detail, "stop": stop}


def _judge(r, sres, fx, structured, allowed, ids, checklist, inp):
    """(verdict, value, facts outcome) of one leader session — boundary first (scope D12)."""
    S = codes.StepStatus
    E = codes.SessionEnd
    FC = codes.FailureCode
    sess = fx["session"]
    for bad, reason in ((not fx["control_files"]["ok"], SR.CONTROL_FILE.value),
                        (bool(fx["judge_writes_outside"]), SR.JUDGE_WROTE_OUTSIDE.value)):
        if bad:
            return "stop", reason, _outcome(S.NEEDS_HUMAN.value, stop=reason)
    end = sess["end"]
    if end == E.BUDGET.value:
        return "failed", FC.SESSION_LIMIT.value, _outcome(S.NEEDS_HUMAN.value, code=FC.SESSION_LIMIT.value)
    if end != E.COMPLETED.value:
        q = getattr(sres, "quota_reset_at", None)
        if end == E.ERROR.value and q is not None and float(q) - _now() <= defaults.INFRA_WAIT_MAX_S:
            return "quota", q, _outcome(S.FAILED.value, code=FC.INFRA.value, detail=codes.InfraReason.QUOTA.value)
        detail = {E.WALL_CLOCK.value: codes.InfraReason.WALL_CLOCK.value,
                  E.NO_OUTPUT.value: codes.InfraReason.NO_OUTPUT.value}.get(
            end, codes.InfraReason.QUOTA.value if q is not None else codes.InfraReason.API.value)
        infra = {"detail": detail, "reset_at": q if detail == codes.InfraReason.QUOTA.value else None}
        return "infra", infra, _outcome(S.NEEDS_LEADER.value, code=FC.INFRA.value, detail=detail,
                                        stop=SR.INFRA_STOP.value)
    errs = check_answer(r.situation, structured, allowed, ids, checklist_acs=checklist,
                        origin_template=r.origin_template, stage=r.stage, inp=inp,
                        followups_made=_followup_ids(r.state))
    if errs:
        return "format", errs, _outcome(S.FAILED.value, code=FC.OUTPUT_FORMAT.value, detail=errs[0][0])
    return "answer", structured, _outcome(S.DONE.value)
