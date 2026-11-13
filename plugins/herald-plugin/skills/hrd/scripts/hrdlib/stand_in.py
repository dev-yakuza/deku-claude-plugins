"""Stand-in and decorative pictures (design/herald/12-generated-fallback-and-decorative.md, 0.21.0).

A real place or thing the brief planned as an external image (`external (place)` / `external
(thing)`) may, when no photo can be used, be drawn as a generic scene that is *not* that place —
a stand-in, labelled "not the actual place" next to the picture. A decorative picture (opt-in,
`images.scenes.decorative`) sits between sections only. Works, people, logos and text are never
drawn instead (decision 2); an unmarked `external` line (a 0.20.0 brief) gets no stand-in (P28).

Every decision is tied to a brief line (`place_key` — §R1-0), never to an IC number or an id:
brief.md and the research candidates are read only while they hash to what their stage pass
recorded (§R2-M1 rule 2, fail-closed), and brief/research re-passes are refused (§R3-M1). The
records here (`image_rejects` with `place`, `stand_in_refused`, `candidate_skips`, …) live in
state.json, which the guard does not protect: against an agent that deliberately breaks its
instructions they are a tripwire, as 0.20.0's `image_rejects` was (§R4-m5, risk R10) —
`records_shrank` lets a `--ship` run's ship-pass see a commit that removed one.
"""

import hashlib
import json
import os
import re
import unicodedata

from .util import HeraldError, git, now_iso

SUBJECTS = ("place", "thing", "work", "person", "quotation")
STAND_IN_SUBJECTS = ("place", "thing")
KINDS = ("external", "scene", "diagram", "screenshot", "decorative")
WHYS = ("no-candidates", "used-up", "human-chose")
SPENT_AT = 3  # a stand-in place turned down three times (redo or reject) is left out (§2.10)
NAMES_MAX = 5
NAME_MAX = 60
DECORATIVE_MAX = 3
STAND_IN_LABELS = {
    "ko": {"place": "AI 생성 이미지(실제 장소 아님)", "thing": "AI 생성 이미지(실물 아님)"},
    "ja": {"place": "AI生成画像（実在の場所ではありません）", "thing": "AI生成画像（実物ではありません）"},
    "en": {"place": "AI-generated image (not the actual place)", "thing": "AI-generated image (not the actual object)"},
}
# a figure template that hides its label from readers (§2.8) — cheap and mechanical
# the opening tag that holds `{label}`: a hiding class, style or attribute (`overflow: hidden` and an
# icon's `aria-hidden` elsewhere in the template are not the label — review 26 m2)
HIDE_CLASS_RE = re.compile(r"""\bclass\s*=\s*["']?[^"'>]*\b(?:hidden|sr-only|visually-hidden)(?![\w-])""", re.I)
HIDE_STYLE_RE = re.compile(r"(?:display\s*:\s*none|visibility\s*:\s*hidden)", re.I)
HIDE_ATTR_RE = re.compile(r"""(?:^|\s)(?:hidden|aria-hidden\s*=\s*["']?true)(?=["'\s>/=]|$)""", re.I)
# R1-m1 + R3-M2: tokens that name no particular place
COMMON = {"temple", "shrine", "castle", "park", "station", "street", "dera", "jinja", "jingu", "ji", "tower",
          "bridge", "garden", "market", "japan", "japanese", "nihon", "tokyo", "kyoto", "osaka", "hokkaido",
          "okinawa", "kanto", "kansai", "asia", "asian", "spring", "summer", "autumn", "fall", "winter",
          "morning", "evening", "night"}
LINE_RE = re.compile(r"^[ \t]*[-*][ \t]+(.+?)[ \t]*$")
KIND_RE = re.compile(r"^kind:[ \t]*([a-z]+)(?:[ \t]*\([ \t]*([a-z]+)[ \t]*\))?[ \t]*$", re.I)
IC_RE = re.compile(r"(?m)^###[ \t]+(IC[0-9]+)[ \t]+—[ \t]+(.*?)[ \t]*$")
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
HEAD_RE = re.compile(r"^(#{1,6})[ \t]+\S")


# --- config (§2.2, §R1-M4, §R1-M6) ---------------------------------------------------------------

def _scenes(cfg):
    from .images import block
    c = (block(cfg) or {}).get("scenes")
    return c if isinstance(c, dict) else None


def _words(cfg):
    from .images import words
    return words(cfg)


def _int(v, lo, hi):
    return isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


def label(cfg, subject):
    """The stand-in's `{label}`: `words.scene_place` / `scene_thing`, else the language default."""
    from .images import lang_tag
    w = _words(cfg).get("scene_" + subject)
    if isinstance(w, str) and w.strip():
        return w
    return (STAND_IN_LABELS.get(lang_tag(cfg)) or {}).get(subject)


def template(cfg):
    """`figure.stand_in` (m11 — a site may give stand-ins their own class), else `figure.scene`."""
    from .images import figure, scene_template
    t = figure(cfg).get("stand_in")
    return t if isinstance(t, str) and t.strip() else scene_template(cfg)


VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


def hidden_label(t):
    """`{label}` readers never see: inside an HTML comment or a tag (an attribute value — `alt`,
    `title`), or in an element whose opening tag hides it (review 26 m2, m3)."""
    if not isinstance(t, str) or "{label}" not in t:
        return False
    before = t[:t.index("{label}")]
    if before.rfind("<!--") > before.rfind("-->"):
        return True
    if before.rfind("<") > before.rfind(">"):
        return True
    depth, holders = 0, []
    for m in reversed(list(re.finditer(r"<(/?)([A-Za-z][\w-]*)([^<>]*)>", before))):
        if m.group(1):
            depth += 1
        elif m.group(3).rstrip().endswith("/") or m.group(2).lower() in VOID_TAGS:
            continue  # self-closing or void (`<img aria-hidden="true">`): wraps nothing
        elif depth:
            depth -= 1
        else:
            holders.append(m.group(3))  # an element still open around the label
    return any(HIDE_CLASS_RE.search(a) or HIDE_STYLE_RE.search(a) or HIDE_ATTR_RE.search(a) for a in holders)


