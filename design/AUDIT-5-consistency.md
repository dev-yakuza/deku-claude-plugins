# Audit 5: Cross-file Consistency + Bash/Section F Discipline

Auditor: Phase C Reviewer 5. Scope: every `*.md` under `plugins/sdd-plugin/skills/sdd/`. Reference docs: `commands/atoms/_bash_rules.md`, `commands/atoms/_review_helpers.md` Section F, `SKILL.md`, `spec/00-common-contracts.md` §4.

## A. Reference integrity

Extracted every distinct `<<SKILL_DIR>>/...` token across the tree and resolved each against the filesystem. All static references resolve. Brace-glob style refs (e.g. `rubrics/design-{completeness,quality,adversarial}.md`) appear only in "Out" / appendix summary blocks (`atoms/stage_analyze.md:545`, `atoms/stage_design.md:696`, `atoms/stage_test.md:1033`, `atoms/stage_implement/main.md:454`) — documentation listings, not Bash arguments, so no shell-expansion risk.

References to deleted v0 work files (`analyze_work.md`, `design_work.md`, `implement_work.md`, `test_work.md`) appear only inside `[PRESERVE — ... line N]` traceability annotations (e.g. `atoms/stage_analyze.md:132,138,182,190,528`; `atoms/stage_design.md:39,135,147,178,189,206,235,243,262,313,346,368,534,676–678`; `atoms/stage_test.md:153,292,315,1014`). These are historical citations pointing at original v0/spec line numbers for provenance, not live `Read` instructions — leaving them in place is intentional per the PRESERVE methodology.

**Broken references: 0**

## B. Marker consistency

Canonical markers in `spec/00-common-contracts.md` §4 lines 69–81: 11 marker families. Markers actually used across v1.0.0:

| Marker | Canonical? |
|---|---|
| `sdd:analyze:output` | Yes |
| `sdd:design:output` | Yes |
| `sdd:children:output` | Yes |
| `sdd:child-issue` | Yes |
| `sdd:implement:plan` | Yes |
| `sdd:test:output` | Yes |
| `sdd:findings:json` (+ closing) | Yes |
| `sdd:review:<stage>:<role>` (×3 stages × 3 roles) | Yes |
| `sdd:review:implement:step-<n>` | Yes |
| `sdd:review:implement:tools` | Yes |
| `sdd:review:parent` | Yes |
| `sdd:test-evidence:step-<n>` | Yes |
| `sdd:rollback` | Yes |
| `sdd:implement:step-exhaustion` | **NEW (non-canonical)** |

The only non-canonical marker is `sdd:implement:step-exhaustion`, introduced by `atoms/stage_implement/_tdd.md:506`. The atom **explicitly self-declares it non-canonical** with the parenthetical "this is informational only, not consumed by other atoms." Acceptable per Common Contracts §4 (external contract concerns only).

Posting/searching usage is consistent across stages: every `gh api ... --jq '... contains("<MARKER>")'` includes the leading `<!-- ` and trailing ` -->` per `_review_helpers.md` §C.2 prefix-collision guidance (`atoms/_review_helpers.md:144`).

**Marker inconsistencies: 0** (1 non-canonical marker, properly disclosed).

## C. Bash discipline violations

Scanned every fenced `bash` block in every v1.0.0 md file (excluding `commands/batch.md`, which contains a generated standalone shell wrapper script — not Bash tool calls — and the FORBIDDEN-pattern catalog in `atoms/_bash_rules.md`).

