# UPDATE — adopt central improvements (`/hrd update [--check]`)

Refreshes plugin-owned parts without clobbering local evolution (INV4). `--check` reports
only. Ported from Guild `update.md`.

1. `HRD lock acquire --cmd update` first (keep the token; `HRD lock release --cmd update --token
   <t>` on every exit path) — a held lock from a crashed session: show `HRD lock status`, and on
   the human's approval `HRD lock unlock`, then acquire. Then the tracked tree must be clean
   (else stop); `git switch <base>`; `HRD sync`.
   **Direction** (after the sync, so base is current): `v` = `version` in
   `<<SKILL_DIR>>/../../.claude-plugin/plugin.json`; `HRD version --against <v>` (a failing
   command = older than 0.3.0). `newer` → stop: the plugin is older than the repo; update the
   installed plugin and restart instead (an update now would downgrade the repo for everyone).
   `equal` → only personas/settings may differ; continue (`--check` reports only).
2. **Scripts**: diff `<<SKILL_DIR>>/scripts/` against `.claude/herald/scripts/`; show the
   changed files; on approval copy them (the guard asks — these are guard wiring). Never keep a
   locally edited central script silently: if a local copy differs from both the old and new
   central versions, show the diff and ask.
3. **Personas**: for each `.claude/agents/<role>.md` that came from a template, replace only the
   frontmatter `name`/`description` and the region between `<!-- herald:persona:start -->` and
   `<!-- herald:persona:end -->` with the central template's; keep "Project specifics" and
   "Habits". Missing markers → skip that file and report it. Also report any persona or
   editorial text (any file, including the kept sections) that tells the session to run
   `HRD signal --kind` with a kind other than `session-edit-request`, `human-edit` or
   `review-finding` — those are recorded automatically since 0.3.0 and the call now fails.
4. **Settings/gitignore/labels**: re-merge `templates/settings.json.tmpl` (key union), the
   gitignore block, and create missing labels.
5. Show a summary; on approval `HRD commit --cmd harness --kind update -m "chore(herald):
   update to <v>" <paths>`, `git push origin <base>`.
