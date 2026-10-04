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
gh issue list --state open --limit 200 --json number,title,body,labels --jq '{total: length, candidates: [.[] | {number, title, body, labels: [.labels[].name]}]}'
```

⚠ **`body` stays here on purpose — it is the material, not overhead.** Phase 1b judges each
candidate 착수 가능 vs 구체화 필요 **by reading it**; a narrowed read would make that judgment
from a title. Measured on `dev-yakuza/one-man-company`: 135,753 B over **51** open Issues
(≈2.7 KB each) — that is the work, and the same conclusion the token work reached about
Write/Agent/Edit. ⚠ Do **not** "optimise" this into a title-only scan.
⚠ Excluding the label classes below in `jq` saves nothing worth having either — measured, **0 of
51** open Issues carried `guild:done` / `guild:sprint` / `guild:child`. Filter them client-side
as before.

**What did change: `total` now comes back in the same call**, so the truncation check below no
longer needs a second `--jq 'length'` invocation. An added turn re-bills the whole prefix, and a
check that costs a turn is a check that gets skipped.

Exclude: `guild:done` · `guild:sprint` (trackers) · `guild:child` (they arrive through a parent) · any Issue already a member of an open sprint (`_sprint_dag.md` Section A). ⚠ Do **not** exclude a `guild:children` parent — if one is taken, `run` handles it per the split rules and may hand it back to the human.

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

**When REFACTOR SLOT is `on`, first fetch the default branch** — the tech-lead's git reads go
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

As the leader, spawn BOTH role sub-agents in one message (independent, concurrent). Reuse the prompt *shape* of `plan.md` Phase 1, but the job is **selection, not decomposition**.

**Product Owner** (value):
- `subagent_type`: `general-purpose`, `model`: the role file's `model:` frontmatter (`_model_tiering.md` Section 0 — `sonnet` when absent), `description`: `product-owner sprint select`
- `prompt`:
  > Adopt the persona in `.claude/agents/product-owner.md`. Read the candidate list below and `docs/standards/charter.md`. Propose (a) **one sentence** naming what this iteration is for, and (b) the candidates that serve it, in priority order. For each candidate rate the three readiness dimensions of `_readiness.md` — **Goal / Constraint / Success-criteria** — as `clear` / `partial` / `unclear` (ASCII machine tokens, never localized). **Recommend excluding any candidate with an `unclear` dimension** and say why: unattended, the leader would have to guess that gap alone. **Do not select a candidate tagged `refactor-slot`** (an orphaned refactor-slot draft — the slot logic handles it), **and rate every candidate tagged `refactor` or `refactor-slot`, whether or not you selected it** — the leader may take one as the sprint's refactor slot and needs your ratings to do so. Write the result to a FILE `docs/specs/sprint-<slug>/po.md` (do not paste it back).
  > <!-- guild:result-contract -->
  > Return EXACTLY one status line, preceded by a `>>> RESULT <<<` sentinel on its own line. Anything before the sentinel is ignored. Status is one of `DONE` / `DONE_WITH_CONCERNS: <one-line>` / `BLOCKED: <one-line>` / `NEEDS_CONTEXT: <one-line>` / `FAIL: <reason>`. **Artifacts are passed as files, not pasted** — write to the working tree or `docs/specs/<issue>/` and name the path in the RESULT line; never inline an artifact body into it.
  > <!-- /guild:result-contract -->
  > CANDIDATES: <number · title · one-line scope · current stage · tag (`refactor-slot` | `refactor` | `—`), for each>.

**Tech Lead** (dependencies and size):
- `subagent_type`: `general-purpose`, `model`: the role file's `model:` frontmatter (`_model_tiering.md` Section 0 — `sonnet` when absent), `description`: `tech-lead sprint select`
- `prompt`:
  > Adopt the persona in `.claude/agents/tech-lead.md`. From the same CANDIDATES (below) and `docs/standards/architecture.md`, produce (a) the **dependency relations** among them — which is a foundation for which, using the `Depends on: #<n>` notes in the bodies as input and correcting them where the code says otherwise — and (b) a **size** verdict per candidate: single dev-unit ✅, or ⚠ **likely to split at design**, plus the source files each candidate will most likely touch. Do NOT read the product-owner's output; judge independently. **When REFACTOR SLOT is `on`**, also produce (c) **one refactor-slot proposal** (rules: the "Refactor slot" section of `<<SKILL_DIR>>/commands/sprint/plan.md` — read that section before writing (c), not the whole file). Write to a FILE `docs/specs/sprint-<slug>/deps.md`. Return one `>>> RESULT <<<` line. CANDIDATES: <same as above>. REFACTOR SLOT: <`on` | `off`>. DEFAULT BRANCH: <the repo's default branch name — the leader has already fetched `origin/<it>` — or `unavailable`>. PAST SLOTS: <the `refactor` field of every `config.sprint.history` entry that has one, or `none`>. VISUAL: <available or not per `_handoff.md` Section L.1 — `available` with `visual.packages` and `visual.tests`, or `unavailable`> (the gap check's visual half needs it; you are not reading config.json yourself).

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
excluded from this sprint's slot.

