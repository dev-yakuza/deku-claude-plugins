# AUTO

**In-session sequential processing of multiple Issues through the full SDD pipeline.**

Each Issue runs end-to-end (analyze → design → implement → PR) in the **current Claude Code session** via the orchestrator/atom architecture. Unlike `/sdd batch` (which spawns separate `claude -p` subprocesses), `/sdd auto` stays entirely on the Interactive subscription pool — unchanged by the 2026-06-15 billing split that moved `claude -p` to the new metered Agent SDK Credit pool.

> **Bash Command Execution**: every shell snippet below is its own simple Bash tool call — no `&&`, `||`, `;`, `|`, `2>/dev/null`, `2>&1`, `>file`, `$(...)`, `VAR=$(...)`, or heredocs. For codebase exploration use the **Grep / Glob / Read** tools — do NOT use Bash `find` against `/`, `~`, `/Users`, or any path outside the repo root. See **Bash Command Execution Rules** in `<<SKILL_DIR>>/SKILL.md`.

## When to use /sdd auto vs /sdd batch

| Axis | `/sdd batch` | `/sdd auto` |
|---|---|---|
| Execution model | Generates `.sdd-batch.sh`; each Issue runs in a fresh `claude -p` child session | Main Claude Code session loops over Issues in-process |
| Billing pool (post 2026-06-15) | Agent SDK Credit pool (metered at API list prices, no rollover) | Interactive subscription pool (unchanged) |
| Claude Code app required after start | No — close it; the shell script runs unattended | **Yes** — keep this session open until the loop completes |
| Permission prompts during run | Bypassed (`--dangerously-skip-permissions`) | Normal main-session prompts apply; opting into the sandbox toggle (`sandbox.enabled = false`) eliminates per-command bypass confirmations from the *next* session onward — the toggle path exits and asks the user to restart Claude Code |
| Cleanup robustness on Ctrl-C | Strong (shell `trap`) | Weak (in-session try/finally; hard kill loses cleanup) |
| Logs | Per-Issue stream-json log files | Inline in the Claude Code transcript |
| Child Issue auto-discovery | Yes | Yes |

**Heuristic**: large queue or want to walk away → `/sdd batch`. Watching progress, want to stay on Interactive billing → `/sdd auto`.

## Practical limits

- Main-session context accumulates across Issues. Realistic ceiling depends on the complexity of each Issue's stages — measure with `/context` between Issues if running a large batch. For very large queues, prefer `/sdd batch`.
- If you interrupt the session (Cmd-Q, terminal close, kernel kill), temporary state files may be left behind. Recover with:
  ```bash
  # If you had an original .sdd-config before the run:
  mv .github/.sdd-config.bak .github/.sdd-config
  ```
  The sandbox toggle (Phase 3.1 step 5) is now **persistent by design** — the toggle path exits before the loop and leaves `sandbox.enabled = false` on disk along with a `<SETTINGS_PATH>.sdd-auto.bak` snapshot of the original setting. The backup is *intentionally* not auto-restored; you can revert any time with:
  ```bash
  mv .claude/settings.local.json.sdd-auto.bak .claude/settings.local.json
  # (replace path with whichever settings file the sandbox toggle modified)
  ```

## Input Validation

Before any other step: validate `$1` per Common Definitions → Issue Validation in `<<SKILL_DIR>>/SKILL.md`. (For `/sdd auto`, the validation is per-Issue inside the loop — the argument here is the **list** of Issue numbers, not a single number.)

## Argument Parsing

Parse `$1`:
- Empty or not provided → **All open Issues** mode
- Comma-separated numbers (e.g. `1,2,3`) → **Specific Issues** mode

## Phase 1: Collect and Filter Issues

Apply the **same Phase 1 logic as `/sdd batch`** — see `<<SKILL_DIR>>/commands/batch.md` "Phase 1: Collect and Filter Issues" (the All-open vs Specific-Issues filter rules, the `sdd:done` / `sdd:child` exclusion semantics, sort order, the "No qualifying Issues" early exit). Apply identical rules; the only differences are display strings and the worktree warning.

### Per-Issue validation (Specific-Issues mode only)

When the user provides `1,2,3` (Specific-Issues mode), validate each number per Common Definitions → Issue Validation in `<<SKILL_DIR>>/SKILL.md`. For each:

```bash
gh issue view <n> --json url --jq .url
```

