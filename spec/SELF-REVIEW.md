# Self-Review Findings — Phase A Spec

Internal review of the extracted spec before dispatching agent reviews.

## File Status

| File | Lines | Status |
|---|---:|---|
| README.md | 50 | ✓ |
| 00-common-contracts.md | ~430 | ✓ |
| 01-config.md | ~250 | ✓ |
| 02-multilingual.md | ~140 | ✓ |
| stage/analyze.md | 315 | ✓ |
| stage/design.md | 402 | ✓ |
| stage/implement.md | 490 | ✓ |
| stage/test.md | 448 | ✓ |
| flow/resume.md | 139 | ✓ |
| flow/auto.md | 359 | ✓ |
| flow/batch.md | 463 | ✓ |
| utilities.md | 338 | ✓ |
| commands-inventory.md | 127 | ✓ |
| edge-cases.md | ~410 | ✓ |
| **Total** | **~4,360** | — |

Source extracted from ~7,000 lines (~62% compression with cross-cutting consolidation).

## Strengths

1. **Consistent classification** — every behavioral item tagged [PRESERVE]/[IMPROVE]/[RETHINK].
2. **Line citations** — every nontrivial claim references source file + line numbers.
3. **Cross-references work** — common-contracts → config → stage → flow → utilities cascade is followed.
4. **Decision tables** — every stage has explicit branching tables (verdict combination, retry decisions, mode detection).
5. **Edge cases catalogued** — 24 cross-cutting edge cases with cross-references to stage/flow specs.
6. **Cross-stage invariants** — every stage spec ends with what downstream stages assume.

## Identified Gaps / Concerns

### G1. Cross-reference style inconsistency [IMPROVE — spec hygiene]
Three styles in use:
- "Common Contracts §X"
- "00-common-contracts.md §X"  
- "`spec/00-common-contracts.md` §X"

→ Should standardize on one form before Phase A close. Recommend `spec/00-common-contracts.md §X` (most explicit).

### G2. Model table duplication [PRESERVE for now]
The depth → model assignment table appears in:
- `_review_helpers.md` Section A.2 (canonical source)
- `01-config.md` §3 (spec mirror)
- Each `stage/*.md` Phase 0 section (per-stage citations)

This duplication exists in source code too. The spec mirrors it. Design phase should DRY into single registry.

### G3. `/sdd review` adversarial asymmetry [RETHINK — surfaced by utilities review]
`/sdd review` re-spawns only completeness + quality, NOT adversarial. This is asymmetric vs per-stage orchestrator's 3-reviewer model. Decision deferred to design phase but should be flagged loudly.

### G4. Version drift (plugin.json 0.36.0 vs marketplace.json 0.35.0) [PRESERVE]
Real bug detected during extraction. Flagged in:
- `commands-inventory.md` §3 [IMPROVE recommendation: pre-commit hook]
- `edge-cases.md` §20

→ Phase A external concern — user should fix this separately.

### G5. Round-aware marker decision deferred [RETHINK across many files]
Multiple specs flag this:
- `00-common-contracts.md` §4 (Update-in-place invariant — RETHINK note)
- `edge-cases.md` §6 (consolidated discussion)
- `stage/analyze.md` §2, §9.4
- `stage/design.md` §2

→ Big design-phase decision. Either keep overwrite (simpler) or add `:r{N}` suffix (audit trail). Spec correctly catalogs both.

### G6. Skip-review semantic naming [IMPROVE]
Multiple specs note that the key name `skip-review` is misleading — it skips the user gate, not the AI review. Suggested rename to `skip-confirm`.
- `01-config.md` §2 [IMPROVE]
- `edge-cases.md` §18 [IMPROVE]

This propagates through every stage spec.

### G7. Language detection not persisted [IMPROVE]
- `stage/analyze.md` §9.5 — flags that detected language is NOT written back to `.sdd-lang`
- `stage/design.md` §8 — same flag

→ Cross-stage drift possible if Issue body language is detected differently across stages.

### G8. Implement stage's empty-`$3` + existing PR is unhandled gap [PRESERVE — known bug]
- `stage/implement.md` §1 flags this as `[PRESERVE / RETHINK]` — current code has the gap; spec captures it.

→ Decision: rewrite should handle this case explicitly (idempotent resume).

### G9. ai-review-*.md location [IMPROVE — discovered during extraction]
- `utilities.md` §7 catalogs them
- `edge-cases.md` §21 confirms NOT vestigial, are rubric files referenced by reviewer atoms
- Location in `commands/` is misleading (they're not user-invocable)

→ Move to `atoms/rubrics/` in rewrite.

### G10. Bash heuristic rules repeated across orchestrators [IMPROVE]
- `00-common-contracts.md` §8 has canonical version
- Each stage orchestrator includes a paraphrase paragraph
- `edge-cases.md` §14 has cheat-sheet

→ Single canonical reference; orchestrators link, not paraphrase.

### G11. Schema version field [IMPROVE — actionable now]
`00-common-contracts.md` §5 suggests adding `schema_version: 1` to findings JSON. Not yet in any review atom. → Could be retrofitted before rewrite (additive change, backward-compat).

## Cross-file Sanity Checks

### Marker inventory cross-check ✓
Markers listed in `00-common-contracts.md` §4 all appear in their respective stage specs with correct posting atom attribution.

### Skip-review key cross-check ✓
Keys `analyze`, `design`, `implement`, `pr`, `qa` all appear consistently across:
- `01-config.md` §2
- Each `stage/*.md` skip-review section
- `flow/auto.md`, `flow/batch.md` (both auto-enable some subset)

### Retry slot cross-check ✓
- `00-common-contracts.md` §7 says: analyze/design/test = `$2`; implement_red/green/refactor/e2e = `$3`; implement_pr = `$3`
- Each stage spec confirms its slot position
- `edge-cases.md` §9 reiterates

Consistent.

### Parent regex cross-check ✓
- `02-multilingual.md` §3 is canonical: `(Parent|상위 |親)Issue: #<n>` with `([^0-9]|$)` boundary
- All 5+ caller locations reference this canonical form
- `edge-cases.md` §1 cross-references

## Verdict

Spec is **complete and internally consistent**. 11 identified gaps are all already classified — none are blockers for moving to agent review.

**Recommendation**: proceed to Task #8 (parallel agent review).
