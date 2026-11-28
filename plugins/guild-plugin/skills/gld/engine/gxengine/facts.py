"""Collect facts.json — the engine's own observations (design §7.2-3, §9.3, §7.12 S5) — U7.

JUDGMENT facts — exit code, changed files (merge-base(base, HEAD)..HEAD + uncommitted +
untracked non-ignored, both rename paths), start/end HEAD, tree state, outputs (existence,
regular-file mode, blob): failing to collect any of them raises
FactMissing → the step stops as infra (InfraReason.FACT_COLLECTION). MEASUREMENT facts —
cost, cache tokens, model, effort, duration, permission denials: a failure only adds a
`warnings` entry (counted in state totals.warnings and always shown, §9.3).
Stage 1–2 claim↔fact comparison: exit code and changed files only (§9.2).

U7 decisions (see the P3-A report):

  * gitops.UnsafePath / Tampered are NOT turned into FactMissing: a moved gitfile or
    commondir, or a link on an output path, is a security signal — it propagates so the
    driver stops with `unsafe-path` instead of an infra retry.
  * `finish_facts` leaves the boundary facts (`control_files`, `ownership`,
    `judge_writes_outside`) and `outcome` as None: results.py (U8) fills them
    (`results.add_boundary_facts`, `results.outcome_fact`). A role step without a session
    result, or a run step without its `run` object, is FactMissing.
  * effort: stream-json carries no effort (open question 8). The fact is the effort the
    engine passed (`--effort`), recorded only when the session's init model is the model the
    engine asked for; otherwise null + a warning. The model is the init event's `model`.
  * A glob output that matches nothing is ONE entry `{path: <the glob>, exists: false}` —
    a declared output that was not produced (fail-closed: results.py reads it as missing).
  * Output paths are reached through real directories only: a link anywhere on the path
    makes the entry `regular: false` (→ output-format non-regular-output).
  * `attempt_changes` is the per-attempt change set (start_head..end_head + the end tree's
    dirty files) for the judge write-scope check: `changed_files` is cumulative since the
    base, which would count the developer's earlier work against a later judge.

Stage 3 (V4; review-q0 D1, D2, D5): a role attempt records `attempt_files` (a judgment fact),
`step_files` nets them over the attempts of one step, and a work step's output globs are one
union (`output_facts`). Stages 1–2 write none of it.
"""

import hashlib
import os
import stat
import time

from . import codes, defaults, globs, gitops, schema, store

_MEASUREMENT_SESSION = ("cost_usd", "cache_read_input_tokens", "cache_creation_input_tokens", "num_turns")


class FactMissing(Exception):
    """A judgment fact could not be collected. `.fact` names it."""

    def __init__(self, fact, note=""):
        self.fact = fact
        self.note = note
        super().__init__(f"judgment fact {fact!r} could not be collected" + (f": {note}" if note else ""))


def _judgment(fact, fn, *args):
    try:
        return fn(*args)
    except gitops.UnsafePath:
        raise
    except FactMissing:
        raise
    except (gitops.GitError, OSError, ValueError) as e:
        raise FactMissing(fact, str(e)[:500]) from e


def _warn(warnings, fact, note):
    warnings.append({"fact": fact, "note": str(note)[:500]})


def start_facts(ctx, step, attempt, issue, kind):
    """Facts recorded before an attempt: start_head, start_tree, base_sha, merge_base, started_at."""
    if kind not in codes.StepKind.values():
        raise ValueError(f"bad step kind {kind!r}")
    head = _judgment("start_head", gitops.head, ctx)
    return {
        "issue": issue, "step": step, "attempt": attempt, "kind": kind,
        "base_sha": ctx.base_sha,
        "merge_base": _judgment("merge_base", gitops.merge_base, ctx, head),
        "start_head": head,
        "start_tree": _judgment("start_tree", gitops.tree_state, ctx),
        "started_at": store.now_ts(),
        "t0": time.monotonic(),
    }


