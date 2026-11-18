"""guildcore.records.answer — the human's `guild-answer: D<k> <token>` line (§2.5, C13).

Grammar only: a whole line `guild-answer: D<k> <token>` (nothing after the token but blanks),
outside fenced code and `>` quotes, in a comment with no `<!-- guild:` ANYWHERE — the stricter of
§2.5 ("does not start with") and Section M ("contains"), so a quote-reply of a Guild comment is
never an answer (K0-m4). Whether an answer is ACCEPTED (association, time, token, timeline) is
`guildcore.decisions.accepted_answer`.
"""

import re

from guildcore.records import markers

# K5r4-m4: the issue-qualified id the attended driver shows (`#8/D2`) is accepted too — only for that same Issue
# (`decisions.accepted_answer` rejects one that names another Issue)
ANSWER_RE = re.compile(r"^guild-answer: (?:#?(\d+)/)?D(\d+) ([a-z0-9:_-]+)[ \t]*$")
ISSUE_URL_RE = re.compile(r"/issues/(\d+)$")


class Answer(object):
    def __init__(self, k, token, comment, issue=None):
        self.k = k
        self.issue = issue            # the Issue a qualified id names (`#8/D2` → 8), else None
        self.token = token
        self.comment = comment
        self.comment_id = comment.get("id")
        self.created_at = comment.get("created_at") or ""
        self.author = ((comment.get("user") or {}).get("login")) or ""
        self.association = comment.get("author_association") or ""


def parse(comment):
    body = markers.body_of(comment)
    if "<!-- guild:" in body:
        return []
    out, fence = [], None
    for ln in body.replace("\r", "").split("\n"):
        f = re.match(r"^\s*(```+|~~~+)", ln)
        if f:
            mark = f.group(1)[0] * 3
            fence = None if fence and mark == fence else (fence or mark)
            continue
        if fence or ln.lstrip().startswith(">"):
            continue
        m = ANSWER_RE.match(ln)
        if m:
            out.append(Answer(int(m.group(2)), m.group(3), comment, int(m.group(1)) if m.group(1) else None))
    return out


def comment_issue(comment):
    """The Issue number a REST comment belongs to (`issue_url`), or None."""
    m = ISSUE_URL_RE.search(str(comment.get("issue_url") or ""))
    return int(m.group(1)) if m else None


def from_comments(comments):
    out = []
    for c in sorted(comments, key=lambda c: c.get("id") or 0):
        out.extend(parse(c))
    return out
