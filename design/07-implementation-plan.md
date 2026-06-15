# 07 — Implementation Plan (Phase C)

Ordered milestones for implementing the Phase B design. Each milestone is a self-contained chunk that produces a verifiable state.

---

## 1. Pre-implementation (must do before any code)

### M0: Version sync fix
- Bump `plugin.json` and `marketplace.json` both to a sync release (e.g. v0.37.0).
- Add CI / pre-commit check enforcing version sync.
- Branch `legacy/0.x` from current main.
- Tag `v0.36.x-final`.

**Verification**: `grep version plugin.json marketplace.json` shows same version.

**Estimated effort**: 1 commit, ~30 min.

---

## 2. Phase C — Implementation milestones

Each milestone produces a coherent, testable state. Tag after each milestone for incremental rollback.

### M1: Rubric relocation (R7)
- Create `plugins/sdd-plugin/skills/sdd/commands/atoms/rubrics/`.
- Copy 14 files from `commands/ai-review-<stage>-<role>.md` → `commands/atoms/rubrics/<stage>-<role>.md`.
- Update reviewer atoms (`atoms/*_review.md`, `*_adversarial.md`, `tdd_step_review.md`, `parent_integration_review.md`) to read from new paths.
- Delete `commands/ai-review-*.md` (14 files).
- Audit: `grep -r "ai-review-"` returns empty.

**Why first**: smallest, lowest-risk change. Validates the migration discipline.

**Verification**: existing test (run `/sdd analyze <N>` on a sample Issue) produces identical results to pre-M1.

**Estimated effort**: ~1-2 hours.

---

### M2: Helper file extraction
- Extract Bash rules from `SKILL.md` into `commands/atoms/_bash_rules.md` (~50 lines).
- Extract multilingual section into `commands/atoms/_multilingual.md` (~30 lines).
- Update `SKILL.md` to reference new helpers instead of inlining (~50 lines remaining).
- Update orchestrators + atoms that paraphrase Bash rules to reference `_bash_rules.md`.

**Why now**: clean baseline before stage sub-agent extraction.

**Verification**: `grep` shows references resolve; no behavioral change.

**Estimated effort**: ~2-3 hours.

---

### M3: Bootstrap sub-agent
- Create `commands/atoms/bootstrap.md` per design/01-sub-agent-contract.md §7.
- Behavior: gh issue view + gh api comments + gh pr list → returns initial state.
- Update `commands/resume.md` to spawn bootstrap (instead of inline dispatch).

**Why now**: validates sub-agent contract pattern with a minimal atom before the larger stage_X work.

**Verification**: `/sdd resume <N>` on a known Issue returns identical dispatch decision.

**Estimated effort**: ~2-3 hours.

---

### M4: stage_analyze (smallest stage)
- Create `commands/atoms/stage_analyze.md` per design/stage-designs/analyze.md.
- Inline: analyze_work + 3 reviewer atoms + escalation logic.
- Update `commands/analyze.md` to spawn stage_analyze (replacing current orchestrator body).

**Why now**: smallest stage = lowest risk. Validates the stage-sub-agent pattern.

**Verification**: 
- `/sdd analyze <N>` on a fresh Issue produces the same markers, same labels, same advance behavior as 0.x.
- Test no-action path on a fixture Issue.
- Test retry path by manually editing the analyze output and forcing a re-review (would need a test harness; otherwise manual).

**Estimated effort**: ~1-2 days. The atom inlining is mechanical; the wiring + main-session FSM thinning is novel.

---

### M5: stage_design
- Create `commands/atoms/stage_design.md` per design/stage-designs/design.md.
- Inline: design_work + 3 reviewers + child Issue creation + idempotency guard.
- Update `commands/design.md` to spawn stage_design.

**Why now**: medium complexity. Children path is the novel bit.

