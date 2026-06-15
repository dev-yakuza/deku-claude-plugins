# stage_design — Sub-agent Design

Per-stage internal design for the **design** stage under Arch B (stage-as-subagent). Inlines `design_work` + `design_review` (completeness/quality) + `design_adversarial` into one sub-agent body. Reviews run **serially** (single-level spawn rule). Two output paths: SINGLE-PR or CHILDREN. Child-Issue creation is idempotent across retry rounds.

Sources: `spec/stage/design.md`, `spec/00-common-contracts.md`, `spec/02-multilingual.md`, `design/00-architecture.md`, `design/01-sub-agent-contract.md`, `design/02-file-layout.md`. Companion: `stage-designs/analyze.md`.

---

## 1. Sub-agent inputs

Spawned by the main session via Agent tool (`subagent_type: general-purpose`). Prompt template per `01-sub-agent-contract.md` §1:

```
Read <<SKILL_DIR>>/atoms/stage_design.md and execute its instructions
for Issue #<N>.

Inputs:
  Issue: #<N>
  Depth: <default|deep|shallow>
  Resume: <none|continue-after-escalation>     # set by main on re-spawn after ESCALATE
```

### Required
- `Issue: #<N>` — already validated as Issue (not PR) by main session per Common Contracts §10. Sub-agent re-validates defensively.
- `Depth: <default|deep|shallow>` — already resolved by main session from labels (`sdd:review:deep`, `sdd:review:shallow`, default). Sub-agent does not re-detect from labels; it accepts the value verbatim.

### Optional
- `Resume: continue-after-escalation` — only set when main session re-spawns this stage after a user-confirmed Continue at the escalation gate (Phase 5). Sub-agent skips Phases 1–4 entirely, goes directly to Phase 6.

### Precondition (fail-fast, before any work)
Issue MUST already have `<!-- sdd:analyze:output -->`. If missing:
```
>>> RESULT <<<
FAIL: analyze output not found on Issue #<N>
```
Main session will report "Run `/sdd analyze #<N>` first." This is defense in depth — main session also pre-checks.

[PRESERVE]: precondition check unchanged from `spec/stage/design.md` §1 + `design_work.md` line 16.

---

## 2. Phase 0 — Depth handoff

The sub-agent receives `Depth` as an explicit input. No re-detection.

Depth selects the model tier referenced in Phase 1–2 rubric notes — but in Arch B model selection happens at the **stage** sub-agent spawn boundary, not inside review atoms (which no longer exist as separate atoms). The depth value is preserved as a string and passed into rubric prompts when relevant (e.g. tighter heuristics for `deep`).

[PRESERVE]: depth label semantics unchanged from `spec/01-config.md` §3.

---

## 3. Phase 1 — Design work (inlined `design_work` logic)

Inlines the producer atom. Two paths emerge here: SINGLE or CHILDREN.

### 3.1 Step 0 — Pre-flight / retry-context fetch

**Round 1** (no prior review markers):
- Follow `<<SKILL_DIR>>/atoms/_preflight.md` Medium tier, Section B items 1 + 2 + 3:
  - Project conventions (CLAUDE.md, README, lint configs)
  - Commit message style (`git log --oneline -20`)
  - Similar past PRs (`gh pr list --search "<feature-keywords>"`) — informs file organization, naming, and architectural choices for steps 4–9.

**Round ≥ 2** (retry):
- Skip preflight items.
- Execute `_review_helpers.md` Section C to self-fetch the three previous-round review markers (`<!-- sdd:review:design:completeness -->`, `:quality`, `:adversarial`).
- Receive sorted findings array `<retry-findings>` (`critical → major → minor`).
- If Section C returns `FAIL: ...` → propagate immediately as this sub-agent's return value.

[PRESERVE — load-bearing]: atom-side retry self-fetch is v0.36 main-session savings invariant.

### 3.2 Steps 1–3 — Read GitHub context

