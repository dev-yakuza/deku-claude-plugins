"""The router (`state.py next`; m0b1-plan §5). Pure: state + current values -> decision.

current = {
  "s2v_version", "stale_build", "hash_version", "brief_core", "content", "source_hash",
  "voice", "audio", "engine": {…}, "presentation": {o: h|None}, "reasons": {…},
  "render": {o: h|None}, "copy": {p: h|None},
  "source_live_hash", "source_text" (the frozen copy's text, for excerpts) }
"""

from . import schema
from ..text.normalize import Text, normalize  # noqa: F401 — the one excerpt normalization (m1-plan §7.1)
from .tuples import OWNER, changed, tuple_for  # noqa: F401

IDX = {s: i for i, s in enumerate(schema.STAGES)}
OWN_TABLE = {
    "brief_core": "script", "content": "verify",
    "voice": "tts", "engine.tts": "tts", "engine.templates": "tts", "engine.defaults_voice": None,
    "audio": "2",
    "presentation": "board",
    "engine.composer": "visual-check", "engine.renderer": "visual-check",
    "engine.defaults_presentation": "visual-check", "engine.ffmpeg": "visual-check",
    "render": "4a", "renders": "copy", "copy": "4b", "credits": "copy",
}


class Decision(object):
    def __init__(self, lang):
        self.lang = lang
        self.redo = None  # {"stage", "output"?, "platform"?, "mode"?, "why": [...]}
        self.stop = None  # {"stop": ..., ...}
        self.held = None
        self.done = False
        self.enter = None  # None | "allowed" | "refused" | "null-hash"
        self.null_reasons = []

    def as_dict(self):
        d = {"lang": self.lang, "redo": self.redo}
        if self.stop:
            d["stop"] = self.stop
        if self.held:
            d["held"] = self.held
        if self.done:
            d["done"] = True
        if self.enter:
            d["enter"] = self.enter
        if self.null_reasons:
            d["reasons"] = self.null_reasons
        return d


def _key(c, state, lang):
    outs = schema.current_outputs(state, lang)
    plats = schema.current_platforms(state, lang)
    side = 0
    if c.get("output") in outs:
        side = outs.index(c["output"])
    elif c.get("platform") in plats:
        side = plats.index(c["platform"])
    return (IDX[c["stage"]], side)


def _source_diff(state, lang, rec1, cur):
    """`source_hash` differs from ①'s (00-plan §3.2, m0b1-plan §5)."""
    if state["source"].get("frozen_hash") != cur["source_live_hash"]:
        return {"stage": "source", "why": ["the source changed; its copy is not refreshed yet"]}
    sd = state["langs"][lang]["approved"].get("source-diff")
    if sd and sd.get("rejected") and sd.get("tuple", {}).get("source_hash") == cur["source_hash"]:
        return {"stage": "verify", "why": ["the source diff was rejected"]}
    text = Text(cur.get("source_text") or "")
    excerpts = rec1.get("excerpts") or []
    if all(text.contains(e) for e in excerpts) and rec1["tuple"].get("content") == cur["content"]:
        return {"held": "source-diff"}
    return {"stage": "script", "why": ["an approved excerpt changed or disappeared in the source"]}


def _compare(state, lang, gate, rec, cur, output=None, platform=None):
    """Rule (a): candidates from a recorded gate's tuple."""
    plats = state["brief"]["platforms"]
    now_t = tuple_for(gate, cur, output=output, platform=platform,
                      platform_outputs=[o for o in plats.get(platform, []) if o in schema.current_outputs(state, lang)])
    diff = changed(rec["tuple"], now_t)
    out = []
    for field in diff:
        owner = OWNER.get(field)
        where = {}
        if output:
            where["output"] = output
        if platform:
            where["platform"] = platform
        if field == "source_hash" and gate == "1":
            r = _source_diff(state, lang, rec, cur)
            if "held" in r:
                out.append({"held": "source-diff"})
            else:
                out.append(dict(r))
            continue
        if field in OWN_TABLE and OWN_TABLE[field] is None:
            continue  # engine.defaults_voice: the voice hash uses the applied values
        if owner == gate:
            stage = OWN_TABLE[field]
            c = dict(where, stage=stage, why=["%s changed (%s)" % (field, gate)])
            if field == "presentation":
                c["mode"] = "exit-condition"
            if field == "engine.ffmpeg":
                c["why"] = ["ffmpeg changed: check the pictures again"]
            out.append(c)
        else:
            c = dict(where, stage=schema.DOWNSTREAM_START[gate], why=["%s changed upstream of %s" % (field, gate)])
            if c["stage"] == "board":
                c["mode"] = "exit-condition"
            out.append(c)
    return out


