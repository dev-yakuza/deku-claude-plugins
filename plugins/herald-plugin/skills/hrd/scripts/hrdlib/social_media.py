"""SNS pictures (design/herald/10-social-media.md, 0.19.0): a single image, card news and comics
for `/hrd social`, composed by limner.

A draft of a run with a format other than `text` has a media spec next to it
(`<draft>.media.json`). This module decides everything about that spec a prompt could get wrong:

- `materials` — what a picture may be made of (P24): the article's limner OG card, its diagrams
  (in a render record), scenes a human confirmed (`sha == generated_blob`), all as committed at
  HEAD, and `gen` — a picture generated for this draft — only where the channel has an AI
  disclosure and this machine can generate; never bytes of a quotation or an external image (P16);
- `spec_problems` — the spec's fields, limner's template limits, panel coordinates;
- `media` (`HRD social media`) — copies the materials out of HEAD, generates with the 0.18 run
  machinery (`images.drive`, a receiver of its own that writes no generation ledger — P26), and
  composes every picture with `lmn compose --layout` from layouts that are Herald constants (the
  boxes and fonts of limner's built-in `card-*` and `strip-*` templates — §10 R3-1);
- `freshness` — the proof `check` and `close` read: the media file = the `media` event = the
  protected compose record's `out_sha256`, the record's layout = the layout Herald builds again
  from the spec now, every input image = a material copy or a generated picture whose record
  matches the spec (§2.5).

Pictures, copies and records stay local (`.claude/herald/memory/social/<sns>/media/`, the limner
state dir) — never committed.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import unicodedata

from . import images, limner
from .util import HeraldError, read_json

FORMATS = ("text", "image", "cards", "comic")
COMPOSE_LANGS = ("ko", "ja", "en")  # limner's fonts
# a single image's aspect: the canvas preset and the generated size (§2.3 3)
ASPECTS = {"4x5": ("instagram-4x5", (720, 896)), "1x1": ("instagram-1x1", (896, 896)),
           "16x9": ("x-16x9", (1024, 576))}
PRESETS = {"instagram-4x5": (1080, 1350), "instagram-1x1": (1080, 1080), "x-16x9": (1600, 900)}
COVER_SIZE = (1024, 768)  # a generated card cover: 4:3 like the cover's 1080×810 box (v3 R2-6)
MAX_IMAGES = (1, 20)
CARDS_MIN = 3
BODY_CARDS = (1, 8)
TEMPLATES = ("card-cover", "card-body", "card-end")
# limner's template schemas (card-*.schema.json): (min, max) characters per text field
CARD_TEXT = {"card-cover": {"title": (1, 120), "subtitle": (1, 200)},
             "card-body": {"heading": (1, 120), "body": (1, 1200)},
             "card-end": {"message": (1, 300), "handle": (1, 80)}}
CARD_REQUIRED = {"card-cover": ("title",), "card-body": ("heading", "body"), "card-end": ("message",)}
CARD_KEYS = {"card-cover": ("template", "title", "subtitle", "image", "sources"),
             "card-body": ("template", "heading", "body", "sources"),
             "card-end": ("template", "message", "handle", "sources")}
CARD_IMAGE_KINDS = ("scene", "gen")  # a cover is a 4:3 `cover` crop: a diagram's labels would be cut (v2 R1-4)

# limner's built-in card templates as Herald constants (§10 R3-1): every picture is composed with
# `--layout`, so the compose record's layout sha256 binds the text Herald checked. A layer with
# `when` is left out when that field is empty (R3-4 — limner's `minLength: 1`).
_TEXT = {"type": "text", "lang": "{{lang}}"}
CARD_LAYOUTS = {
    "card-cover": {"version": 1, "canvas": {"preset": "instagram-4x5", "background": "#ffffff"}, "layers": [
        {"when": "image", "type": "image", "src": "{{image}}", "box": [0, 0, 1080, 810], "fit": "cover"},
        dict(_TEXT, box=[72, 850, 1008, 1130], runs=[{"text": "{{title}}"}], align="left", valign="top", weight=800,
             color="#111111", min_size=40, max_size=96),
        dict(_TEXT, when="subtitle", box=[72, 1150, 1008, 1280], runs=[{"text": "{{subtitle}}"}], align="left",
             valign="top", weight=500, color="#4b5563", min_size=24, max_size=44)]},
    "card-body": {"version": 1, "canvas": {"preset": "instagram-4x5", "background": "#ffffff"}, "layers": [
        dict(_TEXT, box=[72, 96, 1008, 280], runs=[{"text": "{{heading}}"}], align="left", valign="bottom",
             weight=800, color="#111111", min_size=32, max_size=72),
        {"type": "rect", "box": [72, 300, 192, 308], "color": "#111111"},
        dict(_TEXT, box=[72, 340, 1008, 1200], runs=[{"text": "{{body}}"}], align="left", valign="top", weight=400,
             color="#1f2937", min_size=24, max_size=48),
        dict(_TEXT, when="page", box=[72, 1230, 1008, 1290], runs=[{"text": "{{page}}"}], align="right",
             valign="middle", weight=500, color="#6b7280", size=28)]},
    "card-end": {"version": 1, "canvas": {"preset": "instagram-4x5", "background": "#111827"}, "layers": [
        dict(_TEXT, box=[96, 380, 984, 860], runs=[{"text": "{{message}}"}], align="center", valign="middle",
             weight=700, color="#ffffff", min_size=32, max_size=80),
        dict(_TEXT, when="handle", box=[96, 900, 984, 990], runs=[{"text": "{{handle}}"}], align="center",
             valign="middle", weight=500, color="#9ca3af", min_size=24, max_size=40)]},
}
# limner's strip templates: the canvas and each panel's box (strip-3x2's middle row is 424 high)
STRIPS = {
    "strip-2x2": {"preset": "instagram-1x1", "gen": (768, 768), "panel_size": [508, 508],
                  "boxes": [[24, 24, 532, 532], [548, 24, 1056, 532], [24, 548, 532, 1056], [548, 548, 1056, 1056]]},
    "strip-3x2": {"preset": "instagram-4x5", "gen": (768, 640), "panel_size": [508, 423],
                  "boxes": [[24, 24, 532, 447], [548, 24, 1056, 447], [24, 463, 532, 887], [548, 463, 1056, 887],
                            [24, 903, 532, 1326], [548, 903, 1056, 1326]]},
}
PANEL_BORDER = {"width": 4, "color": "#000000"}
BUBBLE_KINDS = ("speech", "shout", "thought", "narration")
BUBBLE_MIN_SIZE = 22   # px on a 1080 wide canvas (v2 R1-3): smaller → limner reports too_small
CAPTION_MIN_SIZE = 20
CAPTION_BAND = 0.18    # of the panel box's height
BUBBLE_MARGIN = 8
BUBBLES_MAX = 3
BUBBLE_TEXT_MAX = 100
CAPTION_TEXT_MAX = 100
REDRAW_MAX = 4         # pictures drawn again in one draft beyond its slots (Q2)
COMPOSE_TIMEOUT = 60
# a compose starts only with this much of the call left, and is cut at the call's end (wait + 55 s
# — a `--wait 0` call still composes; one picture takes about a second)
COMPOSE_START_MIN = 15
# limner `problems` a human may accept with a reason (`close --override`, §10 R3-3); the others never
OVERRIDABLE_PROBLEMS = ("overflow", "too_small", "low_contrast", "overlap", "tail_crosses")
CONTROL_RE = re.compile(r"[\x00-\x09\x0b-\x1f\x7f-\x9f  ]")


# --- paths ----------------------------------------------------------------------------------------

def spec_rel(draft_rel):
    return draft_rel[:-3] + ".media.json" if draft_rel.endswith(".md") else draft_rel + ".media.json"


def draft_name(draft_rel):
    b = os.path.basename(draft_rel)
    return b[:-3] if b.endswith(".md") else b


def draft_no(draft_rel):
    tail = draft_name(draft_rel).rsplit("-", 1)[-1]
    return int(tail) if tail.isdigit() else 1


def media_rel(sns, draft_rel, *parts):
    from .social import memory_rel
    return memory_rel(sns, "media", draft_name(draft_rel), *parts)


def _paths(root, cfg, run_id, n):
    """(state dir, its root-relative spelling, the jobs folder, the output folder's relative path)."""
    sd = limner.state_dir_abs(root, cfg)
    sd_rel = limner.rel_to_root(root, sd)
    return sd, sd_rel, os.path.join(sd, limner.JOBS_DIR), "%s/%s/social/%s/%d" % (sd_rel, limner.OUT_DIR, run_id, n)


def _job_base(run_id, n):
    return "social-%s-%d" % (run_id, n)


def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()


def _sha_file(path):
    try:
        with open(path, "rb") as f:
            return sha_bytes(f.read())
    except OSError:
        return None


def layout_bytes(layout):
    """The bytes Herald writes and hashes — deterministic, so check can build them again (§2.5)."""
    return json.dumps(layout, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


# --- materials (§2.4, P24) ---------------------------------------------------------------------

def _excluded(root, cfg, slug):
    """Contents (blob ids and sha256s) no SNS picture may use: every quotation and external image
    any topic recorded at HEAD, and every fetch this machine logged (P16)."""
    from .shots import Ledger
    out = set()
    for _, st in images._topic_states(root, "HEAD"):
        for f, meta in (((st.get("images") or {}).get("files")) or {}).items():
            if isinstance(meta, dict) and (meta.get("kind") == "external" or meta.get("use") == "quotation"):
                for p in {f, images.cur_path(root, cfg, slug, f) if slug else f}:
                    h = images._rev_hashes(root, "HEAD", p)
                    if h:
                        out |= {x for x in h if x}
    for r in Ledger(root).fetches:
        out |= {x for x in (r.get("blob"), r.get("sha256")) if isinstance(x, str) and x}
    if slug:
        for q in images.quotation_files(root, cfg, slug, rev="HEAD"):
            out |= {x for x in (q.get("blob"), q.get("sha256")) if x}
    return out


def materials(root, cfg, slug, gen_ok, scenes_ok=True):
    """[{path, kind, blob, sha256}] — base paths at HEAD (v2 R1-5), plus `{path: gen}` when a
    picture may be generated for this draft (v2 R1-7). Scenes only with `scenes_ok` (the channel
    discloses AI pictures — a scene is one). A daily draft has `gen` only."""
    out = []
    if slug:
        bad = _excluded(root, cfg, slug)
        olds = set(images._old_slugs(root, slug)) | {slug}
        lines, _ = images.slug_renders(root, cfg, slug, "HEAD")
        seen = {}

        def add(path, kind, h):
            if path in seen or not h or not h[1] or h[0] in bad or h[1] in bad:
                return
            seen[path] = {"path": path, "kind": kind, "blob": h[0], "sha256": h[1]}
            out.append(seen[path])
        ogp = cfg.og_path(slug) if images.og_conf(cfg) else None
        for _, st in images._topic_states(root, "HEAD"):
            if st.get("slug") not in olds:
                continue
            rec = st.get("images") or {}
            og = rec.get("og") or {}
            if ogp and og.get("status") == "made" and og.get("by") == "limner" and og.get("sha"):
                h = images._rev_hashes(root, "HEAD", ogp)
                if h and h[0] == og["sha"]:  # limner's og-title: text and a colour only (v2 R1-6)
                    add(ogp, "og", h)
            files = dict((rec.get("files") or {}))
            for it in (rec.get("items") or {}).values():
                if isinstance(it, dict) and it.get("file"):
                    files.setdefault(it["file"], {"kind": it.get("kind")})
            for f, meta in sorted(files.items()):
                kind = (meta or {}).get("kind") if isinstance(meta, dict) else None
                p = images.cur_path(root, cfg, slug, f)
                if kind == "diagram":
                    h = images._rev_hashes(root, "HEAD", p)
                    if h and any(r.get("png_blob") == h[0] for r in lines):  # blob ids only (v3 R2-5)
                        add(p, "diagram", h)
            for it in (rec.get("items") or {}).values() if scenes_ok else ():
                if not isinstance(it, dict) or it.get("kind") != "scene" or not it.get("sha"):
                    continue
                if str(it.get("role") or "").startswith("stand-in:"):
                    continue  # "not the actual place" never travels to SNS without its caption (12 §2.13)
                if it.get("sha") != it.get("generated_blob"):  # replaced or adopted by a human: not Herald's
                    continue
                p = images.cur_path(root, cfg, slug, it.get("file"))
                h = images._rev_hashes(root, "HEAD", p)
                if h and h[0] == it["sha"]:
                    add(p, "scene", h)
                    if it.get("confirmed_by") == "agent" and p in seen:  # a `--ship` run's (11 §2.4)
                        seen[p]["agent_reviewed"] = True
    if gen_ok:
        out.append({"path": "gen", "kind": "gen", "blob": None, "sha256": None})
    return out


def ai_ok(h):
    """The channel says how an AI picture is disclosed, or a human waived it (§2.6)."""
    return isinstance((h or {}).get("ai_disclosure"), dict)


def gen_available(root, cfg, h):
    """(ok, why): a picture may be generated here — an AI disclosure and a generator."""
    if not ai_ok(h):
        return False, "ai-disclosure"
    p = limner.gen_probe(root, cfg)
    return (True, None) if p["ok"] else (False, p["code"])


# --- the spec (§2.2) ----------------------------------------------------------------------------

def load_spec(root, draft_rel):
    """(raw bytes or None, spec dict or None, error or None)."""
    p = os.path.join(root, spec_rel(draft_rel))
    try:
        with open(p, "rb") as f:
            raw = f.read()
    except OSError:
        return None, None, "%s does not exist — write the media spec next to the draft" % spec_rel(draft_rel)
    try:
        spec = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError) as e:
        return raw, None, "%s is not JSON (%s)" % (spec_rel(draft_rel), e)
    if not isinstance(spec, dict):
        return raw, None, "%s is not a JSON object" % spec_rel(draft_rel)
    return raw, spec, None


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _gen_problems(g, where, appearance=None, persona=False):
    errs = []
    p = g.get("prompt")
    if not isinstance(p, str) or not p.strip():
        errs.append("%s: prompt is required (English, printable ASCII)" % where)
    elif len(p) > images.SCENE_PROMPT_MAX or not images.SCENE_TEXT_RE.match(p):
        errs.append("%s: prompt must be printable ASCII without \" \\ ` and at most %d characters"
                    % (where, images.SCENE_PROMPT_MAX))
    elif persona and appearance and appearance not in p:
        errs.append("%s: a panel with the persona carries the persona's appearance word for word" % where)
    elif persona and not appearance:
        errs.append("%s: persona: true but persona.md has no appearance — `/hrd social --persona` first" % where)
    s = g.get("seed")
    if not (isinstance(s, int) and not isinstance(s, bool) and 0 <= s <= images.SEED_MAX):
        errs.append("%s: seed must be an integer 0–%d" % (where, images.SEED_MAX))
    return errs


def _text_problems(v, where, lo, hi):
    from .social import find_urls
    if not isinstance(v, str):
        return ["%s must be a string" % where]
    if not lo <= len(v) <= hi:
        return ["%s must be %d–%d characters (limner's limit)" % (where, lo, hi)]
    if CONTROL_RE.search(v.replace("\n", "")) or "\r" in v:
        return ["%s: line breaks are \\n only, no other control characters" % where]
    if not v.strip():
        return ["%s is blank" % where]
    if find_urls(unicodedata.normalize("NFKC", v)):
        return ["%s holds a URL — links go in the post text only" % where]
    return []


def _sources_problems(v, where):
    if v is None:
        return []
    if not isinstance(v, list) or not all(isinstance(s, dict) for s in v):
        return ["%s.sources must be a list of {text, from}" % where]
    return []


def _handles(persona):
    out = []
    for t in (persona or {}).get("service_terms") or []:
        term = t if isinstance(t, str) else (t.get("term") if isinstance(t, dict) else None)
        if isinstance(term, str) and re.match(r"^@[A-Za-z0-9_]+$", term.strip()):
            out.append(term.strip())
    return out


def _box_ok(b):
    return isinstance(b, list) and len(b) == 4 and all(_num(v) for v in b) and b[2] > b[0] and b[3] > b[1]


def spec_problems(spec, fmt, kind, mats, persona=None, stage="compose", max_images=10):
    """The spec's errors (`media-spec`, content). `mats` = prepare's materials now (path → item);
    `stage == "panels"`: a comic's bubbles need no coordinates yet (v2 R1-12)."""
    errs = []
    if not isinstance(spec, dict):
        return ["the media spec is not a JSON object"]
    if spec.get("version") != 1:
        errs.append("version must be 1")
    if spec.get("format") != fmt:
        errs.append("format %r but this run is %s" % (spec.get("format"), fmt))
        return errs
    appearance = (persona or {}).get("appearance") if isinstance((persona or {}).get("appearance"), str) else None

    def material(v, where, kinds=None):
        if isinstance(v, dict):
            if v.get("from") != "gen":
                return ["%s: an object is {\"from\": \"gen\", \"prompt\", \"seed\"}" % where]
            if "gen" not in mats:
                return ["%s: no picture can be generated for this draft (no AI disclosure in the guide, a daily "
                        "post's article, or no generator here) — pick a material" % where]
            if set(v) - {"from", "prompt", "seed"}:
                return ["%s: unknown keys %s" % (where, ", ".join(sorted(set(v) - {"from", "prompt", "seed"})))]
            return _gen_problems(v, where)
        if not isinstance(v, str) or v not in mats or v == "gen":
            return ["%s: %r is not one of this draft's materials (prepare's `materials`)" % (where, v)]
        if kinds and mats[v]["kind"] not in kinds:
            return ["%s: a %s cannot be used here (only %s)" % (where, mats[v]["kind"], ", ".join(kinds))]
        return []

    if fmt == "image":
        if set(spec) - {"version", "format", "image"}:
            errs.append("unknown keys %s" % ", ".join(sorted(set(spec) - {"version", "format", "image"})))
        im = spec.get("image")
        if not isinstance(im, dict) or "from" not in im:
            return errs + ["image must be {\"from\": <material path> | \"gen\", …}"]
        if im.get("from") == "gen":
            errs += material(im, "image")
        else:
            if set(im) - {"from"}:
                errs.append("image: a material takes only from")
            errs += material(im.get("from"), "image.from")
    elif fmt == "cards":
        if set(spec) - {"version", "format", "cards"}:
            errs.append("unknown keys %s" % ", ".join(sorted(set(spec) - {"version", "format", "cards"})))
        cards = spec.get("cards")
        if not isinstance(cards, list) or not all(isinstance(c, dict) for c in cards):
            return errs + ["cards must be a list of cards"]
        names = [c.get("template") for c in cards]
        top = min(10, max_images)
        if not CARDS_MIN <= len(cards) <= top:
            errs.append("%d cards — a carousel here has %d–%d" % (len(cards), CARDS_MIN, top))
        if not names or names[0] != "card-cover" or names.count("card-cover") != 1:
            errs.append("the first card, and only the first, is card-cover")
        if names.count("card-end") > 1 or ("card-end" in names and names[-1] != "card-end"):
            errs.append("at most one card-end, and it is the last card")
        if not BODY_CARDS[0] <= names.count("card-body") <= BODY_CARDS[1]:
            errs.append("%d–%d card-body cards" % BODY_CARDS)
        handles = _handles(persona)
        for i, c in enumerate(cards, 1):
            t, where = c.get("template"), "cards[%d]" % i
            if t not in TEMPLATES:
                errs.append("%s: template must be one of %s" % (where, ", ".join(TEMPLATES)))
                continue
            extra = set(c) - set(CARD_KEYS[t])
            if extra:
                errs.append("%s: %s takes no %s" % (where, t, ", ".join(sorted(extra))))
            for k in CARD_REQUIRED[t]:
                if k not in c:
                    errs.append("%s: %s needs %s" % (where, t, k))
            for k, (lo, hi) in CARD_TEXT[t].items():
                if k in c and c[k] is not None and not (c[k] == "" and k not in CARD_REQUIRED[t]):
                    # an empty optional field is left out of the layout (R3-4), never sent empty
                    errs += _text_problems(c[k], "%s.%s" % (where, k), lo, hi)
            if t == "card-cover" and c.get("image") is not None:
                errs += material(c["image"], "%s.image" % where, CARD_IMAGE_KINDS)
            if t == "card-end" and c.get("handle"):
                if kind != "promo":
                    errs.append("%s: a handle goes on promotional cards only (v3 R2-3)" % where)
                elif c["handle"] not in handles:
                    errs.append("%s: handle must be one of the persona's account handles (service_terms): %s"
                                % (where, ", ".join(handles) or "none"))
            errs += _sources_problems(c.get("sources"), where)
    elif fmt == "comic":
        if set(spec) - {"version", "format", "layout", "panels"}:
            errs.append("unknown keys %s" % ", ".join(sorted(set(spec) - {"version", "format", "layout", "panels"})))
        strip = STRIPS.get(spec.get("layout"))
        if not strip:
            return errs + ["layout must be one of %s" % ", ".join(STRIPS)]
        panels = spec.get("panels")
        if not isinstance(panels, list) or not all(isinstance(p, dict) for p in panels):
            return errs + ["panels must be a list"]
        if len(panels) != len(strip["boxes"]):
            return errs + ["%s has exactly %d panels" % (spec["layout"], len(strip["boxes"]))]
        for i, p in enumerate(panels, 1):
            where = "panels[%d]" % i
            extra = set(p) - {"prompt", "seed", "persona", "caption", "bubbles", "sources"}
            if extra:
                errs.append("%s: unknown keys %s" % (where, ", ".join(sorted(extra))))
            if "persona" in p and not isinstance(p["persona"], bool):
                errs.append("%s: persona is true or false" % where)
            errs += _gen_problems(p, where, appearance, p.get("persona") is True)
            x0, y0, x1, y1 = strip["boxes"][i - 1]
            w, h = x1 - x0, y1 - y0
            cap = p.get("caption")
            if cap is not None and not (isinstance(cap, dict) and cap.get("text") == ""):
                if not isinstance(cap, dict) or set(cap) - {"text", "pos"}:
                    errs.append("%s.caption is {text, pos: top|bottom}" % where)
                else:
                    errs += _text_problems(cap.get("text"), "%s.caption.text" % where, 1, CAPTION_TEXT_MAX)
                    if stage != "panels" and cap.get("pos") not in ("top", "bottom"):
                        errs.append("%s.caption.pos must be top or bottom" % where)
            bubbles = p.get("bubbles", [])
            if not isinstance(bubbles, list) or not all(isinstance(b, dict) for b in bubbles):
                errs.append("%s.bubbles must be a list" % where)
                bubbles = []
            if len(bubbles) > BUBBLES_MAX:
                errs.append("%s: at most %d bubbles a panel" % (where, BUBBLES_MAX))
            boxes = []
            for k, b in enumerate(bubbles, 1):
                bw = "%s.bubbles[%d]" % (where, k)
                if set(b) - {"kind", "text", "box", "tail"}:
                    errs.append("%s: unknown keys %s" % (bw, ", ".join(sorted(set(b) - {"kind", "text", "box", "tail"}))))
                if b.get("kind", "speech") not in BUBBLE_KINDS:
                    errs.append("%s.kind must be one of %s" % (bw, ", ".join(BUBBLE_KINDS)))
                errs += _text_problems(b.get("text"), "%s.text" % bw, 1, BUBBLE_TEXT_MAX)
                box, tail = b.get("box"), b.get("tail")
                if box is None and stage == "panels":
                    continue
                if not _box_ok(box):
                    errs.append("%s.box must be [x0, y0, x1, y1] in the panel box (%d×%d, top left 0,0)" % (bw, w, h))
                    continue
                m = BUBBLE_MARGIN
                if box[0] < m or box[1] < m or box[2] > w - m or box[3] > h - m:
                    errs.append("%s.box %s leaves the panel box (%d×%d, %d px margin)" % (bw, box, w, h, m))
                if tail is not None and not (isinstance(tail, list) and len(tail) == 2 and all(_num(v) for v in tail)
                                             and 0 <= tail[0] <= w and 0 <= tail[1] <= h):
                    errs.append("%s.tail must be [x, y] inside the panel box (%d×%d)" % (bw, w, h))
                for j, o in boxes:
                    if box[0] < o[2] and o[0] < box[2] and box[1] < o[3] and o[1] < box[3]:
                        errs.append("%s overlaps bubble %d" % (bw, j))
                boxes.append((k, box))
            errs += _sources_problems(p.get("sources"), where)
    else:
        errs.append("format must be one of %s" % ", ".join(FORMATS[1:]))
    return errs


def image_text(spec, fmt):
    """The words drawn into the pictures, in document order, one field a line — checked with the
    post text (P23, v2 R1-2). The end card's handle is the account's own name, not a mention (v3 R2-3)."""
    out = []
    if fmt == "cards":
        for c in spec.get("cards") or []:
            if isinstance(c, dict):
                for k in ("title", "subtitle", "heading", "body", "message"):
                    if isinstance(c.get(k), str) and c[k].strip():
                        out.append(c[k])
    elif fmt == "comic":
        for p in spec.get("panels") or []:
            if not isinstance(p, dict):
                continue
            cap = p.get("caption")
            if isinstance(cap, dict) and isinstance(cap.get("text"), str):
                out.append(cap["text"])
            for b in p.get("bubbles") or []:
                if isinstance(b, dict) and isinstance(b.get("text"), str):
                    out.append(b["text"])
    return "\n".join(out)


def image_fields(spec, fmt):
    """[(label, text)] of the words drawn into the pictures: one unit a card or a panel (its text
    fields a line each, never the handle) — what a reader sees together is judged together, so a
    failure names the picture and its words (review 22 R2-1, R3-1)."""
    out = []
    if fmt == "cards":
        for i, c in enumerate(spec.get("cards") or [], 1):
            if isinstance(c, dict):
                t = [c[k] for k in ("title", "subtitle", "heading", "body", "message")
                     if isinstance(c.get(k), str) and c[k].strip()]
                if t:
                    out.append(("card %d" % i, "\n".join(t)))
    elif fmt == "comic":
        for i, p in enumerate(spec.get("panels") or [], 1):
            if not isinstance(p, dict):
                continue
            cap = p.get("caption")
            t = [cap["text"]] if isinstance(cap, dict) and isinstance(cap.get("text"), str) and cap["text"].strip() \
                else []
            t += [b["text"] for b in p.get("bubbles") or []
                  if isinstance(b, dict) and isinstance(b.get("text"), str) and b["text"].strip()]
            if t:
                out.append(("panel %d" % i, "\n".join(t)))
    return out


def spec_sources(spec, fmt):
    """The spec's quotes, each tagged with its card or panel (`_where`) for the failure detail."""
    items = (spec.get("cards") if fmt == "cards" else spec.get("panels") if fmt == "comic" else None) or []
    out = []
    for i, x in enumerate(items, 1):
        if isinstance(x, dict) and isinstance(x.get("sources"), list):
            out += [dict(s, _where="%s %d sources" % ("card" if fmt == "cards" else "panel", i))
                    for s in x["sources"] if isinstance(s, dict)]
    return out


def used_materials(spec, fmt):
    """Material paths the spec draws from (never `gen`)."""
    if fmt == "image":
        f = (spec.get("image") or {}).get("from")
        return [f] if isinstance(f, str) and f != "gen" else []
    if fmt == "cards":
        return [c["image"] for c in spec.get("cards") or [] if isinstance(c, dict) and isinstance(c.get("image"), str)]
    return []


def spec_generated(spec, fmt, mats):
    """A post with a generated picture (§2.4): a scene material, `gen`, and every comic."""
    if fmt == "comic":
        return True
    if fmt == "image" and (spec.get("image") or {}).get("from") == "gen":
        return True
    if fmt == "cards" and any(isinstance(c, dict) and isinstance(c.get("image"), dict) for c in spec.get("cards") or []):
        return True
    return any((mats.get(p) or {}).get("kind") == "scene" for p in used_materials(spec, fmt))


def media_input(root, cfg, rec, rel, text=None, stage="compose"):
    """{spec, raw, errors, text, sources, generated, mats} of one draft's media (check's and
    media's shared reading). `errors` are `media-spec` lines."""
    from .social import _load_committed, effective
    out = {"spec": None, "raw": None, "errors": [], "text": "", "fields": [], "sources": [], "generated": False,
           "mats": {}}
    fmt = rec.get("format") or "text"
    raw, spec, err = load_spec(root, rel)
    out["raw"] = raw
    if err:
        out["errors"].append(err)
        return out
    h, persona = _load_committed(root, cfg, rec["sns"])
    # `gen` by the channel's AI disclosure alone: whether this machine can generate is `media`'s
    # question (prepare offered `gen` only where it could), never a reason to fail a made picture
    mats = {m["path"]: m for m in materials(root, cfg, rec.get("slug"), ai_ok(h), ai_ok(h))}
    out["mats"] = mats
    out["spec"] = spec
    out["errors"] = spec_problems(spec, fmt, rec.get("kind"), mats, persona, stage, effective(h)["max_images"])
    out["text"] = image_text(spec, fmt)
    out["fields"] = image_fields(spec, fmt)
    out["sources"] = spec_sources(spec, fmt)
    out["generated"] = spec_generated(spec, fmt, mats)
    return out


# --- jobs and layouts ---------------------------------------------------------------------------

def jobs_of(cfg, spec, fmt, h, out_dir):
    """[job] of the pictures to generate, in slot order: {id, slot, out, width, height, prompt,
    refs: [], seed} (images._job_entry's shape; refs are always empty — v2 R1-12)."""
    out = []

    def job(jid, slot, g, size):
        return {"id": jid, "slot": slot, "out": "%s/gen-%d.png" % (out_dir, slot), "width": size[0],
                "height": size[1], "prompt": images.full_prompt(cfg, {"prompt": g.get("prompt")}), "refs": [],
                "seed": g.get("seed")}
    if fmt == "image" and (spec.get("image") or {}).get("from") == "gen":
        out.append(job("img", 1, spec["image"], ASPECTS[effective_aspect(h)][1]))
    elif fmt == "cards":
        cover = next((c for c in spec.get("cards") or [] if isinstance(c, dict) and c.get("template") == "card-cover"),
                     {})
        if isinstance(cover.get("image"), dict):
            out.append(job("cover", 1, cover["image"], COVER_SIZE))
    elif fmt == "comic":
        size = STRIPS[spec["layout"]]["gen"]
        for i, p in enumerate(spec.get("panels") or [], 1):
            out.append(job("p%d" % i, i, p, size))
    return out


def job_key(job):
    return "sha256:" + sha_bytes(json.dumps([job["prompt"], job["width"], job["height"], job["seed"],
                                             limner.GEN_MODEL]).encode("utf-8"))


def effective_aspect(h):
    from .social import effective
    return effective(h)["image_aspect"]


def _fill(tpl, values):
    """limner's template rule on a Herald constant: a layer whose `when` field is empty goes, a
    whole-string `{{key}}` becomes the value."""
    def sub(v):
        if isinstance(v, str):
            m = re.match(r"^\{\{(\w+)\}\}$", v)
            return values.get(m.group(1)) if m else v
        if isinstance(v, list):
            return [sub(x) for x in v]
        if isinstance(v, dict):
            return {k: sub(x) for k, x in v.items()}
        return v
    out = {"version": 1, "canvas": dict(tpl["canvas"]), "layers": []}
    for layer in tpl["layers"]:
        if layer.get("when") and not values.get(layer["when"]):
            continue
        out["layers"].append(sub({k: v for k, v in layer.items() if k != "when"}))
    return out


def layouts(spec, fmt, lang, src, preview=False):
    """The layouts of a draft's pictures, in order. `src(ref)` = the root-relative path of a
    material copy (ref = its base path) or of a generated picture (ref = ("gen", slot)).
    `preview`: a comic's panels alone — no caption, no bubbles (v3 R2-6)."""
    if fmt == "image":
        im = spec["image"]
        preset = ASPECTS[spec.get("_aspect") or "4x5"][0]
        w, h = PRESETS[preset]
        ref = ("gen", 1) if im.get("from") == "gen" else im["from"]
        return [{"version": 1, "canvas": {"preset": preset, "background": "#ffffff"},
                 "layers": [{"type": "image", "src": src(ref), "box": [0, 0, w, h], "fit": "contain"}]}]
    if fmt == "cards":
        cards = spec["cards"]
        out = []
        for i, c in enumerate(cards, 1):
            t = c["template"]
            vals = {"lang": lang}
            for k in CARD_TEXT[t]:
                if isinstance(c.get(k), str) and c[k]:
                    vals[k] = c[k]
            if t == "card-cover" and c.get("image") is not None:
                vals["image"] = src(("gen", 1) if isinstance(c["image"], dict) else c["image"])
            if t == "card-body":
                vals["page"] = "%d/%d" % (i, len(cards))  # card-body only: limner refuses it elsewhere (v2 R1-4)
            out.append(_fill(CARD_LAYOUTS[t], vals))
        return out
    strip = STRIPS[spec["layout"]]
    layers, texts = [], []
    for i, p in enumerate(spec["panels"], 1):
        x0, y0, x1, y1 = strip["boxes"][i - 1]
        layers.append({"type": "image", "src": src(("gen", i)), "box": [x0, y0, x1, y1], "fit": "cover",
                       "border": dict(PANEL_BORDER)})
        if preview:
            continue
        cap = p.get("caption")
        if isinstance(cap, dict) and cap.get("text"):
            band = round((y1 - y0) * CAPTION_BAND)
            box = [x0, y0, x1, y0 + band] if cap.get("pos") == "top" else [x0, y1 - band, x1, y1]
            texts.append({"type": "caption", "box": box, "lang": lang, "runs": [{"text": cap["text"]}],
                          "background": "#ffffff", "min_size": CAPTION_MIN_SIZE})
        for b in p.get("bubbles") or []:
            bb = b["box"]
            layer = {"type": "bubble", "kind": b.get("kind", "speech"), "lang": lang, "runs": [{"text": b["text"]}],
                     "box": [x0 + bb[0], y0 + bb[1], x0 + bb[2], y0 + bb[3]], "min_size": BUBBLE_MIN_SIZE}
            if b.get("tail") is not None:
                layer["tail"] = [x0 + b["tail"][0], y0 + b["tail"][1]]
            texts.append(layer)
    return [{"version": 1, "canvas": {"preset": strip["preset"], "background": "#ffffff"}, "layers": layers + texts}]


def _layout_spec(spec, fmt, h):
    """The spec with what the layout needs from the guide (the single image's aspect)."""
    if fmt == "image":
        return dict(spec, _aspect=effective_aspect(h))
    return spec


def copy_name(sha256):
    return "in-%s.png" % sha256[:12]


# --- the generation state (one file per draft — §2.3 3) ----------------------------------------

def _gen_file(root, cfg, run_id, n):
    _, _, jobs_dir, _ = _paths(root, cfg, run_id, n)
    return os.path.join(jobs_dir, "%s.gen.json" % _job_base(run_id, n))


def _read_gen(path):
    try:
        g = read_json(path)
    except ValueError:
        g = None
    return g if isinstance(g, dict) else {}


def _write_gen(path, g):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(g, f, sort_keys=True)
    os.replace(tmp, path)


# --- HRD social media (§2.3) ---------------------------------------------------------------------

def _cat_head(root, path):
    """The committed content of `path` (filters and LFS applied — v3 R2-5)."""
    p = subprocess.run(["git", "cat-file", "--filters", "HEAD:%s" % path], cwd=root, capture_output=True)
    return p.stdout if p.returncode == 0 else None


def _media_event(root, rel):
    from .social import events
    ev = None
    for e in events(root):
        if e.get("event") == "media" and e.get("draft") == rel:
            ev = e
    return ev


def media(root, cfg, draft, wait=images.GEN_WAIT, stage=None):
    """`HRD social media --draft <d>`: one draft's pictures. Returns {state: done|running|failed,
    files, problems, errors, remaining, generated} (+ panels, preview, panel_size for
    `--stage panels`). `errors[]` = {code, class: content|env|internal|human, message}."""
    from .social import _load_committed, _rel, drafted_record, evaluate, log_event, on_base
    t0 = time.monotonic()
    deadline = t0 + wait + images.GEN_SLACK if isinstance(wait, int) else t0

    def room():
        return deadline - time.monotonic()

    def cap(n):
        return max(1, int(min(n, room())))
    on_base(root, cfg)
    if not (isinstance(wait, int) and 0 <= wait <= images.GEN_WAIT_MAX):
        raise HeraldError("--wait is 0 to %d seconds" % images.GEN_WAIT_MAX)
    rel = _rel(root, draft)
    rec = drafted_record(root, rel)
    if not rec:
        raise HeraldError("%s is not a draft `HRD social prepare` laid out" % rel)
    fmt = rec.get("format") or "text"
    if fmt == "text":
        raise HeraldError("%s is a text draft — it has no pictures" % rel)
    if stage not in (None, "panels", "compose"):
        raise HeraldError("--stage is panels or compose")
    if stage == "panels" and fmt != "comic":
        raise HeraldError("--stage panels is a comic's first step only")
    stage = stage or "compose"
    out = {"state": "failed", "draft": rel, "format": fmt, "files": [], "problems": [], "errors": [], "remaining": [],
           "generated": False}

    def fail(code, klass, message):
        out["errors"].append({"code": code, "class": klass, "message": message})
        out["state"] = "failed"
        return out
    try:
        with open(os.path.join(root, rel), "rb") as f:
            text = f.read().decode("utf-8-sig", errors="replace")
    except OSError:
        raise HeraldError("draft %s does not exist" % rel)
    # 1: the spec, the materials and the words — before anything is generated (v2 R1-12, v4 R3-2)
    mi = media_input(root, cfg, rec, rel, stage=stage)
    if mi["errors"]:
        for e in mi["errors"]:
            fail("media-spec", "content", e)
        return out
    # the words in the pictures are judged on their own (the profile is the whole post's) and any
    # failure they cause holds the pictures back; the post text's own failures wait for check, where
    # a human may still accept an overridable one (review 22 #2, R2-1)
    res = evaluate(root, cfg, rec, text, media=mi)
    for f in res["failed"]:
        if f.get("where"):
            fail(f["id"], "content", f["detail"])
    if out["errors"]:
        return out
    spec, mats = mi["spec"], mi["mats"]
    out["generated"] = mi["generated"]
    h, _ = _load_committed(root, cfg, rec["sns"])
    lang = h["lang"].split("-")[0].lower()
    run_id, n = rec["run"], draft_no(rel)
    sd, _, jobs_dir, out_dir = _paths(root, cfg, run_id, n)
    rroot = os.path.realpath(root)
    # 2: the materials as committed at HEAD (v2 R1-8, v3 R2-5)
    copies = {}
    for path in used_materials(spec, fmt):
        m = mats[path]
        data = _cat_head(root, path)
        if data is None or sha_bytes(data) != m["sha256"]:
            return fail("material", "env", "%s cannot be read from HEAD as prepare saw it" % path)
        dest = "%s/%s" % (out_dir, copy_name(m["sha256"]))
        full = os.path.join(root, dest)
        if _sha_file(full) != m["sha256"]:
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "wb") as fh:
                fh.write(data)
        copies[path] = dest
    # 3: generate (the 0.18 run machinery, a receiver of its own — v2 R1-9)
    jobs = jobs_of(cfg, spec, fmt, h, out_dir)
    gpath = _gen_file(root, cfg, run_id, n)
    gstate = _read_gen(gpath)
    gen = gstate.get("gen") if isinstance(gstate.get("gen"), dict) else {}
    drawn = list(gstate.get("drawn") or [])
    res_g = {"state": "done", "generated": [], "skipped": [], "failed": [], "running": [], "regenerated": [],
             "waited_s": gen.get("waited_s", 0), "run_id": gen.get("run_id")}
    pre, done = {}, {}
    for j in jobs:
        data, _, bad = images._verify_record(root, cfg, j["out"], j)
        pre[j["id"]] = "generated" if not bad else "pending"
        if not bad:
            done[j["id"]] = sha_bytes(data)

    def save(g):
        _write_gen(gpath, {"gen": g or None, "drawn": drawn})
    if jobs and "pending" in pre.values():
        # every picture drawn counts, the same key drawn again too (review 22 #7)
        pending = sum(1 for j in jobs if pre[j["id"]] == "pending")
        if len(drawn) + pending - len(jobs) > REDRAW_MAX:
            return fail("redraw-limit", "human", "this draft drew %d pictures again already (at most %d) — ask the "
                        "human: go on, another format, or stop" % (len(drawn) - len(jobs), REDRAW_MAX))
        p = limner.gen_probe(root, cfg)
        if not p["ok"]:
            return fail(p["code"], "env", p.get("message") or "this machine cannot generate pictures")

        counted = set()

        def take(jid, regen, rid):
            j = next(x for x in jobs if x["id"] == jid)
            data, r, bad = images._verify_record(root, cfg, j["out"], j)
            if bad:
                res_g["failed"].append({"id": jid, "code": bad, "class": "env",
                                        "message": "limner's record does not vouch for %s (%s)" % (j["out"], bad)})
                return
            done[jid] = sha_bytes(data)
            if pre.get(jid) == "pending" and jid not in counted:  # drawn by this call's run
                counted.add(jid)
                drawn.append(job_key(j))
            res_g["generated"].append({"id": jid, "seconds": (r or {}).get("seconds")})
        os.makedirs(jobs_dir, exist_ok=True)
        jpath = os.path.join(jobs_dir, "%s.json" % _job_base(run_id, n))
        jl = [{k: v for k, v in j.items() if k != "slot"} for j in jobs]
        jmap = {j["id"]: j for j in jl}
        r = images.drive(root, cfg, [{"id": j["id"]} for j in jobs], jmap, jpath, pre, res_g, gen, save, take,
                         t0, wait, room, cap)
        if r is not None:
            gen, live = r
            save(gen)
            if live or res_g["running"]:
                out.update(state="running", remaining=[j["id"] for j in jobs if j["id"] not in done],
                           waited_s=gen.get("waited_s", 0) if gen else 0)
                return out
        for f in res_g["failed"]:
            fail(f.get("code") or "error", "env", f.get("message") or "limner could not generate %s" % f.get("id"))
        if out["errors"]:
            return out
    elif gen.get("run_id"):  # nothing to make: a run Herald still follows is stopped (0.18 m4)
        _, f = images._stop_run(root, cfg, gen["run_id"], room)
        if not f:
            save(None)
    missing = [j["id"] for j in jobs if j["id"] not in done]
    if missing:
        return fail("record-mismatch", "env", "generated pictures not vouched for: %s" % ", ".join(missing))

    def src(ref):
        if isinstance(ref, tuple):
            return next(j["out"] for j in jobs if j["slot"] == ref[1])
        return copies[ref]
    allowed = {mats[p]["sha256"] for p in copies} | set(done.values())
    mdir = os.path.join(root, media_rel(rec["sns"], rel))
    # 4: a comic's panels alone, for the distributor to place the words on (v3 R2-6)
    if stage == "panels":
        if room() < COMPOSE_START_MIN:  # review 22 #6
            out.update(state="running", remaining=["preview"])
            return out
        lay = layouts(spec, fmt, lang, src, preview=True)[0]
        target = "%s/preview.png" % out_dir
        code, probs, err = _compose(root, cfg, sd, rroot, jobs_dir, _job_base(run_id, n) + "-preview", lay, target,
                                    allowed, cap(min(COMPOSE_TIMEOUT, room() - 5)))
        if err:
            return fail(err["code"], err["class"], err["message"])
        pdir = os.path.join(mdir, "preview")
        os.makedirs(pdir, exist_ok=True)
        shutil.copyfile(os.path.join(root, target), os.path.join(pdir, "preview.png"))
        out.update(state="done", stage="panels", preview=media_rel(rec["sns"], rel, "preview", "preview.png"),
                   panels=[{"n": j["slot"], "path": j["out"]} for j in jobs],
                   panel_size=STRIPS[spec["layout"]]["panel_size"],
                   panel_boxes=[[b[2] - b[0], b[3] - b[1]] for b in STRIPS[spec["layout"]]["boxes"]])
        return out
    # 5: compose every picture with Herald's own layout (§10 R3-1)
    lays = layouts(_layout_spec(spec, fmt, h), fmt, lang, src)
    files, problems = [], []
    for i, lay in enumerate(lays, 1):
        if room() < COMPOSE_START_MIN:
            out["remaining"] = ["compose-%d" % k for k in range(i, len(lays) + 1)]
            out["state"] = "running"
            return out
        target = "%s/composed-%d.png" % (out_dir, i)
        code, probs, err = _compose(root, cfg, sd, rroot, jobs_dir, "%s-layout-%d" % (_job_base(run_id, n), i), lay,
                                    target, allowed, cap(min(COMPOSE_TIMEOUT, room() - 5)))
        if err:
            return fail(err["code"], err["class"], err["message"])
        problems += [dict(p, i=i) for p in probs]
        files.append({"i": i, "src": target, "sha256": code["out_sha256"], "record": code["record"],
                      "input_sha256": code["layout_sha256"]})
    # 6: the pictures next to the draft (problems kept with them — the human decides, §10 R3-3)
    shutil.rmtree(mdir, ignore_errors=True)
    os.makedirs(mdir, exist_ok=True)
    for f in files:
        shutil.copyfile(os.path.join(root, f["src"]), os.path.join(mdir, "%d.png" % f["i"]))
    spec_sha = sha_bytes(mi["raw"])
    log_event(root, {"event": "media", "run": run_id, "sns": rec["sns"], "draft": rel, "format": fmt,
                     "spec_sha256": spec_sha,
                     "files": [{k: f[k] for k in ("i", "sha256", "record", "input_sha256")} for f in files],
                     "materials": [{"path": p, "blob": mats[p]["blob"], "sha256": mats[p]["sha256"]} for p in copies],
                     "generated": mi["generated"], "problems": problems})
    out.update(state="done", problems=problems,
               files=[media_rel(rec["sns"], rel, "%d.png" % f["i"]) for f in files])
    return out


