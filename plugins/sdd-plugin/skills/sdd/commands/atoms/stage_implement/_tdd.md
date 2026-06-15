# STAGE: implement — Phase 3 TDD pipeline (topic file)

Topic file read inline by `main.md` §7. Executes inside the same single sub-agent context — no Agent spawns. Iterates 4 TDD steps (Red → Green → Refactor → E2E) with per-step `tdd_step_review`, per-step 2-retry budget (3 attempts total), and the R9 sha-based idempotency check (SYNTHESIS-v2 T1.2).

> **Bash Command Execution**: every shell snippet below is its own simple Bash tool call. See `<<SKILL_DIR>>/commands/atoms/_bash_rules.md`.

---

## Inputs (held in narrative context from `main.md`)

- `$1` — Issue number.
- `<branch_name>` — feature branch (captured in `main.md` §6.4; already checked out).
- `<owner>/<repo>` — captured in `main.md` §2.
- `<parent_num>` — optional, from `main.md` §6.3 if child Issue.
- `depth` — from `main.md` §3.

## Return values (to `main.md`)

- `OK PROCEED e2e_skipped=<true|false>` — all 4 steps complete (or carried forward via skip-review). `main.md` continues to §8 PR Final.
- `FAIL: <reason>` — atom-level error from any step.

---

## §1. Pipeline overview

`spec/stage/implement.md` §5; `design/stage-designs/implement.md` §8 + §10.

```
For step_n in [1 (red), 2 (green), 3 (refactor), 4 (e2e)]:
    # §2 R9 idempotency
    idempotent, sha, evidence = step_idempotent(step_n, branch_name, $1)
    if idempotent:
        record (sha_step_n, test_evidence_step_n)
        if step_n == 3 and sha == EMPTY: record refactor_empty = true
        if step_n == 4 and sha == EMPTY: record e2e_skipped = true
        continue
    # §3..§6 fresh execution
    attempt = 1
    while attempt <= 3:
        result = run_step_atom_inline(step_n, retry = (attempt > 1))
        if result starts FAIL: return FAIL: <reason>
        if step_n == 3 and result == "OK REFACTOR EMPTY":
            record sha_step_3 = EMPTY, test_evidence_step_3 = NONE
            break  # review short-circuits to OK PASS — §5.5
        if step_n == 4 and result == "OK E2E_SKIPPED":
            record e2e_skipped = true
            break  # no review at all — §5.6
        review = run_step_review_inline(step_n, sha, test_evidence)
        if review == "OK PASS": break
        if review starts FAIL: return FAIL: <reason>
        # review == "OK FAIL: <summary>" → retry
        attempt += 1
    if attempt > 3:
        handle_step_exhaustion(step_n)  # §7
return OK PROCEED e2e_skipped=<bool>
```

Stage-internal state (held in narrative):
- `sha_step_<n>`, `test_evidence_step_<n>` for n ∈ 1..4.
- `e2e_skipped: bool` (defaults false).
- `refactor_empty: bool` (defaults false; informational).

---

## §2. R9 idempotency check (per step)

[NEW Phase B; per SYNTHESIS-v2 T1.2 + `design/stage-designs/implement.md` §14] — sha-from-evidence is the canonical idempotency mechanism. No commit-body marker (that path is dropped per T1.2).

Before invoking step `n`'s atom logic:

### §2.1 Fetch evidence marker

```bash
gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | select(.body | contains("<!-- sdd:test-evidence:step-<n> -->")) | .body'
```

(Substitute the literal `<n>` ∈ 1..4.)

- Empty → not idempotent. Return `(false, null, null)` and run fresh.
- Has body → continue §2.2.

### §2.2 Fetch review marker (must exist with PASS verdict)

```bash
gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | select(.body | contains("<!-- sdd:review:implement:step-<n> -->")) | .body'
```

