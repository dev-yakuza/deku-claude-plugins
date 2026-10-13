"""State files (plan §3.2, §3.2.1, §3.5).

- topics.json     base branch only — topic queue and stored states
- published.json  base branch only — publish cache (origin, current_topic_id, aliases, releases)
- work/<id>/      PR branch only — stage artifacts + state.json (hashes)
- ledger/verified.jsonl   local, append-only — the verification ledger (anti-forgery baseline)
- signals.jsonl           local — growth signals
"""

import json
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
    if (st.get("trim") or {}).get("status") == "open":
        problems.append("a trim is open — `HRD trim --topic %s --abort` first" % st.get("topic_id"))
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


AUDIT_ROUND_CAP = 3  # external-auditor rounds per article, human-requested revisions included


def audit_round(root, cfg, tid):
    """Count one external-auditor round before it is spawned (contract §F). Round 1 audits in
    full; later rounds only recheck (a BLOCKER, a regression or an unfixed earlier finding
    blocks; any other new MAJOR is deferred to the PR); past the cap the auditor is not run
    again. Asking again for the same article (an interrupted or discarded round, a re-invoked
    RESULT) returns the same round instead of counting a new one."""
    st = load_state(root, tid)
    if reader_blockers(root, cfg, tid, st):
        raise HeraldError(_reader_pass_refusal(st, "before any auditor round"))
    cur = worktree_hash(root, cfg, st["slug"]) if st.get("slug") else None
    n = _int(st.get("audit_rounds"))
    repeat = n >= 1 and cur is not None and st.get("audit_round_body") == cur
    if not repeat:
        n += 1
        st["audit_rounds"] = n
        st["audit_round_body"] = cur
        save_state(root, tid, st)
    mode = "full" if n == 1 else ("recheck" if n <= AUDIT_ROUND_CAP else "skip")
    return {"round": n, "mode": mode, "last": n == AUDIT_ROUND_CAP, "cap": AUDIT_ROUND_CAP, "repeat": repeat}


def _int(v):
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def critique_passed(crit):
    """critique.json final round: editor PASS and no BLOCKER/MAJOR left open. A MAJOR is closed
    by a dismissal, or — on a recheck round (audit_round 2+) — by deferring it to the PR."""
    fr = (crit or {}).get("final_round") or {}
    audit = fr.get("audit") or {}
    dism = fr.get("dismissed") or {}
    deferred = fr.get("deferred") or {}
    rnd = fr.get("audit_round")
    recheck = isinstance(rnd, int) and not isinstance(rnd, bool) and rnd >= 2
    blocker = _int(audit.get("blocker")) - _int(dism.get("blocker"))
    major = _int(audit.get("major")) - _int(dism.get("major")) - (_int(deferred.get("major")) if recheck else 0)
    return fr.get("verdict") == "PASS" and blocker <= 0 and major <= 0


def verify_passed(ver):
    c = (ver or {}).get("counts") or {}
    return int(c.get("unsupported", 1)) == 0 and int(c.get("contradicted", 1)) == 0


def auto_exclusion(crit, st=None):
    """Reasons a PR may not be auto-published (plan §3.2.2 ③). Empty list = eligible."""
    reasons = []
    tr = (st or {}).get("trim") or {}
    if tr.get("status") == "done" and tr.get("hash") != tr.get("base_hash"):
        reasons.append("trimmed")  # the agents changed the body after critique
    for d in (crit or {}).get("decision_log") or []:
        if isinstance(d, dict) and d.get("kind") in ("dismissal", "assumption", "deferral"):
            reasons.append("decision:%s" % d.get("kind"))
    fr = (crit or {}).get("final_round") or {}
    audit = fr.get("audit") or {}
    if fr.get("verdict") == "PASS" and _int(audit.get("blocker")) + _int(audit.get("major")) > 0:
        reasons.append("audit-dismissed")
    human = {str(d.get("id")) for d in (crit or {}).get("decision_log") or []
             if isinstance(d, dict) and d.get("kind") == "human"}
    by_human = sum(1 for e in audit_entries(crit) if _sev(e) == "BLOCKER" and e.get("outcome") == "dismissed"
                   and str(e.get("id")) in human and e.get("round") == fr.get("audit_round"))
    if _int((fr.get("dismissed") or {}).get("blocker")) > by_human or any(
            _sev(e) == "BLOCKER" and e.get("outcome") == "dismissed" and str(e.get("id")) not in human
            for e in audit_entries(crit)):
        reasons.append("audit-dismissed:blocker")  # only a human closes a BLOCKER; never accepted unread
    if _int(fr.get("audit_round")) > AUDIT_ROUND_CAP:
        reasons.append("audit-skipped")  # the article changed after the last auditor round
    for e in audit_entries(crit):  # whatever the decision log says, a deferred finding stays visible
        if _sev(e) == "BLOCKER" and e.get("outcome") == "deferred":
            reasons.append("audit-log:deferred-blocker")  # a BLOCKER is never deferred; never accepted unread
        elif _sev(e) in ("BLOCKER", "MAJOR") and e.get("outcome") in ("deferred", "open"):
            reasons.append("audit-log:%s" % e.get("outcome"))
    return sorted(set(reasons))


# Exclusions a human may accept for one article by asking for it to be published unread
# (`/hrd next`, `write --ship`): each is a decision the agents made and logged in the PR. The
# others stay blocking: an open BLOCKER, an article changed after its last auditor round, a
# PR whose verdict files cannot be read.
CONSENT_ACCEPTS = ("decision:dismissal", "decision:assumption", "decision:deferral",
                   "audit-dismissed", "audit-log:deferred", "trimmed", "images", "framed")


def blocking_exclusions(reasons, consent=False):
    return [r for r in reasons if not (consent and r in CONSENT_ACCEPTS)]


def _git_blob(root, rev, relpath):
    """The git blob id of a file at `rev`, or of the working-tree file as git would store it."""
    import subprocess

    args = ["git", "rev-parse", "-q", "--verify", "%s:%s" % (rev, relpath)] if rev else \
        ["git", "hash-object", "--", relpath]
    if not rev and not os.path.isfile(os.path.join(root, relpath)):
        return None
    proc = subprocess.run(args, cwd=root, capture_output=True, text=True)
    return proc.stdout.strip() or None if proc.returncode == 0 else None