def stand_in_errors(cfg):
    """`stand_in`, `stand_in_per_category`, the stand-in labels and `figure.stand_in` (§R1-M4):
    each turns stand-ins off only — never the scenes."""
    from .images import SCENE_FIELDS, VALUE_BAD, figure, managed, scene_label
    c = _scenes(cfg)
    if not managed(cfg) or c is None:
        return []
    out = []
    if "stand_in" in c and not isinstance(c["stand_in"], bool):
        out.append("images.scenes.stand_in is true or false")
    per = c.get("stand_in_per_category", {})
    if not isinstance(per, dict) or not all(isinstance(k, str) and isinstance(v, bool) for k, v in per.items()):
        out.append("images.scenes.stand_in_per_category maps a category to true or false")
    for s in STAND_IN_SUBJECTS:
        v = _words(cfg).get("scene_" + s)
        if v is None:
            continue
        if not isinstance(v, str) or not v.strip() or len(v) > 60 or VALUE_BAD.search(v):
            out.append("images.figure.words.scene_%s is the stand-in label: 1–60 characters, no < > \" [ ] \\ or "
                       "line break" % s)
        elif v == scene_label(cfg):
            out.append("images.figure.words.scene_%s must say more than words.scene (\"not the actual %s\")"
                       % (s, "place" if s == "place" else "object"))
    t = figure(cfg).get("stand_in")
    if t is not None:
        holes = set(re.findall(r"\{([^{}]*)\}", t)) if isinstance(t, str) else set()
        if not isinstance(t, str) or not t.strip() or holes != set(SCENE_FIELDS):
            out.append("images.figure.stand_in holds exactly {ref}, {alt} and {label}")
        elif hidden_label(t):
            out.append("images.figure.stand_in hides its label (hidden, sr-only, display:none) — the label is always "
                       "seen")
    return out


def decorative_errors(cfg):
    from .images import managed
    c = _scenes(cfg)
    if not managed(cfg) or c is None:
        return []
    out = []
    if not _int(c.get("decorative", 0), 0, DECORATIVE_MAX):
        out.append("images.scenes.decorative must be an integer from 0 to %d" % DECORATIVE_MAX)
    per = c.get("decorative_per_category", {})
    if not isinstance(per, dict) or not all(isinstance(k, str) and _int(v, 0, DECORATIVE_MAX) for k, v in per.items()):
        out.append("images.scenes.decorative_per_category maps a category to an integer from 0 to %d" % DECORATIVE_MAX)
    return out


def _quotation_categories(root):
    from .images import _rules
    try:
        return list(_rules(root)["images"]["external"].get("quotation_categories") or [])
    except Exception:  # noqa: BLE001 — unreadable rules: the gate reports them
        return []


def stand_in_off(root, cfg, cat):
    """Why stand-ins are off by config (None: on) — scenes and external images on by config,
    `stand_in` not false, the category switch, a label (§2.3, §R1-M6). Never this machine."""
    from .images import external_off, lang_tag, scene_off
    w = scene_off(root, cfg, cat)
    if w:
        return "scene:%s" % w
    w = external_off(root, cfg, cat)
    if w:
        return "external:%s" % w
    if stand_in_errors(cfg):
        return "config"
    c = _scenes(cfg) or {}
    if c.get("stand_in") is False:
        return "off"
    per = c.get("stand_in_per_category") or {}
    if cat in per:
        if per[cat] is not True:
            return "category"
    elif cat is not None and cat in _quotation_categories(root):
        return "category:works"  # a category that quotes works: off unless named true (§R1-M6)
    if not all(label(cfg, s) for s in STAND_IN_SUBJECTS):
        return "label:%s" % lang_tag(cfg)
    return None


def decorative_max(cfg, cat):
    """(max, why) — `decorative_per_category[cat]` or `decorative`; errors → 0."""
    c = _scenes(cfg)
    if c is None:
        return 0, "no-config"
    if decorative_errors(cfg):
        return 0, "config"
    per = c.get("decorative_per_category") or {}
    mx = per.get(cat, c.get("decorative", 0)) if cat is not None else c.get("decorative", 0)
    return (mx, None) if mx > 0 else (0, "category" if cat in per else "no-config")


def kinds_parts(root, cfg, cat, scene_ok, scene_why, ext_ok, ext_why):
    """`kinds.scene.stand_in`, `kinds.scene.decorative` and `kinds.external.decorative` (§2.3)."""
    if not scene_ok:
        why = "scene:%s" % scene_why
    elif not ext_ok:
        why = "external:%s" % ext_why
    else:
        why = stand_in_off(root, cfg, cat)
    labels = {s: label(cfg, s) for s in STAND_IN_SUBJECTS}
    mx, dwhy = decorative_max(cfg, cat)
    return ({"ok": why is None, "why": why, "labels": labels if why is None else None},
            {"max": mx if scene_ok else 0, "why": dwhy if scene_ok else "scene:%s" % scene_why},
            bool(ext_ok and mx > 0))


# --- the brief's places (§R1-0, §R2-m6) -------------------------------------------------------------

def _norm(s):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", s or "")).strip()


def parse_brief(text):
    """[{place, line, what, kind, subject, decorative, scene_first}] — only `- … — kind: <k> — …`
    lines; the same line twice gets two keys (its position among equal lines is in the hash)."""
    out, seen = [], {}
    text = (text or "").replace("\r\n", "\n")
    m = re.search(r"(?m)^##[ \t]+Images[ \t]*$", text)  # the `## Images` section only (review 26 m6)
    if not m:
        return out
    nxt = re.search(r"(?m)^##?[ \t]+(?!#)", text[m.end():])
    text = text[m.end():m.end() + nxt.start()] if nxt else text[m.end():]
    for raw in text.split("\n"):
        m = LINE_RE.match(raw)
        if not m or " — " not in m.group(1):
            continue
        parts = [p.strip() for p in m.group(1).split(" — ")]
        km = next((KIND_RE.match(p) for p in parts[1:] if KIND_RE.match(p)), None)
        if not km:
            continue
        kind, sub = km.group(1).lower(), (km.group(2) or "").lower() or None
        if kind not in KINDS:
            continue
        line = _norm(raw)
        n = seen.get(line, 0)
        seen[line] = n + 1
        key = hashlib.sha256(("%s\n%d" % (line, n)).encode("utf-8")).hexdigest()[:12]
        subject = sub if kind == "external" and sub in SUBJECTS else None
        out.append({"place": key, "line": line, "what": parts[0], "kind": kind, "subject": subject,
                    "decorative": kind == "decorative", "scene_first": kind == "decorative" and sub == "scene"})
    return out


