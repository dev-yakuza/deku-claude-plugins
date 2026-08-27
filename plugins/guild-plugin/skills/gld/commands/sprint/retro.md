# SPRINT RETRO (close the sprint — measure, calibrate, grow, close)

**Turn one finished sprint into the next sprint's capacity number and into Guild's own growth.**
Attended and multi-turn: this is where measurement changes configuration and where the Outer
loop runs, so every write stops for the human (INV1). Terminal: after this, the sprint is closed.

`$1` (optional) = `--dry-run` (measure and present, change nothing — no config write, no evolve,
no close).

> **Bash**: `<<SKILL_DIR>>/commands/atoms/_bash_rules.md` — simple calls; bodies via temp file +
> `--body-file`. Membership · order · base: `_sprint_dag.md`. Stage derivation: `_handoff.md`
> Section A (**list form**). Termination axes: `sprint/daily.md` step 6 — **the same two**, do not
> invent a third. Growth loop: `commands/evolve.md`.
> **Output language**: `config.language` (`_handoff.md` Section K); counts, paths, `#N` and
> machine tokens stay ASCII.

---

## Phase 0 — Preflight

Each its own Bash call.

0. **Detect the mode NOW, before anything below it** — `printenv GLD_SPRINT_RETRO_DRY` is not a
   thing; read `$1` and `printenv GLD_UNATTENDED`:
   - `$1 == --dry-run` → set **DRY** for this whole run.
   - `GLD_UNATTENDED=1` → stop after Phase 3 and return `OK: unattended — retro requires a human`.
   ⚠ **This is step 0 for the same reason `_execute_spine.md` Step 0 detects the mode first: the
   branches below depend on it.** Here those branches are *writing `config.json`*, *running an
   evolve that commits*, and *closing the Issue*. Reading this file top-to-bottom and meeting the
   `--dry-run` rule only at the end — after all three — is how a dry run stops being dry. Every
   phase from 4 on names DRY explicitly; if you reach one of them without having done step 0,
   go back and do it.
1. **Guild initialized?** `ls .claude/guild/config.json` — absent → `FAIL: Guild not initialized (run /gld init first)`. This command needs `config.language` and writes `config.sprint`.
2. **Find the sprint.**
   ```bash
   gh issue list --label guild:sprint --state open --limit 20 --json number,title,body
   ```
   - None → `OK: no open sprint`. ⚠ Suggest `/gld sprint plan`, and say that a **closed** tracker is a finished sprint — a retro is not re-runnable **once it finishes**, because Phase 6 step 3 closes the Issue and `<!-- guild:sprint:retro -->` is append-only (`_handoff.md` Section B). ⚠ A retro that died **partway** is a different case and IS re-runnable: Phase 4 replaces its own `history` entry rather than appending, and Phase 6 step 2 checks for its own comment before adding one. (v10 said "step 5", which this file has never had.)
   - Two or more → list them and ask which. Never retro one speculatively.
3. **Resolve `{owner}/{repo}`** once (`_handoff.md` Section F); hold the literal value.
4. **Is a run still in flight?** From the `<!-- guild:sprint:run -->` comment: `state` and `heartbeat`.
   - `state` is `running` / `installing-deps` / `rate-limited-*` **and** the heartbeat is under ~15 minutes old → **stop**: *"`sprint run`이 아직 진행 중입니다(하트비트 <n>분 전). 끝난 뒤 회고하세요 — 상태는 `/gld sprint daily`."* Return `FAIL: run still in flight`.
   - Same states but the heartbeat is **stale** → say so plainly (*"마지막 하트비트가 <n>분 전입니다 — run이 중단된 것으로 보입니다"*) and ask whether to retro anyway. Do not decide this alone: a stale heartbeat and a dead process look identical from here, and retro'ing a live run would close the container out from under it.
   - `finished` / `halted:*` / no marker at all → proceed.

## Phase 1 — Is the sprint actually finished?

