# SPRINT (router)

**Run a sprint: plan what to take, develop it unattended, watch it, close it with a retro.**
A sprint is an *iteration container* — an issue set with a goal, an execution order and a
capacity — not a mode of autonomy. This file only routes; each subcommand is its own file.

`$1` = subcommand · `$2…` = that subcommand's own arguments.

> **Bash**: `<<SKILL_DIR>>/commands/atoms/_bash_rules.md`. State/labels: `_handoff.md`.
> Membership · dependency graph · base decision: `<<SKILL_DIR>>/commands/atoms/_sprint_dag.md`.
> **Output language**: all human-readable output in `config.language` (`_handoff.md` Section K).
> Machine tokens (`guild:*` labels, marker names, `state:` values, failure classes) stay ASCII.

---

## Routing

Read `<<SKILL_DIR>>/commands/sprint/$1.md` and execute its instructions, passing `$2, $3, …`
as **that file's** `$1, $2, …` (shift by one).

| `$1` | Action |
|---|---|
| `plan` | `commands/sprint/plan.md` — choose this sprint's issues, order them, create the tracking Issue |
| `run` | `commands/sprint/run.md` — develop the members unattended to PRs |
| `daily` | `commands/sprint/daily.md` — read-only status; merge order; what is stuck |
| `retro` | `commands/sprint/retro.md` — metrics, capacity calibration, evolve, close the sprint |
| *(empty)* | route to **`daily`** — the most-used read-only action. A bare invocation must never start something destructive |
| a number or comma-list (e.g. `837,840`) | do **not** run. Report: *"`/gld sprint run 837,840`으로 실행하세요"* — this was the pre-sprint-subcommand form (`help.md`), and silently mapping it to `run` would start an unattended run the user did not ask for |
| `--readiness` | do **not** run. Report: *"`/gld sprint run --readiness`"* — the flag moved onto `run` |
| anything else | report the unknown subcommand and print the valid list above |

---

## Common definitions (all subcommands)

### The sprint container
- **One sprint = one GitHub Issue** labelled `guild:sprint` (the *tracking Issue*). Its body
  holds the goal, the capacity judgment and the **member table**; comments hold everything that
  changes. Full contract: `_sprint_dag.md` Section A.
- **Sprint state = that Issue's open/closed.** Open = active, closed = retro done. No new state
  vocabulary.
- **The tracking Issue never runs the spine.** `guild:sprint` is an identity marker like
  `guild:child`, not a stage — it is excluded from the canonical stage derivation
  (`_handoff.md` Section A), and `dev`/`resume`/`batch` refuse to develop it.
- At most one sprint is expected to be open. Two or more → ask the human which one; concurrent
  sprints are not supported (a member in two sprints has no defined base).

### Markers on the tracking Issue
| Marker | Written by | How |
|---|---|---|
| `<!-- guild:sprint:plan -->` | `plan` | body, **immutable** after creation (guarded by `plan-hash`) |
| `<!-- guild:sprint:run -->` | `run` supervisor (**shell**) | comment, in-place replace — the run ledger |
| `<!-- guild:sprint:daily -->` | `daily` (**LLM**) | comment, in-place replace |
| `<!-- guild:sprint:retro -->` | `retro` (**LLM**) | comment, appended once per sprint |

⚠ **LLM and shell writers follow different procedures.** An LLM writer inherits the
read-then-splice pattern *and its truncation check* (`_execute_spine.md` Step 4): a preview-
truncated read must not be written back. A shell writer cannot be truncated but also cannot
perform that recovery — its procedure is in `sprint/run.md`.

### Two termination axes
- **run finished** — the queue is empty. Every member ended as done, needs-human, failed or
  blocked. **Not all of them have to be done.**
- **sprint finished** — run finished **and** no member PR is `OPEN`, and none is `CLOSED`
  unmerged. Only then is a retro meaningful; `daily` judges both.

### What the human does
Guild plans, develops and reports. **The human reviews and merges every PR** — nothing merges
unattended (INV1). During a run the human reviews concurrently in their own checkout; the
supervisor never touches it. The command for that is **`/gld review <PR>`**, and `daily` names it
on the merge-order line — reviewing is not a side activity here, it is the half of the loop
Guild does not do.

### Return (this router's own)
`plan`/`run`/`daily`/`retro` each define their own return line; the router passes it through
unchanged. Its own returns are for the paths that never reach a subcommand:
`FAIL: unknown subcommand <$1> — valid: plan | run | daily | retro` ·
`OK: use \`/gld sprint run <issues>\`` (the legacy number-list and `--readiness` forms).
⚠ None of these is a spine token: this file never returns `OK ADVANCE` or `OK PAUSE`
(`_handoff.md` Section D — those belong to stage commands).

### Capacity is judged, then calibrated
`plan`'s leader decides how many issues to take (it does **not** ask the human), and `retro`
compares plan against outcome and recommends the next number, which is stored in
`config.json` → `sprint.capacity` after per-item human approval.
