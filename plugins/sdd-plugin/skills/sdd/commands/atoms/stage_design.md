# STAGE: design

**Single sub-agent. MUST NOT spawn Agent calls. MUST NOT spawn other sub-agents. MAY use Skill tool, though design stage uses no Skills.**

This file is the Arch B stage sub-agent body for the **Design** stage. The main session (or `resume.md` after bootstrap) spawns this sub-agent once per Issue per stage invocation. Internally it inlines the logic of the legacy `design_work`, `design_review` (completeness + quality), and `design_adversarial` atoms — runs them **serially** because the single-level spawn rule (`spec/00-common-contracts.md` §12) forbids nested Agent calls.

The sub-agent owns the entire AI-review retry loop (max 3 rounds), the adversarial-only FAIL warning (R6), the SINGLE-vs-CHILDREN path decision, child Issue creation (idempotent across retry rounds), and posting of all marker comments via Section F. It does NOT call `AskUserQuestion`, does NOT change labels, and does NOT auto-proceed to implement — those are main-session responsibilities. On Round 3 FAIL with skip-review OFF the sub-agent returns an `ESCALATE:` line so main can interactively prompt the user.

> **Bash Command Execution**: every shell snippet below is its own simple Bash tool call. See canonical rules in `<<SKILL_DIR>>/commands/atoms/_bash_rules.md`. Codebase exploration uses **Grep / Glob / Read** tools, not Bash equivalents.

---

## Inputs

- `$1` — Issue number. Already validated as an Issue (not a PR) by the caller, but re-validated here as defense in depth (`spec/00-common-contracts.md` §10).
- `$2` — Depth dial. One of `default` / `deep` / `shallow`. The caller derives this from labels; this sub-agent verifies against the live labels in Phase 0.
- `$3` — Resume hint. One of `none` (default; full execution) or `continue-after-escalation` (skip Phases 1-4; main session already escalated to user and the user chose Continue — work + reviews are already persisted on GitHub). Per `design/01-sub-agent-contract.md` §3 and SYNTHESIS-v2 T1.5.

`Branch` / `PR` fields from the global prompt template (`design/01-sub-agent-contract.md` §1) are not used by design and may be omitted or passed as `null`.

---

## §1. Issue Validation (defense in depth)

Before anything else, validate `$1` per Common Contracts §10:

```bash
gh issue view $1 --json url --jq .url
```

- Empty / error → return `FAIL: Issue #$1 does not exist`.
- URL contains `/pull/` → return `FAIL: #$1 is a Pull Request, not an Issue. SDD commands operate on Issues only.` Do NOT modify labels, do NOT post comments.
- URL contains `/issues/` → continue.

[PRESERVE — `spec/stage/design.md` §11.1 Issue Validation; `spec/00-common-contracts.md` §10.]

### Precondition: analyze output present (fail-fast)

Before any work, confirm the analyze output exists on the Issue (`spec/stage/design.md` §1 / §11.2 / `design_work.md` line 16):

```bash
gh repo view --json nameWithOwner -q .nameWithOwner
```

Observe `<owner>/<repo>` from the output. Then:

```bash
gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | select(.body | contains("<!-- sdd:analyze:output -->")) | .id'
```

- Empty result → return `FAIL: analyze output not found on Issue #$1`. Do NOT modify labels, do NOT post comments.
- Non-empty → continue.

[PRESERVE — `spec/stage/design.md` §1 Precondition; `design/stage-designs/design.md` §1 (defense in depth even though main pre-checks).]

---

## §2. Phase 0 — Depth detection

Even though `$2` was passed in by the caller, re-read labels here to keep the sub-agent self-contained (M4.5 pattern: single sub-agent self-contained re-validation):

```bash
gh issue view $1 --json labels --jq '[.labels[].name]'
```

Decision (overrides `$2` if labels disagree):
- Labels contain `sdd:review:deep` → `depth = deep`
- Labels contain `sdd:review:shallow` → `depth = shallow`
- Otherwise → `depth = default`

The depth dial selects models used internally for the inlined work and review reasoning per `spec/00-common-contracts.md` §3 / `_review_helpers.md` Section A.2. Since this entire stage runs inside ONE sub-agent context (no inner Agent spawns), the model dial is informational for the sub-agent's reasoning style — the actual model is fixed by the Agent spawn's `model` parameter from main session. **Note (per `_review_helpers.md` Section A.2.1): `design.md` spawns this stage with `model: fable` when `depth = deep`, `sonnet` when `depth = shallow`, otherwise `opus` (design has no in-context security analysis).** Record the dial for the `<details>` self-review trace, and record the actual model accurately in the findings JSON.

### Resume short-circuit (T1.5)

If `$3 == "continue-after-escalation"`:
- Re-validate the Issue still exists and is still an Issue (Phase 0 above) AND the analyze output precondition still holds (§1 precondition check).
- Confirm the three review markers exist on the Issue: substring check for `<!-- sdd:review:design:completeness -->`, `<!-- sdd:review:design:quality -->`, `<!-- sdd:review:design:adversarial -->` via a single `gh api ... /comments` call.
- Confirm the design output marker exists on the Issue: substring check for `<!-- sdd:design:output -->`.
- **Path re-derivation**: detect presence of `<!-- sdd:children:output -->` on the Issue:
  - Present → path = CHILDREN. Read the children-list comment body; extract child Issue numbers by scanning for `#<digits>` tokens followed by whitespace, `|`, `)`, or EOL (per `design/stage-designs/design.md` §12 implementation note). Inline the captured numbers as `#A,#B,#C` (literal comma-separated, no space) for §8 Phase 6.
  - Absent → path = SINGLE.
- Skip directly to **§8 Phase 6** with Normal path (`OK ADVANCE: implement SINGLE` or `OK ADVANCE: implement CHILDREN: #A,#B,#C`). Work + reviews were already done in the prior spawn; findings remain on GitHub for human follow-up.
- If the three review markers OR the design output marker are NOT all present → return `FAIL: continue-after-escalation requested but prior round's markers missing on #$1`.

[PRESERVE — `design/stage-designs/design.md` §8.5 Resume-after-escalation fast-path; M4.5 review §3 (carry verbatim with CHILDREN detection).]

---

## §3. Phase 1 — Work (inlined `design_work` logic)

This phase produces the design output, decides SINGLE vs CHILDREN, and (on first-time CHILDREN path) creates child Issues and posts the children-list comment.

