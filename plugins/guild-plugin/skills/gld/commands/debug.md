# DEBUG (stage: execute variant — bugs)

**Stage: execute, variant for `type:bug`.** Roles: **developer** (reproduce → root-cause → fix) with **tech-lead conformance**, plus the always-on external auditor and any conditional specialists / gate reviews the leader convenes (Step 3.5). Invocable directly (`/gld debug <issue>`) or via `/gld dev` (auto-selected when the Issue is `type:bug`). The spine is identical to `implement` (execute → test); only the *developer's task shape* differs — a bug is **reproduced and root-caused**, not built.

`$1` = Issue number. Returns a Section D line.

> **Bash**: `_bash_rules.md`. State/handoff: `_handoff.md`.
> **Output language**: all human-readable output in `config.language` (`_handoff.md` Section K); sub-agent prompts carry that instruction.

---

## How to run this stage

Run **Steps 0–6 of `atoms/_execute_spine.md`** — Step 0 preflight (incl. the label read and the **`guild:children`** split-parent guard) · Step 1 spawn developer · Step 2 verify evidence · Step 3 tech-lead conformance · Step 3.5 external auditor (**always**) + conditional specialists/gates (security on auth/exposure, dba on schema, etc.; `_handoff.md` Section G — a gate `BLOCKED` blocks advancement, as does an auditor `BLOCKER`) · Step 4 arbitrate · Step 5 PR · Step 6 transition + return — filling its Section A slots with the values below. Nothing about the spine changes for this variant.

## Slot values (`type:bug`)

**DESIGN INPUT** — load the design output (`<!-- guild:design:output -->`) — for a bug the design is **light**: a **reproduction + root-cause hypothesis** rather than a full skeleton. Load `docs/specs/$1/` (repro steps, hypothesis, test cases) if present. Missing analyze/design output → `NEEDS_CONTEXT: analyze/design not found for #$1`. (The spine's Heavy-tier preflight matters here especially for **⑥ knowledge retrieval** — a hotspot fact often names the culprit.)

**BRANCH + RESUME PROBE** — a **fix** branch (repo convention, e.g. `fix/#$1-<slug>`). The resume test-run probes: **does the repro exist yet? is it red or already green?**

**DEVELOPER TASK SHAPE** — `description`: `developer debug #$1`. Body inserted into the spine's Step 1 prompt:

> Fix bug #$1 on the current branch. **Resume**: keep a correct repro/fix already committed and complete the rest; do not redo correct work. Work in this order:
> 1. **Reproduce** — write a **failing test that captures the bug** (red; it must fail *for the reason the bug describes*, proving the bug exists). Capture the raw red output as evidence.
> 2. **Root cause** — find the *actual* cause, not a symptom. State it in one line. (Use ⑥ knowledge / hotspot facts + the repro.)
> 3. **Fix** — the smallest change that makes the regression test go green **and keeps all existing tests green** (no new regressions). Do NOT patch the symptom while leaving the cause.
> Capture the raw runner output (red→green) as verify evidence — no "fixed" claim without it.

RESULT extras: the raw test summary, the **one-line root cause**, and the branch.

**EVIDENCE RULE** — **the regression test must have been red before the fix** (red→green; existing tests stay green). A fix with no failing-then-passing test is a **symptom patch** — send it back.

**CONFORMANCE CHECKS** — inserted into the spine's Step 3 prompt:

> Review the fix on the current branch. Check: is the **root cause** addressed (not a symptom)? Does the **regression test genuinely capture the bug** (would it fail without the fix)? Blast radius — does the fix touch shared code beyond the reported scope safely?

A tech-lead `BLOCKED` here means **symptom-patch / wrong root cause** — that is the Step 4 loop-back trigger for this variant.

**SIGNAL AREA** — `--area "<the file/area of the bug>"`; typical `--role` set `<tech-lead|security|…>`.

**PR SUMMARY** — root cause + fix + the **regression-test evidence**.

## Hard rules

Spine-common rules apply — **read `_execute_spine.md`'s "Hard rules" section directly; it is the authority and it is longer than this summary**, notably the auditor rules (3.5a never gates by itself and never edits, and the mutation check around it — `git diff --numstat --no-renames <mb>` + `git status --porcelain -uall`, compared before/after — is mandatory on **every** path — a standalone run of this variant that skips them loses the mutation check entirely). The most-cited ones, for orientation: verify evidence mandatory · no verification weakening (INV2) · conformance by the tech-lead, not self-review · artifacts as files, one-line RESULT. Bug-specific, on top:

- **Reproduce first** — a bug fix MUST carry a regression test that was **red before the fix, green after** (proves the bug + prevents recurrence). No red-then-green test = symptom patch = reject.
- **Root cause, not symptom** — the tech-lead conformance check enforces this.
- **No regressions** — existing tests stay green.
