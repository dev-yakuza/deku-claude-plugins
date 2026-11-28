# canary fixtures (U12)

`sample.jsonl` — a hand-written role-canary stream in the event shapes recorded with Claude
Code 2.1.323 (F1 `B`, F3 `sbdeny` / `sb2`): one probe per refusal kind the judge must
recognise, plus one allowed read.

| tool_use | Probe | Evidence in the stream |
|---|---|---|
| `toolu_c1` | Read tool on a worktree secret (`.env-gx-canary`, F3) | error result "denied by your permission settings" + `tool_result_meta` reject |
| `toolu_c2` | Read tool on the attempt's own `in/` | non-error result containing the bait token |
| `toolu_c3` | Write tool outside the worktree | `system/permission_denied` + `result.permission_denials` |
| `toolu_c4` | Bash `cat` of `~/.ssh/…` | error result "Operation not permitted" (sandbox), permission accept |
| `toolu_c5` | Bash `curl` to a host outside the allow-list | error result "CONNECT tunnel failed, response 403" (srt proxy) |

Paths are a synthetic layout under `/tmp/gx-c` (`canary.canary_layout` shape). The Bash
probe `toolu_c4` uses the P4 command form (`cat -- <path> >/dev/null` for a read that must be
refused).

## `real-2.1.323/` — the first paid canary (P4, 2026-11-23)

Recorded by `engine.py canary` against the real Claude Code 2.1.323 (haiku, effort low),
normalised (`normalize.py` rules: layout root → `/tmp/gx-c`, home → `/Users/gx-user`):

| File | What |
|---|---|
| `work-items.json`, `judge-items.json` | the probe list of each role class (`canary.canary_items`, real home) |
| `work-<n>.jsonl`, `judge-<n>.jsonl` | the stream of session n (one batch of ≤ 40 probes) |
| `work-<n>.ids`, `judge-<n>.ids` | the probe ids of session n (own `in/` probes name `runs/canary/<n>/in/`) |

Both records passed (work 182 probes / 5 sessions, judge 87 / 3). `test_scenario_stage1.
RealCanaryRecording` re-judges them, checks the real init (with `StructuredOutput`) and the
real `result.structured_output`. Re-record when the CLI version or a render template changes.
