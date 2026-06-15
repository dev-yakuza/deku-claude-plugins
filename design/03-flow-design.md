# 03 — Flow Design

Flow-layer design for Arch B. Covers `/sdd auto`, `/sdd batch`, and `/sdd resume`. The flow layer is the **main session** code that drives per-Issue dispatch; in Arch B it is slimmer because per-Issue work happens inside stage sub-agents.

Companions: `00-architecture.md` (Arch B overview), `01-sub-agent-contract.md` (`>>> RESULT <<<` envelope, ESCALATE), `02-file-layout.md` (file split).

---

## 1. `/sdd auto` in Arch B

### 1.1 Shape

`commands/auto.md` is a **thin FSM body**. It walks all five phases (1 collect, 2 permissions, 3.1 pre-loop setup, 3.2 loop body, 3.3 child discovery, 3.4 cleanup, 3.5 summary). Phase 3.2's per-Issue dispatch becomes:

```
bootstrap sub-agent → stage_X sub-agent → ... → done
```

instead of `read resume.md inline → read stage orchestrator inline → spawn atoms`. The orchestrator-reads-orchestrator pattern is gone; the FSM is the only main-session code.

### 1.2 Main FSM pseudocode

The full main-session loop body, ~50 lines:

```
# Phase 1, 2, 3.1 setup happens before this block — see §1.3 to §1.5.
# State held in main-session narrative (no on-disk persistence).
QUEUE       = [<issue#>, ...]            # FIFO from Phase 1
SEEN        = set(QUEUE)
TOTAL       = len(QUEUE)
PROCESSED, SUCCEEDED, FAILED = 0, 0, 0
FAILED_ROWS = []
BATCH_START = unix_now()

while QUEUE not empty:
    ISSUE = QUEUE.pop_front()
    PROCESSED += 1
    print f"[{PROCESSED}/{TOTAL}] Processing Issue #{ISSUE}..."

    boot = spawn bootstrap(ISSUE)
    if boot.status == "FAIL":
        FAILED += 1; FAILED_ROWS.append((ISSUE, boot.reason)); continue
    if boot.stage == "done":
        SUCCEEDED += 1; print "Issue already complete."
        run_child_discovery(ISSUE); continue

    state = { issue: ISSUE, stage: boot.stage, depth: boot.depth,
              branch: boot.branch, pr_num: boot.pr_num, parent: boot.parent }

    while state.stage != "done":
        result = spawn stage_<state.stage>(state)
        if result.status == "FAIL":
            FAILED += 1; FAILED_ROWS.append((ISSUE, result.reason)); break
        if result.status == "ESCALATE":
            choice = ask_user("Continue / Pause / Stop?", result.summary)
            if choice == "Continue":
                state.resume_hint = "continue-after-escalation"; continue
            elif choice == "Pause":
                print "Resume later with /sdd resume {ISSUE}"; goto cleanup
            else:  # Stop
                goto cleanup
        if result.status == "OK PAUSE":      print "Paused."; break
        if result.status == "OK PARENT_STOP": SUCCEEDED += 1; break
        if result.status == "OK BACK_TO_IMPLEMENT":
            state.stage = "implement"; continue
        state = apply_advance(state, result)  # OK ADVANCE → next stage

    if state.stage == "done":
        SUCCEEDED += 1
        run_child_discovery(ISSUE)

# Phase 3.4 cleanup FIRST, then 3.5 summary — see §10.
cleanup(); print_summary()
```

Total active code in `auto.md`: ~80 lines.

### 1.3 Phase 1: Collect and filter Issues — unchanged

Per `spec/flow/auto.md` §4 and `spec/flow/batch.md` §5 (canonical):

- All-open: `gh issue list --state open --json number,title,labels --limit 200`; exclude `sdd:done` and `sdd:child`; sort ascending.
- Specific: validate each via `gh issue view <n> --json url --jq .url` (per `00-common-contracts.md` §10); exclude `sdd:done` with warning; **include** `sdd:child` (explicit user choice); sort ascending.
- Empty post-filter → `"No qualifying Issues found."` stop.
- Display confirmation block; show skip-review keys `analyze,design,implement,pr,qa`.
- Dirty-tree warning: `git status --porcelain`; non-empty → ask `Proceed anyway? [y/N]`.

