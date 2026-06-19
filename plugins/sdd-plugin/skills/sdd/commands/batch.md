# BATCH

**Batch process multiple Issues through the SDD pipeline in separate sessions.**

Each Issue runs in an independent `claude -p` session with skip-review enabled (analyze through PR creation), minimizing token consumption. Human reviews PRs and runs QA after batch completes.

> **v1.0.0 architecture note**: each `claude -p` child session is a fresh main thread. Inside the child, `/sdd resume <N>` spawns a single bootstrap sub-agent which spawns a single `stage_<X>` sub-agent per FSM transition (analyze → design → implement → test). The single-nesting-level invariant (main → bootstrap, main → stage) is preserved within each child session, so the v1.0.0 stage sub-agent architecture works inside `/sdd batch` unchanged. The `--dangerously-skip-permissions` flag is still required because the stage sub-agents make tool calls that would otherwise prompt in unattended runs.

> ⚠️ **Security note**: The generated batch script invokes each child session with `--dangerously-skip-permissions`. This bypasses **all** permission prompts and sandbox boundaries in the child session, so test runners (e.g. `flutter test`), commit hooks, and `git push` / `gh pr create` can execute unattended. Use `/sdd batch` only when you accept that the child sessions may run any tool without prompting. All tool calls are recorded in `.github/.sdd-batch-logs/<issue>-<timestamp>.log` for audit.

## Recommended: run in a git worktree

Because the child sessions execute with elevated permissions and may switch branches, stash, or run pre-commit hooks, **strongly consider running `/sdd batch` from a dedicated git worktree** rather than your main checkout. A separate worktree gives the batch its own working tree, index, HEAD, and stash stack, so any mishaps (mis-stashed config, dirty working tree carried across Issues, accidental file deletion) stay isolated and recoverable by simply removing the worktree.

```bash
# From your main checkout (assumed at .../<repo>):
git worktree add ../<repo>-batch main      # or any base branch
cd ../<repo>-batch
# ... run /sdd batch from here ...
# When the batch is finished and PRs are reviewed:
cd ../<repo>
git worktree remove ../<repo>-batch
```

Branches created by the batch are still pushed to the same remote (so PRs work normally), but the local repository state is isolated. If a batch goes wrong, the recovery is `git worktree remove --force ../<repo>-batch` — your main checkout is untouched. Before running the script, the batch flow should detect whether the current directory is a worktree and **suggest creating one if it is not**:

```bash
# Detection (during Phase 1 confirmation):
if [ "$(git rev-parse --git-common-dir)" = "$(git rev-parse --git-dir)" ]; then
  # Not in a worktree — same dir is the main repo
  echo "[batch] You are about to run in the main checkout. Consider:"
  echo "  git worktree add ../<repo>-batch <base-branch>"
  echo "  cd ../<repo>-batch"
fi
```

This is a recommendation, not a hard requirement; the user can decline and proceed in the main checkout.

## Argument Parsing:

Parse `$1`:
- Empty or not provided → **All open Issues** mode
- Comma-separated numbers (e.g. `1,2,3`) → **Specific Issues** mode

## Phase 1: Collect and Filter Issues

### All open Issues mode:
1. Fetch all open Issues:
   ```bash
   gh issue list --state open --json number,title,labels --limit 200
   ```

### Specific Issues mode:
1. For each Issue number in the comma-separated list, fetch its details:
   ```bash
   gh issue view <number> --json number,title,labels,state
   ```
2. Validate each Issue exists and is open. If any Issue is closed or missing → warn and exclude it.

### Filter:

**All open Issues mode**:
1. **Exclude** Issues with `sdd:done` label (already completed)
2. **Exclude** Issues with `sdd:child` label (will be auto-discovered after the parent runs)
3. **Include** all remaining Issues (with or without SDD labels)
4. Sort by Issue number ascending

**Specific Issues mode** (user explicitly listed numbers):
1. **Exclude** Issues with `sdd:done` label (warn the user that the listed Issue is already done)
2. **Include** Issues with `sdd:child` label (the user explicitly chose them; respect intent)
3. **Include** all remaining Issues
4. Sort by Issue number ascending

