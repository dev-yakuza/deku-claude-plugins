"""Walk the AST (m0d1a-plan §6): cwd sets, environment, wrappers, lock.py children, function and
alias effects, opaque forms. Emits Cmd and Opaque records; makes no allow/deny decision.

cwd outcomes are pairs (success, failure) of cwd sets: a tuple of absolute paths, () when that
path does not continue (exit, a cd that cannot fail), or None when unknown.
"""

import collections
import copy
import fnmatch
import os
import re

from .. import lockargs
from . import cmdopts, limits, protect, recog, runners, where
from .lex import WordNode
from .model import Cmd, EnvOp, EnvView, LockWrap, Opaque, Redir, ScriptCall, Word, Wrapper
from .parse import AliasOverflow, AndOr, Compound, ListNode, Pipeline, Simple

DYN = object()
PUA = 0xF0000
PLUGIN_LOCK = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "lock.py"))
GLOB_CH = set("*?[<")  # `<`: only a numeric glob `<N-M>` reaches a word unquoted (review 8 B1)
EXTGLOB_CH = set("^~#")  # glob operators under extendedglob (G1 §2)
# dynamic kinds an unquoted word may expand to nothing from (G1 §3); `param:*` too
MAYBE_EMPTY_KINDS = ("cmdsubst", "special", "paramx", "modifier", "subscript")
MAX_EMPTY_WORDS = 3  # maybe-empty words per simple command read with every subset dropped (at most 8 readings)
MAX_CHOICE_READINGS = 16  # review 11 M-1: readings of a command whose words are each one of known values
CHOICE_SHELL_RE = re.compile(r"\b(PWD|OLDPWD|dirstack|RANDOM|SECONDS|EPOCHSECONDS|EPOCHREALTIME|LINENO|_)\b|\$_\b")
CHOICE_BAD_RE = re.compile(r"[\s*?\[\]<>()|^~#\\'\"`$;&{}]")  # a value read literally only without these
# programs whose words keep their meaning wherever they stand: the no-drop reading only (G1 §3, review 2 MINOR 4)
EMPTY_EXEMPT = (protect.READ_ALLOW - protect.READ_WRITERS) | {"rm", "rmdir", "unlink", "touch", "mkdir", "chmod",
                                                              "trash"}
PRECOMMANDS = ("builtin", "command", "exec", "noglob", "nocorrect", "-")  # zsh precommand modifiers
ARRAY_PARAMS = ("argv", "path", "fpath", "cdpath", "manpath", "module_path", "pipestatus")  # zsh's own arrays


def _multi_word(dk, raw):
    """An expansion that may give several words (or none) whether quoted or not: $@, ${arr[@]}, ${=X}, ${~X}, the
    (s…) (z) (f) (0) (@) flags (G1 §3, §1.8)."""
    raw = raw or ""
    if dk == "special":
        return raw in ("$@", "$*")
    if dk == "subscript":
        return raw.endswith(("[@]", "[*]"))
    if dk == "paramx":
        inner = raw[2:-1] if raw.startswith("${") else raw[1:]
        if inner.startswith(("=", "~", "^", "@", "*")) or inner.endswith(("[@]", "[*]")) or "[@]" in inner:
            return True
        if inner.startswith("("):
            flags = inner[1:inner.find(")")] if ")" in inner else inner
            return any(ch in flags for ch in "sfz0@")
    return False


# redirection targets that cannot fail to open in the Bash tool's shell (review 8 B2)
SAFE_TARGETS = {"/dev/null", "/dev/stdout", "/dev/stderr", "/dev/stdin", "/dev/fd/0", "/dev/fd/1", "/dev/fd/2"}


def redirect_may_fail(r):
    """review 8 B2: whether opening a redirection (a parse.Redirect) may fail. zsh then skips the command it belongs to
    (builtins, functions and compound commands included: `cd x > /bad`, `true > /bad`, `{ … } > /bad`), whose status is
    1. A file (any name but /dev/null and the standard streams, a `$…` or a glob) may fail; a duplicate of an fd other
    than 0, 1, 2 may be closed. Here-documents, here-strings, `>&1`, `2>&1` and closing (`<&-`) do not fail."""
    if r.heredoc is not None or r.op == "<<<":
        return False
    dup = getattr(r, "dup", None)
    if dup is not None:
        return dup not in ("0", "1", "2", "-")
    t = r.target
    if t is not None and t.parts and all(p[0] == "lit" for p in t.parts):
        return "".join(p[1] for p in t.parts) not in SAFE_TARGETS
    return True


# review 10 B1: the known folders a folder set held when it became unknown ("one of these, or a folder the guard cannot
# tell"); the walker's list (Walker.lost) — $PWD, ~+, $(pwd) and `git rev-parse --show-toplevel` under an unknown folder
# are judged in each of them as well as under the unknown folder
_lost_sink = [None]


def note_lost(c):
    sink = _lost_sink[0]
    if sink is None or not c:
        return
    for x in c:
        if x not in sink and len(sink) < limits.MAX_CWDS * 4:
            sink.append(x)


def union(a, b):
    if a is None or b is None:
        note_lost(a if b is None else b)
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


def brace_expand(s, cap=limits.MAX_BRACE, braceccl=False):
    """zsh brace expansion on a template where quoted/dynamic text is already replaced: lists, number and character
    ranges (`{s..s}tudio`), and with BRACE_CCL a single brace's characters (`stu{d}io`, review 3 R1)."""
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
            m = re.fullmatch(r"(.)\.\.(.)(?:\.\.(-?\d+))?", inner, re.S)
            if m:
                a, b = ord(m.group(1)), ord(m.group(2))
                if PUA <= a < PUA + 4096 or PUA <= b < PUA + 4096:
                    raise BraceOverflow()  # a quoted or dynamic end: treated as unknown
                step = abs(int(m.group(3) or 1)) or 1
                if abs(b - a) // step + 1 > cap:
                    raise BraceOverflow()
                for n in (range(a, b + 1, step) if a <= b else range(a, b - 1, -step)):
                    rec(t[:i] + chr(n) + t[j + 1:])
                return
            if braceccl and inner:
                if any(PUA <= ord(ch) < PUA + 4096 for ch in inner):
                    raise BraceOverflow()
                chars = []
                k = 0
                while k < len(inner):
                    if k + 2 < len(inner) and inner[k + 1] == "-":
                        lo, hi = sorted((ord(inner[k]), ord(inner[k + 2])))
                        chars.extend(chr(c) for c in range(lo, hi + 1))
                        k += 3
                    else:
                        chars.append(inner[k])
                        k += 1
                if len(chars) > cap:
                    raise BraceOverflow()
                for ch in sorted(set(chars)):
                    rec(t[:i] + ch + t[j + 1:])
                return
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
        self._env_unknown = False
        self.funcs = {}
        self.aliases_defined = set()
        self.alias_src = set()  # fix20 (P20-5): aliases this call defined whose text may run source / `.` / eval
        self.shadowed = set()
        self.allexport = False
        self.after_exec = False
        self.written = {}
        self.fpath_changed = False
        self.opts = {}               # options changed inside the command (setopt/unsetopt/set -o)
        self.argv_opts_changed = False  # an option that changes words (shwordsplit, globsubst, …) changed
        self.brace_opts_changed = False
        self.options_unknown = False    # an option may have changed in a way the guard cannot tell (G1 §1.3)
        self.tables_changed = False     # zsh's command/alias/function/option tables written (G1 §1.8)
        self.named_dirs_unknown = set()  # ~name the guard no longer resolves (hash -d)
        self.named_dirs_any = False
        self.arrays = set(ARRAY_PARAMS)  # array parameters: unquoted, they give several words or none (G1 §3)
        self.glob_cwd = None  # (folders, pattern) after `cd <wildcard>`: the folder is unknown, the pattern is known
        # review 4 conf M-1: what this call may have put in a parameter (a glob qualifier under GLOB_SUBST): every name
        # (code the guard cannot read got words it cannot read, stdin or files the call wrote), names its words named,
        # $PWD after a folder change the guard cannot follow; and names whose values are known to hold no qualifier
        self.steer_all = False
        self.steer_names = set()
        self.pwd_steered = False
        self.safe_values = set()
        self.raw_values = {}  # name -> the text of its last assignment in the call, searched from outside (review 5)
        # review 4 bypass B3: a function may have been defined in this call (snapshot functions may run it)
        self.defs_maybe = False
        # review 7 M4: functions a literal eval / source / emulate -c string may define (name -> that text), and whether
        # a string the guard cannot read may define any name
        self.defs_src = {}
        self.defs_unknown = False
        # review 4 bypass m3, R1: a hook (chpwd, TRAP*, trap, *_functions) may change the folder after any command
        self.hook_cwd = False
        # review 6 M5-M7: what the shell's input file descriptors hold ("0", "3", …: a stdin description, see
        # Walker.input_desc) after `exec 3<<<…`; fd 0 absent is the Bash tool's /dev/null
        self.fds = {}
        # review 9: name -> (candidate values, exact) of a value the guard does not carry (an array, read, print -v,
        # set -A/--, $(print …), a function's global, one of several folders): judged where the value is used
        self.cands = {}
        self.trap_names = set()  # review 10 M1: words of active trap actions (a function so named is a hook)
        self.complete = {}  # review 10: name -> the candidates union_values found complete (cands_complete)
        self.funcs_disabled = {}  # review 11 B1: functions of this call `disable -f` turned off (enable -f restores)

    @property
    def env_unknown(self):
        return self._env_unknown

    @env_unknown.setter
    def env_unknown(self, v):
        self._env_unknown = v

    def copy(self):
        s = State.__new__(State)
        s.__dict__.update(self.__dict__)
        for k in ("vars", "funcs", "written", "opts", "raw_values", "fds", "defs_src", "cands", "complete",
                  "funcs_disabled"):
            setattr(s, k, dict(getattr(self, k)))
        for k in ("env_ops", "dirstack", "paths"):
            v = getattr(self, k)
            setattr(s, k, v if isinstance(v, StackAlts) else list(v) if v is not None else None)
        for k in ("aliases_defined", "shadowed", "named_dirs_unknown", "arrays", "steer_names", "safe_values",
                  "trap_names", "alias_src"):
            setattr(s, k, set(getattr(self, k)))
        return s


