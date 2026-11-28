"""Mandatory rules re-checked on the actual changed files (design §7, §7.11, I12) — U11.

Neither leader nor evolve can change these (§7). Applied with the same function at plan
time, after every code-changing step and right before PR creation (stage 1, §4.4-3):

  - code changed → a verification (`run`) step must exist;
  - code changed → a review step must exist;
  - a risk-area path changed → that area's gate step must exist (plugin-fixed gate
    definition inserted before PR creation when missing);
  - a `verification` path changed → the review step must carry the
    `test-change-review` check (added to `checks`; a finished review goes back to pending);
  - merge is always a human's.
Cannot supply (the role is not in the repo) → stop RULE_UNFILLABLE (stage 1: needs_human).
The changed verification paths go to the PR's "검토할 결정".

U11 choices (fail-closed — the P3-C report lists them as interpretations):
  - "code" = every changed path outside `docs/specs/<N>/` (docs elsewhere count too);
    `changed_paths` is the cumulative list (facts changed_files, both rename sides).
  - "a verification step exists" = some `run` step names a REPOSITORY command (`cmd`);
    the plugin check scripts (ac-format, ac-coverage, verify-gate) do not verify code.
  - "a review step exists" = some role step with `checks` (§4).
  - the `test-change-review` check goes to ONE review step: the first review step of role
    `tester`, else the first review step. It is recorded in state `steps[].added_checks`
    (the procedure's `checks` stay as the template wrote them — not a structure change,
    no new revision); the brief lists template + added checks, and `rule_checks` = added.
  - a missing gate is inserted from GATE_CATALOG right before the `check: done-gate` step
    (stage 2, D19) or else the `op: create-pr` step,
    only when its role is available (role file at the base SHA AND a session budget —
    the driver computes that set). Otherwise → unfillable. Stage 1 has no conditional
    specialists (I2), so in practice a risk-area change without the gate step in the
    template stops for a human.
  - evaluate is idempotent: a check already present (template or added) is not added again
    and does not reset the review; a gate already in the procedure is not inserted again.

Stage 3 (`evaluate(…, stage=3)`, E5 · E14 · E15 · E25 — stages 1–2 keep everything above):
  - a gate is a `diff-review` entry of the plugin step catalog (GATE_CATALOG is stages 1–2);
  - its place is catalog.position with `current` = the last step in front of the done-gate that
    has been started (`Supplement.insert_at`); its developer step is catalog.developer_step (E5,
    D4: catalog-added steps left out);
  - apply records the gate in `state.catalog_adds` (source mandatory-rule): it counts against
    CATALOG_ADDS_MAX but is never blocked by it;
  - a gate that is already there because a role or the leader added it becomes a mandatory one
    (`Supplement.pin` → its catalog_adds source), and a skipped one goes back to pending: no
    `skip` answer lifts a mandatory rule (E13, §7);
  - only review steps of the template itself count as "a review step" and carry the
    test-change-review check: a catalog-added review may be skipped by the leader (E13), and
    a mandatory rule must not go with it.
"""

import copy

from . import catalog as catmod, codes, defaults, globs, procedure as procmod, statemachine

TEST_CHANGE_REVIEW = codes.RequiredCheck.TEST_CHANGE_REVIEW.value

# Plugin-fixed gate step definitions (§7: "플러그인이 고정한 관문 단계 정의"). `{issue}` is the
# Issue number; `on_fail.back_to` is filled with the developer step at insertion time.
GATE_CATALOG = {
    "security-review": {
        "role": "security",
        "inputs": ["in:review.diff", "docs/specs/{issue}/analysis.md", "in:leader-decision.md"],
        "outputs": [],
        "checks": ["security-review"],
        "max": 2,
    },
}


