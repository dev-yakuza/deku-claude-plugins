# CONTRIBUTE — not available yet (`/hrd contribute`)

Sending flow improvements upstream is **not supported in this version**. The outbound path
needs a deterministic secret scanner and a durable candidate list, and neither exists yet; a
prompt-only "scan" would be a promise the code cannot keep (INV5).

When invoked: say in `config.language` that contribute is not available yet, and that
flow-level ideas (improvements to Herald itself — e.g. the auditor's prompt or severity scale)
can be opened by hand as an issue on the plugin repository
(`dev-yakuza/deku-claude-plugins`, label `herald`) after the human removes repo names, slugs,
URLs, article text and topic ids. Do not run `gh issue create` from this command; send nothing.
