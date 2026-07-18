# STAGNATION (shared loop-back guard)

**Not a stage.** Shared contract for how a stage's bounded loop-back — execute↔conformance (`implement.md`/`debug.md`/`refactor.md` Step 4), and the unattended test/qa loop-back (`_handoff.md` Section H, `test.md`/`qa.md` Step 3) — detects a **stalled** retry (the blocking reason repeats instead of resolving) and stops burning attempts against it, instead of silently exhausting the numeric cap. Read by any stage step that is about to re-invoke after a `BLOCKED` / failed-verify / defect result.

---

## Section A — The signature

Every loop-back already carries a one-line blocking reason (the tech-lead's `BLOCKED: <non-conformance>`, a gate's finding, the verify-gap description, the QA defect). Before consuming another loop-back attempt (attempt #2+) for the same Issue/stage, the leader compares the **current** reason against the **immediately prior** attempt's reason:

- **Same root cause** (same file/AC/concern restated, even if reworded) → **stagnation**: the previous loop-back did not actually address it.
- **Different concern** (a new/different reason, even if in the same area) → genuine progress — one issue surfaced another. Not stagnation; continue under the normal bounded cap.

This is a judgment call by the leader over two short strings it already has in context — no hashing, no new infra, no persistence beyond the current stage invocation.

## Section B — On stagnation detected

Do not spend the remaining loop-back budget on a retry unlikely to help. Escalate immediately, before the numeric cap would otherwise be reached:

- **Attended**: `NEEDS_HUMAN: same blocker recurred after loop-back — <reason>; retrying is unlikely to resolve it without a different approach`.
- **Unattended** (`GLD_UNATTENDED=1`): translates via `_handoff.md` Section H's escape hatch → `OK PAUSE: needs-human — stagnant loop-back — <reason>` + `guild:needs-human` label.

This **composes with, not replaces**, each stage's existing numeric cap ("~2 loops"): whichever condition fires first wins. An identical-reason repeat can fire *before* the cap (e.g. on attempt 2 of 2, immediately); the cap still fires on its own when every attempt raises a genuinely different concern.

## Section C — Ground-truth capture

A stagnant loop-back is itself a growth-loop signal — it suggests the *design/skeleton/standard* the loop keeps bouncing off of may be the actual problem, not the developer's individual attempt. Capture it (its own Bash call, best-effort — never blocks the loop):

```bash
python3 <<SKILL_DIR>>/commands/atoms/capture_signal.py --kind stagnation --issue $1 --stage <execute|test|qa> --role <role whose BLOCKED/defect recurred> --area "<the file/area>" --summary "<the recurring reason, 1 line>" --evidence "<attempt 1 reason> == <attempt 2 reason>" --surprise
```

`--surprise` always — a repeated identical blocker is exactly the "confident work reversed twice" case plan §8-A ranks highest. Read on-demand by evolve/audit alongside the other signal classes (`_signals.md` Section A); a **cluster** of stagnation entries in the same area across issues is a stronger systemic-fix signal (e.g. a misleading skeleton template, an unclear standard) than a single one-off.

## Hard rules

- **Shortens the loop, never lengthens it** (INV2 spirit) — stagnation detection is never used to justify looping *past* the numeric cap.
- **An identical reason on attempt 2 is decisive, not a hint** — do not silently try a third time hoping it resolves.
- Detection is read-only bookkeeping (comparing two one-line strings already produced elsewhere) — no new sub-agent, no new file, no cross-session persistence required.
