"""The guard's judgement (M0d-1b, m0d1b-plan v2). `decide(hook_input, env)` -> (Deny | None, repos).

Two outcomes only: deny, or no decision (the normal permission flow). Never allow, ask or defer.
"""

import copy
import fnmatch
import json
import os
import re
import stat

from .. import paths, s2vcall
from ..state import commands as state_commands
from . import cmdopts, commitrule, gitprobe, hookfiles, limits, messages, protect, ranlog, recog, runners, sedshape
from . import scan as scan_command
from . import load_snapshot
from .messages import Deny
from .model import Word, input_key as model_input_key
from .repos import LOCK_VARS, Repos, has_exclude_block, terms_for
from .snapshot import BASH_TOOL_POSTLUDE, DEFAULT_OPTIONS as SNAP_DEFAULT_OPTIONS
from .where import FS, Where, which as where_which

PLUGIN_SCRIPTS = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
# the scripts folder as ${CLAUDE_PLUGIN_ROOT} spells it (guard.py puts its own unresolved folder on sys.path)
PLUGIN_SCRIPTS_SPELLED = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOC_SCRIPTS = (os.path.join(PLUGIN_SCRIPTS, "setup.py"), os.path.join(PLUGIN_SCRIPTS_SPELLED, "setup.py"))
STUDIO_NAMES_RE = re.compile(r"\bSTUDIO_(SANDBOX|HOME|TEST_[A-Za-z0-9_]*)\b")
MARKER_VARS = ("CLAUDECODE", "CLAUDE_CODE_SESSION_ID")
S2V_APPROVALS = {("character", "pick"), ("character", "approve"), ("voice", "pick"), ("takes", "pick"),
                 ("takes", "unpick")}
MCP_PATH_KEYS = ("path", "file_path", "filepath", "destination", "source", "target", "dest", "src", "filename",
                 "directory", "dir")
MCP_LIST_KEYS = ("paths", "files", "sources", "targets")
MAX_CANDIDATES = 500


class Context(object):
    def __init__(self, hook, env, fs=None, probe=None, snapshot_loader=None):
        self.hook = hook
        self.env = dict(env)
        self.cwd = hook.get("cwd") or os.getcwd()
        self.fs = fs or FS()
        self.where = Where(self.fs, self.env)
        self.repos = Repos(self.where, self.env)
        self.probe = probe or gitprobe.Probe(self.env)
        self.snapshot_loader = snapshot_loader or load_snapshot
        try:
            self.user_dir = paths.user_dir(self.env)
        except ValueError:
            self.user_dir = os.path.join(self.env.get("HOME") or os.path.expanduser("~"), ".claude")
        home = self.env.get("HOME") or os.path.expanduser("~")
        states = [os.path.join(home, ".s2v")]
        sd = self.env.get("S2V_STATE_DIR")
        if sd and os.path.isabs(sd):
            states.insert(0, sd)
        self.state_dirs = states
        items = protect.out_of_repo(self.user_dir, states)
        pdata = self.env.get("CLAUDE_PLUGIN_DATA")
        if pdata and os.path.isabs(pdata):
            items.append((os.path.join(pdata, "pycache"), "dir"))  # the guard's own bytecode
        self.out_items = [(self._real(p), k) for p, k in items]
        self.touched = []  # RepoInfo of Studio repositories this call involves (for the guard-ran record)
        self.denies = []
        # M0d-2: an allow needs evidence (approval commands, Studio commits) and the call being that command alone
        self.allow = None  # the reason, when the guard answers allow
        self.candidates = []  # (cmd, kind "state" | "commit" | "s2v" | "doc" | "script" | "work", reason)
        self.script_calls = {}  # id(cmd) → (worktree, studio_root, video, sub) of a "script" candidate (0.0.28 §1.1)
        self.bulk_ids = set()  # extractions and recursive copies in a Studio repository (W4)
        self.effects = []  # (rule, function) run only when nothing is denied
        self.warnings = []  # shown to the person and the model when there is no decision
        self.snap = None
        self.scan = None
        self.approvals = 0
        cfg = self.env.get("CLAUDE_CONFIG_DIR") or os.path.join(self.env.get("HOME") or os.path.expanduser("~"),
                                                                 ".claude")
        projects = os.path.join(cfg, "projects")  # transcripts: the evidence of a person's answers (M0d-2)
        self.out_items.append((self._real(projects), "transcripts"))
        self.current = None  # the command being judged (its alias sources go into messages)
        self.commit_memo = {}  # review 17 (C17-4): the commit check of one command's readings (judge_git)
        # review 19 (C19-2): push / commit checks of commands in nested strings, shared by identical ones (_nested_key)
        self.nested_memo = {}
        # fix20: a scan of this call stopped at a `source` / `.` (judge._scan) — the rest is the 0.0.26 guard's alone
        self.sourced = False

    @property
    def current(self):
        return self.__dict__.get("_current")

    @current.setter
    def current(self, c):
        self._current = c
        # review 17 (B17-3): git probes are shared only by the readings of one command (the same text in the same
        # scan: walk's lost-folder / HEAD's / choice readings), not by later commands of the call
        # (review 18 B18-2: a nested string's commands carry their own scan — the same text run by another command is
        # another command)
        sp = tuple(getattr(c, "span", None) or ()) if c is not None else ()
        scope = None if not sp or sp == (0, 0) else (getattr(c, "scan_key", None) or id(self.scan), sp, c.prog)
        try:
            self.probe.scope = scope
        except AttributeError:
            pass

    def _real(self, p):
        anc, tail = p, ""
        while anc not in ("/", "") and not os.path.exists(anc):
            tail = os.path.join(os.path.basename(anc), tail) if tail else os.path.basename(anc)
            anc = os.path.dirname(anc)
        r = os.path.realpath(anc)
        return os.path.join(r, tail) if tail else r

    def deny(self, rule, text, sources=(), suffix=None):
        """suffix: a closing line other than INV9 (messages.NONSTOP, an evidence suffix); shown only when every deny
        of the call has the same one."""
        src = list(sources)
        if self.current is not None:
            for s in messages.alias_sources(self.current):
                if s not in src:
                    src.insert(0, s)
        if "lost-folder" in (getattr(self.current, "ctx", None) or ()) and \
                any(d.rule == rule and d.text == text for d in self.denies):
            return  # the same refusal from another reading of one command (review 10: each folder it may run in)
        self.denies.append(Deny(rule, text, src, suffix=suffix))

    def touch(self, ri):
        if ri is not None and ri.studio and ri not in self.touched:
            self.touched.append(ri)


# ---- helpers ----

def _inside(path, root):
    return path == root or path.startswith(root.rstrip("/") + "/")


def out_hit(ctx, real, op):
    """Whether `real` (an absolute real path) touches a per-user/machine-lock file. op: write|delete|read."""
    if real is None:
        return None
    for item, kind in ctx.out_items:
        if kind == "transcripts":
            if op == "read":
                continue
            if _inside(real, item):
                parts = os.path.relpath(real, item).split(os.sep)
                if (len(parts) == 2 and parts[1].endswith(".jsonl")) or (len(parts) >= 3 and parts[2] == "subagents") \
                        or (op == "delete" and len(parts) == 1 and parts[0] not in (".", "")):
                    return item
            elif op == "delete" and _inside(item, real):
                return item
            continue
        if kind == "prefix":
            hit = real.startswith(item) or _inside(real, item)
            parent_hit = op == "delete" and _inside(item, real)
        else:
            hit = _inside(real, item)
            parent_hit = op == "delete" and _inside(item, real)
        if op == "read":
            if kind == "prefix" and (real.startswith(item)) and real.endswith("/owner.json"):
                return item
            continue
        if hit or parent_hit:
            return item
    return None


def is_owner_json(real):
    return real is not None and real.endswith("/owner.json") and (
        "/heavy.lock.d" in real or "/.work/op.lock.d" in real)


def studio_script(ctx, cmd, name=None):
    """The real path when this command runs a Studio script (repository copy or the plugin's)."""
    sc = cmd.script
    if sc is None:
        return None
    path = sc.path if isinstance(sc.path, dict) else {}
    real = path.get("real")
    if not real:
        return None
    base = os.path.basename(real)
    if name and base != name:
        return None
    if os.path.dirname(real) == PLUGIN_SCRIPTS:
        return real
    parent = os.path.dirname(real)
    if parent.endswith("/.claude/studio/scripts"):
        root = parent[:-len("/.claude/studio/scripts")]
        ri = ctx.repos.info(ctx.where.git_repo(root)) if ctx.fs.exists(root) else None
        if ri is not None and ri.harness and os.path.realpath(ri.worktree) == os.path.realpath(root):
            return real
    return None


def candidates(cmd):
    """(Word, value) path candidates of a command: arguments, `=value` parts, redirect targets."""
    out = []
    for w in cmd.words[1:]:
        vals = []
        if w.value is not None:
            vals.append(w.value)
            if "=" in w.value:
                v = w.value.split("=", 1)[1]
                if v:
                    vals.append(v)
        if w.alt and w.alt != "\0":
            vals.append(w.alt)
        vals.extend(v for v in list(getattr(w, "cand_values", ())) + list(getattr(w, "cand_loose", ()))
                    if v not in vals)  # review 9
        out.append((w, vals))
    return out


def run_folders(cmd):
    """The folders a command's relative paths resolve against: its run folders (env -C, sudo -D, git -C, …) or its
    own; [] when the guard cannot tell them (a dynamic or overflowed `cd`, `env -C $D`: G1 §1.7a)."""
    if "run-unknown" in cmd.flags:
        return []
    return list(cmd.run_cwds or cmd.cwds or [])


def resolve_all(ctx, cmd, value):
    """[(abs, real, RepoInfo|None)] for a literal value across the command's cwds."""
    res = []
    if os.path.isabs(value):
        cwds = [None]
    else:
        cwds = run_folders(cmd)
        if not cwds:
            return [(None, None, None)]
    for c in cwds:
        r = ctx.where.resolve(value, c)
        if r is None or r.abs is None:
            res.append((None, None, None))
            continue
        ri = ctx.repos.info(r.repo) if r.repo is not None else None
        res.append((r.abs, r.real, ri))
    return res


def rel(ctx, ri, real):
    fold = ctx.where.case_insensitive(real)
    parts = protect.rel_parts(real, ri.worktree, fold)
    return parts, fold


def looks_like_path(value, cmd, ctx):
    if not value or value.startswith("-") and "=" not in value:
        return False
    if "/" in value or value in (".", ".."):
        return True
    for c in run_folders(cmd):  # where the program runs (env -C, sudo -D: M2)
        if ctx.fs.exists(os.path.join(c, value)):
            return True
    return False


# ---- per-command checks ----

def effective(cmd):
    """(program, argument Words) with package runners unwrapped (`npx rimraf x` → rimraf, [x]). The options are read
    by runners.package (G1 §1.3); a shell string (`npx -c '…'`) or a refused runner is the runner itself."""
    prog = cmd.prog or ""
    words = cmd.words[1:]
    p, end = runners.package(cmd.prog_key, cmd.words, cmd.env.set)
    if p is None or p.outcome != "unwrap" or "runner-unread" in cmd.flags:
        return prog, words
    w = cmd.words[end]
    if w.value is None:
        return prog, words
    name = w.value.split("@")[0] if not w.value.startswith("@") else w.value
    return os.path.basename(name), cmd.words[end + 1:]


FIND_NAME_TESTS = ("-name", "-iname", "-path", "-ipath", "-wholename", "-iwholename", "-regex", "-iregex", "-lname")


def find_starts_in_studio(ctx, cmd, studio_infos):
    """A start path inside a Studio folder: every match there may be protected (voices/**, character/**)."""
    for w in cmd.words[1:]:
        v = w.value
        if v is None:
            return True
        if v.startswith("-") or v in ("(", "!"):
            break
        for a, real, ri in resolve_all(ctx, cmd, v):
            if ri is None or not ri.studio or real is None:
                continue
            parts, fold = rel(ctx, ri, real)
            if parts and (parts[:1] == [ri.studio_root] or parts[:2] == [".claude", "studio"]):
                return True
    return False


def find_may_hit(argv, studio_infos):
    """Whether a find's name/path conditions could select protected items (no conditions: yes)."""
    names = set(protect.TAIL_NAMES) | {"studio", ".claude", "work", "videos", "cast", "voices", "audio", "local",
                                       "character", "consent"}
    for ri in studio_infos:
        names.add(ri.studio_root)
    conds = []
    for i, a in enumerate(argv):
        if a in ("!", "-not", "-o", "-or"):
            return True  # negations and alternatives: cannot tell
        if a in FIND_NAME_TESTS:
            v = argv[i + 1] if i + 1 < len(argv) else None
            if v is None or a in ("-regex", "-iregex"):
                return True
            conds.append((a, v))
    if not conds:
        return True
    import fnmatch as _fn
    for a, v in conds:
        fold = a.startswith("-i")
        segs = [x for x in v.split("/") if x not in ("", ".")] if "path" in a else [v]
        for seg in segs:
            for n in names:
                if _fn.fnmatchcase(n.casefold() if fold else n, seg.casefold() if fold else seg):
                    return True
    return False


ARGV_WHY = ("%s has words that may expand to several or none (an unquoted $@, ${=X}, ${~X}, an array, or more than "
            "three words that may be empty) — in a Studio repository the guard cannot tell its arguments; write them "
            "literally or quote the expansions, one step per call.")


ARGV_CHOICES_WHY = ("%s has words that are each one of several known values, with more than %d combinations of them "
                    "— the guard judges at most %d; write the values literally or split the command, one step per "
                    "call.")


def check_paths(ctx, cmd, studio_infos):
    if studio_infos and "argv-unknown" in cmd.flags:
        if "argv-choices" in cmd.flags:  # review 12 conf m-3
            from .walk import MAX_CHOICE_READINGS
            ctx.deny("G-OPAQUE", ARGV_CHOICES_WHY % (cmd.prog or "the command", MAX_CHOICE_READINGS,
                                                     MAX_CHOICE_READINGS))
        else:
            ctx.deny("G-OPAQUE", ARGV_WHY % (cmd.prog or "the command"))  # G1 §3
        return
    prog, eff_words = effective(cmd)
    if cmd.lock is not None or studio_script(ctx, cmd):
        writes_ok = True
    else:
        writes_ok = False
    argv = [cmd.words[0].value if cmd.words else None] + [w.value for w in eff_words]
    is_s2v = cmd.s2v is not None
    role = "write"
    if prog in protect.READ_ALLOW:
        role = "read"
        exec_tpl = [argv[i + 1] for i, a in enumerate(argv[:-1]) if a in ("-exec", "-execdir", "-ok", "-okdir")]
        if prog in ("find", "bfs") and ("-delete" in argv or any(
                t is None or os.path.basename(t) not in protect.READ_ALLOW for t in exec_tpl)) and \
                (find_starts_in_studio(ctx, cmd, studio_infos) or find_may_hit(argv, studio_infos)):
            role = "find-write"  # -delete, or -exec of a command that may write: the start paths are at stake
        elif prog in ("find", "bfs") and any(a in ("-fprint", "-fprint0", "-fprintf", "-fls") for a in argv if a):
            role = "find-print"
        if prog == "jq":
            role = "read"
    if "via-function" in cmd.flags and prog in ("grep", "find", "rg"):
        pass
    if prog == "git":
        role = "git"
    if prog in protect.DELETE_PROGS or prog in ("mv", "rsync"):
        role = prog
    if prog == "gio" and argv[1:2] in (["trash"], ["remove"]):
        role = "rm"
        eff_words = eff_words[1:]
    if prog == "zip" and any(a and (a == "-m" or a == "--move" or re.match(r"^-[a-zA-Z]*m", a)) for a in argv[1:]):
        role = "zip-move"
    if prog in ("tar", "gtar", "bsdtar") and "--remove-files" in argv:
        role = "tar-remove"
    # redirects
    for r in cmd.redirs:
        if r.target is None or r.mode not in ("write", "append", "rw"):
            continue
        check_target(ctx, cmd, r.target, r.target.value, "write", studio_infos, s2v=False)
    # G1 §1.6: the runners' own file arguments (time -o, flock LOCK, script FILE, sudo -e, watch -s, …); reads only
    # through check_out_of_repo
    for wc, files in runner_files(cmd):
        for w, op in files:
            if op != "read":
                check_target(ctx, wc, w, w.value, op, studio_infos, s2v=False)
    if is_sed(cmd) and check_sed(ctx, cmd, studio_infos):
        return  # its shape decided (fix-0025 §1); an unchecked sed outside a Studio repository is a writer below
    if cmd.prog_key == "parallel" and studio_infos and parallel_runs_sed(cmd):
        ctx.deny("G-OPAQUE", SED_WHY % "sed run by parallel", suffix=messages.NONSTOP)
        return
    if prog in protect.READ_WRITERS and not writes_ok:
        # G1 §1.11: READ_ALLOW programs that can write a file or run a program
        for w, v in read_writer_targets(ctx, cmd, prog, eff_words, studio_infos):
            check_target(ctx, cmd, w, v, "write", studio_infos)
    if writes_ok or role in ("read", "git"):
        if role == "git":
            check_git(ctx, cmd, studio_infos)
        return
    recursive = any(a and (a in ("-r", "-R", "--recursive") or re.match(r"^-[a-zA-Z]*[rR]", a)) for a in argv[1:])
    # G1 §2 (B1): a `**` glob zsh runs with its existing matches is replaced by them, and the operand roles are read
    # on that argv (`mv a.txt **/work/`: every match but the last is a source)
    words = listed_globs(ctx, cmd, eff_words)
    targets = []  # (word, value, op)
    if role in protect.DELETE_PROGS - {"rmdir"}:
        for w in words:
            if w.value is not None and w.value.startswith("-"):
                continue
            targets.append((w, w.value, "delete" if (recursive or role != "rm") else "delete-file"))
    elif role in ("zip-move", "tar-remove"):
        ops = [w for w in words if w.value is None or not w.value.startswith("-")]
        for w in ops[1:]:  # the first operand is the archive
            targets.append((w, w.value, "delete"))
    elif role == "rmdir":
        for w in words:
            if w.value is None or not w.value.startswith("-"):
                targets.append((w, w.value, "delete"))
    elif role == "mv":
        ops = [w for w in words if w.value is None or not w.value.startswith("-")]
        for w in ops[:-1]:
            targets.append((w, w.value, "delete"))
            targets += into_targets(cmd, w, ops[-1])
        if ops:
            targets.append((ops[-1], ops[-1].value, "write"))
    elif role == "rsync":
        ops = [w for w in words if w.value is None or not w.value.startswith("-")]
        delete = any(a and a.startswith("--delete") for a in argv[1:])
        # --remove-sent-files is its older name (review 2, M10)
        moved = any(a and cmdopts.long_option(a, ("--remove-source-files", "--remove-sent-files")) for a in argv[1:])
        for w in ops[:-1]:
            targets.append((w, w.value, "delete" if moved else "read"))  # --remove-source-files deletes the sources
            targets += into_targets(cmd, w, ops[-1])
        if ops:
            targets.append((ops[-1], ops[-1].value, "delete" if delete else "write"))
        for w, vals in candidates(cmd):
            if w.value and w.value.startswith("--") and "=" in w.value:
                targets.append((w, w.value.split("=", 1)[1], "write"))
    elif prog in ("cp", "install", "ln", "gcp"):
        ops = [w for w in words if w.value is None or not w.value.startswith("-")]
        tdir = None
        for i, w in enumerate(words):
            if w.value in ("-t",) and i + 1 < len(words):
                tdir = words[i + 1]
            elif w.value and w.value.startswith("--target-directory="):
                tdir = w
        if tdir is not None:
            dval = tdir.value.split("=", 1)[1] if tdir.value and tdir.value.startswith("--") else tdir.value
            for w in ops:
                if w is tdir or w.value == dval:
                    continue
                tv = os.path.join(dval, os.path.basename(w.value)) if (w.value and dval) else None
                targets.append((as_glob(tdir, tv) or w, tv, "write"))  # a wildcard folder keeps its reading (B-2)
        elif len(ops) >= 2:
            dest = ops[-1]
            if prog == "ln" or (prog in ("cp", "gcp") and hard_link_copy(argv)):
                # a hard link (ln, cp -l / --link / -al) shares the file: writing the copy writes the original
                for w in ops[:-1]:
                    targets.append((w, w.value, "link-source"))
            nt = prog in ("cp", "gcp", "install") and no_target_dir(argv)
            for w in ops[:-1]:
                into = not nt and dest.value is not None and any(ctx.fs.isdir(os.path.join(c, dest.value)) if not
                                                      os.path.isabs(dest.value) else ctx.fs.isdir(dest.value)
                                                      for c in (run_folders(cmd) or [None]) if c or os.path.isabs(dest.value))
                if into and w.value is not None:
                    targets.append((dest, os.path.join(dest.value, os.path.basename(w.value.rstrip("/"))), "write"))
                else:
                    targets.append((dest, dest.value, "write"))
                    if not nt:
                        targets += into_targets(cmd, w, dest)
    elif prog in EXTRACT_PROGS:
        pass  # judged by check_bulk
    elif role == "find-print":
        for i, w in enumerate(words):
            if w.value in ("-fprint", "-fprint0", "-fprintf", "-fls") and i + 1 < len(words):
                targets.append((words[i + 1], words[i + 1].value, "write"))
    elif role == "find-write":
        for w in words:
            if w.value is None:
                targets.append((w, None, "delete"))  # a start the guard cannot read (or nothing): the next words
                continue                              # may still be starts (M14)
            if w.value.startswith("-") or w.value in ("(", "!"):
                break
            targets.append((w, w.value, "delete"))
    else:
        lost = studio_infos and not run_folders(cmd)  # an unknown folder: any word may be a path (§1.7a)
        for w, vals in candidates(cmd):
            if w.value is None:
                targets.append((w, None, "write"))
                continue
            for v in vals:
                if looks_like_path(v, cmd, ctx) or (w.value != v) or (lost and not v.startswith("-")):
                    targets.append((w, v, "write"))
    for w, v, op in targets:
        if op == "read":
            continue
        check_target(ctx, cmd, w, v, op, studio_infos, s2v=is_s2v)
    if check_bulk(ctx, cmd, prog, argv, words, studio_infos):
        ctx.bulk_ids.add(cmd.id)
    # other `--opt=value` / `name=value` paths of ordinary writers (dd of=, --backup-dir=, …)
    if prog in ("cp", "install", "ln", "gcp", "tar", "gtar", "unzip", "ditto", "bsdtar"):
        for w in words:
            if w.value and "=" in w.value and not w.value.startswith(("--target-directory=", "--directory=")):
                v = w.value.split("=", 1)[1]
                if v and looks_like_path(v, cmd, ctx):
                    check_target(ctx, cmd, w, v, "write", studio_infos, s2v=is_s2v)


def as_glob(w, text):
    """A Word for `text` (a part of `w`, or a path built on it) that keeps w's wildcard reading, or None when `w` has
    no wildcard (fail closed: every `*?[` of the text counts, quoted or not)."""
    chars = "*?[<^~#" if getattr(w, "extglob", False) else "*?[<"
    if w is None or not w.glob or not text or not any(ch in text for ch in chars):
        return None
    k = min(text.find(ch) for ch in chars if ch in text)
    nw = Word(text, text, glob=True, glob_base=text[:text.rfind("/", 0, k) + 1])
    nw.extglob = getattr(w, "extglob", False)
    return nw


def into_targets(cmd, src, dest):
    """B-2 (review 2): a destination that is a wildcard, or lies in a folder the guard cannot tell, may be a folder
    the source is copied, moved or linked into — `<dest>/<source name>` is a target too (the listing is not used:
    the file may not exist yet)."""
    if src.value is None or dest.value is None or dest is src:
        return []
    unknown = not os.path.isabs(dest.value) and not run_folders(cmd)
    if not (dest.glob or unknown):
        return []
    tv = os.path.join(dest.value, os.path.basename(src.value.rstrip("/")) or ".")
    w = as_glob(dest, tv)
    if w is None:
        w = Word.lit(tv)
        if getattr(dest, "wild", None) is not None:  # the destination's quoting (review 4 conf M-2)
            w.wild = frozenset(set(dest.wild) | set(range(len(dest.value), len(tv))))
    return [(w, tv, "write")]


# ---------- writers whose file list is not known in advance (m1-plan §3.1 reviews V1/W1–W4) ----------
# Archive extractors and recursive copies. One rule: their destination folder must not be (or hold) Studio's
# folders — the repository root, .claude/**, <sr>/**, .git/** or the git common dir; a recursive copy whose source
# exists is judged entry by entry instead. Flags that let members leave the folder, and extractors whose behaviour
# was not measured, are refused in Studio repositories.

EXTRACT_PROGS = ("tar", "gtar", "bsdtar", "unzip", "ditto", "cpio", "pax", "7z", "7za", "7zz", "7zr", "bsdcpio")
WEAK_7Z = ("7z", "7za", "7zz", "7zr")
BUSYBOX_EXTRACT = ("tar", "unzip", "cpio", "rpm2cpio", "ar", "dpkg-deb", "rpm")
WALK_MAX = 500
BULK_WHY = ("%s writes files the guard cannot list beforehand into %s, which is (or holds) Studio's folders — extract "
            "or copy into another folder (e.g. a build folder) and copy the files you need.")


def _short_has(x, letters):
    return x is not None and x.startswith("-") and not x.startswith("--") and any(c in x[1:] for c in letters)


def _tar_like(prog):
    return prog in ("tar", "gtar", "bsdtar")


def extract_info(prog, argv, words):
    """(extracting, [(word or None, folder or None)], w1 reason or None). Folder None = not readable; an empty list =
    the working folder."""
    a = list(argv[1:])
    dirs = []
    w1 = None
    if _tar_like(prog):
        ext = any(x is None or x in ("--extract", "--get") or _short_has(x, "x")
                  or (i == 0 and not x.startswith("-") and "x" in x) for i, x in enumerate(a))
        for i, w in enumerate(words):
            v = w.value
            if v in ("-C", "--directory", "--cd") and i + 1 < len(words):
                dirs.append((words[i + 1], words[i + 1].value))
            elif v and v.startswith(("--directory=", "--cd=")):
                dirs.append((w, v.split("=", 1)[1]))
            elif v and v.startswith("-C") and len(v) > 2 and not v.startswith("--"):
                dirs.append((w, v[2:]))
            elif v is None and w.raw.startswith(("-C", "--directory")):
                dirs.append((w, None))
        for i, x in enumerate(a):
            if x is None:
                continue
            if x in ("-P", "--absolute-names") or _short_has(x, "P") or (i == 0 and not x.startswith("-") and "P" in x):
                w1 = "-P (absolute names)"
            elif x.startswith(("--transform", "--xform")) or x == "-s":
                w1 = "%s (renames members)" % x.split("=", 1)[0]
    elif prog == "unzip":
        ext = not any(x in ("-l", "-t", "-v", "-z", "-Z", "-p", "-c") for x in a if x)
        for i, w in enumerate(words):
            if w.value == "-d" and i + 1 < len(words):
                dirs.append((words[i + 1], words[i + 1].value))
            elif w.value and w.value.startswith("-d") and len(w.value) > 2:
                dirs.append((w, w.value[2:]))
        if any(x is not None and x.startswith("-") and not x.startswith("--") and ":" in x for x in a):
            w1 = "-: (keeps ../ in member names)"
    elif prog == "ditto":
        ext = any(x == "-x" or _short_has(x, "x") for x in a if x)
        ops = [w for w in words if w.value is None or not w.value.startswith("-")]
        if ext and ops:
            dirs.append((ops[-1], ops[-1].value))
    elif prog == "cpio":
        ext = any(x is None or x == "--extract" or _short_has(x, "i") for x in a)
        for i, w in enumerate(words):
            if w.value in ("-D", "--directory") and i + 1 < len(words):
                dirs.append((words[i + 1], words[i + 1].value))
            elif w.value and w.value.startswith("--directory="):
                dirs.append((w, w.value.split("=", 1)[1]))
        if ext and "--no-absolute-filenames" not in a:
            w1 = "cpio -i without --no-absolute-filenames"
    elif prog == "pax":
        ext = True
        w1 = "pax (its member names are not limited to the folder)"
    else:
        return False, [], None
    return ext, dirs, w1


