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


# K2r3-M2: EXACT-value redaction for secrets the engine knows by value — the string literals of
# the git-ignored files a repo lets the TEST effective re-run copy (`copy_ignored`), with their
# base64 (standard and url-safe, all three byte alignments) and hex forms. Registered once per
# engine process; every `redact()` after that removes them, whatever the surrounding text.
_EXACT = set()
LITERAL_RE = re.compile(r"\"([^\"\\\n]{16,})\"|'([^'\\\n]{16,})'|`([^`\n]{16,})`")
EXACT_MIN = 16


def encodings(value):
    import base64
    import binascii
    b = value.encode("utf-8")
    out = {value, binascii.hexlify(b).decode(), binascii.hexlify(b).decode().upper()}
    for pad in (0, 1, 2):                 # the value at any byte offset inside a larger b64 blob
        for enc in (base64.b64encode, base64.urlsafe_b64encode):
            e = enc(b"\0" * pad + b).decode().rstrip("=")
            head = (pad * 8 + 5) // 6 if pad else 0      # chars touched by the padding bytes
            core = e[head:len(e) - 3] if len(e) - head > 3 else ""
            if len(core) >= EXACT_MIN:
                out.add(core)
    return out


def literals(text):
    return [next(g for g in m.groups() if g) for m in LITERAL_RE.finditer(text or "")]


def register_exact_from_files(root, rels):
    """Read each listed file under `root` (text only — a binary file is skipped), collect its
    string literals of ≥ 16 chars and register them and their encodings. Returns the count."""
    n = 0
    for rel in rels or []:
        try:
            with open(os.path.join(root, rel), "rb") as fh:
                data = fh.read(2 * 1024 * 1024)
        except (IOError, OSError):
            continue
        if b"\0" in data:
            continue
        for v in literals(data.decode("utf-8", "replace")):
            for e in encodings(v):
                if len(e) >= EXACT_MIN and e not in _EXACT:
                    _EXACT.add(e)
                    n += 1
    return n


def clear_exact():
    _EXACT.clear()


def _exact(out):
    for v in sorted(_EXACT, key=len, reverse=True):
        if v in out:
            out = out.replace(v, REPLACEMENT)
    return out


def redact(text):
    """Redact ONE value (a field, an item, or one prose body). Callers never pass a whole
    multi-field block: a key anywhere replaces everything they passed."""
    out = text or ""
    if KEY_VALUE_RE.search(out):
        return REPLACEMENT
    if _EXACT:
        out = _exact(out)
    for rx in patterns():
        out = rx.sub(REPLACEMENT, out)
    return out


def has_secret(text):
    t = text or ""
    return (bool(KEY_VALUE_RE.search(t)) or any(rx.search(t) for rx in patterns())
            or any(v in t for v in _EXACT))
