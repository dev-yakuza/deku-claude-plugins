"""Images Herald makes or fetches for an article (design/herald/08-images.md, 0.17.0;
09-scenes.md, 0.18.0).

brief plans each image place as one kind: a screenshot (06/07 — `screenshots.json`, untouched
here), an SVG diagram the illustrator draws and limner renders to PNG, an external image of a
real place, thing or work fetched from the web under a free license or as a quotation, or a
scene image — a mood or situation that need not be real — limner generates without any text in
it. The diagrams, external and scene images are listed in `<w>images.json`; this module checks
that manifest (`plan`), renders diagrams, fetches external images, generates scenes, writes the
OG card, and judges every item from evidence, never from a state field (P13):

- a diagram is `ready` when its PNG's content is in a committed render record
  (`<w>diagram-renders.jsonl`, written only by `render`, protected by the guard) — the text drawn
  into it is what verify checks;
- an external image is `ready` when its content is in this machine's fetch ledger and a human
  confirmed that content (`ledger/fetches.jsonl` + `confirmations.jsonl`, rule U of 0.16.0);
- a scene is `ready` when its content is in this machine's generation ledger (lines Herald wrote
  from what limner reported for this very job) and a human confirmed that content
  (`ledger/generations.jsonl` + `confirmations.jsonl`) — its body text always carries the AI label.

A repo without an `images` config block behaves exactly as 0.16.0.
"""

import hashlib
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import time
import urllib.parse
from collections import Counter

from . import limner
from .shots import (CONFIRMATIONS, FETCHES, GENERATIONS, Ledger, _bytes_hashes, blob, file_hashes, kind_of,
                    ledger_append, move_to_removed, on_base, public_url, removed_bytes)
from .util import HeraldError, git, git_ok, now_iso, read_json

MANIFEST = "images.json"
RENDERS = "diagram-renders.jsonl"
ID_RES = {"diagram": re.compile(r"^d[0-9]{1,3}$"), "external": re.compile(r"^e[0-9]{1,3}$"),
          "scene": re.compile(r"^g[0-9]{1,3}$")}
SCENE_RE = ID_RES["scene"]
EXTERNAL_EXTS = ("png", "jpg", "jpeg", "webp")
VALUE_BAD = re.compile(r"[<>\"\[\]\\\n\r]")  # alt, credit, title go into the body without escaping
VALUE_MAX = 300
LANGS = ("ko", "ja", "en")
LICENSE_URLS = {
    "CC0 1.0": "https://creativecommons.org/publicdomain/zero/1.0/",
    "Public domain": "https://creativecommons.org/publicdomain/mark/1.0/",
}
for _v in ("2.0", "2.5", "3.0", "4.0"):
    LICENSE_URLS["CC BY %s" % _v] = "https://creativecommons.org/licenses/by/%s/" % _v
    LICENSE_URLS["CC BY-SA %s" % _v] = "https://creativecommons.org/licenses/by-sa/%s/" % _v
FIGURE_FIELDS = ("ref", "alt", "credit", "license", "license_url", "page_url", "label", "source", "orientation")
FIGURE_REQUIRED = {"licensed": ("ref", "alt", "credit", "license", "license_url", "page_url"),
                   "quotation": ("ref", "alt", "credit", "label", "page_url")}
WORDS = {"licensed": "Photo", "quotation": "Quotation", "source": "Source"}
RENDER_FIELDS = ("svg_sha256", "background", "png_blob", "png_sha256")
OG_PLACEHOLDERS = ("{title}", "{slug}", "{date}", "{category}", "{lang}", "{out}")
OG_CONTENT_WHY = ("title-too-long", "missing_glyph", "low_contrast")
SVG_NS = "http://www.w3.org/2000/svg"
SVG_BANNED = ("script", "foreignObject", "image", "use", "a", "style", "title", "desc", "metadata")
SVG_MAX = 1 << 20

BUDGET = 90                 # one `render`/`fetch`/`og` call: under the Bash tool's 120 s default
RENDER_START_MIN = 65       # 60 s limner call + 5 s cleanup
FETCH_ITEM = 30
FETCH_START_MIN = 35
SOCK_TIMEOUT = 10
MAX_REDIRECTS = 3
MAX_SIDE = 8192
MAX_PIXELS = 40_000_000
OG_TOOL_TIMEOUT = 45

ENV_FETCH = ("net", "tls", "dns-fail", "retry-later", "timeout")

# scene images (09-scenes.md §2.2): sizes are code constants — a size changes the generation time
SCENE_SIZES = {"landscape": (1024, 576), "square": (896, 896), "portrait": (720, 896)}
NO_TEXT = ("No text, no letters, no numbers, no writing, no logos, no watermarks; any signs, screens and papers "
           "are blank.")  # appended to every scene prompt; no setting changes it (P21)
SCENE_PROMPT_MAX = 1000     # limner takes 1500; the rest is the style and NO_TEXT
SCENE_STYLE_MAX = 300
# printable ASCII without " \ and ` — the PR body shows each prompt as one code span, so a mention,
# HTML or a link in it stays text (review round 1 m9)
SCENE_TEXT_RE = re.compile(r"^[\x20\x21\x23-\x5b\x5d-\x5f\x61-\x7e]*$")
SCENE_LABELS = {"ko": "AI 생성 이미지", "ja": "AI生成画像", "en": "AI-generated image"}
SCENE_FIGURE = "![{alt}]({ref})\n*{label}*"
SCENE_FIELDS = ("ref", "alt", "label")
SEED_MAX = 2 ** 32 - 1
GEN_WAIT = 240              # one `generate` call's default budget; the caller's Bash timeout is (wait + 60) s
GEN_WAIT_MAX = 540          # limner's own `status --wait-seconds` ceiling
GEN_RUN_TIMEOUT = 60        # `run --wait 30` ends by itself while the machine is busy
GEN_CANCEL_WAIT = 30
GEN_SLACK = 55              # a call ends by `wait` + this; the caller's Bash timeout is `wait` + 60
GEN_RETRY = ("memory", "metal", "crashed")  # and `signal:*` — retried once in the same call
TRIAL_PROMPT = "A cup of tea on a wooden table by a window"


# --- paths and config --------------------------------------------------------------------------

def _work_rel(tid, name=""):
    from .store import work_rel
    return work_rel(tid, name)


def manifest_rel(tid):
    return _work_rel(tid, MANIFEST)


def renders_rel(tid):
    return _work_rel(tid, RENDERS)


def svg_rel(tid, iid):
    return _work_rel(tid, "diagrams/%s.svg" % iid)


def block(cfg):
    b = cfg.get("images")
    return b if isinstance(b, dict) else None


def managed(cfg):
    """Managed mode = an `images` block (§2.14.1). Without it everything is 0.16.0."""
    return block(cfg) is not None


def lang_tag(cfg):
    """The source language's primary subtag (`ko-KR`, `ja_JP` → ko, ja) — what limner gets."""
    v = str(cfg.source_lang() or "").lower()
    return re.split(r"[-_]", v, 1)[0]


def diagram_conf(cfg):
    d = (block(cfg) or {}).get("diagrams")
    if not isinstance(d, dict):
        return None
    return {"width": d.get("width", 1600), "background": d.get("background", "#ffffff")}


def external_on(cfg):
    return (block(cfg) or {}).get("external") is True


def og_conf(cfg):
    o = (block(cfg) or {}).get("og")
    if not isinstance(o, dict):
        return None
    return {"path": o.get("path", "{images}/{slug}/og.png"), "command": o.get("command"),
            "subtitle": o.get("subtitle"), "fallback_first_image": o.get("fallback_first_image", True)}


def figure(cfg):
    f = (block(cfg) or {}).get("figure")
    return f if isinstance(f, dict) else {}


def words(cfg):
    w = figure(cfg).get("words")
    return w if isinstance(w, dict) else {}


def illustrator_on(cfg):
    return "illustrator" in (cfg.get("roles", "conditional") or [])


def figure_errors_by_kind(cfg):
    """{"diagram", "licensed", "quotation", "scene": [errors]} — each list turns only its own kind
    off (implementation review m11): a `diagrams` setting or the diagram template turns diagrams
    off, the licensed template (and `words`) external images, the quotation template quotations,
    the scene template and `words.scene` scenes (09 §2.8). The quotation template is required only
    where a category may quote (`quotation_categories`)."""
    out = {"diagram": [], "licensed": [], "quotation": [], "scene": []}
    if not managed(cfg):
        return out
    d = (block(cfg) or {}).get("diagrams")
    if d is not None:
        if not isinstance(d, dict):
            out["diagram"].append("images.diagrams must be an object")
        else:
            w = d.get("width", 1600)
            if not isinstance(w, int) or isinstance(w, bool) or not 320 <= w <= 4096:
                out["diagram"].append("images.diagrams.width must be an integer from 320 to 4096")
            if not re.match(r"^#[0-9A-Fa-f]{6}$", str(d.get("background", "#ffffff"))):
                out["diagram"].append("images.diagrams.background must be #RRGGBB (diagrams always have an opaque "
                                      "background)")
    f = (block(cfg) or {}).get("figure")
    if f is not None and not isinstance(f, dict):
        for k in out:
            out[k].append("images.figure must be an object")
        return out
    f = f or {}
    try:
        quoting = bool(_rules(cfg.root)["images"]["external"].get("quotation_categories"))
    except Exception:  # noqa: BLE001 — unreadable rules: the gate reports them
        quoting = False
    t = f.get("scene")
    if t is not None:
        if not isinstance(t, str) or not t.strip():
            out["scene"].append("images.figure.scene must be a string")
        else:
            holes = set(re.findall(r"\{([^{}]*)\}", t))
            bad = sorted(holes - set(SCENE_FIELDS))
            if bad:
                out["scene"].append("images.figure.scene has unknown placeholders: %s" % ", ".join("{%s}" % b for b in bad))
            missing = [x for x in SCENE_FIELDS if x not in holes]
            if missing:
                out["scene"].append("images.figure.scene needs %s (the AI label is never left out — P19)"
                                    % ", ".join("{%s}" % m for m in missing))
    for name in ("diagram", "licensed", "quotation"):
        t = f.get(name)
        if t is None:
            if (name == "licensed" and external_on(cfg)) or (name == "quotation" and external_on(cfg) and quoting):
                out[name].append("images.figure.%s is missing — it must hold %s" % (
                    name, " ".join("{%s}" % x for x in FIGURE_REQUIRED[name])))
            continue
        if not isinstance(t, str) or not t.strip():
            out[name].append("images.figure.%s must be a string" % name)
            continue
        holes = set(re.findall(r"\{([^{}]*)\}", t))
        bad = sorted(holes - set(FIGURE_FIELDS))
        if bad:
            out[name].append("images.figure.%s has unknown placeholders: %s" % (
                name, ", ".join("{%s}" % b for b in bad)))
        need = FIGURE_REQUIRED.get(name, ("ref", "alt"))
        missing = [x for x in need if x not in holes]
        if missing:
            out[name].append("images.figure.%s needs %s (attribution: license URI and source page link)" % (
                name, ", ".join("{%s}" % m for m in missing)))
    w = f.get("words")
    if w is not None:
        errs = []
        if not isinstance(w, dict):
            errs.append("images.figure.words must be an object")
        else:
            for k, v in w.items():
                if k == "scene":
                    if not isinstance(v, str) or not v.strip() or len(v) > 60 or VALUE_BAD.search(v):
                        out["scene"].append("images.figure.words.scene is the AI label: 1–60 characters, no < > \" [ ] "
                                            "\\ or line break")
                elif k == "orientation":
                    if not isinstance(v, dict) or not all(isinstance(x, str) for x in v.values()):
                        errs.append("images.figure.words.orientation must map landscape/portrait to strings")
                elif not isinstance(v, str) or VALUE_BAD.search(v):
                    errs.append("images.figure.words.%s must be a plain string" % k)
        out["licensed"] += errs
        out["quotation"] += errs
    return out


def figure_errors(cfg):
    """Every `images.diagrams` and `images.figure` problem ([] when fine or unmanaged). Kept out
    of Config.validate (L4); each turns only its own kind off (`figure_errors_by_kind`)."""
    by = figure_errors_by_kind(cfg)
    return list(dict.fromkeys(by["diagram"] + by["licensed"] + by["quotation"]))


def scene_conf(cfg):
    """`images.scenes` with its defaults, or None (scenes are off by config)."""
    c = (block(cfg) or {}).get("scenes")
    if not isinstance(c, dict):
        return None
    return {"max": c.get("max", 2), "per_category": c.get("per_category") if isinstance(c.get("per_category"), dict)
            else {}, "style": c.get("style") or "", "wait_minutes": c.get("wait_minutes", 30)}


def _small_int(v, lo, hi):
    return isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


def scene_errors(cfg):
    """`images.scenes`, `figure.scene` and `words.scene` problems (09 §2.11) — [] when fine or when
    the repo has no scenes. Kept out of Config.validate and the guard (L4): any turns scenes off."""
    if not managed(cfg) or "scenes" not in (block(cfg) or {}):
        return []
    c = block(cfg)["scenes"]
    if not isinstance(c, dict):
        return ["images.scenes must be an object"]
    errors = []
    if not _small_int(c.get("max", 2), 0, 6):
        errors.append("images.scenes.max must be an integer from 0 to 6")
    per = c.get("per_category", {})
    if not isinstance(per, dict) or not all(isinstance(k, str) and _small_int(v, 0, 6) for k, v in per.items()):
        errors.append("images.scenes.per_category maps a category to an integer from 0 to 6")
    st = c.get("style", "")
    if not isinstance(st, str) or len(st) > SCENE_STYLE_MAX or not SCENE_TEXT_RE.match(st):
        errors.append("images.scenes.style is at most %d printable ASCII characters (English), without \" \\ ` or a "
                      "line break" % SCENE_STYLE_MAX)
    if not _small_int(c.get("wait_minutes", 30), 5, 120):
        errors.append("images.scenes.wait_minutes must be an integer from 5 to 120")
    return errors + figure_errors_by_kind(cfg)["scene"]


def scene_label(cfg):
    """The AI label `{label}`: `words.scene`, else the source language's default, else None."""
    w = words(cfg).get("scene")
    if isinstance(w, str) and w.strip():
        return w
    return SCENE_LABELS.get(lang_tag(cfg))


def scene_template(cfg):
    t = figure(cfg).get("scene")
    return t if isinstance(t, str) and t.strip() else SCENE_FIGURE


def og_errors(root, cfg):
    """`images.og` problems ([] when fine or absent) — OG is off by config while any is there.
    Kept out of Config.validate (L4)."""
    o = (block(cfg) or {}).get("og")
    if o is None:
        return []
    if not isinstance(o, dict):
        return ["images.og must be an object"]
    errors = []
    pat = o.get("path", "{images}/{slug}/og.png")
    if not isinstance(pat, str) or pat.count("{slug}") != 1 or not pat.endswith(".png") or \
            any(h not in ("{images}", "{slug}") for h in re.findall(r"\{[^{}]*\}", pat)):
        errors.append("images.og.path takes {images} and {slug} (exactly once) and ends in .png")
    elif cfg.og_path("x") is None:
        errors.append("images.og.path must be a relative path outside .git/ and .claude/")
    if o.get("subtitle") not in (None, "description"):
        errors.append("images.og.subtitle is null or \"description\"")
    if not isinstance(o.get("fallback_first_image", True), bool):
        errors.append("images.og.fallback_first_image is true or false")
    t = o.get("command")
    if t is not None:
        errors += _og_command_errors(root, cfg, t)
    return errors


def _og_command_errors(root, cfg, t):
    from .shots import INLINE_FLAGS, SHORT_BUNDLE_RE, runner
    if not isinstance(t, list) or not t or not all(isinstance(x, str) and x for x in t):
        return ["images.og.command must be a non-empty array of strings (an argv — no shell)"]
    errors = []
    first = runner(t[0])
    if first:
        prog = os.path.basename(t[0]).lower()
        if prog in ("sh", "bash", "zsh", "dash", "ksh", "fish", "csh", "tcsh", "cmd", "cmd.exe", "powershell",
                    "pwsh", "env", "xargs", "eval", "exec") or re.match(r"^(bash|zsh)[0-9.]+$", prog):
            errors.append("images.og.command must not run a shell (%s)" % t[0])
        elif len(t) < 2 or "{" in t[1] or t[1].startswith("-") or os.path.isabs(t[1]) or ".." in t[1].split("/"):
            errors.append("images.og.command runs an interpreter: its second element must be a repo-relative script")
        elif not git_ok(root, "cat-file", "-e", "origin/%s:%s" % (cfg.base, t[1])):
            errors.append("images.og.command script %s is not tracked on origin/%s" % (t[1], cfg.base))
        else:
            base_blob = git(root, "rev-parse", "origin/%s:%s" % (cfg.base, t[1]), check=False).strip()
            if blob(root, t[1]) != base_blob:
                errors.append("images.og.command script %s differs from origin/%s — commit it to base first"
                              % (t[1], cfg.base))
    others = [x for x in t[1:] if runner(x)]
    if others:
        errors.append("images.og.command must not run a shell or an interpreter after the program (%s)" % ", ".join(others))
    flags = sorted({x for x in t if x in INLINE_FLAGS or SHORT_BUNDLE_RE.match(x)})
    if flags:
        errors.append("images.og.command must not pass inline code (%s)" % ", ".join(flags))
    if "{" in t[0]:
        errors.append("images.og.command's first element is the program — no placeholder there")
    for x in t:
        holes = re.findall(r"\{[^{}]*\}", x)
        bad = [h for h in holes if h not in OG_PLACEHOLDERS]
        if bad:
            errors.append("images.og.command has unknown placeholders: %s" % ", ".join(sorted(set(bad))))
        elif holes and x not in OG_PLACEHOLDERS:
            errors.append("images.og.command takes a placeholder only as a whole element (%s)" % x)
    return errors


# --- what is on: config alone (plan, stage pass) and with this machine (kinds) ------------------

def _category(root, cfg, slug):
    fm = _frontmatter(root, cfg.body_path(slug)) if slug else {}
    return fm.get("category")


def _frontmatter(root, rel, rev=None):
    from .validate import parse_frontmatter
    try:
        if rev:
            text = git(root, "show", "%s:%s" % (rev, rel))
        else:
            with open(os.path.join(root, rel), encoding="utf-8") as f:
                text = f.read()
    except (OSError, HeraldError):
        return {}
    return parse_frontmatter(text.replace("\r\n", "\n"))[0] or {}


def _rules(root):
    from .validate import load_rules
    return load_rules(root)


def diagram_off(cfg):
    """Why diagrams are off by config (None: on). Never looks at this machine's limner."""
    if not managed(cfg) or diagram_conf(cfg) is None:
        return "no-config"
    if not illustrator_on(cfg):
        return "no-illustrator"
    if figure_errors_by_kind(cfg)["diagram"] or limner.limner_errors(cfg):
        return "config"
    if lang_tag(cfg) not in LANGS:
        return "lang:%s" % lang_tag(cfg)
    return None


def external_limits(root, cfg, category):
    ext = _rules(root)["images"]["external"]
    per = ext.get("per_category") if isinstance(ext.get("per_category"), dict) else {}
    mx = per.get(category, ext.get("max")) if category is not None else ext.get("max")
    qcats = ext.get("quotation_categories") or []
    oc = og_conf(cfg)
    fallback = True if oc is None else oc["fallback_first_image"]
    quoting = category in qcats and not fallback and not figure_errors_by_kind(cfg)["quotation"]
    return {"max": mx if isinstance(mx, int) else 0, "quotation": quoting,
            "quotation_max": ext.get("quotation_max", 0), "quotation_min_chars": ext.get("quotation_min_chars", 0),
            "licenses": [x for x in ext.get("licenses") or [] if x in LICENSE_URLS], "rules": ext}


def external_off(root, cfg, category):
    if not managed(cfg) or not external_on(cfg):
        return "no-config"
    if not illustrator_on(cfg):
        return "no-illustrator"
    if cfg.translations():
        return "translations"
    if figure_errors_by_kind(cfg)["licensed"]:
        return "config"
    if external_limits(root, cfg, category)["max"] <= 0:
        return "category"
    return None


def scene_limit(cfg, category):
    c = scene_conf(cfg) or {}
    per = c.get("per_category") or {}
    mx = per.get(category, c.get("max", 2)) if category is not None else c.get("max", 2)
    return mx if _small_int(mx, 0, 6) else 0


def scene_off(root, cfg, category):
    """Why scenes are off by config (None: on) — never looks at this machine's limner (09 §2.1).
    `og-fallback`: a site that may use the first image as its SNS card while OG is off by config
    would show an AI picture without its label there (§2.10; no og block counts as falling back,
    as for quotations)."""
    if not managed(cfg) or scene_conf(cfg) is None:
        return "no-config"
    if not illustrator_on(cfg):
        return "no-illustrator"
    if cfg.translations():
        return "translations"
    if scene_errors(cfg) or limner.limner_errors(cfg):
        return "config"
    oc = og_conf(cfg)
    if (True if oc is None else oc["fallback_first_image"]) and not og_on(root, cfg):
        return "og-fallback"
    if scene_label(cfg) is None:
        return "label:%s" % lang_tag(cfg)
    if scene_limit(cfg, category) <= 0:
        return "category"
    return None