def weak_extractor(cmd, prog, argv):
    """A reason when this is an extractor whose behaviour Studio did not measure (refused in Studio repositories)."""
    a = [x for x in argv[1:]]
    boxes = [w.name for w in cmd.wrappers if w.name in ("busybox", "toybox")]
    if boxes and (prog in BUSYBOX_EXTRACT or cmd.prog is None):  # G1 §1.5: an applet run through busybox/toybox
        return "%s %s" % (boxes[-1], prog or "?")
    if prog in WEAK_7Z:
        w = next((x for x in a if x is not None and not x.startswith("-")), None)
        if w is None or w.lower() in ("x", "e"):
            return "%s extraction" % prog
    elif prog == "bsdcpio":
        return "bsdcpio"
    elif recog.key(prog or "") in ("busybox", "toybox") or recog.key(prog or "").startswith(("busybox.", "busybox-")):
        if a and (a[0] is None or a[0] in BUSYBOX_EXTRACT):
            return "busybox %s" % (a[0] or "?")
    elif prog == "jar":
        if a and (a[0] is None or a[0].lstrip("-").startswith("x") or "--extract" in a):
            return "jar extraction"
    elif prog == "cmake":
        if len(a) >= 3 and a[0] == "-E" and a[1] == "tar" and (a[2] is None or "x" in a[2]):
            return "cmake -E tar extraction"
    elif re.match(r"^python(\d+(\.\d+)*)?$", prog or ""):
        if "-m" in a:
            i = a.index("-m")
            mod = a[i + 1] if i + 1 < len(a) else None
            if mod in ("tarfile", "zipfile", "shutil") and any(x in ("-e", "--extract") for x in a[i + 2:] if x):
                return "python -m %s -e" % mod
    return None


def recursive_copy(prog, argv):
    """'cp' | 'rsync' | 'ditto' | 'rsync-relative' when the command copies trees, else None."""
    a = [x for x in argv[1:] if x is not None]
    if prog in ("cp", "gcp"):
        if any(x in ("--recursive", "--archive") or (x.startswith("-") and not x.startswith("--") and
                                                     any(c in x[1:] for c in "rRa")) for x in a):
            return "cp"
    elif prog == "rsync":
        rec = any(x in ("--recursive", "--archive") or (x.startswith("-") and not x.startswith("--") and
                                                        any(c in x[1:] for c in "ra")) for x in a)
        rel_ = any(x == "--relative" or (x.startswith("-") and not x.startswith("--") and "R" in x[1:]) for x in a)
        if rel_:
            return "rsync-relative"
        if rec:
            return "rsync"
    elif prog == "ditto":
        if not any(x == "-x" or _short_has(x, "x") for x in a):
            return "ditto"
    return None


def studio_area(ctx, cmd, value, studio_infos, word=None):
    """None, or why the folder `value` is (or holds) Studio's folders: the repository root, .claude/**, <sr>/**,
    .git/**, the git common dir, or a folder above a Studio repository. `word`: the Word `value` comes from (a
    wildcard folder is matched as a pattern: review 2, B-2 and M11)."""
    if value is None:
        return "a folder the guard cannot read" if studio_infos else None
    gw = word if (word is not None and word.glob and word.value == value) else as_glob(word, value)
    if gw is not None:
        return glob_area(ctx, cmd, gw, studio_infos)
    for a, real, ri in resolve_all(ctx, cmd, value):
        if a is None:
            if studio_infos:
                return value
            continue
        r = real or a
        for si in studio_infos:
            wt = os.path.realpath(si.worktree)
            if wt.startswith(r.rstrip("/") + "/"):
                return value  # above a Studio repository
            for d in (si.common_dir, si.git_dir):
                if d and (r == os.path.realpath(d) or r.startswith(os.path.realpath(d) + "/")):
                    return value
        if ri is None or not ri.studio:
            continue
        parts, fold = rel(ctx, ri, r)
        if parts is None:
            continue
        if _within(parts, [".claude"], fold):
            return value + " (to put files under .claude/, copy into it from an existing folder in a separate call, " \
                           "or copy the files one by one)"
        if parts and _within(parts, [ri.studio_root], fold):
            return value + " (to put files under %s/, copy them one at a time — cp <file> <destination file> — or " \
                           "let the Studio script that makes them write them)" % ri.studio_root
        if parts == []:
            return value  # .git/**: the git dir checks above
    return None


def glob_area(ctx, cmd, word, studio_infos):
    """studio_area for a wildcard folder: why some folder it may match is (or holds) Studio's folders, or None.
    The pattern is matched from its literal base, in or above each Studio repository (fail closed: `[`, groups and
    `**` may match anything)."""
    value = word.value
    segs, _links = glob_segments(word)
    base_val = word.glob_base or ""
    if ".." in segs:
        segs = ["**"] + segs[len(segs) - segs[::-1].index(".."):]
        base_val = "/" if os.path.isabs(base_val) else ""
    # a folder word (tar -C, unzip -d, a copy's destination) is relative to where the program starts
    start = getattr(cmd, "start_folders", None)
    bases = [None] if os.path.isabs(base_val) else (list(start) if start is not None else run_folders(cmd))
    if not bases:
        return value + " (a wildcard in a folder the guard cannot tell)" if studio_infos else None
    ext = getattr(word, "extglob", False)
    for c in bases:
        r = ctx.where.resolve(base_val or ".", c)
        if r is None or r.abs is None:
            return value
        base_real = os.path.realpath(r.abs) if ctx.fs.exists(r.abs) else (r.real or r.abs)
        for si in studio_infos:
            wt = os.path.realpath(si.worktree)
            fold = ctx.where.case_insensitive(wt)
            inside = protect.rel_parts(base_real, wt, fold)
            if inside is not None:
                prefix, gparts = [], inside + segs
            elif wt.startswith(base_real.rstrip("/") + "/"):
                prefix, gparts = [x for x in os.path.relpath(wt, base_real).split("/") if x], segs
            else:
                continue
            sr = [x for x in si.studio_root.strip("/").split("/") if x]
            for area in ([".claude", "**"], sr + ["**"], [".git", "**"]):
                if protect.glob_may_match(gparts, prefix + area, fold, prefix=True, extglob=ext):
                    return value + " (a wildcard that may match Studio's folders)"
            for root in (prefix + sr, prefix + [".claude", "studio"]):
                for e in range(1, len(root) + 1):
                    if protect.glob_may_match(gparts, root[:e], fold, extglob=ext):
                        return value + " (a wildcard that may match the repository or a folder above Studio's)"
    return None


def _walk(root):
    """Relative entries (folders, files, links — links not followed) of a folder, or None past WALK_MAX."""
    out = []
    for d, dirs, files in os.walk(root, followlinks=False):
        for n in dirs + files:
            p = os.path.join(d, n)
            out.append((os.path.relpath(p, root), os.path.islink(p), n in dirs and not os.path.islink(p)))
            if len(out) > WALK_MAX:
                return None
    return out


def check_bulk(ctx, cmd, prog, argv, words, studio_infos):
    """Returns True when the command is a bulk writer in a Studio context (for the later-writer rule, W4)."""
    weak = weak_extractor(cmd, prog, argv)
    if weak:
        if studio_infos:
            ctx.deny("G-PROT", "%s is not an extractor Studio has checked — in a Studio repository, extract outside "
                               "the repository with tar or unzip and copy the files you need." % weak)
        return bool(studio_infos)
    if prog in EXTRACT_PROGS:
        ext, dirs, w1 = extract_info(prog, argv, words)
    else:
        ext, dirs, w1 = False, [], None
    if prog in EXTRACT_PROGS and (ext or prog != "ditto"):
        if not ext:
            return False
        if w1 and studio_infos:
            ctx.deny("G-PROT", "%s: %s lets archive members leave the folder — not in a Studio repository." % (prog, w1))
            return True
        folders = list(dirs) if dirs else [(None, f) for f in (run_folders(cmd) or [None])]  # [None]: unknown (M1)
        for fw, v in folders:
            why = studio_area(ctx, cmd, v, studio_infos, word=fw)
            if why:
                ctx.deny("G-PROT", BULK_WHY % (prog, why))
                return True
        return bool(studio_infos)
    mode = recursive_copy(prog, argv)
    if mode is None:
        return False
    ops = [w for w in words if w.value is None or not w.value.startswith("-")]  # words: the arguments
    tdir = None
    for i, w in enumerate(words):
        if w.value in ("-t",) and i + 1 < len(words):
            tdir = words[i + 1]
        elif w.value and w.value.startswith("--target-directory="):
            tdir = w
    if tdir is not None:
        dest = tdir.value.split("=", 1)[1] if tdir.value and tdir.value.startswith("--") else tdir.value
        srcs = [w for w in ops if w is not tdir and w.value != dest]
        dword = tdir
    elif len(ops) >= 2:
        dest, srcs, dword = ops[-1].value, ops[:-1], ops[-1]
    else:
        return False
    no_target = prog in ("cp", "gcp") and no_target_dir(argv)
    # the destination rule always (review X2): the walk below is a snapshot and a tool's landing can differ from the
    # model (GNU -T); it only adds checks for other destinations
    for b in [dest] + [x for sw in srcs for x in _copy_bases(ctx, cmd, mode, sw.value, dest, no_target)]:
        why = studio_area(ctx, cmd, b, studio_infos, word=dword)
        if why:
            ctx.deny("G-PROT", BULK_WHY % (prog, why))
            return True
    for sw in srcs:
        sv = sw.value
        bases = _copy_bases(ctx, cmd, mode, sv, dest, no_target)
        entries = None
        if sv is not None and mode != "rsync-relative":
            for a, real, _ri in resolve_all(ctx, cmd, sv):
                if real and ctx.fs.isdir(real):
                    entries = _walk(real)
                elif real and ctx.fs.exists(real):
                    entries = []
                break
        if entries is None:
            continue  # nothing more to know: the destination rule above decided
        for b in bases:
            if b is None:
                continue
            for rel_path, is_link, is_dir in entries:
                target = os.path.join(b, rel_path)
                if is_dir and _real_dir(ctx, cmd, target):
                    continue  # merged into a folder that is already there: its files are judged one by one
                check_target(ctx, cmd, sw, target, "write", studio_infos)  # e.g. a team-shared hook file
    return bool(studio_infos)


def _real_dir(ctx, cmd, value):
    found = [a for a, _r, _ri in resolve_all(ctx, cmd, value) if a]
    return bool(found) and all(os.path.isdir(a) and not os.path.islink(a) for a in found)


def no_target_dir(argv):
    """cp/gcp/install -T / --no-target-directory: the destination is the copy itself, never a folder to copy into."""
    return any(x is not None and (x == "--no-target-directory" or (x.startswith("-") and not x.startswith("--")
                                                                    and "T" in x[1:])) for x in argv[1:])


def _copy_bases(ctx, cmd, mode, src, dest, no_target=False):
    """Where a source's entries land (more than one when the tool's semantics differ — both are judged)."""
    if dest is None:
        return [None]
    if no_target:
        return [dest]
    into = any(ctx.fs.isdir(r) for _a, r, _ri in resolve_all(ctx, cmd, dest) if r)
    if src is None:
        return [dest]
    name = os.path.basename(src.rstrip("/")) or "."
    contents = src.endswith("/.") or src == "." or name == "."
    if mode in ("rsync", "rsync-relative"):
        return [dest] if src.endswith("/") or contents else [os.path.join(dest, name)]
    if mode == "ditto":
        return [dest]
    # cp: GNU copies the folder itself unless `/.`; BSD (macOS) copies the contents for a trailing `/`
    if contents:
        return [dest]
    if not into:
        return [dest]
    out = [os.path.join(dest, name)]
    if src.endswith("/"):
        out.append(dest)
    return out


SHELLS = ("sh", "bash", "zsh", "dash", "ksh")
SHELL_DEPTH = 3


INNER_KINDS = ("shell-c", "eval", "env-S", "script", "source", "stdin-interp", "heredoc-interp", "herestring-interp")
STRING_KINDS = ("shell-c", "eval", "env-S", "heredoc-interp", "herestring-interp")  # text, not script files
RUNNER_WHY = ("%s: the guard cannot read which command this runs in a Studio repository — run the command directly, "
              "one step per call.")
PIECE_SPLIT = re.compile(r"[\s'\"`;|&()<>\0]+")


class Nested(object):
    """A string the shell runs from text (G1 §1.7): its host command, the opaque, and its scan — or `sub` None with
    `why` when the guard cannot read it (then `text`/`skeleton` are what is known of it)."""

    def __init__(self, host, op, cwds, depth):
        self.host, self.op, self.cwds, self.depth = host, op, list(cwds or []), depth
        self.text = op.payload
        self.skeleton = op.skeleton
        self.sub = None
        self.why = None
        self.budget_out = False


def _scan(ctx, *args, **kw):
    """scan_command, noting a `source` / `.` (or eval text that may run one) where the walk stopped: what follows it is
    judged by the 0.0.26 rules only, and the 0.0.26 guard's finish runs for the call (fix20, backstop.decide)."""
    sub = scan_command(*args, **kw)
    if getattr(sub, "sourced", False):
        ctx.sourced = True
    return sub


def nested_scans(ctx, sc, budget, depth=0, tree=None, seen=None, home=None):
    """The literal strings of shell-c, eval, env-S, sourced and shell-run script files and the runners' shell payloads
    (G1 §1.7), scanned to SHELL_DEPTH with the call's budget; one command's string in one folder is scanned once (review
    18: not one text for every command that runs it). Returns (tree, flat):
    tree maps id(scan) to the strings of that scan, flat lists them all. `home`: the $HOME the scan `sc` ran with when
    its own command set it (review 8 M2), inherited by its strings unless their command sets it again."""
    if tree is None:
        tree, seen = {}, {}
        ctx.nested_budget_out = False
    flat = []
    by_id = {c.id: c for c in sc.commands}
    kids = tree.setdefault(id(sc), [])
    for o in sc.opaque:
        if o.kind not in INNER_KINDS:
            continue
        host = by_id.get(o.cmd)
        if host is not None and "exec-template" in (host.ctx or ()):
            continue  # the template of an xargs/find -exec (judged as the template command)
        if o.kind in ("script", "stdin-interp", "heredoc-interp", "herestring-interp") and (
                host is None or os.path.basename(host.prog or "") not in SHELLS):
            continue  # another interpreter's code (python, node, …): the opaque rules (G-OPAQUE) decide
        cwds = run_folders(host) if host is not None else o.cwds  # env -C $D sh -c …: unknown (review 2, M1)
        if not cwds and getattr(o, "at_cwds", None) and "run-unknown" not in (host.flags if host is not None else ()):
            cwds = o.at_cwds  # review 7 M4: an eval-defined function's text replayed from where the eval ran
        nd = Nested(host, o, cwds, depth)
        text = o.payload
        if o.kind == "shell-c" and host is not None and recog.key(recog.base(host.prog or "")) in recog.CSH:
            nd.why = "a csh string (the guard reads zsh only)"  # G1 §1.8: refused; its literal paths are searched
        elif o.kind in ("shell-c", "eval", "env-S") and (o.origin != "literal" or text is None or (
                host is not None and any(w.value is None for w in host.words[1:]))) or \
                o.kind in ("heredoc-interp", "herestring-interp") and o.origin == "dynamic":
            nd.why = "%s with text the guard cannot read" % o.kind
            if nd.skeleton is None and host is not None:
                nd.skeleton = " ".join(w.skeleton for w in host.words[1:])
        elif text is None:
            nd.why = "a script the guard cannot read"
        else:
            if o.kind == "env-S":
                text = re.sub(r"^\s*(-S|--split-string=?)\s*", "", text)
            nd.text = text
            if not cwds or len(cwds) != 1:
                nd.why = "code run from a folder the guard cannot tell"
            elif depth >= SHELL_DEPTH:
                nd.why = "code nested deeper than %d levels" % SHELL_DEPTH
            elif ctx.nested_budget_out:
                nd.why, nd.budget_out = "code the guard ran out of time to read", True
            else:
                inp = getattr(o, "input", None) or None  # the host's input (review 7 M4)
                hh = getattr(host, "home", None) if host is not None else None  # review 8 M2
                nd.home = hh if hh is not None else home
                # review 18 (B18-2): the same string run by the same command in the same folder (its readings) is
                # scanned once; another command running it is judged again, as at HEAD (git's state may have changed
                # in between, and each command spends HEAD's git budget)
                key = (text, cwds[0], tuple(sorted((o.options or {}).items())), model_input_key(inp), nd.home, id(sc),
                       tuple(host.span or ()) if host is not None else o.cmd, host.prog if host is not None else None)
                if key in seen:
                    continue
                sub = _scan(ctx, text, cwds[0], ctx.env, snapshot=ctx.snap, snapshot_notes=(), terms=None, fs=ctx.fs,
                                   budget=budget, options=o.options, stdin=inp, home=nd.home)
                seen[key] = sub
                for c in sub.commands:
                    c.scan_key = id(sub)  # review 18 (Context.current: git probes are per command)
                if sub.status == "ok":
                    nd.sub = sub
                elif sub.reason == "limit:budget":
                    ctx.nested_budget_out = True
                    nd.why, nd.budget_out = "code the guard ran out of time to read", True
                else:
                    nd.why = "code the guard cannot parse"
        kids.append(nd)
        flat.append(nd)
        if nd.sub is not None:
            flat += nested_scans(ctx, nd.sub, budget, depth + 1, tree, seen, getattr(nd, "home", None))[1]
    return tree, flat


def check_shell_strings(ctx, sc, infos, tree):
    """W2 / X1: the path rules (extractions, recursive copies, later writers) for code the shell runs from text:
    literal `sh -c` / `eval` / `env -S` strings, script files run or sourced (`bash f`, `. f`, `bash < f`) and the
    runners' shell payloads (`script -c`, `flock -c`, `watch`, `npx -c`, …), in the host's folder; nested up to
    SHELL_DEPTH (the scans are nested_scans'). In a Studio repository, code the guard cannot read (an unreadable script,
    a non-literal string, a command word from a variable or a substitution, `xargs … sh -c`, a runner it cannot read)
    is refused."""
    for o in sc.opaque:
        if o.kind == "dynamic-command":
            if infos and getattr(o, "why", None):  # a pattern expansion (review 2, M13)
                ctx.deny("G-OPAQUE", "%s — its glob qualifiers may run code the guard cannot check in a Studio "
                                     "repository; write the file names literally, one step per call." % o.why)
            elif infos:
                ctx.deny("G-OPAQUE", "a command word or a shell string built at run time runs code the guard cannot "
                                     "check in a Studio repository — write the command's path literally (or use npx "
                                     "…), one step per call.")
            continue
        if o.kind == "runner":
            if infos:
                ctx.deny("G-OPAQUE", RUNNER_WHY % o.payload)
            continue
        if o.kind == "sudo-shell":
            unknown(ctx, infos, "a root shell (sudo -s/-i, doas -s)")
            continue
        if o.kind == "xargs" and re.match(r"^(\S*/)?(sh|bash|zsh|dash|ksh)\b", o.payload or ""):
            unknown(ctx, infos, "xargs feeding text to a shell")
    for c in sc.commands:
        w0 = c.words[0] if c.words else None
        if w0 is not None and ("$" in (w0.raw or "") or "`" in (w0.raw or "")) and w0.value != "":
            if infos:
                ctx.deny("G-OPAQUE", "a command word taken from a variable or a substitution (%s) runs a program the "
                                     "guard cannot name in a Studio repository — write the command's path literally "
                                     "(or use npx …), one step per call." % w0.raw)
    for nd in tree.get(id(sc), []):
        if nd.sub is None:
            if nd.budget_out:
                if infos:
                    ctx.deny("G-LIMIT", "the shell strings of this command take the guard too long to check in a "
                                        "Studio repository — split it into simple commands.")
            else:
                unknown(ctx, infos, nd.why)
            continue
        outer, ctx.bulk_ids = ctx.bulk_ids, set()  # the inner command ids are their own
        try:
            for c in nd.sub.commands:
                ctx.current = c
                check_out_of_repo(ctx, c)
                check_paths(ctx, c, infos)
            ctx.current = None
            check_shell_strings(ctx, nd.sub, infos, tree)
            inner = ctx.bulk_ids
        finally:
            ctx.bulk_ids = outer
        if inner:
            bulk_then_write(ctx, nd.sub.commands, inner)
            if nd.host is not None:
                ctx.bulk_ids.add(nd.host.id)


def unknown(ctx, infos, what):
    if infos:
        ctx.deny("G-OPAQUE", "%s runs code the guard cannot check in a Studio repository — write the commands directly "
                             "(literal words), one step per call." % what)


# ---- G1 §1.7, §1.7a: Studio repositories named by text the guard cannot read ----

def _piece_value(ctx, v, cwds):
    """~, $HOME and $PWD in a piece of raw or skeleton text, from the hook's environment and the host's folder."""
    home = ctx.env.get("HOME")
    for pre in ("~", "$HOME", "${HOME}"):
        if v == pre or v.startswith(pre + "/"):
            if not home:
                return None
            return home + v[len(pre):]
    for pre in ("$PWD", "${PWD}"):
        if v == pre or v.startswith(pre + "/"):
            if not cwds or len(cwds) != 1:
                return None
            return cwds[0] + v[len(pre):]
    return v


def studio_repos_at(ctx, value, cwds):
    """The Studio repositories `value` (a path, absolute or relative to `cwds`) lies in."""
    out = []
    if not value:
        return out
    bases = [None] if os.path.isabs(value) else list(cwds or [])
    for c in bases:
        r = ctx.where.resolve(value, c)
        if r is None or r.abs is None or r.repo is None:
            continue
        ri = ctx.repos.info(r.repo)
        if ri is not None and ri.studio:
            out.append(ri)
    return out


def _add_infos(infos, ris):
    for ri in ris:
        if ri not in infos:
            infos.append(ri)


def piece_search(ctx, text, cwds, infos, budget=None):
    """piece_search_ under the searches' own file-system budget (_searching)."""
    return _searching(ctx, piece_search_, ctx, text, cwds, infos)


def piece_search_(ctx, text, cwds, infos):
    """G1 §1.7 (M4): the literal pieces of text the guard cannot read — every piece holding `/` and every literal cd
    target — resolved from the host's folder; a Studio repository found joins `infos`. Returns the pieces resolved."""
    if not text:
        return 0
    count = 0
    prev = None
    for t in PIECE_SPLIT.split(text):
        if not t:
            continue
        vals = []
        if "/" in t or prev in ("cd", "pushd", "chdir") or t in ("~",):
            vals.append(t)
        if "=" in t and "/" in t.split("=", 1)[1]:
            vals.append(t.split("=", 1)[1])
        prev = t
        for v in vals:
            v = _piece_value(ctx, v, cwds)
            if v is None:
                continue
            count += 1
            if count > MAX_CANDIDATES:
                return count
            _add_infos(infos, studio_repos_at(ctx, v, cwds))
    return count


def empty_reading(ctx, skeleton, cwds, infos, budget):
    """empty_reading_ under the searches' own file-system budget (_searching)."""
    return _searching(ctx, empty_reading_, ctx, skeleton, cwds, infos, budget)


def empty_reading_(ctx, skeleton, cwds, infos, budget):
    """G1 §1.7 (review 2, D): a non-literal string read once with every unknown expansion empty; the repositories its
    commands name join `infos` (a scan of the text; when it does not parse, piece_search is the fallback)."""
    if not skeleton or "\0" not in skeleton or not cwds or len(cwds) != 1 or getattr(ctx, "nested_budget_out", False):
        return
    sub = _scan(ctx, skeleton.replace("\0", ""), cwds[0], ctx.env, snapshot=ctx.snap, snapshot_notes=(), terms=None,
                       fs=ctx.fs, budget=budget)
    if sub.status == "ok":
        collect_repos(ctx, sub.commands, infos, 0, dynamic=False, quiet=True)


def dynamic_word_search(ctx, c, w, infos):
    """G1 §1.7a (M5): a dynamic path word or cd target — read with its unknown parts empty, and its literal pieces
    (under the searches' own file-system budget)."""
    return _searching(ctx, dynamic_word_search_, ctx, c, w, infos)


def dynamic_word_search_(ctx, c, w, infos):
    cwds = run_folders(c) or c.cwds
    sk = w.skeleton or ""
    n = 0
    empty = _piece_value(ctx, sk.replace("\0", ""), cwds)
    if empty and not re.search(r"\s", empty):  # a word with blanks is no path (a string's pieces are searched below)
        n += 1
        _add_infos(infos, studio_repos_at(ctx, empty, cwds))
    return n + piece_search_(ctx, sk, cwds, infos)


def _searching(ctx, fn, *args):
    """Run a search for Studio repositories in text the guard cannot read with its own file-system budget (the
    searches of one call share MAX_FS_CALLS of their own; the call's budget is not spent). Past it the search stops
    and `ctx.search_cut` is set: in a Studio repository the call is refused (G-LIMIT); outside one the search found
    nothing more and the call is judged as without it (review 2 conformance, MINOR 2)."""
    fs = ctx.fs
    used = getattr(ctx, "search_fs_calls", 0)
    saved = (fs.calls, fs.max_calls)
    fs.calls, fs.max_calls = 0, max(limits.MAX_FS_CALLS - used, 0)
    try:
        return fn(*args) or 0
    except limits.LimitExceeded:
        ctx.search_cut = True
        return 0
    finally:
        ctx.search_fs_calls = used + fs.calls
        fs.calls, fs.max_calls = saved


def runner_files(cmd):
    """(command to judge them as, [(Word, op)]): each unwrapped runner's own file arguments (resolved against the run
    folder in effect for it) and those of a runner that is the program (G1 §1.6)."""
    out = []
    for wr in cmd.wrappers or ():
        if wr.files:
            proxy = copy.copy(cmd)
            proxy.words = [Word.lit(wr.name)]
            proxy.cwds = proxy.run_cwds = list(wr.cwd if wr.cwd is not None else cmd.cwds)
            proxy.flags = set(cmd.flags) - {"run-unknown"}  # this runner's own folder is wr.cwd
            proxy.git = proxy.s2v = proxy.script = proxy.lock = None
            out.append((proxy, wr.files))
    if cmd.files:
        out.append((cmd, cmd.files))
    return out


