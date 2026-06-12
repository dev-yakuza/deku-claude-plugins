# ATOM: analyze_adversarial

**Single-subagent worker. MUST NOT spawn subagents. MUST NOT call the Agent tool.**

Independently REFUTES the analyze output. Reads Issue + analyze comment from GitHub, applies the adversarial lens, posts a review comment, returns a one-line verdict.

> **Bash Command Execution**: every shell snippet below is its own simple Bash tool call — no `&&`, `||`, `;`, `|`, `2>/dev/null`, `2>&1`, `>file`, `$(...)`, `VAR=$(...)`, or heredocs. For codebase exploration use the **Grep / Glob / Read** tools — do NOT use Bash `find` against `/`, `~`, `/Users`, or any path outside the repo root. See **Bash Command Execution Rules** in `<<SKILL_DIR>>/SKILL.md`.

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

3. Read the adversarial criteria: `<<SKILL_DIR>>/commands/ai-review-analyze-adversarial.md`. Also read Section E of `<<SKILL_DIR>>/commands/atoms/_review_helpers.md` for the general adversarial prompt.

4. **Codebase exploration (optional, within budget)** per `_review_helpers.md` Section D. Verify any code references in the analyze output exist as described.

5. Apply the adversarial lens — actively try to REFUTE the analyze output. Find at least one weakness; if none, justify why explicitly. Severity per the criteria file.

6. Determine verdict:
   - Any `critical` or `major` finding → **FAIL** (with summary)
   - Only `minor` findings or none → **PASS** (include in suggestions)

7. **Post a review comment** — follow `<<SKILL_DIR>>/commands/atoms/_review_helpers.md` Section F (mandatory temp-file pattern).
   - **Marker**: `<!-- sdd:review:analyze:adversarial -->`
   - **Temp file path**: `/tmp/sdd-review-analyze-adversarial-$1.md`
   - **Step 1** (Write tool): render the body using the standard format (see `analyze_review.md` template) with stage=analyze and role=adversarial. Include the `<!-- sdd:findings:json -->` block per `_review_helpers.md` Section B.
   - **Step 2** (Bash): search for existing comment id:
     ```bash
     gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | select(.body | contains("<!-- sdd:review:analyze:adversarial -->")) | .id'
     ```
   - **Step 3** (Bash):
     - Empty → `gh issue comment $1 --body-file /tmp/sdd-review-analyze-adversarial-$1.md`
     - Has id `<id>` → `gh api repos/<owner>/<repo>/issues/comments/<id> -X PATCH --field body=@/tmp/sdd-review-analyze-adversarial-$1.md`

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
- Do NOT use Edit/NotebookEdit. The Write tool is permitted **only** for rendering the comment body to `/tmp/sdd-review-analyze-adversarial-$1.md` per Section F of `_review_helpers.md`.
- Be independent.
