"""Walk the AST (m0d1a-plan §6): cwd sets, environment, wrappers, lock.py children, function and
alias effects, opaque forms. Emits Cmd and Opaque records; makes no allow/deny decision.

cwd outcomes are pairs (success, failure) of cwd sets: a tuple of absolute paths, () when that
path does not continue (exit, a cd that cannot fail), or None when unknown.
"""

import os
import re

from .. import lockargs
from . import limits, recog, where
from .lex import WordNode
from .model import Cmd, EnvOp, EnvView, LockWrap, Opaque, Redir, ScriptCall, Word, Wrapper
from .parse import AliasOverflow, Compound, Simple

DYN = object()
PUA = 0xF0000
PLUGIN_LOCK = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "lock.py"))
GLOB_CH = set("*?[")


def union(a, b):
    if a is None or b is None:
        return None
    out = list(a)
    for x in b:
        if x not in out:
            out.append(x)
    if len(out) > limits.MAX_CWDS:
        return None
    return tuple(out)


def cwd_list(c):
    return list(c) if c else []


def single(c):
    return c[0] if c and len(c) == 1 else None


class BraceOverflow(Exception):
    pass


def brace_expand(s, cap=limits.MAX_BRACE):
    """zsh brace expansion on a template where quoted/dynamic text is already replaced."""
    out = []
    if s.count("{") > 64:
        raise BraceOverflow()

    def rec(t):
        i = 0
        while True:
            i = t.find("{", i)
            if i < 0:
                out.append(t)
                if len(out) > cap:
                    raise BraceOverflow()
                return
            depth, j = 0, i
            while j < len(t):
                if t[j] == "{":
                    depth += 1
                elif t[j] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            if j >= len(t):
                out.append(t)
                return
            inner = t[i + 1:j]
            parts, d, cur = [], 0, []
            for ch in inner:
                if ch == "{":
                    d += 1
                elif ch == "}":
                    d -= 1
                if ch == "," and d == 0:
                    parts.append("".join(cur))
                    cur = []
                else:
                    cur.append(ch)
            parts.append("".join(cur))
            if len(parts) > 1:
                for p in parts:
                    rec(t[:i] + p + t[j + 1:])
                return
            m = re.fullmatch(r"(-?\d+)\.\.(-?\d+)(?:\.\.(-?\d+))?", inner)
            if m:
                a, b = int(m.group(1)), int(m.group(2))
                step = abs(int(m.group(3) or 1)) or 1
                if abs(b - a) // step + 1 > cap:
                    raise BraceOverflow()
                rng = range(a, b + 1, step) if a <= b else range(a, b - 1, -step)
                width = max(len(m.group(1)), len(m.group(2))) if (m.group(1).lstrip("-").startswith("0") or
                                                                 m.group(2).lstrip("-").startswith("0")) else 0
                for n in rng:
                    rec(t[:i] + (str(n).zfill(width) if width else str(n)) + t[j + 1:])
                return
            if re.fullmatch(r".\.\..", inner):
                raise BraceOverflow()  # character ranges: treated as unknown
            i = i + 1

    rec(s)
    return out


class State(object):
    def __init__(self, ctx):
        env = ctx.env
        self.vars = {}
        self.env_ops = []
        self.oldpwd = env.get("OLDPWD")
        self.dirstack = []
        self.paths = ctx.path_values()
        self.path_modified = False
        self.cdpath = bool(env.get("CDPATH"))
        self.env_unknown = False
        self.funcs = {}
        self.aliases_defined = set()
        self.shadowed = set()
        self.allexport = False
        self.after_exec = False
        self.written = {}
        self.fpath_changed = False
        self.opts = {}               # options changed inside the command (setopt/unsetopt/set -o)
        self.argv_opts_changed = False  # an option that changes words (shwordsplit, globsubst, …) changed
        self.brace_opts_changed = False

    def copy(self):
        s = State.__new__(State)
        s.__dict__.update(self.__dict__)
        for k in ("vars", "funcs", "written", "opts"):
            setattr(s, k, dict(getattr(self, k)))
        for k in ("env_ops", "dirstack", "paths"):
            v = getattr(self, k)
            setattr(s, k, list(v) if v is not None else None)
        for k in ("aliases_defined", "shadowed"):
            setattr(s, k, set(getattr(self, k)))
        return s


