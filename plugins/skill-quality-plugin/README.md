# skill-quality-plugin

Evaluate Claude Code skill files against a structured 38-item quality rubric before publishing to a marketplace or team library.

## Why

Skills with missing descriptions, vague trigger conditions, or poor structure fail to trigger reliably — Claude cannot decide when or whether to call them. This plugin catches those issues before they reach users.

## Install

Add to your `.claude-plugin/marketplace.json` or install via the Claude Code plugin marketplace.

## Usage

```
/skill-quality check [path] [--depth=shallow|deep] [--rules-only] [--json]
/skill-quality report [path] [--depth=shallow|deep] [--json]
/skill-quality rubric
/skill-quality help
```

### check — Evaluate a single skill

```bash
# Check the skill in the current directory
/skill-quality check .

# Check a specific skill
/skill-quality check ./plugins/my-plugin/skills/my-skill

# Fast rule-only check (no LLM model checks)
/skill-quality check . --rules-only

# Deep check with opus for model judgments
/skill-quality check . --depth=deep

# Machine-readable output for CI/CD
/skill-quality check . --json
```

**Example output:**

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

### report — Batch-check a directory

```bash
# Quick audit of all skills (rule checks only)
/skill-quality report ./plugins

# Deep audit with model checks
/skill-quality report ./plugins --depth=deep
```

**Example output:**

```
/skill-quality report: ./plugins
Depth: shallow  Skills found: 4
══════════════════════════════════════════════════════════════════════

  Grade  B  M  Suggestions  Skill
  ─────────────────────────────────────────────────────────────────
  S      0  0  0            plugins/sdd-plugin/skills/sdd
  A      0  2  1            plugins/pr-tool/skills/pr-check
  B      0  4  2            plugins/changelog/skills/changelog-gen
  F      1  0  0            plugins/draft/skills/my-draft

══════════════════════════════════════════════════════════════════════
Summary
  S: 1  A: 1  B: 1  C: 0  D: 0  F: 1
  Total skills: 4  Not publishable (F): 1
```

### rubric — Show the full rubric

```
/skill-quality rubric
```

Displays all 38 items with criteria, severity, and check type.

## Grades

| Grade | Condition | Meaning |
|-------|-----------|---------|
| **S** | 0 BLOCKER, 0 MAJOR | Publish-ready |
| **A** | 0 BLOCKER, 1–2 MAJOR | Publish with minor fixes |
| **B** | 0 BLOCKER, 3–5 MAJOR | Needs work before publishing |
| **C** | 0 BLOCKER, 6–9 MAJOR | Significant issues |
| **D** | 0 BLOCKER, 10+ MAJOR | Major revision needed |
| **F** | 1+ BLOCKER | Not publishable |

## Rubric Overview

38 items across 7 sections:

| Section | Items | BLOCKERs | Focus |
|---------|-------|----------|-------|
| ST — Structure | 8 | 3 | Valid frontmatter, name format, size |
| F — Frontmatter Semantics | 5 | 1 | Field consistency, effort values |
| T — Trigger | 6 | 0 | WHAT/WHEN clarity, voice, specificity |
| C — Content | 6 | 0 | Org-specific knowledge, examples |
| R — Resources | 8 | 0 | Path hygiene, references structure |
| SF — Safety | 2 | 2 | No secrets, no destructive commands |
| V — Validity | 2 | 0 | Purpose, non-redundancy |

Run `/skill-quality rubric` for the complete list with criteria.

## Depth Modes

| Mode | Speed | Model | Use case |
|------|-------|-------|----------|
| `--rules-only` / `--depth=shallow` | Fast | haiku | Pre-commit quick check |
| default | Medium | sonnet | Standard pre-publish check |
| `--depth=deep` | Thorough | opus | Final quality gate |

## Architecture

- **check**: Main session spawns rule_checks (haiku) → model_checks (sonnet/opus) as isolated sub-agents. Main session only reads `>>> RESULT <<<` summary lines — context stays minimal.
- **report**: Main session spawns one self-contained sub-agent per skill (parallel, cap 4) with an inline checklist — no further nesting.

## Fixtures

The `fixtures/` directory contains example skills demonstrating each grade tier:

- `fixtures/example-s-grade/` — Grade S (publish-ready)
- `fixtures/example-b-grade/` — Grade B (needs work)
- `fixtures/example-f-grade/` — Grade F (has BLOCKERs)

Run `/skill-quality check ./plugins/skill-quality-plugin/fixtures/example-s-grade` to see a passing report.

## License

MIT
