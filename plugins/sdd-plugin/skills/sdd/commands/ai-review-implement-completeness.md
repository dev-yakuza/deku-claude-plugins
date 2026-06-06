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
- [ ] Manual test checklist covers UI behavior and edge cases not in automated tests

## Cross-stage Check (design → implement)
- Are the planned changes fully implemented as designed?
- Did any design item get silently dropped or changed in implementation?
- Did the implementation introduce changes that were NOT in the design? If so, are they justified?

## Codebase verification
Use Read/Grep (Section D of `_review_helpers.md`) on:
- Verify each file claimed in the design's "files to modify" list appears in the PR diff
- For files NOT in the design but modified by the PR, surface them as `major` findings unless they have clear in-PR justification

## Severity guidance
- **critical**: Required design item not implemented, or PR breaks production
- **major**: Cross-stage drift, missing test coverage, undocumented behavior change
- **minor**: Naming, formatting, non-blocking suggestion
