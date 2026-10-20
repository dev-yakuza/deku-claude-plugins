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
| script | script writer | script · `claims-map.json` | `s2v lint` |
| verify | fact-checker | `verify.json` · `verify.md` | no unsupported or contradicted claim · `check_claims` |
| ① | person | approved content | approval record |
| cast | producer / casting director | cast, pronunciation, faces | `s2v lint` · content hash unchanged · `check_assets --actors` |
| tts | producer | audio lock | machine lock (tts) · `check_tts` (or failures handed to ②) |
| audition | producer | audition clips | — |
| ② | person | approved voice and audio | approval record |
| board | visual director | presentation attributes · `board.md` | `s2v check` · content and voice hashes unchanged · `check_assets` |
| visual-check | producer | stills per output | — (frozen audio, no machine lock) |
| ③ | person | approved presentation (per output) | approval record |
| render | producer | video, subtitles, thumbnail, chapters per output | `--frozen-audio --out-dir`; exit code and file sha per output |
| ④a | person | approved render (per output) | approval record |
| copy | distributor | `copy/<video-id>/<lang>/<platform>.md` | `validate_copy` · verify of the copy |
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
prints `hash12` → AskUserQuestion with the fixed label `승인 <hash12>` (other options: changes,
or `거부 <hash12>` for a source diff) → only on that label, `state.py approve <video> <gate> --expect
<hash12>` once. Anything changed after showing (upstream included) needs showing again. `source` and `brief` have their own records (the frozen copy,
`record-brief`).
Each person gate is approved only with a fixed answer `승인 <hash12>` (in the repo's language
the label stays this token) to an `AskUserQuestion` that showed the artifact and its hash.
