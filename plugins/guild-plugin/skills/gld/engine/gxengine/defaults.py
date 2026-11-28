"""Plugin defaults — layer 1 of §7.9 and the provisional numbers of §5.1/§7.4/§7.9/§7.10.

Stage 1 ignores role-file frontmatter (I4) and does not let anyone change model or
effort (§9.2), so these values are what every session gets. Numbers marked
"provisional" are the design's 잠정값; the ones that must be derived from data (I13,
Q7) are `None` until U6 computes them and reports.
"""

from . import codes

FORMAT = 1
"""`format` of every engine file written by this plugin version (§4.3)."""

ENGINE_STAGE = 4
"""Stage-2 scope D21 / stage-3 scope E36 / stage-4 scope H23: the engine stage the CLI runs with
(statemachine.stop_status, procedure grammar, allowed-answer table, the stage-3 templates / catalog / ops,
the stage-4 sprint / init / base-check commands and member start input). Flipped to 2 by the stage-2 merge
(Q6), to 3 by the stage-3 integration (Q4) and to 4 by the stage-4 integration (VZ); setting it back gives
the earlier engine. Tests pass `stage=` explicitly and keep every stage."""

# §7.9 role start defaults (layer 2 table, used as layer 1 in stage 1 — I4).
# Key: role name, or "role/phase" where one role has two rows.
MODEL_EFFORT = {
    "leader": ("opus", "high"),
    "requirements-engineer": ("opus", "medium"),
    "tech-lead/design": ("sonnet", "high"),
    "tester/test-cases": ("sonnet", "high"),
    "developer": ("sonnet", "high"),
    "auditor": ("opus", "high"),
    "tech-lead/review": ("sonnet", "medium"),
    "qa": ("sonnet", "medium"),
    "designer": ("sonnet", "medium"),
    "tester/review": ("sonnet", "medium"),   # not in the §7.9 table — see interfaces.md
}

# §7.8 allow-list initial value: Fable and effort `max` are off unless the repo opens them.
ALLOWED_MODELS = ("opus", "sonnet", "haiku")
ALLOWED_EFFORTS = ("low", "medium", "high", "xhigh")

# Stage 3 (E17): layer-1 values of the roles and steps stage 3 adds. A separate table so that
# stages 1–2 keep refusing those roles (a missing key = no session). Same key rule: a step with
# `checks` looks up "<role>/review", any other "<role>/<step id>", then "<role>". Provisional.
STAGE3_MODEL_EFFORT = dict(MODEL_EFFORT, **{
    "product-owner": ("opus", "medium"),
    "designer/ux-design": ("sonnet", "high"),
    "designer/review": ("sonnet", "medium"),
    "security/threat-model": ("opus", "high"),
    "security/review": ("opus", "high"),
    "dba/data-design": ("sonnet", "high"),
    "dba/review": ("sonnet", "high"),
    "i18n/i18n-plan": ("sonnet", "medium"),
    "i18n/review": ("sonnet", "medium"),
    "performance/review": ("sonnet", "high"),
    "infra/review": ("sonnet", "medium"),
    "developer/reproduce": ("sonnet", "high"),
    "developer/safety-net": ("sonnet", "high"),
    "developer/fix-discovery": ("sonnet", "high"),
    "tech-lead/diagnose": ("sonnet", "high"),
})


def model_effort_table(stage):
    """The layer-1 (model, effort) table of an engine stage."""
    codes.check_stage(stage)
    return MODEL_EFFORT if stage < 3 else STAGE3_MODEL_EFFORT


# Stage 3 (E26) retry raise: the rungs in order. A rung outside the repository's allow-list
# (repo-config allowed_models / allowed_efforts, default ALLOWED_*) is not on the ladder.
# These are also the only names repo-config accepts (E29).
EFFORT_LADDER = ("low", "medium", "high", "xhigh", "max")
MODEL_LADDER = ("haiku", "sonnet", "opus", "fable")
RAISE_EFFORT_AT = 2                # returns(X) ≥ this → effort + 1
RAISE_MODEL_AT = 3                 # returns(X) ≥ this → model + 1 too; never more than these two rungs

