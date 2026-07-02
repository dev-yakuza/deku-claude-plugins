# AI Review Criteria: test — completeness

**Role lens**: test coverage and cross-stage consistency.

## Previous stage outputs to include
- analyze output
- design output

## Required Checklist
- [ ] E2E tests cover the main user flows from the requirements
- [ ] Edge cases identified in analyze/design are tested
- [ ] Regression risks for existing functionality are addressed
- [ ] Test assertions are specific and meaningful (not just "no error")
- [ ] QA checklist separates automated coverage from manual verification needs
- [ ] Each item in the Manual section falls into a genuinely-manual category: UI/UX appearance, accessibility, performance, unmockable external integration, or E2E-skipped scenario — items that could be automated → `[major] manual-item-may-be-automatable`
- [ ] If `<!-- sdd:e2e-skipped-scenario -->` exists on the Issue: each scenario listed there appears in the Manual section of the QA checklist (or is demonstrably covered by a compensating integration test in the PR diff)

## Cross-stage Check
- Compare against analyze + design outputs: are all requirements and risk areas covered by tests?
- Cross-check the test output's QA checklist against the design's Definition of Done — are DoD items covered?

## Path-specific
- **Single/Child path**: tests written in implement stage are validated; QA checklist covers what tests do not.
- **Parent path**: integration tests (if any) cover cross-child scenarios from the design.

## Codebase verification
Use Read/Grep (Section D of `_review_helpers.md`) on:
- The PR's test files — are they running the scenarios the report claims?
- The existing test directory structure — do new tests fit the existing pattern?

## Severity guidance
- **critical**: A required user flow has no test coverage
- **major**: A design-identified edge case is missing, or QA checklist is misleading
- **minor**: Better test name suggestions, additional minor scenarios
