# Utilities — Setup, Status, Help, Review, Rollback

Acceptance specification for the SDD plugin's utility / non-stage commands. These commands sit outside the linear analyze→design→implement→test pipeline. They configure the repo, inspect state, re-run reviews, or revert stage progress. Sources: `commands/init.md`, `commands/config.md`, `commands/status.md`, `commands/rollback.md`, `commands/help.md`, `commands/review.md`, `SKILL.md`.

---

## 1. `/sdd init [lang]` [PRESERVE]

One-time repository setup. Idempotent: re-running overwrites templates and re-applies labels via `--force`.

### Inputs
- `$1` (optional) — language code. Maps to a template directory:
  - `ko`, `korean`, `한국어` → Korean
  - `ja`, `japanese`, `日本語` → Japanese
  - `en`, `english`, empty / absent → English (default)

[PRESERVE]: the accepted alias surface (`korean`, `한국어`, `japanese`, `日本語`, `english`) is user-typed argument to `/sdd init`. Removing aliases breaks scripts users have written like `/sdd init korean`. Keep the full alias set.
[IMPROVE]: the INTERNAL normalization — saving the 2-letter code (`en`/`ko`/`ja`) to `.sdd-lang` regardless of which alias was passed — is freely refactorable. The IMPROVE applies to dedupe of the alias-handling code, not to the user-visible alias surface. (Was [IMPROVE] in v1; corrected per Reviewer C TAG-C9.)

### Steps
1. **Resolve language** from `$1` to one of `en` / `ko` / `ja`. Select template directory `templates/<lang>/`.
2. **Copy Issue templates**: copy every `templates/<lang>/issue_*.yml` to `.github/ISSUE_TEMPLATE/`. Existing files of the same name are overwritten without backup. (`init.md` line 12)
3. **Save language**: write the resolved code to `.github/.sdd-lang` (single-line text). (`init.md` line 15; format spec in `01-config.md` §5)
4. **Create labels** idempotently via `gh label create ... --force` per the table in `01-config.md` §6:
   - 5 lifecycle labels (`sdd:analyze`, `sdd:design`, `sdd:implement`, `sdd:test`, `sdd:done`)
   - 1 orthogonal child label (`sdd:child`)
   - 2 optional depth dials (`sdd:review:deep`, `sdd:review:shallow`)
5. **Report**: number of templates copied, language saved, count of labels created with note that the two `sdd:review:*` labels are optional per-Issue dials. (`init.md` lines 31–34)

### State mutations
- Files written: `.github/ISSUE_TEMPLATE/issue_*.yml` (per language), `.github/.sdd-lang`.
- Labels created/updated on the current `gh` repo.

### Edge cases
- No language argument → English templates installed; `.sdd-lang` = `en`.
- Re-running with a different language → templates overwritten; `.sdd-lang` updated. Past Issue bodies remain in the previous language (orchestrator stages handle multilingual detection — see `02-multilingual.md`).
- Label color collision with pre-existing non-SDD labels of the same name → `--force` silently updates the color. [IMPROVE: no conflict warning, per `01-config.md` §6 IMPROVE note.]
- No `gh` auth or wrong repo → `gh label create` fails per-label; no transactional rollback. [RETHINK: partial label set leaves the repo in a half-configured state.]

[PRESERVE: idempotency via `--force` is load-bearing for re-running on existing repos.]

---

## 2. `/sdd config [--skip-review=<values>]` [PRESERVE]

Manages `.github/.sdd-config`. Three modes selected by argument shape.

### Argument parsing (per `config.md` lines 8–12)
| Input | Mode |
|---|---|
| No arguments | **Show** current config |
| `--skip-review=<v1>,<v2>,...` | **Set** skip-review |
| `--skip-review=` (empty value) | **Reset** skip-review |

[IMPROVE: parsing is ad-hoc string matching, not a real CLI parser. Other commands have no flags so this inconsistency is invisible today, but introduces drift if new flags are added.]

### Show mode
1. Read `.github/.sdd-config`.
2. File missing → report: `No config set. Using defaults (all reviews enabled).`
3. File present → render in a fixed banner format (per `config.md` lines 19–22) and append the value legend table (per `config.md` lines 24–31), which describes what each skipped value means.

