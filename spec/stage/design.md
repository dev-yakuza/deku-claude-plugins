# Stage: Design

How-to design stage (translates analyze output into a technical plan, optionally splits into multiple PRs and creates child Issues). Sources: `commands/design.md`, `commands/atoms/design_work.md`, `commands/atoms/design_review.md`, `commands/atoms/design_adversarial.md`, `commands/ai-review-design-{completeness,quality,adversarial}.md`, `templates/en/output_design.md`, `templates/en/output_children.md`, `templates/en/output_child_issue.md`.

---

## 1. Stage Inputs

### Entry conditions
- `$1` — Issue number passed by `/sdd design $1`, `/sdd resume`, or inline auto-proceed from analyze. Validated as Issue (not PR) per Common Contracts §10. (`design.md` lines 11–13) [PRESERVE]
- **Precondition**: the Issue MUST have an `<!-- sdd:analyze:output -->` comment. Orchestrator fails fast here ("Run `/sdd analyze $1` first") to avoid a wasted subagent. Work atom re-checks and returns `FAIL: analyze output not found on Issue #$1` if missing. (`design.md` lines 15–17; `design_work.md` line 16) [PRESERVE]
- Label state: typically `sdd:analyze` (just transitioned) or `sdd:design`. Not strictly checked — design runs whenever invoked with valid precondition. [PRESERVE]

### Environmental dependencies
- `gh` CLI authenticated for current repo. [PRESERVE]
- `.github/.sdd-lang` (optional) — read by `design_work` Step 10 for template language. Falls back to Issue body detection, then `en`. (`design_work.md` line 84) [PRESERVE]
- `.github/.sdd-config` (optional) — read for `skip-review: design` semantics. (`design.md` Phase 1.5 and Phase 2) [PRESERVE]
- Issue labels — read in Phase 0 for depth detection. (`design.md` lines 23–25) [PRESERVE]
- Parent Issue context (if child) — fetched per Common Contracts → Parent/Child Issue Detection. (`design_work.md` Step 3) [PRESERVE]
- Past PRs — `gh pr list --search` for similar past PRs informs file organization, naming, architecture (preflight Medium tier). (`design_work.md` Step 0 / line 28) [PRESERVE]

### Depth
- Phase 0 reads labels, computes `default` / `deep` / `shallow` (same algorithm as analyze). (`design.md` line 23) [PRESERVE]

---

## 2. Stage Outputs

The design stage has **two output paths**, branched by the work atom's verdict on whether the design splits into a single PR or multiple PRs.

### Markers posted (common to both paths)
- `<!-- sdd:design:output -->` on the Issue (the design body) by `design_work`. (`design_work.md` Step 15 lines 117–127) [PRESERVE]
- `<!-- sdd:review:design:completeness -->` by `design_review` (role=completeness). (`design_review.md` Step 8) [PRESERVE]
- `<!-- sdd:review:design:quality -->` by `design_review` (role=quality). (`design_review.md` Step 8) [PRESERVE]
- `<!-- sdd:review:design:adversarial -->` by `design_adversarial`. (`design_adversarial.md` Step 8) [PRESERVE]
- `<!-- sdd:findings:json -->` … `<!-- /sdd:findings:json -->` block embedded inside each review comment per Common Contracts §5. [PRESERVE]

### Path: SINGLE (work atom returned `OK SINGLE`)
- Single design output comment on the parent Issue. No child Issues created.
- Label transition: parent Issue → `sdd:implement`. (`design.md` line 143) [PRESERVE]

### Path: CHILDREN (work atom returned `OK CHILDREN: #A,#B,...`)
Three artifacts produced by `design_work`:
1. `<!-- sdd:design:output -->` on the parent Issue.
2. One new child Issue per sub-feature in the PR split. Each child Issue body contains `<!-- sdd:child-issue -->` block with multilingual `Parent Issue: #<parent>` line (English `Parent`, Korean `상위 `, Japanese `親`). Title format: `[SDD Child] <parent title> - <sub-feature name>`. Labels applied at creation: `sdd:analyze` + `sdd:child`. (`design_work.md` Step 16) [PRESERVE]
3. `<!-- sdd:children:output -->` on the parent Issue — a children list table (one row per child). (`design_work.md` Step 16c) [PRESERVE]

