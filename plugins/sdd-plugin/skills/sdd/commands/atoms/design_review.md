# ATOM: design_review

**Single-subagent worker. MUST NOT spawn subagents. MUST NOT call the Agent tool.**

Independently reviews the design output that was posted to an Issue. Reads the analyze + design comments from GitHub, applies the criteria from `ai-review-design.md`, posts a review comment, returns a one-line verdict.

> **Bash Command Execution**: run every shell snippet below as its own simple Bash tool call — no `&&`, `||`, `;`, `|`, `$(...)`, `VAR=$(...)`, or heredocs. Inline literal values; do not use shell variables. See **Bash Command Execution Rules** in `${CLAUDE_SKILL_DIR}/SKILL.md`.

## Inputs

- `$1` — Issue number
- `$2` — review role: `completeness` or `quality`

The orchestrator invokes this atom **twice in parallel** in a single message — once with `$2=completeness`, once with `$2=quality`.

## Work

1. Resolve owner/repo and read the Issue + analyze + design comments:
   ```bash
   gh repo view --json nameWithOwner -q .nameWithOwner    # Bash call 1: observe owner/repo from output; inline as <owner>/<repo> below (no shell variables)
   gh issue view $1
   gh api repos/<owner>/<repo>/issues/$1/comments \
     --jq '.[] | select(.body | contains("sdd:analyze:output") or contains("sdd:design:output")) | .body'
   ```

2. If the design output is missing → return `FAIL: design output not found on Issue #$1`.

3. If this is a child Issue, also read the parent's design output for consistency check:
   ```bash
   gh api repos/<owner>/<repo>/issues/<parent>/comments \
     --jq '.[] | select(.body | contains("sdd:design:output")) | .body'
   ```

4. Read the stage-specific criteria from `${CLAUDE_SKILL_DIR}/commands/ai-review-design.md`.

5. Apply criteria according to your role (`$2`):

   ### If `$2` is `completeness`:
   Focus on **requirements coverage and cross-stage consistency**.
   - Apply the **Required Checklist** from `ai-review-design.md`. Mark each item pass/fail with severity.
   - Apply the **Cross-stage Check**: compare against analyze output. Are all features and requirements reflected in the design?
   - For child Issues: verify consistency with the parent's design (architecture decisions, PR split rationale).
   - Report consistency issues with severity.

   ### If `$2` is `quality`:
   Focus on **quality, risks, and issues beyond the checklist**.
   - Apply the **Additional Review** criteria from `ai-review-design.md`.
   - Look for feasibility concerns, maintainability issues, architectural anti-patterns, missing edge cases, unstated assumptions.
   - Report issues with severity.

   Severity definitions:
   - **critical**: Must fix — incorrect approach, missing requirement, security risk, will not work
   - **major**: Should fix — inconsistency with analyze, poor PR-split, unclear specification, significant maintainability concern
   - **minor**: Nice to fix — naming, minor refactor, style, additional suggestion

6. Determine your verdict:
   - Any `critical` or `major` issue → `FAIL` (with summary)
   - Only `minor` issues → `PASS` (include suggestions in the comment)
   - No issues → `PASS`

   Do NOT combine verdicts — the orchestrator merges with the other reviewer's.

7. **Post a review comment** with the marker `<!-- sdd:review:design:<role> -->`. Use duplicate prevention: search marker → update if exists, else create.

   Comment body format:
   ```
   <!-- sdd:review:design:<role> -->
   ## AI Review (design / <role>)

   **Verdict:** PASS | FAIL

   ### Issues
   - **[critical]** <description>
   - **[major]** <description>
   - **[minor]** <description>

   ### Suggestions
   <if any>
   <!-- /sdd:review:design:<role> -->
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
OK FAIL: <one-line severity summary, e.g. "1 critical, 2 major">
```
or
```
>>> RESULT <<<
FAIL: <one-line reason — only for atom errors, not review verdicts>
```

- `OK PASS` — review completed, no critical/major issues.
- `OK FAIL: <summary>` — review completed, critical/major issues found.
- `FAIL: <reason>` — the atom itself errored.

Do NOT return the full review body — it's already in the Issue comment.

## Hard rules

- You are a single-subagent atom. Do NOT invoke the Agent tool. Do NOT spawn subagents.
- Do NOT modify the design output comment. Only post your own review comment.
- Do NOT invoke `/sdd <command>` or the Skill tool.
- Be independent: evaluate the design on its own merits against the criteria, not by trusting that prior reviewers (analyze stage) were correct.