def _scope(state, lang, enter, output, platform):
    """[(gate, output, platform)] to look at: the gates before `enter` (all for no `enter`)."""
    outs = schema.current_outputs(state, lang)
    plats = schema.current_platforms(state, lang)
    full = enter in (None, "commit")
    items = []
    stop_at = IDX[enter] if enter and not full else len(schema.STAGES)
    for g in ("1", "2"):
        if IDX[g] < stop_at:
            items.append((g, None, None))
    if enter in schema.OUTPUT_STAGES:
        o_list = [output]
    elif enter in schema.PLATFORM_STAGES or full:
        o_list = outs
    else:
        o_list = []
    for g in ("3", "4a"):
        if IDX[g] < stop_at:
            items.extend((g, o, None) for o in o_list)
    if full:
        items.extend(("4b", None, p) for p in plats)
    return items


def precheck(state, lang):
    """What needs no current values: a finished language, a held state (m0b1-plan §5 steps 1–2).
    The CLI calls this before collecting (no inspect for a held video)."""
    d = Decision(lang)
    L = state["langs"].get(lang)
    if L is None:
        raise schema.SchemaError("no language %s in the state" % lang, 2)
    if L["status"] in ("done", "aborted"):
        d.done = True
        return d
    held = L.get("held")
    if held and held.get("state") != "source-diff":
        d.held = held
        return d
    return None


def _records(L):
    for g, recs in L["approved"].items():
        if g == "source-diff":
            continue
        for rec in (recs.values() if g in ("3", "4a", "4b") else [recs]):
            if isinstance(rec, dict):
                yield rec


def _section_gate(enter):
    """The first gate at or after `enter` (its own section's gate); None for commit."""
    return schema.section_gate(enter)


def section_tuple(state, lang, cur, gate, output=None, platform=None):
    """The current tuple of `gate` for a scope — what a stage-done record is checked against."""
    outs = [o for o in state["brief"]["platforms"].get(platform, []) if o in schema.current_outputs(state, lang)]
    return tuple_for(gate, cur, output=output if gate in ("3", "4a") else None,
                     platform=platform if gate == "4b" else None, platform_outputs=outs)


def find_done(L, stage, output=None, platform=None):
    for r in L.get("done_stages", []):
        if r.get("stage") == stage and r.get("output") == output and r.get("platform") == platform:
            return r
    return None


def _advance(state, lang, cur, c):
    """A redo point moves forward through its section while each stage has a completion record
    whose tuple is the section's current tuple (`stage-done`); it stops at the first stage without
    one, or at the section's gate (which needs a person's approval)."""
    st = c["stage"]
    if IDX[st] < IDX["script"]:
        return c
    gate = schema.section_gate(st)
    if gate is None or st == gate:
        return c
    o, p = c.get("output"), c.get("platform")
    want = section_tuple(state, lang, cur, gate, o, p)
    L = state["langs"][lang]
    i = IDX[st]
    while schema.STAGES[i] != gate:
        rec = find_done(L, schema.STAGES[i], o if gate in ("3", "4a") else None, p if gate == "4b" else None)
        if not rec or rec.get("tuple") != schema.project(schema.STAGES[i], want):
            if i == IDX[st]:
                return c
            return {k: v for k, v in dict(c, stage=schema.STAGES[i]).items() if k != "mode"}
        i += 1
    out = {k: v for k, v in c.items() if k != "mode"}
    out.update(stage=gate, why=list(c.get("why", [])) + ["the section's stages are done; %s needs approval" % gate])
    return out


def decide_without_script(state, lang, enter=None):
    """No script yet (MJ-1): only the stages before it are judged; s2v inspect is not called."""
    first = precheck(state, lang)
    if first:
        return first
    d = Decision(lang)
    if not state["source"].get("frozen_hash"):
        d.redo = {"stage": "source", "why": ["no frozen copy of the source yet"]}
    elif not state["brief"].get("core"):
        d.redo = {"stage": "brief", "why": ["the brief is not recorded yet"]}
    else:
        d.redo = {"stage": "script", "why": ["no script yet"]}
    if enter:
        d.enter = "refused" if IDX[enter] > IDX[d.redo["stage"]] else "allowed"
    return d


