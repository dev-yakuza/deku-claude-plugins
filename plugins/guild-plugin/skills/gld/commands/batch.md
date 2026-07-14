# BATCH (draft)

**Run multiple Issues through the Guild spine unattended, with rate-limit auto-resume.** Each Issue runs in its own headless `claude -p` child session driven by `/gld resume`; a background supervisor loop **detects token rate limits and automatically waits until reset, then re-runs** — no human interaction. Ported from `sdd-plugin` `batch.md` (the verified rate-limit-resilient runner), adapted to Guild.

> **Status: live-validated (2026-07-14, 1 real batch of 2 issues).** ✅ **rate-limit auto-resume** confirmed (a real limit hit → auto-waited ~115m → resumed, no lost work) · ✅ **`guild:needs-human` pause** confirmed (a scope-defining high-stakes discuss ambiguity → leader paused without guessing) · 🐛 **found + fixed a false-positive**: the supervisor trusted `claude -p` **exit 0** as "completed," but a headless turn can exit 0 while a backgrounded pre-commit hook leaves the Issue mid-spine (no commit/PR). Completion is now judged by the **GitHub label** (`guild:done` / `guild:children`), with `guild:needs-human` counted as PAUSED and a mid-spine exit-0 re-resumed (bounded) then surfaced as INCOMPLETE — never silently "succeeded." Wired across `_handoff.md` (Section H), `analyze.md`/`design.md`/`test.md`/`qa.md` (gate branches), `dev.md` (mode detect + PAUSE handling), `implement.md` (decision log + branch/PR resume), `init.md` (`guild:needs-human` label).

`$1` = comma-separated Issue numbers (e.g. `837,840`), or empty = all open qualifying Issues.

## Language
Read `language` from `.claude/guild/config.json` first; respond to the user in that language (`ko`/`ja`/`en`) for all messages. (Same convention as other `/gld` commands.)

> **Bash**: the generated batch script is written to a file and run as **one** Bash call (background) — this is the sanctioned exception to `_bash_rules.md` atomic-bash (shell variable expansion inside the generated `.sh` is fine; the rule governs direct Bash-tool invocations, not an OS-level script). State/labels: `<<SKILL_DIR>>/commands/atoms/_handoff.md`.

> ⚠️ **Security**: each child runs with `--dangerously-skip-permissions` — bypasses all permission prompts and the sandbox in the child so test runners, commit hooks, `git push`, `gh pr create` run unattended. All tool calls are logged to `.claude/guild/.batch-logs/`. Use only when you accept unattended tool execution.

## Recommended: run in a git worktree
Child sessions switch branches, stash, run hooks. Prefer a dedicated worktree so mishaps stay isolated:
```bash
git worktree add ../<repo>-batch <base-branch>
cd ../<repo>-batch
# run /gld batch here; when done + PRs reviewed:
git worktree remove ../<repo>-batch
```
Detect during Phase 1 (`git rev-parse --git-common-dir` == `--git-dir` → main checkout) and suggest a worktree; the user may decline.

