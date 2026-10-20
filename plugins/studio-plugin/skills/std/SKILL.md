---
name: std
description: "Studio installs a video production harness into a repository and runs a per-repo production organization (producer, source analyst, content strategist, script writer, fact-checker, visual director, distributor, plus conditional casting director, actor designer, translator) that turns writing already in the repo into narrated videos with script2video, checks every fact against the source, takes each video through four human review gates (script, audition, stills, final) and drafts platform copy. In development: commands answer that they are not implemented yet."
argument-hint: "<command> [video-id|args]"
user-invocable: true
---

# Studio (`/std`)

Route on `$0`: first check that `$0` is exactly one of the valid commands below; only then read
`<<SKILL_DIR>>/commands/$0.md` and execute it (never build a path from anything else). Pass `$1`,
`$2`, … through.

- Valid commands: `init`, `make`, `source`, `brief`, `script`, `verify`, `cast`, `board`,
  `render`, `copy`, `status`, `resume`, `abandon`, `move`, `platform`, `review`, `evolve`,
  `rollback`, `audit`, `config`, `update`, `help`.
- Empty `$0` → `help`. Unknown `$0` → say so, then `help`.

**Development status (0.0.x)**: Studio is being built milestone by milestone. A command whose
file says "Not implemented yet" must do nothing else: tell the user which milestone brings it,
then show `help`. Never improvise the command from the plan.

**Language**: these instructions are in English; everything you say to the user is in the
repo's language (`language` in `.claude/studio/config.json`; before `init`, the language the
user writes in). Machine tokens, ids, paths and commit messages stay English.

Shared rules: `<<SKILL_DIR>>/commands/atoms/_contract.md` (role handoff and result contract),
`atoms/_stages.md` (stage spine and gates), `atoms/_auditor.md` (external auditor),
`atoms/_invariants.md` (floors and invariants), `atoms/_actors.md` (cast and actors).
