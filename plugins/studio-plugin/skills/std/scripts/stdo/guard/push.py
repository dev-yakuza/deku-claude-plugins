"""`git push` in a harness repository (m0d2-plan §6, M0f sandbox finding H5): only a leak is refused (machine-only
local/ files, internal video or actor ids in the pushed commits); mixed commits are warnings. The commits each pushed
ref sends are resolved per refspec; when they cannot be told, or there are more than the guard checks, the push is
refused in a Studio repository (closed side) — it used to be a warning, which let `git push origin HEAD:main` with no
upstream go unchecked."""

MAX_COMMITS = 200
OPT_VALUE = ("--repo", "--receive-pack", "--exec", "-o", "--push-option", "--signed")


class Unclear(Exception):
    pass


class TooMany(Exception):
    """More commits than the guard checks one by one (a first publish): only the local-path check runs."""

    def __init__(self, src, excludes, n):
        Exception.__init__(self, "%s sends %s commits" % (src, n))
        self.src, self.excludes, self.n = src, excludes, n


def parse(args):
    """{repo, refspecs, all, mirror, tags, follow_tags, dry, dynamic, delete}. With --repo every positional is a
    refspec; without it the first positional is the repository (a remote name or a URL)."""
    vals = [w.value for w in args]
    out = {"repo": None, "refspecs": [], "all": False, "mirror": False, "tags": False, "follow_tags": False,
           "dry": False, "dynamic": False, "delete": False}
    pos = []
    i = 0
    while i < len(vals):
        a = vals[i]
        if a is None:
            out["dynamic"] = True
        elif a in ("--all", "--branches"):
            out["all"] = True
        elif a == "--mirror":
            out["mirror"] = True
        elif a == "--tags":
            out["tags"] = True
        elif a == "--follow-tags":
            out["follow_tags"] = True
        elif a in ("-n", "--dry-run"):
            out["dry"] = True
        elif a in ("-d", "--delete"):
            out["delete"] = True
        elif a == "--repo":
            if i + 1 < len(vals):
                out["repo"] = vals[i + 1]
                if vals[i + 1] is None:
                    out["dynamic"] = True
            i += 1
        elif a.startswith("--repo="):
            out["repo"] = a.split("=", 1)[1]
        elif a in OPT_VALUE:
            i += 1
        elif a.startswith("-"):
            pass
        else:
            pos.append(a)
        i += 1
    if out["repo"] is not None:
        out["refspecs"] = pos
    else:
        out["repo"] = pos[0] if pos else None
        out["refspecs"] = pos[1:]
    return out


def _ok(git, *args):
    r = git.run(*args, check=False)
    return r.stdout.decode("utf-8", "replace").strip() if r.returncode == 0 else None


def _branch_of(git, rev):
    """The short branch name a rev names (HEAD → the current branch), or None."""
    if rev == "HEAD":
        return _ok(git, "symbolic-ref", "-q", "--short", "HEAD")
    full = _ok(git, "rev-parse", "-q", "--verify", "--symbolic-full-name", rev)
    if full and full.startswith("refs/heads/"):
        return full[len("refs/heads/"):]
    return None


def target_remote(git, repo):
    """(what git pushes to, its configured remote name or None for a URL) in git's order: --repo / first positional,
    branch.<b>.pushRemote, remote.pushDefault, branch.<b>.remote, origin."""
    if repo is None:
        b = _branch_of(git, "HEAD")
        for key in (("branch.%s.pushRemote" % b) if b else None, "remote.pushDefault",
                    ("branch.%s.remote" % b) if b else None):
            if key:
                v = _ok(git, "config", "--get", key)
                if v:
                    repo = v
                    break
        repo = repo or "origin"
    name = None
    if repo and "/" not in repo and ":" not in repo:
        url = _ok(git, "config", "--get", "remote.%s.url" % repo)
        push_urls = (_ok(git, "config", "--get-all", "remote.%s.pushurl" % repo) or "").split()
        # a pushurl elsewhere than the fetched url: the remote-tracking refs describe another repository
        if url and all(u == url for u in push_urls):
            name = repo
    return repo, name


def _remote_ref(git, remote, name):
    if not name or not remote:
        return None
    name = name[len("refs/heads/"):] if name.startswith("refs/heads/") else name
    ref = "refs/remotes/%s/%s" % (remote, name)
    return ref if _ok(git, "rev-parse", "-q", "--verify", ref + "^{commit}") else None


def pairs(git, p, name):
    """[(src rev, dst name or None)] the push sends (`name`: the target's remote name, None for a URL)."""
    out = []
    if p["mirror"] or p["all"]:
        heads = (_ok(git, "for-each-ref", "--format=%(refname:short)", "refs/heads/") or "").splitlines()
        out += [(h, h) for h in heads if h]
    for spec in p["refspecs"]:
        spec = spec.lstrip("+")
        src, sep, dst = spec.partition(":")
        if not src:
            continue  # `:dst` deletes a remote ref: nothing is sent
        out.append((src, dst if sep else None))
    if not (p["all"] or p["mirror"] or p["tags"] or p["refspecs"]):
        configured = (_ok(git, "config", "--get-all", "remote.%s.push" % name) or "").split() if name else []
        if configured:
            for spec in configured:
                spec = spec.lstrip("+")
                if "*" in spec:
                    raise Unclear("remote.%s.push has a pattern (%s)" % (name, spec))
                src, sep, dst = spec.partition(":")
                if src:
                    out.append((src, dst if sep else None))
        elif (_ok(git, "config", "--get", "push.default") or "") == "matching":
            heads = (_ok(git, "for-each-ref", "--format=%(refname:short)", "refs/heads/") or "").splitlines()
            # the branches the remote has; for a URL every local branch (the guard cannot list the remote)
            out += [(h, h) for h in heads if h and (name is None or _remote_ref(git, name, h))]
        else:
            out.append(("HEAD", None))
    if p["tags"] or p["mirror"] or p["follow_tags"]:
        tags = (_ok(git, "for-each-ref", "--format=%(refname)", "refs/tags/") or "").splitlines()
        out += [(t, None) for t in tags if t]
    return out


