# 01 — Sub-agent Contract

How the main session communicates with stage sub-agents. Preserves the existing `>>> RESULT <<<` sentinel + string-keyword format (R5 decision: do not migrate to JSON).

---

## 1. Input: prompt main session sends to stage sub-agent

Spawned via Agent tool with `subagent_type: general-purpose`. Prompt template:

```
Read <<SKILL_DIR>>/commands/stage_<X>.md and execute its instructions
for Issue #<N>.

Inputs:
  Issue: #<N>
  Depth: <default|deep|shallow>
  Retry: <none|"retry">           # only for stages 2-3 of TDD pipeline (see implement)
  Branch: <branch-name|null>      # threaded from prior stage (implement → test)
  PR: #<PR_NUM|null>              # threaded from prior stage

Return EXACTLY one line in the contract specified by stage_<X>.md,
prefixed by the `>>> RESULT <<<` marker line.
```

### Fields per stage

| Stage | Required | Optional |
|---|---|---|
| analyze | Issue, Depth | none |
| design | Issue, Depth | none |
| implement | Issue, Depth | Branch (if resuming) |
| test | Issue, Depth | Branch, PR (always passed from implement) |

[PRESERVE — load-bearing]: stage sub-agents do NOT receive prior stage's outputs in prompt. They re-read GitHub. Inputs are minimal cache hints.

---

## 2. Output: return contract per stage

### Sentinel format [PRESERVE]
Every stage sub-agent's final output ends with:
```
>>> RESULT <<<
<status> <fields>
```

The line BEFORE the sentinel may contain narrative — main session ignores until it sees the sentinel.

### Status keywords by stage

#### stage_analyze
| Return | Meaning |
|---|---|
| `OK ADVANCE: design` | Reviews passed; label transitioned to sdd:design |
| `OK NO_ACTION` | Issue concluded no-action; label transitioned to sdd:done |
| `OK PAUSE` | User chose Pause in escalation (skip-review off) |
| `ESCALATE: <summary>` | Round 3 FAIL, interactive mode (no skip-review) — main asks user |
| `FAIL: <reason>` | Atom-level error — main stops |

#### stage_design
| Return | Meaning |
|---|---|
| `OK ADVANCE: implement SINGLE` | Single-PR design; parent → sdd:implement |
| `OK ADVANCE: implement CHILDREN: #A,#B,#C` | Multi-PR; children created; parent paused |
| `OK PAUSE` | User chose Pause |
| `ESCALATE: <summary>` | Round 3 FAIL interactive |
| `FAIL: <reason>` | Atom-level error |

#### stage_implement
| Return | Meaning |
|---|---|
| `OK ADVANCE: test PR: #N BRANCH: <name>` | TDD + PR Final passed |
| `OK ADVANCE: test PR: #N BRANCH: <name> E2E_SKIPPED` | E2E was skipped, document for test |
| `OK PARENT_STOP` | Issue is parent; children take over (no stage work) |
| `OK PAUSE` | User chose Pause |
| `ESCALATE: <summary>` | Round 3 FAIL interactive |
| `FAIL: <reason>` | Atom-level error |

#### stage_test
| Return | Meaning |
|---|---|
| `OK DONE` | All passed; label → sdd:done; Issue closed |
| `OK BACK_TO_IMPLEMENT` | QA failure; user routed back to implement |
| `OK PAUSE` | User chose Pause |
| `ESCALATE: <summary>` | Round 3 FAIL interactive |
| `FAIL: <reason>` | Atom-level error |

[PRESERVE]: format mirrors existing atom return contract from spec/00-common-contracts.md §6, extended for stage-level returns.

---

## 3. Escalation pattern (new)

When a stage sub-agent hits Round 3 FAIL in **interactive mode** (no skip-review for that gate):

### Sub-agent returns
```
>>> RESULT <<<
ESCALATE: <stage> round 3 FAIL — findings: [critical] X, [major] Y
```

### Main session handles
```
1. Parse ESCALATE.
2. Call AskUserQuestion: "Continue / Pause / Stop?"
3. Branch on user choice:
   - Continue → re-spawn stage_<X> with hint Resume-after-escalation
   - Pause → exit cleanly; user invokes /sdd resume <N> later
   - Stop → exit
```

[NEW — Arch B addition]: in current architecture this is inline in orchestrator. In Arch B, sub-agent surfaces decision to main, main handles AskUserQuestion.

### Sub-agent "Resume-after-escalation" hint
On the re-spawn after Continue:
```
Inputs include: Resume: continue-after-escalation
```
Sub-agent skips Round 1 work atom (already posted), skips review rounds (already done), goes directly to Phase 6 (output + label transition) with the findings persisted on GitHub for human follow-up.

