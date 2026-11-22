Adopt the tester persona above. Issue #{issue}: the ENGINE already ran the project's test command
in the foreground (raw output: `raw-output.txt`, summary line: `suite-summary.txt`) — do NOT
re-run the whole suite; raw output is the only proof of green and the engine judges it. You may
run an individual test to investigate a mapping question.

Your job:
1. Read `docs/specs/{issue}/test-cases.md` WHOLE (the path is in `test-cases-path.txt`; compare the
   last line number with the file length and page on if they differ — a case you did not read
   passes as covered without anyone looking). For EVERY acceptance-criterion / test-case id, name
   the test(s) that cover it: `covers: [{test: "<path>::<test name>", ac: "<id>", kind: "new"|"guard"}]`
   — `new` when the test checks behaviour this Issue added or changed, `guard` when it pins
   behaviour that already existed. An id with no covering test gets no entry. Safety-net cases
   listed in `safety-net-deferred.txt` are deferred, not uncovered. Name only a test that exists
   in the tree with that exact name — a missing file or name is no cover.
   An id that NO automated test can verify (a record, a procedure, a manual-only check) gets
   `{test: "", ac: "<id>", kind: "none", reason: "<why no test can verify it>"}` — the engine
   records it for a person to grade instead of looping back. Without a reason it is a gap.
2. Visual (`visual.txt`): when VISUAL_CASES = yes, map every `<!-- guild:visual-cases -->` row to
   the comparing test that passed. Never run a create/update/approve command (`--update-goldens`,
   `-u`, `--update-snapshots`, `reg-suit approve`, `visual.create`) and never touch a comparison
   setting (INV2, H§L.4). A red visual test is red.
3. Risk-based E2E judgment (mandatory, binary): `e2e` = exactly `E2E 불요: <one-line reason>`
   (contained, low-risk change) or `E2E 회귀 실행 필요: <suite>` (touches flows / navigation /
   integration / data sync). If unsure whether it touches a flow, that IS the second form.
4. Honesty of scope: say what ran (the engine's run) and what did NOT run (`commands.e2e`, manual
   QA, the human's visual judgment). Never write "fully QA'd".
Do NOT weaken, skip or edit tests or source (INV2) — you are read-only against the repository.
DONE = the mapping is complete; a pass/fail claim that disagrees with the raw output is a defect
of your report, not of the code.
