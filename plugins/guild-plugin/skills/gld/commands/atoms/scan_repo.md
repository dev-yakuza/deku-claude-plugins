# SCAN: repo (init P1 analysis family)

**Read-only analysis atoms for `/gld init` Phase 1.** Six scans discover the repo's shape so init can specialize the Guild (role agents) and draft standards. Each scan is independently spawnable (Haiku tier — mechanical) and returns a compact JSON summary. The main session (init.md) spawns them in parallel and feeds the summaries to P2.

> **Bash Command Execution**: simple Bash calls only (`_bash_rules.md`). For code discovery use Grep/Glob/Read, never Bash `find` outside repo root. **Read-only**: no Edit/Write, no code changes.

---

## Common output shape

Every scan returns EXACTLY one `>>> RESULT <<<` line followed by a compact JSON object:

```
>>> RESULT <<<
{ "scan": "<name>", "findings": { ... } }
```

Keep findings small — a summary, not a dump. Values missing/undetectable → `null` or `[]`. Never fail the whole init; if a scan can't determine something, return partial findings with the unknown fields null.

---

## Section 1 — stack-scan

**Goal**: identify languages, frameworks, package manager, runtime.

1. Detect manifests (Glob): `package.json`, `pyproject.toml`, `go.mod`, `Cargo.toml`, `pom.xml`, `pubspec.yaml`, `Gemfile`, etc.
2. Read the primary manifest(s). Extract: language(s), major frameworks/libraries, package manager (yarn/npm/pnpm/pip/poetry/cargo/…), monorepo tooling (workspaces, turbo, nx).
3. Note test/build framework hints from devDependencies (jest, vitest, pytest, playwright, …).

Findings:
```json
{ "scan": "stack", "findings": {
  "languages": ["typescript"], "frameworks": ["react", "next"],
  "package_manager": "yarn", "monorepo": true, "test_framework": "vitest" } }
```

## Section 2 — command-scan

**Goal**: the verification commands the harness needs, **normalized to simple-bash-safe form** so Guild can run them directly.

1. Read `package.json` `scripts` (or Makefile / justfile / pyproject `[tool.*]` / CI config / `dart_test.yaml` / `scripts/` / language-native runner).
2. Map to the canonical categories: `test` (unit), `lint`, `typecheck`, `build`, **`e2e`** (integration / end-to-end), **`vrt`** (visual regression — golden / screenshot comparison). Prefer the repo's actual invocation (e.g. `yarn test`, `flutter test`, `pytest`).
3. **Detect E2E / integration tests explicitly** — the default `test` command often does NOT run them:
   - Look for dedicated dirs/config: `integration_test/`, `e2e/`, `test/e2e/`, `cypress/`, `playwright.config.*`, `*.spec.ts` under an e2e folder, Detox, Maestro.
   - For Flutter: an `integration_test/` dir + `integration_test` dev-dependency → e2e command is `flutter test integration_test` (NOT covered by a plain `flutter test`, which runs `test/` only).
   - Record the e2e run command in `e2e`. If integration tests exist but you can't determine the exact command, still record the dir so the finding isn't lost (e.g. `"e2e": "flutter test integration_test"` with a note in `test_dirs`).
   - Also note special test tags/suites (e.g. `dart_test.yaml` `golden` tag) under `test_dirs`/notes if present.
