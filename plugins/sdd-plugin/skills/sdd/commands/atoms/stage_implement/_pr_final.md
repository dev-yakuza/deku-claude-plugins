# STAGE: implement — Phase 4 + Phase 5 + Phase 5.5 (topic file)

Topic file read inline by `main.md` §8. Executes inside the same single sub-agent context — no Agent spawns; **MAY use Skill tool** for `/code-review` and `/security-review` (per Common Contracts §13; `spec/edge-cases.md` §12).

Covers:
- **Phase 4** (§3) — PR creation in first-round mode, with R8 (empty-`$3` + existing-PR) auto-route to soft retry per SYNTHESIS-v2 T1.1 (no `strict-pr-creation` config key).
- **Phase 5** (§4) — `/review` Skill once after PR creation (`§4.0`), then 3-round PR Final review loop: 3 SDD reviewers serial (`5.N.1.a` completeness → `5.N.1.b` quality → `5.N.1.c` adversarial) → `/code-review` (`5.N.2`) → `/security-review` (`5.N.3`) → tools-summary marker (`5.N.4`) → round verdict (`5.N.5`).
- **Phase 5.5** (§5) — Round 3 escalation gate on FAIL: `skip-review: pr` set → auto-continue; else `ESCALATE: ...`.

> **Bash Command Execution**: every shell snippet below is its own simple Bash tool call. See `<<SKILL_DIR>>/commands/atoms/_bash_rules.md`.

---

## §1. Inputs (held in narrative from `main.md`)

- `$1` — Issue number.
- `<branch_name>` — feature branch (checked out by `main.md` §6.4; final state from `_tdd.md` is the head with all TDD commits).
- `<owner>/<repo>` — captured in `main.md` §2.
- `<parent_num>` — optional, from `main.md` §6.3 if child Issue.
- `e2e_skipped: bool` — from `_tdd.md` §10.
- `depth` — `default` / `deep` / `shallow` from `main.md` §3.

## §2. Return values (to `main.md`)

- `OK ADVANCE PR: #<PR_NUM>` — TDD + PR Final passed; `main.md` §9 composes the final `OK ADVANCE: test PR: #<PR_NUM> BRANCH: <branch_name>` line (appending ` E2E_SKIPPED` if `e2e_skipped`).
- `ESCALATE: implement round 3 FAIL — findings: [critical] <X>, [major] <Y>. PR: #<PR_NUM> BRANCH: <branch_name>` — Round 3 FAIL, `skip-review: pr` OFF; `main.md` returns this verbatim.
- `FAIL: <reason>` — atom-level error; `main.md` returns verbatim.

---

## §3. Phase 4 — PR creation (inlined `implement_pr` first-round mode + R8)

`spec/stage/implement.md` §6 First-round mode; source atom `commands/atoms/implement_pr.md`.

### §3.1 Step 0 — Preflight (Light tier)

Follow `<<SKILL_DIR>>/commands/atoms/_preflight.md` Section A — tier **Light**, Section B items 1 + 2 (project conventions + commit message style). Critical here: PR title and body should match the repo's commit message style (e.g. `feat: …`, `fix: …`, em-dash separator).

### §3.2 Step 1 — Verify state

```bash
git rev-parse --abbrev-ref HEAD
```

If not on `<branch_name>` → `git checkout <branch_name>`.

### §3.3 Step 2 — Re-run all tests

Auto-detect test command. Run all tests (unit + E2E if applicable; respect `e2e_skipped`). All must pass.

- Any failure → return `FAIL: tests fail before PR creation` (from this `_pr_final.md` execution; `main.md` propagates).

### §3.4 Step 3 — Push branch

```bash
git push -u origin <branch_name>
```

(Single simple Bash call; never `--force`; per `spec/edge-cases.md` §23 force-push prohibition.)

### §3.4.5 Coverage Ledger Finalization

Finalize scenario statuses in the shared coverage ledger using the TDD outcomes held in narrative (`sha_step_1..4`, `e2e_skipped` from `_tdd.md`). Runs on BOTH the true first-round path and the R8 soft-retry path (it precedes the §3.5 branch point).

1. **Bash** — fetch the ledger:

   ```bash
   gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | select(.body | contains("<!-- sdd:coverage:ledger -->")) | .body'
   ```

   Parse the `<!-- sdd:coverage:json -->` block in context. **Empty or `scenarios` array has length 0** → log "coverage ledger missing or has no scenarios; skipping finalization" to the narrative and continue to §3.5 (non-blocking; §3.7.2 then uses its plan-based fallback).

2. **Bash** — locate `MANUAL:`-annotated test scenarios (single call; a non-zero exit with no output means no matches — that is fine, read the tool result):

   ```bash
   git grep -n "MANUAL:" -- "*.test.*" "*.spec.*" "*_test.*" "test_*" "*/test_*"
   ```

   From each matching line extract the reason text after `MANUAL:` (covers `// MANUAL:`, `# MANUAL:`, `<!-- MANUAL:` comment styles per `_tdd.md` §3.3) and match it to a ledger scenario by description wording.

3. If `e2e_skipped == true` — **Bash** — fetch the skipped-scenario list:

   ```bash
   gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | select(.body | contains("<!-- sdd:e2e-skipped-scenario -->")) | .body'
   ```

