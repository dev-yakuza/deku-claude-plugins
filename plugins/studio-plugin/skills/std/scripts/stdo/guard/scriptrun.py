"""0.0.28 §1.1 (fix-0028-plan, pilot-3 Q1): when a repository copy of one of Studio's own read-and-record scripts may
run without the person's prompt (kind `script`). Every condition here is a "no allow" condition: failing one means the
normal permission prompt, never a deny. judge.check_script makes the candidate from the call's words (`shape`);
judge.finish asks `trusted` after allowrule.sole, and allow_for stays the only allow site.

Only in the `default` permission mode: there every other write the model makes is prompted, so an unprompted write
cannot prepare what an allow here then runs (pyenv files, nvm, the s2v checkout) — except through an allow rule the
person wrote (`Bash(git:*)`: a stated residual in docs/guard-limits.md). The checks below are defence in depth.

Files are read with os directly (O_NOFOLLOW | O_NONBLOCK, fstat on the open descriptor), not through ctx.fs: its read
count stops at 8, and an error here must never become a deny (`trusted` answers False on any exception)."""

import hashlib
import os
import re
import stat
import unicodedata

from .. import SCRIPTS_VERSION, manifest
from . import cmdopts, version
from .allowrule import PY_NAME

AUTO_SCRIPTS = ("state.py", "check_assets.py", "check_claims.py", "check_scope.py", "check_tts.py",
                "resolve_assets.py", "validate_copy.py", "audition.py")
# evidence-free state.py subcommands that still prompt: a pause request is the person's (plan §13)
NO_AUTO = frozenset(["ask-before"])
# = state/flow.VIDEO_ID (not imported: flow loads the state writers; test_guard_autoallow checks they are equal)
VIDEO_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
# the other scripts' own option parsing: value options (`--x v`; `--lang=v` too), flags. An unknown option: no allow.
OPTIONS = {
    "check_assets.py": (("--lang", "--output"), ("--actors", "--look")),
    "check_claims.py": (("--lang",), ("--narration", "--skeleton", "--source", "--fill")),
    "check_scope.py": ((), ()),
    "resolve_assets.py": ((), ()),
    "check_tts.py": (("--lang",), ()),
    "audition.py": (("--lang",), ()),
    "validate_copy.py": (("--platform", "--lang"), ()),
}
SUFFIX = "/.claude/studio/scripts/"
# what the scripts run from PATH, and the real file's name each must have (no asdf, pyenv, mise or volta shim: they
# choose what runs from repository files such as .tool-versions or mise.toml)
PROGRAMS = (("node", re.compile(r"^node$")), ("git", re.compile(r"^git$")), ("ffmpeg", re.compile(r"^ffmpeg$")))
ENV_OFF = ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONINSPECT", "PYTHONUSERBASE", "NODE_OPTIONS", "NODE_PATH",
           "GIT_DIR", "GIT_WORK_TREE", "GIT_EXEC_PATH", "GIT_ATTR_SOURCE")
PYENV_ENV = ("PYENV_VERSION", "PYENV_DIR", "PYENV_HOOK_PATH", "_PYENV_SHIM_PATH", "BASH_ENV", "ENV", "BASHOPTS",
             "SHELLOPTS")
GIT_SCOPES = ("local", "worktree", "command")
GIT_KEYS = ("filter.*.clean", "filter.*.smudge", "filter.*.process", "diff.*.textconv", "diff.*.command",
            "diff.external", "core.attributesfile", "core.hookspath", "log.showsignature", "gpg.program",
            "gpg.*.program", "extensions.partialclone", "remote.*.promisor")
MAX_ENTRIES = 1000  # files and folders under .claude/studio/scripts (about 100 today)
PLUGIN_MANIFEST = os.path.join(version.PLUGIN_SCRIPTS, manifest.NAME)
OPEN_FLAGS = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)


# ---- the call's words (cheap: judge.check_script) ----

