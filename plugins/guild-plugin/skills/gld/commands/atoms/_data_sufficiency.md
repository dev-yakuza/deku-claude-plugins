# DATA SUFFICIENCY (shared contract — is there enough to grow from?)

**Not a stage.** The single source of truth for **"how much growth-signal has accumulated,"** consumed **three ways** so the growth commands work organically together:
- **evolve → GATE** — blocks / downgrades to dry-run when signal is thin (evolve *mutates* the org/rules/knowledge → shallow data would inject wrong growth).
- **audit → BANNER** — reports the state at the top of its report; **never blocks** (audit is read-only diagnosis — the very tool that tells you you're thin).
- **review → NUDGE** — suggests `/gld evolve` **only when signal is 충분** (so review never nudges evolve to run when evolve would refuse it).

> **Why one atom.** The same accumulation truth drives the gate, the banner, and the nudge. Keeping it in one contract guarantees they stay consistent — review's "evolve 적기입니다" fires on exactly the condition under which evolve will actually proceed (plan 부록 D 항목0).

> **Bash**: simple calls only (`_bash_rules.md`). All reads here are cheap and read-only.

---

## Section A — Two axes (the measure)

Growth readiness has **two independent axes** — conflating them is the mistake:

### Axis 1 — 성장 신호량 (growth signal volume): *is there enough to grow from?*
Count of **distinct anchored** growth-signals available. Sources (all already collected — **no new instrumentation**):
- **Captured ground-truth log** — lines in `.claude/guild/memory/ground-truth.jsonl` (by kind: correction · verify-gap · revert · accepted-risk).
- **Durable signals** — reverts / PR-rejects / recurring CI-failure patterns, from git + `gh` (the same signals `_signals.md` Section E readers surface).

Count = **distinct anchored themes**, deduped by evidence identity (`_signals.md` Section B anchor rule; **exclude AI self-reviews**). Tiers (conservative defaults):

| Tier | Count | Meaning |
|---|---|---|
| **없음** | 0 | nothing to grow from |
| **얕음** | 1–4 | thin — advisory only |
| **충분** | ≥5 | enough to rank above noise |

### Axis 2 — 추세 깊이 (trend depth): *can we tell whether evolution helps (thrashing guard)?*
Source: **prior completed evolve runs** in `.claude/guild/evolution-log.md` (count the run headers). A trend needs ≥2 points.

| Tier | Prior runs | Meaning |
|---|---|---|
| **추세없음** | <2 | no time-series — cannot judge improving/declining |
| **추세있음** | ≥2 | trend is meaningful |

> **The two axes are orthogonal.** A first-ever run can have Axis 1 = 충분 (10 anchored signals) but Axis 2 = 추세없음 (0 prior runs). They gate *different* things (Section C) — do not collapse them into one "얕음."

## Section B — How each consumer computes it (cost-appropriate)

- **evolve** — compute **Axis 1 after Phase 1 scans** (the accurate full count, incl. durable git/CI signals — a repo rich in reverts but empty of captured log is **not** 없음). Axis 2 from the ledger (Phase 0). This is the **authoritative** measure.
- **audit** — cheap proxy: `ground-truth.jsonl` line count + the reverts/CI-gaps it already reads (dimensions E/F) + ledger runs. Label it a proxy.
- **review** — cheapest: `ground-truth.jsonl` line count + ledger runs. A **lower-bound** proxy (may undercount durable) → nudge **conservatively** (under-counting only makes it nudge less, never falsely).

**Budget**: one line-count read of the jsonl + one ledger read. **Never spawn new scans just to compute the banner** — reuse what the caller already has, or the cheap log+ledger proxy.

Count the captured log cheaply (its own Bash call; absent file → 0):
```bash
cat .claude/guild/memory/ground-truth.jsonl
```
(Read the lines and tally by `kind`; a missing file means 0 captured signals — normal early.)

## Section C — What each consumer does with the tiers

### evolve (GATE — the only consumer that blocks, because it mutates)
- **Axis 1 없음** → **HARD BLOCK.** Emit the banner, refuse, and point the human to accumulate traces first: *"성장시킬 ground-truth가 없습니다 — 먼저 `/gld dev`(또는 `batch`)로 실제 작업 흔적을 쌓으세요."* Stop (no proposals).
- **Axis 1 얕음** → **DRY-RUN ONLY.** `--apply` / the approval gate is **refused** → downgrade to dry-run with the reason; every proposal is stamped **`미검증 후보 — 적용 보류`**. The human sees what is accumulating without acting on thin evidence.
- **Axis 1 충분** → apply permitted (still per-item HITL — INV1).
- **Axis 2 추세없음** (independent of Axis 1) → **skip the trend-dependent outputs**: HR proposals (hire/retire/replace/promote), 360 scorecard *verdicts*, and the 감독자 회고 (B) — these need a time-series. **Low-risk applies still proceed** if Axis 1 충분 (adding a ⑥ fact, a small habit refinement — anchored + reversible). ⭐ *This is what breaks the bootstrap deadlock: a first run can apply low-risk anchored changes → the ledger accrues runs → HR/scorecard unlock at run 2. Gating **all** apply on run≥2 would make run 2 unreachable.*
- **Axis 2 추세있음** → all outputs permitted.

### audit (BANNER — read-only, never blocks)
- Print the banner at the **top** of the report. When an axis is low, surface it as a **finding** (*"evolve는 아직 이릅니다 — 신호 N개·run M회"*) but **continue the full diagnosis** — audit is exactly how the human discovers they are thin and what to do about it. Blocking audit would be self-defeating.

### review (NUDGE — advisory, opt-in)
- **Axis 1 충분** → at Step 5 (recap), nudge once: *"이번 PR까지 신호가 충분히 쌓였습니다 (교정 N·run M) — `/gld evolve`로 조직을 성장시킬 적기입니다."*
- **Axis 1 없음/얕음** → **SILENT** (no evolve nudge). Nagging "아직 부족" every review is noise; the audit banner already covers the accumulation question.

## Section D — Banner format (config.language, top of output, ≤3 lines)
```
📊 데이터 충분도: <없음|얕음|충분> · 추세: <없음|있음>
   · 신호 <N> (교정<a>·verify-gap<b>·revert<c>·수용위험<d>) · run 이력 <M>회
   · 영향: <gated actions — e.g. "--apply 거부(dry-run) · HR·성적표·감독자회고 skip">
```
Machine tokens (counts, flags) stay ASCII; prose in `config.language`.

## Hard rules
- **Count only ANCHORED signals** (`_signals.md` Section B) — exclude AI self-reviews (back-patting guard).
- **Only evolve blocks** (it mutates). audit never blocks (read-only diagnosis); review only nudges (advisory).
- **The two axes gate different things** — Axis 1 gates *whether to grow at all*; Axis 2 gates only the *trend-dependent* outputs. Never gate all apply on run history (deadlock).
- **Never trigger new scans** just for the banner — reuse the caller's data or the cheap log+ledger proxy.
- **Sufficiency relaxes the gate; it does not remove the guarantees** — even at 충분, apply is still per-item human-approved (INV1) and reversible (INV3).
- Thresholds are **conservative defaults**; a `/gld config` knob may tune them later (not now).
