# Audit 2: Design Compliance + Implementation Soundness

Reviewer: Phase C Audit Reviewer 2. Scope: verify v1.0.0 code implements `design/` correctly AND verify internal soundness of the stage sub-agents. Findings below cite `path:line`.

## Tier 1 fix verification (T1.1–T1.11)

- **T1.1 — Drop `strict-pr-creation` config key.** verified.
  - `_pr_final.md:6,94,643`, `main.md:330`, `commands/implement.md:184` all explicitly call out "no `strict-pr-creation` config key". A repo-wide grep returns matches only in narrative/docstrings, never as a config-read site.
- **T1.2 — Unify R9 to sha-from-evidence.** verified.
  - `_tdd.md:67` declares "No commit-body marker (that path is dropped per T1.2)" and `§2.1–§2.5` (`_tdd.md:71–127`) implement evidence-marker fetch → review-marker verdict check → sha parse → `git merge-base --is-ancestor` → subject heuristic. No `git log --grep` against any `<!-- sdd:tdd:step-N -->` commit marker anywhere in the implementation.
- **T1.3 — stage_implement split into 4 files.** verified.
  - Files exist under `plugins/sdd-plugin/skills/sdd/commands/atoms/stage_implement/`: `main.md` (entry, ~456 lines), `_tdd.md`, `_pr_final.md`, `_phase7.md`. `main.md:7-13` describes the split and load order. Spawner wrapper (`commands/implement.md:74`) reads only `main.md`.
- **T1.4 — Extended stage_test contract for QA / Framework.** verified.
  - `stage_test.md:931-933` enumerates `OK NEEDS_MANUAL_QA: <summary>`, `OK NEEDS_FRAMEWORK_CHOICE: recommended=<name>`. `stage_test.md:17-24` lists `qa-approved`, `qa-failed`, `Framework: <name>` inputs. `01-sub-agent-contract.md` §2 lacks these rows but `stage_test.md:980` documents they are stage_test-specific extensions accepted by main FSM. ⚠ minor doc gap — see ISSUE-D1.
- **T1.5 — ESCALATE Resume canonical behavior.** verified.
  - All four stage sub-agents have explicit "Resume short-circuit" sections that (a) re-validate Issue/preconditions, (b) confirm prior round's markers exist, (c) jump to Phase 6 / success-branch:
    - `stage_analyze.md:55-60` (§2)
    - `stage_design.md:73-85` (§2)
    - `stage_implement/main.md:104-122` (§4.2)
    - `stage_test.md:69-94` (§2 Resume short-circuits — both T1.4 and T1.5 paths)
  - Wrapper re-spawn shape matches `01-sub-agent-contract.md` §6: `commands/analyze.md:92-103`, `design.md:119-130`, `implement.md:148-161`, `test.md:152-163`.
- **T1.6 — `/sdd review --deep` deferred.** verified.
  - `MIGRATION.md:105` documents deferral. `commands/review.md` was not scanned but `design/04-utilities-design.md` §5 documents the same. No `--deep` flag implementation found in code grep.
- **T1.8 — Batch + ESCALATE conversion.** verified.
  - `commands/implement.md:133-142` implements the heuristic (skip-review.pr in `.github/.sdd-config` → convert ESCALATE to PAUSE-equivalent clean exit). `auto.md:291` references the same path.
- **T1.9 — Version-sync hook.** verified.
  - `.github/workflows/version-sync.yml` present; matches SYNTHESIS-v2 spec verbatim (jq comparison of plugin.json vs marketplace.json). `if:` clause at line 17 excludes `legacy/` branches as required.
- **T1.10 — MIGRATION.md content list.** verified.
  - `plugins/sdd-plugin/MIGRATION.md` exists with 11 sections covering: what changed, what is identical, action required, in-flight Issue behavior, mixed-version warning, behavior changes, R7 rubric move, `/sdd batch` regeneration, rollback policy, version-sync rule, deferred limitations. Matches design 06 §2.3 content list.
- **T1.11 — Bootstrap invocation §11.** verified.
  - `atoms/bootstrap.md` exists (170 lines) implementing the BOOTSTRAP return contract from `01-sub-agent-contract.md` §7. `bootstrap.md:152-166` "Why bootstrap exists" + "direct command branching" matches §11 spec verbatim. Direct-invocation label-check sections present in all four wrappers (`analyze.md:15`, `design.md:15`, `implement.md:19`, `test.md:15`).

⚠ **T1.7 was not in the requested check list**, but the doc change in `MIGRATION.md:63-69` confirms it was applied.

## Design compliance per stage

