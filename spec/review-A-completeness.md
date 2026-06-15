# Reviewer A: Completeness Findings

Audit of Phase A spec against the source under `plugins/sdd-plugin/skills/sdd/`. Focus: behaviors, edge cases, atom-level details, and hard rules that exist in source but are not preserved in spec. Self-review findings (G1–G11) are intentionally excluded.

---

## High-impact gaps (must include in spec before rewrite)

- **GAP-A1**: `tdd_step_review` `test-evidence-log-missing` finding from Step 2a is rendered as a separate gate; spec only catalogs it under §5a
  - **Source**: `plugins/sdd-plugin/skills/sdd/commands/atoms/tdd_step_review.md:37` (Step 2a posts `[major] test-evidence-log-missing` when the marker fetch is empty AND `$4 != EMPTY` AND `$5 != NONE`) and continues the review.
  - **What's missing**: The spec (`spec/stage/implement.md` §5 "Step-review consistency checks") lists the rule_id but does NOT document the Step 2a control flow — specifically that the reviewer does not return early when evidence is missing; it records the finding and continues to step 3 so other checks (step-criteria, etc.) still apply. A rewrite that "fails fast" here would silently lose the post-detection criteria evaluations.
  - **Where it should go in spec**: `spec/stage/implement.md` §5 (TDD pipeline) — explicitly note "evidence missing is captured as finding, not as early return".
  - **Severity rationale**: load-bearing — affects what findings appear on Round 1 vs Round 2 retry input; misimplementation silently degrades review coverage.

- **GAP-A2**: TDD step-review `test-evidence-summary-unparseable` finding (minor) is not in spec
  - **Source**: `tdd_step_review.md:68` defines `[minor] rule_id: test-evidence-summary-unparseable` when the log is present and authentic but a summary line cannot be identified. Explicitly: "Do not block on this — runners differ widely."
  - **What's missing**: `spec/stage/implement.md` §5 (Step-review consistency checks) catalogs `test-evidence-mismatch`, `test-evidence-implausible`, `red-log-shows-no-failure`, `test-evidence-log-missing`, but omits `test-evidence-summary-unparseable`. This is the explicit "we cannot find a summary line but log is plausible" fallback — a designed non-blocking escape hatch.
  - **Where it should go in spec**: `spec/stage/implement.md` §5.
  - **Severity rationale**: without this rule in the rule_id registry, a rewrite may either drop the escape hatch (making the reviewer block on every nonstandard format) or invent a different rule_id that breaks retry-mode parsers reading historical findings JSON.

- **GAP-A3**: Refactor "test count drift" downgrade-on-missing-prior-counts behavior not in spec
  - **Source**: `tdd_step_review.md:59`: for refactor (`$2==3`), if `<p>/<t>` differs from prior Green AND test files weren't touched → `[critical] refactor-changed-test-counts`. **Then explicitly**: "To check the prior Green counts, search Issue comments for the latest `<!-- sdd:review:implement:step-2 -->` block and parse the `Tests` field from its body. If unavailable, **downgrade to `[major]`**."
  - **What's missing**: `spec/stage/implement.md` §5 captures `refactor-changed-test-counts` as critical but does NOT preserve the "downgrade to major if prior counts unavailable" rule. Rewriter would lose the graceful degradation.
  - **Where it should go in spec**: `spec/stage/implement.md` §5 (the bullet about refactor count drift).
  - **Severity rationale**: load-bearing — `critical` vs `major` changes orchestrator FAIL/PASS verdict (any major → FAIL still, but it changes the recovery story when the round-1 step-2 review was lost). The rule's whole purpose is graceful fallback when prior comments were rotated out.

- **GAP-A4**: `/code-review` 🟣 Pre-existing handling in retry-mode atom (and spec)
  - **Source**: `implement.md:207` says 🟣 Pre-existing → ignored. But `implement_pr.md:140-151` retry-mode filter only documents 🔴/🟡 mapping; it does not explicitly say "skip 🟣 Pre-existing during translation to findings JSON". The orchestrator-side counting (§5.1.2) ignores them; the atom-side retry translation does not call this out.
  - **What's missing**: Spec doesn't preserve the asymmetry — orchestrator-side counts ignore 🟣 but atom-side retry-mode filter doesn't have an explicit "ignore 🟣 in translation". `spec/stage/implement.md` §6 Retry mode step 4c mentions the severity mappings but is silent on 🟣.
  - **Where it should go in spec**: `spec/stage/implement.md` §6 (Retry mode) — add 🟣 Pre-existing → skipped/ignored to the filter mapping.
  - **Severity rationale**: data-corruption risk — if retry atom includes 🟣 Pre-existing as `minor` findings, the work atom may waste cycles addressing issues that pre-date the PR (and that the orchestrator round verdict already ignores). Implementation drift between orchestrator and atom on the same emoji is a load-bearing constraint.