- Empty → not idempotent (evidence present but review absent — prior attempt crashed mid-step; rerun step which will re-post both). Return `(false, null, null)`.
- Has body → parse the `<!-- sdd:findings:json -->` block (per `_review_helpers.md` Section B.4) and read `verdict`.
  - `verdict == "PASS"` → continue §2.3.
  - `verdict == "FAIL"` or unparseable → not idempotent (last review failed; rerun in retry mode). Return `(false, null, null)`.

### §2.3 Parse sha from evidence body

The evidence body shape (`_test_evidence.md` Step 2):
```
**Commit:** <sha>
**Reported counts:** TESTS: <p>/<t> FAILED: <f>
```

Parse `<sha>` and the `TESTS: <p>/<t> FAILED: <f>` substring from the body. Hold as `evidence_sha` and `evidence_test_string`.

### §2.4 Verify sha is reachable on current branch

```bash
git merge-base --is-ancestor <evidence_sha> HEAD
```

(Use the literal `<evidence_sha>`.)

- Exit 0 → sha is ancestor of HEAD; continue §2.5.
- Non-zero → branch divergence (force-push, reset, fresh branch). Not idempotent. Return `(false, null, null)`.

### §2.5 Verify commit subject matches step expectation

```bash
git log -1 --format=%s <evidence_sha>
```

Inspect the literal subject line and apply the heuristic:
- step_n == 1 (Red): subject MUST start with `test:` AND contain `(Red)` (case-sensitive — per `implement_red.md` step 8 commit format).
- step_n == 2 (Green): subject MUST start with `feat:` AND contain `(Green)`.
- step_n == 3 (Refactor): subject MUST start with `refactor:`.
- step_n == 4 (E2E): subject MUST start with `test:` AND contain `e2e`.

- Match → step is idempotently complete. Return `(true, <evidence_sha>, <evidence_test_string>)`. Set `sha_step_n = <evidence_sha>` and `test_evidence_step_n = <evidence_test_string>` in stage state. Skip to next step in pipeline.
- Mismatch → not idempotent. Return `(false, null, null)`.

### §2.6 Edge cases

- **REFACTOR EMPTY resumed** — no evidence marker exists (atom skips evidence post on EMPTY per `_test_evidence.md` "When to run"). §2.1 returns Empty → not idempotent → rerun step 3 which will re-detect EMPTY or produce a new refactor. Acceptable. Defer the sentinel-marker optimization to v1.1 (`design/stage-designs/implement.md` §14.3).
- **E2E_SKIPPED resumed** — no evidence marker. §2.1 returns Empty → not idempotent → rerun step 4 detection (cheap; artifact detection only). If still no E2E framework → re-skip. Self-idempotent without an explicit marker.

[PRESERVE per `design/stage-designs/implement.md` §14 — safety invariant: never skip if state uncertain. Re-running idempotent step costs ~5–15K tokens; running with stale state risks corruption.]

---

## §3. Step 3-1 — Red (inlined `implement_red` logic)

`spec/stage/implement.md` §4 Phase 3 step 1; source atom `commands/atoms/implement_red.md`.

### §3.1 Step 0 — Preflight (Code-focused) OR retry self-fetch

- **Attempt 1**: follow `<<SKILL_DIR>>/commands/atoms/_preflight.md` Section A — tier **Code-focused**, Section B item 4 only (target directory survey). For Red specifically, focus directory read on existing test patterns — fixtures, assertion style, mock setup. Apply Section D failure handling.
- **Attempts 2 / 3 (retry)**: SKIP the preflight item. Instead, execute `<<SKILL_DIR>>/commands/atoms/_review_helpers.md` Section C with marker `<!-- sdd:review:implement:step-1 -->` on Issue `$1`. Hold the sorted findings array (`critical → major → minor`) as `<retry-findings>` for §3.5 retry resolution. (Per `spec/edge-cases.md` §13 — saves ~30K tokens per retry round.)
  - If Section C returns `FAIL: ...` → return that line as this `_tdd.md` execution's result (`main.md` propagates).

