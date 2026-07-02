# CHECK

**Evaluate a single skill package against the 38-item quality rubric. Orchestrator.**

Spawns two isolated sub-agents (rule_checks → model_checks) and aggregates their findings into a graded report. The main session reads only the `>>> RESULT <<<` terminal lines from each sub-agent and the two JSON files; it does not read the SKILL.md itself.

---

## Step 1 — Parse arguments

From the invocation arguments:
- `$1` — path argument (may be a directory, a SKILL.md file path, or absent)
- Remaining args — flags: `--depth=shallow`, `--depth=deep`, `--rules-only`, `--json`

**Resolve package root** (per Common Definitions in SKILL.md):
- If `$1` ends in `SKILL.md` → package root = parent directory of `$1`
- If `$1` is a directory → package root = `$1`
- If `$1` is absent → package root = current working directory

**Resolve depth:**
- `--depth=shallow` or `--rules-only` → `depth = shallow`
- `--depth=deep` → `depth = deep`
- Otherwise → `depth = default`

**Flag precedence:** `--rules-only` takes precedence over `--depth`. If both are set, model checks are skipped.

**Resolve model** for model_checks sub-agent:
- `depth = deep` → model = `opus`
- `depth = default` → model = `sonnet`
- `depth = shallow` → model checks skipped

**Resolve output mode:**
- `--json` present → `output_mode = json`
- Otherwise → `output_mode = formatted`

---

## Step 2 — Guard: SKILL.md exists

Verify `<package-root>/SKILL.md` exists:

```
ls "<package-root>/SKILL.md"
```

If ls returns an error (file not found), report error and stop.

```
Error: No SKILL.md found at <package-root>/SKILL.md
Resolve the package root or pass a directory containing SKILL.md.
```

---

## Step 3 — Spawn rule_checks sub-agent [model: haiku]

Spawn a single Agent sub-agent with:
- `subagent_type`: `general-purpose`
- `model`: `haiku`
- `description`: `rule_checks for <package-root>`
- `prompt`:

> Read `<<SKILL_DIR>>/commands/atoms/rule_checks.md` and execute its instructions with:
> - `$1` = `<package-root>` (substitute the actual absolute path)
>
> Output the `>>> RESULT <<<` terminal line as the LAST line of your response.

Wait for the sub-agent to complete. Parse the terminal line after `>>> RESULT <<<`:
- `OK PASS` → `rule_verdict = pass`, `rule_blockers = []`, `rule_majors = []`, `rule_minors = []`
- `OK FAIL: BLOCKER b1,b2; MAJOR m1; MINOR n1` → `rule_verdict = fail`; parse each severity group
- `FAIL: <error>` → `rule_error = <error>`; treat all rule items as SKIP

After the sub-agent completes, read `/tmp/skill-quality-rule.json` using the Read tool to get full item details.

---

## Step 4 — Early exit on error, BLOCKER, or depth=shallow

**If `rule_error` is set** (rule atom failed to execute):
- Output: `Error: rule_checks atom failed — <rule_error>. Grade set to F (rule checks did not run).`
- STOP — do not proceed to Steps 5 or 6.

If `rule_verdict = fail` AND `rule_blockers` is non-empty:
- Skip Step 5 (no model checks needed — grade is already F)
- Jump to Step 6

If `depth = shallow`:
- Skip Step 5
- Jump to Step 6

---

## Step 5 — Spawn model_checks sub-agent [model: sonnet or opus]

Extract SF2-flagged line numbers from the rule findings JSON top-level field `sf2_flagged_lines`. Format as comma-separated string for `$3` (empty string if field is absent or empty).

Spawn a single Agent sub-agent with:
- `subagent_type`: `general-purpose`
- `model`: `<resolved model from Step 1>`
- `description`: `model_checks for <package-root>`
- `prompt`:

> Read `<<SKILL_DIR>>/commands/atoms/model_checks.md` and execute its instructions with:
> - `$1` = `<package-root>` (substitute the actual absolute path)
> - `$2` = `<depth>` (default or deep)
> - `$3` = `<sf2-flagged-lines>` (comma-separated line numbers, or empty string)
>
> Output the `>>> RESULT <<<` terminal line as the LAST line of your response.

Wait for the sub-agent to complete. Parse the terminal line after `>>> RESULT <<<`:
- `OK PASS` → `model_verdict = pass`
- `OK FAIL: MAJOR m1,m2; MINOR n1` → `model_verdict = fail`; parse each severity group
- `FAIL: <error>` → `model_error = <error>`; treat all model items as SKIP

Read `/tmp/skill-quality-model.json` using the Read tool. Set `model_ran = true`.

---

## Step 6 — Compute grade

Merge findings:
- Start with all rule findings (result=fail items from rule JSON)
- If `model_ran = true`: add model findings; model's `sf2` entry **replaces** rule's `sf2` entry (model confirmation supersedes the rule flag)
- If `model_ran = false`: use rule findings only

Collect from the merged set:
- `all_blockers` = items with severity=BLOCKER and result=fail
- `all_majors` = items with severity=MAJOR and result=fail
- `all_minors` = items with severity=MINOR and result=fail

Apply grade formula:
```
if len(all_blockers) >= 1  → grade = F
elif len(all_majors) == 0  → grade = S
elif len(all_majors) <= 2  → grade = A
elif len(all_majors) <= 5  → grade = B
elif len(all_majors) <= 9  → grade = C
else                        → grade = D
```

---

## Step 7 — Output report

### Formatted output (default)

```
/skill-quality check: <package-root>/SKILL.md
══════════════════════════════════════════════════════════════════════
Grade: <grade>  (rubric v1.0<, rule checks only> if depth=shallow)

<if blockers exist:>
BLOCKER (<count>)
  [<ID>] <item name> — <evidence>
       Fix: <fix_suggestion>

<if majors exist:>
MAJOR (<count>)
  [<ID>] <item name> — <evidence>
       Fix: <fix_suggestion>

<if minors exist:>
Suggestions (<count>)
  [<ID>] <item name> — <evidence>

<if any errors:>
Skipped (execution error)
  rule_checks: <rule_error>  ← only if rule_error exists
  model_checks: <model_error>  ← only if model_error exists

══════════════════════════════════════════════════════════════════════
BLOCKER: <n>  MAJOR: <n>  MINOR: <n>  SKIP: <n>
```

Use the item names from rubric-spec.md for display (e.g., ST4 → "name is kebab-case").

### JSON output (--json flag)

Output a single JSON object to stdout:

```json
{
  "rubric_version": "1.0",
  "target": "<package-root>/SKILL.md",
  "grade": "<S|A|B|C|D|F>",
  "depth": "<shallow|default|deep>",
  "summary": {
    "blocker": <n>,
    "major": <n>,
    "minor": <n>,
    "skip": <n>
  },
  "findings": [
    {
      "id": "<id>",
      "section": "<section>",
      "severity": "<BLOCKER|MAJOR|MINOR>",
      "result": "<pass|fail|skip>",
      "evidence": "<text>",
      "fix_suggestion": "<text>"
    }
  ]
}
```

Include ALL items (pass, fail, skip) in `findings` for full traceability.