Label transitions:
- Parent Issue → `sdd:implement`. Parent **pauses** here (does not advance to `sdd:test` itself; waits for all children to reach `sdd:done`, per Common Contracts §1). (`design.md` line 157) [PRESERVE]
- Each child Issue starts at `sdd:analyze` + `sdd:child` (set during `gh issue create --label`). (`design_work.md` line 140) [PRESERVE]

### State changes
- Self-review trace `<details>` block embedded inside `<!-- sdd:design:output -->` when blockers were fixed inline. (`design_work.md` Step 14) [PRESERVE]
- Comments updated in-place across retry rounds (duplicate-prevention pattern, Common Contracts §9). Round-to-round overwrites, not appends. [PRESERVE — but see Common Contracts §4 RETHINK on round preservation]

### Side effects NOT produced by design stage
- No branches, no commits, no PRs. Design is read-only against the working tree (it does post Issue comments and create child Issues, but no source-file edits). (`design_work.md` Hard rules) [PRESERVE]

---

## 3. Atom Inventory

| Atom | Role | Model (default / deep / shallow) | Key responsibility |
|---|---|---|---|
| `design_work` | Producer | opus / opus / opus | Generate Stage 2 design output. If PR split ≥ 2: also create child Issues + post children list. Handles first-round and retry mode. |
| `design_review` (role=`completeness`) | Reviewer | sonnet / opus / sonnet | Verify analyze→design coverage, file/symbol references, Testability presence. |
| `design_review` (role=`quality`) | Reviewer | sonnet / opus / sonnet | Feasibility, maintainability, risks, anti-patterns, testability quality. |
| `design_adversarial` | Reviewer (refuter) | opus / opus / sonnet | Actively REFUTE the design. Must find ≥1 weakness or justify why none. 8 stage-specific refutation angles. |

Model table source: `design.md` lines 33–37. Mirrors analyze stage's pattern (Common Contracts §3 via `01-config.md` §3). [PRESERVE]

All four atoms are single-subagent terminal workers: MUST NOT spawn subagents and MUST NOT call Agent/Skill tools (`design_work.md` Hard rules; `design_review.md` Hard rules; `design_adversarial.md` Hard rules). [PRESERVE — architectural invariant per Common Contracts §12]

---

## 4. Phase-by-Phase Behavior

### Phase 0: Depth label detection
- Read Issue labels via `gh issue view $1 --json labels --jq '[.labels[].name]'`. (`design.md` line 23) [PRESERVE]
- Decision:
  - Contains `sdd:review:deep` → depth = `deep`
  - Contains `sdd:review:shallow` → depth = `shallow`
  - Otherwise → depth = `default`
- Depth value selects models for each Agent spawn per the Phase 0 table. [PRESERVE]

### Phase 1: Design + AI Review Loop (max 3 rounds)
Each round = 1 work atom call → 3 parallel review atom calls → verdict combination → round decision. (`design.md` line 40) [PRESERVE]

**Round 1 — Step 1.1 (work atom spawn)**:
- `subagent_type: general-purpose`, `model: opus`, `description: design work for #$1`.
- Prompt instructs subagent to read `design_work.md` and execute for Issue `#$1`, returning `>>> RESULT <<<` line. (`design.md` lines 44–52) [PRESERVE]
- Parse the result:
  - `FAIL: <reason>` → orchestrator reports failure and stops; no reviews run. (line 54) [PRESERVE]
  - `OK SINGLE` → single-PR design posted. Continue to Step 1.2. **Remember path = SINGLE** for Phase 2. (line 55) [PRESERVE]
  - `OK CHILDREN: #A,#B,#C` → multi-PR design posted, children created. Continue to Step 1.2. **Remember path = CHILDREN with listed numbers** for Phase 2. (line 56) [PRESERVE]

**Round 1 — Step 1.2 (parallel review spawn)**:
- Three Agent tool calls in a **single message** for parallelism. (`design.md` line 58) [PRESERVE]
- Agent A: `design_review.md` with role `completeness`. Model per Phase 0 table.
- Agent B: `design_review.md` with role `quality`. Model per Phase 0 table.
- Agent C: `design_adversarial.md`. Model per Phase 0 table.
- All three reviewers operate **independently** — no cross-visibility of each other's verdicts. (`design.md` line 168) [PRESERVE]
- Each returns `>>> RESULT <<<` with `OK PASS` / `OK FAIL: <summary>` / `FAIL: <reason>`. [PRESERVE]

