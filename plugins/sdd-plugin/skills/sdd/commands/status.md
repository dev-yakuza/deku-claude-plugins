# STATUS

Check the current progress of an Issue.

## Input Validation
Before any other step: validate `$1` per Common Definitions → Issue Validation in `${CLAUDE_SKILL_DIR}/SKILL.md`. If `$1` is a Pull Request, stop without making changes.

## Process:

1. Read Issue labels: `gh issue view $1 --json labels`
2. Check Issue comments for each stage output:
   - `<!-- sdd:analyze:output -->` exists?
   - `<!-- sdd:design:output -->` exists?
   - `<!-- sdd:children:output -->` exists? (parent Issue)
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
