---
name: sdd
description: "Spec-Driven Development - AI collaborative development process with GitHub integration. Use when working on GitHub Issues with a structured process: analyze → design → implement (TDD) → test."
argument-hint: "<command> [issue-number]"
user-invocable: true
---

# SDD (Spec-Driven Development)

You are executing the SDD process. Route to the appropriate command based on `$0`.

**IMPORTANT:** After routing, read the command detail file from `${CLAUDE_SKILL_DIR}/commands/<command>.md` and execute the instructions in it.

## Command Routing

Read `${CLAUDE_SKILL_DIR}/commands/$0.md` and execute. Pass `$1` as issue number (or language for init), `$2` as target stage for rollback.
- Valid commands: `init`, `analyze`, `design`, `implement`, `test`, `resume`, `status`, `review`, `rollback`, `help`
- If `$0` is empty → route to `help`
- If `$0` is not in the list above → report unknown command, then route to `help`

---

## Common Definitions

### Stage Flow
```
1. analyze (What/Why) → 2. design (How) → 3. implement (TDD) → 4. test (E2E/QA) → done
```

### Labels
`sdd:analyze` → `sdd:design` → `sdd:implement` → `sdd:test` → `sdd:done` | `sdd:child` (child Issue)

### Output Markers
| Marker | Location | Purpose |
|--------|----------|---------|
| `<!-- sdd:analyze:output -->` | Issue comment | Analysis result |
| `<!-- sdd:design:output -->` | Issue comment | Design result |
| `<!-- sdd:children:output -->` | Issue comment | Child Issue list (parent only) |
| `<!-- sdd:child-issue -->` | Issue body | Child Issue identifier |
| `<!-- sdd:rollback -->` | Issue comment | Rollback notice |

### Parent/Child Issue Detection
- **Parent Issue**: has `<!-- sdd:children:output -->` marker in comments
- **Child Issue**: body contains `Parent Issue: #<number>` inside `<!-- sdd:child-issue -->` block
- **Single Issue**: neither parent nor child

### Language Setting
- Stored in `.github/.sdd-lang` (default: en)
- Set by `/sdd init [lang]`
- Languages: `en` (default), `ko`/`korean`/`한국어`, `ja`/`japanese`/`日本語`

### Duplicate Output Prevention
Before posting a stage output, search Issue comments for the matching marker. If found → update that comment. If not → create new comment.

