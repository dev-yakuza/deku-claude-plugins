"""Base-branch commit discipline (plan §3.2.1, §3.2.2 step 1, §3.4).

- Every Herald base commit stages only its command's allowed paths and carries the trailer
  `Herald-Record: <kind>`.
- Commits ahead of origin pass step 1 without asking only if they carry the trailer AND
  (normal commit) touch only record paths, or (merge) satisfy the sync-merge definition.
- PR branches may only change the article's own files (PR file scope).
"""

import fnmatch

from .util import HeraldError, git, git_ok, run

TRAILER = "Herald-Record"

RECORD_GLOBS = [
    ".claude/herald/topics.json",
    ".claude/herald/published.json",
    ".claude/herald/work/*/research.md",
    ".claude/herald/work/*/claims-map.json",
    ".claude/herald/work/*/verify.md",
    ".claude/herald/work/*/verify.json",
    ".claude/herald/work/*/state.json",
]

HARNESS_GLOBS = [
    "docs/editorial/*", "docs/editorial/**",
    ".claude/agents/*",
    ".claude/herald/config.json",
    ".claude/herald/evolution-log.md",
    ".claude/herald/topics.json",
    ".claude/herald/published.json",
    ".claude/herald/scripts/*", ".claude/herald/scripts/**",
    ".claude/settings.json",
    ".gitignore",
]

COMMAND_GLOBS = {
    "plan": [".claude/herald/topics.json"],
    "refresh": [".claude/herald/topics.json"],
    "status": [".claude/herald/topics.json", ".claude/herald/published.json"],
    "hold": [".claude/herald/topics.json"],
    "ship": RECORD_GLOBS,
    "runner": [".claude/herald/topics.json", ".claude/herald/published.json"],
    "harness": HARNESS_GLOBS,
}


def _match(path, globs):
    for g in globs:
        if fnmatch.fnmatchcase(path, g):
            return True
        if g.endswith("/**") and path.startswith(g[:-3] + "/"):
            return True
    return False


def allowed_globs(cfg, command):
    if command not in COMMAND_GLOBS:
        raise HeraldError("unknown commit command %s" % command)
    globs = list(COMMAND_GLOBS[command])
    if command in ("ship", "runner"):
        globs += cfg.deploy_artifacts()
    return globs


def record_globs(cfg):
    return RECORD_GLOBS + cfg.deploy_artifacts()


def all_base_globs(cfg):
    out = []
    for c in COMMAND_GLOBS:
        out += allowed_globs(cfg, c)
    return sorted(set(out))


def staged_paths(root):
    return [p for p in git(root, "diff", "--cached", "--name-only", "-z").split("\0") if p]


def commit_state(root, cfg, command, message, kind, add_paths):
    """Stage exactly `add_paths` (must be allowed) and commit with the Herald-Record trailer."""
    globs = allowed_globs(cfg, command)
    bad = [p for p in add_paths if not _match(p, globs)]
    if bad:
        raise HeraldError("`%s` may not commit: %s" % (command, ", ".join(bad)))
    already = staged_paths(root)
    if already:
        raise HeraldError("index already has staged changes (%s) — refusing to mix them into a Herald record commit"
                          % ", ".join(already[:5]))
    import os
    tracked = set(p for p in git(root, "ls-files", "-z", "--", *add_paths).split("\0") if p) if add_paths else set()
    existing = [p for p in add_paths if os.path.exists(os.path.join(root, p)) or p in tracked]
    if existing:
        git(root, "add", "-A", "--", *existing)
    staged = staged_paths(root)
    stray = [p for p in staged if not _match(p, globs)]
    if stray:
        git(root, "reset", "-q", "--", *staged)
        raise HeraldError("refusing: staged paths outside `%s` allowance: %s" % (command, ", ".join(stray)))
    if not staged:
        return None
    git(root, "commit", "-q", "-m", message, "--trailer", "%s: %s" % (TRAILER, kind))
    return git(root, "rev-parse", "HEAD").strip()