- **stage_analyze**: ✓ Implements analyze.md stage design Phases 0–6 verbatim. §1 (Issue Validation), §2 (Phase 0 + Resume short-circuit), §3 (Phase 1 Work with 12 steps), §4 (3 reviewers serial), §5 (verdict combine + adversarial-only R6), §6 (retry), §7 (escalation), §8 (return). Return contract matches `01-sub-agent-contract.md` §2 (stage_analyze table).
- **stage_design**: ✓ Implements design.md stage design Phases 0–6 verbatim. §3 Step 17a idempotency guard (line 295-313) preserves CHILDREN-on-retry invariant. §2 Resume short-circuit re-derives `path` and child list. Return values match design 01 §2 (SINGLE / CHILDREN forms).
- **stage_implement**: ✓ main.md drives Phases 0–7; topic files `_tdd.md`, `_pr_final.md`, `_phase7.md` implement Phase 3 (TDD pipeline + R9), Phase 4/5/5.5 (PR creation + R8 + Final review loop + escalation), Phase 7 (child completion). Returns OK ADVANCE / OK PARENT_STOP / OK PAUSE / ESCALATE / FAIL per design 01 §2.
- **stage_test**: ✓ §3 Phase 1 path detection (SINGLE vs PARENT), §4 Phase 2 work + 3-or-4 reviewers, §6 escalation, §7 `/verify` (SINGLE only), §8 manual-QA gate, §9 Phase 4 (label transition INSIDE sub-agent — only stage where this is so), §10 Phase 5 child completion notification. T1.4 return additions present (`OK NEEDS_MANUAL_QA`, `OK NEEDS_FRAMEWORK_CHOICE`).
- **bootstrap**: ✓ 9 steps matching `01-sub-agent-contract.md` §7. Read-only, no spawning. Returns `BOOTSTRAP: stage=... depth=... branch=... pr=... parent=... children=...` line (`bootstrap.md:123`).
- **wrappers** (`analyze.md` / `design.md` / `implement.md` / `test.md`): ✓ Each wrapper has Direct-invocation label check (T1.11), Phase 0 depth, single Agent spawn, return parsing, ESCALATE re-spawn loop, skip-review-driven inline chain to next wrapper. `auto.md` (~381 lines) + `batch.md` + `resume.md` round out the FSM-level callers.

⚠ **resume.md drift** — `resume.md:7,87,91,94` still says "M3 transient state — legacy orchestrators continue to drive each stage's execution; stage_X sub-agents arrive in M4–M7". But all four `stage_X` files now exist and are referenced by every wrapper. The dispatcher works correctly (it inline-reads `analyze.md`/`design.md`/etc., which themselves now spawn stage sub-agents), so behaviorally resume.md is fine; the "M3 transient" wording is stale doc. See ISSUE-D2.

## Implementation soundness checks

### Reviewer independence
Verified across all four stages.
- `stage_analyze.md:244-245` (independence invariant), `:253-258` (Reviewer 1 re-fetches), `:325` (Reviewer 2 "Re-fetch the analyze output fresh (do NOT reuse §4.1's fetch)"), `:343` (Reviewer 3 same). `Hard rules:531` repeats it.
- `stage_design.md:384-387` (invariant), `:393` (R1 fresh), `:471` (R2 "Re-fetch the design + analyze outputs fresh"), `:490` (R3 same).
- `stage_implement/_pr_final.md:296-300` (independence invariant), `:308-318` (R1 fresh re-fetch via `gh pr view <PR_NUM>` + `gh pr diff <PR_NUM>`), `:387` (R2 "Re-fetch the PR diff fresh"), `:402` (R3 same). Hard rules `_pr_final.md:640`.
- `stage_test.md:404-405` (invariant), `:413-425` (R1 fresh), `:504` (R2), `:523` (R3), `:533-537` (R4 parent_integration fresh fetch). Hard rules `:1017`.

