"""`setup.py init analyze` (m1-plan §5.2 step 2, read-only): drafts for the interview — web_roots from the static site's
settings, the folders that hold writing, the hook manager, LFS, and whether the studio folder name is free.

0.0.24 (pilot-1 P7) adds drafts with their evidence, so the interview offers values instead of asking the person to
type them: `public_domains` (CNAME files and the site settings), `brand_colors` (theme-color, brand/primary/accent
custom properties and Tailwind colours, then the most used colour of the site's own styles), `logos` (tracked logo
and icon images) and `ask_husky`. Only tracked files are read (git ls-files), never `.env*`, never through a symbolic
link, never vendor folders, minified files or files with a vendor banner (`/*!`, `@license`), within a budget; a
repository too big for it gives what was found with `partial: true`. Colours are #RRGGBB or #RGB in the styles
(rgb() and named colours are not read); only chromatic ones count (HSL saturation >= 0.30, 0.15 <= lightness <= 0.85)."""

import colorsys
import glob
import json
import os
import re
import stat

from .common import HOST

STATIC = (  # (settings files, how the public folder is named in them, default public folder)
    (("astro.config.mjs", "astro.config.js", "astro.config.ts", "astro.config.cjs"),
     r"publicDir\s*:\s*['\"]([^'\"]+)['\"]", "public"),
    (("next.config.js", "next.config.mjs", "next.config.ts"), None, "public"),
    (("hugo.toml", "hugo.yaml", "config.toml"), r"staticDir\s*=\s*['\"]([^'\"]+)['\"]", "static"),
    (("docusaurus.config.js", "docusaurus.config.ts"), None, "static"),
    (("svelte.config.js",), None, "static"),
    (("vite.config.js", "vite.config.ts"), r"publicDir\s*:\s*['\"]([^'\"]+)['\"]", "public"),
)
CONTENT_GLOBS = ("src/content/*", "content/*", "content", "posts", "_posts", "blog", "docs")


def _read(p):
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            return f.read(200000)
    except OSError:
        return None


def web_roots(top):
    """{"/": "<folder>/"} for the first static-site setup found, else {}; with what it was read from."""
    for files, rx, default in STATIC:
        for name in files:
            text = _read(os.path.join(top, name))
            if text is None:
                continue
            folder = default
            if rx:
                m = re.search(rx, text)
                if m:
                    folder = m.group(1)
            folder = folder.strip("./").rstrip("/") or default
            if os.path.isdir(os.path.join(top, folder)):
                return {"/": folder + "/"}, name
            return {}, "%s (its %s/ folder is missing)" % (name, folder)
    return {}, None


def content_folders(top):
    out = []
    for g in CONTENT_GLOBS:
        for d in sorted(glob.glob(os.path.join(glob.escape(top), g))):
            if not os.path.isdir(d) or os.path.islink(d):
                continue
            n = len(glob.glob(os.path.join(glob.escape(d), "**", "*.md"), recursive=True)) + \
                len(glob.glob(os.path.join(glob.escape(d), "**", "*.mdx"), recursive=True))
            if n:
                out.append({"folder": os.path.relpath(d, top) + "/", "markdown_files": n})
    return out


def studio_root_free(top, root):
    """None when `<root>/` is free (absent or empty), else why not."""
    d = os.path.join(top, root)
    if os.path.islink(d):
        return "%s is a symbolic link" % root
    if not os.path.exists(d):
        return None
    if not os.path.isdir(d):
        return "%s is a file" % root
    if os.listdir(d):
        return "%s/ exists and holds files that are not Studio's — choose another studio_root" % root
    return None


# ---- 0.0.24 (pilot-1 P7): the tracked-file walk ----

