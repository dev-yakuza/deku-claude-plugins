# ATOM: analyze_review

**Single-subagent worker. MUST NOT spawn subagents. MUST NOT call the Agent tool.**

Independently reviews the analyze output that was posted to an Issue. Reads the analyze comment from GitHub, applies the criteria from `ai-review-analyze.md`, posts a review comment, returns a one-line verdict.

## Inputs

- `$1` — Issue number
- `$2` — review role: `completeness` or `quality`

The orchestrator invokes this atom **twice in parallel** in a single message — once with `$2=completeness`, once with `$2=quality`.

## Work

1. Read the Issue body and the analyze output comment:
   ```bash
   OWNER_REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
   gh issue view $1
   gh api repos/$OWNER_REPO/issues/$1/comments \
     --jq '.[] | select(.body | contains("sdd:analyze:output")) | .body'
   ```

2. If the analyze output is missing → return `FAIL: analyze output not found on Issue #$1`.

3. Read the stage-specific criteria from `${CLAUDE_SKILL_DIR}/commands/ai-review-analyze.md`.

4. Apply the criteria according to your role (`$2`):

   ### If `$2` is `completeness`:
   Focus on **requirements coverage and cross-stage consistency**.
   - Apply the **Required Checklist** from `ai-review-analyze.md`. Mark each item pass/fail with severity.
   - Apply the **Cross-stage Check** from `ai-review-analyze.md` (for analyze stage, this is N/A — skip).
   - Report any consistency issues found.

   ### If `$2` is `quality`:
   Focus on **quality, risks, and issues beyond the checklist**.
   - Apply the **Additional Review** criteria from `ai-review-analyze.md`.
   - Look for risks, edge cases, ambiguities, pattern violations, unstated assumptions.
   - Report issues with severity.

   Use the following severity definitions:
   - **critical**: Must fix — incorrect logic, missing requirement, security risk
   - **major**: Should fix — inconsistency, poor coverage, unclear specification
   - **minor**: Nice to fix — style, naming, minor improvement suggestions

5. Determine your verdict:
   - Any `critical` or `major` issue → `FAIL` (with summary)
   - Only `minor` issues → `PASS` (include suggestions in the comment)
   - No issues → `PASS`

   Do NOT include a combined verdict — the orchestrator merges your verdict with the other reviewer's.

6. **Post a review comment** to the Issue with the marker `<!-- sdd:review:analyze:<role> -->` (where `<role>` is `completeness` or `quality`). Use duplicate prevention per Common Definitions:
   - Search for the matching marker
   - If found → update that comment
   - If not → create new comment

   Comment body format:
   ```
   <!-- sdd:review:analyze:<role> -->
   ## AI Review (analyze / <role>)

   **Verdict:** PASS | FAIL

   ### Issues
   - **[critical]** <description>
   - **[major]** <description>
   - **[minor]** <description>

   ### Suggestions
   <if any>
   <!-- /sdd:review:analyze:<role> -->
   ```

## Return contract

Return EXACTLY ONE LINE on its own, prefixed by the marker `>>> RESULT <<<` on the preceding line. Format:

```
>>> RESULT <<<
OK PASS
```
or
```
>>> RESULT <<<
OK FAIL: <one-line severity summary, e.g. "2 critical, 1 major">
```
or
```
>>> RESULT <<<
FAIL: <one-line reason — only for atom errors, not review verdicts>
```

- `OK PASS` — review completed, no critical/major issues.
- `OK FAIL: <summary>` — review completed, critical/major issues found. The orchestrator will combine with the other reviewer's verdict and decide whether to retry.
- `FAIL: <reason>` — the atom itself errored (could not read analyze output, gh CLI error, etc.).

Do NOT return the full review body — it's already in the Issue comment.

## Hard rules

- You are a single-subagent atom. Do NOT invoke the Agent tool. Do NOT spawn subagents.
- Do NOT modify the analyze output comment. Only post your own review comment.
- Do NOT invoke `/sdd <command>` or the Skill tool.
- Be independent: do not assume the analyze output is correct just because it exists. Evaluate it on its own merits against the criteria.