**Violation 1 — `commands/review.md:36–38`**
```
gh api repos/<owner>/<repo>/issues/$1/comments \
  --jq '.[] | select(.body | contains(...)) | .body' \
  | grep -oE 'sdd:(analyze:output|design:output|implement:plan|test:output)'
```
A real compound command: shell pipe `|` to `grep`, split across `\` continuations. Triggers Claude Code's compound-shell-syntax safeguard regardless of `permissions.allow`. Suggested fix: run the `gh api` call alone, observe its output in the tool result, then perform the marker extraction in narrative (no second shell call needed) — same pattern already used in `atoms/stage_implement/main.md:65–69` (`gh api ... --jq '... | .id'` only).

False positive on `atoms/stage_implement/_tdd.md:106` (`git merge-base --is-ancestor <evidence_sha> HEAD`) — `<evidence_sha>` is a documentation placeholder, not a `<` redirect.

**Bash violations: 1**

## D. Section F compliance

Surveyed every `gh issue comment`, `gh pr comment`, `gh issue create`, and `gh api ... -X PATCH` across atoms. All bodies are passed via `--body-file <path>` or `--field body=@<path>`. Temp-file paths conform to `_review_helpers.md` §F.1 (deterministic `/tmp/sdd-<marker-stub>-$1[-...]` naming). Duplicate-prevention search precedes every post except two documented exceptions: `commands/rollback.md:39` ("no duplicate prevention — every rollback is a new event") and `atoms/stage_test.md:899–905` ("No duplicate-prevention needed — each completion event is a new comment"). Both are intentional and self-documenting.

**Violation 1 — `atoms/implement_review.md:64`**
```
gh api repos/<owner>/<repo>/issues/comments/<EXISTING_ID> -X PATCH -F body=@/tmp/sdd-review-implement-<role>.md
```
Uses `-F body=@` instead of `--field body=@`. Common Contracts §9 and the `[PRESERVE — Reviewer A GAP-A5]` note in `atoms/stage_implement/_pr_final.md:645` mandate `--field`, not `-F`. Every other PATCH call in the tree correctly uses `--field`. Suggested fix: replace `-F` with `--field` on this single line.

Minor weakness (not a violation): `atoms/implement_review.md` references `_review_helpers.md` Section B (line 84) and Section D (line 46) but never explicitly cites Section F, despite posting a comment. The flow itself is compliant; the missing back-reference is just a documentation gap.

**Section F violations: 1**

## E. Helper file usage

- `_bash_rules.md` referenced from **15 files**: `SKILL.md`, `commands/{analyze,design,implement,auto,resume,test}.md`, `commands/atoms/{stage_analyze,stage_design,stage_test,bootstrap}.md`, and all four `stage_implement/*.md` files. Every command orchestrator + every stage atom + every implement topic file links the rules. The standalone reviewer atoms (`analyze_review.md`, `design_review.md`, `implement_review.md`, `test_review.md`) do **not** link `_bash_rules.md` directly — they inherit it transitively via the orchestrator that spawns them and via `_review_helpers.md` Section D's restated rules. Acceptable but slightly weak coverage.
- `_multilingual.md` / `02-multilingual` referenced from **11 files** including `commands/auto.md`, `commands/batch.md`, and `atoms/stage_design.md` (children-creation path), `atoms/stage_analyze.md`, `atoms/stage_test.md`. Matches expected scope.
- `_review_helpers.md` / `Section F` referenced from **15 files** — every reviewer + every work atom that posts comments. Only outlier: `atoms/implement_review.md` cites Sections B + D but omits explicit Section F citation (see D above).

## F. Rubric file references

All 14 rubrics under `atoms/rubrics/` are referenced from at least one consumer:

- `analyze-{completeness,quality,adversarial}.md` → `atoms/stage_analyze.md`, `atoms/analyze_review.md`.
- `design-{completeness,quality,adversarial}.md` → `atoms/stage_design.md`, `atoms/design_review.md`.
- `implement-{completeness,quality,adversarial}.md` → `atoms/stage_implement/_pr_final.md`, `atoms/implement_review.md`, `atoms/stage_implement/main.md` (appendix).
- `implement-step.md` → `atoms/stage_implement/_tdd.md:409`, `atoms/stage_implement/main.md` (appendix).
- `test-{completeness,quality,adversarial}.md` → `atoms/stage_test.md`, `atoms/test_review.md`.
- `parent-integration.md` → `atoms/stage_test.md:531` (single consumer — by design, parent integration is only reached from the parent path inside `stage_test`).

**Orphan rubrics: 0**

## G. stage_implement split coherence

`atoms/stage_implement/main.md` reads its topic files in the right order:

- Phase 0 (parent on `sdd:done`) → `Read _phase7.md` (`main.md:102`).
- Phase 3 (TDD pipeline) → `Read _tdd.md` (`main.md:292–296`).
- Phase 4 + 5 + 5.5 (PR Final) → `Read _pr_final.md` (`main.md:317–321`).

Pre-declared on `main.md:10–12` as part of the file-map summary. Topic files do NOT Read each other — `grep -n "Read.*_tdd.md\|Read.*_pr_final.md\|Read.*_phase7.md"` returns nothing for the three topic files. Single-Read-from-main invariant is preserved.

Single-sub-agent invariant explicitly re-stated at `main.md:426`: "This file + the three topic files (`_tdd.md`, `_pr_final.md`, `_phase7.md`) all execute inside ONE Agent-spawned sub-agent context."

## Critical issues

1. **`commands/review.md:36–38` pipes `gh api ... | grep`** across line continuations. This breaks unattended runs (`/sdd auto`, `/sdd batch`) on the very first time `/sdd review` is invoked inside an automated flow — the compound-shell-syntax safeguard cannot be auto-approved. Fix is mechanical: drop the `| grep` step and let the orchestrator scan the JSON body in narrative.
2. **`atoms/implement_review.md:64` uses `-F body=@` instead of `--field body=@`** — drifts from the `--field` mandate in Common Contracts §9. Cosmetic in `gh` runtime (both flags work), but the tree-wide consistency rule cited in `_pr_final.md:645` (`[PRESERVE — Reviewer A GAP-A5]`) is broken.

## Summary

- References broken: **0**
- Bash violations: **1** (`review.md:36–38`)
- Section F violations: **1** (`implement_review.md:64` uses `-F` instead of `--field`)
- Marker inconsistencies: **0** (1 non-canonical marker, properly disclosed)
- Orphan rubrics: **0**
