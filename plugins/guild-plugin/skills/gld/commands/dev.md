# DEV

**Drive the full spine on one GitHub Issue: `analyze → design → execute → test → qa → done`.** Main-session FSM. The main session **embodies the leader** — it loads `.claude/agents/leader.md` and uses that persona to assemble the team, run gates, arbitrate, and judge completion. Each stage is executed by reading its wrapper command inline; the wrapper spawns the role sub-agents for that stage.

`$1` = Issue number.

> **Bash**: simple calls only (`<<SKILL_DIR>>/commands/atoms/_bash_rules.md`). State model + labels + handoff: `<<SKILL_DIR>>/commands/atoms/_handoff.md`.
> **Output language**: all human-readable output (comments, discuss questions, narration, RESULT summaries) is in `config.language`; sub-agent prompts carry that instruction (`_handoff.md` Section K). Machine tokens stay ASCII.

---

## Phase 0 — Setup

1. **Validate `$1`**: must be an Issue number. Confirm it exists and is not a PR:
   ```bash
   gh issue view $1 --json url --jq .url
   ```
   Empty/error → `FAIL: Issue #$1 does not exist`. URL contains `/pull/` → `FAIL: #$1 is a Pull Request, not an Issue`. Stop on either.

2. **Confirm Guild is initialized** (its own Bash call):
   ```bash
   ls .claude/guild/config.json
   ```
   Absent → report "Guild is not initialized in this repo. Run `/gld init` first." Stop.

3. **Load the leader persona**: Read `.claude/agents/leader.md`. Adopt it for the rest of this command — team assembly, delegation, gate arbitration, and completion judgment are done *as the leader*.

4. **Resolve owner/repo** once (`_handoff.md` Section F); hold the literal value.

5. **Detect run mode** (its own Bash call): `printenv GLD_UNATTENDED`. If `1` → **unattended mode** (invoked by `/gld batch`·`/gld sprint` supervisor): the leader stands in for the human at gates and never calls `AskUserQuestion` (`_handoff.md` Section H). Otherwise attended (default).

---

## Phase 1 — Determine current stage (from label)

Read the Issue's labels:
```bash
gh issue view $1 --json labels --jq '[.labels[].name]'
```

Map to the current stage (`_handoff.md` Section A):
- contains **`guild:sprint`** → this Issue is a **sprint container**, not work: `FAIL: #$1 is a sprint tracking Issue — use /gld sprint daily`. Stop. (It carries no stage label, so without this branch the next row would treat it as a fresh Issue, add `guild:analyze`, and analyze the sprint plan as a requirement.)
- contains `guild:done` → already complete; report and stop (or, if the user wants to re-run test, they invoke `/gld test` directly).
- contains `guild:children` → this is a **split parent** already in orchestration → skip the normal spine and go straight to **Phase 2b** (child orchestration). Do not run analyze/design on it again.
- contains `guild:qa` → resume at **qa**.
- contains `guild:test` → resume at **test**.
- contains `guild:execute` → resume at **execute**.
- contains `guild:design` → resume at **design**.
- contains `guild:analyze` → resume at **analyze**.
- none of the above → fresh Issue; start at **analyze**. Add the `guild:analyze` label now:
  ```bash
  gh issue edit $1 --add-label "guild:analyze"
  ```

Determine work type from the Issue's `type:` label (`type:feature|bug|refactor`) if present; default to feature. **This is provisional, not final** — **analyze may reclassify** (reality differs from the label; it can also split off a `type:refactor` sub-issue first), and when it does, `analyze.md` Step 3 updates the `type:` label on GitHub as part of reclassifying (so the change is durable, not just prose in the analysis comment). The work type selects the **execute variant** (Phase 2):
- `type:bug` → **debug** (reproduce → root-cause → fix + regression test)
- `type:refactor` → **refactor** (behavior-preserving transform; existing tests green)
- otherwise (feature) → **implement** (TDD red→green→refactor)

