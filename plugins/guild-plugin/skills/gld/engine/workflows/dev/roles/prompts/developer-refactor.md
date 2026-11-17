Adopt the developer persona above. Refactor Issue #{issue} on the current branch toward the target
structure (`skeleton-path.txt`). Never switch to another branch at the end, never push.

Behavior-preserving is the contract: the existing tests stay green before and after; no features,
no observable change, no weakened/skipped/deleted test (INV2). A test that asserted an
implementation detail the refactor legitimately removes: say so, with the justification, in
`pr_summary_path`.

Safety net (`net.md`): when it says `SAFETY_NET = with-refactor|only`, follow it exactly — the net
first in new test files of its own, committed alone, green on unchanged code; prove it as a TREE on
the merge base when told to (no commit, no ref, no reset, put the index back, `git switch` back to
the branch). Report `safety-net:`, the run lines, `post-transform-net:` and `leftover:` in
`pr_summary_path`, and `deferred` cases with `DONE_WITH_CONCERNS: untestable without a seam: …`.

Inputs (run `in/`): `issue.md`, `skeleton-path.txt`, `test-cases-path.txt`, `net.md`, `resume.md`,
`loopback.md`, `retry.md`. `result.json` as for implement (`tests`, `impl_files`, `baselines`,
`branch`, `pr_summary_path`).
