"""Recognizers on an argv of Words (m0d1a-plan §6.3-§6.6): s2v call forms, git global options,
per-command cwd options, interpreters and their inline code / script / stdin."""

import os
import re
import unicodedata

from .. import s2vcall
from . import where
from .model import GitInfo, S2vForm

SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "mksh", "yash", "fish"}
PY_RE = re.compile(r"^(python|pypy)[0-9.]*$")
NODE_RE = re.compile(r"^(node|nodejs)[0-9]*$")
INLINE_FLAGS = {"perl": ("-e", "-E"), "ruby": ("-e",), "php": ("-r",), "lua": ("-e",), "osascript": ("-e",),
                "rscript": ("-e",)}
BIN_DIRS = ("/bin/", "/usr/bin/", "/sbin/", "/usr/sbin/", "/usr/local/bin/", "/opt/homebrew/bin/")
STDIN_TARGETS = ("-", "/dev/stdin", "/dev/fd/0")
S2V_MAIN = os.path.join("packages", "cli", "dist", "main.js")
S2V_SRC = os.path.join("packages", "cli", "src", "main.ts")


def key(text):
    return unicodedata.normalize("NFC", text).casefold() if text is not None else None


def base(text):
    return text.rsplit("/", 1)[-1] if text else text


def vals(words):
    return [w.value for w in words]


# ---- interpreters ----

def interp_family(prog):
    k = key(prog) or ""
    if k in SHELLS:
        return "shell"
    if PY_RE.match(k):
        return "python"
    if NODE_RE.match(k) or k in ("bun", "deno", "tsx", "ts-node"):
        return "node"
    if k in INLINE_FLAGS:
        return "inline"
    return None


def parse_interp(family, prog, args):
    """(mode, value_word_or_text, rest) with mode in inline|script|stdin|module|other."""
    a = list(args)
    k = key(prog)
    i = 0
    if family == "shell":
        inline = stdin = False
        while i < len(a):
            v = a[i].value
            if v is None:
                return "other", None, a[i:]
            if v == "--" or v == "-":
                i += 1
                break
            if v in ("-o", "+o"):
                i += 2
                continue
            if re.match(r"^[-+][A-Za-z]+$", v):
                if "c" in v[1:] and v[0] == "-":
                    inline = True
                if "s" in v[1:] and v[0] == "-":
                    stdin = True
                i += 1
                continue
            break
        rest = a[i:]
        if inline:
            return ("inline", rest[0], rest[1:]) if rest else ("inline", None, [])
        if stdin or not rest:
            return "stdin", None, rest
        return "script", rest[0], rest[1:]
    if family == "python":
        while i < len(a):
            v = a[i].value
            if v is None:
                return "other", None, a[i:]
            if v == "-c":
                return ("inline", a[i + 1], a[i + 2:]) if i + 1 < len(a) else ("inline", None, [])
            if v.startswith("-c") and len(v) > 2:
                from .model import Word
                return "inline", Word.lit(v[2:]), a[i + 1:]
            if v == "-m" or (v.startswith("-m") and len(v) > 2):
                return "module", a[i + 1] if v == "-m" and i + 1 < len(a) else None, a[i + 2:]
            if v in ("-W", "-X", "-Q"):
                i += 2
                continue
            if v in STDIN_TARGETS:
                return "stdin", None, a[i + 1:]
            if v.startswith("-") and v != "-":
                i += 1
                continue
            break
        rest = a[i:]
        if not rest:
            return "stdin", None, []
        if rest[0].value in STDIN_TARGETS:
            return "stdin", None, rest[1:]
        return "script", rest[0], rest[1:]
    if family == "node":
        if k == "deno":
            if a and a[0].value == "eval":
                return ("inline", a[1], a[2:]) if len(a) > 1 else ("inline", None, [])
            if a and a[0].value == "run":
                a = a[1:]
                while a and a[0].value and a[0].value.startswith("-"):
                    a = a[1:]
                return ("script", a[0], a[1:]) if a else ("other", None, [])
            return "other", None, a
        if k == "bun" and a and a[0].value == "run":
            a = a[1:]
        while i < len(a):
            v = a[i].value
            if v is None:
                return "other", None, a[i:]
            if v in ("-e", "--eval", "-p", "--print"):
                return ("inline", a[i + 1], a[i + 2:]) if i + 1 < len(a) else ("inline", None, [])
            for flag in ("--eval=", "--print="):
                if v.startswith(flag):
                    from .model import Word
                    return "inline", Word.lit(v[len(flag):]), a[i + 1:]
            if v in ("-r", "--require", "--import", "--loader", "-C", "--conditions", "--input-type"):
                i += 2
                continue
            if v == "-":
                return "stdin", None, a[i + 1:]
            if v.startswith("-"):
                i += 1
                continue
            break
        rest = a[i:]
        if not rest:
            return "stdin", None, []
        if rest[0].value in STDIN_TARGETS:
            return "stdin", None, rest[1:]
        return "script", rest[0], rest[1:]
    if family == "inline":
        flags = INLINE_FLAGS[k]
        codes = []
        while i < len(a):
            v = a[i].value
            if v in flags and i + 1 < len(a):
                codes.append(a[i + 1])
                i += 2
                continue
            if v and any(v.startswith(f) and len(v) > len(f) for f in flags):
                from .model import Word
                codes.append(Word.lit(v[2:]))
                i += 1
                continue
            if v and v.startswith("-") and v != "-":
                i += 1
                continue
            break
        if codes:
            if any(c.value is None for c in codes):
                return "inline", None, a[i:]
            from .model import Word
            return "inline", Word.lit("\n".join(c.value for c in codes)), a[i:]
        rest = a[i:]
        if k == "osascript" or not rest:
            return ("stdin", None, rest) if not rest else ("script", rest[0], rest[1:])
        return "script", rest[0], rest[1:]
    return "other", None, a


