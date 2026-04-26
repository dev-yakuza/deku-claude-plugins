# ANALYZE

**Stage 1: Requirements Analysis (What / Why)**

Focus ONLY on What and Why. Do NOT discuss How (technical implementation).

## Input Validation
Before any other step: validate `$1` per Common Definitions → Issue Validation in `${CLAUDE_SKILL_DIR}/SKILL.md`. If `$1` is a Pull Request, stop without making changes.

## Phase 1: Analysis (via subagent)

Use the **Agent tool** to spawn a subagent with the following instructions. This isolates the heavy work from the main context to save tokens.

> **Subagent instructions:**
>
> You are executing SDD Stage 1 (Analyze) for Issue $1.
>
> 1. Read the Issue: `gh issue view $1`
>    - If the Issue does not exist or is inaccessible → report error and stop
>    - If the Issue body is empty or malformed → report what's missing and stop
> 2. Check if this is a child Issue (body contains `Parent Issue: #<number>`):
>    - If yes: read the parent Issue's analyze and design outputs for context
>      ```bash
>      gh api repos/{owner}/{repo}/issues/<parent>/comments --jq '.[] | select(.body | contains("sdd:analyze:output") or contains("sdd:design:output")) | .body'
>      ```
>    - Use parent context to understand the broader scope, but focus analysis on this child's sub-feature only
> 3. Classify the request type (new feature / enhancement / bug fix / refactoring)
> 4. Assess whether code changes are actually needed. Conclude **no-action** if:
>    - The reported issue is not reproducible and lacks sufficient evidence
>    - The issue has already been fixed (check recent commits/PRs)
>    - The request is out of scope or a duplicate of another Issue
>    - The described behavior is working as intended
>    - If **no-action**: return `verdict: no-action` with a clear explanation of why no code change is needed. Do NOT proceed to steps 5–9.
> 5. Analyze What (feature list) and Why (background, motivation)
> 6. Split into feature list with priorities
> 7. Read the language setting from `.github/.sdd-lang`. If the file does not exist, detect the primary language of the Issue body and map to the closest supported language (`en`, `ko`, `ja`). If unsupported, default to `en`.
> 8. Format output using the template in `${CLAUDE_SKILL_DIR}/templates/{lang}/output_analyze.md`
> 9. **AI Review**: Read `${CLAUDE_SKILL_DIR}/commands/ai-review.md` and execute with the output above (stage: **analyze**)
> 10. Return the final output along with review loop results (rounds, issues fixed, verdict)

If the subagent reports missing information in the Issue, ask the user to fill it in (do NOT ask How questions) and re-run the subagent.

## Phase 2: User Review (in main context)

### If subagent returned `verdict: no-action`:

1. Check skip-review setting (see Common Definitions → Skip Review Setting)
2. If `analyze` is in skip-review:
   - Log: "No action needed — skipping remaining stages"
   - Post the no-action explanation as Issue comment (using duplicate prevention with `<!-- sdd:analyze:output -->` marker)
   - Update label to `sdd:done`
   - **Do NOT proceed** to design. Stop here.
3. If `analyze` is NOT in skip-review:
   - Present the no-action explanation to the user
   - Ask for confirmation: "This Issue appears to need no code changes. Close as no-action?"
   - On approval: post as Issue comment, update label to `sdd:done`
   - On rejection: user may provide additional context → re-run Phase 1 subagent

### If subagent returned normal analysis output:

1. Check skip-review setting (see Common Definitions → Skip Review Setting)
2. If `analyze` is in skip-review:
   - Log: "User review skipped (skip-review: analyze)"
   - Auto-approve: post as Issue comment (using duplicate prevention from Common Definitions) and update label to `sdd:design`
   - **Auto-proceed**: Use the **Agent tool** to spawn a subagent that executes `/sdd design $1`. This isolates the next stage's context and prevents token accumulation.
3. If `analyze` is NOT in skip-review:
   - Present the subagent's output to the user with review loop results (rounds, issues fixed, verdict)
   - Ask for confirmation on direction and priorities
   - On approval: post as Issue comment (using duplicate prevention from Common Definitions) and update label to `sdd:design`
