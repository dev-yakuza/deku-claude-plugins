# REVIEW

Review the current stage output of an Issue.

## Input Validation
Before any other step: validate `$1` per Common Definitions → Issue Validation in `${CLAUDE_SKILL_DIR}/SKILL.md`. If `$1` is a Pull Request, stop without making changes.

## Determine Issue type:

1. Check if this is a parent Issue (has `<!-- sdd:children:output -->` marker in comments)
2. If **parent Issue** → execute **Parent Review** below
3. If **single Issue or child Issue** → execute **Standard Review** below

## Standard Review (single Issue or child Issue):

1. Determine current stage from Issue labels
2. Read the latest output from Issue comments
3. Perform AI review based on stage:
   - **analyze**: missing features, ambiguous descriptions, What/Why sufficient?
   - **design**: design matches requirements? missing impact scope? feasible?
   - **implement**: code quality, pattern consistency, test coverage?
   - **test**: test coverage, regression risks?
4. If child Issue: also check consistency with parent Issue's design
   - Read parent's design output and verify child's work aligns with overall architecture
5. Post review result as Issue comment

## Parent Review:

1. Read child Issue numbers from the children comment
2. For each child Issue, check:
   - Current stage (label)
   - Latest output quality (read comments)
   - If in `implement` stage: check PR status and code quality
3. Generate a summary review:
   ```
   ## SDD Parent Review: #$1

   ### Overall Progress
   - Completed: N / Total child Issues
   - In progress: #<numbers>
   - Not started: #<numbers>

   ### Per-child Review
   - #124: <status> — <brief assessment>
   - #125: <status> — <brief assessment>

   ### Cross-cutting Concerns
   - <consistency issues between child implementations>
   - <shared dependency conflicts>
   - <integration risks>
   ```
4. Post review result as Issue comment on parent Issue