Phase 1 is pure main-session data collection.

### 1.4 Phase 2: Verify tool permissions — unchanged

Per `spec/flow/auto.md` §5 and `spec/flow/batch.md` §6. Same three-group UI (Required / Recommended / Test Runners), marker-based project detection, merge into `.claude/settings.local.json`. Header reads `Tool permissions for /sdd auto (in-session sequential)`. Note about subagents inheriting main-session permissions is preserved — stage sub-agents inherit from main.

### 1.5 Phase 3.1: Pre-loop setup — unchanged (sandbox toggle preserved per R4)

Per `spec/flow/auto.md` §6, all six steps preserved verbatim:

1. **Resolve owner/repo** via `gh repo view --json nameWithOwner -q .nameWithOwner`; inline literal `<owner>/<repo>` per `00-common-contracts.md` §11.
2. **Back up `.github/.sdd-config`** to `.sdd-config.bak` (Read + Write tools, only if it exists).
3. **Write temporary skip-review** `skip-review: analyze,design,implement,pr,qa` (five keys — `qa` is what differentiates auto from batch and lets manual QA inside `stage_test` auto-pass).
4. **Append `.git/info/exclude` entries** for `.sdd-config`, `.sdd-config.bak`, and (later) `<SETTINGS_PATH>.sdd-auto.bak`.
5. **Sandbox disable** (optional, prompted, exits before loop) — **R4: external behavior unchanged**.
   - Locate settings file: `.claude/settings.local.json` → `.claude/settings.json` → `~/.claude/settings.json`.
   - Determine state (file missing / `sandbox` absent / `enabled == true` → ON).
   - Already OFF → skip prompt, log, proceed to step 6.
   - ON → `AskUserQuestion` per `01-config.md` §4. On approval (5e): snapshot to `.sdd-auto.bak`, set `enabled = false`, append `.sdd-auto.bak` to `.git/info/exclude` if in-repo, **roll back the pre-loop changes from steps 2–4** (restore or delete `.sdd-config`), print next-steps block, and **terminate `/sdd auto`**. On rejection: continue without toggle, no backup.
6. **Print recovery hint**:
   ```
   If this session is interrupted, restore your state with:
     mv .github/.sdd-config.bak .github/.sdd-config       # if .sdd-config.bak exists
   ```

All main-session work — no sub-agents. Arch B change starts after Phase 3.1.

### 1.6 Phase 3.2: Loop body — Arch B change

Loop semantics from `spec/flow/auto.md` §7 preserved; step 3 (dispatch) changes:

| Step | Current | Arch B |
|---|---|---|
| 1. Pop ISSUE, increment counter | unchanged | unchanged |
| 2. Print progress line | unchanged | unchanged |
| **3. Dispatch** | `read resume.md inline → stage orchestrator inline → spawn atoms` | `spawn bootstrap → loop: spawn stage_<X>` |
| 4. On success → child discovery | unchanged | unchanged |
| 5. On FAIL → record + continue | unchanged | unchanged |

Loop is **failure-tolerant**: one bad Issue does not abort the queue.

### 1.7 Phase 3.3: Child auto-discovery — unchanged

Per `spec/flow/auto.md` §8, after each successful Issue:

- **Literal-value substitution** (`00-common-contracts.md` §8): main-session narrative substitutes the literal Issue number AND literal `<owner>/<repo>` before Bash. No `${ISSUE}` inside quoted args.
- Bash call (with literals substituted):
  ```
  gh issue list --repo <owner>/<repo> --label sdd:child --state open --limit 200 --json number,body --jq '[.[] | select(.body | test("(Parent|상위 |親)Issue: #<N>([^0-9]|$)"))] | .[] | .number'
  ```
