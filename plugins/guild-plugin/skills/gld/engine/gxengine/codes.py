"""Every named kind and fixed code the engine branches on — one module (design §4.1).

The engine branches only on the values defined here, never on free-text fields
(`note` and friends are for humans and evolve). Each enum's string values are the
exact strings that appear in procedure.yaml, state.json, log.jsonl, brief.json,
result.json and facts.json; the JSON Schema files in `schemas/` repeat the same
lists, and `tests/test_contracts.py` checks that the two never drift apart.

Frozen in P2-0 (extended by the stage-2, stage-3 and stage-4 V1 contract changes). Changing a value
here is a contract change: see README "Changing a contract". A value added for a later stage
never changes an earlier stage's table: stage-specific tables are picked by a `stage`
function (allowed_answers_table, leader_situations, leader_answer_schemas, result_schemas,
stage_ops).
"""

import enum


class _Str(str, enum.Enum):
    """A str-valued enum whose members compare equal to their JSON string."""

    def __str__(self):
        return self.value

    @classmethod
    def values(cls):
        return [m.value for m in cls]


# --- procedure grammar (§4) -------------------------------------------------------

class StepKind(_Str):
    """§4 step kinds. A step names its kind by carrying exactly one of these keys."""
    ROLE = "role"     # a role session (claude -p)
    RUN = "run"       # a named command from the repository settings, judged by exit code
    CHECK = "check"   # a planned leader judgment (stage 1: plan-gate is the I1 machine rule)
    OP = "op"         # an engine built-in action


class CheckKind(_Str):
    """§4.1 named check kinds. Stage 1 has no done-gate in the template (§9.2); from stage 2 both are
    leader sessions (scope §2.1, §2.2) and a template with create-pr has exactly one done-gate right
    before it (D19)."""
    PLAN_GATE = "plan-gate"
    DONE_GATE = "done-gate"


class OpKind(_Str):
    """§4 engine built-in actions usable as `op:` steps.

    CREATE_CHILDREN / RUN_CHILDREN belong to the epic template (stage 5) and are
    listed so the grammar does not change later; stage 1 rejects them at plan time.
    """
    CREATE_PR = "create-pr"
    CREATE_FOLLOWUPS = "create-followups"   # stage 3 (E20): right after create-pr, at most once
    CREATE_CHILDREN = "create-children"
    RUN_CHILDREN = "run-children"


STAGE1_OPS = frozenset({OpKind.CREATE_PR.value})
STAGE2_OPS = STAGE1_OPS
"""Stage 2 adds no op (epic ops are stage 5); procedure.py should refuse the others in stage 2 too."""
STAGE3_OPS = STAGE2_OPS | {OpKind.CREATE_FOLLOWUPS.value}
"""Stage 3 (E20): create-pr, create-followups. Epic ops stay refused."""


def check_stage(stage):
    """ValueError unless `stage` is an engine stage number (int ≥ 1, not a bool)."""
    if isinstance(stage, bool) or not isinstance(stage, int) or stage < 1:
        raise ValueError(f"bad stage {stage!r}")


def stage_ops(stage):
    """The `op:` values a procedure of this engine stage may use (fail-closed: epic ops never)."""
    check_stage(stage)
    return STAGE1_OPS if stage == 1 else STAGE2_OPS if stage == 2 else STAGE3_OPS


class PluginCommand(_Str):
    """Plugin check scripts that are fixed entries of the named-command list (§7.10)."""
    AC_FORMAT = "ac-format"
    AC_COVERAGE = "ac-coverage"
    VERIFY_GATE = "verify-gate"
    # stage 3 (E6, E9–E11): implemented in runner.py like verify-gate, no script file
    REPRO_RED = "repro-red"
    SAFETY_NET_PROOF = "safety-net-proof"
    VERIFICATION_FROZEN = "verification-frozen"
    NO_PRODUCTION_CHANGE = "no-production-change"


STAGE2_PLUGIN_COMMANDS = (PluginCommand.AC_FORMAT.value, PluginCommand.AC_COVERAGE.value,
                          PluginCommand.VERIFY_GATE.value)
"""The plugin commands of stages 1–2. The others exist from stage 3 only."""

EVIDENCE_COMMANDS = frozenset({PluginCommand.REPRO_RED.value, PluginCommand.SAFETY_NET_PROOF.value})
"""Evidence runs (review-q0 D1): judged on an OVERLAY tree — a fresh worktree of the recorded
base plus the HEAD blobs of the step's own test files — never on the HEAD tree, so a later fix
commit does not change the verdict and §4.4-3 may run them again. facts.run: evidence, head,
head_rerun, base_run, base_rerun (K8-2)."""

GIT_FACT_COMMANDS = frozenset({PluginCommand.VERIFICATION_FROZEN.value, PluginCommand.NO_PRODUCTION_CHANGE.value})
"""Plugin commands judged by git facts alone (no process). facts.run: paths_check; exit_code 0 / 1."""


class InFile(_Str):
    """Engine-made input files placed in the attempt's `in/` folder (§6.2, §7.12 S7).

    A procedure names them in `inputs` as `in:<name>` (e.g. `in:issue.md`).
    """
    ISSUE = "issue.md"
    LEADER_DECISION = "leader-decision.md"
    FAILURE_SUMMARY = "failure-summary.md"
    REVIEW_DIFF = "review.diff"
    LEADER_INPUT = "leader-input.json"   # stage 2 (D25): the engine facts of one leader call
    REPRO_EVIDENCE = "repro-evidence.md"               # stage 3 (E8)
    BLOCKING_DISCOVERIES = "blocking-discoveries.md"   # stage 3 (E18)
    PR_REVIEW = "pr-review.md"                         # stage 3 (E31)
    GIT_HISTORY = "git-history.md"                     # readiness E4: read-only git facts for analyze


IN_PREFIX = "in:"

STAGE3_IN_FILES = frozenset({InFile.REPRO_EVIDENCE.value, InFile.BLOCKING_DISCOVERIES.value, InFile.PR_REVIEW.value,
                             InFile.GIT_HISTORY.value})
"""`in:` names a procedure may use from stage 3 only (procedure.py refuses them before)."""


class AttemptKind(_Str):
    """`kind` of brief.json / facts.json: a step kind, or a stage-2 needs_leader call (D13).

    A plan-gate / done-gate leader session is an attempt of its `check` step (kind
    `check`, runs/<step>/<attempt>/). A needs_leader call is not a step: kind `leader`,
    folder `<records>/leader/<k>/`, `step` = the step the situation is attached to,
    `attempt` = k (1-based, per Issue).
    """
    ROLE = "role"
    RUN = "run"
    CHECK = "check"
    OP = "op"
    LEADER = "leader"


# --- step state (§5) --------------------------------------------------------------

class StepStatus(_Str):
    """§5 — the eight step states. Failure causes live in records, not here."""
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"          # reason required
    NEEDS_LEADER = "needs_leader"  # stage 2: the leader is called (never produced in stage 1 — §9.2)
    NEEDS_HUMAN = "needs_human"


class FailureCode(_Str):
    """§5.1 failure codes (recorded with every `failed`)."""
    OUTPUT_FORMAT = "output-format"
    SESSION_LIMIT = "session-limit"
    INFRA = "infra"
    CHECK_FAILED = "check-failed"   # the only code on_fail counters count
    ENGINE_ERROR = "engine-error"


COUNTED_BY_ON_FAIL = frozenset({FailureCode.CHECK_FAILED.value})


class CheckFailedReason(_Str):
    """Detail of a `check-failed` (§5.1 table, §6.2 engine table, I5)."""
    RUN_NONZERO = "run-nonzero"
    RUN_TIMEOUT = "run-timeout"
    VERDICT_BLOCK = "verdict-block"
    REQUIRED_CHECK_FAIL = "required-check-fail"   # I5-2
    FOREIGN_OUTPUT = "foreign-output"
    DIRTY_TREE = "dirty-tree"
    RUN_DIRTY_TREE = "run-dirty-tree"
    # stage 3 plugin runs (§2.2, §2.3 of the scope; trees and scopes as decided by review-q0 D1 / D10)
    REPRO_NOT_RED = "repro-not-red"          # the overlay tree was not red twice
    REPRO_SCOPE = "repro-scope"              # the reproduce step's own changes leave {path:test-code}
    NET_SCOPE = "net-scope"                  # … leave {path:safety-net}, or a net file existed on base
    NET_RED_ON_BASE = "net-red-on-base"      # the overlay tree (base + net files) is not green
    VERIFICATION_CHANGED = "verification-changed"
    PRODUCTION_CHANGED = "production-changed"


