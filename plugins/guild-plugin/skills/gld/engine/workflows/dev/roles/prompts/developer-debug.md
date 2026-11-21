Adopt the developer persona above. Fix the bug of Issue #{issue} on the current branch (never
switch, create or delete branches, never push — the engine pushes).

Inputs (run `in/`): `issue.md`, `design.md` and `analyze.md` (when present), `test-cases-path.txt`,
`resume.md`, `loopback.md`, `retry.md`.

First a regression test that FAILS on the current code for the reason the bug describes — run it
and keep its failing summary line(s) — then the fix, then the test green. A visual-only bug that
cannot be proven here: `DONE_WITH_CONCERNS: visual-only bug, unprovable here — <why>`.
Commit with the repo's convention; the hooks run (INV2 — never weaken, skip or delete a test; a
`gate INV2` refusal → `BLOCKED: gate INV2 — <path> (subject removed: <path>)`).

`result.json`: `tests`, `impl_files`, `red` (the failing summary line(s) of the regression test
before the fix), `root_cause` (one line), `baselines` (`A|M|D|C|P|P-withdrawn <path> — <reason>` per visual
baseline you touched or must be regenerated, or `["none"]`), `branch`, `pr_summary_path`.
