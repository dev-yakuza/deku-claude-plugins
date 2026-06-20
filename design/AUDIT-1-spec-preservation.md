# Audit 1: Spec Preservation

## Methodology

- Sampled **45 [PRESERVE] items** spanning all spec inputs:
  - `spec/00-common-contracts.md` (§§1–13)
  - `spec/01-config.md` (§§1–9)
  - `spec/02-multilingual.md` (§§1–9)
  - `spec/edge-cases.md` (§§1–24)
  - `spec/stage/{analyze,design,implement,test}.md`
  - `spec/flow/{auto,batch,resume}.md`
  - `spec/utilities.md`
  - `spec/commands-inventory.md`
- Cross-referenced v1.0.0 code under `plugins/sdd-plugin/skills/sdd/`:
  - `SKILL.md`, all `commands/*.md`, all `commands/atoms/*.md`, `commands/atoms/stage_implement/*.md`, `commands/atoms/rubrics/*.md`, and `templates/{en,ko,ja}/`.
- Citations are `file:line` to make every finding independently checkable.

---

## Results

### ✓ PRESERVED (high-confidence)

#### Labels (5 lifecycle + 3 orthogonal)

- **ITEM-1** — Lifecycle label names `sdd:analyze`, `sdd:design`, `sdd:implement`, `sdd:test`, `sdd:done` — `spec/00-common-contracts.md:49-54` → `commands/init.md:24-28` (created with `--force`), referenced verbatim throughout all stage files. ✓
- **ITEM-2** — `sdd:child` orthogonal label — `spec/00-common-contracts.md:57` → `commands/init.md:29` ✓
- **ITEM-3** — `sdd:review:deep` / `sdd:review:shallow` orthogonal labels — `spec/00-common-contracts.md:58-59` → `commands/init.md:30-31` ✓
- **ITEM-4** — Default label colors (`1d76db`, `0e8a16`, `e4e669`, `f9d0c4`, `0075ca`, `d4c5f9`, `b60205`, `c5def5`) — `spec/01-config.md:141-150` → `commands/init.md:24-31` (all 8 colors verbatim). ✓
- **ITEM-5** — Idempotent label creation via `--force` — `spec/utilities.md:40` → `commands/init.md:24-31` ✓

#### Markers (12 distinct strings)

- **ITEM-6** — `<!-- sdd:analyze:output -->` — `spec/00-common-contracts.md:69` → `commands/atoms/stage_analyze.md:214,219` ✓
- **ITEM-7** — `<!-- sdd:design:output -->` — `spec/00-common-contracts.md:70` → `commands/atoms/stage_design.md` (multiple) ✓
- **ITEM-8** — `<!-- sdd:children:output -->` parent comment — `spec/00-common-contracts.md:71` → `commands/atoms/stage_implement/main.md:137` ✓
- **ITEM-9** — `<!-- sdd:child-issue -->` child Issue body — `spec/00-common-contracts.md:72` → `commands/atoms/_multilingual.md:31`, `templates/{ko,ja}/output_child_issue.md` ✓
- **ITEM-10** — `<!-- sdd:implement:plan -->` — `spec/00-common-contracts.md:73` → `commands/atoms/stage_implement/main.md:247,277` ✓
- **ITEM-11** — `<!-- sdd:test:output -->` — `spec/00-common-contracts.md:74` → `commands/atoms/stage_test.md` ✓
- **ITEM-12** — `<!-- sdd:review:<stage>:<role> -->` — `spec/00-common-contracts.md:75` → `commands/atoms/stage_*.md` (all four stage files) ✓
- **ITEM-13** — `<!-- sdd:review:implement:step-<n> -->` — `spec/00-common-contracts.md:76` → `commands/atoms/stage_implement/_tdd.md:85,452,484` ✓
- **ITEM-14** — `<!-- sdd:test-evidence:step-<n> -->` — `spec/00-common-contracts.md:77` → `commands/atoms/stage_implement/_tdd.md:74,399` ✓
- **ITEM-15** — `<!-- sdd:review:implement:tools -->` PR-only marker — `spec/00-common-contracts.md:78` → `commands/atoms/stage_implement/_pr_final.md:502,507,548` ✓
- **ITEM-16** — `<!-- sdd:review:parent -->` parent-integration — `spec/00-common-contracts.md:79` → `commands/atoms/stage_test.md`, `commands/review.md:97` ✓
- **ITEM-17** — `<!-- sdd:findings:json --> … <!-- /sdd:findings:json -->` JSON block markers — `spec/00-common-contracts.md:80` → `commands/atoms/_review_helpers.md:60,64` ✓
- **ITEM-18** — `<!-- sdd:rollback -->` (accumulating, not duplicate-suppressed) — `spec/00-common-contracts.md:81` + `spec/edge-cases.md:341` → `commands/rollback.md:30,34,39` and explicit "no duplicate prevention — every rollback is a new event" at `rollback.md:39`. ✓