> ⚠️ **Worktree needs a *committed* harness.** A fresh worktree materializes only **tracked** files at the base commit — so if `.claude/guild/`, `.claude/agents/`, `CLAUDE.md`, `docs/standards/` are **untracked** (a dev/unverified harness, or a repo that hasn't committed its Guild setup), they will **not** exist in the worktree and every child fails "Guild not initialized." In that case either commit the harness first, or **run in the main checkout** (accept the branch-switch/stash caveat). Observed 2026-07-14 (word_app dev harness was untracked → main-checkout required).

---

## Phase 0 — Preflight
As the leader, confirm Guild is initialized (`ls .claude/guild/config.json`; absent → "run `/gld init` first", stop). Resolve `<owner>/<repo>` once (`_handoff.md` Section F).

## Phase 1 — Collect & filter Issues
- **Specific mode** (`$1` = `N,M,…`): `gh issue view <n> --json number,title,labels,state` each; exclude closed/missing (warn); **include** `guild:child` (explicit user intent).
- **All-open mode** (`$1` empty): `gh issue list --state open --json number,title,labels --limit 200`; **exclude** `guild:done` (complete) and `guild:child` (auto-discovered after parent). 
- Sort ascending. If none remain → "No qualifying Issues found." stop.
- Show the filtered list with each Issue's current stage label (`[new]` if none) and confirm with the user (+ worktree warning if in main checkout). Note: "queue may grow as parents spawn children."

## Phase 2 — Permissions (child sessions)
`claude -p` children need tool permissions in `.claude/settings.local.json` (also `--dangerously-skip-permissions` bypasses prompts at runtime; the allowlist is a documented fallback). Detect the project's test runner from root markers (`pubspec.yaml`→flutter/dart, `package.json`→npm/npx, `yarn.lock`→yarn, …) and offer to add the baseline: `Read`, `Edit`, `Write`, `Bash(gh:*)`, `Bash(git:*)`, `Agent`, `Grep`, `Glob`, + detected runner(s). Merge into `settings.local.json` preserving existing. If declined, warn and continue.

## Phase 3 — Generate the supervisor script
Write `.claude/guild/.gld-batch.sh` with the template below. Replace `<ISSUE_NUMBERS>` (space-separated) and `<PLUGIN_VERSION>` (from `plugins/guild-plugin/.claude-plugin/plugin.json`, inlined as a stale-script watermark).

```bash
#!/usr/bin/env bash
set -euo pipefail
# ============================================================
# Guild Batch — generated by /gld batch (guild-plugin <PLUGIN_VERSION>)
# ============================================================
ISSUES=(<ISSUE_NUMBERS>)
LOG_DIR=".claude/guild/.batch-logs"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
mkdir -p "$LOG_DIR"

OWNER_REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || true)
[ -z "$OWNER_REPO" ] && echo "[batch] WARNING: repo unresolved — child auto-discovery disabled."

# Protect batch infra from subagents' `git stash -u` (local-only exclude, not .gitignore)
if [ -d ".git/info" ]; then
  EXCLUDE=".git/info/exclude"; touch "$EXCLUDE"
  for E in ".claude/guild/.gld-batch.sh" ".claude/guild/.batch-logs"; do
    grep -qxF "$E" "$EXCLUDE" || echo "$E" >> "$EXCLUDE"
  done
fi

# Self-delete on exit (trap can't catch SIGKILL — then remove .gld-batch.sh manually)
SCRIPT_PATH="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
cleanup() { rm -f "$SCRIPT_PATH"; echo "[batch] Removed batch script"; }
trap cleanup EXIT INT TERM

BATCH_START=$(date +%s)
SUCCEEDED=0; FAILED=0; PAUSED=0; INCOMPLETE=0; FAILED_ISSUES=(); INCOMPLETE_ISSUES=()
QUEUE=("${ISSUES[@]}"); SEEN=""
for n in "${ISSUES[@]}"; do SEEN="$SEEN #$n "; done
TOTAL=${#ISSUES[@]}; PROCESSED=0

echo "============================================================"
echo "  Guild Batch: ${#ISSUES[@]} initial issue(s) (queue may grow)"
echo "============================================================"

while [ ${#QUEUE[@]} -gt 0 ]; do
  ISSUE=${QUEUE[0]}; QUEUE=("${QUEUE[@]:1}")
  PROCESSED=$((PROCESSED + 1))
  LOG="$LOG_DIR/issue-${ISSUE}-${TIMESTAMP}.log"
  echo "[$PROCESSED/$TOTAL] Issue #$ISSUE → $LOG"

  RESUME_TRIES=0
  while true; do
    EXIT_CODE=0
    # GLD_UNATTENDED=1: flow auto-proceeds discuss/verify gates (records assumptions) — see Notes.
    # --dangerously-skip-permissions: unattended tool calls (tests, hooks, push, PR).
    GLD_UNATTENDED=1 CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0 \
      claude -p --verbose --output-format stream-json --dangerously-skip-permissions \
      "/gld resume $ISSUE" > "$LOG" 2>&1 || EXIT_CODE=$?

    if [ "$EXIT_CODE" -eq 0 ]; then
      # ⚠ exit 0 is NOT proof of completion — a headless `claude -p` turn can end while a
      # backgrounded pre-commit hook is still running, leaving the Issue mid-spine with no
      # commit/PR. Truth = the GitHub label (_handoff.md Section A: "labels are the state").
      if [ -z "$OWNER_REPO" ]; then
        echo "  ✓ Issue #$ISSUE (exit 0; state UNVERIFIED — no repo)"; SUCCEEDED=$((SUCCEEDED + 1)); break
      fi
      STATE=$(gh issue view "$ISSUE" --repo "$OWNER_REPO" --json labels \
        --jq '[.labels[].name] | map(select(startswith("guild:"))) | join(",")' 2>/dev/null || true)
      case "$STATE" in
        *guild:done*)
          echo "  ✓ Issue #$ISSUE done"; SUCCEEDED=$((SUCCEEDED + 1))
          # Auto-discover child Issues (design split → guild:child + "Parent Issue: #N")
          CHILDREN=$(gh issue list --repo "$OWNER_REPO" --label guild:child --state open --limit 200 \
            --json number,body \
            --jq "[.[] | select(.body | test(\"Parent Issue: #${ISSUE}([^0-9]|\$)\"))] | .[].number" 2>/dev/null || true)
          for C in $CHILDREN; do
            case "$SEEN" in *" #$C "*) ;; *)
              SEEN="$SEEN #$C "; QUEUE+=("$C"); TOTAL=$((TOTAL + 1))
              echo "  + Discovered child #$C → queued (total $TOTAL)" ;;
            esac
          done
          break ;;
        *guild:children*)
          echo "  ✓ Issue #$ISSUE split (parent orchestration) — discovering children"; SUCCEEDED=$((SUCCEEDED + 1))
          CHILDREN=$(gh issue list --repo "$OWNER_REPO" --label guild:child --state open --limit 200 \
            --json number,body \
            --jq "[.[] | select(.body | test(\"Parent Issue: #${ISSUE}([^0-9]|\$)\"))] | .[].number" 2>/dev/null || true)
          for C in $CHILDREN; do
            case "$SEEN" in *" #$C "*) ;; *)
              SEEN="$SEEN #$C "; QUEUE+=("$C"); TOTAL=$((TOTAL + 1))
              echo "  + Discovered child #$C → queued (total $TOTAL)" ;;
            esac
          done
          break ;;
        *guild:needs-human*)
          echo "  ⏸ Issue #$ISSUE paused (needs-human)"; PAUSED=$((PAUSED + 1)); break ;;
        *)
          # exited 0 but still mid-spine (or state unreadable) = NOT finished. Re-resume,
          # bounded (resume is state-safe — continues from the label). Then surface honestly.
          RESUME_TRIES=$((RESUME_TRIES + 1))
          if [ "$RESUME_TRIES" -lt 3 ]; then
            echo "  ↻ Issue #$ISSUE exited at [${STATE:-unknown}] without finishing — re-resuming ($RESUME_TRIES/2)"
            continue
          fi
          echo "  ⚠ Issue #$ISSUE INCOMPLETE (stuck at ${STATE:-unknown} after re-resume)"
          INCOMPLETE=$((INCOMPLETE + 1)); INCOMPLETE_ISSUES+=("#$ISSUE (${STATE:-unknown})"); break ;;
      esac
    fi

    # --- Rate-limit detection → wait until reset → auto-retry (the core) ---
    RESET_AT=$(jq -r 'select(.type == "rate_limit_event") | .rate_limit_info | select(.status != "allowed") | .resetsAt // empty' "$LOG" 2>/dev/null | tail -1)
    if [ -z "$RESET_AT" ] && grep -qi "rate.limit\|overloaded\|too many requests" "$LOG" 2>/dev/null; then
      RESET_AT=$(jq -r 'select(.type == "rate_limit_event") | .rate_limit_info.resetsAt // empty' "$LOG" 2>/dev/null | tail -1)
    fi
    if [ -n "$RESET_AT" ]; then
      NOW=$(date +%s); WAIT=$((RESET_AT - NOW + 30))
      if [ "$WAIT" -gt 0 ]; then
        RESET_TIME=$(date -r "$RESET_AT" +%H:%M:%S 2>/dev/null || date -d "@$RESET_AT" +%H:%M:%S 2>/dev/null)
        echo "  ⏳ Rate limited. Waiting until ~$RESET_TIME ($((WAIT/60))m $((WAIT%60))s)..."
        sleep "$WAIT"
        echo "  🔄 Retrying Issue #$ISSUE (resume from GitHub state)..."
        continue
      fi
    fi

    # Genuine failure (not rate limit)
    echo "  ✗ Issue #$ISSUE failed (exit $EXIT_CODE)"; FAILED=$((FAILED + 1))
    REASON=$(jq -r 'select(.type == "result") | select(.is_error == true) | .result // empty' "$LOG" 2>/dev/null | tail -1 | cut -c1-80)
    FAILED_ISSUES+=("#$ISSUE (${REASON:-exit $EXIT_CODE})")
    break
  done
done

# --- Summary + token/cost aggregation from stream-json ---
BATCH_ELAPSED=$(( $(date +%s) - BATCH_START ))
TOTAL_IN=0; TOTAL_OUT=0; TOTAL_CR=0; TOTAL_CC=0; TOTAL_COST="0"
for L in "$LOG_DIR"/issue-*-"${TIMESTAMP}".log; do
  [ -f "$L" ] || continue
  S=$(jq -r 'select(.type=="result") | "\(.usage.input_tokens // 0) \(.usage.output_tokens // 0) \(.usage.cache_read_input_tokens // 0) \(.usage.cache_creation_input_tokens // 0) \(.total_cost_usd // 0)"' "$L" 2>/dev/null | tail -1)
  [ -n "$S" ] && read -r IN OUT CR CC COST <<< "$S" && {
    TOTAL_IN=$((TOTAL_IN + ${IN:-0})); TOTAL_OUT=$((TOTAL_OUT + ${OUT:-0}))
    TOTAL_CR=$((TOTAL_CR + ${CR:-0})); TOTAL_CC=$((TOTAL_CC + ${CC:-0}))
    TOTAL_COST=$(echo "$TOTAL_COST + ${COST:-0}" | bc 2>/dev/null || echo "$TOTAL_COST")
  }
done

echo "============================================================"
echo "  Guild Batch Complete"
echo "  Total: $PROCESSED  Done: $SUCCEEDED  Paused(needs-human): $PAUSED  Incomplete: $INCOMPLETE  Failed: $FAILED"
if [ ${#INCOMPLETE_ISSUES[@]} -gt 0 ]; then
  echo "  Incomplete (exited without reaching guild:done — resume to finish):"
  for II in "${INCOMPLETE_ISSUES[@]}"; do echo "    $II"; done
fi
if [ ${#FAILED_ISSUES[@]} -gt 0 ]; then
  echo "  Failed:"; for FI in "${FAILED_ISSUES[@]}"; do echo "    $FI"; done
fi
echo "  Time: $((BATCH_ELAPSED/60))m $((BATCH_ELAPSED%60))s  Cost: \$${TOTAL_COST}"
echo "  Tokens: in $TOTAL_IN · out $TOTAL_OUT · cache read $TOTAL_CR · create $TOTAL_CC"
echo "  Logs: $LOG_DIR/"
echo "============================================================"
```

## Phase 4 — Run in background + report
1. `chmod +x .claude/guild/.gld-batch.sh`.
2. Ensure `.claude/guild/.batch-logs/` won't be committed (the script already adds it to `.git/info/exclude`; the parent `.claude/guild/.gitignore` may also cover it).
3. Execute via the **Bash tool with `run_in_background: true`**: `bash .claude/guild/.gld-batch.sh`.
4. Report: "Guild batch started (background). Issues: <N>. Logs: .claude/guild/.batch-logs/. Rate limits auto-wait+resume. You'll be notified on completion." Give the `tail -f … | jq …` monitor hint.
5. On completion (harness re-invokes when the background task exits): read the logs, report per-Issue outcome + the summary block. Outcomes are **label-truthful** (Done / Paused-needs-human / Incomplete / Failed), not exit-code-based. **List paused Issues** (`gh issue list --label guild:needs-human --state open`) — resolve, then re-run `/gld dev`/`resume`. **List Incomplete Issues** (exited 0 mid-spine — a backgrounded hook or turn-end) — `/gld resume <n>` continues them from the label; their partial work is on the feature branch.

---

## Notes
- **How far each child goes (scope)**: each Issue runs the full spine to **`guild:done`** = code implemented + automated tests (verify) + agent-doable QA + **PR opened**. It does **NOT** merge the PR (human, INV1), does **NOT** do manual/visual QA (flagged for the human), and does not run guided `review` (on-demand). The deferred human gate lands at **PR review + merge** after the batch; the PR body carries the leader's "무인 결정 로그". High-stakes discuss ambiguity or unresolved verify failure → the Issue is **paused (needs-human)**, not forced to done.
- **Rate-limit auto-resume (the point)**: the inner `while true` loop re-runs `/gld resume $ISSUE` after `sleep`ing until `rate_limit_info.resetsAt` (+30s). Because `resume` reads state from GitHub labels/comments/git (`_handoff.md` Sections A/B), each retry continues from the last completed stage — no lost work, no human interaction.
- **★Companion — the leader stands in for the human at gates (`GLD_UNATTENDED`)**: unattended, the leader exercises *power of attorney* for in-flow gate decisions, but the human's real authority is **deferred to PR review, not removed** — nothing merges unattended (INV1). This is the plan's sprint principle ("사람 리뷰를 뒤로 미룰 뿐 없애지 않음") applied to batch. Rules:
  - **discuss gate (analyze/design)** — the leader classifies the ambiguity's stakes, **charter-anchored**:
    - *low/medium* (local, reversible interpretation) → pick the most charter/standards-aligned option, **record it as an explicit assumption** in the analyze/design output + PR body (`가정: … · 근거: … · 사람 확인 요`), then proceed.
    - *high* (scope-defining / materially different product) → **do NOT guess.** Pause: keep the label at the current stage, post a `<!-- guild:needs-human -->` comment listing the options, return a paused status; the supervisor counts it as PAUSED and moves to the next Issue.
  - **verify gate (test)** — deterministic: raw evidence green + AC covered → proceed; else bounded loop-back to execute (≤2); still failing → **pause (needs-human), never fake-pass** (INV2: no test weakening).
  - **Decision log** — every gate the leader auto-resolved is aggregated into the PR body ("무인 결정 로그") so the human's PR review is **informed, not blind**.
  - **Net**: leader decides low/medium judgments (anchored + logged), escalates high-stakes ones, and the human gate lands at **PR review + merge** after the batch.
  - **Wiring (done)**: `_handoff.md` Section H (policy + detection) · `analyze.md`/`design.md` (discuss classify+record vs pause) · `test.md`/`qa.md` (verify/QA deterministic + pause) · `dev.md` (mode detect; no `AskUserQuestion` when unattended; clean PAUSE) · `implement.md` (PR decision log + resume-safe branch/PR) · `init.md` (`guild:needs-human` label). Authoritative policy = Section H.
- **Resume granularity**: cross-stage is safe (labels). Mid-`execute` interruption re-enters execute — `implement.md` should detect an existing feature branch/partial commits and continue (see plan §부록 B "중단 내성"). Until hardened, a mid-execute retry may redo work.
- **Child auto-discovery**: matches `guild:child` Issues whose body has `Parent Issue: #<n>` (created by `design.md`'s multi-PR split). Keep the regex in sync if that reference string changes. ⚠ **Split-parent limitation (untested edge)**: when a parent splits, the supervisor counts the split as done and **queues the children** (they get developed unattended), but it does **not** re-queue the parent for its final **Phase 2c parent-integration** after the children finish — so a batched split parent is left at `guild:children`. Finish it with a manual `/gld dev <parent>` (re-enters Phase 2b, sees all children `guild:done`, runs integration → parent `guild:done`). Full batch↔orchestration nesting is v2.
- **`_bash_rules.md` exception**: variable expansion inside the generated `.sh` is fine — the atomic-bash rule governs direct Bash-tool calls, not OS-level scripts. The script is one background Bash-tool invocation.
- **SIGKILL**: `trap` can't catch `kill -9`; then remove `.claude/guild/.gld-batch.sh` manually. No config backup/restore is needed (Guild uses `GLD_UNATTENDED` env, not a config-file toggle — simpler than sdd's `.sdd-config` swap).

## Activation checklist
1. ✅ `batch` added to `SKILL.md` valid commands + `help.md` line.
2. ✅ **`GLD_UNATTENDED` companion** wired in `_handoff.md` Section H + `analyze/design/test/qa/dev` gate branches (+ `implement.md` decision log).
3. ✅ `implement.md` mid-execute resume hardened (existing-branch/PR detection).
4. ⬜ **Gating decision** (open): `batch` is lower-risk than full autonomous `sprint` (human still reviews every PR), so it can ship before `sprint`'s readiness gate — but keep the security note prominent. Confirm with the user.
5. ✅ **End-to-end validation** (2026-07-14): real 2-issue batch confirmed rate-limit auto-resume + `guild:needs-human` pause; found + fixed the exit-0 false-positive (now label-based completion). **Untested edges**: happy-path *unattended* completion to `guild:done` was blocked by the false-positive (re-verify after the fix); split-parent under batch (nested orchestration); worktree path assumes a **committed** harness (an untracked/dev harness needs main-checkout — see Phase 1).
