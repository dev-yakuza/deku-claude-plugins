# Reviewer A: Architectural Findings

Adversarial architectural review of Phase B design (excluding SR-D1..SR-D10).

---

## Critical (must address before Phase C)

- **ARCH-A1: FSM has no terminal handler for `OK NEEDS_MANUAL_QA` / `OK NEEDS_FRAMEWORK_CHOICE`**
  - Issue: `stage-designs/test.md` §9 introduces two new stage-test-specific return keywords (`OK NEEDS_MANUAL_QA: <summary>`, `OK NEEDS_FRAMEWORK_CHOICE: recommended=<name>`). Both require the main session to (a) prompt the user, (b) re-spawn `stage_test` with a Resume hint carrying user data. But `01-sub-agent-contract.md` §2's stage_test table and §9 contract validation only list `OK DONE / OK BACK_TO_IMPLEMENT / OK PAUSE / ESCALATE / FAIL`. `03-flow-design.md` §1.2 main-loop pseudocode has no case for these returns — they would be treated as `FAIL: unexpected return` per `01-sub-agent-contract.md` §9.
  - Source: `design/stage-designs/test.md` §6 case B, §9, §13 vs `design/01-sub-agent-contract.md` §2 stage_test row, §9; `design/03-flow-design.md` §1.2.
  - Fix: Extend the stage_test contract table to include both keywords; add explicit FSM cases in §1.2 (Resume value mapping: `qa-approved` / `qa-failed` / `Framework: <name>`); document the `Framework:` and `Resume:` input fields explicitly in §1's prompt template.

- **ARCH-A2: ESCALATE round-trip loses retry-context idempotency contract**
  - Issue: Main re-spawns `stage_<X>` with `Resume: continue-after-escalation`. Per `stage-designs/analyze.md` §2 and `design.md` §8.5, the sub-agent skips Phases 1–5 and goes straight to Phase 6 output. But `stage-designs/implement.md` §17 routes "Continue" by returning `OK ADVANCE` "since human has accepted findings" — without re-running label transition logic that lives in main. The contract is asymmetric across stages: analyze/design fast-path label-transitions internally; implement assumes main does so. Also, the resume path does NOT re-derive `branch`/`pr_num` cache from GitHub — it relies on prompt inputs that may now be stale (e.g. PR closed mid-escalation).
  - Source: `design/stage-designs/analyze.md` §2 + §8 vs `design/stage-designs/design.md` §8.5 vs `design/stage-designs/implement.md` §12.9, §17.
  - Fix: Specify one canonical "resume after escalation" behavior in `01-sub-agent-contract.md` §3 (re-validate inputs from GitHub, then either return `OK ADVANCE: <next>` without doing label work OR perform label transition — pick one). Add a defensive re-validation step.

- **ARCH-A3: SR-D8 unresolved — R8 introduces a new config key contradicting R2/R3**
  - Issue: `stage-designs/implement.md` §11.3 + §20.4 declares a NEW config key `strict-pr-creation: <bool>` in `.github/.sdd-config`. R2/R3 (per `05-rethink-decisions.md`) explicitly KEEP existing config keys to avoid breaking changes; introducing a new key is a non-trivial config surface addition that was never user-decided. SR-D8 flagged this but the design wasn't updated.
  - Source: `design/stage-designs/implement.md` §11.3, §20.4; `design/05-rethink-decisions.md` R8 vs `design/SELF-REVIEW.md` SR-D8.
  - Fix: Either remove the opt-out (R8 is always auto-route — pure improvement), OR escalate the config-key decision to user before Phase C. Recommend: drop the key; the "clear error" mode is dead weight for unattended flows and adds documentation burden.

---

## Major (worth addressing)

