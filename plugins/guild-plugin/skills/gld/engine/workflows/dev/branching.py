"""workflows.dev.branching — execute Step 0 (b)/(c): base, branch, and the Issue's worktree (catalog B
P0.10–P0.13, D-0.5–D-0.8, J-B1–J-B4, design §3.4 BRANCH; K3 carry-over 5).

* `resolve_base(root, injected, default)` — D-0.5 / F-6: an injected `GLD_SPRINT_BASE` must exist,
  be `origin/<default>` or an Issue-token branch that is not release-shaped, and differ from HEAD.
* `candidates(root, n, base, current, related=None)` — J-B1 token rule, drop `== base`, empty log
  and not current, release-shaped; a NON-empty log goes to MJ-BRANCH (`related(name, log)` →
  related | unrelated | unsure → drop, S:142).
* `decide(cands, loopback_branch, current)` — 1 → resume, 0 → fresh, >1 → the loop-back's branch,
  else the current one, else ambiguous (NH `ambiguous branch`).
* `worktree_path(main, n)` / `prepare(...)` — the production worktree: `git worktree add` with the
  engine's git (hooks off — no post-checkout hook runs), OUTSIDE `$TMPDIR` (K1r2: the sandbox always
  allows TMPDIR writes, so a worktree there is not write-protected for reader roles), then the
  same git-ignored preparation the measurement clones needed: the repo's `engine.effective.
  copy_ignored` list copied from the main checkout with the K2 containment rules (relative, no
  `..`, no glob, git-ignored, no symlink on either path, source inside the repo).
"""

import os
import re
import shutil

from guildcore import checks as CH
from guildcore.adapters import git as G

RELEASE_RE = re.compile(r"^(release|support|hotfix|maint(enance)?)/|^v?\d+(\.\d+)+$")
TMP_ROOTS = ("/tmp", "/private/tmp", "/var/folders", "/private/var/folders")
BLOCKED_RE = re.compile(r"would be overwritten|already checked out|is already used by worktree|"
                        r"already exists|is already checked out", re.I)


class BranchProblem(Exception):
    """kind ∈ ambiguous | blocked | base-unusable | base-missing; `line` = the NH text."""

    def __init__(self, kind, line):
        Exception.__init__(self, line)
        self.kind, self.line = kind, line


def _g(root, *args):
    return G.run(root, *args, check=False).decode("utf-8", "replace")


def default_branch(root):
    ref = _g(root, "symbolic-ref", "-q", "refs/remotes/origin/HEAD").strip()
    return ref[len("refs/remotes/origin/"):] if ref.startswith("refs/remotes/origin/") else None


