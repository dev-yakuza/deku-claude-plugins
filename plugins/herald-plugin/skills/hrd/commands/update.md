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
   `HRD signal --kind` with a kind other than `session-edit-request`, `human-edit`,
   `review-finding` or `social-edit-request` — those are recorded automatically since 0.3.0 and the call now fails.
   **Style guide** (local-owned, INV4 — never rewritten): when `docs/editorial/style-guide.md`
   has no `<!-- herald:style <v'> -->` marker for the plugin version `v'` that last changed the
   template's "Not AI prose" section (now `0.7.0`), show the template's lines there that the
   style guide does not already say (in any wording or language), translated into
   `config.language` (the `{{AI_TELLS}}` line filled from the style guide's own avoid list and
   the language's common generated-sounding phrases). On approval append them, followed by the
   marker, to the section that holds the AI-prose rules (any heading or language), or as a new
   `## Not AI prose` section at the end if there is none; declined → append only the marker, so
   the offer is not repeated. Additions only; never remove or reword the repo's lines.
   **Refresh policy** (0.10.0): no `docs/editorial/refresh-policy.md` and no `refresh-policy` key in
   `.claude/herald/memory/update-declined.json` → offer to create it from
   `templates/editorial/refresh-policy.md.tmpl` (exceptions left empty for the human); declined
   → `/hrd refresh` keeps using the template's default rules, and the decline is remembered in
   `.claude/herald/memory/update-declined.json` (`{"refresh-policy": "<plugin version>"}`) so the
   offer is not repeated on this machine (the version is kept for a future template change that
   is worth asking again). A new file only, never an edit of an existing one.
4. **Settings/gitignore/labels**: re-merge `templates/settings.json.tmpl` (key union), the
   gitignore block, and create missing labels.
   **Translations** (0.9.0): never added by `update` (INV4). If config has no `translations` and
   the content has locale directories, say once that `/hrd config` can turn translations on.
   A translator persona from before 0.9.0 still has `{{TRANSLATION_TARGETS}}`-style values in
   "Project specifics": offer to replace them with the line pointing to `config.json`
   `translations` (local-owned — on approval only).
   **Social** (0.11.0): a distributor persona from before 0.11.0 lists channels and post conventions
   in "Project specifics" (`{{SOCIAL_CHANNELS}}`-style values or a hand-written list): offer to
   replace them with the one line pointing to `docs/editorial/channels/` (local-owned — on approval
   only; the channel guides from `/hrd social --add` replace them). Never set up social posts here.
   0.12.0 reserves the channel names `persona` and `persona-notes`: a channel guide with either name
   → say it must be removed (`/hrd social --remove`) and added again under another name.
5. Show a summary; on approval `HRD commit --cmd harness --kind update -m "chore(herald):
   update to <v>" <paths>`, `git push origin <base>`.