def _blob_hash(root, rev, relpath):
    import hashlib
    import subprocess

    proc = subprocess.run(["git", "show", "%s:%s" % (rev, relpath)], cwd=root, capture_output=True)
    return "sha256:" + hashlib.sha256(proc.stdout).hexdigest() if proc.returncode == 0 else None


def exclusion_reasons(root, cfg, tid, rev=None):
    """auto_exclusion for one topic, read from a PR head (`rev`; on base the work files are not
    there) or the working tree, plus what only the repo shows: a critique.json changed after
    critique passed, and images the PR adds or changes (they go out unseen). A PR whose verdict
    files cannot be read is never eligible."""
    from . import commits

    rel = work_rel(tid, "critique.json")
    if rev:
        crit, st, ch = read_json_at(root, rev, rel), read_json_at(root, rev, work_rel(tid, "state.json")), \
            _blob_hash(root, rev, rel)
    else:
        crit, st, ch = load_machine(root, tid, "critique.json"), read_json(state_path(root, tid)), file_hash(root, rel)
    if not isinstance(crit, dict) or not isinstance(st, dict):
        return ["missing-critique-or-state"]
    reasons = auto_exclusion(crit, st)
    vrel = work_rel(tid, "verify.json")
    try:
        ver = read_json_at(root, rev, vrel) if rev else load_machine(root, tid, "verify.json")
    except Exception:  # noqa: BLE001
        ver = None
    vst = (st.get("stages") or {}).get("verify") or {}
    if not isinstance(ver, dict):
        reasons.append("missing-verify")
    else:
        if ver.get("framings"):
            reasons.append("framed")  # the fact-checker exempted sentences as the article's own example
        vblob = (vst.get("blobs") or {}).get("verify.json") if isinstance(vst.get("blobs"), dict) else None
        # verified before 0.7.0: no blob recorded, and a working-tree byte hash cannot be compared
        # with a PR head under line-ending filters — those PRs carry no framings to drop anyway
        if vblob and _git_blob(root, rev, vrel) != vblob:
            reasons.append("verify-changed")  # e.g. framings dropped after verify passed
    cst = (st.get("stages") or {}).get("critique") or {}
    blobs = cst.get("blobs") if isinstance(cst.get("blobs"), dict) else None
    md_rel = work_rel(tid, "critique.md")
    if blobs:
        changed = any(_git_blob(root, rev, work_rel(tid, n)) != blobs.get(n) for n in ("critique.md", "critique.json"))
    else:  # recorded before 0.6.0: content hashes only
        outs = cst.get("outputs") or {}
        md = _blob_hash(root, rev, md_rel) if rev else file_hash(root, md_rel)
        changed = ch != outs.get("critique.json") or md != outs.get("critique.md")
    if changed:
        reasons.append("critique-changed")
    slug = st.get("slug")
    if slug:
        img = cfg.image_dir(slug) + "/"
        if any(f.startswith(img) for f in commits.changed_files(root, "origin/%s...%s" % (cfg.base, rev or "HEAD"))):
            reasons.append("images")
    return sorted(set(reasons))


def audit_entries(crit):
    """`audit_log` entries, the latest per id (an outcome is updated by rewriting the entry;
    an appended entry with the same id supersedes the earlier one)."""
    latest = {}
    for i, e in enumerate((crit or {}).get("audit_log") or []):
        if isinstance(e, dict):
            latest[str(e.get("id", "#%d" % i))] = e
    return list(latest.values())


def _sev(e):
    return str(e.get("severity", "")).upper()


def _count_problems(fr):
    problems = []
    for group in ("audit", "dismissed", "deferred"):
        g = fr.get(group)
        if g is None:
            continue
        if not isinstance(g, dict):
            problems.append("final_round.%s must be an object" % group)
            continue
        for k, v in g.items():
            if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                problems.append("final_round.%s.%s must be a non-negative integer, not %r" % (group, k, v))
    return problems


def audit_log_problems(crit, rnd):
    """What `stage pass --stage critique` checks beyond the verdict: counts are integers; a
    deferred MAJOR is logged as deferred in this round (tag `new`, any tag on the last round); a
    BLOCKER from the last round is closed only by a human's recorded decision; a skip round ran
    no auditor."""
    fr = (crit or {}).get("final_round") or {}
    log = audit_entries(crit)
    problems = _count_problems(fr)
    deferred = _int((fr.get("deferred") or {}).get("major"))
    if deferred and rnd <= AUDIT_ROUND_CAP:
        last = rnd >= AUDIT_ROUND_CAP
        ok = [e for e in log if e.get("round") == rnd and _sev(e) == "MAJOR" and e.get("outcome") == "deferred"
              and (last or e.get("tag") == "new")]
        if len(ok) < deferred:
            problems.append("final_round.deferred.major is %d but audit_log lists %d deferrable MAJOR(s) for round %d "
                            "(deferred, tag new — any tag on the last round)" % (deferred, len(ok), rnd))
    human = {str(d.get("id")) for d in ((crit or {}).get("decision_log") or [])
             if isinstance(d, dict) and d.get("kind") == "human"}
    if os.environ.get("HRD_UNATTENDED") == "1" and any(
            _sev(e) == "BLOCKER" and _int(e.get("round")) >= AUDIT_ROUND_CAP and str(e.get("id")) in human for e in log):
        problems.append("refusing: a last-round BLOCKER closed by a human decision cannot pass in an unattended run")
    if rnd == AUDIT_ROUND_CAP:
        logged = [e for e in log if _sev(e) == "BLOCKER" and e.get("round") == rnd]
        if _int((fr.get("audit") or {}).get("blocker")) > len(logged):
            problems.append("every BLOCKER of the last audit round must be in audit_log with its id and round")
    for e in log:
        r = e.get("round")
        if isinstance(r, bool) or not isinstance(r, int):
            problems.append("audit_log entry %s has no integer round" % e.get("id"))
            continue
        if _sev(e) == "BLOCKER" and e.get("outcome") == "deferred":
            problems.append("BLOCKER %s is logged deferred — a BLOCKER is fixed, dismissed by a human or held"
                            % e.get("id"))
        if _sev(e) == "BLOCKER" and r >= AUDIT_ROUND_CAP and str(e.get("id")) not in human:
            problems.append("BLOCKER %s from the last audit round needs a human's decision (decision_log kind "
                            "human, id %s) — hold needs-human" % (e.get("id"), e.get("id")))
        elif _sev(e) in ("BLOCKER", "MAJOR") and e.get("outcome") == "open" and r < AUDIT_ROUND_CAP:
            problems.append("audit_log %s is open (held for a human): resolve it to fixed or dismissed with the "
                            "human before passing" % e.get("id"))
    if rnd > AUDIT_ROUND_CAP:
        for group in ("audit", "dismissed", "deferred"):
            if any(_int(v) for v in (fr.get(group) or {}).values()):
                problems.append("audit round %d is past the cap: no auditor ran, final_round.%s must be empty "
                                "(earlier decisions stay in audit_log)" % (rnd, group))
        open_ = [e.get("id") for e in log if _sev(e) == "BLOCKER" and e.get("outcome") not in ("fixed", "dismissed")]
        if open_:
            problems.append("BLOCKER %s is still open in audit_log" % ", ".join(map(str, open_)))
    return problems


