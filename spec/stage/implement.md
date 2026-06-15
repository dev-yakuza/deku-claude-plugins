# Stage: Implement

Implementation stage — TDD cycle (Red → Green → Refactor → E2E → PR) with per-step
review gating and a 3-round PR Final review loop. The largest, most complex stage.
Sources: `commands/implement.md`, `commands/atoms/implement_{plan,red,green,refactor,e2e,pr,review,adversarial}.md`, `commands/atoms/tdd_step_review.md`, `commands/atoms/_test_evidence.md`, `commands/ai-review-implement-{completeness,quality,adversarial,step}.md`.

---

## 1. Stage Inputs

### Entry conditions
- `$1` — Issue number passed by `/sdd implement $1`, `/sdd resume`, or auto-proceed from `design`. Validated as Issue (not PR) per Common Contracts §10. (`implement.md` lines 13–15) [PRESERVE]
- Label state: typically `sdd:implement` (set on entry by prior stage or resume dispatcher). Not strictly enforced — stage runs whenever invoked. [PRESERVE]
- **Mandatory upstream**: `<!-- sdd:design:output -->` comment on the Issue. `implement_plan` returns `FAIL: design output not found on Issue #$1` if absent. (`implement_plan.md` line 15) [PRESERVE — load-bearing precondition]
- **Optional resume state** (Issue re-entering implement after prior attempt):
  - Existing feature branch — `implement_plan` step 3 falls back to `git checkout` instead of `git checkout -b`. (`implement_plan.md` line 46) [PRESERVE]
  - Existing open PR — `implement_pr` Mode detection routes to retry mode when `$3 = "retry"` and PR exists. Empty-`$3` + existing PR is an unhandled gap (see §6). (`implement_pr.md` lines 16–28) [PRESERVE / RETHINK]
  - Prior TDD commits — each step atom re-verifies branch state via `git rev-parse` / `git checkout`. No idempotency check skips already-done steps. (`implement_red.md` lines 36–41 et seq.) [PRESERVE; RETHINK]

### Environmental dependencies
- `gh` CLI authenticated for current repo. [PRESERVE]
- `.github/.sdd-lang` (optional) — language for `implement_plan` and `implement_pr` bodies. Same fallback rules as analyze. [PRESERVE]
- `.github/.sdd-config` (optional) — three skip-review keys consumed: `implement`, `pr`, `qa`. (See §10 Edge Cases table.) [PRESERVE]
- Issue labels — read in Phase 0 (depth) and Phase 5.1.3 (`sdd:review:shallow` → skip `/security-review`). [PRESERVE]
- Test runner — auto-detected per repo (`npm test`, `flutter test`, `pytest`, `cargo test`, `go test`, etc.). Required by Red/Green/Refactor/E2E. (`implement_red.md` step 5) [PRESERVE]
- E2E framework artifacts (`playwright.config.*`, `cypress.config.*`, `e2e/`, `integration_test/`, etc.) — detected by `implement_e2e` step 2; absence → `OK E2E_SKIPPED`. [PRESERVE]
- Skill tool availability — `/code-review`, `/security-review`. Graceful skip on absence. [PRESERVE]

### Parent/Child context
- Parent reference detected via multilingual regex `(Parent|상위 |親)Issue: #<n>` inside `<!-- sdd:child-issue -->`. Drives branch naming (`feat/<parent>/<child>`) and PR-body parent line. (`implement_plan.md` line 37; `implement_pr.md` lines 48, 78–82) [PRESERVE]

---

## 2. Stage Outputs

### Markers posted
| Marker | Scope | Posted by |
|---|---|---|
| `<!-- sdd:implement:plan -->` | Issue | `implement_plan` |
| `<!-- sdd:test-evidence:step-<n> -->` (n ∈ 1..4) | Issue | each `implement_<step>` via `_test_evidence.md` |
| `<!-- sdd:review:implement:step-<n> -->` (n ∈ 1..4) | Issue | `tdd_step_review` |
| `<!-- sdd:review:implement:completeness -->` | PR | `implement_review` (role=completeness) |
| `<!-- sdd:review:implement:quality -->` | PR | `implement_review` (role=quality) |
| `<!-- sdd:review:implement:adversarial -->` | PR | `implement_adversarial` |
| `<!-- sdd:review:implement:tools -->` | PR | `implement.md` Phase 5.N.4 (per-round, updated in place) |
| `<!-- sdd:findings:json -->` block | embedded in each review/tools comment | review atoms / Phase 5.N.4 |

[PRESERVE — load-bearing]: TDD step reviews go on the **Issue** (not PR) because the PR may not exist yet during steps 3-1..3-4. PR Final reviews go on the **PR**. (`implement.md` line 386)

`/code-review` and `/security-review` post their own inline line-anchored review comments via the Skill tools — no SDD marker, recognized in retry mode by body emoji / `Severity:` prefix (§6 retry filter). [PRESERVE]

### Labels transitioned to
- `sdd:test` — set in Phase 6 when (skip-review `pr` set) OR (user approves PR). (`implement.md` lines 343, 351) [PRESERVE]
- Stage does NOT close the Issue or set `sdd:done` — that is the `test` stage's job. [PRESERVE]
- **Parent path exception**: when Phase 1 detects this Issue is a parent (has children), no label transition happens — orchestrator stops and the outer flow queues children. (lines 48–52) [PRESERVE]

