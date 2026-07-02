# STAGE: analyze

**Single sub-agent. MUST NOT spawn Agent calls. MUST NOT spawn other sub-agents. MAY use Skill tool, though analyze stage uses no Skills.**

This file is the Arch B stage sub-agent body for the **Analyze** stage. The main session (or `resume.md` after bootstrap) spawns this sub-agent once per Issue per stage invocation. Internally it inlines the logic of the legacy `analyze_work`, `analyze_review` (completeness + quality), and `analyze_adversarial` atoms — runs them **serially** because the single-level spawn rule (`spec/00-common-contracts.md` §12) forbids nested Agent calls.

The sub-agent owns the entire AI-review retry loop (max 3 rounds), the adversarial-only FAIL warning (R6), the no-action shortcut, and posting all five marker comments via Section F. It does NOT call `AskUserQuestion`, does NOT change labels, and does NOT auto-proceed to design — those are main-session responsibilities. On Round 3 FAIL with skip-review OFF the sub-agent returns an `ESCALATE:` line so main can interactively prompt the user.

> **Bash Command Execution**: every shell snippet below is its own simple Bash tool call. See canonical rules in `<<SKILL_DIR>>/commands/atoms/_bash_rules.md`. Codebase exploration uses **Grep / Glob / Read** tools, not Bash equivalents.

---

## Inputs

- `$1` — Issue number. Already validated as an Issue (not a PR) by the caller, but re-validated here as defense in depth (`spec/00-common-contracts.md` §10).
- `$2` — Depth dial. One of `default` / `deep` / `shallow`. The caller derives this from labels; this sub-agent verifies against the live labels in Phase 0.
- `$3` — Resume hint. One of `none` (default; full execution) or `continue-after-escalation` (skip Phases 1-4; main session already escalated to user and the user chose Continue — work + reviews are already persisted on GitHub). Per `design/01-sub-agent-contract.md` §3 and SYNTHESIS-v2 T1.5.

`Branch` / `PR` fields from the global prompt template (`design/01-sub-agent-contract.md` §1) are not used by analyze and may be omitted or passed as `null`.

---

## §1. Issue Validation (defense in depth)

Before anything else, validate `$1` per Common Contracts §10:

```bash
gh issue view $1 --json url --jq .url
```

- Empty / error → return `FAIL: Issue #$1 does not exist`.
- URL contains `/pull/` → return `FAIL: #$1 is a Pull Request, not an Issue. SDD commands operate on Issues only.` Do NOT modify labels, do NOT post comments.
- URL contains `/issues/` → continue.

[PRESERVE — `spec/stage/analyze.md` §7 Issue Validation; `spec/00-common-contracts.md` §10.]

---

## §2. Phase 0 — Depth detection

Even though `$2` was passed in by the caller, re-read labels here to keep the sub-agent self-contained:

```bash
gh issue view $1 --json labels --jq '[.labels[].name]'
```

Decision (overrides `$2` if labels disagree):
- Labels contain `sdd:review:deep` → `depth = deep`
- Labels contain `sdd:review:shallow` → `depth = shallow`
- Otherwise → `depth = default`

The depth dial selects models used internally for the inlined work and review reasoning per `spec/00-common-contracts.md` §3 / `_review_helpers.md` Section A.2. Since this entire stage runs inside ONE sub-agent context (no inner Agent spawns), the model dial is informational for the sub-agent's reasoning style — the actual model is fixed by the Agent spawn's `model` parameter from main session. **Note (per `_review_helpers.md` Section A.2.1): `analyze.md` spawns this stage with `model: fable` when `depth = deep`, `sonnet` when `depth = shallow`, otherwise `opus` (analyze has no in-context security analysis).** Record the dial for the `<details>` self-review trace, and record the actual model accurately in the findings JSON.

### Resume short-circuit (T1.5)

If `$3 == "continue-after-escalation"`:
- Re-validate the Issue still exists and is still an Issue (Phase 0 above).
- Confirm the three review markers exist on the Issue (just `gh api ... /comments` once and check substring presence for `<!-- sdd:review:analyze:completeness -->`, `:quality`, `:adversarial`).
- Skip directly to **§8 Phase 6** with Normal path (`OK ADVANCE: design`). Work + reviews were already done in the prior spawn; findings remain on GitHub for human follow-up.
- If the three review markers are NOT all present → return `FAIL: continue-after-escalation requested but prior round's review markers missing on #$1`.

