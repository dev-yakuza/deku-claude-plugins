# 01 — Configuration

User-facing configuration surfaces. Sources: `SKILL.md`, `commands/config.md`, `commands/init.md`, `commands/auto.md` Phase 3.1.

---

## 1. Configuration Storage [PRESERVE]

| Path | Purpose | Set by | Persistence |
|---|---|---|---|
| `.github/.sdd-lang` | Display language (en/ko/ja) | `/sdd init [lang]` | Permanent, gitignore-able |
| `.github/.sdd-config` | `skip-review` setting | `/sdd config --skip-review=...` or temporarily by `/sdd auto`/`/sdd batch` | Persistent (user) or transient (auto/batch with backup) |
| `.github/.sdd-config.bak` | Temporary backup during `/sdd auto`/`/sdd batch` | auto/batch pre-loop | Removed on cleanup |
| `.claude/settings.local.json` (or `.claude/settings.json`, `~/.claude/settings.json`) | Tool permissions + `sandbox.enabled` | User via `/config` or `/sdd auto`'s sandbox toggle | Persistent |
| `<SETTINGS_PATH>.sdd-auto.bak` | Sandbox pre-toggle snapshot | `/sdd auto` Phase 3.1 step 5e | Persistent; user-controlled restore |

[IMPROVE: paths are mostly `.github/.sdd-<x>` but sandbox-related ones live under `.claude/`. Consider unified `.github/.sdd/` directory with subkeys.]

[RETHINK: `.sdd-lang` and `.sdd-config` are separate files. Could be merged into a single `.sdd-config` with sections. Decision deferred — current separation simplifies parsing.]

---

## 2. `.sdd-config` Format [PRESERVE]

Plain text, line-based key-value:

```
skip-review: analyze,design,implement,pr
```

### Keys
- `skip-review` (only key currently used)
- Format: comma-separated values, allowed: `analyze`, `design`, `implement`, `pr`, `qa`
- Absent file or missing key → defaults to "no reviews skipped"

### Skip-review semantics [PRESERVE — important nuance]

| Value | Skipped | NOT skipped |
|---|---|---|
| `analyze` | User confirmation gate after analyze stage | AI review (Phase 1 loop still runs) |
| `design` | User confirmation gate after design stage | AI review |
| `implement` | User confirmation at plan stage (3-0). Per-step TDD reviews (3-1..3-4) are `self_only` and have no user gate to skip. | TDD step reviews; plan-stage user gate ONLY |
| `pr` | User confirmation at PR Final review (3-5) | AI review on PR (Phase 5 loop) |
| `qa` | Manual QA execution after test stage | AI review (Phase 2) |

**Critical invariant** [PRESERVE]: skip-review skips the **user confirmation gate**, NOT the **AI review loop**. AI review always runs.

**Cascade** [PRESERVE]: when `analyze` is skipped and AI review passes, the orchestrator **auto-proceeds** to `design.md` inline (no user trigger needed). Same for `design → implement`, `pr → test` (when both `pr` and `qa` are skipped).

[PRESERVE — load-bearing]: the values (`analyze`, `design`, `implement`, `pr`, `qa`) are user-typed config tokens in `.github/.sdd-config`. Renaming any of them breaks every existing user's config file.

[RETHINK — for rewrite design]: the inconsistency between stage labels (`analyze`/`design`/`implement`) and phase labels (`pr`/`qa`) is real but renaming requires user-decision + dual-read shim release. Candidate rename: `skip-review: analyze,design,plan,pr,qa` (renaming `implement` → `plan` to clarify scope). Decision deferred. (Was [IMPROVE] in v1; corrected per Reviewer C TAG-C5.)

---

## 3. Depth Labels [PRESERVE]

Per-Issue dial set via `gh issue edit <N> --add-label "sdd:review:deep"` (or `:shallow`).

| Label | Effect on AI review models | Effect on `/code-review` effort | Effect on preflight tier | Effect on `/security-review` |
|---|---|---|---|---|
| (none, default) | sonnet (reviewers), opus (work atoms, adversarial) | `high` | atom's default tier | runs |
| `sdd:review:deep` | opus everywhere | `max` | Heavy tier (extended ranges) | runs |
| `sdd:review:shallow` | sonnet/haiku (cheaper) | `medium` | Light tier | **skipped** |

**Model assignment table** (canonical in `_review_helpers.md` Section A.2) [PRESERVE]:

| Atom role | default | deep | shallow |
|---|---|---|---|
| `*_work` (analyze/design/test) | opus | opus | opus |
| `implement_plan` | opus | opus | opus |
| `implement_red/green/refactor/e2e/pr` | opus | opus | opus |
| `*_completeness` | sonnet | opus | sonnet |
| `*_quality` | sonnet | opus | sonnet |
| `*_adversarial` | opus | opus | sonnet |
| `parent_integration_review` | opus | opus | sonnet |
| `tdd_step_review` (step-1, step-4) | sonnet | opus | haiku |
| `tdd_step_review` (step-2, step-3) | haiku | opus | haiku |
| `implement_review` (PR Final completeness/quality) | sonnet | opus | sonnet |

[PRESERVE]: model assignments themselves (sonnet/opus/haiku per atom × depth) are dollar-impacting — keep table values verbatim.
[IMPROVE]: the DRY violation — this table is duplicated in each orchestrator's Phase 0. Rewrite should resolve via a single canonical source (the values stay, only the duplication goes).

---

## 4. Sandbox Toggle (auto.md Phase 3.1 step 5) [PRESERVE — load-bearing for unattended runs]