---

## 4. Skip-review handling

User's `.github/.sdd-config` is parsed by main session (not sub-agent). Main decides whether to:
- Auto-advance after stage_<X> returns OK (skip-review for the gate is set), OR
- Ask user to confirm (skip-review NOT set)

Stage sub-agent NEVER calls AskUserQuestion. If skip-review is OFF and the stage would normally require user confirmation, sub-agent returns one of:
- `OK <action>` — sub-agent finished its work; main asks user before advancing
- `ESCALATE: ...` — only on Round 3 FAIL

[PRESERVE]: skip-review semantics (gate skip, not AI review skip).

### Distinction: stage sub-agent vs main session responsibilities

| Action | Where |
|---|---|
| AI review loop (max 3 rounds) | Inside stage sub-agent |
| Round verdict combination | Inside stage sub-agent |
| Round 3 escalation interactive prompt | Main session (via AskUserQuestion) |
| skip-review auto-advance | Main session |
| Label transition | Main session (after stage_X returns OK) |
| `/code-review` + `/security-review` invocation | Inside stage_implement |
| Tools-summary comment post | Inside stage_implement |
| User confirmation gates | Main session |
| Child Issue queue management | Main session (auto.md) |

---

## 5. Retry mode (atom-side, preserved)

Within stage_<X>, retry mode for Phase 1 work is signaled by **a stage-internal flag**, not by main session.

- Round 1 work runs normally.
- After review FAIL, stage sub-agent re-invokes its own work logic with retry context (self-fetched markers per current atom convention).
- Main session has no awareness of retry rounds — it sees only the final stage outcome.

[PRESERVE — load-bearing]: retry mode atom self-fetch invariant from spec/00-common-contracts.md §7.

### Exception: implement_pr retry context for PR Final
- stage_implement's Phase 5 (PR Final) retry self-fetches the 3 SDD reviewer markers + /code-review + /security-review inline comments.
- Markers preserved [PRESERVE].
- Implementation: same logic as current atoms/implement_pr.md retry mode, just inlined into stage_implement.

---

## 6. ESCALATE return — main session contract

When main session receives `ESCALATE: <summary>`:

```
1. Render <summary> verbatim to user.
2. Call AskUserQuestion with 3 options: Continue / Pause / Stop
3. On Continue:
   - Re-spawn stage_<X>(issue, depth, branch, pr_num, Resume: 'continue-after-escalation')
4. On Pause:
   - Print "Resume later with /sdd resume <N>"
   - Exit gracefully (main loop break)
5. On Stop:
   - Exit immediately
```

[NEW]: this is the only non-trivial extension to the contract. All other behavior is direct port of current atom contracts.

---

## 7. Bootstrap atom (replaces resume.md)

Tiny dispatcher run as a sub-agent at the start of each Issue:

### Inputs
- `Issue: #<N>`

### Behavior
- `gh issue view N --json labels,body,title`
- `gh api ... /comments` — detect markers (analyze:output, design:output, children:output, implement:plan, test:output)
- `gh pr list --search "Refs #N"` — detect PR

### Returns
```
>>> RESULT <<<
BOOTSTRAP: stage=<next-stage> depth=<dial> branch=<branch|null> pr=<pr|null> parent=<bool> children=[<#A,#B,...>|null]
```

Main session uses this to initialize its FSM state for the Issue.

[NEW]: makes the resume.md logic explicit and main-session-driven. Per current spec/flow/resume.md the dispatcher already runs inline in main; Arch B turns it into a sub-agent call to keep main session's context light.

---

## 8. What main session needs to remember

After a stage sub-agent returns:

| State | Where stored | Purpose |
|---|---|---|
| Current stage | parsed from OK ADVANCE: <next-stage> | Drive next spawn |
| Branch name | parsed from implement's OK ADVANCE | Pass to test stage |
| PR number | parsed from implement's OK ADVANCE | Pass to test stage |
| Children list | parsed from design's OK ADVANCE: implement CHILDREN: ... | auto.md queues children |

That's it. Main session is essentially a state machine over these 4 fields plus the Issue queue.

---

## 9. Contract validation

Main session validates returned line against expected status keywords for the stage. Unknown keyword → treat as `FAIL: unexpected return: <line>` and stop.

[NEW — defensive]: prevents silent misdispatch on stage sub-agent hallucination.

---

## Cross-references

- Architecture overview: `00-architecture.md`
- Per-stage internal design: `stage-designs/*.md`
- Migration of current atom calls into stage sub-agents: `06-migration-plan.md`
