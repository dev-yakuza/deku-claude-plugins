# ATOM: model_checks

**Single sub-agent. MUST NOT spawn Agent calls. MUST NOT spawn other sub-agents.**

Run all model-based rubric checks against the target SKILL.md. Each check requires a binary judgment (Y/N) with a mandatory evidence quote. Writes findings to `/tmp/skill-quality-model.json` and outputs a single `>>> RESULT <<<` terminal line.

---

## Inputs

- `$1` — Absolute path to the skill package root (directory containing SKILL.md)
- `$2` — Depth: `default` | `deep` (already resolved by the caller; `deep` means the caller selected a higher-quality model for this atom)
- `$3` — SF2 rule findings: comma-separated line numbers flagged by the rule_checks atom for SF2 review (may be empty)

---

## Step 1 — Read the skill file

Read `$1/SKILL.md` using the Read tool. If the file does not exist:

```
>>> RESULT <<<
FAIL: SKILL.md not found at $1/SKILL.md
```

Then stop.

Parse the same structure as rule_checks:
- `description` — from frontmatter
- `when_to_use` — from frontmatter (may be absent)
- `context` — from frontmatter (check for `fork`)
- `disable-model-invocation` — from frontmatter
- `body_text` — everything after the closing `---`

---

## Step 2 — Run each model check

Evaluate each item below. For every item:
- Answer **Y** (criterion met) or **N** (criterion not met) — no hedging
- If **Y**: quote the specific line(s) that confirm the criterion as `evidence`
- If **N**: state precisely what is missing as `evidence`
- If the item does not apply: mark as `skip` with reason

Work through ALL items before writing output.

**Polarity convention:** All questions below are phrased so that **Y = criterion met = PASS** and **N = criterion not met = FAIL**. Do not invert this.

---

### V1 — Unique purpose + LLM-exceeding value [MAJOR]

**Question:** Does this skill provide value that cannot be achieved by simply prompting Claude without any skill?

Look for: org-specific procedures, project-specific conventions, non-public knowledge, multi-step workflows that require persistent state or tool orchestration.

**Generic skills FAIL** if the body reads as instructions any user could give Claude in a plain message (e.g., "summarize this text", "translate to English", "fix typos").

- Y: quote the specific line demonstrating non-generic value
- N: state what a user could achieve with a plain prompt instead

---

### V2 — No redundancy with built-in tools [MAJOR]

**Question:** Is this skill free of significant overlap with any built-in Claude Code skill?

Built-in skills to consider: `/code-review`, `/security-review`, `/run`, `/init`, `/simplify`, `/verify`, `/review`, `/schedule`, `/deep-research`.

**Significant overlap** means the skill's primary function is already covered by a built-in skill (e.g., a custom "security audit" skill that duplicates `/security-review`). Complementary extensions or wrappers are NOT overlap.

- Y: no significant overlap (PASS) — confirm the skill's purpose is distinct from any built-in
- N: name the built-in skill that already covers this function (FAIL)

---

### F3 — context: fork has actionable task [MAJOR]

**Check frontmatter first.** If `context: fork` is NOT present → mark as `skip`.

**Question (if fork present):** Does the body contain at least one concrete, specific task for the forked context?

Generic placeholders ("do the work", "continue here") do NOT count. A concrete task specifies WHAT to do and WHERE.

- Y: quote the actionable task
- N: state that the body has no concrete task for the fork context
- skip: context: fork not found in frontmatter

---

### T1 — WHAT in description [MAJOR]

**Question:** Does the description clearly state WHAT this skill does — its primary function or capability?

The WHAT should be understandable to someone who has never seen this skill before.

- Y: quote the WHAT phrase (e.g., "Evaluates Claude Code skill files against a quality rubric")
- N: explain what information is missing

---

### T2 — WHEN in description [MAJOR]

**Question:** Does the description clearly state WHEN to invoke this skill — the trigger conditions, use cases, or "Use when…" clause?

The WHEN should help Claude decide to call THIS skill rather than another.

- Y: quote the WHEN phrase (e.g., "Use when publishing a skill…")
- N: explain what trigger information is missing

---

### T4 — Trigger specificity [MAJOR]

**Question:** Are the trigger conditions specific enough for Claude to reliably distinguish this skill from others?

Imagine another skill exists that does something similar. Could Claude reliably pick the right one based on these descriptions alone?

A FAIL here means: the description is so broad ("helps with code", "assists developers") that Claude might call it for unrelated requests or miss it for relevant ones.

- Y: confirm the conditions are specific (brief reason)
- N: give a concrete ambiguity scenario — what request would incorrectly trigger or miss this skill?

---

### T5 — High-signal content within first 200 chars [MINOR]

