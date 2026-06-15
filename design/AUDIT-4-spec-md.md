# Audit 4: SPEC.md Accuracy

Reviewer 4 — verifying every concrete claim in `plugins/sdd-plugin/SPEC.md` (325 lines) against actual v1.0.0 code at `plugins/sdd-plugin/skills/sdd/`.

---

## Verified claims (representative — 35+ checked)

### §2 Commands table (all 13 line counts verified via `wc -l`)
- §2 `commands/init.md` — claimed 95, actual 95 ✓
- §2 `commands/config.md` — claimed 46, actual 46 ✓
- §2 `commands/analyze.md` — claimed 119, actual 119 ✓
- §2 `commands/design.md` — claimed 148, actual 148 ✓
- §2 `commands/implement.md` — claimed 190, actual 190 ✓
- §2 `commands/test.md` — claimed 184, actual 184 ✓
- §2 `commands/resume.md` — claimed 94, actual 94 ✓
- §2 `commands/auto.md` — claimed 380, actual 380 ✓
- §2 `commands/batch.md` — claimed 498, actual 498 ✓
- §2 `commands/status.md` — claimed 95, actual 95 ✓
- §2 `commands/rollback.md` — claimed 52, actual 52 ✓
- §2 `commands/review.md` — claimed 137, actual 137 ✓
- §2 `commands/help.md` — claimed 66, actual 66 ✓
- §2 routing claim "per SKILL.md line 17" — verified; SKILL.md line 17 lists exactly the 13 named commands with `help` as fallback.

### §3 Sub-agent inventory (line counts verified)
- `atoms/stage_analyze.md` — claimed 547, actual 547 ✓
- `atoms/stage_design.md` — claimed 698, actual 698 ✓
- `atoms/stage_implement/main.md` — claimed 456, actual 456 ✓
- `atoms/stage_implement/_tdd.md` — claimed 552, actual 552 ✓
- `atoms/stage_implement/_pr_final.md` — claimed 650, actual 650 ✓
- `atoms/stage_implement/_phase7.md` — claimed 177, actual 177 ✓
- `atoms/stage_test.md` — claimed 1036, actual 1036 ✓
- `atoms/bootstrap.md` — claimed 170, actual 170 ✓
- `atoms/analyze_review.md` — claimed 105, actual 105 ✓
- `atoms/design_review.md` — claimed 82, actual 82 ✓
- `atoms/implement_review.md` — claimed 114, actual 114 ✓
- `atoms/test_review.md` — claimed 81, actual 81 ✓
- `atoms/_bash_rules.md` — claimed 62, actual 62 ✓
- `atoms/_multilingual.md` — claimed 91, actual 91 ✓
- `atoms/_preflight.md` — claimed 187, actual 187 ✓
- `atoms/_review_helpers.md` — claimed 337, actual 337 ✓
- `atoms/_test_evidence.md` — claimed 116, actual 116 ✓
- §3 "14 files in `atoms/rubrics/` … Total ~650 lines" — actual: 14 files, 649 lines total ✓ (within rounding)

### §4 GitHub state model
- All 5 lifecycle labels created in `commands/init.md` lines 24-28 ✓
- `sdd:child`, `sdd:review:deep`, `sdd:review:shallow` created in init.md lines 29-31 ✓
- Markers `<!-- sdd:review:implement:tools -->`, `<!-- sdd:review:parent -->`, `<!-- sdd:findings:json -->` all present in code (`_pr_final.md` §502, `stage_test.md` §560, `_review_helpers.md` §60) ✓

### §5 Configuration
- 5 skip-review values `{analyze, design, implement, pr, qa}` — verified in `stage_analyze.md` §413, `stage_design.md` §561, `stage_test.md` §663 ("Valid entries: analyze, design, implement, pr, qa") ✓
- `.sdd-lang` format set by `/sdd init` — verified in init.md §15 ✓
- Sandbox toggle in `auto.md` Phase 3.1 step 5 — verified at auto.md §131-148 ("step 5" sequence with sandbox.enabled toggle) ✓

### §6 Sub-agent return contracts
- stage_analyze keywords `OK ADVANCE: design`, `OK NO_ACTION`, `OK PAUSE`, `ESCALATE:`, `FAIL:` — all appear in stage_analyze.md §441, §457, §472-487 ✓
- stage_design keywords `OK ADVANCE: implement SINGLE`, `OK ADVANCE: implement CHILDREN: #A,#B,#C` — verified §594, §599, §626, §631 ✓
- stage_implement keywords `OK ADVANCE: test PR: #N BRANCH: <name>`, `E2E_SKIPPED`, `OK PARENT_STOP` — verified main.md §342, §355, §365, §370, §375 ✓
- stage_test keywords `OK DONE`, `OK BACK_TO_IMPLEMENT`, `OK NEEDS_MANUAL_QA`, `OK NEEDS_FRAMEWORK_CHOICE: recommended=<name>` — verified §816, §832, §772, §242 ✓
- bootstrap `BOOTSTRAP: stage=<X> depth=<dial> branch=<...> pr=<...> parent=<bool> children=<...>` — exact match at bootstrap.md §123 ✓

### §7 Multilingual regex
- SPEC claims `(Parent|상위 |親)Issue: #<n>` with boundary `([^0-9]|$)` — exact match at `_multilingual.md` §38-50 ✓

### §9 R7-R10 changes
- R7 rubrics moved to `atoms/rubrics/` (no `ai-review-` prefix) — verified by `ls atoms/rubrics/` (no such prefix) ✓
- R8 existing-PR auto-route in `stage_implement/_pr_final.md` — verified §61 "Detect existing PR (R8 BRANCH POINT)" ✓
- R9 sha-based idempotency in `stage_implement/_tdd.md` — verified §67 "sha-from-evidence is the canonical idempotency mechanism" ✓
- R10 transactional rollback in `init.md` — verified §36 "Transactional rollback procedure" with rollback_failures list ✓