def marked(places):
    """A 0.21 brief: some line carries a subject or is decorative (§R1-0) — every external and
    scene item then names its place."""
    return any(p["subject"] or p["decorative"] for p in places or [])


def inherited(st, stage):
    """§R3-m6 + §R4-m4: a tr- topic whose stage ran in its reference topic — no hash gate."""
    return bool(((st.get("stages") or {}).get(stage) or {}).get("inherited")) and \
        str(st.get("topic_id", "")).startswith("tr-")


def _gate(root, tid, st, stage, name):
    """The work file's text when it hashes to what its stage pass recorded (or the stage is
    inherited), else None — every stand-in and role decision is fail-closed then (§R2-M1 rule 2)."""
    from .images import _read, _work_rel
    from .hashing import file_hash
    rel = _work_rel(tid, name)
    if inherited(st, stage):
        return _read(root, rel) or ""
    rec = (((st.get("stages") or {}).get(stage) or {}).get("outputs") or {}).get(name)
    if not rec or file_hash(root, rel) != rec:
        return None
    return _read(root, rel) or ""


def places(root, tid, st):
    """The brief's places, or None when brief.md is not the brief that passed."""
    text = _gate(root, tid, st, "brief", "brief.md")
    return None if text is None else parse_brief(text)


def places_cmd(root, cfg, tid):
    """`HRD image places`."""
    from .store import load_state
    st = load_state(root, tid)
    pl = places(root, tid, st)
    if pl is None:
        raise HeraldError("brief changed since it passed — no stand-in or role decision until it is the passed brief "
                          "again (`git checkout -- %s`)" % ".claude/herald/work/%s/brief.md" % tid)
    return {"places": [{k: p[k] for k in ("place", "line", "kind", "subject", "decorative", "scene_first")} for p in pl],
            "marked": marked(pl)}


# --- research candidates (§2.5, §R2-M4, §R3-m2, §R4-m3) -------------------------------------------

def candidates_section(text):
    m = re.search(r"(?m)^##[ \t]+Image candidates[ \t]*$", text or "")
    if not m:
        return ""
    nxt = re.search(r"(?m)^##[ \t]+(?!#)", text[m.end():])
    return text[m.end():m.end() + nxt.start()] if nxt else text[m.end():]


def candidates_hash(research_text):
    """The `## Image candidates` section's hash over its non-empty lines, each stripped and NFC —
    a rewrite that only moves whitespace keeps it (§R4-m3)."""
    lines = [unicodedata.normalize("NFC", x.strip()) for x in candidates_section(research_text).split("\n") if x.strip()]
    return "sha256:" + hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def parse_candidates(section):
    """{IC1: {head, place, decorative, images, pages, licenses, titles, none, searched}}."""
    out = {}
    heads = list(IC_RE.finditer(section or ""))
    for i, m in enumerate(heads):
        body = section[m.end():heads[i + 1].start() if i + 1 < len(heads) else len(section)]
        parts = [p.strip() for p in m.group(2).split(" — ")]
        place = next((p.split(":", 1)[1].strip() for p in parts if re.match(r"^place:", p)), None)
        rec = {"head": parts[0], "place": place, "decorative": "decorative" in parts[1:], "images": [], "pages": [],
               "licenses": {}, "titles": [], "none": None, "searched": []}
        cur = None
        for line in body.split("\n"):
            lm = re.match(r"^[ \t]*[-*][ \t]*(image|page|license|title|none)[ \t]*:[ \t]*(.*?)[ \t]*$", line)
            if not lm:
                continue
            k, v = lm.group(1), lm.group(2)
            if k == "image":
                cur = v
                rec["images"].append(v)
            elif k == "page":
                rec["pages"].append(v)
            elif k == "license" and cur:
                rec["licenses"][cur] = v
            elif k == "title":
                rec["titles"].append(v)
            elif k == "none":
                # `- none: <why> — searched: <https URL>[, …]` (§R2-M4 rule 3)
                why, _, s = v.partition("— searched:")
                rec["none"] = why.strip() or v
                rec["searched"] = [u.strip() for u in s.split(",") if re.match(r"^https://\S+$", u.strip())]
        out[m.group(1)] = rec
    return out


def candidate_blocks(root, tid, st):
    """The candidate blocks of research.md as it passed, or None (fail-closed)."""
    text = _gate(root, tid, st, "research", "research.md")
    return None if text is None else parse_candidates(candidates_section(text))


def block_of(blocks, place):
    return next((b for b in (blocks or {}).values() if b.get("place") == place), None)


# --- names (§2.6 5, §R1-m1, §R3-M2, §R4-m1) --------------------------------------------------------

def norm_name(s):
    s = unicodedata.normalize("NFKC", s or "").casefold()
    return re.sub(r"[\s\-・·]+", "", s)


def _tokens(text, capital=False, keep_first=False):
    """Latin tokens of 4+ letters not in COMMON; `capital`: only those starting upper case, and
    not a sentence's first word unless `keep_first`."""
    out = []
    for i, sent in enumerate(re.split(r"(?<=[.!?。！？])\s+", text or "")):
        for j, m in enumerate(re.finditer(r"[A-Za-z]+", sent)):
            w = m.group(0)
            if len(w) < 4 or w.casefold() in COMMON:
                continue
            if capital and (not w[0].isupper() or (j == 0 and not (keep_first and i == 0))):
                continue
            out.append(w.casefold())
    return out


def _file_tokens(url):
    """Capitalised tokens of a URL's file name (Commons `File:Kiyomizu-dera_main_hall.jpg`)."""
    import urllib.parse
    try:
        last = urllib.parse.unquote(urllib.parse.urlsplit(url or "").path.rsplit("/", 1)[-1])
    except ValueError:
        return []
    last = re.sub(r"^File:", "", last)
    last = re.sub(r"\.[A-Za-z0-9]{2,5}$", "", last)
    last = re.sub(r"^[0-9]+px-", "", last)
    return _tokens(re.sub(r"[_\-]+", " ", last), capital=True, keep_first=True)


