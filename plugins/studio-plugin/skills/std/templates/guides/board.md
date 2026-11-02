# Board guide

How this repository's videos look. The visual director reads it.

- Brand: name, accent color and logo come from `.claude/studio/brand.json`: the accent goes to `theme.accent`, the logo
  to `logo.src` — the lines `check_assets.py <video> --look --output <output>` prints.
- Board changes how the script looks: the frontmatter's `theme`, `logo`, `outputs.<output>.layout` and `transition`,
  and the attributes of the blocks already there. Images and text cards are decided at the script stage: board never
  adds, removes or swaps a block, and never changes text, cast or pronounce (they are in the content and voice hashes
  approved at ① and ②).
- No presenter layout without character art: s2v draws no one, so the layout is `fullscreen` (the `--look` line).
- An image the source analysis does not allow (scope and credits) is reported, not removed: the script stage
  replaces it with `::title[…]` or a text card.
- One visual idea per scene; keep subtitles readable (s2v check must pass).
