# SPRINT DAILY (read-only status — what to merge, in what order, what is stuck)

**Answer four questions in one screen: what can I merge and in which order, what is waiting for
me, what broke, and is this sprint finished?** Read-only. This is how the human stays in the
loop while `sprint run` works in the background — and it is what `/gld sprint` with no
subcommand routes to.

`$1` (optional) = focus section — `prs` | `blocked` | `failed` | `worktrees` · empty = all.

> **Bash**: `<<SKILL_DIR>>/commands/atoms/_bash_rules.md`. Stage derivation: `_handoff.md`
> Section A (**list form**). Membership · order · base: `_sprint_dag.md`. Render conventions
> reused from `monitoring.md` (actionable-first).
> **Output language**: `config.language`; counts, paths, `#N` and machine tokens stay ASCII.

---

## Process

**0. Preflight** (each its own Bash call) — read `config.json` (`language`, `sprint.*`); resolve
`{owner}/{repo}` (`_handoff.md` Section F).

**1. Find the sprint.**
```bash
gh issue list --label guild:sprint --state open --limit 20 --json number,title,body --jq '{count: length, sprints: [.[] | {number, title}], body: (if length == 1 then .[0].body else null end)}'
```
None → `OK: no active sprint` and suggest `/gld sprint plan`. Two or more → list them and ask
which; render nothing speculative.

**2. Read the container.** From the body: the goal, the member table (members + `base 의존`, and
the `구분` column — `goal` / `other` / `slot` — when the table has one),
the capacity reasoning, the stack cap. From the `<!-- guild:sprint:run -->` comment: `state`,
`heartbeat`, `host`/`pid`, per-issue retries, and — when a board is
configured — `board_fails` · `board_bugs` · `board_unknown_col` · `board_account_mismatch` ·
`board_disabled_after` · `board_last_write` · `board_reason_disabled` · `board_off_reason`.
The children are **not** read from the marker — they come from step 3's child call (S, below).

**3. Gather — four `gh` calls here plus one `git`; five `gh` in total, counting step 1** (plus
the truncation re-reads below, only when a count says so —
for the PR list, only when its 완전성 판정 fails).

⚠ **The run marker lives in a COMMENT, and step 1's `--json body` does not contain comments.**
Without this call, step 2's `state` · `heartbeat` · `host`/`pid` and all four `board_*` keys
are values nothing ever fetched — so the header line *"state: … · 하트비트 4분 전"* and the
whole board line would be invented. `retro.md` already has the right shape; `daily` was
missing it.

```bash
gh api repos/<owner>/<repo>/issues/<tracker>/comments --paginate --jq '.[] | select((.body // "") | contains("<!-- guild:sprint:run -->")) | {id, body}'
```

