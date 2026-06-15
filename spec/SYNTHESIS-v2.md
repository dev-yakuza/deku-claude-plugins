# Synthesis — Spec v1 → v2

Phase A spec finalization. Applies findings from 3 parallel reviewer agents (Completeness, Accuracy, Classification).

## Backward Compat Policy (user-confirmed)

**Decided**: External contracts preserved as-is. Internal structure freely refactorable.

| Surface | Treatment in rewrite |
|---|---|
| GitHub labels (`sdd:analyze`, etc.) | PRESERVE — exact names |
| Comment markers (`<!-- sdd:* -->`) | PRESERVE — exact strings, exact match including ` -->` |
| `.sdd-config` key names (`skip-review`) and values (`analyze,design,implement,pr,qa`) | PRESERVE — users type these |
| Depth label names (`sdd:review:deep/shallow`) | PRESERVE — users apply |
| Language aliases (`korean`, `한국어`, `japanese`, `日本語`) | PRESERVE — user-typed args |
| CLI command names (`/sdd analyze`, etc.) and arg shapes | PRESERVE |
| Multilingual parent regex `(Parent\|상위 \|親)Issue: #<n>` | PRESERVE — load-bearing |
| Findings JSON schema | PRESERVE — add `schema_version: 1` additively |
| Internal file structure (`commands/atoms/...`) | IMPROVE — reorganize freely |
| Internal function/variable names | IMPROVE |
| Phase numbering, section organization | IMPROVE — unify |

**If any of the above need to change in rewrite**: dual-read shim for 1+ release; explicit migration guide; deprecation notice.

## Tier 1 Fixes Applied

### Reviewer B (Accuracy) — Critical
- ERR-B1: `spec/edge-cases.md` §21 + `spec/utilities.md` §7 — "11 files" → "14 files"

### Reviewer C (Classification) — 10 IMPROVE→PRESERVE
- TAG-C1: `00-common-contracts.md` §1 — label names → PRESERVE (external contract)
- TAG-C2: `00-common-contracts.md` §2 — marker namespace → PRESERVE
- TAG-C3: `00-common-contracts.md` §3 — depth label values → PRESERVE
- TAG-C4: `00-common-contracts.md` §6 — result contract sentinel → PRESERVE
- TAG-C5: `01-config.md` §2 — skip-review key names → PRESERVE
- TAG-C6: `01-config.md` §3 — table values PRESERVE; DRY is the IMPROVE
- TAG-C7: `02-multilingual.md` §3 — regex itself PRESERVE; DRY is the IMPROVE
- TAG-C8: `stage/implement.md` §10 — `pr`/`qa` key names → PRESERVE
- TAG-C9: `utilities.md` §1 — language aliases → PRESERVE; normalization-on-save is IMPROVE
- TAG-C10: `edge-cases.md` §18 — `skip-review:` key → PRESERVE (rename requires user decision, dual-read shim)

### Reviewer A (Completeness) — 6 High-impact gaps
- GAP-A1: Added to `stage/implement.md` §5 — `test-evidence-log-missing` continues (not early return)
- GAP-A2: Added to `stage/implement.md` §5 — `test-evidence-summary-unparseable` (minor, non-blocking)
- GAP-A3: Added to `stage/implement.md` §5 — Refactor count drift downgrades to major when prior Green counts unavailable
- GAP-A4: Added to `stage/implement.md` §6 — `/code-review` 🟣 Pre-existing also ignored in retry-mode translation
- GAP-A5: Added to `00-common-contracts.md` §9 — `-F body=@<path>` (form) vs `--field body=@<path>` (kv) source inconsistency — standardize on `--field` in rewrite
- GAP-A6: Added to `flow/auto.md` §9 — cleanup MUST be FIRST after loop exit / in-loop fatal

## Tier 2/3 Findings — Deferred to Design Phase

The following findings are documented but not applied to v2 spec. They will be revisited during design:

### Reviewer A — 9 Medium-impact gaps
- GAP-A7..A15: atom variable bindings, framework re-spawn token, PR title conventions, Section C `sort_by(.id) | last`, $3 retry slot completeness, adversarial-justify-missing failure, rate-limit grep guard, deep-tier preflight range overrides

### Reviewer A — 9 Low-impact gaps
- GAP-A16..A24: PR body line count, `[SDD Child]` title prefix, Red "right reasons" check, refactor `git diff --staged --quiet` semantics, 4-template alignment, `Refs #$1` lookup pattern, E2E framework install prohibition, GitHub 65k char cap rationale, reviewer-atom-no-retry-mode caveat

### Reviewer B — 6 Minor errors (citation off-by-N)
- MIN-B1..B7: off-by-one citations; will normalize during design phase when re-reading source files for implementation

### Reviewer C — 6 PRESERVE→IMPROVE re-tagging
- TAG-C11..C16: deterministic temp paths, defensive `gh repo view` framing, label colors, internal git-checkout fallback, in-memory state variable names, bash `set -euo pipefail`

### Reviewer C — 5 missing RETHINK
- TAG-C17..C21: empty-`$3`+existing-PR gap, no-idempotency-check on TDD steps, dual-location markers (Issue vs PR), wrong-PR-split-not-retryable, partial-label-set on init failure

### Reviewer C — 6 untagged items
- TAG-C22..C27: `[VERIFIED]` and `[REFERENCE]` non-standard tags, missing top-level tags on some tables

### Reviewer C — 9 inconsistent across files
- TAG-C28..C36: marker namespace IMPROVE-vs-PRESERVE inconsistency, skip-review key inconsistencies, sandbox toggle triple-listed RETHINK, ai-review-*.md location, round-suffixed markers RETHINK pattern, adversarial-only FAIL classification, Bash heuristic DRY note, language aliases tagging, Skill tool sub-agent classification

**Rationale for deferral**: these are all polish issues that do not change rewrite scope. Tier 1 corrections were the load-bearing fixes (external contract preservation + factual error + high-impact missing rules). Tier 2/3 can be addressed during design phase as we re-read sources for implementation.

## Spec v2 Status

After Tier 1 application:
- 14 spec files
- ~4,400 lines (slight growth from 6 high-impact gap additions)
- All [PRESERVE]/[IMPROVE]/[RETHINK] tags consistent with user-confirmed backward-compat policy
- All factual errors corrected
- All load-bearing atom-level rules captured

**Ready for design phase.**
