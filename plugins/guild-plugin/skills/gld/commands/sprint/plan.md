# SPRINT PLAN (intake — choose this sprint's issues, order them, open the container)

**Decide *what* the sprint takes and in *what order*, then create the tracking Issue.**
Attended and multi-turn: composing a sprint is a judgment the human refines before anything is
created. Upstream of `sprint run`.

`$1` = `--create` (default = **dry-run**: propose only, create nothing).

> **Bash**: `<<SKILL_DIR>>/commands/atoms/_bash_rules.md` — simple calls; issue bodies via a
> temp file + `--body-file`, never inline multi-line. Owner/repo · labels · `gh` write failures:
> `_handoff.md` Sections A/F. Membership · edges · `sprint_dag.py`: `_sprint_dag.md`.
> Readiness dimensions: `_readiness.md`. Roles: product-owner + tech-lead personas.
> **Output language**: `config.language` (`_handoff.md` Section K); machine tokens stay ASCII.

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
   Non-empty → ask the human: close it with `/gld sprint retro` first, or add these issues to it? Two or more open → say so and ask which; concurrent sprints are not supported.

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
5. **Merge strategy + branch deletion** — the stack's premise:
   ```bash
   gh api repos/<owner>/<repo> --jq '{merge: .allow_merge_commit, squash: .allow_squash_merge, rebase: .allow_rebase_merge, delete_branch: .delete_branch_on_merge}'
   ```
   - `allow_merge_commit == false` → **the effective cap for this sprint is 1** (no stacking; every PR targets the default branch). Reason: auto-retarget only shortens a stack under a merge-commit strategy. Under squash, merging the bottom PR makes its commits *not* ancestors of the base, so the retargeted upper PR shows the bottom's changes **again** — the human re-reviews merged code and resolves conflicts, and INV3 forbids the rebase that would fix it.
     ⚠ **This is enforced, not advisory, and the enforcement is a value — not a warning.** Carry it as `EFFECTIVE_CAP = 1` through Phase 4 (it is what `--mode depth` is given) and write **two lines** into the tracker body: the **스택 깊이 상한** value and a **상한 근거** token. ⚠ The reason must be a machine token (`config` / `merge-commit-forbidden` / `human-override`), not prose: `run` compares it against what it sees on the repo *now*, and it cannot parse a sentence. A single line carrying two numbers ("상한 3 (사람이 1로 승인)") does not say which one is in force. Saying "we propose a cap of 1" and then handing `--mode depth` the config's 3 leaves the stack fully formed — the failure §5.6 calls unrecoverable. The human may override after being told the consequence above; record the override in the body on the same line so `run` and `retro` both see which it was.
   - `delete_branch_on_merge == false` → warn: stacks will not shorten by themselves.
   - A field coming back `null` (permissions) → treat as unknown, warn, and do not silently assume the permissive value.

## Phase 1 — Collect candidates

```bash
gh issue list --state open --limit 200 --json number,title,body,labels
```

Exclude: `guild:done` · `guild:sprint` (trackers) · `guild:child` (they arrive through a parent) · any Issue already a member of an open sprint (`_sprint_dag.md` Section A). ⚠ Do **not** exclude a `guild:children` parent — if one is taken, `run` handles it per the split rules and may hand it back to the human.

Apply `_handoff.md` Section A's **list-form** derivation per element to get each candidate's current stage — an Issue already mid-spine can be a member and will resume.

## Phase 1b — Triage the intake (report now, write to the board later)

⚠ **This phase runs whether or not a board is configured.** The judging and the report are
the substance; the board is one way of *showing* the same thing. §12's rollback says it
outright — setting `config.sprint.board` to `null` stops the board **writes**, not the
triage — and a board-less repo (the D2 default) is exactly the reader who needs the
*"구체화가 필요합니다"* group list most, since no column will ever say it for them. What is
gated on the board is Phase 6 step 5, and only that.

The candidate set is Phase 1's, unchanged. Split it in two:

| Verdict | What it means | What Guild does |
|---|---|---|
| **착수 가능** | what to build is decided by reading the Issue | the card goes to `Backlog` |
| **구체화 필요** | an idea, or a plan with an open question. Handed to `dev` today it ends at `needs-human` | the card's column is **cleared** → the null bucket, i.e. `Issues`. **Grouped by theme and reported** |

