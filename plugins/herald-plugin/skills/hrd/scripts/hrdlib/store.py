"""State files (plan §3.2, §3.2.1, §3.5).

- topics.json     base branch only — topic queue and stored states
- published.json  base branch only — publish cache (origin, current_topic_id, aliases, releases)
- work/<id>/      PR branch only — stage artifacts + state.json (hashes)
- ledger/verified.jsonl   local, append-only — the verification ledger (anti-forgery baseline)
- signals.jsonl           local — growth signals
"""

import os
import re

from .hashing import file_hash, tree_hash, worktree_hash
from .util import HeraldError, append_jsonl, herald_dir, now_iso, read_json, read_jsonl, write_json

TOPIC_ID_RE = re.compile(r"^(t\d{4,}|r-[a-z0-9][a-z0-9-]*-\d{8})$")
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

STORED_STATES = ("queued", "held", "declined", "published", "withdrawn", "unwithdrawn")
HOLD_REASONS = (
    "cannibalization", "research", "rejected",          # before PR — cleaned up
    "needs-human", "stagnation", "budget",               # before PR — preserved (WIP branch)
    "verify-after-human-edit",                           # after PR — PR kept open
    "reverted",                                          # after merge — removal revert
)
CLEANUP_REASONS = ("cannibalization", "research", "rejected")
PRESERVE_REASONS = ("needs-human", "stagnation", "budget")


def paths(root):
    h = herald_dir(root)
    return {
        "dir": h,
        "config": os.path.join(h, "config.json"),
        "topics": os.path.join(h, "topics.json"),
        "published": os.path.join(h, "published.json"),
        "work": os.path.join(h, "work"),
        "ledger": os.path.join(h, "ledger", "verified.jsonl"),
        "signals": os.path.join(h, "signals.jsonl"),
        "memory": os.path.join(h, "memory"),
    }


def work_rel(topic_id, name=""):
    return os.path.join(".claude", "herald", "work", topic_id, name) if name else os.path.join(".claude", "herald", "work", topic_id)


def check_topic_id(tid):
    if not TOPIC_ID_RE.match(tid or ""):
        raise HeraldError("invalid topic id %r (expected t0001 or r-<slug>-YYYYMMDD)" % tid)


def check_slug(slug):
    if not SLUG_RE.match(slug or ""):
        raise HeraldError("invalid slug %r (lowercase letters, digits, single hyphens)" % slug)


def branch_name(topic_id, slug):
    return "herald/%s--%s" % (topic_id, slug)


def parse_branch(name):
    """`herald/<topic-id>--<slug>` -> (topic_id, slug) or None."""
    if not name or not name.startswith("herald/"):
        return None
    rest = name[len("herald/"):]
    tid, sep, slug = rest.partition("--")
    if not sep or not TOPIC_ID_RE.match(tid) or not SLUG_RE.match(slug):
        return None
    return tid, slug


# --- topics.json ---------------------------------------------------------------------------

def load_topics(root):
    return read_json(paths(root)["topics"], {"version": 1, "topics": []})


def save_topics(root, data):
    write_json(paths(root)["topics"], data)


def get_topic(data, tid):
    for t in data["topics"]:
        if t["id"] == tid:
            return t
    raise HeraldError("unknown topic %s" % tid)


def next_topic_id(data):
    nums = [int(t["id"][1:]) for t in data["topics"] if re.match(r"^t\d+$", t["id"])]
    return "t%04d" % ((max(nums) + 1) if nums else 1)


def set_topic_state(topic, state, reason=None, note=None):
    if state not in STORED_STATES:
        raise HeraldError("unknown state %s" % state)
    if state in ("held", "declined") and not reason:
        raise HeraldError("%s needs a reason" % state)
    if state == "held" and reason not in HOLD_REASONS:
        raise HeraldError("unknown hold reason %s" % reason)
    topic["state"] = state
    topic["reason"] = reason
    topic.setdefault("history", []).append(
        {"at": now_iso(), "state": state, "reason": reason, "note": note}
    )
    topic.setdefault("reverted_by", [])


