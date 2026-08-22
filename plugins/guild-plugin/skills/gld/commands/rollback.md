# ROLLBACK (on-demand — safe revert of a Guild-authored change)

**Undo a Guild change with git — never destructively.** The human's escape hatch (INV3). Reverts are **additive** (`git revert` creates an undo commit; unmerged work is closed; a stage is relabeled) — **never** `reset --hard`, force-push, or history rewrite. Everything stays recoverable.

`$1` = what to undo: a **PR number**, a **commit SHA**, or the literal word `stage` (move an Issue back one stage). When `$1 == "stage"`, `$2` = the **Issue number** to move back — per `SKILL.md`'s routing (`$1`, `$2`… are space-separated tokens passed positionally), `/gld rollback stage 42` arrives as `$1="stage"`, `$2="42"`; there is no single two-word `$1`.

> **Bash**: `_bash_rules.md`. State/handoff + owner/repo: `_handoff.md`.
> **Output language**: all human-readable output in `config.language` (`_handoff.md` Section K).

---

## Process
**0. Preflight** — as the leader, confirm Guild is initialized; resolve `<owner>/<repo>` (`_handoff.md` Section F).

**1. Identify the target**
- **`$1` is a PR number** → `gh pr view <n> --json state,mergedAt,commits,headRefName` — merged vs open, its commits/branch.
- **`$1` is a commit SHA** → `git show --stat <sha>` — the commit + its diff summary. **Check whether this SHA matches an `[applied]` entry's commit in `.claude/guild/evolution-log.md`** (grep the ledger for the SHA) — if it does, this is an evolve-applied change; note that reverting it (step 3) must also update the ledger entry (see below), not just the git history.
- **`$1 == "stage"`** → `$2` is the Issue number; read its labels (`gh issue view $2 --json labels --jq '[.labels[].name] | map(select(startswith("guild:")))'`). **This can return more than one `guild:*` label** — `guild:needs-human` is additive (coexists with a stage label on a paused Issue), and a `guild:child` Issue carries `guild:child` alongside its own stage label — so "the current label" is never assumed singular; identify the actual **stage** label specifically (excluding `guild:needs-human` and `guild:child`) before computing "one stage back." **If the Issue carries `guild:child`**, also check its body for `Parent Issue: #<n>` and read that parent's current label: if the parent is already `guild:done` (Phase 2c integration already ran, per `_handoff.md` Section I), rolling this child back leaves the parent silently inconsistent — a "done" epic with a regressed child underneath, invisible to `status.md`/`monitoring.md` since neither re-checks a closed parent's children. This isn't a case rollback can fix by itself (re-opening/re-orchestrating the parent is a design-level call, not a revert), so **surface it explicitly in step 2's plan** ("parent #<n> already integrated as done — rolling back this child will not automatically reopen or re-flag it; you may want to also `/gld resume <n>` afterward") rather than silently proceeding as if the child were still standalone. Stage order (`status.md`'s convention): `analyze < design < execute < test < qa < done`. **Two labels are not in this ordinal chain and need their own handling, not a naive "previous row" lookup**: `guild:children` is an **orchestration state** (`_handoff.md` Section I), not a spine stage — rolling it "back one" is undefined; refuse with `NEEDS_HUMAN: #$2 is a split parent (guild:children) — rollback doesn't support orchestration state, target one of its children instead` rather than guessing. `guild:done` rolling back to `guild:qa` is well-defined *unless* the Issue was also closed (`_handoff.md` Section D notes a done Issue "may" be closed) — check `state` in the same `gh issue view` call, and if closed, reopen it (`gh issue reopen $2`) as part of the same confirmed action, stating that explicitly in step 2's plan. **`guild:analyze` is the other boundary** — it's the *first* row in the ordinal chain, so there is no predecessor `guild:*` label to move back to (per `status.md`'s convention, "no `guild:*` label at all" means *not started*, not a stage in the chain); refuse with `NEEDS_HUMAN: #$2 is already at the first stage (guild:analyze) — there's nothing earlier to roll back to. To fully reset it, remove the guild:analyze label by hand instead.`

**2. Show the plan + PAUSE for confirmation (INV1 — rollback acts, so confirm first)**
State exactly WHAT will be reverted and the METHOD (which is always non-destructive):
- Merged PR / commit → **`git revert <sha>`** (new undo commit; opens a revert PR referencing the original). Merge-conflict on revert → surface, the human resolves; never force. If step 1 found this SHA in `evolution-log.md` as an `[applied]` evolve entry, also state that the ledger entry will be annotated `[reverted]` (below) so it stops reading as still-applied.
- Open (unmerged) PR → **close + delete its branch** (`gh pr close <n> --delete-branch`). The work is on the branch's history only (recoverable by reopening).
- `$1 == "stage"` → **relabel** Issue `$2` back one stage, using the actual current *stage* label identified in step 1 (not `guild:needs-human`/`guild:child`, which aren't stages): `gh issue edit $2 --remove-label guild:<cur> --add-label guild:<prev>`. If `guild:needs-human` was also present, leave it — rolling back a stage doesn't resolve the pause, and stripping it here would misreport an unresolved pause as clear. Note: the stage's *artifacts* (comments, commits) remain — this only moves the state pointer so the stage re-runs. `guild:children` target → refused per step 1 (not a stage). `guild:analyze` target → refused per step 1 (no predecessor stage). `guild:done` target on a closed Issue → the plan also states the reopen.
Wait for the human's explicit "yes".

**3. Act (only after confirm; each its own Bash call)**
Execute the confirmed method. For a `git revert`, push + open the revert PR (`Refs #<orig>`, body: what/why reverted). Report the new undo commit/PR.

**Evolve-ledger sync (only when the reverted SHA was an `[applied]` evolve entry, per step 1):** append a note to that entry in `.claude/guild/evolution-log.md` (Edit tool — do not delete the original entry, INV3 reversibility means the history stays intact) marking it `[reverted by <new undo sha>, <date>]`. Without this, `/gld audit` Dimension E and evolve's own regression-tracking (Phase 0 step 3 "prior-applied targets") would keep reading the ledger as if the change were still in effect after a human has explicitly undone it.

**4. Report** — what was reverted, the undo commit/PR link, and how to **redo** if this was a mistake (revert the revert / reopen the PR / relabel forward). Everything is reversible.

## Hard rules
- **Never destructive** (INV3/INV4): `git revert` (additive) only — never `reset --hard`, `push --force`, `rebase`, `branch -D` of merged work, or history rewrite.
- **Confirm before acting** (INV1): show target + method, wait for the human. Read-only until confirmed.
- **Conflicts surface, never force** — a revert that conflicts is handed to the human.