class Supplement:
    """What the rules require now: `add_checks` {review step id: [check ids]},
    `insert_steps` [step dicts], `reset` [step ids], `unfillable` [reasons], `changed_verification` [paths].
    Stage 3: `insert_at` = the index of each insert_steps item in the current list (None before),
    `pin` = catalog steps the rules require from now on."""

    def __init__(self, add_checks, insert_steps, reset, unfillable, changed_verification, insert_at=None, pin=None):
        self.add_checks = {k: list(v) for k, v in (add_checks or {}).items()}
        self.insert_steps = [copy.deepcopy(s) for s in (insert_steps or ())]
        self.reset = list(reset or ())
        self.unfillable = list(unfillable or ())
        self.changed_verification = sorted(set(changed_verification or ()))
        self.insert_at = None if insert_at is None else list(insert_at)
        self.pin = list(pin or ())

    @property
    def changes_anything(self):
        """True when applying it changes the procedure or the state."""
        return bool(self.add_checks or self.insert_steps or self.reset or self.pin)

    def to_json(self):
        out = {"add_checks": self.add_checks, "insert_steps": self.insert_steps,
               "reset": self.reset, "unfillable": self.unfillable,
               "changed_verification": self.changed_verification}
        if self.insert_at is not None:
            out["insert_at"] = self.insert_at
            out["pin"] = self.pin
        return out

    def __repr__(self):
        return f"Supplement({self.to_json()!r})"


def _specs_prefix(issue):
    return defaults.SPECS_DIR.replace("{issue}", str(issue)) + "/"


def is_code_path(path, issue):
    """True for a changed path that counts as code (not docs/specs/<N>/ judgment documents)."""
    if not isinstance(path, str) or not path:
        raise ValueError(f"bad path {path!r}")
    return not path.startswith(_specs_prefix(issue))


def _command_entry(config, name):
    try:
        return config.command(name)
    except KeyError:
        return None


def _has_verification(proc, config):
    for s in proc.steps:
        if s.kind != codes.StepKind.RUN.value:
            continue
        entry = _command_entry(config, s.name)
        if entry is not None and entry.get("cmd"):
            return True
    return False


def _review_steps(proc):
    return [s for s in proc.steps if s.is_review]


def _aligned(state, procedure):
    ids = [s["id"] for s in state["steps"]]
    if ids != procedure.step_ids or state.get("revision") != procedure.revision:
        raise statemachine.StateError("state.json and the procedure disagree (steps or revision)")


def _state_step(state, step_id):
    for s in state["steps"]:
        if s["id"] == step_id:
            return s
    raise statemachine.StateError(f"step {step_id!r} is not in state.json")


def step_checks(proc_step, state_step):
    """(all checks, rule-added checks) of a review step — what its brief must list."""
    added = list((state_step or {}).get("added_checks") or ())
    allc = list(proc_step.checks)
    allc += [c for c in added if c not in allc]
    return allc, added


def _developer_step(proc):
    for s in proc.steps:
        if s.kind == codes.StepKind.ROLE.value and s.role_class == codes.RoleClass.WORK.value:
            return s.id
    return None


def added_steps(state):
    """Ids the catalog put into this procedure (`state.catalog_adds`, stage 3)."""
    return [a["step"] for a in state.get("catalog_adds") or ()]


def _frontier(procedure, state):
    """The last step in front of the done-gate (create-pr / end) that has been started — the
    `current` of a gate insertion; the first step when nothing has."""
    waiting = (codes.StepStatus.PENDING.value, codes.StepStatus.READY.value)
    found = procedure.steps[0].id
    for s in procedure.steps[:catmod.gate_index(procedure)]:
        if _state_step(state, s.id)["status"] not in waiting:
            found = s.id
    return found


def _catalog_gate(procedure, state, entry, issue):
    """(raw step, index) of a stage-3 gate, or None when it has no developer step / no place."""
    added = added_steps(state)
    dev = catmod.developer_step(procedure, added)
    if dev is None:
        return None
    statuses = {s["id"]: s["status"] for s in state["steps"]}
    at = catmod.position(procedure, statuses, _frontier(procedure, state), entry, added)
    return None if at is None else (catmod.expand(entry, issue, dev), at)


