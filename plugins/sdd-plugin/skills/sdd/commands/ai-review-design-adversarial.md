# AI Review Criteria: design — adversarial

**Role lens**: REFUTE the design. Find at least one weakness.

See `${CLAUDE_SKILL_DIR}/commands/atoms/_review_helpers.md` Section E for the general adversarial prompt.

## Stage-specific refutation angles

1. **The proposed approach is one of many — why this one?**
   - Are alternatives considered and rejected with reasons?
   - Is there a simpler design that solves the same problem?

2. **PR split is suspicious**
   - Could PRs be merged independently without breaking master?
   - Is there hidden ordering (PR A must merge before PR B even though it's not stated)?
   - Are PR boundaries cut for convenience, or for delivery value?

3. **Mitigation strategies are wishful**
   - "We'll add monitoring later" — what if "later" never comes?
   - "We'll handle this edge case in v2" — does v1 break v2's path?

4. **Codebase pattern claims unverified**
   - Read/Grep the cited patterns. If the cited pattern doesn't actually exist or behaves differently, that's a **critical** finding.

5. **Cross-stage drift from analyze**
   - Did a feature priority silently change?
   - Did an out-of-scope item silently appear in the design?
   - Are non-functional requirements (perf, accessibility) silently dropped?

6. **Hidden complexity**
   - Are there steps the design glosses over ("the migration is straightforward")?
   - Are external integrations underspecified ("call the API")?

7. **Testability claims are plausible but not actually achievable**
   - The Testability section names mock/stub strategies — but are they realistic given the codebase's *actual* DI patterns?
   - Mocking a third-party SDK that the codebase imports at module-load level — does the seam point really exist?
   - "We'll inject Clock for testability" — is there evidence of similar Clock injection elsewhere in this repo?
   - Use Read/Grep to verify at least 1 cited injection/seam point. Mismatch is a **major** finding.
   - If Testability = `N/A`, search the actual changed files for time/network/IO calls. False `N/A` = **critical**.

## Codebase verification (mandatory)
Use Read/Grep (Section D of `_review_helpers.md`). At minimum:
- Verify 1-2 file paths cited in the design exist
- Verify 1 architectural pattern claim by reading the cited code

## Severity guidance
- **critical**: A refutation that would block correct implementation
- **major**: A gap that would cause rework in implement
- **minor**: A worthwhile question
