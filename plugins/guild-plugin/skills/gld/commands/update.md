# UPDATE (adopt central Guild improvements — preserve local evolution)

**Upgrade the repo's harness to the installed plugin version, keeping local evolution intact (중앙→repo 전파).** The counterpart to `init`: **init builds** the harness once; **update** adopts newer **central-owned** structure (gate scripts · settings hooks · `CLAUDE.md` block · label set · config schema) while **preserving local-owned** evolution (specialized agents · ⑥ knowledge · standards · overlay). Never clobbers what the repo grew.

`$1` (optional): `--check` (show the version gap + what's available, change nothing) · default = interactive update.

> **Bash**: `_bash_rules.md`. Handoff + owner/repo: `_handoff.md`.
> **Output language**: all human-readable output in `config.language` (`_handoff.md` Section K).

---

## Process
**0. Preflight** — read `.claude/guild/config.json` `version` (the repo harness version, stamped at init/last-update) and the **installed plugin version** (`<<SKILL_DIR>>/../../.claude-plugin/plugin.json`, or the marketplace-installed manifest). Guild not initialized → "run `/gld init` first".

**1. Version gap**
Compare the two versions **semver-numerically** (major.minor.patch, each component as a number — e.g. `0.9.0 < 0.10.0`, not a lexicographic string compare where "0.9.0" would wrongly sort above "0.10.0"):
- `config.version` ≥ plugin → "최신입니다 (v<config.version>)." Stop.
- `config.version` < plugin → show the gap and what an update brings (new/changed **commands** are already available plugin-side; the **repo-side** update refreshes gate scripts, the git pre-commit hook, settings hooks, the CLAUDE.md guild block, the label set, and the config schema). `--check` → stop here (nudge only). **`--check` should also report a missing or non-executable `.git/hooks/pre-commit` even at version parity** — that is the fresh-clone case, where the version is current but the authoritative gate layer is absent.

**2. Adopt central-owned repo artifacts (each shown + confirmed — INV1)**
Preserving local content throughout:
- **Gate scripts** → copy the latest `<<SKILL_DIR>>/gates/gate_precommit.py` → `.claude/guild/gates/scripts/` (central-owned; overwrite).
- **git pre-commit hook** → copy the latest `<<SKILL_DIR>>/gates/pre-commit.sh` → `.git/hooks/pre-commit`, then `chmod +x` it (its own Bash call — git silently ignores a non-executable hook). **This is also the fresh-clone recovery path**: `.git/hooks/` is not tracked, so a clone of a Guild-enabled repo has every harness file but no hook until this runs — `update` is how the authoritative layer comes back. Preserve any non-Guild hook exactly as `init` step 6 does (Read the existing one; if it does not contain `gate_precommit.py`, move it to `.git/hooks/pre-commit.local` first, which the shim chains to). Then check `git config --get core.hooksPath` — non-empty means the repo redirects hooks and Guild's will never fire; report it rather than silently claiming the gate is active.
- **Universal gate rules** → refresh `.claude/guild/gates/rules/secrets.md` and `rules/verification.md` (central-owned; overwrite). These two are the **human-readable declaration** of what the gate enforces, not inputs it parses: the secret and verification checks are hardcoded in `gate_precommit.py` precisely because they are universal and non-hallucinated. Only `rules/boundaries.md` is data-driven (the gate reads its `- forbid:` lines, and its **frontmatter** `status:` decides block vs warn).
- **settings.json** → union the latest central `PreToolUse` entries — **both** the `Bash` early-warning hook and the `Edit|Write|MultiEdit` `--guard-config` hook — and the `permissions.ask` list (INV1/INV3 made mechanical). **Preserve local `permissions.allow` and any local hooks**; dedupe by full command string, which includes the mode flag (deduping by script path alone would collapse the three modes into one).
- **CLAUDE.md guild block** → update only the content between `<!-- guild:start -->`…`<!-- guild:end -->` to the latest template shape, **preserving everything outside the markers** and any local knowledge-routing lines you can carry forward.
- **Labels** → ensure the current `guild:*` label set (add any new ones idempotently, `--force`).
- **Config** → bump `version` to the plugin version; add any **new** config keys with defaults, **preserving existing local values** (language, roles, commands, gate/automation dials).

**3. PRESERVE — never touched** (local evolution, INV4): `.claude/agents/*` specialization · `.claude/guild/knowledge/*` (⑥) · `docs/standards/*` (②) · `.claude/guild/overlay/*` (flow overrides) · `.claude/guild/evolution-log.md` (⑤) · `.claude/guild/gates/rules/boundaries.md` (locally grown by `/gld evolve` — `- forbid:` rules, `status: draft`/`confirmed`) · `.claude/guild/gates/dismissed.md` (human-curated accepted-risk registry) · `.claude/guild/gates/findings.json` and `.claude/guild/memory/*` (**runtime state, not structure** — the gate rewrites `findings.json` on its next run and the memory tier is gitignored episodic data; update neither refreshes nor deletes them).

**4. Report** — what updated, what was preserved, the new version, and any newly-available commands. Reversible (git — the update is uncommitted working-tree changes the human reviews + commits).

## Hard rules
- **Preserve local evolution** (INV4 additive/merge) — agents · knowledge · standards · overlay · ledger are LOCAL-owned and never overwritten. Only central-owned *structure* is refreshed.
- **Confirm structural changes** before applying (INV1); leave them uncommitted for the human to review + commit (reversible, INV3).
- **Never downgrade** (`config.version` ≥ plugin → no-op).
