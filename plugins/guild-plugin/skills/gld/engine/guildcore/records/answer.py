"""guildcore.records.answer — the human's `guild-answer: D<k> <token>` line (§2.5, C13).

Grammar only: `^guild-answer: D(\\d+) ([a-z0-9:_-]+)` on any line of a comment that carries no
Guild marker at its start. Whether an answer is ACCEPTED (association, time, token, timeline) is
`guildcore.decisions.accepted_answer`.
"""

import re

from guildcore.records import markers

ANSWER_RE = re.compile(r"^guild-answer: D(\d+) ([a-z0-9:_-]+)", re.M)


class Answer(object):
    def __init__(self, k, token, comment):
        self.k = k
        self.token = token
        self.comment = comment
        self.comment_id = comment.get("id")
        self.created_at = comment.get("created_at") or ""
        self.author = ((comment.get("user") or {}).get("login")) or ""
        self.association = comment.get("author_association") or ""


def parse(comment):
    body = markers.body_of(comment)
    if body.startswith("<!-- guild:"):
        return []
    return [Answer(int(m.group(1)), m.group(2), comment) for m in ANSWER_RE.finditer(body.replace("\r", ""))]


def from_comments(comments):
    out = []
    for c in sorted(comments, key=lambda c: c.get("id") or 0):
        out.extend(parse(c))
    return out
