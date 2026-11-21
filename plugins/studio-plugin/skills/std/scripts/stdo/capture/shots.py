"""Board captures as pictures (m2-plan §7): what `capture.py shot` recorded in `work/captures.json`, read back for the
script and board checks, the credits and gate ③. Reads only; capture.py is the one writer.

A shot `<name>` is the picture `assets/capture-<name>.png` (its script_src, relative to the video's folder). It is
usable when its record says ok and both files are still the bytes capture.py recorded (`png_sha`, `json_sha`): a
picture replaced or removed by hand, or a run cut short between the files and the record, is not usable until the
shot is taken again.

Its floor is judged now (not when it was taken), from s2v's JSON of the shot and the current settings, so a changed
`public_domains` or overlay changes it (and with it the credit's `floor`, which the person approves again):
- the page: a host of public_domains → public, any other host (capture.hosts) → third-party;
- every picture inside the captured area (`inCapture`, missing counts as inside): its host as a URL source's page
  picture (public_domains → public, another host → third-party, no host → unknown);
- every frame, canvas, embed or video inside the area (s2v cannot read into it) → unknown;
- the strictest wins (public < unknown < third-party).
Internal is a flag beside the level, as for a source's pictures: the page's final address on an internal host of the
overlay or one of its internal source pages (or under one), an in-house term in that address, in the page's title,
text or a picture's alt text, or a picture inside the area from an internal host. A public video cannot show an
internal picture; when the overlay is required but missing, a public video's captures are not usable (the closed side,
as check_scope).

The credit of a capture carries two more fields from the record — `source` (the asked address) and `captured_at` —
which the question shows and the entry's hash covers, so a new shot of the same name asks the person again."""

import hashlib
import json
import os
import re
import unicodedata

from . import rules

PREFIX = "assets/capture-"
SUFFIX = ".png"
CREDIT_KEYS = ("source", "captured_at")
LEVELS = ("public", "unknown", "third-party")
NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")  # = cli.SHOT_NAME


def script_src(name):
    return "%s%s%s" % (PREFIX, name, SUFFIX)


def name_of(src):
    """The shot's name when `src` is a capture's script_src, else None."""
    if not isinstance(src, str) or not src.startswith(PREFIX) or not src.endswith(SUFFIX):
        return None
    n = src[len(PREFIX):-len(SUFFIX)]
    return n if NAME.match(n) else None