class Readings(object):
    """fix20 (P20-5): readings of one command (its folders, lost folders, choices of a value, dropped words, the
    definitions of a function in force) each start from the walk's `sourced` flag before the command; after each,
    the flag is whether any reading so far ran a source (the rest of the call is then the 0.0.26 rules' alone)."""

    def __init__(self, w):
        self.w = w
        self.flag0 = self.any = w.sourced

    def start(self):
        self.w.sourced = self.flag0

    def end(self):
        self.any = self.any or self.w.sourced
        self.w.sourced = self.any

    def done(self):
        self.w.sourced = self.any


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
        self.capture = None  # [Cmd]: the first command process() makes (the program of a reading, G1 §3)
        self.pipe_in = None  # the pipe a compound command in a pipeline reads: its commands read it (review 5 M5)
        self.func_depth = 0  # inside a function body this call defines: `return` ends the function, not the shell
        self.rewalking = set()  # functions this call defined whose bodies are being walked again with input (M6)
        self.input_ctx = {}  # cmd id -> (stdin, state): the input of a command's eval / -c strings (review 7 M4)
        self.fail_hint = None  # review 9: the folders a command that may not run leaves, when its own are unknown
        self.forks = 0
        self.lost = []  # review 10 B1: known folders of a folder set that became unknown (note_lost)
        _lost_sink[0] = self.lost
        self.list_depth = 0
        # fix20: a `source` / `.` (or eval text that may run one) ran in this reading: the walk stops there — what
        # follows is judged by the 0.0.26 rules alone (backstop.decide). `ever_sourced`: in any reading (Scan.sourced)
        self.sourced = False
        self.ever_sourced = False
        self.emit_ok = False  # the command a builtin just ran (a `source` itself is judged) — emit()

    # ---- emission ----

    def new_id(self):
        self.ctx.next_id = getattr(self.ctx, "next_id", 0) + 1
        return self.ctx.next_id

    def emit(self, cmd):
        if self.dry:
            return
        if self.sourced and not self.emit_ok:
            cmd.flags.add("post-source")  # fix20: after a source in this reading — dropped by scan()
        if len(self.cmds) >= limits.MAX_COMMANDS:
            raise limits.LimitExceeded("commands")
        self.cmds.append(cmd)

    def emit_opaque(self, op, cmd=None):
        if self.dry:
            return
        if self.sourced and not self.emit_ok:
            op.post_source = True  # fix20: after a source in this reading — dropped by scan()
        if cmd is not None:
            op.cmd = cmd.id
            op.alt = cmd.alt
            if op.kind in INPUT_KINDS and getattr(op, "input", None) is None and cmd.id in self.input_ctx:
                op.input = self.command_input(cmd, *self.input_ctx[cmd.id])
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
        if name in TIED_NAMES and name not in ("PATH", "path"):
            # PS1 after PROMPT=…, $MANPATH after manpath=(…): one parameter under two names (review 5 M2)
            set_ = [n for n in TIED_NAMES[name] if n in state.vars]
            if set_ and set_ != [name]:
                v = state.vars[set_[0]] if len(set_) == 1 and TIED_NAMES[name][0].startswith(("PS", "RPS")) else DYN
                return None if v is DYN else v
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

    def expand(self, wn, state, cwds, assign=False, fngen=None):
        """WordNode -> [Word] (brace expansion may give several). Each Word also says how the shell may drop it
        (G1 §3): `drop` (an unquoted expansion known to be empty), `maybe_empty` (only unquoted expansions of unknown
        value) and `multi` (an expansion that may give several words or none). `fngen`: zsh generates file names from
        the word (argv, `for … in`, redirect targets; not assignments, `[[ ]]`, `case`, here-strings: review 4 conf
        M-1) — only there GLOB_SUBST makes a value a pattern whose qualifiers may run code."""
        if fngen is None:
            fngen = not assign
        if wn is None:
            return [Word.lit("")]
        segs = []  # (kind 'u'|'q'|'d', text, alt, dynkind)
        unq = []  # per segment: an unquoted expansion (the shell drops it when empty)
        opts = self.ctx.options

        qp = []  # review 6 M2: (text or None, the base value of a part of a parameter) per part, for qualifier_word
        seg_c = {}  # review 9: segment index -> (candidate values, exact) of a value the guard does not carry

        def cand(name, exact=True):
            c = state.cands.get(name) if name else None
            if not c and name == "OLDPWD" and "OLDPWD" not in state.vars and state.oldpwd is None:
                # review 17 (B17-1): $OLDPWD is `~-` — one of the folders a cd / pushd that may not have run left
                c = state.cands.get("~-")
            if not c and name in ("PWD", "~+") and cwds is None and name not in state.vars and self.lost:
                c = (tuple(self.lost[:MAX_CANDS]), True)  # review 10 B1: or one of the folders it may still be in
            if c and segs and segs[-1][0] == "d":
                seg_c[len(segs) - 1] = (c[0], c[1] and exact, exact and cands_complete(state, name))

        def known_split(v):
            vals = tuple(dict.fromkeys([v] + v.split()))[:MAX_CANDS]
            if segs and segs[-1][0] == "d" and len(segs) - 1 not in seg_c:
                seg_c[len(segs) - 1] = (vals, len(vals) == 1)

        def add(seg, unquoted=False):
            segs.append(seg)
            unq.append(unquoted)
            if seg[0] == "d":
                qp.append((None, None))
            else:
                qp.append((seg[1], None))
        for part in wn.parts:
            t = part[0]
            if t == "lit":
                add(("q" if part[2] else "u", part[1], None, None))
            elif t == "tilde":
                user = part[1]
                home = self.lookup("HOME", state, cwds)
                named = state.vars.get(user) if user and user not in state.named_dirs_unknown else None
                if user in ("+", "-"):
                    # zsh's own current and previous folder: an assignment to $PWD / $OLDPWD does not change them
                    # (checked in zsh 5.9; review 7 M5)
                    v = single(cwds) if user == "+" else state.oldpwd
                    if v is not None:
                        add(("q", v, None, None))
                    else:
                        add(("d", "~" + user, None, "tilde" + user))
                        cand("~" + user)  # review 9: one of the folders the shell may have left (review 10: or be in)
                elif re.match(r"^[+-]\d+$", user):
                    add(("d", "~" + user, None, "tilde-stack"))
                elif user.startswith("["):
                    # review 14 (B14-6): a dynamic named directory — zsh asks zsh_directory_name /
                    # zsh_directory_name_functions, which a sourced file, eval or this call may define: a folder the
                    # guard cannot tell (judge.tilde_rest)
                    add(("d", "~" + user, None, "tilde-dir"))
                elif user == "" and home is not None:
                    add(("q", home, None, None))
                elif user and user == self.ctx.env.get("USER") and home is not None:
                    add(("q", home, None, None))
                elif isinstance(named, str) and named.startswith("/") and not state.named_dirs_any:
                    add(("q", named, None, None))  # zsh: a parameter holding an absolute path names a folder (§1.8)
                else:
                    add(("d", "~" + user, None, "tilde-user" if user else "tilde"))
                    if user == "":
                        cand("HOME")  # review 10: $HOME may be one of these (an assignment that may not have run)
            elif t == "tildealt":
                home = self.lookup("HOME", state, cwds)
                add(("u", "~", home if home is not None else "\0", None))
            elif t == "rcq":
                add(("q", "", "'", None))
            elif t == "eqtilde":
                add(("u", "=~", "\0", None))
            elif t == "param":
                v = self.lookup(part[1], state, cwds)
                if fngen and not part[2] and self.option_maybe(state, "globsubst") is not False:
                    self.glob_qualifier("$" + part[1], state, cwds, globsubst=True)
                if part[1] in state.arrays and (v is None or part[1] in state.vars):
                    add(("d", "$" + part[1], None, "array:" + part[1]), not part[2])  # C-M3
                    cand(part[1])
                elif not part[2] and state.argv_opts_changed:
                    add(("d", "$" + part[1], None, "param-options"), True)
                    cand(part[1])
                    if v is not None:
                        known_split(v)  # review 10: options that may split or glob it — its known value stays judged
                elif v is None:
                    add(("d", "$" + part[1], None, "param:" + part[1]), not part[2])
                    cand(part[1])
                elif not part[2] and opts.get("shwordsplit") in (True, "both") and re.search(r"\s", v):
                    add(("d", "$" + part[1], None, "param:" + part[1]), True)
                    known_split(v)
                else:
                    add(("q", v, None, None), not part[2])
                if v is not None:  # its value, for qualifier_word (a known value split or not: review 6 M2)
                    qp[-1] = (None, v) if part[1] in state.arrays else (v, None)
            elif t == "dyn":
                if part[1] == "paramx":
                    self.paramx_forms(part[2], state, cwds)
                    if not part[3] and fngen:
                        self.glob_qualifier(part[2], state, cwds,
                                            globsubst=self.option_maybe(state, "globsubst") is not False)
                elif part[1] == "array":
                    # an array value's elements: their ${…} forms and substitutions (`a=("${(e)X}")`, `a=($(…))`:
                    # M8, review 2)
                    if "${" in part[2]:
                        self.paramx_forms(part[2], state, cwds)
                    for sub in (part[4] if len(part) > 4 else ()):
                        self.walk_subst(sub, state, cwds, "cmdsubst")
                elif part[1] in ("subscript", "modifier", "special") and fngen and not part[3] and \
                        self.option_maybe(state, "globsubst") is not False:
                    # $Z[1,-1], $Z:a, $1, $@: GLOB_SUBST makes them patterns too (review 5 M1)
                    self.glob_qualifier(part[2], state, cwds, globsubst=True)
                add(("d", part[2], None, part[1]), not part[3])
                if part[1] in ("subscript", "modifier", "special", "paramx"):
                    nm_, kd_ = _param_name(part[2])
                    if kd_ == "simple" and nm_ and not (part[1] == "special" and nm_ in ("#", "?", "$", "!", "-")):
                        # review 11 A1: only a plain $NAME / ${NAME} (and $1, $@, …) gives the value itself; a
                        # subscript, slice or modifier gives part of it — its candidates are loose (never exact)
                        bare = part[1] == "special" or (part[1] == "paramx" and re.match(
                            r"^\$\{[A-Za-z_0-9]+\}$", part[2] or ""))
                        # one element of an array (`$A[k]`, `${X[1]}`, `$X[@]`) is one of its values
                        msub = re.match(r"^\$\{?[A-Za-z_][A-Za-z0-9_]*\[(-?[A-Za-z0-9_]+|@|\*)\]\}?$",
                                        part[2] or "")
                        if msub and part[1] in ("subscript", "paramx") and nm_ in state.arrays:
                            bare = True
                        cand(nm_, exact=bool(bare))
                if part[1] in ("subscript", "modifier", "special", "paramx") and not part[3]:
                    nm, kd = _param_name(part[2])
                    qp[-1] = (None, self.lookup(nm, state, cwds) if nm and kd != "number" and
                              re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", nm) else None)
            elif t == "cmdsub":
                val = self.walk_subst(part[1], state, cwds, "cmdsubst")
                if val is not None and not (not part[3] and re.search(r"\s", val)):
                    add(("q", val, None, None), not part[3])
                else:
                    # unknown, or a known value the shell splits on blanks (unquoted): G1 §3
                    add(("d", part[2], None, "cmdsubst"), not part[3])
                    if cwds is None and self.lost:
                        # review 10 B1: $(pwd) / $(git rev-parse --show-toplevel) under an unknown folder: also each
                        # known folder the shell may still be in
                        vals = [x for x in (self.idiom(part[1], state, (c,)) for c in self.lost[:MAX_CANDS]) if x]
                        if vals:
                            seg_c[len(segs) - 1] = (tuple(dict.fromkeys(vals)), True)
            elif t == "arith":
                for sub in part[2]:
                    self.walk_subst(sub, state, cwds, "cmdsubst")
                self.arith_check(part[1], state, cwds)
                add(("d", "$((%s))" % part[1], None, "arith"), not part[3])
            elif t == "procsub":
                self.walk_subst(part[2], state, cwds, "procsubst")
                add(("d", part[3], None, "procsub"))
            elif t == "equals":
                p = self.which(part[1], state)
                if p:
                    add(("q", p, None, None))
                else:
                    add(("d", "=" + part[1], None, "equals"))
        if fngen and len(qp) > 1 and self.option_maybe(state, "globsubst") is not False:
            self.qualifier_word(wn.raw, qp, state, cwds)
        braces = {o: self.option_maybe(state, o) for o in BRACE_OPTIONS}
        ws = self.build_words(wn, segs, split=fngen, seg_cands=seg_c,
                              brace_unknown=(state.brace_opts_changed and state.options_unknown) or
                              None in braces.values() or bool(braces["shfileexpansion"] or
                                                               braces["ignoreclosebraces"]),
                              braceccl=bool(braces["braceccl"]), nobraces=bool(braces["ignorebraces"]), unq=unq,
                              globsubst=fngen and self.option_maybe(state, "globsubst") is not False,
                              extglob=self.option_maybe(state, "extendedglob") is not False)
        if any(w.glob for w in ws):
            # G1 §2: a `**` glob is expanded by listing the folders only when zsh runs the command with existing
            # matches alone (NOMATCH on, no null globs) and skips dot folders (GLOB_DOTS off)
            walk_ok = self.option_maybe(state, "nomatch") is True and all(
                self.option_maybe(state, o) is False for o in ("globdots", "nullglob", "cshnullglob"))
            extglob = self.option_maybe(state, "extendedglob") is not False
            gss = self.option_maybe(state, "globstarshort") is not False  # review 8 M3: `**x` is `**/*x`
            for w in ws:
                w.glob_walk, w.extglob, w.globstarshort = walk_ok, extglob, gss
        return ws

    def build_words(self, wn, segs, brace_unknown=False, unq=None, globsubst=False, extglob=False, braceccl=False,
                    nobraces=False, split=True, seg_cands=None):
        unq = unq if unq is not None else [False] * len(segs)
        template = []
        for i, s in enumerate(segs):
            template.append(s[1] if s[0] == "u" else chr(PUA + i))
        tpl = "".join(template)
        if brace_unknown and "{" in tpl:
            return [Word(wn.raw, None, dynamic=True, dyn=["brace-options"], skeleton="\0", quoted=True)]
        try:
            tpls = brace_expand(tpl, braceccl=braceccl) if "{" in tpl and not nobraces else [tpl]
        except BraceOverflow:
            return [Word(wn.raw, None, dynamic=True, dyn=["brace-overflow"], skeleton="\0", quoted=True)]
        glob_ch = GLOB_CH | EXTGLOB_CH if extglob else GLOB_CH
        words = []
        for t in tpls:
            value, skel, alt = [], [], []
            dyn, dynamic, glob, quoted, has_alt = [], False, False, False, False
            dcands = []  # review 9: per dynamic part, its candidates (or None)
            first_glob = None
            lit = False  # literal text (quoted or not) that keeps the word
            only_unq = True  # every part is an unquoted expansion
            empty_ok = True  # every known unquoted expansion is empty and every unknown one may be
            multi = False
            wild, vlen = set(), 0  # positions in value zsh may read as a pattern (review 4 conf M-2)
            for ch in t:
                o = ord(ch)
                if PUA <= o < PUA + len(segs):
                    k, text, a, dk = segs[o - PUA]
                    u = unq[o - PUA]
                    if k == "d":
                        dynamic = True
                        dyn.append(dk)
                        dcands.append((seg_cands or {}).get(o - PUA))
                        skel.append("\0")
                        alt.append("\0")
                        if u and (dk == "param-options" or globsubst or dk.startswith("array:")) or \
                                _multi_word(dk, text):
                            multi = True
                        if not u:
                            only_unq = False
                        elif not (dk.startswith("param:") or dk in MAYBE_EMPTY_KINDS):
                            empty_ok = False
                    else:
                        if not u:
                            quoted = True
                            lit = True
                            only_unq = False
                        else:
                            if text:
                                empty_ok = False
                            if globsubst:
                                multi = True
                                wild.update(range(vlen, vlen + len(text)))
                        value.append(text)
                        vlen += len(text)
                        skel.append(text)
                        alt.append(a if a is not None else text)
                        has_alt = has_alt or a is not None
                else:
                    lit = True
                    only_unq = False
                    wild.add(vlen)
                    value.append(ch)
                    vlen += 1
                    skel.append(ch)
                    alt.append(ch)
                    if ch in glob_ch and first_glob is None:
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
            w = Word(wn.raw, v, dynamic=dynamic, dyn=dyn, skeleton=sk, glob=glob, glob_base=gb,
                     quoted=quoted, alt=altv, plain=wn.plain)
            w.wild = frozenset(wild) if v is not None else None
            if v is None and any(dcands):
                w.cand_values, w.cand_loose = _cand_values(sk, dcands)
                # review 10: every part is one of a complete set of exact values (`if …; then v=1; else v=0; fi`)
                w.cand_complete = bool(w.cand_values) and all(dc and len(dc) > 2 and dc[1] and dc[2] for dc in dcands)
            w.drop = v == "" and only_unq and not lit and bool(t)
            w.maybe_empty = dynamic and only_unq and not lit and empty_ok
            w.multi = multi and split  # an assignment (`local v=$X`) is one word (review 4 conf M-1)
            words.append(w)
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
            if not isinstance(v, str):
                # review 14: a value that is one of several (an assignment after `&&` following a `source`): the
                # text it may hold, as written in the call
                v = state.raw_values.get(name) if name in state.vars else None
            if isinstance(v, str) and ("$(" in v or "`" in v):
                op = Opaque("arith-eval", payload=v, cwds=cwd_list(cwds))
                self.emit_opaque(op, cmd)

    # ---- lists ----

    def walk_list(self, lst, cwds, state):
        self.list_depth += 1
        try:
            return self._walk_list(lst, cwds, state)
        finally:
            self.list_depth -= 1

    def _walk_list(self, lst, cwds, state):
        cur = cwds
        last = (cwds, ())
        for idx, (ao, sep) in enumerate(lst.items):
            if sep == "&":
                self.push("background")
                try:
                    self.walk_and_or(ao, cur, state.copy())
                finally:
                    self.pop()
                last = (cur, ())
                continue
            self.fail_hint = None
            last = self.walk_and_or(ao, cur, state)
            nxt = union(last[0], last[1])
            hint, self.fail_hint = self.fail_hint, None
            if nxt is None and hint and idx + 1 < len(lst.items) and self.forks < MAX_FORKS:
                # review 9 B1: a command that moves to a folder the guard cannot tell may also not run (a redirection
                # that fails: `f > /x/y` where f cds): the rest is judged from the folders it would leave too
                self.forks += 1
                self.push("may-fail")
                rd = Readings(self)  # fix20 (P20-5): another reading of the rest — the main one is walked below
                try:
                    rd.start()
                    self.walk_list(ListNode(lst.items[idx + 1:]), hint, state.copy())
                    rd.end()
                finally:
                    self.pop()
                    self.forks -= 1
                    self.sourced = rd.flag0
            if nxt != ():
                cur = nxt
            if nxt and self.list_depth == 1 and not self.forks and not state.hook_cwd:
                del self.lost[:]  # review 10 B1: the shell is in a known folder again (the call's own list)
        return last

    def walk_and_or(self, ao, cwds, state):
        S, F = self.walk_pipeline(ao.first, cwds, state)
        # review 9 B1: `… && pushd x`, `… || popd` may not have run: a stack the rest of the list leaves changed is
        # unknown (`pushd x && make && popd` leaves it as it was; the first command always runs)
        mark = _stack_mark(state) if ao.rest else None
        out = self._walk_and_or_rest(ao, cwds, state, S, F)
        _stack_unsure(state, mark)
        return out

    def _walk_and_or_rest(self, ao, cwds, state, S, F):
        for op, pl in ao.rest:
            self.push("cond")
            vmark = ValueMark(state)  # review 10 B3: this part may not run — its values join the old ones
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
                value_unsure(self.ctx, state, vmark)
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
                saved = self.pipe_in
                if i > 0:
                    self.pipe_in = stdin  # `… | ( > /dev/null )`, `… | { sh }`: every command in it reads the pipe
                try:
                    o = self.walk_command(c, cwds, st, stdin)
                finally:
                    self.pipe_in = saved
                    self.pop()
                stdin = self.stdin_desc(self.last_top)
                if lastel:
                    out = o
            if self.option_maybe(state, "pipefail") is not False:
                out = (out[0], union(out[1], out[0]))  # review 8 B2: PIPEFAIL: an earlier command's failure is the status
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
        if self.sourced:
            return (cwds, cwds)  # fix20: after a `source` in this reading — the 0.0.26 rules judge it (not walked)
        self.ctx.budget.tick()
        if state.hook_cwd:
            note_lost(cwds)  # review 10 B1: or the hook did not move the shell
            cwds = None  # a hook that may change folder may have run before this command (review 4 m3, R1)
        if isinstance(node, Simple):
            # (a function, eval or source that may change folder leaves it unknown, as before: the folder it may not
            # have left is not judged on its own — options and values after them are unknown too)
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
        # review 6 M5: a compound command's redirections are opened before its body runs; every command in it reads
        # the input they give (`{ sh } <<< …`, `( zsh ) <<EOF`, `{ sh <&3 } 3<<<…`)
        redirs = [self.make_redir(r, state, cwds) for r in node.redirs] if getattr(node, "redirs", None) else []
        saved_in, saved_fds = self.pipe_in, state.fds
        if redirs:
            cur = self.pipe_in if self.pipe_in is not None else state.fds.get("0")
            self.pipe_in, fds = self.redirect_fds(redirs, cur, state, cwds)
            state.fds = dict(fds, **({"0": self.pipe_in} if self.pipe_in is not None else {}))
        mark = _stack_mark(state)
        vmark = ValueMark(state)
        try:
            out = self._walk_compound(node, k, cwds, state, out)
        finally:
            self.pipe_in = saved_in
            if redirs:
                state.fds = saved_fds
        if k in ("for", "while"):
            value_unsure(self.ctx, state, vmark)  # review 10 B3: a loop body may not run
        if k != "funcdef" and any(redirect_may_fail(r) for r in node.redirs):
            out = (out[0], union(out[1], cwds))  # review 8 B2: `{ … } > /bad`, `if …; fi > /bad`: the body does not run
            _stack_unsure(state, mark)
            value_unsure(self.ctx, state, vmark)  # review 10 B3
            if out[0] is None and cwds:
                self.fail_hint = tuple(cwds)
        elif k in ("if", "case", "for", "while"):
            _stack_unsure(state, mark)  # review 9 B1: a branch or a loop body that may not run moved the stack
        if redirs:
            cmd = Cmd(self.new_id(), [], cwd_list(cwds), ctx=self.labels + ["compound-redirect"],
                      span=(node.start, node.start))
            cmd.redirs = redirs
            self.emit(cmd)
        return out

    def _walk_compound(self, node, k, cwds, state, out):
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
            # review 10 B3: each body starts from the values the conditions left; afterwards a value changed on any way
            # through holds one of the values the ways give
            vmark, ends = ValueMark(state), []
            for cond, body in node.clauses:
                self.push("cond")
                try:
                    S, F = self.walk_list(cond, cur, state)
                    bmark = ValueMark(state)
                    results.append(self.walk_list(body, S if S != () else cur, state))
                    ends.append(ValueMark(state))
                    value_restore(state, bmark)
                finally:
                    self.pop()
                cur = F if F != () else cur
            if node.else_body is not None:
                self.push("cond")
                try:
                    bmark = ValueMark(state)
                    results.append(self.walk_list(node.else_body, cur, state))
                    ends.append(ValueMark(state))
                    value_restore(state, bmark)
                finally:
                    self.pop()
            else:
                results.append((cur, ()))
                ends.append(ValueMark(state))  # no body ran
            value_join(self.ctx, state, vmark, ends)
            S = F = ()
            for s, f in results:
                S, F = union(S, s), union(F, f)
            out = (S, F)
        elif k in ("for", "while"):
            if k == "for":
                items = []
                if node.items is not None:
                    for wn in node.items:
                        items.extend(self.expand(wn, state, cwds))
                for sub in node.subs:
                    self.walk_subst(sub, state, cwds, "cmdsubst")
                names = getattr(node, "vars", None) or ([node.var] if node.var else [])
                for vname in names:  # `for i j in …` (review 7 R3)
                    one = items[0].value if len(items) == 1 and not node.subs and not items[0].glob and \
                        not items[0].multi and k == "for" and node.items is not None and len(names) == 1 else None
                    self.param_written(state, vname, "for", cwds, raw=" ".join(wn.raw for wn in node.items or ()),
                                       value=one)  # for/select NAME (G1 §1.9, M6; review 6 M11: its value)
                    if node.items is not None and not node.subs and all(_safe_literal(w) for w in items):
                        state.safe_values.add(vname)  # `for i in 1 2 3`: known values (review 4 conf M-1)
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
            self.expand(node.word, state, cwds, fngen=False)
            S, F = cwds, ()
            self.push("cond")
            ends = getattr(node, "ends", None) or [";;"] * len(node.arms)
            start = cwds
            vmark, vends = ValueMark(state), [ValueMark(state)]  # review 10 B3: no arm may match
            try:
                for (pats, body), end in zip(node.arms, ends):
                    for p in pats:
                        self.expand(p, state, cwds, fngen=False)
                    bmark = ValueMark(state)
                    s, f = self.walk_list(body, start, state)
                    S, F = union(S, s), union(F, f)
                    vends.append(ValueMark(state))
                    if end not in (";&", ";|"):
                        value_restore(state, bmark)  # the next arm starts from the values before this one
                    # `;&` runs the next body, `;|` tests the next patterns: from where this body left the shell too
                    start = union(cwds, union(s, f)) if end in (";&", ";|") else cwds
            finally:
                self.pop()
            vends.append(ValueMark(state))
            value_join(self.ctx, state, vmark, vends)
            out = (S, F)
        elif k == "funcdef":
            eff = self.function_effects(node.body, cwds, state)
            names_ = getattr(node, "names", None) or [node.name]
            if any(not re.match(r"^[^\s$`'\"\\*?\[\]{}()<>|&;~=#^]+$", n or "") for n in names_):
                # review 11 B1: a name the guard cannot read (`$n(){ … }`) may replace any function of this call
                funcs_unknown(state)
                state.defs_unknown = True
            for name in names_:  # `function a b { … }` (review 5 M4)
                state.funcs[name] = eff
                self.ctx.inline_functions.add(name)
                # chpwd, TRAPDEBUG, …: zsh runs it after later commands (review 4 R1); a name an active trap runs
                self.define_hook(state, name, eff)
            state.defs_maybe = True  # snapshot functions may now run it (review 4 B3)
            self.push("function-body")
            self.func_depth += 1
            # fix20: a source in a body defined here stops the walk only where the function is called
            flags0 = (self.sourced, self.ever_sourced)
            try:
                self.walk_command(node.body, cwds, state.copy(), None)
            finally:
                self.pop()
                self.func_depth -= 1
                self.sourced, self.ever_sourced = flags0
            out = (cwds, ())
        elif k == "dbracket":
            prev = None
            for w in node.words:
                if isinstance(w, WordNode):
                    words = self.expand(w, state, cwds, fngen=False)
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
        return out

    def changes_cwd(self, node, cwds, state):
        """Whether one pass of a loop body may change the cwd (dry run)."""
        self.dry += 1
        try:
            st = state.copy()
            res = None
            if node.kind == "while":
                # review 4 R3: a cd in the condition (`while cd x`, `until cd x`) moves the shell too
                c = self.walk_list(node.cond, cwds, st)
                ca = union(c[0], c[1])
                if ca is None or set(ca) - set(cwds or ()):
                    return True
            res = self.walk_list(node.body, cwds, st)
        finally:
            self.dry -= 1
        after = union(res[0], res[1])
        return after is None or set(after) - set(cwds or ()) != set()

    def function_effects(self, body, cwds, state):
        """What calling a function defined in this command may change: {"cwd": bool, "options": bool}.
        Options set without `emulate -L` / localoptions leak to the caller (zsh)."""
        self.dry += 1
        self.func_depth += 1
        st = state.copy()
        try:
            res = self.walk_command(body, cwds, st, None)
        finally:
            self.dry -= 1
            self.func_depth -= 1
        after = union(res[0], res[1])
        cwd = after is None or (cwds is not None and set(after) - set(cwds) != set())
        local = bool(st.opts.get("localoptions"))
        opts = not local and (st.opts != state.opts or st.argv_opts_changed != state.argv_opts_changed
                              or st.brace_opts_changed != state.brace_opts_changed)
        # review 5 R2: what the body exports or assigns for the caller, as for snapshot functions (values unknown:
        # they may depend on the call's words); `local` names count too (fail closed)
        new_ops = st.env_ops[len(state.env_ops):] if st.env_ops[:len(state.env_ops)] == state.env_ops else None
        env = new_ops is None or (st.env_unknown and not state.env_unknown) or (st.allexport and not state.allexport) \
            or any(op.kind in ("unknown", "clear") for op in new_ops)
        names = {op.name.split("[")[0] for op in new_ops or () if op.name}
        names |= {n for n, v in st.vars.items() if n not in state.vars or state.vars[n] is not v}
        names |= {n for n in _changed_names(ValueMark(state), st)}
        # review 10 B2: a name the body declares local before any write (`local X=a`) is the function's own — the
        # caller's value is back after the call; a write that may not run (a branch, a loop, after `return`, a name
        # also declared local somewhere) leaves the caller's value possible too (`maybe`, joined at the call)
        uncond, local_first, local_any = _fn_body_scan(body)
        names -= local_first
        maybe = {n for n in names if n not in uncond or n in local_any}
        # a value the body assigns from literal text only (`f(){ X=studio; }`) is known after the call
        known = {n: st.vars[n] for n in names if n not in maybe and isinstance(st.vars.get(n), str) and
                 n in st.raw_values and not re.search(r"[$`]", st.raw_values[n] or "")}
        # review 9: the candidates of a value the body writes (`f(){ X=(studio) }`)
        cands = {n: st.cands[n] for n in names if n not in known and n not in maybe and st.cands.get(n)}
        # review 6 M9: functions the body defines exist after a call
        funcs = {n: e for n, e in st.funcs.items() if state.funcs.get(n) is not e}
        return {"cwd": cwd, "options": opts, "env": env, "globals": names, "known": known, "cands": cands,
                "maybe": maybe, "end": ValueMark(st), "hook": st.hook_cwd and not state.hook_cwd,
                "unknown": maybe & local_any,
                "texts": {n: [(v.raw or "") for sc in _iter_simple(body) for nm, _s, _o, v, _w in sc.assigns
                              if nm == n and v is not None] for n in maybe & local_any},
                "paths": st.path_modified and (st.paths != state.paths or not state.path_modified),
                "body": body, "funcs": funcs, "tables": st.tables_changed and not state.tables_changed,
                "fntable": body_touches_funcs(body, state),
                "defs": (st.defs_maybe and not state.defs_maybe) or bool(funcs)}

    # ---- simple commands ----

    def walk_simple(self, node, cwds, state, stdin):
        if cwds is not None and len(cwds) > 1 and FOLDER_REF_RE.search(_simple_text(node)):
            # review 9 B1: $PWD, ~+, $(pwd), `git rev-parse --show-toplevel` after a folder change that may or may not
            # happen: the command is walked once in each folder it may run in (each folder one possible value)
            outs, copies = [], []
            rd = Readings(self)
            for i, c in enumerate(cwds):
                last = i == len(cwds) - 1
                st = state if last else state.copy()
                rd.start()
                outs.append(self._walk_simple_fail(node, (c,), st, stdin))
                rd.end()
                if not last:
                    copies.append(st)
            rd.done()
            merge_states(state, copies, self.ctx)
            S = F = ()
            for s_, f_ in outs:
                S, F = union(S, s_), union(F, f_)
            return (S, F)
        lost = self.lost
        if cwds is None and lost:
            # review 10 B1 (the union rule): the folder is unknown, but the shell may still be in one of the known
            # folders it was in when it became so (a cd that may fail, a hook that may not move it): the command is
            # judged in each of those as well as in a folder the guard cannot tell
            folders = tuple(lost[:limits.MAX_CWDS])
            copies = [state.copy() for _c in folders]
            rd = Readings(self)
            rd.start()
            outs = [self._walk_simple_fail(node, None, state, stdin)]
            rd.end()
            top = self.last_top
            self.push("lost-folder")
            try:
                for c, st in zip(folders, copies):
                    rd.start()
                    outs.append(self._walk_simple_fail(node, (c,), st, stdin))
                    rd.end()
            finally:
                self.pop()
                rd.done()
            self.last_top = top
            merge_states(state, copies, self.ctx)
            S = F = ()
            for s_, f_ in outs:
                S, F = union(S, s_), union(F, f_)
            return (S, F)
        return self._walk_simple_fail(node, cwds, state, stdin)

    def _walk_simple_fail(self, node, cwds, state, stdin):
        may_fail = any(redirect_may_fail(r) for r in node.redirs)
        before = _stack_mark(state) if may_fail else None
        vmark = ValueMark(state) if may_fail else None
        out = self._walk_simple(node, cwds, state, stdin)
        if may_fail:
            # review 8 B2: a redirection that fails skips the command (a `cd` does not move, `true` / `exit` fail)
            out = (out[0], union(out[1], cwds))
            _stack_unsure(state, before)  # review 9 B1: a pushd / cd that may not have run
            value_unsure(self.ctx, state, vmark)  # review 10 B3: `read X < /bad`, `print -v X a > /bad`
            if out[0] is None and cwds:
                self.fail_hint = tuple(cwds)
        return out

    def _walk_simple(self, node, cwds, state, stdin):
        if stdin is None:
            stdin = self.pipe_in
        if stdin is None:
            stdin = state.fds.get("0")  # `exec <<< …` (review 6 M7)
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
            if valnode is not None and (valnode.raw or "").startswith("("):
                self.array_qualifiers(valnode.raw, state, cwds)  # array elements: file names are generated
            assigns.append((name, sub, op, val, valnode))
        words = []
        # typeset/local/export NAME=value: an assignment (no file names generated; review 4 conf M-1)
        decl = bool(node.words) and node.words[0].raw in cmdopts.TYPESET
        for wn in node.words:
            dm = decl and wn is not node.words[0] and DECL_ASSIGN_RE.match(wn.raw or "")
            words.extend(self.expand(wn, state, cwds, fngen=not dm))
            if dm and (wn.raw or "")[dm.end():].startswith("("):
                # typeset -a W=($Z): array elements are file-name generated, as in W=($Z) (review 5 M3)
                self.array_qualifiers(wn.raw[dm.end():], state, cwds)
        redirs = [self.make_redir(r, state, cwds) for r in node.redirs]
        for name, sub, op, val, valnode in assigns:
            self.assign_forms(state, name, sub, op, val, valnode, cwds)
        kept = words  # today's reading: every word kept (G1 §3: judged too, so no deny is lost)
        words = [w for w in words if not w.drop]
        if not words and not kept:
            for name, sub, op, val, valnode in assigns:
                self.set_var(state, name, sub, op, val, valnode, "assign")
            if redirs:
                cmd = Cmd(self.new_id(), [], cwd_list(cwds), ctx=self.labels, span=(node.start, node.end))
                cmd.redirs = redirs
                cmd.alt, cmd.aliases = alt, aliases
                cmd.env = EnvView(state.env_ops)
                self.emit(cmd)
                self.last_top = cmd
                if not assigns:  # `NULLCMD=sh > f` is an assignment: no command runs (review 5 M5)
                    self.null_command(cmd, cwds, state, stdin)
            return (cwds, cwds)
        prefix = []
        for name, sub, op, val, valnode in assigns:
            prefix.append(EnvOp("prefix", "set", name + sub, val))

        rd = Readings(self)  # fix20 (P20-5): each reading of the command starts from the flag before it

        def run(ws, base, alt_=alt, flags=(), dropped=None):
            rd.start()
            try:
                return _run(ws, base, alt_, flags, dropped)
            finally:
                rd.end()

        def _run(ws, base, alt_=alt, flags=(), dropped=None):
            st = base
            local_paths = None
            for name, sub, op, val, valnode in assigns:
                if name == "PATH":
                    local_paths = [val.value] if val.value is not None else None
            if local_paths is not None or any(n == "PATH" for n, _, _, _, _ in assigns):
                st = base.copy()
                st.paths = local_paths
                st.path_modified = True
            if not ws:
                # every word dropped: zsh runs no command, the assignments stay in this shell
                for name, sub, op, val, valnode in assigns:
                    self.set_var(base, name, sub, op, val, valnode, "assign")
                return (cwds, cwds)
            return self.process(ws, cwds, st, prefix, redirs, stdin, alt=alt_, aliases=aliases,
                                span=(node.start, node.end), outer_state=base, extra_flags=flags, dropped=dropped)

        self.choice_capped = False
        readings = self.choice_readings(words, kept, state)
        capped, self.choice_capped = self.choice_capped, False
        if readings is not None:
            # review 11 M-1: a word that is one of several known values (`if …; then B=main; else B=develop; fi;
            # git checkout $B`, `cd $D`): the command is walked once per combination, each judged as written —
            # all must pass; the folders and values after it are those of every reading
            outs, copies = [], []
            for i, ws in enumerate(readings):
                last = i == len(readings) - 1
                st = state if last else state.copy()
                a = dict(alt or {}, group="choice", index=str(i)) if alt else {"group": "choice", "index": str(i)}
                outs.append(run(ws, st, alt_=a))
                if not last:
                    copies.append(st)
            merge_states(state, copies, self.ctx)
            S = F = ()
            for s_, f_ in outs:
                S, F = union(S, s_), union(F, f_)
            return (S, F)
        maybe = [i for i, w in enumerate(words) if w.maybe_empty]
        multi = any(w.multi for w in words)
        if len(kept) == len(words) and not maybe and not multi:
            return run(words, state)
        # G1 §3: words the shell may drop. The program decides whether the readings matter: one whose words keep
        # their meaning wherever they stand is judged on the no-drop reading only.
        # (both readings: `X=; env -C $X -Z rm …` runs rm once X is dropped, but the every-word reading is a refused
        # runner — a deny of today's reading is not lost)
        if words and self.exempt_program(words, cwds, state, prefix, redirs, stdin, alt, aliases, node, assigns) and \
                (len(kept) == len(words) or self.exempt_program(kept, cwds, state, prefix, redirs, stdin, alt, aliases,
                                                                node, assigns)):
            return run(words, state)
        out_list = []
        if multi or len(maybe) > MAX_EMPTY_WORDS:
            out_list.append(run(words, state, flags=("argv-unknown", "argv-choices") if capped else ("argv-unknown",)))
            top = self.last_top
        else:
            subsets = sorted(range(1, 1 << len(maybe)), key=lambda b: (-bin(b).count("1"), b))
            for bits in subsets:
                drop = {maybe[k] for k in range(len(maybe)) if bits >> k & 1}
                ws = [w for i, w in enumerate(words) if i not in drop]
                before = {id(words[i - 1]) for i in drop if i > 0} | (_dropped_before(kept) or set())
                a = dict(alt or {}, group=(alt or {}).get("group", "maybe-empty"), empty=bits) if alt else \
                    {"group": "maybe-empty", "index": bits}
                out_list.append(run(ws, state.copy(), alt_=a, dropped=before))
            out_list.append(run(words, state, dropped=_dropped_before(kept)))
            top = self.last_top
        if len(kept) != len(words):
            a = dict(alt or {}, group=(alt or {}).get("group", "maybe-empty"), empty="kept") if alt else \
                {"group": "maybe-empty", "index": "kept"}
            out_list.append(run(kept, state.copy(), alt_=a))
        self.last_top = top
        if all(o == out_list[0] for o in out_list):
            return out_list[0]
        return (None, None)  # the readings move to different folders: unknown (as for alias alternatives)

    def choice_readings(self, words, kept, state):
        """review 11 M-1, A1/A2: the argv of each reading when words are each one of a complete set of known values
        (none empty, none with a blank, a wildcard, a quote or other shell characters), with GLOB_SUBST and
        SH_WORD_SPLIT off and no other word that may be dropped or split — at most MAX_CHOICE_READINGS; else None."""
        idx = [i for i, w in enumerate(words) if w.value is None and getattr(w, "cand_complete", False) and
               w.cand_values]
        if not idx or len(kept) != len(words):
            return None
        if any((w.maybe_empty or w.multi) and i not in idx for i, w in enumerate(words)):
            return None
        if any(words[i].glob or any(v == "" or CHOICE_BAD_RE.search(v) for v in words[i].cand_values) for i in idx):
            return None
        # only parameters the command assigns: not $PWD/$OLDPWD (a `cd` changes them), `~+`, `$(…)`, `$((…))`
        for i in idx:
            w = words[i]
            if any(not (d.startswith(("param:", "array:")) or d in ("paramx", "subscript", "special")) for d in w.dyn) \
                    or CHOICE_SHELL_RE.search(w.raw or ""):
                return None
        if self.option_maybe(state, "globsubst") is not False or self.option_maybe(state, "shwordsplit") is not False:
            return None
        n = 1
        for i in idx:
            n *= len(words[i].cand_values)
            if n > MAX_CHOICE_READINGS:
                self.choice_capped = True  # review 12 conf m-3: refused with its own message
                return None
        out = [list(words)]
        for i in idx:
            nxt = []
            for ws in out:
                for v in words[i].cand_values:
                    w = _choice_word(words[i], v)
                    nxt.append(ws[:i] + [w] + ws[i + 1:])
            out = nxt
        return out

    def null_command(self, cmd, cwds, state, stdin):
        """review 4 R4: a command of redirections only runs $NULLCMD (cat) or, with one input redirection,
        $READNULLCMD (a pager) on that input; set to anything else (`NULLCMD=sh`) it may run the input as code —
        the input is then scanned like `sh <<< …`."""
        if self.effective_stdin(cmd.redirs, stdin, state, cwds) is None:
            return  # no input: the Bash tool's stdin is /dev/null (review 5 M5: a pipe is input, too)
        for name in ("NULLCMD", "READNULLCMD"):
            v = self.lookup(name, state, cwds)
            if (v is None and (name in state.vars or state.env_unknown)) or (v is not None and
                                                                             v not in NULLCMD_OK):
                text, origin, _kind = self.stdin_payload(cmd, stdin, state)
                dyn = any(r.body_dynamic for r in cmd.redirs if r.mode in ("heredoc", "herestring"))
                op = Opaque("shell-c", payload=text, origin="dynamic" if dyn or text is None else "literal",
                            cwds=cwd_list(cwds))
                op.skeleton = text
                self.emit_opaque(op, cmd)
                return

    def exempt_program(self, words, cwds, state, prefix, redirs, stdin, alt, aliases, node, assigns):
        """Whether the no-drop reading runs a program whose words keep their meaning wherever they stand (READ_ALLOW
        programs but those that write, and rm, rmdir, unlink, touch, mkdir, chmod, trash; G1 §3): a dry run."""
        saved, self.capture = self.capture, [None]
        self.dry += 1
        try:
            st = state.copy()
            self.process(words, cwds, st, prefix, redirs, stdin, alt=alt, aliases=aliases,
                         span=(node.start, node.end), outer_state=st)
        finally:
            self.dry -= 1
            cap, self.capture = self.capture[0], saved  # nested: a function body walked from the call (review 8)
        if cap is None or not cap.words or cap.words[0].value is None:
            return False
        return recog.key(cap.prog or "") in EMPTY_EXEMPT and "runner-unread" not in cap.flags

    def assign_forms(self, state, name, sub, op, val, valnode, cwds):
        """G1 §1.8 and §1.9 effects of an assignment: zsh's tables, the prompt, command-valued variables."""
        if cmdopts.TABLE_RE.match(name + (sub or "")):
            key = sub[1:-1] if sub and sub.startswith("[") and sub.endswith("]") else None
            names = [key] if name in ("commands", "functions", "aliases", "builtins") and key and \
                "$" not in key else []
            self.table_write(state, "%s%s%s" % (name, sub or "", op), cwds, names=names)
        if name == "functions" and sub:
            # functions[NAME]=TEXT defines a function: its text is code, read like an eval string (review 4 fix)
            op_ = Opaque("eval", payload=val.value, origin="literal" if val.value is not None else "dynamic",
                         cwds=cwd_list(cwds))
            op_.skeleton = val.value if val.value is not None else val.skeleton
            self.emit_opaque(op_)
        if name == "PS4" and self.option_maybe(state, "promptsubst") is not False:
            self.emit_opaque(Opaque("prompt-subst", payload="PS4", cwds=cwd_list(cwds)))
        if name in cmdopts.CMD_VARS:
            self.var_set(state, name, val.value if not sub else None,  # NAME[1,-1]=…: a part of it (M6)
                         val.value if val.value is not None else val.skeleton, cwds)

    def var_set(self, state, name, value, skeleton, cwds, cmd=None):
        """G1 §1.9: a command-valued variable set in the call. An allowed value (GIT_PAGER=cat, EDITOR=vi with PATH
        unchanged) emits nothing, so every consumer (judge, auditor) reads it alike (review 5 conf M-1)."""
        if not cmdopts.var_problem(name, value, state.path_modified):
            return
        op_ = Opaque("var-set", payload=name, cwds=cwd_list(cwds))
        op_.value, op_.path_modified = value, state.path_modified
        op_.skeleton = skeleton  # searched (review 2, m-a)
        self.emit_opaque(op_, cmd)

    def set_cands(self, state, name, text, cwds, exclude=()):
        """review 9: a value the guard does not carry, written from `text`: its candidates (text_cands)."""
        if text is None:
            state.cands.pop(name, None)
            return
        vals, exact = text_cands(text, state, lambda n: self.lookup(n, state, cwds), exclude=exclude)
        if vals:
            state.cands[name] = (vals, exact)
        else:
            state.cands.pop(name, None)

    def set_var(self, state, name, sub, op, val, valnode, via):
        raw_val = valnode.raw if valnode is not None else ""
        state.safe_values.discard(name)
        if val.value is not None and not sub and op == "=":
            state.cands.pop(name, None)
        else:
            src = raw_val if valnode is not None else (val.raw.partition("=")[2] if "=" in (val.raw or "") else
                                                       val.raw)
            old = state.cands.get(name) if (sub or op == "+=") else None
            if sub and old is None and isinstance(state.vars.get(name), str):
                old = ((state.vars[name],), True)  # review 10: `X[1]=s` may leave the value as it was
            self.set_cands(state, name, src, None)
            wc = tuple(getattr(val, "cand_values", ()) or ())
            if wc and not sub and op == "=":
                # review 10: the values the assigned word may have (`X=~/studio` while $HOME is one of several)
                cur = state.cands.get(name, ((), True))
                state.cands[name] = (tuple(dict.fromkeys(wc + tuple(cur[0])))[:MAX_CANDS], cur[1])
                tg = _oldpwd_targets(val, state)
                if tg:
                    # review 17 (B17-1): `X=$OLDPWD` while $OLDPWD is one of several folders: exactly one of them
                    # (`cd $X` is then judged as `cd -`, _oldpwd_targets)
                    state.cands[name] = (tuple(tg), True)
                    state.complete[name] = (state.cands[name], "oldpwd")
            if old:  # NAME[i]=…, NAME+=…: the old candidates stay possible
                new = state.cands.get(name, ((), True))
                state.cands[name] = (tuple(dict.fromkeys(old[0] + new[0]))[:MAX_CANDS], False)
        state.raw_values[name] = raw_val if val.value is None else val.value
        if not sub and op == "=" and raw_val.startswith("(") and SAFE_ARRAY_RE.match(raw_val):
            state.safe_values.add(name)  # arr=(a b): known elements with no qualifier (review 4 conf M-1)
        if name in HOOK_ARRAYS:
            self.hook_array(state, name)  # chpwd_functions=(…): functions zsh runs after a cd, … (review 4 R1)
        if not sub:
            if raw_val.startswith("("):
                state.arrays.add(name)  # name=(…): an array (C-M3)
            elif op == "=":
                state.arrays.discard(name)
        if sub:
            state.vars[name] = DYN
            if cmdopts.watched_var(name):  # NAME[1,-1]=…: the variable's new value is unknown (M6)
                state.env_ops.append(EnvOp(via, "set", name, _unknown_value(name)))
        elif op == "+=":
            old = state.vars.get(name, self.ctx.env.get(name))
            state.vars[name] = old + val.value if isinstance(old, str) and val.value is not None else DYN
        else:
            state.vars[name] = val.value if val.value is not None else DYN
        state.env_ops.append(EnvOp(via, "set", name + sub, val))
        if name == "argv":
            _positionals_moved(state)  # `argv=(…)`, `argv[2]=…`: every $N may change (review 7 M3)
        if name in ("PATH", "path"):
            state.path_modified = True
            if name == "PATH" and not sub and op == "=" and val.value is not None:
                state.paths = [val.value]
            elif name == "path" and not sub and raw_val.startswith("("):
                state.paths = self.path_array(raw_val, state, op)
            else:
                state.paths = None
        if name == "dirstack":
            state.dirstack = None  # `dirstack=(…)`: zsh's stack; its folders are not followed (review 9: popd)
        if name in ("CDPATH", "cdpath"):
            state.cdpath = not (val.value == "" or raw_val in ("()", ""))
        if name == "fpath":
            state.fpath_changed = True
            self.note("fpath-changed")
        if name == "IFS":
            self.note("ifs-changed")
        if name == "options":
            state.opts["posixbuiltins"] = None  # options[…]=…: any option may change (G1 §1.3)

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
                ws = self.expand(wn, state, cwds, fngen=False)
                if ws and ws[0].value is not None:
                    body = ws[0].value
                elif ws:
                    body = ws[0].skeleton.replace("\0", "")
                    dynamic = True
            return Redir(r.fd, op, "heredoc", target=None, body=body, body_dynamic=dynamic)
        if getattr(r, "dup", None) is not None:
            return Redir(r.fd, op, "close" if r.dup == "-" else "dup", target=Word.lit(r.dup))
        tw = self.expand(r.target, state, cwds, fngen=op != "<<<")
        target = tw[0] if len(tw) == 1 else Word(r.target.raw, None, dynamic=True, dyn=["brace"], skeleton="\0")
        if op == "<<<":
            return Redir(r.fd, op, "herestring", target=target, body=(target.value if target.value is not None
                                                                     else target.skeleton) + "\n",
                         body_dynamic=target.dynamic)
        mode = {"<": "read", "<>": "rw", "<&": "read"}.get(op)
        if mode is None:
            mode = "append" if ">>" in op else "write"  # `>>&|`, `&>>!` (review 8 M1)
        return Redir(r.fd, op, mode, target=target)

    # ---- one command (after expansion) ----

    def process(self, words, cwds, state, prefix_ops, redirs, stdin, alt=None, aliases=(), span=(0, 0),
                via_program=False, parent=None, extra_ctx=(), lock_depth=0, outer_state=None, extra_flags=(),
                dropped=None):
        """`extra_flags`: flags of the reading (argv-unknown); `dropped`: ids of the words right before a word the
        shell drops in this reading (G1 §3, the §1.2 rule for option values)."""
        outer = outer_state or state
        cmd = Cmd(self.new_id(), words, cwd_list(cwds), ctx=self.labels + list(extra_ctx), parent=parent, span=span)
        cmd.flags |= set(extra_flags)
        if cwds is None and getattr(outer, "glob_cwd", None):
            cmd.glob_folders = [outer.glob_cwd]  # after `cd <wildcard>` (M12)
        if self.capture is not None and self.capture[0] is None:
            self.capture[0] = cmd
        cmd.alt, cmd.aliases = alt, list(aliases)
        cmd.redirs = redirs
        self.input_ctx[cmd.id] = (stdin if stdin is not None else (self.pipe_in if self.pipe_in is not None else
                                                                   state.fds.get("0")), state)
        env_ops = list(state.env_ops) + list(prefix_ops)
        if state.env_unknown:
            env_ops.append(EnvOp("code", "unknown"))
        by_shell = not via_program
        bypass_func = via_program
        wrappers = []
        i = 0
        query = False
        run = None  # run folders after env -C / sudo -D (None: the command's own)
        deferred = []
        path_mod = False
        command_wrapped = False  # the `command` builtin: zsh without POSIX_BUILTINS then runs only external commands
        unread = None  # why a runner (the program) cannot be read
        unread_at = None  # (spec, index) of a runner whose options were refused
        shell_op = None  # a runner whose payload is a shell string (the runner is the program)
        run_words = []  # run-folder words the guard cannot read (env -C $D): searched for Studio repositories (§1.7a)
        while i < len(words):
            v = words[i].value
            if v is None:
                break
            name = recog.base(v)
            key = recog.key(name)
            exact = by_shell and "/" not in v
            spec = runners.lookup(key)
            if len(wrappers) >= limits.MAX_WRAPPERS:
                if spec is not None or key in runners.REFUSED or key in PRECOMMANDS:
                    unread = "more than %d wrappers" % limits.MAX_WRAPPERS
                break
            if key in PRECOMMANDS and not (exact and name == key):
                if key != "command":
                    unread = "%s is not zsh's precommand (another case, a path or run by a program)" % v
                    break
            if exact and name == "builtin":
                wrappers.append(Wrapper("builtin", []))
                bypass_func = True
                i += 1
                continue
            if key == "command":
                # exact and run by the shell: the builtin (functions bypassed); a path or another case is the external
                # `command` (/usr/bin/command, COMMAND on APFS): the same options, run by a program
                j = i + 1
                while j < len(words) and words[j].value and words[j].value.startswith("-") and \
                        words[j].value not in ("--", "-"):
                    if not re.fullmatch(r"-[pvV]+", words[j].value):
                        unread = "command %s (options are p, v and V)" % words[j].value
                        break
                    if "v" in words[j].value or "V" in words[j].value:
                        query = True
                    j += 1
                if unread:
                    break
                if j < len(words) and words[j].value == "--":
                    j += 1
                if query:
                    break
                wrappers.append(Wrapper("command", words[i + 1:j]))
                if exact and name == "command":
                    bypass_func = True
                    command_wrapped = True
                else:
                    by_shell = False
                i = j
                continue
            if exact and name == "exec":
                j = i + 1
                eff = "none"
                while j < len(words) and words[j].value and words[j].value.startswith("-") and words[j].value != "-":
                    o = words[j].value
                    if o == "--":
                        j += 1
                        break
                    took = 0
                    for c, ch in enumerate(o[1:], 1):
                        if ch == "c":
                            eff = "env-clear"
                            env_ops.append(EnvOp("exec", "clear"))
                        elif ch == "a":
                            took = 0 if o[c + 1:] else 1  # -a NAME, -aNAME, -cla NAME
                            break
                        elif ch != "l":
                            unread = "exec %s (options are c, l and a NAME)" % o
                            break
                    if unread:
                        break
                    j += 1 + took
                if unread:
                    break
                wrappers.append(Wrapper("exec", words[i + 1:j], eff))
                outer.after_exec = True
                bypass_func = True
                i = j
                continue
            if exact and name in ("noglob", "nocorrect", "-"):
                wrappers.append(Wrapper(name, []))
                i += 1
                continue
            if spec is None:
                if key in runners.REFUSED:
                    unread = runners.refused_reason(key, words[i + 1:])
                break
            base_run = run if run is not None else cwd_list(cwds)
            p = runners.parse(spec, words, i + 1, isdir=lambda val, b=base_run: self.runner_isdir(val, b))
            if p.outcome == "refused":
                unread = "%s: %s" % (spec.name, p.reason)
                unread_at = (spec, i)
                break
            if p.chdirs:
                # the last -C/-D of one runner is its folder (M1); a word the guard cannot read: unknown (M3, §1.7a)
                # a wildcard folder is unknown too (zsh expands it; M12), its text searched like a dynamic word's
                d = p.chdirs[-1]
                tg = _oldpwd_targets(d, outer) if d.value is None and not d.glob else None
                if tg:
                    # review 17 (B17-1): `env -C ~-` while $OLDPWD is one of several known folders: each of them
                    run = list(dict.fromkeys(os.path.normpath(t) for t in tg))
                else:
                    run = self.join_cwds(run if run is not None else cwd_list(cwds),
                                         d.value if d.value is not None and not d.glob else "")
                run_words.extend(x for x in p.chdirs if (x.value is None and not (tg and x is d)) or x.glob)
            self.runner_env(spec, p, env_ops)
            if "path-modified" in p.flags:
                path_mod = True
            if p.outcome == "none":
                cmd.files = list(p.files)
                break
            if p.outcome == "shell":
                cmd.files = list(p.files)
                shell_op = p
                break
            wname = runners.wrapper_name(spec, key)
            end = p.end if p.end is not None else len(words)
            wrappers.append(Wrapper(wname, words[i + 1:end], p.effect, files=p.files, cwd=base_run))
            by_shell = False
            if p.outcome == "sudo-shell":
                rest = words[end:]
                cmd.words, cmd.wrappers = rest, wrappers
                cmd.env = EnvView(env_ops)
                self._run_folder(cmd, run, run_words)
                self.emit(cmd)
                payload = " ".join(w.value for w in rest) if rest and all(w.value is not None for w in rest) else (
                    "" if not rest else None)
                sop = Opaque("sudo-shell", payload=payload, cwds=cwd_list(cwds))
                sop.skeleton = " ".join(w.skeleton for w in rest)  # searched for Studio repositories (m2)
                if not rest:
                    # the root shell reads its commands from stdin (`sudo -s <<< '…'`, m-b): that text is searched
                    text, _origin, _kind = self.stdin_payload(cmd, stdin, state)
                    if text:
                        sop.payload = sop.skeleton = text
                self.emit_opaque(sop, cmd)
                return (cwds, cwds)
            if p.outcome == "env-S":
                cmd.words, cmd.wrappers = [], wrappers
                cmd.env = EnvView(env_ops)
                self._run_folder(cmd, run, run_words)
                self.emit(cmd)
                text, skel = runners.shell_words_text(p.shell)
                op = Opaque("env-S", payload=text, origin="literal" if text is not None else "dynamic",
                            cwds=cwd_list(cwds))
                op.skeleton = skel
                self.emit_opaque(op, cmd)
                return (cwds, cwds)
            i = end
            continue
        cmd.words = words[i:]
        cmd.wrappers = wrappers
        cmd.env = EnvView(env_ops)
        flags = cmd.flags
        self._run_folder(cmd, run, run_words)
        cmd.home = self.home_of(cmd, outer)
        if "HOME" in outer.vars and outer.raw_values.get("HOME") is not None and cmd.words and (
                cmd.words[0].value in ("cd", "chdir", "pushd", "popd") or any("~" in (w.raw or "") for w in cmd.words) or
                any("~" in (r.target.raw or "") for r in cmd.redirs if r.target is not None)):
            # review 6 M11, review 7 M5: $HOME written by this call (`read HOME`, `${HOME:=…}`, `for HOME in …`; a loop
            # body may run in a folder the guard cannot tell) before `cd` or a `~` word of any command: the text it
            # came from is searched for Studio repositories, as a `cd $D` target is, and the rest of a `~/…` word is
            # judged as a path under a folder the guard cannot tell (judge.tilde_rest). `~-` and `~+` are zsh's own
            # folders, whatever $OLDPWD and $PWD hold (checked in zsh 5.9).
            cmd.run_words = list(cmd.run_words) + [Word("$HOME", None, dynamic=True, dyn=["param:HOME"],
                                                        skeleton=outer.raw_values["HOME"])]
            cmd.tilde_unknown = {"tilde"}
        if any("~[" in (w.raw or "") for w in cmd.words) or \
                any("~[" in (r.target.raw or "") for r in cmd.redirs if r.target is not None):
            cmd.tilde_unknown = set(getattr(cmd, "tilde_unknown", None) or ()) | {"tilde-dir"}  # review 14 (B14-6)
        if not by_shell:
            flags.add("exec-by-program")
        if query:
            flags.add("query")
            self.emit(cmd)
            self.last_top = cmd
            return (cwds, cwds)
        if state.path_modified or path_mod:
            flags.add("path-modified")
        if state.env_unknown:
            flags.add("env-unknown")
        if outer.after_exec and "exec" not in [w.name for w in wrappers]:
            flags.add("after-exec")
        if unread is not None and dropped and unread_at is not None and \
                _value_dropped(unread_at[0], words, unread_at[1], dropped):
            # G1 §1.2: in this reading an option whose value the shell dropped takes the next word, which the runner
            # rejects (no word left, or not a number where it takes one) — it runs nothing (M4: a refusal for any
            # other reason stays)
            return (cwds, cwds)
        if unread is not None:
            # a runner the guard cannot read: it stays the program (the generic writer rules judge its words) and
            # judge refuses it in a Studio repository (G1 §1.2)
            flags.add("runner-unread")
            self.emit(cmd)
            self.last_top = cmd
            op = Opaque("runner", payload=unread, cwds=cwd_list(cwds))
            op.skeleton = " ".join(w.skeleton for w in cmd.words)
            self.emit_opaque(op, cmd)
            return (cwds, cwds)
        if not cmd.words:
            if any(w.name == "exec" for w in wrappers) and redirs:
                # `exec <<< …`, `exec 3< f`: the shell's own fds from here on (review 6 M7)
                cur, fds = self.redirect_fds(redirs, stdin, outer, cwd_list(cwds))
                outer.fds = dict(fds)
                if cur is not None:
                    outer.fds["0"] = cur
            self.emit(cmd)
            self.last_top = cmd
            return (cwds, cwds)
        if shell_op is not None:
            text, skel = runners.shell_words_text(shell_op.shell)
            sop = Opaque("shell-c", payload=text, origin="literal" if text is not None else "dynamic",
                         cwds=cwd_list(cwds))
            sop.skeleton = skel
            self.emit_later(deferred, sop, cmd)
        w0 = cmd.words[0]
        if w0.value is None:
            flags.add("dynamic-argv0")
            funcs_unknown(outer)  # review 11 B1: it may be `unfunction f`, `eval …`
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
            if prog in outer.aliases_defined or prog in outer.shadowed or outer.tables_changed:
                flags.add("shadowed")
                if (prog in outer.shadowed or outer.tables_changed) and prog in ("cd", "chdir", "pushd", "popd"):
                    self.emit(cmd)
                    self.last_top = cmd
                    return (None, None)
                if prog in outer.alias_src:
                    # fix20 (P20-5): an alias this call defined that may run source / `.` / eval: the walk stops here
                    self.emit(cmd)
                    self.last_top = cmd
                    mark_sourced(self)
                    return (None, None)
            if prog in outer.funcs:
                flags.add("inline-function")
                if prog in ("cd", "pushd", "popd", "builtin", "command") or prog in ("git", "rm", "cp", "mv"):
                    flags.add("shadowed")
                self.emit(cmd)
                self.last_top = cmd
                eff = outer.funcs[prog]
                call_flag0 = self.sourced
                res = self.inline_call(cmd, prog, eff, cwds, outer, stdin, prefix_ops)
                alts, unknown = _call_alternatives(eff)
                if not (unknown or None in alts) or self.dry:
                    return res
                if prog in BUILTINS:
                    return (None, None)
                # review 11 B1 (R1): the function may be gone (or replaced by code the guard cannot read) — the name
                # then runs the command so named, judged too
                ent = outer.funcs.pop(prog, None)
                rd = Readings(self)  # fix20 (P20-5): the other reading of this call starts from the flag before it
                rd.flag0, rd.any = call_flag0, self.sourced
                try:
                    rd.start()
                    res2 = self.process(words, cwds, state, prefix_ops, redirs, stdin, alt=alt, aliases=aliases,
                                        span=span, via_program=via_program, parent=parent, extra_ctx=extra_ctx,
                                        lock_depth=lock_depth, outer_state=outer_state, extra_flags=extra_flags,
                                        dropped=dropped)
                finally:
                    rd.end()
                    if ent is not None:
                        outer.funcs[prog] = ent
                return (union(res[0], res2[0]), union(res[1], res2[1]))
            self.maybe_defined_call(cmd, prog, outer, stdin, cwds)
            if snap is not None and prog in snap.delegated:
                flags.add("via-function")
            elif snap is not None and prog in snap.user_functions:
                flags.add("user-function")
                self.emit(cmd)
                self.last_top = cmd
                bodies = snap.function_bodies(prog)  # its own definition (not the text after it)
                body = "\n".join(bodies) if bodies else (snap.function_text(prog) or "")
                payload = " ".join(w.value if w.value is not None else w.skeleton for w in cmd.words) + "\n" + body
                if self.effective_stdin(cmd.redirs, stdin, outer, cmd.cwds) is not None:
                    text = self._stdin(cmd, stdin, outer)[0]
                    payload += "\n" + (text or "")  # its input, searched like its words (review 6 M6)
                self.emit_opaque(Opaque("function", payload=payload, cwds=cwd_list(cwds)), cmd)
                # R2-M1 (review 2), review 3 M-1 to M-4: what the body (or a function it calls) may change for later
                # commands — the environment when it exports or sets a global git or the guard reads, the options it
                # sets (all of them when it cannot name them), the folder when it may change folder; a body the guard
                # cannot read (eval, source, "$@", …) may change any of them
                # review 4 B3: a function this call defined (or may have: eval, source, autoload, functions[…]) may be
                # one the snapshot function runs — what it does is then unknown
                eff = None if self.defs_changed(outer) else snapshot_function_effects(self.ctx, prog)
                if eff is None:
                    self.steer_event(outer, cmd.words[1:], stdin, redirs)
                return apply_function_effects(self.ctx, outer, eff, cwds)
        if by_shell and not is_path and (snap is None or snap.partial):
            if not self.runnable(prog, outer):
                # zsh may run an alias or function we could not read: the judgement in M0d-1b denies this
                # in harness repositories; the command itself is still recognized below
                funcs_unknown(outer)  # review 11 B1: such a function may remove or replace one of this call
                payload = " ".join(w.value if w.value is not None else w.skeleton for w in cmd.words)
                op_unknown = Opaque("unknown-command", payload=payload, cwds=cwd_list(cwds))
                deferred.append(lambda: self.emit_opaque(op_unknown, cmd))
        folded = self.fold_name(cmd, cwds, outer)
        if folded:
            prog = cmd.prog
        self.zsh_forms(cmd, cwds, outer)
        shell_builtin = not is_path and not folded and (by_shell or bypass_func and not via_program)
        posix = self.posix_builtins(outer) if command_wrapped else True
        if posix is False:
            shell_builtin = False  # `command cd /tmp` is the external cd: the shell's folder stays
            if prog in ("source", ".") and by_shell and not folded and not is_path:
                # fix20 (P20-5): `command .` / `command source` — the external command in zsh (POSIX_BUILTINS off);
                # read as a source all the same (the walk stops; the 0.0.26 rules judge the rest)
                shell_builtin = True
        if shell_builtin and prog in BUILTINS:
            self.cur_stdin = stdin
            out = BUILTINS[prog](self, cmd, cwds, outer)
            if posix is None and prog in ("cd", "chdir", "pushd", "popd"):
                out = (union(out[0], cwds), union(out[1], cwds))  # POSIX_BUILTINS maybe: both folders
            if prog in ("cd", "chdir", "pushd", "popd"):
                if out[0] is None and any(w.value is None or w.glob or "(" in w.value for w in cmd.words[1:]):
                    outer.pwd_steered = True  # $PWD may now be a folder this call named (review 4 conf M-1)
                out = self.after_chpwd(outer, out)
            ok, self.emit_ok = self.emit_ok, True  # fix20: the builtin's own command (a `source` too) is judged
            try:
                self.emit(cmd)
                self.last_top = cmd
                for f in deferred:
                    f()
            finally:
                self.emit_ok = ok
            return out
        out = self.recognize(cmd, cwds, outer, stdin, lock_depth, deferred)
        self.emit(cmd)
        self.last_top = cmd
        self.record_written(cmd, outer)
        for f in deferred:
            f()
        return out

    def inline_call(self, cmd, prog, eff, cwds, outer, stdin, prefix_ops):
        """A function this call defined, called. Review 10: its body is walked from the call and its folder there is
        the result. Review 11 B1: every definition that may be in force is walked (one that may not have run, the
        earlier one, none: the name then runs a command so named or is not found) and the union taken; when zsh's
        function table may have changed in a way the guard does not follow, the call is judged as before G1 walked
        call-defined functions: the folder and the values it may write unknown."""
        alts, unknown = _call_alternatives(eff)
        outer.steer_all = True  # its body (this call's text) may assign any parameter (review 4 conf M-1)
        if unknown:
            self.call_body(prog, eff, cmd, cwds, outer, stdin, prefix_ops)  # its commands are judged
            if eff.get("options") or any(a and a.get("options") for a in alts):
                _options_unknown(outer)
            if eff.get("env") or eff.get("paths"):
                outer.env_unknown = True
            keep_candidates(self.ctx, outer)
            funcs_unknown(outer)
            outer.dirstack = None
            outer.oldpwd = None
            outer.cands.pop("~-", None)
            note_lost(cwds)  # or the name runs no function: the shell stays (judged there too)
            return (None, None)
        before = dict(outer.funcs)
        results = []
        rd = Readings(self)  # fix20 (P20-5): each definition in force is a reading of the call
        for a in alts:
            rd.start()
            results.append((a, None if a is None else self.call_body(prog, a, cmd, cwds, outer, stdin, prefix_ops)))
            rd.end()
        if any(a and a.get("options") for a in alts):
            _options_unknown(outer)
        self.inline_function_env(outer, eff)
        # the function table after the call: what each walked body left; a body not walked (a dry run, a recursive
        # call) that may change it: unknown
        tabs, table_unknown = [], False
        for a, c in results:
            if a is None:
                tabs.append(before)
            elif c is not None:
                tabs.append(c[1].funcs)
            elif a.get("fntable") or a.get("unknown_def"):
                table_unknown = True
            else:
                t = dict(before)
                t.update(a.get("funcs") or {})
                tabs.append(t)
        if tabs:
            merged = {}
            for n in set().union(*[set(t) for t in tabs]):
                es = [t.get(n) for t in tabs]
                present = [e for e in es if e is not None]
                if all(_same_def(e, present[0]) for e in present):
                    merged[n] = present[-1] if len(present) == len(es) else maybe_removed(present[-1])
                else:
                    merged[n] = dict(present[-1], unknown_def=True)
            outer.funcs = merged
        if table_unknown:
            funcs_unknown(outer)
        afters, moved = [], prog in ("cd", "pushd", "popd")
        for a, c in results:
            if a is None:
                afters.append(cwds)
            elif c is not None:
                afters.append(union(c[0][0], c[0][1]))
            else:
                afters.append(None if a.get("cwd") else cwds)
            moved = moved or bool(a and a.get("cwd"))
        if prog in ("cd", "pushd", "popd"):
            afters = [None]
        after = afters[0] if afters else cwds
        for x in afters[1:]:
            after = union(after, x)
        moved = moved or after is None or set(after) != set(cwds or ())
        if moved:
            outer.dirstack = None
            for a, c in results:
                if c is not None and c[1].oldpwd != outer.oldpwd:
                    _oldpwd_union(outer, (outer.oldpwd, outer.cands.get("~-")), (c[1].oldpwd, c[1].cands.get("~-")))
            return (after, after) if after else (None, None)
        return (cwds, cwds)

    def maybe_defined_call(self, cmd, prog, state, stdin, cwds):
        """review 7 M4: a name a literal eval / source / emulate -c string of this call may have defined as a function
        (`eval 'f(){ sh }'; f <<< …`): that text and this call are scanned together, with this call's input. When a
        string the guard cannot read may have defined it, a call with input may run that input as code: it is
        scanned as a shell string."""
        if (prog in BUILTINS and prog not in state.defs_src) or \
                self.effective_stdin(cmd.redirs, stdin, state, cmd.cwds) is None:
            return  # without input its body was judged where the string defined it
        if prog in state.defs_src:
            src, at = state.defs_src[prog]
            vals = [w.value for w in cmd.words]
            text = None if src is None or any(v is None for v in vals) else \
                src + "\n" + " ".join(_shq(v) for v in vals)
            op = Opaque("eval", payload=text, origin="literal" if text is not None else "dynamic",
                        cwds=cwd_list(cwds))
            if text is None:
                op.skeleton = (src or "") + "\n" + " ".join(w.skeleton for w in cmd.words)
            op.at_cwds = at  # the folder the string ran in, when the call's is unknown (the eval made it so)
            self.emit_opaque(op, cmd)
            return
        if state.defs_unknown:
            text, _origin, _kind, dyn = self._stdin(cmd, stdin, state)
            op = Opaque("shell-c", payload=None if dyn else text,
                        origin="literal" if text is not None and not dyn else "dynamic", cwds=cwd_list(cwds))
            op.skeleton = text
            op.input = False
            self.emit_opaque(op, cmd)

    def call_body(self, prog, eff, cmd, cwds, state, stdin, prefix_ops=()):
        """A function this call defined, called: its body is walked again from the call — in the call's folder, with
        the parameters and prefix assignments in effect there (review 8 M2: `f(){ rm -rf ~/studio }; HOME=<repo> f`,
        `f(){ rm -rf studio }; cd <repo>; f`) and the input it is given (review 6 M6: `f <<< …`, `… | f`,
        `f 3<<< …`, after `exec <<< …`), its commands reading that input."""
        body = eff.get("body")
        if body is None or prog in self.rewalking or self.dry:
            return None  # a dry run (a reading being tried) emits nothing
        cur, fds = self.redirect_fds(cmd.redirs, stdin, state, cmd.cwds)
        saved = self.pipe_in
        st = state.copy()
        st.fds = dict(fds, **({"0": cur} if cur is not None else {}))
        for op in prefix_ops:
            if op.kind == "set" and op.name and "[" not in op.name:
                val = getattr(op.value, "value", None)
                st.vars[op.name] = val if isinstance(val, str) else DYN
                st.raw_values[op.name] = val if isinstance(val, str) else (getattr(op.value, "skeleton", None) or "")
        self.pipe_in = cur
        self.rewalking.add(prog)
        self.push("function-body")
        self.func_depth += 1
        try:
            out = self.walk_command(body, cwds, st, None)
        finally:
            self.func_depth -= 1
            self.pop()
            self.rewalking.discard(prog)
            self.pipe_in = saved
        return out, st

    def home_of(self, cmd, state):
        """review 8 M2: $HOME for the strings a command runs (eval, `sh -c`, env -S, a function body): ("known", value)
        or ("unknown", the text it came from) when the command's environment (a prefix assignment, `env HOME=…`,
        `export`) or this call set it, or it may have (an eval, a sourced file); None: the hook's own."""
        env = cmd.env
        if env is not None and "HOME" in env.set:
            v = env.set["HOME"]
            val = getattr(v, "value", v)
            if isinstance(val, str):
                return ("known", val)
            if "HOME" not in state.vars:
                return ("unknown", getattr(v, "skeleton", None) or getattr(v, "raw", None) or "")
        if "HOME" in state.vars:
            v = state.vars["HOME"]
            if isinstance(v, str):
                return ("known", v)
            return ("unknown", state.raw_values.get("HOME") or "")
        if state.env_unknown or (env is not None and (env.unknown or env.cleared or "HOME" in env.unset)):
            return ("unknown", "")
        return None

    def defs_changed(self, state):
        """review 4 B3: whether this call may have defined a function (a definition, eval, source, autoload, a write to
        zsh's function table): a snapshot function that runs a command by that name runs it. Aliases do not count:
        a function's body was read when the snapshot defined it (checked in zsh 5.9)."""
        return state.defs_maybe or bool(state.funcs) or bool(self.ctx.inline_functions) or state.tables_changed

    def hook_effects(self, state, eff):
        """A hook zsh runs after later commands (chpwd, TRAPDEBUG, TRAPZERR, `trap … ZERR`, *_functions; review 4
        m3, R1): its effects hold from here on — the folder is unknown for every later command when it may change
        it; eff None (a hook the guard does not read): the folder, environment, options and parameters."""
        apply_function_effects(self.ctx, state, eff, None)
        if eff is None or eff["cwd"]:
            state.hook_cwd = True
            state.pwd_steered = True
        if eff is None:
            state.steer_all = True

    def define_hook(self, state, name, eff):
        """review 10 B1/M1: a function `name` this call (re)defined: when zsh runs it as a hook between later commands
        (chpwd, TRAPDEBUG, TRAPZERR, TRAP<signal>, command_not_found_handler, or a name an active trap action runs),
        what its body may do holds from here on. precmd, preexec, periodic, zshaddhistory and zshexit never run in
        the Bash tool's shell; TRAPEXIT set at the top runs after every command."""
        if name in getattr(state, "trap_names", ()):
            self.inline_hook(state, eff)
        if not is_hook_function(name):
            return
        kind = hook_kind(name)
        if kind == "never" or (kind == "exit" and not self.func_depth):
            return
        self.inline_hook(state, eff)

    def inline_hook(self, state, eff):
        """A function this call defined may run between later commands: its effects, each a write that may or may
        not have happened (the union rule); the folder unknown when it may change it."""
        if eff is None:
            self.hook_effects(state, None)
            return
        e = dict(eff)
        e["maybe"] = set(eff.get("globals", ()))
        self.inline_function_env(state, e)
        if eff.get("fntable") or eff.get("unknown_def"):
            funcs_unknown(state)  # review 11 B1: `TRAPDEBUG(){ unfunction f }` may have run before any later call
        state.steer_all = True  # its body (this call's text) may assign any parameter (as a call: review 4 conf M-1)
        if eff.get("options"):
            _options_unknown(state)
        if eff.get("cwd") or eff.get("hook") or _body_moves(eff.get("body"), state):
            state.hook_cwd = True
            state.pwd_steered = True
            state.dirstack = None

    def hook_array(self, state, name):
        """chpwd_functions=(…) and the other hook arrays (review 4 R1): the functions they name run as hooks — the
        guard does not follow which, so the folder and values are unknown — except the arrays zsh never runs in the
        Bash tool's shell (review 10)."""
        if hook_kind(name) != "never":
            self.hook_effects(state, None)

    def after_chpwd(self, state, out):
        """A snapshot chpwd function runs after each folder change (review 4 m3)."""
        snap = self.ctx.snapshot
        if snap is None or "chpwd" not in snap.user_functions or "chpwd" in state.funcs:
            return out
        eff = None if self.defs_changed(state) else snapshot_function_effects(self.ctx, "chpwd")
        if eff is None:
            state.steer_all = True
        if apply_function_effects(self.ctx, state, eff, out[0]) == (None, None):
            state.pwd_steered = True
            note_lost(out[0])  # review 10 B1: or chpwd did not move the shell
            return (None, out[1])
        return out

    def _run_folder(self, cmd, run, run_words):
        """The run folders a runner set (env -C, sudo -D); [] and `run-unknown` when the guard cannot tell them
        (judged like a folder the guard cannot tell, §1.7a)."""
        if run is not None:
            cmd.run_cwds = list(run)
            if not run:
                cmd.flags.add("run-unknown")
        cmd.run_words = run_words

    def zsh_forms(self, cmd, cwds, state):
        """G1 §1.8: builtins that write one of zsh's tables by name (`typeset 'commands[ls]=…'`, `read -r
        'commands[ls]'`, `print -v …`, `zstyle -s … 'commands[ls]'`, …), and prompt expansion that may run `$(…)`."""
        pk = recog.key(cmd.prog or "")
        if pk in cmdopts.NAME_WRITERS:
            vals = [w.value for w in cmd.words[1:]]
            if cmdopts.name_writer(pk, [v for v in vals if v is not None]):
                hits = [w.skeleton for w in cmd.words[1:] if _table_named(w)]
                # a name attached to its option (`print -v'commands[ls]'`, `set -Acommands`: M3, review 2)
                hits += [a for a in cmdopts.attached_names(pk, [v for v in vals if v is not None])
                         if cmdopts.table_word(a)]
                if any(w.value is None and (w.skeleton or "").startswith(("-", "+")) for w in cmd.words[1:]):
                    hits.append("an option the guard cannot read")
                if hits:
                    self.table_write(state, "%s %s" % (cmd.prog, " ".join(hits)), cwds, cmd)
                if pk not in cmdopts.TYPESET:  # export/typeset values are read by b_export
                    names = cmdopts.written_names(pk, vals)
                    text = " ".join([w.raw for w in cmd.words] + [r.body or "" for r in cmd.redirs
                                                                       if r.mode in ("heredoc", "herestring")])
                    vmark = ValueMark(state) if pk == "read" else None
                    for n in names:
                        self.param_written(state, n, pk, cwds, cmd, raw=text)  # read, print -v, set -A, … (M6)
                        if vmark is not None:
                            # review 10 B3: `read -t` with no input, or a read that fails, may leave it as it was
                            union_values(self.ctx, state, n, (vmark, ValueMark(state)))
                    if pk == "set" or (pk == "read" and cmdopts.has_short(vals, "Aa")):
                        state.arrays.update(names)
        if pk in ("autoload", "functions") and any(w.value is None or not w.value.startswith(("-", "+"))
                                                   for w in cmd.words[1:]):
            state.defs_maybe = True  # a function loaded or copied by name (review 4 B3)
        if pk == "functions":
            self.functions_copy(cmd, cwds, state)
        if pk == "print" and any(w.value and re.match(r"^-[A-Za-z]*P", w.value) for w in cmd.words[1:]) and \
                self.option_maybe(state, "promptsubst") is not False:
            self.emit_opaque(Opaque("prompt-subst", payload="print -P", cwds=cwd_list(cwds)), cmd)

    def functions_copy(self, cmd, cwds, state):
        """review 6 M8: `functions -c SRC DST` copies a function under a new name — a function this call defined is
        copied with its effects; any other (a snapshot function, a name the guard cannot read) writes zsh's function
        table: later names may run anything (G1 §1.8)."""
        ws = cmd.words[1:]
        i, copy = 0, False
        while i < len(ws) and (ws[i].value is None or ws[i].value.startswith(("-", "+"))):
            if ws[i].value is None:
                copy = True  # an option the guard cannot read
                break
            if ws[i].value == "--":
                i += 1
                break
            copy = copy or (ws[i].value.startswith("-") and "c" in ws[i].value[1:])
            i += 1
        if not copy:
            return
        names = [w.value for w in ws[i:]]
        if len(names) >= 2 and None not in names[:2] and names[0] in state.funcs:
            state.funcs[names[1]] = state.funcs[names[0]]
            self.ctx.inline_functions.add(names[1])
            state.defs_maybe = True
            self.define_hook(state, names[1], state.funcs[names[1]])
            return
        self.table_write(state, "functions %s" % " ".join(w.skeleton for w in ws), cwds, cmd,
                         names=[n for n in names[1:2] if n])

    def resolve_text(self, text, state, cwds):
        """`text` with each $NAME / ${NAME} whose value the guard knows replaced by it (review 7 M5)."""
        def sub(m):
            v = self.lookup(m.group(1) or m.group(2), state, cwds)
            return v if isinstance(v, str) else m.group(0)
        return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)", sub, text)

    def param_written(self, state, name, via, cwds, cmd=None, raw=None, value=None):
        """A parameter written other than by an assignment (read, for/select, print -v, set -A, ${X::=…}, …): its
        value is unknown from here on, or `value` when the guard knows it (`${X::=lit}`, `for X in lit`). A §1.9
        variable so written is in effect as unknown for later commands, and a command-valued one is refused in a
        Studio repository (M6). `raw`: the text the value came from, searched from outside a Studio repository when a
        later command uses the value (review 6 M11: HOME before `cd`)."""
        if raw is not None and value is None and "$" in raw:
            raw = raw + " " + self.resolve_text(raw, state, cwds)  # `X=<R>; read HOME <<< $X` (review 7 M5)
        state.vars[name] = DYN if value is None else value
        state.safe_values.discard(name)
        if value is not None:
            state.cands.pop(name, None)
        else:
            prog = cmd.prog if cmd is not None else None
            self.set_cands(state, name, raw, cwds, exclude=(name, prog or via))
        if raw is not None or value is not None:
            state.raw_values[name] = value if value is not None else raw
        else:
            state.raw_values.pop(name, None)
        if name in HOOK_ARRAYS:
            self.hook_array(state, name)
        if name in ("PATH", "path"):
            state.paths, state.path_modified = None, True
        if name == "dirstack":
            state.dirstack = None
        if not cmdopts.watched_var(name):
            return
        state.env_ops.append(EnvOp(via, "set", name, _unknown_value(name)))
        if name in cmdopts.CMD_VARS:
            self.var_set(state, name, None, None, cwds, cmd)

    def table_write(self, state, what, cwds, cmd=None, names=()):
        """A write to zsh's command, alias, function or option tables (G1 §1.8): later commands may run anything
        under any name — they are `shadowed`, the options and the environment unknown; judge refuses it in a Studio
        repository."""
        state.tables_changed = True
        funcs_unknown(state)  # review 11 B1
        for n in names:
            state.shadowed.add(n)
        _options_unknown(state)
        state.env_unknown = True
        self.note("zsh-table")
        self.emit_opaque(Opaque("zsh-table", payload=what, cwds=cwd_list(cwds)), cmd)

    def option_maybe(self, state, name):
        """A zsh option in effect for this command: True, False or None (maybe)."""
        if name in state.opts:
            v = state.opts[name]
            return None if v is None else bool(v)
        forced = getattr(self.ctx, "forced_options", None) or {}
        if name in forced:
            return forced[name]
        if state.options_unknown:
            return None
        snap = self.ctx.snapshot
        if snap is not None and name in snap.option_conflicts:
            return None
        v = self.ctx.options.get(name, False)
        return None if v is None else bool(v)

    def paramx_forms(self, raw, state, cwds):
        """G1 §1.8: ${(e)…} evaluates its text; ${(%)…} expands prompts (with PROMPT_SUBST: `$(…)`); ${name::=…}
        writes one of zsh's tables; any assigning (P) form writes the parameter a value names. Nested forms count
        (`${${(e)X}}`, `${Y:-${(e)X}}`: M12). ${NAME::=…} of a §1.9 variable sets it to a value the guard does not
        follow (M6)."""
        for n in cmdopts.paramx_assigned(raw):
            text, op = _paramx_value(raw, n)
            if op == "::=" and text is not None and re.fullmatch(r"(?:[^$`'\"\\~*?\[]|\$\{?[A-Za-z_][A-Za-z0-9_]*\}?)*",
                                                               text):
                text = self.resolve_text(text, state, cwds)  # `X=<R>; : ${HOME::=$X}` (review 7 M5)
            known = text if op == "::=" and text is not None and not re.search(r"[$`'\"\\~*?\[]", text) else None
            vmark = ValueMark(state) if op != "::=" else None
            self.param_written(state, n, "paramx", cwds, raw=text if text is not None else raw, value=known)
            if vmark is not None:
                # review 10 B3: `${X:=…}` / `${X=…}` assign only when X is empty or unset — the old value or the new
                union_values(self.ctx, state, n, (vmark, ValueMark(state)))
        why = cmdopts.paramx_problem(raw)
        if why == "eval":
            op = Opaque("dynamic-command", payload=raw, cwds=cwd_list(cwds))
            # the text it evaluates, when a plain ${(e)NAME} names a known value: searched (review 2, m-a)
            m = re.match(r"^[A-Za-z_][A-Za-z0-9_]*", raw[cmdopts._flag_group(raw)[1]:]) if raw.startswith("${(") \
                else None
            v = self.lookup(m.group(0), state, cwds) if m else None
            op.skeleton = v if v is not None else raw
            self.emit_opaque(op)
        elif why == "table":
            self.table_write(state, raw, cwds)
        elif why == "prompt" and self.option_maybe(state, "promptsubst") is not False:
            self.emit_opaque(Opaque("prompt-subst", payload=raw, cwds=cwd_list(cwds)))

    def glob_qualifier(self, raw, state, cwds, globsubst=False):
        """G1 §1.8 (review 2, M13): a pattern expansion (`$~X`, `${~X}`, `${(~)X}`, or any unquoted expansion while
        GLOB_SUBST may be on) of a value that holds a glob qualifier running code (`(e:…:)`, `(+f)`) or of a value
        the guard cannot read runs that code: Opaque("dynamic-command"). Review 4 conf M-1: when GLOB_SUBST is only
        on or maybe on (a function or eval the guard cannot read), a value the guard cannot read is refused only when
        this call may have put it there (steered); a value only the environment sets is judged as before."""
        m = re.match(r"^\$(\{)?(\(([^)]*)\))?([~=^]*)([A-Za-z_][A-Za-z0-9_]*)(\})?$", raw)
        flags = m.group(3) or "" if m else ""
        pre = m.group(4) or "" if m else ""
        tilde = "~" in pre or "~" in flags or (m is None and re.match(r"^\$\{?[(=^]*~", raw))
        if not globsubst and not tilde:
            return
        simple = m is not None and bool(m.group(1)) == bool(m.group(6)) and not set(flags) - set("~")
        v = self.lookup(m.group(5), state, cwds) if simple else None
        if v is not None and not re.search(QUAL_CODE_RE, v):
            return
        if v is None and not simple and not (flags or pre):
            # $Z[1,-1], ${Z[2]}, $Z:t, ${Z:-word}: a part of a known value (review 5 M1). Its literal added text holds
            # no `(` ("simple"); a part of a value with no `(` holds no qualifier.
            name, kind = _param_name(raw)
            base = self.lookup(name, state, cwds) if kind == "simple" and name and \
                re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name) and name not in state.arrays else None
            if base is not None:
                if "(" not in base:
                    return
                v = base
        if v is None and not tilde:
            name, kind = _param_name(raw)
            if kind == "number" or (name in state.safe_values and kind != "complex"):
                return  # ${#X}, ${+X}; `for i in 1 2 3`, `arr=(a b)`
            if kind == "simple" and _complete_kind(state, name) in ("complete", "env") and \
                    not any(re.search(QUAL_CODE_RE, x) for x in state.cands[name][0]):
                # review 10: one of known values, none with a qualifier (`if …; then v=1; else v=0; fi`), or of
                # those and a value only the environment set (judged as before: `nvm use 20 && X=1; echo $X`)
                return
            if kind != "complex" and name in QUIET_SPECIALS:
                return  # $#, $?, $$, $!, $-: numbers and option letters
            if kind != "complex" and not self.steerable(state, name):
                return  # a value only the environment sets: judged as before (the call cannot put a qualifier there)
        op = Opaque("dynamic-command", payload=raw, cwds=cwd_list(cwds))
        op.why = "%s expands a pattern from %s" % (raw, "a value the guard cannot read" if v is None else
                                                  "a value with a glob qualifier that runs code")
        if v is not None or state.raw_values.get(_param_name(raw)[0]):
            # its text is searched from outside a Studio repository, like ${(e)X}'s (review 5 M1)
            op.skeleton = v if v is not None else state.raw_values.get(_param_name(raw)[0])
        self.emit_opaque(op)

    def qualifier_word(self, raw, pieces, state, cwds):
        """review 6 M1/M2: under GLOB_SUBST zsh reads the glob qualifier on the whole word, so parts may make one
        together (`X='a(#q'; Y='e:…:)'; ls $X$Y`). From the first part whose value holds a `(` (or a part of a
        parameter whose value does), the rest of the word is joined and checked; a part the guard cannot read after
        it, or such a part followed by more text, cannot be checked: refused (fail closed)."""
        start = None
        for i, (text, base) in enumerate(pieces):
            if (text is not None and "(" in text) or (text is None and base is not None and "(" in base):
                start = i
                break
        if start is None:
            return
        rest = pieces[start:]
        if rest[0][0] is None and all(t == "" for t, _b in rest[1:]):
            return  # a part of one value, alone at the end: glob_qualifier judges it
        if any(t is None for t, _b in rest):
            why = "parts the guard cannot read next to a value with `(`"
            joined = None
        else:
            joined = "".join(t for t, _b in rest)
            if not re.search(QUAL_CODE_RE, joined) or any(t is not None and re.search(QUAL_CODE_RE, t)
                                                           for t, _b in rest):
                return  # no qualifier; or one part alone holds it (refused by glob_qualifier)
            why = "values that together make a glob qualifier that runs code"
        op = Opaque("dynamic-command", payload=raw, cwds=cwd_list(cwds))
        op.why = "%s expands a pattern from %s" % (raw, why)
        op.skeleton = joined if joined is not None else raw
        self.emit_opaque(op)

    def inline_function_env(self, state, eff):
        """review 5 R2: a function this call defined ran — the variables its body exports or assigns are set to values
        the guard does not follow (`y(){ export GIT_DIR=…; }; y; git commit`), as a plain `export` would be judged."""
        if eff.get("env"):
            state.env_unknown = True
        if eff.get("maybe_def"):
            # review 10: the definition may not have run — the earlier one (or none) may run instead
            if eff.get("prev") is not None:
                prev = dict(eff["prev"])
                prev["maybe"] = set(prev.get("globals", ()))
                self.inline_function_env(state, prev)
            eff = dict(eff)
            eff["maybe"] = set(eff.get("globals", ()))
        before = ValueMark(state)
        for name in sorted(eff.get("globals", ())):
            if name in eff.get("maybe", ()) and eff.get("end") is not None:
                # review 10 B2: the write may not have run — the caller's value or the body's
                union_values(self.ctx, state, name, (before, eff["end"]))
                if name in eff.get("unknown", ()):
                    # `X=a; local X=b`: the global got a value the end of the body hides — every literal value the
                    # body assigns the name stays a candidate
                    state.vars[name] = DYN
                    extra = [re.sub(r"['\"\\]", "", t) for t in eff.get("texts", {}).get(name, ())
                             if t and not re.search(r"[$`]", t)]
                    old = state.cands.get(name, ((), True))
                    vals = tuple(dict.fromkeys(tuple(old[0]) + tuple(extra)))
                    if vals:
                        state.cands[name] = (vals[:MAX_CANDS], old[1] and len(vals) <= MAX_CANDS)
            else:
                state.vars[name] = eff.get("known", {}).get(name, DYN)
                state.safe_values.discard(name)
                if eff.get("cands", {}).get(name):
                    state.cands[name] = eff["cands"][name]
                else:
                    state.cands.pop(name, None)
            if name in ("PATH", "path"):
                state.paths, state.path_modified = None, True
            elif name == "dirstack":
                state.dirstack = None
            elif name == "OLDPWD":
                state.oldpwd = None
                state.cands.pop("~-", None)
            elif name in HOOK_ARRAYS:
                self.hook_array(state, name)
            if function_watched(self.ctx, state, name):
                state.env_ops.append(EnvOp("function", "set", name, _unknown_value(name)))
        if eff.get("paths"):
            state.paths, state.path_modified = None, True
        if eff.get("hook"):
            # review 10: the body set a trap or hook that may change the folder (an EXIT trap set in a function runs
            # when it returns)
            state.hook_cwd = True
            state.pwd_steered = True
        # review 6 M9: functions its body defined now exist (`f(){ g(){ cd studio } }; f; g`); a write to zsh's
        # tables in its body holds from the call on
        for n, e in sorted(eff.get("funcs", {}).items()):
            state.funcs[n] = e
            self.ctx.inline_functions.add(n)
            self.define_hook(state, n, e)
        if eff.get("defs"):
            state.defs_maybe = True
        if eff.get("tables"):
            self.table_write(state, "a function's body", None)

    def steerable(self, state, name):
        """review 4 conf M-1: whether this call may have put a value in parameter `name` — it assigns it (a loop, read,
        ${…::=}, a function's global), zsh sets it implicitly (REPLY, match, OPTARG, positionals), it is $PWD after a
        folder change the guard cannot follow, or code the guard cannot read got a word naming it, a word it cannot
        read, stdin or a file the call wrote."""
        if name == "0":  # `0=…` sets $0 alone (review 6 M3); `shift` does not move it
            return bool(state.steer_all or self.func_depth or "0" in state.vars or "0" in state.steer_names)
        if name in POSITIONAL or re.match(r"^\d+$", name or ""):
            # $1, $@, $argv: in a function body, or after the call set any of them (`set --`, `read -A argv`, eval,
            # `N=…`, `argv[N]=…`): `shift` moves values and $@ / $* / $argv hold every one (review 7 M3)
            def pos(n):
                return n in POSITIONAL or (n.isdigit() and n != "0")
            return bool(state.steer_all or self.func_depth or any(pos(n) for n in state.vars) or
                        any(pos(n) for n in state.steer_names))
        if state.steer_all or name in IMPLICIT_PARAMS or name in ZSH_SPECIAL_PARAMS:
            return True
        # the same parameter under another name: PS1/PROMPT/prompt, cdpath/CDPATH, … (review 5 M2)
        if any(n in state.vars or n in state.steer_names for n in TIED_NAMES.get(name, (name,))):
            return True
        if name in ("PWD", "OLDPWD"):
            return state.pwd_steered
        return not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name or "")

    def steer_event(self, state, words, stdin=None, redirs=()):
        """Code the guard cannot read ran (eval, source, a function it cannot read; review 4 conf M-1): what it may
        have assigned from this call's input."""
        if state.written or stdin is not None or any(w.value is None for w in words) or \
                any(r.fd in (None, "0") and r.mode in ("heredoc", "herestring", "read", "rw") for r in redirs or ()):
            state.steer_all = True
            return
        for w in words:
            state.steer_names.update(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", w.value))

    def array_qualifiers(self, raw, state, cwds):
        """`a=($X …)`: the unquoted expansions of an array value are file-name generated (review 4 conf M-1)."""
        if self.option_maybe(state, "globsubst") is False and "~" not in raw:
            return
        text = re.sub(r"'[^']*'|\"(?:[^\"\\]|\\.)*\"", "''", raw)
        for m in re.finditer(r"\$(\{[^{}]*\}|[A-Za-z_][A-Za-z0-9_]*)", text):
            self.glob_qualifier(m.group(0), state, cwds, globsubst=self.option_maybe(state, "globsubst") is not False)

    def runner_isdir(self, value, base):
        """Whether a runner's file operand is an existing folder (flock reads a folder; it creates a file)."""
        if value is None:
            return False
        if os.path.isabs(value):
            return self.ctx.fs.isdir(value)
        return bool(base) and all(self.ctx.fs.isdir(os.path.join(b, value)) for b in base)

    def runner_env(self, spec, p, env_ops):
        via = spec.name
        for e in p.env:
            if e[0] == "clear":
                env_ops.append(EnvOp(via + "-i" if via == "env" else via, "clear"))
            elif e[0] == "unset":
                env_ops.append(EnvOp(via + "-u" if via == "env" else via, "unset" if e[1] is not None else "unknown",
                                     e[1]))
            elif e[0] == "set":
                env_ops.append(EnvOp(via, "set", e[1], e[2]))
            else:
                env_ops.append(EnvOp(via, "unknown"))

    def posix_builtins(self, state):
        """POSIX_BUILTINS: True, False or None (maybe) — with it on, `command cd` is the builtin (G1 §1.3)."""
        if "posixbuiltins" in state.opts:
            return state.opts["posixbuiltins"]
        forced = getattr(self.ctx, "forced_options", None) or {}
        if "posixbuiltins" in forced:
            return forced["posixbuiltins"]
        snap = self.ctx.snapshot
        if snap is not None and "posixbuiltins" in snap.option_conflicts:
            return None
        v = self.ctx.options.get("posixbuiltins", False)
        return None if v is None else bool(v)

    def fold_name(self, cmd, cwds, state):
        """G1 §1.4: a program name in capitals (`RM`, `/BIN/RM`, `GIT`) is the lower-case program when both resolve to
        the same file, or the name resolves on a case-insensitive volume. words[0] gets the folded basename (the
        original stays in Word.raw) and the command the flag `name-folded`; it never takes the builtin path."""
        w0 = cmd.words[0]
        v = w0.value
        base = recog.base(v)
        low = recog.key(base)
        if not base or low == base:
            return False
        from .parse import RESERVED
        from .scanctx import ZSH_BUILTINS
        snap = self.ctx.snapshot
        if "/" not in v and (base in ZSH_BUILTINS or base in RESERVED or base in state.funcs or
                             base in self.ctx.inline_functions or base in state.aliases_defined or
                             (snap is not None and (base in snap.user_functions or base in snap.delegated or
                                                    base in snap.plain or base in snap.alternatives))):
            return False
        if "/" in v:
            cwd = single(cwds)
            if not os.path.isabs(v) and cwd is None:
                return False
            p = os.path.normpath(v if os.path.isabs(v) else os.path.join(cwd, v))
            q = os.path.join(os.path.dirname(p), low)
            if not self.ctx.fs.exists(p):
                return False
            folded = v[:len(v) - len(base)] + low
        else:
            p = self.which(v, state)
            if p is None:
                return False
            q = self.which(low, state)
            folded = low
        try:
            same = q is not None and os.path.samefile(p, q)
        except OSError:
            same = False
        if not (same or self.where.case_insensitive(p)):
            return False
        cmd.words[0] = Word(w0.raw, folded, quoted=w0.quoted, plain=w0.plain)
        cmd.flags.add("name-folded")
        return True

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
        # where the program starts (before its own -C/--directory): its folder words are relative to it
        cmd.start_folders = [] if "run-unknown" in cmd.flags else list(cmd.run_cwds or cwd_list(cwds))
        # git
        if k == "git":
            env = cmd.env.set
            g = recog.git_info(args, None)
            for n in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT"):
                if n in env:
                    g.env[n] = env[n]
            cmd.git = g
            if g.c_dirs:
                # from the folder the runners set (env -C, sudo -D); a -C the guard cannot read (or a wildcard) is
                # unknown (§1.7a, M1, M12)
                rc = None if "run-unknown" in cmd.flags else (tuple(cmd.run_cwds) if cmd.run_cwds else cwds)
                for d in g.c_dirs:
                    if d == "":
                        continue  # git -C "": the folder stays
                    rc = tuple(self.join_cwds(rc, d if d is not None else "")) or None
                cmd.run_cwds = list(rc or [])
                if not rc:
                    cmd.flags.add("run-unknown")
        opt = recog.cwd_option(prog, args)
        if opt is not None:
            base = [] if "run-unknown" in cmd.flags else (cmd.run_cwds or cwd_list(cwds))
            cmd.run_cwds = self.join_cwds(base, opt)
            if not cmd.run_cwds:
                cmd.flags.add("run-unknown")
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
                if val is not None and val.value is None:
                    op.skeleton = val.skeleton
                self.emit_later(deferred, op, cmd)
            elif mode == "stdin":
                self.stdin_opaque(cmd, cwds, state, stdin, deferred, "interp")
            elif mode == "script" and val is not None and val.value in ("/dev/stdin", "/dev/fd/0") and fam == "shell":
                self.stdin_opaque(cmd, cwds, state, stdin, deferred, "interp")  # `sh /dev/stdin <<< '…'` (m-b)
            elif mode == "script" and val is not None:
                self.script_call(cmd, prog, val, rest, cwds, state, stdin, lock_depth, deferred)
            elif mode == "other" and val is None and rest and any(w.value is None for w in rest[:1]):
                self.emit_later(deferred, Opaque("dynamic-command", payload=None, cwds=cwd_list(cwds)), cmd)
        elif "/" in words[0].value and cmd.s2v is None:
            self.script_call(cmd, None, words[0], args, cwds, state, stdin, lock_depth, deferred)
        # programs that run other programs
        pk, _end = runners.package(k, words, cmd.env.set)
        if pk is not None and pk.outcome in ("shell", "refused"):
            self.package_runner(cmd, pk, cwds, deferred)
        if k == "xargs":
            self.xargs(cmd, args, cwds, state, deferred)
        elif k in ("find", "gfind", "bfs"):
            self.find_exec(cmd, args, cwds, state, deferred)
        elif k == "parallel":
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

    # ---- stdin (review 6 M5-M7: one description for pipes, redirections, `exec` and function calls) ----

    def input_desc(self, r, state, cwds, cur, fds=None):
        """What an input redirection gives the fd it opens: ("redir", Redir) for a here-document or here-string,
        ("file", path or None), ("literal", text), ("unknown", None); `cur`: the fd 0 it replaces (`< /dev/stdin`
        keeps it). None: not an input redirection."""
        fds = state.fds if fds is None else fds
        if r.mode in ("heredoc", "herestring"):
            return ("redir", r)
        if r.mode == "close":
            return ("literal", "")
        if r.op == "<&" or (r.mode == "dup" and r.op.startswith("<")):
            n = r.target.value if r.target is not None else None
            if n == "0":
                return cur
            if n is not None and n.isdigit() and n in fds:
                return fds[n]
            return ("unknown", None)  # `<&3` of an fd the guard does not know, `<&$fd`
        if r.mode in ("read", "rw") and r.target is not None:
            v = r.target.value
            if v in STDIN_FILES:
                return cur  # `< /dev/stdin`: the pipe (review 5 M5)
            if v is None or not cwds or len(cwds) != 1:
                return ("file", None)
            return ("file", self.where.absolute(v, cwds[0]))
        return None

    @staticmethod
    def _fd(r):
        return r.fd if r.fd is not None else ("0" if r.op.startswith("<") else "1")

    def redirect_fds(self, redirs, stdin, state, cwds):
        """(fd 0, {fd: description}) after a command's redirections. zsh opens here-documents and here-strings
        first, so `sh <&3 3<<<…` reads it (checked in zsh 5.9)."""
        fds = dict(state.fds)
        for r in redirs:
            if r.mode in ("heredoc", "herestring") and self._fd(r) != "0":
                fds[self._fd(r)] = ("redir", r)
        cur = stdin
        multios = True  # zsh's default; judging every input is a superset of the last one when it is off
        seen = {}  # fd -> [descriptions of its input redirections] (review 9 B3)
        if stdin is not None and stdin is not state.fds.get("0"):
            seen["0"] = [stdin]  # a pipe is read first, then the redirections (zsh 5.9: `echo a | cat <<< b`)
        for r in redirs:
            fd = self._fd(r)
            if fd in ("1", "2") and r.mode in ("write", "append", "dup", "close") and not r.op.startswith("<"):
                continue
            d = self.input_desc(r, state, cwds, cur, fds)
            if d is None:
                d = ("unknown", None)  # an output fd 0 or 3: what reads it is unknown
            if multios and d != cur:
                # review 9 B3: MULTIOS (on by default) — several inputs on one fd are read one after the other;
                # review 10 B4: every kind (`<>`, `<&N`, an output on the fd) adds to them and none replaces the others
                seen.setdefault(fd, []).append(d)
                if len(seen[fd]) > 1:
                    d = self.joined_input(seen[fd], state)
            if fd == "0":
                cur = d
            else:
                fds[fd] = d
        return cur, fds

    def joined_input(self, descs, state):
        """review 9 B3: the input zsh gives a fd from several redirections (MULTIOS): their texts in order, as a
        here-string the guard reads (with parts it cannot read when any is dynamic); unknown when one is."""
        texts, dyn = [], False
        for kind, val in descs:
            if kind == "redir":
                texts.append(val.body or "")  # a here-string's body ends with its newline (make_redir)
                dyn = dyn or bool(val.body_dynamic) or val.body is None
            elif kind == "literal":
                texts.append(val or "")
            elif kind == "file" and val == "/dev/null":
                continue
            elif kind == "file" and val:
                t = state.written.get(val) if val in state.written else self.ctx.fs.read(val)
                if t is None:
                    dyn = True
                    continue
                texts.append(t)
            else:
                dyn = True  # a pipe or file the guard cannot read: the rest is still searched and judged
        return ("redir", Redir("0", "<<<", "herestring", body="".join(texts), body_dynamic=dyn))

    def command_input(self, cmd, stdin, state):
        """review 7 M4: (fd 0, {fd: description}) a command's eval, `-c` or sourced string runs with, a file this call
        wrote given as its text; None when it has no input (the Bash tool's /dev/null)."""
        cur, fds = self.redirect_fds(cmd.redirs, stdin, state, cmd.cwds)

        def m(d):
            if d is not None and d[0] == "file" and d[1] in state.written:
                return ("literal", state.written[d[1]])
            return d
        cur = m(cur)
        fds = {k: m(v) for k, v in fds.items()}
        if cur is None and not fds:
            return None
        return (cur, fds)

    def effective_stdin(self, redirs, stdin, state, cwds):
        return self.redirect_fds(redirs, stdin, state, cwds)[0]

    def _stdin(self, cmd, stdin, state):
        """(text, origin, kind, dynamic) of what a command reads on stdin."""
        d = self.effective_stdin(cmd.redirs, stdin, state, cmd.cwds)
        if d is None:
            # the Bash tool runs `eval '<cmd>' < /dev/null`: nothing arrives on stdin
            return "", "devnull", "stdin-interp", False
        kind, val = d
        if kind == "redir":
            if val.mode == "heredoc":
                return val.body, "heredoc", "heredoc-interp", val.body_dynamic
            return val.body, "herestring", "herestring-interp", val.body_dynamic
        if kind == "literal":
            return val, "pipe-literal", "stdin-interp", False
        if kind == "file":
            if val in state.written:
                return state.written[val], "linked-heredoc", "stdin-interp", False
            return (self.ctx.fs.read(val) if val else None), "file", "stdin-interp", False
        return None, "unknown", "stdin-interp", False

    def stdin_payload(self, cmd, stdin, state):
        return self._stdin(cmd, stdin, state)[:3]

    def stdin_opaque(self, cmd, cwds, state, stdin, deferred, what, kind_override=None, path=None, pclass=None):
        payload, origin, kind, dynamic = self._stdin(cmd, stdin, state)
        op = Opaque(kind_override or kind, payload=payload, origin=origin, cwds=cwd_list(cwds), path=path,
                    path_class=pclass)
        if dynamic:
            op.origin, op.skeleton = "dynamic", payload  # text with parts the guard cannot read (G1 §1.7, m1)
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
        if interp is None and recog.trusted_bin_dir(res.abs if res else None):  # G1 §4
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

    def package_runner(self, cmd, p, cwds, deferred):
        """npx -c 'cmd', pnpm exec -c …, yarn exec '…': a shell string; an option the guard cannot read: refused
        (G1 §1.3). The argv form is unwrapped by judge.effective."""
        if p.outcome == "refused":
            cmd.flags.add("runner-unread")
            op = Opaque("runner", payload="%s: %s" % (cmd.prog, p.reason), cwds=cwd_list(cwds))
            op.skeleton = " ".join(w.skeleton for w in cmd.words)
        else:
            text, skel = runners.shell_words_text(p.shell)
            op = Opaque("shell-c", payload=text, origin="literal" if text is not None else "dynamic",
                        cwds=cwd_list(cwds))
            op.skeleton = skel
        self.emit_later(deferred, op, cmd)

    def xargs(self, cmd, args, cwds, state, deferred):
        p = runners.parse(runners.XARGS, cmd.words, 1)
        if p.outcome == "refused":
            cmd.flags.add("runner-unread")
            op = Opaque("runner", payload="xargs: %s" % p.reason, cwds=cwd_list(cwds))
            op.skeleton = " ".join(w.skeleton for w in cmd.words)
            self.emit_later(deferred, op, cmd)
            return
        if p.outcome == "none":
            return  # --help, --version: no command runs
        tpl = cmd.words[p.end:] or [Word.lit("echo")]
        payload = " ".join(w.value if w.value is not None else w.skeleton for w in tpl)
        self.emit_later(deferred, Opaque("xargs", payload=payload, cwds=cwd_list(cwds)), cmd)
        tcwds = _run_of(cmd, cwds)

        def run_tpl():
            self.process(list(tpl) + [Word("{}", None, dynamic=True, dyn=["xargs-input"], skeleton="\0")], tcwds,
                         state.copy(), [], [], None, alt=cmd.alt, span=cmd.span, via_program=True, parent=cmd.id,
                         extra_ctx=("exec-template",))
        deferred.append(run_tpl)

    def find_exec(self, cmd, args, cwds, state, deferred):
        cwds = _run_of(cmd, cwds)  # the templates run in find's folder (env -C $D find …: unknown, M1)
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


def _run_of(cmd, cwds):
    """The folders a program runs in: its run folders, None when the guard cannot tell them, else the shell's."""
    if "run-unknown" in cmd.flags:
        return None
    return tuple(cmd.run_cwds) if cmd.run_cwds else cwds


NULLCMD_OK = ("cat", ":", "true", "more", "less", "")
SAFE_ARRAY_RE = re.compile(r"^\(\s*(?:[A-Za-z0-9_./,:@%=-]+\s*)*\)$")
STDIN_FILES = ("/dev/stdin", "/dev/fd/0", "/proc/self/fd/0")
QUAL_CODE_RE = r"\([^)]*[e+]"  # a glob qualifier that may run code (`(e:…:)`, `(+f)`)
DECL_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\[[^\]]*\])?\+?=")
# parameters zsh sets itself from a command's input (review 4 conf M-1)
IMPLICIT_PARAMS = {"REPLY", "reply", "match", "MATCH", "MBEGIN", "MEND", "mbegin", "mend", "OPTARG", "OPTIND",
                   "BUFFER", "LBUFFER", "RBUFFER", "CUTBUFFER", "_", "BASH_REMATCH"}  # $_: the last argument (review 5)
