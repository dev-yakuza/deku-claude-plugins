# LEARNING (③ growth engine — the human overseer, shared contract)

**Not a stage.** The contract for Guild's **third co-evolution engine: growing the human overseer.** Guild's heart co-evolves the **product** (Inner loop → codebase) and the **developer** (Outer loop → agent org). This adds the **overseer** (the human) as a third growth target (plan §1 three-way co-evolution · §16 overseer member). Read by `review` (A/D/F), `evolve` (B), `analyze`/`design` (D + self-explanation), `onboard` (C), and `_preflight` (E).

> **Design principle — embed, don't ceremony.** Human growth must be a **side effect of normal usage** (review, evolve, dev), not a separate ritual — a dedicated-only command would never get run and the overseer would never grow. Only `onboard` (C) is a standalone (a new maintainer *intends* to ramp up). Everything else rides inside commands the human already runs.

---

## Section A — The overseer as a distinguished org member (§16 extension)

Model the human as a member of the org — but an **authority-tier** one, categorically different from agents:
- **Tracked in the 360° scorecard** (evolve Phase 2.5) — the overseer's *decision patterns* (discuss overrides, accepted-risks, PR approvals/rejections, recurring blind spots, competence trend) are recorded alongside agents. This unifies the data (the human is already the highest-weight ground-truth source; now their patterns are a first-class row).
- **NOT file-defined** — agents are `.claude/agents/*.md` that evolve rewrites; a human is not a file. So the overseer's growth is **teaching/insight the human internalizes**, never a git-committed patch.
- **NOT HR-able** — no hire/retire/replace/promote (§16 C3 is for agents). The overseer is the top authority (INV1), the *source* of ground truth, not a subordinate to performance-manage.

## Section B — Safety (the hard rules — a HIGHER bar than agent-facing)

Teaching a human is more dangerous than teaching an agent: the human **trusts, generalizes, and propagates** a lesson, and acts on it with real authority. So:
1. **Ground-truth-anchored, always.** Every lesson traces to a **verified outcome** (a test/gate/CI result, a real defect, a revert) or **curated authority** (a `confirmed` standard, an evidence-anchored ⑥ fact). **AI opinion is NOT a lesson.** An unanchored observation is surfaced at most as *"인사이트 후보 (미검증 — 직접 확인 필요)"*, never as fact.
2. **Advisory · opt-in · non-condescending.** Frame as *"이런 인사이트가 있습니다"*, never *"당신이 틀렸습니다"*. The human's authority (INV1) is untouched; they can dismiss any insight. No nagging.
3. **Read-only toward the human.** Guild never "fixes" the human — it reflects, teaches, and asks. No behavioral coercion.

## Section C — The six techniques (A–F) + where each lives

| # | Technique | Lives in | What it does |
|---|---|---|---|
| **A** | **Craft transfer** (didactic — the WHY) | `review`, dev narration | Explain not just the local *what* but **name the underlying principle** ("this is the WCAG-contrast principle", "the panel dropped P3 because it duplicated an existing rule") → the human learns spec-driven / verification / a11y / architecture. |
| **B** | **Pattern reflection** (metacognition) | `evolve` (감독자 회고 report) | From the 360 overseer scorecard, reflect recurring decisions/blind spots + the principle behind them ("WCAG 위험을 3회 수용 — 근본 원리는…"). The human sees their own patterns. |
| **C** | **Codebase mastery** (onboarding) | `onboard` (standalone) | Guided tour of *the human's own system* — ⑥ knowledge, hotspots, charter, architecture. Ramps a new maintainer. |
| **D** | **Predict-before-reveal** (active recall / prediction-error) | `review`, `analyze`/`design` discuss | **Before** revealing the answer, ask the human to predict/reason ("이 diff에서 뭐가 위험해 보이세요?" before the adversarial findings; "어떻게 하시겠어요?" before the leader recommendation). The **gap** is where learning happens (surprise drives it — §8-A applied to the human). Turns A's passive telling into active learning. |
| **E** | **Just-in-time reinforcement** (spaced, timely) | `_preflight` (dev/review) | When the touched area matches a **recurring overseer blind spot** (from the scorecard/ledger), surface that one lesson **at the moment of relevance** — right before they'd repeat it — not buried in a periodic report. |
| **F** | **Adaptive fading** (scaffolding → fading) | `review`, dev narration | Scale teaching **depth to the overseer's competence trend** (360). Early / low-competence-in-area → full worked explanation. Rising competence → **fade** the hand-holding (a one-line pointer, or silence) so the human takes over. Prevents both over- and under-explaining. |

**+ Self-explanation capture** (self-explanation effect — dual-purpose): at a discuss/approval decision, invite a one-line *"왜 이 선택을?"*. Articulating solidifies the human's learning **and** yields a higher-quality signal (the human's reasoning → the ground-truth log / 360). Optional, never forced.

## Section D — The overseer 360 scorecard (data for B/E/F)

evolve Phase 2.5 records an **overseer row** alongside the agent scorecards, ground-truth-anchored:
- **Decision patterns**: recurring discuss-overrides (by theme), accepted-risks (measured defects knowingly kept), PR rejection reasons, repeated questions (`ask`).
- **Blind spots**: a pattern where the human's decision was later contradicted by an objective outcome (a kept risk that caused a real defect; an override that was reverted). ⚠ anchor to the outcome, not to "the agent disagreed."
- **Competence trend (per area)**: is the human's decision quality in an area improving (fewer corrections needed, faster good calls)? Feeds F (fading) + B (report).
- **Weak sample caveat**: like agent scorecards, advisory until corroborated across runs. Never a single-run judgment.

## Hard rules
- **Ground-truth or abstain** — no unanchored "lesson" to the human (Section B.1). Higher bar than agent-facing.
- **Embed, don't ceremony** — A/B/D/E/F ride inside review/evolve/discuss/dev (passive growth); only C (`onboard`) is standalone.
- **Advisory, opt-in, non-condescending, read-only toward the human** — the overseer is the authority, not a managed subordinate.
- **Fade with competence** — teaching depth is adaptive (F), so a skilled overseer isn't lectured.