def _sha(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


def records(vdir):
    """{name: record} of work/captures.json ({} when there is none or it cannot be read: nothing is usable then)."""
    try:
        with open(os.path.join(vdir, "work", "captures.json"), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    shots = data.get("shots") if isinstance(data, dict) else None
    return {k: v for k, v in (shots or {}).items() if isinstance(v, dict) and NAME.match(str(k))} \
        if isinstance(shots, dict) else {}


def _verified(vdir, name, rec):
    """(s2v's JSON of the shot, None) when the record says ok and both files are the recorded bytes, else (None, why)."""
    src = script_src(name)
    if rec.get("status") != "ok":
        return None, "its last run was not usable (%s)" % _one(rec.get("reason") or "no reason")
    if rec.get("png") != src or rec.get("json") != "work/captures/%s.json" % name:
        return None, "its record names other files"
    png = os.path.join(vdir, *src.split("/"))
    js = os.path.join(vdir, "work", "captures", name + ".json")
    for p in (png, js):
        if os.path.islink(p) or not os.path.isfile(p):
            return None, "%s is missing or not a plain file" % os.path.relpath(p, vdir).replace(os.sep, "/")
    if _sha(png) != rec.get("png_sha"):
        return None, "%s is not the picture capture.py recorded" % src
    if _sha(js) != rec.get("json_sha"):
        return None, "work/captures/%s.json is not the one capture.py recorded" % name
    try:
        with open(js, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None, "work/captures/%s.json cannot be read" % name
    if not isinstance(data, dict):
        return None, "work/captures/%s.json is not an object" % name
    return data, None


def usable(vdir):
    """The script_src of every shot whose record says ok and whose files are the recorded ones (no settings read:
    the script check's picture rule; the board check judges floors and credits)."""
    return set(script_src(n) for n, rec in records(vdir).items() if _verified(vdir, n, rec)[1] is None)


BIDI = re.compile(r"[‎‏‪-‮⁦-⁩]")  # = source/page.py's: dropped from a question line


def _one(text, limit=300):
    return re.sub(r"[\x00-\x1f\x7f-\x9f  ]", " ", BIDI.sub("", str(text)))[:limit]


def _host(url):
    from urllib.parse import urlsplit
    try:
        return (urlsplit(url).hostname or "").lower().rstrip(".") if isinstance(url, str) and \
            url.lower().startswith(("https://", "http://")) else ""
    except ValueError:
        return ""


def _internal_host(host, items, pub):
    return bool(host) and rules.host_hit(host, items[1]) and host not in pub


def judge(data, cfg, items, internal_urls):
    """(floor, floor_reason, internal reason or None) of a shot's JSON (see the module's text)."""
    pub = rules.public_domains(cfg)
    final = data.get("url") if isinstance(data.get("url"), str) else ""
    host = _host(final)
    level, why = ("public", None) if host in pub else ("third-party", "a page of another host (%s)" % (host or "-"))
    internal = None
    if not host:
        internal = "the page's address cannot be read"
    elif _internal_host(host, items, pub):
        internal = "the page is on an internal host"
    elif any(rules.same_or_under(final, u) for u in internal_urls):
        internal = "the page is an internal source"
    else:
        try:
            rules.check_terms(final, items, "the page's address")
        except rules.CaptureError:
            internal = "the page's address names an in-house term"

    def worse(lv, reason):
        return LEVELS.index(lv) > LEVELS.index(level), (lv, reason)

    texts = [data.get("title")] + [t.get("text") for t in data.get("text") or [] if isinstance(t, dict)]
    for im in data.get("images") or []:
        if not isinstance(im, dict) or im.get("inCapture") is False:
            continue
        src = im.get("src") if isinstance(im.get("src"), str) else ""
        h = _host(src)
        texts.append(im.get("alt"))
        if _internal_host(h, items, pub) and internal is None:
            internal = "a picture in it comes from an internal host"
        if not h:
            cand = ("unknown", "a picture in it has no host address")
        elif h in pub:
            cand = ("public", None)
        else:
            cand = ("third-party", "a picture in it from another host (%s)" % h)
        better, pair = worse(*cand)
        if better:
            level, why = pair
    for op in data.get("opaque") or []:
        if not isinstance(op, dict) or op.get("inCapture") is False:
            continue
        kind = op.get("kind") if isinstance(op.get("kind"), str) and re.match(r"^[a-z]{1,12}$", op["kind"]) else "frame"
        better, pair = worse("unknown", "a %s in it Studio cannot read" % kind)
        if better:
            level, why = pair
    if internal is None and items[2]:
        whole = "\n".join(t for t in texts if isinstance(t, str))
        # also without invisible format characters (Unicode Cf: a soft hyphen or zero-width space inside a term)
        bare = "".join(c for c in whole if unicodedata.category(c) != "Cf")
        if rules.term_hit(whole, items[2]) or rules.term_hit(bare, items[2]):
            internal = "the page names an in-house term"
    return level, why, internal


def pictures(repo, vdir, state, cfg, env):
    """{script_src: entry} of every shot recorded: `status` ok or unusable (`reason`), `sha256` (the recorded
    picture's), `floor`, `floor_reason`, `floor_text` (the credit's floor), `scope` (= floor), `internal` (bool) and
    `internal_reason`, `url` and `captured_at` (the credit's fields), `idle`, `blocked`, `warnings`, `capture` (the
    name)."""
    from .. import credits
    recs = records(vdir)
    if not recs:
        return {}
    public = state.get("scope") != "internal"
    items = rules.overlay_items(repo, cfg, env)
    internal_urls = rules.source_urls(repo, cfg, env) if items[0] == "ok" else []
    out = {}
    for name in sorted(recs):
        rec = recs[name]
        src = script_src(name)
        e = {"script_src": src, "capture": name, "status": "unusable", "reason": None,
             "sha256": rec.get("png_sha") if isinstance(rec.get("png_sha"), str) else None,
             "url": rec.get("url") if isinstance(rec.get("url"), str) else None,
             "captured_at": rec.get("at") if isinstance(rec.get("at"), str) else None,
             "idle": rec.get("idle"), "blocked": [h for h in rec.get("blocked") or [] if isinstance(h, str)],
             "warnings": [w for w in rec.get("warnings") or [] if isinstance(w, str)],
             "floor": "unknown", "floor_reason": None, "internal": False, "internal_reason": None}
        data, why = _verified(vdir, name, rec)
        if why is None and (not e["url"] or not e["captured_at"]):
            why = "its record has no address or time"
        if why is None and public and items[0] == "missing":
            why = "the internal overlay is missing or changed — the person recreates it with /std config"
        if why is None:
            e["floor"], e["floor_reason"], e["internal_reason"] = judge(data, cfg, items, internal_urls)
            e["internal"] = e["internal_reason"] is not None
            e["status"] = "ok"
        e["reason"] = why
        e["scope"] = e["floor"]
        e["floor_text"] = credits.floor_of(e)
        out[src] = e
    return out


def used(files, pics):
    """The captures among the files s2v inspect lists for a script, sorted."""
    paths = set(f.get("path") for f in files or [] if isinstance(f, dict))
    return sorted(p for p in pics if p in paths)


def line(e):
    """The ③ question's line of one used capture (one line, no control characters)."""
    out = "화면 캡처 %s: %s · png %s · %s" % (e["capture"], _one(e.get("url") or "-"),
                                          (e.get("sha256") or "-")[:12], _one(e.get("floor_text") or "-"))
    if e.get("idle") is False:
        out += " · 경고: 페이지가 다 그려지기 전에 찍혔을 수 있음"
    if e.get("blocked"):
        out += " · 막힌 요청의 호스트 %d개" % len(e["blocked"])
    if e.get("status") != "ok":
        out += " · 쓸 수 없음: %s" % _one(e.get("reason") or "-", 120)
    elif e.get("internal"):
        out += " · 내부: %s" % _one(e.get("internal_reason"), 120)
    return out


def bound(pics, files):
    """{script_src: {png_sha, floor}} of the captures a script uses (what gate ③ binds: the picture's bytes and the
    floor its credit was judged with — a settings change that moves the floor sends the work back to ③)."""
    return {p: {"png_sha": pics[p].get("sha256"), "floor": pics[p].get("floor_text")} for p in used(files, pics)}


def credit_fields(e):
    """The credit's fields that come from the capture's record (never from the draft)."""
    return {"source": e.get("url"), "captured_at": e.get("captured_at")}


def for_repo(repo, vdir, state, env=None):
    """pictures() with the repository's config.json and this process's environment (or `env`)."""
    try:
        with open(os.path.join(repo, ".claude", "studio", "config.json"), encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        cfg = {}
    return pictures(repo, vdir, state, cfg if isinstance(cfg, dict) else {},
                    dict(os.environ) if env is None else env)
