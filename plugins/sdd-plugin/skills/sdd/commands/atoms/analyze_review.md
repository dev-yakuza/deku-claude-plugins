# ATOM: analyze_review

**Single-subagent worker. MUST NOT spawn subagents. MUST NOT call the Agent tool.**

Independently reviews the analyze output. Reads the Issue + analyze comment, applies the role-specific criteria, posts a review comment, returns a one-line verdict.

> **Bash Command Execution**: every shell snippet below is its own simple Bash tool call — no `&&`, `||`, `;`, `|`, `2>/dev/null`, `2>&1`, `>file`, `$(...)`, `VAR=$(...)`, or heredocs. For codebase exploration use the **Grep / Glob / Read** tools — do NOT use Bash `find` against `/`, `~`, `/Users`, or any path outside the repo root. See **Bash Command Execution Rules** in `<<SKILL_DIR>>/SKILL.md`.

## Inputs

- `$1` — Issue number
- `$2` — review role: `completeness` or `quality`

The orchestrator invokes this atom **twice in parallel** in a single message. The `adversarial` role is handled by `analyze_adversarial.md`.

## Work

1. Read owner/repo + Issue + analyze output:
   ```bash
   gh repo view --json nameWithOwner -q .nameWithOwner
   gh issue view $1
   gh api repos/<owner>/<repo>/issues/$1/comments \
     --jq '.[] | select(.body | contains("sdd:analyze:output")) | .body'
   ```

2. If analyze output is missing → return `FAIL: analyze output not found on Issue #$1`.

3. Read the role-specific criteria file based on `$2`:
   - `$2=completeness` → `<<SKILL_DIR>>/commands/ai-review-analyze-completeness.md`
   - `$2=quality` → `<<SKILL_DIR>>/commands/ai-review-analyze-quality.md`

4. **Codebase exploration (optional, within budget)** per `<<SKILL_DIR>>/commands/atoms/_review_helpers.md` Section D. Verify any code references in the analyze output exist as described.

5. Apply the criteria. Standard severity definitions:
   - **critical**: Must fix — incorrect logic, missing requirement, security risk
   - **major**: Should fix — inconsistency, poor coverage, unclear specification
   - **minor**: Nice to fix — style, naming, minor improvement

6. Determine verdict:
   - Any `critical` or `major` → **FAIL** (with summary)
   - Only `minor` or none → **PASS** (suggestions included)
   - Do NOT combine with other reviewers — the orchestrator merges verdicts.

7. **Post a review comment** to the Issue — follow `<<SKILL_DIR>>/commands/atoms/_review_helpers.md` Section F (mandatory temp-file pattern).
   - **Marker**: `<!-- sdd:review:analyze:<role> -->` (substitute `<role>` = `$2`)
   - **Temp file path**: `/tmp/sdd-review-analyze-<role>-$1.md`
   - **Step 1** (Write tool): render the body below into the temp file.
   - **Step 2** (Bash): search for existing comment id:
     ```bash
     gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | select(.body | contains("<!-- sdd:review:analyze:<role> -->")) | .id'
     ```
   - **Step 3** (Bash):
     - Empty → `gh issue comment $1 --body-file /tmp/sdd-review-analyze-<role>-$1.md`
     - Has id `<id>` → `gh api repos/<owner>/<repo>/issues/comments/<id> -X PATCH --field body=@/tmp/sdd-review-analyze-<role>-$1.md`

   Comment body format:
   ```
   <!-- sdd:review:analyze:<role> -->
   ## AI Review (analyze / <role>)

   **Verdict:** PASS | FAIL
   **Model:** <opus|sonnet|haiku>

   ### Issues
   - **[critical]** <description>
   - **[major]** <description>
   - **[minor]** <description>

   ### Suggestions
   <if any>

   <!-- sdd:findings:json -->
   ```json
   {<structured findings per _review_helpers.md Section B>}
   ```
   <!-- /sdd:findings:json -->
   <!-- /sdd:review:analyze:<role> -->
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
OK FAIL: <one-line severity summary>
```
or
```
>>> RESULT <<<
FAIL: <one-line reason — only for atom errors>
```

## Hard rules

- Single-subagent atom. Do NOT invoke the Agent tool or Skill tool.
- Do NOT modify the analyze output comment. Only post your own review comment.
- You **MAY** use Read/Grep/Glob to verify references against actual code (Section D budget: 15 Read / 10 Grep / 5 Glob).
- Do NOT use Edit/NotebookEdit. The Write tool is permitted **only** for rendering the comment body to `/tmp/sdd-review-analyze-<role>-$1.md` per Section F of `_review_helpers.md`.
- Be independent: do not assume the analyze output is correct just because it exists. Evaluate it on its own merits.
