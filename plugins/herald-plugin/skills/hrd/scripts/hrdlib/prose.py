"""Readability hints for the writer and the editor (warnings only — never a gate error).

Counts what makes prose tiring or machine-sounding: very long sentences, sentences packed with
numbers or parenthetical asides, the same label repeated, and stock phrases. Read from
`gate-rules.json` `prose` (all keys optional; a malformed value falls back to its default); the
numbers are evidence for the editor's reader pass, not a verdict.
"""

import re

CJK_LANGS = {"ko": 90, "ja": 80, "zh": 70}
WORD_LIMIT = 35

# phrases that read as filler or as generated text, per language (substring match, so only
# phrases that are rarely ordinary prose)
STOCK = {
    "ko": ["결론적으로", "살펴보겠습니다", "알아보겠습니다", "알아보도록 하겠습니다",
           "것이 중요합니다", "도움이 되셨", "도움이 되길", "요약하자면"],
    "ja": ["いかがでしたか", "について解説します", "について見ていきましょう", "ことが重要です",
           "参考になれば", "まとめると"],
    "en": ["delve", "in today's fast-paced", "it's important to note", "it is important to note",
           "in conclusion", "a testament to", "whether you're a", "in the ever-evolving", "embark on"],
}

DEFAULTS = {"max_numbers": 5, "max_asides": 2, "repeat_label": 3}

# config.language may be a name rather than a code (init: "else the content language")
LANG_NAMES = {"korean": "ko", "한국어": "ko", "kr": "ko", "japanese": "ja", "日本語": "ja", "jp": "ja", "chinese": "zh",
              "中文": "zh", "汉语": "zh", "中國語": "zh", "english": "en"}

FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
SETEXT_RE = re.compile(r"^\s*(=+|-+)\s*$")
BREAK_RE = re.compile(r"^\s*([-*_])(?:\s*\1){2,}\s*$")
DELIM_RE = re.compile(r"^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)+\|?\s*$|^\s*\|\s*:?-+:?\s*\|\s*$")
LIST_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
CLOSERS = "\"'”’」』)）]*_"
# Latin punctuation ends a sentence before whitespace; CJK punctuation ends it outright
_C = re.escape(CLOSERS)
# where a sentence ends (closing quotes stay with it): Latin punctuation before whitespace; CJK
# punctuation outright, or after closing quotes only before whitespace — 「はい。」と言った is one
SENT_END_RE = re.compile(r"[.!?][%s]*(?=\s)|[。！？]+(?![%s！？。])|[。！？]+[%s]+(?=\s|$)" % (_C, _C, _C))
QUOTE_OPEN, QUOTE_CLOSE = "「『", "」』"
WEEKDAY_RE = re.compile(r"^[월화수목금토일]$|^[月火水木金土日]$")
ABBREV_RE = re.compile(r"\b(?:e\.g|i\.e|vs|cf|Mr|Mrs|Ms|Dr|St|No|Fig)\.$")
ASIDE_RE = re.compile(r"[(（]([^()（）]{1,80})[)）]")
NUM_RE = re.compile(r"\d+(?:[.,:/-]\d+)*")
# a date or time written in words counts as one number: 7월 5일, 2026年7月5日, 3시 30분
DATE_RE = re.compile(r"(?:\d+\s*(?:년|年)\s*)?\d+\s*(?:월|月)\s*\d+\s*(?:일|日)|\d+\s*(?:시|時)\s*\d+\s*(?:분|分)")
JA_CHAR_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
KANJI_RE = re.compile(r"[\u3400-\u9fff]")
KANA_ONLY_RE = re.compile(r"^[\u3040-\u30ffー・\s]+$")
BLOCK_OPEN_RE = re.compile(r"<(script|style)\b", re.I)


def _int(v, default, low):
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= low else default


def _rules(rules):
    r = rules if isinstance(rules, dict) else {}
    phrases = r.get("stock_phrases")
    return {
        "check": r.get("check", True) is not False,
        "max_sentence": _int(r.get("max_sentence"), None, 1),
        "max_numbers": _int(r.get("max_numbers"), DEFAULTS["max_numbers"], 1),
        "max_asides": _int(r.get("max_asides"), DEFAULTS["max_asides"], 1),
        "repeat_label": _int(r.get("repeat_label"), DEFAULTS["repeat_label"], 2),
        "stock_phrases": [p for p in phrases if isinstance(p, str) and p.strip()] if isinstance(phrases, list) else [],
    }