# --- published.json ------------------------------------------------------------------------

def load_published(root):
    return read_json(paths(root)["published"], {"version": 1, "articles": [], "releases": []})


def save_published(root, data):
    data.setdefault("releases", [])
    write_json(paths(root)["published"], data)


def find_article(pub, slug):
    for a in pub["articles"]:
        if a["slug"] == slug:
            return a
    return None


def find_article_by_topic(pub, tid):
    for a in pub["articles"]:
        if a.get("current_topic_id") == tid:
            return a
    return None


# --- work/<id>/state.json ------------------------------------------------------------------

# Which stage produces which artifact. "@article" = body + images (content hash).
PRODUCES = {
    "brief": ["brief.md"],
    "research": ["research.md"],
    "draft": ["@article", "claims-map.json"],
    "critique": ["critique.md", "critique.json"],
    "verify": ["verify.md", "verify.json"],
}
CONSUMES = {
    "brief": [],
    "research": [("brief", "brief.md")],
    "draft": [("brief", "brief.md"), ("research", "research.md")],
    "critique": [("draft", "@article")],
    "verify": [("draft", "@article"), ("draft", "claims-map.json"), ("research", "research.md")],
}
ORDER = ["brief", "research", "draft", "critique", "verify", "publish"]


def state_path(root, tid):
    return os.path.join(root, work_rel(tid, "state.json"))


def load_state(root, tid):
    st = read_json(state_path(root, tid))
    if st is None:
        raise HeraldError("no work state for %s (start with /hrd write %s)" % (tid, tid))
    return st


def new_state(tid, slug):
    return {"topic_id": tid, "slug": slug, "stage": "brief", "stages": {},
            "verified_hash": None, "agent_final_hash": None, "loopbacks": 0,
            "pr": None, "created_at": now_iso()}


def save_state(root, tid, st):
    write_json(state_path(root, tid), st)


def artifact_hash(root, cfg, st, name):
    if name == "@article":
        return worktree_hash(root, cfg, st["slug"])
    return file_hash(root, work_rel(st["topic_id"], name))


def entry_check(root, cfg, st, stage):
    """Plan §3.2 entry condition: every input file still matches the hash its producer recorded."""
    problems = []
    for producer, name in CONSUMES.get(stage, []):
        rec = st["stages"].get(producer, {}).get("outputs", {})
        if name not in rec:
            problems.append("%s has not passed (needed for %s)" % (producer, name))
            continue
        cur = artifact_hash(root, cfg, st, name)
        if cur != rec[name]:
            problems.append("%s changed since %s passed — rerun %s" % (name, producer, producer))
    if stage == "publish":
        cur = worktree_hash(root, cfg, st["slug"])
        c = st["stages"].get("critique", {}).get("body_hash")
        v = st["stages"].get("verify", {}).get("body_hash")
        if not (cur and cur == c == v == st.get("verified_hash")):
            problems.append("article differs from what critique/verify evaluated — rerun critique and verify")
    return problems


def load_machine(root, tid, name):
    return read_json(os.path.join(root, work_rel(tid, name)))


def critique_passed(crit):
    """critique.json final round: editor PASS and no undismissed BLOCKER/MAJOR."""
    fr = (crit or {}).get("final_round") or {}
    audit = fr.get("audit") or {}
    dism = fr.get("dismissed") or {}
    undismissed = (int(audit.get("blocker", 0)) - int(dism.get("blocker", 0))) + \
                  (int(audit.get("major", 0)) - int(dism.get("major", 0)))
    return fr.get("verdict") == "PASS" and undismissed <= 0


def verify_passed(ver):
    c = (ver or {}).get("counts") or {}
    return int(c.get("unsupported", 1)) == 0 and int(c.get("contradicted", 1)) == 0


