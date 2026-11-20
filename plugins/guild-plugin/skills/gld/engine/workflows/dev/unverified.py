"""workflows.dev.unverified — the §10.2-6 unverified groups and their release (K6 item 4).

* The release ships `verification.json` (written by `replay/gate_report.py` from the held-out judgment replay): the
  §9.5 groups the replay VERIFIED (held-out n ≥ 20 at the gate's agreement, or a passing synthetic set). Every other
  group of `valves.GROUPS` is UNVERIFIED — "no synthetic = not passed" (R4J-m5).
* An unverified group runs the conservative path (`predict.conservative` → the gate's blind question, KICKOFF's blind
  confirmation, EX-ARB's dismiss → accept) until it is RELEASED: `release_after` (5) counted blind answers of that
  group judged by a person — the predict-first `ok`s and the person-confirmed candidates `dev grade` imports (§9.5
  "사람 판정") — with no confirmed wrong among them (§10.4 G1 group rule; R5J-M4: only predict-first answers count).
  A confirmed wrong keeps the group unverified (and the §9.5 count rule acts on it as on any group).
* K6 r1 M6 — every unverified group has a release path, or is not gated with its reason:
  - a group whose conservative path is a blind question (the gate's GATED groups, KICKOFF's confirmation) counts
    the person's verdicts on its predict-first answers;
  - `SHEET_RELEASED` (EX-ARB-dismiss): its conservative path asks nothing — a BLOCKER/MAJOR dismiss is coerced to
    accept and recorded `would-dismiss` — so the person's verdicts on those decisions on the grading sheet (the human
    import, `given_info` ok / wrong on the would-dismiss) count instead;
  - `EXEMPT` (ESCALATE, EX-ARB-accept): no less conservative path exists to gate — never listed as unverified.
  `test_k6_r1.ReleasePath` checks every group of `valves.GROUPS` is in exactly one of these.
  - K6 r2 M1: the gated groups with ONE non-conservative option (`conservative.INHERENT` — INTEGRATE, TEST, QA,
    AN-PO, VIS-ENV, EX-DWC, derived from the option tables) are SHEET_RELEASED too: their gate question exists only
    when the judge chose that option, so its answer is never counted; every such question becomes a grading-sheet
    row (`grade.inherent_row`, open until the person imports it) and the person's verdicts on those decisions count.
* K6 r1 m1 — no release while a wrong CANDIDATE of the group (a blind disagreement on the sheet, `dev grade`) is not
  yet judged by a person (`open` — merged by every `dev grade` across its scopes (K6 r2 m1), cleared only by the person's import of that row); a
  verdict imported after the release still counts (`n`, `wrong` — `dev health` shows a wrong after the release; the
  §9.5 count rule acts on it as on any group).
* K6 r3 m2 — an INHERENT group counts only its `inherent-gate` rows (one per question; the decision the answer
  applied and a block a rule changed are no release verdicts — `counts`), and one decision point once (`points`: its
  re-asks `:a<k>` are the same point — an `ok` is counted once, a `wrong` always).
* K6 r3 m3 — an open candidate whose decision is GONE from the Issue's log (read, not found: an import `verify_rows`
  rejects, or `dev grade` reconciling its scope) is dropped and recorded (`dropped`) — an unreadable log keeps it;
  `report` lists the open keys (`issue/D-id`) so `dev health` names what holds a release.
* State: `grade-state.json` → `unverified: {group: {"n", "wrong", "open", "points", "dropped", "released_at"}}` (local,
  like `watch`).
* The live Ports read the pending set once per run (`ports.fsm_factory` → `p.unverified`); test harnesses that
  build Ports themselves start with none.
"""

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
FILE = os.path.join(HERE, "verification.json")


def shipped(path=FILE):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (IOError, ValueError):
        return {"verified": [], "release_after": 5, "replay": "verification.json unreadable — all unverified"}


def canonical(group):
    return str(group or "").replace(":", "-")