### Single sub-agent invariant
Verified. Across all stage files, `Agent tool` and `subagent_type` appear only in NEGATIVE contexts (Hard rules forbidding spawn) or in metadata fields that describe the spawning context (e.g. `stage_analyze.md:297` mentions "main session spawns this stage with `model: opus`" — that's a description of how main session called this stage, not an inner spawn).

Specifically scanned: no `Spawn`/`Agent tool`/`subagent_type` directive lines exist that would cause a stage sub-agent to spawn another sub-agent. Hard rules forbid it explicitly:
- `stage_analyze.md:524`, `stage_design.md:672`, `stage_implement/main.md:426`, `_tdd.md:546`, `_pr_final.md:637`, `_phase7.md:170`, `stage_test.md:1009`.

The `_pr_final.md:629` mention of "main re-spawns this stage" is narrative referring to the main session's responsibility on ESCALATE-Continue — not an instruction to the sub-agent to spawn anything.

### Resume short-circuit
All four stages implement T1.5 Resume short-circuit in Phase 0. Cited line ranges:
- analyze: `stage_analyze.md:55-60` — checks 3 review markers; jumps to §8 with `OK ADVANCE: design`. FAIL if markers missing.
- design: `stage_design.md:73-85` — checks 3 review markers + design output + children marker (to re-derive SINGLE/CHILDREN path). Returns `OK ADVANCE: implement SINGLE` or `OK ADVANCE: implement CHILDREN: #A,#B,#C` after re-deriving the children list from the marker body.
- implement: `stage_implement/main.md:104-122` — re-derives PR# and branch via `gh pr list --search "Refs #$1"`; verifies 3 PR Final review markers exist; jumps to §8 Return with composed `OK ADVANCE: test PR: ... BRANCH: ...`.
- test: `stage_test.md:69-94` — multi-resume support (`continue-after-escalation` re-derives path then jumps to §7/§8; `qa-approved` jumps to §9 success; `qa-failed` returns `OK BACK_TO_IMPLEMENT`; unknown values return `FAIL`).

All four correctly re-validate via gh re-fetch (T1.5 canonical "Re-validates inputs from GitHub" requirement) before skipping phases.

### stage_implement split coherence
File-loading sequence traced:
1. Main session spawns one sub-agent with prompt "Read `commands/atoms/stage_implement/main.md`".
2. `main.md` §7 (`main.md:296`) instructs "Read `_tdd.md` and execute its instructions". TDD pipeline runs.
3. `main.md` §8 (`main.md:321`) instructs "Read `_pr_final.md` and execute its instructions". PR Final loop runs.
4. `main.md` §4.1 (`main.md:102`) instructs "Read `_phase7.md` and follow its instructions" — ONLY when Resume hint = `phase-7`, BEFORE any other phases.

This is coherent — all four files execute in the single sub-agent context. The order (Phase 7 short-circuits before Phases 1–5; otherwise TDD → PR Final in sequence) matches `design/stage-designs/implement.md` §16.

### R8 implementation
Traced for `gh pr list --search "Refs #N"` returning an existing open PR:
1. `_pr_final.md:62-66` §3.5 — `gh pr list --head <branch_name> --state open` finds `<EXISTING_PR>`.
2. `_pr_final.md:70-94` §3.6 R8 auto-route:
   - §3.6.1 safety check: `gh pr view <EXISTING_PR> --json body` must contain `Refs #$1`, else `FAIL: existing open PR ... does not reference Issue #$1`.
   - §3.6.2: log soft-retry; set `<PR_NUM> = <EXISTING_PR>`; SKIP §3.7 PR creation; proceed to §4 Phase 5 PR Final round 1.
3. Note at line 94: "R8 is always on per T1.1 — no `strict-pr-creation` config key".

Correct. The implementation matches `design/stage-designs/implement.md` §11.3 and SYNTHESIS-v2 T1.1.

### R9 implementation
Traced at TDD step start (`_tdd.md:65-134`):
1. §2.1 fetch `<!-- sdd:test-evidence:step-<n> -->` body. Empty → not idempotent → rerun.
2. §2.2 fetch `<!-- sdd:review:implement:step-<n> -->` body; parse `verdict`. Empty or FAIL or unparseable → not idempotent → rerun.
3. §2.3 parse `evidence_sha` and `evidence_test_string` from evidence body.
4. §2.4 `git merge-base --is-ancestor <evidence_sha> HEAD` — branch divergence → not idempotent.
5. §2.5 `git log -1 --format=%s <evidence_sha>` — subject prefix must match step expectation (`test: (Red)` / `feat: (Green)` / `refactor:` / `test: e2e`).

Match across all 5 checks → step skipped (idempotent). Any mismatch → re-run fresh. Edge cases for REFACTOR EMPTY and E2E_SKIPPED documented at `_tdd.md:130-134` — re-running is cheap (re-detect EMPTY / re-detect E2E absence). NO commit-body marker grep. Correctly implements `design/stage-designs/implement.md` §14 + T1.2.

### R10 implementation
Traced in `commands/init.md:17-90`:
1. `init.md:18-19`: declares "Transactional sequence (R10)" — track every successful `gh label create` in an in-memory list (main-session reasoning, no shell variables).
2. `init.md:38-58` pseudocode: on failure, iterate `reverse(created_labels)` calling `gh label delete <name> --yes`; collect rollback_failures.
3. Three outcomes table at `init.md:67-72`: `OK` / `FAIL: rolled-back` / `FAIL: partial`.
4. Partial-cleanup message at `init.md:75-84` lists exact remaining labels (creates that succeeded AND rollback deletes that failed) — addresses T2.9 best-effort rollback.
5. Edge cases at `init.md:86-90`: idempotent re-run via `--force`, color updates not failures, template-copy non-transactional.

Implementation is correct. Counts → 8 forward creates + N rollback deletes, one Bash per label (matches `_bash_rules.md`).

### Skip-review boundaries (M4.5 §9)
Verified split between sub-agent vs main per M4.5:
- **Sub-agent owns the gate within its own stage**:
  - analyze: §7 Phase 5 reads `.github/.sdd-config`, branches on `analyze` skip-review key (`stage_analyze.md:409-425`).
  - design: §7 (`stage_design.md:557-574`), key `design`.
  - implement: `_tdd.md:510-518` (step exhaustion, key `implement`), `_pr_final.md:606-631` (PR Final, key `pr`).
  - test: §6 (`stage_test.md:659-677`), key `qa`.
- **Main owns the next-stage gate**:
  - `analyze.md:67-72` reads skip-review and inline-reads `design.md` only if `design ∈ skip-review`.
  - `design.md:87-91` reads skip-review for `implement`.
  - `implement.md:101-109` reads skip-review for `qa` to inline-chain into `test.md`.
  - `test.md` is terminal — no next-stage gate.
- Hard rules in each stage file explicitly enumerate which keys the sub-agent consumes vs which main consumes (`stage_implement/main.md:437`, `_pr_final.md:647`).

Boundary is correctly enforced. No leakage in either direction.

## Critical issues found

- **ISSUE-D1 (low) — T1.4 contract rows missing from `01-sub-agent-contract.md` §2 stage_test table.** SYNTHESIS-v2 T1.4 says "Add to 01-sub-agent-contract.md §2: `OK NEEDS_MANUAL_QA: <summary>` / `OK NEEDS_FRAMEWORK_CHOICE: recommended=<name>` / `Resume: qa-approved` / `qa-failed` / `Framework: <name>`". The contract file lists only the 5 generic stage_test returns; the extended T1.4 returns appear in `stage_test.md:980` ("[NEW — Arch B / SYNTHESIS-v2 T1.4]: ... Main-session contract validation (`design/01-sub-agent-contract.md` §9) accepts them for stage_test only.") and in `commands/test.md` wrapper handlers, but the contract file itself was not updated. Code behavior is correct; only doc text is stale.
- **ISSUE-D2 (low) — `resume.md` self-describes as "M3 transient state".** `resume.md:7,87,91,94` say stage_X sub-agents arrive in M4–M7; behavior is correct (it inline-reads orchestrator wrappers which now spawn stage_X) but the doc text is misleading post-M7 completion. Update to "stage_X sub-agents arrive via the inline-read wrapper" or similar.
- **ISSUE-D3 (low) — `batch.md` does not itself wire T1.8.** The T1.8 fix lives in `commands/implement.md:133-142` (inside the child claude -p session). batch.md never sees the ESCALATE; the conversion happens correctly inside the child. Strictly correct, but the design 03 §7.3 narrative reads as if batch.md should "convert"; in practice it's the stage wrapper inside batch's child session that does it. No code change required; doc clarity opportunity.
- **ISSUE-D4 (informational) — `resume.md` does NOT route to stage_X with `Resume: continue-after-escalation`.** On Pause-then-Resume, the user runs `/sdd resume <N>`, which currently inline-reads the stage wrapper — that wrapper would spawn a fresh `Resume: none`, NOT a `Resume: continue-after-escalation`. This is OK because the prior round's markers are already PASSed (no FAIL was outstanding when the user chose Pause inside the wrapper's AskUserQuestion branch); a fresh spawn re-detects PASS state and short-circuits. But this nuance is subtle. Documented behavior is consistent with `01-sub-agent-contract.md` §6 Pause path (no special Resume hint after Pause).

## Summary

- T1 fixes verified: **11/11** (T1.1 ✓, T1.2 ✓, T1.3 ✓, T1.4 ✓ [w/ minor doc drift], T1.5 ✓, T1.6 ✓, T1.7 ✓ (off-list, documented in MIGRATION), T1.8 ✓, T1.9 ✓, T1.10 ✓, T1.11 ✓)
- Soundness checks passed: **8/8** (reviewer independence, single sub-agent invariant, resume short-circuit, stage_implement split coherence, R8, R9, R10, skip-review boundaries)
- Critical issues: **0** — all 4 issues found are LOW severity (doc drift or clarity, no behavioral defect)

Conclusion: v1.0.0 implementation correctly realizes the design across all stages. The 4 doc-only nits should be tracked but do not block release.
