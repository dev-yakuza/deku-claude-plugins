# ATOM: tdd_step_review

**Single-subagent worker. MUST NOT spawn subagents. MUST NOT call the Agent tool.**

Lightweight diff-only review between TDD steps (3-1 Red, 3-2 Green, 3-3 Refactor, 3-4 E2E). Reads the last step's git commit diff, applies step-specific criteria, posts a review comment to the Issue, returns a one-line verdict.

> **Bash Command Execution**: every shell snippet below is its own simple Bash tool call — no `&&`, `||`, `;`, `|`, `$(...)`, `VAR=$(...)`, or heredocs. See **Bash Command Execution Rules** in `${CLAUDE_SKILL_DIR}/SKILL.md`.

## Inputs

- `$1` — Issue number
- `$2` — step number: `1`, `2`, `3`, or `4` (matches TDD step 3-1, 3-2, 3-3, 3-4)
- `$3` — branch name
- `$4` — commit sha to review (from the step atom's return); if `EMPTY` (no commit, e.g. refactor empty), skip the review
- `$5` — test evidence string from the work atom's return contract, in the form `TESTS: <p>/<t> FAILED: <f>`; if `NONE` (no test claim was made — e.g. refactor EMPTY or E2E_SKIPPED), skip the test-evidence check

## Work

1. **Handle empty commit case**:
   - If `$4` == `EMPTY` → return `OK PASS` immediately (nothing to review, nothing to post).

2. Resolve owner/repo + read the commit diff:
   ```bash
   gh repo view --json nameWithOwner -q .nameWithOwner
   git show --stat $4
   git show $4
   ```

2a. **Read the test-evidence comment** posted by the work atom per `${CLAUDE_SKILL_DIR}/commands/atoms/_test_evidence.md`:

   ```bash
   gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | select(.body | contains("<!-- sdd:test-evidence:step-$2 -->")) | .body'
   ```

   (Inline the literal `<owner>/<repo>` and `$2` value.)

   - If the search returns empty AND `$4 != EMPTY` AND `$5 != NONE` → finding `[major] rule_id: test-evidence-log-missing` ("work atom did not post raw test runner output; reported counts are unverifiable"). Continue to step 3 — do not return early; other checks still apply.
   - If the search returns a body → remember it as `<evidence-log>` for step 5a.

3. Read the criteria: `${CLAUDE_SKILL_DIR}/commands/ai-review-implement-step.md`. Use the section matching `$2`:
   - `$2=1` → "Step 3-1: Red"
   - `$2=2` → "Step 3-2: Green"
   - `$2=3` → "Step 3-3: Refactor"
   - `$2=4` → "Step 3-4: E2E"

4. **Codebase exploration (lighter budget)** per `${CLAUDE_SKILL_DIR}/commands/atoms/_review_helpers.md` Section D: max **5 Read / 3 Grep / 0 Glob**. Use sparingly — this is a quick step review, not a full audit.

5. Apply the step-specific criteria to the diff. Severity definitions:
   - **critical**: This step is broken in a way that compounds into the next step
   - **major**: Significant issue in this step that should be fixed before proceeding
   - **minor**: Improvement suggestion (does not block)

5a. **Test-evidence consistency check** (uses `$5` and the `<evidence-log>` from step 2a). You cannot re-run tests in this atom — instead, verify the work atom's reported numbers are present, consistent with the step, and corroborated by the raw runner output:

   - If `$5 == "NONE"` and `$4 == "EMPTY"` → skip this check (refactor produced no diff, nothing to verify).
   - If `$5` is missing, empty, or not parseable as `TESTS: <int>/<int> FAILED: <int>` → finding `[major] rule_id: test-evidence-missing` ("work atom did not report test counts; cannot verify the step's test claim from the diff alone").
   - For `$2 == 1` (Red): if `FAILED` is `0` → finding `[critical] rule_id: red-tests-did-not-fail` ("Red step's claim contradicts evidence: zero tests failed").
   - For `$2 ∈ {2, 3, 4}` (Green / Refactor / E2E): if `FAILED` is non-zero → finding `[critical] rule_id: tests-not-green` ("step claims pass but evidence shows N failures").
   - For `$2 == 3` (Refactor only): if the diff in `$4` does NOT touch any file under a test directory (no `*test*` / `*spec*` paths), but `TESTS: <p>/<t>` differs from the immediately preceding Green commit's reported counts → finding `[critical] rule_id: refactor-changed-test-counts` ("test count drift on a refactor that did not edit tests — behavior may have changed silently"). To check the prior Green counts, search Issue comments for the latest `<!-- sdd:review:implement:step-2 -->` block and parse the `Tests` field from its body. If unavailable, downgrade to `[major]`.
   - Sanity bound: if `<total>` is `0` and `$4 != "EMPTY"` → finding `[major] rule_id: zero-tests-executed` ("work atom reported zero tests executed despite committing changes").

   **Raw-log cross-check** (applies only if `<evidence-log>` was found in step 2a; otherwise the `test-evidence-log-missing` finding from 2a already covers this gap):

   - Inspect the fenced code block inside the test-evidence comment. Look for the runner's own summary line — formats vary by framework, common patterns include `Tests: <p> passed, <f> failed`, `<f> failed, <p> passed` (jest), `passed=<p> failed=<f>` (pytest summary), `<total> tests ... <failed> failures` (junit-style), `PASS`/`FAIL` lines per test file (vitest, mocha), `ok <n> - <name>` / `not ok <n>` (TAP), etc. Do not require a specific format — read the log and judge.
   - **Count mismatch**: if you can identify a summary line and its numbers disagree with `$5` (e.g. `$5` says `42/42 FAILED: 0` but the log summary line shows `12 passed, 0 failed`) → finding `[critical] rule_id: test-evidence-mismatch` ("self-reported counts contradict raw log: reported <$5>, log shows <observed>"). Include the observed log line in the finding description.
   - **Failure-line presence check (Red only)**: for `$2 == 1`, the log MUST contain at least one indicator that a test actually failed — an assertion error message, a `FAIL` marker, a stack trace, a `not ok` line, or equivalent. If none is present → finding `[critical] rule_id: red-log-shows-no-failure` ("Red step's evidence log contains no failure indicator").
   - **Authenticity check**: if the evidence log is suspiciously short (under 200 characters), lacks any file path or test name, or lacks any framework-specific marker (test runner banner, timing line, framework name) → finding `[major] rule_id: test-evidence-implausible` ("evidence log lacks structural markers expected from a real test runner; counts cannot be corroborated"). Apply judgment: tiny test suites may legitimately produce short output, but they should still show at least one identifiable runner artifact.
   - If you cannot identify a summary line in the log at all (despite the log being present and plausibly authentic) → finding `[minor] rule_id: test-evidence-summary-unparseable` ("could not locate a summary line in the runner output; counts assumed accurate"). Do not block on this — runners differ widely.

   Record any findings from this check in the same Issues array used by the step-specific criteria.

6. Determine verdict:
   - critical/major → **FAIL** (the orchestrator will re-spawn this step's atom)
   - only minor or none → **PASS** (proceed to next step)

7. **Post a review comment** to the **Issue** (not the PR — PR may not exist yet) with marker `<!-- sdd:review:implement:step-$2 -->`. Standard duplicate-prevention.

   Comment body format:
   ```
   <!-- sdd:review:implement:step-$2 -->
   ## AI Review (implement / step-$2)

   **Verdict:** PASS | FAIL
   **Model:** <opus|sonnet|haiku>
   **Commit:** <$4>
   **Tests:** <inline $5 verbatim, or "NONE">

   ### Issues
   - **[critical]** path/to/file.ts:42 — <description>
   - **[major]** <description>
   - **[minor]** <description>

   ### Suggestions
   <if any>

   <!-- sdd:findings:json -->
   ```json
   {<structured findings per _review_helpers.md Section B, stage="implement", role="step-$2">}
   ```
   <!-- /sdd:findings:json -->
   <!-- /sdd:review:implement:step-$2 -->
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
- Do NOT modify any commit, file, or PR. Read-only except for the review comment.
- You **MAY** use Read/Grep (Section D lighter budget: 5 Read / 3 Grep / 0 Glob).
- Do NOT use Edit/Write/NotebookEdit.
- Be independent.
