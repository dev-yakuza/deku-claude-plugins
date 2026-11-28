"""Procedure grammar: templates → procedure.yaml, parse and check (design §2, §3, §4, §6.1) — U3.

Files are JSON text (a YAML 1.2 subset — interfaces.md "해석한 곳"). Shapes:
`schemas/template.schema.json` (templates and the plugin start procedure) and
`schemas/procedure.schema.json` (the Issue plan). Beyond the schema this module checks
what a schema cannot say:

  - step ids are unique; `on_fail.back_to` names an EARLIER step (or the step itself);
  - a `run:` name exists in the repository settings' `commands` (§7.10);
  - `checks` only on role steps; `in:` inputs only in the allowed set;
  - stage-1 ops only (`codes.STAGE1_OPS`); `{issue}` fully substituted in a procedure;
  - judge roles' outputs never overlap another step's outputs (§7.6 ownership).

Further checks (U3, fail-closed — see the session report):
  - stage 1 has no `check: done-gate` (§9.2: the template's done-gate is stage 2);
  - `op: create-pr` at most once and only as the last step (nothing runs after the PR);
  - no step output is a control file (§7.6 — control files are write-denied to roles);
  - a template uses no placeholder other than `{issue}`; a procedure none at all.

Only the engine writes procedure.yaml (§6.1). Stage 1: start procedure + the feature
template copied as is (no adjustment), revision 1, committed on the Issue branch.

Stage 2 (scope D1, D19, V4): the procedure is written twice — `build_start` (revision 1 =
the start procedure alone, origin template `start`) and, on the plan answer,
`attach_template` (revision 2 = + the chosen template). A template with create-pr carries
exactly one `check: done-gate` right before it (`template_errors`, L23); a procedure has at
most one done-gate, right before create-pr; a procedure without done-gate (written by the
stage-1 engine) stays readable (L22). Only STAGE2_OPS (no epic op).

Stage 3:
  - `op: create-followups` (E20) — at most one, right after create-pr, then the last step;
  - a template may name `{path:<kind>}` as a whole inputs / outputs item (E4); `expand_paths`
    puts the globs of the repository's path rules there, so procedure.yaml shows the globs;
  - `attach_plan` = the plan answer's revision: template + the leader's catalog adds (E12);
  - a WORK role's output glob may contain `*` / `**` directory segments (a test-code rule is
    `test/**/*_test.dart`): a work role's outputs grant no write access — the control-file denies
    and the control-file comparison stay — so only a glob that names a control file or folder
    by its own segments is refused. A judge's outputs ARE its write scope: the old rule stays;
  - a work step owns the files it really changed, not its globs (review-q0 D2, K2):
    `file_owned_steps` and `owner_of(path, owned)`.
"""

import copy
import json

from . import catalog as catmod, codes, defaults, globs, schema

KIND_KEYS = tuple(codes.StepKind.values())          # role, run, check, op
START_TEMPLATE = "start"                            # the plugin start procedure's name
PATH_TOKENS = {codes.path_token(k): k for k in codes.TEMPLATE_PATH_KINDS}      # stage 3 (E4)
RESERVED_STEP_ID = "leader"                          # stage 2 = paths.LEADER_DIR: tmp/…/leader-<k> (D13)
_KEY_ORDER = ("id",) + KIND_KEYS + ("inputs", "outputs", "on_fail", "checks")


class ProcedureError(Exception):
    """A template or procedure violates the grammar. `.errors` lists the reasons."""

    def __init__(self, errors):
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


# --- text → JSON ------------------------------------------------------------------

