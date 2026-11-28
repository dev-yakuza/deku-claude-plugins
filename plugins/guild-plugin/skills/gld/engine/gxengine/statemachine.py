"""Step transitions and the two counters (design §4.4, §5, §5.1, §6, §9.2) — U4.

Pure functions over (state dict, Procedure). No I/O: the driver saves state and writes
the log events a Decision carries. Stage 1 (§9.2): every §6.3 leader situation
(`codes.LEADER_SITUATIONS`) becomes needs_human; needs_leader never appears.
Stage 2 (scope V6): a leader situation is needs_leader (D9: rule-unfillable / base-red stay
needs_human — the leader could only escalate); a check step is a leader judgment
(`open_check`); `to_human` hands a needs_leader stop over (escalate, leader failure,
mechanical stop of the leader session, caps); `insert_steps` is the one way state.steps grows.

Rules this module owns:
  - on_fail back_to X: X and every step after X → pending, run in order again (§4.4-1).
  - counters: per-step on_fail max N counts check-failed only; issue absolute caps
    (attempts, budget, leader calls — §5.1, §7.4).
  - output-format: same step once more with the errors, then a stop (§5.1).
  - session-limit → stop; infra: quota reset ≤ 4 h → wait and resume the same step, else
    stop keeping the state; engine-error → stop, step state untouched (I14).
  - a failed step without on_fail → stop (§5.1); on_fail max exceeded → stop.
  - result status blocked → stop without looking at verdict (I5-3).
  - I3: a block whose findings point at another step's outputs goes back to that owner.
  - §4.4-3: steps whose recorded start HEAD is older than a non-exempt change → pending.

Events are `(event, fields)` pairs for `store.append_log(paths, event, **fields)`.

Counter semantics (U4):
  - `on_fail_count` counts every check-failed of the step and is never reset (not by
    back_to, not by a later success): `max N` = at most N rewinds for the Issue. The
    (N+1)-th check-failed stops. A human `rerun` (I10) raises the allowance by one.
  - `output_format_retries` is per run of the step: reset when the step is done or
    rewound to pending by back_to / reverify.
  - `totals.attempts` grows by one in `mark_running` (every attempt counts, retries too).
"""

import time

from . import codes, defaults, store

S = codes.StepStatus
_STATUSES = frozenset(S.values())
OUTCOME_STATUSES = ("done", "failed", "blocked", "stop")
DECISION_ACTIONS = ("next", "retry-same", "back-to", "wait", "stop", "finish")
_DETAILS = frozenset(codes.CheckFailedReason.values() + codes.OutputFormatReason.values()
                     + codes.InfraReason.values())
LIMIT_KEYS = ("attempts", "budget_usd", "leader_calls")
_UNTOUCHED_STOPS = frozenset({codes.StopReason.ENGINE_ERROR.value, codes.StopReason.INFRA_STOP.value})


class StateError(Exception):
    """state.json and the procedure disagree, or a transition is not allowed from here."""