def name_problems(names, tokens, text):
    """Which names or tokens `text` carries (normalised substrings of 2+ characters; tokens whole)."""
    hits = []
    nt = norm_name(text)
    for n in names or []:
        k = norm_name(n)
        if len(k) >= 2 and k in nt:
            hits.append(n)
    low = (text or "").casefold()
    for t in tokens or []:
        if re.search(r"(?<![a-z])%s(?![a-z])" % re.escape(t), low):
            hits.append(t)
    return list(dict.fromkeys(hits))


def name_tokens(names):
    out = []
    for n in names or []:
        out += _tokens(n)
    return out


def blocked_pool(st, pl, blocks):
    """(names, tokens) every scene of the topic is checked against (§R2-M2 rule 1 as §R3-M2,
    §R4-m1): the names of every stand-in the topic recorded, and of each blocked place the
    capitalised Latin tokens of its brief `<what>`, its IC head and the file names of its
    original external URLs. Titles are never in it (reviewers read them)."""
    names = []
    for ns in (st.get("stand_in_names") or {}).values():
        names += [n for n in ns or [] if isinstance(n, str)]
    tokens = name_tokens(names)
    by = {p["place"]: p for p in pl or []}
    for p in sorted(blocked_places(st, pl, blocks)):
        line = by.get(p)
        if line:
            tokens += _tokens(line["what"], capital=True, keep_first=True)
        b = block_of(blocks, p)
        if b:
            tokens += _tokens(b["head"], capital=True)
            for u in b["images"] + b["pages"]:
                tokens += _file_tokens(u)
        for r in st.get("image_rejects") or []:
            if isinstance(r, dict) and r.get("place") == p and r.get("source_url"):
                tokens += _file_tokens(r["source_url"])
    return list(dict.fromkeys(names)), list(dict.fromkeys(tokens))


# --- records (§R1-B1, §R1-M3, §R1-M7, §R2-M3, §R3-m4) ----------------------------------------------

def _recs(st, key):
    return [r for r in st.get(key) or [] if isinstance(r, dict)]


def allowed(st, place):
    return any(r.get("place") == place for r in _recs(st, "stand_in_allowed"))


def human_drops(st, place, urls=()):
    """A human's "go without" for this place — `reject --drop` without `--stand-in`, a human
    loopback or a human push (§R1-M3) — matched by place or by one of its candidate URLs."""
    return [r for r in _recs(st, "image_rejects") if r.get("drop") and not r.get("by") and not r.get("stand_in")
            and (r.get("place") == place or (r.get("source_url") and r["source_url"] in urls))]


def refusals(st, place):
    return [r for r in _recs(st, "stand_in_refused") if r.get("place") == place]


def stand_in_attempts(st, place):
    """1 + the decisions that turned a stand-in of this place down — by place, never id (§2.10)."""
    keys = {r.get("key") for r in _recs(st, "review_rejects") if r.get("place") == place
            and str(r.get("role") or "").startswith("stand-in")}
    keys |= {r.get("job") for r in _recs(st, "image_rejects") if r.get("place") == place and r.get("job")
             and str(r.get("role") or "").startswith("stand-in")}
    return 1 + len({k for k in keys if k})


def spent(st, place):
    """Three stand-ins of this place turned down, or one dropped (by anyone) — no stand-in again."""
    if stand_in_attempts(st, place) > SPENT_AT:
        return True
    return any(r.get("drop") and r.get("place") == place and str(r.get("role") or "").startswith("stand-in")
               for r in _recs(st, "image_rejects"))


def topic_off(st):
    """Stand-ins off for the whole topic: a 0.20.0 human drop without a place (§R1-0 fail-safe),
    or a brief re-pass that orphaned a human's record (§R2-M1)."""
    if st.get("stand_in_orphaned"):
        return "orphaned"
    if any(r.get("drop") and not r.get("by") and "place" not in r for r in _recs(st, "image_rejects")):
        return "unplaced-drop"
    return None


def subject_checked(st, place):
    return next((r for r in reversed(_recs(st, "subject_checks")) if r.get("place") == place), None)


def record_block(st, place, urls=(), subject=True):
    """The record-based reason a stand-in of `place` may not go on (None: none) — every point:
    plan, generate, review, confirm, draft/verify/scope and `unvouched` (§R2-m7 as §R3-m5)."""
    w = topic_off(st)
    if w:
        return "topic-off:%s" % w
    rs = refusals(st, place)
    if any(r.get("by") == "human" for r in rs) or (rs and not allowed(st, place)):
        return "refused"
    if human_drops(st, place, urls) and not allowed(st, place):
        return "human-drop"
    if spent(st, place):
        return "spent"
    if subject and not subject_checked(st, place):
        return "subject-check"
    return None


def _skips(st, place, during_loopback=True):
    return {r.get("url") for r in _recs(st, "candidate_skips") if r.get("place") == place
            and (during_loopback or not r.get("human_loopback"))}


def used_up(st, b, licenses, during_loopback=True):
    """Every candidate URL of the block failed on content, was rejected, skipped after a look, or
    carries a license this repo does not allow (§R1-M7). `during_loopback=False` leaves out the
    skips made during a human loopback (§R3-m4)."""
    if not b or not b["images"]:
        return False
    gone = {r.get("source_url") for r in _recs(st, "fetch_failures")} - set(st.get("fetch_ok") or [])
    gone |= {r.get("source_url") for r in _recs(st, "image_rejects") if r.get("source_url")}
    gone |= _skips(st, b.get("place"), during_loopback)
    for u in b["images"]:
        lic = b["licenses"].get(u)
        if u in gone or (lic is not None and lic not in licenses):
            continue
        return False
    return True


def why(st, place, b, licenses):
    """What makes a stand-in allowed here — computed, never taken from the manifest (§R1-M7)."""
    if allowed(st, place) or any(r.get("place") == place and r.get("drop") and r.get("stand_in")
                                 for r in _recs(st, "image_rejects")):
        return "human-chose"
    if b and not b["images"] and b["none"] and b["searched"]:
        return "no-candidates"
    if used_up(st, b, licenses):
        return "used-up"
    return None


