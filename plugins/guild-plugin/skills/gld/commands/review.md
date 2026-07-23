# REVIEW (guided pair-programming walkthrough)

**Walk the human through the change one logical unit at a time — like the author pair-driving a review.** Not a one-shot report: an **interactive, paced** walkthrough that presents ONE change-unit, explains what + why, **pauses for discussion**, then moves to the next. M1's external reviewer is the human (PR approval, INV1); this makes that review a guided conversation instead of a raw-diff slog. **As of M3**, a fresh **adversarial pre-scan** (Step 2.5 — independent external auditor on the Standards/Spec axes) sharpens each unit's scrutiny; it is advisory (the human still approves).

`$1` = Issue number (preferred) or PR number. Optional `$2 = --comment` to post a recap to the PR at the end.

> **Bash**: `<<SKILL_DIR>>/commands/atoms/_bash_rules.md`. State: `<<SKILL_DIR>>/commands/atoms/_handoff.md`.
> **Output language**: conduct the walkthrough (narration, questions, recap) in `config.language` (`_handoff.md` Section K). Machine tokens / `file:line` refs stay ASCII.

> **This is a MULTI-TURN, interactive flow.** It runs in the **main session** (it must pause and wait for the human between units — a sub-agent cannot). The command *initiates* the walkthrough and presents the plan + first unit; each subsequent turn presents the next unit after the human responds. Track the current unit index in your reasoning (like an FSM). If interrupted, re-running `/gld review $1` restarts, or the human can say "continue from unit N".

> **VSCode limit (be honest)**: Claude cannot open/navigate/highlight files in the editor. Present each unit with **clickable `file:line` references** (the human clicks to open) and invite the human to **select the region** in the editor to discuss it (Claude sees the selection). Claude narrates; the human navigates.

> **⚠ Advisory by default, editable on request — review never modifies code unprompted.** Its core job is to (1) split the diff into logical units, (2) guide the human through them, and (3) **present Claude's review opinions** (the Step 2.5 findings) as *suggestions*. Claude does **not** edit, fix, or commit anything on its own initiative, and the Step 2.5 sub-agents **only report, never fix** (their independence as a 2nd opinion must stay intact — always read-only). But **if the human, mid-walk, explicitly asks Claude to fix something, Claude applies the edit directly** (not merely a proposal) — the human remains the approver (INV1) and can review/undo the change before continuing. Without an explicit request, review stays hands-off and the human applies changes themselves (or re-loops via `/gld dev`).

---

## Step 0 — Resolve the change
1. Resolve owner/repo (`_handoff.md` Section F).
2. If `$1` is an Issue → find its open PR (`gh pr list --repo <owner>/<repo> --search "Closes #$1" --state open --json number,headRefName,url`). If `$1` is a PR number, use directly. No PR → "no open PR for #$1 — run `/gld dev $1` first."

## Step 1 — Load rationale (light — so you can explain the WHY, not just the what)

**This command works on ANY open PR — agent-authored (from `/gld dev`) or human-authored.** Load whatever rationale exists; degrade gracefully when it doesn't.

- **Agent-authored PR (has Guild artifacts)**: read `<!-- guild:analyze:output -->` (interpretation + **AC**), `<!-- guild:design:output -->` (design intent + which specialists participated), `<!-- guild:test:output -->` (verify + AC coverage + recorded concerns), `<!-- guild:qa:output -->` (holistic QA + UI/UX gate verdict, if present), and `docs/specs/$1/skeleton.md` / `test-cases.md` / `ux.md`. The "왜" and AC-coverage are rich here.
- **Human-authored PR (no Guild artifacts)**: those markers/specs won't exist — **that's expected, not an error.** Derive the "왜" from the **PR description + commit messages + the diff itself**; where the intent is genuinely unclear, **ask the human** during the walkthrough ("이 변경 의도가 ~인가요?"). **Skip the AC-coverage section** (or, if the PR links an Issue with acceptance criteria, use that).
- **Always** (both cases): read the PR body, and **hotspot data** from `.claude/agents/tech-lead.md` "주의(핫스팟·함정)" to flag risky units.