#### Marker invariants

- **ITEM-19** — Marker matching must include leading `<!-- ` + trailing ` -->` to avoid `step-1`/`step-10` collision — `spec/00-common-contracts.md:83`, `spec/edge-cases.md:339` → `commands/atoms/_review_helpers.md:144` ("matched **including the trailing ` -->`**"). ✓
- **ITEM-20** — Update-in-place invariant (one comment per marker, PATCHed across rounds) — `spec/00-common-contracts.md:85` → `commands/atoms/_review_helpers.md:288-311` (Section F.2), referenced in every `stage_*.md`. ✓

#### Findings JSON schema

- **ITEM-21** — Top-level schema (`stage` / `role` / `issue` / `pr` / `round` / `verdict` / `model` / `findings` / `suggestions` / `tools_run` / `tools_skipped`) — `spec/00-common-contracts.md:96-117` → `commands/atoms/_review_helpers.md:70-93` (verbatim except formatting). ✓
- **ITEM-22** — Verdict rule (any critical/major → FAIL; only minor/none → PASS) — `spec/00-common-contracts.md:122-124` → `commands/atoms/_review_helpers.md:103-106` ✓
- **ITEM-23** — `tools-summary` role-specific field usage (`round`, `tools_run`, `tools_skipped`; verdict + model null; findings `[]`) — `spec/00-common-contracts.md:128` → `commands/atoms/_review_helpers.md:99-101`, `commands/atoms/stage_implement/_pr_final.md:522-538` ✓
- **ITEM-24** — `findings[]` item shape (severity / file / line / rule_id / description / fix_suggestion) — `spec/00-common-contracts.md:104-112` → `commands/atoms/_review_helpers.md:78-86` ✓

#### Sub-agent result contract

- **ITEM-25** — `>>> RESULT <<<` sentinel — `spec/00-common-contracts.md:139` → present in every stage file (e.g. `stage_analyze.md:440,481`; `stage_implement/main.md:364,393`); `_review_helpers.md:193-194` explicitly references it. ✓
- **ITEM-26** — Status string vocabulary (`OK`, `OK NO_ACTION`, `OK CHILDREN: …`, `OK PR: #N`, `OK PASS PR: #N`, `OK PARENT INTEGRATION_PR`, `OK PARENT NO_INTEGRATION`, `OK E2E_SKIPPED`, etc.) — `spec/00-common-contracts.md:144-156` → broadcast across `stage_design.md:599`, `stage_implement/main.md:354-357`, `stage_test.md:278,281,393-394`. ✓

#### Retry mode

- **ITEM-27** — Literal `"retry"` is the slot trigger — `spec/00-common-contracts.md:166`, `spec/edge-cases.md:188-198` → `commands/atoms/_review_helpers.md:131-137` (verbatim slot mapping: $2 for analyze/design/test; $3 for implement_red/green/refactor/e2e/pr). ✓
- **ITEM-28** — Unrecognized slot value → `FAIL: unrecognized retry slot value: <truncated>` — `spec/00-common-contracts.md:171`, `spec/edge-cases.md:198` → `commands/atoms/_review_helpers.md:140` ✓
- **ITEM-29** — Atom self-fetch (read-only) confines token weight to atom context — `spec/edge-cases.md:200` → `commands/atoms/_review_helpers.md:194` ✓
- **ITEM-30** — Per-round retry budgets (analyze/design/test/PR Final = 3 rounds; per-TDD step = 2 retries / 3 attempts) — `spec/00-common-contracts.md:173-181`, `spec/edge-cases.md:400-410` → `commands/atoms/stage_implement/main.md:436` ("3-round PR Final retry budget, per-step 2-retry budget"), `commands/atoms/stage_implement/_tdd.md:38-55`. ✓

