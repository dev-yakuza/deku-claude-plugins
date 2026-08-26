# REFACTOR (stage: execute variant — refactor)

**Stage: execute, variant for `type:refactor`.** Roles: **developer** (behavior-preserving transform) with **tech-lead conformance** (structure improved *and* behavior preserved), plus the always-on external auditor and any conditional specialists (Step 3.5). Invocable directly (`/gld refactor <issue>`) or via `/gld dev` (auto-selected when the Issue is `type:refactor`). Same spine as `implement` (execute → test); the developer's task shape differs — code is **transformed without changing behavior**, so the **existing tests are the safety net** (no new feature test).

`$1` = Issue number. Returns a Section D line.

> **Bash**: `_bash_rules.md`. State/handoff: `_handoff.md`.
> **Output language**: all human-readable output in `config.language` (`_handoff.md` Section K); sub-agent prompts carry that instruction.

---

## How to run this stage

Run **Steps 0–6 of `atoms/_execute_spine.md`** — Step 0 preflight (incl. the label read and the **`guild:children`** split-parent guard) · Step 1 spawn developer · Step 2 verify evidence · Step 3 tech-lead conformance · Step 3.5 external auditor (**always**) + conditional specialists/gates (`_handoff.md` Section G — a refactor touching a hot path → performance; schema → dba; etc. A gate `BLOCKED` blocks advancement, as does an auditor `BLOCKER`) · Step 4 arbitrate · Step 5 PR · Step 6 transition + return — filling its Section A slots with the values below. Nothing about the spine changes for this variant.

## Slot values (`type:refactor`)

**DESIGN INPUT** — load the design output — for a refactor the design **is the target structure** (design = 목표 구조). Load `docs/specs/$1/skeleton.md` (the target shape). Missing → `NEEDS_CONTEXT: design/target-structure not found for #$1`. (The spine's Heavy-tier preflight covers ⑥ knowledge + the target-dir survey.)

**BRANCH + RESUME PROBE** — a **refactor** branch, e.g. `refactor/#$1-<slug>`. The resume test-run confirms **all existing tests are still green on the partial work** → continue the transform, don't restart.

**DEVELOPER TASK SHAPE** — `description`: `developer refactor #$1`. Body inserted into the spine's Step 1 prompt:

> Refactor Issue #$1 on the current branch toward the target structure (`docs/specs/$1/skeleton.md`). **Resume**: CONTINUE the transform from the committed partial state (tests green), do not restart. **Behavior-preserving — this is the core constraint**:
> - The **existing tests MUST stay green throughout** — run them before and after; behavior does not change. They are your safety net.
> - Do **NOT** add features, change observable behavior, or **weaken/delete/skip tests** (INV2). If a test asserted an *implementation detail* that the refactor legitimately removes, surface it **explicitly with justification** in your RESULT — never silently drop it.
> - Prefer many small behavior-preserving steps, tests green at each.
> Capture the raw runner output (all green) as evidence.

RESULT extras: the raw test summary (all green), **what structural improvement was made**, and the branch.

**EVIDENCE RULE** — **all existing tests must be green** (there is no new feature test). A refactor that turns a test red has changed behavior (or broke something); that is not-done, loop back. If the developer changed any test, verify the justification is real — **implementation-detail only, not a weakened assertion**.

**CONFORMANCE CHECKS** — inserted into the spine's Step 3 prompt:

> Review the refactor on the current branch against the target structure (`docs/specs/$1/skeleton.md`) + `docs/standards/architecture.md`. Check TWO things: (1) is the **structure genuinely improved** toward the target (not churn)? (2) is **behavior preserved** — no functional change, and **no test weakened/removed** except a justified implementation-detail test? Your `BLOCKED` line names the non-conformance *or* the behavior/verification change.

A tech-lead `BLOCKED` here means **structure not improved, behavior changed, or a test weakened** — that, or a test going red, is the Step 4 loop-back trigger for this variant.

**SIGNAL AREA** — `--area "<the refactored file/area>"`; typical `--role` set `<tech-lead|performance|…>`. A **weakened-verification** reversal (a refactor that quietly removed/weakened a test, caught here) is exactly the INV2 signal worth capturing.

**PR SUMMARY** — what structure improved, the behavior-preserved statement, and the existing-tests-green evidence.

## Hard rules

Spine-common rules apply — **read `_execute_spine.md`'s "Hard rules" section directly; it is the authority and it is longer than this summary**, notably the auditor rules (3.5a never gates by itself and never edits, and the mutation check around it — `git diff --numstat --no-renames <mb>` + `git status --porcelain -uall`, compared before/after — is mandatory on **every** path — a standalone run of this variant that skips them loses the mutation check entirely). The most-cited ones, for orientation: verify evidence mandatory · no verification weakening (INV2) · conformance by the tech-lead, not self-review · artifacts as files, one-line RESULT. Refactor-specific, on top:

- **Behavior preservation is the contract** — existing tests green **before and after**; a red test = behavior changed = not a refactor.
- **No verification weakening** (INV2 — *especially* critical for refactor, where "cleaning up" can quietly drop tests). A changed test needs an explicit, justified, implementation-detail-only reason surfaced to the human.
- **Structure must actually improve** (tech-lead judges — not churn for its own sake). **No new features.**