# I4 / F2 — `--tools` sets per role class (Claude Code 2.1.323 has no Grep/Glob tools).
TOOLS = {
    codes.RoleClass.WORK.value: ("Bash", "Read", "Edit", "Write"),
    codes.RoleClass.JUDGE.value: ("Read", "Write"),
}

# §5.1 / §6.2 / §7.4 counters and limits.
OUTPUT_FORMAT_RETRIES = 1          # one rerun with the error, then a stop
DEVELOPER_RESUME_MAX = 2           # --resume only when developer comes back (§6.2)
INFRA_WAIT_MAX_S = 4 * 3600        # quota reset within 4 h → wait (§5.1)
LEADER_CALLS_MAX = 5               # provisional (§7.4) — stage 2; counts codes.LEADER_CALL_COUNTED only (D14)
PLAN_GATE_RERUN_MAX = 2            # stage 2 D3: plan-gate `rerun analyze` per Issue
DONE_GATE_RERUN_MAX = 2            # stage 2 D7: done-gate `rerun <step>` per Issue
PLAN_GATE_RERUN_TARGET = "analyze"  # D3: the only plan-gate rerun target (start procedure step id)
REPLAN_TARGET = "plan"             # D8: replan = back_to this step (the plan-gate check step)
LEADER_FORMAT_RETRIES = {"plan-gate": 2, "default": 1}
"""D12: re-calls of the SAME leader situation after a rejected answer (error attached), then
needs_human with `leader_failed`. Keys: a situation (StopReason value) or "default"."""


def leader_format_retries(situation):
    """D12: how many times a rejected leader answer is sent back for `situation`."""
    return LEADER_FORMAT_RETRIES.get(situation, LEADER_FORMAT_RETRIES["default"])


# Stage 2 leader inputs (V3, scope O3): free-text fields copied into leader-input.json are cut
# at this many characters with LEADER_TRUNCATION_MARK appended (provisional, measured later).
LEADER_INPUT_TEXT_MAX = 4000
LEADER_INPUT_TRUNCATION_MARK = "…[truncated by the engine]"

# Stage 2 markers (D18). The engine only checks that the decision block EXISTS in the Issue
# body or a collaborator comment (its content is for the leader).
PLAN_DECISION_MARKER = "<!-- guild:plan-decision -->"
CLOSED_AS_DECIDED_MARKER = "<!-- guild:closed-as-decided -->"
RUN_TIMEOUT_MIN = 30               # provisional default per named command (§7.10)

# Stage 3 limits (provisional, scope O6).
CATALOG_ADDS_MAX = 3               # E15: catalog steps added per Issue (mandatory gates count, are never blocked)
FOLLOWUPS_MAX = 5                  # E19: follow-up Issues per Issue
PR_SUMMARY_LINES_MAX = 3           # the done-gate `summary` lines at the top of a stage-4 PR body (R2 6단계)
FOLLOWUP_CANDIDATES_MAX = 30       # E19: duplicate candidates shown to the done-gate leader
DEFER_MAX = 1                      # E30: replan `defer` per Issue
REPRO_RED_RUNS = 2                 # review-q0 D10: the overlay tree must be red this many times in a row
REPRO_EVIDENCE_LOG_LINES = 200     # E8: in:repro-evidence.md carries this many last lines of the red log

# Readiness E4 (#1910): a bug Issue keeps its red reproduction.
BUG_LABELS = ("bug", "type:bug", "type: bug", "type/bug", "kind:bug", "kind/bug")
"""Issue labels (compared lower-case, trimmed) that make an Issue a bug Issue (history.is_bug_label)."""
BUG_GUARD_MODES = (codes.RunMode.ATTENDED.value, codes.RunMode.UNATTENDED.value)
"""The run modes in which E4 rules 1 and 2 hold. Both: the leader answers inside the engine in attended mode
too (commands/engine/dev.md "Stage 2"), so a human being around does not see the decision before it runs."""
NOT_REPRODUCED_FILE = "not-reproduced.md"   # <records>/…/<N>/ — the facts of the not-reproduced stop
HISTORY_RELATED_FILES_MAX = 40     # related files of a not-reproduced stop (history.related_files)
HISTORY_COMMITS_MAX = 30           # commits listed per question (not-reproduced, in:git-history.md)
HISTORY_COMMIT_FILES_MAX = 8       # files shown per listed commit
HISTORY_SEARCH_TOKENS_MAX = 8      # in:git-history.md: code tokens of the Issue searched
HISTORY_SEARCH_HITS_MAX = 10       # … `git grep` hits shown per token
HISTORY_TEST_LINES_MAX = 12        # not-reproduced: test declaration lines shown per reproduction file

