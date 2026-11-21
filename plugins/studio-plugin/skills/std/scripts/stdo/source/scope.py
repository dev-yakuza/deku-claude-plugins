"""`check_scope.py <video>` (m1-plan §6.2): may this public video use its source, and at which scope is each image.

- The internal overlay must be present and match its recorded sha (else 4: the person recreates it).
- The source must be public: inside `visibility.public` (the default `unknown` is not public) and not one of the
  overlay's internal sources (`internal.sources[]` — an entry's `path` glob, or its `url` equal to the path). Else 1.
- Each image's scope is the stricter of its floor (resolve_assets) and the source analyst's class (`work/source.md`, the
  JSON block between `<!-- studio:images -->` and `<!-- /studio:images -->`: `{"img-01": {"class": …, "reason": …}}`).
  Classes: diagram · photo · screenshot (the owner's: public), third-party, unknown, internal (made inside the
  organization, not for the public: level unknown and the `internal` flag). An image the analyst did not classify, or
  classified with another word, is `unknown`.
- Being internal is a flag beside the level, never a level (`stricter` must not turn it into third-party): set when the
  analyst classes the image internal or its file is an overlay internal source. A public video cannot use such an image
  whatever its level — its entry becomes unusable (reason `internal`); the source itself does not fail (the script,
  board and commit checks refuse the image where it is used). An internal video ignores the flag.
The result goes into assets.json (`scope` per image, `scope_check` for the source copy it judged, with the visibility,
web_roots and internal overlay sha it judged with); record-source records the images and assets.json's sha only when
that check passed for the current copy and none of those changed since."""

import hashlib
import json
import os
import re

from .. import SCRIPTS_VERSION
from . import assets

CLASSES = {"diagram": "public", "photo": "public", "screenshot": "public", "third-party": "third-party",
           "unknown": "unknown", "internal": "unknown"}
BLOCK = re.compile(r"<!-- studio:images -->\s*```json\s*\n(.*?)\n```\s*<!-- /studio:images -->", re.S)


class ScopeError(Exception):
    def __init__(self, code, msg):
        Exception.__init__(self, msg)
        self.code = code


