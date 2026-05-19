# AUTO

**In-session sequential processing of multiple Issues through the full SDD pipeline.**

Each Issue runs end-to-end (analyze → design → implement → PR) in the **current Claude Code session** via the orchestrator/atom architecture. Unlike `/sdd batch` (which spawns separate `claude -p` subprocesses), `/sdd auto` stays entirely on the Interactive subscription pool — unchanged by the 2026-06-15 billing split that moved `claude -p` to the new metered Agent SDK Credit pool.

## When to use /sdd auto vs /sdd batch

| Axis | `/sdd batch` | `/sdd auto` |
|---|---|---|
| Execution model | Generates `.sdd-batch.sh`; each Issue runs in a fresh `claude -p` child session | Main Claude Code session loops over Issues in-process |
| Billing pool (post 2026-06-15) | Agent SDK Credit pool (metered at API list prices, no rollover) | Interactive subscription pool (unchanged) |
| Claude Code app required after start | No — close it; the shell script runs unattended | **Yes** — keep this session open until the loop completes |
| Permission prompts during run | Bypassed (`--dangerously-skip-permissions`) | Normal main-session prompts apply |
| Cleanup robustness on Ctrl-C | Strong (shell `trap`) | Weak (in-session try/finally; hard kill loses cleanup) |
| Logs | Per-Issue stream-json log files | Inline in the Claude Code transcript |
| Child Issue auto-discovery | Yes | Yes |

**Heuristic**: large queue or want to walk away → `/sdd batch`. Watching progress, want to stay on Interactive billing → `/sdd auto`.

## Practical limits

- Main-session context accumulates across Issues. Realistic ceiling depends on the complexity of each Issue's stages — measure with `/context` between Issues if running a large batch. For very large queues, prefer `/sdd batch`.
- If you interrupt the session (Cmd-Q, terminal close, kernel kill), `.github/.sdd-config` may be left in the temporary "skip everything" state. Recover with:
  ```bash
  mv .github/.sdd-config.bak .github/.sdd-config
  ```

## Input Validation

Before any other step: validate `$1` per Common Definitions → Issue Validation in `${CLAUDE_SKILL_DIR}/SKILL.md`. (For `/sdd auto`, the validation is per-Issue inside the loop — the argument here is the **list** of Issue numbers, not a single number.)

## Argument Parsing

Parse `$1`:
- Empty or not provided → **All open Issues** mode
- Comma-separated numbers (e.g. `1,2,3`) → **Specific Issues** mode

## Phase 1: Collect and Filter Issues

Apply the **same Phase 1 logic as `/sdd batch`** — see `${CLAUDE_SKILL_DIR}/commands/batch.md` "Phase 1: Collect and Filter Issues" (the All-open vs Specific-Issues filter rules, the `sdd:done` / `sdd:child` exclusion semantics, sort order, the "No qualifying Issues" early exit). Apply identical rules; the only differences are display strings and the worktree warning.

### Display: Confirmation block

Show the filtered Issue list with current stage:
```
SDD Auto (in-session sequential)
════════════════════════════════
Issues to process (in order):

  #10: Add user authentication       [new]
  #11: Fix pagination bug             [sdd:design]
  #12: Refactor logging module        [sdd:implement]

Total: 3 issues (queue may grow as parent Issues spawn children)
Mode: Sequential (each in the current main session)
Skip-review: analyze, design, implement, pr (auto-enabled — restored when loop ends)
Child auto-queue: enabled (children created by a parent are appended to the queue)
```

Determine stage label for display (same as `/sdd batch`):
- No SDD label → `[new]`
- Has SDD label → show the label (e.g. `[sdd:analyze]`)

### Worktree note

`/sdd auto` runs in-session in the user's current checkout — no separate process. The worktree recommendation from `/sdd batch` (line 9–35) does **not apply** to `/sdd auto`. However, if the working tree is dirty, warn the user:

```bash
git status --porcelain
```

