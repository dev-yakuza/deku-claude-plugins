# AI Review Criteria: analyze — completeness

**Role lens**: requirements coverage and internal consistency.

## Previous stage outputs to include
Not applicable (analyze is the first stage).

## Required Checklist
- [ ] Every feature has both What (what to build) and Why (motivation/background)
- [ ] Every feature has a verifiable acceptance criterion — binary or measurable, not "works correctly" or "looks good" (duplicates `analyze-adversarial.md` DoD rules intentionally to avoid R6-only detection)
- [ ] Dependencies or conflicts between features are identified
- [ ] Priorities have clear rationale
- [ ] Ambiguous terms are defined or clarified
- [ ] Out-of-scope items are explicitly stated

## Internal consistency
Within the analyze output itself, verify:
- Feature list and Priority table reference the same features
- Background motivations align with the feature list
- No contradictions between Summary, Feature List, and Priority

## Severity guidance
- **critical**: Missing required checklist item that prevents downstream design
- **major**: Inconsistency or significant coverage gap
- **minor**: Style, wording, or non-blocking clarification suggestion

## Cross-stage Check
Not applicable (analyze is the first stage).