If no Issues remain after filtering → report "No qualifying Issues found." and stop.

> Note: regardless of mode, the batch script will **auto-discover child Issues** that are created during a parent's processing (via `<!-- sdd:children:output -->` marker / `Parent Issue: #<n>` reference) and append them to the queue.

### Confirm with user:
Show the filtered Issue list with current stage:
```
SDD Batch Processing
════════════════════
Issues to process (in order):

  #10: Add user authentication       [new]
  #11: Fix pagination bug             [sdd:design]
  #12: Refactor logging module        [sdd:implement]

Total: 3 issues (queue may grow as parent Issues spawn children)
Mode: Sequential (each in a separate claude -p session)
Skip-review: analyze, design, implement, pr (auto-enabled — stops after PR creation)
Child auto-queue: enabled (children created by a parent are appended to the queue)
```

Determine stage label for display:
- No SDD label → `[new]`
- Has SDD label → show the label (e.g. `[sdd:analyze]`)

**Workspace check** — before asking for confirmation, detect whether the current directory is a dedicated git worktree:

```bash
COMMON_DIR=$(git rev-parse --git-common-dir 2>/dev/null)
GIT_DIR=$(git rev-parse --git-dir 2>/dev/null)
```

If `COMMON_DIR` equals `GIT_DIR` (or both resolve to the same absolute path), the user is in the **main checkout**, not a worktree. In that case, append the following warning to the confirmation summary:

```
⚠ Workspace: main checkout detected (not a worktree).
  Recommended: run this batch from a worktree to isolate the working tree.

      git worktree add ../<repo>-batch <base-branch>
      cd ../<repo>-batch

  Proceed in the main checkout anyway? [y/N]
```

If the user answers no, stop without generating the script. If yes, continue. Otherwise (already in a worktree) skip the warning and ask the standard confirmation.

## Phase 2: Verify Tool Permissions

`claude -p` sessions need tool permissions pre-configured in `.claude/settings.local.json`.

> Note: The generated script also passes `--dangerously-skip-permissions` to each child `claude -p`, which bypasses prompts and sandbox boundaries at runtime. The permissions registered here are still useful as a documented allowlist (and as a fallback if the user removes the flag), but they are **not strictly required** for the script to run unattended once the flag is in place. Treat the items below as the recommended baseline.

1. Read `.claude/settings.local.json` if it exists.
2. Check which permissions from the groups below are already present.
3. **Detect project type** by inspecting the repository root (use Read/Glob; do not require shelling out). For each marker present, pre-select the matching test-runner permission as `✓`. Markers can stack (e.g. a Flutter repo using FVM gets all three: `flutter`, `fvm`, `dart`).

   | Marker file/dir (in repo root) | Pre-select |
   |---|---|
   | `pubspec.yaml` | `Bash(flutter:*)`, `Bash(dart:*)` |
   | `.fvm/` or `.fvmrc` | `Bash(fvm:*)` |
   | `package.json` | `Bash(npm:*)`, `Bash(npx:*)` |
   | `yarn.lock` | `Bash(yarn:*)` |
   | `pnpm-lock.yaml` | `Bash(pnpm:*)` |
   | `pyproject.toml`, `requirements.txt`, `setup.py`, or `Pipfile` | `Bash(pytest:*)` |
   | `go.mod` | `Bash(go:*)` |
   | `Cargo.toml` | `Bash(cargo:*)` |
   | `Makefile` | `Bash(make:*)` |

4. Show the permission selection UI with three groups (mark detected runners as `✓`, undetected as `◻`):

