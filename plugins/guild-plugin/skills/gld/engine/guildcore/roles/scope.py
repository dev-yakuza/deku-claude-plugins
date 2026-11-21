"""guildcore.roles.scope — the after-role scope check (§5.1 "역할 뒤 범위 검사", R5F-M1(b), R6C-M1, R7C-M1).

Bash rules cannot bound a command's PATH arguments, so a non-developer role's write scope is
enforced after it ends, like the auditor tripwire: snapshot before, snapshot after, compare.

Snapshot = `git status --porcelain -uall -z` (+ a content hash of every listed path, so a second
edit to an already-dirty file is seen) + HEAD + `git for-each-ref refs/heads refs/tags` (commits
and new branches do not show in porcelain). Parallel groups (design: tech-lead · tester-cases ·
specialists; 3.5b specialists incl. tech-writer) share one worktree: one snapshot at group start
and end, the check runs against the UNION of the overlapping roles' scopes, and a path outside
every scope names all of them (`one of <roles>`); a path only one role may write is that role's.

HEAD rule: developer and qa may advance `refs/heads/<branch>` by fast-forward commits only, the
commits' paths must be inside their scope and HEAD must be `<branch>` after the P0.R2 cleanup
(ordering: cleanup FIRST, then this check — R7C-M1); every other role leaves HEAD and refs
untouched. Every role: touching `.claude/settings*.json` or `.claude/guild/gates/**` is a
violation (R6C-m5). A violation discards the result (never reverts) → pause
`defect: <role> wrote outside its scope — <paths>`.
"""

import fnmatch
import hashlib
import os
import subprocess

from guildcore.adapters import git as G

# lefthook's config search (v1/v2): root `lefthook.*` / `.lefthook.*`, then `.config/lefthook.*` — ONE list
# for the role's commit hook (settings.base_lefthook_env) and the engine's 1L checks (K4r2-m9)
LEFTHOOK_EXTS = ("yml", "yaml", "json", "toml")
LEFTHOOK_NAMES = tuple("%s%s.%s" % (d, n, e) for d in ("", ".config/") for n in ("lefthook", ".lefthook")
                       for e in LEFTHOOK_EXTS if not (d and n.startswith(".")))
# the per-checkout overlay lefthook MERGES on top of any config (LEFTHOOK_CONFIG included — measured,
# 2.2.2): no role may create or change one (K4r2-m1 — a role-planted `run:` would later run outside the
# sandbox with a person's credentials when someone commits in that worktree)
LEFTHOOK_LOCAL_NAMES = tuple("%s%s.%s" % (d, n, e) for d in ("", ".config/") for n in ("lefthook-local", ".lefthook-local")
                             for e in LEFTHOOK_EXTS if not (d and n.startswith(".")))
PROTECTED = (".claude/settings.json", ".claude/settings.local.json", ".claude/settings*.json",
             ".claude/guild/gates/**") + LEFTHOOK_LOCAL_NAMES


def lefthook_local_files(worktree):
    """The lefthook-local overlay paths of `worktree` (absolute; existing or not) — watched by the
    integrity snapshot and denyWrite in every role sandbox."""
    return [os.path.join(os.path.abspath(worktree), n) for n in LEFTHOOK_LOCAL_NAMES] if worktree else []
TEST_DIRS = ("test/**", "tests/**", "integration_test/**", "e2e/**", "__tests__/**",
             "spec/**")


def scope_globs(role_key, issue=None):
    """Worktree globs a role may write (developer: everything)."""
    if role_key == "developer":
        return ("**",)
    if role_key == "qa":
        return TEST_DIRS
    if role_key == "tester-cases":
        return ("docs/specs/%s/test-cases.md" % issue,)
    if role_key == "tech-writer":
        return ("docs/**",)
    return ()


EXCLUDE = {"tech-writer": ("docs/standards/**",)}       # confirmed standards stay human-owned


