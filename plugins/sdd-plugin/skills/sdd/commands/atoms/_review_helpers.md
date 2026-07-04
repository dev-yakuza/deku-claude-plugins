# REVIEW HELPERS (shared procedures)

**Not an atom.** This file documents shared procedures referenced by review atoms and orchestrators. Read the relevant section when the calling atom instructs you to.

> **Bash Command Execution**: every shell snippet below is its own simple Bash tool call — no `&&`, `||`, `;`, `|`, `2>/dev/null`, `2>&1`, `>file`, `$(...)`, `VAR=$(...)`, or heredocs. For codebase exploration use the **Grep / Glob / Read** tools — do NOT use Bash `find` against `/`, `~`, `/Users`, or any path outside the repo root. See **Bash Command Execution Rules** in `<<SKILL_DIR>>/SKILL.md`.

---

## Section A — Depth label and model assignment

### A.1 Read depth label

At the start of any orchestrator (analyze/design/implement/test), check the Issue's labels:

```bash
gh issue view $1 --json labels --jq '[.labels[].name]'
```

Look for one of:
- `sdd:review:deep` → depth = `deep`
- `sdd:review:shallow` → depth = `shallow`
- (none) → depth = `default`

### A.2 Model assignment table

| Atom role | depth=default | depth=deep | depth=shallow |
|---|---|---|---|
| `analyze_work` / `design_work` | opus | fable | sonnet |
| `test_work` | opus | opus | opus |
| `implement_plan` | opus | opus | opus |
| `implement_red`/`green`/`refactor`/`e2e`/`pr` | opus | opus | opus |
| `*_completeness` (analyze/design/implement/test) | sonnet | opus | sonnet |
| `*_quality` (analyze/design/implement/test) | sonnet | opus | sonnet |
| `*_adversarial` (analyze/design/implement/test) | opus | opus | sonnet |
| `parent_integration_review` | opus | opus | sonnet |
| `tdd_step_review` (step 3-1, 3-4) | sonnet | opus | haiku |
| `tdd_step_review` (step 3-2, 3-3) | haiku | opus | haiku |
| `implement_review` (PR Final completeness/quality) | sonnet | opus | sonnet |

The orchestrator passes the chosen model to each Agent spawn via the `model` parameter (lowercase `opus`/`sonnet`/`haiku`/`fable`).

### A.2.1 Model granularity is per-stage, not per-atom (Arch B) — and the `fable` override

**Read this before using the table above.** Under Arch B (v1.0.0), each stage wrapper (`analyze`/`design`/`implement`/`test`) spawns exactly ONE `stage_<X>` sub-agent, and **all work + all reviewers for that stage run inside that single sub-agent at one model** — the model fixed by the wrapper's Agent-spawn `model:` value. The per-atom columns above are therefore **informational only for the stage flows**: they describe the intended reasoning style / findings-JSON `model` field, not separate spawns. The columns DO drive real model selection only where an atom is spawned as its own Agent — currently just `/sdd review` (completeness + quality), which reads this table.

**The authoritative stage-spawn matrix (this is what actually runs):**

| Spawn | depth=default | depth=deep | depth=shallow | Set in |
|---|---|---|---|---|
| `analyze` stage | opus | **fable** | **sonnet** | `commands/analyze.md` |
| `design` stage | opus | **fable** | **sonnet** | `commands/design.md` |
| `implement` stage | opus | opus | opus | `commands/implement.md` |
| `test` stage | opus | opus | opus | `commands/test.md` |
| `bootstrap` | haiku | haiku | haiku | `resume.md` / `auto.md` |
| `/sdd review` (completeness + quality) | sonnet | opus | sonnet | `commands/review.md` |

When a stage spawns at `fable` / `sonnet`, **every atom in that stage runs at that model** — the per-atom columns in A.2 are overridden by this matrix for actual execution.

**`fable` (Claude Fable 5)** is Anthropic's most capable model — best at long-horizon implementation, first-shot generation, bug finding, and cross-stage reasoning (~2× opus cost). It is applied at `depth=deep` to the two stages with **no in-context security analysis** (`analyze`, `design`) — Fable's bug-finding gains exclude security work and its classifiers can decline cyber-adjacent code (`stop_reason: "refusal"`). **`sonnet`** (~0.6× opus cost) is applied at `depth=shallow` to those same two stages to cut cost on explicitly low-stakes Issues. Rationale per stage:

