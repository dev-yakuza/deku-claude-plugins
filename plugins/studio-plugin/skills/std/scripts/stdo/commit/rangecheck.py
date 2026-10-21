"""`check_commit.py --range <a>..<b>` / `--since-last` (m0e-plan §8): every commit of a range, after an
integration that did not pass the pre-commit hook. Machine-only (local/) paths fail; commits mixing Studio
and other paths only warn (they may be someone else's); no approval check (another person's video has no
state on this machine)."""

import datetime
import json
import os

from .. import ignore
from .approvals import Problem

REL = os.path.join(".claude", "studio", "local", "last-checked.json")


def _changed(git, commit, parents, added=False):
    """Paths the commit changed (`added`: present after it — additions and modifications, no deletions)."""
    filt = ["--diff-filter=d"] if added else []
    if not parents:
        raw = git.text("diff-tree", "-r", "-z", "--no-commit-id", "--name-only", "--no-renames", "--root", *(filt + [commit]))
        return set(p for p in raw.split("\0") if p)
    sets = []
    for par in parents:
        raw = git.text("diff", "--name-only", "-z", "--no-renames", "--no-ext-diff", *(filt + [par, commit, "--"]))
        sets.append(set(p for p in raw.split("\0") if p))
    out = sets[0]
    for s in sets[1:]:
        out &= s  # a merge: only what differs from every parent was made by the merge itself
    return out


def check(ctx, spec):
    """(code, problems, warnings, commits)."""
    if ".." not in spec:
        return 2, [Problem(2, "a range is <a>..<b>")], [], []
    a, b = spec.split("..", 1)
    for rev in (a, b or "HEAD"):
        if not ctx.git.ok("rev-parse", "-q", "--verify", rev + "^{commit}"):
            return 2, [Problem(2, "unknown revision %s" % rev)], [], []
    lines = ctx.git.text("rev-list", "--reverse", "--parents", "%s..%s" % (a, b or "HEAD")).split("\n")
    return check_lines(ctx, lines)


def check_lines(ctx, lines):
    """The checks of `check` over `rev-list --parents` lines (shared with the guard's push check)."""
    problems, warnings, commits = [], [], []
    for line in lines:
        if not line.strip():
            continue
        ids = line.split()
        c, parents = ids[0], ids[1:]
        paths = sorted(_changed(ctx.git, c, parents))
        local = sorted(p for p in _changed(ctx.git, c, parents, added=True) if ctx.cls.is_local(p))
        studio = [p for p in paths if ctx.cls.is_studio(p) or p == ".gitignore" and _gi_block_changed(ctx, c, parents)]
        other = [p for p in paths if p not in studio]
        for p in local:
            problems.append(Problem(1, "commit %s adds or changes machine-only Studio file %s (local/) in the history" % (c[:12], p),
                                    p))
        if studio and [p for p in other if not ctx.cls.is_local(p)]:
            warnings.append("commit %s mixes Studio paths with other paths" % c[:12])
        commits.append({"commit": c, "studio_paths": studio, "local_paths": local,
                        "mixed": bool(studio and other)})
    return (1 if problems else 0), problems, warnings, commits


def _gi_block_changed(ctx, c, parents):
    from .spaths import gitignore_block
    mine = gitignore_block(ctx.git.show("%s:.gitignore" % c))
    if not parents:
        return mine is not None
    return all(gitignore_block(ctx.git.show("%s:.gitignore" % p)) != mine for p in parents)


def since_last(ctx):
    """The range from the last checked HEAD (falls back to the merge base with the upstream)."""
    try:
        with open(os.path.join(ctx.top, REL), encoding="utf-8") as f:
            last = json.load(f).get("head")
    except (OSError, ValueError, AttributeError):
        last = None
    if last and ctx.git.ok("merge-base", "--is-ancestor", last, "HEAD"):
        return "%s..HEAD" % last
    for up in ("@{upstream}", "origin/HEAD"):
        if ctx.git.ok("rev-parse", "-q", "--verify", up + "^{commit}"):
            mb = ctx.git.run("merge-base", "HEAD", up, check=False)
            if mb.returncode == 0:
                return "%s..HEAD" % mb.stdout.decode().strip()
    return None


def record(ctx):
    local = os.path.join(ctx.top, ".claude", "studio", "local")
    if not os.path.isdir(local):
        try:
            with open(os.path.join(ctx.git.common_dir(), "info", "exclude"), encoding="utf-8") as f:
                if not ignore.ok(f.read(), ctx.roots[0]):
                    return False
        except OSError:
            return False
        os.makedirs(local, exist_ok=True)
    p = os.path.join(ctx.top, REL)
    tmp = "%s.tmp.%d" % (p, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"schema": 1, "head": ctx.head, "at": datetime.datetime.now(datetime.timezone.utc)
                   .strftime("%Y-%m-%dT%H:%M:%SZ")}, f)
        f.write("\n")
    os.replace(tmp, p)
    return True