# zsh's special parameters that builtins write under other names (alias, hash, functions, cd, …): always steerable,
# fail closed (review 5 M2)
ZSH_SPECIAL_PARAMS = {"aliases", "galiases", "saliases", "dis_aliases", "dis_galiases", "dis_saliases", "functions",
                      "dis_functions", "functions_source", "dis_functions_source", "commands", "nameddirs",
                      "userdirs", "usergroups", "dirstack", "history", "historywords", "jobtexts", "jobdirs",
                      "jobstates", "builtins", "dis_builtins", "reswords", "dis_reswords", "options", "parameters",
                      "modules", "funcstack", "functrace", "funcfiletrace", "funcsourcetrace", "widgets", "keymaps",
                      "zsh_scheduled_events", "patchars", "dis_patchars", "errnos", "sysparams", "termcap",
                      "terminfo", "mapfile", "zsh_eval_context", "ZSH_EVAL_CONTEXT"}
QUIET_SPECIALS = {"#", "?", "$", "!", "-"}
POSITIONAL = ("argv", "@", "*")
INPUT_KINDS = ("shell-c", "eval", "env-S", "source")  # strings run with the host command's input (review 7 M4)
# names zsh ties to one parameter or pair (review 5 M2); `typeset -T` pairs the call makes go to steer_names
_TIED_GROUPS = (("PS1", "PROMPT", "prompt"), ("PS2", "PROMPT2"), ("PS3", "PROMPT3"), ("PS4", "PROMPT4"),
                ("RPS1", "RPROMPT"), ("RPS2", "RPROMPT2"), ("cdpath", "CDPATH"), ("psvar", "PSVAR"),
                ("manpath", "MANPATH"), ("watch", "WATCH"), ("fpath", "FPATH"), ("path", "PATH"),
                ("module_path", "MODULE_PATH"), ("mailpath", "MAILPATH"), ("fignore", "FIGNORE"),
                ("zsh_eval_context", "ZSH_EVAL_CONTEXT"), ("argv", "@", "*"))
