# QA (stage)

**Stage: QA — holistic quality.** Role: **qa** (leader judges), plus a conditional **UI/UX review gate** (designer) when the change has a UI surface (Step 1.5). Runs **after `test`** (automated correctness) and before `done`. QA covers what automated tests don't: exploratory testing, E2E user flows, usability, real-app robustness — from the **user's black-box perspective**. Depth is **risk-based** (a tiny fix gets a light QA judgment; a UI feature gets exploratory + E2E planning). Invocable directly (`/gld qa <issue>`) or via `/gld dev`.

`$1` = Issue number. Returns a Section D line (`_handoff.md`).

> **Test vs QA (distinct)**: `test` = tester, automated correctness proof (white-box, AC-driven, verify gate). **QA** = qa role, holistic quality (black-box, user flows, exploratory, E2E, usability). QA builds on test's coverage; it does not repeat it.

> **Bash**: `<<SKILL_DIR>>/commands/atoms/_bash_rules.md`. State/handoff: `<<SKILL_DIR>>/commands/atoms/_handoff.md`.

---

## Step 0 — Preflight
As the leader, follow `_preflight.md` **Medium tier**. Load: `<!-- guild:test:output -->` (verify result + AC coverage + the tester's risk-based E2E judgment), the PR, design/UX outputs (`docs/specs/$1/`), and the hotspot list. Load `docs/standards/quality-bar.md` + `verification.md`.

Validate `$1` is an Issue. Ensure entry label `guild:qa` if invoked directly.

## Step 1 — Spawn qa (risk-based quality plan + execution)
Spawn the qa sub-agent:
- `subagent_type`: `general-purpose`, `model`: `sonnet`, `description`: `qa #$1`
- `prompt`:
  > Adopt the persona in `.claude/agents/qa.md`. Do holistic QA for Issue #$1 on the current branch — **do NOT repeat the tester's automated coverage**; cover what it can't. Steps:
  > 1. **Risk-based QA plan**: from the diff scope + hotspot list + AC, decide what quality checks the change warrants — exploratory scenarios, E2E user flows, usability/visual, manual/real-device. A tiny contained change → a light justified plan; a UI/flow change → a fuller plan.
  > 2. **Execute what you can**: run E2E if available and warranted (`commands.e2e`), exploratory reasoning over user flows, check the AC from a user's perspective. **Capture raw evidence** for anything you run (`_handoff.md` Section E — honesty).
  > 3. **Flag human QA**: anything M1 can't auto-run (manual/visual/real-device) → state clearly WHAT to check and WHERE, for the human. Justified skip vs recommended-human-QA — never a blanket silent skip.
  > Return one `>>> RESULT <<<` line per `_handoff.md` Section C, with a QA summary.

## Step 1.5 — UI/UX review gate (conditional — designer)
As the leader, if this change had a **UI/UX surface** (a `docs/specs/$1/ux.md` exists, or the designer participated in design, or the diff touches UI), convene the **designer** to run the **UI/UX review gate**: the built UI vs the design intent (`ux.md`) — interaction, visual, usability, accessibility. This is a **gate** (reviewing the built result, not self-review of the designer's own spec is acceptable here because the artifact under review is the *implementation*, not the ux.md). No UI surface → skip this step.
- `subagent_type`: `general-purpose`, `model`: `sonnet`, `description`: `designer ui/ux review #$1`
- `prompt`:
  > Adopt the persona in `.claude/agents/designer.md`. Run the **UI/UX review gate** for Issue #$1 on the current branch. Compare the built UI against the design intent in `docs/specs/$1/ux.md` (if present) and the AC — interaction, visual, usability, accessibility (contrast, touch targets, states). You review the built result, not design anew. Return one `>>> RESULT <<<` line per `_handoff.md` Section C — `DONE`, `DONE_WITH_CONCERNS: <one-line>`, or `BLOCKED: <a11y/usability defect>`.

Fold the verdict into Step 2: a designer `BLOCKED` (real a11y/usability defect) blocks `done` the same as a QA defect.

## Step 2 — QA gate (leader)
As the leader, post the QA result (and the UI/UX gate verdict, if it ran) under `<!-- guild:qa:output -->` (temp-file pattern):
- **QA 계획 & 결과**: what was planned, what ran (with evidence), what's recommended for human QA.
- **UI/UX 게이트**: if Step 1.5 ran, record the designer's verdict (pass / concerns / blocking a11y-usability defect).
- **honesty of scope**: automated-QA vs human-QA clearly separated (same discipline as the verify gate). "QA 통과" means *the automated/agent-doable quality checks passed + a human-QA plan is stated* — never "fully QA'd by a human."
- If QA **or** the UI/UX gate surfaces a real defect → do NOT advance; return `NEEDS_HUMAN` (loop back to execute) or record the concern.
- **Ground-truth capture (①, `_signals.md` Section C — agent↔agent correction):** when QA or the UI/UX gate surfaces a **real blocking defect** (the test stage proved correctness-green, yet QA/designer found a defect it missed), append one entry (its own Bash call, best-effort — never blocks). The concrete defect **is** the objective anchor — one role overturning the test-stage pass, not self-review (`_signals.md` Section B). `--surprise` always (a confident pass overturned — plan §8-A):
  ```bash
  python3 <<SKILL_DIR>>/commands/atoms/capture_signal.py --kind correction --issue $1 --stage qa --role <qa|designer> --area "<the area of the defect>" --summary "<the defect QA/UX found that test missed, 1 line>" --evidence "<user flow / a11y measure, 1 line>" --surprise
  ```
  **Skip** on a clean QA pass, and skip human-QA *recommendations* that are not defects (a deferred manual/visual check ≠ a correction).

## Step 2.5 — Manual Test Checklist → PR 본문 (사람 QA를 리뷰 자리로)
Surface the **human-only** QA items where the human actually reviews/merges — PATCH the open PR's body with a checklist. (The qa output comment records the full plan; this puts the *actionable human items* in the PR body, like `sdd`.)
- **⚠ Scope — automated-IMPOSSIBLE only.** Include **only** what neither the `test` stage (automated correctness) nor the qa agent could verify: manual/visual judgment, real-device behavior, external integrations, interactive flows needing human perception. **Exclude anything an automated test already covers** — `test` proved it, so listing it is redundant noise — and anything the qa agent already ran with evidence. The checklist is the human's *irreducible* manual surface, nothing more.
- **Empty → skip entirely.** If everything was automatable / agent-doable (no genuine human-only item), do **not** add an empty section; the qa output's "자동 검증으로 충분" note suffices.
- Find the open PR (`gh pr list --repo <owner>/<repo> --search "Refs #$1" --state open --json number`). None open → skip (the human-QA plan still lives in the qa output).
- PATCH the body via the temp-file **marker** pattern (`_handoff.md` Section B, applied to the PR body): the section is bounded by `<!-- guild:manual-qa -->` … `<!-- /guild:manual-qa -->` and is **updated in place** on re-run (idempotent — never duplicated). Preserve everything outside the markers (INV4). Body via temp file:
  ```bash
  gh pr edit <PR_NUM> --repo <owner>/<repo> --body-file <temp>
  ```
- Format — a checkbox list, each item = **WHAT to verify + WHERE/HOW**:
  ```markdown
  <!-- guild:manual-qa -->
  ## 사람 QA 체크리스트 (Manual Test Checklist)
  자동 테스트로 검증 불가능한 항목만 (test 스테이지가 커버하는 것은 제외):
  - [ ] <무엇을 확인하는가> — <어디서 / 어떻게>
  - [ ] …
  <!-- /guild:manual-qa -->
  ```

## Step 3 — Judge + return
- **QA passed** (agent-doable checks green + UI/UX gate passed or not applicable + human-QA items clearly flagged + quality-bar met) → transition to done:
  ```bash
  gh issue edit $1 --remove-label "guild:qa" --add-label "guild:done"
  ```
  Return:
  ```
  >>> RESULT <<<
  OK DONE
  ```
  **Nudge the guided review** (the Issue is now `done` and the PR awaits the human reviewer — M1 external reviewer, INV1). When invoked directly (`/gld qa`), surface it here; under `/gld dev`, Phase 3 surfaces it: "이슈 #$1 리뷰 준비됨 (연결된 PR) — `/gld review $1`로 리스크 가중 가이드 리뷰를 받을 수 있습니다 (이슈 번호로 PR을 자동으로 찾습니다)." Do not force it on a trivial change.
- **QA found a blocking defect** → do NOT mark done.
  - **Attended**: return `NEEDS_HUMAN: QA found <one-line>; loop back to execute?`.
  - **Unattended** (`GLD_UNATTENDED=1`, `_handoff.md` Section H): record the concern; bounded loop-back to execute if fixable, else return `OK PAUSE: needs-human — QA defect: <one-line>`. Never force `done`. Detect via `printenv GLD_UNATTENDED`.
  ```
  >>> RESULT <<<
  NEEDS_HUMAN: QA found <one-line>; loop back to execute?
  ```
- Hard error → `FAIL: <reason>`.

## Note
`guild:done` after QA = "automated correctness (test) + agent-doable quality (QA) passed, with a stated human-QA plan; awaiting the human's manual/visual QA + PR approval." Still not "merged" and not "fully human-QA'd."

## Hard rules
- **Distinct from test** — do not re-run/duplicate the tester's automated suite; add the user-perspective layer.
- **Risk-based depth, never blanket skip** — always a judgment with a reason.
- **Honesty of scope** (both directions: results + coverage), per `_handoff.md` Section E.
- Read-only against source (QA observes; fixes go back through execute).
