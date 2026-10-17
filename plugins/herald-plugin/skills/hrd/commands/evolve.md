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
    group's `data` merges its records (e.g. a session edit request with its diff); per-theme
    counts (`themes`: kind, `kind:theme` for REVISE / auditor findings, `hold:<reason>`; the
    `escalation` and `incomplete` records in `list` are context and are not in the counts) are the same numbers the `ship`/`status` nudge used.
  - `baseline` — reviewed human edits of at most 2 changed lines, review runs that found
    nothing, and uploaded social texts that changed at most 10% of the approved draft, with ids. Never counted as problems: use them only for exemplar promotion and as
    the denominator of edit rates; citing them consumes nothing.
  - Already excluded: malformed records, human-edit records without `human_reviewed: true`
    (also out of exemplar denominators), and signals an earlier decided proposal consumed.
- `--snapshot` keeps the listed ids locally, tagged with the token. The run marks them as seen
  only when it ends normally (`HRD evolve-mark --scan --token <t>` in Phase 3 for `--dry-run`,
  Phase 7 otherwise); a snapshot left by an aborted run is never used by another run. After
  that the nudge stays quiet until a ready theme gets a signal no completed scan has seen;
  evolve itself can be run at any time.
- External metrics only if connected (`monitoring.md`).
- **Data sufficiency** (Guild `_data_sufficiency.md`): a theme needs ≥ 3 independent signals
  from ≥ 2 topics; otherwise report it as "watching", never propose it. Watching signals stay
  unconsumed and count again next run.

## Phase 2 — Themes

Synthesize ranked themes, strongest evidence first (human edits > ship declines > review
findings > auditor patterns/dismissals > REVISE patterns > research errors (claims the researcher got wrong; researcher persona, `sources.md`) > verify gaps > holds (stagnation is a
hold reason) > gate failures > escalations — listed, never counted by the nudge). Typical targets: style guide, category guides, writer /
researcher / strategist personas (Habits section), sources list, exemplar promotion (first-
round PASS + no undismissed findings + human-reviewed with almost no edits), role default
tiers (never the editor-in-chief), role split proposals (e.g. GEO out of search-discovery),
and `refresh-policy.md` from `refresh-override` signals (a human overturned the strategist's
refresh recommendation — data: recommendation, decision, rule applied, reason; counted per
article, `topic_id` `slug:<slug>`).

**Social posts** (`design/herald/03-social.md` S13): `social-edit-request` (the human asked for a
change), `social-final` (the uploaded text differed from the approved draft), `social-reject`
(every draft of a run discarded) and `social-gate-failure` (a draft still failing the checks),
each on an axis `<kind>:<theme>` (tone, length, format, persona, hashtags, disclosure, fact,
other), counted per SNS day (`topic_id` `social:<sns>:<YYYYMMDD>`). Rank human edits and finals
like human edits, rejects like ship declines, gate failures like gate failures. Targets: a channel
guide's house rules (outside the researched region) and its `house` limits (`max_chars`,
`hashtags`, `link` — narrowing only), `persona.md` (voice, themes, never-says, `mix`, new
`service_terms`, new `forbidden` rules as `draft`), `persona-notes.md`, and the distributor's
Habits. Never: the researched region or research fields (that is `--refresh`), name, aliases or
language, the waiver (only a human adds or removes it), the disclosure items except to strengthen
them, widening `house` (it only narrows), confirming a rule (a human does it), removing a service term or adding an exclusion — the social floor (INV2).

Auditor findings that point at the auditor itself (its prompt, its severity scale) are not
applied here — the auditor deliberately reads no repo guides — list them in the report as
flow-level ideas the human may file by hand (`/hrd contribute` is not available yet).

## Phase 3 — Proposals

Each: target file, the exact edit (smallest possible), evidence (plain sentences citing topics
and PRs, plus the signal `id`s from Phase 1 — Phase 6 consumes them), expected effect.
`--dry-run` prints them, runs `HRD evolve-mark --scan --token <t>`, and stops.

## Phase 4 — Adversarial panel