1. `gh repo view --json nameWithOwner -q .nameWithOwner` → inline `<owner>/<repo>` literally into subsequent calls (no shell variables per Common Contracts §8).
2. Read Issue body + analyze output:
   ```bash
   gh issue view <N>
   gh api repos/<owner>/<repo>/issues/<N>/comments \
     --jq '.[] | select(.body | contains("sdd:analyze:output")) | .body'
   ```
3. Parent/Child detection per `02-multilingual.md` §3 regex `(Parent|상위 |親)Issue: #<n>`. If this Issue is a child, additionally fetch parent's `<!-- sdd:design:output -->` for architectural consistency:
   ```bash
   gh api repos/<owner>/<repo>/issues/<parent>/comments \
     --jq '.[] | select(.body | contains("sdd:design:output")) | .body'
   ```

### 3.3 Steps 4–9 — Inline design work

4. **Codebase exploration** via Read/Grep/Glob (no Explore sub-agent — single-level spawn rule). Investigate existing architecture, affected files, test conventions, similar implementations.
5. Identify impact scope.
6. Design file structure changes (Add/Modify/Delete/Move per file).
7. Design data model changes if applicable.
8. Identify constraints + risks with mitigations.
8.5. **Testability constraints** — list external dependencies (DB, network, time, randomness, file I/O, env vars, external services, browser APIs).
   - 0 deps → Testability section is `N/A (no external dependencies in scope)`.
   - 1+ deps → for each: mock/stub strategy, injection seam (verify exists via Read/Grep; if absent the design MUST add one to step 6), hard-to-test concerns.
   - Testability decisions **must influence** step 6's file list.
9. **Feature list with PR split** — explicitly decide:
   - **1 PR** → path = SINGLE.
   - **≥ 2 PRs** → path = CHILDREN, list sub-feature names + brief descriptions.

[PRESERVE]: 8.5 testability flow load-bearing — reviewers will flag false `N/A` as critical.

### 3.4 Step 10 — Language detection

Read `.github/.sdd-lang`. If missing, detect from Issue body, map to `en`/`ko`/`ja`. Default `en`. Used to select template files in Step 11 and Step 16.

[IMPROVE candidate, deferred]: cross-stage language re-detection. Same wart as analyze.

### 3.5 Step 11 — Render design body

Format design output via `<<SKILL_DIR>>/templates/{lang}/output_design.md` with placeholder substitution:
- `{{feature_list}}`, `{{file_structure}}`, `{{data_model}}`, `{{constraints}}`, `{{risks}}`, `{{testability}}`, `{{pr_split}}` — values from steps 5–9.

### 3.6 Steps 12–14 — Self-review (blockers only)

Use rubric `<<SKILL_DIR>>/atoms/rubrics/design-completeness.md` ONLY for posting-blocking checks (NOT quality evaluation):
- [ ] Marker `<!-- sdd:design:output -->` present
- [ ] Template required sections filled (file structure, PR split rationale, constraints, testability)
- [ ] No `<empty>` / TODO / placeholder text
- [ ] PR split count explicitly stated (single vs ≥ 2)
- [ ] File paths syntactically valid (no obvious typos)
- [ ] If retry: every `critical` / `major` finding from `<retry-findings>` addressed; mention how

Fix inline. Record fixed blockers in a `<details>` block embedded inside the design body BEFORE the closing marker (Step 14).

Quality / completeness / risk evaluation are NOT done here — Phase 2 reviewers' job.

### 3.7 Step 15 — Post the design comment

Mandatory Section F flow (`_review_helpers.md`):
- Marker: `<!-- sdd:design:output -->`
- Temp path: `/tmp/sdd-design-output-<N>.md`
- Write tool renders body → Bash dup search → empty: `gh issue comment <N> --body-file ...` / has id: `gh api ... /comments/<id> -X PATCH --field body=@...`.

### 3.8 Step 16 — Children creation (only on CHILDREN path)

See §10 for the full child-creation contract — including idempotency. On SINGLE path skip Step 16 entirely.

### 3.9 Phase 1 internal return (consumed by Phase 2)

