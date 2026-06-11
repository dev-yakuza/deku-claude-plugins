---
name: sdd
description: "Spec-Driven Development - AI collaborative development process with GitHub integration. Use when working on GitHub Issues with a structured process: analyze → design → implement (TDD) → test."
argument-hint: "<command> [issue-number]"
user-invocable: true
---

# SDD (Spec-Driven Development)

You are executing the SDD process. Route to the appropriate command based on `$0`.

**IMPORTANT:** After routing, read the command detail file from `${CLAUDE_SKILL_DIR}/commands/<command>.md` and execute the instructions in it.

## Command Routing

Read `${CLAUDE_SKILL_DIR}/commands/$0.md` and execute. Pass `$1` as issue number (or language for init), `$2` as target stage for rollback.
- Valid commands: `init`, `analyze`, `design`, `implement`, `test`, `resume`, `status`, `review`, `rollback`, `config`, `batch`, `auto`, `help`
- If `$0` is empty → route to `help`
- If `$0` is not in the list above → report unknown command, then route to `help`

---

## Common Definitions

### Stage Flow
```
1. analyze (What/Why) → 2. design (How) → 3. implement (TDD) → 4. test (E2E/QA) → done
```

### Pre-flight Context Discovery (Step 0 of work atoms)
Each work atom begins with a `Step 0: Pre-flight context discovery` that reads project conventions (CLAUDE.md/AGENTS.md/README.md), commit message style (`git log`), and — for some tiers — similar past PRs and target directory contents. See `commands/atoms/_preflight.md` for the authoritative tier table, items, budgets, failure handling, and retry behavior. Step 0 is **skipped on retry rounds** (when `$2` or `$3` is provided).

### Labels
`sdd:analyze` → `sdd:design` → `sdd:implement` → `sdd:test` → `sdd:done` | `sdd:child` (child Issue)

### Output Markers
| Marker | Location | Purpose |
|--------|----------|---------|
| `<!-- sdd:analyze:output -->` | Issue comment | Analysis result |
| `<!-- sdd:design:output -->` | Issue comment | Design result |
| `<!-- sdd:children:output -->` | Issue comment | Child Issue list (parent only) |
| `<!-- sdd:child-issue -->` | Issue body | Child Issue identifier |
| `<!-- sdd:rollback -->` | Issue comment | Rollback notice |
| `<!-- sdd:implement:plan -->` | Issue comment | TDD plan from `implement_plan` atom |
| `<!-- sdd:test:output -->` | Issue comment | Test results + QA checklist |
| `<!-- sdd:review:<stage>:<role> -->` | Issue comment (or PR for implement / test single-child) | AI review per stage; `<stage>` ∈ {analyze, design, implement, test}, `<role>` ∈ {completeness, quality, adversarial} |
| `<!-- sdd:review:implement:step-<n> -->` | Issue comment | TDD step review per step; `<n>` ∈ {1, 2, 3, 4} (Red/Green/Refactor/E2E) |
| `<!-- sdd:test-evidence:step-<n> -->` | Issue comment | Raw test runner output captured by `implement_<step>` work atom; verified by `tdd_step_review` against the self-reported `TESTS: <p>/<t> FAILED: <f>` counts |
| `<!-- sdd:review:implement:tools -->` | PR comment | Per-round summary of which external Skills (`/code-review`, `/security-review`) ran or were skipped during PR Final; posted by `implement.md` Phase 5 with duplicate-prevention |
| `<!-- sdd:review:parent -->` | Issue comment (parent) | Cross-stage parent integration review (posted by `parent_integration_review.md`) |
| `<!-- sdd:findings:json -->` | Inside any review comment | Structured findings JSON block (machine-parseable; schema in `commands/atoms/_review_helpers.md` Section B) |

### Review Model Assignment

See `commands/atoms/_review_helpers.md` Section A for the model assignment table and `/code-review` depth-to-effort mapping.

orchestrators MUST pass the chosen model via the Agent tool's `model` parameter. Set per-Issue dial via `gh issue edit <N> --add-label "sdd:review:deep"` (or `:shallow`).

### Parent/Child Issue Detection
- **Parent Issue**: has `<!-- sdd:children:output -->` marker in comments
- **Child Issue**: body contains `Parent Issue: #<number>` inside `<!-- sdd:child-issue -->` block
- **Single Issue**: neither parent nor child

**Multi-language parent reference**: child Issues created from non-English templates use translated keywords. To detect a child Issue's parent reference across all supported languages, use the regex:

```
(Parent|상위 |親)Issue: #<n>
```

Where `<n>` is the parent number. Use this regex in any atom/orchestrator that needs to detect parent references in Issue bodies — see the `gh issue list --label sdd:child ... --jq 'test("(Parent|상위 |親)Issue: #<n>([^0-9]|$)")'` pattern in `batch.md` / `auto.md` for child auto-discovery.

### Language Setting
- Stored in `.github/.sdd-lang`
- Set by `/sdd init [lang]`
- Languages: `en`, `ko`/`korean`/`한국어`, `ja`/`japanese`/`日本語`
- Fallback when `.github/.sdd-lang` does not exist: detect the primary language of the Issue body and map to the closest supported language (`en`, `ko`, `ja`). If the language is not one of the supported languages, default to `en`.

### Skip Review Setting
- Stored in `.github/.sdd-config` as `skip-review: <values>`
- Set by `/sdd config --skip-review=<values>`
- Values: `analyze`, `design`, `implement`, `pr`, `qa` (comma-separated)
- When a stage's review is skipped, AI review still runs but user review is auto-approved and the next stage is automatically executed
- To check: read `.github/.sdd-config` and parse `skip-review` line. If file missing or no `skip-review` line → no reviews are skipped

