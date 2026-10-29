"""check_claims.py's two checks (m1-plan §7.3 · §7.4).

script (`--narration`): s2v lint run by Studio (its length warnings fail; `unread-word` is information here — J32),
claims-map.json of the expected shape whose claims are the brief's and whose excerpts are in the source copy, no kana
or kanji in the narration (Japanese goes on screen; `s2v sentences` is the narration, `inspect`'s `screen_text` is not
in it), every picture the script shows a usable `script_src` of assets.json, and the checked assets still the ones
record-source recorded.

verify: the fact-checker's `verify.draft.json` — every narration sentence and on-screen text judged, every `fact`
mapped to claims of the claims map with excerpts that are in the source copy, no `unsupported` or `contradicted` —
then `verify.json` (P-STATE) and `verify.md` (made from verify.json: what the person reads is what was judged)."""

import json
import os
import re

from ..state import hashes
from ..state.collect import frozen_copy_path
from ..text.normalize import Text, normalize
from . import sourcemd

# kana, kanji and half-width katakana: never in a Korean (or other non-CJK) narration
CJK = re.compile("[぀-ヿㇰ-ㇿ㐀-䶿一-鿿豈-﫿ｦ-ﾟ]")
CJK_LANGS = ("ja", "zh")
KINDS = ("fact", "link")
VERDICTS = ("supported", "unsupported", "contradicted")
PICTURE_KINDS = ("image", "video")


def _read_json(p, what):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f), None
    except OSError:
        return None, "%s is missing" % what
    except ValueError as e:
        return None, "%s is not JSON (%s)" % (what, e)


def _strings(x):
    """A non-empty list of non-blank strings."""
    return isinstance(x, list) and bool(x) and all(isinstance(e, str) and e.strip() for e in x)


def brief_claims(vdir, state):
    """The brief's claim ids (work/brief.json, as long as it is still what record-brief recorded), or (None, why)."""
    from ..state.hashes import brief_core
    b, why = _read_json(os.path.join(vdir, "work", "brief.json"), "work/brief.json")
    if why:
        return None, why
    claims = b.get("claims") if isinstance(b, dict) else None
    roles = (b.get("roles") or []) if isinstance(b, dict) else []
    if not isinstance(claims, list) or not all(isinstance(c, str) for c in claims) or not isinstance(roles, list):
        return None, "work/brief.json has no list of claims"
    try:
        core = brief_core(claims, roles)
    except (AttributeError, TypeError):
        return None, "work/brief.json's roles are not {name, …} objects"
    if core != state["brief"].get("core"):
        return None, "work/brief.json is not the brief record-brief recorded: record it again"
    return claims, None


def copy_text(vdir, state):
    try:
        with open(frozen_copy_path(vdir, state["source"]), encoding="utf-8") as f:
            return Text(f.read())
    except OSError:
        return None


def claims_map(vdir, lang, state, copy):
    """(the claims map, [problems]). Shape: {"claims": {"C-…": {"excerpt": str, "sentences": [str]}},
    "excerpts": [str], "copy_excerpts": {<platform>: [str]}}."""
    cm, why = _read_json(os.path.join(vdir, "work", lang, "claims-map.json"), "work/%s/claims-map.json" % lang)
    if why:
        return None, [why]
    problems = []
    if not isinstance(cm, dict):
        return None, ["the claims map is not an object"]
    claims, excerpts, cx = cm.get("claims"), cm.get("excerpts"), cm.get("copy_excerpts")
    if not isinstance(claims, dict) or not claims:
        problems.append("the claims map has no claims ({\"C-…\": {\"excerpt\", \"sentences\"}})")
        claims = {}
    if not _strings(excerpts):
        problems.append("the claims map has no list of excerpts")
        excerpts = []
    if not isinstance(cx, dict) or not all(_strings(v) or v == [] for v in cx.values()):
        problems.append("copy_excerpts must be an object of platform → [excerpt] ({} until copy)")
    chosen, why = brief_claims(vdir, state)
    if why:
        problems.append(why)
        chosen = []
    listed, src_problems = sourcemd.read(vdir)
    problems += ["work/source.md: %s" % p for p in src_problems]
    for cid, c in sorted(claims.items()):
        if cid not in chosen:
            problems.append("%s is not a claim of the brief" % cid)
        if not isinstance(c, dict) or not isinstance(c.get("excerpt"), str) or not _strings(c.get("sentences")):
            problems.append("%s needs an excerpt and the sentences that say it" % cid)
            continue
        if cid in listed and c["excerpt"] != listed[cid]["excerpt"]:
            problems.append("%s's excerpt is not the one in work/source.md" % cid)
        if c["excerpt"] not in excerpts:
            problems.append("%s's excerpt is not in the claims map's excerpts" % cid)
    if copy is None:
        problems.append("no frozen copy of the source — run state.py record-source")
    else:
        for e in excerpts:
            if not copy.contains(e):
                problems.append("an excerpt is not in the source copy: %s" % e[:80])
    return cm, problems