- **ARCH-A4: Crash recovery — partial marker writes leave Bootstrap state ambiguous**
  - Issue: `03-flow-design.md` §2.5 says bootstrap is "idempotent and read-only" and `§9.5` lists "mid-stage sub-agent crash → main receives a tool error → FAIL". But if a stage sub-agent crashed after posting `<!-- sdd:analyze:output -->` and BEFORE posting `<!-- sdd:review:analyze:completeness -->`, on re-run bootstrap returns `stage=analyze` (label is still `sdd:analyze`). Re-spawned `stage_analyze` re-runs Phase 1 work (idempotent in-place overwrite OK) but Phase 4 retry self-fetch may see ZERO review markers — does it count as Round 1 fresh or as Round 2 retry with empty findings? `stage-designs/analyze.md` §6 doesn't disambiguate.
  - Source: `design/03-flow-design.md` §9.5; `design/stage-designs/analyze.md` §6.
  - Fix: Add a "round detection" step at sub-agent start: if N review markers exist with PASS verdict → idempotently advance; if 0 exist → Round 1 fresh; if mixed → restart from Round 1 (overwrite-in-place). Document in each stage design's Phase 0.

- **ARCH-A5: Adversarial-only FAIL inconsistency in `stage_implement` §12.7**
  - Issue: `stage-designs/implement.md` §12.7 says "edge-cases §19 adversarial-only FAIL → log warning but treat as FAIL". But the verdict combination above it already says "Any SDD reviewer `OK FAIL` → Round = FAIL". The adversarial-only case is structurally a normal FAIL — the warning log is the ONLY differentiator. R6 says "log + retry" applies uniformly; consistent with §12.7. However the §17 return-table row for "Adversarial-only FAIL" is missing entirely (only mentioned in narrative). Verify other stages: analyze §5 has it explicit, design §5 has it explicit, test §4 has it explicit.
  - Source: `design/stage-designs/implement.md` §12.7, §17 vs analyze/design/test consistency.
  - Fix: Add adversarial-only-FAIL row in §17 for symmetry; or remove explicit handling from analyze/design/test §5 and consolidate in `01-sub-agent-contract.md`.

- **ARCH-A6: Inlining loses Section A.2 model-table single-source-of-truth**
  - Issue: Per current spec/edge-cases.md §5, `_review_helpers.md` Section A.2 is the canonical model table. With reviews inlined into stage sub-agents (no separate Agent spawns), models are no longer chosen per-spawn — `stage-designs/implement.md` §5 explicitly notes "models above are role guidance, not Agent spawns. ... The model column becomes informational at runtime." This silently breaks the depth dial's per-role model assignment (e.g. step 2/3 haiku vs step 1/4 sonnet). The depth still drives `/code-review --effort` and shallow-skip on `/security-review`, but per-reviewer model selection is dead.
  - Source: `design/stage-designs/implement.md` §5; `spec/edge-cases.md` §5; `spec/stage/implement.md` Phase 0 table.
  - Fix: Either (a) document this as an intentional behavior change in `06-migration-plan.md` "What changes (visible if user looks closely)" and accept that depth no longer modulates per-review cost, OR (b) explore "model hint in Skill/Agent invocation if exposed by Claude Code" — but probably not available for inline reviewers. Recommend (a) with clear user-facing note.

- **ARCH-A7: `/sdd batch` qa-gate exit silently loses ESCALATE — RESOLVED**
  - ~~Issue: `03-flow-design.md` §7.3 says batch writes 4-key skip-review (no `qa`). When `stage_test` reaches QA gate without `qa` set, design says it returns `OK PAUSE`. But per `stage-designs/test.md` §6 case B and §9, the correct return there is `OK NEEDS_MANUAL_QA: <summary>` — not `OK PAUSE`. Same problem reappears at §8 (escalation) where without `qa` it returns `ESCALATE`. In `claude -p` subprocess with `--dangerously-skip-permissions`, main can't ask user → ESCALATE is unrecoverable. Design ignores this case.~~
  - Resolution: batch now writes 5-key skip-review including `qa` (same as `/sdd auto`). `stage_test` auto-advances through the QA gate and the ESCALATE-in-child path is no longer reachable from normal flow. `spec/flow/batch.md` §5, `design/03-flow-design.md` §7.3, and `commands/batch.md` all updated.

