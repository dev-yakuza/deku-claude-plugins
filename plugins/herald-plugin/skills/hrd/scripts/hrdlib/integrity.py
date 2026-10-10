"""Pre-deploy integrity (plan §3.2.2 steps 1, 2, 7).

Deploying builds the whole working directory, so before any deploy every Herald article on
base must match the verification ledger, there must be no untracked build inputs, and no
image directory may be left holding only ignored build residue.
"""

import os

from . import ghstate
from .hashing import tree_hash, worktree_hash
from .store import ledger_latest, load_published
from .util import git


def untracked_build_inputs(root, cfg):
    inputs = cfg.get("paths", "build_inputs") or []
    if not inputs:
        return []
    out = git(root, "ls-files", "-z", "--others", "--exclude-standard", "--", *inputs)
    return [p for p in out.split("\0") if p]


def tracked_dirty(root):
    out = git(root, "status", "--porcelain", "--untracked-files=no")
    return [l[3:] for l in out.splitlines() if l.strip()]


def ignored_residue(root, cfg):
    """Image dirs with no body at HEAD and only gitignored files left (a build may fail on
    an image directory without an article — e.g. check-blog-images.mjs)."""
    images = os.path.join(root, cfg.get("paths", "images"))
    if not os.path.isdir(images):
        return []
    out = []
    for name in sorted(os.listdir(images)):
        d = os.path.join(images, name)
        if not os.path.isdir(d) or os.path.exists(os.path.join(root, cfg.body_path(name))):
            continue
        rel = os.path.relpath(d, root)
        kept = git(root, "ls-files", "--cached", "--others", "--exclude-standard", "--", rel).strip()
        has_files = any(files for _, _, files in os.walk(d))
        if has_files and not kept:
            out.append(rel)
    return out


def check(root, cfg, rev=None, prs=None):
    """Compare every Herald article with its reference topic's latest ledger hash.

    rev=None reads the working tree (base is checked out and clean); otherwise a commit.
    Returns {"ok", "articles": [...], "flags": [...]}.
    """
    pub = load_published(root)
    prs = prs if prs is not None else ghstate.herald_prs(root, cfg)
    members = ghstate.herald_set(root, cfg, prs=prs, pub=pub)
    results = []
    for slug, m in sorted(members.items()):
        cur = tree_hash(root, cfg, rev, slug) if rev else worktree_hash(root, cfg, slug)
        led = ledger_latest(root, m["ref_topic"]) if m["ref_topic"] else None
        if cur is None:
            status = "missing"
        elif led is None:
            status = "no-ledger"
        elif led.get("verified_hash") == cur:
            status = "ok"
        else:
            status = "mismatch"
        results.append({"slug": slug, "ref_topic": m["ref_topic"], "status": status,
                        "current": cur, "ledger": (led or {}).get("verified_hash"),
                        "merged_unrecorded": m["merged_unrecorded"], "sources": m["sources"]})
    flags = ghstate.reappearance_flags(root, cfg, prs=prs, pub=pub)
    ok = all(r["status"] == "ok" for r in results) and not flags
    return {"ok": ok, "articles": results, "flags": flags}


def predeploy(root, cfg, prs=None):
    """Step 7 (a)+(b): clean tree, no untracked build inputs, no residue, full integrity."""
    report = check(root, cfg, prs=prs)
    report["untracked_build_inputs"] = untracked_build_inputs(root, cfg)
    report["tracked_dirty"] = tracked_dirty(root)
    report["ignored_residue"] = ignored_residue(root, cfg)
    report["ok"] = (report["ok"] and not report["untracked_build_inputs"]
                    and not report["tracked_dirty"] and not report["ignored_residue"])
    return report
