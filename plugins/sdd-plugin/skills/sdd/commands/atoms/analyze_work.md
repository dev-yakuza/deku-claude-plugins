# ATOM: analyze_work

**Single-subagent worker. MUST NOT spawn subagents. MUST NOT call the Agent tool.**

Produces the SDD Stage 1 (Analyze) output for one Issue. Reads inputs from GitHub, writes the analysis as an Issue comment, returns a one-line result string.

> **Bash Command Execution**: every shell snippet below is its own simple Bash tool call — no `&&`, `||`, `;`, `|`, `2>/dev/null`, `2>&1`, `>file`, `$(...)`, `VAR=$(...)`, or heredocs. For codebase exploration use the **Grep / Glob / Read** tools — do NOT use Bash `find` against `/`, `~`, `/Users`, or any path outside the repo root. See **Bash Command Execution Rules** in `<<SKILL_DIR>>/SKILL.md`.

## Inputs

- `$1` — Issue number (already validated by the orchestrator as an Issue, not a PR)
- Optional `$2` — retry signal. When the orchestrator invokes this atom in retry mode it passes the literal string `"retry"`. The atom self-fetches the previous round's review findings per `<<SKILL_DIR>>/commands/atoms/_review_helpers.md` Section C — the orchestrator does NOT inline JSON.

## Work

### Step 0: Pre-flight context discovery + retry context fetch

If retry (`$2` provided and non-empty, expected literal `"retry"`):
- Skip the preflight items below.
- **Execute `<<SKILL_DIR>>/commands/atoms/_review_helpers.md` Section C** to self-fetch the previous round's review findings from Issue `$1` (3 markers: `<!-- sdd:review:analyze:completeness -->`, `:quality`, `:adversarial`). The procedure returns a sorted findings array (`critical → major → minor`).
- Hold this array as `<retry-findings>` for use throughout the Main work below: when revisiting any step (analysis, feature split, priorities), prioritize addressing every `critical` and `major` finding, and read `minor` entries as supporting context (often pinpoints specific wording/sections referenced abstractly by higher-severity items).
- If Section C returns `FAIL: ...` (no review comments found, unrecognized retry slot value, etc.) → propagate it as this atom's return value before starting Main work.

Else (first round, `$2` empty): follow `<<SKILL_DIR>>/commands/atoms/_preflight.md` — tier **Light**, Section B items 1 + 2 (project conventions + commit message style).

### Main work (numbered steps below)

1. Read the Issue:
   ```bash
   gh issue view $1
   ```

2. Detect child Issue per Common Definitions → Parent/Child Issue Detection in `<<SKILL_DIR>>/SKILL.md` (use the multi-language regex `(Parent|상위 |親)Issue: #<number>` to support en/ko/ja templates). If a parent reference is found, read the parent's analyze and design outputs for context:
   ```bash
   gh repo view --json nameWithOwner -q .nameWithOwner    # Bash call 1: observe owner/repo from output; inline as <owner>/<repo> below (no shell variables)
   gh api repos/<owner>/<repo>/issues/<parent>/comments \
     --jq '.[] | select(.body | contains("sdd:analyze:output") or contains("sdd:design:output")) | .body'
   ```
   Use parent context to understand broader scope. Focus this analysis on the child's sub-feature only.

3. Classify request type: `new feature` / `enhancement` / `bug fix` / `refactoring`.

4. Assess whether code changes are actually needed. Conclude **no-action** if:
   - Reported issue is not reproducible and lacks evidence
   - Issue has already been fixed (check recent commits/PRs)
   - Request is out of scope or a duplicate
   - Described behavior is working as intended

   If **no-action**: skip steps 5–7. Prepare a clear explanation of why no code change is needed.

5. Analyze What (feature list) and Why (background, motivation). Focus ONLY on What and Why. Do NOT discuss How (technical implementation).

6. Split into feature list with priorities.