```
Tool permissions for batch mode (claude -p sessions)
════════════════════════════════════════════════════
Detected: <list each detected marker, e.g. "Flutter (pubspec.yaml), FVM (.fvm/)">

[Required] — SDD pipeline will fail without these
  ✓ Read           — Read files (source code, config, plugin cache)
  ✓ Edit           — Modify existing files
  ✓ Write          — Create new files
  ✓ Bash(gh:*)     — GitHub CLI (Issue, PR, label operations)
  ✓ Bash(git:*)    — Git (branch, commit, push — covers `git commit`)

[Recommended] — Needed for full pipeline functionality
  ✓ Grep           — Search code content
  ✓ Glob           — Search files by pattern
  ✓ Agent          — Subagent spawning (AI review, code exploration)
  ◻ WebSearch      — Web search (for research during analysis)

[Test Runners] — Auto-pre-selected based on detected markers; toggle as needed
  <state> Bash(flutter:*) — Flutter (build, test, analyze, pub)  [marker: pubspec.yaml]
  <state> Bash(dart:*)    — Dart CLI                              [marker: pubspec.yaml]
  <state> Bash(fvm:*)     — Flutter Version Manager               [marker: .fvm/ or .fvmrc]
  <state> Bash(npm:*)     — npm test, npm run                     [marker: package.json]
  <state> Bash(npx:*)     — npx jest, npx playwright              [marker: package.json]
  <state> Bash(yarn:*)    — yarn test, yarn run                   [marker: yarn.lock]
  <state> Bash(pnpm:*)    — pnpm test, pnpm run                   [marker: pnpm-lock.yaml]
  <state> Bash(pytest:*)  — Python pytest                         [marker: pyproject.toml/...]
  <state> Bash(go:*)      — go test                               [marker: go.mod]
  <state> Bash(cargo:*)   — cargo test (Rust)                     [marker: Cargo.toml]
  <state> Bash(make:*)    — make test, make build                 [marker: Makefile]
  ◻ Bash                  — All shell commands (overrides all above; not auto-selected)
```

(Replace each `<state>` with `✓` if pre-selected by detection or already in settings, otherwise `◻`.)

Display rules:
- `✓` = selected by default, `◻` = not selected by default
- **Exact match only**: a scoped permission (e.g. `Edit(/path/**)`) does NOT satisfy an unscoped requirement (e.g. `Edit`). Only an exact unscoped `Edit` entry counts as "already set" for the `Edit` requirement. If only a scoped variant exists, the unscoped permission must still be added.
- Permissions already in `settings.local.json` (exact match) → show as `✓ (already set)` and skip
- If `Bash` (unscoped) is already set → skip all `Bash(...)` entries and show `Bash ✓ (already set)`
- If a more-specific permission is already present (e.g. `Bash(flutter test:*)` exists but `Bash(flutter:*)` does not), still propose adding the broader `Bash(flutter:*)` so subagents can run the full toolchain (analyze, pub, build, etc.) needed by pre-commit hooks.

5. Ask user which items to change:
   ```
   Enter items to toggle (e.g. "WebSearch, Bash(npm:*)")
   or press Enter to continue with current selection:
   ```

6. On confirmation: create or merge into `.claude/settings.local.json` preserving existing entries
7. On "none" or rejection: warn that batch script may fail without permissions, but continue with script generation

## Phase 3: Generate Batch Script

Generate the file `.github/.sdd-batch.sh` with the following template. Replace `<ISSUE_NUMBERS>` with the actual space-separated Issue numbers from Phase 1. Replace `<PLUGIN_VERSION>` with the literal `version` value read from `plugins/sdd-plugin/.claude-plugin/plugin.json` at script-generation time (inlined as text — the watermark lets users detect stale scripts after a plugin upgrade).