TIED_NAMES = {n: g for g in _TIED_GROUPS for n in g}


def _safe_literal(w):
    """A word whose value is known and holds no glob qualifier that runs code (a literal loop value)."""
    return w.value is not None and not w.glob and not re.search(QUAL_CODE_RE, w.value)


def _param_name(raw):
    """(name, kind) of a parameter expansion: kind "number" (${#X}, ${+X}: a count or a flag), "simple" ($X, ${X},
    ${X[1]}, ${X:-word}, ${X:t} and other forms whose added text is literal and holds no `(`), or "complex" (an added
    `(…)`, a nested expansion or command substitution: the call's own text may hold a qualifier)."""
    m = re.match(r"^\$(\{)?(\([^)]*\))?([~=^#+]*)([A-Za-z_][A-Za-z0-9_]*|[0-9]+|[@*#?$!-])", raw or "")
    if not m:
        return None, "complex"
    if m.group(1) and ("#" in m.group(3) or "+" in m.group(3)):
        return m.group(4), "number"
    rest = raw[m.end():]
    if "P" in (m.group(2) or ""):
        return m.group(4), "complex"  # ${(P)X}: the parameter X names
    if "(" in rest or "$" in rest or "`" in rest or "&" in rest:
        return m.group(4), "complex"  # `:&`, `:g&`: the text of an earlier substitution (review 6 M1)
    return m.group(4), "simple"


