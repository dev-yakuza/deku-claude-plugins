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
| 1 | `record-brief`: the computed length is outside the format, a chosen claim is not in `source.md` or not in the copy | the strategist chooses again |
| 3 | `record-brief`: approved outputs/platforms would be removed | ask the person; removing them is `exclude-output` |
| 3 | `record-brief` · `stage-done script`: the source's images are not checked, or `assets.json` is not the recorded one | finish `/std source` |
| 3 | `record-source`: the writing or an image it shows is not committed | ask the person to commit their writing; never change or commit it yourself |
| 4 | waiting for a person (held state, s2v version changed, hash_version; `loop` on a held language) | ask the person |
| 5 | the video's state lock is busy | wait and retry |
| 6 | no usable evidence of a person's answer (`approve`, `reject-source-diff`, `repin`, `exclude-output`, `unlock`, `credit`; `credit`'s `fields-not-shown`: the question missed one of the eight lines) | ask with AskUserQuestion (fixed label), then run the command once |
| 1 | `credit-preview` · `credit`: the draft entry is incomplete, its floor is not the image's, a line is over 200 characters, or it changed since the preview | fix the draft, preview and ask again |

**`check_commit.py`** (`--staged` is the pre-commit hook's check) **and `hooks.py`**

| Code | Meaning | Producer |
|---|---|---|
| 0 | passed · staged (`--stage` prints the question label `커밋 <tree12>`) · range clean · hook installed/valid | continue (after `--stage`: ask the person with that label, then `git commit`) |
| 1 | refused: a check failed (local/ path, mixed commit, outside the allow-list, not what `--stage` prepared, video approvals, ignore blocks) · hook cannot be installed or is not valid | fix what the message says, stage again, ask again |
| 2 | usage or setup (not a repository, no harness, config unreadable, git failed, Python < 3.9) | a Studio defect or setup: stop and report |
| 3 | not supported yet (commit kinds `harness` M0f · `video` M1 · `actor` M3b; nothing Studio's to finish in a merge/rebase) | stop and report |
| 4 | a person decides (internal overlay missing or changed · proxy approvals · a hook block proposed for a team-shared file) | ask the person |
| 7 | the Studio guard has not run in this Claude Code session | ask the person to enable the Studio plugin; never remove the session markers |

**`setup.py`** (plugin-only: `init` · `config` · `narrator` · `update`)

| Code | Meaning | Producer |
|---|---|---|
| 0 | done (JSON on stdout) | continue (a change to committed files: the harness commit next) |
| 1 | refused: a check failed (`--expect` is not this change's hash, the plan changed since it was shown) | show the person again |
| 2 | usage or setup (no harness — everything but `init`; a value or path that is not allowed; `--proxy`) | fix the command, or stop and report |
| 3 | refused: a harness (or an earlier install's traces) exists for `init`; the folder name is taken; the value is already set; an update that would raise `s2v.min_version` while videos are in progress | tell the person |
| 6 | no usable evidence of the person's answer (`config set` of a protected key or `s2v.path`, `narrator set`, `update apply`) | ask with AskUserQuestion (fixed label, the change line), then run the command once |

**`check_claims.py`** (`--narration`: the script stage; without it: verify)

| Code | Meaning | Producer |
|---|---|---|
| 0 | passed (the check result is written; verify also wrote `verify.json` · `verify.md`) | `stage-done` |
| 1 | failed: the listed problems | script: the writer again · verify: `state.py loop <video> verify`, then fix and check again |
| 2 | usage or setup (no harness, no video, no script, no s2v path) | fix the command, or stop and report |

**`check_assets.py --actors`** · **`check_tts.py`** · **`audition.py`** (the voice section, M1f)

| Code | Meaning | Producer |
|---|---|---|
| 0 | passed (the check result is written) | `stage-done` |
| 1 | failed: the listed problems (`check_tts`: a `retry:` line names the lines to synthesize again) | fix, retry, check again |
| 2 | usage or setup (no harness, video, script or s2v path; `check_assets` without `--actors`; `audition.py` without ffmpeg) | fix the command, or stop and report |

**`validate_copy.py`** (M1h)

| Code | Meaning | Producer |
|---|---|---|
| 0 | passed (the check result is written) | `stage-done copy` |
| 1 | failed: the listed problems (an unchecked platform file: the person checks it — U-M1h) | fix the copy, or ask the person |
| 2 | usage or setup (no harness, video or script; the platform is not in the brief) | fix the command, or stop and report |

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
- Each question's text is unique within the call and **contains the hash** of its fixed option. A question about
  a video **starts with the video id in brackets, literally `[<video>]`** (e.g. `[v1] ① 대본 — … · hash
  3f2a9c0d1e4b`); the guard checks the brackets too, so `[v1]` never stands for `v10`. The fixed labels:
  `승인 <video> <hash12>` · `거부 <video> <hash12>` (a source diff) · `재고정 <video> <hash12>` · `제외 <video> <hash12>` ·
  `해제 <video> <lang> <held>` · `커밋 <tree12>`; later milestones add `출처 <video> <hash12>` (CREDITS),
  `중단 <video> <lang>` (abandon), `사내설정 <sha12>` (overlay), `설정 <hash12>` (protected settings, the s2v path,
  the narrator) and `갱신 <hash12>` (update). Copy the label exactly as the command printed it. The fixed label is one
  of the options; a free-text "Other" answer is never an approval.
- Right after the answer, **in the same turn**, run the command **alone** (optionally after `cd <repo> &&`), as
  `python3 .claude/studio/scripts/state.py …` or `git commit -m …`, without environment prefixes. If the person
  writes anything before the command runs, ask again. An answer is used once in the whole repository (every worktree shares the record). Only an answer Claude Code marks as
  the person's (`permissionDecision` source `user_*`) counts — an answer filled in by a hook never does. Never send the question and the
  approval command in the same message (the guard cannot always tell them apart when the transcript is written late).
- Guard rules: `G-EVIDENCE` (no usable answer: ask again), `G-MAIN` (main session only), `G-PROXY` (`--proxy`
  outside the sandbox proxy mode), `G-COMMIT` / `G-COMMITFORM` (stage again with `--stage`; plain `git commit`),
  `G-HOOKOFF` (hooks must stay on), `G-PLUMB` (no plumbing or GitHub API writes), `G-PUSH` (machine-only or internal
  files in the pushed history), `G-WEB` (INV5), `G-VERSION` (the repository's scripts are another version).

## E. Known limits of the Bash guard

The guard reads each Bash call before it runs; it cannot be complete, and deliberate forgery is outside Studio's
threat model. What it does not see is backed by the pre-commit hook, the commit checks and the person's gates:
- **Interpreters** (python, node, …) run code the guard cannot follow; where it notices Studio paths or terms it
  refuses (`G-OPAQUE`), otherwise it lets the code run.
- **Background jobs started in earlier calls** can change files between the guard's check and a later command; for
  plain (non-recursive) writers the guard judges the paths as they are when it checks. Archive extractions and
  recursive copies are judged by their destination folder for this reason.
- **Tool flags it does not model** (mostly GNU-only options) are judged by the paths it can read, not by what the
  flag changes.
Work with literal commands, one step per call, so the guard can check what runs.