def og_on(root, cfg):
    """OG is on by config (§2.8.1): a block, no `og_errors`, and — for limner — a language it
    draws. plan and stage pass read only this; whether this machine can make it is `og`'s job."""
    o = og_conf(cfg)
    if o is None or og_errors(root, cfg):
        return False
    if o["command"] is None and (limner.limner_errors(cfg) or lang_tag(cfg) not in LANGS):
        return False
    return True


def allowed_exts(root, cfg, slug):
    img = cfg.image_dir(slug or "x")
    from .validate import ignored
    return [e for e in EXTERNAL_EXTS if not ignored(root, "%s/x.%s" % (img, e))]


def kinds(root, cfg, tid=None):
    """`HRD image kinds` — for prompts only (it reads this machine's limner and .gitignore)."""
    st, slug, cat = {}, None, None
    if tid:
        from .store import get_topic, load_state, load_topics
        try:
            st = load_state(root, tid)
        except HeraldError:
            st = {}
        slug = st.get("slug")
        cat = _category(root, cfg, slug) if slug else None
        if cat is None:
            try:
                cat = get_topic(load_topics(root), tid).get("category")
            except HeraldError:
                pass
    out = {"screenshot": {"ok": True}}
    why = diagram_off(cfg)
    if why is None:
        p = limner.probe(root, cfg)
        why = None if p["ok"] else ("config" if p["code"] == "config" else p["code"])
    out["diagram"] = {"ok": why is None, "why": why}
    why = external_off(root, cfg, cat)
    lim = external_limits(root, cfg, cat) if managed(cfg) else {"max": 0, "quotation": False, "quotation_max": 0}
    out["external"] = {"ok": why is None, "licensed": why is None, "quotation": why is None and lim["quotation"],
                       "max": lim["max"], "quotation_max": lim["quotation_max"] if lim["quotation"] else 0,
                       "exts": allowed_exts(root, cfg, slug) if why is None else [], "why": why}
    o = og_conf(cfg)
    og = {"ok": False, "by": None, "path": cfg.og_path(slug or "<slug>") if o else None, "why": None}
    if o is None:
        og["why"] = "no-config"
    elif not og_on(root, cfg):
        og["why"] = "config"
    elif o["command"] is not None:
        og.update(ok=True, by="repo")
    else:
        p = limner.probe(root, cfg)
        og.update(ok=p["ok"], by="limner", why=None if p["ok"] else p["code"])
    out["og"] = og
    why = scene_off(root, cfg, cat)
    if why is None:
        p = limner.gen_probe(root, cfg)
        why = None if p["ok"] else p["code"]
    out["scene"] = {"ok": why is None, "max": scene_limit(cfg, cat) if why is None else 0,
                    "sizes": list(SCENE_SIZES) if why is None else [], "why": why}
    return out


# --- manifest --------------------------------------------------------------------------------

def load_manifest(root, tid, rev=None):
    rel = manifest_rel(tid)
    if rev:
        if not git_ok(root, "cat-file", "-e", "%s:%s" % (rev, rel)):
            return None
        try:
            data = json.loads(git(root, "show", "%s:%s" % (rev, rel)))
        except ValueError as e:
            raise HeraldError("%s at %s is not valid JSON: %s" % (rel, rev, e))
    else:
        full = os.path.join(root, rel)
        if not os.path.isfile(full):
            return None
        try:
            with open(full, encoding="utf-8") as f:
                data = json.load(f)
        except ValueError as e:
            raise HeraldError("%s is not valid JSON: %s" % (rel, e))
    if data is None:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("images"), list):
        raise HeraldError('%s must be {"images": [...]}' % rel)
    return data


def _items(man):
    return [i for i in (man or {}).get("images") or [] if isinstance(i, dict)]


def item_key(it):
    """An external image's key: what it is (file, source) — polishing credit or alt never asks
    for a new fetch."""
    if it.get("kind") != "external":
        return None
    raw = json.dumps([it.get("file"), it.get("source_url")])
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def full_prompt(cfg, it):
    """The prompt limner gets: the item's prompt, the repo's style, then NO_TEXT (09 §2.2)."""
    style = (scene_conf(cfg) or {}).get("style")
    return " ".join([str(it.get("prompt") or "")] + ([style] if style else []) + [NO_TEXT])


def scene_key(cfg, it):
    """A scene's key: what limner is asked to draw (full prompt, size, seed, model) — not `file`
    (R3-3: renaming the file must not bring a rejected picture back), not alt or purpose."""
    w, h = SCENE_SIZES.get(it.get("size"), (None, None))
    raw = json.dumps([full_prompt(cfg, it), w, h, it.get("seed"), limner.GEN_MODEL])
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def rejected_scene_keys(st, iid=None):
    """Keys a review (`review_rejects`) or a human (`image_rejects` `job`) turned down — plan
    refuses a scene item with one of them (§2.7.2: the redo loop cannot return to the same picture)."""
    out = [r.get("key") for r in st.get("review_rejects") or [] if isinstance(r, dict) and
           (iid is None or r.get("id") == iid)]
    out += [r.get("job") for r in st.get("image_rejects") or [] if isinstance(r, dict) and r.get("job") and
            (iid is None or r.get("id") == iid)]
    return [k for k in out if k]


def scene_attempts(st, iid):
    """1 + the decisions that turned a picture of this place down (R2-1 — never ledger lines)."""
    return 1 + len(set(rejected_scene_keys(st, iid)))


def _read(root, rel, rev=None):
    try:
        if rev:
            return git(root, "show", "%s:%s" % (rev, rel))
        with open(os.path.join(root, rel), encoding="utf-8") as f:
            return f.read()
    except (OSError, HeraldError, UnicodeDecodeError):
        return None


def _body(root, cfg, slug, rev=None):
    return _read(root, cfg.body_path(slug), rev) or ""


def _candidates_section(root, tid):
    text = _read(root, _work_rel(tid, "research.md")) or ""
    m = re.search(r"(?m)^##[ \t]+Image candidates[ \t]*$", text)
    if not m:
        return ""
    nxt = re.search(r"(?m)^##[ \t]+(?!#)", text[m.end():])
    return text[m.end():m.end() + nxt.start()] if nxt else text[m.end():]


def _candidate_urls(section):
    """{"source_url": {image: values}, "page_url": {page: values}} — whole values of the
    candidate lines, compared key by key (review m4: never a substring of another URL)."""
    out = {"source_url": set(), "page_url": set()}
    for m in re.finditer(r"(?m)^[ \t]*[-*][ \t]*(image|page)[ \t]*:[ \t]*(\S+)[ \t]*$", section):
        out["source_url" if m.group(1) == "image" else "page_url"].add(m.group(2))
    return out


def research_claims(root, tid):
    """{claim id: withdrawn?} as `stage pass` reads claim lines."""
    from .store import _CLAIM_DEF_RE
    text = _read(root, _work_rel(tid, "research.md")) or ""
    out = {}
    for line in text.splitlines():
        m = _CLAIM_DEF_RE.match(line)
        if m:
            out["C%s" % m.group(1)] = bool(re.search(r"\bwithdrawn:", line, re.I))
    return out


def _body_chars(root, cfg, slug):
    from .validate import body_chars, parse_frontmatter
    rules = _rules(root)
    _, body = parse_frontmatter(_body(root, cfg, slug).replace("\r\n", "\n"))
    return body_chars(body, rules["length"].get("count", "nonspace"))


def check_value(v):
    return isinstance(v, str) and v.strip() and len(v) <= VALUE_MAX and not VALUE_BAD.search(v)


def cur_item(root, cfg, slug, it):
    """The item as it stands after `status --move`: `file` mapped onto the current image dir and
    `ref` rewritten the same way (implementation review M3 — the body references the new path,
    so an attribution built from the old `ref` would never be found)."""
    f = it.get("file")
    new = cur_path(root, cfg, slug, f) if f and slug else f
    if new == f:
        return it
    from .validate import resolve_image_ref
    out = dict(it, file=new)
    ref = it.get("ref") or ""
    for old in _old_slugs(root, slug):
        i = ref.rfind("/%s/" % old)
        if i >= 0:
            cand = ref[:i] + "/%s/" % slug + ref[i + len(old) + 2:]
            if resolve_image_ref(root, cfg.body_path(slug), cand) == new:
                out["ref"] = cand
                break
    return out


def snippet_text(cfg, it, orientation=None, root=None, slug=None):
    """The body text for one item: its `images.figure` template with the values filled in once
    (no value is read again as a placeholder). With `root` and `slug`, the item's paths follow a
    `status --move` first."""
    if root and slug:
        it = cur_item(root, cfg, slug, it)
    w = words(cfg)
    if it.get("kind") == "scene":  # the AI label always goes with the picture (P19)
        vals = {"ref": it.get("ref") or "", "alt": it.get("alt") or "", "label": scene_label(cfg) or ""}
        return re.sub(r"\{(ref|alt|label)\}", lambda m: vals[m.group(1)], scene_template(cfg))
    if it.get("kind") == "diagram":
        t = figure(cfg).get("diagram") or "![{alt}]({ref})"
        use = None
    else:
        use = it.get("use")
        t = figure(cfg).get(use)
        if not isinstance(t, str):
            raise HeraldError("images.figure.%s is not set" % use)
    ori = orientation or "landscape"
    omap = w.get("orientation") if isinstance(w.get("orientation"), dict) else {}
    vals = {"ref": it.get("ref") or "", "alt": it.get("alt") or "", "credit": it.get("credit") or "",
            "license": it.get("license") or "" if use == "licensed" else "",
            "license_url": LICENSE_URLS.get(it.get("license"), "") if use == "licensed" else "",
            "page_url": it.get("page_url") or "", "label": w.get(use) or WORDS.get(use, "") if use else "",
            "source": it.get("title") or w.get("source") or WORDS["source"],
            "orientation": omap.get(ori, ori)}
    return re.sub(r"\{(%s)\}" % "|".join(FIGURE_FIELDS), lambda m: vals[m.group(1)], t)


def check_manifest(root, cfg, tid, st, man):
    """(errors, warnings) — §2.10, every rule code can check without this machine's limner."""
    from .validate import ignored, image_refs, resolve_image_ref
    slug = st["slug"]
    img = cfg.image_dir(slug).rstrip("/") + "/"
    body_rel = cfg.body_path(slug)
    text = _body(root, cfg, slug)
    refs = image_refs(root, body_rel, text)
    errors, warnings = [], []
    items = _items(man)
    if len(items) != len((man or {}).get("images") or []):
        errors.append("every images[] entry must be an object")
    cat = _category(root, cfg, slug)
    d_off, x_off = diagram_off(cfg), external_off(root, cfg, cat)
    g_off = scene_off(root, cfg, cat) if any(i.get("kind") == "scene" for i in items) else None
    lim = external_limits(root, cfg, cat)
    exts_ok = allowed_exts(root, cfg, slug)
    claims = research_claims(root, tid)
    cands = _candidate_urls(_candidates_section(root, tid))
    rejected = {r.get("source_url") for r in st.get("image_rejects") or [] if isinstance(r, dict) and r.get("source_url")}
    rejected_keys = set(rejected_scene_keys(st))
    shot_files = set()
    try:
        from .shots import load_manifest as shot_manifest
        shot_files = {s.get("file") for s in (shot_manifest(root, tid) or {}).get("shots") or [] if isinstance(s, dict)}
    except HeraldError:
        pass
    og = cfg.og_path(slug) if og_conf(cfg) else None
    prev_items = ((st.get("images") or {}).get("items") or {})
    seen, files, srefs = set(), set(), set()
    n_ext = n_quote = n_scene = 0
    for i, it in enumerate(items):
        iid = it.get("id")
        where = iid if isinstance(iid, str) else "images[%d]" % i
        kind = it.get("kind")
        if kind not in ID_RES:
            errors.append("%s: kind must be diagram, external or scene" % where)
            continue
        if not isinstance(iid, str) or not ID_RES[kind].match(iid):
            pre = {"diagram": "d", "external": "e", "scene": "g"}[kind]
            errors.append("%s: a %s id is %s1..%s999" % (where, kind, pre, pre))
        elif iid in seen:
            errors.append("%s: duplicate id" % iid)
        seen.add(iid)
        if kind == "diagram" and d_off:
            errors.append("%s: diagrams are off here (%s)" % (where, d_off))
        if kind == "external" and x_off:
            errors.append("%s: external images are off here (%s)" % (where, x_off))
        if kind == "scene" and g_off:
            errors.append("%s: scene images are off here (%s) — leave that place out" % (where, g_off))
        f = it.get("file")
        if not isinstance(f, str) or not f.startswith(img) or "/" in f[len(img):] or ".." in f.split("/") or \
                not f[len(img):].startswith("%s-" % iid):
            errors.append("%s: file must be %s<id>-<what>.<ext>" % (where, img))
            continue
        if f in files or it.get("ref") in srefs:
            errors.append("%s: another image already uses this file or ref" % where)
        files.add(f)
        srefs.add(it.get("ref"))
        ext = f.rsplit(".", 1)[-1].lower() if "." in f else ""
        if kind in ("diagram", "scene") and ext != "png":
            errors.append("%s: a %s is published as .png" % (where, kind))
        if kind == "external" and ext not in exts_ok:
            errors.append("%s: .%s is not an extension this repo publishes (gitignored or unsupported) — use one of %s"
                          % (where, ext, ", ".join(exts_ok) or "none"))
        if ignored(root, f):
            errors.append("%s: %s is gitignored — it would deploy from this machine only" % (where, f))
        if on_base(root, cfg, f):
            errors.append("%s: %s already exists on %s — use a new file name" % (where, f, cfg.base))
        if f == og or f in shot_files:
            errors.append("%s: %s is the OG file or a screenshot's file" % (where, f))
        ref = it.get("ref")
        if not isinstance(ref, str) or resolve_image_ref(root, body_rel, ref) != f:
            errors.append("%s: ref %r does not resolve to %s the way the gate reads images" % (where, ref, f))
        elif refs.count(f) != 1:
            errors.append("%s: the article must reference %s exactly once (found %d)" % (where, ref, refs.count(f)))
        for k in ("alt", "purpose"):
            if not check_value(it.get(k)) if k == "alt" else not (isinstance(it.get(k), str) and it.get(k).strip()):
                errors.append("%s: %s must be set (alt: at most %d characters, no < > \" [ ] \\ or line break)"
                              % (where, k, VALUE_MAX))
        if kind == "diagram":
            errors += _diagram_errors(root, tid, where, it, claims)
            continue
        if kind == "scene":
            n_scene += 1
            errors += _scene_errors(cfg, where, it, rejected_keys)
            if not g_off and scene_label(cfg):
                c = text.count(snippet_text(cfg, it, None, root, slug))
                if c != 1:
                    errors.append("%s: the picture with its AI label (`HRD image snippet --topic %s --id %s`) must be in "
                                  "the article verbatim exactly once (found %d)" % (where, tid, iid, c))
            continue
        n_ext += 1
        errors += _external_errors(root, cfg, where, it, lim, cands, rejected)
        if it.get("use") == "quotation":
            n_quote += 1
        rec = prev_items.get(iid) or {}
        if rec.get("status") in ("fetched", "ready") and rec.get("key") == item_key(it) and \
                isinstance(it.get("use"), str) and figure(cfg).get(it.get("use")):
            sn = snippet_text(cfg, it, rec.get("orientation"), root, slug)
            c = text.count(sn)
            if c != 1:
                errors.append("%s: the attribution (`HRD image snippet --topic %s --id %s`) must be in the article "
                              "verbatim exactly once (found %d)" % (where, tid, iid, c))
    if n_ext and n_ext > lim["max"]:
        errors.append("%d external images — this category allows %d" % (n_ext, lim["max"]))
    if n_scene and not g_off and n_scene > scene_limit(cfg, cat):
        errors.append("%d scene images — this category allows %d" % (n_scene, scene_limit(cfg, cat)))
    if n_quote:
        if n_quote > (lim["quotation_max"] or 0):
            errors.append("%d quotations — at most %s" % (n_quote, lim["quotation_max"]))
        chars = _body_chars(root, cfg, slug)
        if chars < (lim["quotation_min_chars"] or 0) * n_quote:
            errors.append("the article is %d characters — quotations need %s per quoted image (the text leads)"
                          % (chars, lim["quotation_min_chars"]))
    mt = _rules(root)["images"].get("max_total")
    if isinstance(mt, int) and not isinstance(mt, bool):
        local = [r for r in refs if r != og]
        if len(local) > mt:
            errors.append("%d images in the article — at most %d (images.max_total)" % (len(local), mt))
    if managed(cfg):
        known = files | shot_files | {og}
        added = [p for p in git(root, "ls-files", "--others", "--exclude-standard", "--", cfg.image_dir(slug),
                                check=False).splitlines() if p]
        loose = sorted(p for p in added if p not in known)
        if loose:
            warnings.append("unmanaged images: %s — they go out under the 0.14.0 rule (the `images` exclusion a human "
                            "may accept); the text in them is not verified" % ", ".join(loose))
    return errors, warnings


def _diagram_errors(root, tid, where, it, claims):
    errors = []
    svg = svg_rel(tid, it.get("id"))
    if not os.path.isfile(os.path.join(root, svg)):
        return ["%s: the SVG source %s is missing" % (where, svg)]
    try:
        got = svg_texts(os.path.join(root, svg))
    except HeraldError as e:
        return ["%s: %s" % (where, e)]
    texts = it.get("texts")
    if not isinstance(texts, list) or not all(isinstance(t, dict) and isinstance(t.get("text"), str) for t in texts):
        return ["%s: texts must list [{\"text\", \"claims\"}] — copy `HRD image texts --topic %s --id %s --source svg`"
                % (where, tid, it.get("id"))]
    if Counter(t["text"] for t in texts) != Counter(got):
        errors.append("%s: texts differ from the text in %s — copy `HRD image texts --source svg` exactly" % (where, svg))
    for t in texts:
        cl = t.get("claims")
        if not isinstance(cl, list) or not all(isinstance(c, str) for c in cl):
            errors.append("%s: texts[].claims must be a list of claim ids ([] for a label)" % where)
            continue
        for c in cl:
            if c not in claims:
                errors.append("%s: %r maps to %s, which research.md does not have" % (where, t["text"][:40], c))
            elif claims[c]:
                errors.append("%s: %r maps to %s, which is withdrawn" % (where, t["text"][:40], c))
    return errors


def _scene_errors(cfg, where, it, rejected_keys):
    errors = []
    if "refs" in it:
        errors.append("%s: a scene takes no refs (0.18 draws from the prompt alone)" % where)
    if it.get("size") not in SCENE_SIZES:
        errors.append("%s: size must be one of %s" % (where, ", ".join(SCENE_SIZES)))
    if not _small_int(it.get("seed"), 0, SEED_MAX):
        errors.append("%s: seed must be an integer from 0 to %d" % (where, SEED_MAX))
    pr = it.get("prompt")
    if not isinstance(pr, str) or not pr.strip() or len(pr) > SCENE_PROMPT_MAX or not SCENE_TEXT_RE.match(pr):
        errors.append("%s: prompt is English, 1–%d printable ASCII characters, without \" \\ ` or a line break (a "
                      "Japanese or Korean word makes the model draw letters)" % (where, SCENE_PROMPT_MAX))
    elif scene_key(cfg, it) in rejected_keys:
        errors.append("%s: this prompt, seed and size were turned down before (review or a human) — change the seed "
                      "or the prompt" % where)
    return errors


def _external_errors(root, cfg, where, it, lim, cands, rejected):
    errors = []
    use = it.get("use")
    if use not in ("licensed", "quotation"):
        return ["%s: use must be licensed or quotation" % where]
    for k in ("source_url", "page_url"):
        if not public_url(it.get(k)):
            errors.append("%s: %s must be a public https URL" % (where, k))
        elif it[k] not in cands[k]:
            errors.append("%s: %s is not in research.md ## Image candidates — copy the candidate as written" % (where, k))
    if not check_value(it.get("credit")):
        errors.append("%s: credit must be set (at most %d characters, no < > \" [ ] \\ or line break)" % (where, VALUE_MAX))
    if it.get("title") is not None and not check_value(it.get("title")):
        errors.append("%s: title, when given, follows the alt rules" % where)
    if use == "licensed":
        if it.get("license") not in lim["licenses"]:
            errors.append("%s: license %r is not one this repo allows (%s)" % (where, it.get("license"),
                                                                                ", ".join(lim["licenses"])))
    else:
        if not lim["quotation"]:
            errors.append("%s: quotations are not allowed for this category (gate-rules images.external."
                          "quotation_categories, and a site that never falls back to the first image — og."
                          "fallback_first_image false)" % where)
        if it.get("license"):
            errors.append("%s: a quotation has no license" % where)
    if it.get("source_url") in rejected:
        errors.append("%s: %s was rejected by a human — use another candidate" % (where, it.get("source_url")))
    return errors


def managed_files(root, cfg, tid, st):
    """Files Herald manages for this topic beyond screenshots: images.json files, recorded image
    files and the OG path (the 0.15.0 "new images the article does not reference" warning skips them)."""
    out = set(((st or {}).get("images") or {}).get("files") or {})
    try:
        out |= {i.get("file") for i in _items(load_manifest(root, tid))}
    except HeraldError:
        pass
    if og_conf(cfg) and (st or {}).get("slug"):
        out.add(cfg.og_path(st["slug"]))
    return out


