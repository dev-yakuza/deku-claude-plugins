"""The plugin step catalog: the only steps that may be added to a running procedure (stage 3 — E14, E15, E5, D4, D6).

Fixed by the stage-3 contract change (V1, Q2); bodies by session B1 (V2 · V6). Signatures and
the rules in these docstrings are the contract between B1 and B2 / D — change them only
through README "Changing a contract". Every function is pure: no git, no clock, no write
(`load` reads the plugin data files).

Layer L1. It imports only L0 modules; `procedure` (L1) may import it (test_contracts.SAME_LAYER).
Procedure arguments are duck-typed (`.steps`, `.issue`, `.revision`; a step has `.id`, `.kind`,
`.name`, `.inputs`, `.outputs`, `.checks`, `.is_review`, `.role_class`, `.to_json()`).

`data/catalog.json` (session A; schemas/catalog) is plugin-fixed: neither the repository
settings nor evolve change it (§7, like the mandatory gates — rules.GATE_CATALOG moves here).

Terms
  added       ids of the steps the catalog put into this procedure (`state.catalog_adds[].step`).
  statuses    {step id: codes.StepStatus value} of the current state.
  current     id of the step that has just become done (for a plan answer: the plan step).
"""

import copy
import json
import os

from . import codes, defaults, globs, schema

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
CATALOG_FILE = os.path.join(DATA_DIR, "catalog.json")
START_FILE = os.path.join(DATA_DIR, "start.json")     # the plugin start procedure: its step ids are taken
RESERVED_IDS = ("leader",)                            # the leader calls' temp folders (stage 2, D13)

NOT_REQUESTABLE_CLASSES = (codes.CatalogClass.FIX.value,)
"""Classes left out of the request / adjust enums (fix-discovery comes only from E18)."""

ROLE = codes.StepKind.ROLE.value
WORK = codes.RoleClass.WORK.value


class CatalogError(Exception):
    """The catalog file or an entry breaks its contract. `.errors` lists the reasons."""

    def __init__(self, errors):
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


class Entry:
    """One catalog entry: id, role, cls (codes.CatalogClass value), inputs, outputs, checks,
    on_fail ({"back_to", "max"} or None), summary. `{issue}` / `@developer` are not filled."""

    def __init__(self, raw):
        self.id = raw["id"]
        self.role = raw["role"]
        self.cls = raw["class"]
        self.inputs = list(raw["inputs"])
        self.outputs = list(raw["outputs"])
        self.checks = list(raw["checks"])
        self.on_fail = dict(raw["on_fail"]) if raw["on_fail"] is not None else None
        self.summary = raw["summary"]

    def __repr__(self):
        return f"Entry({self.id!r}, {self.cls}, role={self.role!r})"


class Decision:
    """The end of one request (E15): `request` (the dict passed in), `outcome`
    (codes.RequestOutcome value), `reason` (codes.RequestReason value or None)."""

    def __init__(self, request, outcome, reason=None):
        if outcome not in codes.RequestOutcome.values():
            raise ValueError(f"unknown request outcome {outcome!r}")
        if reason is not None and reason not in codes.RequestReason.values():
            raise ValueError(f"unknown request reason {reason!r}")
        self.request = request
        self.outcome = outcome
        self.reason = reason

    def __repr__(self):
        return f"Decision({self.outcome!r}, {self.reason!r})"


# --- the file ---------------------------------------------------------------------