def _gate_step(gate, issue, back_to):
    d = GATE_CATALOG[gate]
    sub = lambda p: p.replace("{issue}", str(issue))  # noqa: E731
    return {"id": gate, "role": d["role"], "inputs": [sub(p) for p in d["inputs"]],
            "outputs": [sub(p) for p in d["outputs"]], "on_fail": {"back_to": back_to, "max": d["max"]},
            "checks": list(d["checks"])}


def evaluate(procedure, state, config, changed_paths, issue, roles_available=None, stage=2, catalog=None):
    """Return the Supplement for the actual changed paths (pure).

    `config` is a repoconfig.RepoConfig; `roles_available` the role names a gate step may
    use (None = none). Paths are worktree-relative. Stage ≥ 3 takes the gates from `catalog`
    ({id: catalog.Entry}; None = the plugin catalog, read by catalog.load).
    """
    codes.check_stage(stage)
    _aligned(state, procedure)
    changed = sorted({p for p in changed_paths})
    for p in changed:
        is_code_path(p, issue)     # validates
    code = [p for p in changed if is_code_path(p, issue)]
    verification = [p for p in changed if config.matches(codes.PathRuleKind.VERIFICATION.value, p)]
    add_checks, insert, reset, unfillable = {}, [], [], []
    insert_at = [] if stage >= 3 else None
    pin = []
    if not code:
        return Supplement({}, [], [], [], verification)

    if not _has_verification(procedure, config):
        unfillable.append("code changed but the procedure has no verification run step "
                          "(a run of a repository command)")
    reviews = _review_steps(procedure)
    if stage >= 3:
        own = set(added_steps(state))
        reviews = [s for s in reviews if s.id not in own]
    if not reviews:
        unfillable.append("code changed but the procedure has no review step")

    # risk areas → their gate steps
    roles = set(roles_available or ())
    have = set(procedure.step_ids)
    wanted = []
    for rule in config.path_rules(codes.PathRuleKind.RISK.value):
        if any(globs.match_any(rule["globs"], p) is not None for p in code):
            if rule["gate"] not in [g for g, _ in wanted]:
                wanted.append((rule["gate"], rule["area"]))
    if stage >= 3 and wanted and catalog is None:
        catalog = catmod.load()
    seen = set()
    for gate, area in wanted:
        if gate in seen:
            continue
        seen.add(gate)
        if gate in have:
            if stage >= 3:
                sources = {a["source"] for a in state.get("catalog_adds") or () if a["step"] == gate}
                if sources - {codes.ProcedureSource.MANDATORY_RULE.value}:
                    pin.append(gate)
                if _state_step(state, gate)["status"] == codes.StepStatus.SKIPPED.value:
                    reset.append(gate)
            continue
        entry = None
        if stage >= 3:
            entry = catalog.get(gate)
            if entry is not None and entry.cls == codes.CatalogClass.DIFF_REVIEW.value:
                role = entry.role
            else:
                role = None
        else:
            role = GATE_CATALOG[gate]["role"] if gate in GATE_CATALOG else None
        if role is None:
            unfillable.append(f"risk area {area!r}: gate {gate!r} is not a plugin gate definition")
            continue
        if role not in roles:
            unfillable.append(f"risk area {area!r}: gate {gate!r} needs role {role!r}, which this "
                              "repository cannot run (no role file at the base SHA or no session budget)")
            continue
        if stage >= 3:
            placed = _catalog_gate(procedure, state, entry, issue)
        else:
            dev = _developer_step(procedure)
            placed = None if dev is None else (_gate_step(gate, issue, dev), None)
        if placed is None:
            unfillable.append(f"risk area {area!r}: gate {gate!r} has no developer step to go back to")
            continue
        insert.append(placed[0])
        if stage >= 3:
            insert_at.append(placed[1])

    # verification paths → test-change-review on one review step
    if verification and reviews:
        testers = [s for s in reviews if s.name == "tester"]
        target = (testers or reviews)[0]
        allc, _ = step_checks(target, _state_step(state, target.id))
        if TEST_CHANGE_REVIEW not in allc:
            add_checks[target.id] = [TEST_CHANGE_REVIEW]
            if _state_step(state, target.id)["status"] == codes.StepStatus.DONE.value:
                reset.append(target.id)
    return Supplement(add_checks, insert, reset, unfillable, verification, insert_at, pin)