def run_gate(root, cfg, slug):
    """draft gate (plan §3.5): config.commands.validate if set, else the built-in validator."""
    import shlex
    from .util import run
    from .validate import prose_for, validate

    body = cfg.body_path(slug)
    custom = (cfg.get("commands", "validate") or "").strip()
    if custom:
        proc = run(shlex.split(custom) + [body], cwd=root, check=False)
        ok = proc.returncode == 0
        errors = [] if ok else [(proc.stdout + proc.stderr).strip()[-500:]]
        out = proc.stdout
        try:  # a validator that prints Herald's own report (e.g. wraps validate_content.py, maybe after a banner)
            out = json.loads(out[out.index("{"):out.rindex("}") + 1])
            if isinstance(out, dict) and isinstance(out.get("errors"), list) and (out["errors"] or ok):
                errors = [str(e) for e in out["errors"]]
        except ValueError:
            pass
        return {"ok": ok, "errors": errors, "prose": prose_for(root, cfg, body)}
    return validate(root, cfg, body)


def prose_rel(tid):
    """Readability hints of a topic's current body: gitignored memory, never committed (a tracked
    file would go stale on base and dirty the tree before a deploy)."""
    return os.path.join(".claude", "herald", "memory", "prose", "%s.json" % tid)


def reader_blockers(root, cfg, tid, st):
    """The editor's blocking reader-pass problems for the current body, from `reader.json`
    (`{"body_hash", "round", "blockers": [...], "notes": [...]}`; body_hash added by the
    editor-in-chief). No file (an editor before 0.7.0) or one about another body → none. A file
    without `body_hash`, unreadable, or with non-list `blockers` is refused: silently reading
    it as "none" would switch the once-per-article count off."""
    path = os.path.join(root, work_rel(tid, "reader.json"))
    if not os.path.exists(path):
        return []
    rd = safe_machine(root, tid, "reader.json")
    if not rd or not isinstance(rd.get("blockers"), list) or not str(rd.get("body_hash") or "").startswith("sha256:"):
        raise HeraldError("reader.json is malformed — it needs a `blockers` list (the editor's) and `body_hash` "
                          "(the `HRD hash` taken before the editor ran, added by the editor-in-chief)")
    if not st.get("slug") or rd["body_hash"] != worktree_hash(root, cfg, st["slug"]):
        return []
    return [str(x) for x in rd["blockers"]]


LOOP_CAP = 3  # counted loopbacks per article (contract §F)


def reader_round_used(st):
    """Readability can no longer send this article back: its one send-back is used, or the
    loopback budget is down to its last one, which stays for accuracy and audit findings."""
    return bool(st.get("reader_revise")) or _int(st.get("loopbacks")) >= LOOP_CAP - 1


def _reader_pass_refusal(st, when):
    if reader_round_used(st):  # the editor ignored reader_round_used: its PASS stands, the blockers are notes
        return ("reader.json lists blocking reader-pass problems, but the one reader-pass send-back is used — move "
                "them to `notes` in reader.json (the editor's PASS stands; no loopback), then run this again")
    return ("reader.json lists blocking reader-pass problems for this body — a PASS cannot carry them: loop back "
            "(`HRD loopback --cause revise`) %s" % when)


def write_prose(root, cfg, tid, slug, gate):
    """`reader_round_used`: reader-pass problems already sent this article back (state
    `reader_revise`, set by `loopback --cause revise` from reader.json) or the loopback budget
    is spent — the editor then lists new ones as reader notes instead of blocking."""
    prose = gate.get("prose") or {"warnings": [], "stats": {}}
    try:
        used = reader_round_used(load_state(root, tid))
    except Exception:  # noqa: BLE001 — hints never fail the gate
        used = False
    try:
        write_json(os.path.join(root, prose_rel(tid)),
                   {"body_hash": worktree_hash(root, cfg, slug), "reader_round_used": used, **prose})
    except Exception:  # noqa: BLE001 — hints never fail the gate
        return None
    return prose_rel(tid)


def record_gate_failure(root, st, tid, stage, gate, amend=False):
    """Not on `verify --amend` or after a human-requested revision (the failing edit is a
    human's), and once per topic and loopback count (retries of one draft are one event)."""
    n = int(st.get("loopbacks", 0))
    attempt = st.get("created_at")  # a requeued topic starts a new state (loopbacks 0 again)
    try:
        seen = any(isinstance(r, dict) and r.get("kind") == "gate-failure" and r.get("topic_id") == tid
                   and isinstance(r.get("data"), dict) and r["data"].get("loopbacks") == n
                   and r["data"].get("attempt") == attempt for r in read_jsonl(paths(root)["signals"]))
    except Exception:  # noqa: BLE001 — never hide the gate error behind a signal problem
        seen = True
    if not amend and st.get("last_loopback") != "human" and not seen:
        safe_signal(root, "gate-failure", tid, {"stage": stage, "errors": gate["errors"][:10],
                                                "loopbacks": n, "attempt": attempt})


