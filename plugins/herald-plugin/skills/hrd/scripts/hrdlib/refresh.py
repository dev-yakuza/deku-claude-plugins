"""The refresh decision (design/herald/02-refresh-decision.md).

Before `/hrd refresh` queues anything, the content strategist recommends `update` (same URL),
`new` (a new article; the old one stays) or `none`, and a human decides. Code here:

- `precheck`: which decisions are possible at all (and which one is required);
- `check`: the strategist's recommendation file is well formed;
- `decide`: applies the human's decision in one step — the topic, and the decision record in
  `published.json` (`last_refresh_decision`) — or writes nothing;
- `signal`: after the decision was committed, records `refresh-override` when the human
  really overturned the recommendation;
- the `superseded` link between an old article and the new one that follows it.
"""

import datetime
import json
import os
import re

from .util import HeraldError, now_iso, read_json

DECISIONS = ("update", "new", "none")


def rec_rel(slug):
    return os.path.join(".claude", "herald", "memory", "refresh", "%s.json" % slug)


def direction_rel(tid):
    return os.path.join(".claude", "herald", "memory", "directions", "%s.diff" % tid)


# --- precheck (R12) -------------------------------------------------------------------------

def _source_time(art):
    return str(art.get("source_published_at") or art.get("published_at") or "")


def _source_defect_notes(topics, art):
    """Notes of source-defect holds on this article's tr- topics since the source was last
    published — the article itself failed verify: a refresh is the only way out."""
    since = _source_time(art)
    out = []
    for t in topics:
        if t.get("translate_of") != art["slug"]:
            continue
        for h in t.get("history") or []:
            if h.get("reason") == "source-defect" and str(h.get("at", "")) > since:
                out.append(h.get("note") or "source defect (%s)" % t["id"])
    return out


def precheck(root, cfg, slug, for_translation=False, clear=True):
    """The decisions a human may choose for refreshing `slug`, and why some are not offered."""
    from . import ghstate
    from .store import SLUG_RE, find_article, load_published, load_topics

    pub = load_published(root)
    art = find_article(pub, slug)
    if not art:
        moved = find_old(pub, slug)
        if moved:
            raise HeraldError("%s moved to %s — refresh %s" % (slug, moved["slug"], moved["slug"]))
    if not art or art.get("withdrawn"):
        raise HeraldError("%s is not a published article (published.json)" % slug)
    topics = load_topics(root)["topics"]
    choices = list(DECISIONS)
    blocked = []
    if not SLUG_RE.match(slug):
        choices.remove("update")
        blocked.append("update: %s is outside Herald's slug format — the same URL cannot be refreshed" % slug)
    in_flight = ghstate.in_progress_topics(root, cfg)
    busy_ids = {t["id"] for t in in_flight}
    same = [t["id"] for t in in_flight if t["slug"] == slug or
            next((x for x in topics if x["id"] == t["id"]), {}).get("refresh_of") == slug]
    if same and "update" in choices:
        choices.remove("update")
        blocked.append("update: %s is already in progress on this article — finish or close it first" % ", ".join(same))
    names = {slug} | {m.get("slug") for m in art.get("moved_from") or [] if m.get("slug")}
    follows = [t["id"] for t in topics if t.get("follows") in names and t["id"] in busy_ids]
    if follows:
        choices.remove("new")
        blocked.append("new: %s already follows this article" % ", ".join(follows))
    notes = _source_defect_notes(topics, art)
    required = None
    if notes:
        required = "source-defect"
    elif for_translation:
        required = "for-translation"
    if required:
        choices = [c for c in choices if c == "update"]
    if clear:
        try:
            os.remove(os.path.join(root, rec_rel(slug)))
        except OSError:
            pass
    first = art.get("first_published_at") or min(
        (h.get("at") for t in topics if (t.get("slug") or t.get("refresh_of")) == slug
         for h in t.get("history") or [] if h.get("state") == "published" and h.get("at")), default=None)
    return {"slug": slug, "choices": choices, "required": required, "blocked": blocked,
            "source_defects": notes, "origin": art.get("origin"),
            "evidence": {"source_published_at": _source_time(art) or None, "first_published_at": first},
            "last_refresh_decision": art.get("last_refresh_decision"),
            "superseded": art.get("superseded")}


# --- the recommendation (§2) ------------------------------------------------------------------

