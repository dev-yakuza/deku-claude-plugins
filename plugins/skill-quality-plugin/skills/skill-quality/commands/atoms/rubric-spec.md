# RUBRIC SPEC — Single Source of Truth

**Not an atom.** This file defines all 38 rubric items for reference. Read the relevant section when a command or atom needs implementation details.

---

## Section V — Validity

| ID | Severity | Type | Criterion |
|----|----------|------|-----------|
| V1 | MAJOR | model | Skill provides value not achievable by a plain Claude prompt. LLM must find ≥1 line of org-specific or procedural knowledge and quote it. If no such line exists: FAIL. |
| V2 | MAJOR | model | Description does not significantly overlap with built-in Claude Code skills (/code-review, /security-review, /run, /init, /sdd, /simplify, /verify). LLM judges overlap as HIGH/LOW; HIGH = FAIL. |

---

## Section ST — Structure

| ID | Severity | Type | Criterion |
|----|----------|------|-----------|
| ST1 | BLOCKER | rule | File starts with `---` on line 1. Frontmatter block (between first and second `---`) parses without error via `python3 -c "import yaml, sys; yaml.safe_load(sys.stdin)" < frontmatter`. Fallback if python3 absent: every line in frontmatter block matches `^[a-zA-Z_-]+:\s` or is a continuation. |
| ST2 | BLOCKER | rule | `description:` key exists in frontmatter AND value is non-empty string. **If frontmatter is entirely absent (no `---` at all), emit ONLY ST2 as BLOCKER and mark all other items as SKIP.** |
| ST3 | MAJOR | rule | `len(description) + len(when_to_use or "")` ≤ 1536 characters. |
| ST4 | MAJOR | rule | `name` field value matches regex `^[a-z][a-z0-9-]*$`. SKIP if `name` field is absent. |
| ST5 | BLOCKER | rule | File can be read as UTF-8 without error: `python3 -c "open('SKILL.md', encoding='utf-8', errors='strict').read(); print('OK')"`. |
| ST6 | MINOR | rule | If `argument-hint:` present, its value contains at least one of `<`, `[`, `(`. |
| ST7 | MAJOR | rule | No duplicate keys in frontmatter. Parse raw frontmatter lines; collect `key:` tokens; fail if any appears twice. |
| ST8 | MAJOR | rule | Line count of body (content after the closing `---` of frontmatter) ≤ 500. |

---

## Section F — Frontmatter Semantics

| ID | Severity | Type | Criterion |
|----|----------|------|-----------|
| F1 | BLOCKER | rule | `name:` key exists in frontmatter (regardless of value). Without it, the skill cannot be invoked by name. |
| F2 | MAJOR | rule | If `disable-model-invocation: true` is set, description must NOT contain trigger phrases: "Use when", "call this when", "invoke when", "run this when". If contradiction found: FAIL. |
| F3 | MAJOR | model | If `context: fork` is present in frontmatter, body must contain at least one concrete task or action clause. SKIP if `context: fork` not found. |
| F4 | MAJOR | rule | If `effort:` present, value must be exactly one of: `low`, `medium`, `high`, `xhigh`, `max`. |
| F5 | MINOR | rule | If `tools:` present, value must be a YAML sequence (`- item` lines) or a comma-separated string. Fail if value is a bare unstructured paragraph. |

---

## Section T — Trigger

| ID | Severity | Type | Criterion |
|----|----------|------|-----------|
| T1 | MAJOR | model | Description clearly states WHAT the skill does (its function/capability). LLM must quote the WHAT phrase. If no clear WHAT: FAIL. |
| T2 | MAJOR | model | Description clearly states WHEN to invoke (trigger conditions, "Use when…", or use-case list). LLM must quote the WHEN phrase. If no clear WHEN: FAIL. |
| T3 | MAJOR | rule | Description does NOT start with (case-insensitive): `I `, `You `, `We `, `I'm `, `You're `, `We're `, `I'll `, `You'll `, `We'll `. Also fails if description's first sentence subject is first/second person. |
| T4 | MAJOR | model | Trigger conditions are specific enough for Claude to reliably distinguish this skill from other available skills. LLM provides a concrete ambiguity scenario if failing. |
| T5 | MINOR | model | WHAT and WHEN both appear within the first 200 characters of description. |
| T6 | MINOR | rule | `len(description)` ≥ 50 characters. |

---

## Section C — Content