If non-empty:
```
⚠ Uncommitted changes detected in the working tree.
  /sdd auto will create branches and commits per Issue. Uncommitted changes
  may interfere with branch switches.

  Proceed anyway? [y/N]
```

If the user answers no → stop without starting the loop.

### Ask for confirmation

After the Issue list (and dirty-tree warning if applicable), ask "Proceed? [y/N]". On rejection → stop.

## Phase 2: Verify Tool Permissions

Apply the **same Phase 2 logic as `/sdd batch`** — see `${CLAUDE_SKILL_DIR}/commands/batch.md` "Phase 2: Verify Tool Permissions" (project marker detection, the three permission groups: Required / Recommended / Test Runners, the merge-into-settings logic on confirmation). The recommended baseline allowlist is identical because the SDD pipeline needs the same tools whether the orchestrator runs in `claude -p` or in this main session.

### Difference from `/sdd batch`

- The preamble note about `--dangerously-skip-permissions` does **not** apply. In `/sdd auto`, normal main-session permission gates run for every tool call. The allowlist below is a recommendation; if missing, you will see permission prompts during the loop (which breaks "unattended within session").

- Display header changes to:
  ```
  Tool permissions for /sdd auto (in-session sequential)
  ════════════════════════════════════════════════════════
  ```

- The note about "claude -p sessions" should be replaced with: "Subagents inside the orchestrators inherit this main session's permissions. The Phase 1/2 confirmation flows still prompt for user input — only the per-stage AI review skipping is automated by the temporary `skip-review` override."

Everything else (the project detection table, the three permission groups, the toggle UI, the merge-into-settings flow) is identical to `/sdd batch` Phase 2 and is reused verbatim.

## Phase 3: Sequential In-Session Loop

The main session itself runs the loop. **No shell script is generated. No `claude -p` is spawned.**

### 3.1 Pre-loop setup (main session)

1. Resolve owner/repo once for child Issue discovery:
   ```bash
   OWNER_REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
   ```
   If empty → warn the user; continue but disable child auto-discovery.

2. Back up `.github/.sdd-config`:
   - Read existing `.github/.sdd-config` (if any) via the Read tool.
   - Copy its contents to `.github/.sdd-config.bak` via the Write tool (so the file exists on disk for the recovery hint).
   - If no existing `.sdd-config`, do NOT create `.sdd-config.bak`.

3. Write temporary skip-review:
   ```
   skip-review: analyze,design,implement,pr
   ```
   to `.github/.sdd-config` (via the Write tool). This makes every per-Issue stage orchestrator auto-proceed without user confirmation. `qa` is intentionally NOT included — manual QA at the end of `/sdd test` still asks the user for QA pass/fail.

4. Append `.github/.sdd-config` and `.github/.sdd-config.bak` to `.git/info/exclude` if not already present (idempotent check), so subagents' `git stash -u` does not stash these files mid-run.

5. Print the recovery hint **before** entering the loop:
   ```
   If this session is interrupted, restore your config with:
     mv .github/.sdd-config.bak .github/.sdd-config
   ```

### 3.2 Loop body (main session)

Maintain in-memory state in the main session's narrative:
- `QUEUE` — ordered list of Issue numbers from Phase 1 (FIFO)
- `SEEN` — set of every Issue ever queued (prevents duplicate child enqueues)
- `TOTAL_TARGETS` — initial `len(QUEUE)`, grows when children are discovered
- `PROCESSED_COUNT` — running counter
- `SUCCEEDED` — counter
- `FAILED` — counter
- `FAILED_ISSUES` — list with `(number, reason)` tuples
- `BATCH_START` — `date +%s` at loop start, for elapsed wall time

While `QUEUE` is non-empty:

