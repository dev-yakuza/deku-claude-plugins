"""The guard's judgement (M0d-1b, m0d1b-plan v2). `decide(hook_input, env)` -> (Deny | None, repos).

Two outcomes only: deny, or no decision (the normal permission flow). Never allow, ask or defer.
"""

import fnmatch
import json
import os
import re

from .. import paths, s2vcall
from ..state import commands as state_commands
from . import commitrule, gitprobe, hookfiles, limits, messages, protect, ranlog, recog
from . import scan as scan_command
from . import load_snapshot
from .messages import Deny
from .repos import LOCK_VARS, Repos, has_exclude_block, terms_for
from .where import FS, Where

PLUGIN_SCRIPTS = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
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
        self.candidates = []  # (cmd, kind "state" | "commit" | "s2v", reason)
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

    def _real(self, p):
        anc, tail = p, ""
        while anc not in ("/", "") and not os.path.exists(anc):
            tail = os.path.join(os.path.basename(anc), tail) if tail else os.path.basename(anc)
            anc = os.path.dirname(anc)
        r = os.path.realpath(anc)
        return os.path.join(r, tail) if tail else r

    def deny(self, rule, text, sources=()):
        src = list(sources)
        if self.current is not None:
            for s in messages.alias_sources(self.current):
                if s not in src:
                    src.insert(0, s)
        self.denies.append(Deny(rule, text, src))

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
        out.append((w, vals))
    return out


def resolve_all(ctx, cmd, value):
    """[(abs, real, RepoInfo|None)] for a literal value across the command's cwds."""
    res = []
    if os.path.isabs(value):
        cwds = [None]
    else:
        cwds = cmd.run_cwds or cmd.cwds or []
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
    for c in (cmd.cwds or []):
        if ctx.fs.exists(os.path.join(c, value)):
            return True
    return False


# ---- per-command checks ----

RUNNERS = {"npx": 1, "bunx": 1, "pnpx": 1}
RUNNER_SUB = {"pnpm": ("dlx", "exec"), "yarn": ("dlx", "exec"), "npm": ("exec", "x"), "bun": ("x",)}


def effective(cmd):
    """(program, argument Words) with package runners unwrapped (`npx rimraf x` → rimraf, [x])."""
    prog = cmd.prog or ""
    words = cmd.words[1:]
    rest = None
    if prog in RUNNERS:
        rest = words
    elif prog in RUNNER_SUB and words and words[0].value in RUNNER_SUB[prog]:
        rest = words[1:]
    if rest is None:
        return prog, words
    i = 0
    while i < len(rest) and rest[i].value is not None and rest[i].value.startswith("-"):
        i += 2 if rest[i].value in ("-p", "--package") else 1
    if i < len(rest) and rest[i].value is not None:
        name = rest[i].value.split("@")[0] if not rest[i].value.startswith("@") else rest[i].value
        return os.path.basename(name), rest[i + 1:]
    return prog, words


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


def check_paths(ctx, cmd, studio_infos):
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
    if writes_ok or role in ("read", "git"):
        if role == "git":
            check_git(ctx, cmd, studio_infos)
        return
    recursive = any(a and (a in ("-r", "-R", "--recursive") or re.match(r"^-[a-zA-Z]*[rR]", a)) for a in argv[1:])
    words = eff_words
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
        if ops:
            targets.append((ops[-1], ops[-1].value, "write"))
    elif role == "rsync":
        ops = [w for w in words if w.value is None or not w.value.startswith("-")]
        delete = any(a and a.startswith("--delete") for a in argv[1:])
        for w in ops[:-1]:
            targets.append((w, w.value, "read"))
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
                targets.append((w, os.path.join(dval, os.path.basename(w.value)) if (w.value and dval) else None,
                                "write"))
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
                                                      for c in (cmd.cwds or [None]) if c or os.path.isabs(dest.value))
                if into and w.value is not None:
                    targets.append((dest, os.path.join(dest.value, os.path.basename(w.value.rstrip("/"))), "write"))
                else:
                    targets.append((dest, dest.value, "write"))
    elif prog in EXTRACT_PROGS:
        pass  # judged by check_bulk
    elif role == "find-print":
        for i, w in enumerate(words):
            if w.value in ("-fprint", "-fprint0", "-fprintf", "-fls") and i + 1 < len(words):
                targets.append((words[i + 1], words[i + 1].value, "write"))
    elif role == "find-write":
        for w in words:
            if w.value is None or w.value.startswith("-") or w.value in ("(", "!"):
                break
            targets.append((w, w.value, "delete"))
    else:
        for w, vals in candidates(cmd):
            if w.value is None:
                targets.append((w, None, "write"))
                continue
            for v in vals:
                if looks_like_path(v, cmd, ctx) or (w.value != v):
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