class OutputFormatReason(_Str):
    """Detail of an `output-format` failure (§6.2 engine table, §7.2-4, I5)."""
    NO_STRUCTURED_OUTPUT = "no-structured-output"
    RESULT_SCHEMA = "result-schema"
    MISSING_OUTPUT = "missing-output"
    OUTPUT_SCHEMA = "output-schema"
    NON_REGULAR_OUTPUT = "non-regular-output"     # symlink etc. (§7.6) — see interfaces.md
    PASS_WITH_BLOCKER = "pass-with-blocker"
    MISSING_CHECK = "missing-check"
    EMPTY_REVIEWED = "empty-reviewed"
    REVIEWED_NOT_COVERING = "reviewed-not-covering"  # I5-1
    REQUIRED_CHECK_NA = "required-check-na"          # I5-2
    UNKNOWN_REQUEST_STEP = "unknown-request-step"    # §4 "command strings in requests"
    MISSING_GOLDEN_REASON = "missing-golden-reason"  # stage 3 (E33)
    # A lone surrogate in a result (review-q0 D9) is RESULT_SCHEMA (schema.surrogate_errors).


class InfraReason(_Str):
    """Detail of an `infra` failure (§5.1, §6.2 session limits, §9.3)."""
    QUOTA = "quota"                 # 429 / resetsAt
    API = "api"
    AUTH = "auth"
    OP_FAILED = "op-failed"
    FACT_COLLECTION = "fact-collection"   # a judgment fact could not be collected
    WALL_CLOCK = "wall-clock"
    NO_OUTPUT = "no-output"


class StopReason(_Str):
    """Why an issue stopped at needs_leader / needs_human (§5.1, §6, §7.4, §7.6, §7.12).

    LEADER_SITUATIONS are the §6.3 situations: needs_leader from stage 2, needs_human
    in stage 1 (§9.2). Everything else is a mechanical stop that always goes to a human.
    """
    # §6.3 leader situations
    PLAN_GATE = "plan-gate"                 # stage 1: the I1 rule tripped
    BLOCKED = "blocked"                     # role result status: blocked
    OUTPUT_FORMAT_TWICE = "output-format-twice"
    SESSION_LIMIT = "session-limit"
    ON_FAIL_EXCEEDED = "on-fail-exceeded"   # also: a failed step without on_fail
    SOFT_BUDGET = "soft-budget"
    NEW_COMMENT = "new-collaborator-comment"
    DONE_GATE = "done-gate"
    RULE_UNFILLABLE = "rule-unfillable"     # §7 a mandatory step cannot be supplied
    BASE_RED = "base-red"                   # I8: the recorded base is red too
    # stage 3 leader situations (STAGE3_LEADER_SITUATIONS; never produced before stage 3)
    STEP_ADD_LIMIT = "step-add-limit"               # E15
    STEP_REMOVAL_REQUEST = "step-removal-request"   # E13
    PR_REVIEW = "pr-review"                         # E31
    # mechanical stops (always needs_human)
    CONTROL_FILE = "control-file"
    JUDGE_WROTE_OUTSIDE = "judge-wrote-outside-outputs"
    # (INIT_MISMATCH "init-mismatch" — removed by FC decision D, 2026-11-28: no system/init comparison)
    CANARY_FAILED = "canary-failed"
    SELF_CHECK_FAILED = "self-check-failed"   # srt empty command failed (§7.6, F4)
    UNSAFE_PATH = "unsafe-path"               # fsafe met a link / non-regular file (S6)
    SECRET_DETECTED = "secret-detected"
    CLOSE_KEYWORD = "close-keyword"           # S10
    REMOTE_DIVERGED = "remote-diverged"       # non-fast-forward push
    ABSOLUTE_LIMIT = "absolute-limit"         # absolute budget / total attempts / leader calls
    INFRA_STOP = "infra-stop"                 # infra that is not a short quota wait
    ENGINE_ERROR = "engine-error"
    FORMAT_MISMATCH = "format-mismatch"       # unconvertible file `format`
    STABLE_LABEL = "stable-label"             # the Issue carries a stable-Guild stage label
    IRREVERSIBLE_CHANGE = "irreversible-change"   # stage 3 (E23): human only, the leader is never called
    NOT_REPRODUCED = "not-reproduced"             # readiness E4: repro-red not red after its retries — a human's
    # readiness T1 (first promotion guards; start refusals of stage >= 4 — never a state.stop, so no answer)
    UNSUPPORTED_EPIC = "unsupported-epic"     # P3: the Issue is an epic (<prefix>children) — develop its children
    OPEN_CLOSING_PR = "open-closing-pr"       # P2: an open pull request (any branch) already closes the new Issue
    DONE_UNCONFIRMED = "done-unconfirmed"     # R4-12: <prefix>done on an open Issue, no engine record, no open PR


LEADER_SITUATIONS = frozenset(r.value for r in (
    StopReason.PLAN_GATE, StopReason.BLOCKED, StopReason.OUTPUT_FORMAT_TWICE,
    StopReason.SESSION_LIMIT, StopReason.ON_FAIL_EXCEEDED, StopReason.SOFT_BUDGET,
    StopReason.NEW_COMMENT, StopReason.DONE_GATE, StopReason.RULE_UNFILLABLE,
    StopReason.BASE_RED,
))
"""The stage-2 set (unchanged by stage 3 — use leader_situations(stage))."""

STAGE3_LEADER_SITUATIONS = LEADER_SITUATIONS | {
    StopReason.STEP_ADD_LIMIT.value, StopReason.STEP_REMOVAL_REQUEST.value, StopReason.PR_REVIEW.value}


def leader_situations(stage):
    """§6.3 leader situations of an engine stage (stage 1: the same set, always needs_human)."""
    check_stage(stage)
    return LEADER_SITUATIONS if stage < 3 else STAGE3_LEADER_SITUATIONS


# --- leader answers (§6.3) — the stage-2 leader seat and the human in its place -------

class LeaderAnswer(_Str):
    PLAN = "plan"
    CLOSE_AS_DECIDED = "close-as-decided"
    ESCALATE = "escalate"
    RERUN = "rerun"
    REPLAN = "replan"
    CONTINUE = "continue"
    APPROVE = "approve"
    SKIP = "skip"        # stage 3 (E13): step-removal-request only, with skip_step (review-q0 D7)


ALLOWED_ANSWERS = {
    StopReason.PLAN_GATE.value: ("plan", "close-as-decided", "escalate"),
    StopReason.BLOCKED.value: ("rerun", "replan", "escalate"),
    StopReason.OUTPUT_FORMAT_TWICE.value: ("rerun", "replan", "escalate"),
    StopReason.SESSION_LIMIT.value: ("rerun", "replan", "escalate"),
    StopReason.ON_FAIL_EXCEEDED.value: ("rerun", "replan", "escalate"),
    StopReason.SOFT_BUDGET.value: ("rerun", "replan", "escalate"),
    StopReason.NEW_COMMENT.value: ("continue", "rerun", "replan", "escalate"),
    StopReason.DONE_GATE.value: ("approve", "rerun", "escalate"),
}
"""§6.3 table as used in stage 1 (I10): the human answers in the leader's seat with it
(lifecycle.allowed_answers drops STAGE2 answers in stage 1). Unchanged by the stage-2
contract so the stage-1 path stays identical; stage 2 uses STAGE2_ALLOWED_ANSWERS."""

STAGE2_ALLOWED_ANSWERS = {
    StopReason.PLAN_GATE.value: ("plan", "rerun", "close-as-decided", "escalate"),   # D3: rerun analyze only
    StopReason.BLOCKED.value: ("rerun", "replan", "escalate"),
    StopReason.OUTPUT_FORMAT_TWICE.value: ("rerun", "replan", "escalate"),
    StopReason.SESSION_LIMIT.value: ("rerun", "replan", "escalate"),
    StopReason.ON_FAIL_EXCEEDED.value: ("rerun", "replan", "escalate"),
    StopReason.SOFT_BUDGET.value: ("rerun", "replan", "escalate"),
    StopReason.NEW_COMMENT.value: ("continue", "rerun", "replan", "escalate"),
    StopReason.DONE_GATE.value: ("approve", "rerun", "escalate"),
    StopReason.RULE_UNFILLABLE.value: ("escalate",),           # D9 — §7: nobody lifts a rule
    StopReason.BASE_RED.value: ("rerun", "escalate"),          # rerun = a human fixed the base / quarantine
}
"""Stage-2 §6.3 table, BOTH seats before narrowing (scope D3, D9, D17). The human (resume)
gets exactly this row (D17: no D4 narrowing). The leader gets this row minus
LEADER_REMOVED_ANSWERS minus the dynamic NARROWING rules; when only `escalate` is left the
leader is not called (D9) and the stop goes to needs_human without a recommendation."""

