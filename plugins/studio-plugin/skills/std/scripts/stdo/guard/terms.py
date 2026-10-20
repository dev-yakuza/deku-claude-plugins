"""Studio term matching and string-literal extraction (m0d1a-plan §4.5).

`Terms(words, paths, names)`: M0d-1b builds the lists per repository (or a generic set when a
harness or marker exists but the target repository is unknown). Matching runs on NFC text,
case-folded when `fold` is set (case-insensitive volumes).
"""

import re
import unicodedata

from .model import Hit

_WORDCH = re.compile(r"[A-Za-z0-9_]")
_PATH_BEFORE = set(" \t\n/'\"=:;(){}|&<>`$,")
_PATH_AFTER = set(" \t\n/'\";(){}|&<>`,")


def _norm(text, fold):
    t = unicodedata.normalize("NFC", text)
    return t.casefold() if fold else t


class Terms(object):
    def __init__(self, words=(), paths=(), names=(), fold=False):
        self.words = [w for w in words if w]
        self.paths = [p.strip("/") for p in paths if p and p.strip("/")]
        self.names = [n for n in names if n]
        self.fold = fold

    def __bool__(self):
        return bool(self.words or self.paths or self.names)

    __nonzero__ = __bool__

    def find(self, text, limit=50):
        """Hits in `text` (empty when text is None)."""
        if not text or not self:
            return []
        t = _norm(text, self.fold)
        out = []
        for kind, items in (("word", self.words), ("name", self.names), ("path", self.paths)):
            for term in items:
                n = _norm(term, self.fold)
                start = 0
                while len(out) < limit:
                    i = t.find(n, start)
                    if i < 0:
                        break
                    start = i + 1
                    before = t[i - 1] if i > 0 else ""
                    after = t[i + len(n)] if i + len(n) < len(t) else ""
                    if kind in ("word", "name"):
                        # a name may follow a path separator (`work/v/state.json`)
                        if before and (_WORDCH.match(before) or (kind == "word" and before in ".-")):
                            continue
                        if after and (_WORDCH.match(after) or (kind == "word" and after == "-")):
                            continue
                    else:
                        if before and before not in _PATH_BEFORE:
                            continue
                        if after and after not in _PATH_AFTER:
                            continue
                    out.append(Hit(term, kind, i))
        out.sort(key=lambda h: h.offset)
        return out


_LIT = re.compile(r"'((?:[^'\\\n]|\\.){0,4096})'|\"((?:[^\"\\\n]|\\.){0,4096})\"|`([^`]{0,4096})`")


def literals(text, limit=500):
    """String literals in code (Python/JS/shell quoting, heuristic)."""
    if not text:
        return []
    out = []
    for m in _LIT.finditer(text):
        s = next(g for g in m.groups() if g is not None)
        out.append(s)
        if len(out) >= limit:
            break
    return out
