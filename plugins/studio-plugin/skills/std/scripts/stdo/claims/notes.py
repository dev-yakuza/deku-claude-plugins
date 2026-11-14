"""Teaching notes (0.1.2, pilot-2 N8): general knowledge a learner needs and the source does not say — a reading, a
grammar rule — marked in the script with a one-line HTML comment right above a narration paragraph or a text card:

    <!-- studio:note -->
    조사로 쓰일 때 이 글자는 와로 읽습니다.

s2v drops the comment (its content hash and sentence ids do not change when the marker has a blank line or a heading
above it), so Studio reads the markers itself and finds the texts they mark in what s2v gives:
- a marked paragraph: the contiguous run of `s2v sentences` whose texts, concatenated, equal its raw lines (both
  normalized, every whitespace character removed: ja/zh sentences are joined without a space);
- a marked card (`:::bullets`, `:::table`, `:::markdown`): the `screen_text` entries of its block — the k-th block of
  that directive in its scene, the scene found by position (the n-th `# ` heading is s2v's n-th scene; the counts must
  agree, and so must the cards per scene: an empty card has no entry and would shift the blocks).

`marked` gives the note texts and the problems (placement, matching, the same-text rule, the caps); the script check,
the verify skeleton and the verify check use it. `blocks` reads the markers only (no s2v): `collect` binds them to ①.
A note text holds no number and is no claims-map sentence (`text_problems`); a term of the excerpts is allowed and
carried to verify (`terms_of`), where the fact-checker's basis names it."""

import re

from ..text.normalize import normalize
from . import check, linkrule

MARKER = re.compile(r"^ {0,3}<!--\s*studio:note\s*-->[ \t]*$")
INDENTED = re.compile(r"^(?: {4,}|\t)\s*<!--\s*studio:note\s*-->[ \t]*$")  # an indented code block in CommonMark
CARDS = ("bullets", "table", "markdown")  # the text cards a marker may mark (a quote reads as the source: never)
SPEAKER = re.compile(r"^[a-z][\w-]*(\{[^}]*\})?:\s")
TEXT_DIRECTIVE = re.compile(r"(^|\s):[A-Za-z][\w-]*[\[{]")
MARKUP = "`*_[]<>\\"
# caps (starting values): marked blocks, note texts (each sentence, bullet item, table cell or markdown block is one),
# normalized characters per text, and the notes' share of the narration's normalized characters
NOTE_BLOCKS_MAX = 4
NOTE_TEXTS_MAX = 8
NOTE_TEXT_MAX = 120
NOTE_SHARE = 0.15

INSIDE = "a teaching-note marker inside a fence or a card marks nothing: put it above the paragraph or the card"
INDENT = "an indented teaching-note marker is a code block, not a marker: start it at the line's beginning"
ABOVE = "leave a blank line above the teaching-note marker: without it s2v splits the paragraph"
BELOW = "a teaching-note marker goes on the line right above a narration paragraph or a text card " \
        "(:::bullets, :::table, :::markdown)"
QUOTE = "a teaching note is never a :::quote: a quote reads as the source"
FIRST = "scene 1 is the title scene (its hook comes from the claims map): no teaching note there"
HIDDEN = "a teaching-note marker inside an HTML comment or HTML block marks nothing: put it, after a blank line, " \
         "above the paragraph or the card"

# Studio's own read of the script, aligned with CommonMark and remark-directive where s2v's parse differs from the
# simpler check.py patterns: a container has 0-3 spaces and 3 or more colons, and closes at a line of at least as
# many colons; a backtick fence's info string holds no backtick; an HTML block is a type-1 (pre, script, style,
# textarea: to its closing tag), type-6 (a block tag name: to a blank line) or type-7 one (a complete tag alone on its
# line, never interrupting a paragraph: to a blank line). A card the walk still misreads is caught by comparing the
# marked card's own text with what s2v shows for it (`found`).
CONTAINER = re.compile(r"^ {0,3}(:{3,})([A-Za-z][\w-]*)")
CLOSE = re.compile(r"^ {0,3}(:{3,})\s*$")
LEAF = re.compile(r"^ {0,3}::([A-Za-z][\w-]*)")
FENCE_OPEN = re.compile(r"^ {0,3}(?:(`{3,})(?!.*`)|(~{3,}))")
HTML1 = re.compile(r"^ {0,3}<(pre|script|style|textarea)(?:[\s>]|$)", re.I)
HTML6 = re.compile(r"^ {0,3}</?(address|article|aside|base|basefont|blockquote|body|caption|center|col|colgroup|dd|"
                   r"details|dialog|dir|div|dl|dt|fieldset|figcaption|figure|footer|form|frame|frameset|h[1-6]|head|"
                   r"header|hr|html|iframe|legend|li|link|main|menu|menuitem|nav|noframes|ol|optgroup|option|p|param|"
                   r"search|section|summary|table|tbody|td|tfoot|th|thead|title|tr|track|ul)(?:[\s>]|/>|$)", re.I)
