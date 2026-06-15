# SDD Plugin — Specification (Phase A)

This directory captures the **acceptance specification** of the current SDD plugin, extracted from `plugins/sdd-plugin/skills/sdd/` source. It is the input to the rewrite design phase.

## Scope decisions

- **Coverage**: full plugin (all `/sdd <command>`, atoms, templates).
- **Backward compat target**: loose — markers/labels/commands may be renamed in the rewrite with a documented migration path and a dual-read shim release.
- **Output structure**: layered (this directory).

## Classification tags

Every spec item is tagged:

- `[PRESERVE]` — external contract / user data dependency / platform constraint. Cannot be broken.
- `[IMPROVE]` — internal structure, naming, or consistency. Rewrite should clean up.
- `[RETHINK]` — purpose unclear, redundant, possibly removable, or breaking change requiring user decision. Needs explicit discussion before applying.
- `[VERIFIED]` — empirically confirmed capability (used only where a spike validated platform behavior, e.g. Skill tool in sub-agents).
- `[REFERENCE]` — cross-reference / example block, no behavioral assertion.

### Decision rule (v2)
For surface contracts users interact with directly (labels, markers, config keys, CLI args, language aliases): **default to [PRESERVE]**. Renaming requires explicit `[RETHINK]` with user decision + dual-read shim migration path.

## Files

```
spec/
├ README.md                  # this file
├ 00-common-contracts.md     # markers, labels, JSON schema, GitHub state model
├ 01-config.md               # .sdd-config, skip-review, depth labels, sandbox toggle
├ 02-multilingual.md         # en/ko/ja patterns, parent regex, template mapping
├ stage/
│  ├ analyze.md              # analyze stage spec
│  ├ design.md               # design stage spec
│  ├ implement.md            # implement stage spec (TDD pipeline, PR Final)
│  └ test.md                 # test stage spec (QA gate, parent integration)
├ flow/
│  ├ auto.md                 # /sdd auto loop + child auto-discovery
│  ├ batch.md                # /sdd batch subprocess generation
│  └ resume.md               # dispatcher logic
├ utilities.md               # status, rollback, init, config, help, review
├ edge-cases.md              # multilingual, parent/child, sandbox, depth labels, billing pool, recovery
└ commands-inventory.md      # full /sdd <command> surface catalog
```

## Status

**Phase A complete — Spec v2 (post-review synthesis).**

Review chain:
- `SELF-REVIEW.md` — pre-review internal audit (11 gaps identified)
- `review-A-completeness.md` — Reviewer A: 24 completeness gaps (6 high, 9 medium, 9 low)
- `review-B-accuracy.md` — Reviewer B: 1 critical + 6 minor errors + 16 verified-correct
- `review-C-classification.md` — Reviewer C: 36 tagging issues (10 IMPROVE→PRESERVE, 6 PRESERVE→IMPROVE, 5 missing RETHINK, 6 untagged, 9 inconsistent)
- `SYNTHESIS-v2.md` — Tier 1 fixes applied; Tier 2/3 deferred to design phase

| File | Lines | Status |
|---|---:|---|
| 00-common-contracts.md | ~430 | ✓ self-review pass |
| 01-config.md | ~250 | ✓ |
| 02-multilingual.md | ~140 | ✓ |
| stage/analyze.md | 315 | ✓ |
| stage/design.md | 402 | ✓ |
| stage/implement.md | 490 | ✓ |
| stage/test.md | 448 | ✓ |
| flow/resume.md | 139 | ✓ |
| flow/auto.md | 359 | ✓ |
| flow/batch.md | 463 | ✓ |
| utilities.md | 338 | ✓ |
| commands-inventory.md | 127 | ✓ |
| edge-cases.md | ~410 | ✓ |
| **Total** | **~4,360** | — |

Source extracted from ~7,000 lines (~62% compression with cross-cutting consolidation).