- For each discovered child not in `SEEN`: append to `QUEUE`, add to `SEEN`, increment `TOTAL`, print `+ Discovered child Issue #<N> → queued (total now <TOTAL>)`.

Multilingual regex `(Parent|상위 |親)Issue: #<n>([^0-9]|$)` canonical per `spec/02-multilingual.md` §3. Boundary `([^0-9]|$)` prevents `#683` matching `#6831`; `$` is jq's end-of-string anchor — do NOT escape.

Runs in **main session**, not in any sub-agent — children must enter the FSM's `QUEUE`.

### 1.8 Phase 3.4: Cleanup — unchanged (ordering invariant preserved)

Per `spec/flow/auto.md` §9. See §10 below for the load-bearing ordering invariant. Steps:

1. If `.github/.sdd-config.bak` exists → Read it, Write back to `.sdd-config`, `rm -f .sdd-config.bak`.
2. Else (no original config existed) → `rm -f .sdd-config`.
3. Re-read settings file at priority order; if `sandbox.enabled == false`, show disabled-state notice. Cleanup does NOT modify the sandbox setting.

Hard-kill (Cmd-Q / terminal close / kernel kill) → cleanup cannot run. Recovery hint from Phase 3.1 step 6 is the only safety net. Same as current.

### 1.9 Phase 3.5: Final summary — unchanged

Per `spec/flow/auto.md` §10. Print after cleanup:

```
SDD Auto Complete
══════════════════
Total processed: <PROCESSED>
Succeeded:       <SUCCEEDED>
Failed:          <FAILED>
<list of failed Issues with reasons, if any>

Time:            <minutes>m <seconds>s
Config restored: .github/.sdd-config
Sandbox:         <enabled | disabled — restart in NORMAL mode recommended | unchanged>
Next steps:      review PRs and QA evidence on GitHub
```

Cost aggregation **not available** in `/sdd auto` (main session lacks per-subagent usage API). Unchanged constraint.

---

## 2. Bootstrap sub-agent (new — `atoms/bootstrap.md`)

Replaces `resume.md`'s inline dispatch logic. Runs as a sub-agent at the start of each Issue iteration (and as the sole work unit when `/sdd resume <N>` is invoked).

### 2.1 Why a sub-agent

Reading labels + comments + PRs costs ~250 main-session tokens per Issue. Moving it into a sub-agent confines those tokens to the sub-agent's context. Per `00-architecture.md` §5, ~10-15% of per-Issue main-session budget.

### 2.2 Inputs

```
Read <<SKILL_DIR>>/atoms/bootstrap.md and execute its instructions
for Issue #<N>.

Inputs:
  Issue: #<N>
```

### 2.3 Behavior

State sources (each a single simple Bash call per `00-common-contracts.md` §8):

1. **Validate** — `gh issue view <N> --json url --jq .url`. `/pull/` → `FAIL: #<N> is a Pull Request`. Empty → `FAIL: #<N> not found`.
2. **Labels + title** — `gh issue view <N> --json labels,title --jq '{title: .title, labels: [.labels[].name]}'`.
3. **Owner/repo** — `gh repo view --json nameWithOwner -q .nameWithOwner`; inline literal in step 4.
4. **Stage markers** — `gh api repos/<owner>/<repo>/issues/<N>/comments --jq '.[] | select(.body | contains("sdd:analyze:output") or contains("sdd:design:output") or contains("sdd:children:output") or contains("sdd:implement:plan") or contains("sdd:test:output")) | .body'`.
5. **Related PRs** — `gh pr list --search "Refs #<N>" --json number,title,state,headRefName`.

Apply dispatch table (per `spec/flow/resume.md` §2):

| Label | Initial stage |
|---|---|
| (no SDD label) | `analyze` |
| `sdd:analyze` | `analyze` |
| `sdd:design` | `design` |
| `sdd:implement` | `implement` (sub-agent handles PR closed / branch-without-PR routing internally) |
| `sdd:test` | `test` |
| `sdd:done` | `done` |