1. Pop `ISSUE` from front; increment `PROCESSED_COUNT`.
2. Print: `[$PROCESSED_COUNT/$TOTAL_TARGETS] Processing Issue #<ISSUE>...`
3. **Dispatch via resume.md** — read `${CLAUDE_SKILL_DIR}/commands/resume.md` and execute its instructions for Issue `<ISSUE>`. The dispatcher inspects Issue labels + comments + PRs, then reads + executes the appropriate stage orchestrator (`analyze.md` / `design.md` / `implement.md` / `test.md`). Because the temporary skip-review setting includes `analyze,design,implement,pr`, each orchestrator auto-advances label-by-label until the stage chain stops at `sdd:test` (post-PR) or `sdd:done` (no-action analyze, or finished test).
4. On success → mark `SUCCEEDED += 1`. Run **child auto-discovery** (3.3 below).
5. On unrecoverable failure → mark `FAILED += 1`, append `(ISSUE, <one-line reason>)` to `FAILED_ISSUES`. Continue to the next Issue — do **not** abort the entire queue.

### 3.3 Child auto-discovery

After each successful Issue, run the same `gh issue list --label sdd:child` query as `/sdd batch`'s Phase 3 logic. Use the multi-language parent-reference regex from `batch.md`:

```bash
gh issue list --repo "$OWNER_REPO" \
  --label sdd:child --state open --limit 200 \
  --json number,body \
  --jq "[.[] | select(.body | test(\"(Parent|상위 |親)Issue: #${ISSUE}([^0-9]|\$)\"))] | .[] | .number"
```

For each discovered child number not in `SEEN`:
- Append to `QUEUE`
- Add to `SEEN`
- Increment `TOTAL_TARGETS`
- Print: `+ Discovered child Issue #<N> → queued (total now $TOTAL_TARGETS)`

### 3.4 Cleanup (try/finally semantics)

Run at the end of the loop **and** on any abort (user types "cancel" during a sub-prompt, fatal error from a stage orchestrator). The cleanup MUST be the FIRST step the main session does after the loop exits or after an in-loop fatal error:

1. If `.github/.sdd-config.bak` exists:
   - Read its contents (via Read tool)
   - Write them back to `.github/.sdd-config` (via Write tool)
   - Delete `.github/.sdd-config.bak` (via Bash `rm`)
2. Else (no original config existed): delete `.github/.sdd-config` (via Bash `rm`).

> **Cleanup limitation**: If the user **hard-kills** Claude Code (Cmd-Q, terminal close, kernel kill) mid-loop, this cleanup cannot run. The on-disk `.sdd-config.bak` is left behind. The recovery hint printed at 3.1 step 5 tells the user how to manually restore.

### 3.5 Final summary

After cleanup, print:

```
SDD Auto Complete
══════════════════
Total processed: <PROCESSED_COUNT>
Succeeded:       <SUCCEEDED>
Failed:          <FAILED>
<list of failed Issues with reasons, if any>

Time:            <minutes>m <seconds>s
Config restored: .github/.sdd-config
Next steps:      review PRs, run /sdd test <N> for QA if 'qa' was not in your prior skip-review
```

Token / cost aggregation is **not** included — the main session does not have access to per-subagent usage data the way `/sdd batch`'s stream-json logs do. Users wanting cost visibility can check `/cost` in this Claude Code session.

## Notes

- **In-session execution.** Every orchestrator (`analyze.md`, `design.md`, `implement.md`, `test.md`, `resume.md`) and every atom runs in this same Claude Code session. Atoms are spawned via the Agent tool by orchestrators; the spawning layer is single-level (orchestrator → atoms), so there are no nested-subagent issues.
- **Skip-review override is temporary.** The pre-loop step writes `skip-review: analyze,design,implement,pr`; cleanup restores the original config. AI review still runs in every stage (skip-review only suppresses user-confirmation prompts).
- **Sequential only.** Parallel processing of Issues is intentionally not supported — official Claude Code docs warn that parallel subagents consume the subscription quota N× faster, which would defeat the in-session advantage.
- **Child Issue handling.** Parents stop at `sdd:implement` after design creates children (per `design.md`); the auto-discovery in 3.3 queues the children, which then progress through the full pipeline themselves.
- **Failures are tolerated.** A failure on one Issue does not abort the loop. The orchestrator records the failure and continues. The user can re-run `/sdd auto <failed-numbers>` after the run to retry.