- Empty/error → number does not exist; warn and exclude.
- URL contains `/pull/` → number is a PR, not an Issue; warn the user and exclude. SDD commands operate on Issues only.
- URL contains `/issues/` → valid Issue; include for filtering.

(All-open-Issues mode uses `gh issue list --state open`, which already returns only Issues, so this step is implicit there.)

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
Skip-review: analyze, design, implement, pr, qa (auto-enabled — restored when loop ends)
Child auto-queue: enabled (children created by a parent are appended to the queue)
Sandbox toggle: you will be prompted before the loop (optional — temporarily disables sandbox to skip per-command bypass confirmations; restored at cleanup)
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

Apply the **same Phase 2 logic as `/sdd batch`** — see `<<SKILL_DIR>>/commands/batch.md` "Phase 2: Verify Tool Permissions" (project marker detection, the three permission groups: Required / Recommended / Test Runners, the merge-into-settings logic on confirmation). The recommended baseline allowlist is identical because the SDD pipeline needs the same tools whether the orchestrator runs in `claude -p` or in this main session.

### Difference from `/sdd batch`

- The preamble note about `--dangerously-skip-permissions` does **not** apply. In `/sdd auto`, normal main-session permission gates run for every tool call. The allowlist reused from `batch.md` Phase 2 is a recommendation; if missing, you will see permission prompts during the loop (which breaks "unattended within session").

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
   gh repo view --json nameWithOwner -q .nameWithOwner    # Bash call 1: observe owner/repo from output; inline as <owner>/<repo> below (no shell variables)
   ```
   If empty → warn the user; continue but disable child auto-discovery.

2. Back up `.github/.sdd-config`:
   - Read existing `.github/.sdd-config` (if any) via the Read tool.
   - Copy its contents to `.github/.sdd-config.bak` via the Write tool (so the file exists on disk for the recovery hint).
   - If no existing `.sdd-config`, do NOT create `.sdd-config.bak`.

3. Write temporary skip-review:
   ```
   skip-review: analyze,design,implement,pr,qa
   ```
   to `.github/.sdd-config` (via the Write tool). This makes every per-Issue stage orchestrator auto-proceed without user confirmation — including manual QA at the end of `/sdd test` (which would otherwise block the loop indefinitely waiting for human input). `/sdd auto` is by design **unattended**; the user reviews PRs and QA evidence on GitHub after the loop completes.

4. Append `.github/.sdd-config` and `.github/.sdd-config.bak` to `.git/info/exclude` if not already present (idempotent check), so subagents' `git stash -u` does not stash these files mid-run.

5. **Sandbox disable (optional, prompted — toggle requires Claude Code restart, so /sdd auto exits afterwards)**:

   The main session honors permission gates per tool call. In projects whose `gh` / `git push` paths require `dangerouslyDisableSandbox: true` per call (e.g. corporate TLS proxy environments), every such call triggers a sandbox-bypass confirmation that **cannot be auto-approved via `settings.json`'s `permissions.allow`** — it is a separate Claude Code safeguard. To make `/sdd auto` truly unattended in those environments, the user can opt to **disable the sandbox** in their settings file.

   ⚠ **Important — sandbox changes require a Claude Code restart to take effect.** Mid-session toggling does not silence the bypass prompts in the *current* session — the runtime is still using the sandbox state from session start. Therefore, when the user approves the toggle, `/sdd auto` writes the new setting, **rolls back its other pre-loop changes, and exits with a restart instruction** instead of entering the loop. The user then restarts Claude Code and re-runs `/sdd auto`, at which point the new sandbox state is honored from session start (step 5c path) and the loop runs without bypass prompts.

   a. **Locate the settings file** that holds (or will hold) the `sandbox` config. Check in priority order:
      - `.claude/settings.local.json` (project-local, gitignored)
      - `.claude/settings.json` (project-shared)
      - `~/.claude/settings.json` (user-global)

      Use the first file that has a `sandbox` key (or a `sandbox.enabled` nested key). If none of the three contain `sandbox` → fall back to `.claude/settings.local.json` (create it with `{ "sandbox": { "enabled": false } }` on opt-in; do NOT create it on opt-out).

      Remember the chosen path as `SETTINGS_PATH` for later cleanup.

   b. **Determine current state** by reading `SETTINGS_PATH`:
      - File missing OR `sandbox` key absent OR `sandbox.enabled == true` → sandbox is currently **ON**.
      - `sandbox.enabled == false` → sandbox is currently **OFF**.

   c. **If sandbox is already OFF** → skip the prompt. Log: `Sandbox already disabled — no toggle needed.` Do NOT create a backup. Proceed to step 6.

   d. **If sandbox is ON** → ask the user (use AskUserQuestion or equivalent confirmation):

      ```
      Sandbox is currently enabled.

      In this project, `dangerouslyDisableSandbox: true` calls (e.g. `gh` operations
      in projects with TLS-proxy conflicts) each trigger a confirmation prompt that
      cannot be auto-approved via settings.json.

      /sdd auto can set `sandbox.enabled = false` in:
        <SETTINGS_PATH>

      ⚠ Sandbox changes require a Claude Code restart to take effect.
        If you approve, /sdd auto will write the new setting, save a backup
        of the original value, AND THEN EXIT — it will NOT enter the loop in
        this session. You will need to:

          1. Quit Claude Code (Cmd-Q on macOS).
          2. Re-launch Claude Code.
          3. Re-run /sdd auto.

        After restart, the loop runs without sandbox-bypass prompts.

      ⚠ Warning: while sandbox is disabled, all Bash commands run without sandbox
        isolation. Only proceed if you trust the project's allowlisted commands.

        If you ever want to revert, restore the backup:
          mv <SETTINGS_PATH>.sdd-auto.bak <SETTINGS_PATH>

      Disable sandbox and exit (so you can restart and re-run)? [y/N]
      ```

   e. **On approval**:
      - Read `SETTINGS_PATH` via the Read tool (or treat as empty `{}` if the file does not exist).
      - Write its verbatim contents to `<SETTINGS_PATH>.sdd-auto.bak` via the Write tool. If the file did not exist, write the literal string `__SDD_AUTO_NO_ORIGINAL__\n` to the `.bak` file as a sentinel so a future restore-from-bak knows to delete (not restore) the file. Remember this sentinel rule.
      - In memory, set `sandbox.enabled = false`. Preserve all other keys at every level (e.g. `permissions`, `sandbox.autoAllowBashIfSandboxed`). If the `sandbox` key did not exist, create it as `{ "enabled": false }`.
      - Write the modified JSON back to `SETTINGS_PATH` via the Write tool (2-space indentation; preserve existing key order where reasonable).
      - If `SETTINGS_PATH` is **inside the repo** (e.g. `.claude/settings.local.json`), append `<SETTINGS_PATH>.sdd-auto.bak` to `.git/info/exclude` if not already present (idempotent).
      - **Roll back the pre-loop changes from steps 1–4 (sandbox setting stays at `false`):**
        - If `.github/.sdd-config.bak` was created in step 2: restore it to `.github/.sdd-config` (read + write), then delete the `.bak`.
        - Else (no original config existed): delete `.github/.sdd-config`.
        - The `.git/info/exclude` entries added in step 4 are harmless to leave (idempotent on next run).
      - Show the user:
        ```
        ✓ Sandbox has been set to false in <SETTINGS_PATH>.
          Backup of the original setting: <SETTINGS_PATH>.sdd-auto.bak

        ⚠ The change requires a Claude Code restart to take effect.
          /sdd auto cannot proceed correctly in this session because the
          runtime is still using the old (enabled) sandbox state.

          Next steps:
            1. Quit Claude Code (Cmd-Q on macOS).
            2. Re-launch Claude Code WITH the --dangerously-skip-permissions
               flag so that, in addition to honoring the new sandbox state,
               built-in heuristic safety prompts (find -exec, heredocs,
               multi-line `# ...` in CLI args, recursive `find /`, etc.)
               are also bypassed for the duration of /sdd auto:

                 claude --dangerously-skip-permissions

               ⚠ The flag disables ALL in-session safety prompts for the
                 ENTIRE session — not just /sdd auto. Any accidental
                 dangerous command (rm -rf, credential file access, etc.)
                 will run without confirmation. Only use it for the
                 duration of /sdd auto; restart in normal mode afterwards.
            3. Re-run /sdd auto. The new sandbox state is honored from
               session start, so subagents' `gh` / `git push` calls no
               longer trigger sandbox-bypass prompts, AND the flag
               eliminates the remaining heuristic prompts.

          After /sdd auto finishes, quit Claude Code and re-launch in
          NORMAL mode (without --dangerously-skip-permissions) to restore
          per-call safety prompts. The cleanup phase (3.4) will remind you.

          To revert sandbox later:  mv <SETTINGS_PATH>.sdd-auto.bak <SETTINGS_PATH>
        ```
      - **Terminate /sdd auto** — do NOT continue to step 6 or Phase 3.2.

   f. **On rejection**: continue without the toggle. Do NOT create any backup. Log: `Sandbox left enabled — sandbox-bypass prompts will occur for `gh` / `git push` calls during the loop.`

6. Print the recovery hint **before** entering the loop. Show only the lines that apply:
   ```
   If this session is interrupted, restore your state with:
     mv .github/.sdd-config.bak .github/.sdd-config            # if .sdd-config.bak exists
   ```
   (Omit the `.sdd-config` line if no `.sdd-config.bak` was created in step 2. The sandbox toggle path now exits immediately in step 5e, so there is no in-loop sandbox state to recover.)

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
3. **Dispatch via resume.md** — read `<<SKILL_DIR>>/commands/resume.md` and execute its instructions for Issue `<ISSUE>`. The dispatcher inspects Issue labels + comments + PRs, then reads + executes the appropriate stage orchestrator (`analyze.md` / `design.md` / `implement.md` / `test.md`). Because the temporary skip-review setting includes `analyze,design,implement,pr`, each orchestrator auto-advances label-by-label until the stage chain stops at `sdd:test` (post-PR) or `sdd:done` (no-action analyze, or finished test).
4. On success → mark `SUCCEEDED += 1`. Run **child auto-discovery** (3.3 below).
5. On unrecoverable failure → mark `FAILED += 1`, append `(ISSUE, <one-line reason>)` to `FAILED_ISSUES`. Continue to the next Issue — do **not** abort the entire queue.

### 3.3 Child auto-discovery

After each successful Issue, run the same `gh issue list --label sdd:child` query as `/sdd batch`'s Phase 3 logic. Use the multi-language parent-reference regex from `batch.md`.

**Important — substitute literal values before invoking Bash.** Per the **Bash Command Execution Rules** in `<<SKILL_DIR>>/SKILL.md`, do NOT pass shell variable substitutions like `${ISSUE}` inside a quoted argument. The combination of `${...}` and surrounding quotes trips a Claude Code argument heuristic ("brace with quote character — expansion obfuscation") that cannot be suppressed by `permissions.allow`, `--dangerously-skip-permissions`, or `sandbox.enabled = false`.

Instead, the main-session narrative substitutes the literal issue number and literal `<owner>/<repo>` (already resolved in Phase 3.1 step 1) into the command, producing a single simple line:

```bash
gh issue list --repo deku-word-app/word_app --label sdd:child --state open --limit 200 --json number,body --jq '[.[] | select(.body | test("(Parent|상위 |親)Issue: #838([^0-9]|$)"))] | .[] | .number'
```

(Example shows the literal `deku-word-app/word_app` and `#838` — substitute the actual repo and current `ISSUE` value before the Bash tool call. No `\` line continuations, no shell variables. The outer single-quote `'...'` keeps everything inside literal, so jq receives the regex unchanged. The `$` at the end of the character class is jq's end-of-string anchor; do NOT escape or wrap it.)

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
3. **Sandbox & permission-flag post-loop status check** (cleanup does NOT modify the sandbox setting — step 5e is the only path that writes it, and that path exits before the loop):
   - Re-read the settings file at the priority order from Phase 3.1 step 5a (`.claude/settings.local.json`, `.claude/settings.json`, `~/.claude/settings.json` — the first one that has a `sandbox` key).
   - If `sandbox.enabled == false` in that file:
     - Show:
       ```
       ⚠ Sandbox is currently disabled in <SETTINGS_PATH>.
         For correctness and safety, ensure Claude Code is running with this
         setting from session start. If you have not restarted Claude Code
         since the toggle, please do so before running /sdd auto again.

         (Restoring sandbox: mv <SETTINGS_PATH>.sdd-auto.bak <SETTINGS_PATH>)

       ⚠ If you launched Claude Code with --dangerously-skip-permissions
         for this /sdd auto run (as recommended by step 5e of Phase 3.1),
         the flag is STILL ACTIVE for the rest of this session. The flag
         disables ALL in-session permission prompts — including the
         built-in heuristic safety checks for `find -exec`, heredocs,
         multi-line `# ...` in CLI args, recursive `find /`, etc.

         RECOMMENDED: quit Claude Code now and re-launch in NORMAL mode
         (without --dangerously-skip-permissions) for any further work in
         this project. Normal mode restores per-call safety prompts.
       ```
   - If `sandbox.enabled == true` (or unset): nothing to show.

> **Cleanup limitation**: If the user **hard-kills** Claude Code (Cmd-Q, terminal close, kernel kill) mid-loop, this cleanup cannot run. The on-disk `.sdd-config.bak` is left behind. The recovery hint printed at 3.1 step 6 tells the user how to manually restore it. The `.sdd-auto.bak`, when present, is the sandbox-pre-toggle snapshot from step 5e and is *intentionally* persistent — only the user decides when (or whether) to restore it.

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
Sandbox:         <enabled | disabled — restart in NORMAL mode (no --dangerously-skip-permissions) recommended | unchanged>
Next steps:      review PRs and QA evidence on GitHub (manual QA was auto-skipped because /sdd auto runs unattended)
```

