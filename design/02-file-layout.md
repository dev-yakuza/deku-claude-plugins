# 02 — File Layout

Target directory structure for the rewritten plugin. Internal reorganization only — no external contract changes.

---

## 1. Target structure

```
plugins/sdd-plugin/
├ .claude-plugin/
│  └ plugin.json                          # PRESERVE: external metadata
├ skills/
│  └ sdd/
│     ├ SKILL.md                          # IMPROVE: trimmed to routing + cross-cutting links
│     ├ commands/                         # User-invocable commands (orchestrators)
│     │  ├ analyze.md                     # PRESERVE name; body = thin wrapper that spawns stage_analyze
│     │  ├ design.md                      # same pattern
│     │  ├ implement.md                   # same pattern
│     │  ├ test.md                        # same pattern
│     │  ├ resume.md                      # IMPROVE: thin dispatcher; delegates to bootstrap sub-agent
│     │  ├ auto.md                        # IMPROVE: FSM body; spawns stages
│     │  ├ batch.md                       # IMPROVE: generates shell script (largely unchanged)
│     │  ├ init.md                        # NEW: transactional rollback (R10)
│     │  ├ config.md                      # unchanged behavior
│     │  ├ status.md                      # IMPROVE: unify single/parent output schema
│     │  ├ rollback.md                    # unchanged
│     │  ├ review.md                      # IMPROVE: optionally add adversarial via flag (TAG-C-deferred)
│     │  └ help.md                        # IMPROVE: registry-generated
│     ├ atoms/                            # Sub-agent bodies
│     │  ├ stage_analyze.md               # NEW: stage sub-agent (inlines work + reviews + escalation)
│     │  ├ stage_design.md                # NEW
│     │  ├ stage_implement.md             # NEW (largest)
│     │  ├ stage_test.md                  # NEW
│     │  ├ bootstrap.md                   # NEW: replaces resume.md inline logic
│     │  ├ _preflight.md                  # PRESERVE: tier table + items (used by stage atoms)
│     │  ├ _review_helpers.md             # PRESERVE: Section A-F (rules, retry, comment-posting)
│     │  ├ _test_evidence.md              # PRESERVE: raw test output handling
│     │  └ rubrics/                       # NEW location (R7): role-specific review criteria
│     │     ├ analyze-completeness.md
│     │     ├ analyze-quality.md
│     │     ├ analyze-adversarial.md
│     │     ├ design-completeness.md
│     │     ├ design-quality.md
│     │     ├ design-adversarial.md
│     │     ├ implement-completeness.md
│     │     ├ implement-quality.md
│     │     ├ implement-adversarial.md
│     │     ├ implement-step.md           # used by TDD step review (inside stage_implement)
│     │     ├ test-completeness.md
│     │     ├ test-quality.md
│     │     ├ test-adversarial.md
│     │     └ parent-integration.md
│     └ templates/                        # PRESERVE
│        ├ en/                            # PRESERVE per-language structure
│        │  ├ issue_*.yml
│        │  └ output_*.md
│        ├ ko/
│        └ ja/
└ README.md                               # IMPROVE
```

---

## 2. Mapping from current to new

| Current path | Target path | Change |
|---|---|---|
| `commands/analyze.md` | `commands/analyze.md` + `atoms/stage_analyze.md` | Split: command file becomes thin wrapper; stage body in atoms/ |
| `commands/design.md` | `commands/design.md` + `atoms/stage_design.md` | same |
| `commands/implement.md` | `commands/implement.md` + `atoms/stage_implement.md` | same |
| `commands/test.md` | `commands/test.md` + `atoms/stage_test.md` | same |
| `commands/resume.md` | `commands/resume.md` + `atoms/bootstrap.md` | dispatcher logic moves to bootstrap sub-agent |
| `commands/auto.md` | `commands/auto.md` | FSM body; remains in main session |
| `commands/batch.md` | `commands/batch.md` | mostly unchanged (still generates `claude -p` script) |
| `commands/atoms/analyze_work.md` | (inlined into `stage_analyze.md`) | removed as standalone atom |
| `commands/atoms/analyze_review.md` | (inlined into `stage_analyze.md`) | removed |
| `commands/atoms/analyze_adversarial.md` | (inlined into `stage_analyze.md`) | removed |
| `commands/atoms/design_*.md` | (inlined into `stage_design.md`) | removed |
| `commands/atoms/implement_plan.md` | (inlined into `stage_implement.md`) | removed |
| `commands/atoms/implement_red.md` ... | (inlined into `stage_implement.md`) | removed |
| `commands/atoms/implement_pr.md` | (inlined into `stage_implement.md`) | removed |
| `commands/atoms/implement_review.md` ... | (inlined into `stage_implement.md`) | removed |
| `commands/atoms/tdd_step_review.md` | (inlined into `stage_implement.md`) | removed |
| `commands/atoms/test_*.md` | (inlined into `stage_test.md`) | removed |
| `commands/atoms/parent_integration_review.md` | (inlined into `stage_test.md`) | removed |
| `commands/atoms/_preflight.md` | unchanged path | PRESERVE — still referenced by stage atoms |
| `commands/atoms/_review_helpers.md` | unchanged path | PRESERVE — Sections A-F still canonical |
| `commands/atoms/_test_evidence.md` | unchanged path | PRESERVE |
| `commands/ai-review-*.md` (14 files) | `atoms/rubrics/<stage>-<role>.md` | R7 decision: move + rename |

