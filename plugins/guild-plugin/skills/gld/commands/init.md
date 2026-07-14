# INIT

**One-time bootstrap + onboarding.** Sets up Guild's harness in the current repo, founds the role organization (the Guild), and drafts standards. Goal: build the environment where Guild works best (plan §7). Growth is `evolve` (later); structural upgrades are `update` (later). `init` is NOT a growth path — re-running reports "already initialized."

`$1` = language for interviews/standards/labels display: `ko`/`korean`/`한국어` → Korean, `ja`/`japanese`/`日本語` → Japanese, `en`/`english`/empty → English (default). This is stored in `config.json` `language`.

> **Bash**: simple calls only (`<<SKILL_DIR>>/commands/atoms/_bash_rules.md`). Codebase discovery via Grep/Glob/Read. All comment/file bodies via the Write tool.

---

## Output conventions (apply to EVERY generated file)

These govern every file init writes — role agents, standards, CLAUDE.md, config. **Check all four before writing each file.**

1. **Language = config `language` (`$1`).** Every human-readable string — prose, headings, frontmatter `description`, list items, table cells — MUST be in the target language. The templates are written in **Korean as the reference**:
   - `ko` → use the template's language as-is (just fill placeholders).
   - `ja` / `en` → **translate all human-readable text** (headings, prose, frontmatter `description`) into that language.
   - Keep **unchanged** regardless of language: frontmatter keys (`name`, `model`), YAML/JSON structure, markers (`<!-- guild:* -->`, `<!-- guild:start -->`/`<!-- guild:end -->`), file paths, and commands/code.
   - **CLAUDE.md is included in this rule** — it must be in the config language, never English-by-default.
2. **No raw placeholders.** Never leave a literal `{{TOKEN}}` in a generated file. Fill it from scans/interview; if genuinely unknown, replace with an explicit localized note — e.g. `(미정 — 추후 확정)` (ko) / `(TBD)` (en). **Before writing each file, scan the rendered text for `{{` / `}}` and resolve any remaining.**
3. **Strip authoring hints.** Remove all template instruction scaffolding from the final file: guidance HTML comments (`<!-- init: … -->`, `<!-- 이 프로젝트가 … -->`) and `←`-style inline notes. Keep only real content markers (`guild:*`, `guild:start`/`end`).
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
   Observe the literal `<owner>/<repo>`. If it fails → warn that Guild's development flow requires a GitHub repo; ask whether to continue with harness-only setup (agents + standards, no labels). Default: continue and skip label creation (P2 step 6).

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

Collect the six findings objects. These feed P1.5 and P2. Feed hotspot findings into every role's "주의(핫스팟·함정)" section and the P3.5 readiness audit. If a scan returns partial/null findings, proceed — init must not block on incomplete analysis (plan §7: baseline, not exhaustive).

---

## P1.5 — Short interview

**Principle (evidence-first, grow-later)**: **detect from evidence; ask only what evidence genuinely cannot reveal; let `evolve` grow the rest.** Do NOT pose blank-page essay questions ("what architecture rules aren't in the code?", "where are the fragile areas?", "what's your testing philosophy?") — those ask the user to do the agent's introspection work and are answered by evidence anyway (hotspots ← hotspot-scan, conventions ← convention-scan, coverage ← command/config). Rules and intent that stay hidden are **not** extracted by interrogation at init; they surface later when an agent violates them → the user corrects → `evolve` learns them. Day-1 agents are intentionally rough (plan §7). Use `AskUserQuestion` in the `$1` language.

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

### 0. Ensure the harness will be committable (`.gitignore` reconciliation — DETERMINISTIC, do this FIRST)
Guild's harness under `.claude/` (agents, guild state, settings.json) is **meant to be committed** (plan §6). Many repos have a root `.gitignore` that ignores `.claude/` wholesale (e.g. `.claude/*` with only `!.claude/skills/`), which would make the harness **invisible to git / un-committable** — it looks like "the files weren't created" even though they exist on disk. Fix this **deterministically here** — do NOT leave it to the probabilistic P3.5 readiness audit.

