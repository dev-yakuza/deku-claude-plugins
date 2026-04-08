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

## 4-0. Test Setup:
1. Explore the codebase to detect the project's existing test setup:
   - Test framework (e.g. Jest, Pytest, Go test, Playwright, Cypress, etc.)
   - Test directory structure (e.g. `tests/`, `__tests__/`, `e2e/`, etc.)
   - Test run command (e.g. `npm test`, `pytest`, `go test ./...`, etc.)
   - Test configuration files (e.g. `jest.config.js`, `playwright.config.ts`, etc.)
2. If no existing E2E test setup is found:
   - Recommend a framework based on the project's tech stack
   - Ask user for confirmation before setting up
3. Report detected test setup to user

## 4-1. E2E Test (AI writes and runs):
1. Read analyze/design outputs from Issue comments
2. If parent Issue: read all child Issues' implementation PRs to understand what was built
3. If single/child Issue: read implementation PR
4. Write E2E test code using the detected framework, following existing test patterns and directory structure
5. Start test environment → run E2E tests → check results
6. **Self-review**: analyze test logs, verify coverage, estimate bug causes
   - If E2E tests fail → fix test code or identify bugs
   - If bugs found → go back to Stage 3 for TDD bug fix cycle
7. **AI Review**: Read `${CLAUDE_SKILL_DIR}/commands/ai-review.md` and execute with E2E test results (stage: **test**)
8. **User review**: present self-review and AI review results, confirm E2E test code and results

## 4-2. QA Checklist (AI creates, AI + User review):
1. Create QA checklist based on requirements
2. Identify regression test targets
3. **Self-review**: check for missing test scenarios, edge cases, and regression risks
4. **User review**: confirm QA checklist is complete and correct
   - User may add/remove/modify checklist items

## 4-3. Manual QA (User executes):
1. User performs manual QA testing based on the approved checklist
2. User runs regression tests
3. User reports results (pass/fail per checklist item)

## 4-4. Results Review:
1. If any QA item fails → analyze cause, go back to Stage 3 for TDD bug fix cycle
2. All tests pass → update label to `sdd:done`
