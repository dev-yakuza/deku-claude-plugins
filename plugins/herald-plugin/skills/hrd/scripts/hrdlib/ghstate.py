"""GitHub-derived state (plan §3.2.1): open/merged Herald PRs, removal reverts, and the
"Herald article set" with each slug's reference topic id.

Stored state lives in topics.json; "in progress", "PR pending" and "merged-unrecorded" are
derived from branches and PRs so that several PRs never fight over the same JSON file.
"""

from .store import parse_branch, load_published, load_topics
from .util import gh, gh_json, git

PR_FIELDS = "number,state,headRefName,headRefOid,mergedAt,labels,baseRefName,title"

REVERTED = "herald:reverted"
WITHDRAWN = "herald:withdrawn"
REVERT_REMOVE = "herald-revert:remove"
REVERT_RESTORE = "herald-revert:restore"


def _labels(pr):
    return {l["name"] if isinstance(l, dict) else l for l in pr.get("labels") or []}


def herald_prs(root, cfg, state="all"):
    prs = gh_json(root, "pr", "list", "--label", cfg.get("gh", "label"), "--state", state,
                  "--limit", "1000", "--json", PR_FIELDS)
    out = []
    for pr in prs:
        parsed = parse_branch(pr.get("headRefName"))
        if not parsed:
            continue
        pr["topic_id"], pr["slug"] = parsed
        pr["label_set"] = _labels(pr)
        out.append(pr)
    return out


def revert_prs(root, cfg):
    prs = gh_json(root, "pr", "list", "--label", cfg.get("gh", "revert_label"), "--state", "merged",
                  "--limit", "1000", "--json", PR_FIELDS)
    out = []
    for pr in prs:
        head = pr.get("headRefName") or ""
        if not head.startswith("herald-revert/"):
            continue
        pr["topic_id"] = head[len("herald-revert/"):].split("/", 1)[0]
        pr["label_set"] = _labels(pr)
        out.append(pr)
    return out


def local_branches(root):
    out = git(root, "for-each-ref", "--format=%(refname:short)", "refs/heads/herald/")
    return [b for b in out.split() if parse_branch(b)]


def pending_removal_reverts(root, cfg, topics=None):
    """Merged `herald-revert:remove` PRs not yet listed in the topic's `reverted_by` (plan:
    the detection key is the revert PR, so a requeued or republished topic is never re-held)."""
    topics = topics or load_topics(root)
    seen = {(t["id"], n) for t in topics["topics"] for n in t.get("reverted_by", [])}
    return [pr for pr in revert_prs(root, cfg)
            if REVERT_REMOVE in pr["label_set"] and (pr["topic_id"], pr["number"]) not in seen]


def alias_map(pub):
    """topic_id -> current slug, for topics merged under a slug that was later moved."""
    out = {}
    for a in pub["articles"]:
        for m in a.get("moved_from") or []:
            for tid in m.get("topic_ids") or []:
                out[tid] = a["slug"]
    return out


def herald_set(root, cfg, prs=None, pub=None):
    """Return {slug: {"path", "ref_topic", "sources", "merged_unrecorded"}} plus flags.

    Members = published.json `origin: herald` articles ∪ slugs of merged Herald PRs, minus
    PRs labelled reverted/withdrawn and withdrawn entries. Reference topic = most recently
    merged Herald PR for the slug (aliases followed), else `current_topic_id`.
    """
    pub = pub or load_published(root)
    prs = prs if prs is not None else herald_prs(root, cfg)
    aliases = alias_map(pub)
    topics = {t["id"]: t for t in load_topics(root)["topics"]}
    withdrawn_topics = set()
    for a in pub["articles"]:
        if a.get("withdrawn"):
            withdrawn_topics.update(a.get("withdrawn_topics") or [a.get("current_topic_id")])
    members = {}
    for a in pub["articles"]:
        if a.get("origin") == "herald" and not a.get("withdrawn"):
            members[a["slug"]] = {"path": a.get("path") or cfg.body_path(a["slug"]),
                                  "ref_topic": a.get("current_topic_id"), "ref_merged_at": "",
                                  "sources": ["published"], "merged_unrecorded": False}
    merged = [p for p in prs if p.get("mergedAt")]
    for pr in sorted(merged, key=lambda p: p["mergedAt"]):
        if pr["label_set"] & {REVERTED, WITHDRAWN} or pr["topic_id"] in withdrawn_topics:
            continue
        slug = aliases.get(pr["topic_id"], pr["slug"])
        m = members.setdefault(slug, {"path": cfg.body_path(slug), "ref_topic": None,
                                      "ref_merged_at": "", "sources": [], "merged_unrecorded": False})
        m["sources"].append("pr#%d" % pr["number"])
        if pr["mergedAt"] >= m["ref_merged_at"]:
            m["ref_topic"], m["ref_merged_at"] = pr["topic_id"], pr["mergedAt"]
        t = topics.get(pr["topic_id"])
        if not t or t.get("state") not in ("published", "withdrawn"):
            m["merged_unrecorded"] = True
        if t and t.get("state") == "unwithdrawn":
            m["merged_unrecorded"] = True
    return members


