#!/usr/bin/env python3
"""Herald deterministic CLI. Commands (`/hrd ...`) call this for every state change so the
rules in design/herald/00-plan.md are enforced by code, not by prompt text.

Usage: python3 .claude/herald/scripts/hrd.py <group> <action> [...]
Every subcommand prints JSON on success and exits non-zero with a human-readable message on a
failed precondition.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hrdlib import commits, ghstate, integrity, lock, store  # noqa: E402
from hrdlib.config import Config  # noqa: E402
from hrdlib.hashing import tree_hash, worktree_hash  # noqa: E402
from hrdlib.util import HeraldError, emit, git, git_ok, now_iso, read_json, repo_root, write_json  # noqa: E402


def ctx():
    root = repo_root()
    return root, Config.load(root)


def attended_only(what):
    """Base-branch writers: unattended children never write base (plan §3.2.1) — the batch
    runner does. The guard only sees `git commit`; this covers writes made inside hrd.py."""
    if os.environ.get("HRD_UNATTENDED") == "1":
        raise HeraldError("%s writes the base branch — not allowed in unattended sessions (the batch runner records)" % what)


# --- lock -------------------------------------------------------------------------------------

def cmd_lock(a):
    root = repo_root()
    if a.action == "acquire":
        emit({"token": lock.acquire(root, a.cmd)})
    elif a.action == "release":
        emit({"released": lock.release(root, a.token)})
    elif a.action == "status":
        emit({"lock": lock.status(root)})
    elif a.action == "unlock":
        emit({"removed": lock.force_unlock(root)})


# --- topics -----------------------------------------------------------------------------------

def cmd_topics(a):
    root, cfg = ctx()
    data = store.load_topics(root)
    if a.action == "add":
        incoming = json.load(sys.stdin if a.file in (None, "-") else open(a.file, encoding="utf-8"))
        added = []
        for item in incoming if isinstance(incoming, list) else [incoming]:
            if not item.get("title"):
                raise HeraldError("topic needs a title")
            tid = item.get("id") or store.next_topic_id(data)
            store.check_topic_id(tid)
            if any(t["id"] == tid for t in data["topics"]):
                raise HeraldError("topic %s exists" % tid)
            t = {"id": tid, "title": item["title"], "category": item.get("category"),
                 "keywords": item.get("keywords", []), "angle": item.get("angle", ""),
                 "refresh_of": item.get("refresh_of"), "slug": item.get("slug"),
                 "state": "queued", "reason": None, "reverted_by": [], "history": []}
            store.set_topic_state(t, "queued", note="added")
            data["topics"].append(t)
            added.append(tid)
        store.save_topics(root, data)
        emit({"added": added})
    elif a.action == "list":
        emit([{k: t.get(k) for k in ("id", "title", "category", "state", "reason", "slug")}
              for t in data["topics"] if not a.state or t.get("state") == a.state])
    elif a.action == "show":
        emit(store.get_topic(data, a.topic))


def derived_status(root, cfg):
    data = store.load_topics(root)
    prs = ghstate.herald_prs(root, cfg)
    local = ghstate.local_branches(root)
    out = []
    for t in data["topics"]:
        tid = t["id"]
        mine = [p for p in prs if p["topic_id"] == tid]
        merged = [p for p in mine if p.get("mergedAt") and not (p["label_set"] & {ghstate.REVERTED, ghstate.WITHDRAWN})]
        open_ = [p for p in mine if p["state"] == "OPEN"]
        branches = [b for b in local if b.startswith("herald/%s--" % tid)]
        stored = t.get("state")
        if stored == "withdrawn":
            d = "withdrawn"
        elif stored == "published":
            d = "published"
        elif merged and stored != "published":
            d = "merged-unrecorded"
        elif stored == "unwithdrawn":
            d = "merged-unrecorded"
        elif stored in ("declined", "held"):
            d = "%s:%s" % (stored, t.get("reason"))
        elif open_:
            d = "pr-pending"
        elif branches:
            d = "in-progress"
        else:
            d = stored
        out.append({"id": tid, "title": t.get("title"), "stored": stored, "reason": t.get("reason"),
                    "derived": d, "open_prs": [p["number"] for p in open_],
                    "merged_prs": [p["number"] for p in merged], "branches": branches})
    return out


def cmd_select(a):
    root, cfg = ctx()
    picked = ghstate.selectable(root, cfg)
    if a.topic:
        if a.topic not in picked:
            raise HeraldError("topic %s is not selectable (needs queued with no open/merged PR or local branch)" % a.topic)
        picked = [a.topic]
    emit(picked[: a.n] if a.n else picked)


def cmd_status(a):
    root, cfg = ctx()
    emit({"topics": derived_status(root, cfg), "lock": lock.status(root)})


# --- work lifecycle -----------------------------------------------------------------------------

def cmd_begin(a):
    """Create work/<id>/state.json on base (untracked; carried onto the branch by `branch`)."""
    root, cfg = ctx()
    store.check_topic_id(a.topic)
    if os.path.exists(store.state_path(root, a.topic)) and not a.force:
        emit({"resumed": True, "state": store.load_state(root, a.topic)})
        return
    st = store.new_state(a.topic, None)
    store.save_state(root, a.topic, st)
    emit({"created": store.work_rel(a.topic)})


def cmd_branch(a):
    """After brief: fix the slug and branch from origin/<base> (plan §3.2 branch origin)."""
    root, cfg = ctx()
    store.check_slug(a.slug)
    if "--" in a.slug:
        raise HeraldError("slug must not contain `--`")
    st = store.load_state(root, a.topic)
    st["slug"] = a.slug
    store.save_state(root, a.topic, st)
    name = store.branch_name(a.topic, a.slug)
    git(root, "fetch", "-q", "origin", cfg.base)
    if git_ok(root, "rev-parse", "--verify", "-q", "refs/heads/" + name):
        git(root, "switch", "-q", name)
    else:
        git(root, "switch", "-q", "-c", name, "origin/%s" % cfg.base)
    emit({"branch": name})


def cmd_stage(a):
    root, cfg = ctx()
    st = store.load_state(root, a.topic)
    if a.action == "check":
        problems = store.entry_check(root, cfg, st, a.stage)
        emit({"ok": not problems, "problems": problems})
        if problems:
            sys.exit(1)
    elif a.action == "pass":
        st = store.stage_pass(root, cfg, a.topic, a.stage, amend=a.amend)
        emit({"stage": st["stage"], "verified_hash": st.get("verified_hash")})


def cmd_loopback(a):
    root, cfg = ctx()
    st = store.load_state(root, a.topic)
    if not a.human:
        st["loopbacks"] = int(st.get("loopbacks", 0)) + 1
    st["stage"] = "draft"
    store.save_state(root, a.topic, st)
    n = st["loopbacks"]
    emit({"loopbacks": n, "cap": 3, "exhausted": n > 3, "escalate_tier": n >= 2})


def cmd_finalize(a):
    """publish entry: lock agent_final_hash once (never rewritten)."""
    root, cfg = ctx()
    st = store.load_state(root, a.topic)
    problems = store.entry_check(root, cfg, st, "publish")
    if problems:
        raise HeraldError("; ".join(problems))
    if not st.get("agent_final_hash"):
        st["agent_final_hash"] = st["verified_hash"]
    st["stage"] = "publish"
    store.save_state(root, a.topic, st)
    emit({"agent_final_hash": st["agent_final_hash"]})


def cmd_result(a):
    """Batch child result file (memory/batch/<id>.json) — children never write base."""
    root = repo_root()
    path = os.path.join(store.paths(root)["memory"], "batch", a.topic + ".json")
    write_json(path, {"status": a.status, "pr": a.pr, "note": a.note, "merged": a.merged or [], "at": now_iso()})
    emit({"written": path})


# --- hashes / ledger / scope ----------------------------------------------------------------------

def cmd_hash(a):
    root, cfg = ctx()
    emit({"hash": tree_hash(root, cfg, a.rev, a.slug) if a.rev else worktree_hash(root, cfg, a.slug)})


def cmd_ledger(a):
    root, cfg = ctx()
    if a.action == "record":
        emit(store.ledger_record(root, cfg, a.topic, sha=a.sha, kind=a.kind, rev=a.rev))
    else:
        emit(store.ledger_latest(root, a.topic))


def cmd_scope(a):
    root, cfg = ctx()
    st = store.read_json_at(root, a.rev, store.work_rel(a.topic, "state.json")) if a.rev != "HEAD" else store.load_state(root, a.topic)
    slug = a.slug or (st or {}).get("slug")
    if not slug:
        raise HeraldError("slug unknown for %s" % a.topic)
    led = store.ledger_latest(root, a.topic) or {}
    res = commits.scope_check(root, cfg, a.topic, slug, rev=a.rev, herald_sha=led.get("sha"))
    emit(res)
    if not res["ok"]:
        sys.exit(1)


def cmd_ahead(a):
    root, cfg = ctx()
    rows = commits.classify_ahead(root, cfg, cfg.base)
    emit({"commits": rows, "needs_human": [r for r in rows if not r["ok"]]})


def cmd_sync(a):
    root, cfg = ctx()
    emit({"sync": commits.sync_base(root, cfg, allow_merge=os.environ.get("HRD_UNATTENDED") != "1")})


def cmd_fetch_pr(a):
    """Bring a PR head (possibly pushed by a human) into refs/remotes/origin/pr-<n>."""
    root, cfg = ctx()
    ref = "refs/remotes/origin/pr-%d" % a.pr
    git(root, "fetch", "-q", "origin", "+pull/%d/head:%s" % (a.pr, ref))
    emit({"ref": ref, "sha": git(root, "rev-parse", ref).strip()})


def cmd_commit(a):
    root, cfg = ctx()
    attended_only("`commit`")
    sha = commits.commit_state(root, cfg, a.cmd, a.message, a.kind, a.paths)
    emit({"commit": sha})


def cmd_integrity(a):
    root, cfg = ctx()
    rep = integrity.predeploy(root, cfg) if a.predeploy else integrity.check(root, cfg, rev=a.rev)
    emit(rep)
    if not rep["ok"]:
        sys.exit(1)


def cmd_residue(a):
    root, cfg = ctx()
    dirs = integrity.ignored_residue(root, cfg)
    if a.clean:
        for d in dirs:
            git(root, "clean", "-q", "-fdX", "--", d)
    emit({"residue": dirs, "cleaned": bool(a.clean)})


def cmd_herald_set(a):
    root, cfg = ctx()
    emit(ghstate.herald_set(root, cfg))


def cmd_reverts(a):
    root, cfg = ctx()
    topics = store.load_topics(root)
    pending = ghstate.pending_removal_reverts(root, cfg, topics)
    if a.action == "apply":
        attended_only("`reverts apply`")
        prs = ghstate.herald_prs(root, cfg)
        for rv in pending:
            for p in prs:
                if p["topic_id"] == rv["topic_id"] and p.get("mergedAt"):
                    ghstate.add_label(root, p["number"], ghstate.REVERTED)
            t = store.get_topic(topics, rv["topic_id"])
            store.set_topic_state(t, "held", "reverted", "revert PR #%d" % rv["number"])
            t.setdefault("reverted_by", []).append(rv["number"])
        store.save_topics(root, topics)
    emit({"pending": [{"topic_id": p["topic_id"], "pr": p["number"]} for p in pending],
          "applied": a.action == "apply"})


# --- stored-state transitions ----------------------------------------------------------------------

def cmd_state(a):
    root, cfg = ctx()
    attended_only("`state`")
    data = store.load_topics(root)
    t = store.get_topic(data, a.topic)
    store.set_topic_state(t, a.state, a.reason, a.note)
    store.save_topics(root, data)
    emit({"id": t["id"], "state": t["state"], "reason": t["reason"]})


def _article_present(root, cfg, slug):
    return os.path.exists(os.path.join(root, cfg.body_path(slug))) or \
        os.path.isdir(os.path.join(root, cfg.image_dir(slug))) and bool(
            git(root, "ls-files", "--", cfg.image_dir(slug)).strip())


def cmd_requeue(a):
    root, cfg = ctx()
    attended_only("`requeue`")
    data = store.load_topics(root)
    t = store.get_topic(data, a.topic)
    if t["state"] not in ("held", "declined"):
        raise HeraldError("only held/declined topics can be requeued (state: %s)" % t["state"])
    for b in ghstate.local_branches(root):
        if b.startswith("herald/%s--" % a.topic):
            git(root, "branch", "-q", "-D", b)
    store.set_topic_state(t, "queued", note="requeued (reverted_by kept)")
    store.save_topics(root, data)
    emit({"id": a.topic, "state": "queued", "reverted_by": t.get("reverted_by", [])})


def cmd_drop(a):
    root, cfg = ctx()
    attended_only("`drop`")
    data = store.load_topics(root)
    t = store.get_topic(data, a.topic)
    t["dropped"] = True
    store.set_topic_state(t, "declined", "dropped", a.note)
    store.save_topics(root, data)
    emit({"id": a.topic, "state": "declined:dropped"})


def _topic_articles(pub, prs, slug):
    """All topic ids merged under this article (aliases included)."""
    art = store.find_article(pub, slug)
    tids = set()
    if art:
        tids.add(art.get("current_topic_id"))
        for m in art.get("moved_from") or []:
            tids.update(m.get("topic_ids") or [])
    tids |= {p["topic_id"] for p in prs if p.get("mergedAt") and p["slug"] == slug}
    tids.discard(None)
    return art, tids


def cmd_withdraw(a):
    root, cfg = ctx()
    attended_only("`withdraw`")
    pub = store.load_published(root)
    slug = a.slug_or_topic
    art = store.find_article(pub, slug) or store.find_article_by_topic(pub, slug)
    if not art:
        raise HeraldError("no published article %s" % slug)
    slug = art["slug"]
    if _article_present(root, cfg, slug):
        raise HeraldError("the body or tracked images of %s still exist on base — withdraw only after the human removed them "
                          "(to change the slug use `status --move`; to fix content use exit ①/②)" % slug)
    # Without a pathspec git can pair the rename (with one, the other side is out of scope and
    # it reports a delete) — look for any rename whose source is this body or image dir.
    renames = git(root, "log", "-M", "--diff-filter=R", "--name-status", "--format=").splitlines()
    img = cfg.image_dir(slug) + "/"
    renamed = [l for l in renames if l.startswith("R") and len(l.split("\t")) == 3
               and (l.split("\t")[1] == cfg.body_path(slug) or l.split("\t")[1].startswith(img))]
    if renamed:
        raise HeraldError("git shows %s was renamed — use `status --move`, not withdraw" % slug)
    prs = ghstate.herald_prs(root, cfg)
    _, tids = _topic_articles(pub, prs, slug)
    for p in prs:
        if p.get("mergedAt") and p["topic_id"] in tids:
            ghstate.add_label(root, p["number"], ghstate.WITHDRAWN)
    art.update({"withdrawn": True, "withdrawn_at": now_iso(), "withdrawn_topics": sorted(tids)})
    data = store.load_topics(root)
    for t in data["topics"]:
        if t["id"] in tids:
            store.set_topic_state(t, "withdrawn", note=a.note)
    store.save_published(root, pub)
    store.save_topics(root, data)
    emit({"withdrawn": slug, "topics": sorted(tids)})


def cmd_unwithdraw(a):
    root, cfg = ctx()
    attended_only("`unwithdraw`")
    pub = store.load_published(root)
    art = store.find_article(pub, a.slug_or_topic) or store.find_article_by_topic(pub, a.slug_or_topic)
    if not art or not art.get("withdrawn"):
        raise HeraldError("no withdrawn article %s" % a.slug_or_topic)
    if not os.path.exists(os.path.join(root, cfg.body_path(art["slug"]))):
        raise HeraldError("restore the body on base first")
    tids = set(art.get("withdrawn_topics") or [])
    for p in ghstate.herald_prs(root, cfg):
        if p["topic_id"] in tids and ghstate.WITHDRAWN in p["label_set"]:
            ghstate.remove_label(root, p["number"], ghstate.WITHDRAWN)
    art["withdrawn"] = False
    data = store.load_topics(root)
    for t in data["topics"]:
        if t["id"] in tids:
            store.set_topic_state(t, "unwithdrawn", note="restored; next ship re-checks and deploys")
    store.save_published(root, pub)
    store.save_topics(root, data)
    emit({"unwithdrawn": art["slug"]})


def cmd_move(a):
    root, cfg = ctx()
    attended_only("`move`")
    store.check_slug(a.new_slug)
    pub = store.load_published(root)
    art = store.find_article_by_topic(pub, a.topic) or store.find_article(pub, a.topic)
    if not art:
        raise HeraldError("`move` needs a published article (merged-unrecorded: move the files back and run ship)")
    old = art["slug"]
    if os.path.exists(os.path.join(root, cfg.body_path(old))):
        raise HeraldError("old path %s still exists" % cfg.body_path(old))
    if not os.path.exists(os.path.join(root, cfg.body_path(a.new_slug))):
        raise HeraldError("new path %s does not exist" % cfg.body_path(a.new_slug))
    if os.path.isdir(os.path.join(root, cfg.image_dir(old))) and git(root, "ls-files", "--", cfg.image_dir(old)).strip():
        raise HeraldError("tracked images still under %s — move them too" % cfg.image_dir(old))
    prs = ghstate.herald_prs(root, cfg)
    _, tids = _topic_articles(pub, prs, old)
    art.setdefault("moved_from", []).append({"slug": old, "moved_at": now_iso(),
                                             "moved_at_commit": git(root, "rev-parse", "HEAD").strip(),
                                             "topic_ids": sorted(tids)})
    art["slug"] = a.new_slug
    art["path"] = cfg.body_path(a.new_slug)
    art["url"] = cfg.article_url(a.new_slug)
    store.save_published(root, pub)
    # re-verification on base reads work/<tid>/state.json's slug — point it at the new path
    updated = []
    for tid in sorted(tids):
        sp = store.state_path(root, tid)
        st = read_json(sp)
        if st and st.get("slug") == old:
            st["slug"] = a.new_slug
            write_json(sp, st)
            updated.append(store.work_rel(tid, "state.json"))
    emit({"moved": old, "to": a.new_slug, "topic_ids": sorted(tids), "state_files": updated,
          "note": "commit published.json and the state files; next ship re-verifies (path is part of the hash)"})


def cmd_release_slug(a):
    root, cfg = ctx()
    attended_only("`release-slug`")
    pub = store.load_published(root)
    slug = a.slug
    if slug in ghstate.herald_set(root, cfg, pub=pub):
        raise HeraldError("%s is a current Herald article — release applies only to withdrawn or moved-away slugs" % slug)
    known = any(x.get("withdrawn") and x["slug"] == slug for x in pub["articles"]) or \
        any(m["slug"] == slug for x in pub["articles"] for m in x.get("moved_from") or [])
    if not known:
        raise HeraldError("%s is neither withdrawn nor a moved-away slug" % slug)
    rel = {"slug": slug, "at": now_iso(), "content_hash": worktree_hash(root, cfg, slug)}
    pub["releases"] = [r for r in pub.get("releases", []) if r["slug"] != slug] + [rel]
    if not store.find_article(pub, slug):
        pub["articles"].append({"slug": slug, "path": cfg.body_path(slug), "origin": "external",
                                "url": cfg.article_url(slug), "published_at": now_iso()})
    store.save_published(root, pub)
    emit(rel)


def cmd_mark_published(a):
    """External publish record (`status --mark-published`, `ship --deploy-only`): URL checked by caller."""
    root, cfg = ctx()
    attended_only("`mark-published`")
    prs = ghstate.herald_prs(root, cfg)
    if any(p["topic_id"] == a.topic and p.get("mergedAt") for p in prs):
        raise HeraldError("%s has a merged Herald PR — use `ship`, not an external record" % a.topic)
    pub = store.load_published(root)
    data = store.load_topics(root)
    t = store.get_topic(data, a.topic)
    art = store.find_article(pub, a.slug) or {"slug": a.slug, "moved_from": []}
    if art not in pub["articles"]:
        pub["articles"].append(art)
    art.update({"path": cfg.body_path(a.slug), "url": cfg.article_url(a.slug), "origin": "external",
                "published_at": now_iso(), "current_topic_id": a.topic})
    t["slug"] = a.slug
    store.set_topic_state(t, "published", note="external publish")
    store.save_published(root, pub)
    store.save_topics(root, data)
    emit({"published": a.slug, "origin": "external"})


def cmd_record_published(a):
    """ship step 9 for one Herald article (URL already confirmed)."""
    root, cfg = ctx()
    attended_only("`record-published`")
    pub = store.load_published(root)
    data = store.load_topics(root)
    t = store.get_topic(data, a.topic)
    art = store.find_article(pub, a.slug)
    if not art:
        art = {"slug": a.slug, "moved_from": []}
        pub["articles"].append(art)
    art.update({"path": cfg.body_path(a.slug), "url": cfg.article_url(a.slug), "origin": "herald",
                "current_topic_id": a.topic, "published_at": now_iso(),
                "human_reviewed": not a.auto, "withdrawn": False,
                "category": t.get("category"), "keywords": t.get("keywords", [])})
    t["slug"] = a.slug
    store.set_topic_state(t, "published", note="PR #%s" % a.pr if a.pr else None)
    store.save_published(root, pub)
    store.save_topics(root, data)
    emit({"published": a.slug, "human_reviewed": not a.auto})


def cmd_signal(a):
    root = repo_root()
    data = json.loads(a.data) if a.data else {}
    emit(store.signal(root, a.kind, a.topic, data,
                      human_reviewed=None if a.human_reviewed is None else a.human_reviewed == "true"))


def cmd_auto_exclusion(a):
    root, cfg = ctx()
    crit = store.read_json_at(root, a.rev, store.work_rel(a.topic, "critique.json")) if a.rev else \
        store.load_machine(root, a.topic, "critique.json")
    emit({"reasons": store.auto_exclusion(crit)})


def build():
    ap = argparse.ArgumentParser(prog="hrd.py")
    sp = ap.add_subparsers(dest="group", required=True)

    p = sp.add_parser("lock"); p.add_argument("action", choices=["acquire", "release", "status", "unlock"])
    p.add_argument("--cmd", default="cli"); p.add_argument("--token"); p.set_defaults(fn=cmd_lock)

    p = sp.add_parser("topics"); p.add_argument("action", choices=["add", "list", "show"])
    p.add_argument("--file"); p.add_argument("--state"); p.add_argument("--topic"); p.set_defaults(fn=cmd_topics)

    p = sp.add_parser("select"); p.add_argument("--n", type=int, default=0); p.add_argument("--topic")
    p.set_defaults(fn=cmd_select)
    p = sp.add_parser("status"); p.set_defaults(fn=cmd_status)

    p = sp.add_parser("begin"); p.add_argument("--topic", required=True); p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_begin)
    p = sp.add_parser("branch"); p.add_argument("--topic", required=True); p.add_argument("--slug", required=True)
    p.set_defaults(fn=cmd_branch)
    p = sp.add_parser("stage"); p.add_argument("action", choices=["check", "pass"])
    p.add_argument("--topic", required=True); p.add_argument("--stage", required=True)
    p.add_argument("--amend", action="store_true"); p.set_defaults(fn=cmd_stage)
    p = sp.add_parser("loopback"); p.add_argument("--topic", required=True)
    p.add_argument("--human", action="store_true", help="human-requested revision: not counted")
    p.set_defaults(fn=cmd_loopback)
    p = sp.add_parser("finalize"); p.add_argument("--topic", required=True); p.set_defaults(fn=cmd_finalize)
    p = sp.add_parser("result"); p.add_argument("--topic", required=True); p.add_argument("--status", required=True)
    p.add_argument("--pr", type=int); p.add_argument("--note"); p.add_argument("--merged", type=int, nargs="*")
    p.set_defaults(fn=cmd_result)

    p = sp.add_parser("hash"); p.add_argument("--slug", required=True); p.add_argument("--rev")
    p.set_defaults(fn=cmd_hash)
    p = sp.add_parser("ledger"); p.add_argument("action", choices=["record", "show"])
    p.add_argument("--topic", required=True); p.add_argument("--sha"); p.add_argument("--rev")
    p.add_argument("--kind", default="verify", choices=["verify", "push", "base-commit", "trust"])
    p.set_defaults(fn=cmd_ledger)
    p = sp.add_parser("scope"); p.add_argument("--topic", required=True); p.add_argument("--slug")
    p.add_argument("--rev", default="HEAD"); p.set_defaults(fn=cmd_scope)
    p = sp.add_parser("ahead"); p.set_defaults(fn=cmd_ahead)
    p = sp.add_parser("sync"); p.set_defaults(fn=cmd_sync)
    p = sp.add_parser("fetch-pr"); p.add_argument("--pr", type=int, required=True); p.set_defaults(fn=cmd_fetch_pr)
    p = sp.add_parser("commit"); p.add_argument("--cmd", required=True); p.add_argument("--kind", required=True)
    p.add_argument("-m", "--message", required=True); p.add_argument("paths", nargs="+"); p.set_defaults(fn=cmd_commit)
    p = sp.add_parser("integrity"); p.add_argument("--predeploy", action="store_true"); p.add_argument("--rev")
    p.set_defaults(fn=cmd_integrity)
    p = sp.add_parser("residue"); p.add_argument("--clean", action="store_true"); p.set_defaults(fn=cmd_residue)
    p = sp.add_parser("herald-set"); p.set_defaults(fn=cmd_herald_set)
    p = sp.add_parser("reverts"); p.add_argument("action", choices=["list", "apply"]); p.set_defaults(fn=cmd_reverts)

    p = sp.add_parser("state"); p.add_argument("--topic", required=True); p.add_argument("--state", required=True)
    p.add_argument("--reason"); p.add_argument("--note"); p.set_defaults(fn=cmd_state)
    p = sp.add_parser("requeue"); p.add_argument("--topic", required=True); p.set_defaults(fn=cmd_requeue)
    p = sp.add_parser("drop"); p.add_argument("--topic", required=True); p.add_argument("--note")
    p.set_defaults(fn=cmd_drop)
    p = sp.add_parser("withdraw"); p.add_argument("slug_or_topic"); p.add_argument("--note")
    p.set_defaults(fn=cmd_withdraw)
    p = sp.add_parser("unwithdraw"); p.add_argument("slug_or_topic"); p.set_defaults(fn=cmd_unwithdraw)
    p = sp.add_parser("move"); p.add_argument("--topic", required=True); p.add_argument("--new-slug", required=True)
    p.set_defaults(fn=cmd_move)
    p = sp.add_parser("release-slug"); p.add_argument("slug"); p.set_defaults(fn=cmd_release_slug)
    p = sp.add_parser("mark-published"); p.add_argument("--topic", required=True); p.add_argument("--slug", required=True)
    p.set_defaults(fn=cmd_mark_published)
    p = sp.add_parser("record-published"); p.add_argument("--topic", required=True); p.add_argument("--slug", required=True)
    p.add_argument("--pr"); p.add_argument("--auto", action="store_true"); p.set_defaults(fn=cmd_record_published)
    p = sp.add_parser("signal"); p.add_argument("--kind", required=True); p.add_argument("--topic")
    p.add_argument("--data"); p.add_argument("--human-reviewed", choices=["true", "false"]); p.set_defaults(fn=cmd_signal)
    p = sp.add_parser("auto-exclusion"); p.add_argument("--topic", required=True); p.add_argument("--rev")
    p.set_defaults(fn=cmd_auto_exclusion)
    return ap


def main(argv=None):
    a = build().parse_args(argv)
    try:
        a.fn(a)
    except HeraldError as e:
        sys.stderr.write("hrd: %s\n" % e)
        sys.exit(1)


if __name__ == "__main__":
    main()
