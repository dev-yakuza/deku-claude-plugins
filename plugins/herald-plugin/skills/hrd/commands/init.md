# INIT — install the Herald harness (`/hrd init [lang] [--dry-run --out <dir>]`)

Analyzes the repo and its existing articles, interviews the human, and generates the harness
additively. Plan §3.5, §6 M2, D16 (never reads or reuses other local skills). Ported from Guild
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

## P1 — Repo analysis (read-only; spawn up to three Explore agents in parallel)

Exclude `.claude/skills/**` and other local skills from every scan (D16).

1. **Content**: static site generator (Astro/Hugo/Next MDX/Jekyll/…) from config files;
   content directory; body file pattern (`{content}/{slug}.md` or nested); frontmatter keys and
   how the slug is set; categories in use; article count; image directory and how bodies
   reference images; length distribution per category.
2. **Build & deploy**: `package.json` scripts (`build`, `deploy`, `predeploy` chains) and the
   **tracked files they modify** (→ `deploy_artifacts`); CI workflows in `.github/workflows`
   that deploy on push (→ `deploy` empty, required-check advice); hosting config; build input
   directories (→ `paths.build_inputs`: content, images, public); gitignored build derivatives
   in image directories; site base URL and URL pattern (config files, sitemap, README).
3. **Style & policy evidence**: tone, recurring sections, phrases that look like house rules,
   exemplar candidates per category (3 best-structured articles), sitemap/public site
   (→ search-discovery role), multiple locale directories (→ translator), YMYL topics
   (→ subject-expert), an image/diagram pipeline in the repo's own build (→ illustrator).
   Other deploy entry points (scripts or skills that run the deploy command) → **warn only**.

## P1.5 — Interview (attended; `AskUserQuestion`, max 4 questions per call)

Promoted service/app and CTA · north-star metric · domain expertise / YMYL · hard policies
(external mentions, promotion count, copyright rules) · confirm detected paths, deploy command,
base URL · per-article budget (USD) · output language (default: `$1` or the content language).

## P2 — Generate (additive)

1. **Scripts**: copy `<<SKILL_DIR>>/scripts/` (hrd.py, guard.py, integrity.py,
   validate_content.py, measure.py, batch_runner.py, gsc.py, hrdlib/) to `.claude/herald/scripts/`.
2. `.claude/herald/config.json` from `templates/config.json.tmpl` with the detected/confirmed
   values (`roles.conditional` = enabled conditional roles).
3. `docs/editorial/` from `templates/editorial/*.tmpl`: charter (purpose from the interview,
   floor and priority lines verbatim), style guide, one `categories/<cat>.md` per category,
   sources, promotion, exemplars (P1 candidates, human-confirmed), search checklist (if
   enabled), `gate-rules.json` (frontmatter keys from P1, length ranges from the distribution,
   extracted forbidden phrases with `"status": "draft"` — INV6).
4. `.claude/agents/`: the six spine roles + enabled conditional roles from `templates/agents/`;
   fill the "Project specifics" sections in `config.language`; never touch the marker region's
   text.
5. `.claude/herald/topics.json` (empty queue), `.claude/herald/published.json` (every existing
   article as `origin: external`, `current_topic_id: null`), `.claude/herald/evolution-log.md`.
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
3. The human reviews the generated harness (D17 replaces the golden comparison with this
   review) and approves.

## P4 — Commit

`python3 .claude/herald/scripts/hrd.py commit --cmd harness --kind harness -m
"chore(herald): install harness" <generated paths>` then `git push origin <base>`. Summary:
next steps — `/hrd plan`, then `/hrd write <topic-id>`, then `/hrd ship`.
