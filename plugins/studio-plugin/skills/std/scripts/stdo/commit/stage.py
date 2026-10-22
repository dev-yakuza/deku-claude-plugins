"""`check_commit.py --stage <kind> [<target>]` (m0e-plan §7.2): stage a kind's allow-list, check it
again, and write commit-ok.json with `git write-tree`. During a merge/cherry-pick/revert/rebase only the
Studio paths made while resolving conflicts are staged and checked; commit-ok is bound to that HEAD."""

import os
import shutil

from .. import ignore
from . import checks, okfile, spaths, summary
from .approvals import Problem


def _index_file(ctx):
    p = ctx.env.get("GIT_INDEX_FILE")
    if p:
        return p if os.path.isabs(p) else os.path.join(ctx.top, p)
    return ctx.git.git_path("index")


def _stage_gitignore_block(ctx):
    """Stage only the Studio block of the work tree's .gitignore (other hunks stay unstaged)."""
    with open(os.path.join(ctx.top, spaths.GITIGNORE), "rb") as f:
        work = f.read().decode("utf-8", "surrogateescape")
    _rest, block = ignore.split(work)
    if block is None:
        raise ignore.BlockError(".gitignore has no Studio block")
    base = ctx.git.show("%s:%s" % (ctx.head, spaths.GITIGNORE)) if ctx.head else None
    new = ignore.ensure((base or b"").decode("utf-8", "surrogateescape"), block)
    sha = ctx.git.text("hash-object", "-w", "--stdin", input=new.encode("utf-8", "surrogateescape")).strip()
    ctx.git.run("update-index", "--add", "--cacheinfo", "100644,%s,%s" % (sha, spaths.GITIGNORE))


def run(ctx, kind_name, target):
    """(code, problems, result dict | None)."""
    if not ctx.harness:
        return 2, [Problem(2, "no Studio harness here (.claude/studio/config.json is missing)")], None
    if ctx.cfg_error:
        return 2, [Problem(2, ctx.cfg_error)], None
    if kind_name not in ctx.kinds:
        return 2, [Problem(2, "unknown commit kind %r (%s)" % (kind_name, ", ".join(sorted(ctx.kinds))))], None
    kind = ctx.kinds[kind_name]
    if kind is None:
        return 3, checks.kind_problems(ctx, kind_name, []), None
    st = checks.Staged(ctx)
    problems = checks.local_problems(st)
    lp = checks.local_link_problem(ctx)
    if lp:
        problems.append(lp)
    if not st.progress:
        others = [p for p in st.other]
        if others:
            problems.append(Problem(1, "other changes are already staged (%s) — commit or unstage them first "
                                       "(Studio does not touch them)" % ", ".join(others[:10])))
    g = checks.guard_ran_problem(ctx)
    if g:
        problems.append(g)
    if getattr(kind, "needs_overlay", True):
        o = checks.overlay_problem(ctx)
        if o:
            problems.append(o)
    problems += checks.ignore_problems(ctx, index=False)
    if problems:
        return checks.code_of(problems), problems, None
    col = kind.collect(ctx, target)
    if col.problems:
        return checks.code_of(col.problems), col.problems, None
    if not col.paths and not col.gitignore:
        return 1, [Problem(1, "nothing to stage for this %s commit" % kind_name)], None
    index = _index_file(ctx)
    backup = index + ".studio-stage"
    had_index = os.path.exists(index)
    if had_index:
        shutil.copy2(index, backup)
    try:
        if col.paths:
            idx = set(x for x in ctx.git.text("ls-files", "-z", "--", *[":(literal)" + p for p in col.paths]).split("\0")
                      if x)
            # a deletion already staged is neither on disk nor in the index: nothing to add for it
            todo = [p for p in col.paths if p in idx or os.path.lexists(os.path.join(ctx.top, p))]
            if todo:
                ctx.git.run("add", "-A", "--", *[":(literal)" + p for p in todo])
        if col.gitignore:
            _stage_gitignore_block(ctx)
        ctx.git.index_changed()
        after = checks.Staged(ctx)
        bad = checks.local_problems(after)
        want = set(col.paths) | ({spaths.GITIGNORE} if col.gitignore else set())
        if after.progress:
            got = set(after.studio)
            if not got:
                bad.append(Problem(3, "no Studio changes to finish this %s — just run git commit (or --continue)"
                                      % after.progress))
            elif not got <= want:
                bad.append(Problem(1, "conflict-resolution Studio paths outside this commit's list: %s"
                                      % ", ".join(sorted(got - want)[:10])))
        else:
            got = set(after.studio) | set(after.other)
            if got != want:
                bad.append(Problem(1, "the staged result differs from the allow-list (%s)"
                                      % ", ".join(sorted(got ^ want)[:10])))
        bad += checks.kind_problems(ctx, kind_name, after.studio)
        if bad:
            raise _Undo(bad)
        tree = ctx.git.write_tree()
        claude, sid = checks.session(ctx.env)
        line, prot, _agents = summary.compute(ctx, sorted(after.studio), tree)
        data = okfile.write(ctx.top, {
            "tree": tree, "head": ctx.head, "kind": kind_name, "target": target, "studio_root": ctx.roots[0],
            "paths": sorted(after.studio), "states": col.states, "session_id": sid if claude else None,
            "summary": line, "protected_changes": prot,
            "in_progress": after.progress, "scripts_version": checks.scripts_version()})
    except _Undo as u:
        _restore(index, backup, had_index)
        return checks.code_of(u.problems), u.problems, None
    except BaseException:
        _restore(index, backup, had_index)
        raise
    if had_index:
        os.remove(backup)
    return 0, [], data


class _Undo(Exception):
    def __init__(self, problems):
        Exception.__init__(self, "undo")
        self.problems = problems


def _restore(index, backup, had_index):
    if had_index:
        os.replace(backup, index)
    elif os.path.exists(index):
        os.remove(index)
