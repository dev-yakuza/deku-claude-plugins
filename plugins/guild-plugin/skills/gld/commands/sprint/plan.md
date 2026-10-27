# SPRINT PLAN (intake — choose this sprint's issues, order them, open the container)

**Decide *what* the sprint takes and in *what order*, then create the tracking Issue.**
Attended and multi-turn: composing a sprint is a judgment the human refines before anything is
created. Upstream of `sprint run`.

`$1`, `$2` = flags, in either order: `--create` (default = **dry-run**: propose only, create nothing) · `--no-ask` (skip the Phase 3 decision questions — the sprint is filled only from candidates that are ready as they stand).

> **Bash**: `<<SKILL_DIR>>/commands/atoms/_bash_rules.md` — simple calls; issue bodies via a
> temp file + `--body-file`, never inline multi-line. Owner/repo · labels · `gh` write failures:
> `_handoff.md` Sections A/F. Membership · edges · `sprint_dag.py`: `_sprint_dag.md`.
> Readiness dimensions: `_readiness.md`. Roles: product-owner + tech-lead personas.
> **Output language**: `config.language` (`_handoff.md` Section K); machine tokens stay ASCII.
> Every role prompt below (product-owner, tech-lead, the slot re-spawn) ends with Section K's
> language line, written out — not left to the persona.

---

## Phase 0 — Preflight

Each its own Bash call.

1. **Guild initialized?** `ls .claude/guild/config.json` — absent → `FAIL: Guild not initialized (run /gld init first)`. This command needs `config.language`, `config.commands`, `config.sprint` and the product-owner/tech-lead role definitions.
2. **Does the `guild:sprint` label exist?**
   ```bash
   gh label list --limit 200 --json name --jq '[.[].name]'
   ```
   Absent → **stop before touching anything**: *"이 레포에는 아직 `guild:sprint` 라벨이 없습니다. `/gld update`를 실행하고 그 변경을 커밋한 뒤 다시 시도하세요."* Return `FAIL: guild:sprint label missing — run /gld update`.
   ⚠ This check is not cosmetic. Without it Phase 6 dies with a **terminal 422** on the label edit (`_handoff.md` Section F) *after* member bodies have been rewritten, and a re-run cannot find the orphaned tracker by label — it does not self-heal. `gh label list --json name` returns a **flat** array of `{"name":…}`; do not index it as `.labels[]`.
3. **Resolve `{owner}/{repo}`** once (`_handoff.md` Section F); hold the literal value.
4. **Is a sprint already open?**
   ```bash
   gh issue list --label guild:sprint --state open --limit 20 --json number,title
   ```
   Non-empty → ask the human: close it with `/gld sprint retro` first, or add these issues to it?
   **"retro first" → `plan` does nothing more** (no Phase 1, no draft, nothing written) and
   returns `OK: open sprint #<t> — run /gld sprint retro first` (Return); the net-splice note
   below still says the approved net was not applied. Before asking, when the open tracker has a `<!-- guild:sprint:plan-decisions -->` comment, say
   how many of its lines are missing from their members' bodies (by dimension key, members at
   stage `none`/`guild:analyze` only): `결정 N건이 본문에 반영되지 못했습니다: #a … — "추가" 를
   고르고 Phase 6 까지 승인하면(추가할 이슈가 없어도) 재실행이 복구합니다` (Idempotency, below). Two or more open → say so and ask which; concurrent sprints are not supported.

   ⚠ **Then check whether a supervisor is actually RUNNING** — read the open tracker's
   `<!-- guild:sprint:run -->` marker (`gh api repos/<owner>/<repo>/issues/<tracker>/comments
   --paginate --jq '.[].body'`, **oldest** block wins — the supervisor PATCHES one comment in
   place and picks `min(id)`). `state:` of `running` / `installing-deps` /
   `rate-limited-*` / `waiting-for-window-<HHMM>` means a run may be in flight. Branch on the
   heartbeat, **not on the host**:

   ⚠ **`waiting-for-window-*` is a LIVE run.** It is the state a windowed run spends most of its
   life in — up to twelve hours at a stretch, for days — and the refusal message has to say so
   or the human reads *"refused, nothing is happening"* as a bug: *"#<tracker> 의 감독자가 창
   밖이라 대기 중입니다 — 남은 멤버 <n> · 다음 창 <HH:MM>. 중단하시려면 `kill <pid>` 후 다시
   불러 주십시오 — 멤버 작업 중이면 그 멤버가 끝난 뒤에 멈춥니다."* Omit the token and this
   state falls into `proceed`, which does the damage this section already names below —
   *"seeds members a live supervisor is developing, resetting their cards to `Ready`"*.

   | Observed | Verdict |
   |---|---|
   | live `state:` · `heartbeat` within 15 minutes | **refuse `--create`** — *"#<tracker> 의 감독자가 지금 돌고 있습니다(<state>). 끝나기를 기다리시거나 중단한 뒤에 다시 불러 주십시오."* |
   | live `state:` · `heartbeat` older than 15 minutes | **ask the human** — it is either a crashed run or a machine we cannot see |
   | `finished` / `halted:*` / no marker (**read succeeded**) | proceed |
   | the comments read **failed** — non-zero exit, or empty output that is not provably an empty comment list | `NEEDS_HUMAN: cannot prove no supervisor is running` |

   ⚠ **A failed read is not "no marker".** Both produce empty output, so without this row a rate
   limit, an expired token or a `--paginate` that died mid-way lands in `proceed` — and then
   `plan --create` seeds members a live supervisor is developing, resetting their cards to
   `Ready` with the reason cleared while the supervisor's column cache suppresses the repair for
   the rest of that member's development. "No marker" must mean *the read worked and there was
   none*, which is the legitimate first-sprint case and stays `proceed`.

   ⚠ **Do NOT gate this on `host` matching.** The supervisor refreshes its heartbeat at least
   every 10 minutes, *including inside a rate-limit wait* (`run.md` Phase 3 step 3), so a fresh
   heartbeat is proof of life on any machine. Keying on the host lets a run on someone else's
   checkout — or in a container — pass straight through.

   The reason is the board, and it got wider when `ready` became writable by the guard. Member
   seeding is deliberately unguarded (a member entering a sprint belongs in `Ready`), so seeding
   a member the live supervisor is developing resets its card to `Ready` and clears the reason —
   and the supervisor's column cache then suppresses the repair for the rest of that member's
   development, so the board says *"queued"* for hours while the work runs.

   ⚠ **The exposure is the unguarded seeding, not the guarded triage.** `ready` became
   plan-owned so that `plan` can clean up a column no other writer ever revisits — but the
   supervisor only writes `ready` from inside its member queue, so every such card belongs to a
   **member** of the open sprint, and Phase 1 excludes members from the candidate set the
   guarded writes are drawn from. So even if this check fails, the guarded path is structurally
   safe; what is not safe is seeding. The carryover reasoning that justifies unguarded seeding
   assumes the previous run has **ended**, and this check is the only thing that makes that
   assumption true.

   **An interrupted net splice** — only now, after the verdict above is `proceed` **and** the human chose to **add** these issues to the open sprint (never on the "retro first" choice — then say the approved net was not applied — and never under dry-run without asking): if the open tracker has a `<!-- guild:sprint:slot-net -->` comment whose `slot: #<n>` is still the tracker's slot member, that Issue's body lacks `<!-- guild:safety-net -->`, and the Issue is still at `guild:analyze` or earlier, splice the comment's parts (the Safety net section, its Success-criteria lines, and the known-gaps/findings part) into the body (Phase 6 step 3's rules — read, splice, truncation check, full rewrite) and say so. Past analyze → do not splice (its AC are fixed); tell the human the approved net was not applied. Body already holding the marker → it was applied; do nothing.
5. **Merge strategy + branch deletion** — the stack's premise:
   ```bash
   gh repo view <owner>/<repo> --json mergeCommitAllowed,squashMergeAllowed,rebaseMergeAllowed,deleteBranchOnMerge
   ```
   ⚠ **A read that works with read permission.** The REST repository endpoint returns its merge
   settings as `null` to an account that is not a repo admin (measured on `cli/cli`: every field
   `null` over REST, the real values from this call with the same account; on a repo the account
   administers the two agree). Read over REST, a non-admin's settings would fall into the
   unknown case below and cap every sprint at 1.
   The repo is positional; there is no `--repo` flag.
   - `mergeCommitAllowed == false` (squash/rebase only) → **stack with `squash-sync`** (`_sprint_dag.md` Section G): the cap stays `config.sprint.max_stack_depth`. Under squash, merging the bottom PR leaves its commits *not* ancestors of the base, so the upper PR would show them **again**; `/gld sprint sync` fixes that by merging the default branch into the upper branch (a merge, not a rebase — INV3), verifying, and pushing. Stacked PRs open as **drafts** so they cannot merge before their base. Tell the human in Phase 5: *"하단 PR을 머지한 뒤 `/gld sprint sync`를 실행하세요. 하단이 리뷰로 바뀌었다면 상단은 사람이 따라잡습니다. draft에는 리뷰 요청 알림이 가지 않습니다 — 아래부터 리뷰하세요."* The human may decline → **`EFFECTIVE_CAP = 1`**, token `merge-commit-forbidden` (no stacking; every PR targets the default branch) — Phase 5's **`스택 없음`** edit.
     ⚠ **The cap is a value, not a warning.** Carry `EFFECTIVE_CAP` through Phase 4 (it is what `--mode depth` is given) and write **two lines** into the tracker body: the **스택 깊이 상한** value and a **상한 근거** token — `config` (merge commits allowed) / `squash-sync` / `merge-commit-forbidden` / `human-override` (a pre-0.91 tracker that stacked on squash without sync; never written now). ⚠ Machine tokens, not prose: `run` compares the token with the repo *now* and picks the PR mode from it. A line carrying two numbers ("상한 3 (사람이 1로 승인)") does not say which one is in force.
   - `deleteBranchOnMerge == false` → note: GitHub will not retarget an upper PR by itself; `sprint sync` does.
   - **The call fails, or `mergeCommitAllowed` is missing from its output** → do not assume the
     permissive value: **`EFFECTIVE_CAP = 1`**, token `merge-commit-forbidden` (conservative), and
     Phase 5 says
     `머지 전략: 알 수 없음(조회 실패) → 스택 없음(상한 1) · 브랜치 자동삭제 ?`.
     The human accepting a depth is the same switch to `squash-sync` as on a repo known to
     disallow merge commits (Phase 4 step 4); the line then reads
     `머지 전략: 알 수 없음(조회 실패) → squash-sync(상한 <n>) — 하단 PR 머지 뒤 /gld sprint sync · 브랜치 자동삭제 ?`
     — only these two forms. Only `deleteBranchOnMerge` missing → only that half reads
     `브랜치 자동삭제 ?`.

## Phase 1 — Collect candidates

```bash
gh issue list --state open --limit 200 --json number,title,body,labels --jq 'length, (.[] | {number, title, labels: [.labels[].name], body})'
```

