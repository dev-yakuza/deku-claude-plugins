# SPRINT RUN (unattended development of a sprint's members to PRs)

**Drive every member through the spine unattended, in dependency order, each in its own git
worktree, stacking PRs where a dependency has not landed yet — and keep going through rate
limits until the queue is empty.** The human reviews and merges concurrently in their own
checkout; this command never touches it.

`$1` = comma-separated Issue numbers (ad-hoc sprint) · empty = **resume the active sprint** ·
`--readiness` = print the preflight verdict and stop.

> **Bash**: `<<SKILL_DIR>>/commands/atoms/_bash_rules.md`. The generated supervisor script is
> the sanctioned exception (`:85`) — variable expansion, redirection and heredocs *inside* it
> are fine; the rule governs the Bash tool call (`bash <path>`), not what a script does once
> running. State/labels/unattended: `_handoff.md` Sections A/H. Graph · base · membership:
> `_sprint_dag.md`. Base injection into the spine: `_execute_spine.md` (`<base>` resolution).
> **Output language**: `config.language`; machine tokens stay ASCII.

> ⚠️ **Security**: each child runs `claude -p --dangerously-skip-permissions` — all permission
> prompts and the sandbox are bypassed in the child so test runners, hooks, `git push` and
> `gh pr create` work unattended. Every tool call is logged. Use only if you accept unattended
> tool execution. Nothing merges (INV1).

---

## Phase 0 — Preflight

`--readiness` prints this table and stops; otherwise a blocking row stops the command.

| Check | How | Verdict |
|---|---|---|
| Guild initialized | `ls .claude/guild/config.json` | **block** |
| **A test can be run** | `config.commands.test` points at a real runner **and** a test framework/layout exists | **block** |
| **Harness is committed** | `git ls-files --error-unmatch .claude/guild/config.json CLAUDE.md` (and spot-check `.claude/agents/`, `docs/standards/`) | **block** |
| **Container dir creatable** | repo parent writable; else `$TMPDIR`; neither → **block** | **block** |
| `guild:sprint` label exists | `gh label list --limit 200 --json name --jq '[.[].name]'` | **block** |
| Merge strategy | `gh api repos/<o>/<r> --jq '{merge:.allow_merge_commit,squash:.allow_squash_merge,delete_branch:.delete_branch_on_merge}'` | Read the tracker body's **스택 깊이 상한** value and its **상한 근거** token, and compare with the repo now. `allow_merge_commit == false` **and** 근거 is not `merge-commit-forbidden`/`human-override` → the plan predates the setting: **stop** with `FAIL: this repo forbids merge commits but the sprint was planned with a stack — re-run /gld sprint plan`. `run` cannot lower the cap itself: the bases are already fixed in the immutable member table. ⚠ 근거 == `human-override` → **proceed**, and say once that the human accepted re-reviewing merged code under a squash strategy (`plan` Phase 0 step 5's reason). Do not re-litigate a decision the body records |
| CI runs tests on PRs | read `.github/workflows/*.yml` for a `pull_request` trigger invoking the test command | warn |
| A review path exists | recent merged PRs carry at least one review | warn |
| Install command resolvable | `config.commands` scan | warn |
| **Not already running** | Phase 1 step 3 | **block** |

**Why only the test row blocks on verification.** Guild judges completion by the raw output of
a test runner, refusing self-report (`_handoff.md` Section E). With no way to *run* tests that
gate is inert and an unattended run mass-produces unverified PRs — and in a stack the damage
compounds, because the PRs are entangled. `audit_readiness.md` already classifies
`no-test-command` as a **BLOCKER**; this reuses that judgment rather than inventing one.
**A greenfield repo with zero test files passes** — the requirement is the *ability to run and
read* tests, not existing tests; writing the first one is the work.

