"""`audition.py <video>` (m1-plan §8): the clips a person listens to at ② — fixed samples (the longest sentence, the
first sentence with a number or a proper noun), the first sentence with each reading change (V4), every sentence
whose lock entry changed since the last ② approval
(its `sentences` {id: lockKey}), and every exempted line — joined by ffmpeg into `out/<v>/<l>/audition/narrator.wav`
with `audition.md` beside it, then `checks/audition.json` over its inputs and those two files (v5 S4: touching the
files never passes it)."""

import os
import re
import tempfile

from ..claims.linkrule import has_number

PROPER = re.compile(r"[A-Z][A-Za-z]+|[぀-ヿ㐀-䶿一-鿿]")


def pick(sentences, previous, exempt, pron_keys=()):
    """[(sentence, [reasons])] in script order."""
    lines = [s for s in sentences or [] if isinstance(s, dict) and not s.get("recorded")
             and isinstance(s.get("lock"), dict)]
    why = {}

    def add(s, reason):
        why.setdefault(s["id"], []).append(reason)
    if lines:
        add(max(lines, key=lambda s: (len(s.get("text") or ""), -lines.index(s))), "the longest sentence")
        for s in lines:
            t = s.get("text") or ""
            if has_number(t) or PROPER.search(t) or any(k in t for k in pron_keys):
                add(s, "a number or a proper noun")
                break
    for k in pron_keys or ():  # every reading change is heard (M1f review V4)
        s = next((x for x in lines if k in (x.get("text") or "")), None)
        if s is not None:
            add(s, "pronounce %s" % k)
    prev = previous if isinstance(previous, dict) else None
    for s in lines:
        if prev is not None and prev.get(s["id"]) != s.get("lockKey"):
            add(s, "changed since the last ② approval")
    ex = {e.get("id"): e for e in exempt or [] if isinstance(e, dict)}
    for s in lines:
        if s["id"] in ex:
            add(s, "exempted: %s" % ex[s["id"]].get("why"))
    return [(s, why[s["id"]]) for s in lines if s["id"] in why]


def assemble(wavs, out, runner):
    """Join the clips with ffmpeg (concat demuxer, stream copy). `runner(argv)` → exit code (tests inject it)."""
    os.makedirs(os.path.dirname(out), exist_ok=True)
    fd, listfile = tempfile.mkstemp(prefix="audition-", suffix=".txt")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for w in wavs:
                f.write("file '%s'\n" % w.replace("'", "'\\''"))
        tmp = out + ".tmp.wav"
        code = runner(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
                       "-i", listfile, "-c", "copy", tmp])
        if code == 0 and os.path.isfile(tmp):
            os.replace(tmp, out)
            return 0
        if os.path.exists(tmp):
            os.remove(tmp)
        return code or 1
    finally:
        os.remove(listfile)


def markdown(video, lang, clips, conflicts=(), warning=None, changes=None):
    lines = ["# Audition — %s (%s)" % (video, lang), "",
             "Made by audition.py: `narrator.wav` plays these sentences in this order.", ""]
    for n, (s, why) in enumerate(clips, 1):
        lock = s.get("lock") or {}
        lines.append("%d. %s — %s" % (n, s.get("id"), "; ".join(why)))
        lines.append("   > %s" % s.get("text"))
        if lock.get("heard") is not None:
            lines.append("   - heard: %s (CER %s)" % (lock.get("heard"), lock.get("cer")))
    if changes:
        said = {k for s, why in clips for w in why if w.startswith("pronounce ") for k in [w[len("pronounce "):]]}
        lines += ["", "## Reading changes (pronounce-changes.json)", ""]
        lines += ["- 발음 %s → %s%s" % (k, v, "" if k in said else " (no sentence says it)")
                  for k, v in sorted(changes.items())]
    if conflicts:
        lines += ["", "## Readings that differ elsewhere (information)", ""] + ["- %s" % c for c in conflicts]
    if warning:
        lines += ["", "## Length", "", "- %s" % warning]
    return "\n".join(lines) + "\n"
