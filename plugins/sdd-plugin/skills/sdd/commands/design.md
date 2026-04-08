# DESIGN

**Stage 2: Design (How)**

Define HOW to implement based on the requirements.

## Process:
1. Read analyze output from Issue comments:
   ```bash
   gh api repos/{owner}/{repo}/issues/$1/comments --jq '.[] | select(.body | contains("sdd:analyze:output")) | .body'
   ```
   - If no analyze output found → report error: "Run `/sdd analyze $1` first" and stop
2. Check if this is a child Issue (body contains `Parent Issue: #<number>`):
   - If yes: read the parent Issue's design output for context (architecture decisions, PR split rationale, constraints)
     ```bash
     gh api repos/{owner}/{repo}/issues/<parent>/comments --jq '.[] | select(.body | contains("sdd:design:output")) | .body'
     ```
   - The child's design must be consistent with the parent's overall architecture and design decisions
   - Focus on the detailed design for this child's sub-feature only
3. Explore the codebase using a **dedicated Explore agent** (Agent tool with `subagent_type: Explore`, `model: "sonnet"`):
   - Provide the agent with the analyze output and ask it to investigate:
     - Existing architecture and patterns relevant to the requirements
     - Files, modules, and dependencies that would be affected
     - Existing test structure and conventions
     - Similar implementations in the codebase that can be referenced
   - Do **NOT** share design ideas with the agent — let it explore objectively
   - Use the agent's findings as input for the design steps below
4. Identify impact scope (related files, screens, data) based on exploration results
5. Design file structure changes
6. Design data model changes (if applicable)
7. Identify constraints and risks
8. Create feature list with PR split
9. Read the language setting from `.github/.sdd-lang` (default: en)
10. Format output using the template in `${CLAUDE_SKILL_DIR}/templates/{lang}/output_design.md`

## Review Loop:
Read `${CLAUDE_SKILL_DIR}/commands/ai-review.md` and execute with the output above (stage: **design**).

## User Review:
- Present the output to the user with review loop results (rounds, issues fixed, verdict)
- Ask for confirmation on technical approach and PR split
- On approval:
  - Post as Issue comment (using duplicate prevention from Common Definitions)
  - If **single PR** → update label to `sdd:implement`
  - If **multiple PRs** → execute **Child Issue Creation** below

## Child Issue Creation (when multiple PRs are needed):

When the design identifies 2 or more PRs, create a child Issue for each sub-feature:

1. Read the language setting from `.github/.sdd-lang` (default: en)
2. For each sub-feature in the design:
   - Format the child Issue body using the template in `${CLAUDE_SKILL_DIR}/templates/{lang}/output_child_issue.md`
   - Placeholders are NOT processed by a template engine. AI must manually replace them:
     - `{{parent_issue}}` → replace with `$1`
     - `{{sub_feature_description}}` → replace with the sub-feature description from design
     - `{{criteria_list}}` → replace with a markdown checkbox list from design (e.g. `- [ ] Criterion 1\n- [ ] Criterion 2`)
   ```bash
   gh issue create --title "[SDD Child] <parent title> - <sub-feature name>" \
     --body "<formatted body from template>" --label "sdd:analyze" --label "sdd:child"
   ```
3. Post the child Issue list as a comment on the parent Issue using the template in `${CLAUDE_SKILL_DIR}/templates/{lang}/output_children.md`
   - Add a row for each created child Issue to the table
4. Post design output as Issue comment on parent Issue
5. Update parent Issue label to `sdd:implement`
6. Ask user which child Issue to start with, then execute **ANALYZE** on that child Issue