Reuse `daily.md` step 6's **two axes verbatim** — same three `gh` calls, same derivation:

```bash
gh pr list --state all --limit 200 --json number,headRefName,baseRefName,state,mergedAt,reviewDecision,closingIssuesReferences
```
```bash
gh issue list --state all --limit 200 --json number,title,labels,state,body
```

⚠ **`--limit 200` with a client-side filter can silently miss members, and six of the nine
metrics come from that PR list.** This matters more here than anywhere else in the sprint,
because these numbers do not just get rendered — Phase 4 writes them into `config.json` and the
next `plan` reads them. **A truncated list does not produce an error or a zero; it produces a
plausible smaller number, which then becomes configuration.**

So: **count first, then decide.** Ask for the count in the same call
(`--jq 'length'` on a separate invocation, or read the array length before filtering) and compare
it with the limit:

- **Issues** — if the count equals the limit, re-read with the server-side filter
  `--search '"Sprint: #<tracker>" in:body'`, the form `_sprint_dag.md` Section A prescribes at
  this scale. Member Issues carry that back-reference, so the search is exact.
- **PRs** — ⚠ **that search does not work here and must not be attempted.** Nothing writes
  `Sprint: #<tracker>` into a PR body; a PR body carries `Closes #<N>` and the auditor block
  (`_execute_spine.md` Step 5). Searching for it returns an **empty set**, which is the worst
  possible failure for this phase: six of the nine metrics come from the PR list, and zero reads
  as *"nothing happened"*. Instead raise the limit (`--limit 500`) and, if the count still equals
  the limit, **stop**: `FAIL: could not read the sprint's PRs in full — the metrics would be
  understated and Phase 4 would write them into config.json`.

The hard rule *"Zero and unrecorded are different"* is worthless if a truncated read is treated
as a count — and here a truncated read becomes **configuration**.

| Axis | Condition |
|---|---|
| **run finished** | the queue is empty — every member ended done, needs-human, failed or blocked |
| **sprint finished** | run finished **AND** no member PR is `OPEN` **AND** no member PR is `CLOSED` unmerged **AND** the same holds for split children's PRs |

**Not finished → present what remains and ask.** A retro over open PRs measures a sprint that is
not over, and closing the tracker orphans them from the next `plan`'s carryover list. But this is
a **question, not a block** — the human may legitimately be abandoning the sprint. If they
proceed, stamp the record *"⚠ 미완 상태에서 회고함 — 미결 PR <n>건"* so the history is honest.

⚠ **Do not use Issue open/closed as the completion signal** (`daily.md`): a stacked PR merged
into a dependency branch does not close its Issue, because GitHub's closing keywords only fire
on a default-branch merge. Judge by label and PR state.

## Phase 2 — Metrics (compute; do not judge yet)

Sources, and **what each is honestly derived from**:

| 지표 | 계산 | 출처 |
|---|---|---|
| 약속 이행률 | 머지된 멤버 / 계획된 멤버 | 멤버 표 + PR `mergedAt` |
| 캐리오버 | 결말나지 않은 멤버 (done도 아니고 머지도 안 된 것) | 라벨 + PR 상태 |
| 사람 대기 횟수 | `guild:needs-human`에 도달한 멤버 수 | 라벨 |
| ↳ 그중 분할이 멈춘 것 | **분리 집계** — 원인이 다르다 | `failures.jsonl`의 `split-stalled`. ⚠ 분할 자체는 더 이상 일시정지가 아니다(§8.7) — 감독자가 이어서 재개하므로, 이 값은 *재개가 전진을 멈춘* 횟수다 |
| 감사자 루프백 | 멤버 이슈의 감사자 레코드에서 **disposition 토큰** 집계 | `<!-- guild:auditor:execute -->` 댓글 |
| 의존성 차단 횟수 | 차단으로 건너뛴 횟수 | `failures.jsonl`의 `dependency-blocked` · `base-unresolved`. ⚠ `base-decision-failed`는 **세지 말 것** — 그것은 실패다 |
| 스택 따라잡기 횟수 | base가 기본 브랜치로 폴백한 PR 수 | PR `baseRefName` ↔ 멤버 표의 기대 base |
| 리뷰 변경 요청률 | `reviewDecision == CHANGES_REQUESTED` / 멤버 PR | PR |
| 닫힌-미머지 PR | 사람이 거절한 작업 | PR `state == CLOSED` + `mergedAt == null` |

