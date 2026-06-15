# AI Review Criteria: design — completeness

**Role lens**: requirements coverage and cross-stage consistency.

## Previous stage outputs to include
- analyze output

## Required Checklist
- [ ] Every feature from analyze output is addressed in the design
- [ ] Impact scope covers all affected files, modules, and data
- [ ] Constraints and risks are identified with mitigation strategies
- [ ] PR split is logical and each PR is independently deliverable
- [ ] Architecture decisions are consistent with existing codebase patterns
- [ ] **Testability section is present**: either `N/A (no external dependencies)` or a complete table covering each external dependency
- [ ] If `N/A`, verify by Read/Grep that the PR truly has no external dependencies (DB, network, time, randomness, file I/O, env, external services, browser APIs); flag false `N/A` as **critical**

## Cross-stage Check (analyze → design)
- Are all features and requirements from analyze reflected in the design?
- Are priorities preserved? (high-priority features should be in early PRs)
- Are out-of-scope items still out-of-scope, or did they sneak back in?

## Child Issue consistency (if this is a child)
- Is the child's design consistent with the parent's overall architecture?
- Does the child fit the PR-split rationale set by the parent?

## Codebase verification
Use Read/Grep (Section D of `_review_helpers.md`) to confirm:
- File paths mentioned in the design exist (Add/Modify/Delete classification is accurate)
- Referenced modules/symbols exist in the codebase

Discrepancies between design references and actual code are **major** findings.

## Severity guidance
- **critical**: Required checklist item failed; design will not realize analyze requirements
- **major**: Cross-stage inconsistency, broken file references, or significant coverage gap
- **minor**: Style, naming, or non-blocking improvement
