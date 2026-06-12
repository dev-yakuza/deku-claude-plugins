# TEST EVIDENCE (shared procedure)

**Not an atom.** This file documents the shared procedure called by every `implement_<step>` work atom (Red/Green/Refactor/E2E) to post the raw test runner output as a verifiable evidence comment. Read this when the calling atom instructs you to.

The procedure exists because `tdd_step_review` cannot re-run tests; it can only verify the work atom's self-reported `TESTS: <p>/<t> FAILED: <f>` counts against a captured log. Without this evidence, those counts are unverifiable.

> **Bash Command Execution**: every shell snippet below is its own simple Bash tool call — no `&&`, `||`, `;`, `|`, `2>/dev/null`, `2>&1`, `>file`, `$(...)`, `VAR=$(...)`, or heredocs. For codebase exploration use the **Grep / Glob / Read** tools — do NOT use Bash `find` against `/`, `~`, `/Users`, or any path outside the repo root. See **Bash Command Execution Rules** in `<<SKILL_DIR>>/SKILL.md`.

---

## When to run

After the work atom's commit step, and **only** when there is a real test claim to post:

- `implement_red` — always (Red must run tests)
- `implement_green` — always
- `implement_refactor` — only if the refactor produced a commit (skip when returning `OK REFACTOR EMPTY`)
- `implement_e2e` — only if E2E ran (skip when returning `OK E2E_SKIPPED`)

If the step returns one of the "no commit" variants above, **skip this procedure entirely**.

## Inputs (from the caller)

- `<n>` — step number: `1` (Red), `2` (Green), `3` (Refactor), `4` (E2E)
- `<sha>` — the commit sha just created
- `<passed>` / `<total>` / `<failed>` — the counts captured from the test runner output
- The **full test runner output text** that the work atom observed (from the Bash tool result of running tests)
- `$1` — the Issue number (passed through from the calling atom)

## Procedure

### Step 1: Prepare the log excerpt

GitHub issue comments cap at ~65,000 characters and a noisy test log can exceed that. Build the excerpt as follows:

1. If the **full** test runner output is ≤ 50,000 characters → use it verbatim.
2. Otherwise → take the **first 2,000 characters** (framework banner, configuration block) + a separator line `... [truncated middle] ...` + the **last 8,000 characters** (per-test results and summary).

Preserve the original line breaks and ANSI-free text exactly as observed. Do NOT paraphrase, summarize, or "clean up" the output — the reviewer needs structural signals (file paths, framework banners, timings) to judge authenticity.

### Step 2: Build the comment body

Use this exact template (substitute the literal values, no shell variables):

```
<!-- sdd:test-evidence:step-<n> -->
## Test Evidence (step-<n>)

**Commit:** <sha>
**Reported counts:** TESTS: <passed>/<total> FAILED: <failed>
**Test command:** <command the atom actually ran, e.g. `npm test`, `pytest -q`, `flutter test`>

### Raw runner output

\`\`\`
<log excerpt from Step 1>
\`\`\`

<!-- /sdd:test-evidence:step-<n> -->
```

The fenced code block in the template uses triple backticks at the start and end of the log excerpt. Do NOT wrap the excerpt in additional markdown formatting.

### Step 3: Write the body to a temp file

Use the **Write tool** (not Bash heredoc — heredocs violate the simple-command rule) to write the prepared body to:

```
/tmp/sdd-test-evidence-$1-step-<n>.md
```

(Substitute `$1` and `<n>` literally.)

### Step 4: Post or update the comment (duplicate-prevention)

Resolve owner/repo if not already known in this atom's context:

```bash
gh repo view --json nameWithOwner -q .nameWithOwner
```

Search the Issue for an existing test-evidence comment for this step:

```bash
gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | select(.body | contains("<!-- sdd:test-evidence:step-<n> -->")) | .id'
```

(Inline the literal `<owner>/<repo>` and `<n>` from prior context — no shell variables.)

- **If the search returns a comment id** → update in place:
  ```bash
  gh api repos/<owner>/<repo>/issues/comments/<id> -X PATCH --field body=@/tmp/sdd-test-evidence-$1-step-<n>.md
  ```
- **If the search returns empty** → create a new comment:
  ```bash
  gh issue comment $1 --body-file /tmp/sdd-test-evidence-$1-step-<n>.md
  ```

### Step 5: Verify the post (best-effort)

Re-read the comment to confirm the marker is present:

```bash
gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | select(.body | contains("<!-- sdd:test-evidence:step-<n> -->")) | .id'
```

If empty after the post — return `FAIL: test evidence comment not found after posting (step-<n>)` from the calling atom. The reviewer cannot verify the step without it.

---

## What NOT to do

- Do NOT redact or summarize the runner output beyond the truncation rule in Step 1. Reviewer authenticity checks rely on framework-specific patterns.
- Do NOT change the self-reported counts (`<passed>/<total>/<failed>`) in the comment to match the log if they disagree — the reviewer is supposed to catch that discrepancy. Post what was observed, both the raw counts and the raw log.
- Do NOT skip the post on retry rounds — `tdd_step_review` re-reads the test evidence each round; stale evidence from a prior round will fail the consistency check.
- Do NOT post this comment for steps that returned `OK REFACTOR EMPTY` or `OK E2E_SKIPPED` — there is no test claim to verify.