**Question:** Do both WHAT and WHEN appear within the first 200 characters of the description?

Count exactly 200 characters from the start of the description value.

- Y: confirm both WHAT and WHEN appear within the first 200 chars
- N: quote what appears at char 200 and what is missing before that point

---

### C1 — Org-specific / non-derivable knowledge [MAJOR]

**Question:** Does the body contain at least ONE piece of knowledge that could NOT be derived from Claude's training data or public documentation?

This includes: internal tool names, project-specific file paths, team conventions, proprietary workflows, custom command formats, organization-specific rules.

Generic best practices, well-known patterns, and instructions that apply to any project do NOT qualify.

- Y: quote the specific line containing non-derivable knowledge
- N: state that the body reads as generic instructions with no org-specific content

---

### C2 — Worked example present [MAJOR]

**Question:** Does the body contain at least one worked example showing a concrete input → output, before → after, or command → result pair?

A worked example is NOT just a description of what the skill does. It shows ACTUAL sample input and the expected ACTUAL output side by side or in sequence.

- Y: quote the example (or the start of it)
- N: confirm no worked example exists

---

### C4 — Terminology consistency [MINOR]

**Question:** Are the same concepts referred to by consistent terms throughout the skill?

Look for: the same action described as "evaluate" in one place and "assess" or "check" in another; the same artifact called "file" in one place and "document" in another; mixed capitalization for proper names.

Minor variation for readability is acceptable; systematic inconsistency is not.

- Y: terminology is consistent (brief confirmation)
- N: give one specific example of inconsistency (term A vs term B)

---

### C5 — Autonomy calibrated to task risk [MINOR]

**Question:** Is the level of instruction detail appropriate for what the skill does?

High-risk tasks (file deletion, destructive operations, external API calls, code deployment) should be more prescriptive with explicit guards and confirmation steps.

Low-risk tasks (reading files, generating suggestions, formatting text) can allow more model freedom with fewer constraints.

- Y: calibration is appropriate (brief reason)
- N: state whether the skill is over-specified for a low-risk task OR under-specified for a high-risk task

---

### C6 — Failure modes documented [MINOR]

**Question:** Does the body state at least one failure mode, limitation, or "do NOT" guard clause?

Examples: "Do not run on production databases", "SKIP if no config file exists", "Returns empty if no matches found", "Not suitable for files > 10MB".

- Y: quote the failure mode or guard
- N: confirm no such statement exists
- skip: skill is trivially scoped and failure modes are genuinely not applicable (provide reason)

---

### R6 — Script error handling [MINOR]

**Check body first.** If body contains no shell command sequences or script blocks → mark as `skip`.

**Question:** Do command sequences in the body include error handling guidance?

Acceptable forms: `|| exit 1`, `set -e`, `if [ $? -ne 0 ]`, explicit fallback instructions, "If this command fails, do X", or an error-handling section.

- Y: quote an example of error handling
- N: quote an unguarded command sequence that has no error guidance
- skip: no command sequences in body

---

### SF2 — Destructive pattern context confirmation [MAJOR]

**Check input $3.** If $3 is empty (no lines flagged by rule_checks) → mark as `skip`.

For each flagged line number in $3: read that line from the file. Determine whether the destructive command appears in:

**A) Documentation / warning context** — the command is shown as an EXAMPLE of what NOT to do, in a warning block, in a "dangerous" section header context, or quoted as reference.

**B) Execution instruction** — the command is presented as something the skill INSTRUCTS the model to run.

- Y (PASS): context is documentation — state why
- N (FAIL): context is an actual execution instruction — quote the line

If multiple lines are flagged, evaluate each separately. If ANY is an execution instruction → FAIL.

---

## Step 3 — Write JSON findings

Use the Write tool to create `/tmp/skill-quality-model.json`:

```json
{
  "rubric_version": "1.0",
  "target": "<$1/SKILL.md>",
  "atom": "model_checks",
  "verdict": "<PASS if no fails, else FAIL>",
  "items": [
    {
      "id": "<item-id>",
      "section": "<section-name>",
      "severity": "<MAJOR|MINOR>",
      "result": "<pass|fail|skip>",
      "evidence": "<quoted text or explanation>",
      "fix_suggestion": "<concrete one-line fix or empty string>"
    }
  ]
}
```

Include ALL 14 model check items in the items array.

---

## Step 4 — Output terminal line

Output exactly:

```
>>> RESULT <<<
```

Followed immediately by one of:
- `OK PASS` — no failures
- `OK FAIL: MAJOR v1,t1,c1; MINOR c4` — list only IDs with result=fail, grouped by severity
- `FAIL: <error description>` — only on unexpected execution error
