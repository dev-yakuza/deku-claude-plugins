# SDD Plugin — v1.0.0 Specification

Current contract and architecture after the Arch B rewrite. This is the single source of truth for what v1.0.0 ships with.

For background:
- `spec/` — original acceptance contract (Phase A, unchanged by rewrite)
- `design/` — architectural blueprint (Phase B)
- `MIGRATION.md` — upgrade notes from 0.x

---

## 1. Architecture overview

```
User invokes /sdd <command> [args]
  │
  ▼
SKILL.md routes to commands/<command>.md
  │
  ▼
Main Claude Code session reads command file
  │
  ▼
Command spawns ONE sub-agent (stage_X or bootstrap)
  │
  ▼
Sub-agent inlines all work + reviews + Skill calls
  │
  ▼
Sub-agent returns >>> RESULT <<< one-liner
  │
  ▼
Main session parses, transitions label, possibly auto-advances
```

Main session is a thin FSM. Each pipeline stage runs as one sub-agent. State lives on GitHub (labels + comment markers), not in-process.

---

## 2. User-facing commands (13)

| Command | Purpose | Source | State changes |
|---|---|---|---|
| `/sdd init [lang]` | Setup repo (labels, templates, .sdd-lang) — R10 transactional rollback | `commands/init.md` (95) | Labels, files |
| `/sdd config [--skip-review=...]` | Manage `.github/.sdd-config` skip-review key | `commands/config.md` (46) | `.sdd-config` |
| `/sdd analyze <issue>` | Stage 1: requirements analysis (What/Why) | `commands/analyze.md` (119) | Labels, comments |
| `/sdd design <issue>` | Stage 2: design (How), may split into children | `commands/design.md` (148) | Labels, comments, child Issues |
| `/sdd implement <issue>` | Stage 3: TDD pipeline + PR creation + PR Final review | `commands/implement.md` (190) | Branch, commits, PR, comments |
| `/sdd test <issue>` | Stage 4: QA + E2E + close Issue | `commands/test.md` (184) | Labels, integration PR (parent), Issue close |
| `/sdd resume <issue>` | Auto-detect current stage, continue | `commands/resume.md` (94) | Inherits dispatched stage |
| `/sdd auto [issues]` | In-session sequential multi-Issue loop | `commands/auto.md` (380) | All of the above × N |
| `/sdd batch [issues]` | Subprocess batch (claude -p per Issue) | `commands/batch.md` (498) | All of the above (in child sessions) |
| `/sdd status [issue]` | Read-only progress inspection (unified renderer) | `commands/status.md` (95) | None |
| `/sdd rollback <issue> <stage>` | Revert Issue to earlier stage | `commands/rollback.md` (52) | Labels, comments |
| `/sdd review <issue>` | Re-run 2 reviewers (completeness + quality) on latest stage output | `commands/review.md` (137) | Review comments |
| `/sdd help` | Show command list | `commands/help.md` (66) | None |

Routing: per `SKILL.md` line 17 (the canonical valid-commands list). Unknown command → routes to help.

---

## 3. Sub-agent inventory (atoms)

### Stage sub-agents (4 stages, 7 files)
| Sub-agent | File | Lines | Role |
|---|---|---|---|
| stage_analyze | `atoms/stage_analyze.md` | 547 | Inlines analyze_work + 3 reviewers (serial) |
| stage_design | `atoms/stage_design.md` | 698 | Inlines design_work + 3 reviewers + child creation + idempotency |
| stage_implement (split) | `atoms/stage_implement/main.md` | 456 | Entry point + phase orchestration |
| ⮤ TDD pipeline | `atoms/stage_implement/_tdd.md` | 552 | Red→Green→Refactor→E2E + R9 sha-based idempotency |
| ⮤ PR Final | `atoms/stage_implement/_pr_final.md` | 650 | 3-round PR Final loop + /code-review + /security-review + tools-summary |
| ⮤ Phase 7 child | `atoms/stage_implement/_phase7.md` | 177 | Child completion notification |
| stage_test | `atoms/stage_test.md` | 1036 | 3 paths (single/child/parent) + /verify + manual QA |

