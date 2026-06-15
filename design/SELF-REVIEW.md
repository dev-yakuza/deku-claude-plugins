# Self-Review Findings — Phase B Design

Internal review of design v1 before dispatching agent reviews.

## File Status

| File | Lines | Status |
|---|---:|---|
| README.md | 61 | ✓ |
| 00-architecture.md | 242 | ✓ |
| 01-sub-agent-contract.md | 240 | ✓ |
| 02-file-layout.md | 176 | ✓ |
| 03-flow-design.md | 581 | ✓ |
| 04-utilities-design.md | 408 | ✓ |
| 05-rethink-decisions.md | 222 | ✓ |
| 06-migration-plan.md | 234 | ✓ |
| 07-implementation-plan.md | 286 | ✓ |
| stage-designs/analyze.md | 281 | ✓ |
| stage-designs/design.md | 481 | ✓ |
| stage-designs/implement.md | 1117 | ✓ (over target but justified) |
| stage-designs/test.md | 545 | ✓ |
| **Total** | **4,874** | — |

## Strengths

1. **Decisions explicit** — every R1-R10 decision documented in 05-rethink-decisions.md with rationale.
2. **Cross-references consistent** — design files cite each other and spec/ correctly.
3. **Contract centralized** — 01-sub-agent-contract.md is the single source of truth for return keywords; all 4 stage designs reference it.
4. **Migration plan concrete** — 06-migration-plan.md has explicit M0 (version sync), validation checklist, rollback plan.
5. **Implementation plan ordered** — 07-implementation-plan.md has 12 milestones with verification per step.
6. **Backward compat clean** — R1-R6 all KEEP means zero breaking changes for users.

## Identified Concerns

### SR-D1. implement.md is large (1117 lines) [observed]
- Above the 700-900 target given by the agent.
- Justified by: largest stage, most complex (TDD pipeline + PR Final loop + R8/R9 additions + Skill invocations + parent path).
- Could be split into stage-designs/implement/ subdirectory with topic files, but the single-file form is easier to read end-to-end.
- **Verdict**: acceptable; agent should review for cuttable content.

### SR-D2. Skill invocation invariant subtly different in Arch B
- Current spec/stage/implement.md §7 says Skill cannot be in same parallel batch as Agent calls. Constraint is **at main-session message level**.
- In Arch B, stage_implement is one sub-agent context. Inside the sub-agent there are no Agent calls (single-level rule). So the "same batch" constraint is moot.
- Does this mean Skill ordering can be relaxed inside stage_implement? Probably not — the Skill comments needing to settle before subsequent reads is a separate concern (eventual consistency / read-after-write timing).
- **Design implication**: keep the serial ordering convention in stage_implement (Skills after SDD reviews) even though the platform constraint that motivated it no longer applies. design/stage-designs/implement.md does preserve this; verify in agent review.

### SR-D3. Bootstrap atom output format consistency
- 01-sub-agent-contract.md §7 specifies: `BOOTSTRAP: stage=<X> depth=<dial> branch=<...> pr=<...> parent=<bool> children=[...]`
- This is a different keyword from `OK ADVANCE: <stage>` etc.
- Main session needs to parse two different "kinds" of returns: stage returns (OK ADVANCE / OK PAUSE / ESCALATE / FAIL) and bootstrap returns (BOOTSTRAP: ...).
- **Verdict**: acceptable but worth flagging — main session FSM needs a dispatch on first token (BOOTSTRAP vs OK vs ESCALATE vs FAIL).

### SR-D4. R9 commit marker introduces a "v1.0.0 watermark"
- 05-rethink-decisions.md §R9: new commits include `<!-- sdd:tdd:step-N -->` in commit body.
- Old (pre-1.0.0) commits don't have this marker → idempotency skip doesn't fire.
- 06-migration-plan.md §7 notes this and proposes optional `/sdd retroactive-mark` command for Phase C.
- **Verdict**: acceptable; the degradation is "re-run work that was already done" which is wasteful but correct.

### SR-D5. State threading in main FSM
- 01-sub-agent-contract.md §8 says main remembers: current_stage, branch, pr_num, children list.
- But the FSM also needs depth (from labels), Issue queue (QUEUE), seen set (SEEN).
- These are mentioned in 00-architecture.md §2 but not explicitly in 01.
- **Verdict**: should consolidate into a single "state model" section. Minor.