STAGE3_ALLOWED_ANSWERS = dict(STAGE2_ALLOWED_ANSWERS, **{
    # K8-3: an analysis that finds the Issue already settled; gone once a developer step has run (both seats)
    StopReason.BLOCKED.value: ("rerun", "replan", "close-as-decided", "escalate"),
    StopReason.STEP_ADD_LIMIT.value: ("continue", "escalate"),
    StopReason.STEP_REMOVAL_REQUEST.value: ("skip", "continue", "escalate"),
    StopReason.PR_REVIEW.value: ("continue", "rerun", "escalate"),
    StopReason.IRREVERSIBLE_CHANGE.value: ("continue", "rerun"),   # E23: a human's row — no leader seat
    # readiness E4: a human's row — the engine never concludes "already fixed"; no `continue` (no fix without
    # the red reproduction), no `replan` (the bug template stays, L22)
    StopReason.NOT_REPRODUCED.value: ("rerun", "close-as-decided", "escalate"),
})
"""Stage-3 §6.3 table (E35), BOTH seats before narrowing. The stage-2 rows are unchanged but blocked
(K8-3 close-as-decided; done-gate has no replan — E34). irreversible-change is a mechanical stop: the row is the human's only
(it is not in STAGE3_LEADER_SITUATIONS and has no answer schema)."""

LEADER_REMOVED_ANSWERS = {
    StopReason.BASE_RED.value: ("rerun",),   # D9: red cannot be turned into a pass; quarantine is human-only (§7.10)
}
"""Answers the leader seat never has, whatever the state (static part of D9)."""

RECOMMENDATION_REMOVED_ANSWERS = {
    StopReason.STEP_REMOVAL_REQUEST.value: ("skip",),
}
"""Answers `recommendation.answer` never offers: `skip` needs a step of its own (skip_step) and the
recommendation has only the rerun step; a leader that wants skip answers it directly."""


def allowed_answers_table(stage):
    """The §6.3 table of an engine stage: ALLOWED_ANSWERS (1), STAGE2_ALLOWED_ANSWERS (2) or
    STAGE3_ALLOWED_ANSWERS (≥ 3)."""
    check_stage(stage)
    return ALLOWED_ANSWERS if stage < 2 else STAGE2_ALLOWED_ANSWERS if stage < 3 else STAGE3_ALLOWED_ANSWERS


LEADER_CALL_COUNTED = frozenset(r.value for r in (
    StopReason.BLOCKED, StopReason.OUTPUT_FORMAT_TWICE, StopReason.SESSION_LIMIT,
    StopReason.ON_FAIL_EXCEEDED, StopReason.SOFT_BUDGET,
    StopReason.STEP_ADD_LIMIT, StopReason.STEP_REMOVAL_REQUEST,      # stage 3 (E35)
))
"""D14: the situations counted against defaults.LEADER_CALLS_MAX. plan-gate, done-gate,
new-collaborator-comment and pr-review (stage 3) are not counted (§5.1 — planned, or called by a
human's input); format retries are the same call."""

LEADER_FAILED_CODES = frozenset({"output-format", "session-limit"})
"""D12: `state.stop.leader_failed.code` values (FailureCode values). A leader boundary
failure is a mechanical stop instead; infra is a wait or `infra-stop`."""


class NarrowReason(_Str):
    """Why the engine took an answer out of the leader's enum (D4, D7, D8, D14 — scope §2).

    Each value removes the answers listed in NARROWING; `leader-input.json`
    `allowed.narrowed[]` names the ones that applied. Never applied to the human (D17).
    """
    # plan-gate — analysis.md structure fields (acparse.parse_analysis), D4
    TYPE_NOT_FEATURE = "type-not-feature"
    SPLIT_PROPOSED = "split-proposed"
    PREREQUISITE_OPEN = "prerequisite-open"
    RISK_HIGH = "risk-high"                     # D4 conservative (coordinator memo, pending A2)
    UNATTENDED_NO_DECISION = "unattended-no-decision-marker"   # D18
    PLAN_RERUN_USED = "plan-rerun-used"         # D3: defaults.PLAN_GATE_RERUN_MAX
    # done-gate
    DONE_RERUN_USED = "done-rerun-used"         # D7: defaults.DONE_GATE_RERUN_MAX
    # needs_leader
    ON_FAIL_RERUN_USED = "on-fail-rerun-used"   # §6.3: one on-fail-exceeded rerun per Issue
    SOFT_BUDGET_RERUN_USED = "soft-budget-rerun-used"
    PLAN_NOT_DONE = "plan-not-done"             # D8: replan = back_to plan, only when plan is done
    NO_RERUN_TARGET = "no-rerun-target"         # the rerun target list came out empty
    # stage 3
    NO_TEMPLATE_FOR_TYPE = "no-template-for-type"   # E2: TYPE_TEMPLATES has no row (replaces type-not-feature)
    TEMPLATE_UNUSABLE = "template-unusable"         # E2: every template of the row fails procedure.check
    DEFER_USED = "defer-used"                       # E30: defaults.DEFER_MAX — the `defer` field is not rendered
    NO_SKIPPABLE_STEP = "no-skippable-step"         # E13: {skippable_steps} came out empty
    FOLLOWUP_CAP = "followup-cap"                   # E19: state.followups is at FOLLOWUPS_MAX already
    DEVELOPER_STARTED = "developer-started"         # K8-3: a developer step has run (or it is not known)
    CLOSE_RISK = "close-risk"                       # K8-3: blocked — the committed analysis says risk high (or no risk)
    # readiness E4 (#1910): a bug Issue (label / analysis record) may not be planned on a template without repro-red
    BUG_WITHOUT_REPRO = "bug-without-repro-red"


NARROWING = {
    NarrowReason.TYPE_NOT_FEATURE.value: ("plan",),
    NarrowReason.SPLIT_PROPOSED.value: ("plan",),
    NarrowReason.PREREQUISITE_OPEN.value: ("plan",),
    # D4 conservative: risk=high is a human decision. Removing rerun / close too leaves only
    # escalate, so D9 applies (no leader call, straight needs_human) — and the leader cannot
    # get round it by sending analyze back until the risk field reads low.
    NarrowReason.RISK_HIGH.value: ("plan", "rerun", "close-as-decided"),
    NarrowReason.UNATTENDED_NO_DECISION.value: ("close-as-decided",),
    NarrowReason.PLAN_RERUN_USED.value: ("rerun",),
    NarrowReason.DONE_RERUN_USED.value: ("rerun",),
    NarrowReason.ON_FAIL_RERUN_USED.value: ("rerun",),
    NarrowReason.SOFT_BUDGET_RERUN_USED.value: ("rerun",),
    NarrowReason.PLAN_NOT_DONE.value: ("replan",),
    NarrowReason.NO_RERUN_TARGET.value: ("rerun",),
    NarrowReason.NO_TEMPLATE_FOR_TYPE.value: ("plan",),
    NarrowReason.TEMPLATE_UNUSABLE.value: ("plan",),
    NarrowReason.DEFER_USED.value: (),              # narrows a field, not an answer (NARROWING_FIELDS)
    NarrowReason.NO_SKIPPABLE_STEP.value: ("skip",),
    NarrowReason.FOLLOWUP_CAP.value: (),            # narrows a field
    NarrowReason.DEVELOPER_STARTED.value: ("close-as-decided",),
    NarrowReason.CLOSE_RISK.value: ("close-as-decided",),    # A2 / RISK_HIGH for blocked: closing it is a human's
    NarrowReason.BUG_WITHOUT_REPRO.value: ("plan",),
}
"""NarrowReason → answers it removes from the leader's enum (the order of the table row is kept)."""

NARROWING_FIELDS = {
    NarrowReason.DEFER_USED.value: "defer",         # {requirement_rows} of `defer` = [] → the field is dropped
    NarrowReason.FOLLOWUP_CAP.value: "followup",    # `followup` leaves {dispositions}
}
"""Stage 3: NarrowReason → what it removes when it removes no answer (leader-input `narrowed[].field`)."""

