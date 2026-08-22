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
3. Derive the current **stage** from the `guild:*` label (Section A table below). ⚠ `_handoff.md` Section A's table has **four kinds of row** and an Issue routinely carries more than one `guild:*` label, so pick the stage from the **stage/orchestration** labels only (`guild:analyze`/`design`/`execute`/`test`/`qa`/`done`/`guild:children`) and treat the rest as annotations rendered alongside it: `guild:child` (permanent identity marker — every child carries it *plus* its real stage label), `guild:needs-human` (additive pause), `guild:harness` (provenance — a readiness-gap Issue). Taking "the first `guild:*` label" instead would mis-read a child as having no stage and a not-yet-started harness Issue as `harness`-the-stage. **Also check for `guild:needs-human`** — this label is *additive* on top of the stage label (an unattended run paused mid-stage, `_handoff.md` Section H), so an Issue can simultaneously show e.g. `guild:execute` AND `guild:needs-human`. If present, render it prominently (see the output example) — do not let it hide behind the plain stage line, since `batch`/`monitoring`/`sprint` all treat it as first-class and a human relying on `status` alone should see it too.
4. Scan comments for stage-output markers to build the checklist:
   - `<!-- guild:analyze:output -->`
   - `<!-- guild:design:output -->`
   - `<!-- guild:test-evidence:step-1 -->` (execute produced evidence)
   - `<!-- guild:test:output -->`
   - `<!-- guild:qa:output -->`
5. Find the related PR:
   ```bash
   gh pr list --search "Closes #$1" --json number,url,state
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
| `guild:harness` **and no stage label** | harness remediation — not started |
| (none) | not started |

`guild:harness` is **not a stage** — it marks a harness readiness gap that `init` P3.5 / `/gld audit` filed as a developable Issue. Alone (no `guild:analyze`…`guild:done` alongside), it means the gap has been filed but no spine stage has begun; render the stage as `harness remediation — not started` and say what to run next: **`/gld dev <n>` to start it** (dev's Phase 1 adds `guild:analyze` and it proceeds as a normal Issue) — the same routing `resume.md` gives it. Once a stage label exists, that stage label wins and `guild:harness` is just a `(harness)` annotation on the title line, exactly like `(child)` below. Without this row a filed remediation Issue renders as a bare "not started", indistinguishable from an Issue Guild has never seen.

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
If the Issue is a split parent, render a **children checklist** instead of the single-Issue stage checklist (`_handoff.md` Section I):
1. Discover its children (its own read-only Bash call — substitute the **literal** parent number for `<parent>`; no shell `$1` inside the jq string, per `_bash_rules.md` / `_handoff.md` Section I). ⚠ The `guild:*` filter must exclude `guild:child` (every child carries it, alongside its real stage label — including it in the `stage` field produces a comma-joined string like `"guild:child,guild:execute"` that matches no row of the stage-derivation table, verified against real `jq`) and `guild:needs-human` (additive, not a stage — see below):
   ```bash
   gh issue list --label guild:child --state all --limit 200 --json number,title,body,labels --jq '[.[] | select((.body // "") | test("Parent Issue: #<parent>([^0-9]|$)"))] | sort_by(.number) | .[] | {number, title, stage: ([.labels[].name] | map(select(startswith("guild:") and . != "guild:child" and . != "guild:needs-human")) | .[0] // "none"), paused: ([.labels[].name] | any(. == "guild:needs-human"))}'
   ```
2. For each child, derive its stage from the `stage` field above (matches the derivation table cleanly now — a single label, or `"none"` for a fresh child with no stage yet). Mark `[x]` when the child is `guild:done`. If `paused` is `true`, note it next to that child's line (same additive-pause treatment as the single-Issue checklist above).
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
