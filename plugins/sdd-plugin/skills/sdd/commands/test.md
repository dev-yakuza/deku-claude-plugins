# TEST

**Stage 4: Testing**

Unit/UI tests and E2E tests are already done in Stage 3 (for single/child Issues). This stage focuses on QA verification, and integration E2E for parent Issues.

## Input Validation
Before any other step: validate `$1` per Common Definitions → Issue Validation in `${CLAUDE_SKILL_DIR}/SKILL.md`. If `$1` is a Pull Request, stop without making changes.

## Determine Issue type:

1. **Parent Issue (has children)**: Check all child Issues
   - Read child Issue numbers from the children comment
   - Check each child Issue's label
   - If any child Issue is NOT `sdd:done` → report which children are incomplete, ask user to complete them first
   - If ALL child Issues are `sdd:done` → proceed with **Parent Issue Flow** below
2. **Single Issue or Child Issue**: proceed with **Single/Child Issue Flow** below

---

## Single/Child Issue Flow

E2E tests were already written in Stage 3 (implement) and included in the PR. This flow focuses on QA verification only.

### Phase 1: QA Checklist (via subagent)

Use the **Agent tool** to spawn a subagent with the following instructions. This isolates the heavy work from the main context to save tokens.

> **Subagent instructions:**
>
> You are executing SDD Stage 4 (Test) for Issue $1. This is a single/child Issue — E2E tests are already in the PR.
>
> **Context to read** (only these — do NOT read analyze/design outputs):
> - Implementation PR for this Issue (find via `gh pr list --search "Refs #$1"`)
> - Definition of Done from the Issue body
>
> ### 4-1. Verify Existing Tests
> 1. Read the implementation PR to understand what was built and what tests exist
> 3. Run existing tests (unit, widget, E2E) → confirm all pass
> 4. Evaluate test coverage: check if E2E tests adequately cover the requirements
>    - If E2E tests were skipped in Stage 3 (no E2E setup): report it
>    - If E2E tests exist but have gaps: report specific missing scenarios
>
> ### 4-2. QA Checklist
> 1. Create QA checklist based on requirements (separate automated vs manual items)
> 2. Identify regression test targets
> 3. **Self-review**: check for missing test scenarios, edge cases, and regression risks
>
> Return: test run results, coverage evaluation, and QA checklist.

### Phase 2: User Review + Manual QA (in main context)

1. If the subagent reported E2E tests were skipped in Stage 3 → ask user for framework confirmation, write E2E tests, and push to the PR branch
2. If the subagent reported E2E coverage gaps → ask user whether to add more tests or proceed

**User review**: Check skip-review setting (see Common Definitions → Skip Review Setting)
- If `qa` is in skip-review:
  - Log: "User review skipped (skip-review: qa)"
  - Auto-approve test results and QA checklist, skip to **Results Review**
- If `qa` is NOT in skip-review:
  - Present test results and coverage evaluation
  - Present QA checklist, user may add/remove/modify items
  - **Manual QA (4-3)**: User performs manual QA testing based on the approved checklist, runs regression tests, and reports results (pass/fail per checklist item)

### Results Review (4-4):
1. If any QA item fails → analyze cause, go back to Stage 3 for TDD bug fix cycle
2. All tests pass → update label to `sdd:done` and close the Issue:
   ```bash
   gh issue edit $1 --remove-label "sdd:test" --add-label "sdd:done"
   gh issue close $1
   ```

---

## Parent Issue Flow

Child Issues have individual tests, but cross-child integration E2E tests may be needed at the parent level.

### Phase 1: Integration E2E Test + QA Checklist (via subagent)

Use the **Agent tool** to spawn a subagent with the following instructions.

> **Subagent instructions:**
>
> You are executing SDD Stage 4 (Test) for Parent Issue $1.
>
> **Context to read** (only these — minimize token usage):
> - Design output from Issue comments (the `<!-- sdd:design:output -->` comment) — for understanding the overall architecture
> - Child Issues' implementation PRs (find via children comment)
> - Definition of Done from the Issue body
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
> ### 4-1. Integration E2E Test
> 1. Read the context specified above
> 2. Read all child Issues' implementation PRs to understand what was built
> 3. Identify integration points between child Issues that need cross-child testing
> 4. If integration tests are needed:
>    - Create a test branch: `test/<parent-feature-name>`
>    - Write integration E2E test code using the detected framework, following existing patterns
>    - Run E2E tests → check results
>    - Create a PR for the integration tests:
>      `gh pr create --title "test: <parent feature> integration tests" --body "Refs #$1\n\n..."`
> 5. If no integration tests are needed (child tests already cover all scenarios): report the reasoning
> 6. **AI Review**: Read `${CLAUDE_SKILL_DIR}/commands/ai-review.md` and execute with E2E test results (stage: **test**)
>    - If E2E tests fail → fix test code or identify bugs
>    - If bugs found → report them (will need to go back to Stage 3)
>
> ### 4-2. QA Checklist
> 1. Create QA checklist based on parent-level requirements (cross-child integration scenarios)
> 2. Identify regression test targets
> 3. **Self-review**: check for missing test scenarios, edge cases, and regression risks
>
> Return: detected test setup, integration E2E test results (or skip reasoning), PR URL (if created), AI review loop results (rounds, issues fixed, verdict), and QA checklist.

### Phase 2: User Review + Manual QA (in main context)

1. If the subagent reported no existing E2E test setup → ask user for framework confirmation, then re-run subagent with the chosen framework
2. If the subagent reported bugs → go back to Stage 3 for TDD bug fix cycle
3. If the subagent created an integration test PR → present it for review

**User review**: Check skip-review setting (see Common Definitions → Skip Review Setting)
- If `qa` is in skip-review:
  - Log: "User review skipped (skip-review: qa)"
  - Auto-approve E2E test results and QA checklist, skip to **Results Review**
- If `qa` is NOT in skip-review:
  - Present integration E2E test results and AI review loop results, confirm E2E test code
  - Present QA checklist, user may add/remove/modify items
  - **Manual QA (4-3)**: User performs manual QA testing based on the approved checklist, runs regression tests, and reports results (pass/fail per checklist item)

### Results Review (4-4):
1. If any QA item fails → analyze cause, go back to Stage 3 for TDD bug fix cycle
2. All tests pass → update label to `sdd:done` and close the Issue:
   ```bash
   gh issue edit $1 --remove-label "sdd:test" --add-label "sdd:done"
   gh issue close $1
   ```
