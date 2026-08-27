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
- **Gate script** → copy the latest `<<SKILL_DIR>>/gates/gate_precommit.py` → `.claude/guild/gates/scripts/` (central-owned; overwrite) — **but check for a local extension first.** ⚠ This overwrite destroyed real enforcement once: a repo had hand-extended the script with a `test-naming` check that read its own `gates/rules/test-naming.md` at `status: confirmed`, and it was actively blocking commits. An update replaced the script; the rule file stayed on disk, nothing read it, and it enforced nothing — silently. That is an INV4 violation, and the root cause was that the repo had nowhere else to put the check.
  1. Before overwriting, compare the two (its own Bash call):
     ```bash
     diff .claude/guild/gates/scripts/gate_precommit.py <<SKILL_DIR>>/gates/gate_precommit.py
     ```
     A large diff is normal (this file changes every release). What matters is whether the **repo's** copy contains checks the central one does not — look for `def check_*` names or `rules/<name>.md` reads that the central file lacks, and for any `rules/*.md` file with no reader in the central script:
     ```bash
     ls .claude/guild/gates/rules
     ```
     The central script reads only `boundaries.md` as data (`secrets.md`/`verification.md` are declarations, not inputs). **Any other rule file is a local extension's rule file** and is the clearest signal one exists.
     ⚠ **Check `scripts/local/` before concluding the extension is still inline.** Once a check has been migrated, its rule file legitimately has no reader in the central script — the reader is `local/<name>.py`. Grep the local modules for the rule file's name; if one reads it, the migration is already done and the central script can be overwritten with no loss. Two other things also look like inline extensions but are not: this file's own post-mortem comments naming a rule file, and the central script's comments citing the case that motivated the `local/` mechanism. Confirm a live reader (`def check_*`, an `open(...rules/<name>)`) before reporting a conflict — a false alarm here teaches the human to click through the one warning that is supposed to stop them.
  2. Local extension found → **do not overwrite silently.** Report exactly which check would be lost and that its rule file would go inert. Offer to migrate it to `.claude/guild/gates/scripts/local/<name>.py`, which update **preserves**. A module may define either or both of:
     - **`check(ctx)` → `(block, warn)`** — *add* findings. `ctx` gives `changed_names()`, `changed_diff()`, `is_dismissed(path)`, `rule_file(name)` → `(text, confirmed)`, and `record(rule, action, path)` for the evolve scorecard. Build findings with `{"rule": …, "file": …, "message": …}` (a bare string still works).
     - **`refine(ctx, findings)` → the findings to keep** — *narrow* a central rule under a repo-specific condition. This is what a policy like "deleting a non-entry-point integration test is not a weakening — our architecture has one entry point, so removing the others restores it" needs: it is neither an added finding nor a static path, so neither `check()` nor `dismissed.md` can express it, and without this hook it stays in a maintained fork forever. Guard rails: a **`secret` finding can never be suppressed** (INV5 — `dismissed.md` is the reviewable path for an accepted secret risk); every suppression is logged as a firing (`action: suppressed-by-<module>`) so it reaches evolve and `/gld audit` rather than vanishing; a refiner that raises suppresses nothing.
     ⚠ One deletion produces **two** findings when the file carried ≥3 assertions — `verification:test-deleted` *and* `verification:assertion-drop`. A refiner that exempts only the first does not actually exempt the deletion. `assertion-drop` is an aggregate over the whole commit, so it carries **`files`**: the list of test files with a net removal (and `file` names the single one when there is exactly one). Exempt it only when that list is *entirely* accounted for by the exemption — `f.get("files") == [EXEMPT]` — so an unrelated file losing assertions in the same commit still blocks. Suppressing every `verification:` finding instead is far broader than any exemption should be. Migrate, verify the check still fires, and only then overwrite the central script. If the human declines the migration, **skip the gate-script update entirely** and say the harness stays behind — a stale gate that still enforces beats a current one that silently stopped.
  3. No local extension → overwrite normally.
