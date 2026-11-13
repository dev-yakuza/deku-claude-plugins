# CONFIG

**Guild configuration.** View and adjust settings in `.claude/guild/config.json`. `config` turns dials; `init` builds the house. Off-switch for automation lives here (user escape hatch).

Parse `$1` onward:
- No arguments → **show current config**.
- `--language=<code>` → set `language` (`en`/`ko`/`ja`).
- `--evolve-nudge=<on|off>` → set `automation.evolve_nudge` (default `on`). This dial gates the **review-stage evolve nudge** (`review.md` Step 5 — the advisory "신호가 충분히 쌓였습니다, `/gld evolve` 적기" reminder). `off` silences it entirely; the review nudge reads this flag before evaluating its 충분/cooldown gate. (evolve itself is always run manually — there is no *automatic* evolve trigger; this switch only controls the reminder.)
- `--gates=<on|off>` → set `gates.enabled` (M3 강제층 off-switch). `off` makes the commit gate advisory (no blocking) — the escape hatch. `on` (default) blocks secret / verification-weakening commits, in **all three** of its wirings (`.git/hooks/pre-commit`, the `PreToolUse(Bash)` early warning, and the `--guard-config` control-file guard). `off` also turns off the Bash text guard (`shell-text` · `bodies-save` — the same `PreToolUse(Bash)` hook refusing a backtick the shell would run, or an Issue-body bundle saved to a file).
  - ⚠ **Scope**: this dial governs the *commit gate* only. It is **not** an override for INV2 — `/gld evolve`'s apply-time hard-block on a verification-weakening change is non-negotiable and ignores this flag (`_invariants.md` INV2). Turning gates off is for a repo the gate misjudges, not permission to weaken tests.
  - Writing this key trips the gate's own `--guard-config` guard, so the change surfaces as an explicit confirmation prompt. That is intended: disabling the enforcement layer should be a decision on the record.
- `--max-stack-depth=<n>` → set `sprint.max_stack_depth` (default `3`). See the section below.
- `--refactor-slot=<on|off>` → set `sprint.refactor_slot` (default `on`). Whether `/gld sprint plan` reserves one member slot for a refactor. See the section below.
- `--window=<HH:MM-HH:MM|none>` → set `sprint.window` (default `null` = no window). The run window: `/gld sprint run` only starts a **new** member inside it. See the section below.
- `--local-dev=<on|off>` → set `local_developer.enabled` (default `off`). The opt-in local-model developer of the execute stage. See the section below.
- Other keys → report "unknown/unsupported config key" and list the supported ones.

> **Bash**: `_bash_rules.md`. Read/write JSON via the Read/Write tools (not `jq -i`).

---

## Show current config
1. Read `.claude/guild/config.json`.
   - Absent → "Guild is not initialized (run `/gld init`)." Stop.
2. Display readably. ⚠ **Every value below comes from the file you just read — none of it is a literal to copy from this doc.** The shape is the example; the content never is. A doc-copied value here is worse than a missing one, because it reads as a real reading of the user's config:
   ```
   Guild config (.claude/guild/config.json)
   ────────────────────────────────────────
   version:    <config.json's "version">
   language:   <config.json's "language">
   roles:      <count of config.json's "roles"> — spine: <the spine roles present in that array>
               specialists: <the remaining roles in that array>
   commands:   test=<...> lint=<...> typecheck=<...> build=<...> e2e=<...>
               (e2e is auto-run by the qa stage when available/warranted; the test
               stage's own automated-correctness pass never runs it — test.md's scope)
               vrt=<...> (visual regression — run by the test stage when visual is runnable and the Issue has visual cases or changed a visual package)
   visual:     runnable=<on|off> env=<...|미설정> packages=<dirs|전체> baselines=<globs|없음>
               tests=<globs|없음> matchers=<names|없음> config_files=<paths|없음>
               create=<recipe|없음> run_file=<recipe|없음> (commit gate warns when a baseline or config file changes)
   automation: evolve_nudge=<on|off>
   gates:      enabled=<on|off> (commit gate: secret + verification-weakening block)
   sprint:     capacity=<n|미설정> max_stack_depth=<n> history=<count> runs
               refactor_slot=<on|off> (키가 없으면 on)
               window=<HH:MM-HH:MM|미설정>
               board=<#n (<column_field>) · 마지막 시딩(plan) <last_projected>|미설정>
               ⚠ `last_projected` 는 `plan --create` 만 쓴다 — **"마지막 투영"이 아니다.**
               카드가 마지막으로 움직인 시각은 run 마커의 `board_last_write` 이고
               `sprint daily`·`sprint board` 가 그것을 렌더한다
   local_dev:  enabled=<on|off> (키가 없으면 off) model=<...|미설정> attempts=<max_attempts>
               attempt_timeout=<attempt_timeout_min>m total_timeout=<total_timeout_min>m (큐 대기 제외)
   ```
   Render `roles` from the array in the file — **do not enumerate the roster from memory or from this document.** The installed roster is whatever `.claude/guild/config.json` lists and `.claude/agents/` contains; a repo may have grown or pruned it via `evolve` HR, so a hardcoded 16-name list would silently misreport it. Spine roles always run; specialists are convened per task by the leader (participation model: `_handoff.md` Section G).

