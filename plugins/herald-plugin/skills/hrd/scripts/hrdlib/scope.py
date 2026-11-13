"""A refresh's scope for the auditor, out-of-scope findings and the next refresh's candidates
(design/herald/13-auditor-scope-and-signal-retire.md, 0.22.0).

- `refresh_scope`: what this refresh was meant to change, quoted by code (the topic's stale list,
  its `angle`, its direction file, the earlier findings the brief adopted) — the auditor gets the
  quote, never a model's rewording of it (§1.1, §R1-M5, §R1-m6).
- `quote_problem`: an `out-of-scope` finding names one sentence (`quote`) that must stand, word
  for word, in the body the refresh started from (the merge-base with `origin/<base>`) and in the
  current body, inside a paragraph that is unchanged in both (§R2-1, §R2-2). Sentences and the
  quote go through the same normalisation (`prose._clean` → `translation.normalize` → no
  whitespace), and a `<ruby>` reading may be in the quote or not (§R3-1). No substring matching.
- `update_candidates`: what a published refresh leaves for the next one (`published.json`
  `refresh_candidates`, §1.5, §R1-M5, §R2-4, §R2-5).
"""

import hashlib
import os
import re
import subprocess

from . import prose
from .util import HeraldError, now_iso

QUOTE_MAX = 500     # characters of `quote`, in audit_log and in refresh_candidates alike (§R2-8)
QUOTE_MIN = 15      # characters after normalisation, whitespace excluded (§R2-1)
SUMMARY_MAX = 200   # a candidate's summary — public repos keep it on base (§R1-m12)
CANDIDATES_MAX = 20

_FM_RE = re.compile(r"\A(?:---|\+\+\+)\r?\n.*?\r?\n(?:---|\+\+\+)\r?\n?", re.S)
_RUBY_RE = re.compile(r"<(rt|rp)\b[^>]*>.*?</\1\s*>", re.I | re.S)
_ADOPTED_RE = re.compile(r"(?mi)^[ \t]*(?:[-*+][ \t]+)?adopted:[ \t]*([^\s/]+)/(\S+?)[ \t]*$")


def _key(text):
    from .translation import normalize
    return re.sub(r"\s+", "", normalize(prose._clean(text or "")))


def quote_hash(quote):
    """The comparison and merge key of a quote: sha256 of its normalised form, first 16 hex."""
    return hashlib.sha256(_key(quote).encode("utf-8")).hexdigest()[:16]


def _units(body, drop_ruby):
    """(every sentence key, [(paragraph key, its sentence keys)]) of a body."""
    text = _FM_RE.sub("", (body or "").replace("\r\n", "\n"), count=1)
    if drop_ruby:
        text = _RUBY_RE.sub("", text)
    sents, paras = set(), []
    for para in prose._paragraphs(text):
        keys = {_key(s) for _, s in prose._para_sentences(para)}
        sents |= keys
        paras.append((_key(" ".join(t for _, t in para)), keys))
    return sents, paras


def quote_problem(base, cur, quote, eid):
    """Why `quote` cannot mark finding `eid` out of scope, or None. Passes when one of the two
    ruby readings (as written, or with `<rt>`/`<rp>` dropped on both sides) passes every check."""
    if not isinstance(quote, str) or not quote.strip():
        return "%s is out of scope but has no quote (the sentence it is about, word for word)" % eid
    if len(quote) > QUOTE_MAX:
        return "%s's quote is over %d characters — a sentence that long cannot be out of scope" % (eid, QUOTE_MAX)
    if base is None:
        return ("%s is out of scope but the body this refresh started from cannot be read (no merge-base with the "
                "base branch) — fix or dismiss it" % eid)
    first = None
    for drop in (False, True):
        q = _RUBY_RE.sub("", quote) if drop else quote
        qk = _key(q)
        b_sents, b_paras = _units(base, drop)
        c_sents, c_paras = _units(cur, drop)
        if len(qk) < QUOTE_MIN:
            why = "%s's quote is too short to name one sentence (%d characters, at least %d)" % (eid, len(qk), QUOTE_MIN)
        elif qk not in b_sents:
            why = ("%s is in text this refresh wrote (its quote is no whole sentence of the article before the "
                   "refresh) — fix or dismiss it" % eid)
        elif qk not in c_sents:
            why = ("%s's sentence changed after it was ruled out of scope — log it fixed (the next recheck checks "
                   "it) or dismiss it" % eid)
        else:
            b_keys, c_keys = {k for k, _ in b_paras}, {k for k, _ in c_paras}
            # every paragraph holding the sentence, on either side, stands unchanged on the other (§R3-2)
            if all(k in c_keys for k, s in b_paras if qk in s) and all(k in b_keys for k, s in c_paras if qk in s):
                return None
            why = "%s's paragraph changed in this refresh — fix or dismiss it" % eid
        first = first or why
    return first


