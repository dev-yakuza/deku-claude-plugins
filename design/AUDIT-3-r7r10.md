# Audit 3: R7-R10 Behavioral Correctness

Audit of v1.0.0 implementation against design/05-rethink-decisions.md (R7-R10), design/SYNTHESIS-v2.md (T1.1 + T1.2), design/stage-designs/implement.md, and design/04-utilities-design.md.

---

## R7: Rubric file move

### File location check: PASS

Listing of `plugins/sdd-plugin/skills/sdd/commands/atoms/rubrics/` (per `ls -la` confirmation, all dated 6月 12 10:31):

```
analyze-adversarial.md       analyze-completeness.md       analyze-quality.md
design-adversarial.md        design-completeness.md        design-quality.md
implement-adversarial.md     implement-completeness.md     implement-quality.md
implement-step.md            parent-integration.md
test-adversarial.md          test-completeness.md          test-quality.md
```

Count: 14 files — matches the design (3 stages × 3 roles = 9, plus implement × 4-roles = 1 extra = 10, plus 4 in test = ...). Recount: analyze(3) + design(3) + implement(3) + test(3) + implement-step + parent-integration = 14. PASS.

### No orphaned `commands/ai-review-*.md`: PASS

`ls commands/ | grep -i ai-review` returned empty. No 0.x location files remain.

### Reference update check: PASS

`grep -rn "atoms/rubrics/"` shows 27 references; every consuming atom uses the new path:
- `commands/atoms/analyze_review.md:29,30` — analyze-completeness/quality
- `commands/atoms/design_review.md:35,36` — design-completeness/quality
- `commands/atoms/implement_review.md:5,43,44` — implement-completeness/quality
- `commands/atoms/test_review.md:33,34` — test-completeness/quality
- `commands/atoms/stage_analyze.md:251,316,332,545` — all 3 analyze rubrics
- `commands/atoms/stage_design.md:391,462,478,696` — all 3 design rubrics
- `commands/atoms/stage_test.md:411,494,511,531,1033` — all 3 test + parent-integration
- `commands/atoms/stage_implement/_tdd.md:409` — implement-step (Phase 3 TDD step review)
- `commands/atoms/stage_implement/_pr_final.md:306,382,394` — all 3 implement rubrics (PR Final)
- `commands/atoms/stage_implement/main.md:454` — aggregate reference list

`grep -rn "ai-review-"` in plugin code: only 2 hits in `MIGRATION.md:73-76` and `SPEC.md:224`, both documenting the *historical* move — zero live references.

### Audit findings

- No orphaned references. Every reviewer atom (`*_review.md`) AND every stage atom that reads rubrics inline (`stage_*.md`, `_tdd.md`, `_pr_final.md`) uses `<<SKILL_DIR>>/commands/atoms/rubrics/<name>.md` form.
- `<<SKILL_DIR>>` placeholder is consistent with the v0.35.0 token-economy convention.

**R7: PASS.**

---

## R8: empty-$3 + existing-PR auto-route

### Detection logic: PASS

Located in `_pr_final.md:61-94` (§3.5 + §3.6). The detection happens unconditionally inside Phase 4 (first-round mode entry), not gated on `$3` value. The probe:

```bash
gh pr list --head <branch_name> --state open --json number --jq '.[0].number'
```

(line 64). Branch outcomes (line 66-68):
- Empty → continue §3.6 (compose body + `gh pr create`).
- Has number `<EXISTING_PR>` → R8 auto-route to soft retry.

### Trace through scenarios

**Scenario 1: First-round mode (empty $3) + existing OPEN PR**  → Auto-route fires. §3.6.1 verifies `Refs #$1` in PR body, then §3.6.2 sets `<PR_NUM> = <EXISTING_PR>`, skips `gh pr create`, proceeds to Phase 5 PR Final round 1. **PASS — matches design §11.3.**

**Scenario 2: First-round mode + no PR**  → §3.5 empty branch → §3.7 normal `gh pr create` + capture `<PR_NUM>` from `gh pr view --json number`. **PASS — preserves first-round behavior.**

