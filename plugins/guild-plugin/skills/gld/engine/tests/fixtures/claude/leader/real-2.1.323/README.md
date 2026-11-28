# real leader sessions — V13 (stage 2, Q5, 2026-11-24)

Recorded against the real Claude Code **2.1.323** by the V13 experiment
(`design/guild/24-redesign/stage2/experiments/v13/`, record `stage2/experiments/V13.md`):
the engine's own `leader.call()` on the `tests/test_leader.py` worlds, with only
`defaults.MODEL_EFFORT["leader"]` = haiku / low and the session budget lowered to $0.30 —
the argv, settings, schema render and answer check are the engine's.

Normalised by the `../../normalize.py` rules: the temp roots → `/tmp/gx-l`, the home →
`/Users/gx-user`, the CLI config dir → `/Users/gx-user/.claude-cfg`, `NAME=value` lines redacted.

| File | What |
|---|---|
| `<name>.jsonl` | the session's stream-json, unchanged except the normalisation |
| `<name>.schema.json` | the exact `--json-schema` value the engine sent (render drops `$schema` / `$id`) |
| `<name>.call.json` | situation, kind, step, the `Allowed`, the id lists (from `in/leader-input.json`), the checklist AC ids, the engine's verdict (`LeaderResult` fields), the argv flags, model / effort |
| `probe-<situation>.jsonl` / `.schema.json` | direct CLI probes with the same schema: a schema violation first, then a valid answer |

| Recording | Situation | Real answer (accepted by `check_answer`) | Covers |
|---|---|---|---|
| `plan-gate-rerun` | plan-gate | rerun `analyze`, R2 not covered | string enum `step` non-null; `plan` / `close` / `recommendation` null |
| `plan-gate-plan` | plan-gate | plan `feature` | `plan` object side of `object \| null` |
| `plan-gate-escalate` | plan-gate | escalate, recommendation close-as-decided | `recommendation` object with `step` null |
| `done-gate-rerun` | done-gate | rerun `implement`, AC 1 / 2 unmet, D1 followup | integer enum `ac` (JSON integers 1, 2) |
| `done-gate-nodisc-rerun` | done-gate, no discovery | rerun `implement` | the empty D list drops `discoveries` (property and `required`) |
| `blocked-escalate` | blocked | escalate, recommendation rerun `analyze` | common envelope only |
| `new-comment-escalate` | new-collaborator-comment | escalate, comments 9101 / 9102 | integer enum comment `id` |
| `probe-plan-gate` | (CLI probe) | first `answer: "merge"`, row `R9` → refused; then close-as-decided | the CLI's StructuredOutput tool validates enums; `close` object side |
| `probe-done-gate` | (CLI probe) | first `ac: "1"` and `ac: 3` → refused; then escalate | integer type and integer enum enforced by the CLI |

`tests/test_leader_recording.py` pins them: the schema rendered today equals the recorded one
(re-record when a leader schema template or the render changes, scope §6.3), the real init
passes the judge check, the real `result.structured_output` passes `check_answer`, the CLI
refused what the engine refuses, and each recording replays through the fake claude into the
recorded `LeaderResult`. The stage-2 `l-*` scenarios replay these streams (their own
`structured_output` replaces the recorded one).
