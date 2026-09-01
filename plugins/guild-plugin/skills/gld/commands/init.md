# INIT

**One-time bootstrap + onboarding.** Sets up Guild's harness in the current repo, founds the role organization (the Guild), and drafts standards. Goal: build the environment where Guild works best. Growth is `evolve` (later); structural upgrades are `update` (later). `init` is NOT a growth path — re-running reports "already initialized."

`$1` = language for interviews/standards/labels display: `ko`/`korean`/`한국어` → Korean, `ja`/`japanese`/`日本語` → Japanese, `en`/`english`/empty → English (default). This is stored in `config.json` `language`.

> **Bash**: simple calls only (`<<SKILL_DIR>>/commands/atoms/_bash_rules.md`). Codebase discovery via Grep/Glob/Read. All comment/file bodies via the Write tool.

---

## Output conventions (apply to EVERY generated file)

These govern every file init writes — role agents, standards, CLAUDE.md, config. **Check all four before writing each file.**

1. **Language = config `language` (`$1`).** Every human-readable string — prose, headings, frontmatter `description`, list items, table cells — MUST be in the target language. The templates are written in **Korean as the reference**:
   - `ko` → use the template's language as-is (just fill placeholders).
   - `ja` / `en` → **translate all human-readable text** (headings, prose, frontmatter `description`) into that language.
   - Keep **unchanged** regardless of language: frontmatter keys (`name`, `model`), YAML/JSON structure, markers (`<!-- guild:* -->`, `<!-- guild:start -->`/`<!-- guild:end -->`, and the persona pair `<!-- guild:persona:start -->`/`<!-- guild:persona:end -->` plus `<!-- guild:persona:habits -->`), file paths, and commands/code.
   - **CLAUDE.md is included in this rule** — it must be in the config language, never English-by-default.
2. **No raw placeholders.** Never leave a literal `{{TOKEN}}` in a generated file. Fill it from scans/interview; if genuinely unknown, replace with an explicit localized note — e.g. `(미정 — 추후 확정)` (ko) / `(TBD)` (en). **Before writing each file, scan the rendered text for `{{` / `}}` and resolve any remaining.**
3. **Strip authoring hints.** Remove all template instruction scaffolding from the final file: guidance HTML comments (`<!-- init: … -->`, `<!-- 이 프로젝트가 … -->`) and `←`-style inline notes. Keep only real content markers (`guild:*`, `guild:start`/`end`, `guild:persona:start`/`end`/`habits`).
4. **Well-formed Markdown.** Structure enumerations as short bullets or **nested sub-bullets** (`  - `) — do NOT cram a long parenthetical list (e.g. "화면(a, b, c … 등 20개)") into one run-on bullet. One idea per line. Headings stay clean and localized (no bracketed English tags like `[PROJECT SPECIALIZATION]` in a Korean file).

---

## P0 — Preflight

1. Check for an existing install (its own Bash call):
   ```bash
   ls .claude/guild/config.json
   ```
