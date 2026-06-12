# ATOM: parent_integration_review

**Single-subagent worker. MUST NOT spawn subagents. MUST NOT call the Agent tool.**

Cross-stage synthesis review at the **parent Issue level**. Reads parent's analyze + design + children:output + each child's analyze/design/implement review summaries, applies the criteria from `ai-review-parent-integration.md`, posts a review comment on the parent Issue, returns a one-line verdict.

Runs only on **parent Issues** during the test stage. Invoked by `test.md` orchestrator when `test_work.md` returns `OK PARENT ...`.

> **Bash Command Execution**: every shell snippet below is its own simple Bash tool call — no `&&`, `||`, `;`, `|`, `2>/dev/null`, `2>&1`, `>file`, `$(...)`, `VAR=$(...)`, or heredocs. For codebase exploration use the **Grep / Glob / Read** tools — do NOT use Bash `find` against `/`, `~`, `/Users`, or any path outside the repo root. See **Bash Command Execution Rules** in `<<SKILL_DIR>>/SKILL.md`.

## Inputs

- `$1` — parent Issue number (already validated as a parent by the orchestrator — has `<!-- sdd:children:output -->`)

## Work

1. Resolve owner/repo + read the parent Issue body and stage outputs:
   ```bash
   gh repo view --json nameWithOwner -q .nameWithOwner
   gh issue view $1
   gh api repos/<owner>/<repo>/issues/$1/comments \
     --jq '.[] | select(.body | contains("sdd:analyze:output") or contains("sdd:design:output") or contains("sdd:children:output") or contains("sdd:test:output")) | .body'
   ```

2. If `<!-- sdd:children:output -->` is missing → return `FAIL: parent has no children comment on Issue #$1`.

3. Extract child Issue numbers from `<!-- sdd:children:output -->` (parse the table rows).

4. For each child, fetch the child's analyze, design, and implement review summaries (structured findings JSON blocks). Each child:
   ```bash
   gh api repos/<owner>/<repo>/issues/<child>/comments \
     --jq '.[] | select(.body | contains("sdd:review:analyze:") or contains("sdd:review:design:") or contains("sdd:review:implement:")) | .body'
   ```
   Extract the `<!-- sdd:findings:json -->` blocks. Also fetch each child's PR diff (find via `gh pr list --search "Refs #<child>"`).

5. Read the criteria: `<<SKILL_DIR>>/commands/ai-review-parent-integration.md`.

6. **Codebase exploration (mandatory)** per `<<SKILL_DIR>>/commands/atoms/_review_helpers.md` Section D:
   - Read the interface/contract files where children connect
   - Verify cross-child invariants hold in the actual code
   - Budget: 15 Read / 10 Grep / 5 Glob

7. Apply the synthesis criteria:
   - Feature distribution coverage across children
   - Cross-child design consistency
   - Cross-child implementation gaps
   - Aggregate quality signals (similar rule_ids across children)
   - Closure verification against parent's Definition of Done

8. Determine verdict: critical/major → FAIL; only minor or none → PASS.

9. **Post a review comment on the parent Issue** — follow `<<SKILL_DIR>>/commands/atoms/_review_helpers.md` Section F (mandatory temp-file pattern). The marker is defined in `SKILL.md`.
    - **Marker**: `<!-- sdd:review:parent -->`
    - **Temp file path**: `/tmp/sdd-review-parent-$1.md`
    - **Step 1** (Write tool): render the body (format below) into the temp file.
    - **Step 2** (Bash): search for existing comment id:
      ```bash
      gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | select(.body | contains("<!-- sdd:review:parent -->")) | .id'
      ```
    - **Step 3** (Bash):
      - Empty → `gh issue comment $1 --body-file /tmp/sdd-review-parent-$1.md`
      - Has id `<id>` → `gh api repos/<owner>/<repo>/issues/comments/<id> -X PATCH --field body=@/tmp/sdd-review-parent-$1.md`

    Comment body format:
    ```
    <!-- sdd:review:parent -->
    ## AI Review (parent integration)

    **Verdict:** PASS | FAIL
    **Model:** <opus|sonnet|haiku>
    **Children reviewed:** #A, #B, #C, ...

    ### Issues
    - **[critical]** <description>
    - **[major]** <description>
    - **[minor]** <description>

    ### Suggestions
    <if any>

    <!-- sdd:findings:json -->
    ```json
    {<structured findings per _review_helpers.md Section B, stage="parent", role="parent-integration">}
    ```
    <!-- /sdd:findings:json -->
    <!-- /sdd:review:parent -->
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
- Do NOT modify any code, child Issues, or PRs.
- You **MAY** use Read/Grep/Glob (Section D budget).
- Do NOT use Edit/NotebookEdit. The Write tool is permitted **only** for rendering the parent integration review body to `/tmp/sdd-review-parent-$1.md` per Section F of `_review_helpers.md`.
- Be independent: do not read other reviewers' verdicts before forming yours.
