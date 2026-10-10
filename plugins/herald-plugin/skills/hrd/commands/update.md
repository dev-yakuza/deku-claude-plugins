# UPDATE — adopt central improvements (`/hrd update [--check]`)

Refreshes plugin-owned parts without clobbering local evolution (INV4). `--check` reports
only. Ported from Guild `update.md`.

1. `HRD lock acquire --cmd update` (keep the token; `HRD lock release --cmd update --token <t>` on
   every exit path); base clean; `HRD sync`.
2. **Scripts**: diff `<<SKILL_DIR>>/scripts/` against `.claude/herald/scripts/`; show the
   changed files; on approval copy them (the guard asks — these are guard wiring). Never keep a
   locally edited central script silently: if a local copy differs from both the old and new
   central versions, show the diff and ask.
3. **Personas**: for each `.claude/agents/<role>.md` that came from a template, replace only the
   frontmatter `name`/`description` and the region between `<!-- herald:persona:start -->` and
   `<!-- herald:persona:end -->` with the central template's; keep "Project specifics" and
   "Habits". Missing markers → skip that file and report it.
4. **Settings/gitignore/labels**: re-merge `templates/settings.json.tmpl` (key union), the
   gitignore block, and create missing labels.
5. Show a summary; on approval `HRD commit --cmd harness --kind update -m "chore(herald):
   update to <version>" <paths>`, `git push origin <base>`.