- **Local gate extensions** (`.claude/guild/gates/scripts/local/*.py`) → **PRESERVE** (see the preserve list below). Central never writes into that directory.
- **Commit-gate wiring** → follow `init` step 6 **including its step 2 ownership question**, which decides the whole path. Resolve with `git rev-parse --git-path hooks/pre-commit` (its own Bash call — never hardcode `.git/hooks/`, absent in a worktree), then run the detector (`gate_precommit.py --detect-hook-manager`, stdin = the existing hook's text):
  - **`guild` / `none`** → copy the latest `<<SKILL_DIR>>/gates/pre-commit.sh` to the resolved path and `chmod +x` it (its own Bash call — git silently ignores a non-executable hook). **This is the fresh-clone recovery path**: `.git/hooks/` is not tracked, so a clone has every harness file but no hook until this runs. A hand-written hook is moved aside to `<path>.local` first, exactly as `init` step 2 describes.
  - **A manager name** (`lefthook`/`husky`/…) → **do not touch the hook file.** Confirm the gate is still registered as one of that manager's commands (`init` step 2b) and re-register it if a config edit dropped it — this is the case where `update` most earns its keep, since a `lefthook install` or a config rewrite can silently remove it. Show the diff and confirm before writing (INV1).
  Then check `git config --get core.hooksPath` — on the unmanaged path a non-empty value means Guild's hook will never fire, so report it rather than claiming the gate is active; on the managed path it is expected and harmless.
- **Universal gate rules** → refresh `.claude/guild/gates/rules/secrets.md` and `rules/verification.md` (central-owned; overwrite) — **but only together with the gate script**. ⚠ These files *declare* what the gate enforces; the script *is* the enforcement. Refreshing the declaration while the script stays behind makes it claim protection the repo does not have: a 0.52.0 `secrets.md` lists `.key`/`.p8`/`id_rsa`/`.netrc`/`kubeconfig`/`.tfvars`, and against an older script none of those are actually checked. A human reading it would reasonably stop worrying about exactly the files still going through. **If the gate-script update is skipped (a local extension pending migration), skip these too** and say they stay at the old version for that reason — a declaration that overstates coverage is worse than one that is merely old. These two are the **human-readable declaration** of what the gate enforces, not inputs it parses: the secret and verification checks are hardcoded in `gate_precommit.py` precisely because they are universal and non-hallucinated. Only `rules/boundaries.md` is data-driven (the gate reads its `- forbid:` lines, and its **frontmatter** `status:` decides block vs warn).
- **settings.json** → union the latest central `PreToolUse` entries — **both** the `Bash` early-warning hook and the `Edit|Write|MultiEdit` `--guard-config` hook — and the `permissions.ask` list (INV1/INV3 made mechanical). **Preserve local `permissions.allow` and any local hooks**; dedupe by full command string, which includes the mode flag (deduping by script path alone would collapse the three modes into one).
- **CLAUDE.md guild block** → update only the content between `<!-- guild:start -->`…`<!-- guild:end -->` to the latest template shape, **preserving everything outside the markers** and any local knowledge-routing lines you can carry forward.
- **`.claude/guild/.gitignore`** → ensure it carries everything `init` writes there (currently `memory/` and `gates/scripts/local/__pycache__/`). Central-owned and additive: add missing lines, never remove a line the repo added.
- **Labels** → read what exists **before** claiming anything is missing (its own Bash call):
  ```bash
  gh label list --limit 200 --json name --jq '[.[].name] | map(select(startswith("guild:")))'
  ```
  ⚠ **`gh label list --json name` returns a FLAT array of `{"name": …}` objects** — not an object with a `.labels` field. Indexing it as `.labels[]` (the shape `gh issue view` uses, which is easy to reach for here) errors with `jq: error … Cannot index array with string` and exit 5, producing **no output at all** — which then reads as "no labels exist". Same gotcha as `atoms/audit_readiness.md` Group 4, which documents it against the real binary.
  Create only the names genuinely absent from that list, idempotently with `--force`. **The canonical set is `init.md` P2 §7's `gh label create` block** — read it rather than an enumeration held here, so a label added centrally (e.g. `guild:sprint`) reaches an existing repo through this step without a second edit. **Report the actual count** — "N개 중 M개 누락" from the read, never "전부 누락" inferred from an empty or failed query. Observed: an update run reported every `guild:*` label missing on a repo whose Issues were actively carrying `guild:done`/`guild:child`; a bad query is indistinguishable from an empty repo unless you look.
- **Config** → add any **new** config keys with defaults, **preserving existing local values** (language, roles, commands, gate/automation dials). Bump `version` to the plugin version **only if every central-owned artifact above was actually adopted**.
  ⚠ **A partial update must NOT bump `version`.** `config.version` is a single scalar standing for the whole harness, so stamping it after skipping a component (most often the gate script, when a local extension could not be migrated) makes the gap **invisible**: the next `/gld update` compares versions, reports "최신입니다", and stops — the deferred work is never revisited, and the repo reads as current while running an old enforcement layer. Leave `version` at its old value, state plainly which component is behind and why, and say that re-running `update` will re-offer it. Re-offering the already-adopted parts is idempotent and harmless; losing track of the skipped one is not.
- **Linter scope** → re-run `init` step 0b's check. `update` **rewrites `gate_precommit.py`**, so a plugin release that adds a new secret or skip pattern adds new vocabulary to a file the repo's spell checker may lint — and the human then discovers it as a failed commit, not as an update result. If Guild-managed paths are still not excluded from a linter that would see them, propose the exclusion and confirm (INV1). This is a check every update must repeat, not a one-time `init` concern.

**3. PRESERVE — never touched** (local evolution, INV4): `.claude/agents/*` specialization · `.claude/guild/knowledge/*` (⑥) · `docs/standards/*` (②) · `.claude/guild/overlay/*` (flow overrides) · `.claude/guild/evolution-log.md` (⑤) · `.claude/guild/gates/rules/boundaries.md` (locally grown by `/gld evolve` — `- forbid:` rules, `status: draft`/`confirmed`) · `.claude/guild/gates/dismissed.md` (human-curated accepted-risk registry) · `.claude/guild/gates/scripts/local/*` (**repo-local gate extensions** — the supported place for a check the central script doesn't have; central never writes there) · `.claude/guild/gates/rules/*.md` other than `secrets.md`/`verification.md` (a rule file the central script doesn't read belongs to a local extension) · `.claude/guild/gates/findings.json` and `.claude/guild/memory/*` (**runtime state, not structure** — the gate rewrites `findings.json` on its next run and the memory tier is gitignored episodic data; update neither refreshes nor deletes them).

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