def auto_exclusion(crit):
    """Reasons a PR may not be auto-published (plan §3.2.2 ③). Empty list = eligible."""
    reasons = []
    for d in (crit or {}).get("decision_log") or []:
        if d.get("kind") in ("dismissal", "assumption"):
            reasons.append("decision:%s" % d.get("kind"))
    fr = (crit or {}).get("final_round") or {}
    audit = fr.get("audit") or {}
    if fr.get("verdict") == "PASS" and int(audit.get("blocker", 0)) + int(audit.get("major", 0)) > 0:
        reasons.append("audit-dismissed")
    return sorted(set(reasons))


def run_gate(root, cfg, slug):
    """draft gate (plan §3.5): config.commands.validate if set, else the built-in validator."""
    import shlex
    from .util import run
    from .validate import validate

    body = cfg.body_path(slug)
    custom = (cfg.get("commands", "validate") or "").strip()
    if custom:
        proc = run(shlex.split(custom) + [body], cwd=root, check=False)
        return {"ok": proc.returncode == 0, "errors": [(proc.stdout + proc.stderr).strip()[-500:]]}
    return validate(root, cfg, body)


def stage_pass(root, cfg, tid, stage, amend=False):
    st = load_state(root, tid)
    if stage not in PRODUCES:
        raise HeraldError("unknown stage %s" % stage)
    if not amend:
        problems = entry_check(root, cfg, st, stage)
        if problems:
            raise HeraldError("; ".join(problems))
    outputs = {}
    for name in PRODUCES[stage]:
        h = artifact_hash(root, cfg, st, name)
        if h is None:
            raise HeraldError("%s missing — %s did not write it" % (name, stage))
        outputs[name] = h
    rec = {"outputs": outputs, "at": now_iso()}
    if stage == "draft" or (stage == "verify" and amend):
        gate = run_gate(root, cfg, st["slug"])
        if not gate["ok"]:
            raise HeraldError("deterministic gate failed: %s" % "; ".join(gate["errors"][:5]))
    if stage in ("critique", "verify"):
        # The verdict file must evaluate THIS article: the main session writes the hash it
        # got from `HRD hash` before spawning into the file, and a verdict file carried over
        # unchanged from an earlier pass cannot vouch for a changed body (plan §3.2).
        cur = worktree_hash(root, cfg, st["slug"])
        name = "critique.json" if stage == "critique" else "verify.json"
        machine = load_machine(root, tid, name) or {}
        claimed = (machine.get("final_round") or {}).get("body_hash") if stage == "critique" else machine.get("body_hash")
        if claimed != cur:
            raise HeraldError("%s does not evaluate the current article (body_hash %s != %s) — run %s again"
                              % (name, (claimed or "missing")[:19], (cur or "none")[:19], stage))
        prev = st["stages"].get(stage) or {}
        if prev.get("body_hash") and prev["body_hash"] != cur and prev.get("outputs", {}).get(name) == outputs[name]:
            raise HeraldError("%s is unchanged since the previous %s pass but the article changed — run %s again"
                              % (name, stage, stage))
    if stage == "critique":
        crit = load_machine(root, tid, "critique.json")
        if not critique_passed(crit):
            raise HeraldError("critique.json does not record a PASS with zero undismissed BLOCKER/MAJOR")
        rec["body_hash"] = worktree_hash(root, cfg, st["slug"])
    if stage == "verify":
        ver = load_machine(root, tid, "verify.json")
        if not verify_passed(ver):
            raise HeraldError("verify.json has unsupported or contradicted claims")
        bh = worktree_hash(root, cfg, st["slug"])
        rec["body_hash"] = bh
        st["verified_hash"] = bh
        if amend:
            # delta research rewrote research.md / claims-map.json: re-anchor their producers
            for producer, name in (("research", "research.md"), ("draft", "claims-map.json")):
                st["stages"].setdefault(producer, {}).setdefault("outputs", {})[name] = artifact_hash(root, cfg, st, name)
    st["stages"][stage] = rec
    nxt = ORDER[ORDER.index(stage) + 1]
    st["stage"] = nxt
    save_state(root, tid, st)
    return st


