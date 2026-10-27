# SPRINT RETRO (close the sprint — measure, calibrate, grow, close)

**Turn one finished sprint into the next sprint's capacity number and into Guild's own growth.**
Attended and multi-turn: this is where measurement changes configuration and where the Outer
loop runs, so every write stops for the human (INV1). Terminal: after this, the sprint is closed.

`$1` (optional) = `--dry-run` (measure and present, change nothing — no config write, no evolve,
no close, no cleanup) · `--cleanup <tracker>` (Phase 7 alone, for a sprint already closed;
`--dry-run` may come before or after it).

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
   thing; read **every** argument and `printenv GLD_UNATTENDED`:
   - any argument `--dry-run` → set **DRY** for this whole run (it may come before or after
     `--cleanup <tracker>`).
   - `GLD_UNATTENDED=1` → stop after Phase 3 and return `OK: unattended — retro requires a human`.
     (In **CLEANUP** mode there is no Phase 3: return the same line at once.)
   - any argument `--cleanup` → set **CLEANUP**; the argument right after it is the tracker,
     digits only (anything else → `FAIL: --cleanup needs a tracker number`). CLEANUP runs
     Phase 0 steps 1, 3 and 4, then `gh issue view <tracker> --repo <owner>/<repo> --json state,labels,body --jq '{state, sprint: ([.labels[].name] | index("guild:sprint") != null), body}'`
     — not a `guild:sprint` Issue → `FAIL: #<tracker> is not a sprint tracking Issue`; still
     `OPEN` → `FAIL: #<tracker> is still open — run /gld sprint retro` (an open sprint is cleaned
     by its retro, after the record and the close). Then Phase 1's members call, child-discovery
     call and PR call for that tracker (in that order — they define S and the PR filter), then
     **Phase 7**, skipping 2–6 entirely: nothing is measured, written or
     closed. ⚠ The truncation `FAIL`s in Phase 1 are about **metrics** and do not apply
     here: in CLEANUP, when Phase 1's 완전성 판정 fails (the PR list is not complete even at 500), look up each member **and each
     child of S** on the server instead (this is the branch-confirmation path, not a count) — `gh pr list --repo <owner>/<repo> --state all --search '"Closes #<m>" in:body' --limit 100 --json number,headRefName,baseRefName,state,mergedAt,closedAt,closingIssuesReferences`
     — and let Phase 7's confirmation decide which rows are really that Issue's. A result that
     **equals the limit** is truncated: report *"#<m>의 PR을 전부 읽지 못했습니다"* and exclude
     that member or child — never read it as "no PR", which would call a merged member carryover.
     A child supplement that fails (an error, or its first line equals 200 — Phase 1) → report *"#<m>의 자식을 모두 찾지 못했습니다"* and exclude
     that member's children (their branches are not candidates). It
     exists because Phase 7 runs after the close, so a cleanup that was declined, interrupted or
     refused by a permission prompt has no other way back.
   ⚠ **This is step 0 for the same reason `_execute_spine.md` Step 0 detects the mode first: the
   branches below depend on it.** Here those branches are *writing `config.json`*, *running an
   evolve that commits*, *closing the Issue*, and *deleting worktrees and branches*. Reading this
   file top-to-bottom and meeting the `--dry-run` rule only at the end — after all four — is how
   a dry run stops being dry. Every
   phase from 4 on names DRY explicitly; if you reach one of them without having done step 0,
   go back and do it.
1. **Guild initialized?** `ls .claude/guild/config.json` — absent → `FAIL: Guild not initialized (run /gld init first)`. This command needs `config.language` and writes `config.sprint`.
2. **Find the sprint.**
   ```bash
   gh issue list --label guild:sprint --state open --limit 20 --json number,title,body --jq '{count: length, sprints: [.[] | {number, title}], body: (if length == 1 then .[0].body else null end)}'
   ```
   ⚠ **The body comes back only when there is exactly one open sprint** — which is the normal
   case, and then nothing extra is needed. With two or more, `body` is `null` on purpose: you
   have to ask which one anyway, and pulling every candidate's member table to discard all but
   one is the same waste Phase 1 was making. Fetch the chosen tracker's body **after** the human
   picks — that call was going to happen regardless, so this adds no turn in either branch.
   - None → `OK: no open sprint`. ⚠ Suggest `/gld sprint plan` (and `--cleanup <tracker>` for
     a closed sprint whose worktrees or branches are still around), and say that a **closed** tracker is a finished sprint — a retro is not re-runnable **once it finishes**, because Phase 6 step 3 closes the Issue and `<!-- guild:sprint:retro -->` is append-only (`_handoff.md` Section B). ⚠ A retro that died **partway** is a different case and IS re-runnable: Phase 4 replaces its own `history` entry rather than appending, and Phase 6 step 2 checks for its own comment before adding one. (v10 said "step 5", which this file has never had.)
   - Two or more → list them and ask which. Never retro one speculatively.
3. **Resolve `{owner}/{repo}`** once (`_handoff.md` Section F); hold the literal value.
4. **Is a run still in flight?** From the `<!-- guild:sprint:run -->` comment: `state` and `heartbeat`.
   - `state` is `running` / `installing-deps` / `rate-limited-*` / `waiting-for-window-*` **and** the heartbeat is under ~15 minutes old → **stop**: *"`sprint run`이 아직 진행 중입니다(하트비트 <n>분 전). 끝난 뒤 회고하세요 — 상태는 `/gld sprint daily`."* Return `FAIL: run still in flight`.
     - ⚠ **`waiting-for-window-<HHMM>` is a live run**, not a stalled one, and it can stay that way for **days**. Say why and for how long: *"#<tracker> 의 감독자가 창 밖이라 대기 중입니다 — 다음 창 <HH:MM>. 중단하시려면 `kill <pid>` 후 다시 부르십시오."* Refusing here is correct; refusing without the reason looks like a bug.
   - Same states but the heartbeat is **stale** → say so plainly (*"마지막 하트비트가 <n>분 전입니다 — run이 중단된 것으로 보입니다"*) and ask whether to retro anyway. Do not decide this alone: a stale heartbeat and a dead process look identical from here, and retro'ing a live run would close the container out from under it.
   - `finished` / `halted:*` / no marker at all → proceed.

## Phase 1 — Is the sprint actually finished?

Reuse `daily.md` step 6's **two axes verbatim** — the same three calls in the same order
(members, child discovery, PR list — `daily.md` step 3; this PR call takes `closedAt` for
Phase 4 and no CI), the same per-Issue derivation:

⚠⚠ **`--jq` runs inside `gh`, so filtering on a field does NOT mean receiving it.** The calls
below decide membership from `body` / `closingIssuesReferences` and then emit **neither**.
Measured on `dev-yakuza/one-man-company` (sprint 389, 3 members):

| call | as it was | with `--jq` | |
|---|---|---|---|
| issue list | **556,413 B** | **981 B** | −99.8% |
| PR list | **53,458 B** | **569 B** | −98.9% |

