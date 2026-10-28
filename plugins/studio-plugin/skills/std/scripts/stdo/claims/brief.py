"""The brief's length estimate (m1-plan §7.2): record-brief computes it itself — the normalized characters of the chosen
claims' excerpts ÷ the format's `chars_per_sec.<lang>` — and refuses a brief outside the format's `length_seconds`.
The strategist's own number is never used."""

import os

from .. import criteria
from ..state.collect import frozen_copy_path
from ..text.normalize import Text, chars
from . import sourcemd


class BriefProblem(Exception):
    """The brief cannot be recorded (exit 1)."""


def estimate(repo, vdir, state, claim_ids):
    """{"chars", "chars_per_sec", "seconds", "min", "max"} (raises BriefProblem)."""
    try:
        crit = criteria.read(repo, state.get("kind"))
    except criteria.Missing as e:
        raise BriefProblem("the format's criteria cannot be read (%s) — a person fixes .claude/studio/formats/%s.md"
                           % (e, state.get("kind")))
    lang = state["source_lang"]
    cps = crit["chars_per_sec"].get(lang)
    if cps is None:
        raise BriefProblem("the format gives no chars_per_sec for %s" % lang)
    claims, problems = sourcemd.read(vdir)
    if problems:
        raise BriefProblem("work/source.md: " + "; ".join(problems))
    unknown = [c for c in claim_ids if c not in claims]
    if unknown:
        raise BriefProblem("claims not in work/source.md: %s" % ", ".join(unknown))
    try:
        with open(frozen_copy_path(vdir, state["source"]), encoding="utf-8") as f:
            copy = Text(f.read())
    except OSError:
        raise BriefProblem("no frozen copy of the source — run state.py record-source first")
    absent = [c for c in claim_ids if not copy.contains(claims[c]["excerpt"])]
    if absent:
        raise BriefProblem("the excerpts of %s are not in the source copy (copy them exactly)" % ", ".join(absent))
    n = sum(chars(claims[c]["excerpt"]) for c in sorted(set(claim_ids)))
    secs = n / float(cps)
    ls = crit["length_seconds"]
    out = {"chars": n, "chars_per_sec": cps, "seconds": round(secs, 1), "min": ls["min"], "max": ls["max"]}
    if not ls["min"] <= secs <= ls["max"]:
        raise BriefProblem("the chosen claims come to about %.0f s (%d characters ÷ %s per second), outside the "
                           "format's %s–%s s — choose %s claims" % (secs, n, cps, ls["min"], ls["max"],
                                                                     "more" if secs < ls["min"] else "fewer"))
    return out


def assets_problem(vdir, state):
    """Why the source's checked images do not let the brief or the script go on (J61 · J74), or None."""
    from ..state.hashes import file_sha
    want = state["source"].get("assets_sha")
    if want is None:
        return ("the source's images are not checked yet (no assets_sha): run resolve_assets.py, the source analyst "
                "and check_scope.py, then state.py record-source %s" % state["video"])
    if file_sha(os.path.join(vdir, "work", "assets.json")) != want:
        return ("work/assets.json is not the one record-source recorded: run check_scope.py, then state.py "
                "record-source %s again" % state["video"])
    return None