**Do not hold this as final if analyze hasn't run yet in this session** — when the spine starts at (or passes through) `analyze` before reaching `execute`, **re-read the `type:` label immediately before Phase 2 runs the execute-stage wrapper** (its own Bash call), not the value read here at Phase 1 start; analyze may have changed it in between. Only skip the re-read when this run resumes directly at `execute` or later (analyze already ran in a prior session, so its output — and any reclassification — is already final and reflected in the current label).

**Assemble the cast (as the leader).** With the work-type known, size up the change surface (Issue body + AC + hotspots) and decide which roster specialists this task needs — following the assembly rules in `leader.md` ("팀 조립 규칙") and the participation model in `_handoff.md` Section G. The **spine roles always run**; every other installed role joins only when its trigger matches; **gate reviews** (designer UI/UX, security, infra CI/deploy/env/IaC) are inserted before advancing when risk matches. Read the roster from Section G rather than a list held here — a repo may have grown or pruned it via `evolve` HR, and a stale inline list would silently exclude a role the repo actually has. Hold this cast decision — each stage wrapper convenes the roles it owns (e.g. design convenes designer when the change is UI). When in doubt, convene minimally and let a downstream gap pull a specialist in later. Surface non-obvious/risky assembly choices to the human.

---

## Phase 2 — Run the spine

From the current stage, run each stage in order until `guild:done` or a stop condition. For each stage, **read the wrapper command inline and execute it** for Issue `$1`:

| Stage | Wrapper to read & execute |
|---|---|
| analyze | `<<SKILL_DIR>>/commands/analyze.md` |
| design | `<<SKILL_DIR>>/commands/design.md` |
| execute | the selected variant: `implement.md` (feature) · `debug.md` (`type:bug`) · `refactor.md` (`type:refactor`) — re-read from the Issue's current `type:` label right before this row runs (Phase 1's read was provisional; see Phase 1's note on analyze possibly reclassifying since) |
| test | `<<SKILL_DIR>>/commands/test.md` |
| qa | `<<SKILL_DIR>>/commands/qa.md` |

Each wrapper **owns its own label transition** on success (single source — `_handoff.md` Section A) and returns a stage-level line (`_handoff.md` Section D). dev reads the returned line only to sequence the next stage:

- **`OK ADVANCE: <next>`** → the wrapper has already set `guild:<next>`. Continue by running `<next>`'s wrapper.
- **`OK SPLIT: <N> children`** (from design) → design set the parent to `guild:children` with `N` children now existing in total (`N` isn't necessarily how many design just created this run — a resumed split may have created only the remaining few; Phase 2b re-derives the actual set independently regardless, so `N` is informational only). (`_handoff.md` Section I). **Go to Phase 2b** (child orchestration) — do not run execute on the parent.
- **`OK DONE`** (from qa) → the wrapper has set `guild:done`. Report completion. Stop.
- **`NEEDS_HUMAN: <one-line>`** → a discuss/verify gate needs a human decision. **Attended**: as the leader, surface the options and ask the user (`AskUserQuestion`), then re-run the same stage wrapper with the decision. Do NOT auto-decide — discuss refuses to proceed until the user chooses. **Unattended (`GLD_UNATTENDED=1`)**: there is no human — stages already self-resolve low/medium gates and return `OK PAUSE: needs-human` for high-stakes ones (`_handoff.md` Section H), so a `NEEDS_HUMAN` should not normally arrive here; if it does, treat it as `OK PAUSE: needs-human` (do NOT call `AskUserQuestion`).
- **`NEEDS_CONTEXT: <one-line>`** → a required upstream artifact is missing (design without analyze output, execute without a design skeleton). The wrapper has **not** advanced the label. Do not treat this as `FAIL`: re-enter the spine at the stage that produces the missing artifact and run forward from there. If that stage's label is already set — it ran but left nothing behind — stop and surface it as a state inconsistency the human should see (`NEEDS_HUMAN` handling above, attended; `guild:needs-human` + clean stop, unattended). Do not re-run the same wrapper unchanged; it will return the same line.
- **`OK PAUSE: <one-line>`** → leave label as-is; report where it paused and how to resume (`/gld resume $1`). **Unattended**: a `needs-human` pause has already marked the Issue (`guild:needs-human` label + `<!-- guild:needs-human -->` comment, Section H); stop **cleanly** so the supervisor moves to the next Issue. Stop.
- **`FAIL: <reason>`** → stop; report the reason.

**Leader judgment between stages**: after each `OK ADVANCE`, briefly confirm the produced output is coherent enough to feed the next stage (completion judged by downstream consumability). If a gap is obvious, loop back rather than advancing.

---

## Phase 2b — Child orchestration (split parents only)

Reached when the parent Issue `$1` is at `guild:children` (Phase 1) or design just returned `OK SPLIT` (Phase 2). The parent's work is the sum of its children, run **sequentially, one full spine each** (`_handoff.md` Section I).

1. **Discover children** (its own Bash call — substitute the **literal** parent number for `<parent>`; do NOT splice a shell `$1` into the jq string, per `_bash_rules.md` / Section I. Ascending order = execution order):
   ```bash
   gh issue list --label guild:child --state all --limit 200 --json number,title,body,labels --jq '[.[] | select((.body // "") | test("Parent Issue: #<parent>([^0-9]|$)"))] | sort_by(.number) | .[] | {number, title, labels: [.labels[].name]}'
   ```
   None found → `FAIL: parent #$1 is at guild:children but no child Issues reference it` (state inconsistency — report, do not guess). This should be unreachable via normal operation — `design.md`/`plan.md` only set `guild:children` **after** every child already exists, so their own flow can never produce a `guild:children` parent with zero discoverable children. Reaching this FAIL means something outside that flow set the label (a manual GitHub edit, a bug, or a `guild:child` Issue's body/label was altered after creation so the discovery query no longer finds it) — recovery: verify by hand whether children genuinely exist (`gh issue list --label guild:child --state all` and inspect bodies for a `Parent Issue: #$1` line that the query's regex might be missing), fix the mismatch, then re-run `/gld resume $1`.

2. **Drive each pending child through the full spine.** For each child `C` in order whose labels do **not** include `guild:done`:
   - Announce which child is starting (of how many).
   - Run the spine on `C` from `C`'s current label, running each stage wrapper inline (the Phase 2 table — **only** the stage→wrapper mapping applies here, not Phase 2's outer return-handling row; the next bullet is Phase 2b's own return-handling and takes precedence for children) for issue `C` until `C` reaches `guild:done` or a stop condition. A freshly-created child starts at `guild:analyze`. The **leaf-only** invariant holds — a child's design must not re-split (its design returns `NEEDS_HUMAN` if it tries; Section I).
   - **Work-type determination also applies per child**, not just to `$1` at Phase 1: child Issues are created without a `type:` label (design.md's/plan.md's `gh issue create` for a child sets only `guild:child`/`guild:analyze`), so when `C`'s spine reaches the execute row, apply Phase 1's same rule (work-type determination, above) — read `C`'s current `type:` label, default to feature if absent, and re-read right before `C`'s own execute wrapper runs (`C`'s own analyze may reclassify it, exactly as for `$1`).
   - **On child stop before done**: unlike Phase 2's outer handling — where an attended `NEEDS_HUMAN` is resolved inline via `AskUserQuestion` and the *same* stage re-runs — a child's `NEEDS_HUMAN` always halts the whole orchestration loop instead, attended or not. Reason: the human should see the *whole* paused split (which child, how many remain, whether later children even still make sense) before deciding, not get an isolated inline prompt about child N while children N+1..last are silently still queued.
     - `OK PAUSE` / `NEEDS_HUMAN` (attended) → surface it and **stop orchestration here**; report which child paused and that `/gld resume $1` (or `/gld dev $1`) will continue from it. Do not proceed to later children (they may depend on it).
     - `FAIL` → stop; report the child and reason.
     - **Unattended** (`GLD_UNATTENDED=1`): a child that needs a human has already marked itself (`guild:needs-human` + comment, Section H); stop cleanly so the supervisor moves on.
   - On child `guild:done` → continue to the next pending child.

3. When **every** child is `guild:done`, go to **Phase 2c**.

---

## Phase 2c — Parent integration

All children are `guild:done`; verify they combine into a correct whole before closing the parent (`_handoff.md` Section I).

1. As the leader (convene the **tech-lead** for a conformance view), read the parent's analyze/design outputs and each child's PR + test output. Check:
   - **Coverage** — every parent acceptance criterion is satisfied by some child (nothing dropped in the split).
   - **Cross-child consistency** — shared seams/data shapes/interfaces agree across children; no duplicated or orphaned work.
   - **DoD closure** — the parent's Definition of Done items are all addressed.
2. Post the result on the parent under `<!-- guild:integration:output -->` … `<!-- /guild:integration:output -->` (temp-file pattern): what was checked, coverage map (parent AC → child), any gap.
3. **Judge**:
   - Gap found → do NOT close. Attended: `NEEDS_HUMAN: integration gap — <one-line>` (a targeted loop-back to the responsible child, or a new child). Unattended: mark `guild:needs-human` + comment, stop cleanly.
   - Clean → transition the parent. **Also remove `guild:needs-human` in this same call if it's present** (e.g. left over from a prior interrupted integration attempt that found a gap, per the branch above — `_handoff.md` Section A):
     ```bash
     gh issue edit $1 --remove-label "guild:children" --add-label "guild:done" --remove-label "guild:needs-human"
     ```
     Report parent completion (Phase 3).

---

## Phase 3 — Report

On `OK DONE`: summarize what was built (stages run, PR link if any, test evidence). **Nudge the human review** — the PR now awaits the human reviewer (M1 external reviewer, INV1); suggest the guided pair review to make it lighter: "이슈 #$1 완료 (PR #<n> 오픈) — `/gld review $1`로 리스크 가중 가이드 리뷰를 받을 수 있습니다 (이슈 번호를 넣으면 연결된 PR을 자동으로 찾습니다; PR 번호를 직접 넣어도 됩니다)." On pause/fail: state the stage reached and the resume command. Never claim completion without the test stage's verify evidence (`_handoff.md` Section E).

**Split parent (Phase 2c closed the parent):** summarize the children (each `#<n>` + its PR) and the integration check, then nudge review on the child PRs. **Stopped mid-orchestration** (a child paused): report which child paused (of how many), what it needs, and that `/gld resume $1` continues from it — the remaining children have not run yet.

---

## Notes
- **One Issue tree, in-session.** `/gld dev` drives a single Issue — or, if design splits it, that parent and its children **sequentially** in one session (Phase 2b/2c, `_handoff.md` Section I). Driving *many unrelated* Issues in one run is `/gld batch`/`/gld sprint`'s job (both unattended; `sprint` additionally isolates each Issue in its own worktree and stacks dependent PRs), not `dev`'s.
- **Leader is embodied, not spawned.** No separate leader sub-agent (avoids nesting). The main session IS the leader; only the stage roles (tech-lead/developer/tester) are spawned as sub-agents by the wrappers.
- **Labels are the state.** If interrupted, `/gld resume $1` or a fresh `/gld dev $1` re-reads the label and continues from there — no local state file to corrupt.
- **Human approval is always the final gate.** The human approving the PR is the external reviewer of record (INV1) — Guild collaboration (tech-lead conformance, tester-first) provides internal review throughout; the **execute stage runs an always-on external auditor** (`_execute_spine.md` Step 3.5a) so `BLOCKER`-level defects are fixed *before* `test`/`qa` verify the result; and `/gld review`'s Step 2.5 runs that **same auditor again, outside `dev`** — a further advisory 2nd opinion before human approval (never a replacement for it), and the only place from which "did `dev` actually get better?" can be measured, since a scan inside `dev` cannot measure `dev`.