The core walkthrough (Steps 3–4) is **diff-based** and works identically for both — only the depth of the pre-loaded "왜" and the presence of the AC table differ.

## Step 2 — Read the diff
```bash
gh pr diff <PR_NUM> --repo <owner>/<repo>
```
(Or `git diff <base>...<head>`.) Note every changed file + its hunks.

## Step 2.5 — Adversarial pre-scan (M3 — independent 2nd opinion)
Get a **fresh, adversarial** read of the diff before planning units — the independent/external-auditor layer (plan §4 "독립/적대 2차 의견", §18 외부 감사자). Spawn reviewer sub-agent(s) whose job is to find what's **wrong**, on **two axes**:
- **Standards axis** — does the diff violate `docs/standards/` (architecture · conventions · quality-bar) or a Guild gate rule?
- **Spec axis** — does it satisfy the Issue's AC / design intent (analyze/design output), or miss/contradict a requirement?

As the leader, spawn in one parallel message:
- **External auditor (always — fresh eyes, no Guild persona → unbiased, plan §16 C1 외부자)**: `subagent_type: general-purpose`, `model: sonnet`, `description: adversarial review #$1`, prompt:
  > You are an **independent, adversarial** code reviewer with NO prior context — fresh eyes. **⚠ READ-ONLY: you MUST NOT edit, write, create, delete, fix, or commit ANY file — you only READ and report.** Do not "fix" the defects you find; report them. Read the diff (`gh pr diff <PR> --repo <owner>/<repo>`), `docs/standards/`, and the Issue AC/design if present (`docs/specs/$1/`, the `guild:*:output` comments). Hunt for **real defects**: correctness bugs, security/exposure, missing error/null handling, **blast radius** beyond the reported scope, convention/standard violations, AC gaps, and **weakened or vacuous tests** (pass-but-verify-nothing — INV2 spirit). Be skeptical; do NOT rubber-stamp. Write `finding`/`why` in **plain, jargon-free language a non-expert reviewer can understand without follow-up** — spell out any acronym/pattern name on first use and state the concrete consequence, not just the violated rule. Return findings as JSON: `[{"severity":"BLOCKER|MAJOR|MINOR","axis":"standards|spec","file":"...","line":<n>,"finding":"<1 line, plain language>","why":"<1 line, concrete evidence>"}]` — no vague nits; every finding anchored to a concrete line + reason.
