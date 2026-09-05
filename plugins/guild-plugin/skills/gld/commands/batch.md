# BATCH (draft)

**Run multiple Issues through the Guild spine unattended, with rate-limit auto-resume.** Each Issue runs in its own headless `claude -p` child session driven by `/gld dev` (**not** `/gld resume` — see the inline note in the generated script: `dev` reads the label and either starts fresh or resumes mid-spine, a superset of `resume`); a background supervisor loop **detects token rate limits and waits out a reset up to 4h away, then re-runs** — no human interaction. Ported from `sdd-plugin` `batch.md` (the verified rate-limit-resilient runner), adapted to Guild.

> **Status: partially live-validated (2026-07-14, 1 real batch of 2 issues) — shipped, with untested edges (Activation checklist item 5).** The two mechanisms below were confirmed on real traffic; **happy-path unattended completion to `guild:done` has not been re-verified since the exit-0 fix**, and split-parent-under-batch and the worktree path are still unexercised — so this does **not** read as fully validated. ✅ **rate-limit auto-resume** confirmed (a real limit hit → auto-waited ~115m → resumed, no lost work) · ✅ **`guild:needs-human` pause** confirmed (a scope-defining high-stakes discuss ambiguity → leader paused without guessing) · 🐛 **found + fixed a false-positive**: the supervisor trusted `claude -p` **exit 0** as "completed," but a headless turn can exit 0 while a backgrounded pre-commit hook leaves the Issue mid-spine (no commit/PR). Completion is now judged by the **GitHub label** (`guild:done` / `guild:children`), with `guild:needs-human` counted as PAUSED and a mid-spine exit-0 re-resumed (bounded) then surfaced as INCOMPLETE — never silently "succeeded." Wired across `_handoff.md` (Section H), `analyze.md`/`design.md`/`test.md`/`qa.md` (gate branches), `dev.md` (mode detect + PAUSE handling), `implement.md` (decision log + branch/PR resume), `init.md` (`guild:needs-human` label).

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
- **All-open mode** (`$1` empty): `gh issue list --state open --json number,title,labels --limit 200`; **exclude** `guild:done` (complete), `guild:child` (auto-discovered after parent) and **`guild:sprint`** (a sprint *container*, not work — developing it would analyze the sprint plan as a requirement and could open a PR for it; `_handoff.md` Section A). 
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

# Protect batch infra from subagents' `git stash -u` (local-only exclude, not .gitignore).
# Resolve the real exclude path via git itself rather than assuming ".git/info/exclude" —
# inside a git worktree (the setup this doc's own "Recommended" section pushes users toward),
# .git is a FILE (a `gitdir:` pointer), not a directory, so `.git/info` never exists there and
# an `[ -d ".git/info" ]` guard silently skips this whole block, leaving batch infra unprotected
# exactly where subagent stashing is expected. `git rev-parse --git-path` resolves correctly
# from both a normal checkout and a worktree (worktrees share the main checkout's info/exclude).
EXCLUDE="$(git rev-parse --git-path info/exclude 2>/dev/null || true)"
if [ -n "$EXCLUDE" ]; then
  mkdir -p "$(dirname "$EXCLUDE")"; touch "$EXCLUDE"
  for E in ".claude/guild/.gld-batch.sh" ".claude/guild/.batch-logs"; do
    grep -qxF "$E" "$EXCLUDE" || echo "$E" >> "$EXCLUDE"
  done
fi

# Self-delete on a COMPLETED run only (trap can't catch SIGKILL — then remove .gld-batch.sh
# manually). An earlier version deleted unconditionally on EXIT, so a batch that died — crash,
# Ctrl-C, a genuine failure — destroyed the very script needed to re-run it and to see what it
# was going to do. A run that did not finish keeps its script.
SCRIPT_PATH="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
COMPLETED=0
cleanup() {
  if [ "$COMPLETED" -eq 1 ]; then
    rm -f "$SCRIPT_PATH"; echo "[batch] Removed batch script"
  else
    echo "[batch] Run did not complete — script kept at $SCRIPT_PATH"
    echo "[batch] Re-run it to continue; each Issue resumes from its GitHub label."
  fi
}
trap cleanup EXIT INT TERM

