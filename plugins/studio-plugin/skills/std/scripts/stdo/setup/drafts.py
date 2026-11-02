"""`init analyze` drafts added in 0.0.26 (pilot-2 N5 · N4), plugin only: `project_names` (the site's title, the web
manifest, package.json, the origin remote's repository name, else the folder name) and `image_folders` (the folders
holding the images the writing shows, for the visibility question). Every file is read through analyze.Walk: tracked
files only, link-free, within the budget."""

import html
import json
import os
import re

from ..source import assets, refs

# ---- project_names (N5) ----

MAX_NAMES = 3
NAME_MAX = 60
PLACEHOLDERS = frozenset(("my-app", "astro-blog", "website", "app", "site", "blog", "docs"))
Q = r"""['"`]([^'"`\n]+)['"`]"""
SITE_TITLES = (  # (files at the top level, the pattern, what the evidence says)
    (("hugo.toml", "config.toml"), r"(?m)^\s*title\s*=\s*['\"]([^'\"\n]+)['\"]", "title"),
    (("hugo.yaml", "hugo.yml", "config.yaml", "config.yml"), r"(?m)^title\s*:\s*['\"]?([^'\"\n#]+?)['\"]?\s*(?:#.*)?$",
     "title"),
    (("_config.yml", "_config.yaml"), r"(?m)^title\s*:\s*['\"]?([^'\"\n#]+?)['\"]?\s*(?:#.*)?$", "title"),
    (("docusaurus.config.js", "docusaurus.config.ts", "docusaurus.config.mjs"), r"\btitle\s*:\s*" + Q, "title"),
    (("gatsby-config.js", "gatsby-config.ts", "gatsby-config.mjs"),
     r"\bsiteMetadata\s*:\s*\{[^{}]*?\btitle\s*:\s*" + Q, "siteMetadata.title"),
    (("mkdocs.yml", "mkdocs.yaml"), r"(?m)^site_name\s*:\s*['\"]?([^'\"\n#]+?)['\"]?\s*(?:#.*)?$", "site_name"),
    (("src/consts.ts", "src/consts.js", "src/consts.mjs", "src/config.ts", "src/config.js"),
     r"\b(?:SITE_TITLE|SITE_NAME)\b\s*[:=]\s*" + Q, "SITE_TITLE"),
    (("astro.config.mjs", "astro.config.js", "astro.config.ts", "astro.config.cjs", "astro.config.mts"),
     r"\bstarlight\s*\(\s*\{[^{}]*?\btitle\s*:\s*" + Q, "starlight title"),
)
TITLE_TAG = re.compile(r"<title\b[^>]*>(.*?)</title\s*>", re.I | re.S)
ASTRO_CONFIGS = ("astro.config.mjs", "astro.config.js", "astro.config.ts", "astro.config.cjs", "astro.config.mts")


def clean_name(value):
    """The name as offered (entities decoded, spaces collapsed), or None: empty, longer than 60 characters, a
    template expression, or a placeholder name."""
    if not isinstance(value, str) or "\n" in value.strip("\n"):
        return None
    v = " ".join(html.unescape(value).split())
    if not v or len(v) > NAME_MAX or "\n" in v or any(c in v for c in "{}<>") or v.lower() in PLACEHOLDERS:
        return None
    return v


def _index_pages(walk, roots):
    """The home pages whose <title> names the site: the web root's index.html, and Astro's src/pages/index."""
    out = [f.rstrip("/") + "/index.html" for f in (roots or {}).values()]
    if any(walk.has(c) for c in ASTRO_CONFIGS):
        out += ["src/pages/index.astro", "src/pages/index.html"]
    return out


def _manifests(walk, roots):
    homes = [f.rstrip("/") + "/" for f in (roots or {}).values()]
    found = [f for f in walk.files if f.lower().endswith(".webmanifest") or os.path.basename(f) == "manifest.json"]
    return sorted(found, key=lambda f: (not any(f.startswith(h) for h in homes), f.count("/"), f))


def origin_name(git):
    """The origin remote's repository name (the URL's last path segment without `.git`), or None. The URL itself is
    never returned: it may carry a user name or a token."""
    if git is None:
        return None
    try:
        out = git.run("remote", "get-url", "origin", check=False, timeout=10)
    except Exception:  # noqa: BLE001 — a draft only
        return None
    if out.returncode != 0:
        return None
    url = out.stdout.decode("utf-8", "replace").strip()
    url = re.split(r"[?#]", url, maxsplit=1)[0].rstrip("/")
    last = re.split(r"[/:\\]", url)[-1]
    if last.endswith(".git"):
        last = last[:-4]
    return last if re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*$", last or "") else None


