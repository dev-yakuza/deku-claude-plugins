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

## Phase 2 — Select and order (product-owner ∥ tech-lead, parallel)

As the leader, spawn BOTH role sub-agents in one message (independent, concurrent). Reuse the prompt *shape* of `plan.md` Phase 1, but the job is **selection, not decomposition**.

**Product Owner** (value):
- `subagent_type`: `general-purpose`, `model`: `sonnet`, `description`: `product-owner sprint select`
- `prompt`:
  > Adopt the persona in `.claude/agents/product-owner.md`. Read the candidate list below and `docs/standards/charter.md`. Propose (a) **one sentence** naming what this iteration is for, and (b) the candidates that serve it, in priority order. For each candidate rate the three readiness dimensions of `_readiness.md` — **Goal / Constraint / Success-criteria** — as `clear` / `partial` / `unclear` (ASCII machine tokens, never localized). **Recommend excluding any candidate with an `unclear` dimension** and say why: unattended, the leader would have to guess that gap alone. Write the result to a FILE `docs/specs/sprint-<slug>/po.md` (do not paste it back). Return one `>>> RESULT <<<` line per `_handoff.md` Section C. CANDIDATES: <number · title · one-line scope · current stage, for each>.

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
```

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
