"""check_claims.py's two checks (m1-plan §7.3 · §7.4).

script (`--narration`): s2v lint run by Studio (its length warnings fail; `unread-word` is information here — J32),
0.0.26: every usable image of assets.json shown or given a reason in the claims map's `unused_images`, scene 1 a title
scene (`::title[<frontmatter title>]` its only visual, unless the script has `::thumbnail{src=…}`), and no presenter or
dialogue layout without character art (look.layout_problem, mode "script");
claims-map.json of the expected shape whose claims are the brief's and whose excerpts are in the source copy, no kana
or kanji in the narration (Japanese goes on screen; `s2v sentences` is the narration, `inspect`'s `screen_text` is not
in it), every picture the script shows a usable `script_src` of assets.json, and the checked assets still the ones
record-source recorded.

verify: the fact-checker's `verify.draft.json` — every narration sentence and on-screen text judged, every `fact`
mapped to claims of the claims map with excerpts that are in the source copy, no `unsupported` or `contradicted` —
then `verify.json` (P-STATE) and `verify.md` (made from verify.json: what the person reads is what was judged)."""

import fractions
import json
import math
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
REASON_MAX = 200
END_OF_QUESTION = "end of question"  # the question block's last line (labels.question_block)
CONTROL = re.compile("[\x00-\x1f\x7f-\x9f\u2028\u2029]")
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
    problems += unused_shape_problems(cm.get("unused_images", {}))
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
    origin = origins(sentences, screen, titles)
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
        for c in cited:  # S7: the claim lists this sentence (0.0.28 Q7: the message names the text and where it is)
            if c not in listed.get(key, ()):
                src = s.get("from") if s.get("from") in FROM else origin.get(key, "narration")
                out.append("sentence %d (%s): \"%s\" — %s does not list it in the claims map; add it to that claim's "
                           "sentences" % (n, src, _short(s["text"]), c))
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


FROM = ("narration", "screen", "title")  # where a judged text is in the script (the skeleton's `from`)


def _short(t, n=60):
    t = " ".join(str(t or "").split())
    return t if len(t) <= n else t[:n - 1] + "…"


def origins(sentences, screen, titles=()):
    """{normalized text: narration | screen | title} — the first place a text is in (narration first)."""
    out = {}
    for kind, items in (("narration", [x.get("text") for x in sentences or [] if isinstance(x, dict)]),
                        ("screen", [x.get("text") for x in screen or [] if isinstance(x, dict)]),
                        ("title", list(titles or ()))):
        for t in items:
            if isinstance(t, str) and t.strip():
                out.setdefault(normalize(t), kind)
    return out


KANJI = re.compile("[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")  # CJK ideographs (kanji), not kana


def screen_warnings(screen, cm):
    """0.0.28 Q7 (a hint at the script stage, never a failure): on-screen texts with digits or kanji that no claim of
    the claims map lists — verify judges them, and a fact there needs its claim's `sentences` to list it."""
    claims = (cm or {}).get("claims") if isinstance(cm, dict) else None
    listed = set()
    for c in (claims or {}).values() if isinstance(claims, dict) else []:
        for t in (c.get("sentences") if isinstance(c, dict) and isinstance(c.get("sentences"), list) else []):
            if isinstance(t, str):
                listed.add(normalize(t))
    out, seen = [], set()
    for x in screen or []:
        t = x.get("text") if isinstance(x, dict) else None
        if not isinstance(t, str) or not t.strip() or normalize(t) in listed or normalize(t) in seen:
            continue
        if re.search(r"\d", t) or KANJI.search(t):
            seen.add(normalize(t))
            out.append("on-screen text \"%s\" has digits or kanji and no claim lists it — if it states a fact, add it "
                       "to that claim's sentences" % _short(t))
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


# ---------- excerpts (0.0.28 Q8) ----------