- **Conditional role lenses (leader convenes by diff surface, `_handoff.md` Section G)**: security (auth/exposure/secrets/input), performance (hot path/query), dba (schema), designer (UI a11y). Each reviews **its slice** adversarially as an **external gate** (reviewing the developer's diff, never self-review). **Each is READ-ONLY — only reads and reports findings (same JSON shape); it MUST NOT edit or fix any file.** Skip any not warranted (the common case).

Collect + dedup the findings (by file+line). They feed the walkthrough's "확인할 점" (Step 4). **Advisory, not a gate** — the human still approves (INV1); the auditor sharpens scrutiny, it doesn't block. If a `--comment` run, the deduped adversarial findings also go into the posted recap.

## Step 3 — Plan the change-units, then present the plan (and pause)
Group the diff into **logical change-units**, not just per-file:
- **Group related changes together** — a source change with its directly-related test(s); files that implement one behavior.
- **Separate the mechanical** — generated artifacts (golden images, lockfiles) as their own light unit.
- **Order by importance** — core logic change first → its tests → supporting/mechanical last.
- Keep each unit small enough to discuss in one exchange.

Present the plan and **stop**:
```
이 PR은 <M>개 파일, <N>개 논리 단위로 나눴습니다:
① <unit 1 — 한 줄>
② <unit 2 — 한 줄>
③ <unit 3 — 한 줄>
①부터 시작할까요? (또는 특정 단위부터/전체 요약부터 원하시면 말씀하세요.)
```
Wait for the human before presenting unit ①.

## Step 4 — Walkthrough loop (ONE unit per turn — the core)
For the current unit:
1. **Header**: `[단위 i/N] <제목>`.
2. **어디**: the hunk(s), each as a clickable `file:line` ref (e.g. `lib/widgets/check_box.dart:27`). Show the key changed lines briefly (not the whole file).
3. **무엇을**: what changed, concretely.
4. **왜 (③ 크래프트 전수 — A · `_learning.md`)**: the rationale — root cause → why this fix — AND **name the underlying principle** so the human learns transferably (not just "we branched the token" but "테마 토큰은 모드별 분기 필수 — WCAG 대비 원칙"). Ground-truth-anchored (a verified outcome / ⑥ fact / confirmed standard), never AI opinion.
5. **확인할 점 (D 예측-후-공개 옵션)**: for a risky unit, first **invite the human to predict** — *"이 유닛에서 뭐가 위험해 보이세요?"* — then reveal the **Step 2.5 adversarial findings that map to this unit** (by file:line, highest severity first, axis-tagged `[standards]`/`[spec]`). **Present each finding pre-translated, never raw JSON/jargon** — one plain-Korean line explaining what's wrong and why it matters, followed by an explicit action recommendation derived straight from severity:
   ```
   [standards] lib/x.dart:42 — <평이한 설명: 무엇이 왜 문제인지, 방치하면 어떻게 되는지>
   → 수정 필요: 반드시 수정 (BLOCKER)
   ```
   Mapping: `BLOCKER` → "반드시 수정", `MAJOR` → "수정 권장", `MINOR` → "선택/참고용". Add any leader scrutiny note the same way. **The human should never have to ask "쉽게 설명해 주세요" or "수정이 필요한가요?"** — that translation + recommendation is Claude's job on every reveal, not on request. The predict→compare gap is where learning happens (§8-A). Nothing found + no concern → say so and move on.
6. **Pause**: `질문이나 이견 있으세요? 없으면 '다음'이라고 하시면 ②로 갑니다.` → **STOP and wait.**

**③ Overseer learning depth (F 적응형 페이딩 — `_learning.md`)**: scale the WHY (item 4) + predict-prompt (item 5) to the human's competence trend (evolve 360 overseer scorecard). Low competence in this area → full worked explanation + predict prompt. Rising competence → **fade** to a one-line pointer (don't lecture a skilled reviewer). Absent scorecard data (early) → default to moderate. Opt-in, non-condescending, advisory (the human is the approver — INV1).

Rules for the loop:
- **One unit per turn.** Never dump all units at once — that defeats the paced pair-review.
- Handle the human's response: answer questions using the loaded rationale; if they select a region in the editor, discuss that. If they **request a change**, **record it as a change-request** (for the Step 5 recap). By default **do NOT edit the code yourself** — the human applies changes (directly, or by re-looping `/gld dev $1`). **If the human explicitly asks you to make the fix**, apply the edit directly (not just a proposal) — show what changed, let the human review/undo, then continue the walkthrough. Never edit proactively, and never during the Step 2.5 adversarial scan (that stays independently read-only).
- Advance only when the human signals (e.g. "다음") — respect their pace; they may linger or skip.

**Ground-truth capture (①, agent↔agent — `_signals.md` Section C):** if the human, during the walkthrough or at the Step 5 decision, **acts on a Step 2.5 adversarial finding** — explicitly asks Claude to fix it, records a `change_request` anchored to it, or sends the PR to request-changes because of it — append one entry (its own Bash call, best-effort — never blocks the walkthrough). The independent auditor's finding is the anchor (Section B — external cross-role review, not self-review); `role` = the lens that raised it. `--surprise` when the acted-on finding was `BLOCKER`/`MAJOR` (a confident PR reversed):
```bash
python3 <<SKILL_DIR>>/commands/atoms/capture_signal.py --kind correction --issue $1 --stage review --role <reviewer|security|performance|dba|designer> --area "<the area the finding concerns>" --summary "<the finding the human acted on, 1 line>" --evidence "<file:line + why, 1 line>" --surprise
```
**Skip** when the human merely acknowledges a finding without acting on it (agreement ≠ correction — already covered by Step 4 item 5's "say so and move on"), and skip `MINOR` findings unless the human explicitly elevates one. This is the review-stage half of the "PR-review overturn" signal `_signals.md` Section C flags — it captures a human confirming an *independent-auditor* finding as real; an unattended execute decision reversed at review (needing the auto-decision's own trail) stays the separate, still-deferred case.