Local state: a counter `round` starting at 1. Rounds 2 and 3 enter this phase via §6.

### Autonomy mode (depth == deep / Fable only)

If `depth == deep`, this stage runs on Fable (per `_review_helpers.md` Section A.2.1). Fable produces better designs when given a goal and constraints rather than a step-by-step recipe, so **treat Steps 3–9 below as goals your design must satisfy, not a fixed sequence to execute or narrate.** Explore and design in whatever order is most effective; only the final output matters.

Working principles (apply only at `depth == deep`):
- When you have enough information to act, act. Don't re-derive facts already in the Issue / analyze output, and don't enumerate options you won't pursue — give a recommendation, not an exhaustive survey.
- Design the simplest thing that meets the requirements. No speculative abstractions, extra files, or future-proofing the Issue didn't ask for.

This relaxes only the *ordering and narration* of Steps 3–9. It does NOT relax any hard constraint — you still MUST: run Step 0 preflight (or retry self-fetch) and Steps 1–2 as written, fill every required Step 11 template field, give ≥1 rejected alternative with reasoning, produce a REAL Step 8 testability section (no false `N/A` when side effects exist), state the Step 9 PR-split count with rationale, select the correct language template (Step 10), and pass Step 12's self-review blockers. At `depth == default` / `shallow` (opus), ignore this block and follow Steps 3–9 in order.

> **Tunable — rollback if it regresses.** This autonomy framing is an A/B-tunable Fable adaptation (`_review_helpers.md` Section A.2.1). If deep-tier design output degrades versus opus, delete this block; the numbered steps below are the opus-tuned fallback.

### Step 0: Preflight (Medium tier) or retry self-fetch

- **Round 1** (`round == 1`): follow `<<SKILL_DIR>>/commands/atoms/_preflight.md` Section A — tier **Medium**, Section B items 1 + 2 + 3 + 5 (project conventions + commit message style + similar past PRs via `gh pr list --search` + project-specific stage rules). Apply Section D failure handling. The similar past PRs (item 3) inform file organization, naming, and architectural choices for steps 4–9 below. Record findings for the §3.11 self-review trace.
- **Rounds 2 / 3** (`round > 1`): SKIP the preflight items above. Instead, execute `<<SKILL_DIR>>/commands/atoms/_review_helpers.md` Section C to self-fetch the previous round's three review comments (markers: `<!-- sdd:review:design:completeness -->`, `<!-- sdd:review:design:quality -->`, `<!-- sdd:review:design:adversarial -->`) from Issue `$1`. The procedure returns a sorted findings array (`critical → major → minor`). Hold this array as `<retry-findings>` for use throughout the steps below.
  - If Section C returns `FAIL: ...` (no review comments found, unrecognized retry slot value, etc.) → propagate it as this sub-agent's return value before doing any further work.

[PRESERVE — `spec/stage/design.md` §4 Phase 1 retry semantics; `spec/00-common-contracts.md` §7 Retry Mode Trigger; v0.36 atom-side self-fetch invariant.]

### Step 1: Read the Issue + analyze output

Owner/repo was already resolved in §1 precondition; reuse the literal `<owner>/<repo>` value here.

```bash
gh issue view $1
```

```bash
gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | select(.body | contains("sdd:analyze:output")) | .body'
```

Capture Issue title, body, labels, and the analyze output content for use in Steps 2–9.

### Step 2: Detect child / parent context (multilingual regex)

Scan the Issue body for the canonical regex from `<<SKILL_DIR>>/commands/atoms/_multilingual.md`:

```
(Parent|상위 |親)Issue: #<n>
```

Per `spec/02-multilingual.md` §3 — `상위` is followed by a space; `親` is NOT followed by a space. If a match is found, capture the parent's `<n>`.

If parent found, fetch the parent's design output for architectural consistency:

```bash
gh api repos/<owner>/<repo>/issues/<parent>/comments --jq '.[] | select(.body | contains("sdd:design:output")) | .body'
```

Substitute the literal parent number. Use parent context to keep this child's design consistent with the parent's overall architecture and PR-split rationale. Focus the detailed design on this child's sub-feature only.

[PRESERVE — `design_work.md` Step 3 / `spec/stage/design.md` §5 multilingual parent reference; `spec/02-multilingual.md` §3 regex.]

### Step 3: Codebase exploration

Use Read / Grep / Glob aggressively (no Explore sub-agent — single-level spawn rule):
- Existing architecture and patterns relevant to the requirements
- Files, modules, and dependencies that would be affected
- Existing test structure and conventions
- Similar implementations in the codebase that can be referenced

Be systematic: start with repo root listing, identify relevant directories, search for related symbols, read at least one similar implementation. Budget: keep within reasonable bounds for work-phase exploration (not subject to reviewer Section D cap — but stop when context is sufficient).

[PRESERVE — `design_work.md` Step 4 lines 53–59.]

### Step 4: Impact scope

Identify impact scope (related files, screens, data, configurations) based on Step 3 results.

### Step 5: File structure changes

Design file structure changes (Add / Modify / Delete / Move per file).

### Step 6: Data model

Design data model changes if applicable.

### Step 7: Constraints and risks

Identify constraints and risks with mitigations.

### Step 8: Testability constraints (load-bearing)

a. **List external dependencies** in this PR's scope. Examples: DB, network, time, randomness, file I/O, environment variables, external services, browser APIs.

b. **If 0 external dependencies** → Testability section in the design output will be `N/A (no external dependencies in scope)`. Skip to Step 9.

