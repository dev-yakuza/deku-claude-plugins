# STATUS

Show the current progress of an Issue. **Read-only**: never posts comments, never sets labels. State source = GitHub labels + stage-output markers (`_handoff.md` Sections A/B).

`$1` = Issue number.

> **Bash**: `_bash_rules.md`.

---

## Process
1. Validate `$1` is an Issue (not a PR):
   ```bash
   gh issue view $1 --json url --jq .url
   ```
   `/pull/` → report "not an Issue"; stop.
2. Read the Issue in one call:
   ```bash
   gh issue view $1 --json labels,title,comments
   ```
3. Derive the current **stage** from the `guild:*` label (Section A table below).
4. Scan comments for stage-output markers to build the checklist:
   - `<!-- guild:analyze:output -->`
   - `<!-- guild:design:output -->`
   - `<!-- guild:test-evidence:step-1 -->` (execute produced evidence)
   - `<!-- guild:test:output -->`
   - `<!-- guild:qa:output -->`
5. Find the related PR:
   ```bash
   gh pr list --search "Refs #$1" --json number,url,state
   ```
6. Render (below).

### Stage derivation (from label)
| Label | Stage |
|---|---|
| `guild:analyze` | analyze |
| `guild:design` | design |
| `guild:execute` | execute |
| `guild:test` | test |
| `guild:qa` | qa |
| `guild:children` | orchestrating (split parent) |
| `guild:done` | done |
| (none) | not started |

### Checklist rules
| Row | completed | in progress | else |
|---|---|---|---|
| Analyze | analyze marker present AND label ≥ design | label == analyze | not started |
| Design | design marker present AND label ≥ execute | label == design | not started |
| Execute | evidence marker present AND label ≥ test (or PR open) | label == execute | not started |
| Test | test output present AND label ≥ qa | label == test | not started |
| QA | qa output present AND label == done | label == qa | not started |

(Label order: analyze < design < execute < test < qa < done.)

## Output example
```
Issue #123: Add login form
Stage: execute
- [x] Analyze: completed
- [x] Design: completed
- [ ] Execute: in progress
- [ ] Test: not started
- [ ] QA: not started
PR: https://github.com/<owner>/<repo>/pull/456 (open)   (or "none")
```

If the Issue has a `guild:child` label, note it (`(child)`) and, if the body references a parent (`Parent Issue: #<n>`), show `Parent: #<n>`.

### Split parent (`guild:children`)
If the Issue is a split parent, render a **children checklist** instead of the single-Issue stage checklist (`_handoff.md` Section I):
1. Discover its children (its own read-only Bash call — substitute the **literal** parent number for `<parent>`; no shell `$1` inside the jq string, per `_bash_rules.md` / `_handoff.md` Section I):
   ```bash
   gh issue list --label guild:child --state all --limit 200 --json number,title,body,labels --jq '[.[] | select((.body // "") | test("Parent Issue: #<parent>([^0-9]|$)"))] | sort_by(.number) | .[] | {number, title, stage: ([.labels[].name] | map(select(startswith("guild:"))) | join(","))}'
   ```
2. For each child, derive its stage from its `guild:*` label (same table above). Mark `[x]` when the child is `guild:done`.
3. Render `Children: <done>/<total> done` + one line per child. If a `<!-- guild:integration:output -->` comment exists, show integration = done; else pending.
```
Issue #838: Word detail screen  (split parent)
Stage: orchestrating (split parent)
Children: 1/3 done
- [x] #841 DB schema slice — done
- [ ] #842 detail view slice — execute
- [ ] #843 entry-point slice — not started
Integration: pending
```

## Invariants
- **Read-only.** Label/marker mismatches are reported as-is (no reconciliation, no auto-fix) — same discipline as sdd's status.
- One renderer for all Issues.