| ID | Severity | Type | Criterion |
|----|----------|------|-----------|
| C1 | MAJOR | model | Body contains ≥1 fact, rule, or procedure NOT derivable from public documentation. LLM must quote the specific line. If body reads as generic instructions: FAIL. |
| C2 | MAJOR | model | Body contains ≥1 worked example showing concrete input → output, before → after, or command → result. Quote the example. |
| C3 | MINOR | rule | Body does not contain time-bound phrases. Regex (case-insensitive): `\b(as of|currently|at the moment|at this time)\b` or 4-digit year `\b(19|20)\d{2}\b`. |
| C4 | MINOR | model | Same concepts use consistent terminology throughout the skill. LLM gives one example of inconsistency if failing. |
| C5 | MINOR | model | Level of prescriptiveness is appropriate for task risk: high-risk tasks (file deletion, deployments, external calls) are more prescriptive; low-risk tasks allow model freedom. |
| C6 | MINOR | model | Body states ≥1 failure mode, limitation, or "do NOT" guard clause. Quote it if present. |

---

## Section R — Resources

| ID | Severity | Type | Criterion |
|----|----------|------|-----------|
| R1 | MINOR | rule | If body line count > 200 AND no `references/` subdirectory exists in package root: suggest creating references/. |
| R2 | MINOR | rule | If any ` ```bash ` or ` ```python ` block in body is > 30 lines AND no `scripts/` subdirectory exists: suggest creating scripts/. |
| R3 | MAJOR | rule | Body contains no absolute filesystem paths. Regex: `/Users/`, `/home/`, `/root/`, `C:\`, `C:/`, `D:\`. |
| R4 | MAJOR | rule | All `<<SKILL_DIR>>/path` references in body point to files that exist on disk. Extract each reference path, resolve relative to package root, check existence. |
| R5 | MAJOR | rule | For each ` ```bash ` block: write content to temp file, run `bash -n <tempfile>`. For each ` ```python ` block: write content to temp file, run `python3 -m py_compile <tempfile>`. FAIL if exit code ≠ 0. SKIP language if interpreter not available. |
| R6 | MINOR | model | If body contains shell command sequences, they note expected exit behavior or include error guards (`|| exit 1`, `set -e`, fallback instructions). SKIP if no command sequences in body. |
| R7 | MINOR | rule | `SKILL.md` line count (total, including frontmatter) > 200 → suggest splitting content into references/. |
| R8 | MINOR | rule | If `references/` directory exists: no files are more than 1 directory level deep inside it. SKIP if references/ does not exist. |

---

## Section SF — Safety

| ID | Severity | Type | Criterion |
|----|----------|------|-----------|
| SF1 | BLOCKER | rule | Body contains no real secrets. Regex (case-insensitive): `(api[_-]?key\|secret[_-]?key\|access[_-]?token\|auth[_-]?token\|password\|passwd)[[:space:]]*[:=][[:space:]]*[^[:space:]<{\[(\x27\x22]`. **Exclude** lines matching (case-insensitive): `<`, `your[-_]`, `xxx`, `example`, `placeholder`, `changeme`, `dummy`, `fake`, `test`. BLOCKER only if a non-excluded match is found. |
| SF2 | MAJOR | rule+model | Body contains no unguarded destructive commands. Regex flags: `rm -rf [^"\x27<]`, `DROP TABLE`, `DELETE FROM .* WHERE 1`, `git push.*--force`, `mkfs`, `dd if=`. For each match, model confirms: is this in a documentation/warning context (PASS) or an actual execution instruction (FAIL)? |

---

## Report-Only

| ID | Severity | Type | Criterion |
|----|----------|------|-----------|
| X1 | MAJOR | model | Two or more skills in the same parent directory have descriptions so similar that Claude cannot reliably distinguish when to invoke each. Provide the conflicting pair and why. |

---

## BLOCKER Summary

`ST1` `ST2` `ST5` `F1` `SF1`

## Grade Formula

```
Count MAJOR failures (excluding SKIP items).

BLOCKER ≥ 1           → F
BLOCKER = 0, MAJOR  0 → S
BLOCKER = 0, MAJOR  1-2 → A
BLOCKER = 0, MAJOR  3-5 → B
BLOCKER = 0, MAJOR  6-9 → C
BLOCKER = 0, MAJOR 10+  → D
```

## ST2 Short-Circuit Rule

If `description` field is absent (ST2 = BLOCKER), skip ALL other checks and emit only:
- ST2: BLOCKER
- All remaining items: SKIP

This prevents a cascade of meaningless failures on a file that has no frontmatter at all.