- **`analyze` / `design`: `deep → fable`, `shallow → sonnet`, `default → opus`.** No `/security-review` / `/code-review` in-context, so the whole stage (work + completeness/quality/adversarial reviewers, one sub-agent) rides the dial safely. Overrides live in `analyze.md` / `design.md` Phase 1 + escalation resume, NOT in this table.
- **`implement` stays `opus` at every depth.** Its sub-agent runs `/security-review` + `/code-review` in the same context (`implement.md` §Notes); Arch B cannot split the model within one sub-agent, so `fable` would run security analysis on `fable` (refusal risk) and `sonnet` would weaken TDD coding + security review. Do not route implement (or any security-analysis atom) to `fable`.
- **`test` stays `opus` at every depth.** `test_work` is opus by a preserve rule (`spec/stage/test.md` Phase 0); shallow does not downgrade it.

Constraints an orchestrator MUST respect:
- **Agent-tool support required.** `fable` is only usable if this Claude Code build accepts `fable` as an Agent `model` value. If a spawn rejects `fable`, fall back to `opus` and continue.
- **Prompting.** Fable underperforms on over-prescriptive prompts; SDD atoms are deliberately prescriptive. Treat the deep→fable and shallow→sonnet overrides as tunable — if deep output regresses versus opus, set the stage's deep spawn back to `opus`; if shallow sonnet output is too weak, set it back to `opus`.

### A.3 `/code-review` effort per depth

| depth | `/code-review` effort |
|---|---|
| default | `high` |
| deep | `max` |
| shallow | `medium` |

The orchestrator (implement.md PR Final step) invokes `/code-review <effort> --comment` accordingly.

---

## Section B — Structured findings JSON schema

Every review atom embeds a JSON block inside its posted comment using the marker pair below.

### B.1 Marker

```
<!-- sdd:findings:json -->
```json
{ ... }
```
<!-- /sdd:findings:json -->
```

### B.2 Schema

```
{
  "stage":        "analyze" | "design" | "implement" | "test" | "parent",
  "role":         "completeness" | "quality" | "adversarial" | "step-<N>" | "parent-integration" | "tools-summary",
  "issue":        <number>,
  "pr":           <number> | null,
  "round":        <number> | null,
  "verdict":      "PASS" | "FAIL" | null,
  "model":        "opus" | "sonnet" | "haiku" | "fable" | null,
  "findings": [
    {
      "severity":       "critical" | "major" | "minor",
      "file":           "<path>" | null,
      "line":           <number> | null,
      "rule_id":        "<short-kebab-case-id>",
      "description":    "<one-line summary>",
      "fix_suggestion": "<one-line suggestion>" | null
    }
  ],
  "suggestions": [
    "<one-line suggestion>", ...
  ],
  "tools_run":     ["<skill-name>", ...] | null,
  "tools_skipped": [{"name": "<skill-name>", "reason": "skill-unavailable" | "shallow-label-skip" | "<other>"}] | null
}
```

**Role-specific field usage**:

- `completeness` / `quality` / `adversarial` / `step-<N>` / `parent-integration` — use `verdict`, `model`, `findings`, `suggestions`. Omit (or `null`) `round`, `tools_run`, `tools_skipped`.
- `tools-summary` — posted by `implement.md` Phase 5 (PR Final) per round. Use `round`, `tools_run`, `tools_skipped`. Set `verdict` and `model` to `null`. `findings` is empty `[]`.

**Why `tools-summary` matters**: `/code-review` and `/security-review` Skills can be unavailable (older Claude Code version, plugin not installed) or intentionally skipped (`sdd:review:shallow` skips `/security-review`). The orchestrator's graceful-skip writes only a transient log. Without a structured marker on the PR, downstream consumers (auditors, future automation) cannot distinguish "tool ran, found nothing" from "tool never ran". Recording `tools_run` / `tools_skipped` makes graceful-skip observable.

### B.3 Verdict rules (per atom)

- Any `critical` or `major` finding → `verdict: "FAIL"`
- Only `minor` findings or none → `verdict: "PASS"`

### B.4 Parsing the JSON block

To extract a review atom's findings from its posted comment:

