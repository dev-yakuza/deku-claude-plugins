# ATOM: design_review

**Single-subagent worker. MUST NOT spawn subagents. MUST NOT call the Agent tool.**

Independently reviews the design output. Reads analyze + design comments, applies role-specific criteria, posts a review comment, returns a one-line verdict.

> **Bash Command Execution**: every shell snippet below is its own simple Bash tool call — no `&&`, `||`, `;`, `|`, `2>/dev/null`, `2>&1`, `>file`, `$(...)`, `VAR=$(...)`, or heredocs. For codebase exploration use the **Grep / Glob / Read** tools — do NOT use Bash `find` against `/`, `~`, `/Users`, or any path outside the repo root. See **Bash Command Execution Rules** in `<<SKILL_DIR>>/SKILL.md`.

## Inputs

- `$1` — Issue number
- `$2` — review role: `completeness` or `quality`

The orchestrator invokes this atom **twice in parallel** in a single message. The `adversarial` role is handled by `design_adversarial.md`.

## Work

1. Read owner/repo + Issue + analyze + design comments:
   ```bash
   gh repo view --json nameWithOwner -q .nameWithOwner
   gh issue view $1
   gh api repos/<owner>/<repo>/issues/$1/comments \
     --jq '.[] | select(.body | contains("sdd:analyze:output") or contains("sdd:design:output")) | .body'
   ```

2. If design output missing → return `FAIL: design output not found on Issue #$1`.

3. If this is a child Issue, also read the parent's design output:
   ```bash
   gh api repos/<owner>/<repo>/issues/<parent>/comments \
     --jq '.[] | select(.body | contains("sdd:design:output")) | .body'
   ```

4. Read the role-specific criteria file:
   - `$2=completeness` → `<<SKILL_DIR>>/commands/atoms/rubrics/design-completeness.md`
   - `$2=quality` → `<<SKILL_DIR>>/commands/atoms/rubrics/design-quality.md`

5. **Codebase exploration** per `<<SKILL_DIR>>/commands/atoms/_review_helpers.md` Section D. Both roles benefit from verifying design's file/symbol references actually exist. Budget: 15 Read / 10 Grep / 5 Glob.

6. Apply the criteria. Standard severity definitions:
   - **critical**: Must fix — incorrect approach, missing requirement, will not work
   - **major**: Should fix — inconsistency, poor PR-split, significant concern
   - **minor**: Nice to fix

7. Determine verdict: critical/major → FAIL; only minor or none → PASS.

8. **Post a review comment** — follow `<<SKILL_DIR>>/commands/atoms/_review_helpers.md` Section F (mandatory temp-file pattern).
   - **Marker**: `<!-- sdd:review:design:<role> -->` (substitute `<role>` = `$2`)
   - **Temp file path**: `/tmp/sdd-review-design-<role>-$1.md`
   - **Step 1** (Write tool): render body using the standard format (see `analyze_review.md` template) with stage=design and role=`<role>`. Include the `<!-- sdd:findings:json -->` block per `_review_helpers.md` Section B.
   - **Step 2** (Bash): search for existing comment id:
     ```bash
     gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | select(.body | contains("<!-- sdd:review:design:<role> -->")) | .id'
     ```
   - **Step 3** (Bash):
     - Empty → `gh issue comment $1 --body-file /tmp/sdd-review-design-<role>-$1.md`
     - Has id `<id>` → `gh api repos/<owner>/<repo>/issues/comments/<id> -X PATCH --field body=@/tmp/sdd-review-design-<role>-$1.md`

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
- Do NOT modify the design output or children comments.
- You **MAY** use Read/Grep/Glob (Section D budget).
- Do NOT use Edit/NotebookEdit. The Write tool is permitted **only** for rendering the comment body to `/tmp/sdd-review-design-<role>-$1.md` per Section F of `_review_helpers.md`.
- Be independent.