BATCH_START=$(date +%s)
SUCCEEDED=0; FAILED=0; PAUSED=0; INCOMPLETE=0; FAILED_ISSUES=(); INCOMPLETE_ISSUES=()
# `set -u` + an EMPTY array: bash 3.2 (the macOS default /bin/bash) aborts an unguarded
# "${ISSUES[@]}" expansion with `ISSUES[@]: unbound variable` — verified. Phase 1 can
# legitimately select nothing (e.g. every open Issue is already guild:done), so exit cleanly
# rather than dying with a confusing bash error. The guarded `${#ARR[@]}` counts and the
# `"${QUEUE[@]:1}"` slice-to-empty below are both fine in 3.2 — also verified — so they need
# no such guard.
if [ ${#ISSUES[@]} -eq 0 ]; then
  echo "[batch] No qualifying issues — nothing to do."
  COMPLETED=1
  exit 0
fi
QUEUE=("${ISSUES[@]}"); SEEN=""
for n in "${ISSUES[@]}"; do SEEN="$SEEN #$n "; done
TOTAL=${#ISSUES[@]}; PROCESSED=0

echo "============================================================"
echo "  Guild Batch: ${#ISSUES[@]} initial issue(s) (queue may grow)"
echo "============================================================"

while [ ${#QUEUE[@]} -gt 0 ]; do
  ISSUE=${QUEUE[0]}; QUEUE=("${QUEUE[@]:1}")
  PROCESSED=$((PROCESSED + 1))
  ATTEMPT=0
  echo "[$PROCESSED/$TOTAL] Issue #$ISSUE → $LOG_DIR/issue-${ISSUE}-${TIMESTAMP}-attempt*.log"

  RESUME_TRIES=0; RL_TRIES=0
  while true; do
    ATTEMPT=$((ATTEMPT + 1))
    # Each attempt gets its OWN file (not overwritten by a retry) — a rate-limit wait or a
    # bounded re-resume both loop back to here, and `> "$LOG"` on a single shared filename
    # (an earlier version of this script did that) truncates the previous attempt's evidence
    # on every retry: the final cost/token summary below then only reflects the LAST attempt,
    # silently undercounting a multi-retry Issue, and Phase 4's "read the logs" report loses
    # what actually happened during the earlier rate-limited/incomplete attempts.
    LOG="$LOG_DIR/issue-${ISSUE}-${TIMESTAMP}-attempt${ATTEMPT}.log"
# ⚠ jq preflight, and it exercises the FILTER rather than the file. Rate-limit detection is
# the one thing in this script that depends on jq for a DECISION rather than for formatting, and
# a jq that is missing — or present but broken (an incompatible build, a shim, a wrapper) —
# makes it fail SILENTLY: the member falls through to the mid-spine arm and is recorded terminal,
# blocking every dependant. `command -v` alone passes for the broken case (measured). Every
# other jq use here is `gh --jq`, which gh implements itself.
if ! printf '{"type":"rate_limit_event","rate_limit_info":{"status":"x"}}\n' \
     | jq -r -R '(fromjson? // empty) | objects | .type // empty' 2>/dev/null | grep -q rate_limit_event; then
  echo "[batch] FAIL: a working jq is required — rate-limit detection cannot work without it" >&2
  exit 1
fi

WAIT_MAX=14400   # 4h ceiling on any single rate-limit wait; the shared region can
                 # report up to 30 days and this script sleeps with a bare `sleep`.
    EXIT_CODE=0
    # GLD_UNATTENDED=1: flow auto-proceeds discuss/verify gates (records assumptions) — see Notes.
    # --dangerously-skip-permissions: unattended tool calls (tests, hooks, push, PR).
    GLD_UNATTENDED=1 CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0 \
      claude -p --verbose --output-format stream-json --dangerously-skip-permissions \
      "/gld dev $ISSUE" > "$LOG" 2>&1 || EXIT_CODE=$?
    # /gld dev (not resume): dev Phase 1 reads the label and STARTS FRESH (analyze) on a
    # no-label Issue OR resumes from a mid-spine label — a superset of resume. This fixes
    # the batch gap where `/gld resume` punted fresh Issues to "run /gld dev" (no-op exit 0).

    # ⚠ In THIS file the fence and its handler sit ABOVE the `[ "$EXIT_CODE" -eq 0 ]` guard.
    # They used to sit below it, and every arm inside that guard ends in `break` or `continue`,
    # so on exit 0 the whole region was DEAD CODE: a rate-limited session that ended cleanly
    # burned three child sessions on re-resume and was recorded INCOMPLETE with the wrong cause
    # (measured end to end). /gld sprint's copy is placed the same way, asserted there by
    # `rlpos.py`; `cmp.py` compares these bytes but not their position, so this comment is the
    # only record on this side.
    # ⚠ Read the label BEFORE the fence, because the gate below needs it. This used to live
    # inside the exit-0 guard further down, where the arms themselves supplied the priority: they
    # ran first and every one of them breaks. Hoisting the fence above that guard inverted it, so
    # the priority now has to be stated explicitly.
    STATE=""
    if [ "$EXIT_CODE" -eq 0 ] && [ -n "$OWNER_REPO" ]; then
      STATE=$(gh issue view "$ISSUE" --repo "$OWNER_REPO" --json labels \
        --jq '[.labels[].name] | map(select(startswith("guild:"))) | join(",")' 2>/dev/null || true)
    fi
    # <!-- guild:supervisor-core:ratelimit -->
    # Rate-limit DETECTION + SANITISATION + WAIT — VERBATIM-shared with batch.md's supervisor
    # (tests/sprint_supervisor_test.sh compares them byte-for-byte after indent normalisation).
    # ⚠ PURE COMPUTATION, and it closes every `if` it opens. It used to leave
    # `if [ "$RATE_LIMITED" -eq 1 ]` open, so moving it as a unit swallowed whatever followed —
    # `bash -n` stays green and a completed member stops being counted (measured).
    #
    # ⚠ ONE jq pass, and it reads the LAST rate_limit_event, whichever status that one carries.
    # ⚠ `${RL_LAST##* }` strips to the LAST space. A status containing one ("rate limited") made
    # the single-`#` form hand the sanitiser "limited <epoch>", which it discarded (measured).
    # ⚠ `| tostring` on the STATUS too, not just the reset. A non-string status (`429`, `true`,
    # a list) makes jq's `+` fail, the line emits nothing, and `tail -1` silently falls back to
    # the previous — routine `allowed` — event. That needs no log corruption at all (measured).
    # `rate_limit_info.status` is CURRENT STATE telemetry, not an error record: a session that
    # was limited, waited, recovered and then died of something else carries a non-`allowed`
    # event followed by an `allowed` one. Selecting non-`allowed` events anywhere in the log
    # therefore hijacks a healthy member — six waits, then blocked, on every re-run (measured).
    # ⚠ And it must not be `.resetsAt // empty`: that DROPS the line for a live event that has
    # no resetsAt, so `tail -1` reaches back to an EARLIER event's value. A stale past reset then
    # masked a live unknown one and the exit-0 demotion below fired on it (measured).
    # ⚠ Parse the whole line FIRST and fall back to slicing — additive, not a replacement.
    # `$LOG` is `> "$LOG" 2>&1`, so stdout and stderr share one file offset: a stderr write with
    # no trailing newline (a `\r` progress spinner never emits one) is GLUED to the next JSON
    # line, and `jq -R` splits only on `\n`, so that whole line is unparseable and the limit
    # vanishes (measured). `rindex`, not `index`: two objects on one physical line leave the
    # FIRST offset pointing at a concatenation that cannot parse, while the last one is a
    # complete object (measured).
    RL_LAST=$(jq -r -R '(fromjson? // (.[(rindex("{\"type\":") // 0):] | fromjson?)) | objects | select(.type == "rate_limit_event") | .rate_limit_info | objects | (((.status // "null") | tostring) + " " + ((.resetsAt // "") | tostring))' "$LOG" 2>/dev/null | tail -1 || true)
    RATE_LIMITED=0
    RESET_AT=""
    case "$RL_LAST" in
      '')          ;;                      # no rate_limit_event in this log at all
      allowed*)    ;;                      # `allowed`, `allowed_warning`, … — not blocking
      *)           RATE_LIMITED=1; RESET_AT="${RL_LAST##* }" ;;
    esac
    # ⚠ `tail -1` is the last event jq could DECODE, not the last event that exists. One
    # unparseable event line therefore promotes an earlier routine `allowed` to the verdict — and
    # every real log carries one of those. Three shapes do it: a truncated final line (a SIGKILLed
    # child loses its last stdout buffer), an event split across two writes with stderr injected
    # between them, and any single line jq rejects.
    # ⚠ NO `rindex` fallback here, deliberately — the main filter has it, this must not. With it,
    # a line holding the limit FIRST and an ordinary object second slices to that second object,
    # which decodes cleanly, so `select(decode failed)` is false and the rescue is skipped — while
    # `tail -1` hands back an earlier routine `allowed`. The limit is not merely lost, the log's
    # own telemetry outranks it (measured). Here "did not decode AS A WHOLE" is exactly what
    # "the limit's bytes were lost" means.
    # ⚠ Scope the status to the tail after the LAST `"rate_limit_info":`, and treat a missing
    # status as a LOST limit rather than a healthy one. A corruption landing anywhere between the
    # field name and the end of the status token deletes the limit's own status while leaving an
    # earlier routine `allowed` as the last one on the line — an offset sweep over one event line
    # rescued only 33 of 89 cut points before this, 63 after. The `"type":"rate_limit_event"`
    # alternative catches cuts so early that the field name never completes. ⚠ The COLON matters:
    # `"rate_limit_info"` without it is prose naming the field (`KeyError: "rate_limit_info"`),
    # which used to fire. ⚠ `ltrimstr` chain, because `{ "status" : "rejected" }` is legal JSON. A first-match byte search is vetoed by an EARLIER `allowed`
    # fragment sharing the line with a truncated limit — two corruptions this file's own fixtures
    # assert separately — and it fires on plain stderr prose that merely names the field
    # (`KeyError: "rate_limit_info"`). Both measured, both through record_failure.
    # ⚠ Ask for exactly that: a line that FAILED to decode, carries the field, and does not say
    # allowed. Counting `"rate_limit_info"` matches with grep and comparing against the decoded
    # count looks equivalent and is not — it fires on healthy logs (stderr appended AFTER the
    # JSON on one line, `"rate_limit_info": null`, the field named in prose), overriding an
    # `allowed` verdict jq had read correctly and blocking the member on every re-run (measured).
    # ⚠ Additive either way: it can only turn detection ON, and a recovered limit is untouched
    # because there every line decodes.
    if [ "$RATE_LIMITED" -eq 0 ]; then
      RL_LOST=$(jq -r -R 'select((fromjson? // null) == null) | . as $l | select(index("\"rate_limit_info\":") or index("\"type\":\"rate_limit_event\"") or (($l|length) >= 12 and ("{\"type\":\"rate_limit_event\"" | startswith($l)))) | select((index("\"rate_limit_info\":") | not) or (.[(rindex("\"rate_limit_info\":")):] | (index("\"status\"") | not) or (.[(rindex("\"status\"")):] | ltrimstr("\"status\"") | ltrimstr(" ") | ltrimstr(":") | ltrimstr(" ") | startswith("\"allowed") | not))) | 1' "$LOG" 2>/dev/null | grep -c 1 || true)
      if [ "${RL_LOST:-0}" -gt 0 ]; then RATE_LIMITED=1; fi
    fi
    # Fallback text scan, for a genuinely rate-limited log that carried NO structured event.
    # ⚠ Gated on `EXIT_CODE != 0`. The regex is deliberately BROAD — a narrowed one missed four
    # of five real limit messages (measured) — and false positives are handled STRUCTURALLY
    # instead: the structured judgement above wins, and a normally-completed member never reaches
    # this line. Guild files themselves contain `rate limit`, and `$LOG` carries tool_result file
    # contents. "rate[ -]limit" (space/hyphen only, not an unescaped dot) still avoids matching
    # the literal JSON field name `rate_limit_event`, which appears on every log carrying a
    # routine status:"allowed" telemetry event.
    if [ "$RATE_LIMITED" -eq 0 ] && [ "$EXIT_CODE" -ne 0 ] \
       && grep -qi "rate[ -]limit\|usage limit reached\|rate_limit_error\|overloaded\|too many requests" "$LOG" 2>/dev/null; then
      RATE_LIMITED=1
    fi
    WAIT=""
    if [ "$RATE_LIMITED" -eq 1 ]; then
      # Sanitise resetsAt. Every step DISCARDS rather than trusts; a discarded value falls to
      # the bounded backoff below, which is always safe.
      case "$RESET_AT" in
        ''|*[!0-9]*)     RESET_AT="" ;;   # (1) ISO-8601, floats, `null`, and friends
        ??????????????*) RESET_AT="" ;;   # (1b) 14 digits or more
      esac
      # ⚠ (1b) is not cosmetic. `[ 99999999999999999999 -gt 100000000000 ]` exits 2 on bash 3.2
      # ("integer expression expected"), so (2) and (3) BOTH skip and `$(( ))` wraps to a huge
      # positive — an effectively unbounded wait. A 14-char glob, not `${#RESET_AT}`: every
      # comment stripper in this suite cuts at the first `#`.
      NOW=$(date +%s)
      if [ -n "$RESET_AT" ] && [ "$RESET_AT" -gt 100000000000 ]; then
        RESET_AT=$((RESET_AT / 1000))                              # (2) milliseconds
      fi
      if [ -n "$RESET_AT" ] && [ "$RESET_AT" -gt "$((NOW + 2592000))" ]; then
        RESET_AT=""                                                # (3) beyond now + 30 days
      fi
      if [ -n "$RESET_AT" ]; then
        WAIT=$((RESET_AT - NOW + 30))
        if [ "$WAIT" -lt 0 ]; then WAIT=0; fi                      # (4) already past
      fi
      # ⚠ exit 0 plus an already-past reset is a limit the CLI already waited out. Treating it
      # as live sends a `guild:children` member into an immediate retry in which the children
      # arm never runs, so SPLIT_PASSES/RESUME_TRIES stop advancing: the bound survives and
      # PROGRESS dies. ⚠ `-n` FIRST. Without it an UNKNOWN reset — a live event with no
      # resetsAt, an ISO-8601 value, or one (3) discarded — is demoted too, and those are live
      # limits that then land on `record_failure incomplete-mid-spine`.
      if [ "$EXIT_CODE" -eq 0 ] && [ -n "$WAIT" ] && [ "$WAIT" -le 0 ]; then RATE_LIMITED=0; fi
    fi
    # <!-- /guild:supervisor-core:ratelimit -->
    # ⚠ A member that reached a terminal label BEATS a rate limit found in its log. Without this
    # a `guild:done` Issue whose log merely CONTAINS a rate_limit_event is counted FAILED and six
    # waits are burned on work that is already finished (measured end to end, uncorrupted log).
    # /gld sprint states the same priority as a `case` before its handler.
    case "$STATE" in *guild:needs-human*|*guild:done* ) RATE_LIMITED=0 ;; esac
    # ⚠ Re-open the handling `if` here. The shared region above now closes every `if` it
    # opens (it used to leave this one open), so without this line the block below and its
    # `fi` are orphaned and the script is a syntax error.
    if [ "$RATE_LIMITED" -eq 1 ]; then
      # ⚠ The shared region can now hand back a wait of up to 30 days. This script sleeps with
      # a bare `sleep`, so a ceiling is required; /gld sprint blocks the member and lets the
      # re-run pick it up, which has no meaning here (no queue, no board) — so give up the run.
      if [ -n "$WAIT" ] && [ "$WAIT" -gt "$WAIT_MAX" ]; then
        echo "  ✗ Issue #$ISSUE — reset is $((WAIT/3600))h away, over the ${WAIT_MAX}s ceiling — giving up this run"
        FAILED=$((FAILED + 1)); FAILED_ISSUES+=("#$ISSUE (rate limited, reset beyond the ceiling)"); break
      fi
      # ⚠ `-le 0` stays, deliberately: a past reset backs off rather than retrying at once, which
      # is what this script wants — it has no queue to hand the member back to. The cap no longer
      # depends on it (the increment moved out of the no-reset branch just below), so the old
      # `sleep 0` argument for keeping it no longer applies; the reason above does.
      # ⚠ Advance and compare the counter on EVERY encounter, not only when no reset time was
      # reported. Inside the no-reset branch below, an API that keeps returning a usable
      # `resetsAt` never reached the cap and this loop had no bound at all.
      RL_TRIES=$((RL_TRIES + 1))
      if [ "$RL_TRIES" -gt 6 ]; then
        echo "  ✗ Issue #$ISSUE still rate limited after 6 waits — giving up this run"
        FAILED=$((FAILED + 1)); FAILED_ISSUES+=("#$ISSUE (rate limited, six waits spent)"); break
      fi
      if [ -z "$WAIT" ] || [ "$WAIT" -le 0 ]; then
        # No usable reset time (absent, non-numeric, or already past) → escalating capped
        # backoff, so a persistent limit waits instead of spinning or being mislabelled FAILED.
        WAIT=$((RL_TRIES * 300))
        # ⚠ Belt and braces, and say so: with RL_TRIES capped at 6 this is 1800s at most, so the
        # clamp is UNREACHABLE in any shipped configuration (instrumented: zero hits across both
        # suites). It exists because the ceiling above ran while WAIT was still empty and never
        # sees this value — so if the multiplier or the cap is ever raised, the bound is here
        # rather than nowhere. The multiplier itself is pinned separately.
        if [ "$WAIT" -gt "$WAIT_MAX" ]; then WAIT="$WAIT_MAX"; fi
        echo "  ⏳ Rate limited, no reset time reported. Backing off ${WAIT}s ($RL_TRIES/6)..."
      else
        RESET_TIME=$(date -r "$RESET_AT" +%H:%M:%S 2>/dev/null || date -d "@$RESET_AT" +%H:%M:%S 2>/dev/null || echo "?")
        echo "  ⏳ Rate limited. Waiting until ~$RESET_TIME ($((WAIT/60))m $((WAIT%60))s)..."
      fi
      sleep "$WAIT"
      echo "  🔄 Retrying Issue #$ISSUE (resume from GitHub state)..."
      continue
    fi
    if [ "$EXIT_CODE" -eq 0 ]; then
      # ⚠ exit 0 is NOT proof of completion — a headless `claude -p` turn can end while a
      # ⚠ Arm order below is the shell-side twin of `_handoff.md` Section A — canonical stage
      # derivation. A generated .sh cannot use that jq projection, so the same rule appears here
      # as `case` ordering: `guild:needs-human` must be tested BEFORE `guild:done`/`guild:children`
      # because bash `case` fires the first matching arm and those labels coexist on one Issue.
      # A new label kind therefore has to be reflected in THREE places — Section A, here, and
      # templates/sprint-supervisor.sh's arms (/gld sprint duplicates this script by design).
      # backgrounded pre-commit hook is still running, leaving the Issue mid-spine with no
      # commit/PR. Truth = the GitHub label (_handoff.md Section A: "labels are the state").
      if [ -z "$OWNER_REPO" ]; then
        echo "  ✓ Issue #$ISSUE (exit 0; state UNVERIFIED — no repo)"; SUCCEEDED=$((SUCCEEDED + 1)); break
      fi
      STATE=$(gh issue view "$ISSUE" --repo "$OWNER_REPO" --json labels \
        --jq '[.labels[].name] | map(select(startswith("guild:"))) | join(",")' 2>/dev/null || true)
      case "$STATE" in
        *guild:needs-human*)
          # MUST be checked before *guild:done*/*guild:children* below: guild:needs-human is
          # ADDITIVE (_handoff.md Section A) and can coexist with guild:children specifically
          # (dev.md Phase 2c: an integration gap found unattended marks needs-human but leaves
          # the parent at guild:children, still mid-orchestration). A bash `case` fires the
          # FIRST matching arm, not the most specific one — checking guild:children first (an
          # earlier version of this script did) would silently miscount a genuinely-stuck
          # split-parent as SUCCEEDED, since its STATE string contains both substrings.
          echo "  ⏸ Issue #$ISSUE paused (needs-human)"; PAUSED=$((PAUSED + 1)); break ;;
        *guild:done*)
          echo "  ✓ Issue #$ISSUE done"; SUCCEEDED=$((SUCCEEDED + 1))
          # Auto-discover child Issues (design split → guild:child + "Parent Issue: #N")
          CHILDREN=$(gh issue list --repo "$OWNER_REPO" --label guild:child --state all --limit 200 \
            --json number,body,labels \
            --jq "[.[] | select(.body | test(\"Parent Issue: #${ISSUE}([^0-9]|\$)\")) | select((.labels // []) | map(.name) | index(\"guild:done\") | not)] | .[].number" 2>/dev/null || true)
          for C in $CHILDREN; do
            case "$SEEN" in *" #$C "*) ;; *)
              SEEN="$SEEN #$C "; QUEUE+=("$C"); TOTAL=$((TOTAL + 1))
              echo "  + Discovered child #$C → queued (total $TOTAL)" ;;
            esac
          done
          break ;;
        *guild:children*)
          echo "  ✓ Issue #$ISSUE split (parent orchestration) — discovering children"; SUCCEEDED=$((SUCCEEDED + 1))
          CHILDREN=$(gh issue list --repo "$OWNER_REPO" --label guild:child --state all --limit 200 \
            --json number,body,labels \
            --jq "[.[] | select(.body | test(\"Parent Issue: #${ISSUE}([^0-9]|\$)\")) | select((.labels // []) | map(.name) | index(\"guild:done\") | not)] | .[].number" 2>/dev/null || true)
          for C in $CHILDREN; do
            case "$SEEN" in *" #$C "*) ;; *)
              SEEN="$SEEN #$C "; QUEUE+=("$C"); TOTAL=$((TOTAL + 1))
              echo "  + Discovered child #$C → queued (total $TOTAL)" ;;
            esac
          done
          break ;;
        *)
          # exited 0 but still mid-spine (or state unreadable) = NOT finished. Re-resume,
          # bounded (resume is state-safe — continues from the label). Then surface honestly.
          # The bound is TWO re-resumes: the counter is incremented BEFORE the test, so tries 1
          # and 2 loop back and try 3 falls through to INCOMPLETE. Written `-le 2` so the bound's
          # literal matches the `($RESUME_TRIES/2)` the message prints — the equivalent `-lt 3`
          # this used to say reads like a third re-resume that never actually happens (the same
          # literal-matches-message shape the RL_TRIES `-gt 6` / `($RL_TRIES/6)` pair already has).
          RESUME_TRIES=$((RESUME_TRIES + 1))
          if [ "$RESUME_TRIES" -le 2 ]; then
            echo "  ↻ Issue #$ISSUE exited at [${STATE:-unknown}] without finishing — re-resuming ($RESUME_TRIES/2)"
            continue
          fi
          echo "  ⚠ Issue #$ISSUE INCOMPLETE (stuck at ${STATE:-unknown} after re-resume)"
          INCOMPLETE=$((INCOMPLETE + 1)); INCOMPLETE_ISSUES+=("#$ISSUE (${STATE:-unknown})"); break ;;
      esac
    fi

    # Genuine failure (not rate limit)
    # ⚠ The jq below needs `|| true`. This script is `set -euo pipefail` and $LOG is
    # `> "$LOG" 2>&1`, so stderr is mixed in BY DESIGN — plain `jq` exits 5 on the first
    # non-JSON line, pipefail propagates it, and the assignment kills the whole run mid-queue:
    # every remaining Issue goes unrun and no summary is printed (measured). The supervisor's
    # twin has carried `|| true` for exactly this reason.
    # ⚠ `-R 'fromjson?'` here too, not just `|| true`. `|| true` stops the run from dying but
    # plain jq still stops at the first non-JSON line, and $LOG mixes stderr in BY DESIGN — a
    # member whose log has stderr at the head reported 0 tokens and $0, and its failure reason
    # came back empty (measured).
    echo "  ✗ Issue #$ISSUE failed (exit $EXIT_CODE)"; FAILED=$((FAILED + 1))
    REASON=$(jq -r -R 'fromjson? | objects | select(.type == "result") | select(.is_error == true) | .result // empty' "$LOG" 2>/dev/null | tail -1 | cut -c1-80 || true)
    FAILED_ISSUES+=("#$ISSUE (${REASON:-exit $EXIT_CODE})")
    break
  done