### Dispatcher sub-agent
| Sub-agent | File | Lines | Role |
|---|---|---|---|
| bootstrap | `atoms/bootstrap.md` | 170 | Reads Issue state, returns BOOTSTRAP: line (used by /sdd auto, batch, resume) |

### Standalone reviewer atoms (for /sdd review only)
| Atom | File | Lines | Role |
|---|---|---|---|
| analyze_review | `atoms/analyze_review.md` | 105 | Re-spawned by /sdd review (completeness or quality role) |
| design_review | `atoms/design_review.md` | 82 | Same |
| implement_review | `atoms/implement_review.md` | 114 | Same |
| test_review | `atoms/test_review.md` | 81 | Same |

### Helper files (referenced, not directly spawned)
| Helper | File | Lines | Purpose |
|---|---|---|---|
| Bash rules | `atoms/_bash_rules.md` | 62 | Canonical Bash execution discipline |
| Multilingual | `atoms/_multilingual.md` | 91 | en/ko/ja + parent regex |
| Preflight | `atoms/_preflight.md` | 187 | Step 0 context-discovery procedures (tier-based) |
| Review helpers | `atoms/_review_helpers.md` | 337 | Sections A-F: model assignment, JSON schema, retry, exploration budget, adversarial prompt, comment posting |
| Test evidence | `atoms/_test_evidence.md` | 116 | Raw test log truncation + posting |

### Rubric files (read by reviewer logic inside stage_X)
14 files in `atoms/rubrics/` — one per (stage, role) pair. Total ~650 lines.

---

## 4. GitHub state model (unchanged from v0.x)

All state lives on GitHub. No in-process FSM.

### Labels (lifecycle, mutually exclusive)
- `sdd:analyze` — analyze stage active
- `sdd:design` — design stage active
- `sdd:implement` — implement stage active (or parent paused after children created)
- `sdd:test` — test stage active
- `sdd:done` — pipeline complete (Issue closed)

### Labels (orthogonal)
- `sdd:child` — Issue spawned by parent's design
- `sdd:review:deep` — optional depth dial (force opus everywhere)
- `sdd:review:shallow` — optional depth dial (cheaper models, skip /security-review)

### Markers (unchanged — exact substring match including ` -->`)
- `<!-- sdd:analyze:output -->`
- `<!-- sdd:design:output -->`
- `<!-- sdd:children:output -->` (parent only)
- `<!-- sdd:child-issue -->` (child body block)
- `<!-- sdd:implement:plan -->`
- `<!-- sdd:test:output -->`
- `<!-- sdd:review:<stage>:<role> -->` (3 reviewers × 4 stages = 12 markers)
- `<!-- sdd:review:implement:step-<n> -->` (4 TDD step reviews)
- `<!-- sdd:test-evidence:step-<n> -->` (4 raw test logs)
- `<!-- sdd:review:implement:tools -->` (PR Final tools summary)
- `<!-- sdd:review:parent -->` (parent integration review)
- `<!-- sdd:findings:json -->` … `<!-- /sdd:findings:json -->` (JSON block inside reviews)
- `<!-- sdd:rollback -->` (rollback notices, intentional non-dedupe)

### Findings JSON schema (unchanged)
See `spec/00-common-contracts.md` §5. Embedded in every review comment.

---

## 5. Configuration (unchanged)

### `.github/.sdd-config`
```
skip-review: <comma-separated values from {analyze, design, implement, pr, qa}>
```

| Value | What it skips |
|---|---|
| `analyze` | User confirmation gate after analyze stage (AI review still runs) |
| `design` | User confirmation gate after design stage |
| `implement` | Plan stage user gate (3-0) |
| `pr` | PR Final user gate (3-5) |
| `qa` | Manual QA execution |