4. Update each scenario currently `"pending"`, in this order (later rules win where they overlap):
   - `category` ∈ {`happy_path`, `error_path`, `boundary`, `concurrent`} → `status: "automated"`, `sha: "<sha_step_2 literal value>"` (the Green commit).
   - `category == "e2e"` AND `sha_step_4 != EMPTY` → `status: "automated"`, `sha: "<sha_step_4 literal value>"`.
   - `category == "e2e"` AND `e2e_skipped == true` → if the scenario appears in the `<!-- sdd:e2e-skipped-scenario -->` list → `status: "skipped"`, `reason: "<the listed skip reason>"`; if it does NOT appear (compensating integration test covered it — `_tdd.md` §6.4) → `status: "automated"`, `sha: null` (compensating test SHA is not tracked in pipeline state; see git log for commits containing "E2E_SKIPPED" message).
   - Any scenario matched by an item-2 `MANUAL:` annotation → `status: "manual"`, `reason: "MANUAL: <extracted reason>"`, `sha: null` (overrides the automated rules above).
   - Any scenario still `"pending"` after applying rules 1–4 → `status: "manual"`, `reason: "disposition undetermined — manual verification required"`.

5. Leave `pr: null` for now — the PR does not exist yet on the first-round path; §3.8.5 records it after creation.

6. Recompute `summary` (`total` / `automated` / `manual` / `skipped` / `pending` from the scenarios array). Set `updated_by: "implement"`.

7. **Write tool** — render to `/tmp/sdd-coverage-ledger-$1.md` (same body shape as §6.7.5; `**Updated by:** implement`).

8. **Bash** — duplicate-prevention search:

   ```bash
   gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | select(.body | contains("<!-- sdd:coverage:ledger -->")) | .id'
   ```

9. **Bash** — PATCH in place (the id exists — item 1 found the ledger): `gh api repos/<owner>/<repo>/issues/comments/<id> -X PATCH --field body=@/tmp/sdd-coverage-ledger-$1.md`

Hold the finalized ledger object and comment `<id>` in narrative for §3.7.2 and §3.8.5.

### §3.5 Step 4 — Detect existing PR (R8 BRANCH POINT)

```bash
gh pr list --head <branch_name> --state open --json number --jq '.[0].number'
```

- **Empty** → true first-round → continue §3.6 (compose PR body + create).
- **Has number `<EXISTING_PR>`** → **R8 auto-route** per SYNTHESIS-v2 T1.1 + `design/stage-designs/implement.md` §11.3.

### §3.6 R8 auto-route to soft retry [NEW Phase B; no config opt-out per T1.1]

When an existing OPEN PR is detected on `<branch_name>` despite no explicit Resume hint:

#### §3.6.1 Defensive verification — PR references this Issue

```bash
gh pr view <EXISTING_PR> --json body --jq .body
```

Inspect the literal output. If the body does NOT contain `Refs #$1` → return `FAIL: existing open PR #<EXISTING_PR> on branch <branch_name> does not reference Issue #$1`. (Prevents accidentally overwriting an unrelated PR.)

If body contains `Refs #$1` → continue §3.6.2.

#### §3.6.2 Soft retry path

Log to sub-agent narrative: "Existing PR #<EXISTING_PR> detected on branch <branch_name>; routing to retry-like flow (R8 auto-route). Step 4 fetch will return empty (no prior findings), step 5 is a no-op (no critical/major to address), step 7 push is a no-op (nothing new). PR Final round 1 proceeds normally against the existing PR."

Action:
- SKIP §3.7 (no `gh pr create`).
- Set `<PR_NUM> = <EXISTING_PR>`.
- Treat Phase 4 as complete (no new commits, no `git push` beyond §3.4 which was a no-op for an up-to-date branch).
- Proceed to §4 Phase 5 with PR Final round 1.

Note: R8 is "always on" per T1.1 — no `strict-pr-creation` config key was added. Users wanting strict behavior must manually `gh pr close <PR_NUM>` before re-running `/sdd implement` or `/sdd resume`.

### §3.7 Step 5 — Compose PR body + create

(True first-round only; skipped on R8 auto-route.)

#### §3.7.1 Determine language

From `.github/.sdd-lang` per `<<SKILL_DIR>>/commands/atoms/_multilingual.md` (fallback: detect from Issue body; else `en`).

#### §3.7.2 Build PR body

Auto-generate from `git log --oneline -20` (already in context from §3.1 Item 2). Read the `<!-- sdd:implement:plan -->` test plan from the Issue (already in narrative context from Phase 2).

**Ledger-first rule**: if §3.4.5 finalized the coverage ledger (held in narrative) AND the `scenarios` array is non-empty, build the `## Automated Test Coverage` section and the `## Manual Test Checklist` directly from the ledger's `scenarios` array instead of re-deriving them — `status == "automated"` entries become the Automated bullets (group by `category`; cite the scenario `description`), `status == "manual"` entries become Manual checklist items (include `reason`), `status == "skipped"` entries (E2E-skipped) become Manual checklist items under "E2E-skipped" (include `reason`). The `<!-- sdd:e2e-skipped-scenario -->` fetch and the `git grep "MANUAL:"` scan described below are then SKIPPED (already folded into the ledger in §3.4.5). The `- E2E:` line in `## Automated Test Coverage` is still determined from `sha_step_4` and `e2e_skipped` per the rules below; when `e2e_skipped == true`, use the count of `status == "skipped"` scenarios with `category == "e2e"` from the ledger as N in `"N scenario(s) require manual verification"`. Use the derivation steps below ONLY when the ledger is absent or has no scenarios.

