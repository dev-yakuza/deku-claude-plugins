"""The claims of `work/source.md` (the source analyst's list, m1-plan §6.3 · §7.2):

    - C-<first 8 hex of the excerpt's sha256>: <the claim in one sentence>
      > <the excerpt, exactly as in the copy>          (more `>` lines continue it; joined with a line break)

A claim's id is the hash of its excerpt (00-plan §3.2), so an id that does not match its excerpt is a problem."""

import hashlib
import os
import re

CLAIM = re.compile(r"^\s*[-*]\s+(C-[0-9a-f]{8})\s*:\s*(.*?)\s*$")
QUOTE = re.compile(r"^\s*>\s?(.*?)\s*$")


def claim_id(excerpt):
    return "C-" + hashlib.sha256(excerpt.encode("utf-8")).hexdigest()[:8]


def parse(text):
    """({id: {"claim", "excerpt", "line"}}, [problems])."""
    lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out, problems = {}, []
    i = 0
    while i < len(lines):
        m = CLAIM.match(lines[i])
        if not m:
            i += 1
            continue
        cid, claim, line = m.group(1), m.group(2), i + 1
        quote = []
        i += 1
        while i < len(lines) and QUOTE.match(lines[i]) and not CLAIM.match(lines[i]):
            quote.append(QUOTE.match(lines[i]).group(1))
            i += 1
        excerpt = "\n".join(quote)
        if not excerpt.strip():
            problems.append("line %d: %s has no excerpt (`  > …` on the next line)" % (line, cid))
            continue
        if claim_id(excerpt) != cid:
            problems.append("line %d: %s is not the id of its excerpt (that would be %s)" % (line, cid,
                                                                                            claim_id(excerpt)))
            continue
        if cid in out:
            problems.append("line %d: %s is listed twice" % (line, cid))
            continue
        out[cid] = {"claim": claim, "excerpt": excerpt, "line": line}
    return out, problems


def path(vdir):
    return os.path.join(vdir, "work", "source.md")


def read(vdir):
    """({id: claim}, [problems]) — a missing source.md is a problem."""
    try:
        with open(path(vdir), encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return {}, ["work/source.md is missing: the source analyst writes it (source stage)"]
    claims, problems = parse(text)
    if not claims and not problems:
        problems.append("work/source.md lists no claims (`- C-<id>: <claim>` with `  > <excerpt>`)")
    return claims, problems
