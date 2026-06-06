# AI Review Criteria: implement (PR Final 3-5) — quality

**Role lens**: code quality, security, performance, maintainability.

## Previous stage outputs to include
- design output
- implement plan

## Quality dimensions

### Correctness
- Off-by-one errors, null/undefined handling, type coercion bugs
- Async/await correctness, promise rejection paths
- Concurrency: races, shared mutable state, ordering assumptions
- Error handling: are errors caught at the right boundary? are messages safe?

### Security
- Input validation at trust boundaries (user input, API responses, env vars)
- Injection vectors: SQL, command, XSS, prototype pollution, deserialization
- Authentication/authorization: are checks at every required gate?
- Secrets: no credentials in code, logs, or commit messages
- Sensitive data: no PII in logs, error messages, or analytics

### Performance
- Unnecessary work in hot paths (loops, renders, queries)
- N+1 queries, missing indexes, missing pagination
- Memory: leaks, oversized allocations, retained references
- Bundle/asset size impact for frontend changes

### Maintainability
- Public API design: is it stable? versioning? defaults?
- Dead code, commented-out blocks, debug artifacts (console.log, dbg!)
- Test brittleness: tests that depend on internals or timing
- Readability: deeply nested logic, long functions, unclear naming

### Pattern violations
- Layer boundaries respected (UI ↛ DB direct, etc.)
- Naming conventions consistent with repo
- File organization follows existing structure

## Codebase verification
Use Read/Grep (Section D of `_review_helpers.md`). Look at 1-2 similar existing implementations to compare patterns.

## Severity guidance
- **critical**: Correctness bug, security vulnerability, severe perf regression
- **major**: Significant quality issue, pattern violation, missing test
- **minor**: Style, naming, minor improvement