def _paramx_value(raw, name):
    """(text, operator) of the first `${NAME::=text}`, `${NAME:=text}` or `${NAME=text}` in raw (review 6 M11)."""
    m = re.search(r"\$\{(?:\([^)]*\))?%s(?:\[[^\]]*\])?(::=|:=|=)" % re.escape(name), raw or "")
    if not m:
        return None, None
    depth, i = 1, m.end()
    while i < len(raw):
        if raw[i] == "\\":
            i += 2
            continue
        if raw.startswith("${", i):
            depth += 1
            i += 2
            continue
        if raw[i] == "}":
            depth -= 1
            if depth == 0:
                return raw[m.end():i], m.group(1)
        i += 1
    return None, m.group(1)


MAX_CANDS = 16
MAX_FORKS = 2  # review 9: nested re-walks of a list's rest from the folders a failed command leaves


def _cand_values(skel, dcands):
    """review 9: values a word may have from the candidates of its parts (each `\0` in its skeleton one part):
    every combination when each part has candidates, and the candidates of a part that are not its exact value (the
    words of a command whose output it is) on their own."""
    pieces = skel.split("\0")
    out, loose = [], []
    combos = None
    if len(pieces) == len(dcands) + 1 and all(dc and dc[1] for dc in dcands):
        combos = [pieces[0]]
        for i, dc_ in enumerate(dcands):
            vals = dc_[0]
            combos = [c + v + pieces[i + 1] for c in combos for v in vals]
            if len(combos) > 4 * MAX_CANDS:
                combos = None
                break
        if combos is not None:
            out.extend(combos)
    for dc in dcands:
        if dc and (not dc[1] or combos is None):
            loose.extend(dc[0])
    return list(dict.fromkeys(out)), list(dict.fromkeys(loose))
CAND_SEP_RE = re.compile(r"(\$\(|`|\|\||&&|[\s()|;&<>])")
LITERAL_OUTPUT = ("print", "echo", "printf")


def text_cands(text, state, lookup, exclude=()):
    """review 9: candidate values of a parameter written from `text` (the source of a value the guard does not carry:
    `(a b)`, `$(print …)`, `read X <<< …`): its literal words, quotes removed, `$NAME` resolved where the guard knows
    the value (or its candidates); command words, options and the names in `exclude` skipped. (values, exact): exact
    when the words are the value itself (an array of literals, print/echo output) rather than words of a command
    whose output the value is."""
    vals, exact = [], True
    cmdpos = False
    in_cmd = False
    for tok in CAND_SEP_RE.split(text or ""):
        if not tok or tok.isspace():
            continue
        if tok in ("$(", "`", "|", "||", "&&", ";", "&", "\n"):
            cmdpos = True
            in_cmd = True
            continue
        if tok in ("(", ")", "<", ">"):
            continue
        t = re.sub(r"['\"\\]", "", tok)
        if cmdpos:
            cmdpos = False
            if os.path.basename(t) not in LITERAL_OUTPUT:
                exact = False
            continue
        if not t or t.startswith(("-", "+")) or t in exclude:
            continue
        if "$" in t:
            m = re.match(r"^\$\{?([A-Za-z_][A-Za-z0-9_]*|[0-9]+)\}?$", t)
            v = lookup(m.group(1)) if m else None
            if isinstance(v, str):
                vals.append(v)
            elif m and state.cands.get(m.group(1)):
                c, e = state.cands[m.group(1)]
                vals.extend(c)
                exact = exact and e
            else:
                exact = False
            continue
        vals.append(t)
    if in_cmd and not vals:
        exact = False
    vals = tuple(dict.fromkeys(vals))
    if len(vals) > MAX_CANDS:
        return vals[:MAX_CANDS], False
    return vals, exact


FOLDER_REF_RE = re.compile(r"PWD|~\+|\bpwd\b|--show-toplevel")


def _simple_text(node):
    """The text of a simple command's words, assignment values and redirections (review 9 B1)."""
    out = [wn.raw or "" for wn in node.words]
    out += [v.raw or "" for _n, _s, _o, v, _w in node.assigns if v is not None]
    for r in node.redirs:
        if r.target is not None:
            out.append(r.target.raw or "")
        if r.heredoc is not None:
            out.append(r.heredoc.get("body") or "")
    return " ".join(out)


def _stack_mark(state):
    d = state.dirstack
    return (d if isinstance(d, StackAlts) else list(d) if d is not None else None, state.oldpwd,
            state.cands.get("~-"))


def _oldpwd_vals(oldpwd, cands):
    """(values, complete): complete False when $OLDPWD may hold a folder the guard cannot tell."""
    if oldpwd is not None:
        return (oldpwd,), True
    return (tuple(cands[0]), bool(cands[1])) if cands else ((), False)


def _oldpwd_union(state, a, b):
    """review 10: $OLDPWD (`~-`) is one of two readings' — unknown with both as candidates when they differ; when either
    may be a folder the guard cannot tell, the candidates are not the whole (`cd -` is then unknown)."""
    if a[0] == b[0] and a[1] == b[1]:
        return
    va, ca = _oldpwd_vals(*a)
    vb, cb = _oldpwd_vals(*b)
    vals = tuple(dict.fromkeys(va + vb))
    state.oldpwd = None
    if vals:
        state.cands["~-"] = (vals[:MAX_CANDS], ca and cb and len(vals) <= MAX_CANDS)
    else:
        state.cands.pop("~-", None)


def _stack_unsure(state, mark):
    """review 9 B1: code that may or may not have run changed the directory stack: review 10 (the union rule) — it
    is one of the stacks before or after; unknown when either is."""
    if mark is None:
        return
    if state.dirstack != mark[0]:
        a, b = stack_alts(mark[0]), stack_alts(state.dirstack)
        if a is None or b is None:
            state.dirstack = None
        else:
            set_stack_alts(state, a + b)
    if len(mark) > 2:
        _oldpwd_union(state, (mark[1], mark[2]), (state.oldpwd, state.cands.get("~-")))
    # $OLDPWD keeps the value the move gives: `cd -` is then judged there (the shell's own earlier $OLDPWD is not
    # known either way)


_MISSING = object()


class ValueMark(object):
    """review 10 B2/B3: the parameters' values at one point of the walk (vars, candidates, source text, the names
    known to hold safe values or arrays), to tell later what code that may or may not have run changed."""

    def __init__(self, state):
        self.vars = dict(state.vars)
        self.cands = dict(state.cands)
        self.raw = dict(state.raw_values)
        self.safe = set(state.safe_values)
        self.arrays = set(state.arrays)
        self.env_unknown = state.env_unknown
        self.funcs = dict(state.funcs)
        self.complete = dict(state.complete)


def _funcs_unsure(state, mark):
    """review 10: a function defined (or redefined) by code that may not have run may not exist when called: what
    its body writes is then a write that may not happen (the previous definition's too). Review 11 B1: one removed by
    such code (`[[ … ]] || unfunction f`) may still exist."""
    for n, e in list(state.funcs.items()):
        if mark.funcs.get(n) is not e and not (isinstance(e, dict) and e.get("maybe_def") and
                                                 e.get("prev") is mark.funcs.get(n)):
            d = dict(e)
            d["maybe_def"], d["prev"] = True, mark.funcs.get(n)
            state.funcs[n] = d
    for n, e in mark.funcs.items():
        if n not in state.funcs and isinstance(e, dict):
            state.funcs[n] = maybe_removed(e)


FUNC_CHAIN = 4  # review 11 B1: definitions a call may run (maybe_def / prev), followed this deep


def _choice_word(word, v):
    """review 11 M-1: a word standing for one of its known values, read as written."""
    w = copy.copy(word)
    w.value, w.dynamic, w.dyn, w.skeleton, w.alt = v, False, [], v, None
    w.cand_values, w.cand_loose, w.cand_complete = (), (), False
    w.drop = w.maybe_empty = w.multi = False
    w.wild = frozenset()
    return w


def _same_def(a, b):
    """review 11 B1: two function-table entries for the same definition (the same body text, walked in different
    readings), none of them one the guard cannot tell or one that may not exist."""
    if a is b:
        return True
    if not (isinstance(a, dict) and isinstance(b, dict)) or a.get("body") is None or a.get("body") is not b.get("body"):
        return False
    return not any(e.get(k) for e in (a, b) for k in ("unknown_def", "maybe_def"))


def _call_alternatives(eff, depth=0):
    """review 11 B1: the definitions a call of a function this call defined may run — dicts, None for no function —
    and whether one the guard cannot tell may run instead."""
    if eff is None:
        return [None], False
    if not isinstance(eff, dict) or eff.get("unknown_def") or depth > FUNC_CHAIN:
        return [], True
    if eff.get("maybe_def"):
        rest, unknown = _call_alternatives(eff.get("prev"), depth + 1)
        return [eff] + rest, unknown
    return [eff], False


def maybe_removed(e, depth=0):
    """review 11 B1: a function this call defined that may have been removed: this definition, an earlier one it
    may not have replaced, or none (the name then runs a command or is not found)."""
    if not isinstance(e, dict):
        return None
    if e.get("unknown_def") or depth >= FUNC_CHAIN:
        return dict(e, unknown_def=True)
    d = dict(e)
    d["maybe_def"], d["prev"] = True, (maybe_removed(e["prev"], depth + 1) if e.get("maybe_def") else None)
    return d


def funcs_unknown(state, names=None):
    """review 11 B1: zsh's function table may have changed in a way the guard does not follow (an eval or a sourced
    file, `emulate … -c`, a definition under a name it cannot read, a function or hook it cannot read, `unfunction -m`
    with a pattern, a later `enable`): each function this call defined (or each of `names`) may be gone, redefined or
    kept. A call of one is then judged as before G1 walked them: the folder and the values it may write unknown."""
    for n, e in list(state.funcs.items()):
        if (names is None or n in names) and isinstance(e, dict) and not e.get("unknown_def"):
            state.funcs[n] = dict(e, unknown_def=True)


def funcs_remove(state, names, sure=True):
    """review 11 B1: `unfunction NAME`, `unhash -f NAME`, `unset -f NAME`, `disable -f NAME`: a later call of NAME
    runs a command so named (or none). `sure` False: it may or may not be removed."""
    for n in names:
        if n in state.funcs:
            if sure:
                state.funcs.pop(n)
            else:
                state.funcs[n] = maybe_removed(state.funcs[n])


def funcs_matching(state, pattern):
    """The functions this call defined whose name zsh pattern `pattern` matches for sure, and those it may match (a
    pattern with more than `*` and `?`: every one)."""
    if pattern is None or not re.match(r"^[A-Za-z0-9_.*?+:@%-]*$", pattern):
        return set(), set(state.funcs)
    sure = {n for n in state.funcs if fnmatch.fnmatchcase(n, pattern)}
    return sure, set()


# command words that change zsh's function table (review 11 B1)
TABLE_WORDS = {"unfunction", "unhash", "disable", "enable", "functions", "eval", "source", ".", "emulate", "autoload",
               "zmodload", "zle"}