**The PR body MUST be self-contained — a reviewer reading ONLY this PR (without opening parent / referenced Issues) must understand**:
1. **What** the PR changes (concrete scope, not just a category label).
2. **Why** the change is needed (the underlying problem, in 1-3 sentences — do not assume the reader has the Issue context).
3. **How** the change is made (approach / breakdown — table if there are multiple distinct policies / cases).

If the parent Issue uses an ad-hoc taxonomy term (e.g. `"C 그룹"`, `"the boilerplate"`, `"the old pattern"`) **do not paste the term as-is** into the PR title or first paragraph. Either re-define it inline in one sentence, or replace it with a self-explanatory description. The `Refs #$1` link is sufficient for traceability; standalone readability is the standalone PR's responsibility.

Examples:
- ❌ Bad title: `refactor: C 그룹 본문 Get.reset() 을 좁히기`
- ✅ Good title: `refactor: 테스트 본문 내 Get.reset() 10개 호출을 의도별로 좁히기 (helper 재등록 누락 회귀 방지)`
- ❌ Bad first line: `Refs #872. C 그룹 본문 처리.`
- ✅ Good first line: `Refs #872. 테스트 본문에서 호출되는 Get.reset() 은 permanent helper 까지 제거하기 때문에 직후 재등록이 누락되면 회귀가 발생한다. 본 PR 은 호출 10곳을 의도별로 좁힌다.`

**Automated Test Coverage section** — derive from the implement plan's test categories and TDD step SHAs (all available in narrative context from `_tdd.md`):

- **Unit (Red → Green)**: list the concrete scenarios that were automated — use the test plan's Happy path / Error path / Boundary / Concurrent entries as-is, but be specific enough for a reviewer to understand coverage (e.g. `"login flow, invalid credentials, empty input"` not just `"Happy path"`). These correspond to `sha_step_1` (Red) and `sha_step_2` (Green) commits.
- **Refactor**: `"applied"` if `sha_step_3 != EMPTY`; `"no changes needed"` if `sha_step_3 == EMPTY`.
- **E2E**: `"covered (<framework name>)"` if `sha_step_4 != EMPTY`; if `e2e_skipped == true` → fetch `<!-- sdd:e2e-skipped-scenario -->` from the Issue:
  ```bash
  gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | select(.body | contains("<!-- sdd:e2e-skipped-scenario -->")) | .body'
  ```
  - Comment found with scenarios listed → `"skipped — integration-level coverage added where possible; <N> scenario(s) require manual verification (see Manual Test Checklist below)"`.
  - Comment found but empty scenario list → `"skipped — no E2E framework detected; all user-flow scenarios were expressible as integration-level unit tests"`.
  - Comment not found → `"skipped — no E2E framework detected"`.

**Manual Test Checklist** — include ONLY items that fall into one or more of these categories. If none apply, write the "all automated" note instead (see body shapes below).

| Category | Include when |
|---|---|
| UI/UX appearance | Visual rendering, responsive layout, animation, hover states — not expressible as assertions |
| Accessibility | Screen reader behavior, keyboard navigation, focus management |
| Performance | Response times, memory usage, behavior under load |
| Unmockable external integrations | Payment processors, SMS gateways, OAuth flows requiring a live provider |
| E2E scenarios | `e2e_skipped == true` — use the bullets from `<!-- sdd:e2e-skipped-scenario -->` directly; if comment absent, infer from the test plan what user flows would need E2E coverage |

Additionally, scan the PR diff for `// MANUAL:` inline comments added by `_tdd.md` §3.3 (test scenarios excluded from unit tests with an explanation). Include each as a Manual Test Checklist item:

```bash
gh pr diff <PR_NUM>
```

Search the diff for lines matching `// MANUAL:` (JavaScript/TypeScript/Go/Dart), `# MANUAL:` (Python/Ruby/Shell), or `<!-- MANUAL:` (HTML/template files) and extract the reason text as a checklist item. If none found, skip this step.

Do NOT echo back test plan items that are already covered by unit or E2E tests. The TDD pipeline automated those; listing them here as manual items creates noise and causes reviewers to re-verify what CI already verifies.

Body shape (single Issue):
```
Refs #$1

## Background (standalone)
<1-3 sentences stating the underlying problem — self-contained; assumes the reader has NOT opened the Issue>

## Changes
<change summary — table or bullets, 3-10 lines covering what · why · how per the rule above>

## Automated Test Coverage
- Unit (Red → Green): <specific scenario list from test plan — e.g. "happy path: X, error: Y, boundary: Z">
- Refactor: <"applied" | "no changes needed">
- E2E: <"covered (Playwright)" | "covered (Cypress)" | "skipped — integration-level coverage added where possible; N scenario(s) require manual verification" | "skipped — no E2E framework detected">

## Manual Test Checklist
<If genuinely manual items exist (UI/UX, accessibility, performance, unmockable integrations, E2E-skipped scenarios from <!-- sdd:e2e-skipped-scenario -->):>
- [ ] <item>
<If ALL scenarios are covered by automated tests above and e2e_skipped == false:>
> All scenarios are covered by automated tests above. No manual verification required.
```

