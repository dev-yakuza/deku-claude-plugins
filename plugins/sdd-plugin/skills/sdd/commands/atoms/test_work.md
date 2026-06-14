# ATOM: test_work

**Single-subagent worker. MUST NOT spawn subagents. MUST NOT call the Agent tool.**

Produces the SDD Stage 4 (Test) output for one Issue: verifies existing tests pass, evaluates coverage, and creates a QA checklist. Handles two paths — Single/Child Issue (validate existing tests + QA checklist) and Parent Issue (integration E2E testing across children). Posts the result as an Issue comment.

## Inputs

- `$1` — Issue number (already validated by the orchestrator)
- Optional `$2` — retry signal. When the orchestrator invokes this atom in retry mode it passes the literal string `"retry"`. The atom self-fetches the previous round's review findings per `<<SKILL_DIR>>/commands/atoms/_review_helpers.md` Section C (single/child path: 3 stage markers; parent path: 3 stage markers + `<!-- sdd:review:parent -->`).

## Mode detection

Run before any work:

```bash
gh repo view --json nameWithOwner -q .nameWithOwner    # Bash call 1: observe owner/repo from output; inline as <owner>/<repo> below (no shell variables)
gh api repos/<owner>/<repo>/issues/$1/comments \
  --jq '.[] | select(.body | contains("<!-- sdd:children:output -->")) | .body'
```

- If `HAS_CHILDREN` is non-empty → **Parent Issue path**.
- Otherwise → **Single/Child Issue path**.

