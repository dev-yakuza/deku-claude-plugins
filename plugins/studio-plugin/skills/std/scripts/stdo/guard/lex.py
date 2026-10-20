"""Character-level reading of shell words (m0d1a-plan §5.1). zsh semantics are the baseline.

A word is read into parts:
  ("lit", text, quoted)         literal text; quoted=True for quoted or backslash-escaped text
  ("tilde", user)               unquoted ~ / ~user at word start (or after = / : in assignments)
  ("tildealt",)                 a `~` after `=` inside an ordinary argument: zsh keeps it, bash expands it
  ("rcq",)                      `''` inside single quotes when snapshots disagree on rcquotes
  ("param", name, quoted)       $NAME / ${NAME}
  ("dyn", kind, raw, quoted)    anything whose value is unknown (${…} forms, specials, arrays, subscripts)
  ("cmdsub", list, raw, quoted) $(…) or `…`
  ("arith", raw, subs, quoted)  $((…)) / $[…]; subs = command substitutions inside
  ("procsub", dir, list, raw)   <(…) / >(…)
  ("equals", name)              zsh `=name` (PATH lookup)
  ("eqtilde",)                  a word starting with `=~` (literal in one reading, dynamic in the other)
"""

import re

from . import limits

META = set(" \t\n;&|()<>")
NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
SPECIAL_PARAMS = set("@*#?$!-0123456789")
MODIFIERS = set("aAcehlpPqQrstuwxWX&")
ASSIGN_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)(\[[^\]]*\])?(\+?=)")
PLAIN_RE = re.compile(r"[^\s;&|()<>'\"\\$`]+")


class ParseError(Exception):
    def __init__(self, code, pos):
        Exception.__init__(self, "%s@%d" % (code, pos))
        self.code, self.pos = code, pos


class Unsupported(ParseError):
    pass


ANSI = {"a": "\a", "b": "\b", "e": "\x1b", "E": "\x1b", "f": "\f", "n": "\n", "r": "\r", "t": "\t",
        "v": "\v", "\\": "\\", "'": "'", '"': '"', "?": "?"}


def ansi_c(body):
    """Decode the body of $'…' as zsh does. Returns (text, sure): sure is False where the result
    depends on the locale or on version details (then the word is treated as dynamic)."""
    out, i, n = [], 0, len(body)
    sure = True
    while i < n:
        c = body[i]
        if c != "\\" or i + 1 >= n:
            out.append(c)
            i += 1
            continue
        d = body[i + 1]
        if d in ANSI:
            out.append(ANSI[d])
            i += 2
        elif d in "01234567":
            m = re.match(r"[0-7]{1,3}", body[i + 1:])
            out.append(chr(int(m.group(0), 8) & 0xFF))
            i += 1 + len(m.group(0))
        elif d == "x":
            m = re.match(r"[0-9A-Fa-f]{1,2}", body[i + 2:])
            if m:
                out.append(chr(int(m.group(0), 16)))
                i += 2 + len(m.group(0))
            else:
                sure = False
                i += 2
        elif d in "uU":
            m = re.match(r"[0-9A-Fa-f]{1,%d}" % (4 if d == "u" else 8), body[i + 2:])
            if m:
                cp = int(m.group(0), 16)
                if cp < 0x80:
                    out.append(chr(cp))
                else:
                    sure = False  # encoded per locale
                i += 2 + len(m.group(0))
            else:
                sure = False
                i += 2
        else:
            out.append(d)  # zsh: an unknown escape (also \c) drops the backslash
            i += 2
    return "".join(out), sure


class WordNode(object):
    def __init__(self, parts, raw, start, end):
        self.parts, self.raw, self.start, self.end = parts, raw, start, end

    @property
    def plain(self):
        return bool(self.parts) and all(p[0] == "lit" and not p[2] for p in self.parts) \
            and "\\" not in self.raw and PLAIN_RE.fullmatch(self.raw or "") is not None

    def __repr__(self):
        return "WordNode(%r)" % self.raw