class Outcome:
    """What one attempt came to, as judged by results.py / runner.py.

    Attributes:
      status    "done" | "failed" | "blocked" (role result blocked) | "stop"
      code      codes.FailureCode value or None
      detail    sub-code (CheckFailedReason / OutputFormatReason / InfraReason) or None
      stop      codes.StopReason value for status "stop" (security boundary etc.) or None
      back_to   explicit back_to target (I3 owner) or None → the step's on_fail
      reset_at  epoch seconds of a quota reset (infra quota) or None
      errors    list of strings handed to the retry brief (output-format)
    """

    def __init__(self, status, code=None, detail=None, stop=None, back_to=None, reset_at=None, errors=()):
        if status not in OUTCOME_STATUSES:
            raise ValueError(f"bad outcome status {status!r}")
        if status == "failed":
            if code not in codes.FailureCode.values():
                raise ValueError(f"a failed outcome needs a FailureCode, got {code!r}")
        elif code is not None:
            raise ValueError(f"only a failed outcome carries a code (got {code!r} for {status})")
        if status == "stop":
            if stop not in codes.StopReason.values():
                raise ValueError(f"a stop outcome needs a StopReason, got {stop!r}")
        elif stop is not None:
            raise ValueError("only a stop outcome carries a stop reason")
        if detail is not None and detail not in _DETAILS:
            raise ValueError(f"unknown detail code {detail!r}")
        if back_to is not None and code != codes.FailureCode.CHECK_FAILED.value:
            raise ValueError("an explicit back_to only goes with check-failed (I3)")
        if reset_at is not None and code != codes.FailureCode.INFRA.value:
            raise ValueError("reset_at only goes with infra")
        if reset_at is not None and (isinstance(reset_at, bool) or not isinstance(reset_at, (int, float))):
            raise ValueError("reset_at must be epoch seconds")
        self.status = status
        self.code = None if code is None else str(code)
        self.detail = None if detail is None else str(detail)
        self.stop = None if stop is None else str(stop)
        self.back_to = back_to
        self.reset_at = reset_at
        self.errors = [str(e) for e in errors]

    def __repr__(self):
        return (f"Outcome({self.status!r}, code={self.code!r}, detail={self.detail!r}, "
                f"stop={self.stop!r}, back_to={self.back_to!r})")


class Decision:
    """What the driver must do next.

    Attributes:
      action    "next" | "retry-same" | "back-to" | "wait" | "stop" | "finish"
      step      the step id concerned
      target    back_to target (action "back-to")
      wait_s    seconds to wait (action "wait")
      stop      (status, codes.StopReason value) for action "stop"
      events    list of (event, fields) log entries to append
      errors    the output-format errors for the retry brief (action "retry-same")
    """

    def __init__(self, action, step=None, target=None, wait_s=None, stop=None, events=(), errors=()):
        if action not in DECISION_ACTIONS:
            raise ValueError(f"bad decision action {action!r}")
        self.action = action
        self.step = step
        self.target = target
        self.wait_s = wait_s
        self.stop = stop
        self.events = list(events)
        self.errors = list(errors)

    def __repr__(self):
        return f"Decision({self.action!r}, step={self.step!r}, target={self.target!r}, stop={self.stop!r})"


# --- helpers ----------------------------------------------------------------------

def _aligned(state, procedure):
    """Require state.steps and the procedure to list the same ids in the same order."""
    ids = [s["id"] for s in state["steps"]]
    if ids != procedure.step_ids:
        raise StateError(f"state.json steps {ids} differ from the procedure {procedure.step_ids}")
    if state.get("revision") != procedure.revision:
        raise StateError(f"state.json follows revision {state.get('revision')}, "
                         f"the procedure is revision {procedure.revision}")


def _sstep(state, step_id):
    for s in state["steps"]:
        if s["id"] == step_id:
            return s
    raise StateError(f"step {step_id!r} is not in state.json")


def _set_status(s, to, events, code=None, detail=None, note=None, data=None):
    frm = s["status"]
    if to not in _STATUSES:
        raise ValueError(f"bad status {to!r}")
    s["status"] = to
    if frm == to and code is None:
        return
    f = {"step": s["id"], "attempt": s.get("latest_attempt"), "from": frm, "to": to}
    if code is not None:
        f["code"] = code
    if detail is not None:
        f["detail"] = detail
    if note is not None:
        f["note"] = note
    if data:
        f["data"] = data
    events.append((codes.LogEvent.STATUS.value, f))


def _now(now):
    return time.time() if now is None else now


def leader_static_answers(reason, stage=2):
    """The leader seat's row of a stage ≥ 2 before the dynamic narrowing (codes.allowed_answers_table
    minus codes.LEADER_REMOVED_ANSWERS), or () when the row does not exist."""
    row = codes.allowed_answers_table(max(stage, 2)).get(reason, ())
    removed = codes.LEADER_REMOVED_ANSWERS.get(reason, ())
    return tuple(a for a in row if a not in removed)


