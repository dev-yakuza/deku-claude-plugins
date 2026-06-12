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
| `*_work` (analyze/design/test) | opus | opus | opus |
| `implement_plan` | opus | opus | opus |
| `implement_red`/`green`/`refactor`/`e2e`/`pr` | opus | opus | opus |
| `*_completeness` (analyze/design/implement/test) | sonnet | opus | sonnet |
| `*_quality` (analyze/design/implement/test) | sonnet | opus | sonnet |
| `*_adversarial` (analyze/design/implement/test) | opus | opus | sonnet |
| `parent_integration_review` | opus | opus | sonnet |
| `tdd_step_review` (step 3-1, 3-4) | sonnet | opus | haiku |
| `tdd_step_review` (step 3-2, 3-3) | haiku | opus | haiku |
| `implement_review` (PR Final completeness/quality) | sonnet | opus | sonnet |

The orchestrator passes the chosen model to each Agent spawn via the `model` parameter (lowercase `opus`/`sonnet`/`haiku`).

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
  "model":        "opus" | "sonnet" | "haiku" | null,
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

### B.4 Parsing on orchestrator side

When an orchestrator needs the JSON for retry feedback (Section C), extract:

```bash
gh repo view --json nameWithOwner -q .nameWithOwner
gh api repos/<owner>/<repo>/issues/<N>/comments --jq '.[].body'
```

Inside the comment body text, find the substring between `<!-- sdd:findings:json -->` and `<!-- /sdd:findings:json -->`, strip the surrounding fenced code block markers, and treat as JSON.

For PR-scoped reviews (implement PR Final), replace `<N>` with the PR number and use `gh api repos/<owner>/<repo>/issues/<PR_NUM>/comments` (PR comments share the Issues API in GitHub).

---

## Section C — Retry feedback structuring

When an orchestrator retries a work atom after a failed review round, it passes the failing findings as **`$2`** (work atoms) or **`$3`** (implement_pr retry mode). Do NOT summarize.

### C.1 Build retry input

1. Collect the parsed JSON objects from all review atoms in the failed round (Section B.4).
2. Concatenate the `findings` arrays from each (preserve all fields).
3. **Keep all severities** — do NOT drop `minor`. `minor` findings frequently carry the specifics (variable names, file lines, suggestive wording) that make a `critical` or `major` finding actionable. Sort the combined array by severity: `critical` first, then `major`, then `minor`. Stable order within each group.
4. Serialize the combined array as compact JSON.

### C.2 Pass to work atom

In the work atom Agent prompt, include:

```
Previous round structured findings — sorted by severity (critical → major → minor).
Address every critical and major finding. Read minor findings as context that may
clarify what to change; do not skip them when they cite specific lines/symbols
referenced by a higher-severity finding.

<inlined JSON array>
```

The work atom parses this JSON and addresses critical/major findings individually before posting its next output, using the minor entries as supporting context.

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

Hard caps to prevent runaway exploration:
- Max **15 Read tool calls** per review atom invocation.
- Max **10 Grep tool calls** per review atom invocation.
- Max **5 Glob tool calls** per review atom invocation.

For lighter atoms (`tdd_step_review`): **5 Read / 3 Grep / 0 Glob**.

Track your own counts. If a cap is reached, stop exploration, note the limit in your findings (`rule_id: exploration-budget-exceeded`, severity `minor`), and proceed to verdict based on what you found.

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