# --- SVG rules and text (§2.5.3) ---------------------------------------------------------------

def svg_texts(path_or_bytes):
    """The text a diagram draws, in document order (each `<text>` one value, whitespace folded).
    Refuses what Herald never passes to limner: DTDs and entities (before any parser), script,
    foreign objects, embedded or linked images, links, style sheets, event handlers, external
    references, hidden text (title/desc/metadata), and a root without a viewBox."""
    import xml.etree.ElementTree as ET
    if isinstance(path_or_bytes, (bytes, bytearray)):
        raw = bytes(path_or_bytes)
    else:
        if os.path.getsize(path_or_bytes) > SVG_MAX:
            raise HeraldError("the SVG is larger than 1 MB")
        with open(path_or_bytes, "rb") as f:
            raw = f.read()
    if len(raw) > SVG_MAX:
        raise HeraldError("the SVG is larger than 1 MB")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HeraldError("the SVG is not UTF-8")
    if re.search(r"<!DOCTYPE|<!ENTITY", text, re.I):
        raise HeraldError("the SVG has a DOCTYPE or ENTITY — not allowed")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise HeraldError("the SVG does not parse: %s" % e)
    if root.tag != "{%s}svg" % SVG_NS:
        raise HeraldError("the root element must be <svg xmlns=\"%s\">" % SVG_NS)
    if not root.get("viewBox"):
        raise HeraldError("the <svg> root needs a viewBox")
    out = []
    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1] if isinstance(el.tag, str) else ""
        if tag in SVG_BANNED:
            raise HeraldError("<%s> is not allowed in a diagram" % tag)
        for k, v in el.attrib.items():
            name = k.rsplit("}", 1)[-1].lower()
            if name.startswith("on"):
                raise HeraldError("event attribute %s is not allowed" % name)
            if name == "href":
                raise HeraldError("href is not allowed (no links or external references)")
            if re.search(r"url\(\s*(?!['\"]?#)", v, re.I):
                raise HeraldError("url(...) may only point inside the SVG (url(#id))")
            if name == "font-family" and v.strip().strip("'\"").lower() not in ("sans-serif", "monospace"):
                raise HeraldError("font-family must be sans-serif or monospace (limner sets the font)")
        if tag == "text":
            v = re.sub(r"\s+", " ", "".join(el.itertext())).strip()
            if v:
                out.append(v)
    return out


# --- diagram render records (§2.7.2) -----------------------------------------------------------

def _valid_render(rec):
    return isinstance(rec, dict) and all(isinstance(rec.get(k), str) and rec.get(k) for k in RENDER_FIELDS) and \
        isinstance(rec.get("width"), int) and isinstance(rec.get("texts"), list) and \
        all(isinstance(t, str) for t in rec["texts"])


def read_renders(root, tid, rev=None):
    """(lines, dropped): a line that is no whole record does not exist — the file only lets
    things pass, so dropping a line only makes the judgement stricter."""
    raw = _read(root, renders_rel(tid), rev)
    if raw is None:
        return [], 0
    out, dropped = [], 0
    for line in raw.split("\n"):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except (ValueError, RecursionError):
            dropped += 1
            continue
        if _valid_render(rec):
            out.append(rec)
        else:
            dropped += 1
    return out, dropped


def _topic_states(root, rev=None):
    """[(tid, state)] of every work dir, in the working tree or at `rev`."""
    out = []
    if rev:
        for p in git(root, "ls-tree", "-r", "--name-only", rev, "--", ".claude/herald/work", check=False).splitlines():
            if p.endswith("/state.json") and p.count("/") == 4:
                txt = _read(root, p, rev)
                try:
                    st = json.loads(txt) if txt else None
                except ValueError:
                    st = None
                if isinstance(st, dict):
                    out.append((p.split("/")[-2], st))
        return out
    work = os.path.join(root, ".claude/herald/work")
    for tid in sorted(os.listdir(work)) if os.path.isdir(work) else []:
        try:
            st = read_json(os.path.join(work, tid, "state.json"))
        except ValueError:
            st = None
        if isinstance(st, dict):
            out.append((tid, st))
    return out


def _old_slugs(root, slug):
    from .store import load_published
    art = next((a for a in load_published(root).get("articles") or [] if a.get("slug") == slug), None) or {}
    return [m["slug"] for m in art.get("moved_from") or [] if isinstance(m, dict) and m.get("slug")]


def cur_path(root, cfg, slug, f):
    """A recorded path under an old slug (`status --move`) mapped onto the current image dir."""
    from .integrity import moved_image_path
    return moved_image_path(cfg, slug, f, _old_slugs(root, slug)) if f else f


def slug_renders(root, cfg, slug, rev=None):
    """Every render line of every topic of this slug (refresh topics, moved slugs included)."""
    olds = set(_old_slugs(root, slug)) | {slug}
    lines, dropped = [], 0
    for tid, st in _topic_states(root, rev):
        if st.get("slug") in olds:
            ls, d = read_renders(root, tid, rev)
            lines += ls
            dropped += d
    return lines, dropped


def find_render(lines, h):
    if not h:
        return None
    return next((r for r in reversed(lines) if r.get("png_blob") == h[0] or r.get("png_sha256") == h[1]), None)


def _rev_hashes(root, rev, rel):
    """(blob, sha256) of `rel` at `rev`, or of the working-tree file."""
    if not rev:
        return file_hashes(root, rel)
    b = git(root, "rev-parse", "-q", "--verify", "%s:%s" % (rev, rel), check=False).strip()
    if not b:
        return None
    import subprocess
    p = subprocess.run(["git", "cat-file", "--filters", "%s:%s" % (rev, rel)], cwd=root, capture_output=True)
    return b, hashlib.sha256(p.stdout).hexdigest() if p.returncode == 0 else None


def _svg_sha(root, tid, iid, rev=None):
    rel = svg_rel(tid, iid)
    if rev:
        import subprocess
        p = subprocess.run(["git", "show", "%s:%s" % (rev, rel)], cwd=root, capture_output=True)
        return hashlib.sha256(p.stdout).hexdigest() if p.returncode == 0 else None
    full = os.path.join(root, rel)
    if not os.path.isfile(full):
        return None
    with open(full, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


# --- item state (P13) -------------------------------------------------------------------------

def diagram_state(root, cfg, tid, st, it, lines, strict=True, rev=None):
    """(`ready`|`pending`, E): ready when the PNG's content is in a render record E; `strict`
    (draft, first verify) also wants E to be the current SVG, settings and manifest texts."""
    f = cur_path(root, cfg, st["slug"], it.get("file"))
    E = find_render(lines, _rev_hashes(root, rev, f))
    if not E:
        return "pending", None
    if strict:
        conf = diagram_conf(cfg) or {}
        texts = [t.get("text") for t in it.get("texts") or [] if isinstance(t, dict)]
        if E.get("svg_sha256") != _svg_sha(root, tid, it.get("id"), rev) or E.get("width") != conf.get("width") or \
                str(E.get("background")).lower() != str(conf.get("background")).lower() or \
                Counter(E.get("texts")) != Counter(texts):
            return "pending", E
    return "ready", E


def external_state(root, tid, it, led, rev=None, path=None):
    """`ready` (logged for this item and confirmed), `fetched` (logged only) or `pending`.
    `path`: where the file is now (after `status --move`); the key stays the manifest's."""
    h = _rev_hashes(root, rev, path or it.get("file"))
    key = item_key(it)
    if not h or not led.fetch_line(h, tid, it.get("id"), key):
        return "pending"
    # a human's line of this content, or an agent's line of this very item (11-ship-consent.md P25)
    return "ready" if led.confirmed_for(h, tid, it.get("id"), key) else "fetched"


def fail_closed(tid, iid, rec, led, it=None):
    """§2.7.4: a fetch time recorded, but no fetch line for the item on this machine."""
    if not rec or not rec.get("fetched_at") or led.fetch_lines(tid, iid, rec.get("key")):
        return None
    return ("%s: no fetch record on this machine — `HRD image reject --topic %s --id %s --refetch --reason 'refetch on "
            "this machine'`, then `HRD image fetch` and `HRD image confirm` (unattended: hold needs-human, note "
            "`tooling: images fetch record missing %s`)" % (iid, tid, iid, iid))


def scene_state(root, cfg, tid, it, led, rev=None, path=None):
    """`ready` (a generation line of this item and key for this content, and a human confirmed
    it), `generated` (the line only) or `pending` (09 §2.5)."""
    h = _rev_hashes(root, rev, path or it.get("file"))
    key = scene_key(cfg, it)
    if not h or not led.gen_line(h, tid, it.get("id"), key):
        return "pending"
    return "ready" if led.confirmed_for(h, tid, it.get("id"), key) else "generated"


def scene_fail_closed(tid, iid, rec, led):
    """§2.5 (v4 R3-2): the state says this topic generated a picture here (`generated_blob`), but
    this machine's ledger has no line of that very content — another machine made it."""
    b = (rec or {}).get("generated_blob")
    if not b or led.gen_has(tid, iid, rec.get("key"), b):
        return None
    return ("%s: no generation record of this picture on this machine — resume on the machine that generated it, or "
            "`HRD image reject --topic %s --id %s --regenerate --reason 'regenerate on this machine'`, then `HRD image "
            "generate` and `HRD image confirm` (unattended: hold needs-human, note `tooling: images generation record "
            "missing %s`)" % (iid, tid, iid, iid))


# --- plan ---------------------------------------------------------------------------------------

def _hash(root, rel):
    from .hashing import file_hash
    return file_hash(root, rel)


def _og_text(root, cfg, st):
    """`fresh|stale|off` for plan's output."""
    if not og_on(root, cfg):
        return "off"
    rec = ((st.get("images") or {}).get("og")) or {}
    try:
        key = og_key(root, cfg, st)
    except HeraldError:
        return "stale"
    if rec.get("key") != key:
        return "stale"
    return "off" if rec.get("status") == "off" else "fresh"


def plan(root, cfg, tid, check_only=False):
    from .store import load_state, save_state
    st = load_state(root, tid)
    slug = st.get("slug")
    if not slug:
        raise HeraldError("no slug yet for %s" % tid)
    man = load_manifest(root, tid)
    out = {"errors": [], "warnings": [], "pending": {"render": [], "fetch": [], "generate": [], "confirm": []},
           "og": _og_text(root, cfg, st)}
    rec = st.get("images") or {}
    if not _items(man) and not (man or {}).get("images"):
        if check_only or not rec:
            return out
        files = dict(rec.get("files") or {})
        st["images"] = {"manifest": None, "body": None, "awaiting": False, "files": files, "items": {},
                        "og": rec.get("og")}
        if rec.get("gen"):
            st["images"]["gen"] = rec["gen"]
        save_state(root, tid, st)
        out["moved"] = move_to_removed(root, tid, [f for f in files if not on_base(root, cfg, f)], "unlisted",
                                       area="images")
        return out
    errors, warnings = check_manifest(root, cfg, tid, st, man)
    out["errors"], out["warnings"] = errors, warnings
    if errors or check_only:
        return out
    led = Ledger(root)
    items = _items(man)
    led.check(sum(1 for it in items if it.get("kind") in ("external", "scene") and
                  os.path.isfile(os.path.join(root, it["file"]))), warnings)
    lines, dropped = slug_renders(root, cfg, slug)
    if dropped:
        warnings.append("diagram render records: %d damaged line(s) ignored" % dropped)
    prev = rec.get("items") or {}
    files = dict(rec.get("files") or {})
    current = {it["file"] for it in items}
    to_move = [f for f in files if f not in current]
    new = {}
    for it in items:
        iid, f = it["id"], it["file"]
        files[f] = {"kind": it["kind"], "use": it.get("use") if it["kind"] == "external" else None}
        h = file_hashes(root, f)
        if it["kind"] == "diagram":
            status, _ = diagram_state(root, cfg, tid, st, it, lines)
            if h and not find_render(lines, h):
                to_move.append(f)  # not a PNG Herald rendered (a hand-drawn or edited one): P9
            new[iid] = {"kind": "diagram", "file": f, "status": status}
            if status == "pending":
                out["pending"]["render"].append(iid)
            continue
        if it["kind"] == "scene":
            key = scene_key(cfg, it)
            p = prev.get(iid) or {}
            if h and not led.gen_line(h, tid, iid, key):
                to_move.append(f)  # not Herald's copy of what limner made for this very item and key
            status = scene_state(root, cfg, tid, it, led)
            r = {"kind": "scene", "file": f, "key": key, "status": status}
            if p.get("key") == key:  # a new key drops the old picture's marks (R3-2)
                for k in ("generated_at", "generated_blob", "reviewed", "review_note", "regenerated"):
                    if p.get(k) is not None:
                        r[k] = p[k]
                if status == "ready":
                    r["sha"] = p.get("sha") or blob(root, f)
                    if led.confirmed_by(h, tid, iid, key) == "agent":
                        r["confirmed_by"] = "agent"  # who confirmed follows the ledger (11 §2.2 5)
            new[iid] = r
            if status == "pending":
                out["pending"]["generate"].append(iid)
            elif status == "generated":
                out["pending"]["confirm"].append(iid)
            continue
        key = item_key(it)
        p = prev.get(iid) or {}
        if h and not led.fetch_line(h, tid, iid, key):
            to_move.append(f)  # not Herald's fetch of this very item
        status = external_state(root, tid, it, led)
        r = {"kind": "external", "use": it.get("use"), "file": f, "key": key, "status": status}
        if p.get("key") == key:
            for k in ("fetched_at", "orientation", "width", "height", "reviewed", "review_note"):
                if p.get(k) is not None:
                    r[k] = p[k]
            if r.get("reviewed") and (not h or r["reviewed"] != h[0]):
                r.pop("reviewed")  # a review follows the bytes it looked at (11 §9 m3)
            if status == "ready":
                r["sha"] = p.get("sha") or blob(root, f)
                if led.confirmed_by(h, tid, iid, key) == "agent":
                    r["confirmed_by"] = "agent"
        elif status != "pending":
            r["status"] = "pending"  # another source at the same file: the old fetch moves away
            to_move.append(f)
        new[iid] = r
        if r["status"] == "pending":
            out["pending"]["fetch"].append(iid)
        elif r["status"] == "fetched":
            out["pending"]["confirm"].append(iid)
    st["images"] = {"manifest": _hash(root, manifest_rel(tid)), "body": _hash(root, cfg.body_path(slug)),
                    "awaiting": True, "files": files, "items": new, "og": rec.get("og")}
    if rec.get("gen"):
        st["images"]["gen"] = rec["gen"]  # the scene run this topic follows (§2.4.3)
    save_state(root, tid, st)
    out["moved"] = move_to_removed(root, tid, [f for f in dict.fromkeys(to_move) if not on_base(root, cfg, f)],
                                   "unlisted", area="images")
    for it in items:  # a moved file leaves its item pending
        if it["file"] in out["moved"] and new[it["id"]]["status"] != "pending":
            new[it["id"]]["status"] = "pending"
            new[it["id"]].pop("sha", None)
    if out["moved"]:
        save_state(root, tid, st)
    out["og"] = _og_text(root, cfg, st)
    return out


def _plan_items(root, tid, ids=None, kind=None):
    man = load_manifest(root, tid)
    items = [i for i in _items(man) if (kind is None or i.get("kind") == kind)]
    if ids:
        want = [x.strip() for x in (ids if isinstance(ids, list) else str(ids).split(",")) if x.strip()]
        by = {i.get("id"): i for i in items}
        missing = [x for x in want if x not in by]
        if missing:
            raise HeraldError("not %s items in images.json: %s" % (kind or "any", ", ".join(missing)))
        return [by[x] for x in want]
    return items


def _on_branch(root, tid, st):
    from .store import branch_name
    head = git(root, "rev-parse", "--abbrev-ref", "HEAD", check=False).strip()
    return bool(st.get("slug")) and head == branch_name(tid, st["slug"])


# --- render (§2.5.2) ----------------------------------------------------------------------------

def _diagram_item_errors(root, cfg, tid, st, it):
    img = cfg.image_dir(st["slug"]).rstrip("/") + "/"
    f, iid = it.get("file"), it.get("id")
    from .validate import ignored
    if not isinstance(iid, str) or not ID_RES["diagram"].match(iid):
        return "id must be d1..d999"
    if not isinstance(f, str) or not f.startswith(img) or "/" in f[len(img):] or ".." in f.split("/") or \
            not f.endswith(".png"):
        return "file must be a .png directly under %s" % img
    if ignored(root, f) or on_base(root, cfg, f):
        return "%s is gitignored or already on %s" % (f, cfg.base)
    return None


def pushed_change(root, cfg, tid, st, it, lines):
    """ship §5 (§2.7.2 table): a human changed the diagram — its PNG is no recorded render, or
    its SVG is not the one that render drew. Settings and manifest text are not looked at
    (implementation review M2: a settings change alone never asks for limner after a push)."""
    E = find_render(lines, file_hashes(root, cur_path(root, cfg, st["slug"], it.get("file"))))
    return E is None or E.get("svg_sha256") != _svg_sha(root, tid, it.get("id"))


def render(root, cfg, tid, ids=None, after_push=False):
    """`HRD image render`. Without `--id` it renders what draft needs (`after_push`: only what
    a human changed in a pushed PR — ship §5)."""
    from .store import load_state, save_state
    st = load_state(root, tid)
    if not _on_branch(root, tid, st):
        raise HeraldError("render runs on this topic's herald branch only (never on base — a published diagram "
                          "is judged by its render record, §2.7.2)")
    why = diagram_off(cfg)
    if why:
        raise HeraldError("diagrams are off here (%s)" % why)
    conf = diagram_conf(cfg)
    items = _plan_items(root, tid, ids, kind="diagram")
    lines, _ = slug_renders(root, cfg, st["slug"])
    out = {"rendered": [], "failed": [], "remaining": [], "skipped": []}
    todo = []
    for it in items:
        if not ids and (not pushed_change(root, cfg, tid, st, it, lines) if after_push else
                        diagram_state(root, cfg, tid, st, it, lines)[0] == "ready"):
            out["skipped"].append(it.get("id"))
        else:
            todo.append(it)
    if not todo:
        return out
    p = limner.probe(root, cfg)
    if not p["ok"]:
        code = "limner:config" if p["code"] == "config" else p["code"]
        out["failed"] = [{"id": it.get("id"), "code": code, "class": "env",
                          "message": "; ".join(p.get("errors") or []) or None} for it in todo]
        return out
    t0 = time.monotonic()  # the budget starts after the probe (§2.4.2)
    sd = limner.state_dir_abs(root, cfg)
    for it in todo:
        iid = it.get("id")
        if BUDGET - (time.monotonic() - t0) < RENDER_START_MIN:
            out["remaining"].append(iid)
            continue
        bad = _diagram_item_errors(root, cfg, tid, st, it)
        if bad:
            out["failed"].append({"id": iid, "code": "input", "class": "content", "message": bad})
            continue
        svg = svg_rel(tid, iid)
        try:
            # one read: the bytes limner draws are the bytes the record's sha and text come from
            # (implementation review m7 — the source may change while limner runs)
            with open(os.path.join(root, svg), "rb") as fh:
                raw = fh.read()
            drawn = svg_texts(raw)
        except (HeraldError, OSError) as e:
            out["failed"].append({"id": iid, "code": "svg", "class": "content", "message": str(e)})
            continue
        svg_sha = hashlib.sha256(raw).hexdigest()
        snap = os.path.join(sd, "herald-render", "%s-%s.svg" % (iid, limner._stamp()))
        os.makedirs(os.path.dirname(snap), exist_ok=True)
        with open(snap, "wb") as fh:
            fh.write(raw)
        f = it["file"]
        h = file_hashes(root, f)
        if h and not find_render(lines, h):
            move_to_removed(root, tid, [f], "replaced", area="images")  # not Herald's render: kept (P9)
        os.makedirs(os.path.dirname(os.path.join(root, f)), exist_ok=True)
        try:
            res = limner.run(root, cfg, ["rasterize"], [
                ("--svg", snap), ("--root", os.path.realpath(root)),
                ("--state-dir", sd), ("--out", os.path.join(os.path.realpath(root), f)),
                ("--width", conf["width"]), ("--background", conf["background"])])
        finally:
            try:
                os.remove(snap)
            except OSError:
                pass
        problems, failure = limner.classify(res)
        if failure:
            out["failed"].append(dict(failure, id=iid))
            continue
        if problems:
            out["rendered"].append({"id": iid, "file": f, "problems": problems})
            continue
        h = file_hashes(root, f)
        if not h or (res["obj"] or {}).get("out_sha256") != h[1]:
            out["failed"].append({"id": iid, "code": "record-mismatch", "class": "env",
                                  "message": "limner's out_sha256 is not the file Herald reads"})
            continue
        rec = {"id": iid, "svg_sha256": svg_sha, "width": conf["width"], "background": conf["background"],
               "png_blob": h[0], "png_sha256": h[1], "texts": drawn,
               "limner": (limner.probe(root, cfg) or {}).get("limner"), "at": now_iso()}
        ledger_append(os.path.join(root, renders_rel(tid)), rec)
        lines.append(rec)
        out["rendered"].append({"id": iid, "file": f, "problems": []})
    rec = st.get("images")
    if rec and isinstance(rec.get("items"), dict):  # the cache only; evidence is the record
        for r in out["rendered"]:
            if not r["problems"] and r["id"] in rec["items"]:
                rec["items"][r["id"]]["status"] = "ready"
        save_state(root, tid, st)
    return out


def texts(root, cfg, tid, iid=None, source="drawn"):
    from .store import load_state
    st = load_state(root, tid)
    items = _plan_items(root, tid, iid, kind="diagram")
    out = {"texts": [], "errors": []}
    lines = slug_renders(root, cfg, st["slug"])[0] if source == "drawn" else []
    for it in items:
        if source == "svg":
            try:
                out["texts"] += [{"id": it["id"], "text": t} for t in svg_texts(os.path.join(root, svg_rel(tid, it["id"])))]
            except (HeraldError, OSError) as e:
                out["errors"].append("%s: %s" % (it.get("id"), e))
            continue
        E = find_render(lines, file_hashes(root, cur_path(root, cfg, st["slug"], it.get("file"))))
        if not E:
            out["errors"].append("%s: its PNG is no render Herald recorded — `HRD image render --topic %s --id %s`"
                                 % (it.get("id"), tid, it.get("id")))
            continue
        out["texts"] += [{"id": it["id"], "text": t} for t in E["texts"]]
    return out


# --- fetch (§2.6.3) -----------------------------------------------------------------------------

class PinnedHTTPS(http.client.HTTPSConnection):
    """HTTPS to the address Herald checked, never resolved again (no DNS rebinding); the
    certificate is still checked against the host name."""

    def __init__(self, host, ips, timeout):
        super().__init__(host, 443, timeout=timeout, context=ssl.create_default_context())
        self._ips = [ips] if isinstance(ips, str) else list(ips)

    def connect(self):
        # every address was checked; try them in the resolver's order, so a host whose first
        # answer is unreachable here (IPv6 without a route) still works (review m2)
        err = None
        for ip in self._ips:
            try:
                sock = socket.create_connection((ip, 443), self.timeout)
            except OSError as e:
                err = e
                continue
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
            return
        raise err or OSError("no address")


CONNECTION = PinnedHTTPS  # tests replace it with a fake server


def _resolve(host):
    """Every address `host` resolves to, in the resolver's order (deduplicated), within the DNS
    time limit."""
    import threading
    from .shots import DNS_TIMEOUT
    box = {}

    def work():
        try:
            box["addrs"] = list(dict.fromkeys(ai[4][0] for ai in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)))
        except Exception as e:  # noqa: BLE001
            box["err"] = e
    t = threading.Thread(target=work, daemon=True)
    t.start()
    t.join(DNS_TIMEOUT)
    if t.is_alive() or "err" in box or not box.get("addrs"):
        raise OSError("%s did not resolve" % host)
    return box["addrs"]


