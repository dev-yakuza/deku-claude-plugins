# AUTO

**In-session sequential processing of multiple Issues through the full SDD pipeline — thin FSM dispatcher.**

Arch B (v1.0.0): this file runs in the **main session** and acts as the FSM that drives the per-Issue stage chain. For each Issue: spawn ONE `bootstrap` sub-agent (state detection) → read + execute the appropriate stage wrapper command (`analyze.md` / `design.md` / `implement.md` / `test.md`) inline → repeat until the Issue reaches `sdd:done`. The stage wrappers themselves spawn ONE `stage_<X>` sub-agent each per `design/01-sub-agent-contract.md` §1.

Unlike `/sdd batch` (which spawns separate `claude -p` subprocesses), `/sdd auto` stays entirely on the Interactive subscription pool — unchanged by the 2026-06-15 billing split that moved `claude -p` to the new metered Agent SDK Credit pool.

> **Bash Command Execution**: see `<<SKILL_DIR>>/commands/atoms/_bash_rules.md`.

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

**Heuristic**: large queue or want to walk away → `/sdd batch`. Watching progress, want to stay on Interactive billing → `/sdd auto`. Rationale per `design/03-flow-design.md` §1.1.

### Practical limits

- Main-session context accumulates across Issues. Realistic ceiling depends on the complexity of each Issue's stages — measure with `/context` between Issues if running a large batch. For very large queues, prefer `/sdd batch`. Per-Issue main-session budget in Arch B is ~2,610 tokens (per `design/00-architecture.md` §5).
- If you interrupt the session (Cmd-Q, terminal close, kernel kill), temporary state files may be left behind. Recover via the hint printed in Phase 3.1 step 6 (`mv .github/.sdd-config.bak .github/.sdd-config`).
- The sandbox toggle (Phase 3.1 step 5) is **persistent by design**. The toggle path exits before the loop and leaves `sandbox.enabled = false` on disk with a `<SETTINGS_PATH>.sdd-auto.bak` snapshot. The backup is intentionally not auto-restored; revert with `mv <SETTINGS_PATH>.sdd-auto.bak <SETTINGS_PATH>`.

## Input Validation

Before any other step: validate `$1` per Common Definitions → Issue Validation in `<<SKILL_DIR>>/SKILL.md`. For `/sdd auto`, validation is per-Issue inside Phase 1 — the argument here is the **list** of Issue numbers, not a single number.

## Argument Parsing

Parse `$1`:
- Empty or not provided → **All open Issues** mode
- Comma-separated numbers (e.g. `1,2,3`) → **Specific Issues** mode

## Phase 1: Collect and Filter Issues

Apply the **same Phase 1 logic as `/sdd batch`** — see `<<SKILL_DIR>>/commands/batch.md` "Phase 1: Collect and Filter Issues" (the All-open vs Specific-Issues filter rules, the `sdd:done` / `sdd:child` exclusion semantics, per-Issue validation in Specific-Issues mode, sort order, the "No qualifying Issues" early exit). Apply identical rules; the only differences are display strings and the worktree warning below.

### Display: Confirmation block

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

Stage label: no SDD label → `[new]`; SDD label → show it.

### Worktree note

`/sdd auto` runs in-session in the user's current checkout. The worktree recommendation from `/sdd batch` does **not apply**. However, if the working tree is dirty, warn the user:

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
- The note about "claude -p sessions" should be replaced with: "Stage sub-agents inherit this main session's permissions. The Phase 1/2 confirmation flows still prompt for user input — only the per-stage AI review skipping is automated by the temporary `skip-review` override."

Everything else is identical to `/sdd batch` Phase 2 and reused verbatim.

## Phase 3: Sequential In-Session Loop

The main session itself runs the loop. **No shell script is generated. No `claude -p` is spawned.**

### 3.1 Pre-loop setup (main session)

1. Resolve owner/repo once for child Issue discovery:
   ```bash
   gh repo view --json nameWithOwner -q .nameWithOwner
   ```
   Observe owner/repo from output; inline as `<owner>/<repo>` in Phase 3.3 (no shell variables). If empty → warn the user; continue but disable child auto-discovery.

2. Back up `.github/.sdd-config`:
   - Read existing `.github/.sdd-config` (if any) via the Read tool.
   - Copy its contents to `.github/.sdd-config.bak` via the Write tool (so the file exists on disk for the recovery hint).
   - If no existing `.sdd-config`, do NOT create `.sdd-config.bak`.