def _insert_position(proc):
    """Index before the `check: done-gate` step (stage 2, §7 "done-gate 앞에 넣는다" — D19),
    else before the op: create-pr step, else the end."""
    for kind, name in ((codes.StepKind.CHECK.value, codes.CheckKind.DONE_GATE.value),
                       (codes.StepKind.OP.value, codes.OpKind.CREATE_PR.value)):
        for i, s in enumerate(proc.steps):
            if s.kind == kind and s.name == name:
                return i
    return len(proc.steps)


def apply(procedure, state, supplement, commands=None, stage=1):
    """Apply a Supplement: new procedure (revision + 1 if steps inserted), state resets, log events.

    Returns (procedure, events). `state` is changed in place (added_checks, reset steps,
    inserted step entries, revision). An unfillable supplement is refused (ValueError) — the
    driver stops with RULE_UNFILLABLE instead. A new procedure is checked with `commands`
    (procedure.check); the driver commits it and records the commit. Stage ≥ 3 also records
    each inserted gate in `state.catalog_adds` (source mandatory-rule).
    """
    if supplement.unfillable:
        raise ValueError("an unfillable supplement cannot be applied: " + "; ".join(supplement.unfillable))
    _aligned(state, procedure)
    events = []
    data = supplement.to_json()
    data.pop("unfillable")
    new_proc = procedure
    if supplement.insert_steps:
        at = supplement.insert_at
        if at is None:
            at = [_insert_position(procedure)] * len(supplement.insert_steps)
        # from the back, so that every index stays an index of the current list; gates with the
        # same index keep their order
        placed = sorted(zip(at, range(len(at)), supplement.insert_steps), key=lambda x: x[:2], reverse=True)
        steps = [s.to_json() for s in procedure.steps]
        for pos, _, raw in placed:
            steps.insert(pos, copy.deepcopy(raw))
        new_proc = procmod.with_revision(procedure, steps)
        errs = procmod.check(new_proc, commands, stage=stage)
        if errs:
            raise procmod.ProcedureError(errs)
        for pos, _, raw in placed:
            statemachine.insert_steps(state, pos, [raw["id"]], new_proc.revision)
        if stage >= 3:
            adds = state.setdefault("catalog_adds", [])
            have = {a["step"] for a in adds}
            adds += [{"step": raw["id"], "source": codes.ProcedureSource.MANDATORY_RULE.value, "from_step": None,
                      "revision": new_proc.revision} for raw in supplement.insert_steps if raw["id"] not in have]
    for step_id, ids in supplement.add_checks.items():
        s = _state_step(state, step_id)
        cur = list(s.get("added_checks") or ())
        for c in ids:
            if c not in cur:
                cur.append(c)
        s["added_checks"] = cur
    for step_id in supplement.reset:
        s = _state_step(state, step_id)
        if s["status"] != codes.StepStatus.PENDING.value:
            frm = s["status"]
            s["status"] = codes.StepStatus.PENDING.value
            s["output_format_retries"] = 0
            note = "mandatory rule added a check"
            if frm == codes.StepStatus.SKIPPED.value:
                s["reason"] = None
                note = "mandatory rule: the gate may not be skipped"
            events.append((codes.LogEvent.STATUS.value,
                           {"step": step_id, "attempt": s.get("latest_attempt"), "from": frm,
                            "to": s["status"], "note": note}))
    for a in state.get("catalog_adds") or ():
        if a["step"] in supplement.pin:
            a["source"] = codes.ProcedureSource.MANDATORY_RULE.value
    events.insert(0, (codes.LogEvent.RULE_SUPPLEMENT.value,
                      {"data": dict(data, revision=new_proc.revision)}))
    return new_proc, events
