# ANALYZE

**Stage 1: Requirements Analysis (What / Why) — Orchestrator**

Focus ONLY on What and Why. Do NOT discuss How (technical implementation).

This file is an **orchestrator**. It runs in the main session and composes atomic operations via the Agent tool. The atoms (`atoms/analyze_work.md`, `atoms/analyze_review.md`) do the actual work; this file manages state, retries, and user interaction.

## Input Validation

Before any other step: validate `$1` per Common Definitions → Issue Validation in `${CLAUDE_SKILL_DIR}/SKILL.md`. If `$1` is a Pull Request, stop without making changes.

## Phase 1: Analyze + AI Review Loop

Up to **3 rounds** maximum. Each round = work atom → parallel review atoms → verdict check.

### Round 1

**Step 1.1 — Spawn the work atom** via the Agent tool:

- `subagent_type`: `general-purpose`
- `description`: `analyze work for #$1`
- `prompt`:
  > Read `${CLAUDE_SKILL_DIR}/commands/atoms/analyze_work.md` and execute its instructions for Issue #$1.
  > Return EXACTLY one line in the contract specified by that file, prefixed by the `>>> RESULT <<<` marker line.

Parse the subagent's `>>> RESULT <<<` line:
- `FAIL: <reason>` → report failure to the user and stop. Do not proceed to reviews.
- `OK NO_ACTION` → skip the review loop entirely. Jump to **Phase 2 (No-Action path)**.
- `OK` → continue to Step 1.2.

**Step 1.2 — Spawn the two review atoms in parallel** via the Agent tool. Use a single message containing **two Agent tool calls** so they run concurrently:

Agent A:
- `subagent_type`: `general-purpose`
- `description`: `analyze review (completeness) for #$1`
- `prompt`:
  > Read `${CLAUDE_SKILL_DIR}/commands/atoms/analyze_review.md` and execute its instructions for Issue #$1 with role `completeness`.
  > Return EXACTLY one line in the contract specified by that file, prefixed by the `>>> RESULT <<<` marker line.

Agent B:
- `subagent_type`: `general-purpose`
- `description`: `analyze review (quality) for #$1`
- `prompt`:
  > Read `${CLAUDE_SKILL_DIR}/commands/atoms/analyze_review.md` and execute its instructions for Issue #$1 with role `quality`.
  > Return EXACTLY one line in the contract specified by that file, prefixed by the `>>> RESULT <<<` marker line.

Parse both `>>> RESULT <<<` lines:
- If either is `FAIL: <reason>` (atom error, not review verdict) → report failure, stop.
- Combine the verdicts:
  - Both `OK PASS` → reviews passed. Exit the round loop. Proceed to **Phase 2**.
  - Either `OK FAIL: <summary>` → reviews failed. Combine the summaries.

**Step 1.3 — Round decision:**
- If reviews passed → break out of the loop; proceed to **Phase 2**.
- If reviews failed and round < 3 → fetch the review comments from the Issue to get full issue details (via `gh api .../comments`), summarize the combined critical/major issues, and run **Round N+1** by re-spawning the work atom with `$2` = combined-issues feedback string.
- If reviews failed and round == 3 → exit the loop. Report the remaining unfixed issues to the user (severity-summarized) and proceed to **Phase 2** anyway (user makes the call).

### Round 2 and Round 3 (retry)

Same as Round 1 Steps 1.1–1.3, but the work atom's prompt **must include the previous round's review feedback** as `$2`:

- `prompt`:
  > Read `${CLAUDE_SKILL_DIR}/commands/atoms/analyze_work.md` and execute its instructions for Issue #$1.
  > Previous round review feedback (address each item): <combined critical/major issues from prior reviews>
  > Return EXACTLY one line in the contract specified by that file.

The review atom prompts are unchanged between rounds — reviewers always evaluate the **current** analyze output on the Issue.

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
   - **Auto-proceed**: use the Agent tool to spawn a subagent that executes `/sdd design $1`. This isolates the next stage's context.
3. If `analyze` is NOT in skip-review:
   - Summarize for the user: which round reviews passed in, any minor suggestions still on the Issue, where the analysis comment is.
   - Ask for confirmation on direction and priorities.
   - On approval: update label to `sdd:design`.
   - (Do not auto-proceed to design when skip-review is off — the user invokes `/sdd design $1` themselves or runs `/sdd resume $1`.)

## Notes

- **AI review always runs.** `skip-review: analyze` skips only the **user confirmation** between stages — the AI review loop (Phase 1) always executes.
- **Atoms never spawn other atoms.** All Agent-tool spawning happens here in the orchestrator (this file). Atoms run as terminal subagents.
- **Reviews are independent.** The two review atoms run in parallel with independent contexts — they do not see each other's verdicts.
- **Retry limit is 3 rounds total** (initial + 2 retries).