### §3.2 Step 1 — Read context

```bash
git rev-parse --abbrev-ref HEAD
```

If not on `<branch_name>` → `git checkout <branch_name>`.

```bash
gh issue view $1
gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | select(.body | contains("sdd:design:output") or contains("sdd:implement:plan")) | .body'
```

Do NOT read the analyze output (`implement_red.md` Hard rules — design already incorporated those requirements).

### §3.3 Step 2 — Write failing test code

Edit / Write tool as needed. Cover:
- Main scenarios from the plan.
- Edge cases identified in the design.
- Specific, meaningful assertions (not just "no throw").

### §3.4 Step 3 — Run tests + capture evidence

Auto-detect test command from repo (`npm test`, `flutter test`, `pytest`, `cargo test`, `go test`, etc.) using context from preflight item 2 + repo files. Run the Bash command and **capture the full raw output** for §3.7's `_test_evidence.md` post.

From the output extract:
- `<passed>` — number of passing tests
- `<failed>` — MUST be ≥ 1 for Red
- `<total>` — passed + failed (+ skipped if shown)

If any number is unobtainable from the runner's output format → use `0` (the reviewer will flag missing evidence with `[major] test-evidence-missing`).

Confirm the failures are for the **right reasons** (assertion failures, not import errors).

### §3.5 Step 4 — Retry resolution check

If §3.1 fetched `<retry-findings>`, before committing verify every `critical` and `major` finding has been addressed in the failing tests. Read `minor` entries as supporting context (often pinpoint the specific assertion line a higher-severity finding referenced abstractly).

If resolving findings forces conceptual changes that break the Red invariant (`<failed>` ≥ 1), surface in the trace below.

### §3.6 Step 5 — Self-review + commit

Self-review (blockers only):
- [ ] Tests file syntactically valid (test runner can parse)
- [ ] Tests fail (Red confirmed: `<failed>` ≥ 1)
- [ ] No `skip` / `only` / `focus` markers left in
- [ ] No `console.log` / `print` / `dbg!` debug artifacts

Inspect repo convention from preflight item 2; commit:

```bash
git add <test-files>
git commit -m "test: <description> (Red)"
```

**No Claude as co-author** (per `spec/stage/implement.md` §9 + `implement_red.md` Hard rules).

Capture the new sha:
```bash
git rev-parse HEAD
```

Hold as `sha_step_1` and build `test_evidence_step_1 = "TESTS: <p>/<t> FAILED: <f>"`.

### §3.7 Step 6 — Post test-evidence via `_test_evidence.md`

Follow `<<SKILL_DIR>>/commands/atoms/_test_evidence.md` with inputs:
- `<n> = 1`
- `<sha> = sha_step_1` (literal value)
- `<passed>` / `<total>` / `<failed>` (literal)
- The full test runner output captured in §3.4

The procedure handles 50,000-char truncation (Step 1: first 2,000 + `... [truncated middle] ...` + last 8,000 if total > 50,000), Section F duplicate-prevention post, and Step 5 re-read verification.

If the procedure returns the failure described in its Step 5 — return `FAIL: test evidence comment not found after posting (step-1)` from this pipeline.

### §3.8 Return semantics for Red

If §3.3–§3.7 complete successfully → step result is `OK RED COMMIT: <sha> TESTS: <p>/<t> FAILED: <f>`. Continue to §6 step review.

Atom-level failure during §3.2–§3.7 → return `FAIL: <reason>` from this pipeline.

---

## §4. Step 3-2 — Green (inlined `implement_green` logic)

`spec/stage/implement.md` §4 Phase 3 step 2; source atom `commands/atoms/implement_green.md`.

Same structure as §3 with substitutions:

- **Retry marker**: `<!-- sdd:review:implement:step-2 -->`.
- **Step 0 retry**: identical pattern; preflight item 4 (Code-focused) on attempt 1; Section C self-fetch on retries.
- **Sanity step** (before writing code): run tests once to **confirm current Red state**.
- **Step 2 — Write minimal production code**:
  - **Minimal** — only what's needed to pass the tests; no speculative features.
  - Follow existing codebase patterns (Read/Grep on similar implementations).
  - Match existing style / naming conventions.
- **Step 3 — Run tests + capture evidence**:
  - `<failed>` MUST be 0 for Green.
  - Same number-extraction with `0` fallback rule.
- **Step 4 retry resolution**: address every critical/major in `<retry-findings>` from step-2 review.
- **Self-review blockers**:
  - [ ] All tests pass
  - [ ] No debug artifacts (`console.log`, `dbg!`, `print`, `breakpoint()`)
  - [ ] No TODO / FIXME inserted that should be tracked elsewhere
  - [ ] Code is in the file paths designed (no surprise locations)
- **Commit**: `git commit -m "feat: <description> (Green)"`. No Claude co-author.
- **Test-evidence post**: `_test_evidence.md` with `<n> = 2`.

Step result on success: `OK GREEN COMMIT: <sha> TESTS: <p>/<t> FAILED: 0`. Continue to §6 step review.

---

## §5. Step 3-3 — Refactor (inlined `implement_refactor` logic) + REFACTOR EMPTY

`spec/stage/implement.md` §4 Phase 3 step 3; source atom `commands/atoms/implement_refactor.md`.

### §5.1 Step 0 — Preflight or retry self-fetch

- Attempt 1: preflight item 4 (Code-focused) — focus directory read on structural patterns (extraction style, helper organization, naming).
- Retries: Section C self-fetch with marker `<!-- sdd:review:implement:step-3 -->`.

### §5.2 Steps 1–2 — Verify Green + refactor

Verify branch + Green state (run tests; confirm `<failed>` == 0).

Apply refactor:
- Remove duplication (DRY).
- Improve naming (intention-revealing).
- Simplify control flow.
- Clean up imports, unused vars, dead code.
- Remove debug artifacts.
- **Behavior MUST remain identical** — tests verify this.

### §5.3 Step 3 — Run tests + sanity check counts

Capture `<passed>` / `<total>` / `<failed>`. `<failed>` MUST be 0 to keep Green.

**Sanity rule**: `<passed>` and `<total>` MUST match the values reported by `sha_step_2` (the prior Green commit) — UNLESS test files were edited in this refactor's diff. A change in `<total>` without a corresponding test-file edit signals tests were silently added/removed; fix before committing.

### §5.4 REFACTOR EMPTY branch

Check whether there's anything to commit:

```bash
git diff --staged --quiet
```

(Caller must have already `git add`-ed any changes. If no `git add` was done yet because no refactor happened, `--staged` will be empty.)

Alternative — check the working tree for changes since the Green commit:

```bash
git diff <sha_step_2> --quiet
```

- Exit 0 (no diff) → refactor not needed. Skip commit. Record:
  - `sha_step_3 = EMPTY`
  - `test_evidence_step_3 = NONE`
  - `refactor_empty = true`
  - Step result is `OK REFACTOR EMPTY`. **DO NOT** post test-evidence (`_test_evidence.md` "When to run" — refactor empty has no test claim to verify).
  - Skip §6 step review for this step (§6.5 short-circuits to `OK PASS` per `tdd_step_review.md` step 1).

- Non-zero (diff present) → continue §5.5.

### §5.5 Non-empty refactor — commit + evidence

Retry resolution check (if retries): address every critical/major in `<retry-findings>`.

Self-review (blockers only):
- [ ] All tests still pass
- [ ] No new debug artifacts
- [ ] No premature abstractions introduced (interface for one impl, factory for one type)
- [ ] No new TODO / FIXME

```bash
git add <files>
git commit -m "refactor: <description>"
```