3. Write temporary skip-review (5 keys — the `qa` key is what differentiates auto from batch):
   ```
   skip-review: analyze,design,implement,pr,qa
   ```
   to `.github/.sdd-config` (via the Write tool). This makes every per-Issue stage sub-agent auto-proceed without user confirmation — including manual QA at the end of `stage_test` (which would otherwise block the loop indefinitely waiting for human input). `/sdd auto` is by design **unattended**; the user reviews PRs and QA evidence on GitHub after the loop completes.

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
               SOME built-in heuristic safety prompts (find -exec, heredocs,
               multi-line `# ...` in CLI args, recursive `find /`, etc.)
               are bypassed for the duration of /sdd auto:

                 claude --dangerously-skip-permissions

               ⚠ The flag disables MANY in-session safety prompts for the
                 ENTIRE session — not just /sdd auto. Any accidental
                 dangerous command (rm -rf, credential file access, etc.)
                 will run without confirmation. Only use it for the
                 duration of /sdd auto; restart in normal mode afterwards.

               ⚠ Some Bash heuristics remain UNSUPPRESSIBLE even with the
                 flag (verified empirically v1.1.x — see
                 `spec/edge-cases.md` §26 + `spec/00-common-contracts.md`
                 §8 UNSUPPRESSIBLE rows): compound shell syntax (`;`, `|`,
                 `&&`, `||`, `for ... do ... done`), output redirection
                 (`2>/dev/null`, `> file`, `&> file`), `${VAR}` inside
                 quoted args, and `find` against absolute paths outside
                 repo root. Sub-agent compliance with §8 is the only
                 complete defense. Expect occasional user prompts for
                 safe read-only operations even under the flag — answer
                 'Yes' to proceed.
            3. Re-run /sdd auto. The new sandbox state is honored from
               session start, so subagents' `gh` / `git push` calls no
               longer trigger sandbox-bypass prompts. The flag eliminates
               most (not all) heuristic prompts — see §26 for the
               residual set.

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
   (Omit the `.sdd-config` line if no `.sdd-config.bak` was created in step 2. The sandbox toggle path exits in step 5e, so there is no in-loop sandbox state to recover.)

### 3.2 Loop body (main session FSM)

Per `design/03-flow-design.md` §1.2 / §1.6. Maintain in-memory state in the main session's narrative:

- `QUEUE` — ordered list of Issue numbers from Phase 1 (FIFO)
- `SEEN` — set of every Issue ever queued (prevents duplicate child enqueues)
- `TOTAL_TARGETS` — initial `len(QUEUE)`, grows when children are discovered
- `PROCESSED_COUNT`, `SUCCEEDED`, `FAILED` — counters
- `FAILED_ISSUES` — list of `(number, reason)` tuples for the final summary
- `BATCH_START` — `date +%s` at loop start, for elapsed wall time

For each Issue while `QUEUE` is non-empty:

1. Pop `ISSUE` from front; increment `PROCESSED_COUNT`.
2. Print: `[<PROCESSED_COUNT>/<TOTAL_TARGETS>] Processing Issue #<ISSUE>...` (substitute the literal counter values and Issue number before printing — no shell variables).

3. **Spawn bootstrap** to determine the Issue's current stage. Use the Agent tool:
   - `subagent_type`: `general-purpose`
   - `model`: `haiku` (bootstrap is lightweight read-only state detection)
   - `description`: `bootstrap dispatch for #<ISSUE>`
   - `prompt`:
     > Read `<<SKILL_DIR>>/commands/atoms/bootstrap.md` and execute its instructions for Issue #<ISSUE>.
     > Return EXACTLY one line in the contract specified by that file (the `>>> RESULT <<<` BOOTSTRAP: line).

   Parse the `>>> RESULT <<<` line:
   - `FAIL: <reason>` → `FAILED += 1`; append `(ISSUE, reason)` to `FAILED_ISSUES`; continue to next Issue.
   - `BOOTSTRAP: stage=<X> depth=<dial> branch=<...> pr=<...> parent=<bool> children=<...>` → continue to step 4.

   Remember the parsed fields for the rest of this iteration.

