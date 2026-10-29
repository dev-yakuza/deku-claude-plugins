"""A platform's rules (m1-plan §10): `.claude/studio/platforms/<platform>.md` (P-CRIT — the agent drafts it, a person
checks it against the platform's own help and fills `checked` in its frontmatter; U-M1h). The rules are the JSON block
between `<!-- studio:rules -->` and `<!-- /studio:rules -->`:

    {"title_max": 100, "description_max": 5000, "hashtags_max": 15, "required": ["<notice line>", …]}

A missing or invalid block, or an empty `checked`, fails the copy check (the closed side)."""

import json
import os
import re

BLOCK = re.compile(r"<!-- studio:rules -->\s*```json\s*\n(.*?)\n```\s*<!-- /studio:rules -->", re.S)
CHECKED = re.compile(r"^checked:\s*[\"']?([^\"'\n]*)[\"']?\s*$", re.M)
INTS = ("title_max", "description_max", "hashtags_max")


class RulesProblem(Exception):
    pass


def path(repo, platform):
    """The platform's rules file — only for a safe name, and only inside .claude/studio/platforms/ (M1h review Y1)."""
    from ..state.schema import platform_ok
    if not platform_ok(platform):
        raise RulesProblem("%r is not a platform name" % (platform,))
    base = os.path.realpath(os.path.join(repo, ".claude", "studio", "platforms"))
    p = os.path.join(base, "%s.md" % platform)
    if not os.path.realpath(p).startswith(base + os.sep):
        raise RulesProblem("the rules of %s are not inside .claude/studio/platforms/" % platform)
    return p


def parse(text):
    """(rules, checked date or "")."""
    head = ""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        head = text[3:end] if end > 0 else ""
    m = CHECKED.search(head)
    checked = m.group(1).strip() if m else ""
    b = BLOCK.search(text)
    if not b:
        raise RulesProblem("no studio:rules JSON block")
    try:
        data = json.loads(b.group(1))
    except ValueError as e:
        raise RulesProblem("the rules block is not JSON (%s)" % e)
    if not isinstance(data, dict):
        raise RulesProblem("the rules block is not an object")
    for k in INTS:
        v = data.get(k)
        if not isinstance(v, int) or isinstance(v, bool) or v <= 0:
            raise RulesProblem("%s must be a positive whole number" % k)
    req = data.get("required")
    if not isinstance(req, list) or not all(isinstance(x, str) and x.strip() for x in req):
        raise RulesProblem("required must be a list of notice lines")
    return data, checked


def read(repo, platform):
    p = path(repo, platform)
    try:
        with open(p, encoding="utf-8") as f:
            return parse(f.read())
    except OSError as e:
        raise RulesProblem("cannot read .claude/studio/platforms/%s.md (%s)" % (platform, e.strerror))
