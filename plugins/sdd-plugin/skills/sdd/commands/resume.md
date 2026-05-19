# RESUME

**Resume work on an Issue from where it left off. Pure dispatcher.**

This file is a **dispatcher**. It runs in the main session, reads Issue state from GitHub (labels + comments + PRs), determines which stage orchestrator to invoke, and then reads + executes that orchestrator. It does **NOT** itself spawn subagents — the orchestrators it routes to are responsible for atom spawning.

## Input Validation

Before any other step: validate `$1` per Common Definitions → Issue Validation in `${CLAUDE_SKILL_DIR}/SKILL.md`. If `$1` is a Pull Request, stop without making changes.

## Process

1. **Read Issue labels** to determine the nominal stage:
   ```bash
   gh issue view $1 --json labels,title --jq '{title: .title, labels: [.labels[].name]}'
   ```

2. **Check Issue comments for existing stage outputs** (use a single API call):
   ```bash
   OWNER_REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
   gh api repos/$OWNER_REPO/issues/$1/comments \
     --jq '.[] | select(.body | contains("sdd:analyze:output") or contains("sdd:design:output") or contains("sdd:children:output") or contains("sdd:implement:plan") or contains("sdd:test:output")) | .body'
   ```
   Note presence/absence of:
   - `<!-- sdd:analyze:output -->`
   - `<!-- sdd:design:output -->`
   - `<!-- sdd:children:output -->` (parent Issue indicator)
   - `<!-- sdd:implement:plan -->`
   - `<!-- sdd:test:output -->`

3. **Check related PRs**:
   ```bash
   gh pr list --search "Refs #$1" --json number,title,state,headRefName
   ```

## Dispatch: Parent Issue (has `<!-- sdd:children:output -->`)

1. Read child Issue numbers from the children comment.
2. Check each child's current label.
3. Report progress to the user:
   ```
   Issue #$1: <title> (Parent)
   Child Issues:
   - #124: <name> → sdd:done ✓
   - #125: <name> → sdd:implement (in progress)
   - #126: <name> → sdd:analyze (not started)
   ```
4. **Determine the action**:
   - **If all children are `sdd:done`**:
     - Update parent label: `gh issue edit $1 --remove-label "sdd:implement" --add-label "sdd:test"` (label transitions only — do NOT spawn subagents).
     - **Read + execute inline (do NOT spawn a subagent)**: read `${CLAUDE_SKILL_DIR}/commands/test.md` and execute its instructions for Issue #$1 in this main session. The test orchestrator handles the parent path internally.
   - **If any child is incomplete**:
     - Check skip-review setting (Common Definitions → Skip Review Setting).
     - If skip-review contains any of `analyze`, `design`, `implement`, `pr` → **stop here** without asking. Report pending children and exit cleanly. The surrounding flow (e.g., `/sdd batch` or `/sdd auto`) is responsible for queuing the pending children for processing.
     - Otherwise → ask user which child to resume; then **read + execute inline (do NOT spawn a subagent)**: read `${CLAUDE_SKILL_DIR}/commands/resume.md` and execute for the chosen child Issue in this main session.

## Dispatch: Single Issue or Child Issue

Determine the resume point based on findings:

| Label                  | Output exists                                  | Dispatch target                                                  |
|------------------------|------------------------------------------------|------------------------------------------------------------------|
| (no SDD label)         | —                                              | Add `sdd:analyze` label, then `analyze.md`                       |
| `sdd:analyze`          | No `analyze:output`                            | `analyze.md`                                                     |
| `sdd:analyze`          | `analyze:output` exists                        | User completed analyze but label not advanced — `analyze.md` re-confirms (it will detect the existing output via duplicate prevention) |
| `sdd:design`           | `analyze:output` present, no `design:output`   | `design.md`                                                      |
| `sdd:design`           | `design:output` exists                         | `design.md` (re-confirm pattern, same as above)                  |
| `sdd:implement`        | `design:output` exists, no PR                  | `implement.md` (will run plan + TDD from scratch)                |
| `sdd:implement`        | open PR exists                                 | `implement.md` (the TDD atom's mode detection will continue from the existing PR) |
| `sdd:implement`        | PR closed (not merged)                         | Ask user: reopen or start a new PR; then `implement.md`          |
| `sdd:implement`        | branch exists, no PR                           | Ask user: create PR from existing branch or start fresh; then `implement.md` |
| `sdd:test`             | PR(s) present                                  | `test.md`                                                        |
| `sdd:done`             | —                                              | Report: "Issue is already complete." Stop.                       |

For the dispatch action, read the target orchestrator file and execute its instructions. **resume.md itself does not spawn subagents.**

## Reporting

Before dispatching, report current status to the user:

```
Issue #$1: <title>
Current stage: <stage>
Resuming from: <specific point>
```

## skip-review handling

Check skip-review setting (Common Definitions → Skip Review Setting):

- If the determined stage's skip-review key (`analyze` / `design` / `implement`) is set in `.github/.sdd-config` → **skip user confirmation** and immediately read + execute the target orchestrator. This allows `/sdd auto` and `/sdd batch` to chain stages without prompting. (Note: `pr` and `qa` are skip-review keys consumed inside `implement.md` / `test.md` respectively, not dispatch targets of resume. The test stage's user gate is `qa`, not `test` — `test` is not a valid skip-review value.)
- If NOT in skip-review → ask the user for confirmation ("Resume from <stage>? [y/N]"), then read + execute the target orchestrator.

## Notes

- **resume.md is a dispatcher, not a worker.** It determines the target stage based on Issue state and reads + executes the corresponding orchestrator. All atom spawning happens inside those orchestrators (analyze.md, design.md, implement.md, test.md).
- **Idempotent re-entry.** Calling `/sdd resume <N>` multiple times on the same Issue produces the same dispatch decision based on the current state. If the previous run reached a partial state, the target orchestrator's atom-level duplicate prevention (markers) ensures comments are updated in place rather than duplicated.
- **Safe within `/sdd auto` loops.** Because resume.md does not itself spawn subagents, the orchestrators it dispatches to are the ONLY layer that spawns. The atoms inside those orchestrators are leaves. There is no nesting risk.
