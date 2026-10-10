# CONTRIBUTE — send a flow improvement upstream (`/hrd contribute`)

The only outbound path (INV5). Ported from Guild `contribute.md`.

1. Candidates: evolve proposals marked "flow-level" in `evolution-log.md` (improvements to
   Herald itself, not to this repo's guides).
2. Sanitize: deterministic secret scan of the text; remove repo/owner names, slugs, URLs,
   article text, topic ids and run numbers; keep only the general improvement.
3. Dedup: search the plugin repository's issues (`gh issue list -R dev-yakuza/deku-claude-plugins
   --search "<keywords>"`).
4. Show the human the final text; send only on explicit approval
   (`gh issue create -R dev-yakuza/deku-claude-plugins --label herald --body-file <tmp>`).
