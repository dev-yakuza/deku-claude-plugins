# Phase B Design v1 → v2 Synthesis

Resolution of findings from 3 parallel agent reviews + self-review. 42 findings total; Tier 1 (10) applied to design files; Tier 2/3 (32) deferred to Phase C with documented rationale.

---

## Tier 1 — Applied to Design v2

### T1.1 Drop `strict-pr-creation` config key (ARCH-A3, MIG-B3, FEA-C3) — APPLIED
- **Source**: design/stage-designs/implement.md §11.3 + §20.4
- **Fix**: Remove the opt-out config key. R8 = always auto-route on existing PR.
- **Rationale**: violates R2/R3 KEEP decision (no new config keys).
- **File touched**: stage-designs/implement.md

### T1.2 Unify R9 to sha-from-evidence (FEA-C2) — APPLIED
- **Source**: 05-rethink-decisions.md §R9 vs stage-designs/implement.md §14
- **Fix**: Drop "commit body marker" mechanism; use sha-from-test-evidence-comment as the canonical idempotency check (already specced in stage-designs/implement.md §14).
- **Benefit**: 0.x branches work without retroactive marking — `/sdd retroactive-mark` command no longer needed.
- **File touched**: 05-rethink-decisions.md + 06-migration-plan.md

### T1.3 stage_implement file split plan (SR-D1, FEA-C1) — APPLIED
- **Source**: stage-designs/implement.md (1117 lines design → 2000+ runtime)
- **Fix**: When implementing in Phase C, split into:
  - `commands/atoms/stage_implement.md` (Phase orchestration, ~400 lines) — entry point
  - `commands/atoms/stage_implement/_tdd.md` (TDD pipeline)
  - `commands/atoms/stage_implement/_pr_final.md` (PR Final review loop)
  - `commands/atoms/stage_implement/_phase7.md` (child completion)
- **Pattern**: main.md is what the Agent reads; main.md instructs Read on topic files in sequence. Single sub-agent context preserved.
- **File touched**: 02-file-layout.md (proposed structure)

### T1.4 Extend stage_test contract for QA / Framework returns (ARCH-A1) — APPLIED
- **Source**: stage-designs/test.md vs 01-sub-agent-contract.md §2
- **Fix**: Add to 01-sub-agent-contract.md §2:
  - `OK NEEDS_MANUAL_QA: <summary>` — interactive QA gate; main asks user
  - `OK NEEDS_FRAMEWORK_CHOICE: recommended=<name>` — main asks, re-spawns
  - `Resume: qa-approved` / `qa-failed` / `Framework: <name>` input fields
- **File touched**: 01-sub-agent-contract.md

### T1.5 ESCALATE canonical Resume behavior (ARCH-A2) — APPLIED
- **Source**: cross-stage inconsistency
- **Fix**: 01-sub-agent-contract.md §3 specifies canonical behavior:
  - On Resume: continue-after-escalation, sub-agent:
    1. Re-validates inputs from GitHub (gh issue view + gh pr list)
    2. Skips Phases 1-5 (work + reviews already done)
    3. Returns appropriate OK ADVANCE (main session does label transition)
  - All stages follow this contract.
- **File touched**: 01-sub-agent-contract.md

### T1.6 `/sdd review --deep` defer (SR-D7, ARCH-A11) — APPLIED
- **Source**: 04-utilities-design.md §5
- **Fix**: KEEP current 2-reviewer behavior for v1.0.0. Document in 04 §5 that adversarial inclusion deferred to v1.1+ with explicit user request.
- **Rationale**: matches R6 spirit (keep current behavior for low-risk decisions).
- **File touched**: 04-utilities-design.md

### T1.7 Document model-table behavior change (ARCH-A6) — APPLIED
- **Source**: stage-designs/implement.md §5; spec/edge-cases.md §5
- **Fix**: 06-migration-plan.md "What changes (visible if user looks closely)" — note that per-reviewer model dial is dead in Arch B (no separate Agent spawns). Depth still affects `/code-review --effort` and `/security-review` shallow-skip.
- **Decision**: accept the change; rewrite tradeoff documented.
- **File touched**: 06-migration-plan.md

