# CONFIG

**Guild configuration.** View and adjust settings in `.claude/guild/config.json`. `config` turns dials; `init` builds the house (plan §3). Off-switch for automation lives here (plan §11 — user escape hatch).

Parse `$1` onward:
- No arguments → **show current config**.
- `--language=<code>` → set `language` (`en`/`ko`/`ja`).
- `--evolve-nudge=<on|off>` → set `automation.evolve_nudge` (placeholder in M1 — evolve is a later milestone; the dial exists so the off-switch is available early).
- Other keys → in M1, report "unknown/unsupported config key for M1" and list the supported ones. (Gate/evolve dials arrive in M2/M3.)

> **Bash**: `_bash_rules.md`. Read/write JSON via the Read/Write tools (not `jq -i`).

---

## Show current config
1. Read `.claude/guild/config.json`.
   - Absent → "Guild is not initialized (run `/gld init`)." Stop.
2. Display readably:
   ```
   Guild config (.claude/guild/config.json)
   ────────────────────────────────────────
   version:    0.1.0
   language:   ko
   roles:      16 — spine: leader, tech-lead, developer, tester, qa
               specialists: product-owner, designer, infra, dba, security,
               performance, i18n, analytics, tech-writer, release-manager, support-triage
   commands:   test=<...> lint=<...> typecheck=<...> build=<...>
   automation: evolve_nudge=off
   gates:      (none in M1)
   ```
   (Render the `roles` array from config; the spine roles always run, specialists are convened per task by the leader.)

## Set a value
1. Read `.claude/guild/config.json` (parse as JSON in context).
2. Validate the key/value:
   - `language` ∈ {en, ko, ja}.
   - `evolve_nudge` ∈ {on→true, off→false}.
   - Invalid → report the allowed values; do not write.
3. Update the key in the in-context object, preserving all other keys.
4. Write the full JSON back via the Write tool (2-space indent).
5. Confirm what changed.

## Notes
- M1 config schema is a **versioned subset** (plan §18 C): `{ version, language, roles[], commands{}, automation{evolve_nudge}, gates{} }`. It is forward-compatible — later milestones add gate/evolve dials without breaking this shape.
- `roles` is edited by init (and by evolve HR later), not by `config` in M1 — editing the active roster manually is possible but unsupported as a config command yet.
