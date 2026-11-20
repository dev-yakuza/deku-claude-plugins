"""workflows.dev.unverified — the §10.2-6 unverified groups and their release (K6 item 4).

* The release ships `verification.json` (written by `replay/gate_report.py` from the held-out judgment replay): the
  §9.5 groups the replay VERIFIED (held-out n ≥ 20 at the gate's agreement, or a passing synthetic set — the criteria
  in code: `replay/gate_report.decide`, K6 r7 m4; run it on the paid replay's graded rows before a release). Every other
  group of `valves.GROUPS` is UNVERIFIED — "no synthetic = not passed" (R4J-m5).
* An unverified group runs the conservative path (`predict.conservative` → the gate's blind question — STAKES' asked
  openly —, KICKOFF's open confirmation, EX-ARB's dismiss → accept) until it is RELEASED: `release_after` (5) counted blind answers of that
  group judged by a person — the predict-first `ok`s and the person-confirmed candidates `dev grade` imports (§9.5
  "사람 판정") — with no confirmed wrong among them (§10.4 G1 group rule; R5J-M4: only predict-first answers count).
  A confirmed wrong keeps the group unverified (and the §9.5 count rule acts on it as on any group).
* K6 r1 M6 — every unverified group has a release path, or is not gated with its reason:
  - a group whose conservative path is a blind question (the gate's GATED groups but STAKES) counts the person's
    verdicts on its predict-first answers;
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
* K6 r4 (user decision 2026-11-20, scope reduction) — KICKOFF and STAKES (`OPEN_ASKED`, = `predict.OPEN_GROUPS`)
  leave predict-first blind counting: their questions are asked openly and never counted; they are SHEET_RELEASED
  like the INHERENT groups — every engine-raised KICKOFF reading question / STAKES gate question is a sheet row
  (`grade.inherent_row`, open until imported) and the person's verdicts on those rows (any engine pick) count.
* K6 r3 m2 — an INHERENT group counts only its `inherent-gate` rows (one per question; the decision the answer
  applied and a block a rule changed are no release verdicts — `counts`), and one decision point once (`points`: its
  re-asks `:a<k>` are the same point — an `ok` is counted once, a `wrong` always).
* K6 r3 m3 — an open candidate whose decision is GONE from the Issue's log (read, not found: an import `verify_rows`
  rejects, or `dev grade` reconciling its scope) is dropped and recorded (`dropped`) — an unreadable log keeps it;
  `report` lists the open keys (`issue/D-id`) so `dev health` names what holds a release.
* K6 r5 m7 — an open candidate whose Issue log shows NO engine block (r4 m6: never reconciled away) is counted
  `unread` (consecutive times; a read log resets it) and `report` shows it with the way out: the person's
  `dev grade --drop-candidate <issue/D-id> --reason <why>` (`drop_by_human` — `dropped` with `by: human` and the reason).
* K6 r6 m1 — that way out is for an UNREAD candidate only (`unread` ≥ 1): a candidate whose log reads fine is a
  decision a person can still judge on the sheet; dropping it anyway needs `--force` (recorded `forced: true`). A
  release reached while human drops stand records them (`after_human_drop`); a human-dropped candidate that a later
  `dev grade` lists again is OPEN again (`reopened`), and when the group's release came after that drop the release is
  REVOKED (`release_revoked` — the group runs the conservative path again until the candidate is judged).
* K6 r7 m2 — "a later `dev grade`" is ANY `dev grade` (any `--sprint` / `--issues` scope): it also reads the log of
  every Issue holding a standing human drop (`human_dropped`) and lists those dropped candidates again when the log
  still shows them (only those — the Issue's other decisions stay out of a scope that did not name it).
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


def _open_asked():
    from workflows.dev import predict as PF
    return dict((canonical(g), why) for g, why in PF.OPEN_GROUPS.items())


OPEN_ASKED = _open_asked()          # K6 r4: groups asked openly — released by their gate rows' sheet verdicts
SHEET_RELEASED = dict(_sheet_released(), **OPEN_ASKED)
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


def note_candidates(st, cands, path=FILE, now=None):
    """K6 r1 m1: `dev grade` lists the wrong candidates still waiting for a person (blind disagreements not yet
    confirmed, and — K6 r2 M1 — the inherent-gate sheet rows). K6 r2 m1: MERGED into each unverified group's `open`
    set, never replaced — a `dev grade` reads only its scope (`--sprint T` / `--issues N,M`), and an older scope's
    unjudged candidate must keep holding the release; only the person's import of that row removes it (`count`).
    K6 r6 m1: a candidate the person dropped (`by: human`) that is listed again is open again (`reopened`); a release
    reached after that drop (`after_human_drop`) is revoked (`release_revoked`). Returns the revoked groups."""
    groups = unverified(path)
    by = {}
    for c in cands or ():
        g = canonical(c.get("group"))
        if g in groups:
            by.setdefault(g, set()).add(_key(c))
    revoked = []
    for g in groups:
        u = st.setdefault("unverified", {}).get(g)
        if u is None and g not in by:
            continue
        u = st["unverified"].setdefault(g, {"n": 0, "wrong": 0})
        u["open"] = sorted(set(u.get("open") or ()) | by.get(g, set()))
        back = sorted(set(d.get("key") for d in (u.get("dropped") or ()) if d.get("by") == "human")
                      & by.get(g, set()))
        if not back:
            continue
        was = [d for d in u.get("dropped") or () if d.get("by") == "human" and d.get("key") in back]
        u.setdefault("reopened", []).extend({"key": d.get("key"), "at": now, "drop": d} for d in was)
        u["dropped"] = [d for d in u.get("dropped") or () if d not in was]
        hit = sorted(set(back) & set(u.get("after_human_drop") or ()))
        if hit and u.get("released_at"):
            u.setdefault("release_revoked", []).append(
                {"released_at": u.pop("released_at"), "at": now, "keys": hit,
                 "why": "a candidate the person dropped is listed again — it holds the release until judged"})
            u.pop("after_human_drop", None)
            revoked.append(g)
    return revoked


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


def note_unread(st, keys):
    """K6 r5 m7: open candidates whose Issue log showed NO engine block this time (`dev grade` of its scope, an import
    `verify_rows` rejected so) — never reconciled away silently (r4 m6), but counted (`unread`: key → consecutive
    times) so `dev health` names them and a person can decide (`dev grade --drop-candidate`). Returns the keys noted."""
    keys = set(keys or ())
    out = []
    for _g, u in sorted((st.get("unverified") or {}).items()):
        for k in u.get("open") or ():
            if k in keys:
                un = u.setdefault("unread", {})
                un[k] = int(un.get(k) or 0) + 1
                out.append(k)
    return out


def open_keys_of(st, issue):
    return sorted(set(k for u in (st.get("unverified") or {}).values() for k in u.get("open") or ()
                      if k.partition("/")[0] == str(issue)))


def human_dropped(st):
    """K6 r7 m2: {issue: {keys}} of every candidate a person dropped (`by: human`, forced or not) that still stands —
    `dev grade` re-reads those Issues' logs whatever its scope, so a drop is re-checked by the next `dev grade`, not
    only by one whose scope happens to hold that Issue."""
    out = {}
    for _g, u in sorted((st.get("unverified") or {}).items()):
        for d in u.get("dropped") or ():
            if d.get("by") == "human" and d.get("key"):
                i = str(d["key"]).partition("/")[0]
                if i.isdigit():
                    out.setdefault(int(i), set()).add(d["key"])
    return out


def drop_refused(st, key, force=False):
    """K6 r6 m1: why the person's drop of `key` is refused — "not-open" (open nowhere), "readable" (open, but its log
    was read: never `unread` — a person can judge it on the sheet; `force` overrides), or None."""
    groups = [u for u in (st.get("unverified") or {}).values() if key in (u.get("open") or ())]
    if not groups:
        return "not-open"
    if not force and not any(int((u.get("unread") or {}).get(key) or 0) >= 1 for u in groups):
        return "readable"
    return None


def drop_by_human(st, key, reason, now, force=False):
    """K6 r5 m7: the person's way out for an open candidate nothing can judge any more (its Issue's decision log is
    gone — deleted comments, a changed association): `dev grade --drop-candidate <issue/D-id> --reason <why>`. Removed
    from every group's `open` and recorded in `dropped` with `by: human` and the reason. Returns [{group, key}] (empty
    when the key is open nowhere). A reason is required (the caller refuses an empty one).
    K6 r6 m1: only an UNREAD candidate (`drop_refused`); `force` drops a readable one (recorded `forced: true`)."""
    if drop_refused(st, key, force):
        return []
    out = []
    for g, u in sorted((st.get("unverified") or {}).items()):
        if key not in (u.get("open") or ()):
            continue
        n_unread = int((u.get("unread") or {}).get(key) or 0)
        u["open"] = [k for k in u["open"] if k != key]
        (u.get("unread") or {}).pop(key, None)
        d = {"key": key, "why": str(reason)[:300], "by": "human", "at": now, "unread": n_unread}
        if force and n_unread < 1:
            d["forced"] = True
        u.setdefault("dropped", []).append(d)
        out.append({"group": g, "key": key})
    return out


def reconcile(st, issue, log_ids, now):
    """K6 r3 m3: `dev grade` — the open candidates of `issue` (its log READ: `log_ids`) whose D-id the log no longer
    has are dropped as `drop_gone` does. K6 r5 m7: a read log resets their `unread` count."""
    if not log_ids:
        return []                    # K6 r4 m6: a log with no engine block was not read as trusted — never "gone"
    for _g, u in sorted((st.get("unverified") or {}).items()):
        for k in list((u.get("unread") or {}).keys()):
            if k.partition("/")[0] == str(issue):
                u["unread"].pop(k)
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
        # K6 r2 M1 / K6 r4: an inherent gate group's — or an open group's — answer is never a counted blind one
        return g not in SHEET_CHOICE and g not in OPEN_ASKED
    if g in OPEN_ASKED:
        # K6 r4: only the gate-question rows (one per question, any engine pick) — like the INHERENT groups (r3 m2)
        return source == "human" and (row.get("mode") or "") == INHERENT_MODE
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
        hd = sorted(set(d.get("key") for d in (u.get("dropped") or ()) if d.get("by") == "human"))
        if hd:
            u["after_human_drop"] = hd          # K6 r6 m1: released while these human drops stand
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
                    # K6 r5 m7: the person's drops (with the reason) and the candidates whose log shows no engine
                    # block (n times in a row) — the way out is the person's
                    "dropped_by_human": [{"key": d.get("key"), "reason": d.get("why"), "at": d.get("at"),
                                          "forced": bool(d.get("forced"))}
                                         for d in (u.get("dropped") or ()) if d.get("by") == "human"],
                    # K6 r6 m1: a release reached while human drops stood, and a release a re-listed drop revoked
                    "after_human_drop": list(u.get("after_human_drop") or ()) if u.get("released_at") else [],
                    "release_revoked": list(u.get("release_revoked") or ()),
                    # K6 r7 m2: the human drops a later `dev grade` found listed again (re-opened)
                    "reopened": [r.get("key") for r in (u.get("reopened") or ())],
                    "unread": dict((k, n) for k, n in sorted((u.get("unread") or {}).items())
                                   if k in (u.get("open") or ())),
                    "way_out": ("an open candidate whose Issue log shows no engine block holds the release — if that "
                                "log is gone for good: dev grade --drop-candidate <issue/D-id> --reason <why>")
                    if any(k in (u.get("open") or ()) for k in (u.get("unread") or {})) else None,
                    "wrong_after_release": int(u.get("wrong_after_release") or 0),
                    "release_by": "sheet verdicts" if g in SHEET_RELEASED else "blind answers"})
    return out