def check(root, cfg, slug, choices):
    """Problems of the strategist's recommendation file (empty list = usable)."""
    rec = read_json(os.path.join(root, rec_rel(slug)))
    if not isinstance(rec, dict):
        return None, ["%s is missing or not JSON — run the strategist's refresh recommendation" % rec_rel(slug)]
    problems = []
    for k in ("stale", "reasons"):  # a model may write one string where a list belongs
        if isinstance(rec.get(k), str):
            rec[k] = [rec[k]]
        elif rec.get(k) is not None and not (isinstance(rec[k], list) and all(isinstance(x, str) for x in rec[k])):
            problems.append("%s must be a list of strings" % k)
    r = rec.get("recommendation")
    if r not in DECISIONS:
        problems.append("recommendation must be one of %s" % ", ".join(DECISIONS))
    if r == "update" and not [x for x in rec.get("stale") or [] if str(x).strip()]:
        problems.append("an update recommendation names what is stale (`stale`, quoting the article)")
    if r == "new":
        nt = rec.get("new_topic") if isinstance(rec.get("new_topic"), dict) else {}
        if not nt.get("title") or not nt.get("angle"):
            problems.append("a new recommendation needs new_topic with title and angle (what differs from the old article)")
    if r == "none" and not [x for x in rec.get("reasons") or [] if str(x).strip()]:
        problems.append("a none recommendation gives reasons")
    if r in DECISIONS and r not in choices:
        problems.append("recommendation %s is not among the possible decisions (%s) — recommend within them"
                        % (r, ", ".join(choices) or "none"))
    return rec, problems


# --- the decision (§2) ------------------------------------------------------------------------

