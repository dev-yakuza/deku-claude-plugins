"""When the guard may answer `allow` (m0d2-plan §4.4, v2 MAJOR): allow covers the whole Bash call, so the
call must be exactly the approved command — optionally after `cd <literal> &&` — with no environment
changes anywhere, no alias, wrapper or function in the way, a plain interpreter / git that resolves to the
same file the guard would run, and harmless redirections only. Anything else gets no decision (the normal
permission prompt); the evidence written for state.py still holds."""

import os
import re

from . import where

PY_NAME = re.compile(r"^python3(\.\d+)?$")
PY_ABS = ("/usr/bin/python3",)
PY_OPTS = ("-B", "-I")
SUBST_PROGS = ("cat", "printf", "echo")


def _redir_ok(r):
    t = r.target.value if r.target is not None else None
    if r.op == ">&" and r.fd == "2" and t == "1":
        return True
    if r.op in (">", "&>") and r.fd in (None, "1", "2") and t == "/dev/null":
        return True
    return False


def _plain(c, lock_ok=False):
    flags = set(c.flags)
    if lock_ok and c.ctx == ["lock-child"]:
        flags.discard("exec-by-program")  # lock.py runs its child itself (not the shell)
    return not flags and not c.aliases and c.alt is None and not c.wrappers and not c.env.ops and \
        (c.lock is None or lock_ok)


def _resolves_same(ctx, name):
    """A bare program name resolves to the same real file on every PATH the call may use and on the guard's PATH."""
    mine = where.which(name, ctx.env.get("PATH", ""), ctx.fs)
    if mine is None:
        return False
    mine = os.path.realpath(mine)
    pvs = list(ctx.snap.paths) if getattr(ctx, "snap", None) is not None and ctx.snap.paths else [ctx.env.get("PATH", "")]
    for pv in pvs:
        p = where.which(name, pv, ctx.fs)
        if p is None or os.path.realpath(p) != mine:
            return False
    return True


def _python_script_ok(ctx, cmd):
    """`python3|python3.N|/usr/bin/python3 [-B|-I]… <script>`: the interpreter is plain and resolves like the guard's."""
    w0 = cmd.words[0].value if cmd.words else None
    if w0 is None:
        return False
    if "/" in w0:
        if w0 not in PY_ABS:
            return False
    elif not PY_NAME.match(w0) or not _resolves_same(ctx, w0):
        return False
    sc = cmd.script
    text = sc.path.get("text") if sc is not None and isinstance(sc.path, dict) else None
    vals = [w.value for w in cmd.words]
    if text is None or text not in vals[1:]:
        return False
    opts = vals[1:vals.index(text, 1)]
    return all(o in PY_OPTS for o in opts)


def _program_ok(ctx, cmd, kind):
    w0 = cmd.words[0].value if cmd.words else None
    if w0 is None:
        return False
    if kind == "s2v":
        return w0 == "s2v" and _resolves_same(ctx, "s2v")
    if kind == "state":
        return _python_script_ok(ctx, cmd)
    if kind == "commit":
        if "/" in w0:
            mine = where.which("git", ctx.env.get("PATH", ""), ctx.fs)
            return mine is not None and os.path.realpath(w0) == os.path.realpath(mine)
        return w0 == "git" and _resolves_same(ctx, "git")
    return False


CLEANUP = ("strip", "whitespace", "verbatim", "scissors", "default")
COMMIT_FLAGS = ("-q", "--quiet", "-s", "--signoff", "--no-edit", "--allow-empty")


def _file_ok(ctx, cmd, value):
    """`-F <file>`: a regular file inside the repository (no /etc/hosts, ~/.ssh, /dev/stdin, FIFO, outside symlink)."""
    run = cmd.run_cwds or cmd.cwds or []
    if len(run) != 1 or not value or value == "-":
        return False
    p = os.path.realpath(os.path.join(run[0], os.path.expanduser(value)))
    repo = ctx.where.git_repo(run[0]) if ctx.fs.exists(run[0]) else None
    if repo is None:
        return False
    wt = os.path.realpath(repo.worktree)
    if not p.startswith(wt.rstrip("/") + "/") or os.path.relpath(p, wt).split(os.sep)[0] == ".git":
        return False
    return os.path.isfile(p)  # follows the link; isfile is False for FIFOs and devices


