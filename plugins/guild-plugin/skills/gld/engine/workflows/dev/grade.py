"""workflows.dev.grade — `dev grade` (design §9.5 human side, §10.4 first-sprint sheet).

    dev grade --sprint T | --issues N,M [--out DIR]     the human grading sheet (CSV + markdown)
    dev grade --import CSV                               the person's filled sheet → grades.jsonl + count rules

Selection (deterministic — `(repo, issue, D-id)` hash, never random):
* only L0/SJ decisions the engine made (`by: judge:*` / `leader:*`); a decision a person already decided (an
  ask answer, a pause resolution — `by: human`) is never on the sheet again;
* high-risk groups (KICKOFF · STAKES · EX-ARB dismiss/dispute · ESCALATE · SPLIT · INTEGRATE): first sprint
  100 %, after that `grading.highrisk_human_rate` (default 0.3, a valve may only lower it, floor 0.2);
* triggered items always: `unsure`, coerced (not by first-sprint / valve), a later loop-back or needs-human on
  the same Issue;
* the selective groups get a fixed calibration sample (2 per active group in the first sprint, 1 after).
The sheet never carries a grader's output (R4J-m4). Columns: decision_id, issue, stage, group, mode,
choice, reason, coerced, coerced_by, unsure, evidence, given_info (ok|wrong|unsure — the person's), outcome,
note.

Count rules on import (§9.5, shared with `dev health`): per group, a person's confirmed `given_info=wrong`
1 → `watch` (state file); a second while watched, or one in an irreversible class (SPLIT; STAKES on an
irreversible path) → `group.<G>.conservative` in the valves' `auto` area (a person-released valve is never
re-applied — `guildcore.valves`). `watch` clears after 10 consecutive confirmed non-wrong judgments.
The 2-call opus grader (blind + reveal) is not wired yet — K5 carry-over; the human sheet stands on its own.
"""

import csv
import hashlib
import io
import json
import os

from guildcore import journal as J
from guildcore import valves as VALVES

HIGH_RISK = ("KICKOFF", "STAKES", "EX-ARB:dismiss", "ESCALATE", "SPLIT", "INTEGRATE")
SELECTIVE = ("TEST", "QA", "EX-ARB:accept", "DE-ARB", "AN-PO", "VIS-ENV", "DIRECTIVE", "HANDOFF", "EX-DWC")
IRREVERSIBLE = ("SPLIT",)
COLUMNS = ("decision_id", "issue", "stage", "group", "mode", "choice", "reason", "coerced", "coerced_by",
           "unsure", "evidence", "given_info", "outcome", "note")
WATCH_CLEAR_AFTER = 10


def group_of(b):
    """The §9.5 group of a decision block (EX-ARB split by what it chose)."""
    pt = (b.get("point") or "").split(":")[0]
    if pt == "EX-ARB":
        ch = (b.get("raw_choice") or b.get("choice") or "")
        return "EX-ARB:dismiss" if ("dismiss" in ch or "dispute" in ch or "would-dismiss" in ch) else "EX-ARB:accept"
    if pt.startswith("L0-"):
        pt = pt[3:]
    return pt


def _h(repo, issue, did):
    return int(hashlib.sha256(("%s|%s|%s" % (repo, issue, did)).encode()).hexdigest()[:8], 16) / float(0xFFFFFFFF)


def _engine_made(b):
    by = b.get("by") or ""
    return by.startswith("judge:") or by.startswith("leader:")


def triggered(b, later_events):
    """unsure, coerced (not by first-sprint / valve), or a later loop-back / needs-human on the Issue."""
    if str(b.get("unsure")).lower() == "true":
        return "unsure"
    if str(b.get("coerced")).lower() == "true" and b.get("coerced_by") not in ("first-sprint", "valve"):
        return "coerced"
    if later_events:
        return later_events
    return None