MAX_LISTED = 50000  # git ls-files entries looked at
MAX_SIZE = 512 * 1024  # larger files are never read
READ_CAP = 200 * 1024  # bytes read of one file
BUDGET_BYTES = 20 * 1024 * 1024  # over every candidate file read
BUDGET_FILES = 3000
SKIP_SEGMENTS = frozenset(("node_modules", "vendor", "vendors", "third_party", "bower_components", "dist", ".next",
                           ".nuxt", "coverage", ".git", ".claude", "themes", "_site"))
BANNER = re.compile(rb"/\*!|@license")


def _skip(rel, studio_root="studio"):
    """True for a path the drafts never read: vendor and build folders, Studio's folders, `.env*`, minified files."""
    parts = rel.split("/")
    if any(p in SKIP_SEGMENTS or p == studio_root for p in parts[:-1]):
        return True
    base = parts[-1]
    return base.startswith(".env") or ".min." in base


class Walk(object):
    """The tracked files of `top` and a budgeted, link-free reader."""

    def __init__(self, top, git, studio_root="studio"):
        self.top = top
        self.real_top = os.path.realpath(top)
        self.studio_root = studio_root
        self.partial = False
        self.read_bytes = 0
        self.read_files = 0
        self.files = []
        self.tracked = frozenset()
        if git is None:
            return
        try:
            raw = git.run("ls-files", "-z", timeout=60).stdout
        except Exception:  # noqa: BLE001 — a draft only: no files, no drafts
            return
        names = [n.decode("utf-8", "surrogateescape") for n in raw.split(b"\0") if n]
        if len(names) > MAX_LISTED:
            names, self.partial = names[:MAX_LISTED], True
        self.files = [n for n in names if not _skip(n, studio_root)]
        self.tracked = frozenset(names)

    def has(self, rel):
        return rel in self.tracked

    def stat(self, rel, max_size=MAX_SIZE):
        """os.lstat of a regular file inside the repository (not a link, FIFO or device; its real path under the top
        level; at most `max_size` bytes), else None. Checked before anything opens the file."""
        p = os.path.join(self.top, rel)
        try:
            st = os.lstat(p)
        except OSError:
            return None
        if not stat.S_ISREG(st.st_mode) or (max_size is not None and st.st_size > max_size):
            return None
        real = os.path.realpath(p)
        if not real.startswith(self.real_top.rstrip("/") + "/"):
            return None  # a folder on the way is a link out of the repository
        return st

    def read(self, rel, cap=READ_CAP, max_size=MAX_SIZE):
        """Up to `cap` bytes of a tracked file, or None (skipped, unsafe, or the budget is spent)."""
        if self.read_files >= BUDGET_FILES or self.read_bytes >= BUDGET_BYTES:
            self.partial = True
            return None
        if self.stat(rel, max_size) is None:
            return None
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        try:
            fd = os.open(os.path.join(self.top, rel), flags)
        except OSError:
            return None
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                return None
            data = os.read(fd, cap)
        except OSError:
            return None
        finally:
            os.close(fd)
        self.read_files += 1
        self.read_bytes += len(data)
        return data

    def text(self, rel):
        data = self.read(rel)
        return None if data is None else data.decode("utf-8", "replace")


# ---- public_domains ----