Body shape (child Issue — add localized parent line BEFORE the change summary):
- `en`: `Parent Issue: #<parent_num>`
- `ko`: `상위 Issue: #<parent_num>`
- `ja`: `親Issue: #<parent_num>`

```
Refs #$1
<localized parent line>

<change summary>

## Automated Test Coverage
- Unit (Red → Green): <specific scenario list>
- Refactor: <"applied" | "no changes needed">
- E2E: <"covered (<framework>)" | "skipped — integration-level coverage added; N scenario(s) require manual verification" | "skipped — no E2E framework detected">

## Manual Test Checklist
<genuinely manual items only (including E2E-skipped scenarios), or "> All scenarios are covered by automated tests above.">
```

#### §3.7.3 Write body to temp file

Use the **Write tool** (not Bash heredoc — per `_bash_rules.md`) to write the body to `/tmp/sdd-pr-body-$1.md`.

#### §3.7.4 Create PR

```bash
gh pr create --title "<title>" --body-file /tmp/sdd-pr-body-$1.md
```

Title convention from `git log --oneline -20`:
- Single Issue: `feat: <feature>` or matching repo convention.
- Child Issue: same pattern derived from child Issue title.

(Substitute the literal `<title>` value; do NOT use shell expansion / `$(...)`.)

#### §3.7.5 Capture PR number

```bash
gh pr view --json number -q .number
```

Observe the literal number. Hold as `<PR_NUM>`.

### §3.8 Phase 4 success

Whether via §3.6 (R8 soft retry) or §3.7 (true first-round), `<PR_NUM>` is now known. Proceed to §4 PR Final round 1.

Atom-level failure anywhere in §3 → return `FAIL: <reason>` from this `_pr_final.md` execution.

### §3.8.5 Coverage Ledger — record PR number

If §3.4.5 finalized the ledger (skip this section if the ledger was absent):

1. In the ledger object held in narrative, set `pr: <PR_NUM>` (literal number; applies on both the §3.7 first-round path and the §3.6 R8 path).
2. **Write tool** — re-render to `/tmp/sdd-coverage-ledger-$1.md` (body otherwise unchanged from §3.4.5).
3. **Bash** — PATCH using the comment `<id>` held from §3.4.5 (re-run the duplicate-prevention search from §3.4.5 item 8 first if the id is no longer in context):

   ```bash
   gh api repos/<owner>/<repo>/issues/comments/<id> -X PATCH --field body=@/tmp/sdd-coverage-ledger-$1.md
   ```

Non-blocking on failure: log a warning and proceed to §4.

---

## §4. Phase 5 — PR Final review loop (3 rounds)

`spec/stage/implement.md` §7; `design/stage-designs/implement.md` §12. Most complex orchestration in the stage.

Local state:
- `round` counter — starts at 1.
- Per round verdict combiner — tracked through §4.6.

```
§4.0 /review Skill (once, pre-loop, round 1 only)  # holistic PR overview; informational
For round in [1, 2, 3]:
    if round > 1:
        run §4.2 retry mode (inlined implement_pr retry mode)
    §4.3.a SDD reviewer 1 — completeness        # serial
    §4.3.b SDD reviewer 2 — quality              # serial after a
    §4.3.c SDD reviewer 3 — adversarial          # serial after b
    §4.4   /code-review Skill                    # serial after c
    §4.5   /security-review Skill                # serial after /code-review (skip on shallow)
    §4.6   Post tools-summary marker
    §4.7   Combine verdict
    if PASS: exit loop → return OK ADVANCE PR: #<PR_NUM>
    if FAIL and round < 3: continue loop
    if FAIL and round == 3: §5 Phase 5.5 escalation gate
```

### §4.0 `/review` Skill (pre-loop, round 1 only)

Invoked once immediately after `<PR_NUM>` is confirmed (§3.8), before the 3-round loop begins. Provides a holistic human-readable overview of the PR to inform the SDD reviewers.

#### §4.0.1 Invoke Skill

```
Skill tool call:
  skill: /review
  args: <PR_NUM>
```

(Substitute the literal `<PR_NUM>` value.)

#### §4.0.2 Graceful skip

Same pattern as §4.4.3:
- **Skill unavailable** → log warning to sub-agent narrative. Record for tools-summary (§4.6): `{"name": "review", "reason": "skill-unavailable"}`. Neutral for verdict.
- **Skill errored** → record `{"name": "review", "reason": "skill-errored: <first 80 chars of error>"}`. Neutral.
- **Successful** → output remains in sub-agent narrative (no PR comment posted — `/review` writes to conversation only). Record `{"name": "review"}` in `tools_run` for §4.6.

#### §4.0.3 Verdict impact

**Informational only.** `/review` output does NOT contribute to round verdict. It is included in the tools-summary marker (§4.6) for audit purposes only.

#### §4.0.4 Depth gate

`/review` runs regardless of `depth` (`default` / `deep` / `shallow`). No shallow-skip gate — unlike `/security-review`, it posts nothing to GitHub and incurs minimal cost at any depth.

#### §4.0.5 Round guard

Run §4.0 ONLY when entering the loop for the first time (`round == 1`). On rounds 2 and 3 (retry mode), skip §4.0 entirely. Always record `{"name": "review", "reason": "round>1"}` in `tools_skipped` for the tools-summary (same unconditional pattern as all other graceful-skip paths).

---

### §4.1 Serial ordering

