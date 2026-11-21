"""What capture.py lets reach a page (m2-plan §5.1, decided Q4: capture runs without a prompt, so these rules close the
channel a URL or a selector could carry out). Pure except `overlay_items`, which reads the internal overlay.

- host: one of `public_domains`, or — for a board picture of a public video only — one of `capture.hosts` (third-party
  pages); never a host of the internal overlay; https only, no user, no port, a host name (an IP literal is not one).
- a board picture's URL has no query and no fragment, and a path of at most PATH_MAX characters.
- every URL and every selector is checked with the guard's INV5 data (guard/web.py `internal_items`: the overlay's
  hosts, terms and video/actor ids of MIN_TERM characters or more, case-folded, NFC); a required overlay that is missing
  or changed refuses every capture (exit 4, as check_scope).
- a selector is at most SELECTOR_MAX characters from SELECTOR_CHARS (no quotes: attribute values are bare words).
- `capture` in config.json is {"hosts": [...], "allow_hosts": [...]} of host names (setup/common.HOST); the
  `--allow-host` values s2v gets are `capture.allow_hosts` only.

Exit codes of the refusals: 2 a malformed value or setting · 3 refused by the host lists or the overlay · 4 the overlay
is missing."""

import hashlib
import json
import os
import posixpath
import re
import unicodedata
from urllib.parse import unquote, urlsplit

from .. import paths

USAGE, REFUSED, WAIT = 2, 3, 4
MIN_TERM = 4  # = guard/web.MIN_TERM
URL_MAX = 500
PATH_MAX = 200
SELECTOR_MAX = 200
SELECTOR_CHARS = re.compile(r"^[A-Za-z0-9 _#.,:>+~*()\[\]=-]+$")
# = setup/common.HOST (setup/ is plugin-only; test_m2d checks they are equal)
HOST = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+(?:[a-z]{2,63}|xn--[a-z0-9-]{1,59})$")
SIZE_MIN, SIZE_MAX = 320, 4096
DECODE_ROUNDS = 3


class CaptureError(Exception):
    def __init__(self, code, msg):
        Exception.__init__(self, msg)
        self.code = code


# ---------- config ----------

def capture_config(cfg):
    """(hosts, allow_hosts) of config.json's `capture` (absent: none), or CaptureError(2) when it is not that shape."""
    c = cfg.get("capture") if isinstance(cfg, dict) else None
    if c is None:
        return [], []
    problem = config_problem(c)
    if problem:
        raise CaptureError(USAGE, "config.json %s — fix it with /std config" % problem)
    return list(c.get("hosts") or []), list(c.get("allow_hosts") or [])


def config_problem(c):
    """None when `c` is a valid `capture` value, else what is wrong (setup.py config set checks a new value with it)."""
    if not isinstance(c, dict):
        return "capture must be an object {\"hosts\": [...], \"allow_hosts\": [...]}"
    extra = sorted(k for k in c if k not in ("hosts", "allow_hosts"))
    if extra:
        return "capture has unknown keys: %s (it takes hosts and allow_hosts)" % ", ".join(extra)
    for k in ("hosts", "allow_hosts"):
        v = c.get(k, [])
        if not isinstance(v, list) or not all(isinstance(h, str) and HOST.match(h) for h in v):
            return ("capture.%s must be a list of host names in lower-case ASCII (like cdn.example.com: no scheme, "
                    "port, path or wildcard)" % k)
    return None


def public_domains(cfg):
    return [d.lower() for d in (cfg.get("public_domains") or []) if isinstance(d, str)]


# ---------- the internal overlay (the guard's INV5 data, read without the guard) ----------

def overlay_items(top, cfg, env):
    """("none" | "ok" | "missing", hosts, terms): guard/web.py `overlay` + `internal_items` — the repository copy has
    no guard, so the same keys are read here (test_m2d compares the two)."""
    if not isinstance(cfg, dict) or cfg.get("internal_overlay") != "required":
        return "none", set(), []
    try:
        with open(os.path.join(top, ".claude", "studio", "local", "config.internal.json"), "rb") as f:
            raw = f.read()
        with open(os.path.join(paths.backup_root(env), paths.repo_key(top), "overlay.sha"), encoding="utf-8") as f:
            want = f.read().strip()
    except (OSError, RuntimeError, ValueError):
        return "missing", set(), []
    if hashlib.sha256(raw).hexdigest() != want:
        return "missing", set(), []
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return "missing", set(), []
    return items_of(data)


