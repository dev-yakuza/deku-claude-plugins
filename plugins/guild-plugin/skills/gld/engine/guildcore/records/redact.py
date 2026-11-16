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


# A private key is never pattern-matched body by body (K0-M1/B2/M7 flip-flopped between leaking
# and over-erasing). The rule: redaction runs PER VALUE, and a value that contains a private-key
# header anywhere — PEM in any flavor (RSA/EC/DSA/OPENSSH/ENCRYPTED, indented, quoted, with
# headers or blank lines) or a PuTTY key file — is replaced WHOLE by the token. Record structure
# survives because every other field is a separate value; a renderer whose only free text is one
# prose value (a pause body) loses that whole prose — a pasted key must not be posted.
KEY_VALUE_RE = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----|PuTTY-User-Key-File-\d+:")


def redact(text):
    """Redact ONE value (a field, an item, or one prose body). Callers never pass a whole
    multi-field block: a key anywhere replaces everything they passed."""
    out = text or ""
    if KEY_VALUE_RE.search(out):
        return REPLACEMENT
    for rx in patterns():
        out = rx.sub(REPLACEMENT, out)
    return out


def has_secret(text):
    t = text or ""
    return bool(KEY_VALUE_RE.search(t)) or any(rx.search(t) for rx in patterns())