## Set a value
1. Read `.claude/guild/config.json` (parse as JSON in context).
2. Validate the key/value:
   - `language` ∈ {en, ko, ja}.
   - `evolve_nudge` ∈ {on→true, off→false} (sets `automation.evolve_nudge`).
   - `gates` ∈ {on→true, off→false} (sets `gates.enabled`).
   - `max_stack_depth` — an integer ≥ 1 (sets `sprint.max_stack_depth`). Reject `0` and
     non-integers: a cap of 0 would block every dependent Issue in every sprint. A value of 1
     is meaningful — it means "no stacking, every PR targets the default branch" (what `sprint
     plan` records as `merge-commit-forbidden` when the human declines `squash-sync`).
   - `refactor_slot` ∈ {on→true, off→false} (sets `sprint.refactor_slot`).
   - `window` — **`HH:MM-HH:MM (24h, zero-padded)`**, or `none` to clear it (writes `null`).
     Reject: a missing zero (`9:00`), `HH` outside 00-23, `MM` outside 00-59, and
     **start == end** (say *"omit the window instead"*). `~` is accepted as the separator and
     normalised to `-`. The end is **exclusive** — `22:00-10:00` is already outside at 10:00.
     ⚠ **The same rule exists in three places** — this list, `sprint/run.md`'s argument
     contract, and the supervisor script's own `case`. All three quote the literal
     `HH:MM-HH:MM (24h, zero-padded)` so that a drift is visible; this list is where the
     *validation* lives, and an empty one leaves the other two unchecked.
   - `local_dev` ∈ {on→true, off→false} (sets `local_developer.enabled`). `on` with no
     `local_developer.model` is written but warn: the execute stage will fall back with
     `ineligible:no_model_configured` until a model is set.
   - Invalid → report the allowed values; do not write.
3. Update the key in the in-context object, preserving all other keys.
4. Write the full JSON back via the Write tool (2-space indent).
5. Confirm what changed.

### `--max-stack-depth=<n>`

The sprint PR-stack cap (`sprint.max_stack_depth`, default 3).
`/gld sprint plan` warns and proposes cutting a chain that exceeds it. Raising it is legitimate
but each extra level means one more PR that a change request on the bottom of the stack forces
to catch up — and `retro` measures how often that happened before recommending a change.
`sprint.board` is **written by `/gld sprint board --setup`** (03-sprint-board.md §6) and is
`null` until then — a repo without a board is not in an error state (D2). Its `last_projected`
is refreshed by `sprint plan --create`.

### `--refactor-slot=<on|off>`

The sprint refactor slot (`sprint.refactor_slot`, default `true`). With it on, `/gld sprint plan`
reserves one member per sprint for a behavior-preserving refactor of the code that sprint is
about to touch — reserved, not forced: when nothing qualifies the slot stays empty and the
tracker records why (`sprint/plan.md` "Refactor slot"). The slot sits **inside** capacity.
⚠ **An absent key means `on`** — configs written before this key existed get the slot too.
`off` is for a repo whose refactors are planned elsewhere; the tracker then records
`skip (disabled)`.

### `--window=<HH:MM-HH:MM|none>`

The **run window** (`sprint.window`, default `null`). `/gld sprint run` starts a new member only
inside it and otherwise waits, the way it already waits out a rate limit whose reset is within 4h; a member that started
at 09:59 runs to the end. `--window none` clears the value.

Same `=` syntax as the five dials above. ⚠ **`sprint run`'s flag takes a space *or* an `=`**
(`--window 22:00-10:00`), and its `--duration` alias is a **`run` flag only** — it is not a
config key and there is no `--duration=` setter here.

This value is the default for every run of this repo; the per-run flag overrides it, and on a
resume the tracking Issue marker's `window` key overrides both (that is where a run's own
window survives a crash — it is never written to `config.json`).

`sprint.capacity` and `sprint.history` are **written by `/gld sprint retro`** after per-item
human approval, not set here — they are shown by "Show current config" and have no setter, the
same gap `commands` has (see Notes). ⚠ **`sprint.window` is not in that set** — it has a setter
(above), so do not add it to the "no setter" list.

### `--local-dev=<on|off>`

The **local developer** (`local_developer.enabled`, default `false`; an absent block means off).
With it on, the execute stage (`_execute_spine.md` Step 1L) has a Sonnet developer write the
failing tests (committed, or left staged when a pre-commit hook that runs the suite refuses red
tests), then asks a model served by a local Ollama to write the implementation
— up to `max_attempts` tries — and hands the Issue back to the Sonnet developer when it cannot.
Loop-backs and `refactor` Issues always go to the Sonnet developer.