def collect_repos(ctx, cmds, infos, n, dynamic=True, quiet=False):
    """The Studio repositories commands involve: their folders, run folders, path candidates, redirect targets, the
    runners' file arguments and (dynamic=True) what their dynamic words name (§1.7a). Returns the candidate count, or
    None past MAX_CANDIDATES (denied G-LIMIT)."""
    for c in cmds:
        for d in (c.cwds or []) + (c.run_cwds or []):
            if ctx.fs.exists(d):
                ri = ctx.repos.info(ctx.where.git_repo(d))
                if ri is not None and ri.studio and ri not in infos:
                    infos.append(ri)
        for w in getattr(c, "run_words", ()):  # env -C $D, sudo -D $D (§1.7a, M3)
            if dynamic:
                n += dynamic_word_search(ctx, c, w, infos)
        for w, vals in candidates(c):
            if w.value is None and dynamic:
                n += dynamic_word_search(ctx, c, w, infos)
            for v in vals:
                if not looks_like_path(v, c, ctx):
                    continue
                n += 1
                if n > MAX_CANDIDATES:
                    break
                for a, real, ri in resolve_all(ctx, c, v):
                    if ri is not None and ri.studio and ri not in infos:
                        infos.append(ri)
        for r in c.redirs:
            if r.target is not None and r.target.value:
                for a, real, ri in resolve_all(ctx, c, r.target.value):
                    if ri is not None and ri.studio and ri not in infos:
                        infos.append(ri)
            elif r.target is not None and r.target.value is None and dynamic and r.mode != "herestring":
                n += dynamic_word_search(ctx, c, r.target, infos)
        for wc, files in runner_files(c):
            for w, _op in files:
                n += 1
                for a, real, ri in resolve_all(ctx, wc, w.value):
                    if ri is not None and ri.studio and ri not in infos:
                        infos.append(ri)
        if n > MAX_CANDIDATES:
            if quiet:  # a search (the empty reading): it stops, and decide_bash refuses only in a Studio repository
                ctx.search_cut = True
                return None
            ctx.deny("G-LIMIT", "the command has too many path arguments for the guard — split it.")
            return None
    return n


def bulk_then_write(ctx, commands, bulk_ids):
    """W4: after an extraction or a recursive copy in a Studio repository, no other writing command in the same call
    (what the bulk writer put down could be moved into Studio's folders before the guard sees it)."""
    seen = []
    for c in commands:
        if seen and is_writer(c) and any(not other_reading(b, c) for b in seen):
            ctx.deny("G-PROT", "%s runs after an archive extraction or a recursive copy in the same call — run the "
                               "extraction or copy alone, then run the next step in a separate call."
                     % (c.prog or "a command"))
            return
        if c.id in bulk_ids:
            seen.append(c)


def other_reading(a, b):
    """review 12 conf M-1: two readings of one command with a word of several known values (walk.choice_readings):
    zsh runs one of them, so one is not "earlier" than the other."""
    aa, ba = a.alt or {}, b.alt or {}
    if a.span == b.span and tuple(a.span or ()) != (0, 0) and a.prog == b.prog and \
            ("lost-folder" in (a.ctx or ()) or "lost-folder" in (b.ctx or ())):
        return True  # review 16: the same command judged in another folder it may run in (walk: lost folders)
    return aa.get("group") == "choice" == ba.get("group") and a.span == b.span and tuple(a.span or ()) != (0, 0) \
        and aa.get("index") != ba.get("index")


def is_writer(c):
    prog = c.prog or ""
    if any(r.target is not None and r.mode in ("write", "append", "rw") for r in c.redirs):
        return True
    if any(op in ("write", "write-dir") for _wc, files in runner_files(c) for _w, op in files):
        return True
    if is_sed(c):
        return sed_shape(c)[0] != "read"
    if prog in protect.READ_ALLOW and prog not in ("find", "bfs"):
        return False
    if prog in ("find", "bfs"):
        return any(w.value in protect.FIND_WRITE for w in c.words if w.value)
    if prog == "git" and c.git is not None and c.git.sub in protect.GIT_READ:
        return False
    return True


# ---- sed: an allowlist of shapes (fix-0025-plan §1, pilot-2 P11) ----
# The program is sed when walk's unwrapped word (env, command, nohup, …) is sed or gsed, compared as NFC + casefold of
# the basename (APFS is case-insensitive). Package runners (npx sed, …) are not sed: they stay writers.

SED_WHY = ("%s: sed with this script or these options cannot be checked in a Studio repository — Studio checks only "
           "plain prints (sed -n 1,80p FILE) and s/// edits with -i '' or -i.bak.")
SED_OUT_WHY = ("sed with this script or these options cannot be checked, and it names %s, which is in a Studio "
               "repository or is Studio's per-user files or the machine lock.")


def is_sed(cmd):
    return cmd.prog_key in sedshape.NAMES


def sed_trusted(cmd):
    """Whether the program is the system's sed: an absolute path in a system bin folder (whatever PATH is), or the
    bare name with PATH untouched. Any other sed (a copy in /tmp, PATH=… sed, env -i sed) is never shaped: other."""
    if any(w.name in ("busybox", "toybox", "xcrun") for w in cmd.wrappers):
        return False  # G1 §1.5: their sed is not the system's (shapes were measured on GNU and BSD only)
    w0 = cmd.words[0].value
    if "/" in w0:
        # no `..`, `.` or `//`: /usr/bin/../../tmp/sed is not in /usr/bin
        return os.path.isabs(w0) and os.path.normpath(w0) == w0 and recog.trusted_bin_dir(w0)  # G1 §4
    env = cmd.env
    return not (env.cleared or env.unknown or "PATH" in env.set or "PATH" in env.unset
                or "path-modified" in (cmd.flags or ()))


def sed_exec_by(cmd):
    """None, "xargs" (an xargs template: walk appends the input word) or "find" (a find -exec template)."""
    if "exec-template" not in (cmd.ctx or ()):
        return None
    if any("xargs-input" in (w.dyn or ()) for w in cmd.words):
        return "xargs"
    return "find"


def sed_shape(cmd):
    if not sed_trusted(cmd):
        return "other", "a sed that may not be the system's (its path, or PATH changed)"
    return sedshape.classify(cmd.words[1:], sed_exec_by(cmd))


def check_sed(ctx, cmd, studio_infos):
    """True when the shape decided: read (the files are only read; out-of-repo reads are check_out_of_repo's), edit
    (the files, backups and the script word are writes), other in a Studio repository (refused). False for other
    outside one: today's writer rules, and decide_bash resolves its path pieces."""
    shape, det = sed_shape(cmd)
    if shape == "read":
        return True
    if shape == "edit":
        for w, v in sedshape.targets(det):
            check_target(ctx, cmd, w, v, "write", studio_infos)
        return True
    if studio_infos:
        ctx.deny("G-OPAQUE", SED_WHY % det, suffix=messages.NONSTOP)
        return True
    return False


def parallel_runs_sed(cmd):
    for w in cmd.words[1:]:
        if w.value in (":::", "::::", ":::+", "::::+"):
            break
        first = (w.value or "").split()
        if first and recog.key(recog.base(first[0])) in sedshape.NAMES:
            return True
    return False


def check_sed_outside(ctx, sc, n):
    """An unchecked sed outside a Studio repository: no term matching (`/` is sed's delimiter); its path pieces are
    resolved instead, and one that lands in a Studio repository or on Studio's per-user files is refused. `n` path
    candidates were counted already (MAX_CANDIDATES)."""
    for c in sc.commands:
        if not is_sed(c) or sed_shape(c)[0] != "other":
            continue
        ctx.current = c
        hit = None
        for v in sedshape.pieces(c.words[1:]):
            n += 1
            if n > MAX_CANDIDATES:
                ctx.current = None
                ctx.deny("G-LIMIT", "the command has too many path arguments for the guard — split it.")
                return
            for a, real, ri in resolve_all(ctx, c, v):
                if (ri is not None and ri.studio) or out_hit(ctx, real, "write") is not None:
                    hit = v
                    break
            if hit:
                break
        if hit:
            ctx.deny("G-OPAQUE", SED_OUT_WHY % hit, suffix=messages.NONSTOP)
    ctx.current = None


def hard_link_copy(argv):
    return any(x is not None and (x == "--link" or (x.startswith("-") and not x.startswith("--") and "l" in x[1:]))
               for x in argv[1:])


def tilde_rest(cmd, word):
    """The path after a leading `~` when this call wrote $HOME with a value the guard cannot read (Cmd.tilde_unknown;
    review 7 M5) — "." for the folder itself — or None."""
    kinds = getattr(cmd, "tilde_unknown", None)
    sk = word.skeleton or ""
    if not kinds or len(word.dyn or ()) != 1 or word.dyn[0] not in kinds or not sk.startswith("\0") or \
            sk.count("\0") != 1 or (len(sk) > 1 and sk[1] != "/"):
        return None
    return sk[1:].lstrip("/") or "."


PWD_REF_RE = re.compile(r"^(\$PWD|\$\{PWD\}|~\+|\$\(\s*pwd(\s+-[LP])?\s*\)|`\s*pwd(\s+-[LP])?\s*`|"
                        r"\$\(\s*git\s+rev-parse\s+--show-toplevel\s*\))(?![A-Za-z0-9_])")


def pwd_rest(cmd, word):
    """review 10 B1: the path after a leading `$PWD`, `~+`, `$(pwd)` or `$(git rev-parse --show-toplevel)` when the
    folder the command runs in is unknown — "." for the folder itself — or None."""
    if cmd.cwds:
        return None
    sk = word.skeleton or ""
    raw = re.sub(r"[\"']", "", word.raw or "")
    if not sk.startswith("\0") or sk.count("\0") != 1 or (len(sk) > 1 and sk[1] != "/") or not PWD_REF_RE.match(raw):
        return None
    return sk[1:].lstrip("/") or "."


def add_candidate(ctx, item):
    """An allow candidate (a Studio script call alone in the Bash call). review 10: a copy of a command judged in a
    known folder the shell may still be in is not a second call."""
    if "lost-folder" in (getattr(item[0], "ctx", None) or ()):
        return
    ctx.candidates.append(item)


def cand_word(word, v):
    """review 9: a word standing for one candidate value of a dynamic word (every wildcard character a wildcard)."""
    w = copy.copy(word)
    w.value, w.dynamic, w.dyn, w.skeleton, w.wild, w.alt, w.cand_values, w.cand_loose = v, False, [], v, None, None, \
        (), ()
    i = min([v.find(ch) for ch in "*?[<" if ch in v] or [-1])
    w.glob = i >= 0
    w.glob_base = (v[:i][:v[:i].rfind("/") + 1] if "/" in v[:i] else "") if i >= 0 else None
    return w


def loose_cands(word, infos):
    """review 9: the words of a command whose output a value is (`X=$(ls studio)`) that name a protected thing or may
    name a repository (an absolute path): judged as values the word may have."""
    names = protect.UNKNOWN_FOLDER_NAMES | protect.TAIL_NAMES | {ri.studio_root for ri in infos or ()}
    out = []
    for v in getattr(word, "cand_loose", ()):
        segs = [x for x in v.split("/") if x not in ("", ".", "..")]
        if segs and (v.startswith(("/", "~")) or any(x in names for x in segs)):
            out.append(v)
    return out


def check_target(ctx, cmd, word, value, op, studio_infos, s2v=False):
    if value is None and (getattr(word, "cand_values", None) or getattr(word, "cand_loose", None)):
        # review 9: a value the guard does not carry (an array, read, print -v, $(print …), a function's global, one
        # of several folders): each value it may have is judged
        n = len(ctx.denies)
        for v in list(word.cand_values) + [x for x in loose_cands(word, studio_infos) if x not in word.cand_values]:
            check_target(ctx, cmd, cand_word(word, v), v, op, studio_infos, s2v)
            if len(ctx.denies) > n:
                return
    if value is None and studio_infos and "tilde-dir" in (word.dyn or ()):
        # review 14 (B14-6): `~[name]` — zsh asks zsh_directory_name / zsh_directory_name_functions (a sourced file,
        # an eval or this call may define them); the guard does not run them
        ctx.deny("G-OPAQUE", "%s names a dynamic named directory (%s) whose folder zsh gets from a "
                             "zsh_directory_name function the guard does not run — write the folder's path."
                 % (cmd.prog or "the command", word.raw))
        return
    if value is None:
        rest = tilde_rest(cmd, word)
        if rest is not None and studio_infos:
            # review 7 M5: `~/<rest>` after this call wrote $HOME with a value the guard cannot read: <rest> under a
            # folder the guard cannot tell (the text the value came from was searched for Studio repositories)
            for sri in studio_infos:
                judge_unknown_folder(ctx, cmd, rest, sri, op, s2v)
            return
        rest = pwd_rest(cmd, word)
        if rest is not None and studio_infos:
            # review 10 B1: `$PWD/<rest>`, `~+/<rest>`, `$(pwd)/<rest>`, `$(git rev-parse --show-toplevel)/<rest>` in
            # a folder the guard cannot tell: <rest> under that folder, as a relative path is judged
            for sri in studio_infos:
                judge_unknown_folder(ctx, cmd, rest, sri, op, s2v)
            return
        if word.dynamic and studio_infos and protect.tail_hits(word.skeleton or ""):
            ctx.deny("G-PROT" if op == "write" else "G-DEL",
                     "%s %s a path the guard cannot read (%s) that ends in a protected name."
                     % (cmd.prog or "the command", "writes" if op == "write" else "deletes", word.raw))
        return
    glob = word.glob and word.glob_base is not None and value == word.value
    if glob:
        judge_glob_target(ctx, cmd, word, op, studio_infos)  # G1 §2 (folders the guard can tell)
    unknown_done = False
    for a, real, ri in resolve_all(ctx, cmd, value):
        if a is None:
            # G1 §1.7a: the folder is unknown or overflowed — `**/<rel>` in each Studio repository
            for sri in studio_infos:
                judge_unknown_folder(ctx, cmd, value, sri, op, s2v, word=word)
            if not unknown_done and not os.path.isabs(value):
                unknown_done = True
                judge_glob_folders(ctx, cmd, value, op, studio_infos)
            continue
        if op == "link-source":
            if ri is not None and hookfiles.hit(ri, real, "delete", ctx.where.case_insensitive(real)):
                ctx.deny("G-PROT", "%s links %s, which holds %s — writing through the link would change it."
                         % (cmd.prog or "the command", value, HOOK_WHY))
                continue
            if ri is not None and ri.studio:
                parts, fold = rel(ctx, ri, real)
                if parts is not None:
                    judge_parts(ctx, cmd, word, value, parts, ri, fold, op, s2v, real)
            continue
        hit = out_hit(ctx, real, "delete" if op.startswith("delete") else "write")
        if hit:
            ctx.deny("G-OUT", "%s %s %s (Studio's per-user files or the machine lock) — only Studio's scripts change "
                              "it. If a stale lock blocks you, run \"python3 .claude/studio/scripts/lock.py status\" "
                              "and ask the user." % (cmd.prog or "the command",
                                                    "deletes" if op.startswith("delete") else "writes", value))
            continue
        if op != "link-source" and hook_file_denied(ctx, cmd, ri, real, value, op):
            continue
        if studio_infos and not op.startswith("delete") and user_config(ctx, real):
            ctx.deny("G-HOOKOFF", "%s writes %s (git's or ssh's own settings, which can run commands) in a Studio "
                                  "repository; %s" % (cmd.prog or "the command", value, commitrule.HOOKOFF_TAIL))
            continue
        if glob or ri is None or not ri.studio:
            continue
        ctx.touch(ri)
        parts, fold = rel(ctx, ri, real)
        if parts is None:
            continue
        judge_parts(ctx, cmd, word, value, parts, ri, fold, op, s2v, real)


def value_segments(value, word):
    """`value` split at `/` (no empty or `.` segments). With the word's quoting known (Word.wild), each segment is a
    protect.Seg: its quoted `(`, `[`, `*`, `?` are letters (review 4 conf M-2); else plain strings (every one a
    wildcard)."""
    wild = getattr(word, "wild", None) if word is not None else None
    if wild is not None and word.value is not None and value != word.value:
        if value.startswith(word.value + "/"):
            wild = set(wild) | set(range(len(word.value), len(value)))  # into a folder: the source's name follows
        else:
            off = word.value.find(value)
            wild = None if off < 0 or word.value.count(value) != 1 else {i - off for i in wild}
    if word is not None and getattr(word, "glob", False):
        out = protect.pattern_segments(value, wild)  # not split inside `[…]` (`[s/]tudio`; review 7 B1)
    else:
        out, pos = [], 0
        for part in value.split("/"):
            if part not in ("", "."):
                out.append(part if wild is None else protect.Seg(part, {i - pos for i in wild
                                                                       if pos <= i < pos + len(part)}))
            pos += len(part) + 1
    if word is not None and getattr(word, "glob", False) and getattr(word, "extglob", False):
        out = protect.ext_cut(out, True)  # `x~*/y`: what `x` matches (review 6 conf m-1)
    if word is not None and getattr(word, "glob", False) and getattr(word, "globstarshort", False):
        out = star_short(out)
    return out


def star_short(segs):
    """review 8 M3: under GLOB_STAR_SHORT (on, or options the guard cannot tell) zsh reads a segment `**x` / `***x` as
    `**/*x` / `***/*x` (any depth)."""
    out = []
    for x in segs:
        wild = getattr(x, "wild", None)
        k = 3 if x.startswith("***") else 2 if x.startswith("**") else 0
        if k and len(x) > k and all(wild is None or i in wild for i in range(k)):
            out.append("**")
            rest = x[k - 1:]  # `*` + the rest
            out.append(protect.Seg(rest, {i - (k - 1) for i in wild if i >= k - 1}) if wild is not None else rest)
        else:
            out.append(x)
    return out


def judge_unknown_folder(ctx, cmd, value, ri, op, s2v, word=None):
    """A relative write, delete or extraction folder under a folder the guard cannot tell (a dynamic or overflowed
    `cd`, a `cd` in a function, a wildcard folder): judged as `**/<rel>` — denied when <rel> names a protected thing
    literally (or by a wildcard that may be one) and some protected path may match (G1 §1.7a). `.`, `..` and a
    wildcard may stand for the unknown folder itself or a folder above it, so a recursive delete or an extraction
    there may be the studio root or an ancestor (review 2, B-1)."""
    segs = value_segments(value, word)
    if ".." in segs:
        segs = segs[len(segs) - segs[::-1].index(".."):]  # `**` stands for every folder above anyway
    o = "delete" if op == "delete" else "delete-file" if op == "delete-file" else (
        "write-dir" if op == "write-dir" else "write")
    fold = ctx.where.case_insensitive(ri.worktree)
    if o == "write" and effective(cmd)[0] == "ln" and segs:
        # review 11 (a HEAD regression after `eval`, `source` or a hook): a link whose path names one of Studio's
        # folders may be one under the studio root, which Studio does not follow (judge_parts) — as in a known folder
        names = {n.casefold() for n in protect.UNKNOWN_FOLDER_NAMES | {os.path.basename(ri.studio_root.rstrip("/"))}}
        if any(x.casefold() in names for x in segs):
            ctx.deny("G-PROT", "ln %s in a folder the guard cannot tell may make a link under %s/ (or its own "
                               "folders), which Studio does not follow — cd to a literal folder first, in a separate "
                               "call." % (value, ri.studio_root))
            return
    if not segs:
        tid = "P-ANC" if o in ("delete", "write-dir") else None
    else:
        # `^x`, `*~x`, `l#ocal` while EXTENDED_GLOB may be on: wildcards too (review 5)
        ext = word is not None and bool(getattr(word, "glob", False)) and bool(getattr(word, "extglob", False))
        tid = protect.unknown_folder_hit(segs, ri.studio_root, fold, o, skip=protect.S2V_OWNED if s2v else (),
                                         extglob=ext)
    if tid is None:
        return
    what = "be the repository root or an ancestor of Studio's folders" if tid == "P-ANC" else \
        "hold %s data" % protect.BY_ID[tid][2]
    if o.startswith("delete"):
        ctx.deny("G-DEL", "%s deletes %s in a folder the guard cannot tell, which may %s that git cannot restore — cd "
                          "to a literal folder first, in a separate call." % (cmd.prog or "the command", value, what))
    elif tid == "P-ANC" or o == "write-dir":
        ctx.deny("G-PROT", "%s extracts or copies into %s in a folder the guard cannot tell, which may %s — cd to a "
                           "literal folder first, in a separate call." % (cmd.prog or "the command", value, what))
    else:
        ctx.deny("G-PROT", "%s writes %s in a folder the guard cannot tell, which may be a protected Studio file (%s) "
                           "— cd to a literal folder first, in a separate call." % (cmd.prog or "the command", value,
                                                                                   protect.BY_ID[tid][2]))


def judge_glob_folders(ctx, cmd, value, op, studio_infos):
    """A relative path under a folder a wildcard names (`cd stu?io`, `env -C studio/vid*`, review 2 M12): judged as
    the pattern `<folder pattern>/<path>` too (the unknown-folder rule above judges `**/<path>`)."""
    pats = list(getattr(cmd, "glob_folders", None) or [])
    pats += [(tuple(cmd.cwds or ()), w.value) for w in getattr(cmd, "run_words", ()) if w.value is not None and w.glob]
    for bases, pat in pats:
        if not bases and not os.path.isabs(pat):
            continue
        gw = as_glob(Word(pat, pat, glob=True), os.path.join(pat, value))
        if gw is None:
            continue
        proxy = copy.copy(cmd)
        proxy.run_cwds, proxy.flags = list(bases), set(cmd.flags) - {"run-unknown"}
        judge_glob_target(ctx, proxy, gw, op, studio_infos)


HOOK_WHY = "Studio's pre-commit hook (wiring) — only \"python3 .claude/studio/scripts/hooks.py install\" changes it"


def hook_file_denied(ctx, cmd, ri, real, value, op):
    """P-HOOK for Bash: any write, delete or move of an installed hook file (m0e-plan §10)."""
    h = hookfiles.hit(ri, real, "delete" if op.startswith("delete") else "write",
                      real is not None and ctx.where.case_insensitive(real))
    if not h:
        return False
    if h[1] == "gitconfig":
        ctx.deny("G-HOOKOFF", "%s %s %s (git's settings of a Studio repository: hooks and aliases live there) — "
                              "change settings with git config; %s" % (cmd.prog or "the command", "deletes" if
                                                                      op.startswith("delete") else "writes", value,
                                                                      commitrule.HOOKOFF_TAIL))
        return True
    ctx.deny("G-PROT", "%s %s %s, %s." % (cmd.prog or "the command", "deletes" if op.startswith("delete") else "writes",
                                          value, HOOK_WHY))
    return True


def judge_parts(ctx, cmd, word, value, parts, ri, fold, op, s2v, real):
    sr = ri.studio_root
    if op == "link-source":
        tid = protect.classify(parts, sr, fold)
        if not tid and real is not None and ctx.fs.isdir(real):
            tid = protect.delete_hits(parts, sr, fold, is_dir=True)  # a folder that holds protected files (cp -al)
        if tid:
            if tid == "P-ANC":
                what = "which holds Studio's folders"
            elif real is not None and ctx.fs.isdir(real):
                what = "which holds protected Studio files (%s)" % protect.BY_ID[tid][2]
            else:
                what = "a protected Studio file (%s)" % protect.BY_ID[tid][2]
            ctx.deny("G-PROT", "%s links %s, %s — writing through the link would change it."
                     % (cmd.prog or "ln", value, what))
        return
    if op == "write-dir":
        for tid, pats, cls, who in protect.TABLE:
            if tid == "P-LOCAL":
                continue
            if any(protect._match(parts, protect._expand(p, sr), fold) or
                   protect._may_contain(parts, protect._expand(p, sr), fold) for p in pats):
                ctx.deny("G-PROT", "%s extracts into %s, which may overwrite %s files — only %s may change them."
                         % (cmd.prog, value, cls, who))
                return
        return
    if op.startswith("delete"):
        is_dir = op == "delete" and (real is None or ctx.fs.isdir(real))
        tid = protect.delete_hits(parts, sr, fold, is_dir=is_dir)
        if tid:
            what = "the repository root or an ancestor of Studio's folders" if tid == "P-ANC" else \
                protect.BY_ID[tid][2] + " data"
            ctx.deny("G-DEL", "%s deletes %s, which holds %s that git cannot restore." % (cmd.prog, value, what))
        return
    if op == "write" and effective(cmd)[0] in protect.CREATORS and protect.local_anchor(parts, sr, fold):
        # a link, a moved or a copied tree in place of the machine-local folder would put files there that no
        # Studio script wrote (machine.json, pending approvals) — only a real folder (mkdir) (m1-plan §3.1 review U1)
        ctx.deny("G-PROT", "%s creates %s, Studio's machine-local folder (or a folder above it) — it may only be a "
                           "real folder made with mkdir; ask the user." % (cmd.prog or "the command", value))
        return
    if op == "write" and effective(cmd)[0] == "ln" and protect.may_hold_protected(parts, sr, fold):
        ctx.deny("G-PROT", "ln %s: Studio does not follow links under %s/ (or its own folders); reference the file "
                           "by its relative path (assets.json script_src) or copy it." % (value, sr))
        return
    tid = protect.classify(parts, sr, fold)
    if tid is None:
        return
    if s2v and tid in protect.S2V_OWNED:
        return
    _id, _p, cls, who = protect.BY_ID[tid]
    hint = ""
    if tid == "P-CHAR":
        hint = " Write character.yaml.draft instead; a person moves it."
    elif tid == "P-CRED":
        hint = " Write CREDITS.draft.yaml instead."
    elif tid == "P-STATE":
        hint = " Use state.py."
    ctx.deny("G-PROT", "%s writes %s (%s) — only %s may change it.%s" % (cmd.prog or "the command", value, cls, who, hint))


def user_config(ctx, real):
    """git's and ssh's user settings (G1 §1.9): ~/.gitconfig, $XDG_CONFIG_HOME/git/config, ~/.ssh/config."""
    if real is None:
        return False
    home = ctx.env.get("HOME") or os.path.expanduser("~")
    xdg = ctx.env.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
    fold = ctx.where.case_insensitive(real)  # ~/.GitConfig is ~/.gitconfig on a volume that ignores case (M14)
    k = (lambda x: x.casefold()) if fold else (lambda x: x)
    for p in (os.path.join(home, ".gitconfig"), os.path.join(xdg, "git", "config"),
              os.path.join(home, ".config", "git", "config"), os.path.join(home, ".ssh", "config")):
        if k(real) in (k(p), k(ctx._real(p))):
            return True
    return False


GLOB_WHY = "%s %s %s, which may match %s — write the path without wildcards."


def glob_segments(word):
    """The pattern after the literal folder part, split on `/` (`***` is `**`), and whether it has `***`."""
    off = len(word.glob_base or "")
    rest = (word.value or "")[off:]
    wild = getattr(word, "wild", None)
    if wild is not None:
        wild = {i - off for i in wild if i >= off}
    # split as zsh does: not inside `[…]` (`[s/]tudio`), quoting kept (review 7 B1)
    segs = protect.ext_cut(protect.pattern_segments(rest, wild), getattr(word, "extglob", False))
    links = "***" in segs or (getattr(word, "globstarshort", False) and any(x.startswith("***") for x in segs))
    if getattr(word, "globstarshort", False):
        segs = star_short(segs)
    return ["**" if x in ("**", "***") else x for x in segs], links


def judge_glob_target(ctx, cmd, word, op, studio_infos):
    """G1 §2: a glob word is denied when some path it can match would be denied as a literal path. Folders the guard
    cannot tell are the unknown-folder rule's (check_target)."""
    base_val = word.glob_base or ""
    segs, links = glob_segments(word)
    if ".." in segs:
        # a `..` after a wildcard: any folder of the repository (the unknown-folder rule's reading)
        segs = ["**"] + segs[len(segs) - segs[::-1].index(".."):]
        base_val = "/" if os.path.isabs(base_val) else ""
    bases = [None] if os.path.isabs(base_val) else run_folders(cmd)
    for c in bases:
        r = ctx.where.resolve(base_val or ".", c)
        if r is None or r.abs is None:
            continue
        base_real = r.real or r.abs
        ri = ctx.repos.info(r.repo) if r.repo is not None else None
        if ri is not None and ri.studio:
            fold = ctx.where.case_insensitive(ri.worktree)
            ctx.touch(ri)
            bparts = protect.rel_parts(base_real, ri.worktree, fold)
            if bparts is None:
                continue
            if "**" in segs and not links and getattr(word, "glob_walk", False) and \
                    not getattr(ctx, "earlier_write", True):
                found = glob_walk(ctx, base_real, segs, fold, getattr(word, "extglob", False))
                if found is not None:
                    for p in found:
                        check_target(ctx, cmd, Word.lit(p), p, op, studio_infos)
                    continue
            judge_glob_static(ctx, cmd, word, ri, bparts + segs, fold, op)
        else:
            fold = ctx.where.case_insensitive(base_real) if ctx.fs.exists(base_real) else False
            glob_outside(ctx, cmd, word, base_real, segs, fold, op, studio_infos)


