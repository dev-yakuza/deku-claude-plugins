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
* K6 r1 m1 — no release while a wrong CANDIDATE of the group (a blind disagreement on the sheet, `dev grade`) is not
  yet judged by a person (`open` — refreshed by every `dev grade`, cleared by the person's import of that row); a
  verdict imported after the release still counts (`n`, `wrong` — `dev health` shows a wrong after the release; the
  §9.5 count rule acts on it as on any group).
* State: `grade-state.json` → `unverified: {group: {"n", "wrong", "open", "released_at"}}` (local, like `watch`).
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


# K6 r1 M6: groups whose conservative path asks no blind question — released by the person's sheet verdicts
SHEET_RELEASED = {
    "EX-ARB-dismiss": "a BLOCKER/MAJOR dismiss is coerced to accept (`would-dismiss`, no question) — the person's "
                      "verdicts on those decisions on the grading sheet count",
}
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
    confirmed) — each unverified group's `open` set is replaced by this run's list."""
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
        u["open"] = sorted(by.get(g, ()))


def counts(row, source):
    """Does this human verdict count toward the release of its group? — a predict-first answer's verdict, or (K6 r1
    M6) for a SHEET_RELEASED group the person's own sheet verdict (`source` = the import version `human`)."""
    g = canonical(row.get("group"))
    if (row.get("mode") or "") == "predict-first":
        return True
    return g in SHEET_RELEASED and source == "human"


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
                    "wrong_after_release": int(u.get("wrong_after_release") or 0),
                    "release_by": "sheet verdicts" if g in SHEET_RELEASED else "blind answers"})
    return out