```bash
gh repo view --json nameWithOwner -q .nameWithOwner
gh api repos/<owner>/<repo>/issues/<N>/comments --jq '[.[] | select(.body | contains("<EXACT_MARKER>"))] | sort_by(.id) | last | .body'
```

Inside the comment body text, find the substring between `<!-- sdd:findings:json -->` and `<!-- /sdd:findings:json -->`, strip the surrounding fenced code block markers, and treat as JSON per Section B.2.

For PR-scoped reviews (implement PR Final), `<N>` is the PR number — PR comments share the Issues API in GitHub.

This procedure is invoked by **retry-mode work atoms** (Section C) to reconstruct previous-round findings. It is read-only and does not modify any comment.

---

## Section C — Retry feedback (atom-side self-fetch)

When a work atom is invoked in retry mode, it self-fetches the previous round's review comments from the target Issue / PR. The orchestrator no longer pre-extracts and inlines the JSON — this keeps the main session context light and ensures the atom always sees the latest review state.

### C.1 Trigger

The orchestrator signals retry mode by passing the **literal string `"retry"`** as the relevant slot:

- analyze / design / test work atoms: `$2 = "retry"`
- `implement_red` / `green` / `refactor` / `e2e`: `$3 = "retry"`
- `implement_pr` retry mode: `$3 = "retry"`

Slot value handling:
- **Empty / absent** → first round; do NOT execute this section.
- **Literal `"retry"`** → retry mode; execute C.2 → C.3.
- **Anything else** (legacy JSON arrays from external callers, typos, accidental shell expansion, etc.) → the atom MUST return `FAIL: unrecognized retry slot value: <first 80 chars of the slot>` instead of silently falling back to first-round. This prevents silent context loss when callers use the pre-v0.36 calling convention.

### C.2 Stage → marker resolution

The marker substrings below are matched **including the trailing ` -->`** (and the leading `<!-- `) to avoid prefix collisions — e.g. `sdd:review:implement:step-1` must not match `:step-10` or `:tools`.

| Stage / atom | Comment scope | Markers to fetch |
|---|---|---|
| `analyze_work` | Issue `$1` | `<!-- sdd:review:analyze:completeness -->`, `<!-- sdd:review:analyze:quality -->`, `<!-- sdd:review:analyze:adversarial -->` |
| `design_work` | Issue `$1` | `<!-- sdd:review:design:completeness -->`, `<!-- sdd:review:design:quality -->`, `<!-- sdd:review:design:adversarial -->` |
| `test_work` (single / child path) | Issue `$1` | `<!-- sdd:review:test:completeness -->`, `<!-- sdd:review:test:quality -->`, `<!-- sdd:review:test:adversarial -->` |
| `test_work` (parent path) | Issue `$1` | Above 3 markers **plus** `<!-- sdd:review:parent -->` (cross-child integration review) |
| `implement_red` | Issue `$1` | `<!-- sdd:review:implement:step-1 -->` |
| `implement_green` | Issue `$1` | `<!-- sdd:review:implement:step-2 -->` |
| `implement_refactor` | Issue `$1` | `<!-- sdd:review:implement:step-3 -->` |
| `implement_e2e` | Issue `$1` | `<!-- sdd:review:implement:step-4 -->` |
| `implement_pr` retry mode | PR (self-derived) | `<!-- sdd:review:implement:completeness -->`, `<!-- sdd:review:implement:quality -->`, `<!-- sdd:review:implement:adversarial -->` (3 markers; `<!-- sdd:review:implement:tools -->` and `<!-- sdd:review:implement:step-* -->` excluded by exact match on trailing ` -->`) |

PR-scoped fetches use the GitHub Issues comments API with the PR number (PR comments live under `/issues/<PR_NUM>/comments`).

### C.3 Fetch + merge procedure

Each Bash call below is its own simple Bash tool invocation. Do NOT chain (`&&`, `;`, `|`, `$(...)`, `VAR=$(...)`).

1. Resolve owner/repo:
   ```bash
   gh repo view --json nameWithOwner -q .nameWithOwner
   ```
   Observe the literal `<owner>/<repo>`. For `implement_pr` retry, additionally derive `<PR_NUM>`:
   ```bash
   gh pr list --head $2 --state open --json number --jq '.[0].number'
   ```
   If `<PR_NUM>` is empty → return `FAIL: retry mode requested but no open PR for branch $2`.

