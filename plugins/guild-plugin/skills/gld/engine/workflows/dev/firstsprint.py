"""workflows.dev.firstsprint — the §10.4 first-sprint SETTINGS (the mode itself: `predict.first_sprint`).

While first-sprint mode is on (`config.engine.first_sprint_mode` on, or auto with no recorded go):

    confirm_interpretation(p)   attended KICKOFF asks the interpretation-surface question (as
                                `attended_confirm_interpretation: true`) — predict-first (KICKOFF is high-risk)
    no_dismiss(p)               unattended EX-ARB BLOCKER/MAJOR dismiss/dispute → accept, `coerced_by: first-sprint`,
                                `raw_choice` names `would-dismiss` (graded as EX-ARB:dismiss, §9.5). After the go the
                                `exarb.no_unattended_dismiss` valve carries it (`predict.go_recorded` sets it in the
                                `auto` area; only a person releases it) → `coerced_by: valve`
    handoff_shadow(p)           HANDOFF is judged at every boundary as a SHADOW (`handoff.shadow`: recorded as
                                `HANDOFF-SHADOW`, cost kind `monitoring`, never changes the flow); live HANDOFF stays in its
                                configured mode
    assumption_pauses(p)        a LIVE HANDOFF `ok_with_assumption` on an analyze/design artifact gap is a person's
                                `ambiguity:` (not a recorded assumption)

The unverified groups of §10.2-6 (their conservative path) are not here: the list comes from the K6 replay.
"""

from workflows.dev import predict as PF


def on(p):
    try:
        return bool(PF.first_sprint(p))
    except Exception:                                            # noqa: BLE001 — unknown = on (the conservative side)
        return True


def confirm_interpretation(p):
    # K5r5-M3: a conservative KICKOFF (§9.5 count rule) confirms the interpretation with a person too
    return bool(p.engine_cfg("attended_confirm_interpretation", False)) or on(p) or PF.conservative(p, "KICKOFF")


def no_dismiss(p, attended=False):
    """None | 'first-sprint' | 'valve' | 'conservative' — why a BLOCKER/MAJOR dismiss is forced to accept. Unattended:
    first-sprint mode, the `exarb.no_unattended_dismiss` valve, or (K5r5-M3) `group.EX-ARB-dismiss.conservative`;
    attended: the conservative path only (EX-ARB's conservative side — §9.5 rule 2) — the valve, or (K6 item 4) the
    §10.2-6 unverified EX-ARB-dismiss, released by the person's verdicts on these would-dismiss decisions on the
    grading sheet (K6 r1 M6, `unverified.SHEET_RELEASED`)."""
    if not attended:
        if on(p):
            return "first-sprint"
        v = p.engine_cfg("exarb_no_unattended_dismiss", None)
        if v is True or str(v).lower() == "true":
            return "valve"
    if PF.conservative(p, "EX-ARB:dismiss"):
        return "conservative"
    return None


def handoff_shadow(p):
    return on(p) and p.engine_cfg("handoff_judge", "default") != "always"   # always: the live call judges anyway


def assumption_pauses(p):
    return on(p)