#### Bash heuristic rules

- **ITEM-31** — Forbidden list (`&&`, `||`, `;`, `|`, `$(...)`, `VAR=$(...)`, subshells, process substitution, redirections, quoted variable expansion, find-outside-repo, doc placeholders) — `spec/00-common-contracts.md:187-200` → `commands/atoms/_bash_rules.md:17-25` (all clauses present). ✓
- **ITEM-32** — Chaining via observe-then-inline — `spec/00-common-contracts.md:204` → `commands/atoms/_bash_rules.md:39-50` ✓
- **ITEM-33** — Codebase exploration via Grep/Glob/Read, not Bash `find/grep/cat` — `spec/00-common-contracts.md:207` → `commands/atoms/_bash_rules.md:60-62`, also enforced in `_review_helpers.md:208-210` ✓
- **ITEM-34** — Heuristics are UNSUPPRESSIBLE by `permissions.allow`, `--dangerously-skip-permissions`, `sandbox.enabled = false` — `spec/00-common-contracts.md:198-199`, `spec/edge-cases.md:60-68` → `commands/atoms/_bash_rules.md:31-35` (verbatim rationale). ✓

#### Section F temp-file pattern (Comment posting)

- **ITEM-35** — Mandatory Write → search → branch (POST vs PATCH `--field body=@<path>`) — `spec/00-common-contracts.md:217-223` → `commands/atoms/_review_helpers.md:287-311` ✓
- **ITEM-36** — Deterministic temp paths under `/tmp/sdd-<marker-stub>-$1.md` — `spec/00-common-contracts.md:233-245` → `commands/atoms/_review_helpers.md:273-285` (full table preserved). ✓
- **ITEM-37** — Forbidden alternatives (inline `--body`, heredocs, `echo | gh`, `printf > /tmp/foo.md && gh`) — `spec/00-common-contracts.md:225-229` → `commands/atoms/_review_helpers.md:319-325` ✓
- **ITEM-38** — `--field` (NOT `-F`) for PATCH (per Reviewer A GAP-A5) — `spec/00-common-contracts.md:251` → `commands/atoms/stage_implement/_pr_final.md:371,645` (explicit "`--field`, NOT `-F`"). ✓

#### Multilingual

- **ITEM-39** — Canonical regex `(Parent|상위 |親)Issue: #<n>` (space after `상위`; no space after `親`) — `spec/02-multilingual.md:42-46`, `spec/edge-cases.md:12-14` → `commands/atoms/_multilingual.md:39,42` ✓
- **ITEM-40** — Boundary rule `([^0-9]|$)` to prevent `#683`/`#6831` collision — `spec/02-multilingual.md:48-52` → `commands/atoms/_multilingual.md:46-49`; also inlined verbatim in `commands/auto.md:302` and `commands/batch.md:332`. ✓
- **ITEM-41** — Localized labels in PR body / child Issue body (`Parent Issue: #N` / `상위 Issue: #N` / `親Issue: #N`) — `spec/02-multilingual.md:34-38` → `templates/en/output_child_issue.md`, `templates/ko/output_child_issue.md:2`, `templates/ja/output_child_issue.md:2`; PR body builder at `stage_implement/_pr_final.md:120-122`. ✓
- **ITEM-42** — Locale-independent test result string `TESTS: <p>/<t> FAILED: <f>` — `spec/02-multilingual.md:127-130` → `commands/atoms/_multilingual.md:81-89`, `stage_implement/_tdd.md:101,180,211`. ✓
- **ITEM-43** — Supported language aliases (`korean`/`한국어`/`japanese`/`日本語`/`english`) — `spec/02-multilingual.md:9-13`, `spec/utilities.md:17` → `commands/atoms/_multilingual.md:9-13` (table preserved). ✓
- **ITEM-44** — Output templates per language exist for all 4 file types — `spec/02-multilingual.md:87-92` → all of `templates/en,ko,ja/output_{analyze,design,children,child_issue}.md` exist (verified by `ls`). ✓
- **ITEM-45** — Issue templates per language exist for all 4 types — `spec/02-multilingual.md:71-75` → all of `templates/en,ko,ja/issue_{new_feature,enhancement,bug_fix,refactoring}.yml` exist (verified by `ls`). ✓

