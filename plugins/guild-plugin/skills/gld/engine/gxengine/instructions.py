"""Work instructions — the plugin-fixed frame per step kind (design §6.2, §2.1, I4 I7 I13) — U15.

The instruction (the `-p` text) = fixed frame + the step's task text + step specifics. The
variable part goes last so the session prefix (CLAUDE.md + role body + fixed frame + task)
stays cache-friendly (§7.9). Fixed rules, highest priority first (`data/frames/common.md`):

  1. (I4) The role body's status lines, run instructions and plugin-file references do not
     apply to this session.
  2. Preflight (0.98.7): docs/standards/ `status:` — confirmed = binding; read the knowledge
     index.md, then only the matching facts/<area>.md (paths only, the engine matches nothing).
  3. Leave no background process.
  4. (I7) Do not merge the base; do not rewrite pushed history.
  5. (I13, developer) The `run` steps run the full suite; run only the changed files' tests yourself.
  6. (§2.1) Golden rule: intended screen changes only via visual.create; never relax comparison settings.
  7. Inputs are paths — read what you need; outputs go to the declared paths only; the
     result is the structured output (schema given separately).

Three frame kinds: `work` (the developer), `judge` (a judge role that writes document
outputs), `review` (a step with `checks`). Frame texts live in `data/frames/`, per-step task
texts in `data/tasks/<step id>.md` (a step without a task file gets the frame alone).

The plugin start procedure (analyze → ac-format → plan) and the default feature template
are data files under `engine/data/` (U15), checked by procedure.parse_template. The
plugin-owned roles (requirements-engineer, auditor, and from stage 2 the leader) ship a default body in `data/roles/`;
a repository's copy lives in `.claude/guild/roles/` and is read from the base SHA blob
like every role file (design §6.2, §7.12 S3); every other role is the stable edition's
`.claude/agents/<role>.md`, read only.
"""

import json
import os

from . import codes
from . import defaults
from . import schema

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "data")

START_PROCEDURE_FILE = "data/start.json"
DEFAULT_TEMPLATES_DIR = "data/templates"
DEFAULT_TEMPLATE_SUFFIX = ".json"        # template files are JSON text (interfaces.md §4 item 1)

AGENTS_DIR = ".claude/agents"            # stable edition role files — read only
ROLE_FILES_DIR = ".claude/guild/roles"
PLUGIN_ROLES = ("requirements-engineer", "auditor", "leader")

FRAME_KINDS = ("work", "judge", "review")

# Check ids the feature template uses, and what an engine rule may add (codes.RequiredCheck).
# `covers_diff`: the I5-1 rule applies — `reviewed` must cover every changed file (except
# docs/specs/<issue>/), else `output-format`.
CHECK_CATALOG = {
    "design-conformance": {
        "covers_diff": False,
        "summary": "the change honours the skeleton: module boundaries, seams, technical direction",
    },
    "test-quality": {
        "covers_diff": False,
        "summary": "the tests really prove the acceptance criteria and the cases, and verify nothing less than before",
    },
    "diff-review": {
        "covers_diff": True,
        "summary": "independent read of the whole diff: defects, blast radius, standards, AC gaps, weak tests",
    },
    "qa-acceptance": {
        "covers_diff": False,
        "summary": "every acceptance criterion is proven by an automated test or covered by a manual checklist item",
    },
    codes.RequiredCheck.TEST_CHANGE_REVIEW.value: {
        "covers_diff": False,
        "summary": "every change to a test, snapshot, baseline image or verification config keeps or strengthens what it verifies",
    },
    # stage 3 — the bug template (E8)
    "root-cause-addressed": {
        "covers_diff": False,
        "summary": "the change removes the root cause the diagnosis names, not only the symptom, and its blast radius stays safe",
    },
    "regression-proof": {
        "covers_diff": False,
        "summary": "the regression test was red for the bug's reason and fails again without the fix",
    },
    # stage 3 — the refactor templates (scope §2.3)
    "structure-improved": {
        "covers_diff": False,
        "summary": "the code really moved toward the target structure — not churn, not half done",
    },
    "behavior-preserved": {
        "covers_diff": False,
        "summary": "no observable behaviour changed: outputs, errors, side effects, public API, what the user sees",
    },
    "net-public-behavior": {
        "covers_diff": False,
        "summary": "the safety net covers every (safety net) case through the public interface and fails if a behaviour breaks",
    },
    # stage 3 — the diff-review entries of the plugin step catalog (data/catalog.json, E14);
    # `security-review` is also the check of the mandatory risk-area gate (rules, every stage)
    "ux-conformance": {
        "covers_diff": False,
        "summary": "every changed screen shows the required states, keeps the repository's components and stays accessible",
    },
    "security-review": {
        "covers_diff": False,
        "summary": "adversarial security read of the diff: authentication, authorisation, secrets, injection, exposure",
    },
    "data-integrity": {
        "covers_diff": False,
        "summary": "no data loss or corruption, migrations in a safe order with a rollback path, old readers keep working",
    },
    "i18n-completeness": {
        "covers_diff": False,
        "summary": "every new or changed user-facing text exists in every shipped language, nothing hard-coded",
    },
    "performance-regression": {
        "covers_diff": False,
        "summary": "no unbounded work, blocking call or lost cache on a hot path",
    },
    "infra-safety": {
        "covers_diff": False,
        "summary": "builds stay reproducible, CI stays as strict, no secret or permission widened",
    },
}