### `.github/.sdd-lang`
Single-line: `en` / `ko` / `ja`. Set by `/sdd init [lang]`.

### `.claude/settings.local.json` sandbox toggle
Per `auto.md` Phase 3.1 step 5 — opt-in disable for TLS-proxy environments.

---

## 6. Sub-agent return contract

Every stage sub-agent returns ONE line prefixed by `>>> RESULT <<<`:

### stage_analyze
- `OK ADVANCE: design`
- `OK NO_ACTION`
- `OK PAUSE`
- `ESCALATE: <summary>`
- `FAIL: <reason>`

### stage_design
- `OK ADVANCE: implement SINGLE`
- `OK ADVANCE: implement CHILDREN: #A,#B,#C`
- `OK PAUSE` / `ESCALATE: ...` / `FAIL: ...`

### stage_implement
- `OK ADVANCE: test PR: #N BRANCH: <name>`
- `OK ADVANCE: test PR: #N BRANCH: <name> E2E_SKIPPED`
- `OK PARENT_STOP`
- `OK PAUSE` / `ESCALATE: ...` / `FAIL: ...`

### stage_test
- `OK DONE`
- `OK BACK_TO_IMPLEMENT`
- `OK NEEDS_MANUAL_QA: <summary>`
- `OK NEEDS_FRAMEWORK_CHOICE: recommended=<name>`
- `OK PAUSE` / `ESCALATE: ...` / `FAIL: ...`

### bootstrap
- `BOOTSTRAP: stage=<X> depth=<dial> branch=<...> pr=<...> parent=<bool> children=<...>`
- `FAIL: <reason>`

---

## 7. Multilingual support (unchanged)

Languages: `en` / `ko` / `ja`. Parent regex (canonical):

```
(Parent|상위 |親)Issue: #<n>
```

With boundary `([^0-9]|$)` for specific N matching. See `atoms/_multilingual.md`.

---

## 8. Stage flow (unchanged)

```
(no label) → sdd:analyze → sdd:design → sdd:implement → sdd:test → sdd:done
                                                                  ↑
                                                          sdd:child (orthogonal)
```

Parent Issues stop at `sdd:implement` until all children done; then advance to `sdd:test`.

---

## 9. Internal improvements introduced in v1.0.0

| R# | Change | Where |
|---|---|---|
| R7 | Rubric files moved to `atoms/rubrics/` (dropped `ai-review-` prefix) | M1 |
| R8 | `/sdd implement <N>` with existing PR auto-routes to retry mode (no error, no new config key) | M6 — `stage_implement/_pr_final.md` |
| R9 | TDD step idempotency via sha-from-evidence (resume skips already-done steps) | M6 — `stage_implement/_tdd.md` |
| R10 | `/sdd init` transactional rollback on partial label-creation failure | M10 — `init.md` |

### R1-R6 all KEEP (no breaking changes)
- R1: round-aware markers — kept in-place overwrite (round info in JSON `round` field)
- R2: `skip-review:` key name — kept
- R3: `pr`/`qa` value names — kept
- R4: marker namespace — kept
- R5: `>>> RESULT <<<` sentinel + string keywords — kept (no JSON migration)
- R6: adversarial-only FAIL — kept current behavior (log warning, treat as FAIL, retry)

---

## 10. Architectural invariants (PRESERVE)

- Single-level sub-agent spawn: stage_X cannot spawn Agent calls; all logic inlines
- Reviewer independence: each reviewer re-fetches stage output from GitHub (not in-memory)
- Skill tool reachable from sub-agents (verified R5 spike): `/code-review`, `/security-review`, `/verify` all callable from inside stage_implement / stage_test
- Bash execution discipline (see `_bash_rules.md`) — no compound commands, no quoted variable expansion, etc.
- Comment posting via Write tool → temp file → `gh api ... --field body=@<path>` (see `_review_helpers.md` Section F)
- All markers exact-match including ` -->`
- Cleanup MUST be FIRST after `/sdd auto` loop exit (load-bearing)

