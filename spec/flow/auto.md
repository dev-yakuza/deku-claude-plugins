# Flow: Auto

In-session sequential processing of multiple Issues through the full SDD pipeline. Sources: `commands/auto.md`.

---

## 1. Comparison: `/sdd auto` vs `/sdd batch` [PRESERVE]

Both commands iterate a queue of Issues and dispatch each through `resume.md`. The architectural difference is **where the dispatcher runs**.

| Axis | `/sdd batch` | `/sdd auto` |
|---|---|---|
| Execution model | Generates `.github/.sdd-batch.sh`; each Issue runs in a fresh `claude -p` child session | Main Claude Code session loops over Issues in-process |
| Billing pool (post 2026-06-15) | **Agent SDK Credit pool** — metered at API list prices, no rollover | **Interactive subscription pool** — unchanged by the split |
| Claude Code app required after start | No — close it; the shell script runs unattended | **Yes** — keep the session open until the loop completes |
| Permission prompts during run | Bypassed via `--dangerously-skip-permissions` | Normal main-session gates apply; sandbox toggle (§5 of phase 3.1) eliminates per-command bypass confirmations from the *next* session onward |
| Cleanup robustness on Ctrl-C | Strong — shell `trap` covers EXIT/INT/TERM | Weak — in-session try/finally only; hard kill loses cleanup |
| Logs | Per-Issue stream-json log files under `.github/.sdd-batch-logs/` | Inline in the Claude Code transcript |
| Child Issue auto-discovery | Yes (in-script jq) | Yes (main-session narrative) |
| Cost aggregation | jq across `result` events in logs | Not available (no per-subagent usage from main session) |

**Heuristic**: large queue or want to walk away → `/sdd batch`. Watching progress, want to stay on Interactive billing → `/sdd auto`.

### Why the dual command remains justified post-2026-06-15 split [PRESERVE — rationale]

The June 2026 billing split moved `claude -p` (and the Agent SDK) onto a **new metered Agent SDK Credit pool**, separate from the Interactive subscription pool used by the main Claude Code app. Before the split, `/sdd batch` was an unattended-runtime preference; after the split, it is also a **billing-pool choice**:

- `/sdd auto` keeps the entire pipeline on the Interactive pool — users who pay a flat subscription want this for cost predictability.
- `/sdd batch` consumes Agent-SDK credits — users who need unattended runs (walk away, multi-hour queues, Cmd-Q safe) accept metered billing.

Removing either command would force users into a billing pool they did not pick.

[PRESERVE: dual command is justified by the billing split + cleanup-robustness gap. Do not collapse to one.]

[RETHINK: the "post-2026-06-15" framing is timestamped. If Anthropic changes the pool structure again, this rationale section needs revision. Treat as a dated note, not an evergreen invariant.]

### Practical limits (auto-specific) [PRESERVE]

- Main-session context accumulates across Issues. The realistic ceiling depends on per-Issue complexity. Measure with `/context` between Issues on large queues; prefer `/sdd batch` if context approaches limit.
- Hard-kill (Cmd-Q, terminal close, kernel kill) skips cleanup. Recovery hint is printed before the loop starts (§3.1 step 6).

---

## 2. Input Validation [PRESERVE]

Per `00-common-contracts.md` §10: `/sdd auto` validates per-Issue *inside* the loop (the argument is a comma-separated list, not a single number).

---

## 3. Argument Parsing [PRESERVE]

Parse `$1`:
- Empty or not provided → **All open Issues** mode
- Comma-separated numbers (e.g. `1,2,3`) → **Specific Issues** mode

---

## 4. Phase 1: Collect and Filter Issues [PRESERVE — shared with batch]

Identical to `/sdd batch` Phase 1 (see `spec/flow/batch.md` §4). Summary:

### All-open mode
- `gh issue list --state open --json number,title,labels --limit 200`
- Exclude `sdd:done` (already completed).
- Exclude `sdd:child` (children are auto-queued after parent runs).
- Sort by Issue number ascending.

### Specific-Issues mode
- For each number: `gh issue view <n> --json url --jq .url`. Empty/error → exclude with warning. URL contains `/pull/` → PR, warn and exclude (SDD operates on Issues only). URL contains `/issues/` → valid.
- Then: `gh issue view <n> --json number,title,labels,state` per included number.
- Exclude `sdd:done` (warn user that the listed Issue is already done).
- **Include** `sdd:child` (user explicitly listed it; respect intent).
- Sort by Issue number ascending.

Empty post-filter → "No qualifying Issues found." stop.