def reappearance_flags(root, cfg, prs=None, pub=None):
    """Withdrawn slugs / moved-away slugs that have files again with no later Herald PR, minus
    active releases (plan §3.2.1 withdrawn row, §3.2.2 exit ⓪)."""
    import os
    from .hashing import bundle_hash

    pub = pub or load_published(root)
    prs = prs if prs is not None else herald_prs(root, cfg)
    merged = [p for p in prs if p.get("mergedAt")]
    releases = {r["slug"]: r for r in pub.get("releases") or []}
    flags = []

    def later_pr(slug, after, exclude_topics):
        return any(p["slug"] == slug and p["mergedAt"] > (after or "")
                   and p["topic_id"] not in exclude_topics
                   and not (p["label_set"] & {REVERTED, WITHDRAWN}) for p in merged)

    candidates = []
    for a in pub["articles"]:
        if a.get("withdrawn"):
            candidates.append((a["slug"], a.get("withdrawn_at"), set(a.get("withdrawn_topics") or []), "withdrawn"))
        for m in a.get("moved_from") or []:
            candidates.append((m["slug"], m.get("moved_at"), set(m.get("topic_ids") or []), "moved"))
    for slug, at, topics_, why in candidates:
        # any bundle file counts: a withdrawn slug whose translation alone came back is flagged too
        # the body or a translation (not the image dir: as in 0.8.0, image residue is ship's
        # residue check, L15)
        if not any(os.path.exists(os.path.join(root, p)) for p in [cfg.body_path(slug)] + list(cfg.translation_paths(slug).values())):
            continue
        if later_pr(slug, at, topics_):
            continue
        rel = releases.get(slug)
        if rel and rel.get("content_hash") == bundle_hash(root, cfg, slug) and not later_pr(slug, rel.get("at"), set()):
            continue
        flags.append({"slug": slug, "why": why})
    return flags


def add_label(root, number, label):
    gh(root, "pr", "edit", str(number), "--add-label", label)


def remove_label(root, number, label):
    gh(root, "pr", "edit", str(number), "--remove-label", label)


def selectable(root, cfg, prs=None):
    """Topic selection rule (plan §3.2.1): stored `queued` and no open Herald PR, no merged
    Herald PR (reverted/withdrawn excluded) and no local herald branch for the topic."""
    prs = prs if prs is not None else herald_prs(root, cfg)
    busy = set()
    for p in prs:
        if p["state"] == "OPEN":
            busy.add(p["topic_id"])
        elif p.get("mergedAt") and not (p["label_set"] & {REVERTED, WITHDRAWN}):
            busy.add(p["topic_id"])
    busy |= {b[len("herald/"):].split("--", 1)[0] for b in local_branches(root)}
    return [t["id"] for t in load_topics(root)["topics"] if t.get("state") == "queued" and t["id"] not in busy]


# L16 (01-multilingual.md): holds whose work is kept count as in progress — judged by reason,
# not by the branch (a preserved branch is local to one machine)
IN_PROGRESS_HOLDS = ("needs-human", "stagnation", "budget", "verify-after-human-edit")


def in_progress_topics(root, cfg, prs=None):
    """Topics still in flight, with the slug each one works on when it can be known here:
    queued, in progress, a kept hold, PR pending, merged-unrecorded. Inputs: topics.json (r-/tr-
    carry their slug), Herald PRs and local herald branch names (both carry it), and a state.json
    left in the working tree."""
    import os

    from .util import read_json

    prs = prs if prs is not None else herald_prs(root, cfg)
    local = local_branches(root)
    out = []
    for t in load_topics(root)["topics"]:
        tid, stored = t["id"], t.get("state")
        if stored in ("published", "withdrawn", "declined"):
            continue
        mine = [p for p in prs if p["topic_id"] == tid]
        merged = [p for p in mine if p.get("mergedAt") and not (p["label_set"] & {REVERTED, WITHDRAWN})]
        open_ = [p for p in mine if p["state"] == "OPEN"]
        branches = [b for b in local if b.startswith("herald/%s--" % tid)]
        if stored == "held" and t.get("reason") not in IN_PROGRESS_HOLDS and not open_ and not merged:
            continue
        slug = t.get("slug") or t.get("refresh_of") or t.get("translate_of")
        if not slug:
            for name in [p["headRefName"] for p in mine] + branches:
                parsed = parse_branch(name)
                if parsed:
                    slug = parsed[1]
                    break
        if not slug:
            st = read_json(os.path.join(root, ".claude", "herald", "work", tid, "state.json")) or {}
            slug = st.get("slug")
        out.append({"id": tid, "slug": slug, "state": stored})
    return out


def slug_busy(root, cfg, slug, exclude=None, prs=None):
    """The ids of other in-progress topics on `slug` (translation repos only — without
    translations overlapping topics surface as source conflicts, as in 0.8.0)."""
    if not cfg.translations() or not slug:
        return []
    return [t["id"] for t in in_progress_topics(root, cfg, prs=prs) if t["slug"] == slug and t["id"] != exclude]

