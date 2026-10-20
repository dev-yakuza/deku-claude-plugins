"""Fixtures for the M0b-1 state tests. Expected tuples are written out here from 00-plan §3.2's
table, independently of stdo/state/tuples.py (m0b1-plan §7)."""

import copy

import helpers  # noqa: F401  (import path)
from stdo.state import schema

ENGINE = {"tts": "e-tts", "templates": "e-tpl", "defaults_voice": "e-dv", "composer": "e-comp",
          "renderer": "e-rend", "ffmpeg": "e-ff", "defaults_presentation": "e-dp"}


def state(outputs=("youtube",), platforms=None, langs=("ko",)):
    s = schema.create_state("v1", "public", "youtube", "public", langs[0],
                            {"id": "0.12.1+abc", "version": "0.12.1", "commit": "c0ffee", "dirty": False},
                            {"kind": "repo-md", "path": "docs/a.md", "images": [], "frozen_hash": "src1"})
    for l in langs[1:]:
        s["langs"][l] = schema.new_lang()
    s["brief"] = {"core": "brief1", "outputs": list(outputs),
                  "platforms": dict(platforms or {"youtube": [outputs[0]]})}
    return s


def current(outputs=("youtube",), platforms=("youtube",), **over):
    c = {"s2v_version": "0.12.1+abc", "stale_build": False, "hash_version": 1,
         "brief_core": "brief1", "content": "c1", "source_hash": "src1", "source_live_hash": "src1",
         "source_text": "The cat sat on the mat.\nIt was warm.", "voice": "v1", "audio": "a1",
         "engine": dict(ENGINE), "presentation": {o: "p-" + o for o in outputs}, "reasons": {},
         "render": {o: "r-" + o for o in outputs}, "copy": {p: "cp-" + p for p in platforms}}
    for k, v in over.items():
        c[k] = v
    return c


def literal_tuple(gate, c, o=None, p=None, p_outputs=()):
    """00-plan §3.2: ① brief_core·content·source_hash; ② brief_core·content·voice·audio·engine voice;
    ③ ② + presentation + engine screen; ④a ③ + render; ④b content·source_hash·renders·copy."""
    e = c["engine"]
    if gate == "1":
        return {"brief_core": c["brief_core"], "content": c["content"], "source_hash": c["source_hash"]}
    if gate == "4b":
        return {"content": c["content"], "source_hash": c["source_hash"],
                "renders": {x: c["render"].get(x) for x in p_outputs}, "copy": c["copy"].get(p)}
    t = {"brief_core": c["brief_core"], "content": c["content"], "voice": c["voice"], "audio": c["audio"],
         "engine.tts": e["tts"], "engine.templates": e["templates"], "engine.defaults_voice": e["defaults_voice"]}
    if gate == "2":
        return t
    t.update({"presentation": c["presentation"].get(o), "engine.composer": e["composer"],
              "engine.renderer": e["renderer"], "engine.ffmpeg": e["ffmpeg"],
              "engine.defaults_presentation": e["defaults_presentation"]})
    if gate == "3":
        return t
    t["render"] = c["render"].get(o)
    return t


def approve(s, gate, c, o=None, p=None, lang=None, excerpts=None, hash_version=1):
    lang = lang or s["source_lang"]
    rec = {"tuple": literal_tuple(gate, c, o, p, s["brief"]["platforms"].get(p, [])),
           "hash_version": hash_version, "s2v_id": s["s2v"]["id"], "approved_by": "human"}
    if excerpts is not None:
        rec["excerpts"] = excerpts
    A = s["langs"][lang]["approved"]
    if gate in ("3", "4a"):
        A.setdefault(gate, {})[o] = rec
    elif gate == "4b":
        A.setdefault(gate, {})[p] = rec
    else:
        A[gate] = rec
    return s


def approve_all(s, c, lang=None, upto="4b"):
    order = ["1", "2", "3", "4a", "4b"]
    for g in order[: order.index(upto) + 1]:
        if g in ("3", "4a"):
            for o in schema.current_outputs(s, lang or s["source_lang"]):
                approve(s, g, c, o=o, lang=lang)
        elif g == "4b":
            for p in schema.current_platforms(s, lang or s["source_lang"]):
                approve(s, g, c, p=p, lang=lang)
        else:
            approve(s, g, c, lang=lang, excerpts=["The cat sat on the mat."] if g == "1" else None)
    return s


# fields a stage's record leaves out (produced later in its section) — written out literally
LATER = {"cast": ("audio", "engine.tts", "engine.templates", "engine.defaults_voice"),
         "board": ("engine.composer", "engine.renderer", "engine.ffmpeg", "engine.defaults_presentation")}


def done(s, stage, c, o=None, p=None, lang=None):
    """A stage-done record with its section's literal tuple, minus what later stages produce."""
    from stdo.state.schema import section_gate
    lang = lang or s["source_lang"]
    gate = section_gate(stage)
    t = literal_tuple(gate, c, o if gate in ("3", "4a") else None, p if gate == "4b" else None,
                      s["brief"]["platforms"].get(p, []))
    t = {k: v for k, v in t.items() if k not in LATER.get(stage, ()) and k != "engine.defaults_voice"}
    s["langs"][lang]["done_stages"].append({"stage": stage, "output": o if gate in ("3", "4a") else None,
                                            "platform": p if gate == "4b" else None, "tuple": t})
    return s


def changed(c, **over):
    d = copy.deepcopy(c)
    for k, v in over.items():
        if k.startswith("engine_"):
            d["engine"][k[len("engine_"):]] = v
        else:
            d[k] = v
    return d
