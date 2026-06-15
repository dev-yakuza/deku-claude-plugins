# TEST

**Stage 4: Testing — thin wrapper.**

Arch B (v1.0.0): this file runs in the **main session** and spawns ONE `stage_test` sub-agent that does all the work (test work + 3-or-4 reviewers serial + retry loop + `/verify` Skill + escalation gates). Main session parses the sub-agent's `>>> RESULT <<<` line, handles label transitions, and runs the user-interactive prompts (Continue/Pause/Stop on escalation; Pass/Fail on manual QA; framework choice on missing E2E setup).

QA verification + integration E2E for parent Issues. Unit/UI tests and E2E tests for single/child Issues were already done in Stage 3 (implement); this stage validates them, adds the QA gate, and triggers final label transition to `sdd:done`.

> **Bash Command Execution**: see `<<SKILL_DIR>>/commands/atoms/_bash_rules.md`.

## Input Validation

Validate `$1` per Common Definitions → Issue Validation in `<<SKILL_DIR>>/SKILL.md`. If `$1` is a Pull Request, stop without making changes.

## Direct-invocation label check (per `design/01-sub-agent-contract.md` §11)

For direct `/sdd test <N>` invocation (not via `/sdd resume` / `/sdd auto` / `/sdd batch`), verify the Issue's current SDD lifecycle label matches this stage. Read labels:

```bash
gh issue view $1 --json labels --jq '[.labels[].name]'
```

- Labels contain `sdd:test` → continue.
- Labels contain `sdd:analyze` / `sdd:design` / `sdd:implement` / `sdd:done` → refuse:
  > Issue #$1 is currently at `sdd:<current>`. Use `/sdd resume $1` for correct stage dispatch.

  Stop without making changes.
- Labels contain no `sdd:*` lifecycle label → refuse with the same message (Issue must have reached `sdd:test` via implement to enter test stage).

(When this file is read-and-executed inline from `/sdd resume`, bootstrap has already validated the stage — but the label check above is idempotent and cheap, so it stays.)

## Phase 0: Depth detection (for sub-agent prompt)

From the same labels read above, derive the depth dial:
- Contains `sdd:review:deep` → `depth = deep`
- Contains `sdd:review:shallow` → `depth = shallow`
- Otherwise → `depth = default`

## Phase 1: Spawn stage_test

Spawn ONE sub-agent via the Agent tool:

- `subagent_type`: `general-purpose`
- `model`: `opus` (the stage's work logic + all reviewers run in this single sub-agent context)
- `description`: `stage_test for #$1`
- `prompt`:
  > Read `<<SKILL_DIR>>/commands/atoms/stage_test.md` and execute its instructions for Issue #$1.
  >
  > Inputs:
  >   Issue: #$1
  >   Depth: <dial>      (substitute the literal value from Phase 0: `default` / `deep` / `shallow`)
  >   Resume: none
  >
  > Return EXACTLY one line per the contract in stage_test.md, prefixed by the `>>> RESULT <<<` marker line.

(Substitute `<dial>` with the literal Phase 0 value. Do NOT pass through the literal placeholder.)

## Phase 2: Parse sub-agent return

Parse the `>>> RESULT <<<` line. Branch on status:

### `OK DONE`

Sub-agent already transitioned label to `sdd:done` and closed the Issue (and ran child completion notification if applicable). Report to user:
> Issue #$1 complete. Labelled `sdd:done` and closed. Test output + reviews remain on the Issue/PR for reference.

Stop. (No further stage — test is the terminal stage.)

### `OK BACK_TO_IMPLEMENT`

QA failure: user reported manual QA item(s) failed. Sub-agent left label as `sdd:test` (no transition). Report to user:
> Manual QA failed. Run `/sdd implement $1` for a TDD bug-fix cycle, then re-run `/sdd test $1` (or `/sdd resume $1`).

Stop.

### `OK NEEDS_MANUAL_QA: <summary>`

Sub-agent finished AI reviews + `/verify` and is waiting on the user manual-QA gate (skip-review.qa is OFF).

1. Render `<summary>` verbatim to the user (includes path, reviewer verdicts, /verify evidence, E2E_SKIPPED flag if any, link to the QA checklist comment).

2. Call `AskUserQuestion` with 3 options:
   - **Yes** — all manual QA items passed.
   - **No** — at least one manual QA item failed.
   - **Skip** — treat as Yes (user opts to skip manual verification).

3. Branch on user choice:
   - **Yes** or **Skip** → re-spawn `stage_test` with `Resume: qa-approved`:
     - `subagent_type`: `general-purpose`, `model`: `opus`, `description`: `stage_test qa-approved for #$1`
     - `prompt`:
       > Read `<<SKILL_DIR>>/commands/atoms/stage_test.md` and execute its instructions for Issue #$1.
       >
       > Inputs:
       >   Issue: #$1
       >   Depth: <dial>
       >   Resume: qa-approved
       >
       > Return EXACTLY one line per the contract, prefixed by `>>> RESULT <<<`.
     - Parse the re-spawn's return — should be `OK DONE` (success branch) or `FAIL:` (label transition error). Loop into the corresponding branch above.
   - **No** → re-spawn `stage_test` with `Resume: qa-failed`:
     - Same prompt shape with `Resume: qa-failed`.
     - Parse the re-spawn's return — should be `OK BACK_TO_IMPLEMENT` or `FAIL:`. Loop into the corresponding branch.

### `OK NEEDS_FRAMEWORK_CHOICE: recommended=<name>`

Sub-agent (PARENT path) detected no E2E test setup and is surfacing a framework recommendation.

1. Surface the recommendation verbatim to the user:
   > No E2E test setup detected. Recommended framework: `<name>`.

2. Call `AskUserQuestion` with 3 options:
   - **Yes** — use the recommended framework `<name>`.
   - **Choose other** — open-ended; ask the user to type a framework name (e.g. `cypress`, `playwright`, `pytest-bdd`, `jest`, etc.).
   - **Skip** — abort integration testing (treated as `FAIL: user declined to choose a framework`; stop).

3. Branch on user choice:
   - **Yes** → re-spawn with `Framework: <name>`.
   - **Choose other** → ask user for the literal framework name, then re-spawn with `Framework: <user-supplied-name>`.
   - **Skip** → report "User declined framework choice; cannot proceed with PARENT integration testing." Stop.

4. Re-spawn prompt:
   - `subagent_type`: `general-purpose`, `model`: `opus`, `description`: `stage_test framework=<choice> for #$1`
   - `prompt`:
     > Read `<<SKILL_DIR>>/commands/atoms/stage_test.md` and execute its instructions for Issue #$1.
     >
     > Inputs:
     >   Issue: #$1
     >   Depth: <dial>
     >   Resume: none
     >   Framework: <choice>
     >
     > Return EXACTLY one line per the contract, prefixed by `>>> RESULT <<<`.

5. Parse the re-spawn's return — should be one of `OK DONE`, `OK BACK_TO_IMPLEMENT`, `OK NEEDS_MANUAL_QA: <summary>`, `ESCALATE: <summary>`, or `FAIL:`. Loop into the corresponding branch above.

### `OK PAUSE`

(Rare — emitted only after a Pause-then-Resume cycle.) Report to user:
> Paused. Resume with `/sdd resume $1`.

Stop.

### `ESCALATE: <summary>`

Round 3 AI review FAIL with skip-review.qa OFF.

1. Render `<summary>` verbatim to the user.

2. Call `AskUserQuestion` with 3 options: `Continue`, `Pause`, `Stop`.

3. Branch on user choice:
   - **Continue** → re-spawn `stage_test` with `Resume: continue-after-escalation`:
     - `subagent_type`: `general-purpose`, `model`: `opus`, `description`: `stage_test resume for #$1`
     - `prompt`:
       > Read `<<SKILL_DIR>>/commands/atoms/stage_test.md` and execute its instructions for Issue #$1.
       >
       > Inputs:
       >   Issue: #$1
       >   Depth: <dial>
       >   Resume: continue-after-escalation
       >
       > Return EXACTLY one line per the contract, prefixed by `>>> RESULT <<<`.
     - Parse the re-spawn's return (typically `OK NEEDS_MANUAL_QA: <summary>` for SINGLE/CHILD, or `OK DONE` if PARENT path auto-approved under skip-review.qa, or `FAIL:`). Loop into the corresponding branch.
   - **Pause** → report "Resume later with `/sdd resume $1`." Stop.
   - **Stop** → exit cleanly.

### `FAIL: <reason>`

Report `<reason>` to the user. Stop.

### Unknown / malformed

Treat as `FAIL: unexpected return: <line>` and stop. (Defensive per `design/01-sub-agent-contract.md` §9.)

## Notes

- **AI review always runs.** `skip-review: qa` skips only the user-facing manual QA gate and the Round 3 interactive escalation — `stage_test` always executes Phases 1-2 internally. Phase 2.5 escalation (inside the sub-agent) still triggers on Round 3 FAIL, but skip-review auto-continues it (sub-agent proceeds to Phase 2.7 / Phase 3 instead of returning `ESCALATE`). Findings remain on the Issue/PR for human follow-up.
- **At most 2 sub-agent spawns per invocation under normal flow** (1 initial + 1 for QA resolution OR escalation continue OR framework choice). A pathological case combining escalation → manual-QA → framework re-spawn could reach 3 spawns; each return is independent and main loops through the corresponding branch.
- **`/verify` Skill runs inside the sub-agent.** Main session does NOT invoke `/verify` directly — it lives in `stage_test.md` §7 Phase 2.7. Graceful-skip on Skill unavailability is handled inside the sub-agent.
- **Reviewers run serially inside the sub-agent.** Reviewer independence is preserved by the sub-agent's internal narrative structure (re-fetch the test output for each reviewer; no cross-visibility of verdicts). PARENT path runs 4 reviewers (3 SDD + `parent_integration_review`); SINGLE/CHILD runs 3.
- **Label transitions and Issue close are sub-agent responsibilities** (different from analyze/design/implement). `stage_test` §9 success branch transitions `sdd:test → sdd:done` and runs `gh issue close $1` directly inside the sub-agent context — main does NOT re-transition. This is the only stage where the sub-agent sets labels.
- **Child completion notification runs inside the sub-agent** (`stage_test.md` §10 Phase 5). Multilingual parent regex per `_multilingual.md`. Same logic as `implement.md` Phase 7.
- **Depth label override**: `sdd:review:deep` / `sdd:review:shallow` selects the depth dial, which the sub-agent uses for model selection internally per `_review_helpers.md` Section A.2. `test_work`-style reasoning is always opus regardless of depth.
- **Test is the terminal stage.** There is no next-stage skip-review to consult in this wrapper; `skip-review: qa` is consumed entirely by the sub-agent.
