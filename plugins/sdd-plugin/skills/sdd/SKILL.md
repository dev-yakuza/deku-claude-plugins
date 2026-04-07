---
name: sdd
description: "Spec-Driven Development - AI collaborative development process with GitHub integration. Use when working on GitHub Issues with a structured process: analyze → design → implement (TDD) → test."
argument-hint: "<command> [issue-number]"
user-invocable: true
---

# SDD (Spec-Driven Development)

You are executing the SDD process. Route to the appropriate command based on `$0`.

## Command Routing

- If `$0` is "init" → execute **INIT** with language `$1` (default: en)
- If `$0` is "analyze" → execute **ANALYZE** with issue `$1`
- If `$0` is "design" → execute **DESIGN** with issue `$1`
- If `$0` is "implement" → execute **IMPLEMENT** with issue `$1`
- If `$0` is "test" → execute **TEST** with issue `$1`
- If `$0` is "resume" → execute **RESUME** with issue `$1`
- If `$0` is "status" → execute **STATUS** with issue `$1`
- If `$0` is "review" → execute **REVIEW** with issue `$1`
- If `$0` is "help" or empty → execute **HELP**

---

## INIT

Set up SDD for the current GitHub repository.

**Language argument:** `$1` determines the language for Issue templates.
- `ko`, `korean`, `한국어` → Korean
- `ja`, `japanese`, `日本語` → Japanese
- `en`, `english`, or empty → English (default)

1. Copy Issue templates from `${CLAUDE_SKILL_DIR}/templates/{lang}/issue_*.yml` to `.github/ISSUE_TEMPLATE/`
   - Select the template directory based on the language argument
2. Save the selected language to `.github/.sdd-lang` file for other commands to reference
3. Create GitHub labels:
   ```bash
   gh label create "sdd:analyze" --color "1d76db" --description "SDD: Requirements Analysis" --force
   gh label create "sdd:design" --color "0e8a16" --description "SDD: Design" --force
   gh label create "sdd:implement" --color "e4e669" --description "SDD: Implementation" --force
   gh label create "sdd:test" --color "f9d0c4" --description "SDD: Testing" --force
   gh label create "sdd:done" --color "0075ca" --description "SDD: Done" --force
   gh label create "sdd:child" --color "d4c5f9" --description "SDD: Child Issue" --force
   ```
4. Report completion with a summary of what was installed.

---

## ANALYZE

**Stage 1: Requirements Analysis (What / Why)**

Focus ONLY on What and Why. Do NOT discuss How (technical implementation).

### Process:
1. Read the Issue: `gh issue view $1`
2. Check if this is a child Issue (body contains `Parent Issue: #<number>`):
   - If yes: read the parent Issue's analyze and design outputs for context
     ```bash
     gh api repos/{owner}/{repo}/issues/<parent>/comments --jq '.[].body'
     ```
   - Use parent context to understand the broader scope, but focus analysis on this child's sub-feature only
3. Classify the request type (new feature / enhancement / bug fix / refactoring)
4. Analyze What (feature list) and Why (background, motivation)
5. If information is missing, ask the user (do NOT ask How questions)
6. Split into feature list with priorities
7. Read the language setting from `.github/.sdd-lang` (default: en)
8. Format output using the template in `${CLAUDE_SKILL_DIR}/templates/{lang}/output_analyze.md`

### Self-Review:
- Check for missing features, ambiguous descriptions
- Verify What/Why are sufficient
- If issues found, go back and improve

### User Review:
- Present the output to the user
- Ask for confirmation on direction and priorities
- On approval: post as Issue comment and update label to `sdd:design`

```bash
# Post output as Issue comment
gh issue comment $1 --body "$(cat <<'EOF'
<output content here>
EOF
)"

# Update label
gh issue edit $1 --remove-label "sdd:analyze" --add-label "sdd:design"
```

---

## DESIGN

**Stage 2: Design (How)**

Define HOW to implement based on the requirements.

### Process:
1. Read analyze output from Issue comments:
   ```bash
   gh api repos/{owner}/{repo}/issues/$1/comments --jq '.[].body' | grep -A 1000 'sdd:analyze:output' | grep -B 1000 '/sdd:analyze:output'
   ```
