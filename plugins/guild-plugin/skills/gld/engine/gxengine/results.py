"""Judge an attempt: result JSON + facts → statemachine.Outcome (design §6.2 engine table, §7.6, §7.12 S3, I3 I5) — U8.

Order (the first hit decides):
  1. security boundary — control files differ from base (cumulative; procedure.yaml vs the
     engine's last commit), a judge role changed paths outside its outputs →
     Outcome stop (discard the result, needs_human, never on_fail, never revert).
  2. role result missing / not schema-valid / no structured output → output-format.
  3. status blocked → stop BLOCKED without looking at verdict (I5-3).
  4. outputs missing or not regular files → output-format.
  5. review: empty `reviewed`, a required check id missing, reviewed ⊉ actual changed files
     (outside docs/specs/<N>/, I5-1), pass with a blocker finding, a rule-added check n/a
     → output-format.
  6. review: a required check `fail` (I5-2) or verdict block → check-failed (block wins
     across reviews, §6.3), back_to = the owner step of the findings' files (I3).
  7. foreign-output (an output differs from its owner step's last engine commit,
     cumulative) / developer dirty tree at the end → check-failed.
  8. otherwise done; judge outputs are committed by the engine (gitops.commit_paths) and
     read back as blobs.
`requests` are recorded only (stages 0–2, §6; from stage 3 the driver evaluates them after a
done step — catalog.evaluate_requests); `discoveries` are kept for the PR body.

U8 decisions (fail-closed; see the P3-A report):

  * Between 1 and 2 the session end is applied: budget → session-limit; wall clock /
    no output → infra (wall-clock / no-output); a rejected rate limit → infra quota with
    `reset_at`; any other error end → infra api. The security checks still come first.
  * A boundary fact that is missing (None) on a role / run attempt → infra
    fact-collection (no judgment without the fact, §9.3).
  * Control files, cumulative (S3): every control path (globs.is_control_file — case folded)
    of the base tree, the HEAD tree, the index and the worktree FILE SYSTEM (walked, so
    gitignored and untracked control files count — C3) is compared with its reference:
    the base blob, or for procedure.yaml the engine's last commit (`procedure_commit`; none
    yet → base). Mode and content must be equal; a path missing on one side is a change.
    The reference is always a git blob, never a worktree copy (C8).
  * Ownership, cumulative: for every other step with outputs, each path matching them
    (case folded) in the base tree, the HEAD tree, the worktree files, or the owner's
    recorded outputs is compared (HEAD and worktree) with the owner reference: the blob the
    owner's latest DONE attempt recorded in facts.outputs, else the base. Paths the judged
    step declares itself are skipped (shared work outputs).
  * Judge write scope: the per-attempt change set (facts.attempt_changes) — exact,
    case-sensitive match against the step's outputs.
  * A request whose `step` is not a step-name token → output-format unknown-request-step
    (stage 1: name pattern only, open question 9).
  * I5-1 applies when one of the step's checks is a `covers_diff` check of
    instructions.CHECK_CATALOG; `reviewed` must hold every changed path (both rename sides)
    outside docs/specs/<N>/.
  * I3: the owners of the files of `blocker` findings (all findings when none is a blocker)
    that are THIS step or an earlier one; the earliest owner wins (back_to the earliest
    resets everything after it). No owner → the step's on_fail.
  * Stage 3 (review-q0 D2, K2): with `owned` (owned_files) a work step owns the files its
    attempts really changed, for the ownership check and for I3; its globs only bound them.
  * A run: control files first (C7), then the runner's outcome as is (P3-Z decision 1:
    base red → stop base-red, I8 · dirty tree / moved HEAD → run-dirty-tree · timeout →
    run-timeout · rc ≠ 0 → run-nonzero); no exit code and no timeout → infra op-failed.
  * Control files under a gitignored path that are control files only by their NAME
    (CLAUDE.md, CLAUDE.local.md, AGENTS.md — not inside `.claude/`, not procedure.yaml) are
    not compared (P3-Z decision 6b: dependencies unpacked by `run: setup`); "gitignored" =
    not in `git ls-files -co --exclude-standard` (tracked files always count).
"""

