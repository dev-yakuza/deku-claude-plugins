"""workflows.dev.grade — `dev grade` (design §9.5, §10.4 first-sprint sheet).

    dev grade --sprint T | --issues N,M [--out DIR] [--grader [--pass 2]]
    dev grade --import CSV                     the person's filled sheet → grades.jsonl + count rules (+ the grader's
                                               output for those rows, revealed only now — R4J-m4)

Human judgments (§9.5 "사람 판정 = 블라인드 채점표 답 + predict-first 답"):
* the blind sheet rows a person fills (`--import`);
* predict-first ANSWERS — a resolved question whose pending block carried `predict_first` (never
  `predict_first_refused`), whose resolution revealed `recommended` (never `reveal: unavailable`) and whose answer
  is counted (K5r6-M2: at least two real options; `stop` is a CANDIDATE, never an `ok`). K5r5-M2 (user decision 2026-11-19): only a question the ENGINE raised although
  the judge was sure (`raised_by: confirm` — the first-sprint confirmation, a conservative group) counts; a question
  the judge itself raised (`judge-unclear`, `judge-surface`, or no `raised_by`) is out of the count either way. The
  answer equal to the hidden recommendation → `ok` (grades.jsonl, grader_version `predict-first`, the count rules);
  a DIFFERENT answer is only a wrong CANDIDATE: it goes on the sheet (`predict-first candidate`) for a person to
  confirm — only that person's `given_info=wrong` (imported like any sheet row) is a §9.5 / G1 wrong; nothing sets
  `watch` / `conservative` before. An answer that saw the recommendation stays a decision (`by: human`) only.
  K6 r2 M1: a conservative-gate question of a group with ONE non-conservative option (`conservative.INHERENT`) exists
  only because the judge chose that option — its answer is neither an `ok` nor a candidate; every such question is a
  sheet row (`mode: inherent-gate`, `choice` = the judge's pick, `inherent_row`) the person grades on the evidence,
  open (holding the §10.2-6 release) until imported.

Selection (deterministic — `(repo, issue, D-id)` hash, never random):
* only L0/SJ decisions the engine made (`by: judge:*` / `leader:*`); a decision a person already decided (an
  ask answer, a pause resolution — `by: human`) is never on the sheet again — K5r4-m5: nor is a KICKOFF whose
  readiness / interpretation / close question a person answered;
* high-risk groups (KICKOFF · STAKES · EX-ARB dismiss/dispute · ESCALATE · SPLIT · INTEGRATE): first sprint
  100 %, after that `grading.highrisk_human_rate` (default 0.3, a valve may only lower it, floor 0.2);
* K5r5-M3: a group on `watch` → every engine decision of that group (§9.5 "그 그룹 결정 전부 사람 + 채점자");
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
irreversible path) → `group.<G>.conservative` in the valves' `auto` area. K5r6-M3: a person's release of that
valve is an event — the group's watch/streak start again and later confirmed wrongs may set it again. `watch` clears after 10 consecutive confirmed non-wrong judgments.
"""

import csv
import hashlib
import io
import json
import os

from guildcore import journal as J
from guildcore import valves as VALVES
from workflows.dev import unverified as UV

HIGH_RISK = ("KICKOFF", "STAKES", "EX-ARB:dismiss", "ESCALATE", "SPLIT", "INTEGRATE")
SELECTIVE = ("TEST", "QA", "EX-ARB:accept", "DE-ARB", "AN-PO", "VIS-ENV", "DIRECTIVE", "HANDOFF", "EX-DWC")
IRREVERSIBLE = ("SPLIT",)
COLUMNS = ("decision_id", "issue", "stage", "group", "mode", "choice", "reason", "coerced", "coerced_by",
           "unsure", "irreversible", "evidence", "given_info", "outcome", "note")
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
    if str(b.get("dual") or "") == "disagree":                   # K6 item 11: §9.5 — 이중 판단 불일치
        return "dual-judge disagreement (%s said %s)" % (b.get("dual_model") or "-", b.get("dual_choice") or "-")
    if str(b.get("coerced")).lower() == "true" and b.get("coerced_by") not in ("first-sprint", "valve", "conservative"):
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


