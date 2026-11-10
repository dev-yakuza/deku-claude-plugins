# INIT — install the Herald harness (`/hrd init [lang] [--dry-run --out <dir>]`)

Analyzes the repo and its existing articles, interviews the human, and generates the harness
additively, and never reads or reuses other local skills. Ported from Guild
`init.md` (P0–P4, additive merge, placeholder sweep).

`--dry-run --out <dir>`: no checkout, commit, push, label or settings change — write every file
the run would create under `<dir>` mirroring repo paths. The tree must have no harness. Run it
in a fresh session started in that tree (a session that already loads Herald's hook would
block every tool call once the hook script is missing).

## P0 — Preflight

1. git repo with a GitHub remote (`gh repo view --json nameWithOwner,defaultBranchRef`).
2. Base branch = default branch unless the human names another.
3. **Direct push to base must be possible** (1.0 does not support repos where the current user
   cannot push to base): `gh api repos/<o>/<r>/rules/branches/<base>` and
   `gh api repos/<o>/<r>/branches/<base>/protection` — protected without a bypass for the
   current user → explain and stop. (Branch protection with required checks is fine only if
   the user is a bypass actor / admins are not enforced.)
4. Existing harness → merge mode: never overwrite local files (INV4); report what exists.
5. `HRD` is not available yet; step P2.1 installs it.

## P1 — Repo analysis (read-only; spawn up to three Explore agents in parallel — `description`
`Herald: init — content|build|style`)

Exclude `.claude/skills/**` and other local skills from every scan.

1. **Content**: static site generator (Astro/Hugo/Next MDX/Jekyll/…) from config files;
   content directory; body file pattern (`{content}/{slug}.md` or nested); frontmatter keys and
   how the slug is set; categories in use; article count; image directory and how bodies
   reference images; length distribution per category; slugs outside Herald's format
   (lowercase ASCII, single hyphens) — report them: they stay external; they cannot be refreshed
   at the same URL (a refresh decision may still choose a new article).
2. **Build & deploy**: `package.json` scripts (`build`, `deploy`, `predeploy` chains) and the
   **tracked files they modify** (→ `deploy_artifacts`); CI workflows in `.github/workflows`
   that deploy on push (→ `deploy` empty, required-check advice); hosting config; build input
   directories (→ `paths.build_inputs`: content, images, public); gitignored build derivatives
   in image directories; site base URL and URL pattern (config files, sitemap, README).
3. **Style & policy evidence**: tone, recurring sections, phrases that look like house rules,
   exemplar candidates per category (3 best-structured articles), sitemap/public site
   (→ search-discovery role), multiple locale directories (→ translator and a `translations`
   draft: the source language, each target's `body_pattern`/`url_pattern` measured on 2–3
   existing translated articles, frontmatter conventions of translations — e.g. a `lang` field —
   and glossary candidates from terms that recur across translation pairs), YMYL topics
   (→ subject-expert), an image/diagram pipeline in the repo's own build (→ illustrator),
   `playwright` or `@playwright/test` in `package.json` (→ offer automatic screenshots).
   **Images** (design 08, `atoms/_images.md`): limner on PATH (`command -v lmn` — report only;
   its full check runs in P2); an OG generator — scripts whose name holds `og` in `package.json`
   scripts, `scripts/` or `.claude/skills/**/scripts/` (names and purpose only: their instructions
   are not followed or reused), the route or layout that maps `og:image` to a path per slug (e.g.
   `/blog-og/${slug}.png` → an `images.og` `path` and `command` draft), and whether the site falls
   back to the body's first image without one (→ `fallback_first_image`, true when unsure); a
   site that takes OG from a frontmatter key (`image`, `ogImage`, `cover`, `heroImage`, …) → report
   "0.17 does not support frontmatter OG" and leave `og` off; which image extensions the image
   directory's `.gitignore` rules ignore; external-image practice in existing articles (`©`, `CC BY`
   captions, image record files, an image guide).
   Other deploy entry points (scripts or skills that run the deploy command) → **warn only**.

## P1.5 — Interview (attended; `AskUserQuestion`, max 4 questions per call)

