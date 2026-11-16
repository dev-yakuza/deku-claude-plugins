# SJ-TEST — does each acceptance criterion have an EFFECTIVE covering test? (§3.3, T-AC-COVER, T-VACUOUS)

The suite already ran green (the engine ran it; the raw output is in the brief). For every AC id:
- `effective` — a cited test exercises the AC's behaviour AND its assertion would fail if that
  behaviour broke (#894: a check skipped in one path passes regardless — that is `vacuous`).
- `vacuous` — a test is cited but asserts nothing meaningful about the AC, or cannot fail.
- `not_covering` — no cited test exercises this AC (a test of something else is not coverage).
- `unsure` — the excerpts do not let you tell.
`covered_by` lists the test references you relied on (copy them from the tester's `covers`).
Visual rows: `covered` only when a comparing test that passed is named for that row.
Your `effective` is re-checked by code (an assertion line must exist, and for new behaviour the
test must fail with the implementation reverted) — do not call a test effective on its name alone.
`overall` = `all_effective` only when every AC is `effective`.
Use the Read/Grep tools on the repository when an excerpt is cut short.