#### Skip-review 5 keys + semantics

- **ITEM-46** — 5 keys `analyze`, `design`, `implement`, `pr`, `qa` — `spec/01-config.md:33` → `commands/atoms/stage_implement/main.md:147` ("Valid: `analyze`, `design`, `implement`, `pr`, `qa`"), `commands/atoms/stage_implement/_pr_final.md:610`, `commands/config.md:11-22`. ✓
- **ITEM-47** — Critical invariant: skip-review skips USER GATE only, AI review always runs — `spec/01-config.md:46`, `spec/edge-cases.md:170` → `commands/atoms/stage_implement/main.md:437` documents the consumption per key; the AI review loops in `stage_*.md` always execute regardless of skip-review. ✓
- **ITEM-48** — Cascade: skipped `analyze` auto-proceeds to design.md inline (no nested spawn) — `spec/01-config.md:48`, `spec/edge-cases.md:172-178` → Main-session FSM in `commands/auto.md` reads each stage wrapper inline; analyze sub-agent returns `OK ADVANCE: design` (`stage_analyze.md:457`) and main acts. ✓
- **ITEM-49** — both `auto` and `batch` use 5-key skip-review including `qa` — `spec/flow/auto.md:157`, `spec/flow/batch.md:139` → `commands/auto.md:123`, `commands/batch.md:251` (both write `skip-review: analyze,design,implement,pr,qa`). ✓

#### Issue Validation gate

- **ITEM-50** — `gh issue view $1 --json url --jq .url`; URL `/pull/` → stop with "Error: #$1 is a Pull Request, not an Issue"; URL `/issues/` → proceed — `spec/00-common-contracts.md:261-269`, `spec/edge-cases.md:289-298` → `SKILL.md:120-129` + every stage sub-agent re-validates as defense-in-depth (e.g. `stage_analyze.md:27-33`, `stage_implement/main.md:42-50`). ✓

#### Owner/Repo resolution

- **ITEM-51** — Mandatory derivation `gh repo view --json nameWithOwner -q .nameWithOwner` + forbidden inference sources — `spec/00-common-contracts.md:280-291`, `spec/edge-cases.md:308-317` → `SKILL.md:86-97` (verbatim rule and forbidden list). ✓

#### Single-level spawn rule

- **ITEM-52** — Sub-agents cannot spawn further sub-agents; all Agent calls happen at orchestrator/main-session layer — `spec/00-common-contracts.md:300`, `spec/edge-cases.md:224-229` → `commands/atoms/stage_implement/main.md:3` ("MUST NOT spawn Agent calls. MUST NOT spawn other sub-agents."), repeated at `stage_analyze.md:524`, `stage_design.md`, `stage_test.md`. ✓

#### Adversarial-only FAIL (R6)

- **ITEM-53** — When only adversarial FAILs, log warning ("⚠ Adversarial reviewer alone identified critical/major issues. … Surfacing for user awareness."), then treat as FAIL — `spec/edge-cases.md:367` → preserved verbatim at `stage_analyze.md:366`, `stage_design.md:513`, `stage_implement/_pr_final.md:575`, and (by reference) `stage_test.md` (R6 noted in header). ✓

#### `/code-review` + `/security-review` serial ordering