`spec/edge-cases.md` §24 + `design/stage-designs/implement.md` §13.1: inside a sub-agent the platform constraint "Skill cannot share parallel batch with Agent" is moot (no Agent calls here). However, sub-agent convention preserves the serial ordering for:
1. **Verdict determinism** — SDD reviewer verdicts known before Skill verdicts.
2. **Code clarity** — round structure easier to reason about serially.
3. **Token economy** — outputs processed incrementally, not held simultaneously.

Full Phase 5 sequence: `§4.0` (pre-loop, round 1 only) → per-round: `5.N.1.a → 5.N.1.b → 5.N.1.c → 5.N.2 → 5.N.3 → 5.N.4 → 5.N.5`.

### §4.2 Retry mode — inlined `implement_pr` retry mode (rounds 2, 3)

`spec/stage/implement.md` §6 Retry mode; source atom `commands/atoms/implement_pr.md` "Work — retry mode". Triggered when `round >= 2` AND the prior round's §4.7 verdict was FAIL.

#### §4.2.1 Verify branch + PR

```bash
git rev-parse --abbrev-ref HEAD
gh pr list --head <branch_name> --state open --json number --jq '.[0].number'
```

Confirm number matches `<PR_NUM>`. If empty → return `FAIL: retry mode requested but no open PR for branch <branch_name>` (defensive — should never happen after Phase 4 succeeded).

#### §4.2.2 Update branch (best-effort)

```bash
git pull --ff-only origin <branch_name>
```

If this fails (e.g. network) — continue. Local state is still usable.

#### §4.2.3 Read PR diff

```bash
gh pr diff <PR_NUM>
```

#### §4.2.4 Self-fetch findings (PR-scoped)

a. Use `<PR_NUM>` as the comment scope for Section C self-fetch. Execute `<<SKILL_DIR>>/commands/atoms/_review_helpers.md` Section C with the 3 SDD markers PR-scoped:
   - `<!-- sdd:review:implement:completeness -->`
   - `<!-- sdd:review:implement:quality -->`
   - `<!-- sdd:review:implement:adversarial -->`

   (Marker exact match with trailing ` -->` per Section C.2 — prevents collision with `:tools` and `:step-*`.)

   Section C returns a sorted findings array (`critical → major → minor`).

b. Fetch `/code-review` + `/security-review` inline PR comments (line-anchored, posted via `pulls/<PR_NUM>/comments`):

   ```bash
   gh api repos/<owner>/<repo>/pulls/<PR_NUM>/comments --jq '.[] | {body: .body, path: .path, line: .line, created_at: .created_at, user_login: .user.login}'
   ```

   **Filter to Skill-authored comments only** (per `implement_pr.md` retry mode):
   - Body starting with `🔴` or `🟡` (first non-whitespace chars) → `/code-review` Important / Nit.
   - Body contains `Severity: High` / `Severity: Medium` / `Severity: Low` → `/security-review`.
   - Author `github-actions[bot]` is a secondary signal (Actions mode).

   Translate by severity:
   - 🔴 Important → `{severity: "critical", rule_id: "code-review-important", ...}`
   - 🟡 Nit → `{severity: "minor", rule_id: "code-review-nit", ...}`
   - 🟣 Pre-existing → **SKIP**.
   - Severity: High → `{severity: "critical", rule_id: "security-review-high", ...}`
   - Severity: Medium → `{severity: "major", rule_id: "security-review-medium", ...}`
   - Severity: Low / informational → `{severity: "minor", rule_id: "security-review-low", ...}`

   Append + re-sort (critical → major → minor; stable within group).

c. SDD-marker fetch returns `FAIL: ...` from Section C → return `FAIL: <reason>` from this `_pr_final.md`. Missing `/code-review` / `/security-review` comments are NOT a failure (those Skills may be gracefully skipped or produced no findings).

#### §4.2.5 Apply fixes

For each `critical` or `major` finding in the combined sorted array:
- **Decide fix kind**:
  - Code defect → modify production code.
  - Missing test → add a failing test first (mini Red), then implement (mini Green).
  - Test defect → modify the existing test.
  - Refactoring nit → adjust the implementation.
- Apply the fix.
- Re-run all tests → all pass.
- **Use `minor` entries as context**: if a `minor` cites the same file/line/rule_id as a critical/major you're fixing, read its `description` and `fix_suggestion` — they often pinpoint the exact line. Do not promote minors to standalone fixes unless trivial to address while already in-file.

#### §4.2.6 Commit fix-ups

```bash
git add <files>
git commit -m "fix: address review (round <N>) - <short summary>"
```

(Substitute literal round number and summary. No Claude co-author.)

**NEVER `--amend`. NEVER `--force-push`.**

#### §4.2.7 Push regular

```bash
git push -u origin <branch_name>
```

(No `--force` / `--force-with-lease`. Single simple Bash call.)

#### §4.2.8 Do NOT create new PR

Existing PR auto-updates on push.

### §4.3 SDD reviewers — serial (5.N.1.a / 5.N.1.b / 5.N.1.c)

3 SDD reviewers reason with **independent contexts** — no cross-visibility of each other's verdicts. In Arch B with serial execution inside one sub-agent, independence is enforced by **prose discipline**:
- Each reviewer reads ONLY its rubric + the shared PR diff + PR body from §4.3.a.2 — PR diff and Issue context are shared ground truth and are reused without re-fetching.
- Each reviewer does NOT read the other 2 reviewers' just-posted comments (even though those markers may exist on the PR from this round or prior).
- The sub-agent's narrative MUST treat each reviewer as a fresh logical pass — do NOT carry the prior reviewer's verdict into the next reviewer's reasoning.