NARROWING_SITUATIONS = {
    NarrowReason.TYPE_NOT_FEATURE.value: (StopReason.PLAN_GATE.value,),
    NarrowReason.SPLIT_PROPOSED.value: (StopReason.PLAN_GATE.value,),
    NarrowReason.PREREQUISITE_OPEN.value: (StopReason.PLAN_GATE.value,),
    NarrowReason.RISK_HIGH.value: (StopReason.PLAN_GATE.value,),
    NarrowReason.UNATTENDED_NO_DECISION.value: (StopReason.PLAN_GATE.value, StopReason.BLOCKED.value),   # blocked: K8-3
    NarrowReason.PLAN_RERUN_USED.value: (StopReason.PLAN_GATE.value,),
    NarrowReason.DONE_RERUN_USED.value: (StopReason.DONE_GATE.value,),
    NarrowReason.ON_FAIL_RERUN_USED.value: (StopReason.ON_FAIL_EXCEEDED.value,),
    NarrowReason.SOFT_BUDGET_RERUN_USED.value: (StopReason.SOFT_BUDGET.value,),
    # computed from the stage-3 table (its stage-2 rows are the stage-2 table's); irreversible-change
    # has no leader seat, so nothing narrows there
    NarrowReason.PLAN_NOT_DONE.value: tuple(sorted(
        s for s, a in STAGE3_ALLOWED_ANSWERS.items() if "replan" in a and s in STAGE3_LEADER_SITUATIONS)),
    NarrowReason.NO_RERUN_TARGET.value: tuple(sorted(
        s for s, a in STAGE3_ALLOWED_ANSWERS.items() if "rerun" in a and s in STAGE3_LEADER_SITUATIONS)),
    NarrowReason.NO_TEMPLATE_FOR_TYPE.value: (StopReason.PLAN_GATE.value,),
    NarrowReason.TEMPLATE_UNUSABLE.value: (StopReason.PLAN_GATE.value,),
    NarrowReason.DEFER_USED.value: tuple(sorted(r.value for r in (
        StopReason.BLOCKED, StopReason.OUTPUT_FORMAT_TWICE, StopReason.SESSION_LIMIT,
        StopReason.ON_FAIL_EXCEEDED, StopReason.SOFT_BUDGET))),
    NarrowReason.NO_SKIPPABLE_STEP.value: (StopReason.STEP_REMOVAL_REQUEST.value,),
    NarrowReason.FOLLOWUP_CAP.value: (StopReason.DONE_GATE.value,),
    NarrowReason.DEVELOPER_STARTED.value: (StopReason.BLOCKED.value,),
    NarrowReason.CLOSE_RISK.value: (StopReason.BLOCKED.value,),
    NarrowReason.BUG_WITHOUT_REPRO.value: (StopReason.PLAN_GATE.value,),
}
"""Where each NarrowReason may apply (leader.allowed_answers refuses any other use)."""


LEADER_ANSWER_SCHEMAS = {
    StopReason.PLAN_GATE.value: "leader-answer-plan-gate",
    StopReason.DONE_GATE.value: "leader-answer-done-gate",
    StopReason.NEW_COMMENT.value: "leader-answer-new-comment",
    StopReason.BLOCKED.value: "leader-answer",
    StopReason.OUTPUT_FORMAT_TWICE.value: "leader-answer",
    StopReason.SESSION_LIMIT.value: "leader-answer",
    StopReason.ON_FAIL_EXCEEDED.value: "leader-answer",
    StopReason.SOFT_BUDGET.value: "leader-answer",
}
"""Situation → the answer-schema TEMPLATE in schemas/ (scope §2.0: common envelope, plus the
situation fields for three situations). rule-unfillable / base-red have none: the leader is
never called there (D9). The templates carry enum tokens (LEADER_SCHEMA_TOKENS) that
schema.fill_enums replaces per call. Stage 2 — unchanged by stage 3: use leader_answer_schemas(stage)."""

STAGE3_LEADER_ANSWER_SCHEMAS = {
    StopReason.PLAN_GATE.value: "leader-answer-plan-gate-s3",
    StopReason.DONE_GATE.value: "leader-answer-done-gate-s3",
    StopReason.NEW_COMMENT.value: "leader-answer-new-comment",        # unchanged
    StopReason.BLOCKED.value: "leader-answer-s3",
    StopReason.OUTPUT_FORMAT_TWICE.value: "leader-answer-s3",
    StopReason.SESSION_LIMIT.value: "leader-answer-s3",
    StopReason.ON_FAIL_EXCEEDED.value: "leader-answer-s3",
    StopReason.SOFT_BUDGET.value: "leader-answer-s3",
    StopReason.STEP_ADD_LIMIT.value: "leader-answer-s3",
    StopReason.STEP_REMOVAL_REQUEST.value: "leader-answer-step-removal",
    StopReason.PR_REVIEW.value: "leader-answer-pr-review",
}
"""Stage-3 situation → answer-schema template. The stage-2 files stay as they are (stage 2 renders
them with the stage-2 tokens); the `-s3` files are the same envelope + the stage-3 fields."""


def leader_answer_schemas(stage):
    """Situation → answer-schema template name for an engine stage ≥ 2."""
    check_stage(stage)
    if stage < 2:
        raise ValueError("no leader before stage 2")
    return LEADER_ANSWER_SCHEMAS if stage < 3 else STAGE3_LEADER_ANSWER_SCHEMAS


LEADER_SCHEMA_TOKENS = (
    "{answers}",              # the narrowed allowed answers
    "{rerun_steps}",          # rerun targets of this call (may be empty → step only null)
    "{human_answers}",        # recommendation.answer: the human's answers (STAGE2 row)
    "{human_rerun_steps}",    # recommendation.step
    "{requirement_rows}",     # plan-gate: R1..Rn
    "{templates}",            # plan-gate: usable templates
    "{ac_ids}",               # done-gate: AC ids
    "{discovery_ids}",        # done-gate: D1..Dn (may be empty → property dropped)
    "{comment_ids}",          # new comment: GitHub comment ids (integers)
    # stage 3 ("{requirement_rows}" also fills `defer` of leader-answer-s3: [] = not offered)
    "{catalog_steps}",        # plan-gate adjust: catalog ids this repository can run (may be empty → adjust dropped)
    "{plan_role_steps}",      # plan-gate models: role steps of the usable templates (union)
    "{models}",               # plan-gate models / rerun session: the repository's model allow-list ([] = not offered)
    "{efforts}",              # … the effort allow-list
    "{fix_ids}",              # done-gate: F1..Fn (may be empty → property dropped)
    "{dispositions}",         # done-gate: the DiscoveryDisposition values offered
    "{candidate_issues}",     # done-gate duplicate_of: issue numbers (integers; may be empty → only null)
    "{skippable_steps}",      # step-removal-request (may be empty → only null)
    "{review_ids}",           # pr-review: "<PrReviewKind>:<GitHub id>"
    "{close_reasons}",        # leader-answer-s3 close.reason: CloseReason where close-as-decided is offered (blocked, K8-3), else []
)

RESULT_SCHEMA_TOKENS = ("{catalog_steps}",)
"""Tokens of the stage-3 result templates result-work-s3 / result-review-s3 (E16): every catalog id
except the fix class (fix-discovery)."""

RESULT_SCHEMAS = {"work": "result-work", "review": "result-review"}
STAGE3_RESULT_SCHEMAS = {"work": "result-work-s3", "review": "result-review-s3"}


def result_schemas(stage):
    """ResultKind value → result-schema name (stage ≥ 3: an enum TEMPLATE — RESULT_SCHEMA_TOKENS)."""
    check_stage(stage)
    return RESULT_SCHEMAS if stage < 3 else STAGE3_RESULT_SCHEMAS


