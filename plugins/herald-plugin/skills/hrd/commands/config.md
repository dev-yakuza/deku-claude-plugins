# CONFIG — dials and off-switches (`/hrd config [key value]`)

Shows `.claude/herald/config.json` in `config.language` with what each dial does; with
`key value` changes one dial.

- Protected keys (`autonomy`, `budget`, `commands`, `paths`, `base_branch`, `roles`, `models`, `translations`,
  `screenshots`, `limner`, `images`)
  are guarded: the edit triggers an `ask` — the human approves it on the record (INV1/INV2).
  Turning on `autonomy.publish: auto` deserves a one-line warning: PRs then merge and deploy
  without per-PR approval (still excluding dismissals, assumptions, deferred audit findings, a skipped audit round, a
  trim, the fact-checker's framings and image changes). Since `/hrd write` runs without questions by default, `auto` then publishes
  articles no human read before the merge/deploy confirmation; use `write --attended` to read
  them first.
- `language` is free to change.
- **Automatic screenshots** (`atoms/_screenshots.md`, design 07). The block
  `"screenshots": {"capture": ["npx", "--no-install", "playwright", "screenshot",
  "--viewport-size={w},{h}", "--color-scheme={scheme}", "--lang={lang}", "{url}", "{out}"]}` is the
  argv Herald runs (no shell) to capture a public page; without it every screenshot is a human's.
  Turning it on: write the block, then `HRD config-check` — its `capture_errors` (a shell or an
  interpreter as the program, `-c`/`-e`, `{url}`/`{out}` not exactly once as a whole element, an
  unknown placeholder) must be empty — and `HRD shot trial` (one capture of `about:blank`; the
  result is deleted). A trial failure → show the install command (`npm i -D playwright` and `npx
  playwright install chromium` for the default) and leave the block out. Turning it off: remove
  the block. A template with errors never stops other commands — capture is simply off (`no-tool`).
- **Images** (`/hrd config images`; `atoms/_images.md`, design 08). The blocks:
  `"limner": {"command": ["lmn"], "state_dir": ".limner"}` and `"images": {"diagrams": {"width":
  1600, "background": "#ffffff"}, "external": true, "figure": {"diagram": "![{alt}]({ref})",
  "licensed": "…{ref} {alt} {credit} {license} {license_url} {page_url}…", "quotation": "…{ref}
  {alt} {credit} {label} {page_url}…", "words": {"licensed": "…", "quotation": "…", "source": "…",
  "orientation": {"landscape": "…", "portrait": "…"}}}, "og": {"path": "{images}/{slug}/og.png",
  "command": null, "subtitle": null, "fallback_first_image": true}}` — each sub-key on its own
  (no `diagrams` → no diagrams, `external` not true → no external images, no `og` → no OG card).
  Turning one on or changing it reuses init's P1 detection and the three P1.5 image questions, then:
  1. `HRD config-check`: `limner_errors`, `og_errors`, `figure_errors` must be empty (each only
     turns its own kind off — never another command); `HRD image doctor` for diagrams and a limner
     OG; `HRD image og --trial` for OG (a repo generator: also with `--category` of each category
     whose badge looks wrong — e.g. a slug printed as a label — and tell the human the fix belongs
     in the repo's script).
  2. **Conflicts with existing personas — never changed silently**: read
     `.claude/agents/illustrator.md` ("Project specifics", "Habits"), `docs/editorial/categories/*.md`
     and `sources.md` for sentences that forbid the kind being turned on or name another tool
     ("no external or work images"); show each with its replacement side by side ("external images
     only through Herald `images.json` — limits in `gate-rules.json` `images.external`"); the human
     approves → change it; declines → do not turn that kind on.
  3. Say: turning OG on makes every new article carry an OG file, so each gets the `images`
     exclusion — with `autonomy.publish: auto` nothing publishes without consent. With
     `translations` on, external images stay off, and articles that already have external images
     on base cannot be translated or refreshed (list them: `HRD translate missing` `blocked`).
     Official photos with no free license (tourist boards, airports) are neither `licensed` nor
     `quotation`: those places are left out.
  4. One commit: `HRD commit --cmd harness --kind config -m "chore(herald): config images" <config,
     gate-rules, sources, personas, category guides, .gitignore — what changed>` → push (protected
     files and keys: the guard asks). `.gitignore` gets `.limner/` in the herald block.
- **Translations**. The block:
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