---

## §3. Phase 1 — Work (inlined `analyze_work` logic)

This phase produces the analysis output and posts it under `<!-- sdd:analyze:output -->`.

Local state: a counter `round` starting at 1. Rounds 2 and 3 enter this phase via §6.

### Step 0: Preflight (Light tier) or retry self-fetch

- **Round 1** (`round == 1`): follow `<<SKILL_DIR>>/commands/atoms/_preflight.md` Section A — tier **Light**, Section B items 1 + 2 (project conventions + commit message style). Apply Section D failure handling. Record findings for the §3.11 self-review trace.
- **Rounds 2 / 3** (`round > 1`): SKIP the preflight items above. Instead, execute `<<SKILL_DIR>>/commands/atoms/_review_helpers.md` Section C to self-fetch the previous round's three review comments (markers: `<!-- sdd:review:analyze:completeness -->`, `<!-- sdd:review:analyze:quality -->`, `<!-- sdd:review:analyze:adversarial -->`) from Issue `$1`. The procedure returns a sorted findings array (`critical → major → minor`). Hold this array as `<retry-findings>` for use throughout the steps below.
  - If Section C returns `FAIL: ...` (no review comments found, unrecognized retry slot value, etc.) → propagate it as this sub-agent's return value before doing any further work.

[PRESERVE — `spec/stage/analyze.md` §7 Retry semantics; `spec/00-common-contracts.md` §7 Retry Mode Trigger; v0.36 atom-side self-fetch invariant.]

### Step 1: Read the Issue

```bash
gh issue view $1
```

Capture title, body, labels for use in Steps 2–7.

### Step 2: Detect child / parent context (multilingual regex)

Scan the Issue body for the canonical regex from `<<SKILL_DIR>>/commands/atoms/_multilingual.md`:

```
(Parent|상위 |親)Issue: #<n>
```

Per `spec/02-multilingual.md` §3 — `상위` is followed by a space; `親` is NOT followed by a space. If a match is found, capture the parent's `<n>`.

If parent found, fetch the parent's analyze and design outputs:

```bash
gh repo view --json nameWithOwner -q .nameWithOwner
```

Observe the literal `<owner>/<repo>` from output. Then:

```bash
gh api repos/<owner>/<repo>/issues/<parent>/comments --jq '.[] | select(.body | contains("sdd:analyze:output") or contains("sdd:design:output")) | .body'
```

Substitute the literal `<owner>/<repo>` and the literal parent number (e.g. `#42` → `42`). Use parent context to understand broader scope. Focus this analysis on the child's sub-feature only.

[PRESERVE — `spec/stage/analyze.md` §7 Child/parent Issue handling; `spec/02-multilingual.md` §3 multilingual regex.]

### Step 3: Classify request type

From Issue title + body, classify into exactly one of:
- `new feature`
- `enhancement`
- `bug fix`
- `refactoring`

