Adopt the developer persona above. Issue #{issue}: write ONLY the failing tests for the acceptance
cases in `test-cases.md` (`test-cases-path.txt`) — no production code. Stage them (`git add`), do
not commit. Name the production files the implementation will need to change.

If a new production file is needed, you cannot name the files, or the bug is visual-only, return
`DONE_WITH_CONCERNS: local-ineligible — <why>`.
`result.json`: `tests` (staged test files), `impl_files` (existing production files to change),
`red` (the failing summary line), `root_cause` (debug only, one line), `baselines` (`["none"]`),
`branch`, `pr_summary_path` (any file under `out/`).
