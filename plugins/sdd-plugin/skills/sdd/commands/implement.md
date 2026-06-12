# IMPLEMENT

**Stage 3: Implementation — TDD Cycle (Red → Green → Refactor → E2E → PR) — Orchestrator**

> **Bash Command Execution**: every shell snippet below is its own simple Bash tool call — no `&&`, `||`, `;`, `|`, `2>/dev/null`, `2>&1`, `>file`, `$(...)`, `VAR=$(...)`, or heredocs. For codebase exploration use the **Grep / Glob / Read** tools — do NOT use Bash `find` against `/`, `~`, `/Users`, or any path outside the repo root. See **Bash Command Execution Rules** in `<<SKILL_DIR>>/SKILL.md`.

## Rules
- Do NOT set Claude as co-author in git commits.
- Check existing git history for branch naming and commit message conventions, and follow the same format.

This file is an **orchestrator**. It runs in the main session and composes atomic operations via the Agent tool. The atoms (`atoms/implement_plan.md`, `atoms/implement_red.md`, `atoms/implement_green.md`, `atoms/implement_refactor.md`, `atoms/implement_e2e.md`, `atoms/implement_pr.md`, `atoms/tdd_step_review.md`, `atoms/implement_review.md`, `atoms/implement_adversarial.md`) do the actual work; this file manages state, sequencing, and user interaction.

## Input Validation

Before any other step: validate `$1` per Common Definitions → Issue Validation in `<<SKILL_DIR>>/SKILL.md`. If `$1` is a Pull Request, stop without making changes.

## Phase 0: Depth label detection

Per `<<SKILL_DIR>>/commands/atoms/_review_helpers.md` Section C:

```bash
gh issue view $1 --json labels --jq '[.labels[].name]'
```

Determine depth (`default` / `deep` / `shallow`).

**Model resolution for implement stage**:

| Atom | default | deep | shallow |
|---|---|---|---|
| `implement_plan` | opus | opus | opus |
| `implement_red` / `green` / `refactor` / `e2e` / `pr` | opus | opus | opus |
| `tdd_step_review` (step 1, 4) | sonnet | opus | haiku |
| `tdd_step_review` (step 2, 3) | haiku | opus | haiku |
| `implement_review` (PR Final completeness/quality) | sonnet | opus | sonnet |
| `implement_adversarial` (PR Final) | opus | opus | sonnet |

**`/code-review` effort by depth**: see `_review_helpers.md` Section A.3.

## Phase 1: Determine Issue type

1. Check if this Issue has child Issues:
   ```bash
   gh repo view --json nameWithOwner -q .nameWithOwner    # observe owner/repo; inline below
   gh api repos/<owner>/<repo>/issues/$1/comments \
     --jq '.[] | select(.body | contains("sdd:children:output")) | .body'
   ```
