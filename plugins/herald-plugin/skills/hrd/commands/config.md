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
  "command": null, "subtitle": null, "fallback_first_image": true}, "scenes": {"max": 2,
  "per_category": {}, "style": "<English, one line>", "wait_minutes": 30}}` (0.18.0; `figure` may
  add `"scene": "![{alt}]({ref})\n*{label}*"` — `{ref}`, `{alt}` and `{label}` all required — and
  `words.scene`, the AI label, 1–60 characters; without them the default template and the source
  language's label: ko "AI 생성 이미지", ja "AI生成画像", en "AI-generated image") — each sub-key on
  its own (no `diagrams` → no diagrams, `external` not true → no external images, no `og` → no OG
  card, no `scenes` → no scene images). `scenes`: `max` and `per_category` values 0–6, `style` at
  most 300 printable ASCII characters (the repo's one picture style, appended to every scene
  prompt), `wait_minutes` 5–120 (how long one collect step waits for generation). Scenes also need
  the illustrator, no `translations`, and — on a site that falls back to the first image as its SNS
  card (`fallback_first_image`, assumed without an `og` block) — OG on (`why: og-fallback`).
  0.21.0 (`atoms/_images.md` §9, design 12): `scenes` may add `"stand_in": false` (stand-ins are
  **on by default** wherever scenes and external images are both on: an external place on an
  `external (place|thing)` brief line with no usable photo becomes a generic AI scene labelled
  "not the actual place"), `"stand_in_per_category": {"<cat>": true|false}` (a category in
  `gate-rules` `quotation_categories` is off unless named `true`), `"decorative": 0–3` (default 0 —
  opt-in decorative pictures between sections, within the scene, external and total limits) and
  `"decorative_per_category": {"<cat>": 0–3}`; `figure.words` may set the stand-in labels
  `scene_place` / `scene_thing` (1–60 characters, never the same as `words.scene`; defaults: ko
  "AI 생성 이미지(실제 장소 아님)" / "AI 생성 이미지(실물 아님)", ja "AI生成画像（実在の場所ではありません）" /
  "AI生成画像（実物ではありません）", en "AI-generated image (not the actual place)" / "AI-generated image
  (not the actual object)"), and `figure.stand_in` a template of its own (`{ref}`, `{alt}`,
  `{label}`; default `figure.scene`). A template that hides `{label}` (`hidden`, `sr-only`,
  `visually-hidden`, `display:none`) is an error. A mistake in these keys turns only stand-ins
  (`stand_in_errors`) or decorative pictures (`decorative_errors`) off — never the scenes.
  Changing a stand-in label: ask the human "does this text say it is not the actual place /
  object?" first.
  Turning one on or changing it reuses init's P1 detection and the P1.5 image questions, then:
  1. `HRD config-check`: `limner_errors`, `og_errors`, `figure_errors`, `scene_errors` (and
     0.21.0's `stand_in_errors`, `decorative_errors`; `HRD image kinds` `scene.stand_in.ok`,
     `scene.decorative.max`) must be
     empty (each only turns its own kind off — never another command); `HRD image doctor` for
     diagrams and a limner OG; `HRD image og --trial` for OG (a repo generator: also with
     `--category` of each category whose badge looks wrong — e.g. a slug printed as a label — and
     tell the human the fix belongs in the repo's script). Scenes: `HRD image kinds` `scene.ok`
     (else its `why`: `generate:env` → "`lmn setup` — about 54 GB; a model already in
     `~/.cache/models` is shared"), then **one trial picture**: `HRD image generate --trial --wait
     240` with the Bash `timeout` at 300000 ms, again while `running` (a cold model load passes 240 s) — show the human the `file` (under
     the state dir, never the image dir; no ledger) and ask whether the style is right; change
     `style` and try again, or turn scenes off. Turning scenes off: remove `scenes`.
  2. **Conflicts with existing personas — never changed silently**: read
     `.claude/agents/illustrator.md` ("Project specifics", "Habits"), `docs/editorial/categories/*.md`
     and `sources.md` for sentences that forbid the kind being turned on or name another tool
     ("no external or work images"); show each with its replacement side by side ("external images
     only through Herald `images.json` — limits in `gate-rules.json` `images.external`"); the human
     approves → change it; declines → do not turn that kind on. The same for stand-ins and
     decorative pictures: a sentence such as "no decorative images" or "never draw a real place
     with AI" is shown with a replacement ("decorative pictures only within
     `images.scenes.decorative`, between sections — no text, real person or work, never first") —
     declined → `decorative: 0` / `stand_in: false`. "Photos only under free licenses" is a photo
     rule, no conflict. A decorative picture or stand-in is a scene: the same generation time,
     human confirmation, AI label and PR prompt. 0.23.0: when a kind is turned on, also run
     `update.md`'s image-kinds scan (step 1a) — every image line read by `atoms/_images.md` §1's
     `guide:` rules, so a line that only names what a category usually gets ("도해 1장") is seen
     before section images are planned around it — and offer the same (a) keep / (b) diagrams
     only by `per_category` 0 / (c) clarify choice for the listed lines. An existing
     `image-kinds-reading` key in `.claude/herald/memory/update-declined.json` skips the question
     (the lines are still shown); config's answer is recorded there the same way, after its push.
  3. Say: turning OG on makes every new article carry an OG file, so each gets the `images`
     exclusion — with `autonomy.publish: auto` nothing publishes without consent. Scenes: each one
     takes minutes on this machine (a model load too), a human confirms each in draft (batch:
     a `screenshots` hold), every picture shows the AI label, and its prompt goes into the PR body. With
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
