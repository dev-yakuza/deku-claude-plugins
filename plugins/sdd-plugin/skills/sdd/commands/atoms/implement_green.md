# ATOM: implement_green

**Single-subagent worker. MUST NOT spawn subagents. MUST NOT call the Agent tool.**

Executes TDD step 3-2: write minimal production code to make the failing tests pass. Must end in confirmed Green state.

> **Bash Command Execution**: every shell snippet below is its own simple Bash tool call — no `&&`, `||`, `;`, `|`, `$(...)`, `VAR=$(...)`, or heredocs. See **Bash Command Execution Rules** in `${CLAUDE_SKILL_DIR}/SKILL.md`.

## Inputs

- `$1` — Issue number
- `$2` — feature branch name
- Optional `$3` — retry feedback (JSON array)

## Preconditions

- The Issue must have `<!-- sdd:design:output -->` and `<!-- sdd:implement:plan -->`.
- The branch `$2` is checked out with the Red commit from `implement_red`.

## Work

### Step 0: Pre-flight context discovery

If `$3` (retry feedback) is provided → **skip this step entirely**.

Otherwise, follow `${CLAUDE_SKILL_DIR}/commands/atoms/_preflight.md` Section A for the **Code-focused** tier. Execute Section B item 4 only (target directory survey).

For Green specifically: focus the directory read on existing implementation patterns — error handling style, import conventions, naming.

Apply Section D failure handling. Record findings for the Section F self-review trace.

### Main work (numbered steps below)

1. Verify branch and Red state:
   ```bash
   git rev-parse --abbrev-ref HEAD
   ```
   If not on `$2`, `git checkout $2`.

2. Run tests once to confirm current Red state (sanity):
   - Detect test command. Run. Confirm failures.

3. Read context (design + plan):
   ```bash
   gh repo view --json nameWithOwner -q .nameWithOwner
   gh issue view $1
   gh api repos/<owner>/<repo>/issues/$1/comments \
     --jq '.[] | select(.body | contains("sdd:design:output") or contains("sdd:implement:plan")) | .body'
   ```

4. **Write minimal production code** to make the failing tests pass:
   - **Minimal**: only what's needed to pass the tests — no speculative features
   - Follow existing codebase patterns (use Read/Grep on similar implementations)
   - Match existing style/naming conventions

5. Run tests → **confirm pass** (Green state). All tests must pass; if regressions occur in pre-existing tests, fix them before continuing.

   Capture from the test runner output:
   - `<passed>` — number of passing tests (MUST equal total for Green)
   - `<failed>` — number of failing tests (MUST be 0 for Green)
   - `<total>` — total tests executed

   These numbers are reported in the return contract (step 8) and used by `tdd_step_review` to verify the Green claim. If the runner's output format makes any of these unobtainable, use `0` for that field — the reviewer will flag the missing evidence.

6. If `$3` (retry feedback) is provided: address each finding. Parse `$3` as JSON.

7. **Self-review (blockers only)**:
   - [ ] All tests pass
   - [ ] No debug artifacts left (console.log, dbg!, print, breakpoint())
   - [ ] No TODO/FIXME inserted that should be tracked elsewhere
   - [ ] Code is in the file paths designed (no surprise locations)

8. **Commit** the implementation:
   ```bash
   git add <impl-files>
   git commit -m "feat: <description> (Green)"
   ```

   Match repo's convention. No Claude co-author.

## Return contract

```
>>> RESULT <<<
OK GREEN COMMIT: <sha> TESTS: <passed>/<total> FAILED: 0
```
or
```
>>> RESULT <<<
FAIL: <one-line reason>
```

- `OK GREEN COMMIT: <sha> TESTS: <p>/<t> FAILED: 0` — minimal implementation committed, tests now passing. Inline the literal commit sha and observed counts. `FAILED` MUST be `0`. The orchestrator forwards this evidence to `tdd_step_review` so the reviewer can verify the Green claim it cannot re-run tests for.
- `FAIL: <reason>` — could not complete.

## Hard rules

- Single-subagent atom. Do NOT invoke the Agent tool or Skill tool.
- Do NOT read the analyze output.
- Do NOT over-implement — minimal is the contract. Over-implementation will be flagged by reviewers.
- Do NOT set Claude as co-author.
- Do NOT push the branch.