The tech-lead fills (c) in this order and stops at the first that yields a **ready**
candidate — all three readiness dimensions `clear` **and** size ✅ (the bar below). A
candidate that fails it does not end the search; go on to the next step:

0. **A resumed slot** — a candidate tagged `refactor-slot` (Phase 1). It is a draft an
   earlier `plan --create` made and the human approved, orphaned when that run died before
   the tracker existed (Phase 6 step 0). Take it ahead of everything else and judge it
   by the draft's bar (the tech-lead's own ratings), not the existing-Issue bar — otherwise a
   re-run drafts a second Issue beside it. Run the gap check (below) on its **Files** unless its
   body already carries `<!-- guild:safety-net -->`.
1. **An existing candidate tagged `refactor`** (Phase 1). **Run the gap check on it too** — an
   existing refactor Issue is the slot's most common source, and "existing tests stay green" is
   exactly as empty for it as for a draft. A gap found here becomes a Safety net that Phase 6
   step 0 appends to the existing Issue (after the human approves it in Phase 5). Prefer one whose area overlaps the
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
2b. **A safety-net-only draft** — only when step 2 found no refactor worth drafting (or a step-2
   draft is converted for size at arbitration — see the Safety net bullets below). Among the
   same intersecting hotspot files, take the one with the clearest **gap** (below) and draft an
   Issue that adds only the net: tests (and, where they apply, visual cases) for that file's
   public behavior, **no production code change**. It is weaker than a refactor — it removes no
   difficulty, it makes the next change safer — so it needs the gap evidence, not just a hotspot:
   a hotspot that is already tested is no reason to fill the slot.
3. **Nothing qualifies** → `none: <token>` — `no-candidate` (no hotspot overlaps this sprint's
   work, or no change found that would make it easier, and no hotspot with a safety-net gap).

**The gap check** (every step 0–2b candidate, the same ≤ ~3 files — no new budget). It is
**per behavior, not per file**: in a repo where every component has a colocated test, "is the
file imported by a test" is always yes and finds nothing, while the bugs keep coming. Two
sources name the behaviors, both from data you already have:
- **Fix commits that changed no test** — for each hotspot file, the window's `fix:` commits that
  touched it (step 2's `git log … --name-only` output already lists each commit's files; for a
  step-0/1 candidate run that same call scoped to its Files): a `fix:` commit whose file list has
  **no test path** fixed a behavior no test was made to hold. Read that commit's subject (and, if
  unclear, its diff of the hotspot file — at most ~3 commits) and name the behavior. That is a
  **test gap**, and the strongest evidence this check has.