**Verification**:
- SINGLE path: `/sdd design <N>` produces same design:output as 0.x.
- CHILDREN path: produces same children + parent paused at sdd:implement.
- Retry with children-already-exist: same idempotency.

**Estimated effort**: ~2-3 days.

---

### M6: stage_implement (LARGEST)
- Create `commands/atoms/stage_implement.md` per design/stage-designs/implement.md.
- Inline: 6 work atoms (plan, red, green, refactor, e2e, pr) + 4 review variants + Skill invocations + tools-summary.
- Add R8: empty-$3 + existing-PR auto-routing.
- Add R9: TDD step idempotency.
- Update `commands/implement.md` to spawn stage_implement.

**Why now**: largest chunk. Single most important stage to validate.

**Verification**:
- TDD pipeline: red/green/refactor/e2e all produce same commits + markers.
- PR creation: same PR body, same labels.
- PR Final reviews: same verdict combination logic.
- /code-review + /security-review: invoked from inside stage_implement (verify R5 spike result in practice).
- R8: re-run `/sdd implement <N>` after manual fix and existing PR → routes to retry. No `gh pr create` error.
- R9: re-run after partial completion → skips already-done steps.
- Parent path: returns `OK PARENT_STOP` without doing TDD.

**Estimated effort**: ~4-6 days. This is the centerpiece.

---

### M7: stage_test
- Create `commands/atoms/stage_test.md` per design/stage-designs/test.md.
- Inline: test_work + 3 reviewers + parent_integration_review (parent path) + /verify Skill.
- Update `commands/test.md`.

**Verification**:
- SINGLE/CHILD path: same QA checklist, same label transition to sdd:done.
- PARENT path: same children-all-done check, same integration PR creation.
- Test framework re-spawn: same "no E2E test setup detected" flow.

**Estimated effort**: ~2-3 days.

---

### M8: Main session FSM (auto.md body) update
- Update `commands/auto.md` body to use new spawn pattern (bootstrap + stage_X) per design/03-flow-design.md.
- Slim from ~370 lines to ~100 lines (FSM only; helpers extracted).
- Phase 3.4 cleanup MUST-FIRST invariant preserved verbatim.

**Verification**:
- `/sdd auto` with N=2 Issues end-to-end: same Issues reach sdd:done.
- Crash mid-loop → recovery hint identical to 0.x.
- Sandbox toggle path unchanged.

**Estimated effort**: ~1-2 days.

---

### M9: /sdd batch update (minimal)
- batch.md mostly unchanged (generates `claude -p` script).
- Update generated script to use new commands (no change; uses same `/sdd resume <N>` entry).
- Verify subprocess execution end-to-end.

**Verification**: `/sdd batch <1,2,3>` runs identical to 0.x.

**Estimated effort**: ~half day.

---

### M10: Utilities updates
- init.md: add R10 transactional rollback.
- status.md: unify single/parent output schema.
- help.md: registry-generated content (from commands-inventory schema).
- review.md, rollback.md, config.md: unchanged behavior verification.

**Verification**:
- `/sdd init`: fresh repo + simulated partial-fail (mock gh rate-limit) → rollback triggered.
- `/sdd status <N>`: same output as 0.x for sample Issue states.
- `/sdd help`: same content (just generated differently).

**Estimated effort**: ~1 day.

---

### M11: Delete obsolete atoms
- Delete now-inlined atom files:
  - `commands/atoms/analyze_work.md`, `analyze_review.md`, `analyze_adversarial.md`
  - `commands/atoms/design_*.md` (3 files)
  - `commands/atoms/implement_*.md` (8 files)
  - `commands/atoms/test_*.md` (3 files)
  - `commands/atoms/parent_integration_review.md`
  - `commands/atoms/tdd_step_review.md`
- Keep helpers: `_preflight.md`, `_review_helpers.md`, `_test_evidence.md`, `_bash_rules.md`, `_multilingual.md`.

**Why last**: ensures nothing references them before deletion.

