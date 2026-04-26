# TEST

**Stage 4: Testing**

Unit/UI tests are already done in Stage 3. This stage focuses on E2E and QA.

## Determine Issue type:

1. **Parent Issue (has children)**: Check all child Issues
   - Read child Issue numbers from the children comment
   - Check each child Issue's label
   - If any child Issue is NOT `sdd:done` → report which children are incomplete, ask user to complete them first
   - If ALL child Issues are `sdd:done` → proceed with parent-level E2E/QA below
2. **Single Issue or Child Issue**: proceed with E2E/QA below

## Phase 1: E2E Test + QA Checklist (via subagent)

Use the **Agent tool** to spawn a subagent with the following instructions. This isolates the heavy work from the main context to save tokens.

> **Subagent instructions:**
>
> You are executing SDD Stage 4 (Test) for Issue $1.
>
> ### 4-0. Test Setup
> 1. Explore the codebase to detect the project's existing test setup:
>    - Test framework (e.g. Jest, Pytest, Go test, Playwright, Cypress, etc.)
>    - Test directory structure (e.g. `tests/`, `__tests__/`, `e2e/`, etc.)
>    - Test run command (e.g. `npm test`, `pytest`, `go test ./...`, etc.)
>    - Test configuration files (e.g. `jest.config.js`, `playwright.config.ts`, etc.)
> 2. If no existing E2E test setup is found:
>    - Recommend a framework based on the project's tech stack and report it (do NOT set up without user confirmation)
>
> ### 4-1. E2E Test
> 1. Read analyze/design outputs from Issue comments
> 2. If parent Issue: read all child Issues' implementation PRs to understand what was built
> 3. If single/child Issue: read implementation PR
> 4. Write E2E test code using the detected framework, following existing test patterns and directory structure
> 5. Start test environment → run E2E tests → check results
> 6. **AI Review**: Read `${CLAUDE_SKILL_DIR}/commands/ai-review.md` and execute with E2E test results (stage: **test**)
>    - If E2E tests fail → fix test code or identify bugs
>    - If bugs found → report them (will need to go back to Stage 3)
>
> ### 4-2. QA Checklist
> 1. Create QA checklist based on requirements
> 2. Identify regression test targets
> 3. **Self-review**: check for missing test scenarios, edge cases, and regression risks
>
> Return: detected test setup, E2E test results, AI review loop results (rounds, issues fixed, verdict), and QA checklist.

## Phase 2: User Review + Manual QA (in main context)

1. If the subagent reported no existing E2E test setup → ask user for framework confirmation, then re-run subagent with the chosen framework
2. If the subagent reported bugs → go back to Stage 3 for TDD bug fix cycle

**User review**: Check skip-review setting (see Common Definitions → Skip Review Setting)
- If `qa` is in skip-review:
  - Log: "User review skipped (skip-review: qa)"
  - Auto-approve E2E test results and QA checklist, skip to **Results Review**
- If `qa` is NOT in skip-review:
  - Present E2E test results and AI review loop results, confirm E2E test code
  - Present QA checklist, user may add/remove/modify items
  - **Manual QA (4-3)**: User performs manual QA testing based on the approved checklist, runs regression tests, and reports results (pass/fail per checklist item)

## Results Review (4-4):
1. If any QA item fails → analyze cause, go back to Stage 3 for TDD bug fix cycle
2. All tests pass → update label to `sdd:done` and close the Issue:
   ```bash
   gh issue edit $1 --remove-label "sdd:test" --add-label "sdd:done"
   gh issue close $1
   ```