def listed_globs(ctx, cmd, words):
    """`words` with each `**` glob that zsh runs with its existing matches (G1 §2: NOMATCH on, no GLOB_DOTS, nothing
    before it in the call may write) replaced by those matches, when its folder part lies in one Studio repository
    and the listing ends within WALK_MAX; any other word stays (judged by judge_glob_target)."""
    out = []
    for w in words:
        found = None
        if w.glob and w.glob_base is not None and w.value is not None and getattr(w, "glob_walk", False) and \
                not getattr(ctx, "earlier_write", True):
            segs, links = glob_segments(w)
            bases = [None] if os.path.isabs(w.glob_base) else run_folders(cmd)
            if "**" in segs and ".." not in segs and not links and len(bases) == 1:
                r = ctx.where.resolve(w.glob_base or ".", bases[0])
                ri = ctx.repos.info(r.repo) if r is not None and r.abs is not None and r.repo is not None else None
                if ri is not None and ri.studio:
                    found = glob_walk(ctx, r.real or r.abs, segs, ctx.where.case_insensitive(ri.worktree),
                                      getattr(w, "extglob", False))
        if found:
            base = r.real or r.abs
            out.extend(Word.lit(w.glob_base + os.path.relpath(p, base)) for p in found)
        else:
            out.append(w)
    return out


def glob_hook_hit(ctx, ri, gparts, fold, op, ext):
    """review 6 M12 (plan §2 for P-HOOK): an installed Studio hook file (hookfiles.items, active) that the pattern
    `gparts` may match — or, for a recursive delete, a folder above it; for Studio's runner folder, a path in it.
    Returns (path, kind) or None."""
    hop = "delete" if op.startswith("delete") else "write"
    wt = os.path.realpath(ri.worktree)
    for path, kind in hookfiles.items(ri):
        parts = protect.rel_parts(path, wt, fold)
        if parts is None:
            parts = protect.rel_parts(path, ri.worktree, fold)
        if not parts or not hookfiles._active(path, kind, ri, hop):
            continue
        pat = parts + ["**"] if kind == "dir" and hop == "write" else parts
        if protect.glob_may_match(gparts, pat, fold, prefix=op in ("delete", "write-dir"), extglob=ext):
            return path, kind
    return None


def judge_glob_static(ctx, cmd, word, ri, gparts, fold, op):
    """The two-pattern rule: `gparts` (repository-relative, the base resolved) against every protected pattern."""
    sr = ri.studio_root
    ext = getattr(word, "extglob", False)
    prog = cmd.prog or "the command"
    if op == "delete":
        for root in (protect._expand(sr, sr), [".claude", "studio"]):
            for e in range(1, len(root) + 1):
                if protect.glob_may_match(gparts, root[:e], fold, extglob=ext):
                    ctx.deny("G-DEL", GLOB_WHY % (prog, "deletes", word.value,
                                                  "the repository root or an ancestor of Studio's folders"))
                    return
    hh = glob_hook_hit(ctx, ri, gparts, fold, op, ext)
    if hh:
        verb = "deletes" if op.startswith("delete") else "links" if op == "link-source" else "writes"
        if hh[1] == "gitconfig":
            ctx.deny("G-HOOKOFF", GLOB_WHY % (prog, verb, word.value, "git's settings of a Studio repository (hooks and "
                                                                     "aliases live there)"))
        else:
            ctx.deny("G-PROT", GLOB_WHY % (prog, verb, word.value, HOOK_WHY))
        return
    order = [t for t in protect.TABLE if t[0] == "P-LOCAL"] + [t for t in protect.TABLE if t[0] != "P-LOCAL"]
    if op == "write" and effective(cmd)[0] == "ln":
        # a link in place of a folder that may hold protected files (`ln -sfn /tmp/x s*/videos/v/work`: review 2,
        # B-2), as judge_parts does for a literal path
        if any(protect.glob_may_match(gparts, protect._expand(p, sr), fold, prefix=True, extglob=ext)
               for _t, pats, _c, _w in protect.TABLE for p in pats):
            ctx.deny("G-PROT", "ln %s: Studio does not follow links under %s/ (or its own folders), and the wildcard "
                               "may match one — reference the file by its relative path (assets.json script_src) or "
                               "copy it." % (word.value, sr))
            return
    for tid, pats, cls, who in order:
        if tid == "P-LOCAL" and not op.startswith("delete"):
            continue
        prefix = op in ("delete", "write-dir")
        for p in pats:
            if protect.glob_may_match(gparts, protect._expand(p, sr), fold, prefix=prefix, extglob=ext):
                if op.startswith("delete"):
                    ctx.deny("G-DEL", GLOB_WHY % (prog, "deletes", word.value, "%s data that git cannot restore"
                                                  % cls))
                else:
                    ctx.deny("G-PROT", GLOB_WHY % (prog, "extracts into" if op == "write-dir" else
                                                   "links" if op == "link-source" else "writes", word.value,
                                                   "protected Studio files (%s) — only %s may change them"
                                                   % (cls, who)))
                return


def _glob_literal(seg, extglob):
    return not any(ch in seg for ch in "*?[(|<") and not (extglob and any(ch in seg for ch in "^~#"))


def glob_walk(ctx, base, segs, fold, extglob):
    """Existing paths under `base` that the pattern `segs` matches as zsh would (dot names only by a literal dot,
    no links followed), or None past WALK_MAX listed entries, at a folder that cannot be listed, or past the walks'
    own file-system budget (C-M1: the walks of one call share MAX_FS_CALLS of their own; the call's budget is not
    spent, and the static rule decides past it)."""
    key = (base, tuple(segs), fold, extglob)
    cache = ctx.__dict__.setdefault("glob_walks", {})
    if key in cache:
        return cache[key]
    fs = ctx.fs
    used = getattr(ctx, "glob_fs_calls", 0)
    saved = (fs.calls, fs.max_calls)
    fs.calls, fs.max_calls = 0, max(limits.MAX_FS_CALLS - used, 0)
    try:
        found = _glob_walk(ctx, base, segs, fold, extglob)
    except limits.LimitExceeded:
        found = None
    finally:
        ctx.glob_fs_calls = used + fs.calls
        fs.calls, fs.max_calls = saved
    cache[key] = found
    return found


def _listdir(ctx, path):
    """A folder's names, listed once per call for every glob walk."""
    names = ctx.__dict__.setdefault("glob_names", {})
    if path not in names:
        names[path] = ctx.fs.listdir(path)
    return names[path]


def _glob_walk(ctx, base, segs, fold, extglob):
    out = []
    listed = set()  # each folder's entries count once toward WALK_MAX

    def names_of(path):
        names = _listdir(ctx, path)
        if names is not None and path not in listed:
            listed.add(path)
            ctx_count[0] += len(names)
            if ctx_count[0] > WALK_MAX:
                raise _WalkFull()
        return names
    ctx_count = [0]

    def rec(path, i):
        if i == len(segs):
            out.append(path)
            return True
        s = segs[i]
        if s == "**":
            if not rec(path, i + 1):
                return False
            names = names_of(path)
            if names is None:
                return not ctx.fs.exists(path)
            for n in sorted(names):
                p = os.path.join(path, n)
                if n.startswith(".") or os.path.islink(p) or not ctx.fs.isdir(p):
                    continue
                if not rec(p, i):
                    return False
            return True
        if _glob_literal(s, extglob):
            p = os.path.join(path, s)
            if os.path.lexists(p) and (i + 1 == len(segs) or ctx.fs.isdir(p)):
                return rec(p, i + 1)
            return True
        names = names_of(path)
        if names is None:
            return not ctx.fs.exists(path)
        for n in sorted(names):
            if n.startswith(".") and not s.startswith("."):
                continue
            if not protect._seg_ok(s, n, fold, extglob):
                continue
            p = os.path.join(path, n)
            if i + 1 < len(segs) and not ctx.fs.isdir(p):
                continue
            if not rec(p, i + 1):
                return False
        return True
    try:
        return out if rec(base, 0) else None
    except _WalkFull:
        return None


class _WalkFull(Exception):
    pass


def glob_outside(ctx, cmd, word, base, segs, fold, op, studio_infos):
    """A glob whose literal folder part lies outside every Studio repository: its folders are listed one segment at
    a time; a folder in a Studio repository continues with the two-pattern rule from there (G1 §2)."""
    ext = getattr(word, "extglob", False)
    roots = {".claude", "studio"} | {ri.studio_root for ri in studio_infos} | set(protect.TAIL_NAMES)

    def risky(rest):
        return any(x.casefold() in {r.casefold() for r in roots} for x in rest if _glob_literal(x, ext))

    count = 0
    frontier = [(base, 0)]
    while frontier:
        path, i = frontier.pop()
        if i > 0 and ctx.fs.exists(path):
            ri = ctx.repos.info(ctx.where.git_repo(path))
            if ri is not None and ri.studio:
                real = ctx.fs.realpath(path)
                bparts = protect.rel_parts(real, ri.worktree, ctx.where.case_insensitive(real))
                if bparts is not None:
                    ctx.touch(ri)
                    judge_glob_static(ctx, cmd, word, ri, bparts + segs[i:], ctx.where.case_insensitive(real), op)
                    continue
        if i == len(segs):
            continue
        s = segs[i]
        if s == "**":
            if risky(segs[i:]):
                ctx.deny("G-LIMIT", "%s: a wildcard above a Studio repository — write the folder names." % word.value)
                return
            continue
        if _glob_literal(s, ext):
            p = os.path.join(path, s)
            if ctx.fs.exists(p):
                frontier.append((p, i + 1))
            continue
        names = ctx.fs.listdir(path)
        if names is None:
            if ctx.fs.exists(path) and risky(segs[i:]):
                ctx.deny("G-LIMIT", "%s: a wildcard above a Studio repository — write the folder names." % word.value)
                return
            continue
        for n in sorted(names):
            count += 1
            if count > WALK_MAX:
                if risky(segs[i:]):
                    ctx.deny("G-LIMIT", "%s: a wildcard above a Studio repository — write the folder names."
                             % word.value)
                return
            if n.startswith(".") and not s.startswith("."):
                continue
            if protect._seg_ok(s, n, fold, ext):
                p = os.path.join(path, n)
                if i + 1 < len(segs) and not ctx.fs.isdir(p):
                    continue
                frontier.append((p, i + 1))


GIT_ENV_TARGET = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")


UNKNOWN_RUN = "the folder git runs in is unknown"


def keeps_files(g):
    """Whether a git call in a folder the guard cannot tell changes no file Studio protects whatever the folder is: add
    without -f, stash without -a, checkout -b, switch and reset without a discard, restore --staged."""
    args = [w.value for w in g.args]
    if any(a is None for a in args):
        return False
    flags = [a for a in args if a.startswith("-")]
    if g.sub == "add":
        return not any(a in ("-f", "--force") or re.match(r"^-[a-zA-Z]*f", a) for a in flags)
    if g.sub == "stash":
        return not any(a == "--all" or re.match(r"^-[a-zA-Z]*a[a-zA-Z]*$", a) for a in flags)
    if g.sub == "checkout":
        return any(a in ("-b", "-B", "--orphan") or a.startswith("--orphan=") for a in flags) and "--" not in args \
            and not any(a in ("-f", "--force", "-p", "--patch") for a in flags)
    if g.sub == "switch":
        return not any(a in ("-f", "--force", "--discard-changes") for a in flags)
    if g.sub == "reset":
        return not any(a in ("--hard", "--merge", "--keep") for a in flags)
    if g.sub == "restore":
        return any(a in ("-S", "--staged") for a in flags) and not any(a in ("-W", "--worktree") for a in flags)
    return False


def per_folder(cmd):
    """review 9 B1: the command once per folder it may run in (a `cd` that may fail, a conditional `cd`, PIPEFAIL):
    copies with that one run folder; the command itself when it has one folder or none the guard can tell."""
    run = run_folders(cmd)
    if len(run) <= 1:
        return [cmd]
    out = []
    for c in run:
        cc = copy.copy(cmd)
        cc.run_cwds = [c]
        out.append(cc)
    return out


def git_targets(ctx, cmd):
    """[(folder copy, git_target)] for each folder git may run in (review 9 B1)."""
    return [(cc, git_target(ctx, cc)) for cc in per_folder(cmd)]


def git_target(ctx, cmd):
    """(RepoInfo, run cwd, git prefix args, extra env) for a git command, or a reason string to deny.
    --git-dir/--work-tree and GIT_DIR/GIT_WORK_TREE (command first, then the inherited environment) win."""
    g = cmd.git
    run = run_folders(cmd) or [None]
    run_cwd = run[0] if len(run) == 1 else None
    env_set = cmd.env.set
    extra = {}
    for name, w in env_set.items():
        if name.startswith("GIT_CONFIG"):
            return "the command sets %s" % name
        if name in GIT_ENV_TARGET:
            if w is None or w.value is None:
                return "%s is not a literal" % name
            extra[name] = w.value
    if any(d is None for d in g.c_dirs):
        return "-C is not a literal"
    gd = g.git_dir if g.git_dir is not None else extra.get("GIT_DIR", ctx.env.get("GIT_DIR"))
    wt = g.work_tree if g.work_tree is not None else extra.get("GIT_WORK_TREE", ctx.env.get("GIT_WORK_TREE"))
    raw = [w.value for w in cmd.words]
    for i, a in enumerate(raw):
        if a in ("--git-dir", "--work-tree") and (i + 1 >= len(raw) or raw[i + 1] is None):
            return "%s is not a literal" % a
    if run_cwd is None:
        if gd is None and wt is None:
            # a folder the guard cannot tell (cd $D, env -C $D, a wildcard -C: §1.7a, review 2 M1/M12): the repository
            # git works in is unknown. Several folders are judged one by one (per_folder, review 9 B1).
            return UNKNOWN_RUN
        if (gd and not os.path.isabs(gd)) or (wt and not os.path.isabs(wt)):
            return "the working folder is unknown"
        if wt is None:
            return UNKNOWN_RUN  # GIT_DIR alone: git's work tree is the folder it runs in (review 9 M1)
    def absol(p):
        return os.path.normpath(p if os.path.isabs(p) else os.path.join(run_cwd, p))
    pre = []
    if gd is not None:
        gd = absol(gd)
        pre += ["--git-dir", gd]
    if wt is not None:
        wt = absol(wt)
        pre += ["--work-tree", wt]
    if gd is None and wt is None:
        if run_cwd is None or not ctx.fs.exists(run_cwd):
            return None
        repo = ctx.where.git_repo(run_cwd)
    else:
        from .where import GitRepo
        worktree = wt or run_cwd
        git_dir = gd or os.path.join(worktree, ".git")
        common = git_dir
        cf = os.path.join(git_dir, "commondir")
        if ctx.fs.isfile(cf):
            c = (ctx.fs.read(cf, 4096, count_read=False) or "").strip()
            if c:
                common = os.path.normpath(c if os.path.isabs(c) else os.path.join(git_dir, c))
        repo = GitRepo(ctx.fs.realpath(worktree), ctx.fs.realpath(git_dir), ctx.fs.realpath(common))
    ri = ctx.repos.info(repo) if repo is not None else None
    if ri is None:
        return None
    env = {k: v for k, v in extra.items() if k == "GIT_INDEX_FILE"}
    cwd = run_cwd or ri.worktree
    if pre and protect.rel_parts(os.path.realpath(cwd), ri.worktree, False) is None:
        cwd = ri.worktree  # outside the work tree git reads paths from its top; previews print them from there
    return ri, cwd, pre, env


def _ancestor_or_equal(parts, anchor, fold):
    if len(parts) > len(anchor):
        return False
    return all((a.casefold() == b.casefold()) if fold else a == b for a, b in zip(parts, anchor))


def _within(parts, anchor, fold):
    if len(parts) < len(anchor):
        return False
    return all((a.casefold() == b.casefold()) if fold else a == b for a, b in zip(parts[:len(anchor)], anchor))


def spec_parts(ctx, ri, run_cwd, spec):
    """Repository-relative parts of a pathspec (None when outside the worktree)."""
    if spec.startswith(":/") or spec.startswith(":(top)"):
        rest = spec.split(")", 1)[1] if spec.startswith(":(") else spec[2:]
        base = ri.worktree
        spec = rest or "."
    else:
        base = run_cwd
    p = os.path.normpath(os.path.join(base, spec)) if not os.path.isabs(spec) else os.path.normpath(spec)
    real = ctx.fs.realpath(p) if ctx.fs.exists(p) else p
    fold = ctx.where.case_insensitive(ri.worktree)
    parts = protect.rel_parts(real, ri.worktree, fold)
    if parts is None:
        parts = protect.rel_parts(p, ri.worktree, fold)
    return parts, fold, real


GIT_NEW_VALUE_OPTS = {"-b", "-B", "--reason", "--orphan", "-o", "--origin", "--branch", "--template",
                      "--separate-git-dir", "--reference", "--reference-if-able", "--depth", "--shallow-since",
                      "--shallow-exclude", "-c", "--config", "--server-option", "--filter", "-u", "--upload-pack",
                      "-j", "--jobs", "--bundle-uri", "--object-format", "--ref-format", "--initial-branch"}


def check_git_new_checkout(ctx, cmd):
    """`git worktree add` / `git clone` / `git init` with a folder inside Studio's folders would fill them with files
    no Studio script wrote (a branch's local/ — machine.json, pending approvals; m1-plan §3.1 review V1)."""
    g = cmd.git
    args = [w.value for w in g.args]
    if g.sub == "worktree" and args[:1] == ["add"]:
        rest, sub = g.args[1:], "worktree add"
    elif g.sub in ("clone", "init"):
        rest, sub = g.args, g.sub
    else:
        return False
    pos, skip = [], False
    for w in rest:
        v = w.value
        if skip:
            skip = False
            if v is not None and g.sub == "init" and w is not None:
                pass
            continue
        if v is None:
            pos.append(None)
            continue
        if v.startswith("-"):
            if v in GIT_NEW_VALUE_OPTS:
                skip = True
            if v.startswith("--separate-git-dir="):
                pos.append(v.split("=", 1)[1])
            continue
        pos.append(v)
    if g.sub == "clone":
        if len(pos) >= 2:
            dests = pos[1:2]
        elif pos and pos[0] is not None:
            dests = [os.path.basename(pos[0].rstrip("/")).rsplit(".git", 1)[0] or "."]
        else:
            dests = pos[:1]
    elif g.sub == "init":
        dests = pos[:1] or ["."]
    else:
        dests = pos[:1]
    # --separate-git-dir <dir> of init/clone also writes a git folder
    for i, w in enumerate(rest):
        if w.value == "--separate-git-dir" and i + 1 < len(rest):
            dests.append(rest[i + 1].value)
    for d in dests:
        if d is None:
            continue
        for a, real, ri in resolve_all(ctx, cmd, d):
            if real is None or ri is None or not ri.studio:
                continue
            parts, fold = rel(ctx, ri, real)
            if parts is None:
                continue
            if any(_within(parts, anc, fold) for anc in ([ri.studio_root], [".claude", "studio"])):
                ctx.deny("G-PROT", "git %s %s would create a checkout inside Studio's folders (%s) — its files would "
                                   "stand where only Studio's scripts write; use a folder outside them."
                         % (sub, d, "/".join(parts)))
                return True
    return False


def check_git(ctx, cmd, studio_infos):
    g = cmd.git
    if g is None:
        return
    if len(run_folders(cmd)) > 1:
        # review 9 B1: a folder change that may or may not happen — git is judged in each folder it may run in
        for cc in per_folder(cmd):
            n = len(ctx.denies)
            check_git(ctx, cc, studio_infos)
            if len(ctx.denies) > n:
                return
        return
    dyn_global = [w.raw for w in cmd.words[1:] if w.value is None and w.raw.startswith(("--git-dir", "--work-tree"))]
    if g.sub is None and getattr(g, "sub_dynamic", False) and not dyn_global and studio_infos:
        ctx.deny("G-OPAQUE", "git with a subcommand the guard cannot read (a word that may be anything or nothing) in "
                             "a Studio repository — write the subcommand literally.")  # G1 §3
        return
    if g.sub is None or dyn_global:
        if dyn_global and studio_infos:
            ctx.deny("G-RESET", "git with %s (not a literal) cannot be checked — write the path." % dyn_global[0])
        return
    if check_git_new_checkout(ctx, cmd):
        return
    target = git_target(ctx, cmd)
    if isinstance(target, str):
        if studio_infos and g.sub in ("clean", "reset", "checkout", "restore", "switch", "stash", "rm", "mv", "add", "worktree") \
                and not (target == UNKNOWN_RUN and keeps_files(g)):
            ctx.deny("G-RESET" if g.sub != "clean" else "G-CLEAN",
                     "git %s cannot be checked safely (%s)." % (g.sub, target))
        return
    if target is None:
        return
    ri, run_cwd, pre, penv = target
    if not ri.studio:
        return
    ctx.touch(ri)
    args = [w.value for w in g.args]
    sub = g.sub
    raw_argv = [w.value for w in cmd.words]
    sr_anchor, cl_anchor = [ri.studio_root], [".claude", "studio"]
    unsafe = gitprobe.unsafe(g) or ("--exec-path" if any(a and a.startswith("--exec-path") for a in raw_argv) else None)
    if sub == "clean":
        if any(a in ("-n", "--dry-run") or (a and re.match(r"^-[a-zA-Z]*n", a)) for a in args):
            return
        if unsafe:
            ctx.deny("G-CLEAN", "git clean with %s cannot be previewed safely." % unsafe)
            return
        if any(a is None for a in args):
            ctx.deny("G-CLEAN", "could not preview git clean (an argument the guard cannot read).")
            return
        removed = ctx.probe.clean_preview(run_cwd, g.configs, args, pre=pre, env=penv)
        if removed is None:
            ctx.deny("G-CLEAN", "could not preview git clean (git failed or timed out).")
            return
        for p in removed:
            real = ctx.fs.realpath(p.rstrip("/")) if ctx.fs.exists(p.rstrip("/")) else p.rstrip("/")
            parts, fold = rel(ctx, ri, real)
            if parts is None:
                continue
            if any(_ancestor_or_equal(parts, anc, fold) or _within(parts, anc, fold) for anc in (sr_anchor, cl_anchor)):
                ctx.deny("G-CLEAN", "git clean would remove %s (Studio files). Limit the pathspec to non-Studio "
                                    "folders, or ask the user." % p)
                return
        return
    if sub == "stash":
        if any(a is not None and (a == "--all" or re.match(r"^-[a-zA-Z]*a[a-zA-Z]*$", a)) for a in args):
            ctx.deny("G-STASH", "git stash --all would take Studio's local files (%s/local)." % ri.studio_root)
        return
    if sub == "worktree" and args[:1] == ["remove"]:
        for w in g.args[1:]:
            if w.value is None or w.value.startswith("-"):
                continue
            path = os.path.normpath(os.path.join(run_cwd, w.value))
            other = ctx.repos.info(ctx.where.git_repo(path)) if ctx.fs.exists(path) else None
            if other is not None and other.studio:
                ctx.deny("G-DEL", "git worktree remove %s deletes a checkout that holds Studio's folders." % w.value)
        return
    if sub in ("rm", "mv"):
        specs = [w for w in g.args if w.value is None or not w.value.startswith("-")]
        if any(w.value is None for w in specs):
            ctx.deny("G-DEL", "git %s with a pathspec the guard cannot read." % sub)
            return
        dels = specs if sub == "rm" else specs[:-1]
        for w in dels:
            parts, fold, real = spec_parts(ctx, ri, run_cwd, w.value)
            if parts is None:
                continue
            tid = protect.delete_hits(parts, ri.studio_root, fold, is_dir=(not ctx.fs.exists(real)) or ctx.fs.isdir(real))
            if tid:
                ctx.deny("G-DEL", "git %s %s removes %s that git cannot restore." % (
                    sub, w.value, "Studio's folders" if tid == "P-ANC" else protect.BY_ID[tid][2] + " data"))
                return
        if sub == "mv" and specs:
            parts, fold, real = spec_parts(ctx, ri, run_cwd, specs[-1].value)
            if parts is not None and protect.classify(parts, ri.studio_root, fold):
                ctx.deny("G-PROT", "git mv onto %s writes a protected Studio path." % specs[-1].value)
        return
    if sub == "add":
        force = any(a is not None and (a in ("-f", "--force") or re.match(r"^-[a-zA-Z]*f[a-zA-Z]*$", a)) for a in args)
        for w in g.args:
            if w.value is None or w.value.startswith("-"):
                continue
            parts, fold, real = spec_parts(ctx, ri, run_cwd, w.value)
            if parts is None:
                continue
            tid = protect.classify(parts, ri.studio_root, fold, include_local=True)
            if tid == "P-LOCAL" or (force and _ancestor_or_equal(parts, sr_anchor + ["local"], fold)):
                if force:
                    ctx.deny("G-PROT", "git add -f %s: Studio's local files are never staged (they stay out of "
                                       "every commit)." % w.value)
            elif tid:
                ctx.deny("G-PROT", "git add %s (%s) — Studio files are staged only by check_commit.py --stage."
                         % (w.value, protect.BY_ID[tid][2]))
        return
    if sub in ("checkout", "restore", "reset", "switch"):
        check_discard(ctx, cmd, ri, run_cwd, pre, penv, unsafe)


