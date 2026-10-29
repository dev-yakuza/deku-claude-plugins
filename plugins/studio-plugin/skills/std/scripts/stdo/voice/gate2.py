"""The lines gate ②'s question must show (M1f review V1): one per exempted line, one per reading change, and the
readings that differ elsewhere — computed by `state.py shown <v> 2` and kept in its shown record, so the guard asks
for exactly what was shown. Too many lines (commit/values.py's limits) go to `work/<l>/gate2-lines.txt` (P-STATE) and
the question shows one line with its path, sha12 and counts instead."""

import hashlib
import json
import os

from ..commit.values import overflows
from . import pronounce, tts

FILE = "gate2-lines.txt"


def exemption_line(e):
    return "면제 %s: \"%s\" → 들림 \"%s\" (CER %s)" % (e.get("id"), e.get("text"), e.get("heard"), e.get("cer"))


def full_lines(vdir, lang, conflicts):
    try:
        with open(tts.exemptions_path(vdir, lang), encoding="utf-8") as f:
            ex = (json.load(f) or {}).get("lines") or []
    except (OSError, ValueError, AttributeError):
        ex = []
    chg, _why = pronounce.read(pronounce.path_changes(vdir, lang))
    lines = [exemption_line(e) for e in ex if isinstance(e, dict)]
    lines += ["발음 %s → %s" % (k, v) for k, v in sorted((chg or {}).items())]
    return lines + list(conflicts or []), len(ex), len(chg or {})


def lines(vdir, lang, conflicts, write):
    """The lines the question must show. `write(path, text)` writes the overflow file when needed."""
    full, n_ex, n_chg = full_lines(vdir, lang, conflicts)
    p = os.path.join(vdir, "work", lang, FILE)
    if not full or not overflows(full, max(len(l) for l in full)):
        if os.path.exists(p):
            os.remove(p)
        return full
    text = "\n".join(full) + "\n"
    write(p, text)
    sha12 = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return ["② 목록 파일: %s (sha %s) · 면제 %d · 발음 %d · 다른 읽기 %d" % (
        os.path.join("work", lang, FILE), sha12, n_ex, n_chg, len(conflicts or []))]