**The event log** — one call, and it spans **every run of this sprint**, not just the last:
```bash
wc -l .claude/guild/.sprint-logs/<tracker>/failures.jsonl
```
then read it in full (it is one line per event and bounded by the run's own activity; `daily`
uses `tail -50` because it only needs the recent picture, `retro` needs all of it):
```bash
cat .claude/guild/.sprint-logs/<tracker>/failures.jsonl
```
Absent → say *"이벤트 기록 없음"* for those three rows rather than reporting 0. **Zero and
unrecorded are different findings**, and only one of them is good news.

**감사자 루프백** — one call per member is acceptable here (retro is attended and runs once).
⚠ **`--paginate`, not a plain view.** That comment grows a block per attempt and per re-entry, so
it is exactly the shape that comes back as page 1 only — and a truncated read produces a
plausible small number, not an error (`_execute_spine.md` Step 4 states the same requirement for
the same comment):
```bash
gh api repos/<owner>/<repo>/issues/<n>/comments --paginate --jq '[.[] | select((.body // "") | contains("<!-- guild:auditor:execute -->"))] | .[].body'
```

Count the **disposition tokens** — `looped-back` · `fixed` · `recorded` · `dismissed` — and the
number of `### audit-record ` headings (= how many times the auditor ran).

⚠ **Do NOT count `"severity":"BLOCKER"`.** That string is the JSON the auditor returns *to the
leader*; it is not what lands on the Issue. What lands is a `### audit-record <n>` block whose
**surrounding prose is in `config.language`** (`_execute_spine.md` Step 4 says so explicitly), so
on a `ko` repo the severity word may not be `BLOCKER` at all. `_handoff.md` Section K guarantees
exactly two things here: the block headings and the four disposition tokens. Counting anything
else yields a number that is always 0 and reads as *"the auditor never blocked"*.

⚠ The comment is **cumulative across re-entries** (`_handoff.md` Section B), so `looped-back` +
`fixed` is *how often the auditor stopped the stage over the sprint*, not *defects shipped*. Say
which one you are reporting. A `dismissed` is a judgment the human should be able to see: list
those with their Issue numbers rather than folding them into a total.

**스택 따라잡기** — a member whose table row says its base is `#<dep>`'s branch but whose PR
targets the default branch means Step 5's `git ls-remote` re-verification fired: the dependency
had already landed and its branch was gone. That is the **normal, healthy** shortening of a
stack, not a defect. Report it as *"스택이 <n>회 자연 단축됨"*, and only call it a cost if the
PR body also records the fallback with the dependency still open.

⚠ **One sprint is not a trend.** For the first sprint, print the numbers under a heading that
says so — *"첫 스프린트 — 기준선입니다 (판정 아님)"* — and skip every comparative verdict.
`config.sprint.history` is empty exactly then, so this is decidable, not a judgment call.

## Phase 3 — Present metrics + retrospective, then stop