def blocked_places(st, pl, blocks):
    """Places a stand-in can no longer fill (human drop, refusal, spent)."""
    out = set()
    for p in pl or []:
        b = block_of(blocks, p["place"])
        urls = tuple((b or {}).get("images") or ())
        if (human_drops(st, p["place"], urls) and not allowed(st, p["place"])) or refusals(st, p["place"]) or \
                spent(st, p["place"]):
            out.add(p["place"])
    for r in _recs(st, "stand_in_refused"):
        if r.get("borrowed"):
            out.add(r["borrowed"])
    return out


def borrowed(st, it):
    """A review found this scene redraws a blocked place (`--problem subject --place`)."""
    return any(r.get("origin") == "borrowed" and r.get("place") == it.get("place") and r.get("place")
               for r in _recs(st, "stand_in_refused"))


def marks(st):
    """What was ever a stand-in in this topic — its picture (role-less key) and file stay one."""
    return _recs(st, "stand_in_marks")


# --- roles (§R1-M1) -------------------------------------------------------------------------------

def role_of(it, line):
    """The role the brief line gives this item, or None when the kind does not fit the line."""
    kind = it.get("kind")
    if not line:
        return kind
    k = line["kind"]
    if kind == "scene":
        if k == "external" and line["subject"] in STAND_IN_SUBJECTS:
            return "stand-in:%s" % line["subject"]
        return {"decorative": "decorative", "scene": "scene"}.get(k)
    if kind == "external":
        if k == "external":
            return "external"
        if k == "decorative" and not line["scene_first"]:
            return "decorative"
    return None


def is_stand_in(role):
    return str(role or "").startswith("stand-in:")


def item_role(it):
    """The role an item shows (its display copies — plan holds them to the brief)."""
    if it.get("kind") == "scene" and isinstance(it.get("stand_in"), dict):
        s = it["stand_in"].get("subject")
        return "stand-in:%s" % s if s in STAND_IN_SUBJECTS else "stand-in:place"
    if it.get("decorative") is True:
        return "decorative"
    return it.get("kind")


# --- body positions (§2.9, §R1-M5, §R1-m7) ---------------------------------------------------------

def _lines(body):
    """[(line, outside a fence)] after the frontmatter, with the line offset of the first."""
    ls = body.replace("\r\n", "\n").split("\n")
    start = 0
    if ls and ls[0].strip() == "---":
        for i in range(1, len(ls)):
            if ls[i].strip() == "---":
                start = i + 1
                break
    out, fence = [], None
    for i in range(start, len(ls)):
        raw = ls[i]
        fm = FENCE_RE.match(raw)
        if fence:
            out.append((i, raw, False))
            if fm and fm.group(1)[0] == fence[0] and len(fm.group(1)) >= len(fence):
                fence = None
            continue
        if fm:
            fence = fm.group(1)
            out.append((i, raw, False))
            continue
        out.append((i, raw, True))
    return out


def position_problems(root, cfg, tid, slug, items, body):
    """§2.9 and §R1-M5 on the working tree: a decorative picture sits between sections only
    (after a section heading of the shallowest level L, right before the next one, not stacked on
    another picture, one per boundary); a stand-in or decorative picture is never before the first
    section heading nor the article's first image."""
    from .images import snippet_text
    from .validate import image_refs
    out = []
    special = [it for it in items if item_role(it) == "decorative" or is_stand_in(item_role(it))]
    if not special:
        return out
    text = body.replace("\r\n", "\n")
    ls = _lines(text)
    heads = [(i, len(HEAD_RE.match(raw).group(1))) for i, raw, ok in ls if ok and HEAD_RE.match(raw)
             and len(HEAD_RE.match(raw).group(1)) >= 2]
    if not heads:
        return ["%s: decorative/stand-in pictures need Markdown section headings (##)" % it.get("id") for it in special]
    L = min(n for _, n in heads)
    lvl = {i: n for i, n in heads}
    first_head = min(i for i, n in heads if n == L)
    starts = {}  # line of each managed snippet's start/end
    for it in items:  # an external item's snippet depends on its orientation: try each one
        for ori in ((None,) if it.get("kind") == "scene" else (None, "landscape", "portrait", "square")):
            try:
                sn = snippet_text(cfg, it, ori, root, slug) if it.get("kind") in ("scene", "external") else None
            except Exception:  # noqa: BLE001
                sn = None
            if sn and sn in text:
                a = text.index(sn)
                starts[it.get("id")] = (text.count("\n", 0, a), text.count("\n", 0, a + len(sn)))
                break
    for it in items:  # no snippet found as written: fall back to its reference line
        if it.get("id") not in starts and it.get("ref") and it.get("ref") in text:
            a = text.index(it["ref"])
            n = text.count("\n", 0, a)
            starts[it["id"]] = (n, n)
    refs = image_refs(root, cfg.body_path(slug), text)
    og = cfg.og_path(slug) if cfg.og_path(slug) else None
    local = [r for r in refs if r != og]
    lines = text.split("\n")
    ends = {e for s, e in starts.values()}
    boundaries = {}
    for it in special:
        iid, role = it.get("id"), item_role(it)
        if iid not in starts:
            continue  # the snippet check reports a missing picture
        s, e = starts[iid]
        if s < first_head:
            out.append("%s: a %s picture never comes before the first section heading" % (
                iid, "decorative" if role == "decorative" else "stand-in"))
        elif local and local[0] == it.get("file"):
            out.append("%s: a %s picture is never the article's first image (the site and search previews use it)" % (
                iid, "decorative" if role == "decorative" else "stand-in"))
        if role != "decorative":
            continue
        after = next((j for j in range(e + 1, len(lines)) if lines[j].strip()), None)
        before = next((j for j in range(s - 1, -1, -1) if lines[j].strip()), None)
        if after is None or lvl.get(after) != L:
            out.append("%s: a decorative picture goes right before a section heading (%s) — between sections, never "
                       "after the last one" % (iid, "#" * L))
        elif after in boundaries:
            out.append("%s: one decorative picture per section boundary (%s is there already)" % (iid, boundaries[after]))
        else:
            boundaries[after] = iid
        if before is not None and before in ends - {e}:
            out.append("%s: a decorative picture is not stacked on another picture" % iid)
    return out


# --- the plan's checks (§2.6, §R1, §R2, §R3) -------------------------------------------------------

