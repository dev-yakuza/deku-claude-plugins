# ATOM: tdd_step_review

**Single-subagent worker. MUST NOT spawn subagents. MUST NOT call the Agent tool.**

Lightweight diff-only review between TDD steps (3-1 Red, 3-2 Green, 3-3 Refactor, 3-4 E2E). Reads the last step's git commit diff, applies step-specific criteria, posts a review comment to the Issue, returns a one-line verdict.

> **Bash Command Execution**: every shell snippet below is its own simple Bash tool call — no `&&`, `||`, `;`, `|`, `$(...)`, `VAR=$(...)`, or heredocs. See **Bash Command Execution Rules** in `${CLAUDE_SKILL_DIR}/SKILL.md`.

## Inputs

- `$1` — Issue number
- `$2` — step number: `1`, `2`, `3`, or `4` (matches TDD step 3-1, 3-2, 3-3, 3-4)
- `$3` — branch name
- `$4` — commit sha to review (from the step atom's return); if `EMPTY` (no commit, e.g. refactor empty), skip the review

## Work

1. **Handle empty commit case**:
   - If `$4` == `EMPTY` → return `OK PASS` immediately (nothing to review, nothing to post).

2. Resolve owner/repo + read the commit diff:
   ```bash
   gh repo view --json nameWithOwner -q .nameWithOwner
   git show --stat $4
   git show $4
   ```

3. Read the criteria: `${CLAUDE_SKILL_DIR}/commands/ai-review-implement-step.md`. Use the section matching `$2`:
   - `$2=1` → "Step 3-1: Red"
   - `$2=2` → "Step 3-2: Green"
   - `$2=3` → "Step 3-3: Refactor"
   - `$2=4` → "Step 3-4: E2E"

4. **Codebase exploration (lighter budget)** per `${CLAUDE_SKILL_DIR}/commands/atoms/_review_helpers.md` Section D: max **5 Read / 3 Grep / 0 Glob**. Use sparingly — this is a quick step review, not a full audit.

5. Apply the step-specific criteria to the diff. Severity definitions:
   - **critical**: This step is broken in a way that compounds into the next step
   - **major**: Significant issue in this step that should be fixed before proceeding
   - **minor**: Improvement suggestion (does not block)

6. Determine verdict:
   - critical/major → **FAIL** (the orchestrator will re-spawn this step's atom)
   - only minor or none → **PASS** (proceed to next step)

7. **Post a review comment** to the **Issue** (not the PR — PR may not exist yet) with marker `<!-- sdd:review:implement:step-$2 -->`. Standard duplicate-prevention.

   Comment body format:
   ```
   <!-- sdd:review:implement:step-$2 -->
   ## AI Review (implement / step-$2)

   **Verdict:** PASS | FAIL
   **Model:** <opus|sonnet|haiku>
   **Commit:** <$4>

   ### Issues
   - **[critical]** path/to/file.ts:42 — <description>
   - **[major]** <description>
   - **[minor]** <description>

   ### Suggestions
   <if any>

   <!-- sdd:findings:json -->
   ```json
   {<structured findings per _review_helpers.md Section B, stage="implement", role="step-$2">}
   ```
   <!-- /sdd:findings:json -->
   <!-- /sdd:review:implement:step-$2 -->
   ```

## Return contract

```
>>> RESULT <<<
OK PASS
```
or
```
>>> RESULT <<<
OK FAIL: <one-line severity summary>
```
or
```
>>> RESULT <<<
FAIL: <one-line reason — only for atom errors>
```

## Hard rules

- Single-subagent atom. Do NOT invoke the Agent tool or Skill tool.
- Do NOT modify any commit, file, or PR. Read-only except for the review comment.
- You **MAY** use Read/Grep (Section D lighter budget: 5 Read / 3 Grep / 0 Glob).
- Do NOT use Edit/Write/NotebookEdit.
- Be independent.
