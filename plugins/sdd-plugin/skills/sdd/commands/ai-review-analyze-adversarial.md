# AI Review Criteria: analyze — adversarial

**Role lens**: REFUTE the analyze output. Find at least one weakness. Default to skepticism.

See also `<<SKILL_DIR>>/commands/atoms/_review_helpers.md` Section E for the general adversarial reviewer prompt.

## Stage-specific refutation angles

When refuting an analyze output, hunt for these specific failure modes. Each is checkable against the Issue body and the analyze output text.

1. **Unsourced requirements presented as fact**
   - "Users want X" / "Customers expect Y" — locate the supporting evidence. If the Issue body has no link, quote, ticket reference, metric, or stated stakeholder, flag as `[major] rule_id: requirement-without-evidence`.
   - "Feature A depends on B" — is the dependency real (cited in code/docs) or inferred? Read/Grep the cited paths; if unverifiable → `[critical] rule_id: dependency-claim-unverified`.

2. **Feature list completeness from the inverse direction**
   - For each persona/role mentioned in the Issue body, walk the feature list and ask: "Which feature serves this persona?" A persona named in the Issue body with **zero** features in the list → `[major] rule_id: persona-not-served`.
   - For each user action implied by the Issue title (create / read / update / delete / list / search / share / export), confirm there is at least one feature covering it. Missing CRUD-pair (e.g., "Add" without "Remove", "Create" without "Delete") → `[major] rule_id: crud-pair-missing`.

3. **Conflicting requirements not reconciled**
   - Scan the analyze output for adjective pairs that frequently contradict: "simple" vs "extensible", "fast" vs "secure/comprehensive", "minimal" vs "configurable", "automatic" vs "auditable". If both appear without an explicit trade-off statement → `[major] rule_id: unreconciled-tradeoff`.
   - Quantitative contradictions: requirement says "latency < 100ms" but priority list places a synchronous external call as high-priority → `[critical] rule_id: contradictory-nfr`.

4. **Implicit user/system assumptions**
   - Authentication: does any feature assume "logged-in user" without the Issue saying so? Flag and ask whether anonymous access is required.
   - Locale/language: does any feature assume a specific locale (currency, date format, RTL)? If the project supports multiple locales (check `.github/.sdd-lang` + `i18n/` / `locales/` / `l10n/` dirs via Glob), an analyze that doesn't address localization → `[major] rule_id: locale-assumption`.
   - Device/platform: does the feature assume desktop vs mobile, online vs offline, ≥X screen width? Implicit assumption → `[minor] rule_id: device-assumption`.

5. **Priority order without rationale**
   - Each priority tier (high/medium/low) MUST be justified by either user impact, blocking dependency, or explicit Issue request. A tier without any of these → `[major] rule_id: priority-unjustified`.
   - Swap test: mentally swap two adjacent items in the priority list. Can you tell which order is correct from the rationale alone? If not → `[minor] rule_id: priority-arbitrary`.

6. **Out-of-scope items that hide hard work**
   - For each "out of scope" line, ask: was this excluded because it is genuinely orthogonal, or because it is the hardest part of the Issue's stated goal? Cross-check against the Issue title — if the out-of-scope item is closer to the title than any in-scope item → `[critical] rule_id: out-of-scope-evasion`.

7. **Definition of Done — measurability**
   - Each DoD line must be either (a) binary (file exists / endpoint returns 200 / test green) or (b) quantitative (≤X seconds, ≥Y% coverage). Vague verbs without numbers — "works correctly", "handles errors", "is performant", "is user-friendly" — → `[major] rule_id: dod-not-measurable`.
   - DoD that lacks a verification method (how would you *check* it?) → `[major] rule_id: dod-no-verification`.

## Codebase verification (Section D of `_review_helpers.md`)

If the analyze output references existing code paths, modules, screens, or features, use Read/Grep to verify they exist as described. Mismatches are **major** findings (`rule_id: codebase-claim-unverified`).

## Severity guidance
- **critical**: A refutation that would block shipping if unaddressed (contradictory NFRs, scope evasion, false dependency claim)
- **major**: A meaningful gap or unjustified assumption (missing persona, unmeasurable DoD, unverified codebase claim)
- **minor**: A worthwhile question that does not block (priority swap-test, implicit device assumption)

## Cross-stage Check
Not applicable.
