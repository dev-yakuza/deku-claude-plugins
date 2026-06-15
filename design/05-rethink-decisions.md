# 05 — RETHINK Decisions

Resolution of all 10 RETHINK items deferred from Phase A. All decisions were user-confirmed before Phase B design work began.

---

## Decision summary

| # | RETHINK item | Decision | Impact |
|---|---|---|---|
| R1 | Round-aware markers (`:r1/:r2/:r3` suffix) | **KEEP CURRENT** (in-place overwrite) | No marker change |
| R2 | `skip-review:` → `skip-confirm:` rename | **KEEP CURRENT** (document semantics in README) | No config break |
| R3 | `pr`/`qa` keys → `pr-final`/`implement-final` | **KEEP CURRENT** | No config break |
| R4 | Marker namespace unification (`sdd/stage/artifact`) | **KEEP CURRENT** | No marker break |
| R5 | `>>> RESULT <<<` JSON migration | **KEEP CURRENT** (sentinel + string keywords) | No parser break |
| R6 | Adversarial-only FAIL → warning vs retry | **KEEP CURRENT** (log + retry) | No behavior change |
| R7 | `ai-review-*.md` location → `atoms/rubrics/` | **CHANGE** (move + rename) | Internal-only |
| R8 | empty-$3 + existing-PR handling | **NEW behavior** (auto-route to retry-like) | Improvement |
| R9 | TDD step idempotency (resume skip) | **NEW behavior** (skip already-done steps) | Improvement |
| R10 | `/sdd init` transactional rollback | **NEW behavior** (undo on partial fail) | Improvement |

**6 "KEEP" + 4 changes**. The 6 KEEPs mean **zero breaking changes** for users with existing Issues, configs, labels, markers, automation. The 4 changes are all internal (R7) or additive (R8, R9, R10) — defensive improvements.

---

## Detailed rationale

### R1: Round-aware markers — KEEP CURRENT

**What it is**: Current architecture overwrites `<!-- sdd:review:analyze:completeness -->` in place each round. Round number is inside the embedded JSON (`"round": N`), but the comment body is rotated.

**Alternative considered**: Append `:r{N}` suffix (`<!-- sdd:review:analyze:completeness:r2 -->`) for audit.

**Decision rationale**:
- Comment count would explode for retry-heavy stages (3 rounds × N retries = many comments).
- The JSON `round` field already preserves round info for the latest comment.
- Audit can be done separately (e.g. a `<!-- sdd:audit:trail -->` append-only comment if ever needed).
- Migration cost (every retry-mode self-fetch needs round-aware matching logic) outweighs benefit.

**Impact on Phase C**: zero. Current marker behavior preserved.

---

### R2: `skip-review:` → `skip-confirm:` rename — KEEP CURRENT

**What it is**: The config key `skip-review:` in `.github/.sdd-config` is misleading — it skips the user-confirmation gate, not the AI review loop. AI review always runs.

**Alternative considered**: Rename to `skip-confirm:` with dual-read shim 1+ release.

**Decision rationale**:
- Users have existing `.sdd-config` files with `skip-review:` key.
- README + command docs already explain the semantic. Better docs > breaking change.
- The cognitive load of "skip-review skips confirmation not review" is a documentation problem, not a naming problem.

**Impact on Phase C**: zero. Key name preserved. README/help text should reinforce the semantic.

---

### R3: `pr`/`qa` keys → `pr-final`/`implement-final` — KEEP CURRENT

**What it is**: Two of the five skip-review values are phase labels (`pr`, `qa`) while the others are stage labels (`analyze`, `design`, `implement`).

**Alternative considered**: Rename `pr` → `pr-final`, `qa` → `implement-final` with dual-read shim.

**Decision rationale**:
- Same as R2 — config key names are user-typed tokens.
- The inconsistency is documentation-resolvable.

**Impact on Phase C**: zero.

---

### R4: Marker namespace unification — KEEP CURRENT

**What it is**: Marker grammar is inconsistent (`sdd:analyze:output` vs `sdd:review:analyze:completeness` vs `sdd:test-evidence:step-1`).

**Alternative considered**: Unify to `<!-- sdd/<stage>/<artifact>[/<modifier>] -->` with dual-read shim.

**Decision rationale**:
- External scripts (user automation, log aggregators, audit tools) may parse these markers.
- Even with shim, downstream consumers (CI dashboards, search filters) likely hard-code current pattern.
- "Internal consistency" benefit doesn't outweigh user-automation risk.

**Impact on Phase C**: zero. Marker strings preserved exactly.

---

### R5: `>>> RESULT <<<` JSON migration — KEEP CURRENT

**What it is**: Atom return lines mix sentinel + string keywords (`OK PR: #42 E2E_SKIPPED`, etc.). Parsing is regex/grep-style.

**Alternative considered**: `>>> RESULT <<<\n{JSON}` after the sentinel — structured, deterministic parse.

**Decision rationale**:
- Stage sub-agent returns are also parsed by main session FSM (in Arch B). Adding JSON requires both sub-agent generators AND main session parsers migrated atomically.
- Current strings are human-readable in logs.
- The orchestrator-side parser is small (~20 lines of regex/string-splitting per stage); adding a JSON layer doubles parser complexity for minimal correctness gain.

**Impact on Phase C**: zero. Format preserved per design/01-sub-agent-contract.md.

---

### R6: Adversarial-only FAIL handling — KEEP CURRENT

**What it is**: When 2 reviewers PASS but adversarial alone FAILs, the round is treated as FAIL (full retry). The orchestrator also logs a warning "Adversarial reviewer alone identified critical/major issues."

**Alternative considered**: Treat as warning-only PASS (proceed); user-configurable behavior.

