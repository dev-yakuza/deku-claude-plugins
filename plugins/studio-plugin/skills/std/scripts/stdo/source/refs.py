"""The images a Markdown source refers to (m1-plan §6.1): `![alt](src "title")` (an alt may hold one level of
brackets), reference images (`![alt][label]` with `[label]: src "title"`), HTML `<img>`, `<picture>` (every
`<source srcset>` candidate and the `<img>`), CSS `url(…)`, and the frontmatter's image keys (a scalar, a nested
`src`/`url`/`path`/`image`, or a list of either). Fenced code, inline code and HTML comments are skipped. Each reference
keeps the text that can say who owns it — alt, title, the caption (the rest of its line and the next non-empty line),
and its context (the whole surrounding `<figure>`, and a short window of lines around it). Lines that still look like
an image after extraction are counted as unparsed (`extract_all`)."""

import re

FENCE = re.compile(r"^\s{0,3}(```|~~~)")
_ALT = r"(?P<alt>(?:[^\[\]]|\[[^\[\]]*\])*)"
INLINE = re.compile(r"!\[" + _ALT + r"\]\(\s*(?P<src><[^>]*>|[^)\s]+)(?:\s+(?:\"(?P<t1>[^\"]*)\"|'(?P<t2>[^']*)'|"
                    r"\((?P<t3>[^)]*)\)))?\s*\)")
REFIMG = re.compile(r"!\[" + _ALT + r"\]\[(?P<label>[^\]]*)\]")
REFDEF = re.compile(r"^\s{0,3}\[(?P<label>[^\]]+)\]:\s*(?P<src><[^>]*>|\S+)(?:\s+(?:\"(?P<t1>[^\"]*)\"|'(?P<t2>[^']*)'|"
                    r"\((?P<t3>[^)]*)\)))?\s*$")
IMG = re.compile(r"<img\b[^>]*>", re.I)
PICTURE = re.compile(r"<picture\b.*?</picture\s*>", re.I | re.S)
FIGURE = re.compile(r"<figure\b.*?</figure\s*>", re.I | re.S)
SOURCE = re.compile(r"<source\b[^>]*>", re.I)
ATTR = re.compile(r"([A-Za-z_:][\w:.-]*)\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s\"'>]+)")
INLINE_CODE = re.compile(r"`[^`\n]*`")
CSSURL = re.compile(r"url\(\s*(?:\"(?P<q1>[^\"]*)\"|'(?P<q2>[^']*)'|(?P<u>[^)\s'\"]*))\s*\)", re.I)
TAG = re.compile(r"<[^>]*>")
IMAGE_LIKE = re.compile(r"\.(?:png|jpe?g|gif|webp|avif|svg|bmp|tiff?|heic)\b|<img\b|!\[|url\(", re.I)
FM_KEY = re.compile(r"^([A-Za-z_][\w-]*):\s*(.*?)\s*$")
FM_SRC_KEYS = ("src", "url", "path", "image")
WINDOW_UP, WINDOW_DOWN = 1, 3


class Ref(object):
    def __init__(self, kind, src, line, alt="", title="", caption="", candidates=None, context=""):
        self.kind, self.src, self.line = kind, src, line
        self.alt, self.title, self.caption = alt or "", title or "", caption or ""
        self.context = context or ""
        self.candidates = list(candidates or [src])

    def owner_text(self):
        return " ".join(x for x in (self.alt, self.title, self.caption, self.context) if x)


def attrs(tag):
    out = {}
    for k, v in ATTR.findall(tag):
        if v[:1] in "\"'":
            v = v[1:-1]
        out[k.lower()] = v
    return out


def _title(m):
    return m.group("t1") or m.group("t2") or m.group("t3") or ""


def _unangle(src):
    return src[1:-1] if src.startswith("<") and src.endswith(">") else src


def _unquote(v):
    v = v.strip()
    if v[:1] in "\"'" and v[-1:] == v[:1] and len(v) >= 2:
        return v[1:-1]
    return v


def srcset(value):
    """The URLs of a srcset ("a.webp 1x, b.png 2x")."""
    out = []
    for part in (value or "").split(","):
        bits = part.strip().split()
        if bits:
            out.append(bits[0])
    return out


