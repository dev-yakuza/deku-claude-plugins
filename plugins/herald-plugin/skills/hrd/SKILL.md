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
the user to run `/hrd init`. Shared rules: `<<SKILL_DIR>>/commands/atoms/_contract.md`
(tooling, role handoff, unattended mode, language, tiers, loops, signals),
`atoms/_stages.md` (stage spine), `atoms/_auditor.md`, `atoms/_invariants.md`.
`HRD` = `python3 .claude/herald/scripts/hrd.py`. The scripts are copied into the repo by `init`
and refreshed by `update`; never call scripts from the plugin cache directly.
