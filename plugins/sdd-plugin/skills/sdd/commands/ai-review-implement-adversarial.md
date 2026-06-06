# AI Review Criteria: implement (PR Final 3-5) — adversarial

**Role lens**: REFUTE the PR. Find at least one weakness.

See `${CLAUDE_SKILL_DIR}/commands/atoms/_review_helpers.md` Section E for the general adversarial prompt.

## Stage-specific refutation angles

1. **Tests look comprehensive but…**
   - Could the tests pass with a broken implementation? (Try mentally mutating the implementation — would any test catch it?)
   - Are the tests testing *behavior*, or just *implementation detail*?
   - Are there scenarios in the design's test plan that aren't actually covered?

2. **The diff looks clean but…**
   - Is there dead code introduced for "future use"?
   - Are there abstractions added prematurely (interface for one impl, factory for one type)?
   - Did the PR scope creep beyond the design?

3. **Edge cases the author may have missed**
   - Empty input / null / undefined
   - Concurrency: two callers hitting the same code path
   - Failure: what if the underlying call fails halfway?
   - Cancellation: what if the user navigates away mid-operation?

4. **Cross-stage drift**
   - Compare design → implement: did the implementation change the contract? (Naming, parameter order, return shape)
   - Did the PR description hide a meaningful change?

5. **Hidden coupling**
   - Does the PR rely on side effects of code in another file?
   - Are there magic values that should be constants?
   - Is there an implicit ordering between the new code and existing code that's not enforced?

6. **Security blind spots**
   - User input → DB query path: is parameterization correct?
   - User input → shell/cmd execution: is escaping correct?
   - Authentication: is the new path checking auth?

## Codebase verification (mandatory)
Use Read/Grep on the PR diff files. Try at least:
- Read 1 similar pattern in the codebase and compare against the new implementation
- Grep for "Refs #<issue>" and similar tracking to ensure traceability
- Check if any TODO/FIXME comments were introduced

## Severity guidance
- **critical**: A defect that ships to production
- **major**: A defect requiring rework or pattern misuse
- **minor**: A worthwhile question or future-improvement note
