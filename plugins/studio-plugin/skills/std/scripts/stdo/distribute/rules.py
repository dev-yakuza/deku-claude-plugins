"""A platform's rules (m1-plan §10): `.claude/studio/platforms/<platform>.md` (P-CRIT — the agent drafts it, a person
checks it against the platform's own help; `setup.py platform apply` writes it and fills `checked`). The rules are the
JSON block between `<!-- studio:rules -->` and `<!-- /studio:rules -->`:

    {"title_max": 100, "description_max_bytes": 5000, "hashtags_max": 15, "required": ["<notice line>", …],
     "chapters": "required", "link": "body"}

- `title_max`: characters of the title, or null — the platform has no title (the copy has none).
- exactly one of `description_max_bytes` (the description's UTF-8 bytes — the YouTube Data API's "maximum length of
  5000 bytes", the stricter of its two published limits; U-M1h, J172) and `description_max_chars` (characters).
- `hashtags_max`: 0 or more. `required`: the notice lines the description carries word for word.
- `chapters`: "required" (the render's chapters in the description) or "none" (no chapters). `link`: "body" (the
  source link line in the description) or "none". A block without them (v1) reads as "required" and "body".

The frontmatter: `platform`, `audience` (public | internal), `checked`, `outputs` (a list of `name`, `aspect`,
`max_duration`, optional `layout` and `shot`) and `sources` (the https pages the rules were checked against).
A missing or invalid block, or an empty `checked`, fails the copy check (the closed side)."""

import json
import os
import re

BLOCK = re.compile(r"<!-- studio:rules -->\s*```json\s*\n(.*?)\n```\s*<!-- /studio:rules -->", re.S)
CHECKED = re.compile(r"^checked:\s*[\"']?([^\"'\n]*)[\"']?\s*$", re.M)
AUDIENCE = re.compile(r"^audience:\s*[\"']?([^\"'\n]*)[\"']?\s*$", re.M)
AUDIENCES = ("public", "internal")
RULE_KEYS = ("title_max", "description_max_bytes", "description_max_chars", "hashtags_max", "required", "chapters",
             "link")
CHAPTERS = ("required", "none")
LINKS = ("body", "none")


class RulesProblem(Exception):
    pass


def path(repo, platform):
    """The platform's rules file — only for a safe name, and only inside .claude/studio/platforms/ (M1h review Y1)."""
    from ..state.schema import platform_ok
    if not platform_ok(platform):
        raise RulesProblem("%r is not a platform name" % (platform,))
    base = os.path.realpath(os.path.join(repo, ".claude", "studio", "platforms"))
    p = os.path.join(base, "%s.md" % platform)
    if not os.path.realpath(p).startswith(base + os.sep):
        raise RulesProblem("the rules of %s are not inside .claude/studio/platforms/" % platform)
    return p


def _head(text):
    if text.startswith("---"):
        end = text.find("\n---", 3)
        return text[3:end] if end > 0 else ""
    return ""


def audience(repo, platform):
    """The frontmatter's `audience` (`public` | `internal`), or None when the file has none, another value or cannot be
    read (the closed side: record-brief refuses)."""
    try:
        with open(path(repo, platform), encoding="utf-8") as f:
            m = AUDIENCE.search(_head(f.read()))
    except (OSError, UnicodeDecodeError, RulesProblem):
        return None
    v = m.group(1).strip() if m else None
    return v if v in AUDIENCES else None