def check_discard(ctx, cmd, ri, run_cwd, pre, penv, unsafe):
    g = cmd.git
    sub = g.sub
    args = [w.value for w in g.args]
    sr_anchor, cl_anchor = [ri.studio_root], [".claude", "studio"]
    rev, specs, whole = None, [], False
    if sub == "reset":
        whole = "--hard" in args or "--merge" in args or "--keep" in args
        if not whole:
            return
    elif sub == "switch":
        whole = any(a in ("--discard-changes", "-f", "--force") for a in args)
        if not whole:
            return
    elif sub == "checkout":
        positional, after, seen_dd, branch = [], [], False, False
        flags_patch = False
        i = 0
        while i < len(args):
            a = args[i]
            if seen_dd:
                after.append(g.args[i])
            elif a == "--":
                seen_dd = True
            elif a in ("-b", "-B", "--orphan"):
                branch = True
                i += 1
            elif a is not None and a.startswith("--orphan="):
                branch = True
            elif a in ("-f", "--force"):
                whole = True
            elif a in ("-p", "--patch"):
                flags_patch = True
            elif a is not None and a.startswith("-"):
                if a in ("--conflict", "--pathspec-from-file"):
                    i += 1
                if a.startswith("--pathspec-from-file"):
                    ctx.deny("G-RESET", "git checkout --pathspec-from-file cannot be checked.")
                    return
            else:
                positional.append(g.args[i])
            i += 1
        if seen_dd:
            rev = positional[0].value if positional else None
            specs = after
        elif branch:
            specs = []
        elif positional:
            first = positional[0]
            is_rev = first.value is not None and ctx.probe.is_rev(run_cwd, first.value, pre=pre, env=penv)
            if is_rev:
                rev, specs = first.value, positional[1:]
            else:
                specs = positional
                if is_rev is None:
                    rev = first.value  # cannot tell: judge both readings (as a revision and as a pathspec)
        if flags_patch and not specs and not branch:
            whole = True  # --patch without a pathspec walks the whole tree
    elif sub == "restore":
        staged_only = False
        flags = set()
        i = 0
        while i < len(args):
            a = args[i]
            if a in ("-s", "--source") and i + 1 < len(args):
                rev = args[i + 1]
                i += 2
                continue
            if a is not None and a.startswith("--source="):
                rev = a.split("=", 1)[1]
            elif a is not None and a.startswith("-") and a != "--":
                flags.add(a)
            elif a != "--":
                specs.append(g.args[i])
            i += 1
        staged_only = bool(flags & {"-S", "--staged"}) and not (flags & {"-W", "--worktree"})
        if staged_only:
            return
        if flags & {"-p", "--patch"} and not specs:
            whole = True
    if whole:
        specs_check = [ri.studio_root, ".claude/studio"]
        protected_spec = None
    else:
        specs_check, protected_spec, covers = [], None, False
        for w in specs:
            if w.value is None:
                ctx.deny("G-RESET", "git %s with a pathspec the guard cannot read." % sub)
                return
            parts, fold, real = spec_parts(ctx, ri, run_cwd, w.value)
            if parts is None:
                continue
            if _ancestor_or_equal(parts, sr_anchor, fold) or _ancestor_or_equal(parts, cl_anchor, fold) or \
                    any(ch in w.value for ch in "*?[<"):
                covers = True
            elif _within(parts, sr_anchor, fold) or _within(parts, cl_anchor, fold):
                tid = protect.classify(parts, ri.studio_root, fold, include_local=True)
                if tid:
                    protected_spec = (w.value, tid)
                specs_check.append("/".join(parts))
        if covers:
            specs_check = [ri.studio_root, ".claude/studio"]
        if protected_spec:
            ctx.deny("G-PROT", "git %s %s overwrites a protected Studio file (%s)%s." % (
                sub, protected_spec[0], protect.BY_ID[protected_spec[1]][2], (" from %s" % rev) if rev else ""))
            return
        if covers and rev:
            ctx.deny("G-PROT", "git %s %s … restores Studio's folders from %s, overwriting Studio files."
                     % (sub, rev, rev))
            return
        if not specs_check:
            return
    if unsafe:
        ctx.deny("G-RESET", "git with %s cannot be checked safely." % unsafe)
        return
    changes = ctx.probe.studio_changes(run_cwd, specs_check, pre=pre, env=penv)
    if changes is None:
        ctx.deny("G-RESET", "could not check for uncommitted Studio changes (git failed or timed out).")
    elif changes:
        ctx.deny("G-RESET", "git %s would discard uncommitted Studio changes: %s." % (sub, ", ".join(changes[:5])))


def check_env(ctx, cmd):
    """(f): lock-bypassing environment on s2v and lock.py calls; Claude Code markers on commits."""
    v = cmd.env
    if cmd.s2v is not None or cmd.lock is not None:
        what = "s2v" if cmd.s2v is not None else "lock.py"
        if v.cleared:
            ctx.deny("G-ENV", "%s runs with an emptied environment (env -i / sudo / exec -c) — that bypasses the "
                              "machine lock." % what)
        if v.unknown:
            ctx.deny("G-ENV", "%s runs after `source` changed the environment in unknown ways." % what)
        if "HOME" in v.set or "HOME" in v.unset:
            ctx.deny("G-ENV", "%s runs with a different HOME — that moves ~/.s2v (the machine lock)." % what)
        for name in LOCK_VARS:
            if name in v.set or name in v.unset:
                if name == "S2V_STATE_DIR":
                    mine = ctx.env.get("S2V_STATE_DIR")
                    if name in v.unset:
                        if not mine:
                            continue
                    else:
                        val = v.set[name].value
                        if val is not None and mine and os.path.realpath(val) == os.path.realpath(mine):
                            continue
                ctx.deny("G-ENV", "%s changes %s for an %s call — that bypasses the machine lock (S2V_STATE_DIR "
                                  "must be the guard's own)." % (cmd.prog or what, name, what))
    if studio_script(ctx, cmd):
        # Studio's scripts find the repository (and its used-answer record) through git: a redirected git folder
        # would make them use a copy (m1-plan §3.2 review U2)
        moved = sorted(n for n in set(v.set) | set(v.unset) if n in commitrule.GIT_ENV or n in GIT_ENV_TARGET
                       or n.startswith("GIT_CONFIG"))
        if v.cleared:
            moved.append("env -i")
        if moved:
            ctx.deny("G-ENV", "%s runs with %s changed — Studio's scripts use the repository's own git folder; run "
                              "them without git variables." % (os.path.basename(studio_script(ctx, cmd)),
                                                               ", ".join(moved)))
    is_commit = (cmd.git is not None and cmd.git.sub == "commit") or studio_script(ctx, cmd, "check_commit.py")
    if is_commit:
        if v.cleared or any(n in v.set or n in v.unset for n in MARKER_VARS):
            ctx.deny("G-MARKER", "this removes the Claude Code session markers from a commit — do not remove "
                                 "markers to retry.")


# s2v commands whose results a person reviews: in a Studio repository only run_s2v.py runs them (m1-plan §4.2,
# M1b review Y1) — it picks the watermark from the state and records the result. The wrapper's own child process is
# not a Bash command the guard sees.
WRAPPED_S2V = (("render",), ("snapshot",), ("dev",))  # dev runs snapshot / render --draft and keeps servers up
# pages written into a folder of the agent's choosing: refused with --out-dir (their default place is s2v's own)
OUT_DIR_S2V = (("takes",), ("direct",))
# s2v commands that change a video's audio lock: only under lock.py (M1f; `audio prune` deletes takes — review V5).
# `say` takes the machine lock itself and writes nothing of a video's (s2v say.ts → Service.ensure), so it is free.
LOCKED_S2V = (("tts",), ("audio", "prune"))


def check_s2v_results(ctx, cmd):
    if cmd.s2v is None:
        return
    vals = [w.value for w in cmd.s2v.args]
    words, flags = s2vcall.split([x for x in vals if x is not None])
    if words[:1] in OUT_DIR_S2V and "--out-dir" in flags:  # `takes` is a two-word s2v command (takes pick …)
        ctx.deny("G-WRAP", "s2v %s --out-dir writes its results where the agent says in a Studio repository — run it "
                           "without --out-dir (s2v's own results folder), or use \"python3 "
                           ".claude/studio/scripts/run_s2v.py render|snapshot <video> --output <output>\"." % words[0])
        return
    if tuple(words[:1]) in LOCKED_S2V or tuple(words[:2]) in LOCKED_S2V:
        if "lock-child" not in (cmd.ctx or []):
            ctx.deny("G-WRAP", "s2v %s in a Studio repository runs only under the machine lock wrapper, which records "
                               "a busy machine as held:lock — use \"python3 .claude/studio/scripts/lock.py run --kind "
                               "tts -- <the same s2v command>\"." % " ".join(words[:2]))
            return
    if words in WRAPPED_S2V or (any(x is None for x in vals[:1])):
        ctx.deny("G-WRAP", "s2v %s in a Studio repository runs only through Studio's wrapper, which sets the proxy "
                           "watermark from the approvals and records the result — use \"python3 "
                           ".claude/studio/scripts/run_s2v.py render|snapshot <video> --output <output>\"."
                 % (words[0] if words else "with a command word the guard cannot read"))


def check_setup(ctx, cmd):
    """The plugin's setup.py (M1c): its approval commands need the person's answer; init, get, previews and plans do
    not. A setup.py that is not the plugin's is not Studio's (a repository copy never has one)."""
    real = studio_script(ctx, cmd, "setup.py")
    if real is None:
        return False
    args = cmd.script.args
    ri = _run_repo(ctx, cmd)
    if ri is None or not ri.harness:
        return True  # no harness: setup.py refuses everything but init itself (m1-plan §5.1)
    if os.path.dirname(real) != PLUGIN_SCRIPTS:
        ctx.deny("G-APPROVAL", "setup.py runs from the plugin only — this one (%s) is not Studio's." % real)
        return True
    if any(w.value is None for w in args):
        ctx.deny("G-DYNARG", "setup.py arguments must be literal (the person's answer binds the exact command line).")
        return True
    vals = [w.value for w in args]
    from ..setup import labels as sl
    if not sl.needs_evidence(vals, ri.protected_keys):
        return True
    from . import approve
    if not _count_approval(ctx, cmd, "setup.py %s" % " ".join(vals[:2])):
        return True
    v = approve.setup_py(ctx.hook, ctx.env, ri, vals)
    if v.rule:
        ctx.deny(v.rule, v.text, messages.alias_sources(cmd),
                 suffix=approve.evidence_suffix(v.code))  # fix-0025 §2.2
        return True
    pend = v.pending
    ctx.effects.append(("G-EVIDENCE", lambda: approve.write_pending(ri, pend)))
    add_candidate(ctx, (cmd, "state", v.reason))
    return True


def check_approval(ctx, cmd):
    if check_setup(ctx, cmd):
        return
    real = studio_script(ctx, cmd, "state.py")
    if real is not None:
        args = cmd.script.args
        if any(w.value is None for w in args):
            ctx.deny("G-DYNARG", "state.py arguments must be literal (the approval record binds the exact command "
                                 "line).")
            return
        sub = args[0].value if args else None
        if sub is None or state_commands.needs_evidence(sub):
            state_approval(ctx, cmd, [w.value for w in args])
        return
    if cmd.s2v is not None:
        vals = [w.value for w in cmd.s2v.args]
        if any(x is None for x in vals):
            known = [x for x in vals if x is not None]
        else:
            known = vals
        words, flags = s2vcall.split(known)
        appr = words in S2V_APPROVALS
        if words == ("character", "build") and "--reset-derived" in flags and "--dry-run" not in flags:
            appr = True
        if words == ("character", "missing") and "--apply" in flags:
            appr = True
        if words == ("voice", "create"):
            for i, x in enumerate(known):
                if x == "--candidates" and i + 1 < len(known) and known[i + 1] == "1":
                    appr = True
                if x == "--candidates=1":
                    appr = True
        if appr:
            s2v_approval(ctx, cmd, words)


def _run_repo(ctx, cmd):
    run = run_folders(cmd)
    if len(run) != 1 or not ctx.fs.exists(run[0]):
        return None
    return ctx.repos.info(ctx.where.git_repo(run[0]))


def _count_approval(ctx, cmd, what):
    ctx.approvals += 1
    if ctx.approvals > 1:
        ctx.deny("G-APPROVAL", "%s: one approval command per call (the evidence slot holds one)." % what)
        return False
    return True


def state_approval(ctx, cmd, argv):
    """M0d-2: a state.py subcommand that records a person's decision (m0d2-plan §3)."""
    from . import approve
    sub = argv[0] if argv else ""
    if not _count_approval(ctx, cmd, "state.py %s" % sub):
        return
    ri = _run_repo(ctx, cmd)
    if ri is None or not ri.harness:
        ctx.deny("G-APPROVAL", "state.py %s runs outside a Studio repository the guard can tell." % sub)
        return
    v = approve.state_py(ctx.hook, ctx.env, ri, argv)
    if v.rule:
        ctx.deny(v.rule, v.text, messages.alias_sources(cmd),
                 suffix=approve.evidence_suffix(v.code))  # fix-0025 §2.2
        return
    pend = v.pending
    ctx.effects.append(("G-EVIDENCE", lambda: approve.write_pending(ri, pend)))
    add_candidate(ctx, (cmd, "state", v.reason))


def check_script(ctx, cmd):
    """0.0.28 §1.1: a repository copy of Studio's read-and-record scripts (scriptrun.AUTO_SCRIPTS; state.py only for
    evidence-free subcommands but ask-before) becomes an allow candidate; finish() allows only a call that is that
    alone and that scriptrun.trusted accepts. No deny comes from here."""
    from . import scriptrun
    if ctx.hook.get("permission_mode") != "default":
        return
    real = studio_script(ctx, cmd)
    if real is None or os.path.dirname(real) == PLUGIN_SCRIPTS or os.path.basename(real) not in scriptrun.AUTO_SCRIPTS:
        return
    args = cmd.script.args
    if any(w.value is None for w in args):
        return
    name = os.path.basename(real)
    got = scriptrun.shape(name, [w.value for w in args])
    if got is None:
        return
    video, sub = got
    ri = _run_repo(ctx, cmd)
    if ri is None or not ri.harness or ri.config_error:
        return
    add_candidate(ctx, (cmd, "script", scriptrun.describe(name, sub, video)))
    ctx.script_calls[id(cmd)] = (ri.worktree, ri.studio_root, video, sub)


def s2v_approval(ctx, cmd, words):
    from . import approve
    what = "s2v " + " ".join(words)
    if not _count_approval(ctx, cmd, what):
        return
    ri = _run_repo(ctx, cmd)
    v = approve.s2v(ctx.hook, ctx.env, ri if ri is not None and ri.studio else None, words)
    if v.rule:
        ctx.deny(v.rule, v.text, messages.alias_sources(cmd),
                 suffix=approve.evidence_suffix(v.code))  # fix-0025 §2.2
        return
    add_candidate(ctx, (cmd, "s2v", v.reason))


# ---- 0.0.24 (pilot-1 P6): printing Studio's own documents ----

def doc_call(ctx, cmd):
    """The reason to allow when `cmd` is `python3 <the plugin's setup.py> doc [<name>]`, else None. The document
    command is read-only and plugin-only, so it needs no evidence; allowing it keeps every later `doc` call of a
    `/std` run free of prompts (the skill's allowed-tools rule lasts one turn). A mismatch only means no allow:
    the call then gets today's judgement and the normal permission prompt."""
    sc = cmd.script
    if sc is None or not isinstance(sc.path, dict):
        return None
    args = sc.args
    if not args or len(args) > 2 or args[0].value != "doc" or any(w.value is None for w in args):
        return None
    # exactly two spellings of the plugin's own setup.py (resolved, and as ${CLAUDE_PLUGIN_ROOT} spells it),
    # never a symbolic link to it (a link elsewhere may sit next to a planted stdo/)
    text = sc.path.get("text")
    if text not in DOC_SCRIPTS:
        return None
    try:
        if stat.S_ISLNK(os.lstat(text).st_mode):
            return None
    except OSError:
        return None
    if os.path.realpath(text) != DOC_SCRIPTS[0]:
        return None
    name = args[1].value if len(args) == 2 else None
    from ..setup import doc
    if name is not None and name != "help" and name not in doc.NAMES:
        return None
    # the run folder's root: the `cd <dir>` target, else the hook's cwd; its git top level, else the folder itself
    run = run_folders(cmd) if (cmd.run_cwds or "run-unknown" in cmd.flags) else [ctx.cwd]
    if len(run) != 1 or not ctx.fs.exists(run[0]):
        return None
    repo = ctx.where.git_repo(run[0])
    root = repo.worktree if repo is not None else run[0]
    roots = (root, os.path.realpath(root))

    def inside(p):
        return any(_inside(p, r) for r in roots)

    # developing Studio with the plugin enabled: the repository holds the plugin (another copy of the code)
    if inside(PLUGIN_SCRIPTS) or inside(PLUGIN_SCRIPTS_SPELLED):
        return None
    # an interpreter of the repository's own (a venv in it) is the repository's code, not the person's Python
    w0 = cmd.words[0].value if cmd.words else None
    if w0 is None:
        return None
    if "/" in w0:
        found = [w0]
    else:
        pvs = list(ctx.snap.paths) if getattr(ctx, "snap", None) is not None and ctx.snap.paths else []
        found = [where_which(w0, pv, ctx.fs) for pv in [ctx.env.get("PATH", "")] + pvs]
    for p in found:
        if p is None:
            return None
        if inside(p) or inside(os.path.realpath(p)):
            return None
        for folder in (os.path.dirname(p), os.path.dirname(os.path.dirname(p))):
            if os.path.exists(os.path.join(folder, "pyvenv.cfg")) and (inside(folder) or
                                                                       inside(os.path.realpath(folder))):
                return None
    return "prints Studio's document %s (setup.py doc: read-only, plugin only)" % (name or "list")


def check_docs(ctx, sc):
    """Every `setup.py doc` call becomes an allow candidate; finish() allows only a call that is that alone."""
    for c in sc.commands:
        reason = doc_call(ctx, c)
        if reason:
            add_candidate(ctx, (c, "doc", reason))


# ---- tools ----

# glob qualifiers that only narrow a glob's matches (no `e`/`+` code, no `D` dot files, no `P` words, no `:` modifiers)
QUALIFIER_AT_END_RE = re.compile(r"(?<=[^\s;&|(<>])\([^()\s]*\)(?=[\s;&|)<>]|$)")
PLAIN_QUALIFIER_RE = re.compile(r"^\((\^?[./@=p*%\-rwxRWXAIEsStUGNnoOLmacdkhMTY0-9\[\],^]+)\)$")


def glob_group_at(command, reason):
    """Whether the parser stopped at a `(` inside a command's words: a zsh glob group (`rm -rf (stu)dio`, `ls (a|b)`)
    the guard does not read (refused in a Studio repository like the other zsh glob groups)."""
    m = re.match(r"^syntax:[\w-]+@(\d+)$", reason or "")
    if not m:
        return False
    p = int(m.group(1))
    # a `(` after a blank, or joined to a word (`[[ a == x(a|b) ]]`, review 7 conf M-1)
    return command[p:p + 1] == "(" and p > 0 and command[p - 1] not in ";&|<>$=`(\n"


def ksh_glob_maybe(command, snap):
    """Whether KSH_GLOB may be on for a command: on in a snapshot, or the command may change options (setopt, set -o,
    emulate, eval, source, the options table, a snapshot function)."""
    opts_re = r"ksh|glob|setopt|unsetopt|emulate|options|eval|source|\bset\b|(^|[\s;&|(])\.(\s|$)"
    if snap is not None and snap.options.get("kshglob", False) is not False:
        return True
    if re.search(opts_re, command):
        return True
    if snap is not None:
        for w in set(re.split(r"[\s;&|()<>]+", command)):
            if w in snap.user_functions or w in snap.alternatives or w in snap.global_aliases or (
                    w in snap.plain and re.search(opts_re, snap.plain[w])):
                return True
    return False


def bare_glob_qual_on(command, snap):
    """review 4 bypass B2: whether a trailing `(…)` is certainly a glob qualifier — BARE_GLOB_QUAL certainly on and
    KSH_GLOB and SH_GLOB certainly off for the whole command. Without BARE_GLOB_QUAL `studi(o)` is a pattern that
    matches `studio`. The Bash tool turns BARE_GLOB_QUAL off after the snapshot (BASH_TOOL_POSTLUDE; checked in the
    tool's own shell, zsh 5.9), so this holds only where a snapshot's options say otherwise."""
    opts = snap.options if snap is not None else dict(SNAP_DEFAULT_OPTIONS, **BASH_TOOL_POSTLUDE["options"])
    if opts.get("bareglobqual", True) is not True or opts.get("kshglob", False) is not False or \
            opts.get("shglob", False) is not False:
        return False
    if snap is not None and snap.option_conflicts & {"bareglobqual", "kshglob", "shglob"}:
        return False
    return not ksh_glob_maybe(command, snap)


def without_plain_qualifiers(ctx, command, sc, snap, notes, budget):
    """review 3 conformance m-3: `ls **/*(.)` — a word ending in a glob qualifier that only narrows its matches is read
    without it (its matches are a subset) when BARE_GLOB_QUAL is certainly on (review 4 B2); any other glob group stays
    unparsable (G-UNPARSE in a Studio repository)."""
    text, orig = command, sc
    if not bare_glob_qual_on(command, snap):
        return orig
    for _ in range(8):
        m = re.match(r"^unsupported:zsh-glob-group@(\d+)$", sc.reason or "") if sc.status == "unparsable" else None
        if not m:
            break
        pos = int(m.group(1))
        groups = [g for g in QUALIFIER_AT_END_RE.finditer(text) if g.start() <= pos]
        if not groups or not PLAIN_QUALIFIER_RE.match(groups[-1].group(0)):
            return orig
        if text[groups[-1].start() - 1] in "!@+?*" and ksh_glob_maybe(command, snap):
            return orig  # with KSH_GLOB, `!(x)`, `*(x)`, … are patterns, not qualifiers
        text = text[:groups[-1].start()] + text[groups[-1].end():]
        sub = _scan(ctx, text, ctx.cwd, ctx.env, snapshot=snap, snapshot_notes=notes, terms=None, fs=ctx.fs,
                           budget=budget)
        if sub.status == "ok":
            return sub
        if not (sub.reason or "").startswith("unsupported:zsh-glob-group@"):
            return orig
        sc = sub
    return orig


def decide_bash(ctx, command):
    ctx.command = command
    try:
        snap, notes = ctx.snapshot_loader(ctx.env)
    except Exception:  # noqa: BLE001 — an unreadable snapshot is the None mode
        snap, notes = None, ["snapshot-unreadable:load"]
    budget = limits.Budget()
    ctx.snap = snap
    sc = _scan(ctx, command, ctx.cwd, ctx.env, snapshot=snap, snapshot_notes=notes, terms=None, fs=ctx.fs,
                      budget=budget)
    sc = without_plain_qualifiers(ctx, command, sc, snap, notes, budget)
    cwd_repo = ctx.repos.info(ctx.where.git_repo(ctx.cwd)) if ctx.fs.exists(ctx.cwd) else None
    infos = []
    ctx.infos = infos  # the Studio repositories found so far (decide: G-LIMIT only in a Studio context)
    if cwd_repo is not None and cwd_repo.studio:
        infos.append(cwd_repo)
    # the strings the shell runs from text, scanned before the repositories are collected (G1 §1.7)
    tree, flat = nested_scans(ctx, sc, budget)
    nested_cmds = [c for nd in flat if nd.sub is not None for c in nd.sub.commands]
    # target repositories
    n = collect_repos(ctx, list(sc.commands) + nested_cmds, infos, 0)
    if n is None:
        return sc, infos
    for nd in flat:
        if nd.sub is None and nd.op.kind in STRING_KINDS:  # strings, not script files
            text = nd.skeleton if nd.skeleton is not None else nd.text
            n += piece_search(ctx, text, nd.cwds, infos)
            empty_reading(ctx, nd.skeleton, nd.cwds, infos, budget)
    for o in list(sc.opaque) + [o for nd in flat if nd.sub is not None for o in nd.sub.opaque]:
        if o.kind in ("runner", "sudo-shell"):  # a refused runner's words are searched like a non-literal string (§1.2)
            n += piece_search(ctx, o.skeleton, o.cwds, infos)
            empty_reading(ctx, o.skeleton, o.cwds, infos, budget)
        elif o.kind in ("dynamic-command", "var-set") and getattr(o, "skeleton", None):
            n += piece_search(ctx, o.skeleton, o.cwds, infos)  # ${(e)X}'s value, a §1.9 variable's (m-a)
    for c in list(sc.commands) + nested_cmds:
        if unmodelled(ctx, c) and fallback_writes(c):  # §1.10: searched as a refused runner's words are
            n += piece_search(ctx, " ".join(w.skeleton for w in c.words[1:]), run_folders(c), infos)
        for text in refusal_texts(c):  # §1.9 (review 2, m-a): the command lines in options and variables
            n += piece_search(ctx, text, run_folders(c) or c.cwds, infos)
    if sc.status == "unparsable":
        n += piece_search(ctx, command, [ctx.cwd], infos)
    if n > MAX_CANDIDATES:
        ctx.deny("G-LIMIT", "the command has too many path arguments for the guard — split it.")
        return sc, infos
    # review 3 B1/B-1, M3: a search cut short, a string not read for time or a scan stopped by a limit may hide a
    # Studio repository named later in the command — refused unless nothing in it can name one (also outside one)
    cut = getattr(ctx, "search_cut", False) or getattr(ctx, "nested_budget_out", False) or (
        sc.status == "unparsable" and (sc.reason or "").startswith("limit:"))
    if cut and (infos or may_name_repo(ctx, command)):
        ctx.deny("G-LIMIT", "the text this command runs takes the guard too long to search for Studio repositories "
                            "— split it into simpler commands, one step per call.")
        return sc, infos
    ctx.collected = True  # the repositories are known: a limit from here on refuses only in a Studio context
    for ri in infos:
        ctx.touch(ri)
    fold = ctx.where.case_insensitive(ctx.cwd) if ctx.fs.exists(ctx.cwd) else False
    terms = terms_for(infos, fold)
    # G1 §1.8: a term split by quoting or backslashes (`stu''dio`, `st\udio`) still hits
    raw_hits = terms.find(command) or terms.find(re.sub(r"['\"\\]", "", command))
    src_notes = messages.snapshot_sources(sc.notes)
    if sc.status == "error":
        if infos:
            ctx.deny("G-ERR", "internal guard error (%s) in a Studio repository — tell the user; this is a bug in the "
                              "guard." % sc.reason)
        return sc, infos
    if sc.status == "unparsable":
        if infos and raw_hits:
            ctx.deny("G-UNPARSE", "the guard could not parse this command (%s) and it mentions %s — split it into "
                                  "simple commands." % (sc.reason, raw_hits[0].term), src_notes)
        elif infos and ((sc.reason or "").startswith("unsupported:zsh-") or glob_group_at(command, sc.reason)):
            # G1 §1.8 (M6): zsh-only forms the parser does not read (glob groups and qualifiers, repeat, foreach,
            # anonymous functions) — refused without a Studio term
            ctx.deny("G-UNPARSE", "the guard does not read this zsh form (%s) in a Studio repository — write the "
                                  "command without it, one step per call." % sc.reason, src_notes)
        elif infos and unparsable_assignment(command):
            ctx.deny("G-UNPARSE", "the guard could not parse this command (%s) and it assigns %s, which the guard "
                                  "would follow — split it into simple commands." % (
                                      sc.reason, unparsable_assignment(command)), src_notes)
        elif infos and (unparsable_glob_group(command) or unparsable_verb(command, snap)):
            # review 7 conf M-1: text the guard cannot read with a glob group or a command that deletes, moves or
            # writes files does not pass silently in a Studio repository
            ctx.deny("G-UNPARSE", "the guard could not parse this command (%s) and it %s — split it into simple "
                                  "commands, one step per call." % (
                                      sc.reason, "has a glob group (…)" if unparsable_glob_group(command) else
                                      "runs %s" % unparsable_verb(command, snap)), src_notes)
        # out-of-repo files are judged from the text only when parsing failed
        return sc, infos
    check_zsh(ctx, [sc] + [nd.sub for nd in flat if nd.sub is not None], infos)  # G1 §1.8, §1.9
    # always: out-of-repo protected files (and lock owner records); Studio paths when a repository is one
    ctx.earlier_write = False  # G1 §2: a `**` glob is listed only when nothing before it in the call may write
    for c in sc.commands:
        ctx.current = c
        check_out_of_repo(ctx, c)
        check_paths(ctx, c, infos)
        if is_writer(c) or c.wrappers:
            ctx.earlier_write = True
    ctx.current = None
    ctx.earlier_write = True  # the strings run from text: the static rule
    check_shell_strings(ctx, sc, infos, tree)  # adds the host `sh` of a string that extracts or copies trees
    if ctx.bulk_ids:
        bulk_then_write(ctx, sc.commands, ctx.bulk_ids)
    ctx.scan = sc
    check_docs(ctx, sc)  # in any folder: the document command needs no Studio repository (0.0.24)
    if not infos:
        check_sed_outside(ctx, sc, n)  # fix-0025 §1: a sed `w`/`r` file is not a path-like word
        return sc, infos
    if STUDIO_NAMES_RE.search(command):
        ctx.deny("G-ENV", "STUDIO_* variables are set only by the person who starts Claude.")
    by_id = {c.id: c for c in sc.commands}
    check_dynamic_writers(ctx, sc, terms, infos)
    for o in sc.opaque:
        check_opaque(ctx, o, by_id.get(o.cmd), terms, infos, src_notes)
    for c in sc.commands:
        ctx.current = c
        per_command(ctx, c, infos, sc)
    ctx.current = None
    # the commands of the strings the shell runs from text, each with its own scan (G1 §1.7)
    for nd in flat:
        if nd.sub is None:
            continue
        ctx.scan, ctx.command = nd.sub, nd.text
        sub_ids = {c.id: c for c in nd.sub.commands}
        for o in nd.sub.opaque:
            check_opaque(ctx, o, sub_ids.get(o.cmd), terms, infos, src_notes)
        for c in nd.sub.commands:
            ctx.current = c
            per_command(ctx, c, infos, nd.sub)
        ctx.current = None
    ctx.scan, ctx.command = sc, command
    for c in list(sc.commands) + nested_cmds:  # §1.10
        if unmodelled(ctx, c):
            ctx.current = c
            check_fallback(ctx, c, infos)
    ctx.current = None
    return sc, infos


