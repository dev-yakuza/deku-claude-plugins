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
`.claude/studio/scripts/` has another `SCRIPTS_VERSION` (now 12). Until `/std update` exists (M1), copy the plugin's
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

**M1b** (`SCRIPTS_VERSION` 10): `state.py` flow commands (`begin` · `record-source` · `hold` · `release-lock` ·
`record-render` · `done`, and `abandon` · `overlay` with a person's answer), `run_s2v.py` (render and snapshot; the proxy
watermark comes from the state) and the check results `stage-done` requires (`work/<l>/checks/*.json`, table
`schema.STAGE_CHECKS`). `begin` and `stage-done` need a committed harness.
- **The fake s2v CLI** `tests/py/drivers/fake_s2v_cli/packages/cli/dist/main.js` (Node, no dependencies): point
  `machine.json` at `tests/py/drivers/fake_s2v_cli`. Scenarios come from the JSON file named by
  `STUDIO_TEST_FAKE_S2V_SCENARIO` (the guard refuses `STUDIO_TEST_*` in agent commands); each call is appended to
  `calls.log` beside that file. It writes results only with `--out-dir` and never into its own folder.
  `fake_inspect_table.json` (which hash an edit changes) is measured from real s2v by `tests/tools/fake_table.py --write` (M1j).
- **Tests that move a video along** without the stages' check scripts (they arrive in M1d–M1h) use `checkfix.py`: it
  writes the passing check result a check script would write over the current inputs (the same input sha), so
  `stage-done` keeps its own rule. `test_m1b.StageChecks` turns this off and checks the rule itself.
- **Writers of protected records** (`stdo/writes.py`): the library writes state, check results, the used-answer record,
  commit-ok and machine.json only after an entry script called `writes.enable()`; `helpers.py` enables it for the test
  process (`test_m1b.Y2Writers` checks a fresh process is refused).

**M1c** (`SCRIPTS_VERSION` 11): `skills/std/scripts/setup.py` (plugin-only, with `stdo/setup/`: neither is in the
manifest or the copy) runs `init analyze|plan|apply`, `config get|preview|set`, `narrator preview|set` and
`update plan|apply`. `make_harness.py` is a thin wrapper over its `init` (no s2v check), so test harnesses carry the
default narrator, `installed.json`, the format and the guides. A harness commit's question shows the **value block**
(`--stage` prints it; commit-ok keeps `values_settings` · `values_machine` · `values_shown` · `overflow`): test helpers
that commit a harness put those lines in the question and in the recorded approval.

**M1d** (`SCRIPTS_VERSION` 12): `resolve_assets.py` and `check_scope.py` (the source stage). `test_m1d.py` builds a
synthetic static site (PNG/JPEG headers written byte by byte, WebP/AVIF headers, a © caption, a symbolic link out of the
web root, an image outside `visibility.public`). The source analyst's image classes are a JSON block in
`work/source.md`; `record-source` records images and the assets sha only after `check_scope` passed for that copy.


**M1e** (`SCRIPTS_VERSION` 13): `stdo/text/normalize.py` (the one excerpt normalization), `record-brief`'s computed
length, `check_claims.py` (`--narration`: the script check; without it: verify → `verify.json` · `verify.md`) and the
external auditor's guard rule (`G-AUDIT`). `test_m1e.py` drives a video through source, brief, script and verify with
the fake s2v (`FlowCase`); its `--full` test runs real `s2v lint` past `maxDuration`. Test claim ids are excerpt
hashes (`state_fixtures.C1` · `C2`, `brief_ready`), and the fixture state's `assets_sha` is the sha of
`state_fixtures.ASSETS_BYTES`, which `checkfix` writes before `stage-done script`. `record-source` freezes only
committed writing, so tests commit an article before recording it.

**M1f** (`SCRIPTS_VERSION` 14): `check_assets.py --actors`, `check_tts.py` and `audition.py` (`stdo/voice/`), gate ②'s
`pronounce-approved.json` and the guard's tts-under-lock rule. `test_m1f.py` takes a video from `test_m1e.FlowCase`
through ① (evidence written as `approve_base` does) and on through cast, tts (the fake s2v's `tts`, its per-sentence
`asr` · `cer` · `heard` scenario and `--retry`), audition (ffmpeg injected; `--full` joins with the real ffmpeg) and ②.
Its `--full` real-mock test writes mock lock entries by hand and runs only the real `s2v sentences` — no TTS or
aligner is started.

**M1g** (`SCRIPTS_VERSION` 15): the board check (`check_assets.py --output`, `stdo/board.py`), `state.py
credit-preview` · `credit` (`stdo/credits.py`, `stdo/state/credit.py`) and CREDITS.yaml. `test_m1g.BoardCase` takes a
video from `test_m1f.VoiceCase` through ②, then board with the credits, the fake s2v's snapshot, visual-check and ③.
The fake s2v's tts writes `tried` (the takes made) and keeps the old take when a scenario line says `keep`.

**M1h** (`SCRIPTS_VERSION` 16): `validate_copy.py` (`stdo/distribute/`) and the platform rules block of
`platforms/youtube.md`. `test_m1h.CopyCase` takes a video from `test_m1g.BoardCase` through ③, then the fake s2v's
render, record-render, ④a, the copy (the platform file marked checked and committed in the test) and ④b.

**M1i** (`SCRIPTS_VERSION` 17): the commit kind `video` (`stdo/commit/video.py`) and the status warnings.
`test_m1i.CommitCase` takes a video from `test_m1h.CopyCase` through ④b, then runs `check_commit.py --stage video`
in-process with a `VideoKind` given the test's providers (the fake s2v) and no Claude Code session in the environment;
the person's answer the guard would record is written into commit-ok.json by the test before `--staged` and `done`.

**M1j** (`SCRIPTS_VERSION` 18): the video commit decides by content (racy-git safe), never stages deletions under
`voices/`, merges pronounce keys NFC. `test_e2e_m1.py` runs the M1 flow with the fake s2v and the real guard, hooks
and git. `tests/tools/fake_table.py <s2v> --write` measures real s2v `inspect` (isolated HOME) into
`fake_inspect_table.json`; `test_m1j.FakeTable` (`--full`) compares real, table and fake.

**M1j follow-up** (`SCRIPTS_VERSION` 19): pronounce keys are NFC in the one shared reader (`pronounce.parse`,
`of_script`; harnessgate reads through it). `test_e2e_m1.E10bHandOver` runs the proxy mode (a sandbox session: ①–③
and the credit with `--proxy`, a marked render) and the hand-over to the person through ④b and the video commit.

**0.0.21** (`SCRIPTS_VERSION` 20): `platforms/youtube.md` counts the description in UTF-8 bytes
(`description_max_bytes`); a credit approved in the proxy mode is in ③'s tuple and the board inputs with the session's
mode, so after the hand-over the router sends the work back to board (E10b asserts it).