def stage_pass(root, cfg, tid, stage, amend=False):
    st = load_state(root, tid)
    if stage not in PRODUCES:
        raise HeraldError("unknown stage %s" % stage)
    if (st.get("trim") or {}).get("status") == "open":
        raise HeraldError("a trim is open — `HRD trim --topic %s --finish` or `--abort` first" % tid)
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
        if stage == "draft":
            write_prose(root, cfg, tid, st["slug"], gate)
        if not gate["ok"]:
            record_gate_failure(root, st, tid, stage, gate, amend)
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
        rounds = _int(st.get("audit_rounds"))
        claimed_round = ((crit or {}).get("final_round") or {}).get("audit_round")
        if rounds < 1:
            raise HeraldError("no audit round counted — run `HRD audit-round --topic %s` before spawning the auditor" % tid)
        if claimed_round != rounds:
            raise HeraldError("critique.json final_round.audit_round is %r but this article's audit round is %d"
                              % (claimed_round, rounds))
        problems = audit_log_problems(crit, rounds)
        if problems:
            raise HeraldError("; ".join(problems))
        if not critique_passed(crit):
            raise HeraldError("critique.json does not record a PASS with no BLOCKER/MAJOR left open "
                              "(dismissed, or a MAJOR deferred on a recheck round)")
        if reader_blockers(root, cfg, tid, st):
            raise HeraldError(_reader_pass_refusal(st, "before this pass"))
        rec["body_hash"] = worktree_hash(root, cfg, st["slug"])
        # git blob ids too: a PR head is compared by blob, which line-ending filters keep equal
        rec["blobs"] = {n: _git_blob(root, None, work_rel(tid, n)) for n in ("critique.md", "critique.json")}
        tr = st.get("trim") or {}
        if tr.get("status") == "done" and tr.get("hash") != rec["body_hash"]:
            tr["status"] = "superseded"  # a fresh critique evaluated a later body: the trim is history
        # dismissals are recorded from the decision log, not from memory (abuse watch, auditor
        # prompt material); also on audit loopbacks, so a topic that never passes keeps them
        record_dismissals(root, tid, crit)
    if stage == "verify":
        ver = load_machine(root, tid, "verify.json")
        if not verify_passed(ver):
            raise HeraldError("verify.json has unsupported or contradicted claims")
        bh = worktree_hash(root, cfg, st["slug"])
        rec["body_hash"] = bh
        rec["blobs"] = {"verify.json": _git_blob(root, None, work_rel(tid, "verify.json"))}
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


# --- trim: the one deletion-only repair of a verify gap (contract §F) ----------------------

TRIM_MAX_UNSUPPORTED = 3   # more unsupported sentences than this is a writing problem: loop back
TRIM_MAX_SENTENCE = 400    # characters: a longer "sentence" is a passage
_ASIDE_RE = re.compile(r"[(（][^()（）\n]*[)）]")
_CLOSERS = "\"'”’)）」』"
_ABBREVIATIONS = {"dr", "mr", "mrs", "ms", "prof", "st", "jr", "sr", "vs", "etc", "e.g", "i.e", "no", "fig", "vol",
                  "approx", "inc", "ltd", "co", "corp", "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep",
                  "sept", "oct", "nov", "dec", "mt", "ft", "est", "dept", "gen", "gov", "rev", "p", "pp"}
_LINE_MARK_RE = re.compile(r"[ \t]*(?:[-*+]|\d+[.)]|>|#{1,6})?[ \t]*")
# text a trim never cuts into: code, URLs, autolinks, link targets
_PROTECTED_RE = re.compile(r"(?ms)^[ \t]*(```|~~~).*?^[ \t]*\1[^\n]*$|^(?: {4}|\t)[^\n]*$|`[^`\n]+`|<[^<>\s]+>"
                           r"|\]\((?:[^()\s]|\([^()\s]*\))*\)|\bhttps?://\S+")


def _trim_dir(root, tid):
    return os.path.join(paths(root)["memory"], "trim", tid)


def _image_hash(root, cfg, slug):
    return worktree_hash(root, cfg, slug, path=cfg.image_dir(slug))


def _body_start(text):
    """Offset where the body starts (after a `---` YAML or `+++` TOML frontmatter block), so a
    trim never touches frontmatter fields (draft, noindex, description …). None: a frontmatter
    opens but does not close."""
    m = re.match(r"(---|\+\+\+)\r?\n", text)
    if not m:
        return 0
    end = re.compile(r"\r?\n%s\r?\n" % re.escape(m.group(1))).search(text, m.end() - 1)
    return end.end() if end else None


def _sentence_bounds(text, a, b):
    """Does text[a:b] stand as whole sentences? It starts a paragraph or block line (after a
    list/quote/heading mark), or follows a sentence end — after 。！？ directly, after .!? and a
    space only when it opens with a capital, a digit or a non-ASCII letter (so "e.g. aspirin"
    is no start); a line start inside a paragraph counts only when the previous line ended a
    sentence. It ends with a sentence end followed by whitespace or the end of the text (a CJK
    end may also be followed by more text, but not after a closing quote)."""
    seg = text[a:b]
    if not seg or len(seg) > TRIM_MAX_SENTENCE or re.search(r"\n[ \t]*\n", seg):
        return False
    ls = text.rfind("\n", 0, a) + 1
    line = text[ls:a]
    end_re = r"(?:[.!?][%s]*|[。！？][%s]*)" % (_CLOSERS, _CLOSERS)
    if _LINE_MARK_RE.fullmatch(line):
        if line.strip():
            starts = True  # after a list, quote or heading mark
        else:
            prev = text[text.rfind("\n", 0, max(ls - 1, 0)) + 1:max(ls - 1, 0)] if ls else ""
            starts = ls == 0 or not prev.strip() or re.search(end_re + r"[ \t]*$", prev) is not None
    elif re.search(r"[。！？][%s]*[ \t]*$" % _CLOSERS, line):
        # after a closing quote only with a space: 「…。」と述べた。 continues the sentence
        starts = re.search(r"[。！？][%s]+$" % _CLOSERS, line) is None
    elif re.search(r"[.!?][%s]*[ \t]+$" % _CLOSERS, line):
        word = re.search(r"(\S*)[.!?][%s]*[ \t]+$" % _CLOSERS, line).group(1)
        abbrev = (word.lower().rstrip(".") in _ABBREVIATIONS or re.fullmatch(r"[A-Z]", word) is not None
                  or "." in word)  # Dr. Smith, J. Doe, U.S. Food …
        starts = not re.match(r"[a-z]", seg) and not abbrev
    else:
        starts = False
    m = re.search(r"([.!?。！？])([%s]*)$" % _CLOSERS, seg)
    after = text[b:b + 1]
    if not m:
        ends = False
    elif after in ("", " ", "\t", "\r", "\n"):
        ends = True
    else:
        ends = m.group(1) in "。！？" and not m.group(2)
    return bool(starts and ends)