⚠ **Stream form — the first line is the count, then one Issue per line.** The earlier
`{total, candidates:[…]}` form printed the whole read as **one line** (measured 156,923 B), and
when a tool output that large is moved to a file, Read reports *"very long lines and cannot be
paginated"* and shows only its start — the product-owner and the tech-lead judged from a prefix
of the candidates (measured: up to about #555–#524). One line per Issue pages normally. **When
the output is moved to a file, read it to the end with Read's `offset`/`limit`** — the leader,
and the product-owner and tech-lead too (their prompts say so).

⚠ **`body` stays here on purpose — it is the material, not overhead.** Phase 1b judges each
candidate 착수 가능 vs 구체화 필요 **by reading it**; a narrowed read would make that judgment
from a title. Measured on `dev-yakuza/one-man-company`: 135,753 B over **51** open Issues
(≈2.7 KB each) — that is the work, and the same conclusion the token work reached about
Write/Agent/Edit. ⚠ Do **not** "optimise" this into a title-only scan.
⚠ The label classes below are filtered **client-side**, not in `jq`: an open `guild:child` is
excluded as a candidate but its body is still read here — it is the body of an epic's remaining
child (Phase 2 reads it from this output). Measured 2026-10-18 (`dev-yakuza/one-man-company`):
of 60 open Issues, 36–38 (depending on the moment) carried `guild:child`, 57% of the bodies.

**The count comes back in the same call** — the first line — so the truncation check below
needs no second `--jq 'length'` invocation (`count` in Phase 1b is that line). An added turn
re-bills the whole prefix, and a check that costs a turn is a check that gets skipped.

Exclude: `guild:done` · `guild:sprint` (trackers) · `guild:child` (they arrive through a parent) · any Issue already a member of an open sprint (`_sprint_dag.md` Section A). ⚠ Do **not** exclude a `guild:children` parent (an **epic** — already split into children): taken, `run` continues it — it re-invokes `/gld dev <parent>`, which drives the remaining children in order to the end (`run.md` Phase 3, *`guild:children` is not terminal* — it is not handed to the human), so the epic is one candidate like any other (below).

**Epics (`guild:children` candidates) — one more call**, after the one above:
```bash
gh issue list --label guild:child --state all --limit 500 --json number,body,labels,state --jq 'length, (.[] | {number, state, labels: [.labels[].name], parent: ((.body // "") | (match("Parent Issue: #([0-9]+)").captures[0].string | tonumber)? // null), depends_text: [(.body // "") | match("Depends on:?[^\n]*"; "g").string | split(". ")[0]]})'
```
The same stream form (first line the count, one child per line — measured ~116 B a child, so
as one JSON line 500 children would be ~58 KB on one line that Read cannot page). A child with no
`Parent Issue:` line stays as `parent: null`, so the count and the lines never disagree;
`tonumber` makes `parent` comparable to an Issue number. `depends_text` holds **the first
sentence** (before `. `) of each `Depends on` line. **Count == 500 → the epics cannot be judged**:
no epic is filled automatically (Phase 5 `제외: #e (에픽 · 자식 목록이 500건에서 잘려 판정 불가)`).
Per epic `#e` (a candidate with `guild:children`):
- `remaining: <k>` = its children (`parent == e`) **without `guild:done`**, whatever their
  state — the definition `run`'s `children_pending` uses (`sprint-supervisor.sh`), except that
  the merged children below are left out of `k`; a stacked PR
  does not close its Issue, so an open child that is already `guild:done` is common.
  A child marked `(머지됨 — run 이 정리)` (below) is **not counted in `k`** — its work is in and
  only `dev` Phase 2b's cleanup is left — so it adds no seat, no PR and no `epic ×<k>`.
  `blocked_children: <#c…>` = those of them carrying `guild:needs-human` — **except a CLOSED one
  merged by a human** (rare): for each `guild:needs-human` child that is closed, run
  `gh issue view <c> --json closedByPullRequestsReferences` and, for each PR in it whose
  `repository.owner.login`/`repository.name` is this repo, `gh pr view <p> --json state` (each its
  own Bash call). A `MERGED` one → not blocked (`dev` Phase 2b cleans the child up to `guild:done`
  on the next run); none → blocked as before (closed by a human but not merged — `run` would stop
  on it). This is the definition `daily` step 5's 사람 대기 shares.
  `closed-not-done: <#c…>` = those of them that are closed (their bodies are not in the Phase 1
  output). A closed-not-done child with a same-repo `MERGED` PR (the same check, for every
  closed-not-done child) is shown `#c(머지됨 — run 이 정리)` — its work is in; it is not read,
  and it is excluded from readiness, sizing and the `remaining`/`epic ×<k>` counts.
- **k = 0** → every child is done (or merged and waiting for `dev` Phase 2b's cleanup); only `dev` Phase 2c's integration check is left. Not a
  candidate: Phase 5 `통합 점검 대기 — /gld dev #e`, one line per such epic, right after the
  `사람 작업 필요` line; it counts in Phase 1b's first-line `제외`.
- **The extended dependency floor** (the leader computes it, here, mechanically): the `#<n>` in
  the epic's own body's `Depends on` lines and in the remaining children's `depends_text`,
  **minus each line's own Issue, its parent (the epic) and its siblings (the epic's other
  children)** — removed mechanically, never judged. The
  **`Depends on` reading rule** applies to every `Depends on` this file reads — an epic's body,
  a child's `depends_text`, and an ordinary member's body (Phase 5's `⚠ 선행 미포함`): only
  the line's **first sentence** (before `. `) counts, and a line that begins `Depends on: 없음`
  or `Depends on: none` (any case) is **no dependency at all** (measured #252
  *"Depends on: 없음(#155/#248이 … 코드 의존은 없음)"* — the first-sentence rule alone keeps the
  whole line). A child's `Depends on` is free prose (measured #504 *"…, #496. #146(…)과 같은
  엔진 구간이라 순서를 조율한다"*, #523·#524 *"#523. #154 의존 없음"*, #193 *"자식 #132-①"* — its
  own parent), so when the first sentence still holds a negation (*"의존 없음"*) or an ordering
  note, the leader may remove that number too. What is removed for being the line's own Issue,
  its parent or a sibling is **not shown** (#158 alone would be ~15 lines); a `#n` left out only because it
  sat after the first sentence, and every number the leader removed by judgment, is shown in
  Phase 5 as `의존 무시: #e ← #d (본문: «<그 문장>»)` — **for a member only** (an epic member
  or an ordinary one — Phase 5; a non-member's ignored number changes nothing) — and the human
  can put it back (`의존 유지 #d`). Measured (this exact jq): epic #459's remaining children #502–#505, siblings
  #502·#503 removed → floor {#496, #495}, both CLOSED and `guild:done`; #146 does not enter.
- **A dependency on a child** (whoever holds it — an ordinary candidate or another epic's
  child; the same rule): the
  target child `c` closed or `guild:done` → judged as `c` itself; otherwise read as a dependency
  on **`c`'s epic** (measured #529 → #513·#518, children of epic #154).
- **An epic's files** = the union of the files its remaining children will touch (tech-lead
  (b)); a child that names only a directory overlaps every file under it (the slot overlap check,
  Phase 2).
- **Each remaining child's stage** = the `labels` of this child query with `_handoff.md` Section
  A's canonical derivation applied (the same exclusion list — no extra call); `children:` carries
  it per child (Phase 2), so the product-owner and the tech-lead see it too.
- **The children each judgment reads — the bound differs by kind of judgment** (the same bounds
  an ordinary candidate already has). Every child-level rule in this file reads these sets:
  - **Children to be sized** (the tech-lead's ✅ / ⚠ / `depends:` / mixed verdict, and a missing
    verdict): the remaining children at stage `guild:design` or earlier. A child at
    `guild:execute` or later cannot be split any more — design does not run again on it (`dev`
    starts the spine from its current label, and the only loop-back is `OK LOOPBACK: execute`) —
    so its size is not judged: whatever the tech-lead wrote, it counts as ✅.
  - **Children to be decided** (the product-owner's `decide-in: #c`, a readiness `unclear` that
    comes from a child's body, 1b 구체화 필요): the remaining children at stage `guild:analyze` or
    earlier (`none` included) — past analyze, an answer in the body no longer reaches the
    acceptance criteria (the bound of an ordinary candidate's past-analyze readiness exemption,
    Phase 3 step 1). A `decide-in:` that names a later child is ignored, and a later child's body
    makes the epic neither `unclear` nor 구체화 필요.
  - **Every remaining child**, whatever its stage: 1b **막힘** (a credential, a device or an
    upstream fix stops `run` after execute too), the extended dependency floor, (i),
    `바닥 선행 미완`, the tech-lead's (a), the files (an execute child also starts from the
    default branch — measured #532·#555 on `schedule_engine.dart`), and k (`SPLIT_PASSES` grows
    on every pass whatever the stage — the k ≥ 10 warning is unchanged).
  - **No child to be decided** → the epic is not held to the readiness gate either (Phase 3
    step 1 holds an epic to it only because its remaining children are usually at analyze);
    Phase 5 shows it as `이월(에픽 · 자식 모두 <stage> 이후)`, `<stage>` = the earliest stage
    among its remaining children.

"Open" for every check here = in this phase's first output (before exclusions) or an `OPEN`
child above; anything else is closed.

Apply `_handoff.md` Section A's **list-form** derivation per element to get each candidate's current stage — an Issue already mid-spine can be a member and will resume.

**Mark the refactor candidates** — each candidate gets a `tag` in the CANDIDATES list Phase 2
hands out:
- `refactor-slot` — its body holds `<!-- guild:refactor-slot -->` **and** it was created after
  the newest `guild:sprint` tracker (`gh issue list --label guild:sprint --state all --limit 1
  --json number,createdAt` against `gh issue view <n> --json createdAt`, one call each; **no
  tracker has ever existed → the bound is met**, which is the first sprint's case). That is
  exactly the orphan of a `plan --create` that died before its tracker existed (Phase 6 step
  0); the re-run reuses it instead of drafting a second one. ⚠ The time bound is what keeps a
  slot the human once declined from claiming step 0 forever: after any later tracker exists it
  is an ordinary `refactor`.
- `refactor` — carries `type:refactor`, or holds the marker but is older than that tracker.
- `—` — everything else.

## Phase 1b — Triage the intake (report now, write to the board later)

⚠ **This phase runs whether or not a board is configured.** The judging and the report are
the substance; the board is one way of *showing* the same thing. §12's rollback says it
outright — setting `config.sprint.board` to `null` stops the board **writes**, not the
triage — and a board-less repo (the D2 default) is exactly the reader who needs the
*"구체화가 필요합니다"* group list most, since no column will ever say it for them. What is
gated on the board is Phase 6 step 5, and only that.

The candidate set is Phase 1's, unchanged. Split it in three:

| Verdict | What it means | What Guild does |
|---|---|---|
| **착수 가능** | what to build is decided by reading the Issue | the card goes to `Backlog` |
| **구체화 필요** | an idea, or a plan with an open question. Handed to `dev` today it ends at `needs-human` | the card's column is **cleared** → the null bucket, i.e. `Issues`. **Grouped by theme and reported** |
| **막힘** | what to build is decided, but something only a human can clear blocks it — a credential, a real device, a fix in **another repository** | the card's column is **cleared** → the null bucket, like 구체화 필요. **Reported as its own group**; Phase 5 lists it under `사람 작업 필요: #n (<credential\|device\|upstream\|other>)` — the class from this 1b reading (Phase 2 leaves it out of the product-owner's CANDIDATES, so the product-owner never rates it) |

⚠ **Changing a central-owned file is not by itself `upstream`** (*Central-owned files*, in the
Refactor slot section) — 막힘 (upstream) only when the body requires a fix to land first in another
repository. A change the body would make here is Phase 5's warning line, not a block: the same
kind of Issue must not come out 막힘 on one reading and a member on another.

An **epic** (`guild:children`) is judged by its **remaining children's bodies** (Phase 1 —
the children without `guild:done`), not its own: 착수 가능 / 구체화 필요 / 막힘 — **막힘 from
every remaining child, 구체화 필요 only from the children to be decided** (Phase 1's bounds: a
child past analyze can no longer be refined by its body, but a credential, device or upstream
block still stops `run` on it). A
`closed-not-done` child's body is not in the Phase 1 output — read it with
`gh issue view <c> --json body` (one call per such child; rare). **Except a child marked
`(머지됨 — run 이 정리)`**: it is not read and is no remaining child for this judgment — not 막힘,
not 구체화 필요 (its work is merged; `dev` Phase 2b cleans it up).

⚠ **Truncation is named, not silenced.** Phase 1 reads `--limit 200`. If `count` (the first
output line) `== limit`, re-read with `--limit 500` (the same command, same stream form); if it
still equals the limit, **continue anyway** and put one line
at the top of the report: *"⚠ 열린 이슈가 500개 이상입니다. 최근 500개만 판정했습니다."*
⚠ Do **not** borrow `retro.md`'s procedure here. Its re-read narrows with
`--search '"Sprint: #<tracker>" in:body'`, which is exact *because members carry that
back-reference* — intake candidates are non-members and have no such line. And its PR branch
**stops**; stopping here would mean `sprint plan` cannot run at all in a repo with 200+ open
issues, which it does today.

Report all three groups. This is the whole point of the phase — the second and third groups
are a work list for the human. The first line is defined, not free-form:
`판정 <후보 수>개 · 착수 가능 <a> · 구체화 필요 <b> · 막힘 <c> · 제외 <Phase 1 에서 뺀 수> · 절단 <없음|있음>`
(`<후보 수>` = a + b + c; `제외` = the Issues Phase 1's exclusions removed from the read, **k = 0
epics included** — `통합 점검 대기`).

```
판정 41개 · 착수 가능 34 · 구체화 필요 4 · 막힘 3 · 제외 6 · 절단 없음

■ 이번 스프린트 후보 — 착수 가능
  그룹 1 «결제 실패 처리»   #101 #102 #104
  그룹 2 «영수증»          #103

■ 구체화가 필요합니다
  그룹 A «알림 채널 재편»   #120 #121 #127
      → 셋 다 "어디로 보낼지"가 미정입니다. 함께 정하는 편이 낫습니다
      → /gld plan 120
  그룹 B «관리자 화면»      #133 · #140 (이월 — 채우기를 막지 않음)
      → 화면 범위가 한 줄뿐입니다
      → /gld plan 133
  그룹 C «일정 엔진»        #459 (에픽)
      → 자식 #503 의 경계 조건이 미정입니다
      → 자식 #503 본문을 구체화하세요

■ 막힘 — 사람만 풀 수 있습니다
  #190 (credential) · #246 (device) · #357 (upstream)
```

**A carried-over 구체화 필요** — an ordinary candidate (not an epic) at stage `guild:design` or
later — is reported as judged, with `(이월 — 채우기를 막지 않음)` beside its number, and gets no
`→ /gld plan <n>` line: past analyze its acceptance criteria are written, so an answer in its body
reaches nothing, and the fill does not gate on 구체화 필요 there (Phase 3 step 1 — the same bound
and reason as the readiness exemption). 막힘 is reported the same at every stage.

When attended and not `--no-ask`, add one line under the second group: *"일부는 이번 플래닝 중에
결정 질문으로 담을 수 있습니다"* — which ones is known only after Phase 2, so Phase 5 says which
were asked (`앞서 구체화 필요로 보고한 #n — 이번에 답해 담았습니다 / 건너뛰었습니다 / 이번에 답했지만 빠졌습니다(결정했지만 제외 줄 참고)`).

⚠ **Larger refinement is not this command's job.** A decision that one answer settles is asked
in Phase 3; anything bigger stays with the human, who runs the existing **`/gld plan <issue>`**,
which decomposes an epic into dev-unit Issues. That labels the parent `guild:children`, and a
`guild:children` parent is **not** excluded from Phase 1 — so the epic itself becomes a
candidate next time. The backlog unit after refinement is the **epic**, not its children.
⚠ **An epic is never pointed at `/gld plan`** — it is already split, and `/gld plan #e` only
adds the children it lacks (`plan.md` step 5, issue-mode idempotency). An epic in the second group gets
`→ 자식 #c 본문을 구체화하세요` (or `결정할 자식 전체` when no single child is the gap) instead.

⚠ **Nothing is written to the board yet.** Judging is free; writing is not. See Phase 6 step 5.

## Phase 2 — Select and order (product-owner ∥ tech-lead, parallel)

**When REFACTOR SLOT is `on`, first fetch the default branch** (decide that after *Two candidate
lists* below — a removed `refactor-slot` candidate turns it `off`) — the tech-lead's git reads go
against it (the "Refactor slot" section below). Its name: `gh repo view --json defaultBranchRef
--jq .defaultBranchRef.name`; then `git fetch origin <d>:refs/remotes/origin/<d>` — the refspec
form, because a bare `git fetch origin <d>` does not update `origin/<d>` in a single-branch
clone (`_execute_spine.md` says the same). Each its own Bash call.
⚠ The fetch is the leader's, not the sub-agent's: the tech-lead runs `scan_git.md`, whose rule is *local &
read-only — no git mutations*, and that stays true. Fetch fails (offline, an SSH remote with no
agent while `gh` still works over HTTPS) → say so once, and pass `DEFAULT BRANCH: unavailable`
and `PAST SLOTS: unverifiable — <the entries, verbatim>` — **keep the entries**: the flag says
they cannot be checked, not that they are gone. What the tech-lead does with these values is
in the "Refactor slot" section, which is the only part of this file it reads.

**`docs/specs/sprint-draft/`** is a fixed scratch name: the sprint has no number yet. First
make sure it exists — its own call, `mkdir -p docs/specs/sprint-draft` (a repo's first sprint has
no such directory, and a sub-agent's Write into it should not be the first to find out). **Then,
before spawning, clear the last run's verdicts** — one call,
`rm -f docs/specs/sprint-draft/po.md docs/specs/sprint-draft/deps.md docs/specs/sprint-draft/deps-slot.md`
— so a sub-agent that returns without writing, or a re-spawn that does not happen this time,
cannot leave an older run's file to be read or recorded as this one's. Phase 6 step 6 moves the
files this run's RESULT lines named into `docs/specs/sprint-<tracker>/` and commits them: the PO
and tech-lead **verdicts as first given** (판정 원문), not the composition the human approved
after edits — that is the tracker body.

**Two candidate lists — what the leader already knows is left out of the product-owner's.**
Before spawning, the leader removes from the product-owner's list every candidate it already
knows, deterministically, cannot be taken: a Phase 1b **막힘** one, one carrying
`guild:needs-human` (Phase 3 step 1), and an epic with `blocked_children` (*Epics in the fill*;
an epic with k = 0 is not a candidate at all — Phase 1). A goal written around a candidate the
fill must then drop is the goal mismatch this prevents (measured twice: the product-owner built
the goal on #459 and #161, and the mechanical rules dropped both — `⚠ 목표 멤버 없음`).
- **`CANDIDATES (product-owner)`** = the candidates minus those.
- **`CANDIDATES (tech-lead)`** = **every** candidate, each one removed above carrying the extra
  field `slot: ineligible` (a field of its own — the `tag` enumeration does not change). The
  tech-lead still sizes it and names its files: a human who puts it back with Phase 5's Add needs
  them (the slot overlap check, Phase 4's file edges). `slot: ineligible` keeps (c) off it — a
  candidate the product-owner did not rate has no `clear` rating, so the slot's step-1 bar
  (both ratings `clear`, the arbitration below) would reject it and spend the one re-spawn.
- A **`refactor-slot`**-tagged candidate among the removed (step 0 would take it ahead of
  everything) → the leader records `skip (not-ready)` now, before the spawn, and spawns the
  tech-lead with REFACTOR SLOT `off` (no (c) is asked for, and the default-branch fetch above is
  skipped).
- **An epic's `children:` carries each remaining child's stage and the leader's floor verdict**
  (both lists — the `tag` stays as it is): `children: #c1(<stage>) #c2(<stage>) … (remaining <k> ·
  blocked … · closed-not-done … · 바닥 선행 미완 <#d…|—>)` — the stage is Phase 1's (*Each
  remaining child's stage*) — where *미완* = a target of Phase 1's extended dependency floor that, after the child
  mapping, is **open and not `guild:done`** — the same definition as (i) in *Epics in the fill*
  (a `guild:done` target still open, measured #530·#531, is not 미완). The child list cut at 500
  (Phase 1) → `바닥 선행 미완 판정 불가`. Such an epic stays in the product-owner's list (the
  tech-lead can still **add** a dependency to it), and the product-owner is told it is not taken
  this sprint.
Phase 5 states each removed candidate's reason itself, in the wording it already has
(`사람 작업 필요: …`). A removed candidate the human adds back in Phase 5 shows
`readiness: —(PO 미평가)` in its row.

As the leader, spawn BOTH role sub-agents in one message (independent, concurrent). Reuse the prompt *shape* of `plan.md` Phase 1, but the job is **selection, not decomposition**.

⚠ **BODIES 는 명령으로만 넘긴다 — 본문을 파일로 저장해 넘기지 마라(공유 /tmp·저장소 안 모두).** Put the Phase 1 command itself in each prompt's BODIES and let the role run it. Measured: a leader saved the bodies to `/tmp/gld_candidates_tl.txt` and `/tmp/gld_sprint_candidates.jsonl` — a fixed name in a shared directory any other process can read or replace — and `docs/specs/sprint-draft/` is no alternative: it is not gitignored (Phase 5's sweep handles the case where it was swept into a human's commit). 도구 출력이 파일로 넘어가는 것은 도구의 동작이며 Read 의 offset/limit 으로 끝까지 읽는다.

**Product Owner** (value):
- `subagent_type`: `general-purpose`, `model`: the role file's `model:` frontmatter (`_model_tiering.md` Section 0 — `sonnet` when absent), `description`: `product-owner sprint select`
- `prompt`:
  > Adopt the persona in `.claude/agents/product-owner.md`. Read the candidate list below and `docs/standards/charter.md`. **A number that is not in CANDIDATES (product-owner) is never ranked, made the goal, or given a `Q:`** — even when its body is in the BODIES output; pointing at it from another candidate's `prerequisite: #<d>` or `decide-in: #<c>` is allowed, and writing that dependency is required. **Judge from the bodies, not the one-line scope**: run the read-only command given as BODIES (after CANDIDATES) yourself and read its output to the end — when the tool moves it to a file, page through it with Read's `offset`/`limit` (it prints one Issue per line, the first line is the count). A `guild:children` candidate is an epic already split into children — taken, `run` carries its remaining children through in order to the end. Its children cannot be picked one by one, so rank the epic as one candidate, exactly like the others. Its readiness is judged from its remaining (not `guild:done`) children's bodies — open ones are in the same output, a `closed-not-done` one you read with `gh issue view <c> --json body` — **except one marked `(머지됨 — run 이 정리)`: do not read it, and leave it out of the readiness judgment** (its work is already merged; `run` only cleans it up). **A child whose stage in `children:` is later than `guild:analyze` gets no `decide-in:`, and leave it out of the readiness judgment** — its acceptance criteria are already written, so an answer in its body would reach nothing. Do not draft decision questions for an epic — when one of its children needs a decision, write that child's number in the epic's readiness `note` (`decide-in: #<c>`), and an unfinished prerequisite of the epic there too (`prerequisite: #<d>`); neither goes under `## questions`. **An epic whose `children:` shows `바닥 선행 미완 #<d…>` or `바닥 선행 미완 판정 불가` is not taken this sprint** — do not make it the center of the goal. Propose (a) **one sentence** naming what this iteration is for — it becomes the tracker's title, so it names the aim, never a list of the issues; (b) **goal-picks**: the candidates that serve it, in priority order; (c) **other-ranked**: every other candidate worth starting now, in priority order, whatever its relation to the goal — do not leave one out for being off-goal, the sprint fills its remaining seats from this list; include one that is `unclear` when a single decision would make it startable (its question is drafted below). For each candidate rate the three readiness dimensions of `_readiness.md` — **Goal / Constraint / Success-criteria** — as `clear` / `partial` / `unclear` (ASCII machine tokens, never localized). **Mark every candidate with an `unclear` dimension and, for each such dimension, draft the decision that would settle it**: one question line and 2–3 answer options of one line each — or, when no answer from the requester can settle it, `human-work: <credential|device|upstream|other>` instead of a question (`upstream` = a fix that must land first in **another repository**). **An unfinished prerequisite Issue is not human work**: rate that dimension (usually Constraint) `unclear` and write `prerequisite: #<d>` instead — it waits on that Issue, not on a person. **Each `## questions` entry is exactly one of `Q:` / `human-work:` / `prerequisite:`** — when a question and human work both apply, write `human-work:` (an answer would not make it takeable). **Write `Q:` only for a candidate you put in goal-picks or other-ranked** — a not-ranked one is never asked; `human-work:` and `prerequisite:` are written for a not-ranked one too. The leader puts your drafts to the human when one is present and leaves those candidates out when unattended. **Do not select a candidate tagged `refactor-slot`** (an orphaned refactor-slot draft — the slot logic handles it), **and rate every candidate tagged `refactor` or `refactor-slot`, whether or not you selected it** — the leader may take one as the sprint's refactor slot and needs your ratings to do so. Write the result to a FILE `docs/specs/sprint-draft/po.md` (do not paste it back) with exactly these section headings, in this order: `## goal` · `## goal-picks` · `## other-ranked` · `## readiness` (a table `| # | Goal | Constraint | Success | note |`) · `## questions` (per drafted dimension `### #<n> <Goal|Constraint|Success>`, then exactly one of: `Q: <question>` and `- A) …` lines, the option you recommend first as `- A) <answer> (recommended) — <reason>` (`(recommended)` stays in English; one option only) (a goal-picks or other-ranked candidate only), `human-work: <class>`, or `prerequisite: #<d>`) · `## not-ranked` (every candidate you put in neither goal-picks nor other-ranked, one line each: `#<n> <reason>`).
  > <!-- guild:result-contract -->
  > Return EXACTLY one status line, preceded by a `>>> RESULT <<<` sentinel on its own line. Anything before the sentinel is ignored. Status is one of `DONE` / `DONE_WITH_CONCERNS: <one-line>` / `BLOCKED: <one-line>` / `NEEDS_CONTEXT: <one-line>` / `FAIL: <reason>`. **Artifacts are passed as files, not pasted** — write to the working tree or `docs/specs/<issue>/` and name the path in the RESULT line; never inline an artifact body into it.
  > <!-- /guild:result-contract -->
  > CANDIDATES (product-owner): <number · title · one-line scope · current stage · tag (`refactor-slot` | `refactor` | `—`) · decided: <the body's `<!-- guild:plan-decision -->` lines (`<key>: <question> → <answer>`), or `—`> · for an epic also `children: #c1(<stage>) #c2(<stage>) … (remaining <k> · blocked <#c…|—> · closed-not-done <#c…|—> · 바닥 선행 미완 <#d…|—>)` — in `closed-not-done`, a child a same-repo `MERGED` PR closed is written `#c(머지됨 — run 이 정리)` (Phase 1), for each candidate not removed above>. A decided line is the human's answer to that question — never draft it again; rate the rest of that dimension as usual (the same rule `analyze.md` Step 1 applies). BODIES: <the Phase 1 command **the leader actually ran** — the `--limit 500` one when Phase 1b re-read> — the verdicts are judged from the bodies; read them with this command.
  > <`_handoff.md` Section K's language line (emission point 2), rendered in `config.language` — e.g. in `ko`: *"모든 사람이 읽는 산출물(코멘트·파일 산문·RESULT 요약)은 이 레포의 `config.language`로 작성한다 (기계 토큰·코드·경로·마커는 영어 유지)."*> Write output in `config.language`.

**Tech Lead** (dependencies and size):
- `subagent_type`: `general-purpose`, `model`: the role file's `model:` frontmatter (`_model_tiering.md` Section 0 — `sonnet` when absent), `description`: `tech-lead sprint select`
- `prompt`:
  > Adopt the persona in `.claude/agents/tech-lead.md`. From CANDIDATES (tech-lead) (below) and `docs/standards/architecture.md`, produce (a) the **dependency relations** among them — which is a foundation for which, using the `Depends on: #<n>` notes in the bodies as input (only each line's first sentence, before `. `; a line beginning `Depends on: 없음` or `Depends on: none` is no dependency) and **adding** relations where the code says otherwise — add only, never remove one a body states (the leader computes those itself). A bullet line that follows a `Depends on` line with no blank line between, in a `## 의존성` section (`- #161 … (선행 필수)`), is a dependency too — add it. A soft ordering recommendation (better after another, not required) is not a dependency: keep it out of (a), as a separate note. When you judge that a dependency a body states is **already satisfied** in the code or at the child level, keep it in (a) all the same and write a **separate note** `satisfied: #<e> ← #<d> — via #<x> — <evidence>` (`#x` = the Issue that actually delivered what was needed) — it is shown to the human, it removes nothing. For an epic, (a) also covers its remaining children's dependencies outside the epic. **Whatever REFACTOR SLOT is, read the *Central-owned files* paragraph of the "Refactor slot" section of `<<SKILL_DIR>>/commands/sprint/plan.md`** (the one place it is written; not the whole file): changing a central-owned file is not by itself a fix that must land first in another repository — judge size and dependencies on the work in this repository. Write in (a) only a dependency that holds with no condition; a relation that holds only under a condition is a **separate note**, like a soft ordering recommendation — `conditional: #<a> ← #<b> (조건: <condition>) — <note>` (apart from (b)'s `depends:` size form) — except that when a body's `decided:` line already settles the condition, it is true → a dependency in (a), or false → left out. And (b) a **size** verdict per candidate: single dev-unit ✅, or ⚠ **likely to split at design**; for an epic, `epic ×<k>` (k = its remaining children) **and a ✅/⚠ for each child to be sized** — a child is a leaf and cannot be split again; **do not size a child whose stage in `children:` is `guild:execute` or later** (design does not run on it again) — keep writing its (a) dependencies and its files; when the size turns on a decision not yet made, `depends: <option>→✅, <option>→⚠`, saying in plain words which decision makes it ✅ (the leader maps that onto the product-owner's options, or asks it itself); **do not put ⚠ in front of `depends:`** — when it looks likely to split whatever the decision, write ⚠ alone (with its reason); the `decided:` lines of a candidate's body and of an epic's remaining children's bodies are evidence for the size — a decision a decided line already made is not a `depends:`; plus the source files each candidate will most likely touch (for an epic, its remaining children's; a directory is acceptable). Judge from the bodies: run the BODIES command yourself and read its output to the end (Read's `offset`/`limit` when it is moved to a file); a `closed-not-done` child's body via `gh issue view <c> --json body` — **except one marked `(머지됨 — run 이 정리)`: do not read it, do not size it, and do not count it in `epic ×<k>`** (its work is already merged; `run` only cleans it up). Do NOT read the product-owner's output; judge independently. **When REFACTOR SLOT is `on`**, also produce (c) **one refactor-slot proposal** (rules: the "Refactor slot" section of `<<SKILL_DIR>>/commands/sprint/plan.md` — read that section before writing (c), not the whole file). Write to a FILE `docs/specs/sprint-draft/deps.md`. Return one `>>> RESULT <<<` line. CANDIDATES (tech-lead): <the product-owner's entry format, for **every** candidate — those left out of the product-owner's list included, each with `slot: ineligible`>. BODIES: <same as above>. REFACTOR SLOT: <`on` | `off`>. DEFAULT BRANCH: <the repo's default branch name — the leader has already fetched `origin/<it>` — or `unavailable`>. PAST SLOTS: <the `refactor` field of every `config.sprint.history` entry that has one, or `none`>. VISUAL: <available or not per `_handoff.md` Section L.1 — `available` with `visual.packages` and `visual.tests`, or `unavailable`> (the gap check's visual half needs it; you are not reading config.json yourself). <`_handoff.md` Section K's language line, rendered in `config.language` — the same line as the product-owner's> Write output in `config.language`.

### Refactor slot — one per sprint, reserved, never forced

**Every sprint reserves one member slot for a behavior-preserving refactor** that pays down
the codebase the sprint is about to work in — **with a safety net laid first** where the code it
reshapes is under-tested, or, when no refactor qualifies, a **safety-net-only** slot that only
adds that net (both below). The slot is **reserved, not mandatory**: an empty
slot is a legitimate outcome **with a recorded reason**, and a weak refactor taken to fill it
is the failure this section exists to prevent. It costs one PR of the human's review
throughput, so it is the cheapest unit of codebase improvement that still goes through review.

**Switch**: `config.sprint.refactor_slot` — `true`, or **absent** (a config written before
this key existed) → `on`; `false` → `off`. `off` skips (c) entirely and the tracker records
`skip (disabled)`.

Every git read below goes against `origin/<default-branch>` (fetched by the leader before
the spawn — Phase 2's lead paragraph), so a stale clone or a checkout on a feature branch
cannot hide recent commits. **DEFAULT BRANCH `unavailable`** (the fetch failed) → read `HEAD`
instead, and say in (c) that the evidence may be stale. **PAST SLOTS `unverifiable — …`** →
run no PAST SLOTS git check; treat the `paths` of every listed `merged` or `refused` entry as
excluded from this sprint's slot — except `"kind": "safety-net-only"` entries (below): a merged one excludes nothing, a refused one excludes only another safety-net-only slot on its paths.

The tech-lead fills (c) in this order and stops at the first that yields a **ready**
candidate — all three readiness dimensions `clear` **and** size ✅ (the bar below; a
candidate at stage `guild:execute` or later counts as ✅ — design can no longer split it, the
same stage exemption the fill applies, Phase 2). A
candidate that fails it does not end the search; go on to the next step. **A candidate whose
CANDIDATES entry carries `slot: ineligible` is never (c)**, at any step — the leader already
knows it cannot be taken (Phase 2's two lists):

0. **A resumed slot** — a candidate tagged `refactor-slot` (Phase 1). It is a draft an
   earlier `plan --create` made and the human approved, orphaned when that run died before
   the tracker existed (Phase 6 step 0). Take it ahead of everything else and judge it
   by the draft's bar (the tech-lead's own ratings), not the existing-Issue bar — otherwise a
   re-run drafts a second Issue beside it. Run the gap check (below) on its **Files** unless its
   body already carries `<!-- guild:safety-net -->` or it is already past analyze (the same
   exclusion as step 1).
1. **An existing candidate tagged `refactor`** (Phase 1). **Run the gap check on it too** — an
   existing refactor Issue is the slot's most common source, and "existing tests stay green" is
   exactly as empty for it as for a draft — **unless** its body already carries
   `<!-- guild:safety-net -->` (a net appended by an earlier `plan`, possibly one that died
   mid-create: never a second net), or it is already **past analyze** (stage `guild:design` or
   later — Phase 1's stage derivation): its AC are fixed, so an appended net would never become
   AC and the refactor stage would find no `(safety net)` cases to lay. Such a slot runs without
   a net; say so in (c) (`안전망 없음 — 이미 <stage> 단계`). A gap found otherwise becomes a
   Safety net that Phase 6 step 3 appends to the existing Issue (after the human approves it in
   Phase 5). Prefer one whose area overlaps the
   files this sprint's other candidates will touch. ⚠ A stale, vague `type:refactor` Issue
   (*"clean up X"*) is the common case here; rate it honestly and fall through to 2 rather
   than letting it occupy the slot every sprint as a `skip (not-ready)`.
2. **A new draft**, from evidence. Run `<<SKILL_DIR>>/commands/atoms/scan_git.md`'s **Step 0 and Step 1 only** (fix
   concentration, scoped to the source dir, with `origin/<default-branch>` as the revision
   — `git log origin/<default-branch> --name-only … -80 -- <dir>`) — ⚠ not the whole scan; churn, co-change and
   conventions are evolve's inputs, not this slot's. Intersect the hotspot list with the
   files the other candidates will touch, and Read **at most ~3** of the intersecting files
   (the same bound `audit.md` dimension F uses). Draft the refactor that **makes those
   candidates' change easier** — a seam, an extraction, a duplication removed — in the
   Issue shape below. **Check its safety net while you are there** (the gap check below) and
   add a **Safety net** section when it finds a gap.
2b. **A safety-net-only draft** — only when step 2 found no refactor worth drafting, or drafted
   one that is not ready (readiness below `clear`) — the net's evidence does not depend on the
   refactor's (or a step-2 draft is converted for size at arbitration — see the Safety net
   bullets below). Among the
   same intersecting hotspot files, take the one with the clearest **gap** (below) and draft an
   Issue that adds only the net: tests (and, where they apply, visual cases) for that file's
   public behavior, **no production code change**. It is weaker than a refactor — it removes no
   difficulty, it makes the next change safer — so it needs the gap evidence, not just a hotspot:
   a hotspot that is already tested is no reason to fill the slot.
3. **Nothing qualifies** → `none: <token>` — `no-candidate` (no hotspot overlaps this sprint's
   work, or no change found that would make it easier, and no hotspot with a safety-net gap).

**Central-owned files — never (c).** A central-owned file is one `/gld update` refreshes from the plugin: the gate script and the two universal gate rules. 실행 중 변경은 커밋 게이트가 정보 경고로 알린다 (a staged `.claude/guild/gates/scripts/gate_precommit.py` / `rules/secrets.md` / `rules/verification.md` — the plan-time check below sees only the Issue body). A text names one when it holds:
- **`gate_precommit.py`** as a file-name token — the character before it is none of
  `[A-Za-z0-9_.-]` and it is not prefixed `test_`, and what follows is neither one of
  `[A-Za-z0-9_]` nor a `.` followed by one of `[A-Za-z0-9]`. So a sentence-final
  `gate_precommit.py.`, `gate_precommit.py를` and `gate_precommit.py` followed by `:` and a line
  number are it; `gate_precommit.py.bak`, `gate_precommit.pyc` and `test_gate_precommit.py` are
  not. When a path is attached in front (the run of characters back to a space, a backtick or a
  quote), it counts only when that path begins `.claude/guild/gates/` or `./.claude/guild/gates/`
  — `.claude/guild/gates/scripts/gate_precommit.py` and the short `.claude/guild/gates/gate_precommit.py`
  are it, a plugin source path such as `skills/gld/gates/gate_precommit.py` is not.
- **`secrets.md`, `verification.md`** — only with `gates/rules/` right in front
  (`gates/rules/verification.md`); `docs/standards/verification.md` is not one.
The next `/gld update` offers to overwrite a local change to the script (it asks to move the
change into `scripts/local/` only when it finds a new check), and the two rule files are
overwritten together with the script. So **do not propose (c) whose Files include a
central-owned file** — at any step, **a 2b included**: a 2b changes no production code itself,
but the refactor that follows it would fork that file. The leader rejects one that slips in
(the arbitration below). The same definition is what Phase 5's warning line on a member reads.

**The gap check** (every step 0–2b candidate). Budget: the ≤ ~3 hotspot files and their test
files, ≤ ~5 behaviors per file, ≤ ~3 commit diffs **in total**; a Grep with a few lines of
context is enough to tell an assertion from a mention. A fall-through to the next step reuses
what was already read. It is
**per behavior, not per file**: in a repo where every component has a colocated test, "is the
file imported by a test" is always yes and finds nothing, while the bugs keep coming. Two
sources name the behaviors, both from data you already have:
- **Fix commits that changed no runnable test** — for each hotspot file, the window's `fix:` commits that
  touched it (a commit whose only test change is in a file no runnable runner runs still counts as
  test-less; step 2's `git log … --name-only` output already lists each commit's files; for a
  step-0/1 candidate run that same call scoped to the Files' **directories**, not the files —
  scoped to the files alone, colocated tests never show and every fix looks test-less): a `fix:` commit whose file list has
  **no test path** fixed a behavior no test was made to hold. Read that commit's subject (and, if
  unclear, its diff of the hotspot file — at most ~3 commits) and name the behavior. Before
  counting it:
  - **Drop noise** by subject: reverts (including "removed X's change"-style subjects),
    renames/moves, lint/format/typo, and review-nit fixups ("review", "指摘", "리뷰 반영",
    "copilot") — they changed no behavior a test could hold.
  - **Collapse one branch's fixes** into one behavior: `fix:` commits from the same feature
    branch (the same PR number, the same subject stem, or — in a merge-commit repo — the same
    merge, visible with `--format='%h %p %s'`) are one fix, not several.
  - **Check it is still uncovered today** — Grep the file's current tests for an assertion on
    that behavior, the same as the second source: a later `test:` commit may have covered it
    (and a merged safety-net-only slot certainly did).
  What survives is a **test gap**, and the strongest evidence this check has.
- **Behaviors this sprint's members will lean on** — from (b)'s per-candidate files: the public
  functions / component states of the hotspot file those members call. One Grep per behavior
  name in the file's tests (an assertion that exercises it, not a mention): none → a test gap.
- ⚠ **Only an assertion Guild can run counts as coverage** — one in a file `commands.test`
  runs, or `commands.vrt` when `visual.runnable` is true. In a repo whose component tests run
  only through a visual runner Guild cannot run (Docker-only browser tests while
  `commands.test` is Jest), those assertions referee nothing during the refactor stage: count
  the behavior as a gap, and the net will pin it in a runnable file — **but only if it can be
  pinned there**: a behavior the runnable runner cannot exercise (placement under jsdom, a
  real layout measurement) is not a gap the net can fill — record it as a rule-4 finding
  (untestable here) for the human, outside the net and outside the Success-criteria.
- **Rank and cap**: keep the strongest gaps — fix-commit evidence first, then member-relied
  behaviors — **at most 5 net lines in all**, behavior and visual lines counted together; the rest are listed in **Why** as known gaps for a
  later slot. A net that alone would fail the size gate is too big: cut it, do not convert it.
- **Visual** — only when VISUAL is `available` and the file renders UI inside `visual.packages`:
  a screen/state from either list above that no `visual.tests` file captures → a **visual gap**.
  `unavailable` → no visual gap is ever recorded (an image Guild cannot render here is not a
  safety net) — say so in (c) so Phase 5 can tell the human the screen has no visual net.
No gap → no Safety net, and the slot is judged as before. A hotspot whose recent fixes all came
with tests needs no net.
- **Lint rules are not part of the slot.** A lint rule earns its place from repeated failures,
  and that route is `evolve`'s (fail-to-rule, human-approved). A rule added here would arrive
  without that evidence, and fixing its existing violations would bloat the one PR the slot
  costs.

Whichever step yields it, (c) states for the slot:
- **Files** — the source files the slot reshapes. For an existing Issue, derive them from its
  body and the code. The leader builds the slot's edges from this list and (b)'s per-candidate
  files (Phase 4); without it those edges are a guess.
- **Prepares** — the candidate numbers it makes easier, and how.
- **Readiness** — Goal / Constraint / Success-criteria each rated `clear` / `partial` /
  `unclear` (ASCII tokens), with one line on each rating below `clear`.
- **Safety net** — for any step, when the gap check found a gap: the section as specified for a
  draft below (lines, visual cases, test-support files, rules). For a step-0/1 slot this is what
  Phase 6 step 3 appends; without it there is nothing to append.

A draft for (2) also carries, all in `config.language` (tokens stay ASCII):
- **Title** — what is reshaped, and where.
- **Files** — as above, written into the Issue (Phase 6 step 0) so that a resumed slot and
  `retro` read the same list Phase 4 built edges from.
- **Why** — the evidence: path · `fix:` count in the window · what is hard about it today.
- **Goal / Constraint / Success-criteria** — `_readiness.md`'s three dimensions. Constraint
  always includes *"behavior unchanged — no test is weakened or deleted"* (INV2).
  Success-criteria must be checkable from the diff: existing tests stay green, plus one
  structural criterion (a named function extracted, a duplicate gone, a dependency cut).
  ⚠ *"Code is cleaner"* is not a criterion — it is the `unclear` that Phase 2 excludes.
- **Safety net** (only when the gap check found a gap; always for a 2b draft) — under a heading
  in `config.language` followed by the marker line `<!-- guild:safety-net -->` (never
  translated — `analyze` and `refactor` find the section by it): the behaviors to pin, one line
  each (`<file> · <public function or component state> · <what it must keep doing> · <evidence:
  fix commit / member #n>`), the visual cases (screen · state · theme · size) when there is a
  visual gap (each tagged `(safety net)` too, so design keeps the tag on its visual rows), and
  any **test-support files** the net needs (a test helper or fixture, named by path — the only
  non-test files the net's commit may touch). The net goes into **new test files of its own**,
  named so the runner still picks them up (a file the `commands.test` runner picks up — `index.safety-net.test.tsx` beside
  `index.test.tsx` under Jest, `foo_safety_net_test.dart`; a visual-runner file only for visual rows, and only when that runner is runnable here): the refactor stage freezes the net's files, and
  freezing an existing colocated test file would also freeze its older tests, which a refactor is
  allowed to adjust. **Each line is also a
  Success-criterion** (*"covered by a test that would fail if it broke"*) — that is what carries
  it into the AC, the design tester's cases and the test stage's coverage and vacuous-test
  checks; a net that lives only in its own section is checked by nobody.
  Rules that ride with it into the Issue, verbatim in `config.language`:
  1. *Added before the refactor, in their own commit, and green on the unchanged code* — that
     run is what proves they pin today's behavior rather than the new code's.
  2. *Public behavior only* — no private functions, no mocks of the file's own internals, no
     snapshot of internal structure. A test that pins implementation blocks the very refactor
     it was written to protect, and the next one.
  3. *Never pin a suspected bug* — a behavior that looks wrong is written into the Issue as a
     finding for the human, not frozen by a test.
  4. *Untestable without a seam* (a clock, a DOM measurement, a private constructor) — report
     it; do not write a test that passes without exercising it, and do not add the seam in the
     net's commit.
  Keep it small: the slot is one PR, and the size gate below counts the net with the refactor.
  When both together are ⚠ likely to split, keep the net and drop the refactor to a later
  sprint (the next slot then starts with the code already covered) — the draft becomes a 2b.
- A **2b draft** says so in its title and carries the `<!-- guild:safety-net-only -->` line
  beside `<!-- guild:refactor-slot -->`. Its Goal is the coverage; its Success-criteria are the
  Safety net lines covered, green on the unchanged code, and **no production file changed**
  (checkable from the diff: every changed path is a test, a visual baseline, a named
  test-support file or `docs/specs/`); it has no structural criterion. Its **Files** are the
  **production** hotspot file(s) the net covers — not the new tests: Phase 4 builds edges from
  Files, so members that change those files stack on the net instead of racing it, and `retro`
  records them as the slot's `paths`. A 2b runs only through `refactor.md` (it reads the
  marker): without `type:refactor` it would run as a feature, test-first, and lose both "green
  on the unchanged code" and "no production change" — so when the label is missing and the
  human declines creating it in Phase 5, the 2b is dropped (`skip (human-declined)`).
- When a step-2 draft is rejected at arbitration **only for size**, and its Safety net alone
  passes the size gate, the leader converts it to a 2b instead of skipping — no re-spawn: the
  net is already in the draft. Converting means rewriting it as a 2b, not relabelling: **Files**
  narrowed to the production files the net covers, the **Title** rewritten as a 2b (and
  `(로직만)` when it applies), the `<!-- guild:safety-net-only -->` marker added, **Prepares**
  reduced to the members whose files share a file with the narrowed Files (then the
  must-prepare check re-run on it — no member left → the re-spawn rule for drafts that prepare
  no member, below), Goal and
  Success-criteria rewritten per the 2b rules, and the readiness re-checked on those rewritten
  sections (all `clear`, or `skip (not-ready)`). The same conversion applies when the leader
  rejects a step-2 draft for readiness **only in its refactor sections** (the net's lines are
  clear). A size-only rejection with no net is `skip (not-ready)`. Record the dropped refactor in the 2b's **Why** (*"deferred: <the
  refactor's title>"*) so the next sprint's step 2 finds it again with the code covered.
- When VISUAL is `unavailable` and the 2b covers a file that renders UI, its title says
  `(로직만)` — the human approving a "safety net" for a screen should see that no picture of it
  is pinned.

⚠ **PAST SLOTS is a check, not a quota.** Each entry is `{issue, outcome, kind, paths, merged_at,
closed_at}` (`retro.md` Phase 4); an entry without `kind` (recorded before it existed) is a
`refactor`. Read `origin/<default-branch>` (fetched by the leader), not
the local checkout — a stale clone or a feature branch has no commits after the date and
answers *"no hits"* falsely. **Only `merged` and `refused` entries are checked**; ignore
`carryover` and `skip:*` entries (no paths, no date). One call per checked entry (substitute
the literal values):
```bash
git log origin/<default-branch> --since=<date> --oneline --grep='^fix[(:]' -i -- <paths>
```
(the same subject check as `scan_git.md` Step 1 — discard hits whose subject does not start
with `fix`).
- **`merged`** (`<date>` = `merged_at`) → do not propose the same `paths` again unless there are
  hits; then you may, and say so in (c) as a finding: the earlier refactor did not hold.
  ⚠ **An entry with `"kind": "safety-net-only"` is exempt from this exclusion**: it added
  coverage to those paths so that a refactor could follow — excluding them would block the very
  refactor it prepared. (A second 2b on the same paths is still stopped by the gap check: they
  are covered now.) Its fix hits are not "the refactor did not hold" — say "the net did not
  catch it" instead.
- **`refused`** (`<date>` = `closed_at`) → the human closed that slot's PR. Do not propose the
  same `paths` again unless there are hits, or a candidate this sprint needs the change; name
  that evidence in (c). A refused `"kind": "safety-net-only"` entry blocks only another
  safety-net-only slot on those paths — the human rejected that coverage, not a refactor of them.
- An entry whose `paths` key or date key is **absent** (a slot recorded before these fields
  existed) gives no basis either way — ignore it rather than guessing. A `null` date is not
  absence: `merged_at` is `null` on every `refused` entry by design.

**The leader's arbitration of (c)** — the slot gets **no exemption** from the gates every
other member passes, and its readiness gate is **stricter**: all three dimensions `clear`, where
a feature member may carry a `partial`. An optional member has no reason to carry a gap that
unattended the leader would have to guess alone:
- any readiness dimension below `clear` → do not take it. For a **draft** record
  `skip (not-ready)`; a step-0 or step-1 pick goes to the re-spawn bullet below instead.
- size ⚠ **likely to split** (not for a candidate at `guild:execute` or later — its ⚠ is
  ignored, as in the fill, Phase 2) → the same: a draft records `skip (not-ready)` — **unless** it
  carries a Safety net that alone passes the size gate, in which case it is converted to a 2b
  (the Safety net bullets in the Refactor slot section; the same conversion applies to a
  readiness rejection confined to the refactor's own sections) — and a step-0 or step-1 pick
  goes to the re-spawn.
- **Files that include a central-owned file** (*Central-owned files*, above) → do not take it,
  and never convert it to a 2b. A step-0 or step-1 pick goes to the re-spawn bullet below; a
  step-2 draft records `skip (not-ready)` with no re-spawn; a re-spawned final attempt rejected
  for it records `skip (not-ready)` too. The tracker token stays `skip (not-ready)`; **only when
  the slot ends for this reason** (the final `skip (not-ready)` came from a central-owned file)
  does Phase 5's slot line end with `(중앙 관리 파일)` — a re-spawn that brings back a normal slot
  shows no tail. A step-1 pick rejected for it that goes back to the feature picks (below) is a
  member like any other, and Phase 5's central-owned-file warning line applies to it.
- ⚠ **A new draft was never in the product-owner's CANDIDATES**, so its readiness comes from
  the tech-lead's own **Readiness** ratings in (c). Re-read the draft's Success-criteria
  yourself before accepting a `clear` — the author of a draft is the one reader least likely to
  see its gap. For an existing Issue (step 1), the product-owner's ratings and the
  tech-lead's must both be `clear` — a candidate with no product-owner rating (left out of
  `CANDIDATES (product-owner)`) is not `clear`; a resumed slot (step 0) is judged as a draft.
- ⚠ **The slot must prepare this sprint's work.** The tech-lead chose it from the whole
  candidate set, in parallel with the product-owner, so it cannot know which candidates
  become members. Once the Phase 3 fill is done (whether or not it cut anything), require that
  **Prepares** names at least one selected feature member, or that its **Files** share a file
  with one. Neither → it pays down code nobody in this sprint touches; reject it (next
  bullet). Re-check this after **any** change to the feature set — the Phase 3 capacity cut, a
  Phase 3 refill, a Phase 4 cut, a Phase 5 edit.
- ⚠ **A slot never touches an epic member.** Phase 4 adds the slot to the `deps` of every
  member sharing a file with it, and that edge cannot be deleted (Phase 4) — on an epic it makes
  the epic downstream of the slot and breaks the epic's independence (Phase 3, *Epics*; measured:
  the slot's Files were `schedule_engine.dart`, and #459's and #146's children touch the same
  file). So **reject a slot whose Files overlap an epic member's files** (Phase 1 — the union
  of its remaining children's, a directory overlapping every file under it) **or whose Prepares
  names an epic member** — the slot yields, it never costs a feature member its place. It goes
  to the re-spawn (next bullet) with *"do not touch the epic members' files"* added; rejected
  for this again → `skip (epic-overlap)`. Re-check with the other prepares checks, after any
  change to the feature set.
- ⚠ **Rejecting a pick does not empty the slot — one re-spawn.** A rejected step-0 or step-1
  pick, or a draft rejected **only** because it prepares no selected member (the draft was
  aimed at the whole candidate set; a hotspot under the actual members may well exist), gets
  **one** re-spawn per `plan` run, and it always runs **after the Phase 3 fill is done (whether
  or not it cut anything)** — a readiness or size rejection made during Phase 2 waits until
  then, so the re-spawn gets the real member list. Spawn the tech-lead once more,
  asking for **(c) only**, with **the slot re-spawn prompt** (after this list — its inputs are
  listed there once). It writes `deps-slot.md`, leaving
  `deps.md`'s (a)/(b) untouched; from then on Phase 4 reads the slot's **Files** and
  **Prepares** from `deps-slot.md`. Arbitrate that (c) the same way; if it is
  rejected too, or comes back `none`, the slot ends in a `skip` keyed on the **final**
  attempt's reason — `skip (no-candidate)` when it prepares no member or came back `none`,
  `skip (not-ready)` when it failed readiness or size or its Files include a central-owned file,
  `skip (epic-overlap)` when it overlaps
  an epic member. A draft rejected for readiness or
  size ends in `skip (not-ready)` without a re-spawn (or, for size — or readiness confined to
  its refactor sections — with a net that fits, as a 2b, above). A **converted** 2b left
  preparing no member is a draft rejected only for not preparing one: it gets the re-spawn like
  any such draft — unless the re-spawn is already spent, then `skip (no-candidate)` — and
  `skip (no-candidate)` if that also comes back empty.
  From then on Phase 5's evidence lines and Phase 6 step 0's Issue body also come from
  `deps-slot.md`.
- ⚠ **A rejected pick the product-owner ranked as a feature goes back to the feature picks**
  (the goal-picks or the other-ranked list, wherever the product-owner put it)
  at its product-owner rank and competes under the feature gates (a `partial` is allowed
  there). Rejecting it as the slot is not rejecting it as work the product-owner wanted. Redo
  the Phase 3 fill with it at that rank — if the sprint then holds more than capacity, drop
  members in reverse fill order (lowest other-ranked first, then lowest goal pick); the sprint
  never holds more than capacity. The same applies when the human drops such a slot in Phase 5
  (`skip (human-declined)` removes its slot role, not the Issue), unless the human drops the
  Issue itself.
- otherwise it is a member, tagged `🧹 리팩토링 슬롯` in the member table. A draft is **not
  created** here — Phase 6 step 0 creates it, after the human approves.
- ⚠ **One Issue, one role.** A `refactor` or `refactor-slot` candidate the product-owner also
  ranked as a feature pick is the slot, not both — remove it from the feature picks, or the sprint holds
  one fewer member than the capacity reasoning says.

**The slot re-spawn** (tech-lead, (c) only — the one re-spawn above). Pass the rejected numbers, not *"step 1 is exhausted"*: another
existing `refactor` Issue may still qualify. A rejected draft has no number — name it by its
title: *"exclude the draft «<title>»"*. Write the epic sentence only when epic members are
selected; otherwise leave it out.
- `subagent_type`: `general-purpose`, `model`: the role file's `model:` frontmatter (`_model_tiering.md` Section 0 — `sonnet` when absent), `description`: `tech-lead sprint slot re-spawn`
- `prompt`:
  > Adopt the persona in `.claude/agents/tech-lead.md`. This is a second request, for the sprint's refactor slot only: produce **(c) only** — one refactor-slot proposal (rules: the "Refactor slot" section of `<<SKILL_DIR>>/commands/sprint/plan.md` — read that section before writing (c), not the whole file); do not redo (a) or (b). Exclude <#n[, #m] | the draft «<title>»>; continue the search order from where those were; draft against the selected feature members' files. <only when epic members are selected: Do not touch the epic members' files: <their files>.> Judge from the bodies: run the BODIES command yourself and read its output to the end (Read's `offset`/`limit` when it is moved to a file); a `closed-not-done` child's body via `gh issue view <c> --json body` — **except one marked `(머지됨 — run 이 정리)`: do not read it, do not size it, and do not count it in `epic ×<k>`** (its work is already merged; `run` only cleans it up). Your first answer's (b) per-candidate files are in `docs/specs/sprint-draft/deps.md` — read them as step 2's input, and do not edit that file. Write (c) to a FILE `docs/specs/sprint-draft/deps-slot.md`. Return one `>>> RESULT <<<` line. CANDIDATES (tech-lead): <the same entries as the first spawn — tags and `slot:` fields included>. BODIES: <same as the first spawn>. REFACTOR SLOT: on. DEFAULT BRANCH: <same as the first spawn>. PAST SLOTS: <same as the first spawn>. VISUAL: <same as the first spawn>. SELECTED FEATURE MEMBERS: <number · title · files from (b) of each feature member the Phase 3 fill selected>. <`_handoff.md` Section K's language line, rendered in `config.language` — the same line as the product-owner's> Write output in `config.language`.

Collect both RESULTs and **arbitrate as the leader** into one candidate set plus a dependency edge list.

⚠ **A `⚠ likely to split` candidate is excluded by strong default** (the Phase 3 fill keeps this gate as it is). A split that happens *during* the run is handed back to the human (`run.md`), so the sprint stops on that issue. Include one only if the human overrides after being told this.
**Except at `guild:execute` or later**: design does not run on it again, so it cannot split — the tech-lead's ⚠ is ignored and it counts as ✅ (the same stage exemption as a `depends:` size, Phase 3; the slot's size bar applies it too).
**`⚠ depends: …` is read as `depends:`** (an ordinary candidate or a child): the tech-lead's judgment that a decision settles the size is the substance, and the ⚠ in front only repeats "⚠ until it is decided". **Mixed** is only a verdict with a **split rationale written between the ⚠ and the `depends:`** (measured #503: *"⚠ (감시 틱+정지 / 이력 모델 / …) depends: …"*) — ⚠ whatever the decision — and it counts as ⚠ (the strong default above, an ordinary candidate's too).
**An epic's size is `epic ×<k>`, judged per child to be sized** (Phase 1 — the remaining
children at `guild:design` or earlier; one at `guild:execute` or later counts as ✅). A child cannot be split again
(leaf-only — `_handoff.md` Section I, `dev.md` Phase 2b): a child whose design tries to split it
stops the whole epic at `needs-human` on that child. So **an epic with any ⚠ child to be sized is excluded
by the same strong default** — Phase 5 `제외: #e (에픽 · 자식 #c 분할 예상)`; a mixed child (above) counts as ⚠, a `⚠ depends:` child as `depends:`. **An epic passes the size gate only when every child to be sized is ✅** — wherever the fill says "size ✅", an epic needs
`epic ×<k>` with every child to be sized ✅. A child sized `depends:` is **not** ✅ and is never
asked about (an epic and its children are never a question's subject — Phase 3: a decision
written into a non-member child's body is missed by every member-keyed read — Phase 0's missing
count, `run`'s plan-decisions check, the Idempotency repair), so the epic is not filled:
`제외: #e (에픽 · 자식 #c 결정 필요 — 그 자식 Issue 에서 정해 주세요)` for a child at
`guild:analyze` or earlier, `제외: #e (에픽 · 자식 #c 결정 필요 — 다음 design 에서 정하거나 재범위)`
for a `guild:design` child (an answer in its body no longer reaches its acceptance criteria);
a child to be sized that the tech-lead gave no verdict → `제외: #e (에픽 · 자식 #c 크기 판정 없음)`. An epic with only some
children startable is not filled either — partial progress is separate work (`run` stops on the
child that stops).

## Phase 3 — Capacity and fill (the capacity number is not asked; attended, the decision questions add supply)

| Input | Source |
|---|---|
| capacity `C` | `config.json` → `sprint.capacity` (written by `retro`) |
| past sizes (shown, never used to shrink `C`) | `config.json` → `sprint.history[].planned` |
| size per candidate | tech-lead |
| dependency chain depth | `sprint_dag.py --mode depth` (Phase 4) |
| readiness + decision drafts | the product-owner's `## readiness` and `## questions` |
| goal / other ranking | the product-owner's `## goal-picks` and `## other-ranked` |
| ready vs needs refinement | Phase 1b |
| refactor slot | Phase 2's arbitration of (c) |

**`C` is the target, not a ceiling to argue under.** `C` = `config.sprint.capacity`. No capacity
yet (first sprint) → **be conservative**: use `C` = 5 for the fill below (same order, same gates,
same questions — an answered candidate counts as having no `unclear` dimension), with a chain
depth within the cap, and write `- capacity: n/a` (there was no configured number to fill
against). ⚠ **Never shrink `C` from history.** A history entry whose `planned`
equals its `merged` with no carryover measured the *supply* that sprint had, not the human's
review throughput — reading "the last sprints were all about 3" as "capacity is about 3" planned
3 because 3 were ready, merged 3, and fed the next plan the same number. Fewer members than `C`
happen only for a reason recorded as `shortfall` (Phase 6 template): `supply` (no candidate left
that passes the gates), `depth` (Phase 4's cut), `human-cut` (the human set a size in Phase 5).
Changing `C` itself is `retro`'s job (Phase 4 there), nowhere else.

**Fill — in this order, each list in its product-owner rank, while seats remain:**
1. **goal-picks** — the feature gates as before: no `unclear` dimension; size ✅ — for an epic,
   `epic ×<k>` with every child to be sized ✅ (Phase 1; `depends:` and mixed verdicts are not ✅ — Phase 2)
   (a `⚠ likely to split` candidate is excluded by strong default, below — not at `guild:execute`
   or later, where its ⚠ is ignored; a mixed verdict counts as ⚠, a `⚠ depends:` one as
   `depends:` — Phase 2; an epic with any child to be sized
   not ✅ likewise — Phase 2); a `depends:` size settled by an answer or by its stage (*A size
   that depends on the answer*, below); the slot rules; dependencies as the
   tech-lead's edges; an epic also under *Epics in the fill* (below). **A candidate already past analyze** (`guild:design` or later — typically a
   carried-over member) is not held to the readiness gate: analyze already settled its
   acceptance criteria, which is what readiness protects; Phase 5 shows it as
   `이월(<stage>)`. ⚠ **Not an epic**: `guild:children` has no stage ordinal (`_handoff.md`
   Section A) and its remaining children are usually still at analyze, so an epic is held
   to the readiness gate — **unless it has no child to be decided** (Phase 1: every remaining
   child is past analyze) → exempt, Phase 5 `이월(에픽 · 자식 모두 <stage> 이후)`. **Plus two gates the fill now has to state, because the leader no longer
   picks by judgment:** the candidate is **착수 가능 in Phase 1b, or 구체화 필요 past analyze** (one 1b reported as
   구체화 필요 **at stage `none` or `guild:analyze`** is never filled automatically, whatever the
   product-owner rated — 1b's own definition is "handed to `dev` today it ends at `needs-human`";
   **later than analyze** (`guild:design` or after — a carry-over) 구체화 필요 is not a gate, for
   the reason and at the bound of the readiness exemption above: an answer in the body no longer
   reaches the acceptance criteria, and *Who is asked about* never reaches it, so as a gate it
   would keep the candidate out for good; one reported as **막힘** is never filled either,
   whatever its stage — Phase 5 `사람 작업 필요: #n (<credential|device|upstream|other>)`), and it does **not** carry
   `guild:needs-human` (the supervisor treats that label as terminal and blocks everything stacked
   on it — `sprint-supervisor.sh`, `sprint_dag.py` `TERMINAL_BLOCKING`; list it under
   `사람 작업 필요` instead).
   This list is the gates, not the order of Phase 5's reason lines: a candidate not taken gets
   **one** line, by the order of reasons defined below (*Phase 5 order of reasons — one line per
   epic* in *Epics in the fill*; *Phase 5 order of reasons — ordinary candidates* right after it).
2. **Decision questions for goal-related candidates** — attended and not `--no-ask` only (below).
3. **other-ranked** — the same gates.
4. **Decision questions for the other candidates** — attended and not `--no-ask` only.

A candidate whose questions the human answered passes the 1b gate as well — the answer is the
refinement 1b asked for; that is what Phase 5's `이번에 답해 담았습니다` reports. **Only a
구체화 필요 one**: 막힘 is not cleared by an answer (what blocks it is a credential, a device or
another repository, not a decision). **Only the answer to a product-owner `Q:`** clears 1b — the
answer to a leader-drafted size question (below) settles the size, never a 1b verdict reached
for another reason.
When a seat cannot be filled, the seat stays empty and the reason is the `shortfall`. A 1b
구체화 필요 candidate at stage `none` or `guild:analyze` not asked about (no `unclear` dimension, so no question to ask — or the
questions did not reach it) is listed in Phase 5 as
`제외: #n (구체화 필요 — 1b)` and goes no further (② of *Phase 5 order of reasons — ordinary candidates*).

**Decision questions (steps 2 and 4).** The point: an `unclear` candidate is not unready
forever — it is waiting on one answer from the person who is right here.
- **Already decided**: a candidate whose body (Phase 1 read it) already holds a
  `<!-- guild:plan-decision -->` line — a decision made in an earlier sprint plan, for a member
  that carried over — has that question settled: it is never asked again (`analyze.md` Step 1
  reads the same block). Pass those lines to the product-owner in CANDIDATES (`decided: …`); a
  gap the block does not answer is rated and drafted as usual.
- **Who is asked about**: a candidate of that step's list whose every remaining `unclear`
  dimension has a drafted question (not `human-work`) — or one that gets a leader-drafted size
  question (*A size question the leader drafts*, below) — that does not carry `guild:needs-human`, whose stage is
  `none` or `guild:analyze` (later than analyze, an answer in the body can no longer reach the
  acceptance criteria analyze already wrote), that the human has not dropped this session, and
  that would actually be taken once answered — size ✅, or ✅ under some answer (a `depends:`
  size, below), not a `refactor-slot`-tagged candidate
  and not this sprint's slot (One Issue, one role), and not dependent on an epic already filled
  (rule (ii) below would leave it out whatever the answer — a question whose outcome is already
  settled is not asked). **Never an epic, nor an epic's child**: an epic's stage is
  `guild:children` (not none/analyze), and an answer written into the epic's body is not read by
  its children's analyze; a child is not a member, and every read of a recorded decision is keyed
  on members (Phase 2, the epic's size). An epic whose child needs a decision (the
  product-owner's `decide-in: #c` on a child to be decided, or a child to be sized the tech-lead
  sized `depends:` — Phase 1's bounds) is Phase 5
  `제외: #e (에픽 · 자식 #c 결정 필요 — 그 자식 Issue 에서 정해 주세요)` (a `guild:design` child:
  `… — 다음 design 에서 정하거나 재범위)`, Phase 2); an `unclear` epic with no
  `decide-in` is `제외: #e (에픽 · 구체화 필요 — 자식 <#c|결정할 자식 전체> 본문을 구체화하세요)`
  (one line per epic — *Epics in the fill*, the order of reasons).
  No more candidates than seats remain, in rank order.
  **A `prerequisite: #d` dimension is not asked** — an unfinished prerequisite Issue is not
  human work and no answer settles it: Phase 5 shows it as `선행 대기: #n ← #d(이번 스프린트)`
  when `#d` is a member of this sprint and as `선행 대기(미포함): #n ← #d` otherwise (not
  `사람 작업 필요`; and not the members' `⚠ 선행 미포함:` warning either). The leader reads
  `prerequisite:` in both places the product-owner writes it — a `## questions` entry, and an
  epic's readiness `note`.
- **How**: `AskUserQuestion`, one candidate's questions together (at most three — one per
  dimension), at most four questions per call. Each question is `#<n> <title> — <question>`, its
  options the product-owner's drafts — or, for a leader-drafted size question, the tech-lead's
  conditions (below) — (at most three — an option that leads to a ⚠ size under a
  `depends:` verdict carries `(이 답이면 이번 스프린트에서 빠집니다)` in its label, so the human
  knows before choosing) and, **always last, a skip option**
  (labelled in `config.language`; judged by being the last option, never by its text). A
  free-text answer counts as an answer.
  **The recommended option** — the product-owner's option carrying `(recommended)`, written
  first — is asked first, its label ending in `(권장)` (rendered in `config.language`) and its
  reason as the option's description (`AskUserQuestion`'s recommended-first convention). When it
  is also an option that leads to a ⚠ size, its label carries both —
  `(권장) (이 답이면 이번 스프린트에서 빠집니다)`; the leader never drops the warning. A draft
  with no recommended option is asked as it is — the leader does not pick one. A leader-drafted
  size question (below) has no recommendation: it is not a product judgment — the ✅ side first,
  then the ⚠ side.
  **The `<answer>`** every record and display uses — the decision lines (Phase 6 steps 2 and 3),
  Phase 5's `계획 중 결정:` line and the member table's 비고 — is the chosen option's wording
  with its tags removed: `(recommended)` together with the `— <reason>` right after it (only there — a ` — ` elsewhere in an option is its wording), `(권장)` and `(이 답이면 …)`. The preamble says it plainly: *answered candidates join
  this sprint if they pass the selection gates, and the decision is written into the Issue when
  the sprint is created; skipped ones are not taken.*
- **Then**: all of a candidate's questions answered (none skipped) → treat those dimensions as
  `clear (계획 중 결정)` for selection and offer it to that step's fill at its rank; any skipped →
  not taken. Answered candidates that end up outside the sprint (Phase 4 cut, slot
  re-arbitration, a Phase 5 edit) are shown as `결정했지만 제외: #a (<reason>) — 답은 기록되지
  않습니다`.
- **A size that depends on the answer** (`depends: <option>→✅, <option>→⚠` — the tech-lead
  wrote which decision makes it ✅ in plain words; the tech-lead does not read `po.md`, so the
  leader maps that onto the product-owner's options here, in Phase 3). After the answer the size
  is settled — the mapping reads the option's wording with its tags removed (`(recommended)` and
  the `— <reason>` right after it, `(권장)`, `(이 답이면 …)`): an answer that maps to ✅ → ✅; one that maps to ⚠, a free-text answer, or one that
  cannot be mapped → ⚠, and the candidate is not taken — `결정했지만 제외: #n (답 <X> → 분할 예상)` (the decision is not recorded — only final members get it).
  **An option maps to ✅ only when its wording explicitly meets the tech-lead's ✅ condition**; one
  that takes any interpretation to get there → ⚠ (measured #555: whether option A met the
  condition was left to the leader's reading).
  **The size reasons below and `⚠ 분할 예상` are given only to a candidate the fill's walk
  actually judges** — a ranked one (goal-picks or other-ranked) that passed the gates ahead of
  size in the order of reasons (*Phase 5 order of reasons — ordinary candidates*): a not-ranked
  candidate gets its PO line, a 막힘 or `guild:needs-human` one its `사람 작업 필요` line, never a
  size line as well.
  **A `depends:` size that no question settles** (no mapping `Q:`, no size question) — **its
  stage first**: later than `guild:design` (`guild:execute` or after) → design can no longer split
  it, so the tech-lead's size and its `depends:` are ignored and it counts as ✅; `guild:design` →
  an answer in the body no longer reaches its acceptance criteria (the readiness exemption above),
  attended or not: Phase 5 `제외: #n (크기가 결정에 달림 — <tech-lead 의 조건> — 다음 design 에서 정하거나 재범위)`;
  otherwise (unattended, `--no-ask`, the question skipped, or outside the conditions below) →
  `제외: #n (크기가 결정에 달림 — <tech-lead 의 조건> — Issue 에서 정해 주세요)`.
- **A size question the leader drafts** — for an ordinary candidate (never an epic or an epic's
  child) sized `depends:` whose decision no product-owner `Q:` puts to the human, even when every
  dimension is `clear` or `partial`. The leader writes it from the tech-lead's condition: the
  question is the decision the tech-lead named; the options are **one on the condition's ✅ side
  and one on its ⚠ side** (three at most; measured #558 *"A 또는 C → ✅ / D 나 B → ⚠"* is two
  options), the ⚠ one labelled `(이 답이면 이번 스프린트에서 빠집니다)`, then the skip option; the
  dimension key is **`Constraint`** (a decision that narrows the scope — the plan-decision line's
  `<Goal|Constraint|Success>`, no new token; `analyze` reads it). Its options are the tech-lead's
  conditions, so the mapping is direct. Drafted only when **all** of these hold:
  - the candidate is in goal-picks or other-ranked (never not-ranked — the product-owner's
    judgment is not overturned), and is 1b **착수 가능** — or 1b 구체화 필요 **with a
    product-owner `Q:` asked together** (that `Q:`'s answer is what clears 1b); a 구체화 필요 or
    막힘 candidate with no product-owner `Q:` gets no size question;
  - `## questions` holds no `human-work:` or `prerequisite:` for it;
  - it passes *Who is asked about* (stage `none`/`guild:analyze`, no `guild:needs-human`, not
    the slot nor `refactor-slot`-tagged, not dependent on a filled epic, not dropped);
  - its body holds no `Constraint:` decided line — an earlier plan's decision; one line per key,
    never rewritten (`_handoff.md`'s plan-decision row, Phase 6 step 3), so a new answer would not
    be recorded → instead `제외: #n (결정 줄이 있는데도 크기 미정 — 재범위 필요: <tech-lead 의 조건>)`;
  - **no product-owner `Q:` for it maps** onto the tech-lead's condition — *maps* = at least one
    of its options explicitly meets the ✅ condition, **whatever its dimension** (measured #555: a
    `Success` question whose A/B/C are the tech-lead's conditions). One that maps → the path
    above; the same choice is never asked twice;
  - the product-owner wrote no `Constraint` `Q:` for it (one decision line per key; "one per
    dimension" above) → instead `제외: #n (크기가 결정에 달림 — <tech-lead 의 조건> — Issue 에서 정해 주세요)`.
  It is asked together with the candidate's product-owner `Q:`s, if any, at the candidate's own
  place in steps 2 and 4 (the same rank order and seat limit), and the size comes from its answer
  alone; a product-owner answer that contradicts it (one implying the tech-lead's ⚠ side) → ⚠.
  Measured: #558 *"훅만 손봄(A/C)이면 ✅"*, #377 *"스킬 목록 행 한정이면 ✅"*.
- **Nothing is written now.** The answers live in this session until Phase 6 writes them — into
  the final members only. A dry-run that ends here loses them; Phase 5 says so.
- Unattended or `--no-ask`: steps 2 and 4 do not run.

**Epics in the fill** (a `guild:children` candidate — Phase 1's `remaining`, `blocked_children`
and extended dependency floor; the epic takes **one seat**). Applied, deterministically, when
the fill's walk reaches the epic:
- **`blocked_children` present → not filled automatically**: `run` would stop on that child at
  `needs-human`. Phase 5 `사람 작업 필요: #e (자식 #c needs-human 대기 — /gld resume c)`.
  (Phase 2 already left such an epic out of the product-owner's list.)
- **Every child to be sized ✅** (Phase 2, the epic's size — a child at `guild:execute` or later
  is ✅ by its stage; only the children to be sized, Phase 1, are read) — a ⚠ or mixed child → `제외: #e (에픽 ·
  자식 #c 분할 예상)`; a `depends:` child → `제외: #e (에픽 · 자식 #c 결정 필요 — 그 자식 Issue 에서
  정해 주세요)` (a `guild:design` child: `… — 다음 design 에서 정하거나 재범위)`; never asked — *Who is asked about*); a child with no verdict → `제외: #e (에픽 · 자식 #c
  크기 판정 없음)`. Only an epic whose children to be sized are **all** ✅ is filled automatically.
- **The epic's extended dependency** = Phase 1's floor ∪ what the tech-lead's (a) added for it
  (a correction only adds), with Phase 1's child mapping applied (a child target that is closed or
  `guild:done` counts as itself, any other as its epic).
- **(i) Every extended-dependency target is closed or `guild:done`.** One still open → the epic
  is not filled, whether that target is a member or not: `선행 대기: #e ← #d(이번 스프린트)`
  when `#d` is a member, `선행 대기(미포함): #e ← #d` otherwise. **The mapping is shown on the
  target side only**: a dependency that reached target epic `#d` through its children →
  `선행 대기(미포함): #e ← #d(자식 #c…)`; the body naming `#d` itself → plain `#e ← #d`; both →
  `선행 대기(미포함): #e ← #d(+자식 #c…)`; a member target carries both brackets in that order —
  `선행 대기: #e ← #d(자식 #c…)(이번 스프린트)`. Where the dependency came from on the depending side
  (the epic's own body or one of its children) is not shown — one bracket, one meaning. A target that is `guild:done` but still open
  (not yet merged — `_handoff.md` Section D; measured #530·#531) passes (i), and Phase 5's
  `⚠ 선행 미포함` covers the epic's extended dependency too (its children start from the default
  branch without that code) — the same notation: `⚠ 선행 미포함: #q ← #d(자식 #c…)`. A chain (measured
  #154→#158→#159, #146→#161→#164) drops to its tail by this alone — #158 waits on the open #154,
  #159 on the open #158 — whatever the product-owner noted. An epic depending on another member
  is covered here too (members are open).
- **(ii) The fill order (rank) wins — a member already filled is never pushed out.** When the
  epic's turn comes and a member `q` already filled depends on the epic (by the mapping above)
  → the epic is not filled: `제외: #e (하류 멤버 #q 가 먼저 담김)`. When `q`'s turn comes after
  the epic is filled and `q` depends on it → `q` is not filled: `제외: #q (선행 에픽 #e 와 같은 스프린트에 쌓을 수 없음)`. The slot's refill (below) and Phase 5's drop refill follow the same
  rule — they skip, they never push out.
- **(iii) Independent inside the sprint** — an epic is taken only when it neither depends on
  another member nor is depended on by one. (i)–(ii) settle that during the fill; the re-check
  covers only what a later graph change makes: **Phase 4's final graph** (slot edges, linearize)
  and **Phase 5's leader refills**. The reason: with a split parent as a base, `sprint_dag.py`
  `resolve_base` gives `DEFAULT`, so the downstream member starts without the children's code;
  with the epic downstream, its children inherit the parent's `GLD_SPRINT_BASE` (`run.md`) and
  stack outside `sprint sync` (which syncs member PRs only — `stack_sync.py`). The epic ends up
  downstream in the final graph → `제외: #e (에픽 — 스프린트 안 의존 있음)`; upstream → drop
  the downstream member as in (ii). **A human's Phase 5 edit** (add, drop) that breaks the
  independence is **not** undone automatically — warn by direction and ask (the "a human add gets a
  warning, not the gate" rule of Phase 5's Edits): `q` depends on the epic → `⚠ #q 는 에픽 #e 에 의존합니다 — 에픽은 자기 PR 이 없어 #q 는 기본 브랜치에서 시작합니다(자식 코드 없이). 그대로 둘까요?`; the epic depends on `q` → `⚠ 에픽 #e 가 #q 에 의존합니다 — 자식 PR 들이 #q 의 브랜치 위에 쌓이고 sprint sync 대상이 아닙니다. 그대로 둘까요?`.
- **Phase 5 order of reasons — one line per epic** (an ordinary candidate gets one line too, in
  its own order — *Phase 5 order of reasons — ordinary candidates*, after this list; an epic's
  not-ranked PO line is shown only when none of these applies — Phase 5). When several apply (measured #164·#159: an epic, Constraint `unclear` from an
  unfinished epic before it, and `human-work: upstream` all at once), only the first is shown:
  ⓪ the child list cut at 500 → `제외: #e (에픽 · 자식 목록이 500건에서 잘려 판정 불가)` (Phase 1)
  ① human work — `blocked_children` → `사람 작업 필요: #e (자식 #c needs-human 대기 — /gld resume c)`,
  1b 막힘 → `사람 작업 필요: #e (<class>)` — first, so what only a human can clear is never hidden
  behind another reason
  ② an open prerequisite → `선행 대기…`, decided by (i) — never by the product-owner's note
  ③ a child's reason — only about a child Phase 1's bounds judge for it (children to be sized,
  children to be decided) — in this order: split expected `제외: #e (에픽 · 자식 #c 분할 예상)` > a
  decision needed (the product-owner's `decide-in: #c` on a child to be decided, or a tech-lead
  `depends:` child to be sized)
  `제외: #e (에픽 · 자식 #c 결정 필요 — 그 자식 Issue 에서 정해 주세요)` (a `guild:design` child:
  `… — 다음 design 에서 정하거나 재범위)`) > no verdict
  `제외: #e (에픽 · 자식 #c 크기 판정 없음)`
  ④ 1b 구체화 필요, or a readiness `unclear` with no `decide-in` — both from the children to be
  decided only (an epic with none is exempt from readiness — Phase 3 step 1) →
  `제외: #e (에픽 · 구체화 필요 — 자식 <#c|결정할 자식 전체> 본문을 구체화하세요)` — not `/gld plan`:
  on an already-split epic it only adds the children it lacks (Phase 1b)
  ⑤ (ii)–(iii).
  **A barrier hidden behind ②** — an epic out as `선행 대기` whose ③ (a child's split expected
  or decision needed) or ④ (구체화 필요) also applies — is shown on a **separate line**, so the
  next sprint does not meet it for the first time once the prerequisite clears:
  `그 뒤의 장벽: #e(자식 #c 결정 필요, #c2 분할 예상) · #e2(…)` — the words in the bracket are
  ③'s and ④'s own: `자식 #c 분할 예상`, `자식 #c 결정 필요`, `자식 #c 크기 판정 없음`, `구체화 필요` — only about a child Phase 1's bounds judge (a child to be sized, or one to be decided). Not in brackets on the
  `선행 대기` line, which joins several epics with `·`.
- **Shown in Phase 5** as `#e (에픽 · 남은 자식 k개 — PR 최대 k개)`. **k ≥ 10** → add
  `⚠ #e 는 남은 자식 <k>개 — 한 run 안에 끝나지 않을 수 있습니다` (the supervisor's split
  progress bound, `SPLIT_PASSES ≤ 12` — past it the member is `split-stalled`, INCOMPLETE).
  A limit, stated: children's PRs may stack on each other (measured #146: #554's base is #553's
  branch), are not `sprint sync` targets, and do not pass through `max_stack_depth` (measured
  #158, k = 11) — when 상한 근거 is `squash-sync` or `merge-commit-forbidden`, add
  `⚠ #e 의 자식 PR 은 서로 쌓일 수 있고 sprint sync 대상이 아닙니다`. A child whose design tries to
  split again goes to needs-human (leaf-only, `_handoff.md` Section I) — `run` stops on it: when
  it is the smallest outstanding child, the supervisor pauses the epic (`#e (child #c)`, no
  re-try, not `split-stalled`) and its dependants wait as `dep-needs-human` (Phase 5's Add warning).
  `retro` and `daily` count an epic as one seat, merged when it is `guild:done` and all its children are merged (`daily.md` step 6).
  Known limit: `run`'s `children_pending`, `dev` Phase 2b and the other child-discovery reads
  (`_handoff.md` Section I, `status.md`) still read `--limit 200`; in a repo with more
  than 200 `guild:child` Issues they can see fewer children than this plan's 500 — separate work.
  (`daily` and `retro` read `--label guild:child --limit 500`, as Phase 1 does.)

**Phase 5 order of reasons — ordinary candidates: one line each, the first gate it failed.** An
ordinary candidate (not an epic) the sprint does not take gets **one** reason line — the first of
these that applies, in this order (defined here; it is not the order in which Phase 3 step 1
lists the gates):
① human work — 1b 막힘 `사람 작업 필요: #n (<class>)`, the product-owner's `human-work:`
  `사람 작업 필요: #n (<class> · PO 판단, 1b 는 <착수 가능|구체화 필요>)`, `guild:needs-human`
  `사람 작업 필요: #n (needs-human 대기 — /gld resume n)`
② 1b 구체화 필요 at stage `none` or `guild:analyze` **not asked about** — `제외: #n (구체화 필요 — 1b)`
  (later than analyze it is no gate — Phase 3 step 1; one asked and skipped is ⑥'s
  `건너뜀`; Phase 1b's `앞서 구체화 필요로 보고한 #n …` line is a follow-up to the 1b report, not a
  reason line)
③ an open prerequisite — `선행 대기…` (`prerequisite:`) — ahead of not-ranked even for a
  not-ranked candidate, so that the `satisfied` `의견:` line (shown only for a candidate out as
  `선행 대기`) still appears
④ not-ranked — `제외: #n (PO: <사유>)`
⑤ size ⚠ — `제외: #n (⚠ 분할 예상)`
⑥ readiness — asked and skipped `제외: #n (<dim>=unclear · 건너뜀)`; not asked for any other
  reason (unattended, `--no-ask`, no seat left for the question, a draft the product-owner did not
  write …) `제외: #n (<dim>=unclear · 묻지 않음)`; several dimensions joined with `·`
  (`Goal·Success=unclear · 건너뜀`). When a skipped question also decided the size, append to this
  line: a product-owner `Q:` mapped onto the tech-lead's condition → `— 크기도 이 답에 달림`; the
  leader's size question skipped with it → `— 크기 질문도 건너뜀`. A question not asked because
  its outcome was already settled (dependent on a filled epic — *Who is asked about*) shows that
  reason (⑧) instead
⑦ size `depends:` — `제외: #n (크기가 결정에 달림 — …)` and its variants (the `guild:design`
  one; `결정 줄이 있는데도 크기 미정 — …`)
⑧ a dependency conflict — (ii)'s `제외: #q (선행 에픽 #e 와 같은 스프린트에 쌓을 수 없음)`
⑨ seats and Phase 4's depth cut (their wording as it is).
An answered candidate (*Then*, Phase 3) that ends outside the sprint shows
`결정했지만 제외: #n (<reason>) — 답은 기록되지 않습니다` **in place of ⑦–⑨** — one line, so the
notice that the answer is not recorded never disappears behind another line.

**The goal matches the members — re-checked whenever the member set changes** (after the Phase 3
fill, after a Phase 4 depth cut or slot refill, after a Phase 5 drop, "크기 N" or add — the same
"after any change" list as the slot's prepares check). The check is mechanical, not a reading
of the sentence:
- **At least one filled `goal` member came from the product-owner's goal-picks** (a member made
  `goal` by the promotion below does not count) → **any goal-pick not filled** (a goal-pick taken
  as the slot counts as filled — One Issue, one role) → rewrite the goal as one sentence from the
  `goal` members filled and show `목표 수정: 원래 «…» — 빠진 목표 후보 #a · #b` in Phase 5. A pick
  left out only for want of a seat counts too: the goal sentence becomes the tracker's title, and
  a title wider than the members it holds is the mismatch this check exists for. Recompute every
  time from the product-owner's original sentence and goal-picks — a Phase 5 Add that brings
  every missing pick back restores the original and the `목표 수정:` line disappears. While a
  promotion (below) is in force **and no filled `goal` member came from the goal-picks**, its
  message is the one shown; once a goal-pick is back, this rule's line replaces it.
- **A goal the human set** with Phase 5's `목표 <문장>` edit is never recomputed; only
  `⚠ 목표 멤버 없음 — …` still shows when later drops leave no `goal` member.
- **No goal-pick filled** (the slot aside) **while `other` members were** → the leader
  rewrites the goal as one sentence around the filled `other` member the product-owner ranked
  **highest**, and changes **that one member's** `구분` to `goal` — `목표 수정: 원래 «…» — 목표 후보가
  모두 빠져 #n 으로 다시 씀`. This promotion happens **only in the Phase 3 fill and in the refill a
  slot re-arbitration runs inside Phase 3** (*A rejected pick … goes back to the feature picks*),
  recomputed from scratch each time (an earlier promotion is undone first). Never after Phase 4
  (a `skip (stack-cap)` refill, the final-graph re-check) or a Phase 5 edit — the `구분` the human
  has seen does not change under them; there a `goal` group holding only the slot, or nothing,
  reads `⚠ 목표 멤버 없음 — 목표를 정하거나 드롭/추가하세요`, as it does when nothing at all was
  filled. (`plan-hash` is computed over Phase 6's final body — a promotion does not affect it.)

**Adding to an open sprint** (Phase 0 step 4's "add"): none of the above applies — no automatic
fill, no decision questions, no `구분` column, no machine lines. The tracker body is sealed by its
`plan-hash`, and the leader proposes additions by judgment — which issues, how many — and the
human approves them in Phase 5. (Members
added this way have a known gap of their own — `run` reads only the sealed table; that is
separate work.)

⚠ **The refactor slot counts inside the capacity, not on top of it.** Capacity is the human's
PR-review throughput (`retro.md` Phase 4), and a refactor PR is reviewed like any other. A
capacity of 5 with the slot filled is 4 feature members plus the slot. Do **not** drop the slot
to make room for a fifth feature unless capacity is 1 — then record `skip (capacity)`.
⚠ **A seat the slot gives back is refilled.** Whenever the slot leaves after the Phase 3
fill, **for any reason** (the prepares check below the cut, `skip (stack-cap)` in Phase 4, the
human dropping it in Phase 5), take the next candidate in
the fill order (goal-picks, then other-ranked) that passes the usual gates into its seat — never
one needing a decision question, which are asked once, in the fill; *Epics in the fill* (i)–(ii)
apply, so a pick they rule out is skipped, never a member pushed out — and redo Phase 4. Otherwise a slot that
did not happen silently costs the sprint a feature member — the opposite of its hard rule.
No such pick → leave the seat empty and say so in Phase 5's **`용량:`** line (`shortfall: supply`).
⚠ **The seat is the slot's or the refill's, never both.** If a later recompute lets the slot
back in (Phase 4's comparison after a feature-set change, or the human accepting a depth),
the refilled pick leaves again — otherwise the sprint holds capacity + 1. ⚠ **The recompute
that the slot's own refill triggers never re-admits the slot** — only a change unrelated to it
(a cut the human accepts, a Phase 5 edit) can, and **only a `skip (stack-cap)` slot** can be
re-admitted at all: a slot the human declined, or one rejected at arbitration, stays out. Otherwise refill → slot fits → refill leaves →
slot over the cap → refill returns loops without end.

## Phase 4 — Cycles → linearize → order → depth

Write the graph to a temp JSON with the **Write tool** (`_sprint_dag.md` Section F), then one Bash call per mode. **Absorb every exit code and branch on the value** — these are meaningful non-zero codes, not failures (`_sprint_dag.md` Section C).

⚠ **TWO input files, not one.** `cycles` and `linearize` read `deps` (the declaration); `order`, `depth` and `base` read **`base_deps`**, which is step 2's *output*. Passing one file through all four modes therefore asks the last three to read a key that is not there yet. The script now refuses that (exit 64) rather than answering — it used to return issue-number order, `depth 1` and `DEFAULT` for every member, all with exit 0, so nothing warned. **After step 2, write a second file** with each member's `base_deps` set from the `linearize` output, and point steps 3–4 at it.

**Every member in the `base_deps` file carries its `kind`** — `goal`, `other` or `slot` (the
Phase 3 fill; the draft placeholder is `slot`). `--mode order` breaks a tie by kind first
(`goal`/`slot` before `other`) and then by issue number, so where dependencies leave a choice the
goal's work runs first. `linearize` ignores `kind` — which issue becomes a fan-in's base is
unchanged, and an `other` member can still end up as a `goal` member's base (a known limit).
`run` rebuilds the same file from the table's `구분` column (`run.md` Phase 1 step 5) so the
order it runs is the order the human approved.

**When Phase 2 accepted a slot** (the next three paragraphs; with no slot — `skip`, `off`, or
the ad-hoc path — Phase 4 runs once, as numbered below):

**The refactor slot enters the graph as a foundation.** In the with-slot graph, add the slot to the
`deps` of every member listed in its **Prepares**, and of every member whose (b) files share a
file with the slot's **Files**. ⚠ This is what keeps the slot from colliding
with the work it prepares: two parallel PRs on one hotspot file conflict, and INV3 forbids the
rebase that would resolve it; one stacked under the other is only an order.
- ⚠ **Never add the edge to an ancestor of the slot.** If the slot already depends on a member,
  directly or through others (an existing Issue's `Depends on:` can say so), that member is
  below the slot in the stack already — the two are ordered, not parallel, and the extra edge
  would only make a cycle that fails the whole sprint at step 1 over an optional member.
- **A draft has no Issue number yet** — give it the placeholder **`999999999`** in both files
  and present it as `#(신규)`. ⚠ **Not `0`, and not any small number.** The script breaks ties
  by issue number (in `linearize`, and in `order` after `kind` — the slot's kind is the same
  for the placeholder and the real number), and `run` recomputes the order from the
  table with the real number (`run.md` Phase 1 step 5). A new Issue always gets a number above every
  existing member, so a placeholder above them too breaks every tie the same way the real
  number will; `0` breaks them the opposite way, and the stack and order the human approves
  would not be the ones that run. Phase 6 step 0 swaps the real number in.

**The slot never costs a feature member its place in the stack — it yields instead.** Run
steps 1–4 twice, as two independent pairs of files (each pair is the `deps` file and its
`base_deps` file from the TWO-files rule above — four files in all): first **without** the
slot, then **with** it. Compare the two `depth` values:
- with-slot depth ≤ `max(EFFECTIVE_CAP, without-slot depth)` → the slot adds no depth beyond
  what the feature work already needs; **keep it**, and use the with-slot results. If the
  without-slot depth itself exceeds the cap, step 4's usual proposal applies — to feature work.
- otherwise the slot is what lengthens the stack past the cap: it leaves the sprint — record
  `skip (stack-cap)` and use the without-slot results.
- After **any** change to the feature set (a cut the human accepts, a refill below), redo both
  runs and this comparison; a slot that was over the cap may now fit, and the reverse (but see
  Phase 3: the slot's own refill never re-admits it).

⚠ Do **not** keep the slot by deleting some of its edges: every edge exists because a
member is prepared by it or shares a file with it, so a deleted edge either leaves a Prepares
member building on the pre-refactor code or puts two PRs on one file in parallel.
⚠ At `EFFECTIVE_CAP = 1` a slot always has an edge (it must prepare a member — Phase 2), so
the comparison removes it unless the feature work already needs a deeper stack the human
accepted. The human may also accept the slot's depth after being told — then keep it and
record the override like any other over-cap acceptance (under `merge-commit-forbidden` that
means switching to `squash-sync` — step 4).

1. `--mode cycles` → exit **3** means a cycle exists: show the witness path and `FAIL`. **A cycle must be caught here** — reaching an unattended run with one is a deadlock.
2. `--mode linearize` → each member's `base_dep`. This is what gets written to the member table.
3. `--mode order` → execution order. **Reads the step-2 file.**
4. `--mode depth` (**the step-2 file**) with `max_depth` = **`EFFECTIVE_CAP`** — `1` when Phase 0 step 5 recorded `merge-commit-forbidden`, otherwise `config.sprint.max_stack_depth` (default 3) → exit **4** means over the cap: report the chain and **propose cutting it**, deferring the tail to the next sprint. A warning plus a proposal, not a block — the human may accept the depth — then **keep the 상한 근거 token and write the accepted depth as the 스택 깊이 상한 value** (never `human-override`: `run` would drop the drafts). ⚠ At `EFFECTIVE_CAP = 1` any dependency at all exceeds it, which is the point: the sprint either drops the dependants or the human switches to `squash-sync` (Phase 0 step 5) — when 상한 근거 is `merge-commit-forbidden`, **accepting depth IS that switch**: rewrite 상한 근거 to `squash-sync` and the cap to the accepted depth (≥ the config value). A stack under `merge-commit-forbidden` gets no drafts and no `sync` (`run.md` Phase 0), so that combination must never be written.

⚠ Linearization adds edges: an originally independent issue can end up stacked on another so that a fan-in node has a single base. Mark those in the member table (`⚠ 선형화로 추가된 의존`) and say so in Phase 5 — the human needs to know that #102's PR now cannot merge before #101's.

⚠ **Epic members are re-checked on the final graph** (after the slot edges and `linearize`):
an epic that now has an edge to or from another member breaks Phase 3's *Epics in the fill*
(iii) — the epic downstream → it leaves, `제외: #e (에픽 — 스프린트 안 의존 있음)`, its seat
refilled per Phase 5's Drop; the epic upstream → the downstream member leaves as in (ii). Then
redo Phase 4. (A slot overlapping an epic member was already refused in Phase 2, so this is
only what linearize adds.) An edge the human's own Phase 5 edit (an add, a drop) brought about is
not removed this way — it gets Phase 3's direction warning and the human's answer instead.

## Phase 5 — Present, then stop (attended)

The first line, `후보 N개 중 M개`: M = the members taken (a new slot draft included), N = the
candidates judged (1b's `<후보 수>`) — a new slot draft is not among the N, so M can exceed N.

```
후보 12개 중 8개를 이번 스프린트로 제안합니다.

▎목표: <한 문장>

  ■ 목표
  ① #103  영수증 재발행         base: —        🏗 기초   readiness: clear/partial/clear
  ② #104  실패 로그 집계        base: #103               원래 의존: #103
  ③ #(신규) 결제 상태 갱신 경로 통합  base: —        🧹 리팩토링 슬롯
  ④ #101  결제 상태 머신 정리   base: #(신규)            원래 의존: #(신규)
  ⑤ #102  타임아웃 재시도       base: #101     스택 3단  원래 의존: #101
  ■ 목표 외
  ⑥ #164  알림 설정 섹션        base: —
  ⑦ #210  감사 로깅            base: —        계획 중 결정: Constraint → 감사 테이블은 history 계층에
  ⑧ #459 (에픽 · 남은 자식 4개 — PR 최대 4개)  일정 엔진 재작성  base: —
  …
  🧹 리팩토링 슬롯: #(신규) «결제 상태 갱신 경로를 한 곳으로» — #101이 이 위에 쌓입니다 (#102는 #101 위)
       근거: src/payment/state.ts · 최근 fix: 커밋이 몰림 · 갱신 경로 3곳 중복
       성공 기준: 기존 테스트 green · applyTransition() 하나로 통합
       안전망: state.ts · applyTransition() · 취소 후 재시도 시 상태 유지 외 2건 (리팩토링 전 커밋에서 green)
  계획 중 결정: #210(Constraint: 감사 테이블 위치 → history 계층) — 만들 때 Issue 본문에 기록합니다
  결정했지만 제외: #213(스택 깊이) — 답은 기록되지 않습니다
  사람 작업 필요: #190(credential) · #357(upstream) · #377(needs-human 대기 — /gld resume 377)
  통합 점검 대기 — /gld dev #458
  선행 대기: #122 ← #103(이번 스프린트)
  선행 대기(미포함): #159 ← #158 · #161 ← #146
  그 뒤의 장벽: #161(자식 #506 결정 필요)
  ⚠ 선행 미포함: #120 ← #118(열림, 멤버 아님) — 기본 브랜치에서 시작합니다
  의존 무시: #459 ← #146 (본문: «#496. #146(…)과 같은 엔진 구간이라 순서를 조율한다»)
  의견: #161 ← #146 는 이미 충족됐을 수 있습니다(tech-lead: 실제 필요는 #531 의 엔진 변경, via #531) — 맞으면 #161 본문 · 자식 #512 본문의 Depends on 을 고치세요
  제외 5개: #108(Success=unclear · 건너뜀) · #110(⚠ 분할 예상) · #133(구체화 필요 — 1b) · #141(PO: 이번 목표와 무관한 실험) · …
  용량: 10 · 담음 8(목표 5 · 목표 외 3 · 슬롯 1 포함) · 미달 사유: supply — 남은 후보 없음 (실측 최대 9)
  (담음이 용량과 같을 때만, 용량 > 실측 최대이면: ⚠ 용량 10 은 아직 실측된 적 없는 크기입니다(실측 최대 9) — 줄이려면 "크기 N" 으로 말해 주세요)
  최대 스택 깊이: 3 (상한 3 — 경계)
  머지 전략: merge commit 허용 ✅ · 브랜치 자동삭제 ✅
  기록: 만들면 판정 원문(docs/specs/sprint-<트래커 번호>/)과 config.json 을 main 에 커밋하고 push 합니다

이대로 만들까요? (드롭 / 추가 / 크기 N / 의존 유지 #d / 목표 <문장> / 재범위 / 재정렬 [/ 스택 없음] 요청 가능)
```

`[/ 스택 없음]` is shown **only when 상한 근거 is `squash-sync`** (Edits, `스택 없음`), rendered without
the brackets — the line then ends `재정렬 / 스택 없음 요청 가능)`; otherwise it ends `재정렬 요청 가능)`.

**The lines the fill adds** (each only when it has something to say):
- `■ 목표` / `■ 목표 외` — the two groups; the slot sits in the goal group.
- `용량:` — `C`, how many were taken and how they split, the `shortfall` reason when fewer than
  `C`, and the largest `planned` in `sprint.history` (entries with `adhoc` excluded). ⚠ **When
  the sprint holds `C` and `C` is larger than that largest past size**, add
  `⚠ 용량 <C> 는 아직 실측된 적 없는 크기입니다(실측 최대 <M>) — 줄이려면 "크기 N" 으로 말해 주세요`.
  The number is never cut automatically — it is the human's to change here, or `retro`'s.
  No usable history entry (first sprint, or every entry `adhoc`/without `planned`) → omit the
  `실측 최대` part and the ⚠ line.
- `머지 전략:` — Phase 0 step 5's reading, its front part 1:1 with the 상한 근거 token:
  `merge commit 허용 ✅` (`config`) /
  `merge commit 불허 → squash-sync(상한 <n>) — 하단 PR 머지 뒤 /gld sprint sync` (`squash-sync`) /
  `merge commit 불허 · 스택 거절 → 스택 없음(상한 1)` (`merge-commit-forbidden`), then
  `· 브랜치 자동삭제 <✅|❌>`. Settings that could not be read → Phase 0 step 5's two
  `머지 전략: 알 수 없음(조회 실패) → …` forms, and nothing else.
- `⚠ #n 은 중앙 관리 파일 <file> 을 고칩니다 — …` — for every **member** (filled automatically or
  added with Add; for an epic, its remaining children's bodies too, shown as `#e(자식 #c)`) whose
  body holds a central-owned file — the definition and matching rule are in the Refactor slot
  section (*Central-owned files*), the one place they are written. Read that body: does it name
  the file **as something to change**? Yes even when it also offers accepting it or leaving it
  unchanged — **unless a decision rules the change out**, which takes both: (1) a decision (one
  made in this plan, or a `decided:` line of the body — an earlier plan's, Phase 3's *Already
  decided*; for a `#e(자식 #c)` warning, that child's body's line) whose question or options deal
  with **that file, or a change item the body ties to that file**, and (2) an answer that rules
  out **every** change branch the body writes for that file (measured #349: "3건 모두 명시적
  수용") → no line. A decision that rules out only some of them (accepting defect 3 only — the
  file changes of defects 1 and 2 remain), or one unrelated to that file → the line.
  **A conditional change counts**: written as one branch of the work ("if the investigation
  shows X, fix that file") → yes. **A mention made to rule the change out does not**: when every
  sentence naming the file rules the change out ("fixing it here would fork it", "not that file
  but …") → no. No when it only describes calling it, comparing with it or its timing.
  `<file>` in the line is the **file name** (`gate_precommit.py`, `secrets.md`,
  `verification.md`), even when the body attaches a path. Yes → one line:
  `⚠ #n 은 중앙 관리 파일 <file> 을 고칩니다 — 다음 /gld update 는 이 로컬 수정을 덮어쓰자고 제안합니다(새 check 추가일 때만 scripts/local/ 이관을 묻습니다); 플러그인 저장소(plugin.json 의 repository)에서 고칠 일인지 확인하세요`
  — for `secrets.md` / `verification.md`:
  `⚠ #n 은 중앙 관리 파일 <file> 을 고칩니다 — 다음 /gld update 가 게이트 스크립트와 함께 덮어씁니다; 플러그인 저장소(plugin.json 의 repository)에서 고칠 일인지 확인하세요`.
  A body that says it makes the change as a `scripts/local/` extension → no line. Not
  `/gld contribute`: it takes only overlay and evolve candidates. **A warning, not a gate** — the
  gates, the product-owner's list, 1b and the board do not change: the change can be made here,
  and the risk is that the next update overwrites it.
- `계획 중 결정:` / `결정했지만 제외:` / `사람 작업 필요:` / `선행 대기:` — Phase 3's decision
  questions and the candidates they could not reach. A dry-run adds
  `dry-run 으로 끝나면 이 답은 남지 않습니다 — --create 로 다시 부르면 다시 묻습니다`.
- `앞서 구체화 필요로 보고한 #n — …` — when Phase 1b listed a candidate this run then asked about,
  with one of three endings: `이번에 답해 담았습니다` / `건너뛰었습니다` /
  `이번에 답했지만 빠졌습니다(결정했지만 제외 줄 참고)` — answered but out of the sprint (size,
  depth, a dependency, a drop — whichever): the reason is written on its `결정했지만 제외:` line
  only, never here.
- `사람 작업 필요: #n (<credential|device|upstream|other>)` — a Phase 1b **막힘** candidate (the
  class is the leader's 1b reading — Phase 2 left it out of the product-owner's list, so there is
  no `human-work:` of the product-owner's for it); an epic waiting on a child:
  `사람 작업 필요: #e (자식 #c needs-human 대기 — /gld resume c)`. A candidate at stage `none` or
  `guild:analyze` that 1b did **not** find 막힘 but the product-owner gave a `human-work:` → not
  taken, `사람 작업 필요: #n (<class> · PO 판단, 1b 는 <착수 가능|구체화 필요>)`.
- `선행 대기: #n ← #d(이번 스프린트)` / `선행 대기(미포함): #n ← #d` — a `prerequisite:` dimension
  or an epic's (i) (Phase 3); a prerequisite is not human work and is never listed under
  `사람 작업 필요`.
- `제외: #n (PO: <사유>)` — a candidate in the product-owner's `## not-ranked`, with its line.
  An ordinary candidate gets it as ④ of its order of reasons (Phase 3, *Phase 5 order of
  reasons — ordinary candidates*: one line, the first that applies); an epic (whose order ⓪–⑤
  has no not-ranked — measured #161) **only when no other line already gives it a reason** (`사람 작업 필요`, `선행 대기`, a Phase 3
  `제외` — measured: 7 candidates shown twice). Together with the Phase 3 reasons (`제외: #e (에픽 · …)`, `제외: #n (크기가 결정에 달림 — …)`,
  `통합 점검 대기 — /gld dev #e` …) every candidate the sprint did not take has a stated reason.
- `그 뒤의 장벽: #e(자식 #c 결정 필요, #c2 분할 예상) · …` — an epic out as `선행 대기` whose
  ③ or ④ reason the one-line rule hid (Phase 3, *A barrier hidden behind ②*).
- `목표 수정: 원래 «…» — <이유>` / `⚠ 목표 멤버 없음 — 목표를 정하거나 드롭/추가하세요` —
  Phase 3's goal re-check.
- An epic member's lines (Phase 3, *Epics in the fill*): `#e (에픽 · 남은 자식 k개 — PR 최대 k개)`
  in its row, and the k ≥ 10 and stacking warnings.
- `의존 무시: #e ← #d (본문: «<그 문장>»)` — **for members only** (an epic member, or an ordinary
  member whose `Depends on` Phase 5's `⚠ 선행 미포함` reads by the same rule; a non-member's ignored
  number changes nothing): each number left out only because it sat after the first sentence,
  and each number the leader removed by judgment (Phase 1's `Depends on` reading rule) — never
  for the Issue itself, its parent, a sibling, or a line that begins `없음`/`none`. A negation
  inside the first sentence is shown too, not hidden — the line is how the human can undo the
  leader's reading (`의존 유지 #d`).
- `의견: #e ← #d 는 이미 충족됐을 수 있습니다(tech-lead: <근거>, via #x) — 맞으면 <#e 본문|자식 #c 본문>의 Depends on 을 고치세요`
  — the tech-lead's `satisfied: #e ← #d — via #x — <근거>` note. This `satisfied` 의견 line is shown
  **only when that candidate (an epic or not) is out as `선행 대기`** on `#d`. Name **every** source that put `#d`
  in its floor (measured #161: the epic's own body and child #512 both say #146). A reason the
  one-line rule hid behind the `선행 대기` goes on the `그 뒤의 장벽:` line, not here. Display only:
  the dependency stays (the tech-lead's (a) adds, never removes), and nothing is edited for the
  human.
- `의견: #a ← #b (조건: <조건>) — <tech-lead 메모>` — the tech-lead's `conditional:` note (a
  relation that holds only under a condition), shown **only when both `#a` and `#b` are members**
  (most often through an Add); an epic side mapped as `#e(자식 #c)`, the same as the `satisfied`
  line. The direction is the note's — never `↔`. The leader never uses the note as a dependency:
  no edge in Phase 4, no `⚠ 선행 미포함`.
- **`⚠ 선행 미포함:` (required)** — for every member, each **dependency** (a hard edge: the
  tech-lead's (a) relations and the body's `Depends on: #d` read by Phase 1's `Depends on` reading
  rule — first sentence only, `없음`/`none` is none; an epic's extended dependency; **not** a
  conditional note or soft ordering recommendation of the tech-lead's) that is **open** (in
  Phase 1's list before exclusions — for an epic that includes a `guild:done` target not yet closed) and **not a
  member**: `⚠ 선행 미포함: #p ← #d(열림, 멤버 아님) — 기본 브랜치에서 시작합니다` (mapped through a
  child, on the target side only as in (i): `⚠ 선행 미포함: #q ← #d(자식 #c…)`, `#q ← #d(+자식 #c…)`). Phase 4's
  "outside the sprint" warnings go to stderr where nobody reads them; the leader used to filter
  such picks by judgment, and the fill no longer does — so the human must see them. Nothing is
  added or removed automatically; dropping or adding is the human's edit.

**Edits** (re-apply before re-presenting; new sprints only — the "add" path is unchanged):
- **Drop** → the seat is refilled by the next candidate in the fill order that passes the gates
  (never one the human dropped this session, never one needing a question; an epic's (i)–(ii)
  apply — a pick they rule out is skipped, no member is pushed out). Dropping is not a
  size decision; no candidate left → the seat stays empty, `shortfall: supply`.
- **`의존 유지 #d`** → put `#d` back into that epic's extended dependency (a number a `의존 무시:`
  line showed) and re-apply Phase 3's *Epics in the fill* (i)–(ii); the epic leaving as a result
  → its seat is refilled as for a Drop. For an ordinary member, `#d` goes back into its
  dependencies — Phase 4 and the `⚠ 선행 미포함` check then read it like any other.
- **`목표 <문장>`** → the human's sentence becomes the goal (and the tracker's title). The goal
  re-check (Phase 3) no longer rewrites it and shows no `목표 수정:` line for it; it still shows
  `⚠ 목표 멤버 없음 — …` when no `goal` member is left. No member's `구분` changes.
- **"크기 N"** → cut in reverse fill order (lowest other-ranked first, then lowest goal pick)
  down to N and do not refill. Record `shortfall: human-cut` **only** in this case and only when
  the sprint held at least `C` before the cut — a sprint already short of `C` keeps its own
  reason, so the supply level never hardens into the capacity.
- **Add** → the human's own choice: the automatic gates (`unclear`, `guild:needs-human`,
  구체화 필요, 막힘, an epic's (i)–(ii) and its every-child-✅ gate) do not apply, a warning line is shown instead (`⚠ #n 은 needs-human 대기 — run 이
  건너뜁니다` …; an epic: `⚠ #e 는 자식 #c needs-human 대기 — run 이 그 자식에서 멈춥니다` for
  `blocked_children`, `⚠ #e 의 자식 #c 는 분할 예상 — run 이 그 자식에서 사람 대기로 멈추고 에픽은 일시정지됩니다(재시도 없음)`
  for a tech-lead ⚠ or mixed child to be sized, `⚠ #e 의 자식 #c 는 결정이 필요합니다 — design 에서 정해지지 않으면 그 자식에서 멈출 수 있습니다`
  for a `depends:` child to be sized or a `decide-in: #c` on a child to be decided — Phase 1's bounds; a child past them gets no such warning); size and slot rules apply as before. A candidate
  Phase 2 left out of the product-owner's list has no ratings: its row shows
  `readiness: —(PO 미평가)`. Its `구분` follows where the product-owner
  ranked it (goal-picks → `goal`, anything else → `other`). More than `C` → one warning line,
  `shortfall: none`. An add or drop that leaves an epic member depending on, or depended on by,
  another member gets Phase 3's two direction warnings (*Epics in the fill* (iii)) and the
  human's answer — never an automatic removal.
- **`스택 없음`** → offered **only when 상한 근거 is `squash-sync`** — including a `squash-sync`
  reached by accepting a depth after Phase 0's read failed (Phase 4 step 4). The human declines
  stacking (Phase 0 step 5): rewrite 상한 근거 to `merge-commit-forbidden` and `EFFECTIVE_CAP` to
  1, leave Phase 0's `/gld sprint sync` instruction out of the presentation, and re-run Phase 4.
  The `머지 전략:` line becomes `merge commit 불허 · 스택 거절 → 스택 없음(상한 1)`, or after a
  failed read `머지 전략: 알 수 없음(조회 실패) → 스택 없음(상한 1) · 브랜치 자동삭제 ?`.
  **This edit leads to a cut proposal**: a depth over 1 gets step 4's usual proposal to cut.
  **Accepting that depth instead of the cut switches back to `squash-sync`** (step 4) — it undoes
  `스택 없음`. A slot, if there is one, leaves by itself once the depth is 1 (the cut accepted —
  Phase 4's slot comparison at `EFFECTIVE_CAP = 1`, `skip (stack-cap)`).
  When 상한 근거 is `config` (merge commits allowed) and the human says `스택 없음`, answer in one
  line: `merge commit 이 허용되어 스택은 그대로 머지됩니다 — 깊이를 줄이려면 크기 N 이나 드롭`.
- After every edit, re-run Phase 4 (an epic re-check on the final graph included), the slot's
  prepares checks and the goal re-check (Phase 3).

The `기록:` line is what Phase 6 step 6 will actually do — read it before presenting, with
the read-only checks of step 6 sub-steps 3 and 5 (current branch, upstream, push URLs): not the
default branch → `기록: 현재 브랜치가 기본 브랜치가 아니라 커밋하지 않습니다 — 직접 커밋해 주세요`;
no upstream or another push target → `… 에 커밋합니다 (push 하지 않음)`.
When the slot is empty, the line says why instead of disappearing —
`🧹 리팩토링 슬롯: 비움 (no-candidate) — 이번 후보들이 건드리는 hotspot 이 없습니다`; after `스택 없음`,
`🧹 리팩토링 슬롯: 비움 (stack-cap) — 스택 없음(상한 1)에서는 슬롯이 스택을 늘립니다`; a slot that
ended `skip (not-ready)` because of a central-owned file (Phase 2's arbitration) ends the line
with `(중앙 관리 파일)`.
The `안전망:` line appears only when the draft carries a Safety net (one line: file · the first
behavior · `외 N건`). A 2b draft is shown as `🧹 리팩토링 슬롯 (안전망만): #(신규) «…»` with its
`근거:` naming the gap (`테스트 없음` / `시각 테스트 없음`) and `성공 기준:` ending in
`프로덕션 코드 변경 없음` — the human should see at a glance that this slot adds coverage, not a
refactor. When the gap check reported VISUAL `unavailable` for a screen it covers, add
`(시각 안전망 없음 — 이 환경에서 렌더링 불가)` to that `안전망:` line. For an existing or resumed
slot that gains a net, the `안전망:` line ends with `(Issue 본문에 추가 예정)`. A slot that gets
no net because it is already past analyze shows `안전망: 없음 — 이미 <stage> 단계라 AC 에
추가할 수 없습니다` — the human is approving a refactor whose "existing tests stay green" may
prove little, and should know it.
When the slot — of any origin: draft, resumed or existing — will not carry `type:refactor`, and
**Phase 0 step 2's label list** has no `type:refactor`, add one line:
`  ⚠ 이 레포에 type:refactor 라벨이 없습니다 — 만들까요? (없으면 기능 흐름으로 개발됩니다)` —
for a 2b slot instead: `(없으면 이 안전망 슬롯은 빠집니다 — 기능 흐름에서는 "바뀌지 않은 코드에서 green" 과 "프로덕션 코드 변경 없음" 을 지킬 수 없습니다)`.
⚠ Use that list (`--limit 200`), not a fresh `gh label list --json name`: without `--limit`
gh returns 30 labels, so a repo with more reads an existing label as missing.
⚠ **Ask this even under `--create`.** `--create` approves the sprint, not a repo-wide label
that `init`, `update` and `audit` all deliberately never create. No explicit yes → no label.
⚠ **The human dropping the slot is a normal edit**, recorded as `skip (human-declined)`. Do not
argue for it beyond its evidence line; the slot is a proposal like every other member.

Handle edits and re-present until the human approves. **Create nothing** without `--create` or an explicit approval — opening a sprint and rewriting member bodies are outward, hard-to-reverse actions (INV1).

**Unattended** (`GLD_UNATTENDED=1`): do not create. Return `OK: unattended — sprint proposal requires a human`. ⚠ Do **not** use `OK PAUSE: needs-human`: that return obliges marking an Issue with the `guild:needs-human` label plus a comment so the pause is discoverable (`_handoff.md` Section H), and there is no tracking Issue yet to mark.

## Phase 6 — Create (`--create` or explicit approval)

**Order matters. The label goes on before any member body is touched.**

0. **Create the refactor slot's Issue** — only when the approved slot is a **draft**. (A
   **resumed** slot already exists: skip creation, record it as `#<n> (drafted)` — it was
   drafted, only by an earlier run.) For a resumed **or existing** slot without the label: if
   the human approved creating it, run `gh label create type:refactor` first (its own call),
   then add it with `gh issue edit <n> --add-label type:refactor`;
   otherwise say once that the slot will run as a feature. When the repo already has the
   label and only the slot lacks it, add it the same way — that is part of the sprint the
   human approved, not a new repo-wide object. A draft goes
   first because the member table needs its number. Body: the draft's sections (Why · Files ·
   Prepares · Goal · Constraint · Success-criteria · Safety net when present) and a `<!-- guild:refactor-slot -->` line
   (plus `<!-- guild:safety-net-only -->` for a 2b draft) —
   the marker Phase 1 finds on a re-run. (An existing or resumed slot that gained a Safety net
   is **not** edited here — step 3 appends it, after the label, in the same rewrite as the
   back-reference.) Temp file + `--body-file`; add `--label type:refactor`
   **only if that label exists or was just created** (Phase 0 step 2's list, or the approved
   `gh label create` below — `init.md` never creates `type:*`
   labels, and `gh issue create --label <name>` errors on a missing one; the same rule as
   `audit.md`). Then **swap the real number for `999999999`** everywhere Phase 4's results
   hold it — the slot's own row, every `base 의존` and every `원래 의존` cell. Because the
   placeholder breaks ties the way the real number does (Phase 4), the order and bases the
   human approved are unchanged, so there is nothing to rerun. ⚠ `999999999` must not reach
   the tracker body, a member back-reference (step 3) or a board write (step 5); grep the body
   for it before step 1.
   ⚠ **Without the label the slot is developed as a feature.** `dev.md` defaults an unlabelled
   Issue to `implement.md`, not `refactor.md`, so the behavior-preserving discipline is lost
   unless `analyze` happens to reclassify. So when the label is missing, Phase 5 asks to create
   it (`gh label create type:refactor`, its own Bash call, before the Issue) — and only an
   explicit yes to *that question* creates it. Declined or unanswered → create the Issue
   without it and say the slot will run as a feature — **except a 2b**, which is settled in
   Phase 5, not here: there the label question is asked first, and a declined label drops the
   2b (`skip (human-declined)`, the seat refilled per Phase 3, Phase 4 re-run) and the sprint is
   presented again before anything is created — so what Phase 6 creates is what the human
   approved. Under `--create`, a 2b whose label is missing and was not explicitly approved is
   dropped the same way, and the sprint is presented again before anything is created — the
   refill is a member the human has not seen.

1. **Create the tracking Issue** — title `Sprint: <goal>`, body from the template below, **no label yet** (temp file + `--body-file`).
2. **Attach the label** — `gh issue edit <tracker> --add-label "guild:sprint"`. If the label is missing this dies here, with **every member body still intact**.
   **Then, when Phase 3 collected at least one decision for a final member**, post them as one
   tracker comment before any member body is touched — `<!-- guild:sprint:plan-decisions -->` …
   `<!-- /guild:sprint:plan-decisions -->`, one line per decision,
   `- #<n> <Goal|Constraint|Success>: <question> → <answer> (<YYYY-MM-DD>)` (`<answer>` without
   its option tags — Phase 3, *How*; its line breaks and runs of spaces collapsed to one space). It is the record a re-run reads if this
   step dies before step 3 finishes; one comment per tracker, replace-in-place (`_handoff.md`
   Section B).
3. **Add the back-reference** to each member body — a `Sprint: #<tracker>` line, **and, for a
   member Phase 3 asked about, its decision block in the same rewrite** (appended once per Issue;
   when the block already exists, add only the dimension keys it lacks and leave existing lines
   alone — a different value there is a human's edit):
   ```
   <!-- guild:plan-decision -->
   ### <계획 중 결정 — config.language>
   - <Goal|Constraint|Success>: <question> → <answer> (<YYYY-MM-DD>, sprint plan)
   <!-- /guild:plan-decision -->
   ```
   The dimension keys stay ASCII; the question and answer are in `config.language`. Read → splice → full rewrite, **with the truncation check** (`_sprint_dag.md` Section A). **Do the slot member first.** Before it, when the slot gains a net, post the approved net as a tracker **comment** under `<!-- guild:sprint:slot-net -->` … `<!-- /guild:sprint:slot-net -->` — a `slot: #<n>` line, then the three parts to splice (the Safety net section, the lines to add to Success-criteria, and a known-gaps/findings part: gaps cut by the 5-line cap and rule-4 "untestable here" findings — an existing Issue has no Why section to hold them) — a comment, not the tracker body, which `plan-hash` seals. A death before the splice leaves that comment as the only record of the net the human approved; Phase 0 step 4 applies it on the next run. **For an existing or resumed slot that gained a Safety net** (approved in Phase 5), splice it into the same rewrite: the Safety net section (heading + `<!-- guild:safety-net -->` + lines + rules), the same lines added to its Success-criteria (or a new Success-criteria section), and the known-gaps/findings part (gaps cut by the cap, untestable-here findings) — skipped when the body already holds `<!-- guild:safety-net -->`, which is what makes a re-run after a mid-create death append nothing twice. One member per Bash call; a failure mid-way is resumable because step 4's idempotency check re-derives what exists.
4. **Compute and store `plan-hash`** — `sprint_dag.py --mode hash` over the finished body, then write it into the `plan-hash:` line. Do this **last**, after the body is final. ⚠ This rewrites the **tracking Issue's** body, which holds the member table — the canonical dependency source for the whole sprint. It carries the **same mandatory truncation check** as a member body (`_sprint_dag.md` Section A): if the read comes back as a preview, read the persisted full output, and if that is unavailable do **not** write. A truncated rewrite here destroys the sprint unrecoverably, which is worse than any member body. (`--mode hash` *removes* the `plan-hash:` line before hashing, so writing the value back does not change it.)

5. **Project onto the board** — only when `config.sprint.board` is set. One Bash call:

```bash
python3 <<SKILL_DIR>>/commands/atoms/board_write.py --input <path>
```

Write the input file with the Write tool. ⚠ **All six top-level keys are required** —
a missing one is exit 64 and the board gets nothing for the whole sprint. `repo` is the easy
one to forget and it is load-bearing twice (it builds the issue URL and it filters other
repos' issues out of `item-list`).

```json
{
  "number":  <config.sprint.board.number>,
  "owner":   "<config.sprint.board.owner>",
  "repo":    "<owner/repo from Phase 0>",
  "field":   "<config.sprint.board.column_field>",
  "columns": <config.sprint.board.columns, verbatim>,
  "owned":   <config.sprint.board.owned, verbatim>,
  "guard":   true,
  "read":    true,
  "writes":  [ ... ]
}
```

⚠ **Pass `owned` too.** `board_write.py` refuses to write any field name that is not on that
list and exits 64 before touching anything — that is what turns D1 from an intention into a
rule. Without it, a hand-edited `fields.needs_human` pointing at `Assignees` would have Guild
writing the human's own field with nothing refusing.

⚠ **Take every name from `config.sprint.board`, never from this file.** The column field, the
column display names and the four data-field names are all things a human can rename in the
GitHub UI, and config is where that rename is recorded. Hardcoding `"Order"` / `"Needs human"`
means `plan`'s writes start failing the day someone renames a field while the supervisor's
keep working — the supervisor reads its names from config for exactly this reason (§7.2).

Two kinds of entry in `writes`:

| Kind | Entry | Guard |
|---|---|---|
| **members** (seeding) | `{"issue":101,"column":"ready","guard":false,"fields":{"<fields.order>":"1","<fields.depends_on>":"#100","<fields.sprint>":"<tracker>"},"clear":["<fields.needs_human>"]}` | **off** — a member entering a sprint belongs in `Ready`, carryover included |
| **non-members** (Phase 1b) | `{"issue":120,"column":"backlog"}` (착수 가능) or `{"issue":121,"column":null}` (구체화 필요 and 막힘 — both the null bucket) | **on** |

⚠ **The two sets are disjoint — subtract the selected members from the triage writes.** Phase
1b judges the whole candidate set and Phase 2 then picks members out of that same set, so an
issue can appear in both lists. Entries are applied in order against one pre-read snapshot,
so a `backlog` entry landing after the member's `ready` entry leaves that member sitting in
`Backlog` for the entire sprint. Members are seeded by the member rows; the triage rows cover
everything else.

⚠ **Clear the `needs_human` field on every member.** A carryover member can arrive still carrying
`guild:needs-human` — the Phase 3 fill no longer takes such a candidate on its own, but the
human may add it in Phase 5 (that is the designed path — 02번 §10.4), and the supervisor left
`failed:<class>` or `needs-human` on its card last sprint. Writing `Ready` without clearing
the reason produces a self-contradictory card: *"queued"* with *"blocked because …"* beside it.

⚠ **The guard is what keeps `plan` off supervisor-owned cards.** `board_write.py` reads
`item-list` once and writes a non-member card only when its current value is **absent (the null
bucket), `backlog` or `ready`**. The four values the supervisor owns — `in_progress`, `blocked`,
`in_review`, `done` — are refused.

⚠ **`ready` is on the writable side, and that is deliberate.** It is the one column both writers
touch, so treating it as supervisor-owned made every `Ready` card unrepairable by either: a
member the human DROPS from the next sprint sat there with last sprint's `Order` and `Sprint`
forever, saying *"queued, nothing to do"* about work in no queue. Only non-members reach these
guarded writes (Phase 1 excludes anything already a member of an open sprint), so re-triaging a
stale `Ready` is both safe and the only thing that ever cleans that column. Three earlier designs tried to draw this line
with **labels** and all three leaked: `needs-human` carryover, then `guild:children` epics
locked in `Issues`, then members that failed before their child session ever started
(`split-stalled`, `worktree-create-failed`) — those have **no stage label at all**. Card
value is the only boundary that holds.

⚠ **`item-list` truncated → the guarded writes are skipped**, `truncated=1` comes back, and
that goes in the report. Writing blind is how a supervisor's `Blocked` becomes `Backlog`.
The script re-reads once at the real size before declaring truncation, so `truncated=1` means
the board genuinely could not be read whole — not merely that it is bigger than a page.

⚠ **`unknown=<n>` is a different sentence from `skipped=<n>`.** `skipped` means the supervisor
owns those cards, which is normal and needs no action. `unknown` means the card holds a value
that is **not in `config.sprint.board.columns` at all** — almost always a column renamed in
the GitHub UI without updating config. Those writes are refused too, but the remedy is a
one-line config edit, so say so:
*"⚠ 카드 <n>장이 config에 없는 컬럼 값을 갖고 있습니다 — 보드에서 컬럼 이름을 바꾸셨다면
`config.sprint.board.columns`도 맞춰 주십시오."*

⚠ **This is the only step gated on the board.** Everything above happened already; a board
failure must not undo a created sprint. Report the summary line and move on (D9).

**Report all six numbers `board_write.py` returns.** In these files the example is what gets
copied, so here are three shapes that matter:

```
보드: 41건 기록 · 3건 생략(감독자 소유) · 미상 0 · 실패 0
보드: 7건 기록(멤버 시딩) · 41건 생략 · 미상 0 — ⚠ 보드를 다 읽지 못해 인테이크 판정은 반영하지 않았습니다
보드: 41건 기록 · ⚠ 그중 5장은 컬럼 쓰기가 실패했습니다 (stderr 의 이슈 번호를 확인하십시오)
```

⚠ **The second line: truncation does NOT mean "nothing was written".** Only *guarded* writes are
skipped, and member seeding is deliberately unguarded — so on the `--create` path a truncated
read yields `wrote=<members> skipped=<M> col_failed=0 failed=0 truncated=1`, never `wrote=0`.
Saying *"아무 것도 쓰지 않았습니다"* is false whenever the sprint has at least one member. What
is true is that the **intake judgement** did not land. And `failed` stays 0 because no guarded
write was attempted — not because nothing failed.

⚠ **The third line: `col_failed` is not `failed`.** `failed` counts every `gh` call, `Order` and
`Sprint` writes included; `col_failed` counts entries whose **column** write failed, which is the
only field that changes what the board *says*. An entry can be in `wrote` and `col_failed` at
once (its `Order` landed, its column did not), so without this number the human cannot learn
that 5 of the 41 "recorded" cards are in the wrong column. The issue numbers are on stderr.

⚠ **Name the retry.** There is no re-projection command: re-running `plan --create` stops at
Phase 0 ("a sprint is already open"). So when `col_failed > 0`, say what the human can actually
do — fix those cards in the UI, or start the run and let P1 overwrite the column on its first
projection of each member.

⚠ **Also set `config.sprint.board.last_projected`** to now. `sprint board` and `daily` show it.

6. **Record the plan in git** — after step 5, so `last_projected` is in it. Phase 5 told the
   human this commit and push would happen; Phase 6 only runs after their approval.
   ⚠ **Not on `run.md`'s ad-hoc path** (its Phase 1 step 2 runs this Phase 6): there was no
   Phase 2, and `run` leaves the human's checkout alone — skip this step there, and when step 5
   wrote `last_projected`, say once that `config.json` is left uncommitted.
   Each command its own Bash call. Any check below that stops → **commit nothing**, say why, and
   print the retry line at the end of this step.
   **The record** is: the verdict files **this run's** Phase 2 RESULT lines named in
   `docs/specs/sprint-draft/` — `po.md`, `deps.md`, and `deps-slot.md` only when this run
   re-spawned — plus `.claude/guild/config.json`. Never the directory: anything else in it
   (a file a sub-agent or a leader left there) is not this sprint's record.
   1. **What is there to record?** `git status --porcelain -uall -- .claude/guild/config.json docs/specs/sprint-draft/`.
      Keep only the record's paths from what it prints — plus any ` D` line for one of the three
      fixed names under `sprint-draft/`: Phase 2's `rm -f` deleted a draft that had been committed,
      and that deletion goes into the record too. None → skip the rest of this step silently.
   2. **Name the files after the sprint — first, before any check can stop**, so a record a later
      check leaves uncommitted is not where the next `sprint plan` overwrites it. One
      `mkdir -p docs/specs/sprint-<tracker>`, then pick **one suffix for the whole run**: none
      when no target name exists, else the first `-<N>` (2, 3, …) at which none of this run's
      names exists (`ls` each; the add-these-issues path of Phase 0 step 4 records into a sprint
      that already has a record) — so `po-2.md`, `deps-2.md` and `deps-slot-2.md` read as one
      run. Then per file `mv docs/specs/sprint-draft/<name> docs/specs/sprint-<tracker>/<stem><suffix>.md`.
      `mkdir`, `mv` (and Phase 2's `rm`) are not on the template's allow list, so each asks —
      expected in an attended step. Denied → stop, and say which files are still in `sprint-draft/`.
      A source that was already committed — a dry-run's draft swept into one of the human's own
      commits (`git ls-files --error-unmatch docs/specs/sprint-draft/<name>` succeeds) — leaves a
      deletion behind: add that source path to the record too, so this commit carries the
      deletion instead of leaving it unstaged in the human's tree.
   3. **On the default branch?** `git branch --show-current` must equal the default branch
      (Phase 2's `DEFAULT BRANCH`; when that was `unavailable` or never resolved — the refactor
      slot was off — `gh repo view <owner>/<repo>
      --json defaultBranchRef --jq .defaultBranchRef.name` — the repo is positional, there is no
      `--repo` flag). A feature branch, or empty output (detached HEAD) → stop: a sprint record
      committed onto a feature branch ships inside that branch's PR.
   4. **Nothing else staged?** `git diff --cached --name-only` must print nothing. Anything →
      stop: those are the human's. With paths after `--`, git itself commits only those paths,
      but Guild's PreToolUse commit gate scans the whole index — it would judge (and may refuse)
      this commit by files it does not contain.
   5. **Where does it go, and is the branch level?**
      `git config branch.<branch>.remote` and `git config branch.<branch>.merge` (e.g. `origin`,
      `refs/heads/main`). Either empty → no upstream: commit, and skip sub-step 8. Otherwise:
      - `git config branch.<branch>.pushRemote` and `git config remote.pushDefault` must both print
        nothing, and `git remote get-url <remote>` and `git remote get-url --push <remote>` must both
        name `<owner>/<repo>` (Phase 0 step 3; `pushurl` can point the push elsewhere) —
        else the human pushes elsewhere (a fork) or this is not the tracker's repo: commit, and
        skip sub-step 8 ("push 하지 않았습니다 — push 대상이 이 저장소의 upstream 이 아닙니다").
      - `git fetch <remote>` — it fails → stop: a stale `@{u}` cannot prove the branch is level.
      - `git rev-list --count HEAD..@{u}` must print `0` (it fails — the upstream branch is gone
        or not fetched → stop). Behind → stop: the push would be
        rejected and leave the branch diverged; the human pulls first.
      - `git rev-list --count @{u}..HEAD` — `0` → go on. Not `0` → the branch already has the
        human's unpushed commits, usually `retro`'s evolve commit (evolve commits on this branch
        and deliberately never pushes). `git log --oneline @{u}..HEAD` and ask: (a) push them
        together with the record, (b) commit the record but push nothing, (c) commit nothing.
        An unanswered or ambiguous reply is (b). (a) → go on to sub-step 6.
   6. **Is `config.json` only Guild's?** `git diff HEAD -- .claude/guild/config.json` — against
      `HEAD`, not the index, because the commit takes the working-tree file. Guild's own lines:
      the whole `sprint.board` block (`sprint board` setup writes it, and its status writes
      `column_by_verified`; step 5 writes `last_projected`) and `sprint.capacity` /
      `sprint.history` (`retro` Phase 4 writes them; the human may not have committed them yet).
      A hand edit inside `sprint.board` (a column rename the board step tells the human to make)
      is committed without asking — it is still the board's config.
      Any other changed line is the human's edit: ask — (a) commit it together, (b) leave
      `config.json` out, (c) commit nothing. An unanswered or ambiguous reply is (c). After (b),
      if nothing is left in the record, stop.
   7. **Commit — only the record's paths, never an empty list.**
      `git add -- <record paths>`, then `git commit -m "<message>" -- <record paths>`, each with
      an explicit `timeout` (600000) — the repo's hooks run in full (`_bash_rules.md`
      Long-running).
      ⚠ **Both commands need at least one path after `--`.** `git commit -m <m> --` with nothing
      after it exits 0 and commits the whole index. Never `git add .`, never `-a`. Message, in
      `config.language`: `docs(guild): 스프린트 #<tracker> 구성 판정 원문을 남긴다`, or
      `docs(guild): 스프린트 #<tracker> 구성 판정 원문과 Guild 설정을 남긴다` when `config.json`
      is in the record (`… Guild 설정을 남긴다` alone when it is the only path).
      Either command fails (a pre-commit refusal, an ignored path) → `git restore --staged --
      <path>` for each record path, one call each (one call for the list errors on the first
      unmatched path and unstages nothing), so nothing of ours stays staged for the human's
      next commit; report the reason and stop. **Never `--no-verify`.**
   8. **Push to the upstream, by name** — skipped after sub-step 5 said so.
      `git push <remote> HEAD:<merge>` with sub-step 5's two values and an explicit `timeout`
      (600000) — not a bare `git push`, whose target depends on `push.default`. It pushes the
      record's commit, plus the commits the human chose with sub-step 5 (a).
      Fails for any reason (a protected default branch that requires PRs, a race, the network, the
      timeout) → first `git ls-remote <remote> <merge>`: its hash equals our commit → the push
      landed after all; report `pushed` and stop here. It cannot be read → leave the commit and
      say so. Otherwise take **our** commit back so the default branch is not left with an
      unpublished commit the human did not make: `git rev-parse HEAD` must equal the commit just
      made (anything else → leave it and say so), then `git reset --soft HEAD~1` — local and unpublished, so no
      published history is rewritten (INV3) — and `git restore --staged -- <path>` per record
      path. The files stay in the working tree as they are (under `sprint-<tracker>`). Report
      the stderr line and *"push 가 실패해 커밋을 되돌렸습니다 — 파일은 그대로 있습니다. 보호
      브랜치라면 PR 로 올려 주세요"*. **Never `--force`, never pull or rebase on the human's
      behalf.**
   **Retry by hand** — this step does not re-run by itself: a second `plan --create` meets
   Phase 0 step 4's open sprint and only records again if the human adds issues. Whenever it
   stopped, say where the files are now and print the commands for the record as it stands
   (without `config.json` after sub-step 6 (b)): `git add -- <record paths>` ·
   `git commit -m "<message>" -- <record paths>` · `git push <remote> HEAD:<merge>` (or the PR
   their branch rules require). Stopped at sub-step 3 → put `git switch <default branch>` first,
   and name `<remote>`/`<merge>` as that branch's (`git config branch.<default>.remote`/`.merge`) —
   run as printed on the feature branch, they would commit there.

Body template:

```markdown
# Sprint: <목표 한 문장>

<!-- guild:sprint:plan -->
plan-hash: <sprint_dag.py --mode hash 의 출력>
- 목표: <한 문장>
- 시작: <YYYY-MM-DD>
- 용량 판단: <N>개 — 용량 <C> · 목표 <g>(슬롯 포함) · 목표 외 <o> · 미달 사유 <없음 | 구체적 사유>
- capacity: <C 정수 | n/a>
- shortfall: <none | supply | depth | human-cut | n/a>
- 머지 전략: <Phase 5 의 머지 전략: 줄과 같은 형태 — merge commit 허용 ✅ | merge commit 불허 → squash-sync(상한 <n>) — 하단 PR 머지 뒤 /gld sprint sync | merge commit 불허 · 스택 거절 → 스택 없음(상한 1) | 알 수 없음(조회 실패) → …> · 브랜치 자동삭제 <✅|❌|?>
- 스택 깊이 상한: <유효 상한 N>
- 상한 근거: <"config" | "squash-sync" | "merge-commit-forbidden">
- 리팩토링 슬롯: <"#<n> (existing)" | "#<n> (drafted)" | "skip (<disabled|no-candidate|not-ready|capacity|stack-cap|human-declined|epic-overlap|ad-hoc>)">

## 멤버 (실행 순서 · 의존성 정본)
| # | 이슈 | base 의존 | 원래 의존 | 비고 | 구분 |
|---|---|---|---|---|---|
| 1 | #101 | — | — | 🏗 기초 | goal |
| 2 | #102 | #101 | — | ⚠ 선형화로 추가된 의존 | goal |
| 3 | #104 | #102 | #101, #102 | fan-in → 체인 · 깊이 3 | other |
<!-- /guild:sprint:plan -->

보드: <config.sprint.board.url>
```

⚠ **The 리팩토링 슬롯 line is always written**, filled or not, and its value is a token, not
prose — `retro` reads it to tell *"no slot was taken"* from *"the slot's PR was refused"*, and
an omitted line reads as neither. The slot's own row carries `🧹 리팩토링 슬롯` in 비고. On the
ad-hoc path (`run.md`, numbers given to `run`) Phase 2 never ran: write `skip (ad-hoc)`. A
`type:refactor` Issue among those numbers is an ordinary member there, not a slot — the slot is
a `plan` decision, and `retro` reads `skip:ad-hoc` as exactly that.

⚠ **The `구분` column is the last column, and its values are machine tokens** — `goal` ·
`other` · `slot` (`_handoff.md` Section K), read back by `run` (the order's tie-break),
`daily` and `retro`. It is last because `stack_sync.py` reads the first three columns by
position; a column inserted earlier would shift `base 의존`. `capacity:` and `shortfall:` are
machine lines too: `capacity` is `C` when this plan filled against one and `n/a` on the first
sprint (no capacity yet) and on the ad-hoc path; `shortfall` is `none` when the sprint holds
`C`, otherwise the reason (Phase 3; several → `human-cut` before `depth` before `supply`), and
`n/a` whenever `capacity` is `n/a`. On the ad-hoc path also write `- adhoc: true`. `retro`
reads these lines (its Phase 4); the prose `용량 판단:` line is for people (`daily` shows it).

⚠ **The board line goes OUTSIDE the marker.** Everything between `<!-- guild:sprint:plan -->`
and its closing marker is the dependency source of truth, and `sprint_dag.py --mode hash`
hashes it — a line added inside would change `plan-hash` on the next read and halt `run` with
`plan-hash-mismatch`. Omit the line entirely when no board is configured; do not write an
empty one.

**Idempotency.** A re-run finds the open tracker at Phase 0 step 4 and adds only what is missing — including, for a member that gets its `Sprint:` line now, the decision lines the tracker's `<!-- guild:sprint:plan-decisions -->` comment (lowest id if several) holds for it and its body block lacks (by dimension key; stage `none`/`guild:analyze` only — later, tell the human instead). The repair runs inside Phase 6, so on the "add" path Phase 6 runs even when the human approves no new issue (it then only adds what is missing). ⚠ **Known limit**: a member whose back-reference already landed but whose decision lines did not, a tracker that died before step 2, and an "add" re-run that ends before Phase 6 (a dry-run, or the human stopping) are not repaired by this — report `결정 N건이 본문에 반영되지 못했습니다: #a … (트래커의 plan-decisions 댓글 참고)` so the human can copy them by hand. A tracker that was created but never labelled is found by its body marker:
```bash
gh issue list --state open --limit 200 --search '"guild:sprint:plan" in:body' --json number,title
```
⚠ GitHub's search index is eventually consistent, so a tracker created seconds ago may not appear yet. If the search is empty but Phase 0 step 2 said the label is missing, say so plainly rather than creating a second tracker.

## Return

`OK: sprint #<n> created with <N> members` (+ ` · plan recorded <sha> pushed` |
` · plan recorded <sha> local` | ` · plan not recorded (<reason>)` from step 6; nothing when
there was nothing to record) · `OK: proposed <N> members (dry-run)` ·
`OK: unattended — sprint proposal requires a human` ·
`OK: open sprint #<t> — run /gld sprint retro first` (Phase 0 step 4, the human chose "retro
first" — nothing was proposed or written) · `NEEDS_HUMAN: <one-line>` · `FAIL: <reason>`

On creation, say what to do next: *"`/gld sprint run`으로 무인 실행하세요. 상태는 `/gld sprint daily`."*

---

## Hard rules

- **Default dry-run.** Nothing is created without `--create` or explicit approval (INV1).
- **The label goes on before member bodies are edited** — otherwise a missing label leaves rewritten bodies and an unfindable orphan.
- **`plan` selects and orders; it does not design or implement.** It stops at a filled container.
- **Every body rewrite carries the truncation check** — member bodies *and* the tracking Issue's. A truncated read must not be written back.
- **A cycle fails here, never later.**
- **The refactor slot is reserved, never forced.** It passes the size gate every member passes and a stricter readiness gate (all three `clear`), shares the capacity (a filled slot takes one seat; a seat it gives back is refilled), never costs a feature member its place in the stack, must prepare at least one selected member, and an empty slot is recorded with its reason token.
- **Members get no new `guild:*` label** (`_sprint_dag.md` Section A).
- **The member table is written once.** After creation it is immutable and guarded by `plan-hash`; changing membership means running `sprint plan` again.
- **The plan commit holds this run's verdict files and `config.json` — nothing else** (bar the
  deletion of a committed `sprint-draft/` source it moved). At least
  one path after `--` on `git commit`, default branch only, nothing else staged, not behind the
  upstream, the human's own unpushed commits pushed only on their word, push by name, a failed
  push taken back with `--soft`; never `git add .`, `-a`, `--no-verify`, `--force` or a pull
  (step 6). Not on `run`'s ad-hoc path.
- All Bash per `_bash_rules.md`; every issue body via temp file + `--body-file`.