### Bash Command Execution Rules

To keep automated runs (`/sdd auto`, `/sdd batch`) unattended, every Bash tool invocation inside an atom or orchestrator MUST be a **simple command** that matches the project's `permissions.allow` patterns (typically `Bash(gh:*)`, `Bash(git:*)`, `Bash(jq:*)`, etc.).

**FORBIDDEN inside a single Bash tool call**:
- Variable assignment with command substitution: `VAR=$(command)`
- Compound commands: `cmd1 && cmd2`, `cmd1 || cmd2`, `cmd1; cmd2`, `cmd1 | cmd2`
- Subshells / groups: `(...)`, `{...}`
- Process substitution: `<(...)`, `>(...)`
- Heredocs that wrap multiple commands (`<<EOF ... EOF` containing more than the body of one tool call)

**Why**: Claude Code's permission matcher evaluates the above as compound expressions and cannot match single-token allow patterns like `Bash(gh:*)`. Each such call therefore raises a permission prompt, breaking unattended runs.

**How to chain results between commands**:
1. Run the first simple command in its own Bash tool call.
2. Read the output yourself from the tool result.
3. Substitute the **literal** value (not a shell variable, not a `$(...)`) into the next simple Bash tool call.

Example:
- ❌ Forbidden: `VAR=$(gh repo view ...); gh api repos/$VAR/...` — compound disables `Bash(gh:*)` matching.
- ✅ Correct: run `gh repo view --json nameWithOwner -q .nameWithOwner` as Bash call 1; observe the literal output (e.g. `owner/repo`); inline that literal into `gh api repos/owner/repo/...` as Bash call 2.

Parallel-independent commands (e.g. `gh issue view ...` and `git status ...`) should be issued as **multiple Bash tool calls in a single message**, not chained with `&&`. Cleanup steps that need ordering should be issued as **separate sequential Bash tool calls**, not chained with `&&` or `;`.

This rule applies to every Bash tool invocation inside any atom or orchestrator, including snippets shown in this skill's Markdown files — those snippets are templates for tool calls, not literal shell scripts to paste.

### Repository Owner/Repo
Commands using `gh api` need `{owner}/{repo}`. **Always** obtain it by running:

```bash
gh repo view --json nameWithOwner -q .nameWithOwner
```

as its own isolated Bash tool call (per the **Bash Command Execution Rules** above — do NOT wrap this in `VAR=$(...)`, do NOT chain it with `&&`). Read the output (e.g. `deku-word-app/word_app`) and inline that **literal** value into subsequent `gh api repos/<owner>/<repo>/...` calls.

**Do NOT infer `{owner}/{repo}` from any other source** — not from `git config user.name`, not from the system prompt's "Git user" field, not from commit authors, not from environment variables. Those values are the *user identity*, not the *repository owner*, and using them will hit a wrong repository (potentially returning unrelated data with the same Issue/PR number).

If you need `{owner}/{repo}` for multiple `gh api` calls in the same flow, run `gh repo view` once at the start, remember the literal value, and inline it everywhere.

### Posting multi-line comment bodies

The simple-Bash rules above are necessary but not sufficient. SDD also posts Markdown comment bodies to GitHub Issues and PRs, and inline multi-line bodies trip an **additional** Claude Code heuristic — "newline followed by `#` inside a quoted argument can hide arguments from path validation". `permissions.allow`, `--dangerously-skip-permissions`, and `sandbox.enabled = false` do **not** suppress it; the prompt cannot be auto-approved.

For every comment-posting step in any atom or orchestrator, follow the **temp-file pattern** documented in `commands/atoms/_review_helpers.md` Section F:

1. Use the **Write tool** to render the body to a deterministic `/tmp/sdd-...md` path (see Section F.1 for the path table).
2. Create a comment via `gh issue comment <N> --body-file <path>` (or `gh pr comment <PR_NUM> --body-file <path>`).
3. Update an existing comment via `gh api repos/<owner>/<repo>/issues/comments/<id> -X PATCH --field body=@<path>`.
4. Create a new Issue with `gh issue create --title "<title>" --body-file <path> ...`.

Inline `--body "<multi-line content>"` is **forbidden** whenever the content contains markdown headers, code fences, or HTML comment markers — i.e. essentially every SDD comment.

### Duplicate Output Prevention
Before posting a stage output, search Issue comments for the matching marker. If found → update that comment via `gh api ... -X PATCH --field body=@<path>`. If not → create a new comment via `gh issue comment <N> --body-file <path>`. See `commands/atoms/_review_helpers.md` Section F.2 for the full procedure.

### Issue Validation
SDD commands operate **only on GitHub Issues**, not Pull Requests. Before executing the main logic of any command that takes an Issue number (`analyze`, `design`, `implement`, `test`, `resume`, `rollback`, `status`, `review`), validate the input.

Use `gh issue view` (which auto-detects the current repository from `cwd`) so you don't need to compute `{owner}/{repo}` first:

```bash
gh issue view $1 --json url --jq .url
```

- Empty/error → `$1` does not exist in the current repository. Stop and report.
- URL contains `/issues/` → `$1` is an Issue. Proceed.
- URL contains `/pull/` → `$1` is a Pull Request. Stop immediately:
  - Do NOT modify labels, post comments, create branches, or make any other state changes.
  - Report to the user:
    > Error: #$1 is a Pull Request, not an Issue. SDD commands operate on Issues only. Please pass an Issue number.