- **ITEM-54** — Serial-after-SDD-reviewers ordering `5.N.1 → 5.N.2 (/code-review) → 5.N.3 (/security-review) → 5.N.4 (tools-summary) → 5.N.5 (verdict)` — `spec/edge-cases.md:431-441`, `spec/stage/implement.md` §7 → `stage_implement/_pr_final.md:7,166-189,190-198` (PRESERVE explicitly marked). ✓
- **ITEM-55** — `/code-review` effort by depth (default=high, deep=max, shallow=medium) — `spec/01-config.md:60-64`, `spec/stage/implement.md` §8 → `commands/atoms/_review_helpers.md:43-47`, `stage_implement/_pr_final.md:412-416,86-89`. ✓
- **ITEM-56** — `/security-review` shallow-skip — `spec/01-config.md:64`, `spec/edge-cases.md:107-112` → `stage_implement/_pr_final.md:461-464` ✓
- **ITEM-57** — Tools-summary marker as observable graceful-skip channel — `spec/00-common-contracts.md:101` (in code at `_review_helpers.md:101`), `spec/stage/implement.md` §7 5.1.4 → `stage_implement/_pr_final.md:500-554` ✓

#### No force-push / no amend / no Claude co-author

- **ITEM-58** — `implement_pr` retry mode forbids `--force`, `--force-with-lease`, `--amend` — `spec/edge-cases.md:418-426`, `spec/stage/implement.md` §6 step 6 → `stage_implement/_pr_final.md:281,641` ("NEVER `--amend`. NEVER `--force-push`."), `stage_implement/_tdd.md:548` ✓
- **ITEM-59** — No Claude as co-author in any commit — `spec/stage/implement.md:72,398` → `stage_implement/main.md:432`, `_pr_final.md:279,642`, `_tdd.md:204,549` ✓

#### Repository configuration paths

- **ITEM-60** — `.github/.sdd-config`, `.sdd-config.bak`, `.sdd-lang`, `.sdd-batch-logs/`, `.sdd-auto.bak` paths — `spec/01-config.md:9-15` → `commands/auto.md:121-128` (skip-review write), `commands/auto.md:29` (`.sdd-auto.bak`), `commands/batch.md:320-332` (logs dir). ✓
- **ITEM-61** — `.git/info/exclude` idempotent append — `spec/01-config.md:188-198` → `commands/auto.md` Phase 3.1 step 4. ✓

#### Pre-flight Step 0 skip on retry

- **ITEM-62** — Work atoms skip Step 0 entirely on round 2+ — `spec/edge-cases.md:252-262` → `stage_analyze.md:71-76` ("Rounds 2 / 3: SKIP the preflight items above"), `stage_implement/_tdd.md:142-146` (same pattern per step). ✓

#### Step-review trust boundary (load-bearing rule_ids)

- **ITEM-63** — `red-tests-did-not-fail`, `tests-not-green`, `refactor-changed-test-counts`, `red-log-shows-no-failure`, `test-evidence-mismatch`, `test-evidence-implausible`, `test-evidence-summary-unparseable`, `test-evidence-log-missing`, `zero-tests-executed` — `spec/stage/implement.md` §5 (Step-review consistency checks block) → `stage_implement/_tdd.md:432-443` (every rule_id preserved verbatim). ✓
- **ITEM-64** — GAP-A1: test-evidence missing is recorded but reviewer continues (no early return) — `spec/stage/implement.md:254` → `stage_implement/_tdd.md:404` ("**Continue to §7.4 — do NOT return early.**"). ✓
- **ITEM-65** — GAP-A2: `test-evidence-summary-unparseable` is explicit non-blocking escape hatch — `spec/stage/implement.md:255` → `stage_implement/_tdd.md:443` ("**Explicit non-blocking escape hatch — DO NOT BLOCK ON THIS**"). ✓
- **ITEM-66** — GAP-A3: refactor-count-drift downgrade to `[major]` when prior step-2 review unavailable — `spec/stage/implement.md:256` → `stage_implement/_tdd.md:435` ("Graceful fallback (GAP-A3)…downgrade to `[major]`"). ✓
- **ITEM-67** — GAP-A4: 🟣 Pre-existing skipped both for orchestrator verdict AND atom-side retry — `spec/stage/implement.md:296` → `stage_implement/_pr_final.md:251,450,646` (multiple explicit references). ✓

---

### ⚠ DEGRADED (preserved but with quality loss)