- **Behaviors this sprint's members will lean on** — from (b)'s per-candidate files: the public
  functions / component states of the hotspot file those members call. One Grep per behavior
  name in the file's tests (an assertion that exercises it, not a mention): none → a test gap.
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
  visual gap, and any **test-support files** the net needs (a test helper or fixture, named by
  path — the only non-test files the net's commit may touch). **Each line is also a
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
  human declines creating it, a 2b is not offered (`skip (not-ready)`).
- When a step-2 draft is rejected at arbitration **only for size**, and its Safety net alone
  passes the size gate, the leader converts it to a 2b instead of skipping — no re-spawn: the
  net is already in the draft. Record the dropped refactor in the 2b's **Why** (*"deferred: <the
  refactor's title>"*) so the next sprint's step 2 finds it again with the code covered.

⚠ **PAST SLOTS is a check, not a quota.** Each entry is `{issue, outcome, paths, merged_at,
closed_at}` (`retro.md` Phase 4). Read `origin/<default-branch>` (fetched by the leader), not
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
  that evidence in (c).
- An entry whose `paths` key or date key is **absent** (a slot recorded before these fields
  existed) gives no basis either way — ignore it rather than guessing. A `null` date is not
  absence: `merged_at` is `null` on every `refused` entry by design.

**The leader's arbitration of (c)** — the slot gets **no exemption** from the gates every
other member passes, and its readiness gate is **stricter**: all three dimensions `clear`, where
a feature member may carry a `partial`. An optional member has no reason to carry a gap that
unattended the leader would have to guess alone:
- any readiness dimension below `clear` → do not take it. For a **draft** record
  `skip (not-ready)`; a step-0 or step-1 pick goes to the re-spawn bullet below instead.
- size ⚠ **likely to split** → the same: a draft records `skip (not-ready)`, a step-0 or step-1
  pick goes to the re-spawn.
- ⚠ **A new draft was never in the product-owner's CANDIDATES**, so its readiness comes from
  the tech-lead's own **Readiness** ratings in (c). Re-read the draft's Success-criteria
  yourself before accepting a `clear` — the author of a draft is the one reader least likely to
  see its gap. For an existing Issue (step 1), the product-owner's ratings and the
  tech-lead's must both be `clear`; a resumed slot (step 0) is judged as a draft.
- ⚠ **The slot must prepare this sprint's work.** The tech-lead chose it from the whole
  candidate set, in parallel with the product-owner, so it cannot know which candidates
  become members. Once Phase 3 has cut the feature picks to capacity, require that
  **Prepares** names at least one selected feature member, or that its **Files** share a file
  with one. Neither → it pays down code nobody in this sprint touches; reject it (next
  bullet). Re-check this after **any** change to the feature set — the Phase 3 capacity cut, a
  Phase 3 refill, a Phase 4 cut, a Phase 5 edit.
- ⚠ **Rejecting a pick does not empty the slot — one re-spawn.** A rejected step-0 or step-1
  pick, or a draft rejected **only** because it prepares no selected member (the draft was
  aimed at the whole candidate set; a hotspot under the actual members may well exist), gets
  **one** re-spawn per `plan` run, and it always runs **after the Phase 3 capacity cut** — a
  readiness or size rejection made during Phase 2 waits until then, so the re-spawn gets the
  real member list. Spawn the tech-lead once more, asking for **(c) only** —
  *"exclude #<n>[, #<m>]; continue the search order from where those were; draft against the
  selected feature members' files"* — with the same CANDIDATES (tags included), REFACTOR SLOT, VISUAL, DEFAULT BRANCH and
  PAST SLOTS as the first spawn, plus the selected feature members and the path of `deps.md`
  (its (b) per-candidate files are step 2's input). It writes `deps-slot.md`, leaving
  `deps.md`'s (a)/(b) untouched; from then on Phase 4 reads the slot's **Files** and
  **Prepares** from `deps-slot.md`. Pass the rejected numbers, not *"step 1 is exhausted"*: another
  existing `refactor` Issue may still qualify. Arbitrate that (c) the same way; if it is
  rejected too, or comes back `none`, the slot ends in a `skip` keyed on the **final**
  attempt's reason — `skip (no-candidate)` when it prepares no member or came back `none`,
  `skip (not-ready)` when it failed readiness or size. A draft rejected for readiness or
  size ends in `skip (not-ready)` without a re-spawn.
  From then on Phase 5's evidence lines and Phase 6 step 0's Issue body also come from
  `deps-slot.md`.
- ⚠ **A rejected pick the product-owner ranked as a feature goes back to the feature picks**
  at its product-owner rank and competes under the feature gates (a `partial` is allowed
  there). Rejecting it as the slot is not rejecting it as work the product-owner wanted. Redo
  the Phase 3 cut with it at that rank — it may displace the lowest-ranked feature; the sprint
  never holds more than capacity. The same applies when the human drops such a slot in Phase 5
  (`skip (human-declined)` removes its slot role, not the Issue), unless the human drops the
  Issue itself.
- otherwise it is a member, tagged `🧹 리팩토링 슬롯` in the member table. A draft is **not
  created** here — Phase 6 step 0 creates it, after the human approves.
- ⚠ **One Issue, one role.** A `refactor` or `refactor-slot` candidate the product-owner also
  ranked as a feature pick is the slot, not both — remove it from the feature picks, or the sprint holds
  one fewer member than the capacity reasoning says.

Collect both RESULTs and **arbitrate as the leader** into one candidate set plus a dependency edge list.

⚠ **A `⚠ likely to split` candidate is excluded by strong default.** A split that happens *during* the run is handed back to the human (`run.md`), so the sprint stops on that issue. Include one only if the human overrides after being told this.

## Phase 3 — Capacity (leader judgment — the human is not asked)

| Input | Source |
|---|---|
| past performance | `config.json` → `sprint.capacity` and `sprint.history` (written by `retro`) |
| size per candidate | tech-lead |
| dependency chain depth | `sprint_dag.py --mode depth` (Phase 4) |
| readiness | the product-owner's three dimensions |
| refactor slot | Phase 2's arbitration of (c) |

No history (first sprint) → **be conservative**: the top ~5 candidates with no `unclear`
dimension, and a chain depth within the cap. Record the *reasoning* as a sentence in the
tracking Issue body — `retro` compares against it.

⚠ **The refactor slot counts inside the capacity, not on top of it.** Capacity is the human's
PR-review throughput (`retro.md` Phase 4), and a refactor PR is reviewed like any other. A
capacity of 5 with the slot filled is 4 feature members plus the slot. Do **not** drop the slot
to make room for a fifth feature unless capacity is 1 — then record `skip (capacity)`.
⚠ **A seat the slot gives back is refilled.** Whenever the slot leaves after the capacity
cut, **for any reason** (the prepares check below the cut, `skip (stack-cap)` in Phase 4, the
human dropping it in Phase 5), take the next-ranked
feature pick that passes the usual gates into its seat and redo Phase 4. Otherwise a slot that
did not happen silently costs the sprint a feature member — the opposite of its hard rule.
No such pick → leave the seat empty and say so in **용량 판단**.
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
  by issue number (in `linearize` and in `order`), and `run` recomputes the order from the
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
record the override like any other over-cap acceptance.

1. `--mode cycles` → exit **3** means a cycle exists: show the witness path and `FAIL`. **A cycle must be caught here** — reaching an unattended run with one is a deadlock.
2. `--mode linearize` → each member's `base_dep`. This is what gets written to the member table.
3. `--mode order` → execution order. **Reads the step-2 file.**
4. `--mode depth` (**the step-2 file**) with `max_depth` = **`EFFECTIVE_CAP`** — Phase 0 step 5's value when the repo forbids merge commits, otherwise `config.sprint.max_stack_depth` (default 3) → exit **4** means over the cap: report the chain and **propose cutting it**, deferring the tail to the next sprint. A warning plus a proposal, not a block — the human may accept the depth. ⚠ At `EFFECTIVE_CAP = 1` any dependency at all exceeds it, which is the point: the sprint either drops the dependants or the human accepts re-reviewing merged code.

⚠ Linearization adds edges: an originally independent issue can end up stacked on another so that a fan-in node has a single base. Mark those in the member table (`⚠ 선형화로 추가된 의존`) and say so in Phase 5 — the human needs to know that #102's PR now cannot merge before #101's.

## Phase 5 — Present, then stop (attended)

```
후보 12개 중 7개를 이번 스프린트로 제안합니다.

▎목표: <한 문장>

  ① #103  영수증 재발행         base: —        🏗 기초   readiness: clear/partial/clear
  ② #104  실패 로그 집계        base: #103               원래 의존: #103
  ③ #(신규) 결제 상태 갱신 경로 통합  base: —        🧹 리팩토링 슬롯
  ④ #101  결제 상태 머신 정리   base: #(신규)            원래 의존: #(신규)
  ⑤ #102  타임아웃 재시도       base: #101     스택 3단  원래 의존: #101
  …
  🧹 리팩토링 슬롯: #(신규) «결제 상태 갱신 경로를 한 곳으로» — #101이 이 위에 쌓입니다 (#102는 #101 위)
       근거: src/payment/state.ts · 최근 fix: 커밋이 몰림 · 갱신 경로 3곳 중복
       성공 기준: 기존 테스트 green · applyTransition() 하나로 통합
       안전망: state.ts · applyTransition() · 취소 후 재시도 시 상태 유지 외 2건 (리팩토링 전 커밋에서 green)
  제외 5개: #108(Success=unclear) · #110(⚠ 분할 예상) · …
  용량 판단: 7개 — <근거 한 줄>
  최대 스택 깊이: 3 (상한 3 — 경계)
  머지 전략: merge commit 허용 ✅ · 브랜치 자동삭제 ✅

이대로 만들까요? (드롭 / 추가 / 재범위 / 재정렬 요청 가능)
```

When the slot is empty, the line says why instead of disappearing —
`🧹 리팩토링 슬롯: 비움 (no-candidate) — 이번 후보들이 건드리는 hotspot 이 없습니다`.
The `안전망:` line appears only when the draft carries a Safety net (one line: file · the first
behavior · `외 N건`). A 2b draft is shown as `🧹 리팩토링 슬롯 (안전망만): #(신규) «…»` with its
`근거:` naming the gap (`테스트 없음` / `시각 테스트 없음`) and `성공 기준:` ending in
`프로덕션 코드 변경 없음` — the human should see at a glance that this slot adds coverage, not a
refactor. When the gap check reported VISUAL `unavailable` for a screen it covers, add
`(시각 안전망 없음 — 이 환경에서 렌더링 불가)` to that `안전망:` line. For an existing or resumed
slot that gains a net, the `안전망:` line ends with `(Issue 본문에 추가 예정)`.
When the slot — of any origin: draft, resumed or existing — will not carry `type:refactor`, and
**Phase 0 step 2's label list** has no `type:refactor`, add one line:
`  ⚠ 이 레포에 type:refactor 라벨이 없습니다 — 만들까요? (없으면 기능 흐름으로 개발됩니다)`.
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
   the marker Phase 1 finds on a re-run. **An existing or resumed slot that gained a Safety net**
   (approved in Phase 5): read its body (`gh issue view <n> --json body --jq .body`), append the
   Safety net section (heading + `<!-- guild:safety-net -->` + lines + rules) and the same lines
   to its Success-criteria section (or a new one), and write it back with `gh issue edit <n>
   --body-file <temp>` — read-then-replace, never a blind overwrite (a truncated read → do not
   write; NEEDS_HUMAN). Temp file + `--body-file`; add `--label type:refactor`
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
   without it and say the slot will run as a feature.

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
- 리팩토링 슬롯: <"#<n> (existing)" | "#<n> (drafted)" | "skip (<disabled|no-candidate|not-ready|capacity|stack-cap|human-declined|ad-hoc>)">

## 멤버 (실행 순서 · 의존성 정본)
| # | 이슈 | base 의존 | 원래 의존 | 비고 |
|---|---|---|---|---|
| 1 | #101 | — | — | 🏗 기초 |
| 2 | #102 | #101 | — | ⚠ 선형화로 추가된 의존 |
| 3 | #104 | #102 | #101, #102 | fan-in → 체인 · 깊이 3 |
<!-- /guild:sprint:plan -->

보드: <config.sprint.board.url>
```

⚠ **The 리팩토링 슬롯 line is always written**, filled or not, and its value is a token, not
prose — `retro` reads it to tell *"no slot was taken"* from *"the slot's PR was refused"*, and
an omitted line reads as neither. The slot's own row carries `🧹 리팩토링 슬롯` in 비고. On the
ad-hoc path (`run.md`, numbers given to `run`) Phase 2 never ran: write `skip (ad-hoc)`. A
`type:refactor` Issue among those numbers is an ordinary member there, not a slot — the slot is
a `plan` decision, and `retro` reads `skip:ad-hoc` as exactly that.

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
- **The refactor slot is reserved, never forced.** It passes the size gate every member passes and a stricter readiness gate (all three `clear`), shares the capacity (a filled slot takes one seat; a seat it gives back is refilled), never costs a feature member its place in the stack, must prepare at least one selected member, and an empty slot is recorded with its reason token.
- **Members get no new `guild:*` label** (`_sprint_dag.md` Section A).
- **The member table is written once.** After creation it is immutable and guarded by `plan-hash`; changing membership means running `sprint plan` again.
- All Bash per `_bash_rules.md`; every issue body via temp file + `--body-file`.
