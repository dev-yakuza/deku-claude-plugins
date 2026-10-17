"""SNS drafts (design/herald/03-social.md — phase 1, 0.11.0).

The distributor writes post drafts; this module decides everything a prompt could get wrong:

- channel guides `docs/editorial/channels/<sns>.md` and the persona `docs/editorial/persona.md`
  carry machine-readable head blocks; `lint` checks their format and, against HEAD, that a change
  never loosens the floor (S10, S14) without a named human approval;
- `prepare` decides whether an article may be promoted at all (S7, S8) and fixes the run id, the
  draft paths and the basis (`drafted` records) every later check uses;
- `check` runs the post rules (S6, S7, S9, S10) on a draft, reading every source from HEAD;
- `close` re-checks the chosen draft and records the decision.

Drafts, records and copies stay local under `.claude/herald/memory/social/` (gitignored).
"""

import datetime
import hashlib
import json
import os
import re
import shutil
import unicodedata

from .config import LANG_RE
from .store import find_article, ledger_latest, load_published, paths, read_json_at, work_rel
from .util import HeraldError, append_jsonl, git, git_ok, now_iso, read_jsonl, run

CHANNELS_DIR = "docs/editorial/channels"
PERSONA = "docs/editorial/persona.md"
NOTES = "docs/editorial/persona-notes.md"
PROMOTION = "docs/editorial/promotion.md"
GATE_RULES = "docs/editorial/gate-rules.json"
DISTRIBUTOR = ".claude/agents/distributor.md"

STALE_DAYS = 180
MAX_N = 5
SNS_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
RESERVED = ("pending", "approved", "final", "drafts")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

CHANNEL_RE = re.compile(r"<!--\s*herald:channel\s*(\{.*?\})\s*-->", re.S)
PERSONA_RE = re.compile(r"<!--\s*herald:social-persona\s*(\{.*?\})\s*-->", re.S)
RESEARCHED_START = "<!-- herald:researched:start -->"
RESEARCHED_END = "<!-- herald:researched:end -->"

RESEARCH_FIELDS = ("max_chars", "count", "url_len", "hashtags", "link", "researched_at")
HOUSE_KEYS = ("max_chars", "hashtags", "link")
LINK_VALUES = ("end", "start", "any", "none")
WHERE_STRENGTH = {"post": 3, "setting": 2, "profile": 1}
MODES = ("setup", "add", "edit", "persona")
FLOOR_MODES_STRENGTHEN = ("setup", "persona", "edit")

# S9 starter patterns per language (primary subtag). A language without an entry has no code
# check for (a) and the statistic vocabulary — lint refuses such a guide unless a human accepts
# `s9:<lang>` (03-social.md S9).
PATTERNS = {
    "ko": {"experience": r"써 ?보니|써 ?봤|사용해 ?보니|덕분에|(?<![가-힣])덕에", "stats": r"통계|조사에 따르면"},
    "ja": {"experience": r"使ってみ|使ったら|おかげで", "stats": r"統計|調査によると"},
    "en": {"experience": r"\bi (?:tried|used|have been using)\b|thanks to", "stats": r"according to|survey"},
}
# numbers followed by a unit of comparison (after NFKC: full-width digits and ％ are ASCII)
UNIT_RE = re.compile(r"\d+(?:[.,]\d+)?\s?(?:%|퍼센트|percent|倍)", re.I)
BAE_RE = re.compile(r"\d+(?:[.,]\d+)?\s?배(?=(?:가|로|나|는|를|의|이|만|씩|에|까지|보다|와|과)|[\s.,!?。、]|$)")
DIGIT_RE = re.compile(r"\d")

# Rule ids `check` emits. Overridable ones may pass with `close --override` after a human said so.
OVERRIDABLE = ("length", "hashtags", "link-position", "s9b-statistic")  # + s9a on promo only
RULE_IDS = ("length", "hashtags", "link-position", "s9a-service-experience", "s9b-statistic",
            "disclosure", "forbidden-confirmed", "forbidden-invalid", "sources", "promotion-quote-not-found",
            "promotion-lang", "promo-url", "promo-link-missing", "daily-url", "daily-sources",
            "service-mention-not-allowed", "header-mismatch", "guide-invalid", "basis-changed")

_URLCH = r"A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%"
_TLDS = ("com|net|org|edu|gov|io|dev|app|ai|co|jp|kr|cn|tw|hk|sg|us|uk|de|fr|es|it|nl|ru|br|in|au|ca|eu|me|"
         "ch|at|se|pl|be|nz|fi|dk|no|pt|cz|gr|hu|ro|ie|il|tr|ua|za|mx|ar|cl|pe|kz|lt|lv|ee|sk|si|hr|rs|bg|"
         "art|top|club|xyz|fun|live|space|cloud|digital|social|media|studio|design|email|asia|tokyo|"
         "info|biz|xyz|site|blog|tech|page|link|ly|gl|to|tv|so|sh|gg|cc|news|online|shop|store|website|world|"
         "life|today|jobs|vn|th|id|ph|my")
# a scheme URL's host may be non-ASCII (IDN); its path is RFC 3986 characters, so CJK text right
# after it is not swallowed
# The host of a scheme URL may have non-ASCII labels (IDN) but ends in an ASCII top-level label,
# so text right after it (`https://safie.jpで`) is not swallowed; the path is RFC 3986 characters.
# A bare domain may follow CJK text directly (X autolinks `詳しくはevil.comで`): its lookbehind is
# ASCII only.
_HOSTLABEL = r"[^\s/.:<>\"'「」『』（）【】、。！？]+"
URL_RE = re.compile(r"https?://(?:%s\.)+(?:xn--[A-Za-z0-9-]+|[A-Za-z]{2,63})(?::\d+)?(?:/[%s]*)?"
                    r"|(?<![A-Za-z0-9@.\-/_])(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+(?:%s)"
                    r"(?![A-Za-z0-9-])(?:/[%s]*)?" % (_HOSTLABEL, _URLCH, _TLDS, _URLCH), re.I)
HANDLE_RE = re.compile(r"(?<![A-Za-z0-9_.@])@[A-Za-z0-9_]{2,}")
HASHTAG_RE = re.compile(r"(?<![\w#&])#[^\s#.,!?、。！？()\[\]{}\"']+")
CJK = "ᄀ-ᇿ⺀-鿿ꥠ-꥿가-힯豈-﫿　-〿"
_CJK_SPACE_RE = re.compile(r"\s+(?=[%s])|(?<=[%s])\s+" % (CJK, CJK))


# --- small helpers --------------------------------------------------------------------------

def primary(lang):
    return str(lang or "").split("-")[0].lower()


def fold(s):
    return unicodedata.normalize("NFKC", s if isinstance(s, str) else str(s or "")).casefold()


def memory_dir(root):
    return os.path.join(paths(root)["memory"], "social")


def memory_rel(*parts):
    return "/".join((".claude", "herald", "memory", "social") + parts)


def log_path(root):
    return os.path.join(memory_dir(root), "log.jsonl")


def guide_rel(sns):
    return "%s/%s.md" % (CHANNELS_DIR, sns)


def show(root, rev, rel):
    proc = run(["git", "show", "%s:%s" % (rev, rel)], cwd=root, check=False)
    return proc.stdout if proc.returncode == 0 else None


def _on_base(root, cfg):
    branch = git(root, "rev-parse", "--abbrev-ref", "HEAD", check=False).strip()
    if branch != cfg.base:
        raise HeraldError("social drafts read the committed base — switch to %s first (now on %s)" % (cfg.base, branch))