class LeaderFormatReason(_Str):
    """Named detail of a rejected leader answer (D12 → `leader_failed.detail`, retry errors).

    Order of checks (scope §2.0): schema → combination rules → situation rules.
    """
    NO_STRUCTURED_OUTPUT = "no-structured-output"
    ANSWER_SCHEMA = "answer-schema"                       # the rendered schema refused it
    # combination rules (§2.0)
    RERUN_STEP_MISMATCH = "rerun-step-mismatch"           # answer=rerun ⇔ step ≠ null
    ESCALATE_RECOMMENDATION_MISMATCH = "escalate-recommendation-mismatch"   # escalate ⇔ recommendation
    # plan-gate (D5, D18, D1)
    REQUIREMENTS_NOT_COVERING = "requirements-not-covering"   # every R row exactly once
    PLAN_WITH_GAP = "plan-with-gap"                       # plan with covered=false / missing requirements
    PLAN_MISMATCH = "plan-mismatch"                       # answer=plan ⇔ plan ≠ null
    CLOSE_MISMATCH = "close-mismatch"                     # answer=close-as-decided ⇔ close ≠ null (plan-gate; blocked K8-3)
    TEMPLATE_MISMATCH = "template-mismatch"               # L22: a stage-1 state's plan must name origin.template
    # done-gate (D6)
    AC_NOT_COVERING = "ac-not-covering"
    DISCOVERIES_NOT_COVERING = "discoveries-not-covering"
    APPROVE_WITH_UNMET = "approve-with-unmet"
    APPROVE_WITH_INCLUDE = "approve-with-include"
    MANUAL_NOT_IN_CHECKLIST = "manual-not-in-checklist"
    # new collaborator comment (D16)
    COMMENTS_NOT_COVERING = "comments-not-covering"
    CONTINUE_WITH_EFFECT = "continue-with-effect"
    ADDS_REQUIREMENT_NOT_ANALYZE = "adds-requirement-not-analyze"
    # stage 3
    ADJUST_INVALID = "adjust-invalid"                     # plan-gate (E12): a step twice / over CATALOG_ADDS_MAX
    MODELS_INVALID = "models-invalid"                     # plan-gate models (E12), rerun session (E28)
    FIXES_NOT_COVERING = "fixes-not-covering"             # done-gate (E18): every F id exactly once
    APPROVE_WITH_OUT_OF_SCOPE = "approve-with-out-of-scope"
    FOLLOWUP_TITLE_MISMATCH = "followup-title-mismatch"   # done-gate (E19): followup ⇔ title ≠ null
    DUPLICATE_MISMATCH = "duplicate-mismatch"             # duplicate ⇔ duplicate_of ≠ null
    FOLLOWUP_OVER_CAP = "followup-over-cap"
    DEFER_INVALID = "defer-invalid"                       # E30
    REVIEWS_NOT_COVERING = "reviews-not-covering"         # pr-review (E31)
    CONTINUE_WITH_CHANGE_REQUEST = "continue-with-change-request"
    SKIP_STEP_MISMATCH = "skip-step-mismatch"             # step-removal (review-q0 D7): skip ⇔ skip_step ≠ null
    MANUAL_REASON_MISMATCH = "manual-reason-mismatch"     # done-gate (E5): manual ⇔ why_not_automated non-blank
    SUMMARY_INVALID = "summary-invalid"                   # done-gate: ≤ SUMMARY_LINES_MAX non-blank lines, approve ≥ 1
    # A lone surrogate in an answer (review-q0 D9) is ANSWER_SCHEMA (schema.surrogate_errors).


STAGE3_LEADER_FORMAT_REASONS = frozenset(r.value for r in (
    LeaderFormatReason.ADJUST_INVALID, LeaderFormatReason.MODELS_INVALID, LeaderFormatReason.FIXES_NOT_COVERING,
    LeaderFormatReason.APPROVE_WITH_OUT_OF_SCOPE, LeaderFormatReason.FOLLOWUP_TITLE_MISMATCH,
    LeaderFormatReason.DUPLICATE_MISMATCH, LeaderFormatReason.FOLLOWUP_OVER_CAP, LeaderFormatReason.DEFER_INVALID,
    LeaderFormatReason.REVIEWS_NOT_COVERING, LeaderFormatReason.CONTINUE_WITH_CHANGE_REQUEST,
    LeaderFormatReason.SKIP_STEP_MISMATCH, LeaderFormatReason.MANUAL_REASON_MISMATCH,
    LeaderFormatReason.SUMMARY_INVALID))
"""The reasons only a stage ≥ 3 answer can have."""


class CloseReason(_Str):
    """plan-gate `close.reason` (D18) → `gh issue close --reason completed|"not planned"`."""
    COMPLETED = "completed"
    NOT_PLANNED = "not-planned"


GH_CLOSE_REASON = {CloseReason.COMPLETED.value: "completed", CloseReason.NOT_PLANNED.value: "not planned"}


class CommentEffect(_Str):
    """new-collaborator-comment `comments[].effect` (D16)."""
    NONE = "none"
    CORRECTS_ASSUMPTION = "corrects-assumption"
    ADDS_REQUIREMENT = "adds-requirement"
    INSTRUCTION = "instruction"


class AcVerdict(_Str):
    """done-gate `ac_verdicts[].status` (D6)."""
    MET = "met"
    UNMET = "unmet"
    MANUAL = "manual"


class DiscoveryDisposition(_Str):
    """done-gate `discoveries[].disposition` (D6, D6-2: recorded / PR body only in stage 2;
    stage 3, E19: create-followups acts on followup / duplicate)."""
    FOLLOWUP = "followup"
    IGNORE = "ignore"
    INCLUDE = "include"
    DUPLICATE = "duplicate"      # stage 3: offered only with a candidate issue


STAGE2_DISPOSITIONS = (DiscoveryDisposition.FOLLOWUP.value, DiscoveryDisposition.IGNORE.value,
                       DiscoveryDisposition.INCLUDE.value)


class FixVerdict(_Str):
    """done-gate `included_fixes[].verdict` (E18, R1-34) — every included fix F1..Fn."""
    KEEP = "keep"
    OUT_OF_SCOPE = "out-of-scope"


class ReviewEffect(_Str):
    """pr-review `reviews[].effect` (E31)."""
    NONE = "none"
    CHANGE_REQUEST = "change-request"
    QUESTION = "question"


class PrReviewKind(_Str):
    """Where a PR review item comes from; its id is `<kind>:<GitHub id>` (three id spaces)."""
    REVIEW = "review"                   # pulls/<n>/reviews
    REVIEW_COMMENT = "review-comment"   # pulls/<n>/comments
    COMMENT = "comment"                 # issues/<n>/comments


# --- change reasons (§4.2) — two short lists, both with `other` ---------------------

class Trigger(_Str):
    """① change-reason codes (adding/removing steps)."""
    UI_CHANGE = "ui-change"
    NEW_DEPENDENCY = "new-dependency"
    SCHEMA_CHANGE = "schema-change"
    SECURITY_SURFACE = "security-surface"
    NO_USER_FACING_TEXT = "no-user-facing-text"
    # stage 3 (E16)
    USER_FACING_TEXT = "user-facing-text"
    PERFORMANCE_RISK = "performance-risk"
    INFRA_CHANGE = "infra-change"
    BLOCKING_DISCOVERY = "blocking-discovery"
    SCOPE_QUESTION = "scope-question"
    OTHER = "other"


STAGE2_TRIGGERS = (Trigger.UI_CHANGE.value, Trigger.NEW_DEPENDENCY.value, Trigger.SCHEMA_CHANGE.value,
                   Trigger.SECURITY_SURFACE.value, Trigger.NO_USER_FACING_TEXT.value, Trigger.OTHER.value)
"""The `requests[].trigger` values of the stage 1–2 result schemas (unchanged)."""


class LeaderReason(_Str):
    """② leader-decision reason codes (§4.2) — M5 closed by stage-2 scope D20.

    Used by the leader's `reason` and by a human answer (`resume --reason`). evolve reads
    the `other` pile for new candidates (§4.2).
    """
    FITS_TEMPLATE = "fits-template"                 # plan
    ANALYSIS_GAP = "analysis-gap"                   # analysis / AC / type does not match the Issue → rerun analyze
    ASSUMPTION_CORRECTED = "assumption-corrected"   # a collaborator corrected an assumption
    COMMENT_NO_EFFECT = "comment-no-effect"         # continue after a new comment
    REAL_DEFECT = "real-defect"                     # the work is wrong → same step / developer again
    UPSTREAM_GAP = "upstream-gap"                   # an earlier step's output is weak → that step again
    TRANSIENT = "transient"                         # format / passing cause — once more
    ENV_PROBLEM = "env-problem"                     # environment / base / infra — a human
    NEEDS_HUMAN_DECISION = "needs-human-decision"   # value / scope / authority / information — a human
    ALREADY_DECIDED = "already-decided"             # close-as-decided
    ACCEPTANCE_MET = "acceptance-met"               # approve
    HIGH_COMPLEXITY = "high-complexity"             # §7.9 example — kept for stage 3 model raises
    REPEATED_FAILURE = "repeated-failure"           # §7.9 example — kept for stage 3 model raises
    OTHER = "other"