def escalate_only(reason, stage=2):
    """D9 (static part): True when the leader seat could only escalate (rule-unfillable,
    base-red) — no leader call, the stop goes straight to needs_human."""
    return leader_static_answers(reason, stage) == (codes.LeaderAnswer.ESCALATE.value,)


def close_allowed(state):
    """K8-3: may a blocked stop be answered close-as-decided? Only while no developer step has ever
    started an attempt (state.developer_started is False from the Issue's start on). A state without
    the field — an earlier engine's — is not known: no (fail-closed)."""
    return (state or {}).get("developer_started") is False


def stop_status(reason, stage=1):
    """needs_leader or needs_human for a StopReason value (§9.2: stage 1 → needs_human).

    Stage ≥ 2: a §6.3 leader situation is needs_leader, except where the leader seat could
    only escalate (D9: rule-unfillable, base-red) — that is needs_human at once."""
    if reason not in codes.StopReason.values():
        raise ValueError(f"unknown stop reason {reason!r}")
    if isinstance(stage, bool) or not isinstance(stage, int) or stage < 1:
        raise ValueError(f"bad stage {stage!r}")
    if stage >= 2 and reason in codes.leader_situations(stage) and not escalate_only(reason, stage):
        return S.NEEDS_LEADER.value
    return S.NEEDS_HUMAN.value


def infra_fields(stage, detail, reset_at=None):
    """Stage ≥ 4 (H8): the `detail` / `reset_at` fields of an infra stop ({} before stage 4, or without a
    detail). `detail` = a codes.STOP_DETAILS value; `reset_at` (epoch seconds) goes with quota only."""
    if stage < codes.STAGE4 or detail is None:
        return {}
    detail = str(detail)
    if detail not in codes.STOP_DETAILS:
        raise ValueError(f"unknown infra detail {detail!r}")
    if reset_at is not None and (isinstance(reset_at, bool) or not isinstance(reset_at, (int, float))):
        raise ValueError("reset_at must be epoch seconds")
    return {"detail": detail, "reset_at": reset_at if detail == codes.InfraReason.QUOTA.value else None}


def stop_record(state, step_id, reason, stage, now=None, note=None, detail=None, reset_at=None):
    """The state["stop"] object of a stop (§5.1) — status by stop_status, the §6.3 row of the
    stage (codes.allowed_answers_table) as `allowed_answers` for a leader situation. Stage ≥ 4:
    `detail` / `reset_at` of an infra stop (infra_fields)."""
    status = stop_status(reason, stage)
    s = _sstep(state, step_id) if step_id is not None else None
    stop = {"status": status, "reason": reason, "step": step_id,
            "attempt": s.get("latest_attempt") if s is not None else None,
            "at": store.now_ts(_now(now))}
    table = codes.allowed_answers_table(stage)
    if reason in table:
        stop["allowed_answers"] = [a for a in table[reason] if not (
            reason == codes.StopReason.BLOCKED.value and a == codes.LeaderAnswer.CLOSE_AS_DECIDED.value
            and not close_allowed(state))]
    if note is not None:
        stop["note"] = note
    stop.update(infra_fields(stage, detail, reset_at))
    return stop


def _stop(state, step_id, reason, stage, now, events, note=None, touch_step=True, detail=None, reset_at=None):
    """Record an Issue stop in state["stop"] (and the step status unless untouched)."""
    status = stop_status(reason, stage)
    s = _sstep(state, step_id) if step_id is not None else None
    if s is not None and touch_step:
        _set_status(s, status, events, code=reason)
    stop = stop_record(state, step_id, reason, stage, now, detail=detail, reset_at=reset_at)
    if note is not None:
        stop["note"] = note
    state["stop"] = stop
    f = {"step": step_id, "attempt": stop["attempt"], "to": status, "code": reason}
    if note is not None:
        f["note"] = note
    events.append((codes.LogEvent.STOP.value, f))
    return Decision("stop", step=step_id, stop=(status, reason), events=events)


def _proceed(state, procedure, events):
    nxt = next_runnable(state, procedure)
    if nxt is None:
        return Decision("finish", events=events)
    return Decision("next", step=nxt, events=events)