def _within(deadline, conn, fn):
    """fn() — connecting, TLS and the response headers — under the item's wall-clock deadline;
    a server that drips its headers is cut off there (review m1), the socket closed."""
    import threading
    box = {}

    def work():
        try:
            box["v"] = fn()
        except BaseException as e:  # noqa: BLE001 — re-raised in the caller's thread
            box["e"] = e
    t = threading.Thread(target=work, daemon=True)
    t.start()
    t.join(max(0.0, deadline - time.monotonic()))
    if t.is_alive():
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass
        raise _Fail("timeout")
    if "e" in box:
        raise box["e"]
    return box["v"]


class _Fail(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def fetch_class(code):
    if code in ENV_FETCH or code in ("http-408", "http-429") or (code.startswith("http-5")):
        return "env"
    return "content"


def _get(url, max_bytes, deadline, user_agent):
    """(bytes, content type, final url) or _Fail(code)."""
    hops = 0
    while True:
        if not public_url(url):
            raise _Fail("redirect-refused" if hops else "url-not-public")
        parts = urllib.parse.urlsplit(url)
        if (parts.port or 443) != 443:
            raise _Fail("redirect-refused" if hops else "url-not-public")
        host = parts.hostname
        try:
            addrs = _resolve(host)
        except Exception:  # noqa: BLE001
            raise _Fail("dns-fail")
        for a in addrs:
            try:
                ok = ipaddress.ip_address(str(a).split("%")[0]).is_global
            except ValueError:
                ok = False
            if not ok:
                raise _Fail("redirect-refused" if hops else "dns-private")
        if time.monotonic() > deadline:
            raise _Fail("timeout")
        conn = CONNECTION(host, addrs, min(SOCK_TIMEOUT, max(0.1, deadline - time.monotonic())))
        try:
            path = parts.path or "/"
            if parts.query:
                path += "?" + parts.query

            def head():
                conn.request("GET", path, headers={"User-Agent": user_agent,
                                                   "Accept": "image/png,image/jpeg,image/webp",
                                                   "Accept-Encoding": "identity"})
                return conn.getresponse()
            resp = _within(deadline, conn, head)
            status = resp.status
            if status in (301, 302, 303, 307, 308):
                hops += 1
                loc = resp.getheader("Location")
                if hops > MAX_REDIRECTS or not loc:
                    raise _Fail("redirect-refused")
                url = urllib.parse.urljoin(url, loc)
                continue
            if resp.getheader("Retry-After") is not None:
                raise _Fail("retry-later")
            if status != 200:
                raise _Fail("http-%d" % status)
            enc = (resp.getheader("Content-Encoding") or "").strip().lower()
            if enc and enc != "identity":
                raise _Fail("encoded")
            ctype = (resp.getheader("Content-Type") or "").split(";")[0].strip().lower()
            if ctype not in ("image/png", "image/jpeg", "image/webp"):
                raise _Fail("not-image")
            try:
                if int(resp.getheader("Content-Length") or 0) > max_bytes:
                    raise _Fail("too-large")
            except ValueError:
                pass
            chunks, n = [], 0
            read = getattr(resp, "read1", None) or resp.read
            while True:
                if time.monotonic() > deadline:  # a body that drips one byte at a time (v2 #16)
                    raise _Fail("timeout")
                c = read(65536)
                if not c:
                    break
                n += len(c)
                if n > max_bytes:
                    raise _Fail("too-large")
                chunks.append(c)
            return b"".join(chunks), ctype, url
        except _Fail:
            raise
        except (ssl.SSLError, ssl.CertificateError):
            raise _Fail("tls")
        except (socket.timeout, TimeoutError):
            raise _Fail("timeout")
        except (OSError, http.client.HTTPException):
            raise _Fail("net")
        finally:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


def _check_image(data, ctype, ext, rules):
    """(cleaned bytes, width, height) or _Fail."""
    from .shots import animated, image_size, sanitize
    want = "jpg" if ext in ("jpg", "jpeg") else ext
    ck = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}[ctype]
    if kind_of(data) != ck or ck != want:
        raise _Fail("bad-format")
    if animated(data):
        raise _Fail("animated")
    size = image_size(data)
    if not size or not size[0] or not size[1]:
        raise _Fail("bad-format")
    w, h = size
    if w < int(rules.get("min_width") or 0) or max(w, h) < int(rules.get("min_long_side") or 0):
        raise _Fail("too-small")
    if max(w, h) > MAX_SIDE or w * h > MAX_PIXELS:
        raise _Fail("too-big")
    try:
        clean, _ = sanitize(data, ext, keep_icc=True)
    except HeraldError:
        raise _Fail("bad-format")
    return clean, w, h




def _originals_dir(root, tid):
    return os.path.join(root, ".claude/herald/memory/images/originals", tid)


def fetch(root, cfg, tid, ids=None, version="0"):
    """`HRD image fetch`: each pending external item (or `--id`), one at a time within BUDGET
    seconds, state saved after each. The fetch line is written before the file (rule U)."""
    from .store import load_state, save_state
    st = load_state(root, tid)
    if not _on_branch(root, tid, st):
        raise HeraldError("fetch runs on this topic's herald branch only")
    why = external_off(root, cfg, _category(root, cfg, st["slug"]))
    if why:
        raise HeraldError("external images are off here (%s)" % why)
    items = _plan_items(root, tid, ids, kind="external")
    man_errors = check_manifest(root, cfg, tid, st, load_manifest(root, tid))[0]
    # plan's whole-manifest rules hold for a fetch too (counts, quotations, max_total — review m3)
    general = [e for e in man_errors if not re.match(r"^([a-z][0-9]{1,3}|images\[[0-9]+\]): ", e)]
    if general:
        raise HeraldError("images.json: " + "; ".join(general))
    rules = external_limits(root, cfg, _category(root, cfg, st["slug"]))["rules"]
    max_bytes = int(rules.get("max_bytes") or 10485760)
    led = Ledger(root)
    led.check(len(items))
    rejected = {r.get("source_url") for r in st.get("image_rejects") or [] if isinstance(r, dict)}
    st.setdefault("images", {}).setdefault("items", {})
    st["images"].setdefault("files", {})
    out = {"fetched": [], "failed": [], "remaining": [], "skipped": []}
    ua = "Herald/%s (+%s)" % (version, cfg.get("site", "base_url") or "")
    t0 = time.monotonic()
    for it in items:
        iid = it.get("id")
        if not ids and external_state(root, tid, it, led) != "pending":
            out["skipped"].append(iid)
            continue
        if BUDGET - (time.monotonic() - t0) < FETCH_START_MIN:
            out["remaining"].append(iid)
            continue
        if it.get("source_url") in rejected:
            out["failed"].append({"id": iid, "code": "rejected-before", "class": "content"})
            continue
        mine = [e for e in man_errors if e.startswith("%s:" % iid) and "attribution" not in e]
        if mine:
            raise HeraldError("images.json: " + "; ".join(mine))
        f = it["file"]
        try:
            data, ctype, final = _get(it["source_url"], max_bytes, time.monotonic() + FETCH_ITEM, ua)
            clean, w, h = _check_image(data, ctype, f.rsplit(".", 1)[-1].lower(), rules)
        except _Fail as e:
            out["failed"].append({"id": iid, "code": e.code, "class": fetch_class(e.code)})
            continue
        ext = f.rsplit(".", 1)[-1].lower()
        src_sha = hashlib.sha256(data).hexdigest()
        od = _originals_dir(root, tid)
        os.makedirs(od, exist_ok=True)
        with open(os.path.join(od, "%s-%s.%s" % (iid, src_sha[:12], ext)), "wb") as fh:
            fh.write(data)
        hh = _bytes_hashes(root, f, clean)
        at, key = now_iso(), item_key(it)
        ledger_append(os.path.join(root, FETCHES), {
            "topic": tid, "id": iid, "key": key, "file": f, "blob": hh[0], "sha256": hh[1], "at": at,
            "source_url": it["source_url"], "final_url": final, "page_url": it.get("page_url"),
            "credit": it.get("credit"), "license": it.get("license"), "use": it.get("use"),
            "source_sha256": src_sha, "width": w, "height": h})
        led.fetches.append({"topic": tid, "id": iid, "key": key, "blob": hh[0], "sha256": hh[1]})
        cur = file_hashes(root, f)
        if cur and cur != hh:
            move_to_removed(root, tid, [f], "replaced", area="images")  # whatever sat there was not this fetch (P9)
        dest = os.path.join(root, f)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as fh:
            fh.write(clean)
        ori = "portrait" if h > w else "landscape"
        st["images"]["items"][iid] = {"kind": "external", "use": it.get("use"), "file": f, "key": key,
                                      "status": "fetched", "fetched_at": at, "orientation": ori,
                                      "width": w, "height": h}
        st["images"]["files"][f] = {"kind": "external", "use": it.get("use")}
        save_state(root, tid, st)
        out["fetched"].append({"id": iid, "file": f, "width": w, "height": h, "bytes": len(clean), "orientation": ori})
    return out


# --- generate scenes (09 §2.4) -------------------------------------------------------------------

LIVE = ("starting", "running")


def _num(iid):
    return int(iid[1:]) if isinstance(iid, str) and iid[1:].isdigit() else 0


def _gen_paths(root, cfg, tid):
    """(state dir, its root-relative spelling, the job file, the output folder's relative path)."""
    sd = limner.state_dir_abs(root, cfg)
    sd_rel = limner.rel_to_root(root, sd)
    return sd, sd_rel, os.path.join(sd, limner.JOBS_DIR, "%s.json" % tid), "%s/%s/%s" % (sd_rel, limner.OUT_DIR, tid)


def _job_entry(cfg, it, out_rel):
    w, h = SCENE_SIZES[it["size"]]
    return {"id": it["id"], "out": out_rel, "width": w, "height": h, "prompt": full_prompt(cfg, it), "refs": [],
            "seed": it["seed"]}


def _job_bytes(jobs):
    return json.dumps({"version": 1, "model": limner.GEN_MODEL, "jobs": jobs}, sort_keys=True).encode("utf-8")


def _write_job(path, jobs):
    """The job file (rewritten on every call — the same jobs give the same bytes and run_id)."""
    data = _job_bytes(jobs)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return hashlib.sha256(data).hexdigest()


def _verify_record(root, cfg, out_rel, job):
    """(bytes, record, None) or (None, record, code) — §2.6.2: limner's record of this output says
    it generated these bytes from this very job. The model name is not compared (the record names
    the quantized model, R1-1)."""
    try:
        with open(os.path.join(root, out_rel), "rb") as f:
            data = f.read()
    except OSError:
        return None, None, "record-mismatch"
    rec = limner.read_record(root, cfg, out_rel)
    if rec is None:
        return None, None, "record-mismatch"
    if rec.get("generator") != "mflux":
        if rec.get("generator") == "fake" and limner.fake_allowed():
            pass
        else:
            return None, rec, "fake-generator" if rec.get("generator") == "fake" else "record-mismatch"
    ok = rec.get("kind") == "generate" and rec.get("contract") == limner.CONTRACT and \
        isinstance(rec.get("job_sha"), str) and rec.get("job_sha") and \
        isinstance(rec.get("out"), str) and os.path.normpath(rec["out"]) == os.path.normpath(out_rel) and \
        rec.get("out_sha256") == hashlib.sha256(data).hexdigest() and rec.get("prompt") == job["prompt"] and \
        rec.get("seed") == job["seed"] and rec.get("width") == job["width"] and rec.get("height") == job["height"] and \
        rec.get("refs") == []
    return (data, rec, None) if ok else (None, rec, "record-mismatch")


def _receive(root, cfg, tid, st, it, job, led, res, run_id, updated=False):
    """§2.4.3 8: one item limner reported finished — record verified, then the ledger line (once
    per (topic, id, key, blob), R2-1), then the published file (atomically; another file there goes
    under removed/, P9). Ledger → file, as for a fetch. `updated`: limner drew this very job again
    because its own lock changed (shown at the confirmation, R2-5)."""
    iid, f = it["id"], it["file"]
    data, rec, bad = _verify_record(root, cfg, job["out"], job)
    if bad:
        res["failed"].append({"id": iid, "code": bad, "class": "env",
                              "message": "limner's record does not vouch for %s (%s)" % (job["out"], bad)})
        return
    key = scene_key(cfg, it)
    hh = _bytes_hashes(root, f, data)
    new = False
    if not led.gen_has(tid, iid, key, hh[0]):
        line = {"topic": tid, "id": iid, "key": key, "file": f, "blob": hh[0], "sha256": hh[1], "at": now_iso(),
                "run_id": run_id, "job_sha": rec.get("job_sha"),
                "model": rec.get("model") if isinstance(rec.get("model"), dict) else {},
                "lora": rec.get("lora") if isinstance(rec.get("lora"), dict) else {},
                "model_license": rec.get("model_license") or "", "generator": rec.get("generator"),
                "seed": job["seed"], "width": job["width"], "height": job["height"], "prompt": job["prompt"],
                "limner": rec.get("limner"), "mflux": rec.get("mflux"), "seconds": rec.get("seconds")}
        ledger_append(os.path.join(root, GENERATIONS), line)
        led.generations.append(line)
        new = True
    cur = file_hashes(root, f)
    copied = False
    if cur != hh:
        if cur:
            move_to_removed(root, tid, [f], "replaced", area="images")  # a human's or an old key's file (P9)
        dest = os.path.join(root, f)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        tmp = os.path.join(os.path.dirname(dest), ".%s.hrd-tmp" % os.path.basename(dest))
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, dest)
        copied = True
    items = st["images"].setdefault("items", {})
    r = items.setdefault(iid, {"kind": "scene", "file": f})
    if r.get("generated_blob") != hh[0]:  # another picture: review again, say why it changed
        r["generated_at"] = now_iso()
        r.pop("reviewed", None)
        r.pop("review_note", None)
        r.pop("confirmed_by", None)  # a confirmation follows the content (11 §9 m3)
        if updated:
            r["regenerated"] = True
        else:
            r.pop("regenerated", None)
    r.update(kind="scene", file=f, key=key, generated_blob=hh[0],
             status="ready" if led.confirmed_for(hh, tid, iid, key) else "generated")
    if led.confirmed_by(hh, tid, iid, key) == "agent":
        r["confirmed_by"] = "agent"
    else:
        r.pop("confirmed_by", None)
    st["images"].setdefault("files", {})[f] = {"kind": "scene", "use": None}
    if updated and iid not in res["regenerated"]:
        res["regenerated"].append(iid)
    if new or copied:
        res["generated"].append({"id": iid, "file": f, "seconds": rec.get("seconds")})
    else:
        res["skipped"].append(iid)


def _retryable(code):
    return code in GEN_RETRY or code.startswith("signal:")


def _status_obj(obj):
    """limner's attempt status (a final verdict or `attempt: null`) — not an `{"error"}` answer."""
    return isinstance(obj, dict) and "state" in obj and "run_id" in obj


def _settle(res, pre, jid, received):
    """An item this call need not make (generated or ready before it): never a failure."""
    if pre.get(jid) == "generated" and jid not in received and jid not in res["skipped"]:
        res["skipped"].append(jid)


def _final(root, cfg, obj, todo, jobs, res, run_id, received, pre, take, partial=False, can_retry=False,
           room=None):
    """Read a limner result: receive `done ∪ skipped ∪ adopted` of the items not confirmed yet and
    — unless `partial` (a run still going) — map the rest by the §2.4.3 table; items generated or
    ready before this call are never failures (review round 1 m2). Returns True when only machine
    failures (memory, metal, signal, crashed) are left: one more `run` resumes the work.
    `take(id, regenerated, run_id)` receives one finished item (0.19: the topic's `_receive` or the
    social draft's own — design/herald/10-social-media.md §2.3 3); `regenerated`: limner listed it
    as drawn again."""
    by = {it["id"]: it for it in todo}
    regen = {g.get("id") for g in obj.get("regenerated") or [] if isinstance(g, dict)}
    done_ids = [d.get("id") for d in obj.get("done") or [] if isinstance(d, dict)]
    for jid in done_ids + list(obj.get("skipped") or []) + list(obj.get("adopted") or []):
        if jid in by and jid not in received and pre.get(jid) != "ready":
            received.add(jid)
            take(jid, jid in regen, run_id)
    if partial:
        return False
    fails, general = {}, None
    for x in obj.get("failed") or []:
        if not isinstance(x, dict):
            continue
        reason = str(x.get("reason") or "error")
        code = "env" if reason == "environment" else reason
        entry = (code, str(x.get("message") or "")[:300] or None)
        if x.get("id") is None:
            general = entry
        elif x["id"] in by:
            fails[x["id"]] = entry
    for jid in list(obj.get("modified") or []) + list(obj.get("untracked") or []) + \
            [b.get("id") for b in obj.get("blocked") or [] if isinstance(b, dict)]:
        if jid in by:
            fails[jid] = ("race", "the output folder %s was changed by someone else" % jobs[jid]["out"])
    for jid in list(fails):
        if pre.get(jid) != "pending":
            fails.pop(jid)
            _settle(res, pre, jid, received)
    state = obj.get("state")
    if state == "crashed":
        general = general or ("crashed", "limner's worker ended without a result")
    elif state == "orphan_child":
        _stop_run(root, cfg, run_id, room)
        general = ("orphan_child", "limner's generator outlived its worker — cancelled")
    elif state == "cancelled":
        general = general or ("cancelled", "the run was cancelled")
    elif state == "busy":
        general = ("busy", str((obj.get("busy") or {}).get("holder") or "the machine is busy")[:300])
    left = [it["id"] for it in todo if it["id"] not in received and it["id"] not in fails]
    for jid in [j for j in left if pre.get(j) != "pending"]:
        left.remove(jid)
        _settle(res, pre, jid, received)
    if left and general is None:
        general = ("crashed", "limner's run ended without a result for it")
    codes = [c for c, _ in fails.values()] + ([general[0]] if general and left else [])
    if can_retry and codes and all(_retryable(c) for c in codes):
        return True
    for jid, (code, msg) in sorted(fails.items(), key=lambda kv: _num(kv[0])):
        if jid not in received:
            res["failed"].append({"id": jid, "code": code, "class": "env", "message": msg})
    if general:
        for jid in left:
            res["failed"].append({"id": jid, "code": general[0], "class": "env", "message": general[1]})
    return False


