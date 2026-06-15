# 06 — Migration Plan

How to roll out the rewrite without breaking existing users, in-flight Issues, or external automation.

---

## 1. Migration strategy: cutover, not gradual

**Decision**: single cutover at v1.0.0, not multi-release gradual migration.

**Rationale**:
- All RETHINK decisions R1-R6 are **KEEP** — no external contract changes. Therefore no need for dual-read shim.
- R7-R10 are internal-only (file moves + new behaviors).
- A multi-release gradual migration adds complexity for zero compat benefit.

**Versioning**: bump to **v1.0.0** to signal major restructure. Current line is 0.x — clean semver bump.

---

## 2. Pre-cutover prep

Before v1.0.0 release commit:

### 2.1 Fix version drift bug (carried over from Phase A)
- `plugin.json` and `marketplace.json` must agree.
- Current: `plugin.json` 0.36.0 vs `marketplace.json` 0.35.0.
- Bring both to v0.37.0 first (sync release) THEN bump to v1.0.0 in the rewrite commit.
- Add CI check or pre-commit hook to enforce version sync.

### 2.2 Snapshot current branch
- Tag last 0.x: `v0.36.0-final` (or whatever the final 0.x is).
- Branch `legacy/0.x` for any backports.

### 2.3 Write Phase C entry doc
- `plugins/sdd-plugin/MIGRATION.md` — what changed for users.

---

## 3. What users see in v1.0.0

### What's identical (zero change)
- All `/sdd <command>` names and arg shapes
- All GitHub labels (`sdd:analyze`, `sdd:design`, ..., `sdd:child`, `sdd:review:deep/shallow`)
- All comment markers (`<!-- sdd:* -->`)
- `.github/.sdd-config` format and `skip-review:` key
- `.github/.sdd-lang` format and language aliases
- Stage outputs (markdown structure inside comments)
- Multilingual parent regex
- Bash heuristic discipline (Section 8 of common-contracts)
- Issue templates (`templates/{en,ko,ja}/`)

### What changes (visible if user looks closely)
- Wall-clock per stage **slightly longer** (serial reviews vs parallel — ~+60s per review round per stage). Trade-off accepted.
- `commands/ai-review-*.md` files moved to `commands/atoms/rubrics/*` (R7). Users who happen to grep the source tree may notice.
- Main Claude Code session uses ~65% less context per Issue. Subjectively: fewer "context approaching limit" warnings during `/sdd auto`.

### Internal-only changes (invisible)
- Stage execution moves from main session to sub-agents.
- Atoms inlined into stage sub-agents.
- TDD step idempotency added (resume is faster).
- `init` transactional rollback added (partial-fail safer).
- empty-$3 + existing-PR auto-handled (no more `gh pr create` errors on re-run).

---

## 4. In-flight Issue compatibility

Users may have Issues currently mid-pipeline when v1.0.0 ships (e.g. `sdd:design` label, design output comment present, no PR yet).

### Read compatibility
- All existing markers readable by v1.0.0 atoms (same pattern, exact-match including ` -->`).
- All existing JSON schema blocks parseable (schema unchanged, optional `schema_version` field omitted = treat as v1).
- All existing labels recognized.

### Write compatibility
- v1.0.0 writes the same markers and JSON shape.
- An Issue that had analyze:output written by 0.36 then design:output written by 1.0.0 looks identical to one written entirely by 1.0.0.

### No special migration step needed
Users do NOT need to run any migration command. Existing Issues will continue from where they are when v1.0.0 is installed.

[VERIFIED — by design]: R1-R6 KEEP decisions guarantee this.

---

## 5. R7 migration: `commands/ai-review-*.md` → `commands/atoms/rubrics/*`

### Step 1: Add new location
- Create `commands/atoms/rubrics/` directory.
- Copy all 14 files: `commands/ai-review-<stage>-<role>.md` → `commands/atoms/rubrics/<stage>-<role>.md` (drop "ai-review-" prefix since the location now disambiguates).
- File contents unchanged.

### Step 2: Update atom references
- Each reviewer atom in current `commands/atoms/*_review.md` and `*_adversarial.md` reads a rubric. References change from:
  ```
  <<SKILL_DIR>>/commands/ai-review-<stage>-<role>.md
  ```
  to:
  ```
  <<SKILL_DIR>>/commands/atoms/rubrics/<stage>-<role>.md
  ```

### Step 3: Remove old location
- Delete `commands/ai-review-*.md` (14 files).

### Step 4: Audit
- `grep -r "ai-review-" plugins/sdd-plugin/skills/sdd/` should return empty post-cutover.
- `grep -r "atoms/rubrics" plugins/sdd-plugin/skills/sdd/` should show every reviewer's reference.

[NEW]: this is a one-shot move during the cutover. No shim needed since rubric files are not user-facing.

---

## 6. R8 migration: empty-$3 + existing-PR auto-routing