def _git(cwd, *args):
    p = subprocess.run(["git"] + list(args), cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        raise RuntimeError("git %s failed: %s" % (" ".join(args), p.stderr.decode("utf-8", "replace").strip()))
    return p.stdout


def _hash(path):
    try:
        with open(path, "rb") as fh:
            return hashlib.sha1(fh.read()).hexdigest()
    except (IOError, OSError):
        return None


def remote_url(worktree, remote="origin"):
    """The push URL of `remote`, resolved BEFORE a role runs and reused for the after-snapshot
    (K1-B3: a role that rewrites `remote.origin.url` must not redirect the tripwire)."""
    p = subprocess.run(["git", "remote", "get-url", "--push", remote], cwd=worktree,
                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return p.stdout.decode().strip() or None if p.returncode == 0 else None


def remote_heads(worktree, url):
    """{ref: sha} of every branch and tag at `url` (`git ls-remote --refs`), or None when it
    cannot be read — which the check treats as a violation (fail closed, K1-B3)."""
    if not url:
        return None
    try:
        raw = G.run(worktree, "ls-remote", "--refs", url, timeout=60)
    except (subprocess.TimeoutExpired, G.GitError):
        return None
    out = {}
    for ln in raw.decode().splitlines():
        if "\t" in ln:
            sha, ref = ln.split("\t", 1)
            out[ref] = sha
    return out


def _git_paths(worktree):
    out = {}
    for k, arg in (("gitdir", "--git-dir"), ("common", "--git-common-dir")):
        p = subprocess.run(["git", "rev-parse", "--path-format=absolute", arg], cwd=worktree,
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        out[k] = p.stdout.decode().strip()
    return out


def _tree_hash(root):
    h = hashlib.sha1()
    if not root or not os.path.isdir(root):
        return None
    for base, dirs, files in sorted(os.walk(root)):
        dirs.sort()
        for f in sorted(files):
            fp = os.path.join(base, f)
            h.update(os.path.relpath(fp, root).encode())
            h.update((_hash(fp) or "").encode())
            try:
                h.update(oct(os.stat(fp).st_mode).encode())
            except OSError:
                pass
    return h.hexdigest()


def integrity(worktree, watch_files=()):
    """Hashes of what no role may change and porcelain cannot see (K1-B2): local/worktree git
    config, the hooks and info dirs of the git dir and common dir, and `watch_files` (the main
    checkout's `.claude/settings.local.json`, the user settings)."""
    gp = _git_paths(worktree)
    out = {}
    for scope in ("--local", "--worktree"):
        p = subprocess.run(["git", "config", "--list", scope], cwd=worktree, stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL)
        out["git config " + scope] = hashlib.sha1(p.stdout).hexdigest() if p.returncode == 0 else None
    for k in sorted(set(gp.values())):
        out["hooks " + k] = _tree_hash(os.path.join(k, "hooks"))
        out["info " + k] = _tree_hash(os.path.join(k, "info"))
        out["config file " + k] = _hash(os.path.join(k, "config"))
    for f in watch_files or ():
        out["file " + f] = _hash(f)
    for f in lefthook_local_files(worktree):           # K4r2-m1: gitignored → porcelain never shows it
        out["file " + f] = _hash(f)
    return out


def snapshot(worktree, remote=None, watch_files=()):
    """`remote` = the push URL fixed before the role (see remote_url) or None (no remote check)."""
    raw = _git(worktree, "status", "--porcelain", "-uall", "-z").decode("utf-8", "replace")
    entries = {}
    parts = raw.split("\0")
    i = 0
    while i < len(parts):
        e = parts[i]
        i += 1
        if len(e) < 4:
            continue
        st, p = e[:2], e[3:]
        if st[0] in "RC":          # rename/copy: the next field is the source
            i += 1
        entries[p] = [st, _hash(os.path.join(worktree, p))]
    head = _git(worktree, "rev-parse", "HEAD").decode().strip()
    try:
        sym = _git(worktree, "symbolic-ref", "-q", "HEAD").decode().strip()
    except RuntimeError:
        sym = None
    refs = {}
    for ln in _git(worktree, "for-each-ref", "--format=%(refname) %(objectname)",
                   "refs/heads", "refs/tags", "refs/remotes").decode().splitlines():
        if " " in ln:
            r, sha = ln.split(" ", 1)
            refs[r] = sha
    snap = {"status": entries, "head": head, "symref": sym, "refs": refs,
            "integrity": integrity(worktree, watch_files)}
    if remote:
        snap["remote_url"] = remote
        snap["remote"] = remote_heads(worktree, remote)
    return snap


def group_snapshot(worktree, watch_files=(), remote="origin"):
    """Snapshot for a parallel group — the remote tripwire is ON by default (K1-m8)."""
    url = remote_url(worktree, remote) if remote else None
    return snapshot(worktree, remote=url or "unresolved:%s" % remote, watch_files=watch_files)


def _reachable_from_local(worktree, sha, after):
    """Is `sha` reachable from a local branch or HEAD? (a fetched human commit only sits under
    refs/remotes — K1-M6)"""
    if subprocess.run(["git", "cat-file", "-e", sha + "^{commit}"], cwd=worktree,
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0:
        return False
    tips = set(v for r, v in after["refs"].items() if r.startswith("refs/heads/")) | {after["head"]}
    for t in tips:
        if subprocess.run(["git", "merge-base", "--is-ancestor", sha, t], cwd=worktree,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
            return True
    return False


def _human_ref_move(worktree, ref, rb, ra, head):
    """0.102.3: another local ref (main, a sibling branch, a tag) that moved or vanished away from this
    worktree's work is a person's ordinary activity on the shared repo (a merge, `/gld update`, a deleted merged
    branch) — not this issue's role. A move counts only when its new tip is this worktree's own history
    (reachable from HEAD): that is what a role here could have made."""
    if ref.startswith("refs/remotes/"):
        return False
    new = ra.get(ref)
    if not new:
        return True
    return subprocess.run(["git", "merge-base", "--is-ancestor", new, head], cwd=worktree,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0


def _match(path, globs):
    for g in globs:
        if g == "**" or fnmatch.fnmatchcase(path, g):
            return True
        if g.endswith("/**") and (path == g[:-3] or path.startswith(g[:-2])):
            return True
    return False


def protected(path):
    return _match(path, PROTECTED)


def changed_paths(before, after):
    out = set()
    for p in set(before["status"]) | set(after["status"]):
        if before["status"].get(p) != after["status"].get(p):
            out.add(p)
    return sorted(out)


def check(worktree, before, after, roles, issue=None, branch=None, extra_globs=None):
    """Violations ([str]) for a role or a parallel group `roles` = [role_key, …]."""
    viol = []
    paths = changed_paths(before, after)
    movers = [r for r in roles if r in ("developer", "qa")]
    # refs / HEAD
    rb, ra = before["refs"], after["refs"]
    branch_ref = "refs/heads/%s" % branch if branch else None
    for ref in sorted(set(rb) | set(ra)):
        if rb.get(ref) == ra.get(ref):
            continue
        if ref.startswith("refs/remotes/"):
            # a remote-tracking ref only moves on fetch or PUSH; fetch is allowed, so only a
            # move to a commit that exists solely because of this session (= was a local
            # head/HEAD after the role) is reported — a push that got past the deny rules (Q22)
            if ra.get(ref) and _reachable_from_local(worktree, ra[ref], after) and ref in rb:
                viol.append("%s moved to a local commit (push?)" % ref)
            elif ra.get(ref) and ref not in rb and _reachable_from_local(worktree, ra[ref], after):
                viol.append("%s moved to a local commit (push?)" % ref)
            continue
        if ref == branch_ref and movers and ref in rb and ref in ra:
            if subprocess.run(["git", "merge-base", "--is-ancestor", rb[ref], ra[ref]],
                              cwd=worktree).returncode != 0:
                viol.append("%s moved by a non-fast-forward change" % ref)
                continue
            committed = [x for x in _git(worktree, "diff", "--name-only", "-z", "%s..%s" % (rb[ref], ra[ref]))
                         .decode("utf-8", "replace").split("\0") if x]
            paths = sorted(set(paths) | set(committed))
            continue
        if ref != branch_ref and _human_ref_move(worktree, ref, rb, ra, after["head"]):
            continue
        viol.append("ref %s %s" % (ref, "created" if ref not in rb else "deleted" if ref not in ra else "moved"))
    # remote push tripwire (Q22): a remote head that moved to a commit this clone has — i.e. a
    # push from here; a human's concurrent push to another branch is not in local objects
    if "remote_url" in before or "remote_url" in after:
        rmb, rma = before.get("remote"), after.get("remote")
        if rmb is None or rma is None:
            viol.append("remote unverifiable (%s) — cannot rule out a push" % (before.get("remote_url") or after.get("remote_url")))
        else:
            for ref in sorted(set(rmb) | set(rma)):
                if rmb.get(ref) == rma.get(ref):
                    continue
                if ref not in rma:
                    viol.append("remote %s deleted during the role" % ref)
                elif _reachable_from_local(worktree, rma[ref], after):
                    viol.append("remote %s moved to a local commit during the role (push)" % ref)
    ib, ia = before.get("integrity") or {}, after.get("integrity") or {}
    for k in sorted(set(ib) | set(ia)):
        # watched settings FILES are a human's to edit while a role runs ("always allow" in
        # Claude Code writes settings.local.json) — a role cannot (denyWrite); not a violation
        # (K1r3-M2), see watch_warnings
        if ib.get(k) != ia.get(k) and not k.startswith("file "):
            viol.append("%s changed during the role" % k)
    if movers:
        if branch_ref and after.get("symref") != branch_ref:
            viol.append("HEAD is %s after the role, not %s" % (after.get("symref") or after["head"][:12], branch_ref))
    elif after["head"] != before["head"] or after.get("symref") != before.get("symref"):
        viol.append("HEAD moved (%s → %s)" % (before["head"][:12], after["head"][:12]))
    # paths
    owners = {}
    for r in roles:
        g = tuple(scope_globs(r, issue)) + tuple((extra_globs or {}).get(r, ()))
        owners[r] = (g, EXCLUDE.get(r, ()))
    bad = []
    for p in paths:
        if protected(p):
            bad.append((p, "protected"))
            continue
        ok = [r for r, (g, ex) in owners.items() if _match(p, g) and not _match(p, ex)]
        if not ok:
            bad.append((p, roles[0] if len(roles) == 1 else "one of %s" % ",".join(roles)))
    for p, who in bad:
        viol.append("%s wrote %s" % (who, p) if who != "protected" else "protected path %s changed" % p)
    return viol


def drift(baseline, now, worktree=None):
    """Changes between the end of the previous role (its after-snapshot, or the engine's own
    re-baseline) and now — what an escaped orphan wrote late (K1r2-B3). Remote-tracking refs
    are ignored (the engine fetches); everything else is compared."""
    out = []
    for p in changed_paths(baseline, now):
        out.append("path %s" % p)
    rb = {k: v for k, v in baseline["refs"].items() if not k.startswith("refs/remotes/")}
    ra = {k: v for k, v in now["refs"].items() if not k.startswith("refs/remotes/")}
    own = baseline.get("symref") or now.get("symref")
    for ref in sorted(set(rb) | set(ra)):
        if rb.get(ref) != ra.get(ref):
            if worktree and ref != own and _human_ref_move(worktree, ref, rb, ra, now["head"]):
                continue
            out.append("ref %s" % ref)
    if baseline["head"] != now["head"] or baseline.get("symref") != now.get("symref"):
        out.append("HEAD")
    ib, ia = baseline.get("integrity") or {}, now.get("integrity") or {}
    for k in sorted(set(ib) | set(ia)):
        if ib.get(k) != ia.get(k) and not k.startswith("file "):
            out.append(k)
    return out


def watch_warnings(before, after):
    ib, ia = before.get("integrity") or {}, after.get("integrity") or {}
    return ["%s changed (a human's edit — not the role's: denyWrite)" % k
            for k in sorted(set(ib) | set(ia)) if k.startswith("file ") and ib.get(k) != ia.get(k)]


def remote_warnings(before, after):
    """K1r2-m1: any remote ref that moved during the role without being attributable to this
    clone (e.g. objects garbage-collected after a push) — logged, not a violation."""
    rmb, rma = before.get("remote"), after.get("remote")
    if rmb is None or rma is None:
        return []
    return ["remote %s moved during the role" % r for r in sorted(set(rmb) | set(rma))
            if rmb.get(r) != rma.get(r)]


def render_pause_line(role, violations):
    paths = ", ".join(v.split(" ", 2)[-1] for v in violations)[:300]
    return "%s wrote outside its scope — %s" % (role, paths)
