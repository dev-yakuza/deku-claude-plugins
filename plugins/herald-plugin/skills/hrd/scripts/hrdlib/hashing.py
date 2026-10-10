"""Article content hash (plan §3.2).

The hash covers one article = its body file + its slug image directory, as a list of
(repo-relative path, git blob id). Two input modes must agree on the same commit:

- worktree: tracked files + untracked files that are not gitignored, restricted to files that
  exist on disk (`git ls-files --cached --others --exclude-standard`). Blob ids come from
  `git hash-object`, so clean filters / LFS pointers match what a commit would store.
- tree-ish: the same paths as stored in a commit (`git ls-tree -r <rev>`), for PR heads that are
  not checked out.

Gitignored build derivatives (e.g. .avif/.webp a build generates next to tracked images) are
outside both modes on purpose: including them would make every build change the hash.
"""

import hashlib
import os

from .util import git


def _digest(entries):
    if not entries:
        return None
    h = hashlib.sha256()
    for path, blob in sorted(entries):
        h.update(path.encode("utf-8") + b"\0" + blob.encode("ascii") + b"\n")
    return "sha256:" + h.hexdigest()


def _hash_objects(root, files):
    from .util import run

    proc = run(["git", "hash-object", "--stdin-paths"], cwd=root, input_text="\n".join(files) + "\n")
    return proc.stdout.split()


def worktree_hash(root, cfg, slug, path=None):
    body = path or cfg.body_path(slug)
    img = cfg.image_dir(slug)
    out = git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", body, img)
    files = sorted({p for p in out.split("\0") if p and os.path.isfile(os.path.join(root, p))})
    if not files:
        return None
    return _digest(list(zip(files, _hash_objects(root, files))))


def tree_entries(root, cfg, rev, slug, path=None):
    body = path or cfg.body_path(slug)
    img = cfg.image_dir(slug)
    out = git(root, "ls-tree", "-r", "-z", rev, "--", body, img)
    entries = []
    for rec in out.split("\0"):
        if not rec:
            continue
        meta, _, p = rec.partition("\t")
        parts = meta.split()
        if len(parts) >= 3 and parts[1] == "blob":
            entries.append((p, parts[2]))
    return entries


def tree_hash(root, cfg, rev, slug, path=None):
    return _digest(tree_entries(root, cfg, rev, slug, path))


def file_hash(root, relpath):
    """Hash of a single artifact file (stage output hashes)."""
    full = os.path.join(root, relpath)
    if not os.path.isfile(full):
        return None
    h = hashlib.sha256()
    with open(full, "rb") as f:
        h.update(f.read())
    return "sha256:" + h.hexdigest()