def narration_problems(sentences, lang):
    if (lang or "").split("-")[0] in CJK_LANGS:
        return []
    out = []
    for s in sentences or []:
        t = s.get("text") if isinstance(s, dict) else None
        if isinstance(t, str) and CJK.search(t):
            out.append("narration %s has kana or kanji (put them on screen; narrate the reading): %s"
                       % (s.get("id"), t[:80]))
    return out


def picture_problems(ins, assets_data):
    usable = set(i.get("script_src") for i in (assets_data or {}).get("images") or []
                 if isinstance(i, dict) and i.get("status") == "ok" and i.get("script_src"))
    out = []
    for f in ins.get("files") or []:
        if not isinstance(f, dict):
            continue
        kinds = str(f.get("kind") or "").split(",")
        if any(k in PICTURE_KINDS for k in kinds) and f.get("path") not in usable:
            out.append("the script shows %s, which is not a usable image of work/assets.json (use its script_src)"
                       % f.get("path"))
    return out


# ---------- verify ----------

def draft_problems(draft, cm, copy, sentences, screen, titles=()):
    """[problems] of the fact-checker's draft. `titles`: the scene titles — they become the copy's chapters, which
    the copy check leaves out (M1h NIT), so a title that states something (the link floor: a number, a term of the
    excerpts, a claims-map sentence) is judged here, at ①."""
    from . import linkrule
    if not isinstance(draft, dict) or not isinstance(draft.get("sentences"), list):
        return ["the draft has no list of sentences ({\"sentences\": [{\"text\", \"kind\", \"verdict\", \"claims\", "
                "\"excerpts\"}]})"]
    out = []
    claims = (cm or {}).get("claims") or {}
    claims = claims if isinstance(claims, dict) else {}
    listed = {}  # normalized sentence → the claims that list it
    for cid, c in claims.items():
        for t in (c.get("sentences") if isinstance(c, dict) and isinstance(c.get("sentences"), list) else []):
            if isinstance(t, str):
                listed.setdefault(normalize(t), set()).add(cid)
    ts = linkrule.terms((cm or {}).get("excerpts") if isinstance((cm or {}).get("excerpts"), list) else [])
    seen, links, judged = set(), 0, 0
    for n, s in enumerate(draft["sentences"], 1):
        if not isinstance(s, dict) or not isinstance(s.get("text"), str) or s.get("kind") not in KINDS:
            out.append("sentence %d needs text and a kind (fact | link)" % n)
            continue
        judged += 1
        key = normalize(s["text"])
        seen.add(key)
        if s.get("verdict") in ("unsupported", "contradicted"):
            out.append("sentence %d is %s: %s" % (n, s["verdict"], s["text"][:80]))
            continue
        if s["kind"] == "link":
            links += 1
            if key in listed:
                out.append("sentence %d is a sentence of claim %s in the claims map — it must be a fact"
                           % (n, ", ".join(sorted(listed[key]))))
            if linkrule.has_number(s["text"]):
                out.append("sentence %d holds a number — it must be a fact: %s" % (n, s["text"][:80]))
            term = linkrule.term_in(s["text"], ts)
            if term:
                out.append("sentence %d uses %s from the excerpts — it must be a fact" % (n, term))
            if not (isinstance(s.get("note"), str) and s["note"].strip()):
                out.append("sentence %d (link) needs a note saying why it states nothing to check" % n)
            continue
        if s.get("verdict") != "supported":
            out.append("sentence %d (fact) has no verdict" % n)
            continue
        ids = s.get("claims")
        if not _strings(ids):
            out.append("sentence %d (fact) is mapped to no claim" % n)
            ids = []
        cited = [c for c in ids if c in claims]
        out += ["sentence %d: %s is not a claim of the claims map" % (n, c) for c in ids if c not in claims]
        for c in cited:  # S7: the claim lists this sentence
            if c not in listed.get(key, ()):
                out.append("sentence %d is not among the sentences of %s in the claims map" % (n, c))
        if not _strings(s.get("excerpts")):
            out.append("sentence %d (fact) quotes no excerpt" % n)
            continue
        own = set(claims[c].get("excerpt") for c in cited if isinstance(claims[c], dict))
        out += ["sentence %d: an excerpt is not the excerpt of a claim it cites: %s" % (n, e[:80])
                for e in s["excerpts"] if e not in own]
        if copy is not None:
            out += ["sentence %d: an excerpt is not in the source copy: %s" % (n, e[:80])
                    for e in s["excerpts"] if not copy.contains(e)]
    cap = max(linkrule.LINK_MAX, int(judged * linkrule.LINK_SHARE))
    if links > cap:
        out.append("%d link sentences — at most %d (a fact-checker states what it cannot support as unsupported)"
                   % (links, cap))
    for t in [x.get("text") for x in sentences or [] if isinstance(x, dict)] + \
             [x.get("text") for x in screen or [] if isinstance(x, dict)]:
        if isinstance(t, str) and t.strip() and normalize(t) not in seen:
            out.append("not judged: %s" % t[:80])
    for t in titles or ():
        if isinstance(t, str) and t.strip() and normalize(t) not in seen and \
                (linkrule.has_number(t) or linkrule.term_in(t, ts) or normalize(t) in listed):
            out.append("not judged: the scene title %s (it states something, and it becomes a chapter of the copy)"
                       % t[:80])
    return out