No Claude co-author. Capture `sha_step_3 = git rev-parse HEAD`. Build `test_evidence_step_3 = "TESTS: <p>/<t> FAILED: 0"`.

Post test-evidence via `_test_evidence.md` with `<n> = 3`.

Step result on success: `OK REFACTOR COMMIT: <sha> TESTS: <p>/<t> FAILED: 0`. Continue to §6 step review.

---

## §6. Step 3-4 — E2E (inlined `implement_e2e` logic) + E2E_SKIPPED

`spec/stage/implement.md` §4 Phase 3 step 4; source atom `commands/atoms/implement_e2e.md`.

### §6.1 Step 0 — Preflight or retry self-fetch

- Attempt 1: preflight item 4 (Code-focused) — focus directory read on existing E2E test files (framework: Playwright/Cypress/Puppeteer/Flutter integration_test/etc., fixture patterns, page-object usage, waiting strategy).
- Retries (only relevant if §6.2 took the E2E path on attempt 1): Section C self-fetch with marker `<!-- sdd:review:implement:step-4 -->`.

### §6.2 Step 2 — Detect existing E2E setup

Use Read / Grep / Glob (not Bash `find`) to look for:
- E2E framework artifacts: `playwright.config.*`, `cypress.config.*`, `e2e/` directory, `integration_test/` (Flutter), `tests/e2e/`.
- `package.json` scripts named `test:e2e`, `e2e`, `cy:run`, etc.

### §6.3 Branch 3a — E2E setup exists

- Read 1–2 existing E2E test files to learn patterns.
- Write E2E tests for the implemented feature, matching existing framework conventions (page objects, fixtures, waiting strategy — **no sleep-based waits**, use condition-based waits).
- Run the E2E command. Capture `<passed>` / `<total>` / `<failed>` (`<failed>` MUST be 0). Capture full E2E runner output.
- Retry resolution check: address every critical/major in `<retry-findings>`.
- Self-review (blockers only):
  - [ ] E2E tests follow existing framework patterns
  - [ ] E2E tests pass
  - [ ] No `sleep(...)` / `waitFor(500)` — condition-based waits only
  - [ ] No skip / disable markers
- Commit: `git add <e2e-files>` → `git commit -m "test: e2e for <feature>"`. No Claude co-author. Capture `sha_step_4`. Build `test_evidence_step_4 = "TESTS: <p>/<t> FAILED: 0"`.
- Post test-evidence via `_test_evidence.md` with `<n> = 4`.
- Step result: `OK E2E COMMIT: <sha> TESTS: <p>/<t> FAILED: 0`. Continue to §7 step review.

### §6.4 Branch 3b — No E2E setup

- Do NOT install new E2E frameworks — that's a stage_test decision with user confirmation (`implement_e2e.md` Hard rules).
- No commit. Record `e2e_skipped = true` and `sha_step_4 = EMPTY`, `test_evidence_step_4 = NONE`.
- Step result: `OK E2E_SKIPPED`. **DO NOT** post test-evidence. **DO NOT** run step review for this step (entirely skipped per `spec/stage/implement.md` §4 Phase 3 step 1; `design/stage-designs/implement.md` §10.6).
- After §6.4 the pipeline continues directly to §1's loop exit / Return: `OK PROCEED e2e_skipped=true`.

---

## §7. Step review (`tdd_step_review`) — inlined per step

`spec/stage/implement.md` §5; source atom `commands/atoms/tdd_step_review.md`. Run after each step's atom returns a successful commit (NOT for REFACTOR EMPTY, NOT for E2E_SKIPPED).

Inputs (held in narrative):
- `step_n` ∈ {1, 2, 3, 4}.
- `<sha>` = `sha_step_<n>` (or `EMPTY`).
- `<test-evidence>` = `test_evidence_step_<n>` (or `NONE`).

### §7.1 Handle empty / skipped cases