ASSIGN_TEXT_RE = re.compile(r"(?:^|(?<=[\s;&|({`]))([A-Za-z_][A-Za-z0-9_]*)(?:\[[^\]\s]*\])?\+?=")


UNPARSABLE_VERBS = ("rm", "rmdir", "unlink", "mv", "cp", "ln", "install", "rsync", "dd", "truncate", "shred", "trash",
                    "srm", "find", "git", "tar", "unzip", "ditto", "chmod", "chown", "chflags", "sed", "perl", "tee",
                    "touch", "mkdir", "patch", "xargs", "sh", "bash", "zsh", "eval", "source", "exec", "python",
                    "python3", "node")
_VERB_RE = re.compile(r"(?<![\w./=$-])(%s)(?![\w.=/-])" % "|".join(re.escape(v) for v in UNPARSABLE_VERBS))


def _unquoted_text(command):
    return re.sub(r"'[^']*'|\"(?:[^\"\\]|\\.)*\"|\\.", " ", command)


def unparsable_glob_group(command):
    """review 7 conf M-1: whether text the guard cannot parse may hold a zsh glob group — a `(` joined to a word
    (`stu(d|x)io`, `*.(ts|tsx)`, `(#i)x`) or a parenthesized `|` alternative outside quotes."""
    t = _unquoted_text(command)
    t = re.sub(r"\$\(\(|\$\(|[<>=]\(|\(\(|\)\)", " ", t)  # $(…), $((…)), <(…), =(…), ((…))
    if re.search(r"[^\s;&|(){}<>`$=]\(", t) or re.search(r"\([^()]*\|[^()]*\)", t):
        return True
    return bool(re.search(r"\(#[a-zA-Z]", t))


def unparsable_verb(command, snap=None):
    """review 7 conf M-1: a command word in unparsable text that deletes, moves or writes files or runs code — its
    name, or None (the text is not read, so any such word counts). review 8 M1: also in every spelling zsh accepts in
    command position (`/bin/rm`, `=rm`, `r''m`, `r\\m`, `${:-rm}`, `$X`, an alias or function of the snapshot whose text
    holds such a word), and a write redirection (`>`, `>|`, `>>&!`, `&>|`, …)."""
    m = _VERB_RE.search(command)
    if m:
        return m.group(1)
    words, writes, aliases = _text_commands(command)
    for w, dyn in words:
        r = _verb_word(w, dyn, snap, 0)
        if r:
            return r
    for value in aliases:  # `alias x='r\\m -rf'` in the text itself
        for w, dyn in _text_commands(value)[0]:
            r = _verb_word(w, dyn, snap, 1)
            if r:
                return "an alias the command defines (%s)" % r
    if writes:
        return "a file write (%s)" % writes[0]
    return None


PRECOMMAND_WORDS = {"if", "then", "else", "elif", "do", "while", "until", "!", "time", "coproc", "{", "exec", "command",
                    "builtin", "noglob", "nocorrect", "nohup", "sudo", "doas", "env", "nice", "-", "xargs", "caffeinate",
                    "timeout", "gtimeout", "stdbuf", "watch", "repeat", "foreach", "select", "function"}
_SAFE_REDIRECT = re.compile(r"^(/dev/null|/dev/stdout|/dev/stderr)$")


def _text_commands(text):
    """Rough reading of text the parser cannot read: ([(command word with its quotes and backslashes removed, whether
    it holds an expansion)], [write redirections], [values of aliases the text defines]). A word stands in command position at the start, after `; & | ( )
    { } ` $(` or a newline, and after reserved words, precommands and assignments."""
    words, writes = [], []
    toks = []  # (text, raw, kind) kind: "w" word, "s" separator, "r>" / "r<" redirection operator
    i, n = 0, len(text)
    cur, raw, dyn = [], [], False

    def flush():
        if raw:
            toks.append(("".join(cur), "".join(raw), "w", dyn))
        del cur[:], raw[:]
    while i < n:
        c = text[i]
        if c == "\\" and i + 1 < n:
            if text[i + 1] != "\n":
                cur.append(text[i + 1])
                raw.append(text[i:i + 2])
            i += 2
            continue
        if c == "'":
            j = text.find("'", i + 1)
            j = n if j < 0 else j
            cur.append(text[i + 1:j])
            raw.append(text[i:j + 1])
            i = j + 1
            continue
        if c == '"':
            j = i + 1
            while j < n and text[j] != '"':
                if text[j] == "\\":
                    j += 1
                elif text[j] in "$`":
                    dyn = True
                j += 1
            cur.append(text[i + 1:j].replace("\\", ""))
            raw.append(text[i:j + 1])
            i = j + 1
            continue
        if c == "$" and text.startswith("$'", i):
            # review 9 B2: $'…' with its backslash escapes (`$'\''` is one quote character)
            j = i + 2
            while j < n and text[j] != "'":
                j += 2 if text[j] == "\\" else 1
            j = min(j, n)
            from .lex import ansi_c
            body, _sure = ansi_c(text[i + 2:j])
            cur.append(body)
            raw.append(text[i:j + 1])
            i = j + 1
            continue
        if c == "$" and text.startswith("$(", i) and not text.startswith("$((", i):
            flush()
            dyn = False
            toks.append(("$(", "$(", "s", False))
            i += 2
            continue
        if c in "$`":
            if c == "`":
                flush()
                dyn = False
                toks.append(("`", "`", "s", False))
                i += 1
                continue
            dyn = True
            cur.append(c)
            raw.append(c)
            i += 1
            continue
        if c in " \t":
            flush()
            dyn = False
            i += 1
            continue
        if c in ";&|(){}\n":
            if c == "&" and text.startswith(">", i + 1):
                flush()
                dyn = False
                m = re.match(r"&>>?[|!]?", text[i:])
                toks.append((m.group(0), m.group(0), "r>", False))
                i += len(m.group(0))
                continue
            if c in "{}" and raw:
                cur.append(c)
                raw.append(c)
                i += 1
                continue
            flush()
            dyn = False
            toks.append((c, c, "s", False))
            i += 1
            continue
        if c in "<>":
            m = re.match(r"<[0-9]*-[0-9]*>", text[i:]) if c == "<" else None
            if m:
                cur.append(m.group(0))
                raw.append(m.group(0))
                i += m.end()
                continue
            if c in "<>" and text.startswith("(", i + 1):
                flush()
                dyn = False
                toks.append(("(", "(", "s", False))
                i += 2
                continue
            if raw and re.fullmatch(r"\d+|\{[A-Za-z_]\w*\}", "".join(raw)):
                del cur[:], raw[:]  # an fd number
            flush()
            dyn = False
            m = re.match(r"<<<|<<-?|<>|<&|<|>>?&?[|!]?|>[|!]|>&|>", text[i:])
            toks.append((m.group(0), m.group(0), "r>" if ">" in m.group(0) and not m.group(0).startswith("<")
                         else "r<", False))
            i += len(m.group(0))
            continue
        cur.append(c)
        raw.append(c)
        i += 1
    flush()
    cmdpos = True
    k = 0
    aliases, in_alias = [], False
    while k < len(toks):
        t, r, kind, d = toks[k]
        if kind == "w" and in_alias and not cmdpos and "=" in t:
            aliases.append(t.split("=", 1)[1])
        if kind == "s":
            cmdpos = True
            in_alias = False
        elif kind.startswith("r"):
            nxt = toks[k + 1] if k + 1 < len(toks) and toks[k + 1][2] == "w" else None
            if kind == "r>":
                target = nxt[0] if nxt is not None else ""
                dup = t in (">&", "<&") and re.fullmatch(r"\d+|-", target or "")
                if not dup and not _SAFE_REDIRECT.match(target or ""):
                    writes.append(t)
            if nxt is not None:
                k += 1
        elif cmdpos:
            if re.match(r"^[A-Za-z_][A-Za-z0-9_]*(\[[^\]]*\])?\+?=", r):
                pass  # an assignment: the command word follows
            elif t in PRECOMMAND_WORDS or (t.startswith("-") and words and words[-1][0] in PRECOMMAND_WORDS):
                pass
            else:
                words.append((t, d))
                cmdpos = False
                in_alias = t == "alias"
        k += 1
    return words, writes, aliases


def _verb_word(w, dyn, snap, depth):
    """Whether a command word (quotes removed) is, or may be, a command that deletes, moves, writes or runs code."""
    if dyn or "$" in w:
        return "a command word built at run time (%s)" % w
    name = w[1:] if w.startswith("=") else w
    base = name.rstrip("/").rsplit("/", 1)[-1]
    if base in UNPARSABLE_VERBS:
        return base
    if snap is None or depth > 3 or "/" in name:
        return None
    vals = []
    if name in snap.plain:
        vals.append(snap.plain[name])
    vals += [v for v in snap.alternatives.get(name, ()) if isinstance(v, str)]
    for v in vals:
        m = _VERB_RE.search(v)
        if m:
            return "%s (an alias for %s)" % (name, m.group(1))
        for w2, d2 in _text_commands(v)[0]:
            r = _verb_word(w2, d2, snap, depth + 1)
            if r:
                return "%s (an alias: %s)" % (name, r)
    if name in snap.user_functions:
        body = snap.function_text(name) or ""
        m = _VERB_RE.search(body)
        if m or not body:
            return "%s (a function of yours that may run %s)" % (name, m.group(1) if m else "anything")
    return None


def unparsable_assignment(command):
    """review 5 R1: a command the guard cannot parse that assigns a variable the guard follows (§1.9, a function's
    watched names) or one the command expands later: the name, or None."""
    from .walk import FUNC_WATCHED
    for m in ASSIGN_TEXT_RE.finditer(command):
        name = m.group(1)
        if cmdopts.watched_var(name) or name in FUNC_WATCHED or name in cmdopts.CMD_VARS:
            return name
        if re.search(r"\$\{?(?:\([^)]*\))?[~=^+#]*%s(?![A-Za-z0-9_])" % re.escape(name), command[m.end():]):
            return name
    return None


def refusal_texts(c):
    """The texts of a command that §1.9 refuses in a Studio repository (G1 §1.7: searched for Studio repositories like
    a refused runner's words, review 2 m-a): command-valued variables in effect, and the words of a command whose
    options, git keys or git subcommand options run a command line."""
    out = []
    if not c.words or c.words[0].value is None:
        return out
    pm = "path-modified" in (c.flags or ()) or "PATH" in c.env.set or "PATH" in c.env.unset
    for name, w in c.env.set.items():
        if cmdopts.var_problem(name, w.value if w is not None else None, pm) and w is not None:
            out.append(w.value if w.value is not None else (w.skeleton or ""))
    prog, words = effective(c)
    k = recog.key(prog or "")
    vals = [w.value for w in words]
    g = c.git
    hit = cmdopts.program_option_problem(k, vals) or recog.key(c.prog or "") == "zstyle"
    if not hit and k == "git" and g is not None:
        avals = [w.value for w in g.args]
        hit = any(cmdopts.command_key(key, val) for key, val in g.configs) or (
            g.sub is not None and (cmdopts.git_option_problem(g.sub, avals) or
                                   (g.sub == "clone" and any(cmdopts.command_key(kk, vv)
                                                             for kk, vv in cmdopts.clone_configs(g.args)))))
    if hit:
        out.append(" ".join(w.skeleton for w in c.words[1:]))
    return out


def per_command(ctx, c, infos, sc):
    check_version(ctx, c)
    check_env(ctx, c)
    check_approval(ctx, c)
    check_script(ctx, c)
    check_s2v_results(ctx, c)
    check_git_rules(ctx, c, infos)
    check_gh(ctx, c, infos)
    check_patch(ctx, c, infos, sc)
    check_command_values(ctx, c, infos)


# ---- G1 §1.8: zsh constructs the walk does not model; §1.9: command lines in options and variables ----

CMDLINE_WHY = ("%s runs a command line the guard does not read (%s) in a Studio repository — run that command "
               "directly, one step per call.")
ZSH_WHY = ("%s changes zsh's command, alias, function or option tables in a Studio repository — the guard cannot tell "
           "what later commands run; write the commands directly, one step per call.")


def check_zsh(ctx, scans, infos):
    """In a Studio repository, refused with no Studio term needed (G1 §1.8): writes to zsh's tables, prompt
    expansion that may run `$(…)`, options set by a name the guard cannot read, autoload and zmodload outside their
    allowlists, `zstyle -e`; and command-valued variables set in the call (§1.9)."""
    if not infos:
        return
    for sc in scans:
        by_id = {c.id: c for c in sc.commands}
        for o in sc.opaque:
            ctx.current = by_id.get(o.cmd)
            if o.kind == "zsh-table":
                ctx.deny("G-OPAQUE", ZSH_WHY % o.payload)
            elif o.kind == "prompt-subst":
                ctx.deny("G-OPAQUE", "%s expands a prompt while PROMPT_SUBST may be on, which runs $(…) the guard "
                                     "does not read, in a Studio repository — print the text without prompt "
                                     "expansion." % o.payload)
            elif o.kind == "var-set":
                why = cmdopts.var_problem(o.payload, getattr(o, "value", None), getattr(o, "path_modified", False))
                if why:
                    ctx.deny("G-OPAQUE", CMDLINE_WHY % ("setting " + o.payload, why))
        for c in sc.commands:
            if not c.words or c.words[0].value is None:
                continue
            ctx.current = c
            k = recog.key(c.prog or "")
            vals = [w.value for w in c.words[1:]]
            why = None
            if k in ("setopt", "unsetopt", "emulate") and any(v is None for v in vals):
                why = "%s with a name the guard cannot read" % k
            elif k == "set" and any(v in ("-o", "+o") and (i + 1 >= len(vals) or vals[i + 1] is None)
                                    for i, v in enumerate(vals)):
                why = "set -o with an option name the guard cannot read"
            elif k == "autoload":
                why = cmdopts.autoload_problem(vals)
            elif k == "zmodload":
                why = cmdopts.zmodload_problem(vals)
            elif k == "zstyle" and any(v is None or re.match(r"^-[A-Za-z]*e", v or "") for v in vals[:1]):
                why = "zstyle -e (its value is evaluated as code by zstyle -s)"
            elif k == "zstyle":
                why = cmdopts.zstyle_problem(vals)
            if why:
                ctx.deny("G-OPAQUE", "%s — the guard does not follow it in a Studio repository; run the commands "
                                     "directly, one step per call." % why)
    ctx.current = None


def check_command_values(ctx, c, infos):
    """G1 §1.9: command-valued environment variables in effect, git keys, git routes to configuration and
    command-valued options, and the options of ssh, rsync, tar, zip, sort, man and make."""
    if not infos or not c.words or c.words[0].value is None:
        return
    env = c.env
    pm = "path-modified" in (c.flags or ()) or "PATH" in env.set or "PATH" in env.unset
    for name, w in env.set.items():
        why = cmdopts.var_problem(name, w.value if w is not None else None, pm)
        if why:
            ctx.deny("G-OPAQUE", CMDLINE_WHY % (c.prog or "the command", why))
    prog, words = effective(c)
    k = recog.key(prog or "")
    vals = [w.value for w in words]
    hit = cmdopts.program_option_problem(k, vals)
    if hit:
        ctx.deny("G-OPAQUE", CMDLINE_WHY % (prog, hit))
    g = c.git
    if k != "git" or g is None:
        return
    if env.unknown:
        # m5: `eval`, env --env0-from, a function: what git reads is in effect but unknown (§1.9). (fix20: after a
        # `source` this guard judges nothing — the 0.0.26 rules do, backstop.decide)
        ctx.deny("G-OPAQUE", "git runs with environment variables the guard cannot read (set by `eval`, env "
                             "--env0-from or a shell function that exports or assigns variables) in a Studio "
                             "repository — they may move where git reads its settings, which can run commands.")
    for key, val in g.configs:
        why = cmdopts.command_key(key, val)
        if why:
            ctx.deny("G-OPAQUE", CMDLINE_WHY % ("git -c", why))
    for name in cmdopts.git_env_problems(env.set):
        ctx.deny("G-OPAQUE", "git runs with %s set in a Studio repository — it moves where git reads its settings "
                             "(which can run commands); run git without it." % name)
    run = run_folders(c)
    for name in ("GIT_DIR", "GIT_WORK_TREE"):
        if name not in env.set:
            continue
        w = env.set[name]
        v = w.value if w is not None else None
        inside = v is not None and (os.path.isabs(v) or len(run) == 1) and any(
            _inside(ctx._real(os.path.normpath(v if os.path.isabs(v) else os.path.join(run[0], v))),
                    os.path.realpath(d))
            for ri in infos for d in (ri.worktree, ri.common_dir) if d)
        if not inside:
            ctx.deny("G-OPAQUE", "git runs with %s=%s, a folder outside the Studio repository — git would read "
                                 "settings the guard does not see; run git in the repository itself."
                     % (name, v if v is not None else "…"))
    if g.sub is None:
        return
    avals = [w.value for w in g.args]
    hit = cmdopts.git_option_problem(g.sub, avals)
    if hit:
        ctx.deny("G-OPAQUE", CMDLINE_WHY % ("git " + g.sub, hit))
    if g.sub == "clone":
        for key, val in cmdopts.clone_configs(g.args):
            why = cmdopts.command_key(key, val)
            if why:
                ctx.deny("G-OPAQUE", CMDLINE_WHY % ("git clone", why))
    if g.sub == "config":
        for key, val in cmdopts.config_sets(avals):
            if key in (None, "*"):
                continue  # the hook-key rule refuses those (G-HOOKOFF)
            why = cmdopts.command_key(key, val)
            if why:
                ctx.deny("G-OPAQUE", CMDLINE_WHY % ("git config", why))
        for sec in cmdopts.config_renames(avals):  # M8: the keys of a renamed section move into it
            why = cmdopts.command_section(sec)
            if why:
                ctx.deny("G-OPAQUE", CMDLINE_WHY % ("git config --rename-section",
                                                    "%s holds settings that run commands" % why))


# ---- G1 §1.11: READ_ALLOW programs that write files or run programs ----

EXIF_ALLOW = {"-s", "-a", "-u", "-j", "-json", "-n", "-b", "-x", "-csv", "-l", "-ver", "-ee", "-r", "-f"}
EXIF_VALUE = {"-ext", "--ext", "-d", "-c", "-charset", "-lang"}
EXIF_KNOWN = set("""
-@ -a -api -b -binary -c -coordformat -charset -config -csv -csvdelim -d -dateformat -decimal -delete_original
-diff -duplicates -e -ec -ex -escapehtml -escapexml -echo -echo1 -echo2 -echo3 -echo4 -efile -efile1 -efile2
-efile3 -efile4 -ee -extractembedded -ext -extension -execute -f -forceprint -fixbase -fast -fast2 -fast3 -fast4
-fast5 -fileorder -g -groupheadings -geotag -geosync -geotime -globaltimeshift -h -htmlformat -hex -htmldump -i
-ignore -if -ignoreminorerrors -j -json -k -pause -l -long -latin -lang -list -listw -listf -listr -listwf -listg
-listd -listx -listgeo -m -n -o -out -overwrite_original -overwrite_original_in_place -p -printformat -preserve
-password -progress -q -quiet -r -recurse -restore_original -s -short -veryshort -scanforxmp -sep -separator -sort
-struct -srcfile -stay_open -t -tab -table -tagsfromfile -u -unknown -unknown2 -use -userparam -v -verbose
-validate -ver -w -textout -tagout -wext -wm -writemode -x -xmlformat -exclude -z -zip -common_args -php -plot
-all -allextract -args
""".split())
DOC_EXT = ("md", "txt", "pdf", "png", "jpg", "jpeg", "gif", "webp", "svg", "mp4", "mov", "m4a", "mp3", "wav", "json",
           "yaml", "yml", "srt", "vtt", "html")


def exiftool_problem(vals):
    """Why an exiftool call is not a plain read (an allowlist, review 5 M2), or None."""
    i = 0
    while i < len(vals):
        v = vals[i]
        if v is None:
            return "a word the guard cannot read"
        if not v.startswith("-") or v == "-":
            i += 1
            continue
        lv = v.lower()
        if "=" in v or "<" in v:
            return v
        if lv in EXIF_VALUE:
            # -lang and -charset take a value only when the next word is not an option (M11)
            opt_val = lv in ("-lang", "-charset")
            nxt = vals[i + 1] if i + 1 < len(vals) else None
            i += 1 if opt_val and (nxt is None or nxt.startswith("-")) else 2
            continue
        name = re.sub(r"[0-9:]+$", "", lv.rstrip("+!#"))
        if lv in EXIF_ALLOW or name in ("-s", "-g") or lv.startswith("-list") or re.fullmatch(r"-g[0-9:]*", lv):
            i += 1
            continue
        if name in EXIF_KNOWN or lv in EXIF_KNOWN or v.startswith("--") and v[2:].lower() in ("ext",):
            return v
        i += 1  # a tag name to print (-Duration, -ID3:Title)
    return None


def open_problem(ctx, cmd, words):
    """Why an `open` call is not `open [-R] [-g] [-W] <URL or document>…` (review 3 M2, review 4), or None."""
    opts = True
    for w in words:
        v = w.value
        if v is None:
            return "a word the guard cannot read"
        if opts and v.startswith("-") and v != "-":
            if re.fullmatch(r"-[RgW]+", v):
                continue
            return v
        opts = False
        if re.match(r"^https?://", v):
            continue
        res = resolve_all(ctx, cmd, v)
        for a, real, ri in res:
            if a is None:
                return "%s (a folder the guard cannot tell)" % v
            r = os.path.realpath(a)
            ext = os.path.splitext(r)[1].lower().lstrip(".")
            if ctx.fs.isdir(r) or ext not in DOC_EXT:
                return "%s (not a document: %s)" % (v, os.path.basename(r))
    return None


def _getopt_values(words, value_letters, value_longs, operands=False):
    """A getopt_long reading of `words`: (option, Word, value) for each option that takes a value (short ones in a
    cluster take the rest of it or the next word; long ones `--name=v` or `--name v`, unambiguous abbreviations
    too), and with `operands`, (None, Word, value) for each operand. Other options are flags; `--` ends them."""
    out = []
    i, dd = 0, False
    while i < len(words):
        w = words[i]
        v = w.value
        if dd or v is None or not v.startswith("-") or v == "-":
            if operands:
                out.append((None, w, v))
            i += 1
            continue
        if v == "--":
            dd = True
            i += 1
            continue
        if v.startswith("--"):
            name, eq, val = v.partition("=")
            full = next((n for n in value_longs if cmdopts.long_option(name, (n,))), None)
            if full is not None:
                if eq:
                    out.append((full, w, val))
                elif i + 1 < len(words):
                    out.append((full, words[i + 1], words[i + 1].value))
                    i += 1
            i += 1
            continue
        for c, ch in enumerate(v[1:], 1):
            if ch in value_letters:
                if v[c + 1:]:
                    out.append(("-" + ch, w, v[c + 1:]))
                elif i + 1 < len(words):
                    out.append(("-" + ch, words[i + 1], words[i + 1].value))
                    i += 1
                break
        i += 1
    return out


def _cluster_has(v, letter, value_letters):
    """Whether a short-option cluster sets `letter` before a letter that takes a value."""
    if not v or not v.startswith("-") or v.startswith("--"):
        return False
    for ch in v[1:]:
        if ch == letter:
            return True
        if ch in value_letters:
            return False
    return False


def read_writer_targets(ctx, cmd, prog, words, studio_infos):
    """G1 §1.11: [(Word, value)] the program writes (sort -o, uniq and xxd's second operand, tree -o); its options that
    write or run programs are refused in a Studio repository (G-OPAQUE)."""
    vals = [w.value for w in words]
    out = []
    if prog == "sort":
        # getopt_long: -o FILE in a cluster (`-uo FILE`, `-oFILE`), --output, and its abbreviations (M10)
        for opt, w, v in _getopt_values(words, "kStTo", ("--output", "--key", "--field-separator", "--buffer-size",
                                                          "--temporary-directory", "--parallel", "--batch-size",
                                                          "--compress-program", "--files0-from", "--sort",
                                                          "--random-source")):
            if opt in ("-o", "--output"):
                out.append((w, v))
    elif prog == "uniq":
        ops = [w for opt, w, v in _getopt_values(words, "fsw", ("--skip-fields", "--skip-chars", "--check-chars"),
                                                 operands=True) if opt is None]
        if len(ops) >= 2:
            out.append((ops[1], ops[1].value))
    elif prog == "xxd":
        # xxd reads one option per word (`-c8`, `-c 8`, `-cols 8`)
        takes = ("-c", "-cols", "-g", "-groupsize", "-l", "-len", "-s", "-seek", "-o", "-offset", "-n", "-name",
                 "-R")
        ops, i, dd = [], 0, False
        while i < len(words):
            v = vals[i]
            if not dd and v == "--":
                dd = True
            elif not dd and v in takes:
                i += 1
            elif not dd and v is not None and v.startswith("-") and v != "-":
                pass
            else:
                ops.append(words[i])
            i += 1
        if len(ops) >= 2:
            out.append((ops[1], ops[1].value))
    elif prog == "tree":
        # tree's own reader: each value letter of a cluster takes the next word (`-fo FILE`, `-L 2 -o FILE`)
        i = 0
        while i < len(words):
            v = vals[i]
            if v is not None and v.startswith("-") and not v.startswith("--") and len(v) > 1:
                k = i
                for ch in v[1:]:
                    if ch in "LPIoHT" and k + 1 < len(words):
                        k += 1
                        if ch == "o":
                            out.append((words[k], vals[k]))
                i = k
            elif v is not None and v.startswith("--") and "=" not in v and v in ("--charset", "--filelimit",
                                                                                "--timefmt", "--sort", "--fromfile",
                                                                                "--infile", "--hintro", "--houtro"):
                i += 1
            i += 1
    if studio_infos:
        why = None
        if prog == "exiftool":
            why = exiftool_problem(vals)
        elif prog == "file":
            why = next((v for v in vals if v == "--compile" or _cluster_has(v, "C", "eFfmP")), None)
        elif prog == "ffprobe":
            if "-report" in vals:
                why = "-report"
            elif "FFREPORT" in cmd.env.set or ctx.env.get("FFREPORT"):
                why = "FFREPORT"
        elif prog == "rg":
            why = next((v for v in vals if v and (v in ("--pre", "--pre-glob") or
                                                   v.startswith(("--pre=", "--pre-glob=")))), None)
        elif prog == "open":
            why = open_problem(ctx, cmd, words)
        if why:
            ctx.deny("G-OPAQUE", "%s %s writes files or runs programs the guard does not check in a Studio "
                                 "repository — %s" % (prog, why, "open documents and web pages only" if
                                                     prog == "open" else "read the file with plain options, one "
                                                                         "step per call."))
    return out