import os
import re
import stat

from . import codes, defaults, facts as F, gitops, globs, instructions, schema, statemachine, store

Outcome = statemachine.Outcome
_NAME_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
_LINK_MODE = "120000"


# --- result JSON ----------------------------------------------------------------------

def result_schema(result_kind, stage=2, catalog_steps=()):
    """The `--json-schema` value of a role session (render.RenderInput.json_schema).

    Stages 1–2: the schema name. From stage 3 (E16): the enum template filled with
    `catalog_steps` (catalog.requestable_ids) — a name outside the catalog or a command string
    cannot be a valid request. No catalog step at all → the `requests` property is left out
    (schema.fill_enums; the engine reads a missing array as [])."""
    if result_kind not in codes.ResultKind.values():
        raise ValueError(f"bad result kind {result_kind!r}")
    name = codes.result_schemas(stage)[str(getattr(result_kind, "value", result_kind))]
    if stage < 3:
        return name
    return schema.fill_enums(schema.load_schema(name), {t: list(catalog_steps) for t in codes.RESULT_SCHEMA_TOKENS})


def validate_result(result, result_kind, stage=2, catalog_steps=()):
    """List of schema errors of a role result against the result schema of the stage.

    A lone surrogate is refused first, at every stage (review-q0 D9): such a string cannot be
    written as UTF-8 anywhere (state, PR body, inputs of later steps)."""
    if result_kind not in codes.ResultKind.values():
        raise ValueError(f"bad result kind {result_kind!r}")
    if not isinstance(result, dict):
        return ["result: not a JSON object"]
    errs = schema.surrogate_errors(result)
    if errs:
        return errs
    sch = result_schema(result_kind, stage, catalog_steps)
    errs = list(schema.errors(result, schema.load_schema(sch) if isinstance(sch, str) else sch))
    if errs:
        return errs
    if result["status"] == codes.ResultStatus.BLOCKED.value and result["blocked_by"] is None:
        errs.append("blocked_by: required (not null) when status is blocked")
    if result["status"] == codes.ResultStatus.DONE.value and result["blocked_by"] is not None:
        errs.append("blocked_by: must be null when status is done")
    return errs


def _request_errors(result):
    out = []
    for i, r in enumerate(result.get("requests") or []):
        s = r.get("step")
        if not isinstance(s, str) or len(s) > 64 or not _NAME_RE.match(s):
            out.append(f"requests[{i}].step {s!r} is not a step name (never a command string)")
    return out


# --- git helpers ----------------------------------------------------------------------

def _tree(ctx, sha):
    return F._tree_entries(ctx, sha)


def _index(ctx):
    """{path: (mode, sha)} of the index (stage 0; conflicted entries → a marker)."""
    raw = gitops.git(ctx, "ls-files", "-s", "-z")
    out = {}
    for e in raw.split("\0"):
        if not e:
            continue
        meta, _, name = e.partition("\t")
        mode, obj, stage_no = meta.split()
        out[name] = (mode, obj) if stage_no == "0" else ("conflict", obj)
    return out


_hash_algo = F.hash_algo
_disk_entry = F.disk_entry


def _is_control(path, issue):
    """A control file, or an entry NAMED like a control folder that is not a real directory
    (a `pkg/.claude` symlink or file — `**/.claude/**` alone would not match it)."""
    return globs.is_control_file(path, issue) or path.rsplit("/", 1)[-1].lower() in globs.CONTROL_FOLDERS


