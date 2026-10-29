"""`check_tts.py <video>` (m1-plan §8): every sentence s2v synthesized is checked by its lock entry —
`s2v sentences --json`, recorded (a person's own recording) lines skipped:
- a lock entry with `asr: true` (else the closed side: no ASR, no pass — the real mock always ends here);
- CER at most the format's `cer_max.<lang>` (formats/<kind>.md, P-CRIT; config.json is never read);
- the heard text says the script's numbers (as values: `이십 분` = `20분`, voice/numbers.py) and negations.
A failing line asks for `tts --retry`. Studio counts the retries itself (M1f review V2: s2v's `attempt` is the take
it kept — one tts run already tries up to six): the language state keeps, per sentence id, the lock key and s2v's
`tried` (the audio manifest's highest take made for it; the kept `attempt` when an older manifest has none) when a
retry was asked; a later check that finds `tried` grown for the same key counts one retry done — even when s2v kept
the old take (M1f re-review W1). After two retries a still failing line is written to `work/<l>/exemptions.json` (P-STATE: this script writes it, ② shows it)
and no longer fails the stage. The audio hash must be computable; a total length more than 30 % outside the format's
range is a warning for ②."""

import json
import os
import re
from collections import Counter

from . import numbers

MAX_RETRIES = 2
LENGTH_SLACK = 0.30
NEGATIONS = {
    "ko": re.compile(r"(?:^|\s)안\s|않|못\s|못했|못합|없|아니"),
    "ja": re.compile(r"ない|ません|ず(?![っ])|なかった"),
    "en": re.compile(r"\b(?:not|no|never|none|nothing|nobody)\b|n't", re.I),
}


def mismatch(text, heard, lang):
    """Why the heard text does not say the script's numbers or negations, or None."""
    a, b = numbers.values(text), numbers.values(heard)
    if Counter(a) != Counter(b):
        if a and b:
            return "numbers %s heard as %s" % (" ".join(map(str, a)), " ".join(map(str, b)))
        return "a number is %s" % ("missing in what was heard" if a else "heard that the script does not say")
    neg = NEGATIONS.get((lang or "").split("-")[0])
    if neg and bool(neg.search(text or "")) != bool(neg.search(heard or "")):
        return "a negation is %s" % ("missing in what was heard" if neg.search(text or "") else "heard but not written")
    return None


def made(manifest, key, lock):
    """How many takes s2v has made for a lock key: the manifest's `tried`, else the kept attempt."""
    e = ((manifest or {}).get("entries") or {}).get(key) if isinstance(manifest, dict) else None
    v = e.get("tried") if isinstance(e, dict) else None
    if not isinstance(v, int) or isinstance(v, bool):
        v = (lock or {}).get("attempt")
    return int(v) if isinstance(v, int) and not isinstance(v, bool) else 0


def judge(sentences, cer_max, lang, retries=None, manifest=None):
    """(problems, retry ids, exemptions, the new retry records). `retries`: {id: {"key", "tried", "done"}} from the
    language state; `manifest`: the audio lock's manifest.json."""
    problems, retry, exempt, new = [], [], [], {}
    old = retries if isinstance(retries, dict) else {}
    for s in sentences or []:
        if not isinstance(s, dict) or s.get("recorded"):
            continue
        sid, lock = s.get("id"), s.get("lock")
        if not isinstance(lock, dict):
            problems.append("%s is not synthesized" % sid)
            continue
        if lock.get("asr") is not True:
            problems.append("%s has no ASR check (asr: false — synthesize with ASR; a mock TTS never passes)" % sid)
            continue
        why = []
        cer = lock.get("cer")
        if not isinstance(cer, (int, float)) or isinstance(cer, bool):
            why.append("no CER")
        elif cer > cer_max:
            why.append("CER %.3f over %.3f" % (cer, cer_max))
        m = mismatch(s.get("text"), lock.get("heard"), lang)
        if m:
            why.append(m)
        if not why:
            continue
        rec = old.get(sid) if isinstance(old.get(sid), dict) else None
        key, tried = s.get("lockKey"), made(manifest, s.get("lockKey"), lock)
        if rec is None or rec.get("key") != key:
            rec = {"key": key, "tried": tried, "done": 0}  # first failure of this text and voice
        elif tried > int(rec.get("tried") or 0):
            rec = {"key": key, "tried": tried, "done": int(rec.get("done") or 0) + 1}  # a retry ran: more takes
        new[sid] = rec
        if rec["done"] >= MAX_RETRIES:
            exempt.append({"id": sid, "text": s.get("text"), "heard": lock.get("heard"), "cer": cer,
                           "retries": rec["done"], "why": "; ".join(why)})
        else:
            retry.append(sid)
            problems.append("%s: %s — retry it (%d of %d retries done)" % (sid, "; ".join(why), rec["done"],
                                                                          MAX_RETRIES))
    return problems, retry, exempt, new


def seconds(manifest, sentences):
    entries = (manifest or {}).get("entries") or {}
    total = 0.0
    for s in sentences or []:
        if isinstance(s, dict) and not s.get("recorded"):
            e = entries.get(s.get("lockKey"))
            if isinstance(e, dict) and isinstance(e.get("duration"), (int, float)):
                total += float(e["duration"])
    return total


def length_warning(total, ls):
    lo, hi = ls["min"] * (1 - LENGTH_SLACK), ls["max"] * (1 + LENGTH_SLACK)
    if not lo <= total <= hi:
        return "the narration is %.0f s, more than 30 %% outside the format's %s–%s s — say so at ②" % (
            total, ls["min"], ls["max"])
    return None


def exemptions_path(vdir, lang):
    return os.path.join(vdir, "work", lang, "exemptions.json")


def exemptions_text(lines):
    return json.dumps({"schema": 1, "lines": lines}, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
