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
- **`STUDIO_TEST_S2V` set but unusable** (no `dist/main.js`, older than 0.13.0, stale `dist` —
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
`.claude/studio/scripts/` has another `SCRIPTS_VERSION` (now 27). Run `/std update` in an older sandbox repository,
or copy the plugin's `skills/std/scripts/` (without `guard.py` and `stdo/guard/`) into it again by hand.

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

**0.0.22** (`SCRIPTS_VERSION` 21, s2v 0.13.0): s2v's `no-visual` warning (a scene with narration that shows only the
background) fails the script, cast and board checks. The fake s2v keeps a leaf directive's label (`::title[…]` is a
visual, not narration) and warns `no-visual` with real s2v's rule and message (the first visual other than
`::thumbnail` is missing or a label-less `::title`; exempt when every speaker has `character` art — the fake ignores
`:react`), per output (its `scenes: [...]` and its own character mode; `:only` is not modeled). Only title · image ·
video · thumbnail are leaf visuals (another leaf is `container-required`). A visual block is content (and presentation
when added), its label content and `screen_text` (`fake_table.py` measures `visual_block` · `visual_label`). Fixture
scenes without a visual get `::title[…]` after their last paragraph, so sentence ids stay. The script, cast and board
checks print s2v's `no-visual` message (the scene) after the code line.

**0.0.23** (`SCRIPTS_VERSION` 22, pilot 1): a G-EVIDENCE refusal at ① ② ④b, a credit, an overlay, a setup change line
or a commit's value block names the first missing line, how many are missing and the question's closest line with
where it differs (`commit/summary.first_missing`); `shown 1|2|4b` and `credit-preview` print the question block to paste
unchanged (`test_e2e_m1` asks with it); ④b's lines are the union over the current platforms whatever `--platform`
says, and lines that cannot be computed deny (fail closed). Spaced Korean numbers are joined (`열 다섯 개` = 15,
`십 오 분` = 15). The ignore block ignores `videos/*/audio/` and `videos/*/CREDITS.draft.yaml` (no `!` line);
`/std update` rewrites old blocks, keeping a person's own lines in `.gitignore` (`ignore.SHIPPED` lists every released
line). The copy must be NFC, and the description's bytes count each inner line break as 2. `test_pilot1.py` covers
all of it.

**0.0.24** (`SCRIPTS_VERSION` 22: only plugin-only files changed — `setup.py`, `stdo/setup/`, the guard, `SKILL.md`,
the command documents; pilot 1 P6 · P7): documents are printed by `setup.py doc [<name>]` (names from
`commands/*.md` and `commands/atoms/*.md`, looked up, never joined from the argument; `<<SKILL_DIR>>` replaced; no
repository needed, nothing written), and `SKILL.md` pre-approves `Bash(python3 "${CLAUDE_SKILL_DIR}/scripts/setup.py"
doc *)` for the invoking turn. The guard allows that call in any folder through the usual allow path
(`judge.doc_call` before the Studio-repository return, one candidate of kind `doc`, `allowrule.sole` as for state.py):
only the two spellings of the plugin's own `setup.py` (not a link), a name in `doc.NAMES`, no allow when the run
folder's root holds the plugin or the interpreter (a venv: the PATH result, its real path, `pyvenv.cfg` one or two
folders up), or when a warning is shown. `setup.py` imports from its real folder. `init analyze` adds
`public_domains`, `brand_colors`, `logos`, `ask_husky` and `partial` from tracked files only (`analyze.Walk`: lstat
regular files under the top level, no `.env*`, vendor folders, minified or banner files; a 20 MB / 3,000-file budget).
`test_pilot1b.py` covers all of it, with the pilot's colour counts, a FIFO behind a tracked link (with a timeout) and
the guard's time; `structure_test.sh` checks the rule, the `doc` mentions and init.md's question rules.

**0.0.25** (`SCRIPTS_VERSION` 23, pilot 2): `check_claims.py <video> --source [--fill]` lists the claim ids of
`work/source.md` (`ok`, `placeholder`, `was C-…`; a missing excerpt or one excerpt listed twice fails) and with
`--fill` writes the right ids atomically, with no script and no s2v; `--skeleton` (re)writes
`work/<lang>/verify.draft.json` from s2v's sentences, screen text and the titles the verify check judges, keeping the
entries whose normalized text is still there; `--source`, `--skeleton` and `--narration` exclude each other.
`setup.py doc s2v-syntax` prints s2v's write-script reference through a fence (the repository found by walking up for
`.git`, no process; `O_NOFOLLOW`, the real path under the real s2v path, the opened file the one that path names, a
regular file of at most 25,000 characters). `state.py shown <video> 2` prints `read: <audition.md>` after `hash12`
when the file exists (block and hash unchanged). The documents run approvals as the next tool call of the same turn,
the guard-refusal blocks, INV9 and every role rule carry the "This is not a stop" exception, and every role but the
auditor does file work with Read, Write and Edit. `test_pilot2.py` covers these with stub Providers (no s2v process);
the guard's 0.0.25 changes (the sed shapes, the non-stop and re-ask suffixes) are in `test_pilot2_guard.py` and
`test_guard_judge.py`; `structure_test.sh` checks the wording.