7. Determine language: read `.github/.sdd-lang`. If the file does not exist, detect the primary language of the Issue body and map to the closest supported language (`en`, `ko`, `ja`). If unsupported, default to `en`.

8. Format output using the template `<<SKILL_DIR>>/templates/{lang}/output_analyze.md`. For no-action, use a brief no-action explanation inside the same `<!-- sdd:analyze:output -->` marker.

9. **Self-review (blockers only)**: before posting, verify the output passes these *posting-blocking* checks:
   - [ ] Marker is present (`<!-- sdd:analyze:output -->`)
   - [ ] Template's required sections are filled (Summary, Feature List, Priority — for normal path; no-action explanation for no-action path)
   - [ ] No `<empty>` / TODO / placeholder text left in
   - [ ] Type classification (`new feature` / `enhancement` / `bug fix` / `refactoring`) is set
   - [ ] Cross-stage refs valid (if child Issue, parent reference is correct)

   If a blocker fails → fix inline. Track any blocker that was fixed for the `<details>` trace below.

   *Quality, completeness, risk evaluation are NOT done here — they are the Agent reviewers' job. Keep self-review minimal.*

10. **Retry resolution check**: if Step 0 fetched `<retry-findings>`, before posting verify that every `critical` and `major` finding has been addressed in the output, and mention how (or — only if genuinely infeasible — why it could not be). Treat `minor` entries as supporting context to clarify wording.

11. **Append self-review trace** to the output. Inside the same `<!-- sdd:analyze:output -->` block, before the closing marker, embed:

    ```markdown
    <details>
    <summary>Self-review trace (blockers only)</summary>

    - [x] Template required sections filled
    - [x] Type classification set
    - [x] Cross-stage references valid
    - [ ] Cross-stage ref to parent #N was misspelled — fixed inline

    </details>
    ```

    List only the blockers actually checked; mark `[x]` for clean, `[ ]` with inline note for fixed. Skip the `<details>` block entirely if there is nothing to record.

12. **Post to Issue** — follow `<<SKILL_DIR>>/commands/atoms/_review_helpers.md` Section F (mandatory temp-file pattern). Inline `--body` is forbidden because the body contains `\n#` patterns that trip a non-bypassable Claude Code heuristic.
    - **Marker**: `<!-- sdd:analyze:output -->`
    - **Temp file path**: `/tmp/sdd-analyze-output-$1.md`
    - **Step 1** (Write tool): render the analysis body with marker into the temp file.
    - **Step 2** (Bash): search for an existing comment id:
      ```bash
      gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | select(.body | contains("<!-- sdd:analyze:output -->")) | .id'
      ```
    - **Step 3** (Bash): branch on the result.
      - Empty → `gh issue comment $1 --body-file /tmp/sdd-analyze-output-$1.md`
      - Has id `<id>` → `gh api repos/<owner>/<repo>/issues/comments/<id> -X PATCH --field body=@/tmp/sdd-analyze-output-$1.md`

## Return contract

Return EXACTLY ONE LINE on its own, prefixed by the marker `>>> RESULT <<<` on the preceding line. Format:

```
>>> RESULT <<<
OK
```
or
```
>>> RESULT <<<
OK NO_ACTION
```
or
```
>>> RESULT <<<
FAIL: <one-line reason, max 200 chars, no newlines>
```

- `OK` — analysis posted successfully.
- `OK NO_ACTION` — analysis posted as no-action explanation; the orchestrator will route to `sdd:done`.
- `FAIL: <reason>` — could not complete (e.g., Issue body empty, gh CLI error, etc.). Be specific.

Do NOT return the analysis body, the Issue URL, or any transcript. The Issue comment is the artifact.

## Hard rules

- You are a single-subagent atom. Do NOT invoke the Agent tool. Do NOT spawn subagents.
- Do NOT invoke `/sdd <command>` slash commands or the Skill tool (you are already inside the analyze pipeline).
- Stay within the current repository. Do not modify files outside `.github/` or the working tree.
- Stick to What/Why. Do not write design or implementation details.
