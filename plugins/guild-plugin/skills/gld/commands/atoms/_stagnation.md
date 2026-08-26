# STAGNATION (shared loop-back guard)

**Not a stage.** Shared contract for how a stage's bounded loop-back — execute↔conformance (`implement.md`/`debug.md`/`refactor.md` Step 4), and the unattended test/qa loop-back (`_handoff.md` Section H, `test.md`/`qa.md` Step 3) — detects a **stalled** retry (the blocking reason repeats instead of resolving) and stops burning attempts against it, instead of silently exhausting the numeric cap. Read by any stage step that is about to re-invoke after a `BLOCKED` / failed-verify / defect result.

---

## Section A — The signature

Every loop-back already carries a blocking reason — one line for most sources (the tech-lead's `BLOCKED: <non-conformance>`, a gate's finding, the verify-gap description, the QA defect), a **set** of them for the execute-stage external auditor (see below), and often both at once. Before consuming another loop-back attempt (attempt #2+) for the same Issue/stage, the leader compares the **current** reason against the **immediately prior** attempt's reason — per source, per the two-axis rule below:

- **Same root cause** (same file/AC/concern restated, even if reworded) → **stagnation**: the previous loop-back did not actually address it.
- **Different concern** (a new/different reason, even if in the same area) → genuine progress — one issue surfaced another. Not stagnation; continue under the normal bounded cap.

**Multi-finding sources — the reason is a SET, not a line.** The execute stage's always-on external auditor (`_execute_spine.md` Step 3.5a) returns a JSON **array**, so a loop-back it triggers has several reasons at once. Comparing "the reason" as a single string there would silently **never** match: attempt 2 returning `{A, C}` against attempt 1's `{A, B}` is not a different concern — it is the **same blocker A**, still unresolved, with a new one alongside it. Reduce each attempt to its **blocking signature**: the set of `(file, defect)` pairs among that attempt's **un-dismissed** findings at `BLOCKER` **or** `MAJOR` severity. Three exclusions, for different reasons:

- **`MINOR` never enters** — it never blocks, so it would only add churn.
- **A finding the leader DISMISSED never enters** — nobody was asked to fix it, and the auditor (which has no memory of the dismissal) re-reports it verbatim on every re-scan, so counting it would manufacture an identical set out of a decision the spine deliberately made. A dismissal is a decision about the finding, not a count of it — so excluding it is not the ordinal-dependent membership the warning below forbids.
- **A finding Step 4 has decided to RECORD rather than retry never enters** — the out-of-budget `MAJOR` case (`_execute_spine.md` Step 4's severity policy). Same reasoning as the dismissal: nobody is working on it, so its verbatim recurrence says nothing about whether the retry is progressing. This is the voting rule below, stated as a membership consequence.

Then:

⚠ **Never make membership depend on a finding's ORDINAL — its occurrence count, or which attempt first raised it.** A rule like "…plus a `MAJOR` only on its *first* occurrence" makes the signature unstable across exactly the comparison it exists for: attempt 1 blocks on `{A (BLOCKER), M (MAJOR)}`, the redo fixes nothing, attempt 2 returns the identical findings — but `M` is no longer a first occurrence, so attempt 2's signature would read `{A}` and the leader would call a retry that resolved *nothing* "genuine progress".

What decides membership is whether the finding is **currently driving the retry** (the voting rule below), which is stable: a finding that is blocking now was blocking on identical terms last time, or it was not. That is a different question from *how many times it has appeared*, and it is why an out-of-budget `MAJOR` — which Step 4 has explicitly decided to record rather than retry — is out of the signature while a still-blocking one is in it.

**A loop-back usually has BOTH kinds of reason now — compare them SEPARATELY, and flag stagnation if EITHER repeats.** The execute stage re-runs the auditor on *every* loop-back (`_execute_spine.md` Step 4's chain rule), so an attempt commonly carries a one-line role reason (a tech-lead `BLOCKED`, a gate finding) *and* an auditor finding set. Do **not** merge them into one pooled set: pooling lets each source's repeat hide behind the other's churn — an identical tech-lead `BLOCKED` twice would be excused by the auditor turning up a different finding, which is exactly backwards. So:

⚠ **An axis votes only if it is actually TRIGGERING the current loop-back.** This is the rule that keeps the guard honest, and it does more work than it looks like. A finding that is present but not driving the retry — a `MINOR`, a dismissed finding, an out-of-budget `MAJOR` that Step 4 decided to record rather than retry — is **not** being worked on, so the auditor re-reports it verbatim on every re-scan forever. Letting it vote would manufacture an identical signature out of a decision the spine deliberately made, and escalate a loop-back whose real blocker is brand new. Likewise a source that returned nothing, or never ran, does not vote (`∅` is agreement about *nothing*, not a stall).

- **Role-reason axis** (votes when a role `BLOCKED`/defect/verify-gap is triggering this loop-back) — compare this attempt's blocking reason(s) against the prior attempt's by the "same root cause" test at the top of this section.
- **Auditor-set axis** (votes when an auditor finding is triggering this loop-back) — compare this attempt's triggering signature against the prior attempt's.
- **A voting axis fires when everything currently driving it was already driving it last time** — i.e. this attempt's triggering set is **non-empty and wholly contained in** the prior attempt's. Nothing new is pushing the loop; the same thing survived a full redo.
- **Any voting axis fires → stagnation**, on that axis's reason. None fires → genuine progress; continue under the numeric cap.

**Containment, not equality — and this is a deliberate trade.** `{A, B}` → `{A}` fires: B was fixed, but `A` — still the thing blocking — went through an entire loop-back untouched, which is exactly what "the previous loop-back did not actually address it" means. The cost is real but small: the numeric cap is ~2, so the attempt this saves is usually the one the cap would have denied anyway; what the guard mainly buys is an honest message and the `stagnation` signal instead of a silent budget exhaustion. Contrast the two failure modes and it is clear which to prefer: firing here costs one early hand-off to a human, while *not* firing costs a retry everyone already knows will not help.

⚠ **The guard only runs when a loop-back is otherwise about to be consumed.** If Step 4 has already decided to advance — every blocking condition cleared, an out-of-budget `MAJOR` merely recorded — there is no attempt to protect and the comparison is not performed at all. Running it on the advance path would convert "recorded, not retried" (an explicit policy outcome) into an escalation.

⚠ **Containment is not the same as intersection — do not loosen it further.** Firing on *any* recurring pair would also fire when something genuinely new is driving the loop (`{A}` → `{A, C}`: `C` is new, the loop is moving), which is a real interruption for no reason. Containment fires only when **nothing** new is driving it. The two rules differ exactly where it matters, and the calibration below still governs the judgment inside each pair ("when genuinely unsure whether two reasons are the same root cause, err toward **not** flagging").

A loop-back with no auditor involvement (a verify gap, a QA defect, the unattended `test`/`qa` loop-backs) uses the role-reason axis alone and behaves **exactly as it did before this rule existed**.

This is a judgment call by the leader over short strings it already has in context — no hashing, no new infra, no persistence beyond the current stage invocation. **Calibration**: same *file* + same underlying *defect* = same root cause even if the wording differs entirely (e.g. "widget test asserts nothing in the disabled path" vs. "disabled-state contrast check is a no-op" — same #894-class bug, restated); a genuinely different file, a different AC, or a different mechanism within the same file (e.g. the fix for a null-check bug then exposes a separate off-by-one) = different concern, not stagnation. When genuinely unsure, err toward **not** flagging stagnation — the bounded numeric cap (≤2) still catches a truly stuck loop-back even if one ambiguous retry gets miscounted as progress, whereas prematurely escalating a retry that was actually about to succeed costs a human interruption for nothing.

## Section B — On stagnation detected

Do not spend the remaining loop-back budget on a retry unlikely to help. Escalate immediately, before the numeric cap would otherwise be reached:

- **Attended**: `NEEDS_HUMAN: same blocker recurred after loop-back — <reason>; retrying is unlikely to resolve it without a different approach`.
- **Unattended** (`GLD_UNATTENDED=1`): translates via `_handoff.md` Section H's escape hatch → `OK PAUSE: needs-human — stagnant loop-back — <reason>` + `guild:needs-human` label.

This **composes with, not replaces**, each stage's existing numeric cap ("~2 loops"): whichever condition fires first wins. An identical-reason repeat can fire *before* the cap (e.g. on attempt 2 of 2, immediately); the cap still fires on its own when every attempt raises a genuinely different concern.

## Section C — Ground-truth capture

A stagnant loop-back is itself a growth-loop signal — it suggests the *design/skeleton/standard* the loop keeps bouncing off of may be the actual problem, not the developer's individual attempt. Capture it (its own Bash call, best-effort — never blocks the loop):

```bash
python3 <<SKILL_DIR>>/commands/atoms/capture_signal.py --kind stagnation --issue <N> --stage <execute|test|qa> --role <role whose BLOCKED/defect recurred; use the literal token auditor when the recurring axis was the execute-stage external auditor and no role blocked> --area "<the file/area>" --summary "<the recurring reason, 1 line>" --evidence "<attempt 1 reason> == <attempt 2 reason>" --surprise
```

Substitute the **literal** Issue number for `<N>` (and the literal values for every other `<…>`) before the Bash call — `_bash_rules.md` item 9 forbids passing `$1`/`<N>` through unresolved, and `capture_signal.py` accepts a non-numeric `--issue` silently rather than erroring, so an unresolved `$1` would land in the ground-truth log as `"issue": "$1"` and quietly poison the record evolve reads.

**No `--escalated` here** — this capture fires on the *stagnation* path, which does not retry at all, so no model tier was ever bumped (`_model_tiering.md` Section A/B, `implement.md` Step 4). `--surprise` always — a repeated identical blocker is exactly the "confident work reversed twice" case. Read on-demand by evolve/audit alongside the other signal classes (`_signals.md` Section A); a **cluster** of stagnation entries in the same area across issues is a stronger systemic-fix signal (e.g. a misleading skeleton template, an unclear standard) than a single one-off.

## Hard rules

- **Shortens the loop, never lengthens it** (INV2 spirit) — stagnation detection is never used to justify looping *past* the numeric cap.
- **An identical reason on attempt 2 is decisive, not a hint** — do not silently try a third time hoping it resolves.
- Detection is read-only bookkeeping (comparing reasons already produced elsewhere — two short strings, or two small `(file, defect)` sets for a multi-finding source) — no new sub-agent, no new file, no cross-session persistence required.
- **`MINOR` findings never enter a signature.** They never block, so a churning `MINOR` would make two otherwise-identical attempts compare unequal and **suppress** a stall the guard should have caught.
