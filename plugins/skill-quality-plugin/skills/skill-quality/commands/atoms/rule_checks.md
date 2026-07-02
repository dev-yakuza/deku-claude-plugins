# ATOM: rule_checks

**Single sub-agent. MUST NOT spawn Agent calls. MUST NOT spawn other sub-agents.**

Run all rule-based rubric checks against the target SKILL.md. Writes findings to `/tmp/skill-quality-rule.json` and outputs a single `>>> RESULT <<<` terminal line.

---

## Inputs

- `$1` — Absolute path to the skill package root (directory containing SKILL.md)

---

## Step 1 — Read the skill file

Read the file at `$1/SKILL.md` using the Read tool. If the file does not exist, output:

```
>>> RESULT <<<
FAIL: SKILL.md not found at $1/SKILL.md
```

Then stop.

---

## Step 2 — Parse frontmatter

Identify the frontmatter block:
- Look for the first `---` line (line 1 or within first 3 lines)
- Find the second `---` line that closes the block
- Everything before the first `---` or after the second `---` is the body

Extract:
- `frontmatter_text` — raw text between the two `---` delimiters
- `body_text` — all content after the closing `---`
- `body_line_count` — number of lines in body_text
- `total_line_count` — total lines in the file

Parse frontmatter fields as key: value pairs. For multiline values (indented continuation lines), capture the full value.

Extract these fields (null if absent):
- `name`, `description`, `when_to_use`, `argument-hint`, `user-invocable`
- `disable-model-invocation`, `context`, `effort`, `tools`

---

## Step 3 — Run each rule check

Work through ALL checks below in order. For each, record the result as `pass`, `fail`, or `skip`. Collect all findings.

**IMPORTANT — ST2 short-circuit:** If `description` field is absent or empty (ST2 = fail), immediately set ALL remaining checks to `skip` and jump to Step 4. Only ST2 will be a BLOCKER.

---

### ST1 — Valid YAML frontmatter [BLOCKER]

Condition to FAIL: no frontmatter block found (no `---` delimiters), OR frontmatter text cannot be parsed as valid YAML key-value pairs.

Validation:
1. Use the Write tool to save `frontmatter_text` to `/tmp/skill-quality-fm.yaml`
2. Run a single Bash call: `python3 -c "import yaml; yaml.safe_load(open('/tmp/skill-quality-fm.yaml').read()); print('OK')"`
3. If python3 is unavailable or returns an error, fall back: check in-model that every non-blank line in `frontmatter_text` starts with a word character followed by `:` (key: value) or starts with whitespace (indented continuation).

- FAIL evidence: "No frontmatter found" or "YAML parse error: <error>"
- PASS evidence: "Frontmatter parses as valid YAML"
- Fix: "Add valid YAML frontmatter between --- delimiters"

---

### ST2 — description field exists [BLOCKER]

Condition to FAIL: `description` field is null or empty string.

- FAIL evidence: "description field is absent"
- PASS evidence: "description: <first 60 chars>..."
- Fix: "Add description: field to frontmatter"

---

### ST3 — description + when_to_use ≤ 1536 chars [MAJOR]

Compute: `len(description) + len(when_to_use or "")`. FAIL if > 1536.

- FAIL evidence: "Combined length: <N> chars (limit: 1536)"
- Fix: "Shorten description and/or when_to_use to fit within 1536 chars combined"

---

### ST4 — name is kebab-case [MAJOR]

SKIP if `name` field is absent.

Condition to FAIL: `name` value does not match `^[a-z][a-z0-9-]*$` (lowercase letters, digits, hyphens only; must start with a letter).

- FAIL evidence: "name: <actual value>"
- Fix: "Rename to kebab-case, e.g. <suggested-kebab-version>"

---

### ST5 — UTF-8 encoding [BLOCKER]

Run a single Bash call, substituting `<root>` with the actual value of `$1`:
```
python3 -c "open('<root>/SKILL.md', encoding='utf-8', errors='strict').read(); print('OK')"
```
Use the absolute path — do not rely on the current working directory.

- FAIL evidence: "File contains non-UTF-8 bytes: <error>"
- Fix: "Re-save the file with UTF-8 encoding"

---

### ST6 — argument-hint format [MINOR]

SKIP if `argument-hint` field is absent.

Condition to FAIL: value does not contain `<`, `[`, or `(`.

- FAIL evidence: "argument-hint: '<value>' — no bracket characters"
- Fix: "Add bracket notation, e.g. argument-hint: \"<command> [options]\""

---

### ST7 — No duplicate frontmatter keys [MAJOR]

Parse raw frontmatter line-by-line. Collect all keys (lines matching `^[a-zA-Z_-]+:`). Check for duplicates.

- FAIL evidence: "Duplicate key: '<key>' appears <N> times"
- Fix: "Remove the duplicate '<key>' entry from frontmatter"