# --- role results (§6.2, §7.5) ----------------------------------------------------

class ResultStatus(_Str):
    DONE = "done"
    BLOCKED = "blocked"


class BlockedKind(_Str):
    MISSING_INPUT = "missing-input"
    AMBIGUOUS = "ambiguous"
    ENV = "env"
    OTHER = "other"


class RequestOp(_Str):
    ADD = "add"
    REMOVE = "remove"
    SKIP = "skip"


class DiscoveryKind(_Str):
    BUG = "bug"
    DEBT = "debt"
    SECURITY = "security"
    TEST_GAP = "test-gap"
    DOC = "doc"


class Verdict(_Str):
    PASS = "pass"
    BLOCK = "block"


class CheckResult(_Str):
    PASS = "pass"
    FAIL = "fail"
    NA = "n/a"


class Severity(_Str):
    BLOCKER = "blocker"
    MAJOR = "major"
    MINOR = "minor"


class ResultKind(_Str):
    """Which of the two result schemas a step gets (§4 `checks`, §6.2)."""
    WORK = "work"
    REVIEW = "review"


class RequestOutcome(_Str):
    """Stage 3 (E13, E15): how the engine ended a role's change request (`state.requests[].outcome`)."""
    APPLIED = "applied"
    NOOP = "noop"
    DECLINED = "declined"
    DEFERRED_TO_PLAN = "deferred-to-plan"
    PENDING = "pending"        # waits for step-add-limit / step-removal-request
    SKIPPED = "skipped"        # a remove / skip request answered `skip`


class RequestReason(_Str):
    """`state.requests[].reason` — set with noop / declined / pending, else null."""
    ALREADY_PRESENT = "already-present"     # noop
    ROLE_UNAVAILABLE = "role-unavailable"   # declined …
    POSITION = "position"
    GRAMMAR = "grammar"
    LIMIT = "limit"                         # pending, then declined by the leader's continue
    REMOVAL = "removal"                     # pending (step-removal-request)
    REFUSED = "refused"                     # declined: a remove / skip request answered `continue`


class ProcedureSource(_Str):
    """log `procedure-written` `data.source` (TX3): what made this revision."""
    START = "start"                          # revision 1 (the start procedure)
    LEADER_PLAN = "leader-plan"              # the plan answer, adjust included (either seat)
    ROLE_REQUEST = "role-request"
    MANDATORY_RULE = "mandatory-rule"
    BLOCKING_DISCOVERY = "blocking-discovery"


class CatalogClass(_Str):
    """Step-catalog entry classes (E14) — the class fixes the position (catalog.position)."""
    DESIGN_TIME = "design-time"
    DIFF_REVIEW = "diff-review"
    FIX = "fix"


CATALOG_DEVELOPER_TOKEN = "@developer"
"""catalog.json `on_fail.back_to`: the developer step (E5, D4) at insertion time."""

LEADER_SKIP_REASON = "leader-skip"
"""`state.steps[].reason` of a step skipped by the `skip` answer (E13)."""


class ReturnCause(_Str):
    """Why a step was made `pending` as the TARGET of a return (E26 — each one counts in
    `state.steps[].returns`). §4.4-3 re-verification, being reset by another step's return and
    output-format retries are no return."""
    ON_FAIL = "on-fail"              # its own on_fail, another step's on_fail, I3
    LEADER_RERUN = "leader-rerun"
    HUMAN_RERUN = "human-rerun"


class ModelLayer(_Str):
    """Which §7.9 layer gave the base model / effort (E26, E28)."""
    PLUGIN_DEFAULT = "plugin-default"   # layer 1
    PLAN = "plan"                       # layer 4: plan-gate plan.models
    LEADER = "leader"                   # layer 5: rerun.session


class RequiredCheck(_Str):
    """Check ids the mandatory rules (§7) add by themselves."""
    TEST_CHANGE_REVIEW = "test-change-review"


# --- roles, sessions, settings ----------------------------------------------------

class RoleClass(_Str):
    """I4 — developer is the only work role; every other role (incl. leader) judges."""
    WORK = "work"
    JUDGE = "judge"


WORK_ROLES = frozenset({"developer"})


def role_class(role):
    """Return the RoleClass value of a role name (I4)."""
    return RoleClass.WORK.value if role in WORK_ROLES else RoleClass.JUDGE.value


class AnalysisType(_Str):
    """`analysis.md` issue type written by requirements-engineer (§3.1, I1)."""
    FEATURE = "feature"
    BUG = "bug"
    REFACTOR = "refactor"
    DOCS = "docs"
    CHORE = "chore"


class SafetyNet(_Str):
    """`analysis.md` machine field `safety_net` (E3, stage 3). Anything but none needs type refactor."""
    NONE = "none"
    WITH_REFACTOR = "with-refactor"
    ONLY = "only"


STAGE3_TEMPLATES = ("feature", "bug", "refactor", "refactor-net", "safety-net")

TYPE_TEMPLATES = {
    ("feature", "none"): ("feature",),
    ("bug", "none"): ("bug",),
    ("refactor", "none"): ("refactor",),
    ("refactor", "with-refactor"): ("refactor-net",),
    ("refactor", "only"): ("safety-net",),
    ("docs", "none"): (),
    ("chore", "none"): (),
}
"""E2: (analysis type, safety_net) → the templates the leader may choose. () or no row = no
template (NarrowReason no-template-for-type). The human may choose any of STAGE3_TEMPLATES."""


def templates_for(analysis_type, safety_net):
    """TYPE_TEMPLATES row of an analysis, () when there is none (fail-closed)."""
    return TYPE_TEMPLATES.get((analysis_type, safety_net), ())


class Size(_Str):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


class Risk(_Str):
    LOW = "low"
    HIGH = "high"


class PathRuleKind(_Str):
    """Repository-settings path rule kinds (§7.4, §7.10, §7.11)."""
    VERIFICATION = "verification"
    RISK = "risk"                 # risk area (security/auth, data migration, …) → a gate step
    IRREVERSIBLE = "irreversible"  # kinds of hard-to-revert change → a handling level
    TEST_CODE = "test-code"       # stage 3 (E4): test source files only (no goldens, no config)
    SAFETY_NET = "safety-net"     # stage 3 (E4): the naming rule of safety-net-only test files


TEMPLATE_PATH_KINDS = (PathRuleKind.TEST_CODE.value, PathRuleKind.SAFETY_NET.value)
"""The kinds a template may name as `{path:<kind>}` (E4)."""


def path_token(kind):
    """The template placeholder of a path kind: a WHOLE inputs / outputs item, e.g. "{path:test-code}"."""
    value = getattr(kind, "value", kind)
    if value not in TEMPLATE_PATH_KINDS:
        raise ValueError(f"no path placeholder for {kind!r}")
    return "{path:" + value + "}"


class VerificationCategory(_Str):
    """`verification` path rule `category` (E33, optional)."""
    TEST = "test"
    GOLDEN = "golden"
    COMPARISON_CONFIG = "comparison-config"
    RUNNER = "runner"
    CI = "ci"


class GoldenRow(_Str):
    """Baseline-image ledger row kinds (E33) — engine facts, never written by a role."""
    ADDED = "A"
    MODIFIED = "M"
    DELETED = "D"
    RENAMED = "R"            # same blob, other path
    CONFIG = "C"             # a comparison-config path changed
    PENDING = "P"            # a role reported needs-regeneration


GOLDEN_ROWS_NEEDING_REASON = frozenset({GoldenRow.ADDED.value, GoldenRow.MODIFIED.value, GoldenRow.DELETED.value,
                                        GoldenRow.CONFIG.value})


class GoldenReason(_Str):
    """Role `golden_reasons[].reason` (E33)."""
    INTENDED_CHANGE = "intended-change"
    BUG_FIX = "bug-fix"
    NEW_CASE = "new-case"
    MOVED = "moved"
    NEEDS_REGENERATION = "needs-regeneration"


class IrreversibleCategory(_Str):
    """§7.4 categories (repo-config path rules; IRREVERSIBLE_CODE_CATEGORY)."""
    EXTERNAL_SIDE_EFFECT = "external-side-effect"
    HARD_TO_REVERT = "hard-to-revert"
    HUMAN_EXECUTED = "human-executed"