1. Check whether the harness paths would be git-ignored (each its own Bash call):
   ```bash
   git check-ignore .claude/agents .claude/guild .claude/settings.json
   ```
   (Any path echoed back = it is ignored. If the tool errors because a path doesn't exist yet, treat as "will be created under .claude/" and proceed to inspect `.gitignore`.)
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
Create via Write tool:
- `.claude/guild/config.json` — the M1 config (see schema below).
- `.claude/guild/knowledge/` — the ⑥ semantic-memory **baseline** (`<<SKILL_DIR>>/commands/atoms/_knowledge.md` format), seeded from the P1 scans — **not** a blank header:
  - `index.md` — a finite pointer map keyed by path/area (one line per seeded slice → its `facts/` file + a one-line hook).
  - `facts/<area>.md` — seed a **solid baseline** (plan §7 — not exhaustive): the top bug-**hotspot** files (with approx `fix:` frequency), the strongest **co-change** groups (X↔Y), and the main **layer/coupling** boundaries from structure-scan. Each fact evidence-anchored to git history, provenance `init-scan`. **Reuse the same scan findings** that fill the agent specialization's hotspot line (step 2) so ③ and ⑥ agree. `evolve` grows the rest.
- `.claude/guild/evolution-log.md` — ledger header (used by evolve later).
- `.claude/guild/gates/` — the **강제층 (enforcement layer, M3 minimal set — plan §11/§14)**:
  - `scripts/gate_precommit.py` — **copy** the bundled gate verbatim from `<<SKILL_DIR>>/gates/gate_precommit.py` (Read it, Write it to the repo path). It is the `PreToolUse(Bash: git commit)` hook (wired in settings.json, step 5) that blocks a commit carrying a **secret** (keystore/.p12/.jks/.pem/serviceAccount/.env — public identifiers like `google-services.json` excluded) or **weakening verification** (INV2 — deleted test file / net-removed assertions / added skips). Off-switch = config `gates.enabled`.
  - `rules/secrets.md` + `rules/verification.md` — one-line rule statements, `status: confirmed` (universal + non-hallucinated → they **block**).
  - `rules/boundaries.md` — **structure/boundary rules, `status: draft` (= WARN only, never blocks until the human confirms — INV6/T3)**. Seed 0–2 `- forbid: <layer-glob> imports <path-substr>` rules from the structure-scan's layer boundaries (e.g. `- forbid: lib/ui/** imports lib/db/`); if the layers are unclear, write the `status: draft` header + a commented example + a note that `evolve`/`audit` grow it. Draft rules warn; confirming a rule (`status: confirmed`) promotes it to a block.
  - `dismissed.md` — accepted-risk registry (header only; `- <path/pattern> — <reason>` downgrades that item to a warning).
  - `findings.json` — `{ "open": [] }` (the gate writes open violations here).
- `.claude/guild/overlay/.gitkeep` — flow-policy override surface (empty; `/gld contribute` upstreams diffs here — plan §10).
- `.claude/guild/.gitignore` — containing `memory/` (episodic memory is gitignored per plan §6).
- `.claude/guild/memory/.gitkeep`.

**config.json (M1 subset, plan §18 C):**
```json
{
  "version": "0.18.2",
  "language": "<lang from $1>",
  "roles": ["leader", "tech-lead", "developer", "tester", "product-owner", "qa", "designer", "infra", "dba", "security", "performance", "i18n", "analytics", "tech-writer", "release-manager", "support-triage"],
  "commands": { "test": "<simple cmd>", "lint": ["<step1>", "<step2>"], "typecheck": null, "build": null, "e2e": "<simple cmd or null>" },
  "automation": { "evolve_nudge": false },
  "gates": { "enabled": true }
}
```
- `commands.*` values are the **normalized, simple-bash-safe** forms from command-scan (see `scan_repo.md` Section 2): each is either a single simple command string, or an **array** of simple commands run in sequence. They MUST NOT contain `$(...)`, `&&`, `|`, `;`, or redirections — Guild runs them one per Bash call. (e.g. `flutter test --fail-fast --concurrency=$(nproc --all)` → store `"flutter test --fail-fast"`; `flutter analyze && npx remark . --quiet --frail` → store `["flutter analyze", "npx remark . --quiet --frail"]`.) A missing category → `null`.
- `commands.e2e` records the detected integration/E2E command (e.g. `flutter test integration_test`). **M1 detects and records it but does NOT auto-run E2E** (test stage runs unit/existing tests only — plan §18 B; E2E auto-run is a later milestone). Recording it here keeps the info from being lost and lets a human run it manually.
- `roles` lists the **full installed roster** (16) — the spine roles plus every participation/gate specialist. It records who is *available*; the leader decides who *participates* per task (`_handoff.md` Section G). Keep it in sync with the agents actually written in step 2.
- `gates.enabled` (M3) is the **off-switch** for the enforcement layer — `true` = the pre-commit gate blocks (secret / verification-weakening); `false` = advisory only (plan §11 off-switch). `automation.evolve_nudge` is still a placeholder.

### 2. Role agents (the Guild's full roster — 16)
Install the **entire roster** so the leader can assemble any of them per task (plan §18 D — "전 역할 활성화; init이 로스터 전체 설치, 리더가 태스크별 조건부 참여"). The roster has three participation kinds (documented in `_handoff.md` Section G):
- **Spine roles (always in the flow)**: `leader`, `tech-lead`, `developer`, `tester`, `qa`.
- **Participation roles (leader convenes conditionally)**: `product-owner`, `designer`, `infra`, `dba`, `security`, `performance`, `i18n`, `analytics`, `tech-writer`, `release-manager`, `support-triage`.
- **Gate roles (conditional review checks)**: `designer` (UI/UX review), `security` (security review) — same files as their participation entry.

For **each of the 16** roles (`leader`, `tech-lead`, `developer`, `tester`, `product-owner`, `qa`, `designer`, `infra`, `dba`, `security`, `performance`, `i18n`, `analytics`, `tech-writer`, `release-manager`, `support-triage`):
- Read `<<SKILL_DIR>>/templates/agents/<role>.md`.
- Fill the `{{...}}` placeholders from the P1 scans + P1.5 interview:
  - `{{PROJECT_NAME}}`, `{{DOMAIN}}`, `{{STACK}}`, `{{TEST_CMD}}`, `{{E2E_CMD}}`, `{{E2E_SETUP}}`, `{{LINT_CMD}}`, `{{TYPECHECK_CMD}}`, `{{BUILD_CMD}}`, `{{CONVENTIONS}}`, `{{ARCHITECTURE}}`, `{{BOUNDARIES}}`, `{{TEST_FRAMEWORK}}`, `{{TEST_LOCATION}}`, `{{LEADER_NOTES}}`, `{{VALUES}}` (each template uses only the subset it needs).
  - `{{TEST_CMD}}`/`{{LINT_CMD}}`/`{{TYPECHECK_CMD}}` use the **normalized** commands from config (no `$(...)`/`&&`; render an array as a comma- or slash-separated list of the simple steps).
  - **The "주의(핫스팟·함정)" line MUST incorporate the hotspot-scan (scan 6) findings** — list the concrete top bug-hotspot files/areas (with their approximate `fix:` frequency) and any strong co-change groups, for `tech-lead`/`developer`/`tester`/`qa`/`performance`. This is evidence from git history, not a guess — do NOT reduce this line to "규칙 미정". (Hidden *rules/intent* may be "(미정 — evolve가 채움)", but **hotspots are known and must appear.**) Example: "핫스팟: `db_helper.dart`(fix 최다)·`sync_data_controller`·`iap_controller`·`tts_controller` — 변경 시 회귀 주의".
  - Fill the specialization section concretely — this is what makes the role *this repo's* senior, not a generic shell. Apply the **Output conventions** above: no raw `{{...}}` (use a localized "(미정)" note if unknown), structure enumerations as nested sub-bullets, and localize the heading (the template's `프로젝트 특화` heading stays localized — never emit `[PROJECT SPECIALIZATION]`).
  - **Not-applicable specialists**: a participation role the repo genuinely never needs (e.g. `dba`/`i18n`/`designer` for a single-language headless library) still gets **installed**, but its 프로젝트 특화 section is filled with a localized "(해당 없음 — 이 레포에 <해당 영역> 없음)" per that template's authoring hint. Installing it is cheap and lets `evolve` promote it later; the leader simply won't convene it. Do NOT skip creating the file.
