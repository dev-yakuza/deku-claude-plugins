# Stage: Test

Testing and QA stage (Stage 4). QA verification + integration E2E for parent Issues. Unit/UI tests and E2E tests for single/child Issues were already written in Stage 3 (implement); this stage validates them, adds the QA gate, and triggers final label transition to `sdd:done`.

Sources: `commands/test.md`, `commands/atoms/test_work.md`, `commands/atoms/test_review.md`, `commands/atoms/test_adversarial.md`, `commands/atoms/parent_integration_review.md`, `commands/ai-review-test-{completeness,quality,adversarial}.md`, `commands/ai-review-parent-integration.md`, `commands/atoms/_test_evidence.md`.

---

## 1. Stage Inputs

### Entry conditions
- `$1` — Issue number passed by `/sdd test $1`, `/sdd resume`, or auto-proceed from `implement`. Validated as Issue (not PR) per Common Contracts §10. (`test.md` lines 11–13) [PRESERVE]
- Entry label: `sdd:test` (set by implement stage when its PR Final review passed). [PRESERVE]
- For **single/child Issue path**: an open PR linked to `$1` via `Refs #$1` (created by `implement_pr` in Stage 3). (`test_work.md` lines 49–54) [PRESERVE]
- For **parent Issue path**: ALL child Issues listed in `<!-- sdd:children:output -->` must already have label `sdd:done`. Verified by orchestrator Phase 1 and again by work atom mode detection. (`test.md` lines 44–48; `test_work.md` lines 24–25) [PRESERVE]

### Environmental dependencies
- `gh` CLI authenticated for current repo. [PRESERVE]
- `.github/.sdd-lang` (optional) — read by `test_work` for template language. (`test_work.md` step 7) [PRESERVE]
- `.github/.sdd-config` (optional) — read for `skip-review: qa` semantics (Phase 2.5 escalation, Phase 3 user review). (`test.md` Phase 2.5 and 3.2) [PRESERVE]
- Issue labels — read in Phase 0 for depth detection (`sdd:review:deep` / `sdd:review:shallow`). (`test.md` lines 19–23) [PRESERVE]
- Repo test infrastructure detection (test framework, runner, directory layout). (`test_work.md` lines 64, 150–154) [PRESERVE]

### Upstream prerequisites (from Stage 3)
- PR exists on `gh pr list --search "Refs #$1"` for single/child path. [PRESERVE]
- `<!-- sdd:children:output -->` exists on the Issue for parent path. [PRESERVE]
- `<!-- sdd:test-evidence:step-<n> -->` comments may be present from implement stage's TDD steps — used by reviewers for cross-stage authenticity checks. (Common Contracts §4; `_test_evidence.md` lines 1–8) [PRESERVE]

### Depth
- Depth detection identical to other stages (Phase 0). Selects model per atom. (`test.md` lines 19–33) [PRESERVE]

---

## 2. Stage Outputs

### Markers posted
- `<!-- sdd:test:output -->` on the Issue — QA checklist + test results. Posted by `test_work` (both paths). (`test_work.md` lines 92, 191) [PRESERVE]
- `<!-- sdd:review:test:completeness -->` — single/child path: on the **PR**; parent path: on the **Issue**. Posted by `test_review` (role=completeness). (`test_review.md` lines 42–54) [PRESERVE]
- `<!-- sdd:review:test:quality -->` — same dual-location rule. Posted by `test_review` (role=quality). [PRESERVE]
- `<!-- sdd:review:test:adversarial -->` — same dual-location rule. Posted by `test_adversarial`. (`test_adversarial.md` lines 40–52) [PRESERVE]
- `<!-- sdd:review:parent -->` (parent path only) — on the **parent Issue**. Posted by `parent_integration_review`. (`parent_integration_review.md` lines 52–62) [PRESERVE]
- `<!-- sdd:findings:json -->` … `<!-- /sdd:findings:json -->` block inside every review comment per Common Contracts §5. [PRESERVE]

### Labels transitioned to
- `sdd:done` — at Phase 4 when all QA items pass (or auto-approved via `skip-review: qa`). Concurrent with `gh issue close $1`. (`test.md` Phase 4, lines 211–215) [PRESERVE]
- `sdd:test` is removed at the same transition. (`test.md` line 214) [PRESERVE]

### State changes
- For **single/child** path that transitioned to `sdd:done`: if the Issue is a child (multi-language `Parent|상위|親 Issue: #N` regex matched in body), the parent's `<!-- sdd:children:output -->` table row is updated to mark the child done. (Phase 5; reuses `implement.md` Phase 7 logic.) [PRESERVE]
- For **parent** path that transitioned to `sdd:done`: pipeline complete. No parent-of-parent in SDD model. [PRESERVE]
- `gh issue close $1` — closes the Issue. (`test.md` line 215) [PRESERVE]

