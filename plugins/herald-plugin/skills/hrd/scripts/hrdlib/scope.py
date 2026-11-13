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
_RT_RE = re.compile(r"<rt\b[^>]*>(.*?)</rt\s*>", re.I | re.S)
_RP_RE = re.compile(r"<rp\b[^>]*>(.*?)</rp\s*>", re.I | re.S)
# inline code is expanded, not dropped: a reader sees `npm install` as "npm install" (review 28 M1);
# never across lines, so a fence stays a fence
_CODE_RE = re.compile(r"(`+)([^`\n]*?)\1")
_FOOTNOTE_RE = re.compile(r"\[\^[^\]\s]*\](?!:)")
_REFLINK_RE = re.compile(r"(?<!!)\[([^\]]*)\]\[[^\]]*\]")
_ESCAPE_RE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|<>~])")
_END_RE = re.compile(r"[.。!?！？]+$")
# a ruby reading and its fallback brackets survive `_clean` as private-use marks, so each reading can
# be taken from the same paragraphs: as written (reading and brackets), without the brackets, without both
_RT_A, _RT_B, _RP_A, _RP_B = "\ue000", "\ue001", "\ue002", "\ue003"
_CODE_MARK = "\ue004"  # an inline code span's backticks in a body, so `_clean` keeps its text
READINGS = (0, 1, 2)
_ADOPTED_LINE_RE = re.compile(r"(?mi)^[ \t]*(?:[-*+][ \t]+)?adopted:(.*)$")
_ADOPTED_RE = re.compile(r"^[ \t]*`?([^\s/`]+)/([^\s`,;:]+)`?(?:[ \t,;:].*)?$")


def _ruby_marks(t):
    t = _RT_RE.sub(lambda m: _RT_A + m.group(1) + _RT_B, t)
    return _RP_RE.sub(lambda m: _RP_A + m.group(1) + _RP_B, t)


def _pre_piece(t):
    """What a reader does not see as text inside a line: footnote marks, reference links, escapes,
    entities. A body's lines are classified (heading, quote, table, list) before this, on the text
    as written — `\\#`, `&gt;` or an expanded code span never turn a line into something else
    (review 28 n1)."""
    import html
    t = _FOOTNOTE_RE.sub("", t)
    t = _REFLINK_RE.sub(r"\1", t)
    t = _ESCAPE_RE.sub(r"\1", t)
    return html.unescape(t)


def _pre(text):
    """A quote, the same way a body's sentences are read."""
    return _pre_piece(_ruby_marks(_CODE_RE.sub(r"\2", text or "")))


def _reading(text, r):
    if r >= 1:
        text = re.sub("%s[^%s]*%s" % (_RP_A, _RP_B, _RP_B), "", text)
    if r >= 2:
        text = re.sub("%s[^%s]*%s" % (_RT_A, _RT_B, _RT_B), "", text)
    return re.sub("[%s%s%s%s%s]" % (_RT_A, _RT_B, _RP_A, _RP_B, _CODE_MARK), "", text)


def _k(text, r=0):
    """One sentence or paragraph (already through `_pre`) as a comparison key in reading `r`."""
    from .translation import normalize
    return _END_RE.sub("", re.sub(r"\s+", "", normalize(prose._clean(_reading(text, r)))))


def _key(text, r=0):
    return _k(_pre(text), r)


def quote_hash(quote):
    """The comparison and merge key of a quote: sha256 of its normalised form, first 16 hex."""
    return hashlib.sha256(_key(quote).encode("utf-8")).hexdigest()[:16]


def _units(body):
    """[(paragraph key as written, {reading: its sentence keys})] of a body."""
    text = _ruby_marks(_FM_RE.sub("", (body or "").replace("\r\n", "\n"), count=1))
    text = "\n".join(l if prose.FENCE_RE.match(l) else _CODE_RE.sub(lambda m: _CODE_MARK + m.group(2) + _CODE_MARK, l)
                     for l in text.split("\n"))
    paras = []
    for para in prose._paragraphs(text):
        para = [(ln, _pre_piece(t)) for ln, t in para]
        sents = [s for _, s in prose._para_sentences(para)]
        paras.append((_k(" ".join(t for _, t in para)), {r: {_k(x, r) for x in sents} for r in READINGS}))
    return paras


def present(paras, quote):
    """The quote is a whole sentence of these paragraphs in some reading."""
    return any(_key(quote, r) in s[r] for _, s in paras for r in READINGS)


