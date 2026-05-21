# ATOM: implement_plan

**Single-subagent worker. MUST NOT spawn subagents. MUST NOT call the Agent tool.**

Produces the test plan + implementation plan for SDD Stage 3, posts it to the Issue, and creates the feature branch. Self-reviews inline (the implement-plan review point 3-0 is `self_only`).

> **Bash Command Execution**: run every shell snippet below as its own simple Bash tool call — no `&&`, `||`, `;`, `|`, `$(...)`, `VAR=$(...)`, or heredocs. Inline literal values; do not use shell variables. See **Bash Command Execution Rules** in `${CLAUDE_SKILL_DIR}/SKILL.md`.

## Inputs

- `$1` — Issue number (already validated by the orchestrator as an Issue, not a PR)

## Preconditions

- The Issue must already have an `<!-- sdd:design:output -->` comment. Otherwise return `FAIL: design output not found on Issue #$1`.
- The Issue must NOT be a parent (must not have `<!-- sdd:children:output -->`). The orchestrator handles that branch before calling this atom.

## Work

1. Resolve owner/repo and read context:
   ```bash
   gh repo view --json nameWithOwner -q .nameWithOwner    # Bash call 1: observe owner/repo from output; inline as <owner>/<repo> below (no shell variables)
   gh issue view $1
   gh api repos/<owner>/<repo>/issues/$1/comments \
     --jq '.[] | select(.body | contains("sdd:design:output")) | .body'
   ```
   Read ONLY the design output and the Issue body's Definition of Done. Do NOT read the analyze output — the design has already incorporated those requirements.

2. Detect child Issue per Common Definitions → Parent/Child Issue Detection in `${CLAUDE_SKILL_DIR}/SKILL.md` (multi-language regex `(Parent|상위 |親)Issue: #<number>` inside `<!-- sdd:child-issue -->`). If a parent reference is found, capture the parent number for branch naming.

3. **Create the feature branch**:
   - Single Issue: `feat/<feature-name>` (derive `<feature-name>` from Issue title, kebab-cased)
   - Child Issue: `feat/<parent-feature>/<child-feature>` (e.g., `feat/user-profile/avatar-upload`)
   - Check git history first for branch naming convention; follow what's there.
   ```bash
   git checkout -b <branch-name>
   ```
   - If the branch already exists from a prior implement attempt, check it out instead of creating (`git checkout <branch-name>`). The TDD atom will continue from existing state.

4. Write the **test plan** for this PR. Classify each test case by behavioral path:
   - **Happy path**: Normal expected flows
   - **Error path**: Invalid input, failure scenarios, error handling
   - **Boundary conditions**: Edge values, empty/null, limits, overflow
   - **Concurrent/State**: Race conditions, state transitions (if applicable)

5. Write the **implementation plan** based on the test plan. Outline:
   - Which files to add/modify (consistent with design's File Structure section)
   - Order of operations
   - Any setup/teardown required

6. **Self-review** the plan against `${CLAUDE_SKILL_DIR}/commands/ai-review-implement.md` "Plan (3-0)" section (review type: self_only):
   - Test plan covers all design items for this PR scope
   - Test plan classifies cases by behavioral path
   - Implementation plan is consistent with the test plan
   - Plan follows the architecture decisions from the design
   - Additional self-review: feasibility, approach, risk; compare against design output

   If issues found → fix inline before posting. Self-review is non-retriable at this layer.

7. Determine language from `.github/.sdd-lang` (same fallback rules as other atoms).

8. **Post the plan** to the Issue with the marker `<!-- sdd:implement:plan -->`. Use duplicate prevention.

   Comment body format:
   ```
   <!-- sdd:implement:plan -->
   ## Implementation Plan

   **Feature branch:** `<branch-name>`

   ### Test Plan
   #### Happy path
   - <test cases>
   #### Error path
   - <test cases>
   #### Boundary conditions
   - <test cases>
   #### Concurrent/State
   - <test cases or "N/A">

   ### Implementation Plan
   1. <ordered steps>
   2. ...

   ### Self-Review
   - Verdict: PASS (after self-review and fixes)
   <!-- /sdd:implement:plan -->
   ```

## Return contract

Return EXACTLY ONE LINE on its own, prefixed by `>>> RESULT <<<`:

```
>>> RESULT <<<
OK BRANCH: <branch-name>
```
or
```
>>> RESULT <<<
FAIL: <one-line reason, max 200 chars, no newlines>
```

- `OK BRANCH: <branch-name>` — plan posted, branch created and checked out. The orchestrator passes the branch name to the TDD atom.
- `FAIL: <reason>` — could not complete (design missing, branch creation failed, etc.).

## Hard rules

- You are a single-subagent atom. Do NOT invoke the Agent tool. Do NOT spawn subagents.
- Do NOT invoke `/sdd <command>` slash commands or the Skill tool.
- Do NOT read the analyze output — it has already been incorporated into the design.
- Do NOT start writing test code or implementation code in this atom — only plan. The TDD atom does the actual coding.
- Do NOT create a PR in this atom — the TDD atom creates it after Red/Green/Refactor.
- Follow the existing repo's git history for branch naming and commit message conventions.
- Do NOT set Claude as co-author in commits (rule from `implement.md`).