# Stage 3 irreversible changes (E22–E24): the category's level unless the settings say otherwise.
IRREVERSIBLE_DEFAULT_LEVEL = {
    codes.IrreversibleCategory.EXTERNAL_SIDE_EFFECT.value: codes.IrreversibleLevel.HUMAN_DECISION.value,
    codes.IrreversibleCategory.HARD_TO_REVERT.value: codes.IrreversibleLevel.NOTIFY.value,
    codes.IrreversibleCategory.HUMAN_EXECUTED.value: codes.IrreversibleLevel.NOTIFY.value,
}
IRREVERSIBLE_LEVEL_ORDER = (codes.IrreversibleLevel.PROCEED.value, codes.IrreversibleLevel.NOTIFY.value,
                            codes.IrreversibleLevel.HUMAN_DECISION.value)
"""Weakest first: a configured level before the default one is a LOWERED level (E24)."""

# Stage 3 follow-up Issues (E19–E21).
FOLLOWUPS_DRY_RUN_DEFAULT = False  # repo-config `followups_dry_run` (user decision A4): absent = really create
FOLLOWUP_LABEL_NAME = "followup"   # written as LABEL_PREFIX + name; candidates also carry the stable prefix + name
SECURITY_LABEL_NAME = "security"
IRREVERSIBLE_LABEL_NAME = "irreversible"
FOLLOWUP_MARKER = "<!-- guild:followup origin={issue} key={key} -->"
DEFERRED_REQUIREMENT_KIND = "deferred-requirement"   # E30: the follow-up of the deferred rows (not a discovery)
FOLLOWUP_TYPE_LABELS = {
    codes.DiscoveryKind.BUG.value: "type:bug",
    codes.DiscoveryKind.SECURITY.value: "type:bug",
    codes.DiscoveryKind.DEBT.value: "type:refactor",
    codes.DiscoveryKind.TEST_GAP.value: "type:refactor",
    codes.DiscoveryKind.DOC.value: "type:docs",
    DEFERRED_REQUIREMENT_KIND: "type:feature",
}
"""Put on a follow-up Issue only when the repository already has that label."""
FOLLOWUPS_DRY_RUN_FILE = "followups-dry-run.jsonl"   # <records>/…/<N>/ — what a dry run would have written
SECURITY_FINDINGS_FILE = "security-findings.md"      # <records>/…/<N>/ — public repositories (E21)
TOTAL_ATTEMPTS_PER_STEP = 4        # absolute attempt cap = steps of the procedure × this (P3-Z,
                                   # human decision) — reached → ABSOLUTE_LIMIT stop at once


def total_attempts_max(step_count):
    """The §7.4 absolute cap on attempts of one Issue: procedure steps × TOTAL_ATTEMPTS_PER_STEP."""
    if isinstance(step_count, bool) or not isinstance(step_count, int) or step_count < 1:
        raise ValueError(f"bad step count {step_count!r}")
    return step_count * TOTAL_ATTEMPTS_PER_STEP

# §7.9 / §9.5 budgets — attended mode (Q10), corrected baseline.
SOFT_BUDGET_USD = {codes.RunMode.ATTENDED.value: 44.79, codes.RunMode.UNATTENDED.value: 18.44}
ABSOLUTE_BUDGET_USD = {codes.RunMode.ATTENDED.value: 89.57, codes.RunMode.UNATTENDED.value: 36.88}

