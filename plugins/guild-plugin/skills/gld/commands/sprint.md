# SPRINT (autonomous Inner+Outer — built, readiness-gated · LOCKED by default)

**Run the full loop (dev spine + evolve) with no human intervention — but only once autonomy is *earned by measurement* (plan §3/§11/§14).** The mechanism is built; a **readiness gate keeps it locked by default**. INV1 is *relaxed, not removed*: human review is **deferred to PR + merge**, never eliminated — nothing merges unattended.

`$1` = comma-separated Issues (like `batch`) · empty = all open qualifying · `--readiness` = show the readiness score only (never runs).

> **Bash**: `_bash_rules.md`. Mechanism reuses `<<SKILL_DIR>>/commands/batch.md` (unattended dev) + `<<SKILL_DIR>>/commands/evolve.md` (Outer loop). Handoff: `_handoff.md`.
> **Output language**: all human-readable output in `config.language` (`_handoff.md` Section K).
> ⚠️ **Security**: a passed gate runs unattended tool execution (inherits batch's `--dangerously-skip-permissions`). Only reachable when the readiness gate + explicit opt-in both pass.

---

## Phase 0 — Readiness gate (the lock — always checked FIRST)
**Check whether `$1 == "--readiness"` first, before anything else in this phase** (per the header: `$1` is either a comma-separated Issue list, empty, or the literal `--readiness`). Compute the score below regardless, but if `$1 == "--readiness"`, **report the score and stop unconditionally right after** — do not fall through to the `< 100%`/`100%` branching below, and do not enter Phase 1 even if the score happens to read 100% (the flag means "show me the number," never "run"). Otherwise (`$1` is an Issue list or empty), proceed to the normal branching below.

Compute a readiness score from **measured** signals (never self-assessment — plan §11 "자율은 측정으로 벌어서 얻는다"):
- **Autonomy prerequisites (hard)** — test automation present + CI runs tests on PRs (both from `audit`/readiness data + config `commands`) + **a review path exists**, measured directly (its own read-only Bash call — `atoms/audit_readiness.md`'s 5 groups don't check this, so it can't be folded into that scan): `gh pr list --repo <owner>/<repo> --state merged --limit 20 --json reviews --jq '[.[] | select((.reviews | length) > 0)] | length'` — **> 0** (at least one recent merged PR carried a real review) means the repo actually has a working review path; `0` (or no merged PRs yet) → not measurable as present, treat as missing. **Any missing → NOT ready** (can't run unattended safely).
- **Per-agent scorecard trend (360/HR — depends on `evolution-log` scorecard, plan §11)** — roles' ground-truth-anchored performance stable/improving. **No scorecard data yet → NOT ready** (insufficient basis; this is the common early case).
- **Human-correction-rate trend (⑤ ledger friction snapshots)** — corrections/overrides **declining** across recent evolve runs. **Rising, flat, or no data → NOT ready.**

Score = fraction of thresholds met.
- **< 100% (the default state)** → **DO NOT RUN.** Report: *"자율 실행 준비 <X>%. 남은 조건: <미충족 목록>. 지금은 `/gld batch`(무인 dev + 사람이 PR 리뷰)를 쓰세요."* **Stop.** Building sprint locked is safe — the data must permit it.
- **100% AND explicit user opt-in** (a `--readiness`-shown score of 100% + a confirmed "yes, run autonomously") → Phase 1.

## Phase 1 — Autonomous run (only past the gate + opt-in)
- **Inner loop** — drive the queue through the spine unattended to `guild:done` + PR, reusing `batch.md`'s supervisor exactly as it exists today: rate-limit resume, `GLD_UNATTENDED` leader-proxy gates, label-based completion, `guild:needs-human` pauses. ⚠ **Honest gap**: `batch.md` has **no branch isolation** (children of one Issue process sequentially in the same checkout — the "run in a git worktree" advice is a manual human mitigation, not automated per-Issue isolation), **no checkpointing**, and **no regression-detection/auto-halt mechanism** — an earlier version of this doc claimed all three ("Branch isolation + checkpoints; stop on a regression (T2)"), but none of them exist anywhere in this plugin (`T2` was never defined either). A `FAILED` Issue in the queue does not stop the run; the supervisor just moves to the next Issue. Until one of these is actually built, sprint's Phase 0 readiness gate should be read as "measured autonomy prerequisites are met," **not** "a regression-safety net exists" — the two are currently different claims, and only the first is true.
- **Outer loop** — run `evolve` after the Inner pass, **`--dry-run` only** — self-modification is **never** unattended (§8/§11); evolve *proposals* are queued for the human, not applied.
- All **6 invariants** hold (INV1 = PR gate / nothing merges · INV2 = no verification weakening · INV3 = reversible · …).

## Phase 2 — Report
What ran (done / paused-needs-human / incomplete / failed — label-truthful, per batch), PRs opened (awaiting human review + merge), evolve proposals queued (`--dry-run` output), and the readiness score at run time.

## Hard rules
- **Locked by default; autonomy is earned** (§11) — the gate refuses until prerequisites + scorecard-trend + declining-correction-rate all pass. Never bypass the gate.
- **Nothing merges unattended** (INV1) — PR gate; the human reviews + merges after. The deferral is the *only* INV1 relaxation.
- **evolve apply is never unattended** (self-mod is always HITL) — sprint runs evolve `--dry-run` and queues proposals.
- **Off-switch + all 6 invariants** apply. **No regression-auto-halt exists** (see Phase 1's honest-gap note above — "T2" was a fabricated reference, never implemented anywhere in this plugin); a `FAILED` Issue does not stop the queue today.