def shape(name, argv):
    """(video, sub) when the arguments are a form this allow covers — video None only for `state.py status` without
    one — else None."""
    from ..state import argv as state_argv, commands as state_commands
    if name == "state.py":
        sub = argv[0] if argv else None
        if sub is None or state_commands.needs_evidence(sub) or sub in NO_AUTO or sub not in state_commands.IMPLEMENTED:
            return None
        try:
            pos = state_argv.canonical(argv)["pos"]
        except ValueError:
            return None
        if not pos:
            return (None, sub) if sub == "status" else None
        return (pos[0], sub) if VIDEO_ID.match(pos[0]) else None
    if name not in OPTIONS:
        return None
    values, flags = OPTIONS[name]
    pos = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in flags:
            i += 1
        elif a in values:
            if i + 1 >= len(argv):
                return None
            i += 2
        elif a.startswith("--lang=") and "--lang" in values:
            i += 1
        elif a.startswith("-"):
            return None
        else:
            pos.append(a)
            i += 1
    if len(pos) != 1 or not VIDEO_ID.match(pos[0]):
        return None
    return pos[0], None


# ---- the area the model may write to ----

def _key(p):
    # compared case-folded always: on a volume that tells case apart this only gives fewer allows
    return unicodedata.normalize("NFC", p).casefold()


def _inside(p, root):
    p, root = _key(p), _key(root.rstrip("/") or "/")
    return p == root or p.startswith(root.rstrip("/") + "/")


class Area(object):
    """The run repository, the hook cwd and the session's project folder, as spelled and as resolved."""

    def __init__(self, folders):
        self.roots = []
        for f in folders:
            for r in (os.path.normpath(f), os.path.realpath(f)):
                if r not in self.roots:
                    self.roots.append(r)

    def inside(self, p):
        if not p:
            return True
        return any(_inside(x, r) for x in (os.path.normpath(p), os.path.realpath(p)) for r in self.roots)


# ---- small file helpers ----

def _read(path, limit=1 << 20):
    """The bytes of a regular file opened without following a link (None otherwise)."""
    try:
        fd = os.open(path, OPEN_FLAGS)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        chunks, left = [], limit + 1
        while left > 0:
            b = os.read(fd, min(left, 65536))
            if not b:
                break
            chunks.append(b)
            left -= len(b)
        data = b"".join(chunks)
        return None if len(data) > limit else data
    except OSError:
        return None
    finally:
        os.close(fd)