Parent detection: `<!-- sdd:children:output -->` marker present → `parent = true`. Depth: from `sdd:review:deep` / `sdd:review:shallow` labels. Branch/PR: from `Refs #<N>` PR if open, else null.

### 2.4 Returns

```
>>> RESULT <<<
BOOTSTRAP: stage=<analyze|design|implement|test|done> depth=<default|deep|shallow> branch=<name|null> pr=<num|null> parent=<true|false>
```

Per `01-sub-agent-contract.md` §7. Main session parses into FSM `state`.

### 2.5 What bootstrap does NOT do

Bootstrap is **idempotent and read-only**. It never posts comments, mutates labels, spawns sub-agents, or asks the user. Label transitions belong to stage sub-agents (the first-time `(no label) → sdd:analyze` transition happens inside `stage_analyze`).

[PRESERVE]: dispatcher-vs-worker separation from `spec/flow/resume.md` §1.

---

## 3. Main session FSM state

What the main session holds in narrative across stage spawns. Per `00-architecture.md` §2, the FSM state is small:

| Field | Purpose | Set by |
|---|---|---|
| `QUEUE` | FIFO of Issue numbers | Phase 1; child discovery appends |
| `SEEN` | Membership dedup | Phase 1; child discovery adds |
| `TOTAL` | Initial queue size; grows with children | Phase 1; child discovery increments |
| `PROCESSED`, `SUCCEEDED`, `FAILED` | Counters | Loop iteration |
| `FAILED_ROWS` | `(issue, reason)` list for summary | On FAIL |
| `BATCH_START` | Epoch for wall time | Loop start |
| **Per-Issue (cleared each iteration)** | | |
| `state.issue` | Current Issue | bootstrap return |
| `state.stage` | `analyze`/`design`/`implement`/`test`/`done` | bootstrap; stage return |
| `state.depth` | `default`/`deep`/`shallow` | bootstrap |
| `state.branch` | Threaded for implement → test | bootstrap; stage_implement |
| `state.pr_num` | Threaded for implement → test | bootstrap; stage_implement |
| `state.parent` | True if `sdd:children:output` posted | bootstrap |
| `state.resume_hint` | `"continue-after-escalation"` after ESCALATE Continue | main on ESCALATE |

State lives in **main session narrative** — no disk file. GitHub remains the only durable state per `00-common-contracts.md` §2.

**Crash recovery**: per `spec/flow/auto.md` §11, on session death user re-runs `/sdd auto <remaining-numbers>`. Bootstrap re-detects each Issue's stage from on-GitHub state. In-memory FSM rebuilt from scratch.

---

## 4. Stage spawn pattern

Per `01-sub-agent-contract.md` §1, every stage spawn uses the same template with literal values substituted:

```
Read <<SKILL_DIR>>/atoms/stage_<X>.md and execute its instructions
for Issue #<N>.

Inputs:
  Issue: #<N>
  Depth: <default|deep|shallow>
  Retry: <none|continue-after-escalation>
  Branch: <branch-name|null>
  PR: #<PR_NUM|null>

Return EXACTLY one line in the contract specified by stage_<X>.md,
prefixed by the `>>> RESULT <<<` marker line.
```

### 4.1 Substitution discipline

Per `00-common-contracts.md` §8, main session MUST substitute literal values before Agent tool invocation. Concretely: FSM `state.issue = 42`, `state.depth = "default"`, `state.branch = "feat/auth-42"`, `state.pr_num = 87` → spawned prompt contains literal `Issue: #42`, `Depth: default`, `Branch: feat/auth-42`, `PR: #87`. No `${state.issue}`, no `$(...)`.

### 4.2 Sub-agent type

All stage sub-agents use `subagent_type: general-purpose`. Per `00-common-contracts.md` §13 (R5 verified), this type can invoke the Skill tool — load-bearing for `stage_implement`'s `/code-review` + `/security-review` calls.

### 4.3 What stages spawn what