def _walk_control(ctx, issue):
    """Worktree-relative paths of every control entry on disk (ignored and untracked too).
    Real directories are descended, links never followed."""
    found = []
    stack = [(ctx.work_tree, "")]
    while stack:
        d, rel = stack.pop()
        try:
            entries = list(os.scandir(d))
        except (FileNotFoundError, NotADirectoryError):
            continue
        for e in entries:
            r = e.name if not rel else rel + "/" + e.name
            if not rel and e.name == ".git":
                continue          # the worktree's gitfile (git's own, render-protected)
            try:
                is_dir = e.is_dir(follow_symlinks=False)
            except OSError:
                is_dir = False
            if is_dir:
                stack.append((e.path, r))
            elif _is_control(r, issue):
                found.append(r)
    return sorted(found)


def _git_fact(fact, fn, *args):
    try:
        return fn(*args)
    except gitops.UnsafePath:
        raise
    except (gitops.GitError, OSError, ValueError) as e:
        raise F.FactMissing(fact, str(e)[:500]) from e


# --- boundary facts --------------------------------------------------------------------

def check_control_files(ctx, procedure_commit, issue, head_sha):
    """facts.json `control_files`: cumulative HEAD-tree and worktree comparison with base (S3)."""
    return _git_fact("control_files", _control_files, ctx, procedure_commit, issue, head_sha)


def _control_files(ctx, procedure_commit, issue, head_sha):
    proc_path = defaults.CONTROL_FILE_GLOBS[-1].replace("{issue}", str(issue))
    if not proc_path.endswith("procedure.yaml"):
        raise ValueError("defaults.CONTROL_FILE_GLOBS no longer ends with procedure.yaml")
    algo = _hash_algo(ctx)
    base = _tree(ctx, ctx.base_sha)
    proc_ref_tree = _tree(ctx, procedure_commit) if procedure_commit else base

    def ref(path):
        if path.lower() == proc_path.lower():
            return proc_ref_tree.get(path)
        return base.get(path)

    head = _tree(ctx, head_sha)
    index = _index(ctx)
    ctl = lambda p: _is_control(p, issue)          # noqa: E731
    changed = set()
    ref_paths = {p for p in base if ctl(p)} | {p for p in proc_ref_tree if ctl(p) and p.lower() == proc_path.lower()}
    for p in ref_paths | {p for p in head if ctl(p)}:
        if head.get(p) != ref(p):
            changed.add(p)
    for p in ref_paths | {p for p in index if ctl(p)}:
        if index.get(p) != ref(p):
            changed.add(p)
    on_disk = _walk_control(ctx, issue)
    if any(_name_only(p, proc_path) for p in on_disk):
        visible = set(F.worktree_files(ctx))      # tracked + untracked non-ignored (P3-Z decision 6b)
        on_disk = [p for p in on_disk if not _name_only(p, proc_path) or p in visible]
    for p in ref_paths | set(on_disk):
        if _disk_entry(ctx, p, algo) != ref(p):
            changed.add(p)
    return {"ok": not changed, "changed": sorted(changed)}


def _name_only(path, proc_path):
    """A control file only by its NAME (CLAUDE.md / CLAUDE.local.md / AGENTS.md), not inside a
    control folder and not procedure.yaml. Such a file under a gitignored path is not compared
    (P3-Z decision 6b: `run: setup` may unpack them into node_modules); everything else is."""
    low = path.lower()
    parts = low.split("/")
    return (low != proc_path.lower() and parts[-1] in globs.CONTROL_NAMES
            and not any(seg in globs.CONTROL_FOLDERS for seg in parts))


def owner_facts(paths, state):
    """{step id: facts} of every step whose latest attempt's facts record outcome done —
    the ownership references (`check_ownership(owner_facts=…)`). Reads through store."""
    out = {}
    for s in state.get("steps") or []:
        a = s.get("latest_attempt")
        if not a:
            continue
        try:
            fx = store.read_facts(paths, s["id"], a)
        except FileNotFoundError:
            continue
        oc = fx.get("outcome") or {}
        if oc.get("status") == codes.StepStatus.DONE.value:
            out[s["id"]] = fx
    return out