# K6 r1 M6: groups whose conservative path asks no COUNTED blind question — released by the person's sheet verdicts.
# K6 r2 M1: + every gated group with one non-conservative option (`conservative.INHERENT`, derived from the option
# tables): its gate question exists only when the judge chose that option, so the answer is no blind judgment — the
# person's grading-sheet verdicts on those decisions (`grade.inherent_row`: every such question → a sheet row, open
# until imported) count, and only on that option (`SHEET_CHOICE`).
def _sheet_released():
    from workflows.dev import conservative as CONS
    out = {"EX-ARB-dismiss": "a BLOCKER/MAJOR dismiss is coerced to accept (`would-dismiss`, no question) — the "
                             "person's verdicts on those decisions on the grading sheet count"}
    for g, opt in sorted(CONS.INHERENT.items()):
        out[g] = ("the gate asks only when the judge chose `%s` (the one non-conservative option) — the question's "
                  "existence is the recommendation, so its answer is never counted; the person's grading-sheet "
                  "verdicts on those `%s` decisions count (`dev grade` puts every such question on the sheet)"
                  % (opt, opt))
    return out


def _sheet_choice():
    from workflows.dev import conservative as CONS
    return dict(CONS.INHERENT)


SHEET_RELEASED = _sheet_released()
SHEET_CHOICE = _sheet_choice()       # group → the only choice whose sheet verdict counts (EX-ARB-dismiss: any)
# K6 r1 M6: groups with no less conservative path to gate — never unverified
EXEMPT = {
    "ESCALATE": "no G-ESCALATE judge is wired (k6-notes user decision 1) — every unknown state already pauses for a "
                "person; nothing to verify",
    "EX-ARB-accept": "accept is EX-ARB's conservative side itself — nothing less conservative to hold back",
}


def unverified(path=FILE):
    """The §9.5 groups the shipped replay result did not verify (valve spelling: `EX-ARB-dismiss`), without the
    EXEMPT ones (K6 r1 M6)."""
    from guildcore import valves as VALVES
    ver = set(canonical(g) for g in (shipped(path).get("verified") or []))
    return [g for g in VALVES.GROUPS if g not in ver and g not in EXEMPT]


def pending(common, path=FILE):
    """The unverified groups not yet released — the conservative path's extra source. No common dir → all of them
    (unknown release state = the conservative side)."""
    groups = unverified(path)
    if not common:
        return frozenset(groups)
    from workflows.dev import grade as G
    st = (G.load_state(common).get("unverified") or {})
    return frozenset(g for g in groups if not (st.get(g) or {}).get("released_at"))


def _key(row):
    return "%s/%s" % (row.get("issue"), row.get("decision_id"))


def note_candidates(st, cands, path=FILE):
    """K6 r1 m1: `dev grade` lists the wrong candidates still waiting for a person (blind disagreements not yet
    confirmed, and — K6 r2 M1 — the inherent-gate sheet rows). K6 r2 m1: MERGED into each unverified group's `open`
    set, never replaced — a `dev grade` reads only its scope (`--sprint T` / `--issues N,M`), and an older scope's
    unjudged candidate must keep holding the release; only the person's import of that row removes it (`count`)."""
    groups = unverified(path)
    by = {}
    for c in cands or ():
        g = canonical(c.get("group"))
        if g in groups:
            by.setdefault(g, set()).add(_key(c))
    for g in groups:
        u = st.setdefault("unverified", {}).get(g)
        if u is None and g not in by:
            continue
        u = st["unverified"].setdefault(g, {"n": 0, "wrong": 0})
        u["open"] = sorted(set(u.get("open") or ()) | by.get(g, set()))


INHERENT_MODE = "inherent-gate"         # the sheet row of an INHERENT gate question (`grade.inherent_row`)


def point_of(refs):
    """K6 r3 m2: the decision point of a conservative-gate question's `refs` — its re-asks (`:a<k>`) are the same point."""
    import re
    return re.sub(r"(?::a[0-9]+)+$", "", str(refs or ""))


def drop_gone(st, gone, now):
    """K6 r3 m3: open candidates whose decision is GONE from the Issue's log (read, not found — `grade.verify_rows`) are
    reconciled away: nothing is left for a person to judge, and keeping them held the release forever. Recorded per
    group (`dropped`: key, why, when) and returned [{group, key}]."""
    keys = set("%s/%s" % (x.get("issue"), x.get("decision_id")) for x in gone or ())
    out = []
    for g, u in sorted((st.get("unverified") or {}).items()):
        hit = [k for k in (u.get("open") or ()) if k in keys]
        if not hit:
            continue
        u["open"] = [k for k in u["open"] if k not in hit]
        u.setdefault("dropped", []).extend({"key": k, "why": "gone from the Issue's decision log", "at": now}
                                           for k in hit)
        out += [{"group": g, "key": k} for k in hit]
    return out