- `<sha> == EMPTY` AND `<test-evidence> == NONE` → step review immediately returns `OK PASS` per `tdd_step_review.md` step 1 (REFACTOR EMPTY short-circuit). No comment posted. **Distinction**: REFACTOR EMPTY → review returns PASS (this case). E2E_SKIPPED → review is **entirely skipped** at the pipeline level (§6.4 — no `tdd_step_review` call at all). [PRESERVE — load-bearing per `design/stage-designs/implement.md` §10.5 + §10.6.]

### §7.2 Read commit diff + test evidence

```bash
git show --stat <sha>
git show <sha>
```

Then read the test-evidence comment:

```bash
gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | select(.body | contains("<!-- sdd:test-evidence:step-<n> -->")) | .body'
```

(Substitute literal `<n>`.)

- Empty AND `<sha> != EMPTY` AND `<test-evidence> != NONE` → record finding `[major] rule_id: test-evidence-log-missing` ("work atom did not post raw test runner output; reported counts are unverifiable"). **Continue to §7.4 — do NOT return early.** This is a load-bearing nuance: `spec/stage/implement.md` §5 Step 5a from Reviewer A GAP-A1 — a "fail fast" rewrite would silently lose post-detection criteria evaluations.
- Has body → hold as `<evidence-log>` for §7.5.

### §7.3 Read rubric

Read `<<SKILL_DIR>>/commands/atoms/rubrics/implement-step.md`. Use the section matching `step_n`:
- `step_n == 1` → "Step 3-1: Red"
- `step_n == 2` → "Step 3-2: Green"
- `step_n == 3` → "Step 3-3: Refactor"
- `step_n == 4` → "Step 3-4: E2E"

### §7.4 Codebase exploration (lighter budget)

Per `<<SKILL_DIR>>/commands/atoms/_review_helpers.md` Section D: max **5 Read / 3 Grep / 0 Glob**. Use sparingly — quick diff review, not a full audit.

### §7.5 Apply step criteria + test-evidence consistency check (§5a)

Severity definitions:
- **critical** — step is broken in a way that compounds into the next step
- **major** — significant issue in this step that should be fixed before proceeding
- **minor** — improvement suggestion (does not block)

