# RUBRIC

Display the full 38-item quality rubric with criteria. No path argument needed.

---

Output the following text exactly:

```
skill-quality Rubric v1.0 — 38 items across 7 sections + 1 report-only item
══════════════════════════════════════════════════════════════════════════════

SEVERITY LEGEND
  [B] BLOCKER  Must fix — prevents loading or invocation. 1+ → grade F.
  [M] MAJOR    Degrades quality or trigger reliability. Affects grade.
  [m] MINOR    Suggestion. Does not affect grade.
  [R] Rule     Checked mechanically (regex / count / syntax)
  [L] Model    Checked by LLM judgment (binary Y/N + evidence)

──────────────────────────────────────────────────────────────────────────────
SECTION V — Validity (2 items)
──────────────────────────────────────────────────────────────────────────────
V1  [M][L]  Unique purpose + LLM-exceeding value
           Skill provides value not achievable by a plain Claude prompt.
           Evidence of org-specific or procedural knowledge required.

V2  [M][L]  No redundancy with built-in tools
           Description does not significantly overlap with built-in Claude Code
           skills (/code-review, /security-review, /run, /init, etc.).

──────────────────────────────────────────────────────────────────────────────
SECTION ST — Structure (8 items)
──────────────────────────────────────────────────────────────────────────────
ST1 [B][R]  Valid YAML frontmatter
           File starts with --- delimiter; frontmatter parses as valid YAML.

ST2 [B][R]  description field exists and is non-empty
           If frontmatter is entirely absent, only ST2 is emitted (others SKIP).

ST3 [M][R]  description + when_to_use ≤ 1536 chars (combined)
           Anthropic truncates at 1536 chars; excess content is invisible.

ST4 [M][R]  name is kebab-case
           Matches ^[a-z][a-z0-9-]*$ (SKIP if name field absent).

ST5 [B][R]  File is valid UTF-8
           Non-UTF-8 bytes cause silent load failures.

ST6 [m][R]  argument-hint format
           If present, value contains < or [ brackets indicating arg shape.

ST7 [M][R]  No duplicate frontmatter keys
           Duplicate YAML keys cause unpredictable field resolution.

ST8 [M][R]  Body ≤ 500 lines
           Exceeding 500 lines significantly increases token load per invocation.

──────────────────────────────────────────────────────────────────────────────
SECTION F — Frontmatter Semantics (5 items)
──────────────────────────────────────────────────────────────────────────────
F1  [B][R]  name field present
           Without name, Claude cannot invoke the skill by name. BLOCKER.

F2  [M][R]  disable-model-invocation consistent with description
           If disable-model-invocation: true, description must not contain
           trigger language ("Use when", "call this when", etc.).

F3  [M][L]  context: fork has actionable task
           If context: fork is set, body must contain a concrete task.
           (SKIP if context: fork not present.)

F4  [M][R]  effort is a valid value
           If effort: present, value must be one of:
           low / medium / high / xhigh / max

F5  [m][R]  tools field format
           If tools: present, value must be a YAML list or comma-separated
           string (not an unstructured freeform value).

──────────────────────────────────────────────────────────────────────────────
SECTION T — Trigger (6 items)
──────────────────────────────────────────────────────────────────────────────
T1  [M][L]  description contains WHAT (the skill's function)
           A reader should know WHAT the skill does from the description alone.
           Evidence quote required.

T2  [M][L]  description contains WHEN (trigger conditions)
           A reader should know WHEN to invoke this skill vs other skills.
           Evidence quote required.

T3  [M][R]  description uses third-person / imperative voice
           Must not start with "I ", "You ", "We ", "I'm ", "You're ", "We're ".

T4  [M][L]  Trigger conditions are specific
           Claude can reliably decide to call this skill vs others. No ambiguous
           overlap with common requests.

T5  [m][L]  High-signal content appears within first 200 chars
           WHAT and WHEN should be front-loaded before the 1536-char truncation
           point reduces visibility.

T6  [m][R]  description length ≥ 50 chars
           Very short descriptions lack enough signal for reliable triggering.

──────────────────────────────────────────────────────────────────────────────
SECTION C — Content (6 items)
──────────────────────────────────────────────────────────────────────────────
C1  [M][L]  Body contains org-specific / non-derivable knowledge
           At least one fact, rule, or procedure that cannot be found in public
           documentation. Evidence quote required.

C2  [M][L]  At least one worked example (input → output / before → after)
           Worked examples measurably improve skill reliability. Quote required.

C3  [m][R]  No time-bound statements
           Phrases like "as of 2024", "currently", "at the moment" become stale.

C4  [m][L]  Terminology is consistent
           Same concepts use the same terms throughout the skill body.

C5  [m][L]  Autonomy is calibrated to task risk
           High-risk/destructive tasks are more prescriptive; low-risk tasks
           allow appropriate model freedom.

C6  [m][L]  Failure modes or limits are documented
           At least one "do NOT", guard clause, or known limitation stated.

──────────────────────────────────────────────────────────────────────────────
SECTION R — Resources (8 items)
──────────────────────────────────────────────────────────────────────────────
R1  [m][R]  Heavy reference content moved to references/
           If body > 200 lines, a references/ subdirectory is recommended.

R2  [m][R]  Scripts moved to scripts/
           Inline script blocks > 30 lines should live in scripts/.

R3  [M][R]  No absolute paths
           No /Users/, /home/, C:\, /root/ in skill body (breaks portability).

R4  [M][R]  No broken <<SKILL_DIR>> references
           All <<SKILL_DIR>>/path references point to existing files.

R5  [M][R]  Script syntax is valid
           ```bash blocks verified with bash -n.
           ```python blocks verified with python3 -m py_compile.
           Other languages: SKIP.

R6  [m][L]  Scripts include error handling
           Command sequences note expected exit codes or failure behavior.
           (SKIP if no scripts in body.)

R7  [m][R]  SKILL.md ≤ 200 lines (load-size suggestion)
           Files over 200 lines increase per-invocation token cost noticeably.

R8  [m][R]  references/ is at most 1 level deep
           Nested subdirectories inside references/ reduce maintainability.
           (SKIP if references/ does not exist.)

──────────────────────────────────────────────────────────────────────────────
SECTION SF — Safety (2 items)
──────────────────────────────────────────────────────────────────────────────
SF1 [B][R]  No plaintext secrets
           No real API keys, tokens, or passwords. Placeholders (<key>,
           your-key, xxx, example, changeme) are allowed and excluded.

SF2 [M][R+L] No unguarded destructive commands
           Patterns like `rm -rf`, `DROP TABLE`, `git push --force` flagged.
           Model confirms whether context is documentation (PASS) or instruction
           (MAJOR). Placeholders and quoted examples are excluded.

──────────────────────────────────────────────────────────────────────────────
REPORT-ONLY
──────────────────────────────────────────────────────────────────────────────
X1  [M][L]  No description collision between sibling skills
           Two skills in the same directory should not have descriptions so
           similar that Claude cannot distinguish when to call each.
           (report command only — requires comparing multiple skills.)

══════════════════════════════════════════════════════════════════════════════
Run /skill-quality check <path> to evaluate a skill.
Run /skill-quality help for usage.
```
