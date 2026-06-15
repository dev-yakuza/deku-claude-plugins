# Stage Design: analyze

Sub-agent that executes the Analyze stage. Spawned once per Issue per stage invocation.

---

## 1. Sub-agent purpose

`stage_analyze` is the Arch B stage sub-agent for requirements analysis (What / Why only — no How). It consumes an Issue number plus a depth dial and produces a Stage-1 analysis comment on the Issue along with three independent reviewer verdicts (completeness, quality, adversarial). Internally it inlines the logic of today's four atoms — `analyze_work`, two flavors of `analyze_review`, and `analyze_adversarial` — and runs them serially because the single-level spawn rule (`spec/00-common-contracts.md` §12) forbids a sub-agent from spawning its own sub-agents.

The sub-agent owns the entire AI-review retry loop (max 3 rounds), the adversarial-only FAIL warning (R6 decision), the no-action shortcut, and posting all five marker comments via Section F. It does NOT call `AskUserQuestion`, does NOT change labels, and does NOT auto-proceed to design — those are main-session responsibilities. On Round 3 FAIL with skip-review OFF the sub-agent surfaces an `ESCALATE:` return so main can interactively prompt the user.

---

## 2. Input prompt (from main session)

Spawned via Agent tool (`subagent_type: general-purpose`). Main session sends:

```
Read <<SKILL_DIR>>/atoms/stage_analyze.md and execute its instructions
for Issue #<N>.

Inputs:
  Issue: #<N>
  Depth: <default|deep|shallow>
  Resume: <none|continue-after-escalation>   # optional; default none

Return EXACTLY one line prefixed by `>>> RESULT <<<` per stage_analyze.md §3.
```

`Branch` and `PR` fields from the global prompt template (`design/01-sub-agent-contract.md` §1) are not used by analyze and may be omitted or passed as `null`.

---

## 3. Return contract

Reproduces `design/01-sub-agent-contract.md` §2 stage_analyze table verbatim:

| Return | Meaning |
|---|---|
| `OK ADVANCE: design` | Reviews passed; main session transitions label to `sdd:design` |
| `OK NO_ACTION` | Issue concluded no-action; main transitions label to `sdd:done` and closes |
| `OK PAUSE` | User chose Pause at an escalation gate (skip-review OFF) — only emitted on a `continue-after-escalation` resume after Pause is later re-routed; not used on first FAIL |
| `ESCALATE: <summary>` | Round 3 FAIL in interactive mode — main asks user Continue / Pause / Stop |
| `FAIL: <reason>` | Atom-level error (Issue Validation failed, gh API failed, retry slot value rejected, etc.) — main stops |

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

[PRESERVE — load-bearing]: sentinel + literal status strings are parsed by main FSM. The `ESCALATE: <summary>` line is the only addition relative to today's atom returns.

---

## 4. Internal structure (the sub-agent's own MD body outline)

### §1. Issue Validation [PRESERVE]

Before anything else, validate `$1` per Common Contracts §10:

```bash
gh issue view $1 --json url --jq .url
```

- Empty / error → return `FAIL: Issue #$1 does not exist`.
- URL contains `/pull/` → return `FAIL: #$1 is a Pull Request, not an Issue. SDD commands operate on Issues only.` Do NOT modify labels, post comments, etc.
- URL contains `/issues/` → continue.

### §2. Phase 0 — Depth detection

Read labels and set the depth dial used by all subsequent spawns within this sub-agent:

```bash
gh issue view $1 --json labels --jq '[.labels[].name]'
```

- Contains `sdd:review:deep` → `depth = deep`
- Contains `sdd:review:shallow` → `depth = shallow`
- Otherwise → `depth = default`

The depth dial selects models for the inlined work and review phases per Common Contracts §3 / `spec/01-config.md` §3.

If the `Resume` input is `continue-after-escalation`, skip directly to §8 Phase 6 (output + advance) — Round 1 work and reviews were already done in the prior spawn.

### §3. Phase 1 — Work atom (inlined)

