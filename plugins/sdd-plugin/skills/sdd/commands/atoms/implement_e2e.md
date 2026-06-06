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

## Return contract

```
>>> RESULT <<<
OK E2E COMMIT: <sha>
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

- `OK E2E COMMIT: <sha>` — E2E written and committed.
- `OK E2E_SKIPPED` — no E2E setup in the repo; flagged for `/sdd test`.
- `FAIL: <reason>` — could not complete.

## Hard rules

- Single-subagent atom. Do NOT invoke the Agent tool or Skill tool.
- Do NOT install new E2E frameworks.
- Do NOT change unit/widget tests in this step.
- Do NOT set Claude as co-author.
- Do NOT push the branch.