def owned_files(paths, procedure):
    """Stage 3 (review-q0 D2, K2): {work step id: {path: blob after its last attempt, None = gone}}
    of every work-role step with outputs — the files it REALLY owns (facts.step_files `owned`),
    not everything its globs match. Pass it as `owned=` to add_boundary_facts and judge_role;
    facts.FactMissing when an attempt was recorded without `attempt_files`."""
    out = {}
    for p in procedure.steps:
        if p.role_class == codes.RoleClass.WORK.value and p.outputs:
            sf = F.step_files(paths, p.id, p.outputs)
            out[p.id] = {x: sf["net"][x][1] for x in sf["owned"]}
    return out


def owner_step(procedure, path, owned=None):
    """The step id that owns `path` (I3), or None. With `owned` (owned_files) a work step owns only
    its own files; every other step — and every step without `owned` — owns by its globs."""
    for p in procedure.steps:
        if owned is not None and p.id in owned:
            if path in owned[p.id]:
                return p.id
        elif p.outputs and globs.match_any(p.outputs, path) is not None:
            return p.id
    return None


def check_ownership(ctx, procedure, state, step, owner_facts=None, head_sha=None, owned=None):
    """facts.json `ownership`: outputs of other steps that differ from their owner's last engine commit.

    `owner_facts` = {step id: facts of its latest done attempt} (results.owner_facts);
    `head_sha` defaults to the worktree HEAD. Paths are matched case-folded. `owned`
    (owned_files, stage 3): the steps in it own exactly those files, at exactly those blobs."""
    return _git_fact("ownership", _ownership, ctx, procedure, state, step, owner_facts or {}, head_sha, owned)


def _ownership(ctx, procedure, state, step, owner_facts, head_sha, owned=None):
    cur = procedure.step(step) if isinstance(step, str) else step
    head_sha = head_sha or gitops.head(ctx)
    algo = _hash_algo(ctx)
    base = _tree(ctx, ctx.base_sha)
    head = _tree(ctx, head_sha)
    disk = F.worktree_files(ctx)
    universe = set(base) | set(head) | set(disk)
    foreign = {}
    for other in procedure.steps:
        if other.id == cur.id or not other.outputs:
            continue
        recorded = {}
        if owned is not None and other.id in owned:
            recorded = dict(owned[other.id])         # its own files only (D2); None = must stay gone
            cands = set(recorded)
        else:
            for o in (owner_facts.get(other.id) or {}).get("outputs") or []:
                if o.get("exists") and o.get("blob"):
                    recorded[o["path"]] = o["blob"]
            cands = {p for p in universe if globs.match_any(other.outputs, p, fold=True)}
            cands |= {p for p in recorded}
        for p in sorted(cands):
            if cur.outputs and globs.match_any(cur.outputs, p, fold=True):
                continue
            if p in recorded:
                want = recorded[p]
            else:
                b = base.get(p)
                want = b[1] if b else None
            h = head.get(p)
            d = _disk_entry(ctx, p, algo)
            if (h[1] if h else None) != want or (d[1] if d else None) != want or \
                    (d is not None and d[0] in ("other", _LINK_MODE)) or (h is not None and h[0] == _LINK_MODE):
                foreign.setdefault(p, other.id)
    items = [{"path": p, "owner_step": o} for p, o in sorted(foreign.items())]
    return {"ok": not items, "foreign": items}


def judge_writes_outside(procedure, step, changed):
    """Changed paths a judge role wrote outside its outputs (→ security-boundary stop)."""
    p = procedure.step(step) if isinstance(step, str) else step
    if not p.is_judge:
        return None
    out = []
    for path in sorted(set(changed)):
        try:
            inside = globs.match_any(p.outputs, path) is not None if p.outputs else False
        except ValueError:
            inside = False
        if not inside:
            out.append(path)
    return out


