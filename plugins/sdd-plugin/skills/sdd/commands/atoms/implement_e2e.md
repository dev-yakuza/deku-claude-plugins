# ATOM: implement_e2e

**Single-subagent worker. MUST NOT spawn subagents. MUST NOT call the Agent tool.**

Executes TDD step 3-4: write E2E tests for the implemented feature, if the repo has an E2E setup.

> **Bash Command Execution**: every shell snippet below is its own simple Bash tool call — no `&&`, `||`, `;`, `|`, `$(...)`, `VAR=$(...)`, or heredocs. See **Bash Command Execution Rules** in `${CLAUDE_SKILL_DIR}/SKILL.md`.

## Inputs

- `$1` — Issue number
- `$2` — feature branch name
- Optional `$3` — retry feedback (JSON array)

## Preconditions

- The branch has Red + Green + (optional) Refactor commits.
- All unit/widget tests are passing.

## Work

### Step 0: Pre-flight context discovery

If `$3` (retry) → skip. Else: follow `${CLAUDE_SKILL_DIR}/commands/atoms/_preflight.md` — tier **Code-focused**, Section B item 4 only (target directory survey).

For E2E specifically: focus the directory read on existing E2E test files — the framework used (Playwright/Cypress/Puppeteer/Flutter integration_test/etc.), test fixture patterns, page-object usage, waiting strategy.

### Main work (numbered steps below)

1. Verify branch:
   ```bash
   git rev-parse --abbrev-ref HEAD
   ```
   If not on `$2`, `git checkout $2`.

2. **Detect existing E2E/integration test setup**:
   - Look for E2E framework artifacts: `playwright.config.*`, `cypress.config.*`, `e2e/` directory, `integration_test/` (Flutter), `tests/e2e/`, etc.
   - Look for `package.json` scripts like `test:e2e`, `e2e`, `cy:run`, etc.
   - Use Read/Grep/Glob as needed.

3. **Branch on detection**:

   ### 3a. If E2E setup exists
   - Read the existing E2E patterns (read 1-2 existing E2E test files).
   - Write E2E tests for the implemented feature, following existing patterns and naming.
   - Match the existing E2E test framework's conventions (page objects, fixtures, etc.).
   - Run the E2E tests → **confirm pass**.
   - Capture from the E2E runner output:
     - `<passed>` — number of passing E2E tests
     - `<failed>` — number of failing E2E tests (MUST be 0)
     - `<total>` — total E2E tests executed
     These numbers are reported in the return contract and used by `tdd_step_review` to verify the E2E claim.
   - **Also remember the full E2E runner output text** — it is posted in step 7 as evidence the reviewer can cross-check against the reported counts.

   ### 3b. If no E2E setup exists
   - Skip E2E entirely. Note this for the result return.
   - Do NOT install new E2E frameworks — that's a `/sdd test` stage decision with user confirmation.

4. If `$3` (retry feedback) is provided (and E2E was run): address each finding.

5. **Self-review (blockers only — E2E path only)**:
   - [ ] E2E tests follow existing framework patterns
   - [ ] E2E tests pass
   - [ ] No sleep-based waits (`waitFor(500)`) — use condition-based waits
   - [ ] No skip/disable markers

6. **Commit** if E2E was written:
   ```bash
   git add <e2e-files>
   git commit -m "test: e2e for <feature>"
   ```

   If E2E was skipped, no commit. No Claude co-author.

7. **Post test evidence comment** per `${CLAUDE_SKILL_DIR}/commands/atoms/_test_evidence.md`. Inputs: `<n>=4`, `<sha>` from `git rev-parse HEAD`, the captured `<passed>/<total>/<failed>`, and the full E2E runner output from step 3a. Skip this step entirely when returning `OK E2E_SKIPPED` (no commit, no test claim to verify). If the procedure returns the failure described in its Step 5, return that `FAIL:` from this atom.

## Return contract

```
>>> RESULT <<<
OK E2E COMMIT: <sha> TESTS: <passed>/<total> FAILED: 0
```
or
```
>>> RESULT <<<
OK E2E_SKIPPED
```
or
```
>>> RESULT <<<
FAIL: <one-line reason>
```

- `OK E2E COMMIT: <sha> TESTS: <p>/<t> FAILED: 0` — E2E written and committed; E2E suite passing. `FAILED` MUST be `0`. The orchestrator forwards this evidence to `tdd_step_review`.
- `OK E2E_SKIPPED` — no E2E setup in the repo; flagged for `/sdd test`. No test evidence required.
- `FAIL: <reason>` — could not complete.

## Hard rules

- Single-subagent atom. Do NOT invoke the Agent tool or Skill tool.
- Do NOT install new E2E frameworks.
- Do NOT change unit/widget tests in this step.
- Do NOT set Claude as co-author.
- Do NOT push the branch.
