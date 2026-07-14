# UPDATE (adopt central Guild improvements — preserve local evolution)

**Upgrade the repo's harness to the installed plugin version, keeping local evolution intact (plan §10 중앙→repo 전파).** The counterpart to `init`: **init builds** the harness once; **update** adopts newer **central-owned** structure (gate scripts · settings hooks · `CLAUDE.md` block · label set · config schema) while **preserving local-owned** evolution (specialized agents · ⑥ knowledge · standards · overlay). Never clobbers what the repo grew.

`$1` (optional): `--check` (show the version gap + what's available, change nothing) · default = interactive update.

> **Bash**: `_bash_rules.md`. Handoff + owner/repo: `_handoff.md`.
> **Output language**: all human-readable output in `config.language` (`_handoff.md` Section K).

---

## Process
**0. Preflight** — read `.claude/guild/config.json` `version` (the repo harness version, stamped at init/last-update) and the **installed plugin version** (`<<SKILL_DIR>>/../../.claude-plugin/plugin.json`, or the marketplace-installed manifest). Guild not initialized → "run `/gld init` first".

**1. Version gap**
- `config.version` ≥ plugin → "최신입니다 (v<config.version>)." Stop.
- `config.version` < plugin → show the gap and what an update brings (new/changed **commands** are already available plugin-side; the **repo-side** update refreshes gate scripts, settings hooks, the CLAUDE.md guild block, the label set, and the config schema). `--check` → stop here (nudge only).

**2. Adopt central-owned repo artifacts (each shown + confirmed — INV1)**
Preserving local content throughout:
- **Gate scripts** → copy the latest `<<SKILL_DIR>>/gates/gate_precommit.py` → `.claude/guild/gates/scripts/` (central-owned; overwrite).
- **settings.json hooks** → union the latest central `PreToolUse` gate hook, **preserving local `permissions.allow` and any local hooks** (dedupe by command path).
- **CLAUDE.md guild block** → update only the content between `<!-- guild:start -->`…`<!-- guild:end -->` to the latest template shape, **preserving everything outside the markers** and any local knowledge-routing lines you can carry forward.
- **Labels** → ensure the current `guild:*` label set (add any new ones idempotently, `--force`).
- **Config** → bump `version` to the plugin version; add any **new** config keys with defaults, **preserving existing local values** (language, roles, commands, gate/automation dials).

**3. PRESERVE — never touched** (local evolution, INV4): `.claude/agents/*` specialization · `.claude/guild/knowledge/*` (⑥) · `docs/standards/*` (②) · `.claude/guild/overlay/*` (flow overrides) · `.claude/guild/evolution-log.md` (⑤).

**4. Report** — what updated, what was preserved, the new version, and any newly-available commands. Reversible (git — the update is uncommitted working-tree changes the human reviews + commits).

## Hard rules
- **Preserve local evolution** (INV4 additive/merge) — agents · knowledge · standards · overlay · ledger are LOCAL-owned and never overwritten. Only central-owned *structure* is refreshed.
- **Confirm structural changes** before applying (INV1); leave them uncommitted for the human to review + commit (reversible, INV3).
- **Never downgrade** (`config.version` ≥ plugin → no-op).