# P3-A (P2 session 3): the engine stops on a close keyword next to an Issue reference in any
# commit message of the push range (S10, outbound.find_close_keywords) — that includes a
# harmless `fix: x (#42)`. The work frame therefore forbids Issue numbers in commit messages.
COMMIT_MESSAGE_RULE = (
    "- **Commit messages.** Never write an Issue or PR number (`#42`, `owner/repo#42`, `GH-42`, "
    "an issue URL) or a closing keyword (`close`, `closes`, `fix`, `fixes`, `resolve`, "
    "`resolves` … followed by a reference) in a commit message — not even `fix: x (#42)`. "
    "The engine links the Issue itself; a message with a reference stops the Issue for a human."
)

# P5 F2 (reverses P3-Z decision 5): the developer session gets the run's toolchain
# environment — the Guild cache variables, run_env and the repository's approved sandbox
# exceptions. Its own PATH / HOME stay the user's (the gate hook runs outside the sandbox with
# the session env), so the frame tells it to set them per command the way the named commands do.
SANDBOX_LIMITS_RULE = (
    "- **Sandbox and toolchain.** Your sandbox is the one the engine's `run` steps get: the same "
    "write roots, registry hosts and the repository's approved sandbox exceptions, and the "
    "Guild cache variables of the repository settings are set in your environment. Your PATH "
    "and HOME are still the user's, and the user's toolchain folders are read-only to you: run "
    "a repository tool (test runner, analyzer, formatter, package manager) the way the "
    "repository's named commands below do — with the same `export PATH=…` / `export HOME=…` "
    "prefix in the same Bash command — so it uses the Guild copy. Run the tests you touch "
    "yourself (red before the fix, green after) and read their failure output. If something "
    "still fails only because of the sandbox, note it in `note` and go on; never work around "
    "the sandbox. The repository's own git hooks are switched off for your session (the engine "
    "runs the same checks as `run` steps): commit normally, and never pass `--no-verify`."
)

TOOLCHAIN_CMD_MAX = 4000

FACT_VALUE_MAX = 2000
LIST_MAX = 200


# --- data files ---------------------------------------------------------------------

def _read_data(rel):
    """Text of a plugin data file (trusted, shipped with the plugin)."""
    path = os.path.join(DATA_DIR, rel[len("data/"):] if rel.startswith("data/") else rel)
    with open(path, encoding="utf-8") as f:
        return f.read()


def _load_template_file(rel):
    data = json.loads(_read_data(rel))
    try:
        schema.validate(data, "template")
    except schema.ValidationError as e:
        raise ValueError(f"{rel} is not a valid template: {e}") from e
    return data