def _head(path):
    """The first two bytes of a regular file (following links: a program's real file), None when unreadable."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0))
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        return os.read(fd, 2)
    except OSError:
        return None
    finally:
        os.close(fd)


def _no_link_below(prefix, parts):
    """No existing component of prefix/parts below prefix is a link."""
    cur = prefix
    for part in parts:
        cur = os.path.join(cur, part)
        try:
            st = os.lstat(cur)
        except FileNotFoundError:
            return True
        except OSError:
            return False
        if stat.S_ISLNK(st.st_mode):
            return False
    return True


def _real_dir(path):
    try:
        return stat.S_ISDIR(os.lstat(path).st_mode)
    except OSError:
        return False


def _which(name, path_value):
    for d in path_value.split(":"):
        p = os.path.join(d, name)
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


def _path_ok(path_value, area):
    """No entry empty, relative or inside the area (the scripts run node, git and ffmpeg from PATH)."""
    if not path_value:
        return False
    return all(d and os.path.isabs(d) and not area.inside(d) for d in path_value.split(":"))


def program_ok(path, name_re, area):
    """The resolved file and its real file outside the area, the real file not a `#!` script and named as the
    program itself."""
    if path is None or area.inside(path):
        return False
    real = os.path.realpath(path)
    if area.inside(real) or not name_re.match(os.path.basename(real)):
        return False
    head = _head(real)
    return head is not None and head != b"#!"


# ---- pyenv, `system` only (review 5 M1: python3 may resolve to ~/.pyenv/shims/python3, a bash script) ----

def _set_in(names, env, snap, prefixes=()):
    for k in env:
        if k in names or k.startswith(prefixes):
            return True
    for v in (getattr(snap, "variants", None) or []) if snap is not None else []:
        text = getattr(v, "text", "") or ""
        if any(re.search(r"(?<![A-Za-z0-9_])%s=" % re.escape(n), text) for n in names) or \
                any(p in text for p in prefixes):
            return True
    return False


PYENV_HOOK_DIRS = ("/usr/etc/pyenv.d", "/opt/homebrew/etc/pyenv.d", "/usr/local/etc/pyenv.d", "/etc/pyenv.d",
                   "/usr/lib/pyenv/hooks")


def _pyenv_own(env, cwd, root, prefix):
    """The pyenv variables whose values are the ones libexec/pyenv and pyenv-exec set themselves when the guard was
    started through the same shim (hooks.json runs `python3 …/guard.py`): PYENV_VERSION `system`, PYENV_DIR the hook
    cwd, PYENV_HOOK_PATH starting at `<root>/pyenv.d` with pyenv's own hook folders only (those folders are a stated
    residual). A value the person set (another version, a hook folder of theirs first) is not one of these."""
    own = set()
    if env.get("PYENV_VERSION") == "system":
        own.add("PYENV_VERSION")
    d = env.get("PYENV_DIR")
    if d and os.path.isabs(d) and os.path.realpath(d) == os.path.realpath(cwd):
        own.add("PYENV_DIR")
    hp = env.get("PYENV_HOOK_PATH")
    if hp:
        import glob
        known = {os.path.join(root, "pyenv.d"), os.path.join(prefix, "pyenv.d")} | set(PYENV_HOOK_DIRS) | \
            set(glob.glob(os.path.join(root, "plugins", "*", "etc", "pyenv.d")))
        parts = hp.split(":")
        if parts[0] == os.path.join(root, "pyenv.d") and all(x in known for x in parts):
            own.add("PYENV_HOOK_PATH")
    return own


def version_file_system(path):
    """pyenv-version-file-read's reading of `<root>/version`: absent or no entry → True ("system" by default); exactly
    one entry `system` → True; anything else (an installed version) → False."""
    try:
        os.lstat(path)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    data = _read(path, 65536)
    if data is None:
        return False
    found = []
    for line in data.decode("utf-8", "replace").split("\n"):
        for i in range(0, max(len(line), 1), 1024):
            chunk = line[i:i + 1024]
            words = chunk.split()
            w = words[0].rstrip("\r") if words else ""
            if not w or w.startswith("#"):
                continue
            found.append(w)
    return found in ([], ["system"])


def _python_version_near(folders):
    for f in folders:
        d = os.path.normpath(f)
        while True:
            if os.path.lexists(os.path.join(d, ".python-version")):
                return True
            parent = os.path.dirname(d)
            if parent == d:
                break
            d = parent
    return False


def pyenv_target(shim, path_value, ctx, area, folders):
    """The file pyenv's `system` lookup would run for this shim on this PATH, or None (no allow)."""
    root = os.path.dirname(os.path.dirname(shim))
    data = _read(os.path.realpath(shim), 65536)
    if data is None:
        return None
    text = data.decode("utf-8", "replace")
    m = re.search(r'(?m)^export PYENV_ROOT="([^"$`\\]*)"$', text)
    e = re.search(r'(?m)^exec "([^"$`\\]+)" exec "\$program" "\$@"$', text)
    if m is None or e is None or m.group(1) != root:
        return None
    pyenv = e.group(1)
    if not os.path.isabs(pyenv) or area.inside(pyenv) or area.inside(os.path.realpath(pyenv)):
        return None
    bin_path = os.path.dirname(os.path.realpath(pyenv))
    prefix = os.path.dirname(bin_path)
    own = _pyenv_own(ctx.env, ctx.cwd, root, prefix)
    env = {k: v for k, v in ctx.env.items() if k not in own}
    if _set_in(PYENV_ENV, env, ctx.snap, ("_PYENV_SHIM_PATHS_", "BASH_FUNC_")):
        return None
    if _python_version_near(folders):
        return None
    if not version_file_system(os.path.join(root, "version")):
        return None
    # libexec/pyenv puts its own folder and the plugins' bin folders in front of PATH; pyenv-which then drops every
    # <root>/shims entry for the `system` version
    import glob
    front = [bin_path] + sorted(glob.glob(os.path.join(root, "plugins", "*", "bin")), reverse=True) + \
        sorted(glob.glob(os.path.join(prefix, "plugins", "*", "bin")), reverse=True)
    if any(area.inside(d) for d in front):
        return None
    shims = os.path.join(root, "shims")
    entries = [d for d in front + path_value.split(":") if d != shims]
    return _which(os.path.basename(shim), ":".join(entries))


def _is_shim(path):
    return path is not None and os.path.basename(os.path.dirname(path)) == "shims" and \
        _head(os.path.realpath(path)) == b"#!"


