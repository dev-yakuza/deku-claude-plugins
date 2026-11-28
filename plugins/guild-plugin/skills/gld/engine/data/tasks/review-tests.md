Review the **tests** of this change, not the production code. The branch diff is `review.diff` (engine folder); the intent is the acceptance criteria in `analysis.md` and the cases in `test-cases.md`. Read both whole.

Check (check id `test-quality`: `pass` when all hold, `fail` when one does not — then give it as a finding):
- every case of `test-cases.md` that is testable has a test that really proves it, and every AC is proven by at least one test;
- a test would fail if the behaviour it names broke — flag tests that pass without the implementation, assert nothing about the behaviour, only mirror the implementation's internals or only check that code ran (vacuous tests);
- edge and failure paths of the cases are tested, not just the happy path;
- nothing verifies less than before: no deleted test file, no net-removed assertions, no new skip/focus directives, no loosened tolerance or rewritten expected image the Issue did not call for.

You cannot run anything; the engine's `run` steps already ran the suite. Judge from the diff and the files. `reviewed` lists the test files you read in full.
