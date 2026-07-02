# AI Review Criteria: implement TDD step (3-1, 3-2, 3-3, 3-4)

**Role lens**: lightweight diff-only review between TDD steps.

Used by `tdd_step_review.md` atom. Step-specific section below is selected by the calling atom's `$2` argument (the step number).

## Common rules

- Input: the git diff produced by the corresponding TDD step (single-step delta from a fresh branch), plus the work atom's reported test evidence (`$5` of `tdd_step_review`).
- Scope: this step's diff only — do NOT re-review prior steps' diffs.
- Goal: catch obvious step-specific issues before the next step compounds the mistake.
- **You cannot run tests.** Wherever a checklist below says "tests pass" or "tests fail", read it as "the work atom's reported `TESTS: <p>/<t> FAILED: <f>` evidence is consistent with the step." The evidence-consistency check in `tdd_step_review.md` step 5a is the authoritative gate; this rubric is the diff-level companion.

---

## Step 3-1: Red (failing tests)

### Checklist
- [ ] Tests cover main scenarios from the implementation plan
- [ ] Tests cover edge cases identified in the design (boundary, error, concurrent)
- [ ] Test assertions are specific and meaningful (not just "no throw")
- [ ] Reported evidence shows `FAILED ≥ 1` (the Red state was verified by the work atom)
- [ ] Test names communicate the scenario clearly

### Common failure modes to flag
- Vague assertions (`expect(x).toBeDefined()`)
- Missing setup/teardown causing test pollution
- Test fixture data that doesn't reflect real input shape
- Skip/only/focus markers left in (`it.only`, `xit`)

### Coverage cross-check (applies when `<plan-body>` is available from `_tdd.md` §7.2)

For each non-`N/A` category in the Test Plan (Happy path / Error path / Boundary conditions / Concurrent/State):
- Verify the commit diff contains ≥ 1 test addressing that category.
- Zero tests AND no `// MANUAL: ...` inline note in the diff → `[major] rule_id: test-plan-category-uncovered` (cite the category name, e.g. `"Error path has no test"`).
- `// MANUAL: ...` note present → record `[minor] rule_id: manual-gap-acknowledged` (intentional omission noted by author; does not block).

### Severity guidance
- **critical**: Tests are tautologies, or do not actually fail; cannot serve as Red
- **major**: A non-`N/A` Test Plan category has no test and no `// MANUAL:` note (`rule_id: test-plan-category-uncovered`); or a significant scenario clearly implied by the design is absent with no explanation
- **minor**: Naming/assertion improvement; `// MANUAL:` note present (acknowledged gap)

---

## Step 3-2: Green (minimal implementation)

### Checklist
- [ ] Implementation is **minimal** — only what's needed to pass the tests
- [ ] Code follows existing patterns
- [ ] Reported evidence shows `FAILED: 0` (Green state verified by the work atom)
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
- [ ] Reported evidence shows `FAILED: 0` AND `<p>/<t>` matches the prior Green step's counts (no silent test count drift)

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
- [ ] Reported evidence shows `FAILED: 0` for the E2E suite (work atom verified)
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