### T1.8 Batch + ESCALATE conversion (ARCH-A7) — APPLIED
- **Source**: 03-flow-design.md §7.3 vs stage-designs/test.md §6
- **Fix**: In `claude -p` subprocess child sessions (batch), when stage returns `OK NEEDS_MANUAL_QA` or `ESCALATE`, main session converts to `OK PAUSE`-equivalent exit (child terminates cleanly; findings persisted on GitHub).
- **Rationale**: batch is unattended; conversion is the safe default.
- **File touched**: 03-flow-design.md

### T1.9 Version-sync hook concrete spec (MIG-B1, FEA-C9) — APPLIED
- **Source**: 06-migration-plan.md §2.1
- **Fix**: GitHub Actions check `.github/workflows/version-sync.yml`:
  ```yaml
  - name: Check version sync
    run: |
      PLUGIN_V=$(jq -r .version plugins/sdd-plugin/.claude-plugin/plugin.json)
      MARKET_V=$(jq -r '.plugins[] | select(.name=="sdd-plugin") | .version' .claude-plugin/marketplace.json)
      [ "$PLUGIN_V" = "$MARKET_V" ] || (echo "version mismatch: $PLUGIN_V vs $MARKET_V"; exit 1)
  ```
- **Excludes**: `legacy/0.x` branch via workflow conditional.
- **File touched**: 06-migration-plan.md

### T1.10 MIGRATION.md required content list (MIG-B4) — APPLIED
- **Source**: 06-migration-plan.md §2.3 / M12
- **Fix**: Normative content list now in 06-migration-plan.md (11 sections per review-B).
- **File touched**: 06-migration-plan.md

### T1.11 Bootstrap invocation §11 (SR-D9, FEA-C4) — APPLIED
- **Source**: 01-sub-agent-contract.md missing entry
- **Fix**: New §11 in 01-sub-agent-contract.md:
  - `/sdd auto`, `/sdd batch`, `/sdd resume` → always spawn bootstrap → spawn stages chain
  - `/sdd <stage> <N>` (direct) → command file reads labels itself (~250 tok), validates label matches; if mismatch → refuse with "Use /sdd resume <N>"; if match → spawn stage_<X> directly (skip bootstrap)
- **Rationale**: avoid wasteful bootstrap on direct invocation; avoid wrong-stage execution
- **File touched**: 01-sub-agent-contract.md

---

## Tier 2 — Documented, Deferred to Phase C

### T2.1 Round detection at sub-agent start (ARCH-A4)
- Crash recovery: partial marker writes leave round ambiguous.
- Add to Phase C: each stage_<X> Phase 0 includes "count existing review markers with PASS; decide Round 1 fresh vs idempotent advance".

### T2.2 Adversarial-only FAIL row in stage_implement §17 (ARCH-A5)
- Add explicit row to return table for symmetry with other stages.
- Phase C implementation detail.

### T2.3 SHA threading formalization (ARCH-A12)
- Document stage-internal state model vs main-FSM state model.
- Add §2.5 to 01-sub-agent-contract.md during Phase C if a re-split occurs.

### T2.4 Bootstrap "depth" output for done state (ARCH-A9)
- Add `BOOTSTRAP: stage=done variant=<complete|parent-waiting>` if behavior depends.
- Currently behaves correctly; documentation clarity only.

### T2.5 stage_implement R9 race against ongoing retries (ARCH-A8)
- Defensive parse failure → re-run step.
- Add to Phase C R9 implementation pseudocode.

### T2.6 Skill internals risk (ARCH-A14)
- Add to risk profile: "Skill internals change to nested → graceful skip covers".
- Documentation only.

### T2.7 stage_implement cold-boot estimate update (ARCH-A10)
- Update 00-architecture.md §5 with revised per-stage estimates (~13K for implement).
- Documentation only; doesn't change architecture.

### T2.8 Sandbox toggle preservation discipline (MIG-B9)
- M8 sub-task: preserve sandbox toggle line-for-line during auto.md slim.
- Diff against 0.x version pre-merge.

### T2.9 R10 rollback-of-rollback (MIG-B7, FEA-C8)
- Best-effort rollback with clear error report + manual cleanup commands.
- Add to Phase C R10 implementation pseudocode.

### T2.10 Re-run init partial-state heal (MIG-B8)
- Make init strictly idempotent (query existing first).
- Phase C implementation detail.