#### §4.3.a Reviewer 1 — completeness

##### §4.3.a.1 Read rubric

Read `<<SKILL_DIR>>/commands/atoms/rubrics/implement-completeness.md`. Read also `<<SKILL_DIR>>/commands/atoms/implement_review.md` source for reference if needed — but the rubric file holds the criteria.

##### §4.3.a.2 Load PR diff + context

```bash
gh pr view <PR_NUM>
gh pr diff <PR_NUM>
```

For round > 1, the PR diff is already in context from §4.2.3 — skip `gh pr diff` and reuse. Issue context (design output, implement plan) is already in narrative context from earlier in the stage — do NOT re-fetch.

##### §4.3.a.3 Codebase exploration

Per `<<SKILL_DIR>>/commands/atoms/_review_helpers.md` Section D. Apply the Section D budget for the current `depth`. Verify file references in design against actual PR diff; read similar existing implementations to compare patterns.

##### §4.3.a.4 Apply criteria + verdict

Severity (per `implement_review.md` step 7):
- **critical** — broken functionality, security vulnerability, missing requirement.
- **major** — inconsistency, significant quality issue, poor test coverage.
- **minor** — style, naming, minor improvement.

Verdict per Common Contracts §5: critical/major → FAIL; only minor or none → PASS.

##### §4.3.a.5 Post review comment on PR via Section F

Marker: `<!-- sdd:review:implement:completeness -->`. Temp path: `/tmp/sdd-review-implement-completeness-pr<PR_NUM>.md`.

Body shape:
```
<!-- sdd:review:implement:completeness -->
## AI Review (implement / completeness)

**Verdict:** PASS | FAIL
**Model:** opus

### Issues
- **[critical]** path/to/file.ts:42 — <description>
- **[major]** <description>
- **[minor]** <description>

### Suggestions
<if any>

<!-- sdd:findings:json -->
```json
{<structured findings per _review_helpers.md Section B.2, stage="implement", role="completeness", issue=<$1>, pr=<PR_NUM>, round=<N>, verdict, model="opus", findings, suggestions>}
```
<!-- /sdd:findings:json -->
<!-- /sdd:review:implement:completeness -->
```

Procedure (Section F):
1. **Write tool** → `/tmp/sdd-review-implement-completeness-pr<PR_NUM>.md`.
2. **Bash** duplicate-prevention search:
   ```bash
   gh api repos/<owner>/<repo>/issues/<PR_NUM>/comments --jq '.[] | select(.body | contains("<!-- sdd:review:implement:completeness -->")) | .id'
   ```
   (PR comments live under `/issues/<PR_NUM>/comments` per Section F.)
3. **Bash** branch:
   - Empty → `gh pr comment <PR_NUM> --body-file /tmp/sdd-review-implement-completeness-pr<PR_NUM>.md`
   - Has id `<id>` → `gh api repos/<owner>/<repo>/issues/comments/<id> -X PATCH --field body=@/tmp/sdd-review-implement-completeness-pr<PR_NUM>.md`

NOTE: `--field` (NOT `-F`) per Common Contracts §9 and `design/stage-designs/implement.md` §12.2.

##### §4.3.a.6 Record verdict

Hold `completeness_verdict = PASS | FAIL` (with one-line summary if FAIL). Move to §4.3.b.

Atom-level error (rubric load failure, gh API failure, missing PR diff, etc.) → return `FAIL: <reason>` from this `_pr_final.md`.

#### §4.3.b Reviewer 2 — quality

Same structure as §4.3.a with substitutions:
- Rubric: `<<SKILL_DIR>>/commands/atoms/rubrics/implement-quality.md`.
- Marker: `<!-- sdd:review:implement:quality -->`.
- Temp path: `/tmp/sdd-review-implement-quality-pr<PR_NUM>.md`.
- Findings JSON `role`: `"quality"`.

Reuse the PR diff and Issue context already in context from §4.3.a.2 — no re-fetch. Independence invariant: do NOT incorporate completeness verdict into this reviewer's reasoning.

Record `quality_verdict = PASS | FAIL`. Move to §4.3.c.

#### §4.3.c Reviewer 3 — adversarial

Same structure with substitutions:
- Rubric: `<<SKILL_DIR>>/commands/atoms/rubrics/implement-adversarial.md`.
- Apply the adversarial lens from Section E of `_review_helpers.md` — already in context from the Section D exploration step above; no separate Read needed.
- Marker: `<!-- sdd:review:implement:adversarial -->`.
- Temp path: `/tmp/sdd-review-implement-adversarial-pr<PR_NUM>.md`.
- Findings JSON `role`: `"adversarial"`.
- **Codebase exploration (mandatory)** per `implement_adversarial.md` step 6 — read 1+ similar pattern, compare against new implementation; Grep for TODO/FIXME introduced in the PR; check `Refs #$1` traceability.
- Lens: **REFUTE** the PR. Mentally mutate the implementation, find edge cases the author missed, surface hidden coupling.

Reuse the PR diff and Issue context already in context — no re-fetch. Independence invariant: do NOT incorporate completeness or quality verdicts into this reviewer's reasoning.

Record `adversarial_verdict = PASS | FAIL`. Proceed to §4.4.

