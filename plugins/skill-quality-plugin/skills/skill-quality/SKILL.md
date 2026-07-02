---
name: skill-quality
description: "Evaluate Claude Code skill files against a 38-item quality rubric spanning structure, triggers, content, resources, and safety. Use when publishing a skill to a marketplace, auditing an existing skill for quality issues, batch-checking a skill library before a release, or diagnosing why a skill fails to trigger reliably."
argument-hint: "<command> [path] [--depth=shallow|deep] [--rules-only] [--json]"
user-invocable: true
---

# skill-quality

Route to the appropriate command based on `$0`. Read `<<SKILL_DIR>>/commands/$0.md` and execute its instructions.

## Command Routing

- Valid commands: `check`, `report`, `rubric`, `help`
- If `$0` is empty or not in list → route to `help`

---

## Common Definitions

### Skill Package Root

A "skill package root" is the directory containing a `SKILL.md` file. Resolve from the path argument:

- Argument is a directory → use as package root
- Argument is a file path ending in `SKILL.md` → use its parent directory
- Argument is missing → use current working directory

After resolving, verify `<root>/SKILL.md` exists before proceeding.

### Grade System

| Grade | Condition |
|-------|-----------|
| **S** | BLOCKER 0 + MAJOR 0 |
| **A** | BLOCKER 0 + MAJOR 1–2 |
| **B** | BLOCKER 0 + MAJOR 3–5 |
| **C** | BLOCKER 0 + MAJOR 6–9 |
| **D** | BLOCKER 0 + MAJOR 10+ |
| **F** | BLOCKER ≥ 1 |

MINOR findings do not affect grade — they appear under "Suggestions."
SKIP items (check not applicable) are excluded from grade calculation.

### BLOCKER Items (5 total — all rule checks)

`ST1` `ST2` `ST5` `F1` `SF1`

Any one of these produces grade **F** regardless of other findings.

### Depth Dial

| Flag | Rule checks | Model checks | Model |
|------|-------------|--------------|-------|
| `--depth=shallow` | ✓ | skipped | — |
| (default) | ✓ | ✓ | sonnet |
| `--depth=deep` | ✓ | ✓ | opus |

### Flags

- `--rules-only` — run rule checks only, skip model checks (equivalent to `--depth=shallow`)
- `--json` — output machine-readable JSON to stdout instead of formatted report
- `--depth=shallow|deep` — override model depth

### Atom Output Contract

Atoms write findings to a temp JSON file and output a single terminal line after `>>> RESULT <<<`:

- `OK PASS` — no findings
- `OK FAIL: BLOCKER st1,sf1; MAJOR st4; MINOR st6` — findings present (caller reads JSON for details)
- `FAIL: <execution error>` — atom error; treat all items in this atom as SKIP

Temp file paths:
- rule_checks atom → `/tmp/skill-quality-rule.json`
- model_checks atom → `/tmp/skill-quality-model.json`

### Findings JSON Schema

```json
{
  "rubric_version": "1.0",
  "target": "<absolute-path-to-SKILL.md>",
  "atom": "rule_checks | model_checks",
  "verdict": "PASS | FAIL",
  "sf2_flagged_lines": [42, 67],
  "items": [
    {
      "id": "st4",
      "section": "structure",
      "severity": "BLOCKER | MAJOR | MINOR",
      "result": "pass | fail | skip",
      "evidence": "<quoted text or line reference>",
      "fix_suggestion": "<concrete one-line fix>"
    }
  ]
}
```

`sf2_flagged_lines` — rule_checks atom only. Line numbers where SF2 destructive patterns were found. Used by check.md to pass to model_checks for documentation-context confirmation. Empty list `[]` if no SF2 matches.

### Stateless Operation

All commands are stateless and idempotent — no GitHub, no config files, no external state written. Safe to run multiple times.

### Example

```
/skill-quality check ./plugins/my-plugin/skills/my-skill
```

```
/skill-quality check: plugins/my-plugin/skills/my-skill
══════════════════════════════════════════════════════════════════════
Grade: A  (rubric v1.0)

MAJOR (2)
  [T1] WHAT not in description — "helps with tasks" is too vague
       Fix: Add what the skill does: "Generates unit tests for..."
  [C1] No org-specific knowledge — body reads as generic instructions
       Fix: Add project-specific constraints or examples

Suggestions (1)
  [R7] SKILL.md is 312 lines — consider moving content to references/

══════════════════════════════════════════════════════════════════════
BLOCKER: 0  MAJOR: 2  MINOR: 1
```
