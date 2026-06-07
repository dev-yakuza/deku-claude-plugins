# AI Review Criteria: design — adversarial

**Role lens**: REFUTE the design. Find at least one weakness.

See `${CLAUDE_SKILL_DIR}/commands/atoms/_review_helpers.md` Section E for the general adversarial prompt.

## Stage-specific refutation angles

Each refutation angle below names the specific failure mode, what to check, and the severity to assign.

1. **The proposed approach is one of many — why this one?**
   - The design MUST state at least one rejected alternative with reasoning. None present → `[major] rule_id: no-alternative-considered`.
   - Simpler-design probe: ask "could the same outcome be reached by extending an existing module instead of adding a new one?" Read/Grep for existing modules covering ≥50% of the design's responsibility. If one exists and the design adds parallel structure without explaining why → `[major] rule_id: parallel-structure-unjustified`.

2. **PR split — independence and ordering**
   - For each PR in the split, ask: "If I merge PRs in reverse order, does master compile/test green?" Find any backward-dependency not declared in the design → `[critical] rule_id: pr-order-hidden`.
   - Half-feature PRs: a PR that adds a function but no caller, or a UI without its data source, leaves master in an inconsistent state. Detect by scanning each PR's "changes" for new exports with no in-PR usage and no follow-up PR consuming them → `[major] rule_id: pr-leaves-master-inconsistent`.
   - Convenience-cut boundaries: PR titled "refactor + feat" or "feat + tests + docs" combined for one ticket → `[minor] rule_id: pr-boundary-by-convenience`.

3. **Mitigation strategies that defer the hard part**
   - "We'll add monitoring later" / "metrics in v2" / "handle this edge case after launch" — each such phrase against a risk classified critical/high in the design → `[critical] rule_id: critical-risk-deferred`. Lower-classified risks → `[major]`.
   - "Fallback" that re-introduces the original problem (e.g., fallback to the unsafe path on error) → `[critical] rule_id: fallback-defeats-mitigation`.

4. **Codebase pattern claims — verify by Read/Grep**
   - For every cited pattern (e.g., "use the existing `XService` pattern", "follow `useThing` hook convention"), Read 1 reference instance. If the cited file/symbol does not exist → `[critical] rule_id: pattern-not-found`. If it exists but behaves differently than the design's description → `[critical] rule_id: pattern-misdescribed`.
   - If the design cites a directory layout (`src/features/<x>/`), Glob to confirm the layout actually exists. Mismatch → `[major] rule_id: layout-claim-incorrect`.

5. **Cross-stage drift from analyze**
   - Read the `<!-- sdd:analyze:output -->` block. For each high-priority feature, locate its design entry. Missing → `[critical] rule_id: high-priority-feature-dropped`.
   - For each out-of-scope item in analyze, scan the design for re-introduction. Silent reappearance → `[major] rule_id: out-of-scope-silently-reintroduced`.
   - Non-functional requirements (perf budget, accessibility level, security control) named in analyze but absent from design → `[major] rule_id: nfr-silently-dropped`.

6. **Hidden complexity — gloss phrases**
   - Flag every occurrence of these glosses and require a concrete plan: "straightforward", "trivial", "just call", "simply", "should be easy", "wire up". Each gloss against a step touching external systems, schema migration, async/concurrency, or cross-team coordination → `[major] rule_id: complexity-glossed`. Same gloss on pure-function changes → `[minor]`.
   - External-integration underspecification: any "call the API" / "use the SDK" / "integrate with X" without naming the auth model, error contract, rate limits, idempotency, and timeout → `[major] rule_id: external-integration-underspecified`.

7. **Testability claims — verify the seam exists**
   - For each Testability row, the seam point (DI socket, injectable Clock, mockable client) MUST be greppable in the codebase. Grep for the cited injection symbol; zero hits → `[major] rule_id: testability-seam-missing`.
   - Module-load-time imports: if a mock target is imported at module top level (not via a factory/DI), runtime mocking is brittle. Confirm by Reading the calling file → `[major] rule_id: testability-seam-brittle`.
   - Testability = `N/A`: Glob the design's File Structure section for matching paths, then Grep those files for time/network/IO/randomness calls (`new Date`, `Date.now`, `fetch`, `axios`, `Math.random`, `setTimeout`, file/DB I/O). Any hit → `[critical] rule_id: testability-na-but-side-effects-present`.

8. **Data shape and contract drift**
   - For every API signature in the design (function name + parameters + return type), Read the analyze's stated inputs/outputs. Mismatch (renamed param, dropped field, changed type) without a stated reason → `[critical] rule_id: contract-drift`.
   - For every schema/DB change, check if the design names the migration path (forward + backward) and rollout order. Missing → `[major] rule_id: schema-migration-unspecified`.

## Codebase verification (mandatory)
Use Read/Grep (Section D of `_review_helpers.md`). At minimum:
- Verify 1-2 file paths cited in the design exist
- Verify 1 architectural pattern claim by reading the cited code

## Severity guidance
- **critical**: A refutation that would block correct implementation
- **major**: A gap that would cause rework in implement
- **minor**: A worthwhile question
