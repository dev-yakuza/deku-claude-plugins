# CONFIG

**Guild configuration.** View and adjust settings in `.claude/guild/config.json`. `config` turns dials; `init` builds the house. Off-switch for automation lives here (user escape hatch).

Parse `$1` onward:
- No arguments → **show current config**.
- `--language=<code>` → set `language` (`en`/`ko`/`ja`).
- `--evolve-nudge=<on|off>` → set `automation.evolve_nudge` (default `on`). This dial gates the **review-stage evolve nudge** (`review.md` Step 5 — the advisory "신호가 충분히 쌓였습니다, `/gld evolve` 적기" reminder). `off` silences it entirely; the review nudge reads this flag before evaluating its 충분/cooldown gate. (evolve itself is always run manually — there is no *automatic* evolve trigger; this switch only controls the reminder.)
- `--gates=<on|off>` → set `gates.enabled` (M3 강제층 off-switch). `off` makes the commit gate advisory (no blocking) — the escape hatch. `on` (default) blocks secret / verification-weakening commits, in **all three** of its wirings (`.git/hooks/pre-commit`, the `PreToolUse(Bash)` early warning, and the `--guard-config` control-file guard).
  - ⚠ **Scope**: this dial governs the *commit gate* only. It is **not** an override for INV2 — `/gld evolve`'s apply-time hard-block on a verification-weakening change is non-negotiable and ignores this flag (`_invariants.md` INV2). Turning gates off is for a repo the gate misjudges, not permission to weaken tests.
  - Writing this key trips the gate's own `--guard-config` guard, so the change surfaces as an explicit confirmation prompt. That is intended: disabling the enforcement layer should be a decision on the record.
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
   ```
   Render `roles` from the array in the file — **do not enumerate the roster from memory or from this document.** The installed roster is whatever `.claude/guild/config.json` lists and `.claude/agents/` contains; a repo may have grown or pruned it via `evolve` HR, so a hardcoded 16-name list would silently misreport it. Spine roles always run; specialists are convened per task by the leader (participation model: `_handoff.md` Section G). Execute's always-on adversarial auditor is outside the roster and so never appears here.

## Set a value
1. Read `.claude/guild/config.json` (parse as JSON in context).
2. Validate the key/value:
   - `language` ∈ {en, ko, ja}.
   - `evolve_nudge` ∈ {on→true, off→false} (sets `automation.evolve_nudge`).
   - `gates` ∈ {on→true, off→false} (sets `gates.enabled`).
   - Invalid → report the allowed values; do not write.
3. Update the key in the in-context object, preserving all other keys.
4. Write the full JSON back via the Write tool (2-space indent).
5. Confirm what changed.

## Notes
- M1 config schema is a **versioned subset**: `{ version, language, roles[], commands{}, automation{evolve_nudge}, gates{} }`. It is forward-compatible — later milestones add gate/evolve dials without breaking this shape.
- `roles` is edited by init (and by evolve HR later), not by `config` in M1 — editing the active roster manually is possible but unsupported as a config command yet.
- `commands` (test/lint/typecheck/build/e2e) has the **same gap**: it's part of the real schema and shown in "Show current config" above, but `config`'s "Set a value" section has no setter for it — an attempt to change it (e.g. after a build-tool migration changes the test command) falls into "Other keys → unknown/unsupported," same as any other unrecognized key. Edit `.claude/guild/config.json` directly for now.