# ---- G1 §1.10: programs the guard does not model ----

# programs whose judgement the guard has (their words are not searched by the fallback)
MODELLED = protect.READ_ALLOW | protect.DELETE_PROGS | protect.CREATORS | set(EXTRACT_PROGS) | {
    "mv", "rsync", "dd", "tee", "touch", "mkdir", "chmod", "chown", "truncate", "zip", "gio", "sed", "gsed", "git",
    "gh", "xargs", "parallel", "awk", "gawk", "nawk", "mawk", "find", "gfind", "bfs", "jar", "cmake", "s2v"}
FALLBACK_WRITERS = protect.DELETE_PROGS | protect.CREATORS | {
    "touch", "tee", "dd", "truncate", "chmod", "chown", "sed", "gsed", "perl", "ruby", "osascript", "find", "tar",
    "gtar", "bsdtar", "unzip", "xargs", "sh", "bash", "zsh", "ksh", "dash", "fish", "csh", "tcsh", "git"}
FALLBACK_PIECES = re.compile(r"&&|\|\||>>|[;|&()<>]|[^\s;|&()<>'\"`]+")
FALLBACK_SEPS = (";", "|", "&", "&&", "||", "(")


def unmodelled(ctx, c):
    """True when the command's program is in none of the guard's tables (G1 §1.10)."""
    if not c.words or c.words[0].value is None or c.s2v is not None or c.lock is not None:
        return False
    if "runner-unread" in c.flags or studio_script(ctx, c):
        return False
    from .scanctx import ZSH_BUILTINS
    prog = effective(c)[0]
    k = recog.key(prog)
    return not ((k in MODELLED and k not in protect.READ_WRITERS) or prog in ZSH_BUILTINS or
                recog.interp_family(prog) is not None or runners.lookup(k) is not None or k in runners.REFUSED or
                k in runners.PACKAGE_RUNNERS)


def _fallback_pieces(c):
    """[(piece, command position)] of the literal words after the program."""
    out = []
    prev = None
    for w in c.words[1:]:
        if w.value is None:
            prev = None
            continue
        first = True
        for t in FALLBACK_PIECES.findall(w.value):
            k = recog.key(recog.base(t))
            pos = first or prev in FALLBACK_SEPS or (prev is not None and (
                runners.lookup(prev) is not None or prev in runners.REFUSED or prev in ("nohup", "command", "exec")))
            out.append((t, pos))
            first = False
            prev = k if t not in FALLBACK_SEPS else t
    return out


def _writer_piece(t):
    k = recog.key(recog.base(t))
    return t in (">", ">>") or k in FALLBACK_WRITERS or recog.PY_RE.match(k) or recog.NODE_RE.match(k)


def _studio_piece(ctx, c, t, infos):
    if any(s in protect.TAIL_NAMES for s in t.split("/") if s):
        return True
    for a, real, ri in resolve_all(ctx, c, t):
        if ri is None or not ri.studio or real is None:
            continue
        parts, fold = rel(ctx, ri, real)
        if parts and (_within(parts, [ri.studio_root], fold) or _within(parts, [".claude", "studio"], fold)):
            return True
    return False


def fallback_writes(c):
    """Whether an unmodelled command's words hold a writer piece in command position (its words are then searched for
    Studio repositories, as a refused runner's are)."""
    return any(pos and _writer_piece(t) or t in (">", ">>") for t, pos in _fallback_pieces(c))


def check_fallback(ctx, c, infos):
    """G1 §1.10: in a Studio repository, an unmodelled program whose literal words run a writer on a Studio path (or
    git: today's git rules on the pieces that follow) is refused."""
    pieces = _fallback_pieces(c)
    for i, (t, pos) in enumerate(pieces):
        k = recog.key(recog.base(t))
        if pos and k == "git":
            tail = []
            for t2, _p in pieces[i:]:
                if t2 in FALLBACK_SEPS:
                    break
                tail.append(t2)
            check_synthetic(ctx, c, tail, infos)
            continue
        if not ((pos and _writer_piece(t)) or t in (">", ">>")):
            continue
        hit = next((t2 for t2, _p in pieces[i + 1:] if t2 not in FALLBACK_SEPS and _studio_piece(ctx, c, t2, infos)),
                   None)
        if hit is not None:
            ctx.deny("G-OPAQUE", "%s is a program the guard does not model, and its words run %s on %s in a Studio "
                                 "repository — run the command directly, one step per call." % (c.prog, t, hit))
            return


def check_synthetic(ctx, c, words, infos):
    """`git …` pieces inside an unmodelled program's words: judged with today's git rules in the host's folder."""
    cwds = run_folders(c)
    if not cwds or len(cwds) != 1:
        unknown(ctx, infos, "git run by %s from a folder the guard cannot tell" % c.prog)
        return
    import shlex
    sub = _scan(ctx, " ".join(shlex.quote(x) for x in words), cwds[0], ctx.env, snapshot=None, snapshot_notes=(),
                       terms=None, fs=ctx.fs)
    if sub.status != "ok":
        unknown(ctx, infos, "git run by %s" % c.prog)
        return
    for s in sub.commands:
        ctx.current = s
        check_paths(ctx, s, infos)
        check_git_rules(ctx, s, infos)
    ctx.current = None


# ---- M0d-2: versions, commits, pushes, GitHub API (m0d2-plan §5, §6, §8) ----

def check_version(ctx, cmd):
    """D-M0-3: Studio commands stop when the repository's scripts are another version than the guard's."""
    from . import version
    real = None
    for name in ("state.py", "check_commit.py", "hooks.py", "lock.py", "run_s2v.py", "resolve_assets.py",
                 "check_scope.py"):
        real = studio_script(ctx, cmd, name)
        if real is not None:
            break
    if real is None:
        return
    if os.path.dirname(real) == PLUGIN_SCRIPTS:
        ri = _run_repo(ctx, cmd)
        repo_copy = False
    else:
        ri = ctx.repos.info(ctx.where.git_repo(os.path.dirname(real)))
        repo_copy = True
    if ri is None or not ri.harness:
        return
    why = version.problem(ri.worktree, repo_copy)
    if why:
        ctx.deny("G-VERSION", "%s: %s." % (os.path.basename(real), why))


def _commit_like(g):
    if g.sub == "commit":
        return True
    vals = [w.value for w in g.args]
    return g.sub in commitrule.CONTINUE_SUBS and "--continue" in vals


def check_git_rules(ctx, cmd, infos):
    g = cmd.git
    if g is None or g.sub is None:
        return
    sub = g.sub
    is_commit = _commit_like(g)
    cfg = commitrule.hook_config(cmd)
    if not (is_commit or cfg or sub in ("config", "push") or commitrule.plumbing(sub, g.args)):
        return
    if len(run_folders(cmd)) > 1:
        # review 9 B1: judged in each folder git may run in; one repository is judged once
        pairs = git_targets(ctx, cmd)
        studio = sorted({t[0].worktree for _c, t in pairs if isinstance(t, tuple) and t[0].studio})
        if is_commit and len(studio) > 1:
            ctx.deny("G-COMMIT", "git %s cannot be checked: it may run in any of several Studio repositories (%s) "
                                 "after a folder change that may or may not happen — cd to one literal folder first, "
                                 "in a separate call; %s" % (sub, ", ".join(studio), commitrule.HOOKOFF_TAIL))
            return
        seen = set()
        for cc, t in pairs:
            key = (t[0].worktree, tuple(t[2]), tuple(sorted(t[3].items()))) if isinstance(t, tuple) else \
                ("str", t) if isinstance(t, str) else None
            if key in seen:
                continue
            seen.add(key)
            n = len(ctx.denies)
            check_git_rules(ctx, cc, infos)
            if len(ctx.denies) > n:
                return
        return
    target = git_target(ctx, cmd)
    if isinstance(target, str):
        if infos and (is_commit or sub == "config"):
            ctx.deny("G-HOOKOFF" if "GIT_CONFIG" in target else "G-COMMIT",
                     "git %s cannot be checked (%s) in a Studio repository; %s" % (sub, target, commitrule.HOOKOFF_TAIL))
        return
    if target is None:
        return
    ri, run_cwd, pre, penv = target
    if not ri.studio:
        return
    ctx.touch(ri)
    if cfg:
        ctx.deny("G-HOOKOFF", "git %s %s changes hooks or aliases in a Studio repository; %s"
                 % (cmd.git.sub, cfg, commitrule.HOOKOFF_TAIL))
        return
    if sub == "config":
        key = commitrule.config_write(g.args)
        if key:
            ctx.deny("G-HOOKOFF", "git config %s changes how commits are checked in a Studio repository (hooks, "
                                  "aliases or included config files). If the person wants this setting, they run the "
                                  "command themselves in a terminal; %s" % (key if key != "*" else "(any key)",
                                                                           commitrule.HOOKOFF_TAIL))
        return
    why = commitrule.plumbing(sub, g.args)
    if why:
        ctx.deny("G-PLUMB", "%s — in a Studio repository commits and the index change only through git commit and "
                            "check_commit.py --stage. If this is needed, ask the person to run it in a terminal." % why)
        return
    if sub == "push":
        check_push(ctx, cmd, ri)
        return
    # commits
    env_names = commitrule.hookoff_env(cmd)
    if env_names:
        ctx.deny("G-HOOKOFF", "git %s with %s in a Studio repository turns Studio's pre-commit check off or points git "
                              "elsewhere; %s" % (sub, ", ".join(env_names), commitrule.HOOKOFF_TAIL))
        return
    if not ri.harness:
        return
    opts = commitrule.parse_commit(g.args) if sub == "commit" else commitrule.parse_commit([])
    if opts["dry_run"]:
        return
    extra = {}
    if pre:
        gi = pre.index("--git-dir") + 1 if "--git-dir" in pre else None
        wi = pre.index("--work-tree") + 1 if "--work-tree" in pre else None
        if gi:
            extra["GIT_DIR"] = pre[gi]
        if wi:
            extra["GIT_WORK_TREE"] = pre[wi]
    scope = getattr(ctx.probe, "scope", None)
    mkey = None if scope is None else (scope, ri.worktree, tuple(sorted(extra.items())), repr(sorted(opts.items())))
    nkey = _nested_key(cmd, ("commit", ri.worktree, tuple(sorted(extra.items())), repr(sorted(opts.items()))))
    out = ctx.commit_memo.get(mkey) if mkey is not None else None
    if out is None and nkey is not None:
        out = ctx.nested_memo.get(nkey)
    if out is None:
        # review 17 (C17-4): the same commit in several readings of one command (its folders) is checked once
        # fix20 (P20-4): the 0.0.26 guard's own check (frozen), shared with it within this decision (backstop)
        from . import backstop
        out = backstop.shared_commit(ri.worktree, ctx.env, extra, opts, plugin_scripts=PLUGIN_SCRIPTS)
        if mkey is not None:
            ctx.commit_memo[mkey] = out
        if nkey is not None:
            ctx.nested_memo[nkey] = out
    if out.deny:
        ctx.deny(*out.deny)
        return
    if not out.studio:
        return
    commit_evidence(ctx, cmd, ri, out)


def commit_evidence(ctx, cmd, ri, out):
    from . import approve, proxy, transcript
    from ..commit import okfile
    hook = ctx.hook
    if approve.in_subagent(hook):
        ctx.deny("G-MAIN", "a Studio commit runs only in the main session.")
        return
    sid = hook.get("session_id")
    ok = out.ok
    rv = runner_version(ri)
    from ..hooks import templates as HT
    if rv is None or rv < HT.RUNNER_VERSION:
        ctx.deny("G-COMMIT", "Studio's pre-commit runner in this clone is %s — run \"python3 "
                             ".claude/studio/scripts/hooks.py install\" and ask the person to commit again."
                 % ("missing" if rv is None else "an older version (v%d)" % rv))
        return
    if ok.get("session_id") != sid:
        ctx.deny("G-COMMIT", "commit-ok.json was prepared in another session — stage again (check_commit.py "
                             "--stage) and ask the person again.")
        return
    label = ok.get("label")
    approval = {"tree": out.tree, "head": out.head, "session_id": sid, "answer": label,
                "at": transcript_now()}
    if proxy.active(ctx.env, ri.worktree):
        if ok.get("protected_changes"):
            ctx.deny("G-COMMIT", "this commit changes protected settings (%s) — only a person approves that, not the "
                                 "proxy mode." % ", ".join(c.get("key", "?") for c in ok["protected_changes"]))
            return
        approval.update({"mode": "proxy", "tool_use_id": hook.get("tool_use_id"), "question_index": 0})
        reason = "proxy commit %s" % label
    else:
        line = ok.get("summary")
        try:
            ans = transcript.find(hook, ctx.env)
            # with a summary line (M0f) the question must show it verbatim; it holds tree12, so F9 is not needed
            idx, text, _note = transcript.choose(ans, label, None if line else out.tree[:12])
            if approve.consumed(ri, (sid, ans.tool_use_id, idx)):
                # the record is shared by the repository's worktrees: an answer approves one commit (m1-plan §3.2)
                raise transcript.NoEvidence("consumed")
            if line:
                from ..commit import summary as csum
                if not csum.shown_in(line, text):
                    raise transcript.NoEvidence("summary-not-shown")
            shown = ok.get("values_shown") or []
            if shown:
                from ..commit.summary import first_missing
                miss = first_missing(shown, text)
                if miss:
                    raise transcript.NoEvidence("values-not-shown")  # m1-plan §5.1 (v3 N1)
        except transcript.NoEvidence as e:
            what = "this Studio commit" + (" (the question must contain the line: %s)" % line if line else "")
            extra = ""
            if e.code == "values-not-shown":  # name the first missing line (pilot-1 P4)
                from ..commit.summary import missing_text
                extra = " " + missing_text(miss, "check_commit.py --stage")
            elif ok.get("values_shown"):
                what += " and these lines: %s" % " / ".join(ok["values_shown"][:6])
            ctx.deny("G-EVIDENCE", approve.evidence_text(what, label, e) + extra,
                     suffix=approve.evidence_suffix(e.code))
            return
        approval.update({"mode": "human", "tool_use_id": ans.tool_use_id, "question_index": idx})
        if line:
            approval["summary"] = line
        if ok.get("values_shown"):
            approval["values"] = list(ok["values_shown"])
        reason = "answer %s#%d (%s)" % (ans.tool_use_id, idx, label)
    top = out.top

    def effect():
        okfile.set_approval(top, approval)
        if not ranlog.record(ri.worktree, sid, may_create=True):
            raise OSError("could not record that the guard ran in this session")
    ctx.effects.append(("G-COMMIT", effect))
    add_candidate(ctx, (cmd, "commit", reason))


def runner_version(ri):
    """The version mark of `<git common dir>/studio/pre-commit` (M0f review MINOR-3), None when absent."""
    try:
        with open(os.path.join(ri.common_dir, "studio", "pre-commit"), encoding="utf-8") as f:
            head = f.read(400)
    except (OSError, TypeError):
        return None
    m = re.search(r"studio:hook v(\d+) \S+ Studio's pre-commit runner", head)
    return int(m.group(1)) if m else None


def transcript_now():
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _nested_key(cmd, key):
    """review 19 (C19-2): the memo key of a push / commit check run by a command of a nested string (`sh -c 'git
    push'` repeated), None for any other command. The guard runs nothing, so these checks read the same repository
    for every command of one call: the same worktree, words, options and git environment give the same answer.
    The git command's own environment (prefix assignments, `env …`) is part of the key."""
    if getattr(cmd, "scan_key", None) is None:
        return None
    env = getattr(cmd, "env", None)
    if env is not None and (getattr(env, "unknown", False) or getattr(env, "cleared", False)):
        return None
    sets = tuple(sorted((k, repr(getattr(v, "value", v))) for k, v in (getattr(env, "set", None) or {}).items()))
    unsets = tuple(sorted(getattr(env, "unset", None) or ()))
    return key + (sets, unsets)


def check_push(ctx, cmd, ri):
    from . import web
    if not ri.harness:
        return
    st, data = web.overlay(ri.worktree, ri.config, ctx.env)
    ids = web.internal_items(data)[2] if st == "ok" else set()
    vals = tuple(w.value for w in cmd.git.args)
    nkey = None if None in vals else _nested_key(cmd, ("push", ri.worktree, vals, tuple(sorted(ids))))
    if nkey is not None and nkey in ctx.nested_memo:
        deny, warns = ctx.nested_memo[nkey]
        warns = []  # (shown once)
    else:
        from . import backstop  # fix20 (P20-4): the 0.0.26 check (frozen), shared with it within this decision
        deny, warns = backstop.shared_push(ri.worktree, ctx.env, cmd.git.args, ids)
        if nkey is not None:
            ctx.nested_memo[nkey] = (deny, list(warns))
    if deny:
        ctx.deny("G-PUSH", deny)
    for w in warns:
        ctx.warnings.append("Studio (git push): %s." % w)


APPLY_READONLY = ("--check", "--stat", "--numstat", "--summary")


def _patch_call(cmd):
    """("git-apply" | "git-am" | "patch", [operand words], strip levels or None, directory) or None."""
    g = cmd.git
    if g is not None and g.sub in ("apply", "am"):
        vals = [w.value for w in g.args]
        if g.sub == "apply" and any(v in APPLY_READONLY for v in vals if v):
            return None
        if g.sub == "am" and any(v in ("--abort", "--skip", "--quit", "--show-current-patch") for v in vals if v):
            return None
        levels, directory, files = [1], None, []
        i = 0
        while i < len(g.args):
            w, v = g.args[i], vals[i]
            if v is None:
                files.append(w)
            elif re.match(r"^-p\d+$", v):
                levels = [int(v[2:])]
            elif v == "-p" and i + 1 < len(vals) and (vals[i + 1] or "").isdigit():
                levels = [int(vals[i + 1])]
                i += 1
            elif v.startswith("--directory="):
                directory = v.split("=", 1)[1]
            elif v == "--directory" and i + 1 < len(vals):
                directory = vals[i + 1]
                i += 1
            elif v in ("--exclude", "--include", "-C", "--whitespace") and i + 1 < len(vals):
                i += 1
            elif not v.startswith("-"):
                files.append(w)
            i += 1
        return ("git-" + g.sub, files, levels, directory)
    if cmd.prog in ("patch", "gpatch"):
        words = cmd.words[1:]
        vals = [w.value for w in words]
        levels, directory, files, operands = None, None, [], []
        i = 0
        while i < len(words):
            v = vals[i]
            if v is None:
                operands.append(words[i])
            elif re.match(r"^-p\d+$", v):
                levels = [int(v[2:])]
            elif v.startswith("--strip="):
                levels = [int(v.split("=", 1)[1])] if v.split("=", 1)[1].isdigit() else None
            elif v in ("-p", "--strip") and i + 1 < len(vals):
                levels = [int(vals[i + 1])] if (vals[i + 1] or "").isdigit() else None
                i += 1
            elif v in ("-i", "--input") and i + 1 < len(vals):
                files.append(words[i + 1])
                i += 1
            elif v.startswith("--input="):
                files.append(model_word(v.split("=", 1)[1]))
            elif v in ("-d", "--directory") and i + 1 < len(vals):
                directory = vals[i + 1]
                i += 1
            elif v.startswith("--directory="):
                directory = v.split("=", 1)[1]
            elif v in ("-o", "--output", "-r", "--reject-file", "-B", "-z", "-D", "-F", "--fuzz", "-V"):
                i += 1
            elif not v.startswith("-"):
                operands.append(words[i])
            i += 1
        if len(operands) >= 2:
            files.append(operands[1])  # patch [options] [originalfile [patchfile]]
        return ("patch", files, levels, directory)
    return None


def model_word(text):
    from .model import Word
    return Word.lit(text)


def check_patch(ctx, cmd, infos, sc):
    """MAJOR-1 (M0f review): the files a patch tool writes, judged like any other write in a Studio repository."""
    if not infos:
        return
    call = _patch_call(cmd)
    if call is None:
        return
    from . import patchtargets as PT
    tool, files, levels, directory = call
    run = run_folders(cmd) or [None]
    cwd = run[0] if len(run) == 1 else None
    texts = []
    stdin = [r for r in cmd.redirs if r.mode in ("read", "heredoc", "herestring") and r.fd in (None, "0")]
    if not files:
        if stdin:
            r = stdin[0]
            if r.mode in ("heredoc", "herestring"):
                if r.body_dynamic or r.body is None:
                    ctx.deny("G-PROT", "%s reads a patch the guard cannot read (a here-document with expansions)."
                             % tool)
                    return
                texts.append(r.body)
            else:
                files = [r.target] if r.target is not None else [model_word("")]
        else:
            ctx.deny("G-PROT", "%s reads its patch from a pipe or the terminal, which the guard cannot read — save it "
                               "to a file and apply that file." % tool)
            return
    for w in files:
        if w is None or w.value is None or w.value in ("-", ""):
            ctx.deny("G-PROT", "%s applies a patch the guard cannot read (%s)." % (tool, getattr(w, "raw", "?")))
            return
        p = w.value if os.path.isabs(w.value) else (os.path.join(cwd, w.value) if cwd else None)
        if p is None or not ctx.fs.exists(p):
            ctx.deny("G-PROT", "%s applies %s, which the guard cannot read." % (tool, w.value))
            return
        try:
            if os.path.getsize(p) > PT.MAX:
                ctx.deny("G-PROT", "%s applies %s, larger than the guard reads (64 KB) — split it." % (tool, w.value))
                return
            with open(p, "rb") as f:
                texts.append(f.read(PT.MAX).decode("utf-8", "replace"))
        except OSError:
            ctx.deny("G-PROT", "%s applies %s, which the guard cannot read." % (tool, w.value))
            return
    tops = []
    if tool.startswith("git-"):
        for _cc, t in git_targets(ctx, cmd):
            if isinstance(t, tuple) and t[0].worktree not in tops:
                tops.append(t[0].worktree)
    found = [(t, PT.targets(t)) for t in texts]
    if any(t.strip() for t in texts) and not any(ts for _t, ts in found):
        ctx.deny("G-PROT", "%s applies a patch whose target files the guard cannot read (no diff headers it "
                           "knows) — apply a unified or git diff." % tool)
        return
    for text, tlist in found:
        for path, op, stripped in tlist:
            lv = levels if levels is not None else list(range(0, max(1, len(path.split("/")))))
            names = PT.candidates(path, lv) if stripped else [path]
            for name in names:
                if directory:
                    name = directory.rstrip("/") + "/" + name
                values = [name]
                if not os.path.isabs(name):
                    values += [os.path.join(top, name) for top in tops]
                for v in values:
                    check_target(ctx, cmd, model_word(v), v, "delete-file" if op == "delete" else "write", infos)


def check_gh(ctx, cmd, infos):
    if cmd.prog != "gh" or not infos:
        return
    argv = [w.value for w in cmd.words[1:]]
    if not argv or argv[0] != "api":
        return
    sps = set([".claude/studio", ".claude/agents/std-"])
    for ri in infos:
        if ri.studio:
            sps.add(ri.studio_root)
    why = commitrule.gh_api(argv, sorted(sps))
    if why:
        ctx.deny("G-PLUMB", "%s — Studio files reach a repository only through Studio's commit checks. Ask the person."
                 % why)


def check_out_of_repo(ctx, c):
    for wc, files in runner_files(c):
        for w, _op in files:
            for a, real, ri in resolve_all(ctx, wc, w.value):
                if real is not None and is_owner_json(real) and (out_hit(ctx, real, "read") or "/.work/op.lock.d/" in real):
                    ctx.deny("G-OUT", "reading %s (a lock owner record with its token) is not allowed — use "
                                      "\"python3 .claude/studio/scripts/lock.py status\"." % w.value)
    for w, vals in candidates(c):
        for v in vals:
            if not looks_like_path(v, c, ctx):
                continue
            for a, real, ri in resolve_all(ctx, c, v):
                if real is not None and is_owner_json(real) and (out_hit(ctx, real, "read") or "/.work/op.lock.d/" in real):
                    ctx.deny("G-OUT", "reading %s (a lock owner record with its token) is not allowed — use "
                                      "\"python3 .claude/studio/scripts/lock.py status\"." % v)


FED_MAX = 64 * 1024
# programs whose arguments are paths they delete, move or write: only these are judged by fed input
FED_WRITERS = protect.DELETE_PROGS | {"mv", "cp", "ln", "rsync", "tee", "install", "gcp", "trash"}
# readers that pass file lines on; the value says which arguments are not files
READER_SKIP = {"cat": (), "tac": (), "head": ("-n", "-c"), "tail": ("-n", "-c"), "sort": ("-k", "-t", "-o"),
               "uniq": (), "cut": ("-d", "-f", "-c", "-b"), "grep": ("-e", "-f", "-m", "-A", "-B", "-C"),
               "egrep": ("-e", "-f"), "rg": ("-e", "-f", "-g", "-m", "-A", "-B", "-C", "-t", "-T"),
               "sed": ("-e", "-f"), "awk": ("-F", "-v", "-f"), "jq": ("--arg", "--argjson", "-f")}
PATTERN_FIRST = {"grep", "egrep", "rg", "sed", "awk", "jq"}  # the first operand is a pattern/program


def reader_files(c):
    """The input files a reader command passes on (patterns, programs and option values skipped)."""
    prog = c.prog
    if prog not in READER_SKIP:
        return []
    takes = READER_SKIP[prog]
    argv = [w.value for w in c.words[1:]]
    out, i, pattern_given = [], 0, False
    if prog in PATTERN_FIRST and any(a in ("-e", "-f") or (a and a.startswith(("-e", "--regexp", "--file", "-f")))
                                     for a in argv if a and prog not in ("awk", "jq")):
        pattern_given = True
    if prog == "awk" and "-f" in argv:
        pattern_given = True
    first_operand = True
    while i < len(argv):
        a = argv[i]
        if a is None:
            out.append(None)
            i += 1
            continue
        if a in takes:
            i += 2
            continue
        if a.startswith("-") and a != "-":
            i += 1
            continue
        if first_operand and prog in PATTERN_FIRST and not pattern_given:
            first_operand = False
            i += 1
            continue
        first_operand = False
        out.append(a)
        i += 1
    return out


def _span_in(inner, outer):
    return inner.span and outer.span and outer.span[0] <= inner.span[0] and inner.span[1] <= outer.span[1]


def statement_start(raw, pos):
    head = raw[:pos]
    cut = max(head.rfind(";"), head.rfind("\n"), head.rfind("&&"), head.rfind("||"))
    return cut + 1 if cut >= 0 else 0