```bash
#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# SDD Batch Processing Script
# Generated by /sdd batch
# Generated by sdd-plugin <PLUGIN_VERSION> ($(date))
# ============================================================

ISSUES=(<ISSUE_NUMBERS>)
LOG_DIR=".github/.sdd-batch-logs"
CONFIG_FILE=".github/.sdd-config"
CONFIG_BACKUP=".github/.sdd-config.bak"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# --- Setup ---
mkdir -p "$LOG_DIR"

# Resolve owner/repo once for child Issue discovery
OWNER_REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || true)
if [ -z "$OWNER_REPO" ]; then
  echo "[batch] WARNING: Could not resolve repository (gh repo view failed). Child auto-discovery will be disabled."
fi

# Protect the batch infrastructure from `git stash -u` and similar.
# Subagents may stash untracked files when switching branches; without these
# entries, .sdd-batch.sh / .sdd-config can disappear into a stash mid-run,
# breaking skip-review detection in subsequent sessions.
#
# Use .git/info/exclude (local-only) instead of .gitignore so the user's
# tracked .gitignore is not modified.
if [ -d ".git/info" ]; then
  EXCLUDE_FILE=".git/info/exclude"
  touch "$EXCLUDE_FILE"
  for ENTRY in ".github/.sdd-batch.sh" ".github/.sdd-config" ".github/.sdd-config.bak"; do
    if ! grep -qxF "$ENTRY" "$EXCLUDE_FILE"; then
      echo "$ENTRY" >> "$EXCLUDE_FILE"
      echo "[batch] Added $ENTRY to .git/info/exclude (protect from stash -u)"
    fi
  done
fi

if [ -f "$CONFIG_FILE" ]; then
  cp "$CONFIG_FILE" "$CONFIG_BACKUP"
  echo "[batch] Backed up $CONFIG_FILE"
else
  echo "[batch] No existing $CONFIG_FILE"
fi

# 4 keys — NOT 5. Batch stops after PR creation; `qa` is intentionally
# omitted so each child's `stage_test` returns OK PAUSE and the human runs
# QA manually after the batch completes (per spec/flow/batch.md §5).
echo "skip-review: analyze,design,implement,pr" > "$CONFIG_FILE"
echo "[batch] Set skip-review for batch mode"

# --- Config restore (GAP-A6 core — called explicitly before stats/summary) ---
# Separating config restore from script deletion keeps the "[batch] Restored" message
# before stats output, while "[batch] Removed batch script" appears after summary via trap.
restore_config() {
  if [ -f "$CONFIG_BACKUP" ]; then
    cp "$CONFIG_BACKUP" "$CONFIG_FILE"
    rm -f "$CONFIG_BACKUP"
    echo "[batch] Restored original $CONFIG_FILE"
  else
    rm -f "$CONFIG_FILE"
    echo "[batch] Removed temporary $CONFIG_FILE"
  fi
}

# --- Cleanup trap (script deletion only — fires via trap EXIT after summary) ---
SCRIPT_PATH="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
CLEANUP_DONE=0
cleanup() {
  if [ "$CLEANUP_DONE" -eq 1 ]; then return; fi
  CLEANUP_DONE=1
  echo ""
  echo "[batch] Cleaning up..."
  rm -f "$SCRIPT_PATH"
  echo "[batch] Removed batch script"
}
trap cleanup EXIT INT TERM

# --- Process Issues (queue-based; supports auto-discovery of child Issues) ---
BATCH_START=$(date +%s)
ERROR_LOG="$LOG_DIR/errors-${TIMESTAMP}.log"
SUCCEEDED=0
FAILED=0
FAILED_ISSUES=()

# Queue + bookkeeping. SEEN holds every Issue ever queued (processed or pending)
# as " #<n> " tokens so membership checks via `case` are simple and robust.
QUEUE=("${ISSUES[@]}")
SEEN=""
for n in "${ISSUES[@]}"; do SEEN="$SEEN #$n "; done
TOTAL_TARGETS=${#ISSUES[@]}
PROCESSED_COUNT=0

# --- Recovery hint (SIGKILL cannot be trapped) ---
if [ -f "$CONFIG_BACKUP" ]; then
  echo "[batch] Recovery hint (if killed with SIGKILL):"
  echo "  mv .github/.sdd-config.bak .github/.sdd-config"
  echo "  rm -f .github/.sdd-batch.sh"
  echo ""
fi

echo ""
echo "============================================================"
echo "  SDD Batch: Processing ${#ISSUES[@]} initial issue(s)"
echo "  (queue may grow as parents spawn children)"
echo "============================================================"
echo ""

while [ ${#QUEUE[@]} -gt 0 ]; do
  ISSUE=${QUEUE[0]}
  QUEUE=("${QUEUE[@]:1}")

  PROCESSED_COUNT=$((PROCESSED_COUNT + 1))
  LOG_FILE="$LOG_DIR/issue-${ISSUE}-${TIMESTAMP}.log"

  echo "[$PROCESSED_COUNT/$TOTAL_TARGETS] Processing Issue #$ISSUE..."
  echo "  Log: $LOG_FILE"

  while true; do
    EXIT_CODE=0
    # --dangerously-skip-permissions: bypass per-call permission prompts AND
    # the sandbox boundary in the child session. Required for unattended runs
    # because subagents otherwise hit "Run outside of the sandbox" on
    # `flutter test`, pre-commit hooks invoking the toolchain, `git push`, etc.
    claude -p --verbose --output-format stream-json --dangerously-skip-permissions "/sdd resume $ISSUE" > "$LOG_FILE" 2>&1 || EXIT_CODE=$?

    if [ "$EXIT_CODE" -eq 0 ]; then
      echo "  ✓ Issue #$ISSUE completed"
      SUCCEEDED=$((SUCCEEDED + 1))

      # --- Auto-discover child Issues created by this parent ---
      # Match the parent reference across all supported language templates:
      #   en: "Parent Issue: #N"
      #   ko: "상위 Issue: #N"
      #   ja: "親Issue: #N"
      # Canonical source for the multilingual prefix list:
      #   plugins/sdd-plugin/skills/sdd/commands/atoms/_multilingual.md
      # Keep this regex in sync with that atom if new languages are added.
      # Approach: filter sdd:child open issues, then jq-test body for any of
      # the three templated parent references (with non-digit boundary so
      # #683 doesn't match #6831).
      if [ -n "$OWNER_REPO" ]; then
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
      fi

      break
    fi

    # Check for rate limit
    RESET_AT=$(jq -r 'select(.type == "rate_limit_event") | .rate_limit_info | select(.status != "allowed") | .resetsAt // empty' "$LOG_FILE" 2>/dev/null | tail -1)

    if [ -z "$RESET_AT" ] && grep -qi "rate.limit\|overloaded\|too many requests" "$LOG_FILE" 2>/dev/null; then
      RESET_AT=$(jq -r 'select(.type == "rate_limit_event") | .rate_limit_info.resetsAt // empty' "$LOG_FILE" 2>/dev/null | tail -1)
    fi

    if [ -n "$RESET_AT" ]; then
      NOW=$(date +%s)
      WAIT=$((RESET_AT - NOW + 30))
      if [ "$WAIT" -gt 0 ]; then
        WAIT_MIN=$((WAIT / 60))
        WAIT_SEC=$((WAIT % 60))
        RESET_TIME=$(date -r "$RESET_AT" +%H:%M:%S 2>/dev/null || date -d "@$RESET_AT" +%H:%M:%S 2>/dev/null)
        echo "  ⏳ Rate limited. Waiting until ~$RESET_TIME (${WAIT_MIN}m ${WAIT_SEC}s)..."
        sleep "$WAIT"
        echo "  🔄 Retrying Issue #$ISSUE..."
        continue
      fi
    fi

    # Not rate limited — genuine failure
    echo "  ✗ Issue #$ISSUE failed (exit code: $EXIT_CODE)"
    FAILED=$((FAILED + 1))
    FAIL_REASON=$(jq -r 'select(.type == "result") | select(.is_error == true) | .result // empty' "$LOG_FILE" 2>/dev/null | tail -1 | cut -c1-80)
    if [ -z "$FAIL_REASON" ]; then
      FAIL_REASON="exit code $EXIT_CODE"
    fi
    FAILED_ISSUES+=("#${ISSUE} (${FAIL_REASON})")

    # Extract error details to error log
    {
      echo "════════════════════════════════════════"
      echo "Issue #$ISSUE — $(date '+%Y-%m-%d %H:%M:%S')"
      echo "════════════════════════════════════════"
      echo "Exit code: $EXIT_CODE"

      DENIALS=$(jq -r 'select(.type == "result") | .permission_denials[]?' "$LOG_FILE" 2>/dev/null)
      if [ -n "$DENIALS" ]; then
        echo ""
        echo "Permission denied:"
        echo "$DENIALS" | while read -r D; do echo "  - $D"; done
      fi

      ERRMSG=$(jq -r 'select(.type == "result") | select(.is_error == true) | .result // empty' "$LOG_FILE" 2>/dev/null | tail -1)
      if [ -n "$ERRMSG" ]; then
        echo ""
        echo "Error message:"
        echo "  $ERRMSG"
      fi

      echo ""
    } >> "$ERROR_LOG"

    break
  done

  echo ""
done

TOTAL=$PROCESSED_COUNT

# --- Config restore (GAP-A6: must precede stats/summary) ---
# Explicit call ensures .sdd-config is restored even if stats aggregation errors out
# under set -e before trap EXIT can fire.
restore_config

# --- Aggregate stats from stream-json logs ---
BATCH_END=$(date +%s)
BATCH_ELAPSED=$((BATCH_END - BATCH_START))
BATCH_MIN=$((BATCH_ELAPSED / 60))
BATCH_SEC=$((BATCH_ELAPSED % 60))

TOTAL_INPUT=0
TOTAL_OUTPUT=0
TOTAL_CACHE_READ=0
TOTAL_CACHE_CREATE=0
TOTAL_COST=0

for LOG in "$LOG_DIR"/issue-*-"${TIMESTAMP}".log; do
  [ -f "$LOG" ] || continue
  STATS=$(jq -r 'select(.type == "result") | "\(.usage.input_tokens // 0) \(.usage.output_tokens // 0) \(.usage.cache_read_input_tokens // 0) \(.usage.cache_creation_input_tokens // 0) \(.total_cost_usd // 0)"' "$LOG" 2>/dev/null | tail -1)
  if [ -n "$STATS" ]; then
    read -r IN OUT CR CC COST <<< "$STATS"
    TOTAL_INPUT=$((TOTAL_INPUT + IN))
    TOTAL_OUTPUT=$((TOTAL_OUTPUT + OUT))
    TOTAL_CACHE_READ=$((TOTAL_CACHE_READ + CR))
    TOTAL_CACHE_CREATE=$((TOTAL_CACHE_CREATE + CC))
    TOTAL_COST=$(echo "$TOTAL_COST + $COST" | bc)
  fi
done

TOTAL_CONTEXT=$((TOTAL_INPUT + TOTAL_OUTPUT + TOTAL_CACHE_READ + TOTAL_CACHE_CREATE))

# --- Summary ---
echo "============================================================"
echo "  SDD Batch Complete"
echo "============================================================"
echo "  Total:     $TOTAL"
echo "  Succeeded: $SUCCEEDED"
echo "  Failed:    $FAILED"
if [ ${#FAILED_ISSUES[@]} -gt 0 ]; then
  echo "  Failed Issues:"
  for FI in "${FAILED_ISSUES[@]}"; do
    echo "    $FI"
  done
  echo "  Error log: $ERROR_LOG"
fi
echo ""
echo "  Time:      ${BATCH_MIN}m ${BATCH_SEC}s"
echo "  Cost:      \$${TOTAL_COST}"
echo "  Tokens:    $(printf "%'d" $TOTAL_CONTEXT) total"
echo "               in: $(printf "%'d" $TOTAL_INPUT)  out: $(printf "%'d" $TOTAL_OUTPUT)"
echo "               cache read: $(printf "%'d" $TOTAL_CACHE_READ)  cache create: $(printf "%'d" $TOTAL_CACHE_CREATE)"
echo ""
echo "  Logs: $LOG_DIR/"
echo "============================================================"
```

