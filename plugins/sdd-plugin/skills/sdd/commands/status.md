# STATUS

Check the current progress of an Issue. **Read-only**: never posts comments, never sets labels.

## Input Validation
Before any other step: validate `$1` per Common Definitions → Issue Validation in `<<SKILL_DIR>>/SKILL.md`. If `$1` is a Pull Request, stop without making changes.

## Process

1. Read Issue with one call: `gh issue view $1 --json labels,title,comments`
2. Scan comments for stage-output markers:
   - `<!-- sdd:analyze:output -->`
   - `<!-- sdd:design:output -->`
   - `<!-- sdd:children:output -->` (parent marker)
   - `<!-- sdd:implement:plan -->`
   - `<!-- sdd:test:output -->`
3. Check related PRs: `gh pr list --search "Refs #$1"` (matches the PR body convention written by `implement_tdd.md`).
4. If the parent marker is present, extract child Issue numbers from the children comment and run `gh issue view <N> --json labels,title` per child (one Bash call each — no compounding).
5. Pass the collected data through the **unified renderer** below.

## Unified renderer

Single render function with a conditional `Children` section. Same fields shown for both paths; parent path adds the children block.

```
render_status(data):
    out  = "Issue #{n}: {title}{ (Parent) if is_parent}"
    out += "Stage: {stage_from_label}"
    out += render_checklist(data.markers, data.label)   # always 4 lines
    if data.is_parent:                                   # conditional
        out += render_children_block(data.children)
    return out
```

### Stage derivation (from label)

| Label | `Stage:` |
|---|---|
| `sdd:analyze` | `analyze` |
| `sdd:design` | `design` |
| `sdd:implement` | `implement` |
| `sdd:test` | `test` |
| `sdd:done` | `done` |
| (none) | `not started` |

### Checklist row rules

| Row | `completed` | `in progress` | else |
|---|---|---|---|
| Analyze | output marker present AND label ≥ design | label == `analyze` | not started |
| Design | output or children marker present AND label ≥ implement | label == `design` | not started |
| Implement | plan marker present AND label ≥ test (or PR merged) | label == `implement` | not started |
| Test | test output present AND label == done | label == `test` | not started |

### Children block (parent only)

Header `Children:` followed by one line per child showing `#<N>: <title> → sdd:<stage>` and a trailing progress summary (`Progress: X/N done, Y in progress, Z not started`). Append a `✓` after `sdd:done` children.

## Output examples

**Single Issue**:
```
Issue #123: Add login form
Stage: implement
- [x] Analyze: completed
- [x] Design: completed
- [ ] Implement: in progress
- [ ] Test: not started
PR: https://github.com/<owner>/<repo>/pull/456 (or "none")
```

**Parent Issue** (has `<!-- sdd:children:output -->`):
```
Issue #100: Auth system (Parent)
Stage: implement
- [x] Analyze: completed
- [x] Design: completed (3 child Issues)
- [ ] Implement: in progress
- [ ] Test: not started

Children:
  - #124: Login form    → sdd:done ✓
  - #125: Signup form   → sdd:implement
  - #126: OAuth         → sdd:analyze
Progress: 1/3 done, 1 in progress, 1 not started

PR: https://github.com/<owner>/<repo>/pull/456 (or "none")
```

The Children block is appended **only** when the parent marker is present. The PR line is shown for both paths (single Issue PR, or the parent's tracking PR if any).

## Invariants

- **Read-only contract.** Label/marker mismatches are reported as-is (no reconciliation, no auto-fix).
- **One renderer.** Single Issue and Parent Issue share the same fields; only the Children block differs.