def select(blocks_by_issue, repo, first_sprint, rate, later, grader=None, watch=()):
    """[(issue, block, why)] for the sheet. `later(issue, block) -> str|None` names a later loop-back /
    needs-human. `blocks_by_issue` = {issue: [blocks]} (trusted records, superseded ones dropped). `grader` =
    {(issue, D-id): grader row} (latest pass) — flagged ones go to the person, calibration from its `ok`s.
    `watch` = the groups on watch (K5r5-M3): all of their decisions go to the person."""
    out, calib = [], {}
    grader = grader or {}
    watch = set(watch or ())
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
            elif g in watch:
                out.append((issue, b, "watch: 100%"))
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


def grader_select(blocks_by_issue, repo, first_sprint, rate, later, watch=()):
    """[(issue, block, why)] the grader grades: never KICKOFF; a HANDOFF shadow only when it reported a gap;
    triggered always; a `watch` group 100 % (K5r5-M3); the rest 100 % in the first sprint, `rate` after (its own
    hash salt)."""
    out = []
    watch = set(watch or ())
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
            elif g in watch:
                out.append((issue, b, "watch: 100%"))
            elif first_sprint or _h("grader|" + repo, issue, b.id) < rate:
                out.append((issue, b, "sample"))
    return out


CONFIRM = "confirm"


def predict_first_judgments(blocks, issue):
    """The blind human answers in one Issue's log → (counted, candidates) — see the module doc (K5r5-M2).
    `counted` = `ok` rows (the person, blind, chose the hidden recommendation on a `confirm` question);
    `candidates` = sheet rows for a person to confirm (a different blind answer on a `confirm` question).
    Excluded: a refused blind (`predict_first_refused`), a resolution that could not reveal (`reveal: unavailable`
    / no `recommended`), every answer that saw the recommendation (no `predict_first`), every question the judge
    raised itself (`raised_by` ≠ confirm), and — K5r6-M2 — an answer equal to the recommendation on a question with
    one real option (`predict_first_counted: false`). `stop` is a candidate (K5r6-M2(b)). K6 r1 M2: a question asked
    after an earlier answer of the same decision point (`predict_first_counted: false — after-reveal`) is neither an
    `ok` nor a candidate — the recommendation of that time was revealed."""
    from guildcore import ask as ASK
    from workflows.dev import predict as PF
    pend = dict((b.id, b) for b in blocks)
    counted, cands = [], []
    for r in blocks:
        q = pend.get(r.get("resolves")) if r.get("by") == "human" else None
        if q is None:
            continue
        row = inherent_row(q, r, issue)
        if row is not None:
            cands.append(row)            # K6 r2 M1: never an `ok` / candidate — the sheet verdict releases the group
            continue
        if not q.get("predict_first") or q.get("predict_first_refused"):
            continue
        if r.get("reveal") == "unavailable" or r.get("recommended") in (None, ""):
            continue
        ch = r.get("choice")
        if not ch:
            continue
        if q.get("raised_by") != CONFIRM:
            continue                     # the judge said it could not decide / asked a person — not its wrong
        if str(q.get("predict_first_counted") or "").startswith("false — " + ASK.AFTER_REVEAL):
            continue                     # K6 r1 M2: an earlier recommendation of the point was revealed — not blind
        # K5r6-M2(a): one real option (`i1 | stop`) is no blind judgment between options — never an `ok`
        real = [t for t in q.options() if t != "stop"]
        one = len(real) < 2 or str(q.get("predict_first_counted") or "").startswith("false")

        class _Q(object):
            kind, point, group = q.get("kind") or "", q.get("point") or "", q.get("group")
        g = PF.group_of(_Q(), q.get("stage"))
        if g is None:
            continue
        row = {"decision_id": q.id, "issue": issue, "stage": q.get("stage") or "", "group": g,
               "mode": "predict-first", "choice": r.get("recommended"), "coerced": "false", "coerced_by": "",
               "unsure": "false", "irreversible": "true" if q.get("irreversible") == "true" else "",
               "outcome": "", "note": "resolution %s" % r.id}
        if ch == "stop":
            # K5r6-M2(b): `stop` on a blind engine-raised question rejects every option — the strongest "the
            # recommendation was wrong" signal: a CANDIDATE (the person confirms it on the sheet, like any other)
            cands.append(dict(row, reason="wrong candidate: the person, blind, answered stop (none of %s); the engine "
                                          "recommended %s (%s)" % ("|".join(real) or "-", r.get("recommended"),
                                                                  q.get("predict_first")),
                              given_info="", evidence="predict-first candidate (stop) — confirm: was the engine's %s "
                                                      "wrong, or did the person only stop the run?" % r.get("recommended")))
        elif ch == r.get("recommended"):
            if one:
                continue                 # uncounted (`predict_first_counted: false`) — see above
            counted.append(dict(row, reason="blind answer = recommended %s (%s)" % (ch, q.get("predict_first")),
                                given_info="ok", evidence=""))
        else:
            cands.append(dict(row, reason="wrong candidate: the person, blind, chose %s; the engine recommended %s "
                                          "(%s)" % (ch, r.get("recommended"), q.get("predict_first")),
                              given_info="", evidence="predict-first candidate — confirm: was %s clearly better on "
                                                      "what the engine knew?" % ch))
    return counted, cands


