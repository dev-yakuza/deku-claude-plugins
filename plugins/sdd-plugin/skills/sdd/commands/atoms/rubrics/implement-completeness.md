# AI Review Criteria: implement (PR Final 3-5) — completeness

**Role lens**: requirements coverage and cross-stage consistency for the implementation PR.

## Previous stage outputs to include
- design output
- implement plan (`<!-- sdd:implement:plan -->`)

## Required Checklist
- [ ] All design items for this PR scope are implemented
- [ ] Tests cover the main scenarios and edge cases from the design
- [ ] Code follows existing codebase patterns and conventions
- [ ] No unnecessary code, comments, or debug artifacts remain
- [ ] PR description accurately reflects the changes
- [ ] **PR description is self-contained** — a reviewer reading ONLY the PR (without opening the parent Issue / referenced Issues) can understand WHAT changes, WHY they are needed, and HOW they are done. Ad-hoc taxonomy terms from upstream Issues (e.g. `"C group"`, `"the boilerplate"`) are either re-defined inline or replaced with self-explanatory wording. Treat violation as `major`.
- [ ] Manual test checklist covers UI behavior and edge cases not in automated tests

## Cross-stage Check (design → implement)
- Are the planned changes fully implemented as designed?
- Did any design item get silently dropped or changed in implementation?
- Did the implementation introduce changes that were NOT in the design? If so, are they justified?
- **Testability adherence**: Does the implementation follow design's Testability section?
  - For each row in design's Testability table: verify the implementation uses the same mock/stub strategy.
  - If design specified `mock the Clock`, the test code should mock it — no real `Date.now()` calls in the test path.
  - If design's Testability = `N/A`, verify the PR does not introduce hidden external dependencies (time/network/IO/random) that should have been declared.

## Codebase verification
Use Read/Grep (Section D of `_review_helpers.md`) on:
- Verify each file claimed in the design's "files to modify" list appears in the PR diff
- For files NOT in the design but modified by the PR, surface them as `major` findings unless they have clear in-PR justification

## Severity guidance
- **critical**: Required design item not implemented, or PR breaks production
- **major**: Cross-stage drift, missing test coverage, undocumented behavior change
- **minor**: Naming, formatting, non-blocking suggestion