⚠ **Truncation is named, not silenced.** Phase 1 reads `--limit 200`. If `count == limit`,
re-read with `--limit 500`; if it still equals the limit, **continue anyway** and put one line
at the top of the report: *"⚠ 열린 이슈가 500개 이상입니다. 최근 500개만 판정했습니다."*
⚠ Do **not** borrow `retro.md`'s procedure here. Its re-read narrows with
`--search '"Sprint: #<tracker>" in:body'`, which is exact *because members carry that
back-reference* — intake candidates are non-members and have no such line. And its PR branch
**stops**; stopping here would mean `sprint plan` cannot run at all in a repo with 200+ open
issues, which it does today.

Report both groups. This is the whole point of the phase — the second group is a work list
for the human:

```
판정 47개 중 41개 · 제외 6개 · 절단 없음

■ 이번 스프린트 후보 — 착수 가능
  그룹 1 «결제 실패 처리»   #101 #102 #104
  그룹 2 «영수증»          #103

■ 구체화가 필요합니다
  그룹 A «알림 채널 재편»   #120 #121 #127
      → 셋 다 "어디로 보낼지"가 미정입니다. 함께 정하는 편이 낫습니다
      → /gld plan 120
  그룹 B «관리자 화면»      #133
      → 화면 범위가 한 줄뿐입니다
      → /gld plan 133
```

⚠ **Refinement is not this command's job.** The human runs the existing **`/gld plan <issue>`**,
which decomposes an epic into dev-unit Issues. That labels the parent `guild:children`, and a
`guild:children` parent is **not** excluded from Phase 1 — so the epic itself becomes a
candidate next time. The backlog unit after refinement is the **epic**, not its children.

⚠ **Nothing is written to the board yet.** Judging is free; writing is not. See Phase 6 step 5.

## Phase 2 — Select and order (product-owner ∥ tech-lead, parallel)

As the leader, spawn BOTH role sub-agents in one message (independent, concurrent). Reuse the prompt *shape* of `plan.md` Phase 1, but the job is **selection, not decomposition**.

**Product Owner** (value):
- `subagent_type`: `general-purpose`, `model`: `sonnet`, `description`: `product-owner sprint select`
- `prompt`:
  > Adopt the persona in `.claude/agents/product-owner.md`. Read the candidate list below and `docs/standards/charter.md`. Propose (a) **one sentence** naming what this iteration is for, and (b) the candidates that serve it, in priority order. For each candidate rate the three readiness dimensions of `_readiness.md` — **Goal / Constraint / Success-criteria** — as `clear` / `partial` / `unclear` (ASCII machine tokens, never localized). **Recommend excluding any candidate with an `unclear` dimension** and say why: unattended, the leader would have to guess that gap alone. Write the result to a FILE `docs/specs/sprint-<slug>/po.md` (do not paste it back).
  > <!-- guild:result-contract -->
  > Return EXACTLY one status line, preceded by a `>>> RESULT <<<` sentinel on its own line. Anything before the sentinel is ignored. Status is one of `DONE` / `DONE_WITH_CONCERNS: <one-line>` / `BLOCKED: <one-line>` / `NEEDS_CONTEXT: <one-line>` / `FAIL: <reason>`. **Artifacts are passed as files, not pasted** — write to the working tree or `docs/specs/<issue>/` and name the path in the RESULT line; never inline an artifact body into it.
  > <!-- /guild:result-contract -->
  > CANDIDATES: <number · title · one-line scope · current stage, for each>.

**Tech Lead** (dependencies and size):
- `subagent_type`: `general-purpose`, `model`: `sonnet`, `description`: `tech-lead sprint select`
- `prompt`:
  > Adopt the persona in `.claude/agents/tech-lead.md`. From the same CANDIDATES (below) and `docs/standards/architecture.md`, produce (a) the **dependency relations** among them — which is a foundation for which, using the `Depends on: #<n>` notes in the bodies as input and correcting them where the code says otherwise — and (b) a **size** verdict per candidate: single dev-unit ✅, or ⚠ **likely to split at design**. Do NOT read the product-owner's output; judge independently. Write to a FILE `docs/specs/sprint-<slug>/deps.md`. Return one `>>> RESULT <<<` line. CANDIDATES: <same as above>.

Collect both RESULTs and **arbitrate as the leader** into one candidate set plus a dependency edge list.