def reconcile(st, issue, log_ids, now):
    """K6 r3 m3: `dev grade` — the open candidates of `issue` (its log READ: `log_ids`) whose D-id the log no longer
    has are dropped as `drop_gone` does."""
    gone = []
    for _g, u in sorted((st.get("unverified") or {}).items()):
        for k in u.get("open") or ():
            i, _s, did = k.partition("/")
            if str(i) == str(issue) and did not in log_ids:
                gone.append({"issue": i, "decision_id": did})
    return drop_gone(st, gone, now)


def release_check(st, now, path=FILE):
    """The groups that reach their release now (after open candidates were reconciled)."""
    out = []
    for g in unverified(path):
        u = (st.get("unverified") or {}).get(g)
        if u is not None and _release(u, now, path):
            out.append(g)
    return out


def counts(row, source):
    """Does this human verdict count toward the release of its group? — a predict-first answer's verdict, or (K6 r1
    M6) for a SHEET_RELEASED group the person's own sheet verdict (`source` = the import version `human`; K6 r2 M1:
    for an inherent gate group on its non-conservative choice only — never a predict-first `ok`)."""
    g = canonical(row.get("group"))
    if (row.get("mode") or "") == "predict-first":
        return g not in SHEET_CHOICE          # K6 r2 M1: an inherent gate group's blind answer is never counted
    if g in SHEET_RELEASED:
        # K6 r2 M1: a sheet-released group counts the person's sheet verdicts — for an inherent gate group only on its
        # non-conservative pick (a verdict on a conservative `block` / `gap` releases nothing)
        need = SHEET_CHOICE.get(g)
        if need is not None:
            # K6 r3 m2: only the inherent-gate row (one per question; the decision the answer applied, or a block a
            # rule changed, is no release verdict) on the non-conservative pick
            return source == "human" and (row.get("mode") or "") == INHERENT_MODE and \
                (row.get("choice") or "").strip() == need
        return source == "human"
    return False


def count(st, row, now, path=FILE, source=None):
    """One human judgment (a grades.jsonl row being imported) → the release state. Returns the group released by
    this row, or None. Counted: `counts(row, source)` with given_info ok / wrong; any import of a row clears it
    from the group's `open` candidates (m1). After the release the verdicts are still counted (shown), never undo it."""
    g = canonical(row.get("group"))
    gi = (row.get("given_info") or "").strip().lower()
    if g not in unverified(path):
        return None
    u = st.setdefault("unverified", {}).setdefault(g, {"n": 0, "wrong": 0})
    if u.get("open") and _key(row) in u["open"]:
        u["open"] = [k for k in u["open"] if k != _key(row)]
    if gi not in ("ok", "wrong") or not counts(row, source):
        return g if gi in ("ok", "wrong", "unsure") and _release(u, now, path) else None
    pk = row.get("point_key")
    if pk and gi == "ok" and pk in (u.get("points") or ()):
        return g if _release(u, now, path) else None      # K6 r3 m2: this decision point already counted
    if pk:
        u["points"] = sorted(set(u.get("points") or ()) | {pk})
    u["n"] = int(u.get("n") or 0) + 1
    if gi == "wrong":
        u["wrong"] = int(u.get("wrong") or 0) + 1
        if u.get("released_at"):
            u["wrong_after_release"] = int(u.get("wrong_after_release") or 0) + 1
    return g if _release(u, now, path) else None


def _release(u, now, path=FILE):
    if u.get("released_at"):
        return None
    if int(u.get("n") or 0) >= int(shipped(path).get("release_after") or 5) and not u.get("wrong") \
            and not u.get("open"):
        u["released_at"] = now
        return True
    return None


def report(common, path=FILE):
    """`dev health` / `status`: [{group, n, wrong, released_at}] for every unverified group."""
    from workflows.dev import grade as G
    st = (G.load_state(common).get("unverified") or {}) if common else {}
    out = []
    for g in unverified(path):
        u = st.get(g) or {}
        out.append({"group": g, "counted": int(u.get("n") or 0), "wrong": int(u.get("wrong") or 0),
                    "open_candidates": len(u.get("open") or ()), "released_at": u.get("released_at"),
                    # K6 r3 m3: WHICH Issue / D-id holds the release (and what was reconciled away)
                    "open": sorted(u.get("open") or ()),
                    "dropped": [d.get("key") for d in (u.get("dropped") or ())],
                    "wrong_after_release": int(u.get("wrong_after_release") or 0),
                    "release_by": "sheet verdicts" if g in SHEET_RELEASED else "blind answers"})
    return out