def _rule_hash(rule):
    return hashlib.sha1(json.dumps([rule.get("pattern", ""), bool(rule.get("regex"))],
                                   ensure_ascii=False).encode("utf-8")).hexdigest()[:8]


def _json_block(rx, text):
    """(dict, error) of the first head block matching rx."""
    m = rx.search(text or "")
    if not m:
        return None, "head block missing"
    try:
        data = json.loads(m.group(1))
    except ValueError as e:
        return None, "head block is not JSON (%s)" % e
    if not isinstance(data, dict):
        return None, "head block is not a JSON object"
    return data, None


def parse_channel(text):
    return _json_block(CHANNEL_RE, text)


def parse_persona(text):
    return _json_block(PERSONA_RE, text)


def researched_region(text):
    t = text or ""
    if t.count(RESEARCHED_START) != 1 or t.count(RESEARCHED_END) != 1:
        return None
    a, b = t.index(RESEARCHED_START), t.index(RESEARCHED_END)
    return t[a + len(RESEARCHED_START):b] if a < b else None


def outside_region(text):
    """The text outside the head block and the researched region (the house rules)."""
    t = CHANNEL_RE.sub("", text or "", count=1)
    if RESEARCHED_START in t and RESEARCHED_END in t:
        a, b = t.index(RESEARCHED_START), t.index(RESEARCHED_END)
        if a < b:
            t = t[:a] + t[b + len(RESEARCHED_END):]
    return t.strip()


# --- terms, sentences, URLs -------------------------------------------------------------------

def site_host(cfg):
    from urllib.parse import urlparse

    host = (urlparse(cfg.get("site", "base_url") or "").hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def service_terms(persona, cfg):
    """[(folded term, [folded excludes])] — the persona's terms plus the site host (S4)."""
    out = []
    for t in (persona or {}).get("service_terms") or []:
        if isinstance(t, str) and t.strip():
            out.append((fold(t.strip()), []))
        elif isinstance(t, dict) and isinstance(t.get("term"), str) and t["term"].strip():
            out.append((fold(t["term"].strip()), [fold(x) for x in t.get("exclude") or [] if isinstance(x, str) and x]))
    host = site_host(cfg)
    if host and host not in [x[0] for x in out]:
        out.append((host, []))
    return out


def _latin(term):
    return bool(re.match(r"^[a-z0-9][a-z0-9._\- ]*$", term))


def term_spans(norm, terms):
    spans = []
    for term, excludes in terms:
        masked = norm
        for e in excludes:
            masked = masked.replace(e, " " * len(e))
        rx = (r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(term)) if _latin(term) else re.escape(term)
        spans += [m.span() for m in re.finditer(rx, masked)]
    return spans


def sentence_spans(text):
    """Sentence boundaries: newlines, 。！？ always; . ! ? only before whitespace or the end (so
    `example.com`, `Node.js` and decimals stay whole)."""
    spans, start = [], 0
    for m in re.finditer(r"\n|[。！？]|[.!?](?=\s|$)", text):
        spans.append((start, m.end()))
        start = m.end()
    spans.append((start, len(text)))
    return [s for s in spans if text[s[0]:s[1]].strip()]


def _trim_url(u):
    prev = None
    while prev != u:
        prev = u
        u = u.rstrip(".,!?;:'")
        if u.endswith(")") and u.count("(") < u.count(")"):
            u = u[:-1]
    return u


def find_urls(text):
    out = []
    for m in URL_RE.finditer(text):
        u = _trim_url(m.group(0))
        if u:
            out.append((m.start(), m.start() + len(u), u))
    return out


def norm_url(u):
    u = re.sub(r"^https?://", "", u.strip(), flags=re.I)
    u = re.split(r"[?#]", u, 1)[0]
    host, sep, path = u.partition("/")
    return (host.lower() + sep + path).rstrip("/")


def mask_urls(text):
    out = text
    for a, b, _ in find_urls(text):
        out = out[:a] + " " * (b - a) + out[b:]
    return out


# twitter-text v3 weights: these ranges count 1, every other code point 2 (03-social.md §2)
_LIGHT = ((0x0000, 0x10FF), (0x2000, 0x200D), (0x2010, 0x201F), (0x2032, 0x2037))


def _wide(c):
    o = ord(c)
    return not any(a <= o <= b for a, b in _LIGHT)


def _weight(s):
    """An emoji sequence (ZWJ joins, skin tones, variation selectors) counts as one unit."""
    n, join, ri = 0, False, False
    for c in s:
        o = ord(c)
        if 0x1F1E6 <= o <= 0x1F1FF:  # a flag is a pair of regional indicators
            ri = not ri
            if not ri:
                continue
        else:
            ri = False
        if o == 0x20E3:  # keycap: `1️⃣` counts as one emoji (2) — the digit already counted 1
            n += 1
            continue
        if o == 0x200D:
            join = True
            continue
        if unicodedata.combining(c) or o in (0xFE0F, 0xFE0E) or 0x1F3FB <= o <= 0x1F3FF:
            continue
        if join:
            join = False
            continue
        n += 2 if _wide(c) else 1
    return n


def post_length(text, count, url_len):
    text = unicodedata.normalize("NFC", text).strip()
    if count != "weighted":
        return len(text)
    total, pos = 0, 0
    for a, b, _ in find_urls(text):
        total += _weight(text[pos:a]) + int(url_len or 23)
        pos = b
    return total + _weight(text[pos:])


def disclosure_present(norm, text):
    t = fold(text).strip()
    if not t:
        return False
    if t.startswith("#"):
        return re.search(r"(?<!\w)%s(?!\w)" % re.escape(t), norm) is not None
    # a latin label is a word, not letters inside one (`ad` is not in `today`, `pr` not in `product`)
    head = r"(?<![a-z0-9])" if re.match(r"[a-z0-9]", t) else ""
    tail = r"(?![a-z0-9])" if re.search(r"[a-z0-9]$", t) else ""
    return re.search(head + re.escape(t) + tail, norm) is not None


def plain(text):
    """Markdown → comparable text (S7): no frontmatter, no markup, CJK-adjacent whitespace
    removed (hard-wrapped Japanese), other whitespace collapsed."""
    t = unicodedata.normalize("NFKC", (text or "").replace("\r\n", "\n"))
    t = re.sub(r"\A---\n.*?\n---\n?", "", t, flags=re.S)
    t = re.sub(r"\A\+\+\+\n.*?\n\+\+\+\n?", "", t, flags=re.S)
    t = re.sub(r"<!--.*?-->", " ", t, flags=re.S)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", t)
    t = re.sub(r"\[\^[^\]]*\]:?", " ", t)
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"(?m)^[ \t]{0,3}(?:#{1,6}|>|[-*+]|\d+[.)])[ \t]+", "", t)
    t = re.sub(r"[*_~`]+", "", t)
    t = _CJK_SPACE_RE.sub("", t)
    return re.sub(r"\s+", " ", t).strip()


# --- head block validation --------------------------------------------------------------------

def _forbidden_problems(rules, where):
    errors, warnings = [], []
    if not isinstance(rules, list):
        return ["%s forbidden must be a list" % where], []
    for i, r in enumerate(rules):
        if not isinstance(r, dict) or not isinstance(r.get("pattern"), str) or not r["pattern"]:
            errors.append("%s forbidden[%d] needs a pattern" % (where, i))
            continue
        if r.get("status") not in ("draft", "confirmed"):
            errors.append("%s forbidden[%d] status must be draft or confirmed" % (where, i))
        if r.get("regex"):
            try:
                re.compile(r["pattern"])
            except re.error as e:
                (errors if r.get("status") == "confirmed" else warnings).append(
                    "%s forbidden[%d] regex does not compile (%s)" % (where, i, e))
    return errors, warnings


