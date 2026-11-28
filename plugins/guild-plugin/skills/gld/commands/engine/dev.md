# DEV — stage-1 engine (`/gld dev <N>`)

**Stage 1 of the redesign: the gld engine runs the Issue, not this conversation.** The
engine (`<<SKILL_DIR>>/engine/engine.py`) reads a fixed procedure (start procedure +
feature template), starts every role as its own `claude -p` session, runs the named
checks under `srt`, judges by facts it collects itself, and opens the PR. This
conversation only **starts the engine, waits, and relays stops to the human**. There is
no leader in stage 1: every place a leader would decide stops as `needs_human`, and the
human answers through the resume flow below.

`$1` = Issue number.

> **Bash**: one command per Bash call, no `&&`, no `$(...)` (`<<SKILL_DIR>>/commands/atoms/_bash_rules.md`).
> **Never** read `engine.log` or any file under `~/.gld/records/` into the conversation — the
> status command prints the short summary that is needed (§7.3: engine logs do not flow
> into the conversation).

---

## 1. Start the engine

1. Resolve `owner/repo` (its own Bash call) and hold the literal value:
   ```bash
   gh repo view --json nameWithOwner -q .nameWithOwner
   ```
2. Resolve the repository root (the main checkout) the same way and hold it:
   ```bash
   git rev-parse --show-toplevel
   ```
3. Start the engine **outside the conversation's sandbox** (F4 — inside it the engine's own
   srt self check fails with `listen EPERM … srt-mux`). If the user settings list the
   pattern `python3 -I <<SKILL_DIR>>/engine/engine.py:*` under `sandbox.excludedCommands`,
   run it normally; otherwise run this ONE Bash call with `dangerouslyDisableSandbox: true`
   (the human approves it once):
   ```bash
   python3 -I <<SKILL_DIR>>/engine/engine.py dev --repo OWNER/REPO --issue N --checkout REPO_ROOT
   ```
   The command detaches the engine and returns at once with exit 0, printing the engine
   log path. Exit 3 = another engine holds this Issue or this repository (one `/gld dev`
   per repository at a time) — report it and stop. Exit 2 = a usage error in the line above.

## 2. Wait for the engine

Repeat this Bash call (each waits up to 9 minutes; read only its short output) until the
output no longer says `engine running`:
```bash
python3 -I <<SKILL_DIR>>/engine/engine.py status --repo OWNER/REPO --issue N --wait 540
```
Its exit code is the engine's once it has finished. Stage 4, a new Issue: its own stage labels (`guild:analyze` … `guild:qa`) left by an earlier run without engine
records here are taken off and the work starts from analyze — the engine labels it again itself.
A `- notice:` line (stage 4: the Issue is a child of an
epic — `guild:child`; it runs as a single Issue) is relayed to the human once, as it is, with the parent's
number and state it names; it asks nothing and changes nothing.

| exit | meaning | what to do |
|---|---|---|
| 0 (and `engine running`) | still running | call it again |
| 0 | finished — the PR line shows the pull request | report the PR and stop |
| 10 | stopped `needs_human` | run section 3 |
| 11 | stopped `needs_leader` (stage 2 only): the leader could not be reached — a quota stop past the wait limit, an infra failure of its session, or a judgment fact the engine could not collect | do **not** ask the human for an answer; tell them the leader will be called again and run `resume` without `--answer` (section 3, "Stage 2") once the cause is gone (quota reset, network) |
| 4 | the engine refused to start (self check, the other channel's `gx:` label, closed Issue, settings, a leftover worktree; stage 4 also a leftover `gld/N` branch or open PR on the remote without engine state here — removing it is the human's; and `unsupported-epic`: the Issue is an epic (`guild:children`) — say *"에픽은 아직 지원하지 않음 — 자식을 하나씩 `/gld dev <자식>`"*, a `resume` of it is refused the same way; `open-closing-pr`: an open pull request on any branch already closes the Issue and this machine has no engine record of it — name the pull request(s) from the line and say the human reviews and merges or closes them first, the engine does not start a second one; `done-unconfirmed`: the Issue carries `guild:done`, is open, and no open pull request closes it — ask the human to close it when it is done or to remove `guild:done` to develop it again) | show the `refused:` reason from `status --json` (`last_events`) and stop. A self-check failure means the engine ran inside the sandbox: register the pattern from step 1.3 or approve the unsandboxed call, then run `/gld dev N` again | <!-- promote: other -->