def _compose(root, cfg, sd, rroot, jobs_dir, name, layout, target, allowed, timeout):
    """One `lmn compose --layout`: (record facts, problems, error). Exit 2 is Herald's own bug
    (`internal` — its layout broke limner's checks; fonts → env), the rest the 0.17 table."""
    data = layout_bytes(layout)
    lpath = os.path.join(jobs_dir, name + ".json")
    os.makedirs(jobs_dir, exist_ok=True)
    with open(lpath, "wb") as f:
        f.write(data)
    out_abs = os.path.join(rroot, target)
    os.makedirs(os.path.dirname(out_abs), exist_ok=True)
    res = limner.run(root, cfg, ["compose"], [("--layout", lpath), ("--root", rroot), ("--state-dir", sd),
                                               ("--out", out_abs)], timeout=timeout)
    probs, failure = limner.classify(res)
    if failure:
        if failure["code"] == "input":
            return None, [], {"code": "internal", "class": "internal",
                              "message": "limner refused Herald's layout (%s)" % (failure["message"] or "")[:300]}
        return None, [], {"code": failure["code"], "class": "env", "message": failure["message"]}
    rec = limner.read_record(root, cfg, target)
    sha = _sha_file(out_abs)
    why = _record_problem(rec, target, sha, sha_bytes(data), allowed)
    if why:
        return None, [], {"code": "record-mismatch", "class": "env", "message": "limner's compose record of %s: %s"
                          % (target, why)}
    return {"out_sha256": sha, "record": "%s/records/%s.json" % (limner.rel_to_root(root, sd), target),
            "layout_sha256": sha_bytes(data)}, probs, None


