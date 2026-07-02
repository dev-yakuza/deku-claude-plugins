# REPORT

**Batch-check all skills in a directory. Orchestrator.**

Finds every `SKILL.md` under the given path, spawns one runner sub-agent per skill (parallel, cap 4). Each runner sub-agent uses `claude --print` to invoke the full rule_checks and model_checks atoms in isolated processes — this bypasses the 2-level sub-agent constraint and produces the same quality as `/skill-quality check`.

---

## Step 1 — Parse arguments

- `$1` — root directory to scan (default: current working directory)
- `--depth=shallow` (default for report) or `--depth=deep`
- `--json` — output JSON array instead of formatted table

Resolve depth:
- `--depth=deep` → `depth = deep`, model_checks model = `claude-opus-4-8`
- Otherwise → `depth = default`, model_checks model = `claude-sonnet-4-6`

---

## Step 2 — Find all SKILL.md files

Use the Bash tool (single call):
```
find "<root>" -name "SKILL.md" -not -path "*/fixtures/*"
```

Collect the list of absolute paths. If empty: report "No SKILL.md files found under `<root>`" and stop.

Derive each skill's package root = parent directory of each SKILL.md path.

---

## Step 3 — Spawn per-skill runner sub-agents (parallel, cap 4)

For each skill package root, spawn a runner sub-agent:
- `model`: `haiku` (the runner itself only issues Bash calls; heavy lifting is inside `claude --print`)
- `description`: `skill-quality check: <package-root>`
- `prompt` (substitute `<root>`, `<depth>`, `<model>`, `<rule_atom>`, `<model_atom>` with resolved values):

---

> You are a runner for ONE skill quality check. Do NOT spawn sub-agents.
>
> **Skill package root:** `<root>`
> **Depth:** `<depth>`
> **Atom files (absolute paths):**
> - rule_checks: `<rule_atom>` (= `<<SKILL_DIR>>/commands/atoms/rule_checks.md`)
> - model_checks: `<model_atom>` (= `<<SKILL_DIR>>/commands/atoms/model_checks.md`)
>
> Use the skill's directory basename as the temp file suffix (e.g. for `/path/to/my-skill`, suffix = `my-skill`). Temp file paths:
> - Rule JSON: `/tmp/sqr-<suffix>-rule.json`
> - Model JSON: `/tmp/sqr-<suffix>-model.json`
>
> ---
>
> **Step A — Run rule checks**
>
> Run this Bash command (replace paths and suffix):
> ```
> claude --print "Read <rule_atom> and follow ALL its instructions for the skill at <root>. Write the findings JSON to /tmp/sqr-<suffix>-rule.json instead of /tmp/skill-quality-rule.json. At the end output the >>> RESULT <<< line." --model claude-haiku-4-5-20251001
> ```
>
> Find the line immediately after `>>> RESULT <<<` in the output — that is the result line.
>
> If the result line starts with `FAIL:` (execution error):
> Return: `GRADE:F TARGET:<root>/SKILL.md BLOCKER:1 MAJOR:0 MINOR:0 SKIP:37`
>
> ---
>
> **Step B — Read rule JSON and extract SF2 flagged lines**
>
> Read `/tmp/sqr-<suffix>-rule.json` using the Read tool.
> Extract `sf2_flagged_lines` (top-level array field). Join as comma-separated string (may be empty).
>
> ---
>
> **Step C — Early exit for BLOCKER or shallow depth**
>
> Parse the result line for BLOCKER count. If BLOCKER ≥ 1:
> Read rule JSON to get exact counts. Return GRADE:F immediately.
>
> If depth = shallow: parse rule JSON, count MAJOR failures, apply grade formula, return GRADE line.
>
> ---
>
> **Step D — Run model checks**
>
> Run this Bash command:
> ```
> claude --print "Read <model_atom> and follow ALL its instructions for the skill at <root>. Depth is <depth>. SF2 flagged lines from rule_checks: <sf2_lines>. Write the findings JSON to /tmp/sqr-<suffix>-model.json instead of /tmp/skill-quality-model.json. At the end output the >>> RESULT <<< line." --model <model>
> ```
>
> ---
>
> **Step E — Merge and grade**
>
> Read `/tmp/sqr-<suffix>-rule.json` and `/tmp/sqr-<suffix>-model.json`.
> Merge all items from both. Where model_checks has an SF2 result, it overrides rule_checks SF2.
> Count BLOCKER failures (result = fail AND severity = BLOCKER) and MAJOR failures (result = fail AND severity = MAJOR).
>
> Grade:
> - BLOCKER ≥ 1 → F
> - MAJOR = 0 → S
> - MAJOR 1–2 → A
> - MAJOR 3–5 → B
> - MAJOR 6–9 → C
> - MAJOR 10+ → D
>
> Return as the LAST line of your response (no other output):
> `GRADE:<grade> TARGET:<root>/SKILL.md BLOCKER:<n> MAJOR:<n> MINOR:0 SKIP:<n>`