def weak_extractor(prog, argv):
    """A reason when this is an extractor whose behaviour Studio did not measure (refused in Studio repositories)."""
    a = [x for x in argv[1:]]
    if prog in WEAK_7Z:
        w = next((x for x in a if x is not None and not x.startswith("-")), None)
        if w is None or w.lower() in ("x", "e"):
            return "%s extraction" % prog
    elif prog == "bsdcpio":
        return "bsdcpio"
    elif prog == "busybox":
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


def studio_area(ctx, cmd, value, studio_infos):
    """None, or why the folder `value` is (or holds) Studio's folders: the repository root, .claude/**, <sr>/**,
    .git/**, the git common dir, or a folder above a Studio repository."""
    if value is None:
        return "a folder the guard cannot read" if studio_infos else None
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
    weak = weak_extractor(prog, argv)
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
        folders = [v for _w, v in dirs] if dirs else (cmd.run_cwds or cmd.cwds or [None])
        for v in folders:
            why = studio_area(ctx, cmd, v, studio_infos)
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
    elif len(ops) >= 2:
        dest, srcs = ops[-1].value, ops[:-1]
    else:
        return False
    no_target = prog in ("cp", "gcp") and no_target_dir(argv)
    # the destination rule always (review X2): the walk below is a snapshot and a tool's landing can differ from the
    # model (GNU -T); it only adds checks for other destinations
    for b in [dest] + [x for sw in srcs for x in _copy_bases(ctx, cmd, mode, sw.value, dest, no_target)]:
        why = studio_area(ctx, cmd, b, studio_infos)
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


INNER_KINDS = ("shell-c", "eval", "env-S", "script", "source", "stdin-interp")
SCRIPT_OPTS_VALUE = ("-t", "-T", "-I", "-O", "-B", "-E", "-m", "-c", "-F")  # script(1) options taking a value


def check_shell_strings(ctx, sc, infos, depth):
    """W2 / X1: the path rules (extractions, recursive copies, later writers) for code the shell runs from text:
    literal `sh -c` / `eval` / `env -S` strings, script files run or sourced (`bash f`, `. f`, `bash < f`) and
    `script … <cmd>`, in the host's folder; nested up to SHELL_DEPTH. In a Studio repository, code the guard cannot
    read (an unreadable script, a non-literal string, a command word from a variable or a substitution, `xargs … sh
    -c`) is refused."""
    by_id = {c.id: c for c in sc.commands}
    texts = []  # (host command, text)
    for o in sc.opaque:
        host = by_id.get(o.cmd)
        if o.kind == "dynamic-command":
            if infos:
                ctx.deny("G-OPAQUE", "a command word or a shell string built at run time runs code the guard cannot "
                                     "check in a Studio repository — write the command's path literally (or use npx "
                                     "…), one step per call.")
            continue
        if o.kind == "xargs" and re.match(r"^(\S*/)?(sh|bash|zsh|dash|ksh)\b", o.payload or ""):
            unknown(ctx, infos, "xargs feeding text to a shell")
            continue
        if o.kind not in INNER_KINDS:
            continue
        if host is not None and "exec-by-program" in (host.flags or ()):
            continue  # the template of an xargs/find -exec (judged above)
        if o.kind in ("script", "stdin-interp") and (host is None or os.path.basename(host.prog or "") not in SHELLS):
            continue  # another interpreter's code (python, node, …): the opaque rules (G-OPAQUE) decide
        text = o.payload
        if o.kind in ("shell-c", "eval", "env-S") and (o.origin != "literal" or text is None or (
                host is not None and any(w.value is None for w in host.words[1:]))):
            unknown(ctx, infos, "%s with text the guard cannot read" % o.kind)
            continue
        if text is None:
            unknown(ctx, infos, "a script the guard cannot read")
            continue
        if o.kind == "env-S":
            text = re.sub(r"^\s*(-S|--split-string=?)\s*", "", text)
        texts.append((host, text, o.cwds))
    for c in sc.commands:
        w0 = c.words[0] if c.words else None
        if w0 is not None and ("$" in (w0.raw or "") or "`" in (w0.raw or "")) and w0.value != "":
            if infos:
                ctx.deny("G-OPAQUE", "a command word taken from a variable or a substitution (%s) runs a program the "
                                     "guard cannot name in a Studio repository — write the command's path literally "
                                     "(or use npx …), one step per call." % w0.raw)
        if c.prog == "script":
            inner = script_inner(c)
            if inner is None:
                unknown(ctx, infos, "script(1) running a command the guard cannot read")
            elif inner:
                texts.append((c, inner, None))
    for host, text, ocwds in texts:
        cwds = (host.run_cwds or host.cwds) if host is not None else ocwds
        if not cwds or len(cwds) != 1:
            unknown(ctx, infos, "code run from a folder the guard cannot tell")
            continue
        if depth >= SHELL_DEPTH:
            unknown(ctx, infos, "code nested deeper than %d levels" % SHELL_DEPTH)
            continue
        sub = scan_command(text, cwds[0], ctx.env, snapshot=ctx.snap, snapshot_notes=(), terms=None, fs=ctx.fs,
                           budget=limits.Budget())
        if sub.status != "ok":
            unknown(ctx, infos, "code the guard cannot parse")
            continue
        outer, ctx.bulk_ids = ctx.bulk_ids, set()  # the inner command ids are their own
        try:
            for c in sub.commands:
                ctx.current = c
                check_paths(ctx, c, infos)
            ctx.current = None
            check_shell_strings(ctx, sub, infos, depth + 1)
            inner = ctx.bulk_ids
        finally:
            ctx.bulk_ids = outer
        if inner:
            bulk_then_write(ctx, sub.commands, inner)
            if host is not None:
                ctx.bulk_ids.add(host.id)


