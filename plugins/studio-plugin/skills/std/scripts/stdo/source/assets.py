"""`resolve_assets.py <video>` (m1-plan §6.1): every image reference of the frozen source copy, resolved and judged, in
`work/assets.json` (P-STATE: only Studio's scripts write it; record-source keeps its sha).

Resolution: a URL (`http(s)://`, `//host`) or `data:` is not usable in M1 (`url` · `data`); a site path (`/…`) goes
through the longest matching `web_roots` prefix (`no-web-root` without one); anything else is relative to the source's
own folder. Query and fragment are dropped, percent-escapes decoded, the name NFC-normalized. The real path must stay in
the repository and, for a site path, in its web root (`outside-root`); a missing file is `not-found`, one that exists
only with other letter case `case-mismatch`. Only PNG and JPEG bytes are usable (`format`), and the bytes must match the
extension (`ext-mismatch`).

The floor (M6, D-M1-15): alt, title, caption or context (the surrounding `<figure>` and a short window of lines) naming a
copyright or a source (CREDIT_MARKS plus `source.credit_marks`, letter case ignored; `via` only as a word) → at least
`third-party`; a file outside `visibility.public` → at least `unknown`; else `public`. Lines that still look like an
image but were not parsed are counted in `unparsed` (M1g's check_assets refuses any script image that is not a usable
entry here). The source analyst may only make an image stricter (check_scope takes the stricter of the two)."""

import hashlib
import json
import os
import re
import unicodedata
from urllib.parse import unquote

from .. import credits, writes
from . import imgformat, refs

SCHEMA = 1
IMAGE_KEYS = ("image", "heroImage", "cover", "ogImage", "images")
CREDIT_MARKS = ("©", "Ⓒ", "ⓒ", "(c)", "copyright", "all rights reserved", "出典", "출처", "提供", "引用", "courtesy",
                "image:", "이미지:", "via")
WORD_MARKS = ("via",)  # only as a whole word ("via" in "trivia" is no credit)
LEVELS = ("public", "unknown", "third-party")


class AssetError(Exception):
    def __init__(self, code, msg):
        Exception.__init__(self, msg)
        self.code = code


def stricter(a, b):
    return a if LEVELS.index(a) >= LEVELS.index(b) else b


def glob_match(path, pattern):
    """`**` = any number of folders, `*` / `?` within one name (fnmatch per part, case-sensitive)."""
    import fnmatch
    p, g = path.split("/"), pattern.strip("/").split("/")
    memo = {}

    def rec(i, j):
        if (i, j) in memo:
            return memo[(i, j)]
        if j == len(g):
            r = i == len(p)
        elif g[j] == "**":
            r = rec(i, j + 1) or (i < len(p) and rec(i + 1, j))
        else:
            r = i < len(p) and fnmatch.fnmatchcase(p[i], g[j]) and rec(i + 1, j + 1)
        memo[(i, j)] = r
        return r
    return rec(0, 0)


def is_public(path, cfg):
    vis = cfg.get("visibility") if isinstance(cfg.get("visibility"), dict) else {}
    return any(isinstance(g, str) and glob_match(path, g) for g in vis.get("public") or [])


def settings(cfg):
    src = cfg.get("source") if isinstance(cfg.get("source"), dict) else {}
    keys = src.get("image_keys", list(IMAGE_KEYS))
    marks = list(CREDIT_MARKS) + [m for m in src.get("credit_marks") or [] if isinstance(m, str) and m]
    wr = cfg.get("web_roots") or {}
    if not isinstance(keys, list) or not all(isinstance(k, str) for k in keys):
        raise AssetError(2, "source.image_keys must be a list of frontmatter keys")
    if not isinstance(wr, dict) or not all(isinstance(k, str) and k.startswith("/") and isinstance(v, str) and v
                                           and not os.path.isabs(v) for k, v in wr.items()):
        raise AssetError(2, "web_roots must map site paths (starting with /) to repository folders")
    return keys, marks, wr


def _clean(src):
    for sep in ("#", "?"):
        src = src.split(sep, 1)[0]
    return unicodedata.normalize("NFC", unquote(src))


def _within(real, base):
    return real == base or real.startswith(base.rstrip(os.sep) + os.sep)


