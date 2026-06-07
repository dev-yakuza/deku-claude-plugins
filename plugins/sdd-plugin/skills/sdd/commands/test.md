# TEST

**Stage 4: Testing — Orchestrator**

QA verification + integration E2E for parent Issues. Unit/UI tests and E2E tests for single/child Issues were already done in Stage 3 (implement); this stage validates them and adds the QA gate.

This file is an **orchestrator**. It runs in the main session and composes atomic operations via the Agent tool. The atoms (`atoms/test_work.md`, `atoms/test_review.md`, `atoms/test_adversarial.md`, `atoms/parent_integration_review.md`) do the actual work; this file manages state, retries, manual QA interaction, and the final label transition to `sdd:done`.

> **Bash Command Execution**: run every shell snippet below as its own simple Bash tool call — no `&&`, `||`, `;`, `|`, `$(...)`, `VAR=$(...)`, or heredocs. Inline literal values; do not use shell variables. See **Bash Command Execution Rules** in `${CLAUDE_SKILL_DIR}/SKILL.md`.

## Input Validation

Before any other step: validate `$1` per Common Definitions → Issue Validation in `${CLAUDE_SKILL_DIR}/SKILL.md`. If `$1` is a Pull Request, stop without making changes.

## Phase 0: Depth label detection

Per `${CLAUDE_SKILL_DIR}/commands/atoms/_review_helpers.md` Section C:

```bash
gh issue view $1 --json labels --jq '[.labels[].name]'
```

Determine depth (`default` / `deep` / `shallow`).

**Model resolution for test stage**:

| Atom | default | deep | shallow |
|---|---|---|---|
| `test_work` | opus | opus | opus |
| `test_review` (completeness) | sonnet | opus | sonnet |
| `test_review` (quality) | sonnet | opus | sonnet |
| `test_adversarial` | opus | opus | sonnet |
| `parent_integration_review` | opus | opus | sonnet |

## Phase 1: Determine Issue type

1. Check for children comment:
   ```bash
   gh repo view --json nameWithOwner -q .nameWithOwner
   gh api repos/<owner>/<repo>/issues/$1/comments \
     --jq '.[] | select(.body | contains("<!-- sdd:children:output -->")) | .body'
   ```

2. **Parent Issue (has children)**: Verify all child Issues are `sdd:done` before proceeding:
   - Read child Issue numbers from the children comment.
   - Check each child's label.
   - If any child is NOT `sdd:done` → report which children are incomplete; ask user to complete them first; stop.
   - If ALL children are `sdd:done` → proceed to Phase 2 (work atom will run in parent path).
3. **Single/Child Issue**: proceed directly to Phase 2.

## Phase 2: Test + AI Review Loop

Up to **3 rounds** maximum. Each round = work atom → parallel review atoms → verdict check.

### Round 1

#### 2.1.1 — Spawn the work atom

- `subagent_type`: `general-purpose`
- `model`: `opus`
- `description`: `test work for #$1`
- `prompt`:
  > Read `${CLAUDE_SKILL_DIR}/commands/atoms/test_work.md` and execute its instructions for Issue #$1.
  > Return EXACTLY one line in the contract, prefixed by `>>> RESULT <<<`.

Parse the `>>> RESULT <<<` line:
- `FAIL: <reason>` → report failure, stop. (Special case: if reason starts with `no E2E test setup detected; recommended framework:` → surface to user, ask for framework choice, re-spawn with the chosen framework noted in the prompt as `Framework: <name>`.)
- `OK SINGLE PR: #N` → single/child path; existing PR validated. Continue. Remember `path=SINGLE`.
- `OK PARENT INTEGRATION_PR: #M` → parent path; integration test PR created. Continue. Remember `path=PARENT, integration_pr=#M`.
- `OK PARENT NO_INTEGRATION` → parent path; children's tests sufficient. Continue. Remember `path=PARENT, integration_pr=null`.

#### 2.1.2 — Spawn the review atoms in parallel