### Optional side effects (parent path)
- Integration test PR may be created on a `test/<parent-feature-name>` branch (when `OK PARENT INTEGRATION_PR`). The PR carries cross-child E2E coverage. (`test_work.md` lines 158–173) [PRESERVE]
- Body of the integration PR is written via the Write tool to `/tmp/sdd-test-parent-<Issue>.md` and passed with `--body-file` (no heredocs). [PRESERVE — Bash safety per Common Contracts §8/§9]

### Side effects NOT produced by test stage
- Test stage does NOT modify production code on the implementation PR. Code changes for failing QA flow back to `implement` (Phase 4.1). [PRESERVE]
- Test stage does NOT merge the PR; merge is a human decision after `sdd:done`. [PRESERVE]

---

## 3. Atom Inventory

| Atom | Role | Model (default / deep / shallow) | Key responsibility |
|---|---|---|---|
| `test_work` | Producer | opus / opus / opus | Detect mode (single/child vs parent), validate or create tests, produce QA checklist, post `<!-- sdd:test:output -->`. Returns one of four `OK` variants or `FAIL`. |
| `test_review` (role=`completeness`) | Reviewer | sonnet / opus / sonnet | Cross-stage coverage: do tests cover analyze/design requirements + DoD? Posts on PR (single/child) or Issue (parent). |
| `test_review` (role=`quality`) | Reviewer | sonnet / opus / sonnet | Assertion quality, flakiness risk, coverage depth, regression protection, manual QA checklist quality. |
| `test_adversarial` | Reviewer (refuter) | opus / opus / sonnet | REFUTE the test output. Mentally mutate impl, find tests that pass with no-op or broken code. Must find ≥1 weakness or justify why none. |
| `parent_integration_review` | Reviewer (parent only) | opus / opus / sonnet | Cross-child synthesis at parent Issue level. Reads each child's analyze/design/implement review findings + interface contract files. Posts `<!-- sdd:review:parent -->`. |

Model table source: `test.md` lines 27–33. Canonical in `_review_helpers.md` Section A.2. [PRESERVE]

All five atoms are single-subagent terminal workers: MUST NOT spawn subagents, MUST NOT call Agent or Skill tool. (`test_work.md` lines 3, 226–229; `test_review.md` lines 3, 76; `test_adversarial.md` lines 3, 73; `parent_integration_review.md` lines 3, 107) [PRESERVE — architectural invariant per Common Contracts §12]

### Shared procedure used by upstream stage
`commands/atoms/_test_evidence.md` is **not an atom**. It is a shared procedure called by each `implement_<step>` work atom in Stage 3 to post `<!-- sdd:test-evidence:step-<n> -->`. The test stage does **not** call it directly, but its outputs are read by `test_review` / `test_adversarial` during cross-stage authenticity checks. (`_test_evidence.md` lines 1–8) [PRESERVE]

---

## 4. Phase-by-Phase Behavior

### Phase 0: Depth label detection
- Read `gh issue view $1 --json labels --jq '[.labels[].name]'`. (`test.md` line 21) [PRESERVE]
- Resolve depth (`default` / `deep` / `shallow`); selects models per the Phase 0 table. (`test.md` lines 25–33) [PRESERVE]
- `test_work` is always `opus` regardless of depth (the producer atom does the most consequential reasoning). [PRESERVE]

### Phase 1: Determine Issue type
1. Fetch comments and search for `<!-- sdd:children:output -->`. (`test.md` lines 38–42) [PRESERVE]
2. **Parent Issue path** (children comment present):
   - Read child Issue numbers from the children comment.
   - For each child, check its label.
   - If any child is NOT `sdd:done` → report which children are incomplete; ask user to complete them first; stop. (`test.md` lines 44–48) [PRESERVE]
   - If ALL children are `sdd:done` → proceed to Phase 2 with `path=PARENT`. [PRESERVE]
