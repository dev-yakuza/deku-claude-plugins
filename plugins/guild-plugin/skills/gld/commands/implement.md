# IMPLEMENT (stage: execute variant)

**Stage: execute (M1 = implement).** Roles: **developer** (fills the skeleton via TDD) with **tech-lead conformance check**, plus any **conditional specialists / gate reviews** the leader convenes (security/infra/i18n/dba/analytics/performance — Step 3.5). Invocable directly (`/gld implement <issue>`) or via `/gld dev`. In M1, execute is always `implement` (debug/refactor variants are later milestones).

`$1` = Issue number. Returns a Section D line.

> **Bash**: `_bash_rules.md`. State/handoff: `_handoff.md`.

---

## Step 0 — Preflight
As the leader, follow `_preflight.md` **Heavy tier** (items 1–5, including target-dir survey). Load the design output (`<!-- guild:design:output -->`), the skeleton (`docs/specs/$1/skeleton.md`), and the test cases (`docs/specs/$1/test-cases.md`). If design output or skeleton is missing → `NEEDS_CONTEXT: design/skeleton not found for #$1`.

Validate `$1` is an Issue. Ensure entry label `guild:execute` if invoked directly.

Create/switch to a feature branch for this Issue (follow the repo's branch convention from conventions.md; e.g. `feature/#$1-<slug>`). Do this as the leader before spawning the developer, so the developer works on the branch. **Resume-safe (rate-limit/interruption — 항목 4)**: if a branch for this Issue **already exists** (a prior interrupted execute), switch to it and build a concise **partial-work summary** — `git log <base>..HEAD --oneline` (what's committed) **plus one run of the test command** to see which cases already pass vs still fail (where TDD left off). This summary is passed into the developer prompt (Step 1) so it **continues from the partial state, not from scratch**. Only create the branch (no summary) if absent. (Plan §부록 B "중단 내성" — mid-execute resume.)

## Step 1 — Spawn developer (TDD red→green→refactor)
Spawn the developer sub-agent:
- `subagent_type`: `general-purpose`, `model`: `sonnet`, `description`: `developer implement #$1`
- `prompt`:
  > Adopt the persona in `.claude/agents/developer.md`. Implement Issue #$1 on the current branch. Read the skeleton (`docs/specs/$1/skeleton.md`) and test cases (`docs/specs/$1/test-cases.md`) — these are your inputs, passed as files. Do TDD: make the tester's cases fail (red), implement to green, then refactor. **Resume (항목 4)**: if Step 0 supplied a partial-work summary below, a prior run was interrupted mid-execute — **CONTINUE from it**: keep the already-green work, pick up the TDD cycle where it stopped, complete the rest; redo only what is wrong. Do NOT rewrite correct existing work from scratch. `<partial-work summary from Step 0, or "none — fresh branch">`. Run the project's test command and **capture the raw runner output** as verify evidence — do NOT claim green without it (`_handoff.md` Section E). slopcheck: verify every import/dependency exists (no hallucinated packages). Commit with the repo's convention. Return EXACTLY one `>>> RESULT <<<` line per `_handoff.md` Section C, including the raw test summary line and the branch name.

## Step 2 — Capture verify evidence
When the developer reports green, post the raw test-runner output to the Issue as evidence (temp-file pattern):
- Marker: `<!-- guild:test-evidence:step-1 -->` … `<!-- /guild:test-evidence:step-1 -->`.
- Body: the raw runner summary line(s) the developer captured. As the leader, cross-check the developer's self-report against this raw output — if they disagree, the raw output wins; treat as not-green and loop back (Step 4).

## Step 3 — Tech Lead conformance check
Spawn the tech-lead sub-agent to check the implementation against the design (separate eyes — anti-confirmation-bias, plan §16 C1):
- `subagent_type`: `general-purpose`, `model`: `sonnet`, `description`: `tech-lead conformance #$1`
- `prompt`:
  > Adopt the persona in `.claude/agents/tech-lead.md`. Review the implementation on the current branch against your skeleton (`docs/specs/$1/skeleton.md`) and `docs/standards/architecture.md`. Check: did it honor the module boundaries, seams, technical direction, and design intent? You are reviewing the DEVELOPER's output, not your own. Return one `>>> RESULT <<<` line: `DONE` (conformant), `DONE_WITH_CONCERNS: <one-line>`, or `BLOCKED: <non-conformance>` (requires an execute loop).

## Step 3.5 — Conditional specialists + gate reviews (leader)
As the leader, convene the **execute-stage participation specialists** and **gate reviews** this change warrants (assembly rules in `.claude/agents/leader.md`; participation model in `_handoff.md` Section G). Match the diff surface against triggers; spawn only what matches (none matched → skip). Run the independent reviews in parallel:
- **auth / external exposure / secrets / sensitive data / input validation** → **security**: adversarial review of the developer's diff (a **gate** — reviewing someone else's output, not self-review). Returns findings with severity.
- **CI/CD / deploy / env / IaC touched** → **infra**: review the infra change (rollback/verify path correct?).
- **user-facing strings** → **i18n** · **schema/migration** → **dba** · **instrumentation** → **analytics** · **hot path/render/query** → **performance**: execute-time participation on their slice.
- **user-facing / API / documented-behavior change, OR an architecture-impacting change** (new module / changed boundary / major dependency) → **tech-writer**: draft/update the docs (README, user docs, ADR follow-through) against the **implemented** change — docs describe what was actually built. **② architecture.md drift-sync (항목 2a — Inner Loop)**: when the change is architecture-impacting, keep `docs/standards/architecture.md`'s **high-level skeleton** current (details stay in the ADR + ⑥ — architecture.md is the *slow overview*, not a detail log). By its `status`: `draft` → **update in place** (provisional, safe); `confirmed` → **never silently rewrite** — **attended**: propose the skeleton update, apply on human approval; **unattended** (`GLD_UNATTENDED`): the ADR already preserves the decision, so append a `<!-- guild:arch-drift -->` flag noting architecture.md needs a skeleton update → surfaced at the next `/gld review` or `/gld audit`. (Release notes are the release-manager's job, out of the spine.)