---

## 11. Token economics

Per design/00-architecture.md §5 estimates:

| Metric | v0.x | v1.0.0 |
|---|---|---|
| Main session per-Issue | ~19,715 tok | **~2,610 tok (87% drop)** |
| Total system per-Issue | ~48,000 tok | ~46,000 tok (slight drop) |
| Wall-clock per stage | (parallel reviewers) | +~60s/round (serial reviewers) |

The Arch B win: main session no longer reads orchestrator markdown × 4 stages × N issues. Each stage spawns once; main only sees the return line.

---

## 12. File inventory summary

```
plugins/sdd-plugin/
├ .claude-plugin/plugin.json                       # v1.0.0
├ MIGRATION.md                                     # upgrade guide
├ SPEC.md                                          # this file
└ skills/sdd/
   ├ SKILL.md                                      # 130 lines (was 164)
   ├ commands/
   │  ├ <13 user-invocable commands>               # all stage commands now thin wrappers
   │  └ atoms/
   │     ├ <5 helpers>                             # _bash_rules, _multilingual, _preflight, _review_helpers, _test_evidence
   │     ├ <4 standalone reviewers>                # for /sdd review only
   │     ├ bootstrap.md                            # dispatcher sub-agent
   │     ├ stage_analyze.md, stage_design.md, stage_test.md
   │     ├ stage_implement/                        # split per T1.3
   │     │  └ <main.md + 3 topic files>
   │     └ rubrics/<14 rubric files>               # role-specific criteria
   └ templates/
      ├ en/ ko/ ja/                                # per-language: 4 issue + 4 output templates
```

Total: 8,344 lines of markdown (skill body, excluding templates).

---

## 13. Where to look for what

| Need | Location |
|---|---|
| What does `/sdd <command>` do? | `commands/<command>.md` |
| What logic runs inside stage X? | `commands/atoms/stage_<X>.md` (or `stage_implement/*.md` for implement) |
| What are the review criteria for stage X role Y? | `commands/atoms/rubrics/<X>-<Y>.md` |
| What's the marker / label / JSON schema contract? | `spec/00-common-contracts.md` |
| How was a behavior decided? | `design/05-rethink-decisions.md` (10 RETHINK calls) |
| What were the review-driven fixes? | `design/SYNTHESIS-v2.md` (Phase A + Phase B) |
| How do I migrate from 0.x? | `MIGRATION.md` |
| Why does X exist? | `spec/edge-cases.md` (24 cross-cutting edge cases) |

---

## 14. Verification against spec/

| Spec item | v1.0.0 status |
|---|---|
| All 5 lifecycle labels | ✓ unchanged |
| All marker conventions | ✓ unchanged |
| 5 skip-review values | ✓ unchanged |
| 3-tier depth dial | ✓ unchanged |
| Multilingual parent regex | ✓ unchanged (canonical in `_multilingual.md`) |
| Findings JSON schema | ✓ unchanged |
| 3-round retry budget (analyze/design/test) | ✓ preserved in each stage_X |
| 2-retry per TDD step | ✓ preserved in stage_implement/_tdd.md |
| 3-round PR Final | ✓ preserved in stage_implement/_pr_final.md |
| `/code-review` + `/security-review` serial ordering | ✓ preserved as in-stage convention |
| Bash heuristic discipline | ✓ canonical in `_bash_rules.md` |
| Comment posting Section F pattern | ✓ canonical in `_review_helpers.md` Section F |
| 13 user commands | ✓ all present |
| 14 rubric files | ✓ all present in `atoms/rubrics/` |
| Plugin metadata sync (plugin.json + marketplace.json) | ✓ both at 1.0.0; CI workflow enforces |