def sync_base(root, cfg):
    """fetch + merge origin/<base> into base. A real merge gets the `Herald-Record: sync`
    trailer (plan §3.2.2 sync-merge definition); conflicts abort and stop."""
    base = cfg.base
    git(root, "checkout", "-q", base)
    git(root, "fetch", "-q", "origin", base)
    origin = "origin/%s" % base
    if git_ok(root, "merge-base", "--is-ancestor", origin, base):
        return "up-to-date"
    if git_ok(root, "merge-base", "--is-ancestor", base, origin):
        git(root, "merge", "-q", "--ff-only", origin)
        return "fast-forward"
    proc = run(["git", "merge", "--no-ff", "--no-commit", origin], cwd=root, check=False)
    if proc.returncode != 0:
        run(["git", "merge", "--abort"], cwd=root, check=False)
        raise HeraldError("syncing %s with origin conflicts — resolve by hand, then rerun" % base)
    git(root, "commit", "-q", "-m", "chore(herald): sync %s" % base, "--trailer", "%s: sync" % TRAILER)
    return "merged"


# --- ahead-of-origin classification (step 1) ----------------------------------------------

def trailer(root, sha):
    out = git(root, "log", "-1", "--format=%(trailers:key=" + TRAILER + ",valueonly)", sha)
    return out.strip() or None


def parents(root, sha):
    return git(root, "rev-list", "--parents", "-n", "1", sha).split()[1:]


def changed_files(root, a, b):
    return [p for p in git(root, "diff", "--name-only", "-z", a, b).split("\0") if p]


def is_sync_merge(root, cfg, sha, origin_ref):
    """Plan §3.2.2: second parent is origin/<base> or its ancestor, and the merge adds nothing
    beyond the automatic merge result except conflict resolutions inside record paths."""
    ps = parents(root, sha)
    if len(ps) != 2:
        return False
    if not git_ok(root, "merge-base", "--is-ancestor", ps[1], origin_ref):
        return False
    proc = run(["git", "merge-tree", "--write-tree", "--no-messages", ps[0], ps[1]], cwd=root, check=False)
    if proc.returncode not in (0, 1):
        return False
    auto_tree = proc.stdout.split()[0]
    commit_tree = git(root, "rev-parse", sha + "^{tree}").strip()
    if proc.returncode == 0:
        return auto_tree == commit_tree
    return all(_match(p, record_globs(cfg)) for p in changed_files(root, auto_tree, commit_tree))


def classify_ahead(root, cfg, base, origin_ref=None):
    origin_ref = origin_ref or "origin/%s" % base
    shas = git(root, "rev-list", "--reverse", "%s..%s" % (origin_ref, base)).split()
    out = []
    for sha in shas:
        kind = trailer(root, sha)
        ps = parents(root, sha)
        ok = False
        why = "no Herald-Record trailer"
        if kind:
            if len(ps) == 2:
                ok = is_sync_merge(root, cfg, sha, origin_ref)
                why = "sync merge" if ok else "merge adds changes beyond the automatic merge result"
            else:
                files = changed_files(root, ps[0], sha) if ps else []
                bad = [f for f in files if not _match(f, record_globs(cfg))]
                ok = not bad
                why = "record commit" if ok else "touches non-record paths: %s" % ", ".join(bad[:5])
        out.append({"sha": sha, "trailer": kind, "ok": ok, "why": why,
                    "subject": git(root, "log", "-1", "--format=%s", sha).strip()})
    return out


# --- PR file scope -------------------------------------------------------------------------

def pr_scope_globs(cfg, tid, slug):
    return [".claude/herald/work/%s/*" % tid, cfg.body_path(slug), cfg.image_dir(slug) + "/*",
            cfg.image_dir(slug) + "/**"]


def scope_check(root, cfg, tid, slug, rev="HEAD", base_ref=None, herald_sha=None):
    base_ref = base_ref or "origin/%s" % cfg.base
    files = [p for p in git(root, "diff", "--name-only", "-z", "%s...%s" % (base_ref, rev)).split("\0") if p]
    globs = pr_scope_globs(cfg, tid, slug)
    bad = [p for p in files if not _match(p, globs)]
    tampered = []
    if herald_sha and herald_sha != rev:
        if git_ok(root, "merge-base", "--is-ancestor", herald_sha, rev):
            later = changed_files(root, herald_sha, rev)
            tampered = [p for p in later if p.startswith(".claude/herald/work/%s/" % tid)
                        and p.rsplit("/", 1)[-1] in ("state.json", "verify.json", "critique.json")]
        else:
            tampered = ["(history rewritten after Herald's last push)"]
    return {"ok": not bad and not tampered, "files": files, "out_of_scope": bad, "tampered": tampered}
