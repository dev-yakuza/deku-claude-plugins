"""A video's approval records against its state (m0e-plan §6).

light_check (the hook; no s2v): state.json readable · no interrupted write · approvals.jsonl ends at
state.last_seq · every approval in the state has its `approve` event · every gate of every active
language approved for the current outputs/platforms · nothing held · no proxy approval.
full_check (`--stage` of the video kind, M1): the router with current hashes says nothing to redo."""

import os

from ..state import router, schema, store


class Problem(object):
    def __init__(self, code, message, path=None):
        self.code, self.message, self.path = code, message, path


def _ev_matches(rec, ev_rec):
    for k in ("approved_by", "answer", "at", "shown"):
        if (k in rec or k in ev_rec) and rec.get(k) != ev_rec.get(k):
            return False
    return True


def light_check(vdir, video):
    out = []
    try:
        state = store.read_state(vdir)
    except schema.SchemaError as e:
        return [Problem(1, "video %s: %s" % (video, e))]
    inc = store.incomplete(vdir, state)
    if inc:
        out.append(Problem(1, "video %s: approvals.jsonl has an interrupted write (seq %s) — run \"state.py next %s\" "
                              "and ask the user" % (video, ", ".join(str(s) for s in inc), video)))
    log = store.read_log(vdir)
    seqs = [e["seq"] for e in log if isinstance(e.get("seq"), int)]
    if (max(seqs) if seqs else 0) != state["last_seq"]:
        out.append(Problem(1, "video %s: approvals.jsonl ends at seq %s but state.json says %s"
                              % (video, max(seqs) if seqs else 0, state["last_seq"])))
    events = {}
    for e in log:
        if e.get("event") == "approve" and isinstance(e.get("record"), dict):
            events.setdefault((e.get("lang"), e.get("gate"), e.get("key")), []).append(e["record"])
    for lang, L in sorted(state["langs"].items()):
        if L.get("status") != "active":
            continue
        if L.get("held"):
            out.append(Problem(1, "video %s [%s]: held (%s) — a person decides first"
                                  % (video, lang, (L["held"] or {}).get("state"))))
        outs = schema.current_outputs(state, lang)
        plats = schema.current_platforms(state, lang)
        need = [("1", None), ("2", None)] + [(g, o) for g in ("3", "4a") for o in outs] + [("4b", p) for p in plats]
        for gate, key in need:
            recs = L["approved"].get(gate)
            rec = recs if gate in ("1", "2") else (recs or {}).get(key)
            where = gate if key is None else "%s(%s)" % (gate, key)
            if not isinstance(rec, dict):
                out.append(Problem(1, "video %s [%s]: gate %s is not approved — the video is not ready to commit"
                                      % (video, lang, where)))
                continue
            if not any(_ev_matches(rec, r) for r in events.get((lang, gate, key), [])):
                out.append(Problem(1, "video %s [%s]: the approval of gate %s has no matching approve event in "
                                      "approvals.jsonl (edited by hand?)" % (video, lang, where)))
            if rec.get("approved_by") == "proxy":
                out.append(Problem(4, "video %s [%s]: gate %s was approved by proxy — a person must approve it "
                                      "before a commit" % (video, lang, where)))
    for path, rec in sorted((state.get("credits") or {}).items()):  # J131: a picture's credit is a person's too
        if isinstance(rec, dict) and rec.get("approved_by") != "human":
            out.append(Problem(4, "video %s: the credit of %s was approved in the proxy mode — a person runs "
                                  "\"state.py credit\" for it again before a commit" % (video, path)))
    if state.get("location") == "local":
        out.append(Problem(1, "video %s is a local (machine-only) video — it is never committed" % video))
    return out


def full_check(state, lang, cur, video):
    d = router.decide(state, lang, cur)
    if d.stop:
        return [Problem(4, "video %s [%s]: stopped (%s) — a person decides first" % (video, lang, d.stop.get("stop")))]
    if d.held:
        return [Problem(1, "video %s [%s]: held (%s)" % (video, lang, d.held.get("state")))]
    if d.redo:
        return [Problem(1, "video %s [%s]: not ready to commit — redo %s (%s)"
                           % (video, lang, d.redo["stage"], "; ".join(d.redo.get("why", []))))]
    return []


def state_seq(vdir):
    try:
        return store.read_state(vdir)["last_seq"]
    except schema.SchemaError:
        return None


def video_dir(top, root, video):
    return os.path.join(top, root, "videos", video)