### §4.4 `/code-review` Skill (5.N.2)

#### §4.4.1 Determine effort by depth

| `depth` | `--effort` |
|---|---|
| `default` | `high` |
| `deep` | `max` |
| `shallow` | `medium` |

#### §4.4.2 Invoke Skill

```
Skill tool call:
  skill: /code-review
  args: --effort <high|max|medium> --comment --pr <PR_NUM>
```

(Substitute literal effort value and `<PR_NUM>`.)

#### §4.4.3 Graceful skip

Detect outcome:
- **Skill unavailable** (semantic error from Skill tool — older Claude Code, Skill disabled) → log warning to sub-agent narrative. Record for tools-summary (§4.6): `{"name": "code-review", "reason": "skill-unavailable"}`. Skipped Skills are **neutral** for verdict (do NOT contribute to FAIL).
- **Skill errored** (Skill ran but returned non-success / error markers in output) → record `{"name": "code-review", "reason": "skill-errored: <first 80 chars of error>"}` per `design/stage-designs/implement.md` §13.3 [IMPROVE — splits "unavailable" vs "errored" for audit]. Same neutral treatment.
- **Skill ran successfully** → continue §4.4.4.

#### §4.4.4 Count findings

After Skill returns, read PR inline comments to extract findings count:

```bash
gh api repos/<owner>/<repo>/pulls/<PR_NUM>/comments --jq '.[] | select((.body | startswith("🔴")) or (.body | startswith("🟡")) or (.body | startswith("🟣"))) | {body: (.body[0:80]), path: .path, line: .line}'
```

(Filter to Skill-authored: body starts with 🔴 / 🟡 / 🟣. Author `github-actions[bot]` is secondary signal.)

Count by severity:
- 🔴 Important → critical (contributes FAIL).
- 🟡 Nit → minor (does NOT contribute to FAIL).
- 🟣 Pre-existing → **IGNORED for verdict**.

If `code-review` produced **1+ 🔴 Important** → record `code_review_verdict = FAIL`. Else `code_review_verdict = PASS`.

Record the counts (X 🔴 / Y 🟡 / Z 🟣) for the tools-summary body in §4.6.

### §4.5 `/security-review` Skill (5.N.3)

#### §4.5.1 Shallow-skip gate

If `depth == shallow` → SKIP `/security-review`. Record for tools-summary: `{"name": "security-review", "reason": "shallow-label-skip"}`. Neutral for verdict.

Skip to §4.6.

#### §4.5.2 Invoke Skill

```
Skill tool call:
  skill: /security-review
  args: --pr <PR_NUM>
```

(No `--effort` — Skill self-calibrates.)

#### §4.5.3 Graceful skip

Same pattern as §4.4.3:
- Unavailable → `{"name": "security-review", "reason": "skill-unavailable"}`. Neutral.
- Errored → `{"name": "security-review", "reason": "skill-errored: <truncated>"}`. Neutral.
- Successful → continue §4.5.4.

#### §4.5.4 Count findings

Read PR inline comments authored by the Skill:

```bash
gh api repos/<owner>/<repo>/pulls/<PR_NUM>/comments --jq '.[] | select(.body | contains("Severity: ")) | {body: (.body[0:80]), path: .path, line: .line}'
```

Classify:
- Severity: High → critical (contributes FAIL).
- Severity: Medium → major (contributes FAIL).
- Severity: Low / informational → minor (does NOT contribute to FAIL).

If `security-review` produced **1+ High OR 1+ Medium** → record `security_review_verdict = FAIL`. Else `security_review_verdict = PASS`.

Record counts (A High / B Medium / C Low) for §4.6.

### §4.6 Post tools-summary marker (5.N.4) — in-place per round

Marker `<!-- sdd:review:implement:tools -->` on PR. Updated in place across rounds (latest round PATCHes prior body).

Body shape (per `spec/stage/implement.md` §7 5.1.4 + `design/stage-designs/implement.md` §12.6):

```
<!-- sdd:review:implement:tools -->
## SDD External Tools (round <N>)

**Round:** <N>
**/review:** ran (round 1, overview in narrative) | skipped (skill-unavailable | skill-errored: <truncated> | round>1)
**/code-review:** ran (effort: <high|max|medium>) | skipped (skill-unavailable | shallow-label-skip | skill-errored: <truncated>)
**/security-review:** ran | skipped (shallow-label-skip | skill-unavailable | skill-errored: <truncated>)

<details>
<summary>Tools details</summary>

- /review: ran (overview in narrative) | skipped (<reason>)
- /code-review: X 🔴 Important, Y 🟡 Nit, Z 🟣 Pre-existing
- /security-review: A High, B Medium, C Low

</details>

<!-- sdd:findings:json -->
```json
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
  "tools_run": [...],
  "tools_skipped": [...]
}
```
<!-- /sdd:findings:json -->
<!-- /sdd:review:implement:tools -->
```

(Substitute literal `<N>`, `<PR_NUM>`, counts, effort, and the `tools_run` / `tools_skipped` arrays tracked in §4.0 / §4.4 / §4.5.)

Procedure (Section F):
1. **Write tool** → `/tmp/sdd-implement-tools-$1-round-<N>.md`.
2. **Bash** duplicate-prevention search:
   ```bash
   gh api repos/<owner>/<repo>/issues/<PR_NUM>/comments --jq '.[] | select(.body | contains("<!-- sdd:review:implement:tools -->")) | .id'
   ```
