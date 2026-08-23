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
- **Commit-gate wiring** → follow `init` step 6 **including its step 2 ownership question**, which decides the whole path. Resolve with `git rev-parse --git-path hooks/pre-commit` (its own Bash call — never hardcode `.git/hooks/`, absent in a worktree), then run the detector (`gate_precommit.py --detect-hook-manager`, stdin = the existing hook's text):
  - **`guild` / `none`** → copy the latest `<<SKILL_DIR>>/gates/pre-commit.sh` to the resolved path and `chmod +x` it (its own Bash call — git silently ignores a non-executable hook). **This is the fresh-clone recovery path**: `.git/hooks/` is not tracked, so a clone has every harness file but no hook until this runs. A hand-written hook is moved aside to `<path>.local` first, exactly as `init` step 2 describes.
  - **A manager name** (`lefthook`/`husky`/…) → **do not touch the hook file.** Confirm the gate is still registered as one of that manager's commands (`init` step 2b) and re-register it if a config edit dropped it — this is the case where `update` most earns its keep, since a `lefthook install` or a config rewrite can silently remove it. Show the diff and confirm before writing (INV1).
  Then check `git config --get core.hooksPath` — on the unmanaged path a non-empty value means Guild's hook will never fire, so report it rather than claiming the gate is active; on the managed path it is expected and harmless.
- **Universal gate rules** → refresh `.claude/guild/gates/rules/secrets.md` and `rules/verification.md` (central-owned; overwrite). These two are the **human-readable declaration** of what the gate enforces, not inputs it parses: the secret and verification checks are hardcoded in `gate_precommit.py` precisely because they are universal and non-hallucinated. Only `rules/boundaries.md` is data-driven (the gate reads its `- forbid:` lines, and its **frontmatter** `status:` decides block vs warn).
- **settings.json** → union the latest central `PreToolUse` entries — **both** the `Bash` early-warning hook and the `Edit|Write|MultiEdit` `--guard-config` hook — and the `permissions.ask` list (INV1/INV3 made mechanical). **Preserve local `permissions.allow` and any local hooks**; dedupe by full command string, which includes the mode flag (deduping by script path alone would collapse the three modes into one).
- **CLAUDE.md guild block** → update only the content between `<!-- guild:start -->`…`<!-- guild:end -->` to the latest template shape, **preserving everything outside the markers** and any local knowledge-routing lines you can carry forward.
- **Labels** → read what exists **before** claiming anything is missing (its own Bash call):
  ```bash
  gh label list --limit 200 --json name --jq '[.[].name] | map(select(startswith("guild:")))'
  ```
  ⚠ **`gh label list --json name` returns a FLAT array of `{"name": …}` objects** — not an object with a `.labels` field. Indexing it as `.labels[]` (the shape `gh issue view` uses, which is easy to reach for here) errors with `jq: error … Cannot index array with string` and exit 5, producing **no output at all** — which then reads as "no labels exist". Same gotcha as `atoms/audit_readiness.md` Group 4, which documents it against the real binary.
  Create only the names genuinely absent from that list, idempotently with `--force`. **Report the actual count** — "N개 중 M개 누락" from the read, never "전부 누락" inferred from an empty or failed query. Observed: an update run reported all 10 labels missing on a repo whose Issues were actively carrying `guild:done`/`guild:child`; a bad query is indistinguishable from an empty repo unless you look.
- **Config** → bump `version` to the plugin version; add any **new** config keys with defaults, **preserving existing local values** (language, roles, commands, gate/automation dials).
- **Linter scope** → re-run `init` step 0b's check. `update` **rewrites `gate_precommit.py`**, so a plugin release that adds a new secret or skip pattern adds new vocabulary to a file the repo's spell checker may lint — and the human then discovers it as a failed commit, not as an update result. If Guild-managed paths are still not excluded from a linter that would see them, propose the exclusion and confirm (INV1). This is a check every update must repeat, not a one-time `init` concern.

**3. PRESERVE — never touched** (local evolution, INV4): `.claude/agents/*` specialization · `.claude/guild/knowledge/*` (⑥) · `docs/standards/*` (②) · `.claude/guild/overlay/*` (flow overrides) · `.claude/guild/evolution-log.md` (⑤) · `.claude/guild/gates/rules/boundaries.md` (locally grown by `/gld evolve` — `- forbid:` rules, `status: draft`/`confirmed`) · `.claude/guild/gates/dismissed.md` (human-curated accepted-risk registry) · `.claude/guild/gates/findings.json` and `.claude/guild/memory/*` (**runtime state, not structure** — the gate rewrites `findings.json` on its next run and the memory tier is gitignored episodic data; update neither refreshes nor deletes them).

**4. Verify it actually landed — before reporting anything** (its own Bash calls; do not skip, and do not report from what you *intended* to write):

```bash
git status --short
```
```bash
jq -r .version .claude/guild/config.json
```

- **Working tree unchanged AND `config.version` still the old value** → **nothing was applied.** Say exactly that and why (the human declined at the confirm gate · the run was cancelled · every artifact was already current). Do **not** report success. Then state what to run to actually apply it.
- **`config.version` still the old value but files did change** → a partial apply: name which artifacts landed and which did not, and that the version was deliberately not bumped. This is a state to surface, not to smooth over.
- **`config.version` == plugin version and the tree shows the expected changes** → applied; report normally.

Spot-check the two artifacts whose *content* matters most, rather than trusting that a copy happened — the gate script is the enforcement layer and the hook wiring is what makes it run:

```bash
grep -c "^def main_" .claude/guild/gates/scripts/gate_precommit.py
```
On the **managed** path, also confirm the gate is registered in the manager's config (grep it for `gate_precommit.py`); on the **unmanaged** path, that `.git/hooks/pre-commit` exists and is executable.

⚠ **"The plugin updated" ≠ "this repo updated."** These are two different things and conflating them produces a false success report — observed: a run that applied nothing still told the human "Guild 플러그인 업데이트가 적용됐네요", because the *plugin* had indeed reached a new version while the *repo harness* sat untouched at its old one. Step 1 already draws this distinction; the report must keep it. Always name the repo-side version explicitly (`v<old> → v<new>`), never just "updated".

**5. Report** — what updated, what was preserved, the repo-side version transition, and any newly-available commands. Reversible (git — the update is uncommitted working-tree changes the human reviews + commits). If step 4 found nothing applied, the report is that finding.

## Hard rules
- **Preserve local evolution** (INV4 additive/merge) — agents · knowledge · standards · overlay · ledger are LOCAL-owned and never overwritten. Only central-owned *structure* is refreshed.
- **Confirm structural changes** before applying (INV1); leave them uncommitted for the human to review + commit (reversible, INV3).
- **Never downgrade** (`config.version` ≥ plugin → no-op).
- **Never claim an update that did not happen.** Report from step 4's verification of the working tree and `config.version`, never from intent. A declined or cancelled confirm gate is a normal outcome — say so plainly; an unchanged repo reported as "적용됐다" is worse than an obvious failure, because the human then believes the enforcement layer is current when it is still the old one.
