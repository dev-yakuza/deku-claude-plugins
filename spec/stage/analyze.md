# Stage: Analyze

Requirements analysis stage (What / Why only — no How). Sources: `commands/analyze.md`, `commands/atoms/analyze_work.md`, `commands/atoms/analyze_review.md`, `commands/atoms/analyze_adversarial.md`, `commands/ai-review-analyze-{completeness,quality,adversarial}.md`, `templates/en/output_analyze.md`.

---

## 1. Stage Inputs

### Entry conditions
- `$1` — Issue number passed by `/sdd analyze $1`, `/sdd resume`, or auto-proceed from `init`. Validated as Issue (not PR) per Common Contracts §10. (`analyze.md` lines 11–13) [PRESERVE]
- Label state: typically no label, `sdd:analyze`, or initial entry. (Label not strictly checked at stage entry — the stage runs whenever invoked.) [PRESERVE]
- No prior stage outputs required. Analyze is the first stage. (Confirmed by `ai-review-analyze-completeness.md` line 6, `ai-review-analyze-quality.md` line 6: "Not applicable — analyze is the first stage.") [PRESERVE]

### Environmental dependencies
- `gh` CLI authenticated for current repo. [PRESERVE]
- `.github/.sdd-lang` (optional) — read by `analyze_work` Step 7 for template language. Falls back to Issue body language detection, then `en`. (`analyze_work.md` line 55) [PRESERVE]
- `.github/.sdd-config` (optional) — read for `skip-review: analyze` semantics. (`analyze.md` Phase 1.5 and Phase 2) [PRESERVE]
- Issue labels — read in Phase 0 for depth detection. (`analyze.md` lines 17–25) [PRESERVE]
- Parent Issue context (if child) — fetched per Common Contracts → Parent/Child Issue Detection. (`analyze_work.md` Step 2, lines 33–39) [PRESERVE]

---

## 2. Stage Outputs

### Markers posted
- `<!-- sdd:analyze:output -->` on the Issue (analysis body or no-action explanation) by `analyze_work`. (`analyze_work.md` Step 8, line 57, line 89) [PRESERVE]
- `<!-- sdd:review:analyze:completeness -->` by `analyze_review` (role=completeness). (`analyze_review.md` line 45) [PRESERVE]
- `<!-- sdd:review:analyze:quality -->` by `analyze_review` (role=quality). (`analyze_review.md` line 45) [PRESERVE]
- `<!-- sdd:review:analyze:adversarial -->` by `analyze_adversarial`. (`analyze_adversarial.md` line 38) [PRESERVE]
- `<!-- sdd:findings:json -->` … `<!-- /sdd:findings:json -->` block embedded inside each review comment. (`analyze_review.md` lines 71–76; `analyze_adversarial.md` line 40) [PRESERVE]

### Labels transitioned to
- `sdd:done` — when Phase 1 returned `OK NO_ACTION` and either skip-review is set or the user approves closing. (`analyze.md` Phase 2 No-Action path, lines 138, 142) [PRESERVE]
- `sdd:design` — when reviews completed and (skip-review set OR user approved). (`analyze.md` Phase 2 Normal path, lines 150, 155) [PRESERVE]

### State changes
- Self-review trace `<details>` block appended inside `<!-- sdd:analyze:output -->` comment when blockers were fixed inline. (`analyze_work.md` Step 11, lines 72–86) [PRESERVE]
- Comments updated in-place across retry rounds (duplicate-prevention pattern from Common Contracts §9). Round-to-round overwrites, not appends. (`analyze_work.md` Step 12; `analyze_review.md` Step 7; `analyze_adversarial.md` Step 7) [PRESERVE — but see Common Contracts §4 RETHINK on round preservation]

### Side effects NOT produced by analyze stage
- No branches, no commits, no PRs. Analyze is read-only against the working tree. (`analyze_work.md` line 129: "Stay within the current repository. Do not modify files outside `.github/` or the working tree.") [PRESERVE]

---

## 3. Atom Inventory