def body_touches_funcs(body, state=None):
    """review 11 B1: whether a body (a function's, a hook's) may change zsh's function table: a word that removes,
    defines or runs code by name (unfunction, unhash, disable, enable, functions, eval, source, emulate, autoload,
    unset -f), a command word the guard cannot read, a definition, or a call of a function of this call that does."""
    if body is None:
        return False
    stack = [body]
    while stack:
        x = stack.pop()
        if isinstance(x, Compound) and x.kind == "funcdef":
            return True
        if isinstance(x, Compound):
            for k in ("body", "cond", "else_body", "cmd"):
                if getattr(x, k, None) is not None:
                    stack.append(getattr(x, k))
            for c, b in getattr(x, "clauses", None) or ():
                stack += [c, b]
            for _p, b in getattr(x, "arms", None) or ():
                stack.append(b)
        elif isinstance(x, ListNode):
            stack += [ao for ao, _s in x.items]
        elif isinstance(x, AndOr):
            stack += [x.first] + [pl for _o, pl in x.rest]
        elif isinstance(x, Pipeline):
            stack += list(x.cmds)
        elif isinstance(x, Simple):
            for name, _s, _o, _v, _w in x.assigns:
                if name.split("[")[0] in ("functions", "dis_functions", "functions_source"):
                    return True
            ws = [_lit(w) for w in x.words]
            k = 0
            while k < len(ws) and ws[k] in FUNC_PRECOMMANDS:
                k += 1
            if k >= len(ws):
                continue
            if ws[k] is None or ws[k] in TABLE_WORDS:
                return True
            if ws[k] == "unset" and any(a is None or (a[:1] == "-" and "f" in a) for a in ws[k + 1:]):
                return True
            e = state.funcs.get(ws[k]) if state is not None else None
            if isinstance(e, dict) and (e.get("fntable") or e.get("unknown_def")):
                return True
        else:
            return True
    return False


def _possible(v, c, env_val=_MISSING):
    """(values, exact, unknown) a parameter may hold: v its entry in state.vars (a string, DYN or _MISSING), c its
    candidates; env_val the hook's environment value when v is _MISSING (_MISSING: unknown, None: unset)."""
    if isinstance(v, str):
        return (v,), True, False
    if v is DYN or (v is _MISSING and c):
        return (tuple(c[0]), bool(c[1]), True) if c else ((), True, True)
    if env_val is _MISSING:
        return (), True, True
    if isinstance(env_val, str):
        return (env_val,), True, False
    return (), True, False  # unset: empty, nothing to judge


def _changed_names(mark, state):
    names = set()
    for n in set(mark.vars) | set(state.vars):
        a, b = mark.vars.get(n, _MISSING), state.vars.get(n, _MISSING)
        if not (a is b or (isinstance(a, str) and a == b)):
            names.add(n)
    for n in set(mark.cands) | set(state.cands):
        if mark.cands.get(n) != state.cands.get(n):
            names.add(n)
    return {n for n in names if not n.startswith("~")}


def _env_value(ctx, mark_or_state, name):
    if getattr(mark_or_state, "env_unknown", False):
        return _MISSING
    return ctx.env.get(name)


def union_values(ctx, state, name, readings):
    """review 10 (one rule for every uncertainty): `name` holds the value of one of `readings` (ValueMark or State,
    each a way the code may have run). Its possible values are their union; when any reading's value is unknown the
    whole is unknown (DYN) and the known values stay candidates, judged where the value is used — never only the
    known ones, never dropped."""
    vals, exact, unknown, raws = [], True, False, []
    from_call = False  # an unknown member this call may have put there (not only the environment's value)
    safe = True
    is_array = False
    for r in readings:
        vs = r.vars if isinstance(r, ValueMark) else r.vars
        cs = r.cands if isinstance(r, ValueMark) else r.cands
        v = vs.get(name, _MISSING)
        pv, pe, pu = _possible(v, cs.get(name), _env_value(ctx, r, name) if v is _MISSING else _MISSING)
        vals.extend(pv)
        exact = exact and pe
        unknown = unknown or pu
        if pu and v is not _MISSING:
            mk = r.complete.get(name)
            if not (mk is not None and mk[0] is cs.get(name)) or mk[1] == "oldpwd":
                from_call = True
            elif mk[1] == "env":
                pass  # an earlier union whose unknown member was the environment's
            # ("complete": no unknown member)
        rw = (r.raw if isinstance(r, ValueMark) else r.raw_values).get(name)
        if rw:
            raws.append(rw)
        sv = r.safe if isinstance(r, ValueMark) else r.safe_values
        if v is not _MISSING and name not in sv:
            safe = False
        if name in (r.arrays if isinstance(r, ValueMark) else r.arrays):
            is_array = True
    vals = tuple(dict.fromkeys(vals))
    if not unknown and len(vals) == 1:
        state.vars[name] = vals[0]
        state.cands.pop(name, None)
    elif not unknown and not vals:
        state.vars.pop(name, None)
        state.cands.pop(name, None)
    else:
        state.vars[name] = DYN
        if vals:
            state.cands[name] = (vals[:MAX_CANDS], exact and len(vals) <= MAX_CANDS)
            if exact and len(vals) <= MAX_CANDS and not from_call:
                # one of exactly these (cands_complete), or of these and a value only the environment (or a function
                # the guard cannot read, as before) put there
                state.complete[name] = (state.cands[name], "env" if unknown else "complete")
        else:
            state.cands.pop(name, None)
    if raws:
        state.raw_values[name] = " ".join(dict.fromkeys(raws))
    if safe:
        state.safe_values.add(name)
    else:
        state.safe_values.discard(name)
    if is_array:
        state.arrays.add(name)


def cands_complete(state, name):
    """review 10: whether a value the guard does not carry is one of exactly its candidates (no unknown member): set
    by union_values, and valid while those candidates are the ones it recorded (any later write replaces them)."""
    return _complete_kind(state, name) == "complete"


def _complete_kind(state, name):
    c = state.cands.get(name)
    mk = state.complete.get(name)
    if c is None or mk is None or mk[0] is not c or state.vars.get(name) is not DYN:
        return None
    return mk[1]


def value_unsure(ctx, state, mark):
    """review 10 B3: code that may or may not have run (a condition, a loop body, a command whose redirection may
    fail) changed parameters since `mark`: each holds its old value or the new one."""
    if mark is None:
        return
    for n in sorted(_changed_names(mark, state)):
        union_values(ctx, state, n, (mark, state))
    _funcs_unsure(state, mark)


def value_restore(state, mark, names=None):
    """Put the values of `names` (default: every changed one) back as they were at `mark` (the next branch of an `if`
    or a `case` starts from there)."""
    for n in (_changed_names(mark, state) if names is None else names):
        for d, md in ((state.vars, mark.vars), (state.cands, mark.cands), (state.raw_values, mark.raw)):
            if n in md:
                d[n] = md[n]
            else:
                d.pop(n, None)
        for s, ms in ((state.safe_values, mark.safe), (state.arrays, mark.arrays)):
            if n in ms:
                s.add(n)
            else:
                s.discard(n)


def value_join(ctx, state, mark, ends):
    """The values after a branch construct: `ends` are ValueMarks at the end of each way through it (a body, or no
    body). A name changed on any way holds one of the values the ways give."""
    names = set(_changed_names(mark, state))
    for e in ends:
        names |= _changed_names(mark, e)
    for n in sorted(names):
        union_values(ctx, state, n, tuple(ends))
    _funcs_unsure(state, mark)


def merge_states(state, copies, ctx=None):
    """review 9 B1: `state` after one reading of a command and `copies` after the others (one per folder it may run
    in): a value that differs between them becomes one of those values — unknown, with the known ones as candidates
    (state.cands, judged where the value is used); the stack, $OLDPWD and PATH become unknown. Review 10: the union
    rule (union_values): a known value next to an unknown one stays a candidate."""
    for c in copies:
        names = set()
        for name in set(c.vars) | set(state.vars) | set(c.cands) | set(state.cands):
            if name.startswith("~"):
                continue
            a, b = c.vars.get(name, _MISSING), state.vars.get(name, _MISSING)
            if (a is b or (isinstance(a, str) and a == b)) and c.cands.get(name) == state.cands.get(name):
                continue
            names.add(name)
        for name in sorted(names):
            if ctx is not None:
                union_values(ctx, state, name, (c, state))
                continue
            vals, exact, unknown = [], True, False
            for st in (c, state):
                pv, pe, pu = _possible(st.vars.get(name, _MISSING), st.cands.get(name))
                vals.extend(pv)
                exact, unknown = exact and pe, unknown or pu
            vals = tuple(dict.fromkeys(vals))
            state.vars[name] = DYN
            state.safe_values.discard(name)
            if vals:
                state.cands[name] = (vals[:MAX_CANDS], exact and len(vals) <= MAX_CANDS)
            else:
                state.cands.pop(name, None)
            state.raw_values[name] = " ".join(dict.fromkeys(
                [x for x in (c.raw_values.get(name), state.raw_values.get(name)) if x]))
        if c.dirstack != state.dirstack:
            a, b = stack_alts(c.dirstack), stack_alts(state.dirstack)
            if a is None or b is None:
                state.dirstack = None
            else:
                set_stack_alts(state, a + b)  # review 10: one of the two
        if c.oldpwd != state.oldpwd or c.cands.get("~-") != state.cands.get("~-"):
            _oldpwd_union(state, (c.oldpwd, c.cands.get("~-")), (state.oldpwd, state.cands.get("~-")))
        if c.paths != state.paths:
            state.paths, state.path_modified = None, True
        if c.env_unknown:
            state.env_unknown = True
        # review 11 B1: a function one reading removed or replaced may still be there in another
        for n in set(c.funcs) | set(state.funcs):
            a, b = c.funcs.get(n), state.funcs.get(n)
            if a is b:
                continue
            if a is None or b is None:
                state.funcs[n] = maybe_removed(a if b is None else b)
            elif not _same_def(a, b):
                state.funcs[n] = dict(b, unknown_def=True)
        ops = [(o.kind, o.name, getattr(o.value, "value", None)) for o in c.env_ops]
        mine = [(o.kind, o.name, getattr(o.value, "value", None)) for o in state.env_ops]
        if ops != mine:
            names = set()
            for i in range(max(len(ops), len(mine))):
                a, b = ops[i] if i < len(ops) else None, mine[i] if i < len(mine) else None
                if a != b:
                    names.update(x[1] for x in (a, b) if x is not None and x[1])
            for n in sorted(names):
                state.env_ops.append(EnvOp("merge", "set", n, _unknown_value(n.split("[")[0])))


def _unknown_value(name):
    return Word("$" + name, None, dynamic=True, dyn=["param:" + name], skeleton="\0")


def _table_named(w):
    """A word of a name-writing builtin that names (or, dynamic, may name) one of zsh's tables (G1 §1.8)."""
    if w.value is not None:
        return cmdopts.table_word(w.value)
    sk = w.skeleton or ""
    return sk.startswith("\0") or cmdopts.table_word(sk.replace("\0", "x"))


def _dropped_before(kept):
    """ids of the words right before a word the shell drops (an unquoted empty expansion)."""
    return {id(kept[i - 1]) for i, w in enumerate(kept) if w.drop and i > 0} or None


def _value_dropped(spec, words, i, dropped):
    """Whether the runner rejects this reading because a word right before a dropped word is an option that takes a
    separate value, and the word it takes instead is no value it accepts: none is left, or the option takes a number
    and the word is not one (G1 §1.2, M4). The runner then runs nothing."""
    rest = words[i + 1:]
    for k, w in enumerate(rest):
        if id(w) not in dropped or w.value is None or not w.value.startswith("-"):
            continue
        v = w.value
        name = v if v.startswith("--") else "-" + v[-1]
        if spec.opts.get(name) not in runners.VALUE_KINDS:
            continue
        nxt = rest[k + 1] if k + 1 < len(rest) else None
        if nxt is None or runners.number_refused(spec, name, nxt):
            return True
    return False


# ---- snapshot user functions (review 2 conformance, R2-M1) ----

FUNC_DEPTH = 4  # functions a snapshot function calls, followed this deep
FUNC_UNKNOWN = {"source", ".", "eval", "trap", "disable", "enable", "zmodload", "functions", "emulate-c", "zle", "sched",
                "coproc"}
FUNC_NAMES = ("autoload", "unfunction", "unalias", "unhash", "alias", "hash")  # they change what a name runs
FUNC_LOCALS = ("local", "typeset", "declare", "integer", "float", "readonly", "private")
FUNC_PRECOMMANDS = ("builtin", "command", "noglob", "nocorrect", "-", "exec", "time", "nohup")
FUNC_CD = ("cd", "chdir", "pushd", "popd")
# an arithmetic assignment (or ++/--) to a parameter named by an expansion (review 4 m2)
ARITH_DYN_ASSIGN_RE = re.compile(r"\$\{?[^\s=]*\}?\s*(\[[^\]]*\])?\s*((\*\*|<<|>>|[-+*/%&|^])?=(?!=)|\+\+|--)|"
                                 r"(\+\+|--)\s*\$")
ARITH_ASSIGN_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*(\[[^\]]*\])?\s*(?:\*\*|<<|>>|[-+*/%&|^])?=(?!=)|"
                             r"(?:\+\+|--)\s*([A-Za-z_][A-Za-z0-9_]*)|([A-Za-z_][A-Za-z0-9_]*)\s*(?:\+\+|--)")
# globals a function may set that reach later commands although not exported (review 3, M-3): the folder, git's and
# the guard's own variables, the hook arrays zsh runs, word splitting
FUNC_WATCHED = {"PATH", "path", "HOME", "XDG_CONFIG_HOME", "ZDOTDIR", "CDPATH", "cdpath", "OLDPWD", "PWD", "dirstack",
                "IFS", "chpwd_functions", "precmd_functions", "preexec_functions", "periodic_functions",
                "zshexit_functions", "zshaddhistory_functions", "BASH_ENV", "ENV", "TMPDIR", "NULLCMD", "READNULLCMD"}


DBRACKET_RE = re.compile(r"\[\[\s([^\n]*?)\s\]\]")


class _Unknown(Exception):
    pass


# review 4 m3, R1: functions and arrays zsh runs by name after commands, folder changes, errors, signals or at exit
HOOK_FUNCS = {"chpwd", "precmd", "preexec", "periodic", "zshexit", "zshaddhistory", "command_not_found_handler"}
HOOK_ARRAYS = {"chpwd_functions", "precmd_functions", "preexec_functions", "periodic_functions", "zshexit_functions",
               "zshaddhistory_functions"}


def is_hook_function(name):
    return name in HOOK_FUNCS or (name or "").startswith("TRAP")


# review 10 B1/M1: when zsh runs a hook in the Bash tool's shell (non-interactive `zsh -c`): precmd, preexec, periodic
# and zshaddhistory never; zshexit, TRAPEXIT and `trap … EXIT` at the shell's end (an EXIT trap or TRAPEXIT set in a
# function: when the function returns); DEBUG, ZERR, ERR and command_not_found_handler between commands; chpwd after
# a folder change; a signal trap when the signal arrives (from any command, so between commands too)
NEVER_HOOKS = {"precmd", "preexec", "periodic", "zshaddhistory", "precmd_functions", "preexec_functions",
               "periodic_functions", "zshaddhistory_functions", "zshexit", "zshexit_functions"}


def trap_kind(sig):
    """'exit', 'between' (DEBUG, ZERR, ERR) or 'signal' for a trap's signal name or number; None: unknown."""
    if sig is None:
        return None
    s = sig.upper()
    if s.startswith("SIG"):
        s = s[3:]
    if s in ("EXIT", "0"):
        return "exit"
    if s in ("DEBUG", "ZERR", "ERR"):
        return "between"
    return "signal"


def hook_kind(name):
    """'never', 'exit', 'between', 'signal' or 'chpwd' for a hook function or array name."""
    if name in NEVER_HOOKS:
        return "never"
    if name in ("chpwd", "chpwd_functions"):
        return "chpwd"
    if name == "command_not_found_handler":
        return "between"
    if (name or "").startswith("TRAP"):
        return trap_kind(name[4:]) or "between"
    return "between"


def snapshot_hooks(ctx, state):
    """review 4 m3: snapshot hook functions that run in a Bash call before or between its commands (TRAP*,
    command_not_found_handler; chpwd at each folder change: Walker.after_chpwd). precmd, preexec, periodic and
    zshaddhistory run only in an interactive shell, zshexit at its end."""
    snap = ctx.snapshot
    if snap is None:
        return
    for name in sorted(snap.user_functions):
        if name.startswith("TRAP") or name == "command_not_found_handler":
            kind = hook_kind(name)
            if kind == "exit":
                continue  # TRAPEXIT: at the shell's end, after every command (review 10 M1)
            eff = snapshot_function_effects(ctx, name)
            if eff is None and kind == "signal":
                # review 10 M1: a signal trap of yours the guard cannot read (`TRAPWINCH(){ zle && zle -R }`) runs
                # only when that signal reaches the shell — assumed not to (as before G1; guard-limits)
                continue
            apply_function_effects(ctx, state, eff, None)
            if eff is None or eff["cwd"]:
                state.hook_cwd = True
                state.pwd_steered = True


def text_effects(ctx, text, inline=None):
    """The effects of a shell string run in this shell later (a trap action; review 4 R1), or None when the guard
    cannot read it — a command that is no builtin and not found on PATH may be a function defined later. Review 10
    M1: `inline` — the functions this call defined so far (name -> Walker.function_effects): a name among them is read
    by its effects (`cleanup(){ rm -f $tmp }; trap cleanup INT`)."""
    from .parse import Parser
    from .scanctx import Oracle, ScanCtx
    try:
        pctx = ScanCtx(ctx.env, ctx.fs, snapshot=None, budget=ctx.budget)
        pctx.oracle, pctx.tokens, pctx.depth = Oracle([], lambda taken, n: False), 0, 0
        ast = Parser(text, pctx).parse_program()
        sc = _FuncScan(ctx, 0, set(), strict=True)
        sc.inline = dict(inline or {})
        sc.node(ast)
    except _Unknown:
        return None
    except Exception:  # noqa: BLE001 — a string the guard cannot read: unknown (closed side)
        return None
    return {"env": sc.env, "globals": sc.globals, "options": sc.opts, "options_unknown": sc.options_unknown,
            "local": sc.local, "cwd": sc.cwd, "shadowed": sc.shadowed}


def snapshot_function_effects(ctx, name):
    """What a snapshot user function may change for the caller, or None when the guard cannot read it (an eval, a
    source, a command word or a parameter name it cannot read, a change to zsh's tables, a trap). A dict:
    "env": it exports (export, typeset -x, set -a/allexport); "globals": the names it assigns outside the function
    (not declared local unconditionally at its top level: a `local` on a branch may not run); "options": the literal
    options it sets {name: True/False/None (maybe)}; "options_unknown": an option it sets the guard cannot name
    (`set -y`, `emulate zsh`); "local": LOCAL_OPTIONS when it returns (True, False, None maybe, "inherit" untouched);
    "shadowed": names it autoloads, aliases or unfunctions (later commands so named are ones the guard cannot read);
    "cwd": it may change the folder (cd/chdir/pushd/popd, or a function it calls does). Functions it calls are followed
    FUNC_DEPTH deep (review 3, M-1 to M-4)."""
    cache = ctx.__dict__.setdefault("func_effects", {})
    if name not in cache:
        try:
            cache[name] = _function_effects(ctx, name, 0, set())
        except _Unknown:
            cache[name] = None
        except Exception:  # noqa: BLE001 — a body the guard cannot read: unknown (closed side)
            cache[name] = None
    return cache[name]


def _function_effects(ctx, name, depth, seen):
    from .parse import Parser
    from .scanctx import Oracle, ScanCtx
    snap = ctx.snapshot
    if depth > FUNC_DEPTH or snap is None:
        raise _Unknown()
    texts = snap.function_bodies(name)
    if not texts:
        raise _Unknown()
    seen = seen | {name}
    eff = {"env": False, "globals": set(), "options": {}, "options_unknown": False, "local": "inherit", "cwd": False,
           "shadowed": set()}
    locals_ = []
    for text in texts:  # several snapshots: any of the definitions may run
        # a [[ … ]] test with no expansion that can assign or run code changes nothing: read as `[[ x ]]` (the parser
        # does not read zsh's =~ patterns with groups, `[[ $1 =~ ^(https?|ftp).*$ ]]`)
        text = DBRACKET_RE.sub(lambda m: m.group(0) if re.search(r"\$\{|\$\(|\(\(|`", m.group(1)) else "[[ x ]]", text)
        pctx = ScanCtx(ctx.env, ctx.fs, snapshot=None, budget=ctx.budget)
        pctx.oracle, pctx.tokens, pctx.depth = Oracle([], lambda taken, n: False), 0, 0
        ast = Parser(text, pctx).parse_program()
        items = ast.items
        if len(items) != 1 or items[0][0].rest or len(items[0][0].first.cmds) != 1:
            raise _Unknown()
        fd = items[0][0].first.cmds[0]
        if not isinstance(fd, Compound) or fd.kind != "funcdef":
            raise _Unknown()
        sc = _FuncScan(ctx, depth, seen)
        sc.node(fd.body)
        eff["env"] = eff["env"] or sc.env
        eff["globals"] |= sc.globals
        eff["cwd"] = eff["cwd"] or sc.cwd
        eff["shadowed"] |= sc.shadowed
        eff["options_unknown"] = eff["options_unknown"] or sc.options_unknown
        for k, v in sc.opts.items():
            eff["options"][k] = v if eff["options"].get(k, v) == v else None
        locals_.append(sc.local)
    eff["local"] = locals_[0] if all(x == locals_[0] for x in locals_) else None
    return eff