done

# --- Summary + token/cost aggregation from stream-json ---
BATCH_ELAPSED=$(( $(date +%s) - BATCH_START ))
TOTAL_IN=0; TOTAL_OUT=0; TOTAL_CR=0; TOTAL_CC=0; TOTAL_COST="0"
for L in "$LOG_DIR"/issue-*-"${TIMESTAMP}"-attempt*.log; do
  [ -f "$L" ] || continue
  S=$(jq -r -R 'fromjson? | objects | select(.type=="result") | "\(.usage.input_tokens // 0) \(.usage.output_tokens // 0) \(.usage.cache_read_input_tokens // 0) \(.usage.cache_creation_input_tokens // 0) \(.total_cost_usd // 0)"' "$L" 2>/dev/null | tail -1 || true)
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
# The run reached its own end — but the script is the artifact a re-run needs, so keep it when
# anything did not finish. A rate limit whose reset is beyond the ceiling gives up the run, and
# deleting the script then contradicts this file's own promise that an unfinished run keeps it.
# ⚠ `if`, not `A && B`: this is the script's LAST statement, and under `set -e` the `&&` form
# exits 1 whenever the test is false.
if [ "$((FAILED + INCOMPLETE))" -eq 0 ]; then COMPLETED=1; fi
```

## Phase 4 — Run in background + report
1. `chmod +x .claude/guild/.gld-batch.sh`.
2. Ensure `.claude/guild/.batch-logs/` won't be committed (the script already adds it to `.git/info/exclude` — that's the actual mechanism; `.claude/guild/.gitignore` only covers `memory/`, per `init.md`, so it does **not** also cover `.batch-logs/` — don't rely on it as a fallback here).
3. Execute via the **Bash tool with `run_in_background: true`**: `bash .claude/guild/.gld-batch.sh`.
4. Report: "Guild batch started (background). Issues: <N>. Logs: .claude/guild/.batch-logs/. Rate limits auto-wait+resume (up to a 4h reset). You'll be notified on completion." Give the `tail -f … | jq …` monitor hint.
5. On completion (harness re-invokes when the background task exits): read the logs, report per-Issue outcome + the summary block. Outcomes are **label-truthful** (Done / Paused-needs-human / Incomplete / Failed), not exit-code-based. **List paused Issues** (`gh issue list --label guild:needs-human --state open`) — resolve, then re-run `/gld dev`/`resume`. **List Incomplete Issues** (exited 0 mid-spine — a backgrounded hook or turn-end) — `/gld resume <n>` continues them from the label; their partial work is on the feature branch.

---

## Notes
- **How far each child goes (scope)**: each Issue runs the full spine to **`guild:done`** = code implemented + automated tests (verify) + agent-doable QA + **PR opened**. It does **NOT** merge the PR (human, INV1), does **NOT** do manual/visual QA (flagged for the human), and does not run guided `review` (on-demand). The deferred human gate lands at **PR review + merge** after the batch; the PR body carries the leader's "무인 결정 로그". High-stakes discuss ambiguity, an unresolved verify failure, or an execute-stage auditor `BLOCKER` that was neither fixed nor (being unattended) dismissible → the Issue is **paused (needs-human)**, not forced to done.
- **Rate-limit auto-resume (the point)**: the inner `while true` loop re-runs `/gld dev $ISSUE` after `sleep`ing until `rate_limit_info.resetsAt` (+30s). Because `dev` Phase 1 reads state from GitHub labels/comments/git (`_handoff.md` Sections A/B) — starting fresh on a no-label Issue and resuming from a mid-spine label otherwise — each retry continues from the last completed stage — no lost work, no human interaction. (The script invokes `dev`, not `resume`; the prose used to say `resume` and disagreed with the script it describes.)
- **★Companion — the leader stands in for the human at gates (`GLD_UNATTENDED`)**: unattended, the leader exercises *power of attorney* for in-flow gate decisions, but the human's real authority is **deferred to PR review, not removed** — nothing merges unattended (INV1). This is the plan's sprint principle ("사람 리뷰를 뒤로 미룰 뿐 없애지 않음") applied to batch. Rules:
  - **discuss gate (analyze/design)** — the leader classifies the ambiguity's stakes, **charter-anchored**:
    - *low/medium* (local, reversible interpretation) → pick the most charter/standards-aligned option, **record it as an explicit assumption** in the analyze/design output + PR body (`가정: … · 근거: … · 사람 확인 요`), then proceed.
    - *high* (scope-defining / materially different product) → **do NOT guess.** Pause: keep the label at the current stage, post a `<!-- guild:needs-human -->` comment listing the options, return a paused status; the supervisor counts it as PAUSED and moves to the next Issue.
  - **verify gate (test)** — deterministic: raw evidence green + AC covered → proceed; else bounded loop-back to execute (≤2); still failing → **pause (needs-human), never fake-pass** (INV2: no test weakening).
  - **qa gate (qa)** — same shape as verify: record the concern, bounded loop-back to execute if fixable, else **pause (needs-human)**; never force `done` on a blocking defect.
  - **Decision log** — every gate the leader auto-resolved is aggregated into the PR body ("무인 결정 로그") so the human's PR review is **informed, not blind**.
  - **Net**: leader decides low/medium judgments (anchored + logged), escalates high-stakes ones, and the human gate lands at **PR review + merge** after the batch.
  - **Wiring (done)**: `_handoff.md` Section H (policy + detection) · `analyze.md`/`design.md` (discuss classify+record vs pause) · `test.md`/`qa.md` (verify/QA deterministic + pause) · `dev.md` (mode detect; no `AskUserQuestion` when unattended; clean PAUSE) · `implement.md`/`debug.md`/`refactor.md` (PR decision log + resume-safe branch/PR) · `init.md` (`guild:needs-human` label). Authoritative policy = Section H.
- **Resume granularity**: cross-stage is safe (labels). Mid-`execute` interruption re-enters execute — `implement.md`/`debug.md`/`refactor.md` Step 0 detect an existing feature branch + build a **partial-work summary** (git log + one test run) passed into the worker, so it **continues from partial state rather than redoing work** (hardened).
- **Child auto-discovery**: matches `guild:child` Issues whose body has `Parent Issue: #<n>` (created by `design.md`'s multi-PR split). Keep the regex in sync if that reference string changes. ⚠ **Correction — the normal case does NOT need a manual follow-up.** `dev.md` Phase 2 routes `OK SPLIT` straight into Phase 2b **in the same session** (`dev.md` Notes: *"that parent and its children sequentially in one session (Phase 2b/2c)"*), and Phase 2b/2c drive every child, then run parent-integration automatically, closing the parent to `guild:done` — all within the **same** `claude -p "/gld dev <parent>"` invocation batch already runs. So in the uninterrupted case, batch sees the parent arrive at `guild:done` directly, with the split already fully resolved; **no manual `/gld dev <parent>` follow-up is needed.** The only case that still needs one is if orchestration was genuinely **interrupted mid-split** (a child paused/failed, or a Phase 2c integration gap) — then the parent is left at `guild:children` (possibly plus `guild:needs-human`, see the case-order note above) and a later `/gld dev <parent>`/`/gld resume <parent>` picks up where it stopped.
  - **Double-counting (fixed)**: both the `*guild:done*` and `*guild:children*` case arms' child auto-discovery queries filter on `,labels` and `select((.labels // []) | map(.name) | index("guild:done") | not)`, so a child already finished automatically during the parent's own in-session Phase 2b is never re-queued/re-invoked.
