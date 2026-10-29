"""Number values in a sentence (M1f review V3): the script and what ASR heard may write the same number differently
(`이십 분` · `20분`), so both are turned into values and compared as multisets.

Read: digit runs (any script, NFKC), Sino-Korean numbers (a run with 십 · 백 · 천 · 만 · 억, or a single digit before a
spaced time or measure unit — `삼 년`; a bare `이번` · `구분` is no number), native Korean counts before a counter
(`한 번` · `스물두 명`) and standalone 하나 · 둘 · 셋 · 넷, Japanese kanji numerals and kana counts (ひとつ … ここのつ,
とお), and English number words. The forms follow claims.linkrule.has_number."""

import re
import unicodedata

from ..claims.linkrule import COUNTERS

SINO_D = {"일": 1, "이": 2, "삼": 3, "사": 4, "오": 5, "육": 6, "칠": 7, "팔": 8, "구": 9,
          "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
SINO_U = {"십": 10, "백": 100, "천": 1000, "十": 10, "百": 100, "千": 1000}
SINO_B = {"만": 10 ** 4, "억": 10 ** 8, "万": 10 ** 4, "億": 10 ** 8}
NATIVE_T = {"열": 10, "스물": 20, "스무": 20, "서른": 30, "마흔": 40, "쉰": 50, "예순": 60, "일흔": 70, "여든": 80,
            "아흔": 90}
NATIVE_U = {"한": 1, "두": 2, "세": 3, "네": 4, "다섯": 5, "여섯": 6, "일곱": 7, "여덟": 8, "아홉": 9}
STANDALONE = {"하나": 1, "둘": 2, "셋": 3, "넷": 4}
KANA = {"ひとつ": 1, "ふたつ": 2, "みっつ": 3, "よっつ": 4, "いつつ": 5, "むっつ": 6, "ななつ": 7, "やっつ": 8,
        "ここのつ": 9, "とお": 10}
ENGLISH = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
           "eleven": 11, "twelve": 12, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "hundred": 100,
           "thousand": 1000, "dozen": 12}
DIGITS = re.compile(r"\d+")
SINO_RUN = re.compile(r"(?<![가-힣])([일이삼사오육칠팔구십백천만억]*[십백천만억][일이삼사오육칠팔구십백천만억]*)"
                      r"(?=\s?" + COUNTERS + r"|[^가-힣]|$)")
SINO_ONE = re.compile(r"(?<![가-힣])([일이삼사오육칠팔구])\s(?=(?:년|개월|시간|분|초|퍼센트|층|배|시|명|개|살|번째)(?![가-힣]))")
NATIVE = re.compile(r"(?<![가-힣])(" + "|".join(sorted(NATIVE_T, key=len, reverse=True)) + r")?("
                    + "|".join(sorted(NATIVE_U, key=len, reverse=True)) + r")?\s?(?=" + COUNTERS + ")")
ALONE = re.compile(r"(?<![가-힣])(하나|둘|셋|넷)(?![가-힣])")
KANJI = re.compile(r"[一二三四五六七八九十百千万億]+")
KANA_RE = re.compile("|".join(KANA))
WORDS = re.compile(r"(?<![A-Za-z])(" + "|".join(ENGLISH) + r")(?![A-Za-z])", re.I)


def sino(run):
    """The value of a Sino-Korean or kanji numeral run (이천이십육 → 2026, 二十 → 20)."""
    total, section, digit = 0, 0, 0
    for ch in run:
        if ch in SINO_D:
            digit = SINO_D[ch]
        elif ch in SINO_U:
            section += (digit or 1) * SINO_U[ch]
            digit = 0
        elif ch in SINO_B:
            total += (section + digit or 1) * SINO_B[ch]
            section, digit = 0, 0
    return total + section + digit


def values(text):
    """The sorted list of the number values a text says."""
    t = unicodedata.normalize("NFKC", text or "")
    out = [int(d) for d in DIGITS.findall(t)]
    t2 = DIGITS.sub(" ", t)
    out += [sino(m.group(1)) for m in SINO_RUN.finditer(t2)]
    out += [SINO_D[m.group(1)] for m in SINO_ONE.finditer(t2)]
    for m in NATIVE.finditer(t2):
        if m.group(1) or m.group(2):
            out.append(NATIVE_T.get(m.group(1) or "", 0) + NATIVE_U.get(m.group(2) or "", 0))
    out += [STANDALONE[m.group(1)] for m in ALONE.finditer(t2)]
    out += [sino(k) for k in KANJI.findall(t2)]
    out += [KANA[k] for k in KANA_RE.findall(t2)]
    out += [ENGLISH[w.lower()] for w in WORDS.findall(t2)]
    return sorted(out)