4. **Dispatch on `stage`**:

   - **`done`** → Issue is already complete. `SUCCEEDED += 1`. Print: `Issue #<ISSUE> already complete.` Run child auto-discovery (§3.3), then continue to next Issue.

   - **`implement-parent`** → parent paused at `sdd:implement` with children present. For each child number in the `children` field, read its current label:
     ```bash
     gh issue view <child-N> --json labels --jq '[.labels[].name]'
     ```
     Print a progress summary (one line per child showing its current `sdd:<stage>`). Because `/sdd auto`'s skip-review covers all five keys (including `implement`), the surrounding flow handles parent-pause silently: do NOT prompt the user. Treat as `SUCCEEDED += 1` (parent stop is a success state for auto's queue) and continue. Children are picked up by §3.3 auto-discovery on the parent's iteration or were already queued earlier.

   - **`analyze` / `design` / `implement` / `test`** → drive the stage chain by reading the matching command wrapper inline and executing its instructions. The wrapper performs its own Phase 0 depth check + spawns the single `stage_<X>` sub-agent + handles label transition on `OK ADVANCE` (with skip-review consulted to chain into the next stage by inline-reading the next wrapper). Because all five skip-review keys are set, the chain auto-advances label-by-label inside the main session without user prompts, stopping when the Issue reaches `sdd:done`.

     - `analyze` → read `<<SKILL_DIR>>/commands/analyze.md` and execute its instructions for Issue #<ISSUE>.
     - `design` → read `<<SKILL_DIR>>/commands/design.md` and execute its instructions for Issue #<ISSUE>.
     - `implement` → read `<<SKILL_DIR>>/commands/implement.md` and execute its instructions for Issue #<ISSUE>.
     - `test` → read `<<SKILL_DIR>>/commands/test.md` and execute its instructions for Issue #<ISSUE>.

     The wrapper command IS the right entry point in Arch B v1.0.0 — it does the direct-invocation label check + Phase 0 depth + stage_<X> spawn + label transition + skip-review-driven chain to the next wrapper. Do NOT spawn `stage_<X>` directly from auto.md; always go through the command wrapper so its idempotent label check + chain logic runs.

   On chain completion (`sdd:done` reached, or terminal `OK BACK_TO_IMPLEMENT`, or `OK PARENT_STOP` from `implement`, or `OK PAUSE` after a Pause-from-ESCALATE path) → `SUCCEEDED += 1` if the Issue reached a clean terminal state. On any `FAIL:` returned through the wrapper chain → `FAILED += 1`, append `(ISSUE, <one-line reason>)` to `FAILED_ISSUES`. **Do not abort the entire queue on single-Issue failure** — per `design/03-flow-design.md` §9.1.

5. Run **child auto-discovery** (§3.3 below) after a successful Issue. Continue the loop.

**ESCALATE under `/sdd auto`** — should not occur because all five skip-review keys are set; if it does (configuration mismatch), the implement wrapper's T1.8 batch-conversion (`design/03-flow-design.md` §7.3, `commands/implement.md` Phase 2 `ESCALATE` branch) converts to a clean PAUSE-equivalent exit with findings persisted on the PR.

### 3.3 Child auto-discovery

After each successful Issue, run the same `gh issue list --label sdd:child` query as `/sdd batch`'s Phase 3 logic. Use the canonical multilingual parent-reference regex from `<<SKILL_DIR>>/commands/atoms/_multilingual.md` (the `(Parent|상위 |親)Issue: #<n>` form with the `([^0-9]|$)` boundary).

**Mandatory: literal-value substitution** (per `<<SKILL_DIR>>/commands/atoms/_bash_rules.md`, items 6 + 9, and `design/03-flow-design.md` §1.7). Do NOT pass `${ISSUE}` inside a quoted argument — the `${...}` + quote combination trips Claude Code's "brace with quote character — expansion obfuscation" heuristic, which `permissions.allow`, `--dangerously-skip-permissions`, and `sandbox.enabled = false` cannot suppress.

The main-session narrative substitutes the literal Issue number and literal `<owner>/<repo>` (already resolved in §3.1 step 1) into a single simple line:

```bash
gh issue list --repo deku-word-app/word_app --label sdd:child --state open --limit 200 --json number,body --jq '[.[] | select(.body | test("(Parent|상위 |親)Issue: #838([^0-9]|$)"))] | .[] | .number'
```

