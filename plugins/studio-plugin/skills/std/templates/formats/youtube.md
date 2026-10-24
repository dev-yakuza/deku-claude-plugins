---
format: youtube
---
# Format: YouTube (16:9)

The criteria Studio's checks read for a `youtube` video. **Only a person changes this file** (the guard protects it;
a change shows up in the harness commit question). The values are starting points: the first real sessions measure them
(m1-plan Q1 · Q2), then a person edits them here.

<!-- studio:criteria -->
```json
{
  "length_seconds": {"min": 180, "max": 480},
  "chars_per_sec": {"ko": 5.5, "ja": 7.0, "en": 14.0},
  "cer_max": {"ko": 0.15, "ja": 0.15, "en": 0.1}
}
```
<!-- /studio:criteria -->

- `length_seconds`: the narration's length range. The brief's estimate (normalized characters of the chosen excerpts ÷
  `chars_per_sec`) must fall in it.
- `chars_per_sec`: normalized characters spoken per second, per language (ko measured by the first sessions).
- `cer_max`: the largest ASR round-trip character error rate a synthesized sentence may have (s2v's take checks use
  the same values).