OPEN_TAG = re.compile(r"<([A-Za-z][\w-]*)\b[^<>]*?(/?)>")
CLOSE_TAG = re.compile(r"</([A-Za-z][\w-]*)\s*>")
VOID = ("br", "img", "wbr", "hr", "input", "meta", "link", "source")
SENTENCE_END = "。．.！!？?…"
TRAILERS = "\"'”’」』）)]】*_ \t"


def open_tag_at_end(excerpt):
    """True when the excerpt ends inside a tag (`…<stro`) or with an element still open (`<strong><ruby>緑`)."""
    e = excerpt or ""
    if re.search(r"<[/A-Za-z][^<>]*$", e):  # `3 < 5` is text, not a tag
        return True
    stack = []
    for m in re.finditer(r"</?[A-Za-z][^<>]*>", e):
        tag = m.group(0)
        c = CLOSE_TAG.match(tag)
        if c:
            name = c.group(1).lower()
            if name in stack:
                del stack[len(stack) - 1 - stack[::-1].index(name):]
            continue
        o = OPEN_TAG.match(tag)
        if o and not o.group(2) and o.group(1).lower() not in VOID:
            stack.append(o.group(1).lower())
    return bool(stack)


def _ends_sentence(text):
    t = re.sub(r"</?[A-Za-z][^<>]*>", "", text or "").rstrip(TRAILERS)
    return bool(t) and t[-1] in SENTENCE_END


def stops_mid_sentence(excerpt, copy_raw):
    """True when the excerpt, found as written in the copy, does not end a sentence while its line goes on to one."""
    e = excerpt or ""
    if not e or _ends_sentence(e):
        return False
    i = (copy_raw or "").find(e)
    if i < 0:
        return False  # found only as normalized text: nothing to compare with
    rest = copy_raw[i + len(e):].split("\n", 1)[0]
    rest = re.sub(r"</?[A-Za-z][^<>]*>", "", rest)
    rest = re.sub(r"https?://\S+", "", rest)  # dots inside a URL end no sentence
    return any(ch in SENTENCE_END and (ch != "." or k + 1 == len(rest) or rest[k + 1].isspace())
               for k, ch in enumerate(rest))


def excerpt_problems(cid, excerpt, copy, copy_raw):
    """The --source problems of one claim's excerpt: in the copy, not ending inside a tag or mid-sentence."""
    if copy is None:
        return ["no frozen copy of the source — run state.py record-source"]
    if not copy.contains(excerpt):
        return ["the excerpt of %s is not in the source copy (copy whole sentences as they are, markup included): %s"
                % (cid, _short(excerpt, 80))]
    if open_tag_at_end(excerpt):
        return ["excerpt of %s stops inside a tag — copy up to the end of the sentence, markup included" % cid]
    if stops_mid_sentence(excerpt, copy_raw):
        return ["excerpt of %s stops mid-sentence — copy the whole sentence" % cid]
    return []


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


# s2v lint passes a script whose own timeline estimate is within ±15 % of targetDuration (s2v lint-budget.ts
# TARGET_TOLERANCE). Studio bounds targetDuration so that such a pass puts s2v's estimate inside the format's range
# (0.0.28 Q6: targetDuration 185 let a 157 s estimate pass a 180 s minimum).
S2V_TARGET_TOLERANCE = 0.15


def target_range(ls):
    """(lo, hi): the whole seconds targetDuration may be — ceil(min ÷ 0.85) to floor(max ÷ 1.15) — or None when the
    format's range is too narrow for any (max ÷ min under about 1.353)."""
    tol = fractions.Fraction(str(S2V_TARGET_TOLERANCE))
    lo = math.ceil(fractions.Fraction(str(ls["min"])) / (1 - tol))
    hi = math.floor(fractions.Fraction(str(ls["max"])) / (1 + tol))
    return (lo, hi) if lo <= hi else None


