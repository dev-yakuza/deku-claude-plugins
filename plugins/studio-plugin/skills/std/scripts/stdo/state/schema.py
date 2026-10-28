"""The video state file (`work/state.json`, schema 1; m0b1-plan §3)."""

import datetime

SCHEMA = 1
STAGES = ["source", "brief", "script", "verify", "1", "cast", "tts", "audition", "2", "board",
          "visual-check", "3", "render", "4a", "copy", "4b", "commit"]
OUTPUT_STAGES = ("board", "visual-check", "3", "render", "4a")
PLATFORM_STAGES = ("copy", "4b")
GATES = ("1", "2", "3", "4a", "4b")
# the stage that makes a gate's artifact: where work restarts when the gate has no record (rule b)
PRODUCES = {"1": "script", "2": "cast", "3": "board", "4a": "render", "4b": "copy"}
# the first stage of a gate's own segment, for changes of upstream fields in its tuple
DOWNSTREAM_START = {"2": "cast", "3": "board", "4a": "render", "4b": "copy"}  # ③: board exit-condition
LOOPS = ("verify", "1", "3", "4a", "copy")
LOOP_RESET = {"1": ("verify", "1"), "3": ("3",), "4a": ("4a",), "4b": ("copy",)}
HELD = ("render", "lock", "source-diff", "stagnation", "actor", "actor-building")
# the field of a ② approval record that holds the sha of `work/<l>/pronounce-approved.json` written with it (m1-plan
# §8, v5.1 T1; M1f writes it): only a file with that sha, of a current human ② record, counts anywhere
PRONOUNCE_SHA = "pronounce_approved_sha"
REQUIRED = ("schema", "video", "location", "kind", "scope", "source_lang", "s2v", "brief", "source", "langs")


class SchemaError(Exception):
    def __init__(self, msg, code=1):
        Exception.__init__(self, msg)
        self.code = code


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def stage_index(stage):
    return STAGES.index(stage)


def new_lang():
    return {"status": "active", "stage": "source", "held": None, "loops": {k: 0 for k in LOOPS},
            "approved": {}, "renders": {}, "copies": {}, "excluded": {"outputs": [], "platforms": []},
            "done_stages": [], "shown": {}, "shown_pending": {}}


# stages whose completion is recorded with `state.py stage-done` (gates are approved instead;
# source and brief have their own records — the frozen copy and the recorded brief)
DONE_STAGES = ("script", "verify", "cast", "tts", "audition", "board", "visual-check", "render", "copy")


# which stage produces each tuple field (m0b1-plan §5.1). A completion record of a stage leaves
# out the fields produced by LATER stages of its own section (they do not exist yet, or change
# later by design). Engine fields belong to the stage that consumes them: the TTS constants and
# templates to tts (they change the synthesized audio), the screen constants to visual-check (the
# stills are where they show; 00-plan §3.2's engine row sends their changes to ③).
FIELD_PRODUCER = {
    "source_hash": "source", "brief_core": "brief", "content": "script",
    "voice": "cast", "audio": "tts",
    "engine.tts": "tts", "engine.templates": "tts", "engine.defaults_voice": "tts",
    "presentation": "board",
    "engine.composer": "visual-check", "engine.renderer": "visual-check", "engine.ffmpeg": "visual-check",
    "engine.defaults_presentation": "visual-check",
    "render": "render", "renders": "render", "copy": "copy",
}


def project(stage, section_tuple):
    """The part of a section tuple a completion record of `stage` covers."""
    gate = section_gate(stage)
    i = STAGES.index(stage)
    g = STAGES.index(gate) if gate else len(STAGES)

    def later(field):
        prod = FIELD_PRODUCER.get(field)
        return prod is not None and i < STAGES.index(prod) < g
    # engine.defaults_voice changes nothing a stage made (the voice hash uses applied values) and
    # D29 catches it with the s2v version: completion records ignore it
    return {k: v for k, v in section_tuple.items() if not later(k) and k != "engine.defaults_voice"}