def resolve_base(root, injected, default, n=None):
    if injected:
        v = injected.strip()
        if not G.ok(root, "rev-parse", "--verify", "-q", v):
            raise BranchProblem("base-unusable", "injected base %s is not usable for #%s" % (v, n))
        conv = (default and v == "origin/%s" % default) or (
            not RELEASE_RE.search(v.split("/", 1)[-1]) and re.search(r"(?<![0-9.])\d+(?![0-9])", v))
        head = _g(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
        if not conv or v == head:
            raise BranchProblem("base-unusable", "injected base %s is not usable for #%s" % (v, n))
        return v
    if not default:
        raise BranchProblem("base-missing", "could not resolve the base branch for #%s" % n)
    return default


def recover_base(root, base, default):
    """D-0.8 by shape. Returns None (now available) or the FAIL line."""
    if G.ok(root, "rev-parse", "--verify", "-q", base):
        return None
    return "base branch %s is not available locally — fetch it and re-run" % base


def local_branches(root):
    return [x for x in _g(root, "for-each-ref", "--format=%(refname:short)", "refs/heads").split("\n") if x]


def candidates(root, n, base, current, related=None):
    out = []
    for b in CH.branch_candidates(n, local_branches(root)):
        if b == base or b == (base or "").replace("origin/", "", 1):
            continue
        log = _g(root, "log", "--oneline", "%s..%s" % (base, b)).strip()
        if not log:
            if b != current or RELEASE_RE.search(b):
                continue
        elif RELEASE_RE.search(b):
            continue
        elif related is not None and related(b, log) != "related":
            continue
        out.append(b)
    return out


def decide(cands, loopback_branch=None, current=None):
    if len(cands) == 1:
        return cands[0]
    if not cands:
        return None
    if loopback_branch in cands:
        return loopback_branch
    if current in cands:
        return current
    raise BranchProblem("ambiguous", "has more than one branch (%s) — tell me which to continue" % ", ".join(cands))


def worktree_path(main, n):
    main = os.path.realpath(main)
    p = os.path.join(os.path.dirname(main), ".gld-%s-%d" % (os.path.basename(main), int(n)))
    assert_outside_tmp(p)
    return p


def assert_outside_tmp(path):
    rp = os.path.realpath(os.path.dirname(path) if not os.path.exists(path) else path)
    roots = list(TMP_ROOTS)
    t = os.environ.get("TMPDIR")
    if t:
        roots.append(os.path.realpath(t).rstrip("/"))
    for r in roots:
        if rp == r or rp.startswith(r.rstrip("/") + "/"):
            raise BranchProblem("blocked", "worktree %s would be inside a temp root (%s) — the sandbox "
                                "cannot protect it" % (path, r))


def _is_worktree_on(main, path, branch):
    lst = _g(main, "worktree", "list", "--porcelain")
    cur = None
    for ln in lst.split("\n"):
        if ln.startswith("worktree "):
            cur = os.path.realpath(ln[len("worktree "):])
        elif ln.startswith("branch ") and cur == os.path.realpath(path):
            return ln[len("branch "):] == "refs/heads/%s" % branch
    return False


def prepare(main, path, branch, base, fresh, copy_list=()):
    """Create (or reuse) the Issue worktree; returns {path, created, copied, refused}."""
    assert_outside_tmp(path)
    created = False
    if os.path.exists(path):
        if not _is_worktree_on(main, path, branch):
            raise BranchProblem("blocked", "cannot switch to the branch %s — %s exists and is not its worktree"
                                % (branch, path))
    else:
        try:
            if fresh:
                G.run(main, "worktree", "add", "--no-track", "-b", branch, path, base)
            else:
                G.run(main, "worktree", "add", path, branch)
        except G.GitError as e:
            if BLOCKED_RE.search(str(e)):
                hint = ""
                if "already checked out" in str(e) or "already used by worktree" in str(e):
                    hint = (" — the branch is checked out in another checkout (often the main one): switch "
                            "that checkout to another branch (e.g. the base) and run again")      # K3r1-m11
                raise BranchProblem("blocked", "cannot %s branch %s — %s%s" % (
                    "create the" if fresh else "switch to the", branch, str(e).split("\n")[0], hint))
            raise
        created = True
    copied, refused = copy_ignored(main, path, copy_list)
    return {"path": path, "created": created, "copied": copied, "refused": refused}


def copy_ignored(main, dest, paths):
    """`engine.effective.copy_ignored` into the worktree (K2 containment rules)."""
    copied, refused = [], []
    real_main = os.path.realpath(main)
    real_dest = os.path.realpath(dest)
    for raw in paths or []:
        rel = os.path.normpath(raw or "")
        bad = (not raw or os.path.isabs(raw) or rel.startswith("..") or rel == "." or any(c in raw for c in "*?[")
               or not G.ok(main, "check-ignore", "-q", "--", rel))
        if not bad:
            for root in (main, dest):
                cur = root
                for part in rel.split(os.sep):
                    cur = os.path.join(cur, part)
                    if os.path.islink(cur):
                        bad = True
        src = os.path.join(main, rel)
        dst = os.path.join(dest, rel)
        if not bad and (not os.path.exists(src) or not os.path.realpath(src).startswith(real_main + os.sep)
                        or not os.path.realpath(os.path.dirname(dst) if not os.path.exists(os.path.dirname(dst))
                                                else dst).startswith(real_dest)):
            bad = True
        if bad:
            refused.append(raw)
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.isdir(src):
            if os.path.lexists(dst):
                shutil.rmtree(dst, True)
            shutil.copytree(src, dst, symlinks=True,
                            ignore=lambda d, names: [x for x in names if os.path.islink(os.path.join(d, x))])
        else:
            shutil.copy2(src, dst)
        copied.append(rel)
    return copied, refused
