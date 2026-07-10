# DESIGN (stage)

**Stage: design.** Roles: **architect ∥ tester** (leader orchestrates). The architect drafts the skeleton; the tester writes test cases from the acceptance criteria **without seeing the skeleton** (bias-free — plan §4, §16 C4). They run in parallel. Invocable directly (`/gld design <issue>`) or via `/gld dev`.

`$1` = Issue number. Returns a Section D line.

> **Bash**: `_bash_rules.md`. State/handoff: `_handoff.md`.

---

## Step 0 — Preflight
As the leader, follow `_preflight.md` **Medium tier** (items 1–4). Item 4 loads the `<!-- guild:analyze:output -->` comment (feature list + **acceptance criteria**). If analyze output is missing → the stage is out of order; return `NEEDS_CONTEXT: analyze output not found for #$1` (leader should run analyze first).

Validate `$1` is an Issue (not a PR). Ensure entry label `guild:design` if invoked directly.

Ensure the spec dir exists for file-based handoff:
```bash
ls docs/specs/$1
```
(If absent, the role sub-agents create `docs/specs/$1/` when writing their artifacts.)

## Step 1 — Spawn architect and tester in parallel
As the leader, spawn BOTH role sub-agents in a single message (two Agent tool calls) so they run concurrently and independently (`claude -p`-style isolation is unnecessary in M1 — in-process Agent is fine, plan §12):

**Architect** (skeleton first):
- `subagent_type`: `general-purpose`, `model`: `sonnet`, `description`: `architect design #$1`
- `prompt`:
  > Adopt the persona in `.claude/agents/architect.md`. You are designing Issue #$1 for this repo. Read the analyze output (`<!-- guild:analyze:output -->` on the Issue) and `docs/standards/`. Produce the **skeleton**: module boundaries, data flow, extension seams, file structure. Write it as a FILE to `docs/specs/$1/skeleton.md` (do not paste it back). Decide whether this needs a **multi-PR split** (child issues) and note it. Return EXACTLY one `>>> RESULT <<<` line per `_handoff.md` Section C (`DONE: skeleton at docs/specs/$1/skeleton.md — <one-line>`), or `BLOCKED:`/`NEEDS_CONTEXT:`/`FAIL:`.

**Tester** (test cases from AC only — do NOT read the skeleton):
- `subagent_type`: `general-purpose`, `model`: `sonnet`, `description`: `tester cases #$1`
- `prompt`:
  > Adopt the persona in `.claude/agents/tester.md`. Read ONLY the acceptance criteria from the analyze output (`<!-- guild:analyze:output -->`) — do NOT read the architect's skeleton (bias-free test design). Write test cases (normal + edge + failure paths) as a FILE to `docs/specs/$1/test-cases.md`. Return EXACTLY one `>>> RESULT <<<` line per `_handoff.md` Section C.

## Step 2 — Collect handoff, arbitrate
Read both RESULT lines:
- Both `DONE`/`DONE_WITH_CONCERNS` → proceed. Record any concerns.
- Any `BLOCKED`/`NEEDS_CONTEXT` → as the leader, intervene: supply the missing context and re-invoke that role, or if unresolvable return `NEEDS_HUMAN: <one-line>`.
- Any `FAIL` → return `FAIL: <reason>`.

If the architect flagged a **multi-PR split**: in M1, note it in the design output and (optionally) create child Issues labeled `guild:child` with a `Parent Issue: #$1` reference (temp-file `gh issue create --body-file`). Full child orchestration is light in M1 — record the split for the humans; the primary path is single-PR.

## Step 3 — Post design output + durable spec
Post the design summary comment (temp-file pattern):
- Marker: `<!-- guild:design:output -->` … `<!-- /guild:design:output -->`.
- Contents: design summary, pointer to `docs/specs/$1/skeleton.md`, pointer to `docs/specs/$1/test-cases.md`, PR-split decision, any concerns. `<details>` preflight trace.

The durable artifacts already live in `docs/specs/$1/` (written by the roles) and are committed with the PR.

## Step 4 — Transition + return
```bash
gh issue edit $1 --remove-label "guild:design" --add-label "guild:execute"
```
Return:
```
>>> RESULT <<<
OK ADVANCE: execute
```
Other returns: `NEEDS_HUMAN`, `NEEDS_CONTEXT`, `FAIL` (do NOT transition on these).

## Hard rules
- **Tester independence**: the tester MUST NOT see the skeleton (spawn prompt enforces this). This is the anti-bias core of design.
- Artifacts pass as **files** (`docs/specs/$1/`), never pasted into RESULT lines (context protection).
- Design is read-only against source code — it writes only spec files + the Issue comment + label.