def merge_base_body(root, cfg, slug):
    """The source body at `git merge-base HEAD origin/<base>`, or None (§R2-2)."""
    p = subprocess.run(["git", "merge-base", "HEAD", "origin/%s" % cfg.base], cwd=root, capture_output=True, text=True)
    mb = p.stdout.strip() if p.returncode == 0 else ""
    if not mb:
        return None
    p = subprocess.run(["git", "show", "%s:%s" % (mb, cfg.body_path(slug))], cwd=root, capture_output=True)
    return p.stdout.decode("utf-8", "replace") if p.returncode == 0 else None


def _read(root, rel):
    try:
        with open(os.path.join(root, rel), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def is_out(e):
    return isinstance(e, dict) and (e.get("outcome") == "out-of-scope" or e.get("scope") == "out")


def audit_problems(root, cfg, tid, crit, rnd, entries):
    """`stage pass --stage critique`'s out-of-scope checks, over every such audit_log entry (not
    only this round's — a sentence that changed between rounds is caught then)."""
    from .store import _int, _sev, get_topic, load_topics
    fr = (crit or {}).get("final_round") or {}
    outs = [e for e in entries if is_out(e)]
    problems = []
    claimed = _int((fr.get("out_of_scope") or {}).get("major"))
    if claimed and rnd <= _cap():
        ok = [e for e in outs if e.get("round") == rnd and _sev(e) == "MAJOR"]
        if len(ok) < claimed:
            problems.append("final_round.out_of_scope.major is %d but audit_log lists %d out-of-scope MAJOR(s) for "
                            "round %d" % (claimed, len(ok), rnd))
    if not outs:
        return problems
    try:
        t = get_topic(load_topics(root), tid)
    except HeraldError:
        t = {}
    slug = t.get("refresh_of")
    if not slug or tid.startswith("tr-"):
        return problems + ["%s: out-of-scope is only for a refresh of a published article (this topic has no "
                           "refresh_of) — fix or dismiss" % ", ".join(str(e.get("id")) for e in outs)]
    h = fr.get("scope_hash")
    if not isinstance(h, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", h) or h == _EMPTY_HASH:
        problems.append("out-of-scope findings need final_round.scope_hash (`HRD refresh-scope` scope_hash at the "
                        "audit; a refresh with no known scope audits in full)")
    base, cur = None, _read(root, cfg.body_path(slug))
    base_needed = True
    for e in outs:
        eid = e.get("id")
        if e.get("outcome") != "out-of-scope" or e.get("scope") != "out":
            problems.append("%s: scope \"out\" goes with outcome out-of-scope (both, or neither)" % eid)
            continue
        if _sev(e) == "BLOCKER":
            problems.append("%s: a BLOCKER is never out of scope" % eid)
            continue
        if e.get("tag") in ("unfixed", "regression"):
            problems.append("%s: an %s finding is about text this refresh touched — never out of scope"
                            % (eid, e.get("tag")))
            continue
        if base_needed:
            base, base_needed = merge_base_body(root, cfg, slug), False
        why = quote_problem(base, cur or "", e.get("quote"), eid)
        if why:
            problems.append(why)
    return problems


def _cap():
    from .store import AUDIT_ROUND_CAP
    return AUDIT_ROUND_CAP


_EMPTY_HASH = "sha256:" + hashlib.sha256(b"").hexdigest()


# --- the scope (§1.1) -------------------------------------------------------------------------

def _angle(angle):
    a = str(angle or "").strip()
    m = re.match(r"(?i)^refresh:\s*", a)
    return a[m.end():].strip() if m else a  # not written by `/hrd refresh`: the whole text (§R1-m6)


def adopted(root, tid):
    """`adopted: <from>/<id>` lines of the topic's brief (§R1-M5)."""
    from .store import work_rel
    text = _read(root, work_rel(tid, "brief.md")) or ""
    return [(m.group(1), m.group(2)) for m in _ADOPTED_RE.finditer(text)]


def refresh_scope(root, cfg, tid):
    from .store import find_article, get_topic, load_published, load_topics
    t = get_topic(load_topics(root), tid)
    slug = t.get("refresh_of")
    if not slug:
        return {"refresh_of": None}
    warnings = []
    stale = [str(x).strip() for x in ((t.get("refresh_decision") or {}).get("stale") or []) if str(x).strip()]
    angle = _angle(t.get("angle"))
    direction = None
    if t.get("direction"):
        direction = _read(root, t["direction"])
        if direction is None:
            warnings.append("direction file %s is not on this machine" % t["direction"])
    art = find_article(load_published(root), slug) or {}
    cands = {(c.get("from"), c.get("id")): c for c in art.get("refresh_candidates") or [] if isinstance(c, dict)}
    body = _read(root, cfg.body_path(slug)) or ""
    sents = _units(body, False)[0] | _units(body, True)[0]
    picked = []
    for frm, cid in adopted(root, tid):
        c = cands.get((frm, cid))
        if not c:
            warnings.append("adopted %s/%s is not among %s's refresh_candidates" % (frm, cid, slug))
            continue
        q = c.get("quote")
        still = isinstance(q, str) and (_key(q) in sents or _key(_RUBY_RE.sub("", q)) in sents)
        picked.append({"from": frm, "id": cid, "summary": c.get("summary"), "status": "unchanged" if still else "resolved"})
    parts = []
    if stale:
        parts.append("What is stale (refresh decision):\n" + "\n".join("- %s" % s for s in stale))
    if angle:
        parts.append("The human's reason (topic angle):\n%s" % angle)
    if direction and direction.strip():
        parts.append("The human's direction:\n%s" % direction.strip())
    if picked:
        parts.append("Earlier audit findings this refresh adopted:\n" +
                     "\n".join("- %s" % (p["summary"] or "%s/%s" % (p["from"], p["id"])) for p in picked))
    quoted = "\n\n".join(parts)
    out = {"refresh_of": slug, "scope": stale, "angle": angle or None, "direction": direction,
           "adopted": picked, "quoted": quoted,
           "scope_hash": ("sha256:" + hashlib.sha256(quoted.encode("utf-8")).hexdigest()) if quoted else None}
    if warnings:
        out["warnings"] = warnings
    return out


# --- candidates for the next refresh (§1.5) ----------------------------------------------------

def update_candidates(root, cfg, tid, t, art):
    """On a refresh's publish: drop candidates whose sentence is gone from the new body (this
    refresh changed it) or that this audit raised again (same quote_hash — the new entry replaces
    it); an adopted one still in place stays, marked `adopted_by`; then this audit's out-of-scope
    entries. The latest CANDIDATES_MAX. Reads the merged work files on base."""
    from .store import audit_entries, safe_machine, _sev
    crit = safe_machine(root, tid, "critique.json")
    body = _read(root, cfg.body_path(art["slug"])) or ""
    sents = _units(body, False)[0] | _units(body, True)[0]
    now = now_iso()
    fresh = []
    for e in audit_entries(crit):
        if e.get("outcome") != "out-of-scope" or e.get("scope") != "out" or _sev(e) not in ("MAJOR", "MINOR"):
            continue
        q = e.get("quote")
        if not isinstance(q, str) or not q.strip():
            continue
        fresh.append({"from": tid, "id": str(e.get("id")), "severity": _sev(e),
                      "summary": str(e.get("summary") or "")[:SUMMARY_MAX], "quote": q[:QUOTE_MAX],
                      "quote_hash": quote_hash(q), "at": now})
    again = {c["quote_hash"] for c in fresh}
    took = set(adopted(root, tid))
    kept = []
    for c in art.get("refresh_candidates") or []:
        if not isinstance(c, dict):
            continue
        q = c.get("quote")
        h = c.get("quote_hash") or (quote_hash(q) if isinstance(q, str) else None)
        if h in again:
            continue
        if isinstance(q, str) and _key(q) not in sents and _key(_RUBY_RE.sub("", q)) not in sents:
            continue  # the sentence is gone: this refresh changed it (§R2-4)
        if (c.get("from"), c.get("id")) in took:
            c = dict(c, adopted_by=tid)  # adopted, yet the sentence stands (§R2-5)
        kept.append(c)
    out = (kept + fresh)[-CANDIDATES_MAX:]
    if out:
        art["refresh_candidates"] = out
    else:
        art.pop("refresh_candidates", None)
    return out


def candidates_of(art):
    return [c for c in (art or {}).get("refresh_candidates") or [] if isinstance(c, dict)]
