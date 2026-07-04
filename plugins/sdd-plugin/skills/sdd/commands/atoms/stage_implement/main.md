# STAGE: implement (main / entry)

**Single sub-agent. MUST NOT spawn Agent calls. MUST NOT spawn other sub-agents. MAY use the Skill tool (`/code-review`, `/security-review`) per `spec/edge-cases.md` §12 and Common Contracts §13.**

This file is the Arch B stage sub-agent entry point for the **Implement** stage — the largest and most complex stage. The main session (or `resume.md` bootstrap) spawns this sub-agent once per Issue per stage invocation.

Phase logic is split across four files for readability (per `design/SYNTHESIS-v2.md` T1.3); all four execute inside this single sub-agent context — no nested Agent spawns:

- `main.md` (this file) — Phases 0/1/2 + return contract.
- `_tdd.md` — Phase 3 TDD pipeline (Red → Green → Refactor → E2E + per-step `tdd_step_review` + R9 idempotency).
- `_pr_final.md` — Phase 4 PR creation (with R8 auto-route) + Phase 5 PR Final review loop (3 SDD reviewers serial + `/code-review` + `/security-review` + tools-summary) + Phase 5.5 escalation gate.
- `_phase7.md` — Phase 7 child completion notification (entered only when the Issue is already `sdd:done`).

