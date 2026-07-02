# REVIEW

**Re-run AI review on the current stage output of an Issue. Orchestrator.**

This file is an **orchestrator**. It detects the Issue's latest stage and spawns the appropriate stage's two review atoms in parallel (completeness + quality). The review atoms read the existing stage output from GitHub and post fresh review comments via duplicate-prevention markers — so re-running `/sdd review` overwrites the prior review of the same stage rather than appending duplicates.

Use cases:
- Re-review after manually editing a stage output comment.
- Spot-check a stage's review quality mid-pipeline.
- Re-trigger the parallel completeness/quality reviewers without invoking the full stage orchestrator (which would also re-spawn the work atom).

> **Bash Command Execution**: every shell snippet below is its own simple Bash tool call — no `&&`, `||`, `;`, `|`, `2>/dev/null`, `2>&1`, `>file`, `$(...)`, `VAR=$(...)`, or heredocs. For codebase exploration use the **Grep / Glob / Read** tools — do NOT use Bash `find` against `/`, `~`, `/Users`, or any path outside the repo root. See **Bash Command Execution Rules** in `<<SKILL_DIR>>/SKILL.md`.

## Input Validation

Before any other step: validate `$1` per Common Definitions → Issue Validation in `<<SKILL_DIR>>/SKILL.md`. If `$1` is a Pull Request, stop without making changes.

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

Read all stage output markers present on the Issue. Single simple Bash call (no compound shell syntax per `<<SKILL_DIR>>/commands/atoms/_bash_rules.md`):

```bash
gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | select(.body | contains("sdd:analyze:output") or contains("sdd:design:output") or contains("sdd:implement:plan") or contains("sdd:test:output")) | .body'
```

Observe the tool output: scan the returned comment bodies in main-session narrative (NOT in shell). Note which of the 4 marker substrings appear: `sdd:analyze:output`, `sdd:design:output`, `sdd:implement:plan`, `sdd:test:output`.

Determine the latest stage by precedence (latest-stage wins): `test:output` > `implement:plan` (+ open PR for the implement review) > `design:output` > `analyze:output`.

- For `implement`, also confirm an open PR exists for the Issue (`gh pr list --search "Refs #$1"`); the `implement_review` atom requires the PR to diff against. If no PR → return "No PR found for the implement stage. Run `/sdd implement $1` to create the PR before reviewing."

If no stage output is present → report "No stage outputs to review yet. Run `/sdd analyze $1` first." Stop.

### 2. Spawn the two review atoms in parallel

Map the detected stage to its review atom:

| Detected stage     | Atom file                                                    |
|--------------------|--------------------------------------------------------------|
| `analyze:output`   | `<<SKILL_DIR>>/commands/atoms/analyze_review.md`       |
| `design:output`    | `<<SKILL_DIR>>/commands/atoms/design_review.md`        |
| `implement:plan`   | `<<SKILL_DIR>>/commands/atoms/implement_review.md`     |
| `test:output`      | `<<SKILL_DIR>>/commands/atoms/test_review.md`          |

**Depth detection (for the reviewer model).** Read the Issue's labels and derive the depth dial, then pick the model per `_review_helpers.md` Section A.2 (`completeness` / `quality` rows):

```bash
gh issue view $1 --json labels --jq '[.labels[].name]'
```

- Contains `sdd:review:deep` → `depth = deep` → `reviewer_model = opus`
- Contains `sdd:review:shallow` → `depth = shallow` → `reviewer_model = sonnet`
- Otherwise → `depth = default` → `reviewer_model = sonnet`

(completeness/quality never use `fable` — `fable` applies only to the `design` stage spawn per Section A.2.1, not to these standalone review atoms.)

Spawn two Agent tool calls in a **single message** for concurrent execution. Substitute `<reviewer_model>` below with the literal value derived above:

Agent A:
- `subagent_type`: `general-purpose`
- `model`: `<reviewer_model>`
- `description`: `<stage> review (completeness) for #$1`
- `prompt`:
  > Read `<<SKILL_DIR>>/commands/atoms/<stage>_review.md` and execute its instructions for Issue #$1 with role `completeness`.
  > Return EXACTLY one line in the contract specified by that file, prefixed by the `>>> RESULT <<<` marker line.

Agent B:
- `subagent_type`: `general-purpose`
- `model`: `<reviewer_model>`
- `description`: `<stage> review (quality) for #$1`
- `prompt`:
  > Read `<<SKILL_DIR>>/commands/atoms/<stage>_review.md` and execute its instructions for Issue #$1 with role `quality`.
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
3. Generate a summary review and post on the parent Issue — follow `<<SKILL_DIR>>/commands/atoms/_review_helpers.md` Section F (mandatory temp-file pattern).
   - **Marker**: `<!-- sdd:review:parent -->`
   - **Temp file path**: `/tmp/sdd-review-parent-$1.md`
   - **Step 1** (Write tool): render the body below into the temp file.
   - **Step 2** (Bash): search for an existing comment id:
     ```bash
     gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | select(.body | contains("<!-- sdd:review:parent -->")) | .id'
     ```
   - **Step 3** (Bash):
     - Empty → `gh issue comment $1 --body-file /tmp/sdd-review-parent-$1.md`
     - Has id `<id>` → `gh api repos/<owner>/<repo>/issues/comments/<id> -X PATCH --field body=@/tmp/sdd-review-parent-$1.md`

   Body format:

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

The cross-cutting concerns are produced by the main session reading the children's design + implementation comments and identifying inconsistencies — no review atom is involved (this is a unique cross-child operation, not a per-stage review). The `/tmp/sdd-review-parent-$1.md` path is shared with `parent_integration_review.md` (auto-triggered in `/sdd test` parent path); both atoms post under the same `<!-- sdd:review:parent -->` marker so one overwrites the other as expected.

## Notes

- **review.md only re-runs AI reviews; it does not advance the pipeline.** To progress a stage after a successful review, run the appropriate `/sdd <stage>` command or `/sdd resume`.
- **Review atoms use duplicate-prevention markers.** Re-running `/sdd review` updates the existing review comments in place rather than appending — the Issue's review state always reflects the latest review pass.
- **Parent review is special** — it aggregates child state and does not use the per-stage review atoms. The output marker `<!-- sdd:review:parent -->` is distinct from per-stage review markers.
- **Adversarial review re-spawn deferred to v1.1+** — file an issue if you need it sooner. v1.0.0 keeps the 2-reviewer (completeness + quality) behavior for `/sdd review`. The adversarial reviewer still runs inside the full stage orchestrators (analyze/design/implement/test); only the standalone re-review path is limited to 2 reviewers.