# I13 session limits. `SESSION_MAX_BUDGET_USD` (human decision, P3-0): per role KIND — the
# role name without the "/phase" suffix of MODEL_EFFORT — passed as `--max-budget-usd`
# (USD). FORMAT_REPAIR_BUDGET_KEY is the output-format repair session (haiku). A role
# missing here gets no session (fail-closed: no default budget).
FORMAT_REPAIR_BUDGET_KEY = "format-repair"
# P4: the paid boundary canary (`engine.py canary`) — one cap per canary session (a batch of
# probes, haiku), and the deliberately tiny cap of the budget-end shape probe (it must hit
# the cap after its first turn so the CLI's budget-end result is recorded).
CANARY_BUDGET_KEY = "canary"
CANARY_BUDGET_PROBE_KEY = "canary-budget-probe"
SESSION_MAX_BUDGET_USD = {
    "developer": 15.0,
    "requirements-engineer": 8.0,
    "tech-lead": 8.0,
    "tester": 8.0,
    "auditor": 8.0,
    "qa": 8.0,
    "designer": 8.0,
    "leader": 6.0,                     # stage 2 D10 — provisional, below the judge cap (short session)
    FORMAT_REPAIR_BUDGET_KEY: 1.0,
    CANARY_BUDGET_KEY: 1.5,
    CANARY_BUDGET_PROBE_KEY: 0.0005,   # measured: haiku costs ~$0.00015 a turn (P4)
}
# Stage 3 (E17): budgets of the conditional specialists (provisional). Separate so that stages
# 1–2 still have no session for them (a risk gate stays rule-unfillable there).
STAGE3_SESSION_MAX_BUDGET_USD = dict(SESSION_MAX_BUDGET_USD, **{
    "product-owner": 8.0,
    "security": 8.0,
    "dba": 8.0,
    "i18n": 8.0,
    "performance": 8.0,
    "infra": 8.0,
})


def session_budget_table(stage):
    """The `--max-budget-usd` table (role kind → USD) of an engine stage."""
    codes.check_stage(stage)
    return SESSION_MAX_BUDGET_USD if stage < 3 else STAGE3_SESSION_MAX_BUDGET_USD


CANARY_TOTAL_MAX_USD = 5.0          # `engine.py canary` stops before a session that could pass this
SESSION_WALL_CLOCK_S = {}          # role key → int
SESSION_NO_OUTPUT_S = None         # N minutes without a stream-json event, in seconds

# §7.6 / F1 / F2 — FC decision D (2026-11-28): no per-CLI-version list of the `system/init`
# fields (CLI_BUILTINS) any more — a role session's init is not compared. The launch flags
# (render.CLAUDE_FIXED_FLAGS: --setting-sources "", --strict-mcp-config, --permission-mode
# default, --tools) still keep the user's settings out.

# §6.2 — environment variables removed before any role session or run, by pattern
# (fnmatch, case-sensitive). The parent Claude session's own variables go too (F1 run.sh).
ENV_SCRUB_PATTERNS = (
    "GH_*", "GITHUB_*", "*TOKEN*", "ANTHROPIC_*", "AWS_*", "GOOGLE_*", "GCLOUD_*",
    "CLOUDSDK_*", "AZURE_*", "SSH_AUTH_SOCK", "GIT_ASKPASS", "SSH_ASKPASS",
    "CLAUDECODE", "CLAUDE_CODE_*", "CLAUDE_PID", "CLAUDE_EFFORT",
)
# Set on every role session (§6.2). CLAUDE_CONFIG_DIR passes through for the CLI's own
# login; SCRUB removes it from the role's Bash children (F1).
ENV_SESSION_SET = {
    "CLAUDE_CODE_SUBPROCESS_ENV_SCRUB": "1",
    "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
    # P5 real run: the repository's own git hooks (lefthook: flutter analyze/test, mktemp -t)
    # cannot run inside a role sandbox, so a role's `git commit` failed and the developer
    # (rightly) refused --no-verify. Verification is the engine's `run` steps + verify-gate;
    # the 0.98.7 gate still runs as the Claude PreToolUse hook (S9), not as a git hook.
    "GIT_CONFIG_COUNT": "1",
    "GIT_CONFIG_KEY_0": "core.hooksPath",
    "GIT_CONFIG_VALUE_0": "/dev/null",
}
ENV_KEEP_EVEN_IF_MATCHED = ("CLAUDE_CONFIG_DIR",)