| state.stage | File | Returns advance to |
|---|---|---|
| `analyze` | `atoms/stage_analyze.md` | `design` (or `done` on NO_ACTION) |
| `design` | `atoms/stage_design.md` | `implement` (SINGLE or CHILDREN) |
| `implement` | `atoms/stage_implement.md` | `test` (or PARENT_STOP for parents) |
| `test` | `atoms/stage_test.md` | `done` (or `implement` on QA fail) |

Typical chain: `analyze → design → implement → test → done`. Parent Issues stop at `implement` (PARENT_STOP).

---

## 5. State transitions

After each stage return, main session parses `>>> RESULT <<<` and decides next action per `01-sub-agent-contract.md` §2.

### 5.1 Parse and dispatch

```
def apply_advance(state, result):
    parts = parse_result_line(result.line)

    if parts.status == "OK ADVANCE":
        state.stage = parts.next_stage
        if "BRANCH" in parts.fields: state.branch = parts.fields["BRANCH"]
        if "PR"     in parts.fields: state.pr_num = int(parts.fields["PR"])
        if "CHILDREN" in parts.fields:
            for c in parts.fields["CHILDREN"]:
                if c not in SEEN:
                    QUEUE.append(c); SEEN.add(c); TOTAL += 1
        state.resume_hint = None

    elif parts.status == "OK NO_ACTION":      state.stage = "done"
    elif parts.status == "OK PARENT_STOP":    state.stage = "done"  # FSM-locally
    elif parts.status == "OK BACK_TO_IMPLEMENT": state.stage = "implement"
    elif parts.status == "OK PAUSE":          state.stage = "done"  # FSM-locally
    return state
```

### 5.2 Skip-review auto-advance

In `/sdd auto`, skip-review is pre-set to `analyze,design,implement,pr,qa` (Phase 3.1 step 3). Per `01-sub-agent-contract.md` §4, **main session reads `.github/.sdd-config`** to decide auto-advance.

Because `/sdd auto` writes all five keys, every gate auto-passes inside stage sub-agents (no `OK PAUSE` returns) and the FSM advances without `AskUserQuestion` calls.

For `/sdd resume <N>` standalone, skip-review may be partial. Main session asks `"Resume from <stage>? [y/N]"` between stages where the gate is not set, matching `spec/flow/resume.md` §4.

### 5.3 Children enqueue from `OK ADVANCE: implement CHILDREN: ...`

Per `01-sub-agent-contract.md` §2, when `stage_design` returns `OK ADVANCE: implement CHILDREN: #A,#B,#C`:

1. Main parses the list; for each not in `SEEN`: append to `QUEUE`, add to `SEEN`, increment `TOTAL`, print `+ Discovered child Issue #<N> → queued (total now <TOTAL>)`.
2. Main sets `state.stage = "implement"` so the next spawn is `stage_implement` for the parent — which returns `OK PARENT_STOP` (parent has just-created children with `sdd:children:output`).

Per `00-common-contracts.md` §1: parent's `sdd:implement` → `sdd:test` transition happens later, when the last child's `stage_test` detects all siblings done and promotes the parent. Bootstrap then routes the parent to `test` on the next `/sdd auto` iteration.

---

## 6. Escalation flow

ESCALATE is **new in Arch B** — in current architecture, the escalation user prompt is inline in stage orchestrators. In Arch B, stage sub-agents cannot ask the user (`AskUserQuestion` is main-session-only), so they surface the decision via the `>>> RESULT <<<` envelope.

### 6.1 Trigger

Inside a stage sub-agent: Round 3 AI review FAIL **AND** skip-review for that gate is OFF. Only reachable from `/sdd resume` standalone or `/sdd batch` child (which has `qa` outside skip-review). `/sdd auto` has all five keys set — ESCALATE should not occur.

### 6.2 Sub-agent return

```
>>> RESULT <<<
ESCALATE: <stage> round 3 FAIL — findings: [critical] X, [major] Y
```

Round 3 reviewer comments already persisted to the Issue (Section F of `_review_helpers.md`) before return — user reads them on GitHub.

### 6.3 Main session handler

Per `01-sub-agent-contract.md` §6:

```
1. Print <summary> verbatim.
2. AskUserQuestion: 3 options — Continue / Pause / Stop.
3. Continue → state.resume_hint = "continue-after-escalation"; re-spawn stage_<X>.
   Pause    → print "Resume later with /sdd resume #<N>"; break inner loop.
   Stop     → break outer loop; goto cleanup.
```

### 6.4 Resume-after-escalation hint

Per `01-sub-agent-contract.md` §3, on re-spawn with `Retry: continue-after-escalation`:

- Skip Round 1 work atom (already posted).
- Skip review rounds (already done; latest verdict FAIL on GitHub).
- Go directly to Phase 6 (output + label transition); findings persist for human follow-up.
- Return `OK ADVANCE: <next-stage>` so the FSM continues.

This is the only "deferred user decision" pattern in Arch B. The synchronous user prompt buried in current orchestrators moves to the main session as the price of main-session-thinning.

---

## 7. `/sdd batch` in Arch B

### 7.1 What changes: almost nothing

`/sdd batch` is **mostly unchanged**:

- Generates `.github/.sdd-batch.sh` from shell template (per `spec/flow/batch.md` §7).
- Executes in background via Bash `run_in_background: true`.
- Uses shell `trap cleanup EXIT INT TERM` for robust cleanup (the "killer feature" vs `/sdd auto`).
- Logs per-Issue to `.github/.sdd-batch-logs/issue-<N>-<timestamp>.log` (stream-json).
- Invokes each child: `claude -p --verbose --output-format stream-json --dangerously-skip-permissions "/sdd resume <N>"`.
- Aggregates cost + tokens via jq.
- Self-deletes via `rm -f "$SCRIPT_PATH"` in trap.

Reason: the shell script is the **outer** orchestration layer. Each `claude -p` child is a fresh Claude Code session running Arch B internally — opaque to the script.

### 7.2 What changes: inside each `claude -p` child

Each `claude -p` invocation starts with `/sdd resume <N>`. The child:

1. Reads new thin `commands/resume.md` (§8).
2. Runs **the same FSM as `/sdd auto`'s loop body** — bootstrap → stage chain → done.
3. Exits when FSM reaches `done` for that single Issue.

Differences vs `/sdd auto` iteration:

| Axis | `/sdd auto` per-Issue | `/sdd batch` child |
|---|---|---|
| Process | In-session iteration | Fresh `claude -p` subprocess |
| Skip-review | 5 keys (`analyze,design,implement,pr,qa`) | 4 keys (no `qa`) — batch script writes this |
| User prompts | Possible (sandbox pre-loop) | Never (`--dangerously-skip-permissions` + skip-review) |
| Cleanup on Ctrl-C | Weak (try/finally) | Strong (shell `trap`) |
| Logs | In-transcript | Per-Issue stream-json files |

### 7.3 Batch skip-review (4 keys, not 5)

Per `spec/flow/batch.md` §5: shell template writes `skip-review: analyze,design,implement,pr` — **no `qa`**. Rationale: batch stops at PR creation; human reviews PRs and runs QA manually after.

In Arch B: when bootstrap routes to `stage_test`, the child's `qa` gate inside `stage_test` is NOT in skip-review. `stage_test` returns `OK PAUSE` (manual QA would normally ask user; `--dangerously-skip-permissions` is for tool permissions, not skip-review). Main session in child sees `OK PAUSE`, exits FSM, child exits cleanly. Next Issue in queue gets fresh `claude -p`.

[PRESERVE]: 4-vs-5-keys contract gap is the contractual difference between auto and batch.

### 7.4 Phases that are unchanged

Per `spec/flow/batch.md`, every section is preserved verbatim: §2 security note (`--dangerously-skip-permissions` + audit log), §3 worktree recommendation (`COMMON_DIR` vs `GIT_DIR` detection), §4 argument parsing, §5/§6 canonical Phase 1/2 (shared with auto), §7 template structure (header, setup, trap, queue + retry loop with rate-limit detection), §8 child auto-discovery in script (jq inside generated `bash`; `${ISSUE}` allowed because heuristic does not apply to OS-spawned shells), §9 logs + stats aggregation (`bc` for cost, jq for tokens), §10 script lifecycle, §11 edge cases (rate-limit, permission denials, crash, `gh` not authenticated, `bc` missing, macOS vs GNU date).