# --- public -----------------------------------------------------------------------

def next_runnable(state, procedure):
    """The first step id that is pending/ready in procedure order, or None when all are done/skipped.

    StateError when the first unfinished step is running / failed / needs_* (the driver
    must settle that step — resume, answer — before anything later may run) or when
    an Issue stop is recorded in state["stop"].
    """
    _aligned(state, procedure)
    if state.get("stop"):
        raise StateError(f"the Issue is stopped ({state['stop'].get('reason')}); answer or resume first")
    for s in state["steps"]:
        st = s["status"]
        if st in (S.DONE.value, S.SKIPPED.value):
            continue
        if st in (S.PENDING.value, S.READY.value):
            return s["id"]
        raise StateError(f"step {s['id']!r} is {st}; nothing after it may run")
    return None


def mark_running(state, step_id, attempt, head):
    """Set the step running with latest_attempt / start_head. Returns the log events.

    The step must be pending/ready and the first runnable one; `attempt` is the number
    store.new_attempt returned (≥ the recorded latest_attempt). Counts the attempt in
    totals.attempts and records `head` as start_head and last_head.
    """
    s = _sstep(state, step_id)
    if s["status"] not in (S.PENDING.value, S.READY.value):
        raise StateError(f"step {step_id!r} is {s['status']}, not pending")
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        raise ValueError(f"bad attempt {attempt!r}")
    prev = s.get("latest_attempt")
    if prev is not None and attempt < prev:
        raise StateError(f"attempt {attempt} of {step_id!r} is older than the recorded {prev}")
    events = []
    s["latest_attempt"] = attempt
    s["start_head"] = head
    state["last_head"] = head
    totals = state.setdefault("totals", {})
    totals["attempts"] = totals.get("attempts", 0) + 1
    events.append((codes.LogEvent.ATTEMPT_START.value,
                   {"step": step_id, "attempt": attempt, "data": {"start_head": head}}))
    _set_status(s, S.RUNNING.value, events)
    return events


