"""workflows.dev.grade — `dev grade` (design §9.5, §10.4 first-sprint sheet).

    dev grade --sprint T | --issues N,M [--out DIR] [--grader [--pass 2]]
    dev grade --import CSV                     the person's filled sheet → grades.jsonl + count rules (+ the grader's
                                               output for those rows, revealed only now — R4J-m4)

Human judgments (§9.5 "사람 판정 = 블라인드 채점표 답 + predict-first 답"):
* the blind sheet rows a person fills (`--import`);
* K5r4 (b): predict-first ANSWERS — a resolved question whose pending block carried `predict_first` (never
  `predict_first_refused`), whose resolution revealed `recommended` (never `reveal: unavailable`) and whose answer
  is an option other than `stop`: the answer equal to the hidden recommendation → `ok`, another option → `wrong`
  (the person, blind, chose differently). Collected by every `dev grade` run into grades.jsonl
  (grader_version `predict-first`, key-deduplicated) and fed to the same count rules. An answer that saw the
  recommendation stays a decision (`by: human`) only.

Selection (deterministic — `(repo, issue, D-id)` hash, never random):
* only L0/SJ decisions the engine made (`by: judge:*` / `leader:*`); a decision a person already decided (an
  ask answer, a pause resolution — `by: human`) is never on the sheet again — K5r4-m5: nor is a KICKOFF whose
  readiness / interpretation / close question a person answered;
* high-risk groups (KICKOFF · STAKES · EX-ARB dismiss/dispute · ESCALATE · SPLIT · INTEGRATE): first sprint
  100 %, after that `grading.highrisk_human_rate` (default 0.3, a valve may only lower it, floor 0.2);
* triggered items always — K5r4-m5: from the Issue's HISTORY, not its current label: `unsure`, coerced (not by
  first-sprint / valve), a later loop-back (the loop-back record), a later needs-human (a later pending question
  in the log, or a `guild:needs-human` label event in the timeline), a later QA fail, a review that requested
  changes on the Issue's PR;
* with the grader (`--grader`): its flagged decisions (wrong · unsure · blind choice ≠ the engine's) go to the person;
  the selective groups' calibration sample (2 per active group in the first sprint, 1 after) is drawn from the
  grader's `ok`s; without grader output, from all of the group's decisions.
The sheet never carries a grader's output (R4J-m4). Columns: decision_id, issue, stage, group, mode,
choice, reason, coerced, coerced_by, unsure, evidence, given_info (ok|wrong|unsure — the person's), outcome,
note. `evidence` = why selected + the post-hoc evidence summary (PR state, reviews, CI, loop-backs, needs-human).

The grader (`workflows.dev.grader`, opus by default — `config.engine.grading.grader_model`; a local endpoint only
through `config.engine.allowed_endpoints`): KICKOFF never (its after-evidence is only intent); the other high-risk
groups and the selective ones 100 % in the first sprint, after that `grading.grader_rate` (0.25, floor 0.15) —
triggered always; a first-sprint HANDOFF shadow only when it reported a gap. Pass 1 at sprint end; `--pass 2` after
review/merge re-grades only pass-1 `unsure`s. Key (repo, issue, D-id, grader_version, pass) — never called twice.

Count rules on import (§9.5, shared with `dev health`): per group, a person's confirmed `given_info=wrong`
1 → `watch` (state file); a second while watched, or one in an irreversible class (SPLIT; STAKES on an
irreversible path) → `group.<G>.conservative` in the valves' `auto` area (a person-released valve is never
re-applied — `guildcore.valves`). `watch` clears after 10 consecutive confirmed non-wrong judgments.
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
    """unsure, coerced (not by first-sprint / valve), or a later loop-back / needs-human / QA fail / review
    rejection on the Issue (K5r4-m5: from its history — `history_triggers`)."""
    if str(b.get("unsure")).lower() == "true":
        return "unsure"
    if str(b.get("coerced")).lower() == "true" and b.get("coerced_by") not in ("first-sprint", "valve"):
        return "coerced"
    if later_events:
        return later_events
    return None


KICKOFF_ASKS = ("readiness", "interpretation-surface", "close-decided", "premise")
STAGE_ORDER = ("analyze", "design", "execute", "test", "qa")


def _human_decided(blocks):
    """The engine decisions a person already decided (§9.5): the pending block every `by: human` resolution
    resolves, and — K5r4-m5 — the KICKOFF decisions of an Issue whose KICKOFF-group question a person answered
    (the readiness answer IS the human judgment of that KICKOFF)."""
    out = set(b.get("resolves") for b in blocks if b.get("by") == "human" and b.get("resolves"))
    pend = dict((b.id, b) for b in blocks)
    kick = any(b.get("by") == "human" and b.get("resolves") and (b.get("kind") or (pend.get(b.get("resolves")) or
                                                                                    {}).get("kind")) in KICKOFF_ASKS
               for b in blocks if hasattr(b, "get"))
    if kick:
        out.update(b.id for b in blocks if b.get("point") == "KICKOFF")
    return out


def history_triggers(blocks, loopbacks=(), needs_human_events=0, review_rejections=0):
    """K5r4-m5: `later(block) -> str|None` from the Issue's history (§9.5 촉발 — 연결된 리뷰 반려·이후 loop-back·
    needs-human·QA fail): a pending question or pause after it in the log; a loop-back from a stage at or after its
    stage (the loop-back record — `loopbacks` = [from-stage]); a QA `block`/`fail` after it; a timeline
    `guild:needs-human` label event (no order there — every decision of the Issue, the conservative side); a PR
    review that requested changes (every decision of the Issue)."""
    def later(b):
        why = []
        if any(x.n > b.n and (x.get("status") == "pending-human" or x.get("cause")) for x in blocks):
            why.append("needs-human")
        elif needs_human_events:
            why.append("needs-human (timeline)")
        st = b.get("stage") or ""
        si = STAGE_ORDER.index(st) if st in STAGE_ORDER else 0
        if any(f in STAGE_ORDER and STAGE_ORDER.index(f) >= si for f in loopbacks):
            why.append("loop-back")
        if any(x.n > b.n and (x.get("point") or "").split(":")[0] == "QA" and
               any(w in str(x.get("choice") or "") for w in ("block", "fail")) for x in blocks):
            why.append("qa-fail")
        if review_rejections:
            why.append("review: changes requested")
        return ", ".join(why) or None
    return later


def select(blocks_by_issue, repo, first_sprint, rate, later, grader=None):
    """[(issue, block, why)] for the sheet. `later(issue, block) -> str|None` names a later loop-back /
    needs-human. `blocks_by_issue` = {issue: [blocks]} (trusted records, superseded ones dropped). `grader` =
    {(issue, D-id): grader row} (latest pass) — flagged ones go to the person, calibration from its `ok`s."""
    out, calib = [], {}
    grader = grader or {}
    for issue in sorted(blocks_by_issue):
        human_resolved = _human_decided(blocks_by_issue[issue])
        for b in blocks_by_issue[issue]:
            if not _engine_made(b) or b.id in human_resolved or b.get("shadow") == "true":
                continue
            g = group_of(b)
            gr = grader.get((issue, b.id))
            why = triggered(b, later(issue, b))
            if why:
                out.append((issue, b, "triggered: %s" % why))
            elif g in HIGH_RISK and (first_sprint or _h(repo, issue, b.id) < rate):
                out.append((issue, b, "high-risk sample"))
            elif gr is not None and gr.get("flagged"):
                out.append((issue, b, "grader flagged"))
            elif g in SELECTIVE and (gr is None or gr.get("given_info") == "ok"):
                calib.setdefault(g, []).append((issue, b))
    per = 2 if first_sprint else 1
    for g, items in sorted(calib.items()):
        items.sort(key=lambda ib: _h(repo, ib[0], ib[1].id))
        out += [(i, b, "calibration") for i, b in items[:per]]
    return out


def grader_select(blocks_by_issue, repo, first_sprint, rate, later):
    """[(issue, block, why)] the grader grades: never KICKOFF; a HANDOFF shadow only when it reported a gap;
    triggered always; the rest 100 % in the first sprint, `rate` after (its own hash salt)."""
    out = []
    for issue in sorted(blocks_by_issue):
        human_resolved = _human_decided(blocks_by_issue[issue])
        for b in blocks_by_issue[issue]:
            if not _engine_made(b) or b.id in human_resolved:
                continue
            g = group_of(b)
            if g == "KICKOFF":
                continue
            if b.get("shadow") == "true":
                if (b.get("choice") or "") in ("upstream_gap", "ok_with_assumption"):
                    out.append((issue, b, "shadow gap"))
                continue
            if g not in HIGH_RISK and g not in SELECTIVE:
                continue
            why = triggered(b, later(issue, b))
            if why:
                out.append((issue, b, "triggered: %s" % why))
            elif first_sprint or _h("grader|" + repo, issue, b.id) < rate:
                out.append((issue, b, "sample"))
    return out


def predict_first_judgments(blocks, issue):
    """K5r4 (b): the blind human judgments in one Issue's log — [row] (see the module doc). Excluded: a refused
    blind (`predict_first_refused`), a resolution that could not reveal (`reveal: unavailable` / no `recommended`),
    `stop`, and every answer that saw the recommendation (no `predict_first` on its pending block)."""
    from workflows.dev import predict as PF
    pend = dict((b.id, b) for b in blocks)
    rows = []
    for r in blocks:
        q = pend.get(r.get("resolves")) if r.get("by") == "human" else None
        if q is None or not q.get("predict_first") or q.get("predict_first_refused"):
            continue
        if r.get("reveal") == "unavailable" or r.get("recommended") in (None, ""):
            continue
        ch = r.get("choice")
        if not ch or ch == "stop":
            continue

        class _Q(object):
            kind, point, group = q.get("kind") or "", q.get("point") or "", None
        g = PF.group_of(_Q(), q.get("stage"))
        if g is None:
            continue
        rows.append({"decision_id": q.id, "issue": issue, "stage": q.get("stage") or "", "group": g,
                     "mode": "predict-first", "choice": ch, "reason": "recommended %s (%s)" % (
                         r.get("recommended"), q.get("predict_first")),
                     "given_info": "ok" if ch == r.get("recommended") else "wrong", "outcome": "",
                     "note": "resolution %s" % r.id})
    return rows


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
    skipped); then the count rules. Returns {"imported": n, "watch": [...], "conservative": [...], "grader": [...]}
    — `grader` = the grader's output for the imported rows, revealed only now (R4J-m4)."""
    rows = [r for r in csv.DictReader(io.StringIO(text))]
    res = apply_judgments(common, rows, repo, "human", irreversible)
    gv_rows = latest_grader_rows(common, repo)
    res["grader"] = [{"decision_id": r.get("decision_id"), "issue": r.get("issue"),
                      "human": (r.get("given_info") or "").strip().lower(),
                      "grader": (gv_rows.get((int(r.get("issue") or 0), r.get("decision_id"))) or {}).get("given_info")}
                     for r in rows if (r.get("given_info") or "").strip().lower() in ("ok", "wrong", "unsure")
                     and (int(r.get("issue") or 0), r.get("decision_id")) in gv_rows]
    return res