In projects whose `gh` / `git push` paths require `dangerouslyDisableSandbox: true` per call (TLS-proxy environments), every such call triggers a sandbox-bypass confirmation that **cannot be auto-approved** via `permissions.allow`. `/sdd auto` offers an opt-in to disable sandbox in settings file.

### Settings file priority [PRESERVE]
1. `.claude/settings.local.json` (project-local, gitignored)
2. `.claude/settings.json` (project-shared)
3. `~/.claude/settings.json` (user-global)

Use first file that has a `sandbox` key. If none, fall back to `.claude/settings.local.json` (create on opt-in).

### Toggle flow [PRESERVE]
1. Detect current state (`sandbox.enabled`).
2. Already OFF → skip prompt, proceed.
3. ON → prompt user with full warning. On approval:
   - Backup original to `<SETTINGS_PATH>.sdd-auto.bak` (or sentinel `__SDD_AUTO_NO_ORIGINAL__\n` if file didn't exist).
   - Set `sandbox.enabled = false`, preserve other keys.
   - Add `.sdd-auto.bak` to `.git/info/exclude` if SETTINGS_PATH is in-repo.
   - **Roll back pre-loop changes (skip-review config) and EXIT** — sandbox state only takes effect at session start.
   - Instruct user to re-launch Claude Code (optionally with `--dangerously-skip-permissions` to bypass heuristic prompts).

### `--dangerously-skip-permissions` flag [PRESERVE]
Companion flag for fully unattended `/sdd auto`. Bypasses ALL in-session safety prompts including:
- `find -exec` heuristic
- Multi-line `# …` in CLI args
- Quoted-variable expansion heuristic

**Warning**: flag persists across the ENTIRE session. User instructed to restart in NORMAL mode after `/sdd auto` completes.

[RETHINK: sandbox toggle UX (~190 lines in auto.md Phase 3.1) is complex. Investigate whether Claude Code provides a per-tool sandbox bypass that could replace this manual approach. Defer to user.]

---

## 5. `.sdd-lang` [PRESERVE]

Single-line file with the language code:

```
ko
```

Set by `/sdd init [lang]`. Values: `en`, `ko`, `ja`.

### Fallback [PRESERVE]
If `.github/.sdd-lang` does not exist:
1. Detect primary language of Issue body
2. Map to closest supported (`en`, `ko`, `ja`)
3. Unsupported → default `en`

---

## 6. Label Creation (`/sdd init`) [PRESERVE]

Created idempotently with `--force`:

| Label | Color | Purpose |
|---|---|---|
| `sdd:analyze` | `1d76db` | Lifecycle |
| `sdd:design` | `0e8a16` | Lifecycle |
| `sdd:implement` | `e4e669` | Lifecycle |
| `sdd:test` | `f9d0c4` | Lifecycle |
| `sdd:done` | `0075ca` | Lifecycle |
| `sdd:child` | `d4c5f9` | Child marker |
| `sdd:review:deep` | `b60205` | Optional depth dial |
| `sdd:review:shallow` | `c5def5` | Optional depth dial |

[PRESERVE: colors are a user-visible contract; users may have customized their GitHub label colors. Keep defaults.]
[IMPROVE: `/sdd init` doesn't check for label-name conflicts (existing non-SDD labels with same name).]

---

## 7. Permission Allowlist Baseline [PRESERVE]

`/sdd auto` and `/sdd batch` Phase 2 propose this baseline allowlist:

### Required
- `Read`, `Edit`, `Write`
- `Bash(gh:*)`, `Bash(git:*)`

### Recommended
- `Grep`, `Glob`
- `Agent`
- `WebSearch` (optional)

### Test Runners (auto-detected by repo markers)
| Marker | Permission |
|---|---|
| `pubspec.yaml` | `Bash(flutter:*)`, `Bash(dart:*)` |
| `.fvm/` or `.fvmrc` | `Bash(fvm:*)` |
| `package.json` | `Bash(npm:*)`, `Bash(npx:*)` |
| `yarn.lock` | `Bash(yarn:*)` |
| `pnpm-lock.yaml` | `Bash(pnpm:*)` |
| `pyproject.toml`/`requirements.txt`/`setup.py`/`Pipfile` | `Bash(pytest:*)` |
| `go.mod` | `Bash(go:*)` |
| `Cargo.toml` | `Bash(cargo:*)` |
| `Makefile` | `Bash(make:*)` |

**Matching rule** [PRESERVE]: exact unscoped match only. `Edit(/path/**)` does NOT satisfy `Edit`. Scoped permissions don't subsume unscoped requirements.

[IMPROVE: test-runner detection is hardcoded in `batch.md` and `auto.md`. DRY candidate — single registry.]

---

## 8. `.git/info/exclude` Entries [PRESERVE]

Auto-appended (idempotent) by `/sdd auto` and `/sdd batch`:
- `.github/.sdd-config`
- `.github/.sdd-config.bak`
- `.github/.sdd-batch.sh` (batch only)
- `<SETTINGS_PATH>.sdd-auto.bak` (auto only, if SETTINGS_PATH is in-repo)

**Rationale**: prevent subagent `git stash -u` from stashing these files mid-run.

[PRESERVE: this is a defensive mechanism; keep.]

---

## 9. `.github/.sdd-batch-logs/` [PRESERVE]

Created by `/sdd batch` to hold per-Issue stream-json logs. Path is:

```
.github/.sdd-batch-logs/issue-<N>-<timestamp>.log
.github/.sdd-batch-logs/errors-<timestamp>.log
```

Suggested for `.gitignore`. `/sdd batch` Phase 3 prompts user to add if not present.