2. Check if this is a child Issue (body contains `Parent Issue: #<number>`):
   - If yes: read the parent Issue's design output for context (architecture decisions, PR split rationale, constraints)
     ```bash
     gh api repos/{owner}/{repo}/issues/<parent>/comments --jq '.[].body' | grep -A 1000 'sdd:design:output' | grep -B 1000 '/sdd:design:output'
     ```
   - The child's design must be consistent with the parent's overall architecture and design decisions
   - Focus on the detailed design for this child's sub-feature only
3. Explore the codebase — analyze existing architecture and patterns
3. Identify impact scope (related files, screens, data)
4. Design file structure changes
5. Design data model changes (if applicable)
6. Identify constraints and risks
7. Create feature list with PR split
8. Read the language setting from `.github/.sdd-lang` (default: en)
9. Format output using the template in `${CLAUDE_SKILL_DIR}/templates/{lang}/output_design.md`

### Self-Review:
- Verify design matches requirements
- Check for missing impact scope
- Assess feasibility

### User Review:
- Present the output to the user
- Ask for confirmation on technical approach and PR split
- On approval:
  - If **single PR** → post as Issue comment and update label to `sdd:implement`
  - If **multiple PRs** → execute **Child Issue Creation** below, then update label to `sdd:implement`

### Child Issue Creation (when multiple PRs are needed):

When the design identifies 2 or more PRs, create a child Issue for each sub-feature:

1. Read the language setting from `.github/.sdd-lang` (default: en)
2. For each sub-feature in the design:
   - Format the child Issue body using the template in `${CLAUDE_SKILL_DIR}/templates/{lang}/output_child_issue.md`
   - Replace `{{parent_issue}}` with `$1`, `{{sub_feature_description}}` and `{{criteria}}` with design content
   ```bash
   gh issue create --title "[SDD Child] <parent title> - <sub-feature name>" \
     --body "<formatted body from template>" --label "sdd:analyze" --label "sdd:child"
   ```
3. Post the child Issue list as a comment on the parent Issue using the template in `${CLAUDE_SKILL_DIR}/templates/{lang}/output_children.md`
   - Add a row for each created child Issue to the table
4. Post design output as Issue comment on parent Issue
5. Update parent Issue label to `sdd:implement`
6. Ask user which child Issue to start with, then execute **ANALYZE** on that child Issue

---

## IMPLEMENT

**Stage 3: Implementation - TDD Cycle (Red → Green → Refactor)**

### Determine Issue type:

1. Check if this Issue has child Issues:
   ```bash
   gh api repos/{owner}/{repo}/issues/$1/comments --jq '.[].body' | grep 'sdd:children'
   ```
2. **Parent Issue (has children)**: Do NOT implement directly. Instead:
   - List child Issues and their current status
   - Ask user which child Issue to work on
   - Execute **ANALYZE** or **RESUME** on the selected child Issue
3. **Single Issue or Child Issue (no children)**: Execute TDD cycle below

### TDD Cycle (single Issue or child Issue):

Test scope: Unit tests / UI tests (widget tests, golden tests, etc.)

#### 3-0. PR Kickoff: Plan
1. Read design output from Issue comments
2. Create feature branch:
   - Single Issue: `feat/<feature-name>`
   - Child Issue: `feat/<parent-feature>/<child-feature>` (e.g. `feat/user-profile/avatar-upload`)
3. Write test plan for this PR
4. Write implementation plan based on test plan
5. **Self-review**: verify test coverage and feasibility
6. **User review**: confirm plan direction before proceeding

#### 3-1. Red: Write Failing Tests
1. Write test code based on test plan
2. Run tests → confirm failure (Red)
3. **Self-review**: check test code quality
4. **User review**: confirm test code

#### 3-2. Green: Minimal Implementation
1. Implement minimal code to pass tests
2. Run tests → confirm pass (Green)
3. **Self-review**: ensure no unnecessary code
4. **User review**: confirm implementation direction

#### 3-3. Refactor: Improve Code
1. Remove duplication, improve readability, clean up structure
2. Run tests → confirm still passing (Green)
3. **Self-review**: check code quality and pattern consistency
4. **User review**: confirm refactoring result