FINAL_STATES = ("done", "failed", "busy", "cancelled", "crashed")


def _cancel_run(root, cfg, run_id, timeout=GEN_CANCEL_WAIT + 30):
    sd = limner.state_dir_abs(root, cfg)
    ws = max(0, min(GEN_CANCEL_WAIT, int(timeout - 10)))
    return limner.gen_call(root, cfg, "cancel", [("--run-id", run_id), ("--root", os.path.realpath(root)),
                                                 ("--state-dir", sd), ("--wait-seconds", ws)], timeout)


def _stop_run(root, cfg, run_id, room=None):
    """Stop a run Herald no longer needs and judge it by the result's `state` (design R1-5 — never
    the exit code: `cancel` of an ended attempt answers that attempt's code, 73 for one that ended
    busy, 2 for one that ended on an environment failure). (state, None) when it is over — gone,
    finished or cancelled —, else (state, failure): `busy` while it still runs, or the code of an
    answer with no status. `orphan_child` is cancelled once more. `room()`: the seconds the call has
    left, read again before each cancel (review round 2 m3) — none left: not stopped now (the next
    call or `HRD image cancel` does). Not found or no limner here: not this machine's run, gone."""
    for n in range(2):
        timeout = GEN_CANCEL_WAIT + 30 if room is None else int(min(GEN_CANCEL_WAIT + 30, room()))
        if timeout < 2:
            return None, ("busy", "no time left in this call to stop run %s" % run_id)
        c = _cancel_run(root, cfg, run_id, timeout)
        if c["code"] in ("not-found", "limner:missing"):
            return None, None
        obj = c["obj"] or {}
        state = obj.get("state") if _status_obj(obj) else None
        if state in FINAL_STATES:
            return state, None
        if state == "orphan_child" and n == 0:
            continue
        if state in LIVE or c["exit"] == 10 or c["code"] == "timeout":
            return state, ("busy", "Herald's earlier run %s has not stopped yet" % run_id)
        return state, (state or c["code"] or "crashed", c["message"])
    return "orphan_child", ("orphan_child", "limner's generator outlived its worker")


def _fail_pending(res, todo, pre, received, code, message=None):
    """A failure with no attempt status to read: the items still to make fail with it; those
    already generated stay as they are (review round 1 m2)."""
    for it in todo:
        jid = it["id"]
        if jid in received:
            continue
        if pre.get(jid) == "pending":
            res["failed"].append({"id": jid, "code": code, "class": "env", "message": message})
        else:
            _settle(res, pre, jid, received)


def _gen_state(res, live=False):
    res["state"] = "running" if live or res["running"] else ("failed" if res["failed"] else "done")
    return res


def generate(root, cfg, tid, wait=GEN_WAIT):
    """`HRD image generate` (§2.4.3): start or take over limner's run of this topic's scenes,
    wait at most `wait` seconds, take in what it finished. Never on base; never `--force` or
    `--accept` (a human's file is moved away by Herald first, P9). The whole call stays within
    `wait` + GEN_SLACK seconds — the caller's Bash timeout is `wait` + 60 (review round 1 m7)."""
    from .store import load_state, save_state
    t0 = time.monotonic()
    deadline = t0 + wait + GEN_SLACK if isinstance(wait, int) else t0

    def cap(n):
        return max(1, int(min(n, deadline - time.monotonic())))

    def room():
        return deadline - time.monotonic()
    st = load_state(root, tid)
    if not _on_branch(root, tid, st):
        raise HeraldError("generate runs on this topic's herald branch only (never on base — the worker writes "
                          "under the state dir, Herald copies from there on this branch)")
    if not _small_int(wait, 0, GEN_WAIT_MAX):
        raise HeraldError("--wait is 0 to %d seconds" % GEN_WAIT_MAX)
    rec = st.get("images") or {}
    man = load_manifest(root, tid)
    scenes = sorted([i for i in _items(man) if i.get("kind") == "scene"], key=lambda i: _num(i.get("id")))
    if scenes and (not rec.get("manifest") or rec.get("manifest") != _hash(root, manifest_rel(tid)) or
                   rec.get("body") != _hash(root, cfg.body_path(st["slug"]))):
        raise HeraldError("images.json or the article changed since `HRD image plan` — run `HRD image plan --topic %s` "
                          "first" % tid)
    led = Ledger(root)
    led.check(len(scenes))
    gen = rec.get("gen") if isinstance(rec.get("gen"), dict) else {}
    res = {"state": "done", "generated": [], "skipped": [], "failed": [], "running": [], "regenerated": [],
           "waited_s": gen.get("waited_s", 0), "run_id": gen.get("run_id")}
    items = rec.setdefault("items", {})
    _, _, job_path, out_dir = _gen_paths(root, cfg, tid)
    live_ids = set()
    if gen.get("run_id"):  # the job file is the last job written — the run Herald follows
        try:
            live_ids = {j.get("id") for j in (read_json(job_path) or {}).get("jobs") or [] if isinstance(j, dict)}
        except ValueError:
            live_ids = set()
    todo, pre = [], {}
    for it in scenes:  # 2: what to make — before any probe (R2-4, R3-1)
        iid, key = it.get("id"), scene_key(cfg, it)
        s = scene_state(root, cfg, tid, it, led)
        r = items.get(iid) or {}
        if s != "ready" and r.get("key") == key and scene_fail_closed(tid, iid, r, led):
            res["failed"].append({"id": iid, "code": "record-missing", "class": "env",
                                  "message": scene_fail_closed(tid, iid, r, led)})
            continue
        if s == "ready" and iid not in live_ids:
            continue  # confirmed: a new run never draws it (review round 2 m5)
        # confirmed while the run Herald follows has it in its job: kept, so a confirmation never
        # changes the run_id of a run in progress (review round 1 m4); limner skips it
        todo.append(it)
        pre[iid] = s
    if "pending" not in pre.values():
        # nothing to make: generated pictures are in the ledger and in place already. A run Herald
        # still follows can only be drawing what is taken in, confirmed or dropped — stop it (review
        # round 1 m4, round 2 m4/m5); an ended run, or another machine's, is simply forgotten
        if gen.get("run_id"):
            _, fail = _stop_run(root, cfg, gen["run_id"], room)
            if not fail:
                rec.pop("gen", None)
                save_state(root, tid, st)
        return _gen_state(res)
    why = scene_off(root, cfg, _category(root, cfg, st["slug"]))  # 3
    if why is None:
        p = limner.gen_probe(root, cfg)
        if not p["ok"]:
            why = p["code"]
            res["message"] = p.get("message") or "; ".join(p.get("errors") or []) or None
    if why:
        res.update(state="off", why=why)
        return res
    jobs = {it["id"]: _job_entry(cfg, it, "%s/%s.png" % (out_dir, it["id"])) for it in todo}

    def take(jid, regen, run_id):
        it = next(i for i in todo if i["id"] == jid)
        updated = False
        if regen:  # limner's own update: it drew again a job Herald did not change (the key had a line already)
            prior = led.gen_lines_key(tid, jid, scene_key(cfg, it))
            r = limner.read_record(root, cfg, jobs[jid]["out"]) or {}
            drawn = (r.get("model"), r.get("lora"))
            # a line of this key drawn with another model or LoRA revision: limner's lock changed (a
            # seed changed by hand and back is no update — review round 2 n7)
            updated = bool(prior) and all((x.get("model"), x.get("lora")) != drawn for x in prior)
        _receive(root, cfg, tid, st, it, jobs[jid], led, res, run_id, updated=updated)

    def save_gen(g):
        if g:
            st.setdefault("images", rec)["gen"] = g
        else:
            st.setdefault("images", rec).pop("gen", None)
        save_state(root, tid, st)
    out = drive(root, cfg, todo, jobs, job_path, pre, res, gen, save_gen, take, t0, wait, room, cap)
    if out is None:
        return _gen_state(res)
    gen, live = out
    if gen:
        st["images"]["gen"] = gen
        res["waited_s"] = gen.get("waited_s", 0)
    else:
        st["images"].pop("gen", None)  # the run is over: nothing to take over or cancel
    save_state(root, tid, st)  # 9
    return _gen_state(res, live)


def drive(root, cfg, todo, jobs, job_path, pre, res, gen, save_gen, take, t0, wait, room, cap):
    """Steps 4–8 of §2.4.3 for any set of jobs (0.19: a topic's scenes or a social draft's
    pictures — 10-social-media.md §2.3 3): write the job file, start or take over limner's run,
    wait within the budget, hand each finished item to `take`. `pre[id]` is `pending` (to make),
    `generated` or `ready`; `gen` the run Herald follows ({} for none), `save_gen(gen or None)`
    persists it. Returns None when the run could not start (`res` says why), else (gen, live)."""
    sd = limner.state_dir_abs(root, cfg)
    job_sha = _write_job(job_path, [jobs[it["id"]] for it in todo])
    rroot = os.path.realpath(root)
    base_opts = [("--job", job_path), ("--root", rroot), ("--state-dir", sd)]
    chk = limner.gen_call(root, cfg, "run", [("--check", None)] + base_opts, cap(limner.GEN_PROBE_TIMEOUT))
    run_id = (chk["obj"] or {}).get("run_id")
    received = set()
    if chk["code"] or chk["exit"] != 0 or not isinstance(run_id, str):
        _fail_pending(res, todo, pre, received, chk["code"] or "contract", chk["message"])
        return None
    res["run_id"] = run_id
    if gen.get("run_id") and gen["run_id"] != run_id:  # 4: the jobs changed — stop Herald's old run
        _, fail = _stop_run(root, cfg, gen["run_id"], room)
        if fail:
            _fail_pending(res, todo, pre, received, fail[0], fail[1])
            return None
        gen = {}
        save_gen(None)
    retried, again, live = False, False, False

    def more():
        """Another `run` only while the call has room for it (m7); else the next call goes on."""
        if room() >= 15:
            return True
        res["running"] = [it["id"] for it in todo if it["id"] not in received and pre[it["id"]] == "pending"]
        return False
    while True:
        r = limner.gen_call(root, cfg, "run", base_opts + [("--wait", max(0, min(30, int(room() - 30))))],
                            cap(GEN_RUN_TIMEOUT))  # 5
        obj = r["obj"] or {}
        if r["code"] and not _status_obj(obj):
            _fail_pending(res, todo, pre, received, r["code"], r["message"])
            break
        if obj.get("attempt") is None or obj.get("state") not in LIVE:
            if _final(root, cfg, obj, todo, jobs, res, run_id, received, pre, take, can_retry=not retried,
                      room=room):
                retried = True
                if more():
                    continue
                live = True
            gen = {}
            break
        same = gen.get("run_id") == run_id
        gen = {"run_id": run_id, "attempt": obj.get("attempt"), "job_sha256": job_sha,
               "started_at": gen.get("started_at") if same and gen.get("started_at") else now_iso(),
               "waited_s": gen.get("waited_s", 0) if same else 0}
        save_gen(gen)
        left = t0 + wait - time.monotonic()  # 6
        ws = int(left - 20) if left >= 30 else 0
        t1 = time.monotonic()
        s_ = limner.gen_call(root, cfg, "status", [("--run-id", run_id), ("--root", rroot), ("--state-dir", sd),
                                                  ("--wait-seconds", ws)], cap(ws + 20))
        gen["waited_s"] = int(gen.get("waited_s", 0) + round(time.monotonic() - t1))
        sobj = s_["obj"] or {}
        if s_["code"] == "not-found" and not again:  # 12: the state dir lost the run — once more from 5
            again = True
            gen = {}
            save_gen(None)
            if more():
                continue
            live = True
            break
        if s_["code"] and not _status_obj(sobj):
            _fail_pending(res, todo, pre, received, s_["code"], s_["message"])
            break
        if sobj.get("state") in LIVE:  # 7: still going — take in what it finished so far
            _final(root, cfg, sobj, todo, jobs, res, run_id, received, pre, take, partial=True, room=room)
            res["running"] = [it["id"] for it in todo if it["id"] not in received and pre[it["id"]] == "pending"]
            live = True
            break
        # ended — whatever the exit code (2, 73, 11, 5), the attempt's lists are read (m2)
        if _final(root, cfg, sobj, todo, jobs, res, run_id, received, pre, take, can_retry=not retried,
                  room=room):
            retried = True
            if more():
                continue
            live = True
        gen = {}
        break
    return gen, live


def reset_wait(root, cfg, tid):
    """`generate --reset-wait`: the collect step starts counting this run's wait again (R1-6)."""
    from .store import load_state, save_state
    st = load_state(root, tid)
    g = (st.get("images") or {}).get("gen")
    if isinstance(g, dict):
        g["waited_s"] = 0
        save_state(root, tid, st)
    return {"ok": True}


def cancel(root, cfg, tid):
    """`HRD image cancel`: stop this topic's run (abandon, trim, a deleted topic). Not guarded —
    stopping a generation forges no human decision (§2.4.4)."""
    from .store import load_state
    st = load_state(root, tid)
    g = (st.get("images") or {}).get("gen") or {}
    if not g.get("run_id"):
        return {"cancelled": False, "state": None}
    state, fail = _stop_run(root, cfg, g["run_id"])
    out = {"cancelled": state == "cancelled", "state": state}
    if fail:
        out["error"] = fail[0]
    return out


def generate_trial(root, cfg, wait=GEN_WAIT):
    """`HRD image generate --trial`: one fixed picture with the repo's style under the state dir
    (never the image dir), no ledger. A `running` answer is taken over by calling it again (the
    same job, the same run_id)."""
    if not _small_int(wait, 0, GEN_WAIT_MAX):
        raise HeraldError("--wait is 0 to %d seconds" % GEN_WAIT_MAX)
    t0 = time.monotonic()
    deadline = t0 + wait + GEN_SLACK  # within the caller's Bash timeout of `wait` + 60 (m6, m7)

    def cap(n):
        return max(1, int(min(n, deadline - time.monotonic())))
    errs = scene_errors(cfg) + limner.limner_errors(cfg)
    if errs:
        return {"state": "off", "why": "config", "errors": errs, "file": None, "run_id": None}
    p = limner.gen_probe(root, cfg)
    if not p["ok"]:
        return {"state": "off", "why": p["code"], "message": p.get("message"), "file": None, "run_id": None}
    sd = limner.state_dir_abs(root, cfg)
    sd_rel = limner.rel_to_root(root, sd)
    out_rel = "%s/%s/scene.png" % (sd_rel, limner.TRIAL_DIR)
    it = {"prompt": TRIAL_PROMPT, "size": "square", "seed": 1}
    job = _job_entry(cfg, dict(it, id="trial"), out_rel)
    jpath = os.path.join(sd, limner.TRIAL_DIR, "scene.json")
    _write_job(jpath, [job])
    rroot = os.path.realpath(root)
    base_opts = [("--job", jpath), ("--root", rroot), ("--state-dir", sd)]
    out = {"state": "failed", "file": out_rel, "run_id": None}
    chk = limner.gen_call(root, cfg, "run", [("--check", None)] + base_opts, cap(limner.GEN_PROBE_TIMEOUT))
    if chk["code"] or chk["exit"] != 0:
        out.update(code=chk["code"] or "contract", message=chk["message"])
        return out
    out["run_id"] = (chk["obj"] or {}).get("run_id")
    r = limner.gen_call(root, cfg, "run", base_opts + [("--wait", max(0, min(30, int(deadline - time.monotonic() - 30))))],
                        cap(GEN_RUN_TIMEOUT))
    if r["code"]:
        out.update(code=r["code"], message=r["message"])
        return out
    obj = r["obj"] or {}
    if obj.get("attempt") is not None and obj.get("state") in LIVE:
        left = wait - (time.monotonic() - t0)
        ws = int(left - 20) if left >= 30 else 0
        s_ = limner.gen_call(root, cfg, "status", [("--run-id", out["run_id"]), ("--root", rroot), ("--state-dir", sd),
                                                  ("--wait-seconds", ws)], cap(ws + 20))
        if s_["code"]:
            out.update(code=s_["code"], message=s_["message"])
            return out
        obj = s_["obj"] or {}
        if obj.get("state") in LIVE:
            out["state"] = "running"
            return out
    ids = [d.get("id") for d in obj.get("done") or [] if isinstance(d, dict)] + list(obj.get("skipped") or []) + \
        list(obj.get("adopted") or [])
    if "trial" not in ids:
        f = (obj.get("failed") or [{}])[0] if obj.get("failed") else {}
        out.update(code=(f.get("reason") if isinstance(f, dict) else None) or obj.get("state") or "crashed",
                   message=(f.get("message") if isinstance(f, dict) else None))
        return out
    _, _, bad = _verify_record(root, cfg, out_rel, job)
    if bad:
        out.update(code=bad)
        return out
    out["state"] = "done"
    return out


def review(root, cfg, tid, iid, ok=False, redo=False, note=None):
    """`HRD image review` (§2.7.2) — the illustrator's look before a human's: `--ok` marks the
    picture reviewed, `--redo` turns a scene's key down (plan then refuses the same prompt, seed
    and size). 0.20.0 (11-ship-consent.md §2.2): a fetched external image or quotation too — its
    `--redo` turns down nothing (another candidate replaces it through `reject`). State only —
    never a pass decision (P13: the human's confirmation is, or in a `--ship` run `confirm --agent`)."""
    from .store import load_state, save_state
    if ok == redo:
        raise HeraldError("give exactly one of --ok and --redo")
    if not isinstance(note, str) or not note.strip():
        raise HeraldError("--note says in one line what the reviewer saw")
    st = load_state(root, tid)
    it = next((i for i in _items(load_manifest(root, tid)) if i.get("id") == iid), None)
    if not it or it.get("kind") not in ("scene", "external"):
        raise HeraldError("%s is not a scene or external image in images.json" % iid)
    led = Ledger(root)
    scene = it["kind"] == "scene"
    if scene and scene_state(root, cfg, tid, it, led) != "generated":
        raise HeraldError("%s is not a generated scene waiting for review — `HRD image status --topic %s`" % (iid, tid))
    if not scene and external_state(root, tid, it, led) != "fetched":
        raise HeraldError("%s is not a fetched image waiting for review — `HRD image status --topic %s`" % (iid, tid))
    h = file_hashes(root, it["file"])
    key = scene_key(cfg, it) if scene else item_key(it)
    if ok:
        why = agent_review_refusal(st, it, iid, key, h)
        if why:
            raise HeraldError(why)
    r = st.setdefault("images", {}).setdefault("items", {}).setdefault(
        iid, {"kind": it["kind"], "file": it["file"], "key": key} if scene else
        {"kind": "external", "use": it.get("use"), "file": it["file"], "key": key})
    if ok:
        r["reviewed"] = h[0]
        r["review_note"] = note[:300]
    else:
        r.pop("reviewed", None)
        r["review_note"] = note[:300]
        if scene:
            st.setdefault("review_rejects", []).append({"id": iid, "key": key, "note": note[:300], "at": now_iso()})
        else:  # no key turned down (a candidate is replaced), but these bytes never pass an agent again
            st.setdefault("review_redos", []).append({"id": iid, "blob": h[0], "sha256": h[1], "note": note[:300],
                                                      "at": now_iso()})
    save_state(root, tid, st)
    if ok:
        nxt = None
    elif scene:
        nxt = "change the seed (or the prompt) of %s, then `HRD image plan --topic %s --check`" % (iid, tid)
    else:
        nxt = "`HRD image reject --topic %s --id %s --agent --reason …` (a `--ship` run), then another candidate" % (
            tid, iid)
    return {"reviewed": [iid] if ok else [], "redo": [iid] if redo else [],
            "attempts": scene_attempts(st, iid) if scene else agent_rejects(st, iid), "next": nxt}


def agent_rejects(st, iid):
    """How many times the agent review turned this place's image down (11-ship-consent.md §2.3 2)."""
    return sum(1 for r in st.get("image_rejects") or [] if isinstance(r, dict) and r.get("id") == iid
               and r.get("by") == "agent")


AGENT_REJECTS_MAX = 2  # the third agent reject of one place drops it (three candidates at most)


def agent_review_refusal(st, it, iid, key, h):
    """Why an agent may not pass this picture (`review --ok`, `confirm --agent` — implementation
    review 24 MAJOR-2, MINOR-1): a scene whose key a review or a human turned down, or an external
    image whose very bytes a review sent back (`review_redos`, top-level state: a plan keeps it).
    A human's confirm is not affected — the human judges."""
    if it.get("kind") == "scene" and key in rejected_scene_keys(st, iid):
        return ("%s: a review turned this picture's key down — change the seed or the prompt (a human may still "
                "confirm it)" % iid)
    if it.get("kind") == "external" and h and any(
            isinstance(x, dict) and x.get("id") == iid and (x.get("blob") == h[0] or x.get("sha256") == h[1])
            for x in st.get("review_redos") or []):
        return ("%s: a review sent these very bytes back — `HRD image reject --agent` and another candidate (a human "
                "may still confirm it)" % iid)
    return None