def _licenses(root, cfg, cat):
    from .images import external_limits
    try:
        return external_limits(root, cfg, cat)["licenses"]
    except Exception:  # noqa: BLE001
        return []


def manifest_errors(root, cfg, tid, st, items, text, cat):
    """(errors, roles {id: role}) — the rules of 0.21.0 a plan adds to 0.20.0's."""
    from .images import check_value, scene_off
    errors, roles = [], {}
    pl = places(root, tid, st)
    blocks = candidate_blocks(root, tid, st)
    uses_place = [it for it in items if it.get("place") is not None or "stand_in" in it or it.get("decorative")]
    if pl is None:
        if uses_place:
            errors.append("brief changed since it passed — no stand-in or picture role until it is the passed brief "
                          "again")
        return errors, {it.get("id"): it.get("kind") for it in items}
    by = {p["place"]: p for p in pl}
    v21 = marked(pl)
    if blocks is not None:
        for ic, b in sorted(blocks.items()):
            if b["place"] is not None and b["place"] not in by:
                errors.append("research.md %s names place %s, which brief.md does not have" % (ic, b["place"]))
    used = {}
    lic = _licenses(root, cfg, cat)
    dmax, _ = decorative_max(cfg, cat)
    n_dec = 0
    pool = None
    for it in items:
        iid, kind = it.get("id"), it.get("kind")
        if kind not in ("external", "scene"):
            continue
        p = it.get("place")
        if p is None:
            if v21:
                errors.append("%s: place is required — copy its brief line's key from `HRD image places --topic %s`"
                              % (iid, tid))
            elif "stand_in" in it or it.get("decorative"):
                errors.append("%s: a stand-in or decorative picture needs its place (a 0.21 brief line)" % iid)
            roles[iid] = kind
            continue
        line = by.get(p)
        if not line:
            errors.append("%s: place %r is no line of brief.md (`HRD image places --topic %s`)" % (iid, p, tid))
            roles[iid] = kind
            continue
        if p in used:
            errors.append("%s: place %s already has %s — one picture per place (a stand-in never sits beside its "
                          "photo)" % (iid, p, used[p]))
        used[p] = iid
        role = role_of(it, line)
        roles[iid] = role or kind
        if role is None:
            errors.append("%s: a %s cannot fill the brief line %r" % (iid, kind, line["line"][:80]))
            continue
        b = block_of(blocks, p)
        urls = tuple((b or {}).get("images") or ())
        si = it.get("stand_in")
        if is_stand_in(role):
            subj = role.split(":", 1)[1]
            if not isinstance(si, dict) or si.get("subject") != subj:
                errors.append("%s: a scene on an `external (%s)` line is a stand-in — stand_in.subject must be %s"
                              % (iid, subj, subj))
                continue
            w = stand_in_off(root, cfg, cat)
            if w:
                errors.append("%s: stand-ins are off here (%s) — leave that place out" % (iid, w))
            w = record_block(st, p, urls, subject=False)
            if w:
                errors.append("%s: no stand-in for this place (%s) — leave it out" % (iid, _say(w)))
            if blocks is None:
                errors.append("%s: research.md changed since it passed — no stand-in" % iid)
            else:
                w = why(st, p, b, lic)
                if w is None:
                    errors.append("%s: no stand-in yet — the place still has a usable candidate (fetch it, or `HRD "
                                  "image skip` one you looked at)" % iid)
                elif si.get("why") != w:
                    errors.append("%s: stand_in.why is %r — the records say %r" % (iid, si.get("why"), w))
            names = si.get("names")
            if not isinstance(names, list) or not 1 <= len(names) <= NAMES_MAX or not all(
                    check_value(n) and len(n) <= NAME_MAX for n in names):
                errors.append("%s: stand_in.names lists the place's own names, 1–%d of 1–%d characters" % (
                    iid, NAMES_MAX, NAME_MAX))
                names = []
            hits = name_problems(names, name_tokens(names), "%s\n%s" % (it.get("alt") or "", it.get("prompt") or ""))
            if hits:
                errors.append("%s: alt or prompt names the real place (%s) — a stand-in is a generic picture, not that "
                              "place" % (iid, ", ".join(hits[:3])))
            if it.get("decorative"):
                errors.append("%s: decorative is false for a stand-in" % iid)
        else:
            if si is not None:
                errors.append("%s: stand_in is only for a scene on an `external (place|thing)` line" % iid)
            if bool(it.get("decorative")) != (role == "decorative"):
                errors.append("%s: decorative must be %s — the brief line says so" % (
                    iid, "true" if role == "decorative" else "false"))
        if role == "decorative":
            n_dec += 1
            if kind == "external" and it.get("use") != "licensed":
                errors.append("%s: a decorative external image is licensed — never a quotation" % iid)
            if kind == "scene" and scene_off(root, cfg, cat):
                errors.append("%s: scene images are off here — no decorative scene" % iid)
        if kind == "external":
            if it.get("use") == "quotation" and line["kind"] == "external" and line["subject"] not in (None, "quotation"):
                errors.append("%s: a quotation fills an `external (quotation)` line only" % iid)
            if line["kind"] == "external" and line["subject"] == "quotation" and it.get("use") != "quotation":
                errors.append("%s: an `external (quotation)` line is a quotation" % iid)
            if any(r.get("origin") == "stand-in" for r in refusals(st, p)):
                errors.append("%s: this place is not a place or thing (a review said so) — left out" % iid)
        if kind == "scene":
            if any(r.get("borrowed") and r.get("place") == p for r in _recs(st, "stand_in_refused")):
                errors.append("%s: a review found this scene redraws a blocked place — left out" % iid)
            if not is_stand_in(role):  # a stand-in's picture never loses its label on another line (review 26 B1)
                from .images import base_scene_key
                bk = base_scene_key(cfg, it)
                if any(m.get("key") == bk or m.get("file") == it.get("file") for m in marks(st)):
                    errors.append("%s: this picture (or file) was a stand-in — it keeps that role and its label; draw "
                                  "a new picture under a new file name" % iid)
            if pool is None:
                pool = blocked_pool(st, pl, blocks)
            # every scene against the topic's pool (§R2-M2 rule 1); a stand-in's own names were checked above
            own = (si.get("names") or []) if is_stand_in(role) and isinstance(si, dict) else []
            names = [n for n in pool[0] if norm_name(n) not in {norm_name(x) for x in own}]
            toks = [t for t in pool[1] if t not in name_tokens(own)]
            hits = name_problems(names, toks, "%s\n%s" % (it.get("alt") or "", it.get("prompt") or ""))
            if hits:
                errors.append("%s: alt or prompt names a place that is left out or drawn elsewhere (%s)" % (
                    iid, ", ".join(hits[:3])))
    if n_dec > dmax:
        errors.append("%d decorative pictures — this category allows %d (images.scenes.decorative)" % (n_dec, dmax))
    if not v21 and any(p["kind"] for p in pl):
        free = sum(1 for it in items if it.get("kind") == "scene" and it.get("place") is None)
        lines = sum(1 for p in pl if p["kind"] == "scene")
        if free > lines:
            errors.append("%d scenes without a place — brief.md plans %d scene places" % (free, lines))
    return errors, roles