def _earlier_stage_view(doc, stage):
    """A data template as an engine of `stage` < 3 reads it (E36): without the stage-3 additions —
    `op: create-followups`, the stage-3 `in:` files (codes.STAGE3_IN_FILES) and `in:failure-summary.md`
    on a step whose role is not the developer (Q8 carry-over ①: from stage 3 every writing step that a
    return or a rerun can target gets it; stages 1–2 gave it to the developer only). Below 2 also without
    `check: done-gate`. The stage-1/2 views are byte for byte the files of stage 2."""
    if stage >= 3:
        return doc
    steps = []
    for s in doc["steps"]:
        if s.get("op") == codes.OpKind.CREATE_FOLLOWUPS.value:
            continue
        if stage < 2 and s.get("check") == codes.CheckKind.DONE_GATE.value:
            continue
        if "inputs" in s:
            keep = []
            for i in s["inputs"]:
                name = i[len(codes.IN_PREFIX):] if i.startswith(codes.IN_PREFIX) else None
                if name in codes.STAGE3_IN_FILES:
                    continue
                if name == codes.InFile.FAILURE_SUMMARY.value and codes.role_class(s.get("role") or "") != codes.RoleClass.WORK.value:
                    continue
                keep.append(i)
            s = dict(s, inputs=keep)
        steps.append(s)
    return dict(doc, steps=steps)


def load_start_procedure(stage=None):
    """The plugin-fixed start procedure (template-schema dict). `stage` (default
    `defaults.ENGINE_STAGE`): below 3 without the stage-3 additions (_earlier_stage_view)."""
    return _earlier_stage_view(_load_template_file(START_PROCEDURE_FILE), _stage(stage))


CATALOG_DATA_FILE = "data/catalog.json"


def load_catalog_data():
    """The plugin step catalog as raw data (schemas/catalog checked) — for the instruction texts and
    the checks of the data files. The engine's reader with the rules beyond the schema is catalog.load."""
    data = json.loads(_read_data(CATALOG_DATA_FILE))
    try:
        schema.validate(data, "catalog")
    except schema.ValidationError as e:
        raise ValueError(f"{CATALOG_DATA_FILE} is not a valid catalog: {e}") from e
    return data


STAGE1_2_TEMPLATES = ("feature",)
"""The plugin templates an engine before stage 3 has (the others are stage 3's, codes.STAGE3_TEMPLATES)."""


def default_template_names(stage=None):
    """Names of the plugin's default templates of an engine stage (file stems of `data/templates/`;
    below stage 3 only STAGE1_2_TEMPLATES — the bug and refactor templates use stage-3 grammar)."""
    d = os.path.join(DATA_DIR, "templates")
    names = sorted(f[:-len(DEFAULT_TEMPLATE_SUFFIX)] for f in os.listdir(d) if f.endswith(DEFAULT_TEMPLATE_SUFFIX))
    return names if _stage(stage) >= 3 else [n for n in names if n in STAGE1_2_TEMPLATES]


def load_default_template(name, stage=None):
    """A plugin default template (template-schema dict). KeyError when the stage has none of that name.

    `stage` (default `defaults.ENGINE_STAGE`): the template as that engine reads it — below 3 without
    the stage-3 additions, below 2 also without the leader's `check: done-gate` (a stage-1 engine
    refuses it, procedure._step_errors); one file is the source for every stage (_earlier_stage_view)."""
    stage = _stage(stage)
    if name not in default_template_names(stage):
        raise KeyError(name)
    return _earlier_stage_view(_load_template_file(f"{DEFAULT_TEMPLATES_DIR}/{name}{DEFAULT_TEMPLATE_SUFFIX}"), stage)


def role_file_path(role):
    """The repository-relative path the engine reads a role file from (at the base SHA)."""
    if not _is_name(role):
        raise ValueError(f"invalid role name {role!r}")
    base = ROLE_FILES_DIR if role in PLUGIN_ROLES else AGENTS_DIR
    return f"{base}/{role}.md"


