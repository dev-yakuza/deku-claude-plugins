"""Issue budget (design §7.9, §7.4, §9.5) — U14.

Issue cost = sum of facts `session.cost_usd` (the conversation session's own cost is
added afterwards by U19 measurement, not here). Stage 2 (D13, L25): the leader sessions
count too — a plan-gate / done-gate session is an attempt of its check step
(runs/<step>/<n>/, facts kind `check`), a needs_leader call is <records>/leader/<k>/. Soft budget exceeded → stop SOFT_BUDGET
(stage 1: needs_human); absolute budget exceeded → stop ABSOLUTE_LIMIT at once, no leader.
Stage 1 mode is attended (Q10): soft $44.79, absolute $89.57 (defaults).
A missing cost is a measurement warning, not zero-and-silent.

U14 choices (fail-closed, see the P3-C report):
  - "exceeded" = the running total has REACHED the budget (>=), the same reading as
    statemachine.check_absolute_limits: the next attempt would only go further past it.
  - The total is recomputed from every attempt folder on disk (not added up in memory), so
    a crash between a session and the state save cannot lose a session's cost. An attempt
    folder without a readable facts.json (a crash before facts were written) or a role
    attempt whose `session.cost_usd` is null adds a warning; its cost counts as 0 — the
    warning is what tells the human the total may be low (§9.3).
  - The soft budget stops ONCE per Issue: after a human answered the soft-budget stop
    (§6.3 — `rerun` once per Issue), the driver passes `soft_acknowledged=True` and only
    the absolute budget still applies. The absolute budget is never acknowledged away.
"""

import os

from . import codes, defaults, store

_ROLE = codes.StepKind.ROLE.value
_CHECK = codes.StepKind.CHECK.value
_LEADER = codes.AttemptKind.LEADER.value     # <records>/leader/<k>/ (D13)


def _attempt_dirs(paths, state):
    """(step id, attempt n) for every numbered attempt folder of the state's steps."""
    out = []
    for s in state.get("steps") or ():
        step_dir = paths.step_dir(s["id"])
        try:
            names = os.listdir(step_dir)
        except FileNotFoundError:
            continue
        nums = sorted(int(n) for n in names if n.isdigit() and n == str(int(n)) and int(n) >= 1)
        out += [(s["id"], n) for n in nums]
    return out


def issue_cost(paths, state):
    """Sum of session costs over every attempt folder; (cost_usd, warnings).

    `warnings` = [{"fact": "cost_usd", "note": …}] for each attempt whose cost could not be
    read (no facts.json, unreadable facts.json, or a role attempt with a null cost). Corrupt
    records are reported, never guessed (the total stays a lower bound).
    """
    total = 0.0
    warnings = []
    for step_id, n in _attempt_dirs(paths, state):
        where = f"runs/{step_id}/{n}"
        try:
            facts = store.read_facts(paths, step_id, n)
        except FileNotFoundError:
            warnings.append({"fact": "cost_usd", "note": f"{where}: no facts.json (attempt did not finish)"})
            continue
        except (store.CorruptFile, store.FormatMismatch, ValueError) as e:
            warnings.append({"fact": "cost_usd", "note": f"{where}: facts.json unreadable ({e})"})
            continue
        kind = facts.get("kind")
        if kind not in (_ROLE, _CHECK):
            continue
        sess = facts.get("session")
        if kind == _CHECK and sess is None:
            continue                      # a stage-1 plan-gate (I1 machine rule): no session
        cost = (sess or {}).get("cost_usd")
        if isinstance(cost, bool) or not isinstance(cost, (int, float)) or cost < 0:
            warnings.append({"fact": "cost_usd", "note": f"{where}: session cost not recorded"})
            continue
        total += float(cost)
    for k in _leader_dirs(paths):
        where = f"{_LEADER}/{k}"
        path = paths.leader_file(k, "facts.json")
        try:
            facts = store._read_json(paths, path, "facts", "facts")
        except FileNotFoundError:
            warnings.append({"fact": "cost_usd", "note": f"{where}: no facts.json (leader session did not finish)"})
            continue
        except (store.CorruptFile, store.FormatMismatch, ValueError) as e:
            warnings.append({"fact": "cost_usd", "note": f"{where}: facts.json unreadable ({e})"})
            continue
        cost = (facts.get("session") or {}).get("cost_usd")
        if isinstance(cost, bool) or not isinstance(cost, (int, float)) or cost < 0:
            warnings.append({"fact": "cost_usd", "note": f"{where}: session cost not recorded"})
            continue
        total += float(cost)
    return round(total, 6), warnings


def _leader_dirs(paths):
    """k of every numbered <records>/leader/<k>/ folder (stage-2 needs_leader calls, D13)."""
    try:
        names = os.listdir(paths.leader_root)
    except FileNotFoundError:
        return []
    return sorted(int(n) for n in names if n.isdigit() and n == str(int(n)) and int(n) >= 1)


def _budgets(mode):
    if mode not in codes.RunMode.values():
        raise ValueError(f"unknown run mode {mode!r}")
    return defaults.SOFT_BUDGET_USD[mode], defaults.ABSOLUTE_BUDGET_USD[mode]


def check(state, mode, soft_acknowledged=False):
    """None, or the codes.StopReason value (SOFT_BUDGET / ABSOLUTE_LIMIT) for the current total.

    Reads `state.totals.cost_usd` (the driver refreshes it from issue_cost before every
    attempt). The absolute budget wins over the soft one.
    """
    soft, absolute = _budgets(mode)
    cost = (state.get("totals") or {}).get("cost_usd", 0.0)
    if isinstance(cost, bool) or not isinstance(cost, (int, float)) or cost < 0:
        raise ValueError(f"bad totals.cost_usd {cost!r}")
    if cost >= absolute:
        return codes.StopReason.ABSOLUTE_LIMIT.value
    if cost >= soft and not soft_acknowledged:
        return codes.StopReason.SOFT_BUDGET.value
    return None


def refresh(paths, state):
    """Recompute totals.cost_usd in `state` (in memory); return the cost warnings."""
    cost, warnings = issue_cost(paths, state)
    totals = state.setdefault("totals", {})
    totals["cost_usd"] = cost
    return warnings