def _hashtags_ok(v):
    return isinstance(v, list) and len(v) == 2 and all(isinstance(x, int) and x >= 0 for x in v) and v[0] <= v[1]


def channel_problems(h, name, cfg=None, persona=None, others=None):
    """(errors, warnings) of a channel head block. `others` = {name: header} of the other guides
    (alias collisions); `persona` for the script-coverage warning."""
    errors, warnings = [], []
    if not isinstance(h, dict):
        return ["head block missing"], []
    if h.get("name") != name:
        errors.append("name %r must equal the file name %r" % (h.get("name"), name))
    if not SNS_RE.match(name or "") or name in RESERVED:
        errors.append("channel name %r must be [a-z0-9-] and not one of %s" % (name, ", ".join(RESERVED)))
    aliases = h.get("aliases", [])
    if not isinstance(aliases, list) or not all(isinstance(a, str) and SNS_RE.match(a) and a not in RESERVED
                                                 for a in aliases):
        errors.append("aliases must be a list of [a-z0-9-] names")
        aliases = []
    taken = {}
    for o, oh in (others or {}).items():
        if o == name:
            continue
        taken[o] = o
        for a in (oh or {}).get("aliases") or []:
            taken[a] = o
    for a in aliases + [name]:
        if a in taken:
            errors.append("%s is already the name or an alias of %s" % (a, taken[a]))
    lang = h.get("lang")
    if not isinstance(lang, str) or not LANG_RE.match(lang):
        errors.append("lang %r is not a language code" % lang)
    if not isinstance(h.get("max_chars"), int) or h["max_chars"] <= 0:
        errors.append("max_chars must be a positive integer")
    if h.get("count", "chars") not in ("chars", "weighted"):
        errors.append("count must be chars or weighted")
    if "url_len" in h and (not isinstance(h["url_len"], int) or h["url_len"] < 0):
        errors.append("url_len must be a non-negative integer")
    if not _hashtags_ok(h.get("hashtags", [0, 30])):
        errors.append("hashtags must be [min, max]")
    if h.get("link", "any") not in LINK_VALUES:
        errors.append("link must be one of %s" % ", ".join(LINK_VALUES))
    if not isinstance(h.get("researched_at"), str) or not DATE_RE.match(h["researched_at"]):
        errors.append("researched_at must be YYYY-MM-DD")
    house = h.get("house") or {}
    if not isinstance(house, dict):
        errors.append("house must be an object")
        house = {}
    for k, v in house.items():
        if k not in HOUSE_KEYS:
            warnings.append("house.%s is ignored (house narrows only %s)" % (k, ", ".join(HOUSE_KEYS)))
        elif k == "max_chars" and (not isinstance(v, int) or v <= 0):
            errors.append("house.max_chars must be a positive integer")
        elif k == "hashtags" and not _hashtags_ok(v):
            errors.append("house.hashtags must be [min, max]")
        elif k == "link" and v not in LINK_VALUES:
            errors.append("house.link must be one of %s" % ", ".join(LINK_VALUES))
    if isinstance(house.get("max_chars"), int) and isinstance(h.get("max_chars"), int) and house["max_chars"] > h["max_chars"]:
        warnings.append("house.max_chars is looser than the researched max_chars")
    disc = h.get("disclosure")
    seen = set()
    if not isinstance(disc, list):
        errors.append("disclosure must be a list (S10)")
        disc = []
    for i, d in enumerate(disc):
        if not isinstance(d, dict) or d.get("kind") not in ("ad", "operator") or \
                d.get("where") not in WHERE_STRENGTH or not isinstance(d.get("required"), bool):
            errors.append("disclosure[%d] needs kind ad|operator, required true|false, where post|setting|profile" % i)
            continue
        if (d["kind"], d["where"]) in seen:
            errors.append("disclosure has two %s/%s items" % (d["kind"], d["where"]))
        seen.add((d["kind"], d["where"]))
        if "text" in d and not isinstance(d["text"], str):
            errors.append("disclosure[%d] text must be a string" % i)
            continue
        if d["where"] in ("post", "setting") and not unicodedata.normalize("NFKC", d.get("text") or "").strip():
            errors.append("disclosure[%d] (%s/%s) needs a text" % (i, d["kind"], d["where"]))
        elif d["where"] == "post" and find_urls(d.get("text") or ""):
            errors.append("disclosure[%d] text contains a URL — post checks never read text inside links; "
                          "write the operator without its domain" % i)
    waiver = h.get("disclosure_waiver")
    if waiver is not None and not (isinstance(waiver, dict) and waiver.get("kind") == "ad"
                                   and isinstance(waiver.get("reason"), str) and waiver["reason"].strip()
                                   and isinstance(waiver.get("approved_at"), str) and DATE_RE.match(waiver["approved_at"])):
        errors.append("disclosure_waiver must be null or {kind: ad, reason, approved_at: YYYY-MM-DD}")
    if not any(isinstance(d, dict) and d.get("kind") == "ad" and d.get("required") is True
               and d.get("where") in ("post", "setting") for d in disc) and not waiver:
        errors.append("no required ad disclosure in the post or as a platform setting, and no disclosure_waiver (S10)")
    e, w = _forbidden_problems(h.get("forbidden", []), "channel")
    errors += e
    warnings += w
    if isinstance(lang, str) and persona is not None:
        if not any(_script_matches(t, lang) for t, _ in service_terms(persona, cfg) if cfg) and lang and \
                primary(lang) in ("ja", "ko", "zh"):
            warnings.append("persona service_terms has no term in this channel's script (%s) — add the "
                            "transliteration the posts will use" % lang)
    return errors, warnings


def _script_matches(term, lang):
    p = primary(lang)
    if p == "ja":
        return bool(re.search(r"[぀-ヿ一-鿿]", term))
    if p == "ko":
        return bool(re.search(r"[가-힯]", term))
    if p == "zh":
        return bool(re.search(r"[一-鿿]", term))
    return True


def persona_problems(p, cfg=None):
    errors, warnings = [], []
    if not isinstance(p, dict):
        return ["head block missing"], []
    terms = p.get("service_terms")
    if not isinstance(terms, list):
        errors.append("service_terms must be a list")
        terms = []
    host = site_host(cfg) if cfg else ""
    named = 0
    for i, t in enumerate(terms):
        if isinstance(t, str):
            term, excludes = t, []
        elif isinstance(t, dict) and isinstance(t.get("term"), str):
            term, excludes = t["term"], t.get("exclude") or []
        else:
            errors.append("service_terms[%d] must be a string or {term, exclude}" % i)
            continue
        if not term.strip():
            errors.append("service_terms[%d] is empty" % i)
            continue
        if fold(term).strip() != host:
            named += 1
        if not isinstance(excludes, list):
            errors.append("service_terms[%d].exclude must be a list" % i)
            continue
        for e in excludes:
            if not isinstance(e, str) or fold(term) not in fold(e) or fold(e) == fold(term):
                errors.append("service_terms[%d].exclude %r must contain the term and be longer" % (i, e))
    if not named:
        errors.append("service_terms needs at least one name besides the site host (S4)")
    mix = p.get("mix", {"promo": 1, "daily": 3})
    if not (isinstance(mix, dict) and isinstance(mix.get("promo"), int) and isinstance(mix.get("daily"), int)
            and mix["promo"] >= 0 and mix["daily"] >= 0 and mix["promo"] + mix["daily"] > 0):
        errors.append("mix must be {promo: n, daily: m}")
    e, w = _forbidden_problems(p.get("forbidden", []), "persona")
    return errors + e, warnings + w