Inlines `commands/atoms/analyze_work.md` step-by-step. The work phase produces the analysis output and posts it under `<!-- sdd:analyze:output -->`.

- **Step 0: Preflight (Light tier).** Run `_preflight.md` Light items: `gh repo view --json nameWithOwner -q .nameWithOwner` (resolve owner/repo, Common Contracts §11), `git status --short`. Inline literal owner/repo into later `gh api` calls.
- **Step 1: Read Issue.** `gh issue view $1 --json title,body,labels` → capture title, body, labels.
- **Step 2: Detect child/parent context (multilingual regex).** Scan Issue body for `(Parent|상위 |親)Issue: #<number>` per `spec/02-multilingual.md` §3. If parent found, fetch the parent Issue's `<!-- sdd:analyze:output -->` and `<!-- sdd:design:output -->` comments via `gh api repos/<owner>/<repo>/issues/<parent>/comments`.
- **Step 3: Classify request type.** Determine one of `new feature` / `enhancement` / `bug fix` / `refactoring` from Issue body.
- **Step 4: No-action assessment.** Classify as no-action if any of: not reproducible & lacks evidence; already fixed (verify via recent commits/PRs); out of scope or duplicate; behavior working as intended. If no-action → skip Steps 5–7, jump to Step 8 with a brief explanation body.
- **Step 5: Feature list.** (normal path only) Enumerate the requested features / changes.
- **Step 6: Priorities.** Assign priority to each feature with justification.
- **Step 7: Language template selection.** Read `.github/.sdd-lang` if present; else detect from Issue body; else `en`. Load `templates/<lang>/output_analyze.md`.
- **Step 8: Format output via template.** Fill the template (or no-action template) with Step 1–7 results. Include the Type classification line.
- **Step 9: Self-review (blockers only).** Verify before posting: marker present, required sections filled, no `<empty>` / TODO / placeholder text, Type classification set, parent reference correct if child. Fix inline. Quality / completeness / risk evaluation are NOT done here — that is the reviewer phase's job (analyze_work.md lines 59–68).
- **Step 10: Retry resolution (if retry mode — rounds 2/3 only).** Self-fetch the prior round's three review comments (`<!-- sdd:review:analyze:{completeness,quality,adversarial} -->`) via `gh api ... /comments`, parse `<!-- sdd:findings:json -->` blocks, sort findings (`critical → major → minor`), and verify every critical/major finding is addressed in the updated output. Mention how (or — only if genuinely infeasible — why not). On `FAIL: no review comments found` or `FAIL: unrecognized retry slot value: <truncated>`, propagate the FAIL as this sub-agent's return.
- **Step 11: Append self-review trace.** If Step 9 fixed any blockers inline, append a `<details>` block listing them at the bottom of the output body.
- **Step 12: Post via Section F temp-file pattern.** `Write` body to `/tmp/sdd-analyze-output-$1.md`. Duplicate-prevention query for `sdd:analyze:output`. Branch: empty → `gh issue comment $1 --body-file /tmp/sdd-analyze-output-$1.md`; has id → `gh api repos/<owner>/<repo>/issues/comments/<id> -X PATCH --field body=@/tmp/sdd-analyze-output-$1.md`.

#### Work return-value handling (internal to sub-agent)

After Step 12, branch on the work result:

- Work produced `OK NO_ACTION` → skip §4 reviews entirely; go to §8 Phase 6 No-Action path.
- Work produced `OK` → continue to §4 reviews.
- Work produced `FAIL: <reason>` → return `FAIL: <reason>` from this sub-agent immediately.

### §4. Phase 2 — Reviews (SERIAL inside stage sub-agent)

Three reviewers execute one after another. Each reviewer reads ONLY its role-specific rubric, performs bounded codebase exploration, posts under its marker, and produces a PASS/FAIL verdict + findings JSON.

