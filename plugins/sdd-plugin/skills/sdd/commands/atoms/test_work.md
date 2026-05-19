# ATOM: test_work

**Single-subagent worker. MUST NOT spawn subagents. MUST NOT call the Agent tool.**

Produces the SDD Stage 4 (Test) output for one Issue: verifies existing tests pass, evaluates coverage, and creates a QA checklist. Handles two paths — Single/Child Issue (validate existing tests + QA checklist) and Parent Issue (integration E2E testing across children). Posts the result as an Issue comment.

## Inputs

- `$1` — Issue number (already validated by the orchestrator)

## Mode detection

Run before any work:

```bash
OWNER_REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
HAS_CHILDREN=$(gh api repos/$OWNER_REPO/issues/$1/comments \
  --jq '.[] | select(.body | contains("<!-- sdd:children:output -->")) | .body' | head -1)
```

- If `HAS_CHILDREN` is non-empty → **Parent Issue path**.
- Otherwise → **Single/Child Issue path**.

For Parent Issue path, also verify all children are `sdd:done` before running (read child numbers from the children comment, check each child's labels). If any child is not done → return `FAIL: parent has incomplete children: #X, #Y, ...`.

## Work — Single/Child Issue path

E2E tests were already written in Stage 3 (implement) and included in the PR. This path validates them and produces a QA checklist.

1. Find the implementation PR:
   ```bash
   PR_NUM=$(gh pr list --search "Refs #$1" --state open --json number --jq '.[0].number')
   ```
   If empty → `FAIL: no open PR found for Issue #$1`.

2. Read the PR + Issue body (for DoD). Do NOT read analyze/design outputs.
   ```bash
   gh pr view $PR_NUM
   gh pr diff $PR_NUM
   gh issue view $1
   ```

3. **4-1. Verify existing tests**:
   - Check out the PR's branch locally (`gh pr checkout $PR_NUM`).
   - Detect the test command from the repo (`package.json` scripts, `Makefile`, `flutter test`, `pytest`, etc.). Use `git log -20` / repo file inspection.
   - Run all tests (unit, widget, E2E) → record pass/fail per test.
   - If tests fail → return `FAIL: tests fail on PR #<PR_NUM>: <short summary>`.

4. **Evaluate test coverage**:
   - Compare existing tests against the Issue's DoD and the PR's manual test checklist.
   - Note gaps: missing scenarios, missing edge cases, regression risks.
   - If Stage 3 reported E2E was skipped (no E2E setup at the time), flag it.

5. **4-2. Create QA checklist**:
   - Build a markdown checklist from the Issue's DoD and the PR's manual test checklist.
   - Separate automated (already covered by tests) from manual (needs human verification).
   - Identify regression test targets.

6. **Self-review** the test report and QA checklist against `${CLAUDE_SKILL_DIR}/commands/ai-review-test.md` "Additional Review" criteria. Fix gaps inline.

7. Determine language from `.github/.sdd-lang` (same fallback rules).

8. **Post to Issue** with the marker `<!-- sdd:test:output -->`. Duplicate-prevention.

   Comment body format:
   ```
   <!-- sdd:test:output -->
   ## Test Results

   **Path:** Single/Child Issue
   **PR:** #<PR_NUM>
   **Branch:** <branch-name>

   ### 4-1. Existing Tests
   - Unit / widget / E2E run results (pass/fail counts)
   - Coverage evaluation (gaps if any)

   ### 4-2. QA Checklist
   #### Automated (already verified by tests)
   - [x] <item>
   #### Manual (requires human verification)
   - [ ] <item>
   #### Regression
   - [ ] <item>

   ### Self-Review
   - <issues noted, or "No gaps">
   <!-- /sdd:test:output -->
   ```

## Work — Parent Issue path

Child Issues have individual tests; cross-child integration tests may be needed at the parent level.

1. Read the parent Issue body + design output + children PRs:
   ```bash
   gh issue view $1
   gh api repos/$OWNER_REPO/issues/$1/comments \
     --jq '.[] | select(.body | contains("sdd:design:output") or contains("sdd:children:output")) | .body'
   # Then for each child: gh pr list --search "Refs #<child>"; gh pr view <PR_NUM>
   ```

2. **4-0. Test setup detection**:
   - Framework (Jest, Pytest, Go test, Playwright, Cypress, etc.)
   - Test directory structure (`tests/`, `__tests__/`, `e2e/`)
   - Test run command
   - Test configuration files
   - If no E2E setup is found → recommend a framework based on the tech stack; return `FAIL: no E2E test setup detected; recommended framework: <name>; user confirmation required`. The orchestrator surfaces this to the user; on user confirmation, the atom is re-invoked with the framework choice in its prompt.

3. **4-1. Integration E2E tests**:
   - Identify cross-child integration scenarios from the design output and the children's PRs.
   - If integration tests are needed:
     - Create test branch: `test/<parent-feature-name>`.
     - Write E2E test code following existing framework patterns.
     - Run E2E tests → record results.
     - Create a PR for the integration tests:
       ```bash
       gh pr create --title "test: <parent feature> integration tests" \
         --body "Refs #$1\n\n<summary>\n\n## Manual Test Checklist\n<items>"
       ```
   - If no integration tests are needed (children's tests already cover all scenarios): document the reasoning in the report.

4. **4-2. QA checklist** (parent-level):
   - Cross-child integration scenarios
   - Regression test targets across the whole parent feature

5. **Self-review** against `ai-review-test.md` "Additional Review". Fix gaps inline.

6. **Post to Issue** with `<!-- sdd:test:output -->` marker (parent variant of the body — include the integration PR URL if created).

## Return contract

Return EXACTLY ONE LINE on its own, prefixed by `>>> RESULT <<<`:

```
>>> RESULT <<<
OK SINGLE PR: #N
```
or
```
>>> RESULT <<<
OK PARENT INTEGRATION_PR: #M
```
or
```
>>> RESULT <<<
OK PARENT NO_INTEGRATION
```
or
```
>>> RESULT <<<
FAIL: <one-line reason, max 200 chars, no newlines>
```

- `OK SINGLE PR: #N` — single/child path; existing PR validated; QA checklist posted.
- `OK PARENT INTEGRATION_PR: #M` — parent path; integration test PR created.
- `OK PARENT NO_INTEGRATION` — parent path; children's tests sufficient; no integration PR needed.
- `FAIL: <reason>` — could not complete (tests failed, no PR found, no E2E setup detected, parent has incomplete children, etc.).

## Hard rules

- You are a single-subagent atom. Do NOT invoke the Agent tool. Do NOT spawn subagents.
- Do NOT invoke `/sdd <command>` or the Skill tool.
- Do NOT perform manual QA — that is the user's role in the orchestrator's Phase 2.
- Do NOT update labels or close the Issue — the orchestrator handles label transitions.
- Do NOT set Claude as co-author in commits (when creating an integration PR for parent path).