# --- channel guides at HEAD ---------------------------------------------------------------------

def guides(root, rev="HEAD"):
    """{name: (rel, header or None, error)} for every guide committed at rev."""
    out = {}
    listing = git(root, "ls-tree", "--name-only", rev, CHANNELS_DIR + "/", check=False)
    for rel in listing.split("\n"):
        rel = rel.strip()
        if not rel.endswith(".md"):
            continue
        name = os.path.basename(rel)[:-3]
        h, err = parse_channel(show(root, rev, rel))
        out[name] = (rel, h, err)
    return out


def resolve(root, name, rev="HEAD"):
    n = (name or "").strip().lower()
    if not SNS_RE.match(n) or n in RESERVED:
        raise HeraldError("invalid channel name %r ([a-z0-9-], not %s)" % (name, ", ".join(RESERVED)))
    gs = guides(root, rev)
    if n in gs:
        return n
    for g, (_, h, _) in sorted(gs.items()):
        if n in ((h or {}).get("aliases") or []):
            return g
    raise HeraldError("no channel guide for %s — run `/hrd social --add %s` first" % (n, n))


def _load_committed(root, cfg, sns):
    """(guide header, persona header) at HEAD, refusing invalid ones (guide-invalid)."""
    gs = guides(root)
    if sns not in gs:
        raise HeraldError("guide-invalid: no channel guide %s on base (removed?) — `/hrd social --add %s`" % (sns, sns))
    rel, h, err = gs[sns]
    others = {k: v[1] for k, v in gs.items()}
    if err:
        raise HeraldError("guide-invalid: %s: %s — fix it with `/hrd social --edit %s`" % (rel, err, sns))
    ptext = show(root, "HEAD", PERSONA)
    if ptext is None:
        raise HeraldError("no %s on base — run `/hrd social --setup` first" % PERSONA)
    p, perr = parse_persona(ptext)
    if perr:
        raise HeraldError("guide-invalid: %s: %s — fix it with `/hrd social --persona`" % (PERSONA, perr))
    perrors, _ = persona_problems(p, cfg)
    if perrors:
        raise HeraldError("guide-invalid: %s: %s — fix it with `/hrd social --persona`" % (PERSONA, "; ".join(perrors)))
    errors, _ = channel_problems(h, sns, cfg, None, others)
    if errors:
        raise HeraldError("guide-invalid: %s: %s — fix it with `/hrd social --edit %s`" % (rel, "; ".join(errors), sns))
    return h, p


def effective(h):
    """Research fields with the house overrides (house wins; only HOUSE_KEYS)."""
    eff = {"max_chars": h.get("max_chars"), "count": h.get("count", "chars"), "url_len": h.get("url_len", 23),
           "hashtags": h.get("hashtags", [0, 30]), "link": h.get("link", "any")}
    for k, v in (h.get("house") or {}).items():
        if k in HOUSE_KEYS:
            eff[k] = v
    return eff


def _stale(h, today=None):
    try:
        d = datetime.date.fromisoformat(h.get("researched_at") or "")
    except ValueError:
        return True
    return ((today or datetime.date.today()) - d).days > STALE_DAYS


def promo_lang(cfg, lang):
    """The configured language a channel's posts promote in, or None (daily only, S8)."""
    langs = [cfg.source_lang()] + cfg.target_langs()
    for x in langs:
        if x == lang:
            return x
    # a regional tag on the channel (`ja-JP`) promotes the bare configured language (`ja`);
    # two different regions (`zh-TW` vs `zh-CN`) are different languages
    for x in langs:
        if "-" not in x and primary(x) == primary(lang):
            return x
    return None


def daily_service_allowed(cfg, lang):
    """promotion.md is written in config.language: only posts in that language may quote it, so
    only they may mention the service at all (S6, S7)."""
    return primary(lang) == primary(cfg.get("language") or "en")


# --- the log ------------------------------------------------------------------------------------

def events(root):
    return read_jsonl(log_path(root))


def _log(root, rec):
    rec = dict(rec)
    rec.setdefault("at", now_iso())
    append_jsonl(log_path(root), rec)
    return rec


def latest_status(root):
    """{draft rel: the last status event}."""
    out = {}
    for e in events(root):
        if e.get("event") == "status" and e.get("draft"):
            out[e["draft"]] = e
    return out


def drafted_record(root, rel):
    rec = None
    for e in events(root):
        if e.get("event") == "status" and e.get("status") == "drafted" and e.get("draft") == rel:
            rec = e
    return rec


def recent_mix(root, n=10):
    posts = [e for e in latest_status(root).values() if e.get("status") in ("approved", "uploaded")]
    posts.sort(key=lambda e: e.get("at") or "")
    posts = posts[-n:]
    promo = sum(1 for e in posts if e.get("profile") in ("promo", "daily+service"))
    return {"n": len(posts), "promo": promo, "daily": len(posts) - promo}


def recent_approved(root, sns, n=10):
    rows = [e for e in latest_status(root).values()
            if e.get("sns") == sns and e.get("status") in ("approved", "uploaded") and e.get("approved_copy")]
    rows.sort(key=lambda e: e.get("at") or "")
    return [e["approved_copy"] for e in rows[-n:] if os.path.exists(os.path.join(root, e["approved_copy"]))]


# --- prepare (S7, S8) ---------------------------------------------------------------------------

def _require_setup(root, cfg):
    if "distributor" not in (cfg.get("roles", "conditional") or []):
        raise HeraldError("the distributor role is not enabled — run `/hrd social --setup` first")
    if not git_ok(root, "cat-file", "-e", "HEAD:%s" % DISTRIBUTOR):
        raise HeraldError("%s is not on base — run `/hrd social --setup` first" % DISTRIBUTOR)


def _brief(root, tid):
    seen = set()
    while tid and tid.startswith("tr-") and tid not in seen:
        seen.add(tid)
        st = read_json_at(root, "HEAD", work_rel(tid, "state.json")) or {}
        tid = st.get("inherited_from")
    if not tid:
        return None
    rel = work_rel(tid, "brief.md")
    return rel if git_ok(root, "cat-file", "-e", "HEAD:%s" % rel) else None