class _FuncScan(object):
    """One function body: what it may change for the caller (snapshot_function_effects); raises _Unknown at the first
    thing the guard cannot follow."""

    def __init__(self, ctx, depth, seen, strict=False):
        self.ctx, self.depth, self.seen = ctx, depth, seen
        self.strict = strict  # a command not on PATH and no builtin: unknown (a function defined later)
        self.locals = set()
        self.globals = set()
        self.env = False
        self.cwd = False
        self.opts = {}
        self.options_unknown = False
        self.local = "inherit"  # LOCAL_OPTIONS: True, False, None (maybe), "inherit" (untouched)
        self.shadowed = set()  # names later commands may run as a function or alias the guard cannot read
        self.cond = 0  # inside a branch, a loop or after && / || (may not run)
        self.inline = {}  # review 10 M1: functions the call defined (text_effects)

    def node(self, n):
        if n is None:
            return
        if isinstance(n, ListNode):
            for ao, _sep in n.items:
                self.node(ao)
        elif isinstance(n, AndOr):
            self.node(n.first)
            self.cond += 1
            for _op, pl in n.rest:
                self.node(pl)
            self.cond -= 1
        elif isinstance(n, Pipeline):
            for c in n.cmds:
                self.node(c)
        elif isinstance(n, Simple):
            self.simple(n)
        elif isinstance(n, Compound):
            self.compound(n)
        else:
            raise _Unknown()  # an alias overflow or a node the guard does not know

    def compound(self, n):
        k = n.kind
        if k == "subshell":
            return  # its own process: nothing it sets reaches the caller
        if k == "group":
            self.node(n.body)
            return
        self.cond += 1
        try:
            if k == "if":
                for cond, body in n.clauses:
                    self.node(cond)
                    self.node(body)
                self.node(n.else_body)
            elif k == "while":
                self.node(n.cond)
                self.node(n.body)
            elif k == "for":
                for vname in getattr(n, "vars", None) or ([n.var] if n.var else []):
                    self.assigned(vname)
                for w in n.items or ():
                    self.word(w)
                self.node(n.body)
            elif k == "case":
                self.word(n.word)
                for _pats, body in n.arms:
                    self.node(body)
            elif k == "dbracket":
                for w in n.words:
                    if isinstance(w, WordNode):
                        self.word(w)
            elif k == "arith":
                self.arith(n.raw)
            else:
                raise _Unknown()  # funcdef (a function table change), coproc, …
        finally:
            self.cond -= 1

    def assigned(self, name):
        """A parameter set by name: the function's own when declared local before, else a global (one of zsh's
        tables: unknown)."""
        if not name or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*(\[.*\])?$", name, re.S):
            raise _Unknown()  # a name the guard cannot read
        base = name.split("[")[0]
        if cmdopts.table_word(base):
            raise _Unknown()  # options, commands, functions, …
        if base not in self.locals:
            self.globals.add(base)

    def arith(self, raw):
        if ARITH_DYN_ASSIGN_RE.search(raw or ""):
            raise _Unknown()  # `(( $1 = 1 ))`: a name the guard cannot read is assigned (review 4 m2)
        for m in ARITH_ASSIGN_RE.finditer(raw or ""):
            self.assigned(m.group(1) or m.group(3) or m.group(4))

    def word(self, wn):
        if wn is None:
            return
        raw = wn.raw or ""
        if "${" in raw:
            why = cmdopts.paramx_problem(raw)
            if why in ("eval", "table"):
                raise _Unknown()
            for n_ in cmdopts.paramx_assigned(raw):
                self.assigned(n_)
        for part in wn.parts:
            if part[0] == "arith":
                self.arith(part[1])
            elif part[0] == "dyn" and part[1] == "paramx" and re.match(r"^\$\{?\(?[^)]*[~]|^\$\{?~", part[2]):
                raise _Unknown()  # a pattern from a value: glob qualifiers may run code in this shell

    def set_opt(self, name, on):
        n = name.lower().replace("_", "")
        if n.startswith("no") and n not in ("nomatch", "notify"):
            n, on = n[2:], not on
        if not re.match(r"^[a-z0-9]+$", n):
            self.options_unknown = True
            return
        if n == "allexport":
            self.env = True
        if n == "localoptions":
            self.local = None if self.cond else on
            return
        self.opts[n] = None if self.cond else on

    def simple(self, n):
        for name, sub, _op, val, _ws in n.assigns:
            self.word(val)
            if not n.words:
                self.assigned(name + (sub or ""))
        for w in n.words:
            self.word(w)
        if not n.words:
            return
        texts = []
        for w in n.words:
            if any(p[0] != "lit" for p in w.parts):
                texts.append(None)
            else:
                texts.append("".join(p[1] for p in w.parts))
        i = 0
        while i < len(texts) and texts[i] in FUNC_PRECOMMANDS:
            i += 1
            while i < len(texts) and texts[i] is not None and texts[i].startswith("-") and texts[i] != "-":
                i += 1  # command -p, exec -c, …
        if i >= len(texts):
            return
        prog = texts[i]
        args = texts[i + 1:]
        if prog is None:
            raise _Unknown()  # a command word the guard cannot read
        if prog in FUNC_UNKNOWN or prog in ("}", "{", "always") or "always" in texts:
            raise _Unknown()  # `{ HOME=x } always { … }`: the parser does not read `always` blocks (review 3, m1)
        snap = self.ctx.snapshot
        if prog in FUNC_CD or (snap is not None and _alias_changes_folder(snap, prog)):
            self.cwd = True
        if prog == "export":
            self.env = True
            return
        if prog in FUNC_NAMES:
            self.names(prog, args)
            return
        if prog in FUNC_LOCALS:
            self.declare(prog, n.words[i + 1:])
            return
        if prog == "unset":
            if any(a is None or (a.startswith("-") and a not in ("-v",)) for a in args):
                raise _Unknown()
            for a in args:
                if a != "-v":
                    self.assigned(a)
            return
        if prog == "set":
            self.set_(args)
            return
        if prog in ("setopt", "unsetopt"):
            for a in args:
                if a is None:
                    self.options_unknown = True
                elif a[:1] in "-+" and len(a) > 1:
                    self.options_unknown = True  # single-letter option flags (`setopt -4`)
                else:
                    self.set_opt(a, prog == "setopt")
            return
        if prog == "emulate":
            if any(a is None or a == "-c" for a in args):
                raise _Unknown()
            if any(re.match(r"^-[A-Za-z]*L", a) for a in args):
                self.local = None if self.cond else True
            elif any(not a.startswith("-") for a in args):
                self.options_unknown = True
            return
        if prog == "let":
            for a in args:
                if a is None:
                    raise _Unknown()
                self.arith(a)
            return
        if prog in cmdopts.NAME_WRITERS and cmdopts.name_writer(prog, [a for a in args if a is not None]):
            if any(a is None for a in args):
                raise _Unknown()
            for nm in cmdopts.written_names(prog, args):
                self.assigned(nm)
            return
        if prog in self.inline:
            e = self.inline[prog]
            if e is None or e.get("tables") or e.get("defs") or e.get("funcs"):
                raise _Unknown()  # it defines functions or writes zsh's tables: what runs later is unknown
            self.cwd = self.cwd or bool(e.get("cwd") or e.get("hook"))
            self.env = self.env or bool(e.get("env") or e.get("paths"))
            for g in e.get("globals", ()):
                if g not in self.locals:
                    self.globals.add(g)
            if e.get("options"):
                self.options_unknown = True
            return
        if snap is not None and prog in snap.user_functions and prog not in self.seen:
            self.called(_function_effects(self.ctx, prog, self.depth + 1, self.seen))
        elif self.strict:
            from .scanctx import ZSH_BUILTINS
            if prog in self.ctx.inline_functions or (prog not in ZSH_BUILTINS and
                                                     self.ctx.which_any(prog) is None):
                raise _Unknown()

    def names(self, prog, args):
        """autoload, unfunction, unalias, unhash, alias NAME=…, hash NAME=…: the names later commands may run as
        something the guard cannot read (shadowed); a global or suffix alias, a named folder or a name the guard cannot
        read: unknown."""
        flags = set()
        for a in args:
            if a is None:
                raise _Unknown()
            if a[:1] in "-+" and len(a) > 1:
                flags |= set(a[1:])
                if prog == "autoload" and a[0] == "-" and "X" in a:
                    # review 4 B1: `autoload -X` (zsh's stub `# undefined` body) loads the function's file from
                    # $fpath and runs it in this shell — code the guard does not read
                    raise _Unknown()
                continue
            name = a.split("=", 1)[0] if prog in ("alias", "hash") else a
            if prog in ("alias", "hash") and "=" not in a:
                continue  # a query
            if not name or "/" in name:
                raise _Unknown()
            self.shadowed.add(name)
        if prog == "alias" and flags & set("gs") or prog == "hash" and "d" in flags:
            raise _Unknown()  # global and suffix aliases expand anywhere; hash -d names folders

    def set_(self, args):
        k = 0
        while k < len(args):
            a = args[k]
            if a is None:
                self.options_unknown = True
            elif a in ("--", "-"):
                return  # positional parameters follow
            elif a[:2] in ("-A", "+A"):
                nm = a[2:] or (args[k + 1] if k + 1 < len(args) else "")
                if nm is None:
                    raise _Unknown()
                if nm:
                    self.assigned(nm)
                return
            elif a[:1] in "-+" and len(a) > 1 and re.match(r"^[-+][A-Za-z0-9]+$", a):
                nxt = args[k + 1] if k + 1 < len(args) else None
                if a.endswith("o") and k + 1 < len(args) and nxt is None:
                    self.options_unknown = True
                    k += 2
                    continue
                got = set_flags(a, nxt)  # review 10 conf M-1: `set -euo pipefail`, letter by letter
                if got is None:
                    self.options_unknown = True  # `set -r`, a letter the guard does not know
                else:
                    for name, on in got[0]:
                        if name == "allexport" and on:
                            self.env = True
                        if name not in ("errexit", "unset", "xtrace", "verbose"):
                            self.set_opt(name, on)
                    k += got[1]
                    continue
            elif a[:1] in "-+" and len(a) > 1:
                self.options_unknown = True
            else:
                return  # positional parameters
            k += 1

    def called(self, eff):
        """A function this one calls: its globals are this one's unless local here (zsh's dynamic scope); its options
        stay when it does not restore them."""
        self.env = self.env or eff["env"]
        self.cwd = self.cwd or eff["cwd"]
        self.shadowed |= eff["shadowed"]
        for g in eff["globals"]:
            if g not in self.locals:
                self.globals.add(g)
        if eff["local"] is True:
            return
        if eff["local"] != "inherit":
            self.local = None  # it may have turned LOCAL_OPTIONS off for this function too
        if eff["options_unknown"]:
            self.options_unknown = True
        for k, v in eff["options"].items():
            self.opts[k] = None if (self.cond or eff["local"] is None) else v

    def unwatched_prefix(self, lead):
        """Whether a parameter name that starts with `lead` (the rest built at run time) can be none of the names a
        function's globals are judged by: §1.9 and git variables, zsh's tables and hook arrays, the folder, PATH and the
        other watched names, or a name in the hook's environment (review 4 conf m-2)."""
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]+$", lead) or lead.upper().startswith(("GIT", "DIS_")):
            return False
        names = set(FUNC_WATCHED) | set(cmdopts.CMD_VARS) | set(cmdopts.GIT_ENV_JUDGED) | set(cmdopts.TABLE_NAMES) | \
            HOOK_ARRAYS | IMPLICIT_PARAMS | set(getattr(self.ctx, "env", None) or ())
        return not any(n.startswith(lead) for n in names)

    def declare(self, prog, words):
        """local/typeset/declare/…: the names it declares are the function's own when declared unconditionally at
        the top of the body (a `local` on a branch may not run); exported names are an environment change; global,
        tied or reference names are globals or unknown."""
        flags = set()
        for w in words:
            lead = w.parts[0][1] if w.parts and w.parts[0][0] == "lit" else None
            a = "".join(p[1] for p in w.parts) if all(p[0] == "lit" for p in w.parts) else None
            if a is not None and a[:1] in "-+" and "=" not in a and len(a) > 1:
                flags |= set(a[1:]) if a[0] == "-" else set()
                continue
            if "p" in flags and (a is None or "=" not in a) and not (lead and "=" in lead):
                continue  # typeset -p NAME, local -p NAME: prints, declares nothing (review 4 m1)
            if "m" in flags:
                raise _Unknown()  # typeset -m PATTERN=…: every name the pattern matches
            name = (a if a is not None else (lead if lead and "=" in lead else "")).split("=", 1)[0]
            if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*(\[.*\])?$", name):
                if a is None and lead and "=" not in lead and self.unwatched_prefix(lead) and not flags & set("Tnx"):
                    continue  # `typeset -g "_my_cache${key}"`: a global no watched name starts like (review 4 m-2)
                raise _Unknown()  # a name the guard cannot read
            if flags & set("Tn"):
                raise _Unknown()  # tied or a reference: writes another name
            base = name.split("[", 1)[0]
            if cmdopts.table_word(base) and "g" in flags:
                raise _Unknown()
            if "x" in flags:
                self.env = True
            if "g" in flags:
                self.globals.add(base)
            elif not self.cond:
                self.locals.add(base)
            else:
                self.globals.add(base)  # a local only on a branch: global when the branch does not run
        if "x" in flags:
            self.env = True


FN_STOP_WORDS = ("return", "exit", "logout", "exec")


def _iter_simple(n):
    """Every simple command in a node (not the bodies of functions it defines)."""
    if n is None:
        return
    if isinstance(n, ListNode):
        for ao, _sep in n.items:
            yield from _iter_simple(ao)
    elif isinstance(n, AndOr):
        yield from _iter_simple(n.first)
        for _op, pl in n.rest:
            yield from _iter_simple(pl)
    elif isinstance(n, Pipeline):
        for c in n.cmds:
            yield from _iter_simple(c)
    elif isinstance(n, Simple):
        yield n
    elif isinstance(n, Compound):
        if n.kind == "funcdef":
            return
        for k in ("body", "cond", "else_body", "cmd"):
            yield from _iter_simple(getattr(n, k, None))
        for c, b in getattr(n, "clauses", None) or ():
            yield from _iter_simple(c)
            yield from _iter_simple(b)
        for _p, b in getattr(n, "arms", None) or ():
            yield from _iter_simple(b)


def _lit(wn):
    return "".join(p[1] for p in wn.parts) if wn is not None and all(p[0] == "lit" for p in wn.parts) else None