(Example shows the literal `deku-word-app/word_app` and `#838` — substitute the actual repo and current `ISSUE` value before the Bash tool call. No `\` line continuations, no shell variables. The outer single-quote `'...'` keeps everything inside literal, so jq receives the regex unchanged. The `$` at the end of the character class is jq's end-of-string anchor; do NOT escape or wrap it.)

For each discovered child number not in `SEEN`:
- Append to `QUEUE`
- Add to `SEEN`
- Increment `TOTAL_TARGETS`
- Print: `+ Discovered child Issue #<N> → queued (total now <TOTAL_TARGETS>)`

### 3.4 Cleanup (try/finally semantics)

**Ordering invariant — load-bearing, from `spec/edge-cases.md` §7 / GAP-A6**: cleanup MUST be the **FIRST step** the main session does after the loop exits or after an in-loop fatal error. Any post-loop reporting, summary printing, sandbox status logging, or token telemetry that runs *before* cleanup risks leaving a stale `.github/.sdd-config` on disk if the reporting code itself errors. Phase 3.5 (final summary) MUST run AFTER Phase 3.4.

1. If `.github/.sdd-config.bak` exists:
   - Read its contents (via Read tool)
   - Write them back to `.github/.sdd-config` (via Write tool)
   - Delete `.github/.sdd-config.bak` (via Bash `rm`)
2. Else (no original config existed): delete `.github/.sdd-config` (via Bash `rm`).
3. **Sandbox & permission-flag post-loop status check** (cleanup does NOT modify the sandbox setting — §3.1 step 5e is the only path that writes it, and that path exits before the loop):
   - Re-read the settings file at the priority order from §3.1 step 5a (`.claude/settings.local.json`, `.claude/settings.json`, `~/.claude/settings.json` — the first one that has a `sandbox` key).
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

> **Cleanup limitation**: If the user **hard-kills** Claude Code (Cmd-Q, terminal close, kernel kill) mid-loop, this cleanup cannot run. The on-disk `.sdd-config.bak` is left behind. The recovery hint printed at §3.1 step 6 tells the user how to manually restore it. The `.sdd-auto.bak`, when present, is the sandbox-pre-toggle snapshot from step 5e and is *intentionally* persistent — only the user decides when (or whether) to restore it.

### 3.5 Final summary

After cleanup (NEVER before), print:

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

(Sandbox status: show `disabled — restart in NORMAL mode (no --dangerously-skip-permissions) recommended` if step 3 of §3.4 found `sandbox.enabled == false`. Show `enabled` if it is true. §3.1 step 5e never reaches §3.5 because it exits before the loop. The "restart in NORMAL mode" wording is intentional — the user is likely running with `--dangerously-skip-permissions` per the step 5e re-launch guidance, and that flag should not persist beyond /sdd auto.)

Token / cost aggregation is **not** included — the main session does not have access to per-subagent usage data the way `/sdd batch`'s stream-json logs do. Users wanting cost visibility can check `/cost` in this Claude Code session.

## Notes

- **Thin FSM dispatcher.** Per `design/03-flow-design.md` §1.1, auto.md is a main-session FSM body. Each Issue iteration spawns ONE bootstrap sub-agent + reads + executes ONE stage wrapper command inline (which spawns ONE `stage_<X>` sub-agent). The orchestrator-reads-orchestrator pattern is gone in Arch B v1.0.0.
- **Skip-review override is temporary and 5-key.** Pre-loop writes `analyze,design,implement,pr,qa`; cleanup restores the original config. The `qa` key is what differentiates auto's skip-review from batch's (4 keys) — auto must skip the manual QA gate to remain unattended. AI review still runs in every stage sub-agent (skip-review only suppresses user-confirmation gates per `spec/01-config.md` §2).
- **Sandbox toggle is opt-in and persistent — forces a restart.** §3.1 step 5e exits before the loop on approval; cleanup does NOT auto-restore the sandbox snapshot. Per `spec/edge-cases.md` §3, sandbox-bypass prompts are an UNSUPPRESSIBLE Claude Code safeguard that `permissions.allow` cannot auto-approve — the toggle is the only way to silence them.
- **`--dangerously-skip-permissions` is the companion flag.** Step 5e instructs the user to re-launch with this flag because, even after `sandbox.enabled = false`, the main session still applies built-in heuristic safety prompts (e.g. `find -exec`, heredocs, multi-line `# …` in CLI args, recursive `find /`) that `permissions.allow` cannot auto-approve. Cleanup explicitly reminds the user to quit and re-launch in NORMAL mode after `/sdd auto` completes.
- **Sequential only.** Parallel Issue processing is intentionally unsupported — parallel subagents consume the subscription quota N× faster, defeating the in-session billing advantage.
- **Child Issue handling.** Parents stop at `sdd:implement` after design creates children (per `spec/00-common-contracts.md` §1); §3.3 auto-discovery queues the children, which then progress through the full pipeline themselves.
- **Failures are tolerated.** A failure on one Issue does not abort the queue (per `design/03-flow-design.md` §9.1). The user can re-run `/sdd auto <failed-numbers>` afterwards to retry. Crash recovery is manual — re-run `/sdd auto <remaining-numbers>`; bootstrap re-detects each Issue's stage from on-GitHub state (per `spec/edge-cases.md` §7).
- **Cleanup MUST be FIRST.** Ordering invariant — §3.4 always precedes §3.5 even on in-loop fatal error.
