"""A video kind's criteria (m1-plan §7.2 · §8, D-M1-11 · D-M1-19): the JSON block between `<!-- studio:criteria -->` and
`<!-- /studio:criteria -->` in `.claude/studio/formats/<kind>.md` (P-CRIT: only a person changes it). Read-only."""

import json
import math
import os
import re

BLOCK = re.compile(r"<!-- studio:criteria -->\s*```json\s*\n(.*?)\n```\s*<!-- /studio:criteria -->", re.S)
KEYS = ("length_seconds", "chars_per_sec", "cer_max")


class Missing(Exception):
    """No readable criteria (the checks that need them fail closed)."""


def path(repo, kind):
    return os.path.join(repo, ".claude", "studio", "formats", "%s.md" % kind)


def _no_constant(name):
    raise ValueError("%s is not a number Studio accepts" % name)


def _number(x):
    """A finite int or float that is not a bool (JSON true/false are not numbers here)."""
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def parse(text, langs=()):
    """The criteria (Missing when absent or invalid). `langs`: the languages the repository uses — cer_max and
    chars_per_sec must give each of them a value (M1c review P3)."""
    m = BLOCK.search(text or "")
    if not m:
        raise Missing("no studio:criteria JSON block")
    try:
        data = json.loads(m.group(1), parse_constant=_no_constant)
    except ValueError as e:
        raise Missing("the criteria block is not JSON (%s)" % e)
    if not isinstance(data, dict):
        raise Missing("the criteria block is not an object")
    missing = [k for k in KEYS if k not in data]
    if missing:
        raise Missing("the criteria lack %s" % ", ".join(missing))
    ls = data["length_seconds"]
    if not (isinstance(ls, dict) and all(_number(ls.get(k)) for k in ("min", "max"))
            and 0 < ls["min"] <= ls["max"]):
        raise Missing("length_seconds must be {\"min\": s, \"max\": s} with 0 < min <= max")
    for k in ("chars_per_sec", "cer_max"):
        v = data[k]
        if not isinstance(v, dict) or not v or not all(_number(x) and x > 0 for x in v.values()):
            raise Missing("%s must map each language to a positive number" % k)
        missing = [l for l in langs if l not in v]
        if missing:
            raise Missing("%s has no value for %s (a language this repository uses)" % (k, ", ".join(missing)))
    return data


def repo_langs(repo):
    """The languages a repository's videos use (config.json `language`)."""
    try:
        with open(os.path.join(repo, ".claude", "studio", "config.json"), encoding="utf-8") as f:
            lang = json.load(f).get("language")
    except (OSError, ValueError, AttributeError):
        return ()
    return (lang,) if isinstance(lang, str) and lang else ()


def read(repo, kind):
    try:
        with open(path(repo, kind), encoding="utf-8") as f:
            return parse(f.read(), repo_langs(repo))
    except OSError as e:
        raise Missing("cannot read %s (%s)" % (os.path.relpath(path(repo, kind), repo), e.strerror))