2. For each marker in the table row above, query the **most recent** matching comment:
   ```bash
   gh api repos/<owner>/<repo>/issues/<N>/comments --jq '[.[] | select(.body | contains("<MARKER>"))] | sort_by(.id) | last | .body'
   ```
   - `<N>` = `$1` (Issue-scoped) or `<PR_NUM>` (PR-scoped).
   - `<MARKER>` = exact substring from the table (includes leading `<!-- ` and trailing ` -->`).
   - `sort_by(.id) | last` picks the highest-id comment when duplicates exist (update-in-place rotates the body, so this is the canonical latest version).
   - Empty result for a required marker → return `FAIL: retry requested but review comment for <MARKER> not found on <N>`.

3. From each body, extract the JSON between `<!-- sdd:findings:json -->\n\`\`\`json` and `\`\`\`\n<!-- /sdd:findings:json -->`. Parse it as a JSON object per Section B.2.

4. Concatenate every reviewer's `findings` array. **Keep all severities** — do NOT drop `minor`. Sort the combined array by severity: `critical → major → minor`. Stable order within each group.

5. Use the sorted array as the retry input: address every `critical` and `major` finding individually, read `minor` entries as supporting context (they often pinpoint the specific line/symbol a higher-severity finding only referenced abstractly).

### C.4 Notes

- **Self-fetch is read-only.** This is an idempotent reconstruction of retry context, **not** a license for work atoms to spawn sub-tasks or expand scope. The "atoms never spawn other atoms" rule still applies.
- **Marker exact match with trailing ` -->`** — prevents prefix collisions across `step-1` vs `step-10`, `implement:completeness` vs `implement:completeness-extra`, etc.
- **GitHub API eventual consistency**: in the rare case where a reviewer's PATCH has not yet propagated when the atom fetches, the atom may see a stale body. The orchestrator waits for all reviewer atoms' `>>> RESULT <<<` to land in the main session before spawning the retry work atom — by then GitHub's eventual-consistency window has elapsed in practice. No active retry-on-stale is required.
- **Why atom-side instead of orchestrator-side**: the orchestrator runs in the main session, so any review-comment fetch and JSON inline accumulates main-session context. atom-side fetch confines that token weight to the atom's own (separate) context. Net result: main session only sees the atom's short `>>> RESULT <<<` line.

---

## Section D — Reviewer codebase exploration (Read/Grep/Glob)

When a review atom needs to verify that the work output references actual code:

### D.1 Allowed

- **Read tool** on any file path mentioned in the work output (cross-stage reference checking).
- **Grep tool** to search for symbols/identifiers claimed by the work output.
- **Glob tool** to enumerate matching files.

**Use these dedicated tools — NOT Bash equivalents.** Do NOT use Bash `find`, `grep`, `cat`, `head`, `tail`, `awk`, or `sed` for codebase exploration. Those Bash invocations frequently trip Claude Code's argument heuristics — `find` against absolute paths like `/Users`, `~`, `~/fvm`, or `/` is flagged as a recursive-broad-search safeguard prompt that cannot be auto-approved via `permissions.allow`. Compound forms (`a ; b`, `a | head`, `cmd 2>/dev/null`, `cmd && cmd2`) trip a separate compound-command safeguard. Both prompts break unattended `/sdd auto` / `/sdd batch` runs. The Grep / Glob / Read tools achieve the same exploration without triggering any of these heuristics.

If you absolutely must shell out (e.g. running a project script the work output references), the Bash call must be a **single simple command** with no `;`, `|`, `&&`, `||`, `>`, `2>`, `2>&1`, subshells, or process substitution, and any path argument must be **relative to the repo root** or an absolute path you have already validated lives inside the repo root. Searches that traverse `/`, `~`, `~/fvm`, `/Users`, or any path outside the current working tree are forbidden — use Grep / Glob bound to the repo root instead.

### D.2 Budget

Hard caps vary by `depth` dial — apply to every reviewer in the stage:

| Depth | Read | Grep | Glob | Notes |
|---|---|---|---|---|
| `shallow` | 3 | 1 | 0 | Light verification only |
| `default` | 8 | 5 | 2 | Targeted exploration |
| `deep` | 12 | 7 | 3 | Thorough but bounded |

For lighter atoms (`tdd_step_review`): **5 Read / 3 Grep / 0 Glob** (depth-independent).