- **ARCH-A8: Stage_implement R9 idempotency check has a race against ongoing retries**
  - Issue: `stage-designs/implement.md` §14.1 checks for `<!-- sdd:test-evidence:step-<n> -->` AND `<!-- sdd:review:implement:step-<n> -->` with PASS verdict. But step-review markers are updated in-place per round (Common Contracts §4). If a prior `/sdd implement` crashed after Round 2 PASS for step-1 but mid-step-2 retry, the step-2 review marker has the latest round-N FAIL — meaning step-1 still has PASS marker, but is the test-evidence sha still ancestor? The check verifies that, OK. But `<sha>` and `<test-evidence>` parsing assumes a specific body format. If the body was updated by an OOB user edit (allowed per QA flow), parsing may fail silently.
  - Source: `design/stage-designs/implement.md` §14.1, §14.4; `spec/00-common-contracts.md` §4.
  - Fix: Add defensive parse failure → re-run step (safe default). Document the body-format dependency. Consider versioning the test-evidence body shape via embedded `<!-- sdd:findings:json -->` `schema_version` field (already proposed in spec).

- **ARCH-A9: Bootstrap "depth" output ambiguity for "done" state**
  - Issue: Bootstrap returns `BOOTSTRAP: stage=... depth=... ...`. If `stage=done` (Issue already complete), `depth` is meaningless but still emitted. Main session pseudocode in §1.2 reads `state.depth` from bootstrap and threads it to subsequent stage spawns — but for `stage=done` no stages spawn. Defensive ok, but `done` with `parent=true` is interesting: bootstrap doesn't tell main that the parent is "done but waiting on children" vs "fully complete". The auto loop's child-discovery (§1.7) handles this, but the design conflates them.
  - Source: `design/01-sub-agent-contract.md` §7; `design/03-flow-design.md` §1.2 (line `if boot.stage == "done": SUCCEEDED += 1; ... run_child_discovery(ISSUE)`).
  - Fix: Add explicit `BOOTSTRAP: stage=done variant=<complete|parent-waiting>` if behavior depends. Otherwise document that `done + parent=true` is handled identically (the current pseudocode does run child discovery on done — appears correct, just lacks rationale).

- **ARCH-A10: stage_implement.md token estimate misses cold-boot regression**
  - Issue: `00-architecture.md` §5 estimates per-stage cold-boot at ~8K tokens. But `stage-designs/implement.md` is 1117 lines (~13K tokens). Across 4 stages, total cold-boot is ~32K but stage_implement alone exceeds the per-stage estimate by ~60%. With retries, stage_implement context grows further. Combined with rubric file reads (~1.8K) and inline atom logic exposition, single stage_implement sub-agent context may reach 50-80K tokens before any work. SR-D1 noted line count but didn't update the per-stage token estimate.
  - Source: `design/SELF-REVIEW.md` SR-D1; `design/00-architecture.md` §5; `design/stage-designs/implement.md` (1117 lines).
  - Fix: Update §5 with revised cold-boot per stage: analyze ~3.5K, design ~5.5K, implement ~13K, test ~6.5K — total ~28.5K. Note that implement stage's context utilization will be measurably higher than current `implement.md` (~4.5K) + per-atom 1.5-2K. The win is on main session; sub-agent cost grows. Document this trade-off explicitly.

- **ARCH-A11: SR-D7 unresolved — `/sdd review --deep` decision baked into design without user gate**
  - Issue: `04-utilities-design.md` §5 commits to the `--deep` flag option. SELF-REVIEW SR-D7 flagged this as a missing decision. Adding a new flag is a public API extension — should be a R-level decision, not silently committed by the designer.
  - Source: `design/04-utilities-design.md` §5; `design/SELF-REVIEW.md` SR-D7.
  - Fix: Surface to user as an R-decision before Phase C. Recommend: keep current 2-reviewer behavior for v1.0.0 (R6-style "keep current"); defer `--deep` to v1.1 with explicit user request.

---

## Minor (nice-to-have)

- **ARCH-A12: SHA threading via stage-internal vars not formalized**
  - Issue: `stage-designs/implement.md` §10.4 says SHA + test-evidence threading is "stage-internal". Not in `01-sub-agent-contract.md`. If future refactor splits stage_implement into two sub-agents (e.g. TDD vs PR Final), the implicit threading breaks. Worth documenting "stage-internal state model" explicitly.
  - Source: `design/stage-designs/implement.md` §10.4.
  - Fix: Add §2.5 to `01-sub-agent-contract.md` listing what's stage-internal vs main-FSM state.