def add_boundary_facts(ctx, procedure, state, step, facts, procedure_commit, owner_facts=None, owned=None):
    """Fill facts `control_files`, `ownership`, `judge_writes_outside` in place (role and run
    attempts). Raises facts.FactMissing / gitops.UnsafePath like the checks themselves.
    `owned` (stage 3): owned_files, read BEFORE this attempt's facts are written — the judged
    step is never compared with itself, so its own new files do not matter here."""
    p = procedure.step(step) if isinstance(step, str) else step
    head = facts["end_head"]
    facts["control_files"] = check_control_files(ctx, procedure_commit, procedure.issue, head)
    if p.kind in (codes.StepKind.ROLE.value, codes.StepKind.RUN.value):
        facts["ownership"] = check_ownership(ctx, procedure, state, p, owner_facts, head, owned)
    if p.is_judge:
        changed = _git_fact("attempt_changes", F.attempt_changes, ctx, facts["start_head"], head, facts["end_tree"])
        facts["judge_writes_outside"] = judge_writes_outside(procedure, p, changed)
    return facts


def outcome_fact(outcome, step_status):
    """facts.json `outcome` for an Outcome and the step status statemachine.apply left."""
    return {"status": step_status, "code": outcome.code, "detail": outcome.detail, "stop": outcome.stop}


# --- judging ---------------------------------------------------------------------------

def _infra(detail, reset_at=None):
    return Outcome("failed", code=codes.FailureCode.INFRA.value, detail=detail, reset_at=reset_at)


def _fmt(detail, errors):
    return Outcome("failed", code=codes.FailureCode.OUTPUT_FORMAT.value, detail=detail, errors=errors)


def _cf(detail, back_to=None, errors=()):
    return Outcome("failed", code=codes.FailureCode.CHECK_FAILED.value, detail=detail, back_to=back_to,
                   errors=errors)


def _stop(reason):
    return Outcome("stop", stop=reason)


def _security(facts, judge):
    """Security-boundary Outcome, an infra Outcome for a missing boundary fact, or None."""
    cf = facts.get("control_files")
    if not isinstance(cf, dict) or "ok" not in cf:
        return _infra(codes.InfraReason.FACT_COLLECTION.value)
    if not cf["ok"]:
        return _stop(codes.StopReason.CONTROL_FILE.value)
    if judge:
        jw = facts.get("judge_writes_outside")
        if jw is None:
            return _infra(codes.InfraReason.FACT_COLLECTION.value)
        if jw:
            return _stop(codes.StopReason.JUDGE_WROTE_OUTSIDE.value)
    return None


def _session_end(sess, quota_reset_at=None):
    end = sess.get("end")
    E = codes.SessionEnd
    if end == E.COMPLETED.value:
        return None
    if end == E.BUDGET.value:
        return Outcome("failed", code=codes.FailureCode.SESSION_LIMIT.value)
    if end == E.WALL_CLOCK.value:
        return _infra(codes.InfraReason.WALL_CLOCK.value)
    if end == E.NO_OUTPUT.value:
        return _infra(codes.InfraReason.NO_OUTPUT.value)
    if quota_reset_at is not None:
        return _infra(codes.InfraReason.QUOTA.value, reset_at=quota_reset_at)
    return _infra(codes.InfraReason.API.value)


def _check_results(result):
    """{check id: worst result} of a review result."""
    rank = {codes.CheckResult.PASS.value: 0, codes.CheckResult.NA.value: 1, codes.CheckResult.FAIL.value: 2}
    out = {}
    for c in result.get("checks") or []:
        cid, r = c.get("id"), c.get("result")
        if cid not in out or rank[r] > rank[out[cid]]:
            out[cid] = r
    return out