def apply(state, procedure, step_id, outcome, stage=1, now=None):
    """Apply an Outcome to `state` in place and return the Decision (§5.1 table)."""
    _aligned(state, procedure)
    if not isinstance(outcome, Outcome):
        raise TypeError("apply needs an Outcome")
    s = _sstep(state, step_id)
    p = procedure.step(step_id)
    if s["status"] != S.RUNNING.value:
        raise StateError(f"step {step_id!r} is {s['status']}, not running")
    events = []
    attempt = s.get("latest_attempt")
    F = codes.FailureCode

    if outcome.status == "done":
        s["output_format_retries"] = 0
        _set_status(s, S.DONE.value, events)
        return _proceed(state, procedure, events)

    if outcome.status == "blocked":
        # I5-3: status blocked → stop without looking at the verdict.
        return _stop(state, step_id, codes.StopReason.BLOCKED.value, stage, now, events)

    if outcome.status == "stop":
        # A security-boundary failure (or any mechanical stop): the result is discarded.
        return _stop(state, step_id, outcome.stop, stage, now, events,
                     touch_step=outcome.stop not in _UNTOUCHED_STOPS)

    # failed
    code = outcome.code
    if code == F.ENGINE_ERROR.value:
        # I14: the step state stays as it is; the traceback goes to the log by the driver.
        return _stop(state, step_id, codes.StopReason.ENGINE_ERROR.value, stage, now, events,
                     touch_step=False)
    s["reason"] = code
    s["detail"] = outcome.detail

    if code == F.SESSION_LIMIT.value:
        _set_status(s, S.FAILED.value, events, code=code, detail=outcome.detail)
        return _stop(state, step_id, codes.StopReason.SESSION_LIMIT.value, stage, now, events)

    if code == F.OUTPUT_FORMAT.value:
        used = s.get("output_format_retries", 0)
        _set_status(s, S.FAILED.value, events, code=code, detail=outcome.detail)
        if used < defaults.OUTPUT_FORMAT_RETRIES:
            s["output_format_retries"] = used + 1
            _set_status(s, S.PENDING.value, events, note="output-format retry with the errors")
            return Decision("retry-same", step=step_id, events=events, errors=outcome.errors)
        return _stop(state, step_id, codes.StopReason.OUTPUT_FORMAT_TWICE.value, stage, now, events)

    if code == F.INFRA.value:
        if outcome.reset_at is not None:
            wait = max(0.0, float(outcome.reset_at) - float(_now(now)))
            if wait <= defaults.INFRA_WAIT_MAX_S:
                _set_status(s, S.FAILED.value, events, code=code, detail=outcome.detail)
                _set_status(s, S.PENDING.value, events, note="quota wait, then the same step")
                events.append((codes.LogEvent.WAIT.value,
                               {"step": step_id, "attempt": attempt, "code": code,
                                "data": {"wait_s": wait, "reset_at": outcome.reset_at}}))
                return Decision("wait", step=step_id, wait_s=wait, events=events)
        # §5.1: otherwise stop, keeping the state (the step stays as it is for resume).
        return _stop(state, step_id, codes.StopReason.INFRA_STOP.value, stage, now, events,
                     note=outcome.detail, touch_step=False, detail=outcome.detail, reset_at=outcome.reset_at)

    if code == F.CHECK_FAILED.value:
        _set_status(s, S.FAILED.value, events, code=code, detail=outcome.detail)
        count = s.get("on_fail_count", 0) + 1
        s["on_fail_count"] = count
        if p.on_fail is None:
            # §5.1: a failed step without on_fail goes up (stage 1: needs_human).
            return _stop(state, step_id, codes.StopReason.ON_FAIL_EXCEEDED.value, stage, now, events,
                         note="the step has no on_fail")
        allowed = p.on_fail["max"] + s.get("on_fail_extra", 0)
        if count > allowed:
            return _stop(state, step_id, codes.StopReason.ON_FAIL_EXCEEDED.value, stage, now, events,
                         note=f"check-failed {count} > on_fail max {allowed}")
        target = outcome.back_to if outcome.back_to is not None else p.on_fail["back_to"]
        try:
            ti = procedure.index(target)
        except KeyError:
            raise StateError(f"back_to target {target!r} is not a step") from None
        if ti > procedure.index(step_id):
            raise StateError(f"back_to target {target!r} is after {step_id!r}")
        events += back_to(state, procedure, target, cause=step_id,
                          data={"count": count, "max": allowed, "detail": outcome.detail})
        return Decision("back-to", step=step_id, target=target, events=events)

    raise ValueError(f"unhandled failure code {code!r}")


def engine_error(state, step_id=None, stage=1, now=None, note=None):
    """I14: an engine top-level exception — stop needs_human, every step state untouched.

    Unlike `apply`, the step need not be running (the exception can come from anywhere).
    The driver writes the traceback to engine.log and an `error` log line itself.
    """
    if step_id is not None:
        _sstep(state, step_id)
    return _stop(state, step_id, codes.StopReason.ENGINE_ERROR.value, stage, now, [],
                 note=note, touch_step=False)


def back_to(state, procedure, target, cause=None, data=None):
    """Reset `target` and every later step to pending (§4.4-1). Returns the log events.

    Counters (on_fail_count, on_fail_extra) and latest_attempt are kept; the
    output-format retry allowance starts again.
    """
    _aligned(state, procedure)
    i = procedure.index(target)
    events = []
    d = {"target": target}
    if cause is not None:
        d["cause"] = cause
    if data:
        d.update({k: v for k, v in data.items() if v is not None})
    events.append((codes.LogEvent.BACK_TO.value, {"step": cause or target, "data": d}))
    for s in state["steps"][i:]:
        s["output_format_retries"] = 0
        _set_status(s, S.PENDING.value, events, note=f"back_to {target}")
    return events


