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
| `<!-- sdd:review:<stage>:<role> -->` | Issue comment (or PR for implement) | AI review per stage; `<stage>` ∈ {analyze, design, implement, test}, `<role>` ∈ {completeness, quality} |
| `<!-- sdd:review:parent -->` | Issue comment (parent) | Cross-child parent review summary |

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

### Repository Owner/Repo
Commands using `gh api` need `{owner}/{repo}`. **Always** obtain it by running:

```bash
gh repo view --json nameWithOwner -q .nameWithOwner
```

**Do NOT infer `{owner}/{repo}` from any other source** — not from `git config user.name`, not from the system prompt's "Git user" field, not from commit authors, not from environment variables. Those values are the *user identity*, not the *repository owner*, and using them will hit a wrong repository (potentially returning unrelated data with the same Issue/PR number).

If you need `{owner}/{repo}` for multiple `gh api` calls in the same flow, run the command above once and reuse the result.

### Duplicate Output Prevention
Before posting a stage output, search Issue comments for the matching marker. If found → update that comment. If not → create new comment.

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