---

### ST8 — Body ≤ 500 lines [MAJOR]

Use `body_line_count` computed in Step 2.

- FAIL evidence: "Body is <N> lines (limit: 500)"
- Fix: "Move bulky content to references/ subdirectory; aim for a concise skill.md"

---

### F1 — name field present [BLOCKER]

Condition to FAIL: `name` key is entirely absent from frontmatter (distinct from ST4 which checks format).

- FAIL evidence: "name field is absent from frontmatter"
- Fix: "Add name: <your-skill-name> to frontmatter"

---

### F2 — disable-model-invocation consistent [MAJOR]

SKIP if `disable-model-invocation` is not `true`.

If `disable-model-invocation: true`, check description for trigger phrases (case-insensitive):
`use when`, `call this when`, `invoke when`, `run this when`, `trigger when`

Condition to FAIL: any trigger phrase found in description.

- FAIL evidence: "disable-model-invocation: true but description contains '<phrase>'"
- Fix: "Remove trigger language from description, or remove disable-model-invocation"

---

### F4 — effort valid value [MAJOR]

SKIP if `effort` field is absent.

Valid values: `low`, `medium`, `high`, `xhigh`, `max`.

- FAIL evidence: "effort: '<value>' is not a valid effort level"
- Fix: "Set effort to one of: low / medium / high / xhigh / max"

---

### F5 — tools field format [MINOR]

SKIP if `tools` field is absent.

Condition to FAIL: value is a non-empty string that is neither comma-separated nor a YAML list (i.e., it appears to be a freeform paragraph with no commas and no `- ` prefix patterns).

- FAIL evidence: "tools: value appears to be freeform text, not a list"
- Fix: "Use YAML list format: tools:\n  - tool1\n  - tool2"

---

### T3 — Third-person / imperative voice [MAJOR]

Check in-model (no Bash required): inspect the `description` value parsed in Step 2. Does it start (case-insensitive) with any of: `i `, `you `, `we `, `i'm `, `you're `, `we're `, `i'll `, `you'll `, `we'll `?

Condition to FAIL: the first word(s) of description match a first or second person pronoun.

- FAIL evidence: "description starts with '<matched phrase>'"
- Fix: "Rewrite in third-person or imperative: 'Evaluates...' or 'Evaluate...'"

---

### T6 — description length ≥ 50 chars [MINOR]

Condition to FAIL: `len(description)` < 50.

- FAIL evidence: "description is <N> chars (minimum: 50)"
- Fix: "Expand description to at least 50 characters"

---

### C3 — No time-bound statements [MINOR]

Search body_text for (case-insensitive):
- Phrases: `as of`, `currently`, `at the moment`, `at this time`
- 4-digit years: `\b(19|20)\d{2}\b`

Use a single Bash grep call on the file:
```
grep -niE "(as of|currently|at the moment|at this time|\b(19|20)[0-9]{2}\b)" "$1/SKILL.md"
```

Condition to FAIL: any match found.

- FAIL evidence: "Line <N>: '<matched line>'"
- Fix: "Remove time-bound references; write timeless instructions"

---

### R1 — references/ separation [MINOR]

SKIP if `body_line_count` ≤ 200.

If body > 200 lines: check whether `$1/references/` directory exists.

Condition to FAIL: body > 200 lines AND no `references/` directory.

Use Bash:
```
test -d "$1/references" && echo "exists" || echo "absent"
```

- FAIL evidence: "Body is <N> lines; no references/ directory found"
- Fix: "Create references/ and move large reference blocks there"

---

### R2 — scripts/ separation [MINOR]

Search body_text for code blocks of type `bash` or `python`. Count their lines. If any block exceeds 30 lines: check whether `$1/scripts/` exists.

Use Bash:
```
test -d "$1/scripts" && echo "exists" || echo "absent"
```

Condition to FAIL: any script block > 30 lines AND no `scripts/` directory.

- FAIL evidence: "Inline script block is <N> lines; no scripts/ directory found"
- Fix: "Move large script blocks to scripts/ and reference them"

---

### R3 — No absolute paths [MAJOR]

Search body_text for absolute path patterns: `/Users/`, `/home/`, `/root/`, `C:\`, `C:/`, `D:\`

Use Bash:
```
grep -nE "(/Users/|/home/|/root/|C:\\\\|C:/|D:\\\\)" "$1/SKILL.md"
```

Condition to FAIL: any match found.

- FAIL evidence: "Line <N>: '<matched line>'"
- Fix: "Replace absolute paths with relative paths or <<SKILL_DIR>> references"

---

### R4 — No broken <<SKILL_DIR>> references [MAJOR]

Extract all occurrences of `<<SKILL_DIR>>/...` from body_text. For each, isolate the relative path after `<<SKILL_DIR>>/`.

For each referenced path, resolve it relative to `$1` and check existence using Bash (one call per path):
```
test -f "$1/<relative-path>" && echo "exists" || echo "missing"
```

Condition to FAIL: any referenced path does not exist.

- FAIL evidence: "<<SKILL_DIR>>/<path> — file not found"
- Fix: "Create the missing file or correct the path reference"

---

### R5 — Script syntax valid [MAJOR]

For each ` ```bash ` code block in body_text:
1. Write block content to `/tmp/skill-quality-syntax-check.sh` using the Write tool
2. Run: `bash -n /tmp/skill-quality-syntax-check.sh`
3. FAIL if exit code ≠ 0

