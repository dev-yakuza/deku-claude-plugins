# WRITE — one article end to end (`/hrd write <topic-id> [--attended]`)

brief → research → draft → critique → verify → publish (PR). Publishing itself is `/hrd ship`.
Rules: `atoms/_contract.md`, `atoms/_stages.md`. Plan: §3.2, §3.2.2.

## 0. Preflight (each its own call)

1. `printenv HRD_UNATTENDED` → mode: `1` = unattended; else `--attended` given = attended
   (asks at every gate, session approval before the PR); else **in-session auto**, the default
   (`atoms/_contract.md` §C — no questions until the PR; `--auto` is accepted and means the
   same).
2. `HRD lock acquire --cmd write` → keep the token (unattended: inherits `HRD_LOCK_TOKEN`).
   Release with `HRD lock release --token <t>` on every exit path below (an inherited batch
   lock is left to the runner — release is then a no-op).
3. `git status --porcelain --untracked-files=no` must be empty; `git switch <base>`;
   `HRD sync` (fetch + merge origin; a conflict stops; unattended: fast-forward only).
4. `HRD ahead` — any `needs_human` commit: attended or in-session auto (a pre-flow question) →
   show it and ask whether to continue;
   unattended → `HRD result --topic <id> --status held:needs-human --note "tooling: base has
   foreign unpushed commits"` and stop.
5. Unpushed commits touching `docs/editorial/` or `.claude/agents/` on base → push them first
   (roles read the harness from the herald branch = `origin/<base>`).
6. `HRD select --topic <id>` must list the topic (queued, no open/merged PR, no local
   branch). An existing local branch means `resume`, not `write`.
7. Budget: `config.budget.per_article_usd` (0 = none). Run `python3
   .claude/herald/scripts/measure.py` now and keep its `total_usd` as the baseline and its
   `session` id (the session may already have spent on other work); at each stage end run
   `measure.py --session <that id>` — the article's cost is its `total_usd` minus the baseline.
   `found: false` (now or later) → tell the user the budget cannot be measured in this run and
   continue without it (never treat it as 0 spent silently). The baseline follows the transcript
   modified last: another Claude Code session working in this repo at the same moment can be
   picked instead — say so if the user mentions one. Attended runs **warn only**; in-session auto holds `budget`
   when it is exceeded (a `resume` takes a fresh baseline: resuming a budget hold is the human's
   choice to spend more); batch enforces it from its own stream.

## 1. Stages

Run brief, research, draft, critique, verify in order per `atoms/_stages.md`. After each
`DONE`, tell the user one line (in `config.language`; not unattended).

## 2. Session approval (`--attended` only, before the PR)

Show: title, slug, 5-line summary, audit findings incl. MINOR, dismissals and deferrals, verify
counts, measured cost so far. Ask: approve / request changes / hold. Each re-run below counts
an audit round (`HRD audit-round`), so after the cap only the editor and verify run again.

- **Request changes**: record it right away — `HRD signal --kind session-edit-request --topic
  <id> --data '{"request": "<verbatim>"}'` (so a later hold or failure cannot lose it) and keep
  the `id` it prints; the writer applies the request (`HRD loopback --topic <id> --human` — not
  counted); `HRD stage pass --stage draft` (runs the gate; on errors the writer fixes them under
  the same `--human` loopback — never `--cause gate` for a human-requested revision); then
  `HRD signal --kind
  session-edit-request --topic <id> --data '{"request_id": "<that id>", "diff_summary": "...",
  "lines_changed": n}'` (joined to its request by the id, counted once); then critique (editor →
  auditor) and verify run again. Loop until approve or hold.
- **Hold**: hold `needs-human` with `--note "human: <the human's reason>"` (branch preserved; a
  human's choice is not a growth signal).

## 3. Publish

`atoms/_stages.md` § publish (finalize → commit → scope → push → ledger push record → PR).
Report the PR URL (in-session auto: also the decisions it made and any deferred findings) and
remind: "publish with `/hrd ship`". If `config.autonomy.publish` is
`auto`, instead run `/hrd ship <that PR> --session-auto` right away, before releasing this
command's lock (ship nests on it with this token): per plan §3.2.2 the
interactive auto path covers only the PR this session just created — step 4 (per-PR question) is
skipped, the auto-exclusion rules and the daily throttle apply (`HRD auto-exclusion --topic
<id>`; excluded → stay PR-pending and say why), and the guard's merge/deploy confirmations remain.

## 4. Unattended specifics

No session approval. On any hold or stop, write `HRD result` and exit 0. Never write the base
branch, never merge, never deploy (the guard denies these).