- **GAP-A5**: `implement_review` PATCH uses `-F body=@<path>` (form-data) NOT `--field body=@<path>`
  - **Source**: `commands/atoms/implement_review.md:64` uses `gh api ... -X PATCH -F body=@/tmp/...` (form-data flag). All other atoms use `--field body=@<path>`. This is the only atom in the entire source tree that uses `-F` instead of `--field`.
  - **What's missing**: Spec (§00-common-contracts §9 Section F.2, `spec/stage/implement.md`) consistently shows `--field body=@<path>`. The source's `-F` variant in `implement_review.md` is undocumented.
  - **Where it should go in spec**: `spec/00-common-contracts.md` §9 — note either (a) this is an inconsistency to normalize in rewrite, or (b) both `-F` and `--field body=@<path>` are valid.
  - **Severity rationale**: external contract — `gh api -F body=@<path>` and `--field body=@<path>` behave differently for some types. If rewrite picks one and the existing comment-update flow depends on the other, comment updates could silently corrupt body content. Worth verifying before standardizing.

- **GAP-A6**: `auto.md` Phase 3.4 cleanup ordering / "FIRST step the main session does" invariant is dropped in spec
  - **Source**: `auto.md:305`: cleanup "MUST be the FIRST step the main session does after the loop exits or after an in-loop fatal error".
  - **What's missing**: `spec/flow/auto.md` §9 lists the cleanup steps but does not preserve the "MUST be FIRST" ordering invariant. This is a hard rule: any post-loop reporting/logging that runs before cleanup risks leaving a stale `.sdd-config` on disk if the reporting code itself errors.
  - **Where it should go in spec**: `spec/flow/auto.md` §9 (Phase 3.4 Cleanup).
  - **Severity rationale**: load-bearing — invariant ensures the user's `.sdd-config` is restored even if subsequent reporting code crashes. Without this invariant in the spec, a rewrite may interleave reporting with cleanup and reintroduce the partial-state bug.

---

## Medium-impact gaps (worth adding for clarity)

- **GAP-A7**: `test_work` parent path mode-detection variable `HAS_CHILDREN` is implicit in spec
  - **Source**: `commands/atoms/test_work.md:18-23` introduces `HAS_CHILDREN` as the result of the children-comment search and switches paths on its emptiness. Retry-mode marker selection (`test_work.md:31-33`) also references it.
  - **What's missing**: Spec (`spec/stage/test.md` §1, §11.8) refers to "single/child path" vs "parent path" but does not name the source variable / control variable that drives the branch in retry mode. Without this binding, the rewrite may re-detect children inside retry context fetch and produce different marker sets.
  - **Where it should go in spec**: `spec/stage/test.md` §1 (Stage Inputs / Mode detection).
  - **Severity rationale**: medium — affects retry marker resolution correctness for parent-path test stage.

- **GAP-A8**: Test framework re-spawn signal "Framework: <name>" passed via prompt text only — no formal slot
  - **Source**: `test.md:67` notes the special-prefix `FAIL: no E2E test setup detected; recommended framework:` triggers re-spawn with "Framework: <name>" in the prompt. `test_work.md:154` only emits the FAIL prefix. There is no `$3` or explicit slot for the framework choice.
  - **What's missing**: `spec/stage/test.md` §9 mentions "framework choice is currently passed only via prompt text" as a `[RETHINK]` note — but the spec does not document the **exact prompt-handoff contract** (what string appears in the re-spawn prompt) so a rewrite can reproduce it. Currently it relies on the orchestrator narrative to inject `Framework: <name>` literally.
  - **Where it should go in spec**: `spec/stage/test.md` §9 (Test Framework Detection) — preserve the literal prompt-injection token.
  - **Severity rationale**: medium — without the literal token, re-spawn behavior is non-reproducible across the rewrite.