def snippet(root, cfg, tid, iid):
    from .store import load_state
    st = load_state(root, tid)
    it = next((i for i in _items(load_manifest(root, tid)) if i.get("id") == iid), None)
    if not it:
        raise HeraldError("%s is not in images.json" % iid)
    if it.get("kind") == "external":
        r = ((st.get("images") or {}).get("items") or {}).get(iid) or {}
        if r.get("key") != item_key(it) or not r.get("orientation"):
            raise HeraldError("%s is not fetched yet — `HRD image fetch --topic %s --id %s` first (the attribution "
                              "follows the picture's orientation)" % (iid, tid, iid))
        return {"snippet": snippet_text(cfg, it, r.get("orientation"), root, st.get("slug"))}
    return {"snippet": snippet_text(cfg, it, None, root, st.get("slug"))}


# --- confirm / reject (§2.7.3) -----------------------------------------------------------------

def _human_only(what):
    if os.environ.get("HRD_UNATTENDED") == "1":
        raise HeraldError("`image %s` records a human's decision — not allowed in unattended sessions" % what)


def _ids(ids):
    out = [x.strip() for x in (ids if isinstance(ids, list) else str(ids or "").split(",")) if x and x.strip()]
    if not out:
        raise HeraldError("--id needs one or more external or scene image ids (e1,g1)")
    return list(dict.fromkeys(out))


def confirm(root, cfg, tid, ids, agent=False):
    """A human looked at fetched images and their attribution, or at generated scenes and their AI
    label: the confirmation line first, then the state. `agent` (0.20.0, 11-ship-consent.md §2.2):
    in a `--ship` run the agent review stands in for that look — only for images a review marked
    `--ok` as they are now; the line says `by: agent` and vouches for this item only (P25)."""
    from .shots import _agent_allowed, hold_note
    from .store import load_state, save_state
    _human_only("confirm")
    if agent:
        _agent_allowed(root, tid)
    ids = _ids(ids)
    st = load_state(root, tid)
    by = {i.get("id"): i for i in _items(load_manifest(root, tid))}
    led = Ledger(root)
    led.check(len(ids))
    todo = []
    for iid in ids:
        it = by.get(iid)
        if not it or it.get("kind") not in ("external", "scene"):
            raise HeraldError("%s is not an external or scene image in images.json" % iid)
        if it["kind"] == "scene":
            s = scene_state(root, cfg, tid, it, led)
            if s != "generated":
                raise HeraldError("%s is not a generated scene waiting for confirmation (%s) — `HRD image plan --topic "
                                  "%s` first if the file was changed" % (iid, s, tid))
        else:
            s = external_state(root, tid, it, led)
            if s != "fetched":
                raise HeraldError("%s is not a fetched image waiting for confirmation (%s) — `HRD image plan --topic "
                                  "%s` first if the file was changed" % (iid, s, tid))
        h = file_hashes(root, it["file"])
        if agent and ((st.get("images") or {}).get("items") or {}).get(iid, {}).get("reviewed") != h[0]:
            raise HeraldError("%s: the agent review has not passed this picture as it is now — `HRD image review "
                              "--topic %s --id %s --ok` by a fresh review first" % (iid, tid, iid))
        if agent:
            why = agent_review_refusal(st, it, iid, scene_key(cfg, it) if it["kind"] == "scene" else item_key(it), h)
            if why:
                raise HeraldError(why)
        todo.append((iid, it, h))
    at = now_iso()

    def key_of(it):
        return scene_key(cfg, it) if it["kind"] == "scene" else item_key(it)
    items = st.setdefault("images", {}).setdefault("items", {})
    for iid, it, h in todo:
        line = {"topic": tid, "id": iid, "key": key_of(it), "blob": h[0], "sha256": h[1], "at": at}
        if agent:
            line.update(by="agent", note=((items.get(iid) or {}).get("review_note") or "")[:300])
        ledger_append(os.path.join(root, CONFIRMATIONS), line)
    for iid, it, h in todo:
        items.setdefault(iid, {"kind": it["kind"], "use": it.get("use"), "file": it["file"], "key": key_of(it)})
        items[iid].update(status="ready", sha=h[0])
        if agent:
            items[iid]["confirmed_by"] = "agent"
        else:
            items[iid].pop("confirmed_by", None)
    save_state(root, tid, st)
    return {"confirmed": [t[0] for t in todo], "by": "agent" if agent else "human", "note": hold_note(st),
            "items": [{"id": iid, "kind": it["kind"], "use": it.get("use"), "credit": it.get("credit"),
                       "license": it.get("license"), "page_url": it.get("page_url")} for iid, it, _ in todo]}


def reject(root, cfg, tid, iid, reason=None, drop=False, refetch=False, regenerate=False, agent=False):
    """A human rejects a fetched image or a generated scene (state first, then the file moves).
    Without `--refetch`/`--regenerate` this is the `--human` loopback's state change too: the
    illustrator runs next (another candidate, a scene's other seed or prompt, or with `--drop` the
    place goes). `--refetch`: fetch it again on this machine; `--regenerate`: generate a scene again
    on this machine (§2.5 — the way out of a missing generation record; no rejected key).
    `agent` (0.20.0, 11-ship-consent.md §2.2): the agent review of a `--ship` run turns a picture
    down — an external image for another candidate (its third reject must `--drop`), a scene only
    with `--drop` (a scene is drawn again through `review --redo`); recorded `by: agent`."""
    from .shots import _agent_allowed, hold_note
    from .store import load_state, open_research_fix, save_state
    _human_only("reject")
    if sum(map(bool, (drop, refetch, regenerate))) > 1:
        raise HeraldError("give at most one of --drop, --refetch and --regenerate")
    if agent:
        _agent_allowed(root, tid)
        if refetch or regenerate:
            raise HeraldError("--refetch and --regenerate are a human's way out — not with --agent")
    again = refetch or regenerate
    st = load_state(root, tid)
    if not again and st.get("stage") != "draft":
        raise HeraldError("reject is for an image waiting in draft — later, a loopback with --theme images")
    if open_research_fix(st):
        raise HeraldError("a research fix is open — the researcher runs first")
    if (st.get("trim") or {}).get("status") == "open":
        raise HeraldError("a trim is open — `HRD trim --topic %s --abort` first" % tid)
    it = next((i for i in _items(load_manifest(root, tid)) if i.get("id") == iid), None)
    scene = bool(it) and it.get("kind") == "scene"
    if not it or it.get("kind") not in ("external", "scene"):
        raise HeraldError("%s is not an external or scene image in images.json" % iid)
    if refetch and scene or regenerate and not scene:
        raise HeraldError("--refetch is for an external image, --regenerate for a scene")
    if agent and scene and not drop:
        raise HeraldError("an agent rejects a scene only with --drop — another picture comes from `HRD image review "
                          "--redo`")
    if agent and not scene and not drop and agent_rejects(st, iid) >= AGENT_REJECTS_MAX:
        raise HeraldError("%s was turned down by the agent review %d times — the next reject is `--drop` (three "
                          "candidates at most)" % (iid, AGENT_REJECTS_MAX))
    key = scene_key(cfg, it) if scene else item_key(it)
    rec = st.setdefault("images", {})
    items = rec.setdefault("items", {})
    r = items.setdefault(iid, {"kind": it["kind"], "use": it.get("use"), "file": it["file"], "key": key})
    r["status"] = "pending"
    for k in ("sha", "fetched_at", "orientation", "width", "height", "generated_at", "generated_blob", "reviewed",
              "review_note", "confirmed_by"):
        r.pop(k, None)
    if not again:
        rj = {"id": iid, "source_url": it.get("source_url"), "reason": (reason or "")[:300], "drop": bool(drop),
              "at": now_iso()}
        if scene:  # the key turned down: plan refuses the same prompt, seed and size (§2.6.3)
            rj = {"id": iid, "job": key, "reason": rj["reason"], "drop": rj["drop"], "at": rj["at"]}
        if agent:
            rj["by"] = "agent"
        st.setdefault("image_rejects", []).append(rj)
        st["stage"] = "draft"
        # an agent's reject is no human loopback: a later gate failure stays a signal (11 §2.2)
        st["last_loopback"] = "agent" if agent else "human"
        rec["awaiting"] = False
        if st.get("screenshots"):
            st["screenshots"]["awaiting"] = False
        if st.get("translation"):
            st["translation"].pop("last_loopback_langs", None)
            st["translation"].pop("last_loopback_stage", None)
    save_state(root, tid, st)
    moved = move_to_removed(root, tid, [it["file"]] if not on_base(root, cfg, it["file"]) else [],
                            "refetch" if refetch else "regenerate" if regenerate else "rejected", area="images")
    if refetch:
        nxt = "HRD image fetch --topic %s --id %s, then a human confirms it" % (tid, iid)
    elif regenerate:
        nxt = "HRD image generate --topic %s on this machine, then a human confirms it" % tid
    elif drop:
        nxt = "the illustrator: remove that place (reference, %s, manifest entry)" % (
            "AI label" if scene else "attribution")
    else:
        nxt = "the illustrator: %s" % ("change the seed or the prompt of %s, or leave the place out" % iid if scene else
                                       "another candidate from research.md, or leave the place out")
    return {"rejected": [iid] if not again else [], "refetch": [iid] if refetch else [],
            "regenerate": [iid] if regenerate else [], "moved": moved, "note": hold_note(st), "next": nxt}


# --- OG (§2.8) --------------------------------------------------------------------------------

def _nfc(s):
    import unicodedata
    return unicodedata.normalize("NFC", s) if isinstance(s, str) else s


def og_inputs(root, cfg, st, rev=None):
    """The raw values the OG card is drawn from (frontmatter of the source body)."""
    slug = st.get("slug")
    fm = _frontmatter(root, cfg.body_path(slug), rev) if slug else {}
    o = og_conf(cfg) or {}
    return {"title": _nfc(fm.get("title")), "subtitle": _nfc(fm.get("description")) if o.get("subtitle") == "description"
            else None, "slug": slug, "date": str(fm.get("date") or "")[:10], "category": fm.get("category"),
            "lang": lang_tag(cfg)}


def _used(cfg):
    t = (og_conf(cfg) or {}).get("command")
    if t is None:
        return ("title", "subtitle", "lang")
    return tuple(x[1:-1] for x in t if x in OG_PLACEHOLDERS and x != "{out}")


def og_key(root, cfg, st, inputs=None):
    o = og_conf(cfg) or {}
    v = inputs or og_inputs(root, cfg, st)
    by = "repo" if o.get("command") is not None else "limner"
    used = {k: v.get(k) for k in _used(cfg)}
    raw = json.dumps([by, o.get("command") or "og-title", limner.CONTRACT, v.get("title"), v.get("subtitle"),
                      v.get("lang"), used], sort_keys=True, ensure_ascii=False)
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def og_bad_value(cfg, v):
    """The first input that cannot go into an argv or a card, or None."""
    def text_ok(s, n):
        return isinstance(s, str) and 1 <= len(s) <= n and not re.search(r"[\n\r\x00]", s) and not s.startswith("-")
    for k in _used(cfg):
        val = v.get(k)
        if k == "title" and not text_ok(val, 120):
            return "title"
        if k == "subtitle" and val is not None and not text_ok(val, 200):
            return "subtitle"
        if k == "date" and not re.match(r"^\d{4}-\d{2}-\d{2}$", str(val or "")):
            return "date"
        if k == "category" and not re.match(r"^[a-z0-9-]+$", str(val or "")):
            return "category"
        if k == "slug" and not re.match(r"^[a-z0-9-]+$", str(val or "")):
            return "slug"
        if k == "lang" and not re.match(r"^[a-z]{2,3}$", str(val or "")):
            return "lang"
    return None


def quotation_files(root, cfg, slug, rev=None):
    """Every file recorded as a quotation by any topic of this slug, with its content (blob and
    sha256 at `rev` or in the working tree). 0.18.0/0.19.0 must refuse these as a reference or
    composition input before using one (a contract this design leaves — P16)."""
    olds = set(_old_slugs(root, slug)) | {slug}
    out = []
    for _, st in _topic_states(root, rev):
        if st.get("slug") not in olds:
            continue
        for f, meta in (((st.get("images") or {}).get("files")) or {}).items():
            if isinstance(meta, dict) and meta.get("use") == "quotation":
                p = cur_path(root, cfg, slug, f)
                h = _rev_hashes(root, rev, p)
                out.append({"file": p, "blob": h[0] if h else None, "sha256": h[1] if h else None})
    # the fetch ledger knows the content even after the file moved away
    led = Ledger(root)
    for r in led.fetches:
        if r.get("use") == "quotation" and r.get("file", "").startswith(cfg.image_dir(slug).rstrip("/") + "/"):
            out.append({"file": r.get("file"), "blob": r.get("blob"), "sha256": r.get("sha256")})
    return out


def _is_quotation(h, q):
    return bool(h) and any(x.get("blob") == h[0] or x.get("sha256") == h[1] for x in q if x.get("blob") or x.get("sha256"))


def og_quotation_problem(root, cfg, slug, rev=None):
    """P16 in code: the OG path holding a quotation image is an error no consent lifts."""
    path = cfg.og_path(slug) if og_conf(cfg) else None
    if not path:
        return None
    h = _rev_hashes(root, rev, path)
    if h and _is_quotation(h, quotation_files(root, cfg, slug, rev)):
        return ("%s is a quotation image — a quotation never becomes the OG card or an SNS picture: remove that file, "
                "then `HRD image og` again (or leave OG off)" % path)
    return None


def _base_blob(root, cfg, rel):
    return git(root, "rev-parse", "-q", "--verify", "origin/%s:%s" % (cfg.base, rel), check=False).strip() or None


def _is_refresh(root, tid, st):
    from .store import get_topic, load_topics
    try:
        t = get_topic(load_topics(root), tid)
    except HeraldError:
        t = {}
    return bool(t.get("refresh_of") or st.get("refresh_of"))


def _snapshot(root):
    """(path → sha256 of the working-tree content) for every path git status lists."""
    raw = git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all", check=False)
    parts, out, i = raw.split("\0"), {}, 0
    while i < len(parts):
        e = parts[i]
        i += 1
        if len(e) < 4:
            continue
        st, path = e[:2], e[3:]
        if "R" in st or "C" in st:
            i += 1  # the rename's source
        full = os.path.join(root, path)
        if os.path.isfile(full):
            with open(full, "rb") as f:
                out[path] = (st, hashlib.sha256(f.read()).hexdigest())
        else:
            out[path] = (st, None)
    return out


def _og_limner(root, cfg, tid, path, v, out_abs=None, data_rel=None):
    """(status, why, problems): `made` or `off` — a card limner draws with og-title."""
    p = limner.probe(root, cfg)
    if not p["ok"]:
        return "off", "no-limner" if p["code"] == "limner:missing" else p["code"], []
    data = {"title": v["title"], "lang": v["lang"]}
    if v.get("subtitle"):
        data["subtitle"] = v["subtitle"]
    drel = data_rel or _work_rel(tid, "og.json")
    os.makedirs(os.path.dirname(os.path.join(root, drel)), exist_ok=True)
    with open(os.path.join(root, drel), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    rroot = os.path.realpath(root)
    target = out_abs or os.path.join(rroot, path)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    res = limner.run(root, cfg, ["compose"], [("--template", "og-title"), ("--data", os.path.join(rroot, drel)),
                                               ("--root", rroot), ("--state-dir", limner.state_dir_abs(root, cfg)),
                                               ("--out", target)])
    problems, failure = limner.classify(res)
    if failure:
        return "off", failure["code"], []
    if problems:
        codes = [x.get("code") for x in problems]
        why = "title-too-long" if any(c in ("overflow", "too_small") for c in codes) else \
            next((c for c in codes if c in ("missing_glyph", "low_contrast")), codes[0] or "problems")
        return "off", why, problems
    h = None
    if os.path.isfile(target):
        with open(target, "rb") as f:
            h = hashlib.sha256(f.read()).hexdigest()
    if not h or (res["obj"] or {}).get("out_sha256") != h:
        return "off", "record-mismatch", []
    return "made", None, []


def _og_argv(cfg, v, out):
    vals = dict({k: str(v.get(k) or "") for k in ("title", "slug", "date", "category", "lang")}, out=out)
    return [vals[x[1:-1]] if x in OG_PLACEHOLDERS else x for x in og_conf(cfg)["command"]]


def _og_repo(root, cfg, tid, path, v, trial=False):
    """(status, why, problems) — the repo's generator, without a shell; anything it changes
    besides the OG path (and new folders above it) refuses (`og:side-effects`)."""
    from .shots import _run_tool
    errs = og_errors(root, cfg)
    if errs:
        return "off", "config", []
    rroot = os.path.realpath(root)
    target = os.path.join(rroot, path)
    argv = _og_argv(cfg, v, target)
    before = _snapshot(root)
    code = _run_tool(root, argv, os.path.join(root, ".claude/herald/memory/images/tmp/og.pgid"))
    after = _snapshot(root)
    changed = sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p) and p != path)
    if changed:
        raise HeraldError("og:side-effects %s — the OG command changed other files (left as they are for a human). "
                          "Attended: show them and ask; otherwise hold needs-human with the note `tooling: og "
                          "side-effects`" % ", ".join(changed[:10]))
    if code:
        return "off", "repo:%s" % code, []
    rules = external_limits(root, cfg, None)["rules"]
    if not os.path.isfile(target) or os.path.getsize(target) == 0:
        return "off", "repo:no-file", []
    with open(target, "rb") as f:
        data = f.read()
    if kind_of(data) != "png" or len(data) > int(rules.get("max_bytes") or 10485760):
        return "off", "repo:bad-format", []
    return "made", None, []


def _accept_human_og(root, cfg, tid, path, h, pr):
    """§2.8.2 7: a file a human pushed to the PR after Herald's last push from this machine."""
    from .store import ledger_lines
    _human_only("og --human-push")
    if pr is None:
        raise HeraldError("--human-push needs --pr <n> (the PR whose head is checked out)")
    pushes = [r for r in ledger_lines(root) if r.get("topic_id") == tid and r.get("kind") == "push" and r.get("sha")]
    if not pushes:
        raise HeraldError("no Herald push of %s is recorded on this machine — ship from the machine that pushed it, "
                          "or remove the OG file from the PR; this PR is not merged now" % tid)
    hsha = pushes[-1]["sha"]
    ref = "refs/remotes/origin/pr-%d" % int(pr)
    head = git(root, "rev-parse", "HEAD").strip()
    if git(root, "rev-parse", "-q", "--verify", ref, check=False).strip() != head:
        raise HeraldError("HEAD is not %s — `HRD fetch-pr --pr %s` and switch to it first (a local commit is no "
                          "human's push)" % (ref, pr))
    if not git_ok(root, "merge-base", "--is-ancestor", hsha, head):
        raise HeraldError("Herald's last push %s is not in this PR's history" % hsha[:12])
    came = git(root, "log", "--format=%H", "%s..%s" % (hsha, head), "--", path, check=False).split()
    if not came:
        raise HeraldError("%s did not come in after Herald's last push — not a human's OG file" % path)
    at_head = git(root, "rev-parse", "-q", "--verify", "HEAD:%s" % path, check=False).strip()
    if at_head != (h[0] if h else ""):  # h None: the human deleted base's card in the PR
        raise HeraldError("%s differs from the PR head (a local edit) — not a human's OG change" % path)


def _settle_base_card(root, cfg, tid, path, base):
    """Without a card of its own (`kept`, or `off` but for an accepted human file) the OG path
    holds base's card or nothing: any other file there goes under removed/, and base's card comes
    back when it is gone (implementation review M1 — every exit of `og`, early returns included)."""
    cur = file_hashes(root, path)
    if cur and cur[0] != base:
        move_to_removed(root, tid, [path], "og-off", area="images")
    if base and not os.path.isfile(os.path.join(root, path)):
        git(root, "checkout", "origin/%s" % cfg.base, "--", path, check=False)