**Round 1 — Step 1.3 (round decision)**:
- Any reviewer returns `FAIL: <reason>` (atom error, not verdict) → report failure and stop. (`design.md` line 85) [PRESERVE]
- All three return `OK PASS` → reviews passed, break loop, proceed to Phase 2. (line 87) [PRESERVE]
- Any `OK FAIL` → combine summaries; check adversarial-only escalation (see §7); decide whether to retry. (lines 88–89) [PRESERVE]
- Reviews failed and round < 3 → spawn next round's work atom in **retry mode**. (line 93) [PRESERVE]
- Reviews failed and round == 3 → exit loop, go to Phase 1.5. (line 94) [PRESERVE]

**Rounds 2 & 3 (retry)**:
- Identical to Round 1 except `$2 = "retry"` is passed to the work atom. (`design.md` lines 98–103) [PRESERVE]
- Orchestrator does **NOT** fetch review comments or extract JSON itself — the atom self-fetches per `_review_helpers.md` Section C. This is the v0.36 main-session token-savings change. (line 93) [PRESERVE]
- Review atom prompts are unchanged between rounds. (line 105) [PRESERVE]
- **Children idempotency**: if Round 1 returned `OK CHILDREN`, the retry only updates the design output comment. Children are NOT re-created — `design_work` Step 16a guards by checking for existing `<!-- sdd:children:output -->`. (`design.md` line 107; `design_work.md` line 130) [PRESERVE — load-bearing]

### Phase 1.5: Round 3 Escalation Gate
Triggered only when round 3 also failed. (`design.md` line 109) [PRESERVE]

1. Fetch latest review findings (same extraction as retry mode). (line 113) [PRESERVE]
2. Render summary listing remaining `critical` and `major` findings with role label. (lines 114–120) [PRESERVE]
3. Branch on skip-review:
   - `design` in skip-review → log to Issue comment + orchestrator output, auto-continue to Phase 2 without prompting. Do NOT call `AskUserQuestion`. (lines 122–124) [PRESERVE]
   - Interactive → ask user: Continue / Pause / Stop. (line 126)
     - Continue → Phase 2.
     - Pause → orchestrator stops; resume via `/sdd resume <N>`.
     - Stop → exit cleanly. (lines 127–129) [PRESERVE]

### Phase 2: Branch on SINGLE vs CHILDREN

**Path: SINGLE** (Phase 1 returned `OK SINGLE`):
1. Check `skip-review: design` setting. (`design.md` line 134) [PRESERVE]
2. Skip-review set:
   - Log "User review skipped (skip-review: design). AI review already ran."
   - Update parent label to `sdd:implement`.
   - **Inline auto-proceed** — read `commands/implement.md` and execute in same main session. Do NOT spawn a subagent for the next stage. (lines 135–139) [PRESERVE — load-bearing: spawning would nest atoms]
3. Skip-review NOT set:
   - Summarize for user: round that passed, minor suggestions still on Issue, design comment location.
   - Ask for confirmation on technical approach + PR split.
   - On approval: update label to `sdd:implement`. User invokes `/sdd implement $1` or `/sdd resume $1`. (lines 140–143) [PRESERVE]

**Path: CHILDREN** (Phase 1 returned `OK CHILDREN: #A,#B,...`):
Work atom has already posted design output, created child Issues with `sdd:analyze` + `sdd:child` labels, and posted children list comment. Orchestrator now:
1. Check skip-review setting. (`design.md` line 154) [PRESERVE]
2. Update parent label to `sdd:implement`. (line 155) [PRESERVE — done regardless of skip-review]
3. Skip-review set:
   - **Stop here.** Parent reaches `sdd:implement` with children at `sdd:analyze`. The surrounding flow (`/sdd batch` or `/sdd auto`) picks up the children.
   - Log: "Children created (#A, #B, ...). Parent stopped at sdd:implement for batch/orchestrator to queue children." (lines 156–158) [PRESERVE]
4. Skip-review NOT set:
   - Summarize: design posted, children #A, #B, ... created, parent now at `sdd:implement`.
   - Ask: "Which child Issue would you like to start with?"
   - On selection: **inline-execute** `commands/analyze.md` for the selected child Issue in the same main session. Do NOT spawn a subagent. (lines 159–162) [PRESERVE — load-bearing]

---

