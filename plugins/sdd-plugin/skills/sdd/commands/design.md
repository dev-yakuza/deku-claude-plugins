# DESIGN

**Stage 2: Design (How) — Orchestrator**

Define HOW to implement based on the requirements.

This file is an **orchestrator**. It runs in the main session and composes atomic operations via the Agent tool. The atoms (`atoms/design_work.md`, `atoms/design_review.md`, `atoms/design_adversarial.md`) do the actual work; this file manages state, retries, and user interaction.

> **Bash Command Execution**: every shell snippet below is its own simple Bash tool call — no `&&`, `||`, `;`, `|`, `2>/dev/null`, `2>&1`, `>file`, `$(...)`, `VAR=$(...)`, or heredocs. For codebase exploration use the **Grep / Glob / Read** tools — do NOT use Bash `find` against `/`, `~`, `/Users`, or any path outside the repo root. See **Bash Command Execution Rules** in `<<SKILL_DIR>>/SKILL.md`.

## Input Validation

Before any other step: validate `$1` per Common Definitions → Issue Validation in `<<SKILL_DIR>>/SKILL.md`. If `$1` is a Pull Request, stop without making changes.

## Precondition

The Issue must have an `<!-- sdd:analyze:output -->` comment. If missing → report "Run `/sdd analyze $1` first" and stop. The work atom will also check this, but failing fast here avoids a wasted subagent invocation.

## Phase 0: Depth label detection

Per `<<SKILL_DIR>>/commands/atoms/_review_helpers.md` Section C:

```bash
gh issue view $1 --json labels --jq '[.labels[].name]'
```

Determine depth (`default` / `deep` / `shallow`).

**Model resolution for design stage**:

| Atom | default | deep | shallow |
|---|---|---|---|
| `design_work` | opus | opus | opus |
| `design_review` (completeness) | sonnet | opus | sonnet |
| `design_review` (quality) | sonnet | opus | sonnet |
| `design_adversarial` | opus | opus | sonnet |

## Phase 1: Design + AI Review Loop

Up to **3 rounds** maximum. Each round = work atom → 3 parallel review atoms → verdict check.

### Round 1

**Step 1.1 — Spawn the work atom** via the Agent tool:

- `subagent_type`: `general-purpose`
- `model`: `opus`
- `description`: `design work for #$1`
- `prompt`:
  > Read `<<SKILL_DIR>>/commands/atoms/design_work.md` and execute its instructions for Issue #$1.
  > Return EXACTLY one line in the contract specified by that file, prefixed by the `>>> RESULT <<<` marker line.

Parse the subagent's `>>> RESULT <<<` line:
- `FAIL: <reason>` → report failure to the user and stop. Do not proceed to reviews.
- `OK SINGLE` → single-PR design posted. Continue to Step 1.2. **Remember the path = SINGLE** for Phase 2.
- `OK CHILDREN: #A,#B,#C` → multi-PR design posted, children created. Continue to Step 1.2. **Remember the path = CHILDREN with the listed numbers** for Phase 2.

**Step 1.2 — Spawn the three review atoms in parallel** via the Agent tool. Single message, three Agent tool calls (concurrent execution):

Agent A (completeness):
- `subagent_type`: `general-purpose`
- `model`: per Phase 0 table
- `description`: `design review (completeness) for #$1`
- `prompt`:
  > Read `<<SKILL_DIR>>/commands/atoms/design_review.md` and execute its instructions for Issue #$1 with role `completeness`.
  > Return EXACTLY one line in the contract, prefixed by `>>> RESULT <<<`.

Agent B (quality):
- `subagent_type`: `general-purpose`
- `model`: per Phase 0 table
- `description`: `design review (quality) for #$1`
- `prompt`:
  > Read `<<SKILL_DIR>>/commands/atoms/design_review.md` and execute its instructions for Issue #$1 with role `quality`.
  > Return EXACTLY one line in the contract, prefixed by `>>> RESULT <<<`.

Agent C (adversarial):
- `subagent_type`: `general-purpose`
- `model`: per Phase 0 table
- `description`: `design adversarial for #$1`
- `prompt`:
  > Read `<<SKILL_DIR>>/commands/atoms/design_adversarial.md` and execute its instructions for Issue #$1.
  > Return EXACTLY one line in the contract, prefixed by `>>> RESULT <<<`.

