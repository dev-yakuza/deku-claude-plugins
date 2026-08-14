# CONFIG

**Guild configuration.** View and adjust settings in `.claude/guild/config.json`. `config` turns dials; `init` builds the house (plan §3). Off-switch for automation lives here (plan §11 — user escape hatch).

Parse `$1` onward:
- No arguments → **show current config**.
- `--language=<code>` → set `language` (`en`/`ko`/`ja`).
- `--evolve-nudge=<on|off>` → set `automation.evolve_nudge` (default `on`). This dial gates the **review-stage evolve nudge** (`review.md` Step 5 — the advisory "신호가 충분히 쌓였습니다, `/gld evolve` 적기" reminder). `off` silences it entirely; the review nudge reads this flag before evaluating its 충분/cooldown gate. (evolve itself is always run manually — there is no *automatic* evolve trigger; this switch only controls the reminder.)
- `--gates=<on|off>` → set `gates.enabled` (M3 강제층 off-switch). `off` makes the pre-commit gate advisory (no blocking) — the escape hatch (plan §11). `on` (default) blocks secret / verification-weakening commits.
- Other keys → report "unknown/unsupported config key" and list the supported ones.

> **Bash**: `_bash_rules.md`. Read/write JSON via the Read/Write tools (not `jq -i`).

---

## Show current config
1. Read `.claude/guild/config.json`.
   - Absent → "Guild is not initialized (run `/gld init`)." Stop.
2. Display readably:
   ```
   Guild config (.claude/guild/config.json)
   ────────────────────────────────────────
   version:    <config.json's actual "version" field — never a literal copied from this doc>
   language:   ko
   roles:      16 — spine: leader, tech-lead, developer, tester, qa
               specialists: product-owner, designer, infra, dba, security,
               performance, i18n, analytics, tech-writer, release-manager, support-triage
   commands:   test=<...> lint=<...> typecheck=<...> build=<...> e2e=<...>
               (e2e is auto-run by the qa stage when available/warranted; the test
               stage's own automated-correctness pass never runs it — test.md's scope)
   automation: evolve_nudge=on
   gates:      enabled=on (pre-commit: secret + verification-weakening block)
   ```
   (Render the `roles` array from config; the spine roles always run, specialists are convened per task by the leader.)

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
- M1 config schema is a **versioned subset** (plan §18 C): `{ version, language, roles[], commands{}, automation{evolve_nudge}, gates{} }`. It is forward-compatible — later milestones add gate/evolve dials without breaking this shape.
- `roles` is edited by init (and by evolve HR later), not by `config` in M1 — editing the active roster manually is possible but unsupported as a config command yet.
- `commands` (test/lint/typecheck/build/e2e) has the **same gap**: it's part of the real schema and shown in "Show current config" above, but `config`'s "Set a value" section has no setter for it — an attempt to change it (e.g. after a build-tool migration changes the test command) falls into "Other keys → unknown/unsupported," same as any other unrecognized key. Edit `.claude/guild/config.json` directly for now.