Track your own counts. If a cap is reached, stop exploration, note `rule_id: exploration-budget-exceeded` severity `minor`, and proceed to verdict.

### D.3 What NOT to do

- Do NOT modify any code. Read-only.
- Do NOT run tests, builds, or any Bash command except those explicitly listed in this skill.
- Do NOT use the Edit, Write, or NotebookEdit tools.
- Stay within the repository — do not Read absolute paths outside the working tree.
- Do NOT use Bash `find /`, `find /Users`, `find ~`, `find ~/<anything>`, or any `find` with an absolute path that crosses out of the repo root — those trigger Claude Code's recursive-broad-search safeguard which cannot be bypassed via permission settings, and the resulting prompt breaks unattended runs.
- Do NOT chain commands with `;`, `|`, `&&`, `||`, `>`, `2>`, `2>&1`, subshells, or process substitution. Use multiple separate Bash tool calls instead — but for exploration, prefer Grep / Glob / Read tools and avoid Bash entirely.

---

## Section E — Adversarial reviewer prompt

When the calling atom's role is `adversarial`, use this lens explicitly:

```
You are an adversarial reviewer. Your job is to REFUTE the work output, not validate it.

- Assume the author was overconfident.
- Try to find at least one weakness. If you genuinely find none after thorough
  investigation, you must explicitly justify why ("verified by checking X, Y, Z").
- Your lens is distinct from completeness (which checks coverage) and quality
  (which checks risks). Your lens: "what's plausibly wrong here that the others
  might miss?"
- Common refutation angles:
  * The work assumes context that may not hold in this codebase
  * The work satisfies the checklist on the surface but the underlying logic is flawed
  * Cross-stage references look correct but the referenced code does not behave as assumed
  * Edge cases the author did not consider
  * Implicit assumptions about user/system behavior
- Severity guidance for adversarial findings:
  * critical: a refutation that would block correct shipping
  * major: a refutation that exposes a meaningful gap
  * minor: a question worth raising but does not block
```

Independence: like other reviewers, do NOT read other reviewers' verdicts before forming yours.

---

## Section F — Posting Issue/PR comments (mandatory pattern)

Every SDD comment body is multi-line Markdown containing `#` headers (`## ...`, `### ...`), HTML comment markers (`<!-- ... -->`), and triple-backtick code fences. When passed to `gh` via inline `--body "..."`, Claude Code's argument heuristics intercept patterns like "newline followed by `#` inside a quoted argument" and prompt for user confirmation. **The prompts cannot be suppressed by `permissions.allow`, `--dangerously-skip-permissions`, or `sandbox.enabled = false`** — they are a separate static safeguard.

Use the **temp-file pattern** below for every comment body the atom posts. Do NOT pass multi-line bodies inline.

### F.1 Deterministic temp file path

For each atom that posts a comment, pick a deterministic path under `/tmp/` that encodes the SDD marker stub, `$1` (Issue number), and any role/step/PR distinguisher. Recommended naming:

| Marker | Path |
|---|---|
| `<!-- sdd:analyze:output -->` | `/tmp/sdd-analyze-output-$1.md` |
| `<!-- sdd:design:output -->` | `/tmp/sdd-design-output-$1.md` |
| `<!-- sdd:children:output -->` | `/tmp/sdd-children-output-$1.md` |
| `<!-- sdd:child-issue -->` (new child Issue body) | `/tmp/sdd-child-issue-$1-<seq>.md` |
| `<!-- sdd:implement:plan -->` | `/tmp/sdd-implement-plan-$1.md` |
| `<!-- sdd:test:output -->` | `/tmp/sdd-test-output-$1.md` |
| `<!-- sdd:review:<stage>:<role> -->` (Issue-scoped) | `/tmp/sdd-review-<stage>-<role>-$1.md` |
| `<!-- sdd:review:<stage>:<role> -->` (PR-scoped) | `/tmp/sdd-review-<stage>-<role>-pr<PR_NUM>.md` |
| `<!-- sdd:review:implement:step-<n> -->` | `/tmp/sdd-review-implement-step-<n>-$1.md` |
| `<!-- sdd:review:parent -->` | `/tmp/sdd-review-parent-$1.md` |
| `<!-- sdd:test-evidence:step-<n> -->` | `/tmp/sdd-test-evidence-$1-step-<n>.md` (see `_test_evidence.md`) |