def project_names(walk, roots, git, top):
    """Up to 3 {name, from}, deduplicated case-insensitively: the site title, the web manifest's name, package.json's
    name, the origin remote's repository name; the folder name only when there is none."""
    cands = []

    def add(value, src):
        name = clean_name(value)
        if name and not any(c["name"].lower() == name.lower() for c in cands):
            cands.append({"name": name, "from": src})

    for files, rx, what in SITE_TITLES:
        for rel in files:
            if walk.has(rel):
                m = re.search(rx, walk.text(rel) or "")
                if m:
                    add(m.group(1).strip(), "%s %s" % (rel, what))
    for rel in _index_pages(walk, roots):
        if walk.has(rel):
            m = TITLE_TAG.search(walk.text(rel) or "")
            if m:
                add(m.group(1), "%s <title>" % rel)
    for rel in _manifests(walk, roots):
        try:
            data = json.loads(walk.text(rel) or "")
        except ValueError:
            continue
        if isinstance(data, dict):
            for key in ("name", "short_name"):
                if isinstance(data.get(key), str):
                    add(data[key], "%s %s" % (rel, key))
    if walk.has("package.json"):
        try:
            name = json.loads(walk.text("package.json") or "").get("name")
        except (ValueError, AttributeError):
            name = None
        if isinstance(name, str):
            add(re.sub(r"^@[^/]+/", "", name), "package.json name")
    add(origin_name(git), "git remote origin")
    if not cands:
        folder = os.path.basename(os.path.realpath(top).rstrip(os.sep))
        v = " ".join(folder.split())
        if v and len(v) <= NAME_MAX:
            cands.append({"name": v, "from": "folder name"})
    return cands[:MAX_NAMES]


# ---- image_folders (N4) ----

IMG_BUDGET_FILES = 400
IMG_BUDGET_BYTES = 4 * 1024 * 1024
MD_EXT = (".md", ".mdx")


def _anchor(rel, roots, writing):
    """The folder an image is grouped under: the first folder below a web root (`public/blog-images`), the writing
    folder that holds it, else its first two folders. A file right in a web root gives None: a glob over the whole
    web root is never offered (it would mark every file the site serves public)."""
    parts = rel.split("/")[:-1]
    for folder in sorted((f.strip("/") for f in (roots or {}).values()), key=len, reverse=True):
        if rel.startswith(folder + "/"):
            below = rel[len(folder) + 1:].split("/")[:-1]
            return "/".join([folder] + below[:1]) if below else None
    for folder in sorted((f.strip("/") for f in writing), key=len, reverse=True):
        if rel.startswith(folder + "/"):
            return folder
    return "/".join(parts[:2]) or None


def image_folders(walk, roots, writing):
    """[{glob, images, posts, writing, example, via_web_root}] and the reasons the list is partial ([] when whole).
    The Markdown files of the writing folders are read (tracked only) with their own budget of 400 files / 4 MB inside
    the global one; each image reference goes through the resolver resolve_assets uses and counts only when the file
    is tracked."""
    from . import analyze as analyze_mod  # its budget and size limits (read at call time)
    reasons = []
    folders = [f.rstrip("/") + "/" for f in writing]
    mds = [f for f in walk.files if f.lower().endswith(MD_EXT) and any(f.startswith(w) for w in folders)]
    used_files = used_bytes = 0
    groups = {}  # anchor -> {"images": set, "posts": set, "writing": set, "site": bool, "relative": bool}
    for rel in mds:
        if walk.read_files >= analyze_mod.BUDGET_FILES or walk.read_bytes >= analyze_mod.BUDGET_BYTES:
            reasons.append("image_folders: the global read budget was used up before every post was read")
            walk.partial = True
            break
        if used_files >= IMG_BUDGET_FILES or used_bytes >= IMG_BUDGET_BYTES:
            reasons.append("image_folders: its budget (%d files / %d MB) was reached"
                           % (IMG_BUDGET_FILES, IMG_BUDGET_BYTES // (1024 * 1024)))
            break
        st = walk.stat(rel, None)
        if st is None:
            continue
        if st.st_size > analyze_mod.MAX_SIZE:
            reasons.append("image_folders: %s is over %d KB (not read)" % (rel, analyze_mod.MAX_SIZE // 1024))
            continue
        data = walk.read(rel, analyze_mod.MAX_SIZE)
        if data is None:
            continue
        used_files += 1
        used_bytes += len(data)
        found, _odd, _hidden = refs.extract_all(data.decode("utf-8", "replace"), assets.IMAGE_KEYS)
        own = next(w for w in folders if rel.startswith(w))
        for ref in found:
            for src in ref.candidates or [ref.src]:
                status, _why, img = assets.resolve(walk.top, rel, src, roots or {})
                anchor = _anchor(img, roots, folders) if status == "ok" and walk.has(img) else None
                if anchor is None:
                    continue
                g = groups.setdefault(anchor, {"images": set(), "posts": set(),
                                                                      "writing": set(), "site": False,
                                                                      "relative": False})
                g["images"].add(img)
                g["posts"].add(rel)
                g["writing"].add(own)
                g["site" if src.strip().startswith("/") else "relative"] = True
    out = [{"glob": a.rstrip("/") + "/**", "images": len(g["images"]), "posts": len(g["posts"]),
            "writing": sorted(g["writing"]), "example": sorted(g["images"])[0],
            "via_web_root": g["site"] and not g["relative"]}
           for a, g in groups.items()]
    out.sort(key=lambda d: (-d["posts"], -d["images"], d["glob"]))
    if reasons:
        walk.partial = True
    return out, reasons