def judge_role(procedure, step, brief, result, facts, quota_reset_at=None, stage=2, catalog_steps=(),
               owned=None):
    """Apply the table above to a role attempt. Returns statemachine.Outcome.

    `result`: the structured output (dict) or None. `quota_reset_at`: the session's
    rejected-rate-limit reset time (session.SessionResult.quota_reset_at). `catalog_steps`
    (stage 3): the ids the session's result schema was filled with (result_schema). `owned`
    (stage 3): owned_files — a blocking finding goes back to the step that owns its file (K2)."""
    p = procedure.step(step) if isinstance(step, str) else step
    if p.kind != codes.StepKind.ROLE.value:
        raise ValueError(f"judge_role is for role steps, {p.id!r} is {p.kind}")
    sess = facts.get("session")
    if not isinstance(sess, dict):
        return _infra(codes.InfraReason.FACT_COLLECTION.value)
    # 1. security boundary (no system/init comparison since FC decision D; an earlier engine's
    # facts may still carry `session.init` — it is not read)
    sec = _security(facts, p.is_judge)
    if sec is not None:
        return sec
    if not isinstance(facts.get("ownership"), dict) or "ok" not in facts["ownership"]:
        return _infra(codes.InfraReason.FACT_COLLECTION.value)
    ended = _session_end(sess, quota_reset_at)
    if ended is not None:
        return ended
    # 2. the result
    O = codes.OutputFormatReason
    kind = (brief or {}).get("result_kind") or (codes.ResultKind.REVIEW.value if p.is_review
                                               else codes.ResultKind.WORK.value)
    if result is None:
        return _fmt(O.NO_STRUCTURED_OUTPUT.value, ["the session returned no structured output"])
    errs = validate_result(result, kind, stage, catalog_steps)
    if errs:
        return _fmt(O.RESULT_SCHEMA.value, errs)
    rerrs = _request_errors(result)
    if rerrs:
        return _fmt(O.UNKNOWN_REQUEST_STEP.value, rerrs)
    # 3. blocked
    if result["status"] == codes.ResultStatus.BLOCKED.value:
        return Outcome("blocked")
    # 4. outputs
    outs = facts.get("outputs")
    if not isinstance(outs, list):
        return _infra(codes.InfraReason.FACT_COLLECTION.value)
    bad = [o["path"] for o in outs if o.get("exists") and not o.get("regular")]
    if bad:
        return _fmt(O.NON_REGULAR_OUTPUT.value, [f"output {x!r} is not a regular file" for x in bad])
    missing = [o["path"] for o in outs if not o.get("exists")]
    if missing:
        return _fmt(O.MISSING_OUTPUT.value, [f"declared output {x!r} was not written" for x in missing])
    bad_schema = [o["path"] for o in outs if o.get("schema_ok") is False]
    if bad_schema:
        return _fmt(O.OUTPUT_SCHEMA.value, [f"output {x!r} does not follow its format" for x in bad_schema])
    if stage >= 3 and p.role_class == codes.RoleClass.WORK.value:
        unexplained = [g for g in facts.get("golden") or []
                       if g["row"] in codes.GOLDEN_ROWS_NEEDING_REASON and g["reason"] is None]
        if unexplained:                # E33: cumulative — a reason given before is carried over (facts.golden_facts)
            return _fmt(O.MISSING_GOLDEN_REASON.value,
                        [f"baseline row {g['row']} {g['path']!r} has no reason in `golden_reasons`" for g in unexplained])
    # 5–6. review rules
    if kind == codes.ResultKind.REVIEW.value:
        out = _judge_review(procedure, p, brief or {}, result, facts, owned)
        if out is not None:
            return out
    # 7. ownership, dirty tree
    own = facts["ownership"]
    if not own["ok"]:
        return _cf(codes.CheckFailedReason.FOREIGN_OUTPUT.value,
                   errors=[f"{f['path']} belongs to step {f['owner_step']}" for f in own["foreign"]])
    if p.role_class == codes.RoleClass.WORK.value:
        tree = facts.get("end_tree")
        if not isinstance(tree, dict) or "clean" not in tree:
            return _infra(codes.InfraReason.FACT_COLLECTION.value)
        if not tree["clean"]:
            return _cf(codes.CheckFailedReason.DIRTY_TREE.value,
                       errors=[f"uncommitted: {x}" for x in tree.get("dirty_files") or []])
    return Outcome("done")