### F.2 Procedure

#### Step 1 — Render body to temp file (Write tool)

Use the **Write tool** — not Bash heredoc, not `echo`, not `printf` — to write the comment body to the path from F.1. Include the SDD marker(s), the rendered content, and the closing marker.

#### Step 2 — Search for an existing comment (duplicate prevention)

Resolve owner/repo first if not already known (per **Repository Owner/Repo** in `SKILL.md`), then:

```bash
gh api repos/<owner>/<repo>/issues/<N>/comments --jq '.[] | select(.body | contains("<MARKER>")) | .id'
```

Substitute the **literal** `<owner>/<repo>`, target number `<N>`, and marker string. For PR comments, `<N>` is the PR number (PR comments share the GitHub Issues comments API).

#### Step 3 — Branch on the search result (decided in atom-side narrative, not shell)

- **Empty** → create a new comment:
  - Issue-scoped: `gh issue comment <N> --body-file <path>`
  - PR-scoped: `gh pr comment <PR_NUM> --body-file <path>`
- **Has id** → update the existing comment in place:
  ```bash
  gh api repos/<owner>/<repo>/issues/comments/<id> -X PATCH --field body=@<path>
  ```

The PATCH endpoint is shared by Issue and PR comments — both live under `/issues/comments/<id>`.

#### Step 4 — Verify the post (optional but recommended)

Re-run the F.2 Step 2 query. If the result is empty after a successful post, return `FAIL: <marker> comment not found after posting` from the calling atom.

### F.3 Forbidden alternatives

- ❌ `gh issue comment <N> --body "<multi-line content>"`
- ❌ `gh api ... -X PATCH --field body="<multi-line content>"`
- ❌ Heredocs: `--body "$(cat <<EOF ... EOF)"`
- ❌ `echo "..." | gh ...` (pipe is a compound; violates `SKILL.md` rules)
- ❌ `printf '...' > /tmp/foo.md && gh ...` (compound)

All of the above either trip the multi-line-`#` heuristic or violate the simple-Bash rule in `SKILL.md`. The only sanctioned flow is: Write tool → simple `gh ... --body-file` / `... --field body=@<path>`.

### F.4 Creating new Issues with multi-line bodies

The same constraint applies to `gh issue create`: do not pass the body inline. Write to a temp file (e.g. `/tmp/sdd-child-issue-<parent>-<seq>.md`) and pass it via `--body-file`:

```bash
gh issue create --title "<title>" --body-file <path> --label <label-1> --label <label-2>
```

Multi-line titles are not required by SDD, so `--title "<title>"` remains a single-line argument and is safe.

---

## Section G — Shared verdict combiner (3-reviewer stages)

PASS+PASS+PASS → **PASS** (exit loop, Phase 6). PASS+PASS+FAIL → **Adversarial-only FAIL (R6)**: log "⚠ Adversarial reviewer alone identified critical/major issues. Other reviewers passed. Surfacing for user awareness." → treat as FAIL, no auto-pass. Any other FAIL combination → **FAIL**. Atom-level `FAIL:` errors are returned before this point.

Round decision: All PASS → Phase 6. FAIL + round < 3 → Phase 4. FAIL + round == 3 → Phase 5.

---

## Section H — Shared escalation gate (Round 3 FAIL)

When `round == 3` AND combined verdict is FAIL:

1. Build summary: `<stage> round 3 FAIL — findings: [critical] <N>, [major] <M> (completeness=<P/F>, quality=<P/F>, adversarial=<P/F>)` — re-derive N/M via Section B.4 if needed; stages append extra fields (design: `(path: SINGLE|CHILDREN: ...)`, test: `, parent=<P/F>`, PR Final: `, code-review=<P/F/skipped>, security-review=<P/F/skipped>`).
2. Read `.github/.sdd-config`; parse `skip-review:` list (valid: analyze, design, implement, pr, qa).
3. Stage key (analyze→`analyze`, design→`design`, test→`qa`, PR Final→`pr`): key in list → log "⚠ Round 3 FAIL; skip-review: <key> set — auto-continuing. Findings remain for human follow-up." → Normal path; NOT in list → return `ESCALATE: <summary>`.

[PRESERVE — sub-agent NEVER calls `AskUserQuestion`. Return `ESCALATE:` to main; main handles the interactive prompt.]
