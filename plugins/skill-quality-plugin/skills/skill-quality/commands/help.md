# HELP

Print usage information for the skill-quality plugin.

---

Output the following text exactly:

```
skill-quality — Claude Code Skill Quality Rubric (v1.0)

USAGE
  /skill-quality <command> [path] [flags]

COMMANDS
  check   Evaluate a single skill against the 38-item rubric
  report  Batch-check all skills in a directory
  rubric  Show the full rubric with all 38 items and criteria
  help    Show this help

CHECK
  /skill-quality check ./skills/my-skill
  /skill-quality check ./skills/my-skill/SKILL.md
  /skill-quality check . --depth=deep
  /skill-quality check . --rules-only
  /skill-quality check . --json

  path        Directory containing SKILL.md, or the SKILL.md file itself.
              Defaults to current working directory.
  --depth     shallow: rule checks only (fast)
              deep:    rule + model checks at opus (thorough)
              default: rule + model checks at sonnet
  --rules-only  Alias for --depth=shallow
  --json      Output machine-readable JSON (for CI/CD)

REPORT
  /skill-quality report ./plugins
  /skill-quality report . --depth=shallow

  path        Root directory to scan recursively for SKILL.md files.
              Defaults to current working directory.
  --depth     shallow (default for report), deep
  --json      Output JSON array of per-skill results

GRADES
  S  0 BLOCKER, 0 MAJOR          (publish-ready)
  A  0 BLOCKER, 1–2 MAJOR        (publish with minor fixes)
  B  0 BLOCKER, 3–5 MAJOR        (needs work before publishing)
  C  0 BLOCKER, 6–9 MAJOR        (significant issues)
  D  0 BLOCKER, 10+ MAJOR        (major revision needed)
  F  1+ BLOCKER                  (not publishable)

SEVERITY
  BLOCKER  Prevents correct loading or invocation — must fix (5 items)
  MAJOR    Significantly degrades quality or trigger reliability
  MINOR    Suggestions for improvement — does not affect grade

RUBRIC SECTIONS
  ST  Structure (8 items)        F  Frontmatter Semantics (5 items)
  T   Trigger (6 items)          C  Content (6 items)
  R   Resources (8 items)        SF Safety (2 items)
  V   Validity (2 items)         X1 Cross-skill collision (report only)

  Run /skill-quality rubric to see all 38 items with criteria.

EXAMPLES
  Check a skill before publishing:
    /skill-quality check ./plugins/my-plugin/skills/my-skill

  Batch audit a plugin's skills:
    /skill-quality report ./plugins/my-plugin --depth=shallow

  CI/CD gate (check exit-equivalent via --json output):
    /skill-quality check . --json
```