def analyst_classes(vdir):
    """({image id: {"class", "reason"}}, note or None) from work/source.md."""
    p = os.path.join(vdir, "work", "source.md")
    try:
        with open(p, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return {}, "work/source.md is missing: every image is unknown until the source analyst classifies it"
    m = BLOCK.search(text)
    if not m:
        return {}, "work/source.md has no studio:images block: every image is unknown"
    try:
        data = json.loads(m.group(1))
    except ValueError as e:
        return {}, "the studio:images block is not JSON (%s): every image is unknown" % e
    if not isinstance(data, dict):
        return {}, "the studio:images block is not an object: every image is unknown"
    return {k: v for k, v in data.items() if isinstance(v, dict)}, None


def internal_source(source_rel, overlay):
    inner = (overlay or {}).get("internal") if isinstance(overlay, dict) else None
    for s in (inner or {}).get("sources") or []:
        if not isinstance(s, dict):
            continue
        p = s.get("path")
        if isinstance(p, str) and p and assets.glob_match(source_rel, p):
            return p
        if s.get("url") == source_rel:
            return s.get("url")
    return None


def fingerprint(top, cfg, env):
    """What a scope check depends on besides the source copy: visibility, web_roots and the internal overlay's sha
    (None when there is none or it does not match its recorded sha)."""
    from ..commit.harness import overlay_terms
    st, _terms = overlay_terms(top, cfg, env)
    sha = None
    if st == "ok":
        try:
            with open(os.path.join(top, ".claude", "studio", "local", "config.internal.json"), "rb") as f:
                sha = hashlib.sha256(f.read()).hexdigest()
        except OSError:
            sha = None
    return {"visibility": cfg.get("visibility"), "web_roots": cfg.get("web_roots") or {}, "overlay_sha": sha}


def check(top, vdir, state, cfg, copy_sha, overlay_state, overlay_data, fp):
    """The updated assets.json object (raises ScopeError)."""
    if overlay_state == "missing":
        raise ScopeError(4, "the internal overlay is missing or does not match its recorded sha — ask the person to "
                            "recreate it (/std config) before choosing a public video's source")
    data = assets.read(vdir)
    if data is None:
        raise ScopeError(1, "work/assets.json is missing or unreadable — run resolve_assets.py first")
    if data.get("source_copy_sha") != copy_sha:
        raise ScopeError(1, "work/assets.json was made from another copy of the source — run resolve_assets.py again")
    if state["source"].get("kind") == "url":
        return _check_url(vdir, state, cfg, copy_sha, overlay_data, fp, data)
    source_rel = state["source"]["path"]
    if state.get("scope") == "public":
        if not assets.is_public(source_rel, cfg):
            raise ScopeError(1, "the source %s is not in visibility.public — a public video needs public writing "
                                "(ask the person: change visibility with /std config, or choose another source)"
                             % source_rel)
        hit = internal_source(source_rel, overlay_data)
        if hit:
            raise ScopeError(1, "the source %s is an internal source of the overlay (%s) — not for a public video"
                             % (source_rel, hit))
    return _judge_images(vdir, state, copy_sha, overlay_data, fp, data)


def _judge_images(vdir, state, copy_sha, overlay_data, fp, data, internal_host=None):
    classes, note = analyst_classes(vdir)
    for img in data["images"]:
        if img.get("reason") == "internal":  # this check's own mark from an earlier run: judged again below
            img["status"], img["reason"] = "ok", None
        c = classes.get(img["id"]) or {}
        cls = c.get("class")
        mapped = CLASSES.get(cls, "unknown")
        img["analyst_class"] = cls if cls in CLASSES else None
        img["analyst_reason"] = c.get("reason") if isinstance(c.get("reason"), str) else None
        img["scope"] = assets.stricter(img.get("floor") or "unknown", mapped)
        res = img.get("resolved")
        img["internal"] = cls == "internal" or bool(isinstance(res, str) and internal_source(res, overlay_data)) or \
            bool(internal_host and any(internal_host("https://%s/" % r["host"] if r.get("host") else r.get("src"))
                                       for r in img.get("refs") or [] if isinstance(r, dict)))
        if img["internal"] and state.get("scope") != "internal" and img.get("status") == "ok":
            img["status"], img["reason"] = "unusable", "internal"
    data["scope_check"] = {"result": "pass", "source_copy_sha": copy_sha, "scripts_version": SCRIPTS_VERSION,
                           "video_scope": state.get("scope"), "note": note}
    data["scope_check"].update(fp)
    return data


def _check_url(vdir, state, cfg, copy_sha, overlay_data, fp, data):
    """A URL source (m2-plan §6.2 6): public when its host is one of public_domains, not a host of the overlay (an
    exact public domain excepted, as capture.py) and not an overlay source; a page picture from an overlay host is
    internal."""
    from urllib.parse import urlsplit
    from ..capture import rules
    url = state["source"].get("url")
    st, hosts, terms = rules.items_of(overlay_data or {})
    pub = rules.public_domains(cfg)

    def internal_host(u):
        try:
            h = (urlsplit(u).hostname or "").lower() if isinstance(u, str) else ""
        except ValueError:
            h = ""
        return bool(h) and rules.host_hit(h, hosts) and h not in pub

    if state.get("scope") == "public":
        # the asked address and the page's final one (a redirect on the same host): both public, neither internal
        from ..capture import files
        cap = state["source"].get("capture") if isinstance(state["source"].get("capture"), dict) else {}
        rec, _why = files.read(os.path.join(vdir, "work", "source"))
        finals = [u for u in (cap.get("url"), (rec or {}).get("final")) if isinstance(u, str)]
        internal_urls = rules.urls_of(overlay_data or {})
        for u, what in [(url, "the source page %s" % url)] + [(u, "the captured page %s" % u) for u in finals]:
            why = rules.final_problem(u, cfg, (st, hosts, terms), internal_urls, what)
            if why:
                raise ScopeError(1, why + " — not for a public video")
    return _judge_images(vdir, state, copy_sha, overlay_data, fp, data, internal_host=internal_host)