def _cjk(c):
    """Kana, CJK ideographs and fullwidth forms: written without spaces (Hangul is not)."""
    return bool(c) and ("\u3000" <= c <= "\u30ff" or "\u3400" <= c <= "\u9fff" or "\uff00" <= c <= "\uffef")


def _protected(text):
    return [(m.start(), m.end()) for m in _PROTECTED_RE.finditer(text)]


def _kept_pattern(old, spans):
    """The trimmed body must be the snapshot minus `spans`, byte for byte. At each seam only the
    whitespace the deletion left may change: within a line it may close up to one space or none;
    across lines the line break and indentation before the next kept text stay as they were."""
    merged = []
    for a, b in sorted(spans):  # deletions separated only by whitespace form one seam
        if merged and not old[merged[-1][1]:a].strip():
            merged[-1][1] = b
        else:
            merged.append([a, b])
    pieces, last = [], 0
    for a, b in merged:
        pieces.append(old[last:a])
        last = b
    pieces.append(old[last:])
    out = []
    for i, p in enumerate(pieces):
        lead = re.match(r"\s*", p).group(0) if i > 0 else ""
        core = p[len(lead):]
        trail = re.search(r"\s*$", core).group(0) if i < len(pieces) - 1 else ""
        core = core[:len(core) - len(trail)] if trail else core
        out.append((lead, core, trail))
    pat = []
    for i, (lead, core, trail) in enumerate(out):
        if i > 0:
            wl, wr = out[i - 1][2], lead
            if i == len(out) - 1 and not core:
                opts = {wl, wr, wl + wr}  # trailing whitespace at the end of the text
            elif "\n" in wr:
                # the next line keeps its own break and indentation (or the previous side's,
                # when the indentation is the same)
                opts = {wr} | ({wl} if "\n" in wl and wl.rsplit("\n", 1)[1] == wr.rsplit("\n", 1)[1] else set())
            elif "\n" in wl:
                opts = {wl}
            else:
                opts = {x for x in (" ", wl, wr, wl + wr) if x}
                left, right = out[i - 1][1][-1:], core[:1]
                if (not wl and not wr) or (right and not right.isalnum() and not right.isspace()) or (
                        _cjk(left) and _cjk(right)):
                    opts.add("")  # as it was, before punctuation ("helps (x)." → "helps."), or between CJK
            pat.append("(?:%s)" % "|".join(re.escape(o) for o in sorted(opts, key=len, reverse=True)))
        pat.append(re.escape(core))
    return re.compile("".join(pat), re.S)


def trim_begin(root, cfg, tid):
    """Open the trim after a failed verify. The fact-checker lists the unsupported text verbatim
    — whole sentences, or a parenthetical aside when that aside alone is unsupported; the writer
    may then only delete a listed text whole, or map it to an existing claim. The article
    critique passed is snapshotted."""
    import shutil

    st = load_state(root, tid)
    slug = st.get("slug")
    if st.get("trim"):
        raise HeraldError("%s was already trimmed once (%s) — loop back or hold" % (tid, st["trim"].get("status")))
    if st.get("stage") != "verify" or not slug:
        raise HeraldError("trim repairs a failed verify (stage is %s)" % st.get("stage"))
    if "translator" in ((cfg.get("roles", "conditional") or [])):
        raise HeraldError("trim does not cover translations — loop back")
    cur = worktree_hash(root, cfg, slug)
    if not cur or (st["stages"].get("critique") or {}).get("body_hash") != cur:
        raise HeraldError("critique did not pass on the current article — trim only repairs a verify gap on it")
    ver = load_machine(root, tid, "verify.json") or {}
    if ver.get("body_hash") != cur:
        raise HeraldError("verify.json does not evaluate the current article — run verify first")
    counts = ver.get("counts") if isinstance(ver.get("counts"), dict) else {}
    con, uns = _int(counts.get("contradicted")), _int(counts.get("unsupported"))
    if con:
        raise HeraldError("a contradicted sentence is never trimmed away — loop back")
    if not 1 <= uns <= TRIM_MAX_UNSUPPORTED:
        raise HeraldError("trim takes 1 to %d unsupported sentences, not %d — loop back"
                          % (TRIM_MAX_UNSUPPORTED, uns))
    sents = ver.get("unsupported_sentences")
    if not isinstance(sents, list) or len(sents) != uns or not all(isinstance(x, str) and x.strip() for x in sents):
        raise HeraldError("verify.json must list the %d unsupported sentences verbatim (unsupported_sentences) — "
                          "loop back" % uns)
    quals = ver.get("unsupported_qualifiers") or []
    if not isinstance(quals, list) or any(isinstance(q, str) and q.strip() in [x.strip() for x in sents] for q in quals):
        raise HeraldError("an unsupported warning or limit is never trimmed (deleting it broadens what remains) — "
                          "loop back")
    body_path = os.path.join(root, cfg.body_path(slug))
    with open(body_path, encoding="utf-8", newline="") as f:
        old = f.read()
    b0 = _body_start(old)
    if b0 is None:
        raise HeraldError("the article's frontmatter does not close — loop back")
    prot = _protected(old)
    units, taken = [], []
    for text in sents:
        text = text.strip()
        aside = _ASIDE_RE.fullmatch(text) is not None
        hits = [m.start() + b0 for m in re.finditer(re.escape(text), old[b0:])]
        if len(hits) != 1:
            raise HeraldError("unsupported text found %d times in the article body (need exactly once, "
                              "verbatim): %r — loop back" % (len(hits), text[:80]))
        a, b = hits[0], hits[0] + len(text)
        if aside:
            # an aside the fact-checker named as the unsupported part, never inside code or a link
            if old[a - 1:a] == "]" or any(a < y and x < b for x, y in prot):
                raise HeraldError("%r sits in a link, code or URL — loop back" % text[:80])
            if old[a - 1:a] in (" ", "\t"):
                a -= 1
        else:
            if not _sentence_bounds(old, a, b):
                raise HeraldError("%r is not a whole sentence (it must start a line or follow a sentence end, end a "
                                  "sentence or a line, be at most %d characters and one paragraph) — loop back"
                                  % (text[:80], TRIM_MAX_SENTENCE))
            if any((x < a < y) or (x < b < y) for x, y in prot):
                raise HeraldError("%r cuts through a link, code or URL — loop back" % text[:80])
            ls = old.rfind("\n", 0, a) + 1
            le = old.find("\n", b)
            mark = old[ls:a]
            if mark.strip() and _LINE_MARK_RE.fullmatch(mark) and not old[b:le if le != -1 else None].strip():
                if mark.strip().startswith("#"):
                    raise HeraldError("%r is a whole heading — deleting it would move its section under the "
                                      "previous one; loop back" % text[:80])
                nxt = old[le + 1:old.find("\n", le + 1) if old.find("\n", le + 1) != -1 else None] if le != -1 else ""
                ind = len(mark) - len(mark.lstrip())
                nm = re.match(r"([ \t]*)(?:[-*+]|\d+[.)])[ \t]", nxt)
                if not (le == -1 or not nxt.strip() or (nm and len(nm.group(1)) <= ind)):
                    raise HeraldError("%r is a list item with lines attached below it — deleting it would move them "
                                      "to another item; loop back" % text[:80])
                a = ls  # a whole list item goes with its mark
        if any(a < y and x < b for x, y in taken):
            raise HeraldError("unsupported texts overlap — loop back")
        taken.append((a, b))
        units.append({"text": text, "span": [a, b], "aside": aside})
    d = _trim_dir(root, tid)
    if os.path.isdir(d):
        shutil.rmtree(d)
    os.makedirs(d)
    shutil.copyfile(body_path, os.path.join(d, "body"))
    cmap = os.path.join(root, work_rel(tid, "claims-map.json"))
    if os.path.isfile(cmap):
        shutil.copyfile(cmap, os.path.join(d, "claims-map.json"))
    img = os.path.join(root, cfg.image_dir(slug))
    if os.path.isdir(img):
        shutil.copytree(img, os.path.join(d, "images"))
    st["trim"] = {"status": "open", "base_hash": cur, "images": _image_hash(root, cfg, slug),
                  "snapshot": file_hash(root, os.path.relpath(os.path.join(d, "body"), root)),
                  "unsupported": uns, "sentences": units, "at": now_iso()}
    save_state(root, tid, st)
    # the gap is the writer's, even when no loopback follows
    safe_signal(root, "verify-gap", tid, {"note": "trim", "trim": True, "counts": counts,
                                          "loopback": _int(st.get("loopbacks"))})
    return {"status": "open", "sentences": [u["text"] for u in units]}