def _next_refresh_id(topics, slug):
    base = "r-%s-%s" % (slug, datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d"))
    ids = {t["id"] for t in topics}
    if base not in ids:
        return base
    n = 2
    while "%s-%d" % (base, n) in ids:
        n += 1
    return "%s-%d" % (base, n)


def decide(root, cfg, slug, decision, source="recommended", direction=None, for_translation=False,
           override_reason=None, topic=None):
    """Apply a human's decision in one step. Returns {"decision", "topic_id", "files"}."""
    from . import store

    if decision not in DECISIONS:
        raise HeraldError("decision must be one of %s" % ", ".join(DECISIONS))
    if source not in ("recommended", "forced", "direction"):
        raise HeraldError("source must be recommended, forced or direction")
    if source != "recommended" and decision != "update":
        raise HeraldError("--source %s is an update" % source)
    pc = precheck(root, cfg, slug, for_translation=for_translation, clear=False)
    if decision not in pc["choices"]:
        raise HeraldError("%s is not possible for %s now: %s" % (decision, slug, "; ".join(pc["blocked"]) or
                                                                  "required: %s" % pc["required"]))
    rec = None
    if source == "recommended":
        rec, problems = check(root, cfg, slug, pc["choices"])
        if rec is None or [p for p in problems if "not among" not in p]:
            # the strategist's file is unusable: the human still decides, and the record says
            # there was no recommendation (so no override signal either)
            rec = None
    dir_path = None
    if source == "direction":
        if not direction:
            raise HeraldError("--source direction needs --direction <id>")
        dir_path = direction_rel(direction)
        if not os.path.isfile(os.path.join(root, dir_path)):
            raise HeraldError("no saved direction %s" % dir_path)
    if decision != "none":
        if not isinstance(topic, dict) or not topic.get("title"):
            raise HeraldError("--topic-file must hold the topic entry (title, category, keywords, angle)")
        if isinstance(topic.get("keywords"), str):
            topic["keywords"] = [topic["keywords"]]
    data = store.load_topics(root)
    pub = store.load_published(root)
    art = store.find_article(pub, slug)
    now = now_iso()
    stale = [str(x) for x in (rec or {}).get("stale") or []] + list(pc["source_defects"])
    tid = None
    if decision in ("update", "new"):
        t = {"title": topic["title"], "category": topic.get("category"), "keywords": topic.get("keywords") or [],
             "angle": topic.get("angle", ""), "state": "queued", "reason": None, "reverted_by": [], "history": []}
        if decision == "update":
            tid = _next_refresh_id(data["topics"], slug)
            t.update({"refresh_of": slug, "slug": slug,
                      "refresh_decision": {"recommendation": (rec or {}).get("recommendation"), "decision": "update",
                                           "source": source, "stale": stale}})
            if dir_path:
                t["direction"] = dir_path
        else:
            tid = store.next_topic_id(data)
            t.update({"refresh_of": None, "slug": None, "follows": slug})
        store.check_topic_id(tid)
        t["id"] = tid
        store.set_topic_state(t, "queued", note="refresh decision: %s" % decision)
        data["topics"].append(t)
    art["last_refresh_decision"] = {
        "at": now, "source": source, "choices": pc["choices"],
        "recommendation": (rec or {}).get("recommendation"), "decision": decision,
        "reasons": [str(x) for x in (rec or {}).get("reasons") or []],
        "policy_rule": (rec or {}).get("policy_rule"), "override_reason": override_reason}
    if pc["required"]:
        art["last_refresh_decision"]["required"] = pc["required"]
    paths_ = store.paths(root)
    before = open(paths_["topics"], "rb").read() if os.path.exists(paths_["topics"]) else None
    store.save_topics(root, data)
    try:
        store.save_published(root, pub)
    except Exception:
        if before is None:
            os.remove(paths_["topics"])
        else:
            with open(paths_["topics"], "wb") as f:
                f.write(before)
        raise
    return {"decision": decision, "topic_id": tid,
            "files": [".claude/herald/topics.json", ".claude/herald/published.json"]}


def signal(root, cfg, slug):
    """`refresh-override` after the decision was committed — only a real overturn (R7)."""
    from . import store

    pub = store.read_json_at(root, "HEAD", ".claude/herald/published.json") or {"articles": []}
    art = store.find_article(pub, slug) or {}
    d = art.get("last_refresh_decision") or {}
    real = (d.get("source") == "recommended" and d.get("recommendation") in (d.get("choices") or [])
            and d.get("decision") != d.get("recommendation"))
    if not real:
        return {"recorded": False}
    tid = "slug:%s" % slug
    for r in store.read_jsonl(store.paths(root)["signals"]):
        if isinstance(r, dict) and r.get("kind") == "refresh-override" and r.get("topic_id") == tid \
                and (r.get("data") or {}).get("at") == d.get("at"):
            return {"recorded": False, "duplicate": True}
    store.safe_signal(root, "refresh-override", tid, {
        "at": d.get("at"), "recommendation": d.get("recommendation"), "decision": d.get("decision"),
        "policy_rule": d.get("policy_rule"), "reason": d.get("override_reason")})
    return {"recorded": True}


# --- old article → new article (R9) ---------------------------------------------------------

def find_old(pub, slug):
    """The article a `follows` slug names now — following `moved_from` aliases."""
    from .store import find_article
    art = find_article(pub, slug)
    if art:
        return art
    for a in pub["articles"]:
        if any(m.get("slug") == slug for m in a.get("moved_from") or []):
            return a
    return None


def link_superseded(pub, follows, new_slug, warn=None):
    old = find_old(pub, follows)
    if not old or old.get("withdrawn"):
        if warn:
            warn("the article %s follows (%s) is gone or withdrawn — no `superseded` link recorded" % (new_slug, follows))
        return None
    old["superseded"] = {"by": new_slug, "at": now_iso()}
    return old


def supersede_pending(root, cfg, pub):
    """Old articles whose new article is published but whose body has no link to it yet."""
    from .store import SLUG_RE, find_article

    out = []
    for old in pub["articles"]:
        sup = old.get("superseded") or {}
        if not sup.get("by") or old.get("withdrawn"):
            continue
        new = find_article(pub, sup["by"])
        if not new or new.get("withdrawn"):
            continue
        last = old.get("last_refresh_decision") or {}
        if last.get("decision") == "none" and str(last.get("at", "")) > str(sup.get("at", "")):
            continue  # a human saw the new article and chose not to link it
        url = cfg.article_url(sup["by"])
        path = re.sub(r"^[a-z]+://[^/]+", "", url)
        try:
            with open(os.path.join(root, cfg.body_path(old["slug"])), encoding="utf-8") as f:
                body = f.read()
        except OSError:
            continue
        if path and re.search(re.escape(path.rstrip("/")) + r"(?=/?[)\"'#?\s>]|/?$)", body, re.M):
            continue
        out.append({"old": old["slug"], "new": sup["by"], "refreshable": bool(SLUG_RE.match(old["slug"]))})
    return out


def load_topic_file(path):
    if not path:
        return None
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        data = data[0] if data else None
    return data
