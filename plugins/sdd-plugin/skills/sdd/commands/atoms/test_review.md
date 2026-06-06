# ATOM: test_review

**Single-subagent worker. MUST NOT spawn subagents. MUST NOT call the Agent tool.**

Independently reviews the test output. Reads analyze + design + test comments, applies role-specific criteria, posts a review comment, returns a one-line verdict.

> **Bash Command Execution**: every shell snippet below is its own simple Bash tool call — no `&&`, `||`, `;`, `|`, `$(...)`, `VAR=$(...)`, or heredocs. See **Bash Command Execution Rules** in `${CLAUDE_SKILL_DIR}/SKILL.md`.

## Inputs

- `$1` — Issue number
- `$2` — review role: `completeness` or `quality`

The orchestrator invokes this atom **twice in parallel** in a single message. The `adversarial` role is handled by `test_adversarial.md`. The cross-stage parent integration role is handled by `parent_integration_review.md` (parent path only).

## Work

1. Resolve owner/repo and read the Issue + relevant stage outputs:
   ```bash
   gh repo view --json nameWithOwner -q .nameWithOwner
   gh issue view $1
   gh api repos/<owner>/<repo>/issues/$1/comments \
     --jq '.[] | select(.body | contains("sdd:analyze:output") or contains("sdd:design:output") or contains("sdd:test:output")) | .body'
   ```

2. If test output missing → return `FAIL: test output not found on Issue #$1`.

3. Detect path (single/child vs parent) from the test output body (`Path:` line) and from the presence of `<!-- sdd:children:output -->`.
   - **Parent path**: also read children's PRs (find via children comment numbers).
   - **Single/Child path**: also read the implementation PR diff (find via `gh pr list --search "Refs #$1"`).

4. Read the role-specific criteria:
   - `$2=completeness` → `${CLAUDE_SKILL_DIR}/commands/ai-review-test-completeness.md`
   - `$2=quality` → `${CLAUDE_SKILL_DIR}/commands/ai-review-test-quality.md`

5. **Codebase exploration** per `${CLAUDE_SKILL_DIR}/commands/atoms/_review_helpers.md` Section D. Budget: 15 Read / 10 Grep / 5 Glob. Read PR test files and verify the test output's claims match actual test code.

6. Apply criteria. Standard severity definitions.

7. Determine verdict: critical/major → FAIL; only minor or none → PASS.

8. **Post a review comment**. Location:
   - Single/Child path: post on the **PR** (`gh pr comment <PR_NUM>`) with marker `<!-- sdd:review:test:<role> -->`
   - Parent path: post on the **Issue** with marker `<!-- sdd:review:test:<role> -->`

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
- Do NOT modify the test output comment or PR files.
- You **MAY** use Read/Grep/Glob (Section D budget).
- Do NOT use Edit/Write/NotebookEdit except for the temp PR-comment body file.
- Be independent.
