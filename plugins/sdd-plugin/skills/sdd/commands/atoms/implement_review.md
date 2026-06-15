# ATOM: implement_review

**Single-subagent worker. MUST NOT spawn subagents. MUST NOT call the Agent tool.**

Independently reviews the PR Final state (step 3-5) for an implement Issue. Reads PR diff + Issue context, applies role-specific criteria from `atoms/rubrics/implement-<role>.md`, posts a review comment on the PR, returns a one-line verdict.

> **Bash Command Execution**: every shell snippet below is its own simple Bash tool call — no `&&`, `||`, `;`, `|`, `2>/dev/null`, `2>&1`, `>file`, `$(...)`, `VAR=$(...)`, or heredocs. For codebase exploration use the **Grep / Glob / Read** tools — do NOT use Bash `find` against `/`, `~`, `/Users`, or any path outside the repo root. See **Bash Command Execution Rules** in `<<SKILL_DIR>>/SKILL.md`.

## Inputs

- `$1` — Issue number (the SDD pipeline's Issue, not the PR)
- `$2` — review role: `completeness` or `quality`

The orchestrator invokes this atom **twice in parallel** in a single message. The `adversarial` role is handled by `implement_adversarial.md`.

## Work

1. Resolve owner/repo:
   ```bash
   gh repo view --json nameWithOwner -q .nameWithOwner
   ```

2. Find the PR for this Issue:
   ```bash
   gh pr list --search "Refs #$1" --state open --json number --jq '.[0].number'
   ```
   If no PR → return `FAIL: PR for Issue #$1 not found (no open PR with Refs #$1 in body)`.

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

5. Read the role-specific criteria:
   - `$2=completeness` → `<<SKILL_DIR>>/commands/atoms/rubrics/implement-completeness.md`
   - `$2=quality` → `<<SKILL_DIR>>/commands/atoms/rubrics/implement-quality.md`

6. **Codebase exploration** per `<<SKILL_DIR>>/commands/atoms/_review_helpers.md` Section D. Budget: 15 Read / 10 Grep / 5 Glob. Verify file references in design vs actual PR diff; read similar existing implementations to compare patterns.

7. Apply criteria. Standard severity:
   - **critical**: broken functionality, security vulnerability, missing requirement
   - **major**: inconsistency, significant quality issue, poor test coverage
   - **minor**: style, naming, minor improvement

8. Determine verdict: critical/major → FAIL; only minor or none → PASS.

9. **Post a review comment on the PR** (not the Issue) with marker `<!-- sdd:review:implement:<role> -->`. Per the **Bash Command Execution Rules**, write the rendered body to a temp file first, then pass via `--body-file`. Standard duplicate-prevention.

    ```bash
    gh api repos/<owner>/<repo>/issues/<PR_NUM>/comments \
      --jq '.[] | select(.body | contains("<!-- sdd:review:implement:<role> -->")) | .id'
    ```

    Branch on output (orchestrator-side, NOT in shell):
    - Empty → create with `gh pr comment <PR_NUM> --body-file /tmp/sdd-review-implement-<role>.md`
    - Has ID → update with `gh api repos/<owner>/<repo>/issues/comments/<EXISTING_ID> -X PATCH --field body=@/tmp/sdd-review-implement-<role>.md`

    Comment body format:
    ```
    <!-- sdd:review:implement:<role> -->
    ## AI Review (implement / <role>)

    **Verdict:** PASS | FAIL
    **Model:** <opus|sonnet|haiku>

    ### Issues
    - **[critical]** path/to/file.ts:42 — <description>
    - **[major]** <description>
    - **[minor]** <description>

    ### Suggestions
    <if any>

    <!-- sdd:findings:json -->
    ```json
    {<structured findings per _review_helpers.md Section B, stage="implement", role="<role>", pr=<PR_NUM>>}
    ```
    <!-- /sdd:findings:json -->
    <!-- /sdd:review:implement:<role> -->
    ```

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
- Do NOT modify code, commit, push, merge, or close the PR. Only post the review comment.
- You **MAY** use Read/Grep/Glob (Section D budget).
- Do NOT use Edit/Write/NotebookEdit except for writing the temp PR-comment body file.
- Be independent.
- Reviews go on the **PR**, not the Issue.
