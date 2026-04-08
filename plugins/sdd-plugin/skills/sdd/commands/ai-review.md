# AI Review (Independent Agent Review)

Spawn a separate review agent to independently verify the stage output.

## Process:
1. Use the **Agent tool** to create a review agent with the following prompt:
   - Include the **stage output only** (the content to review)
   - Include the **review criteria** for the current stage (see below)
   - Include the **original Issue body** for reference
   - Do **NOT** include the reasoning process or context that generated the output
   - The agent must review and report: issues found, suggestions, and a pass/fail verdict

2. Review criteria by stage:
   - **analyze**: Are features clearly defined? Is What/Why sufficient? Missing requirements? Ambiguous descriptions? Priorities make sense?
   - **design**: Does design match requirements? Missing impact scope? Feasible? Architecture consistent? Risks identified?
   - **implement**: Code quality? Test coverage? Pattern consistency? No unnecessary code? PR description accurate?
   - **test**: Test coverage sufficient? Edge cases covered? Regression risks addressed?

3. Handle results:
   - If **pass** → proceed to user review, include AI review summary
   - If **fail** → address the issues, re-run self-review, then re-run AI review
   - Maximum 2 AI review rounds (to avoid infinite loops)

4. Present both self-review and AI review results to the user before asking for confirmation.