def select(blocks_by_issue, repo, first_sprint, rate, later):
    """[(issue, block, why)] for the sheet. `later(issue, block) -> str|None` names a later loop-back /
    needs-human. `blocks_by_issue` = {issue: [blocks]} (trusted records, superseded ones dropped)."""
    out, calib = [], {}
    for issue in sorted(blocks_by_issue):
        human_resolved = set(b.get("resolves") for b in blocks_by_issue[issue] if b.get("by") == "human")
        for b in blocks_by_issue[issue]:
            if not _engine_made(b) or b.id in human_resolved:
                continue
            g = group_of(b)
            why = triggered(b, later(issue, b))
            if why:
                out.append((issue, b, "triggered: %s" % why))
            elif g in HIGH_RISK:
                if first_sprint or _h(repo, issue, b.id) < rate:
                    out.append((issue, b, "high-risk sample"))
            elif g in SELECTIVE:
                calib.setdefault(g, []).append((issue, b))
    per = 2 if first_sprint else 1
    for g, items in sorted(calib.items()):
        items.sort(key=lambda ib: _h(repo, ib[0], ib[1].id))
        out += [(i, b, "calibration") for i, b in items[:per]]
    return out


def sheet_rows(selected, mode, evidence):
    rows = []
    for issue, b, why in selected:
        rows.append({"decision_id": b.id, "issue": issue, "stage": b.get("stage") or "", "group": group_of(b),
                     "mode": mode, "choice": b.get("raw_choice") or b.get("choice") or "",
                     "reason": " ".join((b.get("reason") or "").split())[:300],
                     "coerced": b.get("coerced") or "false", "coerced_by": b.get("coerced_by") or "",
                     "unsure": b.get("unsure") or "false", "evidence": "%s; %s" % (why, evidence(issue)),
                     "given_info": "", "outcome": "", "note": ""})
    return rows


def render_csv(rows):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLUMNS)
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return buf.getvalue()


def render_md(rows):
    out = ["| " + " | ".join(COLUMNS) + " |", "|" + "---|" * len(COLUMNS)]
    for r in rows:
        out.append("| " + " | ".join(str(r[c]).replace("|", "\\|") for c in COLUMNS) + " |")
    return "\n".join(out) + "\n"


# ---- import + count rules ------------------------------------------------------------------------------------

def grades_path(common):
    return os.path.join(J.engine_dir(common), "grades.jsonl")


def state_path(common):
    return os.path.join(J.engine_dir(common), "grade-state.json")


def load_state(common):
    try:
        with open(state_path(common), encoding="utf-8") as fh:
            return json.load(fh)
    except (IOError, ValueError):
        return {"watch": {}, "streak": {}}


def grades(common):
    out = []
    try:
        with open(grades_path(common), encoding="utf-8") as fh:
            for ln in fh:
                try:
                    out.append(json.loads(ln))
                except ValueError:
                    pass
    except IOError:
        pass
    return out


def import_sheet(common, text, repo, irreversible=lambda row: False):
    """Rows with given_info filled → grades.jsonl (key (repo, issue, D-id, "human"); a key already present is
    skipped); then the count rules. Returns {"imported": n, "watch": [...], "conservative": [...]}."""
    have = set((g.get("repo"), str(g.get("issue")), g.get("decision_id"), g.get("grader_version"))
               for g in grades(common))
    st = load_state(common)
    st.setdefault("watch", {})
    st.setdefault("streak", {})
    n, cons, watch = 0, [], []
    for row in csv.DictReader(io.StringIO(text)):
        gi = (row.get("given_info") or "").strip().lower()
        if gi not in ("ok", "wrong", "unsure"):
            continue
        key = (repo, str(row.get("issue")), row.get("decision_id"), "human")
        if key in have:
            continue
        have.add(key)
        rec = dict((c, row.get(c)) for c in COLUMNS)
        rec.update(repo=repo, grader_version="human", given_info=gi)
        J.fsync_append(grades_path(common), json.dumps(rec, ensure_ascii=False, sort_keys=True))
        n += 1
        g = row.get("group") or "?"
        if gi == "wrong":
            st["streak"][g] = 0
            if g in st["watch"] or g in IRREVERSIBLE or irreversible(row):
                VALVES.auto_set(common, "group.%s.conservative" % g.replace(":", "-"), True,
                                "count rule: confirmed wrong %s (%s)" % (row.get("decision_id"), "irreversible"
                                                                         if g in IRREVERSIBLE else "while watched"))
                cons.append(g)
            st["watch"][g] = st["watch"].get(g) or row.get("decision_id")
            watch.append(g)
        elif gi == "ok":
            st["streak"][g] = st["streak"].get(g, 0) + 1
            if g in st["watch"] and st["streak"][g] >= WATCH_CLEAR_AFTER:
                del st["watch"][g]
    J.atomic_write(state_path(common), json.dumps(st, sort_keys=True, indent=1))
    return {"imported": n, "watch": sorted(set(watch)), "conservative": sorted(set(cons))}