- **ARCH-A13: Bootstrap `parent=true` + `stage=test` semantics**
  - Issue: Bootstrap can return `stage=test parent=true`. Main spawns stage_test with parent context. stage_test re-detects parent via children marker. Two sources, no canonical: did parent's children re-create after rollback? §10's path detection re-runs, but if `children` list shrunk (impossible per design idempotency, but defensive), behavior is undefined.
  - Source: `design/03-flow-design.md` §2.3, `design/stage-designs/test.md` §10.
  - Fix: Document that stage_test always re-derives from GitHub; bootstrap input is hint only. Already implicit per contract §1 [PRESERVE — load-bearing], but re-stating in test.md §10 helps.

- **ARCH-A14: Skill inside sub-agent — what if Skill itself spawns sub-agents?**
  - Issue: `/code-review`, `/security-review`, `/verify` are Claude Code Skills. The task asks whether Skill might internally spawn sub-agents. Empirically (R5 spike), they reach successfully from inside a sub-agent — that means the platform tolerates Skills inside the single-level rule (Skills are not "Agent calls" in the platform model). But if `/code-review` internally uses `Task` tool or similar, the call chain is 2-deep (main → stage_implement → /code-review → ?). The design treats this as "verified safe" but never analyzes what `/code-review` does internally. If Anthropic changes `/code-review` to nest, stage_implement breaks silently.
  - Source: `design/00-architecture.md` §4 [VERIFIED — R5 spike]; `spec/00-common-contracts.md` §13.
  - Fix: Add risk row to §8 risk profile: "Skill internals change to nested sub-agents → stage_implement Skills fail. Mitigation: graceful skip already covers this case (records `skill-errored`), so degradation is observable not silent."

- **ARCH-A15: M3 vs M4 ordering — partial inversion ok but not documented**
  - Issue: SR-D9 flagged the unclear bootstrap invocation path. The design's `commands/analyze.md` is a "thin wrapper that spawns stage_analyze" per `02-file-layout.md` §2 — meaning `/sdd analyze <N>` does NOT go through bootstrap. But `/sdd resume <N>` does. The wrapper's job: validate Issue, then spawn stage. The current design files don't show what the wrapper actually does. Phase C ambiguity.
  - Source: `design/02-file-layout.md` §2; `design/SELF-REVIEW.md` SR-D9.
  - Fix: Add one paragraph to `03-flow-design.md` explaining `commands/<stage>.md` wrapper body (5-line: validate Issue, spawn `stage_<X>`, parse return, optional label transition + auto-advance via skip-review check).

---

## Counter-proposals

### CP-1: Promote "Resume reasons" to a tagged enum in the contract

Currently, `Resume:` field carries free-form strings: `none`, `continue-after-escalation`, `qa-approved`, `qa-failed`, plus an implicit `Framework: <name>` second field. This is parser-fragile and lets stages disagree on what they accept. Propose making `Resume:` a discriminated union in `01-sub-agent-contract.md`:

```
Resume: { reason: "none" | "escalation-continue" | "qa-approved" | "qa-failed" | "framework-chosen", data?: {...} }
```

Stages declare which `reason` values they accept. Main FSM validates before re-spawn. Eliminates contract drift between `stage_test`'s 3 resume modes and `stage_analyze`/`design`'s 1 mode.

Cost: minor — replaces string match with field-tagged parse. Benefit: ARCH-A1 + ARCH-A2 root cause goes away.

### CP-2: Extract "common stage harness" file before Phase C

Implementation §12 of `stage-designs/design.md` already flags this. Concretely: create `atoms/_stage_harness.md` containing the Phase 0 (depth), retry loop scaffold, verdict combination table, escalation gate skeleton. Each `stage_X.md` references it instead of inlining ~200 lines of identical structure.

Estimated reduction: stage_implement 1117 → ~900 lines; analyze/design/test similarly. Tightens consistency (ARCH-A4, A5) and reduces cold-boot. Worth doing in M2 (before M3 bootstrap) so all later milestones benefit.

---

## Summary

- Critical: 3
- Major: 8
- Minor: 4
- Counter-proposals: 2

Total findings: 15 (within the 8-15 target range). The 3 Critical findings (A1 missing return-keyword handling, A2 ESCALATE asymmetry, A3 unresolved config-key R-decision) are pre-conditions for Phase C; A4-A11 are addressable during Phase C implementation; minor findings are documentation polish. CP-1 and CP-2 are structural improvements worth landing before code.