class IrreversibleCode(_Str):
    """Codes a role reports in `irreversible[].code` (E22)."""
    DEPLOY_OR_RELEASE = "deploy-or-release"
    EXTERNAL_API_EFFECT = "external-api-effect"
    SHARED_DB_EXECUTION = "shared-db-execution"
    IAC_APPLY = "iac-apply"
    RESOURCE_DELETION = "resource-deletion"
    DESTRUCTIVE_MIGRATION = "destructive-migration"
    DATA_TRANSFORM = "data-transform"
    BREAKING_API = "breaking-api"
    STORAGE_FORMAT_CHANGE = "storage-format-change"
    MAJOR_DEPENDENCY_UPGRADE = "major-dependency-upgrade"
    MIGRATION_FILE = "migration-file"


IRREVERSIBLE_CODE_CATEGORY = {
    IrreversibleCode.DEPLOY_OR_RELEASE.value: IrreversibleCategory.EXTERNAL_SIDE_EFFECT.value,
    IrreversibleCode.EXTERNAL_API_EFFECT.value: IrreversibleCategory.EXTERNAL_SIDE_EFFECT.value,
    IrreversibleCode.SHARED_DB_EXECUTION.value: IrreversibleCategory.EXTERNAL_SIDE_EFFECT.value,
    IrreversibleCode.IAC_APPLY.value: IrreversibleCategory.EXTERNAL_SIDE_EFFECT.value,
    IrreversibleCode.RESOURCE_DELETION.value: IrreversibleCategory.EXTERNAL_SIDE_EFFECT.value,
    IrreversibleCode.DESTRUCTIVE_MIGRATION.value: IrreversibleCategory.HARD_TO_REVERT.value,
    IrreversibleCode.DATA_TRANSFORM.value: IrreversibleCategory.HARD_TO_REVERT.value,
    IrreversibleCode.BREAKING_API.value: IrreversibleCategory.HARD_TO_REVERT.value,
    IrreversibleCode.STORAGE_FORMAT_CHANGE.value: IrreversibleCategory.HARD_TO_REVERT.value,
    IrreversibleCode.MAJOR_DEPENDENCY_UPGRADE.value: IrreversibleCategory.HARD_TO_REVERT.value,
    IrreversibleCode.MIGRATION_FILE.value: IrreversibleCategory.HUMAN_EXECUTED.value,
}
"""E22: the category of a reported code (its level: defaults.IRREVERSIBLE_DEFAULT_LEVEL / settings)."""


class IrreversibleLevel(_Str):
    """§7.4 handling levels (stage 3, E23; stage 1–2 only notify for hard-to-revert code)."""
    HUMAN_DECISION = "human-decision"
    NOTIFY = "notify"
    PROCEED = "proceed"


class RunMode(_Str):
    """§7.3 — the two run modes differ only in how a human is reached."""
    ATTENDED = "attended"
    UNATTENDED = "unattended"


class Actor(_Str):
    """`who` prefix in log.jsonl (§4.3). A role actor is written `role:<name>`."""
    ENGINE = "engine"
    ROLE = "role"
    LEADER = "leader"
    HUMAN = "human"
    SPRINT = "sprint"     # stage 4 (H8): the sprint supervisor's automatic rerun of a quota stop, nothing else


class LogEvent(_Str):
    """`event` values of log.jsonl lines (§4.3; U19 `collect.py --log` reads these)."""
    ISSUE_START = "issue-start"
    ENGINE_START = "engine-start"
    ENGINE_EXIT = "engine-exit"
    PROCEDURE_WRITTEN = "procedure-written"
    ATTEMPT_START = "attempt-start"
    ATTEMPT_END = "attempt-end"
    STATUS = "status"                 # a step status change
    BACK_TO = "back-to"               # on_fail / rerun rewind (§4.4-1)
    REVERIFY = "reverify"             # §4.4-3 pending again
    RULE_SUPPLEMENT = "rule-supplement"  # §7 mandatory check/step added
    REQUEST = "request"               # a role change request, recorded only (stages 0–2)
    DISCOVERY = "discovery"
    STOP = "stop"                     # needs_leader / needs_human
    ANSWER = "answer"                 # a leader/human answer at resume
    WAIT = "wait"                     # quota wait
    COMMIT = "commit"                 # an engine commit
    PUSH = "push"
    PR_CREATED = "pr-created"
    COMMENT = "comment"
    LABEL = "label"
    WARNING = "warning"               # a measurement fact was not collected (§9.3)
    ERROR = "error"                   # engine-error traceback
    LEADER_CALL = "leader-call"       # stage 2: a leader session start / end (data: situation, k, phase)
    ISSUE_CLOSED = "issue-closed"     # stage 2: close-as-decided closed the Issue (D18)
    # stage 3 (data fields: schemas/log-line description)
    FOLLOWUP_CREATED = "followup-created"             # E20
    FOLLOWUP_COMMENTED = "followup-commented"         # E20
    SECURITY_PRIVATE_PATH = "security-private-path"   # E21
    IRREVERSIBLE_DETECTED = "irreversible-detected"   # E23
    MODEL_RAISED = "model-raised"                     # E26
    PR_UPDATED = "pr-updated"                         # E31
    CANARY = "canary"                                 # K8-1: a role canary the engine ran itself (cost outside the Issue)
    # stage 4
    SPRINT_MEMBER = "sprint-member"                   # H6: the start input a sprint gave this Issue
    TEST_CHANGE_ALLOWED = "test-change-allowed"       # H21 (E9-2): a human allowed files
    MUTATION_PROOF = "mutation-proof"                 # VB9: the engine ran the declared mutations at a HEAD


class FileChange(_Str):
    """facts.json `changed_files[].change`."""
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"
    COPIED = "copied"
    TYPE_CHANGED = "type-changed"


class ChangeWhere(_Str):
    """facts.json `changed_files[].where` — committed in base..HEAD, or not yet committed."""
    COMMITTED = "committed"
    WORKTREE = "worktree"     # tracked, uncommitted (staged or not)
    UNTRACKED = "untracked"   # new, not ignored


class SessionEnd(_Str):
    """facts.json `session.end` — how a role session ended."""
    COMPLETED = "completed"
    BUDGET = "budget"           # --max-budget-usd reached → session-limit
    WALL_CLOCK = "wall-clock"   # engine killed the group → infra
    NO_OUTPUT = "no-output"     # engine killed the group → infra
    ERROR = "error"             # non-zero exit / is_error without the above


# --- stage 4: sprints, init, mutation evidence (stage-4 scope §2.0) -------------------------------
#
# Everything below is used at engine stage >= 4 only (H23). The lists are repeated in schemas/
# (sprint-state, sprint-log-line, init-decisions, mutation-record) and kept equal by test_contracts.

STAGE4 = 4
"""The first engine stage with the sprint supervisor, init, E9-2, run serialisation and VB9 (H23)."""


class MemberKind(_Str):
    """The kind column (`구분`) of the member table (§2.3). A table without it is read in number order."""
    GOAL = "goal"
    OTHER = "other"
    SLOT = "slot"


MEMBER_KIND_RANK = {MemberKind.GOAL.value: 0, MemberKind.SLOT.value: 0, MemberKind.OTHER.value: 1}
"""0.98.7 sprint_dag.py KIND_RANK: goal and slot share a rank and run before other."""


class MemberOutcome(_Str):
    """§2.2 — what one member came to in one supervisor run."""
    DONE = "done"
    CLOSED = "closed"
    STOPPED = "stopped"
    BLOCKED = "blocked"                  # `block` says why (MemberBlock); not a failure
    SKIPPED_LOCKED = "skipped-locked"
    REFUSED = "refused"                  # engine exit 4, or a member Issue closed as not planned (D4)
    FAILED = "failed"


class MemberBlock(_Str):
    """§2.2 / §2.3 — why a member was not started (or, quota, could not go on)."""
    DEP_STOPPED = "dep-stopped"
    DEP_FAILED = "dep-failed"
    UPSTREAM = "upstream"
    DEP_NOT_DONE = "dep-not-done"
    DEP_PR_CLOSED = "dep-pr-closed"
    DEP_PR_AMBIGUOUS = "dep-pr-ambiguous"
    DEP_NOT_PLANNED = "dep-not-planned"
    DEP_UNMERGED = "dep-unmerged"        # §2.4: no stacking here (merge settings unknown, or the human declined stacks)
    BASE_UNRESOLVED = "base-unresolved"  # facts not collected, fetch failed, head differs, a control file moved (D1)
    QUOTA = "quota"
    REPO_BUSY = "repo-busy"
    REMOTE_BRANCH_EXISTS = "remote-branch-exists"
    UNSUPPORTED_EPIC = "unsupported-epic"
    ATTENDED_RUN = "attended-run"        # review-q0 D2: the member's state.json has mode attended