- Write the result to `.claude/agents/<role>.md` (create; if a same-named agent already exists, see Merge rules below).

Static copy + specialization only — no HR (hire/retire/promote) in M1. The roster is installed as-is; growing/pruning it is `evolve` (plan §14 M1, §18 C/D).

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
- Read `<<SKILL_DIR>>/templates/settings.json.tmpl`; fill `{{TEST_BIN}}`/`{{LINT_BIN}}` (the executable names, e.g. `yarn`, `npm`, `pytest`). The template includes the **`PreToolUse(Bash: git commit)` gate hook** (M3 강제층 — runs `.claude/guild/gates/scripts/gate_precommit.py`).
- **If `.claude/settings.json` does not exist** → Write the filled template.
- **If it exists** → JSON has no comment markers, so merge by key: read the existing JSON, union `permissions.allow` (dedupe), and **union the Guild gate hook into `hooks.PreToolUse`** — append the Guild `{matcher:"Bash", hooks:[{... gate_precommit.py}]}` entry only if an equivalent one is not already present (dedupe by command path); **preserve all other existing hooks and keys**. Write the merged JSON back (2-space indent).

### 6. GitHub labels (skip if P0 found no GitHub repo)
Create the ten `guild:*` labels. Run each as its own Bash call; if any fails, report which and continue (labels are not transactional in M1 — they are idempotent with `--force`):
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
```
(`guild:harness` labels the remediation issues that P3.5's readiness audit proposes. `guild:needs-human` marks an Issue an unattended `/gld batch`·`sprint` run paused at a high-stakes gate — the human resolves it, then re-runs `/gld dev`/`resume`.)

---

## P3 — Confirm pass (optional, skippable)

Offer to confirm the drafted standards now (plan §7 P3, §6 draft→confirm→enforce):
- Show the user each `docs/standards/*.md` draft summary.
- For each, ask: keep as `draft`, or flip to `confirmed`? (Skippable — "confirm later with a manual edit or a future audit.")
- On confirm: change the file's frontmatter `status: draft` → `status: confirmed`.
- Enforcement is not wired in M1 (advisory harness), so this only sets intent — but it is the honest place to lock standards while the human is in the loop.

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

### 4. Remediation (opt-in, per gap — plan INV1)
For each **BLOCKER/MAJOR** gap (offer MINOR too, but default to skip), ask the user how to handle it. Offer only **safe, reversible** actions:
- **Create a tracking issue** (default): via the temp-file pattern, `gh issue create --body-file <path> --label guild:harness` (+ `type:refactor`/`type:chore` if those labels exist). Title = the gap; body = gap · why it helps Guild · acceptance criteria. **Dedup**: first search open issues for an existing `guild:harness` issue with the same gap `id` marker (`<!-- guild:harness:<id> -->`) — PATCH/skip if found. These issues are then developable with `/gld dev`.
- **Safe local fix** where applicable: e.g. gitignore gap → append the missing entries; committed-secret-file → add to `.gitignore` + `git rm --cached <file>` **(confirm first)**.
- **Guide-only for destructive/external actions** (committed/inline secrets): print the steps for git-history purge and key rotation — **NEVER auto-run** history rewrite (`git filter-branch`/filter-repo) or rotate keys. These are irreversible (T6/INV3) / external. The tracking issue captures the follow-up.

Batch the questions where possible (one grouped prompt listing gaps → user picks which to file). If the user skips remediation entirely, the report on disk still records everything.

---

## P4 — Summary

Report what was installed:
- Guild: 16 role agents at `.claude/agents/` — spine (leader, tech-lead, developer, tester, qa) + participation/gate specialists (product-owner, designer, infra, dba, security, performance, i18n, analytics, tech-writer, release-manager, support-triage). Note that the leader convenes the specialists **conditionally** per task (spine roles always run; specialists join by work-type/risk — see `_handoff.md` Section G).
- Standards: 5 drafts at `docs/standards/` (note which are `draft` vs `confirmed`).
- Harness: `CLAUDE.md` (created or merged), `.claude/settings.json` (created or merged), `.claude/guild/` state skeleton. Note whether `.gitignore` was reconciled (P2 step 0) so `.claude/` harness is committable — and confirm the harness is visible to git (`git status` shows it), since ignored files silently look "not created".
- ⑥ Knowledge baseline: `.claude/guild/knowledge/index.md` + `facts/` seeded from the scans (hotspots · co-change · coupling). Note the seeded slice count; `evolve` grows it from here.
- 강제층 게이트 (M3): `.claude/guild/gates/scripts/gate_precommit.py` + `PreToolUse` hook wired — blocks committing secrets / weakening verification. Off-switch: config `gates.enabled` (or `/gld config`).
- Labels: 10 `guild:*` (analyze, design, execute, test, qa, done, child, children, harness, needs-human) (or "skipped — no GitHub repo").
- Readiness audit (P3.5): report at `.claude/guild/readiness-report.md` — summarize the gap counts (BLOCKER/MAJOR/MINOR) and list any `guild:harness` issues created.
- Next steps: "`/gld dev <issue>` to develop a GitHub Issue end-to-end (including any `guild:harness` remediation issues). `/gld status <issue>` to check progress. Day-1 agents are intentionally rough — they improve as you work (evolve, a later milestone)."

---

## Partial-failure repair (not a hard dead-end)

`init` is additive and idempotent per-file. If it is interrupted, re-running detects `.claude/guild/config.json` at P0 and reports "already initialized." To repair a partial install, the completeness set is: `config.json` + 16 role agents (full roster) + 5 standards + CLAUDE.md guild block + settings.json allowlist **+ PreToolUse gate hook** + 10 labels + `knowledge/` baseline (index.md + facts/) + `gates/` (gate_precommit.py + rules + dismissed.md). Re-running does not auto-repair in M1 (P0 stops early) — instead, report any missing pieces from the completeness set in P4 so the user can address them, or delete `.claude/guild/config.json` to force a clean re-init.

## Hard rules (safety)
- **Additive only** (INV4): existing files are merged/preserved, never clobbered. CLAUDE.md via markers; settings.json via key union; existing `docs/standards/*` and `.claude/agents/*` are not overwritten.
- **Read-only scans** (P1) — no code changes during analysis.
- All Bash per `_bash_rules.md`; all file bodies via the Write/Edit tools.