# --- ledger ---------------------------------------------------------------------------------

def ledger_lines(root):
    return read_jsonl(paths(root)["ledger"], strict_bytes=True)


def ledger_latest(root, tid):
    last = None
    for rec in ledger_lines(root):
        if rec.get("topic_id") == tid:
            last = rec
    return last


def ledger_record(root, cfg, tid, sha=None, kind="verify", rev=None):
    """`integrity.py --record` self-check (plan §3.2): current hash == verify.body_hash ==
    verified_hash and verify.json clean. With `rev`, the article is read from that commit."""
    if kind == "trust" and not rev:
        # trust vouches for the COMMITTED state only (plan §3.2): read HEAD, refuse local edits
        st_head = read_json_at(root, "HEAD", work_rel(tid, "state.json"))
        if st_head != read_json(state_path(root, tid)):
            raise HeraldError("refusing: work/%s/state.json differs from HEAD — trust needs the committed file" % tid)
    if rev:
        st = read_json_at(root, rev, work_rel(tid, "state.json"))
        ver = read_json_at(root, rev, work_rel(tid, "verify.json"))
    else:
        st = load_state(root, tid)
        ver = load_machine(root, tid, "verify.json")
    if not st:
        raise HeraldError("no state.json for %s" % tid)
    cur = tree_hash(root, cfg, rev, st["slug"]) if rev else worktree_hash(root, cfg, st["slug"])
    vb = st.get("stages", {}).get("verify", {}).get("body_hash")
    if kind == "trust":
        # Only for "no ledger line on this machine", attended, and only for the exact body the
        # committed state.json says was verified (plan §3.2 "원장 기록이 없을 때").
        if os.environ.get("HRD_UNATTENDED") == "1":
            raise HeraldError("refusing: trust records need a human (attended ship only)")
        if ledger_latest(root, tid) is not None:
            raise HeraldError("refusing: %s already has a ledger line — re-verify instead of trusting" % tid)
        if not (cur and cur == st.get("verified_hash")):
            raise HeraldError("refusing: the article differs from the committed verified_hash — re-verify instead")
    else:
        if not (cur and cur == vb == st.get("verified_hash")):
            raise HeraldError("refusing to record: article hash does not match the last verify pass")
        if not verify_passed(ver):
            raise HeraldError("refusing to record: verify.json is not clean")
    rec = {"at": now_iso(), "topic_id": tid, "slug": st["slug"], "verified_hash": cur,
           "sha": sha, "kind": kind}
    append_jsonl(paths(root)["ledger"], rec)
    return rec


def read_json_at(root, rev, relpath):
    import json
    from .util import run

    proc = run(["git", "show", "%s:%s" % (rev, relpath)], cwd=root, check=False)
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout)
    except ValueError:
        return None


# --- publish record (ship step 9 and the batch runner share it) -----------------------------

def record_published(root, cfg, tid, slug, pr=None, auto=False, origin="herald"):
    pub = load_published(root)
    data = load_topics(root)
    t = get_topic(data, tid)
    art = find_article(pub, slug)
    if not art:
        art = {"slug": slug, "moved_from": []}
        pub["articles"].append(art)
    art.update({"path": cfg.body_path(slug), "url": cfg.article_url(slug), "origin": origin,
                "current_topic_id": tid, "published_at": now_iso(), "withdrawn": False,
                "category": t.get("category"), "keywords": t.get("keywords", [])})
    if t.get("auto_merged_pr") and (pr is None or str(pr) == str(t["auto_merged_pr"])):
        auto = True  # merged unattended: stays false whoever records it later
    if origin == "herald":
        art["human_reviewed"] = not auto
    t["slug"] = slug
    set_topic_state(t, "published", note=("auto " if auto else "") + ("PR #%s" % pr if pr else origin))
    save_published(root, pub)
    save_topics(root, data)
    return art