**Test-evidence consistency check (Step 5a) — load-bearing trust boundary** [PRESERVE — `spec/stage/implement.md` §5 — system's only defense against an LLM work atom hallucinating "tests pass"]:

You cannot re-run tests in this review. Verify the work atom's self-reported counts against the captured raw log:

- If `<test-evidence> == "NONE"` and `<sha> == "EMPTY"` → skip this check.
- If `<test-evidence>` missing / empty / unparseable as `TESTS: <int>/<int> FAILED: <int>` → finding `[major] rule_id: test-evidence-missing`.
- `step_n == 1` (Red): if `FAILED` is `0` → finding `[critical] rule_id: red-tests-did-not-fail`.
- `step_n ∈ {2, 3, 4}` (Green / Refactor / E2E): if `FAILED` is non-zero → finding `[critical] rule_id: tests-not-green`.
- `step_n == 3` (Refactor only): if the diff does NOT touch any file under a test directory (no `*test*` / `*spec*` paths) but `TESTS: <p>/<t>` differs from the prior Green's reported counts → finding `[critical] rule_id: refactor-changed-test-counts`.
  - **Graceful fallback (GAP-A3)**: to verify drift, search Issue comments for the latest `<!-- sdd:review:implement:step-2 -->` block and parse the `Tests:` field. If unavailable → **downgrade to `[major]`**. [PRESERVE — preserves recovery when round-1 step-2 review was rotated out.]
- Sanity bound: `<total> == 0` AND `<sha> != EMPTY` → finding `[major] rule_id: zero-tests-executed`.

**Raw-log cross-check** (applies only when `<evidence-log>` was found in §7.2):
- Inspect the fenced code block inside the test-evidence comment. Look for the runner's summary line — formats vary (jest `Tests: <p> passed, <f> failed`, pytest `passed=<p> failed=<f>`, junit `<total> tests ... <failed> failures`, TAP `ok <n>` / `not ok <n>`, etc.). Read and judge framework-agnostically.
- **Count mismatch**: identifiable summary line disagrees with `<test-evidence>` → finding `[critical] rule_id: test-evidence-mismatch`. Include observed log line in description.
- **Failure-line presence (Red only)**: `step_n == 1` — log MUST contain at least one failure indicator (assertion error, `FAIL` marker, stack trace, `not ok`). If absent → finding `[critical] rule_id: red-log-shows-no-failure`.
- **Authenticity check**: log under 200 chars / lacks any file path or test name / lacks any framework marker → finding `[major] rule_id: test-evidence-implausible`.
- **Summary unparseable**: log present and plausibly authentic but no summary line locatable → finding `[minor] rule_id: test-evidence-summary-unparseable`. **Explicit non-blocking escape hatch — DO NOT BLOCK ON THIS** [PRESERVE — GAP-A2, per `spec/stage/implement.md` §5: "runners differ widely"; a rewrite that ignores this preserve would mis-classify when summary detection fails on a legitimate run.].

### §7.6 Verdict

- critical or major in findings → **FAIL** (one-line summary).
- only minor or none → **PASS**.

### §7.7 Post review comment on Issue via Section F

Marker: `<!-- sdd:review:implement:step-<n> -->`. Substitute the literal `<n>`. Temp path: `/tmp/sdd-review-implement-step-<n>-$1.md`.

Body (per `tdd_step_review.md` step 7):
```
<!-- sdd:review:implement:step-<n> -->
## AI Review (implement / step-<n>)

**Verdict:** PASS | FAIL
**Model:** opus
**Commit:** <sha>
**Tests:** <test_evidence_step_n verbatim, or "NONE">

### Issues
- **[critical]** path/to/file.ts:42 — <description>
- **[major]** <description>
- **[minor]** <description>

### Suggestions
<if any>

<!-- sdd:findings:json -->
```json
{<structured findings per _review_helpers.md Section B.2, stage="implement", role="step-<n>", issue=<$1>, pr=null, round=<attempt>, verdict, model="opus", findings, suggestions>}
```
<!-- /sdd:findings:json -->
<!-- /sdd:review:implement:step-<n> -->
```

Procedure (Section F):
1. **Write tool** → temp file `/tmp/sdd-review-implement-step-<n>-$1.md`.
2. **Bash** duplicate-prevention search:
   ```bash
   gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | select(.body | contains("<!-- sdd:review:implement:step-<n> -->")) | .id'
   ```
3. **Bash** branch:
   - Empty → `gh issue comment $1 --body-file /tmp/sdd-review-implement-step-<n>-$1.md`
   - Has id `<id>` → `gh api repos/<owner>/<repo>/issues/comments/<id> -X PATCH --field body=@/tmp/sdd-review-implement-step-<n>-$1.md`

### §7.8 Return semantics

- `verdict == PASS` → step review returns `OK PASS`. Pipeline advances to next step.
- `verdict == FAIL` → step review returns `OK FAIL: <summary>`. Pipeline re-invokes the step atom in retry mode (attempt += 1).
- Any unrecoverable error (gh API failure, rubric load failure) → return `FAIL: <reason>` from this pipeline (`main.md` propagates).

---

## §8. Per-step exhaustion (attempt > 3)

[Per `design/stage-designs/implement.md` §10.7 — Arch B Option 2 behavior shift documented in `spec/stage/implement.md` §20.5.]

Triggered when a step's 2-retry budget is consumed without `OK PASS`.

### §8.1 Post unresolved findings summary on Issue

Compose a comment listing remaining critical/major findings from the final round's `<!-- sdd:review:implement:step-<n> -->`. Use Section F (Write tool → `/tmp/sdd-implement-step-exhaustion-$1-step-<n>.md` → search for an existing exhaustion marker or post new). Marker: `<!-- sdd:implement:step-exhaustion -->` (non-canonical; this is informational only, not consumed by other atoms).

Alternative simpler path: rely on the latest `<!-- sdd:review:implement:step-<n> -->` comment (already on the Issue, contains the findings JSON) — narrative-log the exhaustion event without posting a new marker. The latest review marker IS the audit trail.

### §8.2 Branch on `skip-review: implement`

Read `.github/.sdd-config` (Read tool — file or key absent → empty). Parse comma-separated `skip-review:` entries.

- **`implement` IS in skip-review** → log to sub-agent narrative: "⚠ TDD step-<n> failed review 3 times. Auto-continuing because `skip-review: implement` is set; unresolved findings carry forward to PR Final." Continue pipeline to next step (Arch B Option 2 — soft step exhaustion).
- **`implement` is NOT in skip-review** → Arch B Option 2 default: same auto-continue with a logged warning. Sub-agent cannot ask user (`design/01-sub-agent-contract.md` §4); PR Final (the harder gate) is reserved for the ESCALATE return.

[PRESERVE — behavior shift documented in `spec/stage/implement.md` §20.5: spec says interactive → ask user; Arch B can't ask. The hard gate moves entirely to PR Final round 3.]

---

## §9. Pipeline-level early return

If any step's atom logic OR step review returns `FAIL: <reason>` (atom error — gh API failure, evidence post failure, rubric load failure, Section C retry-slot rejection, etc.) → return that `FAIL: ...` line from this `_tdd.md` execution. `main.md` propagates as the sub-agent's overall return.

Sub-step `OK FAIL: <summary>` (verdict failure) is NOT an early-return — it triggers an attempt retry. Only `FAIL:` (atom error, not prefixed by `OK`) escapes the pipeline.

---

## §10. Pipeline success — return value

After step 3-4 completes (or §6.4 short-circuits to `OK E2E_SKIPPED` after §3 + §4 + §5 already PASSed), return to `main.md` §7 caller:

```
OK PROCEED e2e_skipped=<true|false>
```

Stage-internal state held in narrative for `_pr_final.md` (read by `main.md` §8):
- `sha_step_1`, `sha_step_2`, `sha_step_3` (possibly `EMPTY`), `sha_step_4` (possibly `EMPTY`).
- `test_evidence_step_<n>` (possibly `NONE`).
- `e2e_skipped: bool`.

---

## Hard rules (this topic file)

- **No Agent spawns, no Skill calls** in this file. (Skills are reserved for `_pr_final.md`'s Phase 5 reviewers; `_tdd.md` only commits + posts evidence/reviews.)
- **No `git push`.** Pushing is `_pr_final.md`'s job. `_tdd.md` commits only.
- **No force-push, no `--amend`.** Retry mode = new commit on the failed step (the prior failed commit stays; `git reset` to clean is NOT used because review history is preserved). However, on a retry attempt the work atom MAY overwrite the prior attempt's commit by addressing findings then `git commit --amend`? **NO** — explicit invariant. The retry pattern adds a NEW commit (the test/code/refactor file is edited again, then a fresh commit). If the prior commit's diff was wrong, the new commit either reverts + corrects or supersedes; the prior commit stays on the branch. [PRESERVE per `spec/stage/implement.md` §9.]
- **No Claude as co-author** in any commit.
- **All Bash per `_bash_rules.md`.** All comment posting per `_review_helpers.md` Section F. Test-evidence per `_test_evidence.md`.
- **Edit / Write tool permitted** here for writing test code, production code, and refactors (to working tree files); also for the deterministic `/tmp/sdd-*.md` temp paths. NEVER modify files outside the working tree.
- **Independence does NOT apply.** Step reviews are sequential; the step review CAN read prior step's evidence (it does — §7.5 Refactor cross-checks step-2's review). Independence is a PR Final invariant only (`_pr_final.md`).