### Set mode
1. Validate each comma-separated value against the allowed set: `analyze`, `design`, `implement`, `pr`, `qa`. (See `01-config.md` §2 for semantics.)
2. Any invalid value → error report with the offending value and the allowed list. No file write.
3. Write `skip-review: <comma-separated values>` to `.github/.sdd-config`. Existing `skip-review` line is replaced; other lines preserved. (`config.md` lines 37–40)
4. Confirm save with a summary of which gates will now be skipped.

### Reset mode
1. Remove the `skip-review` line from `.github/.sdd-config`.
2. If `skip-review` was the only key → delete the file. (`config.md` line 45)
3. Confirm: `skip-review reset. All reviews are now enabled.`

### State mutations
- Writes / deletes `.github/.sdd-config`.
- Never modifies `.sdd-lang`, labels, or any Issue state.

### Edge cases
- File exists but contains an invalid line (manual edit) → show mode displays as-is; set mode parses only `skip-review` and rewrites without touching the rest. [IMPROVE: no robust line-level merge guarantees if other keys are added later.]
- Empty file → behaves like missing file in show mode.
- `--skip-review=qa` alone is valid (single value).

[PRESERVE: format and value semantics are documented in `01-config.md` §2 with the critical invariant that skip-review skips ONLY the user gate, not the AI review loop.]

---

## 3. `/sdd status [issue]` [IMPROVE]

Read-only inspection. Does not modify any GitHub state.

### Inputs
- `$1` — Issue number. **Required** despite the bracket in `help.md` line 15 (which uses `<issue>` and suggests it's required). The status command has no inventory mode. [IMPROVE: argument is mandatory in practice but `help.md` reads ambiguously; the `status.md` source assumes `$1` is always supplied.]

### Validation
Issue Validation per Common Contracts §10. PR input → stop, no state changes.

### Process (per `status.md` lines 8–19)
1. Read labels: `gh issue view $1 --json labels`.
2. Read Issue comments and detect which stage-output markers are present:
   - `<!-- sdd:analyze:output -->`
   - `<!-- sdd:design:output -->`
   - `<!-- sdd:children:output -->` (parent indicator)
   - `<!-- sdd:implement:plan -->`
   - `<!-- sdd:test:output -->`
3. Search related PRs by body convention: `gh pr list --search "Refs #$1"` (matches the body line `implement_pr` atom writes).
4. If `<!-- sdd:children:output -->` present → recurse into each child Issue (read label + same marker scan).
5. Render summary.

### Output formats (per `status.md` lines 21–42)

**Single / child Issue**:
```
Issue #$1: <title>
Stage: <current stage based on label>
- [x] Analyze: completed
- [x] Design: completed
- [ ] Implement: in progress
- [ ] Test: not started
```

**Parent Issue**:
```
Issue #$1: <title> (Parent)
Stage: implement
- [x] Analyze: completed
- [x] Design: completed (3 child Issues created)
- [ ] Implement:
  - #124: <name> → sdd:done ✓
  - #125: <name> → sdd:implement
  - #126: <name> → sdd:analyze
- [ ] Test: not started
```

### Edge cases
- No SDD labels and no markers → stage shown as blank / "not started"; command does NOT auto-init.
- Label and markers disagree (e.g. label `sdd:test` but no `<!-- sdd:implement:plan -->`) → output reflects label as "stage" and marker checks separately; no reconciliation. [RETHINK: should status flag inconsistencies?]
- Parent's children all closed but parent label still `sdd:implement` → status shows children as done but parent stage unchanged; does not auto-advance the parent. (Stage advance is the test-stage parent orchestrator's job.)

[IMPROVE: single Issue and parent Issue use different output schemas. Consider a unified renderer with parent block as an optional section.]

[PRESERVE: read-only contract — `/sdd status` never posts comments or sets labels.]

---

## 4. `/sdd rollback <issue> <target-stage>` [PRESERVE]

Revert an Issue to an earlier lifecycle label and re-execute that stage inline.

### Inputs
- `$1` — Issue number.
- `$2` — target stage: `analyze` | `design` | `implement`. **Cannot** target `test` or `done` (per `rollback.md` line 10).