⚠ **A `⚠ likely to split` candidate is excluded by strong default.** A split that happens *during* the run is handed back to the human (`run.md`), so the sprint stops on that issue. Include one only if the human overrides after being told this.

## Phase 3 — Capacity (leader judgment — the human is not asked)

| Input | Source |
|---|---|
| past performance | `config.json` → `sprint.capacity` and `sprint.history` (written by `retro`) |
| size per candidate | tech-lead |
| dependency chain depth | `sprint_dag.py --mode depth` (Phase 4) |
| readiness | the product-owner's three dimensions |

No history (first sprint) → **be conservative**: the top ~5 candidates with no `unclear`
dimension, and a chain depth within the cap. Record the *reasoning* as a sentence in the
tracking Issue body — `retro` compares against it.

## Phase 4 — Cycles → linearize → order → depth

Write the graph to a temp JSON with the **Write tool** (`_sprint_dag.md` Section F), then one Bash call per mode. **Absorb every exit code and branch on the value** — these are meaningful non-zero codes, not failures (`_sprint_dag.md` Section C).

⚠ **TWO input files, not one.** `cycles` and `linearize` read `deps` (the declaration); `order`, `depth` and `base` read **`base_deps`**, which is step 2's *output*. Passing one file through all four modes therefore asks the last three to read a key that is not there yet. The script now refuses that (exit 64) rather than answering — it used to return issue-number order, `depth 1` and `DEFAULT` for every member, all with exit 0, so nothing warned. **After step 2, write a second file** with each member's `base_deps` set from the `linearize` output, and point steps 3–4 at it.

1. `--mode cycles` → exit **3** means a cycle exists: show the witness path and `FAIL`. **A cycle must be caught here** — reaching an unattended run with one is a deadlock.
2. `--mode linearize` → each member's `base_dep`. This is what gets written to the member table.
3. `--mode order` → execution order. **Reads the step-2 file.**
4. `--mode depth` (**the step-2 file**) with `max_depth` = **`EFFECTIVE_CAP`** — Phase 0 step 5's value when the repo forbids merge commits, otherwise `config.sprint.max_stack_depth` (default 3) → exit **4** means over the cap: report the chain and **propose cutting it**, deferring the tail to the next sprint. A warning plus a proposal, not a block — the human may accept the depth. ⚠ At `EFFECTIVE_CAP = 1` any dependency at all exceeds it, which is the point: the sprint either drops the dependants or the human accepts re-reviewing merged code.

⚠ Linearization adds edges: an originally independent issue can end up stacked on another so that a fan-in node has a single base. Mark those in the member table (`⚠ 선형화로 추가된 의존`) and say so in Phase 5 — the human needs to know that #102's PR now cannot merge before #101's.

## Phase 5 — Present, then stop (attended)

```
후보 12개 중 7개를 이번 스프린트로 제안합니다.

▎목표: <한 문장>

  ① #101  결제 상태 머신 정리   base: —        🏗 기초   readiness: clear/clear/clear
  ② #102  타임아웃 재시도       base: #101 ⚠   (원래 독립 — #104의 fan-in을 체인으로)
  ③ #104  실패 로그 집계        base: #102     스택 3단  원래 의존: #101, #102
  ④ #103  영수증 재발행         base: —                  readiness: clear/partial/clear
  …
  제외 5개: #108(Success=unclear) · #110(⚠ 분할 예상) · …
  용량 판단: 7개 — <근거 한 줄>
  최대 스택 깊이: 3 (상한 3 — 경계)
  머지 전략: merge commit 허용 ✅ · 브랜치 자동삭제 ✅

이대로 만들까요? (드롭 / 추가 / 재범위 / 재정렬 요청 가능)
```

Handle edits and re-present until the human approves. **Create nothing** without `--create` or an explicit approval — opening a sprint and rewriting member bodies are outward, hard-to-reverse actions (INV1).

**Unattended** (`GLD_UNATTENDED=1`): do not create. Return `OK: unattended — sprint proposal requires a human`. ⚠ Do **not** use `OK PAUSE: needs-human`: that return obliges marking an Issue with the `guild:needs-human` label plus a comment so the pause is discoverable (`_handoff.md` Section H), and there is no tracking Issue yet to mark.

## Phase 6 — Create (`--create` or explicit approval)

