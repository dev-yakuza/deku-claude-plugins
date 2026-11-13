# NEXT — publish one more article (`/hrd next [--attended]`)

Picks the next queued topic (planning first when the queue is empty), writes it to a PR and
ships it: brief → … → PR → merge → deploy → URL check, one article per run, with no human look
(0.20.0). Running it is the human's request to publish this article without reading it first, so
`ship` accepts the agents' logged decisions, a trim, the fact-checker's framings and Herald-made
images (`--consent`, `ship.md`), and — the run carries `write --ship`'s mark — screenshots and
external images a fresh agent review confirmed in draft (`atoms/_images.md` §2a); the guard lets
the verified merge and the deploy through (`ship.md` §6–§7). Still stopping it: a blocking
exclusion (an open, deferred or agent-dismissed BLOCKER, an article changed after its last auditor
round, a critique or verify file changed after it passed, verdict files that cannot be read, a file
in the PR no record vouches for — `images-unconfirmed`), a hold (a screenshot only a human can
take, a capture the review flagged) and the daily throttle. The article is recorded
`human_reviewed: false` (unless `--attended`, where the human approves the body before the PR and
looks at every image), with `agent_confirmed` listing what the agent review passed. `next` takes
no lock itself: `plan` and `write` take their own.

1. `printenv HRD_UNATTENDED` → `1`: refuse (`batch` is the unattended path) and stop.
2. Base checked out and clean (`git status --porcelain --untracked-files=no` empty; `git switch
   <base>`), `HRD sync`, then the version check (SKILL.md).
3. `HRD throttle` → `room` 0: stop and say today's auto-publish limit is reached
   (`autonomy.throttle.max_per_day`); nothing is written.
4. `HRD select --n 1` → the topic. Empty → run `plan.md` with `--auto --n 3`, then select
   again; still empty (the planner kept nothing) → report the dropped titles and stop.
5. Run `write.md` for that topic with `--ship` (and `--attended` if `next` got it) — a `tr-` id
   runs `translate.md` § C instead, with the same flags. Its pre-flow
   questions still apply (`atoms/_contract.md` §C).
6. Report in one short block: the published URL and what was accepted unread (ship §10: the
   accepted exclusions, the deferred auditor findings, dismissals and assumptions with their
   reasons, the trimmed sentences, the framings and the sentences they covered, the Herald-made images,
   the images and screenshots the agent review confirmed or turned down — id, kind, its one-line
   note (`HRD image status` `agent`, `HRD shot status` `agent_confirmed`) — a deferred or
   out-of-scope MAJOR is published as is, so name each one) — or where it stopped and what to do next
   (a capture the review flagged — `s1(review:<kind>)` in a `screenshots` hold → `/hrd resume <id>`
   **without** `--ship`: a human looks at it; a screenshot only a human can take → put it in, then
   `/hrd resume <id> --ship`; any other preserved hold — `needs-human`, `stagnation`, `budget`,
   `screenshots` → `/hrd resume <id> --ship`; a
   cleaned hold — `cannibalization`, `research`, `rejected` → `/hrd status`, then `/hrd next`
   picks another topic; excluded or throttled → the PR waits for `/hrd ship`; a failed deploy or
   URL check → the next `/hrd ship` finishes it).
