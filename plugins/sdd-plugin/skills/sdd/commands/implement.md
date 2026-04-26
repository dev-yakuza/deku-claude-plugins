# IMPLEMENT

**Stage 3: Implementation - TDD Cycle (Red → Green → Refactor)**

## Rules
- Do NOT set Claude as co-author in git commits.
- Check existing git history for branch naming and commit message conventions, and follow the same format.

## Determine Issue type:

1. Check if this Issue has child Issues:
   ```bash
   gh api repos/{owner}/{repo}/issues/$1/comments --jq '.[] | select(.body | contains("sdd:children:output")) | .body' | head -1
   ```
2. **Parent Issue (has children)**: Do NOT implement directly. Instead:
   - List child Issues and their current status
   - Ask user which child Issue to work on
   - Execute **ANALYZE** or **RESUME** on the selected child Issue
3. **Single Issue or Child Issue (no children)**: Execute TDD cycle below

## TDD Cycle (single Issue or child Issue):

Test scope: Unit tests / UI tests (widget tests, golden tests, etc.)

### Phase 1: Plan (via subagent)

Use the **Agent tool** to spawn a subagent with the following instructions:

> **Subagent instructions:**
>
> You are executing SDD Stage 3 (Implement) - Plan phase for Issue $1.
>
> 1. Read design output from Issue comments
> 2. Create feature branch:
>    - Single Issue: `feat/<feature-name>`
>    - Child Issue: `feat/<parent-feature>/<child-feature>` (e.g. `feat/user-profile/avatar-upload`)
> 3. Write test plan for this PR
> 4. Write implementation plan based on test plan
> 5. **AI Review**: Read `${CLAUDE_SKILL_DIR}/commands/ai-review.md` and execute with the plan (stage: **implement**, review point: **Plan (3-0)**)
> 6. Return the plan along with review loop results (rounds, issues fixed, verdict)

**User review**: Check skip-review setting (see Common Definitions → Skip Review Setting)
- If `implement` is in skip-review → log "User review skipped (skip-review: implement)" and proceed
- Otherwise → present the subagent's plan and review loop results, confirm plan direction before proceeding

### Phase 2: TDD + PR (via subagent)

Use the **Agent tool** to spawn a subagent with the following instructions:

> **Subagent instructions:**
>
> You are executing SDD Stage 3 (Implement) - TDD cycle for Issue $1.
> Read the design output from Issue comments for context.
>
> #### 3-1. Red: Write Failing Tests
> 1. Write test code based on the plan
> 2. Run tests → confirm failure (Red)
> 3. **AI Review**: Read `${CLAUDE_SKILL_DIR}/commands/ai-review.md` and execute with the test code (stage: **implement**, review point: **Red - Test Code (3-1)**)
>
> #### 3-2. Green: Minimal Implementation
> 1. Implement minimal code to pass tests
> 2. Run tests → confirm pass (Green)
> 3. **AI Review**: Read `${CLAUDE_SKILL_DIR}/commands/ai-review.md` and execute with the implementation code (stage: **implement**, review point: **Green - Implementation (3-2)**)
>
> #### 3-3. Refactor: Improve Code
> 1. Remove duplication, improve readability, clean up structure
> 2. Run tests → confirm still passing (Green)
> 3. **AI Review**: Read `${CLAUDE_SKILL_DIR}/commands/ai-review.md` and execute with the refactored code (stage: **implement**, review point: **Refactor (3-3)**)
>
> #### 3-4. PR Creation
> 1. Summarize changes
> 2. Create manual test checklist for this PR's scope:
>    - Based on the changes made, list items a reviewer should manually verify
>    - Focus on UI behavior, user flows, edge cases that automated tests don't cover
>    - Format as a markdown checklist (e.g. `- [ ] Verify button click navigates to...`)
> 3. Create PR with manual test checklist included:
>    - Single Issue: `gh pr create --title "..." --body "Refs #$1\n\n...\n\n## Manual Test Checklist\n<checklist>"`
>    - Child Issue: `gh pr create --title "..." --body "Refs #$1\nParent Issue: #<parent>\n\n...\n\n## Manual Test Checklist\n<checklist>"`
> 4. Re-run all tests → confirm pass
> 5. **AI Review**: Read `${CLAUDE_SKILL_DIR}/commands/ai-review.md` and execute with the implementation changes (stage: **implement**, review point: **PR Final (3-4)**)
> 6. Return the PR URL, change summary, and review loop results (rounds, issues fixed, verdict)

**User review**: Check skip-review setting (see Common Definitions → Skip Review Setting)
- If `pr` is in skip-review → log "User review skipped (skip-review: pr)", update label to `sdd:test`, then:
  - If `qa` is also in skip-review → **auto-proceed**: use the **Agent tool** to spawn a subagent that executes `/sdd test $1`
  - Otherwise → **stop here** (PR created, label updated — human reviews PR and runs QA)
- Otherwise → present the subagent's results (PR URL, change summary, review loop results), final confirmation. On approval: update label to `sdd:test`

## After child Issue reaches `sdd:done`:

If this Issue is a child Issue (Issue body contains `Parent Issue: #<number>`):

1. Find parent Issue number from the `<!-- sdd:child-issue -->` block in Issue body
2. Find the children comment on parent Issue using `gh api` with `--jq` to get the **exact comment** with both start and end markers:
   ```bash
   # Use jq to find the single comment containing both markers — avoids false matches
   gh api repos/{owner}/{repo}/issues/<parent>/comments \
     --jq '.[] | select((.body | contains("<!-- sdd:children:output -->")) and (.body | contains("<!-- /sdd:children:output -->"))) | {id, body}'
   ```
   - If no matching comment found → warn user and skip update
   - If multiple comments match → use the **most recent one** (last in the array)
3. Update the children comment — replace this child's status label in the table row:
   ```bash
   COMMENT_ID=<id from step 2>
   # Read the comment body, replace the status for this child Issue's row, then update
   gh api repos/{owner}/{repo}/issues/comments/$COMMENT_ID \
     -X PATCH --field body="<updated body with new status>"
   ```
4. Verify the update was applied by re-reading the comment
5. Check if ALL child Issues are now `sdd:done`:
   - Read each child Issue's labels directly (do NOT rely only on the comment table)
   - If all `sdd:done` → add a comment to the parent Issue notifying all children are complete, and suggest running `/sdd test <parent>` or `/sdd resume <parent>`
   - If not → report remaining children to the user and ask which child to work on next