def default_role_file(role):
    """The plugin's default body of a plugin-owned role (requirements-engineer, auditor)."""
    if role not in PLUGIN_ROLES:
        raise KeyError(role)
    return _read_data(f"roles/{role}.md")


def _is_name(s):
    import re
    return isinstance(s, str) and re.match(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$", s) is not None and len(s) <= 64


# --- frames and tasks ---------------------------------------------------------------

STAGE3_COMMON_FRAME = "frames/stage3-common.md"
STAGE3_WORK_FRAME = "frames/stage3-work.md"
STAGE4_WORK_FRAME = "frames/stage4-work.md"
"""Stage 4 (VB9): appended to the work frame from stage 4 when the file exists (how to declare mutations)."""
CATALOG_LIST_TOKEN = "{catalog}"
KNOWLEDGE_TOKEN = "{knowledge_dir}"
"""Readiness T2 (R4-13 K2): where frames/common.md and frames/leader.md name the shared ⑥ knowledge folder — filled
with defaults.KNOWLEDGE_DIR (the same path in both channels)."""


def _with_knowledge(text):
    return text.replace(KNOWLEDGE_TOKEN, defaults.KNOWLEDGE_DIR)


def catalog_lines():
    """The requestable catalog steps as the stage-3 frame lists them (id, role, class, summary)."""
    out = []
    for e in load_catalog_data()["entries"]:
        if e["class"] == codes.CatalogClass.FIX.value:
            continue                       # fix-discovery comes only from a blocking discovery (E18)
        out.append(f"   - `{e['id']}` ({e['role']}, {e['class']}) — {e['summary']}")
    return "\n".join(out)


def _stage3_frame(rel):
    if not _data_exists(rel):
        return ""
    text = _read_data(rel).rstrip()
    return text.replace(CATALOG_LIST_TOKEN, catalog_lines()) if CATALOG_LIST_TOKEN in text else text


def frame(kind, role, role_class, stage=None):
    """The fixed frame text for a step kind / role (role: "developer" gets rule 5).

    `kind` is one of FRAME_KINDS; `role_class` must agree with it (the developer is the only
    work role, I4). Unknown values raise ValueError (fail-closed). `stage` (default
    `defaults.ENGINE_STAGE`): from 3 the stage-3 result rules follow the common rules
    (STAGE3_COMMON_FRAME — the catalog filled in) and, for the work frame, STAGE3_WORK_FRAME."""
    stage = _stage(stage)
    if kind not in FRAME_KINDS:
        raise ValueError(f"unknown frame kind {kind!r}")
    if role_class not in codes.RoleClass.values():
        raise ValueError(f"unknown role class {role_class!r}")
    if (kind == "work") != (role_class == codes.RoleClass.WORK.value):
        raise ValueError(f"frame kind {kind!r} does not fit role class {role_class!r}")
    if not _is_name(role):
        raise ValueError(f"invalid role name {role!r}")
    parts = [_with_knowledge(_read_data("frames/common.md")).rstrip()]
    if stage >= 3 and _stage3_frame(STAGE3_COMMON_FRAME):
        parts.append(_stage3_frame(STAGE3_COMMON_FRAME))
    parts.append(_read_data(f"frames/{kind}.md").rstrip())
    if kind == "work":
        parts[-1] += "\n" + COMMIT_MESSAGE_RULE + "\n" + SANDBOX_LIMITS_RULE
        if stage >= 3 and _stage3_frame(STAGE3_WORK_FRAME):
            parts[-1] += "\n" + _stage3_frame(STAGE3_WORK_FRAME)
        if stage >= codes.STAGE4 and _stage3_frame(STAGE4_WORK_FRAME):
            parts[-1] += "\n" + _stage3_frame(STAGE4_WORK_FRAME)
    return "\n\n".join(parts) + "\n"


STAGE3_TASKS_DIR = "tasks/stage3"
"""Stage-3 task texts (E36): for an engine stage ≥ 3, `tasks/stage3/<step id>.md` is appended to
`tasks/<step id>.md` (or is the whole text of a step that exists from stage 3 only — the catalog
steps, the bug and refactor templates' steps). Below stage 3 it is never read, so the stage 1–2
texts stay byte for byte what they were."""
STAGE4_TASKS_DIR = "tasks/stage4"
"""Stage 4: `tasks/stage4/<step id>.md` is appended the same way for an engine stage ≥ 4 (never read below)."""


def _stage(stage):
    s = defaults.ENGINE_STAGE if stage is None else stage
    codes.check_stage(s)
    return s


def task_text(step_id, stage=None):
    """The plugin-fixed task text of a step id ('' when the plugin has none for it).

    `stage` (default `defaults.ENGINE_STAGE`): from 3 the stage-3 part is appended (STAGE3_TASKS_DIR)."""
    if not _is_name(step_id):
        raise ValueError(f"invalid step id {step_id!r}")
    parts = []
    stage = _stage(stage)
    for rel in (f"tasks/{step_id}.md",) + ((f"{STAGE3_TASKS_DIR}/{step_id}.md",) if stage >= 3 else ()) \
            + ((f"{STAGE4_TASKS_DIR}/{step_id}.md",) if stage >= codes.STAGE4 else ()):
        if os.path.isfile(os.path.join(DATA_DIR, rel)):
            parts.append(_read_data(rel).rstrip())
    return "\n\n".join(parts) + "\n" if parts else ""


# --- the leader instruction (stage 2, scope §2.0 D10 D11 D25) ----------------------------

LEADER_FRAME_FILE = "frames/leader.md"
LEADER_TASK_FILES = {                     # situation → (task file stem, section | None)
    codes.StopReason.PLAN_GATE.value: ("plan-gate", None),
    codes.StopReason.DONE_GATE.value: ("done-gate", None),
}
NEEDS_LEADER_TASK_FILE = "needs-leader"   # one file: "## Common" + one "## Situation: <code>" section
LEADER_SITUATION_HEADING = "## Situation: "
LEADER_COMMON_HEADING = "## Common"
LEADER_STAGE4_DIR = "tasks/leader-stage4"
"""Stage 4: `plan-gate.md` / `done-gate.md` here are APPENDED to the text of the stages before (≥ 4 only)."""
LEADER_STAGE3_DIR = "tasks/leader-stage3"
"""Stage-3 leader task texts (E36). From engine stage 3: `plan-gate.md` / `done-gate.md` here REPLACE
the stage-2 file (the answer schema changed: adjust, models, included_fixes, duplicate …);
`needs-leader.md` here adds to the stage-2 one — its `## Common` is appended to the common section and
a `## Situation: <code>` section replaces (or, for a stage-3 situation, is) that situation's section.
Below stage 3 none of it is read: the stage-2 leader texts stay byte for byte what they were."""


def leader_frame():
    """The fixed frame of every leader session (data/frames/leader.md)."""
    return _with_knowledge(_read_data(LEADER_FRAME_FILE)).rstrip() + "\n"


def _sections(text):
    """{heading line: body} of the `## ` sections of a task file (text before the first is dropped)."""
    out, cur, buf = {}, None, []
    for line in text.split("\n"):
        if line.startswith("## "):
            if cur is not None:
                out[cur] = "\n".join(buf).strip()
            cur, buf = line.rstrip(), []
        elif cur is not None:
            buf.append(line)
    if cur is not None:
        out[cur] = "\n".join(buf).strip()
    return out


def _data_exists(rel):
    return os.path.isfile(os.path.join(DATA_DIR, rel))


def leader_task_text(situation, stage=None):
    """The plugin-fixed task text of a leader situation (the keys of codes.leader_answer_schemas(stage)).

    plan-gate / done-gate: their whole task file. The needs_leader situations: the common
    section of needs-leader.md plus the situation's own section. ValueError for a situation
    that has none (rule-unfillable / base-red / irreversible-change never call the leader, D9,
    E23 — fail closed). `stage` (default `defaults.ENGINE_STAGE`): from 3 the stage-3 texts
    (LEADER_STAGE3_DIR) apply; a stage-3 situation has no text before stage 3."""
    stage = _stage(stage)
    known = codes.leader_answer_schemas(stage) if stage >= 2 else codes.LEADER_ANSWER_SCHEMAS
    if situation in LEADER_TASK_FILES:
        stem, _ = LEADER_TASK_FILES[situation]
        rel = f"{LEADER_STAGE3_DIR}/{stem}.md"
        text = _read_data(rel if stage >= 3 and _data_exists(rel) else f"tasks/{stem}.md").rstrip()
        rel4 = f"{LEADER_STAGE4_DIR}/{stem}.md"
        if stage >= codes.STAGE4 and _data_exists(rel4):
            text += "\n\n" + _read_data(rel4).rstrip()
        return text + "\n"
    if situation not in known:
        raise ValueError(f"no leader task for situation {situation!r} in stage {stage}")
    secs = _sections(_read_data(f"tasks/{NEEDS_LEADER_TASK_FILE}.md"))
    common = secs.get(LEADER_COMMON_HEADING)
    own = secs.get(LEADER_SITUATION_HEADING + situation)
    rel3 = f"{LEADER_STAGE3_DIR}/{NEEDS_LEADER_TASK_FILE}.md"
    if stage >= 3 and _data_exists(rel3):
        secs3 = _sections(_read_data(rel3))
        if common and secs3.get(LEADER_COMMON_HEADING):
            common = common + "\n\n" + secs3[LEADER_COMMON_HEADING]
        own = secs3.get(LEADER_SITUATION_HEADING + situation) or own
    if not own or not common:
        raise ValueError(f"tasks/{NEEDS_LEADER_TASK_FILE}.md has no section for {situation!r}")
    return common + "\n\n" + LEADER_SITUATION_HEADING + situation + "\n\n" + own + "\n"


def build_leader_instruction(situation, fields, stage=None):
    """Fixed leader frame + the situation's task text + this call's specifics. The `-p` text
    recorded in the call's brief.json (session A, leader.py, calls this). `stage` (default
    `defaults.ENGINE_STAGE`): the engine stage of the call (leader_task_text).

    `fields`: issue (int), step (the check step / the step the situation is attached to),
    attempt (the call's folder number: the check attempt or k), in_dir (the engine folder with
    the in/ files, or None), in_files (names in it, `leader-input.json` first), docs (worktree
    paths of the judgment documents), format_retry (0 on the first call), errors (why the previous
    answer was rejected — LeaderFormatReason code + detail lines; empty on the first call)."""
    f = fields or {}
    out = [leader_frame().rstrip(),
           f"## Task — situation `{situation}`\n\n{leader_task_text(situation, stage).rstrip()}"]
    attempt = f.get("attempt")
    head = ["## This call", "",
            f"Issue #{f.get('issue')} · situation `{situation}` · step `{f.get('step')}`"
            + (f" · call {attempt}" if attempt else "") + " · role `leader`"]
    out.append("\n".join(head))
    in_files = list(f.get("in_files") or [])
    sec = ["### Engine folder (read these first; the only engine files you may read)", ""]
    if in_files:
        sec.append(f"Folder `{f.get('in_dir') or '(the engine folder)'}`:")
        sec += ["", _bullets(in_files)]
    else:
        sec.append("(none)")
    out.append("\n".join(sec))
    docs = list(f.get("docs") or [])
    out.append("### Judgment documents (paths — contents are not pasted; read what you need)\n\n"
               + (_bullets(docs) if docs else "(none)"))
    errors = list(f.get("errors") or [])
    if f.get("format_retry") or errors:
        lines = ["### Your previous answer was rejected", "",
                 f"This is re-call {f.get('format_retry') or 1}. Fix exactly these problems and change nothing else:", ""]
        lines += [f"- {_clip(e, 500)}" for e in errors[:LIST_MAX]] or ["- (the answer had no structured output)"]
        out.append("\n".join(lines))
    return "\n\n".join(out) + "\n"


# --- the instruction ----------------------------------------------------------------

def _get(obj, key, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _clip(text, limit=FACT_VALUE_MAX):
    text = str(text)
    return text if len(text) <= limit else text[:limit] + f" …[{len(text) - limit} more characters]"


def _fact_value(v):
    if isinstance(v, str):
        return _clip(v)
    return _clip(json.dumps(v, ensure_ascii=False, sort_keys=True))


def _bullets(items):
    items = list(items)[:LIST_MAX]
    return "\n".join(f"- `{i}`" for i in items)


def toolchain_section(toolchain):
    """The developer's "Repository commands" section (P5 F2) — '' when there is nothing to say.

    `toolchain` = {"commands": {name: shell text}, "env_names": [cache / run variable names]}
    from the repository settings (base blob). The command texts are the repository's own
    (trusted, human-committed), shown so the developer runs tools with the same PATH / HOME."""
    if not toolchain:
        return ""
    cmds = dict(toolchain.get("commands") or {})
    names = list(toolchain.get("env_names") or [])
    if not cmds and not names:
        return ""
    lines = ["### Repository commands", "",
             "The engine's `run` steps run these named commands (the full suite — you run only what "
             "you need). Set up a tool the same way when you run it yourself: copy the command's "
             "leading `export …;` part into the same Bash command."]
    if names:
        lines += ["", "Set in your environment by the engine: " + ", ".join(f"`{n}`" for n in names[:LIST_MAX]) + "."]
    for n in list(cmds)[:LIST_MAX]:
        lines += ["", f"`{n}`:", "", "```sh", _clip(cmds[n], TOOLCHAIN_CMD_MAX).replace("```", "` ` `"), "```"]
    return "\n".join(lines)


def build_instruction(step, brief_fields, toolchain=None, stage=None):
    """Fixed frame + step specifics (id, inputs, outputs, checks, facts, return context,
    re-entry dirty files, flaky marks). Returns the `-p` text recorded in brief.json.

    `step`: a procedure.Step or a dict with `id`, `kind`, `checks`. `brief_fields`: the brief.json
    fields — issue, attempt, role, role_class, inputs, in_dir, in_files, outputs, checks,
    rule_checks, facts, returned, reentry. Only role steps get an instruction.
    `toolchain` (work role only, P5 F2): see toolchain_section.
    `stage` (default `defaults.ENGINE_STAGE`): the engine stage — from 3 the stage-3 texts are
    added (task_text, frame); a caller running an earlier stage passes it."""
    stage = _stage(stage)
    f = brief_fields or {}
    step_id = _get(step, "id") or f.get("step")
    kind = _get(step, "kind")
    if kind is not None and str(kind) != codes.StepKind.ROLE.value:
        raise ValueError(f"only role steps get a work instruction (step {step_id!r} is {kind!r})")
    role = f.get("role") or (_get(step, "name") if kind is not None else None) or _get(step, "role")
    if not _is_name(role):
        raise ValueError(f"step {step_id!r} has no valid role")
    role_class = f.get("role_class") or codes.role_class(role)
    checks = list(f.get("checks") or _get(step, "checks") or [])
    frame_kind = "work" if role_class == codes.RoleClass.WORK.value else ("review" if checks else "judge")

    out = [frame(frame_kind, role, role_class, stage).rstrip()]
    task = task_text(step_id, stage)
    if task:
        out.append(f"## Task — step `{step_id}`\n\n{task.rstrip()}")

    attempt = f.get("attempt")
    head = [f"## This attempt", ""]
    head.append(f"Issue #{f.get('issue')} · step `{step_id}`" + (f" · attempt {attempt}" if attempt else "")
                + f" · role `{role}`")
    out.append("\n".join(head))

    inputs = [i for i in (f.get("inputs") or []) if not str(i).startswith("in:")]
    sec = ["### Inputs (paths — contents are not pasted; read what you need)", ""]
    sec.append(_bullets(inputs) if inputs else "(none)")
    in_files = list(f.get("in_files") or [])
    if in_files:
        in_dir = f.get("in_dir") or "(the engine folder)"
        sec += ["", f"Engine-made input files, in the folder `{in_dir}` (the only engine folder you may read):", ""]
        sec.append(_bullets(in_files))
    out.append("\n".join(sec))

    outputs = list(f.get("outputs") or [])
    if outputs:
        out.append("### Outputs — write exactly these paths and nothing else\n\n" + _bullets(outputs))
    elif role_class == codes.RoleClass.WORK.value:
        out.append("### Outputs\n\nNone declared: your work is the committed change on this branch.")
    else:
        out.append("### Outputs\n\nNone: you write no file.")

    if role_class == codes.RoleClass.WORK.value:
        tc = toolchain_section(toolchain)
        if tc:
            out.append(tc)
    elif toolchain:
        raise ValueError("only the work role gets the repository toolchain section")

    if checks:
        rule = set(f.get("rule_checks") or [])
        lines = ["### Required checks — your result's `checks` must contain every one of these ids", ""]
        for c in checks[:LIST_MAX]:
            meta = CHECK_CATALOG.get(c)
            text = f"- `{c}`" + (f" — {meta['summary']}" if meta else "")
            if c in rule:
                text += " (added by an engine rule: it may not be `n/a`)"
            if meta and meta["covers_diff"]:
                text += " (`reviewed` must cover every changed file)"
            lines.append(text)
        out.append("\n".join(lines))

    facts = f.get("facts") or {}
    if facts:
        lines = ["### Facts the engine collected", ""]
        lines += [f"- {k}: {_fact_value(facts[k])}" for k in sorted(facts)]
        out.append("\n".join(lines))

    returned = f.get("returned")
    if returned:
        lines = ["### Returned", "",
                 f"This step comes back from step `{returned.get('from_step')}` "
                 f"(attempt {returned.get('from_attempt')}), failure code `{returned.get('code')}`."]
        if returned.get("detail"):
            lines.append(f"Detail: {_clip(returned['detail'])}")
        errs = returned.get("errors") or []
        if errs:
            lines += ["", "Fix exactly these problems:", ""] + [f"- {_clip(e, 500)}" for e in errs[:LIST_MAX]]
        out.append("\n".join(lines))

    reentry = f.get("reentry")
    if reentry:
        lines = ["### Re-entry", "",
                 "The branch HEAD moved forward only from the recorded HEAD: "
                 + ("yes" if reentry.get("forward_only") else "NO — check the history before you continue") + "."]
        dirty = reentry.get("dirty_files") or []
        if dirty:
            lines += ["", "Uncommitted files found when this attempt started (finish or revert them; "
                          "the tree must be clean at the end):", "", _bullets(dirty)]
        else:
            lines.append("The tree was clean when this attempt started.")
        out.append("\n".join(lines))

    return "\n\n".join(out) + "\n"


# --- system prompt ------------------------------------------------------------------

def strip_frontmatter(text):
    """Role-file body without its YAML frontmatter (stage 1 ignores it, I4).

    Frontmatter = a first line `---` up to the next line `---` (or `...`). An unterminated one
    raises ValueError (fail-closed: the engine must not feed half a header to the model)."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    if text.startswith("﻿"):
        text = text[1:]
    lines = text.split("\n")
    if not lines or lines[0].rstrip() != "---":
        return text
    for i in range(1, len(lines)):
        if lines[i].rstrip() in ("---", "..."):
            return "\n".join(lines[i + 1:]).lstrip("\n")
    raise ValueError("role file frontmatter is not terminated")


def system_prompt(claude_md, dot_claude_md, role_body):
    """--append-system-prompt text: root CLAUDE.md, .claude/CLAUDE.md, then the role body
    (base-SHA blobs; frontmatter stripped — stage 1 ignores it, I4). Missing parts skipped."""
    parts = []
    for title, body in (("Repository instructions — CLAUDE.md", claude_md),
                        ("Repository instructions — .claude/CLAUDE.md", dot_claude_md),
                        ("Your role file", strip_frontmatter(role_body) if role_body else role_body)):
        if body and body.strip():
            parts.append(f"# {title}\n\n{body.strip()}")
    return "\n\n".join(parts) + ("\n" if parts else "")
