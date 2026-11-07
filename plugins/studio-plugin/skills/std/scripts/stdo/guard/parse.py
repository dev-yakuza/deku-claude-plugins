"""Recursive-descent parser (m0d1a-plan §5.2) with zsh alias expansion (§5.4).

Aliases are expanded while parsing, as zsh does: the alias value is spliced into the buffer at the
word's place and read again (operators in the value split statements). An ambiguous alias asks the
context's oracle which alternative this parse takes; the scan runs one parse per alternative.
"""

import re

from . import limits
from .lex import ASSIGN_RE, NUMGLOB_RE, PLAIN_RE, Lexer, ParseError, Unsupported, WordNode

RESERVED = {"if", "then", "elif", "else", "fi", "for", "in", "do", "done", "while", "until", "case", "esac",
            "select", "function", "{", "}", "!", "[[", "]]", "time", "coproc", "repeat", "foreach", "end"}
OPS = ["&&", "||", ";;&", ";;", ";&", ";|", "|&", "&>>", "&>", "&|", "&!", ";", "&", "|", "\n", "(", ")"]
# zsh's redirection operators, longest first: `|` / `!` after `>` clobber, `&` sends stderr too (`>&|`, `>>&!`, `&>>|`;
# checked in zsh 5.9, review 8 M1)
REDIR_OPS = ["<<<", "<<-", "<<", "<>", "<&", ">>&|", ">>&!", ">>&", ">>|", ">>!", ">>", ">&|", ">&!", ">|", ">!", ">&",
             "&>>|", "&>>!", "&>>", "&>|", "&>!", "&>", "<", ">"]
CASE_ENDS = (";;", ";&", ";|", ";;&")
TYPESET = {"export", "typeset", "declare", "local", "readonly", "integer", "float"}  # zsh: arguments are assignments
CLOSERS = {"then", "elif", "else", "fi", "do", "done", "esac", "}"}


# ---- AST ----

class Node(object):
    alt = None


class ListNode(Node):
    def __init__(self, items):
        self.items = items  # [(AndOr, sep)]


class AndOr(Node):
    def __init__(self, first, rest):
        self.first, self.rest = first, rest  # rest: [(op, Pipeline)]


class Pipeline(Node):
    def __init__(self, cmds, neg=False, timed=False):
        self.cmds, self.neg, self.timed = cmds, neg, timed


class Redirect(Node):
    def __init__(self, fd, op, target, start):
        self.fd, self.op, self.target, self.start = fd, op, target, start
        self.heredoc = None  # dict(delim, quoted, strip, body, parts, unterminated)


class Simple(Node):
    def __init__(self, assigns, words, redirs, start, end):
        self.assigns, self.words, self.redirs, self.start, self.end = assigns, words, redirs, start, end
        self.aliases = []


class Compound(Node):
    def __init__(self, kind, start, **kw):
        self.kind, self.start = kind, start
        self.redirs = []
        self.__dict__.update(kw)


class AliasOverflow(Node):
    def __init__(self, name, values, words, start):
        self.name, self.values, self.words, self.start = name, values, words, start
        self.redirs = []


# ---- parser ----

