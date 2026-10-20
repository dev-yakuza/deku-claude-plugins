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