3b. **Detect visual regression tests (golden / VRT) explicitly** — a separate category because the default `test` command may or may not include them, and because their *expected values are image files* the commit gate and the PR have to know about. Output feeds `config.json` per `_handoff.md` Section L.0:
   - **Run command → `vrt`**. Flutter: goldens tagged `golden` **and excluded by default** → `flutter test --tags golden` for the `exclude_tags` idiom, but **`flutter test --tags golden --run-skipped`** for the `tags: golden: skip:` idiom (`--tags` only selects; a tag-level `skip` still applies without `--run-skipped`, and the run reports everything skipped); goldens that `commands.test` already runs (untagged, or tagged but not excluded) → `vrt: null` with `notes: "golden 은 test 에 포함"` — recording them twice runs them twice. JS: `@playwright/test` with `toHaveScreenshot`, Vitest browser mode with `toMatchScreenshot`, `storycap`/`reg-suit`, Chromatic — **a script name alone (`test:view`, `vrt`) is not evidence**: confirm a screenshot matcher in the files it runs, or committed images, before calling it visual (a repo can have a `test:view` per app that only renders into happy-dom). Other stacks: the equivalent screenshot runner.
   - **Expected images → `vrt_baselines`** (globs, repo-root-relative, `**/` for any depth): where **committed** expected images live — e.g. `test/**/goldens/**`, `**/__screenshots__/**`, `**/*-snapshots/**`. Take them from the runner's config (`snapshotPathTemplate`, `goldenFileComparator`, `resolveScreenshotPath`) or from where committed images actually sit (`git ls-files` on the candidate dirs). ⚠ **Only globs you have seen committed images under** — never a guessed `**/*.png`: these drive a commit-gate warning, and one that matches ordinary assets fires on every icon change until nobody reads it. Off-repo storage (Chromatic, reg-suit's bucket) → `[]`.
   - **Custom matchers → `vrt_matchers`**: names the repo registers with `expect.extend` (or wraps around `matchesGoldenFile`) in its visual helpers — e.g. `toMatchThemeScreenshot`, `toMatchHoverScreenshot`. The gate counts these calls; an unlisted name ending in `Screenshot` is recognized anyway, any other is not.
   - **Visual test files → `vrt_tests`** (globs): the files that hold the screenshot/golden matchers — e.g. `**/*.vitest.tsx`, `**/*.visual.spec.ts`, `test/**/*_golden_test.dart`. The commit gate treats these as test paths; a name like `index.vitest.tsx` matches no generic test convention, so without this a deleted or skipped visual test goes unseen.
   - **Where → `vrt_packages`** (dirs): the packages/apps that actually have visual tests (`packages/lib/components`); `[]` when the whole repo is one package. Design only writes visual cases for UI work inside these.
   - **Comparison config → `vrt_config_files`** (**repo-root-relative** paths or globs — the gate matches from the repo root, so a package-relative `src/…` never matches in a monorepo): the files that set tolerance/threshold/comparator or which visual tests run — `vitest.config.*`/`vitest.workspace.*` (browser `expect.toMatchScreenshot` options), `playwright.config.*` (`expect.toHaveScreenshot`), `**/flutter_test_config.dart` (`goldenFileComparator` — a glob, because a new per-directory one also applies), `dart_test.yaml` (tags), `regconfig.json`, any shared matcher helper the visual tests import (e.g. `packages/ui/src/test-utils/matchers.ts`), and the files the runner config names in `setupFiles`/`globalSetup` (global CSS, masking, animation off — they change what is rendered). Only files that exist and carry such settings.
   - **Rendering environment → `vrt_env`** (one line, **with CPU architecture** — `docker linux/amd64`; an unpinned Docker image builds arm64 on Apple silicon and renders differently from amd64 CI) and **`vrt_runnable`** (bool): where the expected images were rendered — read the CI workflow that runs them and any Docker wrapper (`docker compose … vrt`, a `Dockerfile` under the package). **Decide `vrt_runnable` from evidence when you can**: with the human's OK, run `vrt` once on the clean tree (foreground, timeout) — green means `true` whatever the architecture says (a tolerance like `allowedMismatchedPixelRatio` may absorb arm64/amd64 differences), red on an untouched tree means `false` with the failure count in `notes`. Without a trial run: `vrt_runnable: false` when the run needs a TTY with no non-interactive form, or when the images are only reproducible in an environment Guild does not run in (e.g. rendered on Linux CI with no local container, while Guild runs on the developer's macOS host) — a run outside that environment fails on rendering noise, and a stage that trusts it either loops forever or "fixes" it by rewriting images.
   - **Developer's scoped recipe → `vrt_create`**: the create/update form **with a `<file>` placeholder**, carrying the **same tag/selection flags and environment** as `vrt` (a `golden`-tagged suite excluded by default needs `--tags golden` here too, or the update silently runs nothing), in the same normalized shape as other commands; `<file>` is relative to where the runner resolves paths (inside a container, its working directory) (e.g. `flutter test --tags golden --run-skipped --update-goldens <file>`, `["docker compose -f packages/ui/compose.yaml build vrt", "docker compose -f packages/ui/compose.yaml run --rm vrt npx vitest run -u <file>"]`). ⚠ This is the **only** place an update command is recorded, and it is never a command any stage runs on its own: `_handoff.md` Section L.4 limits it to the developer, scoped to the files the Issue touched. Never record a whole-suite update form, and never record it under `commands`. No scoped form exists → `null`.
   - **Developer's scoped compare → `vrt_run_file`**: the same as `vrt` narrowed to one test file with a `<file>` placeholder, **no update flag** (e.g. `flutter test --tags golden --run-skipped <file>`, or the docker form ending in `npx vitest run <file>`). `null` when the runner cannot be narrowed.
   - ⚠ **Non-interactive only.** Visual runners are often wrapped in Docker (`docker compose run --rm -it vrt …`). `-it`/`-t` allocates a TTY, which the Bash tool does not have — the call fails or hangs. Drop `-i`/`-t`/`-it` from a `docker run`/`docker compose run` step; if the wrapper script hard-codes them and there is no non-interactive equivalent, keep the command but set `vrt_runnable: false` with the reason in `notes`.
   - ⚠ **Every step runs from the repo root**, one Bash call each (`_bash_rules.md` forbids `cd … &&`, and the working directory does not carry between calls). For a monorepo package, express the directory with the tool's own flag — `docker compose -f <pkg>/compose.yaml` (or `--project-directory <pkg>`), `yarn --cwd <pkg>` / `yarn workspace <name>`, `npm --prefix <pkg>`, `flutter test <pkg>/test`. No such flag → `vrt_runnable: false` with the reason.
