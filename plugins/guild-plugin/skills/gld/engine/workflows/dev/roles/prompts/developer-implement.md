Adopt the developer persona above. Implement Issue #{issue} on the current branch (the engine made
or resumed it; never switch, create or delete branches, never push — the engine pushes).

Inputs (files in your run `in/` directory): `issue.md` (the Issue), `design.md` (design output),
`skeleton-path.txt` / `test-cases-path.txt` (read both files WHOLE), `resume.md` (partial work on
this branch, or "none — fresh branch"), `loopback.md` (why the work came back, when it did) and
`retry.md` (what blocked the previous attempt of this invocation, when this is a retry).

Work test-first: a failing test for each acceptance case in `test-cases.md`, then the code. Commit
your work with the repo's commit convention (the repo's hooks run — a hook refusal is a finding to
fix, never something to route around: no `--no-verify`, no weakening/skipping/deleting a test, INV2).
If the commit gate refuses a test change with `gate INV2`, stop and return
`BLOCKED: gate INV2 — <path> (subject removed: <path>)`.

The ENGINE runs the full test suite itself after you return; still run the tests you touched.
`result.json`: `tests` (test files you added/changed), `impl_files` (non-test files you changed),
`baselines` (`A|M|D|C|P|P-withdrawn <path> — <reason>` per visual baseline you touched or must be
regenerated, or `["none"]`), `branch` (the current branch), `pr_summary_path` (a Markdown file under
your run `out/` with what you built, for the PR).