HTML7 = re.compile(r"^ {0,3}(?:<[A-Za-z][\w-]*(?:\s+[A-Za-z_:][\w.:-]*(?:\s*=\s*(?:[^\s\"'=<>`]+|'[^']*'|\"[^\"]*\"))?)*"
                   r"\s*/?>|</[A-Za-z][\w-]*\s*>)\s*$")


def _ws_free(text):
    return re.sub(r"\s+", "", normalize(text or ""))


def _paragraph_end(line):
    """True when `line` ends a paragraph a marker marks (Studio's read of where s2v's paragraph stops)."""
    return not line.strip() or bool(check.HEADING1.match(line) or CONTAINER.match(line) or LEAF.match(line) or
                                     FENCE_OPEN.match(line) or MARKER.match(line))


def _raw_problems(lines):
    """A marked paragraph is plain text, checked on its raw lines (normalize strips markup)."""
    out = []
    for l in lines:
        if SPEAKER.match(l.strip()):
            out.append("a teaching note has no speaker prefix (the default narrator says it): %s" % l.strip()[:40])
        if TEXT_DIRECTIVE.search(l):
            out.append("a teaching note holds no text directive: %s" % l.strip()[:40])
        bad = sorted(set(c for c in l if c in MARKUP))
        if bad:
            out.append("keep a teaching note plain — no %s: %s" % (" ".join(bad), l.strip()[:40]))
    return out


COMMENT_OPEN = re.compile(r"^ {0,3}<!--")
SETEXT1 = re.compile(r"^ {0,3}=+[ \t]*$")
HEADING_ID = re.compile(r"\s*\{#[\w-]+\}\s*$")


def heading_text(line):
    """The title of an ATX level-1 heading line as s2v shows it, normalized: CommonMark drops the closing `#`s first
    (only at the line's end: `# a ## {#x}` keeps `a ##`), then the `{#id}`; backslash escapes are text (`\\#`)."""
    t = re.sub(r"^ {0,3}#[ \t]*", "", line)
    t = re.sub(r"(?:^|[ \t]+)#+[ \t]*$", "", t)
    t = HEADING_ID.sub("", t)
    t = re.sub(r"\\([!-/:-@\[-`{-~])", r"\1", t)
    return normalize(t)