BLOCK_BY_DEP_OUTCOME = {
    MemberOutcome.STOPPED.value: MemberBlock.DEP_STOPPED.value,
    MemberOutcome.SKIPPED_LOCKED.value: MemberBlock.DEP_STOPPED.value,
    MemberOutcome.FAILED.value: MemberBlock.DEP_FAILED.value,
    MemberOutcome.REFUSED.value: MemberBlock.DEP_FAILED.value,
    MemberOutcome.BLOCKED.value: MemberBlock.UPSTREAM.value,
}
"""review-q0 D4: this run's outcome of the dependency → the block of the members on it (done / closed: none)."""


class DepBase(_Str):
    """sprintdag.member_state / base_for: where a member with a dependency starts."""
    DEFAULT = "default"      # the repository's default branch (merged, or closed as completed)
    STACK = "stack"          # the dependency's branch gld/<D>
    BLOCKED = "blocked"      # + a MemberBlock


class StackReason(_Str):
    """The tracker body's stack-cap reason token (`상한 근거`, sprint plan) — how the run may stack."""
    CONFIG = "config"                                  # merge commits allowed: plain stacked PRs
    SQUASH_SYNC = "squash-sync"                        # squash / rebase only: DRAFT stacked PRs (U1)
    MERGE_COMMIT_FORBIDDEN = "merge-commit-forbidden"  # the human declined stacks → dep-unmerged
    HUMAN_OVERRIDE = "human-override"                  # trackers before 0.98.7: read as squash-sync


DRAFT_STACK_REASONS = frozenset({StackReason.SQUASH_SYNC.value, StackReason.HUMAN_OVERRIDE.value})


class SprintState(_Str):
    """`sprint.json` state (and the first word of the tracker marker's `state`)."""
    STARTING = "starting"
    CHECKING_BASE = "checking-base"
    RUNNING = "running"
    WAITING_FOR_WINDOW = "waiting-for-window"
    WAITING_FOR_QUOTA = "waiting-for-quota"
    FINISHED = "finished"
    HALTED = "halted"


SPRINT_ENDED = frozenset({SprintState.FINISHED.value, SprintState.HALTED.value})


class SprintHalt(_Str):
    """Why the supervisor ended before the last member (§2.2)."""
    BASE_RED = "base-red"
    BOUNDARY = "boundary"                # H11 + review-q0 D3
    MARKER_UNWRITABLE = "marker-unwritable"
    PLAN_HASH_MISMATCH = "plan-hash-mismatch"
    OTHER_HOST = "other-host"
    SIGNAL = "signal"
    ENGINE_ERROR = "engine-error"


BOUNDARY_STOPS = frozenset({StopReason.CANARY_FAILED.value, StopReason.SELF_CHECK_FAILED.value})
"""H11: a member that stopped (or was refused — D3: the code of its last `data.refused` log line) for one
of these halts the sprint as `boundary`: the next member would stop at the same place."""

STOP_DETAILS = frozenset(InfraReason.values())
"""`state.stop.detail` (H8) — InfraReason values, no enum of its own."""

SPRINT_RERUN_REASON = StopReason.INFRA_STOP.value
SPRINT_RERUN_DETAIL = InfraReason.QUOTA.value
"""H8 / D6: the only needs_human stop a sprint may answer (`rerun`), and only after `reset_at`."""


class SprintEvent(_Str):
    """`event` of the sprint log (sprints/<tracker>/log.jsonl, schema sprint-log-line)."""
    SPRINT_START = "sprint-start"
    BASE_CHECK = "base-check"
    MEMBER_START = "member-start"
    MEMBER_END = "member-end"
    MEMBER_BLOCKED = "member-blocked"
    WAIT = "wait"
    HALT = "halt"
    SPRINT_END = "sprint-end"
    WARNING = "warning"                  # e.g. a dependency outside the member table (0.98.7 rule, dropped)


class StopCause(_Str):
    """User decision A13: metrics report engine-caused stops and stops the Issue itself demands apart."""
    ENGINE = "engine"
    ISSUE = "issue"
    LABEL = "label"          # the code alone does not say: a human label decides (metrics), the default


STOP_CAUSE = {
    StopReason.OUTPUT_FORMAT_TWICE.value: StopCause.ENGINE.value,
    StopReason.SESSION_LIMIT.value: StopCause.ENGINE.value,
    StopReason.CANARY_FAILED.value: StopCause.ENGINE.value,
    StopReason.SELF_CHECK_FAILED.value: StopCause.ENGINE.value,
    StopReason.INFRA_STOP.value: StopCause.ENGINE.value,
    StopReason.ENGINE_ERROR.value: StopCause.ENGINE.value,
    StopReason.FORMAT_MISMATCH.value: StopCause.ENGINE.value,
    StopReason.IRREVERSIBLE_CHANGE.value: StopCause.ISSUE.value,
    StopReason.NEW_COMMENT.value: StopCause.ISSUE.value,
    StopReason.STABLE_LABEL.value: StopCause.ISSUE.value,
    StopReason.PR_REVIEW.value: StopCause.ISSUE.value,
    # readiness T1: the Issue's own state on GitHub refuses the start (an epic, someone's open PR, a done label)
    StopReason.UNSUPPORTED_EPIC.value: StopCause.ISSUE.value,
    StopReason.OPEN_CLOSING_PR.value: StopCause.ISSUE.value,
    StopReason.DONE_UNCONFIRMED.value: StopCause.ISSUE.value,
}


def stop_cause(reason):
    """StopCause value of a StopReason value (A13). Anything not in STOP_CAUSE is `label`: a leader's
    escalate, a blocked role or a red base can be either (word_app #1938 read like an Issue demand and
    was an engine gap), so a human says which."""
    value = getattr(reason, "value", reason)
    if value not in StopReason.values():
        raise ValueError(f"unknown stop reason {reason!r}")
    return STOP_CAUSE.get(value, StopCause.LABEL.value)


class InitQuestion(_Str):
    """§2.9 — the only questions init asks (eight, then three more by A15, 2026-11-26: what a human judged and the
    repository files cannot show — VW1)."""
    TEST_COMMAND = "test-command"
    COMMAND_CONFLICT = "command-conflict"
    NOT_LOCAL = "not-local"
    SANDBOX_EXCEPTION = "sandbox-exception"
    QUARANTINE = "quarantine"
    RISK_RULES = "risk-rules"
    REGISTRY_HOST = "registry-host"
    TOOLCHAIN = "toolchain"
    RISK_ADD = "risk-add"                     # A15: a human adds a risk / irreversible rule line (glob + kind, a note)
    NARROW_GLOB = "narrow-glob"               # A15: a human narrows a test-code / safety-net candidate (never widens)
    FOLLOWUPS_DRY_RUN = "followups-dry-run"   # A15: create-followups really creates, or only records (A4); Q11 (11-28):
                                              # optional and never asked — no answer = really create (the default)


class CommandSource(_Str):
    """§2.9 — where a proposed command text came from (the only sources there are)."""
    STABLE_CONFIG = "stable-config"
    CI = "ci"
    LEFTHOOK = "lefthook"
    MANIFEST = "manifest"
    HUMAN = "human"


class MutationStatus(_Str):
    """VB9 — what the engine saw for one declared mutation (mutation-record). A fact, never a verdict."""
    KILLED = "killed"            # the repository's `test` was red on HEAD + the mutation
    SURVIVED = "survived"        # … was green
    TIMED_OUT = "timed-out"      # neither (a timeout is never red)
    REFUSED = "refused"          # the declaration is not usable (MutationRefusal); nothing was run
    NOT_RUN = "not-run"          # the engine could not run it (no tree, setup red, dirty tree, control run red)


class MutationRefusal(_Str):
    """`mutation-record` `problem` (the whole file) and `rows[].detail` (one refused row)."""
    BAD_FILE = "bad-file"            # mutations.json is not a regular file, not JSON, or not schemas/mutations
    BAD_PATH = "bad-path"            # not a regular tracked file of HEAD, a control file, or under docs/specs/
    VERIFICATION_PATH = "verification-path"    # under a verification / test-code / safety-net rule
    NOT_UNIQUE = "not-unique"        # `find` does not occur exactly once in the HEAD blob
    NO_CHANGE = "no-change"          # `replace` equals `find`
    UNKNOWN_AC = "unknown-ac"        # an AC id analysis.md does not have