def length_problems(script_text, outputs, crit, sentences, lang, fmt="the format file"):
    """maxDuration is the format's upper bound for every output of the brief, targetDuration lies in target_range
    (so that s2v lint's pass means its estimate is in the format's range), and the narration itself (normalized
    characters ÷ chars_per_sec) is in the format's range too — Studio's own estimate, which catches a far-off script
    before lint. `fmt`: the format file, named when its range is too narrow."""
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
    rng = target_range(ls)
    if rng is None:
        out.append("the format's length range %s–%s s is too narrow for s2v's ±%d %% targetDuration tolerance (max ÷ "
                   "min must be at least about 1.353): a person widens length_seconds in %s"
                   % (ls["min"], ls["max"], round(S2V_TARGET_TOLERANCE * 100), fmt))
    elif target is None or not rng[0] <= target <= rng[1]:
        out.append("targetDuration must be a number within %d–%d s (it is %s): s2v lint passes when its estimate is "
                   "within ±%d %% of targetDuration, and only this range keeps that estimate inside the format's "
                   "%s–%s s — lengthen the script with the brief's claims, never move targetDuration out of it"
                   % (rng[0], rng[1], "missing" if m is None else m.group(1), round(S2V_TARGET_TOLERANCE * 100),
                      ls["min"], ls["max"]))
    if cps:
        n = sum(len(normalize(s.get("text") or "")) for s in sentences or [] if isinstance(s, dict))
        secs = n / float(cps)
        if not ls["min"] <= secs <= ls["max"]:
            out.append("the narration comes to about %.0f s (%d characters ÷ %s per second), outside the format's "
                       "%s–%s s" % (secs, n, cps, ls["min"], ls["max"]))
    else:
        out.append("the format gives no chars_per_sec for %s" % lang)
    return out


# ---------- 0.0.26 (pilot-2 P16 · P17): unused images, the title scene ----------

def reason_problem(src, reason):
    """Why an unused_images reason cannot be shown in the ① question (None when it can)."""
    if not isinstance(reason, str) or not reason.strip():
        return "unused_images %s needs a reason (one line)" % src
    if "\n" in reason or "\r" in reason or CONTROL.search(reason):
        return "unused_images %s: the reason must be one line without control characters" % src
    if len(reason) > REASON_MAX:
        return "unused_images %s: the reason is longer than %d characters" % (src, REASON_MAX)
    if END_OF_QUESTION in reason.lower():
        return "unused_images %s: the reason must not say \"%s\"" % (src, END_OF_QUESTION)
    return None


def sanitize_reason(reason):
    """A reason as `shown 1` prints it, whatever the file says now: one line, no control characters, no "end of
    question", at most REASON_MAX characters."""
    t = " ".join(str(reason or "").split())
    t = CONTROL.sub("", t)
    t = re.sub(re.escape(END_OF_QUESTION), "", t, flags=re.I)
    return " ".join(t.split())[:REASON_MAX]


def unused_shape_problems(ui):
    """The claims map's optional `unused_images`: {script_src: reason}."""
    if not isinstance(ui, dict) or not all(isinstance(k, str) for k in ui):
        return ["unused_images must be an object of script_src → reason"]
    return [p for p in (reason_problem(k, v) for k, v in sorted(ui.items())) if p]


def unused_problems(ins, assets_data, cm):
    """Every usable image of assets.json is shown (any file of inspect) or listed in `unused_images` with a reason."""
    shown = set(f.get("path") for f in ins.get("files") or [] if isinstance(f, dict))
    ui = (cm or {}).get("unused_images") if isinstance(cm, dict) else None
    ui = ui if isinstance(ui, dict) else {}
    usable = [i for i in (assets_data or {}).get("images") or []
              if isinstance(i, dict) and i.get("status") == "ok" and i.get("script_src")]
    out = []
    for i in usable:
        if i["script_src"] not in shown and i["script_src"] not in ui:
            out.append("%s (%s) is usable but not shown — show it with ::image, or give a reason in the claims "
                       "map's unused_images" % (i.get("id") or "an image", i["script_src"]))
    known = set(i["script_src"] for i in usable)
    out += ["unused_images names %s, which is not a usable image of work/assets.json" % k
            for k in sorted(ui) if k not in known]
    return out


FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})")
HEADING1 = re.compile(r"^ {0,3}#(?:[ \t]|$)")
LEAF = re.compile(r"^::([A-Za-z][\w-]*)")
CONTAINER = re.compile(r"^:::([A-Za-z][\w-]*)")
CLOSE = re.compile(r"^:::\s*$")
TITLE = re.compile(r"^::title\[(.*)\](?:\{[^{}]*\})?\s*$")  # the label up to the line's last ] (a title may hold ])


def _body(text):
    """The script's lines after the frontmatter."""
    lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                return lines[i + 1:]
    return lines


def before_first_heading(text):
    """The non-blank lines before the first ATX level-1 heading (outside fences; one-line HTML comments aside): s2v
    puts them into an untitled first scene (parse.ts `implicit-scene`)."""
    out, fence = [], None
    for line in _body(text):
        if fence:
            if re.match(r"^ {0,3}(%s{%d,})\s*$" % (re.escape(fence[0]), len(fence)), line):
                fence = None
            out.append(line)
            continue
        if HEADING1.match(line):
            break
        f = FENCE_OPEN.match(line)
        if f:
            fence = f.group(1)
            out.append(line)
            continue
        if line.strip() and not re.match(r"^\s*<!--.*-->\s*$", line):
            out.append(line)
    return out


def top_directives(text):
    """[(scene index, directive line)] of the directives outside fences and outside container bodies; scenes start at
    ATX level-1 headings only (s2v parse.ts); text before the first heading belongs to no scene (index -1)."""
    out, scene, fence, inside = [], -1, None, False
    for line in _body(text):
        if fence:
            m = re.match(r"^ {0,3}(%s{%d,})\s*$" % (re.escape(fence[0]), len(fence)), line)
            if m:
                fence = None
            continue
        f = FENCE_OPEN.match(line)
        if f:
            fence = f.group(1)
            continue
        if inside:
            if CLOSE.match(line):
                inside = False
            continue
        if HEADING1.match(line):
            scene += 1
            continue
        if CONTAINER.match(line):
            out.append((scene, line))
            inside = True
            continue
        if LEAF.match(line):
            out.append((scene, line))
    return out


def title_scene_problems(text):
    """Scene 1 is the title scene (the thumbnail is its still): its only visual is ::title[<frontmatter title>]. A
    script with ::thumbnail{src=…} gives its own thumbnail (the rule is skipped)."""
    from ..look import title_of
    dirs = top_directives(text)
    if any(LEAF.match(l).group(1) == "thumbnail" for _s, l in dirs if LEAF.match(l)):
        return []
    pre = before_first_heading(text)
    if pre:
        return ["the script has content before its first `# ` heading (%s) — s2v puts it into an untitled first "
                "scene: move it under a `# ` heading" % pre[0].strip()[:40]]
    title = title_of(text)
    if not title:
        return ["add a frontmatter title (it is the thumbnail's title)"]
    first = [l for s, l in dirs if s == 0 and (CONTAINER.match(l) or LEAF.match(l).group(1) not in STAGE_LEAVES)]
    hint = "scene 1 is the title scene: one visual, ::title[%s], after its narration (it becomes the thumbnail)" % title
    if len(first) != 1 or not TITLE.match(first[0]):
        return ["%s — scene 1 shows %s" % (hint, ", ".join(l.split("{")[0][:40] for l in first) or "nothing")]
    label = TITLE.match(first[0]).group(1)
    if normalize(label) != normalize(title):
        return ["%s — its label is %s" % (hint, label[:60])]
    return []


STAGE_LEAVES = ("shot", "enter", "exit")  # stage directions, not visuals (s2v parse.ts)
