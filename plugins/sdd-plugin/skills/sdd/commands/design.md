# DESIGN

**Stage 2: Design (How) — thin wrapper.**

Arch B (v1.0.0): this file runs in the **main session** and spawns ONE `stage_design` sub-agent that does all the work (design body + child Issue creation + 3 reviewers serial + retry loop + escalation). Main session parses the sub-agent's `>>> RESULT <<<` line and handles label transitions + user prompts.

Define HOW based on the analyze stage's What/Why output. Two output paths: SINGLE-PR or CHILDREN (multi-PR with child Issues, parent paused).

> **Bash Command Execution**: see `<<SKILL_DIR>>/commands/atoms/_bash_rules.md`.

## Input Validation

Validate `$1` per Common Definitions → Issue Validation in `<<SKILL_DIR>>/SKILL.md`. If `$1` is a Pull Request, stop without making changes.

## Direct-invocation label check (per `design/01-sub-agent-contract.md` §11)

For direct `/sdd design <N>` invocation (not via `/sdd resume` / `/sdd auto` / `/sdd batch`), verify the Issue's current SDD lifecycle label matches this stage. Read labels:

```bash
gh issue view $1 --json labels --jq '[.labels[].name]'
```

- Labels contain no `sdd:*` lifecycle label OR contain `sdd:design` → continue.
- Labels contain `sdd:analyze` → refuse (analyze hasn't finished):
  > Issue #$1 is currently at `sdd:analyze`. Run `/sdd analyze $1` first, or `/sdd resume $1`.

  Stop without making changes.
- Labels contain `sdd:implement` / `sdd:test` / `sdd:done` → refuse:
  > Issue #$1 is currently at `sdd:<current>`. Use `/sdd resume $1` for correct stage dispatch.

  Stop without making changes.

(When this file is read-and-executed inline from `/sdd resume` or from analyze.md's skip-review.design auto-advance, bootstrap / the prior stage has already validated the stage — but the label check above is idempotent and cheap, so it stays.)

## Precondition check (defense in depth)

Confirm the analyze output exists on the Issue before spawning the sub-agent (`stage_design` also checks, but failing fast here avoids a wasted Agent spawn):

```bash
gh repo view --json nameWithOwner -q .nameWithOwner
```

Observe `<owner>/<repo>`. Then:

```bash
gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | select(.body | contains("<!-- sdd:analyze:output -->")) | .id'
```

If empty → report "Run `/sdd analyze $1` first." Stop.

## Phase 0: Depth detection (for sub-agent prompt)

From the same labels read in the direct-invocation check, derive the depth dial:
- Contains `sdd:review:deep` → `depth = deep`
- Contains `sdd:review:shallow` → `depth = shallow`
- Otherwise → `depth = default`

## Phase 1: Spawn stage_design

Spawn ONE sub-agent via the Agent tool:

- `subagent_type`: `general-purpose`
- `model`: `fable` when `depth = deep` (from Phase 0), otherwise `opus`. The whole stage (design work + inlined reviewers) runs in this one sub-agent; design has no in-context `/security-review` / `/code-review`, so `fable` at the deep dial is safe and raises design + review reasoning quality (per `_review_helpers.md` Section A.2.1). If this build's Agent tool rejects `fable`, fall back to `opus`.
- `description`: `stage_design for #$1`
- `prompt`:
  > Read `<<SKILL_DIR>>/commands/atoms/stage_design.md` and execute its instructions for Issue #$1.
  >
  > Inputs:
  >   Issue: #$1
  >   Depth: <dial>      (substitute the literal value from Phase 0: `default` / `deep` / `shallow`)
  >   Resume: none
  >
  > Return EXACTLY one line per the contract in stage_design.md, prefixed by the `>>> RESULT <<<` marker line.

(Substitute `<dial>` with the literal Phase 0 value. Do NOT pass through the literal placeholder.)

## Phase 2: Parse sub-agent return

Parse the `>>> RESULT <<<` line. Branch on status:

### `OK ADVANCE: implement SINGLE`
1. Update label:
   ```bash
   gh issue edit $1 --remove-label "sdd:design" --add-label "sdd:implement"
   ```
   (If the Issue had no `sdd:design` label yet — fresh entry via analyze auto-advance — the `--remove-label` is a no-op; that's fine.)
2. Check skip-review setting (Common Definitions → Skip Review Setting in `SKILL.md`). Read `.github/.sdd-config` and parse the `skip-review:` line.
3. If `implement` is in skip-review:
   - **Read + execute inline** (do NOT spawn a sub-agent here — `implement.md` itself spawns `stage_implement`, which would be nested): read `<<SKILL_DIR>>/commands/implement.md` and execute its instructions for Issue #$1 in this same main session.
4. If `implement` is NOT in skip-review:
   - Summarize for the user: design comment location, PR split = SINGLE.
   - Ask for confirmation on technical approach and PR split.
   - On approval: report "Run `/sdd implement $1` to continue, or `/sdd resume $1`." Stop.

### `OK ADVANCE: implement CHILDREN: #A,#B,#C`
The sub-agent has already posted the design output, created the child Issues with `sdd:analyze` + `sdd:child` labels, and posted the `<!-- sdd:children:output -->` comment on the parent.

1. Update parent label (parent reaches `sdd:implement` but pauses there — parent-pause invariant per Common Contracts §1):
   ```bash
   gh issue edit $1 --remove-label "sdd:design" --add-label "sdd:implement"
   ```
2. Check skip-review setting.
3. If `design` is in skip-review (e.g. running under `/sdd auto` or `/sdd batch`):
   - **Stop here.** Parent is at `sdd:implement` (paused). Children are at `sdd:analyze` + `sdd:child`. The surrounding flow (`/sdd auto` or `/sdd batch`) picks up the children.
   - Log: "Children created (#A, #B, ...). Parent stopped at sdd:implement for batch/orchestrator to queue children."
4. If `design` is NOT in skip-review (interactive mode):
   - Summarize: design posted, children `#A`, `#B`, ... created, parent now at `sdd:implement` (paused).
   - Ask the user (`AskUserQuestion`): "Which child Issue would you like to start with?" (Options: each child number, plus a Skip option to defer.)
   - On selection: **read + execute inline** (do NOT spawn a sub-agent — `analyze.md` itself spawns `stage_analyze`, which would be nested): read `<<SKILL_DIR>>/commands/analyze.md` and execute its instructions for the selected child Issue `#<child>` in this same main session.
   - On Skip: report "Resume any child later with `/sdd analyze #<child>` or `/sdd resume #<child>`." Stop.

### `OK PAUSE`
Report to user: "Paused. Resume with `/sdd resume $1`." Stop.

### `ESCALATE: <summary>`
1. Render `<summary>` verbatim to the user.
2. Call `AskUserQuestion` with 3 options: `Continue`, `Pause`, `Stop`.
3. Branch on user choice:
   - **Continue** → re-spawn `stage_design` with `Resume: continue-after-escalation`:
     - `subagent_type`: `general-purpose`, `model`: `fable` when `depth = deep` else `opus` (same rule as Phase 1), `description`: `stage_design resume for #$1`
     - `prompt`:
       > Read `<<SKILL_DIR>>/commands/atoms/stage_design.md` and execute its instructions for Issue #$1.
       >
       > Inputs:
       >   Issue: #$1
       >   Depth: <dial>
       >   Resume: continue-after-escalation
       >
       > Return EXACTLY one line per the contract, prefixed by `>>> RESULT <<<`.
     - Parse the re-spawn's return (should be `OK ADVANCE: implement SINGLE`, `OK ADVANCE: implement CHILDREN: #A,#B,#C`, or `FAIL:`). Loop into the corresponding branch above. If `OK ADVANCE: ...`, handle the label + skip-review steps again. **Note**: re-running the label transition is idempotent on a clean Issue, but if the user manually changed labels between escalate and resume, the `--remove-label "sdd:design"` is a no-op and `--add-label "sdd:implement"` overwrites the user's manipulation — this is intentional (the resume continues the SDD flow).
   - **Pause** → report "Resume later with `/sdd resume $1`." Stop.
   - **Stop** → exit cleanly.

### `FAIL: <reason>`

Parse `<reason>` for an optional subtype prefix (`<subtype>: <detail>`) per `spec/00-common-contracts.md` §6 "FAIL reason prefix convention". Branch:

- **`no-action: <detail>`** — design concluded the requested change is not warranted. Render:
  > Issue #$1 design concluded no-action: `<detail>`.
  > Close-as-not-planned recommended:
  > ```bash
  > gh issue edit $1 --remove-label "sdd:design" --add-label "sdd:done"
  > gh issue close $1 --reason "not planned" --comment "<detail>"
  > ```
  > Design comment remains on the Issue for reference.

  Stop without changing labels.

- **`precondition-missing: <detail>`** — required `<!-- sdd:analyze:output -->` absent. Render:
  > Issue #$1 design precondition missing: `<detail>`.
  > Run `/sdd analyze $1` first, or `/sdd resume $1`.

  Stop.

- **No recognized prefix** — render `<reason>` verbatim to the user. Stop.

### Unknown / malformed
Treat as `FAIL: unexpected return: <line>` and stop. (Defensive per `design/01-sub-agent-contract.md` §9.)

## Notes

- **AI review always runs.** `skip-review: design` skips only the user confirmation between stages — `stage_design` always executes Phases 1-4 internally. The Phase 5 escalation gate (inside the sub-agent) still triggers on Round 3 FAIL, but skip-review auto-continues it (sub-agent returns `OK ADVANCE: implement <path>` instead of `ESCALATE`). Findings remain on the Issue for human follow-up.
- **Single sub-agent spawn per invocation** (or two, if a `continue-after-escalation` resume is needed). All reviewer + retry loop logic, plus SINGLE/CHILDREN decision + child Issue creation + children-list comment, lives inside `stage_design.md` — main session stays thin.
- **Reviewers run serially inside the sub-agent.** Reviewer independence is preserved by the sub-agent's internal narrative structure (re-fetch the design output for each reviewer; no cross-visibility of verdicts).
- **Label transitions are main session's responsibility.** `stage_design` never sets parent labels itself. Children's `sdd:analyze` + `sdd:child` labels are applied at `gh issue create --label` time inside the sub-agent — that is NOT a parent-label transition.
- **Children idempotency is load-bearing.** If the sub-agent is re-invoked (retry rounds, or `continue-after-escalation` resume), child Issues are NOT re-created — the existing children-list comment is detected via `<!-- sdd:children:output -->` and preserved (`spec/stage/design.md` §5 / §8).
- **Parent pauses at `sdd:implement` on CHILDREN path.** Parent does NOT advance through implement/test by itself. It waits until all children reach `sdd:done`, then the test stage's parent-integration logic advances it (Common Contracts §1 parent-pause invariant).
- **Depth label override**: `sdd:review:deep` / `sdd:review:shallow` selects the depth dial. At `depth = deep` the wrapper spawns `stage_design` with `model: fable` (the design stage has no in-context security analysis; per `_review_helpers.md` Section A.2.1) — falling back to `opus` if the Agent tool rejects `fable`. All other depths spawn `opus`. The depth dial also informs the sub-agent's reasoning style per `_review_helpers.md` Section A.2.
