# CHECKOUT (the human's checkout and history — the one definition)

**Not a stage.** The single definition of what Guild may and may not do to the checkout `/gld` runs in and to the history of branches it did not create. `SKILL.md` *The human's checkout* carries the short form (it is in context on every `/gld` call); every command's head line points here; the per-command Hard rules (`sprint/retro.md`, `sprint/plan.md`, `evolve.md`, `review.md`) are instances of this file and do not redefine it. Measured five times, five commands: resume #161 (`git checkout main` + `git merge --ff-only origin/main` + a full test run, unasked), plan #1889 (`git switch main` + `git pull --rebase` recommended — two unpushed record commits changed hash), sync #1889 (`git switch` + `git merge --no-commit origin/main` in the human's checkout), retro #649 (`git pull --rebase origin main` on "pull 과 push"), retro #630 (`git rebase origin/main` on "push 해 주세요").

---

## Section A — Whose checkout

- **The human's checkout** = the working tree `/gld` was invoked in, and every worktree Guild did not create.
- **Guild's worktrees** = the ones a Guild command created, named `.gld-<repo>-…`: the sprint container's `issue-<N>` · `supervisor` · `sync-<N>`, review's `.gld-<repo>-review-<pr>`.

## Section B — Never, on its own (three open principles)

1. **Moving the human's checkout off its branch** — `git checkout <branch>` / `git switch <branch>` to another branch, detaching.
2. **Moving or rewriting a commit already on a branch Guild did not create** — `git pull`, a `merge` into it, `rebase`, `reset` (except `--soft HEAD~1` of Guild's own unpushed commit), `commit --amend`, `cherry-pick` / `am` onto it, `update-ref refs/heads/<that branch>`.
3. **Discarding or hiding the human's uncommitted changes** — `git stash`, `git checkout -- .`, `git restore` / `git checkout -- <f>` / `git clean` / `rm` of a file Guild did not edit.

**And no option that offers any of these** — `main 으로 이동 후 진행 (Recommended)`, `제가 최신화하겠습니다` and the like (the generalisation of `sprint/retro.md`'s measured #1839 option).

## Section C — The one exception

**The branch of the Issue the execute stage is executing** — `/gld dev`·`resume`·`implement`·`debug`·`refactor` invoked directly (`implement.md`), an epic's children (`dev.md` Phase 2b → `_execute_spine.md`), and the integration-fix child (`dev.md` Phase 2c) included: `_execute_spine.md` Step 0 (c)'s `git switch --no-track -c <branch> <base>` and the switch to that Issue's existing branch, and `refactor.md`'s detach-and-return net proof (it detaches to prove the safety net and returns to its own branch). The human asked for that Issue to be worked in this checkout.

## Section D — Outside the three principles: allowed

Listed so the rule is not over-applied — each of these is ordinary work:

- **Every fetch** — `git fetch origin <d>:refs/remotes/origin/<d>`, `git fetch origin pull/<p>/head <baseRefName>` → `FETCH_HEAD` (`rollback.md`), `git fetch <remote>` (`sprint/plan.md`), `<base>:<base>` that creates a local branch that does not exist yet.
- **A new commit on the current branch** — the developer's Issue-branch commits, plan/retro/evolve's record commits, rollback's `git revert --no-commit` → commit and `git revert --abort`.
- **Restoring a file Guild edited** — `git checkout -- <f>`, `git checkout HEAD -- <path>` (evolve's rollback), rollback's ledger copy; `git checkout <branch> -- <files>`, `git rm -f`, `git mv` (`refactor.md`, evolve's rollback); `git rm --cached` (`init.md`).
- **`git reset --soft HEAD~1` of Guild's own unpushed commit** (`sprint/plan.md` Phase 6 step 8).
- **Pushing the current branch as it is** — rejected → stop and say so (`sprint/retro.md` Hard rules).
- **Work inside Guild's worktrees and on member branches Guild created** — `stack_sync.py`'s `update-ref refs/heads/<member branch>`, a merge in a sprint worktree; `sprint/retro.md` Phase 7's cleanup.

`batch.md`'s child sessions run in the checkout the human handed to batch (no isolation — its `stash -u` defence): this rule is about the leader's own actions, and batch's existing limit stays as it is.

## Section E — When the human asks (pull · sync · 최신화 · "main 으로 옮겨" · "충돌 풀어" · a rejected push)

Read the state first, **each its own Bash call**: `git branch --show-current` → `<b>`; `git status --porcelain`; `git fetch origin <b>:refs/remotes/origin/<b>`; `git rev-list --left-right --count HEAD...origin/<b>` → `<ahead> <behind>`; `ahead > 0` → `git log --oneline origin/<b>..HEAD`. Then, **before running any command**, show this form and ask (AskUserQuestion):

```
실행할 명령(순서대로):
  git pull --ff-only origin main
결과: fast-forward — 바뀌는 커밋 없음
```

The result line is the fixed wording that applies, one or more of:
- `fast-forward — 바뀌는 커밋 없음`
- `머지 커밋 1개가 생깁니다 — 기존 커밋 해시는 그대로`
- `해시가 바뀌는 로컬 커밋 <k>개: <sha> <제목> …(이 해시를 인용한 Guild 댓글·기록은 옛 해시를 가리키게 됩니다)`
- `커밋 안 된 파일 <n>개가 그대로 따라갑니다(충돌하면 git 이 거부합니다)`

**`git pull` is always written in an explicit form** (`--ff-only` / `--no-rebase`) — a bare `git pull` can rebase, depending on the `pull.rebase` setting.

**Guild runs only an update that keeps every hash** (the human's rule: only hash-preserving updates): `ahead = 0` → `git pull --ff-only origin <b>`; `ahead > 0` → `git pull --no-rebase origin <b>` (a merge commit). The options are that one (recommended) and `직접 하겠습니다` — two. **A form that rewrites local commits (`git pull --rebase`, `git rebase`) is never an option Guild runs**: when the human wants it, show the command and the `해시가 바뀌는 로컬 커밋 <k>개: …` list only — the human runs it.

The conditions on `--no-rebase`:
- (i) `git status --porcelain` is not empty (the human's uncommitted changes) → `--no-rebase` is not made an option — after a conflict, `merge --abort` is not guaranteed to restore those changes; show the command only, the human runs it.
- (ii) `git config pull.ff` is `only` → git refuses with `Not possible to fast-forward`. On that output nothing changed: one line `pull.ff=only 설정이라 머지 갱신이 거부되었습니다 — 직접 하십시오(git pull --no-rebase --no-ff origin <b> 또는 설정 변경)` and stop — never change the setting or retry with `--no-ff`.
- (iii) `behind = 0` → one line `갱신할 것이 없습니다(origin/<b> 와 같거나 앞섬)` and stop — no command, no `머지 커밋 1개` result line.

**Conflict pre-check** (a conflict leaves the human's checkout MERGING): before running, the read-only `git merge-tree --write-tree HEAD origin/<b>` (git ≥ 2.38; exit 1 = conflict). Conflict expected → do not run; one line `충돌 예상 — <파일…>: 머지는 사람이 하십시오(git pull --no-rebase origin <b>)`. Any exit code other than 0 or 1 (git < 2.38's unknown option, say) → the check cannot judge → do not run, show the command only. The pre-check passed and the run still conflicts → **the only next command allowed is `git merge --abort`**; report and stop.

Only the approved list, in that order. Anything outside the list becoming necessary (a hook refusal, an extra command) → stop and show the form again. **`--force` and `reset --hard` never, in any case** (INV3).

**Fetch failed or no upstream** — the state read's `git fetch` fails, or `branch.<b>.remote` / `@{u}` is missing → `<ahead>/<behind>` cannot be known → run nothing, show the commands only: `원격 상태를 읽지 못했습니다 — 직접 하십시오: …`.

**A request to switch branches** ("main 으로 옮겨 주세요"): a switch changes no hash, so under the same rule **Guild runs it only after an explicit yes** — read `git status --porcelain` first, show `실행할 명령: git switch <b>` with the result line `커밋 안 된 파일 <n>개가 그대로 따라갑니다(충돌하면 git 이 거부합니다)` or `커밋 안 된 변경 없음`, and ask. git refuses (changes it would overwrite) → report it as it is and stop — never make way with `stash` / `restore` (principle 3). An option that switches without asking and goes on is still forbidden.

**A request to work on another branch** (resolve a member PR's conflict, fix a PR): never in the human's checkout — `review.md`'s worktree procedure (`.gld-<repo>-review-<pr>`, its question and its removal condition as they are). `sprint sync`'s `conflict` is the same: `stack_sync.py` learns of the conflict from the tree computation and returns before creating any worktree, so what that line carries is **the conflicted paths**, not a worktree — make the review worktree for that member's PR. When done, report the path.

## Section F — The scope of an approval

**An approval reaches only the list shown in that command.** A new `/gld …` invocation asks again; "알아서 판단해서 해 주세요" approves the items of the list that was shown — it never widens to what the procedure **decided to keep** (a dirty worktree's contents, an untracked file, a branch whose tip ≠ `headRefOid`, …). `sprint/retro.md` Phase 7 applies this to `--cleanup` (measured `--cleanup 630` right after `--cleanup 545`).

## Limits

This is still the leader's behaviour: no gate refuses `git pull --rebase` or `git checkout <branch>` at PreToolUse — it cannot tell a request the human made and approved from one it did not, and the execute exception's switch is the same command shape. What this file adds is that the rule is always in context (`SKILL.md`), the request form is fixed, and a recommended option can never be a rewrite.
