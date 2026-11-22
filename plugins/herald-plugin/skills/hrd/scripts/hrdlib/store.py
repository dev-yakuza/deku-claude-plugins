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

from .hashing import bundle_files, bundle_hash, file_hash, tree_hash, worktree_hash
from .util import HeraldError, append_jsonl, herald_dir, now_iso, read_json, read_jsonl, write_json

# t0001 · r-<slug>-<date>[-n] (refresh) · tr-<slug>-<date>[-n] (later translation, 01-multilingual.md L11)
TOPIC_ID_RE = re.compile(r"^(t\d{4,}|(?:r|tr)-[a-z0-9][a-z0-9-]*-\d{8}(?:-\d+)?)$")
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

STORED_STATES = ("queued", "held", "declined", "published", "withdrawn", "unwithdrawn")
HOLD_REASONS = (
    "cannibalization", "research", "rejected",          # before PR — cleaned up
    "needs-human", "stagnation", "budget",               # before PR — preserved (WIP branch)
    "verify-after-human-edit",                           # after PR — PR kept open
    "reverted",                                          # after merge — removal revert
    "source-defect",                                     # tr-: the verified source fails verify — cleaned up
    "screenshots",                                       # before PR — preserved; waits for a human's files
)
CLEANUP_REASONS = ("cannibalization", "research", "rejected", "source-defect")
PRESERVE_REASONS = ("needs-human", "stagnation", "budget", "screenshots")
# holds that wait on a human's input rather than mark a writing weakness: never a growth signal
NON_SIGNAL_HOLD_REASONS = ("verify-after-human-edit", "reverted", "screenshots")


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
        raise HeraldError("invalid topic id %r (expected t0001, r-<slug>-YYYYMMDD or tr-<slug>-YYYYMMDD, optionally -<n>)" % tid)


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
    "translation": ["@translations"],  # files + claims-map.<lang>.json (01-multilingual.md §3)
    "verify": ["verify.md", "verify.json"],
}
CONSUMES = {
    "brief": [],
    "research": [("brief", "brief.md")],
    "draft": [("brief", "brief.md"), ("research", "research.md")],
    "critique": [("draft", "@article")],
    # not @article: a translator that edited the source must reach translation's own refusal
    "translation": [("critique", "critique.json")],
    "verify": [("draft", "@article"), ("draft", "claims-map.json"), ("research", "research.md"),
               ("translation", "@translations")],
}
ORDER = ["brief", "research", "draft", "critique", "translation", "verify", "publish"]


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
    if name == "@translations":
        from .translation import translations_hash
        return translations_hash(root, cfg, st)
    return file_hash(root, work_rel(st["topic_id"], name))


def entry_check(root, cfg, st, stage):
    """Plan §3.2 entry condition: every input file still matches the hash its producer recorded."""
    problems = []
    if open_trim(st):
        problems.append("a trim is open — `HRD trim --topic %s --abort` first" % st.get("topic_id"))
    from .translation import langs_of, verify_entry_problems
    for producer, name in CONSUMES.get(stage, []):
        if name == "@translations" and not langs_of(st):
            continue  # no languages (0.8.0 topics, untranslated repos): verify follows critique
        prec = st["stages"].get(producer, {})
        if prec.get("inherited") and str(st.get("topic_id", "")).startswith("tr-") and name not in (prec.get("outputs") or {}):
            continue  # a tr- topic: that stage ran in its reference topic (01-multilingual.md §7)
        rec = prec.get("outputs", {})
        if name not in rec:
            problems.append("%s has not passed (needed for %s)" % (producer, name))
            continue
        cur = artifact_hash(root, cfg, st, name)
        if cur != rec[name]:
            problems.append("%s changed since %s passed — rerun %s" % (name, producer, producer))
    if stage == "verify":
        from .translation import unowned_translations
        problems += verify_entry_problems(st)
        unowned = unowned_translations(root, cfg, st)
        if unowned:
            problems.append("the bundle has %s translations this topic did not make — hold needs-human (requeue, or "
                            "adopt them with /hrd translate --adopt)" % ", ".join(unowned))
    if stage == "publish":
        # critique evaluated the source; verify the bundle (source + translations) — equal
        # without translations (design/herald/01-multilingual.md §3)
        src = worktree_hash(root, cfg, st["slug"])
        cur = bundle_hash(root, cfg, st["slug"])
        c = st["stages"].get("critique", {}).get("body_hash")
        v = st["stages"].get("verify", {}).get("body_hash")
        if not (src and src == c and cur and cur == v == st.get("verified_hash")):
            problems.append("article differs from what critique/verify evaluated — rerun critique and verify")
        vr = st["stages"].get("verify", {}).get("research")
        if vr and vr != artifact_hash(root, cfg, st, "research.md"):
            problems.append("research.md changed since verify checked the article against it — rerun verify")
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
    sh = _audit_scope_hash(root, cfg, tid)
    if not repeat or st.get("scope_hash") != sh:
        if not repeat:
            n += 1
        st["audit_rounds"] = n
        st["audit_round_body"] = cur
        # the scope this round's auditor gets: `stage pass` compares critique.json's scope_hash with it
        # (0.22.0, review 28 m5 — computed here, on this machine, never taken from the editor)
        if sh:
            st["scope_hash"] = sh
        else:
            st.pop("scope_hash", None)
        save_state(root, tid, st)
    mode = "full" if n == 1 else ("recheck" if n <= AUDIT_ROUND_CAP else "skip")
    out = {"round": n, "mode": mode, "last": n == AUDIT_ROUND_CAP, "cap": AUDIT_ROUND_CAP, "repeat": repeat}
    if sh:
        out["scope_hash"] = sh  # final_round.scope_hash of this round (refresh topics with a known scope)
    return out


def _audit_scope_hash(root, cfg, tid):
    try:
        from .scope import refresh_scope
        return refresh_scope(root, cfg, tid).get("scope_hash")
    except Exception:  # noqa: BLE001 — no readable scope: the refresh audits in full
        return None


def _int(v):
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def critique_passed(crit):
    """critique.json final round: editor PASS and no BLOCKER/MAJOR left open. A MAJOR is closed
    by a dismissal, or — on a recheck round (audit_round 2+) — by deferring it to the PR; 0.22.0:
    on a refresh, in any round, by ruling it out of scope (text the refresh did not touch —
    `audit_log_problems` checks the quote; 13 §1.3)."""
    fr = (crit or {}).get("final_round") or {}
    audit = fr.get("audit") or {}
    dism = fr.get("dismissed") or {}
    deferred = fr.get("deferred") or {}
    out = fr.get("out_of_scope") or {}
    rnd = fr.get("audit_round")
    recheck = isinstance(rnd, int) and not isinstance(rnd, bool) and rnd >= 2
    blocker = _int(audit.get("blocker")) - _int(dism.get("blocker"))
    major = _int(audit.get("major")) - _int(dism.get("major")) - (_int(deferred.get("major")) if recheck else 0) \
        - (_int(out.get("major")) if isinstance(out, dict) else 0)
    return fr.get("verdict") == "PASS" and blocker <= 0 and major <= 0


def verify_passed(ver):
    """No unsupported or contradicted sentence and no research claim found wrong (a malformed
    research_suspects list never passes)."""
    c = (ver or {}).get("counts") or {}
    try:
        suspects = research_suspects(ver)
    except HeraldError:
        return False
    return int(c.get("unsupported", 1)) == 0 and int(c.get("contradicted", 1)) == 0 and not suspects


def trims_of(st):
    """Every trim of the article, oldest first: `trims` (0.24.0), or the one `trim` dict a state
    written before 0.24.0 carries (a pending PR's head keeps its `trimmed` exclusion)."""
    st = st or {}
    if isinstance(st.get("trims"), list):
        return [t for t in st["trims"] if isinstance(t, dict)]
    old = st.get("trim")
    return [old] if isinstance(old, dict) and old else []


def open_trim(st):
    return next((t for t in trims_of(st) if t.get("status") == "open"), None)


def _trims_rw(st):
    """`trims` to write to: an old `trim` dict moves into the list."""
    trs = trims_of(st)
    st["trims"] = trs
    st.pop("trim", None)
    return trs


def auto_exclusion(crit, st=None):
    """Reasons a PR may not be auto-published (plan §3.2.2 ③). Empty list = eligible."""
    reasons = []
    done = [t for t in trims_of(st) if t.get("status") == "done" and t.get("hash") != t.get("base_hash")]
    if done:
        reasons.append("trimmed")  # the agents changed the body after critique
    if any(t.get("narrowed") for t in done):
        reasons.append("narrowed")  # a listed sentence lost words: the re-verify judged before → after
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
        if e.get("outcome") == "out-of-scope" or e.get("scope") == "out":  # 13 §1.4, §R1-m3
            if _sev(e) == "BLOCKER":
                reasons.append("audit-log:out-of-scope-blocker")  # never accepted unread
            elif _sev(e) == "MAJOR":
                reasons.append("audit-log:out-of-scope")
    return sorted(set(reasons))


# Exclusions a human may accept for one article by asking for it to be published unread
# (`/hrd next`, `write --ship`): each is a decision the agents made and logged in the PR. The
# others stay blocking: an open BLOCKER, an article changed after its last auditor round, a
# PR whose verdict files cannot be read.
# `screenshots` is never here: a screen may show what must not go out, so a human looks at it in
# `/hrd ship` (design/herald/06-screenshots.md §2.10); nor `external-images`: a web image and its
# attribution are confirmed in `/hrd ship` too (08-images.md §2.13)
# `audit-log:out-of-scope` (0.22.0, 13 §1.4): a MAJOR in text a refresh did not touch, left for the
# next refresh — the same trust as a deferred one
# `narrowed` (0.24.0, 15 D2.4): a trim deleted whole words inside a listed sentence; the full
# before/after re-verify and the revert are its safeguard
CONSENT_ACCEPTS = ("decision:dismissal", "decision:assumption", "decision:deferral",
                   "audit-dismissed", "audit-log:deferred", "audit-log:out-of-scope", "trimmed", "narrowed", "images",
                   "framed", "translated")


# 0.20.0 (design/herald/11-ship-consent.md §2.4, §9 R2-5): a `--ship` run (the lock's ship mark for
# this topic — `strong`, never passed by a caller) also accepts screenshots and external images: an
# agent review stood in for the human's look in draft. Never while a file in the PR is one nobody
# vouched for (`images-unconfirmed` — blocking whatever the consent).
STRONG_ACCEPTS = ("external-images", "screenshots")


def blocking_exclusions(reasons, consent=False, strong=False):
    accepts = CONSENT_ACCEPTS
    if consent and strong and "images-unconfirmed" not in reasons:
        accepts = CONSENT_ACCEPTS + STRONG_ACCEPTS
    return [r for r in reasons if not (consent and r in accepts)]


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


def exclusion_reasons(root, cfg, tid, rev=None, vouch=False):
    """auto_exclusion for one topic, read from a PR head (`rev`; on base the work files are not
    there) or the working tree, plus what only the repo shows: a critique.json changed after
    critique passed, and images the PR adds or changes (they go out unseen). A PR whose verdict
    files cannot be read is never eligible. `vouch` (a `--ship` run's strong consent, 0.20.0): also
    `images-unconfirmed` when a changed image file is one no record vouches for at that head."""
    from . import commits

    rel = work_rel(tid, "critique.json")
    if rev:
        crit, st, ch = read_json_at(root, rev, rel), read_json_at(root, rev, work_rel(tid, "state.json")), \
            _blob_hash(root, rev, rel)
    else:
        crit, st, ch = load_machine(root, tid, "critique.json"), read_json(state_path(root, tid)), file_hash(root, rel)
    inherited = isinstance(st, dict) and tid.startswith("tr-") and \
        ((st.get("stages") or {}).get("critique") or {}).get("inherited")
    if inherited and crit is None:
        crit = {}  # a tr- topic: critique ran in the reference topic; its decisions are not this PR's
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
    if changed and not inherited:
        reasons.append("critique-changed")
    slug = st.get("slug")
    if slug:
        img = cfg.image_dir(slug) + "/"
        changed = commits.changed_files(root, "origin/%s...%s" % (cfg.base, rev or "HEAD"))
        from . import images as images_mod
        if any(f.startswith(img) for f in changed) or images_mod.og_excluded(root, cfg, tid, rev, changed, slug):
            reasons.append("images")  # Herald-made images too: diagrams, the OG card (08-images.md §2.13)
        if images_mod.excluded_external(root, cfg, tid, rev, changed):
            reasons.append("external-images")
        # translations read by no editor or auditor go out only with a human, unless the repo
        # allowed it (translations.auto_publish) — derived from the diff, not from state.json
        from .shots import excluded as shots_excluded
        if shots_excluded(root, cfg, tid, rev, changed):
            reasons.append("screenshots")
        if vouch and images_mod.unvouched(root, cfg, tid, rev, slug):
            reasons.append("images-unconfirmed")
        if vouch:  # 12 §R4-m5: the stand-in records only grow — a commit that shortened one blocks
            from .stand_in import records_shrank
            if records_shrank(root, cfg, tid, rev):
                reasons.append("stand-in-records-shrank")
        tr_paths = set(cfg.translation_paths(slug).values())
        if tr_paths and not (cfg.translations() or {}).get("auto_publish") and any(f in tr_paths for f in changed):
            reasons.append("translated")
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
    for group in ("audit", "dismissed", "deferred", "out_of_scope"):
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