class Walker(object):
    def __init__(self, ctx, scan):
        self.ctx = ctx
        self.scan = scan
        self.cmds = []
        self.opaque = []
        self.dry = 0
        self.labels = []
        self.last_top = None
        self.where = ctx.where

    # ---- emission ----

    def new_id(self):
        self.ctx.next_id = getattr(self.ctx, "next_id", 0) + 1
        return self.ctx.next_id

    def emit(self, cmd):
        if self.dry:
            return
        if len(self.cmds) >= limits.MAX_COMMANDS:
            raise limits.LimitExceeded("commands")
        self.cmds.append(cmd)

    def emit_opaque(self, op, cmd=None):
        if self.dry:
            return
        if cmd is not None:
            op.cmd = cmd.id
            op.alt = cmd.alt
        self.opaque.append(op)

    def note(self, text):
        if not self.dry:
            self.ctx.note(text)

    def push(self, label):
        self.labels.append(label)

    def pop(self):
        self.labels.pop()

    # ---- variables ----

    def lookup(self, name, state, cwds):
        if name in state.vars:
            v = state.vars[name]
            return None if v is DYN else v
        if name == "PWD":
            return single(cwds)
        if name == "OLDPWD":
            return state.oldpwd
        if name in ("PATH",):
            return state.paths[0] if state.paths and len(state.paths) == 1 else None
        if state.env_unknown:
            return None
        return self.ctx.env.get(name)

    # ---- words ----

    def expand(self, wn, state, cwds, assign=False):
        """WordNode -> [Word] (brace expansion may give several)."""
        if wn is None:
            return [Word.lit("")]
        segs = []  # (kind 'u'|'q'|'d', text, alt, dynkind)
        opts = self.ctx.options
        for part in wn.parts:
            t = part[0]
            if t == "lit":
                segs.append(("q" if part[2] else "u", part[1], None, None))
            elif t == "tilde":
                user = part[1]
                home = self.lookup("HOME", state, cwds)
                if user in ("+", "-"):
                    v = single(cwds) if user == "+" else state.oldpwd
                    if v is not None:
                        segs.append(("q", v, None, None))
                    else:
                        segs.append(("d", "~" + user, None, "tilde" + user))
                elif re.match(r"^[+-]\d+$", user):
                    segs.append(("d", "~" + user, None, "tilde-stack"))
                elif user == "" and home is not None:
                    segs.append(("q", home, None, None))
                elif user and user == self.ctx.env.get("USER") and home is not None:
                    segs.append(("q", home, None, None))
                else:
                    segs.append(("d", "~" + user, None, "tilde-user" if user else "tilde"))
            elif t == "tildealt":
                home = self.lookup("HOME", state, cwds)
                segs.append(("u", "~", home if home is not None else "\0", None))
            elif t == "rcq":
                segs.append(("q", "", "'", None))
            elif t == "eqtilde":
                segs.append(("u", "=~", "\0", None))
            elif t == "param":
                v = self.lookup(part[1], state, cwds)
                if not part[2] and state.argv_opts_changed:
                    segs.append(("d", "$" + part[1], None, "param-options"))
                elif v is None:
                    segs.append(("d", "$" + part[1], None, "param:" + part[1]))
                elif not part[2] and opts.get("shwordsplit") in (True, "both") and re.search(r"\s", v):
                    segs.append(("d", "$" + part[1], None, "param:" + part[1]))
                else:
                    segs.append(("q", v, None, None))
            elif t == "dyn":
                segs.append(("d", part[2], None, part[1]))
            elif t == "cmdsub":
                val = self.walk_subst(part[1], state, cwds, "cmdsubst")
                if val is not None:
                    segs.append(("q", val, None, None))
                else:
                    segs.append(("d", part[2], None, "cmdsubst"))
            elif t == "arith":
                for sub in part[2]:
                    self.walk_subst(sub, state, cwds, "cmdsubst")
                self.arith_check(part[1], state, cwds)
                segs.append(("d", "$((%s))" % part[1], None, "arith"))
            elif t == "procsub":
                self.walk_subst(part[2], state, cwds, "procsubst")
                segs.append(("d", part[3], None, "procsub"))
            elif t == "equals":
                p = self.which(part[1], state)
                if p:
                    segs.append(("q", p, None, None))
                else:
                    segs.append(("d", "=" + part[1], None, "equals"))
        return self.build_words(wn, segs, brace_unknown=state.brace_opts_changed)

    def build_words(self, wn, segs, brace_unknown=False):
        template = []
        for i, s in enumerate(segs):
            template.append(s[1] if s[0] == "u" else chr(PUA + i))
        tpl = "".join(template)
        if brace_unknown and "{" in tpl:
            return [Word(wn.raw, None, dynamic=True, dyn=["brace-options"], skeleton="\0", quoted=True)]
        try:
            tpls = brace_expand(tpl) if "{" in tpl else [tpl]
        except BraceOverflow:
            return [Word(wn.raw, None, dynamic=True, dyn=["brace-overflow"], skeleton="\0", quoted=True)]
        words = []
        for t in tpls:
            value, skel, alt = [], [], []
            dyn, dynamic, glob, quoted, has_alt = [], False, False, False, False
            first_glob = None
            for ch in t:
                o = ord(ch)
                if PUA <= o < PUA + len(segs):
                    k, text, a, dk = segs[o - PUA]
                    if k == "d":
                        dynamic = True
                        dyn.append(dk)
                        skel.append("\0")
                        alt.append("\0")
                    else:
                        quoted = True
                        value.append(text)
                        skel.append(text)
                        alt.append(a if a is not None else text)
                        has_alt = has_alt or a is not None
                else:
                    seg_alt = None
                    for k, text, a, dk in segs:
                        pass
                    value.append(ch)
                    skel.append(ch)
                    alt.append(ch)
                    if ch in GLOB_CH and first_glob is None:
                        glob = True
                        first_glob = len("".join(skel)) - 1
            # unquoted segments with an alternative reading (tildealt, eqtilde)
            for k, text, a, dk in segs:
                if k == "u" and a is not None:
                    has_alt = True
            v = None if dynamic else "".join(value)
            sk = "".join(skel)
            altv = None
            if has_alt:
                altv = self._alt_value(t, segs)
            gb = None
            if glob:
                pre = sk[:first_glob]
                gb = pre[:pre.rfind("/") + 1] if "/" in pre else ""
            words.append(Word(wn.raw, v, dynamic=dynamic, dyn=dyn, skeleton=sk, glob=glob, glob_base=gb,
                              quoted=quoted, alt=altv, plain=wn.plain))
        return words

    def _alt_value(self, t, segs):
        """The value under the other reading (bash tilde after '=', rcquotes on, '=~' dynamic)."""
        out = []
        i = 0
        # rebuild from segments in order: unquoted text in t is literal; alternatives apply per segment
        ulits = [(k, text, a) for k, text, a, dk in segs]
        for ch in t:
            o = ord(ch)
            if PUA <= o < PUA + len(segs):
                k, text, a, dk = segs[o - PUA]
                if k == "d":
                    return "\0"
                out.append(a if a is not None else text)
            else:
                out.append(ch)
        s = "".join(out)
        for k, text, a in ulits:
            if k == "u" and a is not None:
                if a == "\0":
                    return "\0"
                s = s.replace(text, a, 1)
        return s

    def which(self, name, state):
        if state.paths is None:
            return None
        for pv in state.paths:
            p = where.which(name, pv, self.ctx.fs)
            if p:
                return p
        return None

    # ---- substitutions ----

    def walk_subst(self, lst, state, cwds, label):
        """Walk a $(…)/`…`/<(…) body (its own subshell); returns a known value for idioms."""
        self.push(label)
        try:
            self.walk_list(lst, cwds, state.copy())
        finally:
            self.pop()
        return self.idiom(lst, state, cwds) if label == "cmdsubst" else None

    def idiom(self, lst, state, cwds):
        if len(lst.items) != 1:
            return None
        ao = lst.items[0][0]
        if ao.rest or len(ao.first.cmds) != 1 or not isinstance(ao.first.cmds[0], Simple):
            return None
        node = ao.first.cmds[0]
        if node.assigns or node.redirs:
            return None
        raws = [w.raw for w in node.words]
        cwd = single(cwds)
        if raws in (["pwd"], ["pwd", "-P"], ["pwd", "-L"]):
            if cwd and raws[-1] == "-P":
                return self.ctx.fs.realpath(cwd)
            return cwd
        if len(raws) >= 3 and raws[0] == "git" and raws[-2:] == ["rev-parse", "--show-toplevel"]:
            mid = raws[1:-2]
            base = cwd
            if mid:
                if len(mid) != 2 or mid[0] != "-C" or base is None:
                    return None
                base = os.path.normpath(os.path.join(base, mid[1]))
            if base is None:
                return None
            r = self.where.git_repo(base) if self.ctx.fs.exists(base) else None
            return r.worktree if r else None
        return None

    def arith_check(self, raw, state, cwds, cmd=None):
        for name in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", raw or ""):
            v = state.vars.get(name)
            if isinstance(v, str) and ("$(" in v or "`" in v):
                op = Opaque("arith-eval", payload=v, cwds=cwd_list(cwds))
                self.emit_opaque(op, cmd)

    # ---- lists ----

    def walk_list(self, lst, cwds, state):
        cur = cwds
        last = (cwds, ())
        for ao, sep in lst.items:
            if sep == "&":
                self.push("background")
                try:
                    self.walk_and_or(ao, cur, state.copy())
                finally:
                    self.pop()
                last = (cur, ())
                continue
            last = self.walk_and_or(ao, cur, state)
            nxt = union(last[0], last[1])
            if nxt != ():
                cur = nxt
        return last

    def walk_and_or(self, ao, cwds, state):
        S, F = self.walk_pipeline(ao.first, cwds, state)
        for op, pl in ao.rest:
            self.push("cond")
            try:
                if op == "&&":
                    if S == ():
                        self.dry += 1
                        try:
                            self.walk_pipeline(pl, cwds, state.copy())
                        finally:
                            self.dry -= 1
                        continue
                    S2, F2 = self.walk_pipeline(pl, S, state)
                    S, F = S2, union(F, F2)
                else:
                    if F == ():
                        self.dry += 1
                        try:
                            self.walk_pipeline(pl, cwds, state.copy())
                        finally:
                            self.dry -= 1
                        continue
                    S2, F2 = self.walk_pipeline(pl, F, state)
                    S, F = union(S, S2), F2
            finally:
                self.pop()
        return S, F

    def walk_pipeline(self, pl, cwds, state):
        n = len(pl.cmds)
        if n == 1:
            out = self.walk_command(pl.cmds[0], cwds, state, None)
        else:
            stdin = None
            out = (cwds, cwds)
            for i, c in enumerate(pl.cmds):
                lastel = i == n - 1
                st = state if lastel else state.copy()
                self.push("pipeline")
                self.last_top = None
                try:
                    o = self.walk_command(c, cwds, st, stdin)
                finally:
                    self.pop()
                stdin = self.stdin_desc(self.last_top)
                if lastel:
                    out = o
        if pl.neg:
            out = (out[1], out[0])
        return out

    def stdin_desc(self, cmd):
        if cmd is None or not cmd.words:
            return ("unknown", None)
        argv = cmd.argv
        p = cmd.prog
        if p in ("echo", "print") and all(a is not None for a in argv[1:]):
            return ("literal", " ".join(a for a in argv[1:] if not a.startswith("-") or a == "-") + "\n")
        if p == "printf" and len(argv) >= 2 and all(a is not None for a in argv[1:]):
            return ("literal", " ".join(argv[1:]))
        if p == "cat" and len(argv) == 1:
            for r in cmd.redirs:
                if r.mode in ("heredoc", "herestring") and r.fd in (None, "0"):
                    return ("literal", r.body)
        if p == "cat" and len(argv) == 2 and argv[1] is not None and cmd.cwds:
            return ("file", self.where.absolute(argv[1], cmd.cwds[0]))
        return ("unknown", None)

    # ---- commands ----

    def walk_command(self, node, cwds, state, stdin):
        self.ctx.budget.tick()
        if isinstance(node, Simple):
            return self.walk_simple(node, cwds, state, stdin)
        if isinstance(node, AliasOverflow):
            words = []
            for wn in node.words:
                words.extend(self.expand(wn, state, cwds))
            cmd = Cmd(self.new_id(), [Word.lit(node.name)] + words, cwd_list(cwds), ctx=self.labels,
                      span=(node.start, node.start))
            cmd.flags.add("ambiguous-alias")
            self.emit(cmd)
            payload = "%s: %s %s" % (node.name, " | ".join(v if v is not None else "(not an alias)" for v in node.values),
                                     " ".join(w.skeleton for w in words))
            self.emit_opaque(Opaque("ambiguous-alias", payload=payload, cwds=cwd_list(cwds)), cmd)
            return (None, None)
        k = node.kind
        out = (cwds, cwds)
        if k == "subshell":
            self.push("subshell")
            try:
                self.walk_list(node.body, cwds, state.copy())
            finally:
                self.pop()
        elif k == "group":
            self.push("group")
            try:
                out = self.walk_list(node.body, cwds, state)
            finally:
                self.pop()
        elif k == "if":
            results = []
            cur = cwds
            for cond, body in node.clauses:
                self.push("cond")
                try:
                    S, F = self.walk_list(cond, cur, state)
                    results.append(self.walk_list(body, S if S != () else cur, state))
                finally:
                    self.pop()
                cur = F if F != () else cur
            if node.else_body is not None:
                self.push("cond")
                try:
                    results.append(self.walk_list(node.else_body, cur, state))
                finally:
                    self.pop()
            else:
                results.append((cur, ()))
            S = F = ()
            for s, f in results:
                S, F = union(S, s), union(F, f)
            out = (S, F)
        elif k in ("for", "while"):
            if k == "for":
                if node.items is not None:
                    for wn in node.items:
                        self.expand(wn, state, cwds)
                for sub in node.subs:
                    self.walk_subst(sub, state, cwds, "cmdsubst")
                if node.var:
                    state.vars[node.var] = DYN
            changes = self.changes_cwd(node, cwds, state)
            run = None if changes else cwds
            self.push("loop")
            try:
                if k == "while":
                    self.walk_list(node.cond, run, state)
                self.walk_list(node.body, run, state)
            finally:
                self.pop()
            out = (None, None) if changes else (cwds, cwds)
        elif k == "case":
            self.expand(node.word, state, cwds)
            S, F = cwds, ()
            self.push("cond")
            try:
                for pats, body in node.arms:
                    for p in pats:
                        self.expand(p, state, cwds)
                    s, f = self.walk_list(body, cwds, state)
                    S, F = union(S, s), union(F, f)
            finally:
                self.pop()
            out = (S, F)
        elif k == "funcdef":
            state.funcs[node.name] = self.function_effects(node.body, cwds, state)
            self.ctx.inline_functions.add(node.name)
            self.push("function-body")
            try:
                self.walk_command(node.body, cwds, state.copy(), None)
            finally:
                self.pop()
            out = (cwds, ())
        elif k == "dbracket":
            prev = None
            for w in node.words:
                if isinstance(w, WordNode):
                    words = self.expand(w, state, cwds)
                    if prev in ("-eq", "-ne", "-lt", "-le", "-gt", "-ge"):
                        self.arith_check(w.raw, state, cwds)
                    prev = w.raw
                else:
                    prev = w
            # the operand before an arithmetic comparison
            raws = [w.raw if isinstance(w, WordNode) else w for w in node.words]
            for i, r in enumerate(raws):
                if r in ("-eq", "-ne", "-lt", "-le", "-gt", "-ge") and i > 0:
                    self.arith_check(raws[i - 1], state, cwds)
        elif k == "arith":
            for sub in node.subs:
                self.walk_subst(sub, state, cwds, "cmdsubst")
            self.arith_check(node.raw, state, cwds)
        elif k == "coproc":
            self.push("background")
            try:
                self.walk_command(node.cmd, cwds, state.copy(), None)
            finally:
                self.pop()
            self.emit_opaque(Opaque("coproc", payload=None, cwds=cwd_list(cwds)))
            out = (cwds, cwds)
        if getattr(node, "redirs", None):
            redirs = [self.make_redir(r, state, cwds) for r in node.redirs]
            cmd = Cmd(self.new_id(), [], cwd_list(cwds), ctx=self.labels + ["compound-redirect"],
                      span=(node.start, node.start))
            cmd.redirs = redirs
            self.emit(cmd)
        return out

    def changes_cwd(self, node, cwds, state):
        """Whether one pass of a loop body may change the cwd (dry run)."""
        self.dry += 1
        try:
            st = state.copy()
            res = None
            if node.kind == "while":
                self.walk_list(node.cond, cwds, st)
            res = self.walk_list(node.body, cwds, st)
        finally:
            self.dry -= 1
        after = union(res[0], res[1])
        return after is None or set(after) - set(cwds or ()) != set()

    def function_effects(self, body, cwds, state):
        """What calling a function defined in this command may change: {"cwd": bool, "options": bool}.
        Options set without `emulate -L` / localoptions leak to the caller (zsh)."""
        self.dry += 1
        st = state.copy()
        try:
            res = self.walk_command(body, cwds, st, None)
        finally:
            self.dry -= 1
        after = union(res[0], res[1])
        cwd = after is None or (cwds is not None and set(after) - set(cwds) != set())
        local = bool(st.opts.get("localoptions"))
        opts = not local and (st.opts != state.opts or st.argv_opts_changed != state.argv_opts_changed
                              or st.brace_opts_changed != state.brace_opts_changed)
        return {"cwd": cwd, "options": opts}

    # ---- simple commands ----

    def walk_simple(self, node, cwds, state, stdin):
        alt = None
        if node.alt and node.alt.get("path"):
            alt = {"group": node.alt["group"], "index": ".".join(node.alt["path"]), "source": node.alt["source"]}
        aliases = list(node.alt["names"]) if node.alt else []
        assigns = []
        for name, sub, op, valnode, ws in node.assigns:
            vw = self.expand(valnode, state, cwds, assign=True) if valnode is not None else [Word.lit("")]
            val = vw[0] if len(vw) == 1 else Word(valnode.raw, None, dynamic=True, dyn=["array"], skeleton="\0")
            if sub:
                self.arith_check(sub, state, cwds)
            assigns.append((name, sub, op, val, valnode))
        words = []
        for wn in node.words:
            words.extend(self.expand(wn, state, cwds))
        redirs = [self.make_redir(r, state, cwds) for r in node.redirs]
        if not words:
            for name, sub, op, val, valnode in assigns:
                self.set_var(state, name, sub, op, val, valnode, "assign")
            if redirs:
                cmd = Cmd(self.new_id(), [], cwd_list(cwds), ctx=self.labels, span=(node.start, node.end))
                cmd.redirs = redirs
                cmd.alt, cmd.aliases = alt, aliases
                cmd.env = EnvView(state.env_ops)
                self.emit(cmd)
                self.last_top = cmd
            return (cwds, cwds)
        prefix = []
        local_paths = None
        for name, sub, op, val, valnode in assigns:
            prefix.append(EnvOp("prefix", "set", name + sub, val))
            if name == "PATH":
                local_paths = [val.value] if val.value is not None else None
        st = state
        if local_paths is not None or any(n == "PATH" for n, _, _, _, _ in assigns):
            st = state.copy()
            st.paths = local_paths
            st.path_modified = True
        return self.process(words, cwds, st, prefix, redirs, stdin, alt=alt, aliases=aliases,
                            span=(node.start, node.end), outer_state=state)

    def set_var(self, state, name, sub, op, val, valnode, via):
        raw_val = valnode.raw if valnode is not None else ""
        if sub:
            state.vars[name] = DYN
        elif op == "+=":
            old = state.vars.get(name, self.ctx.env.get(name))
            state.vars[name] = old + val.value if isinstance(old, str) and val.value is not None else DYN
        else:
            state.vars[name] = val.value if val.value is not None else DYN
        state.env_ops.append(EnvOp(via, "set", name + sub, val))
        if name in ("PATH", "path"):
            state.path_modified = True
            if name == "PATH" and not sub and op == "=" and val.value is not None:
                state.paths = [val.value]
            elif name == "path" and not sub and raw_val.startswith("("):
                state.paths = self.path_array(raw_val, state, op)
            else:
                state.paths = None
        if name in ("CDPATH", "cdpath"):
            state.cdpath = not (val.value == "" or raw_val in ("()", ""))
        if name == "fpath":
            state.fpath_changed = True
            self.note("fpath-changed")
        if name == "IFS":
            self.note("ifs-changed")

    def path_array(self, raw, state, op):
        inner = raw[1:-1] if raw.endswith(")") else raw[1:]
        old = state.paths[0].split(":") if state.paths and len(state.paths) == 1 else None
        out = []
        for tok in inner.split():
            if tok in ("$path", "${path}", "${path[@]}", "$PATH", "${PATH}", '"$path[@]"', "$path[@]"):
                if old is None:
                    return None
                out.extend(old)
            elif "$" in tok or "`" in tok or "~" in tok or "'" in tok or '"' in tok:
                return None
            else:
                out.append(tok)
        if op == "+=":
            if old is None:
                return None
            out = old + out
        return [":".join(out)]

    def make_redir(self, r, state, cwds):
        op = r.op
        if r.heredoc is not None:
            h = r.heredoc
            body = h.get("body") or ""
            dynamic = False
            if not h.get("quoted") and h.get("parts"):
                wn = WordNode(h["parts"], body, 0, 0)
                ws = self.expand(wn, state, cwds)
                if ws and ws[0].value is not None:
                    body = ws[0].value
                elif ws:
                    body = ws[0].skeleton.replace("\0", "")
                    dynamic = True
            return Redir(r.fd, op, "heredoc", target=None, body=body, body_dynamic=dynamic)
        if getattr(r, "dup", None) is not None:
            return Redir(r.fd, op, "close" if r.dup == "-" else "dup", target=Word.lit(r.dup))
        tw = self.expand(r.target, state, cwds)
        target = tw[0] if len(tw) == 1 else Word(r.target.raw, None, dynamic=True, dyn=["brace"], skeleton="\0")
        if op == "<<<":
            return Redir(r.fd, op, "herestring", target=target, body=(target.value if target.value is not None
                                                                     else target.skeleton) + "\n",
                         body_dynamic=target.dynamic)
        mode = {"<": "read", "<>": "rw", "<&": "read"}.get(op)
        if mode is None:
            mode = "append" if op.startswith(">>") or op == "&>>" else "write"
        return Redir(r.fd, op, mode, target=target)

    # ---- one command (after expansion) ----

    def process(self, words, cwds, state, prefix_ops, redirs, stdin, alt=None, aliases=(), span=(0, 0),
                via_program=False, parent=None, extra_ctx=(), lock_depth=0, outer_state=None):
        outer = outer_state or state
        cmd = Cmd(self.new_id(), words, cwd_list(cwds), ctx=self.labels + list(extra_ctx), parent=parent, span=span)
        cmd.alt, cmd.aliases = alt, list(aliases)
        cmd.redirs = redirs
        env_ops = list(state.env_ops) + list(prefix_ops)
        if state.env_unknown:
            env_ops.append(EnvOp("source", "unknown"))
        by_shell = not via_program
        bypass_func = via_program
        wrappers = []
        i = 0
        query = False
        run_cwd = None
        clear_env = False
        deferred = []
        while i < len(words) and len(wrappers) < limits.MAX_WRAPPERS:
            v = words[i].value
            if v is None:
                break
            name = recog.base(v)
            if by_shell and name == "builtin" and "/" not in v:
                wrappers.append(Wrapper("builtin", []))
                bypass_func = True
                i += 1
                continue
            if by_shell and name == "command" and "/" not in v:
                j = i + 1
                while j < len(words) and words[j].value and words[j].value.startswith("-") and words[j].value != "--":
                    if "v" in words[j].value or "V" in words[j].value:
                        query = True
                    j += 1
                if j < len(words) and words[j].value == "--":
                    j += 1
                if query:
                    break
                wrappers.append(Wrapper("command", words[i + 1:j]))
                bypass_func = True
                i = j
                continue
            if by_shell and name == "exec" and "/" not in v:
                j = i + 1
                eff = "none"
                while j < len(words) and words[j].value and words[j].value.startswith("-"):
                    if words[j].value == "-a":
                        j += 1
                    elif "c" in words[j].value:
                        eff = "env-clear"
                        env_ops.append(EnvOp("exec", "clear"))
                    j += 1
                wrappers.append(Wrapper("exec", words[i + 1:j], eff))
                outer.after_exec = True
                bypass_func = True
                i = j
                continue
            if by_shell and name in ("noglob", "nocorrect", "-") and "/" not in v:
                wrappers.append(Wrapper(name, []))
                i += 1
                continue
            if name == "env":
                j = i + 1
                eff = "env-ops"
                stop_opaque = None
                while j < len(words):
                    a = words[j].value
                    if a is None:
                        break
                    if a in ("-i", "-", "--ignore-environment"):
                        env_ops.append(EnvOp("env-i", "clear"))
                        eff = "env-clear"
                        j += 1
                    elif a in ("-u", "--unset") and j + 1 < len(words):
                        env_ops.append(EnvOp("env-u", "unset", words[j + 1].value))
                        j += 2
                    elif a.startswith("--unset="):
                        env_ops.append(EnvOp("env-u", "unset", a.split("=", 1)[1]))
                        j += 1
                    elif a in ("-C", "--chdir") and j + 1 < len(words):
                        run_cwd = words[j + 1].value if words[j + 1].value is not None else ""
                        j += 2
                    elif a.startswith("--chdir="):
                        run_cwd = a.split("=", 1)[1]
                        j += 1
                    elif a in ("-S", "--split-string") or a.startswith(("-S", "--split-string=")):
                        stop_opaque = " ".join(w.skeleton for w in words[j:])
                        j = len(words)
                    elif a == "--":
                        j += 1
                        while j < len(words) and words[j].value and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[j].value):
                            n, _, val = words[j].value.partition("=")
                            env_ops.append(EnvOp("env", "set", n, Word.lit(val)))
                            j += 1
                        break
                    elif re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", a):
                        n, _, val = a.partition("=")
                        env_ops.append(EnvOp("env", "set", n, Word.lit(val)))
                        j += 1
                    elif a.startswith("-"):
                        j += 1
                    else:
                        break
                wrappers.append(Wrapper("env", words[i + 1:j], eff))
                by_shell = False
                if stop_opaque is not None:
                    cmd.words, cmd.wrappers = [], wrappers
                    cmd.env = EnvView(env_ops)
                    self.emit(cmd)
                    self.emit_opaque(Opaque("env-S", payload=stop_opaque, cwds=cwd_list(cwds)), cmd)
                    return (cwds, cwds)
                i = j
                continue
            if name in ("sudo", "doas"):
                j = i + 1
                keep = shell = False
                eff = "env-clear"
                while j < len(words):
                    a = words[j].value
                    if a is None or not a.startswith("-"):
                        break
                    if a == "--":
                        j += 1
                        break
                    if a in ("-u", "-g", "-C", "-h", "-p", "-U", "-D", "-r", "-t", "-T"):
                        j += 2
                        continue
                    if a in ("-E",) or a.startswith("--preserve-env"):
                        keep = True
                    if a in ("-s", "-i", "--shell", "--login"):
                        shell = True
                    j += 1
                if not keep:
                    env_ops.append(EnvOp("sudo", "clear"))
                else:
                    eff = "user-change"
                wrappers.append(Wrapper(name, words[i + 1:j], eff))
                by_shell = False
                if shell:
                    rest = words[j:]
                    cmd.words, cmd.wrappers = rest, wrappers
                    cmd.env = EnvView(env_ops)
                    self.emit(cmd)
                    payload = " ".join(w.value for w in rest) if rest and all(w.value is not None for w in rest) else (
                        "" if not rest else None)
                    self.emit_opaque(Opaque("sudo-shell", payload=payload, cwds=cwd_list(cwds)), cmd)
                    return (cwds, cwds)
                i = j
                continue
            if name in ("nohup", "nice", "ionice", "timeout", "gtimeout", "stdbuf", "caffeinate", "time", "chronic",
                        "unbuffer") and not (name == "time" and by_shell and False):
                j = i + 1
                takes = {"nice": ("-n",), "ionice": ("-c", "-n", "-p"), "timeout": ("-s", "-k", "--signal", "--kill-after"),
                         "gtimeout": ("-s", "-k"), "stdbuf": ("-i", "-o", "-e"), "caffeinate": ("-t", "-w"),
                         "time": ("-o", "-f")}.get(name, ())
                while j < len(words):
                    a = words[j].value
                    if a is None:
                        break
                    if a in takes:
                        j += 2
                        continue
                    if a == "--":
                        j += 1
                        break
                    if a.startswith("-"):
                        j += 1
                        continue
                    if name in ("timeout", "gtimeout") and re.match(r"^\d+(\.\d+)?[smhd]?$", a):
                        j += 1
                        break
                    if name == "nice" and re.match(r"^-?\d+$", a):
                        j += 1
                        continue
                    break
                wrappers.append(Wrapper(name, words[i + 1:j]))
                by_shell = False
                i = j
                continue
            break
        cmd.words = words[i:]
        cmd.wrappers = wrappers
        cmd.env = EnvView(env_ops)
        if run_cwd is not None:
            cmd.run_cwds = self.join_cwds(cwds, run_cwd)
        flags = cmd.flags
        if not by_shell:
            flags.add("exec-by-program")
        if query:
            flags.add("query")
            self.emit(cmd)
            self.last_top = cmd
            return (cwds, cwds)
        if state.path_modified:
            flags.add("path-modified")
        if state.env_unknown:
            flags.add("env-unknown")
        if outer.after_exec and "exec" not in [w.name for w in wrappers]:
            flags.add("after-exec")
        if not cmd.words:
            self.emit(cmd)
            self.last_top = cmd
            return (cwds, cwds)
        w0 = cmd.words[0]
        if w0.value is None:
            flags.add("dynamic-argv0")
            self.emit(cmd)
            self.last_top = cmd
            payload = " ".join(w.skeleton.replace("\0", "") if w.dynamic else w.value for w in cmd.words)
            raw = " ".join(w.raw for w in cmd.words)
            op = Opaque("dynamic-command", payload=payload + "\n" + raw, cwds=cwd_list(cwds))
            self.emit_opaque(op, cmd)
            return (cwds, cwds)
        prog = cmd.prog
        is_path = "/" in w0.value
        snap = self.ctx.snapshot
        # functions and shadows
        if by_shell and not bypass_func and not is_path:
            if prog in outer.aliases_defined or prog in outer.shadowed:
                flags.add("shadowed")
                if prog in outer.shadowed and prog in ("cd", "chdir", "pushd", "popd"):
                    self.emit(cmd)
                    self.last_top = cmd
                    return (None, None)
            if prog in outer.funcs:
                flags.add("inline-function")
                if prog in ("cd", "pushd", "popd", "builtin", "command") or prog in ("git", "rm", "cp", "mv"):
                    flags.add("shadowed")
                self.emit(cmd)
                self.last_top = cmd
                eff = outer.funcs[prog]
                if eff["options"]:
                    _options_unknown(outer)
                if eff["cwd"] or prog in ("cd", "pushd", "popd"):
                    outer.dirstack = None
                    return (None, None)
                return (cwds, cwds)
            if snap is not None and prog in snap.delegated:
                flags.add("via-function")
            elif snap is not None and prog in snap.user_functions:
                flags.add("user-function")
                self.emit(cmd)
                self.last_top = cmd
                body = snap.function_text(prog) or ""
                payload = " ".join(w.value if w.value is not None else w.skeleton for w in cmd.words) + "\n" + body
                self.emit_opaque(Opaque("function", payload=payload, cwds=cwd_list(cwds)), cmd)
                outer.env_unknown = True
                return (None, None)
        if by_shell and not is_path and (snap is None or snap.partial):
            if not self.runnable(prog, outer):
                # zsh may run an alias or function we could not read: the judgement in M0d-1b denies this
                # in harness repositories; the command itself is still recognized below
                payload = " ".join(w.value if w.value is not None else w.skeleton for w in cmd.words)
                op_unknown = Opaque("unknown-command", payload=payload, cwds=cwd_list(cwds))
                deferred.append(lambda: self.emit_opaque(op_unknown, cmd))
        shell_builtin = not is_path and (by_shell or bypass_func and not via_program)
        if shell_builtin and prog in BUILTINS:
            self.cur_stdin = stdin
            out = BUILTINS[prog](self, cmd, cwds, outer)
            self.emit(cmd)
            self.last_top = cmd
            for f in deferred:
                f()
            return out
        out = self.recognize(cmd, cwds, outer, stdin, lock_depth, deferred)
        self.emit(cmd)
        self.last_top = cmd
        self.record_written(cmd, outer)
        for f in deferred:
            f()
        return out

    def runnable(self, prog, state):
        if prog in state.funcs or prog in self.ctx.inline_functions:
            return True
        snap = self.ctx.snapshot
        if snap is not None and (prog in snap.plain or prog in snap.alternatives):
            return True
        from .scanctx import ZSH_BUILTINS
        from .parse import RESERVED
        if prog in ZSH_BUILTINS or prog in RESERVED:
            return True
        if snap is not None and (prog in snap.user_functions or prog in snap.delegated):
            return True
        if state.paths is None:
            return True  # PATH unknown: cannot tell
        return self.which(prog, state) is not None

    def join_cwds(self, cwds, rel):
        if rel == "":
            return []
        if os.path.isabs(rel):
            return [os.path.normpath(rel)]
        if not cwds:
            return []
        return [os.path.normpath(os.path.join(c, rel)) for c in cwds]

    # ---- recognition of external commands ----

    def recognize(self, cmd, cwds, state, stdin, lock_depth, deferred):
        words = cmd.words
        prog = cmd.prog
        k = recog.key(prog)
        args = words[1:]
        # git
        if k == "git":
            env = cmd.env.set
            g = recog.git_info(args, None)
            for n in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT"):
                if n in env:
                    g.env[n] = env[n]
            cmd.git = g
            if g.c_dirs:
                rc = cwds
                for d in g.c_dirs:
                    rc = tuple(self.join_cwds(rc, d if d is not None else "")) or None
                cmd.run_cwds = list(rc or [])
        opt = recog.cwd_option(prog, args)
        if opt is not None:
            cmd.run_cwds = self.join_cwds(cwds, opt)
        # s2v
        run = cmd.run_cwds[0] if len(cmd.run_cwds) == 1 else None
        form = recog.s2v_like(words)
        if form is not None:
            cmd.s2v = recog.classify_s2v(words, run, self.ctx.s2v_path, state.paths or [], self.ctx.fs)
        # interpreters, scripts, lock.py
        fam = recog.interp_family(prog)
        if fam is not None and not (cmd.s2v and cmd.s2v.form in ("node", "tsx")):
            mode, val, rest = recog.parse_interp(fam, prog, args)
            if mode == "inline":
                kind = "shell-c" if fam == "shell" else "interp-inline"
                payload = val.value if val is not None else None
                if val is not None and val.value is None:
                    payload = None
                op = Opaque(kind, payload=payload, cwds=cwd_list(cwds))
                self.emit_later(deferred, op, cmd)
            elif mode == "stdin":
                self.stdin_opaque(cmd, cwds, state, stdin, deferred, "interp")
            elif mode == "script" and val is not None:
                self.script_call(cmd, prog, val, rest, cwds, state, stdin, lock_depth, deferred)
            elif mode == "other" and val is None and rest and any(w.value is None for w in rest[:1]):
                self.emit_later(deferred, Opaque("dynamic-command", payload=None, cwds=cwd_list(cwds)), cmd)
        elif "/" in words[0].value and cmd.s2v is None:
            self.script_call(cmd, None, words[0], args, cwds, state, stdin, lock_depth, deferred)
        # programs that run other programs
        if k == "xargs":
            self.xargs(cmd, args, cwds, state, deferred)
        elif k in ("find", "gfind", "bfs"):
            self.find_exec(cmd, args, cwds, state, deferred)
        elif k in ("parallel", "watch"):
            payload = " ".join(w.value if w.value is not None else w.skeleton for w in args)
            self.emit_later(deferred, Opaque(k, payload=payload, cwds=cwd_list(cwds)), cmd)
        elif k in ("awk", "gawk", "nawk", "mawk"):
            prog_text = self.first_operand(args, ("-F", "-v", "-f"))
            if prog_text is not None and re.search(r"system\s*\(|getline|print[f]?\b[^;}]*>|\|\s*\"", prog_text):
                self.emit_later(deferred, Opaque("awk-program", payload=prog_text, cwds=cwd_list(cwds)), cmd)
        elif k in ("sed", "gsed"):
            scripts = [args[i + 1].value for i, w in enumerate(args[:-1]) if w.value in ("-e", "--expression")]
            if not scripts:
                f = self.first_operand(args, ("-f",))
                scripts = [f] if f is not None else []
            for s in scripts:
                if s and re.search(r"(^|[;{}\n])\s*(\d+|\$|/[^/]*/)?\s*e(\s|;|$)", s):
                    self.emit_later(deferred, Opaque("sed-exec", payload=s, cwds=cwd_list(cwds)), cmd)
        elif k in ("eval",):
            pass
        return (cwds, cwds)

    def emit_later(self, deferred, op, cmd):
        deferred.append(lambda: self.emit_opaque(op, cmd))

    def first_operand(self, args, value_opts):
        i = 0
        while i < len(args):
            v = args[i].value
            if v is None:
                return None
            if v in value_opts:
                i += 2
                continue
            if v.startswith("-") and v != "-":
                i += 1
                continue
            return v
        return None

    def stdin_payload(self, cmd, stdin, state):
        for r in reversed(cmd.redirs):
            if r.fd not in (None, "0"):
                continue
            if r.mode == "heredoc":
                return r.body, "heredoc", "heredoc-interp"
            if r.mode == "herestring":
                return r.body, "herestring", "herestring-interp"
            if r.mode == "read" and r.target is not None:
                if r.target.value is None or not cmd.cwds:
                    return None, "unknown", "stdin-interp"
                p = self.where.absolute(r.target.value, cmd.cwds[0])
                if p in state.written:
                    return state.written[p], "linked-heredoc", "stdin-interp"
                return self.ctx.fs.read(p), "file", "stdin-interp"
        if stdin is not None:
            kind, val = stdin
            if kind == "literal":
                return val, "pipe-literal", "stdin-interp"
            if kind == "file":
                if val in state.written:
                    return state.written[val], "linked-heredoc", "stdin-interp"
                return (self.ctx.fs.read(val) if val else None), "file", "stdin-interp"
            return None, "unknown", "stdin-interp"
        # the Bash tool runs `eval '<cmd>' < /dev/null`: nothing arrives on stdin
        return "", "devnull", "stdin-interp"

    def stdin_opaque(self, cmd, cwds, state, stdin, deferred, what, kind_override=None, path=None, pclass=None):
        payload, origin, kind = self.stdin_payload(cmd, stdin, state)
        op = Opaque(kind_override or kind, payload=payload, origin=origin, cwds=cwd_list(cwds), path=path,
                    path_class=pclass)
        self.emit_later(deferred, op, cmd)

    def script_call(self, cmd, interp, pword, rest, cwds, state, stdin, lock_depth, deferred):
        cwd = cmd.cwds[0] if cmd.cwds else None
        if pword.value is None:
            self.emit_later(deferred, Opaque("dynamic-command", payload=None, cwds=cwd_list(cwds)), cmd)
            return
        res = self.where.resolve(pword.value, cwd) if (cwd or os.path.isabs(pword.value)) else None
        cmd.script = ScriptCall(interp, res.to_dict() if res else {"text": pword.value}, rest)
        if os.path.basename(pword.value) == "lock.py":
            self.lock_child(cmd, res, rest, cwds, state, lock_depth, deferred)
            return
        if interp is None and recog.is_bin_dir(res.abs if res else None):
            return
        real = res.real if res else None
        pclass = self.where.path_class(real, self.ctx.env) if real else ["other"]
        abs_p = res.abs if res else None
        if abs_p in state.written:
            payload, origin = state.written[abs_p], "linked-heredoc"
        elif res is not None and res.exists and self.ctx.fs.isfile(abs_p):
            payload = self.ctx.fs.read(abs_p)
            origin = "file"
            if interp is None and payload is not None and not payload.startswith("#!"):
                if "\x00" in payload[:512]:
                    return  # a binary
        else:
            payload, origin = None, "unknown"
        self.emit_later(deferred, Opaque("script", payload=payload, origin=origin, cwds=cwd_list(cwds),
                                         path=abs_p, path_class=pclass), cmd)

    def lock_child(self, cmd, res, rest, cwds, state, lock_depth, deferred):
        values = [w.value for w in rest]
        usage = None
        opts = None
        if any(v is None for v in values):
            usage = "dynamic argument"
        else:
            try:
                opts = lockargs.parse(values)
            except lockargs.UsageError as e:
                usage = str(e)
        sub = opts["cmd"] if opts else (values[0] if values and values[0] else None)
        lw = LockWrap(sub, kind=opts.get("kind") if opts else None, holder=opts.get("holder") if opts else None,
                      ids=opts.get("ids") if opts else [], script=res.to_dict() if res else None,
                      usage_error=usage)
        if res is not None and res.real:
            cands = {PLUGIN_LOCK}
            run = cmd.cwds[0] if cmd.cwds else None
            if run:
                repo = self.where.git_repo(run) if self.ctx.fs.exists(run) else None
                if repo:
                    cands.add(os.path.realpath(os.path.join(repo.worktree, ".claude", "studio", "scripts", "lock.py")))
            lw.verified = res.real in cands
        cmd.lock = lw
        idx = next((i for i, v in enumerate(values) if v == "--"), None)
        if idx is None:
            return
        child = rest[idx + 1:]
        if not child:
            return
        if lock_depth + 1 > limits.MAX_LOCK_DEPTH:
            self.note("lock-depth")
            payload = " ".join(w.value if w.value is not None else w.skeleton for w in child)
            self.emit_later(deferred, Opaque("script", payload=payload, origin="literal", cwds=cwd_list(cwds)), cmd)
            return
        prefix = [op for op in cmd.env.ops if op not in state.env_ops]

        def run_child():
            self.process(child, cwds, state, prefix, [], None, alt=cmd.alt, span=cmd.span, via_program=True,
                         parent=cmd.id, extra_ctx=("lock-child",), lock_depth=lock_depth + 1)
        deferred.append(run_child)

    def xargs(self, cmd, args, cwds, state, deferred):
        takes = ("-I", "-n", "-P", "-L", "-d", "-a", "-E", "-s", "-i", "-J", "-R", "-S")
        i = 0
        while i < len(args):
            v = args[i].value
            if v is None or not v.startswith("-"):
                break
            if v in takes:
                i += 2
                continue
            i += 1
        tpl = args[i:] or [Word.lit("echo")]
        payload = " ".join(w.value if w.value is not None else w.skeleton for w in tpl)
        self.emit_later(deferred, Opaque("xargs", payload=payload, cwds=cwd_list(cwds)), cmd)

        def run_tpl():
            self.process(list(tpl) + [Word("{}", None, dynamic=True, dyn=["xargs-input"], skeleton="\0")], cwds,
                         state.copy(), [], [], None, alt=cmd.alt, span=cmd.span, via_program=True, parent=cmd.id,
                         extra_ctx=("exec-template",))
        deferred.append(run_tpl)

    def find_exec(self, cmd, args, cwds, state, deferred):
        i = 0
        while i < len(args):
            v = args[i].value
            if v in ("-exec", "-execdir", "-ok", "-okdir"):
                j = i + 1
                while j < len(args) and args[j].value not in (";", "+"):
                    j += 1
                tpl = [Word("{}", None, dynamic=True, dyn=["find-path"], skeleton="\0") if w.value == "{}" else w
                       for w in args[i + 1:j]]
                if tpl:
                    payload = " ".join(w.value if w.value is not None else w.skeleton for w in tpl)
                    self.emit_later(deferred, Opaque("find-exec", payload=payload, cwds=cwd_list(cwds)), cmd)

                    def run_tpl(tpl=tpl):
                        self.process(tpl, cwds, state.copy(), [], [], None, alt=cmd.alt, span=cmd.span,
                                     via_program=True, parent=cmd.id, extra_ctx=("exec-template",))
                    deferred.append(run_tpl)
                i = j + 1
                continue
            i += 1

    def record_written(self, cmd, state):
        """Files this command writes with known content (for linked heredocs)."""
        if not cmd.cwds:
            return
        cwd = cmd.cwds[0]
        body = None
        for r in cmd.redirs:
            if r.mode in ("heredoc", "herestring") and r.fd in (None, "0"):
                body = r.body
        p = cmd.prog
        content = None
        if p in ("cat", "tee") and body is not None:
            content = body
        elif p in ("echo", "printf", "print") and all(a is not None for a in cmd.argv[1:]):
            content = " ".join(cmd.argv[1:]) + "\n"
        if content is None:
            return
        targets = [r.target.value for r in cmd.redirs if r.mode in ("write", "append") and r.target is not None
                   and r.target.value is not None]
        if p == "tee":
            targets += [a for a in cmd.argv[1:] if a is not None and not a.startswith("-")]
        for t in targets:
            state.written[self.where.absolute(t, cwd)] = content


