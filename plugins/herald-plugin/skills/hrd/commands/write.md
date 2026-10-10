# WRITE — one article end to end (`/hrd write <topic-id>`)

brief → research → draft → critique → verify → publish (PR). Publishing itself is `/hrd ship`.
Rules: `atoms/_contract.md`, `atoms/_stages.md`. Plan: §3.2, §3.2.2.

## 0. Preflight (each its own call)

1. `printenv HRD_UNATTENDED` → mode.
2. `HRD lock acquire --cmd write` → keep the token (unattended: inherits `HRD_LOCK_TOKEN`).
   Release with `HRD lock release --token <t>` on every exit path below (an inherited batch
   lock is left to the runner — release is then a no-op).
3. `git status --porcelain --untracked-files=no` must be empty; `git switch <base>`;
   `HRD sync` (fetch + merge origin; a conflict stops; unattended: fast-forward only).
4. `HRD ahead` — any `needs_human` commit: attended → show it and ask whether to continue;
   unattended → `HRD result --topic <id> --status held:needs-human --note "base has foreign
   unpushed commits"` and stop.
5. Unpushed commits touching `docs/editorial/` or `.claude/agents/` on base → push them first
   (roles read the harness from the herald branch = `origin/<base>`).
6. `HRD select --topic <id>` must list the topic (queued, no open/merged PR, no local
   branch). An existing local branch means `resume`, not `write`.
7. Budget: `config.budget.per_article_usd` — attended runs check it at each stage end with
   `python3 .claude/herald/scripts/measure.py` and **warn only**; batch enforces it.

## 1. Stages

Run brief, research, draft, critique, verify in order per `atoms/_stages.md`. After each
`DONE`, tell the user one line (attended).

## 2. Session approval (attended only, before the PR)

Show: title, slug, 5-line summary, audit findings incl. MINOR and dismissals, verify counts,
measured cost so far. Ask: approve / request changes / hold.

- **Request changes**: record `HRD signal --kind session-edit-request --topic <id> --data
  '{"request": "<verbatim>"}'`; the writer applies the request (`HRD loopback --topic <id>
  --human` — not counted); `HRD stage pass --stage draft` (runs the gate); then critique
  (editor → auditor) and verify run again; record the before/after
  diff summary in the same signal kind. Loop until approve or hold.
- **Hold**: hold `needs-human` (branch preserved).

## 3. Publish

`atoms/_stages.md` § publish (finalize → commit → scope → push → ledger push record → PR).
Report the PR URL and remind: "publish with `/hrd ship`". If `config.autonomy.publish` is
`auto`, instead run `/hrd ship <that PR> --session-auto` right away: per plan §3.2.2 the
interactive auto path covers only the PR this session just created — step 4 (per-PR question) is
skipped, the auto-exclusion rules and the daily throttle apply (`HRD auto-exclusion --topic
<id>`; excluded → stay PR-pending and say why), and the guard's merge/deploy confirmations remain.

## 4. Unattended specifics

No session approval. On any hold or stop, write `HRD result` and exit 0. Never write the base
branch, never merge, never deploy (the guard denies these).