def quote_problem(base, cur, quote, eid):
    """Why `quote` cannot mark finding `eid` out of scope, or None. Passes when, in one ruby reading
    (as written; without `<rp>` brackets; without reading and brackets — on both sides), the quote
    is a whole sentence of both bodies and every paragraph holding it stands, as written, in the
    other body too (so a changed reading is a change, review 28 m3)."""
    if not isinstance(quote, str) or not quote.strip():
        return "%s is out of scope but has no quote (the sentence it is about, word for word)" % eid
    if len(quote) > QUOTE_MAX:
        return "%s's quote is over %d characters — a sentence that long cannot be out of scope" % (eid, QUOTE_MAX)
    if base is None:
        return ("%s is out of scope but the body this refresh started from cannot be read (no merge-base with the "
                "base branch) — fix or dismiss it" % eid)
    b_paras, c_paras = _units(base), _units(cur)
    b_keys, c_keys = {k for k, _ in b_paras}, {k for k, _ in c_paras}
    best = (-1, None)  # the reading that got furthest names the reason
    for r in READINGS:
        qk = _key(quote, r)
        if len(qk) < QUOTE_MIN:
            why = 0, "%s's quote is too short to name one sentence (%d characters, at least %d)" % (eid, len(qk), QUOTE_MIN)
        elif not any(qk in s[r] for _, s in b_paras):
            why = 1, ("%s is in text this refresh wrote (its quote is no whole sentence of the article before the "
                      "refresh) — fix or dismiss it" % eid)
        elif not any(qk in s[r] for _, s in c_paras):
            why = 2, ("%s's sentence changed after it was ruled out of scope — log it fixed (the next recheck checks "
                      "it) or dismiss it" % eid)
        elif all(k in c_keys for k, s in b_paras if qk in s[r]) and all(k in b_keys for k, s in c_paras if qk in s[r]):
            return None  # every paragraph holding the sentence, on either side, stands on the other (§R3-2)
        else:
            why = 3, "%s's paragraph changed in this refresh — fix or dismiss it" % eid
        best = max(best, why)
    return best[1]


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
    try:
        from .store import load_state
        recorded = load_state(root, tid).get("scope_hash")
    except HeraldError:
        recorded = None
    if not isinstance(h, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", h) or h == _EMPTY_HASH:
        problems.append("out-of-scope findings need final_round.scope_hash (`HRD refresh-scope` scope_hash at the "
                        "audit; a refresh with no known scope audits in full)")
    elif h != recorded:  # `HRD audit-round` recorded the scope the auditor got (review 28 m5)
        problems.append("final_round.scope_hash is not the scope `HRD audit-round` recorded for this round — copy "
                        "`refresh-scope`'s scope_hash after `audit-round`, or audit in full")
    seen = {}
    for e in outs:
        if e.get("round") == rnd and _sev(e) == "MAJOR" and isinstance(e.get("quote"), str):
            seen.setdefault(quote_hash(e["quote"]), []).append(str(e.get("id")))
    for ids in seen.values():
        if len(ids) > 1:  # one sentence carries one out-of-scope finding (review 28 m4)
            problems.append("%s quote the same sentence — one out-of-scope MAJOR per sentence" % ", ".join(ids))
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


def adopted(root, tid, warnings=None):
    """`adopted: <from>/<id>` lines of the topic's brief (§R1-M5): the id first (in backticks or
    not), any words after it; a line that names no id is reported in `warnings`."""
    from .store import work_rel
    text = _read(root, work_rel(tid, "brief.md")) or ""
    out = []
    for line in _ADOPTED_LINE_RE.finditer(text):
        m = _ADOPTED_RE.match(line.group(1))
        if m:
            out.append((m.group(1), m.group(2)))
        elif warnings is not None:
            warnings.append("brief line %r names no candidate — write `adopted: <from>/<id>`" % line.group(0).strip())
    return out


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
    paras = _units(_read(root, cfg.body_path(slug)) or "")
    picked = []
    for frm, cid in adopted(root, tid, warnings):
        c = cands.get((frm, cid))
        if not c:
            warnings.append("adopted %s/%s is not among %s's refresh_candidates" % (frm, cid, slug))
            continue
        q = c.get("quote")
        still = isinstance(q, str) and present(paras, q)
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
    paras = _units(_read(root, cfg.body_path(art["slug"])) or "")
    now = now_iso()
    fresh = []
    for e in audit_entries(crit):
        if e.get("outcome") != "out-of-scope" or e.get("scope") != "out" or _sev(e) not in ("MAJOR", "MINOR"):
            continue
        q = e.get("quote")
        if not isinstance(q, str) or not q.strip() or not present(paras, q):
            continue  # a sentence changed after critique (verify, trim) is no candidate (review 28 m6)
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
        if isinstance(q, str) and not present(paras, q):
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