def _clean(line):
    text = re.sub(r"(`+)[^`]*?\1", "", line)  # inline code is not prose
    text = re.sub(r"!\[[^\]]*\]\((?:[^()\s]|\([^()]*\))*(?:\s+[^)]*)?\)", "", text)
    text = re.sub(r"\[([^\]]*)\]\((?:[^()\s]|\([^()]*\))*(?:\s+[^)]*)?\)", r"\1", text)
    return re.sub(r"<[^>]+>", "", text).strip()


def _paragraphs(body, offset=0):
    """Prose paragraphs as lists of (file line, text): no code, tables, headings, blockquotes
    (quotes are verbatim — never a reason to reword), comments, script/style blocks or
    HTML-only lines; each list item, and each indented paragraph inside one, stands alone."""
    out, cur = [], []
    fence, comment, block, in_list, table = None, False, None, False, False
    cur_list = False  # the paragraph in progress is a list item

    def flush():
        if cur:
            out.append(list(cur))
            cur.clear()

    for i, raw in enumerate(body.replace("\r\n", "\n").split("\n"), 1):
        line = raw.strip()
        if comment:
            if "-->" not in line:
                continue
            comment = False
            line = line.split("-->", 1)[1].strip()
        if block:
            if re.search(r"</%s\s*>" % block, line, re.I):
                block = None
            continue
        fm = FENCE_RE.match(raw)
        if fence:
            if fm and fm.group(1)[0] == fence[0] and len(fm.group(1)) >= len(fence) and not raw.strip()[len(fm.group(1)):].strip():
                fence = None
            continue
        if fm:
            fence = fm.group(1)
            flush()
            continue
        line = re.sub(r"<!--.*?-->", "", line)
        if "<!--" in line:
            line, comment = line.split("<!--", 1)[0].strip(), True
        m = BLOCK_OPEN_RE.search(line)
        if m:
            flush()
            if not re.search(r"</%s\s*>" % m.group(1), line, re.I):
                block = m.group(1)
            continue
        if not line:
            table = False
            flush()
            continue
        if table and "|" in line:
            continue
        table = False
        if DELIM_RE.match(line) and "|" in line:  # table delimiter row: the line above was its header
            if cur:
                cur.pop()
            flush()
            table = True
            continue
        if SETEXT_RE.match(raw) and cur and not cur_list:  # the paragraph above was a heading
            cur.clear()
            continue
        if BREAK_RE.match(line):  # thematic break
            flush()
            continue
        indented = raw.startswith("    ") or raw.startswith("\t")
        if not indented and not LIST_RE.match(line):
            in_list = in_list and bool(cur)
        is_code = indented and not cur and not in_list
        mdx = (not cur and re.match(r"^(import|export)\s.*(\bfrom\s+['\"]|[=;{]|['\"]\s*;?$)", line)) \
            or line.startswith(":::")
        if line.startswith(("|", "#", ">")) or line.count("|") >= 2 or is_code or mdx:
            flush()
            continue
        text = _clean(line)
        if not text:
            flush()
            continue
        if LIST_RE.match(line):
            flush()
            in_list = cur_list = True
            text = LIST_RE.sub("", text)
        elif not cur:
            cur_list = False
        cur.append((i + offset, text))
    flush()
    return out


def _sentences(body, offset=0):
    """(file line where the sentence starts, sentence)."""
    for para in _paragraphs(body, offset):
        text, starts = "", []
        for line, piece in para:
            if text:
                text += " "
            starts.append((len(text), line))
            text += piece

        def line_at(at):
            return max(ln for off, ln in starts if off <= at)

        start, out = 0, []
        for m in SENT_END_RE.finditer(text):
            piece = text[start:m.end()]
            if ABBREV_RE.search(piece):
                continue  # "e.g." ends no sentence
            if sum(piece.count(c) for c in QUOTE_OPEN) > sum(piece.count(c) for c in QUOTE_CLOSE):
                continue  # inside 「…」 dialogue
            out.append((start, m.end()))
            start = m.end()
        out.append((start, len(text)))
        for a, b in out:
            piece = text[a:b]
            if piece.strip():
                yield line_at(a + len(piece) - len(piece.lstrip())), piece.strip()


