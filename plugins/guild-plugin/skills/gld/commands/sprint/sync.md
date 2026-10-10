# SPRINT SYNC (after a squash merge — bring the stacked PRs above it level with the default branch)

**Run after merging a lower PR of a stacked sprint on a squash/rebase-only repo.** Each upper
branch gets the default branch merged in (a merge commit — never a rebase or force: INV3), is
verified, pushed, retargeted and readied. Contract: `_sprint_dag.md` Section G.
All logic is in `stack_sync.py`; this file only calls it and reports.

`$1` = `--check` (classify only, change nothing) · empty = sync. **Anything else is refused**
— `FAIL: unknown argument <$1> — valid: --check` — never fall through to the pushing mode.

> **Bash**: `<<SKILL_DIR>>/commands/atoms/_bash_rules.md`. **Output language**: `config.language`;
> statuses, `#N` and paths stay ASCII.

1. **Attended only.** `printenv GLD_UNATTENDED` → `1` → `OK: unattended — sprint sync runs after a
   human merge`. It pushes to member branches; the human triggers it.
2. **Find the sprint** — `gh issue list --label guild:sprint --state open --limit 20 --json number --jq '[.[].number]'`.
   None → `OK: no active sprint`; two or more → ask which.
3. **Run it** — one call, from the human's checkout. Without `--check` it runs install + test/lint/
   typecheck per synced member, so use `run_in_background: true` and wait for the completion
   notice (allowed here: this is not a `claude -p` child — `_bash_rules.md` Long-running).
   ```bash
   python3 <<SKILL_DIR>>/commands/atoms/stack_sync.py --tracker <n> --install-cmd <cmd>
   ```
   `--install-cmd`: one per install step from `config.commands`, quoted as one argument
   (`--install-cmd 'yarn install'`); none → omit. Add `--check` when `$1` is `--check`.
   Exit `64` → report the stderr line (input/config problem). `65` → GitHub or git unavailable;
   nothing was changed for members not yet printed. Any other non-zero → `FAIL: stack_sync crashed
   — <last stderr line>`, plus the lines it printed before.
4. **Report** one line per output line, actionable first:
   - `stale` → *"#<dep>가 리뷰로 바뀌었습니다 — 상단 브랜치를 직접 따라잡은 뒤 `/gld dev <n>`"*
     (then `sync` reports `draft-held` until the human readies it)
   - `diverged` → *"#<dep>의 작업이 기본 브랜치에 온전히 남아 있지 않습니다(revert·부분 재머지) — 사람이 판단"*
     (known false positive: a later PR deleted or renamed a file #<dep> added — then catch up by hand)
   - `conflict` / `verify-failed` / `push-rejected` / `error` → the path or log it names; nothing was
     pushed for `conflict`·`verify-failed`·`push-rejected`
   - `ambiguous` → which PRs/branch to sort out
   - `skipped` → `not-done` (still in the spine — sync after it finishes) · `branch-checked-out`
     (the path follows — remove that preserved worktree or switch it away, then re-run) · `head-moved` (someone pushed — re-run)
   - `draft-held` → *"sync가 아닌 머지로 맞춰진 브랜치입니다 — `/gld dev <n>` 통과 후 `gh pr ready <pr>`"*
   - `worktree-kept` → the path; inspect and remove it (no `--force` was used)
   - `synced` → what was done (`none` = already level); `clean` → nothing needed;
     `needs-sync` (with `--check`) → *"`/gld sprint sync`로 처리됩니다"*
   - No output → *"동기화할 스택이 없습니다"*.

## Return

`OK: sprint #<n> — synced <a> / attention <b>` (synced = `synced` lines whose actions are not
`none`; attention = every status other than `synced`, `clean` and `needs-sync`) · `OK: no active sprint` · `OK: unattended — …` · `FAIL: <stderr line>`

## Hard rules

- **Never catch up a `stale` member**, never rebase, never force — the script refuses all three.
- **No hand-made edits around the script**: no manual retarget or `gh pr ready` — except the
  human's own `gh pr ready` on a `draft-held` PR after `/gld dev <n>`.