**Why the harness row blocks.** A worktree materializes only **tracked** files. If
`.claude/guild/`, `.claude/agents/`, `CLAUDE.md` or `docs/standards/` are untracked, every child
fails with "Guild not initialized" — measured on a real repo (`batch.md`, 2026-07-14).

⚠ The B-group conditions of the old locked `sprint` gate (per-agent scorecard trend, declining
human-correction rate) are **not** checked. They measure trust in *self-modification*, and this
command does not self-modify: `retro` is a separate command the human types, and evolve inside
it keeps per-item approval. What remains is the same risk `batch` already ships with.

Finally, show the warnings, the worktree paths to be created and the estimated dependency
install time, then ask once: *"이대로 무인 실행할까요?"* Unattended (`GLD_UNATTENDED=1`) → do not
ask and do not start: return `OK: unattended — starting a sprint run requires a human`.

## Phase 1 — Resolve the sprint

1. **Resolve `{owner}/{repo}`** once (`_handoff.md` Section F).
2. **Find the sprint.**
   - `$1` empty → the open `guild:sprint` Issue. None → *"활성 스프린트가 없습니다. `/gld sprint plan`으로 먼저 계획하세요."* Two or more → ask which.
   - `$1` = numbers → **create a tracking Issue for them first**, running `plan.md` Phase 4 (cycles → linearize → order → depth) and Phase 6 on the given set, with goal "즉석 스프린트" and capacity "사람 지정". ⚠ The ad-hoc path is **not** allowed to skip the container: the duplicate-run guard, the checkpoint, resume and `daily` all live in the tracking Issue's markers — without it none of them exist.
3. **Duplicate-run guard.** Read the `<!-- guild:sprint:run -->` comment.

   | Observed | Verdict |
   |---|---|
   | no marker | not running → start |
   | `host` matches, pid alive, cmdline matches | **running** → refuse: *"이미 실행 중입니다 (pid N, 시작 HH:MM). 상태는 `/gld sprint daily`."* |
   | `host` matches, pid gone | crash remnant → clear the run fields and resume |
   | `host` differs | cannot verify locally → **ask the human**, showing the heartbeat age and `state` |

   ⚠ The heartbeat is what makes this usable: a rate-limit wait was measured at ~115 minutes, so
   a marker refreshed only at issue boundaries would make a live run look dead. The supervisor
   refreshes at least every 10 minutes, **including inside the wait**.
4. **Verify the plan is unchanged.** `sprint_dag.py --mode hash` over the current body vs the
   `plan-hash:` line. Mismatch → attended: show what differs and ask; unattended: stop.
   ⚠ Do **not** label the tracker `guild:needs-human`: that label has exactly one removal point
   — any successful forward stage transition (`_handoff.md` Section A) — and the tracker has no
   stages, so it would stick forever and mis-report to `monitoring`/`status`. Record
   `state: halted:plan-hash-mismatch` in the run marker instead.
5. **Rebuild the queue.** Read the member table (immutable) for members and `base 의존`; then
   **re-read every member's current label** — the label is authoritative over anything the
   marker says. Restore retry counts and the **discovered-children list** from the marker
   (that list cannot be re-derived: a child body carries only `Parent Issue: #N`).
   Recompute the order with `--mode order` (the tie-break is stable, so a resume reproduces it).
   Queue only members that have not reached a terminal state.
6. **Inventory worktrees.** `git worktree list --porcelain` — note which member worktrees exist,
   which are registered-but-missing, and whether any branch is held by a **preserved worktree
   from an earlier sprint** (containers are keyed by tracker, so that is possible and will
   otherwise surface as a confusing refusal mid-run). Report those to the human now.

## Phase 2 — Permissions for child sessions: nothing to write, and say why

`batch` offers to merge a tool allowlist into `.claude/settings.local.json` here. **This flow
writes nothing.** Two reasons, and the second is the binding one:

1. That file is **gitignored, so it does not exist in a worktree** — `git worktree add` does not
   materialize it. Whatever it contains cannot reach a child.
