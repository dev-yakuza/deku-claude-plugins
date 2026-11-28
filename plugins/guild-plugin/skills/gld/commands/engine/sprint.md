# SPRINT — the engine's supervisor (the CLI behind `/gld sprint run`)

**Stage 4: a sprint is fixed engine code.** `engine.py sprint run` reads the tracking Issue's member
table, checks that the base is green, and runs one member after the other as a child engine
(`engine.py dev --foreground --mode unattended`) — the same run as `/gld dev`, the same settings,
the same gates. It judges by exit code, `state.json`, named log codes and lock files; it reads no
label and no text. The human side (questions, warnings, reports) is `commands/sprint/run.md`.

> **Bash**: one command per Bash call. **Never** read `supervisor.log`, `engine.log` or any file under
> `~/.gld/records/` into the conversation. `sprint run` starts **outside the sandbox** like `dev`
> (`commands/engine/dev.md` step 1.3); the others only read.

```bash
python3 -I <<SKILL_DIR>>/engine/engine.py sprint run --repo OWNER/REPO --tracker T --checkout REPO_ROOT
python3 -I <<SKILL_DIR>>/engine/engine.py sprint run --repo OWNER/REPO --tracker T --checkout REPO_ROOT --window W
python3 -I <<SKILL_DIR>>/engine/engine.py sprint status --repo OWNER/REPO --tracker T --wait 540
python3 -I <<SKILL_DIR>>/engine/engine.py sprint status --repo OWNER/REPO --tracker T --json
python3 -I <<SKILL_DIR>>/engine/engine.py sprint report --repo OWNER/REPO --tracker T --json
python3 -I <<SKILL_DIR>>/engine/engine.py sprint check --repo OWNER/REPO --tracker T
python3 -I <<SKILL_DIR>>/engine/engine.py sprint stop --repo OWNER/REPO --tracker T
```

| Command | What | Exit |
|---|---|---|
| `sprint run` | `--checkout` the main checkout; `--window` `HH:MM-HH:MM` or `none` (not given: the previous run's); `--allow-red-base` (a human's word: start although a named command is red on the base); `--take-over` (a human's word: another machine's run is gone). Detaches | 0 started · 3 a supervisor of this repository runs · 4 refused · 2 usage |
| `sprint status` | `--json`, `--wait` SECONDS (until the supervisor ended): run state, halt, one line per member | 0 running / finished · 3 · 4 halted or died |
| `sprint report` | `--json` (required): per member outcome, block, cause, stop (reason, detail, `cause` engine / issue / label), cost, leader decisions, the paths of its procedure, log and facts files, the kept worktree and its size; counts, total cost, stop causes | 0 · 4 not run here |
| `sprint check` | the member table, plan hash and order as the engine reads them, and the members `run` would not start (`blocked:` an epic, an open pull request that closes it, `gld/<N>` on the remote without records here, `guild:done` on the open Issue; `note:` a child of an epic); writes nothing | 0 · 4 |
| `sprint stop` | asks the supervisor to end after the running member (a waiting one ends within a minute) | 0 · 4 none running |

**Outcomes of a member in one run**: `done` (PR exists) · `closed` (closed as decided) · `stopped`
(waits for a human — `/gld resume N`) · `blocked` · `skipped-locked` (a human's engine is on it) ·
`refused` (the engine did not start it) · `failed`. **Blocks**: `dep-stopped` · `dep-failed` ·
`upstream` (the root member is named) · `dep-not-done` · `dep-pr-closed` · `dep-pr-ambiguous` ·
`dep-not-planned` · `dep-unmerged` (no stacking in this repository) · `base-unresolved` (a fact
could not be read, the branch and its PR differ, or the dependency's branch changes control
files) · `quota` · `repo-busy` (another Issue's engine held the repository for four hours) ·
`remote-branch-exists` (a leftover `gld/N` on the remote) · `unsupported-epic` · `attended-run` (a
human's `dev` started it — finish it with `/gld resume N`).
**Halts**: `base-red` · `boundary` · `marker-unwritable` · `plan-hash-mismatch` · `other-host` ·
`signal` · `engine-error` (`commands/sprint/run.md` Phase 4 says what to do).

**Running it again** starts nothing that is `done` or `closed`, continues what crashed or was
blocked, leaves every stopped member to the human — except a quota stop whose reset time has passed,
which it reruns (logged as `sprint`). It decides from the Issues' states and GitHub, not from the
earlier run's record; only the window is inherited.

**Engine incidents and records (readiness R1).** A needs_human stop the engine probably caused — an engine-caused
stop code (`codes.stop_cause` = `engine`, not a quota wait), an uncaught supervisor exception, or a leader that
escalated with `env-problem` / could not answer — leaves an incident under `~/.gld/incidents/<slug>/` (signature,
engine version and commit, the stop's log lines, secret-free copies of that run's session transcripts). The same
signature again only counts up. `sprint status --json` carries the list as `incidents`; `/gld sprint daily` shows it
and nothing else does.

| Command | What | Who calls it |
|---|---|---|
| `incidents list [--json]` | every incident with `fix_status` (`unfixed` · `fixed` · `recurred`) against the fixed-defects list shipped with this engine | daily (through `sprint status --json`) |
| `incidents prune [--apply] [--json]` | removes the `fixed` ones (without `--apply`: says which) | retro Phase 7 |
| `records prune --repo O/R --tracker T [--issue N …] [--apply] [--json]` | removes `records/` and `tmp/` of members whose pull requests are all merged or closed (an incident's records stay) | retro Phase 7, rows the human approved |
| `records stale [--days 90] [--json]` · `records stale --apply --pick O/R#N …` | lists Issue records untouched for 90 days · removes the picked ones (checked again) | `/gld status` |

**Stacks.** A member on an unmerged dependency starts from the dependency's PR head and its PR
targets `gld/<dependency>` (a draft on a squash / rebase-only repository whose plan says
`squash-sync`): merge the lower one first. After each merge `/gld sprint sync` brings the upper ones level.
