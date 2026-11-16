"""workflows.status.route — `/gld resume N` routing as code (resume.md, C §1.5, §2.10).

Order is resume.md's, with `sprint` checked BEFORE `"none"` (a tracker has no stage label, so
the none rows would route it to /gld dev). Extra facts §2.10 adds: the active loop-back count
the way status reports it, the interrupted-loop-back reading (H§B), and live pending-human
questions with whether a valid `guild-answer:` already resolves them (§2.5 rule 2(a)).

Routing never writes: no label is removed (resume never strips `guild:needs-human`).
"""

from guildcore import config as cfgmod
from guildcore import decisions as dec
from guildcore.state import IssueSnapshot
from workflows.status import render as R
from workflows.status.show import loopback_line

SPINE = ("analyze", "design", "execute", "test", "qa")


class Route(object):
    def __init__(self, number, action, reason, message, stage=None):
        self.number = number
        self.action = action        # dev | stop | fail | suggest
        self.reason = reason        # not_issue | uninitialized | done | children | spine | sprint | harness | none
        self.message = message
        self.stage = stage
        self.paused = False
        self.loopbacks = None
        self.interrupted_loopback = False
        self.pending = []

    def as_dict(self):
        return {"issue": self.number, "action": self.action, "reason": self.reason,
                "stage": self.stage, "paused": self.paused, "loopbacks": self.loopbacks,
                "interrupted_loopback": self.interrupted_loopback, "pending_human": self.pending,
                "message": self.message}

    def text(self):
        lines = [self.message]
        if self.paused and self.action == "dev":
            lines.append("guild:needs-human stays on — the stage's next forward transition removes it")
        if self.loopbacks:
            lines.append(self.loopbacks["line"])
        if self.interrupted_loopback:
            lines.append("Interrupted loop-back: the record is written but the label is still "
                         "guild:%s — that stage's Step 0 finishes the move" % self.stage)
        for p in self.pending:
            ln = "Pending human decision %s (%s): %s" % (p["id"], p.get("kind") or "?",
                                                         p.get("question") or "")
            if p.get("options"):
                ln += " [options: %s]" % " | ".join(p["options"])
            lines.append(ln)
            if p.get("conflict"):
                lines.append("  conflicting answers: " + ", ".join(
                    "#%s %s (%s)" % (c["comment_id"], c["token"], c["author"]) for c in p["conflicting"])
                    + " — left for a human to settle")
            if p.get("answer"):
                lines.append("  answered: guild-answer: %s %s (comment %s)" % (
                    p["id"], p["answer"]["token"], p["answer"]["comment_id"]))
        return "\n".join(lines) + "\n"


def interrupted(snap):
    """H§B: latest active block unhandled, no audit `invocation:` ≥ its `at:`, label test/qa.
    Invocations are read from EVERY auditor:execute comment (K0-m6): a stray duplicate record
    must not make an execute run invisible — a false "interrupted" moves the label without
    re-running anything."""
    from guildcore.records import audit
    rec = snap.loopback
    if rec is None or snap.state.stage not in ("test", "qa") or not rec.not_yet_handled():
        return False
    at = rec.latest_active().get("at") or ""
    invs = [i for r in audit.all_from_comments(snap.comments) for i in r.invocations()]
    return not any(i >= at for i in invs)


def route(gh, number, root=".", unattended=False, own_writes=()):
    issue = gh.issue(number)
    if "/pull/" in (issue.get("url") or ""):
        return Route(number, "fail", "not_issue", R.ROUTE["not_issue"].format(n=number))
    if not cfgmod.exists(root):
        return Route(number, "stop", "uninitialized", R.ROUTE["uninitialized"])
    cfg = cfgmod.load(root)
    snap = IssueSnapshot(number, issue, gh.comments(number), gh.pr_search(number))
    return route_snapshot(gh, snap, cfg, unattended, own_writes)


def route_snapshot(gh, snap, cfg=None, unattended=False, own_writes=()):
    st, n = snap.state, snap.number
    if st.stage == "done" and snap.issue_state.upper() == "OPEN" and snap.markers.get("closed-as-decided"):
        # §2.2: the engine (K4) finishes T3 ④ here; until then resume.md's stop (K0-m13)
        r = Route(n, "stop", "done_open_decided", R.ROUTE["done_open_decided"].format(n=n), "done")
    elif st.stage == "done":
        r = Route(n, "stop", "done", R.ROUTE["done"].format(n=n), "done")
    elif st.stage == "children":
        r = Route(n, "dev", "children", R.ROUTE["children"].format(n=n), "children")
    elif st.stage in SPINE:
        r = Route(n, "dev", "spine", R.ROUTE["spine"].format(n=n, stage=st.stage), st.stage)
    elif st.sprint:
        return Route(n, "fail", "sprint", R.ROUTE["sprint"].format(n=n), "none")
    elif st.stage != "none":
        return Route(n, "stop", "unknown", R.ROUTE["unknown"].format(n=n, label=st.label), st.stage)
    elif st.harness:
        r = Route(n, "dev", "harness", R.ROUTE["harness"].format(n=n), "none")
    else:
        return Route(n, "suggest", "none", R.ROUTE["none"].format(n=n), "none")
    r.paused = st.paused
    if snap.loopback is not None:
        s = snap.loopback.summary()
        s["line"] = loopback_line(snap.loopback)
        r.loopbacks = s
    r.interrupted_loopback = interrupted(snap)
    pend = snap.decisions.pending_human() if snap.decisions else []
    if pend:
        timeline = gh.timeline(n)
        assoc = tuple((cfg.engine if cfg else {}).get("answer_associations")
                      or dec.DEFAULT_ASSOCIATIONS)
        for b in pend:
            alive, _why = dec.live(b, st, timeline, own_writes)
            if not alive:
                continue
            st_a, ans, rej = dec.accepted_answer(b, snap.comments, timeline, unattended, assoc)
            conflicts = [{"comment_id": a.comment_id, "token": a.token, "author": a.author}
                         for a, why in rej if why == "conflicting answers"]
            r.pending.append({"id": b.id, "kind": b.get("kind"), "point": b.get("point"),
                              "question": b.get("question"), "options": b.options(),
                              "answer_status": st_a, "conflict": st_a == "conflict",
                              "conflicting": conflicts,
                              "answer": ({"token": ans.token, "comment_id": ans.comment_id}
                                         if ans else None)})
    return r