# --- signals --------------------------------------------------------------------------------

SIGNAL_KINDS = (
    "human-edit", "ship-decline", "review-finding", "audit-finding", "dismissal",
    "revise-weakness", "verify-gap", "hold", "gate-failure", "stagnation", "escalation",
    "session-edit-request",
)


def signal(root, kind, tid=None, data=None, human_reviewed=None):
    if kind not in SIGNAL_KINDS:
        raise HeraldError("unknown signal kind %s" % kind)
    import uuid
    # the nonce makes every record (and so its id) unique, even two identical events in one second
    rec = {"at": now_iso(), "kind": kind, "topic_id": tid, "data": data or {}, "nonce": uuid.uuid4().hex[:12]}
    if human_reviewed is not None:
        rec["human_reviewed"] = bool(human_reviewed)
    append_jsonl(paths(root)["signals"], rec)
    return dict(rec, id=signal_id(rec))


# --- evolve readiness (shared by evolve Phase 1, the ship/status nudge and monitoring) ----------
#
# Signals are local (gitignored), so is evolve's bookkeeping: `memory/evolve-state.json` keeps
# the ids of signals a decided proposal consumed (applied or rejected by the human) and the ids
# every evolve scan on this machine saw (so "new" never depends on clocks). Signals behind
# "watching" themes or panel-dropped proposals stay unconsumed and keep accumulating.

MIN_SIGNALS, MIN_TOPICS = 3, 2  # a theme needs >= 3 independent signals from >= 2 topics
BASELINE_MAX_LINES = 2  # a reviewed human edit this small is "almost no edits" (exemplar evidence)


def _evolve_state_path(root):
    return os.path.join(paths(root)["memory"], "evolve-state.json")


def load_evolve_state(root):
    try:
        st = read_json(_evolve_state_path(root), None)
    except ValueError:
        raise HeraldError("%s is not valid JSON — fix or restore it (deleting it makes consumed signals count again)"
                          % _evolve_state_path(root))
    if not isinstance(st, dict):
        st = {}
    st.setdefault("last_scan", None)
    for k in ("consumed", "seen"):
        st[k] = [c for c in st.get(k) or [] if isinstance(c, str)]
    return st


def signal_id(rec):
    import hashlib
    import json as _json
    text = _json.dumps(rec, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(text.encode("utf-8", "surrogatepass")).hexdigest()[:16]


def _well_formed(rec):
    if not isinstance(rec, dict) or rec.get("kind") not in SIGNAL_KINDS:
        return False
    if rec.get("data") is not None and not isinstance(rec.get("data"), dict):
        return False
    tid = rec.get("topic_id")
    return tid is None or isinstance(tid, str)


def _count(v):
    """A count field as written by a model: a finite, non-negative int, float or numeric string;
    None if unreadable (missing, bool, negative, NaN, infinite, huge)."""
    import math
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError, OverflowError):
        return None
    return f if math.isfinite(f) and f >= 0 else None


def baseline_signal(rec):
    """Well-formed records that are evidence but not problems: reviewed human edits of at most
    BASELINE_MAX_LINES lines (exemplar candidates, edit-rate denominators) and review runs that
    found nothing (the "healthy flow finds nothing" measure). Listed for evolve, never counted.
    An unreadable count is never baseline (it is counted, so a problem is not hidden)."""
    if not _well_formed(rec):
        return False
    data = rec.get("data") or {}
    if rec["kind"] == "human-edit":
        n = _count(data.get("lines_changed"))
        return rec.get("human_reviewed") is True and n is not None and n <= BASELINE_MAX_LINES
    if rec["kind"] == "review-finding":
        counts = [_count(data.get(k)) for k in ("blocker", "major", "minor")]  # all three required
        return all(c == 0 for c in counts) and not data.get("findings")
    return False


