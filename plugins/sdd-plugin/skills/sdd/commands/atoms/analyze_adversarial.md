# ATOM: analyze_adversarial

**Single-subagent worker. MUST NOT spawn subagents. MUST NOT call the Agent tool.**

Independently REFUTES the analyze output. Reads Issue + analyze comment from GitHub, applies the adversarial lens, posts a review comment, returns a one-line verdict.

> **Bash Command Execution**: every shell snippet below is its own simple Bash tool call — no `&&`, `||`, `;`, `|`, `$(...)`, `VAR=$(...)`, or heredocs. See **Bash Command Execution Rules** in `${CLAUDE_SKILL_DIR}/SKILL.md`.

## Inputs

- `$1` — Issue number

The role is fixed as `adversarial` for this atom (no `$2`).

## Work

1. Read owner/repo + the Issue + the analyze output:
   ```bash
   gh repo view --json nameWithOwner -q .nameWithOwner
   gh issue view $1
   gh api repos/<owner>/<repo>/issues/$1/comments \
     --jq '.[] | select(.body | contains("sdd:analyze:output")) | .body'
   ```

2. If analyze output is missing → return `FAIL: analyze output not found on Issue #$1`.

3. Read the adversarial criteria: `${CLAUDE_SKILL_DIR}/commands/ai-review-analyze-adversarial.md`. Also read Section E of `${CLAUDE_SKILL_DIR}/commands/atoms/_review_helpers.md` for the general adversarial prompt.

4. **Codebase exploration (optional, within budget)** per `_review_helpers.md` Section D. Verify any code references in the analyze output exist as described.

5. Apply the adversarial lens — actively try to REFUTE the analyze output. Find at least one weakness; if none, justify why explicitly. Severity per the criteria file.

6. Determine verdict:
   - Any `critical` or `major` finding → **FAIL** (with summary)
   - Only `minor` findings or none → **PASS** (include in suggestions)

7. **Post a review comment** with marker `<!-- sdd:review:analyze:adversarial -->`. Duplicate-prevention: search for existing marker, update if found, else create.

   Comment body format:
   ```
   <!-- sdd:review:analyze:adversarial -->
   ## AI Review (analyze / adversarial)

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
   <!-- /sdd:review:analyze:adversarial -->
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
- Do NOT modify the analyze output comment. Only post your own review comment.
- You **MAY** use Read/Grep/Glob (Section D budget: 15 Read / 10 Grep / 5 Glob).
- Do NOT use Edit/Write/NotebookEdit.
- Be independent.
