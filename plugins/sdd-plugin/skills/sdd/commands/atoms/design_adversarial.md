# ATOM: design_adversarial

**Single-subagent worker. MUST NOT spawn subagents. MUST NOT call the Agent tool.**

Independently REFUTES the design output. Reads Issue + analyze + design comments, applies the adversarial lens, posts a review comment, returns a one-line verdict.

> **Bash Command Execution**: every shell snippet below is its own simple Bash tool call — no `&&`, `||`, `;`, `|`, `$(...)`, `VAR=$(...)`, or heredocs. See **Bash Command Execution Rules** in `${CLAUDE_SKILL_DIR}/SKILL.md`.

## Inputs

- `$1` — Issue number

The role is fixed as `adversarial` (no `$2`).

## Work

1. Read owner/repo + Issue + analyze + design outputs:
   ```bash
   gh repo view --json nameWithOwner -q .nameWithOwner
   gh issue view $1
   gh api repos/<owner>/<repo>/issues/$1/comments \
     --jq '.[] | select(.body | contains("sdd:analyze:output") or contains("sdd:design:output")) | .body'
   ```

2. If design output is missing → return `FAIL: design output not found on Issue #$1`.

3. If this is a child Issue, also read the parent's design output for consistency context:
   ```bash
   gh api repos/<owner>/<repo>/issues/<parent>/comments \
     --jq '.[] | select(.body | contains("sdd:design:output")) | .body'
   ```

4. Read the adversarial criteria: `${CLAUDE_SKILL_DIR}/commands/ai-review-design-adversarial.md`. Also Section E of `${CLAUDE_SKILL_DIR}/commands/atoms/_review_helpers.md`.

5. **Codebase exploration (mandatory for design adversarial)** per `_review_helpers.md` Section D. Verify at least:
   - 1-2 file paths cited in the design exist
   - 1 architectural pattern claim by reading the cited code

6. Apply the adversarial lens — REFUTE the design. Find at least one weakness; if none, justify why explicitly.

7. Determine verdict:
   - Any `critical` or `major` → **FAIL**
   - Only `minor` or none → **PASS**

8. **Post a review comment** with marker `<!-- sdd:review:design:adversarial -->`. Duplicate-prevention as standard.

   Comment body follows the standard format (see `analyze_review.md` template) with stage=design and role=adversarial. Include the `<!-- sdd:findings:json -->` block per `_review_helpers.md` Section B.

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
- Do NOT modify the design output or children comments. Only post your own review comment.
- You **MAY** use Read/Grep/Glob (Section D budget).
- Do NOT use Edit/Write/NotebookEdit.
- Be independent.
