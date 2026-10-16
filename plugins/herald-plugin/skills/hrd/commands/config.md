# CONFIG — dials and off-switches (`/hrd config [key value]`)

Shows `.claude/herald/config.json` in `config.language` with what each dial does; with
`key value` changes one dial. Plan §3.5.

- Protected keys (`autonomy`, `budget`, `commands`, `paths`, `base_branch`, `roles`, `models`, `translations`)
  are guarded: the edit triggers an `ask` — the human approves it on the record (INV1/INV2).
  Turning on `autonomy.publish: auto` deserves a one-line warning: PRs then merge and deploy
  without per-PR approval (still excluding dismissals, assumptions, deferred audit findings, a skipped audit round, a
  trim, the fact-checker's framings and image changes). Since `/hrd write` runs without questions by default, `auto` then publishes
  articles no human read before the merge/deploy confirmation; use `write --attended` to read
  them first.
- `language` is free to change.
- **Translations** (design/herald/01-multilingual.md §2). The block:
  `"translations": {"source": "<lang>", "targets": [{"lang": "<l>", "body_pattern":
  "{content}/<l>/{slug}.md", "url_pattern": "/<l>/{slug}/"}], "glossary": "<path, optional>",
  "auto_publish": false}` — patterns use only `{content}`/`{slug}` (`{slug}` exactly once),
  `translator` must be in `roles.conditional`. After editing, `HRD config-check` prints
  `Config.validate`'s `errors` and `warnings`: an error names what to fix (overlapping patterns, a pattern inside
  the image directory — Hugo page bundles are not supported —, a missing role); fix before
  committing. A warning (build inputs not covering a translation directory) → offer to add it to
  `paths.build_inputs`.
  - **Turning it on**: add `translator` to `roles.conditional` and, if
    `.claude/agents/translator.md` does not exist (a repo set up without the role), create it
    from `<<SKILL_DIR>>/templates/agents/translator.md` — fill its "Project specifics" in
    `config.language` (language conventions from 2–3 existing translated articles if any) and
    leave the marker region as is; commit it with config.json (`HRD commit --cmd harness --kind
    config … .claude/herald/config.json .claude/agents/translator.md`). The translation stage
    spawns this role.
  - **Turning it on or adding a target**: first list the Herald articles (`published.json`
    `origin: herald`) that already have a file at the new language's path — after the change
    each shows as `translation_added` and **stops deploys until adopted**. Ask per article:
    adopt (queue `/hrd translate <slug> --adopt <l>` after this change), remove the file, or
    cancel the change. Turning it on also groups existing external translations in
    `published.json` under their source entry (`translations: {"<l>": {"path", "url"}}` instead
    of separate articles), says that a custom `commands.validate` now receives `HRD_LANG` per
    file, and offers `gate-rules.json` `languages` overrides (length per language; drafts of the
    house's forbidden phrases in each language, `"status": "draft"`).
  - **Removing a target or changing its pattern**: refuse while `published.json`, a ledger line
    or a topic in progress has that language — `/hrd status --withdraw-lang` (or finishing the
    topic) first. Changing `paths.content`/`body_pattern`/`images` while a Herald article has
    translations: refuse (not supported in 1.0).
- Order: `HRD lock acquire --cmd config` → base checked out and clean → `HRD sync` → edit →
  `HRD commit --cmd harness --kind config -m "chore(herald): config <key>"
  .claude/herald/config.json` → `git push origin <base>` → `HRD lock release --cmd config --token <t>`
  (on every exit path).
