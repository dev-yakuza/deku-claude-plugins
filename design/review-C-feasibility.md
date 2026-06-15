# Reviewer C: Implementation Feasibility Findings

Adversarial review of Phase B design from an implementation-feasibility lens. Does NOT repeat SR-D1..SR-D10.

## Blocking issues (must resolve before Phase C)

- FEA-C1: stage_implement.md actual file size will exceed maintainable bounds; no split plan.
  - Issue: design/stage-designs/implement.md is 1117 lines of *design prose*. The actual `atoms/stage_implement.md` must inline 9 atoms summing to 1131 lines (per `wc -l` on `implement_*.md` + `tdd_step_review.md`) PLUS R8 (~30 lines) + R9 (~50 lines) + Phase 7 + escalation + tools-summary wiring + preamble. Conservative estimate: 1800-2500 lines for the runtime md. 07-implementation-plan.md M6 says "4-6 days" but provides no concrete maintainability target (e.g. "≤ N lines"). At 2000+ lines, future edits become a needle-in-haystack exercise and grep audits dominate.
  - Source: design/stage-designs/implement.md §3 atom inventory; design/02-file-layout.md §1.
  - Recommendation: commit before M6 to a split: `atoms/stage_implement/main.md` (Phase orchestration only, ~300 lines) plus `_tdd.md`, `_pr_final.md`, `_phase7.md`. The "single sub-agent context" is preserved because the spawned agent Reads `main.md` and `main.md` instructs it to Read the topic files in sequence. M6 effort should rise to 6-8 days with this split, but maintainability is unblocked. Alternatively, set a hard line budget in design (e.g. 1500 lines) and accept the file as a "load me once" reference.

- FEA-C2: R9 commit-marker mechanism is unspecified and likely broken in practice.
  - Issue: 05-rethink-decisions.md §R9 says "commit body has `<!-- sdd:tdd:step-N -->`-style marker added during rewrite". design/stage-designs/implement.md §14.1 instead specifies sha-from-evidence-comment + `git merge-base --is-ancestor` + commit-subject heuristic — no commit-body marker. These are two different mechanisms in two design files. Worse, the commit-body-marker variant is brittle (`git log --grep="<!-- sdd:tdd:step-N -->"` is slow on large repos, and HTML comments in commit messages may be stripped by some hosts/tools, e.g. squash-merge rewrites). The §14 sha-based variant is more sound but depends on the test-evidence comment containing a parseable `Commit: <sha>` line — verify that `_test_evidence.md` actually produces that field in body §15.2 (it does — good).
  - Source: design/05-rethink-decisions.md §R9 vs design/stage-designs/implement.md §14.
  - Recommendation: delete the "commit-body marker" mechanism from 05-rethink-decisions.md. Make §14's sha-from-evidence-marker the single mechanism. Update 06-migration-plan.md §7 accordingly (its `<!-- sdd:tdd:step-N -->` story is also outdated). The `/sdd retroactive-mark` command then becomes unnecessary — 0.x branches have evidence markers already and §14 will Just Work on them.

- FEA-C3: R8 introduces a NEW config key (`strict-pr-creation`) without user decision.
  - Issue: design/stage-designs/implement.md §11.3 and §20.4 add `.github/.sdd-config: strict-pr-creation: <bool>`. SR-D8 flagged this; the design did not resolve it. R2/R3 explicitly KEEP current config to avoid breaking users — adding `strict-pr-creation` violates the same principle without justification.
  - Source: design/stage-designs/implement.md §11.3, §20.4; design/SELF-REVIEW.md SR-D8.
  - Recommendation: drop the opt-out. Always auto-route on existing PR (Option A only). The §11.3 "verify `Refs #$1` in PR body" safety check already prevents the dangerous case (overwriting unrelated PR). Users who want strict behavior can `gh pr close` first. If retained, MUST be added to /sdd config validation (§04-utilities §2 currently lists only the 5 skip-review keys as valid — orphan key warning will fire).

## Significant concerns (worth addressing)

