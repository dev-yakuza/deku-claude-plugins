# 00 — Architecture

Arch B (stage-as-subagent) applied to the SDD pipeline. The main session becomes a thin FSM dispatcher; each stage runs as a single sub-agent that internally handles work + reviews serially.

---

## 1. Overall shape

```
User
  │
  ▼
Main session (FSM)                       <- minimal, ~80 lines orchestrator
  │
  │ for each Issue in queue:
  │   spawn ONE stage_subagent           <- per stage, per Issue
  │
  ▼
stage_<analyze|design|implement|test>    <- sub-agent (Agent tool)
  │
  │ Internally:
  │   - inline work atom logic
  │   - inline 3 review atoms serially  <- no nested spawn (platform constraint)
  │   - inline /code-review, /security-review (Skill tool — VERIFIED reachable)
  │   - inline retry loop
  │   - post all GitHub comments via Section F temp-file pattern
  │
  │ Returns one line: `>>> RESULT <<<`
  │
  ▼
Main session parses return, updates state, spawns next stage
```

[PRESERVE — load-bearing]: The single-level spawn rule (atoms cannot spawn atoms) is preserved. Stage sub-agents are leaves from the main session's perspective. All nested logic is inlined into the stage sub-agent's own context.

---

## 2. Main session FSM

The main session reads `auto.md` (or invokes a single stage command). Its job:

### State held in main session
```
{
  queue: [<issue#>, ...],        // Issue queue (auto/batch only)
  seen: Set<issue#>,             // dedup tracker
  current_issue: <issue#>,
  current_stage: 'analyze' | 'design' | 'implement' | 'test' | null,
  stage_results: { ... },        // last stage's return parsed
  branch: <string> | null,       // threaded for implement → test
  pr_num: <int> | null,          // threaded for implement → test
  depth: 'default' | 'deep' | 'shallow',
}
```

Size: tiny. State lives on GitHub via labels + markers; this in-process state is purely cache.

### Main session loop (pseudocode)

```
for issue in queue:
    state = bootstrap(issue)        // gh issue view → labels, body
    while state.current_stage != 'done':
        spawn stage_<X>(issue, state)
        result = parse_result(returned_line)
        update_state(state, result)
        handle_skip_review_advance(state)
    handle_child_auto_discovery(issue)
```

[PRESERVE]: User confirmations (skip-review gates, sandbox toggle, etc.) happen in main session — sub-agents are non-interactive. AskUserQuestion only callable from main.

---

## 3. Stage sub-agent shape

Each stage_X is a self-contained sub-agent. The md file for each stage_X.md is comprehensive (inlines work atom + reviewer rubrics + retry loop).

### Per-stage structure
```
stage_<X>.md (Read by Agent tool spawn)
├ §1. Inputs (from main session prompt: issue, depth, retry state)
├ §2. Phase 0 — Depth detection
├ §3. Phase 1 — Work (inline analyze_work/design_work/etc. logic)
├ §4. Phase 2 — Reviews (SERIAL: completeness → quality → adversarial)
│         Each review reads role-specific rubric from atoms/rubrics/
├ §5. Phase 3 — Retry loop (max 3 rounds; on FAIL → revise work, re-review)
│         Atom self-fetches prior findings via marker fetch
├ §6. Phase 4 — Skill invocations (implement only: /code-review, /security-review)
├ §7. Phase 5 — Escalation gate (round 3 fail)
└ §8. Phase 6 — Output (post all markers, return >>> RESULT <<< line)
```

### Reviews run serially in stage_X context
- Why: single-level spawn prevents parallel sub-agents inside a stage sub-agent.
- Trade-off: ~30s × 3 = 90s wall-clock per review round vs current 30s parallel.
- Acceptance criterion: `/sdd auto` unattended runs care about throughput-per-Issue, not single-Issue latency.
- For `/sdd <stage>` interactive runs: same penalty. User accepted in Arch B comparison (+5-8 min/Issue).

### Reviews remain independent
- Each review reads ONLY its role-specific rubric (from `atoms/rubrics/`).
- No cross-visibility of other reviewers' verdicts.
- [PRESERVE: independence invariant from spec/00-common-contracts.md].

### Verdict combination
- Inside stage_X, after all 3 reviews complete: combine PASS/FAIL.
- All 3 PASS → exit retry loop.
- Any FAIL → revise work, retry (max 2 retries = 3 rounds total).
- Adversarial-only FAIL → log warning, treat as FAIL (per R6 decision).
- Round 3 FAIL → escalation gate (skip-review auto-continues, else user gate via main).

[NEW for Arch B]: escalation gates that need user interaction return a special marker line (e.g. `>>> RESULT <<<\nESCALATE: stage analyze, round 3 FAIL, findings: ...`). Main session receives this, calls AskUserQuestion, re-spawns stage_X with user's choice.

---

## 4. Skill invocations (implement stage only)

[VERIFIED — R5 spike]: `general-purpose` sub-agent can invoke Skill tool.