def apply_judgments(common, rows, repo, version, irreversible=lambda row: False):
    """Human judgments (sheet rows or predict-first answers) → grades.jsonl (key (repo, issue, D-id, version),
    present keys skipped) → the count rules."""
    have = set((g.get("repo"), str(g.get("issue")), g.get("decision_id"), g.get("grader_version"))
               for g in grades(common))
    st = load_state(common)
    st.setdefault("watch", {})
    st.setdefault("streak", {})
    n, cons, watch = 0, [], []
    for row in rows:
        gi = (row.get("given_info") or "").strip().lower()
        if gi not in ("ok", "wrong", "unsure"):
            continue
        key = (repo, str(row.get("issue")), row.get("decision_id"), version)
        if key in have:
            continue
        have.add(key)
        rec = dict((c, row.get(c)) for c in COLUMNS)
        rec.update(repo=repo, grader_version=version, given_info=gi)
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


def latest_grader_rows(common, repo, gv=None):
    """{(issue, D-id): the grader row of the highest pass} (the current grader_version when given)."""
    out = {}
    for g in grades(common):
        if g.get("kind") != "grader" or g.get("repo") != repo or (gv and g.get("grader_version") != gv):
            continue
        k = (int(g.get("issue") or 0), g.get("decision_id"))
        if k not in out or int(g.get("pass") or 1) >= int(out[k].get("pass") or 1):
            out[k] = g
    return out


