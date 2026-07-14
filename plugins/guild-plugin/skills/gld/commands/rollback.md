# ROLLBACK (on-demand — safe revert of a Guild-authored change)

**Undo a Guild change with git — never destructively.** The human's escape hatch (plan §3 · T6 · INV3). Reverts are **additive** (`git revert` creates an undo commit; unmerged work is closed; a stage is relabeled) — **never** `reset --hard`, force-push, or history rewrite. Everything stays recoverable.

`$1` = what to undo: a **PR number**, a **commit SHA**, or `stage <issue>` (move an Issue back one stage).

> **Bash**: `_bash_rules.md`. State/handoff + owner/repo: `_handoff.md`.
> **Output language**: all human-readable output in `config.language` (`_handoff.md` Section K).

---

## Process
**0. Preflight** — as the leader, confirm Guild is initialized; resolve `<owner>/<repo>` (`_handoff.md` Section F).

**1. Identify the target**
- **PR number** → `gh pr view <n> --json state,mergedAt,commits,headRefName` — merged vs open, its commits/branch.
- **commit SHA** → `git show --stat <sha>` — the commit + its diff summary.
- **`stage <issue>`** → the Issue's current `guild:*` label (`gh issue view <n> --json labels`).

**2. Show the plan + PAUSE for confirmation (INV1 — rollback acts, so confirm first)**
State exactly WHAT will be reverted and the METHOD (which is always non-destructive):
- Merged PR / commit → **`git revert <sha>`** (new undo commit; opens a revert PR referencing the original). Merge-conflict on revert → surface, the human resolves; never force.
- Open (unmerged) PR → **close + delete its branch** (`gh pr close <n> --delete-branch`). The work is on the branch's history only (recoverable by reopening).
- `stage <issue>` → **relabel** the Issue back one stage (`gh issue edit <n> --remove-label guild:<cur> --add-label guild:<prev>`). Note: the stage's *artifacts* (comments, commits) remain — this only moves the state pointer so the stage re-runs.
Wait for the human's explicit "yes".

**3. Act (only after confirm; each its own Bash call)**
Execute the confirmed method. For a `git revert`, push + open the revert PR (`Refs #<orig>`, body: what/why reverted). Report the new undo commit/PR.

**4. Report** — what was reverted, the undo commit/PR link, and how to **redo** if this was a mistake (revert the revert / reopen the PR / relabel forward). Everything is reversible.

## Hard rules
- **Never destructive** (INV3/INV4/T6): `git revert` (additive) only — never `reset --hard`, `push --force`, `rebase`, `branch -D` of merged work, or history rewrite.
- **Confirm before acting** (INV1): show target + method, wait for the human. Read-only until confirmed.
- **Conflicts surface, never force** — a revert that conflicts is handed to the human.