3. **Single/Child Issue path** (no children comment) → proceed to Phase 2 with `path=SINGLE` (the literal kind is determined later by `test_work`'s `OK` variant). [PRESERVE]

### Phase 2: Test + AI Review Loop (max 3 rounds)
Each round = 1 work atom → parallel reviewers → verdict combine → round decision. (`test.md` line 53) [PRESERVE]

**Round 1 — Step 2.1.1 (work atom spawn)**:
- `subagent_type: general-purpose`, `model: opus`, `description: test work for #$1`.
- Prompt instructs subagent to read `test_work.md` and execute. (`test.md` lines 57–65) [PRESERVE]
- Parse `>>> RESULT <<<` line. Four success variants plus `FAIL`:
  - `FAIL: <reason>` → report failure, stop. **Special case**: if reason starts with `no E2E test setup detected; recommended framework:` → surface to user, ask framework choice, **re-spawn** the work atom with the chosen framework noted in prompt as `Framework: <name>`. (`test.md` lines 67; `test_work.md` lines 153–154) [PRESERVE]
  - `OK SINGLE PR: #N` → single/child path; existing PR validated. Remember `path=SINGLE`. [PRESERVE]
  - `OK PARENT INTEGRATION_PR: #M` → parent path; integration test PR created. Remember `path=PARENT, integration_pr=#M`. [PRESERVE]
  - `OK PARENT NO_INTEGRATION` → parent path; children's tests sufficient. Remember `path=PARENT, integration_pr=null`. [PRESERVE]

**Round 1 — Step 2.1.2 (parallel reviewer spawn)**:
- **3 Agent calls** in a single message for single/child path; **4 Agent calls** for parent path (the fourth being `parent_integration_review`). (`test.md` lines 72–108) [PRESERVE]
- Agent A: `test_review.md` role=`completeness`.
- Agent B: `test_review.md` role=`quality`.
- Agent C: `test_adversarial.md`.
- Agent D (parent path only): `parent_integration_review.md`.
- All reviewers operate independently per Common Contracts §12 — they post to PR (single/child) or Issue (parent) and return `>>> RESULT <<<`. [PRESERVE]

**Round 1 — Step 2.1.3 (round decision)**:
- Any `FAIL: <reason>` (atom error) → report, stop. (`test.md` line 111) [PRESERVE]
- All `OK PASS` → exit loop → Phase 2.7 (single/child) or Phase 3 (parent skips 2.7). (line 112) [PRESERVE]
- Any `OK FAIL: <summary>` → reviews failed; combine summaries; check adversarial-only escalation; decide retry. [PRESERVE]
- Reviews failed, round < 3 → spawn next round's work atom in **retry mode** (`$2 = "retry"`). The atom self-fetches reviews per `_review_helpers.md` Section C. Orchestrator does NOT fetch JSON itself. (`test.md` lines 119, 124–129) [PRESERVE — main-session token savings, v0.36]
- Reviews failed, round == 3 → exit loop → Phase 2.5. (line 120) [PRESERVE]

**Rounds 2 & 3 (retry mode)**:
- Same as Round 1 Steps 2.1.1–2.1.3, but `$2 = "retry"` is passed to the work atom. (`test.md` line 124) [PRESERVE]
- The atom self-fetches markers per path:
  - **Single/Child path**: 3 stage markers (`sdd:review:test:completeness`, `:quality`, `:adversarial`).
  - **Parent path**: same 3 stage markers + `<!-- sdd:review:parent -->`. (`test_work.md` lines 32–34; `test.md` line 128) [PRESERVE]
- Atom addresses every `critical` and `major` finding; reads `minor` as supporting context. [PRESERVE]

### Phase 2.5: Round 3 Escalation Gate
Triggered only when round 3 also failed. (`test.md` line 134) [PRESERVE]

1. Render summary listing remaining `critical` and `major` findings with role label. [PRESERVE]
2. Branch on skip-review:
   - `qa` is in skip-review (`/sdd auto` / `/sdd batch`):
     - Log to Issue/PR comment: "⚠ Round 3 escalation: tests still failing after 3 rounds, but `skip-review: qa` is set — auto-continuing to Phase 2.7. Findings remain on the Issue/PR for human follow-up."
     - Proceed to **Phase 2.7** without prompting. Do NOT call `AskUserQuestion`. (`test.md` lines 137–139) [PRESERVE]
   - Interactive (no skip-review):
     - Ask user: Continue / Pause / Stop. (lines 140–144) [PRESERVE]
     - Continue → Phase 2.7.
     - Pause → orchestrator stops; resume via `/sdd resume <N>` after manual fixes.
     - Stop → exit cleanly.

### Phase 2.7: Behavioral verification (`/verify` Skill)
Runs **only on single/child path**. Parent path skips entirely (children's verify results were exercised in their own test stages; parent uses E2E integration PR for boundary checks). (`test.md` lines 146–148) [PRESERVE]

- **Skip on shallow**: if `sdd:review:shallow` label is set on the Issue, skip 2.7. (`test.md` line 150) [PRESERVE]
- **Graceful skip on unavailability**: if `/verify` Skill is unavailable (Claude Code v2.1.145 or earlier, Skill disabled, or no app-launch capability detected for the project type) → log warning, proceed to Phase 3 without behavioral verification. (`test.md` lines 153–154) [PRESERVE]
- Invocation: via Skill tool from the orchestrator main session. (`/verify` operates the project's app and reports what it observed.) [PRESERVE]
- Map `/verify` output to SDD verdict:
  - "feature works as expected" → record as PASS evidence for Phase 3 context. [PRESERVE]
  - "feature does not work" or "crash/error observed" → record as FAIL evidence; surface in Phase 3 user context. [PRESERVE]
- **Non-blocking**: `/verify` result is *additional context* for Phase 3's user-or-skip-review decision. It does NOT by itself decide PASS/FAIL. Manual QA (or `skip-review: qa` auto-approval) is the final gate. (`test.md` line 162) [PRESERVE]
- Recorded in the self-review trace section of the test output comment (e.g. `- [x] /verify ran: feature launches and matches description` or `- [ ] /verify reported: error on login screen — see transcript`). (`test.md` lines 166–174) [PRESERVE]

[RETHINK: graceful-skip currently silently downgrades coverage. Consider surfacing skip explicitly in the `tools_skipped` array of the findings JSON for auditability, with `reason: "skill-unavailable" | "shallow-label-skip"`. Already in Common Contracts §5 schema — wire it through.]

### Phase 3: User Review + Manual QA
Requires main-session interaction with the user, unless `qa` is in skip-review. (`test.md` line 178) [PRESERVE]

**3.1 — User-facing context**:
- Present:
  - Test work atom's result (path, PR numbers, integration PR if any).
  - Review verdicts (PASS/FAIL with summaries).
  - For parent path: `parent_integration_review`'s summary, especially any cross-stage gaps surfaced.
  - **Phase 2.7 `/verify` result** (single/child only) — whether the app launched and the feature worked.
  - Link to the Issue's test output comment for the full QA checklist. (`test.md` lines 182–187) [PRESERVE]
- If work atom flagged "E2E was skipped in Stage 3" for single/child path:
  - `qa` in skip-review → log auto-continue without asking; the gap is documented on Issue/PR for human follow-up. (`test.md` line 190) [PRESERVE]
  - Interactive → ask user whether to add E2E tests now (push to PR branch) or proceed without. (`test.md` line 191) [PRESERVE]

**3.2 — skip-review check**:
- **`qa` in skip-review**: log "User review skipped (skip-review: qa)". Auto-approve test results + QA checklist. Skip to Phase 4. (`test.md` lines 196–198) [PRESERVE]
- **`qa` NOT in skip-review**:
  - User may add/remove/modify QA checklist items by editing the Issue comment directly. (line 200) [PRESERVE]
  - **Manual QA (step 4-3)**: ask user to perform manual QA based on the approved checklist and report pass/fail per item. Wait for response. (line 203) [PRESERVE]

### Phase 4: Results Review (step 4-4)
Based on user's manual QA report (or auto-approval under skip-review): (`test.md` lines 207–215) [PRESERVE]

1. **Any QA item failed** → analyze cause with user, route back to Stage 3 (`/sdd implement $1`) for a TDD bug-fix cycle. Stop this orchestrator. [PRESERVE]
2. **All tests pass** → atomic label transition:
   ```bash
   gh issue edit $1 --remove-label "sdd:test" --add-label "sdd:done"
   gh issue close $1
   ```
   (Two simple Bash calls per §8.) [PRESERVE]

### Phase 5: Child completion notification (if this Issue is a child)
Same logic as `implement.md` Phase 7. When a child Issue (detected via multi-language regex `(Parent|상위 |親)Issue: #<n>` per Common Definitions → Parent/Child Issue Detection) just transitioned to `sdd:done`: (`test.md` lines 219–221) [PRESERVE]

1. Update the parent's `<!-- sdd:children:output -->` table row to mark the child done.
2. Check whether ALL children are now done.
3. Notify the user on the parent Issue accordingly (multilingual notice).
4. Detailed steps deferred to `implement.md` Phase 7. [PRESERVE — single source of truth]

---

## 5. Three Paths Compared

The test stage routes to one of three paths, determined by `test_work`'s return value:

| | Single/Child | Parent (with integration) | Parent (no integration) |
|---|---|---|---|
| Work atom return | `OK SINGLE PR: #N` | `OK PARENT INTEGRATION_PR: #M` | `OK PARENT NO_INTEGRATION` |
| Reviewers spawned | 3 (completeness/quality/adversarial) | 4 (+`parent_integration_review`) | 4 (+`parent_integration_review`) |
| Review comment location | On the implementation PR (#N) | On the parent Issue | On the parent Issue |
| Parent integration review location | n/a | Parent Issue (`<!-- sdd:review:parent -->`) | Parent Issue (`<!-- sdd:review:parent -->`) |
| Phase 2.7 (`/verify`) | Runs (unless shallow/unavailable) | Skipped | Skipped |
| Manual QA checklist scope | Single feature on PR #N | Cross-child + integration PR #M | Cross-child + per-child manual items |
| New PR created? | No (uses Stage 3's PR) | Yes (`test/<parent-feature-name>`) | No |
| Phase 5 (child notify) | If Issue body has parent ref | n/a (parent has no parent) | n/a |

Source: `test.md` lines 67–70, 100–108; `test_work.md` lines 137–195. [PRESERVE]

### Why review location varies by path
- **Single/Child path**: the focus of the review is the actual PR diff and its test files. Posting reviewer comments on the PR keeps them adjacent to the code under review. (`test_review.md` lines 43–48; `test_adversarial.md` lines 41–46) [PRESERVE]
- **Parent path**: no single PR encompasses the parent's scope (each child has its own). Reviews aggregate cross-child state, so they live on the parent Issue. (`test_review.md` lines 49–54) [PRESERVE]

[RETHINK: dual-location logic is the most error-prone part of test stage. Path detection lives in 3 places (orchestrator Phase 1, work atom Mode detection, each reviewer Step 3). Consider passing `path` explicitly via the spawn prompt instead of re-detecting in each atom — would tighten the contract.]

---

## 6. `/verify` Skill (Phase 2.7)

**Purpose**: complement AI review (which checks code) and manual QA (which checks user perception) with a third lens — "does the app actually run and behave as expected?" (`test.md` line 152) [PRESERVE]

### Scope
- Runs only on **single/child path** at Phase 2.7. [PRESERVE]
- Skipped on **parent path** (parent uses children's verify results indirectly through E2E integration PR boundary tests). [PRESERVE]
- Skipped on **`sdd:review:shallow`** label (low-confidence runs). [PRESERVE]

### Graceful unavailability
The `/verify` Skill may be unavailable because:
- Claude Code v2.1.145 or earlier (no Skill tool). [PRESERVE]
- Skill disabled in user/project config. [PRESERVE]
- Skill detects no app-launch capability for the project type (e.g. pure library). [PRESERVE]

In any of these cases, the orchestrator logs a warning and proceeds to Phase 3. The downgrade is non-blocking. [PRESERVE]

### Output interpretation
`/verify` is transcript-based — it reports what it observed running the app. Mapping:
| `/verify` says | Recorded as |
|---|---|
| "feature works as expected" | PASS evidence for Phase 3 |
| "feature does not work" / "crash" / "error observed" | FAIL evidence for Phase 3 |

This evidence is *added to* the Phase 3 user context. It does NOT itself decide PASS/FAIL — manual QA (or `skip-review: qa` auto-approval) is the final gate. (`test.md` line 162) [PRESERVE]

### Self-review trace record
Result is recorded in the `<details>` self-review trace block of `<!-- sdd:test:output -->`. Example checkbox states: (`test.md` lines 166–174) [PRESERVE]
- `[x] /verify ran: feature launches and matches description`
- `[ ] /verify reported: error on login screen — see transcript`

---

## 7. Manual QA (Phase 3)

### Checklist source
The work atom posts the QA checklist inside `<!-- sdd:test:output -->`. The checklist is structured into three subsections: (`test_work.md` lines 73–76, 116–122) [PRESERVE]
- **Automated**: items already verified by tests in the PR.
- **Manual**: items requiring human verification (UI behavior, visual states, locale-dependent flows).
- **Regression**: items targeting prior fragility areas.

### User editing
In interactive mode (no `skip-review: qa`), the user MAY add/remove/modify QA checklist items by editing the comment directly on GitHub. The work atom does not re-post; the orchestrator reads the latest comment state before Phase 4. (`test.md` line 200) [PRESERVE]

### Auto-approve under skip-review
If `qa` is in `.github/.sdd-config`'s `skip-review` list:
- The user-review gate is bypassed in Phase 3.2 (log "User review skipped (skip-review: qa)"). [PRESERVE]
- The Phase 2.5 escalation gate also auto-continues. [PRESERVE]
- The Phase 3.1 "E2E was skipped in Stage 3" prompt also auto-continues. [PRESERVE]
- The user must rely on the AI reviewers + `/verify` evidence + the QA checklist as recorded on the Issue. [PRESERVE]

[PRESERVE — AI review (Phase 2) always runs even with `skip-review: qa`. Skip-review only bypasses **user gates**, not AI reviewers, per `01-config.md` §2.]

### QA failure → Stage 3 loop-back
If any manual QA item fails:
1. Orchestrator analyzes cause with user (no automation here — pure conversation). [PRESERVE]
2. User invokes `/sdd implement $1` to enter a TDD bug-fix cycle in Stage 3. [PRESERVE]
3. Current orchestrator stops. Label remains `sdd:test`. [PRESERVE]
4. On next entry to test stage, Phase 1 will find the (updated) PR and re-run reviews. [PRESERVE]

[RETHINK: there is no explicit "test stage re-entry" signal — the user implicitly restarts via `/sdd implement`. Consider whether a `sdd:test:retry` marker would help auto-resume after the implement-fix-cycle finishes.]

---

## 8. Test Evidence

### Source: `_test_evidence.md` (shared procedure)
This is **not an atom** and **not invoked by the test stage**. It is a shared procedure called from `implement_<step>` work atoms in Stage 3 to post raw test runner output as a verifiable evidence comment. (`_test_evidence.md` lines 1–8) [PRESERVE]

### Marker
- `<!-- sdd:test-evidence:step-<n> -->` where `<n>` ∈ {1=Red, 2=Green, 3=Refactor, 4=E2E}. (`_test_evidence.md` line 25) [PRESERVE]
- Posted on the **Issue** (not the PR) for cross-step accessibility. [PRESERVE]
- Latest-only via duplicate-prevention pattern (Common Contracts §9). Stale evidence from prior round MUST be overwritten or the consistency check fails. (`_test_evidence.md` lines 113–115) [PRESERVE]

### Content
- Step number, commit SHA, reported counts (`TESTS: <p>/<t> FAILED: <f>`), test command, raw runner output. [PRESERVE]
- Log excerpt rules: if full output ≤ 50,000 chars → verbatim; else first 2,000 chars + `... [truncated middle] ...` + last 8,000 chars. (`_test_evidence.md` lines 33–40) [PRESERVE]
- ANSI-free, line-breaks preserved, no paraphrasing — reviewer authenticity check relies on framework-specific output patterns. [PRESERVE]

### Skip conditions (in caller)
- `implement_red` — always posts. [PRESERVE]
- `implement_green` — always posts. [PRESERVE]
- `implement_refactor` — skip if step returned `OK REFACTOR EMPTY`. [PRESERVE]
- `implement_e2e` — skip if step returned `OK E2E_SKIPPED`. [PRESERVE]

### Read by test stage atoms
- `test_review` (both roles) and `test_adversarial` MAY Read the test-evidence comments via the codebase exploration budget. They verify whether the implement-stage's claimed test counts are consistent with the captured runner output. (`ai-review-test-quality.md` and `ai-review-test-adversarial.md` mention coverage authenticity checks.) [PRESERVE]
- `parent_integration_review` reads each child's structured findings JSON; test-evidence is secondary. [PRESERVE]

[IMPROVE: test stage does not currently *require* test-evidence comments to exist. A missing or stale evidence comment is reviewer-discretionary. Consider hard-gating: if `<!-- sdd:test-evidence:step-<n> -->` is missing for any committed step, `test_work` returns FAIL until implement re-posts. Would catch silent E2E skips and stale-evidence pollution.]

---

## 9. Test Framework Detection

### Trigger
- **Parent path only**, at `test_work` step 4-0 (test setup detection). (`test_work.md` lines 149–154) [PRESERVE]
- Single/child path expects an existing framework (Stage 3's implement_e2e already used one). If single/child has no framework, that gap is surfaced via the "E2E was skipped in Stage 3" flag, not via this detection. [PRESERVE]

### Detection signals
- Framework type (Jest, Vitest, Pytest, Go test, Playwright, Cypress, etc.). [PRESERVE]
- Test directory layout (`tests/`, `__tests__/`, `e2e/`). [PRESERVE]
- Test run command (from `package.json` scripts, Makefile, etc.). [PRESERVE]
- Test configuration files (`jest.config.*`, `pytest.ini`, `playwright.config.*`, etc.). [PRESERVE]

### Failure mode: no E2E setup
If no E2E setup is found:
1. `test_work` returns `FAIL: no E2E test setup detected; recommended framework: <name>; user confirmation required`. (`test_work.md` line 154) [PRESERVE]
2. Orchestrator detects the special prefix in the FAIL reason. (`test.md` line 67) [PRESERVE]
3. Orchestrator surfaces the recommendation to the user, asks for framework choice. [PRESERVE]
4. On user confirmation, orchestrator **re-spawns** `test_work` with the framework choice noted in the prompt as `Framework: <name>`. (`test.md` line 67) [PRESERVE]
5. Re-spawned atom uses the chosen framework to write integration tests. [PRESERVE]

[RETHINK: framework choice is currently passed only via prompt text — there is no formal `$3` slot. Consider extending the atom signature (`test_work $1 $2 $3`) where `$3 = "framework=<name>"` to make the contract explicit. Currently relies on the atom's prompt-parsing discipline.]

---

## 10. Edge Cases

### E2E was skipped in implement (single/child)
- Stage 3's `implement_e2e` may return `OK E2E_SKIPPED` when no E2E setup existed in the repo. (Common Contracts §6) [PRESERVE]
- Stage 3's `implement_pr` propagates this as `OK PR: #N E2E_SKIPPED`. [PRESERVE]
- `test_work` Step 4 in Stage 4 detects this flag and includes it in the Issue test output. (`test_work.md` line 71) [PRESERVE]
- In Phase 3.1, orchestrator surfaces this to the user:
  - `skip-review: qa` → auto-continue without E2E. Gap is documented for human follow-up. [PRESERVE]
  - Interactive → ask user whether to add E2E now (push to PR branch) or proceed without. [PRESERVE]

### `OK PARENT INTEGRATION_PR` vs `OK PARENT NO_INTEGRATION`
- `INTEGRATION_PR: #M`: cross-child integration test PR was created. Parent now has TWO outputs to review — the children's already-merged tests AND this new integration PR. (`test_work.md` lines 156–173) [PRESERVE]
- `NO_INTEGRATION`: children's tests already cover all integration scenarios (verified by reading children's PRs + design output). No new PR. Rationale documented in `<!-- sdd:test:output -->`. (`test_work.md` line 174) [PRESERVE]
- Both variants spawn the same 4 reviewers. `parent_integration_review` adjusts its codebase exploration based on whether an integration PR exists. [PRESERVE]

### Parent has incomplete children
- Detected at Phase 1 by orchestrator AND re-checked by `test_work` step (Mode detection). [PRESERVE]
- Orchestrator path: reports which children are incomplete; asks user to complete them; stops. (`test.md` lines 45–47) [PRESERVE]
- Atom path (defensive): returns `FAIL: parent has incomplete children: #X, #Y, ...`. (`test_work.md` line 25) [PRESERVE]

[IMPROVE: double-check at orchestrator + atom level is defensive but duplicative. Consider single source of truth via a helper in `_review_helpers.md`.]

### Adversarial-only FAIL in Phase 2 round
- If `OK FAIL` came only from `test_adversarial` (completeness=PASS, quality=PASS, adversarial=FAIL):
- Log to user: "⚠ Adversarial reviewer alone identified critical/major issues. Other reviewers passed. Surfacing for user awareness." [PRESERVE]
- Round still counts as FAIL — orchestrator proceeds to retry (or Phase 2.5 if round 3). (`test.md` line 114) [PRESERVE]

### `/verify` reports failure but manual QA passes
- Phase 2.7 records FAIL evidence but does not block. [PRESERVE]
- In Phase 3, user sees both the `/verify` FAIL and decides manual QA outcome. [PRESERVE]
- User may override `/verify` (e.g. environment-specific issue) or treat it as authoritative (route back to implement). [PRESERVE]

### QA failure → back to implement
- Phase 4 step 1: route back via `/sdd implement $1` for TDD bug-fix cycle. Stops orchestrator without changing label. [PRESERVE]
- On next test stage entry, Phase 1 finds the (now-updated) PR and re-runs reviews from scratch. [PRESERVE]
- The 3-round AI review limit resets on re-entry (not a continuation of the prior loop). [PRESERVE]

### Child completion notification (Phase 5)
- When a child Issue transitions to `sdd:done`, Phase 5 updates parent's `<!-- sdd:children:output -->` table row. [PRESERVE]
- Parent reference detected via multilingual regex `(Parent|상위 |親)Issue: #<n>` per Common Contracts → Multilingual §3. [PRESERVE]
- Notification body language matches the parent's language detection (Common Contracts → Language Detection). [PRESERVE]
- If ALL children are now done, notify parent: "All children complete; parent ready for `/sdd test #<parent>`." (Specific phrasing varies by language; multilingual templates in `templates/{lang}/...`.) [PRESERVE]
- Defers to `implement.md` Phase 7 for the verbatim implementation. [PRESERVE]

### Atom-level FAIL during reviews
- `test_review` and `test_adversarial` return `FAIL: <reason>` if test output is missing from the Issue. (`test_review.md` line 27; `test_adversarial.md` line 26) [PRESERVE]
- `parent_integration_review` returns `FAIL: parent has no children comment on Issue #$1` if `<!-- sdd:children:output -->` is absent (unexpected — orchestrator already validated). (`parent_integration_review.md` line 25) [PRESERVE]
- Orchestrator stops on any atom-level FAIL. [PRESERVE]

### Test stage on a PR (not Issue)
- Caught by Common Contracts §10 Issue Validation. Orchestrator reports error and stops with no state changes. (`test.md` line 13) [PRESERVE]

---

## 11. Cross-Stage Invariants

Upstream stages (`analyze`, `design`, `implement`) and the test stage assume:

1. **PR exists from implement stage** (single/child path).
   - `gh pr list --search "Refs #$1" --state open` returns at least one PR. (`test_work.md` lines 49–54) [PRESERVE]
   - If empty → `test_work` returns `FAIL: no open PR found for Issue #$1`. [PRESERVE]

2. **`<!-- sdd:test-evidence:step-<n> -->` comments exist on the Issue from implement stage** (when applicable).
   - Reviewers use them for authenticity checks against `TESTS: <p>/<t> FAILED: <f>` claims. [PRESERVE]
   - Reviewer discretion (not currently a hard gate). [IMPROVE — see §8]

3. **Parent completion = all children `sdd:done`.**
   - Strict gate at Phase 1 AND at `test_work` Mode detection. [PRESERVE]
   - Children must traverse `analyze → design → implement → test → done` independently before parent can enter test stage. [PRESERVE]

4. **`<!-- sdd:analyze:output -->`, `<!-- sdd:design:output -->` exist on the Issue** before test stage starts.
   - `test_review` and `test_adversarial` read both via `gh api ... --jq '.[] | select(.body | contains("sdd:analyze:output") or contains("sdd:design:output") or contains("sdd:test:output"))'`. (`test_review.md` lines 22–24; `test_adversarial.md` lines 21–23) [PRESERVE]
   - `parent_integration_review` additionally reads `<!-- sdd:children:output -->` and each child's full stage outputs. (`parent_integration_review.md` lines 17–34) [PRESERVE]

5. **Findings JSON schema (Common Contracts §5)** is present in every review comment.
   - Used by retry mode self-fetch in subsequent test rounds. [PRESERVE]
   - Used by `parent_integration_review` for aggregate quality signals across children. (`ai-review-parent-integration.md` lines 30–32) [PRESERVE]

6. **Label transition `sdd:test → sdd:done`** is the sole signal of test stage completion.
   - No file, no env var, no in-process state. (Common Contracts §1, §2) [PRESERVE]
   - `gh issue close $1` is concurrent with the label add, but the label is the authoritative state. [PRESERVE]

7. **Children comment update on child completion** (Phase 5) is the sole signal that updates the parent's view of child progress.
   - No FSM tracks "X of N children done"; the table in `<!-- sdd:children:output -->` is the persistent state. [PRESERVE]
   - Phase 5 logic is shared verbatim with `implement.md` Phase 7. [PRESERVE — single source of truth]

8. **Retry self-fetch markers are stage-and-role specific.**
   - Single/child path retry markers: `sdd:review:test:{completeness,quality,adversarial}`.
   - Parent path retry markers: same 3 PLUS `<!-- sdd:review:parent -->`. (`test_work.md` lines 32–34) [PRESERVE]
   - Pre-v0.36 callers that pass anything other than literal `"retry"` MUST be rejected with `FAIL: unrecognized retry slot value: <truncated>` (Common Contracts §7). [PRESERVE]

9. **Update-in-place invariant**: round-to-round retries overwrite the prior comment for the same marker. Prior-round content is lost from GitHub. (Common Contracts §4) [PRESERVE — but see §4 RETHINK on round preservation]

10. **Bash safety**: every Bash call MUST be a single simple command per Common Contracts §8. The integration-PR creation in `test_work` parent path must use Write-tool + `--body-file` (NEVER heredoc). (`test_work.md` lines 162–172) [PRESERVE — load-bearing]

---

## Cross-references

- Common Contracts (markers, retry, bash rules, comment posting) → `spec/00-common-contracts.md`
- Skip-review semantics (`qa` token) → `spec/01-config.md` §2
- Depth labels / model table → `spec/01-config.md` §3
- Multilingual parent regex (Phase 5) → `spec/02-multilingual.md` §3
- Test evidence procedure → `commands/atoms/_test_evidence.md` (called by Stage 3 implement atoms; consumed by Stage 4 reviewers)
- Parent integration review criteria → `commands/ai-review-parent-integration.md`
- Phase 5 child notification details → `spec/stage/implement.md` Phase 7 (when written)
