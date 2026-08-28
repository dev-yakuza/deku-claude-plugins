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
gh issue list --label guild:sprint --state open --limit 20 --json number,title,body
```
None → `OK: no active sprint` and suggest `/gld sprint plan`. Two or more → list them and ask
which; render nothing speculative.

**2. Read the container.** From the body: the goal, the member table (members + `base 의존`),
the capacity reasoning, the stack cap. From the `<!-- guild:sprint:run -->` comment: `state`,
`heartbeat`, `host`/`pid`, per-issue retries, discovered children, and — when a board is
configured — `board_fails` · `board_bugs` · `board_unknown_col` · `board_account_mismatch` ·
`board_disabled_after` · `board_last_write` · `board_reason_disabled` · `board_off_reason`.

**3. Gather — three `gh` calls here plus one `git`; four `gh` in total, counting step 1.**

⚠ **The run marker lives in a COMMENT, and step 1's `--json body` does not contain comments.**
Without this call, step 2's `state` · `heartbeat` · `host`/`pid` and all four `board_*` keys
are values nothing ever fetched — so the header line *"state: … · 하트비트 4분 전"* and the
whole board line would be invented. `retro.md` already has the right shape; `daily` was
missing it.

```bash
gh api repos/<owner>/<repo>/issues/<tracker>/comments --paginate --jq '.[].body'
```

Take the **last** `<!-- guild:sprint:run -->` block: the supervisor rewrites the marker by
posting, so earlier copies are stale heartbeats. Absent → render `state: 없음` and **no board
line at all**; do not fall back to a freshness claim, because "no marker" and "board healthy"
are the two things that must not look alike.

```bash
gh pr list --state all --limit 200 --json number,headRefName,baseRefName,state,mergedAt,reviewDecision,statusCheckRollup,closingIssuesReferences
```
```bash
gh issue list --state all --limit 200 --json number,title,labels,state
```
```bash
git worktree list --porcelain
```

Derive each member's stage with `_handoff.md` Section A's **list form** (it already excludes
`guild:child`, `guild:needs-human`, `guild:harness` and `guild:sprint`, and returns the
additive `paused` flag separately — never sum `paused` beside the stage buckets).

Map PR → member via `closingIssuesReferences`, falling back to an issue-number token in the
head branch name (`_sprint_dag.md` Section D). ⚠ A member whose dependency shows `BLOCKED:dep-pr-ambiguous` has
**two open PRs with different branches** — render it under 의존성 차단 with both PR numbers and
say *"둘 중 하나를 닫으면 풀립니다"*; it is not a failure and needs no re-plan.
**Merge order comes from the member table's
`base 의존` chain**, not from PR creation order.

**4. Failure reasons come from `failures.jsonl`, not from the console.**
`<repo>/.claude/guild/.sprint-logs/<tracker>/failures.jsonl` — one JSON object per line:
`{at, tracker, run, issue, class, detail}`. Read it with its own Bash call:
```bash
tail -50 .claude/guild/.sprint-logs/<tracker>/failures.jsonl
```
The classes the supervisor writes — **this list is the code's, verbatim**:

| class | 실패인가? |
|---|---|
| `worktree-create-failed` · `deps-install-failed` · `dag-input-failed` · `base-decision-failed` · `rate-limit-exhausted` · `incomplete-mid-spine` · `child-session-failed` | **실패** — 이 이슈의 하류도 차단된다 |
| `dependency-blocked` · `base-unresolved` · `branch-ambiguous` | **차단** — 의존이 아직 랜딩되지 않았거나, 후보 브랜치가 둘 이상이다. 실패로 렌더하지 말 것 |
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

⚠ **Add the split-parent line** for any member that reached `guild:done` with a
`<!-- guild:children:output -->` comment and **no PR of its own** — the same condition step 6
already evaluates: *"#107 은 자식 PR 로 완료됩니다 — 보드 카드는 부모에 남습니다"*. Guild hides
children from the board (D8), so without this the parent sits in `In review` with no PR to
review and a `split-children` token a human has no way to decode.

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
  #107  분할 오케스트레이션이 멈춤 — 자식 2개 미완 (`/gld dev 107`로 이어가세요)

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
- **Heartbeat age with `state`.** A ~115-minute rate-limit wait is normal; age alone would read
  as a dead run. ⚠ Render the `state` token as the supervisor writes it and translate for the
  human beside it — the shapes are `running` · `installing-deps` ·
  `rate-limited-until-<epoch-seconds>` · `rate-limited-remaining-<n>s` · `finished` ·
  `halted:<reason>` (ASCII, `_handoff.md` Section K). `rate-limited-until-1790000000` becomes
  *"rate-limited — 예상 재개 14:20"*; do **not** invent a shape the supervisor never writes.

**6. Termination — two axes, reported separately.**

| Axis | Condition |
|---|---|
| **run finished** | the queue is empty — every member ended done, needs-human, failed or blocked. **Not all done.** |
| **sprint finished** | run finished **AND** no member PR is `OPEN` **AND** no member PR is `CLOSED` unmerged **AND** the same holds for the PRs of any children a split produced |

Sprint finished → *"회고 가능 — `/gld sprint retro`"*. Otherwise say precisely what remains.
⚠ A `CLOSED`-unmerged PR is **not** a completion: the human rejected that work. Surface it as
*"닫힌 PR <n>건 — 확인 후 회고하세요"* rather than letting the count read as done.
⚠ **A split parent's CHILDREN count too.** When a member reached `guild:done` by being split
(its `<!-- guild:children:output -->` comment exists, and `run` handed it to the human), the
parent has no PR of its own — its children carry them. Discover them and fold their PRs into
both axes above:
```bash
gh issue list --state all --limit 200 --json number,title,labels,state,body --jq '[.[] | select((.body // "") | test("Parent Issue: #<parent>([^0-9]|$)"))]'
```
Without this, an open child PR sits outside the count, *"sprint finished"* reads true, and
`retro` closes a sprint whose work is still in review. Render them indented under the parent so
the human sees they belong to it.

⚠ **A member Issue the human CLOSED is not a completion either.** `run` drops it from the queue;
render it as *"사람이 닫음"* in its own line rather than letting it vanish or count as done.

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

`OK: sprint #<n> — run <finished|queue N> / sprint <finished|open PRs N>` ·
`OK: no active sprint` · `FAIL: <reason>`

---

## Hard rules

- **Read-only except the `daily` marker** (step 8), which is named as an exception.
- **Actionable first**: change-requested PRs, needs-human, failures and stale bases come before
  any count.
- **Merge order is derived from the member table**, never guessed from PR numbers or dates.
- **Never use Issue open/closed as completion** — a stacked PR does not close its Issue.
- **Never judge a preserved worktree**; report source-vs-docs and let the human decide.
- **Never auto-catch-up a stale base** and never suggest a rebase — INV3.
- Four `gh` calls (issue list · tracker comments · PR list · issue list) plus one `git`, plus
  one child-discovery call per split parent; a missing source renders as "없음", not an error.
