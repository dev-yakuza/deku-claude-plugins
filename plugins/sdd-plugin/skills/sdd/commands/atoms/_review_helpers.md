# REVIEW HELPERS (shared procedures)

**Not an atom.** This file documents shared procedures referenced by review atoms and orchestrators. Read the relevant section when the calling atom instructs you to.

> **Bash Command Execution**: every shell snippet below is its own simple Bash tool call — no `&&`, `||`, `;`, `|`, `$(...)`, `VAR=$(...)`, or heredocs. See **Bash Command Execution Rules** in `${CLAUDE_SKILL_DIR}/SKILL.md`.

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
  "role":         "completeness" | "quality" | "adversarial" | "step-<N>" | "parent-integration",
  "issue":        <number>,
  "pr":           <number> | null,
  "verdict":      "PASS" | "FAIL",
  "model":        "opus" | "sonnet" | "haiku",
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
  ]
}
```

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