def fed_inputs(sc, cmd, raw=""):
    """(file, cwd) that actually feed `cmd`: its stdin redirect, `$(cat F)` in its own words, the pipeline
    readers before an xargs/parallel, xargs -a / parallel ::::, and a while/for loop's input."""
    out = []
    cwd = (cmd.cwds or [None])[0]  # redirects: the shell's folder
    run = (run_folders(cmd) or [None])[0]  # the program's own file arguments: where it runs (M1)
    for r in cmd.redirs:
        if r.mode == "read" and r.fd in (None, "0") and r.target is not None:
            out.append((r.target.value, cwd))
    for c in sc.commands:
        if c is cmd:
            continue
        if "cmdsubst" in c.ctx and _span_in(c, cmd) and any(w.value is None for w in cmd.words):
            out += [(f, (run_folders(c) or [None])[0]) for f in reader_files(c)]
    argv = [w.value for w in cmd.words]
    if cmd.prog in ("xargs", "parallel"):
        for i, v in enumerate(argv):
            if v in ("-a", "--arg-file") and i + 1 < len(argv):
                out.append((argv[i + 1], run))
            elif v is not None and v.startswith("--arg-file="):
                out.append((v.split("=", 1)[1], run))
        if cmd.prog == "parallel" and "::::" in argv:
            for v in argv[argv.index("::::") + 1:]:
                if v in (":::", "::::"):
                    break
                out.append((v, run))
        if "pipeline" in cmd.ctx and cmd.span:
            start = statement_start(raw, cmd.span[0])
            for c in sc.commands:
                if c is not cmd and "pipeline" in c.ctx and c.span and start <= c.span[0] and c.span[1] <= cmd.span[0] and \
                        not ("cmdsubst" in c.ctx and not _span_in(c, cmd)):
                    out += [(f, (run_folders(c) or [None])[0]) for f in reader_files(c)]
                    for r in c.redirs:
                        if r.mode == "read" and r.fd in (None, "0") and r.target is not None:
                            out.append((r.target.value, (c.cwds or [cwd])[0]))
    if "loop" in cmd.ctx:
        for c in sc.commands:
            if "compound-redirect" in c.ctx and c.span and cmd.span and c.span[0] <= cmd.span[0]:
                for r in c.redirs:
                    if r.mode == "read" and r.target is not None:
                        out.append((r.target.value, (c.cwds or [cwd])[0]))
            if "cmdsubst" in c.ctx and c.span and cmd.span and c.span[1] <= cmd.span[0]:
                out += [(f, (run_folders(c) or [None])[0]) for f in reader_files(c)]
    return [(v, c) for v, c in out if v is None or not (v.startswith("/dev/") or v == "-")]


def read_fed(ctx, value, cwd):
    """(text, state): state "ok", "missing" (the command fails anyway) or "unreadable"."""
    if value is None:
        return None, "unreadable"
    p = value if os.path.isabs(value) else (os.path.join(cwd, value) if cwd else None)
    if p is None:
        return None, "unreadable"
    if not os.path.lexists(p):
        return None, "missing"
    try:
        with open(p, "rb") as f:
            data = f.read(FED_MAX)
    except OSError:
        return None, "unreadable"
    return data.decode("utf-8", "replace"), "ok"


def check_fed(ctx, cmd, sc, terms, op, label, feeder=None):
    """Paths the command takes from files: deny when a line, resolved against the command's cwd, is a
    protected item. Patterns and file bodies' words are not reasons by themselves."""
    target = feeder or cmd
    for value, cwd in fed_inputs(sc, target, getattr(ctx, "command", "")):
        text, state = read_fed(ctx, value, cwd)
        if state == "missing":
            continue
        if state == "unreadable":
            ctx.deny("G-OPAQUE", "%s takes paths from %s, which the guard cannot read — run the commands directly on "
                                 "literal paths." % (label, value or "a file named by a variable"))
            return True
        for line in text.splitlines()[:1000]:
            line = line.strip()
            if not line or "\x00" in line or len(line) > 4096:
                continue
            for a, real, ri in resolve_all(ctx, cmd, line):
                if ri is None or not ri.studio or real is None:
                    continue
                parts, fold = rel(ctx, ri, real)
                if parts is None:
                    continue
                tid = protect.delete_hits(parts, ri.studio_root, fold, is_dir=ctx.fs.isdir(real)) if op == "delete" \
                    else protect.classify(parts, ri.studio_root, fold)
                if tid:
                    ctx.deny("G-OPAQUE", "%s takes %s from %s — a protected Studio path." % (label, line, value))
                    return True
    return False


def template_op(prog):
    base = os.path.basename(prog or "")
    if base in protect.DELETE_PROGS or base == "mv":
        return "delete"
    if base in FED_WRITERS:
        return "write"
    return None


def check_dynamic_writers(ctx, sc, terms, infos):
    """Deleting/moving/path-writing commands whose arguments are not literal (loop variables, `$(cat F)`)."""
    for c in sc.commands:
        prog, words = effective(c)
        op = template_op(prog)
        if op is None or c.lock is not None or studio_script(ctx, c):
            continue
        if not any(w.value is None for w in words):
            continue
        ctx.current = c
        check_fed(ctx, c, sc, terms, op, prog)
    ctx.current = None


def check_parallel_args(ctx, cmd, infos):
    """`parallel <template> ::: args`: the arguments are the template's."""
    argv = [w.value for w in cmd.words]
    if ":::" not in argv:
        return
    i = argv.index(":::")
    tpl = [v for v in argv[1:i] if v is not None and not v.startswith("-")]
    base = os.path.basename(tpl[0]) if tpl else ""
    if base in protect.DELETE_PROGS or base == "mv":
        op = "delete"
    elif base in protect.READ_ALLOW and base not in ("find", "bfs"):
        return
    else:
        op = "write"
    for w in cmd.words[i + 1:]:
        if w.value in (":::", "::::"):
            break
        check_target(ctx, cmd, w, w.value, op, infos)


def upstream_args(ctx, cmd):
    """Literal arguments of the pipeline commands before this one (patterns and programs of readers left out)."""
    sc = getattr(ctx, "scan", None)
    if sc is None or cmd is None or not cmd.span:
        return upstream_text(ctx, cmd)
    seg_start = cmd.span[0] - len(upstream_text(ctx, cmd))
    out = []
    for c in sc.commands:
        if c is cmd or not c.span or c.span[0] < seg_start or c.span[1] > cmd.span[0]:
            continue
        if c.prog in READER_SKIP:
            out += [f for f in reader_files(c) if f]
        else:
            out += [w.value for w in c.words[1:] if w.value]
        out += [r.target.value for r in c.redirs if r.target is not None and r.target.value]
    return "\n".join(out)


def upstream_text(ctx, cmd):
    """The raw text of the statement before this command (the pipeline that feeds it)."""
    raw = getattr(ctx, "command", "") or ""
    if cmd is None or not cmd.span:
        return raw
    end = cmd.span[0]
    head = raw[:end]
    cut = max(head.rfind(";"), head.rfind("\n"), head.rfind("&&"), head.rfind("||"))
    return head[cut + 1:] if cut >= 0 else head


def studio_related(ctx, cmd, infos):
    if cmd is None:
        return True
    for d in cmd.cwds or []:
        for ri in infos:
            p = protect.rel_parts(d, ri.worktree, False)
            if p is not None and (p[:1] == [ri.studio_root] or p[:2] == [".claude", "studio"]):
                return True
    if cmd.s2v is not None or studio_script(ctx, cmd):
        return True
    return False


def check_opaque(ctx, o, cmd, terms, infos, src_notes):
    if o.kind in ("runner", "zsh-table", "prompt-subst", "var-set"):
        return  # refused in check_shell_strings and check_zsh (G1 §1.2, §1.8, §1.9)
    if o.kind == "unknown-command":
        name = (o.payload or "").split(" ")[0]
        ctx.deny("G-UNKNOWN", "\"%s\" is not a command on PATH, a builtin or a known alias/function, and the shell "
                              "snapshot could not be read fully — write the real command name." % name, src_notes)
        return
    if o.kind == "ambiguous-alias":
        name = (o.payload or "").split(":")[0]
        ctx.deny("G-AMBIG", "alias \"%s\" has too many different meanings across recent shell snapshots — write the "
                            "real command." % name, src_notes)
        return
    if o.kind in ("xargs", "parallel"):
        # the template runs on input the guard cannot see; a reading template is harmless
        tpl = (o.payload or "").split(" ")[0]
        if tpl and os.path.basename(tpl) in protect.READ_ALLOW and tpl not in ("find", "bfs", "echo", "printf"):
            return
        if cmd is not None and o.kind == "parallel":
            check_parallel_args(ctx, cmd, infos)
        top = template_op(tpl)
        if cmd is not None and top is not None and check_fed(ctx, cmd, ctx.scan, terms, top, o.kind):
            return
        upstream = upstream_args(ctx, cmd)
        uhits = terms.find(upstream)
        if uhits or studio_related(ctx, cmd, infos):
            what = ("the input mentions %s" % uhits[0].term) if uhits else "it runs in a Studio folder"
            ctx.deny("G-OPAQUE", "%s feeds paths the guard cannot see into \"%s\", and %s — run the commands "
                                 "directly on literal paths." % (o.kind, tpl or "?", what), src_notes)
        return
    if o.kind == "find-exec" and cmd is not None:
        tpl = (o.payload or "").split(" ")[0]
        if tpl in protect.READ_ALLOW and tpl not in ("find", "bfs"):
            return  # judged as the template command
    if o.kind == "script":
        if cmd is not None and studio_script(ctx, cmd) is not None:
            return  # Studio's own scripts (P-WIRE protected) are not opaque, even in a temporary sandbox (m0d1b Q8)
        cls = o.path_class or []
        work = False
        if o.path:
            for ri in infos:
                parts = protect.rel_parts(o.path, ri.worktree, False)
                if parts and parts[:1] == [ri.studio_root] and "work" in parts[1:-1]:
                    work = True
        if not (work or "tmp" in cls or "scratch" in cls):
            return
    hits = terms.find(o.payload) if o.payload is not None else []
    lit_hit = None
    if cmd is not None:
        for lit in o.literals or []:
            if "/" not in lit:
                continue
            for a, real, ri in resolve_all(ctx, cmd, lit):
                if ri is not None and ri.studio and real is not None:
                    parts, fold = rel(ctx, ri, real)
                    if parts is not None and protect.classify(parts, ri.studio_root, fold, include_local=True):
                        lit_hit = lit
    sources = messages.alias_sources(cmd) if cmd is not None else []
    if hits or lit_hit:
        what = hits[0].term if hits else lit_hit
        ctx.deny("G-OPAQUE", "%s runs code the guard cannot read, and it mentions %s — run the commands directly so "
                             "they can be checked." % (o.kind, what), sources + src_notes,
                 suffix=messages.NONSTOP if file_work(o, cmd, hits, lit_hit) else None)
    elif o.hits_unknown and studio_related(ctx, cmd, infos):
        ctx.deny("G-OPAQUE", "%s runs code the guard cannot read in a Studio context — run the commands directly."
                 % o.kind, sources + src_notes)


INTERP_KINDS = ("interp-inline", "stdin-interp", "heredoc-interp", "herestring-interp")


def file_work(o, cmd, hits, lit_hit):
    """fix-0025 §2.1: interpreter code (not a shell's) whose first hit is a Studio path or a protected name (or, with
    no term hit, a literal protected path) — file work the Read/Write/Edit tools do under the guard. A STUDIO_WORDS
    hit anywhere (state.py, s2v, S2V_*, …) means the code runs Studio commands: INV9."""
    if o.kind not in INTERP_KINDS or cmd is None or recog.interp_family(cmd.prog) in (None, "shell") \
            or recog.key(cmd.prog) == "osascript":  # AppleScript runs programs and apps: not file work
        return False
    if any(h.kind == "word" for h in hits):
        return False
    return bool(hits or lit_hit)  # the other hit kinds are "path" and "name"


def decide_file(ctx, tool, ti):
    key = "notebook_path" if tool == "NotebookEdit" else "file_path"
    path = ti.get(key) or ti.get("file_path") or ti.get("notebook_path")
    if not isinstance(path, str) or not path:
        return
    judge_file_path(ctx, path, tool, ti)
    if ctx.denies or "agent_id" not in ctx.hook:
        return
    # 0.0.28 §1.2: a role writing its own output files (roleout.TABLE) — an allow candidate, never a deny
    try:
        r = ctx.where.resolve(path, ctx.cwd)
        ri = ctx.repos.info(r.repo) if r is not None and r.real is not None and r.repo is not None else None
        if ri is None or not ri.harness or ri.config_error or not ri.studio:
            return
        parts, fold = rel(ctx, ri, r.real)
    except limits.LimitExceeded:
        return  # no allow; the checks above already judged the write
    from . import roleout
    if parts is None or protect.classify(parts, ri.studio_root, fold) is not None:
        return
    reason = roleout.owned(ctx.hook, tool, path, ri.worktree, ri.studio_root)
    if reason:
        add_candidate(ctx, (None, "work", reason))


def judge_file_path(ctx, path, tool, ti, mcp=False):
    r = ctx.where.resolve(path, ctx.cwd)
    if r is None or r.abs is None:
        return
    if out_hit(ctx, r.real, "write"):
        ctx.deny("G-OUT", "%s %s (Studio's per-user files or the machine lock) — only Studio's scripts change it."
                 % ("writing" if not mcp else "this tool touches", path))
        return
    ri = ctx.repos.info(r.repo) if r.repo is not None else None
    cwd_ri = ctx.repos.info(ctx.where.git_repo(ctx.cwd)) if ctx.fs.exists(ctx.cwd) else None
    if cwd_ri is not None and cwd_ri.studio and user_config(ctx, r.real):
        ctx.deny("G-HOOKOFF", "%s %s (git's or ssh's own settings, which can run commands) from a Studio repository; %s"
                 % ("writing" if not mcp else "this tool touches", path, commitrule.HOOKOFF_TAIL))
        return
    h = hookfiles.hit(ri, r.real, "write", r.real is not None and ctx.where.case_insensitive(r.real))
    if h and h[1] == "gitconfig":
        ctx.deny("G-HOOKOFF", "%s %s (git's settings of a Studio repository) — change settings with git config; %s"
                 % ("writing" if not mcp else "this tool touches", path, commitrule.HOOKOFF_TAIL))
        return
    if h:
        if h[1] != "shared" or mcp or tool not in ("Write", "Edit", "MultiEdit"):
            ctx.deny("G-PROT", "%s %s, %s." % ("writing" if not mcp else "this tool touches", path, HOOK_WHY))
            return
        new = new_text(r.real, tool, ti)
        if new is not _REJECTED and not hookfiles.shared_edit_ok(h[0], new):
            ctx.deny("G-PROT", "%s %s removes or changes Studio's \"studio:hook\" block (%s) — edit only the other "
                               "lines; the block is Studio's pre-commit hook." % (tool, path, HOOK_WHY))
            return
    if ri is None or not ri.studio:
        return
    ctx.touch(ri)
    parts, fold = rel(ctx, ri, r.real)
    if parts is None:
        return
    tid = protect.classify(parts, ri.studio_root, fold)
    if tid is None:
        return
    if tid == "P-CONF" and not mcp:
        verdict = config_change(ctx, ri, r.real, tool, ti)
        if verdict is None:
            return
        ctx.deny("G-PROT", "%s changes protected keys of .claude/studio/config.json (%s) — only the person changes "
                           "them (/std config)." % (tool, verdict))
        return
    _i, _p, cls, who = protect.BY_ID[tid]
    hint = " Write character.yaml.draft instead; a person moves it." if tid == "P-CHAR" else (
        " Write CREDITS.draft.yaml instead." if tid == "P-CRED" else "")
    ctx.deny("G-PROT", "%s %s (%s) — only %s may change it.%s" % ("writing" if not mcp else "this tool touches", path,
                                                                 cls, who, hint))


_REJECTED = object()  # an edit Claude Code itself rejects (no match, several matches)


def new_text(real, tool, ti):
    """The file's content after a Write/Edit/MultiEdit (None: unreadable edit; _REJECTED: the tool fails)."""
    if tool == "Write":
        c = ti.get("content")
        return c if isinstance(c, str) else None
    try:
        with open(real, encoding="utf-8", errors="surrogateescape") as f:
            text = f.read()
    except OSError:
        return _REJECTED
    edits = ti.get("edits") if tool == "MultiEdit" else [ti]
    for e in edits or []:
        old, new = e.get("old_string"), e.get("new_string")
        if not isinstance(old, str) or not isinstance(new, str):
            return None
        cnt = text.count(old)
        if cnt == 0 or (cnt > 1 and not e.get("replace_all")):
            return _REJECTED
        text = text.replace(old, new) if e.get("replace_all") else text.replace(old, new, 1)
    return text


def config_change(ctx, ri, real, tool, ti):
    """None when no protected key changes; otherwise a short reason."""
    try:
        with open(real, encoding="utf-8") as f:
            current_text = f.read()
    except OSError:
        current_text = None
    if tool == "Write":
        new_text = ti.get("content")
    elif tool in ("Edit", "MultiEdit"):
        if current_text is None:
            return None
        edits = ti.get("edits") if tool == "MultiEdit" else [ti]
        new_text = current_text
        for e in edits or []:
            old, new = e.get("old_string"), e.get("new_string")
            if not isinstance(old, str) or not isinstance(new, str):
                return "an edit the guard cannot read"
            cnt = new_text.count(old)
            if cnt == 0 or (cnt > 1 and not e.get("replace_all")):
                return None  # Claude Code rejects this edit itself
            new_text = new_text.replace(old, new) if e.get("replace_all") else new_text.replace(old, new, 1)
    else:
        return "not a JSON edit"
    try:
        new = json.loads(new_text) if isinstance(new_text, str) else None
    except ValueError:
        return "the new content is not JSON"
    if not isinstance(new, dict):
        return "the new content is not a JSON object"
    try:
        cur = json.loads(current_text) if current_text else {}
    except ValueError:
        cur = {}
    if not isinstance(cur, dict):
        cur = {}
    changed = sorted(k for k in ri.protected_keys if cur.get(k) != new.get(k))
    return ", ".join(changed) if changed else None


def mcp_paths(obj, depth=0, out=None):
    """Path-like values in (nested) MCP arguments, depth ≤ 4."""
    out = [] if out is None else out
    if depth > 4 or len(out) > MAX_CANDIDATES:
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            kl = str(k).lower()
            if kl in MCP_PATH_KEYS and isinstance(v, str):
                out.append(v)
            elif kl in MCP_LIST_KEYS and isinstance(v, list):
                out.extend(x for x in v if isinstance(x, str))
            if isinstance(v, (dict, list)):
                mcp_paths(v, depth + 1, out)
    elif isinstance(obj, list):
        for v in obj:
            if isinstance(v, (dict, list)):
                mcp_paths(v, depth + 1, out)
    return out


def decide_mcp(ctx, ti):
    if not isinstance(ti, dict):
        return
    found = mcp_paths(ti)
    for p in found[:MAX_CANDIDATES]:
        judge_file_path(ctx, p, "mcp", ti, mcp=True)


def decide_g1(hook, env, fs=None, probe=None, snapshot_loader=None, run_finish=True):
    """This guard alone: (Deny | None, Context, complete). Internal errors deny (closed side). `run_finish` False: no
    evidence writes and no allow (backstop.decide runs the one finish). `complete` is False when the checks stopped
    early (a limit outside a Studio context passes on what was found so far): then no finish of this guard runs
    (fix20, P20-2)."""
    ctx = Context(hook, env, fs=fs, probe=probe, snapshot_loader=snapshot_loader)
    try:
        deny, ctx = _decide(ctx, hook, run_finish)
        return deny, ctx, True
    except limits.LimitExceeded as e:
        return _limit_exceeded(ctx, hook, e) + (False,)
    except Exception as e:  # noqa: BLE001
        return _internal_error(ctx, e) + (False,)


def finish_g1(ctx, hook):
    """This guard's finish after backstop.decide chose it, in the same handlers as its decision (fix20, P20-7)."""
    try:
        finish(ctx)
    except limits.LimitExceeded as e:
        return _limit_exceeded(ctx, hook, e)[0]
    except Exception as e:  # noqa: BLE001
        return _internal_error(ctx, e)[0]
    return ctx.denies[0] if ctx.denies else None


def _limit_exceeded(ctx, hook, e):
    # a bound of the checks (file-system calls, time) ran out while judging: refused in a Studio context, but not
    # a bug (C-m4); outside one, the denies found so far decide (review 2 conformance, MINOR 2)
    if studio_context(ctx, hook) or (not getattr(ctx, "collected", False) and may_name_repo_hook(ctx, hook)):
        ctx.denies.insert(0, Deny("G-LIMIT", "the command needs more checks than the guard's limits allow (%s) — "
                                             "split it into simpler commands, one step per call." % e.kind))
    return (ctx.denies[0] if ctx.denies else None), ctx


def _internal_error(ctx, e):
    ctx.denies.insert(0, Deny("G-ERR", "internal guard error (%s) — tell the user; this is a bug in the guard."
                              % type(e).__name__))
    return ctx.denies[0], ctx


LIMIT_PATHISH_RE = re.compile(r"[/~$`*?\[{\\]|\.\.")
FOLDER_WORDS = ("cd", "chdir", "pushd", "popd")
# review 4 R1, R4: words that set code zsh runs later by name (hooks, traps, NULLCMD, the function table)
HOOK_WORDS = ("trap", "chpwd", "chpwd_functions", "precmd_functions", "preexec_functions", "periodic_functions",
              "zshexit_functions", "command_not_found_handler", "NULLCMD", "READNULLCMD", "functions")


def may_name_repo(ctx, text, depth=0, seen=()):
    """review 3 B1/B-1: whether text the guard could not search to its end may still name a Studio repository: any
    path piece (`/`, `~`, `..`), any expansion, wildcard, brace or backslash, a folder change, a snapshot alias whose
    text may, a snapshot function that may change folder or that the guard cannot read (or no snapshot to tell), or a
    word naming a folder in the working folder."""
    if not isinstance(text, str) or LIMIT_PATHISH_RE.search(text) or depth > 3:
        return True
    words = {w for w in re.split(r"[\s;&|()<>=:,]+", re.sub(r"['\"]", "", text)) if w}
    if len(words) > 4096:
        return True
    snap = getattr(ctx, "snap", None)
    if snap is None:
        return True  # any word may be an alias the guard cannot read
    from .walk import snapshot_function_effects
    for w in words:
        if w in FOLDER_WORDS or w in snap.global_aliases or w in HOOK_WORDS or w.startswith("TRAP"):
            return True
        alias = list(snap.alternatives.get(w) or []) + ([snap.plain[w]] if w in snap.plain else [])
        if w not in seen and any(not isinstance(a, str) or may_name_repo(ctx, a, depth + 1, set(seen) | {w})
                                 for a in alias):
            return True
        if w in snap.user_functions:
            sctx = type("FuncCtx", (), {})()
            sctx.snapshot, sctx.env, sctx.fs, sctx.budget = snap, ctx.env, FS(), limits.Budget()
            eff = snapshot_function_effects(sctx, w)
            if eff is None or eff["cwd"]:
                return True
        for v in (w, w[2:] if w.startswith("-") and len(w) > 2 else None):
            try:
                if v and os.path.isdir(os.path.join(ctx.cwd, v)):
                    return True
            except (OSError, ValueError):
                return True
    return False


def may_name_repo_hook(ctx, hook):
    """may_name_repo for the call's input: a Bash command, or any other tool's arguments as text."""
    ti = hook.get("tool_input") or {}
    if hook.get("tool_name") == "Bash" and isinstance(ti, dict) and isinstance(ti.get("command"), str):
        return may_name_repo(ctx, ti["command"])
    return may_name_repo(ctx, json.dumps(ti))


def studio_context(ctx, hook):
    """Whether the call involves a Studio repository (found so far) or names Studio's per-user files or the lock."""
    if getattr(ctx, "infos", None) or ctx.touched:
        return True
    ctx.fs.max_calls = ctx.fs.calls + 200  # the few checks below, after the limits ran out
    try:
        ri = ctx.repos.info(ctx.where.git_repo(ctx.cwd)) if os.path.isdir(ctx.cwd) else None
    except Exception:  # noqa: BLE001 — the limits ran out: a folder the guard cannot read is a Studio context
        return True
    if ri is not None and ri.studio:
        return True
    text = json.dumps(hook.get("tool_input") or {})
    return any(item and (item in text or (kind != "transcripts" and os.path.basename(item.rstrip("/")) in text))
               for item, kind in ctx.out_items)


def _decide(ctx, hook, run_finish=True):
    tool = hook.get("tool_name") or ""
    ti = hook.get("tool_input") or {}
    from . import auditor
    if auditor.is_auditor(hook):  # the external auditor only reads (J46), whatever else would allow
        auditor.judge(ctx, tool, ti)
        if ctx.denies:
            return ctx.denies[0], ctx
    if tool == "Bash":
        cmd = ti.get("command")
        if isinstance(cmd, str):
            decide_bash(ctx, cmd)
    elif tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        decide_file(ctx, tool, ti)
    elif tool in ("WebFetch", "WebSearch"):
        decide_web(ctx, tool, ti)
    elif tool.startswith("mcp__"):
        decide_mcp(ctx, ti)
    if ctx.denies:
        return ctx.denies[0], ctx
    if not run_finish:
        return None, ctx
    finish(ctx)
    if ctx.denies:
        return ctx.denies[0], ctx
    return None, ctx


def finish(ctx):
    """Nothing is denied: run the evidence writes, then decide whether to answer allow (m0d2-plan §4.2)."""
    for rule, fn in ctx.effects:
        try:
            fn()
        except Exception as e:  # noqa: BLE001 — a failed evidence write denies (closed side)
            ctx.deny(rule, "could not record the checked answer (%s: %s) — ask the person again." % (type(e).__name__, e))
            return
    if len(ctx.candidates) == 1:
        from . import allowrule, scriptrun
        cmd, kind, reason = ctx.candidates[0]
        if kind in ("doc", "script", "work") and ctx.warnings:
            return  # a warning is shown instead, with the normal prompt (defence in depth, 0.0.24; 0.0.28 §1.1 m1)
        if kind == "work":
            ok = cmd is None  # a Write/Edit: roleout.owned checked the path (allowrule.sole is for Bash calls)
        else:
            ok = allowrule.sole(ctx, ctx.scan, cmd, kind)
            if ok and kind == "script":
                ok = scriptrun.trusted(ctx, cmd, *ctx.script_calls[id(cmd)])
        if ok:
            allow_for(ctx, reason)


def allow_for(ctx, reason):
    """The only place the guard decides to allow (structure-tested)."""
    ctx.allow = "Studio guard: " + reason


def decide_web(ctx, tool, ti):
    """INV5 (m0d2-plan §9) in the hook cwd's repository."""
    from . import web
    if not ctx.fs.exists(ctx.cwd):
        return
    ri = ctx.repos.info(ctx.where.git_repo(ctx.cwd))
    if ri is None or not ri.harness:
        return
    ctx.touch(ri)
    v = web.judge(tool, ti, ctx.hook, ri, ctx.env)
    if v is None:
        return
    if v[0] == "deny":
        ctx.deny("G-WEB", v[1])
    else:
        ctx.warnings.append(v[1])


def record_run(ctx):
    """The guard-ran record in each harness repository this call involves (after the decision)."""
    sid = ctx.hook.get("session_id")
    seen = set()
    infos = list(ctx.touched)
    try:
        if ctx.fs.exists(ctx.cwd):
            ri = ctx.repos.info(ctx.where.git_repo(ctx.cwd))
            if ri is not None:
                infos.append(ri)
    except Exception:  # noqa: BLE001
        pass
    for ri in infos:
        if ri is None or not ri.harness or ri.worktree in seen:
            continue
        seen.add(ri.worktree)
        local = os.path.join(ri.worktree, ".claude", "studio", "local")
        ranlog.record(ri.worktree, sid, may_create=os.path.isdir(local) or has_exclude_block(ri))


# fix20: every call is judged by this guard and by the 0.0.26 guard (guard/legacy, frozen); `decide` IS the backstop's
# (an alias, so the 0.0.26 guard runs at the stack depth it had in 0.0.26)
from .backstop import decide  # noqa: E402

__all__ = ["decide", "record_run", "Deny", "recog"]