3. **Bash** branch:
   - Empty → `gh pr comment <PR_NUM> --body-file /tmp/sdd-implement-tools-$1-round-<N>.md`
   - Has id `<id>` → `gh api repos/<owner>/<repo>/issues/comments/<id> -X PATCH --field body=@/tmp/sdd-implement-tools-$1-round-<N>.md`

**Informational only** — does NOT affect verdict. Verdict logic in §4.7 reads `completeness_verdict`, `quality_verdict`, `adversarial_verdict`, `code_review_verdict`, `security_review_verdict` directly (not this marker).

### §4.7 Round verdict (5.N.5)

Round combiner:

| Conditions | Round verdict |
|---|---|
| ANY SDD reviewer returned FAIL | **FAIL** |
| `/code-review` produced 1+ 🔴 Important | **FAIL** |
| `/security-review` produced 1+ High OR 1+ Medium | **FAIL** |
| All 3 SDD PASS AND /code-review PASS-or-skipped (no Important) AND /security-review PASS-or-skipped (no High/Medium) | **PASS** |

Skipped Skills are NEUTRAL — they do NOT make the round fail. `tools_skipped` tracks the reason for audit.

#### §4.7.1 Adversarial-only FAIL warning

For R6 text and semantics, follow `<<SKILL_DIR>>/commands/atoms/_review_helpers.md` Section G — treat combined verdict as FAIL, no auto-pass.

#### §4.7.2 Round decision

| Round | Verdict | Next |
|---|---|---|
| 1 or 2 | PASS | Exit loop → return `OK ADVANCE PR: #<PR_NUM>` to `main.md` |
| 1 or 2 | FAIL | Increment round; back to §4.2 retry mode |
| 3 | PASS | Exit loop → return `OK ADVANCE PR: #<PR_NUM>` |
| 3 | FAIL | §5 Phase 5.5 escalation gate |

---

## §5. Phase 5.5 — Round 3 escalation gate

Triggered when `round == 3` AND §4.7 verdict was FAIL. Follow `<<SKILL_DIR>>/commands/atoms/_review_helpers.md` Section H:
- Summary format: `implement round 3 FAIL — findings: [critical] <X>, [major] <Y> (completeness=<P/F>, quality=<P/F>, adversarial=<P/F>, code-review=<P/F/skipped>, security-review=<P/F/skipped>). PR: #<PR_NUM> BRANCH: <branch_name>` — counts include all 3 SDD reviewers + `/code-review` 🔴 + `/security-review` High/Medium; write `skipped` for unavailable/shallow-skipped Skills.
- skip-review key: `pr`
- Auto-continue: return `OK ADVANCE PR: #<PR_NUM>` from this `_pr_final.md`. `main.md` §9 composes the final `OK ADVANCE: test` line (+ ` E2E_SKIPPED` if applicable).
- On ESCALATE: `main.md` returns the line verbatim. On user Continue, main re-spawns with `Resume: continue-after-escalation` — `main.md` §4.2 short-circuit returns `OK ADVANCE` directly.

---

## §6. Hard rules (this topic file)

- **No Agent spawns.** Single sub-agent invariant.
- **MAY use Skill tool** for `/review` (§4.0, once pre-loop, round 1 only), `/code-review`, and `/security-review`. Graceful skip on `skill-unavailable` / `skill-errored` / `shallow-label-skip` (the last only for `/security-review`). `/review` is **informational only** — does NOT contribute to FAIL verdict.
- **Serial ordering**: `/review` (§4.0, pre-loop, round 1 only) → per-round: `5.N.1.a → 5.N.1.b → 5.N.1.c → 5.N.2 → 5.N.3 → 5.N.4 → 5.N.5`. Sub-agent convention; preserved for verdict determinism + token economy.
- **Independence invariant** for 3 SDD reviewers: each uses the same PR diff + body + Issue context from §4.3.a.2 — no re-fetch. Do NOT carry prior reviewer's verdict into next reviewer's reasoning.
- **No force-push, no `--amend`.** Retry mode appends new commits.
- **No Claude as co-author.**
- **R8 auto-route is always on** — no `strict-pr-creation` config key per SYNTHESIS-v2 T1.1.
- **R8 safety**: existing PR body MUST contain `Refs #$1` or return `FAIL: existing PR ...does not reference Issue #$1`.
- **`--field`, NOT `-F`** for `gh api ... -X PATCH` per Common Contracts §9.
- **🟣 Pre-existing → SKIP for verdict AND retry** per Reviewer A GAP-A4. Including them as `minor` retry findings would waste cycles addressing pre-existing issues.
- **`skip-review: pr` consumed here** (Phase 5.5 escalation). `skip-review: implement` is consumed by `_tdd.md` §8.2 and `main.md` §5.2. `skip-review: qa` is consumed by main session AFTER `OK ADVANCE`.
- **All Bash per `_bash_rules.md`. All comment posting per `_review_helpers.md` Section F.**
- **Round-to-round overwrites** all 4 PR Final markers (3 reviewers + tools-summary). Prior-round bodies are lost. Findings JSON `round` field IS updated per PATCH.
- **Edit / Write tool permitted** only for the working tree (fix-up code in §4.2.5) and deterministic `/tmp/sdd-*.md` temp paths. NEVER touch files outside the working tree.
