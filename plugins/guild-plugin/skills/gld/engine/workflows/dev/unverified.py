"""workflows.dev.unverified — the §10.2-6 unverified groups and their release (K6 item 4).

* The release ships `verification.json` (written by `replay/gate_report.py` from the held-out judgment replay): the
  §9.5 groups the replay VERIFIED (held-out n ≥ 20 at the gate's agreement, or a passing synthetic set). Every other
  group of `valves.GROUPS` is UNVERIFIED — "no synthetic = not passed" (R4J-m5).
* An unverified group runs the conservative path (`predict.conservative` → the gate's blind question, KICKOFF's blind
  confirmation, EX-ARB's dismiss → accept) until it is RELEASED: `release_after` (5) counted blind answers of that
  group judged by a person — the predict-first `ok`s and the person-confirmed candidates `dev grade` imports (§9.5
  "사람 판정") — with no confirmed wrong among them (§10.4 G1 group rule; R5J-M4: only predict-first answers count).
  A confirmed wrong keeps the group unverified (and the §9.5 count rule acts on it as on any group).
* State: `grade-state.json` → `unverified: {group: {"n", "wrong", "released_at"}}` (local, like `watch`).
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


def unverified(path=FILE):
    """The §9.5 groups the shipped replay result did not verify (valve spelling: `EX-ARB-dismiss`)."""
    from guildcore import valves as VALVES
    ver = set(canonical(g) for g in (shipped(path).get("verified") or []))
    return [g for g in VALVES.GROUPS if g not in ver]


def pending(common, path=FILE):
    """The unverified groups not yet released — the conservative path's extra source. No common dir → all of them
    (unknown release state = the conservative side)."""
    groups = unverified(path)
    if not common:
        return frozenset(groups)
    from workflows.dev import grade as G
    st = (G.load_state(common).get("unverified") or {})
    return frozenset(g for g in groups if not (st.get(g) or {}).get("released_at"))


def count(st, row, now, path=FILE):
    """One human judgment (a grades.jsonl row being imported) → the release state. Counted: the person's verdict
    (ok / wrong) on a predict-first answer (`mode: predict-first`) of an unverified group. Returns the group released
    by this row, or None."""
    g = canonical(row.get("group"))
    gi = (row.get("given_info") or "").strip().lower()
    if g not in unverified(path) or gi not in ("ok", "wrong") or (row.get("mode") or "") != "predict-first":
        return None
    u = st.setdefault("unverified", {}).setdefault(g, {"n": 0, "wrong": 0})
    if u.get("released_at"):
        return None
    u["n"] = int(u.get("n") or 0) + 1
    if gi == "wrong":
        u["wrong"] = int(u.get("wrong") or 0) + 1
    if u["n"] >= int(shipped(path).get("release_after") or 5) and not u["wrong"]:
        u["released_at"] = now
        return g
    return None


def report(common, path=FILE):
    """`dev health` / `status`: [{group, n, wrong, released_at}] for every unverified group."""
    from workflows.dev import grade as G
    st = (G.load_state(common).get("unverified") or {}) if common else {}
    out = []
    for g in unverified(path):
        u = st.get(g) or {}
        out.append({"group": g, "counted": int(u.get("n") or 0), "wrong": int(u.get("wrong") or 0),
                    "released_at": u.get("released_at")})
    return out