**Scenario 3: Retry mode ($3=retry) + existing PR**  → Phase 4 is entered (per `main.md` flow) but retry handling is in §4.2 (not §3). However, the §3.5 detection runs first; for a retry the branch already has a PR, so §3.5 routes to §3.6 (R8). Effectively merges retry and soft-retry paths — the design is to make them equivalent. The `main.md` §4.2 short-circuit (when `Resume: continue-after-escalation`) bypasses Phase 4 entirely. **PASS — design intent preserved; retry-mode and R8-route both end at §4 round 1.**

### T1.1 no-config-key verification: PASS

`grep -rn "strict-pr-creation"` returns 5 hits, **all of which document its non-existence**:
- `implement.md:184` — "no `strict-pr-creation` config key"
- `_pr_final.md:6,94,643` — three negative references in §1 / §3.6.2 note / Hard rules
- `main.md:330` — overview text

No assignment, no read, no parse. T1.1 fully honored.

### Defensive Refs check: PASS

`_pr_final.md:76-82` (§3.6.1) — `gh pr view <EXISTING_PR> --json body --jq .body`, then **must contain `Refs #$1`** or return:
```
FAIL: existing open PR #<EXISTING_PR> on branch <branch_name> does not reference Issue #$1
```
Marked `[PRESERVE — load-bearing safety per design/stage-designs/implement.md §11.3]`. Hard rule reinforced at `_pr_final.md:644`.

**R8: PASS.**

---

## R9: TDD step idempotency

### Mechanism (sha-from-evidence): PASS

`_tdd.md` §2 (lines 65-135) implements the canonical T1.2 mechanism:

- §2.1 (lines 73-81): fetch `<!-- sdd:test-evidence:step-<n> -->` from Issue comments.
- §2.2 (lines 84-91): fetch matching `<!-- sdd:review:implement:step-<n> -->` review marker; require PASS verdict (FAIL/unparseable → not idempotent).
- §2.3 (lines 94-101): parse `Commit: <sha>` and `TESTS: <p>/<t> FAILED: <f>` from the evidence body.
- §2.4 (lines 104-112): `git merge-base --is-ancestor <evidence_sha> HEAD` — confirms branch divergence detection.
- §2.5 (lines 116-127): verify commit subject matches step expectation (`test: ... (Red)`, `feat: ... (Green)`, `refactor: ...`, `test: ... e2e`).
- §2.6 (lines 129-135): edge cases for REFACTOR EMPTY + E2E_SKIPPED.

The §2 docstring at line 67 explicitly cites T1.2 and rejects the commit-body-marker path.

### T1.2 no commit-body marker: PASS

`grep -rn "sdd:tdd:step-"` returns **only one hit**: `MIGRATION.md:93`, which is a backward-compatibility note describing that *0.x-era* (pre-rewrite intermediate) experimental commits MAY have left such markers, with no functional impact. The active code path does **not** add or search such a marker. T1.2 fully honored.

### Edge case handling: PASS (with one observation)

**REFACTOR EMPTY (§5.4 + §2.6 + §7.1):**
- Fresh run: §5.4 detects empty diff via `git diff <sha_step_2> --quiet`, records `sha_step_3 = EMPTY`, **does NOT post test-evidence**, step-review short-circuits to PASS (§7.1, line 387).
- Resumed: §2.1 returns empty (no evidence marker exists). §2 returns `(false, null, null)` → re-runs step 3 fresh. §2.6 line 131 acknowledges the trade-off: "Acceptable. Defer the sentinel-marker optimization to v1.1." **Correct — design v1.0.0 chose simplicity.**

**E2E_SKIPPED (§6.4 + §2.6 + §7.1):**
- Fresh run: §6.4 records `e2e_skipped = true`, no commit, no evidence, no step-review. Step result `OK E2E_SKIPPED`.
- Resumed: §2.1 returns empty → §2 returns `(false, null, null)` → re-runs §6.2 detection (cheap; framework artifact glob). If still no E2E setup → re-skip. **Self-idempotent without explicit marker.** Line 132 explicitly documents this.

**First-time execution (no prior evidence):** §2.1 empty → `(false, null, null)` returned immediately → fresh execution path (§3 / §4 / §5 / §6). PASS.

**Crashed mid-step (evidence posted but no review):** §2.2 catches this — evidence present but review marker missing → `(false, null, null)` → re-runs step. Conservative but correct.