- **GAP-A9**: `implement_plan` PR title convention examples (`feat: <feature>`) and `git log -20` lookup
  - **Source**: `implement_pr.md:101-102`: title is `feat: <feature>` for single Issue, or matching repo convention discovered from `git log --oneline -20`. Same `git log` lookup appears in `implement_red.md:76`, `implement_green.md:80`, `implement_refactor.md:80`, `implement_e2e.md:78`.
  - **What's missing**: Spec (`spec/stage/implement.md` §9 Branch + Commit Conventions) mentions "All atoms inspect `git log --oneline -20`" but the breadth of usage (PR title, every commit) is not catalogued. The link between PR title generation and the `git log` lookup is not preserved.
  - **Where it should go in spec**: `spec/stage/implement.md` §9.
  - **Severity rationale**: medium — repo-convention conformance is user-facing; partial rewriting risks inconsistent PR titles vs commit messages.

- **GAP-A10**: `implement_pr` retry mode atom DOES use Read tool for self-fetch but spec doesn't preserve this constraint
  - **Source**: `implement_pr.md` retry mode reads PR diff, PR comments, and findings — but it cannot use Edit/Write except for the temp PR-comment body file (rules around line 209 implicit). The "fix kind" decision in step 5 implies code modification.
  - **What's missing**: `spec/stage/implement.md` §6 Retry mode does NOT explicitly state that this atom is the **only** atom in the implement stage allowed to **modify code** (Edit/Write production code) — all reviewer atoms and the TDD step atoms also modify code but per their own scope. The "production code modification authority" of each atom is implicit.
  - **Where it should go in spec**: `spec/stage/implement.md` §6 Retry mode.
  - **Severity rationale**: medium — clarifies the authority boundary; rewrite may accidentally fence retry-mode against code edits.

- **GAP-A11**: Section C "sort_by(.id) | last" canonical-latest-comment rule
  - **Source**: `commands/atoms/_review_helpers.md:180`: when querying review comments, the fetcher uses `sort_by(.id) | last` to pick the highest-id (latest) comment when duplicates exist — this is the canonical disambiguation rule because PATCH-then-PATCH could leave multiple bodies (though duplicate-prevention should make this unlikely).
  - **What's missing**: `spec/00-common-contracts.md` §9 / `spec/edge-cases.md` §17 doesn't document the `sort_by(.id) | last` resolution for the "multiple comments with the same marker" edge case. Even though duplicate-prevention should prevent this, the source defends against it.
  - **Where it should go in spec**: `spec/00-common-contracts.md` §9 (Section F duplicate-prevention) — note that retry-mode fetch uses `sort_by(.id) | last`, not raw `.[]`.
  - **Severity rationale**: medium — defensive but load-bearing; if rewrite uses `.[0]` or `.[-1]` without sort, may pick a stale body.

- **GAP-A12**: `_preflight.md` Section E retry detection slot is `$2` for analyze/design/test but `$3` for implement_pr (with "or `$3`" caveat for all implement atoms)
  - **Source**: `_preflight.md:138`: "Orchestrators detect retry by the presence of `$2` (or `$3` for `implement_pr`) — when retry feedback is provided, Step 0 is skipped." But this is incomplete — implement_red/green/refactor/e2e ALSO use `$3` for retry.
  - **What's missing**: Spec's `spec/edge-cases.md` §13 ("Step 0 Preflight Skip on Retry") says "Detection: orchestrators signal retry by presence of `$2` (or `$3` for implement_pr)". This understates — all 5 implement atoms (red/green/refactor/e2e/pr) use `$3`. The source's own _preflight.md is itself imprecise here.
  - **Where it should go in spec**: `spec/edge-cases.md` §13 — list complete set of `$3`-using atoms.
  - **Severity rationale**: medium — affects Step 0 skip logic across multiple atoms; rewrite that follows the spec's narrower claim would re-run Step 0 in red/green/refactor/e2e retry rounds, defeating the ~30K-token savings.

