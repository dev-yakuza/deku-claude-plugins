# AI Review Criteria: test — quality

**Role lens**: test reliability, flakiness risk, and coverage depth.

## Previous stage outputs to include
- analyze output
- design output

## Quality dimensions

### Assertion quality
- Are assertions specific (`expect(x).toBe(42)` vs `expect(x).toBeTruthy()`)?
- Do assertions describe the actual behavior, or are they tautologies?
- Are negative assertions present (verifying the bad case)?

### Flakiness risk
- Are there time-based waits (`sleep`, `wait(500)`)? Replace with condition-based waits.
- Are there shared mutable fixtures (DB rows, file system state)?
- Are tests order-dependent (passing in one order, failing in another)?
- Are network dependencies stubbed appropriately?

### Coverage depth
- Are happy-path tests present?
- Are error-path tests present?
- Are boundary tests present (empty, max, off-by-one)?
- Are concurrency tests present where relevant?

### Regression protection
- Do the tests catch the kind of bugs that historically happened in this area?
- Is there a test for the specific bug being fixed (if this is a bug-fix Issue)?

### Manual QA checklist quality
- Is the manual checklist actually testable (specific, measurable steps)?
- Does it cover UI behavior that automated tests can't?
- Does it explicitly include known fragile cases?

## Codebase verification
Use Read/Grep (Section D of `_review_helpers.md`) on:
- Existing test patterns in the repo — does the new test set deviate?
- Test configuration files (jest.config, vitest.config, pytest.ini) — does the new test set fit?

## Severity guidance
- **critical**: Test that gives false confidence (passes when it shouldn't)
- **major**: Flakiness risk, missing class of coverage
- **minor**: Assertion improvement, test name clarity