Shell template (~250 lines in `commands/batch.md`) unchanged. The `[IMPROVE]` extraction to `templates/batch-runner.sh.tpl` is orthogonal to Arch B — decision deferred.

---

## 8. `/sdd resume` in Arch B

### 8.1 New shape: thin command file

Per `02-file-layout.md`: `commands/resume.md` becomes a thin dispatcher delegating to bootstrap + stage chain. The new body (~30 lines pseudocode):

```
# Phase 0: validate
gh issue view $1 --json url --jq .url
  → /pull/   → stop "PR not Issue"
  → empty    → stop "not found"
  → /issues/ → continue

# Phase 1: bootstrap
boot = spawn bootstrap($1)
if boot.status == "FAIL": print boot.reason; stop
if boot.stage == "done":  print "Issue is already complete."; stop

# Phase 2: reporting block
print f"Issue #{$1}: {boot.title}"
print f"Current stage: {boot.stage}"
print f"Resuming from: {boot.resume_point}"

# Phase 3: stage chain (same as /sdd auto inner loop)
state = { issue: $1, stage: boot.stage, depth: boot.depth,
          branch: boot.branch, pr_num: boot.pr_num, parent: boot.parent }
while state.stage != "done":
    result = spawn stage_<state.stage>(state)
    handle result per §5/§6

print "Issue #{$1}: complete."
```

### 8.2 User-facing behavior: identical

Per `spec/flow/resume.md` §1-6, unchanged: same dispatch table (label + markers + PR state → next stage), same parent-Issue handling (child progress check, silent-stop in skip-review mode), same skip-review handling per gate, same idempotent re-entry semantics, same reporting block, same Issue validation.

### 8.3 Single-Issue vs auto-loop use

`/sdd resume <N>` is callable two ways:

1. **Direct user invocation**: runs bootstrap + stage chain end-to-end.
2. **NOT recursively from `/sdd auto`'s loop**. Auto's loop body **does not** read `resume.md` inline — it directly spawns bootstrap + stage_<X>. This is the key Arch B change.

In current architecture, auto.md → resume.md → stage orchestrator inline (3 levels). Arch B collapses to: auto.md → bootstrap (sub-agent) + stage_X (sub-agent). resume.md remains as a standalone command for single-Issue resume, but auto.md no longer routes through it.

[PRESERVE]: user-facing behavior of `/sdd resume <N>` identical. Only the call graph changes.

### 8.4 `/sdd resume` inside `/sdd batch` child

Per §7.2, each `claude -p` child runs `/sdd resume <N>`. Inside the child: read `commands/resume.md` → spawn bootstrap → spawn stage_<X> per FSM → exit on `done` (or `PAUSE` for QA stop). Same path as direct user invocation. The batch script does not need to know about Arch B internals.

---

## 9. Error handling

### 9.1 Stage FAIL

Sub-agent returns `>>> RESULT <<<\nFAIL: <reason>`. Main:

1. Increment `FAILED`; append `(state.issue, reason)` to `FAILED_ROWS`.
2. Break inner `while state.stage != "done"` loop.
3. Continue outer `while QUEUE not empty` with next Issue.

[PRESERVE]: failure tolerance from `spec/flow/auto.md` §7 step 5.

In `/sdd resume` standalone, FAIL exits the command with reason printed.

### 9.2 Stage ESCALATE

See §6. Reachable only from `/sdd resume` standalone or `/sdd batch` child.

### 9.3 Stage PAUSE

`OK PAUSE` → print "Issue paused by user." → exit inner stage loop. In `/sdd auto`, loop continues to next Issue. In `/sdd resume`, command exits with resume hint.

### 9.4 Bootstrap FAIL

Same as stage FAIL — record, continue to next Issue (auto) or exit (resume).

### 9.5 Crash recovery