def _asides(sentence, lang):
    """Parenthetical asides, not counting glosses — they are content, not hedges:
    Japanese readings 空港(くうこう) in any language; in other languages also a translation
    right after Japanese/Chinese text or a 「」 quote (搭乗券(탑승권), 「はい」(네)) and Hanja
    after a word (한국어(韓國語))."""
    found = []
    for m in ASIDE_RE.finditer(sentence):
        inner = m.group(1).strip()
        before = sentence[:m.start()].rstrip()
        last = before[-1] if before else ""
        if last and KANA_ONLY_RE.match(inner) and KANJI_RE.match(last):
            continue
        if WEEKDAY_RE.match(inner):  # a date's weekday, 12월 6일(일)
            continue
        if lang not in ("ja", "zh") and last and (JA_CHAR_RE.match(last) or last in "」』" or JA_CHAR_RE.search(inner)):
            continue  # a gloss: Japanese/Chinese around it (搭乗券(탑승권), 음독(音読み), 한국어(韓國語))
        found.append(inner)
    return found


def _excerpt(s, n=40):
    return s if len(s) <= n else s[:n] + "…"


def prose_report(body, language="en", rules=None, offset=0):
    """`offset`: lines before `body` in the file (the frontmatter), so line numbers match the file."""
    r = _rules(rules)
    if not r["check"]:
        return {"warnings": [], "stats": {}}
    name = str(language or "en").strip().lower()
    lang = LANG_NAMES.get(name) or re.split(r"[-_\s]", name)[0]
    cjk = lang in CJK_LANGS
    limit = r["max_sentence"] or (CJK_LANGS[lang] if cjk else WORD_LIMIT)
    warnings, long_, packed, crowded, labels = [], [], [], [], {}
    sentences = list(_sentences(body or "", offset))
    for line, s in sentences:
        # CJK: characters, with each Latin word or number counted as one (GitHub, 2026)
        size = len(re.sub(r"\s", "", re.sub(r"[A-Za-z0-9][A-Za-z0-9._-]*", "x", s))) if cjk else len(s.split())
        if size > limit:
            long_.append("line %d (%d) «%s»" % (line, size, _excerpt(s)))
        asides = _asides(s, lang)
        for a in asides:
            labels[a] = labels.get(a, 0) + 1
        if len(asides) >= r["max_asides"]:
            crowded.append("line %d (%d) «%s»" % (line, len(asides), _excerpt(s)))
        nums = len(NUM_RE.findall(DATE_RE.sub("0", s)))
        if nums >= r["max_numbers"]:
            packed.append("line %d (%d) «%s»" % (line, nums, _excerpt(s)))
    unit = "chars" if cjk else "words"
    if long_:
        warnings.append("prose: %d sentence(s) over %d %s — %s" % (len(long_), limit, unit, "; ".join(long_[:5])))
    if crowded:
        warnings.append("prose: %d sentence(s) with %d+ parenthetical asides — %s"
                        % (len(crowded), r["max_asides"], "; ".join(crowded[:5])))
    if packed:
        warnings.append("prose: %d sentence(s) with %d+ numbers — %s"
                        % (len(packed), r["max_numbers"], "; ".join(packed[:5])))
    for label, c in sorted(labels.items(), key=lambda kv: -kv[1]):
        if c >= r["repeat_label"]:
            warnings.append("prose: the aside (%s) appears %d times — state it once for its section or table" % (label, c))
    low = " ".join(s for _, s in sentences).lower()
    for phrase in STOCK.get(lang, []) + r["stock_phrases"]:
        c = low.count(phrase.lower())
        if c:
            warnings.append("prose: stock phrase %r ×%d" % (phrase, c))
    return {"warnings": warnings,
            "stats": {"sentences": len(sentences), "long": len(long_), "limit": limit, "unit": unit,
                      "crowded": len(crowded), "packed": len(packed)}}


def safe_report(body, language, rules, offset=0):
    """prose_report that can never break the gate: an unexpected error becomes one hint."""
    try:
        return prose_report(body, language, rules, offset)
    except Exception as e:  # noqa: BLE001 — hints must never fail the gate
        return {"warnings": ["prose: hints unavailable (%s: %s)" % (type(e).__name__, e)], "stats": {}}