For each matched role:
- `subagent_type`: `general-purpose`, `model`: `sonnet`, `description`: `<role> review #$1`
- `prompt`:
  > Adopt the persona in `.claude/agents/<role>.md`. Review the implementation on the current branch for Issue #$1 from your specialty. You are reviewing the DEVELOPER's diff, not your own work (external, adversarial). Read `docs/specs/$1/` for design/intent. Return one `>>> RESULT <<<` line per `_handoff.md` Section C — `DONE`, `DONE_WITH_CONCERNS: <one-line>`, or `BLOCKED: <blocking finding>`.

Fold these verdicts into Step 4. A gate role's `BLOCKED` (e.g. security finds a real vulnerability) blocks advancement the same as a tech-lead non-conformance.

## Step 4 — Arbitrate (defined feedback loop)
As the leader, over the developer + tech-lead + any conditional specialist/gate verdicts:
- Developer `DONE`/`DONE_WITH_CONCERNS` + tech-lead `DONE`/`DONE_WITH_CONCERNS` + all gate/specialist verdicts `DONE`/`DONE_WITH_CONCERNS` + raw evidence green → proceed to Step 5. Record specialist concerns in the PR body.
- Tech Lead `BLOCKED` (non-conformance), a **gate `BLOCKED`** (e.g. security vulnerability), OR evidence contradicts green → before looping back, apply the **stagnation guard** (`_stagnation.md`): compare this reason against the immediately-prior loop-back's reason for this Issue (if any). **Same root cause repeated** → stagnation — escalate immediately (`_stagnation.md` Section B) instead of consuming another attempt. **Different concern** → **defined loop back to execute**: re-invoke the developer (Step 1) — and the tech-lead/gate role whose `BLOCKED` triggered this — **at one model tier above their default** (`_model_tiering.md` Section A: sonnet → opus; attempt 1 always ran at the default, this is the one bounded retry), with the specific concern. Bounded — after ~2 loops without resolution, return `NEEDS_HUMAN: <one-line>`.
  - **Ground-truth capture (①, `_signals.md` Section C — agent↔agent correction):** when this loop-back fires on a **real reversal** (a `BLOCKED`, or raw evidence contradicting a claimed green — **not** a mere `DONE_WITH_CONCERNS`), append one entry (its own Bash call, best-effort — never blocks the loop). The `BLOCKED` non-conformance/finding (or the contradicting raw line) **is** the objective anchor — a role overturning *another* role's confident output, not self-review (`_signals.md` Section B). `--surprise` always (confident work reversed — plan §8-A); add `--escalated` since Step 4 just bumped the retry's model tier (`_model_tiering.md` Section B):
    ```bash
    python3 <<SKILL_DIR>>/commands/atoms/capture_signal.py --kind correction --issue $1 --stage execute --role <tech-lead|security|infra|…> --area "<the target dir/file being implemented>" --summary "<what was reversed, 1 line>" --evidence "<the BLOCKED non-conformance/finding, 1 line>" --surprise --escalated
    ```
    For the **evidence-contradicts-green** case (developer claimed green, the raw runner disagreed) use `--kind verify-gap --role developer` instead — the same claimed↔raw shape as the test stage, caught earlier at execute. **Skip** when no loop-back occurred (all `DONE`/green) — a passed conformance check is not a signal (agreement ≠ correction). **When the stagnation guard fires** (identical reason repeated), capture `--kind stagnation` instead (`_stagnation.md` Section C) — the recurrence is the signal, not a single role's reversal; drop `--escalated` there (a stagnant loop-back does not retry at all, so no tier was bumped).
- Any `FAIL` → return `FAIL: <reason>`.

## Step 5 — Open PR
As the leader, push the branch and open a PR referencing the Issue (temp-file body via `--body-file`; body references `Refs #$1` and summarizes the change + test evidence). The PR is where the **human reviewer** (M1's external reviewer, plan §18 A) approves. **Resume-safe**: if a PR for this branch already exists (interrupted prior run), PATCH it rather than opening a duplicate. **Unattended (`GLD_UNATTENDED=1`)**: append a `## 무인 결정 로그 (GLD_UNATTENDED)` section to the PR body aggregating the leader-proxy gate decisions recorded in the analyze/design outputs (chosen interpretation · charter rationale · "사람 확인 요") — `_handoff.md` Section H — so the deferred human gate (PR review) is informed, not blind.

## Step 6 — Transition + return
```bash
gh issue edit $1 --remove-label "guild:execute" --add-label "guild:test"
```
Return:
```
>>> RESULT <<<
OK ADVANCE: test
```
Other returns: `NEEDS_HUMAN`, `NEEDS_CONTEXT`, `FAIL` (do NOT transition).

## Hard rules
- **Verify evidence is mandatory** (`_handoff.md` Section E): no "green" claim without the raw runner output; raw output wins over self-report.
- **No verification weakening** (INV2): the developer must not delete/skip/weaken tests to pass. If a test must change, it requires an explicit, justified reason surfaced to the human.
- **Conformance is by the tech-lead, not self-review** (roles don't self-check — plan §16 C1).
- Artifacts/inputs pass as files; RESULT lines stay one line.