def _record_problem(rec, target, sha, layout_sha, allowed):
    """Why limner's compose record does not vouch for this picture, or None (§2.5)."""
    if not isinstance(rec, dict):
        return "no record"
    if rec.get("kind") != "compose" or rec.get("contract") != limner.CONTRACT:
        return "not a compose record"
    if not isinstance(rec.get("out"), str) or os.path.normpath(rec["out"]) != os.path.normpath(target):
        return "another output"
    if not sha or rec.get("out_sha256") != sha:
        return "the file is not what limner wrote"
    if rec.get("layout_sha256") != layout_sha or "template" in rec:
        return "drawn from another layout than the spec's"
    ins = rec.get("inputs")
    if not isinstance(ins, list) or not all(isinstance(x, dict) and x.get("sha256") in allowed for x in ins):
        return "an input image that is no material copy or generated picture of this draft"
    return None


# --- the proof (§2.5) — check and close ------------------------------------------------------------

def freshness(root, cfg, rec, rel, mi):
    """(failures, info): `media-missing` / `media-stale` / `media-problems` of one draft, and
    {files, problems, generated} — read from the protected compose records, never the log alone."""
    from .social import _load_committed
    failures = []

    def fail(rid, detail, overridable=False):
        failures.append({"id": rid, "overridable": overridable, "detail": detail})
    fmt = rec.get("format") or "text"
    info = {"format": fmt, "files": [], "preview": None, "generated": mi["generated"]}
    ev = _media_event(root, rel)
    pv = media_rel(rec["sns"], rel, "preview", "preview.png")
    if os.path.isfile(os.path.join(root, pv)):
        info["preview"] = pv
    if not ev:
        fail("media-missing", "no pictures yet — `HRD social media --draft %s`" % rel)
        return failures, info
    spec, mats = mi["spec"], mi["mats"]
    stale = []
    if ev.get("spec_sha256") != sha_bytes(mi["raw"] or b""):
        stale.append("the media spec changed since the pictures were made")
    for m in ev.get("materials") or []:
        cur = mats.get(m.get("path"))
        if not cur or cur.get("blob") != m.get("blob"):
            stale.append("the material %s changed on base or is no material any more" % m.get("path"))
    h, _ = _load_committed(root, cfg, rec["sns"])
    run_id, n = rec["run"], draft_no(rel)
    _, _, _, out_dir = _paths(root, cfg, run_id, n)
    jobs = jobs_of(cfg, spec, fmt, h, out_dir)
    allowed = {mats[p]["sha256"] for p in used_materials(spec, fmt) if p in mats}
    for j in jobs:
        r = limner.read_record(root, cfg, j["out"]) or {}
        ok = r.get("kind") == "generate" and r.get("prompt") == j["prompt"] and r.get("seed") == j["seed"] and \
            r.get("width") == j["width"] and r.get("height") == j["height"] and r.get("refs") == [] and \
            os.path.normpath(str(r.get("out") or "")) == os.path.normpath(j["out"]) and \
            (r.get("generator") == "mflux" or (r.get("generator") == "fake" and limner.fake_allowed()))
        if ok and isinstance(r.get("out_sha256"), str):
            allowed.add(r["out_sha256"])
        else:
            stale.append("the generated picture %s is not what the spec asks for" % j["id"])

    def src(ref):
        if isinstance(ref, tuple):
            return next(j["out"] for j in jobs if j["slot"] == ref[1])
        return "%s/%s" % (out_dir, copy_name((mats.get(ref) or {}).get("sha256") or "0" * 12))
    try:
        lays = layouts(_layout_spec(spec, fmt, h), fmt, h["lang"].split("-")[0].lower(), src)
    except (KeyError, StopIteration, TypeError):
        lays = []
        stale.append("the spec cannot be laid out")
    files = {f.get("i"): f for f in ev.get("files") or [] if isinstance(f, dict)}
    mdir = os.path.join(root, media_rel(rec["sns"], rel))
    # every file but hidden ones (a Finder `.DS_Store`) and the preview folder: anything else in the
    # folder is not what Herald made (review 22 #4, R2-5)
    present = sorted(x for x in (os.listdir(mdir) if os.path.isdir(mdir) else [])
                     if not x.startswith(".") and x != "preview")
    want = ["%d.png" % i for i in range(1, len(lays) + 1)]
    if lays and present != want:
        stale.append("the media folder holds %s, not %s" % (", ".join(present) or "nothing", ", ".join(want)))
    for i, lay in enumerate(lays, 1):
        f = files.get(i)
        path = media_rel(rec["sns"], rel, "%d.png" % i)
        sha = _sha_file(os.path.join(root, path))
        if not f or not sha or f.get("sha256") != sha:
            stale.append("%s is not the picture `HRD social media` made" % path)
            continue
        target = "%s/composed-%d.png" % (out_dir, i)
        why = _record_problem(limner.read_record(root, cfg, target), target, sha, sha_bytes(layout_bytes(lay)),
                              allowed)
        if why:
            stale.append("%s: %s" % (path, why))
        info["files"].append(path)
    if stale:
        fail("media-stale", "; ".join(dict.fromkeys(stale)) + " — `HRD social media --draft %s` again" % rel)
        return failures, info
    probs = [p for p in ev.get("problems") or [] if isinstance(p, dict)]
    info["problems"] = probs
    soft = [p for p in probs if p.get("code") in OVERRIDABLE_PROBLEMS]
    hard = [p for p in probs if p.get("code") not in OVERRIDABLE_PROBLEMS]
    if hard:
        fail("media-problems", "limner found %s in picture %s" % (
            ", ".join(sorted({str(p.get("code")) for p in hard})), ", ".join(sorted({str(p.get("i")) for p in hard}))))
    if soft:
        fail("media-problems", "limner found %s in picture %s — a human may accept it" % (
            ", ".join(sorted({str(p.get("code")) for p in soft})), ", ".join(sorted({str(p.get("i")) for p in soft}))),
            overridable=True)
    return failures, info