#### 3-4. PR Creation & Code Review
1. Summarize changes
2. Create PR:
   - Single Issue: `gh pr create --title "..." --body "Closes #$1\n\n..."`
   - Child Issue: `gh pr create --title "..." --body "Closes #$1\nParent Issue: #<parent>\n\n..."`
3. Re-run all tests → confirm pass
4. **Self-review**: check code consistency, verify no missing features
5. **User review**: final confirmation
6. Update label to `sdd:test`

### After child Issue reaches `sdd:done`:

If this Issue is a child Issue (Issue body contains `Parent Issue: #<number>`):

1. Find parent Issue number from Issue body:
   ```bash
   gh issue view $1 --json body --jq '.body' | grep -oP 'Parent Issue: #\K[0-9]+'
   ```
2. Read parent Issue's children comment:
   ```bash
   gh api repos/{owner}/{repo}/issues/<parent>/comments --jq '.[].body' | grep -A 1000 'sdd:children' | grep -B 1000 '/sdd:children'
   ```
3. Update the children comment — change this child's status to `sdd:done`:
   ```bash
   # Find the comment ID, then update it
   COMMENT_ID=$(gh api repos/{owner}/{repo}/issues/<parent>/comments --jq '.[] | select(.body | contains("sdd:children")) | .id')
   gh api repos/{owner}/{repo}/issues/comments/$COMMENT_ID -X PATCH --field body="<updated body>"
   ```
4. Check if ALL child Issues are now `sdd:done`:
   - If yes → add a comment to the parent Issue notifying all children are complete, and suggest running `/sdd test <parent>` or `/sdd resume <parent>`
   - If no → report remaining children to the user and ask which child to work on next

---

## TEST

**Stage 4: Testing**

Unit/UI tests are already done in Stage 3. This stage focuses on E2E and QA.

### Determine Issue type:

1. **Parent Issue (has children)**: Check all child Issues
   - Read child Issue numbers from the children comment
   - Check each child Issue's label:
     ```bash
     gh issue view <child-number> --json labels --jq '[.labels[].name]'
     ```
   - If any child Issue is NOT `sdd:done` → report which children are incomplete, ask user to complete them first
   - If ALL child Issues are `sdd:done` → proceed with parent-level E2E/QA below
2. **Single Issue or Child Issue**: proceed with E2E/QA below

### Process:
1. Read analyze/design outputs from Issue comments
2. If parent Issue: read all child Issues' implementation PRs to understand what was built
3. If single/child Issue: read implementation PR
4. Write E2E test code (integration tests)
5. Start test environment → run E2E tests → check results
6. Create QA checklist based on requirements
7. Identify regression test targets

### User Tasks:
1. Manual QA testing based on checklist
2. Run regression tests

### Self-Review:
- Analyze test logs, estimate bug causes
- If E2E tests fail, fix test code or identify bugs
- If bugs found → go back to Stage 3 for TDD bug fix cycle

### User Review:
- Confirm all test results
- All tests pass → update label to `sdd:done`

```bash
gh issue edit $1 --remove-label "sdd:test" --add-label "sdd:done"
```

---

## RESUME

**Resume work on an Issue from where it left off.**

Automatically detect the current stage and continue the process.

### Process:
1. Read Issue labels to determine current stage:
   ```bash
   gh issue view $1 --json labels,title --jq '{title: .title, labels: [.labels[].name]}'
   ```
2. Check Issue comments for existing stage outputs:
   ```bash
   gh api repos/{owner}/{repo}/issues/$1/comments --jq '.[].body'
   ```
   - Check for `<!-- sdd:analyze:output -->` marker
   - Check for `<!-- sdd:design:output -->` marker
   - Check for `<!-- sdd:children -->` marker (parent Issue with children)
3. Check related PRs and their status:
   ```bash
   gh pr list --search "issue:$1" --json number,title,state
   ```

### If Parent Issue (has `<!-- sdd:children -->` marker):
1. Read child Issue numbers from the children comment
2. Check each child Issue's current label:
   ```bash
   gh issue view <child-number> --json labels --jq '[.labels[].name]'
   ```