c. **If 1+ external dependencies** → for each, design:
   - **Mock/stub strategy** — how will tests isolate this dependency?
   - **Injection/seam point** — verify it exists (use Read/Grep to confirm the codebase has the DI hook). If absent, the design MUST introduce one (add to Step 5's file list as a Modify/Add).
   - **Hard-to-test concerns** — timing, randomness, async ordering. Note how the design accommodates them.

d. Testability decisions made here **must influence** Step 5's file list and Step 7's constraints. If a dependency forces a new seam, update Step 5's file list.

e. **Test level for user-facing scenarios**: review the Feature List (Step 9) and identify any scenarios that require E2E-level verification — multi-step user flows, browser/device interaction, real external service calls that cannot be mocked. List them explicitly in the Testability section output as `E2E required: <scenario>`. If none apply, add the line `No E2E scenarios — all scenarios are expressible as unit or integration tests`. This list is consumed by `_tdd.md` §6.4 (E2E_SKIPPED compensating coverage decision) and `stage_test.md` (Manual QA checklist).

[PRESERVE — `design_work.md` Step 8.5; `design/stage-designs/design.md` §3.3 (8.5 testability flow load-bearing — reviewers flag false `N/A` as critical via rule `testability-na-but-side-effects-present`).]

### Step 9: Feature list + PR split decision (SINGLE vs CHILDREN)

Create the feature list. **Determine if the design splits into multiple PRs (≥ 2) or is a single PR.** This is the SINGLE-vs-CHILDREN narrative decision — record it explicitly:

- **1 PR** → `path = SINGLE`.
- **≥ 2 PRs** → `path = CHILDREN`; enumerate sub-feature names with brief descriptions. Each sub-feature will become a child Issue in §3.12.

The decision must be explicit in the design body (Step 11 template field `pr_split`). Reviewers will flag missing rationale (rule `pr-boundary-by-convenience`, `pr-order-hidden`).

[PRESERVE — `spec/stage/design.md` §6 SINGLE vs CHILDREN trigger; `design_work.md` Step 9; `design/stage-designs/design.md` §3.3 Step 9.]

### Step 10: Language template selection

Determine output language:
1. If `.github/.sdd-lang` exists → read it; use its language code (`en` / `ko` / `ja`).
2. Else detect primary language of the Issue body; map to closest supported (`en` / `ko` / `ja`).
3. Else default to `en`.

Load the templates needed:

```
<<SKILL_DIR>>/templates/<lang>/output_design.md
```

(`<lang>` is one of `en`, `ko`, `ja`.) Read the file via the Read tool. Hold the path also for `output_children.md` and `output_child_issue.md` — needed in §3.12 if `path == CHILDREN`.

[PRESERVE — `spec/02-multilingual.md` §2 Language Detection; §5 Output Template Files; `design_work.md` Step 10.]

### Step 11: Format design output via template

Fill the template fields from Steps 4–9:
- Technical Approach (Approach + Rationale + Alternatives considered) — rule `no-alternative-considered` requires ≥ 1 rejected alternative with reasoning
- File Structure table — rows from Step 5
- Data Model table — rows from Step 6 (or omit body if N/A)
- Constraints and Risks table — rows from Step 7 (with mitigations)
- Testability — table from Step 8c, OR the literal line `N/A (no external dependencies in scope)` if Step 8b
- Feature List with PR Split — rows from Step 9; explicitly state PR count

The Marker `<!-- sdd:design:output -->` MUST be present (open + close — open on first line, close last line per template).

If child Issue: keep the design focused on the child's sub-feature (per Step 2 parent-context read).

### Step 12: Self-review (blockers only — posting-blocking checks)

Before posting, verify:
- [ ] Marker `<!-- sdd:design:output -->` present (open + close)
- [ ] Template required sections filled (Technical Approach, File Structure, Constraints, Testability, Feature List with PR Split)
- [ ] No `<empty>` / TODO / `<...>` placeholder text remaining
- [ ] PR split count explicitly stated (single vs ≥ 2)
- [ ] File paths cited are syntactically valid (no obvious typos)
- [ ] Testability section either is `N/A (no external dependencies in scope)` OR has at least one row per external dependency
- [ ] Cross-stage refs valid (parent reference correct if child Issue)

If a blocker fails → fix inline. Track which blockers were fixed for the §3.14 trace.

**Quality / completeness / risk evaluation are NOT done here** — that is the reviewer phase's job (§4). Keep self-review minimal. [PRESERVE — `design_work.md` Step 12 lines 88–97; `spec/stage/design.md` §8 Self-review.]

### Step 13: Retry resolution check (rounds 2 / 3 only)

If Step 0 fetched `<retry-findings>`, verify before posting that every `critical` and `major` finding has been addressed in the updated design (file structure, PR split, testability, constraints, etc.). Mention how (in the body or in the trace block) — or, only if genuinely infeasible, why it could not be. Treat `minor` entries as supporting context to pinpoint specific rows / files / symbols already revised.

If addressing critical/major findings would force the PR split count to change (e.g., reviewer says "split this into 2 PRs" when round 1 was SINGLE, or vice versa), the work atom MUST work within the constraint of §3.12's idempotency guard — once children exist on this Issue, the child set is fixed (see §3.12 step a). Surface this tension in the body if relevant; do NOT re-create children.

[PRESERVE — `design_work.md` Step 13; `spec/stage/design.md` §8 Retry resolution; `design/stage-designs/design.md` §10.5 RETHINK (idempotency vs split change).]

### Step 14: Append self-review trace

If any blocker was fixed inline in Step 12, OR if Step 0 ran preflight items, append a `<details>` block at the bottom of the body, BEFORE the closing `<!-- /sdd:design:output -->` marker:

```markdown
<details>
<summary>Self-review trace (blockers only)</summary>

- [x] Template required sections filled
- [x] PR split count stated
- [ ] File path `src/auths.ts` was a typo — fixed to `src/auth.ts`

</details>
```

List only blockers actually checked. `[x]` for clean, `[ ]` with inline note for fixed. Skip the block entirely if there is nothing to record. On retry rounds where Step 0 was skipped, omit the preflight section of the trace.

[PRESERVE — `design_work.md` Step 14.]

### Step 15: Post design comment via Section F temp-file pattern

Follow `<<SKILL_DIR>>/commands/atoms/_review_helpers.md` Section F — the mandatory temp-file pattern. Inline `--body` is forbidden because the body contains `\n#` patterns that trip a non-bypassable Claude Code heuristic.

1. **Write tool** — render the design body (including markers) to `/tmp/sdd-design-output-$1.md`. The file must start with `<!-- sdd:design:output -->` on the first line and end with `<!-- /sdd:design:output -->`.

2. **Bash** — duplicate-prevention search:

   ```bash
   gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | select(.body | contains("<!-- sdd:design:output -->")) | .id'
   ```

   Substitute the literal `<owner>/<repo>` from §1 / Step 1 (or re-derive via `gh repo view --json nameWithOwner -q .nameWithOwner` if not held in context).

3. **Bash** — branch on the result:
   - **Empty** → create a new comment: `gh issue comment $1 --body-file /tmp/sdd-design-output-$1.md`
   - **Has id `<id>`** → update in place: `gh api repos/<owner>/<repo>/issues/comments/<id> -X PATCH --field body=@/tmp/sdd-design-output-$1.md`

[PRESERVE — `spec/00-common-contracts.md` §9 Comment Posting Pattern (Section F mandatory); `spec/00-common-contracts.md` §4 Update-in-place invariant; deterministic temp path `/tmp/sdd-design-output-$1.md`.]

### Step 15.5: Coverage Ledger — E2E flag update

Update the shared coverage ledger with the Step 8e E2E decisions. Runs AFTER Step 15 posted the design output.

1. **Bash** — fetch the existing ledger (created by analyze Step 12.5):

   ```bash
   gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | select(.body | contains("<!-- sdd:coverage:ledger -->")) | .body'
   ```

   Parse the JSON between `<!-- sdd:coverage:json -->` and `<!-- /sdd:coverage:json -->` in context.

   - **Found** → hold the parsed object; continue to item 2.
   - **Empty** (analyze stage was skipped) → build an initial ledger in context from THIS design's Feature List (Step 9): ids `F1`, `F2`, … in order, `title` from the Feature List row, `acceptance` derived from the row's description / Issue DoD, `scenarios: []`, `summary` all `0`, `pr: null`. Then continue to item 2.

2. Update the `features` array from Step 8e's Testability output:
   - For each `E2E required: <scenario>` line → match the scenario to its feature (by title / Feature List reference) and set that feature's `e2e_required: true`, `e2e_reason: "<why E2E-level verification is needed — from the Step 8e scenario text>"`.
   - All other features → `e2e_required: false`, `e2e_reason: null`.
   - If Step 8e produced the `No E2E scenarios — …` line → every feature keeps `e2e_required: false`.
   - Do NOT touch `scenarios` or `summary` (implement stage owns those).

3. Set `updated_by: "design"`. Keep `issue`, `pr`, `version` unchanged.

4. **Write tool** — render the updated ledger comment to `/tmp/sdd-coverage-ledger-$1.md`. Same body shape as analyze Step 12.5: opening `<!-- sdd:coverage:ledger -->`, `## Coverage Ledger` heading, `**Updated by:** design`, `**Issue:** #<N>`, then the `<!-- sdd:coverage:json -->` fenced block, then closing markers.

5. **Bash** — duplicate-prevention search:

   ```bash
   gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | select(.body | contains("<!-- sdd:coverage:ledger -->")) | .id'
   ```

6. **Bash** — branch on the result:
   - **Has id `<id>`** (expected — analyze created it) → `gh api repos/<owner>/<repo>/issues/comments/<id> -X PATCH --field body=@/tmp/sdd-coverage-ledger-$1.md`
   - **Empty** (analyze skipped) → `gh issue comment $1 --body-file /tmp/sdd-coverage-ledger-$1.md`

Non-blocking on failure: log a warning to the narrative and continue to Step 16 — downstream stages fall back to the `E2E required:` lines in the design output when the ledger is absent.

### Step 16: SINGLE path short-circuit

If Step 9 decided `path == SINGLE`:
- Skip Step 17 (no child Issue creation, no children-list comment).
- Internal work-phase signal: `WORK SINGLE`.
- Continue to §4 reviews.

### Step 17: CHILDREN path — child Issue creation (idempotent, load-bearing)

If Step 9 decided `path == CHILDREN`:

#### Step 17a: Idempotency guard (load-bearing)

Check whether children already exist on this Issue (this is the critical retry-idempotency check — `spec/stage/design.md` §5 / §8 Edge Case; `design/stage-designs/design.md` §10.5):

```bash
gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | select(.body | contains("<!-- sdd:children:output -->")) | .id'
```

- **Non-empty result** (one id) → children already created in a prior round. **Skip Step 17b and 17c entirely.** Only Step 15 above re-renders the design output.
  - Re-derive the child Issue numbers `#A,#B,#C` for the §8 Phase 6 return by reading the existing children-list comment body:
    ```bash
    gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | select(.body | contains("<!-- sdd:children:output -->")) | .body'
    ```
    Extract child Issue numbers by scanning for `#<digits>` tokens followed by whitespace, `|`, `)`, or EOL (per `design/stage-designs/design.md` §12 implementation note). Hold the captured numbers as `<children-list>` for §8 Phase 6.
  - Internal work-phase signal: `WORK CHILDREN: <children-list>`.
  - Continue to §4 reviews.
- **Empty result** → no prior children. Proceed with Step 17b and Step 17c (first-time creation).

[PRESERVE — load-bearing: `spec/stage/design.md` §5 Idempotency / §8 Edge Cases; `design_work.md` Step 16a line 130; `design/stage-designs/design.md` §10.5. Children would otherwise multiply per retry round.]

#### Step 17b: Create one child Issue per sub-feature

For each sub-feature in Step 9's enumeration (let `<seq>` be the 1-based sub-feature index):

1. **Write tool** — render the child Issue body to `/tmp/sdd-child-issue-$1-<seq>.md`. Use the template `<<SKILL_DIR>>/templates/<lang>/output_child_issue.md` from Step 10, substituting the placeholders:
   - `{{parent_issue}}` → `$1` (literal parent Issue number)
   - `{{sub_feature_description}}` → sub-feature description from Step 9
   - `{{criteria_list}}` → markdown checkbox list (from Step 9's Definition-of-Done rows)
   
   The rendered body MUST contain the `<!-- sdd:child-issue -->` block. Per template language:
   - `en`: line `Parent Issue: #<parent>`
   - `ko`: line `상위 Issue: #<parent>` (note the space after `상위`)
   - `ja`: line `親Issue: #<parent>` (no space after `親`)
   
   These render automatically when the template file is loaded — substitution only fills the placeholders. [PRESERVE — `spec/02-multilingual.md` §3 multilingual regex; load-bearing across 5+ call sites.]

2. **Bash** — create the Issue via `--body-file` (Section F.4 mandatory because the body contains `\n#` patterns):

   ```bash
   gh issue create --title "[SDD Child] <parent title> - <sub-feature name>" --body-file /tmp/sdd-child-issue-$1-<seq>.md --label "sdd:analyze" --label "sdd:child"
   ```

   Substitute literally:
   - `<parent title>` → Issue `$1`'s title (from Step 1's `gh issue view`)
   - `<sub-feature name>` → the sub-feature's short name from Step 9
   - `<seq>` → 1-based index

3. **Observe** the command's output URL (e.g. `https://github.com/<owner>/<repo>/issues/123`). Extract the trailing integer (`123`) as the new child Issue number. Append to a running list `<children-list>` (comma-separated, e.g. `#101,#102,#103`).

Repeat Step 17b for every sub-feature in Step 9's enumeration.

[PRESERVE — `spec/stage/design.md` §5 (title format, label set, body-file path scheme); `design_work.md` Step 16b lines 132–142; `design/stage-designs/design.md` §10.2.]

#### Step 17c: Post children-list comment on parent

After every child created in Step 17b, post the parent's children-list comment. Use the template `<<SKILL_DIR>>/templates/<lang>/output_children.md` from Step 10 — fill one table row per child (number, title, sub-feature, status).

Section F flow:

1. **Write tool** — render the children-list body to `/tmp/sdd-children-output-$1.md`. Body starts with `<!-- sdd:children:output -->` (first line) and ends with `<!-- /sdd:children:output -->`.

2. **Bash** — duplicate-prevention search:
   ```bash
   gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | select(.body | contains("<!-- sdd:children:output -->")) | .id'
   ```
   (Defensive — Step 17a's guard already established this is empty, but the search is idempotent and matches the canonical Section F pattern.)

3. **Bash** — branch:
   - **Empty** → `gh issue comment $1 --body-file /tmp/sdd-children-output-$1.md`
   - **Has id `<id>`** → `gh api repos/<owner>/<repo>/issues/comments/<id> -X PATCH --field body=@/tmp/sdd-children-output-$1.md`

Internal work-phase signal: `WORK CHILDREN: <children-list>` (with the freshly-created list). Continue to §4 reviews.

[PRESERVE — `spec/stage/design.md` §5 Children list comment; `design_work.md` Step 16c lines 144–154; `design/stage-designs/design.md` §10.3.]

### Work return-value handling (internal to this sub-agent)

After Step 15 (and Step 17 if CHILDREN path) completes, branch on the work outcome:

- Work produced `WORK SINGLE` → continue to §4 reviews; record `path = SINGLE`.
- Work produced `WORK CHILDREN: <children-list>` → continue to §4 reviews; record `path = CHILDREN`, `children = <children-list>`.
- Any unrecoverable error (gh API failure, template load failure, Step 0 Section C `FAIL: ...`, child creation failure, etc.) → return `FAIL: <reason>` from this sub-agent immediately. Do NOT proceed to reviews.

---

## §4. Phase 2 — Reviews (SERIAL inside this sub-agent)

Three reviewers execute **one after another**. Each reviewer reads ONLY its role-specific rubric, optionally performs bounded codebase exploration, posts under its marker, and produces a PASS/FAIL verdict + findings JSON.

[PRESERVE — independence invariant from `design/stage-designs/design.md` §4.4]:
Each reviewer's reasoning context cannot see other reviewers' verdicts during its own evaluation. Even though execution is serial, structure each reviewer's work as a **fresh logical pass** — do NOT feed Reviewer 2 the comment body that Reviewer 1 just posted; do NOT let Reviewer 3 see Reviewers 1+2's verdicts. The only shared inputs are the analyze output and the design output under their respective markers.

[PRESERVE — `design_review.md` line 81 / `design_adversarial.md` line 79]: Write tool permitted only for rendering the comment body to the deterministic temp path. Edit / NotebookEdit forbidden inside reviewer logic.

### §4.1. Reviewer 1: completeness

1. Read `<<SKILL_DIR>>/commands/atoms/rubrics/design-completeness.md`.

2. Read the current design output and the analyze output from the Issue (fresh fetch — do NOT reuse the in-memory body from §3):

   ```bash
   gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | select(.body | contains("sdd:analyze:output") or contains("sdd:design:output")) | .body'
   ```

   If the design output substring is empty → return `FAIL: design output not found on Issue #$1` from this sub-agent.

3. If this is a child Issue (per §3 Step 2 parent detection), also re-fetch the parent's design output for architectural consistency:

   ```bash
   gh api repos/<owner>/<repo>/issues/<parent>/comments --jq '.[] | select(.body | contains("sdd:design:output")) | .body'
   ```

4. **Optional codebase exploration** per `<<SKILL_DIR>>/commands/atoms/_review_helpers.md` Section D. Verify any code references in the design output against actual files. Budget: **15 Read / 10 Grep / 5 Glob** per reviewer. Track your own counts; if a cap is reached, stop exploration, note `rule_id: exploration-budget-exceeded` severity `minor`, and proceed to verdict.

5. Apply the completeness rubric — analyze→design coverage, impact scope, constraints + mitigations, PR split logical/independently-deliverable, architecture consistent with codebase patterns, **Testability section present** (false `N/A` → critical), cross-stage analyze→design checks, child consistency (if child), and codebase verification of file/symbol references. Severity definitions:
   - **critical** — missing required item that prevents downstream implement; false Testability `N/A`
   - **major** — inconsistency, poor PR-split, significant coverage gap; codebase reference discrepancy
   - **minor** — style, wording, or non-blocking clarification suggestion

6. **Determine verdict** per Common Contracts §5 B.3:
   - Any `critical` or `major` finding → **FAIL** (with one-line summary)
   - Only `minor` findings or none → **PASS**

7. **Compose comment body** for marker `<!-- sdd:review:design:completeness -->`:

   ```
   <!-- sdd:review:design:completeness -->
   ## AI Review (design / completeness)

   **Verdict:** PASS | FAIL
   **Model:** <opus|sonnet|haiku|fable>

   ### Issues
   - **[critical]** <description>
   - **[major]** <description>
   - **[minor]** <description>

   ### Suggestions
   <if any>

   <!-- sdd:findings:json -->
   ```json
   {<structured findings per _review_helpers.md Section B.2>}
   ```
   <!-- /sdd:findings:json -->
   <!-- /sdd:review:design:completeness -->
   ```

   Set `stage: "design"`, `role: "completeness"`, `issue: <N>`, `pr: null`, `round: <current round>`, `verdict`, `model` (the sub-agent's actual model — `fable` at `depth = deep`, `sonnet` at `depth = shallow`, otherwise `opus`; record what's accurate), `findings` array, `suggestions` array.

8. **Post via Section F** (mandatory temp-file pattern):
   - **Write tool** → `/tmp/sdd-review-design-completeness-$1.md`
   - **Bash** duplicate-prevention search:
     ```bash
     gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | select(.body | contains("<!-- sdd:review:design:completeness -->")) | .id'
     ```
   - **Bash** branch:
     - Empty → `gh issue comment $1 --body-file /tmp/sdd-review-design-completeness-$1.md`
     - Has id `<id>` → `gh api repos/<owner>/<repo>/issues/comments/<id> -X PATCH --field body=@/tmp/sdd-review-design-completeness-$1.md`

9. **Record internal verdict** for the §5 verdict combiner: `completeness_verdict = PASS | FAIL`, plus a one-line summary if FAIL. Move on to §4.2.

If any step above raises an atom-level error (gh API failure, missing design output, etc.), return `FAIL: <reason>` from this sub-agent immediately. Do NOT continue to the next reviewer.

### §4.2. Reviewer 2: quality

Repeat §4.1 with these substitutions:
- Rubric file: `<<SKILL_DIR>>/commands/atoms/rubrics/design-quality.md`
- Marker: `<!-- sdd:review:design:quality -->` (open + close)
- Temp file: `/tmp/sdd-review-design-quality-$1.md`
- Severity definitions:
  - **critical** — risk that would derail the feature if not addressed at this stage; hidden dependency behind a false `N/A` Testability
  - **major** — significant gap in risk identification, feasibility, maintainability, or testability quality (DI seam absent); architectural anti-pattern
  - **minor** — wording improvement, additional suggestion
- Findings JSON `role`: `"quality"`

Re-fetch the design + analyze outputs fresh (do NOT reuse §4.1's fetch). Independence invariant: do NOT incorporate completeness reviewer's verdict into this reviewer's reasoning.

Record `quality_verdict = PASS | FAIL`. Proceed to §4.3.

### §4.3. Reviewer 3: adversarial

Repeat §4.1 with these substitutions:
- Rubric file: `<<SKILL_DIR>>/commands/atoms/rubrics/design-adversarial.md`
- Also read Section E of `<<SKILL_DIR>>/commands/atoms/_review_helpers.md` for the general adversarial reviewer prompt.
- Marker: `<!-- sdd:review:design:adversarial -->` (open + close)
- Temp file: `/tmp/sdd-review-design-adversarial-$1.md`
- Lens: **REFUTE** the design. Apply the 8 stage-specific refutation angles from the rubric with explicit `rule_id`s (`no-alternative-considered`, `parallel-structure-unjustified`, `pr-order-hidden`, `pr-leaves-master-inconsistent`, `pr-boundary-by-convenience`, `critical-risk-deferred`, `fallback-defeats-mitigation`, `pattern-not-found`, `pattern-misdescribed`, `layout-claim-incorrect`, `high-priority-feature-dropped`, `out-of-scope-silently-reintroduced`, `nfr-silently-dropped`, `complexity-glossed`, `external-integration-underspecified`, `testability-seam-missing`, `testability-seam-brittle`, `testability-na-but-side-effects-present`, `contract-drift`, `schema-migration-unspecified`). Must find ≥ 1 weakness OR explicitly justify why none.
- **Codebase verification is mandatory** (per rubric §"Codebase verification (mandatory)"): verify 1–2 file paths cited in the design exist (Read/Glob); verify 1 architectural pattern claim by reading cited code.
- Severity guidance from the rubric:
  - **critical** — refutation that would block correct implementation (e.g. `pr-order-hidden`, `critical-risk-deferred`, `pattern-not-found`, `high-priority-feature-dropped`, `testability-na-but-side-effects-present`, `contract-drift`)
  - **major** — gap that would cause rework in implement (e.g. `parallel-structure-unjustified`, `nfr-silently-dropped`, `testability-seam-missing`, `complexity-glossed` against external-systems steps)
  - **minor** — worthwhile question that does not block (e.g. `pr-boundary-by-convenience`, `complexity-glossed` on pure-function changes)
- Findings JSON `role`: `"adversarial"`

Re-fetch the design + analyze outputs fresh. Independence invariant: do NOT incorporate completeness or quality verdicts into this reviewer's reasoning.

Record `adversarial_verdict = PASS | FAIL`. Proceed to §5.

---

## §5. Phase 3 — Verdict combination

After all three reviewers have posted, combine per `spec/stage/design.md` §6 / `design/stage-designs/design.md` §5:

| completeness | quality | adversarial | Combined |
|---|---|---|---|
| PASS | PASS | PASS | **PASS** — exit loop, go to §8 Phase 6 |
| PASS | PASS | FAIL | **Adversarial-only FAIL** — log warning, treat as FAIL (R6) |
| FAIL | * | * | **FAIL** — retry or escalate |
| * | FAIL | * | **FAIL** — retry or escalate |

Atom-level `FAIL: <reason>` from any reviewer (NOT a verdict — an error) is already handled in §4 (the sub-agent returned immediately). It does not reach this combiner.

### Adversarial-only FAIL warning (R6)

If `completeness_verdict == PASS && quality_verdict == PASS && adversarial_verdict == FAIL`, log to the sub-agent's narrative (which becomes part of stdout the main session may show):

> ⚠ Adversarial reviewer alone identified critical/major issues. Other reviewers passed. Surfacing for user awareness.

Then treat the combined verdict as **FAIL** for round-decision purposes. R6 keeps current behavior — retry not auto-pass.

[PRESERVE — `spec/stage/design.md` §7 Adversarial-only FAIL escalation; `design/stage-designs/design.md` §5; R6 keep-current-behavior decision.]

### Round decision

- All 3 PASS → exit loop → §8 Phase 6 (Normal path).
- FAIL and `round < 3` → §6 Phase 4 (retry).
- FAIL and `round == 3` → §7 Phase 5 (escalation gate).

---

## §6. Phase 4 — Retry loop (rounds 2 and 3)

Increment `round` (now 2 or 3). Re-enter §3 with retry semantics:

1. Step 0 collapses to `_review_helpers.md` Section C self-fetch (no preflight items). Per `spec/00-common-contracts.md` §7 + `_preflight.md` Section E.
2. Steps 1–15 re-execute, addressing every `critical` and `major` finding from `<retry-findings>`.
3. Step 15's duplicate-prevention search WILL find the existing `<!-- sdd:design:output -->` comment id and PATCH it in place (round-to-round overwrites, not appends). [PRESERVE — Common Contracts §4 Update-in-place invariant.]
4. **CHILDREN idempotency guard (Step 17a) is load-bearing across retry rounds.** If round 1 was CHILDREN, the prior round's `<!-- sdd:children:output -->` and child Issues persist. Step 17a detects this and skips Step 17b + 17c. The same `<children-list>` propagates into the §8 Phase 6 return value. [PRESERVE — `spec/stage/design.md` §8 Edge Case "Retry mode with OK CHILDREN"; `design/stage-designs/design.md` §6 "Children idempotency note" load-bearing; `design_work.md` line 188.]
5. Re-run all 3 reviewers (§4.1 → §4.2 → §4.3) against the UPDATED `<!-- sdd:design:output -->`. Reviewer prompts are unchanged across rounds — reviewers always evaluate the CURRENT state of the output marker. Each reviewer's comment is PATCHed in place under its marker.
6. Re-combine verdicts (§5).
7. If still FAIL on round 3 → §7. If PASS at any round → exit loop → §8.

[PRESERVE — `spec/stage/design.md` §4 Rounds 2 & 3 retry; `_review_helpers.md` Section C; v0.36 atom-side self-fetch.]

---

## §7. Phase 5 — Escalation gate (Round 3 FAIL only)

Triggered when `round == 3` AND the combined verdict from §5 is FAIL.

### Step 1: Compose escalation summary

Build a one-line summary listing remaining `critical` and `major` findings with role labels, plus the path:

```
design round 3 FAIL — findings: [critical] <N>, [major] <M> (completeness=<P/F>, quality=<P/F>, adversarial=<P/F>) (path: SINGLE|CHILDREN: #A,#B,#C)
```

Where `<N>` and `<M>` are the counts across all three reviewers' findings arrays (re-derived by reading the latest three review comment JSON blocks if needed — use the Section B.4 parsing pattern). `path` carries SINGLE or CHILDREN with the child list so the user has full context.

### Step 2: Read `.github/.sdd-config` for skip-review

Use the Read tool on `.github/.sdd-config`. If the file does not exist or has no `skip-review:` line → treat as empty.

Parse the comma-separated list at the `skip-review:` key. Trim whitespace per entry. Valid entries: `analyze`, `design`, `implement`, `pr`, `qa`.

### Step 3: Branch on skip-review for `design`

- **`design` IS in skip-review** → log to the sub-agent narrative:
  > ⚠ Round 3 FAIL; `skip-review: design` is set — auto-continuing with findings persisted on Issue. No user prompt.

  Proceed to §8 Phase 6 **Normal path**. Do NOT return `ESCALATE`.

- **`design` is NOT in skip-review** → return `ESCALATE: <summary from Step 1>` from this sub-agent. Main session handles `AskUserQuestion` per `design/01-sub-agent-contract.md` §3 + §6.

[PRESERVE — `spec/stage/design.md` §4 Phase 1.5 Skip-review semantics: gate skip only; AI review always ran (it just failed). Findings remain on GitHub for human follow-up.]
[PRESERVE — `design/01-sub-agent-contract.md` §4: sub-agent NEVER calls `AskUserQuestion`. Sub-agent surfaces decision to main via `ESCALATE:`; main handles the interactive prompt.]
[PRESERVE — `design/stage-designs/design.md` §7.3: ESCALATE does NOT roll back posted artifacts — design comment + (if applicable) children list + child Issues persist. On Continue, Phase 6 simply transitions the parent label.]

---

## §8. Phase 6 — Output

Two exit paths, distinguished by `path` (SINGLE vs CHILDREN). No `OK NO_ACTION` for design — that classification lives only in analyze.

### Normal path

Triggered when:
- All 3 reviewers PASSed at any round (rounds 1, 2, or 3), OR
- Round 3 FAILed and `skip-review: design` auto-continued (§7 Step 3 first branch), OR
- `$3 == "continue-after-escalation"` short-circuit (§2 Resume short-circuit).

Return based on `path`:

- `path == SINGLE`:
  ```
  >>> RESULT <<<
  OK ADVANCE: implement SINGLE
  ```
- `path == CHILDREN`:
  ```
  >>> RESULT <<<
  OK ADVANCE: implement CHILDREN: #A,#B,#C
  ```
  (Substitute the literal `<children-list>` captured in §3 Step 17b or §3 Step 17a re-derivation or §2 Resume short-circuit re-derivation.)

The main session will set the parent's label `sdd:design` → `sdd:implement` after parsing this return. On CHILDREN path, the parent **pauses** at `sdd:implement` — the surrounding flow (`/sdd auto`, `/sdd batch`, or interactive selection) queues children for analyze. The parent does NOT auto-advance through implement/test until all children reach `sdd:done` (parent-pause invariant per Common Contracts §1).

[PRESERVE — `design/stage-designs/design.md` §8.1 / §8.3 / §8.4; `01-sub-agent-contract.md` §4: this sub-agent NEVER sets labels itself. Label transitions are the main session's sole responsibility.]
[PRESERVE — `spec/stage/design.md` §9 Cross-Stage Invariant #4: parent stops at `sdd:implement` after CHILDREN creation.]

---

## Return contract (verbatim from `design/01-sub-agent-contract.md` §2)

Return EXACTLY one line, prefixed by the `>>> RESULT <<<` sentinel on its own preceding line. The line before the sentinel may contain narrative — main session ignores until it sees the sentinel.

| Return | Meaning |
|---|---|
| `OK ADVANCE: implement SINGLE` | Reviews passed (or skip-review auto-continued, or resume short-circuit); main transitions label to `sdd:implement` and either inline-reads `implement.md` (skip-review.implement) or asks user. |
| `OK ADVANCE: implement CHILDREN: #A,#B,#C` | Multi-PR path; design + children created; parent paused at `sdd:implement`; main session queues children for analyze. |
| `OK PAUSE` | User chose Pause at an escalation gate (skip-review OFF) — only emitted on a `continue-after-escalation` resume after Pause is later re-routed; not used on first FAIL. |
| `ESCALATE: <summary>` | Round 3 FAIL in interactive mode — main asks user Continue / Pause / Stop. |
| `FAIL: <reason>` | Atom-level error (Issue Validation failed, analyze output missing, gh API failed, retry slot value rejected, missing design output for reviewer, child creation failed, etc.) — main stops. |

### Examples

```
>>> RESULT <<<
OK ADVANCE: implement SINGLE
```

```
>>> RESULT <<<
OK ADVANCE: implement CHILDREN: #101,#102,#103
```

```
>>> RESULT <<<
ESCALATE: design round 3 FAIL — findings: [critical] 2, [major] 1 (completeness=FAIL, quality=PASS, adversarial=FAIL) (path: SINGLE)
```

```
>>> RESULT <<<
FAIL: analyze output not found on Issue #42
```

[PRESERVE — load-bearing: sentinel + literal status strings are parsed by main FSM. Do NOT reformat to JSON.]

---

## Markers posted (must match `spec/stage/design.md` §2)

- `<!-- sdd:design:output -->` on parent Issue — work output (design body). Posted by §3 Step 15.
- `<!-- sdd:coverage:ledger -->` on Issue — updated with `e2e_required` per feature from Step 8e. PATCHED in place by §3 Step 15.5.
- `<!-- sdd:children:output -->` on parent Issue (CHILDREN path only) — children-list table. Posted by §3 Step 17c on first-time CHILDREN; preserved across retries by §3 Step 17a idempotency guard.
- `<!-- sdd:child-issue -->` inside each child Issue body (CHILDREN path only) — multilingual `Parent Issue: #<parent>` line. Posted by §3 Step 17b via `gh issue create --body-file`.
- `<!-- sdd:review:design:completeness -->` on parent Issue — Reviewer 1 verdict. Posted by §4.1.
- `<!-- sdd:review:design:quality -->` on parent Issue — Reviewer 2 verdict. Posted by §4.2.
- `<!-- sdd:review:design:adversarial -->` on parent Issue — Reviewer 3 verdict. Posted by §4.3.
- `<!-- sdd:findings:json -->` … `<!-- /sdd:findings:json -->` blocks embedded inside each of the three review comments per Common Contracts §5 schema.

All posted via Section F temp-file pattern with deterministic paths:
- `/tmp/sdd-design-output-$1.md`
- `/tmp/sdd-children-output-$1.md`
- `/tmp/sdd-child-issue-$1-<seq>.md` (one per child)
- `/tmp/sdd-review-design-completeness-$1.md`
- `/tmp/sdd-review-design-quality-$1.md`
- `/tmp/sdd-review-design-adversarial-$1.md`

All updates are in-place (duplicate-prevention search → PATCH if id found, else POST). Round-to-round overwrites the per-marker comment; prior round's body is lost from GitHub (Common Contracts §4 Update-in-place invariant). Child Issues themselves are created exactly once (Step 17a idempotency); their bodies are NOT re-rendered on retry.

---

## Hard rules

- **Single sub-agent.** This file runs as ONE Agent-spawned sub-agent (per `design/01-sub-agent-contract.md`). It MUST NOT spawn further Agent calls. It MUST NOT spawn other sub-agents. (Architectural invariant per Common Contracts §12.)
- **No Skill tool invocations.** Even though Common Contracts §13 confirms sub-agents CAN invoke Skill, the design stage deliberately does not. `/code-review`, `/security-review`, `/verify` are implement-stage only.
- **No label changes.** This sub-agent does NOT call `gh issue edit ... --add-label` or `--remove-label`. Label transitions are the main session's sole responsibility. (Children's `sdd:analyze` + `sdd:child` labels are applied at creation via `gh issue create --label`, which is NOT a label-transition op on the parent.)
- **No `AskUserQuestion`.** Sub-agents are non-interactive. Round 3 FAIL in interactive mode is surfaced via `ESCALATE:`.
- **No branches / commits / PRs.** Design is read-only against the working tree (`design_work.md` Hard rules; `spec/stage/design.md` §2 "Side effects NOT produced"). The sub-agent posts Issue comments and creates child Issues, but no source-file edits.
- **Do NOT modify the analyze output comment.** Strictly read-only against `<!-- sdd:analyze:output -->` (`design_work.md` Hard rules line 187).
- **CHILDREN idempotency is load-bearing.** If `<!-- sdd:children:output -->` already exists on the Issue (retry case), do NOT re-create children — preserve the existing children-list and child Issues, only update the design output. Across retry rounds 2 and 3, the same set of children persists. (`spec/stage/design.md` §5 / §8; `design/stage-designs/design.md` §10.5; `design_work.md` Step 16a line 130 and Hard rule line 188.)
- **All Bash calls follow `<<SKILL_DIR>>/commands/atoms/_bash_rules.md`.** No `&&`, `||`, `;`, `|`, `$(...)`, `VAR=$(...)`, redirections, or quoted variable expansion. No `find` against `/`, `~`, `/Users`, or paths outside the repo root.
- **All comment posting follows `<<SKILL_DIR>>/commands/atoms/_review_helpers.md` Section F.** Write tool → temp file → `gh issue comment --body-file <path>` or `gh api ... -X PATCH --field body=@<path>`. Inline `--body` with multi-line content is forbidden (Common Contracts §9). The same Section F.4 constraint applies to `gh issue create --body-file` for child Issue creation.
- **Independence invariant for reviewers.** Each reviewer (§4.1, §4.2, §4.3) reasons from a fresh logical pass — only the design + analyze outputs are shared input; no cross-visibility of verdicts. Re-fetch the design output for each reviewer.
- **Retry rounds overwrite.** Per-marker comments are PATCHed in place across rounds (Common Contracts §4 Update-in-place invariant). Child Issues themselves are NOT recreated.
- **Stay within the repository.** Do not Read absolute paths outside the working tree. Do not modify files outside `.github/` or the working tree. Edit / NotebookEdit are forbidden. The Write tool is permitted ONLY for rendering comment bodies and child Issue bodies to the deterministic `/tmp/sdd-*-$1*.md` paths.

---

## Cross-references

- Spec contract: `spec/stage/design.md`
- Cross-cutting rules: `spec/00-common-contracts.md`
- Multilingual: `spec/02-multilingual.md`
- Architecture: `design/00-architecture.md`
- Sub-agent contract: `design/01-sub-agent-contract.md`
- Per-stage design: `design/stage-designs/design.md`
- Companion stage: `<<SKILL_DIR>>/commands/atoms/stage_analyze.md` (precondition source)
- Rubric files: `<<SKILL_DIR>>/commands/atoms/rubrics/design-{completeness,quality,adversarial}.md`
- Shared helpers: `<<SKILL_DIR>>/commands/atoms/_preflight.md` (Medium tier Step 0), `<<SKILL_DIR>>/commands/atoms/_review_helpers.md` (Sections B/C/D/E/F), `<<SKILL_DIR>>/commands/atoms/_bash_rules.md`, `<<SKILL_DIR>>/commands/atoms/_multilingual.md`
- Output templates: `<<SKILL_DIR>>/templates/<lang>/output_design.md`, `output_children.md`, `output_child_issue.md`