2. **If it exists** → Guild is already initialized. Report: "Guild is already initialized in this repo. Use `/gld update` to adopt central improvements, or edit `.claude/guild/config.json` / `docs/standards/` directly." **Stop.** (Do not re-scan or overwrite.)
3. **If absent** → proceed to P1.
4. Verify this is a GitHub repo (needed for the dev flow's state model):
   ```bash
   gh repo view --json nameWithOwner -q .nameWithOwner
   ```
   Observe the literal `<owner>/<repo>`. If it fails → warn that Guild's development flow requires a GitHub repo; ask whether to continue with harness-only setup (agents + standards, no labels). Default: continue and skip label creation (P2 step 7).

---

## P1 — Repo analysis (parallel scans)

Spawn the six `scan_repo.md` scans **in parallel** (one Agent tool call each, in a single message). Each is Haiku-tier, read-only, and returns a compact `>>> RESULT <<<` JSON summary.

For each scan, spawn with the Agent tool:
- `subagent_type`: `general-purpose`
- `model`: `haiku` for scans 1–5 (mechanical) · **`sonnet` for scan 6 hotspot** (analytical — it ranks frequencies across many commits by reading, since pipes are forbidden)
- `description`: `<name>-scan`
- `prompt`:
  > Read `<<SKILL_DIR>>/commands/atoms/scan_repo.md` and execute **Section <N> — <name>-scan** only. Return exactly one `>>> RESULT <<<` line followed by the findings JSON.

The six: (1) stack, (2) command, (3) convention, (4) structure, (5) existing, (6) **hotspot** (git-history bug/churn/co-change — the evidence-driven answer to "what's fragile?", so the interview never has to ask it).

Collect the six findings objects. These feed P1.5 and P2. Feed hotspot findings into every role's "주의(핫스팟·함정)" section and the P3.5 readiness audit. If a scan returns partial/null findings, proceed — init must not block on incomplete analysis (baseline, not exhaustive).

---

## P1.5 — Short interview

**Principle (evidence-first, grow-later)**: **detect from evidence; ask only what evidence genuinely cannot reveal; let `evolve` grow the rest.** Do NOT pose blank-page essay questions ("what architecture rules aren't in the code?", "where are the fragile areas?", "what's your testing philosophy?") — those ask the user to do the agent's introspection work and are answered by evidence anyway (hotspots ← hotspot-scan, conventions ← convention-scan, coverage ← command/config). Rules and intent that stay hidden are **not** extracted by interrogation at init; they surface later when an agent violates them → the user corrects → `evolve` learns them. Day-1 agents are intentionally rough. Use `AskUserQuestion` in the `$1` language.

**Ask only these (genuinely un-inferable — the charter):**
1. **Domain / what is this?** (e.g. "Flutter Japanese-learning app") — seeds `{{DOMAIN}}`, `{{PROJECT_NAME}}`.
2. **Mission / vision** — why it exists, success state → charter.
3. **Values & priorities** — the principles that win at a fork (e.g. "user-data safety > feature speed", "simplicity > cleverness") → charter. Key material for role specialization + judgment alignment.
4. **(optional) Non-goals** — what it deliberately won't do.

**One optional anchored catch-all (not an essay):** after showing a one-line summary of what the scans detected, offer a single skippable prompt — *"코드·git 이력으로 못 잡은, 에이전트가 꼭 알아야 할 규칙/주의가 있나요? (없으면 건너뛰세요 — evolve가 사용하면서 채웁니다)"*. It is anchored (they react to detected facts, not a blank page) and explicitly optional. Do NOT push; skipping is the expected default.

If the user skips any field, fill it with a scan-derived best guess and mark it as a draft to confirm later (never leave a raw `{{TOKEN}}` per Output convention 2). Do not block. What isn't captured now is `evolve`'s job, not init's.

---

## P2 — Generate (additive; existing files merged, never clobbered)

Create the harness. **Track every file created/merged** for the P4 summary and partial-failure repair.

### 0b. Ensure the harness will not break the repo's own linters (DETERMINISTIC, do this with step 0)

Guild writes files **into the user's repo** — `gate_precommit.py`, 16 agent definitions, the
`CLAUDE.md` block, `docs/standards/*` — and those files then fall under whatever linting the repo
already runs on commit. Guild does not control that tooling, and a Guild-authored file that trips
it **blocks the human's commits**, which is a far worse first impression than a missing feature.

Observed: a Flutter repo ran `cspell` over staged files with no `.claude` exclusion. Committing the
harness produced 22 unknown-word errors from `gate_precommit.py` alone — `kubeconfig`, `tfvars`,
`pgpass`, `fdescribe`, `xoxe` and friends are **secret and test-skip pattern literals**, so they
cannot be spelled differently. Worse, that repo ran its hooks with `parallel: true`, so the spell
failure killed the in-flight `flutter analyze` too and the commit died with `signal: killed` — a
failure whose surface cause looked nothing like its actual cause. That same repo *already*
excluded `.claude/**` from its markdown linter, so the pattern was established; only the spell
checker had been missed.

1. Detect linters that would see the harness — read the repo root for the configs the stack scan
   already found (`.cspell.json` / `cspell.json` · `.markdownlint*` / `.remarkrc*` · `.flake8` /
   `ruff.toml` / `setup.cfg` · `.eslintrc*`) plus any hook-runner config (`lefthook.yml`,
   `.husky/`, `.pre-commit-config.yaml`) that invokes them.
2. For each, check whether Guild-managed paths are already out of scope (an `ignorePaths`,
   `exclude`, or glob that covers `.claude/**`).
3. Where they are not, **propose the exclusion and confirm before editing** (INV1 — this is the
   human's tooling). Additive only: append `.claude/**` to the existing ignore list, never rewrite
   it. Prefer excluding the Guild-managed subtree over adding words to a dictionary — the word
   list would need extending on every plugin update, the path exclusion holds.
4. Record what was reconciled (or declined) for the P4 summary. If the human declines, say plainly
   that their next commit may fail on Guild-authored files and how to undo it.

### 0. Ensure the harness will be committable (`.gitignore` reconciliation — DETERMINISTIC, do this FIRST)
Guild's harness under `.claude/` (agents, guild state, settings.json) is **meant to be committed**. Many repos have a root `.gitignore` that ignores `.claude/` wholesale (e.g. `.claude/*` with only `!.claude/skills/`), which would make the harness **invisible to git / un-committable** — it looks like "the files weren't created" even though they exist on disk. Fix this **deterministically here** — do NOT leave it to the probabilistic P3.5 readiness audit.

1. Check whether the harness paths would be git-ignored (each its own Bash call):
   ```bash
   git check-ignore .claude/agents .claude/guild .claude/settings.json
   ```
   (Any path echoed back = it is ignored. A nonexistent path doesn't error — `git check-ignore` just exits 1 with no output for it, identical to a real path that isn't ignored; verified empirically. Either way, no output for a given path = proceed to inspect `.gitignore` for it as "not ignored / will be created under `.claude/`.")
2. If any is ignored, read the root `.gitignore` and **append negation exceptions** (Edit tool, additive — preserve everything else), after the line that ignores `.claude`:
   ```
   !.claude/agents/
   !.claude/guild/
   !.claude/settings.json
   ```
   - **Do NOT** add `!.claude/settings.local.json` (personal, stays ignored) or `!.claude/guild/memory/` (episodic memory stays ignored — the nested `.claude/guild/.gitignore` re-ignores `memory/`, which still works under the parent negation).
   - If there is no `.gitignore`, or `.claude` is not ignored, do nothing.
3. Re-verify with `git check-ignore .claude/agents/`; it should now report nothing (not ignored). Record the change for the P4 summary.

(INV4: this is an additive edit to `.gitignore`; existing rules are preserved.)

### 1. Guild state skeleton
**Resolve the installed plugin version first** (its own Read call — do NOT hardcode a version string): Read `<<SKILL_DIR>>/../../.claude-plugin/plugin.json` and take its `version` field. Use that literal value for `config.json`'s `version` below. (A hardcoded literal here goes stale the moment the plugin ships a new version — every fresh `init` would then falsely report itself as behind via `/gld update --check`.)

Create via Write tool:
- `.claude/guild/config.json` — the M1 config (see schema below).
- `.claude/guild/knowledge/` — the ⑥ semantic-memory **baseline** (`<<SKILL_DIR>>/commands/atoms/_knowledge.md` format), seeded from the P1 scans — **not** a blank header:
  - `index.md` — a finite pointer map keyed by path/area (one line per seeded slice → its `facts/` file + a one-line hook).
  - `facts/<area>.md` — seed a **solid baseline** (not exhaustive): the top bug-**hotspot** files (with approx `fix:` frequency), the strongest **co-change** groups (X↔Y), and the main **layer/coupling** boundaries from structure-scan. Each fact evidence-anchored to git history, provenance `init-scan`. **Reuse the same scan findings** that fill the agent specialization's hotspot line (step 2) so ③ and ⑥ agree. `evolve` grows the rest.
- `.claude/guild/evolution-log.md` — ledger header (used by evolve later).
- `.claude/guild/gates/` — the **강제층 (enforcement layer, M3 minimal set)**:
  - `scripts/gate_precommit.py` — **copy** the bundled gate verbatim from `<<SKILL_DIR>>/gates/gate_precommit.py` (Read it, Write it to the repo path). It blocks a commit carrying a **secret** (keystore/.p12/.jks/.pem/.key/serviceAccount/.env/key material — public identifiers like `google-services.json` and `.env.example` excluded) or **weakening verification** (INV2 — deleted test file / net-removed assertions / added skip·focus directives). Off-switch = config `gates.enabled`. It runs in **three modes** (step 6 installs the git hook; step 5 wires the two settings hooks):
    - `--git-hook` → **the authoritative layer.** Only here is the index final, so this is the only layer that sees a compound `create-and-commit` in one Bash call.
    - no args → `PreToolUse(Bash)` **early warning**, so the agent gets a specific reason before spending a turn. It self-filters to commits via `is_git_commit()` (Claude Code's hook-level `if` matching is documented as best-effort, too weak to gate a security check on) and scopes its scan to what the command being run will actually commit.
    - `--guard-config` → `PreToolUse(Edit|Write|MultiEdit)`. The commit gate only ever sees Bash, so its own off-switch, rule files and `dismissed.md` are editable with no hook firing. This mode does **not** block (`/gld config --gates=off` is legitimate) — it returns `ask`, so disabling the gate is a human decision on the record rather than a side effect.
  - `rules/secrets.md` + `rules/verification.md` — one-line rule statements, `status: confirmed` (universal + non-hallucinated → they **block**).
  - `rules/boundaries.md` — **structure/boundary rules, `status: draft` (= WARN only, never blocks until the human confirms — INV6)**. Seed 0–2 `- forbid: <layer-glob> imports <path-substr>` rules from the structure-scan's layer boundaries (e.g. `- forbid: lib/ui/** imports lib/db/`); if the layers are unclear, write the `status: draft` header + a commented example + a note that `evolve`/`audit` grow it. Draft rules warn; confirming a rule (`status: confirmed`) promotes it to a block.
  - `dismissed.md` — accepted-risk registry (header only; `- <path/pattern> — <reason>` downgrades that item to a warning).
  - `findings.json` — `{ "open": [] }` (the gate writes open violations here).
- `.claude/guild/overlay/.gitkeep` — flow-policy override surface (empty; `/gld contribute` upstreams diffs here).
- `.claude/guild/.gitignore` — containing `memory/` (episodic memory is gitignored), **`.gld-sprint-*.window`** and **`.gld-sprint-*.board`** (per-run sidecar config: a sprint that has not completed keeps them for days, and the parent `!.claude/guild/` negation would otherwise show them as untracked and let `git add .` commit a machine-local window into the repo — after which `cleanup`'s `rm -f` deletes a TRACKED file; 04-sprint-window.md §6.5 INV3), and `gates/scripts/local/__pycache__/` (a repo-local gate extension is imported at commit time; the gate sets `sys.dont_write_bytecode` so none should appear, but a repo whose own `.gitignore` does not cover `__pycache__` would otherwise commit any that slipped through — Guild owns this file, so it should not depend on the repo's).
- `.claude/guild/memory/.gitkeep`.

**config.json (M1 subset):**
```json
{
  "version": "<the plugin.json version resolved above — e.g. 0.40.0, NOT a literal copied from this doc>",
  "language": "<lang from $1>",
  "roles": ["leader", "tech-lead", "developer", "tester", "product-owner", "qa", "designer", "infra", "dba", "security", "performance", "i18n", "analytics", "tech-writer", "release-manager", "support-triage"],
  "commands": { "test": "<simple cmd>", "lint": ["<step1>", "<step2>"], "typecheck": null, "build": null, "e2e": "<simple cmd or null>" },
  "automation": { "evolve_nudge": true },
  "gates": { "enabled": true },
  "sprint": { "capacity": null, "max_stack_depth": 3, "history": [], "board": null,
              "window": null }
}
```
- `commands.*` values are the **normalized, simple-bash-safe** forms from command-scan (see `scan_repo.md` Section 2): each is either a single simple command string, or an **array** of simple commands run in sequence. They MUST NOT contain `$(...)`, `&&`, `|`, `;`, or redirections — Guild runs them one per Bash call. (e.g. `flutter test --fail-fast --concurrency=$(nproc --all)` → store `"flutter test --fail-fast"`; `flutter analyze && npx remark . --quiet --frail` → store `["flutter analyze", "npx remark . --quiet --frail"]`.) A missing category → `null`.
- `commands.e2e` records the detected integration/E2E command (e.g. `flutter test integration_test`). **M1 detects and records it but does NOT auto-run E2E** (test stage runs unit/existing tests only; E2E auto-run is a later milestone). Recording it here keeps the info from being lost and lets a human run it manually.
- `roles` lists the **full installed roster** (16) — the spine roles plus every participation/gate specialist. It records who is *available*; the leader decides who *participates* per task (`_handoff.md` Section G). Keep it in sync with the agents actually written in step 2.
- `gates.enabled` (M3) is the **off-switch** for the enforcement layer — `true` = the pre-commit gate blocks (secret / verification-weakening); `false` = advisory only (off-switch). `automation.evolve_nudge` (default `true`) is the **off-switch for the review-stage evolve nudge** (`review.md` Step 5) — `false` silences it entirely; toggle via `/gld config --evolve-nudge=<on|off>`.

### 2. Role agents (the Guild's full roster — 16)
Install the **entire roster** so the leader can assemble any of them per task ("전 역할 활성화; init이 로스터 전체 설치, 리더가 태스크별 조건부 참여"). The roster has three participation kinds (documented in `_handoff.md` Section G):
- **Spine roles (always in the flow)**: `leader`, `tech-lead`, `developer`, `tester`, `qa`.
- **Participation roles (leader convenes conditionally)**: `product-owner`, `designer`, `infra`, `dba`, `security`, `performance`, `i18n`, `analytics`, `tech-writer`, `release-manager`, `support-triage`.
- **Gate roles (conditional review checks)**: `designer` (UI/UX review), `security` (security review), `infra` (CI/CD·deploy·env·IaC review — gate-only, never authors its own diff) — same files as their participation entry.

For **each of the 16** roles (`leader`, `tech-lead`, `developer`, `tester`, `product-owner`, `qa`, `designer`, `infra`, `dba`, `security`, `performance`, `i18n`, `analytics`, `tech-writer`, `release-manager`, `support-triage`):
- Read `<<SKILL_DIR>>/templates/agents/<role>.md`.
- Fill the `{{...}}` placeholders from the P1 scans + P1.5 interview:
  - **Read each template's own tokens — do not work from a list held here.** Most placeholders are now **role-scoped and self-describing**: `tech-lead.md` asks for `{{ARCHITECTURE_BOUNDARIES_AND_KEY_COUPLING}}` and `{{TECH_LEAD_TRAPS_AND_HOTSPOTS}}`, `designer.md` for `{{DESIGN_SYSTEM_AND_THEME_CONVENTIONS}}`, and so on — the token says what it wants, so fill it from that meaning plus the Korean bullet label next to it. ⚠ They used to be two shared tokens, `{{CONVENTIONS}}` (in 15 of 16 files) and `{{BOUNDARIES}}` (in 7), carrying about a dozen unrelated meanings between them — and *inverting* between files: in `tech-lead` `{{BOUNDARIES}}` meant architectural boundaries while `{{CONVENTIONS}}` meant hotspots, but in `performance` `{{BOUNDARIES}}` meant hotspots. Filling them correctly required inferring the intended meaning from surrounding prose on every file. Do not reintroduce a shared token for role-specific content.
  - Genuinely shared tokens, unchanged: `{{PROJECT_NAME}}` (all 16), `{{DOMAIN}}`, `{{STACK}}`, `{{VALUES}}`, `{{ARCHITECTURE}}`, `{{LEADER_NOTES}}`, `{{TEST_CMD}}`, `{{LINT_CMD}}`, `{{TYPECHECK_CMD}}`, `{{TEST_FRAMEWORK}}`, `{{TEST_LOCATION}}`, `{{E2E_SETUP}}`. (`{{E2E_CMD}}`/`{{BUILD_CMD}}` appear only in `verification.md`/`CLAUDE.md.tmpl`, not in any agent template.) ⚠ **This covers the 16 agent templates only, NOT the 5 standards templates** (step 3 below) — those introduce their own, separate placeholder set (`{{MISSION}}`, `{{VISION}}`, `{{VALUES}}`, `{{GOALS}}`, `{{NON_GOALS}}`, `{{CODE_STYLE}}`, `{{COMMIT_STYLE}}`, `{{TEST_CONVENTION}}`, `{{PR_CONVENTION}}`, `{{MUST_PASS}}`, `{{QUALITY_EXPECTATIONS}}`, `{{TRADEOFFS}}`, `{{VERIFY_RULES}}`, `{{DOD}}`, `{{DIRECTORY_MAP}}`, `{{SEAMS}}`, `{{PITFALLS}}`), filled per step 3's own generic "content placeholders from scans + interview" instruction — do not assume this list is exhaustive across every templated file init writes.
  - `{{TEST_CMD}}`/`{{LINT_CMD}}`/`{{TYPECHECK_CMD}}` use the **normalized** commands from config (no `$(...)`/`&&`; render an array as a comma- or slash-separated list of the simple steps).
  - **Every `{{*_HOTSPOTS}}` token MUST be filled from the hotspot-scan (scan 6) findings** — list the concrete top bug-hotspot files/areas (with their approximate `fix:` frequency) and any strong co-change groups. This is evidence from git history, not a guess — do NOT reduce such a line to "규칙 미정". The `_HOTSPOTS` suffix is the mechanical handle for this rule and is **exactly co-extensive** with the five roles it applies to, so you can check your own work in one call: `grep -l '_HOTSPOTS}}' .claude/agents/*.md` must come back empty once they are filled, and the templates carrying them are precisely `tech-lead`/`developer`/`tester`/`qa`/`performance`. (dba's data-hotspot slot is deliberately *not* named `_HOTSPOTS` — this rule does not cover it, and the suffix must keep matching the rule exactly.) (Hidden *rules/intent* may be "(미정 — evolve가 채움)", but **hotspots are known and must appear.**) Example: "핫스팟: `db_helper.dart`(fix 최다)·`sync_data_controller`·`iap_controller`·`tts_controller` — 변경 시 회귀 주의".
  - **Carry the three persona markers through verbatim** — `<!-- guild:persona:start -->`,
    `<!-- guild:persona:end -->`, `<!-- guild:persona:habits -->`. They are never translated and
    never dropped: `update` replaces exactly the region between the first two, and the migration
    path anchors on them. A template whose markers did not survive is a persona `update` can
    never refresh.
  - **The text BETWEEN `persona:start` and `persona:end` is localized, not rewritten.** Translate
    it for `ja`/`en`; do not reword, reorder or trim it for `ko`. That region is central-owned —
    `update` overwrites it wholesale, so any local improvement made here is lost on the next run.
    Put repo-specific content in 프로젝트 특화 (below the end marker) instead.
  - **`## 역할 습관` is localized like any other heading, but its marker stays.** Fill the section
    with the single "(아직 없음 …)" line from the template, localized; `/gld evolve` grows it from
    there.
  - Fill the specialization section concretely — this is what makes the role *this repo's* senior, not a generic shell. Apply the **Output conventions** above: no raw `{{...}}` (use a localized "(미정)" note if unknown), structure enumerations as nested sub-bullets, and localize the heading (the template's `프로젝트 특화` heading stays localized — never emit `[PROJECT SPECIALIZATION]`).
  - **Not-applicable specialists**: a participation role the repo genuinely never needs (e.g. `dba`/`i18n`/`designer` for a single-language headless library) still gets **installed**, but its 프로젝트 특화 section is filled with a localized "(해당 없음 — 이 레포에 <해당 영역> 없음)" per that template's authoring hint. Installing it is cheap and lets `evolve` promote it later; the leader simply won't convene it. Do NOT skip creating the file.
- Write the result to `.claude/agents/<role>.md`. **If a file of that name already exists, do not touch it — report it and move on.** `init` never merges an agent file; that is `update`'s job (it replaces the persona marker region and refreshes the central frontmatter keys, leaving everything else alone). ⚠ This line used to say "see Merge rules below" and there was no such section.

Static copy + specialization only — no HR (hire/retire/promote) in M1. The roster is installed as-is; growing/pruning it is `evolve`.

### 3. Standards drafts
For each of `charter`, `architecture`, `conventions`, `quality-bar`, `verification`:
- Read `<<SKILL_DIR>>/templates/standards/<name>.md`.
- Fill `{{DATE}}` (today) and the content placeholders from scans + interview. Keep `status: draft`.
- Write to `docs/standards/<name>.md` (do not overwrite an existing file — if present, skip and note it in the summary).
Also create `docs/adr/0000-template.md` (a minimal ADR skeleton) and ensure `docs/specs/` exists (`.gitkeep`).

### 4. CLAUDE.md (merge — preserve existing)
- Read `<<SKILL_DIR>>/templates/CLAUDE.md.tmpl`; fill `{{TEST_CMD}}` etc. (normalized commands). **Render the block in the config `language`** per Output convention 1 — the template is Korean; translate to `ja`/`en` if needed. Do NOT leave it English when `language` is `ko`.
- **If `CLAUDE.md` does not exist** → Write it with the filled template (the `<!-- guild:start -->`…`<!-- guild:end -->` block).
- **If it exists**:
  - If it already contains a `<!-- guild:start -->` marker → replace only the content between `<!-- guild:start -->` and `<!-- guild:end -->` (Edit tool), preserving everything else.
  - Else → append the filled Guild block (with markers) to the end, preserving all existing content.

### 5. settings.json (key-level merge — preserve existing)
- Read `<<SKILL_DIR>>/templates/settings.json.tmpl`. **It contains no placeholders and is already valid JSON as shipped** — its `permissions.allow` lists only the four commands Guild itself always needs (`gh`, `git`, `jq`, `ls`).
- **Append one `"Bash(<bin>:*)"` element to `permissions.allow` per distinct binary this repo's verification commands use.** Collect them from config `commands.test`/`lint`/`typecheck`/`build`: each value is either a single command string or a normalized **array** of steps (Section 2's rule — e.g. `["flutter analyze", "npx remark . --quiet --frail"]` uses **two** distinct binaries, `flutter` and `npx`). Take the first word of each step, dedupe against what is already listed, and add the rest. Missing one only costs a permission prompt on every lint/test run — not a broken file.
  - ⚠ Earlier versions of this template carried a `{{ADDITIONAL_BIN_ENTRIES}}` slot that the model had to fill with a **raw JSON fragment including its own leading comma** (`,\n      "Bash(npx:*)"`). Getting that wrong produced an unparseable `settings.json`, which silently took the gate hooks down with it — the whole enforcement layer, lost to a comma. Adding array elements to an already-valid document has no such failure mode. Do not reintroduce a fragment placeholder here.
- The template also wires the two **`PreToolUse` gate hooks** (step 6 covers the third, authoritative wiring): `Bash` → `gate_precommit.py` early warning (fires on every Bash call; the script's own `is_git_commit()` decides whether it is a commit), and `Edit|Write|MultiEdit` → `--guard-config` (asks before the gate's own off-switch or rule files are edited). Both carry a `timeout`.
- **If `.claude/settings.json` does not exist** → Write the filled template.
- **If it exists** → JSON has no comment markers, so merge by key: read the existing JSON, union `permissions.allow` and `permissions.ask` (dedupe), and **union both Guild gate hook entries into `hooks.PreToolUse`** — the `{matcher:"Bash", … gate_precommit.py}` early-warning entry and the `{matcher:"Edit|Write|MultiEdit", … --guard-config}` control-file guard — appending each only if an equivalent is not already present (dedupe by command string, which includes the mode flag); **preserve all other existing hooks and keys**. Write the merged JSON back (2-space indent).
- The template's `permissions.ask` list makes two invariants mechanical rather than advisory: `gh pr merge` (INV1 — a human, never an automated run, merges) and the destructive `git push --force` / `reset --hard` / `clean` family (INV3 — everything reversible). Claude Code evaluates `deny > ask > allow`, so these override the broad `Bash(git:*)` / `Bash(gh:*)` allowances above them.

### 6. git pre-commit hook (the authoritative enforcement layer)

`PreToolUse` fires *before* a command runs, so a compound `echo <secret> > f && git add f && git commit -m x` commits content that does not exist yet at hook time — no `git diff`/`git status` can see it. **Verified: that shape, and `sed -i '' 's/assert//g' t_test.py && git commit -am x`, both bypassed the pre-`0.41` gate entirely.** The git hook closes it because git runs it with the index final. Install it here:

1. **Resolve the hook path — do NOT hardcode `.git/hooks/`** (its own Bash call):
   ```bash
   git rev-parse --git-path hooks/pre-commit
   ```
   Hold the literal it prints and use it for every step below. In a **git worktree** `.git` is a *file* (a `gitdir:` pointer), not a directory, so a literal `.git/hooks/…` path does not exist there and every step would silently target nothing — `batch.md` hit exactly this with `info/exclude`. `--git-path` resolves correctly from a normal checkout and a worktree alike (worktrees share the main checkout's hooks, which is what we want: one gate for all of them).
2. **Ask who owns the existing hook** — this decides everything below. Read the resolved path (absent → `none`), then pipe its text to the gate's detector. Two calls: Read the file with the Read tool, Write its text to a temp file, then (its own Bash call, stdin = that file):
   ```bash
   python3 .claude/guild/gates/scripts/gate_precommit.py --detect-hook-manager
   ```
   It prints one word: `guild` · `none` · or a manager name (`lefthook` / `husky` / `pre-commit` / `overcommit` / `simple-git-hooks`).

   - **`guild`** → already ours; overwrite in place at step 3.
   - **`none`** (absent, or a hand-written hook) → if a hand-written hook is present, move it aside so the shim can chain to it (its own Bash call, substituting the literal resolved path):
     ```bash
     mv <resolved-path> <resolved-path>.local
     ```
     ⚠ Use a plain `mv`, **not** `git mv`: hook files live inside `.git/` and are therefore not version-controlled, so `git mv` always fails here with `fatal: not under version control` — verified. Note the rename for the P4 summary; the repo's own hook still runs **first**, before Guild's checks. Then continue to step 3.
   - **A manager name** → **do NOT take the hook file over. Skip steps 3–4 entirely** and register the gate as one of that manager's commands instead (step 2b).

### 2b. Managed repo — register, don't take over

`lefthook`, `husky`, `pre-commit` and friends **generate** `.git/hooks/pre-commit` and rewrite it on their next `install`. A Guild shim placed there survives exactly until then, and afterwards the enforcement layer is gone **with no signal** — the worst shape of failure this gate can have. Registering as one of the manager's commands is strictly better: the manager keeps owning the hook file as it expects, and because its config **is committed**, the gate then travels with a clone — which the `.git/hooks/` path never does, so the fresh-clone caveat below does not apply on this path.

Editing the repo's hook config is a change to the human's own tooling, so **show the exact diff and get confirmation** (INV1) before writing. The command to register, in every manager, is:

```
python3 .claude/guild/gates/scripts/gate_precommit.py --git-hook
```

A non-zero exit must fail the commit — that is the default in every manager below; do not add flags that swallow it.

- **lefthook** → add a command under `pre-commit.commands` in `lefthook.yml` (or `.lefthook.yml`). Additive: preserve every existing command and the file's `parallel:` setting. The gate is read-only, so it is safe under `parallel: true`.
  ```yaml
  pre-commit:
    commands:
      guild-gate:
        run: python3 .claude/guild/gates/scripts/gate_precommit.py --git-hook
  ```
- **husky** → append the command as a new line to `.husky/pre-commit`, preserving what is there.
- **pre-commit** (the Python framework) → add a `repo: local` hook to `.pre-commit-config.yaml` with `language: system` and `always_run: true` (it must run even when no matching file changed — the gate scans the whole staged set).
- **simple-git-hooks / overcommit / anything else** → do not guess the schema. Report the manager, print the command above, and ask the human to add it; record it in P4 as a readiness gap until they confirm.

After registering, still run step 5's `core.hooksPath` check — a manager may set it, and that is fine here (the manager's own hook lives there and now carries Guild's command).
3. **Copy the bundled shim verbatim**: Read `<<SKILL_DIR>>/gates/pre-commit.sh`, Write it to the resolved path.
4. **Make it executable** (its own Bash call, substituting the literal path — git **silently ignores** a non-executable hook, which leaves the enforcement layer installed-but-inert and indistinguishable from installed-and-working):
   ```bash
   chmod +x <resolved-path>
   ```
5. **Verify it is live** (its own Bash call); the output must be empty:
   ```bash
   git config --get core.hooksPath
   ```
   A non-empty value means the repo redirects hooks elsewhere (husky and similar do this) — Guild's hook will **never run**, wherever it was installed. Do not fight it: report this in P4 as a readiness gap ("`core.hooksPath` is set to `<value>`; copy the Guild hook there, or chain to it from the hook already there, to enable the commit gate"), and note that until then only the advisory `PreToolUse` layer is active.

⚠ **On the step-3 path only (`none`/`guild`), `.git/hooks/` is not tracked by git**, so that install is per-clone: a fresh clone has the harness files but no hook until someone runs `/gld update`. Say so in P4. **On the 2b managed path this does not apply** — the manager's config is committed, so the gate travels with the clone; say *that* in P4 instead, rather than warning about a limitation this repo does not have.

⚠ Either way, `git commit --no-verify` skips it, as it skips every git hook — Guild's gate raises the cost of a mistake, it is not a boundary against a determined bypass.

### 7. GitHub labels (skip if P0 found no GitHub repo)
Create the eleven `guild:*` labels. Run each as its own Bash call; if any fails, report which and continue (labels are not transactional in M1 — they are idempotent with `--force`):
```bash
gh label create "guild:analyze" --color "1d76db" --description "Guild: Analyze stage" --force
gh label create "guild:design" --color "0e8a16" --description "Guild: Design stage" --force
gh label create "guild:execute" --color "e4e669" --description "Guild: Execute stage" --force
gh label create "guild:test" --color "f9d0c4" --description "Guild: Test stage (automated)" --force
gh label create "guild:qa" --color "fbca9e" --description "Guild: QA stage (holistic)" --force
gh label create "guild:done" --color "0075ca" --description "Guild: Done" --force
gh label create "guild:child" --color "d4c5f9" --description "Guild: Child Issue" --force
gh label create "guild:children" --color "c5def5" --description "Guild: Split parent — children being driven" --force
gh label create "guild:harness" --color "5319e7" --description "Guild: Harness readiness gap (from readiness audit)" --force
gh label create "guild:needs-human" --color "b60205" --description "Guild: Paused — needs a human decision (unattended run)" --force
gh label create "guild:sprint" --color "0052cc" --description "Guild: Sprint tracking Issue" --force
```
(`guild:harness` labels the remediation issues that P3.5's readiness audit proposes. `guild:needs-human` marks an Issue an unattended `/gld batch`·`sprint` run paused at a high-stakes gate — the human resolves it, then re-runs `/gld dev`/`resume`.)

---

## P3 — Confirm pass (optional, skippable)

Offer to confirm the drafted standards now (draft→confirm→enforce):
- Show the user each `docs/standards/*.md` draft summary.
- For each, ask: keep as `draft`, or flip to `confirmed`? (Skippable — "confirm later with a manual edit or a future audit.")
- On confirm: change the file's frontmatter `status: draft` → `status: confirmed`.
- Confirming a *standards doc* (`charter.md`, `architecture.md`, etc.) never itself toggles any gate — these are advisory, read by roles as judgment context, not mechanically enforced. (The gates that *do* mechanically block — `gate_precommit.py`'s secret/verification checks — are wired separately in P2 steps 1/5/6 above and are already `status: confirmed` from day one, independent of this pass.) So this step only sets intent — but it is the honest place to lock standards while the human is in the loop.

Default if the user skips: everything stays `draft`.

---

## P3.5 — Harness readiness audit + remediation proposals

Run a **full readiness diagnostic** (the first run of what `/gld audit` will later repeat) so the user knows what the project is missing for `/gld` to work well, and can turn gaps into issues. Skippable, but on by default.

### 1. Diagnose (read-only)
Spawn the readiness atom as a sub-agent:
- `subagent_type`: `general-purpose`, `model`: `sonnet`, `description`: `readiness audit`
- `prompt`:
  > Read `<<SKILL_DIR>>/commands/atoms/audit_readiness.md` and execute it. Use the P1 scan findings for this repo: <inline the six findings summaries, incl. hotspot>. Return exactly one `>>> RESULT <<<` line with the findings JSON.

Parse the findings JSON. Groups: 검증 신호 · 정적 게이트 · CI · GitHub 워크플로 · 위생.

### 2. Report (always)
Render a readiness report grouped by category, each gap as `[SEVERITY] title — why(Guild에 필요한 이유) → remediation`. Show a summary count. Then **persist** it via the Write tool to `.claude/guild/readiness-report.md` (in the config `language`) so it is not lost and a future `/gld audit` can diff against it. Include a header noting the scan date and that hygiene checks are a **light heuristic**.

### 3. 위생 deep scan (opt-in)
If the hygiene group ran only the light heuristic, offer: "전용 시크릿 스캐너(gitleaks)로 정밀 검사할까요? (미설치 시 설치 동의를 받습니다)".
- On yes + not installed → ask explicit consent to install (system change), then install via the platform's package manager as its own simple Bash call (e.g. `brew install gitleaks`). If the user declines the install → skip deep scan, keep light findings.
- Run `gitleaks detect` (read-only, its own Bash call) and fold new findings into the report. **Never print secret values** — reference file/line only.

### 4. Remediation (opt-in, per gap — INV1)
For each **BLOCKER/MAJOR** gap (offer MINOR too, but default to skip), ask the user how to handle it. Offer only **safe, reversible** actions:
- **Create a tracking issue** (default): via the temp-file pattern, `gh issue create --body-file <path> --label guild:harness` (+ `type:refactor`/`type:chore` if those labels exist). Title = the gap; body = gap · why it helps Guild · acceptance criteria. **Dedup**: first search open issues for an existing `guild:harness` issue with the same gap `id` marker (`<!-- guild:harness:<id> -->`) — PATCH/skip if found. These issues are then developable with `/gld dev`.
- **Safe local fix** where applicable: e.g. gitignore gap → append the missing entries; committed-secret-file → add to `.gitignore` + `git rm --cached <file>` **(confirm first)**.
- **Guide-only for destructive/external actions** (committed/inline secrets): print the steps for git-history purge and key rotation — **NEVER auto-run** history rewrite (`git filter-branch`/filter-repo) or rotate keys. These are irreversible (INV3) / external. The tracking issue captures the follow-up.

Batch the questions where possible (one grouped prompt listing gaps → user picks which to file). If the user skips remediation entirely, the report on disk still records everything.

---

## P3.9 — Placeholder sweep (deterministic, before reporting success)

Output convention 2 says never to leave a literal `{{TOKEN}}` in a generated file, but nothing
verified it. A surviving `{{CONVENTIONS}}` in a role agent is not cosmetic: that agent is loaded
as a persona on every task it joins, and it teaches the model that the repo's conventions are the
literal string `{{CONVENTIONS}}`. Check, don't assume — one Bash call:

```bash
grep -rn "{{" .claude/agents docs/standards CLAUDE.md .claude/settings.json
```

- **No output** → clean; proceed to P4.
- **Any hit** → for each, fill it now from the P1 scans / P1.5 interview, or replace it with an
  explicit localized note (`(미정 — 추후 확정)` / `(TBD)`). Re-run the grep until it is empty.
  Report in P4 which files needed a second pass — a token that survived the first write is a
  signal about that template, worth a `/gld contribute` flag if it keeps happening.

Then confirm the persona skeleton survived the write — **only for the agent files this run
created**, not the whole directory (a pre-existing file without markers would otherwise trap
`init` forever). One Bash call:

```bash
python3 <<SKILL_DIR>>/commands/atoms/persona_migrate.py --mode check --anchor '<the project-specialization heading this run rendered>' --file <the agent files this run wrote>
```

⚠ **If that list is empty — every agent file already existed and this run wrote none — do not run
the command.** `--file` with no argument is a usage error (exit 64) on a healthy repo.

Every line must start with `ok:`; the script exits `3` if any is a `FAIL:`. **Not every FAIL is a
marker problem.** Do not re-derive the cases here — `update.md`'s rule 3b carries the full table
mapping every `FAIL:` string to its cause and its repair, and it is kept in step with the script.
Read the values against that table. The init-time shapes it covers that matter most:
`start at P, fence2=-, …` the closing YAML fence was lost · `anchor x0` **the localized
specialization heading was dropped or renamed, and the markers are fine** · `h1=-`/`h1 x0` the
translated H1 was lost · `anchor x2` the heading was written twice · `marker appears 0 time(s)`
a marker line was translated or deleted — fix that file before reporting success,
because `update` keys on exactly this shape and a persona without the pair is one `update`
can never refresh. ⚠ The headings are localized and the markers are not — which is exactly why
`--anchor` is passed rather than compiled in. The script **does** compare the first `## ` below the
end marker against the heading you name, and that comparison is the only check that catches a
mis-placed end marker. So a `FAIL: first heading below end is …` means one of **three** things: you
passed the wrong `--anchor`, the localized specialization heading itself was dropped or renamed,
or the markers did not survive localization. Check the argument first, then the heading, then the markers. ⚠ `--anchor` is **required here even for `ko`**: this check runs on
files `init` just localized, so pass the heading you actually rendered. Omitting it works by
accident in a `ko` repo and fails every file in any other language.

Also confirm the settings file actually parses (its own Bash call — a malformed `settings.json`
silently disables the gate hooks it carries):

```bash
python3 -m json.tool .claude/settings.json
```

Non-zero exit → fix it before reporting success; the harness is not installed until this parses.

---

## P4 — Summary

**Report what verification shows, never what was intended.** Each line below states that something exists on disk — so check it before writing it (P3.9 already confirmed the generated files carry no leftover placeholders and that `settings.json` parses; `git status` confirms the harness is visible to git). An install reported as complete when a step silently failed is worse than an obvious failure: the human then believes the enforcement layer is in place when it is not. If anything from the completeness set is missing, say which, and that init is **partial** — do not round up to success.

Report what was installed:
- Guild: 16 role agents at `.claude/agents/` — spine (leader, tech-lead, developer, tester, qa) + participation/gate specialists (product-owner, designer, infra, dba, security, performance, i18n, analytics, tech-writer, release-manager, support-triage). Note that the leader convenes the specialists **conditionally** per task (spine roles always run; specialists join by work-type/risk — see `_handoff.md` Section G).
- Standards: 5 drafts at `docs/standards/` (note which are `draft` vs `confirmed`).
- Harness: `CLAUDE.md` (created or merged), `.claude/settings.json` (created or merged), `.claude/guild/` state skeleton. Note whether `.gitignore` was reconciled (P2 step 0) so `.claude/` harness is committable — and confirm the harness is visible to git (`git status` shows it), since ignored files silently look "not created".
- ⑥ Knowledge baseline: `.claude/guild/knowledge/index.md` + `facts/` seeded from the scans (hotspots · co-change · coupling). Note the seeded slice count; `evolve` grows it from here.
- 강제층 게이트 (M3): `.claude/guild/gates/scripts/gate_precommit.py`, wired three ways — `.git/hooks/pre-commit` (**authoritative**), `PreToolUse(Bash)` (early warning), `PreToolUse(Edit|Write)` (control-file guard). Blocks committing secrets / weakening verification. Off-switch: config `gates.enabled` (or `/gld config`). **State the two honest limits**: `.git/hooks/` is not tracked, so a fresh clone needs `/gld update` to reinstall the hook; and `git commit --no-verify` skips it. If step 6 found a non-empty `core.hooksPath`, say that the authoritative layer is **not** active and what to do about it.
- Labels: 11 `guild:*` (analyze, design, execute, test, qa, done, child, children, harness, needs-human, sprint) (or "skipped — no GitHub repo").
- Readiness audit (P3.5): report at `.claude/guild/readiness-report.md` — summarize the gap counts (BLOCKER/MAJOR/MINOR) and list any `guild:harness` issues created.
- Next steps: "`/gld dev <issue>` to develop a GitHub Issue end-to-end (including any `guild:harness` remediation issues). `/gld status <issue>` to check progress. Day-1 agents are intentionally rough — they improve as you work (evolve, a later milestone)."

---

## Partial-failure repair (not a hard dead-end)

`init` is additive and idempotent per-file. If it is interrupted, re-running detects `.claude/guild/config.json` at P0 and reports "already initialized." To repair a partial install, the completeness set is everything P2 creates: `config.json` + 16 role agents (full roster) + 5 standards + `docs/adr/0000-template.md` + `docs/specs/.gitkeep` + CLAUDE.md guild block + settings.json allowlist **+ both PreToolUse gate hooks + an executable `.git/hooks/pre-commit`** + the `guild:*` labels created by P2 §7 (currently 11) + `knowledge/` baseline (index.md + facts/) + `gates/` (gate_precommit.py + rules + dismissed.md + findings.json) + `evolution-log.md` + `overlay/.gitkeep` + `.claude/guild/.gitignore` + `memory/.gitkeep`. Re-running does not auto-repair in M1 (P0 stops early) — instead, report any missing pieces from the completeness set in P4 so the user can address them, or delete `.claude/guild/config.json` to force a clean re-init.

## Hard rules (safety)
- **Additive only** (INV4): existing files are merged/preserved, never clobbered. This stays true of `init` without exception — it never rewrites an agent file it did not create. Marker-based merging of a persona's central region is `update`'s job, not this command's. CLAUDE.md via markers; settings.json via key union; existing `docs/standards/*` and `.claude/agents/*` are not overwritten.
- **Read-only scans** (P1) — no code changes during analysis.
- All Bash per `_bash_rules.md`; all file bodies via the Write/Edit tools.
