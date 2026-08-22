# QA (stage)

**Stage: QA — holistic quality.** Role: **qa** (leader judges), plus a conditional **UI/UX review gate** (designer) when the change has a UI surface (Step 1.5). Runs **after `test`** (automated correctness) and before `done`. QA covers what automated tests don't: exploratory testing, E2E user flows, usability, real-app robustness — from the **user's black-box perspective**. Depth is **risk-based** (a tiny fix gets a light QA judgment; a UI feature gets exploratory + E2E planning). Invocable directly (`/gld qa <issue>`) or via `/gld dev`.

`$1` = Issue number. Returns a Section D line (`_handoff.md`).

> **Test vs QA (distinct)**: `test` = tester, automated correctness proof (white-box, AC-driven, verify gate). **QA** = qa role, holistic quality (black-box, user flows, exploratory, E2E, usability). QA builds on test's coverage; it does not repeat it.

> **Bash**: `<<SKILL_DIR>>/commands/atoms/_bash_rules.md`. State/handoff: `<<SKILL_DIR>>/commands/atoms/_handoff.md`.
> **Output language**: all human-readable output in `config.language` (`_handoff.md` Section K); sub-agent prompts carry that instruction.

---

## Step 0 — Preflight
As the leader, follow `_preflight.md` **Medium tier**. If `.claude/guild/config.json` is absent → `FAIL: Guild not initialized (run /gld init)`. Load: `<!-- guild:test:output -->` (verify result + AC coverage + the tester's risk-based E2E judgment), the PR, design/UX outputs (`docs/specs/$1/`), and the hotspot list. Load `docs/standards/quality-bar.md` + `verification.md`.

Validate `$1` is an Issue. **Read current labels first** (its own Bash call): `gh issue view $1 --json labels --jq '[.labels[].name] | map(select(startswith("guild:")))'`.

**Split-parent guard** (right here, before any other work): if that read contains `guild:children`, refuse — a parent at `guild:children` is in an *orchestration* state, not a stage (`_handoff.md` Section A: a parent never carries both `guild:children` and a stage label at once), so letting this stage run would transition the parent onto a stage label and destroy the link `dev.md` Phase 2b uses to drive its children:
```
>>> RESULT <<<
FAIL: #$1 is a split parent (guild:children) — its work is its children's, not its own. Run `/gld dev $1` (or `/gld resume $1`) to drive the children.
```
(`guild:child` is **not** this case — a child legitimately carries `guild:child` + its stage label and proceeds normally.)

Empty → add `guild:qa`. Non-empty → do not add on top (Step 3's transition removes whatever **stage** label was actually found here, not necessarily `guild:qa` — never `guild:child`, a permanent identity marker a child Issue also carries alongside its stage label; `_handoff.md` Section A).

## Step 1 — Spawn qa (risk-based quality plan + execution)
Spawn the qa sub-agent:
- `subagent_type`: `general-purpose`, `model`: `sonnet`, `description`: `qa #$1`
- `prompt`:
  > Adopt the persona in `.claude/agents/qa.md`. Do holistic QA for Issue #$1 on the current branch — **do NOT repeat the tester's automated coverage**; cover what it can't. Steps:
  > 1. **Risk-based QA plan**: from the diff scope + hotspot list + AC, decide what quality checks the change warrants — exploratory scenarios, E2E user flows, usability/visual, manual/real-device. A tiny contained change → a light justified plan; a UI/flow change → a fuller plan.
  > 2. **Execute what you can**: run E2E if available and warranted (`commands.e2e`), exploratory reasoning over user flows, check the AC from a user's perspective. **Capture raw evidence** for anything you run (`_handoff.md` Section E — honesty).
  > 3. **Prefer automating over deferring (mandatory check before flagging anything human-QA)**: for each check the plan calls for, first ask "can the project's OWN test framework — unit/widget/component level, not just `commands.e2e` — prove this?" Structural/behavioral claims (accessibility-tree grouping, focus/tab order, keyboard shortcuts, state-transition guards, error-message presence) are usually provable this way even when a full E2E run isn't warranted or available. If yes, **recommend the concrete test to write** (which API, what it asserts) instead of deferring it — this feeds the loop-back to test/execute, not the human checklist. Only what's left after this check proceeds to step 4.
  > 4. **Real-dependency one-off smoke (attended only) — a second escape hatch before deferring**: a check may need a real external dependency (a binary/API/service — install+auth+cost, so it can't go in `commands.e2e` or a repeatable CI gate) that *this execution environment already has working credentials/access to*. Don't default straight to human-QA for that. In an **attended session only** (never under `GLD_UNATTENDED` — a batch/unattended run always falls through to step 5 instead), and only if side effects can be safely isolated — ephemeral/temp state instead of the project's real persisted data, a scratch artifact that stays uncommitted and is deleted right after, no new ad hoc test entry point (respect whatever single-entry-point/runner convention the repo's own verification standard already has), and — if the dependency happens to be the same tool/runtime this agent itself is running under — spawned as a separate process/session so it can't collide with the agent's own state — run it yourself once and capture the raw evidence in the QA output (`_handoff.md` Section E; it's not reproducible later, so this is the only record). One successful real call per checklist item is enough — don't repeat it because the result is inconvenient (retries needed only to fix a broken harness, before any real call has succeeded, don't count against this). Any defect this smoke surfaces is a QA defect like any other (loop back / `NEEDS_HUMAN`) — never softened because it came from a throwaway harness. Isolation not achievable, or no working credentials → this bullet doesn't apply, fall through to step 5.
  > 5. **Flag human QA**: anything left after steps 3–4 that M1 still can't auto-run → state clearly WHAT to check and WHERE, for the human. Justified skip vs recommended-human-QA — never a blanket silent skip.
  > Return one `>>> RESULT <<<` line per `_handoff.md` Section C, with a QA summary (include any step-3 test recommendations and step-4 smoke evidence even when the issue still ends up looping back — they should not be silently dropped). Write output in `config.language`.

## Step 1.5 — UI/UX review gate (conditional — designer)
As the leader, if this change had a **UI/UX surface** (a `docs/specs/$1/ux.md` exists, or the designer participated in design, or the diff touches UI), convene the **designer** to run the **UI/UX review gate**: the built UI vs the design intent (`ux.md`) — interaction, visual, usability, accessibility. This is a **gate, not self-review**: the designer authored `ux.md` at design time, but here reviews the **built implementation** against it — a different artifact than the one they wrote, produced by the developer, which is what keeps this from being self-review (contrast: it would be self-review if the designer were re-checking `ux.md` itself). No UI surface → skip this step.
- `subagent_type`: `general-purpose`, `model`: `sonnet`, `description`: `designer ui/ux review #$1`
- `prompt`:
  > Adopt the persona in `.claude/agents/designer.md`. Run the **UI/UX review gate** for Issue #$1 on the current branch. Compare the built UI against the design intent in `docs/specs/$1/ux.md` (if present) and the AC — interaction, visual, usability, accessibility (contrast, touch targets, states). You review the built result, not design anew. Return one `>>> RESULT <<<` line per `_handoff.md` Section C — `DONE`, `DONE_WITH_CONCERNS: <one-line>`, or `BLOCKED: <a11y/usability defect>`. Write output in `config.language`.

Fold the verdict into Step 2: a designer `BLOCKED` (real a11y/usability defect) blocks `done` the same as a QA defect.

## Step 2 — QA gate (leader)
As the leader, post the QA result (and the UI/UX gate verdict, if it ran) under `<!-- guild:qa:output -->` (temp-file pattern):
- **QA 계획 & 결과**: what was planned, what ran (with evidence), what's recommended for human QA.
- **UI/UX 게이트**: if Step 1.5 ran, record the designer's verdict (pass / concerns / blocking a11y-usability defect).
- **honesty of scope**: automated-QA vs human-QA clearly separated (same discipline as the verify gate). "QA 통과" means *the automated/agent-doable quality checks passed + a human-QA plan is stated* — never "fully QA'd by a human."
- If QA **or** the UI/UX gate surfaces a real defect → do NOT advance; return `NEEDS_HUMAN` (loop back to execute) or record the concern.
- **Ground-truth capture (①, `_signals.md` Section C — agent↔agent correction):** when QA or the UI/UX gate surfaces a **real blocking defect** (the test stage proved correctness-green, yet QA/designer found a defect it missed), append one entry (its own Bash call, best-effort — never blocks). The concrete defect **is** the objective anchor — one role overturning the test-stage pass, not self-review (`_signals.md` Section B). `--surprise` always (a confident pass overturned):
  ```bash
  python3 <<SKILL_DIR>>/commands/atoms/capture_signal.py --kind correction --issue $1 --stage qa --role <qa|designer> --area "<the area of the defect>" --summary "<the defect QA/UX found that test missed, 1 line>" --evidence "<user flow / a11y measure, 1 line>" --surprise
  ```
  **Skip** on a clean QA pass, and skip human-QA *recommendations* that are not defects (a deferred manual/visual check ≠ a correction).

## Step 2.5 — Manual Test Checklist → PR 본문 (사람 QA를 리뷰 자리로) — **MANDATORY when human items exist**
**You MUST run this step whenever the qa output flagged ≥1 human-QA item — including on a re-run with no new findings** (it *surfaces* existing human items to the PR; it does not depend on finding anything new). Recording the items only in the `guild:qa:output` comment is **NOT sufficient** — the human reviews/merges at the **PR**, so the items MUST land in the PR body. `sdd`'s parity feature.
- **What goes in — every human-flagged item from Step 1/Step 2.** Take each item the qa plan marked as recommended/needed for human QA and make it a checklist entry. This explicitly **INCLUDES**:
  - anything the agent **could not run because of an environment/platform constraint** (e.g. "Windows 실기기 기동" verified only on macOS, real-device, external service) — this is the *canonical* automation-impossible item and **belongs in the checklist**;
  - manual/visual judgment, interactive flows needing human perception.
  - ⚠ **A "권장(recommended)" or "미검증(환경 제약)" framing does NOT downgrade it to a skippable caveat** — if a human needs to do it and the agent couldn't, it IS a checklist item.
- **What stays out** — what an automated test already proves (`test` covered it → redundant), what the qa agent already ran with evidence (**including a bullet-4 real-dependency smoke** — a successful one-off run with raw evidence closes the item, it does not become a checklist entry just because it wasn't repeatable/CI-gated), **and what Step 1's automatability check (bullet 3) identified as test-writable even if the test doesn't exist yet** — that's a coverage gap for the loop-back, not a human-QA item. Don't let "nobody wrote the test" get relabeled as "a human must check this."
- **Skip the section ONLY if the human-QA item count is literally zero** (everything was automated/agent-doable). "화면이 없어 exploratory 불요" does not by itself make it zero — a platform/real-device item still counts.
- **Find the open PR — resolve it broadly, the same way `review.md` Step 0 does.** A literal `"Closes #$1"` search is too narrow: a PR may use `Fixes`/`Fixed`/`Resolves`/`Resolved`/`Close`/`Closed` (all of GitHub's recognized closing keywords, case-insensitive), or link the Issue purely through the PR sidebar's "Development" feature with no closing keyword in the body text at all — so a PR that `/gld review $1` finds, this *mandatory* step would silently miss. Search broadly instead:
  ```bash
  gh pr list --repo <owner>/<repo> --search "#$1 in:body" --state open --json number,url,body
  ```
  Then, from the results, keep only PRs whose body actually contains `$1` as a closing/fixing reference (`\b(close[sd]?|fix(e[sd])?|resolve[sd]?)\s*:?\s*#$1\b`, case-insensitive) **or** where the body/title otherwise makes the link obvious.
- **Nothing found → do NOT silently skip a mandatory step.** Say so in the qa output: the checklist items still get reported in the `<!-- guild:qa:output -->` Issue comment, plus one line stating the PR could not be located (it may exist but be sidebar-linked, which `gh pr list --search` cannot see) so the human can paste them into the PR themselves.
- PATCH the body via the temp-file **marker** pattern (`_handoff.md` Section B, applied to the PR body): the section is bounded by `<!-- guild:manual-qa -->` … `<!-- /guild:manual-qa -->` and is **updated in place** on re-run (idempotent — never duplicated). Preserve everything outside the markers (INV4). ⚠ **`gh pr edit --body-file` REPLACES the entire PR body — it does not patch it**, which is why step 1 below is mandatory and not optional. In this order:
  1. **Read the current body first** (its own Bash call):
     ```bash
     gh pr view <PR_NUM> --repo <owner>/<repo> --json body --jq .body
     ```
  2. **Render the FULL new body to a temp file** (Write tool): the body fetched in step 1, verbatim, with the `<!-- guild:manual-qa -->` … `<!-- /guild:manual-qa -->` block replaced in place — or, if those markers are absent, the fetched body verbatim with the block appended at the end. Everything outside the markers is carried over unchanged (INV4).
  3. **Write it back**:
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

## Step 2.6 — Deferred follow-up scan (design docs → tracked issues) — MANDATORY when design artifacts exist
**Design docs self-flag out-of-scope work as deferred/follow-up** (e.g. tech-lead's skeleton.md "기술 부채 / 의식적 유예" section, a DBA/designer note proposing a later issue). Without this step nothing ensures those notes become **trackable** work — they can sit in `docs/specs/$1/` indefinitely, invisible past the PR that introduced them. (This gap was surfaced by a human catching it manually during `/gld review` — the exact failure mode this step exists to close.)

- **Applies only if `docs/specs/$1/` has design artifacts** (an analyze-only issue with no design docs skips this step).
- As the leader, read the design artifacts and identify items the authoring role explicitly deferred as **real, wanted work, deliberately not done in this issue**. This is a **judgment read, not a fixed-string grep** (`config.language` phrasing varies — a Korean repo might say "후속 이슈 제안", an English one "follow-up issue" or "out of scope for now, revisit later").
- **Do NOT count**: conditional/triggered deferrals with no concrete next action yet ("extract a shared helper if a 2nd similar case appears" — nothing to file until the trigger fires), items already resolved later in the same flow (design worried about X, execute/test proved it fine), or the AC's own stated non-goals (already the issue's explicit scope boundary, not a gap).
- For each real deferred item, **search existing issues** (`gh issue list --repo <owner>/<repo> --search "<keywords>" --state all`) for one that already covers it — dedupe by intent, not exact title match.
- **Unfiled items found** → do not auto-create (issue creation is visible/durable — the human decides, same posture as `init.md`'s harness-gap remediation). Instead:
  - **Attended**: list them to the human in one batched prompt — "설계 산출물이 남긴 후속 항목 N개, 아직 이슈 없음: ① … ② … — 지금 이슈로 만들까요?" (localized per `config.language`). On confirmation, create via the temp-file `gh issue create --body-file` pattern — title = the gap, body = 배경·AC(안)·근거(design doc file + section), `Depends on: #$1` — labeling with the repo's existing `type:*`/`area:*` labels where a clear match exists.
  - **Unattended** (`GLD_UNATTENDED=1`): never auto-create — append the list to the `<!-- guild:qa:output -->` comment under a `### 미등록 후속 항목` heading so the deferred human review (PR + merge, INV1) sees it; do not block `done` on it.
- **No unfiled items** (all covered, or none real) → say so in one line, no further action. Cheap when clean — do not force ceremony on a change with no design docs or no real deferrals.
- This runs **once per issue, at QA** — not repeated at `review`. QA is the mandatory spine stop every `/gld dev` run passes through; `review` is on-demand (nudged, not forced) and would miss unattended/batch runs entirely if this lived there instead.

## Step 3 — Judge + return
- **QA passed** (agent-doable checks green + UI/UX gate passed or not applicable + human-QA items clearly flagged + quality-bar met) → transition to done. Remove **whatever `guild:*` stage label Step 0 actually found** (substitute in place of `guild:qa` below if it was something else; **never remove `guild:child`** if present). **Also remove `guild:needs-human` in this same call if Step 0's label read found it present** (`_handoff.md` Section A):
  ```bash
  gh issue edit $1 --remove-label "guild:qa" --add-label "guild:done" --remove-label "guild:needs-human"
  ```
  Return:
  ```
  >>> RESULT <<<
  OK DONE
  ```
  **Nudge the guided review** (the Issue is now `done` and the PR awaits the human reviewer — M1 external reviewer, INV1). When invoked directly (`/gld qa`), surface it here; under `/gld dev`, Phase 3 surfaces it: "이슈 #$1 리뷰 준비됨 (연결된 PR) — `/gld review $1`로 리스크 가중 가이드 리뷰를 받을 수 있습니다 (이슈 번호로 PR을 자동으로 찾습니다)." Do not force it on a trivial change.
- **QA found a blocking defect** → do NOT mark done.
  - **Attended**: return `NEEDS_HUMAN: QA found <one-line>; loop back to execute?`.
  - **Unattended** (`GLD_UNATTENDED=1`, `_handoff.md` Section H): before looping back, apply the **stagnation guard** (`_stagnation.md`) — the same defect recurring after a loop-back → escalate immediately (`OK PAUSE: needs-human — stagnant loop-back — <reason>`, `--kind stagnation` capture) rather than consuming another attempt. Otherwise: record the concern; bounded loop-back to execute if fixable, else add the **`guild:needs-human` label** + a `<!-- guild:needs-human -->` comment stating the defect, and return `OK PAUSE: needs-human — QA defect: <one-line>` (do NOT transition the stage label). Never force `done`. Detect via `printenv GLD_UNATTENDED`.
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
- **Manual Test Checklist → PR body is mandatory when ≥1 human-QA item exists** (Step 2.5) — including on a no-new-findings re-run. A platform/real-device/manual item flagged "권장/미검증" still counts; the qa comment alone does not satisfy this — the item MUST be in the PR body where the human merges.
- **Deferred follow-up scan is mandatory when design artifacts exist** (Step 2.6) — a design doc's self-flagged tech-debt/deferred-work note is not "handled" until it's either matched to an existing issue or surfaced for filing; it must not silently rot in `docs/specs/$1/`.
- Read-only against source (QA observes; fixes go back through execute). *(The one exception: Step 2.5 edits the open PR **body** — a doc surface, not source — to carry the human checklist.)*