After writing the script:
1. Make it executable: `chmod +x .github/.sdd-batch.sh`
2. Check if `.gitignore` exists and whether `.github/.sdd-batch-logs/` is listed
   - If not listed → suggest adding it (ask user)
3. Execute the script in background using the **Bash tool** with `run_in_background: true`:
   ```bash
   bash .github/.sdd-batch.sh
   ```
4. Report to user:
   ```
   SDD Batch started (running in background)

     Issues: <N>
     Logs: .github/.sdd-batch-logs/

   The batch script will:
     1. Process each issue sequentially via claude -p
     2. Restore your original config when done (even on Ctrl+C)
     3. Delete itself after completion

   You will be notified when the batch finishes.

   Monitor real-time progress (in another terminal):
     tail -f .github/.sdd-batch-logs/issue-<N>-*.log | \
       jq -r 'if .type == "assistant" then
         (.message.content[] |
           if .type == "tool_use" then "🔧 \(.name): \(.input.command // .input.file_path // .input.pattern // "")"
           elif .type == "text" then "💬 \(.text[0:120])"
           else empty end)
       elif .type == "result" then "✅ Done (\(.duration_ms/1000)s, $\(.total_cost_usd))"
       else empty end' 2>/dev/null
   ```
5. When the background execution completes, read the log files and report results:
   ```
   SDD Batch Complete
   ══════════════════
     #10: ✓ completed
     #11: ✓ completed
     #12: ✗ failed (see .github/.sdd-batch-logs/issue-12-*.log)

   Succeeded: 2/3
   ```

