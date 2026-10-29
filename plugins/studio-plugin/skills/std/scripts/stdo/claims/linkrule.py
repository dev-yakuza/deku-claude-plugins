"""When a sentence may be a `link` (M1e review S1 · T1 · T2): the deterministic floor under the fact-checker's labels.

A sentence must be `fact` when
- the claims map lists it among a claim's `sentences`;
- it holds a number: a digit (any script), a Japanese numeral (一 … 億, ひとつ … ここのつ), an English number word
  (incl. dozen, first, second, third), a Korean native count before a counter — compounds and the tens too (`두 번`,
  `열두 개`, `서른 살`) —, a Sino-Korean number with a unit (`삼십 명`, `오백`), a single Sino-Korean digit before a time
  or measure unit (`삼 년`), 수/몇 + 십/백/천/만 (`수백 명`), an ordinal (`첫`, `첫째`, `○번째`), `절반` or `반` as a
  quantity (`반 년`), or a standalone 하나 · 둘 · 셋 · 넷;
- it holds a term of the claims map's excerpts. Terms are noun-like and narrow on purpose: a run of kanji or kana
  (`搭乗券`), a Latin word of 4 or more letters, or a Hangul word of 3 or more syllables once its particles are dropped
  (repeatedly: `공항에서는` → `공항`), that is not a verb or adjective form (ENDINGS: `합니다`, `간단하게`, `받아야`) and
  not a conjunction, adverb or other function word (STOPWORDS: `그래서`, `하지만`, `이라고`).
And there are at most LINK_MAX link sentences or LINK_SHARE of all judged items, whichever is larger, each with a
`note` saying why it states nothing to check."""

import re

from ..text.normalize import normalize

LINK_MAX, LINK_SHARE = 2, 0.25
COUNTERS = r"(?:번째|번|가지|개|명|살|시간|시|분|초|년|개월|월|일|주|층|배|퍼센트|%|원|권|장|곳|대|마리|잔|병|쪽|줄)"
NATIVE = r"(?:(?:열|스물|스무|서른|마흔|쉰|예순|일흔|여든|아흔)(?:한|두|세|네|다섯|여섯|일곱|여덟|아홉)?" \
         r"|한|두|세|네|다섯|여섯|일곱|여덟|아홉)"
NUMBER = re.compile(
    r"\d|[一二三四五六七八九十百千万億]"
    r"|(?:ひと|ふた|みっ|よっ|いつ|むっ|なな|やっ|ここの)つ|とお"
    r"|(?<![A-Za-z])(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|twenty|thirty|forty|fifty|"
    r"hundred|thousand|million|billion|half|twice|percent|dozens?|first|second|third)(?![A-Za-z])"
    r"|(?<![가-힣])" + NATIVE + r"\s?" + COUNTERS +
    r"|(?<![가-힣])[일이삼사오육칠팔구]?[십백천만억][일이삼사오육칠팔구]?\s?" + COUNTERS + "?"
    r"|(?<![가-힣])[일이삼사오육칠팔구]\s(?:년|개월|시간|분|초|퍼센트|층|배)(?![가-힣])"
    r"|(?<![가-힣])(?:수|몇)\s?(?:십|백|천|만)"
    r"|(?<![가-힣])첫(?:\s|번)|번째|(?<![가-힣])(?:첫|둘|셋|넷|다섯|여섯|일곱|여덟|아홉|열)째"
    r"|절반|(?<![가-힣])반\s?(?:년|개월|시간|쯤|정도|이상|이하)"
    r"|(?<![가-힣])(?:하나|둘|셋|넷)(?![가-힣])", re.I)
PARTICLES = ("에서는", "에게서", "으로는", "에서", "으로", "에게", "부터", "까지", "처럼", "보다", "에는", "와는", "과는",
             "이나", "이라", "은", "는", "이", "가", "을", "를", "에", "의", "도", "로", "와", "과", "만", "랑", "나")
# verb and adjective forms (a Hangul word ending so is never a term)
ENDINGS = ("니다", "세요", "어요", "아요", "해요", "에요", "예요", "이다", "였다", "었다", "았다", "겠다", "한다", "된다",
           "는다", "라고", "다고", "냐고", "자고", "지만", "는데", "은데", "니까", "도록", "려고", "면서", "아서", "어서",
           "해서", "아야", "어야", "해야", "하게", "되게", "으면", "하면", "하고", "하며", "하여", "했던", "하는", "되는",
           "있는", "없는", "고", "게", "며", "면", "죠", "요", "다", "서")
LONG_ENDINGS = tuple(e for e in ENDINGS if len(e) > 1)
STOPWORDS = frozenset([
    "그래서", "하지만", "그리고", "그러나", "그런데", "그러면", "그러니까", "따라서", "때문에", "이라고", "라고", "이제",
    "정말", "진짜", "아주", "매우", "너무", "먼저", "다음", "다음으로", "다음은", "이번", "이번에는", "그럼", "또한",
    "바로", "다시", "함께", "같이", "이렇게", "그렇게", "저렇게", "어떻게", "여러분", "우리", "지금", "오늘", "항상",
    "모두", "모든", "어떤", "이런", "그런", "저런", "무엇", "무엇을", "이것", "그것", "저것", "여기", "거기", "저기",
    "하나씩", "조금", "많이", "가장", "아마", "물론", "특히", "보통", "그냥", "혹시", "만약", "역시", "결국", "마지막",
    "마지막으로", "처음", "처음에는", "한번", "살펴", "알아보", "알아봅", "이어서"])
CJK_RUN = re.compile("[぀-ヿ㐀-䶿一-鿿]+")
LATIN = re.compile(r"[A-Za-z]{4,}")
HANGUL = re.compile("[가-힣]+")


def has_number(text):
    return bool(NUMBER.search(text or ""))


def _noun(word):
    """The noun-like stem of a Hangul word, or None (particles dropped repeatedly; verbs, adjectives, function words
    and stems under 3 syllables are none)."""
    stripped = False
    for _ in range(3):
        for p in PARTICLES:
            if word.endswith(p) and len(word) > len(p):
                word, stripped = word[:-len(p)], True
                break
        else:
            break
    # a word that carried a particle is a noun whatever its last syllable (세관신고서도 → 세관신고서); the one-syllable
    # endings only judge a bare word (M1e final re-review U1)
    endings = LONG_ENDINGS if stripped else ENDINGS
    if len(word) < 3 or word in STOPWORDS or word.endswith(endings):
        return None
    return word


def terms(excerpts):
    """The terms of the claims map's excerpts (base form)."""
    out = set()
    for e in excerpts or []:
        t = normalize(e)
        out.update(CJK_RUN.findall(t))
        out.update(w.lower() for w in LATIN.findall(t))
        for w in HANGUL.findall(t):
            n = _noun(w)
            if n:
                out.add(n)
    return out


def term_in(text, ts):
    t = normalize(text)
    low = t.lower()
    for x in ts:
        if x in (low if x.isascii() else t):
            return x
    return None