def _session_part(session_result, warnings):
    """(session object, warnings appended) — see session_facts."""
    s = session_result
    end = getattr(s, "end", None)
    if end not in codes.SessionEnd.values():
        raise FactMissing("session.end", f"bad end {end!r}")
    stream_file = getattr(s, "stream_file", None)
    if not isinstance(stream_file, str) or not stream_file:
        raise FactMissing("session.stream_file")
    cost = getattr(s, "cost", None) or {}
    out = {
        "session_id": getattr(s, "session_id", None),
        "cli_version": getattr(s, "cli_version", None),
        "end": end,
        "structured_output": getattr(s, "structured", None) is not None,
        "stream_file": stream_file,
        "model": getattr(s, "model", None),
        "effort": None,
    }
    for k in _MEASUREMENT_SESSION:
        v = cost.get(k)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            v = None
        if k != "cost_usd" and isinstance(v, float):
            v = int(v) if v == int(v) else None
        out[k] = v
    if out["cost_usd"] is not None and out["cost_usd"] < 0:
        out["cost_usd"] = None
    denials = getattr(s, "denials", None)
    if denials is None:
        out["permission_denials"] = None
    else:
        out["permission_denials"] = []
        for d in denials:
            if not isinstance(d, dict) or not isinstance(d.get("tool_name"), str):
                continue
            item = {"tool_name": d["tool_name"]}
            if isinstance(d.get("tool_input"), dict):
                item["tool_input"] = d["tool_input"]
            if schema.surrogate_errors(item):       # facts.json is UTF-8 (review-q0 D9); a measurement only
                _warn(warnings, "session.permission_denials", "a denial held a lone surrogate — its text is left out")
                item = {"tool_name": ascii(d["tool_name"])[1:-1]}
            out["permission_denials"].append(item)
    spawned = getattr(s, "exit_code", None) is not None or getattr(s, "result_event", None) is not None
    if spawned:
        for k in _MEASUREMENT_SESSION:
            if out[k] is None:
                _warn(warnings, f"session.{k}", "not in the stream-json result event")
        if out["model"] is None:
            _warn(warnings, "session.model", "no model in the system/init event")
        if out["permission_denials"] is None:
            _warn(warnings, "session.permission_denials", "no result event")
        for w in getattr(s, "warnings", None) or []:
            _warn(warnings, "session.stream", f"stream line not parsed: {w}")
    return out


def session_facts(session_result):
    """facts.json `session` object from a session.SessionResult (measurement fields may be None)."""
    return _session_part(session_result, [])


def _record_effort(sess, requested_model, requested_effort, warnings):
    """open question 8: the effort the engine passed, when the init model is the requested one."""
    model = sess.get("model")
    if requested_effort is not None and model is not None and requested_model is not None \
            and _same_model(model, requested_model):
        sess["effort"] = requested_effort
        return
    _warn(warnings, "session.effort",
          f"stream-json carries no effort; init model {model!r} vs requested {requested_model!r}")


def _same_model(actual, alias):
    """`claude-sonnet-5-5` ran for `--model sonnet` (an alias) or the exact id."""
    a = actual.lower()
    b = alias.lower()
    return a == b or b in a.replace("_", "-").split("-")


def changed_paths(facts):
    """Every changed path, both sides of renames, sorted unique."""
    out = set()
    for c in facts.get("changed_files") or []:
        out.add(c["path"])
        if c.get("from"):
            out.add(c["from"])
    return sorted(out)


def _tree_entries(ctx, sha):
    """{path: (mode, sha)} of every entry of `sha`'s tree (recursive)."""
    raw = gitops.git(ctx, "ls-tree", "-r", "-z", "--full-tree", sha)
    out = {}
    for e in raw.split("\0"):
        if not e:
            continue
        meta, _, name = e.partition("\t")
        mode, _typ, obj = meta.split()
        out[name] = (mode, obj)
    return out


def _lstat_path(root, rel):
    """(kind, st) of root/rel reached through real directories only: kind is "regular",
    "link", "other", "missing" or "linked-parent"."""
    cur = root
    parts = rel.split("/")
    for i, part in enumerate(parts):
        cur = os.path.join(cur, part)
        try:
            st = os.lstat(cur)
        except FileNotFoundError:
            return "missing", None
        except NotADirectoryError:
            return "missing", None
        last = i == len(parts) - 1
        if not last:
            if stat.S_ISLNK(st.st_mode):
                return "linked-parent", st
            if not stat.S_ISDIR(st.st_mode):
                return "missing", None
            continue
        if stat.S_ISREG(st.st_mode):
            return "regular", st
        if stat.S_ISLNK(st.st_mode):
            return "link", st
        return "other", st
    return "missing", None