Per `spec/flow/auto.md` §11 and `spec/edge-cases.md` §7:

- **Hard kill mid-loop**: Phase 3.4 cleanup does not run. `.sdd-config.bak` left behind. User manually `mv .github/.sdd-config.bak .github/.sdd-config` per recovery hint. Re-run `/sdd auto <remaining-numbers>`; bootstrap re-detects each Issue's stage from on-GitHub state.
- **Soft cleanup** (normal exit or user-cancel): Phase 3.4 runs.
- **Mid-stage sub-agent crash**: stage sub-agent dies; main receives a tool error. Treated as `FAIL: stage sub-agent crashed`. Loop continues; user can `/sdd resume <N>` later.

[PRESERVE]: GitHub-as-state-of-record from `00-common-contracts.md` §2.

### 9.6 Bash heuristic prompts during loop

If user declined sandbox toggle (Phase 3.1 step 5), sandbox-bypass prompts may fire during the loop. Unchanged from `spec/flow/auto.md` §6.5 step 6. Prompts surface in the main session (Bash calls happen there — stage sub-agents inherit main-session permission state).

---

## 10. Cleanup invariant

**Ordering invariant** (from `spec/edge-cases.md` §7 / GAP-A6, **load-bearing**): Cleanup MUST be the **FIRST step** after the loop exits or after an in-loop fatal. Any post-loop reporting, summary printing, sandbox status logging, or token telemetry that runs **before** cleanup risks leaving a stale `.github/.sdd-config` on disk if the reporting code itself errors.

### 10.1 "First step" in Arch B FSM

In the FSM pseudocode (§1.2), `cleanup()` must run before the `print_summary()` block:

```
# After outer while QUEUE loop exits:
cleanup()              # Phase 3.4 — FIRST
print_summary()        # Phase 3.5 — AFTER cleanup
```

On any in-loop fatal (Stop from ESCALATE, hard error in sandbox toggle path before exit):

```
cleanup()              # FIRST
print_partial_summary()
exit
```

Cleanup steps themselves (§1.8): restore `.sdd-config` from `.bak`, or delete `.sdd-config`; re-read settings file; show disabled-state notice if `sandbox.enabled == false`.

### 10.2 What cleanup does NOT do in Arch B

Cleanup is **identical to current architecture**. The Arch B change is purely in Phase 3.2 (loop body). Pre-loop setup, cleanup, and final summary all run in the main session with the same code as today.

Cleanup does NOT modify the sandbox setting (only step 5e of Phase 3.1 writes it; that path exits before the loop), cancel running stage sub-agents (sub-agents are leaves; they complete before cleanup), or delete `.github/.sdd-auto.bak` (sandbox snapshot is intentionally persistent — user restores manually).

### 10.3 Mid-cleanup failure and hard-kill

Per `spec/flow/auto.md` §9 [RETHINK]: no defensive handling for mid-cleanup failures. Decision deferred — Arch B preserves current behavior (best-effort cleanup, manual recovery hint).

Hard-kill (SIGKILL / Cmd-Q / terminal close) → cleanup does not run. Recovery hint from Phase 3.1 step 6 is the only safety net. `/sdd batch` does not have this limitation because shell `trap` catches EXIT/INT/TERM — only SIGKILL bypasses it.

---

## Cross-references

- Architecture → `00-architecture.md` (§2 main session FSM, §3 stage sub-agent shape)
- Sub-agent return envelope → `01-sub-agent-contract.md` (§2 status keywords, §3 ESCALATE, §7 bootstrap)
- File layout → `02-file-layout.md` (commands + atoms split)
- Per-stage internal design → `stage-designs/*.md`
- Common contracts → `spec/00-common-contracts.md` (§6 result contract, §8 bash rules, §9 comment posting, §12 single-level spawn)
- Edge cases → `spec/edge-cases.md` (§1 multilingual regex, §7 recovery, GAP-A6 cleanup ordering)
- Source flow specs → `spec/flow/auto.md`, `spec/flow/batch.md`, `spec/flow/resume.md`