**Decision rationale**:
- Over-retry is safer than over-ship. An adversarial reviewer finding critical/major issues that other reviewers miss is a high-signal event.
- "Surface dissent prominently" is the design intent of having an adversarial reviewer.
- User-configurable would add a new config key — more surface, less determinism.

**Impact on Phase C**: zero.

---

### R7: `ai-review-*.md` → `atoms/rubrics/` — CHANGE

**What it is**: 14 rubric files live in `commands/` alongside user-invocable orchestrators, despite being neither.

**Decision**: Move to `commands/atoms/rubrics/` + rename:
- `commands/ai-review-analyze-completeness.md` → `commands/atoms/rubrics/analyze-completeness.md`
- (same pattern for all 14 files)

**Decision rationale**:
- They are read by reviewer atoms, not by users or orchestrators directly.
- `commands/` should contain user-invocable commands only.
- No external impact: no user types `/sdd ai-review-*`.

**Impact on Phase C**:
- 14 file moves.
- Atom-side reference updates (each reviewer atom reads `<<SKILL_DIR>>/commands/atoms/rubrics/<stage>-<role>.md`).
- `grep -r "ai-review-" plugins/sdd-plugin/skills/sdd/` audit before/after to confirm zero stragglers.

---

### R8: empty-$3 + existing-PR handling — NEW

**What it is**: Currently `implement_pr` atom requires `$3 = "retry"` to handle an existing PR. If `$3` is empty AND a PR already exists for the branch (e.g. user re-ran `/sdd implement` after manual fixes), `gh pr create` errors.

**Decision**: Auto-detect at plan time. If branch + open PR exist for this Issue:
- Route to retry-like mode (skip first-round PR creation).
- Inform user via main-session log.

**Implementation note** (for Phase C):
- In stage_implement Phase 1 (Determine Issue type): also check `gh pr list --search "Refs #$1" --state open`.
- If found: skip Phase 2 (Plan) → jump to Phase 5 (PR Final review).
- This change lives inside `stage_implement.md` per design/stage-designs/implement.md §11.3.

**Impact on Phase C**: ~30 lines in stage_implement.md.

---

### R9: TDD step idempotency — NEW

**What it is**: Currently re-running implement (after partial fix, after interruption) re-runs all 4 TDD steps. If `red` and `green` are already committed, re-running them is wasted work.

**Decision**: At each step atom start, check `git log` for the expected step commit:
- Conventional commit prefix: `test:` for red, `feat:` for green, `refactor:` for refactor, `test:` (E2E suffix) for e2e
- Step-specific marker (commit body has `<!-- sdd:tdd:step-1 -->`-style marker added during rewrite)
- If commit exists with matching marker → return OK with cached sha, skip the work.

**Implementation note** (for Phase C):
- Add commit marker to each step's commit body during rewrite.
- Add idempotency check at top of each step atom.
- See design/stage-designs/implement.md §14.

**Impact on Phase C**: ~50 lines spread across 4 step atoms + commit message template updates.

---

### R10: `/sdd init` transactional rollback — NEW

**What it is**: Currently `/sdd init` runs `gh label create ... --force` for 8 labels. If 5 succeed and the 6th fails (e.g. rate limit, auth issue), the repo is left in a half-configured state.

**Decision**: Wrap label creation in transactional pattern:
- Track each successful `gh label create` call.
- On any failure: iterate the success list, run `gh label delete <name>` for each, then exit with clear error.
- If all 8 succeed: proceed normally.

**Implementation note** (for Phase C):
- New `init.md` orchestrator includes the rollback loop.
- Per design/04-utilities-design.md §1.

**Impact on Phase C**: ~20 lines in init.md.

---

## R7-R10 summary table

| # | New file(s) | Modified file(s) | Lines added |
|---|---|---|---|
| R7 | `commands/atoms/rubrics/*` (14 files moved) | reviewer atom md files (path references) | ~0 net (moves) |
| R8 | — | `commands/atoms/stage_implement.md` (new file) | ~30 |
| R9 | — | `commands/atoms/stage_implement.md` (new file) | ~50 |
| R10 | — | `commands/init.md` (rewritten) | ~20 |
| **Total** | 0 net new files (14 moved) | ~3 new architecture files affected | **~100 lines added** |

[NEW]: behavior additions are small. The main rewrite cost is the architectural restructure (stage-as-subagent), not the R7-R10 changes.

---

## Open RETHINK items deferred to Phase C / later

Some Tier 2/3 items from Phase A spec review are tagged [RETHINK] but not in the R1-R10 set:

- **TAG-C32 / spec/00-common-contracts.md §4 RETHINK on round-suffixed markers**: same as R1, resolved as KEEP.
- **TAG-C33 / spec/stage/analyze.md adversarial-only FAIL**: same as R6, resolved as KEEP.
- **TAG-C30 / sandbox toggle UX (~190 lines)**: not in R1-R10. UX cleanup deferred to Phase C if time permits; behavior unchanged either way.
- **TAG-C31 / ai-review-*.md inlining**: distinct from R7. R7 moves files; inlining would merge rubrics into reviewer atoms. Deferred.
- **TAG-C17/C18 / no-idempotency on TDD steps**: subsumed by R9.

[RETHINK — for Phase C judgment calls]: when implementing, decide whether to inline rubrics (TAG-C31) or keep them as separate files (current). The decision can be local to each stage_X.md.

---

## Cross-references

- Phase A close-out: `spec/SYNTHESIS-v2.md`
- Migration plan: `06-migration-plan.md` (how to apply R7-R10 incrementally)
- Implementation plan: `07-implementation-plan.md` (Phase C order)
