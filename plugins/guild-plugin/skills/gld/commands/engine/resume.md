# RESUME — stage-1 engine (`/gld resume <N>`)

**The one way to answer the engine.** A stopped Issue (`needs_human`) waits for a human
answer; an engine that died mid-step (killed, machine slept) is restarted from that step.
Resume works on the same machine only (the engine state lives in `~/.gld/`).

`$1` = Issue number.

> **Bash**: one command per Bash call (`<<SKILL_DIR>>/commands/atoms/_bash_rules.md`). Never read
> `engine.log` or `~/.gld/records/` into the conversation.

---

1. Resolve `owner/repo` (its own Bash call):
   ```bash
   gh repo view --json nameWithOwner -q .nameWithOwner
   ```
2. Read what waits (read-only, inside the sandbox is fine):
   ```bash
   python3 -I <<SKILL_DIR>>/engine/engine.py status --repo OWNER/REPO --issue N
   ```
   - `no engine state` → nothing to resume; suggest `/gld dev N`. Stop.
   - `engine running` → an engine is already on it; follow `commands/engine/dev.md` section 2. Stop.
   - `the engine died while … was running` → resume WITHOUT an answer (step 3 without
     `--answer`/`--note-file`).
   - `stopped: needs_human …` with `answers: …` → ask the human exactly as
     `commands/engine/dev.md` section 3 describes (reason, step, the leader recommendation when
     shown, allowed answers, optional note).
   - `stopped: needs_leader …` (stage 2, `waiting for the leader`) → do not ask: resume WITHOUT
     an answer — the engine calls the leader again (an `--answer` is refused).
3. Answer and restart the engine **outside the sandbox** (`dangerouslyDisableSandbox: true`
   unless the engine pattern is in `sandbox.excludedCommands` — `commands/engine/dev.md` step 1.3):
   ```bash
   python3 -I <<SKILL_DIR>>/engine/engine.py resume --repo OWNER/REPO --issue N --answer ANSWER --note-file NOTE_FILE
   ```
   `close-as-decided` also needs `--close-reason completed|not-planned` (the note file is the
   closing comment). `--step` also names the step of a `skip` answer, `--template` another template
   for `plan` (stage 3 — `commands/engine/dev.md` section 3). A `not-reproduced` stop and a `plan-gate` stop
   whose note starts `bug-without-repro-red:` are answered as `commands/engine/dev.md` section 3 ("A bug Issue
   keeps its red reproduction") says — the engine never concludes "already fixed"; the human does. Exit 4 → the answer was refused (nothing changed): show the line and ask
   again. Exit 3 → locked. Exit 0 → continue with `commands/engine/dev.md` section 2 (wait).

`--allow-test-change` (stage 4, with `--answer rerun --step STEP` and `--note-file`; one per file) is a
human's permission to change a base test file — `commands/engine/dev.md` section 3 says when. **Write the
file names in the note** (with why each may change): the developer of the rerun learns them from the note's
`leader-decision.md` only — the list itself goes to the engine's checks and the PR, not to the session. A member
of a sprint that stopped is answered here like any other Issue; then `/gld sprint run` goes on.

`--pr-review` (after the PR) and `--dismiss` with `--reason-file` (overrule a review's block) are the
two resumes without an answer — `commands/engine/dev.md` section 3 says when they apply.

The note goes to the next attempts' `leader-decision.md`; `issue.md` is rebuilt from
GitHub at every resume. The engine applies §4.4-3 on its own: anything changed by hand
since a review or run step makes that step run again before the PR.