---

Spawn up to 4 sub-agents at a time. Wait for all to complete before proceeding.

---

## Step 4 — Parse results

For each sub-agent, find the last line matching `GRADE:...` and parse:
- `grade`, `target`, `blocker`, `major`, `minor`, `skip`

If a sub-agent response contains no `GRADE:` line (crash or empty response): record that skill as `ERROR` with all counts as `0` and continue — do not let one failed agent stop the entire report.

---

## Step 5 — X1 cross-skill collision check (depth=deep only)

If `depth = deep` AND 2 or more skills were found:

Group skills by their **grandparent directory** — skills that share the same `skills/` directory are siblings. Compute: `dirname(dirname(SKILL.md path))`.

Example: `plugins/my-plugin/skills/foo/SKILL.md` and `plugins/my-plugin/skills/bar/SKILL.md` both have grandparent `plugins/my-plugin/skills/` → they are siblings.

For each sibling group with ≥ 2 members: read all their `description` fields and compare inline (no sub-agent needed).

For each sibling pair, judge:
- Are the descriptions so similar that Claude could not reliably distinguish when to call each?
- If YES: record X1 MAJOR collision for both skills

---

## Step 6 — Output report

### Formatted output (default)

```
/skill-quality report: <root>
Depth: <shallow|deep>  Skills found: <N>
══════════════════════════════════════════════════════════════════════

  Grade  B  M  Suggestions  Skill
  ─────────────────────────────────────────────────────────────────
  S      0  0  0            plugins/my-plugin/skills/my-skill
  A      0  1  2            plugins/my-plugin/skills/other-skill
  F      1  0  0            plugins/bad-plugin/skills/broken-skill
  ERROR  -  -  -            plugins/crashed/skills/broken-skill
  ...

══════════════════════════════════════════════════════════════════════
Summary
  S: <n>  A: <n>  B: <n>  C: <n>  D: <n>  F: <n>
  Total skills: <N>  Not publishable (F): <n>

<if X1 findings:>
Cross-skill Collisions (X1)
  <skill-a> ↔ <skill-b>: descriptions too similar — <brief reason>
```

Column headers: B = BLOCKER count, M = MAJOR count.
Sort by grade ascending (F and ERROR first, S last).

### JSON output (--json flag)

```json
{
  "rubric_version": "1.0",
  "root": "<root>",
  "depth": "<shallow|deep>",
  "skills": [
    {
      "target": "<path>/SKILL.md",
      "grade": "<grade>",
      "blocker": "<n>",
      "major": "<n>",
      "minor": "<n>",
      "skip": "<n>"
    }
  ],
  "summary": {
    "total": "<n>",
    "by_grade": { "S": "<n>", "A": "<n>", "B": "<n>", "C": "<n>", "D": "<n>", "F": "<n>", "ERROR": "<n>" }
  },
  "x1_collisions": [
    { "skill_a": "<path>", "skill_b": "<path>", "reason": "<text>" }
  ]
}
```
