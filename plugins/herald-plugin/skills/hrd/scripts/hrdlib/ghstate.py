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
    from .hashing import worktree_hash

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
        if not os.path.exists(os.path.join(root, cfg.body_path(slug))):
            continue
        if later_pr(slug, at, topics_):
            continue
        rel = releases.get(slug)
        if rel and rel.get("content_hash") == worktree_hash(root, cfg, slug) and not later_pr(slug, rel.get("at"), set()):
            continue
        flags.append({"slug": slug, "why": why})
    return flags


def add_label(root, number, label):
    gh(root, "pr", "edit", str(number), "--add-label", label)


def remove_label(root, number, label):
    gh(root, "pr", "edit", str(number), "--remove-label", label)
