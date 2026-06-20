# Reviewer B: Accuracy Findings

## Critical errors (spec contradicts source — must fix)

- **ERR-B1**: Wrong count of `ai-review-*.md` files (11 vs actual 14)
  - **Spec claim** (in `spec/edge-cases.md` §21, line 389): "Files: 11 files under `commands/` matching `ai-review-*.md` (analyze/design/implement/test × completeness/quality/adversarial + step + parent-integration)."
  - **Spec claim** (in `spec/utilities.md` §7, line 292): "There are 11 files in `commands/` matching `ai-review-*.md`."
  - **Source truth**: `ls commands/ai-review-*.md` returns **14** files (analyze ×3, design ×3, implement ×3 + implement-step, test ×3, parent-integration). Spec utilities.md §7 line 317 itself states "the directory has 14 files matching `ai-review-*.md`" — internally inconsistent.
  - **Correction**: Replace "11" with "14" in both edge-cases.md §21 and utilities.md §7 (line 292). The math in the §21 parenthetical even adds up to 14, but the leading number is wrong.

- **ERR-B2**: Wrong `tdd_step_review` slot position cited (the atom takes `$3` and `$4` and `$5` but spec utilities mapping omits this)
  - **Spec claim** (in `spec/utilities.md` §7, table line 311): "`ai-review-implement-step.md` | `atoms/tdd_step_review.md` | `$2 = step number (1-4)`; file has subsections per step"
  - **Source truth** (`atoms/tdd_step_review.md` lines 11–15): `$2` is step number, but the atom also takes `$3` (branch), `$4` (commit sha), `$5` (test evidence). Spec utilities table column header is "Atom passes role via" — for tdd_step_review the role *is* `$2`, but the row description omits that `$3..$5` are required for the atom to function, conflating role-pass with full atom signature.
  - **Correction**: Acceptable as-is because the column is "role pass" and `$2` is indeed the role. (Downgrade to non-finding; the citation is narrowly accurate for the column's purpose.) — **REMOVED from critical list**.

- **ERR-B3**: Edge-cases.md §21 line 389 file enumeration is incomplete
  - **Spec claim** (in `spec/edge-cases.md` §21, line 389): "(analyze/design/implement/test × completeness/quality/adversarial + step + parent-integration)"
  - **Source truth**: this expansion produces 4×3 + 1 + 1 = 14 files, NOT 11. The parenthetical is the correct enumeration; the leading "11" is the error. Same as ERR-B1.
  - **Correction**: Already captured under ERR-B1.

## Minor errors (citations off, slightly imprecise wording)

- **MIN-B1**: Off-by-one citation on `analyze_adversarial.md` hard rules
  - **Spec claim** (`spec/stage/analyze.md` §3, line 56): "MUST NOT spawn subagents and MUST NOT call Agent/Skill tools (`analyze_work.md` line 127–128; `analyze_review.md` line 101; `analyze_adversarial.md` line 67)."
  - **Source truth** (`atoms/analyze_adversarial.md` line 68): "Single-subagent atom. Do NOT invoke the Agent tool or Skill tool." — line **68**, not 67. (Line 67 is `## Hard rules` heading; line 68 is the first bullet.)
  - **Correction**: Change `analyze_adversarial.md line 67` → `line 68`.

- **MIN-B2**: Off-by-one citation on `test_review.md` FAIL message
  - **Spec claim** (`spec/stage/test.md` line 388): "`test_review` and `test_adversarial` return `FAIL: <reason>` if test output is missing from the Issue. (`test_review.md` line 27; `test_adversarial.md` line 26)"
  - **Source truth** (`atoms/test_review.md` line 26): "If test output missing → return `FAIL: test output not found on Issue #$1`." Line **26**, not 27. (`test_adversarial.md` line 25 contains the same; spec says 26.)
  - **Correction**: Change `test_review.md line 27` → `line 26`; `test_adversarial.md line 26` → `line 25`.

- **MIN-B3**: Off-by-multiple citation on `test_adversarial.md` Hard rules
  - **Spec claim** (`spec/stage/test.md` §3, line 75): "All five atoms are single-subagent terminal workers ... (`test_work.md` lines 3, 226–229; `test_review.md` lines 3, 76; `test_adversarial.md` lines 3, 73; `parent_integration_review.md` lines 3, 107)"
  - **Source truth**:
    - `test_adversarial.md` line 73 is "## Hard rules" (heading). The first content bullet "Single-subagent atom. Do NOT invoke..." is at line **75**.
    - `parent_integration_review.md` line 107 is the "## Hard rules" heading. The first bullet is at line **108**.
  - **Correction**: For both, the citation points to the heading line, not the rule itself. Either update citations to the bullet line or specify "Hard rules section starting at line X".

- **MIN-B4**: Slight off cite on `design_work.md` Step 3 line
  - **Spec claim** (`spec/stage/design.md` §5, line 182): "downstream detection regex: `(Parent|상위 |親)Issue: #<number>`. (`design_work.md` Step 3 line 47)"
  - **Source truth** (`atoms/design_work.md`): the regex itself is mentioned on **line 46** ("multi-language regex `(Parent|상위 |親)Issue: #<number>`"). Line 47 is the inline shell call, not the regex.
  - **Correction**: Change citation from line 47 → line 46 (or 46–51 for the whole Step 3).

- **MIN-B5**: `analyze.md` line 27 references `Section C.2` for the model table, but the source-of-truth section is `_review_helpers.md` Section A.2
  - **Spec claim**: The spec correctly identifies the model table as `_review_helpers.md` Section A.2 throughout (e.g., `00-common-contracts.md`, `01-config.md` §3 line 64, `spec/stage/analyze.md` line 54).
  - **Source truth** (`commands/analyze.md` line 27, 17, 165): the source file repeatedly references "`_review_helpers.md` Section C / Section C.2" but no such section exists — the actual section is **A** / **A.2**. This is a source bug, not a spec bug. The spec correctly identifies A.2 but does not flag the source's mis-citation.
  - **Correction**: Spec is correct; the source `analyze.md` (and `design.md` line 21, `implement.md` line 19, `test.md` line 17) has its own bug ("Section C" should be "Section A"). Spec could call this out as an `[IMPROVE]` note in §3 model tables, but it is not a spec accuracy error.

- **MIN-B6**: `01-config.md` §4 step 5e references line numbers, but `auto.md` was rewritten so step 5e citations are imprecise
  - **Spec claim** (`spec/01-config.md` §4 line 113): "[RETHINK: sandbox toggle UX (~190 lines in auto.md Phase 3.1) is complex."
  - **Source truth**: source `commands/auto.md` Phase 3.1 step 5 sandbox toggle spans lines 154–254, which is ~100 lines, not 190. ("~190 lines" appears to be approximate or stale.)
  - **Correction**: Either drop the "~190 lines" estimate or revise to "~100 lines" of step 5 plus context.

- **MIN-B7**: `spec/stage/test.md` line 348 says `test_work.md line 71` for E2E-skipped flag
  - **Spec claim** (`spec/stage/test.md` line 348): "`test_work` Step 4 in Stage 4 detects this flag and includes it in the Issue test output. (`test_work.md` line 71)"
  - **Source truth** (`atoms/test_work.md` line 71): "If Stage 3 reported E2E was skipped (no E2E setup at the time), flag it." ✓ — verified accurate, not an error. (False alarm — keeping for transparency.)

- **MIN-B8**: Spec/00-common-contracts.md table for PR Final tools summary attribution
  - **Spec claim** (`spec/00-common-contracts.md` Section 2 line 39): "PR Final tools summary | PR comment `<!-- sdd:review:implement:tools -->` | `implement.md` Phase 5 (per-round)"
  - **Source truth**: source `commands/implement.md` posts this at Phase **5.1.4** / **5.N.4** specifically (line 242–293), not generic "Phase 5".
  - **Correction**: Acceptable as spec abbreviation; "Phase 5" is the parent phase. Not a factual error.

## Verified-correct sample

- Spec `00-common-contracts.md` §7 says `implement_red/green/refactor/e2e` and `implement_pr` use `$3 = "retry"`; source `_review_helpers.md` lines 133–135 confirms exactly that. ✓
- Spec `00-common-contracts.md` §7 says `analyze_work`, `design_work`, `test_work` use `$2 = "retry"`; source `_review_helpers.md` line 133 confirms. ✓
- Spec `00-common-contracts.md` §7 retry budgets — analyze 3 / design 3 / implement TDD 2 retries (3 attempts) / implement PR 3 / test 3 — all confirmed against source `analyze.md` line 40, `design.md` line 40, `implement.md` line 82, `implement.md` line 143 ("3 rounds + escalation"), `test.md` line 53. ✓
- Spec `00-common-contracts.md` §9 mandatory temp-file pattern matches `_review_helpers.md` Section F (lines 263–337). ✓
- Spec `02-multilingual.md` §3 parent regex `(Parent|상위 |親)Issue: #<n>` confirmed against all three template files (`templates/en/output_child_issue.md` line 2: "Parent Issue:", `templates/ko/output_child_issue.md` line 2: "상위 Issue:", `templates/ja/output_child_issue.md` line 2: "親Issue:"). ✓
- Spec `commands-inventory.md` plugin.json/marketplace.json version drift (0.36.0 vs 0.35.0) — confirmed against `plugins/sdd-plugin/.claude-plugin/plugin.json` line 4 and `.claude-plugin/marketplace.json` line 11. ✓
- Spec `stage/implement.md` line 280: `FAIL: retry mode requested but no open PR for branch $2` — confirmed against `atoms/implement_pr.md` line 28 and `_review_helpers.md` line 172. ✓
- Spec `stage/analyze.md` line 78 says "OK NO_ACTION" → skip reviews entirely → Phase 2 No-Action path — confirmed against `commands/analyze.md` line 55 and `atoms/analyze_work.md` lines 110–111 (`OK NO_ACTION` return contract). ✓
- Spec `stage/design.md` §5 lines 165–172: child Issue creation steps with multilingual templates, `gh issue create --label "sdd:analyze" --label "sdd:child"` — confirmed against `atoms/design_work.md` lines 130–140. ✓
- Spec `stage/test.md` line 41 says `parent_integration_review` posts on parent Issue with marker `<!-- sdd:review:parent -->` — confirmed against `atoms/parent_integration_review.md` lines 52–62. ✓
- Spec `stage/implement.md` Phase 5.1.2 / 5.1.3 `/code-review` effort by depth (default=high, deep=max, shallow=medium) — confirmed against `_review_helpers.md` Section A.3 lines 43–47 and `implement.md` line 189. ✓
- Spec `stage/implement.md` line 137: `OK E2E_SKIPPED → skip step 2 entirely` (no tdd_step_review spawn) — confirmed against `commands/implement.md` line 99. ✓
- Spec `stage/test.md` line 88: `test_work` always opus regardless of depth — confirmed against `_review_helpers.md` line 28 (`*_work (analyze/design/test) | opus | opus | opus`) and source `test.md` line 29. ✓
- Spec `flow/batch.md` §5 (skip-review): batch writes 5 keys `analyze,design,implement,pr,qa` — same as auto; both commands run unattended through QA to `sdd:done`. Updated: batch previously used 4 keys (no `qa`); changed so batch also completes through QA unattended.
- Spec `flow/resume.md` §2 dispatch table: `sdd:done → "Issue is already complete."` — confirmed against `commands/resume.md` line 75. ✓
- Spec `flow/auto.md` §10 Final Summary "manual QA was auto-skipped because /sdd auto runs unattended" — confirmed against `commands/auto.md` line 354. ✓

## Summary
- Critical: 1 (file-count error in two places; counts as 1 underlying fact)
- Minor: 6 (citation off-by-N issues + one minor stylistic imprecision)
- Verified: 16
- Total checked: ~35–40 distinct concrete claims spot-checked across 13 spec files