def _commit_shape(cmd, ctx=None):
    """Indexes (in cmd.words) of message values — the only words that may be dynamic — when the call is exactly
    `git commit` with whitelisted options; None otherwise (no global options such as -c/-C/--git-dir, no editor,
    signing, trailers, templates, amend or pathspecs: each can run a program or change what is committed)."""
    words = cmd.words
    if len(words) < 2 or words[1].value != "commit":
        return None
    msg = set()
    i = 2
    while i < len(words):
        v = words[i].value
        if v is None:
            return None
        if v in ("-m", "--message"):
            if i + 1 >= len(words):
                return None
            msg.add(i + 1)
            i += 2
            continue
        if v in ("-F", "--file"):
            if i + 1 >= len(words) or ctx is None or not _file_ok(ctx, cmd, words[i + 1].value):
                return None
            i += 2
            continue
        if v.startswith("--message=") or (v.startswith("-m") and len(v) > 2 and not v.startswith("--")):
            i += 1
            continue
        if (v.startswith("--file=") or (v.startswith("-F") and len(v) > 2)) and ctx is not None and \
                _file_ok(ctx, cmd, v[len("--file="):] if v.startswith("--file=") else v[2:]):
            i += 1
            continue
        if v.startswith("--cleanup=") and v.split("=", 1)[1] in CLEANUP:
            i += 1
            continue
        if v in COMMIT_FLAGS:
            i += 1
            continue
        return None
    return msg


def sole(ctx, sc, cmd, kind):
    """True when the call is just `cmd` (kind: state | commit)."""
    if sc is None or sc.status != "ok":
        return False
    for o in sc.opaque:
        if not (kind in ("state", "s2v") and o.kind == "script" and o.cmd in (cmd.id, cmd.parent)):
            return False
    subs = [c for c in sc.commands if "cmdsubst" in c.ctx]
    lock = None
    if kind == "s2v" and cmd.parent is not None:
        # `lock.py actor-op … -- s2v …`: the wrapper and its one child count as one command (both plain)
        lock = next((c for c in sc.commands if c.id == cmd.parent), None)
        kids = [c for c in sc.commands if c.parent == cmd.parent]
        if lock is None or lock.lock is None or kids != [cmd] or cmd.ctx != ["lock-child"] or \
                not _python_script_ok(ctx, lock):
            return False
    tops = sorted((c for c in sc.commands if "cmdsubst" not in c.ctx and c.ctx != ["lock-child"]),
                  key=lambda c: c.span[0])
    last = lock if lock is not None else cmd
    if not tops or tops[-1] is not last:
        return False
    for c in sc.commands:
        if not _plain(c, lock_ok=lock is not None and c in (lock, cmd)):
            return False
    raw = sc.raw
    prev_end = 0
    for i, c in enumerate(tops):
        if set(c.ctx) - {"cond"}:
            return False
        gap = raw[prev_end:c.span[0]].strip()
        if gap != ("" if i == 0 else "&&"):
            return False
        prev_end = c.span[1]
        if c is last:
            continue
        if [w.value for w in c.words][:1] != ["cd"] or len(c.words) != 2 or c.words[1].value is None or c.redirs:
            return False
    if raw[prev_end:].strip():
        return False
    if not all(_redir_ok(r) for r in cmd.redirs) or (lock is not None and not all(_redir_ok(r) for r in lock.redirs)):
        return False
    if not _program_ok(ctx, cmd, kind):
        return False
    dyn = [i for i, w in enumerate(cmd.words) if w.value is None]
    if kind in ("state", "s2v"):
        return not dyn and not subs and (lock is None or all(w.value is not None for w in lock.words))
    allowed = _commit_shape(cmd, ctx)
    if allowed is None:
        return False
    if any(i not in allowed for i in dyn):
        return False
    for c in subs:
        if c.ctx != ["cmdsubst"] or c.prog not in SUBST_PROGS:
            return False
        if not (cmd.span[0] <= c.span[0] and c.span[1] <= cmd.span[1]):
            return False
        if any(r.mode not in ("heredoc", "herestring") for r in c.redirs):
            return False
        if c.prog == "cat" and (len(c.words) != 1 or not c.redirs):
            return False  # cat only of the here-document, never of a file
        if any(w.value is None for w in c.words):
            return False
    return True
