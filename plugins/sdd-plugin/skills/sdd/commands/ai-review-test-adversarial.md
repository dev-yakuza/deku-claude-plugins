# AI Review Criteria: test — adversarial

**Role lens**: REFUTE the test output. Find at least one weakness.

See `${CLAUDE_SKILL_DIR}/commands/atoms/_review_helpers.md` Section E for the general adversarial prompt.

## Stage-specific refutation angles

1. **The tests look comprehensive but…**
   - Mentally mutate the implementation — would any test fail?
   - Could the tests pass with a no-op implementation?
   - Are the tests checking *behavior* or *implementation detail*?

2. **The QA checklist is suspiciously concise**
   - Are there UI states not covered (loading, error, empty)?
   - Are there device/browser/locale variants ignored?
   - Are there accessibility checks (screen reader, keyboard nav)?

3. **The coverage report is misleading**
   - "All tests pass" — were they run on a clean checkout, or did stale build artifacts mask a failure?
   - Are some tests skipped (`.skip`, `xfail`) without justification?

4. **Cross-stage drift**
   - Did design specify a test approach that the test stage silently changed?
   - Are there features from analyze that have NO automated test AND no manual checklist item?

5. **Parent path: integration vs unit gaps**
   - Children tested individually but integration between them not tested
   - Race condition or ordering bug only visible when children interact
   - Data flow across children not exercised end-to-end

6. **Flakiness signals**
   - Comments like "retry if fails" or "sometimes flaky"
   - Conditional skips based on environment

## Codebase verification (mandatory for parent path)
For parent integration tests, Read at least 1 child's test file and 1 of the parent's integration tests. Compare expected behavior at the boundary.

## Severity guidance
- **critical**: A test that gives false confidence in production behavior
- **major**: Missing coverage class, flakiness risk, cross-stage drift
- **minor**: Question worth raising
