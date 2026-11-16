"""`work/source/page.md` of a URL source: the text blocks of s2v capture's JSON as Markdown the source analyst reads and
the excerpts are checked against (pure: the same JSON gives the same bytes).

- The first line is `<!-- url: <the page's final address> -->`, then the title as a `# ` heading (when there is one).
- One block per JSON text block, in order, separated by a blank line; each TextKind has a fixed prefix (KIND_PREFIX; an
  unknown kind is a paragraph). A block's line breaks (`<br>` on the page) stay line breaks; the lines after the first
  carry the kind's continuation prefix (a heading's lines are joined with a space: a heading is one line).
- The text is escaped so it cannot be read as markup: `&`, `<`, `>` as entities, and a line starting with `#`, `-`,
  `+`, `*`, `=`, `~`, `|`, `_`, `[`, a digit with `.` or `)`, or ``` gets a leading backslash. Line and paragraph
  separators (U+0085, U+2028, U+2029) are line breaks first (so the line after one is escaped too), other control
  characters (C0, C1) spaces, and bidirectional controls are dropped.
- Ruby is not inlined: each block's pairs go to `page-ruby.json` as {block index: [[base, reading], …]} (the index of
  the block in the JSON's `text`, from 0) — the analyst's ruby pairs are checked against it."""

import json
import re
import unicodedata

KIND_PREFIX = {"heading": "## ", "paragraph": "", "list-item": "- ", "quote": "> ", "code": "    ",
               "table-cell": "| ", "caption": "", "figcaption": ""}
# what the second and later lines of a block start with
KIND_MORE = {"list-item": "  ", "quote": "> ", "code": "    ", "table-cell": "  "}
LEAD = re.compile(r"^(?:[#\-+*=~|_\[]|[0-9]+[.)]|```)")
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f\x80-\x84\x86-\x9f]")
# line and paragraph separators a reader may show as a line break: a line break here, so each line is escaped
BREAKS = re.compile(r"[\x85\u2028\u2029]")
# bidirectional controls (they can make the text read otherwise than its characters): dropped
BIDI = re.compile(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069]")


def escape_line(line):
    t = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return "\\" + t if LEAD.match(t) else t


def _lines(text):
    t = unicodedata.normalize("NFC", text if isinstance(text, str) else "")
    t = BIDI.sub("", BREAKS.sub("\n", t.replace("\r\n", "\n").replace("\r", "\n")))
    t = CONTROL.sub(" ", t.replace("\t", " "))
    return [x.strip() for x in t.split("\n") if x.strip()]


def _comment_url(url):
    u = url if isinstance(url, str) else ""
    u = BIDI.sub("", CONTROL.sub("", BREAKS.sub("", u.replace("\n", "").replace("\r", ""))))
    return u.replace("--", "-%2D").replace(">", "%3E")


def block(kind, text):
    """The Markdown of one text block (None when it has no text)."""
    lines = _lines(text)
    if not lines:
        return None
    k = kind if kind in KIND_PREFIX else "paragraph"
    if k == "heading":
        lines = [" ".join(lines)]
    first = KIND_PREFIX[k] + escape_line(lines[0])
    more = KIND_MORE.get(k, "")
    return "\n".join([first] + [more + escape_line(x) for x in lines[1:]])


def render(data):
    """(page.md text, page-ruby.json text) of s2v capture's JSON object."""
    data = data if isinstance(data, dict) else {}
    parts = ["<!-- url: %s -->" % _comment_url(data.get("url"))]
    title = _lines(data.get("title"))
    if title:
        parts.append("# " + escape_line(" ".join(title)))
    ruby = []
    for i, b in enumerate(data.get("text") or []):
        if not isinstance(b, dict):
            continue
        md = block(b.get("kind"), b.get("text"))
        if md is not None:
            parts.append(md)
        pairs = []
        for r in b.get("ruby") or []:
            if isinstance(r, dict) and isinstance(r.get("base"), str) and isinstance(r.get("reading"), str):
                pairs.append([unicodedata.normalize("NFC", r["base"]), unicodedata.normalize("NFC", r["reading"])])
        if pairs:
            ruby.append((str(i), pairs))
    page = "\n\n".join(parts) + "\n"
    body = ",\n".join("  %s: %s" % (json.dumps(k), json.dumps(v, ensure_ascii=False)) for k, v in ruby)
    return page, ("{\n%s\n}\n" % body if ruby else "{}\n")


def ruby_pairs(text):
    """{(base, reading)} of a page-ruby.json text (empty when it is not that shape)."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return set()
    out = set()
    for pairs in (data.values() if isinstance(data, dict) else []):
        for p in pairs if isinstance(pairs, list) else []:
            if isinstance(p, list) and len(p) == 2 and all(isinstance(x, str) for x in p):
                out.add((p[0], p[1]))
    return out