- **GAP-A13**: Adversarial reviewer "justify why" requirement is captured but not the failure mode
  - **Source**: All adversarial atoms (e.g. `analyze_adversarial.md:31`, `design_adversarial.md:39`, `implement_adversarial.md`, `test_adversarial.md:36`) require "Find at least one weakness; if none, justify why explicitly." This is in Section E of `_review_helpers.md:243`.
  - **What's missing**: Spec mentions the rule but doesn't catalog what happens when an adversarial atom finds nothing AND fails to justify. Is that a verdict regression? An atom-level FAIL? The source is silent on enforcement.
  - **Where it should go in spec**: `spec/edge-cases.md` §19 (Adversarial Single-FAIL Escalation) — document the "found nothing without justification" outcome.
  - **Severity rationale**: medium — affects how the rewrite handles adversarial outputs that lack required content.

- **GAP-A14**: Rate-limit detection two-stage jq fallback in batch script
  - **Source**: `batch.md:344-348`: first jq extract uses `select(.status != "allowed")` filter; if empty, falls back to a second jq without that filter when log contains rate-limit keywords (`grep -qi "rate.limit\|overloaded\|too many requests"`). This is a two-stage detection.
  - **What's missing**: `spec/flow/batch.md` §7.4.b documents the two-stage extract but does NOT preserve the **grep keyword guard** — that the second jq runs only if the log text matches `rate.limit | overloaded | too many requests` (case-insensitive). Without the guard, a non-rate-limit failure with a stray `rate_limit_event` could enter an infinite wait loop.
  - **Where it should go in spec**: `spec/flow/batch.md` §7.4.b.
  - **Severity rationale**: medium — operational correctness; rewrite without guard could hang the batch script on certain non-rate-limit failure modes.

- **GAP-A15**: `_preflight.md` Section B Item 2 deep-label override (`-50` instead of `-20`)
  - **Source**: `_preflight.md:50`: "For `sdd:review:deep` label, use `-50` instead of `-20`." Similar for Item 3 (line 68): "use `--limit 5`" instead of 3.
  - **What's missing**: `spec/01-config.md` §3 Depth Labels documents the model assignment table and "Heavy tier" for deep but does NOT preserve the **specific commit-log range / PR-search-limit overrides per depth**. These are operational knobs.
  - **Where it should go in spec**: `spec/01-config.md` §3 or `spec/edge-cases.md` §5.
  - **Severity rationale**: medium — affects context discovery breadth; load-bearing for the "deep = more context" promise.

---

## Low-impact gaps (nice-to-have)

- **GAP-A16**: PR body change-summary line count (3-5 lines) is a soft contract
  - **Source**: `implement_pr.md:57`: "Summarize changes (3-5 lines)".
  - **What's missing**: `spec/stage/implement.md` §6 mentions "change summary" without preserving the soft 3-5 line cap.
  - **Where it should go in spec**: `spec/stage/implement.md` §6.
  - **Severity rationale**: low — style guideline; unlikely to be load-bearing.

- **GAP-A17**: `[SDD Child]` title prefix is hard-coded
  - **Source**: `design_work.md:140`: child Issue title is `"[SDD Child] <parent title> - <sub-feature name>"`.
  - **What's missing**: `spec/stage/design.md` §5 documents this title format but does not flag the `[SDD Child]` literal as a user-discoverable contract — users may grep for it to find SDD-created children, separately from the `sdd:child` label.
  - **Where it should go in spec**: `spec/stage/design.md` §5.
  - **Severity rationale**: low — title cosmetic but could be searched on; rewriter renaming the prefix would break user habits.

- **GAP-A18**: `implement_red` "right reasons" failure-reason check
  - **Source**: `implement_red.md:57`: "Inspect output to confirm the failures are for the **right reasons** (assertion failures, not import errors)."
  - **What's missing**: `spec/stage/implement.md` §5 references the Red authenticity check (`red-tests-did-not-fail`, `red-log-shows-no-failure`) but does not preserve the work-atom-side "right reasons" self-check — assertion failure vs import error. A Red commit where the test "fails" due to a compile error is a false-Red.
  - **Where it should go in spec**: `spec/stage/implement.md` §5 or atom-level invariants.
  - **Severity rationale**: low — overlaps with the reviewer's `red-log-shows-no-failure` rule (which catches it post-hoc) but the work-atom-side preemptive check is a separate constraint.

- **GAP-A19**: `implement_refactor` `git diff --staged --quiet` check semantics
  - **Source**: `implement_refactor.md:75-77`: uses `git diff --staged --quiet` to detect empty refactor. Exit code 0 = no staged changes = skip commit, return `OK REFACTOR EMPTY`.
  - **What's missing**: `spec/stage/implement.md` §5 mentions `OK REFACTOR EMPTY` but not the exact detection mechanism. The rewrite could naively check `git status` or similar and produce different semantics.
  - **Where it should go in spec**: `spec/stage/implement.md` §5.
  - **Severity rationale**: low — implementation detail but the exit-code semantics matter for correct empty detection.

