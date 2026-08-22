# TEST (stage)

**Stage: test.** Role: **tester** (leader judges completion). Runs the tests, enforces the **verify gate** (raw evidence, not self-report); the leader judges automated-correctness completion and **advances to the QA stage** (test no longer marks `done` — QA does). Invocable directly (`/gld test <issue>`) or via `/gld dev`.

`$1` = Issue number. Returns a Section D line.

> **Bash**: `_bash_rules.md`. State/handoff: `_handoff.md`.
> **Output language**: all human-readable output in `config.language` (`_handoff.md` Section K); sub-agent prompts carry that instruction.

---

## Step 0 — Preflight
As the leader, follow `_preflight.md` **Medium tier**. Load the test cases (`docs/specs/$1/test-cases.md`), the design output, and any execute-stage evidence (`<!-- guild:test-evidence:step-1 -->`). Load `docs/standards/verification.md` for the verify rules + DoD.

Validate `$1` is an Issue. **Read current labels first** (its own Bash call): `gh issue view $1 --json labels --jq '[.labels[].name] | map(select(startswith("guild:")))'`.

**Split-parent guard** (right here, before any other work): if that read contains `guild:children`, refuse — a parent at `guild:children` is in an *orchestration* state, not a stage (`_handoff.md` Section A: a parent never carries both `guild:children` and a stage label at once), so Step 3's transition would destroy the link `dev.md` Phase 2b uses to drive the children:
```
>>> RESULT <<<
FAIL: #$1 is a split parent (guild:children) — its work is its children's, not its own. Run `/gld dev $1` (or `/gld resume $1`) to drive the children.
```
(`guild:child` is **not** this case — a child legitimately carries `guild:child` + its stage label and proceeds normally.)