Same predicate, same answer, 1/600th of the bytes — and they land in **Phase 1**, so under §1's
cost identity they were re-billed on every later turn of retro, *including the whole of Phase 5's
`evolve` run*. `_bash_rules.md` sanctions exactly this: **narrowing the query is allowed; shrinking
an answer you already received is not.**

**Members first** — the Issue list also yields the member numbers the PR filter needs:
```bash
gh issue list --state all --limit 200 --json number,title,labels,state,body --jq '{total: length, members: [.[] | select((.body // "") | test("Sprint: #<tracker>([^0-9]|$)")) | {number, title, state, labels: [.labels[].name]}]}'
```
**Then the children** — the same call as `daily.md` step 3 (stream form, first line = the count):
```bash
gh issue list --label guild:child --state all --limit 500 --json number,title,body,labels,state --jq 'length, (.[] | {number, title, state, labels: [.labels[].name], parent: ((.body // "") | (match("Parent Issue: #([0-9]+)").captures[0].string | tonumber)? // null)})'
```
**S** = every member that is some child's `parent`, plus every member labelled
`guild:children`; the children of S are those whose `parent` is in S (a member of S with no child
found is an ordinary member). First line == 500 → for every member labelled `guild:done` or
`guild:children` (by label, in S or not) run `daily.md` step 3's child search:
```bash
gh issue list --state all --search '"Parent Issue: #<m>" in:body' --limit 200 --json number,title,body,labels,state --jq 'length, (.[] | select((.body // "") | test("Parent Issue: #<m>([^0-9]|$)")) | {number, title, state, labels: [.labels[].name], parent: <m>})'
```
and add what it finds. ⚠ **That search fails or its first line equals 200 → stop**, as for a
PR list whose 완전성 판정 fails: `FAIL: could not find every child of #<m> — the metrics would be wrong and
Phase 4 would write them into config.json` (CLEANUP: Phase 0 step 0 instead).