def _say(w):
    return {"refused": "a review or a human found it is not a place or thing", "human-drop": "a human chose to go "
            "without it", "spent": "its stand-ins were turned down", "subject-check": "no subject check yet",
            }.get(w, w)


def observe(st, items, roles, blocks, licenses, update):
    """§R2-M3 + §R3-m4: what each place holds now. During a human loopback (`HRD loopback
    --human`), a place whose item went away — or whose photo became a scene — is a human's
    "go without" unless its candidates were used up or a human chose a stand-in; a stand-in that
    went away is both that and spent. `update` (the plan's normal branch only) keeps the new view."""
    cur = {}
    for it in items:
        p = it.get("place")
        if p and it.get("kind") in ("external", "scene"):
            cur[p] = {"id": it.get("id"), "kind": it.get("kind"), "role": roles.get(it.get("id")) or it.get("kind"),
                      "source_url": it.get("source_url")}
    prev = st.get("places_seen") or {}
    if st.get("human_loopback"):
        for p, was in sorted(prev.items()):
            now = cur.get(p)
            if now and not (was.get("kind") == "external" and now.get("kind") == "scene"):
                continue
            if any(r.get("place") == p and r.get("via") == "human-loopback" for r in _recs(st, "image_rejects")):
                continue
            stand = is_stand_in(was.get("role"))
            b = block_of(blocks, p)
            if not stand and (used_up(st, b, licenses, during_loopback=False) or allowed(st, p) or any(
                    r.get("place") == p and r.get("stand_in") for r in _recs(st, "image_rejects"))):
                continue
            rj = {"id": was.get("id"), "place": p, "source_url": was.get("source_url"), "drop": True,
                  "via": "human-loopback", "reason": "left out in a human loopback", "at": now_iso()}
            if stand:
                rj["role"] = was.get("role")
            st.setdefault("image_rejects", []).append(rj)
    if update:
        st["places_seen"] = cur


def pending_subject(st, items, roles):
    """Stand-in items whose place has no subject check yet (§R1-m2 4-pre)."""
    return [it.get("id") for it in items if is_stand_in(roles.get(it.get("id"))) and
            not subject_checked(st, it.get("place"))]


# --- commands --------------------------------------------------------------------------------------

def stand_in_cmd(root, cfg, tid, place, allow=False, reason=None):
    """`HRD image stand-in --place <k> [--allow --reason]` — read-only without `--allow`."""
    from .images import _category, _human_only, _items, load_manifest, scene_limit
    from .store import load_state, save_state
    st = load_state(root, tid)
    pl = places(root, tid, st)
    if pl is None:
        return {"ok": False, "why": "brief-changed", "next": "brief.md is not the brief that passed"}
    line = next((p for p in pl if p["place"] == place), None)
    if not line:
        raise HeraldError("%s is no place of brief.md — `HRD image places --topic %s`" % (place, tid))
    if allow:
        _human_only("stand-in --allow")
        from . import lock
        if lock.ship_active(root, tid):
            raise HeraldError("--allow is a human's decision — not in a `--ship` run")
        if not isinstance(reason, str) or not reason.strip():
            raise HeraldError("--allow needs --reason (one line)")
        if any(r.get("by") == "human" for r in refusals(st, place)):
            raise HeraldError("a human judged this place a work or person — no stand-in; plan another article if that "
                              "was wrong")
        st.setdefault("stand_in_allowed", []).append({"place": place, "reason": reason[:300], "at": now_iso()})
        save_state(root, tid, st)
    cat = _category(root, cfg, st.get("slug"))
    blocks = candidate_blocks(root, tid, st)
    b = block_of(blocks, place)
    out = {"ok": False, "why": None, "place": place, "subject": line["subject"], "label": None,
           "attempts": stand_in_attempts(st, place), "names_hint": (b or {}).get("head") or line["what"],
           "brief_line": line["line"], "allowed": allowed(st, place), "next": None}
    if line["kind"] != "external" or line["subject"] not in STAND_IN_SUBJECTS:
        out["why"] = "subject:%s" % (line["subject"] or ("missing" if line["kind"] == "external" else line["kind"]))
        return out
    w = stand_in_off(root, cfg, cat)
    if w:
        out["why"] = "off:%s" % w
        return out
    w = record_block(st, place, tuple((b or {}).get("images") or ()), subject=False)
    if w:
        out["why"] = {"refused": "refused"}.get(w, w)
        return out
    if blocks is None:
        out["why"] = "research-changed"
        return out
    try:
        items = _items(load_manifest(root, tid))
    except HeraldError:
        items = []
    n = sum(1 for it in items if it.get("kind") == "scene" and it.get("place") != place)
    if n + 1 > scene_limit(cfg, cat):
        out["why"] = "scene-max"
        return out
    w = why(st, place, b, _licenses(root, cfg, cat))
    if not w:
        out["why"] = "not-yet"
        out["next"] = "a candidate is still usable — fetch it, or `HRD image skip` one you looked at"
        return out
    out.update(ok=True, why=w, label=label(cfg, line["subject"]),
               next="replace the external item with a scene item (place %s, stand_in {subject: %s, names, why: %s}), "
                    "`HRD image snippet`, then `HRD image plan --check`" % (place, line["subject"], w))
    return out


