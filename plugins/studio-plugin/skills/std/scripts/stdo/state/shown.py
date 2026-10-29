"""What was shown to the person (m0b2-plan §2): the gate's FULL tuple for a scope plus the shown
artifacts' hashes. Approving compares this with now, so a change upstream after showing (a ②
re-approval, a new render) needs showing again."""

import os

from . import schema
from .hashes import file_sha, hash_of
from .router import section_tuple

GATES = ("1", "2", "3", "4a", "4b", "source-diff")
ONE = "-"


def scopes(state, lang, gate):
    if gate in ("3", "4a"):
        return schema.current_outputs(state, lang)
    if gate == "4b":
        return schema.current_platforms(state, lang)
    return [ONE]


def frames_index(ctx, state, lang, output):
    return os.path.join(ctx["repo"], ctx["studio_root"], "out", state["video"], lang,
                        "%s.%s.frames" % (output, lang), "index.json")


def tuple_of(state, lang, cur, gate, scope):
    if gate == "source-diff":
        return {"source_hash": cur["source_hash"]}
    return section_tuple(state, lang, cur, gate, output=scope if gate in ("3", "4a") else None,
                         platform=scope if gate == "4b" else None)


def artifacts(ctx, state, lang, gate, scope):
    w = os.path.join(ctx["vdir"], "work", lang)
    if gate == "1":
        # what the person reads and what it was made from (check_claims.py writes both, m1-plan §7.4)
        return {"verify_md": file_sha(os.path.join(w, "verify.md")),
                "verify_json": file_sha(os.path.join(w, "verify.json"))}
    if gate == "2":  # the person hears the audition: its files are part of what was shown (v5 S4)
        a = os.path.join(ctx["repo"], ctx["studio_root"], "out", state["video"], lang, "audition")
        return {"exemptions": file_sha(os.path.join(w, "exemptions.json")),
                "pronounce_changes": file_sha(os.path.join(w, "pronounce-changes.json")),
                "audition_wav": file_sha(os.path.join(a, "narrator.wav")),
                "audition_md": file_sha(os.path.join(a, "audition.md"))}
    if gate == "3":
        return {"frames": file_sha(frames_index(ctx, state, lang, scope))}
    if gate == "4b":  # the fact-checker's judgement of the copy is what the question's 근거 lines come from (M1h NIT)
        from .schema import platform_ok
        return {"copy_verify": file_sha(os.path.join(w, "copy-verify.%s.json" % scope)) if platform_ok(scope)
                else None}
    if gate == "source-diff":
        return {"diff": file_sha(os.path.join(ctx["vdir"], "work", "source-diff.txt"))}
    return {}


def shown_hash(ctx, state, lang, cur, gate, scope):
    return hash_of({"tuple": tuple_of(state, lang, cur, gate, scope),
                    "artifacts": artifacts(ctx, state, lang, gate, scope)})


def hash12(state, lang, gate, recorded=None):
    """The label hash of a gate: the video, the language, the gate and all current scopes' shown hashes (None
    until all were shown). The video, language and gate are in it so that two videos (or languages, or gates)
    with the same content never share a label (m1-plan §3.2)."""
    rec = recorded if recorded is not None else state["langs"][lang]["shown"].get(gate, {})
    pairs = []
    for sc in scopes(state, lang, gate):
        if sc not in rec:
            return None
        pairs.append([sc, rec[sc]["hash"] if isinstance(rec[sc], dict) else rec[sc]])
    return hash_of({"video": state["video"], "lang": lang, "gate": gate, "shown": sorted(pairs)})[:12]


def frames_stamp(path):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return [st.st_mtime_ns, st.st_ino]
