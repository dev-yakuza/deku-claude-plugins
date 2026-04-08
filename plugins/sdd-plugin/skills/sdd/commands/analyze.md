# ANALYZE

**Stage 1: Requirements Analysis (What / Why)**

Focus ONLY on What and Why. Do NOT discuss How (technical implementation).

## Process:
1. Read the Issue: `gh issue view $1`
   - If the Issue does not exist or is inaccessible → report error and stop
   - If the Issue body is empty or malformed → ask user to fill in the required fields
2. Check if this is a child Issue (body contains `Parent Issue: #<number>`):
   - If yes: read the parent Issue's analyze and design outputs for context
     ```bash
     gh api repos/{owner}/{repo}/issues/<parent>/comments --jq '.[].body'
     ```
   - Use parent context to understand the broader scope, but focus analysis on this child's sub-feature only
3. Classify the request type (new feature / enhancement / bug fix / refactoring)
4. Analyze What (feature list) and Why (background, motivation)
5. If information is missing, ask the user (do NOT ask How questions)
6. Split into feature list with priorities
7. Read the language setting from `.github/.sdd-lang` (default: en)
8. Format output using the template in `${CLAUDE_SKILL_DIR}/templates/{lang}/output_analyze.md`

## Self-Review:
- Check for missing features, ambiguous descriptions
- Verify What/Why are sufficient
- If issues found, go back and improve

## AI Review:
Read `${CLAUDE_SKILL_DIR}/commands/ai-review.md` and execute with the output above (stage: **analyze**).

## User Review:
- Present the output to the user with self-review and AI review results
- Ask for confirmation on direction and priorities
- On approval: post as Issue comment (using duplicate prevention from Common Definitions) and update label to `sdd:design`