Only `enabled` has a setter; the rest of the block is edited in `config.json` directly:

```json
"local_developer": {
  "enabled": false,
  "model": "<an Ollama model name, e.g. qwen3.8:27b>",
  "ollama_url": "http://127.0.0.1:11434",
  "max_attempts": 3,
  "max_output_tokens": 8000,
  "max_output_tokens_retry": 16000,
  "attempt_timeout_min": 20,
  "total_timeout_min": 60,
  "num_ctx": 65536,
  "test_cmd": "<runner> {files}",
  "lint_cmd": null
}
```

- `attempt_timeout_min` bounds one model call; `total_timeout_min` bounds the job's **active**
  time (model calls + lint + tests). **Queue wait is not counted**: the model is shared by every
  repo on the machine through a first-come-first-served queue, and an unattended job waits its
  turn however long that takes. An attended job never waits — a busy queue is an immediate
  fallback (`queue_busy`).
- `test_cmd` — **required**: the command that runs only the new tests, with `{files}` where
  their paths go (e.g. `flutter test {files}`, `npx jest {files}`). Without `{files}` every job
  falls back with `ineligible:no_test_cmd` — a whole-suite run would make one unrelated red test
  fail every attempt. The leader still runs the full `commands.test` after a local pass.
  `lint_cmd` `null` → `commands.lint`; lint counts only when it is green before the model edits.
- **Cost.** A local pass saves the implementation part of the developer's work. A **fallback costs
  more than not using this** — the tests-only spawn, then the full developer spawn, plus a leader
  turn per `wait` call. Check `report`'s pass rate before leaving it on.
- Skipped automatically for loop-backs, `refactor` Issues and Issues with visual cases. A job
  without `docs/specs/<N>/skeleton.md` is `ineligible:no_skeleton` — with only the tests to go
  on, a 27B model was measured reasoning until `max_output_tokens` on every attempt.
- A reasoning model's thinking counts against `max_output_tokens` (`output_cap` in `report`).
  An attempt cut off there raises the cap of every later attempt to `max_output_tokens_retry`:
  most passes fit the first cap, a few need more, and starting high only lets a runaway hold the
  model longer. Input and output share `num_ctx`, so a retry cap that leaves no room for the
  prompt is a config error; `report` warns when, at the speed it observed, the retry cap cannot
  be generated within `attempt_timeout_min` (raise that, or lower the cap). `report`'s
  `raised_cap_outcomes` shows whether the raised attempts actually pass. An attempt cut off
  while still reasoning — no edit written yet — usually has its answer in the reasoning, so the
  next attempt is handed that reasoning's last 12,000 characters and runs with reasoning off
  (`think: false`, sent only to a model that showed it reasons); `num_ctx` must leave room for
  that tail too.
- An attended job keeps the model until it ends (so it never waits between attempts); a session
  closed mid-job leaves its worker running to its own end, bounded by `total_timeout_min` of
  active time — other jobs queue behind it meanwhile.
- Every job is logged under `.claude/guild/memory/local-dev/` (gitignored): `runs.jsonl` has one
  line per job — each attempt's outcome, the fallback reason, queue wait and active time — and
  each job folder keeps the prompts, the replies and, on a fallback, the model's last diff.
  `python3 <<SKILL_DIR>>/commands/atoms/local_dev.py report` aggregates it (fallback reasons,
  pass-at-attempt-k, attempt outcomes, and what happened to passes later — `after_pass`).

## Notes
- M1 config schema is a **versioned subset**: `{ version, language, roles[], commands{}, visual{baselines[], tests[], matchers[], packages[], config_files[], runnable, env, create, run_file}, automation{evolve_nudge}, gates{}, sprint{capacity, max_stack_depth, refactor_slot, history[], board, window}, local_developer{enabled, model, ollama_url, max_attempts, max_output_tokens, max_output_tokens_retry, attempt_timeout_min, total_timeout_min, num_ctx, test_cmd, lint_cmd} }`. It is forward-compatible — later milestones add gate/evolve dials without breaking this shape.
- `roles` is edited by init (and by evolve HR later), not by `config` in M1 — editing the active roster manually is possible but unsupported as a config command yet.
- `commands` (test/lint/typecheck/build/e2e/vrt), `visual.*`, `sprint.capacity`/`sprint.history` and `sprint.board` have the **same gap** (⚠ `sprint.window` does **not** — it has a `--window=` setter): they are part of the real schema and shown in "Show current config" above, but `config`'s "Set a value" section has no setter for them (`sprint.max_stack_depth` and `sprint.refactor_slot` do have one) — an attempt to change it (e.g. after a build-tool migration changes the test command) falls into "Other keys → unknown/unsupported," same as any other unrecognized key. Edit `.claude/guild/config.json` directly for now.
