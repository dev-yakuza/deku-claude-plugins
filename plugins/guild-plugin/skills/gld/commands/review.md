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
2. If `$1` is a PR number, use directly. If `$1` is an Issue → find its open PR. **A literal `"Closes #$1"` search alone is too narrow** — this command explicitly claims to "work on ANY open PR, agent-authored or human-authored" (Step 1), but a human-authored PR just as commonly uses `Fixes`/`Fixed`/`Resolves`/`Resolved`/`Close`/`Closed` (all of GitHub's recognized closing keywords, case-insensitive), or links the Issue purely through the PR sidebar's "Development" feature with no closing keyword in the body text at all — none of which a `"Closes #$1"` search would find. Search broadly instead:
   ```bash
   gh pr list --repo <owner>/<repo> --search "#$1 in:body" --state open --json number,headRefName,url,title,body
   ```
   Then, from the results, keep only PRs whose body actually contains `$1` as a closing/fixing reference (`\b(close[sd]?|fix(e[sd])?|resolve[sd]?)\s*:?\s*#$1\b`, case-insensitive) **or** where the exact search turns up nothing but the PR's title/body otherwise makes the link obvious. **If search finds nothing at all** (including the sidebar-linked case, which has no body text to search), don't silently report "no PR" — ask the human directly which PR this review is for, since the PR may exist but be linked in a way `gh pr list --search` can't see.

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
(Or `git diff <base>...<head>` — ⚠ only when this PR's head is a local branch; on a fork PR, or any head never fetched here, those refs do not resolve. Prefer the `gh pr diff` form, which always works.) Note every changed file + its hunks — and if the output came back truncated to a preview, read the persisted full-output file the tool result names before planning units, or you will split a diff you have only partly seen.

## Step 2.5 — Adversarial pre-scan (M3 — independent 2nd opinion)
Get a **fresh, adversarial** read of the diff before planning units — the independent/external-auditor layer ("독립/적대 2차 의견", 외부 감사자). Spawn reviewer sub-agent(s) whose job is to find what's **wrong**, on **two axes**:

> **Relationship to the execute-stage auditor.** `_execute_spine.md` Step 3.5a runs this same auditor *inside* `execute`, so most `BLOCKER`/`MAJOR` findings should already be fixed by the time an agent-authored PR reaches here. Where that run produced findings it did not fix, they are recorded on the **Issue** under `<!-- guild:auditor:execute -->` (the record of account) and copied into the PR body's external-auditor section (anchored by `<!-- guild:auditor:pr -->` — the heading text itself follows `config.language`, so match on the marker, not the words) — **both are absent when execute found nothing, and on a human-authored PR that never ran execute at all** (Step 1's second bullet), which is normal, not a gap.
>
> **This step still runs in full, unchanged.** It is deliberately duplicated: a scan that runs only inside `dev` cannot measure whether `dev` improved. **Never skip, shorten, or "trust" this scan because execute already ran one**, and never treat the execute record as a substitute for reading the diff fresh. Note the ordering constraint is about *use*, not about *exposure*: Step 1 already had you read the whole PR body, so you will have seen the section — the instruction is that the **Step 2.5 auditor sub-agent is spawned with no prior context and forms its findings from the diff alone**, and that you compare the two only afterwards. Do not pass the execute record into that sub-agent's prompt, and do not let it narrow what you ask it to look at.
>
> ⚠ **The "is `dev` improving?" comparison is a human judgment over time, not a metric this flow computes.** Findings here are session-only unless the run is `--comment` (Step 5 posts the recap, including unaddressed adversarial findings, under `<!-- guild:review:output -->`); nothing tallies them across PRs, and `/gld batch` does not run review at all. So the honest instruction is: **run `--comment` if you intend to judge the trend**, which leaves the counts durably on each PR for the human to compare. Do not claim, here or in a recap, that a falling count has been measured — nothing measures it.
- **Standards axis** — does the diff violate `docs/standards/` (architecture · conventions · quality-bar) or a Guild gate rule? Any real defect that breaks no written rule and no stated AC belongs here too.
- **Spec axis** — does it satisfy the Issue's AC / design intent (analyze/design output), or miss/contradict a requirement?

⚠ **The "READ-ONLY" instruction below is enforced by prompt wording only, not by a hard tool restriction** — `general-purpose` sub-agents have the same tool access as any other role this plugin spawns (including ones that legitimately edit files), so nothing mechanically stops a Step 2.5 sub-agent from calling Edit/Write if it ignored the instruction. If your Claude Code environment offers a dedicated read-only/explore-style agent type (no Edit/Write tool access at all), prefer that for this step instead of `general-purpose` — a real tool restriction is strictly stronger than an instruction. Where it isn't available, the leader should spot-check after Step 2.5 (e.g. `git status --porcelain`) that nothing changed, since the independence this step exists for depends on it never touching the diff it's reviewing.

As the leader, spawn in one parallel message:
- **External auditor (always — fresh eyes, no Guild persona → unbiased, 외부자)**: `subagent_type: general-purpose`, `model: sonnet`, `description: adversarial review #$1`, prompt:
  > You are an **independent, adversarial** code reviewer with NO prior context — fresh eyes. **⚠ READ-ONLY: you MUST NOT edit, write, create, delete, fix, or commit ANY file — you only READ and report.** Do not "fix" the defects you find; report them. Read the diff with `gh pr diff <PR> --repo <owner>/<repo>` — ⚠ **and check whether that output was truncated before you review it.** A whole-PR diff can exceed the output limit, in which case only a preview is shown and the full text is written to a file whose path the tool result gives; **read that file** and review the whole diff. If neither the full output nor that file is available, say so explicitly and do not report — a scan of a truncated diff returns perfectly well-formed JSON, so the failure would look exactly like a clean review, on the largest and riskiest PRs. (Do not substitute `git diff <base>...<head>`: this command runs on **any** open PR, including one from a fork whose head was never fetched locally, so those refs may not resolve.) Then read `docs/standards/`, and the Issue AC/design if present (`docs/specs/$1/`, the `guild:*:output` comments) — ⚠ `docs/specs/$1/` is the **intent you review against**, written by the tech-lead and tester, not the developer's output: review the code against it, but do not report findings against it as defects in this change **unless the PR's own AC is to change a spec** (an Issue whose deliverable is the spec would otherwise get an empty scan indistinguishable from a clean one — the execute-stage copy handles this with a leader-set line; here you judge it from the linked Issue's AC) — and that carve-out is **deliberately narrow**: do not extend it to documentation generally, since `docs/adr/…`, `README*` and `docs/standards/architecture.md` are frequently the change's own deliverable, and suppressing findings there would let a doc-deliverable PR pass with an empty scan indistinguishable from a clean one. (The execute-stage copy of this auditor carries the same defect list, the same anti-padding rule and the same two carve-out instructions; keep them calibrated. The intended differences are two: there the leader supplies the spec-deliverable judgment as an explicit line, since it holds the developer's output, while here you derive it from the linked Issue's AC; and the stage-consequence line below the severity/axis core differs.) Hunt for **real defects**: correctness bugs, security/exposure, missing error/null handling, **blast radius** beyond the reported scope, convention/standard violations, AC gaps, and **weakened or vacuous tests** (pass-but-verify-nothing — INV2 spirit). Be skeptical; do NOT rubber-stamp — but do NOT invent findings to fill a quota either: **returning `[]` is a correct and expected answer** for a clean diff. Write `finding`/`why` in **plain, jargon-free language a non-expert reviewer can understand without follow-up** — spell out any acronym/pattern name on first use and state the concrete consequence, not just the violated rule.
  > <!-- guild:severity-core -->
  > Severity is not a mood, and it is not about how hard the fix is — it is the
  > consequence of shipping the defect as it stands.
  > BLOCKER = shipping it causes real harm. The harms are exactly these five:
  >           (1) a security or data exposure; (2) data loss or corruption;
  >           (3) loss of availability; (4) a correctness failure a user hits on
  >           the main path; (5) the change not delivering what the Issue asked
  >           for at all. Plus one rule-based case: weakening verification the way
  >           INV2 defines it — deleting a test file, net-removing assertions, or
  >           adding skip/focus directives — is always a BLOCKER, whatever its
  >           apparent consequence. A newly added but weak assertion is not that
  >           case; grade it by consequence like anything else.
  > MAJOR   = a real defect with a bounded consequence — e.g. an edge case or one branch
  >           of a requirement left unmet, a degraded behavior, or a broken rule
  >           that has teeth — where the change still delivers its purpose and none
  >           of the six BLOCKER cases applies.
  > MINOR   = everything else you would still report: a defect or rule violation
  >           with no consequence at all — not behavior, not exposure, not data,
  >           not availability, not the acceptance criteria — and none of the
  >           BLOCKER cases.
  > axis: spec      = it misses or contradicts the Issue's AC or the design intent
  >                   in docs/specs/<N>/.
  >       standards = everything else — it violates docs/standards/, a Guild gate
  >                   rule, or simply the quality this repo ships. If it is a real
  >                   defect and it is not a spec miss, it is standards.
  > When unsure between MAJOR and MINOR, choose MINOR. When unsure whether
  > something is a BLOCKER, report it as a BLOCKER and say in `why` exactly what
  > you are unsure about, so the reader can weigh it.
  > <!-- /guild:severity-core -->
  >
  > NOT a finding — do not report this shape:
  > "this function looks like it could be split into smaller pieces"
  > Why rejected: no concrete consequence and no rule identified. Padding the list
  > with this shape costs a real loop-back.
  >
  > Your findings never gate — a human decides what to act on. They are shown to
  > that human as a plain-language recommendation keyed off the level you choose.
  >
  > Return findings as JSON: `[{"severity":"BLOCKER|MAJOR|MINOR","axis":"standards|spec","file":"...","line":<n>,"finding":"<1 line, plain language>","why":"<1 line, concrete evidence>"}]` — no vague nits; every finding anchored to a concrete line + reason.
- **Conditional role lenses (leader convenes by diff surface, using each role's participation trigger from `_handoff.md` Section G)**: security (auth/exposure/secrets/input), performance (hot path/query), dba (schema), designer (UI a11y). Here, at review time, **every convened role reviews in the same read-only, external-auditor capacity** — someone else's already-produced diff, never self-review — regardless of whether Section G's roster table formally tags that role a spine-stage "gate role" (designer, security and infra carry that tag there): Step 2.5 is `review`'s own, separate adversarial-scan mechanism, not one of the spine's stage-transition gates, so it borrows each role's *participation* trigger (who joins), not the narrower "Gate role" column (when a spine stage inserts a review check). **Each is READ-ONLY — only reads and reports findings (same JSON shape, and the same severity/axis definitions given to the external auditor above); it MUST NOT edit or fix any file.** Skip any not warranted (the common case).

⚠ **A reply that is not parseable JSON is a FAILED SCAN, never an empty one** — the truncation instruction above tells the auditor to say so in prose rather than review a partial diff, and treating that as "no findings" would read as a clean scan. Re-invoke the auditor once; if the second reply is also unusable, say so in the walkthrough and to the human, and do **not** present this PR as having passed an adversarial scan. (This step is advisory and never gates — INV1 — so it does not stop the review; it stops the *claim*.)

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
   Mapping: `BLOCKER` → "반드시 수정", `MAJOR` → "수정 권장", `MINOR` → "선택/참고용". Add any leader scrutiny note the same way. **The human should never have to ask "쉽게 설명해 주세요" or "수정이 필요한가요?"** — that translation + recommendation is Claude's job on every reveal, not on request. The predict→compare gap is where learning happens. Nothing found + no concern → say so and move on.
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
- Recap: units covered, any **open concerns** (recorded `DONE_WITH_CONCERNS` + points raised during the walk), any **change requests** the human made, **whether the Step 2.5 adversarial scan actually ran** — if it failed (an unusable reply twice, per Step 2.5), say so here in one line instead of listing zero findings, because a durable "0 findings" recap is indistinguishable from a clean scan on the very surface the trend judgment reads — and **any adversarial findings (Step 2.5) still unaddressed** — grouped by severity (BLOCKER/MAJOR first), each kept in the **same plain-language + "수정 필요: ..." recommendation format used in Step 4** (never re-surface raw JSON at this final gate). A BLOCKER-level unaddressed finding should be called out explicitly before the approve prompt (advisory — the human still decides).
- **② arch-drift follow-up**: if the diff carries an open `<!-- guild:arch-drift -->` flag (left by an unattended execute run when a `confirmed` architecture.md needed a skeleton update — `implement.md`), surface it here as a follow-up note ("이 변경이 architecture.md 골격 갱신을 필요로 합니다 — 확인/갱신"). This is the review half of implement.md's "surfaced at the next `/gld review` or `/gld audit`" promise (audit dimension D is the other half).
- Decision prompt: **approve the PR** (M1 external reviewer gate), or request changes → re-loop via `/gld dev $1` or fix directly in the PR.
- If `$2 == --comment`: post the recap to the PR (temp-file pattern, `<!-- guild:review:output -->` marker) as an async record. Default = session-only.

**Outer-loop nudge (organic — `_data_sufficiency.md`)**: after the decision, **first check the off-switch** — read `.claude/guild/config.json` (its own Bash call) and if `automation.evolve_nudge` is **`false`, stay silent entirely** (the human turned the evolve nudge off — re-enable with `/gld config --evolve-nudge=on`; do **not** read the state file, compute the proxy, or evaluate the cooldown). Only if it is **`true`** (or the key is absent → default-on) proceed:
```bash
cat .claude/guild/config.json
```
compute the **cheap proxy** (Section B — `ground-truth.jsonl` **deduped by area/evidence** + ledger run count; one read each, read-only — dedup so it tracks evolve's count, not a raw line tally). **Only if Axis 1 = `sufficient`** (≥5 anchored signals) do you *consider* nudging; at **`none`/`shallow` → stay silent** (no evolve nudge — nagging "아직 부족" every review is noise; `/gld audit`'s banner covers the accumulation question).

**Cooldown — nudge once per evolve cycle (re-fire only on growth).** The `sufficient` state persists across many reviews, so an unconditional nudge fires *every* review until the human runs evolve — naggy. Gate it on a tiny local state file `.claude/guild/memory/review-nudge-state.json` (gitignored working tier — same tier as `ground-truth.jsonl`), holding a **single repo-global** entry: `{"count": <deduped count at last nudge>, "runs": <ledger run count at last nudge>}`. ⚠ **Do not key this by PR number** — an earlier version of this doc did, to avoid two `/gld review` runs on *different* PRs racing on the same file. That race is real, but PR-keying was the wrong fix: "once per evolve cycle" is a repo-global concept (only one evolve cycle is ever in flight), while the common workflow is **one PR per issue** — so nearly every `/gld review` targets a brand-new PR number with no prior state under its own key, and the old "no prior state for this PR (first time)" condition then fired on almost every review regardless of whether a new cycle actually happened. That reproduced the exact naggy behavior this cooldown exists to prevent (observed in practice: a nudge on every single issue). Going back to a global key reintroduces the concurrent-write race — **accepted, not solved**: the read-modify-write below still has no file lock, so two `/gld review` runs finishing at nearly the same moment can still lose one of their two updates (both read the file before either writes, so the second write overwrites the first's change). Accepted as-is: the consequence is only a missed or repeated *advisory* nudge, self-heals on the next review, and adding real file locking here would be disproportionate to what's at stake. Read the whole file as its own Bash call (absent file, or unparsable → no prior nudge):
```bash
cat .claude/guild/memory/review-nudge-state.json
```
(missing/unparsable → treat as `{count: 0, runs: 0}`, i.e. no prior nudge — any leftover `"<pr>": {...}` sub-keys from the old per-PR scheme are dead data now; ignore them, they self-clear on the next write below). **Nudge iff `sufficient` AND** any of: **(a)** no prior state at all (first nudge ever in this repo), **(b)** `runs > state.runs` (an evolve ran since the last nudge → new cycle, re-arm), **(c)** `count >= state.count + 5` (a full `sufficient`-worth of *net-new* signal piled up since the last nudge). Otherwise **stay silent** (same cycle, no new material — already nudged). ⚠ **(c) uses `+5`, not a bare `count > state.count`**: when **resolved-elsewhere residuals** (signals closed by a human edit / test fix / refutation rather than an evolve apply) keep the count pinned at `sufficient`, a bare `>` re-fires the nudge on the *very first* new correction after every evolve — the naggy case the human reported. Requiring a full `sufficient`-worth of growth restores the intended "re-fire only on real accumulation." On firing, overwrite the whole file with the new global state (its own Bash call, best-effort — never blocks the recap; this also drops any dead per-PR sub-keys left over from the old scheme):
```bash
python3 -c "
import json, sys
path = '.claude/guild/memory/review-nudge-state.json'
json.dump({'count': int(sys.argv[1]), 'runs': int(sys.argv[2])}, open(path, 'w'))
" <count> <runs>
```
(After `/gld evolve`, `runs` advances so the *next review of any PR* re-arms once via (b) — not just the next review of the same PR. Consolidation *usually* drops `count`, but **resolved-elsewhere residuals** can keep it pinned at `sufficient` — the `+5` threshold in (c) prevents that floor from re-firing on every subsequent correction, and evolve's Phase 7 residual-hygiene archives those residuals so the floor itself shrinks over time.)

Nudge text: *"이번 PR까지 신호가 충분히 쌓였습니다 (교정 N·run M) — `/gld evolve`로 조직을 성장시킬 적기입니다."* This is **advisory** — evolve's own Phase 1.5 gate is the authority; the shared deduped count just keeps the nudge from pointing at an evolve that would clearly refuse.

## Notes
- **Works on any open PR — agent-authored or human-authored.** Pass the PR number. For human PRs the "왜" is inferred (PR description/commits/diff) or asked; the AC table is skipped. The paced walkthrough + scrutiny is identical.
- **Author-explains-to-reviewer, interactively** — the value is the paced WHY per unit + your ability to interject, not a static findings dump.
- **Assist, not replace — advisory by default, editable on explicit request.** review splits the diff, guides the walk, and **presents Claude's review opinions** (the Step 2.5 findings) as suggestions. It never modifies code **unprompted** — the adversarial scan stays strictly read-only always (to keep the 2nd opinion independent). In the walkthrough, if the human **explicitly asks for a fix**, Claude applies it directly instead of just describing it. The human approves the PR (INV1) and remains in control of what changes. Scrutiny notes ("확인할 점") help; they don't gate and they don't get auto-fixed unless asked.
- **On-demand + nudged** — `/gld dev` nudges this at completion; also standalone on any open PR.
- **Adversarial layer (M3 — Step 2.5)** — a fresh external auditor (+ conditional role lenses) pre-scans the diff on 2 axes (Standards/Spec) and feeds each unit's "확인할 점". This is the agent-based independent/adversarial 2nd opinion; it is **advisory**, the human still approves (INV1). The guided human walk remains the spine.
