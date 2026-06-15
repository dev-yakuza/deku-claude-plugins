# SDD Plugin — Design (Phase B)

Phase B output. Takes `spec/` as input. Produces the architectural blueprint for the Phase C rewrite.

## Inputs

- `spec/` — Phase A specification (acceptance contract). Every spec item tagged [PRESERVE]/[IMPROVE]/[RETHINK].
- 10 RETHINK decisions resolved at Phase B start (see `05-rethink-decisions.md`).
- Arch B (stage-as-subagent) baseline, validated by R5 spike (Skill tool reachable from sub-agent).

## Output structure

```
design/
├ README.md                      # this file
├ 00-architecture.md             # Arch B applied: main FSM, stage sub-agents, lifecycle
├ 01-sub-agent-contract.md       # Return contract (preserved sentinel format), state passing
├ 02-file-layout.md              # New directory structure
├ stage-designs/
│  ├ analyze.md                  # Stage sub-agent body design
│  ├ design.md
│  ├ implement.md                # Largest; most complex
│  └ test.md
├ 03-flow-design.md              # /sdd auto, /sdd batch, /sdd resume in new arch
├ 04-utilities-design.md         # init/config/status/rollback/review/help
├ 05-rethink-decisions.md        # 10 RETHINK decisions + rationale
├ 06-migration-plan.md           # Backward compat (no breaks) + R7-R10 additions
└ 07-implementation-plan.md      # Phase C order, milestones, validation
```

## Phase B scope (decided)

- **Paper design only** — architecture decisions + file outlines + contracts. No code.
- Phase C will implement based on this design + `SYNTHESIS-v2.md`.

## Status

**Phase B complete — design v2 (post-review synthesis).**

Review chain:
- `SELF-REVIEW.md` — internal audit (10 SR-D items)
- `review-A-architecture.md` — Reviewer A: 3 critical + 8 major + 4 minor + 2 counter-proposals
- `review-B-migration.md` — Reviewer B: 4 high + 5 medium + 4 low
- `review-C-feasibility.md` — Reviewer C: 3 blocking + 6 significant + 3 minor
- `SYNTHESIS-v2.md` — **normative override document** — Tier 1 (10 critical fixes) applied; Tier 2/3 (32 items) documented for Phase C
- Updated Phase C estimate: **18-27 days** (was 14-21)

**SYNTHESIS-v2.md is the canonical input to Phase C.** Design files (00-07) are reference; the synthesis takes precedence on any conflict.

## Backward compatibility policy

From RETHINK decisions R1-R6: **no external contracts change.** Labels, markers, config keys, CLI args, language aliases, regex, RESULT format — all preserved verbatim.

Internal improvements (R7-R10):
- R7: `ai-review-*.md` → `atoms/rubrics/`
- R8: empty-$3 + existing-PR auto-routing
- R9: TDD step idempotency
- R10: `init` transactional rollback

## Classification tags (same as Phase A)

- `[PRESERVE]` — external contract / platform constraint
- `[IMPROVE]` — internal refactor / DRY opportunity
- `[RETHINK]` — needs further discussion
- `[NEW]` — Phase B addition (not in current code)
- `[VERIFIED]` — empirically confirmed (e.g. R5 spike)

## Cross-references

- `spec/` — acceptance contract (don't break)
- `spec/SYNTHESIS-v2.md` — Phase A close-out
- Earlier conversation:
  - Arch B vs Arch A comparison (~65% main savings vs ~35%)
  - R5 spike verifying Skill in sub-agent
  - 10 RETHINK decisions