| Atom | Role | Model (default / deep / shallow) | Key responsibility |
|---|---|---|---|
| `analyze_work` | Producer | opus / opus / opus | Generate Stage 1 analysis output, post under `<!-- sdd:analyze:output -->`. Handles first-round and retry mode. |
| `analyze_review` (role=`completeness`) | Reviewer | sonnet / opus / sonnet | Verify requirements coverage and internal consistency. Verdict: PASS/FAIL with findings JSON. |
| `analyze_review` (role=`quality`) | Reviewer | sonnet / opus / sonnet | Evaluate risks, edge cases, unstated assumptions, pattern alignment. Verdict: PASS/FAIL. |
| `analyze_adversarial` | Reviewer (refuter) | opus / opus / sonnet | Actively REFUTE the analysis. Must find at least one weakness or justify why none. |

Model table source: `analyze.md` lines 31–36 (canonical in `_review_helpers.md` Section A.2, mirrored in Common Contracts §3 / `01-config.md` §3). [PRESERVE]

All four atoms are single-subagent terminal workers: MUST NOT spawn subagents and MUST NOT call Agent/Skill tools (`analyze_work.md` line 127–128; `analyze_review.md` line 101; `analyze_adversarial.md` line 67). [PRESERVE — architectural invariant per Common Contracts §12]

---

## 4. Phase-by-Phase Behavior

### Phase 0: Depth label detection
- Read Issue labels via `gh issue view $1 --json labels --jq '[.labels[].name]'`. (`analyze.md` line 21) [PRESERVE]
- Decision:
  - Contains `sdd:review:deep` → depth = `deep`
  - Contains `sdd:review:shallow` → depth = `shallow`
  - Otherwise → depth = `default`
- Depth value selects models for each Agent spawn per the Phase 0 table. (`analyze.md` lines 23–27) [PRESERVE]

### Phase 1: Analyze + AI Review Loop (max 3 rounds)
Each round = 1 work atom call → 3 parallel review atom calls → verdict combination → round decision. (`analyze.md` line 40) [PRESERVE]

**Round 1 — Step 1.1 (work atom spawn)**:
- `subagent_type: general-purpose`, `model: opus`, `description: analyze work for #$1`.
- Prompt instructs subagent to read `analyze_work.md` and execute for Issue `#$1`, returning `>>> RESULT <<<` line. (`analyze.md` lines 44–52) [PRESERVE]
- Parse the result:
  - `FAIL: <reason>` → orchestrator reports failure and stops; no reviews run. (line 54) [PRESERVE]
  - `OK NO_ACTION` → skip reviews entirely, jump to Phase 2 No-Action path. (line 55) [PRESERVE]
  - `OK` → continue to Step 1.2. (line 56) [PRESERVE]

**Round 1 — Step 1.2 (parallel review spawn)**:
- Three Agent tool calls in a **single message** for parallelism. (`analyze.md` line 58) [PRESERVE]
- Agent A: `analyze_review.md` with role `completeness`. Model per Phase 0 table.
- Agent B: `analyze_review.md` with role `quality`. Model per Phase 0 table.
- Agent C: `analyze_adversarial.md`. Model per Phase 0 table.
- All three reviewers operate **independently** — no cross-visibility of each other's verdicts. (`analyze.md` line 162) [PRESERVE]
- Each returns `>>> RESULT <<<` with `OK PASS` / `OK FAIL: <summary>` / `FAIL: <reason>`. (`analyze_review.md` lines 84–95; `analyze_adversarial.md` lines 51–62) [PRESERVE]

**Round 1 — Step 1.3 (round decision)**:
- Any reviewer returns `FAIL: <reason>` (atom error, not verdict) → report failure and stop. (`analyze.md` line 85) [PRESERVE]
- All three return `OK PASS` → reviews passed, break loop, proceed to Phase 2. (line 87) [PRESERVE]
- Any `OK FAIL` → combine summaries; check adversarial-only escalation (see §6); decide whether to retry. (lines 88–89) [PRESERVE]
- Reviews failed and round < 3 → spawn next round's work atom in **retry mode** (Round 2/3). (line 93) [PRESERVE]
- Reviews failed and round == 3 → exit loop, go to Phase 1.5. (line 94) [PRESERVE]