class Lexer(object):
    """Word reading on `self.buf` at `self.pos`. The parser subclass provides parse_list()."""

    def _tick(self):
        self.ctx.budget.tick()
        self.ctx.tokens += 1
        if self.ctx.tokens > limits.MAX_TOKENS:
            raise limits.LimitExceeded("tokens")

    def at(self, k=0):
        i = self.pos + k
        return self.buf[i] if i < len(self.buf) else ""

    def startswith(self, s):
        return self.buf.startswith(s, self.pos)

    # ---- blanks and comments ----

    def skip_blanks(self):
        """Spaces, tabs, line continuations and comments (not newlines)."""
        while self.pos < len(self.buf):
            c = self.buf[self.pos]
            if c in " \t":
                self.pos += 1
            elif c == "\\" and self.at(1) == "\n":
                self.pos += 2
            elif c == "#":
                j = self.buf.find("\n", self.pos)
                self.pos = len(self.buf) if j < 0 else j
            else:
                break

    # ---- words ----

    def read_word(self, assign=False):
        """A WordNode at pos, or None when pos is at a metacharacter / end."""
        start = self.pos
        parts = []
        buf = self.buf
        lit = []

        def flush():
            if lit:
                parts.append(("lit", "".join(lit), False))
                del lit[:]

        while self.pos < len(buf):
            self._tick()
            c = buf[self.pos]
            if c in META:
                if c in "<>" and self.at(1) == "(" and self.pos == start:
                    d = c
                    self.pos += 2
                    body = self.parse_list(stop_ops=(")",))
                    self.expect(")")
                    parts.append(("procsub", d, body, buf[start:self.pos]))
                    continue
                if c == "(" and self.pos > start:
                    sofar = buf[start:self.pos]
                    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*\+?=", sofar):
                        end = self._match_paren(self.pos)
                        flush()
                        parts.append(("dyn", "array", buf[self.pos:end], False))
                        self.pos = end
                        continue
                    if re.match(r"\(\s*\)", buf[self.pos:]):
                        break  # name() function definition
                    raise Unsupported("unsupported:zsh-glob-group", self.pos)
                break
            if c == "\\":
                if self.at(1) == "\n":
                    self.pos += 2
                    continue
                if self.pos + 1 >= len(buf):
                    self.pos += 1  # zsh drops a lone trailing backslash
                    continue
                flush()
                parts.append(("lit", buf[self.pos + 1], True))
                self.pos += 2
                continue
            if c == "'":
                flush()
                self.read_single(parts)
                continue
            if c == '"':
                flush()
                self.pos += 1
                self.read_double(parts, '"')
                continue
            if c == "$":
                flush()
                self.read_dollar(parts, quoted=False)
                continue
            if c == "`":
                flush()
                parts.append(self.read_backtick(quoted=False))
                continue
            if c == "~" and self.pos == start:
                m = re.match(r"~([+-]\d*|[A-Za-z0-9_.-]*)", buf[self.pos:])
                user = m.group(1)
                nxt = buf[self.pos + len(m.group(0)):self.pos + len(m.group(0)) + 1]
                if nxt in ("", "/") or nxt in META:
                    parts.append(("tilde", user))
                    self.pos += len(m.group(0))
                    continue
            if c == "~" and lit and (lit[-1] == "=" or (assign and lit[-1] == ":")):
                flush()
                if assign:
                    m = re.match(r"~([+-]\d*|[A-Za-z0-9_.-]*)", buf[self.pos:])
                    parts.append(("tilde", m.group(1)))
                    self.pos += len(m.group(0))
                else:
                    parts.append(("tildealt",))
                    self.pos += 1
                continue
            if c == "=" and self.pos == start and not assign:
                if self.at(1) == "~":
                    parts.append(("eqtilde",))
                    self.pos += 2
                    continue
                if self.at(1) == "(":
                    raise Unsupported("unsupported:zsh-equals-procsub", self.pos)
                m = re.match(r"=([A-Za-z0-9_.+-]+)", buf[self.pos:])
                if m:
                    nxt = buf[self.pos + len(m.group(0)):self.pos + len(m.group(0)) + 1]
                    if nxt == "" or nxt in META:
                        parts.append(("equals", m.group(1)))
                        self.pos += len(m.group(0))
                        continue
            lit.append(c)
            self.pos += 1
        flush()
        if self.pos == start:
            return None
        return WordNode(parts, buf[start:self.pos], start, self.pos)

    def _match_paren(self, i):
        """Index after the `)` matching buf[i] == '(' (quotes respected)."""
        depth, buf, n = 0, self.buf, len(self.buf)
        while i < n:
            c = buf[i]
            if c == "\\":
                i += 2
                continue
            if c == "'":
                j = buf.find("'", i + 1)
                if j < 0:
                    raise ParseError("unterminated-quote", i)
                i = j + 1
                continue
            if c == '"':
                i = self._skip_dq(i + 1)
                continue
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    return i + 1
            i += 1
        raise ParseError("unterminated-paren", i)

    def _skip_dq(self, i):
        buf, n = self.buf, len(self.buf)
        while i < n:
            c = buf[i]
            if c == "\\":
                i += 2
                continue
            if c == '"':
                return i + 1
            i += 1
        raise ParseError("unterminated-quote", i)

    def read_single(self, parts):
        start = self.pos
        self.pos += 1
        chunks = []
        while True:
            j = self.buf.find("'", self.pos)
            if j < 0:
                raise ParseError("unterminated-quote", start)
            chunks.append(self.buf[self.pos:j])
            self.pos = j + 1
            rcq = self.ctx.options.get("rcquotes")
            if self.at() == "'" and rcq in (True, "both"):
                if rcq is True:
                    chunks.append("'")
                    self.pos += 1
                    continue
                parts.append(("lit", "".join(chunks), True))
                chunks = []
                parts.append(("rcq",))
                self.pos += 1
                continue
            break
        parts.append(("lit", "".join(chunks), True))

    def read_double(self, parts, end):
        """Read up to the closing `end` (or the end of text when end is None) in double-quote rules."""
        start = self.pos
        lit = []
        buf = self.buf

        def flush():
            if lit:
                parts.append(("lit", "".join(lit), True))
                del lit[:]

        while True:
            if self.pos >= len(buf):
                if end is None:
                    break
                raise ParseError("unterminated-quote", start - 1)
            self._tick()
            c = buf[self.pos]
            if end is not None and c == end:
                self.pos += 1
                break
            if c == "\\":
                d = self.at(1)
                if d == "\n":
                    self.pos += 2
                    continue
                if d in ("$", "`", "\\") or (end is not None and d == end):
                    lit.append(d)
                    self.pos += 2
                    continue
                lit.append("\\")
                self.pos += 1
                continue
            if c == "$":
                flush()
                self.read_dollar(parts, quoted=True)
                continue
            if c == "`":
                flush()
                parts.append(self.read_backtick(quoted=True))
                continue
            lit.append(c)
            self.pos += 1
        flush()

    def read_dollar(self, parts, quoted):
        buf, p = self.buf, self.pos
        nxt = self.at(1)
        if nxt == "'" and not quoted:
            j = p + 2
            while j < len(buf) and buf[j] != "'":
                j += 2 if buf[j] == "\\" else 1
            if j >= len(buf):
                raise ParseError("unterminated-quote", p)
            text, sure = ansi_c(buf[p + 2:j])
            parts.append(("lit", text, True) if sure else ("dyn", "ansi-c", buf[p:j + 1], True))
            self.pos = j + 1
            return
        if nxt == '"' and not quoted:
            self.pos += 2
            self.read_double(parts, '"')
            return
        if nxt == "(":
            if self.at(2) == "(":
                end = self._arith_end(p + 3)
                if end is not None:
                    raw = buf[p + 3:end - 2]
                    parts.append(("arith", raw, self.subs_in(raw), quoted))
                    self.pos = end
                    return
            self.pos = p + 2
            self.ctx.depth_enter(self.pos)
            body = self.parse_list(stop_ops=(")",))
            self.expect(")")
            self.ctx.depth_leave()
            parts.append(("cmdsub", body, buf[p:self.pos], quoted))
            return
        if nxt == "[":
            j = buf.find("]", p + 2)
            if j < 0:
                raise ParseError("unterminated-arith", p)
            raw = buf[p + 2:j]
            parts.append(("arith", raw, self.subs_in(raw), quoted))
            self.pos = j + 1
            return
        if nxt == "{":
            end = self._brace_end(p + 2)
            inner = buf[p + 2:end - 1]
            self.pos = end
            if NAME_RE.fullmatch(inner):
                parts.append(("param", inner, quoted))
            else:
                subs = self.subs_in(inner)
                parts.append(("dyn", "paramx", buf[p:end], quoted))
                for s in subs:
                    parts.append(("cmdsub", s, "", quoted))
            return
        if nxt in ("=", "~", "^", "+") and (NAME_RE.match(buf, p + 2) or buf.startswith(("{", "=", "~", "^"), p + 2)):
            q = p + 1
            while q < len(buf) and buf[q] in "=~^+":
                q += 1
            if q < len(buf) and buf[q] == "{":
                q = self._brace_end(q + 1)
            else:
                mm = NAME_RE.match(buf, q)
                q = mm.end() if mm else q
            parts.append(("dyn", "paramx", buf[p:q], quoted))
            self.pos = q
            return
        m = NAME_RE.match(buf, p + 1)
        if m:
            self.pos = m.end()
            if self.at() == ":" and self.at(1) and self.at(1) in MODIFIERS:
                # zsh modifier ($X:h, $X:s/a/b/): the value is not the variable's
                q = self.pos
                while q < len(buf) and buf[q] not in META and buf[q] not in "\\'$`\"":
                    q += 1
                parts.append(("dyn", "modifier", buf[p:q], quoted))
                self.pos = q
                return
            if self.at() == "[":  # zsh subscript
                j = buf.find("]", self.pos)
                if j < 0:
                    raise ParseError("unterminated-subscript", self.pos)
                parts.append(("dyn", "subscript", buf[p:j + 1], quoted))
                self.pos = j + 1
                return
            parts.append(("param", m.group(0), quoted))
            return
        if nxt and nxt in SPECIAL_PARAMS:
            parts.append(("dyn", "special", buf[p:p + 2], quoted))
            self.pos = p + 2
            return
        parts.append(("lit", "$", quoted))
        self.pos = p + 1

    def _arith_end(self, i):
        """Index after the matching `))` for an arithmetic expansion starting at i, or None."""
        depth, buf, n = 0, self.buf, len(self.buf)
        while i < n:
            c = buf[i]
            if c == "(":
                depth += 1
            elif c == ")":
                if depth == 0:
                    return i + 2 if i + 1 < n and buf[i + 1] == ")" else None
                depth -= 1
            elif c in "'\"`":
                return None
            i += 1
        return None

    def _brace_end(self, i):
        depth, buf, n = 1, self.buf, len(self.buf)
        while i < n:
            c = buf[i]
            if c == "\\":
                i += 2
                continue
            if c == "'":
                j = buf.find("'", i + 1)
                if j < 0:
                    raise ParseError("unterminated-quote", i)
                i = j + 1
                continue
            if c == '"':
                i = self._skip_dq(i + 1)
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return i + 1
            i += 1
        raise ParseError("unterminated-brace", i)

    def read_backtick(self, quoted):
        start = self.pos
        i = start + 1
        out = []
        buf = self.buf
        while i < len(buf):
            c = buf[i]
            if c == "\\" and i + 1 < len(buf) and buf[i + 1] in "\\`$":
                out.append(buf[i + 1])
                i += 2
                continue
            if c == "`":
                break
            out.append(c)
            i += 1
        else:
            raise ParseError("unterminated-backtick", start)
        self.pos = i + 1
        body = self.sub_parser("".join(out), start + 1).parse_program()
        return ("cmdsub", body, buf[start:self.pos], quoted)

    def subs_in(self, text):
        """Command substitutions inside arithmetic or ${…} text (parsed, nothing else)."""
        if "$(" not in text and "`" not in text:
            return []
        return self.sub_parser(text, self.pos).extract_subs()