CNAMES = ("CNAME", "public/CNAME", "static/CNAME", "docs/CNAME", "source/CNAME")
DOMAIN_SETTINGS = (  # (files at the top level, the setting's pattern, its name)
    (("astro.config.mjs", "astro.config.js", "astro.config.ts", "astro.config.cjs", "astro.config.mts"),
     r"\bsite\s*:\s*['\"`]([^'\"`\s]+)['\"`]", "site"),
    (("hugo.toml", "config.toml"), r"(?mi)^\s*baseURL\s*=\s*['\"]([^'\"\s]+)['\"]", "baseURL"),
    (("hugo.yaml", "hugo.yml", "config.yaml", "config.yml"), r"(?mi)^\s*baseURL\s*:\s*['\"]?([^'\"\s#]+)", "baseURL"),
    (("_config.yml", "_config.yaml"), r"(?m)^url\s*:\s*['\"]?([^'\"\s#]+)", "url"),
    (("docusaurus.config.js", "docusaurus.config.ts", "docusaurus.config.mjs"),
     r"\burl\s*:\s*['\"`]([^'\"`\s]+)['\"`]", "url"),
    (("gatsby-config.js", "gatsby-config.ts", "gatsby-config.mjs"), r"\bsiteUrl\s*:\s*['\"`]([^'\"`\s]+)['\"`]",
     "siteUrl"),
    (("mkdocs.yml", "mkdocs.yaml"), r"(?m)^site_url\s*:\s*['\"]?([^'\"\s#]+)", "site_url"),
    (("next-sitemap.config.js", "next-sitemap.config.mjs", "next-sitemap.config.cjs"),
     r"\bsiteUrl\s*:\s*['\"`]([^'\"`\s]+)['\"`]", "siteUrl"),
)
EXAMPLE = ("example.com", "example.org", "example.net")


def host_of(value):
    """The host name of a URL or a bare host (scheme, user, port, path and a trailing dot removed, lowercase), or None
    for anything that is not a public host (localhost, an IP address, example.com/org/net)."""
    v = (value or "").strip().lower()
    v = re.sub(r"^[a-z][a-z0-9+.-]*://", "", v)
    v = re.split(r"[/?#]", v, 1)[0].rsplit("@", 1)[-1]
    v = re.sub(r":\d*$", "", v).rstrip(".")
    if not HOST.match(v):
        return None  # also localhost and IPv4 addresses (no letter TLD)
    if any(v == e or v.endswith("." + e) for e in EXAMPLE):
        return None
    return v


def public_domains(walk, roots):
    found = {}  # host -> [from]

    def add(host, src):
        if host:
            found.setdefault(host, [])
            if src not in found[host]:
                found[host].append(src)

    cnames = list(CNAMES)
    for folder in (roots or {}).values():
        c = folder.rstrip("/") + "/CNAME"
        if c not in cnames:
            cnames.append(c)
    for rel in cnames:
        if not walk.has(rel):
            continue
        text = walk.text(rel)
        line = next((l.strip() for l in (text or "").splitlines() if l.strip()), "")
        add(host_of(line), rel)
    for files, rx, name in DOMAIN_SETTINGS:
        for rel in files:
            if not walk.has(rel):
                continue
            m = re.search(rx, walk.text(rel) or "")
            if m:
                add(host_of(m.group(1)), "%s %s" % (rel, name))
    if walk.has("package.json"):  # homepage often names a code host: used only when another source agrees
        try:
            home = json.loads(walk.text("package.json") or "").get("homepage")
        except (ValueError, AttributeError):
            home = None
        h = host_of(home) if isinstance(home, str) else None
        if h in found:
            found[h].append("package.json homepage")
    return [{"host": h, "from": src} for h, src in found.items()]


# ---- brand_colors ----

HEX = re.compile(r"(?<![\w&#])#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})(?![0-9a-zA-Z_-])")
STYLE_EXT = (".css", ".scss", ".sass", ".less")
PART_EXT = (".astro", ".vue", ".svelte", ".html", ".htm")  # their <style> blocks are styles too
META_EXT = (".html", ".htm", ".astro", ".jsx", ".tsx", ".vue", ".svelte", ".njk", ".liquid")
STYLE_BLOCK = re.compile(r"<style\b[^>]*>(.*?)</style>", re.S | re.I)
META = (re.compile(r"<meta\b[^>]*\bname\s*=\s*[\"']theme-color[\"'][^>]*\bcontent\s*=\s*[\"'](#[0-9a-fA-F]{3,6})[\"']",
                   re.I),
        re.compile(r"<meta\b[^>]*\bcontent\s*=\s*[\"'](#[0-9a-fA-F]{3,6})[\"'][^>]*\bname\s*=\s*[\"']theme-color[\"']",
                   re.I))
