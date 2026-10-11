# EVOLVE — grow the organization from real traces (`/hrd evolve [--dry-run|--apply]`)

No flag and `--apply` are the same full run; `--dry-run` stops after the proposals.

Reads signals, proposes improvements, has them attacked by an adversarial panel, applies only
what the human approves item by item, and records everything. Ported from Guild `evolve.md`.
Plan §3.6. Always started by a human; there is no automatic trigger.

Invariants: INV1 (per-item approval), INV2 (no proposal may loosen fact-check rules, critique
criteria, exemplars by deletion/downgrade, the gate, or the charter floor — hard veto), INV3
(one commit per run, `/hrd rollback` reverts it). The charter's priority order is never a
target.

## Phase 0 — Preflight

`HRD lock acquire --cmd evolve` (keep the token; `HRD lock release --cmd evolve --token <t>` on
every exit path); base clean; `HRD sync`. Read `.claude/herald/evolution-log.md`:
run number `n` = existing entries + 1; earlier rejected proposals must not be re-proposed
unchanged; the targets applied in the last 3 runs (regression watch).

## Phase 1 — Scan (read-only on content; writes local bookkeeping)

- `HRD evolve-readiness --list --snapshot --token <t>` (the Phase 0 lock token) returns:
  - `list` — this machine's unconsumed, countable, deduplicated signals, each with an `id`; a
    group's `data` merges its records (e.g. a session edit request with its diff); per-kind
    counts are the same numbers the `ship`/`status` nudge used.
  - `baseline` — reviewed human edits of at most 2 changed lines and review runs that found
    nothing, with ids. Never counted as problems: use them only for exemplar promotion and as
    the denominator of edit rates; citing them consumes nothing.
  - Already excluded: malformed records, human-edit records without `human_reviewed: true`
    (also out of exemplar denominators), and signals an earlier decided proposal consumed.
- `--snapshot` keeps the listed ids locally, tagged with the token. The run marks them as seen
  only when it ends normally (`HRD evolve-mark --scan --token <t>` in Phase 3 for `--dry-run`,
  Phase 7 otherwise); a snapshot left by an aborted run is never used by another run. After
  that the nudge stays quiet until a ready kind gets a signal no completed scan has seen;
  evolve itself can be run at any time.
- External metrics only if connected (`monitoring.md`).
- **Data sufficiency** (Guild `_data_sufficiency.md`): a theme needs ≥ 3 independent signals
  from ≥ 2 topics; otherwise report it as "watching", never propose it. Watching signals stay
  unconsumed and count again next run.

## Phase 2 — Themes

Synthesize ranked themes, strongest evidence first (human edits > ship declines > review
findings > auditor patterns/dismissals > REVISE patterns > verify gaps > holds > gate
failures > stagnation/escalations). Typical targets: style guide, category guides, writer /
researcher / strategist personas (Habits section), sources list, exemplar promotion (first-
round PASS + no undismissed findings + human-reviewed with almost no edits), role default
tiers (never the editor-in-chief), role split proposals (e.g. GEO out of search-discovery).

Auditor findings that point at the auditor itself (its prompt, its severity scale) are not
applied here — the auditor deliberately reads no repo guides — they become `/hrd contribute`
candidates (flow-level).

## Phase 3 — Proposals

Each: target file, the exact edit (smallest possible), evidence (plain sentences citing topics
and PRs, plus the signal `id`s from Phase 1 — Phase 6 consumes them), expected effect.
`--dry-run` prints them, runs `HRD evolve-mark --scan --token <t>`, and stops.

## Phase 4 — Adversarial panel

Spawn three fresh reviewers (opus) in parallel, one lens each: correctness (does the evidence
support it?), degradation (does it weaken verification or the floor? any yes = veto),
redundancy (already covered?). Drop what does not survive; say why in plain words.

## Phase 5 — Per-item approval

`AskUserQuestion` per surviving item: apply / edit / reject. Rejected items go to the ledger's
skip list.

## Phase 6 — Apply

1. Edit approved files (protected files trigger the guard's `ask` — that prompt is the human's
   per-file approval). Re-run `tests` that exist for the harness (`validate_content.py` on the
   last 3 published articles must still pass). Failure → revert the working tree for this run,
   report, and stop without committing, consuming or stamping the scan (the evidence stays
   pending and the nudge stays as it was; the same holds if the human aborts the run).
2. No item was decided (nothing proposed, nothing survived the panel) → no commit, no log row;
   go to Phase 7. Otherwise append the run to `evolution-log.md` (n, date, applied items with
   evidence and target files, rejected items) and commit once:
   `HRD commit --cmd harness --kind evolve -m "chore(herald): evolve #<n> — <summary>" <files>`,
   `git push origin <base>`.
3. After the commit (even if the push was refused; if `HRD commit` itself fails, revert as in
   step 1 and stop without consuming or stamping): `HRD evolve-mark --consume <ids>` with the
   signal ids cited as evidence by every **decided** item (applied or rejected). Panel-dropped
   proposals and watching themes consume nothing. `--dry-run` never consumes. Ids it reports as
   `unknown` were not in the Phase 1 list (mistyped or invented) — report them; the known ones
   are consumed regardless; `baseline_cited` ids are fine (baseline is never consumed), and so
   are `already_consumed` ids (another decided item cited the same evidence).

## Phase 7 — Report

`HRD evolve-mark --scan --token <t>` (the run completed). Then report in plain language (no
"Phase"/"INV" jargon): what changed, what was rejected, what is being watched. Only when a
commit was made: `/hrd rollback evolve#<n>` undoes the run (a rollback does not un-consume
signals: re-proposing the reverted change needs new evidence).