def promotable(root, cfg, slug, lang):
    """S7/S8: whether `slug` may be promoted in `lang` (a configured language). Returns the basis
    {body, url, ref_topic, brief, unread} or raises with the reason and the next step."""
    from . import ghstate, integrity
    from .hashing import bundle_hash

    if not (cfg.get("site", "base_url") or "").strip():
        raise HeraldError("site.base_url is empty — a post would link a relative path; set it with `/hrd config`")
    pub = load_published(root)
    art = find_article(pub, slug)
    if not art:
        moved = next((a["slug"] for a in pub["articles"] for m in a.get("moved_from") or [] if m.get("slug") == slug), None)
        raise HeraldError("%s is not a published article%s" % (slug, " (it moved to %s)" % moved if moved else ""))
    if art.get("origin") != "herald":
        raise HeraldError("%s is an external article — its body never passed verify, so it is not promoted (03-social.md §7)" % slug)
    if art.get("withdrawn"):
        raise HeraldError("%s is withdrawn" % slug)
    try:
        members = ghstate.herald_set(root, cfg, pub=pub)
    except Exception as e:  # noqa: BLE001
        raise HeraldError("gh unavailable (%s) — promoting needs the merged-PR state (gh auth)" % e)
    m = members.get(slug)
    if not m:
        raise HeraldError("%s is not in the Herald article set" % slug)
    if m.get("merged_unrecorded"):
        raise HeraldError("%s has a merged change that is not deployed and recorded yet — `/hrd ship` first "
                          "(the live URL does not show it)" % slug)
    ref = m.get("ref_topic")
    led = ledger_latest(root, ref) if ref else None
    if led is not None:
        ok = led.get("verified_hash") == bundle_hash(root, cfg, slug, rev="HEAD")
        basis = led.get("files")
        causes = [] if ok else ["ledger mismatch"]
    else:
        st = read_json_at(root, "HEAD", work_rel(ref, "state.json")) if ref else None
        if not ref or not st or not (st.get("verified_files") or st.get("verified_hash")):
            ok, causes, basis = False, ["no verified record for %s" % (ref or "this article")], None
        else:
            causes = integrity._causes(root, cfg, "HEAD", slug, ref, None, art)
            ok = not causes
            basis = st.get("verified_files")
    if not ok:
        raise HeraldError("%s differs from what was verified (%s) — `/hrd ship` handles it first" % (slug, ", ".join(causes)))
    src = cfg.source_lang()
    if lang == src:
        unread = art.get("human_reviewed") is False or bool(art.get("auto_accepted"))
        body, url = cfg.body_path(slug), cfg.article_url(slug)
    else:
        tr = (art.get("translations") or {}).get(lang)
        if not tr or lang in (art.get("withdrawn_langs") or []):
            raise HeraldError("%s has no published %s translation — `/hrd translate %s --lang %s` first" % (slug, lang, slug, lang))
        body, url = cfg.body_path(slug, lang), cfg.article_url(slug, lang)
        if basis is None or body not in basis:
            raise HeraldError("the %s translation of %s is not part of the verified bundle — `/hrd ship` first" % (lang, slug))
        unread = tr.get("human_reviewed") is False or bool(tr.get("auto_accepted"))
    if not git_ok(root, "cat-file", "-e", "HEAD:%s" % body):
        raise HeraldError("%s is not on base" % body)
    return {"body": body, "url": url, "ref_topic": ref, "brief": _brief(root, ref), "unread": unread}


def _run_id(root):
    run_id = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    used = {e.get("run") for e in events(root)}
    if run_id not in used:
        return run_id
    n = 2
    while "%s-%d" % (run_id, n) in used:
        n += 1
    return "%s-%d" % (run_id, n)


def prepare(root, cfg, sns, slug=None, n=3):
    _on_base(root, cfg)
    if not 1 <= int(n) <= MAX_N:
        raise HeraldError("--n must be 1–%d" % MAX_N)
    _require_setup(root, cfg)
    sns = resolve(root, sns)
    h, persona = _load_committed(root, cfg, sns)
    lang = h["lang"]
    plang = promo_lang(cfg, lang)
    warnings = []
    if _stale(h):
        warnings.append("the %s guide was researched on %s (over %d days ago) — `/hrd social --refresh %s` when "
                        "convenient" % (sns, h.get("researched_at"), STALE_DAYS, sns))
    if primary(lang) not in PATTERNS:
        warnings.append("no default S9 patterns for %s — a human checks statistics and service-experience sentences" % lang)
    kind = "promo" if slug else "daily"
    basis = {}
    if slug:
        if plang is None:
            raise HeraldError("the %s guide's language %s is neither the source nor a translation target — this "
                              "channel takes daily posts only" % (sns, lang))
        basis = promotable(root, cfg, slug, plang)
        basis["body_blob"] = git(root, "rev-parse", "HEAD:%s" % basis["body"]).strip()
        if basis["unread"]:
            warnings.append("%s was published without a human reading it (auto publish) — read it before promoting" % slug)
    run_id = _run_id(root)
    drafts = [memory_rel(sns, "%s-%s-%d.md" % (run_id, slug or "daily", i)) for i in range(1, int(n) + 1)]
    date = run_id[:8]
    for d in drafts:
        _log(root, {"event": "status", "status": "drafted", "run": run_id, "sns": sns, "kind": kind, "slug": slug,
                    "draft": d, "lang": lang, "url": basis.get("url"), "body": basis.get("body"),
                    "body_blob": basis.get("body_blob"),
                    "signal_topic": "social:%s:%s" % (sns, date)})
    os.makedirs(os.path.join(memory_dir(root), sns), exist_ok=True)
    read = {"guide": guide_rel(sns), "persona": PERSONA, "promotion": PROMOTION,
            "recent": recent_approved(root, sns)}
    if slug:
        read.update({"body": basis["body"], "url": basis["url"], "brief": basis["brief"]})
    else:
        read["notes"] = NOTES if git_ok(root, "cat-file", "-e", "HEAD:%s" % NOTES) else None
    eff = effective(h)
    return {"run": run_id, "sns": sns, "kind": kind, "slug": slug, "lang": lang, "drafts": drafts, "read": read,
            "daily_service_allowed": daily_service_allowed(cfg, lang),
            "limits": eff, "disclosure": h.get("disclosure"), "disclosure_waiver": h.get("disclosure_waiver"),
            "mix": persona.get("mix", {"promo": 1, "daily": 3}), "recent_mix": recent_mix(root),
            "signal_topic": "social:%s:%s" % (sns, date), "warnings": warnings}


# --- check (S6, S7, S9, S10) ------------------------------------------------------------------

def parse_draft(text):
    """(header dict, body, error). Header lines `key: value`; `sources` is one-line JSON."""
    t = (text or "").replace("\r\n", "\n")
    m = re.match(r"\A---\n(.*?)\n---\n?(.*)\Z", t, re.S)
    if not m:
        return None, t, "draft header (---) missing"
    hdr = {}
    for line in m.group(1).split("\n"):
        if not line.strip():
            continue
        key, sep, val = line.partition(":")
        if not sep:
            return None, m.group(2), "header line %r is not key: value" % line
        key, val = key.strip(), val.strip()
        if key == "sources":
            try:
                val = json.loads(val) if val else []
            except ValueError:
                return None, m.group(2), "sources is not one-line JSON"
        elif val in ("", "null", "~"):
            val = None
        hdr[key] = val
    return hdr, m.group(2), None


def _gate_forbidden(root, cfg, lang):
    from .validate import lang_rules, load_rules

    rules = load_rules(root, rev="HEAD")  # raises on an unreadable gate-rules.json (fail closed)
    known = promo_lang(cfg, lang) or lang
    _, forbidden = lang_rules(rules, cfg, known)
    return [r for r in forbidden if isinstance(r, dict) and r.get("scope", "all") != "article"]


def _overridable(rid, profile):
    return rid in OVERRIDABLE or (rid == "s9a-service-experience" and profile == "promo")


