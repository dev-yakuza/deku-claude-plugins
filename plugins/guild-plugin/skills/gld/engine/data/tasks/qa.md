Do the holistic quality review of this change and write the **Manual Test Checklist** to `docs/specs/<issue>/manual-test-checklist.md`. The automated suite, lint, type check, build and E2E already ran as engine steps; do not repeat the tester's coverage and do not run anything yourself — decide what a human still has to look at. The diff is `review.diff` (engine folder); the intent is `analysis.md`, `skeleton.md` and `test-cases.md`.

1. **Risk-based plan.** From the change scope and the acceptance criteria decide which qualities the change warrants: exploratory flows, real-device or platform behaviour, usability, visual judgement. A tiny contained change gets a light, justified plan.
2. **Prefer automation to deferral.** Before you put anything on the human list, ask whether the repository's own test framework could prove it (structure, focus order, keyboard handling, state guards, error text; a visual state by a golden test when the repository has them). If it could, that is a coverage gap: it does not go onto the human list; set `qa-acceptance` to `fail` and give a `major` finding that names the test to write — the step goes back to the developer.
3. **The human list.** Everything left that a person must verify, each as a checkbox item: **what to verify and where / how**. Include anything that could not be run here because of an environment or platform constraint and every judgement that needs human perception. Leave out what an automated test or an engine run already proves. Every entry is something the human MUST do: write instructions, never advice — no "recommended", "if possible", "optionally"; translate such words away. When a changed expected image or comparison setting appears in the diff, add one item asking the human to confirm the new expectation is the intended one. End every item with the tag of the acceptance criteria it checks, in parentheses — `(AC #2)`, or `(AC #2, #3)` for several: from stage 2 the leader's done-gate can call an acceptance criterion `manual` only when this checklist names it that way.
4. **Check id `qa-acceptance`**: `pass` when every acceptance criterion is either proven by an automated test (cite its case id in `note`) or covered by a checklist item; `fail` when one is neither, or when you found an automatable gap (item 2).

File format (keep the markers, write the headings and items in the language of the Issue). With no human item, keep both markers and one line saying that everything is proven automatically and no human check is needed:

```
<!-- guild:manual-qa -->
## Manual Test Checklist
Only what automated tests cannot verify:
- [ ] <what to verify> — <where / how> (AC #1)
<!-- /guild:manual-qa -->
```