def audit_log_problems(crit, rnd, root=None, cfg=None, tid=None):
    """What `stage pass --stage critique` checks beyond the verdict: counts are integers; a
    deferred MAJOR is logged as deferred in this round (tag `new`, any tag on the last round); a
    BLOCKER from the last round is closed only by a human's recorded decision; a skip round ran
    no auditor. With `root`: out-of-scope findings (0.22.0, `scope.audit_problems`)."""
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
    if root is not None:
        from .scope import audit_problems
        problems += audit_problems(root, cfg, tid, crit, rnd, log)
    if rnd > AUDIT_ROUND_CAP:
        for group in ("audit", "dismissed", "deferred", "out_of_scope"):
            if any(_int(v) for v in (fr.get(group) or {}).values()):
                problems.append("audit round %d is past the cap: no auditor ran, final_round.%s must be empty "
                                "(earlier decisions stay in audit_log)" % (rnd, group))
        open_ = [e.get("id") for e in log if _sev(e) == "BLOCKER" and e.get("outcome") not in ("fixed", "dismissed")]
        if open_:
            problems.append("BLOCKER %s is still open in audit_log" % ", ".join(map(str, open_)))
    return problems


def run_gate(root, cfg, slug, lang=None):
    """draft gate (plan §3.5): config.commands.validate if set, else the built-in validator.
    `lang`: one translation (the translation stage, a re-verify) — the custom validator gets it
    as HRD_LANG, the built-in one applies that language's rules (01-multilingual.md §6)."""
    import shlex
    from .util import run
    from .validate import prose_for, validate

    body = cfg.body_path(slug, lang)
    custom = (cfg.get("commands", "validate") or "").strip()
    if custom:
        env = dict(os.environ, HRD_LANG=lang or cfg.source_lang())
        proc = run(shlex.split(custom) + [body], cwd=root, check=False, env=env)
        ok = proc.returncode == 0
        errors = [] if ok else [(proc.stdout + proc.stderr).strip()[-500:]]
        out = proc.stdout
        try:  # a validator that prints Herald's own report (e.g. wraps validate_content.py, maybe after a banner)
            out = json.loads(out[out.index("{"):out.rindex("}") + 1])
            if isinstance(out, dict) and isinstance(out.get("errors"), list) and (out["errors"] or ok):
                errors = [str(e) for e in out["errors"]]
        except ValueError:
            pass
        return {"ok": ok, "errors": errors, "prose": prose_for(root, cfg, body, lang=lang)}
    return validate(root, cfg, body, lang=lang)


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


# the accuracy reserve (contract §F): once per article, one counted loopback past LOOP_CAP for a
# contradicted sentence or a research fix — state `accuracy_reserve`
# a claim is defined where a line starts with its id and a mark after it (`C9.`, `**C9.**`,
# `### C9:`, `- C9 —`, `1. C9)`, `| C9 |`, `Claim C9:`); ids merely mentioned in excerpts or
# notes do not count, nor a wrapped line that only starts with one ("C2 level …")
_CLAIM_DEF_RE = re.compile(r"(?m)^[ \t]*(?:#{1,6}[ \t]*|[-*+][ \t]+|[0-9]+[.)][ \t]+|\|[ \t]*)?(?:\*\*|__)?\[?"
                           r"(?:Claim[ \t]+)?C([0-9]+)(?:\*\*|__|\])?(?=[.:)．：](?![0-9])|[ \t]*\||[ \t]+[—–-]|[ \t]*$)")
# any line that starts like a claim id: a research.md the strict pattern only partly reads is refused
_CLAIM_LOOSE_RE = re.compile(r"(?m)^[ \t]*(?:#{1,6}[ \t]*|[-*+][ \t]+|[0-9]+[.)][ \t]+|\|[ \t]*)?(?:\*\*|__)?\[?"
                             r"(?:Claim[ \t]+)?C([0-9]+)(?![0-9A-Za-z_])")
CLAIM_FORMAT = "each claim starts a line with its id and a mark: `**C3.** …`, `C3: …`, `| C3 | … |`"


def research_claim_ids(root, tid):
    try:
        with open(os.path.join(root, work_rel(tid, "research.md")), encoding="utf-8") as f:
            return sorted({"C%s" % m for m in _CLAIM_DEF_RE.findall(f.read())}, key=lambda c: int(c[1:]))
    except OSError:
        return []


# a claim's own `withdrawn:` line (research fix, `atoms/_stages.md`): at the head of a line inside the
# claim's block, after spaces, a list mark or emphasis (`- **withdrawn:** …`, `*withdrawn*: …`)
_WITHDRAWN_RE = re.compile(r"(?mi)^[ \t]*(?:[-*+][ \t]+|[0-9]+[.)][ \t]+)?(?:\*\*|__|\*|_)?withdrawn(?:\*\*|__|\*|_)?[ \t]*:")


_WITHDRAWN_INLINE_RE = re.compile(r"(?i)(?:^|[\s|(—–-])(?:\*\*|__|\*|_)?withdrawn(?:\*\*|__|\*|_)?[ \t]*:")