MANIFEST_COLOR = re.compile(r"\"theme_color\"\s*:\s*\"(#[0-9a-fA-F]{3,6})\"")
PROP = re.compile(r"(?<![\w-])(--[A-Za-z0-9-]+)\s*:\s*#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})(?![0-9a-zA-Z_-])")
PROP_NAME = re.compile(r"^--(?:[a-z0-9]+-)*(brand|primary|accent)(?:-[a-z0-9]+)*$")
EXACT_PROPS = ("--brand", "--color-brand", "--primary", "--color-primary", "--accent", "--color-accent")
KINDS = ("brand", "primary", "accent")
TAILWIND = re.compile(r"(?<![\w-])['\"]?(brand|primary|accent)['\"]?\s*:\s*(?:\{[^{}]*?['\"]?(?:DEFAULT|500)['\"]?\s*:\s*)?"
                      r"['\"]#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})['\"]")
MAX_COLORS = 3


def norm_hex(h):
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return "#" + h.upper()


def _hls(color):
    r, g, b = (int(color[i:i + 2], 16) / 255.0 for i in (1, 3, 5))
    return colorsys.rgb_to_hls(r, g, b)


def chromatic(color):
    """HSL saturation >= 0.30 and 0.15 <= lightness <= 0.85 (greys, white, black and pastels are not brand colours)."""
    _h, l, s = _hls(color)
    return s >= 0.30 and 0.15 <= l <= 0.85


def near(a, b):
    """The same hue (within 10°) and lightness within 0.1: two shades of one colour."""
    ha, la, _ = _hls(a)
    hb, lb, _ = _hls(b)
    d = abs(ha - hb) * 360
    return min(d, 360 - d) <= 10 and abs(la - lb) < 0.1


def _own_style(data):
    """Not a vendor build: no `/*!` or `@license` banner in the first 300 bytes."""
    return data is not None and not BANNER.search(data[:300])


def _declarations(text):
    """Hex colours in declaration values (after a `:`), not in selectors such as `#add {`."""
    for m in HEX.finditer(text):
        start = max(text.rfind(c, 0, m.start()) for c in "{;}\n")
        if ":" in text[start + 1:m.start()]:
            yield norm_hex(m.group(1))


