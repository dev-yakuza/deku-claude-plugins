# TEST (stage)

**Stage: test.** Role: **tester** (leader judges completion). Runs the tests, enforces the **verify gate** (raw evidence, not self-report); the leader judges automated-correctness completion and **advances to the QA stage** (test no longer marks `done` — QA does). Invocable directly (`/gld test <issue>`) or via `/gld dev`.

`$1` = Issue number. Returns a Section D line.

> **Bash**: `_bash_rules.md`. State/handoff: `_handoff.md`.

---

## Step 0 — Preflight
As the leader, follow `_preflight.md` **Medium tier**. Load the test cases (`docs/specs/$1/test-cases.md`), the design output, and any execute-stage evidence (`<!-- guild:test-evidence:step-1 -->`). Load `docs/standards/verification.md` for the verify rules + DoD.

Validate `$1` is an Issue. Ensure entry label `guild:test` if invoked directly. Ensure the Issue's branch is checked out (the one implement created).

## Step 1 — Spawn tester (run + verify)
Spawn the tester sub-agent:
- `subagent_type`: `general-purpose`, `model`: `sonnet`, `description`: `tester verify #$1`
- `prompt`:
  > Adopt the persona in `.claude/agents/tester.md`. Execute the tests for Issue #$1 on the current branch — run the project's test command (unit + existing suites; E2E/manual QA are later milestones in M1). **Capture the raw runner output**. Confirm every acceptance-criterion test case from `docs/specs/$1/test-cases.md` is covered and passing. Verify gate: your pass claim MUST match the raw output — if they disagree, the raw output wins and you report the failure honestly. Do NOT weaken/skip tests to pass (INV2). **Honesty-of-scope (mandatory)**: explicitly declare WHAT you ran (with raw evidence) AND WHAT you did NOT run — specifically `commands.e2e` (integration/E2E) and manual/visual QA are NOT executed in M1. Never phrase your result as "fully QA'd" or "all problems verified" — the accurate claim is "automated tests (what you ran) pass and the written AC are test-covered."
  > **Risk-based E2E judgment (mandatory — not a blanket skip)**: M1 does not auto-run E2E, but you MUST still JUDGE whether this change warrants E2E regression, and state it: (a) **contained / low-risk** (local widget/util fix, no cross-screen flow or integration change) → "E2E 불요: <one-line reason>" — a *justified* skip; (b) **touches flows / navigation / integration / data sync** → "**E2E 회귀 권장: `<suite>`** — M1 자동 미실행, 사람이 실행 권장" — hand it to the human. Base the judgment on the diff's scope + the hotspot list, not on convenience.
  > Return one `>>> RESULT <<<` line per `_handoff.md` Section C, with the raw test summary line.

## Step 2 — verify gate (leader, mandatory)
As the leader, enforce the verify gate (`_handoff.md` Section E, plan §4):
- Post the tester's raw runner output as evidence under `<!-- guild:test:output -->` … `<!-- /guild:test:output -->` (temp-file pattern), including the pass/fail summary and AC coverage.
- **Verification scope declaration (mandatory, honesty-of-scope)**: the output MUST have an explicit **검증 범위** block stating (a) what ran with evidence (e.g. `flutter test` unit, `flutter analyze`, golden), (b) **what did NOT run — `commands.e2e` (integration/E2E) and manual/visual QA** (deferred / the human in M1), and (c) the **risk-based E2E judgment** — either "E2E 불요: <reason>" (justified skip for a contained change) or "**E2E 회귀 권장: `<suite>`** (사람 실행)" (change touches flows/integration). A blanket silent skip is NOT acceptable — there must be a judgment. This makes "verify 통과" clearly mean *automated-test verification with a stated E2E risk call*, never "fully QA'd". Reject any output missing this block.
- Cross-check the tester's claim against the raw output. **Complete only on matching raw evidence.** If they disagree → the raw output wins; this is not done.
- Check the Definition of Done from `docs/standards/verification.md`.
- **Ground-truth capture (①, `_signals.md` Section C):** if the tester's claim **disagreed** with the raw output (a verify-gap), OR verify failed (tests red / AC gap), append one entry (its own Bash call). `--surprise` when a claimed pass was actually red (a confident self-report contradicted by evidence — the strongest ranking lever, plan §8-A):
  ```bash
  python3 <<SKILL_DIR>>/commands/atoms/capture_signal.py --kind verify-gap --issue $1 --stage test --role tester --area "<the area under test>" --summary "<claimed vs raw / AC gap, 1 line>" --evidence "<raw runner summary line>" --surprise
  ```
  **Skip** when raw evidence matched the claim and was green — no gap means nothing to learn (agreement ≠ signal).

## Step 3 — Judge completion + return
- **Verify passed** (raw evidence green + AC covered + DoD met) → advance to the **QA stage** (holistic quality follows automated correctness):
  ```bash
  gh issue edit $1 --remove-label "guild:test" --add-label "guild:qa"
  ```
  Return:
  ```
  >>> RESULT <<<
  OK ADVANCE: qa
  ```
- **Vacuous-test guard (INV2 spirit — #894 lesson)**: before accepting "AC covered", confirm the covering tests are **effective** — a test that passes but asserts nothing meaningful, or whose assertion does **not** react when the code-under-test breaks (the #894 disabled-contrast pattern: `meetsGuideline` skipped its check in the disabled path, so it passed regardless), is **not** coverage. If verify leans on a vacuous test, treat that AC as **uncovered** → loop back for a real assertion. A green suite of vacuous tests is not a pass.
- **Verify failed** (tests red, or evidence contradicts claim, or AC gap) → do NOT mark done.
  - **Attended**: return `NEEDS_HUMAN: tests not green / AC gap — <one-line>; loop back to execute?` (the leader/human decides whether to loop back to `/gld implement $1`).
  - **Unattended** (`GLD_UNATTENDED=1`, `_handoff.md` Section H): before each loop-back, apply the **stagnation guard** (`_stagnation.md`) — the same test(s)/AC gap recurring after a loop-back → escalate immediately (`OK PAUSE: needs-human — stagnant loop-back — <reason>`, `--kind stagnation` capture) rather than consuming the remaining attempt. Otherwise the leader auto-decides — bounded loop-back to execute (≤2 attempts); if still failing, return `OK PAUSE: needs-human — tests not green / AC gap`. **Never weaken/skip tests to pass** (INV2). Detect mode via `printenv GLD_UNATTENDED`.
  ```
  >>> RESULT <<<
  NEEDS_HUMAN: tests not green / AC gap — <one-line>; loop back to execute?
  ```
- Hard error → `FAIL: <reason>`.

## Note — test hands off to QA
`test` proves **automated correctness** (unit/existing + golden + analyze, cross-checked against raw evidence); it then advances to the **QA stage** (`guild:qa`) for holistic quality. `test` no longer marks `done` — the QA stage does, after its risk-based quality pass. So the `test` output should be scoped as "automated correctness verified; holistic QA follows" — never imply full QA here. The guided-review nudge fires at `done` (QA stage / `dev`), not here. When reporting done (direct `/gld test` invocation), **nudge the guided pair review**: "PR 리뷰 준비됨 — `/gld review $1`로 리스크 가중 가이드 리뷰를 받을 수 있습니다."

## Hard rules
- **Verify gate is the concrete `_handoff.md` Section E check** — raw runner output is the only accepted proof of green.
- **No verification weakening** (INV2).
- Read-only against source (test runs the suite; it does not modify implementation — fixes go back through execute).