def unknown(ctx, infos, what):
    if infos:
        ctx.deny("G-OPAQUE", "%s runs code the guard cannot check in a Studio repository — write the commands directly "
                             "(literal words), one step per call." % what)


def script_inner(c):
    """The command script(1) runs, as shell text: '' for none, None when not literal. BSD: script [opts] [file
    [cmd …]]; util-linux: script [opts] -c 'cmd' [file]."""
    vals = [w.value for w in c.words[1:]]
    if any(v is None for v in vals):
        return None
    i, rest = 0, []
    while i < len(vals):
        v = vals[i]
        if v == "-c" and i + 1 < len(vals):
            return vals[i + 1]
        if v == "--":
            rest = vals[i + 1:]
            break
        if v.startswith("-") and len(v) > 1:
            i += 2 if v in SCRIPT_OPTS_VALUE else 1
            continue
        rest = vals[i:]
        break
    if len(rest) <= 1:
        return ""
    import shlex
    return " ".join(shlex.quote(x) for x in rest[1:])


def bulk_then_write(ctx, commands, bulk_ids):
    """W4: after an extraction or a recursive copy in a Studio repository, no other writing command in the same call
    (what the bulk writer put down could be moved into Studio's folders before the guard sees it)."""
    seen = False
    for c in commands:
        if seen and is_writer(c):
            ctx.deny("G-PROT", "%s runs after an archive extraction or a recursive copy in the same call — run the "
                               "extraction or copy alone, then run the next step in a separate call."
                     % (c.prog or "a command"))
            return
        if c.id in bulk_ids:
            seen = True


def is_writer(c):
    prog = c.prog or ""
    if any(r.target is not None and r.mode in ("write", "append", "rw") for r in c.redirs):
        return True
    if prog in protect.READ_ALLOW and prog not in ("find", "bfs"):
        return False
    if prog in ("find", "bfs"):
        return any(w.value in protect.FIND_WRITE for w in c.words if w.value)
    if prog == "git" and c.git is not None and c.git.sub in protect.GIT_READ:
        return False
    return True


def hard_link_copy(argv):
    return any(x is not None and (x == "--link" or (x.startswith("-") and not x.startswith("--") and "l" in x[1:]))
               for x in argv[1:])


