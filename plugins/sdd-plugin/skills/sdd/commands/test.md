# TEST

**Stage 4: Testing — Orchestrator**

QA verification + integration E2E for parent Issues. Unit/UI tests and E2E tests for single/child Issues were already done in Stage 3 (implement); this stage validates them and adds the QA gate.

This file is an **orchestrator**. It runs in the main session and composes atomic operations via the Agent tool. The atoms (`atoms/test_work.md`, `atoms/test_review.md`) do the actual work; this file manages state, retries, manual QA interaction, and the final label transition to `sdd:done`.

## Input Validation

Before any other step: validate `$1` per Common Definitions → Issue Validation in `${CLAUDE_SKILL_DIR}/SKILL.md`. If `$1` is a Pull Request, stop without making changes.

## Determine Issue type

1. Check for children comment:
   ```bash
   OWNER_REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
   HAS_CHILDREN=$(gh api repos/$OWNER_REPO/issues/$1/comments \
     --jq '.[] | select(.body | contains("<!-- sdd:children:output -->")) | .body' | head -1)
   ```

2. **Parent Issue (has children)**: Verify all child Issues are `sdd:done` before proceeding:
   - Read child Issue numbers from the children comment.
   - Check each child's label.
   - If any child is NOT `sdd:done` → report which children are incomplete; ask user to complete them first; stop.
   - If ALL children are `sdd:done` → proceed to Phase 1 (work atom will run in parent path).
3. **Single/Child Issue**: proceed directly to Phase 1.

## Phase 1: Test + AI Review Loop

Up to **3 rounds** maximum. Each round = work atom → parallel review atoms → verdict check.

### Round 1

#### 1.1 — Spawn the work atom

- `subagent_type`: `general-purpose`
- `description`: `test work for #$1`
- `prompt`:
  > Read `${CLAUDE_SKILL_DIR}/commands/atoms/test_work.md` and execute its instructions for Issue #$1.
  > Return EXACTLY one line in the contract specified by that file, prefixed by the `>>> RESULT <<<` marker line.

Parse the `>>> RESULT <<<` line:
- `FAIL: <reason>` → report failure to the user, stop. (Special case: if reason starts with `no E2E test setup detected; recommended framework:` → surface to user, ask for framework choice, re-spawn with the chosen framework noted in the prompt as `Framework: <name>`.)
- `OK SINGLE PR: #N` → single/child path; existing PR validated. Continue.
- `OK PARENT INTEGRATION_PR: #M` → parent path; integration test PR created. Continue. Note PR `#M` for the user.
- `OK PARENT NO_INTEGRATION` → parent path; children's tests sufficient. Continue.

#### 1.2 — Spawn the two review atoms in parallel

Single message, two Agent tool calls (concurrent):

Agent A:
- `subagent_type`: `general-purpose`
- `description`: `test review (completeness) for #$1`
- `prompt`:
  > Read `${CLAUDE_SKILL_DIR}/commands/atoms/test_review.md` and execute its instructions for Issue #$1 with role `completeness`.
  > Return EXACTLY one line in the contract specified by that file, prefixed by the `>>> RESULT <<<` marker line.

Agent B:
- `subagent_type`: `general-purpose`
- `description`: `test review (quality) for #$1`
- `prompt`:
  > Read `${CLAUDE_SKILL_DIR}/commands/atoms/test_review.md` and execute its instructions for Issue #$1 with role `quality`.
  > Return EXACTLY one line in the contract specified by that file, prefixed by the `>>> RESULT <<<` marker line.

Parse both `>>> RESULT <<<` lines:
- Either `FAIL: <reason>` (atom error) → report, stop.
- Both `OK PASS` → reviews passed; exit loop → Phase 2.
- Either `OK FAIL: <summary>` → reviews failed. Combine summaries.

#### 1.3 — Round decision

- Reviews passed → exit loop → Phase 2.
- Reviews failed, round < 3 → fetch the review comments for full issue details, summarize combined critical/major, re-spawn the work atom with `$2` = combined feedback string. (Test work atom updates its existing `<!-- sdd:test:output -->` comment via duplicate prevention.)
- Reviews failed, round == 3 → exit loop. Report remaining unfixed issues to the user; proceed to Phase 2.

### Round 2 and Round 3 (retry)

Same as Round 1 Steps 1.1–1.3, but the work atom prompt **must include previous round's review feedback** as a follow-on instruction in the prompt:

- `prompt`:
  > Read `${CLAUDE_SKILL_DIR}/commands/atoms/test_work.md` and execute its instructions for Issue #$1.
  > Previous round review feedback (address each item — fix gaps in the test report or QA checklist): <combined critical/major issues from prior reviews>
  > Return EXACTLY one line in the contract specified by that file.

## Phase 2: User Review + Manual QA

This phase requires main-session interaction with the user for manual QA, unless `qa` is in skip-review.

### 2.1 — User-facing context

Present to the user:
- Test work atom's result (which path, PR numbers, integration PR if any)
- Review verdicts (PASS/FAIL with summaries)
- Link to the Issue's test output comment for the full QA checklist

If the work atom flagged "E2E was skipped in Stage 3" for single/child path → ask the user whether to add E2E tests now (push to the PR branch) or proceed without.

### 2.2 — skip-review check

Check skip-review setting (Common Definitions → Skip Review Setting).

- **If `qa` is in skip-review**:
  - Log: "User review skipped (skip-review: qa)". Auto-approve test results and QA checklist.
  - Skip to **Phase 3** (Results Review).

- **If `qa` is NOT in skip-review**:
  - The user may add/remove/modify QA checklist items (the work atom posted the checklist; the user edits the Issue comment directly if needed).
  - **Manual QA (4-3)**: ask the user to perform manual QA based on the approved checklist and report pass/fail per item. Wait for the user's response.

## Phase 3: Results Review (4-4)

Based on the user's manual QA report (or auto-approval under skip-review):

1. **If any QA item failed** → analyze cause with the user, and go back to Stage 3 (`/sdd implement $1`) for a TDD bug-fix cycle. Stop this orchestrator.

2. **All tests pass** → update label and close:
   ```bash
   gh issue edit $1 --remove-label "sdd:test" --add-label "sdd:done"
   gh issue close $1
   ```

## Phase 4: Child completion notification (if this Issue is a child)

Same logic as `implement.md` Phase C: when a child Issue (detected via the multi-language parent regex `(Parent|상위 |親)Issue: #<n>` per Common Definitions → Parent/Child Issue Detection in `${CLAUDE_SKILL_DIR}/SKILL.md`) just transitioned to `sdd:done`, update the parent's `<!-- sdd:children:output -->` table row, check whether all children are now done, and notify the user on the parent Issue accordingly.

(See `implement.md` Phase C for the detailed steps — they apply verbatim here, including the multi-language parent reference.)

## Notes

- **Atoms never spawn other atoms.** All Agent-tool spawning happens here. The test work atom handles both single/child and parent paths internally and self-reviews inline; the orchestrator handles only the PR Final-equivalent review (`full` type for the test stage).
- **Reviews go on the Issue**, not the PR (the test output and QA checklist live on the Issue).
- **Manual QA stays in the main session.** It is inherently human-in-the-loop and cannot be automated by an atom.
- **Retry limit is 3 rounds total** (initial + 2 retries) for the AI review phase. Manual QA failures route back to Stage 3, not to a retry loop here.
