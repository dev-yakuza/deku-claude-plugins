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
   If exit code 0 (no staged changes) — skip commit; return `OK REFACTOR EMPTY`.

   Otherwise:
   ```bash
   git add <files>
   git commit -m "refactor: <description>"
   ```

   No Claude co-author.

## Return contract

```
>>> RESULT <<<
OK REFACTOR COMMIT: <sha>
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

- `OK REFACTOR COMMIT: <sha>` — refactor applied and committed.
- `OK REFACTOR EMPTY` — no refactor needed (code was already clean).
- `FAIL: <reason>` — could not complete (e.g., refactor broke tests and couldn't be salvaged).

## Hard rules

- Single-subagent atom. Do NOT invoke the Agent tool or Skill tool.
- Do NOT change behavior — refactor preserves behavior; tests are the contract.
- Do NOT skip running tests after each refactor change.
- Do NOT set Claude as co-author.
- Do NOT push the branch.