[PRESERVE — `spec/stage/analyze.md` §9 Cross-Stage Invariant #2: downstream stages depend on this Type classification being present in the output marker.]

### Step 4: No-action assessment

Classify the Issue as **no-action** if ANY of the following holds:
- Reported issue is not reproducible AND lacks evidence
- Issue has already been fixed (verify via recent commits / merged PRs — use `git log --oneline -20` or `gh pr list --state merged --search "<keyword>" --limit 3` per `_preflight.md` Section B item 3 if needed)
- Request is out of scope or a duplicate
- Described behavior is working as intended

If no-action → SKIP Steps 5–7 entirely; prepare a brief explanation of why no code change is needed; jump to Step 8 with the no-action body.

[PRESERVE — `spec/stage/analyze.md` §5 No-action detection; `analyze_work.md` Step 4 lines 43–48.]

### Step 5: Feature list (normal path only)

Enumerate the requested features / changes. Focus on **What** and **Why** — no implementation details (no **How**).

[PRESERVE — `spec/stage/analyze.md` Phase 1 Step 5; `analyze_work.md` Step 5 lines 51.]

### Step 6: Priorities (normal path only)

Assign a priority tier to each feature (high / medium / low or P0/P1/P2) with a written justification for each rank.

### Step 7: Language template selection

Determine output language:
1. If `.github/.sdd-lang` exists → read it; use its language code (`en` / `ko` / `ja`).
2. Else detect primary language of the Issue body; map to closest supported (`en` / `ko` / `ja`).
3. Else default to `en`.

Load the template:

```
<<SKILL_DIR>>/templates/<lang>/output_analyze.md
```

(`<lang>` is one of `en`, `ko`, `ja`.) Read the file via the Read tool.

[PRESERVE — `spec/02-multilingual.md` §2 Language Detection; §5 Output Template Files.]

### Step 8: Format output via template

Fill the template fields:
- For **normal path**: Summary (Type + What + Why), Feature List table, Priority table.
- For **no-action path**: replace body sections with a brief no-action explanation. Keep the `<!-- sdd:analyze:output -->` opening marker and `<!-- /sdd:analyze:output -->` closing marker.

The Type classification line MUST be present (one of `new feature` / `enhancement` / `bug fix` / `refactoring`).

If child Issue: include the parent reference using the language-appropriate label (`Parent Issue: #<n>` for `en`, `상위 Issue: #<n>` for `ko`, `親Issue: #<n>` for `ja`).

### Step 9: Self-review (blockers only — posting-blocking checks)

Before posting, verify:
- [ ] Marker `<!-- sdd:analyze:output -->` present (open + close)
- [ ] Template's required sections filled (Summary, Feature List, Priority for normal path; no-action explanation for no-action path)
- [ ] No `<empty>` / TODO / `<...>` placeholder text remaining
- [ ] Type classification set to one of the 4 categories
- [ ] Cross-stage refs valid (parent reference correct if child Issue)

If a blocker fails → fix inline. Track which blockers were fixed for the §3.11 trace.

**Quality / completeness / risk evaluation are NOT done here** — that is the reviewer phase's job (§4). Keep self-review minimal. [PRESERVE — `analyze_work.md` lines 59–68.]

### Step 10: Retry resolution check (rounds 2 / 3 only)

If Step 0 fetched `<retry-findings>`, verify before posting that every `critical` and `major` finding has been addressed in the updated output. Mention how (in the body or in the trace block) — or, only if genuinely infeasible, why it could not be. Treat `minor` entries as supporting context to clarify wording.

If addressing critical/major findings forces a no-action reclassification (rare), follow Step 4's no-action path.

[PRESERVE — `analyze_work.md` Step 10 line 70.]

### Step 11: Append self-review trace

If any blocker was fixed inline in Step 9, OR if Step 0 ran preflight items, append a `<details>` block at the bottom of the body, BEFORE the closing `<!-- /sdd:analyze:output -->` marker:

```markdown
<details>
<summary>Self-review trace (blockers only)</summary>

- [x] Template required sections filled
- [x] Type classification set
- [x] Cross-stage references valid
- [ ] Cross-stage ref to parent #N was misspelled — fixed inline

</details>
```

List only blockers actually checked. `[x]` for clean, `[ ]` with inline note for fixed. Skip the block entirely if there is nothing to record. On retry rounds where Step 0 was skipped, omit the preflight section of the trace.

### Step 12: Post via Section F temp-file pattern

Follow `<<SKILL_DIR>>/commands/atoms/_review_helpers.md` Section F — the mandatory temp-file pattern. Inline `--body` is forbidden because the body contains `\n#` patterns that trip a non-bypassable Claude Code heuristic.

1. **Write tool** — render the analysis body (including markers) to `/tmp/sdd-analyze-output-$1.md`. The file must start with `<!-- sdd:analyze:output -->` on the first line and end with `<!-- /sdd:analyze:output -->`.

2. **Bash** — duplicate-prevention search:

   ```bash
   gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | select(.body | contains("<!-- sdd:analyze:output -->")) | .id'
   ```

   Substitute the literal `<owner>/<repo>` from Step 2 (or re-derive via `gh repo view --json nameWithOwner -q .nameWithOwner` if not held in context).

3. **Bash** — branch on the result:
   - **Empty** → create a new comment: `gh issue comment $1 --body-file /tmp/sdd-analyze-output-$1.md`
   - **Has id `<id>`** → update in place: `gh api repos/<owner>/<repo>/issues/comments/<id> -X PATCH --field body=@/tmp/sdd-analyze-output-$1.md`

[PRESERVE — `spec/00-common-contracts.md` §9 Comment Posting Pattern (Section F mandatory); `spec/00-common-contracts.md` §4 Update-in-place invariant; deterministic temp path `/tmp/sdd-analyze-output-$1.md`.]

### Work return-value handling (internal to this sub-agent)

After Step 12 completes, branch on the work outcome:

- Work produced **no-action body** (Step 4 classified the Issue as no-action) → SKIP §4 reviews entirely; jump to §8 Phase 6 **No-Action path**.
- Work produced **normal body** → continue to §4 reviews.
- Any unrecoverable error (gh API failure, template load failure, Step 0 Section C `FAIL: ...`, etc.) → return `FAIL: <reason>` from this sub-agent immediately. Do NOT proceed to reviews.

---

## §4. Phase 2 — Reviews (SERIAL inside this sub-agent)

Three reviewers execute **one after another**. Each reviewer reads ONLY its role-specific rubric, optionally performs bounded codebase exploration, posts under its marker, and produces a PASS/FAIL verdict + findings JSON.

[PRESERVE — independence invariant from `design/stage-designs/analyze.md` §4]:
Each reviewer's reasoning context cannot see other reviewers' verdicts during its own evaluation. Even though execution is serial, structure each reviewer's work as a **fresh logical pass** — do NOT feed Reviewer 2 the comment body that Reviewer 1 just posted; do NOT let Reviewer 3 see Reviewers 1+2's verdicts. The only shared input is the work output under `<!-- sdd:analyze:output -->`.

[PRESERVE — `analyze_review.md` line 104 / `analyze_adversarial.md` line 71]: Write tool permitted only for rendering the comment body to the deterministic temp path. Edit / NotebookEdit forbidden inside reviewer logic.

### §4.1. Reviewer 1: completeness

1. Read `<<SKILL_DIR>>/commands/atoms/rubrics/analyze-completeness.md`.

2. Read the current analyze output from the Issue (fresh fetch — do NOT reuse the in-memory body from §3):

   ```bash
   gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | select(.body | contains("sdd:analyze:output")) | .body'
   ```

   If empty → return `FAIL: analyze output not found on Issue #$1` from this sub-agent.

3. **Optional codebase exploration** per `<<SKILL_DIR>>/commands/atoms/_review_helpers.md` Section D. Verify any code references in the analyze output against actual files. Budget: **15 Read / 10 Grep / 5 Glob** per reviewer. Track your own counts; if a cap is reached, stop exploration, note `rule_id: exploration-budget-exceeded` severity `minor`, and proceed to verdict.

4. Apply the completeness rubric — requirements coverage and internal consistency. Severity definitions:
   - **critical** — missing required checklist item that prevents downstream design
   - **major** — inconsistency or significant coverage gap
   - **minor** — style, wording, or non-blocking clarification suggestion

5. **Determine verdict** per Common Contracts §5 B.3:
   - Any `critical` or `major` finding → **FAIL** (with one-line summary)
   - Only `minor` findings or none → **PASS**

6. **Compose comment body** for marker `<!-- sdd:review:analyze:completeness -->`:

   ```
   <!-- sdd:review:analyze:completeness -->
   ## AI Review (analyze / completeness)

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
   <!-- /sdd:review:analyze:completeness -->
   ```

   Set `stage: "analyze"`, `role: "completeness"`, `issue: <N>`, `pr: null`, `round: <current round>`, `verdict`, `model` (the sub-agent's actual model — `fable` at `depth = deep`, `sonnet` at `depth = shallow`, otherwise `opus`; record what's accurate), `findings` array, `suggestions` array.

7. **Post via Section F** (mandatory temp-file pattern):
   - **Write tool** → `/tmp/sdd-review-analyze-completeness-$1.md`
   - **Bash** duplicate-prevention search:
     ```bash
     gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | select(.body | contains("<!-- sdd:review:analyze:completeness -->")) | .id'
     ```
   - **Bash** branch:
     - Empty → `gh issue comment $1 --body-file /tmp/sdd-review-analyze-completeness-$1.md`
     - Has id `<id>` → `gh api repos/<owner>/<repo>/issues/comments/<id> -X PATCH --field body=@/tmp/sdd-review-analyze-completeness-$1.md`

8. **Record internal verdict** for the §5 verdict combiner: `completeness_verdict = PASS | FAIL`, plus a one-line summary if FAIL. Move on to §4.2.

If any step above raises an atom-level error (gh API failure, missing analyze output, etc.), return `FAIL: <reason>` from this sub-agent immediately. Do NOT continue to the next reviewer.

### §4.2. Reviewer 2: quality

Repeat §4.1 with these substitutions:
- Rubric file: `<<SKILL_DIR>>/commands/atoms/rubrics/analyze-quality.md`
- Marker: `<!-- sdd:review:analyze:quality -->` (open + close)
- Temp file: `/tmp/sdd-review-analyze-quality-$1.md`
- Severity definitions:
  - **critical** — risk that would derail the feature if not addressed at this stage
  - **major** — significant gap in risk identification or quality
  - **minor** — wording improvement, additional suggestion
- Findings JSON `role`: `"quality"`

Re-fetch the analyze output fresh (do NOT reuse §4.1's fetch). Independence invariant: do NOT incorporate completeness reviewer's verdict into this reviewer's reasoning.

Record `quality_verdict = PASS | FAIL`. Proceed to §4.3.

### §4.3. Reviewer 3: adversarial

Repeat §4.1 with these substitutions:
- Rubric file: `<<SKILL_DIR>>/commands/atoms/rubrics/analyze-adversarial.md`
- Also read Section E of `<<SKILL_DIR>>/commands/atoms/_review_helpers.md` for the general adversarial reviewer prompt.
- Marker: `<!-- sdd:review:analyze:adversarial -->` (open + close)
- Temp file: `/tmp/sdd-review-analyze-adversarial-$1.md`
- Lens: **REFUTE** the analyze output. Apply the 14 `rule_id` registry from the rubric (`requirement-without-evidence`, `dependency-claim-unverified`, `persona-not-served`, `crud-pair-missing`, `unreconciled-tradeoff`, `contradictory-nfr`, `locale-assumption`, `device-assumption`, `priority-unjustified`, `priority-arbitrary`, `out-of-scope-evasion`, `dod-not-measurable`, `dod-no-verification`, `codebase-claim-unverified`). Must find ≥1 weakness OR explicitly justify why none.
- Severity guidance from the rubric:
  - **critical** — refutation that would block correct shipping (contradictory NFRs, scope evasion, false dependency claim)
  - **major** — meaningful gap or unjustified assumption (missing persona, unmeasurable DoD, unverified codebase claim)
  - **minor** — worthwhile question that does not block (priority swap-test, implicit device assumption)
- Findings JSON `role`: `"adversarial"`

Re-fetch the analyze output fresh. Independence invariant: do NOT incorporate completeness or quality verdicts into this reviewer's reasoning.

Record `adversarial_verdict = PASS | FAIL`. Proceed to §5.

---

## §5. Phase 3 — Verdict combination

After all three reviewers have posted, combine per `spec/stage/analyze.md` §5 and `design/stage-designs/analyze.md` §5:

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

[PRESERVE — `spec/stage/analyze.md` §6 Adversarial-only FAIL escalation; `analyze.md` line 89.]

### Round decision

- All 3 PASS → exit loop → §8 Phase 6 (Normal path).
- FAIL and `round < 3` → §6 Phase 4 (retry).
- FAIL and `round == 3` → §7 Phase 5 (escalation gate).

---

## §6. Phase 4 — Retry loop (rounds 2 and 3)

Increment `round` (now 2 or 3). Re-enter §3 with retry semantics:

1. Step 0 collapses to `_review_helpers.md` Section C self-fetch (no preflight items). Per `spec/00-common-contracts.md` §7 + `_preflight.md` Section E.
2. Steps 1–12 re-execute, addressing every `critical` and `major` finding from `<retry-findings>`.
3. Step 12's duplicate-prevention search WILL find the existing `<!-- sdd:analyze:output -->` comment id and PATCH it in place (round-to-round overwrites, not appends). [PRESERVE — Common Contracts §4 Update-in-place invariant.]
4. Re-run all 3 reviewers (§4.1 → §4.2 → §4.3) against the UPDATED `<!-- sdd:analyze:output -->`. Reviewer prompts are unchanged across rounds — reviewers always evaluate the CURRENT state of the output marker. Each reviewer's comment is PATCHed in place under its marker.
5. Re-combine verdicts (§5).
6. If still FAIL on round 3 → §7. If PASS at any round → exit loop → §8.

[PRESERVE — `spec/stage/analyze.md` §6 Rounds 2 & 3 retry; `_review_helpers.md` Section C; v0.36 atom-side self-fetch.]

---

## §7. Phase 5 — Escalation gate (Round 3 FAIL only)

Triggered when `round == 3` AND the combined verdict from §5 is FAIL.

### Step 1: Compose escalation summary

Build a one-line summary listing remaining `critical` and `major` findings with role labels:

```
analyze round 3 FAIL — findings: [critical] <N>, [major] <M> (completeness=<P/F>, quality=<P/F>, adversarial=<P/F>)
```

Where `<N>` and `<M>` are the counts across all three reviewers' findings arrays (re-derived by reading the latest three review comment JSON blocks if needed — use the Section B.4 parsing pattern).

### Step 2: Read `.github/.sdd-config` for skip-review

Use the Read tool on `.github/.sdd-config`. If the file does not exist or has no `skip-review:` line → treat as empty.

Parse the comma-separated list at the `skip-review:` key. Trim whitespace per entry. Valid entries: `analyze`, `design`, `implement`, `pr`, `qa`.

### Step 3: Branch on skip-review for `analyze`

- **`analyze` IS in skip-review** → log to the sub-agent narrative:
  > ⚠ Round 3 FAIL; `skip-review: analyze` is set — auto-continuing with findings persisted on Issue. No user prompt.

  Proceed to §8 Phase 6 **Normal path**. Do NOT return `ESCALATE`.

- **`analyze` is NOT in skip-review** → return `ESCALATE: <summary from Step 1>` from this sub-agent. Main session handles `AskUserQuestion` per `design/01-sub-agent-contract.md` §3 + §6.

[PRESERVE — `spec/stage/analyze.md` §7 Skip-review semantics: gate skip only; AI review always ran (it just failed). Findings remain on GitHub for human follow-up.]
[PRESERVE — `design/01-sub-agent-contract.md` §4: sub-agent NEVER calls `AskUserQuestion`. Sub-agent surfaces decision to main via `ESCALATE:`; main handles the interactive prompt.]

---

## §8. Phase 6 — Output

Two exit paths, distinguished by whether reviews ran.

### No-Action path

Triggered when §3 Work concluded no-action (Step 4) and reviews were skipped.

Return:

```
>>> RESULT <<<
OK NO_ACTION
```

The main session will transition the label to `sdd:done` and close the Issue (or, if skip-review is OFF, present the no-action explanation to the user before closing — that decision is main's, not this sub-agent's).

### Normal path

Triggered when:
- All 3 reviewers PASSed at any round (rounds 1, 2, or 3), OR
- Round 3 FAILed and `skip-review: analyze` auto-continued (§7 Step 3 first branch), OR
- `$3 == "continue-after-escalation"` short-circuit (§2 Resume short-circuit).

Return:

```
>>> RESULT <<<
OK ADVANCE: design
```

The main session will set the label `sdd:design` after parsing this return.

[PRESERVE — `design/stage-designs/analyze.md` §4.§8; `01-sub-agent-contract.md` §4: this sub-agent NEVER sets labels itself. Label transitions are the main session's sole responsibility.]

---

## Return contract (verbatim from `design/01-sub-agent-contract.md` §2)

Return EXACTLY one line, prefixed by the `>>> RESULT <<<` sentinel on its own preceding line. The line before the sentinel may contain narrative — main session ignores until it sees the sentinel.

| Return | Meaning |
|---|---|
| `OK ADVANCE: design` | Reviews passed (or skip-review auto-continued, or resume short-circuit); main transitions label to `sdd:design`. |
| `OK NO_ACTION` | Issue concluded no-action; main transitions label to `sdd:done` and closes. |
| `OK PAUSE` | User chose Pause at an escalation gate (skip-review OFF) — only emitted on a `continue-after-escalation` resume after Pause is later re-routed; not used on first FAIL. |
| `ESCALATE: <summary>` | Round 3 FAIL in interactive mode — main asks user Continue / Pause / Stop. |
| `FAIL: <reason>` | Atom-level error (Issue Validation failed, gh API failed, retry slot value rejected, missing analyze output for reviewer, etc.) — main stops. |

### Examples

```
>>> RESULT <<<
OK ADVANCE: design
```

```
>>> RESULT <<<
OK NO_ACTION
```

```
>>> RESULT <<<
ESCALATE: analyze round 3 FAIL — findings: [critical] 1, [major] 2 (completeness=FAIL, quality=PASS, adversarial=FAIL)
```

```
>>> RESULT <<<
FAIL: #42 is a Pull Request, not an Issue
```

[PRESERVE — load-bearing: sentinel + literal status strings are parsed by main FSM. Do NOT reformat to JSON.]

---

## Markers posted (must match `spec/stage/analyze.md` §2)

- `<!-- sdd:analyze:output -->` on Issue — work output (or no-action explanation). Posted by §3 Step 12.
- `<!-- sdd:review:analyze:completeness -->` on Issue — Reviewer 1 verdict. Posted by §4.1.
- `<!-- sdd:review:analyze:quality -->` on Issue — Reviewer 2 verdict. Posted by §4.2.
- `<!-- sdd:review:analyze:adversarial -->` on Issue — Reviewer 3 verdict. Posted by §4.3.
- `<!-- sdd:findings:json -->` … `<!-- /sdd:findings:json -->` blocks embedded inside each of the three review comments per Common Contracts §5 schema.

All posted via Section F temp-file pattern with deterministic paths:
- `/tmp/sdd-analyze-output-$1.md`
- `/tmp/sdd-review-analyze-completeness-$1.md`
- `/tmp/sdd-review-analyze-quality-$1.md`
- `/tmp/sdd-review-analyze-adversarial-$1.md`

All updates are in-place (duplicate-prevention search → PATCH if id found, else POST). Round-to-round overwrites the per-marker comment; prior round's body is lost from GitHub (Common Contracts §4 Update-in-place invariant).

---

## Hard rules

- **Single sub-agent.** This file runs as ONE Agent-spawned sub-agent (per `design/01-sub-agent-contract.md`). It MUST NOT spawn further Agent calls. It MUST NOT spawn other sub-agents. (Architectural invariant per Common Contracts §12.)
- **No Skill tool invocations.** Even though Common Contracts §13 confirms sub-agents CAN invoke Skill, the analyze stage deliberately does not. `/code-review`, `/security-review`, `/verify` are implement-stage only.
- **No label changes.** This sub-agent does NOT call `gh issue edit ... --add-label` or `--remove-label`. Label transitions are the main session's sole responsibility.
- **No `AskUserQuestion`.** Sub-agents are non-interactive. Round 3 FAIL in interactive mode is surfaced via `ESCALATE:`.
- **No branches / commits / PRs.** Analyze is read-only against the working tree (`analyze_work.md` line 129; `spec/stage/analyze.md` §2).
- **All Bash calls follow `<<SKILL_DIR>>/commands/atoms/_bash_rules.md`.** No `&&`, `||`, `;`, `|`, `$(...)`, `VAR=$(...)`, redirections, or quoted variable expansion. No `find` against `/`, `~`, `/Users`, or paths outside the repo root.
- **All comment posting follows `<<SKILL_DIR>>/commands/atoms/_review_helpers.md` Section F.** Write tool → temp file → `gh issue comment --body-file <path>` or `gh api ... -X PATCH --field body=@<path>`. Inline `--body` with multi-line content is forbidden (Common Contracts §9).
- **Independence invariant for reviewers.** Each reviewer (§4.1, §4.2, §4.3) reasons from a fresh logical pass — only the work output is shared input; no cross-visibility of verdicts. Re-fetch the analyze output for each reviewer.
- **Retry rounds overwrite.** Per-marker comments are PATCHed in place across rounds (Common Contracts §4 Update-in-place invariant).
- **Stay within the repository.** Do not Read absolute paths outside the working tree. Do not modify files outside `.github/` or the working tree. Edit / NotebookEdit are forbidden. The Write tool is permitted ONLY for rendering comment bodies to the deterministic `/tmp/sdd-*-$1.md` paths.

---

## Cross-references

- Spec contract: `spec/stage/analyze.md`
- Cross-cutting rules: `spec/00-common-contracts.md`
- Multilingual: `spec/02-multilingual.md`
- Architecture: `design/00-architecture.md`
- Sub-agent contract: `design/01-sub-agent-contract.md`
- Per-stage design: `design/stage-designs/analyze.md`
- Rubric files: `<<SKILL_DIR>>/commands/atoms/rubrics/analyze-{completeness,quality,adversarial}.md`
- Shared helpers: `<<SKILL_DIR>>/commands/atoms/_preflight.md` (Light tier Step 0), `<<SKILL_DIR>>/commands/atoms/_review_helpers.md` (Sections B/C/D/E/F), `<<SKILL_DIR>>/commands/atoms/_bash_rules.md`, `<<SKILL_DIR>>/commands/atoms/_multilingual.md`
- Output template: `<<SKILL_DIR>>/templates/<lang>/output_analyze.md`
