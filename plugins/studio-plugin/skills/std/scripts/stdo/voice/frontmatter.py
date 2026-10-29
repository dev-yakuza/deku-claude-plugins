"""The parts of a script's frontmatter Studio reads itself (m1-plan §8): `cast` (role → {voice, style}) and
`pronounce` (written form → reading). Only the shapes s2v's own scripts use: a top-level key whose value is a nested
block of `name: value` lines, where a value is a scalar or an inline object `{ a: "x", b: y }`."""

import re

TOP = re.compile(r"^([A-Za-z_][\w-]*):\s*(.*?)\s*$")
CHILD = re.compile(r"^(\s+)([^\s:][^:]*?):\s*(.*?)\s*$")


def head(text):
    """The frontmatter's lines (without the --- lines)."""
    lines = (text or "").replace("\r\n", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        return []
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return lines[1:i]
    return []


def scalar(v):
    v = (v or "").strip()
    if len(v) >= 2 and v[0] in "\"'" and v[-1] == v[0]:
        return v[1:-1]
    return v


def inline(v):
    """`{ a: "x, y", b: z }` → {"a": "x, y", "b": "z"} (None when it is not an inline object)."""
    v = (v or "").strip()
    if not (v.startswith("{") and v.endswith("}")):
        return None
    parts, cur, quote = [], "", None
    for ch in v[1:-1]:
        if quote:
            cur += ch
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
        if ch == ",":
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    out = {}
    for p in parts:
        if ":" in p:
            k, _, val = p.partition(":")
            out[scalar(k)] = scalar(val)
    return out


def block(text, key):
    """The nested block under a top-level `key` as {child: scalar or object}, {} when the key has no children, None
    when the key is absent."""
    lines = head(text)
    for i, line in enumerate(lines):
        m = TOP.match(line)
        if not m or m.group(1) != key:
            continue
        if m.group(2):
            obj = inline(m.group(2))
            return obj if obj is not None else {}
        out, cur, indent = {}, None, None
        for nxt in lines[i + 1:]:
            if not nxt.strip():
                continue
            c = CHILD.match(nxt)
            if not c:
                break
            if indent is None:
                indent = len(c.group(1))
            if len(c.group(1)) == indent:
                cur = scalar(c.group(2))
                val = c.group(3)
                out[cur] = (inline(val) if inline(val) is not None else scalar(val)) if val else {}
            elif cur is not None and isinstance(out[cur], dict):
                out[cur][scalar(c.group(2))] = scalar(c.group(3))
        return out
    return None