def parse(text):
    """(rules, checked date or "")."""
    head = _head(text)
    m = CHECKED.search(head)
    checked = m.group(1).strip() if m else ""
    b = BLOCK.search(text)
    if not b:
        raise RulesProblem("no studio:rules JSON block")
    try:
        data = json.loads(b.group(1))
    except ValueError as e:
        raise RulesProblem("the rules block is not JSON (%s)" % e)
    if not isinstance(data, dict):
        raise RulesProblem("the rules block is not an object")
    if "description_max" in data and "description_max_bytes" not in data:
        raise RulesProblem("description_max (characters) is no longer read: the description limit is in UTF-8 bytes — "
                           "a person replaces it with description_max_bytes (the plugin's platforms/ template)")
    unknown = sorted(k for k in data if k not in RULE_KEYS)
    if unknown:
        raise RulesProblem("unknown rules keys: %s — /std platform refresh <name> drafts a corrected file"
                           % ", ".join(unknown))

    def whole(k, low):
        v = data.get(k)
        return isinstance(v, int) and not isinstance(v, bool) and v >= low
    if not (data.get("title_max", 0) is None or whole("title_max", 1)):
        raise RulesProblem("title_max must be a positive whole number, or null (the platform has no title)")
    limits = [k for k in ("description_max_bytes", "description_max_chars") if k in data]
    if len(limits) != 1:
        raise RulesProblem("give exactly one of description_max_bytes and description_max_chars")
    if not whole(limits[0], 1):
        raise RulesProblem("%s must be a positive whole number" % limits[0])
    if not whole("hashtags_max", 0):
        raise RulesProblem("hashtags_max must be a whole number (0 or more)")
    req = data.get("required")
    if not isinstance(req, list) or not all(isinstance(x, str) and x.strip() for x in req):
        raise RulesProblem("required must be a list of notice lines")
    data = dict(data)
    data.setdefault("chapters", "required")
    data.setdefault("link", "body")
    if data["chapters"] not in CHAPTERS:
        raise RulesProblem("chapters must be \"required\" or \"none\"")
    if data["link"] not in LINKS:
        raise RulesProblem("link must be \"body\" or \"none\"")
    return data, checked


def frontmatter(text):
    """{key: value} of a platform file's frontmatter, read in the one shape the shipped files use: `key: value`
    scalars (quotes dropped; `null` → None; whole numbers → int) and the lists `outputs` (`  - name: x` items with
    `    key: value` lines) and `sources` (`  - <url>`). RulesProblem for anything else."""
    if not text.startswith("---"):
        raise RulesProblem("no frontmatter (--- … ---)")
    end = text.find("\n---", 3)
    if end < 0:
        raise RulesProblem("the frontmatter does not end")
    out, cur, item = {}, None, None

    def scalar(v):
        v = v.strip()
        if len(v) >= 2 and v[0] in "\"'" and v[-1] == v[0]:
            return v[1:-1]
        if v in ("null", "~", ""):
            return None
        return int(v) if re.match(r"^-?[0-9]{1,9}$", v) else v
    for n, line in enumerate(text[3:end].split("\n"), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = re.match(r"^([a-z_]+):(?:\s+(.*)|)$", line)
        if m:
            k, v = m.group(1), m.group(2) or ""
            if k in out:
                raise RulesProblem("frontmatter key %s twice" % k)
            if k in ("outputs", "sources") and not v.strip():
                out[k], cur, item = [], k, None
            else:
                out[k], cur, item = scalar(v), None, None
            continue
        m = re.match(r"^  - (?:([a-z_]+):(?:\s+|$))?(.*)$", line)
        if m and cur == "sources" and m.group(1) is None:
            out["sources"].append(scalar(m.group(2)))
            continue
        if m and cur == "outputs" and m.group(1):
            item = {m.group(1): scalar(m.group(2))}
            out["outputs"].append(item)
            continue
        m = re.match(r"^    ([a-z_]+):\s*(.*)$", line)
        if m and cur == "outputs" and item is not None:
            if m.group(1) in item:
                raise RulesProblem("output key %s twice" % m.group(1))
            item[m.group(1)] = scalar(m.group(2))
            continue
        raise RulesProblem("frontmatter line %d is not in the shape Studio reads: %r" % (n, line[:80]))
    return out


def read(repo, platform):
    p = path(repo, platform)
    try:
        with open(p, encoding="utf-8") as f:
            return parse(f.read())
    except RulesProblem as e:
        raise RulesProblem(str(e).replace("<name>", platform))
    except OSError as e:
        raise RulesProblem("cannot read .claude/studio/platforms/%s.md (%s)" % (platform, e.strerror))