## Notes

- **Setup — `.git/info/exclude` idempotent**: `grep -qxF` ensures each entry is added at most once, so re-running the script or running multiple batches concurrently does not duplicate entries. This protects `.sdd-batch.sh`, `.sdd-config`, and `.sdd-config.bak` from being stashed by subagents' `git stash -u` mid-run. `.git/info/exclude` (not `.gitignore`) is used to avoid modifying the tracked ignore file.

- **Setup — config backup semantics**: `restore_config()` is only created when `.sdd-config` already existed before the batch. If the file did not exist, no `.sdd-config.bak` is created and `restore_config()` removes the temporary file on completion. The `[ -f "$CONFIG_BACKUP" ]` guard in `restore_config()` encodes this invariant.

- **GAP-A6 ordering invariant**: `restore_config()` is called explicitly after the loop and *before* stats aggregation. This ensures `.sdd-config` is restored even if the `jq`-based stats code errors under `set -e` before `trap EXIT` fires. Script deletion (`rm -f "$SCRIPT_PATH"`) is kept in `cleanup()` which runs via `trap EXIT` after summary output — this way the `[batch] Removed batch script` message does not appear before the stats and summary.

- **SIGKILL limitation**: `trap` cannot catch SIGKILL (`kill -9`). The recovery hint printed before the loop tells the user how to manually restore `.sdd-config` and remove the stale `.sdd-batch.sh` if the script is hard-killed. The `CLEANUP_DONE` guard in `cleanup()` prevents double-execution when `cleanup()` is called explicitly (for any future refactoring) and then again via `trap EXIT`.