def check_target(ctx, cmd, word, value, op, studio_infos, s2v=False):
    if value is None:
        if word.dynamic and studio_infos and protect.tail_hits(word.skeleton or ""):
            ctx.deny("G-PROT" if op == "write" else "G-DEL",
                     "%s %s a path the guard cannot read (%s) that ends in a protected name."
                     % (cmd.prog or "the command", "writes" if op == "write" else "deletes", word.raw))
        return
    for a, real, ri in resolve_all(ctx, cmd, value):
        if a is None:
            # unknown cwd: judge the text as if relative to each Studio repository root
            for sri in studio_infos:
                parts = [x for x in value.split("/") if x not in ("", ".")]
                judge_parts(ctx, cmd, word, value, parts, sri, False, op, s2v, None)
            continue
        if op == "link-source":
            if ri is not None and hookfiles.hit(ri, real, "delete"):
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
        if ri is None or not ri.studio:
            continue
        ctx.touch(ri)
        parts, fold = rel(ctx, ri, real)
        if parts is None:
            continue
        if word.glob and word.glob_base is not None:
            judge_glob(ctx, cmd, word, ri, real, fold, op)
            continue
        judge_parts(ctx, cmd, word, value, parts, ri, fold, op, s2v, real)


HOOK_WHY = "Studio's pre-commit hook (wiring) — only \"python3 .claude/studio/scripts/hooks.py install\" changes it"


def hook_file_denied(ctx, cmd, ri, real, value, op):
    """P-HOOK for Bash: any write, delete or move of an installed hook file (m0e-plan §10)."""
    h = hookfiles.hit(ri, real, "delete" if op.startswith("delete") else "write")
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


def judge_glob(ctx, cmd, word, ri, real, fold, op):
    sr = ri.studio_root
    base_val = word.glob_base or ""
    cwd = (cmd.run_cwds or cmd.cwds or [None])[0]
    base = ctx.where.resolve(base_val or ".", cwd)
    if base is None or base.real is None:
        return
    bparts = protect.rel_parts(base.real, ri.worktree, fold)
    if bparts is None:
        return
    rest = (word.value or "")[len(base_val):]
    seg = rest.split("/")[0]
    anchors = [[sr], [".claude", "studio"]]
    for anc in anchors:
        if len(anc) > len(bparts) and anc[:len(bparts)] == bparts:
            nxt = anc[len(bparts)]
            if fnmatch.fnmatchcase(nxt.casefold() if fold else nxt, seg.casefold() if fold else seg):
                judge_parts(ctx, cmd, word, word.value, anc[:len(bparts) + 1], ri, fold,
                            "delete" if op.startswith("delete") else op, False, None)
                return
    if bparts[:1] == [sr] or bparts[:2] == [".claude", "studio"]:
        if op.startswith("delete"):
            tid = protect.delete_hits(bparts, sr, fold, is_dir=True)
            if tid:
                ctx.deny("G-DEL", "%s deletes %s, which may include protected Studio data." % (cmd.prog, word.value))
        else:
            for tid, pats, _c, _w in protect.TABLE:
                if tid == "P-LOCAL":
                    continue
                if any(protect._may_contain(bparts, protect._expand(p, sr), fold) for p in pats):
                    ctx.deny("G-PROT", "%s writes %s, which may match protected Studio files." % (cmd.prog, word.value))
                    return


GIT_ENV_TARGET = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")


def git_target(ctx, cmd):
    """(RepoInfo, run cwd, git prefix args, extra env) for a git command, or a reason string to deny.
    --git-dir/--work-tree and GIT_DIR/GIT_WORK_TREE (command first, then the inherited environment) win."""
    g = cmd.git
    run = cmd.run_cwds or cmd.cwds or [None]
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
            return None
        if (gd and not os.path.isabs(gd)) or (wt and not os.path.isabs(wt)):
            return "the working folder is unknown"
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
    dyn_global = [w.raw for w in cmd.words[1:] if w.value is None and w.raw.startswith(("--git-dir", "--work-tree"))]
    if g.sub is None or dyn_global:
        if dyn_global and studio_infos:
            ctx.deny("G-RESET", "git with %s (not a literal) cannot be checked — write the path." % dyn_global[0])
        return
    if check_git_new_checkout(ctx, cmd):
        return
    target = git_target(ctx, cmd)
    if isinstance(target, str):
        if studio_infos and g.sub in ("clean", "reset", "checkout", "restore", "switch", "stash", "rm", "mv", "add", "worktree"):
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
                    any(ch in w.value for ch in "*?["):
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
        ctx.deny(v.rule, v.text, messages.alias_sources(cmd))
        return True
    pend = v.pending
    ctx.effects.append(("G-EVIDENCE", lambda: approve.write_pending(ri, pend)))
    ctx.candidates.append((cmd, "state", v.reason))
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
    run = cmd.run_cwds or cmd.cwds or []
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
        ctx.deny(v.rule, v.text, messages.alias_sources(cmd))
        return
    pend = v.pending
    ctx.effects.append(("G-EVIDENCE", lambda: approve.write_pending(ri, pend)))
    ctx.candidates.append((cmd, "state", v.reason))