def _no_dupes(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise ValueError(f"duplicate key {k!r}")
        out[k] = v
    return out


def _bad_constant(name):
    raise ValueError(f"not JSON: {name}")


def _loads(text, what):
    if isinstance(text, (bytes, bytearray)):
        try:
            text = bytes(text).decode("utf-8")
        except UnicodeDecodeError:
            raise ProcedureError([f"{what}: not UTF-8"]) from None
    if not isinstance(text, str):
        raise ProcedureError([f"{what}: expected text"])
    try:
        return json.loads(text, object_pairs_hook=_no_dupes, parse_constant=_bad_constant)
    except (ValueError, RecursionError) as e:
        raise ProcedureError([f"{what}: not JSON text ({e}) — files are JSON (a YAML subset)"]) from None


def _schema_errors(raw, name):
    errs = schema.errors(raw, schema.load_schema(name))
    return [f"schema {name}: {e}" for e in errs]


# --- model ------------------------------------------------------------------------

class Step:
    """One parsed step. Attributes: id, kind (codes.StepKind value), name (role / run /
    check / op value), inputs, outputs, on_fail (dict or None), checks (list)."""

    def __init__(self, raw):
        if isinstance(raw, Step):
            raw = raw.to_json()
        if not isinstance(raw, dict):
            raise ProcedureError([f"a step must be an object: {raw!r}"])
        kinds = [k for k in KIND_KEYS if k in raw]
        if len(kinds) != 1:
            raise ProcedureError([f"step {raw.get('id')!r}: exactly one of {'/'.join(KIND_KEYS)} (got {kinds})"])
        unknown = set(raw) - set(_KEY_ORDER)
        if unknown:
            raise ProcedureError([f"step {raw.get('id')!r}: keys outside the grammar {sorted(unknown)}"])
        self.id = raw.get("id")
        self.kind = kinds[0]
        self.name = raw[self.kind]
        self.inputs = list(raw.get("inputs", []))
        self.outputs = list(raw.get("outputs", []))
        self.on_fail = dict(raw["on_fail"]) if raw.get("on_fail") is not None else None
        self.checks = list(raw.get("checks", []))
        self._present = {k for k in ("inputs", "outputs", "on_fail", "checks") if k in raw}

    @property
    def is_review(self):
        """True when the step has `checks` (§4)."""
        return self.kind == codes.StepKind.ROLE.value and bool(self.checks)

    @property
    def role_class(self):
        """codes.RoleClass value for role steps, None otherwise (I4)."""
        return codes.role_class(self.name) if self.kind == codes.StepKind.ROLE.value else None

    @property
    def is_judge(self):
        return self.role_class == codes.RoleClass.JUDGE.value

    def engine_inputs(self):
        """The `in:` input names (codes.InFile values) of this step."""
        return [i[len(codes.IN_PREFIX):] for i in self.inputs if i.startswith(codes.IN_PREFIX)]

    def to_json(self):
        out = {"id": self.id, self.kind: self.name}
        if "inputs" in self._present:
            out["inputs"] = list(self.inputs)
        if "outputs" in self._present or self.kind == codes.StepKind.ROLE.value:
            out["outputs"] = list(self.outputs)
        if self.on_fail is not None:
            out["on_fail"] = {"back_to": self.on_fail["back_to"], "max": self.on_fail["max"]}
        if "checks" in self._present:
            out["checks"] = list(self.checks)
        return out

    def __eq__(self, other):
        return isinstance(other, Step) and self.to_json() == other.to_json()

    def __repr__(self):
        return f"Step({self.id!r}, {self.kind}={self.name!r})"


class Procedure:
    """A parsed procedure. Attributes: format, issue, revision, origin (dict), steps (list[Step]).

    The constructor validates the schema (ProcedureError); `check` adds the rest.
    """

    def __init__(self, raw):
        if isinstance(raw, Procedure):
            raw = raw.to_json()
        errs = _schema_errors(raw, "procedure")
        if errs:
            raise ProcedureError(errs)
        self.format = raw["format"]
        self.issue = raw["issue"]
        self.revision = raw["revision"]
        self.origin = dict(raw["origin"])
        self.new_template_candidate = raw.get("new_template_candidate")
        self.steps = [Step(s) for s in raw["steps"]]

    @property
    def step_ids(self):
        return [s.id for s in self.steps]

    def step(self, step_id):
        for s in self.steps:
            if s.id == step_id:
                return s
        raise KeyError(f"no step {step_id!r} in the procedure")

    def index(self, step_id):
        for i, s in enumerate(self.steps):
            if s.id == step_id:
                return i
        raise KeyError(f"no step {step_id!r} in the procedure")

    def file_owned_steps(self):
        """Stage 3 (D2): ids of the steps that own the files they really changed instead of their
        output globs — the work-role steps with outputs (reproduce, safety-net)."""
        return [s.id for s in self.steps if s.role_class == codes.RoleClass.WORK.value and s.outputs]

    def owner_of(self, path, owned=None):
        """The step id whose `outputs` match `path`, or None (§7.6 ownership, I3).

        Stage 3 (K2): `owned` = {step id: the paths that step really owns} (facts.step_files, for
        `file_owned_steps`); such a step owns exactly those paths, every other step its globs."""
        owned = owned or {}
        for s in self.steps:
            if s.id in owned:
                if path in owned[s.id]:
                    return s.id
                continue
            for pat in s.outputs:
                if globs.match(pat, path):
                    return s.id
        return None

    def to_json(self):
        out = {
            "format": self.format,
            "issue": self.issue,
            "revision": self.revision,
            "origin": {k: self.origin[k] for k in ("template", "version", "start")},
        }
        if self.new_template_candidate is not None:
            out["new_template_candidate"] = self.new_template_candidate
        out["steps"] = [s.to_json() for s in self.steps]
        return out

    def __eq__(self, other):
        return isinstance(other, Procedure) and self.to_json() == other.to_json()


# --- checks -----------------------------------------------------------------------

def _placeholders(s):
    """Every `{…}` group in a string."""
    out, i = [], 0
    while True:
        a = s.find("{", i)
        if a < 0:
            b = s.find("}", i)
            if b >= 0:
                out.append(s[b:b + 1])
            return out
        b = s.find("}", a)
        out.append(s[a:b + 1] if b >= 0 else s[a:])
        if b < 0:
            return out
        i = b + 1


def _step_errors(steps, stage, template):
    """Checks shared by templates and procedures. `steps` = list of Step."""
    errs = []
    seen = {}
    for i, s in enumerate(steps):
        where = f"step {s.id!r}"
        if s.id in seen:
            errs.append(f"{where}: duplicate step id")
        else:
            seen[s.id] = i
        if stage >= 2 and s.id == RESERVED_STEP_ID:
            # needs_leader calls use the name for their temp folders (tmp/…/leader-<k>, D13)
            errs.append(f"{where}: step id {RESERVED_STEP_ID!r} is reserved for the leader calls from stage 2")
        # kind-specific keys (the schema says the same; repeated so a Step built from a
        # raw dict that skipped the schema is still checked)
        if s.checks and s.kind != codes.StepKind.ROLE.value:
            errs.append(f"{where}: `checks` only on role steps")
        if s.kind != codes.StepKind.ROLE.value and "outputs" in s._present:
            errs.append(f"{where}: `outputs` only on role steps")
        if s.on_fail is not None and s.kind not in (codes.StepKind.ROLE.value, codes.StepKind.RUN.value):
            errs.append(f"{where}: `on_fail` only on role and run steps")
        for inp in s.inputs:
            if inp.startswith(codes.IN_PREFIX) and inp[len(codes.IN_PREFIX):] not in codes.InFile.values():
                errs.append(f"{where}: unknown engine input {inp!r}")
            elif inp.startswith(codes.IN_PREFIX) and stage < 3 and inp[len(codes.IN_PREFIX):] in codes.STAGE3_IN_FILES:
                errs.append(f"{where}: engine input {inp!r} is not available in stage {stage}")
        if s.kind == codes.StepKind.OP.value:
            if s.name not in codes.OpKind.values():
                errs.append(f"{where}: unknown op {s.name!r}")
            elif s.name not in codes.stage_ops(stage):
                errs.append(f"{where}: op {s.name!r} is not available in stage {stage}")
        if s.kind == codes.StepKind.CHECK.value:
            if s.name not in codes.CheckKind.values():
                errs.append(f"{where}: unknown check kind {s.name!r}")
            elif stage == 1 and s.name == codes.CheckKind.DONE_GATE.value:
                errs.append(f"{where}: check done-gate is not available in stage 1 (§9.2)")
        for p in s.inputs + s.outputs:
            if template and stage >= 3 and p in PATH_TOKENS:
                continue                     # E4: expanded when the procedure is written
            ph = [x for x in _placeholders(p) if not (template and x == "{issue}")]
            if ph:
                errs.append(f"{where}: placeholder {ph[0]!r} in {p!r}"
                            + (" (only {issue} in a template)" if template else " (a procedure is fully substituted)"))
    # back_to: an earlier step or the step itself. In a template a target outside the
    # template (a start-procedure step) is resolved when `build` joins them.
    for i, s in enumerate(steps):
        if s.on_fail is None:
            continue
        t = s.on_fail.get("back_to")
        if t in seen:
            if seen[t] > i:
                errs.append(f"step {s.id!r}: on_fail.back_to {t!r} is a later step")
        elif not template:
            errs.append(f"step {s.id!r}: on_fail.back_to {t!r} is not a step")
    # create-pr: at most once, last
    prs = [i for i, s in enumerate(steps)
           if s.kind == codes.StepKind.OP.value and s.name == codes.OpKind.CREATE_PR.value]
    if len(prs) > 1:
        errs.append("op create-pr appears more than once")
    # stage 3 (E20): create-followups at most once, right after create-pr; nothing else follows the PR
    tails = [i for i, s in enumerate(steps)
             if s.kind == codes.StepKind.OP.value and s.name == codes.OpKind.CREATE_FOLLOWUPS.value]
    if stage >= 3:
        if len(tails) > 1:
            errs.append("op create-followups appears more than once (E20)")
        if tails and (not prs or tails[0] != prs[-1] + 1):
            errs.append("op create-followups must come right after op create-pr (E20)")
    last = prs[-1] + (1 if stage >= 3 and prs[-1] + 1 in tails else 0) if prs else None
    if prs and last != len(steps) - 1 and not template:
        errs.append("op create-pr must be the last step" + (" (only create-followups may follow)" if stage >= 3 else ""))
    # stage 2 (D19): at most one done-gate, and only right before create-pr
    if stage >= 2:
        gates = [i for i, s in enumerate(steps)
                 if s.kind == codes.StepKind.CHECK.value and s.name == codes.CheckKind.DONE_GATE.value]
        if len(gates) > 1:
            errs.append("check done-gate appears more than once (D19)")
        if gates and prs and gates[-1] != prs[-1] - 1:
            errs.append("check done-gate must come right before op create-pr (D19)")
        if gates and not prs:
            errs.append("check done-gate without an op create-pr after it (D19)")
    return errs


def template_errors(raw, stage):
    """Stage-2 template rules beyond `_step_errors` (§4.1, D19) — [] when fine.

    From stage 2 the only planned check in a template is the done-gate: a template with
    `op: create-pr` must carry exactly one `check: done-gate` right before it (else the
    engine refuses to start — L23), and a plan-gate belongs to the start procedure only.
    Stage 1 adds nothing here (its done-gate refusal is in `_step_errors`)."""
    if isinstance(stage, bool) or not isinstance(stage, int) or stage < 2:
        return []
    steps = [Step(s) for s in raw["steps"]]
    errs = _step_errors(steps, stage, template=True)
    prs = [s for s in steps if s.kind == codes.StepKind.OP.value and s.name == codes.OpKind.CREATE_PR.value]
    gates = [s for s in steps if s.kind == codes.StepKind.CHECK.value and s.name == codes.CheckKind.DONE_GATE.value]
    if prs and not gates:
        errs.append(f"template {raw.get('template')!r}: op create-pr needs a check done-gate right before it "
                    "from stage 2 (D19)")
    for s in steps:
        if s.kind == codes.StepKind.CHECK.value and s.name == codes.CheckKind.PLAN_GATE.value:
            errs.append(f"step {s.id!r}: check plan-gate belongs to the start procedure, not a template (§4.1)")
    return errs


def _work_glob_names_control(pattern, issue):
    """Stage 3, a work role's output: True when the glob names a control file or folder by one of
    its own segments. A bare `*` / `**` directory segment does not count (module doc)."""
    if not globs.is_glob(pattern):
        return globs.is_control_file(pattern, issue)
    low = pattern.lower()
    if low.endswith("/"):
        return True
    segs = low.split("/")
    if any(seg not in ("*", "**") and globs.match(seg, name) for seg in segs[:-1] for name in globs.CONTROL_FOLDERS):
        return True
    if any(globs.match(segs[-1], name) for name in globs.CONTROL_NAMES + globs.CONTROL_FOLDERS):
        return True                          # includes a trailing `**` and `*`
    return globs.match(low, defaults.SPECS_DIR.replace("{issue}", str(issue)) + "/procedure.yaml")


def _ownership_errors(steps, issue, stage=1):
    """§7.6: a judge step's outputs overlap no other step's outputs; no output is a control file."""
    errs = []
    for i, a in enumerate(steps):
        for pa in a.outputs:
            try:
                work = stage >= 3 and a.role_class == codes.RoleClass.WORK.value
                if _work_glob_names_control(pa, issue) if work else globs.names_control_file(pa, issue):
                    errs.append(f"step {a.id!r}: output {pa!r} is a control file (§7.6)")
            except ValueError as e:
                errs.append(f"step {a.id!r}: output {pa!r}: {e}")
                continue
            for b in steps[i + 1:]:
                if not (a.is_judge or b.is_judge):
                    continue
                for pb in b.outputs:
                    try:
                        hit = globs.may_overlap(pa, pb)
                    except ValueError as e:
                        errs.append(f"step {b.id!r}: output {pb!r}: {e}")
                        continue
                    if hit:
                        errs.append(f"steps {a.id!r} and {b.id!r}: outputs {pa!r} and {pb!r} overlap "
                                    "(a judge step's outputs are its own, §7.6)")
    return errs


def check(procedure, commands, stage=1):
    """Return a list of grammar errors (empty when valid). Used at plan time and on every change.

    `commands`: the repository settings' command names (a dict of commands or any
    iterable of names); None skips only the `run:` name check (reading a committed
    procedure back without the settings at hand).
    """
    if not isinstance(procedure, Procedure):
        try:
            procedure = Procedure(procedure)
        except ProcedureError as e:
            return list(e.errors)
    errs = _step_errors(procedure.steps, stage, template=False)
    if commands is not None:
        names = set(commands)
        for s in procedure.steps:
            if s.kind == codes.StepKind.RUN.value and s.name not in names:
                errs.append(f"step {s.id!r}: run {s.name!r} is not a named command of the repository settings")
    errs += _ownership_errors(procedure.steps, procedure.issue, stage)
    return errs


# --- parse / build / dump ---------------------------------------------------------

def parse_template(text, stage=1):
    """Parse and check a template / start-procedure file. Returns the raw dict."""
    raw = _loads(text, "template")
    errs = _schema_errors(raw, "template")
    if errs:
        raise ProcedureError(errs)
    steps = [Step(s) for s in raw["steps"]]
    errs = _step_errors(steps, stage, template=True)
    if not errs and raw.get("template") != START_TEMPLATE:
        errs = template_errors(raw, stage)
    if errs:
        raise ProcedureError(errs)
    return raw


def parse_procedure(text, commands=None, stage=1):
    """Parse and check procedure.yaml. `commands` = repo-config command names to resolve `run:`."""
    raw = _loads(text, "procedure.yaml")
    proc = Procedure(raw)
    errs = check(proc, commands, stage=stage)
    if errs:
        raise ProcedureError(errs)
    return proc


def _subst(value, issue):
    return value.replace("{issue}", str(issue))


def _as_template(t, what, stage=1):
    """A template dict from a dict or its text; text is parsed with `stage`'s rules (a stage-2
    template carries the done-gate, which the stage-1 rules refuse)."""
    if isinstance(t, (str, bytes, bytearray)):
        return parse_template(t, stage=stage)
    errs = _schema_errors(t, "template")
    if errs:
        raise ProcedureError([f"{what}: {e}" for e in errs])
    return t


def build(start, template, issue, commands, stage=1):
    """Stage 1: start procedure + template → Procedure (revision 1, `{issue}` substituted).

    `start` / `template` are raw dicts (from parse_template) or their text. The start
    procedure is the one named `start`; the template must not be. Steps are copied as
    is (§9.2: no adjustment); the result passes `check` or ProcedureError is raised.
    """
    if isinstance(issue, bool) or not isinstance(issue, int) or issue < 1:
        raise ProcedureError([f"bad issue number {issue!r}"])
    start = _as_template(start, "start procedure", stage)
    template = _as_template(template, "template", stage)
    errs = []
    if start["template"] != START_TEMPLATE:
        errs.append(f"the start procedure must be named {START_TEMPLATE!r}, not {start['template']!r}")
    if template["template"] == START_TEMPLATE:
        errs.append(f"the template must not be the start procedure ({START_TEMPLATE!r})")
    if errs:
        raise ProcedureError(errs)
    steps = []
    for raw in copy.deepcopy(start["steps"]) + copy.deepcopy(template["steps"]):
        for key in ("inputs", "outputs"):
            if key in raw:
                raw[key] = [_subst(p, issue) for p in raw[key]]
        steps.append(raw)
    raw = {
        "format": defaults.FORMAT,
        "issue": issue,
        "revision": 1,
        "origin": {"template": template["template"], "version": template["version"],
                   "start": start["version"]},
        "steps": steps,
    }
    proc = Procedure(raw)
    errs = check(proc, commands, stage=stage)
    if errs:
        raise ProcedureError(errs)
    return proc


def _substituted(steps, issue):
    out = []
    for raw in copy.deepcopy(steps):
        for key in ("inputs", "outputs"):
            if key in raw:
                raw[key] = [_subst(p, issue) for p in raw[key]]
        out.append(raw)
    return out


def build_start(start, issue, commands, stage=2):
    """Stage ≥ 2 (D1): revision 1 = the start procedure alone (analyze → ac-format → plan).

    origin = {template: "start", version: <start version>, start: <start version>}; the
    template steps are attached by `attach_template` when the plan answer comes. The result
    passes `check` (a procedure without create-pr is fine) or ProcedureError is raised."""
    if isinstance(stage, bool) or not isinstance(stage, int) or stage < 2:
        raise ProcedureError([f"build_start is the stage-2 path (D1), not stage {stage!r} — use build"])
    if isinstance(issue, bool) or not isinstance(issue, int) or issue < 1:
        raise ProcedureError([f"bad issue number {issue!r}"])
    start = _as_template(start, "start procedure", stage)
    if start["template"] != START_TEMPLATE:
        raise ProcedureError([f"the start procedure must be named {START_TEMPLATE!r}, not {start['template']!r}"])
    raw = {
        "format": defaults.FORMAT,
        "issue": issue,
        "revision": 1,
        "origin": {"template": START_TEMPLATE, "version": start["version"], "start": start["version"]},
        "steps": _substituted(start["steps"], issue),
    }
    proc = Procedure(raw)
    errs = check(proc, commands, stage=stage)
    if errs:
        raise ProcedureError(errs)
    return proc


def is_start_only(procedure):
    """True for a stage-2 revision before the plan answer (origin.template = start, D1)."""
    return procedure.origin.get("template") == START_TEMPLATE


def attach_template(procedure, template, commands, stage=2):
    """Stage ≥ 2 (D1): the plan answer's revision — the start-only `procedure` + `template`
    steps (`{issue}` substituted), revision + 1, origin = the template's name / version.

    Refuses a procedure that already carries a template (L22: then no new revision is
    written) and a template that breaks the stage-2 template rules (D19). The result passes
    `check` with `commands` (ownership, run names, done-gate position) or ProcedureError."""
    if not is_start_only(procedure):
        raise ProcedureError([f"the procedure already follows template {procedure.origin.get('template')!r} "
                              "(no new revision — L22)"])
    template = _as_template(template, "template", stage)
    if template["template"] == START_TEMPLATE:
        raise ProcedureError([f"the template must not be the start procedure ({START_TEMPLATE!r})"])
    errs = template_errors(template, stage)
    if errs:
        raise ProcedureError(errs)
    steps = [s.to_json() for s in procedure.steps] + _substituted(template["steps"], procedure.issue)
    new = with_revision(procedure, steps)
    new.origin = {"template": template["template"], "version": template["version"],
                  "start": procedure.origin["start"]}
    new = Procedure(new.to_json())
    errs = check(new, commands, stage=stage)
    if errs:
        raise ProcedureError(errs)
    return new


# --- stage 3: path placeholders, usable templates, the plan answer --------------------

def _kind_globs(path_globs, kind):
    if path_globs is None:
        return []
    return list((path_globs(kind) if callable(path_globs) else path_globs.get(kind)) or ())


def expand_paths(template, path_globs):
    """E4: a copy of the raw `template` with every `{path:<kind>}` item replaced by the globs of
    that kind, in place and without repeating an item.

    `path_globs` = {kind: [globs]} or a function of the kind (RepoConfig.path_globs).
    ProcedureError when a kind the template names has no glob in the settings."""
    out = copy.deepcopy(template)
    errs = []
    for step in out["steps"]:
        for key in ("inputs", "outputs"):
            if not any(p in PATH_TOKENS for p in step.get(key, ())):
                continue
            items = []
            for p in step[key]:
                new = [p]
                if p in PATH_TOKENS:
                    new = _kind_globs(path_globs, PATH_TOKENS[p])
                    if not new:
                        errs.append(f"step {step['id']!r}: {p} — the repository settings have no "
                                    f"{PATH_TOKENS[p]} path rule")
                items += [x for x in new if x not in items]
            step[key] = items
    if errs:
        raise ProcedureError(errs)
    return out


def _planned_steps(procedure, template, path_globs, stage):
    """(checked template, its raw steps: `{issue}` substituted, path placeholders expanded)."""
    if not is_start_only(procedure):
        raise ProcedureError([f"the procedure already follows template {procedure.origin.get('template')!r} "
                              "(no new revision — L22)"])
    template = _as_template(template, "template", stage)
    if template["template"] == START_TEMPLATE:
        raise ProcedureError([f"the template must not be the start procedure ({START_TEMPLATE!r})"])
    errs = template_errors(template, stage)
    if errs:
        raise ProcedureError(errs)
    # substitute first: a `{issue}` in a settings glob is a placeholder error, not a substitution
    sub = dict(template, steps=_substituted(template["steps"], procedure.issue))
    return template, expand_paths(sub, path_globs)["steps"]


def attach_plan(procedure, template, commands, *, path_globs, catalog, adjust=(), candidate=False, stage=3):
    """Stage ≥ 3 (E12): the plan answer's revision — start procedure + `template` (paths expanded)
    + the catalog steps of `adjust`, as ONE revision. Returns (Procedure, [inserted catalog ids]).

    `adjust` = the answer's [{"op": "add", "step", …}]: same positions and input propagation as a
    role request (E15), `current` = the plan step. An id the template already has is not inserted
    again (not in the returned list). ProcedureError: an unknown or not requestable id, a step
    twice, more than CATALOG_ADDS_MAX, no position, or a refused `check`.
    `candidate`: the leader's new_template_candidate; two or more adjusts set it by themselves."""
    template, steps = _planned_steps(procedure, template, path_globs, stage)
    adjust = list(adjust or ())
    plan = [s.id for s in procedure.steps
            if s.kind == codes.StepKind.CHECK.value and s.name == codes.CheckKind.PLAN_GATE.value]
    ids = [a["step"] for a in adjust]
    ok = set(catmod.requestable_ids(catalog))
    errs = [f"adjust: op {a.get('op')!r} (only add)" for a in adjust if a.get("op") != codes.RequestOp.ADD.value]
    errs += [f"adjust: {i!r} is not a catalog step a plan may add" for i in sorted(set(ids) - ok)]
    errs += [f"adjust: {i!r} is named twice" for i in sorted({i for i in ids if ids.count(i) > 1})]
    if len(ids) > defaults.CATALOG_ADDS_MAX:
        errs.append(f"adjust: {len(ids)} steps (at most {defaults.CATALOG_ADDS_MAX})")
    if adjust and not plan:
        errs.append("adjust: the procedure has no plan-gate step")
    if errs:
        raise ProcedureError(errs)
    raw = with_revision(procedure, [s.to_json() for s in procedure.steps] + steps).to_json()
    raw["origin"] = {"template": template["template"], "version": template["version"],
                     "start": procedure.origin["start"]}
    if candidate or len(adjust) >= 2:
        raw["new_template_candidate"] = True
    new = Procedure(raw)
    inserted = []
    if adjust:
        dev = catmod.developer_step(new)
        statuses = {s.id: codes.StepStatus.PENDING.value for s in new.steps}
        have, entries = set(new.step_ids), []
        for i in ids:
            if i in have:
                continue
            at = catmod.position(new, statuses, plan[-1], catalog[i])
            if at is None:
                raise ProcedureError([f"adjust: no position for {i!r} in template {template['template']!r}"])
            entries.append((at, catmod.expand(catalog[i], new.issue, dev), catalog[i]))
            inserted.append(i)
        raw["steps"] = catmod.insert(new, entries)
        new = Procedure(raw)
    errs = check(new, commands, stage=stage)
    if errs:
        raise ProcedureError(errs)
    return new, inserted


def template_problems(start, template, issue, commands, path_globs, stage=3):
    """E2 `template-unusable`: why `template` (raw dict or text) cannot become this repository's
    procedure — [] = usable. Assembles start + template the way the plan answer does."""
    try:
        attach_plan(build_start(start, issue, commands, stage=stage), template, commands,
                    path_globs=path_globs, catalog={}, stage=stage)
    except ProcedureError as e:
        return list(e.errors)
    return []


def dump(procedure):
    """Serialise a Procedure to the procedure.yaml text the engine commits (stable key order)."""
    if not isinstance(procedure, Procedure):
        procedure = Procedure(procedure)
    return json.dumps(procedure.to_json(), indent=2, ensure_ascii=False, allow_nan=False) + "\n"


def with_revision(procedure, new_steps):
    """Return a copy with `new_steps` and revision + 1 (§4.3 — structure changes only).

    ValueError when `new_steps` equals the current steps (no structure change, no new
    revision). The copy passes the schema; the caller runs `check` with the settings.
    """
    steps = [s.to_json() if isinstance(s, Step) else copy.deepcopy(s) for s in new_steps]
    if [Step(s).to_json() for s in steps] == [s.to_json() for s in procedure.steps]:
        raise ValueError("the steps did not change; the revision stays")
    raw = procedure.to_json()
    raw["steps"] = steps
    raw["revision"] = procedure.revision + 1
    return Procedure(raw)