def og(root, cfg, tid, human_push=False, pr=None):
    from .shots import image_size
    from .store import load_state, save_state
    st = load_state(root, tid)
    slug = st.get("slug")
    if not slug:
        raise HeraldError("no slug yet for %s" % tid)
    o = og_conf(cfg)
    if o is None or not og_on(root, cfg):
        return {"status": "off", "why": "not-configured" if o is None else "config", "unknown_file": None,
                "file": None, "by": None, "problems": [], "warnings": []}
    if human_push:
        _human_only("og --human-push")
    by = "repo" if o["command"] is not None else "limner"
    path = cfg.og_path(slug)
    q = quotation_files(root, cfg, slug)
    h = file_hashes(root, path)
    if h and _is_quotation(h, q):
        raise HeraldError(og_quotation_problem(root, cfg, slug) or "%s is a quotation image" % path)
    rec = st.setdefault("images", {})
    prev = rec.get("og") or {}
    base = _base_blob(root, cfg, path)
    v = og_inputs(root, cfg, st)
    key = og_key(root, cfg, st, v)
    res = {"status": None, "why": None, "unknown_file": None, "file": path, "by": by, "problems": [], "warnings": []}
    draft = st.get("stage") == "draft" and _on_branch(root, tid, st)
    if h and h[0] != prev.get("sha") and h[0] != base:
        if human_push:
            _accept_human_og(root, cfg, tid, path, h, pr)
            with open(os.path.join(root, path), "rb") as fh:
                size = image_size(fh.read())
            for x in q:
                if x.get("file") and os.path.isfile(os.path.join(root, x["file"])):
                    with open(os.path.join(root, x["file"]), "rb") as fh:
                        if size and image_size(fh.read()) == size:
                            res["warnings"].append("og-size-matches-quotation")
                            break
            rec["og"] = {"key": key, "status": "off", "why": "human-file", "sha": h[0], "by": by}
            save_state(root, tid, st)
            res.update(status="off", why="human-file")
            return res
        if not draft:  # the PR stage: never moved, a human decides (`--human-push`)
            res.update(status="needs-human", unknown_file=path)
            return res
        move_to_removed(root, tid, [path], "og-unknown", area="images")
        h = None
    elif not h and base and not draft and prev.get("why") != "human-deleted":
        # the PR stage: a human removed base's card — a deletion is asked like an unknown file,
        # never silently undone (implementation review n1)
        if human_push:
            _accept_human_og(root, cfg, tid, path, None, pr)
            rec["og"] = {"key": key, "status": "off", "why": "human-deleted", "by": by}
            save_state(root, tid, st)
            res.update(status="off", why="human-deleted")
            return res
        res.update(status="needs-human", unknown_file="%s (deleted)" % path)
        return res
    # 3: nothing to do when the inputs and the file are as recorded
    if prev.get("key") == key:
        why = prev.get("why") or ""
        if (prev.get("status") == "made" and h and h[0] == prev.get("sha")) or prev.get("status") == "kept" or \
                (prev.get("status") == "off" and (why in OG_CONTENT_WHY or why.startswith("bad-value:") or
                                                  why in ("human-file", "human-deleted"))):
            if prev.get("status") in ("kept", "off") and why not in ("human-file", "human-deleted"):
                _settle_base_card(root, cfg, tid, path, base)
            res.update(status=prev["status"], why=prev.get("why"), by=prev.get("by", by))
            return res
    refresh = _is_refresh(root, tid, st)
    base_v = og_inputs(root, cfg, st, rev="origin/%s" % cfg.base) if base and refresh else None
    same_as_base = base_v is not None and all(base_v.get(k) == v.get(k) for k in ("title", "subtitle", "slug", "date",
                                                                                     "category", "lang"))
    bad = og_bad_value(cfg, v)
    if bad:
        status, why, probs = "off", "bad-value:%s" % bad, []
    elif refresh and base and same_as_base:  # 4: the base card already shows these inputs
        status, why, probs = "kept", None, []
    else:
        if h and h[0] != base:  # Herald's earlier card or an accepted human file: kept under removed/ (P9)
            move_to_removed(root, tid, [path], "og-replaced", area="images")
            h = None
        if by == "limner":
            status, why, probs = _og_limner(root, cfg, tid, path, v)
        else:
            status, why, probs = _og_repo(root, cfg, tid, path, v)
    res["problems"] = probs
    if status == "made":
        rec["og"] = {"key": key, "status": "made", "sha": blob(root, path), "by": by}
    else:
        _settle_base_card(root, cfg, tid, path, base)  # this topic's own card goes; base's stays
        rec["og"] = {"key": key, "status": status, "by": by}
        if status == "off":
            rec["og"]["why"] = why
            rec["og"]["stale_base"] = bool(refresh and base and not same_as_base)
    save_state(root, tid, st)
    res.update(status=status, why=why)
    return res


def og_trial(root, cfg):
    """`HRD image og --trial`: one card with fixed values; nothing recorded, the result deleted
    (limner: under the state dir; repo: the published path and any folder it created)."""
    o = og_conf(cfg)
    if o is None:
        raise HeraldError("images.og is not configured")
    errs = og_errors(root, cfg)
    if errs:
        return {"ok": False, "by": None, "why": "config", "errors": errs}
    from .store import load_topics
    import datetime
    cats = [t.get("category") for t in load_topics(root).get("topics") or [] if t.get("category")]
    v = {"title": "Herald OG trial", "subtitle": None, "slug": "herald-og-trial",
         "date": datetime.date.today().isoformat(), "category": cats[0] if cats else "general", "lang": lang_tag(cfg)}
    if o["command"] is None:
        if limner.limner_errors(cfg):
            return {"ok": False, "by": "limner", "why": "config", "errors": limner.limner_errors(cfg)}
        sd = limner.state_dir_abs(root, cfg)
        name = limner._stamp()
        d = os.path.join(sd, limner.TRIAL_DIR)
        os.makedirs(d, exist_ok=True)
        try:
            status, why, probs = _og_limner(root, cfg, "trial", None, v, out_abs=os.path.join(d, name + ".png"),
                                            data_rel=os.path.relpath(os.path.join(d, name + ".json"),
                                                                     os.path.realpath(root)))
        finally:
            limner._clean_outputs(root, cfg, limner.TRIAL_DIR)
        return {"ok": status == "made", "by": "limner", "why": why, "problems": probs}
    path = cfg.og_path(v["slug"])
    full = os.path.join(root, path)
    existing = set()
    d = os.path.dirname(full)
    while d.startswith(os.path.realpath(root)) or d.startswith(root):
        if os.path.isdir(d):
            existing.add(d)
        if d in (root, os.path.realpath(root)):
            break
        d = os.path.dirname(d)
    try:
        status, why, probs = _og_repo(root, cfg, None, path, v)
    finally:
        if os.path.isfile(full):
            os.remove(full)
        d = os.path.dirname(full)
        while d not in existing and d not in (root, os.path.realpath(root)) and len(d) > len(root):
            try:
                os.rmdir(d)
            except OSError:
                break
            d = os.path.dirname(d)
    return {"ok": status == "made", "by": "repo", "why": why, "problems": probs}


# --- status, note, resume (§2.9, §2.13) ----------------------------------------------------------

def note_items(st):
    """External and scene images waiting for a human's look: `e1(confirm)`, `g1(confirm)`."""
    items = ((st or {}).get("images") or {}).get("items") or {}
    wait = {"external": "fetched", "scene": "generated"}
    return ["%s(confirm)" % k for k, r in sorted(items.items(), key=lambda kv: ("eg".find(kv[0][:1]), _num(kv[0])))
            if isinstance(r, dict) and wait.get(r.get("kind")) == r.get("status")]


def resume_at_collect(root, cfg, st):
    rec = st.get("images") or {}
    if st.get("stage") != "draft" or not rec.get("awaiting") or not st.get("slug"):
        return False
    return rec.get("manifest") == _hash(root, manifest_rel(st["topic_id"])) and \
        rec.get("body") == _hash(root, cfg.body_path(st["slug"]))


def _confirmed_text(led, h, tid, iid, key, ready):
    """The PR row's confirmation (11-ship-consent.md §2.4): the item's own line first (a human's
    before an agent's), else a human's line of the same content; an agent's shows its review."""
    line = led.confirm_line(h, tid, iid, key) if h else None
    if line and line.get("by") == "agent":
        return "agent-reviewed (no human look): %s" % (line.get("note") or "")
    if line:
        return "confirmed %s" % line.get("at")
    return "confirmed" if ready else "not confirmed"


def status(root, cfg, tid, rev=None):
    from .shots import hold_note
    from .store import load_state, read_json_at
    st = (read_json_at(root, rev, _work_rel(tid, "state.json")) if rev else load_state(root, tid)) or {}
    errors = []
    try:
        man = load_manifest(root, tid, rev)
    except HeraldError as e:
        man, errors = None, [str(e)]
    rec = st.get("images") or {}
    led = Ledger(root)
    slug = st.get("slug")
    lines, dropped = slug_renders(root, cfg, slug, rev) if slug else ([], 0)
    out_items, snippets, rows, prompts, licenses, warnings = [], [], [], [], set(), []
    agent_ok = []
    pend = {"render": [], "render_after_push": [], "fetch": [], "generate": [], "review": [], "confirm": [],
            "review_scene": [], "review_external": []}  # the two parts of `review` (each its own reviewer)
    body = _body(root, cfg, slug, rev) if slug else ""
    for it in _items(man):
        iid, kind = it.get("id"), it.get("kind")
        r = (rec.get("items") or {}).get(iid) or {}
        row = {"id": iid, "kind": kind, "file": it.get("file"), "alt": it.get("alt"), "purpose": it.get("purpose")}
        if kind == "diagram" and slug:
            s, E = diagram_state(root, cfg, tid, st, it, lines, strict=not rev, rev=rev)
            row.update(status=s, texts=len(E["texts"]) if E else None)
            if s == "pending":
                pend["render"].append(iid)
            if not rev and pushed_change(root, cfg, tid, st, it, lines):
                pend["render_after_push"].append(iid)
            claims = sorted({c for t in it.get("texts") or [] if isinstance(t, dict) for c in t.get("claims") or []})
            rows.append("| %s | diagram | %s | %d texts%s — drawn in %s |" % (
                iid, it.get("file"), len(it.get("texts") or []), (", claims " + ", ".join(claims)) if claims else "",
                lang_tag(cfg)))
        elif kind == "scene" and slug:
            cur = cur_path(root, cfg, slug, it.get("file"))
            key = scene_key(cfg, it)
            s = scene_state(root, cfg, tid, it, led, rev, path=cur)
            h = _rev_hashes(root, rev, cur)
            replaced = bool(r.get("sha") and h and h[0] != r["sha"])
            line = led.gen_line(h, tid, iid, key) if h else None
            row.update(status=s, size=it.get("size"), seed=it.get("seed"), prompt=it.get("prompt"),
                       generated_at=r.get("generated_at"), replaced=replaced, why=scene_fail_closed(tid, iid, r, led),
                       reviewed=bool(h and r.get("reviewed") == h[0]), review_note=r.get("review_note"),
                       regenerated=bool(r.get("regenerated")),
                       attempts=scene_attempts(st, iid))
            if s == "pending":
                pend["generate"].append(iid)
            elif s == "generated":
                pend["confirm"].append(iid)
                if r.get("reviewed") != h[0]:
                    pend["review"].append(iid)
                    pend["review_scene"].append(iid)
            if s == "ready" and led.confirmed_by(h, tid, iid, key) == "agent":
                agent_ok.append({"id": iid, "kind": "scene", "note": r.get("review_note")})
            if rev and r.get("key") and r["key"] != key:  # ship §5: a human changed the prompt, not the picture
                warnings.append("%s: the manifest and the picture differ — the next refresh generates it again" % iid)
            if scene_label(cfg):
                sn = snippet_text(cfg, it, None, root, slug)
                snippets.append({"id": iid, "text": sn, "alt": it.get("alt"), "in_body": body.count(sn)})
            model = ((line or {}).get("model") or {}).get("name") or limner.GEN_MODEL
            if (line or {}).get("model_license"):
                licenses.add("%s: %s" % (model, line["model_license"]))
            rows.append("| %s | scene (AI-generated) | %s | %s seed %s · %s · %s%s |" % (
                iid, it.get("file"), model, it.get("seed"), it.get("size"),
                _confirmed_text(led, h, tid, iid, key, s == "ready"), ", replaced by a human" if replaced else ""))
            prompts.append("- %s: `%s`" % (iid, str(it.get("prompt")).replace("`", "'")))
        elif kind == "external" and slug:
            cur = cur_path(root, cfg, slug, it.get("file"))
            s = external_state(root, tid, it, led, rev, path=cur)
            h = _rev_hashes(root, rev, cur)
            replaced = bool(r.get("sha") and h and h[0] != r["sha"])
            row.update(status=s, use=it.get("use"), credit=it.get("credit"), license=it.get("license"),
                       page_url=it.get("page_url"), source_url=it.get("source_url"), fetched_at=r.get("fetched_at"),
                       replaced=replaced, why=fail_closed(tid, iid, r, led))
            if s == "pending":
                pend["fetch"].append(iid)
            elif s == "fetched":
                pend["confirm"].append(iid)
                if not h or r.get("reviewed") != h[0]:  # 0.20.0: the agent review of a `--ship` run
                    pend["review"].append(iid)
                    pend["review_external"].append(iid)
            if s == "ready" and led.confirmed_by(h, tid, iid, item_key(it)) == "agent":
                agent_ok.append({"id": iid, "kind": "quotation" if it.get("use") == "quotation" else "external",
                                 "note": r.get("review_note")})
            if r.get("orientation") and r.get("key") == item_key(it) and figure(cfg).get(it.get("use")):
                sn = snippet_text(cfg, it, r.get("orientation"), root, slug)
                snippets.append({"id": iid, "text": sn, "alt": it.get("alt"), "in_body": body.count(sn)})
            what = ("licensed %s" % it.get("license")) if it.get("use") == "licensed" else \
                "**quotation — no OG/SNS use**"
            rows.append("| %s | external | %s | %s, %s, %s, %s%s |" % (
                iid, it.get("file"), what, it.get("credit"), it.get("page_url"),
                _confirmed_text(led, h, tid, iid, item_key(it), s == "ready"),
                ", replaced by a human" if replaced else ""))
        out_items.append(row)
    og_rec = rec.get("og") or {}
    og_line = None
    if og_conf(cfg) and slug:
        if og_rec.get("status") == "made":
            og_line = "OG image: %s (%s)" % (cfg.og_path(slug), og_rec.get("by"))
        elif og_rec.get("status") == "kept":
            og_line = "OG image: %s (kept from %s)" % (cfg.og_path(slug), cfg.base)
        elif og_rec.get("status") == "off" and og_rec.get("why") == "human-file":
            og_line = "OG image: %s (a human's file)" % cfg.og_path(slug)
        elif og_rec.get("status") == "off":
            og_line = ("OG image: old title kept (%s)" if og_rec.get("stale_base") else "OG image: none (%s)") \
                % og_rec.get("why")
    agent_no = [{"id": x.get("id"), "drop": bool(x.get("drop")), "reason": x.get("reason")}
                for x in st.get("image_rejects") or [] if isinstance(x, dict) and x.get("by") == "agent"]
    pr_rows = (["| id | kind | file | content |", "|---|---|---|---|"] + rows) if rows else []
    for x in agent_no:  # a place the agent review left out (11-ship-consent.md §2.4)
        if x["drop"]:
            pr_rows.append("%s: left out after the agent review (no human look): %s" % (x["id"], x["reason"] or ""))
    if prompts:  # what the model was asked (style and NO_TEXT are the repo's, not shown)
        pr_rows += ["<details><summary>Scene prompts</summary>", ""] + prompts + ["", "</details>"]
        if licenses:
            pr_rows.append("Scene model license: %s" % "; ".join(sorted(licenses)))
        oc = og_conf(cfg)
        if oc and oc["fallback_first_image"] and og_rec.get("status") == "off":
            first = next((x["id"] for x in out_items if x.get("kind") == "scene"), "g1")
            og_line = "OG image: none — the site may use the first image (AI-generated %s) as the card" % first
    if og_line:
        pr_rows.append(og_line)
    unmanaged = []
    if managed(cfg) and slug and not rev:
        known = managed_files(root, cfg, tid, st)
        try:
            from .shots import load_manifest as shot_manifest
            known |= {s.get("file") for s in (shot_manifest(root, tid) or {}).get("shots") or [] if isinstance(s, dict)}
        except HeraldError:
            pass
        unmanaged = sorted(p for p in git(root, "ls-files", "--others", "--exclude-standard", "--",
                                          cfg.image_dir(slug), check=False).splitlines() if p and p not in known)
        if unmanaged:
            pr_rows.append("Unmanaged images (0.14.0 rule, text not verified): %s" % ", ".join(unmanaged))
    return {"items": out_items, "pending": pend, "errors": errors,
            "all_ready": bool(out_items) and all(i.get("status") == "ready" for i in out_items),
            "awaiting": bool(rec.get("awaiting")), "resume_at_collect": resume_at_collect(root, cfg, st) if not rev else False,
            "note": hold_note(st), "files": rec.get("files") or {}, "snippets": snippets, "pr_rows": pr_rows,
            "og": og_rec, "rejects": st.get("image_rejects") or [], "unmanaged": unmanaged,
            "agent": {"confirmed": agent_ok, "rejected": agent_no},
            "renders_dropped": dropped, "warnings": warnings, "gen": rec.get("gen"),
            "gen_out_bytes": _gen_out_bytes(root, cfg, tid) if not rev else 0,
            "removed_bytes": removed_bytes(root, tid, "images")}


def _gen_out_bytes(root, cfg, tid):
    """The bytes in limner's output folder for this topic (shown, never deleted — §2.4.4)."""
    if limner.limner_errors(cfg, check_ignored=False) or not limner.configured(cfg):
        return 0
    d = os.path.join(_gen_paths(root, cfg, tid)[0], limner.OUT_DIR, tid)
    return sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fns in os.walk(d) for f in fns)


# --- stage pass, publish scope, exclusions (§2.10, §2.12, §2.13) ----------------------------------

def draft_problems(root, cfg, tid, st):
    out = []
    try:
        man = load_manifest(root, tid)
    except HeraldError as e:
        return [str(e)]
    rec = st.get("images") or {}
    items = _items(man)
    slug = st["slug"]
    led = Ledger(root)
    if items:
        if not rec.get("items") and rec.get("manifest") is None:
            return out + ["images.json is not planned — run `HRD image plan --topic %s`" % tid]
        if rec.get("manifest") != _hash(root, manifest_rel(tid)):
            out.append("images.json changed since `HRD image plan` — run it again")
        if rec.get("body") != _hash(root, cfg.body_path(slug)):
            out.append("the article changed since `HRD image plan` — run it again")
        if {i.get("id") for i in items} != set(rec.get("items") or {}):
            out.append("images.json lists other images than were planned — run `HRD image plan` again")
        if any(it.get("kind") in ("external", "scene") for it in items):
            led.check(1)
        lines, _ = slug_renders(root, cfg, slug)
        body = _body(root, cfg, slug)
        for it in items:
            iid = it.get("id")
            r = (rec.get("items") or {}).get(iid) or {}
            if it.get("kind") == "diagram":
                if diagram_state(root, cfg, tid, st, it, lines)[0] != "ready":
                    out.append("%s: %s is not the render of the current SVG and settings — `HRD image render --topic %s "
                               "--id %s`" % (iid, it.get("file"), tid, iid))
                continue
            if it.get("kind") == "scene":
                out += _scene_draft_problems(root, cfg, tid, slug, it, r, led, body, st)
                continue
            why = fail_closed(tid, iid, r, led, it)
            if why:
                out.append(why)
                continue
            s = external_state(root, tid, it, led)
            if s == "fetched":
                out.append("%s is waiting for a human's confirmation — look at %s, then `HRD image confirm --topic %s "
                           "--id %s` (or `HRD image reject`)" % (iid, it.get("file"), tid, iid))
            elif s != "ready":
                out.append("%s is not fetched (or not the file `HRD image fetch` wrote) — `HRD image plan`, then `HRD "
                           "image fetch --topic %s --id %s`" % (iid, tid, iid))
            elif figure(cfg).get(it.get("use")):
                sn = snippet_text(cfg, it, r.get("orientation"), root, slug)
                if body.count(sn) != 1:
                    out.append("%s: the attribution must be in the article verbatim exactly once (found %d) — `HRD "
                               "image snippet --topic %s --id %s`" % (iid, body.count(sn), tid, iid))
    elif rec.get("items"):
        out.append("images.json is gone but images are recorded — run `HRD image plan --topic %s`" % tid)
    # rule U over Herald's own image files (shots.draft_problems leaves them to this function)
    current = {i.get("file") for i in items}
    for f in rec.get("files") or {}:
        h = file_hashes(root, f)
        if h and led.unconfirmed(h) and f not in current:
            out.append("%s is an external or scene image no human or agent confirmed — `HRD image plan --topic %s` moves it away"
                       % (f, tid))
    left = [f for f in rec.get("files") or {} if f not in current and os.path.isfile(os.path.join(root, f))
            and not on_base(root, cfg, f)]
    if left:
        out.append("images no longer listed are still in place: %s — run `HRD image plan --topic %s`" % (", ".join(left), tid))
    out += og_draft_problems(root, cfg, tid, st)
    return out


def _scene_draft_problems(root, cfg, tid, slug, it, r, led, body, st=None):
    iid = it.get("id")
    if st is not None and scene_key(cfg, it) in rejected_scene_keys(st, iid):
        # a picture whose key a review or a human turned down never passes draft (review 24 MAJOR-2)
        return ["%s: this picture's key was turned down (a review's redo or a reject) — change the seed or the prompt "
                "of %s, then `HRD image plan --topic %s`" % (iid, iid, tid)]
    why = scene_fail_closed(tid, iid, r, led)
    if why:
        return [why]
    s = scene_state(root, cfg, tid, it, led)
    if s == "generated":
        return ["%s is waiting for a human's confirmation — look at %s, then `HRD image confirm --topic %s --id %s` (or "
                "`HRD image reject`)" % (iid, it.get("file"), tid, iid)]
    if s != "ready":
        return ["%s is not generated (or not the file `HRD image generate` wrote) — `HRD image plan`, then `HRD image "
                "generate --topic %s`" % (iid, tid)]
    if scene_label(cfg):
        c = body.count(snippet_text(cfg, it, None, root, slug))
        if c != 1:
            return ["%s: the picture with its AI label must be in the article verbatim exactly once (found %d) — `HRD "
                    "image snippet --topic %s --id %s`" % (iid, c, tid, iid)]
    return []


