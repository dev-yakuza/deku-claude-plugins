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

A Studio commit is: `check_commit.py --stage <kind> [<target>]` → AskUserQuestion whose text contains the **summary
line `--stage` printed, verbatim** (`커밋 <tree12> | 변경 N | 삭제 M | 보호 키: … | 없음`, plus deleted agents), the
staged paths, and the fixed option `커밋 <tree12>` → `git commit -m …`. Protected setting changes (`보호 키`) are only
for the person — the sandbox proxy mode cannot commit them. Harness commits (`--stage harness`) never delete
`config.json`, `charter.md`, the protected personas or Studio's scripts: **taking Studio out of a repository is the
person's removal procedure**, done in a terminal (remove the installed hook and blocks, `.claude/studio`,
`.claude/agents/std-*` and the `.gitignore` block, then `git commit --no-verify`) (never `-a`, a pathspec, `--amend`, `--no-verify`, `HUSKY=0` /
`LEFTHOOK=0` / `SKIP`, `-c core.hooksPath` or a `git config` change of hooks or aliases).

Approval-type commands work only from a Claude session with the guard's evidence: a person answers
the session's question; there is no direct terminal path (intended — 00-plan §3.4).

**How to ask for an approval** (the guard reads the answer from the transcript — m0d2-plan §2–§4):
- Ask in the **main session** (never from a subagent), with AskUserQuestion. Show the artifact and its hash.
- Each question's text is unique within the call and **contains the hash** of its fixed option (`승인 <hash12>`,
  `거부 <hash12>`, `재고정 <hash12>`, `제외 <hash12>`, `커밋 <tree12>`; `해제 <video> <lang> <held>` names the video
  and language). The fixed label is one of the options; a free-text "Other" answer is never an approval.
- Right after the answer, **in the same turn**, run the command **alone** (optionally after `cd <repo> &&`), as
  `python3 .claude/studio/scripts/state.py …` or `git commit -m …`, without environment prefixes. If the person
  writes anything before the command runs, ask again. An answer is used once. Only an answer Claude Code marks as
  the person's (`permissionDecision` source `user_*`) counts — an answer filled in by a hook never does. Never send the question and the
  approval command in the same message (the guard cannot always tell them apart when the transcript is written late).
- Guard rules: `G-EVIDENCE` (no usable answer: ask again), `G-MAIN` (main session only), `G-PROXY` (`--proxy`
  outside the sandbox proxy mode), `G-COMMIT` / `G-COMMITFORM` (stage again with `--stage`; plain `git commit`),
  `G-HOOKOFF` (hooks must stay on), `G-PLUMB` (no plumbing or GitHub API writes), `G-PUSH` (machine-only or internal
  files in the pushed history), `G-WEB` (INV5), `G-VERSION` (the repository's scripts are another version).