def _trim_choices(units):
    """Each listed sentence or aside is kept or deleted whole."""
    import itertools

    for combo in itertools.product(*[[None, tuple(u["span"])] for u in units]):
        yield sorted(sp for sp in combo if sp)


def _claims_map_problems(root, tid, d, units):
    """The writer may add, change or drop only the claims-map entries of the listed texts (an
    entry whose text contains one, or a sentence that lost a listed aside)."""
    snap = os.path.join(d, "claims-map.json")
    if not os.path.isfile(snap):
        return []
    try:
        with open(snap, encoding="utf-8") as f:
            old = json.load(f)
        with open(os.path.join(root, work_rel(tid, "claims-map.json")), encoding="utf-8") as f:
            new = json.load(f)
    except (OSError, ValueError) as e:
        return ["claims-map.json is unreadable: %s" % e]

    def entries(cm):
        sents = cm.get("sentences") if isinstance(cm, dict) else None
        return [x for x in sents if isinstance(x, dict)] if isinstance(sents, list) else []

    def key(e):
        return json.dumps(e, sort_keys=True, ensure_ascii=False)

    listed = [u["text"] for u in units]
    asides = [u["text"] for u in units if u.get("aside")]
    o, n = entries(old), entries(new)
    shorter = {re.sub(r"[ \t]*" + re.escape(x), "", str(e.get("text", ""))) for e in o for x in asides
               if x in str(e.get("text", ""))}
    ok = set(map(key, o)) & set(map(key, n))
    bad = [e for e in o + n if key(e) not in ok and not any(x in str(e.get("text", "")) for x in listed)
           and str(e.get("text", "")) not in shorter]
    return ["claims-map.json changed outside the listed texts (%s)" % ", ".join(repr(str(e.get("text", ""))[:40])
                                                                       for e in bad[:3])] if bad else []


def _trim_open(root, tid):
    st = load_state(root, tid)
    if (st.get("trim") or {}).get("status") != "open":
        raise HeraldError("%s has no open trim (`HRD trim --topic %s --begin` first)" % (tid, tid))
    return st


def trim_finish(root, cfg, tid):
    """Accept the trim only if the body equals the snapshot minus whole listed texts (only the
    seam whitespace may differ), the images and critique files are untouched and the gate passes;
    then critique's verdict carries over to the shorter body and verify runs again on it."""
    import shutil

    st = _trim_open(root, tid)
    tr, slug = st["trim"], st["slug"]
    if st.get("stage") != "verify":
        raise HeraldError("the trim belongs to verify, but the stage is %s — `HRD trim --topic %s --abort`"
                          % (st.get("stage"), tid))
    d = _trim_dir(root, tid)
    if file_hash(root, os.path.relpath(os.path.join(d, "body"), root)) != tr.get("snapshot"):
        raise HeraldError("the trim snapshot changed or is gone — `HRD trim --topic %s --abort` (with --force if "
                          "the snapshot is gone), then loop back" % tid)
    try:
        with open(os.path.join(d, "body"), encoding="utf-8", newline="") as f:
            old = f.read()
        with open(os.path.join(root, cfg.body_path(slug)), encoding="utf-8", newline="") as f:
            new = f.read()
    except (OSError, UnicodeDecodeError) as e:
        raise HeraldError("cannot compare the trimmed body with its snapshot: %s" % e)
    chosen = None
    for spans in _trim_choices(tr.get("sentences") or []):
        if (not spans and new == old) or (spans and _kept_pattern(old, spans).fullmatch(new)):
            chosen = spans
            break
    problems = []
    if chosen is None:
        problems.append("the body changed beyond deleting listed texts whole")
    crit_out = (st["stages"].get("critique") or {}).get("outputs") or {}
    for name in ("critique.md", "critique.json"):
        if file_hash(root, work_rel(tid, name)) != crit_out.get(name):
            problems.append("%s changed since critique passed" % name)
    problems.extend(_claims_map_problems(root, tid, d, tr.get("sentences") or []))
    if _image_hash(root, cfg, slug) != tr.get("images"):
        problems.append("the images changed — a trim touches only the body text")
    if problems:
        raise HeraldError("; ".join(problems) + " (`HRD trim --topic %s --abort` restores the article)" % tid)
    gate = run_gate(root, cfg, slug)
    if not gate["ok"]:
        raise HeraldError("deterministic gate failed on the trimmed body: %s (`HRD trim --topic %s --abort` "
                          "restores the article)" % ("; ".join(gate["errors"][:5]), tid))
    cur = worktree_hash(root, cfg, slug)
    out = st["stages"].setdefault("draft", {}).setdefault("outputs", {})
    out["@article"] = cur
    out["claims-map.json"] = file_hash(root, work_rel(tid, "claims-map.json"))
    st["stages"].setdefault("critique", {})["body_hash"] = cur  # critique's verdict covers the shorter body
    tr.update({"status": "done", "hash": cur, "removed": [old[a:b].strip() for a, b in chosen],
               "done_at": now_iso()})
    save_state(root, tid, st)
    shutil.rmtree(d, ignore_errors=True)
    return tr