# ---- the CLI -------------------------------------------------------------------------------------------------

def _issues(d, a, gh):
    if getattr(a, "issues", None):
        return [int(x) for x in str(a.issues).split(",") if x.strip()]
    if a.sprint:
        import re
        body = gh.issue(int(a.sprint)).get("body") or ""
        return sorted(set(int(x) for x in re.findall(r"#(\d+)", body)) - {int(a.sprint)})
    return []


def main(d, a):
    from guildcore import emit
    common = d.common()
    if a.import_csv:
        with open(a.import_csv, encoding="utf-8") as fh:
            text = fh.read()
        gh = d.gh()
        res = import_sheet(common, text, gh.owner_repo())
        emit.engine(res, out=d.out)
        return 0
    from guildcore.decisions import DecisionLog
    from guildcore.records import markers
    gh = d.gh()
    repo = gh.owner_repo()
    issues = _issues(d, a, gh)
    if not issues:
        emit.engine({"error": "dev grade needs --sprint T (its tracker lists the members) or --issues N,M"}, out=d.out)
        return 64
    by_issue, later_ev = {}, {}
    for n in issues:
        log = DecisionLog.load(markers.trusted(gh.comments(n), ()))
        gone = log.resolved_ids()
        by_issue[n] = [b for b in log.blocks if b.id not in gone or b.get("by") == "human"]
        labels = [lb.get("name") if isinstance(lb, dict) else lb for lb in gh.issue(n).get("labels") or []]
        later_ev[n] = ("needs-human" if "guild:needs-human" in labels else None)
    valves = VALVES.effective(common, d.env)
    cfg = d.config(d.toplevel())
    mode = (((getattr(cfg, "raw", None) or {}).get("engine") or {}).get("first_sprint_mode") or "auto") if cfg else "auto"
    first = mode == "on" or (mode == "auto" and not _go_recorded(gh, a.sprint))
    rate = valves.get("grading.highrisk_human_rate", VALVES.GRADING_DEFAULT["grading.highrisk_human_rate"])
    sel = select(by_issue, repo, first, rate, lambda i, b: later_ev.get(i))
    rows = sheet_rows(sel, "first-sprint" if first else "steady", lambda i: "https://github.com/%s/issues/%d" % (repo, i))
    out_dir = a.out or os.path.join(J.engine_dir(common), "grading")
    os.makedirs(out_dir, exist_ok=True)  # fs-ok: the engine's grading sheet dir under <git-common-dir>/guild/engine or the person's --out
    tag = ("sprint-%s" % a.sprint) if a.sprint else "issues"
    J.atomic_write(os.path.join(out_dir, "%s.csv" % tag), render_csv(rows))
    J.atomic_write(os.path.join(out_dir, "%s.md" % tag), render_md(rows))
    emit.engine({"rows": len(rows), "csv": os.path.join(out_dir, "%s.csv" % tag), "first_sprint": first}, out=d.out)
    return 0


def _go_recorded(gh, tracker):
    """§10.4: first-sprint mode ends only on a `first-sprint go/no-go` note with `result: go` on GitHub."""
    if not tracker:
        return False
    from guildcore.records import markers
    for c in markers.trusted(gh.comments(int(tracker)), ()):
        b = markers.body_of(c)
        if b.startswith("<!-- guild:note -->") and "first-sprint go/no-go" in b and "result: go" in b:
            return True
    return False