# ---- builtins ----

def _args(cmd):
    return cmd.words[1:]


def _prefix_cdpath(cmd):
    return any(op.via == "prefix" and (op.name or "").split("[")[0] in ("CDPATH", "cdpath") for op in cmd.env.ops)


def _chaselinks(w, state):
    """True / False, or None when unknown (in-command option changes, snapshots disagree)."""
    if "chaselinks" in state.opts:
        return state.opts["chaselinks"]
    snap = w.ctx.snapshot
    if snap is not None and "chaselinks" in snap.option_conflicts:
        return None
    return bool(w.ctx.options.get("chaselinks", False))


def b_cd(w, cmd, cwds, state):
    args = _args(cmd)
    physical = False
    rest = []
    old = cwds
    if _prefix_cdpath(cmd):
        return (None, old)
    opts_done = False
    for a in args:
        v = a.value
        if not opts_done and v is not None and re.match(r"^-[LPqse@]+$", v):
            if "P" in v:
                physical = True
            if "e" in v or "@" in v:
                pass
            continue
        if not opts_done and v == "--":
            opts_done = True
            continue
        opts_done = True
        rest.append(a)
    if len(rest) > 1:
        return (None, old)
    if not rest:
        target = w.lookup("HOME", state, cwds)
        if target is None:
            return (None, old)
        rest_val = target
    else:
        rest_val = rest[0].value
        if rest_val is None:
            return (None, old)
    if rest_val == "-":
        if state.oldpwd is None:
            return (None, old)
        rest_val = state.oldpwd
    elif re.match(r"^[+-]\d+$", rest_val):
        return _stack_move(w, cmd, cwds, state, rest_val)
    if state.cdpath and not rest_val.startswith(("/", "./", "../")) and rest_val not in (".", ".."):
        return (None, old)
    chase = _chaselinks(w, state)
    if chase is None:
        return (None, old)
    return _move(w, cwds, state, rest_val, physical or chase, push=w.ctx.options.get("autopushd"))


