# ATOM: implement_refactor

**Single-subagent worker. MUST NOT spawn subagents. MUST NOT call the Agent tool.**

Executes TDD step 3-3: refactor the implementation for clarity and structure while keeping tests green.

> **Bash Command Execution**: every shell snippet below is its own simple Bash tool call — no `&&`, `||`, `;`, `|`, `$(...)`, `VAR=$(...)`, or heredocs. See **Bash Command Execution Rules** in `${CLAUDE_SKILL_DIR}/SKILL.md`.

## Inputs

- `$1` — Issue number
- `$2` — feature branch name
- Optional `$3` — retry feedback (JSON array)

## Preconditions

- The branch has Red + Green commits.
- All tests are currently passing.

## Work

### Step 0: Pre-flight context discovery

If `$3` (retry) → skip. Else: follow `${CLAUDE_SKILL_DIR}/commands/atoms/_preflight.md` — tier **Code-focused**, Section B item 4 only (target directory survey).

For Refactor specifically: focus the directory read on existing structural patterns — extraction style, helper organization, naming conventions. Refactor should bring the new code closer to *these* patterns, not impose foreign ones.

### Main work (numbered steps below)

1. Verify branch and Green state:
   ```bash
   git rev-parse --abbrev-ref HEAD
   ```
   If not on `$2`, `git checkout $2`.

2. Run tests to confirm current Green state.

3. **Refactor** the implementation:
   - Remove duplication (DRY)
   - Improve naming (intention-revealing)
   - Simplify control flow
   - Clean up imports, unused vars, dead code
   - Remove debug artifacts (console.log, dbg!, print, breakpoint())
   - **Behavior must remain identical** — tests verify this

4. Run tests → **confirm still passing** (Green retained). If any test fails, the refactor changed behavior; back out and try again or accept the test change as a separate decision.

   Capture from the test runner output:
   - `<passed>` — number of passing tests
   - `<failed>` — number of failing tests (MUST be 0 to keep Green)
   - `<total>` — total tests executed

   `<passed>` and `<total>` MUST match the values reported by the prior `implement_green` step. A change in `<total>` (without a corresponding test-file edit in this refactor's diff) signals that tests were silently added/removed — fix before committing.

   These numbers are reported in the return contract (step 7) and used by `tdd_step_review` to verify the refactor preserved behavior.

   **Also remember the full test runner output text** — it is posted in step 8 as evidence the reviewer can cross-check against the reported counts (skipped when the refactor produces no commit).

5. If `$3` (retry feedback) is provided: address each finding.

6. **Self-review (blockers only)**:
   - [ ] All tests still pass
   - [ ] No new debug artifacts
   - [ ] No premature abstractions introduced (interface for one impl, factory for one type)
   - [ ] No new TODO/FIXME

7. **Commit** the refactor. If there are no changes (refactor not needed), skip the commit:
   ```bash
   git diff --staged --quiet
   ```
   If exit code 0 (no staged changes) — skip commit; return `OK REFACTOR EMPTY`. Do NOT run step 8 in this case.

   Otherwise:
   ```bash
   git add <files>
   git commit -m "refactor: <description>"
   ```

   No Claude co-author.

8. **Post test evidence comment** per `${CLAUDE_SKILL_DIR}/commands/atoms/_test_evidence.md`. Inputs: `<n>=3`, `<sha>` from `git rev-parse HEAD`, the captured `<passed>/<total>/<failed>`, and the full test runner output from step 4. Skip this step entirely when returning `OK REFACTOR EMPTY` (no commit, no test claim to verify). If the procedure returns the failure described in its Step 5, return that `FAIL:` from this atom.

## Return contract

```
>>> RESULT <<<
OK REFACTOR COMMIT: <sha> TESTS: <passed>/<total> FAILED: 0
```
or
```
>>> RESULT <<<
OK REFACTOR EMPTY
```
or
```
>>> RESULT <<<
FAIL: <one-line reason>
```

- `OK REFACTOR COMMIT: <sha> TESTS: <p>/<t> FAILED: 0` — refactor applied and committed; tests still passing with the same `<p>`/`<t>` as the prior Green step. `FAILED` MUST be `0`. The orchestrator forwards this evidence to `tdd_step_review` so the reviewer can verify behavior was preserved without re-running tests.
- `OK REFACTOR EMPTY` — no refactor needed (code was already clean). No test evidence required.
- `FAIL: <reason>` — could not complete (e.g., refactor broke tests and couldn't be salvaged).

## Hard rules

- Single-subagent atom. Do NOT invoke the Agent tool or Skill tool.
- Do NOT change behavior — refactor preserves behavior; tests are the contract.
- Do NOT skip running tests after each refactor change.
- Do NOT set Claude as co-author.
- Do NOT push the branch.
