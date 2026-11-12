"""The frontmatter lines `state.py next <video> --enter script` prints for the writer (0.0.28 Q2 · Q4 · Q5): the
default narrator's cast block — part of the script from the start, since s2v's content hash includes the cast (core
inspect.ts) — and each output's `aspect` (from the platform file) with `maxDuration` (the format's upper bound),
plus the range targetDuration must lie in (claims.check.target_range)."""

import json
import os
import re

from .. import criteria, narrator
from ..voice import frontmatter

OUT_NAME = re.compile(r"^\s*-\s*name:\s*[\"']?([^\"'\s]+)[\"']?\s*$")
OUT_KEY = re.compile(r"^\s+([A-Za-z_]+):\s*(.*?)\s*$")


class NotReady(Exception):
    """The default narrator cannot be written into a script yet (exit 1: narrator setup first)."""


def default_narrator(repo, root):
    """(id, status) of the default narrator init recorded: `<root>/cast/narrator/`, else the only folder of cast/
    (init's `narrator.id`); (None, None) when there is none or more than one."""
    base = os.path.join(repo, root, "cast")
    try:
        names = sorted(n for n in os.listdir(base) if os.path.isfile(os.path.join(base, n, "status.json")))
    except OSError:
        names = []
    nid = "narrator" if "narrator" in names else (names[0] if len(names) == 1 else None)
    if nid is None:
        return None, None
    try:
        with open(os.path.join(base, nid, "status.json"), "rb") as f:
            return nid, narrator.parse(f.read())
    except OSError:
        return nid, None


def cast_lines(repo, root, lang):
    """The `cast:` block of the default narrator for `lang` (NotReady when it has no ready voice)."""
    nid, st = default_narrator(repo, root)
    hint = "run the narrator setup of /std init (or /std config narrator) first"
    if nid is None:
        raise NotReady("no default narrator in %s/cast/ — %s" % (root, hint))
    v = ((st or {}).get("voice") or {}).get(lang) if isinstance(st, dict) else None
    if not isinstance(v, dict) or v.get("state") != "ready" or not narrator.engine_ok(v.get("engine")):
        raise NotReady("%s/cast/%s/status.json has no ready voice.%s — %s" % (root, nid, lang, hint))
    style = v.get("style") or ""
    if not isinstance(style, str) or not frontmatter.style_ok(style, narrator.STYLE_MAX):
        raise NotReady("%s/cast/%s: the style of voice.%s holds \" or \\ or a line break — %s"
                       % (root, nid, lang, hint))
    spec = 'voice: "%s"' % v["engine"] + (', style: "%s"' % style if style else "")  # an empty style is none
    return ["cast:", "  narrator: { %s }" % spec]


def platform_aspects(repo, platforms):
    """{output: aspect} from the `outputs` list in the frontmatter of the brief's platform files."""
    from ..distribute import rules
    out = {}
    for p in platforms:
        try:
            with open(rules.path(repo, p), encoding="utf-8") as f:
                text = f.read()
        except (OSError, rules.RulesProblem):
            continue
        if not text.startswith("---"):
            continue
        end = text.find("\n---", 3)
        cur = None
        for line in text[3:end if end > 0 else len(text)].split("\n"):
            m = OUT_NAME.match(line)
            if m:
                cur = m.group(1)
                continue
            k = OUT_KEY.match(line)
            if cur and k and k.group(1) == "aspect":
                val = k.group(2).strip("\"'")
                if re.match(r"^\d+:\d+$", val):
                    out.setdefault(cur, val)
            elif not line.startswith(" "):
                cur = None
    return out


def output_lines(repo, kind, outputs, platforms):
    """(lines, notes): `outputs:` with each output's aspect and maxDuration, then the targetDuration range."""
    from ..claims.check import S2V_TARGET_TOLERANCE, target_range
    crit = criteria.read(repo, kind)  # criteria.Missing: the caller stops
    ls = crit["length_seconds"]
    aspects = platform_aspects(repo, platforms)
    lines, notes = ["outputs:"], []
    for o in outputs:
        a = aspects.get(o)
        if a is None:
            notes.append("no aspect for output %s in the brief's platform files" % o)
        lines.append("  %s: { %smaxDuration: %s }" % (o, 'aspect: "%s", ' % a if a else "", json.dumps(ls["max"])))
    rng = target_range(ls)
    fmt = os.path.relpath(criteria.path(repo, kind), repo)
    if rng is None:
        notes.append("the format's length range %s–%s s is too narrow for s2v's ±%d %% tolerance: a person widens "
                     "length_seconds in %s" % (ls["min"], ls["max"], round(S2V_TARGET_TOLERANCE * 100), fmt))
    else:
        lines.append("targetDuration: <%d–%d, from the brief's estimate>" % rng)
    return lines, notes