def brand_colors(walk):
    tier1, tier2, counts = [], [], {}  # counts: color -> {file: n}
    styles = [f for f in walk.files if f.lower().endswith(STYLE_EXT)]
    parts = [f for f in walk.files if f.lower().endswith(PART_EXT)]
    metas = [f for f in walk.files if f.lower().endswith(META_EXT) and f not in parts]
    manifests = [f for f in walk.files if f.lower().endswith(".webmanifest") or os.path.basename(f) == "manifest.json"]
    tailwinds = [f for f in walk.files if re.match(r"^tailwind\.config\.(js|cjs|mjs|ts)$", f)]
    for rel in manifests + tailwinds + styles + parts + metas:
        data = walk.read(rel)
        if not _own_style(data):
            continue
        text = data.decode("utf-8", "replace")
        low = rel.lower()
        if rel in manifests:
            for m in MANIFEST_COLOR.finditer(text):
                tier1.append((1, norm_hex(m.group(1)), rel, "theme_color in %s" % rel))
            continue
        if rel in tailwinds:
            for m in TAILWIND.finditer(text):
                tier2.append(((KINDS.index(m.group(1)), 1), norm_hex(m.group(2)), rel,
                              "%s in %s" % (m.group(1), rel)))
            continue
        if low.endswith(META_EXT):
            for rx in META:
                for m in rx.finditer(text):
                    tier1.append((0, norm_hex(m.group(1)), rel, "theme-color in %s" % rel))
        style = text if low.endswith(STYLE_EXT) else "\n".join(STYLE_BLOCK.findall(text)) if low.endswith(PART_EXT) else ""
        if not style:
            continue
        for m in PROP.finditer(style):
            name = m.group(1).lower()
            k = PROP_NAME.match(name)
            if not k or name.startswith("--bs-"):
                continue
            rank = (KINDS.index(k.group(1)), 0 if name in EXACT_PROPS else 1)
            tier2.append((rank, norm_hex(m.group(2)), rel, "%s in %s" % (name, rel)))
        for c in _declarations(style):
            counts.setdefault(c, {}).setdefault(rel, 0)
            counts[c][rel] += 1
    cands = []
    for _r, c, rel, ev in sorted(tier1, key=lambda x: x[0]) + sorted(tier2, key=lambda x: x[0]):
        cands.append({"color": c, "from": rel, "evidence": ev})
    for c, per in sorted(counts.items(), key=lambda kv: (-sum(kv[1].values()), kv[0])):
        n = sum(per.values())
        most = sorted(per.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        cands.append({"color": c, "from": most, "evidence": "used %d times in %d files (most in %s)"
                      % (n, len(per), most)})
    out = []
    for cand in cands:
        if not chromatic(cand["color"]) or any(cand["color"] == o["color"] or near(cand["color"], o["color"])
                                               for o in out):
            continue
        out.append(cand)
        if len(out) == MAX_COLORS:
            break
    return out


# ---- logos ----

LOGO_EXT = (".svg", ".png", ".webp", ".jpg", ".jpeg")
LOGO_NAME = re.compile(r"^(?:(?:site[-_])?logo|brand)([-_.].*)?$")
ICON_NAME = re.compile(r"^(?:icon\.svg|favicon\.svg|apple-touch-icon.*\.png|android-chrome-512.*\.png|favicon.*\.png)$")
MAX_LOGOS = 3


def png_size(data):
    """[width, height] from a PNG's IHDR (bytes 16-24), or None."""
    if not data or len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        return None
    return [int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")]


def logos(walk, roots):
    homes = [f.rstrip("/") + "/" for f in (roots or {}).values()] + ["src/assets/"]
    found = []
    for rel in walk.files:
        base = os.path.basename(rel).lower()
        ext = os.path.splitext(base)[1]
        if ext not in LOGO_EXT:
            continue
        stem = base[:-len(ext)]
        if LOGO_NAME.match(base):
            tier, plain = 0, stem in ("logo", "site-logo", "site_logo", "brand")
        elif ICON_NAME.match(base):
            tier, plain = 1, True
        else:
            continue
        if walk.stat(rel, None) is None:  # any size: only a PNG's first 24 bytes are read
            continue
        size = png_size(walk.read(rel, 24, None)) if ext == ".png" else None
        area = size[0] * size[1] if size else 0
        key = (tier, not plain, not any(rel.startswith(h) for h in homes), LOGO_EXT.index(ext if ext != ".jpeg" else
                                                                                           ".jpg"), -area, rel)
        found.append((key, {"path": rel, "from": "logo file name" if tier == 0 else "site icon", "size": size}))
    return [d for _k, d in sorted(found, key=lambda x: x[0])[:MAX_LOGOS]]


def analyze(top, git=None, studio_root="studio"):
    roots, src = web_roots(top)
    out = {"web_roots": roots, "web_roots_from": src, "content_folders": content_folders(top),
           "lfs": "filter=lfs" in (_read(os.path.join(top, ".gitattributes")) or ""),
           "studio_root": studio_root, "studio_root_problem": studio_root_free(top, studio_root)}
    if git is not None:
        from ..hooks import install as I
        try:
            out["hook_manager"] = I.detect(git, top).get("manager")
        except Exception as e:  # noqa: BLE001 — a draft only
            out["hook_manager"] = "unknown (%s)" % e
    out["ask_husky"] = out.get("hook_manager") == "husky"
    walk = Walk(top, git, studio_root)
    out["public_domains"] = public_domains(walk, roots)
    out["brand_colors"] = brand_colors(walk)
    out["logos"] = logos(walk, roots)
    out["partial"] = walk.partial
    return out
