"""E9-2: base verification files a HUMAN allows an Issue to modify (stage-4 scope §2.10 H21, VB5).

The driver (resume --allow-test-change) calls `apply` under the lock BEFORE the rerun answer is applied;
the runner gets `allowed(state)`. Stage >= 4 only. The leader has no way to give one (no field in any
answer schema — TT4).

An allowance is one exact path and one thing: the CONTENT of that base file may change. Deleting it,
renaming it, changing its type or mode stays a violation (runner.frozen_violations), and everything else
that looks at a test change (test-change-review, verify-gate) still does.
"""

import hashlib

from . import codes, gitops, globs


class Refused(ValueError):
    """The allowance is refused; state.json and the log are unchanged (TT3). The driver reports it as a refused answer."""


STOPS = (codes.StopReason.BLOCKED.value, codes.StopReason.ON_FAIL_EXCEEDED.value)
FROZEN = codes.PluginCommand.VERIFICATION_FROZEN.value


def _path_problem(path):
    if not isinstance(path, str) or not path:
        return "--allow-test-change: an empty path"
    if globs.is_glob(path):
        return f"--allow-test-change {path!r}: one exact file, not a glob or a folder"
    if "\\" in path or any(ord(c) < 32 or ord(c) == 127 for c in path):
        return f"--allow-test-change {path!r}: not a plain path"
    if path.startswith("/") or any(seg in ("", ".", "..") for seg in path.split("/")):
        return f"--allow-test-change {path!r}: must be a plain path relative to the repository root"
    return None


def args_problem(answer, step, paths, note):
    """Why these resume arguments cannot be an allowance, or None — pure, checked before detaching.

    answer must be `rerun` with a step, every path a plain relative path (no glob character, not empty, no
    duplicate), the note not empty."""
    if answer != codes.LeaderAnswer.RERUN.value:
        return "--allow-test-change goes with --answer rerun only"
    if not step:
        return "--allow-test-change needs --step (the work step that may change the file)"
    if not isinstance(note, str) or not note.strip():
        return "--allow-test-change needs --note-file (why a human allows it)"
    if not paths:
        return "--allow-test-change names no file"
    for p in paths:
        problem = _path_problem(p)
        if problem:
            return problem
    if len(set(paths)) != len(paths):
        return "--allow-test-change names the same file twice"
    return None


def apply(state, paths, note, *, step, procedure, config, ctx, owned, now):
    """Add `paths` to state["allowed_test_changes"] and return [log (event, fields)]; Refused otherwise.

    Conditions (all): the procedure has a verification-frozen run; the stop is `blocked` or
    `on-fail-exceeded` at needs_human; `step` is a work step; every path is a regular file of the recorded base
    (ctx.base_sha) under a `verification` rule of `config` and is in no step's files (`owned` =
    results.owned_files for the work steps, output globs for the others — a safety-net file can never be
    allowed, E10). The state changes only when every path passes. A path allowed before keeps its first entry."""
    problem = args_problem(codes.LeaderAnswer.RERUN.value, step, paths, note)
    if problem:
        raise Refused(problem)
    stop = state.get("stop") or {}
    if stop.get("status") != codes.StepStatus.NEEDS_HUMAN.value or stop.get("reason") not in STOPS:
        raise Refused("--allow-test-change answers a blocked or on-fail-exceeded stop that waits for a human")
    if not any(s.kind == codes.StepKind.RUN.value and s.name in config.command_names()
               and config.command(s.name)["plugin"] == FROZEN for s in procedure.steps):
        raise Refused(f"the procedure has no {FROZEN} run — its tests are not frozen")
    try:
        target = procedure.step(step)
    except KeyError:
        raise Refused(f"no step {step!r} in the procedure") from None
    if target.role_class != codes.RoleClass.WORK.value:
        raise Refused(f"{step!r} is not a work step — only a developer step changes files")
    for p in paths:
        try:
            got = gitops.blob(ctx, ctx.base_sha, p)
        except gitops.GitError as e:
            raise Refused(f"{p}: the recorded base could not be read: {e}") from e
        if got is None or got[2] is None or not gitops.is_regular_mode(got[0]):
            raise Refused(f"{p}: not a regular file of the recorded base {ctx.base_sha[:12]} "
                          "(a new test file needs no allowance)")
        if not config.matches(codes.PathRuleKind.VERIFICATION.value, p):
            raise Refused(f"{p}: under no verification rule of the repository settings — it is not frozen")
        owner = procedure.owner_of(p, owned)
        if owner is not None:
            raise Refused(f"{p}: owned by step {owner!r} — such a file (a safety net) can never be allowed (E10)")
    have = list(state.get("allowed_test_changes") or [])
    known = {x["path"] for x in have}
    digest = hashlib.sha256(note.encode("utf-8", "surrogatepass")).hexdigest()
    have += [{"path": p, "at": now, "note_sha256": digest} for p in paths if p not in known]
    state["allowed_test_changes"] = have
    return [(codes.LogEvent.TEST_CHANGE_ALLOWED.value,
             {"who": codes.Actor.HUMAN.value, "step": step, "data": {"paths": sorted(paths), "note_sha256": digest}})]


def allowed(state):
    """The allowed paths (sorted) of a state — runner.run_step `allowed_test_changes`, prbody stage4."""
    return sorted({x["path"] for x in state.get("allowed_test_changes") or []})