def items_of(data):
    """("ok", hosts, terms) of an overlay object read and matched already (check_scope has it)."""
    inner = data.get("internal") if isinstance(data, dict) else None
    if not isinstance(inner, dict):
        return "ok", set(), []
    hosts = set()
    for h in inner.get("hosts") or []:
        if isinstance(h, str) and h.strip():
            hosts.add(h.strip().lower().rstrip("."))
    for s in inner.get("sources") or []:
        url = s.get("url") if isinstance(s, dict) else None
        if isinstance(url, str):
            try:
                h = urlsplit(url).hostname
            except ValueError:
                h = None
            if h:
                hosts.add(h.lower())
    ids = [x for x in (inner.get("videos") or []) + (inner.get("actors") or []) if isinstance(x, str) and x]
    terms = [t for t in (inner.get("terms") or []) if isinstance(t, str) and len(t.strip()) >= MIN_TERM]
    terms += [t for t in ids if len(t) >= MIN_TERM]
    return "ok", hosts, sorted(set(t.strip() for t in terms))


def source_urls(top, cfg, env):
    """The overlay's internal source addresses (`internal.sources[].url`; empty without an overlay or a matching one)."""
    if overlay_items(top, cfg, env)[0] != "ok":
        return []
    try:
        with open(os.path.join(top, ".claude", "studio", "local", "config.internal.json"), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    return urls_of(data)


def urls_of(data):
    inner = data.get("internal") if isinstance(data, dict) else None
    return [s["url"] for s in (inner or {}).get("sources") or [] if isinstance(s, dict) and isinstance(s.get("url"), str)]


INDEX_NAMES = ("index.html", "index.htm")


def page_key(url):
    """(host, path) of an address as Studio compares pages with the overlay's internal sources: no query, fragment or
    `;params`, percent-decoded (as `decoded`), dot segments resolved, repeated `/` collapsed, a trailing index.html /
    index.htm and `/` dropped, case-folded. None when it is not an address."""
    try:
        x = urlsplit(url.strip())
    except (ValueError, AttributeError):
        return None
    path = decoded(x.path)[-1] if x.path else ""
    path = "/".join(seg.split(";", 1)[0] for seg in path.split("/"))
    path = posixpath.normpath("/" + re.sub(r"/+", "/", path)) if path else "/"
    low = _fold(path)
    for name in INDEX_NAMES:
        if low.endswith("/" + name):
            low = low[:-len(name)]
    return (x.hostname or "").lower().rstrip("."), low.rstrip("/")


def same_or_under(url, source):
    """Whether `url` is the overlay source page `source` or a page under it (its path a prefix, by page_key)."""
    a, b = page_key(url), page_key(source)
    if a is None or b is None or not b[0] or a[0] != b[0]:
        return False
    return a[1] == b[1] or a[1].startswith(b[1] + "/")


def final_problem(final, cfg, items, internal_urls, what="the page's final address"):
    """None, or why a page's final address (after redirects on the same host) may not be the source: the host and term
    rules of page_host, and not one of the overlay's internal source pages."""
    try:
        page_host(final, cfg, items, what)
    except CaptureError as e:
        return str(e)
    hit = next((u for u in internal_urls if same_or_under(final, u)), None)
    if hit:
        return "%s is an internal source of the overlay" % what
    return None


def shot_final_problem(final, cfg, items, internal_urls, what="the page's final address"):
    """None, or why a board picture's final address (run.judge already found it on the asked host) may not be shown:
    an internal host or an in-house term (as the asked address), or one of the overlay's internal source pages."""
    try:
        _u, host = _split(final, what)
        _check_host_and_terms(final, host, cfg, items, what)
    except CaptureError as e:
        return str(e)
    if any(same_or_under(final, u) for u in internal_urls):
        return "%s is an internal source of the overlay" % what
    return None


def host_hit(host, hosts):
    host = (host or "").lower().rstrip(".")
    return any(host == h or host.endswith("." + h) for h in hosts)


def _fold(text):
    return unicodedata.normalize("NFC", text).casefold()


def term_hit(text, terms):
    """The first overlay term the text names (guard/web.py `_term_hit`, on NFC text): ASCII terms as whole words."""
    low = _fold(text)
    for t in terms:
        tl = _fold(t)
        if re.match(r"^[\x00-\x7f]+$", tl):
            if re.search(r"(?<![0-9a-z])%s(?![0-9a-z])" % re.escape(tl), low):
                return t
        elif tl in low:
            return t
    return None


def overlay_problem(state, what):
    if state == "missing":
        return CaptureError(WAIT, "the internal overlay is missing or changed (.claude/studio/local/"
                                  "config.internal.json) — Studio does not capture %s until the person recreates it "
                                  "with /std config" % what)
    return None


def decoded(text):
    """`text` and its percent-decodings until stable (at most DECODE_ROUNDS: `%2562` → `%62` → `b`), each also without
    invisible format characters (Unicode Cf: a zero-width space inside a term)."""
    out, cur = [], text
    for _i in range(DECODE_ROUNDS + 1):
        for t in (cur, "".join(c for c in cur if unicodedata.category(c) != "Cf")):
            if t not in out:
                out.append(t)
        nxt = unquote(cur)
        if nxt == cur:
            break
        cur = nxt
    return out


def check_terms(text, items, what):
    """CaptureError(3) when `text` (a URL, also percent-decoded, or a selector) names an internal host or term."""
    _st, hosts, terms = items
    texts = decoded(text)
    if unquote(texts[-1]) != texts[-1]:  # still encoded after the last round (`%25` left)
        raise CaptureError(USAGE, "%s is percent-encoded more than %d times" % (what, DECODE_ROUNDS))
    for t in texts:
        hit = term_hit(t, terms)
        if hit:
            raise CaptureError(REFUSED, "%s names an in-house term (\"%s…\") — internal names must not reach an "
                                        "external page (INV5)" % (what, hit[:3]))


# ---------- URLs and selectors ----------

def _split(value, what):
    v = value or ""
    if not v or len(v) > URL_MAX or any(ord(c) < 33 or ord(c) == 127 or c in "<>\"'`\\" for c in v):
        raise CaptureError(USAGE, "%s must be one https URL without spaces, quotes or < > (at most %d characters)"
                           % (what, URL_MAX))
    try:
        u = urlsplit(v)
        port = u.port
    except ValueError:
        raise CaptureError(USAGE, "%s is not a URL: %s" % (what, v))
    host = u.hostname or ""
    if u.scheme != "https":
        raise CaptureError(USAGE, "%s must be an https URL" % what)
    if u.netloc.lower() != host or port is not None:
        raise CaptureError(USAGE, "%s may not carry a user, a password or a port" % what)
    if not HOST.match(host):
        raise CaptureError(USAGE, "%s must name a host in lower-case ASCII, not an IP address (%s)" % (what, host))
    return u, host


def page_host(url, cfg, items, what="the URL"):
    """The host of a source page's URL (`begin --url`, capture.py source and recheck), after the overlay check —
    flow.source_url keeps the rest of its rules (public_domains, no fragment, no credential-like query key)."""
    u, host = _split(url, what)
    if host not in public_domains(cfg):
        raise CaptureError(REFUSED, "%s must be on one of public_domains (%s)"
                           % (what, ", ".join(public_domains(cfg)) or "none set: /std config"))
    _check_host_and_terms(url, host, cfg, items, what)
    return host


def shot_url(url, cfg, items, public_video):
    """(url, host) of a board picture's page: public_domains, or capture.hosts for a public video; no query, no
    fragment, a short path; no internal host or term."""
    what = "--url"
    u, host = _split(url, what)
    if u.query or "?" in url:
        raise CaptureError(USAGE, "%s takes no ?query (capture the page's plain address)" % what)
    if u.fragment or "#" in url:
        raise CaptureError(USAGE, "%s takes no #fragment (use --selector for a part of the page)" % what)
    if any(c in t for t in decoded(u.path)[1:] for c in "?#"):
        raise CaptureError(USAGE, "%s has an encoded ? or # in its path (%%3F, %%23)" % what)
    if len(u.path) > PATH_MAX:
        raise CaptureError(USAGE, "%s has a path longer than %d characters" % (what, PATH_MAX))
    hosts, _allow = capture_config(cfg)
    if host in public_domains(cfg):
        pass
    elif host in hosts:
        if not public_video:
            raise CaptureError(REFUSED, "%s: an internal video captures only pages of public_domains (%s is one of "
                                        "capture.hosts)" % (what, host))
    else:
        raise CaptureError(REFUSED, "%s: %s is in neither public_domains nor capture.hosts — ask the person whether to "
                                    "add it to capture.hosts with /std config" % (what, host))
    _check_host_and_terms(url, host, cfg, items, what)
    return url, host


def _check_host_and_terms(url, host, cfg, items, what):
    st, hosts, _terms = items
    problem = overlay_problem(st, "a page")
    if problem:
        raise problem
    # an overlay host counts unless it is exactly a public domain (an internal source's URL on a public host names that
    # host); a subdomain of a public domain the overlay names (intra.example.com) is internal
    if host_hit(host, hosts) and host not in public_domains(cfg):
        raise CaptureError(REFUSED, "%s: %s is an internal host of the overlay" % (what, host))
    check_terms(url, items, what)


def selector(value, items):
    if value is None:
        return None
    if not value or len(value) > SELECTOR_MAX or not SELECTOR_CHARS.match(value) or value.startswith("-"):
        raise CaptureError(USAGE, "--selector is at most %d characters of letters, digits, space and _ # . , : > + ~ "
                                  "* ( ) [ ] = - (no quotes: an attribute value is a bare word; not starting with -)"
                                  % SELECTOR_MAX)
    check_terms(value, items, "--selector")
    return value


def size(name, value):
    if value is None:
        return None
    if not re.match(r"^[0-9]{3,4}$", value) or not SIZE_MIN <= int(value) <= SIZE_MAX:
        raise CaptureError(USAGE, "%s is a whole number from %d to %d" % (name, SIZE_MIN, SIZE_MAX))
    return int(value)


def allow_hosts(cfg, items):
    """`--allow-host` values: capture.allow_hosts without the overlay's internal hosts."""
    _hosts, allow = capture_config(cfg)
    return [h for h in allow if not host_hit(h, items[1])]