**Verification**: `grep -r "<<SKILL_DIR>>/commands/atoms/" .` confirms no references to deleted files.

**Estimated effort**: ~half day (mostly grep audits).

---

### M12: Version bump + release prep
- Bump `plugin.json` and `marketplace.json` to v1.0.0.
- Write `MIGRATION.md` user-facing doc.
- Tag `v1.0.0`.
- Update README, CLAUDE.md as needed.

**Verification**: clean diff against M11 + version check passes.

**Estimated effort**: ~half day.

---

## 3. Total Phase C effort estimate

| Milestone | Effort |
|---|---|
| M0 (pre-impl) | 30 min |
| M1-M3 (prep + bootstrap) | 1 day |
| M4 (stage_analyze) | 1-2 days |
| M5 (stage_design) | 2-3 days |
| M6 (stage_implement) | 4-6 days |
| M7 (stage_test) | 2-3 days |
| M8 (auto.md) | 1-2 days |
| M9 (batch.md) | half day |
| M10 (utilities) | 1 day |
| M11 (delete obsolete) | half day |
| M12 (release prep) | half day |
| **Total** | **~14-21 days** (single focused contributor) |

---

## 4. Critical path

M6 (stage_implement) is the longest pole. M4 should validate the architecture pattern before M5/M6/M7 work in parallel (if multi-contributor).

For single-contributor:
- Serial: M0 → M1 → M2 → M3 → M4 → M5 → M6 → M7 → M8 → M9 → M10 → M11 → M12
- Each milestone tagged for rollback.

For two contributors (after M4 validates pattern):
- Contributor A: M5 → M6
- Contributor B: M7 → M8 → M9
- Merge at M10.

---

## 5. Validation strategy per milestone

### Smoke tests (run after every milestone)
- `/sdd analyze <fixture-Issue>`: no errors, expected markers, expected label.
- `/sdd resume <N>` on each lifecycle state (fresh, analyzed, designed, in-implement, in-test).
- `grep` audits per milestone's checklist.

### Integration tests (run after M4 + M5 + M6 + M7)
- Full single-Issue lifecycle: analyze → design → implement → test → done. Manual or fixture-based.
- Parent+children lifecycle: design CHILDREN → child analyze → child implement → all children done → parent advances.

### Acceptance tests (run before M12)
- `/sdd auto` with 3 Issues mixing states. Measure: main session tokens (`/context`), wall-clock per Issue.
- `/sdd batch` with 3 Issues. Measure: log output, total time.
- Sandbox toggle path on a repo that needs it (TLS-proxy env).

### Spec compliance (continuous)
- Every change in Phase C should map to a spec/ contract.
- If a behavior in Phase C diverges from spec/, treat as a design bug — update design/ docs before merging.

---

## 6. After v1.0.0

- Patch releases (v1.0.x) for bug fixes inline.
- Minor (v1.1.0) for new features post-rewrite.
- v0.x branch maintained on `legacy/0.x` for back-ports if needed.

### Deferred from Phase B
Items tagged "deferred to Phase C judgment call" in 05-rethink-decisions.md:
- Sandbox toggle UX simplification (~190 lines) — touch if it gets in the way during stage_implement work.
- ai-review-*.md inlining (TAG-C31) — decision per stage during stage_X.md authoring.

### Future RETHINK candidates
- 2-level Agent spawn (if Claude Code platform adds it): re-enable parallel reviews inside stage sub-agents.
- Round-suffixed markers (R1 revisit): if audit needs grow.
- JSON RESULT migration (R5 revisit): if parser complexity grows.

---

## Cross-references

- Architecture: `00-architecture.md`
- File layout: `02-file-layout.md`
- Stage designs: `stage-designs/*.md`
- Migration: `06-migration-plan.md`
- RETHINK decisions: `05-rethink-decisions.md`
- Acceptance contracts: `spec/`