(Sandbox status: show `disabled — restart in NORMAL mode (no --dangerously-skip-permissions) recommended` if step 3 of 3.4 found `sandbox.enabled == false`. Show `enabled` if it is true. Step 5e never reaches Phase 3.5 because it exits before the loop, so the "restored" wording is no longer used. The "restart in NORMAL mode" wording is intentional — the user is likely running with `--dangerously-skip-permissions` per the step 5e re-launch guidance, and that flag should not persist beyond /sdd auto.)

Token / cost aggregation is **not** included — the main session does not have access to per-subagent usage data the way `/sdd batch`'s stream-json logs do. Users wanting cost visibility can check `/cost` in this Claude Code session.

## Notes

- **In-session execution.** Every orchestrator (`analyze.md`, `design.md`, `implement.md`, `test.md`, `resume.md`) and every atom runs in this same Claude Code session. Atoms are spawned via the Agent tool by orchestrators; the spawning layer is single-level (orchestrator → atoms), so there are no nested-subagent issues.
- **Skip-review override is temporary.** The pre-loop step writes `skip-review: analyze,design,implement,pr`; cleanup restores the original config. AI review still runs in every stage (skip-review only suppresses user-confirmation prompts).
- **Sandbox toggle is opt-in and persistent — and forces a restart.** When the user approves the Phase 3.1 step 5 prompt, `sandbox.enabled` is flipped to `false` in the chosen settings file with a backup, the pre-loop changes (skip-review config) are rolled back, and `/sdd auto` **exits without entering the loop**. This is because Claude Code only honors `sandbox.enabled` at session start; toggling mid-session does not silence the bypass prompts in the current session. The user restarts Claude Code and re-runs `/sdd auto`, at which point sandbox is already disabled at session start (step 5c path) and the loop proceeds without `gh` / `git push` bypass prompts. Cleanup (Phase 3.4) does **not** automatically restore sandbox — that decision is left to the user via `mv <SETTINGS_PATH>.sdd-auto.bak <SETTINGS_PATH>`. The toggle is the only way to eliminate per-command `dangerouslyDisableSandbox` confirmations in projects that need sandbox bypass (e.g. TLS-proxy environments) — those confirmations are a Claude Code safeguard that `permissions.allow` cannot auto-approve. If the user rejects the toggle (or sandbox was already disabled), `/sdd auto` runs as normal.
- **`--dangerously-skip-permissions` is the companion flag.** Step 5e (Phase 3.1) instructs the user to re-launch Claude Code with `--dangerously-skip-permissions` because, even after `sandbox.enabled` is `false`, the main session still applies built-in heuristic safety prompts (e.g. `find -exec`, heredocs with quoted braces, multi-line `# …` in CLI args, recursive `find /`) that `permissions.allow` cannot auto-approve. The flag bypasses all of these for the session and is the only way to make `/sdd auto` fully unattended in the main session. Because the flag applies to ALL tool calls in the session (not just /sdd auto), the cleanup phase (3.4 step 3) explicitly instructs the user to quit and re-launch in NORMAL mode after /sdd auto completes, so per-call safety prompts are restored for the rest of their work in the project.
- **Sequential only.** Parallel processing of Issues is intentionally not supported — official Claude Code docs warn that parallel subagents consume the subscription quota N× faster, which would defeat the in-session advantage.
- **Child Issue handling.** Parents stop at `sdd:implement` after design creates children (per `design.md`); the auto-discovery in 3.3 queues the children, which then progress through the full pipeline themselves.
- **Failures are tolerated.** A failure on one Issue does not abort the loop. The orchestrator records the failure and continues. The user can re-run `/sdd auto <failed-numbers>` after the run to retry.
