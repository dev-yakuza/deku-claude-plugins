# 02 — Multilingual Support

en / ko / ja. Sources: `SKILL.md` Common Definitions, `templates/en/*`, `templates/ko/*`, `templates/ja/*`, `commands/init.md`.

---

## 1. Supported Languages [PRESERVE]

| Code | Aliases | Templates dir |
|---|---|---|
| `en` | `english`, empty/default | `templates/en/` |
| `ko` | `korean`, `한국어` | `templates/ko/` |
| `ja` | `japanese`, `日本語` | `templates/ja/` |

[RETHINK: languages added organically. Adding a new language requires (a) new templates dir, (b) update regex in §3, (c) update `/sdd init` aliases. Consider plugin point for community-contributed translations.]

---

## 2. Language Detection [PRESERVE]

Priority:
1. `.github/.sdd-lang` file content
2. Detect from Issue body primary language
3. Fallback: `en`

Used by work atoms to select output templates.

---

## 3. Parent Issue Reference Regex [PRESERVE — load-bearing]

When a child Issue is created, its body contains a reference to the parent. The format differs by template language:

| Lang | Format |
|---|---|
| en | `Parent Issue: #<n>` |
| ko | `상위 Issue: #<n>` |
| ja | `親Issue: #<n>` |

**Canonical regex for detection across all languages**:

```
(Parent|상위 |親)Issue: #<n>
```

Note: `상위` is followed by a space (because Korean tokenization), `親` is NOT followed by a space (Japanese convention).

**Boundary rule** [PRESERVE]: append `([^0-9]|$)` when matching against a specific `<n>` to prevent `#683` matching `#6831`:

```jq
test("(Parent|상위 |親)Issue: #683([^0-9]|$)")
```

**Used by**:
- `/sdd auto` Phase 3.3 child auto-discovery
- `/sdd batch` Phase 3 generated script's auto-discovery loop
- `implement.md` Phase 7 child completion notification (parent lookup)
- `test.md` Phase 5 child completion notification
- `<<SKILL_DIR>>/SKILL.md` Parent/Child Issue Detection

[PRESERVE — load-bearing]: regex pattern is the single source of truth. Used in 5+ locations. The pattern itself (`(Parent|상위 |親)Issue: #<n>`) cannot change without breaking parent-child relationships for existing Issues.
[IMPROVE]: the regex LITERAL is duplicated across multiple files (auto.md, batch.md, multiple atoms, SKILL.md). A single helper definition + reference would DRY without changing the pattern. (Pattern preserved; duplication removed.)

---

## 4. Issue Template Files [PRESERVE]

Per language, copied to `.github/ISSUE_TEMPLATE/` by `/sdd init`:

| File | Purpose |
|---|---|
| `issue_new_feature.yml` | New feature request |
| `issue_enhancement.yml` | Enhancement to existing feature |
| `issue_bug_fix.yml` | Bug report |
| `issue_refactoring.yml` | Refactoring request |

All 4 files exist in `templates/{en,ko,ja}/`. Structure identical across languages (same fields, translated labels).

[IMPROVE: consider sharing field structure across languages, only translating display strings. Currently each lang/file is a full copy.]

---

## 5. Output Template Files [PRESERVE]

Used by work atoms to format Issue/PR comments:

| File | Used by | Marker block |
|---|---|---|
| `output_analyze.md` | `analyze_work` | `<!-- sdd:analyze:output -->` |
| `output_design.md` | `design_work` (single path) | `<!-- sdd:design:output -->` |
| `output_children.md` | `design_work` (children path) | `<!-- sdd:children:output -->` |
| `output_child_issue.md` | `design_work` (creating child Issue body) | `<!-- sdd:child-issue -->` |

Path lookup at runtime:
```
<<SKILL_DIR>>/templates/{lang}/output_<type>.md
```

[PRESERVE: template structure (sections, field names) is part of user contract.]
[IMPROVE: language-specific files share heading structure; only headings differ. Could be parameterized via translation dict.]

---

## 6. Translated Heading Conventions [PRESERVE — display only]

Headings/labels users see inside posted comments:

| Concept | en | ko | ja |
|---|---|---|---|
| Requirements Analysis | `Requirements Analysis` | `요구사항 분석` | `要件分析` |
| Feature List | `Feature List` | `기능 목록` | `機能リスト` |
| Priority | `Priority` | `우선순위` | `優先順位` |
| Design | `Design` | `설계` | `設計` |
| Children | `Children` (table headings) | `자식 Issue` | `子Issue` |

These exist in `templates/{lang}/output_*.md`. Not enforced by code, just user-visible.

[PRESERVE: display strings — users may have come to expect them.]

---

## 7. Test Result Strings [PRESERVE]

Test stage and atoms emit test pass/fail counts in canonical form:

```
TESTS: <p>/<t> FAILED: <f>
```

(Where `p` = passed, `t` = total, `f` = failed.) Format is **language-independent** — always English numerals.

[PRESERVE: machine-parsed by `tdd_step_review` and `implement.md` Phase 3.X result parser.]

---

## 8. Issue Template Multilingual Examples [REFERENCE]

`templates/en/issue_new_feature.yml` (~44 lines) defines GitHub Issue Forms YAML with English labels. `templates/ko/issue_new_feature.yml` translates labels to Korean but keeps the same field structure (`name`, `description`, `required`, etc.). Same for ja.

[IMPROVE: consider GitHub Issue Forms `metadata` for language tag — would let `/sdd init` auto-pick latest template version.]

---

## 9. Locale-Sensitive Behavior [PRESERVE]

None currently. All decision logic, sorting, and matching is locale-independent (machine readable). Multilingual support is **strictly presentation layer**.

[PRESERVE: locale-free logic is a strength; do not introduce locale-dependent behavior in rewrite.]