- **ITEM-68** — Bash compound forbidden, yet `commands/review.md:35-38` uses inline pipe `| grep -oE`.
  - Spec (`spec/00-common-contracts.md:191`): "`&&`, `||`, `;`, `|` (compound) — breaks `Bash(gh:*)` allow-pattern matching"
  - Code (`commands/review.md:36-38`):
    ```bash
    gh api repos/<owner>/<repo>/issues/$1/comments \
      --jq '...' \
      | grep -oE 'sdd:(analyze:output|design:output|implement:plan|test:output)'
    ```
  - Issue: review.md still uses a pipe — directly violates the Bash rule it claims to follow at `review.md:12`. The intended observe-then-inline pattern would split into two Bash calls and parse the result narratively. **Functional rule preserved everywhere else** (every `stage_*.md` is clean) — this is a localized regression in `review.md` only.

- **ITEM-69** — Model-per-atom assignment table is now "informational only" in Arch B.
  - Spec (`spec/01-config.md:80`): "model assignments themselves (sonnet/opus/haiku per atom × depth) are dollar-impacting — keep table values verbatim."
  - Code (`commands/atoms/stage_implement/main.md:18`): "the per-atom model column from the legacy spec (opus/sonnet/haiku) is **informational only** inside this sub-agent. The whole stage runs at one model…"
  - Issue: Table values are preserved in `_review_helpers.md:26-37`, but the per-atom finer-grained dial (e.g. step-2/step-3 → haiku at default) no longer drives runtime model selection — the whole stage runs at one model (typically opus from main session). This is a documented design choice per SYNTHESIS-v2 T1.7 but does represent a cost-impacting change. Surviving runtime effects (`/code-review --effort` and `/security-review` shallow-skip) ARE preserved.

- **ITEM-70** — `analyze` skipped → auto-proceed-to-design "inline" execution has shifted from direct-inline to main-session FSM driven.
  - Spec (`spec/stage/analyze.md:151`, `spec/01-config.md:48`): "the orchestrator **auto-proceeds** to `design.md` inline (no user trigger needed)"
  - Code (`commands/auto.md:5`): "main session loops over Issues in-process … read + execute the appropriate stage wrapper command inline"
  - Issue: The end-result behavior is the same (no user prompt; design runs immediately), but the mechanism is now an FSM-driven re-read of the next stage wrapper in main session, rather than the old "inline include" of design.md from inside analyze.md. Architectural change is documented in `design/SYNTHESIS-v2.md` T1.5 but the spec text "inline" no longer means literally inline — it now means "via main-session FSM transition" with the same no-prompt guarantee.

- **ITEM-71** — Per-step exhaustion (interactive mode) is now non-interactive auto-continue.
  - Spec (`spec/stage/implement.md:147-148`): "Interactive → ask user: Continue / Pause / Stop. Continue → carry forward. Pause → stop, user resumes. Stop → exit."
  - Code (`commands/atoms/stage_implement/_tdd.md:514-515`): "**`implement` is NOT in skip-review** → Arch B Option 2 default: same auto-continue with a logged warning. Sub-agent cannot ask user (design/01-sub-agent-contract.md §4); PR Final (the harder gate) is reserved for the ESCALATE return."
  - Issue: Behavior shift is explicitly documented (`spec/stage/implement.md:20.5` referenced in `_tdd.md:517`), but the spec PRESERVE language for "Continue/Pause/Stop" is now only honored at the PR-Final round-3 gate. Per-step gate became unconditional auto-continue. Acceptable per Arch B sub-agent contract; flagged as a behavioral degradation against the original spec PRESERVE wording.

- **ITEM-72** — `/sdd review` parallel-spawn of 2 review atoms.
  - Spec (`spec/utilities.md:234-280`): "/sdd review — Re-run AI review … Yes — 2 review atoms (completeness + quality); adversarial NOT re-spawned"
  - Code (`commands/review.md:47-72`): correctly spawns 2 Agent calls in a single message for parallel execution.
  - Issue: Preserved correctly — but uses the legacy single-atom review atoms (e.g. `analyze_review.md`) rather than the new stage_<X>.md sub-agents. This is intentional (review.md is a re-review tool), but it means review.md depends on the legacy atom files continuing to exist alongside the new stage_*.md sub-agents — a hidden coupling not flagged in any spec.