**Rounds 2 & 3 (retry)**:
- Identical to Round 1 except `$2 = "retry"` is passed to the work atom. (`analyze.md` lines 98–103) [PRESERVE]
- Orchestrator does **NOT** fetch review comments or extract JSON itself — the atom self-fetches per `_review_helpers.md` Section C. This is the v0.36 main-session token-savings change. (line 93) [PRESERVE]
- Review atom prompts are unchanged between rounds — reviewers always evaluate the **current** state of `<!-- sdd:analyze:output -->`. (`analyze.md` line 105) [PRESERVE]

### Phase 1.5: Round 3 Escalation Gate
Triggered only when round 3 also failed. (`analyze.md` line 108) [PRESERVE]

1. Fetch latest review findings (same extraction as retry mode). (line 111) [PRESERVE]
2. Render summary listing remaining `critical` and `major` findings with role label. (lines 112–118) [PRESERVE]
3. Branch on skip-review:
   - `analyze` in skip-review → log to Issue comment + orchestrator output, auto-continue to Phase 2 without prompting. Do NOT call `AskUserQuestion`. (lines 121–123) [PRESERVE]
   - Interactive (no skip-review) → ask user: Continue / Pause / Stop. (line 125)
     - Continue → Phase 2.
     - Pause → orchestrator stops; resume via `/sdd resume <N>`.
     - Stop → exit cleanly. (lines 126–128) [PRESERVE]

### Phase 2: User Review / Advance
Two paths:

**No-Action path** (`OK NO_ACTION` from Phase 1, reviews skipped):
1. Check `skip-review: analyze` setting from `.github/.sdd-config`. (`analyze.md` line 134) [PRESERVE]
2. Skip-review set: log "No action needed — skipping remaining stages", set label `sdd:done`, do NOT proceed to design. (lines 135–138) [PRESERVE]
3. Skip-review NOT set: present the no-action explanation, ask "Close as no-action?". Approve → `sdd:done`. Reject + user provides context → re-run Phase 1 from Round 1. (lines 139–143) [PRESERVE]

**Normal path** (reviews completed):
1. Check skip-review setting. (line 147) [PRESERVE]
2. Skip-review set: log, set label `sdd:design`, **inline auto-proceed** by reading `commands/design.md` and executing in same main session. Do NOT spawn a subagent for the next stage. (lines 150–151) [PRESERVE — load-bearing: spawning would nest atoms]
3. Skip-review NOT set: summarize round outcome to user, ask for direction confirmation. Approve → set `sdd:design`. Do NOT auto-proceed — user invokes `/sdd design $1` or `/sdd resume $1`. (lines 152–156) [PRESERVE]

---

## 5. Decision Tables

### Round verdict combination (per round)
| completeness | quality | adversarial | Outcome |
|---|---|---|---|
| PASS | PASS | PASS | Loop exits, proceed to Phase 2 |
| PASS | PASS | FAIL | Adversarial-only FAIL — log warning, treat as FAIL, retry/escalate |
| FAIL | * | * | FAIL — retry/escalate |
| * | FAIL | * | FAIL — retry/escalate |
| Any `FAIL: <reason>` (atom error) | — | — | Orchestrator stops |

Source: `analyze.md` lines 86–89. [PRESERVE]

### Round retry decision
| Round | Verdict | Action |
|---|---|---|
| 1 or 2 | PASS | Exit loop → Phase 2 |
| 1 or 2 | FAIL | Spawn next round's work atom with `$2 = "retry"` |
| 3 | PASS | Exit loop → Phase 2 |
| 3 | FAIL | → Phase 1.5 escalation gate |

Source: `analyze.md` lines 92–94. [PRESERVE]

### No-action detection (in `analyze_work` Step 4)
A request is classified **no-action** if ANY of:
- Reported issue is not reproducible and lacks evidence
- Issue has already been fixed (verified via recent commits/PRs)
- Request is out of scope or duplicate
- Described behavior is working as intended

Source: `analyze_work.md` lines 43–48. [PRESERVE]

On no-action: skip Steps 5–7 (feature list, priorities, language template), prepare brief explanation, still embed under `<!-- sdd:analyze:output -->` marker. (`analyze_work.md` line 49, line 57) [PRESERVE]