4. **Normalize each command to be directly runnable via a single Bash call** (per `_bash_rules.md`). A stored command MUST NOT contain `$(...)` or backticks, `&&`, `||`, `|`, `;`, `&`, newlines, or redirections:
   - **Shell substitution** — `$(...)` **or backticks** (e.g. `--concurrency=$(nproc --all)`, `--concurrency=`` `nproc` ``) → **drop that flag** (test runners auto-detect sane defaults). Record the base command only.
   - **Chained steps** (e.g. `flutter analyze && npx remark . --quiet --frail`) → return an **array** of the atomic steps: `["flutter analyze", "npx remark . --quiet --frail"]`. A `yarn <script>` whose script body is itself a chain is resolved the same way: read the script body and store its atomic steps (e.g. `test:view` in `packages/ui` = `docker compose build vrt && docker compose run --rm -it vrt npx vitest` → `["docker compose -f packages/ui/compose.yaml build vrt", "docker compose -f packages/ui/compose.yaml run --rm vrt npx vitest run"]` — the package directory made explicit, `-it` dropped, and the watch-mode `vitest` made a single run with `run`, per 3b).
   - A single simple command → return it as a plain string.
5. If a category has no command, return `null` for it.

Findings (note `test` normalized from `$(...)`, `lint` split into an array, `e2e` detected from `integration_test/`, `vrt` from the `golden` tag with its baselines located):
```json
{ "scan": "command", "findings": {
  "test": "flutter test --fail-fast",
  "lint": ["flutter analyze", "npx remark . --quiet --frail"],
  "typecheck": null, "build": null,
  "e2e": "flutter test integration_test",
  "vrt": "flutter test --tags golden",
  "vrt_baselines": ["test/**/goldens/**"], "vrt_config_files": ["dart_test.yaml", "test/flutter_test_config.dart"],
  "vrt_env": "CI ubuntu-latest amd64 (flutter 3.x)", "vrt_runnable": false, "vrt_create": "flutter test --tags golden --update-goldens <file>", "vrt_run_file": "flutter test --tags golden <file>", "vrt_matchers": [],
  "vrt_tests": ["test/**/*_golden_test.dart"], "vrt_packages": [],
  "test_dirs": ["test/", "integration_test/"], "notes": "dart_test.yaml has a `golden` tag" } }
```
(`vrt_runnable: false` here because the goldens are rendered on Linux CI and nothing reproduces that locally — a macOS run would fail on font hinting alone.) No visual tests found → `"vrt": null, "vrt_baselines": [], "vrt_tests": [], "vrt_packages": [], "vrt_matchers": [], "vrt_run_file": null, "vrt_config_files": [], "vrt_runnable": false, "vrt_env": null, "vrt_create": null` (not an error — `audit_readiness.md` reports the gap for a UI repo; Guild does not introduce the tooling).

## Section 3 — convention-scan

**Goal**: coding conventions from code + git history.

1. Read linter/formatter config (`.eslintrc*`, `biome.json`, `.prettierrc*`, `ruff.toml`, `.editorconfig`).
2. `git log --oneline -30` → commit message convention (prefixes, language, em-dash, version-bump format).
3. Sample 2–3 representative source files (Grep/Read) → naming style, import ordering, error handling, test file placement.
4. **Branch naming** (feeds `conventions.md`'s `{{PR_CONVENTION}}`, which otherwise has no evidence source anywhere in init — this is it): `git branch -a --format='%(refname:short)'` (local + remote branch names) → identify the prevailing pattern if one exists (e.g. `feature/#<n>-<slug>`, `feat/<slug>`, `<user>/<slug>`) from the non-`main`/`master`/`HEAD` entries. Sparse/no pattern (a fresh or trunk-only repo) → report `"unclear"`, do not guess. PR-size norms and review-rule conventions are **not** derivable from git history alone (they live in team practice / branch-protection settings, not the repo tree) — leave those to init's `{{PR_CONVENTION}}` fill-in as an honest "(미정 — 팀 규칙 확인 필요)" rather than inventing them from this scan.

Findings:
```json
{ "scan": "convention", "findings": {
  "commit_style": "conventional (feat:/fix:), Japanese subject",
  "lint": "eslint + prettier", "naming": "camelCase, PascalCase components",
  "test_location": "colocated *.test.tsx", "branch_naming": "feature/#<n>-<slug>" } }
```

## Section 4 — structure-scan

**Goal**: layering, module boundaries, where code lives.

1. Glob the top-level tree and the main source dir (`src/`, `apps/`, `packages/`, `lib/`).
2. Identify layers/domains (e.g. `apps/*`, `packages/*`, feature folders, `components/`, `services/`).
3. Note boundary signals: barrel files, path aliases (tsconfig `paths`), obvious layering (ui/domain/data).

Findings:
```json
{ "scan": "structure", "findings": {
  "layout": "yarn-workspaces monorepo",
  "apps": ["web", "admin"], "shared": ["@packages/components"],
  "boundaries": "path aliases via tsconfig paths" } }
```

## Section 5 — existing-scan

**Goal**: existing harness so init merges instead of clobbering (init is additive).

1. Check for and read (if present): `CLAUDE.md`, `AGENTS.md`, `.claude/settings.json`, `.claude/settings.local.json`, `.claude/agents/`, `.github/workflows/` (CI), `docs/`.
2. Note whether a Guild install already exists (`.claude/guild/config.json`) — P0 concern, but report here too.
3. Note existing permission allowlists and hooks so init's merge preserves them.

Findings:
```json
{ "scan": "existing", "findings": {
  "claude_md": true, "settings_json": true,
  "existing_agents": [], "ci": ["ci.yml", "vrt.yml"],
  "guild_installed": false, "docs_dir": true } }
```

## Section 6 — hotspot-scan

**Goal**: fragile / bug-prone areas from **git history** — evidence-driven, so init does NOT have to ask the human "where are the risky areas?" (that question is un-answerable on the spot; the history knows). Feeds the roles' "주의(핫스팟·함정)" and the readiness audit.

⚠ **This scan is analytical, not mechanical** — it must tally frequencies across many commits. Spawn it at **Sonnet** (not Haiku). `_bash_rules` forbids pipes, so the sub-agent reads the raw `git log` output and ranks it **by reading** — exact counts are NOT required; an approximate "which paths repeat most" is the goal. Keep windows modest so the output stays readable. ⚠ The windows below (`-150`/`-200`) are **deliberately wider** than `scan_git.md`'s near-identically-worded steps (`-80`/`-120`): this is init-time *baseline* profiling (one deep read of the whole history's shape), that one is evolve-time *incremental* re-reading — the prose is shared, the numbers are not, so do not "sync" them.