def frontmatter(lines):
    """({top-level key: (value, line, [(line, text) of its indented block])}, end index) of a leading `---` block."""
    if not lines or lines[0].strip() != "---":
        return {}, 0
    out = {}
    cur = None
    for i in range(1, len(lines)):
        if lines[i].strip() in ("---", "..."):
            return out, i + 1
        m = FM_KEY.match(lines[i])
        if m:
            cur = m.group(1)
            out[cur] = (_unquote(m.group(2)), i + 1, [])
        elif cur and lines[i].strip() and (lines[i][:1] in " \t" or lines[i].lstrip().startswith("-")):
            out[cur][2].append((i + 1, lines[i]))
        elif lines[i].strip():
            cur = None
    return {}, 0


def _fm_refs(key, value, line, block):
    """The Refs of one frontmatter image key: a scalar, a flow list, or a nested mapping / list (one Ref per item)."""
    if value and not value.startswith(("[", "{")):
        return [Ref("frontmatter", value, line)], [line]
    if value.startswith("["):
        items = [_unquote(x) for x in value.strip("[]").split(",") if x.strip()]
        return [Ref("frontmatter", x, line) for x in items], [line]
    if value:
        return [], []
    items = []  # [(first line, {key: value}, [texts], scalar or None)]
    for ln, text in block:
        s = text.strip()
        new = s.startswith("-")
        if new:
            s = s[1:].strip()
            items.append([ln, {}, [], None])
        elif not items:
            items.append([ln, {}, [], None])
        it = items[-1]
        m = FM_KEY.match(s)
        if m:
            it[1][m.group(1)] = (_unquote(m.group(2)), ln)
        elif s and new:
            it[3] = (_unquote(s), ln)
        it[2].append(s)
    out, used = [], []
    for first, kv, texts, scalar in items:
        src = scalar
        for k in FM_SRC_KEYS:
            if src is None and kv.get(k, ("", 0))[0]:
                src = kv[k]
        if src is None:
            continue
        out.append(Ref("frontmatter", src[0], src[1], alt=kv.get("alt", ("", 0))[0],
                       title=kv.get("title", ("", 0))[0], context=" ".join(texts)))
        used += [first] + [v[1] for v in kv.values()]
    return out, used


def _caption(lines, i, rest):
    """The rest of the image's own line and the next line when it is text (not another block)."""
    parts = [rest.strip()]
    if i + 1 < len(lines):
        nxt = lines[i + 1].strip()
        if nxt and not nxt.startswith(("#", "!", "<img", "<picture", "```", "~~~", "|", "- ", "* ")):
            parts.append(nxt)
    return " ".join(p for p in parts if p)


def _blank(s):
    return " " * len(s)


def mask(lines, start):
    """The lines with frontmatter, fenced code, inline code and HTML comments blanked (positions kept)."""
    body = list(lines)
    fence = None
    comment = False
    for i in range(len(body)):
        if i < start:
            body[i] = ""
            continue
        line = body[i]
        if not comment:
            m = FENCE.match(line)
            if fence:
                if m and m.group(1) == fence:
                    fence = None
                body[i] = ""
                continue
            if m:
                fence = m.group(1)
                body[i] = ""
                continue
            line = INLINE_CODE.sub(lambda x: _blank(x.group(0)), line)
        out, pos = [], 0
        while pos <= len(line):
            if comment:
                end = line.find("-->", pos)
                if end < 0:
                    out.append(_blank(line[pos:]))
                    break
                out.append(_blank(line[pos:end + 3]))
                pos, comment = end + 3, False
            else:
                beg = line.find("<!--", pos)
                if beg < 0:
                    out.append(line[pos:])
                    break
                out.append(line[pos:beg])
                pos, comment = beg, True
                end = line.find("-->", beg + 4)
                if end < 0:
                    out.append(_blank(line[beg:]))
                    break
                out.append(_blank(line[beg:end + 3]))
                pos, comment = end + 3, False
        body[i] = "".join(out)
    return body


def extract(text, image_keys=()):
    """[Ref] in reading order."""
    return extract_all(text, image_keys)[0]


