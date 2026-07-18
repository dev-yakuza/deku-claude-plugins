# MODEL TIERING (shared contract — dynamic tier escalation/de-escalation)

**Not a stage.** Operationalizes SKILL.md's "Model tiering" policy (mechanical → Haiku, stage execution → Sonnet, hard judgments → Opus) with two dynamic mechanisms on top of the static per-role/per-task defaults already stated in each command file: (A) **immediate escalation** on a genuine execute-stage loop-back, local to one stage invocation, no persistence; (B) **default-tier review**, a periodic evolve-driven HITL proposal, symmetric with rule HR (`evolve.md` Phase 2 item "rule performance"). Read by `implement.md`/`debug.md`/`refactor.md` Step 4 and by `evolve.md` Phase 2.5/Phase 2.

The ladder: **haiku** (frugal — mechanical reads) < **sonnet** (standard — the default for nearly every role spawn today) < **opus** (frontier — hard judgment / an escalated retry). Guild has no tier above Opus and no per-repo persisted "trust" state (unlike a full runtime router) — both mechanisms below are deliberately simple: one bumps a single retry, the other is a human-approved proposal, not silent code.

---

## Section A — Escalation on genuine retry (mechanical, local, no persistence)

Wired at `implement.md`/`debug.md`/`refactor.md` Step 4, **after** the stagnation guard (`_stagnation.md`) has already run and did **not** fire (i.e. this loop-back's reason genuinely differs from the prior attempt's — real, distinct feedback to act on, not a stall):

- **Attempt 1** always runs at the stage's stated default (sonnet, per the command file). Trust the default first — do not escalate pre-emptively.
- **Attempt 2** (the retry within the bounded ~2-loop cap) runs **one tier above the default** for every role re-invoked in that retry — the developer **and** the tech-lead/gate role whose `BLOCKED` triggered the loop-back, so the re-check isn't weaker than the redo. Sonnet → **Opus**. If a role's default was already Opus, it stays at Opus (no higher tier; this is not a failure).
- This is a **single-step, one-time bump for that retry only** — it does not compound across multiple loop-backs beyond the existing numeric cap, and it never persists past this stage invocation (the next Issue's execute stage starts back at the default).
- **Rationale**: attempt 1 failed for a real, distinct reason (not a repeat — the stagnation guard already ruled that out); giving the one bounded retry more capability is worth the one-time cost, and the ~2-loop cap already bounds total spend regardless.

State the escalation plainly in the re-invocation prompt/RESULT narration (e.g. "retry at opus — attempt 1 flagged `<reason>`") so it is auditable, not silent.

## Section B — Ground-truth tag (piggybacks the existing capture, no new event)

When Section A escalates a retry, tag the **same** ground-truth capture the loop-back already makes (`_signals.md` Section C — `correction`/`verify-gap`/`stagnation`) with `--escalated`:
```bash
python3 <<SKILL_DIR>>/commands/atoms/capture_signal.py --kind <correction|verify-gap|stagnation> --issue $1 --stage execute --role <role> --area "<area>" --summary "<...>" --evidence "<...>" --surprise --escalated
```
No new signal kind, no new capture point — `escalated` is one boolean field riding the loop-back entry that already exists. This is the only data Section C's evolve review needs; it costs nothing beyond a flag on a write that was happening anyway.

## Section C — Default-tier review (evolve-driven, periodic, HITL — symmetric with rule HR)

`evolve.md` Phase 2.5 computes a **model-tier scorecard** per role+stage from the ground-truth log alone (no new scan atom): among that role/stage's loop-back entries in recent cycles, what fraction carried `--escalated`? Phase 2 then proposes, **needs a trend (≥3 cycles, never off one run — same Axis-2 gate as rule HR)**:

- **Frequently escalated** (a role/stage combo needed the Opus bump across most recent loop-backs) → propose **raising that role's stated default** in the relevant command file / `.claude/agents/<role>.md` from sonnet to opus. Rationale: the retry tier is doing the real work most of the time anyway — starting there avoids the loop-back cost entirely.
- **Never escalated** across many cycles → this only **confirms** the current default is adequate; it is evidence, not by itself a reason to *lower* an already-sonnet default (there is nothing cheaper the current spine uses for role spawns except haiku, which is reserved for mechanical/non-judgment work — do not propose moving a judgment role to haiku on clean-run evidence alone).
- Applied via the **normal HITL pipeline** (Phase 5 per-item approval) — a stated-default change is low-risk and reversible (INV3), but it is still a proposal, never a silent edit.

## Hard rules
- **Never escalates on attempt 1** — the default is trusted first.
- **Never escalates past Opus** and never introduces a tier the harness doesn't have.
- **Never persists an escalation past its one retry** — Section A carries no state between stage invocations; only Section C (evolve, HITL) can change a *default*.
- **De-escalating a role's default below its current tier requires the same trend evidence in the opposite direction plus explicit human approval** — never automatic, never from a single clean run (avoids oscillation).
- **Does not touch gate roles' pass/fail criteria** — escalation changes which model reviews, never what the review is allowed to approve (INV2 is untouched).