## 5. Child Issue Creation

Triggered only on PR split ≥ 2 (work atom Step 9). Encapsulated entirely in `design_work` Step 16.

### When
- Step 16 fires only on the multi-PR branch.
- Single-PR branch skips Step 16 entirely (Step 17: "no child creation. Done."). (`design_work.md` line 156) [PRESERVE]

### How (per child)
1. Format child Issue body using `templates/{lang}/output_child_issue.md` with placeholder substitution:
   - `{{parent_issue}}` → `$1`
   - `{{sub_feature_description}}` → sub-feature description from design
   - `{{criteria_list}}` → markdown checkbox list from design
2. Write rendered body to `/tmp/sdd-child-issue-$1-<seq>.md` (Section F.4 mandatory because the body contains `\n#` patterns). (`design_work.md` lines 137–138) [PRESERVE]
3. Create the Issue: `gh issue create --title "[SDD Child] <parent title> - <sub-feature name>" --body-file /tmp/sdd-child-issue-$1-<seq>.md --label "sdd:analyze" --label "sdd:child"`. (line 140) [PRESERVE]
4. Capture new Issue number from command output URL. (line 142) [PRESERVE]

### Children list comment (parent)
After all children created:
- Marker: `<!-- sdd:children:output -->`
- Path: `/tmp/sdd-children-output-$1.md`
- Render via `templates/{lang}/output_children.md` (one table row per child)
- Post via Section F (duplicate-prevention search + create-or-update). (`design_work.md` Step 16c, lines 145–154) [PRESERVE]

### Multilingual parent reference
The `<!-- sdd:child-issue -->` block in each child Issue body contains `Parent Issue: #{{parent_issue}}` (per English template). For Korean and Japanese templates, the analogous strings are `상위 Issue: #...` and `親Issue: #...` (Common Contracts via `02-multilingual.md` §3). Downstream detection regex: `(Parent|상위 |親)Issue: #<number>`. (`design_work.md` Step 3 line 47) [PRESERVE]

### Idempotency
- Before re-creating children, Step 16a checks for `<!-- sdd:children:output -->` on the parent. If present → **skip child creation entirely**, only update design output. (`design_work.md` line 130) [PRESERVE — load-bearing]
- Consequence: across retry rounds 2 and 3, the same set of children persists. Retry can fix design body but cannot change the child set. (`design.md` line 107) [PRESERVE]

[RETHINK: idempotency is correct for "don't duplicate children", but it also means **a wrong PR split cannot be corrected by retry**. If reviewers flag the split, the work atom must work around the existing children rather than re-design. Consider: allow the atom to detect a "split changed" condition and either close-and-recreate or surface a hard error.]

### Hard rules
- `design_work` Hard rules: "If children already exist on this Issue (retry case), do NOT duplicate them — preserve existing children and only update the design output." (`design_work.md` line 188) [PRESERVE]

---

## 6. Decision Tables

### SINGLE vs CHILDREN trigger
The work atom decides at Step 9 ("Create the feature list with PR split. Determine if the design splits into multiple PRs (≥ 2) or is a single PR."). The decision is reflected in the work atom's return contract:

| Work atom decision | Return value | Phase 2 path |
|---|---|---|
| 1 PR | `OK SINGLE` | SINGLE path |
| ≥ 2 PRs | `OK CHILDREN: #A,#B,...` | CHILDREN path |
| Atom error (e.g. analyze output missing, gh failure) | `FAIL: <reason>` | Stop |

Source: `design_work.md` lines 162–175. [PRESERVE]

