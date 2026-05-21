# REVIEW

**Re-run AI review on the current stage output of an Issue. Orchestrator.**

This file is an **orchestrator**. It detects the Issue's latest stage and spawns the appropriate stage's two review atoms in parallel (completeness + quality). The review atoms read the existing stage output from GitHub and post fresh review comments via duplicate-prevention markers — so re-running `/sdd review` overwrites the prior review of the same stage rather than appending duplicates.

Use cases:
- Re-review after manually editing a stage output comment.
- Spot-check a stage's review quality mid-pipeline.
- Re-trigger the parallel completeness/quality reviewers without invoking the full stage orchestrator (which would also re-spawn the work atom).

> **Bash Command Execution**: run every shell snippet below as its own simple Bash tool call — no `&&`, `||`, `;`, `|`, `$(...)`, `VAR=$(...)`, or heredocs. Inline literal values; do not use shell variables. See **Bash Command Execution Rules** in `${CLAUDE_SKILL_DIR}/SKILL.md`.

## Input Validation

Before any other step: validate `$1` per Common Definitions → Issue Validation in `${CLAUDE_SKILL_DIR}/SKILL.md`. If `$1` is a Pull Request, stop without making changes.

## Determine Issue type

1. Check for `<!-- sdd:children:output -->` marker:
   ```bash
   gh repo view --json nameWithOwner -q .nameWithOwner    # Bash call 1: observe owner/repo from output; inline as <owner>/<repo> below (no shell variables)
   gh api repos/<owner>/<repo>/issues/$1/comments \
     --jq '.[] | select(.body | contains("<!-- sdd:children:output -->")) | .body'
   ```
2. **Parent Issue** (has children marker) → execute **Parent Review** below.
3. **Single Issue or Child Issue** → execute **Standard Review** below.

## Standard Review (single / child Issue)

### 1. Detect the latest stage with output

Read all stage output markers present on the Issue:

```bash
gh api repos/<owner>/<repo>/issues/$1/comments \
  --jq '.[] | select(.body | contains("sdd:analyze:output") or contains("sdd:design:output") or contains("sdd:implement:plan") or contains("sdd:test:output")) | .body' \
  | grep -oE 'sdd:(analyze:output|design:output|implement:plan|test:output)'
```

Determine the latest stage by precedence (latest-stage wins): `test:output` > `implement:plan` (+ open PR for the implement review) > `design:output` > `analyze:output`.

- For `implement`, also confirm an open PR exists for the Issue (`gh pr list --search "Refs #$1"`); the `implement_review` atom requires the PR to diff against. If no PR → return "No PR found for the implement stage. Run `/sdd implement $1` to create the PR before reviewing."

If no stage output is present → report "No stage outputs to review yet. Run `/sdd analyze $1` first." Stop.

### 2. Spawn the two review atoms in parallel

Map the detected stage to its review atom:

| Detected stage     | Atom file                                                    |
|--------------------|--------------------------------------------------------------|
| `analyze:output`   | `${CLAUDE_SKILL_DIR}/commands/atoms/analyze_review.md`       |
| `design:output`    | `${CLAUDE_SKILL_DIR}/commands/atoms/design_review.md`        |
| `implement:plan`   | `${CLAUDE_SKILL_DIR}/commands/atoms/implement_review.md`     |
| `test:output`      | `${CLAUDE_SKILL_DIR}/commands/atoms/test_review.md`          |

Spawn two Agent tool calls in a **single message** for concurrent execution:

Agent A:
- `subagent_type`: `general-purpose`
- `description`: `<stage> review (completeness) for #$1`
- `prompt`:
  > Read `${CLAUDE_SKILL_DIR}/commands/atoms/<stage>_review.md` and execute its instructions for Issue #$1 with role `completeness`.
  > Return EXACTLY one line in the contract specified by that file, prefixed by the `>>> RESULT <<<` marker line.

Agent B:
- `subagent_type`: `general-purpose`
- `description`: `<stage> review (quality) for #$1`
- `prompt`:
  > Read `${CLAUDE_SKILL_DIR}/commands/atoms/<stage>_review.md` and execute its instructions for Issue #$1 with role `quality`.
  > Return EXACTLY one line in the contract specified by that file, prefixed by the `>>> RESULT <<<` marker line.

### 3. Parse and report

Parse both `>>> RESULT <<<` lines:
- Either `FAIL: <reason>` (atom error) → report the error, stop.
- Both `OK PASS` (or `OK PASS PR: #N` for implement) → report "Review complete, no critical/major issues. See updated review comments on the Issue (or PR for implement)."
- Either `OK FAIL: <summary>` → report the combined severity summaries and point the user at the review comments for details.

`/sdd review` does **NOT** advance labels or auto-proceed. It is a read-side operation: it re-evaluates and posts fresh review comments, then exits. The user decides what to do with the findings.

## Parent Review

Parent reviews are aggregate, not per-stage. They do not use review atoms — they summarize cross-child state directly in the main session.

1. Read child Issue numbers from the children comment:
   ```bash
   gh api repos/<owner>/<repo>/issues/$1/comments \
     --jq '.[] | select(.body | contains("<!-- sdd:children:output -->")) | .body'
   ```
2. For each child Issue:
   - Read its current label
   - Read the latest stage-output comment (via the same marker detection as Standard Review)
   - If in `sdd:implement` or `sdd:test`: check PR status (`gh pr list --search "Refs #<child>"`)
3. Generate a summary review and post as a comment on the parent Issue with the marker `<!-- sdd:review:parent -->` (use duplicate prevention):

   ```
   <!-- sdd:review:parent -->
   ## SDD Parent Review: #$1

   ### Overall Progress
   - Completed: <N> / <total> child Issues
   - In progress: #<numbers>
   - Not started: #<numbers>

   ### Per-child Review
   - #124: <stage> — <brief assessment>
   - #125: <stage> — <brief assessment>

   ### Cross-cutting Concerns
   - <consistency issues between child implementations>
   - <shared dependency conflicts>
   - <integration risks>
   <!-- /sdd:review:parent -->
   ```

The cross-cutting concerns are produced by the main session reading the children's design + implementation comments and identifying inconsistencies — no review atom is involved (this is a unique cross-child operation, not a per-stage review).

## Notes

- **review.md only re-runs AI reviews; it does not advance the pipeline.** To progress a stage after a successful review, run the appropriate `/sdd <stage>` command or `/sdd resume`.
- **Review atoms use duplicate-prevention markers.** Re-running `/sdd review` updates the existing review comments in place rather than appending — the Issue's review state always reflects the latest review pass.
- **Parent review is special** — it aggregates child state and does not use the per-stage review atoms. The output marker `<!-- sdd:review:parent -->` is distinct from per-stage review markers.
