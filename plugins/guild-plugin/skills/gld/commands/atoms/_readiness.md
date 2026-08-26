# READINESS (shared contract — is this Issue clear enough to design/build?)

**Not a stage.** Operationalizes the analyze **discuss gate** (`analyze.md` Step 1) with an explicit **per-dimension** clarity check, replacing a single holistic "is this ambiguous?" call with three named dimensions — so a gap in *one* dimension (success criteria, say) can't hide behind an otherwise-clear goal. Symmetric in spirit to `_data_sufficiency.md` (a tiered gate + banner for a different axis — spec readiness instead of growth-signal volume), but the mechanism differs on purpose (Section B) because the source of judgment differs.

> **Why not a numeric 0–1 score.** A single LLM self-rating a float like `0.81` implies a precision it does not have. Guild already uses coarse, honest tiers elsewhere (`_data_sufficiency.md`'s `none`/`shallow`/`sufficient`) — this reuses that idiom: three levels per dimension, not a weighted formula.

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

Each dimension gets one of three levels: **`clear`** (proceed) / **`partial`** (proceed, but the gap MUST be recorded as an explicit assumption) / **`unclear`** (material ambiguity, same as today's holistic trigger).

Boundary between `partial` and `unclear`. `clear` means the Issue already
answers the dimension outright. Below that:
- **partial** — the gap is real, but you can narrow it to one assumption a
  reader could challenge, because something in reach points at one reading:
  the charter, the Issue's own AC, existing code, or — when the Issue is simply
  silent — the repo's established default for this kind of decision.
- **unclear** — the readings are defensible enough that picking one is a
  product decision only the requester can make, and nothing in reach breaks
  the tie.
When a gap sits between the two, rate it **partial** and record the assumption;
Section C already requires that assumption to appear in Step 1's list, which is
where a reader challenges it.

> **These three level values are MACHINE TOKENS** — ASCII, never localized, exactly like the `RESULT` keywords and `guild:*` labels in `_handoff.md` Section K. The gate below and every consumer (`analyze.md`) branch on `clear`/`partial`/`unclear` verbatim, so they must read the same on an `en`, `ko`, or `ja` repo. What the **human reads** — the one-line readiness summary (Section D), the `NEEDS_HUMAN` explanation, the recorded assumption prose — is written in `config.language` like all other human-readable output (Section K). Token ≠ rendered text: the token is what the logic tests, the surrounding sentence is what gets translated.

This is the **same leader that is already making the qualitative call** in Step 1 today — the dimension breakdown does not add a second opinion or a ground-truth claim, it only forces the *existing* judgment to be itemized instead of holistic, so a specific gap can't be smoothed over by an otherwise-confident overall impression. **Self-scoring is not ground truth** (`_signals.md` Section B) — it never by itself produces a `correction`/`surprise` capture; it only shapes whether/how the human is asked, exactly as the pre-existing discuss gate already did.

## Section C — Gate (replaces the holistic trigger in `analyze.md` Step 1)

- **Any dimension `unclear`** → material ambiguity (same consequence as today): **attended** → `NEEDS_HUMAN: <dimension> unclear — <the choice needed>`, naming which dimension(s) so the human sees exactly what's missing instead of a vague "this is ambiguous." **Unattended** (`GLD_UNATTENDED=1`, `_handoff.md` Section H) → stakes classification unchanged, but the recorded assumption/needs-human comment names the dimension.
- **All `clear`/`partial`, none `unclear`** → proceed to Step 2. Every **`partial`** dimension MUST appear in Step 1's assumptions list (already required — this just guarantees a `partial` rating can't be silently dropped).
- **All `clear`** → proceed; note in the output that readiness found no gap (mirrors today's "discuss found no material ambiguity" note).

This composes with, not replaces, Step 1's existing "2–3 substantively different interpretations" requirement — the dimensions are what you're checking clarity *of*; the interpretations are how you resolve a gap once found.

## Section D — Recorded in the output (auditability)

`analyze.md` Step 4 posts a one-line readiness summary in the analysis output. The **level tokens stay ASCII** (`clear`/`partial`/`unclear` — Section B); the **prose around them** (the label, the parenthetical assumption note) is written in `config.language`, e.g. on a `ko` repo:
```
Readiness: Goal=clear · Constraint=clear · Success=partial (가정: 빈 목록 처리는 에러 아님 — AC#3에 명시)
```
and on an `en` repo the same line reads `… Success=partial (assumption: an empty list is not an error — stated in AC#3)`. So a later reader (design's tech-lead, a human reviewing the Issue) sees at a glance which dimension carried a recorded assumption, without re-deriving it from prose — and a tool or a later stage can read the token without knowing the repo's language.

## Hard rules
- **Never a numeric/weighted score** — three levels per dimension, stated plainly.
- **The level values are machine tokens** — always `clear` / `partial` / `unclear`, ASCII, in every repo language (`_handoff.md` Section K). Never branch on a translated label; translate only the sentence that carries the token.
- **Never itself ground truth** — a `partial`/`unclear` rating shapes the gate, it is not logged to `ground-truth.jsonl`; only an actual human override at the resulting discuss gate is (`analyze.md` Step 1's existing capture, unchanged — optionally naming the dimension in `--summary`).
- **Does not add a role or a sub-agent spawn** — this is the leader's own Step 1 judgment, itemized, at zero extra cost.
- **Trivial/unambiguous Issues stay cheap** — three quick ratings, most of them `clear`, is not a heavier gate than today's holistic call; it only prevents a partial gap from being averaged away.