# ---- the CLI -------------------------------------------------------------------------------------------------

def _issues(d, a, gh):
    if getattr(a, "issues", None):
        return [int(x) for x in str(a.issues).split(",") if x.strip()]
    if a.sprint:
        import re
        body = gh.issue(int(a.sprint)).get("body") or ""
        return sorted(set(int(x) for x in re.findall(r"#(\d+)", body)) - {int(a.sprint)})
    return []


def collect_evidence(gh, n, repo):
    """K5r4 (§9.5 사후 증거): the Issue's post-hoc evidence — its PRs by the Issue's own `closedByPullRequests`
    (never the search API), each PR's state, reviews, CI check-runs of its head and its diff (cut), the people's
    comments (no `<!-- guild:` record), loop-back records and needs-human label events. A read that fails is
    noted, never fatal (grading is not a correctness read). Returns (summary line, full text, facts)."""
    from guildcore.records import loopback as LB
    from guildcore.records import markers
    url = "https://github.com/%s/issues/%d" % (repo, n)
    parts, summ = [], [url]
    facts = {"loopbacks": [], "needs_human_events": 0, "review_rejections": 0}
    try:
        comments = gh.comments(n)
    except Exception as e:                                       # noqa: BLE001
        comments = []
        summ.append("comments unreadable (%s)" % str(e)[:60])
    people = [c for c in comments if "<!-- guild:" not in markers.body_of(c)]
    for c in people[-20:]:
        parts.append("comment by %s (%s): %s" % ((c.get("user") or {}).get("login"), c.get("author_association"),
                                                 " ".join(markers.body_of(c).split())[:600]))
    try:
        rec = LB.from_comments(markers.trusted(comments, ()))
        facts["loopbacks"] = [("test" if b.get("from") == "leader" else str(b.get("from") or "test"))
                              for b in (rec.numbered() if rec else [])]
    except Exception:                                            # noqa: BLE001
        pass
    if facts["loopbacks"]:
        summ.append("loop-backs %d" % len(facts["loopbacks"]))
        parts.append("loop-backs from: %s" % ", ".join(facts["loopbacks"]))
    try:
        tl = gh.timeline(n)
        facts["needs_human_events"] = sum(1 for ev in tl if ev.get("event") == "labeled" and
                                          ((ev.get("label") or {}).get("name") if isinstance(ev.get("label"), dict)
                                           else ev.get("label")) == "guild:needs-human")
    except Exception:                                            # noqa: BLE001
        pass
    if facts["needs_human_events"]:
        summ.append("needs-human x%d" % facts["needs_human_events"])
        parts.append("guild:needs-human was put on the Issue %d time(s)" % facts["needs_human_events"])
    try:
        prs = gh.closed_by_prs(n)
    except Exception as e:                                       # noqa: BLE001
        prs = []
        summ.append("PRs unreadable (%s)" % str(e)[:60])
    for ref in prs[:3]:
        if ref.get("repo") and ref["repo"] != repo:
            continue
        k = int(ref.get("number"))
        try:
            st = gh.pr_state(k)
            summ.append("PR #%d %s" % (k, "merged" if st.get("mergedAt") else (st.get("state") or "").lower()))
            parts.append("PR #%d state: %s merged_at: %s" % (k, st.get("state"), st.get("mergedAt")))
        except Exception:                                        # noqa: BLE001
            pass
        try:
            rv = gh.pr_reviews(k)
            rej = [r for r in rv if (r.get("state") or "").upper() == "CHANGES_REQUESTED"]
            facts["review_rejections"] += len(rej)
            if rv:
                summ.append("reviews %d (changes requested %d)" % (len(rv), len(rej)))
            for r in rv[-10:]:
                parts.append("review (%s) by %s: %s" % (r.get("state"), (r.get("user") or {}).get("login"),
                                                        " ".join(str(r.get("body") or "").split())[:600]))
        except Exception:                                        # noqa: BLE001
            pass
        try:
            head = gh.pr(k).get("headRefOid")
            runs = gh.check_runs(head) if head else []
            bad = [r for r in runs if (r.get("conclusion") or "") not in ("success", "skipped", "neutral")]
            if runs:
                summ.append("CI %d/%d ok" % (len(runs) - len(bad), len(runs)))
                parts.append("CI on %s: %s" % (head[:10], ", ".join("%s=%s" % (r.get("name"), r.get("conclusion"))
                                                                    for r in runs[:20])))
        except Exception:                                        # noqa: BLE001
            pass
        try:
            diff = gh.pr_diff(k) or ""
            if diff:
                parts.append("PR #%d diff (cut):\n%s" % (k, diff[:12000]))
        except Exception:                                        # noqa: BLE001
            pass
    return "; ".join(summ), "\n".join(parts), facts


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
    by_issue, later_fn, ev_sum, ev_full, texts = {}, {}, {}, {}, {}
    pf_rows = []
    for n in issues:
        log = DecisionLog.load(markers.trusted(gh.comments(n), ()))
        gone = log.resolved_ids()
        by_issue[n] = [b for b in log.blocks if b.id not in gone or b.get("by") == "human"]
        ev_sum[n], ev_full[n], facts = collect_evidence(gh, n, repo)
        later_fn[n] = history_triggers(log.blocks, facts["loopbacks"], facts["needs_human_events"],
                                       facts["review_rejections"])
        pf_rows += predict_first_judgments(log.blocks, n)
        try:
            it = gh.issue(n)
            texts[n] = "%s\n\n%s" % (it.get("title") or "", (it.get("body") or "")[:8000])
        except Exception:                                        # noqa: BLE001
            texts[n] = "#%d" % n
    pf = apply_judgments(common, pf_rows, repo, "predict-first")
    valves = VALVES.effective(common, d.env)
    cfg = d.config(d.toplevel())
    eng = ((getattr(cfg, "raw", None) or {}).get("engine") or {}) if cfg else {}
    mode = eng.get("first_sprint_mode") or "auto"
    first = mode == "on" or (mode == "auto" and not _go_recorded(gh, a.sprint))
    rate = valves.get("grading.highrisk_human_rate", VALVES.GRADING_DEFAULT["grading.highrisk_human_rate"])
    later = lambda i, b: later_fn[i](b)                                    # noqa: E731
    graded = []
    if getattr(a, "grader", False):
        graded = run_grader(d, common, repo, by_issue, later, first, valves, eng, ev_full, texts,
                            int(getattr(a, "pass_no", 1) or 1))
        if isinstance(graded, dict):                                       # an error result
            emit.engine(graded, out=d.out)
            return 64
    from workflows.dev import grader as GD
    gv = GD.version(((eng.get("grading") or {}).get("grader_model")) or GD.DEFAULT_TIER)
    sel = select(by_issue, repo, first, rate, later, grader=latest_grader_rows(common, repo, gv))
    rows = sheet_rows(sel, "first-sprint" if first else "steady", lambda i: ev_sum.get(i) or "")
    out_dir = a.out or os.path.join(J.engine_dir(common), "grading")
    os.makedirs(out_dir, exist_ok=True)  # fs-ok: the engine's grading sheet dir under <git-common-dir>/guild/engine or the person's --out
    tag = ("sprint-%s" % a.sprint) if a.sprint else "issues"
    J.atomic_write(os.path.join(out_dir, "%s.csv" % tag), render_csv(rows))
    J.atomic_write(os.path.join(out_dir, "%s.md" % tag), render_md(rows))
    emit.engine({"rows": len(rows), "csv": os.path.join(out_dir, "%s.csv" % tag), "first_sprint": first,
                 "predict_first": {"judgments": len(pf_rows), "imported": pf["imported"], "watch": pf["watch"],
                                   "conservative": pf["conservative"]},
                 "graded": len(graded)}, out=d.out)
    return 0


