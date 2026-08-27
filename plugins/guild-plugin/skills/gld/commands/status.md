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
3. Derive the current **stage** from those labels with `_handoff.md` **Section A — canonical stage derivation**, which yields `stage` (the single current stage label — `guild:analyze`…`guild:done`, or `guild:children` for a split parent — or `"none"` when there is none), `paused` (`guild:needs-human` present), `harness` (`guild:harness` present) and `sprint` (`guild:sprint` present), having dropped `guild:child` (permanent identity marker, never a stage). ⚠ **`sprint` must be projected, not just excluded.** Excluding it from the stage scan is what makes a tracking Issue return `"none"`; the render rule below then needs the flag itself to say why, and reading a field the projection does not produce leaves the tracker rendering as a bare "not started". Applied to the labels already read in step 2, that is:
   ```
   {stage: ([.labels[].name] | map(select(startswith("guild:") and . != "guild:child" and . != "guild:needs-human" and . != "guild:harness" and . != "guild:sprint")) | .[0] // "none"), paused: ([.labels[].name] | any(. == "guild:needs-human")), harness: ([.labels[].name] | any(. == "guild:harness")), sprint: ([.labels[].name] | any(. == "guild:sprint"))}
   ```
   Render `stage` through the derivation table below. `paused`, `harness` and `(child)` are **annotations rendered alongside** the stage, never in place of it. **`paused == true` gets a prominent leading line** (see the output example) — do not let it hide behind the plain stage line, since `batch`/`monitoring`/`sprint` all treat `guild:needs-human` as first-class and a human relying on `status` alone should see it too.
4. Scan comments for stage-output markers to build the checklist:
   - `<!-- guild:analyze:output -->`
   - `<!-- guild:design:output -->`
   - `<!-- guild:test-evidence:step-1 -->` (execute produced evidence)
   - `<!-- guild:test:output -->`
   - `<!-- guild:qa:output -->`
5. Find the related PR — **resolve it broadly, the same way `review.md` Step 0 does.** A literal `"Closes #$1"` search is too narrow: a PR may use `Fixes`/`Fixed`/`Resolves`/`Resolved`/`Close`/`Closed` (all of GitHub's closing keywords, case-insensitive), or link the Issue purely through the PR sidebar's "Development" feature with no closing keyword in the body at all — so `status` would report "PR: none" for a PR `/gld review $1` finds:
   ```bash
   gh pr list --search "#$1 in:body" --json number,url,state,body
   ```
   Then keep only PRs whose body contains `$1` as a closing/fixing reference (`\b(close[sd]?|fix(e[sd])?|resolve[sd]?)\s*:?\s*#$1\b`, case-insensitive), or whose title/body otherwise makes the link obvious. Nothing matched → render `PR: none` (status is read-only — it never asks or edits; a sidebar-only link stays invisible to this search).
6. Render (below).

### Stage rendering (from the derived `stage`)
| Derived `stage` | Rendered as |
|---|---|
| `guild:analyze` | analyze |
| `guild:design` | design |
| `guild:execute` | execute |
| `guild:test` | test |
| `guild:qa` | qa |
| `guild:children` | orchestrating (split parent) |
| `guild:done` | done |
| `"none"` **and** `harness == true` | harness remediation — not started |
| `"none"` | not started |

The **sprint row** matters for the same reason the harness row does: `guild:sprint` is not a stage, so the derivation returns `"none"` for a tracking Issue and it would render as a bare "not started", indistinguishable from an Issue Guild has never seen. When `sprint == true`, render `sprint (tracking Issue)` and say what to run instead: **`/gld sprint daily`**. Never route it to `/gld dev` — that develops the container.

The harness row matters: `guild:harness` is not a stage (Section A), so the derivation returns `"none"` for an Issue carrying it alone — meaning the gap has been filed but no spine stage has begun. Render `harness remediation — not started` and say what to run next: **`/gld dev <n>` to start it** (dev's Phase 1 adds `guild:analyze` and it proceeds as a normal Issue) — the same routing `resume.md` gives it. Once a stage label exists, `stage` is that label and `harness == true` is just a `(harness)` annotation on the title line, exactly like `(child)` below. Without this row a filed remediation Issue renders as a bare "not started", indistinguishable from an Issue Guild has never seen.

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

If `guild:needs-human` is present, show it as a leading line before the stage checklist (do not bury it), e.g.:
```
Issue #123: Add login form
⏸ PAUSED — needs a human decision (see the <!-- guild:needs-human --> comment)
Stage: execute (paused here)
- [x] Analyze: completed
- [x] Design: completed
- [ ] Execute: in progress (paused)
...
```

If the Issue has a `guild:child` label, note it (`(child)`) and, if the body references a parent (`Parent Issue: #<n>`), show `Parent: #<n>`. Likewise annotate `(harness)` when `guild:harness` accompanies a stage label — neither annotation is the stage.

### Split parent (`guild:children`)
The Issue is a split parent when the derived `stage` is `guild:children`. Then render a **children checklist** instead of the single-Issue stage checklist (`_handoff.md` Section I):
1. Discover its children (its own read-only Bash call — substitute the **literal** parent number for `<parent>`; no shell `$1` inside the jq string, per `_bash_rules.md` / `_handoff.md` Section I). The per-child `stage`/`paused` projection is the **list form of `_handoff.md` Section A — canonical stage derivation** (one stage label or `"none"`, plus the additive-pause flag; `guild:child`, which every child carries, is excluded there):
   ```bash
   gh issue list --label guild:child --state all --limit 200 --json number,title,body,labels --jq '[.[] | select((.body // "") | test("Parent Issue: #<parent>([^0-9]|$)"))] | sort_by(.number) | .[] | {number, title, stage: ([.labels[].name] | map(select(startswith("guild:") and . != "guild:child" and . != "guild:needs-human" and . != "guild:harness" and . != "guild:sprint")) | .[0] // "none"), paused: ([.labels[].name] | any(. == "guild:needs-human"))}'
   ```
2. For each child, render its `stage` through the rendering table above (a single label, or `"none"` for a fresh child with no stage yet). Mark `[x]` when the child is `guild:done`. If `paused` is `true`, note it next to that child's line (same additive-pause treatment as the single-Issue checklist above).
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
