# IMPLEMENT

**Stage 3: Implementation (TDD: Red → Green → Refactor → E2E → PR Final) — thin wrapper.**

Arch B (v1.0.0): this file runs in the **main session** and spawns ONE `stage_implement` sub-agent that does all the work (plan + TDD pipeline with per-step reviewers + PR creation with R8 auto-route + 3-round PR Final review loop + escalation + Phase 7 child completion). Main session parses the sub-agent's `>>> RESULT <<<` line and handles label transitions + user prompts.

The `stage_implement` body is split across four files for readability (per SYNTHESIS-v2 T1.3); all four execute inside the single sub-agent context — the spawn reads `commands/atoms/stage_implement/main.md`, which Reads `_tdd.md`, `_pr_final.md`, `_phase7.md` at the appropriate phases.

> **Bash Command Execution**: see `<<SKILL_DIR>>/commands/atoms/_bash_rules.md`.

## Rules
- Do NOT set Claude as co-author in git commits.
- Check existing git history for branch naming and commit message conventions, and follow the same format.

## Input Validation

Validate `$1` per Common Definitions → Issue Validation in `<<SKILL_DIR>>/SKILL.md`. If `$1` is a Pull Request, stop without making changes.

## Direct-invocation label check (per `design/01-sub-agent-contract.md` §11)

For direct `/sdd implement <N>` invocation (not via `/sdd resume` / `/sdd auto` / `/sdd batch`), verify the Issue's current SDD lifecycle label matches this stage. Read labels:

```bash
gh issue view $1 --json labels --jq '[.labels[].name]'
```

