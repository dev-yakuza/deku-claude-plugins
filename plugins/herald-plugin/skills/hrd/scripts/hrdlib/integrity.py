"""Pre-deploy integrity (plan §3.2.2 steps 1, 2, 7).

Deploying builds the whole working directory, so before any deploy every Herald article on
base must match the verification ledger, there must be no untracked build inputs, and no
image directory may be left holding only ignored build residue.
"""

import os

from . import ghstate
from .hashing import bundle_files, bundle_hash, tree_hash, worktree_hash
from .store import ledger_latest, load_published, read_json_at, state_path, work_rel
from .util import git, read_json


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


def _rewrite_moved(cfg, slug, base, old_slugs):
    """Map a reference's paths under an old slug (`moved_from`) onto the current slug's paths,
    role by role. Returns (files, rewritten?)."""
    out, moved = {}, False
    for path, v in base.items():
        new = path
        if cfg.path_role(slug, path) is None:
            role = v.get("role")
            for old in old_slugs:
                if role == "src" and path == cfg.body_path(old):
                    new = cfg.body_path(slug)
                elif role == "img" and path.startswith(cfg.image_dir(old).rstrip("/") + "/"):
                    new = cfg.image_dir(slug) + path[len(cfg.image_dir(old).rstrip("/")):]
                elif role in cfg.target_langs() and path == cfg.body_path(old, role):
                    new = cfg.body_path(slug, role)
                if new != path:
                    moved = True
                    break
        out[new] = v
    return out, moved


def diagnose(cfg, slug, cur, base=None, base_digest=None, cur_source=None, old_slugs=()):
    """Causes of a bundle mismatch (01-multilingual.md §3). `base` = the reference's files
    ({path: {blob, role}}); without it (a 0.8.0 ledger line, or a state with only a hash) the
    source digest stands in: those lines predate translations, so any translation is added."""
    langs = sorted({v["role"] for v in cur.values() if v.get("role") not in ("src", "img", None)})
    added = ["translation_added:%s" % l for l in langs]
    if base is None:
        return added if (base_digest and cur_source == base_digest) else ["source_changed"] + added
    base, moved = _rewrite_moved(cfg, slug, base, old_slugs)
    causes = []
    for path, v in sorted(base.items()):
        role = v.get("role")
        if role not in ("src", "img") and not cfg.explains(path):
            causes.append("unknown_path")
            continue
        c = cur.get(path)
        if c is None:
            causes.append("source_missing" if role == "src" else
                          "image_changed" if role == "img" else "translation_missing:%s" % role)
        elif c.get("blob") != v.get("blob"):
            causes.append("source_changed" if role == "src" else
                          "image_changed" if role == "img" else "translation_changed:%s" % role)
    for path, c in sorted(cur.items()):
        if path not in base:
            role = c.get("role")
            causes.append("source_changed" if role == "src" else
                          "image_changed" if role == "img" else "translation_added:%s" % role)
    causes = sorted(set(causes))
    if moved:
        causes = ["moved"] + causes
    return causes


def _causes(root, cfg, rev, slug, ref, led, article):
    cur = bundle_files(root, cfg, slug, rev=rev)
    cur_source = tree_hash(root, cfg, rev, slug) if rev else worktree_hash(root, cfg, slug)
    old = [m["slug"] for m in (article or {}).get("moved_from") or [] if m.get("slug")]
    if led is not None:
        if led.get("files"):
            return diagnose(cfg, slug, cur, base=led["files"], old_slugs=old)
        return diagnose(cfg, slug, cur, base_digest=led.get("verified_hash"), cur_source=cur_source, old_slugs=old)
    # no ledger line on this machine: the reference's committed state.json (basis 3)
    if not ref:
        return []
    rel = work_rel(ref, "state.json")
    st = read_json_at(root, rev, rel) if rev else read_json(state_path(root, ref))
    st = st or {}
    if st.get("verified_files"):
        return diagnose(cfg, slug, cur, base=st["verified_files"], old_slugs=old)
    return diagnose(cfg, slug, cur, base_digest=st.get("verified_hash"), cur_source=cur_source, old_slugs=old)


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
        cur = bundle_hash(root, cfg, slug, rev=rev)
        led = ledger_latest(root, m["ref_topic"]) if m["ref_topic"] else None
        if cur is None:
            status = "missing"
        elif led is None:
            status = "no-ledger"
        elif led.get("verified_hash") == cur:
            status = "ok"
        else:
            status = "mismatch"
        row = {"slug": slug, "ref_topic": m["ref_topic"], "status": status,
               "current": cur, "ledger": (led or {}).get("verified_hash"),
               "merged_unrecorded": m["merged_unrecorded"], "sources": m["sources"]}
        if cfg.translations() and status in ("mismatch", "no-ledger"):
            # what changed, for ship step 2's cause table (01-multilingual.md §5)
            art = next((a for a in pub["articles"] if a.get("slug") == slug), None)
            row["causes"] = _causes(root, cfg, rev, slug, m["ref_topic"], led, art)
        results.append(row)
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