⚠ **Generated-asset flood (robustness — observed on real data, MUST handle, same as `scan_git.md` Section 0)**: a single commit that regenerates assets (SVG/PNG icons, golden images, minified bundles, lockfiles) can dump **thousands** of file paths into `--name-only` output — enough to blow this sub-agent's context. Measured on word_app: an unscoped `-120` name-only log = **6675 lines**; the same log **scoped to the source dir = 719 lines**. **Detect the main source dir first** (Glob, not Bash — `lib/`, `src/`, `app/`, `packages/*/src`), then scope every `git log --name-only` call below to it with a pathspec (` -- lib`) — a pathspec is not a pipe, stays atomic-bash-safe, and is the **default**, not a fallback. Only run unscoped if no clear source dir exists (then keep the window small and ignore asset paths by eye).

All read-only, each its own Bash call (`_bash_rules.md`; no `|`, `&&`, `$(...)`, redirections — read the tool output and rank by inspection):

1. **Bug-fix concentration** — where `fix:` commits cluster (conventional-commit `fix:` = a past bug).

   ⚠ **`--grep` cannot be restricted to the subject line — the `^` anchor does NOT fix body false-positives.** Git matches the pattern **line by line** against the whole commit message, so `^` anchors at the start of *every* line, body included (PCRE `\A` under `-P` behaves identically). **Verified on git 2.50.1**: a `feat:` commit whose body carries a line `fix: also handle X` still matches `--grep='^fix[(:]'`. Git offers **no** subject-only grep option, and the construction that would filter properly (`git log --pretty=%s` piped into a filter) is forbidden here (`_bash_rules.md`). The anchor is a **prefilter, not a filter**: it removes mid-line noise ("…a fixture…"), not a body line that itself starts with `fix:`.

   **Account for the residue by printing the subject** and discarding, by eye, any block whose *subject* does not itself start with `fix:` / `fix(` — hence `%h %s` in the format rather than an empty one. One call (substitute the source-dir pathspec from above, e.g. `-- lib`):
   ```bash
   git log --name-only --pretty=format:'%h %s' --grep='^fix[(:]' -i -150 -- lib
   ```
   Output is one `<sha> <subject>` header line per commit followed by its paths; skip a commit's whole path block when its subject fails the check. Read the surviving output and identify the **~8 most-frequently-appearing paths** (approximate ranking by eye is fine). Those = bug hotspots. Group nearby files into their area/layer.
