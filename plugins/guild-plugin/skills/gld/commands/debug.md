# DEBUG (stage: execute variant — bugs)

**Stage: execute, variant for `type:bug`.** Roles: **developer** (reproduce → root-cause → fix) with **tech-lead conformance**, plus conditional specialists / gate reviews the leader convenes (Step 3.5). Invocable directly (`/gld debug <issue>`) or via `/gld dev` (auto-selected when the Issue is `type:bug`). The spine is identical to `implement` (execute → test); only the *developer's task shape* differs — a bug is **reproduced and root-caused**, not built.

`$1` = Issue number. Returns a Section D line.

> **Bash**: `_bash_rules.md`. State/handoff: `_handoff.md`.
> **Output language**: all human-readable output in `config.language` (`_handoff.md` Section K); sub-agent prompts carry that instruction.

---

## Step 0 — Preflight
As the leader, follow `_preflight.md` **Heavy tier** (incl. ⑥ knowledge retrieval — a hotspot fact often names the culprit). Load the design output (`<!-- guild:design:output -->`) — for a bug the design is **light** (§4): a **reproduction + root-cause hypothesis** rather than a full skeleton. Load `docs/specs/$1/` (repro steps, hypothesis, test cases) if present. Missing analyze/design output → `NEEDS_CONTEXT: analyze/design not found for #$1`.

Validate `$1` is an Issue. Ensure entry label `guild:execute` if invoked directly. Create/switch to a fix branch (repo convention, e.g. `fix/#$1-<slug>`). **Resume-safe**: existing branch → continue from partial work.

## Step 1 — Spawn developer (reproduce → root-cause → fix)
Spawn the developer sub-agent (`subagent_type: general-purpose`, `model: sonnet`, `description: developer debug #$1`):
> Adopt the persona in `.claude/agents/developer.md`. Fix bug #$1 on the current branch. Work in this order:
> 1. **Reproduce** — write a **failing test that captures the bug** (red; it must fail *for the reason the bug describes*, proving the bug exists). Capture the raw red output as evidence.
> 2. **Root cause** — find the *actual* cause, not a symptom. State it in one line. (Use ⑥ knowledge / hotspot facts + the repro.)
> 3. **Fix** — the smallest change that makes the regression test go green **and keeps all existing tests green** (no new regressions). Do NOT patch the symptom while leaving the cause.
> Capture the raw runner output (red→green) as verify evidence — no "fixed" claim without it (`_handoff.md` Section E). slopcheck (no hallucinated deps). Commit with the repo convention. Return EXACTLY one `>>> RESULT <<<` line (Section C) incl. the raw test summary, the one-line root cause, and the branch. Write output in `config.language`.

## Step 2 — Capture verify evidence
When the developer reports green, post the raw runner output under `<!-- guild:test-evidence:step-1 -->` (temp-file). As the leader, cross-check the self-report vs raw output — disagreement → raw wins, treat as not-green, loop back (Step 4). **The regression test must have been red before the fix** — a fix with no failing-then-passing test is a symptom patch; send it back.

## Step 3 — Tech-lead conformance check
Spawn the tech-lead (`description: tech-lead conformance #$1`):
> Adopt `.claude/agents/tech-lead.md`. Review the fix on the current branch. Check: is the **root cause** addressed (not a symptom)? Does the **regression test genuinely capture the bug** (would it fail without the fix)? Blast radius — does the fix touch shared code beyond the reported scope safely? You are reviewing the DEVELOPER's output. Return one `>>> RESULT <<<`: `DONE` / `DONE_WITH_CONCERNS: <one-line>` / `BLOCKED: <non-conformance>`.

## Step 3.5 — Conditional specialists + gate reviews (leader)
Same as `implement.md` Step 3.5 — convene the execute-stage specialists / gate reviews the diff surface warrants (security on auth/exposure, dba on schema, etc.; `_handoff.md` Section G). Run in parallel; a gate `BLOCKED` blocks advancement.

## Step 4 — Arbitrate (defined feedback loop)
As the leader, over developer + tech-lead + specialist verdicts:
- All `DONE`/`DONE_WITH_CONCERNS` + raw evidence green (regression test red→green, existing green) → Step 5.
- Tech-lead `BLOCKED` (symptom-patch / wrong root cause), a gate `BLOCKED`, or evidence contradicts green → **defined loop back to execute** (re-spawn developer with the specific concern). Bounded — ~2 loops → `NEEDS_HUMAN: <one-line>`.
  - **Ground-truth capture (①, `_signals.md` Section C — agent↔agent correction):** on a **real reversal** (a `BLOCKED`, or raw evidence contradicting claimed green — not a mere `DONE_WITH_CONCERNS`), append one entry (its own Bash call, best-effort — never blocks). The `BLOCKED` reason / contradicting raw line **is** the objective anchor. `--surprise` always (§8-A):
    ```bash
    python3 <<SKILL_DIR>>/commands/atoms/capture_signal.py --kind correction --issue $1 --stage execute --role <tech-lead|security|…> --area "<the file/area of the bug>" --summary "<what was reversed, 1 line>" --evidence "<the BLOCKED finding / raw line>" --surprise
    ```
    Claimed-green-but-red → use `--kind verify-gap --role developer`. **Skip** when no loop-back occurred (agreement ≠ correction).
- Any `FAIL` → `FAIL: <reason>`.

## Step 5 — Open PR
As the leader, push + open a PR (`Refs #$1`, body summarizes root cause + fix + the regression-test evidence). **Resume-safe** (PATCH existing PR). **Unattended (`GLD_UNATTENDED=1`)**: append the `## 무인 결정 로그` section (`_handoff.md` Section H).

## Step 6 — Transition + return
```bash
gh issue edit $1 --remove-label "guild:execute" --add-label "guild:test"
```
Return `>>> RESULT <<<` / `OK ADVANCE: test`. Other: `NEEDS_HUMAN`/`NEEDS_CONTEXT`/`FAIL` (no transition).

## Hard rules
- **Reproduce first** — a bug fix MUST carry a regression test that was **red before the fix, green after** (proves the bug + prevents recurrence). No red-then-green test = symptom patch = reject.
- **Root cause, not symptom** — the tech-lead conformance check enforces this.
- **No verification weakening** (INV2); **no regressions** (existing tests stay green); conformance by tech-lead, not self-review.
