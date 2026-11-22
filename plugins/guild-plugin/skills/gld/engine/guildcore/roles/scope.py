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
violation (R6C-m5). A violation discards the result → pause `defect: <role> wrote outside its scope — <paths>` —
except (0.102.11) a read-only role's uncommitted writes to paths clean before it, in an engine worktree: the engine
puts them back and hands them to the stage (`revertable` / `revert_writes`, `RoleResult.reverted`).
"""

import fnmatch
import json
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
            src = parts[i] if i < len(parts) else ""
            i += 1
            if st[0] == "R" and src:
                # 0.102.12 (review-0102-11 M3): a rename's SOURCE is a deletion of that path — kept beside the
                # destination (each names the other), so a move out of an allowed path is seen and reverted as a pair
                entries[src] = ["D ", None, "renamed-to:" + p]
                entries[p] = [st, _hash(os.path.join(worktree, p)), "renamed-from:" + src]
                continue
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


def _from_this_clone(worktree, sha, before, after):
    """0.102.5: a remote ref that moved to `sha` was moved FROM HERE (a push past the deny rules) only when `sha` is this
    clone's own work — reachable from a local branch / HEAD after the role AND on no remote-tracking ref before it. A
    commit some remote already had (a fetched base, another person's merge brought in) is not this clone's push."""
    if not _reachable_from_local(worktree, sha, after):
        return False
    for r, v in (before.get("refs") or {}).items():
        if r.startswith("refs/remotes/") and subprocess.run(
                ["git", "merge-base", "--is-ancestor", sha, v], cwd=worktree,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
            return False
    return True


def _deleted_elsewhere(ref, old, remote_after, branch_ref):
    """0.102.6 (review-0102-5 M3): a remote ref that vanished during a role is a deletion ELSEWHERE only when a host
    did it by itself: GitHub's `refs/pull/<n>/merge` (and other `refs/pull/*`), or a branch whose last commit is still
    the head of a pull request on the remote (`refs/pull/<n>/head` == its old sha — a merged PR's branch deleted by
    GitHub, #1945). Never this Issue's own branch (the engine pushes it), the base or a tag; any other branch deleted
    while a role ran is a violation, as in 0.102.4."""
    if branch_ref and ref == branch_ref:
        return False
    if ref.startswith("refs/pull/"):
        return True
    if not ref.startswith("refs/heads/"):
        return False
    return any(r.startswith("refs/pull/") and r.endswith("/head") and v == old for r, v in (remote_after or {}).items())


def _rewound_from_here(worktree, old, new, after):
    """A remote ref moved backwards / sideways (the new sha is not a descendant of the old) to a commit this clone's
    local branches or HEAD reach — what `git push -f` from here leaves."""
    if not _reachable_from_local(worktree, new, after):
        return False
    if subprocess.run(["git", "cat-file", "-e", old + "^{commit}"], cwd=worktree, stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL).returncode != 0:
        return False                                 # the old tip is unknown here: no rewind this clone can show
    return subprocess.run(["git", "merge-base", "--is-ancestor", old, new], cwd=worktree,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0


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
            # move to a commit that exists solely because of this session (= this clone's own
            # work, on no remote before the role) is reported — a push that got past the deny
            # rules (Q22). 0.102.5: a deletion (`fetch --prune` of a merged branch) is never one
            if ra.get(ref) and _from_this_clone(worktree, ra[ref], before, after):
                viol.append("%s moved to a local commit (push?)" % ref)
            continue
        if ref == branch_ref and movers and ref in rb and ref in ra:
            if subprocess.run(["git", "merge-base", "--is-ancestor", rb[ref], ra[ref]],
                              cwd=worktree).returncode != 0:
                viol.append("%s moved by a non-fast-forward change" % ref)
                continue
            # 0.102.12 (M3): `--no-renames` — a moved source counts as deleted (rename detection showed the new path only)
            committed = [x for x in _git(worktree, "diff", "--name-only", "--no-renames", "-z", "%s..%s" % (rb[ref], ra[ref]))
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
                    if not _deleted_elsewhere(ref, rmb[ref], rma, branch_ref):
                        viol.append("remote %s deleted during the role" % ref)
                elif ref in rmb and not ref.startswith("refs/pull/") and \
                        _rewound_from_here(worktree, rmb[ref], rma[ref], after):
                    # 0.102.6 (review-0102-5 M3): a NON-fast-forward move to a commit this clone holds — a force-push
                    # from here (`push -f origin <old>:main`) — whatever the commit's origin (0.102.4 caught it)
                    viol.append("remote %s rewound to a local commit during the role (force-push)" % ref)
                elif _from_this_clone(worktree, rma[ref], before, after):
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


# ---- 0.102.11 (review-0102-10 M4, lead decision 5): a read-only role's own file writes are reverted, never a stop ---
# word_app #1797 (0.102.10 run, `209-qa-qa-run`): the repo's QA persona wrote `release_notes/{ko,ja,en}.txt` — every
# user-visible Issue stopped for a person (`qa wrote outside its scope`). A role other than the developer never writes
# repository files outside its scope: when EVERY violation is such a write — a path that was clean before the role,
# not committed, not protected — the engine puts each path back (tracked: its HEAD content; new: removed) and hands
# what the role wrote to the stage (QA: a fixable finding for the developer). Anything else stays a stop.
def revertable(worktree, before, after, violations, role):
    """[path] when every violation is `<role> wrote <path>` for an uncommitted write to a path that was clean before
    the role (never the developer's, never a protected path); else None."""
    import re as _re
    if role == "developer" or not violations:
        return None
    committed = set()
    if before.get("head") != after.get("head"):
        try:
            committed = set(x for x in _git(worktree, "diff", "--name-only", "--no-renames", "-z", "%s..%s" % (
                before["head"], after["head"])).decode("utf-8", "replace").split("\0") if x)
        except RuntimeError:
            return None
    out = []
    for v in violations:
        m = _re.match(r"^%s wrote (.+)$" % _re.escape(role), v)
        if not m:
            return None
        p = m.group(1)
        if protected(p) or p in committed or p in (before.get("status") or {}) or p not in (after.get("status") or {}):
            return None
        out.append(p)
    # 0.102.12 (M3 / m6): a rename is reverted as a PAIR — the other side joins even when it is inside the scope
    for p in list(out):
        q = rename_partner(after, p)
        if q and q not in out:
            if protected(q) or q in committed or q in (before.get("status") or {}):
                return None
            out.append(q)
    return out


def rename_partner(snap, path):
    """The other side of a staged rename `path` is part of in the snapshot `snap`, or None."""
    e = (snap.get("status") or {}).get(path) or []
    tag = e[2] if len(e) > 2 and isinstance(e[2], str) else ""
    return tag.split(":", 1)[1] if ":" in tag else None


def revert_writes(worktree, paths, cap=1200, keep_dir=None, after=None):
    """Put each path back to HEAD (a new file is removed) → [(path, what the role wrote — its added lines, capped)].

    0.102.12 (review-0102-11 M2, lead decision M2): NOTHING is lost — before any path is touched, its content is copied
    to `keep_dir` (the role's `out/reverted/`: the file at its own relative path, `<path>.diff` against HEAD for a
    tracked one) and `manifest.json` lists each path's state (modified / new / deleted / renamed from|to) and copy.
    No stash, no `git clean` of anything not copied first: a path whose copy cannot be written is not reverted (the
    caller's re-check then stops for a person, as before 0.102.11). A binary file's text is `(binary)`."""
    import shutil
    rows, keep = [], {}
    for p in paths:
        full = os.path.join(worktree, p)
        tracked = subprocess.run(["git", "cat-file", "-e", "HEAD:%s" % p], cwd=worktree,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
        exists = os.path.lexists(full)
        partner = rename_partner(after, p) if after else None
        ent = ((after or {}).get("status") or {}).get(p) or []
        state = ("renamed-to %s" % partner if ent[:1] and str(ent[0]).startswith("D") else "renamed-from %s" % partner) \
            if partner else ("deleted" if not exists else ("modified" if tracked else "new"))
        row = {"path": p, "state": state, "tracked": tracked, "copy": None, "diff": None}
        if keep_dir:
            try:
                if exists and os.path.isfile(full):
                    dst = os.path.join(keep_dir, p)
                    os.makedirs(os.path.dirname(dst), exist_ok=True)  # fs-ok: engine-owned run dir out/reverted (copy before revert)
                    shutil.copy2(full, dst)  # fs-ok: engine-owned run dir out/reverted (copy before revert)
                    row["copy"] = dst
                if tracked:
                    d = _git(worktree, "diff", "--binary", "HEAD", "--", p)
                    if d:
                        dst = os.path.join(keep_dir, p + ".diff")
                        os.makedirs(os.path.dirname(dst), exist_ok=True)  # fs-ok: engine-owned run dir out/reverted
                        with open(dst, "wb") as fh:  # fs-ok: engine-owned run dir out/reverted (copy before revert)
                            fh.write(d)
                        row["diff"] = dst
            except (OSError, RuntimeError, IOError) as e:
                row["error"] = str(e)
        rows.append(row)
        keep[p] = row
    if keep_dir:
        try:
            os.makedirs(keep_dir, exist_ok=True)  # fs-ok: engine-owned run dir out/reverted
            with open(os.path.join(keep_dir, "manifest.json"), "w", encoding="utf-8") as fh:  # fs-ok: engine-owned run dir out/reverted
                json.dump(rows, fh, ensure_ascii=False, indent=1, sort_keys=True)
        except (OSError, IOError):
            return []                                     # no record of what is kept → nothing is reverted
    out = []
    for p in paths:
        row = keep[p]
        if keep_dir and row.get("error"):
            continue                                      # never revert what could not be copied
        full = os.path.join(worktree, p)
        text = ""
        try:
            if _binary(full):
                text = "(binary)"
            elif row["tracked"] and os.path.isfile(full):
                diff = _git(worktree, "diff", "HEAD", "--", p).decode("utf-8", "replace")
                text = "\n".join(l[1:] for l in diff.split("\n") if l.startswith("+") and not l.startswith("+++"))
            elif os.path.isfile(full):
                with open(full, encoding="utf-8", errors="replace") as fh:
                    text = fh.read(cap * 2)
        except (RuntimeError, OSError):
            text = ""
        if row["tracked"]:
            G.run(worktree, "reset", "-q", "HEAD", "--", p, check=False)     # a staged rename / deletion side
            G.run(worktree, "checkout", "HEAD", "--", p)              # the git adapter: the one mutating door
        else:
            # `reset` unstages a staged add / a rename's destination whatever its content (`rm --cached` refuses a
            # path whose staged content differs from both the file and HEAD — an edited rename destination)
            G.run(worktree, "reset", "-q", "HEAD", "--", p, check=False)
            G.run(worktree, "rm", "-q", "--cached", "--ignore-unmatch", "--", p, check=False)
            if os.path.lexists(full) and (row.get("copy") or not keep_dir):
                os.remove(full)  # fs-ok: an engine worktree path the role wrote outside its scope, copied to out/reverted first
        out.append((p, " ".join(text.split())[:cap]))
    return out


def _binary(path):
    try:
        with open(path, "rb") as fh:
            return b"\0" in fh.read(8192)
    except (OSError, IOError):
        return False


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


def drift_print(baseline, now, items):
    """0.102.6 (review-0102-5 M2): the fingerprint of a drift AS IT IS — every late item with its value now (a path's
    status and content hash, a ref's sha, HEAD, an integrity reading). A person's `accept` applies only while the
    worktree still has this fingerprint: a change after the question (the same path written again included) is not
    accepted unseen."""
    import hashlib
    rows = []
    for it in sorted(items or ()):
        if it.startswith("path "):
            v = (now.get("status") or {}).get(it[5:])
        elif it.startswith("ref "):
            v = (now.get("refs") or {}).get(it[4:])
        elif it == "HEAD":
            v = [now.get("head"), now.get("symref")]
        else:
            v = (now.get("integrity") or {}).get(it)
        rows.append("%s=%s" % (it, json.dumps(v, sort_keys=True)))
    return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()[:16]


def _ok(worktree, *args):
    return subprocess.run(["git"] + list(args), cwd=worktree, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0


def _out(worktree, *args):
    p = subprocess.run(["git"] + list(args), cwd=worktree, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return p.stdout.decode("utf-8", "replace").strip() if p.returncode == 0 else None


def _remotes(worktree):
    return [x for x in (_out(worktree, "remote") or "").split("\n") if x]


def base_name(worktree, base):
    """(remote, branch name) of the base: `origin/main` → ("origin", "main"), `main` → ("origin", "main"),
    `refs/remotes/up/main` → ("up", "main")."""
    if not base:
        return None, None
    b = base[len("refs/remotes/"):] if base.startswith("refs/remotes/") else base
    b = b[len("refs/heads/"):] if b.startswith("refs/heads/") else b
    rem = _remotes(worktree)
    head, _s, rest = b.partition("/")
    if rest and head in rem:
        return head, rest
    return ("origin" if "origin" in rem else (rem[0] if rem else None)), b


def recorded_base_tips(worktree, snap, base):
    """0.102.6 (review-0102-5 M1): the base commits recorded when the Issue's first drift baseline is made — before
    any role of the Issue ran: the remote-tracking copy of the base, else the base ref itself. Kept on every later
    baseline (`Runner._set_baseline`), never re-read from a snapshot a role could have changed."""
    remote, name = base_name(worktree, base)
    if not name:
        return []
    refs = (snap or {}).get("refs") or {}
    out = [refs.get("refs/remotes/%s/%s" % (remote, name))] if remote else []
    if not any(out):
        out = [refs.get("refs/heads/%s" % name)]
    return [x for x in out if x]


def remote_base_tip(worktree, base, url=None):
    """0.102.6 M1: the base tip the REMOTE has now, read by the engine itself (`ls-remote`) — a sha this clone holds,
    or None (no remote, unreadable, not fetched)."""
    remote, name = base_name(worktree, base)
    url = url or (remote_url(worktree, remote) if remote else None)
    if not url or not name or url.startswith("unresolved:"):
        return None
    try:
        raw = G.run(worktree, "ls-remote", url, "refs/heads/%s" % name, timeout=60).decode()
    except (subprocess.TimeoutExpired, G.GitError, OSError):
        return None
    sha = raw.split()[0] if raw.split() else None
    return sha if sha and _ok(worktree, "cat-file", "-e", sha + "^{commit}") else None


def trusted_base_tips(worktree, baseline, base):
    """The base commits a base merge may bring in: the tips recorded at the Issue's first baseline and the remote's
    tip read now — never a local base branch or remote-tracking ref as it is now (a role can move either)."""
    tips = list((baseline or {}).get("base_tips") or [])
    rt = remote_base_tip(worktree, base, (baseline or {}).get("remote_url"))
    if rt:
        tips.append(rt)
    return [t for t in dict.fromkeys(tips) if t and _ok(worktree, "cat-file", "-e", t + "^{commit}")]


def _blob(worktree, rev, path):
    return _out(worktree, "rev-parse", "-q", "--verify", "%s:%s" % (rev, path))


def _clean_merge_tree(worktree, a, b):
    """The tree git's own merge of `a` and `b` makes, or None (a conflict, or a git without `merge-tree --write-tree`)."""
    p = subprocess.run(["git", "merge-tree", "--write-tree", "--no-messages", a, b], cwd=worktree,
                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if p.returncode != 0:
        return None
    first = p.stdout.decode("utf-8", "replace").split("\n", 1)[0].strip()
    return first or None


def base_merges(worktree, old, new, refs):
    """0.102.5: the commits `old..new` when they are ONLY merges of the base branch into this branch — every commit on
    the first-parent line is a two-parent merge whose first parent is the previous tip (the chain starts at `old`),
    whose second parent the base already holds (`refs` — 0.102.6: the TRUSTED base tips only, `trusted_base_tips`);
    every other commit of the range is the base's. 0.102.6 (review-0102-5 M1 b): each merge's tree is exactly git's own
    conflict-free merge of its parents (`merge-tree --write-tree`) — no hand edit, no deletion and no revert of the
    branch's work rides in a merge — and every path the branch changed (against the merge base) still differs from
    the merge base after it. Returns [merge sha, …] (oldest first) or None."""
    if not old or not new or old == new or not refs or not _ok(worktree, "merge-base", "--is-ancestor", old, new):
        return None
    line = (_out(worktree, "rev-list", "--first-parent", "%s..%s" % (old, new)) or "").split()
    if not line:
        return None
    rest = (_out(worktree, "rev-list", "%s..%s" % (old, new), "--not", *refs) or "").split()
    if set(rest) - set(line):
        return None                                  # a commit that is neither a merge on the line nor the base's
    prev = old
    for c in reversed(line):
        parents = (_out(worktree, "rev-list", "--parents", "-n", "1", c) or "").split()[1:]
        if len(parents) != 2 or parents[0] != prev:
            return None
        other = parents[1]
        if not any(_ok(worktree, "merge-base", "--is-ancestor", other, r) for r in refs):
            return None
        want = _clean_merge_tree(worktree, parents[0], other)
        if not want or want != _out(worktree, "rev-parse", "%s^{tree}" % c):
            return None                              # a conflict resolved by hand, or an edit inside the merge
        mb = _out(worktree, "merge-base", parents[0], other)
        if not mb:
            return None
        own = [x for x in (_out(worktree, "diff", "--name-only", "--no-renames", mb, parents[0]) or "").split("\n") if x]
        for f in own:
            if _blob(worktree, c, f) == _blob(worktree, mb, f):
                return None                          # the branch's own change is gone after the merge
        prev = c
    return list(reversed(line))


def accept_base_merge(worktree, baseline, now, branch, base):
    """The drift since `baseline` when it is nothing but base merges on this Issue's own branch (a person ran
    `git merge origin/main` in the worktree) → [merge sha, …] to accept (the caller rebaselines and notes it); any
    other drift → None (a person decides). 0.102.6 M1: the base is what the engine vouches for (`trusted_base_tips`);
    the local base branch may have moved only to a commit the trusted base holds."""
    if not branch or baseline is None or now is None:
        return None
    own = "refs/heads/%s" % branch
    late = drift(baseline, now, worktree)
    _remote, name = base_name(worktree, base)
    local_base = "refs/heads/%s" % name if name else None
    if not late or set(late) - {"ref %s" % own, "HEAD", "ref %s" % local_base}:
        return None
    if now.get("symref") != own or baseline.get("symref") not in (own, None):
        return None
    old = (baseline.get("refs") or {}).get(own) or baseline.get("head")
    new = (now.get("refs") or {}).get(own)
    if not new or now.get("head") != new:
        return None
    tips = trusted_base_tips(worktree, baseline, base)
    if not tips:
        return None
    if "ref %s" % local_base in late:
        moved = (now.get("refs") or {}).get(local_base)
        if moved and not any(_ok(worktree, "merge-base", "--is-ancestor", moved, t) for t in tips):
            return None                              # the local base holds a commit the trusted base does not
    return base_merges(worktree, old, new, tips)


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