3. Report overall progress:
   ```
   Issue #$1: <title> (Parent)
   Child Issues:
   - #124: <name> → sdd:done ✓
   - #125: <name> → sdd:implement (in progress)
   - #126: <name> → sdd:analyze (not started)
   ```
4. Determine action:
   - If all children `sdd:done` → execute **TEST** on parent
   - If any child is incomplete → ask user which child to resume, then execute **RESUME** on that child

### If Single Issue or Child Issue:

Determine resume point based on findings:

   | Label | Output exists? | Action |
   |-------|---------------|--------|
   | `sdd:analyze` | No analyze output | Execute **ANALYZE** |
   | `sdd:design` | Analyze output exists, no design output | Execute **DESIGN** |
   | `sdd:implement` | Design output exists | Execute **IMPLEMENT** |
   | `sdd:test` | Implementation PRs merged | Execute **TEST** |
   | `sdd:done` | All complete | Report: Issue is already complete |
   | No SDD label | — | Add `sdd:analyze` label and execute **ANALYZE** |

For `sdd:implement` stage, further check sub-step:
   - If no open PRs → start PR (3-0)
   - If open PR exists → check branch, read PR diff, and continue TDD cycle

Report current status to user before continuing:
   ```
   Issue #$1: <title>
   Current stage: <stage>
   Resuming from: <specific point>
   ```
Ask user for confirmation, then execute the appropriate stage command

---

## STATUS

Check the current progress of an Issue.

1. Read Issue labels: `gh issue view $1 --json labels`
2. Check Issue comments for each stage output:
   - `<!-- sdd:analyze:output -->` exists?
   - `<!-- sdd:design:output -->` exists?
   - `<!-- sdd:children -->` exists? (parent Issue)
3. Check related PRs: `gh pr list --search "issue:$1"`
4. If parent Issue, check all child Issue statuses
5. Summarize current stage and progress

Output format (single Issue):
```
Issue #$1: <title>
Stage: <current stage based on label>
- [x] Analyze: completed
- [x] Design: completed
- [ ] Implement: in progress
- [ ] Test: not started
```

Output format (parent Issue):
```
Issue #$1: <title> (Parent)
Stage: implement
- [x] Analyze: completed
- [x] Design: completed (3 child Issues created)
- [ ] Implement:
  - #124: <name> → sdd:done ✓
  - #125: <name> → sdd:implement
  - #126: <name> → sdd:analyze
- [ ] Test: not started
```

---

## REVIEW

Review the current stage output of an Issue.

1. Determine current stage from Issue labels
2. Read the latest output from Issue comments
3. Perform AI review based on stage:
   - **analyze**: missing features, ambiguous descriptions, What/Why sufficient?
   - **design**: design matches requirements? missing impact scope? feasible?
   - **implement**: code quality, pattern consistency, test coverage?
   - **test**: test coverage, regression risks?
4. Post review result as Issue comment

---

## HELP

Display available commands and usage:

```
SDD (Spec-Driven Development) - AI Collaborative Development Process

Commands:
  /sdd init [lang]       Set up SDD for the current repository (Issue templates, labels)
                         Languages: en (default), ko/korean/한국어, ja/japanese/日本語
  /sdd analyze <issue>   Stage 1: Requirements Analysis (What/Why)
  /sdd design <issue>    Stage 2: Design (How)
  /sdd implement <issue> Stage 3: Implementation with TDD (Red → Green → Refactor)
  /sdd test <issue>      Stage 4: E2E and QA Testing
  /sdd resume <issue>    Auto-detect current stage and continue from where it left off
  /sdd status <issue>    Check current progress
  /sdd review <issue>    AI review of current stage output
  /sdd help              Show this help message

Workflow:
  1. /sdd init [lang]       → set up repository (choose language for templates)
  2. Create an Issue using SDD templates
  3. /sdd analyze <issue>   → analyzes What/Why, posts output to Issue
  4. /sdd design <issue>    → designs How, posts output to Issue
  5. /sdd implement <issue> → TDD cycle per PR
  6. /sdd test <issue>      → E2E tests and QA

  Interrupted? Run: /sdd resume <issue> → auto-detects stage and continues
```