def research_withdrawn_ids(root, tid):
    """Claims marked withdrawn (13 §R2-3, §R3-3): a block runs from a claim's definition line to the
    line before the next definition."""
    try:
        with open(os.path.join(root, work_rel(tid, "research.md")), encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return []
    defs = list(_CLAIM_DEF_RE.finditer(text))
    out = set()
    for i, m in enumerate(defs):
        end = defs[i + 1].start() if i + 1 < len(defs) else len(text)
        nl = text.find("\n", m.end())
        nl = end if nl < 0 or nl > end else nl
        # on the definition line itself (a one-line claim, a table row) anywhere after the id; below it
        # at the head of a line (review 28 m9)
        if _WITHDRAWN_INLINE_RE.search(text[m.end():nl]) or _WITHDRAWN_RE.search(text[nl:end]):
            out.add("C%s" % m.group(1))
    return sorted(out, key=lambda c: int(c[1:]))


def current_verify(root, cfg, tid, st):
    """verify.json when it evaluates the current bundle, else {}."""
    ver = safe_machine(root, tid, "verify.json")
    if not st.get("slug") or not ver.get("body_hash") or ver["body_hash"] != bundle_hash(root, cfg, st["slug"]):
        return {}
    return ver


def research_suspects(ver):
    """Claim ids the fact-checker listed as wrong in research.md (`research_suspects`). A
    malformed list is refused: reading it as "none" would switch the research route off."""
    raw = (ver or {}).get("research_suspects")
    if raw in (None, []):
        return []
    ok = isinstance(raw, list) and all(isinstance(x, dict) and isinstance(x.get("claim"), str)
                                       and re.fullmatch(r"C[0-9]+", x["claim"].strip()) for x in raw)
    if not ok:
        raise HeraldError('verify.json research_suspects is malformed — a list of {"claim": "C<n>", "reason": "…", '
                          '"sentences": […]}')
    return [x["claim"].strip() for x in raw]


def accuracy_gap(ver):
    """A current verify result the accuracy reserve may answer: a contradicted sentence, or a
    research claim the fact-checker found wrong."""
    c = (ver or {}).get("counts") or {}
    return _int(c.get("contradicted")) > 0 or bool(research_suspects(ver))


def open_research_fix(st):
    fixes = st.get("research_fixes") or []
    return fixes[-1] if fixes and isinstance(fixes[-1], dict) and fixes[-1].get("status") == "open" else None


def research_fix_claims(root, cfg, tid, st, claims):
    """Validate `loopback --cause research --claims`: each id is one the fact-checker listed in
    the current verify.json `research_suspects` and exists in research.md."""
    ver = current_verify(root, cfg, tid, st)
    suspects = research_suspects(ver)
    if not suspects:
        raise HeraldError("the current verify.json lists no research_suspects — a research fix starts from the "
                          "fact-checker's finding on this article (run verify first)")
    want = sorted({c.strip() for c in (claims or "").split(",") if c.strip()})
    if set(want) != set(suspects):
        raise HeraldError("--claims must name exactly the suspects verify.json lists: --claims %s"
                          % ",".join(sorted(set(suspects), key=lambda c: int(c[1:]))))
    last = (st.get("research_fixes") or [None])[-1]
    if isinstance(last, dict) and last.get("verify_blob") and last["verify_blob"] == _verify_blob(root, tid):
        raise HeraldError("this verify.json was already answered by a research fix — the same finding again: "
                          "hold `stagnation` (contract §F)")
    have = research_claim_ids(root, tid)
    missing = [c for c in want if c not in have]
    if missing:
        raise HeraldError("%s not found as a claim in research.md (%s)" % (", ".join(missing), CLAIM_FORMAT))
    again = sorted({c for f in st.get("research_fixes") or [] if isinstance(f, dict) and f.get("status") == "done"
                    for c in f.get("claims") or []} & set(want), key=lambda c: int(c[1:]))
    if again:
        raise HeraldError("%s already went through a research fix — the same finding again: hold `stagnation` "
                          "(contract §F); a deferred auditor pointer is not passed again once its claim was "
                          "rechecked" % ", ".join(again))
    return sorted(set(want), key=lambda c: int(c[1:])), have


def _verify_blob(root, tid):
    return file_hash(root, work_rel(tid, "verify.json"))


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


def record_gate_failure(root, st, tid, stage, gate, amend=False, lang=None):
    """Not on `verify --amend` or after a human-requested revision (the failing edit is a
    human's), and once per topic and loopback count (retries of one draft are one event)."""
    n = int(st.get("loopbacks", 0))
    attempt = st.get("created_at")  # a requeued topic starts a new state (loopbacks 0 again)
    try:
        # translation failures are keyed per stage and language too (several languages can fail
        # in one round); draft/critique keep the 0.8.0 key (01-multilingual.md §4)
        seen = any(isinstance(r, dict) and r.get("kind") == "gate-failure" and r.get("topic_id") == tid
                   and isinstance(r.get("data"), dict) and r["data"].get("loopbacks") == n
                   and r["data"].get("attempt") == attempt
                   and (stage != "translation" or (r["data"].get("stage"), r["data"].get("lang")) == (stage, lang))
                   for r in read_jsonl(paths(root)["signals"]))
    except Exception:  # noqa: BLE001 — never hide the gate error behind a signal problem
        seen = True
    if not amend and st.get("last_loopback") != "human" and not seen:
        data = {"stage": stage, "errors": gate["errors"][:10], "loopbacks": n, "attempt": attempt}
        if lang:
            data["lang"] = lang
        safe_signal(root, "gate-failure", tid, data)


def _repass_refusal(root, tid, st, stage, rerun):
    """12 §R3-M1 (§R2-M1 rule 1 narrowed): brief and research — what a stand-in rests on — pass
    again only on a research fix or a human's `--rerun` (refused unattended and in a `--ship` run
    here, in code — the guard only asks, §R4-m2). draft, critique, translation, verify (`--amend`
    too) and publish are as in 0.20.0."""
    if rerun:  # whatever it re-passes — the flag itself lifts the fixed candidates (review 26 M3)
        if os.environ.get("HRD_UNATTENDED") == "1":
            return "--rerun is a human's decision — not in unattended sessions"
        from . import lock
        if lock.ship_active(root, tid):
            return "--rerun is a human's decision — not in a `--ship` run"
    if not _is_repass(st, stage):
        return None
    if not rerun:
        return ("%s passed already (the topic is at %s) — a human reruns it with `/hrd %s` (`--rerun`)"
                % (stage, st["stage"], stage))
    return None


def _is_repass(st, stage):
    """brief or research passing again behind the topic's stage, outside a research fix."""
    if stage not in ("brief", "research") or st.get("stage") not in ORDER or \
            ORDER.index(stage) >= ORDER.index(st["stage"]):
        return False
    return not (stage == "research" and open_research_fix(st))


def _orphaned(root, tid, st):
    """After a brief rerun: a human's place record no line of the new brief has (12 §R2-M1)."""
    from .stand_in import places
    keys = {p["place"] for p in places(root, tid, st) or []}
    recs = [r for r in st.get("image_rejects") or [] if isinstance(r, dict) and r.get("drop") and not r.get("by")]
    recs += [r for r in st.get("stand_in_refused") or [] if isinstance(r, dict)]
    return any(r.get("place") and r["place"] not in keys for r in recs)


def stage_pass(root, cfg, tid, stage, amend=False, rerun=False):
    st = load_state(root, tid)
    if stage not in PRODUCES:
        raise HeraldError("unknown stage %s" % stage)
    why = _repass_refusal(root, tid, st, stage, rerun)
    if why:
        raise HeraldError(why)
    rerun = rerun and _is_repass(st, stage)  # only a real re-pass lifts what a re-pass may change
    if open_trim(st):
        raise HeraldError("a trim is open — `HRD trim --topic %s --finish` or `--abort` first" % tid)
    if stage != "research" and open_research_fix(st):
        raise HeraldError("a research fix is open (%s) — the researcher corrects those claims and `stage pass --stage "
                          "research` runs first" % ", ".join(open_research_fix(st).get("claims") or []))
    if stage == "translation":
        from . import translation
        problems = entry_check(root, cfg, st, stage)
        if problems:
            raise HeraldError("; ".join(problems))
        return translation.stage_pass(root, cfg, tid, st, run_gate, lambda s: save_state(root, tid, s),
                                      record_gate_failure)
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
    fix = open_research_fix(st) if stage == "research" else None
    if stage == "research":
        ids = research_claim_ids(root, tid)
        if not ids:
            raise HeraldError("research.md has no claim the tools can find — %s" % CLAIM_FORMAT)
        try:
            with open(os.path.join(root, work_rel(tid, "research.md")), encoding="utf-8") as f:
                loose = {"C%s" % m for m in _CLAIM_LOOSE_RE.findall(f.read())}
        except OSError:
            loose = set()
        odd = sorted(loose - set(ids), key=lambda c: int(c[1:]))
        if odd and not fix:  # a fix keeps the file's layout; the first pass sets it
            raise HeraldError("research.md lines start with %s in a form the tools cannot read as a claim — %s "
                              "(an excerpt line starting with an id: rewrap it)" % (", ".join(odd[:5]), CLAIM_FORMAT))
    if fix and fix.get("research_before") and fix["research_before"] == artifact_hash(root, cfg, st, "research.md"):
        raise HeraldError("research.md is unchanged since the research fix opened — the researcher marks each listed "
                          "claim corrected:, rechecked: or withdrawn:")
    if stage == "research":  # 12 §R2-M1 rule 3, §R4-m3: the image candidates are fixed at the first pass
        from .stand_in import candidates_hash
        try:
            with open(os.path.join(root, work_rel(tid, "research.md")), encoding="utf-8") as f:
                ch = candidates_hash(f.read())
        except OSError:
            ch = None
        if st.get("candidates_hash") and ch != st["candidates_hash"] and not rerun:
            raise HeraldError("image candidates are fixed after the first research pass — a research fix corrects "
                              "claims only (put `## Image candidates` back as it was)")
        if ch:
            st["candidates_hash"] = ch
    if fix:
        # a correction rewrites the listed claims in place: no claim id disappears or is renumbered
        gone = [c for c in fix.get("ids_before") or [] if c not in research_claim_ids(root, tid)]
        if gone:
            raise HeraldError("research.md lost claim ids %s — correct the listed claims in place, append new ones, "
                              "never delete or renumber" % ", ".join(gone))
        fix["status"] = "done"
        fix["done_at"] = now_iso()
    if stage == "draft":
        from .shots import draft_problems
        problems = draft_problems(root, cfg, tid, st)
        gone, n = unplaced_entries(root, cfg, tid, st["slug"])
        if len(gone) > unplaced_bound(n):  # 15 D1 bound (review 2): an unmatched map would switch coverage off
            problems.append("claims-map.json has %d of %d entries with no place of their own in the article (at most %d) "
                            "— copy each map text from the article as it stands, e.g. %r"
                            % (len(gone), n, unplaced_bound(n), gone[0][:80]))
        from .images import draft_problems as image_problems, label_problems
        problems += image_problems(root, cfg, tid, st)  # diagrams, external images, OG (08-images.md §2.10)
        problems += label_problems(root, cfg, tid, st)  # every scene of the slug keeps its AI label (09 §2.8)
        if problems:  # every listed screenshot in place before the gate (design 06 §2.7)
            raise HeraldError("; ".join(problems))
    if stage == "draft" or (stage == "verify" and amend):
        gate = run_gate(root, cfg, st["slug"])
        if stage == "draft":
            write_prose(root, cfg, tid, st["slug"], gate)
            if cfg.translations():  # the correspondence filter needs every map text in the body
                from .translation import draft_text_problems
                missing = draft_text_problems(root, cfg, tid, st["slug"])
                if missing:
                    gate = dict(gate, ok=False, errors=list(gate.get("errors") or []) + missing)
        if not gate["ok"]:
            record_gate_failure(root, st, tid, stage, gate, amend)
            raise HeraldError("deterministic gate failed: %s" % "; ".join(gate["errors"][:5]))
        if stage == "verify" and amend:
            from .translation import amend_problems
            problems = amend_problems(root, cfg, tid, st, run_gate)
            if problems:
                raise HeraldError("re-verify of a translation failed: %s" % "; ".join(problems[:4]))
    if stage in ("critique", "verify"):
        # The verdict file must evaluate THIS article: the main session writes the hash it
        # got from `HRD hash` before spawning into the file, and a verdict file carried over
        # unchanged from an earlier pass cannot vouch for a changed body (plan §3.2). Critique
        # evaluated the source, verify the bundle (01-multilingual.md §3).
        cur = worktree_hash(root, cfg, st["slug"]) if stage == "critique" else bundle_hash(root, cfg, st["slug"])
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
        problems = audit_log_problems(crit, rounds, root, cfg, tid)
        if problems:
            raise HeraldError("; ".join(problems))
        if not critique_passed(crit):
            raise HeraldError("critique.json does not record a PASS with no BLOCKER/MAJOR left open "
                              "(dismissed, a MAJOR deferred on a recheck round, or on a refresh out of scope)")
        if reader_blockers(root, cfg, tid, st):
            raise HeraldError(_reader_pass_refusal(st, "before this pass"))
        rec["body_hash"] = worktree_hash(root, cfg, st["slug"])
        # git blob ids too: a PR head is compared by blob, which line-ending filters keep equal
        rec["blobs"] = {n: _git_blob(root, None, work_rel(tid, n)) for n in ("critique.md", "critique.json")}
        for tr in trims_of(st):  # an old `trim` dict is updated in place
            if tr.get("status") == "done" and tr.get("hash") != rec["body_hash"]:
                tr["status"] = "superseded"  # a fresh critique evaluated a later body: the trim is history
        # dismissals are recorded from the decision log, not from memory (abuse watch, auditor
        # prompt material); also on audit loopbacks, so a topic that never passes keeps them
        record_dismissals(root, tid, crit)
        record_out_of_scope(root, tid, crit)
    if stage == "verify":
        ver = load_machine(root, tid, "verify.json")
        if research_suspects(ver):
            raise HeraldError("verify.json lists research_suspects — a claim the article rests on is wrong; "
                              "`HRD loopback --cause research` first")
        cov = verify_coverage(root, cfg, tid, st, ver)
        if cov["problems"]:
            raise HeraldError("; ".join(cov["problems"][:4]))
        if not verify_passed(ver):
            raise HeraldError("verify.json has unsupported or contradicted claims")
        from .translation import lang_record, verify_problems
        problems = verify_problems(root, cfg, st, ver)
        from .images import label_problems, verify_problems as image_problems
        problems += image_problems(root, cfg, tid, st, ver, amend=amend)  # drawn diagram text (08-images.md §2.12)
        problems += label_problems(root, cfg, tid, st)  # outside run_gate, `--amend` too (09 §2.8)
        if problems:
            raise HeraldError("; ".join(problems))
        bh = bundle_hash(root, cfg, st["slug"])
        rec["body_hash"] = bh
        rec["blobs"] = {"verify.json": _git_blob(root, None, work_rel(tid, "verify.json"))}
        if cov["unplaced"]:  # map entries with no place in the body: shown in the PR, never refused (15 D1)
            rec["unplaced"] = [t[:200] for t in cov["unplaced"]][:20]
            n = sum(len(p.get("spans") or {}) for p in cov["parts"].values())
            if len(cov["unplaced"]) > unplaced_bound(n):  # draft enforced it; a later map change only warns
                rec["unplaced_warning"] = "%d of %d claims-map entries have no place in the article (bound %d)" \
                    % (len(cov["unplaced"]), n, unplaced_bound(n))
        rec["research"] = artifact_hash(root, cfg, st, "research.md")  # the evidence it checked against
        st["verified_hash"] = bh
        last = (trims_of(st) or [{}])[-1]
        if last.get("status") == "done":  # its re-verify passed: nothing left to revert
            import shutil
            shutil.rmtree(_trim_dir(root, tid), ignore_errors=True)
        # what was verified, file by file: integrity's cause basis on a machine without a ledger
        # line (01-multilingual.md §3, basis 3)
        if cfg.translations():
            st["verified_files"] = bundle_files(root, cfg, st["slug"])
        if amend and st.get("candidates_hash"):  # 12 §R3-m2: before research.md is anchored again
            from .stand_in import candidates_hash
            try:
                with open(os.path.join(root, work_rel(tid, "research.md")), encoding="utf-8") as f:
                    ch = candidates_hash(f.read())
            except OSError:
                ch = None
            if ch != st["candidates_hash"]:
                raise HeraldError("image candidates are fixed — the delta research may change claims only")
        if amend:
            # delta research rewrote research.md / claims-map.json: re-anchor their producers
            for producer, name in (("research", "research.md"), ("draft", "claims-map.json")):
                st["stages"].setdefault(producer, {}).setdefault("outputs", {})[name] = artifact_hash(root, cfg, st, name)
            tr = st.get("translation") or {}
            if tr.get("langs"):  # a re-verified human edit to a translation becomes its new record
                tr["hashes"] = {l: lang_record(root, cfg, tid, st["slug"], l) for l in tr["langs"]}
                st["stages"].setdefault("translation", {}).setdefault("outputs", {})["@translations"] = \
                    artifact_hash(root, cfg, st, "@translations")
    st["stages"][stage] = rec
    if stage == "brief" and rerun:
        if _orphaned(root, tid, st):
            st["stand_in_orphaned"] = True  # the whole topic goes without stand-ins (12 §R2-M1)
        # a new brief has new place keys: the research that follows fixes its candidates anew (review 26 M4)
        st.pop("candidates_hash", None)
    if stage == "draft":
        st.pop("human_loopback", None)  # 12 §R2-M3: the human loopback ends with the draft that passes
    nxt = ORDER[ORDER.index(stage) + 1]
    if stage == "critique":
        from .translation import on_critique_pass
        nxt = on_critique_pass(st, rec["body_hash"])
    st["stage"] = nxt
    if stage == "draft" and st.get("screenshots"):
        st["screenshots"]["awaiting"] = False
    if stage == "draft" and st.get("images"):
        st["images"]["awaiting"] = False
    save_state(root, tid, st)
    if stage == "draft":
        from .shots import archive_inbox
        archive_inbox(root, tid, "imported")  # the branch holds the cleaned files now
    return st


# --- trim: the uncounted repair of a late verify gap (contract §F, 15 D2) --------------------

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


def _image_ref_re():
    from .validate import IMG_RE
    return IMG_RE


_IMG_REF_RE = _image_ref_re()


def _protected(text):
    return [(m.start(), m.end()) for m in _PROTECTED_RE.finditer(text)]


# --- verify coverage: a verdict for every claims-map entry (15 D1, 0.24.0) --------------------

VERDICTS = ("supported", "unsupported", "contradicted", "not-factual")
_SENT_END_RE = re.compile(r"[.!?。！？][%s]*(?=\s|$)" % _CLOSERS)
# translation.normalize, step by step, so a match in its space maps back to the raw body
_NORM_STEPS = ((re.compile(r"!\[[^\]]*\]\([^)]*\)"), " "), (re.compile(r"\[([^\]]*)\]\([^)]*\)"), 1),
               (re.compile(r"<[^>]+>"), " "), (re.compile(r"[*_`~]+"), ""),
               (re.compile(r"^[ \t]*(?:[-+>]|#{1,6}|\d+[.)])[ \t]+", re.M), ""), (re.compile(r"\s+"), " "))


def _occurrences(text, part, lo=0):
    out, i = [], text.find(part, lo) if part else -1
    while i != -1:
        out.append((i, i + len(part)))
        i = text.find(part, i + 1)
    return out


def _norm_tracked(text, lo=0):
    """translation.normalize(text[lo:]) and, for each of its characters, the raw offset it came from."""
    s, pos = text[lo:], list(range(lo, len(text)))
    for rx, rep in _NORM_STEPS:
        out, opos, last = [], [], 0
        for m in rx.finditer(s):
            out.append(s[last:m.start()])
            opos += pos[last:m.start()]
            if rep == 1:
                out.append(m.group(1))
                opos += pos[m.start(1):m.end(1)]
            else:
                out.append(rep)
                opos += [pos[m.start()]] * len(rep)
            last = m.end()
        out.append(s[last:])
        opos += pos[last:]
        s, pos = "".join(out), opos
    a, b = len(s) - len(s.lstrip()), len(s.rstrip())
    return s[a:b], pos[a:b]


class _Body:
    """Where a text lies in the body (from `lo`: frontmatter excluded): verbatim, and — the
    writer's map is markdown-insensitive in places (ruby, emphasis, links) — in
    translation.normalize space, mapped back to raw offsets; a normalised hit no verbatim hit
    covers is one more occurrence (a sentence written once plain and once with emphasis is
    repeated, not single)."""

    def __init__(self, text, lo):
        self.text, self.lo, self._n = text, lo, None

    def find(self, part):
        occ = _occurrences(self.text, part, self.lo)
        from .translation import normalize
        npart = normalize(part) if part else ""
        if not npart:
            return occ
        if self._n is None:
            self._n = _norm_tracked(self.text, self.lo)
        ns, pos = self._n
        more = [(pos[a], pos[b - 1] + 1) for a, b in _occurrences(ns, npart)]
        return sorted(occ + [sp for sp in more if not _overlaps([sp], occ)])


def map_spans(text, lo, texts, body=None):
    """Each map text's spans in the body, longest entry first and exclusively: an occurrence
    inside a longer entry's assigned span belongs to that entry (t0010: a table cell copied
    inside a later sentence)."""
    body = body or _Body(text, lo)
    assigned, out = [], {}
    for t in sorted(set(texts), key=len, reverse=True):
        occ = [(a, b) for a, b in body.find(t) if not any(x <= a and b <= y for x, y in assigned)]
        out[t] = occ
        assigned.extend(occ)
    return out


def _overlaps(spans, others):
    return any(a < y and x < b for a, b in spans for x, y in others)


def coverage(text, lo, entries, rec, framings=None, where="verify.json"):
    """D1 on one body and its claims map. `problems`: what this verify.json gets wrong (a missing
    or malformed verdict, a listed text not unique, counts). `unplaced`: map entries with no span
    of their own — not in the body (the frontmatter, a paraphrase), or only inside a longer entry —
    need no verdict, and a verdict on one is ignored (information for the PR, never a refusal).
    `spans`/`dup`/`listed`: what the trim reads (D2)."""
    out = {"problems": [], "unplaced": [], "dup": set(), "spans": {}, "listed": {}}
    p = out["problems"]
    texts = [t for t in entries if t]
    body = _Body(text, lo)
    spans = map_spans(text, lo, texts, body)
    out["spans"] = spans
    out["dup"] = {t for t, sp in spans.items() if len(sp) > 1}
    own = {t: sp for t, sp in spans.items() if sp}
    out["unplaced"] = sorted(t for t in spans if not spans[t])
    vs = (rec or {}).get("verdicts")
    if not isinstance(vs, list):
        p.append("%s has no `verdicts` list — one per claims-map entry (0.24.0; a verify.json made before it: run "
                 "verify again)" % where)
        return out
    cov = {}
    n = {k: 0 for k in VERDICTS}
    unmapped, uns_texts = 0, []
    cover = {str(c).strip() for f in framings or [] if isinstance(f, dict) for c in f.get("covers") or []}

    def resolve(t):
        if own.get(t):
            return own[t]
        occ = body.find(t)
        if len(occ) != 1:
            p.append("%s: %r is found %d times in the article (a listed text is unique, or equals a map entry that "
                     "is itself repeated)" % (where, t[:80], len(occ)))
            return None
        return occ

    for v in vs:
        if not (isinstance(v, dict) and isinstance(v.get("text"), str) and v["text"].strip()
                and v.get("verdict") in VERDICTS and isinstance(v.get("claims", []), list)):
            p.append('%s verdicts entry is malformed — {"text": "<verbatim>", "verdict": "%s", "claims": ["C1"], '
                     '"why": "…"}' % (where, "|".join(VERDICTS)))
            continue
        t, kind = v["text"].strip(), v["verdict"]
        if kind != "supported" and not str(v.get("why") or "").strip():
            p.append("%s: the %s verdict on %r needs its one-line `why`" % (where, kind, t[:80]))
        n[kind] += 1
        if kind == "unsupported":
            uns_texts.append(t)
        if t in spans and not spans[t]:
            continue  # an unplaced entry: its verdict is counted, not placed
        sp = resolve(t)
        if sp is None:
            continue
        out["listed"][t] = sp
        marked = [e for e, es in own.items() if _overlaps(sp, es)]
        if not marked:  # outside the map: the checker found a factual text the writer did not map
            if kind != "unsupported":
                p.append("%s: %r is in no claims-map entry — an unmapped factual text is `unsupported` (and counted "
                         "in `unmapped`)" % (where, t[:80]))
            unmapped += 1
        for e in marked:
            cov.setdefault(e, []).append(kind)
            if kind == "not-factual" and _SENT_END_RE.search(e) and e not in cover and t not in cover:
                p.append("%s: %r is a mapped sentence judged not-factual without a framing covering it — only a "
                         "label or table header (no sentence end) is, else `framings[].covers` names it" % (where, e[:80]))
    for e in sorted(own, key=lambda x: own[x][0]):
        if e not in cov:
            p.append("%s has no verdict for the claims-map entry %r" % (where, e[:80]))
    c = (rec or {}).get("counts")
    c = c if isinstance(c, dict) else {}
    want = {"supported": n["supported"], "unsupported": n["unsupported"], "contradicted": n["contradicted"],
            "unmapped": unmapped}
    bad = ["%s %s ≠ %d" % (k, c.get(k), x) for k, x in want.items() if _int(c.get(k)) != x]
    if bad:
        p.append("%s counts do not follow its verdicts (%s)" % (where, ", ".join(bad)))
    listed = (rec or {}).get("unsupported_sentences") or []
    if not isinstance(listed, list) or sorted(str(x).strip() for x in listed) != sorted(uns_texts):
        p.append("%s unsupported_sentences must be exactly the texts of its unsupported verdicts" % where)
    return out


def _map_texts(root, tid, map_rel):
    """The `text` of every claims-map entry, or None when the map is missing; [] when unreadable."""
    mp = os.path.join(root, work_rel(tid, map_rel))
    if not os.path.isfile(mp):
        return None
    cm = read_json(mp)
    sents = cm.get("sentences") if isinstance(cm, dict) else None
    return [str(e.get("text") or "").strip() for e in sents or [] if isinstance(e, dict)]


UNPLACED_MIN = 3  # unplaced map entries tolerated: max(3, 10% of the entries) — more is a map that does not match


def unplaced_bound(n):
    return max(UNPLACED_MIN, n // 10)


def unplaced_entries(root, cfg, tid, slug):
    """(map texts not in the body at all, number of distinct entries) for the source body and
    claims-map.json — the bound's count. An entry found only inside a longer entry (a table cell
    copied into a sentence) has a place in the article: it is `unplaced` for coverage, not here."""
    texts = [t for t in dict.fromkeys(_map_texts(root, tid, "claims-map.json") or []) if t]
    try:
        with open(os.path.join(root, cfg.body_path(slug)), encoding="utf-8", newline="") as f:
            text = f.read()
    except (OSError, UnicodeDecodeError):
        return [], len(texts)
    lo = _body_start(text)
    if not texts or lo is None:
        return [], len(texts)
    body = _Body(text, lo)
    return [t for t in texts if not body.find(t)], len(texts)


def map_text_warnings(root, cfg, tid, slug):
    """Map texts with no place in the source body (verbatim or markdown-insensitive): the
    writer fixes them in its own pass — a warning up to `unplaced_bound`, beyond it `stage pass
    --stage draft` refuses (an unbounded `unplaced` would switch D1 off)."""
    gone, _ = unplaced_entries(root, cfg, tid, slug)
    return ["claims-map.json text with no place of its own in the article (copy each sentence as it stands): %r"
            % t[:80] for t in gone[:5]]


def verify_coverage(root, cfg, tid, st, ver):
    """D1 for this topic's verify.json: the source body with claims-map.json, or — in a
    translation repo with `by_lang` — each language that has a claims map. A translation repo
    matches markdown-insensitively throughout, as its draft gate does."""
    from . import translation

    out = {"problems": [], "unplaced": [], "parts": {}}
    slug = st.get("slug")
    ver = ver if isinstance(ver, dict) else {}
    if not slug:
        return out
    by = ver.get("by_lang")
    norm = bool(cfg.translations())
    jobs = []
    if norm and isinstance(by, dict):
        for lang in sorted(by):
            lang_arg = None if lang == cfg.source_lang() else lang
            jobs.append((lang, by[lang] if isinstance(by[lang], dict) else {}, cfg.body_path(slug, lang_arg),
                         translation.map_name(lang_arg)))
    else:
        jobs.append((None, ver, cfg.body_path(slug), "claims-map.json"))
    framings = ver.get("framings")
    for lang, rec, body_rel, map_rel in jobs:
        texts = _map_texts(root, tid, map_rel)
        if texts is None:
            continue  # D1 applies where the language has a claims map
        try:
            with open(os.path.join(root, body_rel), encoding="utf-8", newline="") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError):
            continue  # a missing translation file is translation's own refusal
        where = "verify.json" if lang is None else "verify.json by_lang.%s" % lang
        fr = framings
        if norm:
            nz = translation.normalize
            text = nz(translation._FM_RE.sub("", text.replace("\r\n", "\n"), count=1))
            texts = [nz(t) for t in texts]
            vs = rec.get("verdicts")
            rec = dict(rec, verdicts=[dict(v, text=nz(v["text"])) if isinstance(v, dict) and isinstance(v.get("text"), str)
                                      else v for v in vs] if isinstance(vs, list) else vs,
                       unsupported_sentences=[nz(str(x)) for x in rec.get("unsupported_sentences") or []])
            fr = [dict(f, covers=[nz(str(c)) for c in f.get("covers") or []]) for f in framings or []
                  if isinstance(f, dict)]
            lo = 0
        else:
            lo = _body_start(text)
            if lo is None:
                out["problems"].append("the article's frontmatter does not close")
                continue
        part = coverage(text, lo, texts, rec, fr, where)
        out["problems"] += part["problems"]
        out["unplaced"] += part["unplaced"]
        out["parts"][lang] = part
    return out


def _kept_pattern(old, spans, narrow=()):
    """The trimmed body must be the snapshot minus `spans`, byte for byte. At each seam only the
    whitespace the deletion left may change: within a line it may close up to one space or none;
    across lines the line break and indentation before the next kept text stay as they were. Each
    `narrow` span (inside kept text) becomes a group the caller checks (`_narrowing`)."""
    merged = []
    for a, b in sorted(spans):  # deletions separated only by whitespace form one seam
        if merged and not old[merged[-1][1]:a].strip():
            merged[-1][1] = b
        else:
            merged.append([a, b])
    pieces, last = [], 0
    for a, b in merged:
        pieces.append((last, old[last:a]))
        last = b
    pieces.append((last, old[last:]))
    out = []
    for i, (at, p) in enumerate(pieces):
        lead = re.match(r"\s*", p).group(0) if i > 0 else ""
        core = p[len(lead):]
        trail = re.search(r"\s*$", core).group(0) if i < len(pieces) - 1 else ""
        core = core[:len(core) - len(trail)] if trail else core
        out.append((lead, core, trail, at + len(lead)))

    def esc(core, at):
        res, pos = [], at
        for a, b in sorted(narrow):
            if at <= a and b <= at + len(core):
                res += [re.escape(old[pos:a]), "(.*?)"]
                pos = b
        return "".join(res) + re.escape(old[pos:at + len(core)])

    pat = []
    for i, (lead, core, trail, at) in enumerate(out):
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
        pat.append(esc(core, at))
    return re.compile("".join(pat), re.S)


# --- narrowing: whole tokens deleted inside a listed sentence (15 D2.2, 0.24.0) --------------

# a removed token never holds a digit, markup or a link, emphasis, table, quote or title character
_NARROW_BAD_RE = re.compile(r"[\d<>\[\]()`*_~|「」『』“”‘’《》〈〉\"']")
_QUOTATION_RE = re.compile(r"「[^」]*」|『[^』]*』|“[^”]*”|‘[^’]*’|《[^》]*》|〈[^〉]*〉|\"[^\"]*\"")
# negations (15 D2.2, rule of review 1): en as a whole word or a token ending in n't; ko by form —
# 안/못 alone, 못하-/못했-/못한-/못할-, 말고-/말라-/말아-/말자- after a -지 token, or any token holding
# one of _KO_NEG (so 안내, 안전, 주말, 말하는, know, note are no negations)
_EN_NEG_RE = re.compile(r"\b(?:not|no|never|without|cannot|none|nor|neither|nothing|nobody|except|unless|hardly)\b"
                        r"|n['’]t$")
_KO_NEG = ("않", "없", "아니", "아닌", "아님", "아냐", "마세요", "마라", "맙시다")
_TOKEN_PUNCT = ".,!?;:…。、！？"


def _negation(tok, prev=""):
    t = tok.lower().strip(_TOKEN_PUNCT)
    if _EN_NEG_RE.search(t) or any(w in t for w in _KO_NEG) or t in ("안", "못"):
        return True
    if t.startswith(("못하", "못했", "못한", "못할")):
        return True
    return t.startswith(("말고", "말라", "말아", "말자")) and prev.strip(_TOKEN_PUNCT).endswith("지")


NO_SPACE_LANGS = ("ja", "zh")  # written without spaces: delete or map only


def _narrowing(orig, new):
    """`new` is `orig` with whole whitespace-separated tokens removed: (removed tokens, None), or
    (None, why). Single spaces at the seams collapse; no line break is added or removed; the rest
    is non-empty and still ends with its sentence end; a removed token holds no digit, markup,
    quote or emphasis character, lies in no quotation and is no negation."""
    if not new.strip() or new != new.strip():
        return None, "a narrowed text is the listed text with whole words removed, nothing around it"
    if new.count("\n") != orig.count("\n"):
        return None, "a narrowing adds or removes no line break"
    if not re.search(r"[.!?。！？][%s]*$" % _CLOSERS, new):
        return None, "a narrowed sentence still ends with its sentence end"
    parts = re.split(r"(\s+)", orig)
    toks, seps = parts[0::2], parts[1::2]
    starts, pos = [], 0
    for i, t in enumerate(toks):
        starts.append(pos)
        pos += len(t) + (len(seps[i]) if i < len(seps) else 0)
    quotes = [(m.start(), m.end()) for m in _QUOTATION_RE.finditer(orig)]

    def why_not(i):
        t = toks[i]
        if _NARROW_BAD_RE.search(t):
            return "it holds a digit, markup or a quote, emphasis or table character"
        if any(x < starts[i] + len(t) and starts[i] < y for x, y in quotes):
            return "it lies inside a quotation"
        if _negation(t, toks[i - 1] if i else ""):
            return "it is a negation"
        return None

    nparts = re.split(r"(\s+)", new)
    ntoks, nseps = nparts[0::2], nparts[1::2]

    def align(ok):
        import functools

        @functools.lru_cache(None)
        def go(i, j):
            if i == len(ntoks) - 1:
                rest = tuple(range(j + 1, len(toks)))
                return rest if all(ok(k) for k in rest) else None
            for j2 in range(j + 1, len(toks)):
                if toks[j2] != ntoks[i + 1] or not all(ok(k) for k in range(j + 1, j2)):
                    continue
                allowed = {seps[j]} if j2 == j + 1 else set(seps[j:j2]) | {" "}
                if nseps[i] not in allowed:
                    continue
                r = go(i + 1, j2)
                if r is not None:
                    return tuple(range(j + 1, j2)) + r
            return None

        for j0 in range(len(toks)):
            if toks[j0] == ntoks[0] and all(ok(k) for k in range(j0)):
                r = go(0, j0)
                if r is not None:
                    return tuple(range(j0)) + r
        return None

    removed = align(lambda k: why_not(k) is None)
    if removed:
        return [toks[k] for k in removed], None
    shape = align(lambda k: True)
    if not shape:
        return None, "not the listed text with whole words removed"
    bad = [(toks[k], why_not(k)) for k in shape if why_not(k)]
    return None, "a narrowing never removes %r: %s" % bad[0] if bad else "not a narrowing"


# --- trim: begin, finish, abort, revert ------------------------------------------------------

def _gap_key(ver):
    """A verify gap is its listed texts on one body: the same texts again is the same gap."""
    import hashlib

    listed = sorted(str(x).strip() for x in ver.get("unsupported_sentences") or [] if isinstance(x, str))
    return "sha256:" + hashlib.sha256(json.dumps(listed, ensure_ascii=False).encode()).hexdigest()


TRIM_MAX_PER_ARTICLE = 3  # trims per article, an aborted or reverted one included; none counts as a loopback


def trim_begin(root, cfg, tid):
    """Open a trim after a failed verify. The fact-checker lists the unsupported text verbatim —
    whole sentences, or a parenthetical aside when that aside alone is unsupported; the writer
    may then only delete a listed text whole, map it to an existing claim, or narrow it (delete
    whole words inside it — not an aside, a heading, a span narrowed before, nor in a language
    written without spaces). Eligibility is decided here, before any loopback: up to three per
    article, never twice for one gap. The article, claims map, verify result and the hashes
    critique passed are snapshotted."""
    import shutil

    st = load_state(root, tid)
    slug = st.get("slug")
    trs = trims_of(st)
    if open_trim(st):
        raise HeraldError("a trim is open — `HRD trim --topic %s --finish` or `--abort` first" % tid)
    if len(trs) >= TRIM_MAX_PER_ARTICLE:
        raise HeraldError("%s was trimmed %d times already (%s) — loop back or hold"
                          % (tid, len(trs), ", ".join(str(t.get("status")) for t in trs)))
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
    gap = _gap_key(ver)
    tried = [t for t in trs if t.get("base_hash") == cur and t.get("gap", gap) == gap]
    if tried:
        raise HeraldError("a trim was already tried on this verify result (%s) — loop back or hold"
                          % tried[-1].get("status"))
    counts = ver.get("counts") if isinstance(ver.get("counts"), dict) else {}
    con, uns = _int(counts.get("contradicted")), _int(counts.get("unsupported"))
    if con:
        raise HeraldError("a contradicted sentence is never trimmed away — loop back")
    if research_suspects(ver):
        raise HeraldError("verify.json lists research_suspects — the researcher rechecks them first "
                          "(`HRD loopback --cause research --claims …`), never a trim")
    if isinstance(ver.get("images"), dict) and ver["images"].get("unsupported"):
        raise HeraldError("unsupported text in a diagram is never trimmed (trim deletes body sentences only) — "
                          "`HRD loopback --cause verify` (08-images.md §2.12)")
    sents = ver.get("unsupported_sentences")
    if not 1 <= (len(sents) if isinstance(sents, list) else uns) <= TRIM_MAX_UNSUPPORTED:
        raise HeraldError("trim takes 1 to %d listed unsupported texts, not %d — loop back"
                          % (TRIM_MAX_UNSUPPORTED, len(sents) if isinstance(sents, list) else uns))
    if not isinstance(sents, list) or len(sents) != uns or not all(isinstance(x, str) and x.strip() for x in sents):
        raise HeraldError("verify.json must list the %d unsupported sentences verbatim (unsupported_sentences) — "
                          "loop back" % uns)
    if ver.get("unsupported_qualifiers"):
        raise HeraldError("an unsupported warning or limit is never trimmed (deleting it broadens what remains) — "
                          "loop back")
    body_path = os.path.join(root, cfg.body_path(slug))
    with open(body_path, encoding="utf-8", newline="") as f:
        old = f.read()
    b0 = _body_start(old)
    if b0 is None:
        raise HeraldError("the article's frontmatter does not close — loop back")
    prot = _protected(old)
    from .images import snippet_spans
    attribution = snippet_spans(root, cfg, tid, st, old)  # 08-images.md §2.6.5: never cut into one
    narrowed_before = [sp for t in trs for nr in t.get("narrowed") or [] if isinstance(nr, dict)
                       for sp in _occurrences(old, str(nr.get("after") or ""), b0)]
    spaced = str(cfg.source_lang() or "").split("-")[0].lower() not in NO_SPACE_LANGS
    units, taken = [], []
    for text in sents:
        text = text.strip()
        aside = _ASIDE_RE.fullmatch(text) is not None
        hits = [m.start() + b0 for m in re.finditer(re.escape(text), old[b0:])]
        if len(hits) != 1:
            raise HeraldError("unsupported text found %d times in the article body (need exactly once, "
                              "verbatim): %r — loop back" % (len(hits), text[:80]))
        a, b = hits[0], hits[0] + len(text)
        ta = a
        if any(a < y and x < b for x, y in attribution):
            raise HeraldError("%r overlaps an image attribution — loop back (the illustrator fixes the alt)" % text[:80])
        ls = old.rfind("\n", 0, a) + 1
        heading = re.match(r"[ \t]*#{1,6}[ \t]", old[ls:a]) is not None  # a sentence of a heading line
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
            if any(a < m.end() and m.start() < b for m in _IMG_REF_RE.finditer(old)):
                # trim never touches images: deleting the reference would leave the file deployed
                raise HeraldError("%r holds an image reference — loop back" % text[:80])
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
        narrow = spaced and not aside and not heading and not any(ta < y and x < b for x, y in narrowed_before)
        units.append({"text": text, "span": [a, b], "tspan": [ta, b], "aside": aside, "narrow": narrow})
    cov = verify_coverage(root, cfg, tid, st, ver)  # after the texts' own refusals, which say more
    if cov["problems"]:
        raise HeraldError("; ".join(cov["problems"][:4]))
    from .translation import normalize
    dups = {normalize(t) for t in (cov["parts"].get(None) or {}).get("dup", ())}
    dup = [u["text"] for u in units if normalize(u["text"]) in dups]
    if dup:
        raise HeraldError("%r is a claims-map entry repeated in the article — never trimmed; loop back" % dup[0][:80])
    d = _trim_dir(root, tid)
    if os.path.isdir(d):
        shutil.rmtree(d)
    os.makedirs(d)
    shutil.copyfile(body_path, os.path.join(d, "body"))
    for name in ("claims-map.json", "verify.json", "verify.md"):
        src = os.path.join(root, work_rel(tid, name))
        if os.path.isfile(src):
            shutil.copyfile(src, os.path.join(d, name))
    img = os.path.join(root, cfg.image_dir(slug))
    if os.path.isdir(img):
        shutil.copytree(img, os.path.join(d, "images"))
    out = st["stages"].get("draft", {}).get("outputs") or {}
    pre = {"@article": out.get("@article"), "claims-map.json": out.get("claims-map.json"),
           "critique": (st["stages"].get("critique") or {}).get("body_hash")}
    _trims_rw(st).append({"status": "open", "base_hash": cur, "images": _image_hash(root, cfg, slug),
                          "snapshot": file_hash(root, os.path.relpath(os.path.join(d, "body"), root)),
                          "gap": gap, "pre": pre, "unsupported": uns, "sentences": units, "at": now_iso()})
    save_state(root, tid, st)
    # the gap is the writer's, even when no loopback follows
    safe_signal(root, "verify-gap", tid, {"note": "trim", "trim": True, "counts": counts,
                                          "loopback": _int(st.get("loopbacks"))})
    return {"status": "open", "sentences": [u["text"] for u in units], "trim": len(_trims_rw(st)),
            "may_narrow": [u["text"] for u in units if u["narrow"]]}


def _trim_choices(units):
    """Each listed sentence or aside is kept, deleted whole or — where allowed — narrowed:
    (deleted spans, narrowed spans)."""
    import itertools

    opts = [[None, ("del", tuple(u["span"]))] + ([("nar", tuple(u.get("tspan") or u["span"]))]
                                                  if u.get("narrow") else []) for u in units]
    for combo in itertools.product(*opts):
        yield sorted(c[1] for c in combo if c and c[0] == "del"), sorted(c[1] for c in combo if c and c[0] == "nar")


def _claims_map_problems(root, tid, d, units, narrowed=()):
    """The writer may add, change or drop only the claims-map entries of the listed texts (an
    entry whose text contains one, a sentence that lost a listed aside, or one whose listed
    sentence was narrowed)."""
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

    listed = [u["text"] for u in units] + [n["after"] for n in narrowed]
    asides = [u["text"] for u in units if u.get("aside")]
    o, n = entries(old), entries(new)
    shorter = {re.sub(r"[ \t]*" + re.escape(x), "", str(e.get("text", ""))) for e in o for x in asides
               if x in str(e.get("text", ""))}
    shorter |= {str(e.get("text", "")).replace(nr["before"], nr["after"]) for e in o for nr in narrowed
                if nr["before"] in str(e.get("text", ""))}
    ok = set(map(key, o)) & set(map(key, n))
    bad = [e for e in o + n if key(e) not in ok and not any(x in str(e.get("text", "")) for x in listed)
           and str(e.get("text", "")) not in shorter]
    return ["claims-map.json changed outside the listed texts (%s)" % ", ".join(repr(str(e.get("text", ""))[:40])
                                                                       for e in bad[:3])] if bad else []


def _trim_map_in_step(root, tid, removed, narrowed):
    """The claims map follows the trimmed body (review 1 M1): an entry that is a deleted text goes,
    a deleted text inside an entry leaves it, a narrowed text becomes its narrowed form."""
    from .translation import normalize as nz

    rel = work_rel(tid, "claims-map.json")
    cm = read_json(os.path.join(root, rel))
    sents = cm.get("sentences") if isinstance(cm, dict) else None
    if not isinstance(sents, list):
        return
    kept, changed = [], False
    for e in sents:
        t = e.get("text") if isinstance(e, dict) else None
        if isinstance(t, str):
            new = t
            for nr in narrowed:
                if nr["before"] in new:
                    new = new.replace(nr["before"], nr["after"])
                elif nz(nr["before"]) and nz(nr["before"]) in nz(new):  # a markdown-free entry (t0011)
                    new = nz(new).replace(nz(nr["before"]), nz(nr["after"]))
            for x in removed:
                x = re.sub(r"^(?:[-*+]|\d+[.)])[ \t]+", "", x)  # a list item's text, without its mark
                if x and (new.strip() == x or nz(new) == nz(x)):
                    new = ""
                elif x and x in new:
                    new = re.sub(r"[ \t]*" + re.escape(x), "", new, count=1).strip()
                elif nz(x) and nz(x) in nz(new):
                    new = re.sub(r"[ \t]*" + re.escape(nz(x)), "", nz(new), count=1).strip()
            if new != t:
                changed = True
                if not new.strip():
                    continue
                e = dict(e, text=new)
        kept.append(e)
    if changed:
        cm["sentences"] = kept
        write_json(os.path.join(root, rel), cm)


def _trim_open(root, tid):
    st = load_state(root, tid)
    if not open_trim(st):
        raise HeraldError("%s has no open trim (`HRD trim --topic %s --begin` first)" % (tid, tid))
    return st


def trim_finish(root, cfg, tid):
    """Accept the trim only if the body equals the snapshot with each listed text kept, deleted
    whole or narrowed (only the seam whitespace may differ), the images and critique files are
    untouched and the gate passes; then critique's verdict carries over to the shorter body and
    verify runs again on it — in full, with the before/after pairs. The snapshot stays until that
    verify (`--revert`)."""
    st = _trim_open(root, tid)
    _trims_rw(st)
    tr, slug = open_trim(st), st["slug"]
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
    chosen, why = None, []
    for dels, nars in _trim_choices(tr.get("sentences") or []):
        if not dels and not nars:
            if new == old:
                chosen = ([], [])
                break
            continue
        m = _kept_pattern(old, dels, nars).fullmatch(new)
        if not m:
            continue
        narrowed = []
        for (a, b), after in zip(nars, m.groups()):
            removed, reason = _narrowing(old[a:b], after)
            if reason or after == old[a:b]:
                why.append(reason or "")
                break
            narrowed.append({"before": old[a:b], "after": after, "removed": removed})
        else:
            chosen = (dels, narrowed)
            break
    problems = []
    if chosen is None:
        reason = next((w for w in why if w), None)
        problems.append("the body changed beyond deleting listed texts whole or narrowing them" +
                        (" (%s)" % reason if reason else ""))
    crit_out = (st["stages"].get("critique") or {}).get("outputs") or {}
    for name in ("critique.md", "critique.json"):
        if file_hash(root, work_rel(tid, name)) != crit_out.get(name):
            problems.append("%s changed since critique passed" % name)
    problems.extend(_claims_map_problems(root, tid, d, tr.get("sentences") or [], chosen[1] if chosen else ()))
    if _image_hash(root, cfg, slug) != tr.get("images"):
        problems.append("the images changed — a trim touches only the body text")
    if problems:
        raise HeraldError("; ".join(problems) + " (`HRD trim --topic %s --abort` restores the article)" % tid)
    gate = run_gate(root, cfg, slug)
    if not gate["ok"]:
        raise HeraldError("deterministic gate failed on the trimmed body: %s (`HRD trim --topic %s --abort` "
                          "restores the article)" % ("; ".join(gate["errors"][:5]), tid))
    _trim_map_in_step(root, tid, [old[a:b].strip() for a, b in chosen[0]], chosen[1])
    cur = worktree_hash(root, cfg, slug)
    out = st["stages"].setdefault("draft", {}).setdefault("outputs", {})
    out["@article"] = cur
    out["claims-map.json"] = file_hash(root, work_rel(tid, "claims-map.json"))
    st["stages"].setdefault("critique", {})["body_hash"] = cur  # critique's verdict covers the shorter body
    tr.update({"status": "done", "hash": cur, "removed": [old[a:b].strip() for a, b in chosen[0]],
               "narrowed": chosen[1], "done_at": now_iso()})
    save_state(root, tid, st)
    return tr


def trim_abort(root, cfg, tid, force=False):
    """Put back the article, claims map and images critique passed; the trim stays counted. With
    `force` and the snapshot gone (it is local), only close the trim: the article then differs
    from what critique passed, so the entry checks send it back through draft."""
    import shutil

    st = _trim_open(root, tid)
    _trims_rw(st)
    tr = open_trim(st)
    d = _trim_dir(root, tid)
    body = os.path.join(d, "body")
    if not os.path.isfile(body):
        if not force:
            raise HeraldError("the trim snapshot is gone (%s) — `HRD trim --topic %s --abort --force` closes the "
                              "trim; then loop back" % (d, tid))
        tr.update({"status": "aborted", "done_at": now_iso(), "note": "snapshot lost"})
        save_state(root, tid, st)
        return {"restored": False, "trim": tr}
    slug = st["slug"]
    shutil.copyfile(body, os.path.join(root, cfg.body_path(slug)))
    if os.path.isfile(os.path.join(d, "claims-map.json")):
        shutil.copyfile(os.path.join(d, "claims-map.json"), os.path.join(root, work_rel(tid, "claims-map.json")))
    img = os.path.join(root, cfg.image_dir(slug))
    if _image_hash(root, cfg, slug) != tr.get("images"):
        if os.path.isdir(img):
            shutil.rmtree(img)
        if os.path.isdir(os.path.join(d, "images")):
            shutil.copytree(os.path.join(d, "images"), img)
    if worktree_hash(root, cfg, slug) != tr.get("base_hash"):
        raise HeraldError("could not restore the article critique passed (snapshot kept in %s)" % d)
    tr.update({"status": "aborted", "done_at": now_iso()})
    save_state(root, tid, st)
    shutil.rmtree(d, ignore_errors=True)
    return {"restored": True, "trim": tr}


def trim_revert(root, cfg, tid, force=False):
    """15 D2.3: the re-verify judged a narrowed text `contradicted` → put back the pre-trim
    article, claims map, verify result and hashes, so the normal routes act on that gap (a
    loopback, or a hold at exhaustion). The trim stays counted and this gap is never trimmed
    again. With `force` and the snapshot gone (local, gitignored): only mark it reverted — the
    caller holds `needs-human`."""
    import shutil

    st = load_state(root, tid)
    trs = _trims_rw(st)
    tr = trs[-1] if trs else {}
    slug = st.get("slug")
    if tr.get("status") != "done" or st.get("stage") != "verify" or not slug:
        raise HeraldError("--revert undoes the last trim while its re-verify is current (last trim: %s, stage %s)"
                          % (tr.get("status") or "none", st.get("stage")))
    cur = worktree_hash(root, cfg, slug)
    ver = load_machine(root, tid, "verify.json") or {}
    if cur != tr.get("hash") or ver.get("body_hash") != cur:
        raise HeraldError("--revert needs the trimmed article and its re-verify (verify.json evaluating it) — "
                          "run verify first, or the article changed since")
    contra = [v["text"].strip() for v in ver.get("verdicts") or [] if isinstance(v, dict)
              and v.get("verdict") == "contradicted" and isinstance(v.get("text"), str) and v["text"].strip()]
    with open(os.path.join(root, cfg.body_path(slug)), encoding="utf-8", newline="") as f:
        body = f.read()
    after = [sp for nr in tr.get("narrowed") or [] if isinstance(nr, dict)
             for sp in _occurrences(body, str(nr.get("after") or ""))]
    if not any(_overlaps(_occurrences(body, t), after) for t in contra):
        raise HeraldError("--revert undoes a narrowing the re-verify judged contradicted — no narrowed text is "
                          "contradicted here; the normal routes go on")
    d = _trim_dir(root, tid)
    snap = os.path.join(d, "body")
    if file_hash(root, os.path.relpath(snap, root)) != tr.get("snapshot"):
        if not force:
            raise HeraldError("the trim snapshot is gone or changed (%s) — `HRD trim --topic %s --revert --force` "
                              "marks the trim reverted; then hold needs-human" % (d, tid))
        tr.update({"status": "reverted", "reverted_at": now_iso(), "note": "snapshot lost"})
        save_state(root, tid, st)
        return {"restored": False, "hold": "needs-human", "trim": tr}
    shutil.copyfile(snap, os.path.join(root, cfg.body_path(slug)))
    for name in ("claims-map.json", "verify.json", "verify.md"):
        if os.path.isfile(os.path.join(d, name)):
            shutil.copyfile(os.path.join(d, name), os.path.join(root, work_rel(tid, name)))
    if worktree_hash(root, cfg, slug) != tr.get("base_hash"):
        raise HeraldError("could not restore the pre-trim article (snapshot kept in %s)" % d)
    pre = tr.get("pre") or {}
    out = st["stages"].setdefault("draft", {}).setdefault("outputs", {})
    for name in ("@article", "claims-map.json"):
        if pre.get(name):
            out[name] = pre[name]
    if pre.get("critique"):
        st["stages"].setdefault("critique", {})["body_hash"] = pre["critique"]
    tr.update({"status": "reverted", "reverted_at": now_iso()})
    save_state(root, tid, st)
    shutil.rmtree(d, ignore_errors=True)
    return {"restored": True, "trim": tr}


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
    cur = bundle_hash(root, cfg, st["slug"], rev=rev)
    vb = st.get("stages", {}).get("verify", {}).get("body_hash")
    if kind == "withdraw-lang" and not rev:
        st_head = read_json_at(root, "HEAD", work_rel(tid, "state.json"))
        if st_head != read_json(state_path(root, tid)):
            raise HeraldError("refusing: work/%s/state.json differs from HEAD — commit what `withdraw-lang` wrote first" % tid)
    if kind == "withdraw-lang" and rev and git_rev(root, rev) != git_rev(root, "HEAD"):
        raise HeraldError("refusing: a withdraw-lang record describes HEAD — no other --rev")
    if kind == "withdraw-lang":
        # a translation taken down: proved again here, file by file and on the committed tree,
        # against this machine's last ledger line — only that language's file left the verified
        # bundle; without a line here, the committed record at trust grade (01-multilingual.md §5)
        if os.environ.get("HRD_UNATTENDED") == "1":
            raise HeraldError("refusing: withdraw-lang records need a human (attended only)")
        if not rev and bundle_hash(root, cfg, st["slug"]) != bundle_hash(root, cfg, st["slug"], rev="HEAD"):
            raise HeraldError("refusing: the bundle has uncommitted changes — the record describes HEAD")
        problem = withdraw_lang_proof(root, cfg, tid, st, rev or "HEAD")
        if problem:
            raise HeraldError("refusing: %s" % problem)
        rev = rev or "HEAD"  # hash and file list below both from the committed tree
        cur = bundle_hash(root, cfg, st["slug"], rev=rev)
    elif kind == "trust":
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
    if kind == "withdraw-lang":
        head = git_rev(root, "HEAD")
        if sha and git_rev(root, sha) != head:
            raise HeraldError("refusing: --sha must be HEAD (the commit the record describes)")
        sha = head
    files = bundle_files(root, cfg, st["slug"], rev=rev)
    from .hashing import digest_files
    if cfg.translations() and digest_files(files) != cur:
        raise HeraldError("refusing: the file list and the hash describe different trees")
    rec = {"at": now_iso(), "topic_id": tid, "slug": st["slug"], "verified_hash": cur,
           "sha": sha, "kind": kind}
    if cfg.translations():  # 0.8.0 lines carry neither: no translations (L15)
        rec["langs"] = sorted({v["role"] for v in files.values() if v["role"] not in ("src", "img", None)})
        rec["files"] = files
    append_jsonl(paths(root)["ledger"], rec)
    return rec


def withdraw_lang_proof(root, cfg, tid, st, rev):
    """None when the bundle at `rev` is the verified one minus exactly one translation file of a
    language in `withdrawn_langs`, else why not. Basis: this machine's last ledger line with
    `files`; no line → the committed `verified_files` (the caller is attended, like trust)."""
    cur = {p: v["blob"] for p, v in bundle_files(root, cfg, st["slug"], rev=rev).items()}
    led = ledger_latest(root, tid)
    head_st = read_json_at(root, "HEAD", work_rel(tid, "state.json")) or {}
    committed = {p: v["blob"] for p, v in (head_st.get("verified_files") or {}).items()}
    if led is None and head_st == st and committed == cur and set(head_st.get("withdrawn_langs") or []) and \
            not any((v or {}).get("role") in head_st["withdrawn_langs"] for v in (head_st.get("verified_files") or {}).values()):
        # applied (and committed) already on another machine, and this one has no line: the
        # committed record decides, at trust grade (design §5). With a line here the line decides —
        # a committed state alone never outranks this machine's ledger (R2 M-1)
        return None
    if led is not None and not led.get("files"):
        return "the ledger line predates 0.9.0 (no file list) — re-verify instead"
    if led is None:
        # no line on this machine: only the committed record counts (trust grade)
        head_st = read_json_at(root, "HEAD", work_rel(tid, "state.json")) or {}
        if head_st != st:
            return "work/%s/state.json differs from HEAD — commit what `withdraw-lang` wrote first" % tid
        basis = head_st.get("verified_files") or {}
    else:
        basis = led["files"]
    if not basis:
        return "no file-level record to prove against — re-verify instead"
    gone = [p for p in basis if p not in cur]
    roles = {p: (basis[p] or {}).get("role") for p in gone}
    if led is None and not gone:
        # the committed record already excludes the language (applied on another machine)
        if cur == {p: v["blob"] for p, v in basis.items()} and st.get("withdrawn_langs"):
            return None
        return "the bundle differs from the committed verified_files, or no language was withdrawn — re-verify or restore"
    if len(gone) != 1 or roles[gone[0]] not in (st.get("withdrawn_langs") or []):
        return "the bundle differs from the verified one by more than one withdrawn translation (%s)" % (", ".join(gone) or "-")
    if any(cur.get(p) != (basis[p] or {}).get("blob") for p in basis if p not in gone) or set(cur) - set(basis):
        return "the rest of the bundle differs from what was verified — re-verify or restore"
    return None


def git_rev(root, ref):
    from .util import run
    proc = run(["git", "rev-parse", "--verify", "%s^{commit}" % ref], cwd=root, check=False)
    return proc.stdout.strip() if proc.returncode == 0 else None


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
    if art.get("withdrawn") and tid not in (art.get("withdrawn_topics") or []):
        # a different article reuses a withdrawn slug: the old one's refresh history is not its own
        art.pop("superseded", None)
        art.pop("last_refresh_decision", None)
        art.pop("refresh_candidates", None)  # the old article's findings are not the new one's
    translated = bool(cfg.translations())
    now = now_iso()
    prev_published = art.get("published_at")
    if translated and tid.startswith("tr-") and prev_published:
        art.setdefault("source_published_at", prev_published)  # the source's own time, before a tr- overwrites
    upd = {"path": cfg.body_path(slug), "url": cfg.article_url(slug), "origin": origin,
           "current_topic_id": tid, "published_at": now, "withdrawn": False}
    # 0.8.0 overwrites category/keywords; a translation repo keeps them when the topic has none
    # (a tr- topic, 01-multilingual.md §5)
    if not translated or t.get("category") is not None:
        upd["category"] = t.get("category")
    if not translated or t.get("keywords"):
        upd["keywords"] = t.get("keywords", [])
    art.update(upd)
    stamped = bool(t.get("auto_merged_pr")) and (pr is None or str(pr) == str(t["auto_merged_pr"]))
    if stamped:
        auto = True  # merged unattended: stays false whoever records it later
    accepted = t.get("auto_merged_accepted") if stamped else None
    source_published = not tid.startswith("tr-")  # a later translation never publishes the source
    if source_published:
        if translated:
            art["source_published_at"] = now  # the source itself changed (not a tr- publish)
        if accepted:  # what the human accepted unread for this publish (`/hrd next`)
            art["auto_accepted"] = list(accepted)
        else:
            art.pop("auto_accepted", None)
        if origin == "herald":
            art["human_reviewed"] = not auto
            agent = agent_confirmed(root, tid)
            if agent:  # images an agent review confirmed in a `--ship` run (11-ship-consent.md P25)
                art["agent_confirmed"] = agent
            else:
                art.pop("agent_confirmed", None)
            pics = stand_in_record(root, tid)
            if pics:  # stand-ins and decorative pictures (12-generated-fallback-and-decorative.md §2.13)
                art["images"] = pics
            else:
                art.pop("images", None)
            if t.get("refresh_of"):  # what this refresh left for the next one (13 §1.5, §R1-M5)
                from .scope import update_candidates
                try:
                    update_candidates(root, cfg, tid, t, art)
                except Exception as e:  # noqa: BLE001 — the publish record never fails on them
                    import sys
                    sys.stderr.write("hrd: warning: refresh candidates not updated: %s\n" % e)
    if translated:
        if "first_published_at" not in art:
            # the earliest publish the topics remember; unknown for pre-Herald history (R4 MN-7)
            seen = [h.get("at") for x in data["topics"] if (x.get("slug") or x.get("refresh_of")) == slug
                    for h in x.get("history") or [] if h.get("state") == "published" and h.get("at")]
            art["first_published_at"] = min(seen) if seen else (None if prev_published else now)
        mine = _published_langs(root, cfg, tid, t)
        withdrawn = [l for l in art.get("withdrawn_langs") or [] if l not in mine]
        if withdrawn:
            art["withdrawn_langs"] = withdrawn
        else:
            art.pop("withdrawn_langs", None)
        trs = art.setdefault("translations", {})
        for lang, path in cfg.translation_paths(slug).items():
            if not os.path.isfile(os.path.join(root, path)):
                continue
            e = trs.setdefault(lang, {})
            e.update({"path": path, "url": cfg.article_url(slug, lang)})
            if lang in mine or "published_at" not in e:
                e["published_at"] = now
                e.setdefault("first_published_at", now)
                if origin == "herald":
                    e["human_reviewed"] = not auto
                if accepted:
                    e["auto_accepted"] = list(accepted)
                else:
                    e.pop("auto_accepted", None)
        # one entry per publish (PR): the daily throttle counts these, not human_reviewed
        art["publishes"] = (art.get("publishes") or [])[-19:] + [{"at": now, "auto": bool(auto), "topic_id": tid}]
    if t.get("follows"):  # a new article written instead of refreshing an old one (02-refresh-decision.md R9)
        import sys
        from .refresh import link_superseded
        link_superseded(pub, t["follows"], slug, warn=lambda m: sys.stderr.write("hrd: warning: %s\n" % m))
    t["slug"] = slug
    set_topic_state(t, "published", note=("auto " if auto else "") + ("PR #%s" % pr if pr else origin))
    save_published(root, pub)
    save_topics(root, data)
    return art


def stand_in_record(root, tid):
    """`published.json` `images`: {"stand_ins": [{id, place, names, why}], "decorative": [ids]}."""
    from .images import _items, load_manifest
    from .stand_in import is_stand_in, item_role
    try:
        man = load_manifest(root, tid)
    except HeraldError:
        return None
    stands, dec = [], []
    for it in _items(man):
        role = item_role(it)
        if is_stand_in(role):
            si = it.get("stand_in") or {}
            stands.append({"id": it.get("id"), "of": it.get("place"), "names": si.get("names") or [],
                           "why": si.get("why")})
        elif role == "decorative":
            dec.append(it.get("id"))
    return {"stand_ins": stands, "decorative": dec} if stands or dec else None


def agent_confirmed(root, tid):
    """Ids of the topic's images and screenshots an agent review confirmed (state `confirmed_by`)."""
    try:
        st = read_json(state_path(root, tid))
    except ValueError:
        st = None
    if not isinstance(st, dict):
        return []
    out = [k for k, r in (((st.get("images") or {}).get("items")) or {}).items()
           if isinstance(r, dict) and r.get("confirmed_by") == "agent"]
    out += [k for k, r in (((st.get("screenshots") or {}).get("shots")) or {}).items()
            if isinstance(r, dict) and r.get("confirmed_by") == "agent"]
    return sorted(out)


def _published_langs(root, cfg, tid, t):
    """The translation languages this topic's PR published: its state.json `translation.langs`
    (committed with the merge), else the topic's `languages`."""
    st = read_json(state_path(root, tid)) or {}
    langs = ((st.get("translation") or {}).get("langs"))
    if langs is None:
        langs = t.get("languages") or []
    return [l for l in langs if l in cfg.target_langs()]


def bundle_urls(root, cfg, slug):
    """The source URL and the URL of every translation that exists — ship §8 opens them all."""
    out = {cfg.source_lang(): cfg.article_url(slug)}
    for lang, path in cfg.translation_paths(slug).items():
        if os.path.isfile(os.path.join(root, path)):
            out[lang] = cfg.article_url(slug, lang)
    return out


# --- signals --------------------------------------------------------------------------------

SIGNAL_KINDS = (
    "human-edit", "ship-decline", "review-finding", "audit-finding", "dismissal",
    "revise-weakness", "verify-gap", "hold", "gate-failure", "escalation",
    "session-edit-request", "research-error",
    "stagnation",  # legacy (0.2.x): now recorded as a hold with reason stagnation
    "incomplete",  # a batch child that ended without a result (crash, timeout)
    "refresh-override",  # a human overturned the strategist's refresh recommendation (topic_id slug:<slug>)
    # SNS drafts (03-social.md S13), topic_id social:<sns>:<YYYYMMDD>
    "social-edit-request",  # the human asked for a change to a draft (session, HRD signal)
    "social-reject",        # the human discarded every draft of a run (HRD social close --reject-all)
    "social-gate-failure",  # a draft still failing the post checks after its retry (HRD social check --record)
    "social-final",         # the uploaded text differs from the approved draft (HRD social final)
    "out-of-scope-finding",  # 0.22.0: an auditor MAJOR a refresh left for the next one (13 §R2-1)
)
# listed for evolve but never counted toward the nudge: an escalation accompanies a loopback that
# is already counted; an incomplete child is usually environment, not writing; an out-of-scope
# finding is old text a refresh did not touch — nothing evolve could change
CONTEXT_KINDS = ("escalation", "incomplete", "out-of-scope-finding")


# Hold notes that mark a stop as environment or a human's choice, not a writing weakness: never a
# growth signal (the last two are what 0.2.x wrote for environment stops)
NON_SIGNAL_HOLD_NOTES = ("tooling:", "human:", "batch child did not finish", "base has foreign unpushed commits")


def hold_is_signal(reason, note):
    """One rule for both places a hold is recorded (`HRD state`, the batch runner)."""
    return reason not in NON_SIGNAL_HOLD_REASONS and not str(note or "").startswith(NON_SIGNAL_HOLD_NOTES)

# Closed theme list for editor REVISE and auditor findings: the editor-in-chief classifies each
# loopback so the nudge counts recurring weaknesses, not every REVISE (one theme = one count axis).
THEMES = ("intro", "structure", "length", "depth", "clarity", "tone", "search", "promotion",
          "policy", "accuracy", "images", "exemplar", "other")
# the count axis of social signals (S13): what the human or the checks objected to
SOCIAL_THEMES = ("tone", "length", "format", "persona", "hashtags", "disclosure", "fact", "other")
SOCIAL_FINAL_BASELINE = 0.1  # an uploaded text changed by at most 10% of the draft's characters
LOOPBACK_CAUSES = {"revise": "revise-weakness", "audit": "audit-finding", "verify": "verify-gap", "gate": None,
                   "research": "research-error", "translation": "verify-gap"}


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
        valid = None
        for d in log:
            if isinstance(d, dict) and d.get("kind") == "dismissal":
                data = {k: d[k] for k in ("note", "severity", "finding", "round") if k in d}
                if isinstance(data.get("note"), str):
                    data["note"] = data["note"][:500]
                key = note_of(data)
                if key in existing:
                    continue
                if "grounds" in d:  # 13 §2.2: research claims the auditor could not see
                    if valid is None:
                        valid = set(research_claim_ids(root, tid)) - set(research_withdrawn_ids(root, tid))
                    grounds = _grounds(d.get("grounds"))
                    dropped = [c for c in grounds if c not in valid]
                    if dropped:
                        sys.stderr.write("hrd: warning: dismissal grounds %s are not live claims in research.md "
                                         "(missing or withdrawn) — left out of the signal\n" % ", ".join(dropped))
                    grounds = [c for c in grounds if c in valid]
                    if grounds:
                        data["grounds"] = grounds
                if key not in existing:
                    signal(root, "dismissal", tid, data)
                    existing.add(key)
    except Exception as e:  # noqa: BLE001
        sys.stderr.write("hrd: warning: could not record dismissal signals: %s\n" % e)


def _grounds(raw):
    """`grounds`: claim ids `C<n>`, de-duplicated in order, at most 20; anything else is dropped."""
    out = []
    for x in raw if isinstance(raw, list) else []:
        c = x.strip() if isinstance(x, str) else ""
        if re.fullmatch(r"C[0-9]+", c) and c not in out:
            out.append(c)
    return out[:20]


def record_out_of_scope(root, tid, crit):
    """`out-of-scope-finding` (13 §R2-1): one context record per out-of-scope MAJOR — listed for
    evolve, never counted toward the nudge. Once per (topic, id, quote_hash)."""
    import sys
    try:
        from .scope import quote_hash
        seen = {(r.get("topic_id"), (r.get("data") or {}).get("id"), (r.get("data") or {}).get("quote_hash"))
                for r in read_jsonl(paths(root)["signals"])
                if isinstance(r, dict) and r.get("kind") == "out-of-scope-finding" and isinstance(r.get("data"), dict)}
        for e in audit_entries(crit if isinstance(crit, dict) else {}):
            if e.get("outcome") != "out-of-scope" or _sev(e) != "MAJOR" or not isinstance(e.get("quote"), str):
                continue
            data = {"id": str(e.get("id")), "quote_hash": quote_hash(e["quote"]),
                    "summary": str(e.get("summary") or "")[:200], "round": e.get("round")}
            key = (tid, data["id"], data["quote_hash"])
            if key not in seen:
                signal(root, "out-of-scope-finding", tid, data)
                seen.add(key)
    except Exception as e:  # noqa: BLE001
        sys.stderr.write("hrd: warning: could not record out-of-scope signals: %s\n" % e)


# the plugin version new signal records carry (`v`, 0.22.0 — 13 §3.4, §R1-m7): hrd.py and the batch
# runner set it from SCRIPTS_VERSION (the literal stays in hrd.py); None writes no `v`
PLUGIN_VERSION = None


def signal(root, kind, tid=None, data=None, human_reviewed=None):
    if kind not in SIGNAL_KINDS:
        raise HeraldError("unknown signal kind %s" % kind)
    import uuid
    # the nonce makes every record (and so its id) unique, even two identical events in one second
    rec = {"at": now_iso(), "kind": kind, "topic_id": tid, "data": data or {}, "nonce": uuid.uuid4().hex[:12]}
    if PLUGIN_VERSION:
        rec["v"] = PLUGIN_VERSION
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
    # 0.22.0 (13 §3.1): signals a human retired without a proposal, group by group, and the record of
    # what was put back — kept apart from `consumed`, so they can be listed and undone
    for k in ("retired", "unretired"):
        st[k] = [e for e in st.get(k) or [] if isinstance(e, dict) and isinstance(e.get("ids"), list)]
    return st


def retired_ids(st):
    return {i for e in st.get("retired") or [] for i in e.get("ids") or [] if isinstance(i, str)}


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
    if rec["kind"] == "social-final":  # posts are 1–4 lines: judge by characters, not lines
        changed, total = _count(data.get("chars_changed")), _count(data.get("draft_chars"))
        return changed is not None and total is not None and changed <= SOCIAL_FINAL_BASELINE * max(total, 1)
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
    consumed = set(st["consumed"]) | retired_ids(st)  # a retired signal is used like a consumed one
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
        g = groups.setdefault(key, {"ids": [], "rec": dict(rec), "data": {}, "v": False})
        g["ids"].append(sid)
        g["data"].update(rec.get("data") or {})
        g["v"] = g["v"] or bool(rec.get("v"))
    out = []
    for g in groups.values():
        r = g["rec"]
        r["data"] = g["data"]
        r["id"] = g["ids"][0]
        r["ids"] = g["ids"]
        r.pop("v", None)
        if not g["v"]:
            r["legacy"] = True  # no record of the group says which plugin wrote it (13 §3.4, §R1-m7)
        out.append(r)
    return out, baseline, st


def signal_theme(rec):
    """The count axis: `kind`, or `kind:theme` when the record names a theme from THEMES (editor
    REVISE and auditor findings), or `hold:<reason>` — so unrelated events of one kind are not
    one recurring problem."""
    data = rec.get("data") or {}
    if rec["kind"].startswith("social-"):
        return "%s:%s" % (rec["kind"], data["theme"]) if data.get("theme") in SOCIAL_THEMES else rec["kind"]
    if data.get("theme") in THEMES:
        return "%s:%s" % (rec["kind"], data["theme"])
    if rec["kind"] == "stagnation":
        return "hold:stagnation"
    if rec["kind"] == "hold" and isinstance(data.get("reason"), str) and data["reason"]:
        return "hold:%s" % data["reason"][:40]
    return rec["kind"]


def secondary_themes(rec):
    """Count axes a record adds on top of its theme (13 §R1-M2, §R2-7): a dismissal grounded in
    research claims stays a `dismissal` and also counts as `dismissal:grounded-unseen` — the
    auditor never sees research, the reader may not either."""
    data = rec.get("data") or {}
    if rec.get("kind") == "dismissal" and isinstance(data.get("grounds"), list) and data["grounds"]:
        return ["dismissal:grounded-unseen"]
    return []


def evolve_readiness(root, cfg=None, listing=False):
    """Deterministic, advisory count per theme (see signal_theme) over unconsumed signals.
    `tier` (machine token): sufficient — some theme has >= 3 signals from >= 2 topics AND at
    least one of them was not seen by this machine's last evolve scan (a run that found nothing
    is not re-nudged until new evidence comes); watching — signals exist but that is not met;
    none — no signals."""
    sigs, baseline, st = evolve_signals(root)
    seen = set(st["seen"])
    themes, kinds, secondary = {}, {}, {}
    for r in sigs:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
        if r["kind"] in CONTEXT_KINDS:
            continue
        for axes, name in [(themes, signal_theme(r))] + [(secondary, n) for n in secondary_themes(r)]:
            k = axes.setdefault(name, {"count": 0, "topics": set(), "new": 0})
            k["count"] += 1
            if r.get("topic_id"):
                k["topics"].add(r["topic_id"])
            if not seen.intersection(r["ids"]):
                k["new"] += 1
    both = dict(themes, **secondary)  # a secondary axis may be ready on its own; totals stay per record
    ready = sorted(n for n, k in both.items() if k["count"] >= MIN_SIGNALS and len(k["topics"]) >= MIN_TOPICS)
    fresh = [n for n in ready if both[n]["new"] > 0]
    total = sum(k["count"] for k in themes.values())
    every = set().union(*[k["topics"] for k in themes.values()]) if themes else set()
    # the summary counts articles; social signals count SNS days (03-social.md S13)
    topics = {t for t in every if not t.startswith("social:")}
    social_topics = every - topics
    out = {
        "tier": "sufficient" if fresh else ("watching" if total else "none"),
        "last_scan": st["last_scan"],
        "signals": total,
        "topics": len(topics),
        "social_topics": len(social_topics),
        "ready_themes": ready,
        "new_ready_themes": fresh,
        "themes": {n: {"count": k["count"], "topics": len(k["topics"]), "new": k["new"]}
                   for n, k in sorted(themes.items())},
        "kinds": dict(sorted(kinds.items())),
        "threshold": {"signals": MIN_SIGNALS, "topics": MIN_TOPICS},
    }
    if secondary:
        out["secondary"] = {n: {"count": k["count"], "topics": len(k["topics"]), "new": k["new"]}
                            for n, k in sorted(secondary.items())}
    if listing:
        out["list"] = sigs
        out["baseline"] = baseline
        ret = st.get("retired") or []
        out["retired"] = {"groups": len(ret), "ids": len(retired_ids(st)), "entries": ret}
    return out


def _snapshot_path(root):
    return os.path.join(paths(root)["memory"], "evolve-scan.json")


def evolve_snapshot(root, sigs, token=None):
    """Phase 1 keeps the ids it listed, tagged with the run's lock token; the scan stamp at the
    end of that completed run marks exactly those as seen (not signals that arrived while the
    run waited for approvals). A snapshot from another (aborted) run is never used."""
    write_json(_snapshot_path(root), {"at": now_iso(), "token": token,
                                      "ids": sorted({i for r in sigs for i in r["ids"]})})


def evolve_mark(root, scan=False, consume=(), token=None, retire=(), unretire=(), reason=None, by=None, run=None):
    """evolve's local bookkeeping: `scan` records which signals the run saw (the Phase 1
    snapshot if present, else the current list); `consume` marks signal ids (from
    `evolve-readiness --list`) as used by a decided proposal. Known ids are consumed with their
    whole group; unknown ones are reported, not fatal. Both prune ids whose records are gone.
    0.22.0 (13 §3.1): `retire` takes groups out of the count without a proposal (a human's
    decision, recorded with its reason); `unretire` puts back every group holding one of the ids.
    The caller (`cmd_evolve_mark`) checks that this is an attended evolve run's lock."""
    st = load_evolve_state(root)
    sigs, _, _ = evolve_signals(root)
    present = {signal_id(r) for r in read_jsonl(paths(root)["signals"]) if isinstance(r, dict)}
    unknown, baseline_cited, already, already_retired = [], [], [], []
    known = {}
    for r in sigs:
        for i in r["ids"]:
            known[i] = r["ids"]
    base_ids = {signal_id(r) for r in read_jsonl(paths(root)["signals"]) if baseline_signal(r)} \
        if consume or retire else set()
    if consume:
        add = []
        for i in consume:
            if i in known:
                add.extend(known[i])
            elif i in base_ids:
                baseline_cited.append(i)  # baseline evidence is cited, never consumed
            elif i in st["consumed"] or i in add:
                already.append(i)
            elif i in retired_ids(st):
                already_retired.append(i)
            else:
                unknown.append(i)
        st["consumed"] = sorted(set(st["consumed"]) | set(add))
    retired_now = []
    if retire:
        groups, seen_ids = [], set()
        for i in retire:
            if i in seen_ids:
                continue
            if i in known:
                groups.append(list(known[i]))
                seen_ids.update(known[i])
            elif i in base_ids:
                baseline_cited.append(i)  # nothing to retire: baseline is never counted
            elif i in retired_ids(st):
                already_retired.append(i)
            elif i in st["consumed"]:
                already.append(i)
            else:
                unknown.append(i)
        for ids in groups:
            st["retired"].append({"ids": ids, "reason": reason, "at": now_iso(), "by": by,
                                  "version": PLUGIN_VERSION, "run": run})
            retired_now.extend(ids)
    unretired_now = []
    if unretire:
        want = set(unretire)
        keep = []
        for e in st["retired"]:
            if want & set(e.get("ids") or []):
                unretired_now.extend(e["ids"])
                st["unretired"].append({"ids": list(e["ids"]), "reason": e.get("reason"), "at": now_iso(), "by": by})
            else:
                keep.append(e)
        st["retired"] = keep
        unknown += sorted(want - set(unretired_now))
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
    for e in st["retired"]:  # an entry whose records are all gone stays as the record of a decision
        e["ids"] = [i for i in e["ids"] if i in present]
    write_json(_evolve_state_path(root), st)
    out = {"last_scan": st["last_scan"], "consumed": len(st["consumed"]), "unknown": unknown,
           "baseline_cited": baseline_cited, "already_consumed": already}
    if retire or unretire or already_retired:
        out.update(retired=retired_now, already_retired=already_retired, unretired=unretired_now)
    return out
