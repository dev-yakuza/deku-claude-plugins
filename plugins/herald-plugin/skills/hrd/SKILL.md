---
name: hrd
description: "Herald installs a writing harness into a repository and runs a per-repo editorial organization (editor-in-chief, content strategist, researcher, writer, fact-checker, editor, plus conditional subject expert, search & discovery, illustrator, translator, distributor) that plans topics, writes professional blog articles through brief -> research -> draft -> critique -> verify -> publish, ships them through PR review with accuracy as a non-negotiable floor, and grows its guides from real usage. Use to set up Herald in a repo (init), plan topics, write or batch-write articles, ship (merge + deploy) approved articles, review, evolve, or check status."
argument-hint: "<command> [topic-id|slug|PR|args]"
user-invocable: true
---

# Herald (`/hrd`)

Route on `$0`: read `<<SKILL_DIR>>/commands/$0.md` and execute it. Pass `$1`, `$2`, … through.

- Valid commands: `init`, `config`, `update`, `plan`, `write`, `brief`, `research`, `draft`,
  `critique`, `verify`, `publish`, `status`, `resume`, `ship`, `batch`, `review`, `refresh`,
  `evolve`, `rollback`, `audit`, `monitoring`, `ask`, `contribute`, `help`.
- Empty `$0` → `help`. Unknown `$0` → say so, then `help`.

Before any command other than `init`/`help`: `.claude/herald/config.json` must exist, else tell
the user to run `/hrd init`. **Version gate** (every command except `init`, `help`, `update`, and `status` with no flag or
with `--unlock`): read `version` from `<<SKILL_DIR>>/../../.claude-plugin/plugin.json` (Read
tool) and run `HRD version --against <that version>`. `relation`:
- `equal` → continue.
- `older`, or `HRD version` itself fails (scripts older than 0.3.0) → stop. If the current
  branch is not `<base>`, the branch carries old scripts: switch to base (`/hrd resume` handles
  herald branches); on base, run `/hrd update`.
- `newer` → stop: the repo was updated by a newer Herald. Update the installed herald-plugin
  (`/plugin`, then restart Claude Code) — never `/hrd update`, which would downgrade the repo.
- a "malformed version" error → stop and report it (never treat it as older).
- Unattended (`HRD_UNATTENDED=1`): instead of stopping silently, write the command's result
  with the note `tooling: herald version mismatch` and exit 0 — `HRD result --topic <id>
  --status held:needs-human --note "…"` for a topic command, `HRD result --topic ship --status
  merged --merged --note "…"` for `ship --auto`. The runner then stops the batch: the topic stays
  queued, or — if its branch already exists — is held with the branch preserved (no growth
  signal) for `/hrd resume` after the update.

**Run the same check again** right after every `HRD sync` and `HRD branch` (base or the new
branch may now carry other scripts) and after switching to an existing herald branch
(`atoms/_stages.md` § Existing branches). Exception: `ship` §5 checks out a PR head to
re-verify a human's push with that branch's own scripts and never merges into it. Commands and
scripts must match, or steps fail or record nothing.

Shared rules: `<<SKILL_DIR>>/commands/atoms/_contract.md`
(tooling, role handoff, unattended mode, language, tiers, loops, signals),
`atoms/_stages.md` (stage spine), `atoms/_auditor.md`, `atoms/_invariants.md`.
`HRD` = `python3 .claude/herald/scripts/hrd.py`. The scripts are copied into the repo by `init`
and refreshed by `update`; never call scripts from the plugin cache directly.