def check_draft(root, cfg, rel, record=True):
    """The post rules on one draft. Every basis comes from the `drafted` record and HEAD."""
    _on_base(root, cfg)
    rel = rel.replace(os.sep, "/")
    if os.path.isabs(rel):
        rel = os.path.relpath(rel, root).replace(os.sep, "/")
    rec = drafted_record(root, rel)
    if not rec:
        raise HeraldError("%s is not a draft `HRD social prepare` laid out" % rel)
    try:
        raw = open(os.path.join(root, rel), "rb").read()
    except OSError:
        raise HeraldError("draft %s does not exist" % rel)
    text = raw.decode("utf-8-sig", errors="replace")
    failed, warnings = [], []
    profile = rec.get("kind")

    def fail(rid, detail):
        failed.append({"id": rid, "overridable": _overridable(rid, profile), "detail": detail})

    hdr, body, herr = parse_draft(text)
    if herr:
        fail("header-mismatch", herr)
        hdr = {}
    else:
        for k in ("sns", "kind", "slug", "run"):
            if (hdr.get(k) or None) != (rec.get(k) or None):
                fail("header-mismatch", "header %s=%r but prepare recorded %r" % (k, hdr.get(k), rec.get(k)))
    sns = rec["sns"]
    try:
        h, persona = _load_committed(root, cfg, sns)
    except HeraldError as e:
        fail("guide-invalid", str(e))
        return _result(root, rel, raw, rec, profile, failed, warnings, [], record)
    lang = rec.get("lang") or h["lang"]
    if h["lang"] != lang:
        fail("basis-changed", "the %s guide's language changed from %s to %s since prepare — prepare again"
             % (sns, lang, h["lang"]))
    if rec.get("body"):
        blob = git(root, "rev-parse", "-q", "--verify", "HEAD:%s" % rec["body"], check=False).strip()
        if blob != rec.get("body_blob"):
            fail("basis-changed", "%s changed on base since prepare checked it — prepare again" % rec["body"])
    eff = effective(h)
    post = body.strip()
    norm = fold(post)
    urls = find_urls(post)
    terms = service_terms(persona, cfg)
    masked = mask_urls(norm)
    mentions = term_spans(masked, terms)
    if rec.get("kind") == "promo":
        profile = "promo"
    else:
        profile = "daily+service" if mentions else "daily"
    # length and hashtags
    n = post_length(post, eff["count"], eff["url_len"])
    if eff.get("max_chars") and n > eff["max_chars"]:
        fail("length", "%d > %d (%s)" % (n, eff["max_chars"], eff["count"]))
    disc = h.get("disclosure") or []
    disc_tags = {fold(d.get("text") or "").strip() for d in disc if fold(d.get("text") or "").strip().startswith("#")}
    tags = [t for t in HASHTAG_RE.findall(masked) if t not in disc_tags]
    lo, hi = eff["hashtags"]
    if not lo <= len(tags) <= hi:
        fail("hashtags", "%d hashtags, allowed %d–%d" % (len(tags), lo, hi))
    # links
    if profile == "promo":
        want = norm_url(rec.get("url") or "")
        if eff["link"] == "none":
            for _, _, u in urls:
                fail("promo-url", "this channel takes no link in the post: %s" % u)
        else:
            if not urls:
                fail("promo-link-missing", "the post needs the article link %s" % rec.get("url"))
            for _, _, u in urls:
                if norm_url(u) != want:
                    fail("promo-url", "%s is not the article URL %s" % (u, rec.get("url")))
            if urls and eff["link"] == "end":
                tail = post[urls[-1][1]:]
                for d in disc:
                    tail = tail.replace(d.get("text") or "\0", " ")
                tail = HASHTAG_RE.sub(" ", tail)
                if re.search(r"\w", tail):
                    fail("link-position", "the link must come last (only hashtags after it)")
            elif urls and eff["link"] == "start" and post[:urls[0][0]].strip():
                fail("link-position", "the link must come first")
    else:
        for _, _, u in urls:
            fail("daily-url", "a daily post carries no link: %s" % u)
    # disclosure (S10)
    settings = []
    if profile in ("promo", "daily+service"):
        for d in disc:
            if d.get("where") == "post":
                if not disclosure_present(masked, d.get("text") or ""):  # never inside a URL
                    if d.get("required"):
                        fail("disclosure", "missing %s disclosure %r" % (d.get("kind"), d.get("text")))
                    else:
                        warnings.append("optional %s disclosure %r not in the post" % (d.get("kind"), d.get("text")))
            elif d.get("where") == "setting" and d.get("required"):
                settings.append(d.get("kind"))
    if profile == "daily+service" and not daily_service_allowed(cfg, lang):
        fail("service-mention-not-allowed", "posts in %s may not mention the service (promotion.md is in %s)"
             % (lang, cfg.get("language")))
    # sources (S7)
    _check_sources(root, cfg, rec, hdr, profile, lang, fail)
    # forbidden
    try:
        gate = _gate_forbidden(root, cfg, lang)
    except HeraldError as e:
        gate = []
        fail("forbidden-invalid", str(e))
    rules = list(h.get("forbidden") or []) + list(persona.get("forbidden") or []) + gate
    for r in rules:
        pat = r.get("pattern") or ""
        if not pat:
            continue
        if r.get("regex"):
            try:
                hit = re.search(pat, post)
            except re.error as e:
                if r.get("status") == "confirmed":
                    fail("forbidden-invalid", "confirmed rule %r does not compile (%s)" % (pat, e))
                else:
                    warnings.append("draft rule %r does not compile (%s)" % (pat, e))
                continue
        else:
            hit = pat in post
        if hit:
            if r.get("status") == "confirmed":
                fail("forbidden-confirmed", "forbidden %r%s" % (pat, " (%s)" % r["note"] if r.get("note") else ""))
            else:
                warnings.append("draft rule %r matched" % pat)
    # S9
    pats = PATTERNS.get(primary(lang))
    spans = sentence_spans(masked)

    def same_sentence(a_spans, b_spans):
        for s, e in spans:
            if any(s <= a < e for a, _ in a_spans) and any(s <= b < e for b, _ in b_spans):
                return masked[s:e].strip()
        return None

    if pats:
        exp = [m.span() for m in re.finditer(pats["experience"], masked, re.I)]
        hit = same_sentence(mentions, exp)
        if hit:
            fail("s9a-service-experience", "the service told as a personal experience: %r" % hit[:120])
    else:
        warnings.append("no default S9 patterns for %s — check statistics and service-experience sentences by hand" % lang)
    if profile in ("daily", "daily+service"):
        unit = [m.group(0) for m in UNIT_RE.finditer(masked)] + [m.group(0) for m in BAE_RE.finditer(masked)]
        if unit:
            fail("s9b-statistic", "statistic-like numbers in a daily post: %s" % ", ".join(unit[:3]))
        if pats:
            vocab = [m.span() for m in re.finditer(pats["stats"], masked, re.I)]
            digits = [m.span() for m in DIGIT_RE.finditer(masked)]
            hit = same_sentence(vocab, digits)
            if hit:
                fail("s9b-statistic", "statistics wording with a number: %r" % hit[:120])
    return _result(root, rel, raw, rec, profile, failed, warnings, settings, record)


def _check_sources(root, cfg, rec, hdr, profile, lang, fail):
    sources = hdr.get("sources") if isinstance(hdr, dict) else None
    sources = sources if sources is not None else []
    if not isinstance(sources, list) or not all(isinstance(s, dict) for s in sources):
        fail("header-mismatch", "sources must be a JSON list of {text, from}")
        return
    if profile == "daily":
        if sources:
            fail("daily-sources", "a daily post states no facts — sources must be []")
        return
    if not sources:
        fail("sources", "a %s post needs at least one source quote" % profile)
        return
    cache = {}

    def text_of(rel):
        if rel not in cache:
            cache[rel] = plain(show(root, "HEAD", rel) or "")
        return cache[rel]

    for s in sources:
        quote, origin = s.get("text"), s.get("from")
        if not isinstance(quote, str) or len(re.sub(r"\s", "", plain(quote))) < 10:
            fail("sources", "a quote needs at least 10 characters: %r" % (quote,))
            continue
        q = plain(quote)
        if profile == "daily+service" and origin != "promotion":
            fail("sources", "a daily post mentioning the service quotes promotion.md only: %r" % quote[:80])
        elif origin == "body":
            if q not in text_of(rec.get("body") or ""):
                fail("sources", "not in the verified article (%s): %r" % (rec.get("body"), quote[:80]))
        elif origin == "promotion":
            if not daily_service_allowed(cfg, lang):
                fail("promotion-lang", "promotion.md is in %s; a %s post quotes the article only" % (cfg.get("language"), lang))
            elif q not in text_of(PROMOTION):
                fail("promotion-quote-not-found", "not in promotion.md: %r" % quote[:80])
        else:
            fail("sources", "from must be body or promotion: %r" % (origin,))


