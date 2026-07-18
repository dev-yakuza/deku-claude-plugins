# READINESS (shared contract — is this Issue clear enough to design/build?)

**Not a stage.** Operationalizes the analyze **discuss gate** (`analyze.md` Step 1) with an explicit **per-dimension** clarity check, replacing a single holistic "is this ambiguous?" call with three named dimensions — so a gap in *one* dimension (success criteria, say) can't hide behind an otherwise-clear goal. Symmetric in spirit to `_data_sufficiency.md` (a tiered gate + banner for a different axis — spec readiness instead of growth-signal volume), but the mechanism differs on purpose (Section B) because the source of judgment differs.

> **Why not a numeric 0–1 score.** A single LLM self-rating a float like `0.81` implies a precision it does not have. Guild already uses coarse, honest tiers elsewhere (`_data_sufficiency.md`'s 없음/얕음/충분) — this reuses that idiom: three levels per dimension, not a weighted formula.

---

## Section A — Three dimensions

At the discuss gate (`analyze.md` Step 1, after stating assumptions and offering interpretations), the leader rates each dimension against the Issue as understood **at that point**:

| Dimension | Question | Feeds |
|---|---|---|
| **Goal clarity** | Is the *what* and *why* specific enough to act on (not just a symptom or a vibe)? | Step 2 requirement analysis |
| **Constraint clarity** | Are the limits known — scope boundary, non-goals, tech/compat constraints? | Step 2.5 product-owner alignment (if convened) |
| **Success-criteria clarity** | Can "done" be stated as verifiable acceptance criteria, not just a feeling? | Step 2's AC (design's tester builds from these **without seeing the skeleton** — a vague AC here propagates straight into biased-free test design going wrong) |

No fourth "codebase-context" dimension (ouroboros-style brownfield axis) — Guild already handles that separately via ⑥ knowledge retrieval at pre-flight (`_preflight.md` Item 6); conflating it here would double-count.

## Section B — Self-scoring (leader judgment, not ground truth)

Each dimension gets one of three levels: **명확** (clear — proceed) / **부분** (partial — proceed, but the gap MUST be recorded as an explicit assumption) / **불명확** (unclear — material ambiguity, same as today's holistic trigger).

This is the **same leader that is already making the qualitative call** in Step 1 today — the dimension breakdown does not add a second opinion or a ground-truth claim, it only forces the *existing* judgment to be itemized instead of holistic, so a specific gap can't be smoothed over by an otherwise-confident overall impression. **Self-scoring is not ground truth** (`_signals.md` Section B) — it never by itself produces a `correction`/`surprise` capture; it only shapes whether/how the human is asked, exactly as the pre-existing discuss gate already did.

## Section C — Gate (replaces the holistic trigger in `analyze.md` Step 1)

- **Any dimension 불명확** → material ambiguity (same consequence as today): **attended** → `NEEDS_HUMAN: <dimension> unclear — <the choice needed>`, naming which dimension(s) so the human sees exactly what's missing instead of a vague "this is ambiguous." **Unattended** (`GLD_UNATTENDED=1`, `_handoff.md` Section H) → stakes classification unchanged, but the recorded assumption/needs-human comment names the dimension.
- **All 명확/부분, none 불명확** → proceed to Step 2. Every **부분** dimension MUST appear in Step 1's assumptions list (already required — this just guarantees a 부분 rating can't be silently dropped).
- **All 명확** → proceed; note in the output that readiness found no gap (mirrors today's "discuss found no material ambiguity" note).

This composes with, not replaces, Step 1's existing "2–3 substantively different interpretations" requirement — the dimensions are what you're checking clarity *of*; the interpretations are how you resolve a gap once found.

## Section D — Recorded in the output (auditability)

`analyze.md` Step 4 posts a one-line readiness summary in the analysis output, e.g.:
```
Readiness: Goal=명확 · Constraint=명확 · Success=부분 (가정: 빈 목록 처리는 에러 아님 — AC#3에 명시)
```
So a later reader (design's tech-lead, a human reviewing the Issue) sees at a glance which dimension carried a recorded assumption, without re-deriving it from prose.

## Hard rules
- **Never a numeric/weighted score** — three levels per dimension, stated plainly.
- **Never itself ground truth** — a 부분/불명확 rating shapes the gate, it is not logged to `ground-truth.jsonl`; only an actual human override at the resulting discuss gate is (`analyze.md` Step 1's existing capture, unchanged — optionally naming the dimension in `--summary`).
- **Does not add a role or a sub-agent spawn** — this is the leader's own Step 1 judgment, itemized, at zero extra cost.
- **Trivial/unambiguous Issues stay cheap** — three quick ratings, most of them 명확, is not a heavier gate than today's holistic call; it only prevents a partial gap from being averaged away.
