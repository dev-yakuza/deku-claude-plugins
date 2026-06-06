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
OK GREEN COMMIT: <sha>
```
or
```
>>> RESULT <<<
FAIL: <one-line reason>
```

## Hard rules

- Single-subagent atom. Do NOT invoke the Agent tool or Skill tool.
- Do NOT read the analyze output.
- Do NOT over-implement — minimal is the contract. Over-implementation will be flagged by reviewers.
- Do NOT set Claude as co-author.
- Do NOT push the branch.