### Old behavior
- `/sdd implement <N>` after a PR already exists → `gh pr create` errors.
- User must run `/sdd resume <N>` (which dispatches to implement.md's retry path).

### New behavior
- `/sdd implement <N>` checks for existing branch + PR at stage_implement Phase 1.
- If found: log "Existing PR detected — routing to retry mode", skip to Phase 5 (PR Final review).

### Backward compat
- If user had been running `/sdd implement <N>` and getting the `gh pr create` error: now it succeeds.
- If user was running `/sdd resume <N>`: still works identically.

[NEW]: pure improvement; no breaking change.

---

## 7. R9 migration: TDD step idempotency

### Old behavior
- Re-running implement after partial completion re-runs all 4 TDD steps.

### New behavior
- Each step atom checks for its commit at start (via marker `<!-- sdd:tdd:step-N -->` in commit body).
- If found: return `OK <STEP> COMMIT: <existing-sha>` with no work done.

### Adding step markers to commit messages
- New commits made by v1.0.0 atoms will include `<!-- sdd:tdd:step-N -->` in the commit body.
- Old commits (made by 0.x) won't have the marker — re-running on those will re-run the step (current behavior).

### Edge case
- An Issue that had partial 0.x commits and is finished by 1.0.0: 1.0.0 atoms will re-run those steps. Wasteful but correct.
- Mitigation: a one-time `/sdd retroactive-mark <N>` command (proposed for Phase C) — operator runs once after upgrade to backfill markers for the most recent 0.x branches. Optional.

[NEW]: pure improvement; old commits remain functional, just less optimal.

---

## 8. R10 migration: `init` transactional rollback

### Old behavior
- `/sdd init` runs 8 `gh label create` calls in sequence. Partial failure leaves repo half-configured.

### New behavior
- Tracks successful creates. On any failure: delete the successes, report error.

### Backward compat
- Re-running `/sdd init` on a repo that already has all labels: `--force` overwrites; idempotent (current behavior preserved).
- Re-running on a repo with PARTIAL labels (from a failed 0.x init): v1.0.0 init creates the missing labels (since `--force` on existing succeeds), no rollback triggered. Net: heals the partial state.

[NEW]: pure improvement; both fresh-repo and partial-repo cases improved.

---

## 9. Sub-agent context migration (no user impact)

### From orchestrator-in-main-session → stage-sub-agent
- Per-Issue main session token: ~19,715 → ~2,610 (≈ 87% drop).
- Sub-agent context: similar to current (atoms cold-boot ~2,000 tokens each, stage cold-boot ~6,500 tokens). Net total unchanged.

### User-visible side effects
- `/sdd auto` runs longer Issue queues without context-pressure compaction.
- `/sdd <stage>` wall-clock slightly longer (serial reviews) — single-Issue trade-off.

---

## 10. Risk mitigations

| Risk | Mitigation |
|---|---|
| Stage sub-agent times out (long stage_implement) | Standard Claude Code timeout applies. If hit, stage halts; main session sees no return; user restarts via `/sdd resume`. Existing markers preserve state. |
| Sub-agent hallucinates wrong return keyword | Main session validates against whitelist (per design/01-sub-agent-contract.md §9). Unknown → FAIL stop. |
| Skill invocation fails inside sub-agent | Graceful skip pattern preserved (tools-summary marker records skip reason). |
| Rubric file path typo in sub-agent | Caught at first stage invocation (sub-agent fails to read rubric). Fix is single-file edit. |
| Inlined logic diverges from original atom across multiple stages | Mitigation: spec/stage/*.md remains the canonical contract. Each stage_X.md design lists which atom logic it inlines verbatim. Phase C should preserve the line-by-line equivalence where possible. |

---

## 11. Rollback plan (post-v1.0.0)

If v1.0.0 ships with a critical regression:

### Option A: re-tag 0.36.x as marketplace HEAD
- `marketplace.json` points to `legacy/0.x` branch HEAD.
- Users re-install or auto-update back to 0.36.x.

### Option B: hotfix v1.0.1
- Most issues are likely inside a single stage_X.md — patch and release.
- Stage isolation makes this easier than the current monolithic orchestrators.

### Option C: cherry-pick v1.0.0 changes onto 0.x
- Most v1.0.0 changes are architectural and not cherry-pickable.
- Reserve for very specific bug fixes (e.g. R8 / R9 / R10 behaviors).

---

## 12. Validation checklist (pre-release)

- [ ] All 14 rubric files moved + renamed; old paths deleted.
- [ ] `grep -r "ai-review-" plugins/sdd-plugin/skills/sdd/` returns empty.
- [ ] `plugin.json` + `marketplace.json` versions match (1.0.0).
- [ ] Pre-commit hook or CI check for version sync added.
- [ ] Each stage_X.md exists and follows the §1-§N structure from design/stage-designs/.
- [ ] Each stage_X.md inlines the corresponding work + reviewer atom logic.
- [ ] Bootstrap atom file exists and replaces resume.md inline dispatch.
- [ ] Main session FSM (auto.md body) updated per design/03-flow-design.md.
- [ ] R8/R9/R10 behavior present in stage_implement / init.md.
- [ ] Sample Issue manually walked end-to-end (analyze → design → implement → test → done).
- [ ] In-flight test: Issue in `sdd:implement` from 0.x version completes correctly on 1.0.0.
- [ ] `/sdd auto` with N=2 Issues runs to completion.
- [ ] `/sdd batch` with N=2 Issues runs to completion (subprocess mode).

---

## Cross-references

- 10 RETHINK decisions: `05-rethink-decisions.md`
- File layout: `02-file-layout.md`
- Implementation order: `07-implementation-plan.md`
- Spec acceptance contracts: `spec/`
