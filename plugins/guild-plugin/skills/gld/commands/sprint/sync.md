# SPRINT SYNC (after a merge — bring the stacked PRs above it level with the default branch, and the merged members' cards to Done)

**Run after a merge.** On a squash/rebase-only repo, after merging a lower PR of a stack, each upper
branch gets the default branch merged in (a merge commit — never a rebase or force: INV3), is
verified, pushed, retargeted and readied. Contract: `_sprint_dag.md` Section G.
All logic is in `stack_sync.py`; this file only calls it and reports — and, when a board is
configured, moves the merged members' cards to `Done` through `board_write.py` (step 5). That
second job is why a repo that merges with merge commits may run it too: there is nothing to
sync, but nothing else moves those cards once the run has ended (`retro.md` Phase 6).

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
   Add `--done-cards` when `config.sprint.board` is set (with or without `--check`): the script
   then ends with one `done-cards …` line for step 5. Without a board, leave it out — it costs
   one `gh issue view` per merged member.
   Exit `64` → report the stderr line (input/config problem). `65` → GitHub or git unavailable;
   nothing was changed for members not yet printed. Any other non-zero → `FAIL: stack_sync crashed
   — <last stderr line>`, plus the lines it printed before. On any non-zero exit there is no
   `done-cards` line, so step 5 does not run.