def og_draft_problems(root, cfg, tid, st):
    slug = st["slug"]
    q = og_quotation_problem(root, cfg, slug)
    if q:
        return [q]
    if not og_on(root, cfg):
        return []
    og_rec = ((st.get("images") or {}).get("og")) or {}
    path = cfg.og_path(slug)
    if not og_rec or og_rec.get("key") != og_key(root, cfg, st):
        return ["the OG image is not made for the current title — `HRD image og --topic %s` (it records `off` when it "
                "cannot make one)" % tid]
    h = file_hashes(root, path)
    base = _base_blob(root, cfg, path)
    if og_rec.get("status") == "made":
        if not h or h[0] != og_rec.get("sha"):
            return ["%s is not the OG image Herald made — `HRD image og --topic %s`" % (path, tid)]
    elif base and og_rec.get("why") not in ("human-file", "human-deleted") and (not h or h[0] != base):
        # base's card is never ours to take or replace without a card of our own (review M1)
        return ["%s must be %s's published OG card (this topic made none) — `HRD image og --topic %s` puts it "
                "back" % (path, cfg.base, tid)]
    elif h and h[0] != og_rec.get("sha") and h[0] != base:
        return ["%s is no OG file Herald knows — `HRD image og --topic %s` (a human's own OG goes into the PR)"
                % (path, tid)]
    return []


def verify_problems(root, cfg, tid, st, ver, amend=False):
    """§2.12: the drawn text was read and supported; the drawn text is the text verified."""
    out = []
    try:
        man = load_manifest(root, tid)
    except HeraldError as e:
        return [str(e)]
    items = _items(man)
    slug = st["slug"]
    diagrams = [i for i in items if i.get("kind") == "diagram"]
    if diagrams:
        lines, _ = slug_renders(root, cfg, slug)
        drawn = 0
        for it in diagrams:
            s, E = diagram_state(root, cfg, tid, st, it, lines, strict=not amend)
            if not E:
                out.append("%s: its PNG is no render Herald recorded — the drawn text is unknown (render it from the SVG: "
                           "`HRD image render --topic %s --id %s`)" % (it.get("id"), tid, it.get("id")))
                continue
            if s != "ready":
                out.append("%s: the PNG is not the render of the current SVG and settings — render it again"
                           % it.get("id"))
            drawn += len(E["texts"])
        vi = (ver or {}).get("images") if isinstance((ver or {}).get("images"), dict) else {}
        if not out and vi.get("texts") != drawn:
            out.append("verify.json images.texts is %r but the diagrams draw %d texts — the fact-checker reads every "
                       "one (`HRD image texts --topic %s`)" % (vi.get("texts"), drawn, tid))
        if vi.get("unsupported"):
            out.append("verify.json images.unsupported is not empty — `HRD loopback --cause verify --note \"image text: "
                       "…\"` (the illustrator fixes or drops the diagram)")
    body = _body(root, cfg, slug)
    rec = st.get("images") or {}
    for it in items:
        if it.get("kind") == "scene" and scene_label(cfg):
            if body.count(snippet_text(cfg, it, None, root, slug)) != 1:
                out.append("%s: the picture with its AI label is not in the article verbatim exactly once — put it back "
                           "as `HRD image snippet` gives it" % it.get("id"))
            continue
        if it.get("kind") != "external":
            continue
        r = (rec.get("items") or {}).get(it.get("id")) or {}
        if figure(cfg).get(it.get("use")) and r.get("orientation"):
            sn = snippet_text(cfg, it, r.get("orientation"), root, slug)
            if body.count(sn) != 1:
                out.append("%s: the attribution is not in the article verbatim exactly once — put it back as `HRD image "
                           "snippet` gives it" % it.get("id"))
    q = og_quotation_problem(root, cfg, slug)
    if q:
        out.append(q)
    return out


def svg_drift(root, cfg, tid, st):
    """Warnings for a published diagram whose SVG source no longer matches the drawn PNG."""
    out = []
    try:
        man = load_manifest(root, tid)
    except HeraldError:
        return out
    lines, dropped = slug_renders(root, cfg, st["slug"])
    for it in _items(man):
        if it.get("kind") != "diagram":
            continue
        E = find_render(lines, file_hashes(root, cur_path(root, cfg, st["slug"], it.get("file"))))
        if E and E.get("svg_sha256") != _svg_sha(root, tid, it.get("id")):
            out.append("%s: the SVG source differs from the published picture — the next refresh renders it again"
                       % it.get("id"))
    if dropped:
        out.append("diagram render records: %d damaged line(s) ignored" % dropped)
    return out


def scope_problems(root, cfg, tid, publish=False):
    """`HRD scope` at publish (no --rev — never at ship, L6): every external item's HEAD content
    confirmed, fail-closed, attributions in place, no quotation at the OG path."""
    if not publish:
        return []
    from .store import load_state
    st = load_state(root, tid)
    if not st.get("slug"):
        return []
    out = []
    try:
        man = load_manifest(root, tid)
    except HeraldError as e:
        return [str(e)]
    rec = st.get("images") or {}
    led = Ledger(root)
    body = _body(root, cfg, st["slug"], "HEAD")
    for it in _items(man):
        iid = it.get("id")
        if it.get("kind") == "scene":
            r = (rec.get("items") or {}).get(iid) or {}
            why = scene_fail_closed(tid, iid, r, led)
            if why:
                out.append(why)
                continue
            if scene_state(root, cfg, tid, it, led, rev="HEAD") != "ready":
                out.append("%s: the committed file is not a generated scene a human confirmed — `HRD image confirm` "
                           "before publishing" % iid)
            if scene_label(cfg) and body.count(snippet_text(cfg, it, None, root, st["slug"])) != 1:
                out.append("%s: the picture with its AI label is not in the committed article exactly once" % iid)
            continue
        if it.get("kind") != "external":
            continue
        r = (rec.get("items") or {}).get(iid) or {}
        why = fail_closed(tid, iid, r, led, it)
        if why:
            out.append(why)
            continue
        if external_state(root, tid, it, led, rev="HEAD") != "ready":
            out.append("%s: the committed file is not an external image a human confirmed — `HRD image confirm` before "
                       "publishing" % iid)
        if figure(cfg).get(it.get("use")) and r.get("orientation") and \
                body.count(snippet_text(cfg, it, r.get("orientation"), root, st["slug"])) != 1:
            out.append("%s: the attribution is not in the committed article exactly once" % iid)
    q = og_quotation_problem(root, cfg, st["slug"], rev="HEAD")
    if q:
        out.append(q)
    out += label_problems(root, cfg, tid, st, rev="HEAD")
    return out


def excluded_external(root, cfg, tid, rev, changed):
    """`external-images` (no consent lifts it), fail-closed (§2.13)."""
    from .store import read_json_at
    st = (read_json_at(root, rev, _work_rel(tid, "state.json")) if rev else
          read_json(os.path.join(root, _work_rel(tid, "state.json")))) or {}
    files = ((st.get("images") or {}).get("files")) or {}
    try:
        man = load_manifest(root, tid, rev=rev)
    except HeraldError:
        return bool(files)
    if any(i.get("kind") == "external" for i in _items(man)):
        return True
    return any(isinstance(m, dict) and m.get("kind") == "external" and f in changed for f, m in files.items())


def og_excluded(root, cfg, tid, rev, changed, slug):
    """The `images` exclusion's OG part: an outside OG path in the diff, or a stale base card."""
    from .store import read_json_at
    out = cfg.og_outside(slug) if og_conf(cfg) else None
    if out and out in changed and not tid.startswith("tr-"):
        return True
    st = (read_json_at(root, rev, _work_rel(tid, "state.json")) if rev else
          read_json(os.path.join(root, _work_rel(tid, "state.json")))) or {}
    return bool((((st.get("images") or {}).get("og")) or {}).get("stale_base"))


def unvouched(root, cfg, tid, rev, slug):
    """`images-unconfirmed` (11-ship-consent.md §9 R2-5, §10 R3-2, m3): the files a PR adds or
    changes under the image directory (and an OG path outside it), each judged by its content at
    `rev` — a diagram by a render record, the OG card by its record, an external image or scene by
    a confirmation line (a human's of this content, or an agent's of this very item), a human's
    screenshot by its import record, an automatic one by a confirmation line. Anything else — a
    file no record knows, a record of other bytes — is returned. Deleted paths are not judged; a
    rename is judged at its new path."""
    from . import shots as shots_mod
    from .store import read_json_at
    rng = "origin/%s...%s" % (cfg.base, rev or "HEAD")
    names = [p for p in git(root, "diff", "--name-only", "-z", "--no-renames", "--diff-filter=d", rng,
                            check=False).split("\0") if p]
    img = cfg.image_dir(slug).rstrip("/") + "/"
    og_out = cfg.og_outside(slug)
    targets = [p for p in names if p.startswith(img) or (og_out and p == og_out)]
    if not targets:
        return []
    st = (read_json_at(root, rev, _work_rel(tid, "state.json")) if rev else
          read_json(os.path.join(root, _work_rel(tid, "state.json")))) or {}
    try:
        man = load_manifest(root, tid, rev)
    except HeraldError:
        man = None
    try:
        sman = shots_mod.load_manifest(root, tid, rev=rev) if rev else shots_mod.load_manifest(root, tid)
    except HeraldError:
        sman = None
    led = Ledger(root)
    lines, _ = slug_renders(root, cfg, slug, rev)
    ogp = cfg.og_path(slug) if og_conf(cfg) else None
    og_rec = ((st.get("images") or {}).get("og")) or {}
    by_file = {}
    for it in _items(man):
        for f in {it.get("file"), cur_path(root, cfg, slug, it.get("file"))}:
            if f:
                by_file[f] = ("image", it)
    for x in (sman or {}).get("shots") or []:
        if isinstance(x, dict) and x.get("file"):
            by_file.setdefault(x["file"], ("shot", x))
    shot_recs = ((st.get("screenshots") or {}).get("shots")) or {}
    out = []
    for p in targets:
        h = _rev_hashes(root, rev, p)
        ok = False
        if h and h[1]:
            what, it = by_file.get(p, (None, None))
            if ogp and p == ogp:
                ok = bool(og_rec.get("sha")) and og_rec.get("sha") == h[0]
            elif what == "image" and it.get("kind") == "diagram":
                ok = find_render(lines, h) is not None
            elif what == "image" and it.get("kind") == "external":
                ok = led.confirmed_for(h, tid, it.get("id"), item_key(it))
            elif what == "image" and it.get("kind") == "scene":
                ok = led.confirmed_for(h, tid, it.get("id"), scene_key(cfg, it))
            elif what == "shot":
                r = shot_recs.get(it.get("id")) or {}
                if r.get("capture") == "auto" or led.logged(h):
                    ok = led.confirmed_for(h, tid, it.get("id"), r.get("key"))
                else:  # a human's screenshot: the blob `HRD shot import` recorded
                    ok = r.get("status") == "ready" and bool(r.get("sha")) and r.get("sha") == h[0]
        if not ok:
            out.append(p)
    return sorted(out)


_BASE_MANAGED = {}
MANAGED_ON_BASE = ("external", "scene")  # kinds a translation repo cannot carry (08 §2.6.7, 09 §2.9)


def _git_run(root, args, data=None):
    """One git process (bytes in, bytes out) — `managed_on_base`'s only way to read base, so
    tests can count what it costs."""
    import subprocess
    return subprocess.run(["git"] + list(args), cwd=root, input=data, capture_output=True)


def _ref_stamp(root, base):
    """When origin/<base> last moved, without a git process (the loose ref and packed-refs
    files); None when .git is not a plain directory (then the cache lives for the process)."""
    g = os.path.join(root, ".git")
    if not os.path.isdir(g):
        return None
    out = []
    for p in (os.path.join(g, "refs", "remotes", "origin", base), os.path.join(g, "packed-refs")):
        try:
            st = os.stat(p)
            out.append((st.st_mtime_ns, st.st_size))
        except OSError:
            out.append(None)
    return tuple(out)


def _base_managed_map(root, cfg):
    """{slug: [(recorded file, kind)]} of external and scene images from every committed state on
    origin/<base>, built once per base commit and process (implementation review M4): one `git
    grep` finds the states that record one at all — none (any repo that never fetched or generated
    one, managed or not) → empty at once —, then one `git cat-file --batch` reads only those."""
    ref = "origin/%s" % cfg.base
    key = (os.path.realpath(root), ref, _ref_stamp(root, cfg.base))
    if key in _BASE_MANAGED:
        return _BASE_MANAGED[key]
    out = {}
    g = _git_run(root, ["grep", "-l", "-F", "-e", '"external"', "-e", '"scene"', ref, "--", ".claude/herald/work"])
    paths = [x.split(":", 1)[1] for x in g.stdout.decode("utf-8", "replace").splitlines()
             if ":" in x and x.endswith("/state.json") and x.split(":", 1)[1].count("/") == 4]
    if paths:
        b = _git_run(root, ["cat-file", "--batch"], "".join("%s:%s\n" % (ref, x) for x in paths).encode())
        data, pos = b.stdout, 0
        while pos < len(data):
            nl = data.find(b"\n", pos)
            if nl < 0:
                break
            head = data[pos:nl].split()
            pos = nl + 1
            if len(head) < 3 or head[1] != b"blob":
                continue
            n = int(head[2])
            raw, pos = data[pos:pos + n], pos + n + 1
            try:
                st = json.loads(raw.decode("utf-8"))
            except ValueError:
                continue
            if not isinstance(st, dict) or not st.get("slug"):
                continue
            for f, m in (((st.get("images") or {}).get("files")) or {}).items():
                if isinstance(m, dict) and m.get("kind") in MANAGED_ON_BASE:
                    out.setdefault(st["slug"], []).append((f, m["kind"]))
    _BASE_MANAGED[key] = out
    return out


def managed_on_base(root, cfg, slug, kinds=False):
    """Files of `slug` (moved slugs too) recorded as external or scene images in a committed
    state on origin/<base> and present there — the same on every machine (08 §2.6.7, 09 §2.9;
    0.17.0's `external_on_base` widened). `kinds`: [(file, kind)] instead of files. Costs one
    `git grep` per command when no state on base records such an image."""
    ref = "origin/%s" % cfg.base
    emap = _base_managed_map(root, cfg)
    if not emap:
        return []
    olds = set(_old_slugs(root, slug)) | {slug}
    by = {}
    for s_ in olds:
        for f, k in emap.get(s_, []):
            by.setdefault(cur_path(root, cfg, slug, f), k)
    cand = sorted(by)
    if not cand:
        return []
    chk = _git_run(root, ["cat-file", "--batch-check"], "".join("%s:%s\n" % (ref, p) for p in cand).encode())
    lines = chk.stdout.decode("utf-8", "replace").splitlines()
    found = [p for p, line in zip(cand, lines) if not line.endswith(" missing")]
    return [(p, by[p]) for p in found] if kinds else found


def blocked_reason(found):
    """`external-images` when any external image blocks, else `scene-images` ([(file, kind)])."""
    return "external-images" if any(k == "external" for _, k in found) else "scene-images"


def drop_blocked_translations(root, cfg, ids):
    """Topic ids minus the translation and refresh topics `HRD begin` would refuse (an article
    with external or scene images on base, translation repos only — 08 §2.6.7, R3-4; 09 §2.9).
    `HRD select` and the batch runner's selection share it (implementation review n2);
    `managed_on_base` reads base once per process."""
    if not cfg.translations():
        return list(ids)
    from .store import load_topics
    topics = {t["id"]: t for t in load_topics(root)["topics"]}
    out = []
    for tid in ids:
        t = topics.get(tid) or {}
        slug = t.get("translate_of") or t.get("refresh_of")
        if not slug or not managed_on_base(root, cfg, slug):
            out.append(tid)
    return out


def all_scene_files(root, cfg):
    """Every file recorded as a scene by any topic — the working tree's states and origin/<base>'s
    — so a reference from another article needs the label too (review round 1 m8)."""
    from .integrity import moved_image_path
    from .store import load_published
    now, olds = {}, {}  # old slug → the article's slug today; today's slug → its old slugs
    for a in load_published(root).get("articles") or []:
        chain = [m["slug"] for m in a.get("moved_from") or [] if isinstance(m, dict) and m.get("slug")]
        if a.get("slug") and chain:
            olds[a["slug"]] = chain
            for o in chain:
                now[o] = a["slug"]

    def path(slug, f):
        # through the move chain whatever slug the state still has (review round 2 m1)
        cur = now.get(slug, slug)
        return moved_image_path(cfg, cur, f, olds.get(cur, [])) if cur else f
    out = set()
    for _, st in _topic_states(root):
        for f, m in (((st.get("images") or {}).get("files")) or {}).items():
            if isinstance(m, dict) and m.get("kind") == "scene":
                out.add(path(st.get("slug"), f))
    for slug, fs in _base_managed_map(root, cfg).items():
        out |= {path(slug, f) for f, k in fs if k == "scene"}
    return out


# what the label check counts as a reference (review round 2 m6): the gate's inline forms, a
# reference-style definition and an unquoted `src=`
REF_DEF_RE = re.compile(r"(?m)^[ \t]{0,3}\[[^\]\n]+\]:[ \t]*<?([^\s>]+)>?")
SRC_BARE_RE = re.compile(r"<img[^>]*\ssrc=([^\s\"'>]+)")


def _host(h):
    h = (h or "").lower()
    return h[4:] if h.startswith("www.") else h


def _local_ref(cfg, raw):
    """`raw` as a path on this site: an absolute URL of this site (any scheme, protocol-relative,
    host case and `www.` ignored) loses its origin; another host gives None."""
    import urllib.parse
    if not (re.match(r"^[a-z][a-z0-9+.-]*:", raw, re.I) or raw.startswith("//")):
        return raw
    u = urllib.parse.urlsplit(raw)
    site = urllib.parse.urlsplit(str(cfg.get("site", "base_url") or ""))
    if u.scheme.lower() not in ("", "http", "https") or not u.hostname or _host(u.hostname) != _host(site.hostname):
        return None
    return u.path or "/"



def label_regex(cfg, ref):
    """The AI label's pattern for one reference: `figure.scene` escaped, `{ref}` the reference,
    `{alt}` any text on the line (no `"` or `<` in an HTML template), `{label}` the label."""
    t = scene_template(cfg)
    alt = r'[^"<\n]*?' if "<" in t else r"[^\n]*?"
    vals = {"ref": re.escape(ref), "alt": alt, "label": re.escape(scene_label(cfg) or "")}
    return re.sub(r"\\\{(ref|alt|label)\\\}", lambda m: vals[m.group(1)], re.escape(t))


def label_problems(root, cfg, tid, st, rev=None):
    """The AI label next to every scene picture in this slug's source body (09 §2.8, Q4) — outside
    `run_gate` (whatever `commands.validate` runs), for every topic of the slug, at draft, verify
    (`--amend` too) and publish `scope`: each reference that resolves to any article's scene file
    (a site-absolute URL of this site too) is matched by the label pattern exactly as many times
    as it is referenced."""
    if not managed(cfg) or not st.get("slug"):
        return []
    slug = st["slug"]
    files = all_scene_files(root, cfg)
    if not files:
        return []
    if not scene_label(cfg):
        return ["scene images of %s need their AI label, and this language has no default — set "
                "images.figure.words.scene" % slug]
    from .validate import IMG_RE, resolve_image_ref
    body_rel = cfg.body_path(slug)
    body = _body(root, cfg, slug, rev)
    pub = _rules(root)["images"].get("public_dir", "public")
    raws = [next(g for g in m.groups() if g) for m in IMG_RE.finditer(body)]
    raws += [m.group(1) for m in SRC_BARE_RE.finditer(body)] + [m.group(1) for m in REF_DEF_RE.finditer(body)]
    refs = Counter()
    for raw in raws:
        path = _local_ref(cfg, raw)
        if path is not None and resolve_image_ref(root, body_rel, path, pub) in files:
            refs[raw] += 1
    out = []
    for raw, n in sorted(refs.items()):
        found = len(re.findall(label_regex(cfg, raw), body))
        if found != n:
            out.append("%s: a scene picture must carry its AI label as `HRD image snippet` gives it (%d of %d "
                       "references have it) — put the label back" % (raw, found, n))
    return out


def snippet_spans(root, cfg, tid, st, text):
    """(start, end) of each external item's attribution in `text` — trim never cuts into one."""
    spans = []
    try:
        man = load_manifest(root, tid)
    except HeraldError:
        return spans
    for it in _items(man):
        r = (((st.get("images") or {}).get("items")) or {}).get(it.get("id")) or {}
        sn = None
        if it.get("kind") == "external" and r.get("orientation") and figure(cfg).get(it.get("use")):
            sn = snippet_text(cfg, it, r["orientation"], root, st.get("slug"))
        elif it.get("kind") == "scene" and scene_label(cfg):  # the AI label is never trimmed away (§2.8)
            sn = snippet_text(cfg, it, None, root, st.get("slug"))
        if sn:
            i = text.find(sn)
            while i >= 0:
                spans.append((i, i + len(sn)))
                i = text.find(sn, i + 1)
    return spans


def config_errors(root, cfg):
    return {"limner_errors": limner.limner_errors(cfg), "og_errors": og_errors(root, cfg),
            "figure_errors": figure_errors(cfg), "scene_errors": scene_errors(cfg)}
