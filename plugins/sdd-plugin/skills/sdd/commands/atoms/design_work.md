# ATOM: design_work

**Single-subagent worker. MUST NOT spawn subagents. MUST NOT call the Agent tool.**

Produces the SDD Stage 2 (Design) output for one Issue. Reads inputs from GitHub (analyze comment + parent context if child), explores the codebase directly via Read/Grep/Glob, posts the design as an Issue comment, and — if the design splits into multiple PRs — creates child Issues. Returns a one-line result.

> **Bash Command Execution**: run every shell snippet below as its own simple Bash tool call — no `&&`, `||`, `;`, `|`, `$(...)`, `VAR=$(...)`, or heredocs. Inline literal values; do not use shell variables. See **Bash Command Execution Rules** in `${CLAUDE_SKILL_DIR}/SKILL.md`.

## Inputs

- `$1` — Issue number (already validated by the orchestrator as an Issue, not a PR)
- Optional `$2` — previous-round review feedback (retry round)

## Preconditions

- The Issue must already have an `<!-- sdd:analyze:output -->` comment. Otherwise return `FAIL: analyze output not found on Issue #$1`.

## Work

### Step 0: Pre-flight context discovery

If retry mode (`$2` provided) → **skip this step entirely**.

Otherwise, follow `${CLAUDE_SKILL_DIR}/commands/atoms/_preflight.md` Section A for the **Medium** tier. Execute Section B items 1 + 2 + 3 (project conventions + commit message style + similar past PRs via `gh pr list --search`). Apply Section D failure handling. Record findings for the Section F self-review trace.

The similar past PRs (item 3) inform: file organization patterns, naming conventions, architectural choices in this codebase. Use the discovered patterns to guide steps 4–9 below.

### Main work (numbered steps below)

1. Resolve owner/repo:
   ```bash
   gh repo view --json nameWithOwner -q .nameWithOwner    # Bash call 1: observe owner/repo from output; inline as <owner>/<repo> below (no shell variables)
   ```

2. Read the Issue body and the analyze output:
   ```bash
   gh issue view $1
   gh api repos/<owner>/<repo>/issues/$1/comments \
     --jq '.[] | select(.body | contains("sdd:analyze:output")) | .body'
   ```

3. Detect child Issue per Common Definitions → Parent/Child Issue Detection in `${CLAUDE_SKILL_DIR}/SKILL.md` (multi-language regex `(Parent|상위 |親)Issue: #<number>`). If a parent reference is found, read the parent's design output:
   ```bash
   gh api repos/<owner>/<repo>/issues/<parent>/comments \
     --jq '.[] | select(.body | contains("sdd:design:output")) | .body'
   ```
   The child's design must be consistent with the parent's overall architecture and PR-split rationale. Focus on the detailed design for this child's sub-feature only.

4. **Explore the codebase directly** (no Explore subagent — atoms cannot spawn subagents). Use Read / Grep / Glob aggressively to investigate:
   - Existing architecture and patterns relevant to the requirements
   - Files, modules, and dependencies that would be affected
   - Existing test structure and conventions
   - Similar implementations in the codebase that can be referenced

   Be systematic: start with repo root listing, identify relevant directories, search for related symbols, read at least one similar implementation.

5. Identify impact scope (related files, screens, data) based on exploration results.

6. Design file structure changes (Add/Modify/Delete/Move per file).

7. Design data model changes if applicable.

8. Identify constraints and risks with mitigations.

8.5. **Testability constraints** (new — informs design decisions before PR split):

    a. **List external dependencies** in this PR's scope. Examples: DB, network, time, randomness, file I/O, environment variables, external services, browser APIs.

    b. **If 0 external dependencies** → Testability section in the design output will be `N/A (no external dependencies in scope)`. Skip to step 9.

    c. **If 1+ external dependencies** → for each, design:
       - **Mock/stub strategy** — how will tests isolate this dependency?
       - **Injection/seam point** — verify it exists (use Read/Grep to confirm the codebase has the DI hook). If absent, the design must introduce one (add to the File Structure section as a Modify/Add).
       - **Hard-to-test concerns** — timing, randomness, async ordering. Note how the design accommodates them.

    d. Testability decisions made here **must influence** the file structure (step 6) and constraints (step 8). If a dependency forces a new seam, update step 6's file list.