# §7.12 S9 — auxiliary permission denies (0.102 deny list).
AUX_BASH_DENY = ("Bash(git commit*--no-verify*)", "Bash(git commit*-n*)", "Bash(git -c *)")

# §7.12 S1 — fixed sandbox values.
SANDBOX_FIXED = {
    "enabled": True,
    "allowUnsandboxedCommands": False,
    "autoAllowBashIfSandboxed": False,
    "excludedCommands": [],
}

# §7.6 secret list (home-relative). `{claude_config_dir}` is the CLI's config dir.
HOME_SECRETS = (
    ".ssh", ".aws", ".azure", ".config/gcloud", ".config/gh", ".npmrc", ".netrc",
    ".git-credentials", ".docker/config.json", ".kube", "Library/Keychains",
)
# §7.6 read-allowed even though under $HOME (never put on the deny list).
HOME_READ_ALLOWED = (".gitconfig", ".config/git")

# §7.10 default repository secret paths (init puts these in; a human edits them).
# Root and `**/` forms both: the glob dialect has no implicit basename match (§4-29), and the
# root form is kept for renderers whose `**/` may not reach the top level.
REPO_SECRET_DEFAULTS = (".env*", "*.pem", "*.p12", "*.key", "**/.env*", "**/*.pem", "**/*.p12", "**/*.key")

# §7.6 control files (plugin-fixed). `{issue}` is the Issue number.
# `**/.claude/**` (P3-0): a nested `.claude/` folder is a control folder too; `.claude/**` stays
# for matchers whose `**/` may not reach the top level.
CONTROL_FILE_GLOBS = (
    ".claude/**", "**/.claude/**", "**/CLAUDE.md", "**/CLAUDE.local.md", "**/AGENTS.md",
    "docs/specs/{issue}/procedure.yaml",
)
SPECS_DIR = "docs/specs/{issue}"

# repo-config `sandbox_exceptions.allow_write` (P3-0). Entries are absolute paths or exactly
# this token, which the engine resolves to `getconf DARWIN_USER_TEMP_DIR` (macOS — the
# folder `mktemp`/`xcrun` use whatever TMPDIR says). Not resolvable → refuse (fail-closed).
USER_TMP_TOKEN = "{user_tmp}"
# Path components an allow_write entry may never contain, anywhere in the path (schema
# pattern `$defs/allowwrite`, case-insensitive; test_contracts keeps the two in sync): git
# internals, control files, home secrets (HOME_SECRETS).
ALLOW_WRITE_FORBIDDEN_COMPONENTS = (
    ".git", ".claude", "CLAUDE.md", "CLAUDE.local.md", "AGENTS.md",
    ".ssh", ".aws", ".azure", ".gnupg", ".kube", ".docker", ".npmrc", ".netrc",
    ".git-credentials", "gcloud", "gh", "Keychains",
)

# repo-config `run_env` (P3-0): literal, non-path env for runs (e.g. TURBO_TELEMETRY_DISABLED=1).
# Names must match RUN_ENV_NAME and contain none of RUN_ENV_SECRET_WORDS; names the engine
# sets or scrubs are refused too (RUN_ENV_RESERVED + ENV_SCRUB_PATTERNS).
RUN_ENV_NAME = r"[A-Z_][A-Z0-9_]*"
RUN_ENV_SECRET_WORDS = ("TOKEN", "SECRET", "KEY", "PASSWORD", "PASSWD", "CREDENTIAL")
RUN_ENV_RESERVED = (
    "PATH", "HOME", "TMPDIR", "SHELL", "USER", "LOGNAME", "BASH_MAX_TIMEOUT_MS",
    "BASH_ENV", "ENV", "IFS", "PS4", "PROMPT_COMMAND",
)
RUN_ENV_RESERVED_PREFIXES = ("GIT_", "SSH_", "CLAUDE", "LD_", "DYLD_", "GH_", "GITHUB_",
                             "ANTHROPIC_", "AWS_", "GOOGLE_", "GCLOUD_", "CLOUDSDK_", "AZURE_")

