# BATCH — unattended writing (`/hrd batch [--n N]`)

Writes N queued topics, one fresh `claude -p` child session per article (no context carried
between articles — plan §3.7), and stops at PRs (`approve`) or also publishes through a ship
child (`autonomy.publish: auto`). Plan §3.2.1 (batch structure), §3.2.2 (batch + auto table).

The runner is a plain Python process — the only writer of base-branch state during a batch.
Children run with `HRD_UNATTENDED=1`, `--dangerously-skip-permissions` and the guard hook,
which denies base commits/pushes, merges outside `HRD_AUTO_PRS`, and deploys.

## Steps (main session)

1. Preconditions: base checked out, clean tree, `HRD ahead` has no `needs_human` commits,
   `claude` CLI on PATH, `gh auth status` ok, `config.budget.per_article_usd` set (warn if 0 =
   no budget enforcement).
2. Tell the user what will happen: N topics (`HRD select --n N`), mode (`approve` → PRs only;
   `auto` → up to `throttle.max_per_day` auto publishes today, excluding PRs with dismissals,
   assumptions or image changes), the per-article budget, and that the run may take a long
   time (rate limits up to 4h are waited out).
3. Start in the background:
   `python3 .claude/herald/scripts/batch_runner.py --n <N>` with `run_in_background`.
   Logs: `.claude/herald/memory/batch-logs/`.
4. When it finishes, summarize its JSON: PRs opened, holds by reason (next steps per reason,
   `/hrd status`), incomplete topics, auto publish result (chosen / skipped with reasons).
   Approve-mode PRs are published with `/hrd ship`.

## What the runner does (for the record)

① sync base → ② per topic: child `/hrd write <id>` (budget watched from stream-json usage;
over budget → kill, WIP-commit the branch, hold `budget`) → completion judged from GitHub /
result file, one `/hrd resume` retry, else hold `needs-human` → holds committed on base
(`Herald-Record: hold`) → ③ (auto) PR selection from PR-head `critique.json`, throttle, base
re-sync → ④ ship child `/hrd ship --auto` with `HRD_AUTO_PRS` → ⑤ re-derive merges from GitHub,
removal reverts, sync, `integrity --predeploy`, deploy, URL checks, `published` records
(`human_reviewed: false`), push (retry once after a sync; else leave unpushed).