9. Create the feature list with PR split. **Determine if the design splits into multiple PRs (≥ 2) or is a single PR.**

10. Determine language: read `.github/.sdd-lang`. If the file does not exist, detect from Issue body and map to `en`/`ko`/`ja`. Default `en`.

11. Format design output using the template `${CLAUDE_SKILL_DIR}/templates/{lang}/output_design.md`.

12. **Self-review (blockers only)**: before posting, verify posting-blocking checks:
    - [ ] Marker is present (`<!-- sdd:design:output -->`)
    - [ ] Template's required sections are filled (file structure changes, PR split rationale, constraints)
    - [ ] No `<empty>` / TODO / placeholder text left in
    - [ ] PR split count (single vs ≥2) is explicitly stated
    - [ ] File paths cited in the design are syntactically valid (no obvious typos)

    If a blocker fails → fix inline. Track for the `<details>` trace below.

    *Quality, completeness, risk evaluation are NOT done here — Agent reviewers' job.*

13. **If `$2` (retry feedback) is provided**: `$2` is a JSON array of structured findings (per `${CLAUDE_SKILL_DIR}/commands/atoms/_review_helpers.md` Section B). Parse it and address each finding individually. Mention how each was resolved in the design.

14. **Append self-review trace** to the design output. Inside the `<!-- sdd:design:output -->` block, before the closing marker, embed:

    ```markdown
    <details>
    <summary>Self-review trace (blockers only)</summary>

    - [x] Template required sections filled
    - [x] PR split count stated
    - [ ] File path `src/auths.ts` was a typo — fixed to `src/auth.ts`

    </details>
    ```

    Skip the block entirely if there is nothing to record.

15. **Post the design comment** to the Issue with duplicate prevention:
    - Search for `<!-- sdd:design:output -->` marker; update if exists, else create.

16. **If PR split ≥ 2 — Child Issue creation**:

    a. Check if `<!-- sdd:children:output -->` already exists on this Issue. If yes (retry case), do NOT re-create children — keep existing children and skip to step 17. If no, proceed to (b).

    b. For each sub-feature in the design:
       - Format child Issue body using `${CLAUDE_SKILL_DIR}/templates/{lang}/output_child_issue.md` with manual placeholder substitution:
         - `{{parent_issue}}` → `$1`
         - `{{sub_feature_description}}` → sub-feature description from design
         - `{{criteria_list}}` → markdown checkbox list from design
       - Create the child:
         ```bash
         gh issue create --title "[SDD Child] <parent title> - <sub-feature name>" \
           --body "<formatted body>" --label "sdd:analyze" --label "sdd:child"
         ```
       - Capture the new Issue number.

    c. Post the parent's children list comment using `${CLAUDE_SKILL_DIR}/templates/{lang}/output_children.md` with a row per child Issue.

17. **If single PR**: no child creation. Done.

## Return contract

Return EXACTLY ONE LINE on its own, prefixed by `>>> RESULT <<<` on the preceding line:

```
>>> RESULT <<<
OK SINGLE
```
or
```
>>> RESULT <<<
OK CHILDREN: #A,#B,#C
```
or
```
>>> RESULT <<<
FAIL: <one-line reason, max 200 chars, no newlines>
```

- `OK SINGLE` — design posted; single-PR path. Orchestrator advances label to `sdd:implement` after reviews pass.
- `OK CHILDREN: #A,#B,#C` — design posted, children created (numbers listed). Orchestrator handles parent → `sdd:implement` and children queueing.
- `FAIL: <reason>` — could not complete.

Do NOT return the design body or the full output. The Issue comments are the artifact.

## Hard rules

- You are a single-subagent atom. Do NOT invoke the Agent tool. Do NOT spawn subagents (including Explore).
- Do NOT invoke `/sdd <command>` slash commands or the Skill tool.
- Do NOT update the analyze output comment.
- If children already exist on this Issue (retry case), do NOT duplicate them — preserve existing children and only update the design output.
- Stay within the current repository.