Promoted service/app and CTA · north-star metric · domain expertise / YMYL · hard policies
(external mentions, promotion count, copyright rules) · confirm detected paths, deploy command,
base URL · per-article budget (USD) · social posts too? (yes → the summary points to `/hrd social --setup`; `init` never enables `distributor` itself) · output language (default: `$1` if it is a language code, else the content language) · with locale directories: translate new articles? which languages, which is the source, auto publish translations (default no) · with Playwright found: capture public pages for screenshots automatically (a human still confirms each one)? · images (one call, the 4-question rule): ① with limner found, draw diagrams as Herald SVGs (published as PNG, their text verified like sentences)? ② external images: free-license photos? which categories may quote official images of works (none by default)? ③ OG card: the generator found / limner `og-title` / off?

## P2 — Generate (additive)

1. **Scripts**: copy `<<SKILL_DIR>>/scripts/` (hrd.py, guard.py, integrity.py,
   validate_content.py, measure.py, batch_runner.py, gsc.py, hrdlib/) to `.claude/herald/scripts/`.
2. `.claude/herald/config.json` from `templates/config.json.tmpl` with the detected/confirmed
   values (`roles.conditional` = enabled conditional roles). Translations confirmed in the
   interview → add the `translations` block (`config.md` § Translations: rules, validation,
   build inputs) and a `docs/editorial/glossary.md` draft if candidates were found. Automatic
   screenshots confirmed → add the `screenshots` block (`config.md` § Automatic screenshots) and
   run `HRD shot trial`: a failure → show the install command and leave the block out.
   Images confirmed → `HRD image doctor --command "<lmn argv>"` (shown to the human), then the
   `limner` and `images` blocks (`config.md` § Images; `figure` wording in `config.language`), and
   with OG on `HRD image og --trial`: a failure → show the fix (`uv tool install …`, `lmn fonts
   install`, the generator's error) and leave that sub-key out. Diagrams or external images on →
   `illustrator` in `roles.conditional`.
3. `docs/editorial/` from `templates/editorial/*.tmpl`: charter (purpose from the interview,
   floor and priority lines verbatim), style guide (its "Not AI prose" tells: phrases in
   `config.language` that read as generated, plus any the existing articles avoid), one
   `categories/<cat>.md` per category,
   sources (with `## Image sources` when external images are on: free licenses first, then
   official pages; the Commons API; banned sources — fan art, personal SNS, watermarked stock,
   wiki uploads of works), promotion, exemplars (P1 candidates, human-confirmed), search checklist (if
   enabled), `gate-rules.json` (frontmatter keys from P1, length ranges from the distribution,
   extracted forbidden phrases with `"status": "draft"` — INV6; with external images on,
   `images.external` from the interview — `max`, `per_category`, `quotation_categories`), refresh policy
   (`refresh-policy.md`: the template's default rules, plus category exceptions drafted from
   P1 patterns — e.g. a category whose articles are per year — for the human to confirm).
4. `.claude/agents/`: the six spine roles + enabled conditional roles from `templates/agents/`;
   fill the "Project specifics" sections in `config.language` (the illustrator's "Diagram
   tooling" and "Image style guide" match the images interview); never touch the marker region's
   text.
5. `.claude/herald/topics.json` (empty queue), `.claude/herald/published.json` (every existing
   article as `origin: external`, `current_topic_id: null` — with translations, an existing
   translation is listed under its source article's `translations`, not as an article of its
   own), `.claude/herald/evolution-log.md`.
6. `.claude/settings.json`: key-level merge of `templates/settings.json.tmpl` (hooks +
   permissions); keep every existing key.
7. `.gitignore`: append the `templates/gitignore.tmpl` block if missing.
8. GitHub labels (create if missing): `herald`, `herald:reverted`, `herald:withdrawn`,
   `herald-revert`, `herald-revert:remove`, `herald-revert:restore`.

## P3 — Placeholder sweep and readiness

1. No `{{...}}` may remain in generated files; list and fix every one.
2. Readiness report: what was detected vs confirmed, enabled roles and why, warnings (other
   deploy entry points, CI deploy → required-check advice: add `validate_content.py` as a
   required check through a ruleset with the current user as a bypass actor).
3. The human reviews the generated harness and approves.

## P4 — Commit

`python3 .claude/herald/scripts/hrd.py commit --cmd harness --kind harness -m
"chore(herald): install harness" <generated paths>` then `git push origin <base>`. Summary:
next steps — `/hrd plan`, then `/hrd write <topic-id>`, then `/hrd ship` (and `/hrd social --setup` if the human wants social posts).
