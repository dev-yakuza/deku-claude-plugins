# Contract (shared rules)

Status: contract only (M0). The handoff details (prompts, model tiers, loops, signals) are
written with M1.

## A. Roles

- The **producer** is the main session: it runs the flow, runs every deterministic command
  (script2video, the Studio scripts), judges results and asks people. It is not spawned.
- Other roles are spawned with their persona (`.claude/agents/std-*.md`) and receive **files
  only** as input; they write only the outputs listed for them in `_stages.md`.
- Roles never approve, never commit and never run script2video approval commands.

## B. Result contract

<!-- studio:result-contract -->
> Every spawned role ends its reply with exactly one result line:
> `>>> RESULT <<< <STATUS>: <one-line summary>` where `<STATUS>` is one of
> `DONE` · `DONE_WITH_CONCERNS` · `BLOCKED` · `NEEDS_CONTEXT` · `FAIL`.
> `DONE_WITH_CONCERNS` lists each concern on its own line before the result line.
> `BLOCKED` and `NEEDS_CONTEXT` say what is missing; the producer decides, never the role.
<!-- /studio:result-contract -->

## C. Guard

<!-- studio:guard-refusal -->
> **When the guard refuses something (INV9)**: stop. Do not reach the same effect another way
> (another command, a script, editing the file directly, removing environment markers, retrying
> with different flags). Tell the user what was refused and why, and ask how to proceed.
<!-- /studio:guard-refusal -->

## D. Exit codes of the Studio scripts

Each script has its own table; a code means only what its script's table says.

**`state.py`**

| Code | Meaning | Producer |
|---|---|---|
| 0 | done (`next`: the line says what to do; `--enter`: go) | continue |
| 1 | failed (script errors from s2v inspect, a malformed input, a hash s2v could not compute) | fix the cause, then retry |
| 2 | usage or setup (no harness, unknown command, schema, flock unsupported) | a Studio defect or setup: stop and report |
| 3 | `next --enter`: an earlier stage must be redone | go to the stage `next` names |
| 3 | `record-brief`: approved outputs/platforms would be removed | ask the person; removing them is `exclude-output` |
| 4 | waiting for a person (held state, s2v version changed, hash_version; `loop` on a held language) | ask the person |
| 5 | the video's state lock is busy | wait and retry |
| 6 | no usable evidence of a person's answer (`approve`, `reject-source-diff`, `repin`, `exclude-output`, `unlock`) | ask with AskUserQuestion (fixed label), then run the command once |

**`check_commit.py`** (`--staged` is the pre-commit hook's check) **and `hooks.py`**

| Code | Meaning | Producer |
|---|---|---|
| 0 | passed · staged (`--stage` prints the question label `커밋 <tree12>`) · range clean · hook installed/valid | continue (after `--stage`: ask the person with that label, then `git commit`) |
| 1 | refused: a check failed (local/ path, mixed commit, outside the allow-list, not what `--stage` prepared, video approvals, ignore blocks) · hook cannot be installed or is not valid | fix what the message says, stage again, ask again |
| 2 | usage or setup (not a repository, no harness, config unreadable, git failed, Python < 3.9) | a Studio defect or setup: stop and report |
| 3 | not supported yet (commit kinds `harness` M0f · `video` M1 · `actor` M3b; nothing Studio's to finish in a merge/rebase) | stop and report |
| 4 | a person decides (internal overlay missing or changed · proxy approvals · a hook block proposed for a team-shared file) | ask the person |
| 7 | the Studio guard has not run in this Claude Code session | ask the person to enable the Studio plugin; never remove the session markers |

**`lock.py` and s2v**: 73 / 74 = machine / character busy → `held:lock` / `held:actor`; otherwise the child's code.

A Studio commit is: `check_commit.py --stage <kind> [<target>]` → AskUserQuestion with the staged paths and the
fixed option `커밋 <tree12>` → `git commit` (never `-a`, a pathspec, `--amend` or `--no-verify`).

Approval-type commands work only from a Claude session with the guard's evidence: a person answers
the session's question; there is no direct terminal path (intended — 00-plan §3.4).