### Verdict per reviewer (severity → verdict)
| Findings severity | Verdict |
|---|---|
| any `critical` or `major` | FAIL |
| only `minor` or none | PASS |

Source: `analyze_review.md` lines 39–41; `analyze_adversarial.md` lines 33–35. [PRESERVE — matches Common Contracts §5 Verdict rule]

---

## 6. AI Review Specifics

### Three parallel reviewers
- Spawned in a **single message** with 3 Agent tool calls to ensure concurrent execution. (`analyze.md` line 58) [PRESERVE]
- Independent contexts — no reviewer sees another's verdict during evaluation. (line 162) [PRESERVE]

### Review comment markers (one per role)
- `<!-- sdd:review:analyze:completeness -->`
- `<!-- sdd:review:analyze:quality -->`
- `<!-- sdd:review:analyze:adversarial -->`

Each comment body includes:
- Verdict line (PASS | FAIL)
- Model name (opus | sonnet | haiku)
- `### Issues` with `[critical]`/`[major]`/`[minor]` entries
- `### Suggestions` (optional)
- `<!-- sdd:findings:json -->` … `<!-- /sdd:findings:json -->` block per Common Contracts §5 schema

Source: `analyze_review.md` lines 56–78. [PRESERVE]

### Verdict combination logic
Performed by orchestrator after parsing all three `>>> RESULT <<<` lines:
- All three `OK PASS` → reviews passed.
- Any `OK FAIL` → reviews failed, combine summaries. (`analyze.md` line 88) [PRESERVE]
- Atom-level `FAIL: <reason>` from any reviewer (NOT a verdict, an atom error) → orchestrator stops. (`analyze.md` line 85) [PRESERVE]

### Adversarial-only FAIL escalation
If `OK FAIL` came **only** from `analyze_adversarial` (completeness=PASS, quality=PASS, adversarial=FAIL):
- Log to user: "⚠ Adversarial reviewer alone identified critical/major issues. Other reviewers passed. Surfacing for user awareness." (`analyze.md` line 89) [PRESERVE]
- Then continue to Step 1.3 as a normal FAIL (still triggers retry). (line 89) [PRESERVE]

[RETHINK: rationale is to surface adversarial dissent; but the round still retries as a normal FAIL. Consider whether adversarial-only FAIL should have a separate threshold (e.g. auto-PASS with warning) or whether the current treatment — fail+visible-warning — is correct.]

### Role-specific criteria
- **Completeness** (`ai-review-analyze-completeness.md`): Requirements coverage + internal consistency. 5-item Required Checklist; cross-section consistency. Cross-stage Check N/A. [PRESERVE]
- **Quality** (`ai-review-analyze-quality.md`): Edge cases, ambiguity/unstated assumptions, scope/risk, pattern alignment (no-How discipline). [PRESERVE]
- **Adversarial** (`ai-review-analyze-adversarial.md`): 7 stage-specific refutation angles with explicit `rule_id`s (`requirement-without-evidence`, `dependency-claim-unverified`, `persona-not-served`, `crud-pair-missing`, `unreconciled-tradeoff`, `contradictory-nfr`, `locale-assumption`, `device-assumption`, `priority-unjustified`, `priority-arbitrary`, `out-of-scope-evasion`, `dod-not-measurable`, `dod-no-verification`, `codebase-claim-unverified`). Must find ≥1 weakness or justify why none. [PRESERVE]

[IMPROVE: rule_id list is long and embedded in markdown. Could move to a structured registry for tooling/reporting.]

### Codebase exploration budget (reviewers only)
- All three reviewer atoms MAY use Read/Grep/Glob to verify code references in the analyze output. (`analyze_review.md` line 103; `analyze_adversarial.md` line 70) [PRESERVE]
- Budget: 15 Read / 10 Grep / 5 Glob per atom (per `_review_helpers.md` Section D). [PRESERVE]
- Write tool permitted **only** for rendering the comment body to the deterministic temp path (Common Contracts §9). Edit/NotebookEdit forbidden. [PRESERVE]