### Inside stage_implement
```
After PR Final reviews (3 SDD reviewers serial):
  - Invoke /code-review (Skill) — effort by depth
  - Invoke /security-review (Skill) — skip on shallow
  - Post tools-summary comment to PR
  - Combine SDD verdict + Skill verdict per spec/stage/implement.md §7-8
```

[PRESERVE — load-bearing]: serial ordering preserved (Skill cannot run in parallel batch with Agent calls in same message). Inside a sub-agent's context this is moot (no Agent calls happen there) — but the policy stays: Skills run after SDD reviews complete.

---

## 5. Main session token math

Per Issue (Round 1 PASS, full pipeline):

| Component | Tokens (estimate) |
|---|---|
| auto.md read (amortized over loop) | 80 lines × 12 = ~960 |
| 4 stage sub-agent envelopes (prompt + return) | 4 × 350 = 1,400 |
| Bootstrap atom (label+comment read) | ~250 |
| **Main per Issue total** | **~2,610 tok** |

vs. current architecture: ~19,715 tok per Issue. **~87% main session savings**.

[VERIFIED — Phase A cost analysis]: this is the headline win.

### Sub-agent side
Each stage sub-agent reads its own stage_X.md (~500-700 lines, est. 6-8K tok) plus rubric files (~3 files × ~50 lines = ~1.8K tok). Per-stage cold-boot ~8K. Across 4 stages = 32K tok. Plus generation + GH API responses.

Total system tokens per Issue: similar to current (~46K vs current 48K). Arch B saves main pressure without raising total bill.

[VERIFIED — Phase A Arch B cost analysis].

---

## 6. Sub-agent isolation

Each stage sub-agent boots fresh. No state from main session except what main passes in the prompt (issue#, depth, retry context if applicable).

### State passing into stage sub-agent
Main session's prompt to `stage_X` spawn includes:
- `Issue #<N>` — the target Issue number
- `Depth: <default|deep|shallow>` — from label or default
- Retry context: empty (sub-agent self-derives if needed by reading existing markers — per current atom retry semantics)
- For test/implement: previous stage's branch/PR if any (passed verbatim from main FSM state)

### State returned from stage sub-agent
Single `>>> RESULT <<<` line per current contract. See `01-sub-agent-contract.md`.

---

## 7. What changes vs current architecture

| Layer | Current | Arch B |
|---|---|---|
| Main session | reads 4 orchestrator MDs inline, parses atom returns | reads ~80-line FSM only |
| Orchestrator | runs in main session | becomes stage sub-agent body (atomized) |
| Atoms | spawned by orchestrator | inlined into stage sub-agent (no longer separate Agent calls) |
| Skill invocations | spawned by main session | inlined into implement stage sub-agent |
| Parallel reviews | 3 parallel sub-agent calls from main | 3 serial in-context reviews |
| Retry context | atom self-fetches | same (no change) |
| GitHub markers | unchanged | unchanged [PRESERVE] |
| Labels | unchanged | unchanged [PRESERVE] |

---

## 8. Risk profile

| Risk | Mitigation |
|---|---|
| Stage sub-agent context bloat (~8-12K tokens per stage MD) | Fine — sub-agent context limit is separate from main session |
| Parallel review loss (90s vs 30s wall) | Accepted per Arch B decision |
| Sub-agent crash mid-stage | Current behavior preserved — restart `/sdd resume <N>` re-detects state from GitHub |
| Inline atom logic harder to test in isolation | Mitigated by per-rubric file pattern (`atoms/rubrics/`) — rubrics still independently inspectable |
| Loss of granular telemetry (atom-level usage) | Stage-level usage available; per-atom unavailable. Acceptable. |

---

## 9. What stays the same

- Stage flow: analyze → design → implement → test
- Labels: `sdd:analyze`, `sdd:design`, ..., `sdd:child`, `sdd:review:deep/shallow`
- All GitHub markers (`<!-- sdd:* -->`)
- All `gh` commands and patterns
- Skip-review semantics (5 keys, AI review always runs)
- Depth labels and model assignments
- Multilingual support (en/ko/ja)
- Retry mode with literal `"retry"` slot
- `>>> RESULT <<<` sentinel
- Findings JSON schema
- Comment posting temp-file pattern
- Bash heuristic rules
- Issue Validation gate
- Owner/repo resolution
- Parent/child Issue lifecycle
- 10 RETHINK decisions R1-R6 (all "keep")

---

## 10. What is new

- Stage-as-subagent execution model
- Main session is thin FSM
- `atoms/rubrics/` directory (R7)
- empty-$3 + existing-PR auto-routing (R8)
- TDD step idempotency (R9)
- `init` transactional rollback (R10)
- Escalation-via-main-session pattern (sub-agent returns ESCALATE marker)

These are the only behavioral additions. Everything else is structural (where code lives, how it's organized).

---

## Cross-references

- Sub-agent return contract: `01-sub-agent-contract.md`
- File layout: `02-file-layout.md`
- Per-stage design: `stage-designs/*.md`
- 10 RETHINK decisions: `05-rethink-decisions.md`
- Migration: `06-migration-plan.md`
- Implementation order: `07-implementation-plan.md`
