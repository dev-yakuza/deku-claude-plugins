"""guildcore.records.markers — marker lookup, block documents, PR-body splice.

Byte compatibility (§6.1) is kept structurally: every parser here splits a body on "\\n" only and
keeps each line verbatim (a trailing "\\r" stays part of its line), so `render(parse(x)) == x`
for any input. Matching strips a trailing "\\r" so a CRLF body still parses.
"""

import re

OPEN = "<!-- guild:%s -->"
CLOSE = "<!-- /guild:%s -->"
_FIRST = re.compile(r"^<!-- guild:([A-Za-z0-9:_-]+) -->")


def open_tag(name):
    return OPEN % name


def close_tag(name):
    return CLOSE % name


def body_of(comment):
    """`.body // ""` — a null body is the empty string, never an error (C-F-19, A-F33)."""
    return (comment or {}).get("body") or ""


def clean(line):
    return line[:-1] if line.endswith("\r") else line


def containing(comments, name):
    """Comments whose body contains the opening marker (`contains("<!-- guild:<name> -->")`)."""
    tag = open_tag(name)
    return [c for c in comments if tag in body_of(c)]


def find(comments, name, pick="lowest"):
    """The canonical comment for a marker: `lowest` id (loopback, auditor, decisions — §2.7 C11)
    or `latest` created_at (followups — qa.md Step 2.6). None when absent."""
    hits = containing(comments, name)
    if not hits:
        return None
    if pick == "latest":
        return sorted(hits, key=lambda c: (c.get("created_at") or "", c.get("id") or 0))[-1]
    return sorted(hits, key=lambda c: c.get("id") or 0)[0]


def first_line_marker(body):
    """The marker name on line 1 (`needs-human`, `note`, …) or None."""
    m = _FIRST.match(clean((body or "").split("\n", 1)[0]))
    return m.group(1) if m else None


def is_guild_comment(body):
    """Section M's filter: any `<!-- guild:` anywhere makes it Guild's (`contains(...) | not`)."""
    return "<!-- guild:" in (body or "")


ZWSP = "\u200b"
_NEUTRAL_RE = re.compile(r"<!--(\s*/?)guild:")
# bare names status.md step 2 tests with `test("guild:<x>")` over all bodies
_BARE_RE = re.compile(r"guild:(?=(?:analyze|design|test|qa|children|integration):output"
                      r"|test-evidence:step-)")


def neutralize(text):
    """K0-B1: a value must never carry a live Guild marker. `<!-- guild:` / `<!-- /guild:` and
    the bare output names status presence reads get a zero-width space after `guild`, so no
    reader (engine or the prose's jq) can mistake a quoted marker for a record."""
    text = _NEUTRAL_RE.sub(lambda m: "<!--" + m.group(1) + "guild" + ZWSP + ":", text or "")
    return _BARE_RE.sub("guild" + ZWSP + ":", text)


_SHAPE_RE = re.compile(r"^(### [a-z-]+|[a-z_][a-z0-9_-]*:|- |role-axis)")


def _shape(line):
    m = _SHAPE_RE.match(line)
    return m.group(1) if m else None


def finish(text, structural=True):
    """The last step of every engine renderer over the text it fills in: redact (INV5), then
    neutralize (K0-B1). `structural` (default) asserts the result has the same lines with the
    same key/heading/item prefixes — redaction may blank a VALUE, never a record line (K0-B2).
    Only free multi-line prose (a pause's body) passes structural=False."""
    from guildcore.records.redact import redact
    out = neutralize(redact(text))
    if structural:
        a, b = text.split("\n"), out.split("\n")
        if len(a) != len(b) or [_shape(x) for x in a] != [_shape(y) for y in b]:
            raise ValueError("redaction changed the record's line structure")
    return out


def unescape(text):
    """Undo `neutralize` for comparisons of machine tokens (K0-m17)."""
    return (text or "").replace(ZWSP, "")


def has_marker_text(text):
    return bool(_NEUTRAL_RE.search(text or "") or _BARE_RE.search(text or ""))


def assert_own_markers(out, name=None):
    """Post-render check: the only Guild markers in `out` are `name`'s own open/close lines
    (none at all when name is None — a bare block), and no secret survived."""
    from guildcore.records.redact import has_secret
    own = {open_tag(name), close_tag(name)} if name else set()
    for m in re.finditer(r"<!--\s*/?guild:[^>]*-->", out):
        if m.group(0) not in own:
            raise ValueError("rendered record carries a foreign marker: %s" % m.group(0))
    if name is None and _BARE_RE.search(out):
        raise ValueError("rendered block carries a bare output marker name")
    if has_secret(out):
        raise ValueError("rendered record still carries a secret")
    return out


def _line_spans(body, line):
    """(start, end) offsets of every line equal to `line` (a trailing \r tolerated)."""
    out, pos = [], 0
    for ln in body.split("\n"):
        c = clean(ln)
        if c.rstrip() == line:                          # trailing blanks tolerated (K0-m14)
            out.append((pos, pos + len(c)))             # a CRLF line's \r stays outside
        elif c.lstrip().startswith(line):
            # a line that STARTS with the marker but carries more (e.g. open+close on one line):
            # neither a block nor a mere mention — never guess, never append a second block
            raise ValueError("marker line %r carries extra text" % line)
        pos += len(ln) + 1
    return out