### Validation
1. Issue Validation per Common Contracts §10. PR input → stop, no state changes.
2. Read current label; determine current stage.
3. Direction check: target must be **strictly earlier** in the linear flow `analyze < design < implement < test < done`.
4. Already at or before target → report and exit (no-op, no comment posted).

### Confirmation flow (per `rollback.md` lines 21–27)
Display to user before proceeding:
```
Rolling back Issue #$1 from <current stage> to <target stage>.
This will:
- Change label from <current> to <target>
- Previous stage outputs in Issue comments will be preserved for reference
```
Wait for user confirmation. [IMPROVE: source does not specify mechanism (AskUserQuestion vs raw prompt) — implicit interactive gate.]

### Process on confirmation
1. **Update labels**: remove current `sdd:<current>`, add `sdd:<target>`. (`rollback.md` line 28)
2. **Post rollback notice** per the mandatory temp-file pattern (Common Contracts §9, `_review_helpers.md` Section F). No duplicate-prevention — every rollback creates a **new** comment, accumulating a history. (`rollback.md` lines 29–42)
   - Marker: `<!-- sdd:rollback -->`
   - Temp file: `/tmp/sdd-rollback-$1.md`
   - Body:
     ```markdown
     <!-- sdd:rollback -->
     **Rolled back** from `<current stage>` to `<target stage>`.
     Reason: <user's reason or "requested by user">
     <!-- /sdd:rollback -->
     ```
   - Post via `gh issue comment $1 --body-file /tmp/sdd-rollback-$1.md`.
3. **Inline-execute target stage**: read `<<SKILL_DIR>>/commands/$2.md` and execute its instructions in the **same main session**. Do NOT spawn a subagent — that would create nested-subagent spawning when the target orchestrator spawns its own atoms (Common Contracts §12). (`rollback.md` line 43)

### Parent Issue handling (per `rollback.md` lines 45–48)
- Rolling back a parent to `design` does **NOT** delete existing child Issues.
- Children remain with their current labels and PRs.
- The orchestrator warns the user: `Existing child Issues (#124, #125, ...) were created from the previous design. Review and close them if the new design changes scope.`
- Closing children is left to manual cleanup.

[RETHINK: this leaves potentially orphaned children if the rolled-back design produces a different decomposition. Consider an optional `--close-children` flag.]

### Child Issue handling
- Treated identically to a single Issue rollback.
- If target is `analyze`, warn the user that the new analysis should remain consistent with the parent's design.

### State mutations
- Issue label transition.
- New `<!-- sdd:rollback -->` comment appended (not updated in place — unique among SDD comment writers).
- Then, inline execution of the target stage produces all the usual stage outputs.

### Edge cases
- Target equals current stage → reported as no-op; no rollback notice posted.
- Target ahead of current stage → reported as error; no state changes.
- Target is `test` or `done` → explicitly rejected; the only "forward" recovery path is `/sdd resume`.

[PRESERVE: marker `<!-- sdd:rollback -->` is the ONLY SDD marker that intentionally allows duplicates per Common Contracts §4 — this is the per-event audit trail.]

[IMPROVE: the inline-execute hop in step 3 means a rollback that fails mid-stage leaves the Issue in the target label but without complete outputs. No transactional guarantee.]

---

## 5. `/sdd help` [PRESERVE]

Static text dump. No state reads, no `gh` calls, no validation.

### Behavior
- Prints the help text block from `help.md` (lines 3–61). Includes the command list, workflow overview, and the Tips section that surfaces non-obvious operational knowledge.

### Routing entry point
- When `/sdd` is invoked with empty `$0`, the routing in `SKILL.md` line 18 maps to `help`. So `/sdd` (no args) and `/sdd help` produce identical output.
- An unknown command (`$0` not in the valid list) also routes to `help` after reporting `unknown command`. (`SKILL.md` line 19)

### Content categories surfaced (informational; not enforcement)
- Command list with arg shapes
- Workflow sequence (init → analyze → design → implement → test)
- Resume hint for interrupted runs
- Tips: pre-flight, design-driven test plan, reviewer lenses, codebase verification, skip-review behavior, depth dials, external tool integration, batch vs auto trade-offs