The work block emits a **stage-internal** signal (not the sub-agent's final RESULT):
- `WORK SINGLE` — single-PR design posted. Phase 2 reviews proceed.
- `WORK CHILDREN: #A,#B,#C` — multi-PR design posted, children created, children list posted. Phase 2 reviews proceed.
- Internal `FAIL: <reason>` → escape Phase 1, fall through to Phase 6 with the final return value set to `FAIL: <reason>`.

[NEW for Arch B]: this is a local boundary inside the sub-agent. Externally the path bits propagate into the Phase 6 return: `OK ADVANCE: implement SINGLE` vs `OK ADVANCE: implement CHILDREN: #A,#B,#C`.

---

## 4. Phase 2 — Reviews (serial, 3 in order)

Three reviews run in sequence (single-level spawn rule prohibits parallelism inside a sub-agent). Each review reads only its own role-specific rubric — no cross-visibility of other reviewers' verdicts. Each posts an Issue comment via Section F.

### 4.1 Review A — completeness

Rubric: `<<SKILL_DIR>>/atoms/rubrics/design-completeness.md`. Verifies:
- Analyze→design coverage (every analyze feature addressed)
- Impact scope completeness
- Constraints + risks identified with mitigations
- PR split logical, each PR independently deliverable
- Architecture consistent with codebase patterns
- **Testability section present** — `N/A` only if no external deps; false `N/A` → **critical**
- Cross-stage check (analyze → design): features mapped, priorities preserved, out-of-scope still out-of-scope
- Child Issue consistency (if child): architecture matches parent's PR-split rationale
- Codebase verification (Read/Grep): file path + symbol existence. Discrepancies → **major**

Severity → verdict:
- Any `critical` or `major` → **FAIL**
- Only `minor` or none → **PASS**

Post marker `<!-- sdd:review:design:completeness -->` via Section F (temp path `/tmp/sdd-review-design-completeness-<N>.md`). Body includes `<!-- sdd:findings:json -->` block per Common Contracts §5.

### 4.2 Review B — quality

Rubric: `<<SKILL_DIR>>/atoms/rubrics/design-quality.md`. Verifies:
- Feasibility (buildable; unstated prerequisites; realistic estimates)
- Maintainability (reuse vs new abstractions; reversibility; interface design)
- Risk identification (concurrency, race, transactions, migration, downstream consumers)
- Test strategy realism
- Architectural anti-patterns (layer violations, implicit coupling, premature abstractions)
- Testability quality (DI seam existence; hidden deps behind `N/A` → **major**)
- Codebase verification of pattern claims

Post marker `<!-- sdd:review:design:quality -->` via Section F.

### 4.3 Review C — adversarial

Rubric: `<<SKILL_DIR>>/atoms/rubrics/design-adversarial.md`. **REFUTES** the design — must find ≥ 1 weakness or justify why none. 8 stage-specific refutation angles with explicit `rule_id`s:
1. Alternative-rejection rationale (`no-alternative-considered`, `parallel-structure-unjustified`)
2. PR split independence + ordering (`pr-order-hidden`, `pr-leaves-master-inconsistent`, `pr-boundary-by-convenience`)
3. Deferred mitigations (`critical-risk-deferred`, `fallback-defeats-mitigation`)
4. Codebase pattern claim verification (`pattern-not-found`, `pattern-misdescribed`, `layout-claim-incorrect`)
5. Cross-stage drift from analyze (`high-priority-feature-dropped`, `out-of-scope-silently-reintroduced`, `nfr-silently-dropped`)
6. Hidden complexity gloss (`complexity-glossed`, `external-integration-underspecified`)
7. Testability seam existence (`testability-seam-missing`, `testability-seam-brittle`, `testability-na-but-side-effects-present`)
8. Data shape / contract drift (`contract-drift`, `schema-migration-unspecified`)

Mandatory codebase verification: verify 1–2 file paths cited in design exist; verify 1 architectural pattern claim by reading cited code.

Post marker `<!-- sdd:review:design:adversarial -->` via Section F.

### 4.4 Independence + budgets

Each review evaluates from its own rubric ONLY. Implementation: the sub-agent re-derives context (read analyze + design comments fresh from GitHub) at the start of each review block — no in-context leakage of prior reviewer's findings. Codebase exploration budget per review: 15 Read / 10 Grep / 5 Glob (`_review_helpers.md` Section D). Adversarial verification budget is mandatory (vs optional for completeness/quality).

[PRESERVE — load-bearing]: independence invariant from `spec/00-common-contracts.md`.

---

## 5. Phase 3 — Verdict combination (per round)

After all three reviews complete, combine:

| completeness | quality | adversarial | Round verdict |
|---|---|---|---|
| PASS | PASS | PASS | **PASS** — exit retry loop |
| PASS | PASS | FAIL | **FAIL** — adversarial-only; log warning, retry |
| FAIL | * | * | **FAIL** — retry |
| * | FAIL | * | **FAIL** — retry |
| any atom-level `FAIL: <reason>` | — | — | Stop — return `FAIL: <reason>` to main |

### Adversarial-only FAIL escalation
If only adversarial FAILed:
- Log to narrative output: "⚠ Adversarial reviewer alone identified critical/major issues. Surfacing for awareness."
- Treat as normal FAIL — retry counts apply.

[PRESERVE]: combination + adversarial-only behavior unchanged from `spec/stage/design.md` §7.

### Atom-level vs verdict FAIL
- `FAIL: <reason>` (a review block could not complete — gh failed, design output missing, etc.) → immediately stop sub-agent and return `FAIL: <reason>`.
- `OK FAIL: <summary>` (review verdict) → counts toward round combination; retry counter advances.

---

## 6. Phase 4 — Retry loop (max 3 rounds)

```
round = 1
while round <= 3:
    if round > 1:
        re-invoke Phase 1 work in retry mode (Step 0 fetches <retry-findings>)
        # Children idempotency guard applies — see §10.
    run Phase 2 reviews (serial)
    combine verdicts (Phase 3)
    if PASS:
        break  → Phase 6
    if any atom-level FAIL:
        return that FAIL  → Phase 6 (failure path)
    round += 1
if round > 3:
    → Phase 5 (escalation gate)
```

### Per-round details
- Round 1: first-round work (preflight), three fresh review markers posted.
- Rounds 2–3: retry mode work; review markers UPDATED in place (Section F.2 duplicate-prevention — round-to-round overwrites, not appends, per Common Contracts §4).

### Children idempotency note [PRESERVE — load-bearing]
On rounds ≥ 2 with path = CHILDREN: Phase 1 Step 16a detects existing `<!-- sdd:children:output -->` and **skips child creation entirely**, only re-renders + updates `<!-- sdd:design:output -->`. Children `#A, #B, #C` persist unchanged. See §10.

### Token note
The retry self-fetch is the v0.36 main-session savings invariant. Inside the sub-agent's own context it costs the usual fetch+parse work — main session sees no review-comment bodies.

[PRESERVE]: retry mechanism + 3-round budget per Common Contracts §7.

---

## 7. Phase 5 — Escalation gate (round 3 FAIL)

Triggered only when round 3's combined verdict is FAIL. Two modes:

### 7.1 skip-review.design set
Main session has already parsed `.github/.sdd-config` and indicated this via the spawn-time depth/skip context. However, per `01-sub-agent-contract.md` §4 skip-review semantics live in the **main session**, not the sub-agent.

Sub-agent's job at round 3 FAIL: render an escalation summary listing remaining `critical` and `major` findings with role label, embed in narrative, and return ONE of:

- If sub-agent has been told `Resume: continue-after-escalation` OR if `skip-review.design` was auto-passed in via input flag (Arch B variant — see note below), the sub-agent treats this as "main authorizes auto-continue" and proceeds to Phase 6 normally (returns `OK ADVANCE: implement <path>`).

- Otherwise:
  ```
  >>> RESULT <<<
  ESCALATE: design round 3 FAIL — findings: [critical] X, [major] Y (path: SINGLE|CHILDREN: #A,#B,#C)
  ```

[NEW for Arch B]: per `01-sub-agent-contract.md` §3, the **main session** calls `AskUserQuestion`. Sub-agent surfaces ESCALATE and quits its current invocation. Main session re-spawns with `Resume: continue-after-escalation` on user Continue.

[OPEN — implementation note]: the cleanest contract is for main to pass an explicit `SkipReview: design` flag at spawn time (when configured) so the sub-agent never produces an ESCALATE in that case. This avoids a round-trip when behavior is deterministic. Cross-stage consistency to be settled in `stage-designs/_common.md` (if added) or in each stage's design.

### 7.2 Round 3 PASS through to Phase 6
If round 3 succeeded, no escalation. Skip §7 and proceed to Phase 6.

### 7.3 Path preservation across ESCALATE
Whether path = SINGLE or CHILDREN, the design comment + (if applicable) children list + child Issues are already on GitHub from the most recent round. ESCALATE does NOT roll those back. On Continue, Phase 6 simply transitions the parent label.

---

## 8. Phase 6 — Output (label transition + return)

### 8.1 Parent label transition
Both paths transition parent Issue label: `sdd:design` → `sdd:implement`.

```bash
gh issue edit <N> --remove-label sdd:design --add-label sdd:implement
```

Failure here → return `FAIL: label transition failed for #<N>`.

[PRESERVE]: parent label always advances to `sdd:implement` after design completes — even on CHILDREN path, parent **pauses** there per Common Contracts §1 (parent-pause invariant).

### 8.2 Children label state (CHILDREN path only)
Each child Issue is born with `sdd:analyze` + `sdd:child` labels (applied at `gh issue create --label ...`, per §10). The sub-agent does NOT modify these in Phase 6.

### 8.3 Return contract per path

| Path | Return line |
|---|---|
| SINGLE, success | `OK ADVANCE: implement SINGLE` |
| CHILDREN, success | `OK ADVANCE: implement CHILDREN: #A,#B,#C` |
| ESCALATE (round 3 FAIL, no skip-review) | `ESCALATE: design round 3 FAIL — <summary>` |
| Atom error | `FAIL: <reason>` |

Final output of the sub-agent always ends with the sentinel line:

```
>>> RESULT <<<
<one-line status per table above>
```

### 8.4 What main session does next
Per `01-sub-agent-contract.md` §8:
- `OK ADVANCE: implement SINGLE` → main session checks skip-review.design → either spawn `stage_implement` (auto) OR confirm with user.
- `OK ADVANCE: implement CHILDREN: #A,#B,...` → main queues children for analyze stage; parent paused at `sdd:implement` until all children reach `sdd:done`.
- `ESCALATE: ...` → main calls `AskUserQuestion`; on Continue, re-spawns `stage_design` with `Resume: continue-after-escalation`.

[PRESERVE]: parent-stops-at-implement invariant for CHILDREN path. Parent does not progress through implement/test by itself.

### 8.5 Resume-after-escalation fast-path
When sub-agent re-spawns with `Resume: continue-after-escalation`:
- Skip Phases 1–5 entirely (work already posted, reviews already on GitHub from prior invocation).
- Re-derive path (SINGLE vs CHILDREN) by reading `<!-- sdd:children:output -->` presence:
  - Present → path = CHILDREN; re-derive `#A,#B,#C` list from the children-list comment.
  - Absent → path = SINGLE.
- Execute §8.1 label transition.
- Return `OK ADVANCE: implement <path>`.

[NEW]: enables clean resumption without re-running expensive reviews on already-failed-then-user-accepted content.

---

## 9. Cross-stage invariants preserved

1. `<!-- sdd:design:output -->` exists on parent before any `stage_implement` spawn. SINGLE path posts this in Phase 1 Step 15. CHILDREN path same.
2. `<!-- sdd:children:output -->` exists on parent iff path = CHILDREN. Queryable by `/sdd batch`, `/sdd auto`, and `stage_test`'s parent-integration logic.
3. Each child Issue carries `sdd:analyze` + `sdd:child` at birth (applied at create-time).
4. Each child Issue's body contains `<!-- sdd:child-issue -->` block with multilingual `Parent Issue: #<N>` (English `Parent`, Korean `상위 `, Japanese `親`). Downstream parent-lookup regex unchanged.
5. Parent's label is `sdd:implement` after this stage (both paths). Parent advances no further on its own when path = CHILDREN.
6. Review comments are queryable across rounds via marker. Update-in-place — latest round only.
7. Findings JSON schema (Common Contracts §5) present inside every review comment.
8. Label transition is the sole stage-completion signal.
9. Testability section informs `stage_implement`'s TDD plan. `N/A` only when honest; reviewers verified seam existence (rule `testability-seam-missing`).

[PRESERVE]: all invariants from `spec/stage/design.md` §9.

---

## 10. Child Issue creation (signature behavior)

The CHILDREN-path artifact set is unique to this stage. Encapsulated entirely in Phase 1 Step 16. Inlined from current `design_work.md` Step 16.

### 10.1 When
- Step 16 fires **only** when Step 9 decided ≥ 2 PRs.
- SINGLE path skips Step 16 entirely (Step 17: "no child creation. Done.").

### 10.2 How (per child, sequence)
1. Format child Issue body via `<<SKILL_DIR>>/templates/{lang}/output_child_issue.md` with placeholder substitution:
   - `{{parent_issue}}` → `<N>` (parent Issue number)
   - `{{sub_feature_description}}` → from Step 9's feature list
   - `{{criteria_list}}` → markdown checkbox list from Step 9
2. Write rendered body to `/tmp/sdd-child-issue-<N>-<seq>.md` via the Write tool (`<seq>` = 1-based index over sub-features). Section F.4 mandatory because the body contains `\n#` patterns.
3. Create the child Issue (single simple Bash call):
   ```bash
   gh issue create \
     --title "[SDD Child] <parent title> - <sub-feature name>" \
     --body-file /tmp/sdd-child-issue-<N>-<seq>.md \
     --label sdd:analyze \
     --label sdd:child
   ```
4. Capture the new Issue number from the command's output URL (e.g. `https://github.com/<owner>/<repo>/issues/123` → `123`). Inline as literal for the children-list comment.

[PRESERVE]: title format, label set, body file path scheme, and capture mechanism unchanged from `spec/stage/design.md` §5.

### 10.3 Children list comment (parent)
After all children created in 10.2, post the children list on the parent:
- Marker: `<!-- sdd:children:output -->`
- Temp path: `/tmp/sdd-children-output-<N>.md`
- Render via `<<SKILL_DIR>>/templates/{lang}/output_children.md` (one table row per child: number, title, sub-feature).
- Post via Section F (search + create-or-update).

### 10.4 Multilingual parent reference
Each child's body (rendered from `output_child_issue.md`) contains the `<!-- sdd:child-issue -->` block including:
- en: `Parent Issue: #<N>`
- ko: `상위 Issue: #<N>`
- ja: `親Issue: #<N>`

Downstream detection regex `(Parent|상위 |親)Issue: #<n>` (per `02-multilingual.md` §3). With number-boundary rule `([^0-9]|$)` when matching specific `<n>`.

[PRESERVE — load-bearing]: pattern is the single source of truth across 5+ call sites.

### 10.5 Idempotency (retry rounds)
**Hard rule, load-bearing**: at the start of Step 16:
```bash
gh api repos/<owner>/<repo>/issues/<N>/comments \
  --jq '.[] | select(.body | contains("<!-- sdd:children:output -->")) | .id'
```
- Empty result → no prior children. Proceed with full Step 16 (10.2 + 10.3).
- Non-empty (one id) → children already created in a prior round. **Skip 10.2 and 10.3 entirely.** Only update `<!-- sdd:design:output -->` in Step 15.
- For the Phase 1 internal return on retry-with-children: re-derive `#A,#B,#C` by parsing the existing children list comment body, so the sub-agent's final return still carries the correct numbers.

Consequence: across rounds 2 and 3, the same set of children persists. Retry can fix design body but cannot change the child set.

[PRESERVE — load-bearing]: idempotency guard preserves child Issue identity. Children would otherwise multiply per retry round.

[RETHINK — surfaced, not changed in this design]: if reviewers want the PR split changed, retry cannot deliver. Work atom must adapt design text within the existing child structure. Two future remedies, both out of scope for the rewrite:
1. Detect "split changed" and surface a hard error so user explicitly closes-and-recreates.
2. Allow close-and-recreate from within the sub-agent (would need an explicit user gate to avoid silent destruction).

### 10.6 Hard rules (preserved from `design_work` Hard rules)
- Single-subagent — no Agent / Skill tool calls. (Sub-agent itself; Phase 1 work block honors this.)
- Do NOT modify the analyze output comment.
- If `<!-- sdd:children:output -->` already exists, do NOT duplicate children — preserve and only update the design output.
- Stay within current repo. Owner/repo via `gh repo view`.

---

## 11. Special edge cases

### 11.1 Issue Validation gate (Common Contracts §10)
Before any work, the sub-agent re-validates `<N>` (main session already did this — defense in depth):
```bash
gh issue view <N> --json url --jq .url
```
- Contains `/pull/` → PR, not Issue → return `FAIL: #<N> is a PR, not an Issue` immediately. No state changes.

### 11.2 Precondition: analyze output missing
Already covered in §1. The check fires immediately after Issue Validation, before any Phase 1 work.

### 11.3 Skip-review semantics (recap)
- AI review loop (Phases 1–4) ALWAYS runs. Skip-review never short-circuits it.
- Escalation gate (Phase 5) AND post-stage user confirmation are the only things skip-review.design influences. These both live in the main session per `01-sub-agent-contract.md` §4 — sub-agent's job is just to return the correct status keyword.
- SINGLE path with skip-review on: main spawns `stage_implement` immediately upon receiving `OK ADVANCE: implement SINGLE`.
- CHILDREN path with skip-review on: main stops the parent at `sdd:implement` and queues children for `stage_analyze`.

[PRESERVE]: skip-review semantics — gate skip only, never AI review skip.

### 11.4 Atom-level FAIL within review block
If review C (say) cannot complete (gh API error, design output missing), the sub-agent stops the loop and returns `FAIL: <reason>` to main. The two prior reviews' posted comments remain on GitHub (no rollback) — Section F's update-in-place ensures the next attempt overwrites.

### 11.5 Wall-clock cost
Serial reviews: ~30s × 3 = ~90s per round (vs current 30s parallel). Max 3 rounds = ~270s for reviews alone. Phase 1 work atom dominant cost (Opus, codebase exploration) is unchanged. Acceptable per Arch B trade-off.

---

## 12. Implementation notes (deferred)

- **Common stage harness extraction**: §3 Step 0 (preflight vs retry self-fetch), §4 review block scaffold, §6 retry loop, §7 escalation — these are nearly identical across analyze/design/implement/test stage sub-agents. Candidate for `atoms/_stage_harness.md` shared file. Decision in Phase B common section.
- **Rubric file boundaries**: `design-completeness.md`, `design-quality.md`, `design-adversarial.md` carry the role-specific criteria text. `output_design.md` carries the body template. No code logic lives in rubrics — they are prompts/criteria text.
- **Children list parsing on retry**: §10.5 requires parsing the existing children list comment body to re-derive `#A,#B,#C`. The comment body is markdown table per `output_children.md`. The sub-agent must Read this body and extract issue numbers via simple substring match `#<digits>`. Boundary rule: number must be followed by whitespace, `|`, `)`, or EOL — to avoid matching numbers inside larger strings.

---

## Cross-references

- Spec: `spec/stage/design.md` (source of all PRESERVE markers above)
- Common contracts: `spec/00-common-contracts.md` §§1–13
- Multilingual: `spec/02-multilingual.md` §3 (parent regex, load-bearing)
- Architecture: `design/00-architecture.md` §§3, 9
- Sub-agent contract: `design/01-sub-agent-contract.md` §§1–8
- File layout: `design/02-file-layout.md` §§1, 2 (rubric paths)
- Sibling stage design: `design/stage-designs/analyze.md` (format reference)
- Companion stage designs: `stage-designs/implement.md`, `stage-designs/test.md` (downstream consumers of the CHILDREN path)