def _result(root, rel, raw, rec, profile, failed, warnings, settings, record):
    out = {"draft": rel, "run": rec.get("run"), "sns": rec.get("sns"), "profile": profile,
           "ok": not failed, "failed": failed, "warnings": warnings, "settings_to_confirm": settings,
           "sha256": hashlib.sha256(raw).hexdigest()}
    if record:
        _log(root, {"event": "check", "run": rec.get("run"), "sns": rec.get("sns"), "draft": rel,
                    "sha256": out["sha256"], "result": "pass" if out["ok"] else "fail", "profile": profile,
                    "failed_rules": [{"id": f["id"], "overridable": f["overridable"]} for f in failed]})
    return out


# --- close ---------------------------------------------------------------------------------------

def close(root, cfg, run_id, approved=None, reject_all=False, override=None, settings_confirmed=()):
    _on_base(root, cfg)
    if bool(approved) == bool(reject_all):
        raise HeraldError("give exactly one of --approved <draft> or --reject-all")
    latest = latest_status(root)
    drafts = [d for d, e in latest.items() if e.get("run") == run_id]
    if not drafts:
        raise HeraldError("no drafts recorded for run %s" % run_id)
    closed = [d for d in drafts if latest[d].get("status") != "drafted"]
    if closed:
        raise HeraldError("run %s is already closed (%s)" % (run_id, ", ".join(sorted(closed))))
    base = {k: latest[drafts[0]].get(k) for k in ("run", "sns", "kind", "slug")}
    if reject_all:
        for d in sorted(drafts):
            _log(root, dict(base, event="status", status="rejected", draft=d))
        return {"run": run_id, "rejected": sorted(drafts)}
    rel = approved.replace(os.sep, "/")
    if os.path.isabs(rel):
        rel = os.path.relpath(rel, root).replace(os.sep, "/")
    if rel not in drafts:
        raise HeraldError("%s is not a draft of run %s" % (rel, run_id))
    res = check_draft(root, cfg, rel)
    rec = latest[rel]
    read = [guide_rel(rec["sns"]), PERSONA, PROMOTION, GATE_RULES] + ([rec["body"]] if rec.get("body") else [])
    dirty = git(root, "status", "--porcelain", "--", *read).strip()
    if dirty:
        raise HeraldError("the sources this draft was checked against have local edits — commit or discard them first:\n%s" % dirty)
    hard = [f for f in res["failed"] if not f["overridable"]]
    if hard:
        raise HeraldError("cannot approve %s: %s" % (rel, "; ".join("%s (%s)" % (f["id"], f["detail"]) for f in hard)))
    soft = [f for f in res["failed"] if f["overridable"]]
    if soft and not (override or "").strip():
        raise HeraldError("%s fails %s — approve only with --override \"<the human's reason>\""
                          % (rel, ", ".join(f["id"] for f in soft)))
    missing = [k for k in res["settings_to_confirm"] if k not in (settings_confirmed or ())]
    if missing:
        raise HeraldError("disclosure-setting-unconfirmed: the human must confirm turning on the platform's %s "
                          "disclosure setting for this post (--setting-confirmed %s)" % (", ".join(missing), missing[0]))
    dest = memory_rel("approved", rec["sns"], os.path.basename(rel))
    os.makedirs(os.path.dirname(os.path.join(root, dest)), exist_ok=True)
    shutil.copyfile(os.path.join(root, rel), os.path.join(root, dest))
    entry = dict(base, event="status", status="approved", draft=rel, profile=res["profile"], approved_copy=dest,
                 sha256=res["sha256"], settings_confirmed=sorted(set(settings_confirmed or ())))
    if soft:
        entry["override"] = {"reason": override.strip(), "rules": [f["id"] for f in soft]}
    _log(root, entry)
    for d in sorted(drafts):
        if d != rel:
            _log(root, dict(base, event="status", status="unused", draft=d))
    return {"run": run_id, "approved": rel, "copy": dest, "profile": res["profile"],
            "override": entry.get("override"), "unused": sorted(d for d in drafts if d != rel)}


# --- list ----------------------------------------------------------------------------------------

def listing(root, cfg):
    gs = guides(root)
    others = {k: v[1] for k, v in gs.items()}
    rows = []
    for name, (rel, h, err) in sorted(gs.items()):
        row = {"name": name, "path": rel}
        if err:
            row["errors"] = [err]
        else:
            errors, warnings = channel_problems(h, name, cfg, None, others)
            plang = promo_lang(cfg, h.get("lang"))
            row.update({"aliases": h.get("aliases") or [], "lang": h.get("lang"), "researched_at": h.get("researched_at"),
                        "stale": _stale(h), "daily_only": plang is None,
                        "daily_service_allowed": daily_service_allowed(cfg, h.get("lang")),
                        "disclosure": h.get("disclosure"), "disclosure_waiver": h.get("disclosure_waiver"),
                        "limits": effective(h), "errors": errors, "warnings": warnings})
        rows.append(row)
    persona = show(root, "HEAD", PERSONA)
    p = parse_persona(persona)[0] if persona else None
    return {"channels": rows, "persona": bool(persona), "mix": (p or {}).get("mix"),
            "recent_mix": recent_mix(root), "site_host": site_host(cfg), "source_lang": cfg.source_lang(),
            "language": cfg.get("language"),
            "enabled": "distributor" in (cfg.get("roles", "conditional") or [])}


# --- lint (format + floor against HEAD) -----------------------------------------------------------

def _target_kind(target):
    t = target.replace(os.sep, "/")
    if t == PERSONA:
        return "persona"
    if t == NOTES:
        return "notes"
    if t.startswith(CHANNELS_DIR + "/") and t.endswith(".md") and t.count("/") == CHANNELS_DIR.count("/") + 1:
        return "channel"
    raise HeraldError("lint targets %s/<sns>.md, %s or %s" % (CHANNELS_DIR, PERSONA, NOTES))


def _forbidden_map(rules):
    return {_rule_hash(r): r for r in rules or [] if isinstance(r, dict) and r.get("pattern")}


def _floor_forbidden(old, new, need, strong):
    om, nm = _forbidden_map(old), _forbidden_map(new)
    for k, r in om.items():
        if r.get("status") == "confirmed" and (k not in nm or nm[k].get("status") != "confirmed"):
            need("forbidden:%s" % k, "confirmed rule %r removed or downgraded" % r.get("pattern"))
    for k, r in nm.items():
        if r.get("status") == "confirmed" and (k not in om or om[k].get("status") != "confirmed"):
            strong("forbidden:%s" % k, "rule %r confirmed" % r.get("pattern"))


def _floor_disclosure(old, new, need):
    old = [d for d in old or [] if isinstance(d, dict)]
    new = [d for d in new or [] if isinstance(d, dict)]
    new_keys = {(d.get("kind"), d.get("where")): d for d in new}
    old_keys = {(d.get("kind"), d.get("where")) for d in old}
    moved_to = set()
    for d in old:
        key = (d.get("kind"), d.get("where"))
        tok = "disclosure:%s/%s" % key
        n = new_keys.get(key)
        moved = False
        if n is None:  # a move: the same kind at a `where` HEAD did not have
            n = next((x for k, x in new_keys.items() if k[0] == key[0] and k not in old_keys and k not in moved_to), None)
            if n is not None:
                moved = True
                moved_to.add((n.get("kind"), n.get("where")))
                if WHERE_STRENGTH.get(n.get("where"), 0) < WHERE_STRENGTH.get(key[1], 0):
                    need(tok, "%s disclosure moved from %s to %s" % (key[0], key[1], n.get("where")))
        if n is None:
            need(tok, "%s/%s disclosure removed" % key)
            continue
        if d.get("required") and not n.get("required"):
            need(tok, "%s/%s disclosure no longer required" % key)
        if not moved and fold(d.get("text") or "").strip() != fold(n.get("text") or "").strip():
            need(tok, "%s/%s disclosure text changed" % key)