def trim_abort(root, cfg, tid, force=False):
    """Put back the article, claims map and images critique passed; the trim stays used. With
    `force` and the snapshot gone (it is local), only close the trim: the article then differs
    from what critique passed, so the entry checks send it back through draft."""
    import shutil

    st = _trim_open(root, tid)
    d = _trim_dir(root, tid)
    body = os.path.join(d, "body")
    if not os.path.isfile(body):
        if not force:
            raise HeraldError("the trim snapshot is gone (%s) — `HRD trim --topic %s --abort --force` closes the "
                              "trim; then loop back" % (d, tid))
        st["trim"].update({"status": "aborted", "done_at": now_iso(), "note": "snapshot lost"})
        save_state(root, tid, st)
        return {"restored": False, "trim": st["trim"]}
    slug = st["slug"]
    shutil.copyfile(body, os.path.join(root, cfg.body_path(slug)))
    if os.path.isfile(os.path.join(d, "claims-map.json")):
        shutil.copyfile(os.path.join(d, "claims-map.json"), os.path.join(root, work_rel(tid, "claims-map.json")))
    img = os.path.join(root, cfg.image_dir(slug))
    if _image_hash(root, cfg, slug) != st["trim"].get("images"):
        if os.path.isdir(img):
            shutil.rmtree(img)
        if os.path.isdir(os.path.join(d, "images")):
            shutil.copytree(os.path.join(d, "images"), img)
    if worktree_hash(root, cfg, slug) != st["trim"].get("base_hash"):
        raise HeraldError("could not restore the article critique passed (snapshot kept in %s)" % d)
    st["trim"].update({"status": "aborted", "done_at": now_iso()})
    save_state(root, tid, st)
    shutil.rmtree(d, ignore_errors=True)
    return {"restored": True, "trim": st["trim"]}


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
    if kind == "push":
        sha = pushed_head(root, sha)
    rec = {"at": now_iso(), "topic_id": tid, "slug": st["slug"], "verified_hash": cur,
           "sha": sha, "kind": kind}
    append_jsonl(paths(root)["ledger"], rec)
    return rec


def pushed_head(root, sha=None):
    """A push record names the commit the branch now points at: HEAD, read here rather than
    copied by hand. A given `sha` must resolve to that same commit."""
    from .util import run

    head = run(["git", "rev-parse", "--verify", "HEAD^{commit}"], cwd=root, check=False)
    if head.returncode != 0:
        raise HeraldError("cannot read HEAD for the push record")
    head = head.stdout.strip()
    br = run(["git", "symbolic-ref", "--quiet", "--short", "HEAD"], cwd=root, check=False).stdout.strip()
    if not br:
        raise HeraldError("refusing to record a push: HEAD is detached — switch to the herald branch")
    # what `git push origin <branch>` updated, whatever the branch tracks
    remote = run(["git", "rev-parse", "--verify", "--quiet", "refs/remotes/origin/%s" % br], cwd=root, check=False)
    if remote.returncode != 0 or remote.stdout.strip() != head:
        raise HeraldError("refusing to record: HEAD %s is not origin/%s — `git push origin %s` first"
                          % (head[:12], br, br))
    if sha:
        got = run(["git", "rev-parse", "--verify", "--quiet", "%s^{commit}" % sha], cwd=root, check=False)
        if got.returncode != 0 or got.stdout.strip() != head:
            raise HeraldError("refusing to record: --sha %s is not HEAD (%s) — omit --sha" % (sha, head[:12]))
    return head


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

def mark_auto_merged(root, tid, pr=None, clear=False, accepted=None):
    """An interactive auto publish (`ship --session-auto` of a PR no human approved) stamps the
    topic just before the merge, as the batch runner does: the article stays human_reviewed=false
    and counts toward today's throttle whoever records it later. `clear` undoes a stamp whose
    merge did not happen."""
    data = load_topics(root)
    t = get_topic(data, tid)
    if clear:
        t.pop("auto_merged_pr", None)
        t.pop("auto_merged_at", None)
        t.pop("auto_merged_accepted", None)
    else:
        if pr is None or int(pr) <= 0:
            raise HeraldError("--pr must be the PR number being merged")
        if t.get("state") == "published":
            raise HeraldError("%s is already published" % tid)
        if t.get("auto_merged_pr") and str(t["auto_merged_pr"]) != str(pr):
            raise HeraldError("%s already carries an auto-merge stamp for PR #%s" % (tid, t["auto_merged_pr"]))
        t["auto_merged_pr"] = int(pr)
        t["auto_merged_at"] = now_iso()
        if accepted:  # exclusions the human accepted by asking for this publish (`/hrd next`)
            t["auto_merged_accepted"] = sorted(set(accepted))
        else:
            t.pop("auto_merged_accepted", None)
    save_topics(root, data)
    return {"topic": tid, "auto_merged_pr": t.get("auto_merged_pr"), "auto_merged_at": t.get("auto_merged_at"),
            "accepted": t.get("auto_merged_accepted", [])}


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
    stamped = bool(t.get("auto_merged_pr")) and (pr is None or str(pr) == str(t["auto_merged_pr"]))
    if stamped:
        auto = True  # merged unattended: stays false whoever records it later
    accepted = t.get("auto_merged_accepted") if stamped else None
    if accepted:  # what the human accepted unread for this publish (`/hrd next`)
        art["auto_accepted"] = list(accepted)
    else:
        art.pop("auto_accepted", None)
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
    "revise-weakness", "verify-gap", "hold", "gate-failure", "escalation",
    "session-edit-request",
    "stagnation",  # legacy (0.2.x): now recorded as a hold with reason stagnation
    "incomplete",  # a batch child that ended without a result (crash, timeout)
)
# listed for evolve but never counted toward the nudge: an escalation accompanies a loopback that
# is already counted; an incomplete child is usually environment, not writing
CONTEXT_KINDS = ("escalation", "incomplete")


