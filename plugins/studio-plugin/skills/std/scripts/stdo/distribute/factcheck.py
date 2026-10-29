"""The copy's own facts (M1h review Y2): the link floor of check_claims (claims/linkrule.py) applied to the copy.

The title and the description are split into sentences (chapter lines, credit lines and required notices are not
sentences of the copy's own). A sentence that holds a number, a term of the claims map's excerpts, or a sentence of the
claims map must be judged by the fact-checker in `work/<l>/copy-verify.<p>.json`:

    {"sentences": [{"text": "<the sentence>", "kind": "fact", "verdict": "supported", "excerpts": ["<exact>"]}, …]}

with excerpts that are in the source copy; no entry may be unsupported or contradicted; and the claims map's
`copy_excerpts.<p>` must be exactly the union of the fact entries' excerpts (④b records them, and the source diff
judges the copy by them)."""

import json
import os
import re

from ..claims import linkrule
from ..text.normalize import normalize

SPLIT = re.compile(r"(?<=[.!?。？！])\s+|\n+")


def path(vdir, lang, platform):
    from ..state.schema import platform_ok
    if not platform_ok(platform):
        raise ValueError("%r is not a platform name" % (platform,))
    return os.path.join(vdir, "work", lang, "copy-verify.%s.json" % platform)


def sentences(title, body, skip):
    """The copy's own sentences: the title, then the description without the lines in `skip`. The chapter lines are
    skipped because they are the script's scene titles, which the script verify already judged at ① (check_claims
    covers every on-screen text, scene titles included) — that is where a fact in a chapter title is caught."""
    text = body
    for s in sorted((x for x in skip if x), key=len, reverse=True):
        text = text.replace(s, "\n")
    out = [title.strip()] if title.strip() else []
    out += [x.strip() for x in SPLIT.split(text) if x.strip() and normalize(x)]
    return out


def must_be_fact(sentence, terms, listed):
    return linkrule.has_number(sentence) or bool(linkrule.term_in(sentence, terms)) or normalize(sentence) in listed


def problems(vdir, lang, platform, cm, copy, own):
    """[problems] of the copy's facts. `cm`: the claims map; `copy`: the source copy (Text); `own`: the copy's
    sentences."""
    out = []
    try:
        with open(path(vdir, lang, platform), encoding="utf-8") as f:
            draft = json.load(f)
    except (OSError, ValueError):
        draft = None
    entries = draft.get("sentences") if isinstance(draft, dict) else None
    if not isinstance(entries, list):
        entries = []
        out.append("work/%s/copy-verify.%s.json is missing or has no list of sentences: the fact-checker judges the "
                   "copy" % (lang, platform))
    claims = (cm or {}).get("claims") if isinstance(cm, dict) else None
    listed = set()
    for c in (claims or {}).values() if isinstance(claims, dict) else []:
        for t in (c.get("sentences") or []) if isinstance(c, dict) else []:
            if isinstance(t, str):
                listed.add(normalize(t))
    terms = linkrule.terms((cm or {}).get("excerpts") if isinstance((cm or {}).get("excerpts"), list) else [])
    judged, union = {}, []
    for n, e in enumerate(entries, 1):
        if not isinstance(e, dict) or not isinstance(e.get("text"), str):
            out.append("copy-verify sentence %d has no text" % n)
            continue
        if e.get("verdict") in ("unsupported", "contradicted"):
            out.append("the copy says something %s: %s" % (e["verdict"], e["text"][:80]))
            continue
        if e.get("kind") != "fact" or e.get("verdict") != "supported":
            continue
        ex = e.get("excerpts")
        if not isinstance(ex, list) or not ex or not all(isinstance(x, str) and x.strip() for x in ex):
            out.append("copy-verify: %s quotes no excerpt" % e["text"][:80])
            continue
        bad = [x for x in ex if copy is None or not copy.contains(x)]
        if bad:
            out.append("copy-verify: an excerpt is not in the source copy: %s" % bad[0][:80])
            continue
        judged[normalize(e["text"])] = e
        union += [x for x in ex if x not in union]
    for s in own:
        if must_be_fact(s, terms, listed) and normalize(s) not in judged:
            out.append("a sentence of the copy states something to check and is not judged (copy-verify): %s"
                       % s[:80])
    cx = ((cm or {}).get("copy_excerpts") or {}).get(platform) if isinstance(cm, dict) else None
    if not isinstance(cx, list) or sorted(set(cx)) != sorted(set(union)):
        out.append("claims-map copy_excerpts.%s must be exactly the excerpts of copy-verify's facts" % platform)
    return out


def fact_lines(vdir, lang, platform):
    """`근거: "<sentence>" ← "<excerpt>" / …` for every judged fact of the copy (the ④b question shows them)."""
    try:
        with open(path(vdir, lang, platform), encoding="utf-8") as f:
            entries = (json.load(f) or {}).get("sentences") or []
    except (OSError, ValueError, AttributeError):
        return []
    return ["근거: \"%s\" ← %s" % (e["text"], " / ".join("\"%s\"" % x.replace("\n", " ") for x in e.get("excerpts")
                                                      or []))
            for e in entries if isinstance(e, dict) and e.get("kind") == "fact" and isinstance(e.get("text"), str)]
