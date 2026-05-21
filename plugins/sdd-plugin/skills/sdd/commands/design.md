# DESIGN

**Stage 2: Design (How) — Orchestrator**

Define HOW to implement based on the requirements.

This file is an **orchestrator**. It runs in the main session and composes atomic operations via the Agent tool. The atoms (`atoms/design_work.md`, `atoms/design_review.md`) do the actual work; this file manages state, retries, and user interaction.

> **Bash Command Execution**: run every shell snippet below as its own simple Bash tool call — no `&&`, `||`, `;`, `|`, `$(...)`, `VAR=$(...)`, or heredocs. Inline literal values; do not use shell variables. See **Bash Command Execution Rules** in `${CLAUDE_SKILL_DIR}/SKILL.md`.

## Input Validation

Before any other step: validate `$1` per Common Definitions → Issue Validation in `${CLAUDE_SKILL_DIR}/SKILL.md`. If `$1` is a Pull Request, stop without making changes.

## Precondition

The Issue must have an `<!-- sdd:analyze:output -->` comment. If missing → report "Run `/sdd analyze $1` first" and stop. The work atom will also check this, but failing fast here avoids a wasted subagent invocation.

## Phase 1: Design + AI Review Loop

Up to **3 rounds** maximum. Each round = work atom → parallel review atoms → verdict check.

### Round 1

**Step 1.1 — Spawn the work atom** via the Agent tool:

- `subagent_type`: `general-purpose`
- `description`: `design work for #$1`
- `prompt`:
  > Read `${CLAUDE_SKILL_DIR}/commands/atoms/design_work.md` and execute its instructions for Issue #$1.
  > Return EXACTLY one line in the contract specified by that file, prefixed by the `>>> RESULT <<<` marker line.

Parse the subagent's `>>> RESULT <<<` line:
- `FAIL: <reason>` → report failure to the user and stop. Do not proceed to reviews.
- `OK SINGLE` → single-PR design posted. Continue to Step 1.2. **Remember the path = SINGLE** for Phase 2.
- `OK CHILDREN: #A,#B,#C` → multi-PR design posted, children created. Continue to Step 1.2. **Remember the path = CHILDREN with the listed numbers** for Phase 2.

**Step 1.2 — Spawn the two review atoms in parallel** via the Agent tool. Single message, two Agent tool calls (concurrent execution):

Agent A:
- `subagent_type`: `general-purpose`
- `description`: `design review (completeness) for #$1`
- `prompt`:
  > Read `${CLAUDE_SKILL_DIR}/commands/atoms/design_review.md` and execute its instructions for Issue #$1 with role `completeness`.
  > Return EXACTLY one line in the contract specified by that file, prefixed by the `>>> RESULT <<<` marker line.

Agent B:
- `subagent_type`: `general-purpose`
- `description`: `design review (quality) for #$1`
- `prompt`:
  > Read `${CLAUDE_SKILL_DIR}/commands/atoms/design_review.md` and execute its instructions for Issue #$1 with role `quality`.
  > Return EXACTLY one line in the contract specified by that file, prefixed by the `>>> RESULT <<<` marker line.

Parse both `>>> RESULT <<<` lines:
- If either is `FAIL: <reason>` (atom error) → report failure, stop.
- Combine verdicts:
  - Both `OK PASS` → reviews passed.
  - Either `OK FAIL: <summary>` → reviews failed. Combine the summaries.

**Step 1.3 — Round decision:**
- Reviews passed → exit loop; proceed to Phase 2.
- Reviews failed, round < 3 → fetch review comments from the Issue for full issue details, summarize combined critical/major issues, re-spawn work atom with `$2` = combined-issues string.
- Reviews failed, round == 3 → exit loop. Report remaining unfixed issues (severity-summarized) to the user; proceed to Phase 2 anyway.

### Round 2 and Round 3 (retry)

Same as Round 1 Steps 1.1–1.3, but the work atom prompt **must include previous round's review feedback** as `$2`:

- `prompt`:
  > Read `${CLAUDE_SKILL_DIR}/commands/atoms/design_work.md` and execute its instructions for Issue #$1.
  > Previous round review feedback (address each item): <combined critical/major issues from prior reviews>
  > Return EXACTLY one line in the contract specified by that file.

The review atom prompts are unchanged between rounds.

**Note on retry with `OK CHILDREN`**: if Round 1 returned `OK CHILDREN: #A,#B,#C` and reviews failed, the work atom's idempotency rule (do NOT re-create children if `<!-- sdd:children:output -->` exists) keeps the same children across retries. The retry only updates the design output comment, not the child set.

## Phase 2: Branching on path (SINGLE vs CHILDREN)

### Path: SINGLE (from `OK SINGLE`)

1. Check skip-review setting (Common Definitions → Skip Review Setting).
2. If `design` is in skip-review:
   - Log: "User review skipped (skip-review: design). AI review already ran."
   - Update label to `sdd:implement`.
   - **Auto-proceed (read + execute inline, do NOT spawn a subagent)**: read `${CLAUDE_SKILL_DIR}/commands/implement.md` and execute its instructions for Issue #$1 in this same main session.
3. If `design` is NOT in skip-review:
   - Summarize for the user: which round passed, any minor suggestions still on the Issue, the design comment location.
   - Ask for confirmation on technical approach and PR split.
   - On approval: update label to `sdd:implement`. (User invokes `/sdd implement $1` themselves or runs `/sdd resume $1`.)

### Path: CHILDREN (from `OK CHILDREN: #A,#B,...`)

The work atom has already:
- Posted the design output comment on the parent
- Created the child Issues with labels `sdd:analyze` + `sdd:child`
- Posted the `<!-- sdd:children:output -->` comment on the parent

The orchestrator now:

1. Check skip-review setting.
2. Update parent label to `sdd:implement`.
3. If `design` is in skip-review:
   - **Stop here.** The parent reaches `sdd:implement` with children at `sdd:analyze`. The surrounding flow (e.g. `/sdd batch` or `/sdd auto`) picks up the children.
   - Log: "Children created (#A, #B, ...). Parent stopped at sdd:implement for batch/orchestrator to queue children."
4. If `design` is NOT in skip-review:
   - Summarize: design posted, children #A, #B, ... created, parent now at `sdd:implement`.
   - Ask: "Which child Issue would you like to start with?"
   - On selection (read + execute inline, do NOT spawn a subagent): read `${CLAUDE_SKILL_DIR}/commands/analyze.md` and execute its instructions for the selected child Issue in this same main session.

## Notes

- **AI review always runs.** `skip-review: design` skips only the user confirmation — the AI review loop (Phase 1) always executes.
- **Atoms never spawn other atoms.** All Agent-tool spawning happens here. The work atom does its own codebase exploration via Read/Grep/Glob (no Explore subagent).
- **Reviews are independent.** Two review atoms run in parallel with independent contexts.
- **Retry limit is 3 rounds total** (initial + 2 retries).
- **Child creation is idempotent** across retries — work atom skips re-creation if `<!-- sdd:children:output -->` already exists on the parent.
