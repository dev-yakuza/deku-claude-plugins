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

PROTECTED = (".claude/settings.json", ".claude/settings.local.json", ".claude/settings*.json",
             ".claude/guild/gates/**")
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


def remote_heads(worktree, remote="origin"):
    """{ref: sha} of the remote's branches (`git ls-remote --heads`) — the push tripwire that
    does not depend on remote-tracking refs (an explicit-URL or aliased push bypassing the deny
    rules still changes the remote). None when the remote cannot be read."""
    p = subprocess.run(["git", "ls-remote", "--heads", remote], cwd=worktree, stdout=subprocess.PIPE,
                       stderr=subprocess.DEVNULL, timeout=60)
    if p.returncode != 0:
        return None
    out = {}
    for ln in p.stdout.decode().splitlines():
        if "\t" in ln:
            sha, ref = ln.split("\t", 1)
            out[ref] = sha
    return out


def snapshot(worktree, remote=False):
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
        entries[p] = (st, _hash(os.path.join(worktree, p)))
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
    snap = {"status": entries, "head": head, "symref": sym, "refs": refs}
    if remote:
        snap["remote"] = remote_heads(worktree)
    return snap


def _local_object(worktree, sha):
    return subprocess.run(["git", "cat-file", "-e", sha + "^{commit}"], cwd=worktree,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


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
            local = set(ra[r] for r in ra if r.startswith("refs/heads/")) | {after["head"]}
            if ra.get(ref) in local:
                viol.append("%s moved to a local commit (push?)" % ref)
            continue
        if ref == branch_ref and movers and ref in rb and ref in ra:
            if subprocess.run(["git", "merge-base", "--is-ancestor", rb[ref], ra[ref]],
                              cwd=worktree).returncode != 0:
                viol.append("%s moved by a non-fast-forward change" % ref)
                continue
            committed = _git(worktree, "diff", "--name-only", "%s..%s" % (rb[ref], ra[ref])).decode().split()
            paths = sorted(set(paths) | set(committed))
            continue
        viol.append("ref %s %s" % (ref, "created" if ref not in rb else "deleted" if ref not in ra else "moved"))
    # remote push tripwire (Q22): a remote head that moved to a commit this clone has — i.e. a
    # push from here; a human's concurrent push to another branch is not in local objects
    rmb, rma = before.get("remote"), after.get("remote")
    if rmb is not None and rma is not None:
        for ref in sorted(set(rmb) | set(rma)):
            if rmb.get(ref) != rma.get(ref) and rma.get(ref) and _local_object(worktree, rma[ref]):
                viol.append("remote %s moved to a local commit during the role (push)" % ref)
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


def render_pause_line(role, violations):
    paths = ", ".join(v.split(" ", 2)[-1] for v in violations)[:300]
    return "%s wrote outside its scope — %s" % (role, paths)