For Parent Issue path, also verify all children are `sdd:done` before running (read child numbers from the children comment, check each child's labels). If any child is not done → return `FAIL: parent has incomplete children: #X, #Y, ...`.

## Step 0: Pre-flight context discovery (both paths)

If `$2` (retry signal — non-empty, expected literal `"retry"`):
- Skip the preflight items below.
- **Execute `<<SKILL_DIR>>/commands/atoms/_review_helpers.md` Section C** to self-fetch the previous round's review findings before path-specific work. Markers (use Mode detection above to decide which set):
  - **Single/Child path** (`HAS_CHILDREN` empty): `<!-- sdd:review:test:completeness -->`, `<!-- sdd:review:test:quality -->`, `<!-- sdd:review:test:adversarial -->`
  - **Parent path** (`HAS_CHILDREN` non-empty): the 3 single/child markers **plus** `<!-- sdd:review:parent -->` (cross-child integration review)
- Hold the sorted array as `<retry-findings>` for use throughout the path-specific work below: prioritize addressing every `critical` and `major` finding; read `minor` as supporting context.
- If Section C returns `FAIL: ...` → propagate it as this atom's return value.

Else (first round, `$2` empty): follow `<<SKILL_DIR>>/commands/atoms/_preflight.md` — tier **Light**, Section B items 1 + 2 (project conventions + commit message style).

For `test_work` specifically: item 1's convention reading should pay attention to **testing conventions** (test framework, test directory layout, assertion style).

After Step 0, proceed to the path-specific work below (Single/Child or Parent).

---

## Work — Single/Child Issue path

E2E tests were already written in Stage 3 (implement) and included in the PR. This path validates them and produces a QA checklist.

1. Find the implementation PR:
   ```bash
   gh pr list --search "Refs #$1" --state open --json number --jq '.[0].number'   # Bash call: observe PR number; inline as <PR_NUM> below
   ```
   If empty → `FAIL: no open PR found for Issue #$1`.

2. Read the PR + Issue body (for DoD). Do NOT read analyze/design outputs.
   ```bash
   gh pr view <PR_NUM>
   gh pr diff <PR_NUM>
   gh issue view $1
   ```

3. **4-1. Verify existing tests**:
   - Check out the PR's branch locally (`gh pr checkout <PR_NUM>`).
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

6. **Self-review (blockers only)**: before posting, verify posting-blocking checks:
   - [ ] Marker is present (`<!-- sdd:test:output -->`)
   - [ ] Test results section is filled with actual pass/fail counts (no `<empty>` / TODO)
   - [ ] QA checklist sections (Automated / Manual / Regression) are filled
   - [ ] PR number is referenced if Single/Child path
   - [ ] Path label (`Single/Child Issue` vs `Parent Issue`) is set

   If a blocker fails → fix inline. Track for the `<details>` trace below.

   *Quality, completeness, risk evaluation are NOT done here — Agent reviewers' job.*

7. Determine language from `.github/.sdd-lang` (same fallback rules).

8. **Post to Issue** — follow `<<SKILL_DIR>>/commands/atoms/_review_helpers.md` Section F (mandatory temp-file pattern).
   - **Marker**: `<!-- sdd:test:output -->`
   - **Temp file path**: `/tmp/sdd-test-output-$1.md`
   - **Step 1** (Write tool): render the body (format below) into the temp file.
   - **Step 2** (Bash): search for existing comment id:
     ```bash
     gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | select(.body | contains("<!-- sdd:test:output -->")) | .id'
     ```
   - **Step 3** (Bash):
     - Empty → `gh issue comment $1 --body-file /tmp/sdd-test-output-$1.md`
     - Has id `<id>` → `gh api repos/<owner>/<repo>/issues/comments/<id> -X PATCH --field body=@/tmp/sdd-test-output-$1.md`

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

   <details>
   <summary>Self-review trace (blockers only)</summary>

   - [x] Test results filled
   - [x] QA checklist sections filled
   - [x] PR referenced

   </details>
   <!-- /sdd:test:output -->
   ```

   Skip the `<details>` block if nothing to record.

## Work — Parent Issue path

Child Issues have individual tests; cross-child integration tests may be needed at the parent level.

1. Read the parent Issue body + design output + children PRs:
   ```bash
   gh issue view $1
   gh api repos/<owner>/<repo>/issues/$1/comments \
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
     - Create a PR for the integration tests. Per the **Bash Command Execution Rules** in `<<SKILL_DIR>>/SKILL.md`, do NOT use heredoc or `$(cat <<EOF ...)` inside the Bash call. Instead, write the PR body to a temp file via the **Write** tool first, then pass it via `--body-file`:
       ```
       # Step 1 (Write tool, not Bash) — render body into /tmp/sdd-test-parent-<Issue>.md:
       #   Line 1: Refs #<Issue>           (inline the literal Issue number from $1)
       #   Line 2: (blank)
       #   Then:   <summary>, then blank, then `## Manual Test Checklist` and items
       ```
       ```bash
       # Step 2 (Bash tool — single simple gh call):
       gh pr create --title "test: <parent feature> integration tests" \
         --body-file /tmp/sdd-test-parent-<Issue>.md
       ```
   - If no integration tests are needed (children's tests already cover all scenarios): document the reasoning in the report.

4. **4-2. QA checklist** (parent-level):
   - Cross-child integration scenarios
   - Regression test targets across the whole parent feature

5. **Self-review (blockers only)**: before posting, verify posting-blocking checks:
   - [ ] Marker is present
   - [ ] Path label is `Parent Issue`
   - [ ] Integration PR URL is included (if `OK PARENT INTEGRATION_PR`) OR rationale for no-integration is documented (if `OK PARENT NO_INTEGRATION`)
   - [ ] QA checklist at parent level filled

   If a blocker fails → fix inline. Track for the `<details>` trace.

   *Cross-stage / cross-child integration analysis is NOT done here — the orchestrator spawns `parent_integration_review.md` for that.*

6. **Post to Issue** — follow `<<SKILL_DIR>>/commands/atoms/_review_helpers.md` Section F (mandatory temp-file pattern). Same procedure as the single/child path step 8 above:
   - **Marker**: `<!-- sdd:test:output -->`
   - **Temp file path**: `/tmp/sdd-test-output-$1.md`
   - Render the parent variant of the body (include the integration PR URL if created, and the `<details>`-block self-review trace before the closing marker, in the same style as the single/child path).
   - Search for existing id, then `gh issue comment $1 --body-file /tmp/sdd-test-output-$1.md` (create) OR `gh api repos/<owner>/<repo>/issues/comments/<id> -X PATCH --field body=@/tmp/sdd-test-output-$1.md` (update).

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