def physical_path(fs, base, target):
    """cd -P: resolve each component against the real directory (link/.. leaves the link's target).
    None when a component cannot be checked."""
    p = fs.realpath(base) if not os.path.isabs(target) else "/"
    for comp in target.split("/"):
        if comp in ("", "."):
            continue
        if comp == "..":
            p = os.path.dirname(p) or "/"
            continue
        q = os.path.join(p, comp)
        st = fs.stat(q)
        if st == "error":
            return None
        if st is None:
            p = q  # does not exist: cd fails; keep the lexical rest
            continue
        p = fs.realpath(q)
    return p


def _move(w, cwds, state, target, physical=False, push=False):
    old = cwds
    if old is None and not os.path.isabs(target):
        return (None, None)
    bases = old if old is not None else ("/",)
    news = []
    fails = []
    for b in bases:
        if physical:
            n = physical_path(w.ctx.fs, b, target)
            if n is None:
                return (None, old)
        else:
            n = os.path.normpath(os.path.join(b, target))
        news.append(n)
        if not w.ctx.fs.isdir(n):
            if w.ctx.options.get("cdablevars") and "/" not in target:
                return (None, old)
            fails.append(b)
    S = tuple(dict.fromkeys(news))
    F = tuple(dict.fromkeys(fails))
    state.oldpwd = single(old) if not F else None
    if push:
        if single(old) and state.dirstack is not None and not F:
            state.dirstack.append(single(old))
        else:
            state.dirstack = None  # the move may fail (nothing pushed) or the old cwd is not one path
    return (S if len(S) <= limits.MAX_CWDS else None, F)