2. The children run with `--dangerously-skip-permissions`, so the allowlist would not be
   consulted even if it were there.

⚠ Writing it would therefore be a change to the human's checkout that **buys nothing** — and it
would sit outside the write list this file's own Hard rules call *"in full"*
(`.sprint-logs/<tracker>/**`, `.claude/guild/memory/`, `.gld-sprint-<tracker>.sh`, and three
lines in `.git/info/exclude`). A phase that wrote a fourth path would make that enumeration
false, which is the class of defect §12.5-7 was rewritten for.

**Say this to the human** rather than silently skipping a phase `batch` has: the allowlist is not
protecting anything in an unattended sprint, and what *is* load-bearing is that every child runs
inside its own worktree.

## Phase 3 — Render the supervisor and start it

1. **Write `members.json`** (Write tool) into `<repo>/.claude/guild/.sprint-logs/<tracker>/dag/`:
   **one entry per member of the sprint — every row of the member table, not just the queue.**
   Each with `number`, `base_deps` (from the table) and `split`.
   ⚠ **This is the whole member set even on a resume, and that is not a detail.** Writing only
   the queue drops any member that already reached `guild:done` — and `--mode base` then reports
   its dependants' dep as *"outside the sprint"* and answers `DEFAULT`, so **the PR stack
   silently collapses onto the default branch** (measured). A stacked PR does not close its
   Issue and does not clear on merge, so `guild:done` + PR still OPEN is the *normal* state
   while the human reviews concurrently — i.e. exactly the state a resume starts from. The
   member set is defined by §5.1 as the sprint, not by what is left to run; `<ORDER>` is the
   queue.
   - `base_deps` comes from the member table's **`base 의존`** column — the linearized value, at
     most one per member. Never from `Depends on:` (`_sprint_dag.md` Section B).
   - `split` is `true` when the member's Issue carries a `<!-- guild:children:output -->`
     comment. **This file is the only place that value is produced** — the script cannot see the
     comment (`_sprint_dag.md` Section C), and without it a parent that completed by splitting
     reads as "no PR, no branch → blocked" and stops everything downstream of it. Check it per
     member while re-reading labels in Phase 1 step 5; one `gh issue view <n> --json comments`
     call each, or fold it into that pass.