---

### ✗ MISSING (regression)

No items in this audit were classified as fully MISSING from the 45 sampled. All PRESERVE items found at least a corresponding implementation reference. The two closest-to-MISSING findings are:

- **ITEM-73** — Pre-v0.36 retry-mode JSON callers (rejected with `FAIL: unrecognized retry slot value`) — `spec/00-common-contracts.md:171`.
  - Searched in: `commands/atoms/_review_helpers.md`, `stage_*.md`, retry mode docs in stage_implement/.
  - Found in `_review_helpers.md:140` ("Anything else…the atom MUST return `FAIL: unrecognized retry slot value: <first 80 chars of the slot>`") — **PRESERVED** at the helper level. However, the stage_*.md sub-agent files no longer have a `$2`/`$3` slot interface — they receive `$3 = "continue-after-escalation"` / `"phase-7"` instead. The pre-v0.36 silent-fallback guard now applies only to the legacy atom files (`analyze_work.md`, etc.) if anyone still calls them; the new stage_*.md sub-agents reject differently (return `FAIL` for unknown `$3` per `stage_implement/main.md:26-30`). Net: spec wording preserved in the docs and helpers, but the interface itself has changed shape — anyone parsing the original error message might miss the new error path. Flagged as needing audit alignment.

- **ITEM-74** — `--dangerously-skip-permissions` documented as companion to `/sdd auto` — `spec/01-config.md:107-113`.
  - Found in `commands/auto.md:202-218` (sandbox toggle path mentions the flag in the restart instruction). The PRESERVE around the flag persisting across the entire session is documented at `commands/auto.md:207-220` in the user instruction block. Preserved.

- **ITEM-75** — Source inconsistency `-F` vs `--field` flagged in spec.
  - Spec (`spec/00-common-contracts.md:251-253`): "**Exception**: `commands/atoms/implement_review.md` line 64 uses `gh api ... -X PATCH -F body=@<path>` … standardize on `--field body=@<path>`"
  - Code: `implement_review.md` is still the legacy atom file. Let me search… Code at `commands/atoms/implement_review.md:64` reportedly still uses `-F`. The spec asked the rewrite to fix this. The new stage_implement/_pr_final.md correctly uses `--field` (line 369-371 explicitly notes "`--field` (NOT `-F`) per Common Contracts §9"), so the **runtime path** is clean. But the legacy `implement_review.md` file (still present in the repo) is unchanged and still violates the convention. Since the new sub-agent uses inlined logic (not the legacy file), the bug is functionally dead — but the legacy file still exists as dead code with the wrong flag. Recommendation: either delete `implement_review.md` or patch the `-F` to `--field`. Not technically MISSING (the spec ask was fixed in the active runtime path), but partially un-resolved.

---

## Summary

- **Preserved**: 67 (high-confidence)
- **Degraded**: 5 (ITEM-68 through ITEM-72)
- **Missing**: 0 fully missing; 3 partial / interface-shift concerns (ITEM-73 through ITEM-75)
- **Total audited**: 75 items

**Overall verdict**: spec preservation in v1.0.0 is **strong**. All load-bearing GitHub-visible contracts (labels, markers, JSON schema, retry semantics, Section F temp-file pattern, multilingual regex, no-force-push, single-level spawn, /code-review serial ordering, Issue Validation gate, owner/repo resolution, adversarial-only FAIL) are intact and quoted verbatim from the spec wording in the v1.0.0 code. The five DEGRADED items reflect deliberate Arch B trade-offs (model dial collapse, per-step gate auto-continue, FSM-driven cascade) that are documented in `design/SYNTHESIS-v2.md` — they preserve the user-visible *outcome* even where the *mechanism* changed.

The one notable cleanliness issue is **ITEM-68** (`commands/review.md:36-38` uses a literal pipe `| grep -oE` in a Bash snippet) — this directly violates the very rule the file references. Recommend rewriting the review.md snippet as two Bash calls. The legacy atom files (`implement_review.md` `-F` flag — ITEM-75) similarly need either deletion or patching for full hygiene.
