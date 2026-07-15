# REFACTOR (stage: execute variant — refactor)

**Stage: execute, variant for `type:refactor`.** Roles: **developer** (behavior-preserving transform) with **tech-lead conformance** (structure improved *and* behavior preserved), plus conditional specialists (Step 3.5). Invocable directly (`/gld refactor <issue>`) or via `/gld dev` (auto-selected when the Issue is `type:refactor`). Same spine as `implement` (execute → test); the developer's task shape differs — code is **transformed without changing behavior**, so the **existing tests are the safety net** (no new feature test).

`$1` = Issue number. Returns a Section D line.

> **Bash**: `_bash_rules.md`. State/handoff: `_handoff.md`.
> **Output language**: all human-readable output in `config.language` (`_handoff.md` Section K); sub-agent prompts carry that instruction.

---

## Step 0 — Preflight
As the leader, follow `_preflight.md` **Heavy tier** (incl. ⑥ knowledge + target-dir survey). Load the design output — for a refactor the design **is the target structure** (§4: design = 목표 구조). Load `docs/specs/$1/skeleton.md` (the target shape). Missing → `NEEDS_CONTEXT: design/target-structure not found for #$1`.

Validate `$1` is an Issue. Ensure entry label `guild:execute` if invoked directly. Create/switch to a refactor branch (e.g. `refactor/#$1-<slug>`). **Resume-safe**.

## Step 1 — Spawn developer (behavior-preserving transform)
Spawn the developer (`description: developer refactor #$1`):
> Adopt the persona in `.claude/agents/developer.md`. Refactor Issue #$1 on the current branch toward the target structure (`docs/specs/$1/skeleton.md`). **Behavior-preserving — this is the core constraint**:
> - The **existing tests MUST stay green throughout** — run them before and after; behavior does not change. They are your safety net.
> - Do **NOT** add features, change observable behavior, or **weaken/delete/skip tests** (INV2). If a test asserted an *implementation detail* that the refactor legitimately removes, surface it **explicitly with justification** in your RESULT — never silently drop it.
> - Prefer many small behavior-preserving steps, tests green at each.
> Capture the raw runner output (all green) as evidence (`_handoff.md` Section E). slopcheck. Commit with the repo convention. Return EXACTLY one `>>> RESULT <<<` line (Section C) incl. the raw test summary (all green), what structural improvement was made, and the branch. Write output in `config.language`.

## Step 2 — Capture verify evidence
Post the raw runner output under `<!-- guild:test-evidence:step-1 -->` (temp-file). As the leader, cross-check self-report vs raw. **All existing tests must be green** — a refactor that turns a test red has changed behavior (or broke something); that is not-done, loop back. If the developer changed any test, verify the justification is real (implementation-detail only, not a weakened assertion).

## Step 3 — Tech-lead conformance check
Spawn the tech-lead (`description: tech-lead conformance #$1`):
> Adopt `.claude/agents/tech-lead.md`. Review the refactor on the current branch against the target structure (`docs/specs/$1/skeleton.md`) + `docs/standards/architecture.md`. Check TWO things: (1) is the **structure genuinely improved** toward the target (not churn)? (2) is **behavior preserved** — no functional change, and **no test weakened/removed** except a justified implementation-detail test? You are reviewing the DEVELOPER's output. Return one `>>> RESULT <<<`: `DONE` / `DONE_WITH_CONCERNS: <one-line>` / `BLOCKED: <non-conformance or behavior/verification change>`.

## Step 3.5 — Conditional specialists + gate reviews (leader)
Same as `implement.md` Step 3.5 (`_handoff.md` Section G). A refactor touching a hot path → performance; schema → dba; etc. A gate `BLOCKED` blocks advancement.

## Step 4 — Arbitrate (defined feedback loop)
As the leader, over the verdicts:
- All `DONE`/`DONE_WITH_CONCERNS` + all existing tests green + behavior preserved → Step 5.
- Tech-lead `BLOCKED` (structure not improved, behavior changed, or a test weakened), a gate `BLOCKED`, or a test went red → **defined loop back to execute**. Bounded — ~2 loops → `NEEDS_HUMAN`.
  - **Ground-truth capture (①, `_signals.md` Section C — agent↔agent correction):** on a **real reversal** (`BLOCKED` / a red test contradicting claimed-green — not a mere `DONE_WITH_CONCERNS`), append one entry (own Bash call, best-effort). Anchor = the `BLOCKED` reason / red line. `--surprise` always:
    ```bash
    python3 <<SKILL_DIR>>/commands/atoms/capture_signal.py --kind correction --issue $1 --stage execute --role <tech-lead|performance|…> --area "<the refactored file/area>" --summary "<what was reversed, 1 line>" --evidence "<finding / red line>" --surprise
    ```
    A **weakened-verification** reversal (a refactor that quietly removed/weakened a test, caught here) is exactly the INV2 signal worth capturing. **Skip** when no loop-back (agreement ≠ correction).
- Any `FAIL` → `FAIL: <reason>`.

## Step 5 — Open PR
Push + open a PR (`Refs #$1`, body: what structure improved, behavior-preserved statement, existing-tests-green evidence). Resume-safe. Unattended → `## 무인 결정 로그` (Section H).

## Step 6 — Transition + return
```bash
gh issue edit $1 --remove-label "guild:execute" --add-label "guild:test"
```
Return `OK ADVANCE: test`. Other: `NEEDS_HUMAN`/`NEEDS_CONTEXT`/`FAIL`.

## Hard rules
- **Behavior preservation is the contract** — existing tests green **before and after**; a red test = behavior changed = not a refactor.
- **No verification weakening** (INV2 — *especially* critical for refactor, where "cleaning up" can quietly drop tests). A changed test needs an explicit, justified, implementation-detail-only reason surfaced to the human.
- **Structure must actually improve** (tech-lead judges — not churn for its own sake). No new features. Conformance by tech-lead, not self-review.