def _judge_review(procedure, p, brief, result, facts, owned=None):
    O = codes.OutputFormatReason
    required = list(brief.get("checks") or p.checks)
    rule = set(brief.get("rule_checks") or [])
    reviewed = list(result.get("reviewed") or [])
    if not reviewed:
        return _fmt(O.EMPTY_REVIEWED.value, ["`reviewed` is empty: list every file you reviewed"])
    got = _check_results(result)
    missing = [c for c in required if c not in got]
    if missing:
        return _fmt(O.MISSING_CHECK.value, [f"check {c!r} is missing from `checks`" for c in missing])
    if any((instructions.CHECK_CATALOG.get(c) or {}).get("covers_diff") for c in required):
        specs = defaults.SPECS_DIR.replace("{issue}", str(procedure.issue)) + "/"
        need = [x for x in F.changed_paths(facts) if not x.startswith(specs)]
        uncovered = sorted(set(need) - set(reviewed))
        if uncovered:
            return _fmt(O.REVIEWED_NOT_COVERING.value,
                        [f"changed file {x!r} is not in `reviewed`" for x in uncovered])
    findings = result.get("findings") or []
    blockers = [f for f in findings if f.get("severity") == codes.Severity.BLOCKER.value]
    if result["verdict"] == codes.Verdict.PASS.value and blockers:
        return _fmt(O.PASS_WITH_BLOCKER.value, ["verdict is pass but a finding is a blocker — use block"])
    na = [c for c in required if c in rule and got.get(c) == codes.CheckResult.NA.value]
    if na:
        return _fmt(O.REQUIRED_CHECK_NA.value, [f"check {c!r} was added by an engine rule and may not be n/a"
                                                for c in na])
    failed = [c for c in required if got.get(c) == codes.CheckResult.FAIL.value]
    if failed:
        return _cf(codes.CheckFailedReason.REQUIRED_CHECK_FAIL.value, back_to=block_target(procedure, p, findings, owned),
                   errors=[f"check {c!r} failed" for c in failed])
    if result["verdict"] == codes.Verdict.BLOCK.value:
        return _cf(codes.CheckFailedReason.VERDICT_BLOCK.value, back_to=block_target(procedure, p, findings, owned),
                   errors=[f"{f.get('severity')}: {f.get('file')}: {f.get('text')}"[:500] for f in findings])
    return None


def _from_run_outcome(oc, tree):
    """statemachine.Outcome of a runner outcome dict (runner.outcome_of shape)."""
    if not isinstance(oc, dict) or "status" not in oc:
        return _infra(codes.InfraReason.FACT_COLLECTION.value)
    if oc.get("stop"):
        return _stop(oc["stop"])
    if oc["status"] == codes.StepStatus.DONE.value:
        return Outcome("done")
    if oc["status"] == codes.StepStatus.FAILED.value and oc.get("code"):
        errors = ()
        if oc.get("detail") == codes.CheckFailedReason.RUN_DIRTY_TREE.value:
            errors = [f"left behind: {x}" for x in tree.get("dirty_files") or []]
        return Outcome("failed", code=oc["code"], detail=oc.get("detail"), errors=errors)
    return _infra(codes.InfraReason.FACT_COLLECTION.value)


