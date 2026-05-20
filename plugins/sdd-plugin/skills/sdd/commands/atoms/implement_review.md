# ATOM: implement_review

**Single-subagent worker. MUST NOT spawn subagents. MUST NOT call the Agent tool.**

Independently reviews the PR created by the TDD atom. Reads the PR diff + linked Issue context, applies "PR Final (3-5)" criteria from `ai-review-implement.md`, posts a review comment on the PR, returns a one-line verdict.

## Inputs

- `$1` — Issue number (the SDD pipeline's Issue, not the PR number)
- `$2` — review role: `completeness` or `quality`

The PR is identified by searching `gh pr list --search "Refs #$1"`. The orchestrator could also pass the PR number explicitly, but discovery via the `Refs #$1` convention keeps the atom self-contained.

The orchestrator invokes this atom **twice in parallel** in a single message — once with `$2=completeness`, once with `$2=quality`.

## Work

1. Resolve owner/repo:
   ```bash
   OWNER_REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
   ```

2. Find the PR for this Issue:
   ```bash
   PR_NUM=$(gh pr list --search "Refs #$1" --state open --json number --jq '.[0].number')
   ```
   If no PR found → return `FAIL: PR for Issue #$1 not found (no open PR with Refs #$1 in body)`.

3. Read the PR diff and body:
   ```bash
   gh pr view $PR_NUM
   gh pr diff $PR_NUM
   ```

4. Read the Issue + design + plan comments:
   ```bash
   gh issue view $1
   gh api repos/$OWNER_REPO/issues/$1/comments \
     --jq '.[] | select(.body | contains("sdd:design:output") or contains("sdd:implement:plan")) | .body'
   ```

5. Read the criteria from `${CLAUDE_SKILL_DIR}/commands/ai-review-implement.md` — specifically the **"PR Final (3-5)"** section (review type: full).

6. Apply criteria according to your role (`$2`):

   ### If `$2` is `completeness`:
   Focus on **requirements coverage and cross-stage consistency**.
   - **Required Checklist** from "PR Final (3-5)":
     - All design items for this PR scope are implemented
     - Tests cover main scenarios and edge cases from the design
     - Code follows existing codebase patterns and conventions
     - No unnecessary code, comments, or debug artifacts remain
     - PR description accurately reflects the changes
     - Manual test checklist covers UI behavior and edge cases not in automated tests
   - **Cross-stage Check**: compare against design output — are the planned changes fully implemented as designed?
   - Report issues with severity.

   ### If `$2` is `quality`:
   Focus on **quality, risks, and issues beyond the checklist**.
   - **Additional Review** from "PR Final (3-5)":
     - Code quality (readability, structure, naming)
     - Performance concerns
     - Security concerns (injection, validation, auth, secrets in commits)
     - Edge cases not enumerated in the design
     - Pattern violations or anti-patterns
   - Report issues with severity.

   Severity definitions:
   - **critical**: Must fix — broken functionality, security vulnerability, missing requirement
   - **major**: Should fix — inconsistency, significant quality issue, poor test coverage
   - **minor**: Nice to fix — style, naming, minor improvement

7. Determine verdict:
   - Any `critical` or `major` → `FAIL` (with summary)
   - Only `minor` → `PASS` (suggestions included in the comment)
   - No issues → `PASS`

8. **Post a review comment on the PR** (not the Issue) with the marker `<!-- sdd:review:implement:<role> -->`. Use duplicate prevention:

   ```bash
   # Variable assignments (atom inputs $1 = Issue, $2 = role; PR_NUM resolved earlier)
   ROLE=$2
   REVIEW_BODY=<rendered comment body — see format below>

   # PR comments share the issue-comments API in GitHub — use $PR_NUM as the issue id
   EXISTING_ID=$(gh api repos/$OWNER_REPO/issues/$PR_NUM/comments \
     --jq ".[] | select(.body | contains(\"<!-- sdd:review:implement:$ROLE -->\")) | .id" \
     | tail -1)

   if [ -n "$EXISTING_ID" ]; then
     # Update in place — preserves review history across retry rounds
     gh api repos/$OWNER_REPO/issues/comments/$EXISTING_ID -X PATCH \
       -f body="$REVIEW_BODY"
   else
     # First post on this PR for this role
     gh pr comment $PR_NUM --body "$REVIEW_BODY"
   fi
   ```

   This is the SAME marker check used by the analyze/design/test review atoms (they search Issue comments instead of PR comments, but the duplicate-prevention pattern is identical). On retry rounds, the prior round's comment is updated in place rather than appended, so the PR's review state always reflects the latest diff.

   Comment body format:
   ```
   <!-- sdd:review:implement:<role> -->
   ## AI Review (implement / <role>)

   **Verdict:** PASS | FAIL

   ### Issues
   - **[critical]** <description with file:line if applicable>
   - **[major]** <description>
   - **[minor]** <description>

   ### Suggestions
   <if any>
   <!-- /sdd:review:implement:<role> -->
   ```

## Return contract

Return EXACTLY ONE LINE on its own, prefixed by `>>> RESULT <<<`:

```
>>> RESULT <<<
OK PASS PR: #N
```
or
```
>>> RESULT <<<
OK FAIL PR: #N: <one-line severity summary, e.g. "1 critical, 2 major">
```
or
```
>>> RESULT <<<
FAIL: <one-line reason — only for atom errors, not review verdicts>
```

- `OK PASS PR: #N` — review completed, no critical/major issues.
- `OK FAIL PR: #N: <summary>` — review completed with critical/major issues.
- `FAIL: <reason>` — the atom itself errored (PR not found, gh CLI error, criteria file missing).

## Hard rules

- You are a single-subagent atom. Do NOT invoke the Agent tool. Do NOT spawn subagents.
- Do NOT invoke `/sdd <command>` or the Skill tool.
- Do NOT modify code, commit, push, merge, or close the PR. Only post your review comment.
- Be independent: evaluate the PR diff on its own merits against the criteria.
- Reviews go on the **PR**, not on the Issue (use `gh pr comment`).
