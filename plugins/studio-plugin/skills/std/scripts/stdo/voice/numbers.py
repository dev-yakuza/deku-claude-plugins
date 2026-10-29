"""Number values in a sentence (M1f review V3): the script and what ASR heard may write the same number differently
(`이십 분` · `20분`), so both are turned into values and compared as multisets.

Read: digit runs (any script, NFKC) — with the 십 · 백 · 천 · 만 · 억 that follow them composed into one value (`3만 5천`
= 35000, `1만 원` = 10000; M1f re-review W2), thousands separators and decimals as one value (`1,000` · `3.5` ·
`삼 점 오`; M1g review X3) —, ranges said as one word as both values (`한두` = 1 and 2, as `1~2`), Sino-Korean numbers
(also a single digit right before 월: `삼월에` = 3; `오일` · `오시` alone are words), English ordinals (1st, first …), (a run with 십 · 백 · 천 · 만 · 억, or a single digit before a
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
           "thousand": 1000, "dozen": 12, "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
           "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10}
DIGITS = re.compile(r"\d+")
DIGIT_UNITS = re.compile(r"(?:\d+\s?[십백천만억]\s?)+\d*")
UNIT_PART = re.compile(r"(\d+)\s?([십백천만억])")
# a single Sino digit (or 십 · 십일 · 십이) right before 월 — a month (M1g review X3: `오일` · `오시` are words too,
# so 일 and 시 are read only after digits or as spaced counters)
SINO_DATE = re.compile(r"(?<![가-힣])([일이삼사오육칠팔구]|십[일이]?)(?=월(?:[에은는이가을를의도과와]|\s|$|[^가-힣]))")
THOUSANDS = re.compile(r"\d{1,3}(?:,\d{3})+(?![\d,])")
DECIMAL = re.compile(r"\d+\.\d+")
SINO_POINT = re.compile(r"(?<![가-힣])([일이삼사오육칠팔구십백천만]+|영|공)\s?점\s?([영공일이삼사오육칠팔구]+)(?![가-힣])")
POINT_D = {"영": "0", "공": "0", "일": "1", "이": "2", "삼": "3", "사": "4", "오": "5", "육": "6", "칠": "7", "팔": "8",
           "구": "9"}
# ranges said as one word: both values on both sides (`한두 개` = `1~2개`)
RANGES = {"한두": (1, 2), "두세": (2, 3), "두서너": (2, 3, 4), "서너": (3, 4), "너덧": (4, 5), "네댓": (4, 5),
          "대여섯": (5, 6), "예닐곱": (6, 7), "일여덟": (7, 8), "엳아홉": (8, 9)}
RANGE_RE = re.compile(r"(?<![가-힣])(" + "|".join(sorted(RANGES, key=len, reverse=True)) + r")(?=\s?" + COUNTERS + ")")
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


def digit_units(run):
    """`3만 5천` → 35000: digit runs with the Sino units after them."""
    total, section = 0, 0
    for n, u in UNIT_PART.findall(run):
        if u in SINO_U:
            section += int(n) * SINO_U[u]
        else:
            total += (section + int(n)) * SINO_B[u]
            section = 0
    tail = re.search(r"(\d+)\s*$", run)
    return total + section + (int(tail.group(1)) if tail and not run.rstrip().endswith(tuple(SINO_U) + tuple(SINO_B))
                              else 0)


def values(text):
    """The sorted list of the number values a text says."""
    t = unicodedata.normalize("NFKC", text or "")
    t = THOUSANDS.sub(lambda m: m.group(0).replace(",", ""), t)  # 1,000 = 1000
    out = [float(m.group(0)) for m in DECIMAL.finditer(t)]  # 3.5 is one value
    t = DECIMAL.sub(" ", t)
    out += [digit_units(m.group(0)) for m in DIGIT_UNITS.finditer(t)]
    t = DIGIT_UNITS.sub(" ", t)
    out += [int(d) for d in DIGITS.findall(t)]
    t2 = DIGITS.sub(" ", t)
    for m in SINO_POINT.finditer(t2):  # 삼 점 오 = 3.5
        whole = 0 if m.group(1) in ("영", "공") else sino(m.group(1))
        out.append(float("%d.%s" % (whole, "".join(POINT_D[c] for c in m.group(2)))))
    t2 = SINO_POINT.sub(" ", t2)
    for m in RANGE_RE.finditer(t2):
        out += list(RANGES[m.group(1)])
    t2 = RANGE_RE.sub(" ", t2)
    out += [sino(m.group(1)) for m in SINO_DATE.finditer(t2)]
    t2 = SINO_DATE.sub(" ", t2)
    t2 = re.sub(r"(?<=[가-힣])([만억])\s+(?=[일이삼사오육칠팔구십백천])", r"\1", t2)  # 삼만 오천 = 35000
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