def judge_run(step, facts, run_outcome=None):
    """A run attempt → Outcome. The security boundary first (control files, C7), then the
    runner's own judgment (`run_outcome` = runner.StepRun.outcome — P3-Z decision 1: the run
    verdict is the runner's, base-red first). Without `run_outcome` the same precedence is
    applied to facts.run: base red → stop base-red · dirty tree / moved HEAD → run-dirty-tree
    · timeout → run-timeout · rc ≠ 0 → run-nonzero · no exit code → infra op-failed."""
    sec = _security(facts, judge=False)
    if sec is not None:
        return sec
    run = facts.get("run")
    tree = facts.get("end_tree")
    if not isinstance(run, dict) or not isinstance(tree, dict) or "clean" not in tree:
        return _infra(codes.InfraReason.FACT_COLLECTION.value)
    if run_outcome is not None:
        return _from_run_outcome(run_outcome, tree)
    C = codes.CheckFailedReason
    br = [x for x in (run.get("base_run"), run.get("base_rerun")) if isinstance(x, dict)]
    if br and all(x.get("timed_out") or x.get("exit_code") != 0 for x in br):      # K8-2: the second run counts
        return _stop(codes.StopReason.BASE_RED.value)
    if not tree["clean"] or facts.get("start_head") != facts.get("end_head"):
        return _cf(C.RUN_DIRTY_TREE.value, errors=[f"left behind: {x}" for x in tree.get("dirty_files") or []])
    if run.get("timed_out"):
        return _cf(C.RUN_TIMEOUT.value)
    rc = run.get("exit_code")
    if rc is None:
        return _infra(codes.InfraReason.OP_FAILED.value)
    if rc != 0:
        return _cf(C.RUN_NONZERO.value)
    return Outcome("done")


def block_target(procedure, step, findings, owned=None):
    """I3: the owner step of the blocking findings' files, else the step's on_fail target.
    `owned` (owned_files, stage 3 / K2): a work step owns its own files, not its globs."""
    p = procedure.step(step) if isinstance(step, str) else step
    here = procedure.index(p.id)
    findings = list(findings or [])
    blocking = [f for f in findings if f.get("severity") == codes.Severity.BLOCKER.value] or findings
    best = None
    for f in blocking:
        path = f.get("file")
        if not isinstance(path, str):
            continue
        path = path[2:] if path.startswith("./") else path
        try:
            owner = owner_step(procedure, path, owned)
        except ValueError:
            continue
        if owner is None or owner == p.id:
            continue
        i = procedure.index(owner)
        if i > here:
            continue
        if best is None or i < procedure.index(best):
            best = owner
    if best is not None:
        return best
    return p.on_fail["back_to"] if p.on_fail else None


def commit_judge_outputs(ctx, procedure, step, issue, facts=None):
    """Engine commit of a judge step's outputs after the regular-file check (§7.6). Returns the SHA.

    Call only after the step's control-file and ownership checks passed (§7.6). Every
    output must be a regular file inside the step's outputs and not a control file; the
    commit message carries no Issue reference (S10). With `facts`, its `outputs` are read
    back from the new commit (blob ids — the ownership reference of later steps) and each
    committed blob must equal the file the judgment saw on disk."""
    p = procedure.step(step) if isinstance(step, str) else step
    if not p.is_judge:
        raise ValueError(f"step {p.id!r} is not a judge role step")
    outs = facts.get("outputs") if facts else F.output_facts(ctx, procedure, p, gitops.head(ctx))
    algo = _hash_algo(ctx)
    paths, seen = [], {}
    for o in outs:
        if not o.get("exists"):
            continue
        path = o["path"]
        if not o.get("regular"):
            raise gitops.UnsafePath(f"{path}: not a regular file — not committed")
        if globs.match_any(p.outputs, path) is None:
            raise gitops.UnsafePath(f"{path}: outside the outputs of {p.id!r}")
        if globs.is_control_file(path, issue):
            raise gitops.UnsafePath(f"{path}: a control file is never committed by the engine")
        d = _disk_entry(ctx, path, algo)
        if d is None or d[0] not in ("100644", "100755"):
            raise gitops.UnsafePath(f"{path}: not a regular file — not committed")
        seen[path] = d[1]
        paths.append(path)
    if paths:
        sha = gitops.commit_paths(ctx, paths, f"docs: {p.name} output of step {p.id} (gx engine)")
    else:
        sha = gitops.head(ctx)
    if facts is not None:
        fresh = F.output_facts(ctx, procedure, p, sha)
        for o in fresh:
            if o["path"] in seen and o.get("blob") != seen[o["path"]]:
                raise gitops.GitError(f"engine commit {sha}: {o['path']} does not hold the judged content")
        facts["outputs"] = fresh
    return sha
