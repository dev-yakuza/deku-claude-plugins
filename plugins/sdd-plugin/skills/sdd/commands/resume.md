# RESUME

**Resume work on an Issue from where it left off.**

Automatically detect the current stage and continue the process.

## Process:
1. Read Issue labels to determine current stage:
   ```bash
   gh issue view $1 --json labels,title --jq '{title: .title, labels: [.labels[].name]}'
   ```
2. Check Issue comments for existing stage outputs:
   ```bash
   gh api repos/{owner}/{repo}/issues/$1/comments --jq '.[] | select(.body | contains("sdd:analyze:output") or contains("sdd:design:output") or contains("sdd:children:output")) | .body'
   ```
   - Check for `<!-- sdd:analyze:output -->` marker
   - Check for `<!-- sdd:design:output -->` marker
   - Check for `<!-- sdd:children:output -->` marker (parent Issue with children)
3. Check related PRs and their status:
   ```bash
   gh pr list --search "issue:$1" --json number,title,state
   ```

## If Parent Issue (has `<!-- sdd:children:output -->` marker):
1. Read child Issue numbers from the children comment
2. Check each child Issue's current label
3. Report overall progress:
   ```
   Issue #$1: <title> (Parent)
   Child Issues:
   - #124: <name> → sdd:done ✓
   - #125: <name> → sdd:implement (in progress)
   - #126: <name> → sdd:analyze (not started)
   ```
4. Determine action:
   - If all children `sdd:done`:
     - Update parent label: `gh issue edit $1 --remove-label "sdd:implement" --add-label "sdd:test"`
     - Execute **TEST** on parent (read `${CLAUDE_SKILL_DIR}/commands/test.md`)
   - If any child is incomplete → ask user which child to resume, then execute **RESUME** on that child

## If Single Issue or Child Issue:

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
   - If no open PRs and no merged PRs → start PR (3-0)
   - If open PR exists → check branch, read PR diff, and continue TDD cycle
   - If PR was closed (not merged) → warn user, ask whether to reopen or start a new PR
   - If branch exists but no PR → ask user whether to create PR from existing branch or start fresh
   - If PR exists but branch was deleted → start a new branch and PR (3-0)

Report current status to user before continuing:
   ```
   Issue #$1: <title>
   Current stage: <stage>
   Resuming from: <specific point>
   ```
Check skip-review setting (see Common Definitions → Skip Review Setting):
- If the determined stage (e.g. `analyze`, `design`, `implement`) is in skip-review → **skip confirmation** and immediately read the appropriate command file from `${CLAUDE_SKILL_DIR}/commands/` and execute.
- If NOT in skip-review → ask user for confirmation, then read the appropriate command file from `${CLAUDE_SKILL_DIR}/commands/` and execute.
