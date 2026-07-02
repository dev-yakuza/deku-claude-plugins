# REPORT

**Batch-check all skills in a directory. Orchestrator.**

Finds every `SKILL.md` under the given path, spawns one isolated self-contained sub-agent per skill (parallel, cap 4), then produces a summary table and optional X1 cross-skill collision check.

Each per-file sub-agent runs checks INLINE using an embedded compact checklist — it does NOT read separate atom files and does NOT spawn further sub-agents.

---

## Step 1 — Parse arguments

- `$1` — root directory to scan (default: current working directory)
- `--depth=shallow` (default for report) or `--depth=deep`
- `--json` — output JSON array instead of formatted table

Resolve depth:
- `--depth=deep` → `depth = deep`, model = `opus`
- Otherwise → `depth = shallow`, model checks skipped (fast batch default)

---

## Step 2 — Find all SKILL.md files

Use the Bash tool (single call):
```
find "<root>" -name "SKILL.md" -not -path "*/fixtures/*"
```

Collect the list of absolute paths. If empty: report "No SKILL.md files found under `<root>`" and stop.

Derive each skill's package root = parent directory of each SKILL.md path.

---

## Step 3 — Spawn per-skill sub-agents (parallel, cap 4)

For each skill package root, spawn a self-contained sub-agent:
- `subagent_type`: `general-purpose`
- `model`: `opus` (deep) or `haiku` (shallow — rule checks only)
- `description`: `skill-quality check: <package-root>`
- `prompt` (substitute `<root>` with the actual package root path):

---

> You are doing a quick quality check on a Claude Code skill.
>
> **Skill file:** `<root>/SKILL.md`
> **Mode:** `<depth>` (shallow = rule checks only; deep = rule checks + model judgment)
>
> **Step A — Read the file**
> Read `<root>/SKILL.md` using the Read tool. If not found:
> Return exactly: `GRADE:F TARGET:<root>/SKILL.md BLOCKER:1 MAJOR:0 MINOR:0 SKIP:0`
>
> **Step B — Parse frontmatter and body**
> - frontmatter = text between first `---` and second `---` (or absent if no `---`)
> - body = everything after the closing `---`
> - body_lines = line count of body
> - Extract from frontmatter: `name`, `description`, `when_to_use`, `argument-hint`, `disable-model-invocation`, `effort`, `tools`
>
> **Step C — BLOCKER checks (any BLOCKER → grade F immediately)**
>
> Run all 5 in order. If any fails, jump to Step F with grade F.
>
> **[ST1 BLOCKER]** Does the file have `---` frontmatter AND does the frontmatter parse as valid key:value YAML?
> - Write frontmatter text to `/tmp/sqr-fm-check.yaml` using the Write tool
> - Run: `python3 -c "import yaml; yaml.safe_load(open('/tmp/sqr-fm-check.yaml').read()); print('OK')"`
> - FAIL if no frontmatter or python3 errors
>
> **[ST2 BLOCKER]** Is `description` field present and non-empty?
> - FAIL if absent. If ST2 fails, mark all remaining checks as SKIP and jump to Step F with grade F.
>
> **[ST5 BLOCKER]** Is the file valid UTF-8?
> - Run: `python3 -c "open('<root>/SKILL.md', encoding='utf-8', errors='strict').read(); print('OK')"`
> - FAIL if error
>
> **[F1 BLOCKER]** Is `name` field present in frontmatter?
> - FAIL if `name` key absent (regardless of value)
>
> **[SF1 BLOCKER]** Does the body contain real secrets?
> - Run: `grep -inE "(api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token|password|passwd)[[:space:]]*[:=][[:space:]]*[^[:space:]<{\[('\"]" "<root>/SKILL.md"`
> - For each match: check if the line contains a placeholder (`<`, `your-`, `xxx`, `example`, `placeholder`, `changeme`, `dummy`, `fake`, `test`)
> - FAIL only if a match is found with NO placeholder on that line
>
> **Step D — MAJOR rule checks (count failures)**
>
> **[ST3]** len(description) + len(when_to_use or "") > 1536? → MAJOR
>
> **[ST4]** `name` value does not match `^[a-z][a-z0-9-]*$`? → MAJOR (SKIP if name absent)
>
> **[ST7]** Duplicate keys in frontmatter? Parse line-by-line and collect key tokens. → MAJOR if any duplicated
>
> **[ST8]** body_lines > 500? → MAJOR
>
> **[T3]** Does description start (case-insensitive) with `i `, `you `, `we `, `i'm `, `you're `, `we're `? Check in-model. → MAJOR if yes
>
> **[R3]** Absolute paths in body?
> - Run: `grep -nE "(/Users/|/home/|/root/|C:\\\\|C:/)" "<root>/SKILL.md"`
> - → MAJOR if any match
>
> **[SF2]** Unguarded destructive commands?
> - Run: `grep -inE "(rm -rf [^\"'<]|DROP TABLE|DELETE FROM .{0,50} WHERE 1|git push.{0,20}--force|mkfs|dd if=)" "<root>/SKILL.md"`
> - If matches found: judge in-model whether each is a documentation/example context (PASS) or an actual execution instruction (MAJOR)
>
> **Step E — Model judgment checks (depth=deep only)**
>
> Skip this step entirely if depth=shallow.
>
> **[T1]** Does description clearly state WHAT this skill does? (Y=PASS/N=MAJOR)
>
> **[T2]** Does description clearly state WHEN to invoke it? (Y=PASS/N=MAJOR)
>
> **[V1]** Does the skill provide value not achievable by a plain Claude prompt? Look for org-specific facts. (Y=PASS/N=MAJOR)
>
> **[C1]** Does the body contain ≥1 fact not derivable from public docs? (Y=PASS/N=MAJOR)
>
> **[C2]** Does the body contain ≥1 worked example (input → output)? (Y=PASS/N=MAJOR)
>
> **Step F — Compute grade and return**
>
> Count BLOCKER and MAJOR failures.
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
      "blocker": <n>,
      "major": <n>,
      "minor": <n>,
      "skip": <n>
    }
  ],
  "summary": {
    "total": <n>,
    "by_grade": { "S": <n>, "A": <n>, "B": <n>, "C": <n>, "D": <n>, "F": <n>, "ERROR": <n> }
  },
  "x1_collisions": [
    { "skill_a": "<path>", "skill_b": "<path>", "reason": "<text>" }
  ]
}
```
