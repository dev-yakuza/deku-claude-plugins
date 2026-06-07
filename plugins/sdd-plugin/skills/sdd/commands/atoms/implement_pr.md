# ATOM: implement_pr

**Single-subagent worker. MUST NOT spawn subagents. MUST NOT call the Agent tool.**

Executes TDD step 3-5: push the branch and create the PR. Handles both first-round mode (initial PR) and retry mode (push fix-up commits without creating a new PR).

> **Bash Command Execution**: every shell snippet below is its own simple Bash tool call — no `&&`, `||`, `;`, `|`, `$(...)`, `VAR=$(...)`, or heredocs. See **Bash Command Execution Rules** in `${CLAUDE_SKILL_DIR}/SKILL.md`.

## Inputs

- `$1` — Issue number
- `$2` — feature branch name
- Optional `$3` — retry feedback (JSON array; if provided, operates in **retry mode**)

## Mode detection

Run before any work. Each line is its own Bash call:

```bash
git rev-parse --abbrev-ref HEAD
gh pr list --head $2 --state open --json number --jq '.[0].number'
```

Let the literal output of the second command be `<EXISTING_PR>` (or empty).

- **First-round mode**: `$3` not provided AND `<EXISTING_PR>` is empty → push + create PR.
- **Retry mode**: `$3` provided → push fix-up commits to existing PR (do NOT create a new PR).
- **Mixed (defensive)**: `$3` provided but no PR found → return `FAIL: retry mode requested but no open PR for branch $2`.

## Work — first-round mode

### Step 0: Pre-flight context discovery

(Retry mode skips this — see "Work — retry mode" section.)

Follow `${CLAUDE_SKILL_DIR}/commands/atoms/_preflight.md` Section A for the **Light** tier. Execute Section B items 1 + 2 (project conventions + commit message style).

The commit message style is critical for `implement_pr`: PR title and body should match the conventions discovered here (e.g., `feat: …`, `fix: …`, em-dash separator).

Apply Section D failure handling. Record findings for the Section F self-review trace.

### Main work (numbered steps below)

1. Resolve owner/repo + read context:
   ```bash
   gh repo view --json nameWithOwner -q .nameWithOwner
   gh issue view $1
   gh api repos/<owner>/<repo>/issues/$1/comments \
     --jq '.[] | select(.body | contains("sdd:design:output") or contains("sdd:implement:plan")) | .body'
   ```

2. Detect parent reference for child Issue PR body per Common Definitions → Parent/Child Issue Detection in `${CLAUDE_SKILL_DIR}/SKILL.md` (multi-language regex `(Parent|상위 |親)Issue: #<number>`).

3. **Re-run all tests** (unit + E2E if applicable) → confirm pass. If anything fails, return `FAIL: tests fail before PR creation`.

4. **Push the branch**:
   ```bash
   git push -u origin $2
   ```

5. **Summarize changes** (3-5 lines): what the PR does, scoped to this Issue.

6. **Create the Manual Test Checklist** for this PR:
   - Items a reviewer should manually verify
   - Focus on UI behavior, user flows, edge cases not covered by automated tests
   - Markdown checklist format

7. **Determine language** from `.github/.sdd-lang` (same fallback rules as work atoms).

8. **Write PR body to a temp file** (Write tool, not Bash — per **Bash Command Execution Rules**):

   For Single Issue:
   ```
   Refs #$1

   <change summary>

   ## Manual Test Checklist
   <checklist>
   ```

   For Child Issue (add localized parent line):
   - en: `Parent Issue: #<parent>`
   - ko: `상위 Issue: #<parent>`
   - ja: `親Issue: #<parent>`

   ```
   Refs #$1
   <localized parent line>

   <change summary>

   ## Manual Test Checklist
   <checklist>
   ```

   Write to `/tmp/sdd-pr-body-$1.md`.

9. **Create the PR** (single Bash call — no shell expansion):
   ```bash
   gh pr create --title "<title>" --body-file /tmp/sdd-pr-body-$1.md
   ```

   Title convention:
   - Single Issue: `feat: <feature>` or matching repo convention from `git log --oneline -20`
   - Child Issue: same pattern, derived from child Issue title

10. **Capture the PR number** (its own Bash call):
    ```bash
    gh pr view --json number -q .number
    ```

11. Determine if E2E was skipped (check earlier steps' results or inspect commit history for E2E commit).

## Work — retry mode

1. Verify branch and PR:
   ```bash
   git rev-parse --abbrev-ref HEAD
   gh pr list --head $2 --state open --json number --jq '.[0].number'
   ```
   Confirm `<EXISTING_PR>` matches expected.

2. Ensure the branch is up to date:
   ```bash
   git pull --ff-only origin $2
   ```
   If `git pull` fails (e.g. network), continue — local state is still usable.

3. Read the current PR diff:
   ```bash
   gh pr diff <PR_NUM>
   ```

4. Parse `$3` (JSON array of findings) per `${CLAUDE_SKILL_DIR}/commands/atoms/_review_helpers.md` Section B. Per Section C.1, `$3` now contains all severities sorted `critical → major → minor`.

5. For each `critical` or `major` finding in `$3`:
   - **Decide the fix kind**:
     - Code defect → modify production code
     - Missing test → add a failing test first (mini Red), then implement (mini Green)
     - Test defect → modify the existing test
     - Refactoring nit → adjust the implementation
   - **Apply the fix** and run all tests → confirm pass.
   - **Use the `minor` entries as context**: if a `minor` finding cites the same `file`/`line`/`rule_id` as the critical/major you are fixing, read its `description` and `fix_suggestion` — they often pinpoint the exact line or symbol the higher-severity finding only referenced abstractly. Do not skip `minor` findings; just don't promote them to standalone fixes unless trivial to address while in the same file.

6. **Commit** fix-up changes (**do NOT amend; do NOT force-push**):
   ```bash
   git add <files>
   git commit -m "fix: address review (round N) - <short summary>"
   ```

7. **Push regular** (no `--force`):
   ```bash
   git push -u origin $2
   ```

8. Do NOT create a new PR. The existing PR is auto-updated by the push.

## Return contract

```
>>> RESULT <<<
OK PR: #N
```
or
```
>>> RESULT <<<
OK PR: #N E2E_SKIPPED
```
or
```
>>> RESULT <<<
FAIL: <one-line reason, max 200 chars, no newlines>
```

- `OK PR: #N` — PR created or updated; all tests pass.
- `OK PR: #N E2E_SKIPPED` — same, but E2E setup did not exist.
- `FAIL: <reason>` — could not complete.

## Hard rules

- Single-subagent atom. Do NOT invoke the Agent tool or Skill tool.
- Do NOT do PR Final review (3-5) — that is the orchestrator's responsibility via `implement_review` + `implement_adversarial` atoms.
- Do NOT read the analyze output.
- Do NOT set Claude as co-author in any commit.
- **Never force-push.** Retry mode adds new commits — preserves PR review history.
- **Never amend prior commits** in retry mode.
- Inspect `git log --oneline -20` for the repo's branch and commit message conventions before making commits.