### T2.11 Deleted-atom path references (MIG-B10)
- M11 audit: scan README, CLAUDE.md, templates/, marketplace metadata.
- Documentation task.

### T2.12 batch script version watermark (MIG-B11)
- Include `# generated by sdd-plugin <version>` header in generated script.
- M9 implementation detail.

### T2.13 R9 cross-version warning marker (MIG-B6)
- `<!-- sdd:tdd:step-N v=1.0.0 -->` for forward-compat detection.
- Defer — current marker shape sufficient for v1.0.0.

### T2.14 R9 0.x branch resume warning (MIG-B12)
- MIGRATION.md note: "re-running on 0.x branch under v1.0.0 may duplicate effort; finish on 0.x first or restart fresh".
- Documentation task.

### T2.15 `/sdd retroactive-mark` resolution (MIG-B13)
- With T1.2 (sha-from-evidence), retroactive-mark unnecessary.
- Phase C: do NOT implement.

### T2.16 Fixture catalog (FEA-C5, FEA-C12)
- Commit `spec/fixtures/0.x-snapshot/` capturing 0.x markers/labels per stage state.
- Add to M0 (~half day).

### T2.17 M4.5 contract review checkpoint (FEA-C6)
- After M4 stage_analyze validates the pattern, review all 4 stage designs + contract before M5.
- Add to 07-implementation-plan.md sequence.

### T2.18 Phase C effort re-estimate (FEA-C7)
- 14-21 days → 18-27 days with contingency.
- Update 07-implementation-plan.md §3.

### T2.19 R10 best-effort spec (FEA-C8)
- See T2.9. Same fix.

### T2.20 M12 doc load (FEA-C10)
- 0.5d → 1-1.5d. MIGRATION.md skeleton drafted during M0.
- Update 07-implementation-plan.md.

### T2.21 /verify, /security-review spike (FEA-C11)
- Extend R5 spike to /verify, /security-review before M6/M7.
- Add to Phase C pre-implementation (half day).

---

## Tier 3 — Counter-proposals (worth considering before Phase C)

### T3.1 (CP-1) Resume reasons as tagged enum
- Replace free-form Resume: string with discriminated union.
- Eliminates ARCH-A1/A2 root cause.
- **Decision**: defer — current string-based approach works; refactor if pain emerges.

### T3.2 (CP-2) Extract common stage harness (`_stage_harness.md`)
- Phase 0, retry loop, verdict combination, escalation gate — shared across 4 stages.
- Estimated reduction: stage_implement 1117 → ~900 lines.
- **Decision**: defer — would change Phase C effort estimate; can be done post-v1.0.0 if maintenance pain emerges.

---

## Updated Phase C Effort

| Milestone | Original | Revised | Driver |
|---|---|---|---|
| M0 | 30 min | 1 day | +snapshot capture + version-sync workflow + MIGRATION.md skeleton + /verify+/security-review spikes |
| M3 | 2-3 hr | 4-6 hr | +clarify bootstrap vs direct command branching |
| M4 | 1-2 days | 1.5-2.5 days | unchanged content + M4.5 design re-review |
| M6 | 4-6 days | 6-8 days | +file split + verify R8/R9 mechanism |
| M7 | 2-3 days | 2-3.5 days | +/verify spike validation |
| M10 | 1 day | 1-1.5 days | +R10 rollback-of-rollback spec |
| M12 | 0.5 day | 1-1.5 days | +doc load |
| **Total** | **14-21 days** | **18-27 days** | with contingency |

---

## Design v2 Status

After Tier 1 application:
- 13 design files (~5,000+ lines)
- All cross-references consistent
- All RETHINK decisions explicit
- All review-surfaced contract gaps resolved
- Migration plan complete with MIGRATION.md content list + version-sync workflow

**Ready for Phase C.**

---

## Cross-references

- Phase A close-out: spec/SYNTHESIS-v2.md
- 3 review reports: design/review-{A,B,C}-*.md
- Self-review: design/SELF-REVIEW.md
- Updated files: design/01-sub-agent-contract.md, 02-file-layout.md, 03-flow-design.md, 04-utilities-design.md, 05-rethink-decisions.md, 06-migration-plan.md, 07-implementation-plan.md, stage-designs/implement.md, stage-designs/test.md