- **Reviewer 1: completeness.** Reads `atoms/rubrics/analyze-completeness.md`. Verifies requirements coverage + internal consistency (5-item checklist; cross-section consistency).
- **Reviewer 2: quality.** Reads `atoms/rubrics/analyze-quality.md`. Evaluates edge cases, ambiguity / unstated assumptions, scope / risk, pattern alignment (no-How discipline).
- **Reviewer 3: adversarial.** Reads `atoms/rubrics/analyze-adversarial.md`. Actively refutes the analysis using the 14-`rule_id` registry (`requirement-without-evidence`, `dependency-claim-unverified`, `persona-not-served`, `crud-pair-missing`, `unreconciled-tradeoff`, `contradictory-nfr`, `locale-assumption`, `device-assumption`, `priority-unjustified`, `priority-arbitrary`, `out-of-scope-evasion`, `dod-not-measurable`, `dod-no-verification`, `codebase-claim-unverified`). Must find ≥1 weakness or justify why none.

Each reviewer's loop:

1. Read its rubric file.
2. Read the current `<!-- sdd:analyze:output -->` comment body from the Issue.
3. Optional bounded codebase exploration to verify code references in the analysis (budget per `_review_helpers.md` Section D: **15 Read / 10 Grep / 5 Glob**).
4. Produce comment body: verdict line, model name, `### Issues` with `[critical]`/`[major]`/`[minor]` entries, optional `### Suggestions`, `<!-- sdd:findings:json -->` … `<!-- /sdd:findings:json -->` block per Common Contracts §5 schema.
5. Verdict rule: any `critical` or `major` finding → FAIL; else PASS.
6. Write body to `/tmp/sdd-review-analyze-<role>-$1.md`. Post / PATCH under `<!-- sdd:review:analyze:<role> -->` per Section F.
7. Record internal verdict (PASS / FAIL with summary string) for the verdict combiner.

[PRESERVE — independence invariant]: each reviewer's reasoning context cannot see other reviewers' verdicts during its own evaluation. Even though execution is serial, the sub-agent MUST structure each reviewer's work as a fresh logical pass — do not feed Reviewer 2 the comment body that Reviewer 1 just posted, and do not let Reviewer 3 see Reviewers 1+2's verdicts. The only shared input is the work output under `<!-- sdd:analyze:output -->`.

[PRESERVE]: write tool permitted only for rendering the comment body to the deterministic temp path (Common Contracts §9). Edit / NotebookEdit forbidden inside reviewer logic.

### §5. Phase 3 — Verdict combination

After all three reviewers have posted, combine per Common Contracts §5 / `spec/stage/analyze.md` §5:

| completeness | quality | adversarial | Combined |
|---|---|---|---|
| PASS | PASS | PASS | PASS — exit loop, go to §8 Phase 6 |
| PASS | PASS | FAIL | Adversarial-only FAIL — log warning, treat as FAIL (R6) |
| FAIL | * | * | FAIL — retry or escalate |
| * | FAIL | * | FAIL — retry or escalate |

Atom-level `FAIL: <reason>` from any reviewer (NOT a verdict — an error) → return `FAIL: <reason>` from this sub-agent immediately (no retry).

On adversarial-only FAIL, log to the sub-agent's narrative (and ultimately stdout):
> Adversarial reviewer alone identified critical/major issues. Other reviewers passed. Surfacing for user awareness.

Then treat as a normal FAIL for round-decision purposes (R6 keeps current behavior — retry not auto-pass).

Round decision:

- All 3 PASS → exit loop → §8 Phase 6 (Normal path).
- FAIL and round < 3 → §6 Phase 4 (retry).
- FAIL and round == 3 → §7 Phase 5 (escalation gate).

### §6. Phase 4 — Retry loop

For rounds 2 and 3:

1. Re-invoke the §3 work-atom logic with retry context. Inside the same sub-agent, this is a re-execution of Steps 0–12 with `$2 = "retry"` semantics. Step 0 collapses to Light preflight; Step 10's self-fetch reads the prior round's three review comments from GitHub (atom-side fetch per v0.36 main-session token savings — `spec/stage/analyze.md` §6 retry semantics).
2. Re-run all 3 reviewers (§4) against the updated `<!-- sdd:analyze:output -->`. Reviewer prompts are unchanged across rounds — reviewers always evaluate the CURRENT state of the output marker.
3. Re-combine verdicts (§5).
4. If still FAIL on round 3 → §7. If PASS at any round → exit loop → §8.