- **`_bash_rules.md` exception**: variable expansion inside the generated `.sh` is fine — the atomic-bash rule governs direct Bash-tool calls, not OS-level scripts. The script is one background Bash-tool invocation.
- **SIGKILL**: `trap` can't catch `kill -9`; then remove `.claude/guild/.gld-batch.sh` manually. No config backup/restore is needed (Guild uses `GLD_UNATTENDED` env, not a config-file toggle — simpler than sdd's `.sdd-config` swap).

## Activation checklist
1. ✅ `batch` added to `SKILL.md` valid commands + `help.md` line.
2. ✅ **`GLD_UNATTENDED` companion** wired in `_handoff.md` Section H + `analyze/design/test/qa/dev` gate branches (+ `implement.md` decision log).
3. ✅ `implement.md` mid-execute resume hardened (existing-branch/PR detection).
4. ✅ **Gating decision** (settled): `batch` **shipped ahead of `sprint`** — it is lower-risk because it drives one Issue set in one checkout, while `sprint` adds per-Issue worktrees, PR stacking and a retro that runs the Outer/evolve loop. (The readiness gate this item originally referred to was removed: it required `evolve`-accumulated data a young repo cannot have, so it could never open — `SKILL.md`.) The condition attached to that decision is that the **security note stays prominent** (the `--dangerously-skip-permissions` warning above, which it does). The decision is already in force, not pending: `batch` is a routed command in `SKILL.md`'s valid-command list and `help.md`, and it was run live on 2026-07-14 — this item was a stale open checkbox for a call that shipping had already made.
5. ✅ **End-to-end validation** (2026-07-14): real 2-issue batch confirmed rate-limit auto-resume + `guild:needs-human` pause; found + fixed the exit-0 false-positive (now label-based completion). **Untested edges**: happy-path *unattended* completion to `guild:done` was blocked by the false-positive (re-verify after the fix); split-parent under batch (nested orchestration); worktree path assumes a **committed** harness (an untracked/dev harness needs main-checkout — see Phase 1).