---

## 7. Edge Cases

### No-action conclusion
- `analyze_work` Step 4 may classify the Issue as no-action; in that case Steps 5–7 are skipped. The no-action explanation is still posted under `<!-- sdd:analyze:output -->`. (`analyze_work.md` lines 43–49, 57) [PRESERVE]
- Return value: `OK NO_ACTION` (instead of `OK`). (`analyze_work.md` lines 110–111) [PRESERVE]
- Orchestrator routes to Phase 2 No-Action path. Reviews are NOT spawned for no-action. (`analyze.md` line 55, 132) [PRESERVE]

### Retry semantics (atom self-fetch per `_review_helpers.md` Section C)
- Orchestrator passes literal `"retry"` as `$2` for rounds 2 and 3. (`analyze_work.md` line 12) [PRESERVE]
- Atom skips preflight Step 0 normal items and instead executes Section C to fetch the previous round's three review comments by marker. (`analyze_work.md` lines 18–22) [PRESERVE]
- Result is a sorted findings array (`critical → major → minor`) held as `<retry-findings>`. (line 20) [PRESERVE]
- During Main work, atom MUST address every `critical` and `major` finding; use `minor` as supporting context. (line 21) [PRESERVE]
- Section C returns `FAIL: ...` (no review comments found, unrecognized retry slot value, etc.) → atom propagates as its own return value. (line 22) [PRESERVE — guards against silent context loss from legacy pre-v0.36 callers, per Common Contracts §7]
- Step 10 (retry resolution check): before posting, verify every critical/major finding was addressed in the output. Mention how (or — only if genuinely infeasible — why not). (`analyze_work.md` line 70) [PRESERVE]

### Skip-review semantics (`analyze`)
- Skips the **user confirmation gate** only — AI review (Phase 1 + 1.5) always runs. (`analyze.md` line 160; Common Contracts via `01-config.md` §2 critical invariant) [PRESERVE]
- In Phase 1.5, skip-review makes the escalation gate **auto-continue** without `AskUserQuestion`. (`analyze.md` lines 121–123) [PRESERVE]
- In Phase 2 No-Action path, skip-review auto-closes Issue with `sdd:done`. (lines 135–138) [PRESERVE]
- In Phase 2 Normal path, skip-review auto-advances label to `sdd:design` AND inline-executes `commands/design.md` in the same main session. (lines 150–151) [PRESERVE — load-bearing]
  - **Why inline, not subagent**: spawning a subagent here would create nested-subagent spawning when the design orchestrator itself spawns atoms. Claude Code blocks 2-level Agent calls. (line 151; Common Contracts §12) [PRESERVE — architectural constraint]

### Child / parent Issue handling
- `analyze_work` Step 2 detects parent reference in Issue body via multilingual regex `(Parent|상위 |親)Issue: #<number>` (Common Contracts via `02-multilingual.md` §3). (`analyze_work.md` line 33) [PRESERVE]
- If parent found, fetch parent's `sdd:analyze:output` and `sdd:design:output` comments for context. (`analyze_work.md` lines 35–38) [PRESERVE]
- Focus the child's analysis on its sub-feature only. (line 39) [PRESERVE]
- The `sdd:child` label is orthogonal — analyze stage does not set or read it directly. [PRESERVE]

### Self-review (blockers only) — `analyze_work` Step 9
Posting-blocking checks performed by the work atom before posting:
- Marker `<!-- sdd:analyze:output -->` present
- Template required sections filled (Summary, Feature List, Priority — for normal path; no-action explanation for no-action path)
- No `<empty>` / TODO / placeholder text remaining
- Type classification set (one of `new feature` / `enhancement` / `bug fix` / `refactoring`)
- Cross-stage refs valid (parent reference correct if child Issue)

Fix inline; record fixed blockers in `<details>` trace block (Step 11). Quality / completeness / risk evaluation are **NOT** done here — that is the reviewer atoms' job. (`analyze_work.md` lines 59–68) [PRESERVE]

[IMPROVE: the self-review checklist is duplicated across work atoms (analyze/design/test). Single helper definition would DRY.]