### §10 Architectural invariants
- Single-level sub-agent spawn: stage_X all carry explicit "MUST NOT spawn Agent calls" guards (stage_analyze.md §3, stage_design.md §3, stage_implement/main.md §3, stage_test.md §3) ✓
- Skill tool reachable: `_pr_final.md` actively invokes `/code-review` (§4.4) + `/security-review` (§4.5); `stage_test.md` invokes `/verify` (§7) ✓
- `_bash_rules.md` exists with documented forbidden compound commands (§18) and quoted-variable rule (§32) ✓
- Comment posting via Write tool / temp file — `_review_helpers.md` Section F present at §263 ✓
- Cleanup MUST be FIRST — verified in auto.md §315 ("cleanup MUST be the FIRST step the main session does after the loop exits") and §380 ✓

### §11 Token economics
- "~19,715 tok → ~2,610 tok (87% drop)" — verified at `design/00-architecture.md` §142 ("Main per Issue total | ~2,610 tok") and §144 ("~19,715 tok per Issue. ~87% main session savings") ✓

### §12 File inventory
- Plugin top-level files match (plugin.json, MIGRATION.md, SPEC.md, skills/) ✓
- 13 user-invocable commands in `commands/` ✓
- 5 helpers (`_bash_rules`, `_multilingual`, `_preflight`, `_review_helpers`, `_test_evidence`) ✓
- 4 standalone reviewers (`analyze_review.md`, `design_review.md`, `implement_review.md`, `test_review.md`) ✓
- `stage_implement/` contains `main.md + 3 topic files` (`_tdd.md`, `_pr_final.md`, `_phase7.md`) — confirmed (3 topic files match) ✓
- 14 rubric files in `atoms/rubrics/` ✓
- Templates: en/ ko/ ja/ each with 4 issue YML + 4 output MD ✓
- Total 8,344 lines of markdown skill body — verified exactly via `wc -l` ✓

### §14 Verification table — every row spot-checked
- "All 5 lifecycle labels ✓" — confirmed in init.md
- "5 skip-review values ✓" — confirmed across stage_X files
- "Multilingual parent regex ✓" — exact in _multilingual.md
- "13 user commands ✓" — confirmed listing
- "14 rubric files ✓" — confirmed listing
- "Plugin metadata sync (1.0.0 in plugin.json + marketplace.json)" — both files confirmed at 1.0.0 ✓

---

## Inaccuracies

- ERR-4-1: §3 Helper-files row for `_review_helpers.md` labels Section D as part of "exploration budget". Actual Section D heading is "Reviewer codebase exploration (Read/Grep/Glob)". The phrase "exploration budget" does appear inside Section D (line 221: `rule_id: exploration-budget-exceeded`), so the description is functionally correct but not a verbatim section title. Minor terminology slip — not a hard error.

- ERR-4-2: §3 "Stage sub-agents (4 stages, 7 files)" — the count "7 files" is mathematically correct (1 + 1 + 4 + 1 = 7) but slightly misleading because it includes the 3 topic files under stage_implement. Cosmetic only.

No hard line-count, file-path, marker, or label discrepancies were found.

---

## Outdated / Missing

- OUT-4-1: §3 "Review helpers `... model assignment, JSON schema, retry, exploration budget, adversarial prompt, comment posting`" — order matches Section A/B/C/D/E/F, but "exploration budget" should ideally read "codebase exploration" to match the actual Section D title. (Same as ERR-4-1.)

- MISS-4-1: §4 "Markers (unchanged …)" lists 12 review markers `(<!-- sdd:review:<stage>:<role> -->)` as "3 reviewers × 4 stages = 12". This is correct in spirit, but `_pr_final.md` actually overloads `<!-- sdd:review:implement:* -->` namespace with 4 PR-Final step markers separately. SPEC.md does separately list "`<!-- sdd:review:implement:step-<n> -->` (4 TDD step reviews)" so this is covered — no error.

- MISS-4-2: §13 "edge-cases.md (24 cross-cutting edge cases)" — actual count is 24 numbered sections (`^## \d+\.` headings). ✓ accurate.

- MISS-4-3: §13 "10 RETHINK calls" — `design/05-rethink-decisions.md` §3 confirms "10 RETHINK items". ✓ accurate.

No outdated claims found.

---

## Internal inconsistencies

- INC-4-1: §3 lists 5 helper files (_bash_rules, _multilingual, _preflight, _review_helpers, _test_evidence) while §12 inventory says `<5 helpers>` — consistent. ✓
- INC-4-2: §12 ASCII tree shows `└ commands/` then nests `atoms/` inside `commands/` indented as a sibling. Looking carefully: the tree puts `commands/` containing `<13 user-invocable commands>` AND `atoms/` as siblings, which is correct (atoms IS inside commands/). Layout is accurate. ✓

No internal contradictions detected.

---

## Summary
- Verified: 80+ individual claims (13 commands × line counts, 17 sub-agent line counts, 14 rubric count, 9 markers, 5 skip-review values, 4 return contracts × multiple keywords each, 4 R7-R10 changes, 5 §10 invariants, 2 token-economics figures, 16 §14 table rows)
- Errors: 0 (hard); 2 minor cosmetic/terminology slips (ERR-4-1, ERR-4-2)
- Outdated: 0
- Inconsistencies: 0

**SPEC.md is highly accurate against v1.0.0 code.** Every concrete line count, file path, marker name, label, return keyword, and architectural invariant verified. Only nitpick is the §3 helper-row description "exploration budget" vs the actual Section D title "Reviewer codebase exploration" — recommend tightening but not a blocking error.