---

## 3. File count comparison

| Group | Current | Target |
|---|---|---|
| `commands/*.md` | 27 files | 13 files |
| `commands/atoms/*.md` | 22 files | 8 files (4 stage + bootstrap + 3 helpers) |
| `commands/atoms/rubrics/*.md` | 0 | 14 files (moved + renamed from current ai-review-*) |
| Templates | 24 files | 24 files (unchanged) |
| **Total** | **73 files** | **59 files** |

Net reduction: 14 files. The 22 → 8 atom consolidation is the biggest restructure.

---

## 4. SKILL.md slimming

Current `SKILL.md` is 164 lines containing all cross-cutting rules (Bash heuristics, comment posting, multilingual regex, etc.). In rewrite, SKILL.md becomes:
- Routing (which command file to read for `/sdd $0`)
- 1-paragraph references to canonical locations:
  - Bash rules → `commands/atoms/_review_helpers.md` (or new `_bash_rules.md`)
  - Comment posting → `_review_helpers.md` Section F
  - Multilingual regex → `_review_helpers.md` (or new `_multilingual.md`)
  - JSON schema → `_review_helpers.md` Section B

[IMPROVE]: today every orchestrator includes a copy of the Bash rules paragraph. New design: one canonical file, each stage references via Section link.

---

## 5. New helper files (optional, suggested)

- `_bash_rules.md` (~50 lines) — extracted from current SKILL.md §"Bash Command Execution Rules"
- `_multilingual.md` (~30 lines) — extracted from current SKILL.md §"Multi-language parent reference" + template paths

These reduce SKILL.md to ~50 lines (routing + entry validation only).

[IMPROVE — DRY]: addresses spec/00-common-contracts.md §8 and §9 duplication.

---

## 6. plugin.json + marketplace.json

[PRESERVE]: schemas unchanged. Version bump for the rewrite (e.g. v1.0.0 to signal major restructure).

⚠ Version sync bug from spec/edge-cases.md §20 must be fixed before v1.0.0. Both files must reach v1.0.0 at the same commit.

---

## 7. Tests / fixtures (proposed for Phase C)

Not in current source. Proposed for the rewrite:

```
plugins/sdd-plugin/
└ tests/
   ├ fixtures/                            # Sample Issue states for replay
   │  ├ issue-analyze-empty.json
   │  ├ issue-after-analyze.json
   │  ├ issue-after-design-single.json
   │  ├ issue-after-design-children.json
   │  └ ...
   ├ contract/                            # Return value contract tests
   │  ├ test_stage_returns.md             # Validate >>> RESULT <<< format per stage
   │  └ test_bootstrap.md
   └ integration/                         # Full-flow scenarios
      └ test_analyze_to_done.md
```

[NEW]: not in current code. Suggested for Phase C to enable replay testing. Decision deferred to Phase C.

---

## 8. .github / config files (no change)

`.github/.sdd-config`, `.github/.sdd-lang`, `.github/ISSUE_TEMPLATE/*` — all PRESERVE.

---

## Cross-references

- Architecture: `00-architecture.md`
- Contract: `01-sub-agent-contract.md`
- Stage internals: `stage-designs/*.md`
- Migration: `06-migration-plan.md`