## Step 5 — Recap + decision (after the last unit)
- Recap: units covered, any **open concerns** (recorded `DONE_WITH_CONCERNS` + points raised during the walk), any **change requests** the human made, and **any adversarial findings (Step 2.5) still unaddressed** — grouped by severity (BLOCKER/MAJOR first), each kept in the **same plain-language + "수정 필요: ..." recommendation format used in Step 4** (never re-surface raw JSON at this final gate). A BLOCKER-level unaddressed finding should be called out explicitly before the approve prompt (advisory — the human still decides).
- **② arch-drift follow-up (항목 2a)**: if the diff carries an open `<!-- guild:arch-drift -->` flag (left by an unattended execute run when a `confirmed` architecture.md needed a skeleton update — `implement.md`), surface it here as a follow-up note ("이 변경이 architecture.md 골격 갱신을 필요로 합니다 — 확인/갱신"). This is the review half of implement.md's "surfaced at the next `/gld review` or `/gld audit`" promise (audit dimension D is the other half).
- Decision prompt: **approve the PR** (M1 external reviewer gate), or request changes → re-loop via `/gld dev $1` or fix directly in the PR.
- If `$2 == --comment`: post the recap to the PR (temp-file pattern, `<!-- guild:review:output -->` marker) as an async record. Default = session-only.

**Outer-loop nudge (organic — `_data_sufficiency.md`)**: after the decision, compute the **cheap proxy** (Section B — `ground-truth.jsonl` **deduped by area/evidence** + ledger run count; one read each, read-only — dedup so it tracks evolve's count, not a raw line tally). **Only if Axis 1 = 충분** (≥5 anchored signals), nudge once: *"이번 PR까지 신호가 충분히 쌓였습니다 (교정 N·run M) — `/gld evolve`로 조직을 성장시킬 적기입니다."* At **없음/얕음 → stay silent** (no evolve nudge — nagging "아직 부족" every review is noise; `/gld audit`'s banner covers the accumulation question). This is **advisory** — evolve's own Phase 1.5 gate is the authority; the shared deduped count just keeps the nudge from pointing at an evolve that would clearly refuse.

## Notes
- **Works on any open PR — agent-authored or human-authored.** Pass the PR number. For human PRs the "왜" is inferred (PR description/commits/diff) or asked; the AC table is skipped. The paced walkthrough + scrutiny is identical.
- **Author-explains-to-reviewer, interactively** — the value is the paced WHY per unit + your ability to interject, not a static findings dump.
- **Assist, not replace — advisory by default, editable on explicit request.** review splits the diff, guides the walk, and **presents Claude's review opinions** (the Step 2.5 findings) as suggestions. It never modifies code **unprompted** — the adversarial scan stays strictly read-only always (to keep the 2nd opinion independent). In the walkthrough, if the human **explicitly asks for a fix**, Claude applies it directly instead of just describing it. The human approves the PR (INV1) and remains in control of what changes. Scrutiny notes ("확인할 점") help; they don't gate and they don't get auto-fixed unless asked.
- **On-demand + nudged** — `/gld dev` nudges this at completion; also standalone on any open PR.
- **Adversarial layer (M3 — Step 2.5)** — a fresh external auditor (+ conditional role lenses) pre-scans the diff on 2 axes (Standards/Spec) and feeds each unit's "확인할 점". This is the agent-based independent/adversarial 2nd opinion (plan §4/§18); it is **advisory**, the human still approves (INV1). The guided human walk remains the spine.
