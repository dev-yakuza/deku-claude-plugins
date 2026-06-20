# Flow: Batch

Out-of-session batch processing of multiple Issues through the SDD pipeline. Sources: `commands/batch.md`.

---

## 1. Architectural Differences vs `/sdd auto` [PRESERVE]

See `spec/flow/auto.md` §1 for the side-by-side comparison and the post-2026-06-15 billing-pool rationale. Batch-specific architecture:

- Generates a **self-deleting shell script** (`.github/.sdd-batch.sh`) and executes it in the **background** via the Bash tool with `run_in_background: true`.
- Each Issue runs in a **fresh `claude -p` child session** with `--dangerously-skip-permissions`. Inside the child, `/sdd resume <N>` dispatches to the appropriate stage orchestrator, which spawns atoms — still single-level per `00-common-contracts.md` §12.
- Cleanup is **strong** because the shell script uses `trap cleanup EXIT INT TERM` — Ctrl-C, kernel kill, normal exit all run the same cleanup function.
- Per-Issue logs are streamed to `.github/.sdd-batch-logs/issue-<N>-<timestamp>.log` in `stream-json` format, enabling post-hoc cost / token aggregation via jq.
- The Claude Code app can be **closed after kicking off the batch** — the script runs entirely in the background as an OS-level process.

[PRESERVE: the script-based architecture is what enables Cmd-Q safety and walk-away unattended runs. Cannot be replicated in `/sdd auto`.]

[IMPROVE: the script template embedded in `commands/batch.md` Phase 3 is ~250 lines. Extract to a separate template file (`templates/batch-runner.sh.tpl`) and have the command render placeholders. Editing the script today requires editing inside the Markdown command file, which fights syntax highlighting and makes lints impossible.]

---

## 2. Security Note [PRESERVE — load-bearing]

The generated batch script invokes each child session with `--dangerously-skip-permissions`. This bypasses **all** permission prompts and sandbox boundaries in the child session, so test runners (e.g. `flutter test`), commit hooks, and `git push` / `gh pr create` can execute unattended. Use `/sdd batch` only when you accept that the child sessions may run any tool without prompting.

Mitigation: all tool calls are recorded in `.github/.sdd-batch-logs/<issue>-<timestamp>.log` (stream-json) for audit.

[PRESERVE: the `--dangerously-skip-permissions` flag is the only way to make `claude -p` truly unattended for subagent-heavy workflows; the audit log is the compensating control.]

---

## 3. Worktree Recommendation (detection logic) [PRESERVE]

Because child sessions execute with elevated permissions and may switch branches, stash, or run pre-commit hooks, **strongly consider running `/sdd batch` from a dedicated git worktree**.

### Rationale [PRESERVE]

A separate worktree gives the batch its own working tree, index, HEAD, and stash stack. Any mishaps (mis-stashed config, dirty working tree carried across Issues, accidental file deletion) stay isolated and recoverable by simply removing the worktree.

### Suggested flow (shown to user during confirmation) [PRESERVE]

```
git worktree add ../<repo>-batch main        # or any base branch
cd ../<repo>-batch
# ... run /sdd batch from here ...
# When the batch is finished and PRs are reviewed:
cd ../<repo>
git worktree remove ../<repo>-batch
```

### Detection [PRESERVE]

During Phase 1 confirmation, detect whether the current directory is a dedicated worktree:

```
COMMON_DIR=$(git rev-parse --git-common-dir)
GIT_DIR=$(git rev-parse --git-dir)
```

If `COMMON_DIR` equals `GIT_DIR` (or both resolve to the same absolute path) → user is in the **main checkout**, not a worktree.

In that case, append to the confirmation summary:

```
⚠ Workspace: main checkout detected (not a worktree).
  Recommended: run this batch from a worktree to isolate the working tree.

      git worktree add ../<repo>-batch <base-branch>
      cd ../<repo>-batch

  Proceed in the main checkout anyway? [y/N]
```

- User says no → stop without generating the script.
- User says yes → continue.
- Already in a worktree → skip the warning, ask only the standard confirmation.

[PRESERVE: recommendation-not-requirement is intentional — some teams have CI / repo policies that disallow worktrees.]