def scan(script_text):
    """(blocks, headings, cards, problems, setext, empties) of the script's markers, without s2v. A block: {"kind":
    "paragraph" | "card", "scene": the index of its `# ` heading (-1 before the first), "lines": its raw lines, "name":
    the card's directive, "k": the card's index among the scene's top-level cards of that name, "line": the marker's
    line}. `headings`: the normalized titles of the top-level `# ` headings; `cards`: {(scene, name): count} of every
    top-level card; `setext`: the number of underlined level-1 headings (s2v starts a scene there, Studio does not);
    `empties`: the (scene, name) of the cards with nothing inside.
    The walk follows check.top_directives (a fence first — also inside a card, where it hides a `:::` —, then the
    card); a multi-line HTML comment or an HTML block hides its lines (a `# ` there is no heading)."""
    lines = check._body(script_text)
    blocks, problems, cards, heads, empties = [], [], {}, [], set()
    scene, fence, inside, comment, html, setext = -1, None, 0, False, None, 0
    card, filled = None, False
    i = 0
    while i < len(lines):
        line = lines[i]
        if fence:
            if re.match(r"^ {0,3}(%s{%d,})\s*$" % (re.escape(fence[0]), len(fence)), line):
                fence = None
            elif MARKER.match(line) or INDENTED.match(line):
                problems.append(INSIDE)
            filled = True
            i += 1
            continue
        f = FENCE_OPEN.match(line)
        if f and not comment and not html:
            fence = f.group(1) or f.group(2)
            filled = True
            i += 1
            continue
        if inside:
            c = CLOSE.match(line)
            if c and len(c.group(1)) >= inside:
                if not filled:
                    empties.add(card)
                inside = 0
            elif MARKER.match(line) or INDENTED.match(line):
                problems.append(INSIDE)
            elif line.strip():
                filled = True
            i += 1
            continue
        if comment:  # an HTML comment ends at the first line with -->
            if MARKER.match(line):
                problems.append(HIDDEN)
            if "-->" in line:
                comment = False
            i += 1
            continue
        if html:  # an HTML block ends at its closing tag (type 1) or a blank line
            if MARKER.match(line) or INDENTED.match(line):
                problems.append(HIDDEN)
            if (html == "blank" and not line.strip()) or (html != "blank" and re.search(r"</%s\s*>" % html, line, re.I)):
                html = None
            i += 1
            continue
        if COMMENT_OPEN.match(line) and not MARKER.match(line):
            if "-->" not in line[line.index("<!--") + 4:]:
                comment = True
            i += 1
            continue
        h1 = HTML1.match(line)
        if h1:
            html = None if re.search(r"</%s\s*>" % h1.group(1), line, re.I) else h1.group(1)
            i += 1
            continue
        if HTML6.match(line) or (HTML7.match(line) and not (i and lines[i - 1].strip())):
            html = "blank"
            i += 1
            continue
        if SETEXT1.match(line) and i and lines[i - 1].strip() and not check.HEADING1.match(lines[i - 1]):
            setext += 1
            i += 1
            continue
        if check.HEADING1.match(line):
            scene += 1
            heads.append(heading_text(line))
            i += 1
            continue
        c = CONTAINER.match(line)
        if c:
            card = (scene, c.group(2))
            cards[card] = cards.get(card, 0) + 1
            inside, filled = len(c.group(1)), False
            i += 1
            continue
        if INDENTED.match(line):
            problems.append(INDENT)
            i += 1
            continue
        if not MARKER.match(line):
            i += 1
            continue
        above = lines[i - 1] if i else ""
        nxt = lines[i + 1] if i + 1 < len(lines) else None
        ok = True
        if above.strip() and not check.HEADING1.match(above):
            problems.append(ABOVE)
            ok = False
        nc = CONTAINER.match(nxt) if nxt is not None else None
        name = nc.group(2) if nc else None
        if name == "quote":
            problems.append(QUOTE)
            ok = False
        elif nc and name not in CARDS:
            problems.append(BELOW)
            ok = False
        elif nxt is None or (not nc and _paragraph_end(nxt)) or check.HEADING1.match(nxt) or \
                re.match(r"^\s*#", nxt) or re.match(r"^\s*<!--", nxt):
            problems.append(BELOW)
            ok = False
        if nc and name in CARDS:
            if ok:
                body, j = [], i + 2
                while j < len(lines) and not (CLOSE.match(lines[j]) and
                                              len(CLOSE.match(lines[j]).group(1)) >= len(nc.group(1))):
                    body.append(lines[j])
                    j += 1
                blocks.append({"kind": "card", "scene": scene, "name": name,
                               "k": cards.get((scene, name), 0), "lines": [nxt] + body, "line": i + 1})
            i += 1  # the container line itself is counted by the walk
            continue
        if ok:
            para, j = [], i + 1
            while j < len(lines) and not _paragraph_end(lines[j]):
                para.append(lines[j])
                j += 1
            raw = _raw_problems(para)
            problems += raw
            if not raw:
                blocks.append({"kind": "paragraph", "scene": scene, "lines": para, "line": i + 1})
        i += 1
    return blocks, heads, cards, problems, setext, empties


def card_text(name, body):
    """A card's own text as s2v shows it, normalized without whitespace: a table without its pipes and separator row,
    a list or markdown body without its markers (normalize drops them)."""
    if name == "table":
        body = [re.sub(r"\|", " ", l) for l in body if not re.match(r"^\s*\|?\s*:?-{2,}", l)]
    return "".join(_ws_free(l) for l in body)


def blocks(script_text):
    """The ordered normalized raw texts of the marked blocks (markers only, no s2v): what ① binds (`collect`)."""
    return [normalize("\n".join(b["lines"])) for b in scan(script_text)[0]]


