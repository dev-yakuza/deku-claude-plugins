"""Files a patch writes (m0f-plan implementation review MAJOR-1): `git apply`, `git am` and `patch` change files the
command line does not name. The guard reads the patch (a file argument or a `<` file, at most 64 KB) and judges every
target as a write (or a delete). Pure text parsing — no child processes."""

import re

MAX = 64 * 1024

_P = r'("(?:[^"\\]|\\.)*"|\S+)'  # a git C-quoted path or a plain one
DIFF_GIT = re.compile(r"^diff --git %s %s\s*$" % (_P, _P))
OLD = re.compile(r"^--- (\S.*)$")
NEW = re.compile(r"^\+\+\+ (\S.*)$")
CTX_OLD = re.compile(r"^\*\*\* (\S.*)$")  # context diff: *** old … then --- new
_QUOTED = re.compile(r'"(?:[^"\\]|\\.)*"')
HUNK = re.compile(r"^\*\*\* \d+(,\d+)? \*\*\*\*")  # a context diff's hunk range, not a file
RENAME_COPY = re.compile(r"^(rename from|rename to|copy from|copy to) (.+)$")
DELETED = re.compile(r"^deleted file mode ")
_ESC = {"t": b"\t", "n": b"\n", '"': b'"', "\\": b"\\", "a": b"\a", "b": b"\b", "f": b"\f", "r": b"\r",
        "v": b"\v"}


def _unquote(p):
    """git's C-style quoting (\\t \\n \\" \\\\ and octal bytes) back to the UTF-8 path."""
    p = p.strip()
    if len(p) < 2 or p[0] != '"' or p[-1] != '"':
        return p
    body, out, i = p[1:-1], bytearray(), 0
    while i < len(body):
        c = body[i]
        if c == "\\" and i + 1 < len(body):
            n = body[i + 1]
            if n in "01234567" and i + 3 < len(body) + 1 and all(x in "01234567" for x in body[i + 1:i + 4]):
                out += bytes([int(body[i + 1:i + 4], 8) & 0xFF])
                i += 4
                continue
            out += _ESC.get(n, n.encode("utf-8"))
            i += 2
            continue
        out += c.encode("utf-8")
        i += 1
    return out.decode("utf-8", "replace")


def _header(rest):
    """Paths a `---`/`+++`/`***` header may name (M0f review 3 MINOR-1). Quoted: git's form. Unquoted: GNU diff writes
    spaces as is and a tab before the timestamp, so the path runs to the tab; with no tab both the first word and the
    whole rest are judged (the closed side)."""
    m = _QUOTED.match(rest)
    if m:
        return [_unquote(m.group(0))]
    if "\t" in rest:
        return [rest.split("\t", 1)[0]]
    whole = rest.strip()
    first = whole.split()[0] if whole else ""
    return [p for i, p in enumerate((first, whole)) if p and p not in (first, whole)[:i]]


def _pair(old, new, out, deleting):
    olds, news = _header(old), _header(new)
    gone = "/dev/null" in news or deleting
    for a in olds:
        if a != "/dev/null":
            out.append((a, "delete" if gone else "write", True))
    for b in news:
        if b != "/dev/null":
            out.append((b, "write", True))


def targets(text):
    """[(path as written, op, stripped)] — `stripped` False for git's rename/copy lines (already repository paths)."""
    out = []
    lines = (text or "").splitlines()
    pending_delete = False
    for i, line in enumerate(lines):
        m = DIFF_GIT.match(line)
        if m:
            out.append((_unquote(m.group(1)), "write", True))
            out.append((_unquote(m.group(2)), "write", True))
            pending_delete = False
            continue
        if DELETED.match(line):
            pending_delete = True
            continue
        m = RENAME_COPY.match(line)
        if m:
            op = "delete" if m.group(1) == "rename from" else "write"
            out.append((_unquote(m.group(2).strip()), op, False))
            continue
        m = CTX_OLD.match(line)
        if m and i + 1 < len(lines) and OLD.match(lines[i + 1]) and not HUNK.match(line):
            _pair(m.group(1), OLD.match(lines[i + 1]).group(1), out, False)
            continue
        m = OLD.match(line)
        if m and i + 1 < len(lines) and NEW.match(lines[i + 1]):
            _pair(m.group(1), NEW.match(lines[i + 1]).group(1), out, pending_delete)
            pending_delete = False
    return out


def strip(path, n):
    """`path` without its first n components (patch -pN); None when it has fewer."""
    if n is None:
        return path
    parts = [x for x in path.split("/") if x != ""]
    if n >= len(parts) and n > 0:
        return None
    return "/".join(parts[n:]) if n else path


def candidates(path, levels):
    out = []
    for n in levels:
        s = strip(path, n)
        if s and s not in out and not s.startswith("/"):
            out.append(s)
        elif s and s.startswith("/") and s not in out:
            out.append(s)
    return out