[RETHINK: `git rev-parse --git-common-dir` is in a `2>/dev/null` redirect in the source. Per `00-common-contracts.md` §8, `2>/dev/null` is forbidden inside the in-session dispatcher path. The source command embeds this in the generated `.sdd-batch.sh` runtime script, not in a Claude-tool call, so the rule does not apply at script generation time. Make the boundary explicit in the rewrite.]

---

## 4. Argument Parsing [PRESERVE — shared with auto]

Parse `$1`:
- Empty or not provided → **All open Issues** mode
- Comma-separated numbers (e.g. `1,2,3`) → **Specific Issues** mode

---

## 5. Phase 1: Collect and Filter Issues [PRESERVE — canonical source]

This is the **canonical Phase 1** that `/sdd auto` re-uses verbatim.

### All-open mode
1. `gh issue list --state open --json number,title,labels --limit 200`
2. **Exclude** `sdd:done` (already completed).
3. **Exclude** `sdd:child` (auto-discovered after parent runs).
4. **Include** all remaining.
5. Sort by Issue number ascending.

### Specific-Issues mode
1. For each number: `gh issue view <n> --json number,title,labels,state`.
2. Validate each exists and is open. Closed or missing → warn and exclude.
3. **Exclude** `sdd:done` (warn the user the listed Issue is already done).
4. **Include** `sdd:child` (user explicitly chose them — respect intent).
5. **Include** all remaining.
6. Sort by Issue number ascending.

Empty post-filter → "No qualifying Issues found." stop.

**Auto-discovery note**: regardless of mode, the generated script will auto-discover child Issues during a parent's processing (via `<!-- sdd:children:output -->` marker / `Parent Issue: #<n>` reference per `02-multilingual.md` §3) and append them to the queue.

### Confirmation block (batch-specific)

```
SDD Batch Processing
════════════════════
Issues to process (in order):

  #10: Add user authentication       [new]
  #11: Fix pagination bug             [sdd:design]
  #12: Refactor logging module        [sdd:implement]

Total: 3 issues (queue may grow as parent Issues spawn children)
Mode: Sequential (each in a separate claude -p session)
Skip-review: analyze, design, implement, pr, qa (auto-enabled — runs through sdd:done)
Child auto-queue: enabled
```

Stage label: no SDD label → `[new]`; SDD label → show it.

Then run the Workspace check (§3) and append the worktree warning if applicable.

### Skip-review alignment with auto [PRESERVE — critical]

Batch writes `skip-review: analyze,design,implement,pr,qa` (5 keys — same as `/sdd auto`). Rationale: batch runs unattended through QA to `sdd:done`; the human reviews PRs and QA evidence on GitHub after the batch completes.

`/sdd auto` also writes 5 keys (`analyze,design,implement,pr,qa`) for the same reason — both commands are designed to run fully unattended.

[PRESERVE: batch and auto now use the same 5-key skip-review. There is no longer a 4-vs-5-key distinction between the two commands.]

---

## 6. Phase 2: Verify Tool Permissions [PRESERVE — canonical source]

This is the **canonical Phase 2** that `/sdd auto` re-uses (with display-string deltas, per `spec/flow/auto.md` §5).

### Preamble note [PRESERVE — batch-only]

`claude -p` sessions need tool permissions pre-configured in `.claude/settings.local.json`. The generated script also passes `--dangerously-skip-permissions` to each child, which bypasses prompts and sandbox boundaries at runtime. The permissions registered here are still useful as a documented allowlist (and as a fallback if the user removes the flag), but they are **not strictly required** for the script to run unattended once the flag is in place. Treat the items below as the recommended baseline.

### Workflow [PRESERVE]

