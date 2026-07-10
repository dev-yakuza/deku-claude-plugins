# IMPLEMENT (stage: execute variant)

**Stage: execute (M1 = implement).** Roles: **developer** (fills the skeleton via TDD) with **tech-lead conformance check**, plus any **conditional specialists / gate reviews** the leader convenes (security/infra/i18n/dba/analytics/performance — Step 3.5). Invocable directly (`/gld implement <issue>`) or via `/gld dev`. In M1, execute is always `implement` (debug/refactor variants are later milestones).

`$1` = Issue number. Returns a Section D line.

> **Bash**: `_bash_rules.md`. State/handoff: `_handoff.md`.

---

## Step 0 — Preflight
As the leader, follow `_preflight.md` **Heavy tier** (items 1–5, including target-dir survey). Load the design output (`<!-- guild:design:output -->`), the skeleton (`docs/specs/$1/skeleton.md`), and the test cases (`docs/specs/$1/test-cases.md`). If design output or skeleton is missing → `NEEDS_CONTEXT: design/skeleton not found for #$1`.

Validate `$1` is an Issue. Ensure entry label `guild:execute` if invoked directly.

Create/switch to a feature branch for this Issue (follow the repo's branch convention from conventions.md; e.g. `feature/#$1-<slug>`). Do this as the leader before spawning the developer, so the developer works on the branch.

## Step 1 — Spawn developer (TDD red→green→refactor)
Spawn the developer sub-agent:
- `subagent_type`: `general-purpose`, `model`: `sonnet`, `description`: `developer implement #$1`
- `prompt`:
  > Adopt the persona in `.claude/agents/developer.md`. Implement Issue #$1 on the current branch. Read the skeleton (`docs/specs/$1/skeleton.md`) and test cases (`docs/specs/$1/test-cases.md`) — these are your inputs, passed as files. Do TDD: make the tester's cases fail (red), implement to green, then refactor. Run the project's test command and **capture the raw runner output** as verify evidence — do NOT claim green without it (`_handoff.md` Section E). slopcheck: verify every import/dependency exists (no hallucinated packages). Commit with the repo's convention. Return EXACTLY one `>>> RESULT <<<` line per `_handoff.md` Section C, including the raw test summary line and the branch name.

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
- **user-facing / API / documented-behavior change** → **tech-writer**: draft/update the docs (README, user docs, ADR follow-through) against the **implemented** change — docs describe what was actually built. (Release notes are the release-manager's job, out of the spine.)

For each matched role:
- `subagent_type`: `general-purpose`, `model`: `sonnet`, `description`: `<role> review #$1`
- `prompt`:
  > Adopt the persona in `.claude/agents/<role>.md`. Review the implementation on the current branch for Issue #$1 from your specialty. You are reviewing the DEVELOPER's diff, not your own work (external, adversarial). Read `docs/specs/$1/` for design/intent. Return one `>>> RESULT <<<` line per `_handoff.md` Section C — `DONE`, `DONE_WITH_CONCERNS: <one-line>`, or `BLOCKED: <blocking finding>`.

Fold these verdicts into Step 4. A gate role's `BLOCKED` (e.g. security finds a real vulnerability) blocks advancement the same as a tech-lead non-conformance.

## Step 4 — Arbitrate (defined feedback loop)
As the leader, over the developer + tech-lead + any conditional specialist/gate verdicts:
- Developer `DONE`/`DONE_WITH_CONCERNS` + tech-lead `DONE`/`DONE_WITH_CONCERNS` + all gate/specialist verdicts `DONE`/`DONE_WITH_CONCERNS` + raw evidence green → proceed to Step 5. Record specialist concerns in the PR body.
- Tech Lead `BLOCKED` (non-conformance), a **gate `BLOCKED`** (e.g. security vulnerability), OR evidence contradicts green → **defined loop back to execute**: re-invoke the developer (Step 1) with the specific concern. Bounded — after ~2 loops without resolution, return `NEEDS_HUMAN: <one-line>`.
- Any `FAIL` → return `FAIL: <reason>`.

## Step 5 — Open PR
As the leader, push the branch and open a PR referencing the Issue (temp-file body via `--body-file`; body references `Refs #$1` and summarizes the change + test evidence). The PR is where the **human reviewer** (M1's external reviewer, plan §18 A) approves.

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
