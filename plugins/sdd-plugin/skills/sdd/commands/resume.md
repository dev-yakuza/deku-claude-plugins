# RESUME

**Resume work on an Issue from where it left off. Thin dispatcher.**

Spawns the `bootstrap` sub-agent to determine the current stage (label + comments + PR inspection in a separate sub-agent context). Then inline-reads the corresponding stage wrapper command (`analyze.md` / `design.md` / `implement.md` / `test.md`), which itself spawns a single `stage_<X>` sub-agent.

In Arch B (v1.0.0): bootstrap + stage wrapper chain replaces the v0.x main-session orchestrator inline. Each wrapper is thin (~100-200 lines) and delegates work to its `stage_<X>` sub-agent.

> **Bash Command Execution**: see `<<SKILL_DIR>>/commands/atoms/_bash_rules.md`.

## Input Validation

Validate `$1` per Common Definitions → Issue Validation in `<<SKILL_DIR>>/SKILL.md`. If `$1` is a Pull Request, stop without making changes.

## Process

### Step 1: Spawn bootstrap

Spawn one sub-agent via the Agent tool:
- `subagent_type`: `general-purpose`
- `model`: `haiku` (bootstrap is lightweight)
- `description`: `bootstrap dispatch for #$1`
- `prompt`:
  > Read `<<SKILL_DIR>>/commands/atoms/bootstrap.md` and execute its instructions for Issue #$1.
  > Return EXACTLY one line in the contract specified by that file (the `>>> RESULT <<<` BOOTSTRAP: line).

Parse the `>>> RESULT <<<` line:
- `FAIL: <reason>` → report failure to the user and stop.
- `BOOTSTRAP: stage=<X> depth=<dial> branch=<...> pr=<...> parent=<bool> children=<...>` → continue to Step 2.

Remember the parsed fields (`stage`, `depth`, `branch`, `pr`, `parent`, `children`) for the rest of this file.

### Step 2: Report status to user

```
Issue #$1
Current stage: <stage>
Depth: <depth>
Branch: <branch|none>
PR: <pr|none>
<if parent>Children: <children-list></if>
```

## Dispatch

Based on `stage` from BOOTSTRAP:

### `done`
Report: "Issue is already complete." Stop.

### `implement-parent` (parent paused at sdd:implement)
1. For each child Issue number in the `children` field, check its current label:
   ```bash
   gh issue view <child-N> --json labels --jq '[.labels[].name]'
   ```
2. Report progress to user:
   ```
   Child Issues:
   - #<N>: → sdd:<stage>
   ...
   ```
3. **If all children are `sdd:done`**:
   - Update parent label:
     ```bash
     gh issue edit $1 --remove-label "sdd:implement" --add-label "sdd:test"
     ```
   - **Read + execute inline**: read `<<SKILL_DIR>>/commands/test.md` and execute its instructions for Issue #$1 in this main session. The test orchestrator handles the parent path internally.
4. **If any child is incomplete**:
   - Check skip-review setting (Common Definitions → Skip Review Setting in `SKILL.md`).
   - If skip-review contains any of `analyze`, `design`, `implement`, `pr` → **stop here** without asking. Report pending children. The surrounding flow (`/sdd batch` or `/sdd auto`) queues pending children.
   - Otherwise → ask user which child to resume; then **read + execute inline**: read `<<SKILL_DIR>>/commands/resume.md` and execute for the chosen child Issue.

### `analyze` / `design` / `implement` / `test` (single or child Issue)

Apply skip-review handling (Common Definitions → Skip Review Setting):
- If the stage's skip-review key (`analyze` / `design` / `implement`) is set in `.github/.sdd-config` → skip user confirmation; immediately dispatch.
- Otherwise → ask user "Resume from <stage>? [y/N]". On rejection → stop.

Then dispatch by reading + executing the appropriate orchestrator inline:
- `analyze` → `<<SKILL_DIR>>/commands/analyze.md`
- `design` → `<<SKILL_DIR>>/commands/design.md`
- `implement` → `<<SKILL_DIR>>/commands/implement.md`
- `test` → `<<SKILL_DIR>>/commands/test.md`

The target wrapper handles its Phase 0 depth detection + direct-invocation label check (T1.11), then spawns the single `stage_<X>` sub-agent that runs work + reviews + escalation internally. Sub-agent-level duplicate prevention ensures comments are updated in place if the stage was partially complete.

## Notes

- **resume.md is a thin dispatcher.** It spawns bootstrap (1 sub-agent call) and then inline-reads the target wrapper command, which spawns one `stage_<X>` sub-agent.
- **Idempotent re-entry.** Multiple `/sdd resume <N>` calls produce the same dispatch decision based on the current GitHub state.
- **Safe within `/sdd auto` loops.** Bootstrap is a leaf sub-agent; each stage wrapper spawns exactly one stage sub-agent (single-level spawn rule preserved).
- **Main-session token impact**: bootstrap moves the ~100 lines of label/comment/PR inspection out of main session into its own sub-agent context. Wrapper inline reads are ~100-200 lines each but only one stage runs per resume call.