**Branch divergence (force-push, reset, fresh branch):** §2.4 ancestry check fails → re-runs. PASS.

Safety invariant preserved per line 134: "never skip if state uncertain. Re-running idempotent step costs ~5-15K tokens; running with stale state risks corruption."

**R9: PASS.**

---

## R10: /sdd init transactional rollback

### Tracking logic: PASS

`init.md:38-58` (Pseudocode block):
```
created_labels = []
for label in LABELS:
    Bash: gh label create <name> ... --force
    if exit code 0:
        append name to created_labels
    else:
        # rollback...
```

The list `created_labels` is described as held "in the main session's reasoning loop — no shell variables" (line 19, 61). This matches the SDD architecture's no-shell-state convention.

### Rollback on failure: PASS

Lines 47-50:
```
for name in reverse(created_labels):
    Bash: gh label delete <name> --yes
    if exit code != 0:
        append name to rollback_failures
```

- **Reverse order** rollback (LIFO). Sound.
- Per-label rollback delete is a separate Bash call. Aligns with `--yes` (non-interactive) for unattended ops (line 62).

### Failure-of-failure: PASS

Lines 51-57:
- `rollback_failures` empty → "FAIL: '<offending label>' (<stderr>). Rolled back: <list>. Repo unchanged."
- `rollback_failures` non-empty → partial-cleanup branch with explicit manual cleanup commands (lines 73-82):
  ```
  ⚠ Partial label state — manual cleanup required:
    gh label delete sdd:analyze --yes
    gh label delete sdd:design --yes
    ...
  ```
  Lists exactly labels remaining (line 84).

Matches SYNTHESIS-v2 T2.9 / FEA-C8 spec for best-effort rollback with manual recovery instructions.

### Edge cases

**All 8 succeed:** Loop completes without entering else branch. Line 58: `report "Labels: 8/8 OK. Templates: <N> copied. Language: <code>."` Outcome table line 69 confirms.

**Mid-way failure (e.g., label 5 fails):** Else branch fires for label 5; reverses through `[label_4, label_3, label_2, label_1]` deleting each. If all succeed → "Rolled back: 4 labels. Repo unchanged."

**Rollback itself fails partially (e.g., label_3 delete fails):** `rollback_failures = [label_3]`; partial-cleanup message lists the offending creates that weren't undone + the failed deletes. User receives explicit `gh label delete` commands.

**Idempotent re-run:** Line 88 explicitly preserves: `--force` succeeds silently on existing labels; rollback never triggers. Color updates via `--force` are not failures (line 89).

**Template-copy failures:** Out of scope for R10 (line 90 — filesystem writes are local/idempotent).

**R10: PASS.**

---

## Critical issues

None identified. All four behavioral additions are correctly implemented per the design.

Two minor observations (NOT blockers):

1. **R9 REFACTOR EMPTY resume re-runs the step** — the design (line 131) acknowledges and accepts this trade-off (a sentinel marker is deferred to v1.1). Wastes ~5-15K tokens on a resume of a previously-empty refactor but cannot corrupt state. Acceptable for v1.0.0.

2. **R8 detection runs even in retry mode ($3=retry)** — _pr_final.md §3.5 always probes for an existing PR. In retry mode the PR already exists, so the auto-route fires; net effect is identical to retry mode (both end at §4 round 1). This is design-intended (T1.1 unifies the paths), but reading `main.md` §4 / §4.2 in isolation might suggest separate routes. Documentation could be clearer, but behavior is correct.

---

## Summary

- **R7: PASS** — 14 rubric files moved cleanly; all 4 reviewer atoms + all 4 stage atoms + 2 stage_implement topic files reference the new path. No orphans.
- **R8: PASS** — Detection + soft-retry path + `Refs #$1` defensive check all present; T1.1 no-config-key invariant honored across 5 documented sites.
- **R9: PASS** — sha-from-evidence canonical mechanism implemented (§2.1–§2.6); T1.2 commit-body-marker path correctly absent from code (only documented as a historical curiosity in MIGRATION.md).
- **R10: PASS** — Tracking list, reverse rollback, failure-of-failure manual-cleanup branch, and `--force`-idempotent re-run all correctly implemented.
