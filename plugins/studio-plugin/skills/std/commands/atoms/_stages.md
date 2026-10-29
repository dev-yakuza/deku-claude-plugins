# Stage spine

Status: contract only (M0). Entry checks, hashes and routing are implemented by `state.py`
(M0b); the stage procedures are written with M1.

```
source → brief → script → verify ─[①]→ cast → tts → audition ─[②]→ board → visual-check ─[③]→ render ─[④a]→ copy ─[④b]→ commit
```

| Stage | Owner | Output | Exit (deterministic checks) |
|---|---|---|---|
| source | source analyst | `source/` (pinned copy) · `source.md` · `source_hash` | `check_scope` · `resolve_assets` |
| brief | content strategist | `brief.md` · `brief_core` · output list | expected length within the format · `state.py record-brief` |
| script | script writer | script · `claims-map.json` | `check_claims --narration` (s2v lint with its length warnings, claims map, narration, images) |
| verify | fact-checker | `verify.draft.json` → `verify.json` · `verify.md` (written by `check_claims`) | no unsupported or contradicted claim · `check_claims` |
| ① | person | approved content | approval record |
| cast | producer / casting director | cast, pronunciation (`pronounce-changes.json`), faces | `check_assets --actors` (s2v lint, content hash unchanged, the roster, the readings) |
| tts | producer | audio lock | machine lock (tts) · `check_tts` (failures retried twice, then exempted and shown at ②) |
| audition | producer | `narrator.wav` · `audition.md` | `audition.py` (its check file) |
| ② | person | approved voice and audio (the question shows each exempted line and reading change) | approval record · `pronounce-approved.json` |
| board | visual director | presentation attributes · `board.md` · `CREDITS.draft.yaml` → `CREDITS.yaml` (`state.py credit`) | `check_assets --output` (s2v check · content and voice unchanged · every picture usable, unchanged and credited) |
| visual-check | producer | stills per output | — (frozen audio, no machine lock) |
| ③ | person | approved presentation (per output) | approval record |
| render | producer | video, subtitles, thumbnail, chapters per output | `--frozen-audio --out-dir`; exit code and file sha per output |
| ④a | person | approved render (per output) | approval record |
| copy | distributor | `copy/<video-id>/<lang>/<platform>.md` · claims-map `copy_excerpts` (fact-checker) | `validate_copy` (platform rules checked by a person · limits · notices · credits · chapters · excerpts) |
| ④b | person | approved copy (per platform) | approval record |
| commit | producer | one commit per language | every hash and approval matches · `check_commit` |

Every stage calls `state.py next --enter <stage>` on entry: when an upstream hash differs from its
approved value, the flow goes back to the stage that must be redone and never past it.
**Every stage calls `state.py stage-done <stage> [--output o | --platform p]` at its exit** (after its
deterministic checks passed). That records the stage's completion against its section's current
hashes, so the next stage of the section (up to the gate) may be entered even while the gate's
approval is stale; a later change of those hashes makes the record stale again. `stage-done`
records no person's decision (the guard treats it as evidence-free); gates are approved only with
`state.py approve` (M0b-2).

**A person gate**: `state.py shown <video> <gate> [--output o | --platform p]` for every scope as the artifact
is shown (③: `--begin` right before the snapshot and `--end` right after it) → the last `shown`
prints `hash12` → AskUserQuestion whose text starts with `[<video>]` and shows the hash, with the fixed label
`승인 <video> <hash12>` (other options: changes, or `거부 <video> <hash12>` for a source diff) → only on that label,
`state.py approve <video> <gate> --expect <hash12>` once — **in a later message than the question, never in the same message** (the guard refuses an
approval sent together with its question). Anything changed after showing (upstream included) needs showing again. `source` and `brief` have their own records (the frozen copy,
`record-brief`).
Each person gate is approved only with a fixed answer `승인 <video> <hash12>` (in the repo's language
the label stays this token) to an `AskUserQuestion` that showed `[<video>]`, the artifact and its hash. The hash12
covers the video, the language and the gate, so two videos with the same content still have different labels.