Parse all three `>>> RESULT <<<` lines:
- If any is `FAIL: <reason>` (atom error) → report failure, stop.
- Combine verdicts:
  - All three `OK PASS` → reviews passed.
  - Any `OK FAIL: <summary>` → reviews failed. Combine summaries.
  - **Adversarial single-FAIL escalation**: if `OK FAIL` came only from adversarial, log to user: "⚠ Adversarial reviewer alone identified critical/major issues. Surfacing for awareness." Then continue Step 1.3 as normal.

**Step 1.3 — Round decision:**
- Reviews passed → exit loop; proceed to Phase 2.
- Reviews failed, round < 3 → spawn the next round's work atom in **retry mode** (see Round 2/3 below). Do NOT fetch review comments or extract JSON in the orchestrator — the atom self-fetches per `_review_helpers.md` Section C.
- Reviews failed, round == 3 → exit loop. Proceed to **Phase 1.5**.

### Round 2 and Round 3 (retry)

Same as Round 1 Steps 1.1–1.3, but the work atom is invoked in **retry mode** by passing the literal string `"retry"` as `$2`:

- `prompt`:
  > Read `<<SKILL_DIR>>/commands/atoms/design_work.md` and execute its instructions for Issue #$1.
  > Retry mode (`$2 = "retry"`): self-fetch previous round's review findings per `_review_helpers.md` Section C, then address every critical and major finding (use minor as supporting context).
  > Return EXACTLY one line in the contract.

The review atom prompts are unchanged between rounds.

**Note on retry with `OK CHILDREN`**: if Round 1 returned `OK CHILDREN: #A,#B,#C` and reviews failed, the work atom's idempotency rule (do NOT re-create children if `<!-- sdd:children:output -->` exists) keeps the same children across retries. The retry only updates the design output comment, not the child set.

## Phase 1.5: Round 3 Escalation Gate

Runs only if round 3 failed.

1. Fetch latest review findings.
2. Render summary to user:
   ```
   ⚠ Design stage: 3 review rounds failed.
   Remaining critical/major findings:
     - [critical] ... (design/<role>)
     - [major] ... (design/<role>)
   ```
3. **Honor skip-review** (auto-decide in unattended runs):
   - If `design` is in skip-review (e.g. `/sdd auto`, `/sdd batch`):
     - Log to the Issue (via comment) and to the orchestrator output: "⚠ Round 3 escalation: review still has critical/major findings, but `skip-review: design` is set — auto-continuing to Phase 2. Findings remain on the Issue for human follow-up."
     - Proceed to **Phase 2** immediately without asking. Do NOT call AskUserQuestion or any interactive prompt.
   - Else (interactive mode):
     - Ask the user: "Continue to Phase 2 / Pause for manual intervention / Stop?"
     - On "Continue" → proceed.
     - On "Pause" → stop. User resumes via `/sdd resume <N>` after manual fixes.
     - On "Stop" → exit cleanly.

## Phase 2: Branching on path (SINGLE vs CHILDREN)

### Path: SINGLE (from `OK SINGLE`)

1. Check skip-review setting (Common Definitions → Skip Review Setting).
2. If `design` is in skip-review:
   - Log: "User review skipped (skip-review: design). AI review already ran."
   - Update label to `sdd:implement`.
   - **Auto-proceed (read + execute inline, do NOT spawn a subagent)**: read `<<SKILL_DIR>>/commands/implement.md` and execute its instructions for Issue #$1 in this same main session.
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
   - On selection (read + execute inline, do NOT spawn a subagent): read `<<SKILL_DIR>>/commands/analyze.md` and execute its instructions for the selected child Issue in this same main session.

## Notes

- **AI review always runs.** `skip-review: design` skips only the user confirmation — the AI review loop (Phase 1) still executes. The Phase 1.5 escalation gate still triggers on Round 3 failure, but in skip-review mode it auto-continues to Phase 2 (findings stay on the Issue); in interactive mode it asks the user.
- **Atoms never spawn other atoms.** All Agent-tool spawning happens here. The work atom does its own codebase exploration via Read/Grep/Glob (no Explore subagent).
- **Reviews are independent.** Three review atoms run in parallel with independent contexts.
- **Retry feedback is structured JSON.** Lossless handoff to work atom.
- **Retry limit is 3 rounds total** (initial + 2 retries), then escalation gate.
- **Child creation is idempotent** across retries — work atom skips re-creation if `<!-- sdd:children:output -->` already exists on the parent.
- **Depth label override**: `sdd:review:deep`/`sdd:review:shallow` shifts model assignments per `_review_helpers.md` Section C.