**Then the PRs** — filtered to the members **and** the children of S (`$m` and the branch
pattern both hold all of those numbers) and to closing references **in this repo**, stream form:
first line = the total PR count (`length`), second line = the smallest PR number in the window
(`(map(.number) | min // 0)`), then one filtered PR per line from the third line on:
```bash
gh pr list --state all --limit 200 --json number,headRefName,baseRefName,state,mergedAt,closedAt,reviewDecision,closingIssuesReferences --jq '[<m1>,<m2>,<c1>] as $m | length, (map(.number) | min // 0), (.[] | ([.closingIssuesReferences[]? | select(.repository.owner.login == "<owner>" and .repository.name == "<repo>") | .number] | map(select(. as $n | $m | index($n)))) as $c | ((.headRefName // "") | test("(^|[^0-9])#?(<m1>|<m2>|<c1>)([^0-9]|$)")) as $b | select(($c | length) > 0 or $b) | {number, headRefName, baseRefName, state, mergedAt, closedAt, reviewDecision, closes: $c, via: (if ($c | length) > 0 then "closes" else "branch" end)})'
```
(substitute the tracker, the member numbers, the children's numbers and `<owner>`/`<repo>` —
`_handoff.md`'s `nameWithOwner` — literally.) ⚠ **Only this repo's closing references count.**
`closingIssuesReferences` can point at another repo's Issue (measured on `word_app`: 32 such
references, e.g. PR #351 → `dev-yakuza/word_app#1686`); comparing `.number` alone maps it to a
member whose number happens to match. The `select(.repository…)` drops it — and the 완전성 판정
below holds only for same-repo references anyway. ⚠ The PR
filter used to hold member numbers only, so a split member's children's PRs were read for the
first time in Phase 7 — after the metrics and after the close.
⚠ **The back-reference test has a digit boundary** — the same form as `_sprint_dag.md` Section A.
`contains("Sprint: #38")` also matches `Sprint: #389`, which once only skewed a metric; Phase 7
now deletes branches by this membership, so a sibling sprint's members must not leak in.

⚠ **The count is not decoration — it is the truncation check below, and it now comes free**:
`total` in the members call, the first line of the child and PR calls. (The PR call's second line
— the window's smallest PR number — is the other half of its 완전성 판정.) The
previous instruction told you to get the count *"on a separate invocation"*; that call is gone.
⚠⚠ **Match on `closingIssuesReferences` OR the branch name — not on the reference alone.**
Measured on `dev-yakuza/one-man-company`: **70 of 200 PRs (35%) carry no closing reference at
all**, and several of them are member work — e.g. `#398 fix/153-assignment-header-semantics`,
MERGED, for member #153. A reference-only filter found **3** of that sprint's member PRs; adding
the branch test found **4**. The missing one reads as *"#153 never merged"*, 약속 이행률 drops,
and **Phase 4 writes that number into `config.json`** — the exact failure this phase spends a
paragraph warning about, arriving through the filter instead of through the limit.

⚠ **`// ""` on `headRefName` is not decoration either** — a null there makes `jq` exit with
*"null cannot be matched"* and the **whole PR list returns an error**, which reads as a sprint
with no PRs. Measured: that is exactly what the unguarded form does.

⚠ **`via` says which signal matched, and it is not decoration.** `closes` is authoritative;
`branch` is a heuristic and can over-match (a branch that merely *mentions* another Issue's
number). The digit-boundary test stops `153` matching `1537`, but it cannot stop
`feat/200-refs-153-followup`. So: **treat `via: "branch"` rows as candidates to confirm, not as
facts** — check the PR actually belongs to that member (or child) before counting it, and say so if you
drop one; only a confirmed row joins that Issue's PRs. ⚠ And a member with **no** row at all is still possible: cross-check `members` against
the PR lines and name it rather than reporting it as not-merged.

⚠ **`--limit 200` with a client-side filter can silently miss members, and six of the nine
metrics come from that PR list.** This matters more here than anywhere else in the sprint,
because these numbers do not just get rendered — Phase 4 writes them into `config.json` and the
next `plan` reads them. **A truncated list does not produce an error or a zero; it produces a
plausible smaller number, which then becomes configuration.**

So: **count first, then decide.** ~~Ask for the count in the same call (`--jq 'length'` on a
separate invocation…)~~ — the `--jq` forms above already return the count (`total`, or the
first line). Compare it with the limit (for the PRs, together with the second line — the
완전성 판정):

⚠ **This is live, not hypothetical.** Measured on `dev-yakuza/one-man-company`: the issue list
returns **exactly 200** — `total == limit`, i.e. the read *is* truncated and the fallback below
**must** fire. Under the old shape that check cost an extra call, which is precisely the kind of
step that gets skipped.

- **Issues** — if the count equals the limit, re-read with the server-side filter
  `--search '"Sprint: #<tracker>" in:body'`, the form `_sprint_dag.md` Section A prescribes at
  this scale. Member Issues carry that back-reference, so the search is exact.
- **PRs** — ⚠ **that search does not work here and must not be attempted.** Nothing writes
  `Sprint: #<tracker>` into a PR body; a PR body carries `Closes #<N>` and the auditor block
  (`_execute_spine.md` Step 5). Searching for it returns an **empty set**, which is the worst
  possible failure for this phase: six of the nine metrics come from the PR list, and zero reads
  as *"nothing happened"*. Instead apply the **완전성 판정** (below) — first line < the limit →
  complete; first line == the limit and **second line < the smallest number among the members
  and the children of S → complete, do not re-read** (at 200 too); otherwise re-read with
  `--limit 500` and apply the same test. The 완전성 판정 still fails → **stop**: `FAIL: could not read the sprint's PRs in full — the metrics would be
  understated and Phase 4 would write them into config.json`. ⚠ **No per-Issue fallback on this
  path**: a `"Closes #<m>" in:body` search misses every PR linked only by its branch (measured:
  71 such PRs, member work among them), so it would turn merged work into "no PR" — a plausible
  smaller number again. A repo past 500 PRs **can** be measured now: it fails only when the
  완전성 판정 fails at 500; `daily` says so in advance (`스프린트 종료: 판단 불가`).

  **완전성 판정 — why a full window can still be complete.** GitHub numbers a repo's Issues and
  PRs from **one shared counter** (a fork's PR too). A PR that closes a **same-repo** Issue #n, or
  carries n in its branch, is created after #n, so its number is greater than n (measured: 0
  inversions on `word_app` and `one-man-company`). `gh pr list` with no `--search` / `--label`
  returns PRs in creation order, newest first (createdAt DESC) = number order, descending
  (cli/cli `pkg/cmd/pr/shared/lister.go`: `orderBy: CREATED_AT DESC`). So when the window's
  smallest PR number is below the smallest target Issue, every PR that can map to a target is
  inside the window. The premise holds **only for same-repo references** — hence the
  `select(.repository…)` in the PR call. Its limits: it covers PRs Guild created after their
  Issue — a PR whose body was edited later, or that was linked through the Development sidebar to
  a later Issue, and an Issue transferred from another repo (it gets a new number) are exceptions
  (measured: 0). The real floor is the smallest **member** number (a child is created after its
  parent, at the split), so a very old carryover member (say #50) leaves even the 500 window
  incomplete — `FAIL` as before. Measured: `word_app` sprint #1708, smallest member #1097 (a
  carryover), 200-window minimum #916 → complete at 200; `one-man-company` #563, smallest member
  #349, 200-window minimum #104 → complete.

The hard rule *"Zero and unrecorded are different"* is worthless if a truncated read is treated
as a count — and here a truncated read becomes **configuration**.

| Axis | Condition |
|---|---|
| **run finished** | the queue is empty — every member ended done, needs-human, failed or blocked |
| **sprint finished** | run finished **AND**, for every ordinary member and every child of S: no `OPEN` PR **AND** not 거절 (`daily.md` step 6 — no `MERGED` PR, only `CLOSED`) |

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
| 약속 이행률 | 머지된 멤버 / 계획된 멤버 | 멤버 표 + PR `mergedAt` — 머지 축(`daily.md` step 6). 에픽은 한 자리, 자식이 모두 머지돼야 머지 |
| 캐리오버 | 결말나지 않은 멤버 (done도 아니고 머지도 안 된 것) | 라벨 + PR 상태. 에픽은 부모가 done 이 아니면 캐리오버(자식 상태 무관) |
| 사람 대기 횟수 | `guild:needs-human`에 도달한 멤버 수 | 라벨. 에픽은 부모 또는 done 이 아닌 자식 중 하나라도 `guild:needs-human` 이면 1(`daily.md` step 5 의 **사람 대기** 정의). ⚠ 도달 수이므로 그 정의의 제외(`CLOSED` + 같은 저장소 `MERGED` PR 자식)는 여기 적용하지 않는다 — 사람이 머지한 것도 개입이다. 제외는 아래 현재 대기 목록에만 |
| ↳ 그중 분할이 멈춘 것 | **분리 집계** — 원인이 다르다 | `failures.jsonl`의 `split-stalled`. ⚠ 분할 자체는 더 이상 일시정지가 아니다(§8.7) — 감독자가 이어서 재개하므로, 이 값은 *재개가 전진을 멈춘* 횟수다. 단 가장 작은 대기 자식이 needs-human 이면 PAUSED — 근거는 completion 의 `#e (child #c)`(라벨은 `guild:children` 그대로) |
| 감사자 루프백 | 멤버 이슈(분할 멤버는 자식 이슈)의 감사자 레코드에서 **disposition 토큰** 집계 | 멤버 이슈(분할 멤버는 자식 이슈)의 `<!-- guild:auditor:execute -->` 댓글 |
| 의존성 차단 횟수 | 차단으로 건너뛴 횟수 | `failures.jsonl`의 `dependency-blocked` · `base-unresolved`. ⚠ `base-decision-failed`는 **세지 말 것** — 그것은 실패다 |
| 스택 따라잡기 횟수 | base가 기본 브랜치로 폴백한 PR 수 | PR `baseRefName` ↔ 멤버 표의 기대 base |
| 리뷰 변경 요청률 | `reviewDecision == CHANGES_REQUESTED` / 멤버 PR | PR |
| 닫힌-미머지 PR | 사람이 거절한 작업 | PR `state == CLOSED` + `mergedAt == null` — **자식 PR 도 같은 범위로 센다**(멤버 PR 만이 아님) |
| 목표 달성 | `구분 = goal` 과 `slot` 멤버가 **모두** 머지됐는가(예/아니오) + 머지된 / 계획된 (슬롯은 목표 쪽에 센다 — `daily` 와 같은 기준) | 멤버 표의 `구분` 열 + PR `mergedAt`. 열이 없는 옛 트래커 → "목표 구분 없음" |
| 목표 외 | 머지된 other / 계획된 other | 같은 출처 |

리뷰 변경 요청률과 스택 따라잡기만 **멤버 PR 만** 센다 — 자식 PR 은 넣지 않는다. 감사자 루프백은 이 목록에
넣지 않는다 — PR 이 아니라 Issue 의 레코드이고, 분할 멤버는 자식 이슈를 읽는다(아래 **감사자 루프백**).

**An epic (a member of S) is one seat** in 이행률 · 캐리오버 · 목표 달성 · 목표 외, with
`daily.md` step 6's epic rule deciding it — so `history`'s `planned` stays the seat count (row ③'s
`capacity = planned`, the first-value row and `plan`'s largest-past comparison all count seats).
The `history` schema and the recommendation table do not change. Phase 3 gives each epic one line
with its outcome and `자식 머지 <x>/<y>` (its children merged / its children — counts of
children, not of PRs), e.g. `#146 에픽 — done·미머지 · 자식 머지 2/3`. ⚠ Without this an epic, which has no PR of its
own, counted as unmerged and rows ④/⑥ cut `capacity` for work that had landed.

**The refactor slot's outcome** — not a tenth metric (the slot is already counted in the nine as
a member), but the one member whose fate the next `plan` reads back. Take it from the tracker
body's **리팩토링 슬롯** line (`plan.md` Phase 6), the slot member's PR, already in hand, and
one read of the slot Issue — `gh issue view <slot> --json body,state,closedAt` (the members
query keeps no body). `state`/`closedAt` decide the *Issue closed, no PR* row below; the body's
**Files** section is Phase 4's `paths` — read it here so an unattended retro, which stops after
Phase 3, still has it:

| tracker line | slot PR | outcome token |
|---|---|---|
| `#<n> (existing)` · `#<n> (drafted)` | merged | `merged` |
| `#<n> (existing)` · `#<n> (drafted)` | `CLOSED` unmerged | `refused` |
| `#<n> (existing)` · `#<n> (drafted)` | none, **slot Issue closed** | `refused` — the human rejected it before any PR; `closed_at` is the Issue's |
| `#<n> (existing)` · `#<n> (drafted)` | open / none, Issue open | `carryover` |
| `skip (<token>)` — `disabled` · `no-candidate` · `not-ready` · `capacity` · `stack-cap` · `human-declined` · `epic-overlap` · `ad-hoc` | — | `skip:<token>` |
| line absent (a tracker planned before the slot existed) | — | **no outcome** — omit the field; do not invent `skip` |

⚠ **`refused` is the signal, `skip` is not.** A human closing the slot's PR says the slot picked
the wrong refactor (or, for a safety-net-only slot, the wrong coverage); a `skip` says only that nothing qualified or the human chose features this
time. Phase 3 names a `refused` slot by number; a run of `skip:no-candidate` is not a defect, and neither is `skip:epic-overlap` (the slot
yielded to an epic member that touches the same files — `plan.md` Phase 2).

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

**감사자 루프백** — one call per member or per child of S is acceptable here (retro is attended
and runs once). The calls grow with the number of children — the same per-Issue shape as before.
⚠ **`--paginate`, not a plain view.** That comment grows a block per attempt and per re-entry, so
it is exactly the shape that comes back as page 1 only — and a truncated read produces a
plausible small number, not an error (`_execute_spine.md` Step 4 states the same requirement for
the same comment):
⚠⚠ **Count in `jq`, do not pull the bodies back to count them by eye.** Only these are
used here — the `### audit-record ` heading count, four disposition tokens and the clean-scan /
no-scan lines (`findings: none` / `scan: none`) — and that comment
**grows a block per attempt and per re-entry**, so the body is the one thing in this command that
scales with how badly the sprint went. Measured on `dev-yakuza/one-man-company`:

| member | body as it was | counted in `jq` |
|---|---|---|
| #137 (22 loop-backs) | **39,843 B** | **71 B** |
| #153 | 15,877 B | 67 B |
| #388 | 7,456 B | 67 B |

```bash
gh api repos/<owner>/<repo>/issues/<n>/comments --paginate --jq '. as $all | [$all[] | select((.body // "") | contains("<!-- guild:auditor:execute -->")) | .body] | join("\n") as $b | {records: ([$b | match("### audit-record ";"g")] | length), looped_back: ([$b | match("looped-back";"g")] | length), fixed: ([$b | match("\\bfixed\\b";"g")] | length), recorded: ([$b | match("\\brecorded\\b";"g")] | length), dismissed: ([$b | match("\\bdismissed\\b";"g")] | length), clean: ([$b | match("findings: none";"g")] | length), no_scan: ([$b | match("scan: none";"g")] | length), violation: ([$all[] | select((.body // "") | contains("<!-- guild:auditor-violation -->"))] | length)}'
```

⚠ **One object per PAGE — add them up.** `gh api --paginate --jq` runs the `jq` once per page of
comments (30 per page by default), so an Issue with more comments than that returns **one object
per page**, each counting only its own page — and `violation` counts a different comment from
the audit record, so the two can land in different objects. **Sum every field across all the
objects the call printed**; reading only the first one turns a long Issue into `records: 0`,
the plausible-small-number failure above. (Merging pages inside `jq` would need `--slurp` or a
pipe into a second `jq`, which `gh` and `_bash_rules.md` respectively rule out; adding a handful of
integers by eye does not.)

⚠ **Which Issues — an epic is read through its children.** Look up every member **except a
member of S whose children were found**, and every child of S instead (a member of S with no
child found is an ordinary member — Phase 1 — and is looked up as one). A parent never runs
execute, so its own record is always `records: 0` — measured: #146 and #483 reported *"기록 없음"*
while their children held 18 records, 4 of them looped-back (#532).
- **Numbers are summed, verdicts are not.** Add `records` · `looped_back` · `fixed` · … over the
  children into the epic's row, `#e 에픽(자식 합산)`, but **judge each child on its own**: records 0
  → "기록 없음", `clean == records`, `no_scan == records`, `violation`, `dismissed` — and a child
  that is none of these is listed with its counts (not called "mixed": that word below means a
  record spanning the 0.85.2 upgrade) — every
  verdict and listing below carries the **child's** number. Shape (numbers illustrative):
  `#146 에픽(자식 합산) records 11 · looped-back 4 · 기록 없음 #<c>` — so that *"Zero and
  unrecorded are different"* is not buried in a sum.
- A child that is **미착수** on the merge axis (no PR) is written apart as `미착수 #<c>` and left
  out of the "기록 없음" verdict (its numbers, if any, still go into the epic's sum) — its missing record says nothing about the auditor.
- The record is cumulative, so a child finished in an **earlier** sprint still adds its records
  here — the same property an ordinary carryover member's record has.

⚠ **`records: 0` is "no record", not "clean" — report the two separately.** From plugin 0.85.2 a
clean scan writes its own block (`findings: none`) and an attempt that never reached the scan
writes `scan: none` (`_execute_spine.md` Step 4). So: `clean == records` → every scan was clean;
`no_scan == records` → the auditor **never scanned** this member, which is not clean either; and
**no block at all** → no attempt reached the record write: the auditor did not run, 3.5a stopped
first, *or* the member's execute ran on an older plugin, which wrote nothing for a clean scan.
`violation ≥ 1` (same call — no extra request) names one cause for certain: the auditor broke its
read-only contract and was stopped; say so. Other 3.5a stops leave nothing countable on an
attended run, and the member's `guild:needs-human` label (already in the members query) is only
a weak hint — stagnation and other pauses set it too — so do not attribute it to the auditor. Nothing on the Issue records which plugin version wrote it,
so do not guess between those two: report such a member as *"기록 없음 — 0.85.2 이전 실행이면
클린과 구분 불가"*. Folding `records: 0` into a "0 findings" total is the zero-vs-unrecorded error
the hard rules forbid, and it is the one this record shape exists to remove: one repo's retros
reported "no record" for 2–5 members a sprint without being able to say whether those were clean.
⚠ **The counts are exact only for attempts run on 0.85.2 or later.** The record is cumulative
across re-entries, so one Issue can hold older attempts too — those wrote no clean block and wrote
the no-scan marker as free prose — and then `records`, `clean` and `no_scan` all undercount. For a
member whose execute spans the upgrade, do not read `clean == records` / `no_scan == records` as
complete; say the record is mixed.
⚠ `scan: none` and `findings: none` both contain `: none`, but the two `match` patterns cannot
collide: neither literal is a substring of the other.

⚠ **Word boundaries (`\b`) on the three that are ordinary words.** A bare substring count also
matches `prefixed`, `unrecorded`, … On this corpus both forms agreed (17 = 17, 31 = 31), so this
is prevention, not a fix — but it is free, and a silently inflated `fixed` reads as *"the auditor
kept finding things and they kept getting fixed"*, which is a flattering error.
⚠ `looped-back` is hyphenated and cannot collide, so it needs no boundary.
⚠ **`dismissed` still has to be listed with its Issue numbers** (below). The call is per member or
per child of S, so that Issue's number is already in hand — pair it with the count; do not fold
it into a total.

⚠ **Do NOT count `"severity":"BLOCKER"`.** That string is the JSON the auditor returns *to the
leader*; it is not what lands on the Issue. What lands is a `### audit-record <n>` block whose
**surrounding prose is in `config.language`** (`_execute_spine.md` Step 4 says so explicitly), so
on a `ko` repo the severity word may not be `BLOCKER` at all. `_handoff.md` Section K guarantees
exactly these here: the block headings, the four disposition tokens and the `findings: none` /
`scan: none` lines. Counting anything
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
  리팩토링 슬롯 #140 — merged (src/payment/state.ts · #101·#102의 기반)
  목표 달성     아니오 — 목표 4/5 (#103 캐리오버) · 목표 외 1/2

▎계획 대비
  계획 시 판단: "7개 — 첫 스프린트, 기초 1개 + 독립 6개로 보수적"
  실제:         5개 머지. 두 개는 같은 원인(#103의 범위 불명확)으로 멈췄습니다.

▎회고 (사람이 고칠 것 / Guild가 고칠 것)
  · 사람 쪽: #103은 계획 중 결정(Constraint)으로 담았지만, 그 답이 실제로 막힌 지점과
    달랐습니다. 다음엔 그 결정을 먼저 Issue 에서 다듬는 것이 이 두 개를 살립니다.
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

**First, the plan's own record of how full the sprint was** — the tracking Issue's plan block
carries `- capacity:`, `- shortfall:` and, on the ad-hoc path, `- adhoc: true` (`plan.md` Phase 6
template). Apply the **first** row that matches, top to bottom; the table after it only runs
when none does:

| 순서 | 관측 | 권고 |
|---|---|---|
| ① | `adhoc: true` | **권고 없음** — 사람이 고른 번호 묶음의 크기는 용량 신호가 아니다. 그렇게 말한다 |
| ② | 캐리오버 원인이 **하나의 이슈**에 몰림 | **숫자를 건드리지 않는다** (아래 표의 같은 행) |
| ③ | `shortfall: human-cut` | **`capacity = planned`** — 사람이 Phase 5 에서 "크기 N" 으로 이번 크기를 직접 정했다. 다음 plan 이 같은 숫자로 다시 채워 또 줄이게 만들지 않는다 |
| ④ | 이행률 < 60% · 또는 캐리오버 ≥ 절반 | −1 (아래 표의 같은 행) |
| ⑤ | `shortfall: supply` · `shortfall: depth` | **유지 — +1 은 하지 않는다.** 용량보다 적게 계획했으니 "다 해냈다" 는 더 큰 용량의 근거가 아니다(채울 후보가 없었거나 스택이 막았다). ⚠ 이 행이 없던 때는 3/3 이 +1 을 낳아, 공급과 무관하게 capacity 가 계속 올랐다 |
| ⑥ | `shortfall: none` · `n/a` · 줄이 없는 옛 트래커 | 아래 표 |

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
    { "sprint": 99, "planned": 7, "merged": 5, "carryover": 2, "needs_human": 2,
      "capacity": 7, "shortfall": "none",
      "refactor": { "issue": 140, "outcome": "merged", "kind": "refactor",
                    "paths": ["src/payment/state.ts"],
                    "merged_at": "2026-09-30T04:12:00Z", "closed_at": null } }
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
   missing one). Keep them byte-intact and do not normalize them — `plan` reads only
   `planned` (and skips `adhoc` entries) to show the largest past size beside the capacity. Only the entry for *this* sprint is written by this command.
4a. **`capacity` · `shortfall` · `adhoc`** — copied from the plan block's machine lines:
   `capacity` the integer (omit the key when the line says `n/a` or is absent), `shortfall` the
   token as written (omit when absent), `adhoc: true` only when the line is there. `plan` shows
   the largest past `planned` beside `C` and leaves `adhoc` entries out of that comparison.
4b. **`refactor`** — the slot outcome above, plus:
   - `kind` — `"safety-net-only"` when the slot Issue's body (read in Phase 2) carries
     `<!-- guild:safety-net-only -->`, else `"refactor"` (a refactor that laid a net first is
     still a refactor). The next `plan` exempts a merged `safety-net-only` entry from the
     same-paths exclusion — it covered those paths so a refactor could follow. `skip:*` → omit.
   - `paths` — from the slot Issue's **Files** section, which every drafted slot has (read in
     Phase 2 — see the slot outcome above); ⚠ not the
     **Why** line, which names the evidence hotspot, not what the refactor reshapes). An
     `existing` slot written by a human or by `audit` may have no Files: then take the
     source-dir files the slot's PR changed (`gh pr view <pr> --json files`). Record the paths
     the refactor reshaped, not tests or generated files.
   - `merged_at` — the slot PR's `mergedAt`, already in the PR list; `null` unless `merged`.
   - `closed_at` — the slot PR's `closedAt`, in the same PR list, or the slot Issue's
     `closedAt` when it was closed with no PR; `null` unless `refused`.
   - `carryover` → `paths` as above, both dates `null`. `skip:*` → `"issue": null`,
     `"paths": []`, both dates `null`.
   ⚠ Always write **both** date keys, `null` where they do not apply. The next `plan`'s
   tech-lead checks PAST SLOTS against them — whether `fix:` commits kept landing on `paths`
   after `merged_at` (merged) or `closed_at` (refused) — and it treats an **absent** key as
   *"recorded before this field existed"*, not as `null` (`plan.md` "Refactor slot"). Omit the key entirely when the
   outcome is *no outcome*.
5. Write the full JSON back with the Write tool (2-space indent).
   **DRY**: skip 1–5 entirely and print the JSON that *would* be written.

⚠ **Writing `config.json` trips the commit gate's own `--guard-config` guard**, which surfaces as
a confirmation prompt (`_invariants.md` INV3 — the gate's control files are guarded by an `ask`, not a block). That is expected and intended, not an error — say so before
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
  ledger records its runs — cite it (`python3 <<SKILL_DIR>>/commands/atoms/ledger.py status`, or `where <n>` and a ranged Read — never the whole file) rather than guessing.

## Phase 6 — Carryover, record, close

**Order matters: write the record before closing.** A closed Issue with no retro comment loses
the sprint entirely.

⚠ **Disclose the board's freeze — one line, when `config.sprint.board` is set.** `retro` writes
**nothing** to the board (03-sprint-board.md §7.4, and the Hard rules below repeat it), but this
is the moment the design's largest accepted cost becomes permanent: closing the tracker means
nothing will ever move a card again. `/gld sprint sync` moves a merged member's card to `Done`
(`sync.md` step 5), but it only finds an **open** sprint — after this close, every `In review`
card stays `In review` after the human merges its PR tomorrow morning, and every `Blocked` card
keeps a reason that may already be resolved. Say so rather than letting the human discover it:

```
보드: <url> — 이 시점 이후 카드는 갱신되지 않습니다. 머지하신 뒤에도 In review 에 남고,
      정리는 GitHub UI 에서 하십시오 (`/gld sprint sync` 는 열린 스프린트만 다룹니다).
      다음부터는 retro 전에 `/gld sprint sync` 를 부르시면 머지된 카드가 Done 으로 갑니다.
      다음 `sprint plan` 이 새 카드를 올립니다.
```

This is a **disclosure, not a projection** — no `gh project` call, no card touched.

1. **Name every member that did not land, in the group whose advice fits it** — with its reason
   and its current stage. Every unmerged member (merge axis, `daily.md` step 6; an epic is one
   seat) falls in **exactly one** group:
   1. **캐리오버 — 다음 plan 이 이어받음**: an `OPEN` Issue, not `guild:done`. The next
      `sprint plan` treats these as top candidates (except one still carrying `guild:needs-human`
      — for an epic, `daily.md` step 5's **사람 대기** definition — which its fill does not take
      on its own: the human resolves it or adds it in Phase 5), and it finds them by reading this
      list. ⚠ Except an epic (parent not done) whose children are **all** `guild:done` → group 1b.
   1b. **`통합 점검 대기 — /gld dev #e (다음 plan 후보 아님)`** — `plan` leaves a k = 0 epic out of
      its candidates (`plan.md` Phase 1); the same split as case 1 of `daily.md` step 5's
      split-parent line.
   2. **사람이 닫음 — 다음 plan 대상 아님**: `CLOSED` and not `guild:done` (`plan` reads open
      Issues only) — the same definition as `daily.md` step 6's *"사람이 닫음"*.
   3. **done·미머지 — 열린 PR 리뷰·머지 필요**: `guild:done` with an `OPEN` PR. An epic:
      `#e — 열린 자식 PR #<pr>(#<c>)`, plus `· 거절 #<c>` when a child is also 거절; with no 거절
      child, also `— 자식 PR 이 모두 머지되면 #e 를 닫으세요` (no PR closes a split parent; a 거절
      child needs the human's call first, so that case gets no close line).
   4. **done·미머지 — PR 거절/없음(사람이 판단)**: `guild:done` with **no open PR** (for an epic,
      no open child PR) — only rejected PRs, or none; an epic's `미머지(자식 PR 거절)` and
      `미머지(자식 PR 없음)` land here when no child PR is open.

   (Not a group — a member that landed: an epic counted 머지 whose parent Issue is still `OPEN`
   gets one line `#e — 자식이 모두 머지됨, #e 를 닫으세요`, since retro closing the tracker ends
   `daily`, the only other place that says it.)

   The carryover **metric** (Phase 2) is unchanged by this grouping: it is groups 1 + 1b + 2 (an
   epic whose parent is not done is 캐리오버 whatever its children's state), so Phase 3's
   `캐리오버 <n>개`, `history` and the Return line keep that number. Put no note or equation in
   `history`.
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
   `NEEDS_HUMAN: retro recorded for #<tracker> but closing it failed — re-run /gld sprint retro` rather
   than retrying in a loop. Re-running retro after this point is safe by step 2's check.
   **DRY**: skip steps 2–3 and print the carryover list and the comment that would be posted.
4. **Go to Phase 7** — only when step 3 closed the tracker (or DRY skipped it). If the close
   failed, return the `NEEDS_HUMAN` above and **skip Phase 7**: the sprint is still open, so the
   re-run that closes it reaches Phase 7 then. That is why the message says *re-run*, not
   *close it by hand* — a tracker closed by hand is a finished sprint to Phase 0 step 2, and only
   `--cleanup <tracker>` reaches this phase after that.

## Phase 7 — Cleanup (worktrees, branches and run files the sprint left behind)

Guild creates one branch per member and no other step ever deletes one (`_execute_spine.md`
Step 0 (a)'s resume probe names the cost: a long-lived repo accumulates them until the branch list
truncates). The supervisor removes a member's worktree only at `guild:done` and only when it is
clean (`sprint-supervisor.sh` `worktree_release`), so a paused, dirty or locked one survives the
run — and a worktree from this sprint that still holds a carryover member's branch is refused
mid-run by the next sprint's `worktree_acquire` (*"the branch is held by another worktree"*;
`run.md` Phase 1 step 6 can only warn about it). This phase clears what the sprint no longer
needs. It runs **after** the tracker is closed on purpose: a cleanup failure must never be the
reason a finished sprint stays open. Each command its own Bash call (`_bash_rules.md`).

⚠ **Scope is this sprint and nothing else.** Only (a) worktrees inside this sprint's container,
(b) the head branches of **confirmed** member and split-child PRs (step 1 says what confirms
one), and (c) this tracker's run files. **Never** find branches by name pattern: the name a branch
got came from the repo's `branch_naming` convention, not from Guild's prefix (`_execute_spine.md`
Step 0 (a) forbids the glob for the same reason), so a pattern both misses ours and catches the
human's.

**1. Inventory — read-only.**
- **Worktrees.** `git worktree list --porcelain`. The first entry is the main checkout; its
  basename is `<repo>`. The container is whichever directory is named exactly
  `.gld-<repo>-sprint-<tracker>` and is the **parent** of a listed worktree — find it by that
  name, not by computing a path: it sits beside the checkout or, when that was not writable,
  under the temp dir (`run.md` Phase 3 `--container`, `stack_sync.py` `container_dir`), and on
  macOS git prints the temp dir as `/private/var/…` while `$TMPDIR` says `/var/…`. The
  candidates are the entries under it: `issue-<N>` (member), `supervisor` (detached), `sync-<N>` (a `sprint sync`
  that died mid-run). Note `locked` and `prunable` on each — a `prunable` entry's directory is
  already gone, so it is not removed or inspected, only covered by the prune in step 3.
- `git branch --show-current` (never a candidate) and `gh repo view <owner>/<repo> --json
  defaultBranchRef --jq .defaultBranchRef.name` (never a candidate). ⚠ `gh repo view` takes the
  repo **positionally** — it has no `--repo` flag, and the call fails with `unknown flag`.
- **Split children.** Reuse Phase 1's S and its children (the child call and, when it was
  truncated, its supplement) and their PRs — already in Phase 1's PR list, whose filter holds
  the children's numbers. No run-marker read and no server re-query here: Phase 1's supplement
  already does what this step used to. In CLEANUP when Phase 1's 완전성 판정 fails, the children's PRs
  come from Phase 0 step 0's per-Issue lookup, with its truncation rule.
- **Confirm each PR before its branch becomes a candidate** — Phase 1 itself calls a
  `via: "branch"` row *"a candidate to confirm, not a fact"*, and a cleanup that deletes is the
  last place to skip that. One call per PR:
  `gh pr view <pr> --repo <owner>/<repo> --json headRefName,headRefOid,isCrossRepository,state,mergedAt,closingIssuesReferences,body --jq '{headRefName, headRefOid, isCrossRepository, state, mergedAt, closes: ([.closingIssuesReferences[] | select(.repository.owner.login == "<owner>" and .repository.name == "<repo>") | .number] + [(.body // "") | scan("(?i)\\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?) #([0-9]+)") | .[0] | tonumber] | unique)}'`.
  `closes` unions GitHub's link with the body's keywords on purpose: GitHub links a closing
  keyword only for a PR based on the default branch, so a stacked member PR has an **empty**
  `closingIssuesReferences` while its body still says `Closes #<N>` (`_execute_spine.md` Step 5
  writes it into every PR). The branch is a candidate only when **all** hold:
  - `isCrossRepository` is `false` — a fork's branch name says nothing about ours, and can
    equal `main`;
  - `closes` is exactly **one** number, and it is a sprint member or child — a PR closing several
    Issues (a `develop → main` release PR), a non-member, or nothing at all is not member work;
  - the branch name carries that number as a token — Phase 1's branch test,
    `(^|[^0-9])#?<N>([^0-9]|$)` — because the spine names every branch it cuts after its Issue
    (`_execute_spine.md` Step 0 (c)). `develop` or `main` with a `Closes #12` body fails this;
  - the name is not a release or version line — `release/…` or `v<digits>…` — which can carry
    the number by coincidence (`release/12` for #12), by analogy with the spine's empty-log drop
    (`_execute_spine.md` Step 0 (a)). `hotfix/<N>-…` and `support/<N>-…` are **not** excluded:
    they are real Issue-branch conventions there, and the tests above already stop a long-lived
    line;
  - the name is neither the default branch nor the current branch;
  - `gh pr list --repo <owner>/<repo> --state all --base <headRefName> --limit 200 --json number,state --jq 'map({number, state})'`
    names **no PR outside the confirmed set** (`develop` and `release/*` are the base of other
    people's work) **and no `OPEN` PR at all**;
  - `gh pr list --repo <owner>/<repo> --state all --head <headRefName> --limit 200 --json number,state --jq 'map({number, state})'`
    — every PR **headed** by the branch — names no PR outside the confirmed set either. A second
    PR from the same head (`feat/x → main` after `feat/x → develop` merged) is the human's, and
    deleting its head would end it. A merged member that is still the base of an open
    member PR is kept whole — local and remote — because what GitHub does to a PR whose base
    branch is deleted depends on how it was deleted, and either way the stack under review
    changes underneath the human.
  Every PR that fails a test is listed as excluded, with the test it failed.
- **Group by branch, not by PR.** A branch can head several PRs (a closed attempt and a reopened
  one). Its row is decided by **every** PR the `--head` call returned, confirmed or not: any `OPEN` → carryover; else any `MERGED` → merged,
  with that PR's `headRefOid` — and if two `MERGED` PRs on one branch disagree on `headRefOid`,
  the branch is kept and reported; else closed-unmerged.
- For each candidate branch: `git rev-parse --verify --quiet refs/heads/<branch>` (local tip, or
  nothing) and `git ls-remote origin refs/heads/<branch>` — the full ref, not `--heads <name>`,
  and even then take only the line whose ref is **exactly** `refs/heads/<branch>`: ls-remote
  matches patterns from the tail, so `x/refs/heads/<branch>` would come back too.
- **Run files**: `ls -A .claude/guild/` — **`-A`**: all three are dotfiles, and a plain `ls`
  hides them, so the inventory would report nothing to clean. The candidates are
  `.gld-sprint-<tracker>.sh`, `.board`, `.window`. A clean run removed them itself (`sprint-supervisor.sh` cleanup); after any
  other run they stay (`run.md` Hard rules).
  For each, `git ls-files .claude/guild/<file>` — a **tracked** one (an older repo whose
  `git add .` committed it before `.claude/guild/.gitignore` existed, `init.md`) is excluded and
  reported: deleting it would be a change to the human's tree. ⚠ `.sprint-logs/<tracker>/` is
  **never** a candidate — it is the evidence this retro just measured.

**2. Classify and present — then stop for the human (INV1).**

| row | worktree | local branch | remote branch |
|---|---|---|---|
| merged (any PR `MERGED`, none `OPEN`) | remove (if clean) | delete **iff tip == `headRefOid`** | delete **iff tip == `headRefOid`** |
| carryover (a PR `OPEN`, or no PR) | remove (if clean) | **keep** | **keep** |
| closed-unmerged | remove (if clean) | **keep — report only** | **keep — report only** |
| split parent (a member of S — no PR of its own) | remove (if clean) | — | — |
| `supervisor`, `sync-<N>` | remove (if clean) | — (detached) | — |
| run files (untracked only) | delete | — | — |

- A carryover member's **branch** is kept because the next sprint resumes on it —
  `worktree_acquire` re-attaches an existing branch (*"resumed worktree … on <branch>"*), and
  `_execute_spine.md` Step 0 (a) lists **local** branches only, so a deleted local branch makes it
  cut a second branch and open a duplicate PR. Its **worktree** is removed for the reason above.
- A closed-unmerged branch is work the human rejected and the only copy outside the PR. This
  phase never deletes it; it lists the branch so the human can delete it themselves.
- A tip that differs from `headRefOid` is **kept and reported** with both SHAs. It may be ahead
  (commits after the merge) or behind (a suggestion committed on GitHub); either way it is not
  the commit GitHub merged, and "probably fine" is not a deletion criterion.

Show one table — worktree path (relative to the container), branch, PR, row, action — plus the
exclusions and their reasons, and ask. The human may approve all, approve by row numbers, or
decline; **nothing is removed without that answer.** An unanswered or ambiguous reply is a decline.
⚠ `git branch -D` and `git push origin --delete` are in the template's `permissions.ask`
(`settings.json.tmpl`), and `rm`, `rmdir` and `hostname` are in no allow list, so each raises a
prompt — expected, not an error; say so first. ⚠ That is true only once the repo's
`.claude/settings.json` has those `ask` entries (`init` writes them, `/gld update` adds them to an
older repo): Read its `permissions.ask` first, and if `Bash(git branch -D:*)` or
`Bash(git push origin --delete:*)` is missing, say the deletes will **not** prompt and suggest
`/gld update` — the table answer is then the only gate. Use exactly these spellings: another form
of the same delete (`git push -d origin <branch>`, `git push origin :<branch>`, `git -C <dir>
branch -D`) slips past the `ask` entry that is the harness's half of INV1.

**3. Apply, in this order** (a branch held by a worktree cannot be deleted, so worktrees first):
0. **Re-check the run** — both signals, each its own call. Re-read the `<!-- guild:sprint:run -->`
   marker as Phase 0 step 4 does — the **same live states** (`running` / `installing-deps` /
   `rate-limited-*` / `waiting-for-window-*`) with a fresh heartbeat; `finished` stamps a fresh
   heartbeat too and is not live — **and** probe its `pid` the way `run.md` Phase 1 does, when
   `hostname` prints the marker's `host`: `ps -p <pid> -o command=`. A live state with a fresh
   heartbeat, or `ps` output containing `.gld-sprint-` → remove **nothing** and say so. Another
   host → no pid to probe here; the state rule alone decides.
   ⚠ **This re-check is never skipped**, not even when Phase 0 already accepted a stale
   heartbeat — that acceptance is exactly the case it exists for. ⚠ The heartbeat alone is not
   enough: Phase 0 may have proceeded over a **stale** one on the human's word, and re-reading it
   finds the same stale value — while a live supervisor, whose every `git -C` call needs the
   `supervisor` worktree, may still be behind it.
1. **Worktrees** (not `prunable` ones). `git worktree remove <path>` — **never `--force`**. git's
   refusal is the safety mechanism (`worktree_release` relies on it the same way): a `dirty` or
   `locked` one is refused and preserved. For each refusal run `git -C <path> status --short` and
   report whether what is left is source or only untracked docs (`daily.md` makes the same
   distinction — an execute-stage ADR is left untracked by design), plus the command the human
   can run themselves. Then `rmdir <container>` — it fails harmlessly while anything is left.
   ⚠ **`git worktree prune` only when every `prunable` entry is inside the container.** prune is
   repo-global and would drop the registration of one of the human's worktrees that is merely on
   an unmounted volume (`sprint-supervisor.sh` `prune_safe`). If any prunable entry is outside it,
   skip prune and say so.
2. **Local branches** — merged rows only, and only after re-running item 3's `--head` and
   `--base` calls with `--state open` for the same branch and finding **no open PR** (a branch
   that has one keeps its local copy too). ⚠ A remote ref that is **absent** (GitHub deleted it on
   merge — the normal case with `deleteBranchOnMerge`) or that moved does **not** block the
   local delete; the local tip test below decides. Then re-read the tip right then (`git
   rev-parse --verify --quiet refs/heads/<branch>`) and finding it **exactly equal** to
   `headRefOid`: `git branch -D <branch>`.
   ⚠ **Not `git branch -d`, and not as a first try.** Every Guild branch has an upstream (the
   spine pushes with `git push -u`, `_execute_spine.md` Step 5), and `-d` then judges against the
   upstream instead of HEAD: a branch whose tip is in its upstream is deleted with only a warning,
   whether or not it equals what GitHub merged. That sidesteps the tip check — the one thing that
   makes this deletion safe. With the tip exactly equal, the commits are the ones GitHub merged
   and stay reachable from the PR (`refs/pull/<pr>/head`), so nothing is lost (INV3).
3. **Remote branches** — merged rows only. Right before each delete, re-read the remote ref
   (`git ls-remote origin refs/heads/<branch>`, the exact-ref line only) — **not** the value step
   1 read before the human answered, which may be hours old — and re-run step 1's `--head` and
   `--base` calls with `--state open`: an open PR headed by **or based on** the branch appeared
   meanwhile → keep. Only when the
   ref is still there and **exactly equal** to `headRefOid`: `git push origin --delete <branch>`. A ref that moved means
   someone pushed after the merge, and a plain delete has no lease, so it would drop those
   commits; keep it and report both SHAs. Never `--force`. This is an outward write, which is
   why step 2 asked for it.
4. **Run files** — the untracked ones step 1 found, and only those: `rm
   .claude/guild/.gld-sprint-<tracker>.window` (likewise `.sh`, `.board`), one call each. Never
   `rm -r`, and never anything under `.sprint-logs/`.

A failed, declined or interrupted item is reported with its reason and the command to finish it
by hand. The retro itself cannot be re-run once the tracker is closed (Phase 0 step 2), so for
anything left the report says *"남은 정리는 `/gld sprint retro --cleanup <tracker>`로 다시 할 수
있습니다"* — that mode runs this phase alone (Phase 0 step 0).

**DRY**: run 1, print 2's table with a *"`--dry-run`: 아무것도 삭제하지 않습니다"* line, and skip 3
entirely — delete nothing.

**Then say what is next**: *"`/gld sprint plan`으로 다음 스프린트를 구성하세요.
캐리오버 <n>개(다음 plan 대상 — 사람 대기 <m>개 제외)가 최우선 후보입니다."* (n = 0 → *"다음 plan 이 이어받을
캐리오버는 없습니다."*; m > 0 → add *"(사람 대기 <m>개는 직접 처리)"*; group 3 non-empty → add
*"리뷰·머지 대기 PR <k>건이 남아 있습니다(위 목록)."* — `k` = the open PRs in group 3, child PRs
included) — `n` = Phase 6 step 1's group 1 minus its
사람 대기 members, `m` = those (an epic's by `daily.md` step 5's **사람 대기** definition). It is not
Phase 3's `캐리오버 <n>개` or the Return line's `carryover <K>` — those are the metric (groups 1 + 1b
+ 2); "다음 plan 대상" is what tells the two numbers apart.

**`--dry-run`**: stop after Phase 3, then print what Phases 4–7 *would* do — the capacity number,
the history entry, the carryover list, and the cleanup table. Write nothing, run no evolve, close
nothing, delete nothing.

**Unattended** (`GLD_UNATTENDED=1`): do not proceed past Phase 3. Return
`OK: unattended — retro requires a human`. ⚠ Do **not** use `OK PAUSE: needs-human`: that return
obliges labelling an Issue `guild:needs-human` plus a comment (`_handoff.md` Section H), and
labelling the *tracking* Issue would put a non-stage annotation on a container that `dev`/`resume`
refuse to develop — the pause would be undiscoverable and unclearable.

## Return

`OK: sprint #<n> closed — carryover <K>` ·
`OK: sprint #<n> closed — evolve declined (thin data)` ·
`OK: sprint #<n> measured (dry-run)` ·
`OK: sprint #<n> cleanup — <W> worktrees, <B> branches` (CLEANUP mode) ·
`OK: sprint #<n> cleanup listed (dry-run)` (CLEANUP + DRY) ·
`OK: sprint #<n> cleanup declined` (CLEANUP, the human said no) ·
`OK: no open sprint` ·
`OK: unattended — retro requires a human` ·
`NEEDS_HUMAN: <one-line>` · `FAIL: <reason>`

Both `closed` lines end with Phase 7's tally — `· cleanup <W> worktrees, <B> branches`, plus
`(kept <k>)` when anything was refused or excluded, or `· cleanup declined` when the human said no.

---

## Hard rules

- **Attended only.** Config writes, an evolve apply, closing an Issue and deleting worktrees or
  branches are all outward or hard-to-reverse (INV1).
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
- **Cleanup touches only this sprint** — worktrees inside its container, the head branches of
  confirmed member and child PRs, and this tracker's run files. Never a name-pattern search, never
  the default or current branch, never a fork's branch, never a branch that is the base of a
  non-member PR or of any open PR, never the head of a PR outside the confirmed set.
- **Cleanup never forces and never guesses.** No `--force` on any worktree or push; no
  `git branch -d` (it trusts the upstream); `branch -D` and a remote delete only for a `MERGED`
  PR whose tip equals `headRefOid`; carryover and closed-unmerged branches are kept.
- All Bash per `_bash_rules.md`; every body via temp file + `--body-file`.