class Parser(Lexer):
    def __init__(self, text, ctx, base=0):
        self.buf = text
        self.pos = 0
        self.ctx = ctx
        self.base = base
        self.pending = []      # heredocs waiting for the next newline
        self.regions = []      # [start, end, alias name] spliced alias text
        self.edits = []        # (pos, removed, inserted)
        self.alias_next = None
        self.group_depth = 0

    def sub_parser(self, text, base):
        return Parser(text, self.ctx, self.base + base)

    def orig(self, pos):
        """Buffer position → position in the original text (spliced alias text maps to the alias word)."""
        for at, removed, inserted in reversed(self.edits):
            if pos >= at + inserted:
                pos = pos - inserted + removed
            elif pos > at:
                pos = at
        return self.base + pos

    # ---- entry points ----

    def parse_program(self):
        body = self.parse_list()
        self.skip_blanks()
        if self.pos < len(self.buf):
            raise ParseError("syntax:unexpected-%r" % self.buf[self.pos], self.orig(self.pos))
        if self.pending:
            for h in self.pending:
                h.heredoc.update(body="", parts=[], unterminated=True)
            self.ctx.note("heredoc-unterminated")
            self.pending = []
        return body

    def extract_subs(self):
        """Parse every $(…) and `…` in free text (arithmetic, ${…} bodies)."""
        out = []
        while self.pos < len(self.buf):
            c = self.buf[self.pos]
            if c == "\\":
                self.pos += 2
            elif c == "'":
                j = self.buf.find("'", self.pos + 1)
                self.pos = len(self.buf) if j < 0 else j + 1
            elif c == "$" and self.at(1) == "(" and (self.at(2) != "(" or self._arith_end(self.pos + 3) is None):
                # review 10 P1: a `$((` with no matching `))` is `$( (`, a command substitution of a subshell, as zsh
                # reads it (and as the lexer does outside ${…})
                self.pos += 2
                out.append(self.parse_list(stop_ops=(")",)))
                self.expect(")")
            elif c == "`":
                out.append(self.read_backtick(False)[1])
            else:
                self.pos += 1
        return out

    def heredoc_parts(self):
        parts = []
        self.read_double(parts, None)
        return parts

    # ---- tokens ----

    def peek_op(self):
        for op in OPS:
            if self.buf.startswith(op, self.pos):
                return op
        return None

    def expect(self, op):
        self.skip_blanks()
        while self.at() == "\n" and op != "\n":
            self.newline()
            self.skip_blanks()
        if not self.startswith(op):
            raise ParseError("syntax:expected-%s" % op.strip() if op.strip() else "syntax:expected-newline",
                             self.orig(self.pos))
        self.pos += len(op)

    def newline(self):
        self.pos += 1
        pend, self.pending = self.pending, []
        for r in pend:
            self.read_heredoc_body(r)

    def skip_newlines(self, semi=True):
        """Newlines, and a lone `;` where a command is expected: zsh reads it as an empty command (`a &; b`,
        `do; b`, `a &&; b`, `; a`; checked in zsh 5.9, review 7)."""
        while True:
            self.skip_blanks()
            if self.at() == "\n":
                self.newline()
            elif semi and self.at() == ";" and self.at(1) not in (";", "&", "|"):
                self.pos += 1
            else:
                return

    def peek_plain(self):
        r = self.peek_plain_ex()
        return r[0] if r else None

    def peek_plain_ex(self):
        """(word, end): a plain word at pos, line continuations removed (zsh joins them first)."""
        buf, i, out = self.buf, self.pos, []
        while True:
            m = PLAIN_RE.match(buf, i)
            if m:
                out.append(m.group(0))
                i = m.end()
            if buf.startswith("\\\n", i):
                i += 2
                continue
            break
        if not out:
            return None
        if i < len(buf) and buf[i] not in " \t\n;&|()<>":
            return None
        return "".join(out), i

    def eat_plain(self, word):
        self.skip_blanks()
        if self.peek_plain() == word:
            self.pos += len(word)
            return True
        return False

    # ---- heredocs ----

    def read_heredoc_body(self, r):
        h = r.heredoc
        delim, strip = h["delim"], h["strip"]
        lines = []
        buf = self.buf
        found = False
        while self.pos < len(buf):
            j = buf.find("\n", self.pos)
            line = buf[self.pos:] if j < 0 else buf[self.pos:j]
            self.pos = len(buf) if j < 0 else j + 1
            cmp = line.lstrip("\t") if strip else line
            if cmp == delim:
                found = True
                break
            lines.append(cmp)
        body = "\n".join(lines) + ("\n" if lines else "")
        if not found:
            self.ctx.note("heredoc-unterminated")
        h["body"] = body
        h["unterminated"] = not found
        if h["quoted"]:
            h["parts"] = [("lit", body, True)]
        else:
            h["parts"] = self.sub_parser(body, self.pos - len(body)).heredoc_parts()

    # ---- grammar ----

    def parse_list(self, stop_ops=(), stop_words=()):
        items = []
        while True:
            self.skip_newlines()
            if self.pos >= len(self.buf):
                break
            op = self.peek_op()
            if op is not None and op in stop_ops:
                break
            if op in (")",) + CASE_ENDS:
                if op in stop_ops:
                    break
                raise ParseError("syntax:unexpected-%s" % op, self.orig(self.pos))
            w = self.peek_plain()
            if w is not None and w in stop_words:
                break
            if w == "}" and self.group_depth > 0:
                break
            ao = self.parse_and_or()
            self.skip_blanks()
            op = self.peek_op()
            sep = None
            if op in (";", "&", "&|", "&!"):
                self.pos += len(op)
                sep = "&" if op != ";" else ";"
            elif op == "\n":
                self.newline()
                sep = "\n"
            items.append((ao, sep))
            if sep is None:
                self.skip_blanks()
                op = self.peek_op()
                w = self.peek_plain()
                if self.pos < len(self.buf) and not (op in stop_ops or op in (")",) + CASE_ENDS
                                                     or (w in stop_words) or (w == "}" and self.group_depth)):
                    raise ParseError("syntax:unexpected-token", self.orig(self.pos))
                break
        return ListNode(items)

    def parse_and_or(self):
        first = self.parse_pipeline()
        rest = []
        while True:
            self.skip_blanks()
            op = self.peek_op()
            if op not in ("&&", "||"):
                break
            self.pos += 2
            self.skip_newlines()
            rest.append((op, self.parse_pipeline()))
        return AndOr(first, rest)

    def parse_pipeline(self):
        self.skip_blanks()
        neg = timed = False
        while True:
            w = self.peek_plain()
            if w == "!":
                neg = not neg
                self.pos += 1
                self.skip_blanks()
            elif w == "time":
                timed = True
                self.pos += 4
                self.skip_blanks()
                if self.peek_plain() == "-p":
                    self.pos += 2
                    self.skip_blanks()
            else:
                break
        if (timed or neg) and self.empty_here():
            # `time;`, `time | cat`, `! ;`, `time && …`: zsh runs an empty pipeline (status 0; negated 1; review 8 M1)
            cmds = [Compound("group", self.orig(self.pos), body=ListNode([]))]
        else:
            cmds = [self.parse_command()]
        while True:
            self.skip_blanks()
            op = self.peek_op()
            if op not in ("|", "|&"):
                break
            self.pos += len(op)
            self.skip_newlines()
            cmds.append(self.parse_command())
        return Pipeline(cmds, neg, timed)

    def empty_here(self):
        """No command follows (an operator, a newline, `)` or the end): `time`, `!` and `coproc` alone."""
        self.skip_blanks()
        c = self.at()
        return c == "" or c in "\n;|)" or (c == "&" and self.at(1) != ">")

    def parse_command(self):
        self.ctx.depth_enter(self.orig(self.pos))
        try:
            return self._parse_command()
        finally:
            self.ctx.depth_leave()

    def _parse_command(self):
        self.skip_blanks()
        start = self.pos
        if self.startswith("(("):
            end = self._arith_end(self.pos + 2)
            if end is not None:
                raw = self.buf[self.pos + 2:end - 2]
                self.pos = end
                node = Compound("arith", self.orig(start), raw=raw, subs=self.subs_in(raw))
                return self.compound_redirs(node)
        if re.match(r"\(\s*\)", self.buf[self.pos:]):
            raise Unsupported("unsupported:zsh-anon-function", self.orig(self.pos))
        if self.startswith("("):
            self.pos += 1
            body = self.parse_list(stop_ops=(")",))
            self.expect(")")
            return self.compound_redirs(Compound("subshell", self.orig(start), body=body))
        return self.parse_simple_or_compound()

    def compound_redirs(self, node):
        while True:
            self.skip_blanks()
            r = self.try_redirect()
            if r is None:
                break
            node.redirs.append(r)
        return node

    def parse_simple_or_compound(self):
        start = self.pos
        assigns, words, redirs = [], [], []
        cmdpos = True
        recheck = False
        alias_chain = None
        while True:
            self.skip_blanks()
            if self.pos >= len(self.buf):
                break
            r = self.try_redirect()
            if r is not None:
                redirs.append(r)
                continue
            c = self.at()
            if c in "\n;&|)" or (c == "(" and not (self.startswith("<(") or self.startswith(">("))):
                if c == "(" and words and len(words) == 1 and not assigns and re.match(r"\(\s*\)", self.buf[self.pos:]):
                    return self.parse_funcdef(words[0].raw, start, after_parens=False)
                break
            nxt = self.alias_next
            check_alias = cmdpos or recheck or (nxt is not None and self.pos >= nxt[1])
            recheck = False
            if nxt is not None and self.pos >= nxt[1]:
                self.alias_next = None
            if check_alias:
                pe = self.peek_plain_ex()
                w = pe[0] if pe else None
                if w is not None and not words:
                    if (assigns or redirs) and w in CLOSERS:
                        break  # `{ X=v }`, `then X=v fi`: zsh reads a reserved word after assignments (review 5 R1)
                    if not assigns and not redirs and w in RESERVED and w not in ("}", "]]", "in", "end"):
                        if w in CLOSERS:
                            break
                        return self.parse_reserved(w, start)
                if w is not None:
                    res = self.try_alias(w, alias_chain, pe[1])
                    if res is not None:
                        if isinstance(res, AliasOverflow):
                            res.words = self.read_rest_words()
                            return res
                        alias_chain = res
                        recheck = True  # the first word of the spliced value is checked again
                        continue
            if cmdpos and not words:
                m = ASSIGN_RE.match(self.buf, self.pos)
                if m:
                    ws = self.pos
                    self.pos = m.end()
                    if self.at() == "(":
                        from .lex import WordNode
                        a0 = self.pos
                        end = self._match_paren(self.pos)
                        raw = self.buf[a0:end]
                        self.pos = end
                        subs = self.sub_parser(raw, a0).extract_subs() if ("$(" in raw or "`" in raw) else []
                        value = WordNode([("dyn", "array", raw, False, subs)], raw, a0, end)
                    elif self.at() not in " \t\n;&|)":
                        value = self.read_word(assign=True)
                    else:
                        value = None
                    assigns.append((m.group(1), m.group(2) or "", m.group(3), value, ws))
                    continue
            if self.group_depth > 0 and words and self.peek_plain() == "}":
                break
            typeset_arg = bool(words) and words[0].plain and words[0].raw in TYPESET and \
                ASSIGN_RE.match(self.buf, self.pos) is not None
            w = self.read_word(assign=typeset_arg)
            if w is None:
                raise ParseError("syntax:unexpected-%r" % self.at(), self.orig(self.pos))
            words.append(w)
            cmdpos = cmdpos and w.plain and w.raw == "nocorrect"
        node = Simple(assigns, words, redirs, self.orig(start), self.orig(self.pos))
        node.alt = alias_chain
        if not assigns and not words and not redirs:
            raise ParseError("syntax:empty-command", self.orig(self.pos))
        return node

    def read_rest_words(self):
        out = []
        while True:
            self.skip_blanks()
            if self.pos >= len(self.buf) or self.at() in "\n;&|)":
                return out
            r = self.try_redirect()
            if r is not None:
                continue
            w = self.read_word()
            if w is None:
                return out
            out.append(w)

    # ---- aliases ----

    def try_alias(self, name, chain, end=None):
        """Expand `name` (a plain word at pos) if it is an alias. Returns the alias chain info, an
        AliasOverflow, or None (not expanded)."""
        ctx = self.ctx
        values = ctx.alias_values(name)
        if not values:
            return None
        for s, e, n in self.regions:
            if n == name and s <= self.pos < e:
                return None  # zsh does not expand an alias inside its own text
        if chain is not None and len(chain["names"]) >= limits.MAX_ALIAS_DEPTH:
            ctx.note("alias-depth")
            return None
        if len(values) == 1:
            choice, value = 0, values[0]
            source = ctx.alias_source(name, value) if ctx.alias_ambiguous(name) else None
        else:
            choice = ctx.choose(name, values, self.orig(self.pos))
            if choice < 0:
                return AliasOverflow(name, values, [], self.orig(self.pos))
            value = values[choice]
            source = ctx.alias_source(name, value)
        if chain is None:
            chain = {"group": self.orig(self.pos), "path": [], "names": [], "source": []}
        chain["names"].append(name)
        if source is not None:
            chain["path"].append(str(choice))
            chain["source"].append(source)
        if value is None:  # the "not an alias" alternative
            if not chain["path"]:
                return None
            return self._keep_word(chain, name)
        start = self.pos
        end = end if end is not None else self.pos + len(name)
        removed = end - start
        self.buf = self.buf[:start] + value + self.buf[end:]
        delta = len(value) - removed
        for r in self.regions:
            if r[0] > start:
                r[0] += delta
            if r[1] > start:
                r[1] += delta
        region = [start, start + len(value), name]
        self.regions.append(region)
        self.edits.append((start, removed, len(value)))
        # zsh: a value ending in a blank makes the next word (after the value) an alias candidate too;
        # a nested alias without a trailing blank keeps an outer pending one
        if value.endswith((" ", "\t")):
            self.alias_next = region
        return chain

    def _keep_word(self, chain, name):
        """The word stays as it is (no expansion); mark it so it is not offered again."""
        self.regions.append([self.pos, self.pos + len(name), name])
        return chain

    # ---- redirections ----

    def try_redirect(self):
        buf, p = self.buf, self.pos
        fd = None
        m = re.match(r"(\d+)(?=[<>])", buf[p:p + 12])
        if m:
            fd = m.group(1)
            q = p + len(fd)
        else:
            m = re.match(r"\{([A-Za-z_][A-Za-z0-9_]*)\}(?=[<>])", buf[p:p + 70])
            if m:
                fd = "{%s}" % m.group(1)
                q = p + len(m.group(0))
            else:
                q = p
        if buf.startswith("<(", q) or buf.startswith(">(", q) or NUMGLOB_RE.match(buf, q):
            return None  # `2<->`, `{a}<->`, `<->`: a word with a numeric glob (review 8 B1)
        op = None
        for o in REDIR_OPS:
            if buf.startswith(o, q):
                op = o
                break
        if op is None:
            return None
        self.pos = q + len(op)
        self.skip_blanks()
        r = Redirect(fd, op, None, self.orig(p))
        if op in ("<<", "<<-"):
            dw = self.read_word()
            if dw is None:
                raise ParseError("syntax:heredoc-delimiter", self.orig(self.pos))
            quoted = any(part[0] == "lit" and part[2] for part in dw.parts) or any(
                part[0] != "lit" for part in dw.parts)
            delim = "".join(part[1] for part in dw.parts if part[0] == "lit") if quoted else dw.raw
            r.target = dw
            r.heredoc = {"delim": delim, "quoted": quoted, "strip": op == "<<-", "body": None, "parts": None,
                         "unterminated": False}
            self.pending.append(r)
            return r
        if op in (">&", "<&") and re.match(r"(\d+|-)(?=$|[\s;&|()<>])", buf[self.pos:self.pos + 12]):
            m2 = re.match(r"(\d+|-)", buf[self.pos:])
            r.target = None
            r.dup = m2.group(1)
            self.pos += len(m2.group(1))
            return r
        w = self.read_word()
        if w is None:
            raise ParseError("syntax:redirect-target", self.orig(self.pos))
        r.target = w
        return r

    # ---- compound commands ----

    def parse_reserved(self, w, start):
        self.pos += len(w)
        ostart = self.orig(start)
        if w == "{":
            self.group_depth += 1
            body = self.parse_list(stop_words=("}",))
            self.group_depth -= 1
            self.skip_newlines()
            if not self.eat_plain("}"):
                raise ParseError("syntax:expected-}", self.orig(self.pos))
            self.skip_blanks()
            if self.peek_plain() == "always":
                # `{ try } always { always }`: both lists run, the second whatever the first did (review 5 R1)
                self.pos += len("always")
                self.skip_blanks()
                if self.peek_plain() != "{":
                    raise ParseError("syntax:expected-{", self.orig(self.pos))
                self.pos += 1
                self.group_depth += 1
                more = self.parse_list(stop_words=("}",))
                self.group_depth -= 1
                self.skip_newlines()
                if not self.eat_plain("}"):
                    raise ParseError("syntax:expected-}", self.orig(self.pos))
                body = ListNode(body.items + more.items)
            return self.compound_redirs(Compound("group", ostart, body=body))
        if w == "if":
            clauses = []
            cond = self.short_form(w, lambda: self.parse_list(stop_words=("then",)), "then")
            body = self.parse_list(stop_words=("elif", "else", "fi"))
            clauses.append((cond, body))
            else_body = None
            while True:
                self.skip_newlines()
                if self.eat_plain("elif"):
                    cond = self.short_form(w, lambda: self.parse_list(stop_words=("then",)), "then")
                    body = self.parse_list(stop_words=("elif", "else", "fi"))
                    clauses.append((cond, body))
                    continue
                if self.eat_plain("else"):
                    else_body = self.parse_list(stop_words=("fi",))
                    self.short_form(w, lambda: None, "fi")
                    break
                self.short_form(w, lambda: None, "fi")
                break
            return self.compound_redirs(Compound("if", ostart, clauses=clauses, else_body=else_body))
        if w in ("while", "until"):
            cond = self.short_form(w, lambda: self.parse_list(stop_words=("do",)), "do")
            body = self.parse_list(stop_words=("done",))
            self.need("done")
            return self.compound_redirs(Compound("while", ostart, until=(w == "until"), cond=cond, body=body))
        if w in ("for", "select"):
            self.skip_blanks()
            if self.startswith("(("):
                end = self._arith_end(self.pos + 2)
                if end is None:
                    raise ParseError("syntax:for-arith", self.orig(self.pos))
                raw = self.buf[self.pos + 2:end - 2]
                self.pos = end
                var, items = None, None
                names = []
                subs = self.subs_in(raw)
            else:
                var = self.read_word()
                if var is None or not var.plain:
                    raise ParseError("syntax:for-variable", self.orig(self.pos))
                var = var.raw
                names = [var]
                subs = []
                items = None
                # `for i j in x y; do …; done`: several names take the items in turn (review 7 R3)
                while True:
                    self.skip_blanks()
                    save = self.pos
                    more = self.read_word() if self.at() not in ("(", ";", "\n", "") else None
                    if more is None or not more.plain or more.raw in ("in", "do") or \
                            not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", more.raw):
                        self.pos = save
                        break
                    names.append(more.raw)
                self.skip_blanks()
                if self.at() == "(":
                    raise Unsupported("unsupported:zsh-for-short", self.orig(self.pos))
                self.skip_newlines()
                if self.eat_plain("in"):
                    items = []
                    while True:
                        self.skip_blanks()
                        if self.at() in ("\n", ";", "") :
                            break
                        wd = self.read_word()
                        if wd is None:
                            break
                        items.append(wd)
            self.skip_blanks()
            if self.at() == ";":
                self.pos += 1
            self.skip_newlines()
            if self.peek_plain() == "{":
                raise Unsupported("unsupported:zsh-for-brace", self.orig(self.pos))
            self.short_form(w, lambda: None, "do")  # `for i in x; cmd`, `for ((…)) cmd` (review 6 M10)
            body = self.parse_list(stop_words=("done",))
            self.need("done")
            node = Compound("for", ostart, var=var, items=items, body=body, subs=subs)
            node.vars = names if var is not None else []
            return self.compound_redirs(node)
        if w == "case":
            self.skip_blanks()
            word = self.read_word()
            if word is None:
                raise ParseError("syntax:case-word", self.orig(self.pos))
            self.skip_newlines()
            self.short_form(w, lambda: None, "in")  # `case x { … }` (review 6 M10)
            arms, ends = [], []
            while True:
                self.skip_newlines()
                if self.eat_plain("esac"):
                    break
                pats = self.case_patterns()
                body = self.parse_list(stop_ops=CASE_ENDS, stop_words=("esac",))
                arms.append((pats, body))
                self.skip_blanks()
                op = self.peek_op()
                if op in CASE_ENDS:
                    self.pos += len(op)
                ends.append(op if op in CASE_ENDS else ";;")
            node = Compound("case", ostart, word=word, arms=arms)
            node.ends = ends  # `;&` / `;|`: the next arm's body may run after this one (review 8 M1)
            return self.compound_redirs(node)
        if w == "function":
            self.skip_blanks()
            if self.at() in ("{", "(") and (self.at() == "(" or self.peek_plain() == "{"):
                raise Unsupported("unsupported:zsh-anon-function", ostart)
            name = self.read_word()
            if name is None:
                raise ParseError("syntax:function-name", self.orig(self.pos))
            # `function a b { … }` defines every name with the same body (review 5 M4)
            names = [name.raw]
            while True:
                self.skip_blanks()
                if self.at() in ("{", "(", "\n", ";", "") or self.peek_plain() == "{" or self.peek_op():
                    break
                more = self.read_word()
                if more is None:
                    break
                names.append(more.raw)
            fd = self.parse_funcdef(name.raw, start, after_parens=False)
            fd.names = names
            return fd
        if w == "[[":
            words = []
            while True:
                self.skip_newlines(semi=False)  # a `;` in `[[ ]]` is zsh's parse error
                if self.peek_plain() == "]]":
                    self.pos += 2
                    break
                if self.pos >= len(self.buf):
                    raise ParseError("syntax:expected-]]", self.orig(self.pos))
                op = None
                last = words[-1].raw if words and isinstance(words[-1], WordNode) else None
                # review 7 conf M-1: the pattern after `==` / `=` / `!=` is one word, glob groups included
                regex = True if last == "=~" else "pattern" if last in ("==", "=", "!=") else False
                for o in ("&&", "||", "<", ">", "(", ")", "!"):
                    if self.startswith(o) and not (regex and o in "()") and \
                            not (o == "<" and NUMGLOB_RE.match(self.buf, self.pos)):
                        op = o
                        break
                if op:
                    self.pos += len(op)
                    words.append(op)
                    continue
                wd = self.read_word(regex=regex)  # `=~ ^v([0-9]+)$`: a regular expression (review 6 conf M-1)
                if wd is None:
                    raise ParseError("syntax:dbracket", self.orig(self.pos))
                words.append(wd)
            return self.compound_redirs(Compound("dbracket", ostart, words=words))
        if w == "coproc":
            inner = Compound("group", ostart, body=ListNode([])) if self.empty_here() else self.parse_command()
            return Compound("coproc", ostart, cmd=inner)
        if w in ("repeat", "foreach"):
            raise Unsupported("unsupported:zsh-%s" % w, ostart)
        raise ParseError("syntax:unexpected-%s" % w, ostart)

    def case_patterns(self):
        """The patterns of one case arm, read as zsh 5.9 reads them (review 8 conf m-1/m-2): patterns, not file names,
        so glob groups are part of them (`*.(ts|tsx))`, `(#i)abc)`, `(a|b))`, `(x|y)|z)`). A leading `(` is the
        optional opener when its group is followed by a blank, `;`, a newline or the end (`(x) cmd`, `( x )`,
        `((a|b)) cmd`); joined to more pattern text, a `)` or a `|` it is a group of the pattern. The list ends at the
        first unbalanced `)`. Each alternative is a word (its expansions run)."""
        self.skip_blanks()
        buf, p = self.buf, self.pos
        opener = False
        if self.at() == "(":
            e = self._match_paren(p)
            j = e
            while j < len(buf) and buf[j] in " \t":
                j += 1
            nxt = buf[j:j + 1]
            opener = nxt in ("", "\n", ";", "&") or (j > e and nxt not in (")", "|"))
        if opener:
            s, end = p + 1, e - 1
        else:
            s, end = p, self._case_pattern_end(p)
        text = buf[s:end]
        self.pos = end + 1
        sub = self.sub_parser(text, s)
        pats = []
        while True:
            sub.skip_blanks()
            while sub.at() == "\n":
                sub.pos += 1
                sub.skip_blanks()
            if sub.pos >= len(sub.buf):
                break
            if sub.at() == "|" and pats:
                sub.pos += 1
                continue
            pw = sub.read_word(regex="pattern")
            if pw is None:
                raise ParseError("syntax:case-pattern", self.orig(s + sub.pos))
            pats.append(pw)
        if not pats:
            raise ParseError("syntax:case-pattern", self.orig(p))
        return pats

    def _case_pattern_end(self, i):
        """Index of the `)` that ends a case pattern list starting at i (groups balanced, quotes respected)."""
        depth, buf, n = 0, self.buf, len(self.buf)
        while i < n:
            c = buf[i]
            if c in "\\'\"`$":
                try:
                    j = self.skip_unit(i)  # review 9 B2: $'…', ${(s:(:)X}, $(…) as whole units
                except ParseError as e:
                    raise ParseError(e.code if hasattr(e, "code") else "unterminated-quote", self.orig(i))
                if j is not None:
                    i = j
                    continue
            if c == "(":
                depth += 1
            elif c == ")":
                if depth == 0:
                    return i
                depth -= 1
            elif depth == 0 and c in ";&\n":
                raise ParseError("syntax:case-pattern", self.orig(i))
            i += 1
        raise ParseError("syntax:case-pattern", self.orig(i))

    def short_form(self, w, head, word):
        """Read a compound command's head and its reserved word (`then`, `do`, `in`, `fi`). When they are not
        there, zsh may read a short form (SHORT_LOOPS, `{ … }` bodies: `for i in x; cmd`, `while (( 1 )) { … }`,
        `if [[ … ]] { … }`, `case x { … }`) the guard does not read: unsupported, so a Studio repository refuses it
        (G1 §1.8 M6, review 6 M10)."""
        try:
            out = head()
            self.need(word)
        except Unsupported:
            raise
        except ParseError as e:
            raise Unsupported("unsupported:zsh-short-%s" % w, e.pos)
        return out

    def need(self, word):
        self.skip_newlines()
        if not self.eat_plain(word):
            raise ParseError("syntax:expected-%s" % word, self.orig(self.pos))

    def parse_funcdef(self, name, start, after_parens):
        self.skip_blanks()
        if self.at() == "(":
            m = re.match(r"\(\s*\)", self.buf[self.pos:])
            if not m:
                raise ParseError("syntax:function-parens", self.orig(self.pos))
            self.pos += len(m.group(0))
        self.skip_newlines()
        body = self.parse_command()
        if not isinstance(body, Compound):
            if isinstance(body, Simple):
                pass  # zsh allows a simple command body: name() cmd
        return Compound("funcdef", self.orig(start), name=name, names=[name], body=body)