def _case_exact(top, rel):
    """Whether every part of `rel` exists with exactly this letter case (a case-insensitive disk finds others)."""
    cur = top
    for part in rel.split("/"):
        try:
            names = os.listdir(cur)
        except OSError:
            return False
        if unicodedata.normalize("NFC", part) not in [unicodedata.normalize("NFC", n) for n in names]:
            return False
        cur = os.path.join(cur, part)
    return True


def has_mark(text, marks):
    """The first credit mark in `text` (letter case ignored; a WORD_MARKS mark only as a whole word), or None."""
    low = unicodedata.normalize("NFC", text or "").casefold()
    for m in marks:
        ml = unicodedata.normalize("NFC", m).casefold()
        if not ml:
            continue
        if ml in WORD_MARKS:
            if re.search(r"(?<!\w)%s(?!\w)" % re.escape(ml), low):
                return m
        elif ml in low:
            return m
    return None


def resolve(top, source_rel, src, web_roots):
    """(status, reason, repository-relative path or None)."""
    s = (src or "").strip()
    if not s:
        return "unusable", "no-reference", None
    low = s.lower()
    if low.startswith(("http://", "https://", "//")):
        return "unusable", "url", None
    if low.startswith("data:"):
        return "unusable", "data", None
    path = _clean(s)
    real_top = os.path.realpath(top)
    if path.startswith("/"):
        best = None
        for k in web_roots:
            kk = k if k.endswith("/") else k + "/"
            if path == k or path.startswith(kk) or k == "/":
                if best is None or len(k) > len(best):
                    best = k
        if best is None:
            return "unusable", "no-web-root", None
        folder = web_roots[best].strip("/")
        rest = path[len(best):].lstrip("/")
        rel = os.path.normpath(os.path.join(folder, rest)).replace(os.sep, "/")
        base = os.path.realpath(os.path.join(top, folder))
    else:
        rel = os.path.normpath(os.path.join(os.path.dirname(source_rel), path)).replace(os.sep, "/")
        base = real_top
    if rel.startswith("../") or rel == ".." or os.path.isabs(rel):
        return "unusable", "outside-root", None
    full = os.path.join(top, rel)
    if not os.path.lexists(full):
        return "unusable", "not-found", rel
    real = os.path.realpath(full)
    if not _within(real, real_top) or not _within(real, base):
        return "unusable", "outside-root", rel
    if not _case_exact(top, rel):
        return "unusable", "case-mismatch", rel
    if not os.path.isfile(real):
        return "unusable", "not-a-file", rel
    return "ok", None, os.path.relpath(real, real_top).replace(os.sep, "/")


def judge_file(top, rel):
    """(status, reason, info) for a resolved file: its bytes."""
    with open(os.path.join(top, rel), "rb") as f:
        data = f.read()
    fmt, w, h = imgformat.detect(data)
    info = {"sha256": hashlib.sha256(data).hexdigest(), "format": fmt, "size": len(data), "width": w, "height": h}
    if fmt not in imgformat.USABLE:
        return "unusable", "format", info
    ext = imgformat.extension_format(rel)
    if ext is not None and ext != fmt:
        return "unusable", "ext-mismatch", info
    return "ok", None, info


def floor(ref, rel, cfg, marks):
    hit = has_mark(ref.owner_text(), marks)
    if hit:
        return "third-party", "a copyright or source mark (%s) in its alt, title, caption or context" % hit
    if rel is None or not is_public(rel, cfg):
        return "unknown", "outside visibility.public" if rel else "no file to place"
    return "public", None