**0.0.26** (`SCRIPTS_VERSION` 24, pilot 2 P16 · P17): `stdo/look.py` judges the brand logo live (inside the
repository, a regular PNG or JPEG file, brand.json and the logo committed — `flow.uncommitted`) and reads the theme,
outputs and title from the frontmatter text (trailing comments dropped after an unquoted `#` colour is reported).
`check_assets.py <video> --look --output <o>` prints the lines the brand asks for and writes nothing; the board check
adds the look rules (accent, brand logo by path and sha, no `presenter`/`dialogue` without character art — absent is
s2v's `presenter`), the brand logo is a picture whose CREDITS floor is `public/brand.json logo (committed in the
harness)`, and brand.json with its logo joins the board's inputs (`brand_json`). The script check adds the title scene
(only ATX level-1 headings start scenes; fences close on their own marker, also inside `:::code`), every usable image
shown or listed in `unused_images` with a one-line reason (printed again, sanitized, after the ① question block), and
the layout rule in script mode (absent passes). The harness commit warns when brand.json names an uncommitted logo.
The fixture script (`test_m1e.SCRIPT`) opens with a title scene and `test_m1e.branded()` adds the look board writes;
the fake s2v's layout default is `presenter` and it takes `logo: <path>`. `test_pilot2b.py` covers all of it with stub
Providers; `RealInspect` runs real `s2v inspect`/`lint` only with `STUDIO_TEST_S2V` (`--full`). The init parts are in
`test_pilot2b_init.py`.

**0.0.27** (`SCRIPTS_VERSION` 24, G1: only the guard changed, which is plugin-only): the runners the guard unwraps
(`stdo/guard/runners.py`: one option reader per runner, refused runners, shell payloads, file arguments), program
names in capitals, nested strings judged in any folder, folders the guard cannot tell (`**/<rel>`), the fallback for
unmodelled programs, zsh's tables and forms the walk does not model, command-valued options and variables
(`stdo/guard/cmdopts.py`), READ_ALLOW programs that write, wildcards in folder parts (`protect.glob_may_match`, `**`
by listing the existing matches) and words the shell may drop (the readings of `walk_simple`). `test_guard_runners.py`
covers the option reader, the matcher and the pin that every runner has a must-deny and a must-pass case;
`test_guard_judge.py` holds `RUNNER_DENY`, `G1_DENY` (run again under `studio/videos/v` by `test_pilot2_guard.py`),
`RUNNER_PASS`, `G1_PASS` and `NESTED_OUT_DENY` (from outside the repository); `test_guard_walk.py` the walk's side
(`G1Walk`, `G1Words`). The implementation review's findings are `G1_REVIEW1_DENY` (also under `studio/videos/v`),
`G1_REVIEW1_PASS` and the class `G1Review1` (listed `**` globs, the walks' budget, limits that are not errors),
`G1Fixes` in `test_guard_walk.py`, and `Review1`/`CmdOpts` in `test_guard_runners.py`. Review 2's are
`G1_REVIEW2_DENY` (also under `studio/videos/v`), `G1_REVIEW2_PASS`, the review-2 rows of `NESTED_OUT_DENY` and
`NESTED_OUT_PASS`, the class `G1Review2` (git's and ssh's files in another letter case, the snapshot's functions with
the fixture functions `SNAPSHOT_FUNCS`, the git refusal after an unknown environment), `G1Review2` in
`test_guard_walk.py` and `Review2` in `test_guard_runners.py`. `test_limits_are_not_errors` (in `G1Review1`) checks
that a command past the limits is never G-ERR: outside every Studio repository a long command passes when no limit is
hit, in one it is G-LIMIT (outside, a limit that is hit refuses too when something in the command may name a
repository: `G1Review3.test_limit_outside_names_nothing`). Review 3's are `G1_REVIEW3_DENY` (also under
`studio/videos/v`), `G1_REVIEW3_PASS`, the decoy rows of `NESTED_OUT_DENY`, the class `G1Review3` (the snapshot's
functions with `REVIEW3_FUNCS`, `REVIEW3_FUNCTION_PASS` and `REVIEW3_FUNCTION_DENY`; decoy folders and limits outside a
Studio repository), the function-effect cases of `G1Review2.test_snapshot_function_effects` in `test_guard_walk.py`
and `Review3` in `test_guard_runners.py`. Review 4's are `G1_REVIEW4_DENY` (also under `studio/videos/v`),
`G1_REVIEW4_PASS`, the review-4 rows of `NESTED_OUT_DENY`, the class `G1Review4` (autoload stubs, functions the call
redefines under a snapshot function, the snapshot's hook functions, functions the guard cannot read followed by
unquoted values, with `REVIEW4_FUNCS`, `REVIEW4_FUNCTION_PASS`/`_DENY`, `REVIEW4_OUT_PASS`/`_DENY` and `SNAP_HOOKS`)
and `G1Review4` in `test_guard_walk.py` (function bodies, hooks, pushd and loop conditions, NULLCMD, steered values,
quoted pattern characters). Review 5's are `G1_REVIEW5_DENY` (also under `studio/videos/v`), `G1_REVIEW5_PASS`, the
review-5 rows of `NESTED_OUT_DENY`, the class `G1Review5` (values after a function the guard cannot read, with
`REVIEW5_FUNCTION_PASS`/`_DENY`), `test_function_with_several_names` and `test_reserved_word_after_assignments` in
`test_guard_parse.py`, the auditor's pager and editor values in `test_m1e.Auditor.test_bash_reads_only`, and
`script -q /dev/null` among the refused forms of `test_m1a.OtherWriters.test_x1_scripts_and_text_built_at_run_time`.
Review 6's are `G1_REVIEW6_DENY` (by class: qualifiers of whole words, stdin into compound commands, functions and
`exec`, function-table writes and nested definitions, zsh's short forms; also under `studio/videos/v`),
`G1_REVIEW6_PASS`, the review-6 rows of `NESTED_OUT_DENY` (`$HOME` written by any route), the class `G1Review6`
(wildcards against installed hook files with `REVIEW6_HOOK_DENY`/`_PASS`, extended-glob words after a function the
guard cannot read with `REVIEW6_FUNCTION_PASS`/`_DENY`), `test_review6_forms` in `test_guard_parse.py` and the
extended-glob cases of `UnknownFolder.test_matcher` in `test_guard_runners.py`. Review 7's are `G1_REVIEW7_DENY`
(by class: bracket expressions as zsh reads them, positionals set by `N=`, stdin into `eval` and `-c` strings, the
`[[ … == pattern ]]` operand and unparsable text, several loop names; also under `studio/videos/v`),
`G1_REVIEW7_PASS`, the review-7 rows of `NESTED_OUT_DENY` (a `~` word after `$HOME` is written), the class
`G1Review7` (brackets against installed hook files with `REVIEW7_HOOK_DENY`/`_PASS`), `test_review7_forms` in
`test_guard_parse.py` and the bracket cases of `UnknownFolder.test_matcher`. Review 8's are `G1_REVIEW8_DENY` (by
class: numeric globs `<N-M>`, redirections that may fail and `PIPEFAIL`, zsh forms the parser now reads and unparsable
text however its command is spelled, `case` patterns and `;&`/`;|`, `GLOB_STAR_SHORT`, a function body judged from its
call; also under `studio/videos/v`), `G1_REVIEW8_PASS`, the review-8 rows of `NESTED_OUT_DENY` (`$HOME` for `eval`,
`-c` strings and functions), the class `G1Review8` (aliases after the new forms, with `REVIEW8_ALIAS_DENY`) and
`test_review8_forms` in `test_guard_parse.py`. Review 9's are `G1_REVIEW9_DENY` (by class: git, `$PWD`, `~+` and
`$(pwd)` in each folder a command may run in, `$'…'` in case patterns, several inputs on one fd, `$~1`, values the guard
does not carry as one string; also under `studio/videos/v`), `G1_REVIEW9_PASS` (numeric globs matched as digits,
ordinary arrays and loops), the review-9 rows of `NESTED_OUT_DENY`, the class `G1Review9` (the directory stack after a
`pushd` that may not run), `test_review9_forms` in `test_guard_parse.py` and the numeric-glob cases of
`UnknownFolder.test_matcher`. Review 10's (the union rule: a value or folder that may or may not change is one of the
old and new ones) are `G1_REVIEW10_DENY` (by class: `$PWD`, `~+`, `$(pwd)` and `git rev-parse --show-toplevel` after
a trap, a hook or a folder change the guard cannot follow; `local` and writes that may not run in a function; `read`,
`print -v`, `${X:=…}` and assignments that may not run; `<>` on stdin; `$((` in `${…}`; also under
`studio/videos/v`), `G1_REVIEW10_PASS` (the trap-cleanup idiom, `set -euo pipefail`, a `pushd` into a missing
folder, ordinary branches), the review-10 rows of `NESTED_OUT_DENY`, the class `G1Review10` (the snapshot's hooks,
options and functions), and `G1Review10` in `test_guard_walk.py` (known folders and values kept). Review 11's are
`G1_REVIEW11_DENY` (a function the command defined and then removed or replaced — `unfunction`, `unhash -f`,
`disable -f`, `unset -f --`, `-m` patterns, in another function, `eval`, `emulate … -c`, a sourced string, a name the
guard cannot read, a `DEBUG` hook — and the command so named after it; also under `studio/videos/v`),
`G1_REVIEW11_PASS` (values chosen by `if`/`&&`/`case` used by git, `cd`, `pushd` and script paths), the class
`G1Review11` (files the command sources, function tables after code the guard cannot read, choice values) and
`test_review11_choice_words` in `test_m1e.py` (the auditor reads each value). Review 12's are `G1_REVIEW12_DENY` (a
real write after a recursive copy with a chosen folder; `cd X || exit` where `exit` may not end the shell or X may
have been made; also under `studio/videos/v`), `G1_REVIEW12_PASS` (one recursive copy or extraction into a chosen
folder; `cd X || exit` blocks) and the class `G1Review12` (sourced files that define aliases or may move the shell,
the `**` listing after a source, `cd X || exit` from a folder without X, the message beyond 16 combinations).
Review 13's are `G1_REVIEW13_DENY` (`cd X || exit` with X missing is judged: the rest of the list is not skipped;
also under `studio/videos/v`), `G1_REVIEW13_PASS` and the class `G1Review13` (folders made by git, a sourced file or
a glob qualifier before `cd X || exit`; env files then `git commit`; files that may move the shell; the `**` listing
after any sourced file). Review 14's are `G1_REVIEW14_DENY` (a source after an extraction or a recursive copy; `~[name]`
operands; also under `studio/videos/v`), `G1_REVIEW14_PASS` and the class `G1Review14` (sourced files are not
followed: venv and env files then git as at HEAD; the round-14 attack files leave the folder unknown). Review 15's are
`G1_REVIEW15_DENY` (`~[…]` with `;`, `&&`, `$(…)`, backquotes or `${…}` in the brackets; also under
`studio/videos/v`), `G1_REVIEW15_PASS` and the class `G1Review15` (`popd`, `cd -`, `~-` and `$OLDPWD` after a source
go where they went at HEAD; relative paths after a source are read as at HEAD, from the repository root). Review 16's
are `G1_REVIEW16_DENY` (a `pushd` the guard cannot follow, then `popd`; also under `studio/videos/v`),
`G1_REVIEW16_PASS` and the class `G1Review16` (after a source, `cd -`, `popd`, `~-` and `$OLDPWD` reach the folder HEAD
knew, judged there as a known folder: wildcards, interpreter scripts, `ln` into `.git`, git path operands, also with a
hook defined after the source). Review 17's are `G1_REVIEW17_DENY` (`$OLDPWD` that is one of several folders; a source
and `cd -` inside a function; a shell string after a source and `cd -`; also under `studio/videos/v`),
`G1_REVIEW17_PASS` and the class `G1Review17` (`cd ~-`, `cd $OLDPWD`, `pushd ~-`, `env -C ~-` and `$OLDPWD/…` judged
in each folder `$OLDPWD` may hold; a source inside a function; git probes shared only by the readings of one command;
shell scripts, shell strings and second sources after a source and `cd -` / `popd` read in the folder HEAD knew).
Review 18's are `G1_REVIEW18_DENY` (HEAD's `$OLDPWD` after a source and a relative `cd`; `cd -` after a loop that
moves; a shell string run again by another command; also under `studio/videos/v`), `G1_REVIEW18_PASS` and the class
`G1Review18` (`source` and `.` as at HEAD: the attack rows HEAD refused — a function body run again after a later
source, `cd -` after moves only G1 follows — and the everyday rows HEAD passed — venv then `cd -`, `cd "$OLDPWD"` or a
saved `$PWD`, then commit; Studio names at the repository root after two returns; a nested `git checkout .` run by
two commands on a clean tree).
Review 19's are `G1_REVIEW19_DENY` and `G1_REVIEW19_PASS`, both run by the class `G1Review19` with its fixture
(the attack rows HEAD refused stay refused; a plain snapshot wrapper such as `gh` or `take` after a venv lets git
through; identical nested `git push` / commit checks shared within one call while `git checkout .` stays judged per
command). Its `test_autopushd_as_head` went with fix20, which removed the model of HEAD's folder after a source.

**fix20: the 0.0.26 guard as a backstop.** `stdo/guard/legacy/` is the guard of d2028cc (0.0.26), frozen;
`stdo/guard/backstop.py` runs it after this guard (`judge.decide` is `backstop.decide`; `judge.decide_g1` is this
guard alone, `run_finish=False` without effects). `structure_test.sh` checks that every legacy file is the 0.0.26 file
but for the FROZEN header and the two mechanical rewrites (an extra dot on `from ..` import lines, an extra dirname on
the `os.path.abspath(__file__)` lines), against a sha256 table taken with
`git show d2028cc:plugins/studio-plugin/skills/std/scripts/stdo/guard/<name> | shasum -a 256`. Regenerate the copy and
the table only if the backstop is ever based on another release. The same check holds the sha256 of the non-guard
`stdo` modules the 0.0.26 guard runs (`LEGACY_DEPS_HEAD`): an intended change to one of them goes into
`LEGACY_DEPS_CHANGED` with its reason, and the backstop's verification against 0.0.26 is run again.
`test_guard_backstop.py` covers the combination (since 0.1.4 the 0.0.26 guard judges only a call with a source, after
effects this guard cannot read, or that this guard stopped early on a limit: there a refusal of the 0.0.26 guard is
final; the 0.0.26 guard is not imported when this guard refuses or judges the call alone; its errors keep 0.0.26's
text; exactly one finish runs, the 0.0.26 one for those calls, checked against a 0.0.26 tree rebuilt from `legacy/`;
push and commit checks shared; the time limit before the hook's) and the parity list `BACKSTOP_PARITY` (rows of the
review corpora with and without a source, run in both snapshot modes). `HEAD_REFUSED_KEPT` and `HEAD_REFUSED_FUNCS`
in `test_guard_judge.py` list the rows 0.0.26 refused that this guard passes: `assertHeadRefusedKept` checks that
`decide_g1` passes them, and `decide` too when the 0.0.26 guard does not judge the call.

**0.0.28** (`SCRIPTS_VERSION` 25, pilot 3, fix-0028-plan §2–§14): `test_pilot3.py` covers the writer's frontmatter
lines of `state.py next --enter script` (`stdo/state/scriptlines.py`: the default narrator's cast block, each output's
aspect and maxDuration, the targetDuration range) and the narration check of the cast block; `record-brief --from`
forms; every s2v failure message (`s2vlint.Result.problems`); the targetDuration range (`claims.check.target_range`,
s2v's ±15 %); the S7 message, the skeleton's `from` and the on-screen hint; the `--source` excerpt checks with the
pilot's 緑の通路 line; the ② block's played sentences and `read:` line (also compared by the guard); `floor_text`;
`record-source --url` and the copy's source line; brand lines in the value block; `--ask-before` / `ask-before` (no deny
and no allow from the guard); the ③ and ④a question blocks. The m1e fixture `SCRIPT` has the default narrator's cast
block from the start (test_m1f's `CAST_BLOCK` replaces it at cast). The guard's §1 allows are tested with the guard.

**0.1.0** (`SCRIPTS_VERSION` 25, m1k-plan, marketplace registration): `test_m1k.py` runs the commands of
`docs/removing.md` as written (the shell blocks after `<!-- run: … -->`, read from the English document; the Korean and
Japanese documents must hold the same blocks) on an init fixture with two worktrees — the clone's plain-git hook is a
hand-written one Studio chained, the second worktree uses lefthook — under bash for one worktree and zsh (when
installed) for the other; a husky clone (`core.hooksPath=.husky`) whose tracked hook carries the Studio block, which step 2
must leave as it is; the refusals (staged changes, unpaired markers); a changed `.claude/settings.json` in the removal
commit. `test_guard_entry.PerfNoHarness` prints the guard's cost on a Bash `git status` in a
repository without a harness (the README's "Cost per call"; target p50 300 ms, fails above 900 ms, max printed only),
with the test's own interpreter. `structure_test.sh` requires the marketplace entry (same version, source and
description as plugin.json), the same number of `##` headings in the three READMEs, and no "in development",
"0.0.x", "not in the marketplace" or milestone names in the shipped documents (READMEs: outside `## Version notes`).

**0.1.1** (`SCRIPTS_VERSION` 26, fix-0029): `test_guard_entry.PerfSnapshots` times the same `git status` call as
`PerfNoHarness` with 13 generated shell snapshots in `CLAUDE_CONFIG_DIR` (`guard_base.perf_snapshot_text`: ~280 KB,
~10,500 function lines, 250 alias lines; the texts differ, the variant key is one), a `guard.py` subprocess (target
p50 160 ms, fails above 480 ms), and prints the in-process `judge.decide` too — with the original `snapshot.load` set
as `snapmod.load` and no loader passed, as in production (`snapshot_loader=` would leave the 0.0.26 guard without a
snapshot). G1's `snapshot.load` keeps two memos for one call (a line's `split_line` words; the Variant of a
byte-identical file) and reads the function-name pattern only on lines with a `{`; `tests/py/snapref.py` is the 0.1.0
parse (1cac964, imports rewritten), and `guard_base._load_both` compares every load the tests make with it
(`test_guard_snapshot.ParseParity` adds the edge texts, duplicate files and three loads in a row). The backstop wraps
the frozen `snapshot.split_line` once (`backstop._SPLIT`, only while `decide` runs, at most 4,096 lines; exceptions
never kept): `test_guard_backstop.SplitShared` uses real snapshot files and no injected `legacy_view`, and
`structure_test.sh` checks that the backstop changes exactly `push.check`, `commitrule.evaluate` and
`snapshot.split_line` of the frozen copy. `structure_test.sh` also scans the templates (every folder), the atoms and
the strings the scripts print (an AST scan outside `guard/legacy/`, plus the docstring lines the CLIs print as usage)
for milestone names, plan names and plan sections. `LEGACY_DEPS_HEAD` adds `commit/harness.py`, `commit/video.py` and
`credits.py` (kinds.registry imports the first two lazily; video.py loads credits.py), and
`test_guard_backstop.LegacyDepsClosure` runs the frozen paths in a subprocess and checks that every non-guard module
they load is pinned.

**0.1.2** (`SCRIPTS_VERSION` 27, fix-0102): `test_notes.py` covers teaching notes — `claims/notes.py` on what the fake
s2v gives (placement, plain text, the same-text rule, cards by position with the equal-count rule, scenes matched to s2v's by title — an underlined heading, an untitled
scene or a `# ` inside a multi-line comment refuses a marked card —, the walk read as CommonMark and remark-directive do
(indented and `::::` cards, backtick fences, HTML blocks of types 1, 6 and 7) and, under it, the root guard (the
mapped block must show the marked card's own text; no empty card of that name beside it),
the caps, `blocks` for the ① binding), the text rules and terms, `draft_problems` for `note` entries (the link cap
counts no notes), verify.json / verify.md without notes against `tests/py/verifyref.py` (0.1.1's two functions, copied
from f60349f), the copy check, a video with a marked card through the script check, the skeleton, verify, `shown 1`
and `approve 1` (the script refuses a recorded question without the note line, or without a question, and a malformed
record; a proxy approval is not checked), the router (`notes` in ①'s tuple only with markers), and the comment rule on
real s2v (`STUDIO_TEST_S2V`). `FakeMatchesReal` compares the fake's `screen_text` and sentence ids with real s2v's: the
fake now lists, as real inspect does, the frontmatter title, the speaking casts' names, every scene title (`heading`),
one `paragraph` entry per narration sentence and one entry per bullet item, table cell and markdown block, and drops a
top-level HTML comment (ending the paragraph above it). The drafts of `test_m1e`, `test_m1f` and `test_e2e_m1` judge
the first scene's title (`TITLE1`, listed by the claims map) and the speaker's name (a link) for that reason
(`test_m1e.rendered`). `test_agentmodel.py` covers `setup.py agent-model` (the script checks the question's line before
the answer is used up), the harness commit's `모델` line, `/std update` keeping the model, std-auditor.md as a protected
persona, and G1 and the 0.0.26 guard on the same calls. `structure_test.sh` pins the spawn rule of
`atoms/_contract.md` and that no document spawns a role with a model; `LEGACY_DEPS_CHANGED` lists `state/tuples.py`,
`state/router.py`, `state/schema.py` (① binds the notes) and `setup/labels.py` (`agent-model set`), and extends the
reasons of `commit/summary.py` and `commit/harness.py` — run `test_guard_backstop.py` again after a change there.

**0.1.3** (`SCRIPTS_VERSION` 27, fix-0103): `test_guard_regex.py`. `RegexBudget` collects every regex of
`stdo/guard/*.py` and `stdo/guard/legacy/*.py` (literals passed to `re.*`, `NAME_RE` strings, and the compiled patterns
the modules hold at import time), takes each one's ops from its call sites (none found: search, match and fullmatch),
and runs it through `drivers/regex_budget.py` on adversarial inputs at its call site's bound (4 KB; 512 characters for
the `ARITH_*` patterns behind `walk.ARITH_MAX`), each input under its own 2 s timer: under 50 ms, and no input whose time
grows more than 24-fold from 4 KB to 32 KB (linear is about 8, quadratic about 64; at least 5 ms at 32 KB, re-timed before failing). `ALLOW` lists the patterns the
budget does not hold, each with its reason (the frozen sed regex; both copies of the snapshot's function-line
patterns). `RegexEquivalence` checks each rewrite against its old text on 30,000 random strings. `HookDeadline` runs
guard.py past `limits.HOOK_DEADLINE`: in a plain folder on a sed script with 6,000 blank lines (G-LIMIT after 15 s,
started when the module loads so the other tests overlap it), and through `drivers/guard_deadline.py` with a 3 s
deadline and 5 s sleeps patched in (a slow G1, a slow deny write, a slow too-large write, a slow 0.0.26 guard on an
approval — no evidence —, a slow record after a pass and after a deny, a deadline swallowed once, no timer).

**0.1.4** (`SCRIPTS_VERSION` 27, fix-0104): this guard walks on after a `source` / `.` — `test_guard_backstop.SourceWalk`
covers the four classes of a source (`/dev/null` and an empty file do nothing; a readable file of at most 64 KB that
nothing earlier in the call may have written is walked in this shell, with the real `python3 -m venv` activate of
3.9 and 3.12 in `tests/fixtures/sourced/`; code the call gives the source is judged as a shell string and walked too;
anything else leaves its effects unknown, with the values before it kept as candidates), the routes that route a call
to the 0.0.26 guard (`ctx.sourced`, `ctx.unread`: a source anywhere, also in a body or hook the call defines, an EXIT
hook or a nested string; a snapshot function or hook this guard cannot read, that may change folder or that shadows a
command), the files that may be stale, sources nested three deep, the walk's own bounds (`limits.SOURCE_WALK_*`: a
file shaped like oh-my-zsh's diagnostics.zsh, eight heavy siblings, a nested chain, more than half the commands, file
probes or `cd`s — each class 4, never G-LIMIT), the walk on a copy and the message naming the file. The class N
evidence runs as tests: `Parity.test_parity` (on an unsourced row the final verdict is this guard's, a 0.0.26 refusal
it does not give is in `LEGACY_FALSE_UNSOURCED`, `HEAD_REFUSED_KEPT` or `HEAD_REFUSED_FUNCS`, its repositories and
warnings are this guard's; a sourced row stricter than the 0.0.26 guard is in `PARITY_G1_FIRST`),
`test_parity_g1_alone_after_source` (on every sourced corpus row this guard alone refuses what the 0.0.26 guard does,
but `LEGACY_FALSE_AFTER_SOURCE`, the evidence for removing the frozen guard), `test_parity_tools` (the file, web and MCP
tools on every fixture path) and `SnapshotParity` (each under its own snapshot: functions that change nothing — a
0.0.26 false refusal class —, `typeset +x`, every route to a name a function hashed or autoloaded, folder history after
an unreadable `pyenv`/`nvm`/`dyn` wrapper or eval, a function calling another by every spelling and order with the
whole function text searched, the kept refusal when one body names a Studio file, the no-snapshot PATH writes, the
auditor's own rows). `assertPassAfterSource` (test_guard_judge) passes a row HEAD passed after a source unless this
guard refuses it with the source made a no-op. `PerfSnapshots` has a snapshot-function call and eight calls in a 1.9
MB snapshot; `PerfSourced` times a sourced call (both guards). `structure_test.sh` checks that `backstop.decide` returns
a class N answer before the frozen guard is loaded and that G1's push and commit checks are its own modules.

**0.1.5** (`SCRIPTS_VERSION` 27, fix-0105): a path word this guard cannot read is also judged as its literal twins —
the word with every expansion that may be empty removed (`walk.may_be_empty`: `${X:?}`, a default with a name and the
number forms are not, unless SH_WORD_SPLIT is set explicitly or a `=`/`z`/`s` flag splits), and the folder of its
literal start plus any name — by judging the command again with each such word replaced (`judge.check_paths`,
`twin_readings`; all words of one kind at once, each twin value once, with its own file-system budget
`limits.TWIN_FS_CALLS` and `check_target` as the fallback past it; git, Studio's scripts and s2v keep their own rules).
The rows refused are `EMPTY_TAIL_DENY` and `SUBTREE_DENY` in `MustDeny` (both snapshot modes); the rows that must
still pass are listed in `EMPTY_TAIL_PASS`. Parity (fix-0105 §5): the 1,872-row corpus in both snapshot modes and
the pilot-3 replay give the same verdicts as 0.1.4.

**0.2.0** (`SCRIPTS_VERSION` 28, m2-plan M2a): `test_m2a.py` — `begin` per kind (`schema.KINDS`: scope and location;
an internal kind's video is local), begin's refusal of an id with a leftover `out`/`copy` folder in either location,
`state.py next`'s `scope:` / `out:` / `copy:` lines, the audience check at `record-brief` (a platform of the other
audience, and one without `audience`, are refused; `state_fixtures.write_platforms` writes public platform files for
`brief_ready`), the distributor's role output under `<sr>/local/copy/` for a local video only, a local video's renders,
stills, audition and copy under `<sr>/local/` (`approve_base.sub`), its backups with `_out/` and `_copy/`, local
`done` (no commit; proxy gates and credits → 4), check_scope's `internal` flag (class `internal` = level unknown +
flag; a public video's internal image becomes unusable without failing the source), board credits per scope, in-house
terms in internal copy, the new format templates (init leaves them out, `render.INIT_SKIP`; update offers each as
`optional`) and update's `audience` line. `structure_test.sh` checks that no
module but `stdo/vpaths.py` joins `out` or `copy` to the studio root (an AST walk) and that every kind has a format
template init installs; `stdo/vpaths.py` joins `LEGACY_DEPS_HEAD` (the frozen guard's commit check imports
`commit/video.py`, which uses it).

**0.2.1** (`SCRIPTS_VERSION` 29, m2-plan M2b): `test_m2b.py` — the rules block v1 and v2 (`title_max: null`,
`description_max_chars`, `hashtags_max: 0`, `chapters`, `link`) and the platform frontmatter (`rules.frontmatter`),
validate_copy following them, `platform.preview_lines` (one line per key; http sources, unknown aspects and layouts,
a mismatched name refused), `setup.py platform list | preview | apply | remove-preview | remove` with the person's
`플랫폼 <h12>` answer (a question missing a line → 6; refresh of an unchanged file changes only `checked`; remove
refused while a video in progress names the platform, `exclude-output` named only for a platform alone on its
output), the labels, init's kinds and platforms (each kind needs a platform of its audience; unpicked files are
`declined` in installed.json), update adding missing files and keeping a person's platform file (`person-platform`),
record-brief's unchecked warning and the `internal.md` lines, and the guard computing the preview lines from the
draft. `structure_test.sh` checks the two read-only allowed-tools entries and that platform.md runs them as spelled.

**0.2.2** (`SCRIPTS_VERSION` 30, m2-plan M2c): `test_m2c.py` — the output plan (`scriptlines.output_plan`): outputs
shared by name (a declaration counts only for the outputs the brief maps its platform to; an unnamed use takes
the most permissive declaration of the aspect), conflicting aspects (and layouts) under one name refused, a platform limit below the format's lower
bound (or too close to it for any targetDuration) refused, an output a platform does not accept, files without
outputs; record-brief refusing and recording nothing; the script lines for 9:16 (`subtitles: word`, `shot`, the
smallest limit, the targetDuration range under it); the script check's maxDuration and aspect; the look rules for 9:16
and 1:1. `--full`: real s2v, mock voice, fonts copied from the person's cache (a missing font fails rather than
downloads) — a 9:16 `shorts` snapshot equals `fullscreen` + `subtitles: word` and differs from plain `fullscreen`.
`state_fixtures.write_platforms` files declare outputs (`youtube` 16:9, `shorts` 9:16, one named after the
platform).

**0.2.3** (`SCRIPTS_VERSION` 31, m2-plan M2d): `test_m2d.py` — capture.py's rules (`stdo/capture/rules.py`): a
picture's host in `public_domains` or, for a public video, `capture.hosts`; https, no user, port, IP literal, query or
fragment, a path of at most 200 characters; the internal overlay's hosts and terms in the URL (percent-decoded too)
and the selector, read as `guard/web.py` reads them (compared), a missing overlay → 4; selector characters and size
bounds; the `capture` setting (host names only, protected: `설정 <h12>`, also in a config without the key). With the
fake s2v's new `capture` command (no network, no browser; scenario per URL and per attempt, a tiny PNG, image files
as `<sha>.<ext>`, exit codes and a signal): the command line capture.py builds, the files and `work/captures.json`, a
redirect to another host (apex → www, http, another domain) not usable, s2v exit 1 (the earlier picture removed),
exit 2 (a defect) and a signal (nothing recorded), `idle: false` kept with a warning, blocked hosts listed,
`S2V_CAPTURE_NO_SANDBOX` refused, one capture per video, links not followed, `source`/`recheck` refused (no URL
sources yet), and the source rules of `run.capture` (one retry with `--timeout 60`, unreachable twice or without a
contentHash). The fake's JSON keys, nested ones included, are a subset of s2v's `CaptureJson` (extract.ts:194-214,
kept in the test). `helpers.run_s2v` refuses `capture`. `test_guard_m2.py` — `s2v capture` in each accepted s2v form
(G-WRAP), `S2V_CAPTURE_NO_SANDBOX` set on s2v, lock.py and capture.py calls (G-ENV), writes and deletions of a video's
`assets/`, `work/captures/`, `work/captures.json`, `work/source-diff.txt` (and their `$X` twins, Write and Edit), each
also after a `source`; capture.py's own calls pass. `test_guard_autoallow.py` — capture.py `source | recheck | shot`
allowed without a prompt in the literal forms; a variable URL, an unknown option, `--url=`, a pipe prompt.
`test_m1b` NIT b copies a picture folder into `studio/videos/v/pics` (its `assets/` is protected now).
Review 1: build folders named `assets`/`captures` outside a video pass as at HEAD (`$OUT/assets`, `build/$N/assets`,
a loop, `/tmp/*/assets`) while `$X/videos/v/assets` is refused; an overlay subdomain of a public domain, terms
behind repeated percent-encoding or a zero-width space, encoded `?`/`#`, a selector starting with `-` and a final
address with a port or user are refused.
Review 2: a video id from `$(…)` or backticks before `assets`/`work/captures` is refused (`build/$(echo x)/assets` passes); a URL still encoded after three decoding rounds is refused.

**0.2.4** (`SCRIPTS_VERSION` 32, m2-plan M2e): `test_m2e.py` — URL sources with the fake s2v capture (no network).
`page.md` (`stdo/source/page.py`): golden bytes, every TextKind's prefix, each escape, the url comment and ruby moved
to `page-ruby.json`. `begin --url`: the source record; a host outside `public_domains`, an overlay term (also
percent-encoded), `--url` with `--source`, an internal kind, a fragment, a credential-like query key → 2, a missing
overlay → 4. `capture.py source`: the copy's files and `capture-files.json`; s2v exit 1, unsettled twice, no
contentHash, a redirect, a signal and exit 2 leave `work/source/` empty; blocked hosts and opaque frames reach the ①
line; refused after ①. record-source's URL branch: `frozen_hash` = contentHash, `copy_sha`, `capture`; a changed or
unlisted file and a missing record refused; `--url` refused; `collect.default_source` reads the copy without fetching
and refuses a copy that is not the recorded one. resolve_assets/check_scope: `img-<sha12>` ids, identical bytes
merged into `refs`, floors by host (public, third-party, unknown for `data:`), WebP and no bytes not usable, the
`src-<sha12>` copies, an overlay host's picture internal, an overlay source page or term refused, a missing overlay
→ 4. check_claims `--source`: ruby pairs against `page-ruby.json`. record-recheck: recorded, an old number refused, a
changed file → 1, unreachable recorded without a hash, the promotion line. The promotion: prev-1 and
`source-diff.txt`, nothing to promote twice, unknown/unreachable rechecks refused, a tampered recheck refused, a
promotion cut short (before the event; while moving the old copy) refused by `next`'s collect and plain record-source
and finished by a rerun, two promotions before an approval diff against ①'s copy (same bytes when written again),
analyst classes kept across a reordered page (and a new picture named). The folders kept (last three rechecks and
the promoted one; ①'s prev and the newest). The commit rule: no recheck, 23 h 59 min passes, 24 h 1 min refused,
unreachable, a changed page, approved after a promotion without another recheck; only in `--stage`, not the hook.
The source-diff gate prints `read: work/source-diff.txt` and its hash12 changes with the file. `test_guard_autoallow`
— `state.py record-recheck`, `record-source --from-recheck` and `begin --url` allowed without a prompt.
Review 1: a promotion cut short and then a same-hash recheck (the promoted recheck deleted by the folders kept) puts
the recorded copy back (also a plain record-source after ①); a same-host redirect to the overlay's internal source or
to a path with a term is not usable (source), unreachable (recheck) and refused by check_scope from the recorded final
address; a recheck dated in the future; U+2028/U+2029/U+0085 as line breaks and bidi controls dropped in page.md (no
forged claim line), `_` and `[` escaped; every line of a URL source's `## Ruby pairs` must be a page pair; page
pictures over the byte cap not usable, long data: addresses and alts cut; prevs of every language's ① kept;
`promoted_from` cleared by a new capture; `work/source/last-attempt.json` for an unusable source capture.
Review 2: the overlay's internal source pages match by a normalized prefix (query, fragment, `;params`, repeated `/`,
`index.html`, letter case and pages under it) at begin, source, recheck and check_scope; a second `## Ruby pairs`
heading is refused; a restore needs the prev's recorded content hash and capture record; a page picture's floor and
host come from its whole address.

**0.2.5** (`SCRIPTS_VERSION` 33, m2-plan M2f): `test_m2f.py` — board captures with the fake s2v capture (no network;
the fake's `png_hex` gives a shot other bytes). Floors (`shots.judge`): own host public, another host's page
third-party, a third-party picture inside the area (one outside does not count), a picture without a host unknown, a
frame inside unknown (third-party still wins); internal: a picture from an internal host, an internal source page (or
under one), a term in the final address, the page's title, text or an alt text inside the area. capture.py shot:
an internal source page refused before running, a final address on one or with a term not usable, a left `.tmp-*`
folder removed, the `floor:` and `credit:` lines. The script check takes a usable capture; the board check: no
credit, a third-party page without `public_ok`, a picture changed by hand or removed by an unusable run, an internal
capture in a public video and a missing overlay (closed side). credit-preview: ten lines with the capture's `source`
and `captured_at`, a draft with another source refused, a question without `captured_at` → 6; a shot taken again
(other bytes; the same bytes later) asks the credit again. ③: the `화면 캡처` line in the question (with the warning
and blocked hosts), approve refuses a question without it (6), the record binds the bytes, a shot taken again after
`shown` sends the work back to board. The board and script checks' inputs gain captures.json and public_domains only
when a capture exists. The commit stages the shown capture only (not an unused one, nothing under `work/`) and
refuses a capture other than ③'s.
Review 1: a commit through a clean filter (a fake git-lfs pointer in the index) stages the pictures; a host leaving
`public_domains` asks a capture's credit again at board and is refused at the commit (③ binds the floor); a term
with a soft hyphen or zero-width space in the page's text, title or alt is found; bidi controls are dropped from the
③ line.

**0.2.6** (`SCRIPTS_VERSION` 33, m2-plan M2g): `test_e2e_m2.py` — what pilot 4 does, end to end with the fake s2v (its
`capture` too: no network, no browser) and the real guard, hooks and git, every gate and credit by a person: the person
checks the shipped `youtube-shorts` rules (`setup.py platform preview` / `apply` through a refresh draft) and adds
`reels` (`platform add`: the agent's draft, every preview line and the hash in the `플랫폼` question; at most 60 s) sharing
the 9:16 output `shorts`; an `sns` video from a page on the site's own domain (`begin --url`, `capture.py source`, the
`원본 페이지 캡처` line in the ① question, the page picture `assets/src-<sha12>.png` classed and credited); the script lines
for `shorts` (`maxDuration` 60 = the smaller limit; reels allows 60 s, Shorts 180 s); board with one capture of the page
in place of a picture (`capture.py shot`, ten credit lines with its `source` and `captured_at`, the `화면 캡처` line in ③);
one render; copy for both platforms (Shorts with the source link line, reels without title or link) and one ④b question
for both (the first `shown` prints `other scopes not shown yet`); `capture.py recheck` and the `record-recheck` line it
prints; the commit (both pictures, no `work/`), `done`. The fake's calls show three captures, all of the page, none
without the sandbox. `make_harness.make(answers=…)` takes init's kinds, platforms and public domains. Every call goes
through the guard and must not be refused; which calls it allows without a prompt is not checked here (a call that would
prompt runs as if allowed) — that is `test_guard_autoallow`'s.
Review 1: reels allows 60 s, so the shared output's `maxDuration` is 60 (no longer the format's 90).