def worktree_files(ctx):
    """Worktree-relative paths of the files git sees in the worktree now (tracked + untracked
    non-ignored) — used to expand output globs."""
    raw = gitops.git(ctx, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    return sorted({p for p in raw.split("\0") if p})


def output_facts(ctx, procedure, step, head_sha, stage=2):
    """facts.json `outputs`: every declared output (globs expanded) with exists/regular/blob.

    From stage 3 the outputs of a WORK step are one union (review-q0 D5: `{path:…}` expands to
    every glob of the rule, and a repository need not have a file for each): nothing is missing
    while one file matches any of them, and a link that was on the base already is not an output
    of this step. No match at all → every pattern is reported missing."""
    p = procedure.step(step) if isinstance(step, str) else step
    if not p.outputs:
        return []
    tree = _tree_entries(ctx, head_sha)
    on_disk = worktree_files(ctx)
    if stage >= 3 and p.role_class == codes.RoleClass.WORK.value:
        base = _tree_entries(ctx, ctx.base_sha)
        out = []
        for path in sorted({x for x in list(tree) + on_disk if path_matches(p.outputs, x)}):
            entry = _output_entry(ctx, tree, path)
            if not entry["regular"] and path in base and tree.get(path) == base[path]:
                continue
            out.append(entry)
        return out or [{"path": pat, "exists": False, "regular": False, "blob": None}
                       for pat in dict.fromkeys(p.outputs)]
    seen = set()
    out = []
    for pat in p.outputs:
        if globs.is_glob(pat):
            cands = sorted({x for x in list(tree) + on_disk if globs.match(pat, x)})
            if not cands:
                if pat not in seen:
                    seen.add(pat)
                    out.append({"path": pat, "exists": False, "regular": False, "blob": None})
                continue
        else:
            cands = [pat]
        for path in cands:
            if path in seen:
                continue
            seen.add(path)
            out.append(_output_entry(ctx, tree, path))
    return out


def _output_entry(ctx, tree, path):
    kind, _ = _lstat_path(ctx.work_tree, path)
    entry = tree.get(path)
    exists = kind != "missing" or entry is not None
    regular = kind == "regular" and (entry is None or gitops.is_regular_mode(entry[0]))
    if kind == "missing" and entry is not None:
        regular = False          # committed but deleted in the worktree
    return {"path": path, "exists": exists, "regular": regular, "blob": entry[1] if entry is not None else None}


def attempt_changes(ctx, start_head, end_head, end_tree):
    """Paths changed DURING one attempt: start_head..end_head (both rename sides) + the end
    tree's dirty files (tracked changes and untracked non-ignored files)."""
    paths = set(end_tree.get("dirty_files") or [])
    if start_head != end_head:
        paths.update(gitops.changed_between(ctx, start_head, end_head))
    return sorted(paths)


def finish_facts(ctx, start, procedure, step, session=None, run=None, config=None, stage=2, paths=None):
    """Complete the facts dict after the attempt (schema `facts`); raises FactMissing.

    `session`: the session.SessionResult of a role step. `run`: the facts `run` object of a
    run step (runner.run_step). Optional `start["reentry"]` (I7) and
    `start["requested"] = {"model", "effort"}` (the session parameters) are carried over.

    From stage 3 `start["escalation"]` (the brief's session.escalation object, ladder.raised; None
    for a step that is never raised) is carried into session.escalation.
    From stage 3 a role attempt also gets `attempt_files`. `paths` (EnginePaths, optional): with
    it, work of earlier attempts of this step that left no facts.json is counted here
    (attempt_start). `config` (RepoConfig, optional): with it, `golden` is the baseline-image
    ledger (E33, golden_facts); without it `golden` is None (no ledger, no reason rule).
    """
    warnings = []
    p = procedure.step(step) if isinstance(step, str) else step
    kind = start["kind"]
    if kind != p.kind:
        raise ValueError(f"start facts are for a {kind} step, {p.id!r} is {p.kind}")
    ended = store.now_ts()
    t0 = start.get("t0")
    duration = round(time.monotonic() - t0, 3) if isinstance(t0, (int, float)) else None
    if duration is None:
        _warn(warnings, "duration_s", "no start clock")
    end_head = _judgment("end_head", gitops.head, ctx)
    end_tree = _judgment("end_tree", gitops.tree_state, ctx)
    mb = _judgment("merge_base", gitops.merge_base, ctx, end_head)
    changed = _judgment("changed_files", gitops.changed_files, ctx, end_head)
    outputs = _judgment("outputs", output_facts, ctx, procedure, p, end_head, stage)
    try:
        commits = gitops.commits_between(ctx, start["start_head"], end_head) if start["start_head"] != end_head else []
    except gitops.UnsafePath:
        raise
    except gitops.GitError as e:
        commits = []
        _warn(warnings, "commits", e)

    sess = None
    exit_code = None
    run_obj = None
    if kind == codes.StepKind.ROLE.value:
        if session is None:
            raise FactMissing("session", "a role step needs its session result")
        sess = _session_part(session, warnings)
        req = start.get("requested") or {}
        _record_effort(sess, req.get("model"), req.get("effort"), warnings)
        if stage >= 3:
            sess["escalation"] = start.get("escalation")
        exit_code = session.exit_code
    elif kind == codes.StepKind.RUN.value:
        if not isinstance(run, dict) or "exit_code" not in run:
            raise FactMissing("run", "a run step needs its run result")
        run_obj = run
        exit_code = run.get("exit_code")
    facts = {
        "format": defaults.FORMAT,
        "issue": start["issue"], "step": start["step"], "attempt": start["attempt"], "kind": kind,
        "started_at": start.get("started_at"), "ended_at": ended, "duration_s": duration,
        "base_sha": start["base_sha"], "merge_base": mb,
        "start_head": start["start_head"], "end_head": end_head,
        "start_tree": start["start_tree"], "end_tree": end_tree,
        "exit_code": exit_code,
        "changed_files": changed,
        "commits": commits,
        "outputs": outputs,
        "control_files": None,
        "ownership": None,
        "judge_writes_outside": None,
        "reentry": start.get("reentry"),
        "session": sess,
        "run": run_obj,
        "outcome": None,
        "warnings": warnings,
    }
    if stage >= 3 and kind == codes.StepKind.ROLE.value:
        since = _judgment("attempt_files", attempt_start, ctx, start, paths)
        facts["attempt_files"] = _judgment("attempt_files", attempt_file_facts, ctx, since, end_head, end_tree)
        facts["golden"] = None
        if config is not None:
            facts["golden"] = _judgment("golden", golden_facts, ctx, config, end_head, end_tree,
                                        golden_reasons(session.structured), golden_history(paths, procedure))
    return facts


def reentry_facts(ctx, recorded_head):
    """I7 developer re-entry: {"forward_only": bool, "dirty_files": [...]}."""
    head = _judgment("reentry.head", gitops.head, ctx)
    forward = True if head == recorded_head else _judgment("reentry.forward_only", gitops.is_forward, ctx,
                                                           recorded_head, head)
    tree = _judgment("reentry.dirty_files", gitops.tree_state, ctx)
    return {"forward_only": bool(forward), "dirty_files": list(tree["dirty_files"])}


def warning_count(facts):
    """Number of measurement warnings of one facts dict (state totals.warnings, §9.3)."""
    return len(facts.get("warnings") or [])


# --- stage 3: what each attempt changed, and the files a step owns (review-q0 D1, D2) ---------

def hash_algo(ctx):
    return "sha256" if len(ctx.base_sha) == 64 else "sha1"


def blob_id(algo, data):
    h = hashlib.new(algo)
    h.update(b"blob %d\0" % len(data))
    h.update(data)
    return h.hexdigest()


def disk_entry(ctx, rel, algo):
    """(mode, sha) of a worktree path as git would store it, None if missing, ("other", None)
    for something git cannot store or a path reached through a link."""
    kind, st = _lstat_path(ctx.work_tree, rel)
    if kind == "missing":
        return None
    full = os.path.join(ctx.work_tree, rel)
    if kind == "regular":
        with open(full, "rb") as f:
            data = f.read()
        mode = "100755" if st.st_mode & 0o111 else "100644"
        return (mode, blob_id(algo, data))
    if kind == "link":
        return ("120000", blob_id(algo, os.fsencode(os.readlink(full))))
    return ("other", None)


def attempt_start(ctx, start, paths):
    """The commit this attempt's changes are counted from: its start_head, or the start_head of
    the attempts of this step right before it that left no facts.json (the engine was killed, or a
    fact was missing). What those changed would otherwise belong to no attempt: nobody would own
    it and no scope check would see it."""
    sha = start["start_head"]
    if paths is None:
        return sha
    for n in range(start["attempt"] - 1, 0, -1):
        if os.path.lexists(paths.attempt_file(start["step"], n, "facts.json")):
            break
        brief = store.read_brief_or_none(paths, start["step"], n)
        prev = (brief or {}).get("start_head")
        if isinstance(prev, str) and gitops.is_forward(ctx, prev, sha):
            sha = prev
    return sha


def attempt_file_facts(ctx, start_sha, end_head, end_tree):
    """facts.json `attempt_files`: [{"path", "old_blob", "new_blob"}] of everything changed since
    `start_sha` (both rename sides; the end tree's dirty files with their content on disk)."""
    dirty = set(end_tree.get("dirty_files") or [])
    changed = attempt_changes(ctx, start_sha, end_head, end_tree)
    if not changed:
        return []
    old, new, algo = _tree_entries(ctx, start_sha), _tree_entries(ctx, end_head), hash_algo(ctx)
    out = []
    for path in changed:
        was = old.get(path)
        now = disk_entry(ctx, path, algo) if path in dirty else new.get(path)
        out.append({"path": path, "old_blob": was[1] if was else None, "new_blob": now[1] if now else None})
    return out


def step_files(paths, step_id, patterns):
    """What the attempts of one step changed, net (interfaces §2.4, D1 / D2).

    Returns {"step", "attempts": [n], "net": {path: [old, new]}, "owned": [path], "outside":
    [path]}: `net` = the paths whose blob before the FIRST attempt that touched them differs from
    the blob after the LAST one; `owned` = net paths matching `patterns`; `outside` = the other
    net paths except docs/specs/<N>/. Only the step's own attempts count, so a later step's work
    changes nothing here. An attempt without facts.json is skipped (its changes are counted by the
    next one, attempt_start); one whose facts carry no `attempt_files` → FactMissing."""
    specs = defaults.SPECS_DIR.replace("{issue}", str(paths.issue)) + "/"
    attempts, first, last = [], {}, {}
    for n in store.attempt_numbers(paths, step_id):
        try:
            fx = store.read_facts(paths, step_id, n)
        except FileNotFoundError:
            continue
        rows = fx.get("attempt_files")
        if not isinstance(rows, list):
            raise FactMissing("attempt_files", f"{step_id} attempt {n} was recorded without them")
        attempts.append(n)
        for r in rows:
            first.setdefault(r["path"], r["old_blob"])
            last[r["path"]] = r["new_blob"]
    net = {p: [first[p], last[p]] for p in sorted(first) if first[p] != last[p]}
    owned = [p for p in net if path_matches(patterns, p)]
    outside = [p for p in net if p not in set(owned) and not p.startswith(specs)]
    return {"step": step_id, "attempts": attempts, "net": net, "owned": owned, "outside": outside}


def path_matches(patterns, path):
    """globs.match_any as a bool; a path the glob dialect cannot express matches nothing."""
    try:
        return globs.match_any(list(patterns), path) is not None
    except ValueError:
        return False


# --- stage 3: the baseline-image ledger (E33) --------------------------------------------------

def golden_reasons(result):
    """{path: GoldenReason} a role result reports (the first one of a path counts; anything not of
    that shape is left to the schema check of results.py)."""
    out = {}
    for r in (result.get("golden_reasons") if isinstance(result, dict) else None) or []:
        if isinstance(r, dict) and isinstance(r.get("path"), str) and r.get("reason") in codes.GoldenReason.values():
            path = r["path"][2:] if r["path"].startswith("./") else r["path"]
            out.setdefault(path, r["reason"])
    return out


def golden_history(paths, procedure):
    """{(row, path, old blob, new blob): reason} of every recorded role attempt, the latest one
    winning — what a reason is carried over from. {} without `paths`."""
    if paths is None:
        return {}
    seen = []
    for i, p in enumerate(procedure.steps):
        if p.kind != codes.StepKind.ROLE.value:
            continue
        for n in store.attempt_numbers(paths, p.id):
            try:
                fx = store.read_facts(paths, p.id, n)
            except FileNotFoundError:
                continue
            seen.append((fx.get("ended_at") or "", i, n, fx.get("golden") or []))
    out = {}
    for _, _, _, rows in sorted(seen, key=lambda x: x[:3]):
        for r in rows:
            if r["reason"] is not None:
                out[(r["row"], r["path"], r["old_blob"], r["new_blob"])] = r["reason"]
    return out


def golden_facts(ctx, config, end_head, end_tree, reasons, history):
    """facts.json `golden`: the ledger rows, cumulative from the recorded base (E33).

    A / M / D = a `golden` path added, changed (content or mode), deleted; R = the same blob at
    another golden path; C = a `comparison-config` path changed in any way; P = a golden path the
    role could not regenerate (needs-regeneration; it stays while its blobs do, until a role gives
    the path another reason). `reason` = this result's, else the one recorded before for exactly
    this row, path and blobs."""
    def patterns(category):
        return [g for r in config.path_rules(codes.PathRuleKind.VERIFICATION.value)
                if r.get("category") == category.value for g in r["globs"]]

    golden = patterns(codes.VerificationCategory.GOLDEN)
    compare = patterns(codes.VerificationCategory.COMPARISON_CONFIG)
    if not golden and not compare:
        return []
    base, now, algo = _tree_entries(ctx, ctx.base_sha), _tree_entries(ctx, end_head), hash_algo(ctx)
    for path in end_tree.get("dirty_files") or []:
        entry = disk_entry(ctx, path, algo)
        if entry is None:
            now.pop(path, None)
        else:
            now[path] = entry

    def blob(tree, path):
        return tree[path][1] if path in tree else None

    changed = sorted(p for p in set(base) | set(now) if base.get(p) != now.get(p))
    images = [p for p in changed if path_matches(golden, p)]
    gone = {}
    for p in images:
        if p not in now:
            gone.setdefault(blob(base, p), []).append(p)
    rows, moved = [], set()
    for p in images:
        if p not in base and gone.get(blob(now, p)):
            src = gone[blob(now, p)].pop(0)
            moved.add(src)
            rows.append((codes.GoldenRow.RENAMED.value, p, src))
        elif p not in base:
            rows.append((codes.GoldenRow.ADDED.value, p, None))
        elif p in now:
            rows.append((codes.GoldenRow.MODIFIED.value, p, None))
    rows += [(codes.GoldenRow.DELETED.value, p, None) for p in images if p not in now and p not in moved]
    rows += [(codes.GoldenRow.CONFIG.value, p, None) for p in changed if path_matches(compare, p)]
    regen = codes.GoldenReason.NEEDS_REGENERATION.value
    pending = {p for p, r in reasons.items() if r == regen and path_matches(golden, p)}
    pending |= {p for (row, p, old, new) in history if row == codes.GoldenRow.PENDING.value and p not in reasons
                and (old, new) == (blob(base, p), blob(now, p))}
    rows += [(codes.GoldenRow.PENDING.value, p, None) for p in pending]
    out = []
    for row, path, src in rows:
        old, new = blob(base, src or path), blob(now, path)
        reason = reasons.get(path) or history.get((row, path, old, new))
        if row == codes.GoldenRow.PENDING.value:
            reason = regen
        out.append({"row": row, "path": path, "from": src, "old_blob": old, "new_blob": new, "reason": reason})
    return sorted(out, key=lambda r: (r["path"], r["row"]))