### Atom-level FAIL vs review-verdict FAIL
- `FAIL: <reason>` (atom error) → orchestrator stops the entire stage. (`analyze.md` lines 54, 85) [PRESERVE]
- `OK FAIL: <summary>` (review verdict) → counts toward round verdict combination, NOT a stop signal. (`analyze_review.md` lines 89–93; `analyze_adversarial.md` lines 56–62) [PRESERVE]

### Issue Validation (gate before everything)
Before any other step in `analyze.md`, validate `$1` per Common Contracts §10. If `$1` is a PR → stop immediately with no state changes. (`analyze.md` lines 12–13) [PRESERVE]

---

## 8. External Tools / Skills

None invoked from the analyze stage. Analyze is the lightest stage — no `/code-review`, no `/security-review`, no `/verify`. [PRESERVE]

[RETHINK: should adversarial reviewer optionally use `/code-review` for codebase-claim verification? Currently it does manual Read/Grep. Decision: keep manual — analyze stage is intentionally lightweight, and codebase-claim verification is bounded by the §6 Read/Grep/Glob budget.]

---

## 9. Cross-Stage Invariants

Downstream stages (`design`, `implement`, `test`) assume:

1. **`<!-- sdd:analyze:output -->` exists on the Issue** before `design` starts.
   - `design_work` reads it via `gh api ... --jq '.[] | select(.body | contains("sdd:analyze:output"))'`. [PRESERVE]
   - Cascade case: when `skip-review: analyze` is set, the inline auto-proceed guarantees the comment exists before `design.md` is read (work atom posts before returning `OK`). (`analyze.md` line 151; `analyze_work.md` Step 12) [PRESERVE — load-bearing]

2. **Output marker contains the Type classification** (`new feature` / `enhancement` / `bug fix` / `refactoring`).
   - Required by `analyze_work` Step 9 self-review. (`analyze_work.md` line 62) [PRESERVE]
   - Downstream stages may use type to select test/implementation strategy (e.g. bug fix vs new feature). [PRESERVE]

3. **No-action conclusion ends the pipeline.**
   - When `OK NO_ACTION` flows through Phase 2, the Issue is closed with `sdd:done` and never reaches `sdd:design`. (`analyze.md` lines 138, 142) [PRESERVE]

4. **Review comments are queryable across rounds.**
   - Retry mode in any stage's work atom self-fetches by marker. The duplicate-prevention pattern (Common Contracts §9 / `_review_helpers.md` Section F) keeps exactly one comment per marker — the latest round. (Common Contracts §4 Update-in-place invariant) [PRESERVE]
   - **Implication**: prior-round content is lost from GitHub once new round posts. [PRESERVE — but see Common Contracts §4 RETHINK on round-suffixed markers for audit]

5. **Language choice is fixed by analyze stage** (via `analyze_work` Step 7).
   - `.github/.sdd-lang` is read once; subsequent stages re-read the same file. If absent, `analyze_work` falls back to Issue-body language detection — the choice is **not persisted** to `.sdd-lang`. (`analyze_work.md` line 55) [PRESERVE]
   - [IMPROVE: detected language should be persisted to `.sdd-lang` (or recorded in the analyze output) so downstream stages don't re-detect inconsistently.]

6. **Findings JSON schema (Common Contracts §5)** must be present inside every review comment.
   - Downstream tooling (and the work atom's own self-fetch on retry) parses these blocks. (`analyze_review.md` lines 71–76; `analyze_adversarial.md` line 40) [PRESERVE]

7. **Label transitions are the sole stage-completion signal.**
   - `sdd:design` set → analyze stage complete (normal path).
   - `sdd:done` set → analyze stage complete (no-action path).
   - No other side channel (no file, no env var, no in-process state). (Common Contracts §1, §2) [PRESERVE]

---

## Cross-references

- Common Contracts (markers, retry, bash rules, comment posting) → `spec/00-common-contracts.md`
- Skip-review semantics → `spec/01-config.md` §2
- Depth labels / model table → `spec/01-config.md` §3
- Multilingual parent regex → `spec/02-multilingual.md` §3
- Template output structure → `templates/{lang}/output_analyze.md`