def lint(root, cfg, mode, file_path, target, allow_floor=(), strengthen=()):
    if mode not in MODES:
        raise HeraldError("--mode must be one of %s (refresh and evolve come with 0.12.0)" % ", ".join(MODES))
    target = target.replace(os.sep, "/")
    kind = _target_kind(target)
    full = file_path if os.path.isabs(file_path) else os.path.join(root, file_path)
    try:
        text = open(full, encoding="utf-8-sig").read()
    except OSError as e:
        raise HeraldError("cannot read %s: %s" % (file_path, e))
    head = show(root, "HEAD", target)
    if mode == "add" and head is not None:
        raise HeraldError("%s already exists — use `/hrd social --edit` (or --refresh)" % target)
    if mode == "edit" and head is None:
        raise HeraldError("%s is not on base — use `/hrd social --add`" % target)
    if kind == "channel" and mode not in ("add", "edit"):
        raise HeraldError("a channel guide is linted with --mode add (new) or edit (existing)")
    if kind == "channel" and mode == "edit" and head is None or kind == "channel" and mode == "add" and head is not None:
        raise HeraldError("mode %s does not fit %s" % (mode, target))
    if kind in ("persona", "notes") and mode not in ("setup", "persona"):
        raise HeraldError("the persona files are linted with --mode setup (new) or persona")
    if kind in ("persona", "notes") and mode == "setup" and head is not None:
        raise HeraldError("%s already exists — use --mode persona (`/hrd social --persona`)" % target)
    errors, warnings, floor, strong_list = [], [], [], []
    allow, strengthen_ok = set(allow_floor or ()), set(strengthen or ())
    used = set()

    def need(token, what):
        if token in allow:
            used.add(token)
            floor.append({"token": token, "what": what})
        else:
            errors.append("floor: %s — needs the human's approval (--allow-floor %s)" % (what, token))

    def strong(token, what):
        if mode in FLOOR_MODES_STRENGTHEN and token in strengthen_ok:
            used.add(token)
            strong_list.append({"token": token, "what": what})
        elif mode in FLOOR_MODES_STRENGTHEN:
            errors.append("%s — a human confirms rules (--strengthen %s after asking)" % (what, token))
        else:
            errors.append("%s — only a human confirms a rule (/hrd social --edit or --persona)" % what)

    if kind == "channel":
        name = os.path.basename(target)[:-3]
        h, err = parse_channel(text)
        if err:
            errors.append(err)
        else:
            gs = guides(root)
            ptext = show(root, "HEAD", PERSONA)
            persona = parse_persona(ptext)[0] if ptext else None
            e, w = channel_problems(h, name, cfg, persona, {k: v[1] for k, v in gs.items()})
            errors += e
            warnings += w
            lang = h.get("lang")
            prev, _ = parse_channel(head) if head is not None else (None, None)
            accepted = isinstance(prev, dict) and primary(prev.get("lang")) == primary(lang)  # decided before
            if isinstance(lang, str) and primary(lang) not in PATTERNS and not accepted:
                tok = "s9:%s" % primary(lang)
                if tok in allow:
                    used.add(tok)
                    floor.append({"token": tok, "what": "no default S9 patterns for %s" % lang})
                else:
                    errors.append("no default S9 patterns for %s — the statistics and service-experience checks would "
                                  "be off; a human accepts that with --allow-floor %s" % (lang, tok))
            if researched_region(text) is None:
                errors.append("the researched region markers (%s … %s) must appear once each" % (RESEARCHED_START, RESEARCHED_END))
            old, _ = parse_channel(head) if head is not None else (None, None)
            if head is not None and old is None:
                warnings.append("the guide on base has an unparsable head block — compared as a new file")
                need("head", "the floor cannot be compared with the broken guide on base")
            if old is None:
                for k, r in _forbidden_map(h.get("forbidden")).items():
                    if r.get("status") == "confirmed":
                        strong("forbidden:%s" % k, "new rule %r starts confirmed" % r.get("pattern"))
                if h.get("disclosure_waiver"):
                    need("disclosure_waiver", "the guide starts with an ad disclosure waiver")
            else:
                _floor_forbidden(old.get("forbidden"), h.get("forbidden"), need, strong)
                _floor_disclosure(old.get("disclosure"), h.get("disclosure"), need)
                if old.get("disclosure_waiver") != h.get("disclosure_waiver") and h.get("disclosure_waiver"):
                    need("disclosure_waiver", "ad disclosure waiver added or changed")
                if mode == "edit":
                    changed = [k for k in RESEARCH_FIELDS if old.get(k) != h.get(k)]
                    if changed:
                        errors.append("research fields change only through --refresh: %s" % ", ".join(changed))
                    if researched_region(head) is not None and researched_region(head) != researched_region(text):
                        errors.append("the researched region changes only through --refresh")
    elif kind == "persona":
        p, err = parse_persona(text)
        if err:
            errors.append(err)
        else:
            e, w = persona_problems(p, cfg)
            errors += e
            warnings += w
            old = parse_persona(head)[0] if head is not None else None
            if head is not None and old is None:
                warnings.append("the persona on base has an unparsable head block — compared as a new file")
                need("head", "the floor cannot be compared with the broken persona on base")
            if old is None:
                for k, r in _forbidden_map(p.get("forbidden")).items():
                    if r.get("status") == "confirmed":
                        strong("forbidden:%s" % k, "new rule %r starts confirmed" % r.get("pattern"))
            else:
                _floor_forbidden(old.get("forbidden"), p.get("forbidden"), need, strong)

                def terms(x):
                    out = {}
                    for t in (x or {}).get("service_terms") or []:
                        if isinstance(t, str):
                            out[fold(t)] = set()
                        elif isinstance(t, dict) and isinstance(t.get("term"), str):
                            out[fold(t["term"])] = {fold(e) for e in t.get("exclude") or [] if isinstance(e, str)}
                    return out

                ot, nt = terms(old), terms(p)
                for t in ot:
                    if t not in nt:
                        need("service_terms", "service term %r removed" % t)
                for t, ex in nt.items():
                    if ex - ot.get(t, set()):
                        need("exclude:%s" % t, "exclusions added for %r: %s" % (t, ", ".join(sorted(ex - ot.get(t, set())))))
    else:  # persona-notes: themes and source kinds only (S5)
        for _, _, u in find_urls(text):
            if "/" in re.sub(r"^https?://", "", u, flags=re.I).rstrip("/"):
                errors.append("a URL with a path (%s) — keep the source kind or domain only (S5)" % u[:60])
        for m in HANDLE_RE.finditer(text):
            errors.append("an account handle (%s) — no handles in persona-notes.md (S5)" % m.group(0))
    unused = sorted((allow | strengthen_ok) - used)
    if unused:
        warnings.append("tokens not needed: %s" % ", ".join(unused))
    trailers = ["Herald-Floor: %s" % f["token"] for f in floor] + ["Herald-Strengthen: %s" % s["token"] for s in strong_list]
    return {"ok": not errors, "target": target, "mode": mode, "errors": errors, "warnings": warnings,
            "floor": floor, "strengthen": strong_list, "trailers": trailers}