### Side effects produced
- Feature branch created locally + remote (`feat/<feature-name>` or `feat/<parent>/<child>`). [PRESERVE]
- Up to 4 TDD commits on the branch:
  - Red: `test: <description> (Red)`
  - Green: `feat: <description> (Green)`
  - Refactor: `refactor: <description>` (skipped if `OK REFACTOR EMPTY`)
  - E2E: `test: e2e for <feature>` (skipped if `OK E2E_SKIPPED`)
- Plus retry-mode fix-up commits from `implement_pr` retry mode (one or more per failed round). [PRESERVE]
- PR created (first-round) or updated (retry mode) with `Refs #$1`, optional parent line, change summary, Manual Test Checklist. [PRESERVE]
- Phase 7 only: parent's children comment updated with this child's new status; optional completion notification when all children `sdd:done`. [PRESERVE]

### Side effects NOT produced
- No `sdd:done`, no Issue close (that's test stage). [PRESERVE]
- No force-push, no `git commit --amend` — retry mode appends new commits to preserve review history. (`implement_pr.md` Hard rules) [PRESERVE — load-bearing]
- No new E2E framework install (test stage's call). (`implement_e2e.md` line 64) [PRESERVE]
- No Claude co-author in any commit. (`implement.md` line 8 + every atom's Hard rules) [PRESERVE]

---

## 3. Atom Inventory

| Atom | Role | Model (default / deep / shallow) | Key responsibility |
|---|---|---|---|
| `implement_plan` | Producer | opus / opus / opus | Generate test plan + impl plan, create feature branch, post under `<!-- sdd:implement:plan -->`. |
| `implement_red` | Producer | opus / opus / opus | Write failing tests, commit, post test-evidence. Confirmed Red. |
| `implement_green` | Producer | opus / opus / opus | Write minimal production code, commit, post test-evidence. Confirmed Green. |
| `implement_refactor` | Producer | opus / opus / opus | Refactor while keeping tests green, commit (or `OK REFACTOR EMPTY`). |
| `implement_e2e` | Producer | opus / opus / opus | Detect E2E setup; write E2E or `OK E2E_SKIPPED`. |
| `implement_pr` | Producer | opus / opus / opus | First-round: push + create PR. Retry: self-fetch findings, push fix-ups (no force, no amend). |
| `tdd_step_review` (step 1, 4) | Reviewer | sonnet / opus / haiku | Diff-only review of Red / E2E commit. Verdict on Issue. |
| `tdd_step_review` (step 2, 3) | Reviewer | haiku / opus / haiku | Diff-only review of Green / Refactor commit. (Lower default model — simpler diffs.) |
| `implement_review` (completeness) | Reviewer | sonnet / opus / sonnet | PR Final completeness on PR. |
| `implement_review` (quality) | Reviewer | sonnet / opus / sonnet | PR Final quality on PR. |
| `implement_adversarial` | Reviewer (refuter) | opus / opus / sonnet | PR Final adversarial on PR. |

Source: `implement.md` Phase 0 table, lines 29–36. [PRESERVE]

[RETHINK: step 2/3 use haiku at default while step 1/4 use sonnet. The test-evidence consistency check (step 5a) is identical complexity across all steps. Consider unifying to sonnet at default for reviewer consistency.]

All atoms are single-subagent terminal workers — MUST NOT spawn subagents and MUST NOT call Agent/Skill tools. Each atom enforces this in its Hard rules. (Common Contracts §12) [PRESERVE — architectural invariant]

External Skills (`/code-review`, `/security-review`) are invoked from the **orchestrator main session**, not atoms. (`implement.md` lines 184–186) [PRESERVE; RETHINK per Common Contracts §13 — sub-agents CAN invoke Skills, so Arch B could move these inside a stage sub-agent.]

---

## 4. Phase-by-Phase Behavior

### Phase 0: Depth label detection
Read Issue labels; determine depth (`default`/`deep`/`shallow`) per Common Contracts §3 rule. Depth picks Agent models (Phase 0 table), `/code-review` effort (5.1.2), and gates `/security-review` (5.1.3 shallow skip). [PRESERVE]

### Phase 1: Determine Issue type
- Resolve owner/repo via `gh repo view --json nameWithOwner -q .nameWithOwner`. [PRESERVE]
- Detect children by searching Issue comments for `sdd:children:output` marker.
- **Branch**:
  - **Parent (has children)** — do NOT implement directly.
    - skip-review `implement` set → log "Parent has children; stopping for outer orchestrator to queue children" + stop **without asking**. (line 51) [PRESERVE]
    - Interactive → list children + statuses, ask which to work on. On selection, **read + execute inline** `commands/resume.md` in the same main session — resume dispatcher routes to the child's correct stage. Do NOT spawn for this. (line 52) [PRESERVE — load-bearing: nested Agent spawns are blocked]
  - **Single Issue or Child Issue (no children)** → Phase 2.

### Phase 2: Plan

**2.1 Spawn plan atom**: `subagent_type=general-purpose`, `model=opus` (all depths), prompt reads `implement_plan.md` for `#$1`.
Parse `>>> RESULT <<<`:
- `FAIL: <reason>` → stop.
- `OK BRANCH: <branch-name>` → remember `<branch-name>` for later phases. [PRESERVE]

**2.2 User confirmation**: check `skip-review: implement`.
- Set → log, → Phase 3.
- Interactive → present the plan comment, ask to confirm. Approve → Phase 3. Reject → stop. (`implement.md` lines 72–74) [PRESERVE]

There is no separate "plan review" atom — the plan's review type is `self_only` (atom does its own blocker check). User confirmation in 2.2 is the human gate. [PRESERVE]

### Phase 3: TDD step pipeline (Red → Green → Refactor → E2E)
For each step in order: `red` (3-1) → `green` (3-2) → `refactor` (3-3) → `e2e` (3-4). Up to **2 retries per step** (3 attempts total). Each iteration:

1. **Spawn step atom** (`implement_<step>`, `model=opus`, prompt threads branch name; on retry pass `$3 = "retry"`).
   Parse:
   - `FAIL: <reason>` → stop.
   - `OK <STEP_TYPE> COMMIT: <sha> TESTS: <p>/<t> FAILED: <f>` → remember `<sha>` and substring `TESTS: <p>/<t> FAILED: <f>` as `<test-evidence>`. Continue to step 2.
   - `OK REFACTOR EMPTY` → continue with `<sha>=EMPTY`, `<test-evidence>=NONE`.
   - `OK E2E_SKIPPED` → **skip step 2 entirely**, proceed to next step. (Orchestrator-side skip — `tdd_step_review` is NOT spawned.) [PRESERVE — load-bearing]

2. **Spawn `tdd_step_review`** (model per Phase 0 table, prompt threads Issue, step number, branch, `<sha>`, `<test-evidence>`).
   Parse:
   - `FAIL: <reason>` → stop.
   - `OK PASS` → next step.
   - `OK FAIL: <summary>` → re-spawn this step's atom in retry mode (`$3="retry"`). Up to 2 retries. [PRESERVE]

3. **Step exhaustion** (2 retries consumed without PASS):
   - Post comment to Issue with remaining critical/major findings (Section F).
   - skip-review `implement` set → log "⚠ TDD step-X failed review 3 times. Auto-continuing because `skip-review: implement` is set; unresolved findings carry forward to PR Final." Proceed.
   - Interactive → ask user: Continue / Pause / Stop. Continue → carry forward. Pause → stop, user resumes. Stop → exit. (lines 115–123) [PRESERVE]

After all 4 steps done (or carried forward), → Phase 4.

### Phase 4: PR creation (step 3-5)
Spawn `implement_pr` in **first-round mode** (`model=opus`, no `$3`). Parse:
- `FAIL: <reason>` → stop.
- `OK PR: #N` → remember `<PR_NUM>=#N`.
- `OK PR: #N E2E_SKIPPED` → same; note E2E was skipped for downstream `/sdd test`. [PRESERVE]

### Phase 5: PR Final review loop (3 rounds + escalation)
Each round = 3 parallel SDD reviewers + `/code-review` + `/security-review` → tools-summary → verdict → decision.

**Round 1 — 5.1.1 Spawn 3 SDD review atoms in parallel.**
Single message with three Agent calls (concurrent): completeness, quality, adversarial. Each returns `OK PASS PR: #N` / `OK FAIL PR: #N: <summary>` / `FAIL: <reason>`.
- Any atom-level `FAIL: <reason>` → stop.
- Combine verdicts; surface adversarial-only FAIL as warning to user. [PRESERVE]

**Round 1 — 5.1.2 Invoke `/code-review`** (serial, **after** 5.1.1):
- Effort: `high` (default), `max` (deep), `medium` (shallow). Args: `--comment`. Target: `<PR_NUM>`.
- **Graceful skip**: Skill unavailable → log + skip; do NOT fail the round. (lines 193–194) [PRESERVE]
- Track `tools_run`: `"code-review"` (invoked) or `tools_skipped`: `{"name":"code-review","reason":"skill-unavailable"}`.
- If invoked, read PR comments and count: 🔴 Important → critical; 🟡 Nit → minor; 🟣 Pre-existing → ignored. 1+ Important → contributes a FAIL.

[PRESERVE — load-bearing invariant]: the Skill tool **cannot** be in the same parallel batch as Agent calls. Issue serially after Agent calls complete. (`implement.md` lines 184–186) The rewrite must preserve this ordering OR move Skills into a stage sub-agent (Arch B).

**Round 1 — 5.1.3 Invoke `/security-review`** (serial, **after** 5.1.2):
- No effort argument (Skill self-calibrates). Target: branch / `<PR_NUM>`.
- **Graceful skip**: unavailable → log + skip.
- **Shallow label skip**: if `sdd:review:shallow` on Issue, skip to keep cost low. Record `{"name":"security-review","reason":"shallow-label-skip"}`. [PRESERVE — load-bearing depth gate]
- If invoked, classify: High → critical; Medium → major; Low/info → minor. (lines 215–236)

**Round 1 — 5.1.4 Post round-level tools-summary** ([IMPROVE: observability of graceful skip — added precisely so consumers can distinguish "ran, no findings" from "never ran"]):
- Marker `<!-- sdd:review:implement:tools -->` on the PR.
- Body fields: `**Round:** <N>`, `**/code-review:**` (ran | skipped <reason>), `**/security-review:**` (ran | skipped <reason>), embedded `<!-- sdd:findings:json -->` with `role:"tools-summary"` (verdict null, model null, findings [], populated round/tools_run/tools_skipped per Common Contracts §5).
- Write body to `/tmp/sdd-implement-tools-$1-round-<N>.md` (Write tool). Standard Section F duplicate-prevention: empty search → `gh pr comment <PR_NUM> --body-file <path>`; has id → `gh api .../issues/comments/<id> -X PATCH --field body=@<path>`.
- **Informational** — does NOT affect the round verdict. (line 293) [PRESERVE]

**Round 1 — 5.1.5 Round decision**:
- Reviews passed → exit loop → Phase 6.
- Reviews failed, round < 3 → spawn `implement_pr` retry mode → Round N+1. Orchestrator does NOT fetch PR comments itself — atom self-fetches per Section C + own inline-PR-comment fetch. [PRESERVE — v0.36 atom-side retry pattern]
- Reviews failed, round == 3 → Phase 5.5.

**Rounds 2 & 3 (retry)** — same structure with one change: pass `$3="retry"` to `implement_pr`. Atom self-fetches the 3 SDD review markers (PR-scoped) AND `/code-review` + `/security-review` inline PR comments. Pushes fix-up commits to existing PR (no force, no amend). Review atoms re-diff the updated PR and post fresh review comments (duplicate-prevention). The tools-summary is updated in place. (lines 302–314) [PRESERVE]

### Phase 5.5: Round 3 Escalation Gate (only if round 3 FAIL)
1. Render summary of remaining critical/major findings with role label (`implement/<role>`, `code-review`, `security-review`).
2. Branch on `skip-review: pr`:
   - **Set** → log on Issue/PR comment and orchestrator output ("⚠ Round 3 PR Final escalation … `skip-review: pr` set — auto-continuing"). Proceed to Phase 6 **without asking**. Do NOT call AskUserQuestion. (lines 329–331) [PRESERVE]
   - **Interactive** → ask Continue / Pause / Stop. Continue → Phase 6. Pause → stop (resume via `/sdd resume <N>` after manual fix). Stop → exit. (lines 332–336) [PRESERVE]

[PRESERVE]: skip-review key here is `pr`, **distinct** from `implement`. See §10 Edge Cases table.

### Phase 6: User confirmation + label transition
Check `skip-review: pr`.
- **Set**:
  - Log "User review skipped (skip-review: pr)".
  - Update label to `sdd:test`.
  - If `skip-review: qa` also set → **auto-proceed inline** (read + execute `commands/test.md` in same main session; do NOT spawn). [PRESERVE — load-bearing]
  - Otherwise → stop. PR + label updated; human runs QA.
- **Interactive** → present PR URL, change summary, review verdicts. Ask for final confirmation. Approve → set `sdd:test`. (lines 348–351) [PRESERVE]

### Phase 7: Child completion notification
Runs **only if** [PRESERVE]:
- Issue body matches multi-language parent regex (this is a child), AND
- Issue label just transitioned to `sdd:done` (typically after `/sdd test <child>`).

Steps:
1. Find parent number from `<!-- sdd:child-issue -->` block.
2. Find the **most recent** children comment on parent containing BOTH `<!-- sdd:children:output -->` and `<!-- /sdd:children:output -->`. None → warn + skip. Multiple → use last.
3. Update children comment (Section F): take existing body, replace this child's row with new status in narrative (NOT in shell). Write to `/tmp/sdd-children-output-<parent>.md`. `gh api .../issues/comments/<id> -X PATCH --field body=@<path>`.
4. Verify by re-read.
5. Check every child's actual label:
   - **All `sdd:done`** → post completion notification on parent (e.g. "All children done. Run /sdd test <parent>.") via `gh issue comment <parent> --body-file <path>`. No duplicate-prevention — each completion is a new comment.
   - **Not all done** → report remaining children. Skip-review mode → stop (outer auto-discovery picks remaining). Interactive → may ask which next. No comment posted in this branch. (lines 353–375) [PRESERVE]

[RETHINK: Phase 7 lives in `implement.md` but executes against post-`/sdd test` `sdd:done` state — it gets invoked via test stage / resume dispatcher when the child completes. Rewrite could move this to a dedicated atom called by both `implement` and `test` to clarify when it runs.]

---

## 5. TDD Step Pipeline (3-1..3-4)

### Per-step retry budget
**2 retries per step** (3 attempts total) before escalation. Each retry passes literal `"retry"` as `$3`. Atom self-fetches that step's review comment via Section C (marker `<!-- sdd:review:implement:step-<n> -->` on the **Issue**, not the PR — PR may not exist yet). Atom uses sorted findings (`critical → major → minor`); addresses every critical/major; minor is supporting context. Each atom's retry-resolution check verifies addressing before commit. [PRESERVE]

### SHA threading + test-evidence
- Orchestrator threads `<sha>` and `<test-evidence>` from step atom's return into `tdd_step_review` spawn prompt.
- `<test-evidence>` format: `TESTS: <p>/<t> FAILED: <f>` (substring extracted from `OK <STEP_TYPE> COMMIT: <sha> TESTS: ...`).
- `REFACTOR EMPTY` → `<sha>=EMPTY`, `<test-evidence>=NONE`. `tdd_step_review` returns `OK PASS` immediately (step 1 in atom).
- `E2E_SKIPPED` → step 2 (`tdd_step_review` spawn) entirely skipped. Orchestrator-side branching, NOT an instruction to the reviewer. [PRESERVE]

### Test-evidence posting (shared procedure)
Every step atom that produced a commit + test claim posts `<!-- sdd:test-evidence:step-<n> -->` via `_test_evidence.md`:
- Truncation: full ≤ 50k verbatim; else first 2k + `... [truncated middle] ...` + last 8k.
- Body: commit sha, reported counts, test command, fenced raw runner output.
- Section F duplicate-prevention; re-read verification on Step 5.
- Skipped for `OK REFACTOR EMPTY` and `OK E2E_SKIPPED`.
- Re-read empty after post → atom returns `FAIL: test evidence comment not found after posting (step-<n>)`. [PRESERVE]

### Step-review consistency checks (`tdd_step_review.md` step 5a) [PRESERVE — load-bearing]
Reviewer **cannot re-run tests**; verifies self-reported counts against the captured raw log:
- Red: `FAILED == 0` → `[critical] red-tests-did-not-fail`.
- Green/Refactor/E2E: `FAILED != 0` → `[critical] tests-not-green`.
- Refactor with no test-file changes but `<p>/<t>` drift from prior Green → `[critical] refactor-changed-test-counts`.
- Sanity: `<total> == 0` with non-empty commit → `[major] zero-tests-executed`.
- Raw-log cross-check: framework-agnostic (summary line, fail markers, framework banner, file paths). Count mismatch with `$5` → `[critical] test-evidence-mismatch`. Implausibly short log → `[major] test-evidence-implausible`. Red lacks failure indicator → `[critical] red-log-shows-no-failure`.
- Test-evidence comment missing (when commit ≠ EMPTY and $5 ≠ NONE) → `[major] test-evidence-log-missing`. **Important** [PRESERVE — from Reviewer A GAP-A1]: this finding is **recorded and the review continues**; reviewer does NOT early-return. Subsequent checks (step-criteria evaluation, etc.) still execute. A "fail fast" rewrite would silently lose post-detection criteria evaluations.
- Log present and authentic but summary line cannot be identified → `[minor] test-evidence-summary-unparseable`. [PRESERVE — from Reviewer A GAP-A2]: explicitly **non-blocking escape hatch** ("Do not block on this — runners differ widely"). A rewrite must preserve this rule_id so retry-mode parsers reading historical findings JSON still recognize it.
- Refactor count drift with no test-file changes → `[critical] refactor-changed-test-counts`. [PRESERVE — from Reviewer A GAP-A3]: **graceful fallback rule** — to verify the drift, search latest `<!-- sdd:review:implement:step-2 -->` block and parse `Tests` field from its body. If prior Green counts unavailable → **downgrade to `[major]`**. This preserves recovery when round-1 step-2 review was rotated out. A rewrite that ignores the downgrade would mis-classify the finding as critical when prior context is genuinely lost.

This is the **trust boundary** against an LLM work atom hallucinating "tests pass" without running them.

---

## 6. PR Creation (Phase 4 first-round + Phase 5 retry mode)

### First-round mode (Phase 4)
Triggered when `$3` empty AND no open PR for branch. Steps:
1. Preflight tier **Light**, items 1+2 (project conventions + commit style).
2. Re-run all tests → confirm pass; else `FAIL: tests fail before PR creation`.
3. `git push -u origin <branch>`.
4. Write PR body to `/tmp/sdd-pr-body-$1.md`. Body: `Refs #$1`, optional localized parent line (en `Parent Issue:`, ko `상위 Issue:`, ja `親Issue:`), change summary, Manual Test Checklist.
5. `gh pr create --title "<title>" --body-file /tmp/sdd-pr-body-$1.md`. Title per repo convention from `git log --oneline -20`.
6. Capture `<PR_NUM>` via `gh pr view --json number -q .number`.

Result: `OK PR: #N` or `OK PR: #N E2E_SKIPPED`. [PRESERVE]

### Existing PR handling (resume/defensive)
- Mode detection matrix:
  | `$3` | PR exists | Mode |
  |---|---|---|
  | empty | no | first-round |
  | empty | yes | **unhandled** — `gh pr create` would error (see RETHINK) |
  | `"retry"` | yes | retry |
  | `"retry"` | no | defensive `FAIL: retry mode requested but no open PR for branch $2` |
- [RETHINK]: no explicit "first-round but PR already exists" branch. Resume hitting this state would attempt to recreate the PR. Rewrite should detect existing PR in first-round and route to retry-like flow OR return a clearer error.

### Retry mode (Phase 5 rounds 2 + 3) [PRESERVE — v0.36 atom-side retry]
1. Verify branch + PR.
2. `git pull --ff-only origin <branch>` (continue if fails).
3. Read PR diff via `gh pr diff <PR_NUM>`.
4. **Self-fetch findings**:
   a. `<EXISTING_PR>` is `<PR_NUM>` for PR-scoped fetches.
   b. Section C with 3 SDD markers PR-scoped → sorted findings array.
   c. Fetch `/code-review` + `/security-review` inline PR comments via `gh api repos/<owner>/<repo>/pulls/<PR_NUM>/comments`. Filter to Skill-authored only:
      - body starts with 🔴 / 🟡 → `/code-review` (🟣 Pre-existing also present; see d)
      - body contains `Severity: High/Medium/Low` → `/security-review`
      - secondary author signal: `github-actions[bot]` (Actions mode)
   d. Translate by severity mapping (see Phase 5.1.2/5.1.3 above); append + re-sort. SDD-marker fetch FAIL → propagate; missing Skill comments NOT a failure. **🟣 Pre-existing handling** [PRESERVE — from Reviewer A GAP-A4]: `/code-review` may post 🟣 Pre-existing comments (issues that pre-date this PR). The orchestrator-side counting in Phase 5.1.2 already ignores 🟣 for verdict computation. The atom-side retry translation MUST also skip 🟣 entries — including them as `minor` findings would cause the work atom to waste cycles addressing pre-existing issues that the orchestrator already ignored. Filter mapping: 🔴 → critical, 🟡 → minor, **🟣 → skip**.
5. For each critical/major: decide fix kind (code defect / missing test / test defect / refactoring nit), apply, re-run all tests → pass. Use minor entries as same-file/line context.
6. Commit fix-ups: `fix: address review (round N) - <short summary>`. **No amend, no force-push.** [PRESERVE — load-bearing: preserves review history]
7. `git push -u origin <branch>` (regular).
8. Do NOT create new PR — existing auto-updates.

[PRESERVE — known limit]: Skill-comment filter is keyed to specific emojis/prefixes. New severity vocabulary (e.g. 🟠 Medium) falls through to "informational" until `_review_helpers.md` is updated. [IMPROVE: config block in `_review_helpers.md` defining the recognition patterns would centralize updates.]

[PRESERVE]: Idempotency across retry rounds — same Skill comment may surface multiple rounds (remains on PR). Each retry round is fresh evaluation; fixes from prior rounds cause the finding to no longer be reproducible in step 5 → natural deduplication.

---

## 7. PR Final Review Loop (Phase 5 — 3 rounds)

### Round structure (each N ∈ {1,2,3})
1. **5.N.1** — 3 SDD reviewers parallel (single Agent batch).
2. **5.N.2** — `/code-review` (serial after 5.N.1).
3. **5.N.3** — `/security-review` (serial after 5.N.2). Skipped if `sdd:review:shallow`.
4. **5.N.4** — Post tools-summary (observability).
5. **5.N.5** — Round decision.

[PRESERVE — load-bearing invariant]: the 5.N.2/5.N.3 serial-after-Agent ordering is enforced by the Skill tool's inability to share a parallel batch with Agent calls. Re-ordering breaks the orchestrator.

### Independent reviewer contexts
- The 3 SDD reviewers run with independent contexts — no cross-visibility of each other's verdicts. (`implement.md` line 381) [PRESERVE]
- Skill tools post inline PR comments (not findings JSON) — verdict combination logic in 5.N.2/5.N.3 reads them directly.

### Verdict combination logic [PRESERVE — load-bearing]
With both Skills (lines 238–240):

- **Round = FAIL if ANY of**:
  - Any SDD reviewer returned `OK FAIL PR: #N: <summary>`
  - `/code-review` produced 1+ 🔴 Important finding
  - `/security-review` produced 1+ High or Medium finding
- **Round = PASS only if ALL of**:
  - All 3 SDD reviewers returned `OK PASS PR: #N`
  - `/code-review` found no Important (Nit/none only, or skipped)
  - `/security-review` found no High/Medium (Low/none only, or skipped)

Skipped Skills do NOT make the round fail — they are neutral. `tools_skipped` tracking exists for observability so consumers know absence is by-design, not silent.

[RETHINK]: "skipped = neutral" is correct for `skill-unavailable`; for `shallow-label-skip` it's a deliberate trade-off (shallow Issues accept a weaker security check). Rewrite should document this rationale explicitly.

### Round decision table
| Round | Verdict | Next |
|---|---|---|
| 1 or 2 | PASS | Exit loop → Phase 6 |
| 1 or 2 | FAIL | `implement_pr` retry mode → Round N+1 |
| 3 | PASS | Exit loop → Phase 6 |
| 3 | FAIL | Phase 5.5 escalation |

Source: `implement.md` lines 297–299. [PRESERVE]

### Tools-summary comment (Step 5.N.4) [IMPROVE — observability]
Without this marker, an audit of "did this PR get scanned by /security-review?" cannot distinguish "no, skill disabled" from "yes, no findings." The marker captures the distinction. The rewrite should keep this pattern as a model for similar observability additions in other stages.

Updated in place across rounds (duplicate-prevention by marker) — latest overwrites prior. [PRESERVE — but Common Contracts §4 RETHINK on round preservation applies: round history is lost from GitHub.]

---

## 8. Skill Invocations

### Effort by depth (`/code-review` only — `/security-review` self-calibrates)
| Depth | `/code-review` effort |
|---|---|
| `default` | `high` |
| `deep` | `max` |
| `shallow` | `medium` |

Source: `implement.md` line 189 + `_review_helpers.md` Section A.3. [PRESERVE]

### Graceful skip protocol
- Skill unavailable (older Claude Code version, plugin disabled, semantic error) → log warning, skip, record `{"reason":"skill-unavailable"}`. Round verdict treats skipped as neutral. [PRESERVE]
- [RETHINK]: current code lumps "skill present but errored" with "skill absent". Recording the reason verbatim would improve observability.

### Where Skills are invoked
- `/code-review` and `/security-review` — **main session orchestrator only** (`implement.md` Phase 5.N.2 / 5.N.3). NOT in atoms.
- `/verify` — not invoked in implement stage (test stage may invoke). [PRESERVE]

[RETHINK per Common Contracts §13]: sub-agents CAN invoke Skills (R5 spike verified). Implement chose orchestrator-side because v0.36's main-session-token-savings strategy applied to *reading* review comments (atoms self-fetch). Skill invocation could move into a stage sub-agent (Arch B) to remove these calls from main entirely. Wall-clock penalty: Skills would run serially with SDD reviewers, not their current "serial-after-parallel" arrangement.

---

## 9. Branch + Commit Conventions

### Branch naming
- Single Issue: `feat/<feature-name>` (kebab-cased from title).
- Child Issue: `feat/<parent-feature>/<child-feature>`.
- **Repo override**: `implement_plan` inspects `git log --oneline -20` and follows existing convention if different. [PRESERVE — load-bearing for project conformance]

### Commit message style
| Atom | Commit prefix |
|---|---|
| `implement_red` | `test: <description> (Red)` |
| `implement_green` | `feat: <description> (Green)` |
| `implement_refactor` | `refactor: <description>` (skipped if empty) |
| `implement_e2e` | `test: e2e for <feature>` |
| `implement_pr` retry | `fix: address review (round N) - <short summary>` |

All atoms inspect `git log --oneline -20` to match repo convention. [PRESERVE]

### Hard rules across all atoms
- **No Claude as co-author** — `implement.md` Rules line 8 + every atom's Hard rules. [PRESERVE]
- **No force-push** — `implement_pr` retry mode forbids `--force` / `--force-with-lease`. [PRESERVE]
- **No `git commit --amend`** — retry mode appends new commits to preserve review history. [PRESERVE]
- **No `git push` from TDD step atoms** — only `implement_pr` pushes. Red/Green/Refactor/E2E all forbid push in Hard rules. [PRESERVE]

---

## 10. Edge Cases

### Parent Issue stops at Phase 1
Detected via `<!-- sdd:children:output -->` marker in Issue comments. Two paths based on skip-review `implement`: stop without asking (auto) vs prompt user (interactive). Either way, no stage work on parent — children take over. [PRESERVE]

### Resume from existing branch
- `implement_plan` step 3 detects existing branch and falls back to `git checkout` (no `-b`).
- TDD step atoms re-verify branch state but do NOT skip already-done steps — re-spawn blindly.
- [RETHINK: idempotency on TDD step pipeline. Rewrite could check for existing commits matching the step's commit-message convention and skip.]

### Resume from existing PR (Phase 4 with existing PR)
- See §6 Mode detection matrix — `$3` empty + PR exists is the unhandled gap. [RETHINK]

### Step exhaustion (Phase 3.X step 3)
- 2 retries consumed on red/green/refactor/e2e.
- skip-review `implement` set → auto-continue with unresolved findings carried forward to PR Final.
- Interactive → Continue / Pause / Stop. [PRESERVE]

### Round exhaustion (Phase 5 round 3 FAIL)
- → Phase 5.5 escalation gate.
- skip-review `pr` set → auto-continue to Phase 6.
- Interactive → Continue / Pause / Stop. [PRESERVE]

### `skip-review: implement` vs `:pr` vs `:qa`
| Setting | Affects |
|---|---|
| `skip-review: implement` | Phase 1 parent-stop (suppress prompt), Phase 2.2 plan gate, Phase 3 step exhaustion gate |
| `skip-review: pr` | Phase 5.5 escalation gate, Phase 6 final confirmation gate |
| `skip-review: qa` | Phase 6 auto-proceed inline to `commands/test.md` |

[PRESERVE]: independent dials. A user may set `implement` (trust planning/TDD) but require `pr` review (gate before QA).
[PRESERVE — load-bearing]: the key names (`implement`, `pr`, `qa`) are user-typed config tokens. Renaming any (e.g. `pr` → `pr-final`) is a breaking change for every user with an existing `.sdd-config`.
[RETHINK — for rewrite design]: naming is opaque — `pr` suggests it gates PR creation but actually gates final approval. Candidate rename `skip-review: pr-final` / `:implement-final`. Requires user-decision + dual-read shim. (Was [IMPROVE] in v1; corrected per Reviewer C TAG-C8.)

### Phase 7 child completion notification
- Runs at end of implement (or via test stage / resume dispatcher) when child reached `sdd:done`. Updates parent's children comment; posts completion notification when all done.
- `/sdd auto` / `/sdd batch`: in skip-review mode, stop after step 5 (no next-child prompt) — outer auto-discovery handles remaining. [PRESERVE]

### Test runner output anomalies
- Counts unobtainable → use `0`; reviewer flags via `[major] test-evidence-missing` or `[major] zero-tests-executed`.
- Truncation: 50k cutoff; reviewer's authenticity check uses summary line + framework markers — works across truncated logs. [PRESERVE]

### E2E framework absent
- `implement_e2e` step 2 detection (no artifact + no `test:e2e` script) → `OK E2E_SKIPPED` without commit/evidence.
- Orchestrator skips step-4 review (line 99).
- `implement_pr` flags `OK PR: #N E2E_SKIPPED` for downstream `/sdd test`. [PRESERVE]

### Atom-level FAIL vs review-verdict FAIL
- Atom error `FAIL: <reason>` from any atom → orchestrator stops at that phase.
- `OK FAIL: <summary>` from reviewer → counts toward round verdict, NOT a stop signal. [PRESERVE — same pattern as analyze]

### Adversarial-only FAIL escalation surface
- If only `implement_adversarial` FAILed (completeness + quality both PASS), log warning to user but still treat as FAIL. (`implement.md` line 182) [PRESERVE]

### Multiple children comments on parent (Phase 7 step 2)
- Multiple matches → use most recent (last). Zero matches → warn + skip update (no error). [PRESERVE]

### Issue Validation gate
- Before any work, validate `$1` per Common Contracts §10. PR → stop with no state changes. [PRESERVE]

---

## 11. Cross-Stage Invariants

Downstream (`test`) and Phase 7 parent path assume:

1. **PR exists** before `test` stage begins. `test_work` reads PR diff, expects `Refs #$1`. Phase 4 guarantees this; Phase 6 label transition to `sdd:test` conditional on PR creation. [PRESERVE — load-bearing]
2. **`<!-- sdd:implement:plan -->` exists** before TDD steps run. Each step atom reads it. Phase 2 must complete before Phase 3 starts. [PRESERVE]
3. **Parent path needs ALL children `sdd:done`** before parent advances to test. Phase 7 step 5 explicitly checks each child's label. Parent's own pipeline waits at `sdd:implement` until then. (Common Contracts §1 parent-pause invariant.) [PRESERVE — load-bearing]
4. **Design's File Structure section drives target dir** for `implement_plan` and each TDD step atom's preflight (Section B item 4). [PRESERVE]
5. **Design's Testability section drives mock/stub strategy** in `implement_plan` step 4 (test plan), verified in PR Final completeness (cross-stage testability adherence). [PRESERVE]
6. **Issue type from analyze** (read indirectly via design) affects test plan classification (e.g. bug fix → regression tests). [PRESERVE]
7. **Commit shas are queryable** by `tdd_step_review` via `git show $4`. Branch must remain intact through Phase 3. Force-push would invalidate — hence the no-force-push hard rule. [PRESERVE]
8. **Findings JSON schema** present inside every review comment (step reviews on Issue, PR Final on PR, tools-summary on PR). Retry-mode Section C self-fetch parses these; `implement_pr` retry's inline-PR-comment translation produces the same shape. [PRESERVE]
9. **Test-evidence comments overwrite per-step on retry** (duplicate-prevention). Prior round's evidence is lost — only latest queryable. (Common Contracts §4 RETHINK on round preservation applies.) [PRESERVE]
10. **`sdd:test` set only after successful Phase 5/5.5/6 flow.** Test stage uses this label as entry signal. [PRESERVE]
11. **Children comment on parent reflects current state of all children.** Phase 7 keeps it updated; resume dispatcher and `/sdd auto` rely on it for next-child discovery. [PRESERVE]
12. **Branch name persists across retries.** Phase 2.1 captures it; Phase 3/4/5 reference it. If deleted between phases, recovery path is `/sdd resume <N>` reading branch from PR or Issue context. [PRESERVE]
13. **`/code-review` and `/security-review` inline PR comments are the sole sources of Skill verdicts.** No separate findings JSON; retry mode translates on the fly. [PRESERVE]

---

## Cross-references
- Common Contracts (markers, retry, bash rules, comment posting, Skill availability) → `spec/00-common-contracts.md`
- Skip-review semantics → `spec/01-config.md` §2
- Depth labels / model table / `/code-review` effort → `spec/01-config.md` §3
- Multilingual parent regex → `spec/02-multilingual.md` §3
- Stage Inputs/Outputs format reference → `spec/stage/analyze.md`
- Per-step shared procedure → `plugins/sdd-plugin/skills/sdd/commands/atoms/_test_evidence.md`
- Per-step / PR-Final criteria → `plugins/sdd-plugin/skills/sdd/commands/ai-review-implement-*.md`
