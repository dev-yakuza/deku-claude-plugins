# ROLLBACK

**Roll back an Issue to a previous stage.**

Usage: `/sdd rollback <issue> <target-stage>`

## Inputs

- `$1` — Issue number
- `$2` — target stage: `analyze` | `design` | `implement` (cannot roll back to `test` or `done`)

## Input Validation
Before any other step: validate `$1` per Common Definitions → Issue Validation in `<<SKILL_DIR>>/SKILL.md`. If `$1` is a Pull Request, stop without making changes.

## Process:
1. Read current Issue labels and stage
2. Validate rollback direction:
   - Can only roll back to an **earlier** stage (e.g. `design` → `analyze`, `implement` → `design`)
   - Cannot roll back to `test` or `done`
   - If already at or before the target stage → report and do nothing
3. Confirm with user before proceeding:
   ```
   Rolling back Issue #$1 from <current stage> to <target stage>.
   This will:
   - Change label from <current> to <target>
   - Previous stage outputs in Issue comments will be preserved for reference
   ```
4. On user confirmation, update labels
5. Post a rollback notice as Issue comment — follow `<<SKILL_DIR>>/commands/atoms/_review_helpers.md` Section F (mandatory temp-file pattern).
   - **Marker**: `<!-- sdd:rollback -->`
   - **Temp file path**: `/tmp/sdd-rollback-$1.md`
   - **Step 1** (Write tool): render the body into the temp file:
     ```markdown
     <!-- sdd:rollback -->
     **Rolled back** from `<current stage>` to `<target stage>`.
     Reason: <user's reason or "requested by user">
     <!-- /sdd:rollback -->
     ```
   - **Step 2** (Bash): create a new rollback notice (no duplicate prevention — every rollback is a new event):
     ```bash
     gh issue comment $1 --body-file /tmp/sdd-rollback-$1.md
     ```
6. **Read + execute inline (do NOT spawn a subagent)** the target stage command: read `<<SKILL_DIR>>/commands/$2.md` and execute its instructions for Issue #$1 in this same main session. Spawning a subagent here would create nested-subagent spawning when the target orchestrator spawns atoms.

## Parent Issue rollback:
- Rolling back a parent Issue to `design` does NOT delete child Issues
- Child Issues remain as-is; the user can close them manually if the design changes significantly
- Warn the user: "Existing child Issues (#124, #125, ...) were created from the previous design. Review and close them if the new design changes scope."

## Child Issue rollback:
- Same as single Issue rollback
- If rolling back to `analyze`, warn that the new analysis/design should remain consistent with the parent's design