2. **Render** `<<SKILL_DIR>>/templates/sprint-supervisor.sh`, substituting:

   | Token | Value |
   |---|---|
   | `<PLUGIN_VERSION>` | from `<<SKILL_DIR>>/../../.claude-plugin/plugin.json` (own Read call — never hardcode) |
   | `<TRACKER>` | tracking Issue number |
   | `<ORDER>` | space-separated execution order **of the queue only** — the members still to run (step 1's file stays the full set) |
   | `<OWNER_REPO>` | resolved literal |
   | `<DEFAULT_BRANCH>` | `gh repo view --json defaultBranchRef --jq .defaultBranchRef.name` |
   | `<CONTAINER>` | `<repo-parent>/.gld-<repo-basename>-sprint-<tracker>` (repo name included so two sibling repos with the same sprint number cannot collide — a worktree registers by basename) |
   | `<HUMAN_REPO>` | absolute path of the human's checkout |
   | `<DAG_PATH>` | absolute path of `commands/atoms/sprint_dag.py` |
   | `<INSTALL_CMDS>` | zero or more **shell-quoted** simple commands from `config.commands` (e.g. `'yarn install'`). ⚠ An array, not a string: an empty inline substitution would produce `( cd "$WT" &&  )`, a **parse** error no runtime guard can prevent |

3. **Write** it to `.claude/guild/.gld-sprint-<tracker>.sh` in the **human's checkout** — never
   inside the container. The self-delete trap and the logs must survive the container's removal.
4. `chmod +x` it.
5. **Start it in the background**: Bash tool with `run_in_background: true`, `bash .claude/guild/.gld-sprint-<tracker>.sh`.
   ⚠ **Do not create the container or the supervisor worktree here.** The script does both
   itself, after its empty-queue guard, because it must not build a worktree for a run with
   nothing to do — and because it normalises the container path to a realpath at the same
   moment (`git worktree list` reports realpaths, and on macOS both `/tmp` and `$TMPDIR` are
   symlinks, so an unnormalised path makes every live worktree look unregistered). Phase 0's
   container check is a *precondition* test, not the creation step.
6. Report: sprint number, member count, container path, log dir, and *"진행 상황은 `/gld sprint daily`. rate limit은 자동 대기·재개합니다."*

**What the supervisor does per issue** (implemented in the template; summarized here so this
file is readable on its own):

```
1. assemble the dag input   (gh pr list · gh issue list --json labels · git branch → one JSON)
2. blocked?                 sprint_dag.py --mode blocked   → skip and record
3. refresh base             git fetch origin <d>:refs/remotes/origin/<d>
4. decide base              sprint_dag.py --mode base      → DEFAULT | <branch> | BLOCKED:<why>
5. acquire the worktree     four states (below) + memory symlink + dependency install
6. run the child            (cd <worktree> && GLD_UNATTENDED=1 GLD_SPRINT_BASE=<base> claude -p "/gld dev <n>")
7. judge by label           5 outcomes (below)
8. release the worktree     only at guild:done, never --force
9. update the marker        heartbeat · retries · discovered children
```

**Base refresh uses the remote-tracking namespace only.** `git fetch origin <b>:<b>` is refused
whenever `<b>` is checked out in **any** worktree — and the human's checkout holds it, by
premise. Fetching into `refs/remotes/` never collides and leaves the human's local branch
untouched. The supervisor worktree is `--detach` for the same reason: it cannot check out a
branch the human already has.

**Worktree acquisition, four states.** `-b` is never used (branch naming belongs to the spine —
`_execute_spine.md` Step 0), and `--force` is never used (git's refusal *is* the safety
mechanism).

| Branch | Worktree | Action |
|---|---|---|
| none | none | `worktree add --detach <path> <base>` — the spine cuts the branch |
| **exists** | none | `worktree add <path> <branch>` — **check it out**, no `-b`, no `--detach`. With `--detach` the branch is not "the current branch", and a legitimate resume branch usually has an *empty* log (the developer commits at the end) — exactly the combination `_execute_spine.md` Step 0 (a) drops, sending a resumable Issue down the fresh path where `git switch -c` then fails with "already exists" and the Issue pauses |
| any | registered + present | enter it (judge by `worktree list` registration, **not** by path existence — a path that exists unregistered makes `worktree add` fail with "already exists" and every git call inside it fail) |
| any | registered + missing | `worktree prune`, then treat as absent (also at issue start, not only at run end — a `$TMPDIR` container can be cleaned mid-run) |

**The child runs inside the issue worktree.** That subshell `cd` is what makes the isolation
real; without it the child runs in the supervisor worktree, which has no dependencies
installed, and every test fails while the design silently reverts to one checkout.

**Growth signals are symlinked out.** `capture_signal.py` resolves the repo root by walking up
for a `.git` **entry** — a worktree's `.git` is a file, which it matches — so signals would land
inside the worktree and `git worktree remove` deletes them **silently** (git does not treat a
gitignored path as a reason to refuse). The supervisor links `<worktree>/.claude/guild/memory`
to the human's, and registers that path in `info/exclude` — ⚠ necessary because `.gitignore`'s
`memory/` is a *directory* pattern and does not match a symlink, so without it the worktree is
dirty and removal is refused.

**Five outcomes** (label-truthful — exit 0 is never proof of completion):

| Label | Outcome |
|---|---|
| `guild:needs-human` | PAUSED. Worktree preserved. Next member. Checked **before** the others — the label is additive and coexists with `guild:children` |
| `guild:done` | DONE. Release the worktree |
| `guild:children` | **not terminal** — a split still mid-orchestration. **Continue it**: re-invoke `/gld dev <parent>`, which `dev.md` Phase 1 sends straight to Phase 2b, and Phase 2b drives only the children that are not yet `guild:done` — so each pass resumes where the last stopped. The bound is **progress**, not attempts: reset the counter whenever the number of outstanding children falls, and record `split-stalled` as INCOMPLETE after two passes with no progress. ⚠ Do **not** hand it to the human and do **not** queue the children as members — they are this member's own work and share its worktree, exactly as they would outside a sprint |
| exit 0 mid-spine | bounded re-resume (2), then INCOMPLETE |
| blocked | recorded as **blocked, not failed** — a dependency did not land |

⚠ **The common split case is not `guild:children`.** When orchestration is *not* interrupted,
`dev.md` drives all children to `guild:done` in the same session and Phase 2c flips the parent
to `guild:done` — so the supervisor sees a **done parent with no branch and no PR**. That is
what `split: true` is for (step 1): without it the base decision would call a *completed* Issue
`BLOCKED:dep-no-branch` and block everything downstream of it.

## Phase 4 — On completion

The harness re-invokes when the background task exits. Then:
1. Read the marker and the logs; report per-member outcomes (**label-truthful**: done / paused /
   blocked / incomplete / failed) with counts, plus token/cost totals.
2. List **preserved worktrees** and, for each, whether what blocked removal is uncommitted
   **source** (real unfinished work — the human should look) or only **untracked docs**
   (`_execute_spine.md` Step 3.5b leaves a tech-writer ADR untracked by design — a known gap, not a
   failure). Do not judge it automatically and never auto-commit or delete.
3. State both termination axes (`sprint.md` — run finished vs sprint finished) and point at
   `/gld sprint daily`.

## Return

`OK: run complete — done <N> / paused <M> / failed <K> / blocked <J> / incomplete <I>` ·
`OK: already running (pid <p>, since <t>)` · `OK: paused — plan-hash mismatch` ·
`OK: unattended — starting a sprint run requires a human` ·
`FAIL: preflight blocked — <row>` · `FAIL: <reason>`

---

## Hard rules

- **Nothing merges** (INV1). The human reviews and merges every PR. Unattended *defers* that
  gate exactly as `batch` does — it does not remove it.
- **Never `--force` on a worktree, never `-b`, never `cd` into the container.** git's refusal is
  the safety mechanism; branch naming is the spine's; a supervisor standing in a worktree it
  removes dies on the next git call.
- **Never touch the human's *working tree*, index or stash.** What the run does write, in full:
  the gitignored `.claude/guild/.sprint-logs/<tracker>/**`, `.claude/guild/memory/` (through the
  symlink), `.claude/guild/.gld-sprint-<tracker>.sh` (this script), and three lines in
  `.git/info/exclude`. Plus, unavoidably, in the **shared ref store**: one new branch per Issue
  (the spine cuts it — the work would not exist otherwise), `refs/remotes/origin/<base>`
  advanced by an additive fetch, and `.git/worktrees/` bookkeeping. Fetch only into
  `refs/remotes/`; never into a local branch name. ⚠ `git worktree prune` is repo-global and
  takes no path, so it runs only when every prunable entry is inside our own container —
  otherwise it would drop the registration of a worktree of the human's that is merely on an
  unmounted volume.
- **Every `sprint_dag.py` call absorbs its exit code** and branches on the value.
- **Label-truthful outcomes.** exit 0 is not completion.
- **A marker write failure never kills the run** — but three consecutive failures stop it, since
  the duplicate-run guard depends on that marker being honest.
- **The container is not removed while a worktree in it is preserved.** Removal is git's call.
- The generated script is one backgrounded Bash tool call — the `_bash_rules.md:85` exception.