1. Read `.claude/settings.local.json` if it exists.
2. Check which permissions from the three groups are already present (exact match only — scoped `Edit(/path/**)` does NOT satisfy unscoped `Edit`).
3. **Detect project type** via repo-root markers (Read/Glob; never shell out for this):

   | Marker file/dir | Pre-select |
   |---|---|
   | `pubspec.yaml` | `Bash(flutter:*)`, `Bash(dart:*)` |
   | `.fvm/` or `.fvmrc` | `Bash(fvm:*)` |
   | `package.json` | `Bash(npm:*)`, `Bash(npx:*)` |
   | `yarn.lock` | `Bash(yarn:*)` |
   | `pnpm-lock.yaml` | `Bash(pnpm:*)` |
   | `pyproject.toml`, `requirements.txt`, `setup.py`, `Pipfile` | `Bash(pytest:*)` |
   | `go.mod` | `Bash(go:*)` |
   | `Cargo.toml` | `Bash(cargo:*)` |
   | `Makefile` | `Bash(make:*)` |

4. Show the three-group UI per `01-config.md` §7:
   - **[Required]** — SDD pipeline fails without these: `Read`, `Edit`, `Write`, `Bash(gh:*)`, `Bash(git:*)`.
   - **[Recommended]** — `Grep`, `Glob`, `Agent`, `WebSearch`.
   - **[Test Runners]** — pre-selected based on detected markers; toggle as needed.
5. Ask user which items to toggle. Empty input → continue with pre-selection.
6. On confirmation → create or merge into `.claude/settings.local.json` preserving existing entries.
7. On rejection → warn that batch script may fail without permissions, but continue with script generation.

[PRESERVE: matching rule, exact unscoped, and the "Bash unscoped overrides all" shortcut.]

[IMPROVE: marker→permission map is duplicated between `auto.md` and `batch.md` source. Move to `01-config.md` §7 single source of truth; both commands import.]

---

## 7. Phase 3: Generate Batch Script [IMPROVE — extract template] 

Generate `.github/.sdd-batch.sh` from a template. Currently the template is inlined in `commands/batch.md` (lines 199–448, ~250 lines).

[IMPROVE: extract to a template file (e.g. `templates/batch-runner.sh.tpl`) with `<ISSUE_NUMBERS>` placeholder. Lints and syntax-highlights properly; keeps the Markdown command file readable. The rewrite should treat the template as a first-class artifact, not embedded prose.]

### Template structure

The template has five blocks, each with its own contract.

#### 7.1 Header + variables [PRESERVE]

```
#!/usr/bin/env bash
set -euo pipefail

ISSUES=(<ISSUE_NUMBERS>)
LOG_DIR=".github/.sdd-batch-logs"
CONFIG_FILE=".github/.sdd-config"
CONFIG_BACKUP=".github/.sdd-config.bak"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
```

`<ISSUE_NUMBERS>` is the space-separated list from Phase 1.

[PRESERVE: `set -euo pipefail` is the bash strict-mode contract; without it, jq parse errors silently corrupt the loop.]

#### 7.2 Setup block [PRESERVE]

- `mkdir -p "$LOG_DIR"`.
- Resolve `OWNER_REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner ...)`. Empty → warn, disable child auto-discovery.
- **`.git/info/exclude` protection** (idempotent): append `.github/.sdd-batch.sh`, `.github/.sdd-config`, `.github/.sdd-config.bak` if not already present. Rationale: subagents may stash untracked files when switching branches; without these entries, the batch infrastructure can disappear into a stash mid-run, breaking skip-review detection.
- Back up `.sdd-config` to `.sdd-config.bak` if it exists.
- Write `skip-review: analyze,design,implement,pr,qa` to `.sdd-config`.

