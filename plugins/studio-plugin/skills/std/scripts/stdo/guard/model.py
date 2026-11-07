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
        # G1 §3 (argv words only): the shell drops it (an unquoted empty expansion), may drop it (unquoted expansions
        # of unknown value only), or it may give several words or none
        self.drop = self.maybe_empty = self.multi = False
        self.glob_walk = self.extglob = False  # G1 §2: a glob's `**` may be expanded by listing; ^ ~ # are globs
        # review 4 conf M-2: positions in `value` of characters zsh may read as a pattern (unquoted); None: unknown
        # (every glob character is one)
        self.wild = None
        # review 9: values a dynamic word may have — the candidates of values the guard does not carry (walk.cands)
        self.cand_values = ()
        self.cand_loose = ()  # words of a command whose output the value is: judged when they name a protected thing
        self.cand_complete = False  # review 10: the value is one of cand_values exactly (no unknown member)

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
    """A runner walk unwrapped (G1 §1.2): `files` are its own file arguments [(Word, op)] with op write, read or
    write-dir; `cwd` the run folders in effect for their relative paths (after an earlier env -C / sudo -D)."""
    FIELDS = ("name", "args", "effect", "files", "cwd")

    def __init__(self, name, args, effect="none", files=(), cwd=None):
        self.name, self.args, self.effect = name, list(args), effect
        self.files = list(files)
        self.cwd = list(cwd) if cwd is not None else None


class LockWrap(Base):
    FIELDS = ("sub", "kind", "holder", "ids", "script", "verified", "usage_error")

    def __init__(self, sub, kind=None, holder=None, ids=None, script=None, verified=False, usage_error=None):
        self.sub, self.kind, self.holder, self.ids = sub, kind, holder, list(ids or [])
        self.script, self.verified, self.usage_error = script, verified, usage_error


class GitInfo(Base):
    FIELDS = ("sub", "args", "c_dirs", "git_dir", "work_tree", "configs", "env")

    def __init__(self):
        self.sub, self.args, self.c_dirs = None, [], []
        self.sub_dynamic = False  # the subcommand slot holds a word the guard cannot read (G1 §3)
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
              "env", "redirs", "cwds", "run_cwds", "git", "script", "s2v", "flags", "span", "files")

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
        self.files = []  # a runner that is the program (no command, refused): its own file arguments [(Word, op)]
        self.run_words = []  # run-folder words the guard cannot read (env -C $D, sudo -D $D; G1 §1.7a)
        self.start_folders = None  # where the program starts, before its own -C (walk.recognize)
        self.glob_folders = []  # [(folders, pattern)]: an unknown folder a wildcard names (`cd stu?io`, review 2 M12)

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
        self.skeleton = None  # a string the guard cannot read: its text with \0 for each unknown part (G1 §1.7)
        self.options = None   # shell options in effect for the string (emulate sh -c: posixbuiltins)
        self.input = None     # (fd 0, {fd: description}) the string runs with (review 7 M4); False: none


def input_key(inp):
    """A comparable form of a nested string's input (Opaque.input; review 7 M4)."""
    if not inp:
        return None

    def one(d):
        if d is None:
            return None
        k, v = d
        if k == "redir":
            return (k, v.mode, v.body, v.body_dynamic)
        return (k, v)
    return (one(inp[0]), tuple(sorted((f, one(d)) for f, d in (inp[1] or {}).items())))


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
        # fix20: the walk stopped at a `source` / `.` (walk.mark_sourced) in some reading — later commands are not in
        # `commands` / `opaque`: the 0.0.26 guard judges them (backstop.decide)
        self.sourced = False

    def note(self, text):
        if text not in self.notes:
            self.notes.append(text)