def build(top, vdir, video, source_rel, copy_path, cfg):
    """The assets.json object (deterministic: no times)."""
    keys, marks, web_roots = settings(cfg)
    try:
        with open(copy_path, "rb") as f:
            raw = f.read()
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise AssetError(1, "cannot read the source copy %s (%s) — run state.py record-source first"
                         % (os.path.relpath(copy_path, top), e))
    images = []
    found, unparsed, hidden = refs.extract_all(text, keys, credit=lambda t: has_mark(t, marks) is not None)
    for n, ref in enumerate(found, 1):
        entry = {"id": "img-%02d" % n, "ref": ref.src, "line": ref.line, "kind": ref.kind, "alt": ref.alt,
                 "title": ref.title, "caption": ref.caption, "context": ref.context, "resolved": None, "script_src": None, "sha256": None,
                 "format": None, "size": None, "width": None, "height": None}
        status, reason, rel, info = "unusable", "no-reference", None, None
        tried = []
        for cand in ref.candidates:  # a <picture>: the first PNG/JPEG candidate that resolves
            status, reason, rel = resolve(top, source_rel, cand, web_roots)
            info = None
            if status == "ok":
                status, reason, info = judge_file(top, rel)
            tried.append({"ref": cand, "status": status, "reason": reason})
            if status == "ok":
                entry["ref"] = cand
                break
        if ref.kind == "picture":
            entry["candidates"] = tried
        if info:
            entry.update(info)  # the last candidate's bytes (for a refused format too)
        entry["resolved"] = rel
        if status == "ok":
            entry["script_src"] = os.path.relpath(os.path.join(top, rel), vdir).replace(os.sep, "/")
        fl, why = floor(ref, rel if status == "ok" or reason in ("format", "ext-mismatch") else None, cfg, marks)
        entry.update(status=status, reason=reason, floor=fl, floor_reason=why)
        entry["floor_text"] = credits.floor_of(entry)  # the CREDITS `floor` exactly (0.0.28 Q10: never "public/null")
        images.append(entry)
    return {"schema": SCHEMA, "video": video, "source": source_rel,
            "source_copy_sha": hashlib.sha256(raw).hexdigest(), "images": images,
            "unparsed": {"count": len(unparsed), "lines": unparsed, "hidden_by_comment": hidden}}


# ---------- a URL source (m2-plan §6.2 4) ----------

PAGE_IMAGE_MAX = 20 * 1024 * 1024  # a page picture larger than this is not usable (`too-large`)
SRC_MAX, ALT_MAX = 300, 300  # what assets.json keeps of a reference's address (a data: URL) and of its alt text


def _short(text, limit):
    return text if len(text) <= limit else text[:limit] + "…"

def _url_floor(src, cfg):
    """(floor, reason) of one page picture by where it came from."""
    host = _host_of(src)
    if not host:
        return "unknown", "not an address of a host (%s)" % (src.split(":", 1)[0][:10] or "none")
    if host in [d.lower() for d in cfg.get("public_domains") or [] if isinstance(d, str)]:
        return "public", None
    return "third-party", "from another host (%s)" % host


def _host_of(src):
    from urllib.parse import urlsplit
    try:
        return (urlsplit(src).hostname or "").lower() or None if src.lower().startswith(("https://", "http://")) \
            else None
    except ValueError:
        return None


def _real_folder(vdir, name):
    p = os.path.join(vdir, name)
    if os.path.islink(p):
        raise AssetError(2, "%s is a symbolic link — Studio does not write through it" % p)
    if not os.path.isdir(p):
        os.mkdir(p)
    return p


def _page_file(adir, sha):
    """The file s2v kept for this sha256 in the copy's assets/ (`<sha>.<ext>`), or None."""
    hits = [x for x in sorted(os.listdir(adir)) if x.split(".", 1)[0] == sha] if os.path.isdir(adir) else []
    return os.path.join(adir, hits[0]) if len(hits) == 1 and not os.path.islink(os.path.join(adir, hits[0])) else None