## 3. A stop: the resume flow (same conversation)

The status output shows the stop reason, the step and the allowed answers. **Attended**
(default): put the reason, the step and the allowed answers to the human with
`AskUserQuestion`, plus an optional note. **Unattended** (`GLD_UNATTENDED=1`): do not ask —
report the stop and end; the Issue stays stopped until a human runs `/gld resume N`.

A `canary-failed` stop means the boundary canary of this CLI version and render template (I9)
did not pass. The engine runs a missing one itself (haiku, cents, `canary` lines of log.jsonl),
so the stop's note says which probe failed — and the
engine never repeats a failed one. It is never answered with a rerun of the step alone: show the
human the note, tell them that the PAID role canary has to run again by hand (outside the
sandbox, as in step 1.3; with the repository's `.claude/guild/config.json` as its config file
when that has sandbox exceptions; it writes `~/.gld/canary/`), and only with their go-ahead run
```bash
python3 -I <<SKILL_DIR>>/engine/engine.py canary
```
Exit 0 = every canary passed → `resume … --answer rerun`. Exit 4 = a canary FAILED: a
security boundary did not hold — report the `FAIL` lines and stop (do not resume).

Answers in stage 1 (the human sits in the leader's seat, §6.3):
- `rerun` — run the stopped step again (or an EARLIER step given with `--step`); after
  `on-fail-exceeded` or a soft-budget stop it is allowed once per Issue.
- `continue` — after a new collaborator comment: go on from the same step.
- `plan` — after the plan-rule stop: go on with the fixed feature template.
- `escalate` — leave the Issue stopped; the human takes over outside the engine. It is the
  only answer for `absolute-limit`, `rule-unfillable`, `format-mismatch`, `stable-label`.

**Stage 2** (the engine runs with the leader — `status` shows `leader decisions`): the leader
answers every judgment itself (plan-gate, done-gate, blocked / failure stops, soft budget, new
collaborator comments) inside the engine. A human is asked only when the stop is
`needs_human`; then the status output also shows the **leader recommendation** (answer, step,
reason, note) and, when the leader could not answer, `the leader could not answer: <code>`.
Put the recommendation first in the `AskUserQuestion`, then the other allowed answers — the
human may pick any of them (they sit in the leader's seat; the engine's narrowing of the
leader's answers does not apply to them). Stage-2 answers on top of the stage-1 ones:
- `plan` — the plan-gate: go on with the feature template (the engine writes revision 2 of the
  procedure).
- `close-as-decided` — the plan-gate, and (stage 3) a `blocked` stop before any developer step has
  run: the work is already decided or done; needs `--close-reason
  completed|not-planned` and the rationale as `--note-file` (posted as the closing comment —
  the engine closes the Issue, skips the rest, makes no PR).
- `approve` — the done-gate: go on to the PR.
- `replan` — go back to the plan-gate (only after the plan step is done).
- `rerun` at the plan-gate re-runs `analyze`; at the done-gate any earlier role / run step
  (`--step`).
A `needs_leader` stop is never answered by a human: `resume` without `--answer` calls the
leader again (an answer is refused, exit 4).

**Stage 3** (issue types and risk handling): the same flow, with these stops on top. `status` also
lists the role requests and how they ended, irreversible changes, retry raises, included fixes,
follow-ups and (public repository) the security findings - relay those lines with the stop.
- `irreversible-change` - a human decides, the leader is never asked: show each change (category,
  code or path, step). `continue` approves exactly what is shown (the same change is not asked
  again, a new one is); `rerun` runs the step given with `--step` again without that change (put
  the instruction into the note).
- `step-add-limit` (after a leader escalate) - roles asked for more steps than the plugin allows:
  `continue` declines the surplus requests. The limit itself cannot be raised for one Issue.
- `step-removal-request` (after a leader escalate) - a role asked to drop a step: `continue`
  declines it.
- `skip` — step-removal-request only: skip the step given with `--step` (only a step the catalog
  added and that has not run; a mandatory gate or a template step cannot be skipped).
- `plan` at the plan-gate takes the template of the analysis type; `--template` names another
  (`feature`, `bug`, `refactor`, `refactor-net`, `safety-net`) - always as it is, without
  adjustments. A stop note `templates unusable: …` says which ones this repository cannot run
  and why (usually a missing path rule or role file).

**A bug Issue keeps its red reproduction** (readiness E4, both modes; the leader never answers these):
- `plan-gate` with a note starting `bug-without-repro-red:` — the Issue is a bug Issue (a bug label such as
  `type:bug`, or an analysis of it recorded `type: bug`) and the leader planned (or was offered only) a template
  without a `repro-red` step, e.g. `safety-net`. The leader's wish is shown as its recommendation. Show the note
  and ask: `plan --template bug` (keep the reproduction), `plan --template <other>` (the human accepts the switch),
  `rerun` (analyze again), `close-as-decided` (already done — with `--close-reason` and the rationale), `escalate`.
- `not-reproduced` at `repro-red` — the reproduction test was not red twice on the code before the fix after every
  reproduce retry. The engine does **not** decide why (already fixed / the test is wrong / not reproducible here).
  The note lists the reproduction test, the run results and the commits on the recorded base since the Issue was
  written that touched a related file (the full list is `not-reproduced.md` in the Issue's engine records). Relay
  the note as it is and ask: `close-as-decided --close-reason completed` (already fixed — the rationale names the
  commit; the engine closes the Issue, no PR), `rerun --step reproduce` (reproduce again — the note says what the
  reproduction missed), `rerun --step analyze`, or `escalate`. There is no `continue`: a fix without a red
  reproduction is not offered.

**Stage 4**: while an Issue waits for a human it carries the label `guild:needs-human` (the engine sets and
removes it). One more human-only answer, never the leader's and never yours to suggest:
- **A human allows a base test file to change** — at a `blocked` or `on-fail-exceeded` stop of a
  procedure whose `verification-frozen` run refused it: `rerun` of the work step with one
  `--allow-test-change` per file (no glob) and the human's reason as `--note-file` — the note names the
  files and why (the rerun's developer reads it as `leader-decision.md`; nothing else tells it). Only the content of
  exactly those files may change; deleting, renaming or a safety-net file stays refused, the
  test-change review still runs, and the PR lists the files as allowed by a human. Offer it only after
  the human said which file and why.
```bash
python3 -I <<SKILL_DIR>>/engine/engine.py resume --repo OWNER/REPO --issue N --answer rerun --step STEP --allow-test-change PATH --note-file NOTE_FILE
```

After the pull request (stage 3), only when the human asks for it:
- **PR reviews**: `--pr-review` (no answer) — the engine fast-forwards to commits people pushed on
  the PR branch, hands the collaborators' new reviews and comments to the leader and updates the
  SAME pull request when a step has to run again; nothing new → it ends at once. Branches that
  diverged stop as `remote-diverged`.
- **A human overrules a review**: when a review's block stopped the Issue (`on-fail-exceeded` at
  that review step, `needs_human`), `--dismiss` with the review step id and `--reason-file` with
  the human's own reason (it is shown in the PR). It counts for that HEAD only; a red run, a
  mandatory check or a boundary stop can never be dismissed. Never suggest it yourself — offer it
  only after the human said they disagree with the review.
```bash
python3 -I <<SKILL_DIR>>/engine/engine.py resume --repo OWNER/REPO --issue N --pr-review
```
```bash
python3 -I <<SKILL_DIR>>/engine/engine.py resume --repo OWNER/REPO --issue N --dismiss STEP --reason-file REASON_FILE
```

Write the human's note (if any) to a new file in a temporary folder with the Write tool,
then answer (outside the sandbox, as in step 1.3):
```bash
python3 -I <<SKILL_DIR>>/engine/engine.py resume --repo OWNER/REPO --issue N --answer ANSWER --note-file NOTE_FILE
```
Add `--step STEP` for a `rerun` from an earlier step, `--close-reason completed|not-planned`
for `close-as-decided`, and `--reason CODE` (a leader reason code: `real-defect`,
`upstream-gap`, `transient`, `env-problem`, `needs-human-decision`, `already-decided`,
`acceptance-met`, `fits-template`, `analysis-gap`, `assumption-corrected`,
`comment-no-effect`, `high-complexity`, `repeated-failure`, `other`) when the human gives one.
Exit 4 = the answer was refused (the line says why — nothing changed); ask again. Exit 0 = the
engine continues: go back to section 2.