def _stack_move(w, cmd, cwds, state, spec):
    return (None, cwds)


def b_pushd(w, cmd, cwds, state):
    if _prefix_cdpath(cmd) or _chaselinks(w, state) is None:
        return (None, cwds)
    args = [a for a in _args(cmd) if a.value not in ("-q",)]
    if not args:
        if state.dirstack and single(cwds):
            top = state.dirstack.pop()
            state.dirstack.append(single(cwds))
            state.oldpwd = single(cwds)
            return ((top,), ())
        return (None, cwds)
    v = args[0].value
    if v is None or re.match(r"^[+-]\d+$", v):
        return (None, cwds)
    if state.cdpath and not v.startswith(("/", "./", "../")) and v not in (".", ".."):
        return (None, cwds)
    return _move(w, cwds, state, v, physical=bool(_chaselinks(w, state)), push=True)


def b_popd(w, cmd, cwds, state):
    args = [a for a in _args(cmd) if a.value not in ("-q",)]
    if args or not state.dirstack:
        return (None, cwds)
    top = state.dirstack.pop()
    state.oldpwd = single(cwds)
    return ((top,), ())


def b_dirs(w, cmd, cwds, state):
    if any(a.value == "-c" for a in _args(cmd)):
        state.dirstack = []
    return (cwds, cwds)


