# AUDIT: readiness (shared diagnostic)

**Read-only harness-readiness diagnostic.** Checks whether the repo has what `/gld` needs to work well, and returns structured findings with severity + remediation. **Reused by**: `init` P3.5 (first run at onboarding) and `/gld audit` (re-run with scoring/trend). This atom does **not** modify anything, install tools, or create issues — those are the caller's HITL actions.

> **Bash**: simple calls only (`_bash_rules.md`). Codebase discovery via Grep/Glob/Read. **Read-only**: no Edit/Write (except the caller's report file), no installs, no git mutations.

---

## Inputs
- **`GATE_SCRIPT`** — the absolute path of the plugin's `gates/gate_precommit.py`, **supplied by the caller** (`init` P3.5 puts it in the spawn prompt; `audit` dimension A passes it inline). There is no fallback: this atom may run as a sub-agent, which cannot resolve `<<SKILL_DIR>>`. Not supplied, or the path does not exist → every check below that calls it reports `id: gate-script-unavailable`, **MAJOR** ("판정 불가 — 시크릿·훅 검사를 실행하지 못함"), and is **never** read as clean. The plugin's copy is used rather than the repo's `.claude/guild/gates/scripts/` copy because the repo's can lag behind these instructions (`update` may skip refreshing it) and an old script ignores the arguments below.
- **Exit-code contract for every `GATE_SCRIPT` call**: `0` = clean · `1` = found · **anything else (2 = could not scan, 64 = no input) = NOT judged**. Not judged → `id: secret-scan-unavailable` (or `gate-hook-undetermined` for the hook check), **MAJOR**, with the stderr line — never "no findings".
- The five P1 scan findings if available (from `scan_repo.md`), else re-derive by reading the repo directly.
- `.claude/guild/config.json` (for `commands`, `language`).
- Owner/repo (per `_handoff.md` Section F) for the GitHub-workflow checks.

## Output
Return one `>>> RESULT <<<` line followed by a findings JSON:
```
>>> RESULT <<<
{ "findings": [ { "group": "...", "id": "...", "severity": "BLOCKER|MAJOR|MINOR",
                  "title": "...", "why": "왜 Guild에 필요한가 (1줄)",
                  "remediation": "권고 조치 (1줄)", "present": false } ], "summary": { "blocker": 0, "major": 0, "minor": 0 } }
```
Keep each field to one line. `present: true` = the thing exists (not a gap — omit or mark ok); only emit gap findings.

## Severity rubric
- **BLOCKER** — breaks Guild's core loop or exposes a real secret (e.g. no test command at all → verify gate cannot function; a committed/inline secret → active leak, INV5).
- **MAJOR** — significantly weakens the harness (no CI, no E2E for an app that needs it, no `type:` labels, linter absent).
- **MINOR** — nice-to-have (coverage tooling, formatter, .gitignore gaps).

---

## Group 1 — 검증 신호 (verification signal)
The verify gate judges completion by real test evidence — without tests it is toothless.
- **Unit tests present?** Glob the test dir(s) (`test/`, `tests/`, `__tests__/`, `*_test.*`, `*.test.*`). None → `id: no-unit-tests`, **BLOCKER** (feature repos) / MAJOR (libs). why: "verify 게이트가 검증할 테스트가 없음".
  - **feature-repo vs lib classification** (from the P1 structure/stack scan — no new reads): a repo is a **lib** when its package manifest declares a publishable library with no runnable app target — e.g. a `package.json` with no `"scripts".start`/no `bin` and a `main`/`exports` field, a Python `pyproject.toml`/`setup.py` with no console-script/CLI entrypoint, a `pubspec.yaml` with no `flutter` app section (a pure Dart package). **Everything else — anything with a runnable app/binary/service target — is a feature repo** (the default when the manifest is ambiguous or absent, since an unrunnable-but-untested repo is the higher-risk case). State which one was detected and why in the finding's `why` field so the severity choice is auditable.
- **`test` command valid?** config `commands.test` present and points at a real runner? Missing → `id: no-test-command`, BLOCKER.
- **E2E / integration present?** From command-scan `e2e` / `integration_test/`·`e2e/`·cypress·playwright. Absent → `id: no-e2e`, MAJOR (surface it; do NOT run — M1 records only).
- **Visual regression present? (UI repos only)** A repo with a UI surface (Flutter app, React/Vue/Svelte app or component library, native mobile) and no golden/VRT setup — config `commands.vrt` null **and** `visual.baselines` empty, and command-scan 3b found none — → `id: no-visual-test`, MINOR. why: "화면 변경을 사람이 이미지로 확인할 근거가 없음 — 시각 회귀는 코드 리뷰로 잡히지 않음". Remediation names the stack's usual tool (Flutter golden tests · Playwright `toHaveScreenshot` · Vitest browser `toMatchScreenshot` · Storybook + reg-suit/Chromatic). ⚠ Report only — Guild does not install it (same rule as `no-linter`). A non-UI repo (CLI, server, library with no rendering) skips this check entirely, not `조치 불필요`-with-a-finding. **Configured but not runnable** — visual tests exist (`commands.vrt` non-null or `visual.baselines` non-empty) but `visual.runnable` is not `true` → `id: visual-not-runnable`, MINOR, with `visual.env` in the why: Guild skips visual cases for every UI Issue (`_handoff.md` Section L.1), so the visual check falls to the human. Remediation: a non-interactive way to run them in the rendering environment (usually a Docker image matching CI).
- **Coverage tooling?** lcov/coverage config, `--coverage` flag usage. Absent → `id: no-coverage`, MINOR.
- **(check only; do NOT execute the suite.)** Note in `remediation` that the user can run the command to confirm green.

## Group 2 — 정적 게이트 (static gates)

**Guild's own commit gate — check this first.** It is the only enforcement Guild installs, and
it can be silently absent in a repo that otherwise looks fully set up. Skip this whole block
when `.claude/guild/config.json` is absent (Guild not initialized — `init` will install it).

- **Who owns the hook, and is the gate actually wired?** ⚠ There are **two valid wirings**, and
  checking only one produces a false BLOCKER on every repo that uses a hook manager. Resolve the
  path first (never hardcode `.git/hooks/`, absent in a worktree), then ask the detector:
  ```bash
  git rev-parse --git-path hooks/pre-commit
  ```
  Pass that path to the detector as its argument (its own Bash call; never "pipe its text" —
  the Bash tool's stdin is `/dev/null`, so that form always read nothing):
  ```bash
  python3 <GATE_SCRIPT> --detect-hook-manager <resolved-path>
  ```
  It prints one word; a non-zero exit or any other output → `id: gate-hook-undetermined`, MAJOR.
  - Prints **`guild`** → Guild owns the hook. Confirm it is **executable** (`ls -l <path>`) —
    git silently ignores a non-executable hook, so this is installed-but-inert and
    indistinguishable from working. Not executable → `id: gate-hook-not-executable`, **BLOCKER**.
  - Prints **`absent`** → `id: gate-hook-missing`, **BLOCKER**. Remediation:
    `/gld update`. This is the **normal state of a fresh clone** — `.git/hooks/` is not tracked,
    so every clone starts without it while every committed harness file is present. Until then
    only the advisory `PreToolUse` layer runs and a compound `create-and-commit` in one Bash call
    is unchecked.
  - Prints **`none`** → a hand-written hook owns the file and Guild's shim is not in it →
    `id: gate-hook-missing`, **BLOCKER**, same remediation (`/gld update` moves the hand-written
    hook to `<path>.local` and chains to it).
  - Prints a **manager name** (`lefthook`/`husky`/…) → the hook file is *supposed* to be theirs
    (`init` step 2b). **Do not flag its absence.** Instead grep that manager's committed config
    for `gate_precommit.py`; present → wired correctly, no finding. Absent →
    `id: gate-not-registered-in-hook-manager`, **BLOCKER**, why: "훅 매니저가 훅 파일을 소유하는데
    Guild 게이트가 그 설정에 등록돼 있지 않음 — 커밋 게이트가 전혀 실행되지 않음".
    Remediation: `/gld update` re-registers it. ⚠ This is the failure mode a `lefthook install`
    (or any config rewrite) causes **silently**, which is exactly why it is checked here.
- **Do hooks even fire from `.git/hooks/`?** (its own Bash call; empty output is the good case):
  ```bash
  git config --get core.hooksPath
  ```
  Non-empty → `id: gate-hookspath-redirect`, **BLOCKER**. The repo redirects git hooks
  elsewhere (husky and similar do this), so Guild's hook never runs no matter how it is
  installed. Remediation: copy `.git/hooks/pre-commit` into that directory, or chain to it
  from the existing hook there. Report the literal path so the fix is actionable.
- **Is the gate switched off?** Read `.claude/guild/config.json` → `gates.enabled`. `false` →
  `id: gate-disabled`, MAJOR — legitimate (it is a documented escape hatch), but it should be
  a deliberate state, not one nobody remembers choosing. Note it and move on.

Then the repo's own static tooling:
- **Linter configured?** eslint/biome/ruff/flutter_lints/analysis_options etc. Absent → `id: no-linter`, MAJOR.
- **Typecheck available?** tsc/mypy/`flutter analyze`/etc. Absent (for a typed stack) → `id: no-typecheck`, MAJOR; N/A stacks → skip.
- **Formatter?** prettier/biome/black/dart format. Absent → `id: no-formatter`, MINOR.

## Group 3 — CI (PR safety net)
M1's reviewer is the human — CI is the automated backstop.
- **CI config present?** `.github/workflows/*.yml`, other CI configs. Absent → `id: no-ci`, MAJOR.
- **CI runs test + lint on PRs?** Read the workflow(s): do they invoke the test/lint commands on `pull_request`? If CI exists but doesn't run tests → `id: ci-no-tests`, MAJOR; lint missing → `id: ci-no-lint`, MINOR.

## Group 4 — GitHub 워크플로 (issue routing)
Guild's work-type routing needs labels; `dev` operates on Issues.
- **Issue templates?** `.github/ISSUE_TEMPLATE/`. Absent → `id: no-issue-templates`, MINOR.
- **`type:` labels?** Query labels:
  ```bash
  gh label list --limit 200 --json name --jq '[.[].name]'
  ```
  `gh label list --json name` already returns a flat top-level array of `{"name":...}` objects — indexing it as `.labels[]` (an earlier version of this doc did) errors out (`jq: error ... Cannot index array with string`, exit 5) before the whole command produces any output; verified against the real `jq` binary. Missing `type:feature`/`type:bug`/`type:refactor` → `id: no-type-labels`, MAJOR. why: "작업종류 라우팅(analyze의 재분류)이 라벨에 의존".

## Group 5 — 위생 (hygiene) — light heuristic (read-only)
⚠ This is a **light heuristic**, not a full secret scan (real scanning = gitleaks/trufflehog/Semgrep, offered as an opt-in deep step by the caller — later milestone). State this limitation in findings.
- **Committed sensitive files?** Ask the **commit gate itself** rather than re-implementing its judgement (its own Bash call — a bundled `python3 script.py` invocation is a sanctioned `_bash_rules.md` exception). It lists the tracked files itself — do not run `git ls-files` and hand the list over:
  ```bash
  python3 <GATE_SCRIPT> --scan-paths
  ```
  It prints one `SECRET-PATH <path>` line per sensitive tracked file and exits 1 if any, 0 if clean (any other exit = not judged, see Inputs); it never prints a value.
  ⚠ **Use this instead of a hand-written glob list.** An earlier version re-implemented the gate's pattern set inline as `git ls-files '.env' '*.pem' …` plus its own allowlist caveat — two copies of a security-critical definition, free to drift apart, with the drift invisible until something leaks. `--scan-paths` uses the same `SECRET_PATH_RE` and `SECRET_PATH_ALLOW_RE` as the **current plugin's** commit gate. ⚠ The repo's installed copy is what actually runs at commit time, and if `update` skipped refreshing it, it can be older and weaker than this check — a clean result here does not prove the commit-time gate would block the same file (`/gld update` closes the gap). (That allowlist is why `google-services.json` / `GoogleService-Info.plist` / `firebase_options.dart` are **not** flagged — public Flutter/Firebase client identifiers, conventionally committed; flagging them would train the human to dismiss this finding.)
  Any `SECRET-PATH` hit → `id: committed-secret-file`, **BLOCKER**, why: "레포/히스토리 시크릿 = 유출 경로(INV5)". remediation: "gitignore+`git rm --cached`(향후), 키 회전·히스토리 정리는 사람이 수행".
- **Obvious in-source tokens?** Same principle — use the gate's own inline pattern set rather than a copy. For each candidate source file (keep it bounded), its own Bash call, the file's path as the argument:
  ```bash
  python3 <GATE_SCRIPT> --scan-text <file-path>
  ```
  It prints `SECRET-TEXT <line-no>` per hit and never the value. Hits → `id: inline-secret`, BLOCKER (report file + line only). Any exit other than 0/1 → not judged (see Inputs).
- **.gitignore coverage?** Read root `.gitignore`. Missing coverage for `.env`, build artifacts, or `.claude/guild/memory/` → `id: gitignore-gap`, MINOR. (Note: init already writes `.claude/guild/.gitignore` for `memory/`; this checks the project root file.)

---

## Hard rules
- **Read-only.** No Edit/Write (the caller writes the report), no installs, no `gh label create`, no issue creation, no git mutations. Those are the caller's HITL steps.
- **Never print secret values** — report file+line/identifier only.
- **Bounded exploration**: ~10 Grep + 6 Glob + 8 Read total. If a check can't be determined, emit the finding with `severity: MINOR` and `title` noting "확인 불가" rather than guessing.
- Return exactly one `>>> RESULT <<<` line + findings JSON.
