# Stage Design: stage_implement

Design for the `stage_implement` sub-agent (Arch B). LARGEST of the four stage
designs — inlines 6 work atoms (`implement_{plan,red,green,refactor,e2e,pr}`),
4 step reviewers (`tdd_step_review` × 4), 3 PR-Final reviewers (`implement_review`
completeness/quality + `implement_adversarial`), 2 Skill invocations
(`/code-review`, `/security-review`), plus a 3-round PR-Final retry loop, a
per-step 2-retry budget, R8 (empty-`$3` + existing-PR) auto-routing, R9 (TDD
step idempotency), and Phase 7 child-completion notification.

Source spec: `spec/stage/implement.md`. Phase B foundations:
`design/00-architecture.md`, `design/01-sub-agent-contract.md`,
`design/02-file-layout.md`.

---

## §1. Stage Inputs

### Prompt from main session (per `01-sub-agent-contract.md` §1)

```
Read <<SKILL_DIR>>/atoms/stage_implement.md and execute its instructions
for Issue #<N>.

Inputs:
  Issue:    #<N>
  Depth:    <default|deep|shallow>
  Branch:   <branch-name|null>   # populated only on resume
  PR:       #<PR_NUM|null>       # populated only on resume
  Resume:   <none|continue-after-escalation>
```

[PRESERVE — load-bearing]: stage sub-agent re-reads GitHub for the source of
truth. Inputs above are CACHE HINTS, not authoritative.

### Preconditions verified at boot

| Check | On failure |
|---|---|
| Issue Validation per Common Contracts §10 | `FAIL: #$1 is a Pull Request, not an Issue` |
| `<!-- sdd:design:output -->` exists on Issue | `FAIL: design output not found on Issue #$1` |
| `gh repo view --json nameWithOwner` succeeds | `FAIL: gh CLI not authenticated for current repo` |

### Environmental dependencies

- `.github/.sdd-lang` — language for plan + PR body (fallback en).
- `.github/.sdd-config` — 3 skip-review keys consumed: `implement`, `pr`, `qa`.
  Sub-agent reads but mostly defers user-gate decisions to main session per
  `01-sub-agent-contract.md` §4.
- Issue labels — `sdd:review:deep`, `sdd:review:shallow`, `sdd:implement`.
- Test runner — auto-detected (`npm test`, `flutter test`, `pytest`, etc.).
- E2E framework artifacts (`playwright.config.*`, `cypress.config.*`, `e2e/`,
  `integration_test/`, `tests/e2e/`).

### Parent/Child context

Multilingual regex `(Parent|상위 |親)Issue: #([0-9]+)([^0-9]|$)` inside
`<!-- sdd:child-issue -->` block (Common Contracts §2; multilingual §3). Drives:
- Branch naming (`feat/<parent>/<child>` vs `feat/<feature>`).
- PR body localized parent line.
- Phase 7 child-completion target.

[PRESERVE — load-bearing]: boundary class `([^0-9]|$)` prevents `#683` matching
`#6831` (edge-cases §1). 5+ callers.

---

## §2. Stage Outputs

### Markers posted

| Marker | Scope | Posted by |
|---|---|---|
| `<!-- sdd:implement:plan -->` | Issue | §6 Phase 2 |
| `<!-- sdd:test-evidence:step-<n> -->` (n∈1..4) | Issue | §10 (via `_test_evidence.md`) |
| `<!-- sdd:review:implement:step-<n> -->` (n∈1..4) | Issue | §10 step review |
| `<!-- sdd:review:implement:completeness -->` | PR | §12 PR Final |
| `<!-- sdd:review:implement:quality -->` | PR | §12 PR Final |
| `<!-- sdd:review:implement:adversarial -->` | PR | §12 PR Final |
| `<!-- sdd:review:implement:tools -->` | PR | §12 tools-summary (in-place per round) |

[PRESERVE — load-bearing]: TDD step reviews go on **Issue** (PR may not exist
during Phase 3). PR Final reviews + tools-summary go on **PR**.

### Return contract (per `01-sub-agent-contract.md` §2)

| Return | Meaning |
|---|---|
| `OK ADVANCE: test PR: #N BRANCH: <name>` | TDD + PR Final passed; main → `sdd:test` |
| `OK ADVANCE: test PR: #N BRANCH: <name> E2E_SKIPPED` | Same + E2E flag for stage_test |
| `OK PARENT_STOP` | Parent Issue; main queues children |
| `OK PAUSE` | Stopped non-error; user resumes later |
| `ESCALATE: <summary>` | Round 3 PR Final FAIL interactive; main asks user |
| `FAIL: <reason>` | Atom-level error; main stops |

[NEW for Arch B]: `OK ADVANCE` carries BOTH `PR: #N` and `BRANCH: <name>` so
main session threads both to stage_test without re-deriving from GitHub.

### Labels — sub-agent does NOT transition

Label transitions are main session's job (`01-sub-agent-contract.md` §4).

### Side effects produced

- Feature branch on local + origin.
- Up to 4 TDD commits + 0..N retry fix-up commits.
- PR created (first-round) or updated (retry mode) with `Refs #$1`.
- Phase 7 only: parent's children comment updated; optional completion notification.

### Side effects NOT produced