- FEA-C4: Bootstrap atom is spawned by `/sdd resume` but bypassed for `/sdd <stage>` direct invocation — no design lives where this branching happens.
  - Issue: SR-D9 surfaces the ambiguity but doesn't resolve it. 07-implementation-plan.md M3 just says "Update commands/resume.md to spawn bootstrap". The actual decision tree (which command files spawn bootstrap, which spawn stages directly) is undocumented. For `/sdd auto`, 03-flow-design.md §1.2 shows bootstrap spawned per Issue, which is correct. For `/sdd analyze <N>` (direct), bootstrap is wasteful — the user already declared the stage. But what about `/sdd implement <N>` when the Issue is at `sdd:design`? Direct spawn would skip the dispatcher and possibly leave wrong-stage execution.
  - Source: design/01-sub-agent-contract.md §7; design/03-flow-design.md §1.2; design/SELF-REVIEW.md SR-D9.
  - Recommendation: add §11 to 01-sub-agent-contract.md spelling out: (a) `/sdd auto`, `/sdd batch`, `/sdd resume` always go through bootstrap; (b) `/sdd <stage> <N>` reads labels itself (1 gh call, ~250 tok), validates label matches requested stage, otherwise refuses with "Issue is at sdd:design; use /sdd resume <N> for correct stage". This avoids both the wasted bootstrap call AND the wrong-stage execution risk.