# ---- git ----

GIT_WITH_VALUE = ("-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env",
                  "--super-prefix", "--attr-source", "--list-cmds")


def git_info(words, run_cwd_join):
    """GitInfo from argv words after `git`."""
    g = GitInfo()
    a = list(words)
    i = 0
    while i < len(a):
        v = a[i].value
        if v is None or not v.startswith("-"):
            break
        name, eq, val = v.partition("=")
        if v in GIT_WITH_VALUE:
            nv = a[i + 1].value if i + 1 < len(a) else None
            i += 2
        elif eq and name in GIT_WITH_VALUE:
            nv = val
            i += 1
            v = name
        else:
            i += 1
            continue
        if v == "-C":
            g.c_dirs.append(nv)
        elif v == "-c":
            k, _, cv = (nv or "").partition("=")
            g.configs.append((k, cv))
        elif v == "--git-dir":
            g.git_dir = nv
        elif v == "--work-tree":
            g.work_tree = nv
    if i < len(a):
        g.sub = a[i].value
        g.args = a[i + 1:]
    return g


# ---- per-command cwd options ----

CWD_OPTS = {"yarn": ("--cwd",), "npm": ("--prefix", "-C"), "pnpm": ("-C", "--dir"), "make": ("-C", "--directory"),
            "gmake": ("-C", "--directory"), "tar": ("-C", "--directory"), "gtar": ("-C", "--directory")}


def cwd_option(prog, words):
    """The directory a command switches to for its own work (literal text, '' when dynamic), or None."""
    opts = CWD_OPTS.get(key(prog))
    if not opts:
        return None
    out = None
    for i, w in enumerate(words):
        v = w.value
        if v is None:
            continue
        for o in opts:
            if v == o and i + 1 < len(words):
                nv = words[i + 1].value
                out = nv if nv is not None else ""
            elif v.startswith(o + "=") and o.startswith("--"):
                out = v[len(o) + 1:]
            elif o == "-C" and v.startswith("-C") and len(v) > 2 and key(prog) in ("make", "gmake", "tar", "gtar", "pnpm"):
                out = v[2:]
    return out


# ---- s2v ----

def s2v_like(words):
    """Name/path looks like an s2v call (any runner form)."""
    if not words or words[0].value is None:
        return None
    v0 = words[0].value
    b = key(base(v0))
    if b == "s2v":
        return "path-bin" if "/" in v0 else "name"
    if v0.endswith(S2V_MAIN):
        return "direct-main"
    rest = [w.value for w in words[1:]]
    if b in ("node",) and rest and rest[0] and rest[0].endswith(S2V_MAIN):
        return "node"
    if b == "tsx" and rest and rest[0] and rest[0].endswith(S2V_SRC):
        return "tsx"
    if b in ("yarn", "npx", "pnpm", "bunx", "npm", "pnpx"):
        toks = []
        i = 0
        while i < len(rest):
            x = rest[i]
            if x is None:
                break
            if x in ("--cwd", "-C", "--dir", "--prefix", "-p", "--package"):
                i += 2
                continue
            if x.startswith("-"):
                i += 1
                continue
            toks.append(x)
            i += 1
        if toks and toks[0] in ("run", "exec", "dlx", "x"):
            toks = toks[1:]
        elif toks and toks[0] == "workspace" and len(toks) > 1:
            toks = toks[2:]
        if not toks or key(toks[0]) != "s2v":
            return None
        if b == "yarn" and (rest[:1] == ["s2v"] or (len(rest) > 2 and rest[0] == "--cwd" and rest[2] == "s2v")):
            return "yarn"
        if b == "npx" and rest[:1] == ["s2v"]:
            return "npx"
        return "runner-other"
    return None


def classify_s2v(words, cwd, s2v_path, path_values, fs):
    """S2vForm or None. cwd: the single run cwd (None when unknown)."""
    form = s2v_like(words)
    if form is None:
        return None
    argv = [w.value for w in words]
    if any(v is None for v in argv):
        return S2vForm(form, words[1:], accepted=False, verified=False)
    abs_argv = list(argv)
    if form in ("node", "tsx") and cwd is not None and not os.path.isabs(abs_argv[1]):
        abs_argv[1] = os.path.normpath(os.path.join(cwd, abs_argv[1]))
    accepted = False
    args = None
    if cwd is not None or form == "name":
        try:
            args = s2vcall.s2v_args(abs_argv, s2v_path, cwd or "/")
        except (OSError, ValueError):
            args = None
        accepted = args is not None
    verified = False
    if s2v_path:
        main = os.path.realpath(os.path.join(s2v_path, S2V_MAIN))
        if form == "name":
            found = [where.which("s2v", pv, fs) for pv in path_values] if path_values else [None]
            verified = bool(found) and all(f is not None and os.path.realpath(f) == main for f in found)
        elif form in ("path-bin", "direct-main"):
            p = argv[0] if os.path.isabs(argv[0]) else (os.path.join(cwd, argv[0]) if cwd else None)
            verified = p is not None and os.path.realpath(p) == main
        elif form in ("node", "tsx", "yarn", "npx"):
            verified = accepted
    if args is None:
        # arguments after the s2v word for the display/judgement
        idx = 1
        if form in ("node", "tsx"):
            idx = 2
        elif form in ("yarn", "npx", "runner-other"):
            idx = next((i + 1 for i, v in enumerate(argv) if i > 0 and key(v) == "s2v"), len(argv))
        rest = words[idx:]
    else:
        rest = words[len(words) - len(args):]
    return S2vForm(form, rest, accepted=accepted, verified=verified)


def is_bin_dir(path):
    return path is not None and path.startswith(BIN_DIRS)
