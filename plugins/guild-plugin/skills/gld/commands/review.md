# REVIEW (guided pair-programming walkthrough)

**Walk the human through the change one logical unit at a time — like the author pair-driving a review.** Not a one-shot report: an **interactive, paced** walkthrough that presents ONE change-unit, explains what + why, **pauses for discussion**, then moves to the next. M1's external reviewer is the human (PR approval, INV1); this makes that review a guided conversation instead of a raw-diff slog. **As of M3**, a fresh **adversarial pre-scan** (Step 2.5 — independent external auditor on the Standards/Spec axes) sharpens each unit's scrutiny; it is advisory (the human still approves).

`$1` = Issue number (preferred) or PR number. Optional `$2 = --comment` to post a recap to the PR at the end.

> **Bash**: `<<SKILL_DIR>>/commands/atoms/_bash_rules.md`. State: `<<SKILL_DIR>>/commands/atoms/_handoff.md`.
> **Output language**: conduct the walkthrough (narration, questions, recap) in `config.language` (`_handoff.md` Section K). Machine tokens / `file:line` refs stay ASCII.

> **This is a MULTI-TURN, interactive flow.** It runs in the **main session** (it must pause and wait for the human between units — a sub-agent cannot). The command *initiates* the walkthrough and presents the plan + first unit; each subsequent turn presents the next unit after the human responds. Track the current unit index in your reasoning (like an FSM). If interrupted, re-running `/gld review $1` restarts, or the human can say "continue from unit N".

> **VSCode limit (be honest)**: Claude cannot open/navigate/highlight files in the editor. Present each unit with **clickable `file:line` references** (the human clicks to open) and invite the human to **select the region** in the editor to discuss it (Claude sees the selection). Claude narrates; the human navigates.

---

## Step 0 — Resolve the change
1. Resolve owner/repo (`_handoff.md` Section F).
2. If `$1` is an Issue → find its open PR (`gh pr list --repo <owner>/<repo> --search "Refs #$1" --state open --json number,headRefName,url`). If `$1` is a PR number, use directly. No PR → "no open PR for #$1 — run `/gld dev $1` first."

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
  > You are an **independent, adversarial** code reviewer with NO prior context — fresh eyes. Read the diff (`gh pr diff <PR> --repo <owner>/<repo>`), `docs/standards/`, and the Issue AC/design if present (`docs/specs/$1/`, the `guild:*:output` comments). Hunt for **real defects**: correctness bugs, security/exposure, missing error/null handling, **blast radius** beyond the reported scope, convention/standard violations, AC gaps, and **weakened or vacuous tests** (pass-but-verify-nothing — INV2 spirit). Be skeptical; do NOT rubber-stamp. Return findings as JSON: `[{"severity":"BLOCKER|MAJOR|MINOR","axis":"standards|spec","file":"...","line":<n>,"finding":"<1 line>","why":"<1 line, concrete evidence>"}]` — no vague nits; every finding anchored to a concrete line + reason.
- **Conditional role lenses (leader convenes by diff surface, `_handoff.md` Section G)**: security (auth/exposure/secrets/input), performance (hot path/query), dba (schema), designer (UI a11y). Each reviews **its slice** adversarially as an **external gate** (reviewing the developer's diff, never self-review). Skip any not warranted (the common case).

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
4. **왜**: the rationale — from analyze/design/PR (root cause → why this fix). This is the heart of the pair-walkthrough.
5. **확인할 점**: surface the **Step 2.5 adversarial findings that map to this unit** (by file:line) — lead with the highest severity, tagged by axis (`[standards]`/`[spec]`) — plus any leader scrutiny note (null-safety/force-unwrap, blast radius, hotspot proximity, convention/AC gaps). If the pre-scan found nothing for this unit and there's no genuine concern, say so briefly and move on. One or two lines per point, not a lecture.
6. **Pause**: `질문이나 이견 있으세요? 없으면 '다음'이라고 하시면 ②로 갑니다.` → **STOP and wait.**

Rules for the loop:
- **One unit per turn.** Never dump all units at once — that defeats the paced pair-review.
- Handle the human's response: answer questions using the loaded rationale; if they select a region in the editor, discuss that; if they request a change, note it (and, if agreed, propose an edit — shown in VSCode's native diff for accept/reject).
- Advance only when the human signals (e.g. "다음") — respect their pace; they may linger or skip.

## Step 5 — Recap + decision (after the last unit)
- Recap: units covered, any **open concerns** (recorded `DONE_WITH_CONCERNS` + points raised during the walk), any **change requests** the human made, and **any adversarial findings (Step 2.5) still unaddressed** — grouped by severity (BLOCKER/MAJOR first). A BLOCKER-level unaddressed finding should be called out explicitly before the approve prompt (advisory — the human still decides).
- Decision prompt: **approve the PR** (M1 external reviewer gate), or request changes → re-loop via `/gld dev $1` or fix directly in the PR.
- If `$2 == --comment`: post the recap to the PR (temp-file pattern, `<!-- guild:review:output -->` marker) as an async record. Default = session-only.

## Notes
- **Works on any open PR — agent-authored or human-authored.** Pass the PR number. For human PRs the "왜" is inferred (PR description/commits/diff) or asked; the AC table is skipped. The paced walkthrough + scrutiny is identical.
- **Author-explains-to-reviewer, interactively** — the value is the paced WHY per unit + your ability to interject, not a static findings dump.
- **Assist, not replace** — the human still approves the PR (INV1). Scrutiny notes ("확인할 점") help; they don't gate.
- **On-demand + nudged** — `/gld dev` nudges this at completion; also standalone on any open PR.
- **Adversarial layer (M3 — Step 2.5)** — a fresh external auditor (+ conditional role lenses) pre-scans the diff on 2 axes (Standards/Spec) and feeds each unit's "확인할 점". This is the agent-based independent/adversarial 2nd opinion (plan §4/§18); it is **advisory**, the human still approves (INV1). The guided human walk remains the spine.