def skip(root, cfg, tid, place, url, reason):
    """`HRD image skip`: the illustrator opened a candidate and it does not fit — only a URL this
    machine fetched for this topic (§R2-M4 rule 1, §R3-m3), never in a `--ship` run (rule 2)."""
    from . import lock
    from .shots import FETCHES, ledger_read
    from .store import load_state, save_state
    if not isinstance(reason, str) or not reason.strip():
        raise HeraldError("--reason says in one line why the candidate does not fit")
    if lock.ship_active(root, tid):
        raise HeraldError("a `--ship` run drops a photo only through the agent review (`review --redo`, then `reject "
                          "--agent`) — never `image skip`")
    st = load_state(root, tid)
    b = block_of(candidate_blocks(root, tid, st), place)
    if not b or url not in b["images"]:
        raise HeraldError("%s is no candidate image of place %s in research.md as it passed" % (url, place))
    lines, _ = ledger_read(os.path.join(root, FETCHES))
    if not any(r.get("topic") == tid and r.get("source_url") == url for r in lines):
        raise HeraldError("%s was not fetched for %s on this machine — fetch it first (only an opened candidate is "
                          "skipped)" % (url, tid))
    st.setdefault("candidate_skips", []).append({"place": place, "url": url, "reason": reason[:300], "at": now_iso(),
                                                 "human_loopback": bool(st.get("human_loopback"))})
    save_state(root, tid, st)
    return {"skipped": url, "place": place}


def removed(root, cfg, tid, rev):
    """`HRD image removed --rev <head>` (ship §5): a human's push that deleted an external or
    stand-in picture, or its reference, is a human's "go without" for that place (§R1-M3)."""
    from .images import _body, _items, _rev_hashes, cur_path, load_manifest
    from .store import load_state, read_json_at, save_state, work_rel
    st = load_state(root, tid)
    head = read_json_at(root, rev, work_rel(tid, "state.json")) or {}
    slug = st.get("slug")
    if not slug:
        return {"recorded": []}
    try:
        man = load_manifest(root, tid, rev)
    except HeraldError:
        man = None
    body = _body(root, cfg, slug, rev)
    seen = head.get("places_seen") or st.get("places_seen") or {}
    by = {it.get("place"): it for it in _items(man) if it.get("place")}
    had = ((head.get("images") or {}).get("items")) or {}
    out = []
    for p, was in sorted(seen.items()):
        it = by.get(p)
        # gone: the entry, its reference, or a file the head's state says was in place
        gone = it is None or not it.get("ref") or it["ref"] not in body or (
            (had.get(it.get("id")) or {}).get("sha") and not _rev_hashes(root, rev, cur_path(root, cfg, slug,
                                                                                               it.get("file"))))
        if not gone or any(r.get("place") == p and r.get("via") == "human-push" for r in _recs(st, "image_rejects")):
            continue
        rj = {"id": was.get("id"), "place": p, "source_url": was.get("source_url"), "drop": True, "via": "human-push",
              "reason": "removed in a human's push", "at": now_iso()}
        if is_stand_in(was.get("role")):
            rj["role"] = was.get("role")
        st.setdefault("image_rejects", []).append(rj)
        out.append(p)
    if out:
        save_state(root, tid, st)
    return {"recorded": out}


def first_notice(root, cfg):
    """`/hrd status` and batch summaries, once per machine (`memory/notices.json`): stand-ins are
    on — a 0.21.0 default (12 §R1-m14)."""
    from .images import managed
    from .util import read_json, write_json
    if not managed(cfg) or _scenes(cfg) is None or (_scenes(cfg) or {}).get("stand_in") is False:
        return None
    w = stand_in_off(root, cfg, None)
    if w and not w.startswith("category"):  # stand-ins are not on in this repo at all (review 26 m9)
        return None
    p = os.path.join(root, ".claude/herald/memory/notices.json")
    try:
        seen = read_json(p) or {}
    except ValueError:
        seen = {}
    if seen.get("stand_in"):
        return None
    per = (_scenes(cfg) or {}).get("stand_in_per_category") or {}
    off = sorted(set(_quotation_categories(root)) - {k for k, v in per.items() if v is True} |
                 {k for k, v in per.items() if v is not True})
    seen["stand_in"] = now_iso()
    write_json(p, seen)
    return "stand-ins on: a real place or thing with no usable photo gets a generic AI scene labelled 'not the " \
           "actual place'%s — `/hrd config images.scenes.stand_in false` turns it off" % (
               " (off in: %s)" % ", ".join(off) if off else "")


# --- §R4-m5: the records only grow -----------------------------------------------------------------

GROWING = ("image_rejects", "review_rejects", "stand_in_refused", "candidate_skips", "fetch_failures",
           "subject_checks", "stand_in_marks", "stand_in_allowed", "fetch_ok")


def _lists(st):
    return {k: st.get(k) if isinstance(st.get(k), list) else [] for k in GROWING}


def _shrank(prev, cur):
    """A list that is not its earlier self plus new entries (a record removed or edited — review
    26 m4), or the topic-wide `stand_in_orphaned` switched back off."""
    if any(cur[0][k][:len(prev[0][k])] != prev[0][k] for k in GROWING):
        return True
    return bool(prev[1]) and not cur[1]


def records_shrank(root, cfg, tid, rev):
    """The commits of base..rev that removed or changed an entry of one of the topic's growing
    record lists, or turned `stand_in_orphaned` off (a `--ship` run's ship-pass blocks on it —
    `stand-in-records-shrank`)."""
    from .store import work_rel
    rel = work_rel(tid, "state.json")
    revs = git(root, "rev-list", "--reverse", "origin/%s..%s" % (cfg.base, rev or "HEAD"), "--", rel,
               check=False).split()
    out, prev = [], None
    base = git(root, "merge-base", "origin/%s" % cfg.base, rev or "HEAD", check=False).strip()
    for c in ([base] if base else []) + revs:
        try:
            st = json.loads(git(root, "show", "%s:%s" % (c, rel), check=False) or "null")
        except ValueError:
            st = None
        if not isinstance(st, dict):
            continue
        cur = (_lists(st), st.get("stand_in_orphaned"))
        if prev is not None and _shrank(prev, cur):
            out.append(c)
        prev = cur
    return out