- Labels contain no `sdd:*` lifecycle label OR contain `sdd:implement` → continue.
- Labels contain `sdd:analyze` → refuse (analyze hasn't finished):
  > Issue #$1 is currently at `sdd:analyze`. Run `/sdd analyze $1` first, or `/sdd resume $1`.

  Stop without making changes.
- Labels contain `sdd:design` → refuse (design hasn't finished):
  > Issue #$1 is currently at `sdd:design`. Run `/sdd design $1` first, or `/sdd resume $1`.

  Stop without making changes.
- Labels contain `sdd:test` / `sdd:done` → refuse:
  > Issue #$1 is currently at `sdd:<current>`. Use `/sdd resume $1` for correct stage dispatch.

  Stop without making changes.

(When this file is read-and-executed inline from `/sdd resume` or from design.md's skip-review.implement auto-advance, bootstrap / the prior stage has already validated the stage — but the label check above is idempotent and cheap, so it stays.)

## Precondition check (defense in depth)

Confirm the design output exists on the Issue before spawning the sub-agent (`stage_implement` also checks at `main.md` §2, but failing fast here avoids a wasted Agent spawn):

```bash
gh repo view --json nameWithOwner -q .nameWithOwner
```

Observe `<owner>/<repo>`. Then:

```bash
gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | select(.body | contains("<!-- sdd:design:output -->")) | .id'
```

If empty → report "Run `/sdd design $1` first, or `/sdd resume $1`." Stop.

## Phase 0: Depth detection (for sub-agent prompt)

From the same labels read in the direct-invocation check, derive the depth dial:
- Contains `sdd:review:deep` → `depth = deep`
- Contains `sdd:review:shallow` → `depth = shallow`
- Otherwise → `depth = default`

## Phase 1: Spawn stage_implement

Spawn ONE sub-agent via the Agent tool:

- `subagent_type`: `general-purpose`
- `model`: `opus` (the stage's plan + TDD + PR Final reviewer logic all run inside this single sub-agent context; `_pr_final.md` MAY invoke `/code-review` / `/security-review` Skills inside this context per Common Contracts §13)
- `description`: `stage_implement for #$1`
- `prompt`:
  > Read `<<SKILL_DIR>>/commands/atoms/stage_implement/main.md` and execute its instructions for Issue #$1.
  >
  > Inputs:
  >   Issue: #$1
  >   Depth: <dial>      (substitute the literal value from Phase 0: `default` / `deep` / `shallow`)
  >   Resume: none
  >   Branch: null
  >   PR: null
  >
  > Return EXACTLY one line per the contract in `stage_implement/main.md` §9, prefixed by the `>>> RESULT <<<` marker line.

(Substitute `<dial>` with the literal Phase 0 value. Do NOT pass through the literal placeholder.)

## Phase 2: Parse sub-agent return

Parse the `>>> RESULT <<<` line. Branch on status:

### `OK ADVANCE: test PR: #N BRANCH: <name>` (or with trailing ` E2E_SKIPPED`)

The sub-agent has created/updated the PR, run PR Final reviews to PASS, and is ready to hand off to stage_test. The `E2E_SKIPPED` suffix (if present) is a flag for stage_test (it may install an E2E framework with user confirmation).

1. Update label:
   ```bash
   gh issue edit $1 --remove-label "sdd:implement" --add-label "sdd:test"
   ```
   (If the Issue had no `sdd:implement` label yet — fresh entry via design's `skip-review.implement` auto-advance — the `--remove-label` is a no-op; that's fine.)

2. Check skip-review setting (Common Definitions → Skip Review Setting in `SKILL.md`). Read `.github/.sdd-config` and parse the `skip-review:` line.

3. If `qa` is in skip-review:
   - **Read + execute inline** (do NOT spawn a sub-agent here — `test.md` itself spawns `stage_test`, which would be nested): read `<<SKILL_DIR>>/commands/test.md` and execute its instructions for Issue #$1 in this same main session. Forward the `BRANCH: <name>` and `PR: #N` (and `E2E_SKIPPED` flag if present) so the test stage has the context.

4. If `qa` is NOT in skip-review:
   - Summarize for the user: PR URL (#N), branch name, E2E status (`E2E_SKIPPED` flag if present), reviewer verdicts.
   - Report: "Implement complete. Run `/sdd test $1` to continue, or `/sdd resume $1`."
   - Stop.

### `OK PARENT_STOP`

Sub-agent detected this Issue is a parent (has children). No stage work performed on the parent. Children take over.

1. Log: "Parent stopped at `sdd:implement`; outer flow queues children."
2. Branch on context:
   - **`/sdd auto` / `/sdd batch` context** (skip-review.implement set): stop here without further action. The outer auto-discovery / batch loop picks up the children via `<!-- sdd:children:output -->` lookup.
   - **Interactive context** (no skip-review.implement): list the parent's children and their current labels. Ask the user via `AskUserQuestion` which child to work on next.
     - **On selection**: **read + execute inline** (do NOT spawn a sub-agent — `resume.md` itself dispatches per child's label, and would spawn a stage sub-agent which would be nested): read `<<SKILL_DIR>>/commands/resume.md` and execute its instructions for the selected child Issue `#<child>` in this same main session. The resume dispatcher routes to the correct stage.
     - **On Skip**: report "Resume any child later with `/sdd resume #<child>`." Stop.

### `OK PAUSE`

(Returned by Phase 7 child completion path, or by Phase 5.5 ESCALATE → user Pause cycle.) Report to user:
> Paused. Resume with `/sdd resume $1`.

Stop.

### `ESCALATE: <summary>`

Round 3 PR Final FAIL with `skip-review: pr` OFF.

#### Batch + ESCALATE conversion (T1.8)

In batch mode (`claude -p` subprocess context — detected by `.github/.sdd-config` `skip-review:` containing `pr`), the main session cannot ask the user. Per SYNTHESIS-v2 T1.8 + `design/03-flow-design.md` §7.3, convert `ESCALATE` to a clean `OK PAUSE`-equivalent exit. Findings remain on the PR for human follow-up.

Detection: if `skip-review:` contains `pr` — we are in unattended mode. (This is a heuristic — strict detection would inspect process tree for `claude -p`; the skip-review.pr heuristic is the documented signal per T1.8 because batch mode always sets it.)

- **Batch mode detected** (skip-review.pr set yet we received ESCALATE — defensive; ESCALATE should not normally fire when skip-review.pr is set, but if it does because of a configuration mismatch):
  - Log: "ESCALATE received under batch mode (skip-review.pr set); converting to PAUSE per T1.8. Findings remain on the PR."
  - Report: "Paused. Resume with `/sdd resume $1` from an interactive session."
  - Stop (clean exit, no AskUserQuestion).

- **Interactive mode** (no skip-review.pr):
  1. Render `<summary>` verbatim to the user. (The summary includes counts of critical/major findings + role labels + PR/branch references.)
  2. Call `AskUserQuestion` with 3 options: `Continue`, `Pause`, `Stop`.
  3. Branch on user choice:
     - **Continue** → re-spawn `stage_implement` with `Resume: continue-after-escalation`:
       - `subagent_type`: `general-purpose`, `model`: `opus`, `description`: `stage_implement resume for #$1`
       - `prompt`:
         > Read `<<SKILL_DIR>>/commands/atoms/stage_implement/main.md` and execute its instructions for Issue #$1.
         >
         > Inputs:
         >   Issue: #$1
         >   Depth: <dial>
         >   Resume: continue-after-escalation
         >   Branch: null
         >   PR: null
         >
         > Return EXACTLY one line per the contract, prefixed by `>>> RESULT <<<`.
       - Parse the re-spawn's return (should be `OK ADVANCE: test PR: #N BRANCH: <name>` with or without `E2E_SKIPPED`, or `FAIL:`). Loop into the corresponding branch above. If `OK ADVANCE: ...`, handle the label + skip-review.qa steps again. **Note**: re-running the label transition is idempotent on a clean Issue, but if the user manually changed labels between escalate and resume, the `--remove-label "sdd:implement"` is a no-op and `--add-label "sdd:test"` overwrites the user's manipulation — this is intentional (the resume continues the SDD flow).
     - **Pause** → report "Resume later with `/sdd resume $1`. Findings remain on the PR for review." Stop.
     - **Stop** → exit cleanly.

### `FAIL: <reason>`

Parse `<reason>` for an optional subtype prefix (`<subtype>: <detail>`) per `spec/00-common-contracts.md` §6 "FAIL reason prefix convention". Branch:

- **`no-action: <detail>`** — design specifies zero `lib/` code changes (operational / documentation-only workflow); implement's TDD pipeline cannot produce a Red signal. Render:
  > Issue #$1 implement no-action: `<detail>`.
  > Implement stage cannot produce a PR for a zero-code-change design. Close-as-not-planned recommended:
  > ```bash
  > gh issue edit $1 --remove-label "sdd:implement" --add-label "sdd:done"
  > gh issue close $1 --reason "not planned" --comment "<detail>"
  > ```
  > Analyze / design comments remain on the Issue for reference (e.g. operational thresholds, observation procedure, DoD).

  Stop without changing labels.

- **`gate-pending: <ISO-8601-date>: <detail>`** — a measurement / time gate has not been reached; implement's first-step gate evaluation cannot decide between branches. Render:
  > Issue #$1 implement gate-pending: `<detail>`.
  > Earliest resume date: `<ISO-8601-date>`. After that date, post the required measurement data as a comment on Issue #$1, then run `/sdd resume $1`.
  > Label remains at `sdd:implement` so resume picks up correctly.

  Stop without changing labels.

  (Interactive context: MAY additionally offer `/schedule /sdd resume $1` for `<ISO-8601-date>` via `AskUserQuestion`. Under `/sdd auto` / `/sdd batch`, do NOT prompt — the outer loop continues to the next Issue.)

- **`precondition-missing: <detail>`** — required prior-stage artifact (e.g. design output) absent. Render:
  > Issue #$1 implement precondition missing: `<detail>`.
  > Run `/sdd design $1` first, or `/sdd resume $1`.

  Stop.

- **No recognized prefix** — render `<reason>` verbatim to the user. Stop.

### Unknown / malformed

> **CRITICAL — MAIN SESSION INVARIANT (do not skip):** When the sub-agent's return text does not contain a parseable `>>> RESULT <<<` line, the main session **MUST** execute the auto-recovery probe below **before** spawning any new agent and **before** reporting failure. Do NOT shortcut by re-spawning `stage_implement` with `Resume: continue-after-escalation`, do NOT manually craft finalize agents — the auto-recovery probe IS the contract-restoration path. Skipping it leads to duplicate work, malformed PR markers, and (in `/sdd auto`) wrong queue accounting.

Defensive auto-recovery for sub-agent contract-line drop (`design/01-sub-agent-contract.md` §9):

The sub-agent's `>>> RESULT <<<` line is absent or unparseable. Before failing outright, **probe GitHub state** to see if the sub-agent completed all substantive work but silently dropped the closing contract line — this pattern was observed when the heavy PR Final reviewer + Skill chain consumed the sub-agent's remaining output budget after `/security-review` or after a verdict was implicitly reached.

1. Resolve `<owner>/<repo>` per Common Contracts §11.
2. Find the PR for this Issue:
   ```bash
   gh pr list --search "Refs #$1" --state open --json number,headRefName --jq '.[] | {number, headRefName}'
   ```
   - If empty → fall through to step 6 (no PR exists; cannot recover; fail).
   - Else → observe `<PR_NUM>` and `<branch_name>`.
3. Check whether all three SDD PR Final reviewer comments exist on the PR AND each `verdict` is `PASS`:
   ```bash
   gh api repos/<owner>/<repo>/issues/<PR_NUM>/comments --jq '[.[] | select(.body | contains("<!-- sdd:review:implement:completeness -->") or contains("<!-- sdd:review:implement:quality -->") or contains("<!-- sdd:review:implement:adversarial -->"))] | length'
   ```
   - Result < 3 → not all reviewers completed; fall through to step 6.
   - Result == 3 → re-fetch each comment body and verify the verdict line (`**Verdict:** PASS`) for all three. If any FAIL → fall through to step 6.
4. Check whether the tools-summary marker is present:
   ```bash
   gh api repos/<owner>/<repo>/issues/<PR_NUM>/comments --jq '.[] | select(.body | contains("<!-- sdd:review:implement:tools -->")) | .id'
   ```
   - Present → skip step 5a.
   - Absent → step 5a: post a minimal tools-summary marker per `commands/atoms/stage_implement/_pr_final.md` §4.6 template. Use the comment-posting pattern (Section F.2). Fields:
     - `round`: 1 (auto-recovery assumes the absence of a prior tools marker means round 1)
     - `/code-review`: `ran (effort: <high|max|medium>)` derived from depth dial, OR `skipped (skill-unavailable)` if not detectable. Counts default to `0 / 0 / 0` — auto-recovery cannot reconstruct Skill counts; the marker is informational only and verdict is unaffected (Common Contracts §6 + `_pr_final.md` §4.7 explicitly state Skill counts are informational).
     - `/security-review`: same pattern; `0 / 0 / 0`.
5. Log to the user:
   > ⚠ Sub-agent dropped the `>>> RESULT <<<` contract line, but PR Final reviewers all PASSed on PR #<PR_NUM>. Main session auto-recovered: posted tools-summary marker (if missing) and is treating this as `OK ADVANCE: test PR: #<PR_NUM> BRANCH: <branch_name>`. Continue to label transition + test stage.
   
   Then proceed exactly as the `OK ADVANCE: test PR: #N BRANCH: <name>` branch above (label transition + skip-review.qa chain).
6. **Fall-through**: report
   > FAIL: unexpected return from stage_implement (auto-recovery probed PR state and could not confirm successful PR Final completion): `<line>`.
   
   Stop. (Defensive per `design/01-sub-agent-contract.md` §9 — equivalent to legacy behavior.)

## Notes

- **AI review always runs.** `skip-review: pr` skips only the user-facing confirmation gate (Phase 5.5) — `stage_implement` always executes the 3-round PR Final review loop internally (`/code-review` and `/security-review` Skills inclusive). On Round 3 FAIL, `skip-review: pr` auto-continues (sub-agent returns `OK ADVANCE` instead of `ESCALATE`). Findings remain on the PR for human follow-up.
- **`skip-review: implement` is consumed by the sub-agent**, NOT this wrapper:
  - Phase 1 parent-stop (suppresses interactive child-pick prompt; outer auto-discovery handles).
  - Phase 3 step exhaustion (auto-continue with logged warning per Arch B Option 2 — `design/stage-designs/implement.md` §10.7; behavior shift documented in `spec/stage/implement.md` §20.5).
- **`skip-review: qa` is consumed by THIS wrapper** (not the sub-agent) — see `OK ADVANCE` branch above.
- **Single sub-agent spawn per invocation** (or two, if a `continue-after-escalation` resume is needed). All plan + TDD + PR creation + PR Final reviewers + retry loops + Phase 7 logic lives inside `stage_implement/{main,_tdd,_pr_final,_phase7}.md` — main session stays thin.
- **Reviewers run serially inside the sub-agent.** Reviewer independence is preserved by the sub-agent's internal narrative structure (PR diff is shared ground truth from §4.3.a.2 — no re-fetch; no cross-visibility of verdicts). TDD step reviews are NOT subject to the independence invariant — they are step-scoped and may cross-reference prior step's evidence (the Refactor reviewer reads step-2's review for count-drift detection).
- **Skills run INSIDE the sub-agent.** `_pr_final.md` invokes `/code-review` and `/security-review` per `spec/edge-cases.md` §12 + Common Contracts §13. Graceful skip on `skill-unavailable` / `skill-errored` / shallow-skip — recorded in the `<!-- sdd:review:implement:tools -->` marker for audit.
- **Skill ordering preserved.** Sub-agent enforces serial ordering `5.N.1.a (completeness) → 5.N.1.b (quality) → 5.N.1.c (adversarial) → 5.N.2 (/code-review) → 5.N.3 (/security-review) → 5.N.4 (tools-summary) → 5.N.5 (verdict)` per `spec/edge-cases.md` §24 + `design/stage-designs/implement.md` §13.1. This is sub-agent convention (Skill+Agent batching is moot inside a single sub-agent), preserved for verdict determinism + token economy.
- **R8 (existing PR auto-route) is always on.** Per SYNTHESIS-v2 T1.1 there is no `strict-pr-creation` config key. Resume re-entering implement with an existing OPEN PR on the branch is routed to soft retry (PR Final round 1 against the existing PR). Users wanting strict behavior must `gh pr close` manually before re-running. Defensive guard: existing PR body must contain `Refs #$1` or the sub-agent FAILs.
- **R9 (TDD step idempotency) is sha-based**. Per SYNTHESIS-v2 T1.2 the canonical mechanism is the `<!-- sdd:test-evidence:step-<n> -->` marker's `Commit:` field + `git merge-base --is-ancestor` + commit-subject heuristic. No commit-body marker. 0.x branches resume cleanly without retroactive marking.
- **Label transitions are main session's responsibility.** `stage_implement` never sets labels itself.
- **Phase 7 (child completion notification) re-enters via main session.** When a child Issue reaches `sdd:done` (via stage_test closing the Issue), the main session's bootstrap / dispatcher detects the transition and routes back into `stage_implement` with `Resume: phase-7`. This is NOT a fresh implement; it only updates the parent's children comment + optionally posts a completion notification. The sub-agent returns `OK PAUSE` and this wrapper exits.
- **No force-push, no `git commit --amend`** — retry mode appends new fix-up commits to preserve PR review history (`spec/edge-cases.md` §23).
- **Depth label override**: `sdd:review:deep` / `sdd:review:shallow` selects the depth dial, which the sub-agent uses for `/code-review --effort` (default=high / deep=max / shallow=medium) and to shallow-skip `/security-review`. Per-reviewer model dial is informational only inside the sub-agent (single sub-agent context runs at one model — typically `opus`).
- **3-round PR Final budget, per-step 2-retry budget (3 attempts) for TDD steps** per `spec/edge-cases.md` §22.
- **FAIL reason subtype convention (additive)** — `stage_implement` MAY prefix its FAIL reason with `no-action: `, `gate-pending: <date>: `, or `precondition-missing: ` per `spec/00-common-contracts.md` §6. This wrapper renders subtype-specific user guidance (close-as-not-planned command, resume-after-date hint, etc.) instead of an opaque error string. Legacy unstructured FAIL reasons still render verbatim.
- **Auto-recovery on contract-line drop (additive)** — if the sub-agent's `>>> RESULT <<<` line is absent / malformed, the wrapper probes GitHub state (PR existence + 3 PR Final reviewer PASS verdicts) and synthesizes the missing tools-summary marker + treats as `OK ADVANCE: test` when the probe succeeds. Falls through to legacy `FAIL: unexpected return` behavior when the probe fails. Mitigates the **B1 pattern** (`spec/edge-cases.md` §25) — sub-agent's `stop_reason=end_turn` after Skill output, empirically observed 7/7 times under both natural and prompt-guard-augmented conditions. Auto-recovery is the sole effective mitigation in v1.1.0; expected to activate near-100% for PR Final.