# Labels and markers of this edition (§9.1).
LABEL_PREFIX = "guild:"
MARKER_PREFIX = "<!-- guild:"
STABLE_STAGE_LABELS = (
    "analyze", "design", "execute", "test", "qa", "done", "needs-human",
)  # refused when carried with the stable prefix (U0, E9)

# §7.3 / F4 — short TMPDIR for srt itself (unix socket path length).
SRT_TMP_PREFIX = "/tmp/gx-"
SANDBOX_TMP_FORBIDDEN_PREFIX = "/tmp/claude-"   # never put engine records under it

# --- stage 4 (stage-4 scope; used at stage >= 4 only, H23) ---------------------------------------
SPRINT_REPO_BUSY_MAX_S = INFRA_WAIT_MAX_S   # H5: another Issue holds the repository lock → then repo-busy
SPRINT_POLL_S = 60                          # H5 lock polls, §2.6 window polls
SPRINT_MARKER_EVERY_S = 600                 # §2.2: the tracker marker is refreshed at least this often
SPRINT_MARKER_FAILS_MAX = 3                 # consecutive failed marker writes → halted marker-unwritable
SPRINT_MARKER_FAILS_MAX_WINDOW = 18         # … while waiting for the window
SPRINT_PLAN_MARKER = "<!-- guild:sprint:plan -->"
SPRINT_PLAN_MARKER_END = "<!-- /guild:sprint:plan -->"
SPRINT_RUN_MARKER = "<!-- guild:sprint:run -->"
SPRINT_RUN_MARKER_END = "<!-- /guild:sprint:run -->"
SPRINT_STACK_MARKER = "<!-- guild:sprint:stack -->"     # in the body of a stacked PR (stack_sync.py reads it)
SPRINT_STACK_MARKER_END = "<!-- /guild:sprint:stack -->"
SPRINT_PLAN_HASH_LEN = 12                   # 0.98.7 sprint_dag.py --mode hash
NEEDS_HUMAN_LABEL_NAME = "needs-human"      # H9: LABEL_PREFIX + name; never a stage label (set_stage_label keeps it)
EPIC_LABEL_NAME = "children"                # H3: LABEL_PREFIX + name on a member → unsupported-epic
CHILD_LABEL_NAME = "child"                  # readiness T1 P3: LABEL_PREFIX + name = a child of an epic (runs alone)
DONE_LABEL_NAME = "done"                    # readiness T1 R4-12: LABEL_PREFIX + name = finished by an earlier run
REF_RANGE_MAX = 20                          # H20: `#a~#b` is expanded when a < b and b - a <= this
ENGINE_SETTINGS = ".claude/guild/config.json"     # H13: the engine's only (schemas/repo-config)
HARNESS_SETTINGS = ".claude/guild/harness.json"   # H13: the LLM commands' settings; the engine never reads it
# Readiness T2 (R4-13 K2): the ⑥ knowledge folder BOTH channels read (role frames, LLM commands); only the stable
# channel writes it (channel.VALUES writes_knowledge). The same path in both trees — never renamed by promotion.
KNOWLEDGE_DIR = ".claude/guild/knowledge"   # promote: literal  rename-exception: K2 shared knowledge
MUTATIONS_NAME = "mutations.json"           # VB9: docs/specs/<N>/mutations.json, declared by a work role
MUTATIONS_MAX = 5                           # … entries per Issue (schemas/mutations maxItems)
MUTATION_LOG_LINES = 40                     # last lines of a mutation's run log in its record row
# VW3 E2: what the done-gate leader reads of a red mutation run. log_excerpt (the first failure block,
# mutation._excerpt) is built to fit MUTATION_EXCERPT_MAX characters; log_tail is cut to its LAST
# MUTATION_LEADER_TAIL_MAX characters (the not-run reason is its last line). Together no more than the
# LEADER_INPUT_TEXT_MAX one log_tail had before.
MUTATION_EXCERPT_MAX = 3000
MUTATION_LEADER_TAIL_MAX = 1000