def python_ok(w0, path_value, ctx, area, folders):
    found = w0 if "/" in w0 else _which(w0, path_value)
    if found is None:
        return False
    if _is_shim(found):
        if area.inside(found):
            return False
        found = pyenv_target(found, path_value, ctx, area, folders)
    return program_ok(found, PY_NAME, area)


# ---- the repository copy ----

def copy_intact(prefix):
    """Every MANIFEST.sha256 entry matches its file; nothing else (no __pycache__, .pyc, .pth, stray json.py, link or
    .DS_Store) under .claude/studio/scripts; the manifest is the plugin's for the same SCRIPTS_VERSION."""
    if not _no_link_below(prefix, (".claude", "studio", "scripts")):
        return False
    scripts = os.path.join(prefix, ".claude", "studio", "scripts")
    if not _real_dir(scripts):
        return False
    mine = _read(os.path.join(scripts, manifest.NAME))
    plugin = _read(PLUGIN_MANIFEST)
    if mine is None or plugin is None or mine != plugin:
        return False
    try:
        files, ver = manifest.parse(mine.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return False
    if ver != SCRIPTS_VERSION or not files:
        return False
    dirs = set()
    for rel in files:
        parts = rel.split("/")
        if any(p in ("", ".", "..") for p in parts):
            return False
        for i in range(1, len(parts)):
            dirs.add("/".join(parts[:i]))
    seen = [0]

    def walk(d, rel):
        try:
            entries = list(os.scandir(d))
        except OSError:
            return False
        for ent in entries:
            seen[0] += 1
            if seen[0] > MAX_ENTRIES:
                return False
            r = ent.name if not rel else rel + "/" + ent.name
            try:
                st = os.lstat(ent.path)
            except OSError:
                return False
            if stat.S_ISDIR(st.st_mode):
                if r not in dirs or not walk(ent.path, r):
                    return False
            elif stat.S_ISREG(st.st_mode):
                if r not in files and r != manifest.NAME:
                    return False
            else:
                return False  # a link, a FIFO, a socket, a device
        return True

    if not walk(scripts, ""):
        return False
    for rel, sha in files.items():
        data = _read(os.path.join(scripts, rel), 16 << 20)
        if data is None or hashlib.sha256(data).hexdigest() != sha:
            return False
    return True


# ---- git config of the run repository ----

def git_config_ok(ctx, worktree):
    """The repository's own config (local, worktree and command scopes; read without the guard's -c overrides) sets
    nothing that runs a program on `git status` / `git diff` / `git show`, and there are no submodules."""
    if os.path.lexists(os.path.join(worktree, ".gitmodules")):
        return False
    out = ctx.probe.config_list(worktree)
    if out is None:
        return False
    toks = out.split("\0")
    if toks and toks[-1] == "":
        toks.pop()
    if len(toks) % 2:
        return False
    import fnmatch
    for i in range(0, len(toks), 2):
        scope, kv = toks[i], toks[i + 1]
        if scope not in GIT_SCOPES:
            continue  # global, system, unknown: the person's (the guard refuses writes to the user config)
        key, _sep, val = kv.partition("\n")
        k = key.lower()
        if k.startswith(("include.", "includeif.")):
            return False
        if any(fnmatch.fnmatchcase(k, p) for p in GIT_KEYS):
            return False
        if k == "core.fsmonitor":
            if val.lower() not in cmdopts.BOOLEAN:
                return False
            continue
        if cmdopts.command_key(key, val) is not None:
            return False
    return True


# ---- the whole check ----

def _video_ok(prefix, worktree, studio_root, video, sub):
    sr = [x for x in studio_root.split("/") if x]
    joins = [sr + ["videos", video], sr + ["local", "videos", video]]
    if sub != "begin":
        found = [j for j in joins if _real_dir(os.path.join(prefix, *j))]
        if len(found) != 1:
            return False  # store.video_dir: exactly one of public and local
        joins = found
    for j in joins:
        if not _no_link_below(prefix, j):
            return False
        if not _inside(os.path.realpath(os.path.join(prefix, *j)), worktree) or \
                os.path.realpath(os.path.join(prefix, *j)) == worktree:
            return False
    return True


def _session_env_ok(ctx):
    sid = ctx.hook.get("session_id")
    if not isinstance(sid, str) or not sid or "/" in sid or sid in (".", ".."):
        return False
    cfg = ctx.env.get("CLAUDE_CONFIG_DIR") or os.path.join(ctx.env.get("HOME") or os.path.expanduser("~"), ".claude")
    d = os.path.join(cfg, "session-env", sid)
    if os.path.isdir(d):
        try:
            for dirpath, _dirs, names in os.walk(d):
                for n in names:
                    p = os.path.join(dirpath, n)
                    if not os.path.isfile(p) or os.path.getsize(p) > 0:
                        return False
        except OSError:
            return False
    ef = ctx.env.get("CLAUDE_ENV_FILE")
    if ef:
        try:
            if os.path.getsize(ef) > 0:
                return False
        except FileNotFoundError:
            pass
        except OSError:
            return False
    return True


def trusted(ctx, cmd, run_repo, studio_root, video, sub):
    """Everything §1.1 asks beyond the call's shape; False on any doubt or error."""
    try:
        return _trusted(ctx, cmd, run_repo, studio_root, video, sub)
    except Exception:  # noqa: BLE001 — never a deny: the normal prompt
        return False


def _trusted(ctx, cmd, worktree, studio_root, video, sub):
    if ctx.hook.get("permission_mode") != "default":
        return False
    sc = cmd.script
    text, abs_p = sc.path.get("text"), sc.path.get("abs")
    if not text or not abs_p or any(p in (".", "..") for p in text.split("/")):
        return False
    name = os.path.basename(abs_p)
    if name not in AUTO_SCRIPTS or not abs_p.endswith(SUFFIX + name):
        return False
    prefix = abs_p[:-len(SUFFIX + name)] or "/"
    if os.path.realpath(prefix) != worktree or not _no_link_below(prefix, (".claude", "studio", "scripts", name)):
        return False
    # the run repository does not hold the plugin (developing Studio: another copy of the code)
    from .judge import PLUGIN_SCRIPTS, PLUGIN_SCRIPTS_SPELLED
    roots = (prefix, worktree)
    if any(_inside(p, r) for p in (PLUGIN_SCRIPTS, PLUGIN_SCRIPTS_SPELLED) for r in roots):
        return False
    project = ctx.env.get("CLAUDE_PROJECT_DIR")
    if not project or not os.path.isabs(project):
        return False
    area = Area([prefix, worktree, ctx.cwd, project])
    # environment
    if any(k in ctx.env for k in ENV_OFF) or any(k.startswith("GIT_CONFIG") for k in ctx.env):
        return False
    if _set_in(ENV_OFF, {}, ctx.snap, ("GIT_CONFIG",)):
        return False
    if not _session_env_ok(ctx):
        return False
    # the s2v checkout the scripts run with node
    from .. import machine
    s2v = machine.s2v_path(worktree)
    if s2v is None or area.inside(s2v):
        return False
    # every PATH the call may use, and the programs on it
    pvs = [ctx.env.get("PATH", "")]
    if ctx.snap is not None and ctx.snap.paths:
        pvs += list(ctx.snap.paths)
    w0 = cmd.words[0].value
    run = cmd.run_cwds or cmd.cwds or [ctx.cwd]
    folders = [run[0], ctx.cwd, project]
    for pv in pvs:
        if not _path_ok(pv, area):
            return False
        if not python_ok(w0, pv, ctx, area, folders):
            return False
        for prog, name_re in PROGRAMS:
            if not program_ok(_which(prog, pv), name_re, area):
                return False
    # the interpreter is not the repository's own (a venv in it)
    found = [w0] if "/" in w0 else [_which(w0, pv) for pv in pvs]
    for p in found:
        for folder in (os.path.dirname(p), os.path.dirname(os.path.dirname(p))):
            if os.path.exists(os.path.join(folder, "pyvenv.cfg")) and area.inside(folder):
                return False
    if video is not None and not _video_ok(prefix, worktree, studio_root, video, sub):
        return False
    if not copy_intact(prefix):
        return False
    return git_config_ok(ctx, worktree)


def describe(name, sub, video):
    what = "state.py %s" % sub if name == "state.py" else name
    return "runs Studio's %s%s (repository copy, intact; read and record only)" % (
        what, " for %s" % video if video else "")

