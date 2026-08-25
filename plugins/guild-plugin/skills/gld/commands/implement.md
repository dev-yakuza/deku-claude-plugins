# IMPLEMENT (stage: execute variant)

**Stage: execute, variant for `type:feature`.** Roles: **developer** (fills the skeleton via TDD) with **tech-lead conformance check**, plus any **conditional specialists / gate reviews** the leader convenes (security/infra/i18n/dba/analytics/performance — Step 3.5). Invocable directly (`/gld implement <issue>`) or via `/gld dev` (auto-selected when the Issue is `type:feature`, or has no `type:` label — see `dev.md`'s default-to-feature rule). The spine is identical to `debug`/`refactor` (execute → test); only the *developer's task shape* differs — a feature is **built via TDD from the tech-lead's skeleton**.

`$1` = Issue number. Returns a Section D line.

> **Bash**: `_bash_rules.md`. State/handoff: `_handoff.md`.
> **Output language**: all human-readable output in `config.language` (`_handoff.md` Section K); sub-agent prompts carry that instruction.

---

## How to run this stage

Run **Steps 0–6 of `atoms/_execute_spine.md`** — Step 0 preflight (incl. the label read and the **`guild:children`** split-parent guard) · Step 1 spawn developer · Step 2 verify evidence · Step 3 tech-lead conformance · Step 3.5 conditional specialists/gates · Step 4 arbitrate · Step 5 PR · Step 6 transition + return — filling its Section A slots with the values below. Nothing about the spine changes for this variant; everything that *is* feature-specific is in this file.

## Slot values (`type:feature`)

**DESIGN INPUT** — load the design output (`<!-- guild:design:output -->`), the **skeleton** (`docs/specs/$1/skeleton.md`), and the test cases (`docs/specs/$1/test-cases.md`). If design output or skeleton is missing → `NEEDS_CONTEXT: design/skeleton not found for #$1`.

**BRANCH + RESUME PROBE** — a **feature** branch, e.g. `feature/#$1-<slug>`. The resume test-run shows **which cases already pass vs still fail** (where TDD left off).

**DEVELOPER TASK SHAPE** — `description`: `developer implement #$1`. Body inserted into the spine's Step 1 prompt:

> Implement Issue #$1 on the current branch. Read the skeleton (`docs/specs/$1/skeleton.md`) and test cases (`docs/specs/$1/test-cases.md`) — these are your inputs, passed as files. Do TDD: make the tester's cases fail (red), implement to green, then refactor. **Resume**: keep the already-green work, pick up the TDD cycle where it stopped, complete the rest.

RESULT extras: the raw test summary line and the branch name.

**EVIDENCE RULE** — none beyond the spine's base cross-check: the raw runner output must show green, and it wins over the developer's self-report.

**CONFORMANCE CHECKS** — inserted into the spine's Step 3 prompt:

> Review the implementation on the current branch against your skeleton (`docs/specs/$1/skeleton.md`) and `docs/standards/architecture.md`. Check: did it honor the module boundaries, seams, technical direction, and design intent?

**SIGNAL AREA** — `--area "<the target dir/file being implemented>"`; typical `--role` set `<tech-lead|security|infra|…>`.

**PR SUMMARY** — summarizes the change + test evidence. (**Unattended**: the spine's Step 5 also appends the `## 무인 결정 로그 (GLD_UNATTENDED)` decision log — `_handoff.md` Section H.)

## Hard rules

This variant adds none of its own — the four spine-common hard rules in `_execute_spine.md` are exactly this stage's rules:

- **Verify evidence is mandatory** (`_handoff.md` Section E): no "green" claim without the raw runner output; raw output wins over self-report.
- **No verification weakening** (INV2): the developer must not delete/skip/weaken tests to pass. If a test must change, it requires an explicit, justified reason surfaced to the human.
- **Conformance is by the tech-lead, not self-review** (roles don't self-check).
- Artifacts/inputs pass as files; RESULT lines stay one line.