def s2v_approval(ctx, cmd, words):
    from . import approve
    what = "s2v " + " ".join(words)
    if not _count_approval(ctx, cmd, what):
        return
    ri = _run_repo(ctx, cmd)
    v = approve.s2v(ctx.hook, ctx.env, ri if ri is not None and ri.studio else None, words)
    if v.rule:
        ctx.deny(v.rule, v.text, messages.alias_sources(cmd))
        return
    ctx.candidates.append((cmd, "s2v", v.reason))


# ---- tools ----

def decide_bash(ctx, command):
    ctx.command = command
    try:
        snap, notes = ctx.snapshot_loader(ctx.env)
    except Exception:  # noqa: BLE001 — an unreadable snapshot is the None mode
        snap, notes = None, ["snapshot-unreadable:load"]
    budget = limits.Budget()
    ctx.snap = snap
    sc = scan_command(command, ctx.cwd, ctx.env, snapshot=snap, snapshot_notes=notes, terms=None, fs=ctx.fs,
                      budget=budget)
    cwd_repo = ctx.repos.info(ctx.where.git_repo(ctx.cwd)) if ctx.fs.exists(ctx.cwd) else None
    infos = []
    if cwd_repo is not None and cwd_repo.studio:
        infos.append(cwd_repo)
    # target repositories
    n = 0
    for c in sc.commands:
        for d in (c.cwds or []) + (c.run_cwds or []):
            if ctx.fs.exists(d):
                ri = ctx.repos.info(ctx.where.git_repo(d))
                if ri is not None and ri.studio and ri not in infos:
                    infos.append(ri)
        for w, vals in candidates(c):
            for v in vals:
                if not looks_like_path(v, c, ctx):
                    continue
                n += 1
                if n > MAX_CANDIDATES:
                    ctx.deny("G-LIMIT", "the command has too many path arguments for the guard — split it.")
                    return sc, infos
                for a, real, ri in resolve_all(ctx, c, v):
                    if ri is not None and ri.studio and ri not in infos:
                        infos.append(ri)
        for r in c.redirs:
            if r.target is not None and r.target.value:
                for a, real, ri in resolve_all(ctx, c, r.target.value):
                    if ri is not None and ri.studio and ri not in infos:
                        infos.append(ri)
    for ri in infos:
        ctx.touch(ri)
    fold = ctx.where.case_insensitive(ctx.cwd) if ctx.fs.exists(ctx.cwd) else False
    terms = terms_for(infos, fold)
    raw_hits = terms.find(command)
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
        # out-of-repo files are judged from the text only when parsing failed
        return sc, infos
    # always: out-of-repo protected files (and lock owner records); Studio paths when a repository is one
    for c in sc.commands:
        ctx.current = c
        check_out_of_repo(ctx, c)
        check_paths(ctx, c, infos)
    ctx.current = None
    check_shell_strings(ctx, sc, infos, 0)  # adds the host `sh` of a string that extracts or copies trees
    if ctx.bulk_ids:
        bulk_then_write(ctx, sc.commands, ctx.bulk_ids)
    if not infos:
        return sc, infos
    if STUDIO_NAMES_RE.search(command):
        ctx.deny("G-ENV", "STUDIO_* variables are set only by the person who starts Claude.")
    ctx.scan = sc
    by_id = {c.id: c for c in sc.commands}
    check_dynamic_writers(ctx, sc, terms, infos)
    for o in sc.opaque:
        check_opaque(ctx, o, by_id.get(o.cmd), terms, infos, src_notes)
    for c in sc.commands:
        ctx.current = c
        check_version(ctx, c)
        check_env(ctx, c)
        check_approval(ctx, c)
        check_s2v_results(ctx, c)
        check_git_rules(ctx, c, infos)
        check_gh(ctx, c, infos)
        check_patch(ctx, c, infos, sc)
    ctx.current = None
    return sc, infos


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
    out = commitrule.evaluate(ri.worktree, ctx.env, extra, opts, plugin_scripts=PLUGIN_SCRIPTS)
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
                from ..commit import values as cvals
                if not cvals.shown_in(shown, text):
                    raise transcript.NoEvidence("values-not-shown")  # m1-plan §5.1 (v3 N1)
        except transcript.NoEvidence as e:
            what = "this Studio commit" + (" (the question must contain the line: %s)" % line if line else "")
            if ok.get("values_shown"):
                what += " and these lines: %s" % " / ".join(ok["values_shown"][:6])
            ctx.deny("G-EVIDENCE", approve.evidence_text(what, label, e))
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
    ctx.candidates.append((cmd, "commit", reason))


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


