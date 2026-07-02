# AI Review Criteria: design — quality

**Role lens**: feasibility, maintainability, risks, and architectural concerns.

## Previous stage outputs to include
- analyze output

## Quality dimensions

### Feasibility
- Is the proposed approach actually buildable with the codebase's current state?
- Are there unstated prerequisites (new dependencies, infra changes, secrets)?
- Are estimates implicit ("simple change") realistic for the change set?

### Maintainability
- Does the design follow existing patterns in this codebase, or invent new abstractions unnecessarily?
- Is the code change reversible if the feature gets removed later?
- Are public interfaces designed for change (versioning, defaults, backward compatibility)?

### Risk identification
- Are concurrency, race conditions, transaction boundaries considered?
- Are migration risks (data, schema, config) called out?
- Are downstream consumers (other teams, external integrations) affected?

### Test strategy realism
- Does the Testability section cover all external dependencies with concrete mock/stub strategies and verified injection points?
- Are difficult-to-test concerns (timing, randomness, async, external services) addressed with specific mitigations — not deferred with "we'll figure out testing later"?
- If the Feature List contains user-facing flows that require multi-step interaction or browser/device behavior, are these acknowledged as E2E-level scenarios in the Testability section?

### Architectural anti-patterns
- Layer violations (UI calling repo directly, repo calling UI)
- Implicit coupling that will hurt later (shared mutable state, circular deps)
- Premature abstractions (interfaces for things with single implementation)

### Testability quality
- Mock/stub strategies are realistic — the proposed injection point should actually exist in the codebase. Use Read/Grep to verify the cited DI/seam point.
- Hard-to-test concerns (timing, randomness, async) are addressed in the design — not deferred with "we'll figure out testing later".
- If Testability is marked `N/A`, verify the PR genuinely has no external dependencies. Hidden dependencies (e.g., a util that calls `Date.now()` internally) should be surfaced as **major**.

## Codebase verification
Use Read/Grep (Section D of `_review_helpers.md`) to confirm pattern claims. If the design says "follow the existing X pattern", verify the existing X pattern by reading it.

## Severity guidance
- **critical**: Will not work as designed; serious risk of broken production
- **major**: Significant maintainability/risk concern that should be addressed before implement
- **minor**: Pattern suggestion, readability improvement
