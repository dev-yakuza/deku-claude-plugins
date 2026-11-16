"""guildcore.records — one module per record kind, each a parse/render pair (§2.0).

Parsers keep every byte (`render(parse(x)) == x`); renderers build NEW blocks the way the 0.101.x
prose writes them, with the §6.2 intentional changes (C1 `head:`, C2 `[id:F<k>]`, C4 decisions,
C5 `ran-at:`, C12 recheck note, C13 answer hint, C14 unattended-log markers), and end in
`redact()` (INV5).
"""