- No `sdd:done`, no Issue close (stage_test's job).
- No force-push, no `git commit --amend` (retry appends new commits).
- No E2E framework install (stage_test's call).
- No Claude co-author in any commit.

---

## §3. Atom Inventory (inlined into stage_implement)

| Atom | Source | Role in sub-agent |
|---|---|---|
| `implement_plan` | `atoms/implement_plan.md` | §6 Phase 2 |
| `implement_red` | `atoms/implement_red.md` | §10 step 3-1 |
| `implement_green` | `atoms/implement_green.md` | §10 step 3-2 |
| `implement_refactor` | `atoms/implement_refactor.md` | §10 step 3-3 |
| `implement_e2e` | `atoms/implement_e2e.md` | §10 step 3-4 |
| `implement_pr` | `atoms/implement_pr.md` | §11 Phase 4 (first-round) + §12 (retry) |
| `tdd_step_review` × 4 | `atoms/tdd_step_review.md` + `rubrics/implement-step.md` | §10 each step |
| `implement_review` (completeness) | `atoms/implement_review.md` + `rubrics/implement-completeness.md` | §12 5.N.1.a |
| `implement_review` (quality) | same + `rubrics/implement-quality.md` | §12 5.N.1.b |
| `implement_adversarial` | `atoms/implement_adversarial.md` + `rubrics/implement-adversarial.md` | §12 5.N.1.c |

Skills (NOT atoms — invoked via Skill tool):
- `/code-review` — §12 5.N.2
- `/security-review` — §12 5.N.3

[PRESERVE — Common Contracts §12]: single-level spawn. All atoms are inlined
into stage_implement's own context (no nested Agent calls).

---

## §4. Phase Map

```
Phase 0  Depth detection
Phase 1  Parent/child classification → OK PARENT_STOP possible
Phase 2  Plan (§6) → branch_name captured
Phase 3  TDD pipeline 3-1..3-4 (§10) → R9 idempotency skip per step
Phase 4  PR creation (§11) → pr_num captured; R8 existing-PR routing
Phase 5  PR Final review loop (§12) → 3 rounds
Phase 5.5 Round 3 escalation gate → ESCALATE possible
Phase 6  NO-OP in sub-agent (label transition is main's job)
Phase 7  Child completion notification (§16) — only for already-sdd:done child Issue re-entry
```

**Note on Phase 6 in Arch B**: spec's Phase 6 sets `sdd:test` and conditionally
auto-proceeds to `test.md`. In Arch B, both move to main session — sub-agent
just returns `OK ADVANCE`.

---

## §5. Phase 0 — Depth Detection

| Label | Depth |
|---|---|
| `sdd:review:deep` | `deep` |
| `sdd:review:shallow` | `shallow` |
| Neither | `default` |

Depth-driven values:

| Component | default | deep | shallow |
|---|---|---|---|
| Producer atoms (plan, red, green, refactor, e2e, pr) model | opus | opus | opus |
| `tdd_step_review` step 1/4 model | sonnet | opus | haiku |
| `tdd_step_review` step 2/3 model | haiku | opus | haiku |
| `implement_review` completeness/quality model | sonnet | opus | sonnet |
| `implement_adversarial` model | opus | opus | sonnet |
| `/code-review` `--effort` | `high` | `max` | `medium` |
| `/security-review` | ran | ran | **SKIP (shallow-label-skip)** |

[RETHINK — spec §3]: step 2/3 default haiku vs step 1/4 sonnet. Phase C
decision; preserve current mapping for v1.0.0.

[NEW for Arch B — IMPORTANT]: in Arch B, "models" above are role guidance, not
Agent spawns. Single-level spawn forbids nested Agent calls from inside a
sub-agent, so each inlined reviewer is a serial pseudo-call within
stage_implement's context. The model column becomes **informational** at runtime
(sub-agent runs at one model). The values DO drive `/code-review --effort` and
shallow-skip on `/security-review`. Document in stage_implement.md preamble so
future maintainers don't try to "use" the model column.

---

## §6. Phase 2 — Plan (inline `implement_plan`)

### Step 2.1 — Generate plan

Inline `implement_plan` logic (source `atoms/implement_plan.md`):
1. **Preflight** (_preflight.md Medium tier default/deep, Light shallow):
   project conventions, file structure, test framework, skip-review cache.
2. **Read design output** `<!-- sdd:design:output -->` — File Structure (target
   dir), Testability (mock strategy), Test Strategy (drives test plan).
3. **Branch creation**:
   - Branch name: single `feat/<feature>` or child `feat/<parent>/<child>`.
   - Inspect `git log --oneline -20`; follow repo convention if different.
     [PRESERVE — load-bearing for project conformance.]
   - Existing branch: `git rev-parse --verify <branch>` → if exists, `git checkout
     <branch>` (no `-b`); else `git checkout -b <branch>`.
   - Capture `branch_name` as stage-internal state.
4. **Plan body** in `.github/.sdd-lang` language: test plan + impl plan.
5. **Post plan**: Write to `/tmp/sdd-implement-plan-$1.md`. Section F search
   `<!-- sdd:implement:plan -->`:
   - Empty → `gh issue comment $1 --body-file /tmp/sdd-implement-plan-$1.md`
   - Has id → `gh api repos/<owner>/<repo>/issues/comments/<id> -X PATCH --field body=@/tmp/sdd-implement-plan-$1.md`
6. **Self-review** (atom blocker check): verify branch checked out, plan posted,
   design output parsed. Any blocker → `FAIL: <specific reason>`.

### Step 2.2 — User confirmation handoff

Per `01-sub-agent-contract.md` §4, sub-agent never calls AskUserQuestion.

[NEW for Arch B vs spec]: spec's Phase 2.2 prompts user inline. In Arch B,
sub-agent proceeds directly to Phase 3 after posting plan. Implicit-consent
model — main session pre-confirms via `skip-review: implement` OR via the
design stage's exit gate. Behavior shift documented in §17.

[RETHINK]: alternative — return `OK PLAN_READY` and re-spawn after confirmation.
REJECTED: doubles sub-agent boot cost. Accept implicit-consent model.

---

## §7. Phase 1 — Parent/Child Classification

### 7.1 Resolve owner/repo

```bash
gh repo view --json nameWithOwner -q .nameWithOwner
```

Inline the literal `<owner>/<repo>` into all subsequent `gh api repos/<owner>/<repo>/...`
calls. [PRESERVE — Common Contracts §11].

### 7.2 Detect children

```bash
gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | select(.body | contains("<!-- sdd:children:output -->")) | .id'
```

- Empty → not a parent → Phase 2.
- Has id → parent → §7.3.

### 7.3 Parent branch

| `skip-review: implement` | Action |
|---|---|
| Set | Log + return `OK PARENT_STOP` |
| Not set (interactive) | Sub-agent CANNOT ask user. Return `OK PARENT_STOP`; main session asks which child next |

[PRESERVE — load-bearing]: in current spec this is inline `commands/resume.md`.
Arch B: sub-agent surfaces PARENT_STOP; main's auto.md / status / resume
dispatcher takes over.

---

## §8. Phase 3 Overview — TDD Step Pipeline

See §10 for per-step detail. Phase 3 iterates 3-1..3-4 in order. Each step has
2-retry budget (3 attempts total).

```
For step_n in [1 (red), 2 (green), 3 (refactor), 4 (e2e)]:
    if R9_idempotency_skip(step_n, branch_name):    # see §14
        continue
    attempt = 1
    while attempt <= 3:
        result = run_step_atom_inline(step_n, retry = (attempt > 1))
        if result starts FAIL: return FAIL: <reason>
        if step_n == 4 and result == "OK E2E_SKIPPED":
            e2e_skipped = true; break  # no review
        if step_n == 3 and result == "OK REFACTOR EMPTY":
            break  # review short-circuits to OK PASS — §10.5
        review = run_step_review_inline(step_n, sha, test_evidence)
        if review == OK PASS: break
        if review starts FAIL: return FAIL: <reason>
        # review == OK FAIL → retry
        attempt += 1
    if attempt > 3:
        handle_step_exhaustion(step_n)  # §10.7
```

Notes:
- "spawn" of step atom and step review in current architecture becomes inline
  pseudo-calls — no nested Agent calls.
- `<sha>` and `<test-evidence>` threading lives entirely inside stage_implement;
  main session never sees them.

---

## §9. Phase 4 + Phase 5 Overview

- **Phase 4** (§11) — Inline `implement_pr` first-round mode. Modes:
  - First-round + no PR → create.
  - First-round + PR exists → **R8 NEW**: auto-route to retry-like flow (Option
    A default) or `FAIL` with clear instruction (Option B if config set).
  - Retry round N + PR exists → retry mode (§12 entry into §11.2).
  - Retry round N + no PR → defensive `FAIL`.

- **Phase 5** (§12) — 3-round PR Final review loop:
  - 3 SDD reviewers serial (5.N.1.a/b/c) + `/code-review` (5.N.2) +
    `/security-review` (5.N.3) + tools-summary (5.N.4) + verdict (5.N.5).
  - PASS → exit, return `OK ADVANCE`.
  - FAIL rounds 1-2 → retry mode → next round.
  - FAIL round 3 → §12.9 escalation gate (ESCALATE to main or auto-continue).

---

## §10. Special Section — TDD Step Pipeline Detail (3-1..3-4)

### 10.1 Step-atom inline expansion

Common structure per step:
1. **Preflight** Light tier on round 1; SKIP on retry (edge-cases §13 — saves
   ~30K tokens per failed step).
2. **Read plan** `<!-- sdd:implement:plan -->`.
3. **Read prior step context**:
   - Red: design output testability section.
   - Green: Red's test files via `git diff HEAD~1`.
   - Refactor: Green's diff via `git diff HEAD~1`.
   - E2E: design output e2e section, existing e2e dir, runner config.
4. **Branch verify**: `git rev-parse --verify <branch_name>` + `git status`.
5. **Edit/write files** per step:
   - Red: failing tests.
   - Green: minimal production code.
   - Refactor: cleanup keeping tests green (or `OK REFACTOR EMPTY`).
   - E2E: e2e tests (or `OK E2E_SKIPPED` after detection).
6. **Run tests**: capture raw output for `_test_evidence.md`.
7. **Verify step expectation**:
   - Red: ≥1 failure (else `FAIL: red tests did not fail as expected`).
   - Green/Refactor/E2E: all pass (else `FAIL: tests failed after <step>`).
8. **Commit** with step prefix (no Claude co-author):
   - Red: `test: <description> (Red)`
   - Green: `feat: <description> (Green)`
   - Refactor: `refactor: <description>`
   - E2E: `test: e2e for <feature>`
9. **Post test-evidence** `<!-- sdd:test-evidence:step-<n> -->` via
   `_test_evidence.md` (§15).
10. **Return** `OK <STEP_TYPE> COMMIT: <sha> TESTS: <p>/<t> FAILED: <f>` (or
    `OK REFACTOR EMPTY` / `OK E2E_SKIPPED`).

`<sha>` from `git rev-parse HEAD`. `<test-evidence>` is substring `TESTS: <p>/<t> FAILED: <f>`.

### 10.2 Step-review inline expansion (`tdd_step_review`)

For each step with a commit (NOT REFACTOR EMPTY, NOT E2E_SKIPPED):
1. **Read rubric** `<<SKILL_DIR>>/atoms/rubrics/implement-step.md` (R7 location;
   was `commands/ai-review-implement-step.md`).
2. **Re-diff** `git show <sha>`.
3. **Read test-evidence** `<!-- sdd:test-evidence:step-<n> -->`.
4. **Apply step-criteria rules** per role (red-tests-did-not-fail, tests-not-green,
   refactor-changed-test-counts, e2e-no-e2e-files-changed, ...).
5. **Step 5a consistency check** [PRESERVE — load-bearing trust boundary]:
   - Reviewer CANNOT re-run tests. Verifies self-reported counts vs raw log.
   - Rules per §15.5.
   - **CRITICAL nuances**:
     - `[major] test-evidence-log-missing`: **recorded, reviewer continues** to
       subsequent checks. NOT fail-fast (Reviewer A GAP-A1).
     - `[critical] refactor-changed-test-counts`: requires reading prior step-2
       review. If unavailable → downgrade to `[major]` (GAP-A3).
     - `[minor] test-evidence-summary-unparseable`: explicit non-blocking escape
       hatch ("Do not block on this — runners differ widely") (GAP-A2).
6. **Verdict** per Common Contracts §5.
7. **Post review** `<!-- sdd:review:implement:step-<n> -->` on the **Issue** via
   Section F. Write to `/tmp/sdd-review-implement-step-<n>-$1.md`.
8. **Return** `OK PASS` / `OK FAIL: <summary>` / `FAIL: <reason>`.

### 10.3 Retry semantics

On `OK FAIL: <summary>`:
- attempt counter incremented.
- Re-invoke step atom with retry flag.
- Step atom retry mode self-fetches latest step-review marker via Section C
  (atom-side fetch saves stage_implement context).
- Sorted findings: critical → major → minor. Address every critical/major.
- New sha replaces prior sha. Test-evidence updated in place (Section F).

### 10.4 SHA threading (stage-internal)

In Arch B, `<sha>` and `<test-evidence>` are stage-internal variables, NOT
threaded through main session FSM. Each step's review receives them directly
from preceding step atom's return parse.

For `OK REFACTOR EMPTY`: `<sha_step_3> = EMPTY`, `<test_evidence_step_3> = NONE`.
For `OK E2E_SKIPPED`: step 4 review is entirely SKIPPED — no marker posted.
Stage records `e2e_skipped = true` for §17 return shape.

### 10.5 REFACTOR EMPTY handling

If `implement_refactor` returns `OK REFACTOR EMPTY`:
- No commit, no test-evidence post.
- `tdd_step_review` for step 3 still runs but **immediately returns `OK PASS`**
  per source `tdd_step_review.md` step 1 short-circuit (`if $4 == "EMPTY" and
  $5 == "NONE": return OK PASS`).
- Proceeds to step 4.

### 10.6 E2E_SKIPPED handling

If `implement_e2e` returns `OK E2E_SKIPPED`:
- No commit, no evidence.
- Step 4 review SKIPPED ENTIRELY (no `tdd_step_review` call).
- `e2e_skipped = true` for §17 return.

[PRESERVE — load-bearing]: distinguish "skip review immediately returns PASS"
(REFACTOR EMPTY) from "skip review entirely" (E2E_SKIPPED).

### 10.7 Per-step exhaustion (attempt > 3)

- Post unresolved findings summary on Issue (Section F).
- Branch on `skip-review: implement`:
  - **Set** → log "⚠ TDD step-<n> failed 3 times. Auto-continuing because
    `skip-review: implement` is set; findings carry to PR Final." Continue.
  - **Not set** → **DECISION — Arch B Option 2**: auto-continue with logged
    warning. Step exhaustion is **soft** (findings carry to PR Final, which is
    the harder gate). Reserve ESCALATE for §12.9 round-3 gate.

[RETHINK]: spec says interactive → ask user. Arch B Option 2 is a behavior
shift. Alternative Option 1 (ESCALATE on step exhaustion) preserved as future
option. Documented in §17 + §20 migration notes.

---

## §11. Special Section — PR Creation Detail

Inline `implement_pr` (source `atoms/implement_pr.md`).

### 11.1 First-round mode (Phase 4)

Triggered when no PR Final retry in progress AND no open PR exists.

1. **Preflight** Light tier.
2. **Re-run all tests** → pass; else `FAIL: tests fail before PR creation`.
3. **`git push -u origin <branch_name>`**.
4. **Detect existing PR**:
   ```bash
   gh pr list --head <branch_name> --json number,state --jq '.[] | select(.state=="OPEN") | .number'
   ```
   - Empty → continue to step 5 (true first-round).
   - Has number → **R8 BRANCH POINT** (§11.3).
5. **Write PR body** to `/tmp/sdd-pr-body-$1.md`:
   - `Refs #$1`
   - Optional localized parent line (`Parent Issue:` en, `상위 Issue:` ko,
     `親Issue:` ja) from `<!-- sdd:child-issue -->` block.
   - Change summary (auto-generated from git log).
   - Manual Test Checklist (from plan's test plan).
6. **`gh pr create --title "<title>" --body-file /tmp/sdd-pr-body-$1.md`**. Title
   per repo convention from `git log --oneline -20`.
7. **Capture `<PR_NUM>`** via `gh pr view --json number -q .number`.
8. **Return** `OK PR: #N` or `OK PR: #N E2E_SKIPPED`.

### 11.2 Retry mode (Phase 5 rounds 2 + 3)

Triggered by stage_implement's internal round counter (N ≥ 2).

1. **Verify branch + PR**. If absent → `FAIL: retry mode requested but no open
   PR for branch <branch_name>`.
2. **`git pull --ff-only origin <branch_name>`** (continue if fails).
3. **Read PR diff** via `gh pr diff <PR_NUM>`.
4. **Self-fetch findings** (atom-side per Common Contracts §7):
   a. `<EXISTING_PR>` = literal PR number for PR-scoped fetches.
   b. Section C with 3 SDD markers PR-scoped → sorted findings array.
   c. Fetch `/code-review` + `/security-review` inline PR comments via
      `gh api repos/<owner>/<repo>/pulls/<PR_NUM>/comments`. Filter:
      - body starts with 🔴 / 🟡 → `/code-review`
      - body contains `Severity: High/Medium/Low` → `/security-review`
      - secondary author signal: `github-actions[bot]` (Actions mode)
   d. Translate severity (see §12.2): 🔴 → critical, 🟡 → minor, **🟣 → SKIP**
      (Reviewer A GAP-A4 — pre-existing issues orchestrator already ignored).
      `/security-review`: High → critical, Medium → major, Low/info → minor.
      Append + re-sort.
5. **Fix each critical/major**: decide kind (code defect / missing test / test
   defect / refactoring nit), apply, re-run tests. Minor entries used as
   same-file/line context.
6. **Commit fix-ups**: `fix: address review (round N) - <short summary>`.
   **No amend, no force-push.** [PRESERVE — load-bearing.]
7. **`git push -u origin <branch_name>`** (regular).
8. **Do NOT create new PR** — existing auto-updates.

### 11.3 R8: empty-`$3` + existing-PR auto-routing (NEW)

[NEW — Phase B per `00-architecture.md` §10]: spec §6 RETHINK gap. Resume
re-entering implement with existing PR + no retry context currently attempts
`gh pr create` and errors.

R8 fix: in §11.1 step 4, existing OPEN PR triggers:

**Option A (auto-route to retry — DEFAULT)**:
- Log "Existing PR #N detected on branch <name>; routing to retry-like flow".
- Skip §11.1 steps 5–7 (no PR creation).
- Treat as if §11.2 retry mode invoked with round=1 ("soft retry"; step 4 fetch
  returns empty arrays — no prior findings).
- After §11.2 step 8, return `OK PR: #N`. Proceed to Phase 5 normally.

**Option B (clear error — FALLBACK)**:
- Return `FAIL: existing open PR #N detected on branch <name>; pass Resume:
  retry-existing-pr context to re-enter intentionally`.
- Main session interprets and re-spawns with explicit Resume flag.

[DECISION — Arch B v2 (Synthesis T1.1)]: Option A is the ONLY behavior.
~~Option B activatable via NEW config key `strict-pr-creation`~~ — REMOVED per SYNTHESIS-v2.md T1.1. No new config keys (R2/R3 KEEP decision precludes).

[PRESERVE — load-bearing safety]: verify existing PR references this Issue via
`gh pr view <PR_NUM> --json body` containing `Refs #$1`. If not, `FAIL: existing
PR #N does not reference Issue #$1` — defensive, prevents overwriting unrelated PR.

### 11.4 Existing PR + retry mode (existing edge case)

- `Round N ≥ 2 + PR exists + retry set` → normal retry mode (§11.2).
- `Round N ≥ 2 + PR absent + retry set` → defensive `FAIL: retry mode requested
  but no open PR for branch <branch_name>`. [PRESERVE].

---

## §12. Special Section — PR Final Review Loop Detail (3 rounds)

Most complex orchestration in the stage.

### 12.1 Round structure (N ∈ {1, 2, 3})

```
Round N:
  5.N.1  Serial SDD reviewers (3 inlined)
         5.N.1.a  implement_review (role=completeness)
         5.N.1.b  implement_review (role=quality)
         5.N.1.c  implement_adversarial
  5.N.2  /code-review Skill (after 5.N.1)
  5.N.3  /security-review Skill (after 5.N.2; SKIP on sdd:review:shallow)
  5.N.4  Post tools-summary marker (in-place per round)
  5.N.5  Round decision
```

### 12.2 Reviewer inline expansion (each of 3 SDD reviewers)

Each reviewer reads:
- Rubric file (R7): `<<SKILL_DIR>>/atoms/rubrics/implement-<role>.md`
  - `implement-completeness.md`
  - `implement-quality.md`
  - `implement-adversarial.md`
- PR diff: `gh pr diff <PR_NUM>`
- PR body: `gh pr view <PR_NUM> --json body`

Then:
1. Apply rubric-specific criteria.
2. Compute findings (severity + rule_id + description + fix_suggestion).
3. Verdict per Common Contracts §5: critical/major → FAIL.
4. Write body to `/tmp/sdd-review-implement-<role>-pr<PR_NUM>.md`.
5. Post to PR via Section F:
   - Search marker `<!-- sdd:review:implement:<role> -->` on PR.
   - Empty → `gh pr comment <PR_NUM> --body-file <path>`.
   - Has id → `gh api repos/<owner>/<repo>/issues/comments/<id> -X PATCH --field body=@<path>`.
   - **NOTE**: per Common Contracts §9 source-inconsistency, spec standardizes
     on `--field` (not `-F`). Sub-agent uses `--field` consistently across all 3
     reviewers. [PRESERVE — Phase B fix per Reviewer A GAP-A5.]
6. Return inline: `OK PASS PR: #N` / `OK FAIL PR: #N: <summary>` / `FAIL: <reason>`.

### 12.3 Independent reviewer contexts

[PRESERVE — load-bearing]: 3 SDD reviewers run with **independent contexts** —
no cross-visibility of each other's verdicts.

In Arch B, "independent" means each reviewer's inline expansion does NOT read
the others' just-posted comments before forming its own verdict. Implementation
discipline:
- Order: completeness → quality → adversarial.
- Each reviewer reads ONLY its rubric + PR diff + PR body.
- Each reviewer does NOT read the other 2 review markers on PR (those may
  exist from prior rounds; reading them is OK for retry context — see §12.10,
  but in first round they don't exist).

[NEW for Arch B]: independence enforced by sub-agent discipline, not separate
Agent contexts. Add explicit check in rubric preamble.

### 12.4 Skill invocation: `/code-review` (5.N.2)

```
Skill: /code-review --effort <high|max|medium> --comment --pr <PR_NUM>
```

- Effort by depth (§5 table).
- `--comment` posts findings as inline line-anchored PR comments via Skill.
- Graceful skip:
  - Skill unavailable → log + record `{"name":"code-review","reason":"skill-unavailable"}`.
  - Skill errored → record `{"reason":"skill-errored: <truncated>"}` (IMPROVE vs spec).
- After Skill returns, count findings in PR comments:
  - 🔴 Important → critical (contributes FAIL)
  - 🟡 Nit → minor
  - 🟣 Pre-existing → **IGNORED for verdict** (GAP-A4)
- 1+ Important → /code-review contributes FAIL.

### 12.5 Skill invocation: `/security-review` (5.N.3)

- **Shallow skip** [PRESERVE — load-bearing depth gate]: if `sdd:review:shallow`,
  SKIP. Record `{"name":"security-review","reason":"shallow-label-skip"}`.
- Else: `Skill: /security-review --pr <PR_NUM>` (no effort arg).
- Graceful skip same as 12.4.
- Classify findings:
  - High → critical (contributes FAIL)
  - Medium → major (contributes FAIL)
  - Low/info → minor
- 1+ High or Medium → /security-review contributes FAIL.

### 12.6 Tools-summary marker (5.N.4)

Marker `<!-- sdd:review:implement:tools -->` on PR. Updated in place per round
(latest round overwrites prior).

Body:
```
**Round:** <N>
**/code-review:** <ran (effort: high) | skipped (skill-unavailable | shallow-label-skip | skill-errored: ...)>
**/security-review:** <ran | skipped (shallow-label-skip | skill-unavailable | ...)>

<details>
<summary>Tools details</summary>
- /code-review: X 🔴 Important, Y 🟡 Nit, Z 🟣 Pre-existing
- /security-review: A High, B Medium, C Low
</details>

<!-- sdd:findings:json -->
{ "stage":"implement", "role":"tools-summary", "issue":<N>, "pr":<PR_NUM>,
  "round":<N>, "verdict":null, "model":null, "findings":[], "suggestions":[],
  "tools_run":[...], "tools_skipped":[...] }
<!-- /sdd:findings:json -->
```

Write to `/tmp/sdd-implement-tools-$1-round-<N>.md`. Section F duplicate-prevention.

**Informational only** — does NOT affect verdict. Verdict logic (12.7) reads
underlying Skill comments + reviewer returns, not this marker.

[IMPROVE — observability rationale, PRESERVE marker]: distinguishes "no,
shallow-skip" from "yes, no findings". Cannot audit otherwise.

### 12.7 Verdict combination (5.N.5)

[PRESERVE — load-bearing]:

- **Round = FAIL** if ANY of:
  - Any SDD reviewer `OK FAIL PR: #N: <summary>`.
  - `/code-review` produced 1+ 🔴 Important.
  - `/security-review` produced 1+ High or Medium.
- **Round = PASS** only if ALL of:
  - All 3 SDD reviewers `OK PASS PR: #N`.
  - `/code-review` no Important (or skipped).
  - `/security-review` no High/Medium (or skipped).

Skipped Skills NEUTRAL. `tools_skipped` tracks reason.

[PRESERVE — edge-cases §19]: adversarial-only FAIL → log warning "⚠ Adversarial
reviewer alone identified critical/major issues" but treat as FAIL.

### 12.8 Round decision

| Round | Verdict | Next |
|---|---|---|
| 1 or 2 | PASS | Exit loop → return `OK ADVANCE: test PR: #N BRANCH: <name>` (+ E2E_SKIPPED if set) |
| 1 or 2 | FAIL | `implement_pr` retry (§11.2) → Round N+1 |
| 3 | PASS | Same as above |
| 3 | FAIL | §12.9 escalation |

### 12.9 Phase 5.5 — Round 3 escalation gate

Per `01-sub-agent-contract.md` §3:
1. Render summary of remaining critical/major findings with role labels
   (`implement/<role>`, `code-review`, `security-review`).
2. Branch on `skip-review: pr`:
   - **Set** → log "⚠ Round 3 PR Final escalation … `skip-review: pr` set —
     auto-continuing". Return `OK ADVANCE: test PR: #N BRANCH: <name>` (+
     E2E_SKIPPED if set).
   - **Not set** → return:
     ```
     >>> RESULT <<<
     ESCALATE: implement round 3 FAIL — findings: [critical] X, [major] Y. PR: #N BRANCH: <name>
     ```
     Main calls AskUserQuestion. On Continue, main re-spawns with
     `Resume: continue-after-escalation` (sub-agent jumps directly to return
     `OK ADVANCE: ...` since human has accepted findings).

[PRESERVE — load-bearing]: skip-review key here is `pr`, distinct from `implement`.

### 12.10 Retry-mode data flow

Round N+1 entry into retry mode (§11.2):
- All 3 SDD reviewer markers + tools-summary PATCHed in place. Prior-round
  content lost from GitHub (Common Contracts §4 update-in-place).
- Test-evidence comments NOT updated by PR Final retry (step-scoped, not
  PR-Final-scoped). Findings JSON `round` field IS updated per PATCH.

---

## §13. Special Section — Skill Invocations Inside Sub-agent

[VERIFIED — R5 spike, Common Contracts §13]: sub-agents CAN invoke Skill tool.
Unlocks moving `/code-review` and `/security-review` INSIDE stage_implement.

### 13.1 No parallel-batch constraint inside sub-agent

Constraint "Skill cannot be in same parallel batch as Agent calls" (Common
Contracts §24) applies to MAIN SESSION batches. Inside a sub-agent there are
NO Agent calls (single-level spawn), so the constraint is moot.

However, we PRESERVE serial ordering (5.N.1 → 5.N.2 → 5.N.3) inside
stage_implement for:
1. **Verdict determinism**: SDD reviewer verdicts known before Skill verdicts.
2. **Code clarity**: round structure easier to reason about serially.
3. **Token economy**: serial allows Skill outputs processed incrementally
   without holding all-reviewer + all-Skill outputs simultaneously.

[PRESERVE — load-bearing for Arch B]: serial ordering becomes sub-agent
convention, not platform constraint. Document distinction in preamble.

### 13.2 Skill invocation pattern

```
Skill tool call:
  skill: /code-review
  args: --effort high --comment --pr <PR_NUM>
```

After Skill returns, sub-agent reads PR inline comments via
`gh api repos/<owner>/<repo>/pulls/<PR_NUM>/comments` to extract findings count.

### 13.3 Skill failure modes

| Failure | Detection | Tools-summary entry |
|---|---|---|
| Not installed / disabled | Semantic error | `{"reason":"skill-unavailable"}` |
| Present but errored | Non-empty error markers in return | `{"reason":"skill-errored: <truncated>"}` |
| Shallow label set (security-review only) | Pre-check | `{"reason":"shallow-label-skip"}` |

[IMPROVE — vs spec]: spec lumps "unavailable" and "errored". Splitting helps audit.

### 13.4 Why not move Skill calls back to main session

Considered + rejected:
- **Pro of main-session call**: main can run `/code-review` in parallel with
  other queued Issues (auto.md).
- **Con (decisive)**: main session token bloat — `/code-review` generates
  ~5-15K tokens of inline comments which main would need to read.
- **Con (decisive)**: "stage as cohesive unit" model breaks if half the
  reviewers live outside the stage sub-agent.

[DECISION]: Skills run inside stage_implement.

---

## §14. Special Section — R9 TDD Step Idempotency (NEW)

[NEW — Phase B per `00-architecture.md` §10]: spec §10 RETHINK — "TDD step
atoms do NOT skip already-done steps — re-spawn blindly". R9 fixes this.

### 14.1 Per-step idempotency check

Before invoking step atom for step `n`:
1. Check `<!-- sdd:test-evidence:step-<n> -->` marker exists on Issue.
2. If present, parse body for commit sha.
3. Verify sha is reachable on current branch:
   `git merge-base --is-ancestor <sha> <branch_name>`.
4. Verify commit's subject matches step expectation (heuristic):
   - Red: starts `test:` contains `(Red)`
   - Green: starts `feat:` contains `(Green)`
   - Refactor: starts `refactor:`
   - E2E: starts `test:` contains `e2e`
5. Verify step-review marker exists with PASS verdict (parsed from findings JSON).
6. All checks pass → step idempotently complete. Skip BOTH atom AND review.
   Set `<sha_step_n>` and `<test_evidence_step_n>` from marker. Next step.
7. Any check fails → run step atom normally.

### 14.2 What R9 saves

Without R9: each completed step re-attempted, re-writes potentially conflicting
commits, runs tests, posts new evidence.
With R9: completed steps detected via marker + sha verification; jumps to first
incomplete step.

Saves ~5-15K tokens per skipped step + wall-clock test runs.

### 14.3 Edge cases

- **Branch divergence**: marker-claimed sha NOT ancestor of branch (force-push,
  reset) → check fails → step re-runs. Safety: never skip if state uncertain.
- **REFACTOR EMPTY resumed**: evidence marker absent (no evidence posted) →
  check fails → step re-runs.
  - **Sub-case**: to support REFACTOR EMPTY idempotency, post sentinel marker
    `<!-- sdd:implement:refactor-empty -->` on Issue when atom returns
    REFACTOR EMPTY. On resume, check sentinel + sha-of-prior-step-2 still
    matches → skip.
  - [NEW sub-extension — optional v1.1]: defer to v1.1; preserves v1.0.0 R9
    scope.
- **E2E_SKIPPED resumed**: evidence absent. Step 4 detection re-runs (cheap —
  artifact detection only). If still no e2e → re-skip. Self-idempotent without
  explicit marker.
- **Evidence present but review marker absent OR FAIL**: prior attempt crashed
  mid-step. Sub-agent re-runs review (or step) — implementation re-runs review
  only since commit is on branch. (See pseudocode §14.4.)

### 14.4 Idempotency check pseudocode

```python
def step_idempotent(step_n, branch_name, issue_num):
    evidence_marker = f"<!-- sdd:test-evidence:step-{step_n} -->"
    review_marker = f"<!-- sdd:review:implement:step-{step_n} -->"

    evidence = gh_search_marker(issue_num, evidence_marker)
    review = gh_search_marker(issue_num, review_marker)

    if not evidence or not review:
        return False, None, None

    sha = parse_sha_from_evidence(evidence.body)
    if not git_is_ancestor(sha, branch_name):
        return False, None, None
    if not commit_subject_matches_step(sha, step_n):
        return False, None, None

    review_verdict = parse_verdict_from_findings_json(review.body)
    if review_verdict != "PASS":
        return False, None, None

    test_evidence = parse_test_counts_from_evidence(evidence.body)
    return True, sha, test_evidence
```

### 14.5 R9 cost

Per step: 2 extra `gh api` calls (marker search) + 1 git rev-parse + 1 git log
read. Negligible (~5s wall-clock) vs resume savings.

[PRESERVE — for v1.0.0]: implement R9 for ALL 4 steps where evidence markers
exist. Defer REFACTOR EMPTY sentinel and explicit E2E_SKIPPED sentinel to v1.1.

---

## §15. Special Section — Test-Evidence Handling

Source: `commands/atoms/_test_evidence.md`.

### 15.1 Truncation rule

- Total ≤ 50,000 chars → verbatim.
- Total > 50,000 chars → first 2,000 + `... [truncated middle] ...` + last 8,000.

[PRESERVE — load-bearing]: keep last-N (runner summary + failure markers near
end); first-N preserves framework banner / startup for authenticity check.

### 15.2 Body shape

```
**Commit:** <sha>
**Reported counts:** TESTS: <p>/<t> FAILED: <f>
**Test command:** `<command>`

<details>
<summary>Raw test output</summary>

```
<truncated-or-full-raw-output>
```

</details>

<!-- sdd:test-evidence:step-<n> -->
```

### 15.3 Posting protocol

1. Write to `/tmp/sdd-test-evidence-$1-step-<n>.md` (Common Contracts §9).
2. Section F duplicate-prevention.
3. Re-read after post (Step 5 of `_test_evidence.md`). Empty → atom returns
   `FAIL: test evidence comment not found after posting (step-<n>)`.

### 15.4 Skipped scenarios

- `OK REFACTOR EMPTY` — no commit, no evidence.
- `OK E2E_SKIPPED` — no commit, no evidence.

### 15.5 Reviewer authenticity check (`tdd_step_review` step 5a)

[PRESERVE — load-bearing trust boundary]. System's only defense against LLM
work atom hallucinating "tests pass".

Rules:
- `[critical] red-tests-did-not-fail` (Red: FAILED == 0)
- `[critical] tests-not-green` (Green/Refactor/E2E: FAILED != 0)
- `[critical] refactor-changed-test-counts` (no test-file changes + count drift)
  - Graceful fallback: prior step-2 review unavailable → downgrade `[major]` (GAP-A3)
- `[major] zero-tests-executed` (total == 0 + non-empty commit)
- `[critical] test-evidence-mismatch` (count mismatch with `$5`)
- `[major] test-evidence-implausible` (implausibly short log)
- `[critical] red-log-shows-no-failure` (Red lacks failure indicator)
- `[major] test-evidence-log-missing` (commit ≠ EMPTY, $5 ≠ NONE, evidence absent)
  - **Reviewer continues** to subsequent checks. NOT fail-fast (GAP-A1).
- `[minor] test-evidence-summary-unparseable` (explicit non-blocking escape; GAP-A2)

---

## §16. Special Section — Phase 7 Child Completion Notification

[PRESERVE — load-bearing edge case]: Phase 7 runs ONLY when:
- Issue body matches multilingual parent regex (this is a child), AND
- Issue label JUST transitioned to `sdd:done`.

The "just transitioned" trigger is detected by main session bootstrap/dispatcher.
Dispatcher routes back into `stage_implement` specifically for Phase 7 — NOT
for fresh implement.

### 16.1 Phase 7 entry detection

```
1. Read Issue labels via gh issue view.
2. If labels contain "sdd:done" AND Issue body matches multilingual parent regex:
   → Phase 7 trigger. Run §16.2 ONLY.
3. Else: normal implement flow (Phase 0 onward).
```

### 16.2 Phase 7 steps

1. **Find parent number** from `<!-- sdd:child-issue -->` block:
   ```
   gh issue view $1 --json body --jq .body
   # parse with regex: (Parent|상위 |親)Issue: #([0-9]+)([^0-9]|$)
   ```
2. **Find most-recent children comment on parent**:
   ```
   gh api repos/<owner>/<repo>/issues/<parent_num>/comments --jq '.[] | select(.body | contains("<!-- sdd:children:output -->")) | select(.body | contains("<!-- /sdd:children:output -->")) | .id'
   ```
   - None → warn + skip (no error).
   - Multiple → use last (most recent).
3. **Update children comment** (Section F PATCH):
   - Read body, replace this child's row with new status in narrative (NOT in shell).
   - Write to `/tmp/sdd-children-output-<parent>.md`.
   - `gh api repos/<owner>/<repo>/issues/comments/<id> -X PATCH --field body=@/tmp/sdd-children-output-<parent>.md`.
4. **Verify by re-read**.
5. **Check every child's actual label**:
   - For each child: `gh issue view <child> --json labels --jq '.labels[].name'`.
   - **All `sdd:done`** → post completion notification on parent (NEW comment,
     no duplicate-prevention): "All children done. Run `/sdd test <parent>`."
     Write to `/tmp/sdd-implement-completion-<parent>.md`.
     `gh issue comment <parent_num> --body-file <path>`.
   - **Not all done** → report remaining. Skip-review → return `OK PAUSE` (outer
     auto-discovery picks remaining). Interactive → main asks next.

### 16.3 Multilingual regex

```
(Parent|상위 |親)Issue: #([0-9]+)([^0-9]|$)
```

[PRESERVE — load-bearing]: boundary class required.

### 16.4 Phase 7 return shape

For Phase 7-only invocations (Issue already `sdd:done`): return `OK PAUSE`.
Side-effect-only path; no further work. Sub-agent does NOT advance any label.

[RETHINK — spec]: Phase 7 in `implement.md` is awkward (executes post-test
state). Spec flags moving to dedicated atom. Deferred to Phase C. v1.0.0
preserves Phase 7 inside stage_implement.

---

## §17. Multiple Return Paths Summary

| Trigger | Return |
|---|---|
| Normal completion, PR Final PASS, E2E ran | `OK ADVANCE: test PR: #N BRANCH: <name>` |
| Normal completion, PR Final PASS, E2E skipped | `OK ADVANCE: test PR: #N BRANCH: <name> E2E_SKIPPED` |
| Phase 1 parent detected | `OK PARENT_STOP` |
| Phase 5.5 escalation, `skip-review: pr` SET → auto-continue | `OK ADVANCE: test PR: #N BRANCH: <name>` (+ E2E_SKIPPED) |
| Phase 5.5 escalation, `skip-review: pr` NOT set | `ESCALATE: implement round 3 FAIL — findings: ... PR: #N BRANCH: <name>` |
| Per-step exhaustion, `skip-review: implement` set | continue (no return) |
| Per-step exhaustion, `skip-review: implement` NOT set | continue with warning (§10.7 Option 2 default) |
| Phase 7 child-completion path | `OK PAUSE` |
| Any atom-internal fatal | `FAIL: <reason>` |

[NEW for Arch B contract]: `OK ADVANCE` carries BOTH `PR: #N` and `BRANCH: <name>`
so main session threads both to stage_test without re-deriving.

[PRESERVE — distinction]:
- `OK PAUSE` — sub-agent stopped non-error checkpoint; user resumes via
  `/sdd resume <N>`. No main interaction needed.
- `OK PARENT_STOP` — parent Issue; main queues children. Skip-review: no
  interaction; interactive: main asks which child next.
- `ESCALATE` — gate requires user decision; main calls AskUserQuestion, re-spawns
  with Resume hint.

---

## §18. Branch + Commit Conventions

### Branch naming

| Issue type | Branch |
|---|---|
| Single | `feat/<feature-name>` |
| Child | `feat/<parent-feature>/<child-feature>` |

`<feature-name>` kebab-cased from title. **Repo override**: inspect
`git log --oneline -20`; follow existing convention.

[PRESERVE — load-bearing for project conformance]

### Commit message style

| Step / Mode | Commit prefix |
|---|---|
| Red | `test: <description> (Red)` |
| Green | `feat: <description> (Green)` |
| Refactor (non-empty) | `refactor: <description>` |
| E2E | `test: e2e for <feature>` |
| PR Final retry fix-up | `fix: address review (round N) - <short summary>` |

All commits inspect `git log --oneline -20` to match repo convention.

### Hard rules

[PRESERVE — load-bearing]:
- **No Claude as co-author** in any commit.
- **No force-push** (`git push -u origin <branch>` only).
- **No `git commit --amend`** in retry mode.
- **No `git push` from TDD step atoms** — only PR creation / retry.

Enforced by sub-agent discipline; no Bash heuristic blocks (would pass platform
safeguards). Documentation discipline + code review catches violations.

---

## §19. Edge Cases (cross-reference summary)

- **Parent stops at Phase 1** (§7.3) — both paths return `OK PARENT_STOP`.
- **Resume from existing branch** — Phase 2 step 3 falls back to checkout; R9
  (§14) skips already-completed steps.
- **Resume from existing PR (R8)** — §11.3, auto-route default.
- **Step exhaustion** — §10.7 Option 2 (auto-continue + warning).
- **Round exhaustion** — §12.9 (ESCALATE or auto-continue per `skip-review: pr`).
- **skip-review keys**:
  - `implement` → Phase 1 parent-stop, Phase 2.2 plan gate (NO-OP in Arch B —
    main owns), Phase 3 step-exhaustion Option 2.
  - `pr` → Phase 5.5 escalation.
  - `qa` → NOT consumed by stage_implement (consumed by main post-`OK ADVANCE`).
- **Test runner anomalies** — counts unobtainable → `0`; reviewer flags `[major]
  test-evidence-missing` or `[major] zero-tests-executed`.
- **E2E framework absent** — `OK E2E_SKIPPED`; PR creation includes flag.
- **Atom-level FAIL vs review-verdict FAIL** — atom FAIL stops sub-agent;
  `OK FAIL` from reviewer counts toward round verdict only.
- **Adversarial-only FAIL** — log warning, treat as FAIL (edge-cases §19).
- **Multiple children comments on parent** (§16.2) — use most recent; zero → warn + skip.
- **Issue Validation gate** — Common Contracts §10 at boot.
- **GitHub API eventual consistency** — serial 5.N.1 → 5.N.5 ensures window elapsed.
- **Owner/repo resolution** — Common Contracts §11 mandatory derivation.
- **Bash heuristic compliance** — Common Contracts §8 single-simple-command;
  multi-line bodies via Write tool + `--body-file`.

---

## §20. Migration / Implementation Notes (Phase C reference)

### 20.1 New files

- `atoms/stage_implement.md` — inlines 10 source atoms.
- `atoms/rubrics/implement-completeness.md` (moved from `commands/ai-review-implement-completeness.md`)
- `atoms/rubrics/implement-quality.md` (moved + renamed)
- `atoms/rubrics/implement-adversarial.md` (moved + renamed)
- `atoms/rubrics/implement-step.md` (moved + renamed)
- `commands/implement.md` — slim wrapper that spawns stage_implement.

### 20.2 Files removed

`commands/atoms/implement_{plan,red,green,refactor,e2e,pr,review,adversarial}.md`,
`commands/atoms/tdd_step_review.md`, `commands/ai-review-implement-*.md` (moved).

### 20.3 Files preserved

`commands/atoms/_preflight.md`, `_review_helpers.md`, `_test_evidence.md`.

### 20.4 ~~New config key (R8)~~ — REMOVED

Per SYNTHESIS-v2.md T1.1: no `strict-pr-creation` config key. R8 = always auto-route on existing PR. Users wanting strict behavior can `gh pr close` manually before re-running.

### 20.5 Behavior shifts to document

1. **Per-step exhaustion** in interactive mode no longer prompts user (sub-agent
   no AskUserQuestion). Auto-continues + warning. §10.7.
2. **Phase 2.2 plan gate** moves to main session (implicit consent). §6.
3. **Per-stage model assignment** for inlined reviewers becomes informational.
   §5.
4. **R8 existing-PR auto-route** new behavior. §11.3.
5. **R9 TDD step idempotency** new resume-friendly skip. §14.

---

## §21. Cross-references

- Stage spec: `spec/stage/implement.md`
- Architecture overview: `design/00-architecture.md`
- Sub-agent contract: `design/01-sub-agent-contract.md`
- File layout: `design/02-file-layout.md`
- Common contracts: `spec/00-common-contracts.md`
- Edge cases (6, 11, 13, 17, 24): `spec/edge-cases.md`
- Multilingual regex: `spec/02-multilingual.md` §3
- Skip-review semantics: `spec/01-config.md` §2
- Depth labels + model table: `spec/01-config.md` §3
- Test-evidence helper: `commands/atoms/_test_evidence.md`
- Review helpers (Sections A-F): `commands/atoms/_review_helpers.md`
- Rubrics (R7 location): `atoms/rubrics/implement-*.md`
- Related stage designs: `design/stage-designs/{analyze,design,test}.md`
