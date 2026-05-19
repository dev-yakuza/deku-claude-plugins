# IMPLEMENT

**Stage 3: Implementation — TDD Cycle (Red → Green → Refactor) — Orchestrator**

## Rules
- Do NOT set Claude as co-author in git commits.
- Check existing git history for branch naming and commit message conventions, and follow the same format.

This file is an **orchestrator**. It runs in the main session and composes atomic operations via the Agent tool. The atoms (`atoms/implement_plan.md`, `atoms/implement_tdd.md`, `atoms/implement_review.md`) do the actual work; this file manages state, sequencing, and user interaction.

## Input Validation

Before any other step: validate `$1` per Common Definitions → Issue Validation in `${CLAUDE_SKILL_DIR}/SKILL.md`. If `$1` is a Pull Request, stop without making changes.

## Determine Issue type

1. Check if this Issue has child Issues:
   ```bash
   OWNER_REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
   gh api repos/$OWNER_REPO/issues/$1/comments \
     --jq '.[] | select(.body | contains("sdd:children:output")) | .body' | head -1
   ```
2. **Parent Issue (has children)**: Do NOT implement directly. Instead:
   - List child Issues and their current status (from the `<!-- sdd:children:output -->` table + each child's actual label)
   - Ask user which child Issue to work on
   - Execute `/sdd analyze <child>` or `/sdd resume <child>` via Agent-tool spawn
   - Stop the orchestrator here.
3. **Single Issue or Child Issue (no children)**: Proceed to Phase A below.

## Phase A: Plan

### A.1 — Spawn the plan atom

- `subagent_type`: `general-purpose`
- `description`: `implement plan for #$1`
- `prompt`:
  > Read `${CLAUDE_SKILL_DIR}/commands/atoms/implement_plan.md` and execute its instructions for Issue #$1.
  > Return EXACTLY one line in the contract specified by that file, prefixed by the `>>> RESULT <<<` marker line.

Parse the `>>> RESULT <<<` line:
- `FAIL: <reason>` → report failure, stop.
- `OK BRANCH: <branch-name>` → continue. Remember `<branch-name>` for Phase B.

### A.2 — Plan review (self_only, no orchestrator-level retry)

The plan atom did its own `self_only` review inline. The orchestrator does not spawn additional review atoms for the plan stage.

### A.3 — User confirmation

Check skip-review setting (Common Definitions → Skip Review Setting).
- If `implement` is in skip-review → log "User review skipped (skip-review: implement). Proceeding to TDD." → Phase B.
- Otherwise → present the plan comment (now on the Issue with marker `<!-- sdd:implement:plan -->`) and ask the user to confirm the plan direction before proceeding. On approval → Phase B. On rejection → stop.

## Phase B: TDD + Review Loop (up to 3 rounds)

Each round = TDD atom (first-round or retry) → parallel review atoms → verdict check.

### Round 1

#### B.1.1 — Spawn the TDD atom (first-round)

- `subagent_type`: `general-purpose`
- `description`: `implement TDD for #$1`
- `prompt`:
  > Read `${CLAUDE_SKILL_DIR}/commands/atoms/implement_tdd.md` and execute its instructions for Issue #$1 on branch `<branch-name>`.
  > Return EXACTLY one line in the contract specified by that file, prefixed by the `>>> RESULT <<<` marker line.

Parse the `>>> RESULT <<<` line:
- `FAIL: <reason>` → report failure to user, stop.
- `OK PR: #N` → TDD complete, PR created. Continue.
- `OK PR: #N E2E_SKIPPED` → same, but E2E was skipped (no setup detected). Note for the user; continue.

Remember the PR number `#N` for the review step.

#### B.1.2 — Spawn the two review atoms in parallel

Single message, two Agent tool calls (concurrent):

Agent A:
- `subagent_type`: `general-purpose`
- `description`: `implement review (completeness) for #$1`
- `prompt`:
  > Read `${CLAUDE_SKILL_DIR}/commands/atoms/implement_review.md` and execute its instructions for Issue #$1 with role `completeness`.
  > Return EXACTLY one line in the contract specified by that file, prefixed by the `>>> RESULT <<<` marker line.

Agent B:
- `subagent_type`: `general-purpose`
- `description`: `implement review (quality) for #$1`
- `prompt`:
  > Read `${CLAUDE_SKILL_DIR}/commands/atoms/implement_review.md` and execute its instructions for Issue #$1 with role `quality`.
  > Return EXACTLY one line in the contract specified by that file, prefixed by the `>>> RESULT <<<` marker line.

Parse both `>>> RESULT <<<` lines:
- If either is `FAIL: <reason>` (atom error) → report, stop.
- Both `OK PASS PR: #N` → reviews passed; **exit the round loop, proceed to B.2**.
- Either `OK FAIL PR: #N: <summary>` → reviews failed.

#### B.1.3 — Round decision

- Reviews passed → exit loop → B.2.
- Reviews failed AND round < 3 → fetch the full review comment bodies from the PR for combined critical/major issue text:
  ```bash
  gh api repos/$OWNER_REPO/issues/<PR_NUM>/comments \
    --jq '.[] | select(.body | test("sdd:review:implement:(completeness|quality)")) | .body'
  ```
  Summarize the critical and major items into a single feedback string (max ~50 lines). Proceed to Round 2 (retry).
- Reviews failed AND round == 3 → exit loop. Report the remaining unfixed critical/major issues to the user. Proceed to B.2 anyway (user makes the final call).

### Round 2 and Round 3 (retry)

Same structure as Round 1 with one critical difference: the TDD atom is invoked in **retry mode** by passing the feedback as `$3`. Retry mode = the atom detects the existing PR, adds new commits (regular `git push`, no force-push, no amend), and pushes — preserving the PR's review history.

#### B.N.1 — Spawn the TDD atom (retry)

- `subagent_type`: `general-purpose`
- `description`: `implement TDD retry round N for #$1`
- `prompt`:
  > Read `${CLAUDE_SKILL_DIR}/commands/atoms/implement_tdd.md` and execute its instructions for Issue #$1 on branch `<branch-name>` in retry mode.
  > Previous round review feedback (address each critical/major item with new commits — do NOT force-push, do NOT amend):
  >
  > <combined critical/major issues from prior reviews, verbatim or summarized>
  >
  > Return EXACTLY one line in the contract specified by that file, prefixed by the `>>> RESULT <<<` marker line.

Parse the return:
- `FAIL: <reason>` → report failure, stop. (Retry-mode preconditions may have failed; e.g., the PR was closed externally.)
- `OK PR: #N` / `OK PR: #N E2E_SKIPPED` → fix-up applied, PR updated. Continue to B.N.2.

#### B.N.2 — Re-spawn the review atoms in parallel

Same as B.1.2. The review atoms re-diff the (now updated) PR and post fresh review comments. Because they use duplicate-prevention markers (`<!-- sdd:review:implement:<role> -->`), the prior round's review comments are **updated in place** rather than appended — the reviewer's verdict reflects the latest PR state.

#### B.N.3 — Round decision

Same as B.1.3.

### B.2 — User confirmation and label transition

Check skip-review setting.

- If `pr` is in skip-review:
  - Log "User review skipped (skip-review: pr)".
  - Update label to `sdd:test`.
  - If `qa` is also in skip-review → **auto-proceed (read + execute inline, do NOT spawn a subagent)**: read `${CLAUDE_SKILL_DIR}/commands/test.md` and execute its instructions for Issue #$1 in this same main session.
  - Otherwise → **stop here**. PR created, label updated; human reviews PR and runs QA.

- Otherwise:
  - Present the PR URL, change summary, and the review verdicts (PASS/FAIL with summary).
  - Ask for final confirmation.
  - On approval → update label to `sdd:test`.

## Phase C: Child completion notification (if this is a child Issue)

This phase runs **only if the Issue body contains `Parent Issue: #<number>` inside the `<!-- sdd:child-issue -->` block** AND the Issue's label has just transitioned to `sdd:done` (typically after `/sdd test <child>` completes — but if the orchestrator hits this point with the child already `sdd:done`, run the notification).

1. Find the parent Issue number from `<!-- sdd:child-issue -->`.
2. Find the **most recent** children comment on the parent containing BOTH `<!-- sdd:children:output -->` and `<!-- /sdd:children:output -->`:
   ```bash
   gh api repos/$OWNER_REPO/issues/<parent>/comments \
     --jq '.[] | select((.body | contains("<!-- sdd:children:output -->")) and (.body | contains("<!-- /sdd:children:output -->"))) | {id, body}'
   ```
   - If no matching comment → warn and skip update.
   - If multiple → use the last one.
3. Update the children comment: replace this child Issue's row in the table with the new status. Use `gh api repos/{owner}/{repo}/issues/comments/<id> -X PATCH --field body=...`.
4. Verify the update by re-reading the comment.
5. Check if ALL child Issues are `sdd:done`:
   - Read each child's actual label (do NOT rely only on the comment table).
   - If all `sdd:done` → post a comment on the parent notifying completion and suggest `/sdd test <parent>` or `/sdd resume <parent>`.
   - If not → report remaining children and ask which child to work on next.

## Notes

- **Atoms never spawn other atoms.** All Agent-tool spawning happens here in the orchestrator. The TDD atom does sequential self-reviews within itself (3-1, 3-2, 3-3, 3-4 are `self_only`); the orchestrator handles only the PR Final review (3-5, `full`).
- **PR Final reviews are independent.** Two `implement_review` atoms run in parallel with independent contexts, reading the PR diff fresh from GitHub.
- **Retry limit is 3 rounds total** (initial + 2 retries). On retry, the TDD atom runs in retry mode: it detects the existing PR, addresses the prior round's feedback by adding new commits, and pushes regularly (no `--force`, no `--amend`). Prior PR review comments stay attached to their original commits for audit.
- **Review comments are updated in place across rounds** via the duplicate-prevention markers (`<!-- sdd:review:implement:<role> -->`). The reviewer's verdict on the PR always reflects the latest diff, not historical state.
- **Reviews go on the PR, not the Issue** (via `gh pr comment`). The `<!-- sdd:review:implement:<role> -->` markers identify them on the PR.
