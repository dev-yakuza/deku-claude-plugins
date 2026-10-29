"""The lines gate ④b's question must show (M1h review Y2, the V1 pattern of gate ②): every fact of the copy with the
excerpts it rests on — computed by `state.py shown <v> 4b --platform <p>` and kept in its shown record, so the guard
asks for exactly what was shown. Too many go to `work/<l>/gate4b-lines.<p>.txt` (P-STATE) with one line in their
place: its path, sha12 and count."""

import hashlib
import os

from ..commit.values import overflows
from . import factcheck


def lines(vdir, lang, platform, write):
    full = factcheck.fact_lines(vdir, lang, platform)
    name = "gate4b-lines.%s.txt" % platform
    p = os.path.join(vdir, "work", lang, name)
    if not full or not overflows(full, max(len(l) for l in full)):
        if os.path.exists(p):
            os.remove(p)
        return full
    text = "\n".join(full) + "\n"
    write(p, text)
    return ["④b 근거 목록 파일: %s (sha %s) · 사실 %d" % (os.path.join("work", lang, name),
                                                   hashlib.sha256(text.encode("utf-8")).hexdigest()[:12], len(full))]
