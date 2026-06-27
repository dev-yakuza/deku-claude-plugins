# AI Review Criteria: test — quality

**Role lens**: test reliability, flakiness risk, and coverage depth.

## Previous stage outputs to include
- analyze output
- design output

## Quality dimensions

### Assertion quality
- Are assertions specific (`expect(x).toBe(42)` vs `expect(x).toBeTruthy()`)?
- Do assertions describe the actual behavior, or are they tautologies?
- Are negative assertions present (verifying the bad case)?

### Flakiness risk
- Are there time-based waits (`sleep`, `wait(500)`)? Replace with condition-based waits.
- Are there shared mutable fixtures (DB rows, file system state)?
- Are tests order-dependent (passing in one order, failing in another)?
- Are network dependencies stubbed appropriately?

### Coverage depth
- Are happy-path tests present?
- Are error-path tests present?
- Are boundary tests present (empty, max, off-by-one)?
- Are concurrency/async tests present where relevant?
- Are **branch paths** covered — not just the main branch but else/catch/default arms?
- Are **error handler bodies** exercised (catch blocks, error widgets, fallback states), not just the happy path around them?
- Are coverage configuration files (jest.config, pytest.ini, flutter_test, build.gradle, etc.) excluding only generated/vendor code — not business-critical paths?
- Are any tests skipped (`.skip`, `@Skip`, `@Ignore`, `xit`) without justification? Skipped tests silently inflate coverage numbers.

### Mock / stub accuracy
Applies to all platforms — adapt terminology to the project's test framework (jest.mock / vi.mock for JS·TS; unittest.mock / MagicMock for Python; mocktail / Mockito for Dart·Kotlin·Java; etc.).
- Do mocks match the **current** interface of the module being replaced (parameter types, return types, error contract)? A mock frozen at an old signature gives false confidence after an implement-stage refactor.
- Does the mock's behavior meaningfully represent the real module — not just "returns something" but the correct shape and semantics?
- Are HTTP/network stubs (MSW, nock, WireMock, dio mock, etc.) aligned with the actual API contract (status codes, response schema)?

### Async correctness
Applies to all platforms — adapt to the project's async model (async/await for JS·TS·Dart·C#; Future/Stream for Dart/Flutter; coroutines for Kotlin; asyncio for Python; etc.).
- Is every async test properly awaited / resolved? A missing `await` (JS·TS·Dart) or missing `async` / `await tester.pumpAndSettle()` (Flutter) causes the test to exit before assertions run — it passes vacuously and gives false confidence.
- Are unhandled promise/Future rejections present? They can silently pollute subsequent tests.
- For stream/reactive tests: is the subscription disposed and the stream completed before the test ends?

### Test isolation and cleanup
Applies to all platforms — adapt lifecycle hooks to the framework (afterEach/afterAll for Jest·Vitest; tearDown/tearDownAll for Flutter·Python unittest; @After/@AfterAll for JUnit; addTearDown for Flutter widget tests; etc.).
- Does each test leave global state (environment variables, singletons, module-level caches, database rows) exactly as it found it?
- Are lifecycle hooks (tearDown, afterEach, @After) present wherever state is mutated, not just where it is convenient?
- For Flutter: are widget trees disposed, controllers closed, and streams cancelled after each test?

### Test code readability
- Do test names describe **behavior and outcome**, not implementation (`"shows error banner when login fails"` not `"calls onError"`)?
- Is the Arrange–Act–Assert (or Given–When–Then) structure clear? Multiple act/assert cycles in one test body are a smell.
- Are magic numbers and magic strings replaced with named constants or explanatory variables?

### Regression protection
- Do the tests catch the kind of bugs that historically happened in this area?
- Is there a test for the specific bug being fixed (if this is a bug-fix Issue)?

### Manual QA checklist quality
- Is the manual checklist actually testable (specific, measurable steps)?
- Does it cover UI behavior that automated tests can't (animations, gestures, platform-specific rendering)?
- Does it explicitly include known fragile cases?

## Codebase verification
Use Read/Grep (Section D of `_review_helpers.md`) on:
- Existing test patterns in the repo — does the new test set deviate?
- Test configuration files (jest.config / vitest.config / pytest.ini / pubspec.yaml test section / build.gradle etc.) — does the new test set fit?
- Mock/stub definitions — compare against the actual module interfaces they replace.

## Severity guidance
- **critical**: Test that gives false confidence (passes when it shouldn't) — includes vacuously-passing async tests and mocks with wrong interfaces
- **major**: Flakiness risk, missing class of coverage, async correctness issue, state leak between tests
- **minor**: Assertion improvement, test name clarity, magic number, missing cleanup in non-critical path