```
Sprint #99 — 결제 흐름 안정화        (13일 · run 2회 · 계획 7개)

▎결과
  약속 이행률   5/7  (71%)
  캐리오버      2개 — #103(사람 대기) · #108(#103에 막힘)
  사람 대기     2회  (그중 분할 일시정지 1회)
  감사자 BLOCKER 제기  6건 / 그중 loop-back 후 해소 6건
  의존성 차단   3회
  스택          최대 3단 · 자연 단축 2회
  리뷰 변경요청 2/5 PR (40%)
  닫힌-미머지   0건

▎계획 대비
  계획 시 판단: "7개 — 첫 스프린트, 기초 1개 + 독립 6개로 보수적"
  실제:         5개 머지. 두 개는 같은 원인(#103의 범위 불명확)으로 멈췄습니다.

▎회고 (사람이 고칠 것 / Guild가 고칠 것)
  · 사람 쪽: #103은 readiness가 partial(Constraint)인데 담았습니다 — plan이 제외를
    권고했고 override했습니다. 다음엔 그 권고를 받는 것이 이 두 개를 살립니다.
  · Guild 쪽: 리뷰 변경요청 40%는 감사자가 놓친 축이 있다는 신호입니다 → 아래 성장 루프.
```

**What the retrospective must and must not do:**
- **Separate the two owners.** A metric that reflects a human choice (readiness override, capacity
  acceptance, a change request) is not a Guild defect, and proposing an agent change for it is how
  `evolve` learns the wrong lesson. Say which is which, explicitly.
- **Anchor every claim to a number above or to a specific `#N`.** No unanchored narrative — this
  record becomes `history` and the next sprint's reasoning reads it.
- **Never propose a Guild change here.** Phase 4 is where proposals come from, adversarially
  reviewed, per-item approved. Phase 3 states observations.

**Stop and let the human respond.** They may add their own reading — record it verbatim; the
human's account of their own sprint is ground truth this command cannot derive.

## Phase 4 — Capacity recommendation (per-item approval → config)

Recommend **one number** for the next sprint, with the reasoning in one sentence:

| 관측 | 권고 방향 |
|---|---|
| 이행률 ≥ 85% · 사람 대기 ≤ 1 | +1 |
| 이행률 60~85% | 유지 |
| 이행률 < 60% · 또는 캐리오버 ≥ 절반 | −1 |
| 캐리오버 원인이 **하나의 이슈**에 몰림 | **숫자를 건드리지 않는다** — 원인은 용량이 아니라 선별이다. 그렇게 말한다 |
| `capacity`가 아직 없다(`null`/부재) | **±1을 적용할 대상이 없다.** 이번 스프린트에 **실제로 머지된 수**를 첫 값으로 삼고, 그것이 기준선임을 말한다 |

⚠ The last row matters more than the arithmetic. Capacity is the human's **PR-review
throughput** (D5), and a sprint that stalled on one unclear Issue says nothing about it.

**Then ask, per item** (INV1) — the recommendation and the history entry are two separate writes:

```json
"sprint": {
  "capacity": 7,
  "max_stack_depth": 3,
  "history": [
    { "sprint": 99, "planned": 7, "merged": 5, "carryover": 2, "needs_human": 2 }
  ]
}
```