Single message, three Agent tool calls (concurrent) for single/child path, four for parent path:

Agent A (completeness):
- `subagent_type`: `general-purpose`
- `model`: per Phase 0 table
- `description`: `test review (completeness) for #$1`
- `prompt`:
  > Read `${CLAUDE_SKILL_DIR}/commands/atoms/test_review.md` and execute its instructions for Issue #$1 with role `completeness`.
  > Return EXACTLY one line in the contract, prefixed by `>>> RESULT <<<`.

Agent B (quality):
- `subagent_type`: `general-purpose`
- `model`: per Phase 0 table
- `description`: `test review (quality) for #$1`
- `prompt`:
  > Read `${CLAUDE_SKILL_DIR}/commands/atoms/test_review.md` and execute its instructions for Issue #$1 with role `quality`.
  > Return EXACTLY one line in the contract, prefixed by `>>> RESULT <<<`.

Agent C (adversarial):
- `subagent_type`: `general-purpose`
- `model`: per Phase 0 table
- `description`: `test adversarial for #$1`
- `prompt`:
  > Read `${CLAUDE_SKILL_DIR}/commands/atoms/test_adversarial.md` and execute its instructions for Issue #$1.
  > Return EXACTLY one line in the contract, prefixed by `>>> RESULT <<<`.

**If `path == PARENT`**, also include Agent D in the same parallel batch:

Agent D (parent integration):
- `subagent_type`: `general-purpose`
- `model`: per Phase 0 table
- `description`: `parent integration review for #$1`
- `prompt`:
  > Read `${CLAUDE_SKILL_DIR}/commands/atoms/parent_integration_review.md` and execute its instructions for Issue #$1.
  > Return EXACTLY one line in the contract, prefixed by `>>> RESULT <<<`.

Parse all (3 or 4) `>>> RESULT <<<` lines:
- Any is `FAIL: <reason>` (atom error) → report, stop.
- All `OK PASS` → reviews passed; exit loop → Phase 3.
- Any `OK FAIL: <summary>` → reviews failed. Combine summaries.
- **Adversarial single-FAIL escalation**: if `OK FAIL` came only from adversarial, log to user.

#### 2.1.3 — Round decision

- Reviews passed → exit loop → Phase 3.
- Reviews failed, round < 3 → build **structured retry feedback**:
  1. Fetch review comments from the Issue and (for single/child path) the PR.
  2. Extract `<!-- sdd:findings:json -->` JSON blocks from each FAILed reviewer.
  3. Combine findings, filter to severity ∈ {critical, major}.
  4. Pass combined JSON array as `$2` in the next round's work atom prompt.
- Reviews failed, round == 3 → exit loop → **Phase 2.5 (escalation)**.

### Round 2 and Round 3 (retry)

Same as Round 1 Steps 2.1.1–2.1.3, with structured retry feedback as `$2`:

- `prompt`:
  > Read `${CLAUDE_SKILL_DIR}/commands/atoms/test_work.md` and execute its instructions for Issue #$1.
  > Previous round structured findings (address each item): <inlined JSON array>
  > Return EXACTLY one line in the contract.

## Phase 2.5: Round 3 Escalation Gate

Runs only if round 3 failed.

1. Render summary to user.
2. **Override skip-review** — ask regardless of skip-review setting:
   - Continue to Phase 2.7 / Pause / Stop?

## Phase 2.7: Behavioral verification (`/verify` Skill)

