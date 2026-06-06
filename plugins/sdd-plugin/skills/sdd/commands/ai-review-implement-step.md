# AI Review Criteria: implement TDD step (3-1, 3-2, 3-3, 3-4)

**Role lens**: lightweight diff-only review between TDD steps.

Used by `tdd_step_review.md` atom. Step-specific section below is selected by the calling atom's `$2` argument (the step number).

## Common rules

- Input: the git diff produced by the corresponding TDD step (single-step delta from a fresh branch).
- Scope: this step's diff only — do NOT re-review prior steps' diffs.
- Goal: catch obvious step-specific issues before the next step compounds the mistake.

---

## Step 3-1: Red (failing tests)

### Checklist
- [ ] Tests cover main scenarios from the implementation plan
- [ ] Tests cover edge cases identified in the design (boundary, error, concurrent)
- [ ] Test assertions are specific and meaningful (not just "no throw")
- [ ] Tests actually fail when run (the Red state was verified)
- [ ] Test names communicate the scenario clearly

### Common failure modes to flag
- Vague assertions (`expect(x).toBeDefined()`)
- Missing setup/teardown causing test pollution
- Test fixture data that doesn't reflect real input shape
- Skip/only/focus markers left in (`it.only`, `xit`)

### Severity guidance
- **critical**: Tests are tautologies, or do not actually fail; cannot serve as Red
- **major**: Significant scenario or edge case missing
- **minor**: Naming/assertion improvement

---

## Step 3-2: Green (minimal implementation)

### Checklist
- [ ] Implementation is **minimal** — only what's needed to pass the tests
- [ ] Code follows existing patterns
- [ ] All tests pass (Green state verified)
- [ ] No new debug artifacts (console.log, dbg!, print)

### Common failure modes
- Over-implementation (writing code for cases the tests don't cover)
- Hard-coded values that should come from config
- Copy-paste from elsewhere without adapting

### Severity guidance
- **critical**: Tests don't actually pass, or implementation is wrong path
- **major**: Significant scope creep beyond minimal
- **minor**: Readability nit

---

## Step 3-3: Refactor

### Checklist
- [ ] Duplication removed
- [ ] Readability improved (clearer naming, simpler structure)
- [ ] No unnecessary code, comments, or debug artifacts remain
- [ ] All tests still pass

### Common failure modes
- Refactor changes behavior (tests still pass but feature subtly differs)
- New abstractions for hypothetical future code
- Renames without updating call sites consistently

### Severity guidance
- **critical**: Refactor breaks behavior (tests didn't catch)
- **major**: Premature abstraction, inconsistent refactor
- **minor**: Naming, formatting

---

## Step 3-4: E2E

### Checklist
- [ ] E2E tests cover the key user flows for this feature
- [ ] E2E tests follow existing test framework patterns and directory structure
- [ ] E2E tests pass successfully
- [ ] No flakiness markers (retry: 3, etc.) added to mask flaky tests

### Common failure modes
- E2E using wrong framework (added Playwright when repo uses Cypress)
- Sleep-based waits instead of explicit conditions
- Tests skipped/disabled

### Severity guidance
- **critical**: E2E does not actually exercise the user flow
- **major**: Pattern violation, flakiness risk
- **minor**: Missing minor scenario

---

## Codebase verification
Use Read/Grep (Section D of `_review_helpers.md`) sparingly. For step reviews, budget is **5 Read + 3 Grep** (lower than full-stage reviews).
