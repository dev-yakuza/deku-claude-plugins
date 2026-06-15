# 04 — Utilities Design

Design for non-stage commands: `init`, `config`, `status`, `rollback`, `review`, `help`. These sit outside the `analyze → design → implement → test` pipeline. They configure the repo, inspect state, re-run reviews, or revert progress.

All utilities run in the **main session** as one-shot command files (`commands/<name>.md`). They do NOT spawn `stage_<X>` sub-agents — they are too small or too interactive to justify the sub-agent envelope cost. (Exception: `/sdd rollback`'s target-stage re-execution spawns the normal stage sub-agent at the end.)

Cross-references:
- Spec: `spec/utilities.md` (acceptance), `spec/01-config.md` (config keys), `spec/02-multilingual.md` (lang aliases), `spec/commands-inventory.md` (routing), `spec/edge-cases.md` §20 (version sync).
- Architecture: `design/00-architecture.md` §1 (main session role), `design/02-file-layout.md` (paths).
- RETHINK decisions: R2 (skip-review key preserved), R10 (init transactional rollback).

---

## 1. `/sdd init [lang]`

**File**: `commands/init.md`. Runs in main session (one-shot — no review loop).
**Spec source**: `spec/utilities.md` §1.

### Behavior (preserved)
1. Resolve language alias (`korean`/`한국어` → `ko`, `japanese`/`日本語` → `ja`, `english`/empty → `en`).
2. Copy `templates/<lang>/issue_*.yml` into `.github/ISSUE_TEMPLATE/` (overwrite, no backup).
3. Save resolved 2-letter code to `.github/.sdd-lang`.
4. Create 8 labels idempotently via `gh label create ... --force` per `spec/01-config.md` §6.
5. Report templates copied, lang code, label summary.

### NEW (R10) — Transactional rollback on label failure

Spec §1 RETHINK: *"`gh label create` fails per-label; no transactional rollback ... partial label set leaves the repo half-configured."* R10 implements transactional rollback.

#### Design

Label creation becomes a tracked sequence. Pseudocode (executed by main-session reasoning between per-label Bash calls):

```
created_labels = []
for label in LABELS:
    Bash: gh label create <name> --color <hex> --description <text> --force
    if exit code 0:
        append name to created_labels
    else:
        for name in reverse(created_labels):
            Bash: gh label delete <name> --yes
        report FAIL with offending label + gh stderr
        exit
report OK with full label list
```

One Bash call per label (8 + N for rollback). The main session cannot use `&&` / `set -e` per Common Contracts §8 — branching happens in the model's reasoning loop between calls.

#### Outcomes

| Outcome | Trigger | Message |
|---|---|---|
| `OK` | All 8 succeed (or pre-exist via --force) | `Labels: 8/8 OK. Templates: <N> copied. Language: <code>.` |
| `FAIL: rolled-back` | Label N fails; prior N-1 successfully deleted | `FAIL: '<name>' (<stderr>). Rolled back: <list>. Repo unchanged.` |
| `FAIL: partial` | Label N fails AND a rollback delete also fails | `FAIL: '<name>' (<stderr>). Rollback partial — these remain: <list>. Manual cleanup: gh label delete <each>.` |

#### Edge cases preserved
Idempotent re-run on initialized repo: `--force` succeeds silently on existing labels; rollback path never triggers (same observable behavior as today). Template-copy failures are NOT transactional (filesystem writes are local/idempotent — out of scope for R10). [PRESERVE]: rollback only triggers on hard `gh` errors (auth, network, repo) — NOT when `--force` updates an existing label's color.

---

## 2. `/sdd config [--skip-review=...]`

**File**: `commands/config.md`. Runs in main session.
**Spec source**: `spec/utilities.md` §2.

### Behavior (unchanged)

| Input | Mode | Action |
|---|---|---|
| (none) | Show | Read `.github/.sdd-config`, render banner + legend |
| `--skip-review=<csv>` | Set | Validate values; rewrite `skip-review:` line; other lines preserved |
| `--skip-review=` (empty) | Reset | Remove `skip-review:` line; delete file if it was the only key |

### Key preservation (R2)

The `skip-review:` literal key is **preserved verbatim** — the `skip-confirm:` rename floated in `spec/edge-cases.md` §8 is deferred (requires dual-read shim + user migration). Backward compatibility with users' existing `.github/.sdd-config` files is load-bearing.

Allowed values (preserved verbatim per `spec/01-config.md` §2): `analyze`, `design`, `implement`, `pr`, `qa`. (The `implement → plan` rename floated in spec is also deferred.)

### Implementation notes
- Argument parsing is ad-hoc string matching (spec IMPROVE not addressed — no other utility has flags, consistency surface is small).
- Set mode validates each csv token against the allowed set before any write. Invalid value → report offending token + allowed list, no file write.
- Reset mode: if removing `skip-review` empties the file, delete it (spec §2 step 2).
- Writes via Write tool; never compound-edits.

### State mutations
Writes / deletes `.github/.sdd-config` only. Never touches `.sdd-lang`, labels, Issue state, or sandbox settings.

---

## 3. `/sdd status [issue]`

**File**: `commands/status.md`. Runs in main session.
**Spec source**: `spec/utilities.md` §3 ([IMPROVE]: unify renderer).

### Behavior

Read-only inspection. Validates Issue per Common Contracts §10 (PR → stop). Never posts comments or sets labels.

### Unified renderer (IMPROVE addressed)

Spec §3: *"single Issue and parent Issue use different output schemas. Consider a unified renderer with parent block as an optional section."* This design adopts a single render function with a conditional Children section.

#### Schema

```
render_status(data):
    out  = "Issue #{n}: {title}{ (Parent) if is_parent}"
    out += "Stage: {stage_from_label}"
    out += render_checklist(data.markers, data.label)   # always 4 lines
    if data.is_parent:                                   # conditional
        out += render_children_block(data.children)
    return out
```

Checklist: 4 lines (Analyze/Design/Implement/Test), each `completed` / `in progress` / `not started`. Children block: "Children:" header + per-child line + progress summary.

#### Outputs

**Single Issue**:
```
Issue #123: Add login form
Stage: implement
- [x] Analyze: completed
- [x] Design: completed
- [ ] Implement: in progress
- [ ] Test: not started
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
```

The Children block is appended **only** when the parent marker is present.

#### Data collection
1. `gh issue view $1 --json labels,title,comments` — single call gathers everything needed for the parent decision + checklist.
2. Scan comments for the 5 stage-output markers (spec §3).
3. If parent marker present, extract child numbers from the table and run `gh issue view <N> --json labels,title` per child (one Bash call each — no compounding).

#### Stage derivation

| Label | `Stage:` |
|---|---|
| `sdd:analyze` | `analyze` |
| `sdd:design` | `design` |
| `sdd:implement` | `implement` |
| `sdd:test` | `test` |
| `sdd:done` | `done` |
| (none) | `not started` |

#### Checklist row rules

| Row | `completed` | `in progress` | else |
|---|---|---|---|
| Analyze | output marker present AND label ≥ design | label == `analyze` | not started |
| Design | output or children marker present AND label ≥ implement | label == `design` | not started |
| Implement | plan marker present AND label ≥ test (or PR merged) | label == `implement` | not started |
| Test | test output present AND label == done | label == `test` | not started |

[PRESERVE]: read-only contract. Label/marker mismatches reported as-is (no reconciliation) — spec §3 IMPROVE about flagging inconsistencies is deferred to keep read-only invariant.

---

## 4. `/sdd rollback <issue> <target-stage>`

**File**: `commands/rollback.md`. Runs in main session.
**Spec source**: `spec/utilities.md` §4.

### Behavior (unchanged)

1. Validate Issue per Common Contracts §10.
2. Validate `$2` ∈ `{analyze, design, implement}` (test/done forbidden).
3. Read current label; reject if target at or after current.
4. Display confirmation block (current → target, retention notice).
5. Wait for user via AskUserQuestion (Continue / Cancel).
6. On Continue:
   a. Remove `sdd:<current>`, add `sdd:<target>`.
   b. Post NEW `<!-- sdd:rollback -->` comment via temp file (`/tmp/sdd-rollback-$1.md`).
   c. Spawn `stage_<target>` sub-agent (Arch B) for inline re-execution.

### Marker accumulation (PRESERVE)

`<!-- sdd:rollback -->` is the **only** SDD marker that intentionally allows duplicates per Common Contracts §4. Each rollback creates a NEW comment with NO duplicate-prevention search — this is the per-event audit trail.

`commands/rollback.md` explicitly instructs the main session to **bypass** Section F's marker-existence search and always call `gh issue comment $1 --body-file /tmp/sdd-rollback-$1.md` to create.

### Inline target-stage execution (Arch B alignment)

Current architecture reads `<<SKILL_DIR>>/commands/$2.md` inline. In Arch B, the equivalent is spawning the normal `stage_<target>` sub-agent from `commands/rollback.md` (which itself runs in main session, so no nested-spawn violation):

```
After label transition + rollback comment:
  spawn stage_<target> with prompt:
    Issue #<N>; Depth: <from label>; Retry context: empty
  receive >>> RESULT <<<
  update FSM; cascade per skip-review if applicable
```

### Parent Issue handling (preserved)

Rolling back a parent to `design` does NOT delete child Issues. Emit warning before stage spawn:

```
Existing child Issues (#124, #125, ...) were created from the previous design.
Review and close them manually if the new design changes scope.
```

[Spec §4 RETHINK]: `--close-children` flag deferred.

### Edge cases preserved
Target == current → no-op (no comment, no state change). Target ahead of current → error. Target ∈ {test, done} → rejected.

---

## 5. `/sdd review <issue>`

**File**: `commands/review.md`. Runs in main session.
**Spec source**: `spec/utilities.md` §6 ([IMPROVE]: adversarial asymmetry).

### Current behavior (preserved)

1. Validate Issue per Common Contracts §10.
2. Detect Parent (has `<!-- sdd:children:output -->`) vs Standard.
3. **Standard path**: detect latest stage via marker precedence (`test:output` > `implement:plan` > `design:output` > `analyze:output`); for `implement` require open PR matching `Refs #$1`. Read role rubric from `atoms/rubrics/<stage>-<role>.md`. Run **2 reviewers serially in main session**: completeness, then quality. Post/PATCH `<!-- sdd:review:<stage>:<role> -->` per Section F. Report verdict.
4. **Parent path**: aggregate synthesis (no rubric atoms); post `<!-- sdd:review:parent -->`.

Reviewers run inline in main session (no sub-agent) since `/sdd review` is a read-side one-shot — sub-agent envelope cost not justified for 2 review passes.

### IMPROVE addressed: `--deep` flag for opt-in adversarial

Spec §6: *"The source omits adversarial for cost reasons ... Document this asymmetry explicitly."* Design adds an opt-in flag rather than always-on adversarial.

| Invocation | Reviewers |
|---|---|
| `/sdd review <issue>` | completeness + quality (default, unchanged) |
| `/sdd review <issue> --deep` | completeness + quality + **adversarial** |

#### Rationale
- Adversarial uses opus → cost-sensitive. Most re-review uses are quick second looks.
- `--deep` users have explicit intent to pay for the heavy reviewer.
- Backward-compatible default (existing scripts unaffected).

#### Implementation

`commands/review.md` parses `--deep` token from `$2`. When present:
- **Standard**: read `atoms/rubrics/<stage>-adversarial.md`; run a third reviewer serially after the first two. Post under `<!-- sdd:review:<stage>:adversarial -->`.
- **Parent**: `--deep` adds a second synthesis pass focused on cross-cutting risks; same `<!-- sdd:review:parent -->` marker (update-in-place).

#### Adversarial-only FAIL

Same convention as per-stage orchestrators (spec/edge-cases.md §19): completeness + quality PASS but adversarial FAIL → surface warning prominently; overall verdict = FAIL.

### Invariants preserved
- Never re-spawns the work atom (read-side only).
- Never advances labels.
- Never auto-proceeds to next stage.
- Single pass — no retry loop.
- Read-only-vis-à-vis-labels contract is what makes `/sdd review` safe to invoke any time.

### Edge cases preserved
Misset parent marker → Parent path (load-bearing). Implement stage but no open PR → error. Re-running overwrites prior review comments (Section F update-in-place; spec §6 RETHINK on round audit deferred).

---

## 6. `/sdd help`

**File**: `commands/help.md`. Runs in main session.
**Spec source**: `spec/utilities.md` §5 ([IMPROVE]: registry-generated).

### IMPROVE addressed: command registry

Spec §5: *"help text is duplicated information from individual `.md` files. Drift risk ... Rewrite candidate: generate help from a structured command registry."*

#### Registry source

Canonical: `spec/commands-inventory.md` §1 (the Command Table). Runtime: `<<SKILL_DIR>>/commands/_registry.md` — a small file that contains the rendered subset of the Command Table needed for help output. (Spec lives in design/spec repo only; not shipped at runtime, so `_registry.md` is the runtime single-source-of-truth.)

Generation: `_registry.md` is produced (manually or via release script) from `spec/commands-inventory.md` §1. A pre-release CI check validates the two stay in sync.

#### help.md as renderer

`commands/help.md` instructs the main session to:
1. Read `<<SKILL_DIR>>/commands/_registry.md`.
2. Render commands in groups:
   - **Setup**: `init`, `config`
   - **Pipeline**: `analyze`, `design`, `implement`, `test`
   - **Workflow**: `resume`, `rollback`, `auto`, `batch`
   - **Inspect**: `status`, `review`
   - **Meta**: `help`
3. Append the Tips section (preserved verbatim from current `help.md`).
4. Append the Workflow Overview (preserved verbatim).

Each command row shows: name + arg shape + one-line purpose. Read-only commands tagged `(read-only)`.

#### Routing fallback (unchanged)
- `/sdd` (no args) → routes to help.
- `/sdd <unknown>` → reports `unknown command`, then routes to help.

Both go through the same renderer.

#### What stays
- Plain text output (no terminal styling).
- Tips section content — 8 topics per spec §5.
- Workflow Overview sequence (`init → analyze → design → implement → test`).

---

## 7. Plugin metadata

### Version bump

| File | Pre | Post |
|---|---|---|
| `plugins/sdd-plugin/.claude-plugin/plugin.json` | 0.36.0 | **1.0.0** |
| `.claude-plugin/marketplace.json` | 0.35.0 (drifted) | **1.0.0** |

Major bump (0.x → 1.0) signals the structural rewrite (Arch B). Per semver this is appropriate: behavior contracts preserved but file layout and orchestration model changed.

### Version sync — pre-release CI check

Spec `edge-cases.md` §20 documented an active drift: `plugin.json` is 0.36.0, `marketplace.json` is 0.35.0. The v1.0.0 release MUST fix this in the same commit, and a CI check prevents future drift.

#### Proposed CI workflow (`.github/workflows/version-sync.yml`)

```
plugin_v   = jq -r .version plugins/sdd-plugin/.claude-plugin/plugin.json
market_v   = jq -r '.plugins[] | select(.name=="sdd-plugin") | .version' .claude-plugin/marketplace.json
[[ "$plugin_v" == "$market_v" ]] || fail with diff message
```

CI workflow chosen over pre-commit hook (not enforceable across contributors) and over a manual release checklist (the failure mode that produced the current drift).

### Plugin.json fields (preserved)

`name`, `description`, `author`, `homepage`, `repository`, `license` — all unchanged. Only `version` changes. No schema additions.

---

## 8. `.github/` files (no change)

| File | Status |
|---|---|
| `.github/.sdd-config` | PRESERVE (format + `skip-review:` key per R2) |
| `.github/.sdd-lang` | PRESERVE (single-line 2-letter code) |
| `.github/ISSUE_TEMPLATE/issue_*.yml` | PRESERVE (per-language, written by `/sdd init`) |
| `.github/.sdd-config.bak` | PRESERVE (created by auto/batch only) |
| `.github/.sdd-batch.sh` / `.sdd-batch-logs/*` | PRESERVE (flow command artifacts) |

None of these are utility-command responsibilities; listed for completeness against `spec/01-config.md` §1.

---

## 9. Permissions matrix (no change)

Per `spec/01-config.md` §7 — the baseline allowlist used by `/sdd auto` and `/sdd batch` Phase 2 is preserved verbatim. Required: `Read`, `Edit`, `Write`, `Bash(gh:*)`, `Bash(git:*)`. Recommended: `Grep`, `Glob`, `Agent`, `WebSearch` (optional). Test-runner detection table (pubspec.yaml → flutter/dart, package.json → npm/npx, pyproject.toml → pytest, etc.) preserved verbatim from spec — see `spec/01-config.md` §7 for the full marker-to-permission mapping.

**Matching rule [PRESERVE]**: exact unscoped match only. `Edit(/path/**)` does NOT satisfy `Edit`. Scoped permissions don't subsume unscoped requirements.

[IMPROVE deferred]: test-runner detection duplicated in `auto.md` and `batch.md`. Owned by flow commands — out of scope for utilities.

---

## 10. Cross-references

| Command | Spec | Architecture / layout |
|---|---|---|
| `/sdd init` | `spec/utilities.md` §1, `spec/02-multilingual.md` §1, `spec/01-config.md` §6 | main session |
| `/sdd config` | `spec/utilities.md` §2, `spec/01-config.md` §2 | main session |
| `/sdd status` | `spec/utilities.md` §3 | main session |
| `/sdd rollback` | `spec/utilities.md` §4, `spec/edge-cases.md` §17 (marker accumulation) | main session + stage spawn (Arch B §3) |
| `/sdd review` | `spec/utilities.md` §6, `spec/edge-cases.md` §19 (adversarial-only FAIL) | main session; uses `atoms/rubrics/` |
| `/sdd help` | `spec/utilities.md` §5, `spec/commands-inventory.md` §1 (registry) | renders from new `commands/_registry.md` |

RETHINK decisions: **R2** (skip-review key preserved — affects `/sdd config`), **R10** (init transactional rollback — new behavior).

Version sync (`spec/edge-cases.md` §20) addressed by CI workflow proposed in §7; both `plugin.json` and `marketplace.json` reach v1.0.0 in the rewrite-release commit.

---

## Summary

| Item | Spec status | This design |
|---|---|---|
| `init` transactional rollback | RETHINK | **R10: implemented** (§1) |
| `config` `skip-review:` key | PRESERVE / RETHINK | **R2: preserved** (§2) |
| `status` unified renderer | IMPROVE | **Implemented** (§3) |
| `rollback` marker accumulation | PRESERVE | **Preserved** (§4) |
| `rollback` `--close-children` | RETHINK | **Deferred** (§4) |
| `review` adversarial asymmetry | IMPROVE | **`--deep` flag added** (§5) |
| `help` registry generation | IMPROVE | **`_registry.md` rendered** (§6) |
| Version sync drift | active bug | **CI workflow** (§7) |
| Permissions matrix | PRESERVE | **Verbatim** (§9) |
| `.github/` files | PRESERVE | **Verbatim** (§8) |
