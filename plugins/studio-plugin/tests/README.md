# Studio tests (developer notes)

```bash
bash plugins/studio-plugin/tests/run_tests.sh          # default: offline, standard library only
STUDIO_TEST_S2V=/abs/path/to/script2video \
  bash plugins/studio-plugin/tests/run_tests.sh --full # everything; required before every commit
```

- **Default run**: structure checks and the Python tests that need nothing outside the standard
  library. Tests that need script2video or npx are skipped; the run ends with the number of
  skipped tests and why.
- **`--full`**: runs everything and fails when `STUDIO_TEST_S2V` is unset or `npx` is missing.
  Any skipped test is a failure. It warns when `STUDIO_TEST_DENY_TERMS_FILE` is not set.
- **`STUDIO_TEST_S2V` set but unusable** (no `dist/main.js`, older than 0.12.1, stale `dist` —
  run `yarn build`) fails in every mode; only an unset variable skips.
- **Before every commit** of a Studio sub-item (and of each review round): run `--full`.
- **Python**: `PY=/usr/bin/python3 bash …/run_tests.sh` runs everything with another interpreter
  (check the oldest one the guard may run under, e.g. the system Python).
- **Isolation**: the whole run uses a temporary `HOME`, `S2V_STATE_DIR`, `STUDIO_HOME`,
  `CLAUDE_CONFIG_DIR` and `GIT_CONFIG_GLOBAL`, and drops outside `CLAUDECODE`, `CLAUDE_CODE_*`,
  `S2V_*`, `STUDIO_*` (except the `STUDIO_TEST_*` switches) and `XDG_CONFIG_HOME`.
  `run_tests.sh` fails if, during the run, the real s2v state folder (`$S2V_STATE_DIR` or
  `~/.s2v`), Studio's per-user files (`studio-sandbox.json`, `studio-backup/` in `$CLAUDE_CONFIG_DIR`
  or `~/.claude`), that folder's `settings.json`, `~/.claude.json` or `~/.gitconfig` changed — a
  script2video or Claude Code session running at the same time can cause this too. A leaked
  `S2V_HEAVY_LOCK_TOKEN` or `S2V_ACTOR_LOCK_TOKEN` stops the run at start.
- **script2video calls** go through `helpers.run_s2v`: a fake `uv` (exit 97) is first on `PATH`
  and `S2V_TTS=mock`, so no model server can start.
- **Test-only behaviour** is injected by importing modules in tests (never by a flag file).
  `STUDIO_HOME` and `STUDIO_TEST_*` variables are for tests only; the guard refuses agent
  commands that set them.
- `STUDIO_TEST_DENY_TERMS_FILE` (optional): a file outside the repository with one term per line
  that must not appear in shipped files.
- Fixtures are synthetic only (`tests/fixtures/`).
- **Hook managers (M0e)**: `test_hooks_full.py` runs only under `--full`. It fetches pinned
  `husky@9.1.7` and `lefthook@2.2.2` with `npx --yes` into an npm cache inside the test's temporary
  home (`npm_config_cache`, `npm_config_userconfig=/dev/null`) — no global install, network needed.
  Everything else about the hook (plain git, husky and lefthook file formats, chaining) runs offline
  with real git in temporary repositories. `STUDIO_TEST_COMMIT_KIND` registers a test-only commit kind
  (`test`) for `check_commit.py --stage`; the guard refuses `STUDIO_TEST_*` in agent commands.
- **Perf lines**: `test_commit_perf.py` prints the runner's cost on a non-Studio commit and
  `check_commit --staged` on a Studio commit (targets 50 ms / 300 ms; fails only above 3×).

**Scripts version (M0d-2, D-M0-3)**: the guard refuses Studio commands in a repository whose copy of
`.claude/studio/scripts/` has another `SCRIPTS_VERSION` (now 9). Until `/std update` exists (M1), copy the plugin's
`skills/std/scripts/` (without `guard.py` and `stdo/guard/`) into an older sandbox repository again by hand.

**M0f**: `tests/py/drivers/make_harness.py <dir>` builds a synthetic harness repository (templates, agents, a copy of
the scripts, ignore blocks, the hook, a first commit made outside any session) — the end-to-end tests and the sandbox
real-session check use the same function. After changing anything under `skills/std/scripts/`, run
`python3 tests/tools/manifest.py` (structure_test.sh checks `MANIFEST.sha256`). From 0.0.9 (`SCRIPTS_VERSION` 8)
older sandboxes are refused by the guard: build them again with `make_harness.py`.

**M1a** (`SCRIPTS_VERSION` 9): the s2v path is this machine's, in `.claude/studio/local/machine.json` (not committed;
`config.json` keeps `s2v.min_version` only) — `make_harness.py --s2v PATH` and `helpers.make_repo(s2v=…)` write it.
Approval labels name the video (`승인 <video> <hash12>`; hash12 hashes the video, language and gate too) and the
question shows `[<video>]`. The used-answer record is `<git common dir>/studio/consumed-answers.jsonl`, shared by the
worktrees (an old `.claude/studio/local/consumed-answers.jsonl` is ignored from 9 on). Shown records from before 9
have other hash12s: show them again (sandboxes and tests only).

**Moving a 0.0.x sandbox to 9 by hand** (`/std config` arrives in M1c): copy the scripts again (or rebuild with
`make_harness.py`); in `.claude/studio/config.json` delete `"path"` under `"s2v"` (keep `"min_version"`) — a harness
commit refuses the old format; create `.claude/studio/local/machine.json` as
`{"schema": 1, "s2v": {"path": "<absolute s2v path>"}}` (a real folder, never a link); show every gate again.