def extract_all(text, image_keys=()):
    """([Ref] in reading order, [line numbers that still look like an image but were not parsed])."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    fm, start = frontmatter(lines)
    refs, fm_used = [], set()
    for k in image_keys:
        if k in fm:
            rs, used = _fm_refs(k, *fm[k])
            refs += rs
            fm_used.update(used)
    body = mask(lines, start)
    defs = {}
    def_lines = set()
    for i, l in enumerate(body):
        m = REFDEF.match(l)
        if m:
            defs[m.group("label").strip().lower()] = (_unangle(m.group("src")), _title(m), i)
            def_lines.add(i)
    joined = "\n".join(body)
    starts = [0]
    for l in body:
        starts.append(starts[-1] + len(l) + 1)

    def line_of(pos):
        lo, hi = 0, len(starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if starts[mid] <= pos:
                lo = mid
            else:
                hi = mid - 1
        return lo

    found = []  # (position, end position, first line, last line, Ref)
    masked = list(joined)

    def consume(a, b):
        for k in range(a, b):
            if masked[k] != "\n":
                masked[k] = " "

    for m in PICTURE.finditer(joined):
        block = m.group(0)
        cands = []
        for s in SOURCE.finditer(block):
            cands += srcset(attrs(s.group(0)).get("srcset"))
        img = IMG.search(block)
        a = attrs(img.group(0)) if img else {}
        if a.get("src"):
            cands.append(a["src"])
        i = line_of(m.start())
        end_line = line_of(m.end() - 1)
        rest = body[end_line][m.end() - starts[end_line]:] if end_line < len(body) else ""
        if cands:
            found.append((m.start(), m.end(), i, end_line,
                          Ref("picture", cands[0], i + 1, a.get("alt"), a.get("title"),
                              _caption(body, end_line, rest), cands)))
            consume(m.start(), m.end())
    pic_masked = "".join(masked)
    for m in IMG.finditer(pic_masked):
        a = attrs(m.group(0))
        if not a.get("src"):
            continue
        i = line_of(m.start())
        rest = body[i][:m.start() - starts[i]] + body[i][m.end() - starts[i]:]
        found.append((m.start(), m.end(), i, i, Ref("html", a["src"], i + 1, a.get("alt"), a.get("title"),
                                                    _caption(body, i, rest))))
        consume(m.start(), m.end())
    for m in INLINE.finditer(pic_masked):
        i = line_of(m.start())
        rest = body[i][:m.start() - starts[i]] + body[i][m.end() - starts[i]:]
        found.append((m.start(), m.end(), i, i, Ref("markdown", _unangle(m.group("src")), i + 1, m.group("alt"),
                                                    _title(m), _caption(body, i, rest))))
        consume(m.start(), m.end())
    for m in REFIMG.finditer(pic_masked):
        label = (m.group("label") or m.group("alt")).strip().lower()
        i = line_of(m.start())
        rest = body[i][:m.start() - starts[i]] + body[i][m.end() - starts[i]:]
        if label in defs:
            src, title, _di = defs[label]
            ref = Ref("reference", src, i + 1, m.group("alt"), title, _caption(body, i, rest))
        else:
            ref = Ref("reference", "", i + 1, m.group("alt"), "", _caption(body, i, rest))
        found.append((m.start(), m.end(), i, i, ref))
        consume(m.start(), m.end())
    for m in CSSURL.finditer("".join(masked)):
        src = m.group("q1") or m.group("q2") or m.group("u") or ""
        if not src.strip():
            continue
        i = line_of(m.start())
        found.append((m.start(), m.end(), i, i, Ref("css", src.strip(), i + 1, caption=body[i].strip())))
        consume(m.start(), m.end())
    found.sort(key=lambda t: t[0])
    # context: the whole surrounding <figure>, and a short window of lines (up to the next image line)
    figures = [(m.start(), m.end(), TAG.sub(" ", m.group(0))) for m in FIGURE.finditer(joined)]
    image_lines = set()
    for _a, _b, i, j, _r in found:
        image_lines.update(range(i, j + 1))

    def window(i, j):
        parts = []
        k = i - 1
        while k >= max(0, i - WINDOW_UP) and body[k].strip() and k not in image_lines:
            parts.insert(0, body[k].strip())
            k -= 1
        k = j + 1
        while k <= min(len(body) - 1, j + WINDOW_DOWN) and k not in image_lines and \
                not body[k].lstrip().startswith("#"):
            if body[k].strip():
                parts.append(body[k].strip())
            k += 1
        return parts

    for a, b, i, j, ref in found:
        parts = [f[2] for f in figures if f[0] <= a and b <= f[1]] + window(i, j)
        ref.context = re.sub(r"\s+", " ", " ".join(parts)).strip()
    unparsed = []
    if start:
        unparsed += [n + 1 for n in range(1, start - 1) if n + 1 not in fm_used and IMAGE_LIKE.search(lines[n])]
    rest_lines = "".join(masked).split("\n")
    unparsed += [n + 1 for n, l in enumerate(rest_lines) if n not in def_lines and IMAGE_LIKE.search(l)]
    return refs + [t[4] for t in found], unparsed