Comments are updated in-place via Section F's duplicate-prevention path, so each round overwrites (not appends) the per-marker comment. [PRESERVE — Common Contracts §4 Update-in-place invariant.]

### §7. Phase 5 — Escalation gate (Round 3 FAIL only)

Triggered only when round 3 also failed.

1. Compose escalation summary listing remaining `critical` and `major` findings with role label (e.g. `[completeness][critical] requirement-without-evidence: ...`).
2. Read `.github/.sdd-config` for `skip-review` keys. Parse the comma-separated list at the `skip-review:` key.
3. Branch:
   - `analyze` IS in `skip-review` → log auto-continue to narrative ("⚠ Round 3 FAIL; skip-review=analyze set; auto-continuing with findings persisted on Issue"). Proceed to §8 Phase 6 Normal path. Do NOT return `ESCALATE`.
   - `analyze` NOT in `skip-review` → return `ESCALATE: analyze round 3 FAIL — findings: [critical] <N>, [major] <M> (completeness=<P/F>, quality=<P/F>, adversarial=<P/F>)`. Main session handles `AskUserQuestion`.

[PRESERVE]: skip-review semantics — gate skip only, AI review always ran (it just failed). Findings remain on GitHub for human follow-up. (`spec/stage/analyze.md` §7 Skip-review semantics.)

### §8. Phase 6 — Output + advance

Two exit paths, distinguished by whether reviews ran.

**No-Action path** (work returned `OK NO_ACTION`; reviews were skipped):
- Return `OK NO_ACTION`. Main session sets label `sdd:done` and closes the Issue (or, if skip-review is OFF, presents the no-action explanation to the user before closing — that decision is main's, not this sub-agent's).

**Normal path** (reviews completed PASS, or Round 3 FAIL with skip-review auto-continue):
- Return `OK ADVANCE: design`. Main session sets label `sdd:design` after parsing the return.

[PRESERVE — load-bearing]: this sub-agent NEVER sets labels itself. Label transitions are the main session's sole responsibility — preserves the `01-sub-agent-contract.md` §4 distinction table.

---

## 5. Tooling used inside stage_analyze

- **Read, Write, Grep, Glob** — codebase exploration (reviewers, bounded budget) and comment-body rendering.
- **Bash(gh:*)** — `gh issue view`, `gh issue comment`, `gh pr list`, `gh api repos/.../comments`, `gh repo view`. Single-simple-command rule per Common Contracts §8.
- **Bash(git:*)** — `git status --short` in preflight.
- **NO Agent tool** — single-level spawn rule (Common Contracts §12). The stage sub-agent is itself a sub-agent; nested Agent calls are blocked by Claude Code.
- **NO Skill tool** — analyze stage uses no Skills (`/code-review`, `/security-review`, `/verify` are implement-stage only). Even though sub-agents CAN invoke Skill per `spec/00-common-contracts.md` §13, analyze deliberately does not.

---

## 6. State accessed in GitHub

