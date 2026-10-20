"""Shared state of one scan: limits, options, notes, the snapshot and the alias-alternative oracle."""

from . import limits, where
from .snapshot import DEFAULT_OPTIONS, BASH_TOOL_POSTLUDE

ZSH_BUILTINS = set("""
. : [ alias autoload bg bindkey break builtin bye cd chdir command compadd comparguments compcall compctl
compdescribe compfiles compgroups compquote comptags comptry compvalues continue declare dirs disable disown echo
emulate enable eval exec exit export false fc fg float functions getln getopts hash history integer jobs kill let
limit local log logout noglob nocorrect popd print printf pushd pushln pwd r read readonly rehash return sched set
setopt shift source suspend test times trap true ttyctl type typeset ulimit umask unalias unfunction unhash
unlimit unset unsetopt vared wait whence where which zcompile zformat zle zmodload zparseopts zstyle - time
""".split())


class LexCtx(object):
    """Minimal context for reading words outside a scan (snapshot lines)."""

    def __init__(self, options=None):
        self.budget = limits.Budget(cpu=60, wall=60)
        self.tokens = 0
        self.depth = 0
        self.options = dict(options or {})
        self.notes = []

    def note(self, text):
        if text not in self.notes:
            self.notes.append(text)

    def depth_enter(self, pos):
        self.depth += 1
        if self.depth > limits.MAX_DEPTH:
            raise limits.LimitExceeded("depth")

    def depth_leave(self):
        self.depth -= 1

    def alias_values(self, name):
        return None

    def choose(self, name, values, pos):
        return 0

    def alias_source(self, name, value):
        return None

    def alias_ambiguous(self, name):
        return False


class Oracle(object):
    """Which alternative this parse takes at each ambiguous alias (depth-first enumeration)."""

    def __init__(self, prefix, schedule):
        self.prefix = list(prefix)
        self.taken = []
        self.schedule = schedule  # callable(prefix_list, n) -> bool (False: no room → opaque)

    def choose(self, n):
        k = len(self.taken)
        if k < len(self.prefix):
            c = self.prefix[k]
        elif n > limits.ALT_MAX:
            c = -1
        else:
            c = 0 if self.schedule(self.taken, n) else -1
        self.taken.append(c)
        return c


class ScanCtx(LexCtx):
    def __init__(self, env, fs, snapshot=None, snapshot_notes=(), terms=None, budget=None, s2v_path=None):
        LexCtx.__init__(self)
        self.env = dict(env)
        self.fs = fs
        self.where = where.Where(fs, self.env)
        self.snapshot = snapshot
        self.snapshot_notes = list(snapshot_notes)
        self.terms = terms
        self.budget = budget or limits.Budget()
        self.s2v_path = s2v_path
        if snapshot is not None:
            self.options = dict(snapshot.options)
        else:
            self.options = dict(DEFAULT_OPTIONS)
            self.options.update(BASH_TOOL_POSTLUDE["options"])
        self.oracle = None
        self.inline_functions = set()

    # ---- PATH ----

    def path_values(self):
        """The PATH strings a Bash call may run with (snapshot exports win over the hook's PATH)."""
        if self.snapshot is not None and self.snapshot.paths:
            return list(self.snapshot.paths)
        return [self.env.get("PATH", "")]

    def which_any(self, name):
        for pv in self.path_values():
            p = where.which(name, pv, self.fs)
            if p:
                return p
        return None

    def runnable(self, name):
        """Something zsh could run under this name without an alias."""
        if name in ZSH_BUILTINS or name in ("[[", "{", "if", "for", "while", "case"):
            return True
        if self.snapshot is not None and (name in self.snapshot.user_functions or name in self.snapshot.delegated):
            return True
        if name in self.inline_functions:
            return True
        return self.which_any(name) is not None

    # ---- aliases ----

    def alias_values(self, name):
        s = self.snapshot
        if s is None:
            return None
        if name in s.plain:
            return [s.plain[name]]
        alts = s.alternatives.get(name)
        if not alts:
            return None
        out = [v for v in alts if v is not None or self.runnable(name)]
        return out or None

    def alias_ambiguous(self, name):
        return self.snapshot is not None and name in self.snapshot.alternatives

    def choose(self, name, values, pos):
        if self.oracle is None:
            return 0
        return self.oracle.choose(len(values))

    def alias_source(self, name, value):
        return self.snapshot.source(name, value) if self.snapshot is not None else None
