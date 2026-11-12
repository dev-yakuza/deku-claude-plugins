# Script guide

How this repository's videos are written. The script writer reads it; edit it as the channel finds its voice.

- Say what the source says. Every claim in the narration maps to an excerpt of the source (`claims-map.json`).
- One idea per scene; a scene title is a short noun phrase.
- Narration is for the ear: short sentences, no parentheses, numbers as they are spoken. Write dates and hours with
  digits (`5일`, `3시`): Studio's number check reads them reliably.
- Text in another script or language (for example Japanese in a Korean video) goes on screen (`:::quote`, `:::table`,
  captions); the narration reads it in the video's language.
- Images: only the ones the source analysis marks usable, by their `script_src` path, as a block of their own:
  `::image{src="<script_src>"}` (s2v shows no Markdown image `![…](…)` on its own line — it is an error). Show every
  usable image where it fits; one left out goes in the claims map's `unused_images` with a one-line reason, which the
  person reads at ①.
- Scene 1 is the title scene: the hook in one or two sentences and one visual, `::title[<the frontmatter title>]`,
  after its narration. s2v takes the thumbnail from it, so the thumbnail says what the video is. A title scene shorter
  than 10 seconds joins the next chapter in the chapter list (YouTube's minimum chapter length). Only `#` (level 1)
  headings start scenes.
- The layout is board's: the script names no `layout` (board sets it and the script keeps it).
- Every scene needs a visual, and its first visual is what shows from the scene's start: `::title[…]` with a label, a
  text card (`:::bullets`, `:::quote`, …) or an image. A scene with only narration shows the bare background — s2v
  warns `no-visual` and Studio's check fails. A `::title[…]` goes after the scene's last paragraph (it still shows
  from the scene's start; sentence ids stay). When an image is dropped (its license is unusable), replace it with
  `::title[…]` or a text card here, at the script stage: board cannot add or remove blocks.
- A title's label is on-screen text, judged at ① like the narration: reuse the scene heading or a sentence of the
  claims map rather than a new statement.
- Frontmatter: the lines `state.py next <video> --enter script` prints, exactly — the default narrator's `cast:`
  block (part of the script from the start: s2v's content hash includes it) and `outputs.<output>` with `aspect` and
  `maxDuration`.
- Length: `outputs.youtube.maxDuration` is the format's upper bound. `targetDuration` comes from the brief's estimate,
  within the printed range: s2v lint passes a script within ±15 % of it, and only that range keeps s2v's own estimate
  inside the format's range. Too short: lengthen with claims from the brief, never by lowering `targetDuration` below
  the range. s2v lint only warns past them, Studio's check fails.
- The claims map (`work/<lang>/claims-map.json`): every claim the script uses, its excerpt exactly as in `source.md`,
  and every text of the script that says it — narration sentences, on-screen text (table cells, bullets, captions,
  quotes) and titles that state something. Write it whole with one Write; on a change, rewrite it with one Write.
