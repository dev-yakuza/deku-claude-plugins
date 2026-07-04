# STAGE: test

**Single sub-agent. MUST NOT spawn Agent calls. MUST NOT spawn other sub-agents. MAY use the Skill tool (only `/verify` is invoked here, and only on the SINGLE/CHILD path).**

This file is the Arch B stage sub-agent body for the **Test** stage. The main session (or `resume.md` after bootstrap) spawns this sub-agent once per Issue per stage invocation. Internally it inlines the logic of the legacy `test_work`, `test_review` (completeness + quality), `test_adversarial`, and `parent_integration_review` (parent path only) atoms — runs them **serially** because the single-level spawn rule (`spec/00-common-contracts.md` §12) forbids nested Agent calls.

The sub-agent owns the entire AI-review retry loop (max 3 rounds), the adversarial-only FAIL warning (R6), the `/verify` Skill invocation (Phase 2.7, SINGLE/CHILD path only), the framework-detection recoverable failure, the manual-QA hand-off, and the final `sdd:done` label transition + child completion notification. It does NOT call `AskUserQuestion` — those are main-session responsibilities. On Round 3 FAIL with skip-review OFF the sub-agent returns an `ESCALATE:` line so main can interactively prompt the user. On a recoverable framework gap it returns `OK NEEDS_FRAMEWORK_CHOICE:` so main can ask the user which framework to use and re-spawn. On the manual QA gate (skip-review OFF) it returns `OK NEEDS_MANUAL_QA:` so main can collect user pass/fail and re-spawn with `Resume: qa-approved` or `Resume: qa-failed`.

> **Bash Command Execution**: every shell snippet below is its own simple Bash tool call. See canonical rules in `<<SKILL_DIR>>/commands/atoms/_bash_rules.md`. Codebase exploration uses **Grep / Glob / Read** tools, not Bash equivalents.

---

## Inputs