### Confirmation block (display-only difference vs batch)

```
SDD Auto (in-session sequential)
════════════════════════════════
Issues to process (in order):

  #10: Add user authentication       [new]
  #11: Fix pagination bug             [sdd:design]
  #12: Refactor logging module        [sdd:implement]

Total: 3 issues (queue may grow as parent Issues spawn children)
Mode: Sequential (each in the current main session)
Skip-review: analyze, design, implement, pr, qa (auto-enabled — restored when loop ends)
Child auto-queue: enabled
Sandbox toggle: you will be prompted before the loop (optional)
```

Stage label: no SDD label → `[new]`; SDD label → show it.

### Worktree note (differs from batch) [PRESERVE]

`/sdd auto` runs in-session in the user's current checkout — no separate process. The worktree recommendation from `/sdd batch` Phase 1 does **not apply**. Instead:

- Run `git status --porcelain` (single Bash call).
- If non-empty, warn:
  ```
  Uncommitted changes detected in the working tree.
  /sdd auto will create branches and commits per Issue. Uncommitted changes
  may interfere with branch switches. Proceed anyway? [y/N]
  ```
- No → stop.

Then ask the standard "Proceed? [y/N]". Reject → stop without entering the loop.

[PRESERVE: dirty-tree warning is the in-process equivalent of batch's worktree recommendation.]

---

## 5. Phase 2: Verify Tool Permissions [PRESERVE — shared with batch, reference 01-config.md]

Apply the **same Phase 2 logic as `/sdd batch`** (see `spec/flow/batch.md` §5 and `spec/01-config.md` §7). The recommended baseline allowlist is identical because the SDD pipeline needs the same tools regardless of whether the orchestrator runs in `claude -p` or in the main session.

### Auto-specific differences

- **No `--dangerously-skip-permissions` preamble.** In `/sdd auto`, normal main-session permission gates run for every tool call. The allowlist reused from `batch.md` is a recommendation; if missing, you will see permission prompts during the loop (which breaks "unattended within session").
- **Display header**:
  ```
  Tool permissions for /sdd auto (in-session sequential)
  ════════════════════════════════════════════════════════
  ```
- **Note replacement**: replace any "claude -p sessions" wording with: "Subagents inside the orchestrators inherit this main session's permissions. The Phase 1/2 confirmation flows still prompt for user input — only the per-stage AI review skipping is automated by the temporary `skip-review` override."

Everything else (project marker detection table, three groups: Required / Recommended / Test Runners, merge-into-settings.local.json) is identical to `/sdd batch` Phase 2 and reused verbatim.

---

## 6. Phase 3.1: Pre-Loop Setup [PRESERVE — except §6.5 sandbox toggle is RETHINK]

The main session itself runs the loop. **No shell script is generated. No `claude -p` is spawned.**

### Step 1: Resolve owner/repo [PRESERVE]

```
gh repo view --json nameWithOwner -q .nameWithOwner
```

Observe the literal output; inline as `<owner>/<repo>` in every subsequent `gh api` call (per `00-common-contracts.md` §11). Empty → warn the user; continue but **disable child auto-discovery** for the run.

### Step 2: Back up `.github/.sdd-config` [PRESERVE]

- Read existing `.github/.sdd-config` via the Read tool (if any).
- Copy contents to `.github/.sdd-config.bak` via the Write tool (file exists on disk for the recovery hint).
- If no existing `.sdd-config`, do NOT create `.sdd-config.bak`.

### Step 3: Write temporary skip-review [PRESERVE — load-bearing for unattended]

Write to `.github/.sdd-config`:

```
skip-review: analyze,design,implement,pr,qa
```

This makes every per-Issue stage orchestrator auto-proceed without user confirmation — **including manual QA at the end of `/sdd test`** (which would otherwise block the loop indefinitely waiting for human input). `/sdd auto` is by design **unattended**; the user reviews PRs and QA evidence on GitHub after the loop completes.

[PRESERVE: writing `qa` into skip-review makes the loop run unattended through QA to `sdd:done`. Both `/sdd auto` and `/sdd batch` now use 5-key skip-review including `qa` — both run fully unattended.]

### Step 4: Append `.git/info/exclude` entries [PRESERVE — idempotent]

Per `01-config.md` §8, append (if not already present):
- `.github/.sdd-config`
- `.github/.sdd-config.bak`

(Plus `<SETTINGS_PATH>.sdd-auto.bak` after step 5e, if the sandbox path runs.)

Rationale: prevent subagent `git stash -u` from stashing these files mid-run.

### Step 5: Sandbox disable (optional, prompted — exits before loop) [RETHINK]

See `01-config.md` §4 for the canonical sandbox-toggle contract. Summary of the auto-side behavior:

1. **Locate settings file** in priority order: `.claude/settings.local.json` → `.claude/settings.json` → `~/.claude/settings.json`. Use first with a `sandbox` key. If none → fall back to `.claude/settings.local.json` (create on opt-in only).
2. **Determine current state** by reading the chosen file. File missing OR `sandbox` absent OR `sandbox.enabled == true` → sandbox is ON. `sandbox.enabled == false` → sandbox is OFF.
3. **If sandbox already OFF** → skip prompt entirely. Log "Sandbox already disabled — no toggle needed." Proceed to step 6.
4. **If sandbox ON** → ask user via `AskUserQuestion` with the warning text covering: (a) why sandbox bypass cannot be auto-approved via `permissions.allow`, (b) the settings path being modified, (c) **the mandatory restart**, (d) the optional `--dangerously-skip-permissions` companion flag, (e) the backup path, (f) the warning about disabled sandbox isolation.
5. **On approval (5e path)**:
   - Snapshot original settings to `<SETTINGS_PATH>.sdd-auto.bak` (or sentinel `__SDD_AUTO_NO_ORIGINAL__\n` if file did not exist).
   - In memory: set `sandbox.enabled = false`, preserve all other keys; write back to settings file (2-space indent).
   - If `SETTINGS_PATH` is in-repo, append `.sdd-auto.bak` to `.git/info/exclude`.
   - **Roll back the pre-loop changes from steps 2–4** (sandbox setting stays at false):
     - If `.github/.sdd-config.bak` was created in step 2 → restore it to `.github/.sdd-config`, delete the `.bak`.
     - Else → delete `.github/.sdd-config`.
     - The `.git/info/exclude` entries from step 4 are harmless to leave (idempotent on next run).
   - Print the next-steps instruction block (Quit / Re-launch with `--dangerously-skip-permissions` / Re-run `/sdd auto`).
   - **Terminate `/sdd auto`** — do NOT continue to step 6 or Phase 3.2.
6. **On rejection**: continue without the toggle; do NOT create any backup. Log "Sandbox left enabled — sandbox-bypass prompts will occur for `gh` / `git push` calls during the loop."

[RETHINK: this step occupies ~190 lines in the source `auto.md`. The exit-before-loop design is correct (sandbox state is only honored at session start), but the on-screen instruction blocks duplicate text between the prompt body and the post-write confirmation. Candidates: (a) extract the explanatory text into a template file referenced by both phases, (b) reduce to a single warning + linkable doc URL, (c) keep verbose because users only ever hit this path once. Maintainability cost: editing the prompt requires touching three near-identical text blobs in the source command.]

[RETHINK: investigate whether Claude Code provides a per-tool sandbox-bypass allowlist that would eliminate this whole flow. If it ever does, this section collapses.]

### Step 6: Print recovery hint [PRESERVE]

Before entering the loop, show only the lines that apply:

```
If this session is interrupted, restore your state with:
  mv .github/.sdd-config.bak .github/.sdd-config            # if .sdd-config.bak exists
```

(Omit the `.sdd-config` line if no `.bak` was created in step 2. The sandbox toggle path exits in step 5e, so there is no in-loop sandbox state to recover from.)

---

## 7. Phase 3.2: Loop Body [PRESERVE]

Maintain in-memory state in the main session's narrative (no on-disk persistence):

| Variable | Purpose |
|---|---|
| `QUEUE` | Ordered Issue numbers from Phase 1 (FIFO) |
| `SEEN` | Set of every Issue ever queued (prevents duplicate child enqueues) |
| `TOTAL_TARGETS` | Initial `len(QUEUE)`; grows as children are discovered |
| `PROCESSED_COUNT` | Running counter |
| `SUCCEEDED` | Counter |
| `FAILED` | Counter |
| `FAILED_ISSUES` | List of `(number, reason)` tuples |
| `BATCH_START` | `date +%s` at loop start, for elapsed wall time |

### Loop semantics

While `QUEUE` is non-empty:

1. Pop `ISSUE` from front; increment `PROCESSED_COUNT`.
2. Print `[$PROCESSED_COUNT/$TOTAL_TARGETS] Processing Issue #<ISSUE>...`.
3. **Dispatch via `resume.md`** — read `<<SKILL_DIR>>/commands/resume.md` and execute its instructions for Issue `<ISSUE>`. The dispatcher inspects labels + comments + PRs and routes to the appropriate stage orchestrator (`analyze.md` / `design.md` / `implement.md` / `test.md`). Because the temporary skip-review setting covers `analyze,design,implement,pr,qa`, each orchestrator auto-advances label-by-label until the stage chain stops at `sdd:done`.
4. On success → `SUCCEEDED += 1`. Run **child auto-discovery** (§8 below).
5. On unrecoverable failure → `FAILED += 1`, append `(ISSUE, <one-line reason>)` to `FAILED_ISSUES`. Continue to the next Issue — do **not** abort the entire queue.

[PRESERVE: failure tolerance is the contract — one bad Issue must not poison the queue.]

[PRESERVE: dispatch via `resume.md` (not directly to a stage orchestrator) is what makes resume from any state work.]

---

## 8. Phase 3.3: Child Auto-Discovery [PRESERVE]

After each successful Issue, query `gh` for child Issues that reference the just-completed parent.

### Mandatory: literal-value substitution (per `00-common-contracts.md` §8) [PRESERVE]

Do NOT pass shell variable substitutions like `"...${ISSUE}..."` inside a quoted argument. The combination of `${...}` and surrounding quotes trips Claude Code's "brace with quote character — expansion obfuscation" heuristic. This heuristic is **UNSUPPRESSIBLE** by `permissions.allow`, `--dangerously-skip-permissions`, or `sandbox.enabled = false`.

Instead, the main-session narrative substitutes the literal Issue number and the literal `<owner>/<repo>` (from §6.1) before invoking Bash:

```
gh issue list --repo deku-word-app/word_app --label sdd:child --state open --limit 200 --json number,body --jq '[.[] | select(.body | test("(Parent|상위 |親)Issue: #838([^0-9]|$)"))] | .[] | .number'
```

(Example shows literal `deku-word-app/word_app` and `#838` — substitute the actual repo and current `ISSUE` before the Bash tool call. No `\` line continuations, no shell variables, no compound operators.)

The regex `(Parent|상위 |親)Issue: #<n>([^0-9]|$)` is the canonical multilingual parent reference per `02-multilingual.md` §3. The `([^0-9]|$)` boundary prevents `#683` matching `#6831`. The `$` inside the character class is jq's end-of-string anchor — do NOT escape or wrap it.

[PRESERVE: literal substitution + boundary regex are both load-bearing.]

### For each discovered child not in `SEEN` [PRESERVE]

- Append to `QUEUE`
- Add to `SEEN`
- Increment `TOTAL_TARGETS`
- Print: `+ Discovered child Issue #<N> → queued (total now $TOTAL_TARGETS)`

---

## 9. Phase 3.4: Cleanup (try/finally semantics) [RETHINK — partial-failure robustness]

Run at the end of the loop **and** on any abort (user types "cancel" during a sub-prompt, fatal error from a stage orchestrator).

**Ordering invariant** [PRESERVE — load-bearing, from Reviewer A GAP-A6]: Cleanup MUST be the **FIRST step** the main session does after the loop exits or after an in-loop fatal error. Any post-loop reporting/logging that runs before cleanup risks leaving a stale `.sdd-config` on disk if the reporting code itself errors. Rewrite must preserve this ordering even when reporting is restructured.

### Steps [PRESERVE]

1. If `.github/.sdd-config.bak` exists:
   - Read its contents via Read tool
   - Write them back to `.github/.sdd-config` via Write tool
   - Delete `.github/.sdd-config.bak` via Bash `rm`
2. Else (no original config existed): delete `.github/.sdd-config` via Bash `rm`.
3. **Sandbox & permission-flag post-loop status check** — cleanup does NOT modify the sandbox setting; step 5e is the only path that writes it, and that path exits before the loop. Re-read the settings file at the priority order from §6.5 step 1.
   - If `sandbox.enabled == false`: show the disabled-state notice (recommend restarting in NORMAL mode to restore per-call safety prompts; restore-from-bak instruction).
   - If `sandbox.enabled == true` (or unset): nothing to show.

### Hard-kill limitation [PRESERVE]

If the user hard-kills Claude Code (Cmd-Q, terminal close, kernel kill) mid-loop, this cleanup cannot run. The on-disk `.sdd-config.bak` is left behind. The recovery hint printed at §6.6 tells the user how to manually restore it. `.sdd-auto.bak`, when present, is the sandbox-pre-toggle snapshot from step 5e and is *intentionally* persistent — only the user decides when (or whether) to restore it.

[RETHINK: cleanup robustness against partial failures.]
- **Soft kill (Ctrl-C in the orchestrator)**: orchestrator returns control to main session — cleanup runs. Good.
- **Hard kill (Cmd-Q)**: cleanup does not run. The recovery hint at §6.6 is the only safety net. Better-than-nothing, but compare to `/sdd batch`'s shell `trap` which catches EXIT/INT/TERM.
- **Mid-cleanup failure (e.g. Write tool errors on step 1)**: there is no defensive handling. The function may leave `.sdd-config` in an inconsistent state.
- **Suggested rewrite**: wrap step 1 in defensive re-check (does the source `.bak` still exist? does the target write succeed? log on each). Consider a `cleanup-state.json` written before each step so a re-run of `/sdd auto` can detect "previous cleanup interrupted, finish it first."

---

## 10. Phase 3.5: Final Summary [PRESERVE]

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
Sandbox:         <enabled | disabled — restart in NORMAL mode (no --dangerously-skip-permissions) recommended | unchanged>
Next steps:      review PRs and QA evidence on GitHub (manual QA was auto-skipped because /sdd auto runs unattended)
```

### Sandbox status [PRESERVE]
- `disabled — restart in NORMAL mode ...` if step 3 of cleanup found `sandbox.enabled == false`.
- `enabled` if it is true.
- The "restored" wording is no longer used because step 5e exits before the loop.

### Cost aggregation [PRESERVE — not available]

Token / cost aggregation is **not** included — the main session does not have access to per-subagent usage data the way `/sdd batch`'s stream-json logs do. Users wanting cost visibility check `/cost` in this Claude Code session.

[RETHINK: if Claude Code adds a main-session usage API, this section can report tokens like batch does. Track upstream.]

---

## 11. Crash Recovery [PRESERVE — manual]

`/sdd auto` has no on-disk crash-recovery state. If the session is interrupted:

1. The recovery hint at §6.6 reminds the user to `mv .github/.sdd-config.bak .github/.sdd-config` if the `.bak` exists.
2. The user re-runs `/sdd auto <remaining-numbers>` to continue. Because state lives on GitHub (`00-common-contracts.md` §2), `resume.md` will pick up each Issue from its last on-GitHub state.
3. Sandbox `.sdd-auto.bak` is intentionally persistent — the user restores manually.

[RETHINK: a checkpoint file (`/tmp/sdd-auto-state-<pid>.json` updated after each Issue) would enable "/sdd auto --resume-from-checkpoint" so users do not need to remember which Issues completed. The current "re-run with remaining numbers" works because `resume.md` is idempotent, but is a manual step.]

---

## 12. Notes [PRESERVE]

- **In-session execution.** Every orchestrator (`analyze.md` / `design.md` / `implement.md` / `test.md` / `resume.md`) and every atom runs in the same Claude Code session. Atoms are spawned via the Agent tool by orchestrators; spawning is single-level (`00-common-contracts.md` §12).
- **Skip-review override is temporary.** Pre-loop writes `analyze,design,implement,pr,qa`; cleanup restores the original config. AI review still runs in every stage (skip-review only suppresses user-confirmation gates per `01-config.md` §2).
- **Sandbox toggle is opt-in and persistent — forces restart.** See §6.5 / `01-config.md` §4 for the contract. Cleanup does **not** automatically restore sandbox — that decision is left to the user.
- **`--dangerously-skip-permissions` is the companion flag.** Recommended by step 5e to bypass remaining heuristic prompts (e.g. `find -exec`, heredocs, multi-line `# …` in CLI args). Cleanup phase explicitly reminds the user to quit and re-launch in NORMAL mode after `/sdd auto` completes.
- **Sequential only.** Parallel processing of Issues is intentionally not supported — official Claude Code docs warn that parallel subagents consume the subscription quota N× faster, defeating the in-session advantage.
- **Child Issue handling.** Parents stop at `sdd:implement` after `design` creates children (per `00-common-contracts.md` §1); the §8 auto-discovery queues the children, which then progress through the full pipeline themselves.
- **Failures are tolerated.** A failure on one Issue does not abort the loop. The user can re-run `/sdd auto <failed-numbers>` after the run to retry.

---

## Cross-references

- Common contracts → `spec/00-common-contracts.md`
- Configuration (skip-review, sandbox, allowlist baseline) → `spec/01-config.md`
- Multilingual parent regex → `spec/02-multilingual.md` §3
- Dispatcher → `spec/flow/resume.md`
- Sibling loop command → `spec/flow/batch.md`