2. **Parent Issue (has children)**: Do NOT implement directly. Instead:
   - List child Issues and their current status (from `<!-- sdd:children:output -->` table + each child's actual label)
   - Check skip-review setting (Common Definitions → Skip Review Setting):
     - If `implement` is in skip-review (`/sdd auto` / `/sdd batch`): log "Parent has children; stopping for outer orchestrator to queue children." and stop **without asking**. The surrounding flow (`/sdd auto`'s child auto-discovery or `/sdd batch`) will pick up each child Issue.
     - Else (interactive mode): ask user which child Issue to work on. On selection (read + execute inline, do NOT spawn a subagent): read `<<SKILL_DIR>>/commands/resume.md` and execute its instructions for the selected child Issue in this same main session. The resume dispatcher routes to the correct stage orchestrator. Stop this orchestrator once the child is dispatched.
3. **Single Issue or Child Issue (no children)**: Proceed to Phase 2.

## Phase 2: Plan

### 2.1 — Spawn the plan atom

- `subagent_type`: `general-purpose`
- `model`: `opus`
- `description`: `implement plan for #$1`
- `prompt`:
  > Read `<<SKILL_DIR>>/commands/atoms/implement_plan.md` and execute its instructions for Issue #$1.
  > Return EXACTLY one line in the contract, prefixed by `>>> RESULT <<<`.

Parse the `>>> RESULT <<<` line:
- `FAIL: <reason>` → report failure, stop.
- `OK BRANCH: <branch-name>` → continue. Remember `<branch-name>` for later phases.

### 2.2 — Plan user confirmation

Check skip-review setting (Common Definitions → Skip Review Setting).
- If `implement` is in skip-review → log "User review skipped (skip-review: implement). Proceeding to TDD." → Phase 3.
- Otherwise → present the plan comment (`<!-- sdd:implement:plan -->` on the Issue) and ask the user to confirm. On approval → Phase 3. On rejection → stop.

## Phase 3: TDD step pipeline (Red → Green → Refactor → E2E)

For each step in this order: `red` (3-1) → `green` (3-2) → `refactor` (3-3) → `e2e` (3-4):

### 3.X — Per-step pipeline (X = 1, 2, 3, 4)

Up to **2 retries per step**. Each iteration:

1. **Spawn the step atom**:
   - `subagent_type`: `general-purpose`
   - `model`: `opus` (per Phase 0 table)
   - `description`: `implement step-X for #$1`
   - `prompt`:
     > Read `<<SKILL_DIR>>/commands/atoms/implement_<step>.md` and execute its instructions for Issue #$1 on branch `<branch-name>`.
     > <if retry: include `Previous step review findings — sorted by severity (critical → major → minor). Address every critical and major finding; read minor findings as supporting context. Do not skip minor findings tied to the same area: <inlined JSON array>`>
     > Return EXACTLY one line in the contract, prefixed by `>>> RESULT <<<`.

   Where `<step>` is one of: `red`, `green`, `refactor`, `e2e`.

   Parse the return:
   - `FAIL: <reason>` → report failure, stop.
   - `OK <STEP_TYPE> COMMIT: <sha> TESTS: <p>/<t> FAILED: <f>` → continue to step 2. Remember `<sha>` and the substring `TESTS: <p>/<t> FAILED: <f>` (call this `<test-evidence>`).
   - `OK REFACTOR EMPTY` → continue to step 2. `<sha>` = `EMPTY`, `<test-evidence>` = `NONE`.
   - `OK E2E_SKIPPED` → skip step 2 entirely (nothing committed, nothing to review).

2. **Spawn tdd_step_review**:
   - `subagent_type`: `general-purpose`
   - `model`: per Phase 0 table for this step
   - `description`: `tdd step-X review for #$1`
   - `prompt`:
     > Read `<<SKILL_DIR>>/commands/atoms/tdd_step_review.md` and execute its instructions for Issue #$1, step X, branch `<branch-name>`, commit `<sha>` (or `EMPTY`), test evidence `<test-evidence>` (or `NONE`).
     > Return EXACTLY one line in the contract, prefixed by `>>> RESULT <<<`.


   Parse:
   - `FAIL: <reason>` (atom error) → report, stop.
   - `OK PASS` → proceed to next step in the pipeline.
   - `OK FAIL: <summary>` → re-spawn this step's atom in retry mode with the structured findings as `$3`. Repeat up to 2 retries.

3. **Step exhaustion**: if the step's retry budget (2 retries) is consumed without PASS, **escalate**:
   - Post a comment to the Issue with the remaining critical/major findings (use the temp-file pattern per `_review_helpers.md` Section F).
   - Check skip-review setting (Common Definitions → Skip Review Setting):
     - If `implement` is in skip-review (`/sdd auto` / `/sdd batch`): log "⚠ TDD step-X (`<step>`) failed review 3 times. Auto-continuing to next step because `skip-review: implement` is set; unresolved findings carry forward to PR Final review." Proceed to the next step **without asking**.
     - Else (interactive mode):
       - Render to user: "⚠ TDD step-X (`<step>`) failed review 3 times for Issue #$1. Remaining findings: <list critical/major>. Continue to next step / Pause / Stop?"
       - On "Continue" → proceed to next step (carry forward the unresolved findings to PR Final review).
       - On "Pause" → stop orchestrator. User resumes via `/sdd resume <N>`.
       - On "Stop" → exit.

After all 4 steps complete (or were carried forward with user approval), proceed to Phase 4.

## Phase 4: PR creation (step 3-5)

### 4.1 — Spawn implement_pr atom (first-round mode)

- `subagent_type`: `general-purpose`
- `model`: `opus`
- `description`: `implement PR creation for #$1`
- `prompt`:
  > Read `<<SKILL_DIR>>/commands/atoms/implement_pr.md` and execute its instructions for Issue #$1 on branch `<branch-name>` (first-round mode, no `$3`).
  > Return EXACTLY one line in the contract, prefixed by `>>> RESULT <<<`.

Parse:
- `FAIL: <reason>` → report, stop.
- `OK PR: #N` → PR created. Remember `<PR_NUM>` = `#N`.
- `OK PR: #N E2E_SKIPPED` → same; note E2E was skipped.

## Phase 5: PR Final review loop (3 rounds + escalation)

Each round = 3 parallel SDD reviewers + `/code-review` invocation → verdict check.

### Round 1

#### 5.1.1 — Spawn the three SDD review atoms in parallel

Single message, three Agent tool calls (concurrent):

Agent A (completeness):
- `subagent_type`: `general-purpose`
- `model`: per Phase 0 table
- `description`: `implement review (completeness) for #$1`
- `prompt`:
  > Read `<<SKILL_DIR>>/commands/atoms/implement_review.md` and execute its instructions for Issue #$1 with role `completeness`.
  > Return EXACTLY one line in the contract, prefixed by `>>> RESULT <<<`.

Agent B (quality):
- `subagent_type`: `general-purpose`
- `model`: per Phase 0 table
- `description`: `implement review (quality) for #$1`
- `prompt`:
  > Read `<<SKILL_DIR>>/commands/atoms/implement_review.md` and execute its instructions for Issue #$1 with role `quality`.
  > Return EXACTLY one line in the contract, prefixed by `>>> RESULT <<<`.

Agent C (adversarial):
- `subagent_type`: `general-purpose`
- `model`: per Phase 0 table
- `description`: `implement adversarial for #$1`
- `prompt`:
  > Read `<<SKILL_DIR>>/commands/atoms/implement_adversarial.md` and execute its instructions for Issue #$1.
  > Return EXACTLY one line in the contract, prefixed by `>>> RESULT <<<`.

Parse all three:
- If any is `FAIL: <reason>` (atom error) → report, stop.
- Combine verdicts:
  - All three `OK PASS PR: #N` → SDD reviews passed. Proceed to 5.1.2.
  - Any `OK FAIL PR: #N: <summary>` → SDD reviews failed. Combine summaries.
  - **Adversarial single-FAIL escalation**: log to user if adversarial alone identified critical/major.

#### 5.1.2 — Invoke `/code-review` (after SDD reviewers complete)

The Skill tool invocation cannot be in the same parallel batch as Agent calls. Issue serially **after** Step 5.1.1's results are in.

Attempt to invoke `/code-review` via the Skill tool:
- Effort level: `high` (default), `max` (deep depth), `medium` (shallow depth)
- Arguments: `--comment`
- Target: the PR identified by `<PR_NUM>` (the Skill auto-detects the current PR from the branch; if it doesn't, pass `<PR_NUM>` as the target argument)

**Graceful skip**: if the Skill tool reports `/code-review` is unavailable (e.g., Claude Code v2.1.146 or earlier, Skill disabled), log a warning and skip. Do NOT fail the round on this.

Track outcome for the round-level tools summary (Step 5.1.4):
- Tool invoked successfully → add `"code-review"` to this round's `tools_run`.
- Tool unavailable → add `{"name": "code-review", "reason": "skill-unavailable"}` to this round's `tools_skipped`.

If invoked successfully, after `/code-review` completes:
- Read the PR comments via `gh api`:
  ```bash
  gh api repos/<owner>/<repo>/issues/<PR_NUM>/comments
  ```
- Count `/code-review` findings by severity:
  - 🔴 Important → counted as `critical`
  - 🟡 Nit → counted as `minor`
  - 🟣 Pre-existing → ignored
- Combine into SDD verdict:
  - If `/code-review` produced 1+ Important → treat as a FAIL (in addition to any SDD FAIL)
  - If only Nit → no effect on verdict
- **Verdict combination logic** (with `/code-review` only): if EITHER SDD reviewers FAILed OR `/code-review` produced Important findings → round = FAIL. If all three SDD reviewers PASSed AND `/code-review` found no Important → round = PASS.

#### 5.1.3 — Invoke `/security-review` (after `/code-review`)

Same Skill tool invocation pattern as 5.1.2. Issue serially after `/code-review` completes.

Attempt to invoke `/security-review` via the Skill tool:
- No effort argument (the Skill runs with its own internal effort calibration).
- Target: the current branch (the Skill auto-detects pending changes; if needed, pass `<PR_NUM>` explicitly).
- Output: the Skill posts inline PR comments on lines where it identifies security issues, and a summary block.

**Graceful skip**: if the Skill is unavailable, log a warning and proceed. Do NOT fail the round on this.

**Shallow label skip**: if `sdd:review:shallow` label is set on the Issue, skip `/security-review` to keep cost low.

Track outcome for the round-level tools summary (Step 5.1.4):
- Tool invoked successfully → add `"security-review"` to this round's `tools_run`.
- Tool unavailable → add `{"name": "security-review", "reason": "skill-unavailable"}` to this round's `tools_skipped`.
- Skipped due to shallow label → add `{"name": "security-review", "reason": "shallow-label-skip"}` to this round's `tools_skipped`.

After `/security-review` completes, read PR comments authored by the Skill:
- Each finding has a severity tag (security categories — typically High / Medium / Low or similar).
- Severity mapping:
  - High security findings → counted as `critical`
  - Medium → counted as `major`
  - Low / informational → counted as `minor`

**Verdict combination logic (final, with both Skills)**:
- Round = FAIL if ANY of these conditions: SDD reviewers FAILed, `/code-review` produced 🔴 Important, `/security-review` produced High or Medium.
- Round = PASS only if ALL of these: all 3 SDD reviewers PASSed, `/code-review` found no Important, `/security-review` found no High/Medium.

#### 5.1.4 — Post round-level tools summary comment

Before the round decision, post a structured summary to the PR recording which external Skills ran or were skipped this round. This makes graceful-skip observable — downstream consumers (auditors, future automation) can tell apart "tool ran and found nothing" from "tool never ran".

Build the comment body using the literal `tools_run` and `tools_skipped` arrays tracked in Steps 5.1.2 and 5.1.3. Marker: `<!-- sdd:review:implement:tools -->`.

```
<!-- sdd:review:implement:tools -->
## SDD External Tools (round <N>)

**Round:** <N>
**/code-review:** ran | skipped (<reason>)
**/security-review:** ran | skipped (<reason>)

<!-- sdd:findings:json -->
\`\`\`json
{
  "stage": "implement",
  "role": "tools-summary",
  "issue": $1,
  "pr": <PR_NUM>,
  "round": <N>,
  "verdict": null,
  "model": null,
  "findings": [],
  "suggestions": [],
  "tools_run": ["code-review", "security-review"],
  "tools_skipped": [{"name": "security-review", "reason": "shallow-label-skip"}]
}
\`\`\`
<!-- /sdd:findings:json -->
<!-- /sdd:review:implement:tools -->
```

(Replace `<N>` with the actual round number. The two example arrays show field shape only — emit the literal arrays tracked this round.)

Use the Write tool to write the body to `/tmp/sdd-implement-tools-$1-round-<N>.md`, then duplicate-prevention post via `gh api`:

```bash
gh api repos/<owner>/<repo>/issues/<PR_NUM>/comments --jq '.[] | select(.body | contains("<!-- sdd:review:implement:tools -->")) | .id'
```

- If a comment id is returned → update in place:
  ```bash
  gh api repos/<owner>/<repo>/issues/comments/<id> -X PATCH --field body=@/tmp/sdd-implement-tools-$1-round-<N>.md
  ```
- Otherwise → create:
  ```bash
  gh pr comment <PR_NUM> --body-file /tmp/sdd-implement-tools-$1-round-<N>.md
  ```

This comment is informational; the round decision is unchanged by it.

#### 5.1.5 — Round decision

- Reviews passed → exit loop; proceed to Phase 6.
- Reviews failed, round < 3 → build **structured retry feedback**:
  1. Fetch review comments from the PR.
  2. Extract `<!-- sdd:findings:json -->` JSON blocks from each SDD reviewer's comment.
  3. Combine findings arrays, **keep all severities**, sort `critical → major → minor` (per `_review_helpers.md` Section C.1).
  4. Append `/code-review` Important findings (translated to JSON: `{severity: "critical", ...}` with `rule_id: "code-review-important"`). Also append Nit findings as `{severity: "minor", ...}` so the work atom has the specific call-out lines as context.
  5. Append `/security-review` High and Medium findings (translated to JSON: `{severity: "critical" | "major", ...}` with `rule_id: "security-review-<category>"`). Also append Low/informational findings as `{severity: "minor", ...}`.
  6. Pass combined JSON array as `$3` to the next round's `implement_pr` atom in **retry mode**.
- Reviews failed, round == 3 → exit loop. Proceed to **Phase 5.5 (escalation)**.

### Round 2 and Round 3 (retry)

Same structure with one change: spawn `implement_pr` in **retry mode** by passing the structured findings as `$3`. Retry mode pushes new commits to the existing PR (no force-push, no amend) and does NOT create a new PR.

#### 5.N.0 — Spawn implement_pr in retry mode

- `prompt`:
  > Read `<<SKILL_DIR>>/commands/atoms/implement_pr.md` and execute its instructions for Issue #$1 on branch `<branch-name>` in retry mode.
  > Previous round structured findings — sorted by severity (critical → major → minor). Address every critical and major finding with new commits (do NOT force-push, do NOT amend). Read minor findings as supporting context (often the specific file/line/symbol a higher-severity finding referenced abstractly).
  > <inlined JSON array>
  > Return EXACTLY one line in the contract.

Then proceed to 5.N.1 (same as 5.1.1), 5.N.2, 5.N.3, 5.N.4, 5.N.5.

The review atoms re-diff the (now updated) PR and post fresh review comments via duplicate-prevention markers. The 5.N.4 tools-summary comment is updated in place with this round's `tools_run` / `tools_skipped`.

## Phase 5.5: Round 3 Escalation Gate

Runs only if round 3 failed.

1. Render summary:
   ```
   ⚠ Implement stage: 3 PR Final review rounds failed.
   Remaining critical/major findings:
     - [critical] ... (implement/<role>)
     - [major] ... (implement/<role>)
     - [critical] ... (code-review)
   ```
2. **Honor skip-review** (auto-decide in unattended runs):
   - If `pr` is in skip-review (`/sdd auto` / `/sdd batch`):
     - Log to the Issue/PR (via comment) and to the orchestrator output: "⚠ Round 3 PR Final escalation: review still has critical/major findings, but `skip-review: pr` is set — auto-continuing to Phase 6. Findings remain on the PR for human follow-up."
     - Proceed to **Phase 6** immediately without asking. Do NOT call AskUserQuestion or any interactive prompt.
   - Else (interactive mode):
     - Ask the user: "Continue to Phase 6 / Pause for manual intervention / Stop?"
     - On "Continue" → proceed.
     - On "Pause" → stop. User resumes via `/sdd resume <N>` after manual fixes.
     - On "Stop" → exit cleanly.

## Phase 6: User confirmation and label transition

Check skip-review setting.

- If `pr` is in skip-review:
  - Log "User review skipped (skip-review: pr)".
  - Update label to `sdd:test`.
  - If `qa` is also in skip-review → **auto-proceed (read + execute inline, do NOT spawn a subagent)**: read `<<SKILL_DIR>>/commands/test.md` and execute its instructions for Issue #$1 in this same main session.
  - Otherwise → stop. PR created, label updated; human reviews PR and runs QA.

- Otherwise:
  - Present the PR URL, change summary, and the review verdicts (PASS/FAIL with summary).
  - Ask for final confirmation.
  - On approval → update label to `sdd:test`.

## Phase 7: Child completion notification (if this is a child Issue)

Runs **only if the Issue body matches the multi-language parent regex `(Parent|상위 |親)Issue: #<n>` (Common Definitions → Parent/Child Issue Detection)** AND the Issue's label has just transitioned to `sdd:done` (typically after `/sdd test <child>` completes).

1. Find the parent Issue number from `<!-- sdd:child-issue -->` block.
2. Find the **most recent** children comment on the parent containing BOTH `<!-- sdd:children:output -->` and `<!-- /sdd:children:output -->`:
   ```bash
   gh api repos/<owner>/<repo>/issues/<parent>/comments \
     --jq '.[] | select((.body | contains("<!-- sdd:children:output -->")) and (.body | contains("<!-- /sdd:children:output -->"))) | {id, body}'
   ```
   - If no matching comment → warn and skip update.
   - If multiple → use the last one.
3. Update the children comment — follow `<<SKILL_DIR>>/commands/atoms/_review_helpers.md` Section F (mandatory temp-file pattern):
   - Take the existing body from step 2, replace this child Issue's row with the new status in narrative (not in shell).
   - **Write tool**: render the updated body into `/tmp/sdd-children-output-<parent>.md` (overwrites the original temp file from `design_work` — that's fine; the original is no longer needed).
   - **Bash**: `gh api repos/<owner>/<repo>/issues/comments/<id> -X PATCH --field body=@/tmp/sdd-children-output-<parent>.md`
4. Verify the update by re-reading the comment via the same search as step 2.
5. Check if ALL child Issues are `sdd:done`:
   - Read each child's actual label.
   - If all `sdd:done` → post completion notification on the parent suggesting `/sdd test <parent>` or `/sdd resume <parent>`. Use Section F:
     - **Write tool**: render the notification body (e.g. `All children done. Run /sdd test <parent>.`) into `/tmp/sdd-children-complete-<parent>.md`.
     - **Bash**: `gh issue comment <parent> --body-file /tmp/sdd-children-complete-<parent>.md` (no duplicate-prevention needed — each completion event is a new comment).
   - If not → report remaining children to the user in chat. In skip-review mode (`/sdd auto` / `/sdd batch`), do NOT ask which to work on next — stop here so the outer orchestrator's child auto-discovery picks up remaining children. In interactive mode, you may ask the user which child to work on next. (No comment posted in this branch.)

## Notes

- **Atoms never spawn other atoms.** All Agent-tool spawning happens here.
- **TDD is per-step gated.** Each of 3-1 through 3-4 has its own step atom + step review. Failure in any step triggers up to 2 retries on that step alone before escalation.
- **PR Final reviews are independent.** Three SDD reviewers (completeness, quality, adversarial) run in parallel with independent contexts.
- **`/code-review` integration is graceful.** If unavailable, the orchestrator continues without it.
- **Retry limit is 3 rounds for PR Final** (initial + 2 retries), then escalation gate.
- **Retry feedback is structured JSON**, lossless between rounds.
- **Review comments are updated in place across rounds** via duplicate-prevention markers.
- **Reviews go on the PR** for PR Final (`<!-- sdd:review:implement:<role> -->`). TDD step reviews go on the **Issue** (`<!-- sdd:review:implement:step-<n> -->`) because the PR may not exist yet during steps 3-1~3-4.
- **Depth label override**: `sdd:review:deep`/`sdd:review:shallow` shifts model assignments per `_review_helpers.md` Section C.
