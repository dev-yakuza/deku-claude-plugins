# ATOM: implement_red

**Single-subagent worker. MUST NOT spawn subagents. MUST NOT call the Agent tool.**

Executes TDD step 3-1: write failing test(s) for the next implementation increment. Must end in confirmed Red state.

> **Bash Command Execution**: every shell snippet below is its own simple Bash tool call — no `&&`, `||`, `;`, `|`, `$(...)`, `VAR=$(...)`, or heredocs. See **Bash Command Execution Rules** in `${CLAUDE_SKILL_DIR}/SKILL.md`.

## Inputs

- `$1` — Issue number
- `$2` — feature branch name (from `implement_plan` atom)
- Optional `$3` — retry feedback (JSON array of findings) from a prior round's step review

## Preconditions

- The Issue must have `<!-- sdd:design:output -->` and `<!-- sdd:implement:plan -->`.
- The branch `$2` exists and is checked out.

## Work

### Step 0: Pre-flight context discovery

If `$3` (retry feedback) is provided → **skip this step entirely**.

Otherwise, follow `${CLAUDE_SKILL_DIR}/commands/atoms/_preflight.md` Section A for the **Code-focused** tier. Execute Section B item 4 only (target directory survey).

For Red specifically: the target dir comes from the design's File Structure (test files). Focus the directory read on existing test patterns — fixtures, assertion style, mock setup.

Apply Section D failure handling. Record findings for the Section F self-review trace.

### Main work (numbered steps below)

1. Resolve owner/repo + verify branch:
   ```bash
   gh repo view --json nameWithOwner -q .nameWithOwner    # observe owner/repo
   git rev-parse --abbrev-ref HEAD
   ```
   If not on `$2`, run `git checkout $2`.

2. Read context (design + plan only — do NOT read analyze):
   ```bash
   gh issue view $1
   gh api repos/<owner>/<repo>/issues/$1/comments \
     --jq '.[] | select(.body | contains("sdd:design:output") or contains("sdd:implement:plan")) | .body'
   ```

3. Detect parent reference (for PR body later) per Common Definitions → Parent/Child Issue Detection in `${CLAUDE_SKILL_DIR}/SKILL.md`.

4. **Write failing test code** per the implementation plan. Cover:
   - Main scenarios from the plan
   - Edge cases identified in the design
   - Specific, meaningful assertions (not just "no throw")

5. Run the test command (auto-detect from repo: `npm test`, `flutter test`, `pytest`, `cargo test`, `go test`, etc.) → **confirm tests fail** (Red state). Inspect output to confirm the failures are for the **right reasons** (assertion failures, not import errors).

6. If `$3` (retry feedback) is provided: address each finding before proceeding. Parse `$3` as JSON per `${CLAUDE_SKILL_DIR}/commands/atoms/_review_helpers.md` Section B.

7. **Self-review (blockers only)**:
   - [ ] Tests file syntactically valid (test runner can parse)
   - [ ] Tests actually run (no compilation errors)
   - [ ] Tests fail (Red confirmed)
   - [ ] No `skip`/`only`/`focus` markers left in

8. **Commit** the failing tests using the repo's convention. Inspect `git log --oneline -20` to match style. Do NOT include Claude as co-author.

   ```bash
   git add <test-files>
   git commit -m "test: <description> (Red)"
   ```

## Return contract

```
>>> RESULT <<<
OK RED COMMIT: <sha>
```
or
```
>>> RESULT <<<
FAIL: <one-line reason, max 200 chars, no newlines>
```

- `OK RED COMMIT: <sha>` — failing tests committed; ready for `implement_green`. Inline the literal commit sha from `git rev-parse HEAD`.
- `FAIL: <reason>` — could not complete.

## Hard rules

- Single-subagent atom. Do NOT invoke the Agent tool or Skill tool.
- Do NOT read the analyze output.
- Do NOT implement production code in this step — tests must fail because the production code is missing or incomplete.
- Do NOT set Claude as co-author in commits.
- Do NOT push the branch — pushing happens at `implement_pr` or via separate steps.
