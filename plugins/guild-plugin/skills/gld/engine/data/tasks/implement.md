Implement the Issue on the current branch. Your inputs are `analysis.md` (what), `skeleton.md` (how, the design you must honour) and `test-cases.md` (what the tests must prove).

Read them as the TDD cycle reaches them, not all at once: start with the test cases and the skeleton's structure and boundary sections, and pull a module's section when you begin that module. That is deferral, not skipping — every section you implement against is still read in full. Attach each read to a turn you were taking anyway; do not page through files.

Do TDD: write the tests of the cases and see them fail (red), implement to green, then refactor. If `test-cases.md` has visual cases, implement each as a golden/screenshot test in the repository's own style.

When this step was returned (see "Returned" and "Re-entry" below), find the cause of the listed failure — do not assume the code involved in it is correct — fix it, and show with the raw output of the relevant tests that it now passes. Keep the work that is unrelated to the failure. If files were left uncommitted by the earlier attempt, finish or revert them yourself; the tree must be clean at the end.

Result `note`: the raw test summary line(s) of what you ran, and the branch name.