- **`${ISSUE}` in shell script vs `_bash_rules.md` §6**: Shell variable expansion inside the generated `.sdd-batch.sh` is allowed. `_bash_rules.md` §6 (no `${...}` inside quoted args to the Bash tool) applies only when Claude invokes the Bash tool directly — not to OS-level bash processes running a generated script. `/sdd auto` §3.3's literal substitution requirement does not apply here.

- **`implement-parent` handling**: When a parent Issue is paused at `sdd:implement` waiting for child Issues, `/sdd resume` detects the `implement-parent` state, prints child progress, and exits with code 0. The batch script counts this as SUCCEEDED. Child Issues are discovered and queued in the child auto-discovery step that follows immediately.

- **4-key skip-review** (`analyze,design,implement,pr` — `qa` intentionally absent): Each child session's `stage_test` returns `OK PAUSE` when it reaches manual QA, stopping the child session cleanly after PR creation. The human runs QA after the batch completes. Compare with `/sdd auto` which uses 5 keys (including `qa`) because it runs unattended in-session.

- **FAILED_ISSUES reason**: The failure reason is extracted from the stream-json log's last `result` entry with `is_error == true`. If no such entry exists (process killed, tool failure without structured output), the fallback is `"exit code $EXIT_CODE"`. Rate-limit retries overwrite the same log file, so only the final attempt's reason is captured — this is intentional.
