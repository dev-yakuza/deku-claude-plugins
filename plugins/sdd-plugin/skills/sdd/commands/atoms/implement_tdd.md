# ATOM: implement_tdd

**Single-subagent worker. MUST NOT spawn subagents. MUST NOT call the Agent tool.**

Executes the full TDD cycle for one Issue: Red → Green → Refactor → E2E → PR creation. Each TDD step has an inline `self_only` self-review (review points 3-1 through 3-4 in `ai-review-implement.md`). Returns a one-line result with the PR number.

This is the **largest atom**. If its subagent context becomes saturated for complex Issues, the orchestrator may need to split into separate `implement_red_green`, `implement_refactor`, `implement_e2e`, `implement_pr` atoms — but for typical Issues a single atom is intended.

## Inputs

- `$1` — Issue number
- `$2` — feature branch name (from `implement_plan` atom's `OK BRANCH: <name>` return)
- Optional `$3` — review feedback from a prior round (retry mode). When provided, this atom operates in **retry mode** (see "Retry mode" section below).

## Preconditions

- The Issue must have `<!-- sdd:design:output -->` and `<!-- sdd:implement:plan -->` comments.
- The feature branch (`$2`) must exist and be checked out (the plan atom does this).
- In retry mode (`$3` provided): the branch is expected to have commits and an open PR. The atom verifies and proceeds to fix-up rather than initial TDD.

## Mode detection

Run this **before** Setup to determine which flow to execute:

```bash
git rev-parse --abbrev-ref HEAD                                 # current branch
EXISTING_PR=$(gh pr list --head $2 --state open --json number --jq '.[0].number' 2>/dev/null)
```

- **First-round mode**: `$3` not provided AND `$EXISTING_PR` is empty → execute the full TDD cycle (Setup → 3-1 → 3-2 → 3-3 → 3-4 → 3-5 PR creation).
- **Retry mode**: `$3` provided (review feedback from a prior round). `$EXISTING_PR` should be present; if not, that is an error.
- **Mixed (defensive)**: `$3` provided but no PR found → return `FAIL: retry mode requested but no open PR found for branch $2`. The orchestrator should not have invoked retry without a prior round having created a PR.

## Work — first-round mode

### Setup

1. Resolve owner/repo, verify branch:
   ```bash
   OWNER_REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
   git rev-parse --abbrev-ref HEAD   # confirm we are on $2
   ```
   If not on `$2`, checkout it.

2. Read context (only these — do NOT read analyze):
   ```bash
   gh issue view $1
   gh api repos/$OWNER_REPO/issues/$1/comments \
     --jq '.[] | select(.body | contains("sdd:design:output") or contains("sdd:implement:plan")) | .body'
   ```

3. Detect parent reference for child Issue (needed for PR body) per Common Definitions → Parent/Child Issue Detection in `${CLAUDE_SKILL_DIR}/SKILL.md` (multi-language regex `(Parent|상위 |親)Issue: #<number>`).

### 3-1. Red — Write Failing Tests

1. Write test code per the implementation plan.
2. Run the test command (auto-detect from repo: `npm test`, `flutter test`, `pytest`, `cargo test`, `go test`, etc.) → **confirm tests fail** (Red).
3. **Self-review** against `ai-review-implement.md` "Red - Test Code (3-1)" section:
   - Tests cover main scenarios from the plan
   - Tests cover edge cases from the design
   - Assertions are specific and meaningful
   - Tests actually fail
   - Additional: test quality, readability, missing scenarios
4. If issues → fix inline; re-run tests; repeat until Red state is correct.

### 3-2. Green — Minimal Implementation

1. Implement the minimal code to make tests pass.
2. Run tests → **confirm pass** (Green).
3. **Self-review** against "Green - Implementation (3-2)":
   - Implementation is minimal — only enough to pass tests
   - Code follows existing codebase patterns
   - All tests pass
   - Additional: correctness, readability, side effects
4. If issues → fix inline; re-run; repeat until clean.

### 3-3. Refactor

1. Remove duplication, improve readability, clean up structure.
2. Run tests → **confirm still passing** (Green).
3. **Self-review** against "Refactor (3-3)":
   - Duplication removed, readability improved
   - No unnecessary code, comments, or debug artifacts
   - All tests still pass
   - Additional: code structure, naming, maintainability
4. If issues → fix; re-run; repeat.

### 3-4. E2E Test

1. **Detect existing E2E/integration test setup**: framework, directory structure, config files, run command.
2. **If E2E setup exists**: write E2E tests for the implemented feature following existing patterns; run them; confirm pass.
3. **If no E2E setup exists**: skip E2E and note this (will be addressed in `/sdd test` stage with user confirmation).
4. **Self-review** against "E2E Test (3-4)" (when E2E was run):
   - E2E covers key user flows
   - E2E follows existing framework patterns
   - E2E passes
   - Additional: reliability, flakiness risk, missing flows
5. If issues → fix; re-run; repeat.

### Commit and push

Make commits along the way (test commits, implementation commits, refactor commits) following the repo's commit-message convention as observed in `git log --oneline -20`. Do NOT include Claude as co-author.

Push the branch:
```bash
git push -u origin <branch>
```

### 3-5. PR Creation

1. **Sanity check — PR must not already exist for this branch in first-round mode**:
   ```bash
   gh pr list --head $2 --json number,url --jq '.[0]'
   ```
   - If a PR exists in first-round mode → return `FAIL: PR for branch $2 already exists in first-round mode; orchestrator should have invoked retry mode`.
   - If no PR → continue to step 2.

2. Summarize changes (3-5 lines).

3. Create the **Manual Test Checklist** for this PR:
   - Items a reviewer should manually verify
   - Focus on UI behavior, user flows, edge cases not covered by automated tests
   - Markdown checklist format

4. Create the PR (only if not exists):
   - **Single Issue** title: derive from Issue title, e.g., `feat: <feature>`
     ```bash
     gh pr create --title "<title>" \
       --body "Refs #$1

     <change summary>

     ## Manual Test Checklist
     <checklist>"
     ```
   - **Child Issue** body adds a localized parent line. Use the language from `.github/.sdd-lang` (same fallback rules as work atoms) to choose the keyword:
     - `en` → `Parent Issue: #<parent>`
     - `ko` → `상위 Issue: #<parent>`
     - `ja` → `親Issue: #<parent>`

     PR body:
     ```
     Refs #$1
     <localized parent line per above>

     <change summary>

     ## Manual Test Checklist
     <checklist>
     ```

5. Re-run **all tests** (unit + E2E if applicable) → confirm pass.

6. Do NOT do PR Final review (3-5) in this atom. That review is `full` and runs as parallel `implement_review` atoms spawned by the orchestrator.

7. Capture the PR number (`gh pr view --json number -q .number` against the branch, or from the create command's output).

## Work — retry mode

Triggered when `$3` (review feedback) is provided. The branch and PR already exist.

### Setup (retry)

1. Resolve owner/repo, verify branch and PR:
   ```bash
   OWNER_REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
   PR_NUM=$(gh pr list --head $2 --state open --json number --jq '.[0].number')
   ```
   If `PR_NUM` is empty → return `FAIL: retry mode requested but no open PR found for branch $2`.

2. Ensure `$2` is the current branch:
   ```bash
   git checkout $2 && git pull --ff-only origin $2 || true
   ```

3. Read the same context as first-round (design + plan from Issue), plus the current PR diff:
   ```bash
   gh pr diff $PR_NUM
   ```

4. Parse `$3` review feedback. It contains the combined critical/major issues from the previous round's `implement_review` atoms. Each item should be addressed.

### Fix-up steps (retry)

For each critical/major issue in `$3`:

1. **Decide the fix kind**:
   - Code defect → modify production code
   - Missing test → add a failing test first (mini Red), then implement (mini Green)
   - Test defect → modify the existing test
   - Refactoring nit → adjust the implementation

2. **Apply the fix** and run the full test suite (unit + E2E if applicable) → confirm all tests pass. If a fix causes regressions, address them before continuing.

3. **Self-review the fix** against the relevant `ai-review-implement.md` section for the kind of change (3-1 for tests, 3-2/3-3 for implementation, 3-4 for E2E). Fix self-review issues inline.

### Commit and push (retry)

Make **new commits** (do NOT amend, do NOT force-push) following the repo's commit-message convention. Suggested message form: `fix: address review (round N) - <short summary>`.

```bash
git add <files>
git commit -m "..."
git push -u origin $2   # regular push, no --force; -u is defensive in case upstream is missing
```

The PR is automatically updated by the push — review comments on prior commits remain attached for audit.

### No new PR (retry)

Do NOT create a new PR. The orchestrator will re-spawn `implement_review` atoms after this atom returns; they will re-diff the updated PR and post fresh review comments using duplicate-prevention markers (so prior review comments are updated in place).

## Return contract

Return EXACTLY ONE LINE on its own, prefixed by `>>> RESULT <<<`:

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

- `OK PR: #N` — TDD cycle completed (first round) or fix-up applied (retry round); PR is up to date and all tests pass.
- `OK PR: #N E2E_SKIPPED` — same, but E2E setup did not exist; flagged for `/sdd test` stage.
- `FAIL: <reason>` — could not complete (tests don't pass, push failed, gh pr create failed, retry-mode preconditions unmet, etc.).

Do NOT return code diffs or test output. The PR is the artifact.

## Hard rules

- You are a single-subagent atom. Do NOT invoke the Agent tool. Do NOT spawn subagents.
- Do NOT invoke `/sdd <command>` or the Skill tool.
- Do NOT do PR Final review (3-5) — that is the orchestrator's responsibility via `implement_review` atoms.
- Do NOT read the analyze output.
- Do NOT set Claude as co-author in any commit (rule from `implement.md`).
- Check `git log --oneline -20` for the repo's branch and commit message conventions before making commits.
- Follow existing codebase patterns observed during the TDD cycle.
- **Never force-push.** Retry mode adds new commits (regular `git push`) — this preserves the PR review history so reviewers can see what was changed between rounds.
- **Never amend prior commits** in retry mode.