def b_export(w, cmd, cwds, state):
    prog = cmd.prog
    args = _args(cmd)
    flags = set()
    via = {"export": "export", "declare": "declare", "typeset": "typeset", "local": "local",
           "readonly": "readonly", "integer": "typeset", "float": "typeset"}[prog]
    for a in args:
        v = a.value if a.value is not None else a.raw
        if v.startswith(("-", "+")) and "=" not in v:
            flags |= set(v[1:])
            continue
        if "f" in flags or "p" in flags and "=" not in v:
            continue
        name, eq, val = v.partition("=")
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*(\[[^\]]*\])?$", name):
            continue
        if via in ("declare", "typeset") and "x" in flags:
            via2 = via + "-x"
        else:
            via2 = via
        if prog == "export" and "n" in flags:
            state.env_ops.append(EnvOp("export-n", "unset", name))
            continue
        if eq:
            if a.value is None:
                valw = Word(a.raw, None, dynamic=True, dyn=a.dyn, skeleton=a.skeleton.partition("=")[2])
            else:
                alt = a.alt.partition("=")[2] if a.alt else None
                valw = Word(val, val, alt=alt)
                if alt is not None and alt != "\0" and alt != val:
                    valw = Word(val, alt, alt=val)  # export args are assignments: zsh expands ~ after =
            w.set_var(state, name.split("[")[0], name[len(name.split("[")[0]):], "=", valw, None, via2)
            if state.vars.get(name) is DYN:
                pass
        else:
            cur = state.vars.get(name, w.ctx.env.get(name))
            valw = Word.lit(cur) if isinstance(cur, str) else Word(name, None, dynamic=True, dyn=["param:" + name],
                                                                   skeleton="\0")
            state.env_ops.append(EnvOp(via2, "set", name, valw))
    return (cwds, cwds)


