"""workflows.dev.directive — H§M human directives, read before a HABIT stop (§3.3 SJ-DIRECTIVE, §4.2).

Habit stops = `env: ci-blocked` / `env: base-red` (PR CI) and the visual-environment pause ONLY.
Reads (whole bodies, never sliced): this Issue's unmarked comments + body; each `Sprint: #<t>`
line's tracker when OPEN; a child (`Parent Issue: #<p>`) reads #p's unmarked comments and uses
#p's `Sprint:` lines as tracker candidates. Never higher, never following a named Issue.
No unmarked comment → code writes `사람 지시 확인: 없음 — …` (no judgment); otherwise SJ-DIRECTIVE
(comments whole — no-elide) → `applies` → `사람 지시 적용: …` on the stage output, the stop is
not taken; `out_of_scope`/`unsure` → attended ask `directive-out-of-scope`, unattended pause with
`적용 가능한 사람 지시: …` on the line after the cause line.
"""

import re

from guildcore import state as ST
from guildcore.records import markers
from workflows.dev import judging

SPRINT_RE = re.compile(r"^Sprint: #(\d+)\s*$", re.M)


def _unmarked(comments):
    return [c for c in comments if not markers.is_guild_comment(markers.body_of(c))]


def gather(gh, issue_n, issue=None):
    """{read: [#n…], trackers: [#t], parent: #p|None, comments: [(n, comment)]}."""
    issue = issue or gh.issue(issue_n)
    body = issue.get("body") or ""
    parent = ST.parent_of(body)
    reads = [issue_n]
    got = [(issue_n, c) for c in _unmarked(gh.comments(issue_n))]
    tracker_src = body
    if parent:
        reads.append(parent)
        got += [(parent, c) for c in _unmarked(gh.comments(parent))]
        tracker_src = gh.issue(parent).get("body") or ""
    trackers = []
    for t in [int(x) for x in SPRINT_RE.findall(tracker_src)]:
        if (gh.issue(t).get("state") or "").upper() == "OPEN":
            trackers.append(t)
            got += [(t, c) for c in _unmarked(gh.comments(t))]
    return {"issue": issue_n, "parent": parent, "trackers": trackers, "comments": got}


def none_line(g):
    parts = ["#%d" % g["issue"]] + ["트래커 #%d" % t for t in g["trackers"]]
    if g["parent"]:
        parts.append("부모 #%d" % g["parent"])
    return "사람 지시 확인: 없음 — 읽음: %s (마커 없는 댓글 %d개, 전문)" % (" · ".join(parts), len(g["comments"]))


def judge(p, stage, g, stop_reason, step):
    """Returns (kind, pause_line, decision|None): kind 'none' → the `사람 지시 확인: 없음 — …`
    line; 'applies' / 'out_of_scope' → `적용 가능한 사람 지시: #m "<line>" — …` (a directive the
    engine cannot act on by itself is shown to the human on the pause — conservative)."""
    if not g["comments"]:
        return "none", none_line(g), None
    text = "\n\n".join("#%d comment %s (%s):\n%s" % (n, c.get("id"), c.get("html_url") or "",
                                                     markers.body_of(c)) for n, c in g["comments"])
    sp = judging.spec(p, "DIRECTIVE", [("stop", "Stop about to be taken: %s" % stop_reason),
                                        ("comments", text)], stage, step)
    d = p.judge(sp)
    v = d.choice
    if v == "none":
        return "none", none_line(g), d
    hit = (d.fields.get("out_of_scope") or d.fields.get("applies") or [{}])[0]
    line = '적용 가능한 사람 지시: %s "%s" — 이 Issue(또는 트래커)에 남기면 다음 재개에 적용됩니다' % (
        hit.get("comment") or "#%d" % g["issue"], " ".join((hit.get("line") or "").split()))
    return ("applies" if v == "applies" else "out_of_scope"), line, d


def applied_line(d):
    """`사람 지시 적용: #m (<url>) — <한 줄>` for a stage output / PR body."""
    a = (d.fields.get("applies") or [{}])[0]
    return "%s — %s" % (a.get("comment") or "?", " ".join((a.get("line") or "").split()))