def _node_names(n):
    """Every name-like token in a node's text (fail closed: a name it may write)."""
    out = set()
    for sc in _iter_simple(n):
        for name, _s, _o, val, _w in sc.assigns:
            out.add(name)
            out.update(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", (val.raw if val is not None else "") or ""))
        for wn in sc.words:
            out.update(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", wn.raw or ""))
    if isinstance(n, Compound) or isinstance(n, (ListNode, AndOr, Pipeline)):
        stack = [n]
        while stack:
            x = stack.pop()
            if isinstance(x, Compound):
                for v in [getattr(x, "var", None)] + list(getattr(x, "vars", None) or []):
                    if v:
                        out.add(v)
                if x.kind == "arith":
                    out.update(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", getattr(x, "raw", "") or ""))
                for k in ("body", "cond", "else_body", "cmd"):
                    if getattr(x, k, None) is not None:
                        stack.append(getattr(x, k))
                for c, b in getattr(x, "clauses", None) or ():
                    stack += [c, b]
                for _p, b in getattr(x, "arms", None) or ():
                    stack.append(b)
            elif isinstance(x, ListNode):
                stack += [ao for ao, _s in x.items]
            elif isinstance(x, AndOr):
                stack += [x.first] + [pl for _o, pl in x.rest]
            elif isinstance(x, Pipeline):
                stack += list(x.cmds)
    return out


def _local_decl(sc):
    """The names a `local`/`typeset`/… command declares function-local (none with -g), or None."""
    if not sc.words:
        return None
    w0 = _lit(sc.words[0])
    if w0 not in FUNC_LOCALS:
        return None
    flags, names = set(), []
    for wn in sc.words[1:]:
        a = _lit(wn)
        lead = wn.parts[0][1] if wn.parts and wn.parts[0][0] == "lit" else ""
        if a is not None and a[:1] in "-+" and "=" not in a and len(a) > 1:
            flags |= set(a[1:]) if a[0] == "-" else set()
            continue
        nm = (a if a is not None else lead).split("=", 1)[0].split("[", 1)[0]
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", nm or ""):
            names.append(nm)
    if "g" in flags:
        return None
    return names


def _body_moves(body, state):
    """review 10: whether a hook's body has a folder change: it runs later, from a folder and $OLDPWD its definition
    did not see (`TRAPZERR(){ cd -; }`), so any `cd`, `pushd`, `popd`, a command word the guard cannot read or a call
    of a function of this call that moves counts."""
    if body is None:
        return False
    for sc in _iter_simple(body):
        ws = [_lit(w) for w in sc.words]
        k = 0
        while k < len(ws) and ws[k] in FUNC_PRECOMMANDS:
            k += 1
        if k >= len(ws):
            continue
        w0 = ws[k]
        if w0 is None or w0 in FUNC_CD:
            return True
        e = state.funcs.get(w0)
        if isinstance(e, dict) and (e.get("cwd") or e.get("hook")):
            return True
    return False


def _fn_body_scan(body):
    """review 10 B2: for a function body, (names it assigns unconditionally at its top level — a plain assignment
    with no redirection that may fail, before anything that may end the function; names it declares local at its top
    level before any write to them, the function's own; names it declares local anywhere)."""
    local_any = set()
    for sc in _iter_simple(body):
        d = _local_decl(sc)
        if d:
            local_any.update(d)
    items = []
    if isinstance(body, Compound) and body.kind == "group" and not body.redirs:
        items = body.body.items
    elif isinstance(body, Simple):
        items = [(AndOr(Pipeline([body]), []), ";")]
    uncond, local_first, seen = set(), set(), set()
    for ao, sep in items:
        if sep == "&":
            continue
        plain = not ao.rest and len(ao.first.cmds) == 1 and not ao.first.neg and \
            isinstance(ao.first.cmds[0], Simple) and not any(redirect_may_fail(r) for r in ao.first.cmds[0].redirs)
        sc = ao.first.cmds[0] if plain else None
        if sc is not None and not sc.words:
            for name, sub, op, _v, _w in sc.assigns:
                if not sub and op == "=" and name not in local_first:
                    uncond.add(name)
        elif sc is not None and _local_decl(sc) is not None:
            for nm in _local_decl(sc):
                if nm not in seen and nm not in uncond:
                    local_first.add(nm)
        seen |= _node_names(ao)
        if any(_lit(x.words[0]) in FN_STOP_WORDS or _lit(x.words[0]) is None for x in _iter_simple(ao) if x.words):
            break  # a `return` (or a word the guard cannot read): later writes may not run
    return uncond, local_first, local_any


def _alias_changes_folder(snap, name):
    """Whether an alias of the snapshot named `name` may change the folder (`..` → `cd ..`) or runs a function."""
    vals = list(getattr(snap, "alternatives", {}).get(name) or [])
    if name in getattr(snap, "plain", {}):
        vals.append(snap.plain[name])
    for text in vals:
        if not isinstance(text, str):
            continue
        first = text.split()[:1]
        if re.search(r"(^|[;&|\s(])(cd|chdir|pushd|popd)(\s|$|;)", text) or (first and first[0] in snap.user_functions):
            return True
    return False


def keep_candidates(ctx, state):
    """review 10 (the union rule): code the guard cannot read may have assigned every parameter, or not: each one
    the call set is unknown, with the values it may still hold kept as candidates (judged where it is used)."""
    for k in list(state.vars):
        pv, pe, _pu = _possible(state.vars[k], state.cands.get(k))
        state.vars[k] = DYN
        state.safe_values.discard(k)
        if pv:
            state.cands[k] = (tuple(pv)[:MAX_CANDS], pe and len(pv) <= MAX_CANDS)
        else:
            state.cands.pop(k, None)


def unknown_values(state, ctx=None):
    """Code the guard cannot read ran in this shell (eval, a function it cannot read): every parameter, the
    environment and the options may have changed (review 10: the values it may still hold stay candidates)."""
    if ctx is not None:
        keep_candidates(ctx, state)
    for k in list(state.vars):
        state.vars[k] = DYN
    state.cands.pop("~-", None)
    state.dirstack = None  # review 9: popd fails only on a stack known to be empty
    state.env_unknown = True
    state.paths = None
    _options_unknown(state)
    funcs_unknown(state)  # review 11 B1: it may remove or replace functions of this call


def apply_function_effects(ctx, state, eff, cwds):
    """A snapshot user function ran (snapshot_function_effects): the caller's state after it; returns its folders."""
    if eff is None:
        unknown_values(state, ctx)
        state.dirstack = None
        state.oldpwd = None
        state.cands.pop("~-", None)
        return (None, None)
    if eff["env"]:
        state.env_unknown = True
    for name in eff["shadowed"]:
        state.shadowed.add(name)
    funcs_unknown(state, set(eff["shadowed"]))  # review 11 B1: it unfunctions or autoloads a function of this call
    for name in eff["globals"]:
        # review 10 B2: the function may not write it (a branch, `local` on a branch): the caller's values stay
        # candidates of a value now unknown
        pv, pe, _pu = _possible(state.vars.get(name, _MISSING), state.cands.get(name),
                                _env_value(ctx, state, name) if name not in state.vars else _MISSING)
        state.vars[name] = DYN
        state.safe_values.discard(name)
        if pv:
            state.cands[name] = (tuple(pv)[:MAX_CANDS], pe and len(pv) <= MAX_CANDS)
        else:
            state.cands.pop(name, None)
        if function_watched(ctx, state, name):
            state.env_unknown = True
        if name in ("PATH", "path"):
            state.paths, state.path_modified = None, True
        elif name == "dirstack":
            state.dirstack = None
        elif name == "OLDPWD":
            state.oldpwd = None
            state.cands.pop("~-", None)
    if eff["local"] is not True:
        if eff["options_unknown"]:
            _options_unknown(state)
        for name, on in sorted(eff["options"].items()):
            _set_option(state, name, on if eff["local"] in (False, "inherit") else None)
    if eff["cwd"]:
        state.dirstack = None
        state.oldpwd = None
        state.cands.pop("~-", None)
        return (None, None)
    return (cwds, cwds)


def function_watched(ctx, state, name):
    """Whether a global a function set reaches what the guard judges: a §1.9 or git variable, the folder and PATH,
    a name exported already (the hook's environment, export or allexport in this call)."""
    if name in FUNC_WATCHED or cmdopts.watched_var(name) or name.startswith("GIT_") or state.allexport:
        return True
    if name in ctx.env:
        return True
    return any(op.name == name and op.via in ("export", "typeset-x", "declare-x") for op in state.env_ops)


# ---- builtins ----

def _args(cmd):
    return cmd.words[1:]


def _prefix_cdpath(cmd):
    return any(op.via == "prefix" and (op.name or "").split("[")[0] in ("CDPATH", "cdpath") for op in cmd.env.ops)


def _home_for(w, cmd, state, cwds):
    """$HOME for `cd`/`pushd` with no word: a prefix assignment (`HOME=.. pushd`, review 12) wins; its value when the
    guard reads it, else None (unknown)."""
    ops = [op for op in cmd.env.ops if op.via == "prefix" and op.name == "HOME"]
    if ops:
        v = getattr(ops[-1].value, "value", ops[-1].value)
        return v if isinstance(v, str) else None
    return w.lookup("HOME", state, cwds)


def _chaselinks(w, state):
    """True / False, or None when unknown (in-command option changes, snapshots disagree)."""
    if "chaselinks" in state.opts:
        return state.opts["chaselinks"]
    snap = w.ctx.snapshot
    if snap is not None and "chaselinks" in snap.option_conflicts:
        return None
    return bool(w.ctx.options.get("chaselinks", False))


def _oldpwd_targets(w_, state):
    """review 17 (B17-1): the folders a `~-` / `$OLDPWD` word (optionally with a literal suffix: `~-/.`), or a name
    assigned from one, is exactly one of — $OLDPWD after a cd / pushd that may not have run — else None."""
    if w_ is None or w_.value is not None or w_.glob or not w_.dyn or getattr(w_, "cand_loose", None):
        return None
    vals = tuple(getattr(w_, "cand_values", ()) or ())
    if not vals or len(vals) > MAX_CANDS or not all(os.path.isabs(v) for v in vals):
        return None
    c = state.cands.get("~-")
    old_ok = state.oldpwd is None and bool(c) and bool(c[1])
    for d in w_.dyn:
        if d == "tilde-" or (d == "param:OLDPWD" and "OLDPWD" not in state.vars):
            if not old_ok:
                return None
        elif not (d.startswith("param:") and _complete_kind(state, d[6:]) == "oldpwd"):
            return None
    return list(vals)


def _note_lost_some(w, folders):
    """review 17: the folders $OLDPWD may hold, judged as lost folders — not when the list would grow past MAX_CWDS
    (a long chain of moves that may not run: the folder is then only unknown, as before; guard-limits)."""
    if len(set(w.lost) | set(folders)) <= limits.MAX_CWDS:
        note_lost(folders)


def b_cd(w, cmd, cwds, state):
    state.glob_cwd = None
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
        target = _home_for(w, cmd, state, cwds)
        if target is None:
            return (None, old)
        rest_val = target
    else:
        rest_val = rest[0].value
        tg = _oldpwd_targets(rest[0], state) if rest_val is None else None
        if tg:
            # review 17 (B17-1): `cd ~-` / `cd $OLDPWD` while $OLDPWD is one of several folders: unknown as before,
            # and each of those folders is judged as well (Walker.lost: the union rule only adds readings)
            _note_lost_some(w, tg)
            return (None, old)
        if rest_val is None or rest[0].glob:
            # a word the guard cannot read, or a wildcard zsh expands: unknown (§1.7a, M12); a wildcard's pattern is
            # kept for the later relative paths (judged as `<pattern>/<path>` too)
            if rest_val is not None and (old or os.path.isabs(rest_val)):
                state.glob_cwd = (tuple(old or ()), rest_val)
            return (None, old)
    targets = None
    if rest_val == "-":
        if state.oldpwd is None:
            c = state.cands.get("~-")
            if not c or not c[1] or not all(os.path.isabs(x) for x in c[0]):
                return (None, old)
            targets = list(c[0])  # review 10: $OLDPWD is one of these (a cd that may not have run): each is judged
            rest_val = targets[0]
        else:
            rest_val = state.oldpwd
    elif re.match(r"^[+-]\d+$", rest_val):
        return _stack_move(w, cmd, cwds, state, rest_val)
    if state.cdpath and not rest_val.startswith(("/", "./", "../")) and rest_val not in (".", ".."):
        return (None, old)
    chase = _chaselinks(w, state)
    if chase is None:
        return (None, old)
    autopushd = w.option_maybe(state, "autopushd")
    if autopushd is None:
        # AUTO_PUSHD may be on: the stack is as it was or has the old folder pushed (review 10 M2: popd is judged both
        # ways); unknown when the old folder is not one path (review 5: pushd with no word)
        a = stack_alts(state.dirstack)
        if a is not None and single(old):
            set_stack_alts(state, a + tuple(x + (single(old),) for x in a))
        else:
            state.dirstack = None
    if targets and len(targets) > 1:
        S, F = (), ()
        for t in targets[1:]:
            s_, f_ = _move(w, cwds, state.copy(), t, physical or chase, push=bool(autopushd))
            S, F = union(S, s_), union(F, f_)
        s_, f_ = _move(w, cwds, state, targets[0], physical or chase, push=bool(autopushd))
        return (union(S, s_), union(F, f_))
    return _move(w, cwds, state, rest_val, physical or chase, push=bool(autopushd))


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
        if push:
            state.dirstack = None  # review 16 (C16-1): it pushed a folder the guard cannot tell
        return (None, None)
    bases = old if old is not None else ("/",)
    news = []
    fails = []
    for b in bases:
        if physical:
            n = physical_path(w.ctx.fs, b, target)
            if n is None:
                return _push_unknown(state, old) if push else (None, old)
        else:
            n = os.path.normpath(os.path.join(b, target))
        news.append(n)
        if not w.ctx.fs.isdir(n):
            if w.option_maybe(state, "cdablevars") is not False and not target.startswith("/"):
                # CDABLE_VARS: read as ~target (review 3: an option a function set)
                return _push_unknown(state, old) if push else (None, old)
            fails.append(b)
    S = tuple(dict.fromkeys(news))
    F = tuple(dict.fromkeys(fails))
    prev = state.oldpwd
    state.oldpwd = single(old) if not F else None
    _oldpwd_cands(state, list(old or ()) + ([prev] if F and prev else []))
    if push:
        a = stack_alts(state.dirstack)
        if single(old) and a is not None:
            # review 10 conf m-2: a move that may fail pushes or does not — both stacks stay possible
            pushed = tuple(x + (single(old),) for x in a)
            set_stack_alts(state, pushed + (a if F else ()))
        else:
            state.dirstack = None  # the old cwd is not one path, or the stack is unknown
    return (S if len(S) <= limits.MAX_CWDS else None, F)


class StackAlts(tuple):
    """review 10 conf m-2, M2: the directory stack is one of these (each a tuple of folders, top last)."""


MAX_STACK_ALTS = 8


def stack_alts(stack):
    """The stacks the shell may have (tuples), or None when unknown."""
    if stack is None:
        return None
    if isinstance(stack, StackAlts):
        return tuple(stack)
    return (tuple(stack),)


def set_stack_alts(state, alts):
    alts = tuple(dict.fromkeys(tuple(x) for x in alts))
    if not alts or len(alts) > MAX_STACK_ALTS:
        state.dirstack = None
    elif len(alts) == 1:
        state.dirstack = list(alts[0])
    else:
        state.dirstack = StackAlts(alts)


def _oldpwd_cands(state, vals):
    """review 9 B1: `~-` after a move from one of several folders (or one that may fail) is one of them."""
    vals = tuple(dict.fromkeys(v for v in vals if v))
    if state.oldpwd is None and vals:
        state.cands["~-"] = (vals[:MAX_CANDS], len(vals) <= MAX_CANDS)
    else:
        state.cands.pop("~-", None)


def _stack_move(w, cmd, cwds, state, spec):
    return (None, cwds)


def _push_unknown(state, cwds, rotate=False):
    """review 16 (C16-1/2): a pushd the guard cannot follow. It pushes the folder it leaves (one known path: the
    stack has it on top or, when the move may fail, is as before; $OLDPWD likewise); otherwise, or when it rotates the
    stack (+N / -N), the stack is unknown — `popd` afterwards may succeed."""
    a = stack_alts(state.dirstack)
    old = single(cwds)
    if rotate or a is None or not old:
        state.dirstack = None
    else:
        set_stack_alts(state, tuple(x + (old,) for x in a) + a)
    if old and not rotate:
        _oldpwd_union(state, (state.oldpwd, state.cands.get("~-")), (old, None))
    return (None, cwds)


def b_pushd(w, cmd, cwds, state):
    state.glob_cwd = None
    if _prefix_cdpath(cmd) or _chaselinks(w, state) is None:
        return _push_unknown(state, cwds)
    # review 4 R2: options like cd's (-q -s -L -P, `--`); two words are zsh's substitution in $PWD; +N/-N the stack
    args, physical, done = [], False, False
    for a in _args(cmd):
        v = a.value
        if not done and v is not None and re.match(r"^-[qsLP]+$", v):
            physical = physical or "P" in v
            continue
        if not done and v == "--":
            done = True
            continue
        if not done and v is not None and v.startswith("-") and v != "-" and not re.match(r"^-\d+$", v):
            return _push_unknown(state, cwds, rotate=True)  # an option the guard does not read
        done = True
        args.append(a)
    if len(args) > 1:
        return _push_unknown(state, cwds)
    if not args:
        if isinstance(state.dirstack, StackAlts):
            state.dirstack = None
            return (None, cwds)
        if state.dirstack and single(cwds):
            top = state.dirstack.pop()
            state.dirstack.append(single(cwds))
            state.oldpwd = single(cwds)
            _oldpwd_cands(state, list(cwds or ()))
            return ((top,), ())
        home = _home_for(w, cmd, state, cwds) if state.dirstack == [] else None
        if home is None:
            return _push_unknown(state, cwds, rotate=bool(state.dirstack) or state.dirstack is None)
        # an empty stack: pushd goes to $HOME, as cd does (review 5)
        return _move(w, cwds, state, home, physical=physical or bool(_chaselinks(w, state)), push=True)
    v = args[0].value
    tg = _oldpwd_targets(args[0], state) if v is None else None
    if tg:
        # review 17 (B17-1): `pushd ~-` / `pushd $OLDPWD` while $OLDPWD is one of several folders: unknown as
        # before, and each of those folders judged as well (Walker.lost)
        _note_lost_some(w, tg)
        return _push_unknown(state, cwds)
    if v is None or args[0].glob or re.match(r"^[+-]\d+$", v):
        if v is not None and args[0].glob and (cwds or os.path.isabs(v)):
            state.glob_cwd = (tuple(cwds or ()), v)
        return _push_unknown(state, cwds, rotate=v is not None and not args[0].glob and v[:1] in "+-")
    if v == "-":
        return _push_unknown(state, cwds)
    if state.cdpath and not v.startswith(("/", "./", "../")) and v not in (".", ".."):
        return _push_unknown(state, cwds)
    return _move(w, cwds, state, v, physical=physical or bool(_chaselinks(w, state)), push=True)


def b_popd(w, cmd, cwds, state):
    state.glob_cwd = None
    args = [a for a in _args(cmd) if a.value not in ("-q", "--")]
    alts = stack_alts(state.dirstack)
    if args or alts is None:
        return (None, cwds)  # a stack the guard cannot tell: popd may go anywhere, or fail
    # review 9: on an empty stack popd fails ("directory stack empty") and the shell stays (zsh 5.9); review 10: on
    # each stack the shell may have — the folders of all of them
    tops, fail, rest = [], False, []
    for x in alts:
        if x:
            tops.append(x[-1])
            rest.append(x[:-1])
        else:
            fail = True
            rest.append(x)
    set_stack_alts(state, rest)
    if tops:
        state.oldpwd = single(cwds) if not fail else None
        _oldpwd_cands(state, list(cwds or ()))
    return (tuple(dict.fromkeys(tops)), cwds if fail else ())


def b_dirs(w, cmd, cwds, state):
    if any(a.value == "-c" for a in _args(cmd)):
        state.dirstack = []
    elif any(a.value is None or not a.value.startswith(("-", "+")) for a in _args(cmd)):
        state.dirstack = None  # `dirs <folders>` sets the stack (review 5: pushd with no word)
    return (cwds, cwds)


def b_export(w, cmd, cwds, state):
    prog = cmd.prog
    args = _args(cmd)
    flags = set()
    via = {"export": "export", "declare": "declare", "typeset": "typeset", "local": "local",
           "readonly": "readonly", "integer": "typeset", "float": "typeset", "private": "local"}[prog]
    for a in args:
        v = a.value if a.value is not None else a.raw
        if v.startswith(("-", "+")) and "=" not in v:
            flags |= set(v[1:])
            continue
        if "f" in flags or "p" in flags and "=" not in v:
            continue
        name, eq, val = v.partition("=")
        if flags & set("Tn") and not "f" in flags:
            # typeset -T SCALAR array (tied: writing either writes both), typeset -n REF=NAME (a reference): a §1.9
            # variable or one of zsh's tables so named is written later under another name (M4, review 2)
            for n in (name, val if "n" in flags else None):
                if not n:
                    continue
                base_n = n.split("[")[0]
                if cmdopts.table_word(base_n):
                    w.table_write(state, "%s -%s %s" % (prog, "".join(sorted(flags & set("Tn"))), base_n), cwds,
                                  cmd)
                elif cmdopts.watched_var(base_n):
                    w.param_written(state, base_n, "typeset-" + "".join(sorted(flags & set("Tn"))), cwds, cmd)
            if "T" in flags:
                # the pair is one parameter under two names: a write to either steers both (review 5 M2)
                state.steer_names.update(x for x in (name.split("[")[0],) if x)  # each name of the pair, in turn
            if "T" in flags and not eq:
                continue
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*(\[[^\]]*\])?$", name):
            continue
        if flags & set("aA"):
            state.arrays.add(name.split("[")[0])  # typeset -a / -A NAME (C-M3)
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
            if name in cmdopts.CMD_VARS:  # G1 §1.9: a command-valued variable set by export/typeset
                w.var_set(state, name, valw.value, valw.value if valw.value is not None else valw.skeleton,
                          cwds, cmd)
            if state.vars.get(name) is DYN:
                pass
        else:
            cur = state.vars.get(name, w.ctx.env.get(name))
            valw = Word.lit(cur) if isinstance(cur, str) else Word(name, None, dynamic=True, dyn=["param:" + name],
                                                                   skeleton="\0")
            state.env_ops.append(EnvOp(via2, "set", name, valw))
    return (cwds, cwds)


def b_unset(w, cmd, cwds, state):
    # review 11 B1: the options of the whole cluster (`-fm`); `--` ends them (it does not turn -f off)
    args = _args(cmd)
    flags, k = set(), 0
    while k < len(args) and args[k].value is not None and args[k].value.startswith("-") and args[k].value != "-":
        if args[k].value == "--":
            k += 1
            break
        flags |= set(args[k].value[1:])
        k += 1
    if "f" in flags:
        for a in args[k:]:
            if a.value is None:
                funcs_unknown(state)
            elif "m" in flags:
                sure, maybe = funcs_matching(state, a.value)
                funcs_remove(state, sure)
                funcs_remove(state, maybe, sure=False)
            else:
                funcs_remove(state, [a.value])
        return (cwds, cwds)
    if k < len(args) and args[k].value is None:
        funcs_unknown(state)  # a word the guard cannot read may be `-f`
    for a in args[k:]:
        v = a.value
        if v is None:
            state.env_ops.append(EnvOp("unset", "unknown"))
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
        if EVAL_SOURCE_RE.search(val):
            state.alias_src.add(name)  # fix20 (P20-5): using it runs a source — the walk stops there
        w.emit_opaque(Opaque("alias", payload=val, cwds=cwd_list(cwds)), cmd)
    return (cwds, cwds)


def b_noop(w, cmd, cwds, state):
    return (cwds, cwds)


def mark_sourced(w):
    """fix20: a `source` / `.` (or eval / emulate -c text that may run one) ran in this reading — the walk stops
    here; what follows is judged by the 0.0.26 rules alone (backstop.decide). A dry run (a reading being tried, a
    function's effects) does not stop it."""
    if not w.dry:
        w.sourced = w.ever_sourced = True


def b_source(w, cmd, cwds, state):
    """`source FILE` / `. FILE` (fix20): code given in the call itself — the input (`source /dev/stdin <<< …`, a
    heredoc) or a file this call wrote — is judged as a nested string; then the walk stops (mark_sourced). A file of
    the user's is not read: the 0.0.26 guard judges it and everything after it, as in 0.0.26."""
    args = _args(cmd)
    deferred = []
    if not args:
        return (cwds, cwds)
    p = args[0]
    res = None
    if p.value in ("/dev/stdin", "/dev/fd/0", "-"):
        w.stdin_opaque(cmd, cwds, state, getattr(w, "cur_stdin", None), deferred, "source", kind_override="source")
    else:
        cwd = cmd.cwds[0] if cmd.cwds else None
        res = w.where.resolve(p.value, cwd) if p.value is not None and (cwd or os.path.isabs(p.value)) else None
        if res is not None and res.abs in state.written:
            op = Opaque("source", payload=state.written[res.abs], origin="linked-heredoc", cwds=cwd_list(cwds),
                        path=res.abs, path_class=w.where.path_class(res.real, w.ctx.env) if res.real else ["other"])
            deferred.append(lambda: w.emit_opaque(op, cmd))
    for f in deferred:
        f()
    # what a dry run (a function's effects: a hook, a definition) reads after it: the folder, the environment, PATH,
    # $OLDPWD, the stack and the function table unknown
    state.env_unknown = True
    state.paths = None
    state.glob_cwd = None
    state.oldpwd = None
    state.cands.pop("~-", None)
    state.dirstack = None
    state.defs_maybe = True  # the file may define functions (review 4 B3)
    funcs_unknown(state)  # review 11 B1: it may remove or replace functions of this call
    if p.value in ("/dev/stdin", "/dev/fd/0", "-") or (res is not None and res.abs in state.written):
        note_definitions(state, None if p.value in ("/dev/stdin", "/dev/fd/0", "-") else state.written[res.abs], cwds)
    w.steer_event(state, args, getattr(w, "cur_stdin", None), cmd.redirs)
    w.note("env-unknown-after:#%d" % cmd.id)
    mark_sourced(w)
    return (None, None)


def b_eval(w, cmd, cwds, state):
    """The payload runs in this shell: afterwards the cwd and the environment are unknown."""
    args = _args(cmd)
    payload = " ".join(a.value for a in args) if all(a.value is not None for a in args) else None
    op = Opaque("eval", payload=payload, cwds=cwd_list(cwds))
    if payload is None and args:
        op.literals = [" ".join(a.skeleton.replace("\0", "") for a in args)]
        op.skeleton = " ".join(a.skeleton for a in args)
    w.emit_opaque(op, cmd)
    if args:
        w.steer_event(state, args, getattr(w, "cur_stdin", None), cmd.redirs)  # review 4 conf M-1
        if payload is None or eval_may_define(w.ctx, payload):
            state.defs_maybe = True  # review 4 B3
            note_definitions(state, payload, cwds)
        if text_may_change_funcs(w.ctx, payload):
            funcs_unknown(state)  # review 11 B1: `eval 'unfunction f'`, `eval 'f(){ :; }'`
        state.env_unknown = True
        state.paths = None
        state.argv_opts_changed = True
        state.dirstack = None
        state.oldpwd = None
        state.cands.pop("~-", None)
        keep_candidates(w.ctx, state)  # the string may assign any parameter — or not (review 10: the union rule)
        # review 8 M2: $HOME too (`eval 'HOME=<repo>'; rm -rf ~/studio`): later `~` words are judged as written
        state.vars["HOME"] = DYN
        state.raw_values["HOME"] = payload if payload is not None else (op.skeleton or "")
        if payload is None or eval_may_set_options(w.ctx, payload):
            _options_unknown(state)  # GLOB_SUBST may be on afterwards (review 3, M-4)
        if payload is None or EVAL_SOURCE_RE.search(payload):
            # fix20: text the guard cannot read, or text that may run source / `.` in this shell: the walk stops
            # (the string itself is judged above, as a nested string)
            mark_sourced(w)
        return (None, None)
    return (cwds, cwds)


# fix20: eval / emulate -c text that may run a source in this shell (P20-1: or that the guard cannot read)
EVAL_SOURCE_RE = re.compile(r"\bsource\b|(^|[\s;&|(])\.(\s|$)|\beval\b|\bemulate\b")
EVAL_OPTIONS_RE = re.compile(r"setopt|unsetopt|emulate|options|\bset\b|\bsource\b|(^|[\s;&|(])\.(\s|$)|\beval\b|"
                             r"\bbuiltin\b|\bcommand\b|[$`\\]")


EVAL_DEFS_RE = re.compile(r"\(\s*\)|\bfunctions?\b|\bautoload\b|\bsource\b|(^|[\s;&|(])\.(\s|$)|\beval\b|\bemulate\b|"
                          r"[$`\\]|\bTRAP|\btrap\b|\bchpwd")


def text_may_change_funcs(ctx, payload):
    """review 11 B1: whether a string run in this shell (eval, emulate -c) may remove or replace a function: None (not
    readable), a definition or anything eval_may_define counts, or a word that removes one."""
    return payload is None or eval_may_define(ctx, payload) or \
        re.search(r"\b(unfunction|unhash|disable|enable|unset)\b", payload) is not None


def eval_may_define(ctx, payload):
    """Whether a literal eval string may define a function or a hook (review 4 B3, R1): a definition, `function`,
    autoload, source, eval, an expansion, or a snapshot function the guard cannot read."""
    if EVAL_DEFS_RE.search(payload):
        return True
    snap = ctx.snapshot
    if snap is None:
        return False
    return any(t in snap.user_functions and snapshot_function_effects(ctx, t) is None
               for t in re.split(r"[\s;&|()<>{}]+", payload) if t)


def eval_may_set_options(ctx, payload):
    """Whether a literal eval string may change zsh's options: it names an option builtin, the options table, sources
    or evals, expands a value (the result is run as code), or calls a snapshot function or alias the guard does not
    read here."""
    if EVAL_OPTIONS_RE.search(payload):
        return True
    snap = ctx.snapshot
    if snap is None:
        return False
    for t in re.split(r"[\s;&|()<>{}]+", payload):
        if not t:
            continue
        if t in snap.global_aliases or t in snap.alternatives:
            return True
        if t in snap.plain and (EVAL_OPTIONS_RE.search(snap.plain[t]) or snap.plain[t].split()[:1] and
                                snap.plain[t].split()[0] in snap.user_functions):
            return True
        if t in snap.user_functions:
            eff = snapshot_function_effects(ctx, t)
            if eff is None or eff["options_unknown"] or (eff["options"] and eff["local"] is not True):
                return True
    return False


def _emulate_posix(vals):
    """POSIX_BUILTINS after `emulate MODE`: on for sh and ksh, off for zsh and csh, None when unknown."""
    i = 0
    while i < len(vals):
        v = vals[i]
        if v is None:
            return None
        if v == "-c":
            i += 2
            continue
        if v.startswith("-"):
            i += 1
            continue
        return True if v in ("sh", "ksh") else (False if v in ("zsh", "csh") else None)
    return None


def b_emulate(w, cmd, cwds, state):
    vals = [a.value for a in _args(cmd)]
    posix = _emulate_posix(vals)
    if "-c" in vals:
        i = vals.index("-c")
        code = vals[i + 1] if i + 1 < len(vals) else None
        op = Opaque("eval", payload=code, cwds=cwd_list(cwds))
        op.options = {"posixbuiltins": posix}
        if code is None and i + 1 < len(vals):
            op.skeleton = _args(cmd)[i + 1].skeleton
        w.emit_opaque(op, cmd)
        state.defs_maybe = state.steer_all = True  # review 4 B3, conf M-1
        note_definitions(state, code, cwds)
        if text_may_change_funcs(w.ctx, code):
            funcs_unknown(state)  # review 11 B1
        state.env_unknown = True
        state.paths = None
        if code is None or EVAL_SOURCE_RE.search(code):
            mark_sourced(w)  # fix20 (P20-5): as eval
        return (None, None)
    if "-L" in vals or any(v and re.match(r"^-[a-zA-Z]*L", v) for v in vals):
        state.opts["localoptions"] = True
    if any(v and not v.startswith("-") for v in vals) or any(v is None for v in vals):
        _options_unknown(state)
        state.opts["posixbuiltins"] = posix
    return (cwds, cwds)


ARGV_OPTIONS = {"shwordsplit", "globsubst", "rcexpandparam", "ksharrays", "shglob", "noglob", "glob", "equals",
                "magicequalsubst", "rcquotes", "kshglob", "extendedglob", "nomatch", "nullglob", "cshnullglob",
                "globassign", "histsubstpattern", "bareglobqual", "shfileexpansion", "posixidentifiers",
                "ignorebraces", "ignoreclosebraces", "braceccl", "kshtypeset", "typesetsilent", "multibyte",
                "posixstrings", "cbases", "octalzeroes", "unset", "aliases", "interactivecomments", "globstarshort"}
BRACE_OPTIONS = {"ignorebraces", "ignoreclosebraces", "braceccl", "shfileexpansion"}


def _options_unknown(state):
    state.options_unknown = True
    state.argv_opts_changed = True
    state.brace_opts_changed = True
    state.opts["chaselinks"] = None
    state.opts["posixbuiltins"] = None  # maybe: `command cd` may be the builtin (G1 §1.3)


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
    if cmd.prog == "return" and w.func_depth:
        return (cwds, cwds)  # `f(){ cd x; return; }`: the function ends where it is, its folder is the caller's
    return ((), ())


# review 10 conf M-1: zsh's single-letter `set` flags (zsh emulation): letter -> (option, value with `-`). `-s` sorts
# the arguments; `-o NAME` / `+o NAME` name an option (`set -euo pipefail`); `-A`/`+A` assign an array. A letter not
# listed here (`-r` RESTRICTED among them) makes the options unknown.
SET_LETTERS = {"e": ("errexit", True), "u": ("unset", False), "x": ("xtrace", True), "v": ("verbose", True),
               "n": ("exec", False), "a": ("allexport", True), "h": ("histignoredups", True),
               "g": ("histignorespace", True), "k": ("interactivecomments", True), "1": ("printexitvalue", True),
               "2": ("badpattern", False), "3": ("nomatch", False), "4": ("globdots", True), "5": ("notify", True),
               "6": ("bgnice", True), "7": ("ignoreeof", True), "8": ("markdirs", True), "9": ("autolist", True),
               "0": ("correct", True), "B": ("beep", False), "C": ("clobber", False), "D": ("pushdtohome", True),
               "E": ("pushdsilent", True), "F": ("glob", False), "G": ("nullglob", True),
               "H": ("rmstarsilent", True), "I": ("ignorebraces", True), "J": ("autocd", True),
               "K": ("banghist", False), "L": ("sunkeyboardhack", True), "M": ("singlelinezle", True),
               "N": ("autopushd", True), "O": ("correctall", True), "P": ("rcexpandparam", True),
               "Q": ("pathdirs", True), "R": ("longlistjobs", True), "S": ("recexact", True),
               "T": ("cdablevars", True), "U": ("mailwarning", True), "V": ("promptcr", False),
               "W": ("autoresume", True), "X": ("listtypes", True), "Y": ("menucomplete", True), "Z": ("zle", True),
               "f": ("rcs", False), "m": ("monitor", True), "p": ("privileged", True), "t": ("singlecommand", True),
               "w": ("chaselinks", True), "y": ("shwordsplit", True), "l": ("login", True), "i": ("interactive", True)}


def set_flags(arg, nxt):
    """review 10 conf M-1: one `set` word of flags (`-euo`, `+ex`, `-o`) read letter by letter, `nxt` the word after
    it (the option name a trailing `o` takes). ([(option, on)], words used (1 or 2)) or None when a letter is not
    one the guard knows (the options are then unknown). `-s` (sort the arguments) changes no option."""
    on = arg[0] == "-"
    out, used = [], 1
    letters = arg[1:]
    for k, ch in enumerate(letters):
        if ch == "o":
            if k != len(letters) - 1:
                return None  # `-oe`: the name would be the rest of the word in some shells — not read
            if nxt is None:
                return out, 1  # `set -o`: prints the options
            out.append((nxt, on))
            used = 2
        elif ch in "su":
            continue  # `-s` sorts the arguments; `-u` (NO_UNSET) makes an unset value an error, no change to words
        elif ch in SET_LETTERS:
            name, val = SET_LETTERS[ch]
            out.append((name, val if on else not val))
        else:
            return None
    return out, used


def b_set(w, cmd, cwds, state):
    args = _args(cmd)
    vals = [a.value for a in args]
    if "-a" in vals or ("-o" in vals and "allexport" in vals):
        state.allexport = True
    i = 0
    pos_done = False
    while i < len(vals):
        v = vals[i]
        if v is not None and v[:2] in ("-A", "+A"):
            break  # set -A NAME values…: an array, not options (its name: zsh_forms)
        if v is None or v in ("-", "--") or v[:1] not in ("-", "+"):
            state.steer_names.add("argv")  # `set -- …`, `set x`: the positional parameters (review 5 M1)
            if not pos_done:
                _positionals_moved(state)
            rest = args[i + 1:] if v in ("-", "--") else args[i:]
            if not pos_done and all(a.value is not None for a in rest):
                # review 9: the new positional parameters, as candidates of $1, $@, … (`set -- studio; X=$1`)
                for j, a in enumerate(rest[:MAX_CANDS]):
                    state.cands[str(j + 1)] = ((a.value,), True)
                if rest:
                    for n in POSITIONAL + ("*",):
                        state.cands[n] = (tuple(a.value for a in rest[:MAX_CANDS]), len(rest) <= MAX_CANDS)
            pos_done = True
        if v is None:
            _options_unknown(state)
        elif not pos_done and re.match(r"^[-+][A-Za-z0-9]+$", v):
            nxt = vals[i + 1] if i + 1 < len(vals) else None
            if v.endswith("o") and i + 1 < len(vals) and nxt is None:
                _options_unknown(state)  # `set -o $X`: an option the guard cannot read
                i += 2
                continue
            got = set_flags(v, nxt)
            if got is None:
                _options_unknown(state)
            else:
                for name, on in got[0]:
                    if name.lower().replace("_", "") in ("allexport",) and on:
                        state.allexport = True
                    _set_option(state, name, on)
                i += got[1]
                continue
        i += 1
    return (cwds, cwds)


def b_trap(w, cmd, cwds, state):
    args = _args(cmd)
    if args:
        w.emit_opaque(Opaque("trap", payload=args[0].value, cwds=cwd_list(cwds)), cmd)
        act = args[0].value
        if act is None or (act not in ("", "-") and not (act.startswith("-") and len(args) == 1)):
            # review 4 R1: zsh runs the action after later commands (DEBUG, ZERR, ERR) or at a signal or exit
            kinds = {trap_kind(a.value) for a in args[1:]} or {None}
            if kinds == {"exit"} and not w.func_depth:
                # review 10 B1/M1: an EXIT trap set at the top runs when the shell ends, after every command of the
                # call (its text is searched as a trap string): later commands keep their folder and values
                return (cwds, cwds)
            # a function the action names is read by what this call defined it to do (review 10 M1); a later
            # definition of that name applies again (Walker.define_hook)
            state.trap_names = set(getattr(state, "trap_names", ())) | \
                set(re.findall(r"[^\s;&|()<>'\"]+", act or ""))
            w.hook_effects(state, None if act is None else text_effects(w.ctx, act, state.funcs))
    return (cwds, cwds)


def b_hash(w, cmd, cwds, state):
    vals = [a.value for a in _args(cmd)]
    if cmd.prog == "hash":
        # G1 §1.8: `hash name=path`, `hash -p path name`, `hash -d name=path` change what a name runs (or what ~name
        # is); later commands are shadowed and the call is refused in a Studio repository
        flags = set()
        names = []
        for v in vals:
            if v is not None and v.startswith("-") and len(v) > 1:
                flags |= set(v[1:])
            else:
                names.append(v)
        if "d" in flags and names:
            state.named_dirs_any = True
            w.table_write(state, "hash -d", cwds, cmd)
        elif "p" in flags and len(names) >= 2:
            if names[1]:
                state.shadowed.add(names[1])
                w.note("shadowed:%s" % names[1])
            w.table_write(state, "hash -p", cwds, cmd, names=[n for n in names[1:2] if n])
        elif any(v is None or "=" in v for v in names) and not flags & set("rfL"):
            short = [v.split("=", 1)[0] for v in names if v and "=" in v]
            w.table_write(state, "hash %s" % " ".join(v if v is not None else "?" for v in names), cwds, cmd,
                          names=short)
    if cmd.prog in ("disable", "enable"):
        # review 11 B1: `disable -f NAME` turns a function off (the name runs a command so named, or none); `enable -f`
        # turns it on again; a pattern (-m) or a word the guard cannot read: unknown
        flags, k = set(), 0
        while k < len(vals) and vals[k] is not None and vals[k].startswith("-") and vals[k] != "-":
            if vals[k] == "--":
                k += 1
                break
            flags |= set(vals[k][1:])
            k += 1
        names = vals[k:]
        if (k < len(vals) and vals[k] is None) or ("f" in flags and ("m" in flags or None in names)):
            funcs_unknown(state)
            for n, e in list(state.funcs_disabled.items()):
                state.funcs.setdefault(n, dict(e, unknown_def=True))
        elif "f" in flags and cmd.prog == "disable":
            for n in names:
                if n in state.funcs:
                    state.funcs_disabled[n] = state.funcs.pop(n)
        elif "f" in flags:
            for n in names:
                if n in state.funcs_disabled:
                    state.funcs[n] = state.funcs_disabled.pop(n)
    if cmd.prog == "disable" or (cmd.prog == "enable" and "-n" in vals):
        for v in vals:
            if v and not v.startswith("-"):
                state.shadowed.add(v)
                w.note("shadowed:%s" % v)
    return (cwds, cwds)


def b_unfunction(w, cmd, cwds, state):
    """review 11 B1: `unfunction NAME…` (`-m`: patterns), `unhash -f NAME…`: functions this call defined so named are
    removed (a later call runs a command so named, or none); a word the guard cannot read: unknown."""
    vals = [a.value for a in _args(cmd)]
    flags, k = set(), 0
    while k < len(vals) and vals[k] is not None and vals[k].startswith("-") and vals[k] != "-":
        if vals[k] == "--":
            k += 1
            break
        flags |= set(vals[k][1:])
        k += 1
    if k < len(vals) and vals[k] is None:
        funcs_unknown(state)  # may be an option (`-f`, `-m`)
        return (cwds, cwds)
    if cmd.prog == "unhash" and "f" not in flags:
        return (cwds, cwds)
    for v in vals[k:]:
        if v is None:
            funcs_unknown(state)
        elif "m" in flags:
            sure, maybe = funcs_matching(state, v)
            funcs_remove(state, sure)
            funcs_remove(state, maybe, sure=False)
        else:
            funcs_remove(state, [v])
    return (cwds, cwds)


def b_let(w, cmd, cwds, state):
    for a in _args(cmd):
        w.arith_check(a.value or a.raw, state, cwds, cmd)
    return (cwds, cwds)


def _shq(v):
    return "'" + v.replace("'", "'\\''") + "'"


DEF_UNKNOWN_RE = re.compile(r"\bfunctions\b|\bautoload\b|\bsource\b|(^|[\s;&|(])\.(\s|$)|\beval\b|\bemulate\b|"
                            r"\$\(|`|\$\{\(|\bzle\b|\balias\b")


def note_definitions(state, payload, cwds=None):
    """review 7 M4: the functions a literal eval / emulate -c string (or a file this call wrote and sources) may
    define (`f(){ … }`, `function f`), kept with that text; a string the guard cannot read, or one that may define by
    other means (eval, source, functions[…], a substitution, a name with an expansion), may define any name."""
    if payload is None or DEF_UNKNOWN_RE.search(payload):
        state.defs_unknown = True
        if payload is None:
            return
    names = set(re.findall(r"([^\s;&|(){}<>'\"]+)\s*\(\s*\)", payload))
    for m in re.finditer(r"\bfunction\s+([^;&|(){}<>'\"]+)", payload):
        names.update(m.group(1).split())
    for n in names:
        if re.search(r"[$\\]", n):
            state.defs_unknown = True
        else:
            state.defs_src[n] = (payload, cwd_list(cwds))


def _positionals_moved(state, names=()):
    """`shift`, `set --`, `argv=…`: a known $1, $2, … (`1=…`) no longer says what the parameter holds (review 7 M3)."""
    for k in list(state.vars):
        if (k.isdigit() and k != "0") or k in names:
            state.vars[k] = DYN
    for k in list(state.cands):
        if (k.isdigit() and k != "0") or k in POSITIONAL or k == "*" or k in names:
            del state.cands[k]


def b_shift(w, cmd, cwds, state):
    """`shift [n] [array…]`: moves the positional parameters, or the named arrays' elements."""
    names = [a.value for a in _args(cmd) if a.value is not None and not re.match(r"^[-+]?\d+$", a.value)]
    if any(a.value is None for a in _args(cmd)):
        names = list(state.vars)
    keep = {k: v for k, v in state.cands.items() if k.isdigit() and k != "0" or k in POSITIONAL or k == "*"}
    allv = tuple(dict.fromkeys(x for v in keep.values() for x in v[0]))[:MAX_CANDS]
    _positionals_moved(state, names)
    if allv and not names:
        # review 9: after shift each positional parameter is one of the values they held
        for k in keep:
            state.cands[k] = (allv, all(v[1] for v in keep.values()))
    return (cwds, cwds)


def b_true(w, cmd, cwds, state):
    return (cwds, ())


def b_false(w, cmd, cwds, state):
    return ((), cwds)


BUILTINS = {"cd": b_cd, "chdir": b_cd, "pushd": b_pushd, "popd": b_popd, "dirs": b_dirs, "export": b_export,
            "declare": b_export, "typeset": b_export, "local": b_export, "readonly": b_export,
            "integer": b_export, "float": b_export, "private": b_export, "unset": b_unset, "alias": b_alias, "unalias": b_noop,
            "source": b_source, ".": b_source, "eval": b_eval, "exit": b_exit, "return": b_exit, "logout": b_exit,
            "set": b_set, "shift": b_shift, "trap": b_trap, "hash": b_hash, "enable": b_hash, "disable": b_hash,
            "unfunction": b_unfunction, "unhash": b_unfunction,
            "setopt": b_setopt, "unsetopt": b_setopt, "emulate": b_emulate, "let": b_let, "true": b_true,
            ":": b_true, "false": b_false}
