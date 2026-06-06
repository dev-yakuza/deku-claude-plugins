# AI Review Criteria: parent integration review

**Role lens**: cross-child synthesis at the parent Issue level. Run at the test stage on parent Issues only.

## Previous stage outputs to include
- Parent Issue's analyze output
- Parent Issue's design output
- Parent Issue's `<!-- sdd:children:output -->` (child list)
- For each child: child's analyze, design, and implement review summaries

## Synthesis dimensions

### Feature distribution coverage
- The parent's analyze output identified N features.
- Each feature should be addressed by at least one child.
- **Flag**: any feature with NO corresponding child Issue.
- **Flag**: any child Issue that doesn't map to a parent feature (scope creep).

### Cross-child design consistency
- Children's designs together should equal the parent's design.
- **Flag**: design decisions in child A that contradict child B (e.g., API contract differs).
- **Flag**: PR-split rationale broken (children that depend on each other in undocumented ways).

### Cross-child implementation gaps
- Even if individual children passed implement review, gaps may emerge at integration.
- **Flag**: data shape produced by child A doesn't match what child B consumes.
- **Flag**: timing assumptions between children (child A must run before child B at runtime).
- **Flag**: shared state contention across children.

### Aggregate quality signals
- Read each child's structured findings JSON. If many children have similar `rule_id` findings → systemic issue worth surfacing.
- If multiple children failed review rounds repeatedly → quality risk for the whole parent feature.

### Closure verification
- Parent's analyze had a Definition of Done. Are all DoD items addressed across children?
- Out-of-scope items from parent's analyze — did any child accidentally implement them?

## Codebase verification (mandatory)
Use Read/Grep (Section D of `_review_helpers.md`):
- Read the interface/contract files where children connect
- Verify cross-child invariants hold in the actual code

## Severity guidance
- **critical**: Feature gap (some parent requirement has no implementation), or cross-child contract mismatch
- **major**: Systemic issue across children, design decision inconsistency
- **minor**: Suggestion for tighter integration testing or documentation

## Output marker
Posted on the **parent Issue** with `<!-- sdd:review:parent -->`. Includes the standard structured findings JSON block.
