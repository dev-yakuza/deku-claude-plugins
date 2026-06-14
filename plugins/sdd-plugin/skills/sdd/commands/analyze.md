# ANALYZE

**Stage 1: Requirements Analysis (What / Why) — Orchestrator**

Focus ONLY on What and Why. Do NOT discuss How (technical implementation).

This file is an **orchestrator**. It runs in the main session and composes atomic operations via the Agent tool. The atoms (`atoms/analyze_work.md`, `atoms/analyze_review.md`, `atoms/analyze_adversarial.md`) do the actual work; this file manages state, retries, and user interaction.

> **Bash Command Execution**: every shell snippet below is its own simple Bash tool call — no `&&`, `||`, `;`, `|`, `2>/dev/null`, `2>&1`, `>file`, `$(...)`, `VAR=$(...)`, or heredocs. For codebase exploration use the **Grep / Glob / Read** tools — do NOT use Bash `find` against `/`, `~`, `/Users`, or any path outside the repo root. See **Bash Command Execution Rules** in `<<SKILL_DIR>>/SKILL.md`.

## Input Validation

Before any other step: validate `$1` per Common Definitions → Issue Validation in `<<SKILL_DIR>>/SKILL.md`. If `$1` is a Pull Request, stop without making changes.

## Phase 0: Depth label detection

Read the Issue's labels to determine review depth (per `<<SKILL_DIR>>/commands/atoms/_review_helpers.md` Section C):

```bash
gh issue view $1 --json labels --jq '[.labels[].name]'
```

- Has `sdd:review:deep` → depth = `deep`
- Has `sdd:review:shallow` → depth = `shallow`
- Otherwise → depth = `default`

Use the depth value to select models for each Agent spawn below, per the table in `_review_helpers.md` Section C.2.

**Model resolution for analyze stage**:

| Atom | default | deep | shallow |
|---|---|---|---|
| `analyze_work` | opus | opus | opus |
| `analyze_review` (completeness) | sonnet | opus | sonnet |
| `analyze_review` (quality) | sonnet | opus | sonnet |
| `analyze_adversarial` | opus | opus | sonnet |

## Phase 1: Analyze + AI Review Loop

Up to **3 rounds** maximum. Each round = work atom → 3 parallel review atoms → verdict check.

### Round 1

**Step 1.1 — Spawn the work atom** via the Agent tool:

- `subagent_type`: `general-purpose`
- `model`: `opus` (per Phase 0 table)
- `description`: `analyze work for #$1`
- `prompt`:
  > Read `<<SKILL_DIR>>/commands/atoms/analyze_work.md` and execute its instructions for Issue #$1.
  > Return EXACTLY one line in the contract specified by that file, prefixed by the `>>> RESULT <<<` marker line.

Parse the subagent's `>>> RESULT <<<` line:
- `FAIL: <reason>` → report failure to the user and stop. Do not proceed to reviews.
- `OK NO_ACTION` → skip the review loop entirely. Jump to **Phase 2 (No-Action path)**.
- `OK` → continue to Step 1.2.

**Step 1.2 — Spawn the three review atoms in parallel** via the Agent tool. Use a single message containing **three Agent tool calls** so they run concurrently:

Agent A (completeness):
- `subagent_type`: `general-purpose`
- `model`: per Phase 0 table for analyze_review/completeness
- `description`: `analyze review (completeness) for #$1`
- `prompt`:
  > Read `<<SKILL_DIR>>/commands/atoms/analyze_review.md` and execute its instructions for Issue #$1 with role `completeness`.
  > Return EXACTLY one line in the contract specified by that file, prefixed by the `>>> RESULT <<<` marker line.

Agent B (quality):
- `subagent_type`: `general-purpose`
- `model`: per Phase 0 table for analyze_review/quality
- `description`: `analyze review (quality) for #$1`
- `prompt`:
  > Read `<<SKILL_DIR>>/commands/atoms/analyze_review.md` and execute its instructions for Issue #$1 with role `quality`.
  > Return EXACTLY one line in the contract specified by that file, prefixed by the `>>> RESULT <<<` marker line.

Agent C (adversarial):
- `subagent_type`: `general-purpose`
- `model`: per Phase 0 table for analyze_adversarial
- `description`: `analyze adversarial for #$1`
- `prompt`:
  > Read `<<SKILL_DIR>>/commands/atoms/analyze_adversarial.md` and execute its instructions for Issue #$1.
  > Return EXACTLY one line in the contract specified by that file, prefixed by the `>>> RESULT <<<` marker line.

Parse all three `>>> RESULT <<<` lines:
- If any is `FAIL: <reason>` (atom error, not review verdict) → report failure, stop.
- Combine the verdicts:
  - All three `OK PASS` → reviews passed. Exit the round loop. Proceed to **Phase 2**.
  - Any `OK FAIL: <summary>` → reviews failed. Combine the summaries.
  - **Adversarial single-FAIL escalation**: if `OK FAIL` came ONLY from adversarial and the other two are `OK PASS`, log to the user: "⚠ Adversarial reviewer alone identified critical/major issues. Other reviewers passed. Surfacing for user awareness." Continue to **Step 1.3** as normal.