**Order matters. The label goes on before any member body is touched.**

1. **Create the tracking Issue** — title `Sprint: <goal>`, body from the template below, **no label yet** (temp file + `--body-file`).
2. **Attach the label** — `gh issue edit <tracker> --add-label "guild:sprint"`. If the label is missing this dies here, with **every member body still intact**.
3. **Add the back-reference** to each member body — a `Sprint: #<tracker>` line. Read → splice → full rewrite, **with the truncation check** (`_sprint_dag.md` Section A). One member per Bash call; a failure mid-way is resumable because step 4's idempotency check re-derives what exists.
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
| **non-members** (Phase 1b) | `{"issue":120,"column":"backlog"}` or `{"issue":121,"column":null}` | **on** |

⚠ **The two sets are disjoint — subtract the selected members from the triage writes.** Phase
1b judges the whole candidate set and Phase 2 then picks members out of that same set, so an
issue can appear in both lists. Entries are applied in order against one pre-read snapshot,
so a `backlog` entry landing after the member's `ready` entry leaves that member sitting in
`Backlog` for the entire sprint. Members are seeded by the member rows; the triage rows cover
everything else.

⚠ **Clear the `needs_human` field on every member.** A carryover member arrives still carrying
`guild:needs-human` (that is the designed path — 02번 §10.4), and the supervisor left
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

Body template:

```markdown
# Sprint: <목표 한 문장>

<!-- guild:sprint:plan -->
plan-hash: <sprint_dag.py --mode hash 의 출력>
- 목표: <한 문장>
- 시작: <YYYY-MM-DD>
- 용량 판단: <N>개 — <근거>
- 머지 전략: <merge commit 허용 여부> · 브랜치 자동삭제 <여부>
- 스택 깊이 상한: <유효 상한 N>
- 상한 근거: <"config" | "merge-commit-forbidden" | "human-override">

## 멤버 (실행 순서 · 의존성 정본)
| # | 이슈 | base 의존 | 원래 의존 | 비고 |
|---|---|---|---|---|
| 1 | #101 | — | — | 🏗 기초 |
| 2 | #102 | #101 | — | ⚠ 선형화로 추가된 의존 |
| 3 | #104 | #102 | #101, #102 | fan-in → 체인 · 깊이 3 |
<!-- /guild:sprint:plan -->

보드: <config.sprint.board.url>
```

⚠ **The board line goes OUTSIDE the marker.** Everything between `<!-- guild:sprint:plan -->`
and its closing marker is the dependency source of truth, and `sprint_dag.py --mode hash`
hashes it — a line added inside would change `plan-hash` on the next read and halt `run` with
`plan-hash-mismatch`. Omit the line entirely when no board is configured; do not write an
empty one.

**Idempotency.** A re-run finds the open tracker at Phase 0 step 4 and adds only what is missing. A tracker that was created but never labelled is found by its body marker:
```bash
gh issue list --state open --limit 200 --search '"guild:sprint:plan" in:body' --json number,title
```
⚠ GitHub's search index is eventually consistent, so a tracker created seconds ago may not appear yet. If the search is empty but Phase 0 step 2 said the label is missing, say so plainly rather than creating a second tracker.

## Return

`OK: sprint #<n> created with <N> members` · `OK: proposed <N> members (dry-run)` ·
`OK: unattended — sprint proposal requires a human` · `NEEDS_HUMAN: <one-line>` · `FAIL: <reason>`

On creation, say what to do next: *"`/gld sprint run`으로 무인 실행하세요. 상태는 `/gld sprint daily`."*

---

## Hard rules

- **Default dry-run.** Nothing is created without `--create` or explicit approval (INV1).
- **The label goes on before member bodies are edited** — otherwise a missing label leaves rewritten bodies and an unfindable orphan.
- **`plan` selects and orders; it does not design or implement.** It stops at a filled container.
- **Every body rewrite carries the truncation check** — member bodies *and* the tracking Issue's. A truncated read must not be written back.
- **A cycle fails here, never later.**
- **Members get no new `guild:*` label** (`_sprint_dag.md` Section A).
- **The member table is written once.** After creation it is immutable and guarded by `plan-hash`; changing membership means running `sprint plan` again.
- All Bash per `_bash_rules.md`; every issue body via temp file + `--body-file`.