def b_unset(w, cmd, cwds, state):
    func = False
    for a in _args(cmd):
        v = a.value
        if v is None:
            state.env_ops.append(EnvOp("unset", "unknown"))
            continue
        if v.startswith("-"):
            func = "f" in v
            continue
        if func:
            state.funcs.pop(v, None)
            continue
        state.vars[v] = DYN
        state.env_ops.append(EnvOp("unset", "unset", v))
        if v in ("PATH", "path"):
            state.paths = None
            state.path_modified = True
        if v in ("CDPATH", "cdpath"):
            state.cdpath = False
    return (cwds, cwds)


def b_alias(w, cmd, cwds, state):
    for a in _args(cmd):
        v = a.value
        if v is None or "=" not in v or v.startswith("-"):
            continue
        name, _, val = v.partition("=")
        state.aliases_defined.add(name)
        w.emit_opaque(Opaque("alias", payload=val, cwds=cwd_list(cwds)), cmd)
    return (cwds, cwds)


def b_noop(w, cmd, cwds, state):
    return (cwds, cwds)


def b_source(w, cmd, cwds, state):
    args = _args(cmd)
    deferred = []
    if not args:
        return (cwds, cwds)
    p = args[0]
    if p.value in ("/dev/stdin", "/dev/fd/0", "-"):
        w.stdin_opaque(cmd, cwds, state, getattr(w, "cur_stdin", None), deferred, "source", kind_override="source")
    else:
        cwd = cmd.cwds[0] if cmd.cwds else None
        res = w.where.resolve(p.value, cwd) if p.value is not None and (cwd or os.path.isabs(p.value)) else None
        payload, origin = None, "unknown"
        if res is not None:
            if res.abs in state.written:
                payload, origin = state.written[res.abs], "linked-heredoc"
            elif res.exists:
                payload, origin = w.ctx.fs.read(res.abs), "file"
        pclass = w.where.path_class(res.real, w.ctx.env) if res is not None and res.real else ["other"]
        deferred.append(lambda: w.emit_opaque(Opaque("source", payload=payload, origin=origin, cwds=cwd_list(cwds),
                                                     path=res.abs if res else None, path_class=pclass), cmd))
    for f in deferred:
        f()
    state.env_unknown = True
    state.paths = None
    w.note("env-unknown-after:#%d" % cmd.id)
    return (None, None)


