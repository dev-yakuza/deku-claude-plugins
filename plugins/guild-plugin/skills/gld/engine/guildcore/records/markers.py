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


def inner(body, name):
    """Text strictly between the first opening marker and its closing marker, or None."""
    o, c = open_tag(name), close_tag(name)
    i = body.find(o)
    if i < 0:
        return None
    j = body.find(c, i + len(o))
    if j < 0:
        return None
    return body[i + len(o):j]


def splice(body, name, block):
    """INV4: replace the `<name>` marker block of a PR body with `block` (which carries its own
    markers), remove it when `block` is None, or append it when absent. Every byte outside the
    marker pair is preserved. An opening marker without its closing one is NOT spliced — the
    caller gets ValueError (a truncated read must never be written back, qa.md Step 2.5)."""
    body = body or ""
    o, c = open_tag(name), close_tag(name)
    i = body.find(o)
    if i < 0:
        if block is None:
            return body
        if not body or body.endswith("\n\n"):
            sep = ""
        elif body.endswith("\n"):
            sep = "\n"
        else:
            sep = "\n\n"
        return body + sep + block
    j = body.find(c, i + len(o))
    if j < 0:
        raise ValueError("marker %s has no closing marker" % name)
    end = j + len(c)
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
        self.blocks.extend(new.blocks)
        if new.head and any(clean(x) for x in new.head):
            raise ValueError("block text must start with its heading")
        return self