[PRESERVE: stash-protection rationale and the use of `.git/info/exclude` (not `.gitignore`) so the user's tracked `.gitignore` is unmodified.]

#### 7.3 Cleanup trap [PRESERVE — load-bearing]

```
SCRIPT_PATH="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
cleanup() {
  if [ -f "$CONFIG_BACKUP" ]; then
    cp "$CONFIG_BACKUP" "$CONFIG_FILE"
    rm -f "$CONFIG_BACKUP"
  else
    rm -f "$CONFIG_FILE"
  fi
  rm -f "$SCRIPT_PATH"
}
trap cleanup EXIT INT TERM
```

- Restores or deletes `.sdd-config` based on whether a `.bak` exists.
- **Self-deletes** the batch script via `rm -f "$SCRIPT_PATH"`. Combined with the `EXIT INT TERM` trap, this ensures the script disappears even on Ctrl-C / TERM signals.

[PRESERVE: cleanup robustness here is the BIG advantage over `/sdd auto`. Ctrl-C, kernel signal, normal completion all run the same cleanup.]

[RETHINK: SIGKILL (`kill -9`) bypasses traps. Same hard-kill limitation as `/sdd auto`. Worth a comment in the rewritten template.]

#### 7.4 Queue + process loop [PRESERVE]

State variables:
- `BATCH_START=$(date +%s)` — for elapsed wall time.
- `ERROR_LOG="$LOG_DIR/errors-${TIMESTAMP}.log"` — single consolidated error log.
- `SUCCEEDED=0`, `FAILED=0`, `FAILED_ISSUES=()`.
- `QUEUE=("${ISSUES[@]}")` — bash array, FIFO.
- `SEEN=" #N1 #N2 ... "` — space-padded membership tokens for simple `case` matching.
- `TOTAL_TARGETS=${#ISSUES[@]}`, `PROCESSED_COUNT=0`.

**Per-Issue flow** (`while [ ${#QUEUE[@]} -gt 0 ]; do`):

1. Pop `ISSUE=${QUEUE[0]}`; shift via `QUEUE=("${QUEUE[@]:1}")`.
2. Increment `PROCESSED_COUNT`. Compute `LOG_FILE="$LOG_DIR/issue-${ISSUE}-${TIMESTAMP}.log"`.
3. Print progress `[$PROCESSED_COUNT/$TOTAL_TARGETS] Processing Issue #$ISSUE...`.
4. **Inner retry loop** (`while true; do`):
   - Invoke `claude -p --verbose --output-format stream-json --dangerously-skip-permissions "/sdd resume $ISSUE" > "$LOG_FILE" 2>&1`, capture exit code with `|| EXIT_CODE=$?`.
   - On exit 0 → success path (§7.4.a).
   - On non-zero → rate-limit detection (§7.4.b). If rate-limited → wait + retry. Else → failure path (§7.4.c).

##### 7.4.a Success path [PRESERVE]
- Increment `SUCCEEDED`. Print ✓.
- **Child auto-discovery** (next subsection §7.5).
- `break` out of the retry loop.

##### 7.4.b Rate-limit detection [PRESERVE — jq parsing]

Two-stage extract:

```
RESET_AT=$(jq -r 'select(.type == "rate_limit_event") | .rate_limit_info | select(.status != "allowed") | .resetsAt // empty' "$LOG_FILE" | tail -1)
```

If empty AND grep finds rate-limit keywords (`rate.limit | overloaded | too many requests`):

```
RESET_AT=$(jq -r 'select(.type == "rate_limit_event") | .rate_limit_info.resetsAt // empty' "$LOG_FILE" | tail -1)
```

If `RESET_AT` is non-empty:
- `NOW=$(date +%s)`, `WAIT=$((RESET_AT - NOW + 30))` (30-second cushion).
- `RESET_TIME=$(date -r "$RESET_AT" +%H:%M:%S || date -d "@$RESET_AT" +%H:%M:%S)` (macOS vs GNU `date` fallback).
- Print "Rate limited. Waiting until ~$RESET_TIME ($WAIT_MIN m $WAIT_SEC s)...".
- `sleep "$WAIT"`. `continue` (re-enter the inner retry loop for the same Issue).

[PRESERVE: rate-limit retry is the only retry the batch script does — it preserves billing predictability while waiting out the limit.]

##### 7.4.c Failure path [PRESERVE]
- Increment `FAILED`, append `ISSUE` to `FAILED_ISSUES`.
- Append to `$ERROR_LOG`:
  - Issue number + timestamp banner.
  - Exit code.
  - Permission denials: `jq -r 'select(.type == "result") | .permission_denials[]?'`.
  - Error message: `jq -r 'select(.type == "result") | select(.is_error == true) | .result // empty' | tail -1`.
- `break` out of the retry loop. Continue to next Issue.

[PRESERVE: failure tolerance — same contract as `/sdd auto`.]

---

## 8. Phase 3 (continued): Child Auto-Discovery in Script [PRESERVE]

After a successful Issue inside §7.4.a, the script appends:

```
CHILDREN=$(gh issue list --repo "$OWNER_REPO" \
  --label sdd:child --state open --limit 200 \
  --json number,body \
  --jq "[.[] | select(.body | test(\"(Parent|상위 |親)Issue: #${ISSUE}([^0-9]|\$)\"))] | .[] | .number" \
  2>/dev/null || true)
for CHILD in $CHILDREN; do
  case "$SEEN" in
    *" #$CHILD "*) ;;
    *)
      SEEN="$SEEN #$CHILD "
      QUEUE+=("$CHILD")
      TOTAL_TARGETS=$((TOTAL_TARGETS + 1))
      echo "  + Discovered child Issue #$CHILD → queued (total now $TOTAL_TARGETS)"
      ;;
  esac
done
```

### Notes [PRESERVE]
- Inside the generated shell script (not the in-session dispatcher), `${ISSUE}` inside a double-quoted argument is allowed — Claude Code's expansion-obfuscation heuristic only applies when *Claude* invokes Bash, not at runtime inside an OS-spawned `bash`.
- The `2>/dev/null || true` swallows transient `gh` errors so a single failed lookup does not abort the loop.
- The `case "$SEEN" in *" #$CHILD "*) ;;` pattern is the membership check; the surrounding spaces prevent `#683` matching `#6831` token-wise.
- The regex `(Parent|상위 |親)Issue: #<N>([^0-9]|$)` is the canonical multilingual parent reference per `02-multilingual.md` §3.

[PRESERVE: contrast with `/sdd auto` §3.3 where the literal Issue number must be substituted at Claude-call time — that constraint does not apply inside the script.]

---

## 9. Logs and Stats Aggregation [PRESERVE]

After the loop, jq across all `issue-*-${TIMESTAMP}.log` files extracts per-Issue final `result` event:

```
STATS=$(jq -r 'select(.type == "result") | "\(.usage.input_tokens // 0) \(.usage.output_tokens // 0) \(.usage.cache_read_input_tokens // 0) \(.usage.cache_creation_input_tokens // 0) \(.total_cost_usd // 0)"' "$LOG" | tail -1)
```

Sum across all logs:
- `TOTAL_INPUT`, `TOTAL_OUTPUT`, `TOTAL_CACHE_READ`, `TOTAL_CACHE_CREATE`, `TOTAL_COST`.
- `TOTAL_CONTEXT = TOTAL_INPUT + TOTAL_OUTPUT + TOTAL_CACHE_READ + TOTAL_CACHE_CREATE`.

Use `bc` for floating-point cost accumulation (`TOTAL_COST=$(echo "$TOTAL_COST + $COST" | bc)`).

### Summary block printed at script end [PRESERVE]

```
============================================================
  SDD Batch Complete
============================================================
  Total:     $TOTAL
  Succeeded: $SUCCEEDED
  Failed:    $FAILED
  [if any] Failed: ${FAILED_ISSUES[*]}
  [if any] Error log: $ERROR_LOG

  Time:      ${BATCH_MIN}m ${BATCH_SEC}s
  Cost:      $${TOTAL_COST}
  Tokens:    <total>
               in: <in>  out: <out>
               cache read: <cr>  cache create: <cc>

  Logs: $LOG_DIR/
============================================================
```

[PRESERVE: cost + token summary is the BIG observability advantage over `/sdd auto`.]

[IMPROVE: `printf "%'d"` is locale-dependent for thousands separators. Force `LC_ALL=C` or use a portable formatter. Currently works on most macOS/Linux locales but is brittle.]

---

## 10. Script Lifecycle [PRESERVE]

After writing the script via the Write tool:

1. **`chmod +x .github/.sdd-batch.sh`** via Bash.
2. **Check `.gitignore`** for `.github/.sdd-batch-logs/`. If not listed → suggest adding it (ask user).
3. **Execute in background** via the Bash tool with `run_in_background: true`:
   ```
   bash .github/.sdd-batch.sh
   ```
4. **Report to user**: kickoff confirmation with:
   - Issue count.
   - Log directory path.
   - 3-line behavior summary (process sequentially / restore config on Ctrl-C / self-delete).
   - "You will be notified when the batch finishes."
   - Real-time monitoring snippet (`tail -f .github/.sdd-batch-logs/issue-<N>-*.log | jq ...`).
5. **When background completes**: read final log entries, report results (per-Issue ✓/✗ and aggregate).

[PRESERVE: background + self-delete + restart-safe (via trap) is the full Cmd-Q-safe contract.]

[IMPROVE: the `tail -f ... | jq ...` snippet shown to the user is intricate — a parsed log viewer skill (e.g. `/sdd watch`) would be more discoverable. Defer.]

---

## 11. Edge Cases [PRESERVE]

### Rate limit [PRESERVE]
Handled by the inner retry loop §7.4.b. Mechanism:
- Parse `rate_limit_event` JSON from the stream log.
- Wait until `resetsAt` + 30s cushion.
- Re-invoke `claude -p` for the same Issue.

[PRESERVE: rate-limit retry is graceful and unbounded — the script will wait however long the API tells it to.]

### Permission denials in child session [PRESERVE]
- `--dangerously-skip-permissions` should suppress permission prompts, but if `permissions.deny` is set in `settings.json` it can still produce `permission_denials` in the `result` event.
- The failure path §7.4.c extracts these into `$ERROR_LOG` for post-hoc review.

### Crash mid-loop [PRESERVE — trap-safe]
- Ctrl-C, SIGTERM → cleanup trap fires → `.sdd-config` restored, script self-deletes.
- SIGKILL / kernel kill → trap bypassed; user must manually:
  - `mv .github/.sdd-config.bak .github/.sdd-config` (if `.bak` exists).
  - `rm -f .github/.sdd-batch.sh`.

### `gh` not authenticated [PRESERVE]
- `gh repo view --json nameWithOwner` returns empty.
- Setup block warns and disables child auto-discovery for the run.
- The `claude -p` sessions still launch, but per-Issue work that needs `gh` will fail inside the child and surface via the failure path.

### Empty `ISSUES` array [PRESERVE]
- Phase 1 filtering already catches this with "No qualifying Issues found." — script is never generated.

### `bc` not installed [RETHINK]
- The cost-aggregation block uses `bc` for floating-point sums. On minimal containers (`alpine`, busybox) `bc` may be missing → `TOTAL_COST=` (empty string), summary prints `Cost: $`.
- Suggested rewrite: probe `command -v bc` and degrade gracefully to integer math (sum cents, divide at print time) or `awk` (universal).

[IMPROVE: a portable arithmetic helper would let the template drop the `bc` dependency.]

### macOS vs GNU `date` [PRESERVE]
- `date -r EPOCH +FORMAT` (macOS) vs `date -d "@EPOCH" +FORMAT` (GNU) — handled by `||` fallback in §7.4.b.

[PRESERVE: this is the only portability hack in the script and it works correctly.]

---

## 12. Notes [PRESERVE]

- **0.24.0 architecture invariant**: each `claude -p` child session is a fresh main thread. Inside the child, `/sdd resume <N>` dispatches to a stage orchestrator, which spawns single-level atom subagents. Spawning is single-level per `00-common-contracts.md` §12.
- **Cleanup robustness on Ctrl-C is the killer feature**. The shell `trap` covers EXIT/INT/TERM; `/sdd auto` has nothing equivalent (in-session try/finally only).
- **Per-Issue stream-json logs enable observability** (`/cost`-style aggregation, tool-call audit, permission-denial extraction). `/sdd auto` has no equivalent.
- **Skip-review includes `qa`** — batch runs through `sdd:done` unattended, same as `/sdd auto`. Human reviews PRs and QA evidence on GitHub after batch completes.
- **Worktree recommendation** is shown but not enforced; users can decline and proceed in the main checkout.

---

## Cross-references

- Common contracts → `spec/00-common-contracts.md`
- Configuration (skip-review, allowlist baseline, `.git/info/exclude`, `.sdd-batch-logs/`) → `spec/01-config.md`
- Multilingual parent regex → `spec/02-multilingual.md` §3
- Dispatcher → `spec/flow/resume.md`
- Sibling loop command → `spec/flow/auto.md`
