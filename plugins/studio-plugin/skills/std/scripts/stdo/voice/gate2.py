"""The lines gate ②'s question must show (M1f review V1): one per sentence narrator.wav plays (0.0.28 Q9, from
`checks/audition.json`, at most PLAYED_MAX), one per exempted line, one per reading change, and the readings that
differ elsewhere — computed by `state.py shown <v> 2` and kept in its shown record, so the guard asks for exactly what
was shown. Too many lines (commit/values.py's limits) go to `work/<l>/gate2-lines.txt` (P-STATE) and the question
shows one line with its path, sha12 and counts instead. The `read: <audition.md>` line comes last either way (it is
recorded too, but never moves to the file)."""

import hashlib
import json
import os

from ..commit.values import overflows
from . import pronounce, tts

FILE = "gate2-lines.txt"
PLAYED_MAX = 8
TEXT_MAX = 120


def _one_line(t, limit=TEXT_MAX):
    from ..claims.check import sanitize_reason
    t = sanitize_reason(t)
    return t if len(t) <= limit else t[:limit - 1] + "…"


def played_lines(vdir, lang):
    """`- "<text>" — <why>` per sentence the audition plays (audition.py's check file), at most PLAYED_MAX, then one
    line counting the rest."""
    from ..state import stagechecks
    data = stagechecks.read(vdir, lang, "audition")
    det = (data or {}).get("details") if isinstance(data, dict) else None
    played = det.get("played") if isinstance(det, dict) else None
    if not isinstance(played, list):
        return []
    out = []
    for p in played:
        if not isinstance(p, dict):
            continue
        why = p.get("why") if isinstance(p.get("why"), list) else []
        out.append('- "%s" — %s' % (_one_line(p.get("text")), _one_line("; ".join(str(w) for w in why))))
    if len(out) > PLAYED_MAX:
        out = out[:PLAYED_MAX] + ["- … %d more in audition.md" % (len(out) - PLAYED_MAX)]
    return out


def exemption_line(e):
    return "면제 %s: \"%s\" → 들림 \"%s\" (CER %s)" % (e.get("id"), e.get("text"), e.get("heard"), e.get("cer"))


def full_lines(vdir, lang, conflicts):
    played = played_lines(vdir, lang)
    try:
        with open(tts.exemptions_path(vdir, lang), encoding="utf-8") as f:
            ex = (json.load(f) or {}).get("lines") or []
    except (OSError, ValueError, AttributeError):
        ex = []
    chg, _why = pronounce.read(pronounce.path_changes(vdir, lang))
    lines = list(played) + [exemption_line(e) for e in ex if isinstance(e, dict)]
    lines += ["발음 %s → %s" % (k, v) for k, v in sorted((chg or {}).items())]
    return lines + list(conflicts or []), len(ex), len(chg or {}), len(played)


def lines(vdir, lang, conflicts, write, read=None):
    """The lines the question must show. `write(path, text)` writes the overflow file when needed; `read`: the
    audition.md path, as the last line."""
    full, n_ex, n_chg, n_played = full_lines(vdir, lang, conflicts)
    tail = ["read: %s" % read] if read else []
    p = os.path.join(vdir, "work", lang, FILE)
    if not full or not overflows(full, max(len(l) for l in full)):
        if os.path.exists(p):
            os.remove(p)
        return full + tail
    text = "\n".join(full) + "\n"
    write(p, text)
    sha12 = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return ["② 목록 파일: %s (sha %s) · 재생 %d · 면제 %d · 발음 %d · 다른 읽기 %d" % (
        os.path.join("work", lang, FILE), sha12, n_played, n_ex, n_chg, len(conflicts or []))] + tail