def countable_signal(rec):
    """Signals evolve may count. Not counted (plan §3.6 — no back-patting): malformed records,
    human-edit records not marked human_reviewed: true, and baseline records (above)."""
    if not _well_formed(rec) or baseline_signal(rec):
        return False
    if rec["kind"] == "human-edit" and rec.get("human_reviewed") is not True:
        return False
    if rec["kind"] == "session-edit-request":
        data = rec.get("data") or {}
        if "request_id" in data:
            return isinstance(data["request_id"], str)  # joined (or dropped as an orphan) in evolve_signals
        return isinstance(data.get("request"), str)
    return True


def _dedup_key(rec):
    """Identical records count once. A session edit request is one event: its diff record names
    the request record by `request_id` (the `id` `HRD signal` returned), so the pair is joined
    deterministically and two separate requests — even with the same wording — stay two."""
    import json as _json
    data = rec.get("data") or {}
    if rec["kind"] == "session-edit-request":
        rid = data.get("request_id") if isinstance(data.get("request_id"), str) else signal_id(rec)
        return (rec["kind"], rec.get("topic_id"), "request", rid)
    return (rec["kind"], rec.get("topic_id"), _json.dumps(data, sort_keys=True, ensure_ascii=False))


def evolve_signals(root):
    """(unconsumed countable signals, baseline records, state). Consumed ids are dropped before
    grouping, so a recurrence after an applied fix starts a new group. A group's listed `data`
    merges its records in order (a session edit request's diff joins its request)."""
    st = load_evolve_state(root)
    consumed = set(st["consumed"])
    groups, baseline = {}, []
    records = read_jsonl(paths(root)["signals"])
    request_ids, asked = set(), set()
    for rec in records:
        if countable_signal(rec) and rec["kind"] == "session-edit-request":
            d = rec.get("data") or {}
            if "request_id" not in d:
                request_ids.add(signal_id(rec))
    for rec in records:
        if baseline_signal(rec):
            baseline.append(dict(rec, id=signal_id(rec)))
            continue
        if not countable_signal(rec):
            continue
        sid = signal_id(rec)
        if rec["kind"] == "session-edit-request":
            d = rec.get("data") or {}
            if "request_id" in d and d["request_id"] not in request_ids:
                continue  # a diff naming no request record: never a signal of its own
            if "request_id" not in d:
                said = (rec.get("topic_id"), d.get("request"))
                if said in asked and ("diff_summary" in d or "lines_changed" in d):
                    continue  # plugin 0.2.0 wrote the diff as a second record repeating the request
                asked.add(said)
        if sid in consumed:
            continue
        key = _dedup_key(rec)
        if key[0] == "session-edit-request" and key[3] in consumed:
            continue  # the diff of a request a decided proposal already used
        g = groups.setdefault(key, {"ids": [], "rec": dict(rec), "data": {}})
        g["ids"].append(sid)
        g["data"].update(rec.get("data") or {})
    out = []
    for g in groups.values():
        r = g["rec"]
        r["data"] = g["data"]
        r["id"] = g["ids"][0]
        r["ids"] = g["ids"]
        out.append(r)
    return out, baseline, st