def section_gate(stage):
    """The first gate at or after `stage` (None after ④b)."""
    for g in GATES:
        if STAGES.index(g) >= STAGES.index(stage):
            return g
    return None


def create_state(video, location, kind, scope, source_lang, s2v, source):
    """The state a new video starts with (`begin` in M1 calls this; M0b-1 tests use it)."""
    return {"schema": SCHEMA, "video": video, "location": location, "kind": kind, "scope": scope,
            "source_lang": source_lang, "s2v": dict(s2v),
            "brief": {"core": None, "outputs": [], "platforms": {}},
            "source": dict(source, approved_hash=source.get("approved_hash")), "langs": {source_lang: new_lang()}, "last_seq": 0}


def validate(state):
    if not isinstance(state, dict):
        raise SchemaError("state.json is not an object")
    if state.get("schema") != SCHEMA:
        raise SchemaError("state.json schema %r is not %d: update Studio" % (state.get("schema"), SCHEMA), 2)
    missing = [k for k in REQUIRED if k not in state]
    if missing:
        raise SchemaError("state.json lacks %s" % ", ".join(missing))
    state.setdefault("last_seq", 0)
    for L in state.get("langs", {}).values():
        if isinstance(L, dict):
            L.setdefault("done_stages", [])
            L.setdefault("shown", {})
            L.setdefault("shown_pending", {})
    if isinstance(state.get("source"), dict):
        state["source"].setdefault("approved_hash", None)
    return state


def current_outputs(state, lang):
    ex = set(state["langs"][lang]["excluded"]["outputs"])
    return [o for o in state["brief"]["outputs"] if o not in ex]


def current_platforms(state, lang):
    ex = set(state["langs"][lang]["excluded"]["platforms"])
    return [p for p in state["brief"]["platforms"] if p not in ex]


# ---------- deterministic check results (m1-plan §4.1, D-M1-12) ----------
# One table for the check scripts (which write `work/<l>/checks/<file>[--<scope>].json`) and `stage-done` (which
# recomputes the input sha from the same inputs). `scope`: None, "output" or "platform". `s2v`: the s2v `id` is part
# of the input sha (a pass under another s2v is not reused). visual-check has no file of its own: ③'s shown record
# binds the stills' index.json and the whole ③ tuple already (v5 S4).
STAGE_CHECKS = {
    # fail_unread: whether s2v lint's `unread-word` fails the stage — information at script, a failure from cast on
    # (M1b re-review Z3 · J32; s2vlint.run(fail_unread=…) takes it from here)
    "script": {"file": "script", "script": "check_claims.py", "scope": None, "s2v": True, "fail_unread": False,
               "inputs": ("script", "claims_map", "format", "assets_json", "script_files")},
    "verify": {"file": "verify-claims", "script": "check_claims.py", "scope": None, "s2v": False,
               "inputs": ("verify_draft", "source_copy", "claims_map", "script")},
    "cast": {"file": "cast", "script": "check_assets.py", "scope": None, "s2v": True, "fail_unread": True,
             "inputs": ("script", "cast_roster")},
    "tts": {"file": "tts", "script": "check_tts.py", "scope": None, "s2v": True,
            "inputs": ("lock_manifest", "sentences", "format")},
    "audition": {"file": "audition", "script": "audition.py", "scope": None, "s2v": False,
                 "inputs": ("lock_manifest", "approved_2", "exemptions", "pronounce_changes", "audition_out")},
    "board": {"file": "board", "script": "check_assets.py", "scope": "output", "s2v": True, "fail_unread": True,
              "inputs": ("script", "assets_json", "credits", "script_files", "config_protected", "overlay_sha",
                         "credit_approvals")},
    "render": {"file": "render", "script": "run_s2v.py", "scope": "output", "s2v": True,
               "inputs": ("render_result",)},
    "copy": {"file": "copy", "script": "validate_copy.py", "scope": "platform", "s2v": False,
             "inputs": ("copy_text", "platform_rules", "chapters", "credits", "overlay_sha", "claims_map",
                        "source_copy")},
}
NO_CHECK_FILE = ("visual-check",)
