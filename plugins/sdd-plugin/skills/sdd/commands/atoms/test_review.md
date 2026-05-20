# ATOM: test_review

**Single-subagent worker. MUST NOT spawn subagents. MUST NOT call the Agent tool.**

Independently reviews the test output that was posted to an Issue. Reads the analyze + design + test comments from GitHub, applies the criteria from `ai-review-test.md`, posts a review comment, returns a one-line verdict.

## Inputs

- `$1` — Issue number
- `$2` — review role: `completeness` or `quality`

The orchestrator invokes this atom **twice in parallel** in a single message — once with `$2=completeness`, once with `$2=quality`.

## Work

1. Resolve owner/repo and read the Issue + relevant stage outputs:
   ```bash
   OWNER_REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
   gh issue view $1
   gh api repos/$OWNER_REPO/issues/$1/comments \
     --jq '.[] | select(.body | contains("sdd:analyze:output") or contains("sdd:design:output") or contains("sdd:test:output")) | .body'
   ```

2. If the test output is missing → return `FAIL: test output not found on Issue #$1`.

3. Detect parent vs single/child from the test output body (`Path:` line) and from the presence of `<!-- sdd:children:output -->`.
   - **Parent path**: also read children's PRs for cross-reference (find via children comment numbers).
   - **Single/Child path**: also read the implementation PR diff for cross-reference (find via `gh pr list --search "Refs #$1"`).

4. Read the stage-specific criteria from `${CLAUDE_SKILL_DIR}/commands/ai-review-test.md`.

5. Apply criteria according to your role (`$2`):

   ### If `$2` is `completeness`:
   Focus on **requirements coverage and cross-stage consistency**.
   - **Required Checklist** from `ai-review-test.md`:
     - E2E tests cover the main user flows from the requirements
     - Edge cases identified in analyze/design are tested
     - Regression risks for existing functionality are addressed
     - Test assertions are specific and meaningful
   - **Cross-stage Check**: compare against analyze + design outputs — are all requirements and risk areas covered by tests?
   - Report issues with severity.

   ### If `$2` is `quality`:
   Focus on **quality, risks, and issues beyond the checklist**.
   - **Additional Review** from `ai-review-test.md`:
     - Test reliability (flakiness risk, timing dependencies, external state assumptions)
     - Coverage gaps not enumerated in the design
     - Missing scenarios (concurrency, error paths, boundary)
     - QA checklist completeness for manual items
   - Report issues with severity.

   Severity definitions:
   - **critical**: Must fix — missing requirement, broken test, security gap not covered
   - **major**: Should fix — significant coverage gap, unreliable test, inconsistency with design
   - **minor**: Nice to fix — naming, style, additional suggestion

6. Determine verdict:
   - Any `critical` or `major` issue → `FAIL` (with summary)
   - Only `minor` issues → `PASS` (suggestions in the comment)
   - No issues → `PASS`

7. **Post a review comment on the Issue** with the marker `<!-- sdd:review:test:<role> -->`. Use duplicate prevention.

   Comment body format:
   ```
   <!-- sdd:review:test:<role> -->
   ## AI Review (test / <role>)

   **Verdict:** PASS | FAIL

   ### Issues
   - **[critical]** <description>
   - **[major]** <description>
   - **[minor]** <description>

   ### Suggestions
   <if any>
   <!-- /sdd:review:test:<role> -->
   ```

## Return contract

Return EXACTLY ONE LINE on its own, prefixed by `>>> RESULT <<<`:

```
>>> RESULT <<<
OK PASS
```
or
```
>>> RESULT <<<
OK FAIL: <one-line severity summary, e.g. "1 major, 2 minor">
```
or
```
>>> RESULT <<<
FAIL: <one-line reason — only for atom errors, not review verdicts>
```

## Hard rules

- You are a single-subagent atom. Do NOT invoke the Agent tool. Do NOT spawn subagents.
- Do NOT invoke `/sdd <command>` or the Skill tool.
- Do NOT modify the test output comment. Only post your own review comment.
- Be independent: evaluate test coverage on its own merits against the criteria.
