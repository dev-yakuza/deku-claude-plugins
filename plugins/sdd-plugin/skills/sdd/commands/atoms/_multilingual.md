# Multilingual Support (shared)

Cross-cutting multilingual rules. Extracted from `SKILL.md` so every caller (auto.md, batch.md, design_work atom, etc.) has one source of truth.

---

## Supported languages

| Code | Aliases | Templates dir |
|---|---|---|
| `en` | `english`, empty/default | `templates/en/` |
| `ko` | `korean`, `한국어` | `templates/ko/` |
| `ja` | `japanese`, `日本語` | `templates/ja/` |

Language stored in `.github/.sdd-lang` (set by `/sdd init [lang]`).

---

## Language detection (when `.sdd-lang` absent)

1. Detect primary language of the Issue body.
2. Map to closest supported (`en`, `ko`, `ja`).
3. Unsupported → default `en`.

---

## Parent/Child Issue detection

### Identification
- **Parent Issue**: has `<!-- sdd:children:output -->` marker in comments
- **Child Issue**: body contains `(Parent|상위 |親)Issue: #<n>` inside `<!-- sdd:child-issue -->` block
- **Single Issue**: neither parent nor child

### Multi-language parent reference

Child Issues created from non-English templates use translated keywords. To detect a child Issue's parent reference across all supported languages, use the canonical regex:

```
(Parent|상위 |親)Issue: #<n>
```

Note: `상위` is followed by a space (Korean tokenization); `親` is NOT followed by a space (Japanese convention).

### Boundary rule

Append `([^0-9]|$)` when matching against a specific `<n>` to prevent `#683` matching `#6831`:

```jq
test("(Parent|상위 |親)Issue: #683([^0-9]|$)")
```

---

## Where this regex is used

- `/sdd auto` Phase 3.3 child auto-discovery
- `/sdd batch` Phase 3 generated script's auto-discovery loop
- `implement.md` Phase 7 child completion notification (parent lookup)
- `test.md` Phase 5 child completion notification

All callers should reference this single source rather than re-quoting the regex literally.

---

## Output templates per language

Used by work atoms to format Issue/PR comments. Path lookup at runtime:
```
<<SKILL_DIR>>/templates/{lang}/output_<type>.md
```

| File | Used by | Marker block |
|---|---|---|
| `output_analyze.md` | `analyze_work` | `<!-- sdd:analyze:output -->` |
| `output_design.md` | `design_work` (single path) | `<!-- sdd:design:output -->` |
| `output_children.md` | `design_work` (children path) | `<!-- sdd:children:output -->` |
| `output_child_issue.md` | `design_work` (creating child Issue body) | `<!-- sdd:child-issue -->` |

---

## Test result strings (locale-independent)

Test stage and atoms emit test pass/fail counts in canonical form, always English numerals:

```
TESTS: <p>/<t> FAILED: <f>
```

(Where `p` = passed, `t` = total, `f` = failed.)

Machine-parsed by `tdd_step_review` and `implement.md` Phase 3.X result parser.
