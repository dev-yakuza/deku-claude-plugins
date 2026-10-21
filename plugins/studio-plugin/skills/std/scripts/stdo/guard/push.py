"""`git push` in a harness repository (m0d2-plan §6): never judged as a whole — only a leak is refused
(machine-only local/ files, internal video or actor ids in the pushed commits); anything else is at most a
warning. The range is checked with check_commit's own range function through the guard's budgeted git."""

MAX_COMMITS = 200
OPT_VALUE = ("--repo", "--receive-pack", "--exec", "-o", "--push-option", "--signed")


def parse(args):
    """(remote, [refspecs], partial, dry_run)."""
    vals = [w.value for w in args]
    pos, partial, dry = [], False, False
    i = 0
    while i < len(vals):
        a = vals[i]
        if a is None:
            partial = True
        elif a in ("--all", "--mirror", "--tags", "--branches", "--follow-tags"):
            partial = True
        elif a in ("-n", "--dry-run"):
            dry = True
        elif a in OPT_VALUE:
            i += 1
        elif a.startswith("-"):
            pass
        else:
            pos.append(a)
        i += 1
    remote = pos[0] if pos else None
    refs = pos[1:]
    if len(refs) > 1:
        partial = True
    return remote, refs, partial, dry


def check(worktree, env, args, internal_ids, budget=3.0):
    """(deny text | None, [warnings])."""
    from ..commit import checks, gitx, kinds, rangecheck
    from . import gitprobe
    remote, refs, partial, dry = parse(args)
    if dry:
        return None, []
    warnings = []
    try:
        git = gitprobe.budget_git(worktree, env, budget=budget, max_calls=2 * MAX_COMMITS + 20)
        cctx = checks.Ctx(git, env, kinds.registry({}))
        branch = "HEAD"
        if refs and not partial:
            src = refs[0].lstrip("+").split(":", 1)[0]
            if src:
                branch = src
        if partial:
            warnings.append("only HEAD's commits were checked (several refs are pushed)")
        up = git.run("rev-parse", "-q", "--verify", "--symbolic-full-name", branch + "@{upstream}", check=False)
        base = None
        if up.returncode == 0 and up.stdout.strip():
            base = up.stdout.decode().strip()
        else:
            r = remote or "origin"
            dh = git.run("rev-parse", "-q", "--verify", "refs/remotes/%s/HEAD" % r, check=False)
            if dh.returncode == 0 and dh.stdout.strip():
                mb = git.run("merge-base", branch, dh.stdout.decode().strip(), check=False)
                if mb.returncode == 0 and mb.stdout.strip():
                    base = mb.stdout.decode().strip()
        if base is None:
            return None, warnings + ["could not tell which commits this push sends: not checked"]
        cnt = git.text("rev-list", "--count", "%s..%s" % (base, branch)).strip()
        if not cnt.isdigit():
            return None, warnings + ["could not count the pushed commits: not checked"]
        if int(cnt) > MAX_COMMITS:
            return None, warnings + ["%s commits are pushed: more than the guard checks (%d)" % (cnt, MAX_COMMITS)]
        code, problems, warns, commits = rangecheck.check(cctx, "%s..%s" % (base, branch))
        warnings += list(warns)
        leaks = [p.message for p in problems if p.code == 1]
        if code == 2:
            warnings.append("; ".join(p.message for p in problems))
        for c in commits:
            for p in c.get("studio_paths") or []:
                parts = p.split("/")
                for r in cctx.roots:
                    rp = r.split("/")
                    n = len(rp)
                    if parts[:n] == rp and len(parts) > n + 1 and parts[n] in ("videos", "cast") and \
                            parts[n + 1] in internal_ids:
                        leaks.append("commit %s adds %s of internal %s %s" % (c["commit"][:12], p,
                                                                             "video" if parts[n] == "videos" else "actor",
                                                                             parts[n + 1]))
                        break
        if leaks:
            return ("git push would publish machine-only or internal Studio files: %s. Remove them from the history "
                    "first (ask the person)." % "; ".join(sorted(set(leaks))[:3])), warnings
        return None, warnings
    except gitx.GitError as e:
        return None, warnings + ["the push could not be checked (%s)" % e]
