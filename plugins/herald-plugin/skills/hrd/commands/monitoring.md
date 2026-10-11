# MONITORING — snapshot and external metrics (`/hrd monitoring [--connect-gsc] [--html]`)

Plan §3.6 (M5 external signals), §3.7 (cost). Read-only except `--connect-gsc`.

## Snapshot

- Queue and states (`HRD status`), publish rate, holds by reason.
- Cost: `python3 .claude/herald/scripts/measure.py` for the latest session, or per batch log
  (`.claude/herald/memory/batch-logs/*.jsonl` via `--file`) — dollars per article, per role,
  read calls and bytes (the read-list hypothesis, §3.7).
- Unused signals by kind (not yet consumed by a decided evolve proposal): `HRD evolve-readiness`
  (`kinds`, `tier`, `last_scan`).
- `--html` writes `.claude/herald/memory/monitoring.html` with the same tables.

## Search Console (M5)

`--connect-gsc`: the human creates a Google Cloud service account with read access to the
property and saves the key JSON to `.claude/herald/secrets/gsc.json` (gitignored — INV5); store
the property URL in `config.site.gsc_property` (`site` is not a protected key).
Requires `pip install google-auth requests`. Then
`python3 .claude/herald/scripts/gsc.py collect` reads, for each published URL, impressions ·
clicks · CTR · average position · top queries for the last 28 days vs the previous 28
(Search Console `searchAnalytics.query`) and writes `.claude/herald/memory/metrics.json`;
`gsc.py show` prints the cached result. `evolve` uses it only above the data-sufficiency
threshold; `refresh` uses drops (clicks −30% vs the previous 28 days) as candidates.
Never send credentials or metrics anywhere else.