def _run(sentences, start, target):
    """(i, j) of the first contiguous run of sentences from `start` whose texts, concatenated, equal `target`."""
    texts = [_ws_free(s.get("text") if isinstance(s, dict) else "") for s in sentences]
    for i in range(start, len(texts)):
        acc = ""
        for j in range(i, len(texts)):
            acc += texts[j]
            if acc == target:
                return i, j + 1
            if not target.startswith(acc):
                break
    return None


def found(script_text, sentences, inspect):
    """{"notes": [{"text", "from": "narration" | "screen"}], "problems": [...]} — every check of `marked` but the text
    rules (numbers, claims-map sentences: `text_problems`)."""
    sentences = [s for s in sentences or [] if isinstance(s, dict)]
    ins = inspect if isinstance(inspect, dict) else {}
    screen = [e for e in ins.get("screen_text") or [] if isinstance(e, dict)]
    blks, heads, cards, problems, setext, empties = scan(script_text)
    notes, note_sent, note_entries = [], set(), set()
    cursor = 0
    scenes = [x for x in ins.get("scenes") or [] if isinstance(x, dict)]
    scene_ids = [x.get("id") for x in scenes]
    # s2v's scene 1 (the title scene) is its implicit scene when the script has text before its first `# ` heading
    # (an untitled first scene, one more than the headings); otherwise the first heading's
    implicit = len(scenes) == len(heads) + 1 and not str(scenes[0].get("title") or "").strip()
    first = [b for b in blks if b["scene"] < 0 or (b["scene"] == 0 and not implicit)]
    if first:
        problems.append(FIRST)
        blks = [b for b in blks if b not in first]
    mapped = True
    if any(b["kind"] == "card" for b in blks):
        # a marked card is found by its scene: the n-th `# ` heading must be s2v's n-th scene, by its title too (a count
        # alone can be cancelled out — an underlined heading against a `# ` hidden in a comment)
        titles = [normalize(x.get("title") or "") for x in scenes]
        why = []
        if setext:
            why.append("an underlined heading (a line of = below a text) starts an s2v scene: write `# <title>`")
        if any(not t for t in titles):
            why.append("s2v has an untitled scene (text before the first `# ` heading, as a lead-in with "
                       "::thumbnail makes)")
        if len(titles) != len(heads):
            why.append("s2v sees %d scene(s), the script has %d `# ` heading(s)" % (len(titles), len(heads)))
        else:
            why += ["scene %d: the script's `# %s` is s2v's \"%s\"" % (n + 1, h, t)
                    for n, (h, t) in enumerate(zip(heads, titles)) if h != t]
        if why:
            mapped = False
            problems.append("a marked card is found by its scene, and the scenes do not match s2v's: %s — start every "
                            "scene with a `# ` heading" % "; ".join(why))
    counts_checked = set()
    for b in blks:
        if b["kind"] == "paragraph":
            target = _ws_free("\n".join(b["lines"]))
            r = _run(sentences, cursor, target) if target else None
            if r is None:
                problems.append("the marked paragraph does not match s2v's sentences: keep a teaching note plain (%s)"
                                % " ".join(b["lines"]).strip()[:40])
                continue
            cursor = r[1]
            for k in range(r[0], r[1]):
                note_sent.add(k)
                notes.append({"text": sentences[k]["text"], "from": "narration"})
            continue
        if not mapped:
            continue
        sid, name = scene_ids[b["scene"]], b["name"]
        mine = [n for n, e in enumerate(screen) if e.get("scene") == sid and e.get("directive") == name]
        order = sorted(set(screen[n].get("block") for n in mine if isinstance(screen[n].get("block"), int)))
        want = cards.get((b["scene"], name), 0)
        if (b["scene"], name) not in counts_checked:
            counts_checked.add((b["scene"], name))
            if len(order) != want:
                problems.append("scene %d has %d :::%s card(s) but s2v shows %d — an empty card? fill or remove it"
                                % (b["scene"] + 1, want, name, len(order)))
        if len(order) != want:
            continue
        if (b["scene"], name) in empties:
            problems.append("scene %d has an empty :::%s card besides a marked one — fill or remove it"
                            % (b["scene"] + 1, name))
            continue
        idx = [n for n in mine if screen[n].get("block") == order[b["k"]]]
        texts = [n for n in idx if isinstance(screen[n].get("text"), str) and screen[n]["text"].strip()]
        if not texts:
            problems.append("the marked :::%s card in scene %d shows nothing on screen" % (name, b["scene"] + 1))
            continue
        # the root guard: what s2v shows for the mapped block is the marked card's own text, whatever the walk read
        shown = "".join(_ws_free(screen[n].get("text") if isinstance(screen[n].get("text"), str) else "")
                        for n in idx)
        if shown != card_text(name, b["lines"][1:]):
            problems.append("the marked :::%s card in scene %d is not the card s2v shows in its place (%s) — keep "
                            "the cards plain: no indent, three colons, nothing that hides a card"
                            % (name, b["scene"] + 1, check._short(" / ".join(screen[n]["text"] for n in texts), 40)))
            continue
        for n in texts:
            note_entries.add(n)
            notes.append({"text": screen[n]["text"], "from": "screen"})
    # the same text a note in one place and not in another (by occurrence)
    occ = {}
    for k, s in enumerate(sentences):
        if isinstance(s.get("text"), str) and s["text"].strip():
            occ.setdefault(normalize(s["text"]), set()).add(k in note_sent)
    for n, e in enumerate(screen):
        if e.get("directive") != "paragraph" and isinstance(e.get("text"), str) and e["text"].strip():
            occ.setdefault(normalize(e["text"]), set()).add(n in note_entries)
    for x in ins.get("scenes") or []:
        t = x.get("title") if isinstance(x, dict) else None
        if isinstance(t, str) and t.strip():
            occ.setdefault(normalize(t), set()).add(False)
    seen = set()
    for x in notes:
        k = normalize(x["text"])
        if k not in seen and occ.get(k) == {True, False}:
            seen.add(k)
            problems.append("\"%s\" is a teaching note in one place and not in another" % check._short(x["text"]))
    problems += cap_problems(blks, notes, sentences)
    return {"notes": notes, "problems": problems}


