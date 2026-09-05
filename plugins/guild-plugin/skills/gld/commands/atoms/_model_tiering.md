# MODEL TIERING (shared contract — dynamic tier escalation/de-escalation)

**Not a stage.** Defines Guild's model-tier policy (mechanical → Haiku, stage execution → Sonnet, hard judgments → Opus) with two dynamic mechanisms on top of the static per-role/per-task defaults already stated in each command file: (A) **immediate escalation** on a genuine execute-stage loop-back, local to one stage invocation, no persistence; (B) **default-tier review**, a periodic evolve-driven HITL proposal, symmetric with rule HR (`evolve.md` Phase 2 item "rule performance"). Read by `implement.md`/`debug.md`/`refactor.md` Step 4 and by `evolve.md` Phase 2.5/Phase 2.

The ladder: **haiku** (frugal — mechanical reads) < **sonnet** (standard — the default for nearly every role spawn today) < **opus** (frontier — hard judgment / an escalated retry). Guild has no tier above Opus and no per-repo persisted "trust" state (unlike a full runtime router) — both mechanisms below are deliberately simple: one bumps a single retry, the other is a human-approved proposal, not silent code.

---

## Section A — Escalation on genuine retry (mechanical, local, no persistence)

Wired at `implement.md`/`debug.md`/`refactor.md` Step 4, **after** the stagnation guard (`_stagnation.md`) has already run and did **not** fire (i.e. this loop-back's reason genuinely differs from the prior attempt's — real, distinct feedback to act on, not a stall):