def run_grader(d, common, repo, by_issue, later, first, valves, eng, ev_full, texts, pass_no):
    """The grader pass: pass 1 = the grader's selection; pass 2 = only pass-1 `unsure`s. Already graded keys
    (repo, issue, D-id, grader_version, pass) are never called again. Rows → grades.jsonl (`kind: grader`)."""
    from workflows.dev import grader as GD
    tier = ((eng.get("grading") or {}).get("grader_model")) or GD.DEFAULT_TIER
    if tier not in ("haiku", "sonnet", "opus"):
        return {"error": "config.engine.grading.grader_model must be haiku|sonnet|opus"}
    gv = GD.version(tier)
    judge = getattr(d, "grader_judge", None)                     # tests: a fake judge (never a paid call)
    if judge is None:
        version = None
        try:
            version = VERSION_own()
        except Exception:                                        # noqa: BLE001
            pass
        _r, jr = d.runners(common, None, None, version, d.config(d.toplevel()))
        judge = jr.judge
    done = set((int(g.get("issue") or 0), g.get("decision_id"), int(g.get("pass") or 1))
               for g in grades(common) if g.get("kind") == "grader" and g.get("grader_version") == gv
               and g.get("repo") == repo)
    if pass_no == 1:
        rate = valves.get("grading.grader_rate", VALVES.GRADING_DEFAULT["grading.grader_rate"])
        todo = grader_select(by_issue, repo, first, rate, later)
    else:
        prev = latest_grader_rows(common, repo, gv)
        blocks = dict(((i, b.id), b) for i, bs in by_issue.items() for b in bs)
        todo = [(k[0], blocks[k], "pass 2") for k, r in sorted(prev.items())
                if int(r.get("pass") or 1) == 1 and r.get("given_info") == "unsure" and k in blocks]
    out = []
    for issue, b, why in todo:
        if (issue, b.id, pass_no) in done:
            continue
        row = GD.grade(judge, b, issue, group_of(b), ev_full.get(issue) or "", tier, texts.get(issue) or "",
                       gv, pass_no)
        row.update(kind="grader", repo=repo, selected=why)
        J.fsync_append(grades_path(common), json.dumps(row, ensure_ascii=False, sort_keys=True))
        out.append(row)
    return out


def VERSION_own():
    from guildcore import version as V
    return V.own_version()


def _go_recorded(gh, tracker):
    """§10.4: first-sprint mode ends only on a `first-sprint go/no-go` note with `result: go` on GitHub."""
    if not tracker:
        return False
    from guildcore.records import markers
    from workflows.dev.predict import is_go_note
    return any(is_go_note(markers.body_of(c)) for c in markers.trusted(gh.comments(int(tracker)), ()))
