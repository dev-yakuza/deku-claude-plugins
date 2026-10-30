"""`validate_copy.py <video> --platform <p>` (m1-plan §10): the platform copy `<sr>/copy/<v>/<l>/<p>.md` —

    ---
    title: "<title>"
    hashtags: ["#a", "#b"]
    ---
    <description: chapters, credits, required notices …>

is checked against the platform's rules (rules.py): the platform file is `checked` by a person; title, description and
hashtag counts within the limits; every required notice and every CREDITS `credit_line` in the description; the
render's chapters (`<o>.<l>[.proxy].chapters.txt` of each output the platform uses) in the description, line by line
in order; no home path; no in-house term of the internal overlay; and the copy's excerpts (claims-map `copy_excerpts`,
filled by the fact-checker) all in the source copy — ④b records them."""

import json
import os
import re

from .. import credits
from ..commit.harness import overlay_terms, term_hit
from ..state import schema
from . import factcheck, rules as rules_mod

ANGLE = re.compile(r"[<>]")  # the YouTube Data API forbids < and > in snippet.title and snippet.description
HOME = re.compile(r"/Users/[^/\s]+|/home/[^/\s]+|(?<![\w.])~/|[A-Za-z]:\\Users\\")
HASHTAG = re.compile(r"^#[^\s#]+$")


def parse_copy(text):
    """(title, hashtags, description) — raises ValueError."""
    if not text.startswith("---"):
        raise ValueError("the copy has no frontmatter (title, hashtags)")
    end = text.find("\n---", 3)
    if end < 0:
        raise ValueError("the copy's frontmatter does not end")
    head, body = text[3:end], text[end + 4:].lstrip("\n")
    m = re.search(r"^title:\s*(.+?)\s*$", head, re.M)
    if not m:
        raise ValueError("the copy has no title")
    title = m.group(1)
    if len(title) >= 2 and title[0] in "\"'" and title[-1] == title[0]:
        title = title[1:-1]
    h = re.search(r"^hashtags:\s*(\[.*?\])\s*$", head, re.M)
    try:
        tags = json.loads(h.group(1)) if h else []
    except ValueError:
        raise ValueError("hashtags must be a JSON list on one line")
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        raise ValueError("hashtags must be a list of text")
    return title, tags, body


def chapter_files(ctx, state, lang, platform):
    L = state["langs"][lang]
    out_dir = os.path.join(ctx["repo"], ctx["studio_root"], "out", state["video"], lang)
    files = []
    for o in sorted(x for x in state["brief"]["platforms"].get(platform, []) if x in schema.current_outputs(state,
                                                                                                            lang)):
        proxy = bool(L["renders"].get(o, {}).get("proxy"))
        files.append(os.path.join(out_dir, "%s.%s.%schapters.txt" % (o, lang, "proxy." if proxy else "")))
    return files


def in_order(lines, body):
    pos = 0
    for l in lines:
        i = body.find(l, pos)
        if i < 0:
            return l
        pos = i + len(l)
    return None


def problems(repo, vdir, state, lang, ctx, platform, cfg, env, copy_path):
    out = []
    try:
        rules, checked = rules_mod.read(repo, platform)
    except rules_mod.RulesProblem as e:
        return ["the platform rules: %s — a person fixes .claude/studio/platforms/%s.md" % (e, platform)]
    if not checked:
        out.append("platforms/%s.md is not checked yet (its `checked` date is empty): a person compares it with the "
                   "platform's own help and fills it in (U-M1h)" % platform)
    try:
        with open(copy_path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return out + ["the copy %s is missing" % os.path.relpath(copy_path, repo)]
    try:
        title, tags, body = parse_copy(text)
    except ValueError as e:
        return out + [str(e)]
    if not title.strip() or len(title) > rules["title_max"]:
        out.append("the title has %d characters (1–%d)" % (len(title), rules["title_max"]))
    size = len(body.encode("utf-8"))  # bytes, not characters (the Data API's limit; Korean is about 3 bytes each)
    if size > rules["description_max_bytes"]:
        out.append("the description is %d bytes in UTF-8 (at most %d bytes)"
                   % (size, rules["description_max_bytes"]))
    if len(tags) > rules["hashtags_max"]:
        out.append("%d hashtags (at most %d)" % (len(tags), rules["hashtags_max"]))
    out += ["%r is not one hashtag (#word, no spaces)" % t for t in tags if not HASHTAG.match(t)]
    out += ["the required notice is missing: %s" % r for r in rules["required"] if r not in body]
    cred, why = credits.read(os.path.join(vdir, credits.FILE))
    if why:
        out.append(why)
    out += ["the credit line of %s is missing: %s" % (p, e.get("credit_line")) for p, e in sorted((cred or {}).items())
            if isinstance(e.get("credit_line"), str) and e["credit_line"] not in body]
    for p in chapter_files(ctx, state, lang, platform):
        try:
            with open(p, encoding="utf-8") as f:
                lines = [l.rstrip() for l in f.read().splitlines() if l.strip()]
        except OSError:
            continue  # this output has no chapters (one scene, or not 16:9)
        miss = in_order(lines, body)
        if miss is not None:
            out.append("the chapters are not the render's (%s): missing or out of order: %s"
                       % (os.path.basename(p), miss))
    if ANGLE.search(title + body):
        out.append("the copy has < or > (no HTML or placeholders on a platform)")
    if HOME.search(text):
        out.append("the copy shows a home path (%s)" % HOME.search(text).group(0))
    st, terms = overlay_terms(repo, cfg, env)
    if st == "missing":
        out.append("the internal overlay is missing or changed — the person recreates it (/std config)")
    hit = term_hit(text, terms) if terms else None
    if hit:
        out.append("the copy uses an in-house term (%s)" % hit)
    chapter_lines = []
    for p in chapter_files(ctx, state, lang, platform):
        try:
            with open(p, encoding="utf-8") as f:
                chapter_lines += [l.rstrip() for l in f.read().splitlines() if l.strip()]
        except OSError:
            pass
    skip = chapter_lines + list(rules["required"]) + [e.get("credit_line") for e in (cred or {}).values()
                                                       if isinstance(e.get("credit_line"), str)]
    out += excerpt_problems(vdir, lang, state, platform, factcheck.sentences(title, body, skip))
    return out


def excerpt_problems(vdir, lang, state, platform, own):
    from ..claims.check import copy_text
    try:
        with open(os.path.join(vdir, "work", lang, "claims-map.json"), encoding="utf-8") as f:
            cm = json.load(f)
    except (OSError, ValueError):
        return ["work/%s/claims-map.json is missing or not JSON" % lang]
    ex = ((cm or {}).get("copy_excerpts") or {}).get(platform) if isinstance(cm, dict) else None
    out = []
    if not isinstance(ex, list) or not ex or not all(isinstance(e, str) and e.strip() for e in ex):
        out.append("claims-map copy_excerpts.%s is empty: the fact-checker lists the excerpts the copy rests on"
                   % platform)
        ex = []
    copy = copy_text(vdir, state)
    if copy is None:
        return out + ["no frozen copy of the source"]
    out += ["a copy excerpt is not in the source copy: %s" % e[:80] for e in ex if not copy.contains(e)]
    return out + factcheck.problems(vdir, lang, platform, cm, copy, own)