- **Issue labels** — read once in Phase 0 (depth detection).
- **Issue body** — read in Phase 1 Step 1 (work). Also re-readable inside reviewers if a reviewer wants to cross-check the original request.
- **Issue comments** — read in Phase 1 Step 2 (parent / child context detection); Phase 4 retry (self-fetch of prior-round review markers via `gh api ... /comments`).
- **gh repo view** — Phase 1 Step 0 (owner/repo resolution).
- **Issue comments — write/patch** — Step 12 (work output), Phase 2 (each reviewer's marker).
- **NO PR access** — analyze runs before PRs exist. `gh pr ...` is not invoked.
- **NO branch / commit operations** — analyze is read-only against the working tree (`analyze_work.md` line 129).

---

## 7. Markers posted (matches spec/stage/analyze.md §2)

- `<!-- sdd:analyze:output -->` on Issue — work atom output (or no-action explanation).
- `<!-- sdd:review:analyze:completeness -->` on Issue — Reviewer 1 verdict.
- `<!-- sdd:review:analyze:quality -->` on Issue — Reviewer 2 verdict.
- `<!-- sdd:review:analyze:adversarial -->` on Issue — Reviewer 3 verdict.
- `<!-- sdd:findings:json -->` … `<!-- /sdd:findings:json -->` blocks embedded inside each of the three review comments per Common Contracts §5 schema.

All posted via Section F temp-file pattern with deterministic paths (`/tmp/sdd-analyze-output-$1.md`, `/tmp/sdd-review-analyze-<role>-$1.md`). All updates are in-place (duplicate-prevention search → PATCH if id found, else POST).

---

## 8. Edge cases preserved

- **No-action conclusion.** Work Step 4 may classify the Issue as no-action; reviewers are skipped entirely; return `OK NO_ACTION`. (`spec/stage/analyze.md` §7 No-action conclusion.)
- **Retry mode atom self-fetch.** Rounds 2/3 re-execute the work logic with retry semantics; the inlined work fetches its own prior-round review comments via `gh api`. Unrecognized retry slot values yield `FAIL: unrecognized retry slot value: <truncated>` (Common Contracts §7).
- **Multilingual parent reference.** Step 2 regex matches `Parent` / `상위 ` / `親` per `spec/02-multilingual.md` §3. Parent's analyze + design outputs are pulled for context; child's analysis focuses on its sub-feature.
- **Skip-review.analyze auto-continue.** Round 3 FAIL with `analyze` in skip-review skips the `ESCALATE` return and auto-continues to Normal-path advance. Findings remain on GitHub.
- **Adversarial-only FAIL warning.** R6 keeps current behavior — log warning, treat as FAIL, retry/escalate. Surfaces adversarial dissent to the user via the review comments and the narrative log without auto-passing.

---

## 9. Differences from current implementation

| Aspect | Current | Arch B stage_analyze |
|---|---|---|
| Where the work happens | `analyze_work` atom (separate Agent call from `analyze.md`) | Inlined into `stage_analyze` sub-agent (§3) |
| Reviews | 3 parallel Agent calls from orchestrator (single message) | 3 serial inside `stage_analyze` (§4) |
| Reviewer rubric source | `commands/ai-review-analyze-{completeness,quality,adversarial}.md` | `atoms/rubrics/analyze-{completeness,quality,adversarial}.md` (R7) |
| Escalation | Orchestrator calls `AskUserQuestion` directly | Sub-agent returns `ESCALATE: <summary>`; main session calls `AskUserQuestion` |
| Label transition | Orchestrator sets `sdd:design` / `sdd:done` | Main session sets label after parsing return |
| Inline auto-proceed to design (skip-review) | Orchestrator reads `commands/design.md` in same main session | Main FSM spawns `stage_design` after parsing `OK ADVANCE: design` |
| Wall-clock per review round | ~30s (3 reviewers parallel) | ~90s (3 reviewers serial) |
| Main-session tokens per Issue | ~19.7K | ~2.6K (~87% saving) |

[PRESERVE]: All external contracts — markers, label names, JSON schema, `>>> RESULT <<<` sentinel, status keywords (`OK ADVANCE: design`, `OK NO_ACTION`, `FAIL: <reason>`), retry-mode literal `"retry"` slot, skip-review semantics, multilingual regex, comment temp-file paths.

---

## Cross-references

- Spec contract: `spec/stage/analyze.md`
- Cross-cutting rules: `spec/00-common-contracts.md`
- Architecture: `design/00-architecture.md`
- Sub-agent contract: `design/01-sub-agent-contract.md`
- File layout: `design/02-file-layout.md`
- Rubric files: `atoms/rubrics/analyze-{completeness,quality,adversarial}.md`
- Helpers (referenced by inlined logic): `atoms/_review_helpers.md` (Sections A-F), `atoms/_preflight.md` (Light tier)
