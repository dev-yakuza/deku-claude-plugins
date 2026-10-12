# NEXT — publish one more article (`/hrd next [--attended]`)

Picks the next queued topic (planning first when the queue is empty), writes it to a PR and
ships it: brief → … → PR → merge → deploy → URL check, one article per run. Running it is the
human's request to publish this article without reading it first, so `ship` accepts the
agents' logged decisions, a trim and Herald-made images (`--consent`, `ship.md`); a blocking
exclusion, a hold or the daily
throttle still stops it, the article is recorded `human_reviewed: false` (unless `--attended`,
where the human approves the body before the PR), and the guard's merge and deploy
confirmations remain. Blocking, whatever the consent: an open, deferred or agent-dismissed
BLOCKER, an article changed after its last auditor round, a critique file changed after
critique passed, verdict files that cannot be read. `next` takes no lock itself: `plan` and `write` take their own.

1. `printenv HRD_UNATTENDED` → `1`: refuse (`batch` is the unattended path) and stop.
2. Base checked out and clean (`git status --porcelain --untracked-files=no` empty; `git switch
   <base>`), `HRD sync`, then the version check (SKILL.md).
3. `HRD throttle` → `room` 0: stop and say today's auto-publish limit is reached
   (`autonomy.throttle.max_per_day`); nothing is written.
4. `HRD select --n 1` → the topic. Empty → run `plan.md` with `--auto --n 3`, then select
   again; still empty (the planner kept nothing) → report the dropped titles and stop.
5. Run `write.md` for that topic with `--ship` (and `--attended` if `next` got it). Its pre-flow
   questions still apply (`atoms/_contract.md` §C).
6. Report in one short block: the published URL and what was accepted unread (ship §10: the
   accepted exclusions, the deferred auditor findings, dismissals and assumptions with their
   reasons, the trimmed sentences, the Herald-made images — a deferred MAJOR is published as
   is, so name each one) — or where it stopped and what to do next
   (a preserved hold — `needs-human`, `stagnation`, `budget` → `/hrd resume <id> --ship`; a
   cleaned hold — `cannibalization`, `research`, `rejected` → `/hrd status`, then `/hrd next`
   picks another topic; excluded or throttled → the PR waits for `/hrd ship`; a failed deploy or
   URL check → the next `/hrd ship` finishes it).