2. **Churn** — most-frequently-changed files overall (instability signal). One call (same source-dir pathspec):
   ```bash
   git log --name-only --pretty=format: -200 -- lib
   ```
   Identify the top repeated paths. High churn = area that keeps needing change. (i18n/string files often top churn without being *bug* hotspots — note the distinction.)
3. **Co-change** — files that repeatedly change *together* (hidden coupling): from the same output, note pairs/groups that recur across commits. Report the strongest recurring groups.
4. **Group by directory/path prefix** (from the same `git log` output alone — e.g. every hotspot path under `lib/sync/` groups as "sync/ 계층") to describe hotspots by area, not just single files. ⚠ Do **not** assume access to the structure-scan's own output here — `init.md` spawns all six `scan_repo.md` sections as **isolated, parallel** sub-agents with no shared context, so this section cannot literally read what Section 4 (structure-scan) found in the same run. Directory-prefix grouping from this section's own `git log` output is the self-contained approximation; the deeper, structure-scan-informed cross-reference happens later, when the main session (`init.md` P2) has both scans' results together.

**MUST return concrete paths with an approximate rank** (e.g. `db_helper.dart` appears in most fix commits) — an empty/vague result when the history clearly has hotspots is a scan failure. Keep to top-N; do not dump the full log. If git history is genuinely shallow/unavailable → return empty lists (best-effort; never block).

Findings:
```json
{ "scan": "hotspot", "findings": {
  "bug_hotspots": [ { "path": "lib/controller/sync_data_controller.dart", "fix_count": 9 }, { "path": "lib/services/sync/", "fix_count": 6 } ],
  "high_churn": [ "lib/settings_controller.dart", "lib/word_service.dart" ],
  "co_change": [ ["sync_data_controller.dart", "services/sync/index.dart"] ],
  "note": "동기화 계층이 fix·churn·co-change 모두 상위 — 변경 시 회귀 위험 높음" } }
```

---

## Hard rules
- **Read-only.** No Edit/Write/NotebookEdit. No git mutations.
- **Bounded.** ~8 Read + 4 Grep + 3 Glob per scan. Summarize; do not dump file contents into the RESULT.
- **Never block init.** Undetectable fields → null. Partial findings are acceptable.
- Return exactly one `>>> RESULT <<<` line + JSON.