def commits_of(git, name, src, dst):
    """`rev-list --parents` lines of what pushing `src` (to `dst`) on remote `name` sends. The base is a
    remote-tracking ref of that remote only; a URL or a remote without tracking refs has no base (whole history)."""
    if not _ok(git, "rev-parse", "-q", "--verify", src + "^{commit}"):
        raise Unclear("%s is not a commit the guard can resolve" % src)
    base = _remote_ref(git, name, dst) if dst else None
    if base is None and not dst and name:
        b = _branch_of(git, src)
        if b:
            up = _ok(git, "rev-parse", "-q", "--verify", "--symbolic-full-name", b + "@{upstream}")
            up_remote = _ok(git, "config", "--get", "branch.%s.remote" % b)
            if up and up_remote == name and up.startswith("refs/remotes/%s/" % name):
                base = up
            else:
                base = _remote_ref(git, name, b)
    if base is not None:
        excludes = ["^" + base]
    else:
        has = _ok(git, "for-each-ref", "--count=1", "--format=%(refname)", "refs/remotes/%s/" % name) if name else None
        excludes = ["--not", "--remotes=%s" % name] if has else []  # no tracking refs: the whole history
    n = _ok(git, "rev-list", "--count", src, *excludes)
    if n is None or not n.isdigit():
        raise Unclear("cannot count the commits %s sends" % src)
    if int(n) > MAX_COMMITS:
        raise TooMany(src, excludes, n)
    raw = _ok(git, "rev-list", "--reverse", "--parents", src, *excludes)
    return (raw or "").splitlines()


def leaks_in(git, cctx, src, excludes, internal_ids):
    """The first machine-only path (local/) or internal video/actor folder any of these commits adds or changes, or
    None — one `git log` call (the over-the-cap path)."""
    magic = ":(literal,icase)" if (git.config("core.ignorecase") or "").lower() == "true" else ":(literal)"
    specs = [magic + ".claude/studio/local"] + [magic + "%s/local" % r for r in cctx.roots]
    for r in cctx.roots:
        for i in sorted(internal_ids):
            specs += [magic + "%s/videos/%s" % (r, i), magic + "%s/cast/%s" % (r, i)]
    # -m: merge commits diffed against each parent (an evil merge's own files count; works on older git)
    out = git.text("log", "-m", "--format=", "--name-only", "--diff-filter=AMT", "-z", "--no-renames", src,
                   *(excludes + ["--"] + specs))
    names = [x for x in out.split("\0") if x.strip()]
    return names[0].strip() if names else None


def check(worktree, env, args, internal_ids, budget=3.0):
    """(deny text | None, [warnings])."""
    from ..commit import checks, gitx, kinds, rangecheck
    from . import gitprobe
    p = parse(args)
    if p["dry"] or p["delete"]:
        return None, []  # a dry run or deleting remote refs sends no commits
    warnings = []
    closed = ("— the guard cannot check this push (%s). Push with a plain `git push` from the branch with an upstream, "
              "or ask the person to push in a terminal.")
    if p["dynamic"]:
        return "git push " + closed % "an argument it cannot read", warnings
    try:
        git = gitprobe.budget_git(worktree, env, budget=budget, max_calls=2 * MAX_COMMITS + 60)
        cctx = checks.Ctx(git, env, kinds.registry({}))
        _repo, name = target_remote(git, p["repo"])
        lines, seen = [], set()
        for src, dst in pairs(git, p, name):
            try:
                found = commits_of(git, name, src, dst)
            except TooMany as e:
                leak = leaks_in(git, cctx, e.src, e.excludes, internal_ids)
                if leak:
                    return ("git push would publish machine-only or internal Studio files (%s) — remove them from "
                            "the history first, or ask the person to push from a terminal." % leak), warnings
                warnings.append("%s commits are pushed (a first publish?): only machine-only and internal files "
                                "were checked, not mixed commits" % e.n)
                continue
            for line in found:
                c = line.split()[0] if line.strip() else None
                if c and c not in seen:
                    seen.add(c)
                    lines.append(line)
        _code, problems, warns, commits = rangecheck.check_lines(cctx, lines)
        warnings += list(warns)
        leaks = [x.message for x in problems if x.code == 1]
        for c in commits:
            for path in c.get("studio_paths") or []:
                parts = path.split("/")
                for r in cctx.roots:
                    rp = r.split("/")
                    n = len(rp)
                    if parts[:n] == rp and len(parts) > n + 1 and parts[n] in ("videos", "cast") and \
                            parts[n + 1] in internal_ids:
                        leaks.append("commit %s adds %s of internal %s %s" % (
                            c["commit"][:12], path, "video" if parts[n] == "videos" else "actor", parts[n + 1]))
                        break
        if leaks:
            return ("git push would publish machine-only or internal Studio files: %s. Remove them from the history "
                    "first (ask the person)." % "; ".join(sorted(set(leaks))[:3])), warnings
        return None, warnings
    except Unclear as e:
        return "git push " + closed % e, warnings
    except gitx.GitError as e:
        return "git push " + closed % ("git: %s" % e), warnings
