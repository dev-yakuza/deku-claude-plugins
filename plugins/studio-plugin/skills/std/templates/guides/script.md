# Script guide

How this repository's videos are written. The script writer reads it; edit it as the channel finds its voice.

- Say what the source says. Every claim in the narration maps to an excerpt of the source (`claims-map.json`).
- One idea per scene; a scene title is a short noun phrase.
- Narration is for the ear: short sentences, no parentheses, numbers as they are spoken. Write dates and hours with
  digits (`5일`, `3시`): Studio's number check reads them reliably.
- Text in another script or language (for example Japanese in a Korean video) goes on screen (`:::quote`, `:::table`,
  captions); the narration reads it in the video's language.
- Images: only the ones the source analysis marks usable, by their `script_src` path, as a block of their own:
  `::image{src="<script_src>"}` (s2v shows no Markdown image `![…](…)` on its own line — it is an error).
- Every scene needs a visual, and its first visual is what shows from the scene's start: `::title[…]` with a label, a
  text card (`:::bullets`, `:::quote`, …) or an image. A scene with only narration shows the bare background — s2v
  warns `no-visual` and Studio's check fails. A `::title[…]` goes after the scene's last paragraph (it still shows
  from the scene's start; sentence ids stay). When an image is dropped (its license is unusable), replace it with
  `::title[…]` or a text card here, at the script stage: board cannot add or remove blocks.
- A title's label is on-screen text, judged at ① like the narration: reuse the scene heading or a sentence of the
  claims map rather than a new statement.
- Length: `outputs.youtube.maxDuration` is the format's upper bound and `targetDuration` the brief's length; s2v lint
  only warns past them, Studio's check fails.
- The claims map (`work/<lang>/claims-map.json`): every claim the script uses, its excerpt exactly as in `source.md`,
  and the sentences that say it.
