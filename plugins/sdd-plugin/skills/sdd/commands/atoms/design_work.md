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

9. Create the feature list with PR split. **Determine if the design splits into multiple PRs (≥ 2) or is a single PR.**

10. Determine language: read `.github/.sdd-lang`. If the file does not exist, detect from Issue body and map to `en`/`ko`/`ja`. Default `en`.

11. Format design output using the template `${CLAUDE_SKILL_DIR}/templates/{lang}/output_design.md`.

12. **Self-review** (quick, in-context): before posting, verify:
    - Every feature from analyze output is addressed
    - Impact scope covers all affected files/modules/data
    - Constraints and risks are identified with mitigations
    - PR split is logical and each PR is independently deliverable
    - Architecture decisions are consistent with existing patterns

    Fix inline before posting.

13. **If `$2` (retry feedback) is provided**: explicitly address each issue in `$2` before posting. Mention how each was resolved in the design.

14. **Post the design comment** to the Issue with duplicate prevention:
    - Search for `<!-- sdd:design:output -->` marker; update if exists, else create.

15. **If PR split ≥ 2 — Child Issue creation**:

    a. Check if `<!-- sdd:children:output -->` already exists on this Issue. If yes (retry case), do NOT re-create children — keep existing children and skip to step 16. If no, proceed to (b).

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

16. **If single PR**: no child creation. Done.

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
