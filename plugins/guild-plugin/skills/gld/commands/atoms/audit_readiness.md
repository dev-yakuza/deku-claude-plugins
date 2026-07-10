# AUDIT: readiness (shared diagnostic)

**Read-only harness-readiness diagnostic.** Checks whether the repo has what `/gld` needs to work well, and returns structured findings with severity + remediation. **Reused by**: `init` P3.5 (first run at onboarding) and the future `/gld audit` command (re-run with scoring/trend). This atom does **not** modify anything, install tools, or create issues — those are the caller's HITL actions.

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

## Severity rubric (plan §9)
- **BLOCKER** — breaks Guild's core loop (e.g. no test command at all → verify gate cannot function).
- **MAJOR** — significantly weakens the harness (no CI, no E2E for an app that needs it, no `type:` labels, linter absent, committed secret).
- **MINOR** — nice-to-have (coverage tooling, formatter, .gitignore gaps).

---

## Group 1 — 검증 신호 (verification signal)
The verify gate judges completion by real test evidence — without tests it is toothless.
- **Unit tests present?** Glob the test dir(s) (`test/`, `tests/`, `__tests__/`, `*_test.*`, `*.test.*`). None → `id: no-unit-tests`, **BLOCKER** (feature repos) / MAJOR (libs). why: "verify 게이트가 검증할 테스트가 없음".
- **`test` command valid?** config `commands.test` present and points at a real runner? Missing → `id: no-test-command`, BLOCKER.
- **E2E / integration present?** From command-scan `e2e` / `integration_test/`·`e2e/`·cypress·playwright. Absent → `id: no-e2e`, MAJOR (surface it; do NOT run — M1 records only).
- **Coverage tooling?** lcov/coverage config, `--coverage` flag usage. Absent → `id: no-coverage`, MINOR.
- **(check only; do NOT execute the suite — plan decision #1=A.)** Note in `remediation` that the user can run the command to confirm green.

## Group 2 — 정적 게이트 (static gates)
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
  gh label list --limit 200 --json name --jq '[.labels[]?.name] // [.[].name]'
  ```
  (Adjust to the available shape.) Missing `type:feature`/`type:bug`/`type:refactor` → `id: no-type-labels`, MAJOR. why: "작업종류 라우팅(analyze의 재분류)이 라벨에 의존".

## Group 5 — 위생 (hygiene) — light heuristic (read-only)
⚠ This is a **light heuristic**, not a full secret scan (real scanning = gitleaks/trufflehog/Semgrep, offered as an opt-in deep step by the caller — plan §11 later milestone). State this limitation in findings.
- **Committed sensitive files?** Check whether git *tracks* sensitive paths (each its own Bash call, read-only):
  ```bash
  git ls-files .env .env.* *.pem *.p12 *.keystore *.jks serviceAccount*.json google-services.json
  ```
  Any tracked → `id: committed-secret-file`, **BLOCKER**, why: "레포/히스토리 시크릿 = 유출 경로(T4/INV5)". remediation: "gitignore+`git rm --cached`(향후), 키 회전·히스토리 정리는 사람이 수행".
- **Obvious in-source tokens?** Bounded Grep for high-signal patterns (`AKIA[0-9A-Z]{16}`, `-----BEGIN * PRIVATE KEY-----`, `AIza[0-9A-Za-z_-]{35}`). Hits → `id: inline-secret`, BLOCKER (flag file+line; do NOT print the secret value). Keep bounded (≤ a few Grep calls).
- **.gitignore coverage?** Read root `.gitignore`. Missing coverage for `.env`, build artifacts, or `.claude/guild/memory/` → `id: gitignore-gap`, MINOR. (Note: init already writes `.claude/guild/.gitignore` for `memory/`; this checks the project root file.)

---

## Hard rules
- **Read-only.** No Edit/Write (the caller writes the report), no installs, no `gh label create`, no issue creation, no git mutations. Those are the caller's HITL steps.
- **Never print secret values** — report file+line/identifier only.
- **Bounded exploration**: ~10 Grep + 6 Glob + 8 Read total. If a check can't be determined, emit the finding with `severity: MINOR` and `title` noting "확인 불가" rather than guessing.
- Return exactly one `>>> RESULT <<<` line + findings JSON.