def reverify(state, procedure, changed_since):
    """§4.4-3. `changed_since` maps step id → paths changed since that step's start_head.

    Exempt: docs/specs/<N>/ judgment documents the engine committed (I12). Review and run
    steps with any other change go back to pending. Returns the step ids reset.

    Only done review / run steps are looked at. A done review / run step missing from
    `changed_since` is reset too (fail-closed: no fact, no exemption). "Judgment
    document" = a path under docs/specs/<N>/ owned (procedure outputs) by a judge role
    step; procedure.yaml and anything else is not exempt.
    """
    _aligned(state, procedure)
    specs = defaults.SPECS_DIR.replace("{issue}", str(procedure.issue)) + "/"
    reset = []
    for s in state["steps"]:
        p = procedure.step(s["id"])
        if not (p.is_review or p.kind == codes.StepKind.RUN.value):
            continue
        if s["status"] != S.DONE.value:
            continue
        changed = changed_since.get(s["id"])
        if changed is None:
            stale = True
        else:
            stale = False
            for path in changed:
                if path.startswith(specs):
                    owner = procedure.owner_of(path)
                    if owner is not None and procedure.step(owner).is_judge:
                        continue
                stale = True
                break
        if stale:
            s["status"] = S.PENDING.value
            s["output_format_retries"] = 0
            reset.append(s["id"])
    return reset


def check_absolute_limits(state, limits):
    """None, or the codes.StopReason value (ABSOLUTE_LIMIT) when a cap is exceeded (§7.4).

    `limits` = {"attempts": int|None, "budget_usd": float|None, "leader_calls": int|None}
    (None = no cap yet). Called before every attempt / leader call: a cap is hit when
    the used amount has reached it (the next unit would go past it). Unknown keys are
    a ValueError (a typo must not silently drop a cap).
    """
    unknown = set(limits) - set(LIMIT_KEYS)
    if unknown:
        raise ValueError(f"unknown limit keys {sorted(unknown)}")
    totals = state.get("totals") or {}
    used = {"attempts": totals.get("attempts", 0), "budget_usd": totals.get("cost_usd", 0.0),
            "leader_calls": totals.get("leader_calls", 0)}
    for key in LIMIT_KEYS:
        cap = limits.get(key)
        if cap is None:
            continue
        if isinstance(cap, bool) or not isinstance(cap, (int, float)) or cap < 0:
            raise ValueError(f"bad limit {key}={cap!r}")
        if used[key] >= cap:
            return codes.StopReason.ABSOLUTE_LIMIT.value
    return None


def open_check(state, procedure, step_id, head, stage, now=None):
    """Stage ≥ 2: a `check` step (plan-gate / done-gate) is a leader judgment (scope §2.1, §2.2).

    The step does not run itself: it goes pending → needs_leader with the Issue stop of its
    situation (the check name), and the driver's leader turn calls the leader. The leader's
    sessions are the step's attempts (leader.call makes them, D13). Records `head` as the
    step's start_head and last_head. Returns the stop Decision.
    """
    _aligned(state, procedure)
    if isinstance(stage, bool) or not isinstance(stage, int) or stage < 2:
        raise StateError("a check step is a leader judgment only from stage 2")
    p = procedure.step(step_id)
    if p.kind != codes.StepKind.CHECK.value:
        raise StateError(f"step {step_id!r} is not a check step")
    if next_runnable(state, procedure) != step_id:
        raise StateError(f"step {step_id!r} is not the next runnable step")
    s = _sstep(state, step_id)
    s["start_head"] = head
    state["last_head"] = head
    return _stop(state, step_id, p.name, stage, now, [])


def insert_steps(state, pos, step_ids, revision):
    """Insert pending entries for `step_ids` at `pos` of state.steps and follow `revision` (§4.3).

    The one way state.steps grows: a mandatory-rule gate (rules.apply) and the stage-2 plan
    answer attaching the template (D1). Returns the inserted entries."""
    ids = list(step_ids)
    have = {s["id"] for s in state["steps"]}
    if not ids or len(set(ids)) != len(ids) or have & set(ids):
        raise StateError(f"cannot insert steps {ids} (empty, duplicate or already in state.json)")
    if isinstance(pos, bool) or not isinstance(pos, int) or not 0 <= pos <= len(state["steps"]):
        raise StateError(f"bad insert position {pos!r}")
    entries = [{"id": i, "status": S.PENDING.value, "latest_attempt": None} for i in ids]
    state["steps"][pos:pos] = entries
    state["revision"] = revision
    return entries