For each ` ```python ` code block in body_text:
1. Write block content to `/tmp/skill-quality-syntax-check.py` using the Write tool
2. Run: `python3 -m py_compile /tmp/skill-quality-syntax-check.py`
3. FAIL if exit code ≠ 0

SKIP if no bash/python blocks found, or if bash/python3 is not available.

- FAIL evidence: "Bash block (line <N>): <error message>"
- Fix: "Fix the syntax error in the script block"

---

### R7 — SKILL.md ≤ 200 lines [MINOR]

Use `total_line_count` from Step 2.

Condition to FAIL: total_line_count > 200.

- FAIL evidence: "SKILL.md is <N> lines total (suggestion: ≤ 200)"
- Fix: "Move heavy content to references/ to keep SKILL.md concise"

---

### R8 — references/ at most 1 level deep [MINOR]

SKIP if `$1/references/` does not exist.

Use Bash:
```
find "$1/references" -mindepth 2 -type d
```

Condition to FAIL: any output from find (meaning subdirectories inside references/).

- FAIL evidence: "Nested directory found: <path>"
- Fix: "Flatten references/ — move files to the top level of references/"

---

### SF1 — No plaintext secrets [BLOCKER]

Run a single Bash grep call:
```
grep -inE "(api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token|password|passwd)[[:space:]]*[:=][[:space:]]*[^[:space:]<{\[(\"']" "$1/SKILL.md"
```

For each match: check if the matched line contains any placeholder indicator (case-insensitive): `<`, `your-`, `your_`, `xxx`, `example`, `placeholder`, `changeme`, `dummy`, `fake`, `test`.

Condition to FAIL: any match found with NO placeholder indicator on the same line.

- FAIL evidence: "Line <N>: '<matched line>' — appears to be a real credential"
- Fix: "Replace real credentials with placeholders: <your-api-key>"

---

### SF2 — No unguarded destructive commands [MAJOR]

Run a single Bash grep call:
```
grep -inE "(rm -rf [^\x22\x27<]|DROP TABLE|DELETE FROM .{0,50} WHERE 1|git push.{0,20}--force|mkfs|dd if=)" "$1/SKILL.md"
```

Condition to FAIL (rule part): any match found. Record with `result: "fail"`. Also record the matched line numbers in `sf2_flagged_lines` (a top-level list in the JSON output) so check.md can pass them to model_checks for documentation-context confirmation. model_checks will make the final pass/fail call; check.md Step 6 uses model's SF2 result to override this entry.

If no match: `result: "pass"`, `sf2_flagged_lines: []`.

- FAIL evidence: "Line <N>: '<matched line>' — destructive pattern flagged"
- Fix: "Wrap in warning context, or confirm this is documentation-only"

---

## Step 4 — Compute summary

Count findings by severity:
- `blockers` = items with severity BLOCKER and result = fail
- `majors` = items with severity MAJOR and result = fail
- `minors` = items with severity MINOR and result = fail
- Exclude `skip` and `pass` from counts

---

## Step 5 — Write JSON findings

Use the Write tool to create `/tmp/skill-quality-rule.json`:

```json
{
  "rubric_version": "1.0",
  "target": "<$1/SKILL.md>",
  "atom": "rule_checks",
  "verdict": "<PASS if blockers=0 and majors=0 and minors=0, else FAIL>",
  "sf2_flagged_lines": [42, 67],
  "items": [
    {
      "id": "<item-id>",
      "section": "<section-name>",
      "severity": "<BLOCKER|MAJOR|MINOR>",
      "result": "<pass|fail|skip>",
      "evidence": "<quoted text or description>",
      "fix_suggestion": "<concrete one-line fix or empty string>"
    }
  ]
}
```

Include ALL 24 rule check items in the items array (pass, fail, and skip).

---

## Step 6 — Output terminal line

Output exactly:

```
>>> RESULT <<<
```

Followed immediately by one of:
- `OK PASS` — if no failures
- `OK FAIL: BLOCKER st1,sf1; MAJOR st3,st4; MINOR t6` — list only the IDs with result=fail, grouped by severity. Omit a severity group if empty.
- `FAIL: <error description>` — only if an unexpected execution error prevented the atom from completing