The sub-agent owns retry loops (per-step 2-retry budget, PR Final 3-round budget), `skip-review` auto-continue branches for the `implement` and `pr` keys, marker posting via Section F, the R8 (empty-`$3` + existing-PR) auto-route, and the R9 (TDD step idempotency) check. It does NOT call `AskUserQuestion`, does NOT transition labels (the `sdd:implement → sdd:test` transition is the main session's job), and does NOT consume `skip-review: qa` (that's main's job after `OK ADVANCE`). On Round 3 PR Final FAIL with `skip-review: pr` OFF the sub-agent returns an `ESCALATE:` line so main can interactively prompt the user.

> **Bash Command Execution**: every shell snippet below is its own simple Bash tool call. See canonical rules in `<<SKILL_DIR>>/commands/atoms/_bash_rules.md`. Codebase exploration uses **Grep / Glob / Read** tools, not Bash equivalents.

> **Model dial note (per Arch B / `design/stage-designs/implement.md` §5)**: the per-atom model column from the legacy spec (`opus`/`sonnet`/`haiku`) is **informational only** inside this sub-agent. The whole stage runs at one model (set by the main-session Agent spawn, normally `opus`). The depth dial DOES still drive `/code-review --effort` (default=high / deep=max / shallow=medium) and `/security-review` shallow-skip — those are the surviving runtime effects.

---

## Inputs

- `$1` — Issue number. Already validated as an Issue (not a PR) by the caller, but re-validated here as defense in depth (`spec/00-common-contracts.md` §10).
- `$2` — Depth dial. One of `default` / `deep` / `shallow`. The caller derives this from labels; this sub-agent verifies against the live labels in Phase 0.
- `$3` — Resume hint. One of:
  - `none` (default; full execution Phase 0 → Phase 5/5.5 → return),
  - `continue-after-escalation` (skip Phases 1–5; main session already escalated to user and the user chose Continue — work + reviews are already persisted on GitHub),
  - `phase-7` (Issue already at `sdd:done`; run Phase 7 child completion notification only).
  Per `design/01-sub-agent-contract.md` §3 + §6 and SYNTHESIS-v2 T1.5.
- `$4` — Branch hint. Optional cache hint passed by main session on resume. The sub-agent re-derives from local git state regardless. May be `null`.
- `$5` — PR hint. Optional cache hint. Sub-agent re-derives via `gh pr list --head <branch> --state open` regardless. May be `null`.

`Branch` / `PR` are CACHE HINTS, never authoritative — re-fetch from GitHub. Per `design/stage-designs/implement.md` §1 PRESERVE note.

---

## §1. Issue Validation (defense in depth)

Before anything else, validate `$1` per Common Contracts §10:

```bash
gh issue view $1 --json url --jq .url
```

- Empty / error → return `FAIL: Issue #$1 does not exist`.
- URL contains `/pull/` → return `FAIL: #$1 is a Pull Request, not an Issue. SDD commands operate on Issues only.` Do NOT modify any state, do NOT post comments.
- URL contains `/issues/` → continue.

[PRESERVE — `spec/stage/implement.md` §10 Issue Validation gate; `spec/00-common-contracts.md` §10.]

---

## §2. Precondition — design output

`spec/stage/implement.md` §1 requires `<!-- sdd:design:output -->` on the Issue before implement runs.

```bash
gh repo view --json nameWithOwner -q .nameWithOwner
```

Observe the literal `<owner>/<repo>` from output. Then:

```bash
gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | select(.body | contains("sdd:design:output")) | .id'
```

- Empty → return `FAIL: design output not found on Issue #$1`.
- Has id → continue. Hold `<owner>/<repo>` in narrative context for all subsequent `gh api repos/<owner>/<repo>/...` calls (Common Contracts §11).

---

## §3. Phase 0 — Depth detection

Even though `$2` was passed in by the caller, re-read labels here to keep the sub-agent self-contained:

```bash
gh issue view $1 --json labels --jq '[.labels[].name]'
```

Decision (overrides `$2` if labels disagree):
- Labels contain `sdd:review:deep` → `depth = deep`
- Labels contain `sdd:review:shallow` → `depth = shallow`
- Otherwise → `depth = default`

Surviving runtime effects of `depth` (per `design/stage-designs/implement.md` §5):
- `/code-review --effort` argument in `_pr_final.md`: `high` (default) / `max` (deep) / `medium` (shallow).
- `/security-review` shallow-skip in `_pr_final.md`: skip when `depth == shallow`.

Record `depth` for the `<details>` self-review trace.

---

## §4. Resume routing

Branch on `$3`:

### §4.1 Resume = `phase-7`

Triggered when main session detects the Issue body matches the multilingual parent regex AND the label has just transitioned to `sdd:done` (`spec/stage/implement.md` §10 Phase 7; `spec/edge-cases.md` §1 + §2).

Action: **Read `<<SKILL_DIR>>/commands/atoms/stage_implement/_phase7.md`** and follow its instructions for Issue `$1`. That file returns `OK PAUSE` or `FAIL: <reason>`. Return that line as this sub-agent's result. Do NOT proceed to Phases 1–5.

### §4.2 Resume = `continue-after-escalation`

Triggered when main session prior-spawn returned `ESCALATE: implement round 3 FAIL ...`, user chose Continue, and main re-spawned. Work + reviews are already persisted on GitHub.

Steps (T1.5 canonical resume behavior, per `design/01-sub-agent-contract.md` §3 + SYNTHESIS-v2 T1.5):
1. Re-validate `$1` is still an Issue (Phase 1 above already did this; nothing more to do).
2. Re-derive `<branch_name>` and `<PR_NUM>` from GitHub:
   ```bash
   gh pr list --search "Refs #$1" --state open --json number,headRefName --jq '.[0]'
   ```
   - Empty → return `FAIL: continue-after-escalation requested but no open PR for Issue #$1`.
   - Has object → observe `number` and `headRefName` literally. Hold `<PR_NUM>` and `<branch_name>`.
3. Confirm the three PR Final markers exist on the PR:
   ```bash
   gh api repos/<owner>/<repo>/issues/<PR_NUM>/comments --jq '.[] | select(.body | contains("sdd:review:implement:completeness") or contains("sdd:review:implement:quality") or contains("sdd:review:implement:adversarial")) | .id'
   ```
   - If fewer than 3 distinct ids present → return `FAIL: continue-after-escalation requested but prior round's PR Final review markers missing on PR #<PR_NUM>`.
4. Determine `e2e_skipped` state: search for the step-4 commit subject or for an explicit prior `OK ADVANCE` note in PR conversation. If unclear, default `e2e_skipped = false`. (Best-effort; conservative.)
5. Skip directly to §8 Return — Normal path with `OK ADVANCE: test PR: #<PR_NUM> BRANCH: <branch_name>` (append ` E2E_SKIPPED` if step (4) determined so).

### §4.3 Resume = `none` (default)

Continue to §5 Phase 1.

---

## §5. Phase 1 — Parent / Child Classification

`spec/stage/implement.md` §10 Phase 1; `design/stage-designs/implement.md` §7.

### §5.1 Detect children

```bash
gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | select(.body | contains("<!-- sdd:children:output -->")) | .id'
```

- Empty → not a parent → §6 Phase 2.
- Has id → parent → §5.2.

### §5.2 Parent branch — return PARENT_STOP

`design/stage-designs/implement.md` §7.3. Per `design/01-sub-agent-contract.md` §4 sub-agent never asks user — main session asks which child to work on (interactive) or queues children (skip-review).

Read `.github/.sdd-config` (Read tool). Parse `skip-review:` — comma-separated entries. Valid: `analyze`, `design`, `implement`, `pr`, `qa`. (File or key absent → empty list.)

- Branch is informational; both branches return `OK PARENT_STOP`:
  - `implement` IS in skip-review → log to sub-agent narrative: "Parent #$1 has children; stopping for outer orchestrator to queue children."
  - `implement` is NOT in skip-review → log: "Parent #$1 has children; main session will prompt user for next child."

Skip to §8 Return — emit `OK PARENT_STOP`.

[PRESERVE — `spec/stage/implement.md` §10 Parent path; `design/01-sub-agent-contract.md` §4 sub-agent never calls AskUserQuestion.]

---

## §6. Phase 2 — Plan (inlined `implement_plan` logic)

`spec/stage/implement.md` §4 Phase 2; `design/stage-designs/implement.md` §6.

### §6.1 Step 0 — Preflight (Heavy tier)

Follow `<<SKILL_DIR>>/commands/atoms/_preflight.md` Section A — tier **Heavy**, Section B items 1 + 2 + 3 + 4 + 5 (project conventions + commit message style + similar past PRs + target directory survey + project-specific stage rules). Apply Section D failure handling. Record findings for the §6.6 self-review trace.

Item 4 target directory comes from the design output's File Structure section (read in §6.2).

### §6.2 Step 1 — Read context

```bash
gh issue view $1
gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | select(.body | contains("sdd:design:output")) | .body'
```

Capture the design output's File Structure (target dir) and Testability (mock/stub strategies, injection points, hard-to-test concerns, and any E2E-level scenario notes). **Do NOT read the `<!-- sdd:analyze:output -->` comment** — design already incorporated those requirements (`implement_plan.md` Hard rules).

### §6.3 Step 2 — Detect parent reference (multilingual regex)

Scan the Issue body for the canonical regex from `<<SKILL_DIR>>/commands/atoms/_multilingual.md` (and `spec/02-multilingual.md` §3):

```
(Parent|상위 |親)Issue: #<n>
```

Per §3 — `상위` is followed by a space; `親` is NOT followed by a space. Append `([^0-9]|$)` boundary when matching a specific `<n>` to prevent `#683` matching `#6831` (`spec/edge-cases.md` §1 — 5+ callers depend on this exact pattern). If a match is found, capture `<parent_num>` for branch naming + PR body localization.

### §6.4 Step 3 — Create or reuse feature branch

Derive branch name:
- Single Issue: `feat/<feature-name>` (kebab-case from Issue title)
- Child Issue: `feat/<parent-feature>/<child-feature>` where `<parent-feature>` is the kebab-cased parent's title.

Inspect `git log --oneline -20` (Item 2 already did this) to follow the repo's branch-naming convention if it differs from the defaults above. [PRESERVE — load-bearing for project conformance per `spec/stage/implement.md` §9.]

Check existence first:
```bash
git rev-parse --verify <branch_name>
```

- Exit code 0 (exists) → checkout:
  ```bash
  git checkout <branch_name>
  ```
- Non-zero (does not exist) → create + checkout:
  ```bash
  git checkout -b <branch_name>
  ```

Hold `<branch_name>` as stage-internal state for §7 (Phase 3 TDD) and `_pr_final.md`.

### §6.5 Step 4 — Test plan + implementation plan body

Determine output language from `.github/.sdd-lang` per `<<SKILL_DIR>>/commands/atoms/_multilingual.md` (fallback: detect from Issue body; else `en`).

Write the **test plan** for this PR, referencing the design's Testability section directly:
- Extract mock/stub strategies and hard-to-test concerns.
- For each strategy: which test paths cover it.
- Classify each case by behavioral path: **Happy path** / **Error path** / **Boundary conditions** / **Concurrent / State** (or `N/A`).
- If design's Testability section equals `N/A`: write the test plan without mocking.
- If Testability has 1+ entries: each entry's mock/stub strategy MUST appear in the test plan's setup section (e.g. "Mock the Clock injection point per design row 1").

Write the **implementation plan** based on the test plan:
- Which files to add / modify (consistent with design's File Structure section).
- Order of operations.
- Any setup / teardown required.

### §6.6 Step 5 — Self-review (blockers only)

Before posting verify:
- [ ] Marker `<!-- sdd:implement:plan -->` present (open + close)
- [ ] Test plan and implementation plan sections filled (no `<empty>` / TODO placeholders)
- [ ] Branch name set and valid for the repo's convention
- [ ] Design output is referenced (file paths from design appear in implementation plan)

If a blocker fails → fix inline. Track for the trace below.

Quality / completeness / risk evaluation are NOT done here — implement-plan review is `self_only` (no separate plan review atom). The user confirmation gate in legacy `implement.md` §2.2 is replaced in Arch B by implicit consent: main session pre-confirmed via `skip-review: implement` OR via the design stage's exit gate. (`design/stage-designs/implement.md` §6.2; behavior shift documented in spec §20.5.)

### §6.7 Step 6 — Post the plan via Section F

Follow `<<SKILL_DIR>>/commands/atoms/_review_helpers.md` Section F — mandatory temp-file pattern (Common Contracts §9: multi-line bodies must NOT be passed inline).

1. **Write tool** — render the plan body to `/tmp/sdd-implement-plan-$1.md`. Body shape (`implement_plan.md` lines 89–119):

   ```
   <!-- sdd:implement:plan -->
   ## Implementation Plan

   **Feature branch:** `<branch_name>`

   ### Test Plan
   #### Happy path
   - <test cases>
   #### Error path
   - <test cases>
   #### Boundary conditions
   - <test cases>
   #### Concurrent/State
   - <test cases or "N/A">

   ### Implementation Plan
   1. <ordered steps>
   2. ...

   <details>
   <summary>Self-review trace (blockers only)</summary>
   ...
   </details>
   <!-- /sdd:implement:plan -->
   ```

   Skip the `<details>` block if nothing to record.

2. **Bash** — duplicate-prevention search:
   ```bash
   gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | select(.body | contains("<!-- sdd:implement:plan -->")) | .id'
   ```

3. **Bash** — branch on the result:
   - Empty → `gh issue comment $1 --body-file /tmp/sdd-implement-plan-$1.md`
   - Has id `<id>` → `gh api repos/<owner>/<repo>/issues/comments/<id> -X PATCH --field body=@/tmp/sdd-implement-plan-$1.md`

[PRESERVE — Common Contracts §9 Comment Posting Pattern (Section F mandatory); §4 Update-in-place invariant; deterministic path `/tmp/sdd-implement-plan-$1.md`.]

### §6.7.5 Coverage Ledger — Test Plan scenarios

Register the §6.5 Test Plan cases as tracked scenarios in the shared coverage ledger. Runs AFTER §6.7 posted the plan.

1. **Bash** — fetch the existing ledger:

   ```bash
   gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | select(.body | contains("<!-- sdd:coverage:ledger -->")) | .body'
   ```

   Parse the JSON between `<!-- sdd:coverage:json -->` and `<!-- /sdd:coverage:json -->` in context.
   - **Found** → hold the parsed object.
   - **Empty** (analyze + design skipped) → build an initial ledger in context from the design output's Feature List (already in narrative from §6.2): ids `F1`, `F2`, …, `e2e_required` per the design's `E2E required:` lines, `scenarios: []`, `pr: null`.

2. Populate the `scenarios` array from the §6.5 Test Plan:
   - One entry per test case, ids `S1`, `S2`, … sequential.
   - `feature_id` — match the case to a feature by title / Feature List wording; if a case spans features, pick the primary one.
   - `description` — the test case text from the plan (specific, not the category name).
   - `category` — `happy_path` / `error_path` / `boundary` / `concurrent` per its Test Plan section; skip `N/A` sections.
   - Additionally, one entry per design-flagged E2E scenario (`e2e_required: true` features): `category: "e2e"`, `test_level: "e2e"`, `description` from the design's `E2E required: <scenario>` text.
   - `test_level` — `unit` for isolated logic, `integration` for cases exercising the mock/stub seams from the design's Testability section.
   - `status: "pending"`, `sha: null`, `reason: null` for every entry.
   - **Retry idempotency**: first remove all existing `"pending"` scenarios (uncommitted plan items), then add the fresh plan-derived set. Assign new ids starting from `S<M+1>` where M is the largest numeric suffix among all remaining non-pending scenario ids (e.g. if S1–S3 are automated, fresh pending set starts from S4). If no non-pending scenarios exist, start from S1. This prevents id collision with previously automated/manual/skipped scenarios.

3. Recompute `summary`: `total` = scenarios length; `pending` = count of `"pending"`; other counters from their statuses (normally `automated`/`manual`/`skipped` are `0` here).

4. Set `updated_by: "implement"`. Keep `issue`, `pr`, `features`, `version` unchanged.

5. **Write tool** — render to `/tmp/sdd-coverage-ledger-$1.md` (same body shape as the analyze/design ledger steps; `**Updated by:** implement`).

6. **Bash** — duplicate-prevention search:

   ```bash
   gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | select(.body | contains("<!-- sdd:coverage:ledger -->")) | .id'
   ```

7. **Bash** — branch on the result:
   - **Has id `<id>`** → `gh api repos/<owner>/<repo>/issues/comments/<id> -X PATCH --field body=@/tmp/sdd-coverage-ledger-$1.md`
   - **Empty** → `gh issue comment $1 --body-file /tmp/sdd-coverage-ledger-$1.md`

Non-blocking on failure: log a warning and continue — `_pr_final.md` §3.4.5 and `stage_test.md` fall back to plan/marker re-derivation when the ledger is absent. Hold the ledger comment `<id>` in narrative for `_pr_final.md`.

### §6.8 Phase 2 atom-level failure

Any unrecoverable error in §6 (gh API failure, design output missing despite §2 precondition, branch creation failure, plan post failure, etc.) → return `FAIL: <reason>` from this sub-agent immediately. Do NOT proceed to TDD.

---

## §7. Phase 3 — TDD step pipeline → Read `_tdd.md`

`spec/stage/implement.md` §4 Phase 3 + §5 TDD pipeline; `design/stage-designs/implement.md` §8 + §10.

**Read `<<SKILL_DIR>>/commands/atoms/stage_implement/_tdd.md` and execute its instructions** with stage-internal inputs:
- `$1` — Issue number (forward verbatim).
- `<branch_name>` — captured in §6.4.
- `<owner>/<repo>` — captured in §2.
- `<parent_num>` (optional) — captured in §6.3 if child Issue.
- `depth` — from §3.

`_tdd.md` iterates steps 3-1 → 3-2 → 3-3 → 3-4. For each step it:
1. Runs the R9 idempotency check (`<!-- sdd:test-evidence:step-<n> -->` sha-from-evidence per SYNTHESIS-v2 T1.2).
2. If idempotent → reuses prior `<sha>` + `<test_evidence>`, moves on.
3. Otherwise runs the inlined step atom logic (red/green/refactor/e2e), up to 3 attempts (1 + 2 retries per step), with `tdd_step_review` between each attempt.

`_tdd.md` returns stage-internal control values:
- `OK PROCEED` + `e2e_skipped: bool` — all 4 steps complete (or carried forward via skip-review).
- `OK PARENT_STOP` — defensive; shouldn't fire here (Phase 1 handled this).
- `FAIL: <reason>` — atom-level error from any step.

If `FAIL:` → return that line as this sub-agent's result. If `OK PROCEED` → record `e2e_skipped` and continue to §8.

---

## §8. Phase 4 + 5 + 5.5 — PR creation + PR Final review loop → Read `_pr_final.md`

`spec/stage/implement.md` §4 Phase 4 + §4 Phase 5 + §6 PR Creation + §7 PR Final Review Loop; `design/stage-designs/implement.md` §11 + §12.

**Read `<<SKILL_DIR>>/commands/atoms/stage_implement/_pr_final.md` and execute its instructions** with stage-internal inputs:
- `$1` — Issue number.
- `<branch_name>` — from §6.4.
- `<owner>/<repo>` — from §2.
- `<parent_num>` (optional) — from §6.3.
- `e2e_skipped: bool` — from §7.
- `depth` — from §3.

`_pr_final.md` covers:
- Phase 4: first-round PR creation with R8 auto-route (existing-PR detected → soft retry; per SYNTHESIS-v2 T1.1 no `strict-pr-creation` config key).
- Phase 5: 3-round PR Final review loop — for each round N ∈ {1, 2, 3}:
  - 5.N.1 — 3 SDD reviewers serial (completeness → quality → adversarial; all share PR diff from §4.3.a.2 — no re-fetch per Change B).
  - 5.N.2 — `/code-review` Skill (after 5.N.1; effort by depth).
  - 5.N.3 — `/security-review` Skill (after 5.N.2; shallow-skip).
  - 5.N.4 — `<!-- sdd:review:implement:tools -->` summary marker on PR.
  - 5.N.5 — Round verdict.
- Round PASS → exit + return `OK PR: #<PR_NUM>` for this sub-agent's §9 to consume.
- Round FAIL + N<3 → inlined `implement_pr` retry mode (no force-push, no amend; new fix-up commit appended).
- Round FAIL + N==3 → Phase 5.5 escalation gate (skip-review `pr` → auto-continue; else `ESCALATE: ...`).

`_pr_final.md` returns:
- `OK ADVANCE PR: #<PR_NUM>` — TDD + PR Final passed; this sub-agent returns `OK ADVANCE: test PR: #<PR_NUM> BRANCH: <branch_name>` (append ` E2E_SKIPPED` if `e2e_skipped`).
- `ESCALATE: <summary>` — return verbatim (main asks user Continue / Pause / Stop).
- `FAIL: <reason>` — return verbatim.

---

## §9. Return contract (verbatim from `design/01-sub-agent-contract.md` §2 stage_implement)

Return EXACTLY one line, prefixed by the `>>> RESULT <<<` sentinel on its own preceding line. The line(s) before the sentinel may contain narrative — main session ignores until it sees the sentinel.

| Return | Meaning |
|---|---|
| `OK ADVANCE: test PR: #N BRANCH: <name>` | TDD + PR Final passed; main transitions `sdd:implement → sdd:test`. |
| `OK ADVANCE: test PR: #N BRANCH: <name> E2E_SKIPPED` | Same + E2E was skipped — stage_test reads this and decides framework install. |
| `OK PARENT_STOP` | Parent Issue with children; main queues children. |
| `OK PAUSE` | Phase 7 child-completion path returned (sub-agent stopped non-error); main does NOT advance any label. Also the value Phase 7 returns regardless of all-children-done state. |
| `ESCALATE: <summary>` | Round 3 PR Final FAIL in interactive mode — main asks user Continue / Pause / Stop. |
| `FAIL: <reason>` | Atom-level error (Issue Validation failed, gh API failed, design output missing, retry slot value rejected, etc.) — main stops. |

### Examples

```
>>> RESULT <<<
OK ADVANCE: test PR: #142 BRANCH: feat/avatar-upload
```

```
>>> RESULT <<<
OK ADVANCE: test PR: #143 BRANCH: feat/user-profile/avatar-upload E2E_SKIPPED
```

```
>>> RESULT <<<
OK PARENT_STOP
```

```
>>> RESULT <<<
OK PAUSE
```

```
>>> RESULT <<<
ESCALATE: implement round 3 FAIL — findings: [critical] 2, [major] 1. PR: #142 BRANCH: feat/avatar-upload
```

```
>>> RESULT <<<
FAIL: design output not found on Issue #$1
```

[PRESERVE — load-bearing: sentinel + literal status strings are parsed by main FSM. Do NOT reformat to JSON. `OK ADVANCE` MUST carry both `PR: #N` and `BRANCH: <name>` so main session threads both to `stage_test` without re-deriving — `design/01-sub-agent-contract.md` §2 + §8.]

---

## Markers posted (must match `spec/stage/implement.md` §2)

- `<!-- sdd:implement:plan -->` on Issue — §6 Phase 2 (this file).
- `<!-- sdd:coverage:ledger -->` on Issue — updated with Test Plan scenarios (status: pending). PATCHED in place by §6.7.5. Further updated by `_pr_final.md` §3.4.5 (statuses finalized) and §3.8.5 (PR number recorded).
- `<!-- sdd:test-evidence:step-<n> -->` (n ∈ 1..4) on Issue — `_tdd.md` Phase 3 (via `_test_evidence.md`).
- `<!-- sdd:review:implement:step-<n> -->` (n ∈ 1..4) on Issue — `_tdd.md` Phase 3 step reviews.
- `<!-- sdd:review:implement:completeness -->` on PR — `_pr_final.md` Phase 5.
- `<!-- sdd:review:implement:quality -->` on PR — `_pr_final.md` Phase 5.
- `<!-- sdd:review:implement:adversarial -->` on PR — `_pr_final.md` Phase 5.
- `<!-- sdd:review:implement:tools -->` on PR — `_pr_final.md` Phase 5.N.4 (in-place per round).
- `<!-- sdd:findings:json -->` … `<!-- /sdd:findings:json -->` blocks embedded inside each review / tools comment per Common Contracts §5 schema.

[PRESERVE — load-bearing: TDD step reviews go on **Issue** (PR may not exist during Phase 3). PR Final reviews + tools-summary go on **PR**. `spec/stage/implement.md` §2.]

All posted via Section F temp-file pattern with deterministic paths (per `_review_helpers.md` Section F.1):
- `/tmp/sdd-implement-plan-$1.md`
- `/tmp/sdd-test-evidence-$1-step-<n>.md`
- `/tmp/sdd-review-implement-step-<n>-$1.md`
- `/tmp/sdd-review-implement-completeness-pr<PR_NUM>.md`
- `/tmp/sdd-review-implement-quality-pr<PR_NUM>.md`
- `/tmp/sdd-review-implement-adversarial-pr<PR_NUM>.md`
- `/tmp/sdd-implement-tools-$1-round-<N>.md`
- `/tmp/sdd-pr-body-$1.md`

All updates are in-place (duplicate-prevention search → PATCH if id found, else POST). Round-to-round overwrites per Common Contracts §4 update-in-place invariant.

---

## Hard rules

- **Single sub-agent.** This file + the three topic files (`_tdd.md`, `_pr_final.md`, `_phase7.md`) all execute inside ONE Agent-spawned sub-agent context (per `design/01-sub-agent-contract.md`). MUST NOT spawn further Agent calls. MUST NOT spawn other sub-agents. (Architectural invariant per Common Contracts §12; `spec/edge-cases.md` §11.)
- **MAY use Skill tool.** `_pr_final.md` invokes `/code-review` and `/security-review` per `spec/edge-cases.md` §12 (verified). Graceful skip on unavailable / errored. Single-agent constraint does NOT block Skill invocation (`design/stage-designs/implement.md` §13.1).
- **Skill serial after SDD reviewers.** Inside `_pr_final.md` Phase 5 each round, ordering is `5.N.1 (SDD reviewers serial) → 5.N.2 (/code-review) → 5.N.3 (/security-review) → 5.N.4 (tools summary) → 5.N.5 (verdict)`. (`spec/edge-cases.md` §24; `design/stage-designs/implement.md` §13.1 — sub-agent convention, not platform constraint, but preserved for verdict determinism + token economy.)
- **No label changes.** This sub-agent does NOT call `gh issue edit ... --add-label` or `--remove-label`. Label transitions (`sdd:implement → sdd:test`) are the main session's sole responsibility (`design/01-sub-agent-contract.md` §4).
- **No `AskUserQuestion`.** Sub-agents are non-interactive. Round 3 PR Final FAIL in interactive mode is surfaced via `ESCALATE:`. Per-step exhaustion in interactive mode auto-continues with a logged warning (`design/stage-designs/implement.md` §10.7 — Arch B Option 2; behavior shift documented in spec §20.5).
- **No force-push, no `git commit --amend`.** Retry mode appends new fix-up commits to preserve PR review history. `spec/edge-cases.md` §23; `spec/stage/implement.md` §9 Hard rules.
- **No Claude as co-author** in any commit. `spec/stage/implement.md` §2.
- **No `git push` from TDD step atoms** — only `_pr_final.md` (Phase 4 first push, retry mode fix-up push). `_tdd.md` steps commit only.
- **Skill graceful skip is observable.** `_pr_final.md` records every skip reason (`skill-unavailable`, `skill-errored: <truncated>`, `shallow-label-skip`) in the tools-summary marker — distinguishes "ran, no findings" from "never ran". (`design/stage-designs/implement.md` §12.6.)
- **Round-to-round overwrites markers** per Common Contracts §4. Prior-round bodies are lost from GitHub. Findings JSON `round` field IS updated per PATCH (`design/stage-designs/implement.md` §12.10).
- **3-round PR Final retry budget**, **per-step 2-retry budget (3 attempts) for TDD steps**. `spec/edge-cases.md` §22.
- **`skip-review` keys consumed by this sub-agent**: `implement` (Phase 1 parent-stop logging, Phase 3 step-exhaustion auto-continue) and `pr` (Phase 5.5 escalation auto-continue). `qa` is NOT consumed by this sub-agent — main session reads it after `OK ADVANCE` to decide whether to auto-proceed to `commands/test.md`. (`spec/stage/implement.md` §10 Edge Cases skip-review table.)
- **All Bash calls follow `<<SKILL_DIR>>/commands/atoms/_bash_rules.md`.** No `&&`, `||`, `;`, `|`, `$(...)`, `VAR=$(...)`, redirections, or quoted variable expansion. No `find` against `/`, `~`, `/Users`, or paths outside the repo root.
- **All comment posting follows `<<SKILL_DIR>>/commands/atoms/_review_helpers.md` Section F.** Write tool → temp file → `gh issue comment --body-file <path>` or `gh pr comment <PR_NUM> --body-file <path>` or `gh api ... -X PATCH --field body=@<path>`. Inline `--body` with multi-line content is forbidden (Common Contracts §9).
- **Stay within the repository.** Do not Read absolute paths outside the working tree. The Write tool is permitted ONLY for rendering temp-file bodies under `/tmp/sdd-*.md`. Edit / NotebookEdit are permitted ONLY in `_tdd.md` (writing test/production code). NEVER touch files outside the working tree.

---

## Cross-references

- Spec contract: `spec/stage/implement.md`
- Cross-cutting rules: `spec/00-common-contracts.md` (§4 update-in-place, §7 retry self-fetch, §9 comment posting, §10 Issue Validation, §11 owner/repo, §12 single-level spawn, §13 Skill availability)
- Edge cases (cross-reference): `spec/edge-cases.md` §1 (multilingual), §2 (parent/child lifecycle), §6 (in-place marker updates), §9 (retry self-fetch), §11 (single-level spawn), §13 (Step 0 preflight skip on retry), §22 (retry budgets), §23 (no force-push), §24 (Skill ordering)
- Multilingual: `spec/02-multilingual.md` §3
- Architecture: `design/00-architecture.md`
- Sub-agent contract: `design/01-sub-agent-contract.md`
- Per-stage design: `design/stage-designs/implement.md`
- Synthesis-v2 (T1.1 R8 no opt-out, T1.2 R9 sha-based, T1.3 file split, T1.5 ESCALATE Resume, T1.7 model dial, T1.8 batch + ESCALATE conversion): `design/SYNTHESIS-v2.md`
- Rubric files: `<<SKILL_DIR>>/commands/atoms/rubrics/implement-{completeness,quality,adversarial,step}.md`
- Shared helpers: `<<SKILL_DIR>>/commands/atoms/_preflight.md` (Heavy / Code-focused tiers), `<<SKILL_DIR>>/commands/atoms/_review_helpers.md` (Sections B/C/D/E/F), `<<SKILL_DIR>>/commands/atoms/_test_evidence.md`, `<<SKILL_DIR>>/commands/atoms/_bash_rules.md`, `<<SKILL_DIR>>/commands/atoms/_multilingual.md`
- Topic files in this directory: `_tdd.md`, `_pr_final.md`, `_phase7.md`
