# ATOM: implement_adversarial

**Single-subagent worker. MUST NOT spawn subagents. MUST NOT call the Agent tool.**

Independently REFUTES the PR Final state. Reads PR diff + Issue context, applies the adversarial lens, posts a review comment on the PR, returns a one-line verdict.

> **Bash Command Execution**: every shell snippet below is its own simple Bash tool call — no `&&`, `||`, `;`, `|`, `2>/dev/null`, `2>&1`, `>file`, `$(...)`, `VAR=$(...)`, or heredocs. For codebase exploration use the **Grep / Glob / Read** tools — do NOT use Bash `find` against `/`, `~`, `/Users`, or any path outside the repo root. See **Bash Command Execution Rules** in `<<SKILL_DIR>>/SKILL.md`.

## Inputs

- `$1` — Issue number (the SDD pipeline's Issue, not the PR)

Role is fixed as `adversarial` (no `$2`).

## Work

1. Resolve owner/repo:
   ```bash
   gh repo view --json nameWithOwner -q .nameWithOwner
   ```

2. Find the PR for this Issue:
   ```bash
   gh pr list --search "Refs #$1" --state open --json number --jq '.[0].number'
   ```
   If no PR → return `FAIL: PR for Issue #$1 not found`.

3. Read the PR diff and body:
   ```bash
   gh pr view <PR_NUM>
   gh pr diff <PR_NUM>
   ```

4. Read the Issue + design + plan comments:
   ```bash
   gh issue view $1
   gh api repos/<owner>/<repo>/issues/$1/comments \
     --jq '.[] | select(.body | contains("sdd:design:output") or contains("sdd:implement:plan")) | .body'
   ```

5. Read the adversarial criteria: `<<SKILL_DIR>>/commands/ai-review-implement-adversarial.md`. Also Section E of `<<SKILL_DIR>>/commands/atoms/_review_helpers.md`.

6. **Codebase exploration (mandatory)** per `_review_helpers.md` Section D. For an implement adversarial review:
   - Read at least 1 similar pattern in the codebase, compare against the new implementation
   - Grep for `TODO`/`FIXME` introduced in the PR
   - Check `Refs #<issue>` traceability

7. Apply the adversarial lens — REFUTE the PR. Mentally mutate the implementation, find edge cases the author missed, surface hidden coupling.

8. Determine verdict: critical/major → FAIL; only minor or none → PASS.

9. **Post a review comment on the PR** with marker `<!-- sdd:review:implement:adversarial -->`. Use temp file + `--body-file` per `implement_review.md`'s pattern.

   Comment body follows the standard format with stage=implement, role=adversarial. Include the `<!-- sdd:findings:json -->` block per `_review_helpers.md` Section B.

## Return contract

```
>>> RESULT <<<
OK PASS PR: #N
```
or
```
>>> RESULT <<<
OK FAIL PR: #N: <one-line severity summary>
```
or
```
>>> RESULT <<<
FAIL: <one-line reason — only for atom errors>
```

## Hard rules

- Single-subagent atom. Do NOT invoke the Agent tool or Skill tool.
- Do NOT modify code, commit, push, merge, or close the PR.
- You **MAY** use Read/Grep/Glob (Section D budget).
- Do NOT use Edit/Write/NotebookEdit except for the temp PR-comment body file.
- Be independent.
- Reviews go on the **PR**.