def load(path=CATALOG_FILE):
    """Read and check the plugin catalog file → {id: Entry} in file order.

    schemas/catalog plus: unique ids; a `design-time` entry has outputs, no checks and no
    on_fail; a `diff-review` entry has checks, no outputs and on_fail back_to `@developer`; a
    `fix` entry is a work role without outputs; no output is a control file; no id is
    `leader` or a start-procedure step id. CatalogError otherwise (an engine bug)."""
    raw = _read_json(path)
    errs = schema.errors(raw, schema.load_schema("catalog"))
    if errs:
        raise CatalogError([f"schema catalog: {e}" for e in errs])
    taken = set(RESERVED_IDS) | _start_ids()
    out = {}
    for item in raw["entries"]:
        e = Entry(item)
        if e.id in out:
            errs.append(f"entry {e.id!r}: duplicate id")
        if e.id in taken:
            errs.append(f"entry {e.id!r}: the id is taken (leader or a start-procedure step)")
        errs += [f"entry {e.id!r}: {x}" for x in _entry_errors(e)]
        out[e.id] = e
    if errs:
        raise CatalogError(errs)
    return out


def _no_dupes(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise ValueError(f"duplicate key {k!r}")
        out[k] = v
    return out


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.loads(f.read(), object_pairs_hook=_no_dupes)
    except (OSError, ValueError, RecursionError) as e:
        raise CatalogError([f"{path}: {e}"]) from None


def _start_ids():
    raw = _read_json(START_FILE)
    try:
        return {s["id"] for s in raw["steps"]}
    except (TypeError, KeyError):
        raise CatalogError([f"{START_FILE}: not a start procedure"]) from None


def _entry_errors(e):
    C = codes.CatalogClass
    errs = []
    if e.cls == C.DESIGN_TIME.value:
        if not e.outputs:
            errs.append("a design-time entry has outputs")
        if e.checks:
            errs.append("a design-time entry has no checks")
        if e.on_fail is not None:
            errs.append("a design-time entry has no on_fail (its failure is needs_leader)")
    elif e.cls == C.DIFF_REVIEW.value:
        if not e.checks:
            errs.append("a diff-review entry has checks")
        if e.outputs:
            errs.append("a diff-review entry has no outputs")
        if e.on_fail is None:
            errs.append(f"a diff-review entry goes back to {codes.CATALOG_DEVELOPER_TOKEN}")
    else:
        if codes.role_class(e.role) != WORK:
            errs.append("a fix entry is a work role")
        if e.outputs or e.checks:
            errs.append("a fix entry has no outputs and no checks")
    for o in e.outputs:
        try:
            if globs.names_control_file(_subst(o, 1), 1):
                errs.append(f"output {o!r} is a control file (§7.6)")
        except ValueError as x:
            errs.append(f"output {o!r}: {x}")
    for p in e.inputs + e.outputs:
        rest = _subst(p, 1)
        if "{" in rest or "}" in rest:
            errs.append(f"placeholder in {p!r} (only the issue number)")
    return errs


def _subst(value, issue):
    return value.replace("{issue}", str(issue))


def requestable_ids(catalog):
    """Ids a role may request and a plan may add, in file order (NOT_REQUESTABLE_CLASSES left
    out) — the `{catalog_steps}` fill of the result schemas (codes.RESULT_SCHEMA_TOKENS)."""
    return [e.id for e in catalog.values() if e.cls not in NOT_REQUESTABLE_CLASSES]


def usable_ids(catalog, roles_available):
    """requestable_ids whose role is in `roles_available` (driver.roles_available: role file at
    the base SHA + session budget + layer-1 default) — `{catalog_steps}` of the plan-gate answer."""
    roles = set(roles_available or ())
    return [i for i in requestable_ids(catalog) if catalog[i].role in roles]


# --- positions --------------------------------------------------------------------

def developer_step(procedure, added=()):
    """E5 + D4: the id of the last work-role step before the first review step (a role step
    with checks), not counting steps in `added`; None when there is none. A procedure without
    a review step: its last such work step."""
    skip = set(added or ())
    found = None
    for s in procedure.steps[:first_review_index(procedure, added)]:
        if s.kind == ROLE and s.role_class == WORK and s.id not in skip:
            found = s.id
    return found


def first_review_index(procedure, added=()):
    """Index of the first review step not in `added`, or None."""
    skip = set(added or ())
    for i, s in enumerate(procedure.steps):
        if s.is_review and s.id not in skip:
            return i
    return None


def gate_index(procedure):
    """Index every inserted step stays in front of: `check: done-gate`, else `op: create-pr`,
    else the end of the procedure (§7, D19)."""
    for kind, name in ((codes.StepKind.CHECK.value, codes.CheckKind.DONE_GATE.value),
                       (codes.StepKind.OP.value, codes.OpKind.CREATE_PR.value)):
        for i, s in enumerate(procedure.steps):
            if s.kind == kind and s.name == name:
                return i
    return len(procedure.steps)


def _index(procedure, step_id):
    for i, s in enumerate(procedure.steps):
        if s.id == step_id:
            return i
    raise ValueError(f"step {step_id!r} is not in the procedure")


def position(procedure, statuses, current, entry, added=()):
    """E15 + D6: the index at which `entry`'s step goes, or None (→ declined(position)).

      design-time  right after `current`; only when the developer step is after `current` and
                   not done;
      diff-review  the later of "right after `current`" and "right before the first review";
      fix          right after `current`.
    Always after `current` and before `check: done-gate` (no done-gate: before create-pr).
    An entry with on_fail also needs the developer step in front of it (E5): no such step →
    None; a procedure without a review step puts a diff-review after the developer step."""
    cur = _index(procedure, current)
    dev_id = developer_step(procedure, added)
    dev = None if dev_id is None else _index(procedure, dev_id)
    C = codes.CatalogClass
    pos = cur + 1
    if entry.cls == C.DESIGN_TIME.value:
        if dev is None or dev <= cur or statuses.get(dev_id) == codes.StepStatus.DONE.value:
            return None
    elif entry.cls == C.DIFF_REVIEW.value:
        review = first_review_index(procedure, added)
        if review is not None:
            pos = max(pos, review)
        elif dev is not None:
            pos = max(pos, dev + 1)
    elif entry.cls != C.FIX.value:
        raise ValueError(f"unknown catalog class {entry.cls!r}")
    if entry.on_fail is not None and (dev is None or dev >= pos):
        return None
    return pos if pos <= gate_index(procedure) else None


def expand(entry, issue, developer):
    """The raw procedure step (dict) of `entry`: id = entry id, `{issue}` substituted,
    `@developer` = `developer` (an id; None with such an on_fail → CatalogError)."""
    raw = {"id": entry.id, "role": entry.role,
           "inputs": [_subst(p, issue) for p in entry.inputs],
           "outputs": [_subst(p, issue) for p in entry.outputs]}
    if entry.on_fail is not None:
        back_to = entry.on_fail["back_to"]
        if back_to == codes.CATALOG_DEVELOPER_TOKEN:
            if not developer:
                raise CatalogError([f"entry {entry.id!r}: no developer step for {back_to}"])
            back_to = developer
        raw["on_fail"] = {"back_to": back_to, "max": entry.on_fail["max"]}
    if entry.checks:
        raw["checks"] = list(entry.checks)
    return raw


def insert(procedure, entry_steps, added=()):
    """New raw step list with `entry_steps` = [(index, raw step, Entry)] inserted (indices of
    the CURRENT list) and the outputs of each design-time entry appended to the inputs of every
    later role step (E15 input propagation; an input already there is not repeated).

    Steps with the same index keep their order in `entry_steps`."""
    n = len(procedure.steps)
    at = {}
    for index, raw, entry in entry_steps:
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index <= n:
            raise ValueError(f"bad insert position {index!r}")
        at.setdefault(index, []).append((copy.deepcopy(raw), entry))
    out = []                                 # [(raw step, its Entry or None)]
    for i in range(n + 1):
        out += at.get(i, [])
        if i < n:
            out.append((procedure.steps[i].to_json(), None))
    for k, (raw, entry) in enumerate(out):
        if entry is None or entry.cls != codes.CatalogClass.DESIGN_TIME.value:
            continue
        for later, _ in out[k + 1:]:
            if ROLE not in later:
                continue
            have = list(later.get("inputs") or ())
            later["inputs"] = have + [o for o in raw["outputs"] if o not in have]
    return [raw for raw, _ in out]


# --- requests ---------------------------------------------------------------------

def evaluate_requests(catalog, procedure, statuses, current, requests, *, roles_available, adds_used,
                      added=(), start_steps=(), limit=defaults.CATALOG_ADDS_MAX):
    """E15: decide every `requests` item ({"op", "step", "trigger", "note", …}) of one finished role step.

    Returns (decisions, steps): `decisions` = [Decision] in request order, `steps` = the new raw
    step list, or None when nothing is applied. Order per `add`: current in `start_steps` →
    deferred-to-plan · role → declined(role-unavailable) · same id in the procedure (or applied
    earlier in this call) → noop(already-present) · position → declined(position) · adds_used +
    applied so far ≥ limit → pending(limit) · else applied. `remove` / `skip` → pending(removal).
    The caller bumps the revision once for `steps`, runs procedure.check and the mandatory
    rules; when check refuses, it turns every applied into declined(grammar) and drops `steps`.
    An `add` outside requestable_ids (the rendered schema refuses it before) → declined(grammar)."""
    O, R = codes.RequestOutcome, codes.RequestReason
    op = codes.RequestOp
    roles, starts = set(roles_available or ()), set(start_steps or ())
    allowed = set(requestable_ids(catalog))
    have = {s.id for s in procedure.steps}
    dev = developer_step(procedure, added)
    decisions, entries = [], []
    for req in requests:
        if req["op"] in (op.REMOVE.value, op.SKIP.value):
            decisions.append(Decision(req, O.PENDING.value, R.REMOVAL.value))
            continue
        if req["op"] != op.ADD.value:
            raise ValueError(f"unknown request op {req['op']!r}")
        sid = req["step"]
        if sid not in allowed:
            decisions.append(Decision(req, O.DECLINED.value, R.GRAMMAR.value))
            continue
        entry = catalog[sid]
        at = None
        if current in starts:
            d = Decision(req, O.DEFERRED_TO_PLAN.value)
        elif entry.role not in roles:
            d = Decision(req, O.DECLINED.value, R.ROLE_UNAVAILABLE.value)
        elif sid in have:
            d = Decision(req, O.NOOP.value, R.ALREADY_PRESENT.value)
        else:
            at = position(procedure, statuses, current, entry, added)
            if at is None:
                d = Decision(req, O.DECLINED.value, R.POSITION.value)
            elif adds_used + len(entries) >= limit:
                d = Decision(req, O.PENDING.value, R.LIMIT.value)
            else:
                d = Decision(req, O.APPLIED.value)
                entries.append((at, expand(entry, procedure.issue, dev), entry))
                have.add(sid)
        decisions.append(d)
    return decisions, (insert(procedure, entries, added) if entries else None)


def skippable_steps(procedure, statuses, catalog_adds, requests):
    """E13 `{skippable_steps}`: ids that `requests` (the pending remove / skip items) name, that
    the catalog added (`state.catalog_adds`, source not mandatory-rule) and that are not done,
    in procedure order. An already skipped step is left out too, and a step any catalog_adds
    entry of which is a mandatory gate (§7: not even the leader lifts it)."""
    gone = (codes.StepStatus.DONE.value, codes.StepStatus.SKIPPED.value)
    named = {r["step"] for r in requests if r["op"] in (codes.RequestOp.REMOVE.value, codes.RequestOp.SKIP.value)}
    fixed = {a["step"] for a in catalog_adds if a["source"] == codes.ProcedureSource.MANDATORY_RULE.value}
    ours = {a["step"] for a in catalog_adds} - fixed
    return [s.id for s in procedure.steps if s.id in named & ours and statuses.get(s.id) not in gone]