def _record(L, gate, o, p):
    rec = L["approved"].get(gate)
    if gate in ("3", "4a"):
        return (rec or {}).get(o)
    if gate == "4b":
        return (rec or {}).get(p)
    return rec


def decide(state, lang, cur, enter=None, output=None, platform=None):
    first = precheck(state, lang)
    if first:
        return first
    d = Decision(lang)
    L = state["langs"][lang]
    if cur["s2v_version"] != state["s2v"].get("id") or cur.get("stale_build"):
        st = state["s2v"]
        d.stop = {"stop": "s2v-version", "was": st.get("id"), "now": cur["s2v_version"],
                  "stale_build": bool(cur.get("stale_build")),
                  "exact_revert_possible": bool(st.get("commit")) and not st.get("dirty")}
        return d
    for rec in _records(L):
        if rec.get("hash_version") != cur["hash_version"]:  # missing counts as stale
            d.stop = {"stop": "hash-version", "from": rec.get("hash_version"), "to": cur["hash_version"]}
            return d
    cands = []
    # rule (b) before the gates: the source copy and the brief must exist
    if not state["source"].get("frozen_hash") or cur.get("source_text") is None:
        cands.append({"stage": "source", "why": ["no frozen copy of the source yet"]})
    if not state["brief"].get("core"):
        cands.append({"stage": "brief", "why": ["the brief is not recorded yet"]})
    for gate, o, p in _scope(state, lang, enter, output, platform):
        rec = _record(L, gate, o, p)
        where = {}
        if o:
            where["output"] = o
        if p:
            where["platform"] = p
        if not rec:
            cands.append(dict(where, stage=schema.PRODUCES[gate], why=["%s not approved yet" % gate]))
            continue
        for c in _compare(state, lang, gate, rec, cur, output=o, platform=p):
            if "held" in c:
                d.held = {"state": "source-diff"}
            else:
                cands.append(c)
    if enter:
        # rule (a) only for the entered stage's own section gate (MAJOR-1): a recorded gate whose
        # tuple changed sends the work back even when that gate is not before the stage
        g = _section_gate(enter)
        if g:
            o = output if g in ("3", "4a") else None
            p = platform if g == "4b" else None
            rec = _record(L, g, o, p)
            if rec:
                for c in _compare(state, lang, g, rec, cur, output=o, platform=p):
                    if "held" in c:
                        d.held = {"state": "source-diff"}
                    else:
                        cands.append(c)
            elif IDX[enter] > IDX[schema.PRODUCES[g]]:
                # no record yet: the section's earlier stages must be done (completion records)
                where = {k: v for k, v in (("output", o), ("platform", p)) if v}
                cands.append(dict(where, stage=schema.PRODUCES[g], why=["%s not approved yet" % g]))
    if d.held:
        # a source diff is a person's decision; work found at or before ① still comes first
        if not cands or IDX[min(cands, key=lambda c: _key(c, state, lang))["stage"]] > IDX["1"]:
            return d
        d.held = None
    cands = [_advance(state, lang, cur, c) for c in cands]
    # an output the script does not have yet: back to script whatever the completion records say
    for o in cur.get("outputs_missing", []):
        cands.append({"stage": "script", "output": o, "why": ["output %s is not in the script" % o]})
    if cands:
        d.redo = min(cands, key=lambda c: _key(c, state, lang))
    if enter:
        if d.redo and IDX[enter] > IDX[d.redo["stage"]]:
            d.enter = "refused"
        else:
            nulls = _nulls(enter, cur, output)
            if nulls:
                d.enter, d.null_reasons = "null-hash", nulls
            else:
                d.enter = "allowed"
    return d


def _nulls(enter, cur, output):
    """Hashes the entered stage's own gate needs that s2v could not compute."""
    need = []
    i = IDX[enter]
    if i >= IDX["tts"]:
        need.append("voice")
    if i >= IDX["audition"]:
        need.append("audio")
    if i >= IDX["visual-check"] and output:
        need.append("presentation")
    out = []
    for k in need:
        v = cur["presentation"].get(output) if k == "presentation" else cur[k]
        if v is None:
            key = "presentation.%s" % output if k == "presentation" else k
            out.append({"hash": key, "reasons": (cur.get("reasons") or {}).get(key, [])})
    return out
