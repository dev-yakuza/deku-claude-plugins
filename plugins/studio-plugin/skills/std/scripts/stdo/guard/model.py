"""The scanner's result structures (m0d1a-plan §4). M0d-1b consumes them; `to_dict()` gives JSON for
fixtures and debugging. Python 3.9: plain classes, no slots/kw_only dataclasses."""

SCAN_SCHEMA = 1
NOT_ALIAS = None  # the "not an alias" alternative of an ambiguous alias


def _d(v):
    if hasattr(v, "to_dict"):
        return v.to_dict()
    if isinstance(v, (list, tuple)):
        return [_d(x) for x in v]
    if isinstance(v, (set, frozenset)):
        return sorted(_d(x) for x in v)
    if isinstance(v, dict):
        return {k: _d(x) for k, x in v.items()}
    return v


class Base(object):
    FIELDS = ()

    def to_dict(self):
        return {f: _d(getattr(self, f)) for f in self.FIELDS}

    def __repr__(self):
        return "%s(%s)" % (type(self).__name__, ", ".join("%s=%r" % (f, getattr(self, f)) for f in self.FIELDS))


class Hit(Base):
    FIELDS = ("term", "kind", "offset")

    def __init__(self, term, kind, offset):
        self.term, self.kind, self.offset = term, kind, offset


class Word(Base):
    """One argument after quote removal. `value` is None when any part is dynamic."""
    FIELDS = ("raw", "value", "dynamic", "dyn", "skeleton", "glob", "glob_base", "quoted", "alt")

    def __init__(self, raw, value, dynamic=False, dyn=None, skeleton=None, glob=False, glob_base=None,
                 quoted=False, alt=None, plain=False):
        self.raw = raw
        self.value = value
        self.dynamic = dynamic
        self.dyn = list(dyn or [])
        self.skeleton = skeleton if skeleton is not None else (value if value is not None else "")
        self.glob = glob
        self.glob_base = glob_base
        self.quoted = quoted
        self.alt = alt
        self.plain = plain  # unquoted, no escapes, no expansions (alias candidates)

    @classmethod
    def lit(cls, text):
        return cls(text, text, plain=True)


class Redir(Base):
    FIELDS = ("fd", "op", "mode", "target", "body", "body_dynamic")

    def __init__(self, fd, op, mode, target=None, body=None, body_dynamic=False):
        self.fd, self.op, self.mode, self.target = fd, op, mode, target
        self.body, self.body_dynamic = body, body_dynamic


class EnvOp(Base):
    FIELDS = ("via", "kind", "name", "value")

    def __init__(self, via, kind, name=None, value=None):
        self.via, self.kind, self.name, self.value = via, kind, name, value


class EnvView(Base):
    FIELDS = ("ops", "cleared", "set", "unset", "unknown")

    def __init__(self, ops=None):
        self.ops = list(ops or [])
        self.cleared = False
        self.set = {}
        self.unset = set()
        self.unknown = False
        for op in self.ops:
            self.apply(op)

    def apply(self, op):
        if op.kind == "clear":
            self.cleared = True
            self.set, self.unset = {}, set()
        elif op.kind == "set":
            self.set[op.name] = op.value
            self.unset.discard(op.name)
        elif op.kind == "unset":
            self.set.pop(op.name, None)
            self.unset.add(op.name)
        elif op.kind == "unknown":
            self.unknown = True


class Wrapper(Base):
    FIELDS = ("name", "args", "effect")

    def __init__(self, name, args, effect="none"):
        self.name, self.args, self.effect = name, list(args), effect


class LockWrap(Base):
    FIELDS = ("sub", "kind", "holder", "ids", "script", "verified", "usage_error")

    def __init__(self, sub, kind=None, holder=None, ids=None, script=None, verified=False, usage_error=None):
        self.sub, self.kind, self.holder, self.ids = sub, kind, holder, list(ids or [])
        self.script, self.verified, self.usage_error = script, verified, usage_error


class GitInfo(Base):
    FIELDS = ("sub", "args", "c_dirs", "git_dir", "work_tree", "configs", "env")

    def __init__(self):
        self.sub, self.args, self.c_dirs = None, [], []
        self.git_dir = self.work_tree = None
        self.configs, self.env = [], {}


class ScriptCall(Base):
    FIELDS = ("interp", "path", "args")

    def __init__(self, interp, path, args):
        self.interp, self.path, self.args = interp, path, list(args)


class S2vForm(Base):
    FIELDS = ("form", "args", "accepted", "verified", "s2v_like")

    def __init__(self, form, args, accepted=False, verified=False, s2v_like=True):
        self.form, self.args, self.accepted, self.verified, self.s2v_like = form, list(args), accepted, verified, s2v_like


class Cmd(Base):
    FIELDS = ("id", "parent", "ctx", "words", "argv", "prog", "prog_key", "alt", "aliases", "wrappers", "lock",
              "env", "redirs", "cwds", "run_cwds", "git", "script", "s2v", "flags", "span")

    def __init__(self, id, words, cwds, ctx=None, parent=None, span=(0, 0)):
        self.id = id
        self.parent = parent
        self.ctx = list(ctx or [])
        self.words = list(words)
        self.alt = None
        self.aliases = []
        self.wrappers = []
        self.lock = None
        self.env = EnvView()
        self.redirs = []
        self.cwds = list(cwds) if cwds is not None else []
        self.run_cwds = list(self.cwds)
        self.git = None
        self.script = None
        self.s2v = None
        self.flags = set()
        self.span = span

    @property
    def argv(self):
        return [w.value for w in self.words]

    @property
    def prog(self):
        if not self.words or self.words[0].value is None:
            return None
        v = self.words[0].value
        return v.rsplit("/", 1)[-1] if "/" in v else v

    @property
    def prog_key(self):
        p = self.prog
        if p is None:
            return None
        import unicodedata
        return unicodedata.normalize("NFC", p).casefold()

    @property
    def cwd_known(self):
        return bool(self.cwds)


class Opaque(Base):
    FIELDS = ("kind", "cmd", "payload", "origin", "hits", "hits_unknown", "literals", "path", "path_class", "cwds",
              "alt")

    def __init__(self, kind, cmd=None, payload=None, origin="literal", cwds=None, path=None, path_class=None):
        self.kind, self.cmd, self.payload, self.origin = kind, cmd, payload, origin
        self.hits = []
        self.hits_unknown = payload is None
        self.literals = []
        self.path, self.path_class = path, path_class
        self.cwds = list(cwds or [])
        self.alt = None


class Scan(Base):
    FIELDS = ("schema", "status", "reason", "raw", "raw_hits", "commands", "opaque", "notes", "stats")

    def __init__(self, raw):
        self.schema = SCAN_SCHEMA
        self.status = "ok"
        self.reason = ""
        self.raw = raw
        self.raw_hits = []
        self.commands = []
        self.opaque = []
        self.notes = []
        self.stats = {}

    def note(self, text):
        if text not in self.notes:
            self.notes.append(text)