1. Read `.claude/guild/config.json` (Read tool; parse in context).
2. Apply only the approved changes, **preserving every other key** (`config.md`'s "Set a value").
3. `history` is **keyed by `sprint`, and the write is replace-or-append, never blind append.**
   If an entry with this `sprint` number already exists, **replace it**; only otherwise append.
   ⚠ **This is what makes Phase 4 re-runnable, and it has to be.** Phase 0 says a retro is not
   re-runnable *because Phase 6 closes the Issue* — but if the run dies **between** Phase 4 and
   Phase 6 (an evolve that fails, a network error, the human stopping to think), the config is
   already written and the sprint is still open, so the human re-runs. A blind append then puts
   **two entries for one sprint** into a 10-slot history and skews every later capacity reading.
   Same for `capacity`: recompute it from the metrics, do not increment whatever is there.
4. `history` is **bounded — keep the most recent 10** entries, oldest dropped. Unbounded growth
   would make `config.json` a log, and `plan` only ever reads the recent trend.
   ⚠ Older entries may have a **different shape** (a field this version does not write, or a
   missing one). Keep them byte-intact and do not normalize them — `plan` reads the trend
   defensively. Only the entry for *this* sprint is written by this command.
5. Write the full JSON back with the Write tool (2-space indent).
   **DRY**: skip 1–5 entirely and print the JSON that *would* be written.

⚠ **Writing `config.json` trips the commit gate's own `--guard-config` guard**, which surfaces as
a confirmation prompt (`SKILL.md`). That is expected and intended, not an error — say so before
it appears, so the human does not read it as a failure.

⚠ `capacity` and `history` have **no `config` setter** (`config.md` Notes) — this command is
their only writer. Do not tell the human to run `/gld config` for them.

## Phase 5 — Growth loop: run `evolve`, with no arguments

Read `<<SKILL_DIR>>/commands/evolve.md` and execute it, **passing nothing**.

⚠ **Do not narrow evolve's signal window to this sprint.** It has no window argument, and adding
one would change its internals — out of scope. More importantly `_data_sufficiency.md` defines
Axis 1 as *"the accurate full count … the authoritative measure"* and Axis 2 as **prior evolve
runs**, which a sprint window cannot even express. The sprint's own metrics are Phase 2's job and
are **not** evolve's input.

**DRY**: do **not** read or execute evolve at all. Print *"`--dry-run`: evolve는 실행하지
않습니다 — 실제 회고에서 신호 충분성 게이트가 판정합니다"* and go to Phase 6. ⚠ This phase is the
one that **applies and commits**, so it is the phase where a dry run that is not dry does real
damage. Phase 0 step 0 claims every phase from 4 on names DRY explicitly; this is that naming.

**Pass evolve's own gate through, unchanged:**
- **Axis 1 `none`** → evolve hard-blocks and stops. Relay that verbatim to the human and continue
  to Phase 6. ⚠ This is the correct outcome for a thin repo, **not** a retro failure — but it is
  also the symptom to check first if it happens after a full sprint: §8.1b's `memory` symlink is
  what carries the run's signals out of each worktree, and without it evolve sees zero and
  declines forever. If the sprint merged work and evolve still reports zero signals, say that the
  link may be missing and point at `.claude/guild/memory/`.
- **Axis 1 `shallow`** → evolve downgrades to propose-only. Relay it; nothing applies.
- **Axis 2 `no-trend`** → evolve skips its trend-dependent outputs. Expected on a first run.
- Otherwise → evolve's normal per-item approval gate runs. **retro does not approve anything on
  the human's behalf** and does not re-ask what evolve already asked.

Record which of these happened — the return line distinguishes them.

⚠ **evolve can also fail or be refused item-by-item, and those are not in the list above.**
- evolve returns `FAIL` / errors out → relay it and **continue to Phase 6**. The sprint's own
  measurement (Phase 2–4) is done and the tracker should still be closed; a growth loop that
  failed is not a reason to leave a finished sprint open forever.
- the human rejects every proposal → that is a normal outcome, not a failure. Say so.
- ⚠ **evolve is NOT re-run on a retro re-run.** It applies changes and commits (`evolve.md`
  Phase 6), so a second pass over the same signals can double-apply. If a retro is being re-run
  (Phase 6 step 2 finds this sprint's retro comment already posted, or `history` already has this
  sprint), **skip Phase 5** and say that growth already ran for this sprint. `evolve`'s own
  ledger records its runs — cite it rather than guessing.

## Phase 6 — Carryover, record, close

**Order matters: write the record before closing.** A closed Issue with no retro comment loses
the sprint entirely.

1. **Name the carryover explicitly** — every member that did not land, with its reason and its
   current stage. The next `sprint plan` treats these as top candidates, and it finds them by
   reading this list.
   ⚠ Members carry **no** `guild:*` sprint label (`_sprint_dag.md` Section A) and their
   `Sprint: #<tracker>` back-reference is **kept**, not removed — one Issue having passed through
   two sprints is accurate history. So carryover needs no label surgery at all.
2. **Append the retro comment** — `<!-- guild:sprint:retro -->` … `<!-- /guild:sprint:retro -->`,
   temp file + `--body-file`.
   ⚠ **Appended, never replace-in-place** — the third documented exception in `_handoff.md`
   Section B. A repo's sprint history is the sequence of these comments; a replacing PATCH would
   erase the previous one.
   ⚠ **But check first whether THIS retro already left one.** A run that died between step 2 and
   step 3 leaves a comment on an open sprint, and appending a second one for the same sprint
   makes the history read as two retros. Read the tracker's comments (`--paginate`) and if a
   `<!-- guild:sprint:retro -->` comment already carries this sprint's date/metrics, **do not
   append again** — go to step 3.
   ⚠ **If the append fails, do NOT close** (`_handoff.md` Section F governs `gh` write
   failures): one retry if transient, then `FAIL: could not record the retro for #<tracker> —
   the sprint is left open`. A closed tracker with no record loses the sprint, which is the one
   outcome this ordering exists to prevent.
3. **Close the tracking Issue.**
   ```bash
   gh issue close <tracker> --repo <owner>/<repo> --reason completed
   ```
   ⚠ **`_handoff.md` Section D says "No Guild command closes an Issue deliberately."** That
   sentence is about **stage** Issues — their PR body carries `Closes #<N>`, so GitHub closes them
   on merge and INV1 keeps the human as the merger of record. A tracking Issue is not a stage
   Issue and has no PR, so nothing else can ever close it. That sentence is revised in the same
   commit as this file to name the exception; do not treat the two as contradicting.
   ⚠ **If the close fails**, the record is already safe: report
   `NEEDS_HUMAN: retro recorded for #<tracker> but closing it failed — close it by hand` rather
   than retrying in a loop. Re-running retro after this point is safe by step 2's check.
   **DRY**: skip steps 2–3 and print the carryover list and the comment that would be posted.
4. **Say what is next**: *"`/gld sprint plan`으로 다음 스프린트를 구성하세요. 캐리오버 <n>개가
   최우선 후보입니다."*

**`--dry-run`**: stop after Phase 3, then print what Phases 4–6 *would* do — the capacity number,
the history entry, and the carryover list. Write nothing, run no evolve, close nothing.

**Unattended** (`GLD_UNATTENDED=1`): do not proceed past Phase 3. Return
`OK: unattended — retro requires a human`. ⚠ Do **not** use `OK PAUSE: needs-human`: that return
obliges labelling an Issue `guild:needs-human` plus a comment (`_handoff.md` Section H), and
labelling the *tracking* Issue would put a non-stage annotation on a container that `dev`/`resume`
refuse to develop — the pause would be undiscoverable and unclearable.

## Return

`OK: sprint #<n> closed — carryover <K>` ·
`OK: sprint #<n> closed — evolve declined (thin data)` ·
`OK: sprint #<n> measured (dry-run)` ·
`OK: no open sprint` ·
`OK: unattended — retro requires a human` ·
`NEEDS_HUMAN: <one-line>` · `FAIL: <reason>`

---

## Hard rules

- **Attended only.** Config writes, an evolve apply and closing an Issue are all outward and
  hard-to-reverse (INV1).
- **Measure before judging, and judge before proposing.** Phase 2 computes, Phase 3 observes,
  Phase 4/5 propose. Never collapse them.
- **Zero and unrecorded are different.** Never report a missing log as `0`.
- **One sprint is not a trend.** No comparative verdict when `history` is empty.
- **Separate human choices from Guild defects** — the wrong attribution teaches `evolve` the
  wrong lesson.
- **evolve is called with no arguments**, and its refusal is relayed, never worked around.
- **The retro comment is appended**, never replaced — it is the sprint history.
- **Record before closing.** A closed tracker with no record loses the sprint.
- **Only the tracking Issue may be closed here** — never a member, never a child.
- All Bash per `_bash_rules.md`; every body via temp file + `--body-file`.
