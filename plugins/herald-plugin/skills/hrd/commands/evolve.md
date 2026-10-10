# EVOLVE — grow the organization from real traces (`/hrd evolve [--dry-run|--apply]`)

Reads signals, proposes improvements, has them attacked by an adversarial panel, applies only
what the human approves item by item, and records everything. Ported from Guild `evolve.md`.
Plan §3.6. Always started by a human; there is no automatic trigger.

Invariants: INV1 (per-item approval), INV2 (no proposal may loosen fact-check rules, critique
criteria, exemplars by deletion/downgrade, the gate, or the charter floor — hard veto), INV3
(one commit per run, `/hrd rollback` reverts it). The charter's priority order is never a
target.

## Phase 0 — Preflight

`HRD lock acquire --cmd evolve`; base clean; `HRD sync`. Read `.claude/herald/evolution-log.md`:
run number `n` = existing entries + 1; earlier rejected proposals must not be re-proposed
unchanged; the targets applied in the last 3 runs (regression watch).

## Phase 1 — Scan (read-only)

- `.claude/herald/signals.jsonl` since the last run, grouped by kind and topic.
- Exclude `human_reviewed: false` records from human-edit signals and exemplar denominators.
- External metrics only if connected (`monitoring.md`).
- **Data sufficiency** (Guild `_data_sufficiency.md`): a theme needs ≥ 3 independent signals
  from ≥ 2 topics; otherwise report it as "watching", never propose it.

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
and PRs), expected effect. `--dry-run` stops here and prints them.

## Phase 4 — Adversarial panel

Spawn three fresh reviewers (opus) in parallel, one lens each: correctness (does the evidence
support it?), degradation (does it weaken verification or the floor? any yes = veto),
redundancy (already covered?). Drop what does not survive; say why in plain words.

## Phase 5 — Per-item approval

`AskUserQuestion` per surviving item: apply / edit / reject. Rejected items go to the ledger's
skip list.

## Phase 6 — Apply

Edit approved files (protected files trigger the guard's `ask` — that prompt is the human's
per-file approval). Re-run `tests` that exist for the harness (`validate_content.py` on the
last 3 published articles must still pass). Failure → revert the working tree for this run and
report. Append the run to `evolution-log.md` (n, date, applied items with evidence and target
files, rejected items). Commit once:
`HRD commit --cmd harness --kind evolve -m "chore(herald): evolve #<n> — <summary>" <files>`,
`git push origin <base>`.

## Phase 7 — Report

Plain language (no "Phase"/"INV" jargon): what changed, what was rejected, what is being
watched, and that `/hrd rollback evolve#<n>` undoes the run.
