"""guildcore.records.redact — INV5 scrub, the last step of every engine-rendered block (§2.0).

The pattern set is NOT copied: it is `INLINE_SECRET_RES` of the commit gate
(`skills/gld/gates/gate_precommit.py`), the repo's single definition of "what counts as a secret"
(see the comment above its `--scan-text` mode — two copies drift). A missing/unloadable gate is
an error, never "nothing to redact".
"""

import importlib.util
import os
import re

REPLACEMENT = "[REDACTED]"
_GATE = os.path.join(os.path.dirname(__file__), "..", "..", "..", "gates", "gate_precommit.py")
_PATTERNS = None


def patterns():
    global _PATTERNS
    if _PATTERNS is None:
        spec = importlib.util.spec_from_file_location("_guild_gate_precommit", os.path.abspath(_GATE))
        if spec is None or spec.loader is None:
            raise RuntimeError("commit gate not found at %s — cannot redact" % _GATE)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _PATTERNS = list(mod.INLINE_SECRET_RES)
    return _PATTERNS


# Redaction-only extensions (the gate's patterns detect; these also SPAN what must go). A PEM
# private key: the gate matches its BEGIN line, redaction must take the body to its END line (or
# the end of the text when the END line is missing) — K0-M1.
REDACT_EXTRA = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)"),
]


def redact(text):
    out = text or ""
    for rx in REDACT_EXTRA:
        out = rx.sub(REPLACEMENT, out)
    for rx in patterns():
        out = rx.sub(REPLACEMENT, out)
    return out


def has_secret(text):
    return any(rx.search(text or "") for rx in patterns())
