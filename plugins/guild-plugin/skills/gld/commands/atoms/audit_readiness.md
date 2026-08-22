# AUDIT: readiness (shared diagnostic)

**Read-only harness-readiness diagnostic.** Checks whether the repo has what `/gld` needs to work well, and returns structured findings with severity + remediation. **Reused by**: `init` P3.5 (first run at onboarding) and `/gld audit` (re-run with scoring/trend). This atom does **not** modify anything, install tools, or create issues — those are the caller's HITL actions.

> **Bash**: simple calls only (`_bash_rules.md`). Codebase discovery via Grep/Glob/Read. **Read-only**: no Edit/Write (except the caller's report file), no installs, no git mutations.

---

## Inputs
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
- **Coverage tooling?** lcov/coverage config, `--coverage` flag usage. Absent → `id: no-coverage`, MINOR.
- **(check only; do NOT execute the suite.)** Note in `remediation` that the user can run the command to confirm green.

## Group 2 — 정적 게이트 (static gates)

**Guild's own commit gate — check this first.** It is the only enforcement Guild installs, and
it can be silently absent in a repo that otherwise looks fully set up. Skip this whole block
when `.claude/guild/config.json` is absent (Guild not initialized — `init` will install it).

- **Is the authoritative hook installed and executable?** (its own Bash call — the output is
  the permission string, or nothing if the file is missing):
  ```bash
  ls -l .git/hooks/pre-commit
  ```
  Missing, or present without an execute bit → `id: gate-hook-missing`, **BLOCKER**.
  Remediation: `/gld update` (reinstalls and `chmod +x`). This is the **normal state of a
  fresh clone** — `.git/hooks/` is not tracked, so every clone of a Guild-enabled repo starts
  without it while every committed harness file is present. Without it, only the advisory
  `PreToolUse` layer runs, and a compound `create-and-commit` in one Bash call is unchecked.
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
- **Committed sensitive files?** Ask the **commit gate itself** rather than re-implementing its judgement (its own Bash call — a bundled `python3 script.py` invocation is a sanctioned `_bash_rules.md` exception):
  ```bash
  git ls-files
  ```
  Pipe is forbidden, so run that first, then feed the file list to the gate's path scanner as its own call:
  ```bash
  python3 .claude/guild/gates/scripts/gate_precommit.py --scan-paths
  ```
  (stdin = the `git ls-files` output you just read.) It prints one `SECRET-PATH <path>` line per sensitive tracked file and exits 1 if any, 0 if clean; it never prints a value.
  ⚠ **Use this instead of a hand-written glob list.** An earlier version re-implemented the gate's pattern set inline as `git ls-files '.env' '*.pem' …` plus its own allowlist caveat — two copies of a security-critical definition, free to drift apart, with the drift invisible until something leaks. `--scan-paths` uses the same `SECRET_PATH_RE` and `SECRET_PATH_ALLOW_RE` the commit gate blocks on, so this check and commit-time enforcement can never disagree. (That allowlist is why `google-services.json` / `GoogleService-Info.plist` / `firebase_options.dart` are **not** flagged — public Flutter/Firebase client identifiers, conventionally committed; flagging them would train the human to dismiss this finding.)
  Any `SECRET-PATH` hit → `id: committed-secret-file`, **BLOCKER**, why: "레포/히스토리 시크릿 = 유출 경로(INV5)". remediation: "gitignore+`git rm --cached`(향후), 키 회전·히스토리 정리는 사람이 수행".
  If the gate script is absent (Guild not initialized), fall back to a **quoted** glob query — quote every pattern, because unquoted globs are expanded by the shell before `git ls-files` sees them, and under zsh's default `NOMATCH` an unquoted pattern matching nothing **aborts the whole command** (verified: `git ls-files .env.*` with no such file exits 1 with "no matches found", not a clean empty result), silently skipping this BLOCKER-severity check:
  ```bash
  git ls-files '.env' '.env.*' '*.pem' '*.p12' '*.keystore' '*.jks' 'serviceAccount*.json'
  ```
- **Obvious in-source tokens?** Same principle — use the gate's own inline pattern set rather than a copy. For each candidate source file (keep it bounded), its own Bash call:
  ```bash
  python3 .claude/guild/gates/scripts/gate_precommit.py --scan-text
  ```
  (stdin = the file's text.) It prints `SECRET-TEXT <line-no>` per hit and never the value. Hits → `id: inline-secret`, BLOCKER (report file + line only). Gate script absent → bounded Grep for `AKIA[0-9A-Z]{16}`, `-----BEGIN * PRIVATE KEY-----`, `AIza[0-9A-Za-z_-]{35}` as a degraded fallback, and say in the finding that it was the degraded path.
- **.gitignore coverage?** Read root `.gitignore`. Missing coverage for `.env`, build artifacts, or `.claude/guild/memory/` → `id: gitignore-gap`, MINOR. (Note: init already writes `.claude/guild/.gitignore` for `memory/`; this checks the project root file.)

---

## Hard rules
- **Read-only.** No Edit/Write (the caller writes the report), no installs, no `gh label create`, no issue creation, no git mutations. Those are the caller's HITL steps.
- **Never print secret values** — report file+line/identifier only.
- **Bounded exploration**: ~10 Grep + 6 Glob + 8 Read total. If a check can't be determined, emit the finding with `severity: MINOR` and `title` noting "확인 불가" rather than guessing.
- Return exactly one `>>> RESULT <<<` line + findings JSON.