INHERENT_MODE = "inherent-gate"


def _inherent_group(q):
    """K6 r2 M1: the group of a conservative-gate question whose existence states its recommendation
    (`conservative.INHERENT` — one non-conservative option), or None."""
    from workflows.dev import conservative as CONS
    if q.get("kind") != CONS.KIND:
        return None
    g = q.get("group") or str(q.get("point") or "").partition(":")[2]
    return g if g in CONS.INHERENT else None


def inherent_row(q, r, issue):
    """K6 r2 M1: a person's answer (blind or not, revealed or not, after-reveal or not) to an INHERENT gate question
    → one grading-sheet row for the person to judge the engine's decision on the evidence (`mode: inherent-gate`,
    `choice` = the judge's non-conservative pick); open until imported. Never an `ok` nor a wrong candidate: the
    person knew the recommendation from the question's existence. None for any other question."""
    g = _inherent_group(q)
    ch = r.get("choice")
    if g is None or not ch:
        return None
    from workflows.dev import conservative as CONS
    rec = r.get("recommended") or q.get("recommended") or CONS.INHERENT[g]
    return {"decision_id": q.id, "issue": issue, "stage": q.get("stage") or "", "group": g, "mode": INHERENT_MODE,
            "choice": rec, "coerced": "false", "coerced_by": "", "unsure": "false",
            "irreversible": "true" if q.get("irreversible") == "true" else "", "outcome": "",
            "note": "resolution %s" % r.id,
            "reason": "inherent gate: asked only because the engine chose %s; the person answered %s" % (rec, ch),
            "given_info": "",
            "evidence": "inherent-gate verdict — grade the engine's %s on the evidence (ok = it was right, wrong = it "
                        "was not); the question's existence revealed it, so the answer was no blind judgment" % rec}


