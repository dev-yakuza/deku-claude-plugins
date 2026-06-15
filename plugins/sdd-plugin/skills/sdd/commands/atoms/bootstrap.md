# ATOM: bootstrap

**Single-subagent worker. MUST NOT spawn subagents. MUST NOT call the Agent tool.**

Initial dispatcher for an Issue. Reads GitHub state (labels, comments, PR), determines the current stage and threading hints, returns one line that main session uses to drive the FSM.

Replaces the inline label/comment/PR inspection that `resume.md` used to do in main session — moves that work into a separate sub-agent context to keep main session lean. Per design/01-sub-agent-contract.md §7 + §11.

> **Bash Command Execution**: every shell snippet below is its own simple Bash tool call. See canonical rules in `<<SKILL_DIR>>/commands/atoms/_bash_rules.md`.

## Inputs

- `$1` — Issue number (already validated as an Issue, not a PR, by the caller)

No `$2` / `$3` / retry slots — bootstrap is single-shot and read-only.

## Work

### Step 1: Issue Validation (defense in depth)

```bash
gh issue view $1 --json url --jq .url
```

- Empty / error → return `FAIL: Issue #$1 does not exist in this repository`.
- URL contains `/pull/` → return `FAIL: #$1 is a Pull Request, not an Issue`.
- URL contains `/issues/` → continue.

### Step 2: Resolve owner/repo

```bash
gh repo view --json nameWithOwner -q .nameWithOwner
```

Observe the literal `<owner>/<repo>` value. Inline it into subsequent `gh api repos/<owner>/<repo>/...` calls. Do NOT infer from any other source.

### Step 3: Read Issue labels + body

```bash
gh issue view $1 --json labels,body,title
```

From the output:
- Labels array → extract any `sdd:*` labels.
- Body → save for child-parent detection (Step 6).

### Step 4: Determine depth

From labels:
- Contains `sdd:review:deep` → depth = `deep`
- Contains `sdd:review:shallow` → depth = `shallow`
- Otherwise → depth = `default`

### Step 5: Read Issue comments for marker detection

```bash
gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | .body'
```

Substitute the literal `<owner>/<repo>` from Step 2.

Scan the output for these markers (exact substring match including ` -->`):
- `<!-- sdd:analyze:output -->` — analyze stage completed
- `<!-- sdd:design:output -->` — design stage completed
- `<!-- sdd:children:output -->` — this is a parent Issue
- `<!-- sdd:implement:plan -->` — implement plan posted
- `<!-- sdd:test:output -->` — test stage completed

Set boolean flags for each.

### Step 6: Detect parent / child status

Use the multilingual regex from `<<SKILL_DIR>>/commands/atoms/_multilingual.md`:

```
(Parent|상위 |親)Issue: #<n>
```

- If the Issue body matches → this is a child Issue. Capture the parent's `<n>`.
- If Step 5 found `<!-- sdd:children:output -->` → this is a parent Issue. Capture child Issue numbers by parsing the children comment body.

(Child and parent are not mutually exclusive in extreme cases — a child of a child — but SDD's normal lifecycle doesn't produce nested parents.)

### Step 7: Check for PR linked to this Issue

```bash
gh pr list --search "Refs #$1" --state open --json number,headRefName --jq '.[0]'
```

- Empty → `pr` = null, `branch` = null.
- Has number + headRefName → `pr` = number, `branch` = headRefName.

Also check for closed PRs (for implement state recovery):
```bash
gh pr list --search "Refs #$1" --state closed --limit 1 --json number,state,headRefName --jq '.[0]'
```

- Open PR found in the prior step → use that.
- No open, but closed PR found → record for diagnostics; don't thread (an in-flight `/sdd implement` may need to create a new PR per R8 auto-route).

### Step 8: Determine current stage

Apply this decision table in order (first match wins):

| Condition | stage |
|---|---|
| Has label `sdd:done` | `done` |
| Has label `sdd:test` | `test` |
| Has label `sdd:implement` + this is parent + children list present | `implement-parent` (special case — main session decides if children done → advance to test) |
| Has label `sdd:implement` | `implement` |
| Has label `sdd:design` | `design` |
| Has label `sdd:analyze` | `analyze` |
| No SDD label found | `analyze` (Issue not yet entered; analyze starts here) |

Note: the `implement-parent` distinction allows main session to handle the parent-pause invariant without re-checking labels.

### Step 9: Format the return line

Return EXACTLY this one-line format (prefixed by the sentinel):

```
>>> RESULT <<<
BOOTSTRAP: stage=<stage> depth=<dial> branch=<branch|null> pr=<#PR|null> parent=<true|false> children=[<#a,#b,...>|null]
```

Fields:
- `stage` — one of: `analyze` / `design` / `implement` / `implement-parent` / `test` / `done`
- `depth` — `default` / `deep` / `shallow`
- `branch` — branch name (e.g. `feat-42`) or literal `null`
- `pr` — `#42` or literal `null`
- `parent` — `true` if Step 5 found `<!-- sdd:children:output -->`, else `false`
- `children` — comma-separated `#A,#B,...` if parent, else literal `null`

Example returns:
- `BOOTSTRAP: stage=analyze depth=default branch=null pr=null parent=false children=null`
- `BOOTSTRAP: stage=implement depth=deep branch=feat-42 pr=#101 parent=false children=null`
- `BOOTSTRAP: stage=implement-parent depth=default branch=null pr=null parent=true children=#43,#44,#45`
- `BOOTSTRAP: stage=done depth=default branch=feat-42 pr=#101 parent=false children=null`

## Failure modes

| Condition | Return |
|---|---|
| Issue does not exist | `FAIL: Issue #$1 does not exist in this repository` |
| Input is a PR | `FAIL: #$1 is a Pull Request, not an Issue` |
| `gh repo view` fails (network, auth) | `FAIL: unable to resolve owner/repo via gh repo view` |
| Any other gh API failure | `FAIL: gh API call failed: <verbatim error>` |

On any `FAIL` return, main session stops the dispatch chain. User retries via `/sdd resume <N>` after fixing the underlying issue.

## Hard rules

- This is an atom. **MUST NOT** invoke the Agent tool. **MUST NOT** invoke the Skill tool.
- Pure read-only against GitHub state. **MUST NOT** post comments, edit labels, create branches, or modify any state.
- No retry mode — bootstrap is single-shot.
- All Bash calls follow `<<SKILL_DIR>>/commands/atoms/_bash_rules.md`.

## Why bootstrap exists

Per design/00-architecture.md §2 + design/01-sub-agent-contract.md §11:

- `/sdd auto`, `/sdd batch`, `/sdd resume` need to determine each Issue's current stage to dispatch to the correct stage sub-agent.
- In the v0.x architecture this happened inline in `resume.md` (read by main session). That added ~100 lines of context per Issue.
- In v1.0.0 architecture, main session spawns bootstrap, which does the same work in its own sub-agent context. Main only sees the short return line.

`/sdd <stage> <N>` direct invocation skips bootstrap — the command file does its own minimal label check (1 `gh issue view`) and validates that the requested stage matches before spawning the stage sub-agent. See design/01-sub-agent-contract.md §11.

## Idempotency

Calling bootstrap multiple times on the same Issue at the same moment returns the same result (assuming no concurrent GitHub state changes). Safe to retry on transient failures.
