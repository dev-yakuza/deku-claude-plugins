# CONFIG

**Guild configuration.** View and adjust settings in `.claude/guild/config.json`. `config` turns dials; `init` builds the house. Off-switch for automation lives here (user escape hatch).

Parse `$1` onward:
- No arguments → **show current config**.
- `--language=<code>` → set `language` (`en`/`ko`/`ja`).
- `--evolve-nudge=<on|off>` → set `automation.evolve_nudge` (default `on`). This dial gates the **review-stage evolve nudge** (`review.md` Step 5 — the advisory "신호가 충분히 쌓였습니다, `/gld evolve` 적기" reminder). `off` silences it entirely; the review nudge reads this flag before evaluating its 충분/cooldown gate. (evolve itself is always run manually — there is no *automatic* evolve trigger; this switch only controls the reminder.)
- `--gates=<on|off>` → set `gates.enabled` (M3 강제층 off-switch). `off` makes the commit gate advisory (no blocking) — the escape hatch. `on` (default) blocks secret / verification-weakening commits, in **all three** of its wirings (`.git/hooks/pre-commit`, the `PreToolUse(Bash)` early warning, and the `--guard-config` control-file guard).
  - ⚠ **Scope**: this dial governs the *commit gate* only. It is **not** an override for INV2 — `/gld evolve`'s apply-time hard-block on a verification-weakening change is non-negotiable and ignores this flag (`_invariants.md` INV2). Turning gates off is for a repo the gate misjudges, not permission to weaken tests.
  - Writing this key trips the gate's own `--guard-config` guard, so the change surfaces as an explicit confirmation prompt. That is intended: disabling the enforcement layer should be a decision on the record.
- `--max-stack-depth=<n>` → set `sprint.max_stack_depth` (default `3`). See the section below.
- `--window=<HH:MM-HH:MM|none>` → set `sprint.window` (default `null` = no window). The run window: `/gld sprint run` only starts a **new** member inside it. See the section below.
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
   automation: evolve_nudge=<on|off>
   gates:      enabled=<on|off> (commit gate: secret + verification-weakening block)
   sprint:     capacity=<n|미설정> max_stack_depth=<n> history=<count> runs
               window=<HH:MM-HH:MM|미설정>
               board=<#n (<column_field>) · 마지막 시딩(plan) <last_projected>|미설정>
               ⚠ `last_projected` 는 `plan --create` 만 쓴다 — **"마지막 투영"이 아니다.**
               카드가 마지막으로 움직인 시각은 run 마커의 `board_last_write` 이고
               `sprint daily`·`sprint board` 가 그것을 렌더한다
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
     is meaningful — it means "no stacking, every PR targets the default branch", which is what
     `sprint plan` proposes when the repo forbids merge commits.
   - `window` — **`HH:MM-HH:MM (24h, zero-padded)`**, or `none` to clear it (writes `null`).
     Reject: a missing zero (`9:00`), `HH` outside 00-23, `MM` outside 00-59, and
     **start == end** (say *"omit the window instead"*). `~` is accepted as the separator and
     normalised to `-`. The end is **exclusive** — `22:00-10:00` is already outside at 10:00.
     ⚠ **The same rule exists in three places** — this list, `sprint/run.md`'s argument
     contract, and the supervisor script's own `case`. All three quote the literal
     `HH:MM-HH:MM (24h, zero-padded)` so that a drift is visible; this list is where the
     *validation* lives, and an empty one leaves the other two unchecked.
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

### `--window=<HH:MM-HH:MM|none>`

The **run window** (`sprint.window`, default `null`). `/gld sprint run` starts a new member only
inside it and otherwise waits, the way it already waits out a rate limit whose reset is within 4h; a member that started
at 09:59 runs to the end. `--window none` clears the value.

Same `=` syntax as the four dials above. ⚠ **`sprint run`'s flag takes a space *or* an `=`**
(`--window 22:00-10:00`), and its `--duration` alias is a **`run` flag only** — it is not a
config key and there is no `--duration=` setter here.

This value is the default for every run of this repo; the per-run flag overrides it, and on a
resume the tracking Issue marker's `window` key overrides both (that is where a run's own
window survives a crash — it is never written to `config.json`).

`sprint.capacity` and `sprint.history` are **written by `/gld sprint retro`** after per-item
human approval, not set here — they are shown by "Show current config" and have no setter, the
same gap `commands` has (see Notes). ⚠ **`sprint.window` is not in that set** — it has a setter
(above), so do not add it to the "no setter" list.

## Notes
- M1 config schema is a **versioned subset**: `{ version, language, roles[], commands{}, automation{evolve_nudge}, gates{}, sprint{capacity, max_stack_depth, history[], board, window} }`. It is forward-compatible — later milestones add gate/evolve dials without breaking this shape.
- `roles` is edited by init (and by evolve HR later), not by `config` in M1 — editing the active roster manually is possible but unsupported as a config command yet.
- `commands` (test/lint/typecheck/build/e2e), `sprint.capacity`/`sprint.history` and `sprint.board` have the **same gap** (⚠ `sprint.window` does **not** — it has a `--window=` setter): they are part of the real schema and shown in "Show current config" above, but `config`'s "Set a value" section has no setter for them (`sprint.max_stack_depth` does have one) — an attempt to change it (e.g. after a build-tool migration changes the test command) falls into "Other keys → unknown/unsupported," same as any other unrecognized key. Edit `.claude/guild/config.json` directly for now.