Spawn three fresh reviewers (opus) in parallel, one lens each: correctness (does the evidence
support it?), degradation (does it weaken verification or the floor?), redundancy (already
covered?). Each returns, per item, `{"verdict": "keep|drop|edit", "reason": "<one sentence>",
"edit": "<changed wording, only for edit>"}`. Tell every reviewer: `reason` and `edit` in
`config.language`; `edit` only for a change that alters what the item does or fixes something
that would otherwise mislead — a wording nit is `keep` with the nit in `reason`. Tell the
degradation reviewer: anything that weakens verification or the floor is `drop`, never `edit` —
for social files that includes anything on the social floor (`_invariants.md` INV2: the post
checks, confirmed rules, disclosure items and the waiver, service terms and exclusions, a gate
rule's `scope`) and a distributor Habit that contradicts it.

- Drop an item that a majority drops, that the degradation reviewer drops, or for which the
  degradation reviewer returned no valid verdict (the veto must have run). A missing or
  invalid verdict from another reviewer counts as `drop`.
- **The version on the table**: no `edit` → the Phase 3 draft. One or more `edit`s → one
  revised version, the edits combined when they are compatible. When they conflict: the
  correctness reviewer's edit if it made one (it fixes what is wrong), else the Phase 3 draft —
  and in that case the recommendation's reason says the reviewers disagreed on the wording. A
  revised version goes to a **re-check**: one fresh degradation reviewer (opus) compares it with
  the file it changes — does it loosen a fact-check rule, a critique criterion, the gate, an
  exemplar (deleting or downgrading one), the charter floor or the social floor (INV2)? Only `keep` passes;
  `drop`, `edit` or no valid verdict → the item is dropped (no further rounds).
- Say in plain words why each dropped item went. Survivors carry their verdicts and the
  version on the table into Phase 5.

## Phase 5 — Per-item approval

One item at a time, in `config.language` and plain words (no "Phase", "lens", "INV" or bare
field names): what changes (one clause plus the diff of the version on the table), why (the
evidence as a sentence citing topics and PRs), and the panel's recommendation with its reason
in one or two sentences — always exactly one of two, never a hedge:
- no `drop` → **recommend apply** (plus "the panel's revised wording" when the version on the
  table was revised); the reason says what the change fixes and that it keeps verification;
- one outvoted `drop`, whatever the others said → **recommend reject** (plus "the panel's
  revised wording" when revised); the reason is that reviewer's concern, saying which version
  it was about, or that the reviewer gave no answer (the human may well override it — every
  survivor "passed", so recommending apply here would make the label meaningless).

Then `AskUserQuestion` for that item alone: three options — apply, reject, edit — named in
`config.language` (ko 적용 / 거절 / 수정), the recommended one first and marked (ko "(권장)", ja
"(推奨)", en "(recommended)"); the question repeats the recommendation in the options' words.
Apply means the version on the table; edit means the human's wording, which goes to the same
re-check (anything but `keep` → say why and ask again: apply the version on the table, reject,
or edit once more). Wait for the answer before the next item. Rejected items go to the
ledger's skip list.

## Phase 6 — Apply

1. Apply each approved item's version on the table (or the human's edit) to its files
   (protected files trigger the guard's `ask` — that prompt is the human's
   per-file approval). Re-run `tests` that exist for the harness (`validate_content.py` on the
   last 3 published articles must still pass; every changed channel guide, `persona.md` or
   `persona-notes.md` must pass `HRD social lint --mode evolve --file <path> --target <path>`). Failure → revert the working tree for this run,
   report, and stop without committing, consuming or stamping the scan (the evidence stays
   pending and the nudge stays as it was; the same holds if the human aborts the run).
2. No item was decided (nothing proposed, nothing survived the panel) → no commit, no log row;
   go to Phase 7. Otherwise append the run to `evolution-log.md` (n, date, applied items with
   evidence, target files and the wording applied — draft, panel-revised or human-edited —
   rejected items with their Phase 3 draft (and the version on the table when it differed, so
   an unchanged draft is not proposed again), and for each decided item the panel's
   recommendation next to the human's decision) and commit once:
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