Take the **oldest** `<!-- guild:sprint:run -->` block — the LOWEST `id` among the objects printed.
⚠ **Stream form, not `[…] | sort_by(.id) | first`.** `--paginate --jq` runs the jq once **per
page**, so on a tracker with more than one page of comments (30+) the array form printed one
"first" per page — `{…}` then `null`, or two different blocks — and none of them was the
oldest across the whole thread. Printing every match and taking the minimum yourself is
correct for any page count (the supervisor's own reader, `marker_write`, was fixed the same way).

⚠ **This said "the last block" and that was backwards.** The stated reason was *"the supervisor
rewrites the marker by posting, so earlier copies are stale"* — it does not post, it PATCHES one
comment **in place**, and when it finds several it picks `min(id)` on purpose so history is not
orphaned. With a single marker comment last and oldest are the same, which is why nothing ever
showed; with two, every reader took the wrong one. `plan.md` and `board.md` carried the same
sentence and are corrected with it.

Absent → render `state: 없음` and **no board line at all**; do not fall back to a freshness claim, because "no marker" and "board healthy"
are the two things that must not look alike.

⚠⚠ **`--jq` runs inside `gh` — filtering on a field is not the same as receiving it.**
Measured on `dev-yakuza/one-man-company` (167 PRs, 51 open Issues):

| call | as it was | with `--jq` | |
|---|---|---|---|
| PR list (`statusCheckRollup`) | **123,617 B** | **30,624 B** | −75% |
| tracker comments | 5,276 B | 918 B | −83% |

`statusCheckRollup` is the expensive half, and **all this file renders from it is one glyph per
PR** (`✅ / ⏳ / ⛔` in the sample below). So collapse it to one token in `jq` and receive that.

⚠ **The collapse rule is deliberately asymmetric: anything not known-good is `fail`.**
`pending` wins first (a run still going must not read as a verdict), then `pass` only if **every**
check is `SUCCESS`/`NEUTRAL`/`SKIPPED`, else `fail`. ⚠ **A naive `test("FAIL|ERROR|CANCEL")`
version of this reported `TIMED_OUT` as a pass** — caught by running the expression against
fabricated rollups, not against this repo, whose 167 PRs happened to contain no such case.
`ACTION_REQUIRED`, `STALE` and any conclusion GitHub adds later fall to `fail` for the same
reason: on a daily status board, **an unknown CI state must not look green.**
⚠ `none` (no checks configured) is its own value — it is not `pass`.
⚠ **`?` and `tostring` are there so a schema surprise cannot kill the call.** Without them a
non-object entry in the array makes `jq` exit with *"Cannot index string with string"* and the
**whole PR list comes back as an error** — worse than a large payload, because the phase then has
no PRs at all. With them such an entry degrades to `pending`: not a verdict, and **not green**,
which is the property that matters here.

**In this order — members, then children, then PRs**: the PR call's filter needs both sets.

**Members** — the same call as `retro.md` Phase 1, with the same truncation rule:
```bash
gh issue list --state all --limit 200 --json number,title,labels,state,body --jq '{total: length, members: [.[] | select((.body // "") | test("Sprint: #<tracker>([^0-9]|$)")) | {number, title, state, labels: [.labels[].name]}]}'
```
`total` equal to the limit → re-read with the server-side filter `--search '"Sprint: #<tracker>" in:body'`
(same `--json` and `--jq`), as `retro.md` Phase 1 does. ⚠ The unfiltered `--limit 200` list this
replaced had no such check — a repo past 200 Issues silently dropped its older members (an epic
planned weeks ago is exactly that).

**Children** — one call for every split member at once (the same form as `plan.md` Phase 1's
child read; stream form, first line = the count, one child per line):
```bash
gh issue list --label guild:child --state all --limit 500 --json number,title,body,labels,state --jq 'length, (.[] | {number, title, state, labels: [.labels[].name], parent: ((.body // "") | (match("Parent Issue: #([0-9]+)").captures[0].string | tonumber)? // null)})'
```
**S** (the split members) = every member that is some child's `parent`, plus every member
labelled `guild:children`. The children of S are the children whose `parent` is in S. No tracker
line, no comment read. A member of S with no child found is judged as an ordinary member.
⚠ **First line == 500 → the list is truncated** (newest first, so one epic's children can be cut
at the edge): for **every** member labelled `guild:done` or `guild:children` — by label, whether
or not it is in S yet — search the server and add what it finds (substitute `<m>` literally,
also in `parent: <m>`):
```bash
gh issue list --state all --search '"Parent Issue: #<m>" in:body' --limit 200 --json number,title,body,labels,state --jq 'length, (.[] | select((.body // "") | test("Parent Issue: #<m>([^0-9]|$)")) | {number, title, state, labels: [.labels[].name], parent: <m>})'
```
(search is token-based, so the `jq` re-applies the digit boundary; `Parent Issue:` is body text,
so the search is reliable.) Nothing found → that member stays ordinary. **The call fails, or its
first line equals 200** → the children cannot be known: the sprint is **판단 불가** (step 6).

**PRs** — filtered to members **and** the children of S (`<m…>` = all of those numbers,
substituted literally in both places) and to closing references **in this repo** (`<owner>` and
`<repo>` = step 0's `{owner}/{repo}`, `_handoff.md`'s `nameWithOwner`, substituted literally);
stream form — first line = the total PR count (`length`), second line = the smallest PR number in
the window (`(map(.number) | min // 0)`), then one filtered PR per line from the third line on:
```bash
gh pr list --state all --limit 200 --json number,headRefName,baseRefName,state,mergedAt,reviewDecision,statusCheckRollup,closingIssuesReferences --jq '[<m1>,<m2>,<c1>] as $m | length, (map(.number) | min // 0), (.[] | ([.closingIssuesReferences[]? | select(.repository.owner.login == "<owner>" and .repository.name == "<repo>") | .number] | map(select(. as $n | $m | index($n)))) as $c | ((.headRefName // "") | test("(^|[^0-9])#?(<m1>|<m2>|<c1>)([^0-9]|$)")) as $b | select(($c | length) > 0 or $b) | {number, headRefName, baseRefName, state, mergedAt, reviewDecision, closes: $c, via: (if ($c | length) > 0 then "closes" else "branch" end), ci: ((.statusCheckRollup // []) as $c | if ($c | length) == 0 then "none" elif any($c[]; ((.conclusion? // .status? // .state? // "") | tostring | ascii_upcase) | (. == "" or test("QUEUED|IN_PROGRESS|PENDING|WAITING|EXPECTED|REQUESTED"))) then "pending" elif all($c[]; ((.conclusion? // .status? // .state? // "") | tostring | ascii_upcase) | test("^(SUCCESS|NEUTRAL|SKIPPED)$")) then "pass" else "fail" end)})'
```
⚠ **완전성 판정** — the same rule as `retro.md` Phase 1, which states the premise and its limits:
first line < the limit → complete. First line == the limit → **second line < the smallest number
among the members and the children of S → complete; do not re-read** (at 200 too — that saves the
re-read). Otherwise re-read with `--limit 500` and apply the same test. **The 완전성 판정 still
fails → no per-Issue fallback**: a `"Closes #<m>" in:body` search cannot find a PR linked only by
its branch, so it would turn real work into "no PR". The sprint is **판단 불가** instead (step 6).
A closing reference to **another repo's** Issue is dropped by the `select(.repository…)` above —
its number can equal a member's (measured on `word_app`: 32 such references), and the 완전성 판정's
premise holds only for same-repo references. ⚠ The old shape — every PR
unfiltered as one `{total, prs:[…]}` line — was cut at 200 in a 235-PR repo, and at 500 its
single line grew to ~40 KB, more than Read shows of one line.
```bash
git worktree list --porcelain
```

Derive each member's stage with `_handoff.md` Section A's **list form** (it already excludes
`guild:child`, `guild:needs-human`, `guild:harness` and `guild:sprint`, and returns the
additive `paused` flag separately — never sum `paused` beside the stage buckets).

Map PR → member or child by `closes`, falling back to the issue-number token in the head branch
name (`via: "branch"`, `_sprint_dag.md` Section D). ⚠ A `via: "branch"` row is a candidate to
confirm, not a fact — the same check as `retro.md` Phase 1 — and only a confirmed one joins that
Issue's PRs. ⚠ A member whose dependency shows `BLOCKED:dep-pr-ambiguous` has
**two open PRs with different branches** — render it under 의존성 차단 with both PR numbers and
say *"둘 중 하나를 닫으면 풀립니다"*; it is not a failure and needs no re-plan.
**Merge order comes from the member table's
`base 의존` chain**, not from PR creation order — a child PR takes its parent's place in it
(step 5).

**The cause of each pause** — one call per member waiting on a human (`guild:needs-human`) and per
`guild:needs-human` child of S (step 5's ▎사람 대기), each its own Bash call, no pipe or
redirection (substitute `<n>` literally):
```bash
gh api repos/<owner>/<repo>/issues/<n>/comments --paginate --jq '.[] | select((.body // "") | contains("<!-- guild:needs-human -->")) | .body | [splits("\n")] | (map(select(test("^(defect|ambiguity|env):"))) | first) // (map(select(test("^## "))) | first) // "(원인 줄 없음)"'
```
One line per `<!-- guild:needs-human -->` comment — its cause line (`defect:` / `ambiguity:` /
`env:`, `_handoff.md` Section H), else its first `## ` heading, else `(원인 줄 없음)`; the **last
line printed** is the latest pause's cause. Step 5 groups by it (measured: #555
`defect: CI 인프라(결제) …`; #562 → the heading fallback).

**3b. Squash stacks — only when 상한 근거 is `squash-sync` or `human-override`** (`_sprint_dag.md`
Section G), one more call. It fetches into `refs/remotes/` (and objects) only — no branch, PR or
working tree changes:
```bash
python3 <<SKILL_DIR>>/commands/atoms/stack_sync.py --tracker <tracker> --check
```
⚠ A line `window-incomplete <pr> <member>` is **not a member line** — the PR list it read (200,
then 1000) did not reach the smallest member. It is one warning above the PR table,
*"PR 목록이 #<member> 까지 닿지 않아 그보다 오래된 머지는 판정하지 못했습니다"*, and it takes no part in
the member annotations below or in the "No output" judgment.
Each line annotates that member's PR row: `needs-sync` → *"⚠ 하단 머지됨 — `/gld sprint sync`"*
(its actions ending in `held` → add *"동기화 후 `/gld dev <n>` · `gh pr ready <pr>`"*);
`stale` → **낡은 base** (rule below); `diverged` → *"#<dep>의 작업이 기본 브랜치에 온전히 남아 있지 않습니다 — 사람이 판단"*; `conflict` → *"동기화 충돌 — 사람이 따라잡기"*; `draft-held` → *"`/gld dev <n>` 후 `gh pr ready <pr>`"*;
`ambiguous` → under 의존성 차단 with the reason; `skipped <reason>` → that reason (`not-done`: sync after the spine finishes); `error <message>` → the message, verbatim. No output →
nothing to add. A non-zero exit → one line *"스택 동기화 상태 확인 불가 — <stderr>"*, never a guess.

**4. Failure reasons come from `failures.jsonl`, not from the console.**
`<repo>/.claude/guild/.sprint-logs/<tracker>/failures.jsonl` — one JSON object per line:
`{at, tracker, run, issue, class, detail}`. Read it with its own Bash call:
```bash
tail -50 .claude/guild/.sprint-logs/<tracker>/failures.jsonl
```
The classes the supervisor writes — **this list is the code's, verbatim**:

| class | 실패인가? |
|---|---|
| `worktree-create-failed` · `deps-install-failed` · `dag-input-failed` · `base-decision-failed` · `incomplete-mid-spine` · `child-session-failed` | **실패** — 이 이슈의 하류도 차단된다 |
| `dependency-blocked` · `base-unresolved` · `branch-ambiguous` · `account-rate-limited` | **차단** — 의존이 아직 랜딩되지 않았거나, 후보 브랜치가 둘 이상이거나, 계정 한도의 리셋이 4시간 넘게 남았다. 실패로 렌더하지 말 것 — **재실행이 큐를 이어받는다** |
| `branch-assumed` | **정보** — 실패도 차단도 아니다. 이슈 번호가 맞는 브랜치가 하나뿐이어서 그것으로 재개했다는 기록. 소유를 증명한 것은 아니므로 사람이 확인할 수 있게 남긴다 |
| `split-stalled` | **미완**(실패로 집계) — 분할 부모의 자식 오케스트레이션이 전진을 멈췄다 |

⚠ `base-decision-failed`와 `base-unresolved`는 **다른 일**이다. 앞은 base 결정 자체가 실패한
것(입력이 깨졌거나 출력을 파싱할 수 없다 — 의존에 대해 아는 것이 없으므로 하류가 추측 위에
쌓이면 안 된다), 뒤는 base 이름은 알지만 그 ref가 로컬에도 원격에도 없는 것(의존이 아직 랜딩되지
않았다). 한 이름을 쓰던 v9 초안에서는 `retro`가 실패를 차단으로 셌다.

⚠ The file is named `failures.jsonl` for continuity but it records **every exceptional event**, and
the three kinds are not interchangeable: rendering a block as a failure tells the human to
investigate something that is working as designed. `retro` counts the blocks (§10.1); `daily`
renders them under 의존성 차단, which it already derives from the DAG for the *current* state —
the log adds the count **over the whole sprint, across runs**.
⚠ **Do not scrape the supervisor's stdout for these.** It goes to the buffer of whatever
launched the run; `daily` is a later, separate session and cannot read it. That is exactly why
the classes are written to a file in the human's checkout, which survives worktree removal and
the run itself.
Per-attempt detail still lives beside it in `issue-<N>-<ts>-attempt<k>.log` (the child's
stream-json) and `deps-<N>-<ts>.log` (the dependency install). ⚠ Labels do not carry a reason
and the checkpoint deliberately holds only a few volatile fields (`state`/`retries`/`discovered` plus the four board counters when a board is configured) — so if `failures.jsonl` is
absent, say *"실패 이유 기록 없음"* rather than inferring one from a label.

**5. Render** — actionable first, static counts last.

When the member table has a `구분` column, add one line under the header:
`목표: 머지 <g_merged>/<g> · 목표 외: 머지 <o_merged>/<o>` (the slot counts with the goal). The
merge order below is unchanged — it follows `base 의존`, never `구분`. A table without the column
(a sprint planned before it existed) gets no such line.
"머지" is step 6's **merge axis**, and an epic (a member of S) is **one seat**, merged only by
step 6's epic rule. When the sprint is 판단 불가 (step 6) **and the table has the `구분`
column**, the line is `목표: 판단 불가(<이유>)` instead — a number counted from a truncated list is
not shown; a table without the column still gets no goal line at all.

⚠ **When `config.sprint.board` is set, add ONE board line.** Pick the first matching row —
this is not optional garnish, it is the only place a human learns their board is dead:

| Condition (first match wins) | Line |
|---|---|
| `board_off_reason` present | `⚠ 보드: <url> — 이 run 은 보드를 쓰지 못했습니다 (<board_off_reason>). 카드는 지난 상태 그대로입니다` |
| `board_disabled_after` present | `⚠ 보드: <url> — 연속 실패로 투영을 중단했습니다 (누적 <board_disabled_after>건)` |
| `board_unknown_col` > 0 | `⚠ 보드: <url> — config 와 어긋난 컬럼 이름 <board_unknown_col>건. 보드에서 컬럼을 개명하셨다면 config 를 맞춰 주십시오 — /gld sprint board` |
| `board_fails` > 0 | `⚠ 보드: <url> — 투영 실패 <board_fails>건 · 마지막 성공 <board_last_write>. 일부 카드가 낡았습니다. 원인은 /gld sprint board 로 확인하십시오` |
| `board_last_write` present | `보드: <url> · 마지막 투영 <board_last_write>` |
| otherwise | `보드: <url> · 투영 기록 없음` |

Then append, when present: ` · 사유 필드 기록 중단` (`board_reason_disabled` — the supervisor
gave up writing the reason field after ten consecutive failures and kept projecting columns; the
cards' columns are current but their `Needs human` values are stale) and ` · Guild 버그 <board_bugs>건` (this one is **ours**, not a scope or
rate-limit problem) and ` · 계정 불일치: <value>` (D11 — *the* explanation for a board where
everything failed).

⚠ **Freshness comes from `board_last_write`, never from `heartbeat`.** `heartbeat` is written by
`marker_write` regardless of what the board did, so *"마지막 투영 4분 전"* was a true statement
about the supervisor being alive and a **false** one about the cards. `board_last_write` is set
by the supervisor only on a projection that actually succeeded, which is the only thing that
makes that clause honest.

⚠ **`state: waiting-for-window-*` suspends the freshness clause.** `board_last_write` is frozen
for the whole wait — twelve hours is normal — so *"마지막 투영 12시간 전"* would be rendered on a
**correctly behaving** run. Say instead: *"창 밖 대기 중 — 투영은 <HH:MM>에 재개됩니다."*

⚠ **`board_fails: 0` does not mean anything was projected.** There is no success counter beyond
`board_last_write`; the dependency-blocked path deliberately writes nothing at all, so a run
where every member was blocked ends with `board_fails: 0` and no projections. That is why the
third row keys on `board_last_write` and not on the failure count being zero.

⚠ **Absent is not zero.** No `board_fails` key means the supervisor never wrote a counter — no
marker, or a run that died before its first heartbeat, or a run launched while the board was off.
The last row covers it. Treating absent as zero is how "the board was never touched" ends up
displayed as "the board is fine".

⚠ **`board_unknown_col` is NOT `board_bugs`.** A column renamed in the GitHub UI is the most
probable board fault in a months-old project and the fix is one line of config; rendering it as
*"Guild 버그"* sends the human to file a bug for something they can fix in ten seconds.

⚠ **`board_off_reason` comes first** — it means the board never came up at all, so every other
counter is 0 and would otherwise render as "fine".

⚠ **Reading these keys and rendering none of them is the bug D9 exists to prevent** — a board
where every write failed and a board where everything worked produce the same screen. That
happened; it is why this is a table.

⚠ **Add the split-parent line** for every member of S (step 3), whatever its state, with its
children indented under it — the same set step 6 evaluates. `#e` = the parent; `<n>` = its
children that are **not 머지 on step 6's merge axis**, whatever their labels. **First match wins:**
0. Parent `CLOSED` and not `guild:done` → step 6's *"사람이 닫음"* line takes precedence — never
   suggest `dev` on a closed Issue.
1. Parent **not** `guild:done`:
   - every child `guild:done` (`plan.md` Phase 1's `remaining` is 0 — `dev.md` Phase 2b's
     condition for Phase 2c) → one phrase, with no further condition:
     `통합 점검 대기 — run 이 끝난 뒤에도 남아 있으면 /gld dev #e (run 진행 중에는 run 이 이어갈 수 있으니 동시에 실행하지 마세요)`.
     The marker carries no queue, so whether that epic is still queued in a live run is not
     something this command has the data to decide — do not guess it.
   - otherwise → `#e 은 자식으로 진행 중입니다(머지 안 된 자식 <n>개)`.

   Either way, when the epic is **사람 대기** — defined once: **the parent, or one of its children
   without `guild:done`, carries `guild:needs-human`** — **단 `CLOSED` 이면서 같은 저장소 `MERGED` PR
   이 있는 자식은 제외**: step 3's PR list holds a `MERGED` row whose `closes` includes that child
   (a `via: branch` row is not evidence — `dev` judges by `closedByPullRequestsReferences`, so the
   two must agree). Such a child is not waiting on anyone — `dev` Phase 2b cleans it up to
   `guild:done` on the next run. This is the same set as `plan.md` Phase 1's `blocked_children`
   (which makes the same exclusion per child with `gh pr view`), and `retro.md`'s current 사람 대기
   lists use it (its 사람 대기 횟수 counts reaches and does not exclude). A stopped child carries
   the label itself, `dev.md` Phase 2b —
   append ` · 사람 대기 #<번호>` (the Issue that carries it). Children run one at a time, so a
   stopped epic often shows only children with no PR or already merged — that is still 사람 대기,
   and step 6 still counts it as 캐리오버.
2. Parent `guild:done` — step 6's epic order, unchanged: a child 거절 → `#e 미머지(자식 PR 거절)`,
   plus ` · 열린 자식 PR #<pr>` for each open child PR; else a child 진행 중 →
   `#e done·미머지 — 자식 PR 리뷰·머지 대기(머지 안 된 자식 <n>개)`; else a child 미착수 →
   `#e 미머지(자식 PR 없음)`; else (every child 머지) →
   `#e 은 자식 PR 로 완료됩니다 — 보드 카드는 부모에 남습니다`, plus ` — #e 를 닫으세요` while the
   parent is still OPEN (no PR closes a split parent; a human closing it is the normal path, and
   `plan` never offers a `guild:done` Issue again).

⚠ The old line keyed on the parent's label alone, so a done parent read *"자식 PR 로 완료됩니다"*
on the same screen as that child's open PR, and its `남은 자식` count (`guild:done`-based) could not
show a child that was done with its PR still open.

⚠ **A child's `guild:needs-human` goes under ▎사람 대기 too** — children are not in the list form
(step 3), so without this line nothing on the screen names it:
`#e 자식 #c needs-human 대기 — /gld resume <c> (그 뒤 남은 자식은 /gld dev #e 또는 sprint run 재실행)`
(`plan.md` Phase 5's command; `/gld resume <c>` finishes only that child). The split-parent
line's ` · 사람 대기 #c` points at it.
A child that is `CLOSED` and has a same-repo `MERGED` PR in step 3's list whose `closes` holds it
(the exclusion in step 5's 사람 대기 definition) gets, **instead of** that line:
`#e 자식 #c 는 머지됐지만 done 이 아닙니다 — 다음 run 이 정리합니다(할 일 없음)` — a `/gld resume <c>`
on a closed Issue would do nothing (qa finds the PR with `--state open` only).

**Same-cause pauses are grouped** (the cause lines from step 3): members and children whose latest
cause is `env:` with the same key share **one line**:
`#a · #b · #c — env ci-blocked: <대표 한 줄> → 원인 해결 후 각각 <그 멤버의 한 줄이 쓸 명령>` — the
grouped line uses **exactly the command each one's own line would use**: an ordinary member
`/gld dev <n>` (as `#103` below), a child `/gld resume <c>` (the child line above); both continue
from the label (`resume.md`, `dev` Phase 1), so the group never disagrees with the single lines.
Only when some member downstream is blocked as `dep-needs-human` on one of them, add
`그 뒤 막힌 #q… 는 sprint run 재실행으로` — a needs-human member is terminal in the run
(`sprint-supervisor.sh`, `run.md`, `sprint_dag.py` `TERMINAL_BLOCKING`), so a re-run does not run
it again; it only reaches what waited on it. Everything else stays one line each, as below.
(Measured: 5 of #563's 6 pauses were one cause — the PR CI jobs never started over a billing
limit — for three sprints running, rendered as five unrelated lines.)

Guild hides children from the board (D8), so without the split-parent line the parent sits in
`In review` with no PR to review and a `split-children` token a human has no way to decode.

⚠ **Derive it, do not read the card.** `daily` makes no board read at all — `board.md`'s Hard
rules enumerate the design's two reads and neither is here — so an instruction phrased as *"the
card carries `split-children`"* is one this command cannot execute. It would either invent a
third board read or silently drop the line, and the dropped line is D8's whole compensation for
hiding children.

⚠ **Say when the columns are not split by the board's own field.** When
`config.sprint.board.column_by_verified` is not `true`, append ` · 컬럼 기준 미확인 —
/gld sprint board`. A view created by `--setup` is always auto-assigned `Status`, so the human
who skipped that one click sees one undifferentiated pile and concludes the projection is
broken — while this line says it is fine.

⚠ `daily` **writes nothing to the board.** It has no way to build the supervisor's inputs and
becoming a second writer is what 03-sprint-board.md §5.1 removed; the `daily` marker stays the
one named exception to read-only (step 8).

```
Sprint #99 — 결제 흐름 안정화      (시작 3일 전 · state: rate-limited-until 14:20 · 하트비트 4분 전)

▎리뷰 대기 PR — 머지 순서대로
  1. PR #201  #101 결제 상태 머신   → develop        ✅ CI   ⛔ 변경 요청 있음
                                                    → `/gld review 201`
  2. PR #202  #102 타임아웃 재시도  → #101 브랜치     ✅ CI   ⚠ 1번 먼저
  3. PR #204  #104 실패 로그 집계   → #102 브랜치     ⏳ CI   ⚠ 2번 먼저 · 낡은 base(#201 갱신됨)

▎사람 대기 (2)
  #103  design — 영수증 재발행 범위 불명확 (2개 안 제시됨)
        → 결정 후 `/gld dev 103`.  ⚠ 지금 풀어도 이 run은 다시 집지 않습니다 — `sprint run` 재실행 필요
  #107 자식 #112 needs-human 대기 — /gld resume 112 (그 뒤 남은 자식은 /gld dev #107 또는 sprint run 재실행)

▎실패 (1)
  #106  base-unresolved — origin/develop 을 로컬에서 확인 불가
        → `git fetch origin develop:refs/remotes/origin/develop` 후 `/gld dev 106`

▎의존성 차단 (1)   #108 ← #103 (사람 대기)

▎보존된 워크트리 (1)
  issue-105  미추적 문서만 있음 (tech-writer ADR) — 알려진 갭.
             커밋하거나 버린 뒤 `git worktree remove` 하십시오

▎진행
  완료 3 / 7 · 지금 #105 (test) · 재시도 #105=1
  run 종료: 아직 (큐 2)   ·   스프린트 종료: 아직 (미결 PR 3)
```

**What each line must carry, and why:**
- **`reviewDecision`, before CI.** In a stack, a change request on the *bottom* PR is the single
  event that stops the whole chain. Showing only CI hides it.
- **Name the review command.** The whole point of the worktree isolation is that the human
  reviews **while the run is still going**, so the PR list is an invitation, not a report: put
  **`/gld review <PR 번호>`** on the merge-order line for the PR that is next (the bottom of the
  stack). Guild has a review command and this is its main entry point during a sprint; a list of
  PRs with no command attached sends the human to the GitHub UI and out of the loop that
  `reviewDecision` and 낡은 base are trying to keep them in.
- **Merge order with a "N번 먼저" marker.** A stack must be merged bottom-up; GitHub's UI does
  not enforce it. Merging out of order pulls the upper PR's commits into the lower one's diff.
- **A child PR sits in its parent's place**, not after the member PRs: at the epic member's
  position in the `base 의존` order, the same parent's child PRs in ascending child number
  (`dev` Phase 2b's execution order — measured, child PRs stack on each other). Same line shape:
  `PR #<pr>  #<c>(#<e> 자식) 제목 → base`. The **N in "N번 먼저" is the list position**, as above:
  a child PR whose base is an earlier sibling's branch → that sibling PR's position; a member
  that depends on the epic → the position of the **last of that epic's child PRs still in the
  list**, and none left → no marker. ⚠ That member's base is `DEFAULT` (`_sprint_dag.md`: a
  split-completed parent), so for it the marker is an **order recommendation, not a stack
  warning** — word it as one.
- **`완료 N/M` on the 진행 line counts labels** (`guild:done`) — what it does today; it is not
  the merge axis. Merging is the goal line's and *sprint finished*'s (step 6) job.
- **"낡은 base"** — the dep's PR head has moved since this PR was cut. Catching up is the
  **human's** job (Guild does not auto-rebase: INV3 forbids force-push), and after catching up
  the change has not been through the auditor/test/qa, so the honest advice is to re-enter with
  `/gld dev <n>`.
- **The needs-human note about re-running.** Resolving a pause does **not** make the current run
  pick it back up; the queue was built at start. Say so, or the human waits for nothing.
- **Preserved worktrees, split into two kinds.** Uncommitted **source** = real unfinished work.
  Only untracked **docs** = the known gap where `_execute_spine.md` Step 3.5b deliberately leaves a
  tech-writer's ADR uncommitted. Report the distinction; never judge it automatically and never
  auto-commit or delete (Step 3.5a forbids the blanket revert; Step 3.5b withdrew the auto-commit).
- **Other Guild worktrees — a count only.** From the same `git worktree list --porcelain` output
  (step 3 — no new call): the `.gld-<repo>-*` entries outside this sprint's container (an earlier
  sprint's, a `review` one). Any → one line under ▎보존된 워크트리,
  `다른 Guild 워크트리 <k>개 — /gld sprint retro 정리 단계가 안내합니다`; none → no line. daily never
  names or judges them (`retro.md` Phase 7 lists them).
- **Heartbeat age with `state`.** A ~115-minute rate-limit wait is normal; age alone would read
  as a dead run. ⚠ Render the `state` token as the supervisor writes it and translate for the
  human beside it — the shapes are `running` · `installing-deps` ·
  `rate-limited-until-<epoch-seconds>` · `rate-limited-remaining-<n>s` ·
  **`waiting-for-window-<HHMM>`** · `finished` · `halted:<reason>` (ASCII, `_handoff.md`
  Section K). `rate-limited-until-1790000000` becomes *"rate-limited — 예상 재개 14:20"*;
  `waiting-for-window-2200` becomes *"창 밖 대기 중 — 22:00에 재개"* (the `HHMM` in the token
  **is** the next window opening); do **not** invent a shape the supervisor never writes.
  ⚠ **`halted:<reason>`**: `interrupted` · `window-invalid` · `marker-unwritable` ·
  `container-lost` · `sigTERM` · `sigHUP` · `plan-hash-mismatch`. `halted:marker-unwritable`
  is the one whose reason may exist **only** in `.sprint-logs/<tracker>/dag/ledger.json` —
  the marker write is what failed.
- **How to stop it.** ⚠ For any live state, print the marker's `pid` with the command:
  *"중단: `kill <pid>` — 대기 중이면 최대 60초, 멤버 작업 중이면 그 멤버가 끝난 뒤에 멈춥니다.
  (`kill -9` 는 쓰지 마십시오 — 카드가 `In progress` 에 남습니다)"*. Ctrl-C cannot work: the
  supervisor is a background job of a non-interactive shell and inherits SIGINT as SIG_IGN.
  This is the **main** channel for that instruction — the supervisor's own stdout is a log this
  command cannot read.

#### `state: waiting-for-window-*` — is it sleeping, or dead?

⚠ **Only for this state.** This command does not check whether the pid is alive anywhere else,
and it deliberately renders heartbeat age harmlessly — which is right for a 115-minute rate-limit
wait. It is **wrong** for a window: SIGKILL (power loss, a drained battery, a macOS auto-update
reboot) runs no trap, so the marker freezes on `waiting-for-window-2200`, and a screen viewed at
noon is **byte-for-byte identical** whether the supervisor is asleep or died nine hours ago.

⚠ **Do not put this in step 2 or 3.** Those read `host`/`pid` for every state, so the check
would also apply to `running` and `rate-limited-*` — and then **every windowless run** gets a
wrong verdict on a host mismatch.

Reuse `run.md`'s duplicate-run table **whole** — the command and all five rows:

```bash
ps -p <pid> -o command=
```

| Observed | What to say |
|---|---|
| empty output | **죽었습니다** — `/gld sprint run` 으로 재개하십시오 |
| output contains `.gld-sprint-` | 정상 대기 중 (heartbeat age beside it) |
| some **other** process | pid 재사용 — **확인할 수 없습니다** |
| `ps` itself unavailable | **확인할 수 없습니다.** Never assume not-running |
| `host` differs | **확인할 수 없습니다** — 로컬로 검증 불가 |

⚠ **Do not collapse the last three into *"죽었습니다"*.** Following that advice starts a second
supervisor against a first one that is alive on another host — the outcome `run.md:78` forbids.

⚠ **The match string is `.gld-sprint-`, and it is NOT copied from `run.md`'s prose.** The two
copies say the same thing for the same reason but they are separate strings: what `ps` prints is
`bash .claude/guild/.gld-sprint-<tracker>.sh`, because the marker's `pid` is the supervisor
script's own `$$`. `sprint-supervisor` is the **template** filename and never appears in that
output; matching it sent a live supervisor down the "pid recycled → treat as gone" row.

#### `state: finished` — render the ledger's `completion` key

⚠ **There is no completion notification, and this is the only channel.** Phase 4 of `run.md`
only runs while the launching session is alive; a run that lasted three nights has no such
session, and the marker is a PATCH of an existing comment so GitHub sends nothing either. The
supervisor therefore writes one `completion` object into the ledger just before `state:
finished`, and this command renders it: counts, `elapsed_s` (⚠ **as h:m** — a multi-night run
makes this a large number), `cost`, `tokens`, `logs`, `run_timestamp`, and the four issue lists.

- ⚠ **The completion is a snapshot taken when the run ended.** An issue list that no longer
  matches today's labels and PRs (measured: `incomplete: #146 (split: 1 left)` after #532 reached
  `guild:done`) is rendered with ` (run 종료 시점)` after it — the step 5 lines above are the
  current state.
- ⚠ **`paused_issues` first.** A paused member (`guild:needs-human`) is the one outcome that
  **requires** a human, and `paused: 1` without a number cannot be acted on days later.
  `#e (child #c)` 는 자식이 needs-human — 부모 라벨은 `guild:children` (the supervisor paused the
  split parent because its smallest outstanding child waits on a human); act on `#c`.
- ⚠ **`kept_worktrees` is `{path, reason}`**, and the `reason` is git's own refusal
  (`locked` / `modified or untracked files` / `main working tree`) — three different actions,
  not re-derivable from a live `git status` days later. Render the reason.
- ⚠ **But re-derive the source-vs-docs judgement yourself.** *"Uncommitted **source** vs only
  untracked **docs**"* comes from each worktree's **live `git status`**, never from the ledger.
  Without that distinction `_execute_spine.md` Step 3.5b's deliberate untracked-ADR gap shows
  up as *"확인 필요"* on every single run.
- ⚠ **Known gap, inherited:** `worktree_release` only runs at `guild:done`, so a **paused**
  member's preserved worktree is not in `kept_worktrees`. The `git worktree list` pass below is
  what catches those.
- All paths in `completion` are **relative** by design (`marker_write` PATCHes the whole ledger
  into a public issue comment — INV5). Do not "helpfully" print an absolute one.

**6. Termination — two axes, reported separately.**

| Axis | Condition |
|---|---|
| **run finished** | the queue is empty — every member ended done, needs-human, failed or blocked. **Not all done.** |
| **sprint finished** | run finished **AND**, for every ordinary member and every child of S: no `OPEN` PR **AND** not 거절 (below) |

**Per Issue (a member or a child of S), two separate readings.** Its PRs are those step 3 mapped
to it by `closes`, plus `via: "branch"` rows only once confirmed — several branches included.
- **Merge axis** (the counts — the goal line here, `retro`'s metrics): any `MERGED` PR → **머지**
  (merge time = the latest `mergedAt`; a later `OPEN` PR does not undo it) · no `MERGED`, only
  `CLOSED` → **거절** · no PR → **미착수** · otherwise (only `OPEN`) → **진행 중**.
- **Finish axis** (the table above): no `OPEN` PR and not 거절. An Issue whose first PR was
  closed and a later one merged is **not** 거절 — judging PR by PR, that sprint could never finish.
- **An epic (a member of S) is one seat.** It is 머지 ⇔ the parent is `guild:done` **and** every
  child of it is 머지. Parent `guild:done` and a child 거절 → **미머지(자식 PR 거절)**; else a child
  진행 중 → **done·미머지** (the same cell as an ordinary member that is done with its PR open);
  else a child 미착수 (no PR — a `closed-not-done` child, say) → **미머지(자식 PR 없음)**. Parent
  not `guild:done` → **캐리오버**, whatever its children's state (step 5's split-parent line words
  it as 통합 점검 대기, 진행 중 or 사람이 닫음; the count stays 캐리오버). The finish axis reads the
  children themselves, never the parent.

Sprint finished → *"회고 가능 — `/gld sprint retro`"*. Otherwise say precisely what remains.
⚠ A 거절 Issue is **not** a completion: the human rejected that work. Surface its `CLOSED` PRs as
*"닫힌 PR <n>건 — 확인 후 회고하세요"* rather than letting the count read as done.
⚠ **A split member's CHILDREN count, not the member** — the parent has no PR of its own. They
come from step 3's child call (and its supplement), whatever the parent's state: a parent that
stopped at its k-th child (`guild:children` + `guild:needs-human`) still has open PRs from the
children before it, and leaving them out let *"sprint finished"* read true while `retro` closed a
sprint whose work was still in review. ⚠ The call this replaced looked only at parents that had
reached `guild:done`, over every Issue unfiltered at `--limit 200` with no truncation check.
Render the children indented under the parent (step 5's split-parent line).

⚠ **판단 불가 — the sprint, not one Issue.** When step 3's 완전성 판정 fails at 500 (the window
does not reach below the oldest member — a very old carryover member, say), or a child supplement
failed, do not decide either axis: render
`스프린트 종료: 판단 불가 — PR 목록 500건이 가장 오래된 멤버까지 닿지 않아 판정할 수 없습니다(retro 도 같은 이유로 실패합니다)`
(for a child supplement: `스프린트 종료: 판단 불가 — #<m> 의 자식을 모두 찾지 못했습니다(retro 도 같은 이유로 실패합니다)`)
and do **not** suggest `회고 가능` — `retro` stops on the same truncation, so suggesting it would
send the human into a `FAIL`.

⚠ **A member Issue the human CLOSED is not a completion either.** `run` drops it from the queue;
render it as *"사람이 닫음"* in its own line rather than letting it vanish or count as done.
- **What "the human closed" means here** — no call fetches `stateReason` or events, so it is
  judged from data already in hand: the member Issue is `CLOSED`, is **not `guild:done`**, and
  has **no `MERGED` PR mapped to it** (step 3's PR list) — the same definition as `retro.md`
  Phase 6's group 2. A done one is not this rule — it is done·미머지. ⚠ Limit: a member closed
  by a `fixes #N` commit pushed directly, with no PR, lands here too.
- **Not for an epic whose parent is `guild:done`** (a member of S): no PR closes a parent, so a
  human closing it after its children merged is the normal path — its outcome comes from the
  epic rule above only. A parent closed while **not** done is still *"사람이 닫음"* (`plan`
  reads open Issues only, so nothing takes it up again — it must show).
- A member that also has only `CLOSED` PRs (거절) gets one line, not two:
  `… · 사람이 닫음 · 닫힌 PR #<n>`.

⚠ **Do not use Issue open/closed as the completion signal.** A stacked PR merged into a
dependency branch does **not** close its Issue — GitHub's closing keywords only fire when a PR
merges into the default branch. Judge by label (`guild:done`) and PR state.

**7. Scope (`$1`).** `prs` · `blocked` · `failed` · `worktrees` render only that section, headed
*"포커스: <section>"* so the output is visibly partial. An unrecognized value → list the valid
ones and fall back to the full snapshot.

**8. One side effect.** Replace the `<!-- guild:sprint:daily -->` comment on the tracking Issue
with this snapshot, so the human can read it on GitHub without a terminal. ⚠ This is the **one
exception** to read-only, and a stronger one than `monitoring.md`'s `--html` (a gitignored local
file) because it changes a GitHub comment — state that plainly. Read → splice between the
markers → write via temp file, **with the truncation check** (`_execute_spine.md` Step 4): if the
comment body comes back as a preview, read the persisted full output; if neither is available,
**skip the update** and say so rather than writing a body that drops everything outside the
markers.

## Return

`OK: sprint #<n> — run <finished|queue N> / sprint <finished|open PRs N|undetermined>` ·
`OK: no active sprint` · `FAIL: <reason>`

---

## Hard rules

- **Read-only except the `daily` marker** (step 8), which is named as an exception — and step 3b's
  fetch into `refs/remotes/` (objects and `FETCH_HEAD` only; no branch, PR or working tree).
- **Actionable first**: change-requested PRs, needs-human, failures and stale bases come before
  any count.
- **Merge order is derived from the member table**, never guessed from PR numbers or dates.
- **Never use Issue open/closed as completion** — a stacked PR does not close its Issue.
- **Never judge a preserved worktree**; report source-vs-docs and let the human decide.
- **Never auto-catch-up a stale base** and never suggest a rebase — INV3.
- Five `gh` calls (sprint list · tracker comments · members · child discovery · PR list) plus
  one `git`; only when a count says so, the members re-read and one child search per
  `guild:done` / `guild:children` member; only when the PR list's 완전성 판정 fails at 200, the PR
  re-read at `--limit 500`; plus step 3b's one call on a
  squash-stack sprint; plus one cause call per member and child waiting on a human (사람 대기 멤버·자식마다 원인 한 호출 — step 3). A missing source renders as "없음", not an error.
