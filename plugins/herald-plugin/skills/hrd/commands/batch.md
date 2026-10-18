# BATCH — unattended writing (`/hrd batch [--n N]`)

Writes N queued topics, one fresh `claude -p` child session per article (no context carried
between articles), and stops at PRs (`approve`) or also publishes through a ship
child (`autonomy.publish: auto`).

The runner is a plain Python process — the only writer of base-branch state during a batch.
Children run with `HRD_UNATTENDED=1`, `--dangerously-skip-permissions` and the guard hook,
which denies base commits/pushes, merges outside `HRD_AUTO_PRS`, and deploys.

## Steps (main session)

1. Preconditions: base checked out, clean tree, `HRD ahead` has no `needs_human` commits,
   `claude` CLI on PATH, `gh auth status` ok, `config.budget.per_article_usd` set (warn if 0 =
   no budget enforcement).
2. Tell the user what will happen: N topics (`HRD select --n N`), mode (`approve` → PRs only;
   `auto` → up to `throttle.max_per_day` auto publishes today, excluding PRs with dismissals,
   assumptions, deferred audit findings, a skipped audit round, a trim, framings or image changes), the per-article budget, and that the run may take a long
   time: on a Claude usage limit it waits until the reset (up to 5h per wait, 12h per run) and resumes
   the topic; a longer limit stops the run cleanly. While it waits, every `/hrd` command in this
   repo is blocked by the checkout lock (the refusal names the pid to `kill`).
3. Start it **detached** — a batch can run for hours (children, usage-limit waits), longer
   than a background shell may live: `python3 .claude/herald/scripts/batch_runner.py --n <N> --expect-version <plugin version>
   --detach`. It forks into its own session and prints the paths of `runner.pid`, `runner.out`
   (the final JSON summary) and `runner.log` (progress) under `.claude/herald/memory/batch-logs/`.
   Watch for completion by polling until `runner.out` contains the summary JSON (or the pid in
   `runner.pid` is gone). Stop it with `kill $(cat .claude/herald/memory/batch-logs/runner.pid)` —
   it ends its children and releases the checkout lock (a topic held for a usage limit stays held:
   `/hrd resume <id>`).
4. When it finishes, summarize the JSON in `runner.out` (if `runner.out` is empty or carries
   `"error"`, report it and the last lines of `runner.log` — e.g. the lock was held, untracked
   build inputs, a base sync conflict, or a Herald version mismatch: base's scripts differ from
   the plugin, so the runner stopped before the next child — update, then run batch again): PRs opened, PRs a human merged during the run (→
   `/hrd ship` records them), holds by reason (next steps per reason, `/hrd status`), incomplete
   topics, auto publish result (chosen / skipped with reasons).
   Approve-mode PRs are published with `/hrd ship`.
   `rate_limited` (the run stopped on a usage limit): say until when, that the held topics continue
   with `/hrd resume <id>` after that and the rest with `/hrd batch`, and that this run's PRs are
   published with `/hrd ship`. `rate_limit_waits`: the waits it sat out. `skipped`: each reason.
   `stopped`: the run left the checkout untouched (it changed during a wait) — say why.
   `rate_limit_held`: topics this run holds for a usage limit (whatever ended the run) — each
   continues with `/hrd resume <id>` after the reset. `not_released`: a topic reached its PR but its
   hold changed elsewhere meanwhile — check it with `/hrd status`. `auto.rate_limited`: the ship
   child stopped on a usage limit (`limit`) or an overloaded API (`overloaded`) — nothing was
   deployed; `/hrd ship` later.

## What the runner does (for the record)

① sync base, then base's scripts version must equal `--expect-version` (re-checked before each
child and before the ship child; a mismatch stops the batch) → ② per topic: child `/hrd write <id>` (budget watched from stream-json usage;
over budget → kill, WIP-commit the branch, hold `budget`) → completion judged from GitHub /
result file and the PR first; a Claude usage limit in the child's log (any exit code) → keep the
work on its branch, hold it `needs-human` "tooling: rate limited until … (run <id>)" (pushed), wait
until the reset, check the checkout/base/version/topic, then `/hrd resume <id>` with
`HRD_RESUME_LIMITED=<run id>`, and release the hold when its PR exists; beyond 5h per wait, 6 waits
per topic or 12h per run → stop cleanly (`rate_limited`); else one `/hrd resume` retry, else hold
`needs-human` → holds committed on base
(`Herald-Record: hold`) → ③ (auto) PR selection from PR-head `critique.json`, throttle, base
re-sync → ④ ship child `/hrd ship --auto` with `HRD_AUTO_PRS` → ⑤ re-derive merges from GitHub,
removal reverts, sync, `integrity --predeploy`, deploy, URL checks, `published` records
(`human_reviewed: false`), push (retry once after a sync; else leave unpushed).
