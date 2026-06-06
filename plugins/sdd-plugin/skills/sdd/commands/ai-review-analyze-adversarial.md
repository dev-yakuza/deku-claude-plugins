# AI Review Criteria: analyze — adversarial

**Role lens**: REFUTE the analyze output. Find at least one weakness. Default to skepticism.

See also `${CLAUDE_SKILL_DIR}/commands/atoms/_review_helpers.md` Section E for the general adversarial reviewer prompt.

## Stage-specific refutation angles

When refuting an analyze output, focus on:

1. **Stated requirements that may not actually hold in this codebase context**
   - "Users want X" — do we have evidence, or is this an assumption?
   - "Feature A depends on B" — is the dependency real, or is it inferred?

2. **Feature list completeness from the inverse direction**
   - What use case is *NOT* in this list that probably should be?
   - What user persona is *NOT* served by this feature list?

3. **Priority rationale weak points**
   - Is the priority order justified by data/usage, or is it arbitrary?
   - Could a different prioritization yield a better outcome?

4. **Out-of-scope items that are suspiciously convenient**
   - Was anything pushed out-of-scope to avoid hard work, not because it's truly orthogonal?

5. **Definition of Done specificity**
   - Are the DoD criteria measurable, or could they be claimed "done" without verification?

## Codebase verification (Section D of `_review_helpers.md`)

If the analyze output references existing code paths, modules, or screens, use Read/Grep to verify they exist as described. Mismatches are **major** findings.

## Severity guidance
- **critical**: A refutation that would block shipping if unaddressed
- **major**: A meaningful gap or unjustified assumption
- **minor**: A worthwhile question that does not block

## Cross-stage Check
Not applicable.