4. **Report** one line per member line, actionable first (the `done-cards` line is step 5's, not
   a member):
   - `stale` → *"#<dep>가 리뷰로 바뀌었습니다 — 상단 브랜치를 직접 따라잡은 뒤 `/gld dev <n>`"*
     (then `sync` reports `draft-held` until the human readies it)
   - `diverged` → *"#<dep>의 작업이 기본 브랜치에 온전히 남아 있지 않습니다(revert·부분 재머지) — 사람이 판단"*
     (known false positive: a later PR deleted or renamed a file #<dep> added — then catch up by hand)
   - `conflict` / `verify-failed` / `push-rejected` / `error` → the path or log it names; nothing was
     pushed for `conflict`·`verify-failed`·`push-rejected`. An `error` naming `config.commands`
     (no verification command, or a metacharacter in one) means that member needs a merge and
     will not get one unverified — fix the config with `/gld config`; so does `cannot read
     …/config.json`. Members that need no merge and step 5 are unaffected
   - `ambiguous` → which PRs/branch to sort out
   - `skipped` → `not-done` (still in the spine — sync after it finishes) · `branch-checked-out`
     (the path follows — remove that preserved worktree or switch it away, then re-run) · `head-moved` (someone pushed — re-run)
   - `draft-held` → *"sync가 아닌 머지로 맞춰진 브랜치입니다 — `/gld dev <n>` 통과 후 `gh pr ready <pr>`"*
   - `worktree-kept` → the path; inspect and remove it (no `--force` was used)
   - `synced` → what was done (`none` = already level); `clean` → nothing needed;
     `needs-sync` (with `--check`) → *"`/gld sprint sync`로 처리됩니다"*
   - No member line → *"동기화할 스택이 없습니다"*.
5. **Board — only when `config.sprint.board` is set.** Read the `done-cards` line:
   - `none` → nothing to say.
   - `error <message>` → *"보드: 머지된 멤버를 읽지 못해 카드를 옮기지 않았습니다 — <message>"*. The sync
     above stands; the board is a view (`board.md` D1), so this is never a `FAIL`.
   - `<n>,<n>…` with `--check` → *"보드: Done으로 옮길 카드 <k>장 — #<n>, … (`/gld sprint sync`로
     처리됩니다)"* and **write nothing**.
   - `<n>,<n>…` otherwise → resolve the repo (its own call, `gh repo view --json nameWithOwner --jq
     .nameWithOwner`), write the input file with the Write tool, then one call:
     ```bash
     python3 <<SKILL_DIR>>/commands/atoms/board_write.py --input <path>
     ```
     ```json
     {
       "number":  <config.sprint.board.number>,
       "owner":   "<config.sprint.board.owner>",
       "repo":    "<owner/repo>",
       "field":   "<config.sprint.board.column_field>",
       "columns": <config.sprint.board.columns, verbatim>,
       "owned":   <config.sprint.board.owned, verbatim>,
       "guard":   false,
       "read":    false,
       "writes":  [{"issue": <n>, "column": "done", "clear": ["<config.sprint.board.fields.needs_human>"]}, ...]
     }
     ```
     One entry per listed member and **nothing else** — no other column, no other issue.
     ⚠ **`"guard": false` is required, not a shortcut.** The guard refuses every card in
     `in_review`, the column these cards are in (`board_write.py` `SUPERVISOR_OWNED`). What makes
     the write safe instead is how the list was made (`stack_sync.py` `done_members`): a `MERGED`
     PR attributed to this member, **and** the Issue closed as `COMPLETED` (`stateReason` — an
     Issue closed as not planned or as a duplicate never qualifies). That is the run supervisor's
     P5 attribution with the Issue half added, so these cards are a **subset** of the ones P5
     moves to `Done`, never more.
     ⚠ **`"read": false`, unlike `--reset`.** A read is `item-list` at the board's size —
     ~500 GraphQL points on a 500-card board, every sync — while `read: false` costs one
     idempotent `item-add` (~5 points) per listed card. A sync lists a handful.
     ⚠ **Clear `Needs human` too** — the supervisor does it for a merged card; a `Done` card still
     saying `failed:<class>` contradicts itself.
     Report from the line it prints, with `<k>` = the number of listed members. Every entry
     writes the column, so `<k> − col_failed` cards reached `Done` — **not** `wrote`, which also
     counts an entry whose column failed but whose `Needs human` clear landed:
     *"보드: <k − col_failed>장을 Done으로 옮겼습니다"*, plus
     *"⚠ <col_failed>장은 컬럼 쓰기가 실패했습니다 (stderr 의 이슈 번호를 확인하십시오)"* when
     `col_failed` > 0, and *"⚠ Needs human 비우기 <failed − col_failed>건 실패"* when that is > 0
     (a card whose `item-add` failed is in `col_failed` and its clear was never tried, so it is
     not in this number).
     Exit `64` → the stderr line and *"카드는 옮기지 않았습니다"* (most often a column renamed in the
     UI — `/gld sprint board` says which). Either way the sync result stands.
   A live run writes `Done` to the same cards — same value, no conflict. Without a read,
   nothing compares: each sync rewrites every listed member, already-`Done` ones included, and a
   merged card the human dragged out of `Done` goes back — and one they removed from the board
   is added again (`item-add`). That is the one exception to *"Guild
   does not re-read, so it does not undo"* (`board.md` D1) — and it applies only to a member
   whose PR merged and whose Issue was closed as completed.
   ⚠ **A merge older than the last 200 PRs is not seen** — `stack_sync.py` reads `gh pr list
   --limit 200`, the same window as the supervisor. Such a card stays where it is; move it in
   the UI.

## Return

`OK: sprint #<n> — synced <a> / attention <b>` (synced = `synced` lines whose actions are not
`none`; attention = every status other than `synced`, `clean` and `needs-sync` — the `done-cards`
line is not a status) · `OK: no active sprint` · `OK: unattended — …` · `FAIL: <stderr line>`.
When step 5 wrote, append ` · board done <k − col_failed>`; when it listed (`--check`), ` · board to-done <k>`.

## Hard rules

- **Never catch up a `stale` member**, never rebase, never force — the script refuses all three.
- **No hand-made edits around the script**: no manual retarget or `gh pr ready` — except the
  human's own `gh pr ready` on a `draft-held` PR after `/gld dev <n>`.
- **The board gets `Done` and nothing else** — only for the `done-cards` members, only the column
  and `Needs human`, never under `--check`. Never pick the cards yourself (an Issue closed as not
  planned, a PR merged into a stack base): the script's list is the guard.