def build_url(top, vdir, state, cfg):
    """The assets.json object of a URL source: one entry per picture of the copy's capture.json, by bytes (`img-<first
    12 hex of the sha256>`; pictures with the same bytes are one entry with every reference in `refs`). Usable: PNG or
    JPEG bytes kept by s2v, copied to `<video>/assets/src-<sha12>.<ext>` (P-STATE) — the path the script uses. Not
    usable: no bytes (`no-bytes`: s2v could not tell them), other formats (`format`), bytes that do not match
    (`bytes-mismatch`), more than PAGE_IMAGE_MAX bytes (`too-large`). A reference's address and alt text are kept up
    to SRC_MAX / ALT_MAX characters. Floor: from one of public_domains → public, another host → third-party, no host (data:, blob:)
    → unknown; the strictest over the references."""
    from ..capture import files
    sdir = os.path.join(vdir, "work", "source")
    rec, why = files.verify(sdir)
    if why:
        raise AssetError(1, "the source's copy is not as capture.py wrote it (%s) — run capture.py source and "
                            "state.py record-source first" % why)
    try:
        with open(os.path.join(sdir, "page.md"), "rb") as f:
            raw = f.read()
        with open(os.path.join(sdir, "capture.json"), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        raise AssetError(1, "cannot read the source's copy (%s) — run capture.py source first" % e)
    groups, order = {}, []
    for n, im in enumerate(data.get("images") or [] if isinstance(data, dict) else []):
        if not isinstance(im, dict) or not isinstance(im.get("src"), str):
            continue
        sha = im.get("sha256") if isinstance(im.get("sha256"), str) and re.match(r"^[0-9a-f]{64}$",
                                                                                 im.get("sha256") or "") else None
        key = sha or "src:" + hashlib.sha256(im["src"].encode("utf-8")).hexdigest()
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append({"src": _short(im["src"], SRC_MAX), "full": im["src"],
                            "alt": _short(im.get("alt"), ALT_MAX) if isinstance(im.get("alt"), str) else "",
                            "kind": im.get("kind"), "bbox": im.get("bbox"), "in_capture": im.get("inCapture") is not
                            False, "index": n})
    adir = os.path.join(sdir, "assets")
    images = []
    for key in order:
        refs = groups[key]
        sha = None if key.startswith("src:") else key
        entry = {"id": "img-%s" % (sha or key[4:])[:12], "ref": refs[0]["src"], "refs": refs, "line": None,
                 "kind": "page-image", "alt": next((r["alt"] for r in refs if r["alt"]), ""), "title": None,
                 "caption": None, "context": None, "resolved": None, "script_src": None, "sha256": sha,
                 "format": None, "size": None, "width": None, "height": None}
        status, reason = "unusable", "no-bytes"
        p = _page_file(adir, sha) if sha else None
        if p is not None and os.path.getsize(p) > PAGE_IMAGE_MAX:
            status, reason = "unusable", "too-large"
            entry["size"] = os.path.getsize(p)
            p = None
        if p is not None:
            with open(p, "rb") as f:
                body = f.read()
            fmt, w, h = imgformat.detect(body)
            entry.update(format=fmt, size=len(body), width=w, height=h)
            if hashlib.sha256(body).hexdigest() != sha:
                status, reason = "unusable", "bytes-mismatch"
            elif fmt not in imgformat.USABLE:
                status, reason = "unusable", "format"
            else:
                status, reason = "ok", None
                name = "src-%s.%s" % (sha[:12], "jpg" if fmt == "jpeg" else "png")
                dst = os.path.join(_real_folder(vdir, "assets"), name)
                if os.path.lexists(dst) and (os.path.islink(dst) or not os.path.isfile(dst)):
                    raise AssetError(2, "%s is not a plain file — Studio does not write over it" % dst)
                if file_sha(dst) != sha:
                    writes.check("a video's pictures")
                    tmp = "%s.tmp.%d" % (dst, os.getpid())
                    with open(tmp, "wb") as f:
                        f.write(body)
                    os.replace(tmp, dst)
                entry["script_src"] = "assets/" + name
                entry["resolved"] = os.path.relpath(dst, top).replace(os.sep, "/")
        fl, why_f = "public", None
        for r in refs:
            full = r.pop("full")  # the floor and the host by the whole address, never the shortened one
            r["host"] = _host_of(full)
            f2, w2 = _url_floor(full, cfg)
            if LEVELS.index(f2) > LEVELS.index(fl):
                fl, why_f = f2, w2
        entry.update(status=status, reason=reason, floor=fl, floor_reason=why_f)
        entry["floor_text"] = credits.floor_of(entry)
        images.append(entry)
    return {"schema": SCHEMA, "video": state["video"], "source": state["source"].get("url"),
            "source_copy_sha": hashlib.sha256(raw).hexdigest(), "images": images,
            "unparsed": {"count": 0, "lines": [], "hidden_by_comment": None}}


def file_sha(p):
    try:
        with open(p, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


def path(vdir):
    return os.path.join(vdir, "work", "assets.json")


def write(vdir, data):
    writes.check("assets.json")
    p = path(vdir)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = "%s.tmp.%d" % (p, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)
    return p


def read(vdir):
    try:
        with open(path(vdir), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("schema") == SCHEMA else None