[RETHINK: the SINGLE/CHILDREN heuristic lives entirely inside the work atom's prompt — there is no explicit policy file. Reviewers can flag a bad split but cannot enforce a re-split (see §5 idempotency). Consider externalizing "when to split" criteria.]

### Round verdict combination (per round)
| completeness | quality | adversarial | Outcome |
|---|---|---|---|
| PASS | PASS | PASS | Loop exits, proceed to Phase 2 |
| PASS | PASS | FAIL | Adversarial-only FAIL — log warning, treat as FAIL, retry/escalate |
| FAIL | * | * | FAIL — retry/escalate |
| * | FAIL | * | FAIL — retry/escalate |
| Any `FAIL: <reason>` (atom error) | — | — | Orchestrator stops |

Source: `design.md` lines 86–89. [PRESERVE]

### Round retry decision
| Round | Verdict | Action |
|---|---|---|
| 1 or 2 | PASS | Exit loop → Phase 2 |
| 1 or 2 | FAIL | Spawn next round's work atom with `$2 = "retry"` |
| 3 | PASS | Exit loop → Phase 2 |
| 3 | FAIL | → Phase 1.5 escalation gate |

Source: `design.md` lines 92–94. [PRESERVE]

### Verdict per reviewer (severity → verdict)
| Findings severity | Verdict |
|---|---|
| any `critical` or `major` | FAIL |
| only `minor` or none | PASS |

Source: `design_review.md` lines 42–46; `design_adversarial.md` lines 41–44. [PRESERVE — matches Common Contracts §5]

---

## 7. AI Review Specifics

### Three parallel reviewers
- Spawned in a **single message** with 3 Agent tool calls to ensure concurrent execution. (`design.md` line 58) [PRESERVE]
- Independent contexts — no reviewer sees another's verdict during evaluation. [PRESERVE]

### Verdict combination logic
Performed by orchestrator after parsing all three `>>> RESULT <<<` lines:
- All three `OK PASS` → reviews passed.
- Any `OK FAIL` → reviews failed, combine summaries. (`design.md` line 88) [PRESERVE]
- Atom-level `FAIL: <reason>` from any reviewer → orchestrator stops. (line 85) [PRESERVE]

### Adversarial-only FAIL escalation
If `OK FAIL` came **only** from `design_adversarial` (completeness=PASS, quality=PASS, adversarial=FAIL):
- Log to user: "⚠ Adversarial reviewer alone identified critical/major issues. Surfacing for awareness." (`design.md` line 89) [PRESERVE]
- Then continue to Step 1.3 as a normal FAIL (still triggers retry). [PRESERVE]

[RETHINK: same dilemma as analyze — adversarial-only FAIL still retries as normal FAIL despite consensus from the other two reviewers passing. Consider separate threshold treatment.]

### Role-specific criteria

**Completeness** (`ai-review-design-completeness.md`):
- Requirements coverage (every analyze feature addressed)
- Impact scope completeness
- Constraints + risks identified with mitigations
- PR split is logical and each PR independently deliverable
- Architecture consistent with codebase patterns
- **Testability section present** — either `N/A (no external deps)` or full table. False `N/A` flagged as **critical**.
- Cross-stage check (analyze → design): features mapped, priorities preserved, out-of-scope items still out-of-scope
- Child Issue consistency (if child): architecture matches parent's PR-split rationale
- Codebase verification via Read/Grep — file path + symbol existence. Discrepancies → **major**. [PRESERVE]

**Quality** (`ai-review-design-quality.md`):
- Feasibility (buildable with codebase state; unstated prerequisites; realistic estimates)
- Maintainability (existing patterns vs unnecessary new abstractions; reversibility; interface design for change)
- Risk identification (concurrency, race, transactions, migration, downstream consumers)
- Test strategy realism
- Architectural anti-patterns (layer violations, implicit coupling, premature abstractions)
- Testability quality (DI seam existence; hard-to-test concerns addressed; hidden dependencies behind `N/A` → **major**)
- Codebase verification of pattern claims via Read/Grep. [PRESERVE]

**Adversarial** (`ai-review-design-adversarial.md`):
8 stage-specific refutation angles, each with explicit `rule_id`s:
1. Alternative-rejection rationale (`no-alternative-considered`, `parallel-structure-unjustified`)
2. PR split independence + ordering (`pr-order-hidden`, `pr-leaves-master-inconsistent`, `pr-boundary-by-convenience`)
3. Deferred mitigations (`critical-risk-deferred`, `fallback-defeats-mitigation`)
4. Codebase pattern claim verification (`pattern-not-found`, `pattern-misdescribed`, `layout-claim-incorrect`)
5. Cross-stage drift from analyze (`high-priority-feature-dropped`, `out-of-scope-silently-reintroduced`, `nfr-silently-dropped`)
6. Hidden complexity gloss phrases (`complexity-glossed`, `external-integration-underspecified`)
7. Testability seam existence (`testability-seam-missing`, `testability-seam-brittle`, `testability-na-but-side-effects-present`)
8. Data shape / contract drift (`contract-drift`, `schema-migration-unspecified`)

Mandatory codebase verification: verify 1–2 file paths cited in design exist; verify 1 architectural pattern claim by reading cited code. Must find ≥ 1 weakness or justify why none. (`ai-review-design-adversarial.md`; `design_adversarial.md` Step 5) [PRESERVE]

[IMPROVE: rule_id list is long and embedded in markdown. Could move to a structured registry shared with analyze stage rules for tooling/reporting.]

### Codebase exploration budget (reviewers)
- All three reviewer atoms MAY use Read/Grep/Glob (`_review_helpers.md` Section D). [PRESERVE]
- Budget: 15 Read / 10 Grep / 5 Glob per atom. [PRESERVE]
- **Mandatory** for adversarial — must verify ≥ 1 file path and ≥ 1 pattern claim. (`design_adversarial.md` Step 5 line 36) [PRESERVE]
- Write tool permitted **only** for rendering comment body to deterministic temp path per Common Contracts §9. Edit/NotebookEdit forbidden. [PRESERVE]

---

## 8. Edge Cases

### Retry mode with OK CHILDREN — idempotency of child creation
- Round 1 returns `OK CHILDREN: #A,#B,#C`. Reviews fail. Round 2 spawned with `$2 = "retry"`.
- Retry work atom self-fetches review findings (Section C of `_review_helpers.md`).
- Step 16a detects existing `<!-- sdd:children:output -->`, **skips Step 16b–16c entirely**, only re-renders + updates `<!-- sdd:design:output -->`.
- Children #A, #B, #C remain unchanged across rounds. (`design.md` line 107; `design_work.md` lines 130, 188) [PRESERVE — load-bearing]
- **Implication**: a PR split that reviewers want changed cannot be changed via retry. Work atom must adapt design text within the existing child structure. [PRESERVE — but see §5 RETHINK]

### Skip-review semantics (`design`)
- Skips the **user confirmation gate** only — AI review (Phase 1 + 1.5) always runs. (`design.md` line 166) [PRESERVE]
- In Phase 1.5, skip-review makes the escalation gate **auto-continue** without `AskUserQuestion`. (lines 122–124) [PRESERVE]
- In Phase 2 SINGLE path, skip-review auto-advances to `sdd:implement` AND inline-executes `commands/implement.md`. (lines 137–139) [PRESERVE — load-bearing: nested subagent forbidden]
- In Phase 2 CHILDREN path, skip-review **stops** at `sdd:implement` (parent paused, children at `sdd:analyze`) — it does NOT inline-execute analyze on a child. The surrounding flow (`/sdd batch`, `/sdd auto`) is expected to pick up children. (lines 155–158) [PRESERVE]

### Parent stops at sdd:implement (CHILDREN path)
- After `OK CHILDREN`, parent label is set to `sdd:implement` but the parent does NOT progress through implement → test by itself. (`design.md` line 155; Common Contracts §1) [PRESERVE]
- Parent remains paused until all children reach `sdd:done`, then advances to `sdd:test` (handled by the test stage / `/sdd auto`).
- This is the **parent-pause invariant** (Common Contracts §1). [PRESERVE]

### Atom-level FAIL vs review-verdict FAIL
- `FAIL: <reason>` (atom error) → orchestrator stops the entire stage. (`design.md` lines 54, 85) [PRESERVE]
- `OK FAIL: <summary>` (review verdict) → counts toward round verdict combination, not a stop signal. [PRESERVE]

### Issue Validation gate
Before any other step in `design.md`, validate `$1` per Common Contracts §10. If `$1` is a PR → stop immediately, no state changes. (`design.md` lines 11–13) [PRESERVE]

### Precondition fail-fast
The orchestrator pre-checks for `<!-- sdd:analyze:output -->` BEFORE spawning the work atom; if missing, reports "Run `/sdd analyze $1` first" and stops. The work atom also checks (defense in depth), returning `FAIL: analyze output not found on Issue #$1`. (`design.md` lines 15–17; `design_work.md` line 16) [PRESERVE]

### Self-review (blockers only) — `design_work` Step 12
Posting-blocking checks the work atom performs before posting:
- Marker `<!-- sdd:design:output -->` present
- Template required sections filled (file structure, PR split rationale, constraints)
- No `<empty>` / TODO / placeholder text left in
- PR split count (single vs ≥ 2) explicitly stated
- File paths cited are syntactically valid (no obvious typos)

Fix inline; record fixed blockers in `<details>` trace block (Step 14). Quality / completeness / risk evaluation are **NOT** done here. (`design_work.md` lines 88–96) [PRESERVE]

[IMPROVE: same self-review checklist pattern as analyze. DRY candidate.]

### Retry resolution check — `design_work` Step 13
Before posting the design comment, retry mode verifies every `critical` / `major` finding from `<retry-findings>` is addressed in the new design (file structure, PR split, testability, etc.) and mentions how. `minor` entries serve as supporting context. (`design_work.md` line 99) [PRESERVE]

### Language fixing
- `design_work` Step 10 reads `.github/.sdd-lang`. Falls back to Issue body detection, then `en`. (`design_work.md` line 84) [PRESERVE]
- Same template families used: `output_design.md`, `output_children.md`, `output_child_issue.md`. [PRESERVE]
- [IMPROVE: same persistence issue as analyze — language is re-detected each stage rather than persisted. Cross-stage drift possible.]

---

## 9. Cross-Stage Invariants

Downstream stages (`implement`, `test`) and child stages assume:

1. **`<!-- sdd:design:output -->` exists on the parent Issue** before `implement` starts.
   - `implement` atoms read it via `gh api ... --jq '.[] | select(.body | contains("sdd:design:output"))'`. [PRESERVE]
   - Cascade case: when `skip-review: design` is set on SINGLE path, the inline auto-proceed to `implement.md` guarantees the comment exists. (`design.md` line 139; `design_work.md` Step 15) [PRESERVE — load-bearing]

2. **On CHILDREN path, the children list `<!-- sdd:children:output -->` exists** and is queryable by `/sdd batch`, `/sdd auto`, and the test stage's parent integration logic.
   - Test stage uses this to determine when all children are `sdd:done` and the parent can advance to `sdd:test`. [PRESERVE]

3. **Each child Issue is born with labels `sdd:analyze` + `sdd:child`.**
   - `sdd:analyze` puts the child at the start of its own pipeline. (`design_work.md` line 140) [PRESERVE]
   - `sdd:child` is orthogonal (Common Contracts §3) — marks the Issue as parent-spawned so test stage can locate the parent. [PRESERVE]
   - Each child contains `<!-- sdd:child-issue -->` block in its body with `Parent Issue: #<parent>` (multilingual). Downstream stages detect this via the parent regex `(Parent|상위 |親)Issue: #<N>`. [PRESERVE]

4. **Parent stops at `sdd:implement` after CHILDREN creation.**
   - Parent does NOT progress on its own through implement/test until all children reach `sdd:done`. (Common Contracts §1 parent-pause invariant) [PRESERVE]

5. **The design output's PR-split structure is the contract for `implement` and `test`.**
   - SINGLE: implement produces 1 PR, test runs once.
   - CHILDREN: each child produces its own PR via its own `implement` run; parent's `test` stage runs a parent integration review after children merge. [PRESERVE]

6. **Review comments are queryable across rounds** via marker.
   - Retry mode self-fetches; duplicate-prevention keeps exactly one comment per marker (latest round). (Common Contracts §4 Update-in-place invariant) [PRESERVE]
   - [PRESERVE — but see Common Contracts §4 RETHINK on round-suffixed markers for audit]

7. **Findings JSON schema (Common Contracts §5)** present inside every review comment. [PRESERVE]

8. **Label transitions are the sole stage-completion signal.**
   - `sdd:implement` set → design stage complete (both paths). (Common Contracts §1, §2) [PRESERVE]

9. **Testability section (design output Section 5) informs implement's TDD plan.**
   - If `N/A` was honestly produced, implement-stage TDD plan has no mock/stub seam to wire.
   - If Testability has rows, each row's "Injection Point" must be createable by implement. Reviewers verified seam existence in Phase 1 (adversarial rule `testability-seam-missing`). [PRESERVE — cross-stage handoff via design content]

---

## Cross-references

- Common Contracts (markers, retry, bash rules, comment posting) → `spec/00-common-contracts.md`
- Skip-review semantics → `spec/01-config.md` §2
- Depth labels / model table → `spec/01-config.md` §3
- Multilingual parent regex → `spec/02-multilingual.md` §3
- Analyze stage (precondition source) → `spec/stage/analyze.md`
- Template output structure → `templates/{lang}/output_design.md`, `output_children.md`, `output_child_issue.md`