def check_push(ctx, cmd, ri):
    from . import push, web
    if not ri.harness:
        return
    st, data = web.overlay(ri.worktree, ri.config, ctx.env)
    ids = web.internal_items(data)[2] if st == "ok" else set()
    deny, warns = push.check(ri.worktree, ctx.env, cmd.git.args, ids)
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
    run = cmd.run_cwds or cmd.cwds or [None]
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
        t = git_target(ctx, cmd)
        if isinstance(t, tuple):
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
    cwd = (cmd.cwds or [None])[0]
    for r in cmd.redirs:
        if r.mode == "read" and r.fd in (None, "0") and r.target is not None:
            out.append((r.target.value, cwd))
    for c in sc.commands:
        if c is cmd:
            continue
        if "cmdsubst" in c.ctx and _span_in(c, cmd) and any(w.value is None for w in cmd.words):
            out += [(f, (c.cwds or [cwd])[0]) for f in reader_files(c)]
    argv = [w.value for w in cmd.words]
    if cmd.prog in ("xargs", "parallel"):
        for i, v in enumerate(argv):
            if v in ("-a", "--arg-file") and i + 1 < len(argv):
                out.append((argv[i + 1], cwd))
            elif v is not None and v.startswith("--arg-file="):
                out.append((v.split("=", 1)[1], cwd))
        if cmd.prog == "parallel" and "::::" in argv:
            for v in argv[argv.index("::::") + 1:]:
                if v in (":::", "::::"):
                    break
                out.append((v, cwd))
        if "pipeline" in cmd.ctx and cmd.span:
            start = statement_start(raw, cmd.span[0])
            for c in sc.commands:
                if c is not cmd and "pipeline" in c.ctx and c.span and start <= c.span[0] and c.span[1] <= cmd.span[0] and \
                        not ("cmdsubst" in c.ctx and not _span_in(c, cmd)):
                    out += [(f, (c.cwds or [cwd])[0]) for f in reader_files(c)]
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
                out += [(f, (c.cwds or [cwd])[0]) for f in reader_files(c)]
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
                             "they can be checked." % (o.kind, what), sources + src_notes)
    elif o.hits_unknown and studio_related(ctx, cmd, infos):
        ctx.deny("G-OPAQUE", "%s runs code the guard cannot read in a Studio context — run the commands directly."
                 % o.kind, sources + src_notes)


def decide_file(ctx, tool, ti):
    key = "notebook_path" if tool == "NotebookEdit" else "file_path"
    path = ti.get(key) or ti.get("file_path") or ti.get("notebook_path")
    if not isinstance(path, str) or not path:
        return
    judge_file_path(ctx, path, tool, ti)


def judge_file_path(ctx, path, tool, ti, mcp=False):
    r = ctx.where.resolve(path, ctx.cwd)
    if r is None or r.abs is None:
        return
    if out_hit(ctx, r.real, "write"):
        ctx.deny("G-OUT", "%s %s (Studio's per-user files or the machine lock) — only Studio's scripts change it."
                 % ("writing" if not mcp else "this tool touches", path))
        return
    ri = ctx.repos.info(r.repo) if r.repo is not None else None
    h = hookfiles.hit(ri, r.real, "write")
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


def decide(hook, env, fs=None, probe=None, snapshot_loader=None):
    """(Deny | None, Context). Internal errors deny (closed side)."""
    ctx = Context(hook, env, fs=fs, probe=probe, snapshot_loader=snapshot_loader)
    try:
        return _decide(ctx, hook)
    except Exception as e:  # noqa: BLE001
        ctx.denies.insert(0, Deny("G-ERR", "internal guard error (%s) — tell the user; this is a bug in the guard."
                                  % type(e).__name__))
        return ctx.denies[0], ctx


def _decide(ctx, hook):
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
        from . import allowrule
        cmd, kind, reason = ctx.candidates[0]
        if allowrule.sole(ctx, ctx.scan, cmd, kind):
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


__all__ = ["decide", "record_run", "Deny", "recog"]