- **Attempt 1** always runs at the stage's stated default (sonnet, per the command file). Trust the default first — do not escalate pre-emptively.
- **Attempt 2** (the retry within the bounded ~2-loop cap) runs **one tier above the default** for **every** role re-invoked in that retry — no exceptions and no narrower list: the developer, the tech-lead (whose conformance verdict must be about the redone diff, so it is always re-run), and **every 3.5b specialist/gate role the redone diff matches** — not only the one whose `BLOCKED` triggered the loop-back, since `_execute_spine.md` Step 4's chain rule re-derives that cast from the new diff and a redo can newly warrant a role that did not match before. The re-check must never be weaker than the redo. **The execute-stage external auditor re-scans on every loop-back** (`_execute_spine.md` Step 3.5a — not only ones it triggered), and its re-scan is bumped the same way — it has no persona and no default of its own to change, it simply re-runs one tier up for that retry. Sonnet → **Opus**. If a role's default was already Opus, it stays at Opus (no higher tier; this is not a failure).
- This is a **single-step, one-time bump for that retry only** — it does not compound across multiple loop-backs beyond the existing numeric cap, and it never persists past this stage invocation (the next Issue's execute stage starts back at the default).
- **Rationale**: attempt 1 failed for a real, distinct reason (not a repeat — the stagnation guard already ruled that out); giving the one bounded retry more capability is worth the one-time cost, and the ~2-loop cap already bounds total spend regardless.

State the escalation plainly in the re-invocation prompt/RESULT narration (e.g. "retry at opus — attempt 1 flagged `<reason>`") so it is auditable, not silent.

## Section B — Ground-truth tag (piggybacks the existing capture, no new event)

When Section A escalates a retry, tag the **same** ground-truth capture the loop-back already makes (`_signals.md` Section C) with `--escalated`. ⚠ Section A only fires *after* the stagnation guard did **not** fire, so the capture being tagged here is always a `correction` or a `verify-gap` — **never a `stagnation`**: a stagnant loop-back escalates to the human instead of retrying, so no tier was ever bumped and `--escalated` is dropped there (`_stagnation.md` Section C and `implement.md` Step 4 already state this; listing `stagnation` in the `--kind` set below would be a branch that can never be taken).
```bash
python3 <<SKILL_DIR>>/commands/atoms/capture_signal.py --kind <correction|verify-gap> --issue <N> --stage execute --role <role> --area "<area>" --summary "<...>" --evidence "<...>" --surprise --escalated
```
Substitute the **literal** Issue number for `<N>` (and every other `<…>`) before the Bash call — `_bash_rules.md` item 9. No new signal kind, no new capture point — `escalated` is one boolean field riding the loop-back entry that already exists. This is the only data Section C's evolve review needs; it costs nothing beyond a flag on a write that was happening anyway.

## Section C — Default-tier review (evolve-driven, periodic, HITL — symmetric with rule HR)

`evolve.md` Phase 2.5 computes a **model-tier scorecard** per role+stage from the ground-truth log alone (no new scan atom): among that role/stage's loop-back entries in recent cycles, what fraction carried `--escalated`? ⚠ Count only entries from loop-backs that **actually retried** (`--kind correction`/`verify-gap`) — a `stagnation` entry never retried and so can never carry the flag (Section B); leaving those in the denominator would deflate every escalation rate. Phase 2 then proposes, **needs a consistent trend across ≥3 cycles, never off one run**. ⚠ This ≥3-cycle bar is *stricter than*, not identical to, the base Axis-2 trend-unlock (`_data_sufficiency.md` Section A: `trend` at ≥1 prior run / a 2-point trend) — that base gate only decides whether trend-dependent outputs run *at all*; a 2-point trend is too noisy for a specific tier-change proposal like this one, so model-tier HR (and rule HR, symmetrically) additionally require ≥3 cycles of a **consistent** pattern before proposing:

- **Frequently escalated** (a role/stage combo needed the Opus bump across most recent loop-backs) → propose **raising that role's stated default** in the relevant command file / `.claude/agents/<role>.md` from sonnet to opus. Rationale: the retry tier is doing the real work most of the time anyway — starting there avoids the loop-back cost entirely.
- **Never escalated** across many cycles → this only **confirms** the current default is adequate; it is evidence, not by itself a reason to *lower* an already-sonnet default (there is nothing cheaper the current spine uses for role spawns except haiku, which is reserved for mechanical/non-judgment work — do not propose moving a judgment role to haiku on clean-run evidence alone).
- Applied via the **normal HITL pipeline** (Phase 5 per-item approval) — a stated-default change is low-risk and reversible (INV3), but it is still a proposal, never a silent edit.
- ⚠ **Never propose a tier change for the execute-stage external auditor** (`_execute_spine.md` Step 3.5a). It is not a roster role (`_handoff.md` Section G), has no `.claude/agents/*.md` to edit, and its escalation is per-retry only (Section A). It also must never be counted in a *role's* escalation rate — its `--role auditor` captures are deliberately capped to `BLOCKER`-and-acted-on entries (`_execute_spine.md` Step 4), so its rate is not comparable to a spine role's and would skew any scorecard it were folded into.
- ⚠ **Never propose a tier change for `leader`.** The leader is not spawned as a sub-agent — the main session *embodies* it by loading `.claude/agents/leader.md` as a persona (`dev.md` Phase 0, and `leader.md`'s own description says so). Loading a file as a persona does not switch models, so that file's `model:` frontmatter is **inert**: the leader always runs at whatever tier the main session is running at, which Guild does not control. A "raise the leader to opus" proposal would edit a field nothing reads, and would then read as applied-and-working in the ledger. The field is kept only so the roster's frontmatter is uniform. The same applies to any future role the main session embodies rather than spawns.

## Hard rules
- **Never escalates on attempt 1** — the default is trusted first.
- **Never escalates past Opus** and never introduces a tier the harness doesn't have.
- **Never persists an escalation past its one retry** — Section A carries no state between stage invocations; only Section C (evolve, HITL) can change a *default*.
- **De-escalating a role's default below its current tier requires the same trend evidence in the opposite direction plus explicit human approval** — never automatic, never from a single clean run (avoids oscillation).
- **Does not touch gate roles' pass/fail criteria** — escalation changes which model reviews, never what the review is allowed to approve (INV2 is untouched).