Empty → add `guild:test`. Non-empty → do not add on top (Step 3's transition removes whatever **stage** label was actually found here, not necessarily `guild:test` — never `guild:child`, a permanent identity marker a child Issue also carries alongside its stage label; `_handoff.md` Section A). Ensure the Issue's branch is checked out (the one implement created).

## Step 1 — Spawn tester (run + verify)
Spawn the tester sub-agent:
- `subagent_type`: `general-purpose`, `model`: `sonnet`, `description`: `tester verify #$1`
- `prompt`:
  > Adopt the persona in `.claude/agents/tester.md`. Execute the tests for Issue #$1 on the current branch — run the project's test command (unit + existing suites; E2E/manual QA are later milestones in M1). **Capture the raw runner output**. Confirm every acceptance-criterion test case from `docs/specs/$1/test-cases.md` is covered and passing. Verify gate: your pass claim MUST match the raw output — if they disagree, the raw output wins and you report the failure honestly. Do NOT weaken/skip tests to pass (INV2). **Honesty-of-scope (mandatory)**: explicitly declare WHAT you ran (with raw evidence) AND WHAT you did NOT run — specifically `commands.e2e` (integration/E2E) and manual/visual QA are NOT executed in M1. Never phrase your result as "fully QA'd" or "all problems verified" — the accurate claim is "automated tests (what you ran) pass and the written AC are test-covered."
  > **Risk-based E2E judgment (mandatory — not a blanket skip)**: M1 does not auto-run E2E, but you MUST still JUDGE whether this change warrants E2E regression, and state it: (a) **contained / low-risk** (local widget/util fix, no cross-screen flow or integration change) → "E2E 불요: <one-line reason>" — a *justified* skip; (b) **touches flows / navigation / integration / data sync** → "**E2E 회귀 권장: `<suite>`** — M1 자동 미실행, 사람이 실행 권장" — hand it to the human. Base the judgment on the diff's scope + the hotspot list, not on convenience.
  > Return one `>>> RESULT <<<` line per `_handoff.md` Section C, with the raw test summary line. Write output in `config.language`.

## Step 2 — verify gate (leader, mandatory)
As the leader, enforce the verify gate (`_handoff.md` Section E):
- Post the tester's raw runner output as evidence under `<!-- guild:test:output -->` … `<!-- /guild:test:output -->` (temp-file pattern), including the pass/fail summary and AC coverage.
- **Verification scope declaration (mandatory, honesty-of-scope)**: the output MUST have an explicit **검증 범위** block stating (a) what ran with evidence (e.g. `flutter test` unit, `flutter analyze`, golden), (b) **what did NOT run — `commands.e2e` (integration/E2E) and manual/visual QA** (deferred / the human in M1), and (c) the **risk-based E2E judgment** — either "E2E 불요: <reason>" (justified skip for a contained change) or "**E2E 회귀 권장: `<suite>`** (사람 실행)" (change touches flows/integration). A blanket silent skip is NOT acceptable — there must be a judgment. This makes "verify 통과" clearly mean *automated-test verification with a stated E2E risk call*, never "fully QA'd". Reject any output missing this block.
- Cross-check the tester's claim against the raw output. **Complete only on matching raw evidence.** If they disagree → the raw output wins; this is not done.
- Check the Definition of Done from `docs/standards/verification.md`.
- **Ground-truth capture (①, `_signals.md` Section C):** if the tester's claim **disagreed** with the raw output (a verify-gap), OR verify failed (tests red / AC gap), append one entry (its own Bash call). `--surprise` when a claimed pass was actually red (a confident self-report contradicted by evidence — the strongest ranking lever):
  ```bash
  python3 <<SKILL_DIR>>/commands/atoms/capture_signal.py --kind verify-gap --issue $1 --stage test --role tester --area "<the area under test>" --summary "<claimed vs raw / AC gap, 1 line>" --evidence "<raw runner summary line>" --surprise
  ```
  **Skip** when raw evidence matched the claim and was green — no gap means nothing to learn (agreement ≠ signal).

## Step 3 — Judge completion + return
- **Vacuous-test guard FIRST (INV2 spirit — #894 lesson) — apply before judging "verify passed" below, never after**: before accepting "AC covered", confirm the covering tests are **effective** — a test that passes but asserts nothing meaningful, or whose assertion does **not** react when the code-under-test breaks (the #894 disabled-contrast pattern: `meetsGuideline` skipped its check in the disabled path, so it passed regardless), is **not** coverage. If verify leans on a vacuous test, treat that AC as **uncovered** → loop back for a real assertion (do not proceed to the "Verify passed" bullet below for that AC). A green suite of vacuous tests is not a pass.
- **Verify passed** (raw evidence green + AC covered **by the guard above, not vacuously** + DoD met) → advance to the **QA stage** (holistic quality follows automated correctness). Remove **whatever `guild:*` stage label Step 0 actually found** (substitute in place of `guild:test` below if it was something else; **never remove `guild:child`** if present). **Also remove `guild:needs-human` in this same call if Step 0's label read found it present** (`_handoff.md` Section A):
  ```bash
  gh issue edit $1 --remove-label "guild:test" --add-label "guild:qa" --remove-label "guild:needs-human"
  ```
  **Verify this edit landed** before returning (`_handoff.md` Section F — `gh` write failures): re-read the labels; a failed edit means the Issue is still at `guild:test`, so returning `OK ADVANCE: qa` would desynchronise the state model.
  Return:
  ```
  >>> RESULT <<<
  OK ADVANCE: qa
  ```
- **Verify failed** (tests red, or evidence contradicts claim, or AC gap) → do NOT mark done.
  - **Attended**: return `NEEDS_HUMAN: tests not green / AC gap — <one-line>; loop back to execute?` (the leader/human decides whether to loop back to `/gld implement $1`).
  - **Unattended** (`GLD_UNATTENDED=1`, `_handoff.md` Section H): before each loop-back, apply the **stagnation guard** (`_stagnation.md`) — the same test(s)/AC gap recurring after a loop-back → escalate immediately (`OK PAUSE: needs-human — stagnant loop-back — <reason>`, `--kind stagnation` capture) rather than consuming the remaining attempt. Otherwise the leader auto-decides — bounded loop-back to execute (≤2 attempts); if still failing, add the **`guild:needs-human` label** + a `<!-- guild:needs-human -->` comment stating the gap, and return `OK PAUSE: needs-human — tests not green / AC gap` (do NOT transition the stage label). **Never weaken/skip tests to pass** (INV2). Detect mode via `printenv GLD_UNATTENDED`.
  ```
  >>> RESULT <<<
  NEEDS_HUMAN: tests not green / AC gap — <one-line>; loop back to execute?
  ```
- Hard error → `FAIL: <reason>`.

## Note — test hands off to QA
`test` proves **automated correctness** (unit/existing + golden + analyze, cross-checked against raw evidence); it then advances to the **QA stage** (`guild:qa`) for holistic quality. `test` no longer marks `done` — the QA stage does, after its risk-based quality pass. So the `test` output should be scoped as "automated correctness verified; holistic QA follows" — never imply full QA here. The guided-review nudge fires at `done` (QA stage — `qa.md` owns it, both on direct `/gld qa` invocation and via `/gld dev` Phase 3), never here — `test` only ever advances to `guild:qa`, it doesn't reach `done` even on a direct `/gld test` invocation, so there is nothing to nudge yet at this stage.

## Hard rules
- **Verify gate is the concrete `_handoff.md` Section E check** — raw runner output is the only accepted proof of green.
- **No verification weakening** (INV2).
- Read-only against source (test runs the suite; it does not modify implementation — fixes go back through execute).
