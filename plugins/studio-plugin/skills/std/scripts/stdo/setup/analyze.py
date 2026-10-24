"""`setup.py init analyze` (m1-plan §5.2 step 2, read-only): drafts for the interview — web_roots from the static site's
settings, the folders that hold writing, the hook manager, LFS, and whether the studio folder name is free."""

import glob
import os
import re

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
    return out