[IMPROVE: help text is duplicated information from individual `.md` files. Drift risk — if a command file changes, help may go stale. Rewrite candidate: generate help from a structured command registry.]

[PRESERVE: a single static help is fine for the current command set; refactor only if registry-driven docs are introduced.]

---

## 6. `/sdd review <issue>` [PRESERVE]

Re-run AI review on the latest stage output. Does NOT advance labels or auto-proceed — purely a read-side operation that posts fresh review comments. (`review.md` lines 5, 81)

### Inputs
- `$1` — Issue number.

### Validation
- Issue Validation per Common Contracts §10. PR input → stop.

### Process — Standard (single / child Issue)
1. Determine Issue type via `<!-- sdd:children:output -->` marker check. Has marker → Parent Review; otherwise Standard. (`review.md` lines 21–27)
2. **Detect latest stage** by scanning for stage-output markers and applying precedence (`test:output` > `implement:plan` > `design:output` > `analyze:output`). For `implement`, also require an open PR matching `Refs #$1`. (`review.md` lines 31–43)
3. No outputs found → report `No stage outputs to review yet. Run /sdd analyze $1 first.` and stop.
4. Map detected stage to its review atom (`review.md` lines 51–56):
   - `analyze:output` → `analyze_review.md`
   - `design:output` → `design_review.md`
   - `implement:plan` → `implement_review.md`
   - `test:output` → `test_review.md`
5. **Spawn two review atoms in parallel** in a single message — only `completeness` and `quality` roles. Adversarial is NOT re-run by `/sdd review`. [IMPROVE / RETHINK: the source omits adversarial for cost reasons; users who want a deep re-review must run the full stage orchestrator. Document this asymmetry explicitly.]
6. Parse both `>>> RESULT <<<` lines and report:
   - Any `FAIL: <reason>` → atom error, stop.
   - Both `OK PASS` → `Review complete, no critical/major issues.`
   - Either `OK FAIL` → combined severity summaries with pointer to the updated review comments.

### Process — Parent Review (per `review.md` lines 84–130)
Aggregate, not per-stage. Does NOT spawn review atoms — the synthesis runs in the main session.
1. Read child numbers from `<!-- sdd:children:output -->`.
2. For each child: read current label + latest stage-output comment; if in `sdd:implement` or `sdd:test`, also fetch PR status.
3. Generate a summary report posted on the parent Issue under `<!-- sdd:review:parent -->`:
   - Overall progress (completed / in progress / not started counts)
   - Per-child stage + brief assessment
   - Cross-cutting concerns (consistency, shared deps, integration risk) — produced by the main session reading children's design + implementation comments
4. Posted via the mandatory temp-file pattern (Common Contracts §9). Updates existing `<!-- sdd:review:parent -->` if present, else creates new.

### Differences from per-stage orchestrator reviews

| Aspect | Per-stage orchestrator (e.g. `/sdd analyze`) | `/sdd review` |
|---|---|---|
| Re-spawns work atom? | Yes (Round 1 produces fresh output) | No (reads existing output) |
| Reviewers spawned | 3 (completeness, quality, adversarial) | 2 (completeness, quality) |
| Advances label? | Yes on PASS + user gate | Never |
| Auto-proceeds to next stage? | Yes if skip-review set | Never |
| Round retry loop? | Up to 3 rounds | Single pass |
| Parent-Issue aggregate review | Implicit via test stage | Explicit `<!-- sdd:review:parent -->` synthesis |

[PRESERVE: the read-only contract is what makes `/sdd review` safe to invoke at any time.]

### Edge cases
- Single Issue with `<!-- sdd:children:output -->` accidentally set → treated as Parent, runs aggregate path. (Marker is load-bearing.)
- Implement stage but no open PR → `No PR found for the implement stage. Run /sdd implement $1 to create the PR before reviewing.` and stop.
- Re-running `/sdd review` overwrites prior review comments (duplicate-prevention markers). Round-to-round audit history is lost. (Common Contracts §4 update-in-place invariant.)

[RETHINK: re-running review without preserving prior verdict makes "before/after" comparisons impossible from GitHub alone.]

---

