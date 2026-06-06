# AI Review Criteria: analyze — quality

**Role lens**: risks, edge cases, unstated assumptions, and pattern violations.

## Previous stage outputs to include
Not applicable (analyze is the first stage).

## Quality dimensions
Evaluate the analyze output against each dimension below. Report any concrete issue you find with severity.

### Edge cases & boundary conditions
- Are boundary scenarios identified (empty, max, concurrent, failure paths)?
- Are user-error paths considered?
- Are the assumptions about input data realistic?

### Ambiguity & unstated assumptions
- Are there terms that could be interpreted multiple ways?
- Are there implicit assumptions about user/system behavior that should be explicit?
- Are non-functional requirements (perf, scale, accessibility, i18n) addressed if relevant?

### Scope & risk
- Is the scope realistic for the stated priorities?
- Are external dependencies or integration risks identified?
- Are there hidden costs (data migration, backfill, breaking changes) not stated?

### Pattern alignment
- Does the analyze output use the SDD What/Why discipline (no How/implementation details)?
- Are unrelated implementation choices accidentally embedded in the analysis?

## Severity guidance
- **critical**: Risk that would derail the feature if not addressed at this stage
- **major**: Significant gap in risk identification or quality
- **minor**: Wording improvement, additional suggestion

## Cross-stage Check
Not applicable (analyze is the first stage).
