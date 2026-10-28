"""Fixtures for the M0b-1 state tests. Expected tuples are written out here from 00-plan §3.2's
table, independently of stdo/state/tuples.py (m0b1-plan §7)."""

import copy
import hashlib
import json
import os

import helpers  # noqa: F401  (import path)
from stdo.state import schema

# a video past the source stage: its checked assets.json (the bytes checkfix and brief_ready write) and their sha
ASSETS_BYTES = b'{"images": [], "schema": 1}\n'
ASSETS_SHA = hashlib.sha256(ASSETS_BYTES).hexdigest()
# the source analyst's claims for the brief tests (ids are the excerpts' hashes, 00-plan §3.2)
EXCERPTS = ("The cat sat on the mat.", "It was warm.")


def claim_id(excerpt):
    return "C-" + hashlib.sha256(excerpt.encode("utf-8")).hexdigest()[:8]


C1, C2 = claim_id(EXCERPTS[0]), claim_id(EXCERPTS[1])
FORMAT = """# Format (test)

<!-- studio:criteria -->
```json
{"length_seconds": {"min": %s, "max": %s}, "chars_per_sec": {"ko": 5.5, "ja": 7.0, "en": 14.0},
 "cer_max": {"ko": 0.15, "ja": 0.15, "en": 0.1}}
```
<!-- /studio:criteria -->
"""


def write_assets(vdir):
    os.makedirs(os.path.join(vdir, "work"), exist_ok=True)
    p = os.path.join(vdir, "work", "assets.json")
    if not os.path.exists(p):
        with open(p, "wb") as f:
            f.write(ASSETS_BYTES)


def write_format(repo, kind="youtube", length=(1, 600), commit=True):
    d = os.path.join(repo, ".claude", "studio", "formats")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "%s.md" % kind), "w", encoding="utf-8") as f:
        f.write(FORMAT % length)
    if commit:
        helpers.git(repo, "add", "-A", ".claude/studio/formats")
        helpers.git(repo, "commit", "-q", "--no-verify", "--allow-empty", "-m", "format")


def brief_ready(repo, vdir, source_path="docs/a.md", excerpts=EXCERPTS, length=(1, 600), source_md=None):
    """What record-brief reads: the format, the checked assets, the frozen copy and the analyst's claims."""
    write_format(repo, length=length)
    write_assets(vdir)
    d = os.path.join(vdir, "work", "source")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, os.path.basename(source_path)), "w", encoding="utf-8") as f:
        f.write("# A\n\n" + "\n".join(excerpts) + "\n")
    with open(os.path.join(vdir, "work", "source.md"), "w", encoding="utf-8") as f:
        f.write(source_md if source_md is not None else "# Source\n\n## Claims\n" + "".join(
            "- %s: claim %d\n  > %s\n" % (claim_id(e), n, e) for n, e in enumerate(excerpts, 1)))

ENGINE = {"tts": "e-tts", "templates": "e-tpl", "defaults_voice": "e-dv", "composer": "e-comp",
          "renderer": "e-rend", "ffmpeg": "e-ff", "defaults_presentation": "e-dp"}


def state(outputs=("youtube",), platforms=None, langs=("ko",)):
    s = schema.create_state("v1", "public", "youtube", "public", langs[0],
                            {"id": "0.12.1+abc", "version": "0.12.1", "commit": "c0ffee", "dirty": False},
                            {"kind": "repo-md", "path": "docs/a.md", "images": [], "frozen_hash": "src1",
                             "assets_sha": ASSETS_SHA})  # past the source stage: its images are checked (M1d Q3)
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
