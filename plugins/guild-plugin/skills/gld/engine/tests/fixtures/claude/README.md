# fake-claude fixtures

## Recordings — `f1/`, `f2/`

Stream-json of the stage-1 confirmation experiments, Claude Code **2.1.323**:

| File | Run | What it shows |
|---|---|---|
| `f1/A*.jsonl`, `B*.jsonl`, `C*.jsonl` | F1 permission-mode combinations (SCRUB on/off, dontAsk / default + `--permission-prompts none` / manual) | init `permissionMode` (`default` under SCRUB), allowed vs refused writes/reads, `permission_denials`, the Bash `env` dump (values redacted) |
| `f1/Dw.jsonl`, `De.jsonl` | F1 supplements | `Write(...)` deny has no effect, `Edit(...)` deny blocks the Write tool |
| `f2/r1–r3.jsonl` | F2 `--setting-sources ""` | builtin plugins (3) / agents (5) / skills (17), default tool set, no CLAUDE.md |
| `f2/r4.jsonl` | F2 + `--disable-slash-commands` | skills and slash commands empty; the rendered PreToolUse hook blocks `git commit -n` (exit 2) |
| `f2/r5ctl.jsonl` | control run with `user,project,local` sources | user plugins and their skills load |

They are **normalised copies** (`normalize.py`): the experiment scratch root became
`/tmp/gx-exp`, the home `/Users/user`, and every `NAME=value` line of an `env` dump became
`NAME=<redacted>` (one recording carried a session messaging token). Event order and all
other fields are unchanged, so a replay is the original session. Re-record when the CLI
version changes (scope §6.2) and run `normalize.py` again.

## Real leader sessions — `leader/real-2.1.323/` (stage 2, V13)

Real `leader.call()` sessions (haiku / low) for plan-gate, done-gate, blocked and a new
collaborator comment, plus two direct CLI probes of the schema enforcement — README there.
The `l-*` scenarios with a structured output replay these streams.

## Scenarios — `scenarios/*.json`

Read by `tests/fakes/bin/claude` (full format in its docstring). Short form:

```json
{"format": 1, "description": "…",
 "stream": "../f2/r4.jsonl",            or "events": [ … ]
 "init_from_argv": true,                init tools / cwd / model / session_id from argv
 "init": {…}, "result": {…},            merged into those events
 "structured_output": {…},              result["structured_output"]; absent = none
 "drop_result": false, "truncate_after": null,
 "line_delay_s": 0, "hang_after": null, "hang_s": 0,
 "actions": [{"at": "start|before_result|end", "op": "write|append|delete|mkdir|symlink|git", …}],
 "stderr": "", "exit_code": 0}
```

| Scenario | For |
|---|---|
| `ok-judge.json` | a judge writes its output and returns a valid work result |
| `init-lists-differ.json` | raw F2 r1 init (default tools, 17 skills) — was S6 `init-mismatch`; since FC decision D the session runs on |
| `no-structured-output.json` | R5 |
| `budget-reached.json` | S3 — the result subtype is an **assumption** until U6 records the real one |
| `no-output-hang.json` | I13 no-output limit |
| `review-block.json` | R1 / R8 |
| `developer-commits-control-file.json` | C1 |
| `l-*.json` (stage 2) | leader sessions. Extra key `"leader": {"example": <contract example name or null>, "expect": "accepted" \| <LeaderFormatReason> \| <StopReason> \| "session-limit"}` — the example's `fill` renders the answer schema the structured output fits (`test_fakes.test_leader_scenarios`); `expect` is the engine verdict session A asserts. V1 set: plan-gate plan / rerun / close / plan-with-gap, blocked escalate / rerun, done-gate approve, no structured output, budget reached, leader writes a file. Session A added: `l-plan-gate-rows-not-covering`, `l-done-gate-approve-unmet`, `l-done-gate-approve-include`, `l-done-gate-rerun-implement`, `l-new-comment-continue`, `l-new-comment-continue-with-effect`, `l-new-comment-adds-requirement-design`, `l-writes-control-file`. Stream (V13, Q5): the real leader recording of the same situation in `../leader/real-2.1.323/` (the scenario's `structured_output` replaces the recorded one); `l-no-structured-output` and `l-budget-reached` keep `../f2/r4.jsonl`, a real stream recorded without `--json-schema` whose result has no `structured_output` key — the shape of a session that gave none. The Q4 end-to-end leader sessions (`tests/test_e2e_stage2.py`, `tests/test_scenario_stage2.py`) are built in the test (`leader_scenario`), not files here |

| `t-*.json` (stage 3) | role results: extra key `"role": {"example": "result-work-s3" \| "result-review-s3", "expect": "done" \| "blocked" \| <CheckFailedReason> \| <OutputFormatReason> \| <StopReason>}`; leader answers (`t-l-*`): `"leader": {…}` as for `l-*` with the stage-3 schemas. `expect` is the verdict the owning session (C roles, D leader) asserts — for a role scenario of an evidence / frozen run it is the verdict of the run that FOLLOWS. The stream of every `t-*` is an older recording (no stage-3 schema was recorded yet — V18) |

`structured_output` as the result key is confirmed against the real CLI 2.1.323: role
results by the P4 canary (`canary/real-2.1.323/`), leader answers by V13
(`leader/real-2.1.323/` — the result event carries the answer object at `structured_output`,
the same object as the StructuredOutput tool input; `result` holds its JSON text).
