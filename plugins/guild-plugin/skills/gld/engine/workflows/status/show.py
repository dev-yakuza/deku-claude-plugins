"""workflows.status.show — `/gld status N` as code (status.md, §2.10).

Read-only: gathers one `snapshot()` (≤ 3 gh reads; +1 timeline read only when a pending-human
decision exists, +1 child discovery for a split parent) and renders the complete text.
"""

from guildcore import decisions as dec
from guildcore.records.loopback import CAP
from guildcore.state import STAGE_ORDER, discover_children, snapshot
from workflows.status import render as R


def _pr_open(snap):
    return any((p.get("state") or "").upper() == "OPEN" for p in snap.pr.strict)


def _human_merged_child(snap):
    """C-F-18's 1b-cleanup child, read without judgment: a child that is CLOSED and has a
    strictly matched MERGED PR."""
    return snap.state.child and snap.issue_state.upper() == "CLOSED" and \
        any((p.get("state") or "").upper() == "MERGED" for p in snap.pr.strict)


def row_status(snap, key, stage):
    """status.md checklist rules → (completed, text)."""
    st, m = snap.state, snap.markers
    nxt = STAGE_ORDER[STAGE_ORDER.index(stage) + 1]
    present = m.get(key, False)
    if stage == "execute":
        completed = present and (st.at_least("test") or _pr_open(snap))
    elif stage == "qa":
        completed = present and st.stage == "done"
    else:
        completed = present and st.at_least(nxt)
    if completed:
        return True, "completed"
    if st.stage == stage:
        return False, "in progress" + (" (paused)" if st.paused else "")
    if st.stage == "done":                                  # C-F-18
        if m.get("closed-as-decided"):
            return False, R.DONE_DECIDED
        if _human_merged_child(snap):
            return False, R.DONE_HUMAN_MERGE
        return False, R.DONE_LABEL_ONLY
    return False, R.NOT_STARTED


def loopback_line(rec):
    if rec is None:
        return None
    s = rec.summary()
    line = "Loop-backs: %d/%d" % (s["active"], CAP)
    if s["latest_from"] is not None:
        line += " — latest from %s: %s" % (s["latest_from"], s["latest_reason"] or "")
        if s["not_yet_handled"]:
            line += " (not yet handled)"
    return line


def pr_lines(snap):
    if snap.pr.strict:
        return ["PR: %s (%s)" % (p.get("url"), (p.get("state") or "").lower())
                for p in sorted(snap.pr.strict, key=lambda p: p.get("number") or 0)]
    out = ["PR: none"]
    if snap.pr.candidates:
        out.append("PR candidates (no closing reference — unconfirmed): " + ", ".join(
            "#%s %s (%s)" % (p.get("number"), p.get("title") or "", (p.get("state") or "").lower())
            for p in sorted(snap.pr.candidates, key=lambda p: p.get("number") or 0)))
    return out


def decision_summary(gh, snap, own_writes=()):
    """(pending_alive, superseded) via the shared `decisions.live` predicate (R5C-m3)."""
    pend = snap.decisions.pending_human()
    if not pend:
        return [], []
    timeline = gh.timeline(snap.number)
    alive, dead = [], []
    for b in pend:
        ok, _why = dec.live(b, snap.state, timeline, own_writes)
        (alive if ok else dead).append(b)
    return alive, dead


def decisions_lines(gh, snap):
    out = []
    if snap.decisions:
        alive, dead = decision_summary(gh, snap)
        line = "Decisions: %d (pending-human %d" % (len(snap.decisions.blocks), len(alive))
        if dead:
            line += ", %s %d" % (R.SUPERSEDED, len(dead))
        out.append(line + ")")
    es = snap.decisions.engine_start() if snap.decisions else None
    if es is None and snap.state.stage == "none" and not snap.decisions:
        return out                      # Guild never ran the spine here — no mode to report
    if es is not None:
        out.append("Mode: engine (since %s, plugin %s)" % (es.get("started_at_stage") or "?",
                                                         es.get("plugin") or "?"))
    else:
        out.append("Mode: legacy-started")
    return out


def stage_text(st):
    if st.stage == "none":
        if st.sprint:
            return R.SPRINT
        return R.HARNESS_NONE if st.harness else R.NOT_STARTED
    return R.STAGE_RENDER[st.stage]


def render_children(gh, snap):
    kids = discover_children(gh, snap.number)
    done = sum(1 for k in kids if k["derived"].stage == "done")
    lines = ["Children: %d/%d done" % (done, len(kids))]
    for k in kids:
        d = k["derived"]
        lines.append("%s#%d %s — %s%s" % (R.checkbox(d.stage == "done"), k["number"], k["title"],
                                         stage_text(d), " (paused)" if d.paused else ""))
    lines.append("Integration: %s" % ("done" if snap.markers.get("integration:output") else "pending"))
    return lines


def show(gh, number):
    issue = gh.issue(number)
    if "/pull/" in (issue.get("url") or ""):
        return R.ROUTE["not_issue"].format(n=number) + "\n"
    snap = snapshot_from(gh, number, issue)
    return render_snapshot(gh, snap)


def snapshot_from(gh, number, issue):
    from guildcore.state import IssueSnapshot
    return IssueSnapshot(number, issue, gh.comments(number), gh.pr_search(number))


def render_snapshot(gh, snap):
    st = snap.state
    ann = ""
    if st.children:
        ann += "  (split parent)"
    if st.child:
        ann += "  (child)"
    if st.harness and st.stage != "none":
        ann += "  (harness)"
    lines = ["Issue #%d: %s%s" % (snap.number, snap.title, ann)]
    if st.paused:
        lines.append(R.PAUSED_LINE)
    if st.child and snap.parent:
        lines.append("Parent: #%d" % snap.parent)
    stage = stage_text(st)
    if st.paused and st.stage != "none":
        stage += " (paused here)"
    lines.append("Stage: " + stage)
    if st.sprint and st.stage == "none":
        lines.append("Next: /gld sprint daily (never /gld dev — that develops the container)")
        return "\n".join(lines) + "\n"
    if st.harness and st.stage == "none":
        lines.append("Next: /gld dev %d to start it" % snap.number)
    if st.children:
        lines.extend(render_children(gh, snap))
    else:
        for label, key, stage_name in R.ROWS:
            done, text = row_status(snap, key, stage_name)
            lines.append("%s%s: %s" % (R.checkbox(done), label, text))
        lb = loopback_line(snap.loopback)
        if lb:
            lines.append(lb)
        lines.extend(pr_lines(snap))
    lines.extend(decisions_lines(gh, snap))
    return "\n".join(lines) + "\n"


__all__ = ["show", "render_snapshot", "row_status", "snapshot"]
