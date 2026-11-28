"""Model / effort layers and the retry raise (stage 3 — §7.9, E26–E29, R1-38).

Fixed by the stage-3 contract change (V1, Q2); bodies by session C (V11). Signatures and the
rules in these docstrings are the contract between C and B2 — change them only through README
"Changing a contract". Every function is pure.

Layer L1; imports only L0 modules.

Layers, lowest first: 1 plugin default (defaults.model_effort_table) · 4 plan-gate
`plan.models` · 5 `rerun.session` (both in `state.model_overrides`; the later one overwrites)
· 6 the raise below, on top of that base. Layers 2–3 are stage 6.
"""

from . import codes, defaults

EFFORT_CHANGE_RESUMES = True
"""E27: does an effort-only change keep the developer's --resume? V18 measured that a resumed
session sends the changed effort (stage3/experiments/V18.md §5: the session record's
api-request output_config.effort, the Bash env and the hook input all follow --effort; neither
system/init nor the result shows the value). Coordinator decision Z3: yes - an effort-only raise
keeps --resume; a model change is always a new session. The only place to flip."""


class LadderError(ValueError):
    """A base model / effort that is not on the repository's ladder."""


def _ladder(rungs, allowed, what):
    allowed = list(allowed)
    unknown = [x for x in allowed if x not in rungs]
    if unknown:
        raise LadderError(f"{what} {unknown[0]!r} is not a known name ({', '.join(rungs)})")
    return tuple(x for x in rungs if x in allowed)


def effort_ladder(allowed_efforts):
    """defaults.EFFORT_LADDER without the rungs outside `allowed_efforts`, lowest first."""
    return _ladder(defaults.EFFORT_LADDER, allowed_efforts, "effort")


def model_ladder(allowed_models):
    """defaults.MODEL_LADDER without the rungs outside `allowed_models`, lowest first."""
    return _ladder(defaults.MODEL_LADDER, allowed_models, "model")


def raisable(step):
    """E26-2: True for a role step without `checks` (a review, run, check or op step never)."""
    return step.kind == codes.StepKind.ROLE.value and not step.checks


def base_choice(step, stage, overrides):
    """{"model", "effort", "layer"} (layer = codes.ModelLayer value) of a role step.

    `overrides` = state.model_overrides ({step id: {"model", "effort", "layer", "reason"}});
    without one: defaults.model_effort_table(stage) by "<role>/review" (a step with checks) or
    "<role>/<step id>", then "<role>". No key → LadderError (the driver refuses, as today)."""
    if step.kind != codes.StepKind.ROLE.value:
        raise LadderError(f"step {step.id!r} is not a role step — it has no model")
    table = defaults.model_effort_table(stage)
    o = (overrides or {}).get(step.id)
    if o is not None:
        if o["layer"] not in (codes.ModelLayer.PLAN.value, codes.ModelLayer.LEADER.value):
            raise LadderError(f"step {step.id!r}: an override of layer {o['layer']!r}")
        return {"model": o["model"], "effort": o["effort"], "layer": str(o["layer"])}
    for key in (f"{step.name}/review" if step.checks else f"{step.name}/{step.id}", step.name):
        if key in table:
            model, effort = table[key]
            return {"model": model, "effort": effort, "layer": codes.ModelLayer.PLUGIN_DEFAULT.value}
    raise LadderError(f"no §7.9 model/effort default for role {step.name!r} (step {step.id!r})")


def _next(ladder, rung, what):
    """The rung above, or None at the end. A rung that is not on the ladder → LadderError."""
    if rung not in ladder:
        raise LadderError(f"{what} {rung!r} is outside the allow-list ({', '.join(ladder) or 'empty'}) (§7.8)")
    i = ladder.index(rung) + 1
    return ladder[i] if i < len(ladder) else None


def raised(base, returns, allowed_models, allowed_efforts):
    """E26: the session choice after `returns` returns (state.steps[].returns).

    Returns {"model", "effort", "escalation"} with escalation = {"base": base, "returns",
    "raised": {"effort": [from, to] | None, "model": [from, to] | None}, "capped": bool} — the
    brief / facts `session.escalation` object. returns < RAISE_EFFORT_AT: the base. ≥
    RAISE_EFFORT_AT: effort + 1. ≥ RAISE_MODEL_AT: model + 1 too. No rung left: that part stays
    and capped is True (never a stop — R1-38). A base outside the ladders → LadderError."""
    if isinstance(returns, bool) or not isinstance(returns, int) or returns < 0:
        raise ValueError(f"returns must be a count, got {returns!r}")
    up = {"effort": _next(effort_ladder(allowed_efforts), base["effort"], "effort"),
          "model": _next(model_ladder(allowed_models), base["model"], "model")}
    due = {"effort": returns >= defaults.RAISE_EFFORT_AT, "model": returns >= defaults.RAISE_MODEL_AT}
    out = {"model": base["model"], "effort": base["effort"]}
    moved, capped = {"effort": None, "model": None}, False
    for part in ("effort", "model"):
        if not due[part]:
            continue
        if up[part] is None:
            capped = True
            continue
        moved[part] = [base[part], up[part]]
        out[part] = up[part]
    out["escalation"] = {"base": {k: base[k] for k in ("model", "effort", "layer")}, "returns": returns,
                         "raised": moved, "capped": capped}
    return out


def count_return(state_step, cause, sources=()):
    """Record a return to this step (the TARGET): `returns` + 1, and `return_sources` =
    [{"step", "attempt", "cause"}] for `sources` = [(step id, attempt)] — the attempts whose
    findings the next attempt's failure-summary.md carries (review-q0 D8). Changes the dict in
    place. `cause` = codes.ReturnCause value (ValueError otherwise)."""
    cause = getattr(cause, "value", cause)
    if cause not in codes.ReturnCause.values():
        raise ValueError(f"unknown return cause {cause!r}")
    rows = []
    for step, attempt in sources:
        if not isinstance(step, str) or not step or isinstance(attempt, bool) or not isinstance(attempt, int) \
                or attempt < 1:
            raise ValueError(f"bad return source {(step, attempt)!r}")
        rows.append({"step": step, "attempt": attempt, "cause": cause})
    state_step["returns"] = state_step.get("returns", 0) + 1
    state_step["return_sources"] = rows


def may_resume(previous, chosen):
    """E27: may a developer --resume carry over from `previous` to `chosen` ({"model",
    "effort"})? A model change never. An effort-only change: as V18 measured (False until then)."""
    if not previous or not chosen:
        return False
    for part in ("model", "effort"):
        if not previous.get(part) or not chosen.get(part):
            return False
    if previous["model"] != chosen["model"]:
        return False
    return previous["effort"] == chosen["effort"] or EFFORT_CHANGE_RESUMES