**Step 1.3 — Round decision:**
- If reviews passed → break out of the loop; proceed to **Phase 2**.
- If reviews failed and round < 3 → spawn the next round's work atom in **retry mode** (see Round 2/3 below). Do NOT fetch review comments or extract JSON in the orchestrator — the atom self-fetches per `_review_helpers.md` Section C, which keeps the main session context light.
- If reviews failed and round == 3 → exit the loop. Proceed to **Phase 1.5 (Escalation gate)**.

### Round 2 and Round 3 (retry)

Same as Round 1 Steps 1.1–1.3, but the work atom is invoked in **retry mode** by passing the literal string `"retry"` as `$2`:

- `prompt`:
  > Read `<<SKILL_DIR>>/commands/atoms/analyze_work.md` and execute its instructions for Issue #$1.
  > Retry mode (`$2 = "retry"`): self-fetch previous round's review findings per `_review_helpers.md` Section C, then address every critical and major finding (use minor as supporting context).
  > Return EXACTLY one line in the contract specified by that file.

The review atom prompts are unchanged between rounds — reviewers always evaluate the **current** analyze output on the Issue.

## Phase 1.5: Round 3 Escalation Gate

This phase runs only if round 3 also failed.

1. Fetch the latest review findings (same extraction as above).
2. Render a summary for the user:
   ```
   ⚠ Analyze stage: 3 review rounds failed.
   Remaining critical/major findings:
     - [critical] <description> (analyze/<role>)
     - [major] <description> (analyze/<role>)
     ...
   ```
3. **Honor skip-review** (auto-decide in unattended runs):
   - If `analyze` is in skip-review (e.g. `/sdd auto`, `/sdd batch`):
     - Log to the Issue (via comment) and to the orchestrator output: "⚠ Round 3 escalation: review still has critical/major findings, but `skip-review: analyze` is set — auto-continuing to Phase 2. Findings remain on the Issue for human follow-up."
     - Proceed to **Phase 2** immediately without asking. Do NOT call AskUserQuestion or any interactive prompt.
   - Else (interactive mode, no skip-review):
     - Ask the user: "Continue to Phase 2 anyway / Pause for manual intervention / Stop?"
     - On "Continue" → proceed to Phase 2.
     - On "Pause" → stop the orchestrator. User will resume via `/sdd resume <N>` after manual fixes.
     - On "Stop" → exit cleanly.

## Phase 2: User Review

### No-Action path (Phase 1 returned `OK NO_ACTION`)

1. Check skip-review setting (see Common Definitions → Skip Review Setting in `SKILL.md`).
2. If `analyze` is in skip-review:
   - Log: "No action needed — skipping remaining stages"
   - Update label to `sdd:done`
   - **Do NOT proceed** to design. Stop here.
3. If `analyze` is NOT in skip-review:
   - Present the no-action explanation (already posted on the Issue) to the user.
   - Ask: "This Issue appears to need no code changes. Close as no-action?"
   - On approval: update label to `sdd:done`.
   - On rejection: user may provide additional context → re-run Phase 1 from Round 1.

### Normal path (reviews completed, output is on the Issue)

1. Check skip-review setting.
2. If `analyze` is in skip-review:
   - Log: "User review skipped (skip-review: analyze). AI review already ran."
   - Update label to `sdd:design`.
   - **Auto-proceed (read + execute inline, do NOT spawn a subagent)**: read `<<SKILL_DIR>>/commands/design.md` and execute its instructions for Issue #$1 in this same main session. (Spawning a subagent here would create nested-subagent spawning when the design orchestrator itself spawns atoms — Claude Code blocks that.)
3. If `analyze` is NOT in skip-review:
   - Summarize for the user: which round reviews passed in, any minor suggestions still on the Issue, where the analysis comment is.
   - Ask for confirmation on direction and priorities.
   - On approval: update label to `sdd:design`.
   - (Do not auto-proceed to design when skip-review is off — the user invokes `/sdd design $1` themselves or runs `/sdd resume $1`.)

## Notes

- **AI review always runs.** `skip-review: analyze` skips only the **user confirmation** between stages — the AI review loop (Phase 1) always executes. The Phase 1.5 escalation gate still runs after Round 3 failure, but its decision branch is automatic in skip-review mode: it auto-continues to Phase 2 and leaves findings on the Issue for human follow-up. In interactive mode (no skip-review) it asks the user.
- **Atoms never spawn other atoms.** All Agent-tool spawning happens here in the orchestrator (this file). Atoms run as terminal subagents.
- **Reviews are independent.** The three review atoms run in parallel with independent contexts — they do not see each other's verdicts.
- **Retry feedback is structured JSON**, not summarized text. Lossless handoff to work atom for retry rounds.
- **Retry limit is 3 rounds total** (initial + 2 retries), then escalation gate.
- **Depth label override**: `sdd:review:deep` forces all reviewers to Opus; `sdd:review:shallow` uses cheaper models throughout. See `_review_helpers.md` Section C.