## 7. `ai-review-*.md` files — what they are

There are 14 files in `commands/` matching `ai-review-*.md`. Inspecting representative samples (`ai-review-analyze-completeness.md`, `ai-review-implement-step.md`, `ai-review-parent-integration.md`) and the references in `grep -r "ai-review-" commands/`:

### Classification: **role-specific criteria / rubric documents** read by review atoms.

They are NOT orchestrators, NOT atoms, and NOT user-invocable. They are prompt-extension content — each file holds the role-specific evaluation checklist, severity guidance, common failure modes, and (where applicable) `rule_id` list for one (stage × role) pair.

### File-to-atom mapping

| Criteria file | Read by atom | Atom passes role via |
|---|---|---|
| `ai-review-analyze-completeness.md` | `atoms/analyze_review.md` | `$2 = completeness` |
| `ai-review-analyze-quality.md` | `atoms/analyze_review.md` | `$2 = quality` |
| `ai-review-analyze-adversarial.md` | `atoms/analyze_adversarial.md` | role fixed |
| `ai-review-design-completeness.md` | `atoms/design_review.md` | `$2 = completeness` |
| `ai-review-design-quality.md` | `atoms/design_review.md` | `$2 = quality` |
| `ai-review-design-adversarial.md` | `atoms/design_adversarial.md` | role fixed |
| `ai-review-implement-completeness.md` | `atoms/implement_review.md` | `$2 = completeness` |
| `ai-review-implement-quality.md` | `atoms/implement_review.md` | `$2 = quality` |
| `ai-review-implement-adversarial.md` | `atoms/implement_adversarial.md` | role fixed |
| `ai-review-implement-step.md` | `atoms/tdd_step_review.md` | `$2 = step number (1-4)`; file has subsections per step |
| `ai-review-test-completeness.md` | `atoms/test_review.md` | `$2 = completeness` |
| `ai-review-test-quality.md` | `atoms/test_review.md` | `$2 = quality` |
| `ai-review-test-adversarial.md` | `atoms/test_adversarial.md` | role fixed |
| `ai-review-parent-integration.md` | `atoms/parent_integration_review.md` | role fixed |

(14 atom→criteria mappings; the directory has 14 files matching `ai-review-*.md`.)

### Invocation pattern (verified)
Inside the reviewer atom, after Issue Validation and stage-output fetch:
```
Read the role-specific criteria file based on $2:
  - $2=completeness → <<SKILL_DIR>>/commands/ai-review-<stage>-completeness.md
  - $2=quality     → <<SKILL_DIR>>/commands/ai-review-<stage>-quality.md
```
(See `analyze_review.md` lines 28–30, `design_review.md` lines 34–36, `implement_review.md` lines 42–44, `test_review.md` lines 32–34, `tdd_step_review.md` line 40, and the adversarial / parent atoms which hard-code the path.)

### NOT vestigial
Every file is referenced by at least one atom in `commands/atoms/`. Removing any one would break the corresponding reviewer atom's role logic.

### Tagged: [IMPROVE]
- **Location**: `ai-review-*.md` files sit in `commands/` alongside the actual user-invocable orchestrators (`analyze.md`, `design.md`, etc.). This is misleading — they are NOT commands. A naming/placement that signals "rubric, not entry point" would help (e.g. `commands/atoms/rubrics/<stage>-<role>.md` or `commands/criteria/...`).
- **Naming**: the `ai-review-` prefix conflicts visually with the actual `/sdd review` command. A reader scanning the directory cannot tell at a glance whether `ai-review-analyze-completeness.md` is the implementation of `/sdd review` or a sub-asset. (The actual `/sdd review` implementation is `commands/review.md`, with no prefix.)
- **Duplication risk**: rubrics for the same stage but different roles (`completeness` vs `quality`) overlap in coverage of generic SDD principles. Could share a common preamble.

[RETHINK: the rubrics could be inlined into the corresponding reviewer atom files to remove a layer of indirection — but the current split keeps each atom file shorter and lets criteria evolve without touching atom orchestration logic. Trade-off favors split.]

[PRESERVE: the content of each rubric is load-bearing for reviewer quality. Don't touch the criteria themselves — only the location/naming.]