def b_eval(w, cmd, cwds, state):
    """The payload runs in this shell: afterwards the cwd and the environment are unknown."""
    args = _args(cmd)
    payload = " ".join(a.value for a in args) if all(a.value is not None for a in args) else None
    op = Opaque("eval", payload=payload, cwds=cwd_list(cwds))
    if payload is None and args:
        op.literals = [" ".join(a.skeleton.replace("\0", "") for a in args)]
    w.emit_opaque(op, cmd)
    if args:
        state.env_unknown = True
        state.paths = None
        state.argv_opts_changed = True
        state.dirstack = None
        state.oldpwd = None
        return (None, None)
    return (cwds, cwds)


def b_emulate(w, cmd, cwds, state):
    vals = [a.value for a in _args(cmd)]
    if "-c" in vals:
        i = vals.index("-c")
        code = vals[i + 1] if i + 1 < len(vals) else None
        w.emit_opaque(Opaque("eval", payload=code, cwds=cwd_list(cwds)), cmd)
        state.env_unknown = True
        state.paths = None
        return (None, None)
    if "-L" in vals or any(v and re.match(r"^-[a-zA-Z]*L", v) for v in vals):
        state.opts["localoptions"] = True
    if any(v and not v.startswith("-") for v in vals) or any(v is None for v in vals):
        _options_unknown(state)
    return (cwds, cwds)


ARGV_OPTIONS = {"shwordsplit", "globsubst", "rcexpandparam", "ksharrays", "shglob", "noglob", "glob", "equals",
                "magicequalsubst", "rcquotes", "kshglob", "extendedglob", "nomatch", "nullglob", "cshnullglob",
                "globassign", "histsubstpattern", "bareglobqual", "shfileexpansion", "posixidentifiers",
                "ignorebraces", "ignoreclosebraces", "braceccl", "kshtypeset", "typesetsilent", "multibyte",
                "posixstrings", "cbases", "octalzeroes", "unset", "aliases", "interactivecomments"}
BRACE_OPTIONS = {"ignorebraces", "ignoreclosebraces", "braceccl", "shfileexpansion"}


def _options_unknown(state):
    state.argv_opts_changed = True
    state.brace_opts_changed = True
    state.opts["chaselinks"] = None


def _set_option(state, name, on):
    n = name.lower().replace("_", "")
    if n.startswith("no") and n not in ("nomatch", "notify"):
        n, on = n[2:], (None if on is None else not on)
    state.opts[n] = on
    if n in ARGV_OPTIONS:
        state.argv_opts_changed = True
    if n in BRACE_OPTIONS:
        state.brace_opts_changed = True


def b_setopt(w, cmd, cwds, state):
    on = cmd.prog == "setopt"
    for a in _args(cmd):
        v = a.value
        if v is None:
            _options_unknown(state)
            continue
        if v.startswith("-") or v.startswith("+"):
            if len(v) > 1 and not v.startswith("--"):
                _options_unknown(state)  # single-letter option flags
            continue
        _set_option(state, v, on)
    return (cwds, cwds)


def b_exit(w, cmd, cwds, state):
    return ((), ())


def b_set(w, cmd, cwds, state):
    args = _args(cmd)
    vals = [a.value for a in args]
    if "-a" in vals or ("-o" in vals and "allexport" in vals):
        state.allexport = True
    i = 0
    while i < len(vals):
        v = vals[i]
        if v is None:
            _options_unknown(state)
        elif v in ("-o", "+o") and i + 1 < len(vals):
            if vals[i + 1] is None:
                _options_unknown(state)
            else:
                _set_option(state, vals[i + 1], v == "-o")
            i += 2
            continue
        elif re.match(r"^[-+][A-Za-z]+$", v) and v not in ("-a", "+a", "-e", "+e", "-u", "+u", "-x", "+x", "-v", "+v"):
            _options_unknown(state)
        i += 1
    return (cwds, cwds)


def b_trap(w, cmd, cwds, state):
    args = _args(cmd)
    if args:
        w.emit_opaque(Opaque("trap", payload=args[0].value, cwds=cwd_list(cwds)), cmd)
    return (cwds, cwds)


def b_hash(w, cmd, cwds, state):
    vals = [a.value for a in _args(cmd)]
    if cmd.prog == "hash" and "-p" in vals:
        i = vals.index("-p")
        if i + 2 < len(vals) and vals[i + 2]:
            state.shadowed.add(vals[i + 2])
            w.note("shadowed:%s" % vals[i + 2])
    if cmd.prog == "disable" or (cmd.prog == "enable" and "-n" in vals):
        for v in vals:
            if v and not v.startswith("-"):
                state.shadowed.add(v)
                w.note("shadowed:%s" % v)
    return (cwds, cwds)


def b_let(w, cmd, cwds, state):
    for a in _args(cmd):
        w.arith_check(a.value or a.raw, state, cwds, cmd)
    return (cwds, cwds)


def b_true(w, cmd, cwds, state):
    return (cwds, ())


def b_false(w, cmd, cwds, state):
    return ((), cwds)


BUILTINS = {"cd": b_cd, "chdir": b_cd, "pushd": b_pushd, "popd": b_popd, "dirs": b_dirs, "export": b_export,
            "declare": b_export, "typeset": b_export, "local": b_export, "readonly": b_export,
            "integer": b_export, "float": b_export, "unset": b_unset, "alias": b_alias, "unalias": b_noop,
            "source": b_source, ".": b_source, "eval": b_eval, "exit": b_exit, "return": b_exit, "logout": b_exit,
            "set": b_set, "trap": b_trap, "hash": b_hash, "enable": b_hash, "disable": b_hash,
            "setopt": b_setopt, "unsetopt": b_setopt, "emulate": b_emulate, "let": b_let, "true": b_true,
            ":": b_true, "false": b_false}