def cap_problems(blks, notes, sentences):
    out = []
    if len(blks) > NOTE_BLOCKS_MAX:
        out.append("%d marked teaching-note blocks — at most %d" % (len(blks), NOTE_BLOCKS_MAX))
    if len(notes) > NOTE_TEXTS_MAX:
        out.append("%d teaching-note texts — at most %d (each sentence, bullet, table cell or markdown block counts)"
                   % (len(notes), NOTE_TEXTS_MAX))
    for x in notes:
        if len(normalize(x["text"])) > NOTE_TEXT_MAX:
            out.append("a teaching note is longer than %d characters: %s" % (NOTE_TEXT_MAX, check._short(x["text"])))
    total = sum(len(normalize(s.get("text") or "")) for s in sentences)
    mine = sum(len(normalize(x["text"])) for x in notes if x["from"] == "narration")
    if total and mine > total * NOTE_SHARE:
        out.append("teaching notes are %d %% of the narration — at most %d %%: notes are never the way to reach the "
                   "length" % (round(100.0 * mine / total), round(NOTE_SHARE * 100)))
    return out


def marked(script_text, sentences, inspect):
    """(ordered note texts, problems): placement, matching, the same-text rule and the caps."""
    r = found(script_text, sentences, inspect)
    return [x["text"] for x in r["notes"]], r["problems"]


def listed(cm):
    """{normalized claims-map sentence}."""
    claims = (cm or {}).get("claims") if isinstance(cm, dict) else None
    out = set()
    for c in (claims or {}).values() if isinstance(claims, dict) else []:
        for t in (c.get("sentences") if isinstance(c, dict) and isinstance(c.get("sentences"), list) else []):
            if isinstance(t, str):
                out.add(normalize(t))
    return out


def text_problems(texts, cm):
    """A note text holds no number or date and is not a claim's sentence."""
    out, sentences = [], listed(cm)
    for t in texts:
        if linkrule.has_number(t):
            out.append("a teaching note never holds a number or a date: %s" % check._short(t))
        if normalize(t) in sentences:
            out.append("a text is either a claim's sentence or a teaching note: %s" % check._short(t))
    return out


def excerpt_terms(cm):
    ex = (cm or {}).get("excerpts") if isinstance(cm, dict) else None
    return linkrule.terms(ex if isinstance(ex, list) else [])


def terms_of(text, cm, ts=None):
    """The excerpt terms a note holds (sorted): the basis must name each (verify), and ① shows them."""
    return linkrule.terms_in(text, excerpt_terms(cm) if ts is None else ts)