def follow_procedure(state, procedure):
    """Stage 3: state.steps follows a new revision that only ADDED steps (E15, E18): pending entries
    for the new ids at their places, the old entries untouched. StateError when an old step is
    gone or moved. Returns the new ids in procedure order."""
    have = {s["id"]: s for s in state["steps"]}
    if [i for i in procedure.step_ids if i in have] != [s["id"] for s in state["steps"]]:
        raise StateError("the new procedure revision lost or moved a step")
    new = [i for i in procedure.step_ids if i not in have]
    state["steps"] = [have.get(i) or {"id": i, "status": S.PENDING.value, "latest_attempt": None}
                      for i in procedure.step_ids]
    state["revision"] = procedure.revision
    return new


def reopen_step(state, step_id, note):
    """Stage 3 (coordinator decision K1): a done / skipped step goes back to pending WITHOUT being a
    return (no counter, no later step reset). Returns the log events ([] when it has not run yet)."""
    s = _sstep(state, step_id)
    events = []
    if s["status"] in (S.DONE.value, S.SKIPPED.value):
        s["output_format_retries"] = 0
        _set_status(s, S.PENDING.value, events, note=note)
    return events


def to_human(state, stage, now=None, reason=None, note=None, recommendation=None, leader_failed=None, detail=None,
             reset_at=None):
    """Stage 2: turn the current needs_leader stop into needs_human (no call / escalate / the
    leader failed / a mechanical stop of the leader session). Returns the log events.

    `reason` replaces the stop reason (a mechanical stop, absolute-limit) — the allowed answers
    follow it; otherwise the situation stays (D12). The stopped step goes needs_leader →
    needs_human. `recommendation` (D15) and `leader_failed` (D12) are recorded on the stop. Stage ≥ 4:
    `detail` / `reset_at` only when the caller gives them — an earlier infra detail of the same stop (a
    leader call that waited for its quota) is not why a human is needed now and is dropped, so a sprint
    never reruns an escalated stop by itself (H8, fail-closed).
    """
    stop = state.get("stop")
    if not stop or stop.get("status") != S.NEEDS_LEADER.value:
        raise StateError("no needs_leader stop to hand to a human")
    events = []
    step_id = stop.get("step")
    new_reason = reason or stop["reason"]
    s = _sstep(state, step_id) if step_id is not None else None
    if s is not None and s["status"] == S.NEEDS_LEADER.value:
        _set_status(s, S.NEEDS_HUMAN.value, events, code=new_reason)
    rec = stop_record(state, step_id, new_reason, stage, now,
                      note=note if note is not None else stop.get("note"), detail=detail, reset_at=reset_at)
    rec["status"] = S.NEEDS_HUMAN.value
    rec["recommendation"] = recommendation
    rec["leader_failed"] = leader_failed
    state["stop"] = rec
    f = {"step": step_id, "attempt": rec["attempt"], "to": rec["status"], "code": new_reason}
    if rec.get("note") is not None:
        f["note"] = rec["note"]
    data = {k: v for k, v in (("recommendation", recommendation), ("leader_failed", leader_failed)) if v}
    if data:
        f["data"] = data
    events.append((codes.LogEvent.STOP.value, f))
    return events


def grant_rerun(state, step_id):
    """I10: a human `rerun` answer adds one on_fail allowance (counter kept, recorded).

    §6.3: `rerun` after on_fail exceeded is once per Issue — a second grant on any step
    is a StateError. Returns the step's new on_fail_extra.
    """
    s = _sstep(state, step_id)
    if any(x.get("on_fail_extra", 0) for x in state["steps"]):
        raise StateError("rerun after on_fail exceeded is allowed once per Issue (§6.3)")
    s["on_fail_extra"] = s.get("on_fail_extra", 0) + 1
    return s["on_fail_extra"]