- `$1` — Issue number. Already validated as an Issue (not a PR) by the caller, but re-validated here as defense in depth (`spec/00-common-contracts.md` §10).
- `$2` — Depth dial. One of `default` / `deep` / `shallow`. The caller derives this from labels; this sub-agent verifies against the live labels in Phase 0.
- `$3` — Resume hint. One of:
  - `none` (default; full execution),
  - `continue-after-escalation` (Round 3 FAIL → user chose Continue; skip Phase 2 work + reviews — already persisted — jump to Phase 2.7 for SINGLE/CHILD or Phase 3 for PARENT),
  - `qa-approved` (returning from main session's manual-QA gate; jump to Phase 4 success branch),
  - `qa-failed` (returning from main session's manual-QA gate; return `OK BACK_TO_IMPLEMENT`).

  Per `design/01-sub-agent-contract.md` §3 and SYNTHESIS-v2 T1.5 (`continue-after-escalation`) / T1.4 (`qa-approved` / `qa-failed`).
- `$4` — Framework (optional, used only on re-spawn after `OK NEEDS_FRAMEWORK_CHOICE`). Literal framework name chosen by the user (e.g. `playwright`, `cypress`, `pytest`). Skips PARENT path framework detection inside §3 Phase 2 work logic.

`Branch` / `PR` fields from the global prompt template (`design/01-sub-agent-contract.md` §1) are optional cache hints; this sub-agent re-derives them from `gh pr list --search "Refs #<N>"` and treats absent values as `null`.

---

## §1. Issue Validation (defense in depth)

Before anything else, validate `$1` per Common Contracts §10:

```bash
gh issue view $1 --json url --jq .url
```

- Empty / error → return `FAIL: Issue #$1 does not exist`.
- URL contains `/pull/` → return `FAIL: #$1 is a Pull Request, not an Issue. SDD commands operate on Issues only.` Do NOT modify labels, do NOT post comments.
- URL contains `/issues/` → continue.

[PRESERVE — `spec/stage/test.md` §1 Entry conditions; `spec/00-common-contracts.md` §10.]

### Entry-condition precheck

- **SINGLE/CHILD path precondition** (verified in §3): an open PR matching `Refs #$1` must exist. Empty → `FAIL: no open PR found for Issue #$1`.
- **PARENT path precondition** (verified in §3): ALL children listed in `<!-- sdd:children:output -->` must already be `sdd:done`. Any child not done → `FAIL: parent has incomplete children: #X, #Y, ...` (defensive — main session's bootstrap normally catches this first).

Both checks live inside §3 Phase 1 path detection so this sub-agent stays self-contained.

---

## §2. Phase 0 — Depth detection

Even though `$2` was passed in by the caller, re-read labels here to keep the sub-agent self-contained:

```bash
gh issue view $1 --json labels --jq '[.labels[].name]'
```

Decision (overrides `$2` if labels disagree):
- Labels contain `sdd:review:deep` → `depth = deep`
- Labels contain `sdd:review:shallow` → `depth = shallow`
- Otherwise → `depth = default`

The depth dial selects models used internally for the inlined work and review reasoning per `spec/00-common-contracts.md` §3 / `_review_helpers.md` Section A.2. Since this entire stage runs inside ONE sub-agent context (no inner Agent spawns), the model dial is informational for the sub-agent's reasoning style — the actual model is fixed by the Agent spawn's `model` parameter from main session. `test_work`-style reasoning is always opus per `spec/stage/test.md` Phase 0 [PRESERVE]. Record the dial for the `<details>` self-review trace.

### Resume short-circuits (T1.4, T1.5)

Before path detection, branch on `$3`:

- **`$3 == "continue-after-escalation"`**:
  - Re-validate the Issue still exists and is still an Issue (§1 above).
  - Re-derive `path` via §3 Phase 1 detection (need it to choose target Phase).
  - Confirm the expected review markers exist on the Issue (SINGLE/CHILD: 3 markers `sdd:review:test:{completeness,quality,adversarial}`; PARENT: those 3 plus `<!-- sdd:review:parent -->`). One `gh api ... /comments` call + substring presence checks.
  - If any required marker is missing → return `FAIL: continue-after-escalation requested but prior round's review markers missing on #$1`.
  - SINGLE/CHILD → jump directly to **§7 Phase 2.7** (run `/verify` if available, then return `OK NEEDS_MANUAL_QA` or auto-approve under skip-review).
  - PARENT → jump directly to **§8 Phase 3** (no `/verify` on parent; manual QA gate or auto-approve).

- **`$3 == "qa-approved"`**:
  - Re-validate Issue (§1).
  - Skip Phases 1–2.7 entirely (already done in the spawn that emitted `OK NEEDS_MANUAL_QA`).
  - Jump directly to **§9 Phase 4 success branch** (label transition + close + child notification).

- **`$3 == "qa-failed"`**:
  - Re-validate Issue (§1).
  - Skip Phases 1–2.7 entirely.
  - Return `OK BACK_TO_IMPLEMENT` immediately (§9 Phase 4 failure branch). NO label change, NO close, NO child notification.

- **`$3 == "none"`** (or empty) → continue to §3 Phase 1.

- **Any other `$3` value** → return `FAIL: unrecognized Resume value: <truncated to 80 chars>` per the same defensive convention used for retry slot values (Common Contracts §7).

[PRESERVE — SYNTHESIS-v2 T1.4 / T1.5; `design/stage-designs/test.md` §2 + §12.]

---

## §3. Phase 1 — Path detection (SINGLE/CHILD vs PARENT)

Determine which of three paths this Issue follows. The decision is captured in a stage-internal variable `path ∈ {SINGLE, PARENT}` and an integration sub-variable for PARENT (`integration_pr ∈ {<#M>, null}`, filled in by Phase 2 work).

### Step 1: Detect PARENT vs SINGLE/CHILD

Resolve repo, then search for the children marker:

```bash
gh repo view --json nameWithOwner -q .nameWithOwner
```

Observe the literal `<owner>/<repo>` from output. Then:

```bash
gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | select(.body | contains("<!-- sdd:children:output -->")) | .id'
```

Substitute the literal `<owner>/<repo>` and `$1` from above. Treat the marker as the exact substring (Common Contracts §4 — leading `<!-- ` + trailing ` -->`).

- **Non-empty result** → `path = PARENT`. Continue to Step 2 (children completeness gate).
- **Empty result** → `path = SINGLE`. (Literal kind — single Issue vs child Issue — is irrelevant for §4 routing; the child distinction matters only in §10 Phase 5 for the parent-notification step.)

### Step 2: PARENT path — verify all children done

If `path == PARENT`:

1. Fetch the children comment body:
   ```bash
   gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | select(.body | contains("<!-- sdd:children:output -->")) | .body'
   ```
2. Parse the child Issue numbers from the table rows in the body (narrative parsing — no shell tooling).
3. For each child number, check its labels:
   ```bash
   gh issue view <child> --json labels --jq '[.labels[].name]'
   ```
   (One Bash call per child; substitute the literal child number from Step 2.)
4. If ANY child does NOT have label `sdd:done` → return `FAIL: parent has incomplete children: #X, #Y, ...` (list all incomplete children, comma-separated, max 200 chars).
5. If all children are `sdd:done` → proceed to §4 Phase 2 with `path = PARENT`.

[PRESERVE — `spec/stage/test.md` Phase 1 step 2; `design/stage-designs/test.md` §3; double-check defensive pattern with `test_work` Mode detection.]

### Step 3: SINGLE/CHILD path — verify PR exists

If `path == SINGLE`:

```bash
gh pr list --search "Refs #$1" --state open --json number --jq '.[0].number'
```

- Empty → return `FAIL: no open PR found for Issue #$1`.
- Non-empty → record the literal PR number as `<PR_NUM>` for use throughout §4 (reviewer post location) and Phase 2.7 (`/verify` context).

Proceed to §4 Phase 2 with `path = SINGLE` and the cached `<PR_NUM>`.

[PRESERVE — `spec/stage/test.md` §1 Entry conditions: PR must exist; `test_work.md` lines 49–54.]

---

## §4. Phase 2 — Test work + AI review loop (max 3 rounds)

Each round = work + reviewers (3 for SINGLE/CHILD, 4 for PARENT) + verdict combine. Local state: a counter `round` starting at 1. Rounds 2 and 3 re-enter §4.1 with retry semantics.

### §4.1 Phase 2.X.1 — Test work (inlined `test_work` logic)

This phase produces the test output and posts it under `<!-- sdd:test:output -->`.

#### Step 0: Preflight (Light tier) or retry self-fetch

- **Round 1** (`round == 1`): follow `<<SKILL_DIR>>/commands/atoms/_preflight.md` Section A — tier **Medium**, Section B items 1 + 2 + 3 + 5 (project conventions + commit message style + similar past PRs + project-specific stage rules). For `test_work`-style reasoning, item 1's convention reading should pay attention to **testing conventions** (test framework, test directory layout, assertion style). Apply Section D failure handling. Record findings for the §4.1 self-review trace.
- **Rounds 2 / 3** (`round > 1`): SKIP the preflight items above. Instead, execute `<<SKILL_DIR>>/commands/atoms/_review_helpers.md` Section C to self-fetch the previous round's review comments. Markers per path:
  - **SINGLE/CHILD** (`path == SINGLE`): `<!-- sdd:review:test:completeness -->`, `<!-- sdd:review:test:quality -->`, `<!-- sdd:review:test:adversarial -->`.
  - **PARENT** (`path == PARENT`): the 3 SINGLE markers PLUS `<!-- sdd:review:parent -->`.

  Section C returns a sorted findings array (`critical → major → minor`). Hold this array as `<retry-findings>` for use throughout the steps below.
  - If Section C returns `FAIL: ...` (no review comments found, etc.) → propagate it as this sub-agent's return value before doing any further work.

[PRESERVE — `spec/stage/test.md` §4 Phase 2 retry semantics; `spec/00-common-contracts.md` §7; v0.36 atom-side self-fetch invariant.]

#### Step 1: Read the Issue + relevant cross-stage outputs

```bash
gh issue view $1
```

Capture title, body, labels for use in subsequent steps.

For BOTH paths, also re-read the analyze + design outputs (review atoms re-fetch them independently, but the work step also uses them for QA-checklist composition):

```bash
gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | select(.body | contains("sdd:analyze:output") or contains("sdd:design:output")) | .body'
```

For **SINGLE/CHILD** path, additionally fetch the implement plan and E2E-skipped scenarios — used in Step 2 items 3 and 4:

```bash
gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | select(.body | contains("<!-- sdd:implement:plan -->")) | .body'
```

```bash
gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | select(.body | contains("<!-- sdd:e2e-skipped-scenario -->")) | .body'
```

Hold as `<implement-plan-body>` and `<e2e-skipped-body>`.

For **SINGLE/CHILD** path, also fetch the shared coverage ledger:

```bash
gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | select(.body | contains("<!-- sdd:coverage:ledger -->")) | .body'
```

Hold as `<ledger-body>`. Parse the JSON between `<!-- sdd:coverage:json -->` and `<!-- /sdd:coverage:json -->` in context. If present, the ledger is the **primary source** for QA-checklist composition in Step 2 item 4 (it carries per-scenario status, sha, and reason accumulated by analyze → design → implement); `<implement-plan-body>` and `<e2e-skipped-body>` remain as cross-check inputs and as the fallback when the ledger is absent.

For **PARENT** path, additionally fetch the children marker body:

```bash
gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | select(.body | contains("sdd:children:output")) | .body'
```

#### Step 2: Path-specific work

**SINGLE/CHILD path** (`path == SINGLE`):

1. The PR number is already cached as `<PR_NUM>` from §3 Step 3. Re-fetch the PR view + diff:
   ```bash
   gh pr view <PR_NUM>
   ```
   ```bash
   gh pr diff <PR_NUM>
   ```
2. **4-1. Verify existing tests** (read-only via Read / Grep / Glob tools — do NOT check out the PR locally and do NOT run test commands here; that capability is reserved for the `/verify` Skill in §7 Phase 2.7):
   - Read the PR's test files referenced in the diff.
   - Compare existing tests against the Issue's DoD and analyze/design requirements.
   - Note any gaps (missing scenarios, missing edge cases, regression risks).
3. **Check E2E_SKIPPED flag**: use `<e2e-skipped-body>` (fetched in Step 1) as the primary signal — if `<!-- sdd:e2e-skipped-scenario -->` comment exists on the Issue → `E2E_SKIPPED = true`. Hold the listed scenarios as `<e2e-skipped-scenarios>`. As a secondary fallback, check the PR body's `## Automated Test Coverage` E2E line for the word "skipped". Note: `<!-- sdd:test-evidence:step-4 -->` is **absent** when E2E is skipped (the implement pipeline does not post it — `_tdd.md` §6.4), so its absence is NOT a reliable signal.
4. **4-2. Compose QA checklist** — if `<ledger-body>` was parsed successfully in Step 1 and the `scenarios` array is non-empty, skip the **Automated** and **Manual** sub-bullets below and proceed directly to item 5's ledger-first rule (the **Regression** section and the **Cross-check** still apply regardless):
   - **Automated**: list scenarios covered by the TDD pipeline. Cross-reference `<implement-plan-body>` Test Plan categories (Happy path / Error path / Boundary conditions / Concurrent/State) to confirm completeness. Note any non-`N/A` category with no corresponding automated test as a coverage gap.
   - **Manual**: include ONLY items that fall into one of these 5 categories — (1) UI/UX appearance (visual rendering, animation, hover states not expressible as assertions), (2) accessibility (screen reader, keyboard navigation, focus management), (3) performance (response times, memory usage, load behavior), (4) unmockable external integrations (payment processors, SMS, live OAuth), (5) E2E-skipped scenarios — if `E2E_SKIPPED == true`, use `<e2e-skipped-scenarios>` from `<!-- sdd:e2e-skipped-scenario -->` directly as Manual items. If no items qualify for any category, write "No manual verification required — all scenarios are covered by automated tests."
   - **Regression**: prior fragility areas; note whether each has an automated test or needs manual re-check.
   - Cross-check: read the PR body's `## Manual Test Checklist` section and verify each item falls into one of the 5 categories above. Items that do not → note as `manual-item-may-be-automatable` for the reviewer to flag.

5. **Ledger-first rule for 4-2**: if `<ledger-body>` parsed successfully in Step 1 and the `scenarios` array is non-empty, compose the QA checklist directly from the ledger's `scenarios` array instead of re-deriving coverage from `<implement-plan-body>`:
   - `status == "automated"` → list in the **Automated** section (group by `category`; include the scenario `description` and its `sha` as evidence).
   - `status == "manual"` → list in the **Manual** section, including the `reason`.
   - `status == "skipped"` → list under a **Skipped (E2E)** subsection of Manual, including the `reason`.
   - `status == "pending"` → flag as a **coverage gap** in the Automated section (scenario planned but never automated or dispositioned) — note as a `[major]` coverage gap for reviewers.
   - Cross-check the ledger's `summary` counters against the listed items; a mismatch is itself a coverage-gap note.
   - The `<implement-plan-body>` cross-reference in item 4 then serves only as a sanity check (a plan category with no ledger scenario at all → coverage gap). When the ledger is absent, item 4's original derivation applies unchanged.

**PARENT path** (`path == PARENT`):

1. Read each child's analyze / design / implement outputs and the children's PRs:
   ```bash
   gh issue view <child>
   ```
   ```bash
   gh api repos/<owner>/<repo>/issues/<child>/comments --jq '.[] | select(.body | contains("sdd:analyze:output") or contains("sdd:design:output")) | .body'
   ```
   For each child PR (find via `gh pr list --search "Refs #<child>" --state merged --json number --jq '.[0].number'`):
   ```bash
   gh pr view <child-PR>
   ```
   ```bash
   gh pr diff <child-PR>
   ```
2. **4-0. Test framework detection** (parent only):
   - If `$4` (Framework input) is non-empty → use it directly; SKIP detection.
   - Else → detect framework via Read/Grep/Glob (per Common Contracts §8 — NEVER Bash `find` outside repo root):
     - Framework type (Jest, Vitest, Pytest, Go test, Playwright, Cypress, etc.).
     - Test directory layout (`tests/`, `__tests__/`, `e2e/`, etc.).
     - Test run command (from `package.json` scripts, `Makefile`, etc.).
     - Test configuration files (`jest.config.*`, `pytest.ini`, `playwright.config.*`, etc.).
   - If no E2E setup found AND `$4` is empty → return the special-prefix FAIL from this sub-agent (do NOT post `<!-- sdd:test:output -->`):
     - Compose recommendation based on tech stack (e.g. `playwright` for TypeScript + React, `cypress` for legacy JS, `pytest-bdd` for Python, etc.).
     - Return `OK NEEDS_FRAMEWORK_CHOICE: recommended=<name>` (NOT `FAIL:`).
     - Main session asks the user, then re-spawns this sub-agent with `Framework: <chosen-name>` set as `$4`.

   [PRESERVE — `spec/stage/test.md` §9; `design/stage-designs/test.md` §13; SYNTHESIS-v2 T1.4 — the special-prefix is now an explicit return keyword, not a `FAIL:` prefix.]

3. **4-1. Integration E2E** (parent only):
   - Identify cross-child integration scenarios from the design output + children's PRs.
   - **If integration tests are needed**:
     - Create a test branch via simple Bash (one call):
       ```bash
       git checkout -b test/<parent-feature-name>
       ```
       Substitute the literal branch name (derived from the parent's design output title — kebab-case, max 60 chars).
     - Author E2E test code following the existing framework patterns (use the Write tool for new test files; Edit tool for incremental additions to existing test files).
     - Stage + commit:
       ```bash
       git add <changed-paths>
       ```
       ```bash
       git commit -m "test: <parent-feature> integration tests"
       ```
       (Do NOT set Claude as co-author — see Hard rules.)
     - Push:
       ```bash
       git push -u origin test/<parent-feature-name>
       ```
     - Create the PR via the Section F temp-file pattern (NEVER heredoc — Common Contracts §9):
       - **Write tool** → `/tmp/sdd-test-parent-$1.md`. Body:
         - Line 1: `Refs #$1` (substitute the literal Issue number)
         - Line 2: (blank)
         - Then: summary, then blank, then `## Manual Test Checklist` and items.
       - **Bash**:
         ```bash
         gh pr create --title "test: <parent feature> integration tests" --body-file /tmp/sdd-test-parent-$1.md
         ```
     - Observe the created PR number from `gh pr create`'s URL output. Record as `<INTEGRATION_PR>`.
     - Record the work outcome as `OK PARENT INTEGRATION_PR: #<INTEGRATION_PR>` (used in §4.1 Step 8 below).
   - **If integration tests are NOT needed** (children's tests already cover all scenarios — verified by reading children's PRs + design output):
     - Document the rationale in the `<!-- sdd:test:output -->` body (see Step 6).
     - Record the work outcome as `OK PARENT NO_INTEGRATION`.

4. **4-2. QA checklist (parent-level)**:
   - Cross-child integration scenarios.
   - Regression test targets across the whole parent feature.
   - Apply the same Automated / Manual / Regression structure as SINGLE/CHILD.

#### Step 3: Retry resolution check (rounds 2 / 3 only)

If Step 0 fetched `<retry-findings>`, verify before posting that every `critical` and `major` finding has been addressed in the updated test output. Mention how (in the body or in the trace block) — or, only if genuinely infeasible, why it could not be. Treat `minor` entries as supporting context.

[PRESERVE — `test_work.md` retry-finding handling; Common Contracts §7.]

#### Step 4: Language template + self-review (blockers only)

Determine output language:
1. If `.github/.sdd-lang` exists → read it; use its language code (`en` / `ko` / `ja`).
2. Else detect primary language of the Issue body; map to closest supported (`en` / `ko` / `ja`).
3. Else default to `en`.

`test_work` does NOT use a separate `output_test.md` template file (none ships). Use the in-line body skeleton in Step 5 below, with heading translations applied per `spec/02-multilingual.md` §6 only if the project's `.sdd-lang` is `ko` or `ja`.

Before posting, verify posting-blocking checks:
- [ ] Marker `<!-- sdd:test:output -->` present (open + close).
- [ ] Path label is set (`Single/Child Issue` for SINGLE, `Parent Issue` for PARENT).
- [ ] For SINGLE: PR number referenced.
- [ ] For PARENT with integration: integration PR URL included.
- [ ] For PARENT without integration: rationale documented.
- [ ] QA checklist sections (Automated / Manual / Regression) filled.
- [ ] If E2E_SKIPPED detected on SINGLE: flag visible in body.
- [ ] No `<empty>` / TODO / `<...>` placeholder text remaining.

If a blocker fails → fix inline. Track which blockers were fixed for the Step 7 self-review trace.

*Quality, completeness, risk evaluation are NOT done here — that is the reviewer phase's job (§4.2). Keep self-review minimal.* [PRESERVE — `test_work.md` lines 78–87.]

#### Step 5: Compose test:output body

Skeleton (substitute literal values; preserve markers verbatim):

```
<!-- sdd:test:output -->
## Test Results

**Path:** <Single/Child Issue | Parent Issue>
**PR:** #<PR_NUM>                          # SINGLE only
**Branch:** <branch-name>                   # SINGLE only — read from gh pr view <PR_NUM>
**Integration PR:** #<INTEGRATION_PR>       # PARENT INTEGRATION_PR variant only
**No-Integration Rationale:** <text>        # PARENT NO_INTEGRATION variant only

### 4-1. Existing Tests
- Unit / widget / E2E inventory + coverage evaluation (gaps if any)
- E2E_SKIPPED flag (if SINGLE and Stage 3 skipped E2E)

### 4-2. QA Checklist
#### Automated (already verified by tests)
- [x] <item>
#### Manual (requires human verification)
- [ ] <item>
#### Regression
- [ ] <item>

<!-- /sdd:test:output -->
```

For PARENT INTEGRATION_PR variant, also list the cross-child integration scenarios covered by the new test branch. For PARENT NO_INTEGRATION variant, list the children's tests that already cover each integration scenario from the design output.

#### Step 6: Append self-review trace (optional)

If any blocker was fixed inline in Step 4, OR if Step 0 ran preflight items, append a `<details>` block at the bottom of the body, BEFORE the closing `<!-- /sdd:test:output -->` marker:

```markdown
<details>
<summary>Self-review trace (blockers only)</summary>

- [x] Test results filled
- [x] QA checklist sections filled
- [x] PR/Integration PR referenced
- [ ] E2E_SKIPPED flag missing — fixed inline

</details>
```

List only blockers actually checked. `[x]` for clean, `[ ]` with inline note for fixed. Skip the block entirely if there is nothing to record. On retry rounds where Step 0 was skipped, omit the preflight section of the trace.

The `/verify` Skill result will be ADDED to this same `<details>` block later (§7 Phase 2.7) via update-in-place.

#### Step 7: Post via Section F temp-file pattern

Follow `<<SKILL_DIR>>/commands/atoms/_review_helpers.md` Section F — the mandatory temp-file pattern. Inline `--body` is forbidden because the body contains `\n#` patterns that trip a non-bypassable Claude Code heuristic.

1. **Write tool** — render the test output body (including markers) to `/tmp/sdd-test-output-$1.md`. The file must start with `<!-- sdd:test:output -->` on the first line and end with `<!-- /sdd:test:output -->`.

2. **Bash** — duplicate-prevention search:

   ```bash
   gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | select(.body | contains("<!-- sdd:test:output -->")) | .id'
   ```

   Substitute the literal `<owner>/<repo>` from §3 (or re-derive via `gh repo view --json nameWithOwner -q .nameWithOwner`).

3. **Bash** — branch on the result:
   - **Empty** → create: `gh issue comment $1 --body-file /tmp/sdd-test-output-$1.md`
   - **Has id `<id>`** → update in place: `gh api repos/<owner>/<repo>/issues/comments/<id> -X PATCH --field body=@/tmp/sdd-test-output-$1.md`

[PRESERVE — `spec/00-common-contracts.md` §9; deterministic temp path `/tmp/sdd-test-output-$1.md`; round-to-round PATCHes overwrite (Common Contracts §4).]

#### Step 8: Internal work outcome

Record the work outcome for the §4.3 verdict combiner and §7/§8 path branching:

- `work_outcome = "OK SINGLE PR: #<PR_NUM>"` (path = SINGLE), OR
- `work_outcome = "OK PARENT INTEGRATION_PR: #<INTEGRATION_PR>"` (path = PARENT, integration created), OR
- `work_outcome = "OK PARENT NO_INTEGRATION"` (path = PARENT, no integration).

Any unrecoverable error during Step 1–7 (gh API failure, branch creation failed, PR create failed, etc.) → return `FAIL: <reason>` from this sub-agent immediately. Do NOT proceed to reviews.

Special case: PARENT path with no E2E setup detected and `$4` empty → return `OK NEEDS_FRAMEWORK_CHOICE: recommended=<name>` (handled in Step 2 above; do NOT post the test:output marker in this case).

### §4.2 Phase 2.X.2 — Reviews (SERIAL inside this sub-agent)

Three reviewers (SINGLE/CHILD) or four reviewers (PARENT) execute **one after another**. Each reviewer reads ONLY its role-specific rubric, optionally performs bounded codebase exploration, posts under its marker, and produces a PASS/FAIL verdict + findings JSON.

[PRESERVE — independence invariant from `design/stage-designs/test.md` §4 and Common Contracts §12]:
Each reviewer's reasoning context cannot see other reviewers' verdicts during its own evaluation. Even though execution is serial, structure each reviewer's work as a **fresh logical pass** — do NOT feed Reviewer N+1 the comment body Reviewer N just posted; do NOT let later reviewers see earlier reviewers' verdicts. Work outputs (test output, analyze/design outputs) are shared ground truth and are reused from context without re-fetching.

[PRESERVE — `test_review.md` line 80 / `test_adversarial.md` line 78 / `parent_integration_review.md` line 111]: Write tool permitted only for rendering the comment body to the deterministic temp path. Edit / NotebookEdit forbidden inside reviewer logic.

### §4.2.1 Reviewer 1: completeness

1. Read `<<SKILL_DIR>>/commands/atoms/rubrics/test-completeness.md`.

2. Use the test output from the temp file written in §4.1 Step 7 — **Read tool** on `/tmp/sdd-test-output-$1.md`. Also use the analyze + design outputs already in context (fetched during §4.1 Steps 1–2). No GitHub API call needed for these. Fall back to GitHub fetch only if temp files are unavailable.

3. **Optional codebase exploration** per `<<SKILL_DIR>>/commands/atoms/_review_helpers.md` Section D. Apply the Section D budget for the current `depth`. Read the PR's test files (SINGLE) or integration PR's test files + at least one child's test file (PARENT). Verify the test output's claims match actual test code. Reviewers MAY also Read the `<!-- sdd:test-evidence:step-<n> -->` comments on the Issue to cross-check `TESTS: <p>/<t> FAILED: <f>` claims against captured runner output (`_test_evidence.md` lines 113–115; `spec/stage/test.md` §8). Track your own counts; if a cap is reached, stop exploration, note `rule_id: exploration-budget-exceeded` severity `minor`, and proceed to verdict.

4. Apply the completeness rubric — test coverage against analyze/design requirements + DoD. Severity definitions (per `rubrics/test-completeness.md`):
   - **critical** — a required user flow has no test coverage.
   - **major** — meaningful coverage gap or DoD item with no test/checklist mapping.
   - **minor** — wording or structural suggestion that does not block.

5. **Determine verdict** per Common Contracts §5 B.3:
   - Any `critical` or `major` finding → **FAIL** (with one-line summary).
   - Only `minor` findings or none → **PASS**.

6. **Compose comment body** for marker `<!-- sdd:review:test:completeness -->`:

   ```
   <!-- sdd:review:test:completeness -->
   ## AI Review (test / completeness)

   **Verdict:** PASS | FAIL
   **Model:** <opus|sonnet|haiku>

   ### Issues
   - **[critical]** <description>
   - **[major]** <description>
   - **[minor]** <description>

   ### Suggestions
   <if any>

   <!-- sdd:findings:json -->
   ```json
   {<structured findings per _review_helpers.md Section B.2>}
   ```
   <!-- /sdd:findings:json -->
   <!-- /sdd:review:test:completeness -->
   ```

   Set `stage: "test"`, `role: "completeness"`, `issue: $1`, `pr: <PR_NUM | null>` (SINGLE: literal PR number; PARENT: null), `round: <current round>`, `verdict`, `model` (the sub-agent's actual model — usually `opus` since main session spawns this stage with `model: opus`), `findings` array, `suggestions` array.

7. **Post via Section F** (mandatory temp-file pattern). Location depends on `path`:

   **SINGLE/CHILD** (post on the **PR**):
   - **Write tool** → `/tmp/sdd-review-test-completeness-pr<PR_NUM>.md`
   - **Bash** duplicate-prevention search (PR comments share the Issues API):
     ```bash
     gh api repos/<owner>/<repo>/issues/<PR_NUM>/comments --jq '.[] | select(.body | contains("<!-- sdd:review:test:completeness -->")) | .id'
     ```
   - **Bash** branch:
     - Empty → `gh pr comment <PR_NUM> --body-file /tmp/sdd-review-test-completeness-pr<PR_NUM>.md`
     - Has id `<id>` → `gh api repos/<owner>/<repo>/issues/comments/<id> -X PATCH --field body=@/tmp/sdd-review-test-completeness-pr<PR_NUM>.md`

   **PARENT** (post on the **Issue**):
   - **Write tool** → `/tmp/sdd-review-test-completeness-$1.md`
   - **Bash** duplicate-prevention search:
     ```bash
     gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | select(.body | contains("<!-- sdd:review:test:completeness -->")) | .id'
     ```
   - **Bash** branch:
     - Empty → `gh issue comment $1 --body-file /tmp/sdd-review-test-completeness-$1.md`
     - Has id `<id>` → `gh api repos/<owner>/<repo>/issues/comments/<id> -X PATCH --field body=@/tmp/sdd-review-test-completeness-$1.md`

8. **Record internal verdict** for the §4.3 verdict combiner: `completeness_verdict = PASS | FAIL`, plus a one-line summary if FAIL. Move on to §4.2.2.

If any step above raises an atom-level error (gh API failure, missing test output, etc.), return `FAIL: <reason>` from this sub-agent immediately. Do NOT continue to the next reviewer.

### §4.2.2 Reviewer 2: quality

Repeat §4.2.1 with these substitutions:
- Rubric file: `<<SKILL_DIR>>/commands/atoms/rubrics/test-quality.md`
- Marker: `<!-- sdd:review:test:quality -->` (open + close)
- Temp file (SINGLE): `/tmp/sdd-review-test-quality-pr<PR_NUM>.md`
- Temp file (PARENT): `/tmp/sdd-review-test-quality-$1.md`
- Severity definitions (per rubric):
  - **critical** — assertion is tautological or test cannot catch the regression it claims.
  - **major** — flakiness risk, shared mutable fixtures, order-dependent tests, or missing negative assertions for a critical flow.
  - **minor** — wording, suggestion for additional boundary case, etc.
- Findings JSON `role`: `"quality"`

Reuse the test output + analyze/design outputs already in context from §4.2.1 — no re-fetch. Independence invariant: do NOT incorporate completeness reviewer's verdict into this reviewer's reasoning.

Record `quality_verdict = PASS | FAIL`. Proceed to §4.2.3.

### §4.2.3 Reviewer 3: adversarial

Repeat §4.2.1 with these substitutions:
- Rubric file: `<<SKILL_DIR>>/commands/atoms/rubrics/test-adversarial.md`
- Also read Section E of `<<SKILL_DIR>>/commands/atoms/_review_helpers.md` for the general adversarial reviewer prompt.
- Marker: `<!-- sdd:review:test:adversarial -->` (open + close)
- Temp file (SINGLE): `/tmp/sdd-review-test-adversarial-pr<PR_NUM>.md`
- Temp file (PARENT): `/tmp/sdd-review-test-adversarial-$1.md`
- Lens: **REFUTE** the test output. Mentally mutate the implementation, find tests that would pass with no-op or broken impl, find missing classes of coverage. Apply the angles from the rubric (mutation thinking, suspiciously concise QA checklist, misleading coverage report, cross-stage drift, integration vs unit gaps for parent). Must find ≥1 weakness OR explicitly justify why none.
- Severity guidance (per rubric):
  - **critical** — refutation that would block correct shipping (e.g. test passes with no-op).
  - **major** — meaningful gap (e.g. UI states not covered, locale variant ignored, child integration not exercised end-to-end).
  - **minor** — worthwhile question that does not block.
- Findings JSON `role`: `"adversarial"`

Reuse the test output + analyze/design outputs already in context — no re-fetch. Independence invariant: do NOT incorporate completeness or quality verdicts into this reviewer's reasoning.

Record `adversarial_verdict = PASS | FAIL`. Proceed to §4.2.4 (PARENT only) or §4.3 (SINGLE).

### §4.2.4 Reviewer 4: parent_integration_review (PARENT path only)

**Run only if `path == PARENT`.** For `path == SINGLE`, skip directly from §4.2.3 to §4.3.

1. Read `<<SKILL_DIR>>/commands/atoms/rubrics/parent-integration.md`.

2. Re-fetch the parent Issue's stage outputs + children comment fresh:

   ```bash
   gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | select(.body | contains("sdd:analyze:output") or contains("sdd:design:output") or contains("sdd:children:output") or contains("sdd:test:output")) | .body'
   ```

   If `<!-- sdd:children:output -->` is missing → return `FAIL: parent has no children comment on Issue #$1` from this sub-agent (defensive — §3 should have caught this).

3. Extract child Issue numbers from the children:output table. For each child, fetch the child's analyze + design + implement review summaries (structured findings JSON blocks):

   ```bash
   gh api repos/<owner>/<repo>/issues/<child>/comments --jq '.[] | select(.body | contains("sdd:review:analyze:") or contains("sdd:review:design:") or contains("sdd:review:implement:")) | .body'
   ```

   (One Bash call per child; substitute the literal child number.) Also re-derive each child's PR (`gh pr list --search "Refs #<child>" --state merged --json number --jq '.[0].number'`) and read its diff if needed for cross-child invariants.

4. **Codebase exploration (mandatory)** per `_review_helpers.md` Section D: read the interface/contract files where children connect; verify cross-child invariants hold in actual code. Apply the Section D budget for the current `depth`.

5. Apply the synthesis criteria from the rubric:
   - Feature distribution coverage across children.
   - Cross-child design consistency.
   - Cross-child implementation gaps.
   - Aggregate quality signals (similar `rule_id`s across children).
   - Closure verification against parent's Definition of Done.

6. Determine verdict: critical/major → FAIL; only minor or none → PASS.

7. **Compose comment body** for marker `<!-- sdd:review:parent -->`:

   ```
   <!-- sdd:review:parent -->
   ## AI Review (parent integration)

   **Verdict:** PASS | FAIL
   **Model:** <opus|sonnet|haiku>
   **Children reviewed:** #A, #B, #C, ...

   ### Issues
   - **[critical]** <description>
   - **[major]** <description>
   - **[minor]** <description>

   ### Suggestions
   <if any>

   <!-- sdd:findings:json -->
   ```json
   {<structured findings per _review_helpers.md Section B, stage="parent", role="parent-integration">}
   ```
   <!-- /sdd:findings:json -->
   <!-- /sdd:review:parent -->
   ```

8. **Post via Section F** on the **parent Issue** (always — `parent_integration_review` never posts on a PR per `spec/stage/test.md` §2):
   - **Write tool** → `/tmp/sdd-review-parent-$1.md`
   - **Bash** duplicate-prevention search:
     ```bash
     gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | select(.body | contains("<!-- sdd:review:parent -->")) | .id'
     ```
   - **Bash** branch:
     - Empty → `gh issue comment $1 --body-file /tmp/sdd-review-parent-$1.md`
     - Has id `<id>` → `gh api repos/<owner>/<repo>/issues/comments/<id> -X PATCH --field body=@/tmp/sdd-review-parent-$1.md`

9. **Record internal verdict** for the §4.3 combiner: `parent_integration_verdict = PASS | FAIL`. Proceed to §4.3.

### §4.3 Phase 2.X.3 — Verdict combination + retry decision

After all reviewers (3 for SINGLE/CHILD; 4 for PARENT) have posted, combine per `spec/stage/test.md` Phase 2.1.3 and `design/stage-designs/test.md` §4:

| completeness | quality | adversarial | parent_integration (PARENT only) | Combined |
|---|---|---|---|---|
| PASS | PASS | PASS | PASS | **PASS** — exit loop |
| PASS | PASS | FAIL | * | **Adversarial-only FAIL** (R6) — treat as FAIL |
| FAIL | * | * | * | **FAIL** — retry or escalate |
| * | FAIL | * | * | **FAIL** — retry or escalate |
| * | * | * | FAIL (PARENT) | **FAIL** — retry or escalate |

Atom-level `FAIL: <reason>` from any reviewer (an error, not a verdict) is handled before this combiner.

For R6 warning text and round-decision behavior, follow `<<SKILL_DIR>>/commands/atoms/_review_helpers.md` Section G — R6 applies when adversarial FAIL and all others PASS; for PARENT also verify `parent_integration_verdict == PASS`.

Round decision: All PASS → §7 (SINGLE/CHILD) or §8 (PARENT); FAIL and `round < 3` → §5; FAIL and `round == 3` → §6.

[PRESERVE — `spec/stage/test.md` §10 adversarial-only-FAIL escalation; `spec/edge-cases.md` §19.]

---

## §5. Phase 4 — Retry loop (rounds 2 and 3)

Increment `round` (now 2 or 3). Re-enter §4.1 with retry semantics:

1. Step 0 collapses to `_review_helpers.md` Section C self-fetch (no preflight items). Per `spec/00-common-contracts.md` §7 + `_preflight.md` Section E. Markers fetched depend on `path` (3 for SINGLE/CHILD; 4 for PARENT — adds `<!-- sdd:review:parent -->`).
2. Steps 1–7 re-execute, addressing every `critical` and `major` finding from `<retry-findings>`.
3. Step 7's duplicate-prevention search WILL find the existing `<!-- sdd:test:output -->` comment id and PATCH it in place (round-to-round overwrites, not appends). [PRESERVE — Common Contracts §4 Update-in-place invariant.]
4. Re-run all reviewers (§4.2.1 → §4.2.2 → §4.2.3 → §4.2.4 if PARENT) against the UPDATED `<!-- sdd:test:output -->`. Reviewer prompts are unchanged across rounds — reviewers always evaluate the CURRENT state of the test:output marker. Each reviewer's comment is PATCHed in place under its marker.
5. Re-combine verdicts (§4.3).
6. If still FAIL on round 3 → §6. If PASS at any round → exit loop → §7 (SINGLE/CHILD) or §8 (PARENT).

[PRESERVE — `spec/stage/test.md` §4 Rounds 2 & 3 retry; `_review_helpers.md` Section C.]

---

## §6. Phase 2.5 — Escalation gate (Round 3 FAIL only)

Triggered when `round == 3` AND the combined verdict from §4.3 is FAIL. Follow `<<SKILL_DIR>>/commands/atoms/_review_helpers.md` Section H:
- Summary format: `test round 3 FAIL — findings: [critical] <N>, [major] <M> (completeness=<P/F>, quality=<P/F>, adversarial=<P/F>[, parent=<P/F>])` — include `, parent=<P/F>` only when `path == PARENT`.
- skip-review key: `qa`
- Auto-continue proceeds to **§7 Phase 2.7** (SINGLE/CHILD) or **§8 Phase 3** (PARENT). Additionally append a self-review-trace addendum to `<!-- sdd:test:output -->` (update-in-place via Section F): "⚠ Round 3 escalation: tests still failing after 3 rounds, but `skip-review: qa` is set — auto-continuing. Findings remain on Issue/PR for human follow-up."

[PRESERVE — `spec/stage/test.md` Phase 2.5; gate skip only; AI review always ran. Findings remain on GitHub for human follow-up.]

---

## §7. Phase 2.7 — `/verify` Skill (SINGLE/CHILD path only)

Runs **only on SINGLE/CHILD path**. PARENT path skips entirely (parent uses children's verify results indirectly through E2E integration PR boundary tests) and jumps directly to §8.

### Pre-checks (skip conditions)

```
if path == PARENT          → skip silently (semantic skip); jump to §8
elif depth == 'shallow'     → skip; record tools_skipped += {"name":"/verify","reason":"shallow-label-skip"}; jump to §8
elif /verify unavailable    → log warning to self-review trace; skip;
                              tools_skipped += {"name":"/verify","reason":"skill-unavailable"}
                              # Causes: Claude Code ≤ v2.1.145, Skill disabled, no app-launch capability for project type
else                        → invoke
```

Detection of `/verify` availability: try the Skill tool invocation. If the Skill tool returns "skill not found" or a semantic-error response (e.g. UI-only restriction), treat as unavailable and graceful-skip. Do NOT block the stage on Skill-tool errors.

[IMPROVE — `spec/stage/test.md` Phase 2.7 RETHINK]: `tools_skipped` wiring uses the Common Contracts §5 schema enum values (`skill-unavailable` / `shallow-label-skip`) for auditability.

### Invocation

Invoke via the Skill tool inside this sub-agent (Common Contracts §13 — Skill tool is reachable from `general-purpose` sub-agents, VERIFIED):

- Skill name: `verify` (passed as the skill argument; no leading slash).
- No additional args; `/verify` reads project context from the Issue + PR.

Capture the Skill's transcript output.

### Output mapping

| `/verify` phrase | Recorded as |
|---|---|
| "feature works as expected" (or equivalent positive language) | PASS evidence for §8 |
| "feature does not work" / "crash" / "error observed" (or equivalent negative language) | FAIL evidence for §8 |

### Recording

Update `<!-- sdd:test:output -->` self-review trace (update-in-place via Section F.2). Fetch the current body, locate the `<details>` block (or insert one before `<!-- /sdd:test:output -->` if absent), append:

- `[x] /verify ran: feature launches and matches description` (PASS evidence), OR
- `[ ] /verify reported: error on login screen — see transcript` (FAIL evidence; substitute the actual one-line summary), OR
- `[ ] /verify skipped: <reason>` (skip-path).

Re-render the full body to `/tmp/sdd-test-output-$1.md` via the Write tool; PATCH the existing comment per Section F.

The `/verify` outcome is **additional context** for §8's user gate. It does NOT by itself decide PASS/FAIL. Manual QA — or `skip-review: qa` auto-approval — is the final gate.

[PRESERVE — `spec/stage/test.md` Phase 2.7 + §6; non-blocking semantics.]

---

## §8. Phase 3 — User review + manual QA gate

> **CRITICAL — SUB-AGENT INVARIANT (do not skip Steps 1+3):** Before composing the manual-QA summary or returning anything, you MUST execute **Step 1 (read `.github/.sdd-config`)** and then **Step 3 (branch on `skip-review: qa`)**. Returning `OK NEEDS_MANUAL_QA` while `qa` is in `skip-review` is a contract violation — `/sdd auto` (and any other unattended mode) cannot collect user input and depends on Case A auto-approval. The order is: **Step 1 → Step 3 → Step 2 (summary, only if Case B fires)**, NOT Step 2 → Step 3.

This phase is the only mid-stage interactive gate (sub-agent CANNOT call `AskUserQuestion` per `design/01-sub-agent-contract.md` §4). Split into a skip-review auto-approve branch (Case A) and an interactive return branch (Case B).

### Step 1: Read `.github/.sdd-config` for skip-review  ⚠ MUST run first

Use the Read tool on `.github/.sdd-config`. Parse `skip-review:` list. Token `qa` triggers the auto-approve branch.

If the file does not exist, treat as empty (`qa` absent → Case B). Do NOT skip this read; do NOT assume any value.

### Step 2: Compose manual-QA summary (used in both branches)

Build a one-line-or-short-paragraph summary for §9 (Case A's narrative trace) or for the `OK NEEDS_MANUAL_QA` return (Case B). Include:
- Path (SINGLE / PARENT INTEGRATION_PR / PARENT NO_INTEGRATION) + PR / integration PR number if applicable.
- Reviewer verdicts (compact: `c=PASS q=PASS a=PASS` or with `(adv-only FAIL)` note).
- `/verify` evidence (SINGLE only — PASS / FAIL / skipped + skip reason).
- E2E_SKIPPED flag (SINGLE only — surface if Stage 3 skipped E2E so user can decide whether to add now).
- URL to the test:output comment for the full QA checklist.

Max ~400 chars to keep the main session's narrative compact.

### Step 3: Branch on `skip-review: qa`

#### Case A — `qa` is in skip-review (auto-approve)

Log to the sub-agent narrative:
> User review skipped (skip-review: qa). Auto-approving QA checklist and proceeding to label transition.

If E2E_SKIPPED is set (SINGLE only): also log "E2E was skipped in Stage 3; auto-proceeding without E2E because `skip-review: qa` is set. Gap is documented on Issue/PR for human follow-up." Do NOT prompt.

Append the auto-approve note to the `<!-- sdd:test:output -->` self-review trace (update-in-place via Section F):
- `[x] Manual QA skipped (skip-review: qa)`
- `[x] E2E gap auto-continued (if E2E_SKIPPED)`

Proceed directly to **§9 Phase 4 success branch** (label transition + close + child notification).

#### Case B — `qa` is NOT in skip-review (interactive)

Return from this sub-agent with:

```
>>> RESULT <<<
OK NEEDS_MANUAL_QA: <summary from Step 2>
```

Main session will:
1. Render the summary verbatim to the user.
2. Surface the QA checklist link.
3. Call `AskUserQuestion` for the manual QA result (Pass / Fail / Skip — though Skip is rare, may be treated as Pass at the user's discretion).
4. Re-spawn this sub-agent with `Resume: qa-approved` (Pass) or `Resume: qa-failed` (Fail).

The re-spawn re-enters via §2 Resume short-circuit and jumps directly to §9 success branch (qa-approved) or §9 failure branch (qa-failed). All prior phases (work, reviews, /verify) are NOT re-run.

[PRESERVE — `spec/stage/test.md` Phase 3; SYNTHESIS-v2 T1.4; `design/stage-designs/test.md` §6/§12.]
[RETHINK — vs current arch]: v0.x's orchestrator handled this dialog directly. Arch B's split costs an extra spawn but preserves the "sub-agents non-interactive" invariant.

---

## §9. Phase 4 — Results review (label transition)

Two branches: success (qa-approved or skip-review.qa auto-approval) and failure (qa-failed).

### Success branch (qa-approved / skip-review.qa)

Entered from:
- §8 Case A (skip-review.qa auto-approved), OR
- §2 Resume short-circuit when `$3 == "qa-approved"`.

Steps (each its own simple Bash call):

1. Remove `sdd:test` label + add `sdd:done` label (atomic-ish — two simple Bash calls per Common Contracts §8):
   ```bash
   gh issue edit $1 --remove-label "sdd:test" --add-label "sdd:done"
   ```
2. Close the Issue:
   ```bash
   gh issue close $1
   ```

   If step 1 or 2 fails → return `FAIL: <reason>`; §10 unreached; no parent notification sent.

3. Check whether this Issue is a child (multilingual parent regex — see §10). If yes, execute §10 (Phase 5) child completion notification. If no (or if parsing returns no match), skip §10.

4. Return:
   ```
   >>> RESULT <<<
   OK DONE
   ```

### Failure branch (qa-failed)

Entered from:
- §2 Resume short-circuit when `$3 == "qa-failed"`.

Steps:

1. NO label transition. Leave label as `sdd:test`.
2. NO Issue close.
3. NO child notification (Issue is not done).
4. Return:
   ```
   >>> RESULT <<<
   OK BACK_TO_IMPLEMENT
   ```

Main session then surfaces `/sdd implement <N>` to the user (or auto-invokes for `/sdd auto`). On a future test stage re-entry (after fixes), §3 Phase 1 re-evaluates the (updated) PR and runs the AI review loop from scratch — the 3-round budget RESETS, not a continuation.

[PRESERVE — `spec/stage/test.md` Phase 4; label is authoritative state.]

---

## §10. Phase 5 — Child completion notification

Triggered inside §9 success branch step 3 when the just-completed Issue is a **child**. PARENT Issues skip §10 entirely (parent has no parent).

### Step 1: Detection

1. Read the Issue body (use the cached `gh issue view $1` result from §4.1 Step 1, or re-fetch):
   ```bash
   gh issue view $1 --json body --jq .body
   ```

2. Apply the multilingual parent regex (per `spec/02-multilingual.md` §3 / `<<SKILL_DIR>>/commands/atoms/_multilingual.md`):
   ```
   (Parent|상위 |親)Issue: #<n>
   ```
   Boundary safeguard: `([^0-9]|$)` after the number, so #683 doesn't match #6831.

3. If a match is found → this Issue is a child; capture parent's `<n>` as `<PARENT_N>`.
4. If no match → not a child; skip §10 entirely.

[PRESERVE — `spec/02-multilingual.md` §3; `_multilingual.md`.]

### Step 2: Update parent's children:output table row

1. Resolve owner/repo (already cached from §3, otherwise re-derive).

2. Fetch the parent's children:output comment id + body (per `implement.md` Phase 7 — use `(.body | contains("<!-- sdd:children:output -->")) and (.body | contains("<!-- /sdd:children:output -->"))` to match the most recent complete block):
   ```bash
   gh api repos/<owner>/<repo>/issues/<PARENT_N>/comments --jq '.[] | select((.body | contains("<!-- sdd:children:output -->")) and (.body | contains("<!-- /sdd:children:output -->"))) | {id, body}'
   ```
   - If no matching comment → log "parent #<PARENT_N> has no children:output comment; skipping notification" and skip Step 3/4. (Defensive — should not happen if Issue is a child.)
   - If multiple → use the highest id (most recent).

3. Take the existing body, replace this child Issue's row with the new "done" status in narrative (no shell tooling for the substitution).

4. **Write tool** → render the updated body into `/tmp/sdd-children-output-<PARENT_N>.md`.

5. **Bash** PATCH:
   ```bash
   gh api repos/<owner>/<repo>/issues/comments/<id> -X PATCH --field body=@/tmp/sdd-children-output-<PARENT_N>.md
   ```

### Step 3: Check if all children done

1. Re-parse the updated body — count "done" rows vs total rows.
2. Or, more robustly, re-check each child's actual label via `gh issue view <child> --json labels --jq '[.labels[].name]'` (one Bash call per child) and confirm all have `sdd:done`.

### Step 4: Notify parent if all children done

If ALL children are now `sdd:done`:

1. Detect parent's language (read `.github/.sdd-lang` or detect from parent's body — per `spec/02-multilingual.md` §2).

2. Compose the notification body (language-appropriate, per `spec/stage/test.md` Phase 5):
   - `en`: `All children complete; parent ready for /sdd test #<PARENT_N>.`
   - `ko`: `모든 하위 Issue 완료; 상위 Issue 준비 완료: /sdd test #<PARENT_N>.`
   - `ja`: `全ての子Issueが完了しました; 親Issue準備完了: /sdd test #<PARENT_N>。`

3. Post as a NEW (accumulating) comment on the parent — NOT marker-keyed:
   - **Write tool** → `/tmp/sdd-children-complete-<PARENT_N>.md` (overwrites prior temp from `implement.md` Phase 7 — fine).
   - **Bash**:
     ```bash
     gh issue comment <PARENT_N> --body-file /tmp/sdd-children-complete-<PARENT_N>.md
     ```
   No duplicate-prevention needed — each completion event is a new comment (per `implement.md` Phase 7).

If not all children done: report remaining children to the sub-agent narrative; do NOT post a comment. (`/sdd auto` outer loop's child auto-discovery picks up remaining children.)

[PRESERVE — `spec/stage/test.md` Phase 5; `design/stage-designs/test.md` §14; canonical implementation referenced from `implement.md` Phase 7.]

### Ordering

Within §9 success branch, §10 runs AFTER successful label transition + close:
1. `gh issue edit $1 --remove-label "sdd:test" --add-label "sdd:done"` [must succeed]
2. `gh issue close $1` [must succeed]
3. §10 (child detection + parent children:output update + completion notification if all done)
4. Return `OK DONE`

If step 1 or 2 fails → return `FAIL: <reason>`; §10 unreached.

---

## §11. Phase 6 — Output (return contract)

Final `>>> RESULT <<<` line. One of:

| Return | Triggering path |
|---|---|
| `OK DONE` | §9 success branch — label → sdd:done; Issue closed; child notification (if applicable) sent |
| `OK BACK_TO_IMPLEMENT` | §9 failure branch (Resume: qa-failed) — no label change; user routed to implement |
| `OK NEEDS_MANUAL_QA: <summary>` | §8 Case B — sub-agent paused for user manual-QA gate |
| `OK NEEDS_FRAMEWORK_CHOICE: recommended=<name>` | §4.1 Step 2 PARENT path — no E2E setup detected, framework recommendation surfaced |
| `OK PAUSE` | reserved — only emitted if main session re-spawns post-Pause and resume short-circuit immediately exits (rare; not directly reachable from first invocation per `design/stage-designs/test.md` §9) |
| `ESCALATE: <summary>` | §6 Phase 2.5 — Round 3 FAIL with skip-review.qa OFF |
| `FAIL: <reason>` | §1 / §3 / §4 / §7 / §9 atom-level error — main stops |

### Sentinel format [PRESERVE]

Every return ends with:
```
>>> RESULT <<<
<status> <fields>
```

The line BEFORE the sentinel may contain narrative — main session ignores until it sees the sentinel.

### Examples

```
>>> RESULT <<<
OK DONE
```

```
>>> RESULT <<<
OK BACK_TO_IMPLEMENT
```

```
>>> RESULT <<<
OK NEEDS_MANUAL_QA: SINGLE PR #42 — c=PASS q=PASS a=PASS, /verify=PASS, checklist=https://github.com/o/r/issues/40#issuecomment-1234567
```

```
>>> RESULT <<<
OK NEEDS_FRAMEWORK_CHOICE: recommended=playwright
```

```
>>> RESULT <<<
ESCALATE: test round 3 FAIL — findings: [critical] 1, [major] 2 (completeness=FAIL, quality=PASS, adversarial=FAIL)
```

```
>>> RESULT <<<
FAIL: #42 is a Pull Request, not an Issue
```

[PRESERVE — load-bearing: sentinel + literal status strings are parsed by main FSM. Do NOT reformat to JSON.]
[NEW — Arch B / SYNTHESIS-v2 T1.4]: `OK NEEDS_MANUAL_QA` and `OK NEEDS_FRAMEWORK_CHOICE` are stage_test-specific additions. Main-session contract validation (`design/01-sub-agent-contract.md` §9) accepts them for stage_test only.

---

## §12. Markers posted (must match `spec/stage/test.md` §2)

- `<!-- sdd:test:output -->` on **Issue** — test output (QA checklist + path label + PR/Integration PR refs). Posted by §4.1 Step 7. Updated in place by §6 (skip-review escalation addendum), §7 (`/verify` trace), §8 (skip-review.qa trace).
- `<!-- sdd:review:test:completeness -->` on **PR** (SINGLE) or **Issue** (PARENT) — Reviewer 1 verdict. Posted by §4.2.1.
- `<!-- sdd:review:test:quality -->` on **PR** (SINGLE) or **Issue** (PARENT) — Reviewer 2 verdict. Posted by §4.2.2.
- `<!-- sdd:review:test:adversarial -->` on **PR** (SINGLE) or **Issue** (PARENT) — Reviewer 3 verdict. Posted by §4.2.3.
- `<!-- sdd:review:parent -->` on **parent Issue** (PARENT path only) — Reviewer 4 verdict. Posted by §4.2.4.
- `<!-- sdd:findings:json -->` … `<!-- /sdd:findings:json -->` blocks embedded inside every review comment per Common Contracts §5 schema.

All posted via Section F temp-file pattern with deterministic paths (Common Contracts §9):
- `/tmp/sdd-test-output-$1.md`
- `/tmp/sdd-review-test-completeness-pr<PR_NUM>.md` (SINGLE) | `/tmp/sdd-review-test-completeness-$1.md` (PARENT)
- `/tmp/sdd-review-test-quality-pr<PR_NUM>.md` (SINGLE) | `/tmp/sdd-review-test-quality-$1.md` (PARENT)
- `/tmp/sdd-review-test-adversarial-pr<PR_NUM>.md` (SINGLE) | `/tmp/sdd-review-test-adversarial-$1.md` (PARENT)
- `/tmp/sdd-review-parent-$1.md` (PARENT only)
- `/tmp/sdd-children-output-<PARENT_N>.md` (Phase 5 update)
- `/tmp/sdd-children-complete-<PARENT_N>.md` (Phase 5 notification, accumulating — no duplicate-prevention)
- `/tmp/sdd-test-parent-$1.md` (PARENT integration PR body)

All review updates are in-place (duplicate-prevention search → PATCH if id found, else POST). Round-to-round overwrites the per-marker comment; prior round's body is lost from GitHub (Common Contracts §4 Update-in-place invariant).

---

## §13. Hard rules

- **Single sub-agent.** This file runs as ONE Agent-spawned sub-agent (per `design/01-sub-agent-contract.md`). It MUST NOT spawn further Agent calls. It MUST NOT spawn other sub-agents. (Architectural invariant per Common Contracts §12.)
- **Skill tool: only `/verify`.** Common Contracts §13 confirms sub-agents CAN invoke the Skill tool. The test stage uses ONLY `/verify` (§7 Phase 2.7), only on SINGLE/CHILD path, with graceful-skip on unavailable. `/code-review` and `/security-review` are implement-stage only.
- **No label changes outside §9.** This sub-agent does NOT call `gh issue edit ... --add-label` or `--remove-label` outside the §9 success branch (which transitions `sdd:test → sdd:done`). The failure branch (§9 qa-failed) makes NO label changes. The `<!-- sdd:children:output -->` PATCH in §10 is a comment update, not a label change.
- **No `AskUserQuestion`.** Sub-agents are non-interactive. The manual QA gate (§8) and Round 3 FAIL (§6) are surfaced via `OK NEEDS_MANUAL_QA:` and `ESCALATE:` respectively for main to handle.
- **No code commits on SINGLE path.** Test stage does not modify production code on the implementation PR; code changes for failing QA flow back to `implement` via the `qa-failed` branch. On PARENT INTEGRATION_PR path, the sub-agent MAY create a new `test/<parent-feature-name>` branch + commit + push + open a NEW PR for integration tests only (`spec/stage/test.md` §2 side effects).
- **Do NOT set Claude as co-author** in any git commit (PARENT integration PR creation). [PRESERVE — `test_work.md` line 231.]
- **All Bash calls follow `<<SKILL_DIR>>/commands/atoms/_bash_rules.md`.** No `&&`, `||`, `;`, `|`, `$(...)`, `VAR=$(...)`, redirections, or quoted variable expansion. No `find` against `/`, `~`, `/Users`, or paths outside the repo root.
- **All comment posting follows `<<SKILL_DIR>>/commands/atoms/_review_helpers.md` Section F.** Write tool → temp file → `gh issue comment --body-file <path>` / `gh pr comment --body-file <path>` / `gh api ... -X PATCH --field body=@<path>`. Inline `--body` with multi-line content is forbidden (Common Contracts §9). Integration PR body via `--body-file`, NEVER heredoc.
- **Independence invariant for reviewers.** Each reviewer (§4.2.1, §4.2.2, §4.2.3, §4.2.4) reasons from a fresh logical pass — only the work output + analyze/design outputs are shared inputs; no cross-visibility of verdicts. Work outputs are shared ground truth — no re-fetch (Reviewer 1 loads from temp file; Reviewers 2 and 3 reuse from context; §4.2.4 parent integration reviewer always fetches across Issues).
- **Retry rounds overwrite.** Per-marker comments are PATCHed in place across rounds (Common Contracts §4 Update-in-place invariant).
- **Stay within the repository.** Do not Read absolute paths outside the working tree. Do not modify files outside `.github/` or the working tree on SINGLE path. On PARENT INTEGRATION_PR path, Write/Edit are permitted for the integration test branch's new test files only. The Write tool is otherwise permitted ONLY for rendering comment bodies to the deterministic `/tmp/sdd-*-$1.md` paths.
- **Manual QA stays out of the sub-agent.** It is inherently human-in-the-loop and routed through main session via `OK NEEDS_MANUAL_QA` + `Resume: qa-approved` / `qa-failed`.

---

## §14. Cross-references

Specs: `spec/stage/test.md`, `spec/00-common-contracts.md`, `spec/02-multilingual.md`, `design/00-architecture.md`, `design/01-sub-agent-contract.md`, `design/stage-designs/test.md`, SYNTHESIS-v2 T1.4/T1.5. Rubrics: `test-{completeness,quality,adversarial}.md`, `parent-integration.md`. Helpers: `_preflight.md` (Light tier), `_review_helpers.md`, `_bash_rules.md`, `_multilingual.md`, `_test_evidence.md`.
- Phase 5 canonical implementation (referenced): `<<SKILL_DIR>>/commands/implement.md` Phase 7
