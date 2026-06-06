# ATOM: test_adversarial

**Single-subagent worker. MUST NOT spawn subagents. MUST NOT call the Agent tool.**

Independently REFUTES the test output. Applies the adversarial lens, posts a review comment, returns a one-line verdict.

> **Bash Command Execution**: every shell snippet below is its own simple Bash tool call — no `&&`, `||`, `;`, `|`, `$(...)`, `VAR=$(...)`, or heredocs. See **Bash Command Execution Rules** in `${CLAUDE_SKILL_DIR}/SKILL.md`.

## Inputs

- `$1` — Issue number

Role is fixed as `adversarial`.

## Work

1. Resolve owner/repo + read context:
   ```bash
   gh repo view --json nameWithOwner -q .nameWithOwner
   gh issue view $1
   gh api repos/<owner>/<repo>/issues/$1/comments \
     --jq '.[] | select(.body | contains("sdd:analyze:output") or contains("sdd:design:output") or contains("sdd:test:output")) | .body'
   ```

2. If test output is missing → return `FAIL: test output not found on Issue #$1`.

3. Detect path (single/child vs parent) by inspecting the test output body (`Path: Single/Child Issue` vs `Path: Parent Issue`).

4. Read the adversarial criteria: `${CLAUDE_SKILL_DIR}/commands/ai-review-test-adversarial.md`. Also Section E of `${CLAUDE_SKILL_DIR}/commands/atoms/_review_helpers.md`.

5. **Codebase exploration** per `_review_helpers.md` Section D:
   - Read the PR's test files referenced in the test output
   - For parent path: read at least 1 child's test file and 1 integration test
   - Budget: 15 Read / 10 Grep / 5 Glob

6. Apply the adversarial lens — REFUTE the test output. Mentally mutate the implementation, look for tests that would pass with no-op or broken impl, find missing classes of coverage.

7. Determine verdict: critical/major → FAIL; only minor or none → PASS.

8. **Post a review comment**. Location:
   - Single/Child path: post on the **PR** with marker `<!-- sdd:review:test:adversarial -->`
   - Parent path: post on the **Issue** with marker `<!-- sdd:review:test:adversarial -->`

   Standard format with `<!-- sdd:findings:json -->` block per `_review_helpers.md` Section B. Use temp file + `--body-file` for PR comments.

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
- Do NOT modify any code, tests, or PR.
- You **MAY** use Read/Grep/Glob (Section D budget).
- Do NOT use Edit/Write/NotebookEdit except for the temp PR-comment body file.
- Be independent.