# Hold notes that mark a stop as environment or a human's choice, not a writing weakness: never a
# growth signal (the last two are what 0.2.x wrote for environment stops)
NON_SIGNAL_HOLD_NOTES = ("tooling:", "human:", "batch child did not finish", "base has foreign unpushed commits")

# Closed theme list for editor REVISE and auditor findings: the editor-in-chief classifies each
# loopback so the nudge counts recurring weaknesses, not every REVISE (one theme = one count axis).
THEMES = ("intro", "structure", "length", "depth", "clarity", "tone", "search", "promotion",
          "policy", "accuracy", "images", "exemplar", "other")
LOOPBACK_CAUSES = {"revise": "revise-weakness", "audit": "audit-finding", "verify": "verify-gap", "gate": None}


def safe_signal(root, kind, tid=None, data=None):
    """Best-effort recording for signals written as a side effect of a state change: a signal
    failure is reported on stderr and never undoes or blocks the change itself."""
    import sys
    try:
        return signal(root, kind, tid, data)
    except Exception as e:  # noqa: BLE001 — growth evidence must not break the flow
        sys.stderr.write("hrd: warning: could not record %s signal: %s\n" % (kind, e))
        return None


def safe_machine(root, tid, name):
    """A verdict file as a dict, or {} if missing or unreadable (for signal data only)."""
    try:
        m = load_machine(root, tid, name)
    except Exception:  # noqa: BLE001 — bad JSON, absurd nesting, unreadable file
        return {}
    return m if isinstance(m, dict) else {}


def record_dismissals(root, tid, crit):
    """Dismissals from critique.json's decision log (append-only across rounds). A record
    identical to one already in the file (kind, topic, data) is not appended again, so a
    dismissal an evolve proposal consumed does not come back on the next critique pass."""
    import sys
    try:
        log = crit.get("decision_log") if isinstance(crit, dict) else None
        if not isinstance(log, list):
            return
        # one dismissal = its note on this topic (other fields may be normalized between rounds,
        # and 0.2.x recorded dismissals by hand in other shapes)
        def note_of(data):
            if not isinstance(data, dict):
                return None
            n = data.get("note")
            if isinstance(n, str):
                return n[:500]
            import json as _json  # no note: the remaining fields identify it
            return _json.dumps({k: data[k] for k in ("severity", "finding") if k in data}, sort_keys=True)
        existing = {note_of(r.get("data")) for r in read_jsonl(paths(root)["signals"])
                    if isinstance(r, dict) and r.get("kind") == "dismissal" and r.get("topic_id") == tid}
        for d in log:
            if isinstance(d, dict) and d.get("kind") == "dismissal":
                data = {k: d[k] for k in ("note", "severity", "finding", "round") if k in d}
                if isinstance(data.get("note"), str):
                    data["note"] = data["note"][:500]
                key = note_of(data)
                if key not in existing:
                    signal(root, "dismissal", tid, data)
                    existing.add(key)
    except Exception as e:  # noqa: BLE001
        sys.stderr.write("hrd: warning: could not record dismissal signals: %s\n" % e)


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
    stagnation_holds = {r.get("topic_id") for r in records if isinstance(r, dict) and r.get("kind") == "hold"
                        and isinstance(r.get("data"), dict) and r["data"].get("reason") == "stagnation"}
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
        if rec["kind"] == "stagnation" and rec.get("topic_id") in stagnation_holds:
            continue  # 0.2.x could record both for one event; the hold already counts
        if rec["kind"] == "hold" and str((rec.get("data") or {}).get("note") or "").startswith(NON_SIGNAL_HOLD_NOTES):
            continue  # environment stops / human choices (0.2.x recorded them as holds)
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


def signal_theme(rec):
    """The count axis: `kind`, or `kind:theme` when the record names a theme from THEMES (editor
    REVISE and auditor findings), or `hold:<reason>` — so unrelated events of one kind are not
    one recurring problem."""
    data = rec.get("data") or {}
    if data.get("theme") in THEMES:
        return "%s:%s" % (rec["kind"], data["theme"])
    if rec["kind"] == "stagnation":
        return "hold:stagnation"
    if rec["kind"] == "hold" and isinstance(data.get("reason"), str) and data["reason"]:
        return "hold:%s" % data["reason"][:40]
    return rec["kind"]


def evolve_readiness(root, cfg=None, listing=False):
    """Deterministic, advisory count per theme (see signal_theme) over unconsumed signals.
    `tier` (machine token): sufficient — some theme has >= 3 signals from >= 2 topics AND at
    least one of them was not seen by this machine's last evolve scan (a run that found nothing
    is not re-nudged until new evidence comes); watching — signals exist but that is not met;
    none — no signals."""
    sigs, baseline, st = evolve_signals(root)
    seen = set(st["seen"])
    themes, kinds = {}, {}
    for r in sigs:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
        if r["kind"] in CONTEXT_KINDS:
            continue
        k = themes.setdefault(signal_theme(r), {"count": 0, "topics": set(), "new": 0})
        k["count"] += 1
        if r.get("topic_id"):
            k["topics"].add(r["topic_id"])
        if not seen.intersection(r["ids"]):
            k["new"] += 1
    ready = sorted(n for n, k in themes.items() if k["count"] >= MIN_SIGNALS and len(k["topics"]) >= MIN_TOPICS)
    fresh = [n for n in ready if themes[n]["new"] > 0]
    total = sum(k["count"] for k in themes.values())
    topics = set().union(*[k["topics"] for k in themes.values()]) if themes else set()
    out = {
        "tier": "sufficient" if fresh else ("watching" if total else "none"),
        "last_scan": st["last_scan"],
        "signals": total,
        "topics": len(topics),
        "ready_themes": ready,
        "new_ready_themes": fresh,
        "themes": {n: {"count": k["count"], "topics": len(k["topics"]), "new": k["new"]}
                   for n, k in sorted(themes.items())},
        "kinds": dict(sorted(kinds.items())),
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