def evolve_readiness(root, cfg=None, listing=False):
    """Deterministic, advisory count per kind over unconsumed signals. `tier` (machine token):
    sufficient — some kind has >= 3 signals from >= 2 topics AND at least one of them was not
    seen by this machine's last evolve scan (a run that found nothing is not re-nudged until
    new evidence comes); watching — signals exist but that is not met; none — no signals."""
    sigs, baseline, st = evolve_signals(root)
    seen = set(st["seen"])
    kinds = {}
    for r in sigs:
        k = kinds.setdefault(r["kind"], {"count": 0, "topics": set(), "new": 0})
        k["count"] += 1
        if r.get("topic_id"):
            k["topics"].add(r["topic_id"])
        if not seen.intersection(r["ids"]):
            k["new"] += 1
    ready = sorted(n for n, k in kinds.items() if k["count"] >= MIN_SIGNALS and len(k["topics"]) >= MIN_TOPICS)
    fresh = [n for n in ready if kinds[n]["new"] > 0]
    total = sum(k["count"] for k in kinds.values())
    topics = set().union(*[k["topics"] for k in kinds.values()]) if kinds else set()
    out = {
        "tier": "sufficient" if fresh else ("watching" if total else "none"),
        "last_scan": st["last_scan"],
        "signals": total,
        "topics": len(topics),
        "ready_kinds": ready,
        "new_ready_kinds": fresh,
        "kinds": {n: {"count": k["count"], "topics": len(k["topics"]), "new": k["new"]}
                  for n, k in sorted(kinds.items())},
        "threshold": {"signals": MIN_SIGNALS, "topics": MIN_TOPICS},
    }
    if listing:
        out["list"] = sigs
        out["baseline"] = baseline
    return out


def _snapshot_path(root):
    return os.path.join(paths(root)["memory"], "evolve-scan.json")


def evolve_snapshot(root, sigs, token=None):
    """Phase 1 keeps the ids it listed, tagged with the run's lock token; the scan stamp at the
    end of that completed run marks exactly those as seen (not signals that arrived while the
    run waited for approvals). A snapshot from another (aborted) run is never used."""
    write_json(_snapshot_path(root), {"at": now_iso(), "token": token,
                                      "ids": sorted({i for r in sigs for i in r["ids"]})})


def evolve_mark(root, scan=False, consume=(), token=None):
    """evolve's local bookkeeping: `scan` records which signals the run saw (the Phase 1
    snapshot if present, else the current list); `consume` marks signal ids (from
    `evolve-readiness --list`) as used by a decided proposal. Known ids are consumed with their
    whole group; unknown ones are reported, not fatal. Both prune ids whose records are gone."""
    st = load_evolve_state(root)
    sigs, _, _ = evolve_signals(root)
    present = {signal_id(r) for r in read_jsonl(paths(root)["signals"]) if isinstance(r, dict)}
    unknown, baseline_cited, already = [], [], []
    if consume:
        known = {}
        for r in sigs:
            for i in r["ids"]:
                known[i] = r["ids"]
        base_ids = {signal_id(r) for r in read_jsonl(paths(root)["signals"]) if baseline_signal(r)}
        add = []
        for i in consume:
            if i in known:
                add.extend(known[i])
            elif i in base_ids:
                baseline_cited.append(i)  # baseline evidence is cited, never consumed
            elif i in st["consumed"] or i in add:
                already.append(i)
            else:
                unknown.append(i)
        st["consumed"] = sorted(set(st["consumed"]) | set(add))
    if scan:
        try:
            snap = read_json(_snapshot_path(root), None)
        except ValueError:
            snap = None
        if token and isinstance(snap, dict) and snap.get("token") == token and isinstance(snap.get("ids"), list):
            ids = {i for i in snap["ids"] if isinstance(i, str)}
        else:
            ids = {i for r in sigs for i in r["ids"]}
        st["last_scan"] = now_iso()
        st["seen"] = sorted(set(st["seen"]) | ids)
        if os.path.exists(_snapshot_path(root)):
            os.remove(_snapshot_path(root))
    st["consumed"] = sorted(set(st["consumed"]) & present)
    st["seen"] = sorted((set(st["seen"]) & present) - set(st["consumed"]))
    write_json(_evolve_state_path(root), st)
    return {"last_scan": st["last_scan"], "consumed": len(st["consumed"]), "unknown": unknown,
            "baseline_cited": baseline_cited, "already_consumed": already}