def sheet_rows(selected, mode, evidence):
    rows = []
    for issue, b, why in selected:
        rows.append({"decision_id": b.id, "issue": issue, "stage": b.get("stage") or "", "group": group_of(b),
                     "mode": mode, "choice": b.get("raw_choice") or b.get("choice") or "",
                     "reason": " ".join((b.get("reason") or "").split())[:300],
                     "coerced": b.get("coerced") or "false", "coerced_by": b.get("coerced_by") or "",
                     "unsure": b.get("unsure") or "false",
                     "irreversible": "true" if b.get("irreversible") == "true" else "",
                     "evidence": "%s; %s" % (why, evidence(issue)),
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


def _now():
    import time
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


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


def irreversible_row(row):
    """§9.5 rule 2's irreversible class (K5r5-M3): SPLIT always (IRREVERSIBLE), a STAKES decision whose block the code
    marked `irreversible: true` (an irreversible path — `arbitration.stakes`) — carried on the sheet row."""
    return str(row.get("irreversible") or "").strip().lower() == "true"


def engine_view(b):
    """(group, irreversible) the engine's OWN record says for a sheet row's D-id — a decision block, or the pending
    block of a predict-first question (K5r6-m2)."""
    if b.get("status") == "pending-human":
        from workflows.dev import predict as PF

        class _Q(object):
            kind, point, group = b.get("kind") or "", b.get("point") or "", b.get("group")
        g = PF.group_of(_Q(), b.get("stage"))
    else:
        g = group_of(b)
    return g, (g in IRREVERSIBLE or b.get("irreversible") == "true")


def verify_rows(rows, blocks_of):
    """K5r6-m2: a filled sheet row's `group` / `irreversible` are re-derived from the engine's decision log (never
    taken as written — an edit slip must not become `conservative`); a D-id the log does not have is rejected.
    Returns (rows, rejected)."""
    out, rejected, cache = [], [], {}
    for r in rows:
        if (r.get("given_info") or "").strip().lower() not in ("ok", "wrong", "unsure"):
            out.append(r)
            continue
        try:
            n = int(r.get("issue") or 0)
            if n not in cache:
                cache[n] = dict((b.id, b) for b in blocks_of(n))
            b = cache[n].get(r.get("decision_id"))
        except Exception:                                        # noqa: BLE001 — unreadable = not verified
            b = None
        if b is None:
            rejected.append({"decision_id": r.get("decision_id"), "issue": r.get("issue"),
                             "why": "no such decision in the engine's log"})
            continue
        g, irr = engine_view(b)
        if not g:
            rejected.append({"decision_id": r.get("decision_id"), "issue": r.get("issue"), "why": "no §9.5 group"})
            continue
        fixed = dict(r, group=g, irreversible="true" if irr else "")
        # K6 r2 M1: an inherent group's sheet verdict counts toward its release only on its non-conservative pick —
        # the choice and the mode come from the log (a pending gate block: the pick its resolution revealed)
        from workflows.dev import conservative as CONS
        if g in CONS.INHERENT:
            if _inherent_group(b) is not None:
                res = [x for x in cache[n].values() if x.get("resolves") == b.id and x.get("by") == "human"]
                fixed["choice"] = (res[-1].get("recommended") if res else None) or b.get("recommended") or ""
                fixed["mode"] = INHERENT_MODE
            else:
                fixed["choice"] = b.get("raw_choice") or b.get("choice") or ""
                if fixed.get("mode") == INHERENT_MODE:
                    fixed["mode"] = ""
        # K5r7-m5: a release forgives by DECISION time — K5r8-m4: the log's time only; none in the log = unknown
        # (no forgiveness), never the sheet's `decided_at` column
        fixed["decided_at"] = b.get("at") or ""
        if (r.get("group") or "") != g or str(r.get("irreversible") or "").strip().lower() != fixed["irreversible"]:
            fixed["note"] = ("%s [sheet group/irreversible %s/%s replaced by the log's]" % (
                r.get("note") or "", r.get("group") or "-", r.get("irreversible") or "-")).strip()
        out.append(fixed)
    return out, rejected


def import_sheet(common, text, repo, irreversible=irreversible_row, blocks_of=None):
    """Rows with given_info filled → grades.jsonl (key (repo, issue, D-id, "human"); a key already present is
    skipped); then the count rules. Returns {"imported": n, "watch": [...], "conservative": [...], "grader": [...]}
    — `grader` = the grader's output for the imported rows, revealed only now (R4J-m4). `blocks_of(issue)` (the
    CLI: the Issue's trusted decision log) re-derives each row's group / irreversible (K5r6-m2)."""
    rows = [r for r in csv.DictReader(io.StringIO(text))]
    rejected = []
    if blocks_of is not None:
        rows, rejected = verify_rows(rows, blocks_of)
    else:                                                    # K5r8-m4: a sheet's own `decided_at` is not trusted
        rows = [dict(r, decided_at="") for r in rows]
    res = apply_judgments(common, rows, repo, "human", irreversible)
    if rejected:
        res["rejected"] = rejected
    gv_rows = latest_grader_rows(common, repo)
    res["grader"] = [{"decision_id": r.get("decision_id"), "issue": r.get("issue"),
                      "human": (r.get("given_info") or "").strip().lower(),
                      "grader": (gv_rows.get((int(r.get("issue") or 0), r.get("decision_id"))) or {}).get("given_info")}
                     for r in rows if (r.get("given_info") or "").strip().lower() in ("ok", "wrong", "unsure")
                     and (int(r.get("issue") or 0), r.get("decision_id")) in gv_rows]
    return res


def sync_releases(common, st):
    """K5r6-M3: a person's release of `group.<g>.conservative` (`valves.human_released_at`) forgives that group's
    wrongs up to then — its `watch` and streak start again (§9.5 rules 1–2 from the start). Applied once per release
    (`released` in the state). Returns the groups reset."""
    rel = (VALVES.load(common)["human"].get("released_at") or {})
    seen = st.setdefault("released", {})
    out = []
    for key, at in sorted(rel.items()):
        m = VALVES.COUNT_RULE.match(key)
        if not m or seen.get(key) == at:
            continue
        g = m.group(1).replace("EX-ARB-", "EX-ARB:")
        st.setdefault("watch", {}).pop(g, None)
        st.setdefault("streak", {})[g] = 0
        seen[key] = at
        out.append(g)
    return out


def on_release(common):
    """`dev valve clear group.<g>.conservative` → the grade state follows at once (watch / streak reset)."""
    st = load_state(common)
    if sync_releases(common, st):
        J.atomic_write(state_path(common), json.dumps(st, sort_keys=True, indent=1))


def apply_judgments(common, rows, repo, version, irreversible=lambda row: False, candidates=None):
    """Human judgments (sheet rows or predict-first answers) → grades.jsonl (key (repo, issue, D-id, version),
    present keys skipped) → the count rules. K5r6-M3: `conservative` lists only groups whose valve is IN FORCE after
    this import (the count rule set it now, or it already was); a set the valves refused is `blocked_by_release`."""
    have = set((g.get("repo"), str(g.get("issue")), g.get("decision_id"), g.get("grader_version"))
               for g in grades(common))
    st = load_state(common)
    st.setdefault("watch", {})
    st.setdefault("streak", {})
    sync_releases(common, st)
    if candidates is not None:
        UV.note_candidates(st, candidates)            # K6 r1 m1: no release while a candidate of the group is open
    released_at = VALVES.load(common)["human"].get("released_at") or {}
    blocked, forgiven, released = [], [], []
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
        # K6 item 4: a person's verdict on a blind answer of an unverified group counts toward its release (a wrong
        # forgiven by a valve release below still keeps the group unverified)
        rel_g = UV.count(st, dict(row, given_info=gi), _now(), source=version)
        if rel_g:
            released.append(rel_g)
        rel = released_at.get("group.%s.conservative" % g.replace(":", "-"))
        if gi == "wrong" and rel and row.get("decided_at") and str(row.get("decided_at")) < str(rel):
            # K5r7-m5: a wrong DECIDED before the person's release (imported after it) is forgiven with the rest —
            # recorded, but no watch / conservative step
            forgiven.append(row.get("decision_id"))
            continue
        if gi == "wrong":
            st["streak"][g] = 0
            if g in st["watch"] or g in IRREVERSIBLE or irreversible(row):
                if VALVES.auto_set(common, "group.%s.conservative" % g.replace(":", "-"), True,
                                   "count rule: confirmed wrong %s (%s)" % (row.get("decision_id"), "irreversible"
                                                                            if g in IRREVERSIBLE or irreversible(row)
                                                                            else "while watched")):
                    cons.append(g)
                else:
                    blocked.append(g)
            st["watch"][g] = st["watch"].get(g) or row.get("decision_id")
            watch.append(g)
        elif gi == "ok":
            st["streak"][g] = st["streak"].get(g, 0) + 1
            if g in st["watch"] and st["streak"][g] >= WATCH_CLEAR_AFTER:
                del st["watch"][g]
    J.atomic_write(state_path(common), json.dumps(st, sort_keys=True, indent=1))
    eff = VALVES.effective(common, {})
    cons = [g for g in cons if eff.get("group.%s.conservative" % g.replace(":", "-")) not in (None, False)]
    out = {"imported": n, "watch": sorted(set(watch)), "conservative": sorted(set(cons))}
    if blocked:
        out["blocked_by_release"] = sorted(set(blocked))
    if forgiven:
        out["forgiven_by_release"] = forgiven
    if released:
        out["unverified_released"] = sorted(set(released))
    return out


QUALITY_MIN_WRONG = 10           # §9.5: grader `wrong`s a person judged before the confirmation rate is read
QUALITY_CONFIRM_FLOOR = 0.5      # below this share confirmed → adjust the prosecutor prompt
REVISION_WINDOW = 20             # §9.5: a grader revision re-grades the latest 20 person-judged decisions


def _human_verdicts(common, repo):
    """{(issue, D-id): (given_info, order)} — the person's verdicts (sheet `human` + blind `predict-first` oks)."""
    out = {}
    for i, g in enumerate(grades(common)):
        if g.get("repo") != repo or g.get("kind") == "grader" or g.get("grader_version") not in ("human", "predict-first"):
            continue
        gi = (g.get("given_info") or "").lower()
        if gi in ("ok", "wrong"):
            out[(int(g.get("issue") or 0), g.get("decision_id"))] = (gi, i)
    return out


def grader_quality(common, repo, gv=None, prev_gv=None):
    """K6 item 11 — the §9.5 grader-quality rules, over this clone's grades.jsonl:
    * `wrong_confirmation`: of the grader's `wrong`s a person judged, the share the person confirmed; with ≥ 10 and
      < 50 % → `alert` (adjust the prosecutor prompt — a person's call; nothing changes by itself);
    * `revision`: when `gv` (a new grader_version) and `prev_gv` both graded the latest 20 person-judged decisions,
      the share of exact agreement with the person for each — the new version is adoptable only when ≥ the old
      (`adoptable`); fewer than 20 re-graded → `adoptable: null` (not decidable yet)."""
    human = _human_verdicts(common, repo)
    rows = [g for g in grades(common) if g.get("kind") == "grader" and g.get("repo") == repo]
    cur = gv or (rows[-1].get("grader_version") if rows else None)
    latest = latest_grader_rows(common, repo, cur) if cur else {}
    wrongs = [k for k, r in latest.items() if r.get("given_info") == "wrong" and k in human]
    conf = sum(1 for k in wrongs if human[k][0] == "wrong")
    rate = (float(conf) / len(wrongs)) if wrongs else None
    out = {"grader_version": cur, "wrong_confirmation": {
        "judged": len(wrongs), "confirmed": conf, "rate": rate,
        "alert": bool(len(wrongs) >= QUALITY_MIN_WRONG and rate is not None and rate < QUALITY_CONFIRM_FLOOR)}}
    if gv and prev_gv:
        window = [k for k, _v in sorted(human.items(), key=lambda kv: kv[1][1])][-REVISION_WINDOW:]

        def agree(v):
            got = latest_grader_rows(common, repo, v)
            have = [k for k in window if k in got]
            if len(have) < REVISION_WINDOW:
                return None, len(have)
            return sum(1 for k in have if got[k].get("given_info") == human[k][0]) / float(len(have)), len(have)
        a_new, n_new = agree(gv)
        a_old, n_old = agree(prev_gv)
        out["revision"] = {"new": gv, "old": prev_gv, "new_agreement": a_new, "old_agreement": a_old,
                           "regraded": [n_new, n_old],
                           "adoptable": None if a_new is None or a_old is None else a_new >= a_old}
    return out


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
    uparts = []                          # K5r5-m4 (P2): outsider / unknown authors — never evidence for `ok`
    people = [c for c in comments if "<!-- guild:" not in markers.body_of(c)]
    for c in people[-20:]:
        tv = trust_of(c)
        (parts if tv == "member" else uparts).append("comment by %s (%s, %s): %s" % (
            (c.get("user") or {}).get("login"), c.get("author_association"), tv,
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
                tv = trust_of(r)
                (parts if tv == "member" else uparts).append("review (%s) by %s (%s): %s" % (
                    r.get("state"), (r.get("user") or {}).get("login"), tv,
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
    facts["trusted"], facts["untrusted"] = "\n".join(parts), "\n".join(uparts)
    full = "\n".join(parts)
    if uparts:
        full += "\n" + UNTRUSTED_HEAD + "\n" + "\n".join(uparts)
    return "; ".join(summ), full, facts


UNTRUSTED_HEAD = "## untrusted (outsider or unknown author — data, not evidence for `ok`)"


def trust_of(item):
    """K5r5-m4, P2 three-valued: member (OWNER/MEMBER/COLLABORATOR) | outsider (any other association) | unknown
    (missing / blank — never folded into either side)."""
    from guildcore.records import markers
    a = str(item.get("author_association") or "").strip()
    if not a:
        return "unknown"
    return "member" if a in markers.TRUSTED else "outsider"


def main(d, a):
    from guildcore import emit
    common = d.common()
    if a.import_csv:
        with open(a.import_csv, encoding="utf-8") as fh:
            text = fh.read()
        gh = d.gh()
        from guildcore.decisions import DecisionLog
        from guildcore.records import markers
        res = import_sheet(common, text, gh.owner_repo(), irreversible_row,
                           blocks_of=lambda n: DecisionLog.load(markers.trusted(gh.comments(n), ())).blocks)
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
    by_issue, later_fn, ev_sum, ev_full, texts, ev_untr = {}, {}, {}, {}, {}, {}
    pf_rows, pf_cands = [], []
    acs = {}
    for n in issues:
        tcs = markers.trusted(gh.comments(n), ())
        log = DecisionLog.load(tcs)
        acs[n] = ac_text(tcs)                                  # K6 item 11: call ① sees the Issue's AC
        gone = log.resolved_ids()
        by_issue[n] = [b for b in log.blocks if b.id not in gone or b.get("by") == "human"]
        ev_sum[n], _full, facts = collect_evidence(gh, n, repo)
        ev_full[n], ev_untr[n] = facts.get("trusted") or "", facts.get("untrusted") or ""
        later_fn[n] = history_triggers(log.blocks, facts["loopbacks"], facts["needs_human_events"],
                                       facts["review_rejections"])
        ok_rows, cands = predict_first_judgments(log.blocks, n)
        pf_rows += ok_rows
        pf_cands += cands
        try:
            it = gh.issue(n)
            texts[n] = "%s\n\n%s" % (it.get("title") or "", (it.get("body") or "")[:8000])
        except Exception:                                        # noqa: BLE001
            texts[n] = "#%d" % n
    confirmed = set((str(g.get("issue")), g.get("decision_id")) for g in grades(common)
                    if g.get("repo") == repo and g.get("grader_version") == "human")
    pf_cands = [r for r in pf_cands if (str(r["issue"]), r["decision_id"]) not in confirmed]
    # `ok`s only (K5r5-M2); K6 r1 m1: the candidates still open hold back their group's §10.2-6 release
    pf = apply_judgments(common, pf_rows, repo, "predict-first", candidates=pf_cands)
    watch = sorted((load_state(common).get("watch") or {}).keys())
    valves = VALVES.effective(common, d.env)
    cfg = d.config(d.toplevel())
    eng = ((getattr(cfg, "raw", None) or {}).get("engine") or {}) if cfg else {}
    mode = eng.get("first_sprint_mode") or "auto"
    first = mode == "on" or (mode == "auto" and not _go_recorded(gh, a.sprint))
    rate = valves.get("grading.highrisk_human_rate", VALVES.GRADING_DEFAULT["grading.highrisk_human_rate"])
    later = lambda i, b: later_fn[i](b)                                    # noqa: E731
    graded = []
    if getattr(a, "grader", False):
        d.grading_acs = acs
        graded = run_grader(d, common, repo, by_issue, later, first, valves, eng, ev_full, texts,
                            int(getattr(a, "pass_no", 1) or 1), watch, ev_untr)
        if isinstance(graded, dict):                                       # an error result
            emit.engine(graded, out=d.out)
            return 64
    from workflows.dev import grader as GD
    gv = GD.version(((eng.get("grading") or {}).get("grader_model")) or GD.DEFAULT_TIER)
    sel = select(by_issue, repo, first, rate, later, grader=latest_grader_rows(common, repo, gv), watch=watch)
    rows = sheet_rows(sel, "first-sprint" if first else "steady", lambda i: ev_sum.get(i) or "")
    rows += [dict((c, r.get(c, "")) for c in COLUMNS) for r in pf_cands]   # K5r5-M2: a person confirms
    out_dir = a.out or os.path.join(J.engine_dir(common), "grading")
    os.makedirs(out_dir, exist_ok=True)  # fs-ok: the engine's grading sheet dir under <git-common-dir>/guild/engine or the person's --out
    tag = ("sprint-%s" % a.sprint) if a.sprint else "issues"
    J.atomic_write(os.path.join(out_dir, "%s.csv" % tag), render_csv(rows))
    J.atomic_write(os.path.join(out_dir, "%s.md" % tag), render_md(rows))
    emit.engine({"rows": len(rows), "csv": os.path.join(out_dir, "%s.csv" % tag), "first_sprint": first,
                 "predict_first": {"judgments": len(pf_rows), "imported": pf["imported"], "watch": pf["watch"],
                                   "conservative": pf["conservative"], "candidates": len(pf_cands)},
                 "watch": watch,
                 "graded": len(graded)}, out=d.out)
    return 0


def ac_text(comments):
    """The acceptance criteria of the Issue's trusted `analyze:output` (`AC #n: text` lines) — "" when none."""
    try:
        from guildcore.records import outputs as OUT
        from workflows.dev import analysis as AN
        so = OUT.find(comments, "analyze:output")
        return "\n".join("%s: %s" % (x["id"], x["text"]) for x in (AN.parse_output(so.body).ac if so else []))
    except Exception:                                            # noqa: BLE001 — no AC is not an error here
        return ""


def run_grader(d, common, repo, by_issue, later, first, valves, eng, ev_full, texts, pass_no, watch=(),
               ev_untrusted=None):
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
        todo = grader_select(by_issue, repo, first, rate, later, watch)
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
                       gv, pass_no, untrusted=(ev_untrusted or {}).get(issue) or "",
                       ac=(getattr(d, "grading_acs", None) or {}).get(issue) or "")
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