Runs **only on single/child path** (parent path uses children's verify results indirectly through E2E integration PR).

Skip if `sdd:review:shallow` label is set on the Issue (low-confidence runs).

Invoke the `/verify` Skill via the Skill tool to **launch the project's app and observe behavior** for the implemented feature. This complements the AI review (which checks code) and the manual QA (which checks user perception) — `/verify` answers "does the app actually run and behave as expected?"

**Graceful skip**: if the `/verify` Skill is unavailable (Claude Code v2.1.145 or earlier, Skill disabled, no app-launch capability detected for the project type), log a warning and proceed to Phase 3 without behavioral verification.

After `/verify` returns:
- Parse its output (transcript-based; the Skill reports what it observed).
- Map to SDD verdict:
  - "feature works as expected" → record as PASS evidence for Phase 3
  - "feature does not work" or "crash/error observed" → record as FAIL evidence; surface in Phase 3 user context

This phase **does not block** Phase 3 by itself — manual QA (or `skip-review: qa` auto-approval) decides final outcome. `/verify`'s result is *additional context* for that decision.

Record the verify outcome for the test output comment's self-review trace (Section F of `_preflight.md`):

```markdown
- [x] /verify ran: feature launches and matches description
```

or

```markdown
- [ ] /verify reported: error on login screen — see transcript
```

## Phase 3: User Review + Manual QA

This phase requires main-session interaction with the user for manual QA, unless `qa` is in skip-review.

### 3.1 — User-facing context

Present to the user:
- Test work atom's result (which path, PR numbers, integration PR if any)
- Review verdicts (PASS/FAIL with summaries)
- For parent path: parent_integration_review's summary, particularly any cross-stage gaps it surfaced
- **Behavioral verification result from Phase 2.7** (if `/verify` ran): whether the app actually launched and the feature worked
- Link to the Issue's test output comment for the full QA checklist

If the work atom flagged "E2E was skipped in Stage 3" for single/child path → ask the user whether to add E2E tests now (push to the PR branch) or proceed without.

### 3.2 — skip-review check

Check skip-review setting (Common Definitions → Skip Review Setting).

- **If `qa` is in skip-review**:
  - Log: "User review skipped (skip-review: qa)". Auto-approve test results and QA checklist.
  - Skip to **Phase 4** (Results Review).

- **If `qa` is NOT in skip-review**:
  - The user may add/remove/modify QA checklist items (the work atom posted the checklist; the user edits the Issue comment directly if needed).
  - **Manual QA (4-3)**: ask the user to perform manual QA based on the approved checklist and report pass/fail per item. Wait for the user's response.

## Phase 4: Results Review (4-4)

Based on the user's manual QA report (or auto-approval under skip-review):

1. **If any QA item failed** → analyze cause with the user, and go back to Stage 3 (`/sdd implement $1`) for a TDD bug-fix cycle. Stop this orchestrator.

2. **All tests pass** → update label and close:
   ```bash
   gh issue edit $1 --remove-label "sdd:test" --add-label "sdd:done"
   gh issue close $1
   ```

## Phase 5: Child completion notification (if this Issue is a child)

Same logic as `implement.md` Phase 7: when a child Issue (detected via the multi-language parent regex `(Parent|상위 |親)Issue: #<n>` per Common Definitions → Parent/Child Issue Detection in `${CLAUDE_SKILL_DIR}/SKILL.md`) just transitioned to `sdd:done`, update the parent's `<!-- sdd:children:output -->` table row, check whether all children are now done, and notify the user on the parent Issue accordingly.

(See `implement.md` Phase 7 for the detailed steps — they apply verbatim here, including the multi-language parent reference.)

## Notes

- **Atoms never spawn other atoms.** All Agent-tool spawning happens here.
- **3 parallel reviewers for single/child path; 4 parallel for parent path** (parent integration adds cross-stage synthesis).
- **Reviews location varies by path**: single/child → PR comments (review atoms decide based on path detection); parent → Issue comments. Parent integration review is always on the parent Issue with marker `<!-- sdd:review:parent -->`.
- **Manual QA stays in the main session.** It is inherently human-in-the-loop.
- **Retry feedback is structured JSON.** Lossless handoff.
- **Retry limit is 3 rounds total** (initial + 2 retries) for the AI review phase, then escalation gate. Manual QA failures route back to Stage 3.
- **Depth label override**: `sdd:review:deep`/`sdd:review:shallow` shifts model assignments per `_review_helpers.md` Section C.
