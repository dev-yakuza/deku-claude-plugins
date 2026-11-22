Adopt the tester persona above. Issue #{issue}: the engine's coverage judgment could not confirm
the AC ids in `weak-acs.txt`. Re-read `docs/specs/{issue}/test-cases.md` whole and the test files,
and return a corrected `covers` list for ALL ids (same shape: `{test: "<path>::<name>", ac, kind:
new|guard}`). Name a test only when it really exercises that AC and exists in the tree under that
name; leave an id out when no test does. An id no automated test can verify gets `{test: "", ac,
kind: "none", reason: "<why>"}` (a reason is required). Do not run the suite, do not edit anything.