- **GAP-A20**: Issue templates: 4 categories matched by analyze stage type classification (`new feature` / `enhancement` / `bug fix` / `refactoring`)
  - **Source**: `templates/{lang}/issue_*.yml` has exactly 4 files (new_feature, enhancement, bug_fix, refactoring). `analyze_work.md:41` classifies into the same 4 types. The category set is intentionally aligned across the layers.
  - **What's missing**: `spec/02-multilingual.md` §4 lists the 4 template files but doesn't preserve the **alignment** with analyze's type classification. A rewrite that adds a 5th issue template would orphan it from the analyze classifier.
  - **Where it should go in spec**: `spec/02-multilingual.md` §4 or `spec/stage/analyze.md` §9 (Cross-Stage Invariants).
  - **Severity rationale**: low — discoverability of the constraint; not currently broken.

- **GAP-A21**: `gh pr list --search "Refs #$1"` is the cross-stage PR lookup convention
  - **Source**: Used by `implement_review.md:25`, `implement_adversarial.md:24`, `test_work.md:51`, `status.md:17`, `resume.md:35`, `review.md:43`. The `Refs #$1` body line is written by `implement_pr.md:70,84`. This is the cross-stage handoff.
  - **What's missing**: `spec/stage/implement.md` §11 invariants mention "PR exists" and "Refs #$1" but the spec doesn't elevate `gh pr list --search "Refs #$1"` to a canonical lookup pattern with its own section. It's the only mechanism linking PR back to Issue.
  - **Where it should go in spec**: `spec/00-common-contracts.md` (new section) or `spec/stage/implement.md` §11.
  - **Severity rationale**: low — important convention but well-distributed; not currently broken.

- **GAP-A22**: `implement_e2e` "Do NOT install new E2E frameworks" hard rule
  - **Source**: `implement_e2e.md:64,108`: "Do NOT install new E2E frameworks — that's a `/sdd test` stage decision with user confirmation." Hard rule.
  - **What's missing**: `spec/stage/implement.md` §10 (E2E framework absent) mentions `OK E2E_SKIPPED` but doesn't preserve the **prohibition** on the implement stage installing a new framework. The decision is intentionally deferred to test stage where the user can be asked.
  - **Where it should go in spec**: `spec/stage/implement.md` §10 (Edge Cases / E2E framework absent).
  - **Severity rationale**: low — clarifies stage boundaries.

- **GAP-A23**: `_test_evidence.md` raw output cap is 50,000 chars (~50k) and GitHub comment cap is ~65,000 chars
  - **Source**: `_test_evidence.md:34`: "GitHub issue comments cap at ~65,000 characters and a noisy test log can exceed that."
  - **What's missing**: `spec/stage/implement.md` §5 says "50k cutoff" but doesn't mention the GitHub ~65,000 char cap that motivates the truncation. A rewrite changing the truncation numbers needs to know the actual platform limit.
  - **Where it should go in spec**: `spec/stage/implement.md` §5 or `spec/stage/test.md` §8.
  - **Severity rationale**: low — preserves rationale for the magic numbers.

- **GAP-A24**: `analyze_review.md` and `design_review.md` reviewers do not currently use Section C retry self-fetch
  - **Source**: Review atoms (`analyze_review.md`, `design_review.md`, etc.) do NOT have retry mode — they always evaluate the **current** stage output, even on Round 2/3. Only work atoms self-fetch findings.
  - **What's missing**: Spec catalogs review atom behavior but doesn't explicitly state "reviewer atoms never have retry mode / never self-fetch prior verdicts" as an invariant. The orchestrator notes mention reviewers "always evaluate the current output" but the constraint that reviewers don't have `$2` retry parameter at all is implicit.
  - **Where it should go in spec**: `spec/00-common-contracts.md` §7 (Retry Mode Trigger) — add explicit "review atoms have no retry mode" caveat.
  - **Severity rationale**: low — clarifies architecture; rewrite may otherwise add reviewer-side caching.

---

## Summary
- High: 6 items
- Medium: 9 items
- Low: 9 items
- Total: 24 items
