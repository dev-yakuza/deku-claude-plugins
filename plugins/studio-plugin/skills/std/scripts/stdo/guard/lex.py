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
ASSIGN_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*|[0-9]+)(\[[^\]]*\])?(\+?=)")  # `0=…`, `1=…` too (review 6 M3)
PLAIN_RE = re.compile(r"[^\s;&|()<>'\"\\$`]+")
# zsh's numeric glob `<N-M>` (`<->`, `<5->`, `<-9>`): zsh's lexer reads it as part of a word wherever a `<` stands,
# word-internal, at word start, inside `[…]`, after `^` or an fd number (lex.c isnumglob; checked in zsh 5.9, review 8
# B1); any other `<` is a redirection
NUMGLOB_RE = re.compile(r"<[0-9]*-[0-9]*>")


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

    def read_word(self, assign=False, regex=False):
        """A WordNode at pos, or None when pos is at a metacharacter / end. `regex`: the operand after `=~` in
        `[[ ]]` — balanced `( … )` and `|` are part of the word (zsh reads it as a regular expression, review 6
        conf M-1); "pattern": the operand after `==`, `=` or `!=` — a glob group `( … )` with its `|`, blanks and
        `<…>` is part of the word (`[[ $x == (a|b) ]]`; a `|` outside a group is zsh's parse error; review 7 conf
        M-1)."""
        start = self.pos
        parts = []
        buf = self.buf
        lit = []
        depth = 0

        def flush():
            if lit:
                parts.append(("lit", "".join(lit), False))
                del lit[:]

        while self.pos < len(self.buf):
            self._tick()
            buf = self.buf  # an alias in a `$(…)` of this word is spliced into the buffer (review 6)
            c = buf[self.pos]
            if regex and (c == "(" or (c == ")" and depth > 0) or (c == "|" and (depth > 0 or regex is True)) or
                          (regex == "pattern" and depth > 0 and c in " \t<>")):
                depth += 1 if c == "(" else -1 if c == ")" else 0
                lit.append(c)
                self.pos += 1
                continue
            if c == "<" and NUMGLOB_RE.match(buf, self.pos):
                m = NUMGLOB_RE.match(buf, self.pos)
                lit.append(m.group(0))  # a numeric glob: part of the word (review 8 B1)
                self.pos = m.end()
                continue
            if c in META:
                if c in "<>" and self.at(1) == "(" and self.pos == start:
                    d = c
                    self.pos += 2
                    body = self.parse_list(stop_ops=(")",))
                    self.expect(")")
                    parts.append(("procsub", d, body, self.buf[start:self.pos]))
                    continue
                if c == "(" and self.pos > start:
                    sofar = buf[start:self.pos]
                    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*\+?=", sofar):
                        end = self._match_paren(self.pos)
                        flush()
                        # the substitutions in the elements run (`a=($(…))`, review 2 M8)
                        parts.append(("dyn", "array", buf[self.pos:end], False, self.subs_in(buf[self.pos:end])))
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
            if c == "~" and self.pos == start and buf[self.pos + 1:self.pos + 2] == "[":
                # review 14 (B14-6): `~[name]`, a dynamic named directory (zsh_directory_name): a tilde part whose
                # folder the guard cannot tell (walk: "tilde-dir"). review 15 (B15-1/2): only a plain name between the
                # brackets — zsh's lexer ends the word at `;`, `&`, `|`, `<`, … and runs `$(…)`, backquotes and
                # `${…}` inside it, so any other text is lexed as before (HEAD); `~[x](#q…)` too (a glob qualifier)
                m = re.match(r"~\[[A-Za-z0-9_.:+@%,=-]*\]", buf[self.pos:])
                nxt = buf[self.pos + len(m.group(0)):self.pos + len(m.group(0)) + 1] if m else None
                if m and (nxt in ("", "/") or (nxt in META and nxt != "(")):
                    parts.append(("tilde", m.group(0)[1:]))
                    self.pos += len(m.group(0))
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
        return WordNode(parts, self.buf[start:self.pos], start, self.pos)

    def skip_unit(self, i):
        """review 9 B2: index after the quoted or expansion unit starting at buf[i] — a backslash pair, '…', $'…' (with
        its backslash escapes), "…", `…`, ${…} (its flags' parentheses are not counted), $(…) — or None when buf[i]
        starts none. The one scanner the paren, brace and case-pattern matchers share with the lexer's rules."""
        buf, n = self.buf, len(self.buf)
        c = buf[i]
        if c == "\\":
            return i + 2
        if c == "'":
            j = buf.find("'", i + 1)
            if j < 0:
                raise ParseError("unterminated-quote", i)
            return j + 1
        if c == '"':
            return self._skip_dq(i + 1)
        if c == "`":
            j = i + 1
            while j < n and buf[j] != "`":
                j += 2 if buf[j] == "\\" else 1
            if j >= n:
                raise ParseError("unterminated-backtick", i)
            return j + 1
        if c == "$" and i + 1 < n:
            d = buf[i + 1]
            if d == "'":
                j = i + 2
                while j < n and buf[j] != "'":
                    j += 2 if buf[j] == "\\" else 1
                if j >= n:
                    raise ParseError("unterminated-quote", i)
                return j + 1
            if d == '"':
                return self._skip_dq(i + 2)
            if d == "{":
                return self._brace_end(i + 2)
            if d == "(":
                return self._match_paren(i + 1)
        return None

    def _match_paren(self, i):
        """Index after the `)` matching buf[i] == '(' (quotes respected)."""
        depth, buf, n = 0, self.buf, len(self.buf)
        while i < n:
            c = buf[i]
            if c in "\\'\"`$":
                j = self.skip_unit(i)
                if j is not None:
                    i = j
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
            if (c == "$" and buf[i + 1:i + 2] in ("(", "{")) or c == "`":
                i = self.skip_unit(i)  # "$(echo ")")": the substitution's own quotes (review 9 B2)
                continue
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
        n0 = len(parts)

        def flush():
            if lit:
                parts.append(("lit", "".join(lit), True))
                del lit[:]

        while True:
            buf = self.buf  # an alias in a `$(…)` is spliced into the buffer
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
        if end is not None and len(parts) == n0:
            parts.append(("lit", "", True))  # `""`: an empty quoted word stays a word (G1 §3)

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
            parts.append(("cmdsub", body, self.buf[p:self.pos], quoted))
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
        if nxt in ("=", "~", "^", "+") and (NAME_RE.match(buf, p + 2) or buf.startswith(("{", "=", "~", "^"), p + 2)
                                            or (buf[p + 2:p + 3] in SPECIAL_PARAMS and buf[p + 2:p + 3])):
            q = p + 1
            while q < len(buf) and buf[q] in "=~^+":
                q += 1
            if q < len(buf) and buf[q] == "{":
                q = self._brace_end(q + 1)
            else:
                mm = NAME_RE.match(buf, q)
                if mm:
                    q = mm.end()
                elif q < len(buf) and buf[q].isdigit():
                    q = re.match(r"[0-9]+", buf[q:]).end() + q  # `$~1`, `$=1` (review 9: s7#11)
                elif q < len(buf) and buf[q] in SPECIAL_PARAMS:
                    q += 1  # `$~@`, `$=*`
            parts.append(("dyn", "paramx", buf[p:q], quoted))
            self.pos = q
            return
        m = NAME_RE.match(buf, p + 1)
        if m:
            self.pos = m.end()
            if self.at() == ":" and self.at(1) and (self.at(1) in MODIFIERS or (self.at(1) == "g" and self.at(2) and
                                                                          self.at(2) in "sS&")):
                # zsh modifier ($X:h, $X:s/a/b/): the value is not the variable's
                q = self._modifier_end(self.pos, quoted)
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

    def _modifier_end(self, q, quoted=False):
        """End of an unbraced modifier chain at q (`:h:t`, `:s/a/b/`, `:gs/a/'b'/`). The text of an `s`
        substitution is read to its third delimiter with its quotes and backslashes (zsh reads them as part of the
        modifier: review 6 M4); an expansion in it ends the part (it is read, and runs, as its own part)."""
        buf, n = self.buf, len(self.buf)
        while q < n and buf[q] not in META and buf[q] not in "\\'$`\"":
            ms = re.match(r":g?[sS](.)", buf[q:q + 4]) if buf[q] == ":" else None
            if ms is None or ms.group(1) in META:
                q += 1
                continue
            d, q, seen = ms.group(1), q + ms.end(), 0
            while q < n and seen < 2 and buf[q] not in META:
                c = buf[q]
                if quoted and c == '"':
                    break
                if c == "\\":
                    q += 2
                elif c == "'" and not quoted:
                    j = buf.find("'", q + 1)
                    q = n if j < 0 else j + 1
                elif c == '"' and not quoted:
                    q = self._skip_dq(q + 1)
                elif c in "$`":
                    break  # an expansion in the text: read as its own part (it runs)
                else:
                    seen += c == d
                    q += 1
        return min(q, n)

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
            if c in "\\'\"`" or (c == "$" and buf[i + 1:i + 2] in ("'", "(")):
                i = self.skip_unit(i)
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