def marker_span(body, name):
    """K0-M2: the marker block anchored on WHOLE LINES — a quoted inline occurrence is never a
    marker. Returns (start, end) of open-line start .. close-line end, or None. Two real blocks,
    or an open line without a close line, raise ValueError (never guess which to touch)."""
    opens = _line_spans(body, open_tag(name))
    if not opens:
        return None
    if len(opens) > 1:
        raise ValueError("marker %s appears on %d lines — refusing to choose" % (name, len(opens)))
    closes = [c for c in _line_spans(body, close_tag(name)) if c[0] > opens[0][0]]
    if not closes:
        raise ValueError("marker %s has no closing marker" % name)
    return opens[0][0], closes[0][1]


def inner(body, name):
    """Text strictly between the line-anchored opening and closing marker lines, or None."""
    sp = marker_span(body or "", name)
    if sp is None:
        return None
    blk = body[sp[0]:sp[1]]          # open line … close line (always two distinct lines)
    return blk[blk.index("\n") + 1:blk.rindex("\n") + 1]


def splice(body, name, block):
    """INV4: replace the `<name>` marker block of a PR body with `block` (which carries its own
    markers), remove it when `block` is None, or append it when absent. Markers count only as
    whole lines (K0-M2); every byte outside the block is preserved. Two blocks, or an opening
    line without its closing one, are NOT spliced — ValueError (a truncated read must never be
    written back, qa.md Step 2.5)."""
    body = body or ""
    sp = marker_span(body, name)
    if sp is None:
        if block is None:
            return body
        if not body or body.endswith("\n\n"):
            sep = ""
        elif body.endswith("\n"):
            sep = "\n"
        else:
            sep = "\n\n"
        return body + sep + block
    i, end = sp
    if block is None:
        # drop the pair and one following newline so no blank-line residue piles up
        if body[end:end + 1] == "\n":
            end += 1
        return body[:i] + body[end:]
    return body[:i] + block + body[end:]


class Block(object):
    """One `### <heading>` block: the heading line and every line up to the next block/tail."""

    def __init__(self, heading, lines):
        self.heading = heading
        self.lines = lines

    def get(self, key, default=None):
        """First `key: value` line at column 0 (value verbatim, `\\r` stripped)."""
        pre = key + ":"
        for ln in self.lines:
            ln = clean(ln)
            if ln.startswith(pre):
                v = ln[len(pre):]
                return v[1:] if v.startswith(" ") else v
        return default

    def has(self, key):
        pre = key + ":"
        return any(clean(ln).startswith(pre) for ln in self.lines)

    def fields(self):
        out = []
        for ln in self.lines:
            ln = clean(ln)
            m = re.match(r"^([a-z_][a-z0-9_-]*): ?(.*)$", ln)
            if m:
                out.append((m.group(1), m.group(2)))
        return out

    def render_lines(self):
        return [self.heading] + self.lines


class BlockDoc(object):
    """A cumulative record: head lines, `### …` blocks, tail lines (from `tail_re` on).

    loopback / auditor:execute end blocks at their closing marker; the decision log at
    `</details>`. `render()` reproduces the parsed body byte for byte."""

    def __init__(self, head, blocks, tail, heading_re, tail_re):
        self.head = head
        self.blocks = blocks
        self.tail = tail
        self.heading_re = heading_re
        self.tail_re = tail_re

    @classmethod
    def parse(cls, body, heading_re, tail_re):
        lines = (body or "").split("\n")
        head, blocks, tail = [], [], []
        cur = None
        for idx, ln in enumerate(lines):
            c = clean(ln)
            if tail_re.match(c):
                tail = lines[idx:]
                break
            if heading_re.match(c):
                cur = Block(ln, [])
                blocks.append(cur)
            elif cur is None:
                head.append(ln)
            else:
                cur.lines.append(ln)
        return cls(head, blocks, tail, heading_re, tail_re)

    def render(self):
        out = list(self.head)
        for b in self.blocks:
            out.extend(b.render_lines())
        out.extend(self.tail)
        return "\n".join(out)

    def insert(self, block_text):
        """Append a rendered block immediately before the tail (H§B write rule)."""
        new = BlockDoc.parse(block_text, self.heading_re, self.tail_re)
        if any(l.endswith("\r") for l in self.head + self.tail + [x for b in self.blocks for x in b.lines]):
            for nb in new.blocks:                    # match the body's CRLF line ends (K0-m3)
                nb.heading = nb.heading if nb.heading.endswith("\r") else nb.heading + "\r"
                nb.lines = [l if l.endswith("\r") else l + "\r" for l in nb.lines]
        self.blocks.extend(new.blocks)
        if new.head and any(clean(x) for x in new.head):
            raise ValueError("block text must start with its heading")
        return self