### SR-D6. Adversarial-only FAIL surface inconsistency
- R6 keeps current behavior (treat as FAIL, retry).
- design/stage-designs/analyze.md design §5 says: "Adversarial-only FAIL → log warning, treat as FAIL (R6 decision)."
- design/stage-designs/design.md, implement.md, test.md should mirror this — agent review can verify.

### SR-D7. /sdd review adversarial asymmetry not resolved
- spec/utilities.md §6 noted [RETHINK]: `/sdd review` re-spawns 2 reviewers (completeness + quality), not adversarial.
- design/04-utilities-design.md §5 mentions adding `--deep` flag as an option but doesn't commit.
- Decision should be made: add flag, or keep current asymmetry, or always include adversarial.
- **Verdict**: missing decision. Agent review should flag.

### SR-D8. Stage_implement R8 detection in Phase 1 vs Phase 2
- 05-rethink-decisions.md §R8: detect existing PR at Phase 1 (Determine Issue type).
- design/stage-designs/implement.md §11.3: Option A auto-route default with `strict-pr-creation` config opt-out.
- The "opt-out" introduces a NEW config key (`strict-pr-creation`).
- This conflicts with R2/R3 (no new config keys without user decision).
- **Verdict**: ambiguity — design/stage-designs/implement.md §11.3 may have overreached. Need to confirm: R8 = always auto-route (no config opt-out) OR explicit user decision needed for the opt-out.

### SR-D9. M3 (bootstrap) vs M4 (stage_analyze) order
- 07-implementation-plan.md proposes M3 bootstrap before M4 stage_analyze.
- But bootstrap returns initial stage hint — if user is running `/sdd analyze <N>` directly (not /sdd resume), bootstrap may not be called.
- Need to clarify: does `/sdd analyze` go through bootstrap, or does it bypass directly to stage_analyze?
- **Verdict**: design should clarify. Likely: `/sdd analyze <N>` reads command file → main session spawns stage_analyze directly (no bootstrap). `/sdd resume <N>` reads command file → main session spawns bootstrap → reads result → spawns appropriate stage.

### SR-D10. Test framework re-spawn pattern in Arch B
- stage_test may return `FAIL: no E2E test setup detected; recommended framework: <name>`.
- Main session asks user, gets framework choice, re-spawns stage_test.
- The re-spawn carries the framework choice via prompt text — like the current architecture.
- **Verdict**: 01-sub-agent-contract.md doesn't explicitly handle this. Could be added as a "Framework: <name>" input field.

## Spec Coverage Spot-Check

Sampling 5 random [PRESERVE] items from spec/ to verify they're preserved in design/:

1. **spec/00-common-contracts.md §7 — Retry mode trigger** — atom self-fetches via marker on `$2 = "retry"`. ✓ Preserved per design/stage-designs/*.md sections on retry loops.
2. **spec/stage/implement.md §7 — PR Final 3 rounds with verdict combination** — ✓ Preserved per design/stage-designs/implement.md §12.
3. **spec/edge-cases.md §3 — Sandbox + permission heuristic bypass** — ✓ Preserved per design/03-flow-design.md sandbox toggle section.
4. **spec/edge-cases.md §17 — Duplicate-Prevention pattern** — ✓ Preserved per design/01-sub-agent-contract.md (markers + Section F references).
5. **spec/02-multilingual.md §3 — Parent regex `(Parent|상위 |親)Issue: #<n>`** — ✓ Preserved per design/00-architecture.md cross-references + multiple stage designs.

All 5 sampled items preserved. Quick sample only — agent review for completeness.

## Inconsistency Spot-Check

- Return keywords consistent across 4 stage designs + contract + flow: ✓ (grep verified all 6 files contain OK ADVANCE / ESCALATE / etc.)
- File paths in 02-file-layout.md match references in stage designs: ✓ (atoms/rubrics/ used consistently)
- M-milestone effort estimates plausible: M6 4-6 days is the longest pole — reasonable given 1117-line design.

## Verdict

Design v1 is **complete and internally consistent** for Phase B paper design. 10 identified concerns are mostly minor refinements or ambiguities flagged for agent review.

**Critical concerns to surface in agent review**:
- SR-D7: `/sdd review` adversarial decision (missing)
- SR-D8: R8 opt-out config key (potential R2 violation)
- SR-D9: `/sdd analyze` vs `/sdd resume` bootstrap invocation
- SR-D10: Framework re-spawn contract gap

**Recommendation**: proceed to parallel agent review (Task #15).