def verify_json(state, lang, draft, shas):
    return {"schema": 1, "video": state["video"], "lang": lang, "from": shas,
            "sentences": [{k: s.get(k) for k in ("text", "kind", "verdict", "claims", "excerpts", "note")
                           if s.get(k) is not None} for s in draft["sentences"]]}


def verify_md(v):
    facts = [s for s in v["sentences"] if s["kind"] == "fact"]
    links = [s for s in v["sentences"] if s["kind"] == "link"]
    lines = ["# Verify — %s (%s)" % (v["video"], v["lang"]), "",
             "Made by check_claims.py from verify.json (%d fact sentence(s), %d link sentence(s)); every fact is "
             "supported by the source copy." % (len(facts), len(links)), "", "## Facts", ""]
    for n, s in enumerate(facts, 1):
        lines.append("%d. [%s] %s" % (n, s.get("verdict"), s["text"]))
        for c in s.get("claims") or []:
            lines.append("   - claim %s" % c)
        for e in s.get("excerpts") or []:
            lines.append("   > %s" % e.replace("\n", " "))
        if s.get("note"):
            lines.append("   - note: %s" % s["note"])
    lines += ["", "## Link sentences (not checked against the source — read them)", ""]
    for n, s in enumerate(links, 1):
        lines.append("%d. %s" % (n, s["text"]))
        lines.append("   - why a link: %s" % s.get("note"))
    if not links:
        lines.append("(none)")
    return "\n".join(lines) + "\n"


def file_shas(ctx, vdir, lang, state):
    return {"script": hashes.file_sha(ctx["script"]),
            "source_copy": hashes.file_sha(frozen_copy_path(vdir, state["source"])),
            "claims_map": hashes.file_sha(os.path.join(vdir, "work", lang, "claims-map.json")),
            "draft": hashes.file_sha(os.path.join(vdir, "work", lang, "verify.draft.json"))}


# ---------- length (M1e review S6) ----------

def _frontmatter(text):
    if not text.startswith("---"):
        return ""
    end = text.find("\n---", 3)
    return text[3:end] if end > 0 else ""


def _number(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def max_duration(fm, output):
    """The `outputs.<output>.maxDuration` of a frontmatter (inline `{ … }` or a nested block), or None."""
    lines = fm.split("\n")
    for i, line in enumerate(lines):
        m = re.match(r"^(\s+)%s:\s*(.*)$" % re.escape(output), line)
        if not m:
            continue
        found = re.search(r"maxDuration:\s*([0-9.]+)", m.group(2))
        if found:
            return _number(found.group(1))
        for nxt in lines[i + 1:]:
            if not nxt.strip():
                continue
            if len(nxt) - len(nxt.lstrip()) <= len(m.group(1)):
                break
            found = re.match(r"^\s+maxDuration:\s*([0-9.]+)", nxt)
            if found:
                return _number(found.group(1))
    return None


def length_problems(script_text, outputs, crit, sentences, lang):
    """maxDuration is the format's upper bound for every output of the brief, targetDuration lies in the format's
    range, and the narration itself (normalized characters ÷ chars_per_sec) does too."""
    ls, cps = crit["length_seconds"], crit["chars_per_sec"].get(lang)
    fm = _frontmatter(script_text or "")
    out = []
    for o in outputs:
        md = max_duration(fm, o)
        if md != ls["max"]:
            out.append("outputs.%s.maxDuration must be the format's upper bound %s (it is %s)"
                       % (o, ls["max"], "missing" if md is None else md))
    m = re.search(r"^targetDuration:\s*(\S+)", fm, re.M)
    target = _number(m.group(1)) if m else None
    if target is None or not ls["min"] <= target <= ls["max"]:
        out.append("targetDuration must be a number within the format's %s–%s s (it is %s)"
                   % (ls["min"], ls["max"], "missing" if m is None else m.group(1)))
    if cps:
        n = sum(len(normalize(s.get("text") or "")) for s in sentences or [] if isinstance(s, dict))
        secs = n / float(cps)
        if not ls["min"] <= secs <= ls["max"]:
            out.append("the narration comes to about %.0f s (%d characters ÷ %s per second), outside the format's "
                       "%s–%s s" % (secs, n, cps, ls["min"], ls["max"]))
    else:
        out.append("the format gives no chars_per_sec for %s" % lang)
    return out
