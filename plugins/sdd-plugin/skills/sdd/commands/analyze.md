# ANALYZE

**Stage 1: Requirements Analysis (What / Why) — thin wrapper.**

Arch B (v1.0.0): this file runs in the **main session** and spawns ONE `stage_analyze` sub-agent that does all the work (analysis + 3 reviewers serial + retry loop + escalation). Main session parses the sub-agent's `>>> RESULT <<<` line and handles label transitions + user prompts.

Focus ONLY on What and Why. Do NOT discuss How.

> **Bash Command Execution**: see `<<SKILL_DIR>>/commands/atoms/_bash_rules.md`.

## Input Validation

Validate `$1` per Common Definitions → Issue Validation in `<<SKILL_DIR>>/SKILL.md`. If `$1` is a Pull Request, stop without making changes.

## Direct-invocation label check (per `design/01-sub-agent-contract.md` §11)

For direct `/sdd analyze <N>` invocation (not via `/sdd resume` / `/sdd auto` / `/sdd batch`), verify the Issue's current SDD lifecycle label matches this stage. Read labels:

```bash
gh issue view $1 --json labels --jq '[.labels[].name]'
```

- Labels contain no `sdd:*` lifecycle label OR contain `sdd:analyze` → continue.
- Labels contain `sdd:design` / `sdd:implement` / `sdd:test` / `sdd:done` → refuse:
  > Issue #$1 is currently at `sdd:<current>`. Use `/sdd resume $1` for correct stage dispatch.

  Stop without making changes.

(When this file is read-and-executed inline from `/sdd resume`, bootstrap has already validated the stage — but the label check above is idempotent and cheap, so it stays.)

## Phase 0: Depth detection (for sub-agent prompt)

From the same labels read above, derive the depth dial:
- Contains `sdd:review:deep` → `depth = deep`
- Contains `sdd:review:shallow` → `depth = shallow`
- Otherwise → `depth = default`

## Phase 1: Spawn stage_analyze

Spawn ONE sub-agent via the Agent tool:

- `subagent_type`: `general-purpose`
- `model`: `opus` (the stage's work logic runs in the sub-agent context; reviewer logic also inlined here)
- `description`: `stage_analyze for #$1`
- `prompt`:
  > Read `<<SKILL_DIR>>/commands/atoms/stage_analyze.md` and execute its instructions for Issue #$1.
  >
  > Inputs:
  >   Issue: #$1
  >   Depth: <dial>      (substitute the literal value from Phase 0: `default` / `deep` / `shallow`)
  >   Resume: none
  >
  > Return EXACTLY one line per the contract in stage_analyze.md, prefixed by the `>>> RESULT <<<` marker line.

(Substitute `<dial>` with the literal Phase 0 value. Do NOT pass through the literal placeholder.)

## Phase 2: Parse sub-agent return

Parse the `>>> RESULT <<<` line. Branch on status:

### `OK ADVANCE: design`
1. Update label:
   ```bash
   gh issue edit $1 --remove-label "sdd:analyze" --add-label "sdd:design"
   ```
   (If the Issue had no `sdd:analyze` label yet — fresh entry — the `--remove-label` is a no-op; that's fine.)
2. Check skip-review setting (Common Definitions → Skip Review Setting in `SKILL.md`). Read `.github/.sdd-config` and parse the `skip-review:` line.
3. If `design` is in skip-review:
   - **Read + execute inline** (do NOT spawn a sub-agent here — `design.md` itself spawns `stage_design`, which would be nested): read `<<SKILL_DIR>>/commands/design.md` and execute its instructions for Issue #$1 in this same main session.
4. If `design` is NOT in skip-review:
   - Report to user: "Analyze complete. Run `/sdd design $1` to continue, or `/sdd resume $1`."
   - Stop.

### `OK NO_ACTION`
1. Update label and close:
   ```bash
   gh issue edit $1 --remove-label "sdd:analyze" --add-label "sdd:done"
   ```
   ```bash
   gh issue close $1
   ```
2. Report to user: "Issue #$1 closed as no-action. Analyze comment on the Issue explains why."
3. Stop.

### `OK PAUSE`
Report to user: "Paused. Resume with `/sdd resume $1`." Stop.

### `ESCALATE: <summary>`
1. Render `<summary>` verbatim to the user.
2. Call `AskUserQuestion` with 3 options: `Continue`, `Pause`, `Stop`.
3. Branch on user choice:
   - **Continue** → re-spawn `stage_analyze` with `Resume: continue-after-escalation`:
     - `subagent_type`: `general-purpose`, `model`: `opus`, `description`: `stage_analyze resume for #$1`
     - `prompt`:
       > Read `<<SKILL_DIR>>/commands/atoms/stage_analyze.md` and execute its instructions for Issue #$1.
       >
       > Inputs:
       >   Issue: #$1
       >   Depth: <dial>
       >   Resume: continue-after-escalation
       >
       > Return EXACTLY one line per the contract, prefixed by `>>> RESULT <<<`.
     - Parse the re-spawn's return (should be `OK ADVANCE: design`, `OK NO_ACTION`, or `FAIL:`). Loop into the corresponding branch above. If `OK ADVANCE: design`, handle the label + skip-review steps again.
   - **Pause** → report "Resume later with `/sdd resume $1`." Stop.
   - **Stop** → exit cleanly.

### `FAIL: <reason>`

Parse `<reason>` for an optional subtype prefix (`<subtype>: <detail>`) per `spec/00-common-contracts.md` §6 "FAIL reason prefix convention". Branch:

- **`no-action: <detail>`** — analyze concluded no SDD work is needed (operational / documentation-only). Render:
  > Issue #$1 analyze concluded no-action: `<detail>`.
  > Close-as-not-planned recommended:
  > ```bash
  > gh issue edit $1 --remove-label "sdd:analyze" --add-label "sdd:done"
  > gh issue close $1 --reason "not planned" --comment "<detail>"
  > ```
  > Analyze comment remains on the Issue for reference.

  Stop without changing labels (close is the user's explicit action).

- **`precondition-missing: <detail>`** — required prior artifact absent. Render:
  > Issue #$1 analyze precondition missing: `<detail>`.

  Stop.

- **No recognized prefix** — render `<reason>` verbatim to the user. Stop.

### Unknown / malformed
Treat as `FAIL: unexpected return: <line>` and stop. (Defensive per `design/01-sub-agent-contract.md` §9.)

## Notes

- **AI review always runs.** `skip-review: analyze` skips only the user confirmation between stages — `stage_analyze` always executes Phases 1-4 internally. The Phase 1.5 escalation gate (inside the sub-agent) still triggers on Round 3 FAIL, but skip-review auto-continues it (sub-agent returns `OK ADVANCE: design` instead of `ESCALATE`). Findings remain on the Issue for human follow-up.
- **Single sub-agent spawn per invocation** (or two, if a `continue-after-escalation` resume is needed). All reviewer + retry loop logic lives inside `stage_analyze.md` — main session stays thin.
- **Reviewers run serially inside the sub-agent.** Reviewer independence is preserved by the sub-agent's internal narrative structure (re-fetch the analyze output for each reviewer; no cross-visibility of verdicts).
- **Label transitions are main session's responsibility.** `stage_analyze` never sets labels itself.
- **Depth label override**: `sdd:review:deep` / `sdd:review:shallow` selects the depth dial, which the sub-agent uses for model selection internally per `_review_helpers.md` Section A.2.
