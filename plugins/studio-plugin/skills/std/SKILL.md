---
name: std
description: "Studio installs a video production harness into a repository and runs a per-repo production organization (producer, source analyst, content strategist, script writer, fact-checker, visual director, distributor, plus conditional casting director, actor designer, translator) that turns writing already in the repo into narrated videos with script2video, checks every fact against the source, takes each video through four human review gates (script, audition, stills, final) and drafts platform copy. In development: commands answer that they are not implemented yet."
argument-hint: "<command> [video-id|args]"
user-invocable: true
allowed-tools:
  - 'Bash(python3 "${CLAUDE_SKILL_DIR}/scripts/setup.py" doc *)'
---

# Studio (`/std`)

Studio's documents are **printed, never opened**: run
`python3 "${CLAUDE_SKILL_DIR}/scripts/setup.py" doc <name>` (`${CLAUDE_SKILL_DIR}` is this skill's base directory) and
do what it prints. Never use Read, Grep or Glob on the skill folder — each of those asks the person, because the
plugin is outside the working directories.

Route on `$0`: first compare `$0` with the valid commands below. Only when it is exactly one of them, run
`python3 "${CLAUDE_SKILL_DIR}/scripts/setup.py" doc <name>` with `<name>` copied from the list (never `$0` itself,
never a name built from anything else) and execute the document it prints. Pass `$1`, `$2`, … through.

- Valid commands: `init`, `make`, `source`, `brief`, `script`, `verify`, `cast`, `board`,
  `render`, `copy`, `status`, `resume`, `abandon`, `move`, `platform`, `review`, `evolve`,
  `rollback`, `audit`, `config`, `update`, `help`.
- Empty `$0` → `doc help`. Unknown `$0` → say so, then `doc help`.
- Words in the request that ask to stop before a step (`make … — stop and ask before tts and render`) are the person's
  pause requests: `make` passes them to `state.py begin` as `--ask-before` (`doc make`).

**Development status (0.0.x)**: Studio is being built milestone by milestone. A command whose
document says "Not implemented yet" must do nothing else: tell the user which milestone brings it,
then show `help`. Never improvise the command from the plan.

**Language**: these instructions are in English; everything you say to the user is in the
repo's language (`language` in `.claude/studio/config.json`; before `init`, the language the
user writes in). Machine tokens, ids, paths and commit messages stay English.

Shared rules, printed the same way: `doc _contract` (role handoff and result contract), `doc _stages` (stage spine
and gates), `doc _auditor` (external auditor), `doc _invariants` (floors and invariants), `doc _actors` (cast and
actors). A document naming another (`commands/<name>.md`, `atoms/<name>.md`) means `setup.py doc <name>`.
