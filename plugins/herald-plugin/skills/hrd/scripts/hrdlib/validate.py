"""Deterministic content gate (plan §3.5) driven by `docs/editorial/gate-rules.json`.

Checks: frontmatter keys, body length range, forbidden phrases (INV6: `draft` rules warn,
`confirmed` rules block), internal article links, referenced images (must exist and must not
be gitignored — an ignored image would deploy from this machine only). Readability hints
(`prose.py`) ride along under `prose`; they never fail the gate.
"""

import os
import re

from .prose import safe_report
from .util import read_json, run

DEFAULT_RULES = {
    "frontmatter": {"required": ["title", "description", "slug", "date"]},
    "length": {"min_chars": 0, "max_chars": None, "count": "nonspace", "per_category": {}},
    "forbidden": [],
    "links": {"check": True},
    "images": {"check": True, "public_dir": "public"},
    "prose": {},
}

FM_RE = re.compile(r"\A---\n(.*?)\n---\n?(.*)\Z", re.S)
LINK_RE = re.compile(r"\]\((/[^)\s#?]*)[^)]*\)|href=[\"'](/[^\"'#?]*)")
IMG_RE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)(?:\s+[\"'][^)]*[\"'])?\)|<img[^>]*\ssrc=[\"']([^\"']+)[\"']|<source[^>]*\ssrcset=[\"']([^\"'\s]+)")


def parse_frontmatter(text):
    m = FM_RE.match(text)
    if not m:
        return None, text
    fm = {}
    for line in m.group(1).splitlines():
        if not line or line.startswith((" ", "\t", "-", "#")):
            continue
        key, sep, val = line.partition(":")
        if sep:
            fm[key.strip()] = val.strip().strip("'\"")
    return fm, m.group(2)


def body_chars(body, mode):
    text = re.sub(r"<[^>]+>", "", body)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    if mode == "all":
        return len(text)
    return len(re.sub(r"\s", "", text))


def load_rules(root):
    rules = read_json(os.path.join(root, "docs", "editorial", "gate-rules.json"), {})
    out = {}
    for k, v in DEFAULT_RULES.items():
        if isinstance(v, dict):
            given = rules.get(k)
            out[k] = {**v, **given} if isinstance(given, dict) else dict(v)
        else:
            out[k] = rules.get(k, v)
    return out


def ignored(root, rel):
    return run(["git", "check-ignore", "-q", rel], cwd=root, check=False).returncode == 0


def validate(root, cfg, file_path):
    rules = load_rules(root)
    errors, warnings = [], []
    full = file_path if os.path.isabs(file_path) else os.path.join(root, file_path)
    try:
        text = open(full, encoding="utf-8").read()
    except OSError as e:
        return {"ok": False, "errors": ["cannot read %s: %s" % (file_path, e)], "warnings": [],
                "prose": {"warnings": [], "stats": {}}}
    fm, body = parse_frontmatter(text)
    if fm is None:
        errors.append("frontmatter (---) missing or malformed")
        fm = {}
    for key in rules["frontmatter"].get("required", []):
        if not fm.get(key):
            errors.append("frontmatter `%s` missing" % key)
    if "--" in fm.get("slug", ""):
        errors.append("slug must not contain `--` (Herald branch separator)")
    ln = rules["length"]
    cat = fm.get("category")
    limits = {**ln, **(ln.get("per_category", {}).get(cat, {}) if cat else {})}
    n = body_chars(body, ln.get("count", "nonspace"))
    if limits.get("min_chars") and n < limits["min_chars"]:
        errors.append("body is %d chars; minimum %d%s" % (n, limits["min_chars"], " for %s" % cat if cat else ""))
    if limits.get("max_chars") and n > limits["max_chars"]:
        errors.append("body is %d chars; maximum %d%s" % (n, limits["max_chars"], " for %s" % cat if cat else ""))
    for rule in rules.get("forbidden", []):
        pat = rule.get("pattern", "")
        if not pat:
            continue
        hit = re.search(pat, body) if rule.get("regex") else (pat in body)
        if hit:
            msg = "forbidden phrase %r%s" % (pat, " (%s)" % rule["note"] if rule.get("note") else "")
            (errors if rule.get("status") == "confirmed" else warnings).append(msg)
    if rules["links"].get("check", True):
        prefix, _, suffix = cfg.get("site", "url_pattern", default="/{slug}/").partition("{slug}")
        for m in LINK_RE.finditer(body):
            link = m.group(1) or m.group(2)
            if prefix and link.startswith(prefix):
                slug = link[len(prefix):].strip("/").split("/")[0]
                if slug and not os.path.exists(os.path.join(root, cfg.body_path(slug))):
                    # with url_pattern "/{slug}/" every root link looks like an article: warn only
                    (warnings if prefix == "/" else errors).append("internal link %s points to no article" % link)
    if rules["images"].get("check", True):
        pub = rules["images"].get("public_dir", "public").rstrip("/")
        for m in IMG_RE.finditer(text):
            src = next(g for g in m.groups() if g)
            if re.match(r"^[a-z]+:", src) or src.startswith("//"):  # http:, data:, protocol-relative
                continue
            src = re.split(r"[?#]", src, 1)[0]
            if src.startswith("/"):
                relp = "%s%s" % (pub, src)
            else:  # relative to the article file
                relp = os.path.normpath(os.path.join(os.path.dirname(os.path.relpath(full, root)), src))
            if not os.path.exists(os.path.join(root, relp)):
                errors.append("image %s does not exist (%s)" % (src, relp))
            elif ignored(root, relp):
                errors.append("image %s is gitignored — it would deploy from this machine only" % src)
    return {"ok": not errors, "errors": errors, "warnings": warnings, "chars": n,
            "prose": safe_report(body, cfg.get("language"), rules.get("prose"), _offset(text, body))}


def _offset(text, body):
    return text[:len(text) - len(body)].count("\n") if body and text.endswith(body) else 0


def prose_for(root, cfg, file_path):
    """Readability hints alone (used when config.commands.validate replaces the built-in gate)."""
    full = file_path if os.path.isabs(file_path) else os.path.join(root, file_path)
    try:
        text = open(full, encoding="utf-8").read().replace("\r\n", "\n")
        body = parse_frontmatter(text)[1]
        toml = re.match(r"\+\+\+\n.*?\n\+\+\+\n?", text, re.S)  # Hugo-style frontmatter
        if toml:
            body = text[toml.end():]
        rules = load_rules(root).get("prose")
    except Exception as e:  # noqa: BLE001 — the repo's own validator decides; hints never break it
        return {"warnings": ["prose: hints unavailable (%s: %s)" % (type(e).__name__, e)], "stats": {}}
    return safe_report(body, cfg.get("language"), rules, _offset(text, body))