- FEA-C5: No testing harness; "produces same markers/labels as 0.x" verification is undefined.
  - Issue: 02-file-layout.md §7 proposes a tests/ directory then says "Decision deferred to Phase C". 07-implementation-plan.md §5 enumerates smoke/integration/acceptance tests but never explains *how* they execute (Bash script? Manual? CI?). M4 says verification is "/sdd analyze <N> on a fresh Issue produces the same markers, same labels, same advance behavior as 0.x" — but with v1.0.0 installed, the 0.x version no longer runs, so the comparison is by memory or by checked-in expected-output fixtures (which don't exist).
  - Source: design/02-file-layout.md §7; design/07-implementation-plan.md §5; design/06-migration-plan.md §12.
  - Recommendation: before M4 starts, run 0.x against a fresh test Issue and capture every marker body + label sequence into `spec/fixtures/0.x-snapshot/`. M1..M11 verification compares post-change markers to those fixtures via `gh api ... | diff`. Drop the tests/ directory from 02-file-layout.md if no harness is committed; or keep ONE fixture directory and clarify Phase C is responsible for it. Add ~half day to M0 for snapshot capture.

- FEA-C6: M4 → M5 → M6 → M7 strict serial ordering blocks any pattern-validation feedback.
  - Issue: 07-implementation-plan.md §4 critical path is serial. M4 (stage_analyze, 1-2 days) is the pattern validator. But if M4 reveals a problem with the stage-sub-agent contract (e.g. the FAIL: vs OK FAIL: distinction blurs once inlined), the fix cascades back into 01-sub-agent-contract.md and all 4 stage designs — yet 02-stage_design and 03-stage_test designs are already locked. There's no "M4.5 contract review" checkpoint.
  - Source: design/07-implementation-plan.md §2 (M4) + §4 critical path.
  - Recommendation: insert M4.5 explicit gate: "after M4, review the 4 stage designs against actual M4 implementation; update designs before starting M5." Budget: half day. If M4 reveals a fundamental issue (e.g. Skill+Agent interaction inside sub-agents differs from R5 spike), the project pivots cheaply rather than after M7.

- FEA-C7: Phase C effort estimate (14-21 days) lacks contingency and assumes spec/ is frozen.
  - Issue: 07-implementation-plan.md §3 sums 14-21 days. No contingency line. The user prefers iterative review (per memory note "/clear between SDD steps") and Phase A took multiple turns — Phase C is much larger. M6 alone is 4-6 days for a 2000+ line file; the design review uncovered SR-D7, SR-D8, SR-D10 unresolved items meaning spec/ is NOT frozen.
  - Source: design/07-implementation-plan.md §3; design/SELF-REVIEW.md SR-D7..D10.
  - Recommendation: re-estimate per below ("Effort re-estimate"). Add explicit contingency: M0 ~1 day (was 30 min) for snapshot capture + version sync + branch + tag; M4 1.5-2.5 days; M6 6-8 days. Total 18-26 days realistic for single contributor. Communicate this to user upfront.

- FEA-C8: R10 rollback failure-of-failure is hand-waved.
  - Issue: 04-utilities-design.md §1 "FAIL: partial" outcome occurs when a rollback `gh label delete` itself fails. Design says "Manual cleanup: gh label delete <each>". Real-world: rollback failure usually means same root cause (auth, rate limit, network) — manual cleanup will also fail. No retry policy, no exponential backoff, no "try non-deleted labels in next iteration".
  - Source: design/04-utilities-design.md §1.
  - Recommendation: spec rollback as best-effort with explicit "labels left in repo" report including label names AND error per delete. Suggest user re-run `/sdd init` after fixing the underlying issue — `--force` will reconcile state. Add this to MIGRATION.md user-facing notes.

- FEA-C9: M0 version-sync CI/pre-commit hook implementation is unspecified.
  - Issue: 06-migration-plan.md §2.1 and 07-implementation-plan.md M0 both reference "CI check or pre-commit hook for version sync". No implementation file is named, no language chosen (bash? GitHub Actions yaml?), no rollout (does pre-commit need user install?). The CLAUDE.md memory note explicitly says "always update BOTH files together" — this is a known recurring issue.
  - Source: design/06-migration-plan.md §2.1; CLAUDE.md.
  - Recommendation: commit to GitHub Actions check on PR: `.github/workflows/version-sync.yml` reading both files via `jq`, failing if mismatched. Pre-commit hook is unreliable (contributors may skip). ~30 min to author; counts toward M0 effort.

## Minor concerns

- FEA-C10: Documentation update load at M12 is underestimated.
  - Issue: 07-implementation-plan.md M12 says "half day" but lists: bump versions (2 files), write MIGRATION.md, update README, CLAUDE.md, plus implicit help.md/registry, plugin.json description, marketplace.json description. MIGRATION.md alone for a v1.0.0 rewrite is half a day.
  - Source: design/07-implementation-plan.md M12.
  - Recommendation: estimate M12 at 1-1.5 days. Draft MIGRATION.md skeleton during M0 to amortize.

- FEA-C11: Spike risk — Skill invocations inside sub-agent is verified per R5 but only for `/code-review`.
  - Issue: 00-architecture.md §4 [VERIFIED — R5 spike] applies to one Skill. stage_test's §11 also invokes `/verify` inside sub-agent. Was `/verify` part of the spike? If only `/code-review` was tested, `/verify` may have different invocation semantics (it requires app launch context).
  - Source: design/00-architecture.md §4; design/stage-designs/test.md §11.
  - Recommendation: extend R5 spike to `/verify` and `/security-review` before M6/M7. Half day. Failure here invalidates ~30% of the win.

- FEA-C12: Per-milestone "verification" steps assume manual fixture Issues exist.
  - Issue: M1..M11 verification text references "fixture Issue", "sample Issue", "known Issue", etc. No fixture catalog is committed. Each verification step requires the implementer to author ad-hoc Issues, which is non-deterministic.
  - Source: design/07-implementation-plan.md §2 throughout.
  - Recommendation: commit a "fixtures README" before M1 listing the 6-8 Issue states needed (fresh, analyzed, designed-single, designed-children, in-implement-step2-PASS, in-implement-PR-Final-round3-FAIL, parent-all-children-done, etc.) and the gh commands to create them.

## Effort re-estimate

| Milestone | 07-plan estimate | Revised | Driver |
|---|---|---|---|
| M0 | 30 min | 1 day | +snapshot capture (FEA-C5), +CI version hook (FEA-C9) |
| M1 | 1-2 hr | 2-3 hr | unchanged |
| M2 | 2-3 hr | 2-3 hr | unchanged |
| M3 | 2-3 hr | 4-6 hr | +clarify resume vs direct branching (FEA-C4) |
| M4 | 1-2 days | 1.5-2.5 days | unchanged content + M4.5 design re-review (FEA-C6) |
| M5 | 2-3 days | 2-3 days | unchanged |
| M6 | 4-6 days | 6-8 days | +file split (FEA-C1), +verify R8/R9 mechanism (FEA-C2/C3) |
| M7 | 2-3 days | 2-3.5 days | +/verify spike extension (FEA-C11) |
| M8 | 1-2 days | 1-2 days | unchanged |
| M9 | half day | half day | unchanged |
| M10 | 1 day | 1-1.5 days | +R10 cleanup spec (FEA-C8) |
| M11 | half day | half day | unchanged |
| M12 | half day | 1-1.5 days | +doc load (FEA-C10) |
| **Total** | **14-21 days** | **18-27 days** | with contingency |

## Summary

- Blocking: 3 (FEA-C1, FEA-C2, FEA-C3)
- Significant: 6 (FEA-C4, FEA-C5, FEA-C6, FEA-C7, FEA-C8, FEA-C9)
- Minor: 3 (FEA-C10, FEA-C11, FEA-C12)
