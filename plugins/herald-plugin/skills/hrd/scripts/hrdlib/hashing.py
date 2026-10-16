"""Article content hashes (plan §3.2, design/herald/01-multilingual.md §3).

Two scopes, both lists of (repo-relative path, git blob id):

- source: the body file + its slug image directory (what critique, the editor and the
  auditor rounds evaluate) — `worktree_hash` / `tree_hash`, unchanged from 0.8.0.
- bundle: source + every configured translation path that exists (what verify, the ledger,
  integrity and ship compare) — `bundle_hash` / `bundle_tree_hash`. Paths that do not exist
  add nothing, so without translations the two are equal.
 Two input modes must agree on the same commit:

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


def _worktree_entries(root, paths_):
    out = git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", *paths_)
    files = sorted({p for p in out.split("\0") if p and os.path.isfile(os.path.join(root, p))})
    return list(zip(files, _hash_objects(root, files))) if files else []


def _tree_entries(root, rev, paths_):
    out = git(root, "ls-tree", "-r", "-z", rev, "--", *paths_)
    entries = []
    for rec in out.split("\0"):
        if not rec:
            continue
        meta, _, p = rec.partition("\t")
        parts = meta.split()
        if len(parts) >= 3 and parts[1] == "blob":
            entries.append((p, parts[2]))
    return entries


def worktree_hash(root, cfg, slug, path=None):
    """Source hash: body (or `path`) + image dir."""
    return _digest(_worktree_entries(root, [path or cfg.body_path(slug), cfg.image_dir(slug)]))


source_hash = worktree_hash


def tree_entries(root, cfg, rev, slug, path=None):
    return _tree_entries(root, rev, [path or cfg.body_path(slug), cfg.image_dir(slug)])


def tree_hash(root, cfg, rev, slug, path=None):
    return _digest(tree_entries(root, cfg, rev, slug, path))


def bundle_entries(root, cfg, slug, rev=None):
    paths_ = cfg.bundle_paths(slug)
    return _tree_entries(root, rev, paths_) if rev else _worktree_entries(root, paths_)


def bundle_hash(root, cfg, slug, rev=None):
    """Source + every configured translation that exists (the bundle, §3)."""
    return _digest(bundle_entries(root, cfg, slug, rev))


def bundle_tree_hash(root, cfg, rev, slug):
    return bundle_hash(root, cfg, slug, rev=rev)


def lang_hash(root, cfg, slug, lang, rev=None):
    """One translation file (`lang` = a target) — or the source (body + images) for the source
    language — as `verify.json` `by_lang[l].hash` records it."""
    if lang == cfg.source_lang():
        return tree_hash(root, cfg, rev, slug) if rev else worktree_hash(root, cfg, slug)
    p = [cfg.body_path(slug, lang)]
    return _digest(_tree_entries(root, rev, p) if rev else _worktree_entries(root, p))


def bundle_files(root, cfg, slug, rev=None):
    """{path: {"blob", "role"}} of the bundle — the ledger's `files` (L17) and state.json
    `verified_files`, so a later integrity check can say what changed."""
    return {p: {"blob": b, "role": cfg.path_role(slug, p)} for p, b in bundle_entries(root, cfg, slug, rev)}


def digest_files(files):
    return _digest([(p, v["blob"]) for p, v in (files or {}).items()])


def file_hash(root, relpath):
    """Hash of a single artifact file (stage output hashes)."""
    full = os.path.join(root, relpath)
    if not os.path.isfile(full):
        return None
    h = hashlib.sha256()
    with open(full, "rb") as f:
        h.update(f.read())
    return "sha256:" + h.hexdigest()
