"""guildcore.records.followups — the Issue follow-up record and its PR notice (qa.md Step 2.6).

Issue record `<!-- guild:followups -->` (latest `created_at` canonical, `--paginate`):
    ### <heading in config.language>
    - unfiled — <title> — <근거>
    - declined — <title> — <근거>
    - filed #<n> — <title>
Status token first, ASCII (H§K). review.md reads `unfiled` lines only.

PR notice `<!-- guild:followups:pr:<N> -->` — the Issue number is part of the marker:
    후속 Issue 등록 필요 <k>건 — 사람 확인 전 (/gld review <N> Step 5에서 등록 여부를 묻습니다)
    - <title>
or the settled line `후속 Issue: 처리됨 — #<N>의 후속 기록 참조`.
"""

import re

from guildcore.records import markers
from guildcore.records.redact import redact

NAME = "followups"
ITEM_RE = re.compile(r"^- (unfiled|declined|filed #(\d+)) — (.*)$")
PR_NAME_RE = re.compile(r"<!-- guild:followups:pr:(\d+) -->")
PR_PENDING_T = "후속 Issue 등록 필요 {k}건 — 사람 확인 전 (/gld review {n} Step 5에서 등록 여부를 묻습니다)"
PR_SETTLED_T = "후속 Issue: 처리됨 — #{n}의 후속 기록 참조"


class Item(object):
    def __init__(self, status, filed, title, rationale, line):
        self.status = status          # unfiled | declined | filed
        self.filed = filed            # int when filed
        self.title = title
        self.rationale = rationale
        self.line = line

    def render(self):
        tok = "filed #%d" % self.filed if self.status == "filed" else self.status
        parts = [tok, self.title] + ([self.rationale] if self.rationale else [])
        return "- " + " — ".join(parts)


def parse_item(line):
    m = ITEM_RE.match(markers.clean(line))
    if not m:
        return None
    tok, num, rest = m.group(1), m.group(2), m.group(3)
    status = "filed" if num else tok
    title, _, rationale = rest.partition(" — ")
    return Item(status, int(num) if num else None, title, rationale or None, line)


class FollowupsRecord(object):
    def __init__(self, body, comment_id=None):
        self.body = body
        self.comment_id = comment_id
        self.items = [it for it in (parse_item(l) for l in body.split("\n")) if it]

    def render(self):
        return self.body

    def by_status(self, status):
        return [i for i in self.items if i.status == status]


def from_comments(comments):
    c = markers.find(comments, NAME, pick="latest")
    return FollowupsRecord(markers.body_of(c), c.get("id")) if c else None


def render(heading, items):
    lines = [markers.open_tag(NAME), "### " + heading] + [redact(i.render()) for i in items]
    lines.append(markers.close_tag(NAME))
    return "\n".join(lines)


class PrNotice(object):
    def __init__(self, body, comment_id=None):
        self.body = body
        self.comment_id = comment_id
        m = PR_NAME_RE.search(body)
        self.issue = int(m.group(1)) if m else None
        lines = [markers.clean(l) for l in body.split("\n")]
        self.settled = any(l.startswith("후속 Issue: 처리됨") for l in lines)
        self.titles = [l[2:] for l in lines if l.startswith("- ")]

    def render(self):
        return self.body


def pr_notice_name(issue):
    return "followups:pr:%d" % int(issue)


def pr_notices(pr_comments, issue):
    name = pr_notice_name(issue)
    return [PrNotice(markers.body_of(c), c.get("id")) for c in markers.containing(pr_comments, name)]


def render_pr_notice(issue, unfiled_titles):
    name = pr_notice_name(issue)
    if unfiled_titles:
        lines = [PR_PENDING_T.format(k=len(unfiled_titles), n=issue)] + \
                ["- " + t for t in unfiled_titles]
    else:
        lines = [PR_SETTLED_T.format(n=issue)]
    return "\n".join([markers.open_tag(name), redact("\n".join(lines)), markers.close_tag(name)])
