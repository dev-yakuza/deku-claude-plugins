"""The frontmatter lines `state.py next <video> --enter script` prints for the writer (0.0.28 Q2 · Q4 · Q5): the
default narrator's cast block — part of the script from the start, since s2v's content hash includes the cast (core
inspect.ts) — and each output's shape from the brief's platform files (`output_plan`), plus the range targetDuration
must lie in (claims.check.target_range).

Outputs are shared by name: the brief maps each platform to output names, and a platform file's `outputs` lists the
shapes it accepts. An output's aspect (and `layout`, `shot` when a platform file names them) comes from the brief
platforms that declare that name; a platform that uses an output it does not declare must declare that aspect. Every
output plays the whole script (no scene cut-downs), so its `maxDuration` is the format's upper bound or the smallest
`max_duration` of the platforms using it, and a platform whose limit is below the format's lower bound cannot be used
for the kind (record-brief refuses it). A 9:16 output gets word subtitles."""

import json
import os
import re

from .. import criteria, narrator
from ..voice import frontmatter

ASPECTS = ("16:9", "9:16", "1:1")  # s2v packages/core/src/schema.ts ASPECTS (setup/platform.py checks drafts with it)
LAYOUTS = ("presenter", "dialogue", "fullscreen", "shorts")  # s2v LAYOUTS
PLAIN_LAYOUTS = ("fullscreen", "shorts")  # layouts the script may carry from the start (no character art needed)
SHOTS = ("full",)  # s2v outputProfileSchema `shot`
WORD_SUBTITLES = ("9:16",)  # aspects whose output gets `subtitles: word`
OUTPUT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class NotReady(Exception):
    """The default narrator cannot be written into a script yet (exit 1: narrator setup first)."""


def default_narrator(repo, root):
    """(id, status) of the default narrator init recorded: `<root>/cast/narrator/`, else the only folder of cast/
    (init's `narrator.id`); (None, None) when there is none or more than one."""
    base = os.path.join(repo, root, "cast")
    try:
        names = sorted(n for n in os.listdir(base) if os.path.isfile(os.path.join(base, n, "status.json")))
    except OSError:
        names = []
    nid = "narrator" if "narrator" in names else (names[0] if len(names) == 1 else None)
    if nid is None:
        return None, None
    try:
        with open(os.path.join(base, nid, "status.json"), "rb") as f:
            return nid, narrator.parse(f.read())
    except OSError:
        return nid, None


def cast_lines(repo, root, lang):
    """The `cast:` block of the default narrator for `lang` (NotReady when it has no ready voice)."""
    nid, st = default_narrator(repo, root)
    hint = "run the narrator setup of /std init (or /std config narrator) first"
    if nid is None:
        raise NotReady("no default narrator in %s/cast/ — %s" % (root, hint))
    v = ((st or {}).get("voice") or {}).get(lang) if isinstance(st, dict) else None
    if not isinstance(v, dict) or v.get("state") != "ready" or not narrator.engine_ok(v.get("engine")):
        raise NotReady("%s/cast/%s/status.json has no ready voice.%s — %s" % (root, nid, lang, hint))
    style = v.get("style") or ""
    if not isinstance(style, str) or not frontmatter.style_ok(style, narrator.STYLE_MAX):
        raise NotReady("%s/cast/%s: the style of voice.%s holds \" or \\ or a line break — %s"
                       % (root, nid, lang, hint))
    spec = 'voice: "%s"' % v["engine"] + (', style: "%s"' % style if style else "")  # an empty style is none
    return ["cast:", "  narrator: { %s }" % spec]


class PlanProblem(Exception):
    """The brief's platform files do not give its outputs one shape each (record-brief refuses; next and the script
    check report it)."""


def declared(repo, platform):
    """The `outputs` a platform file declares: [{name, aspect, max_duration, layout, shot}] (PlanProblem when the file
    cannot be read, is not in the shape Studio reads, or declares no usable output)."""
    from ..distribute import rules
    rel = ".claude/studio/platforms/%s.md" % platform
    fix = "a person fixes it, or runs /std platform refresh %s" % platform
    try:
        with open(rules.path(repo, platform), encoding="utf-8") as f:
            fm = rules.frontmatter(f.read())
    except (OSError, UnicodeDecodeError):
        raise PlanProblem("cannot read %s" % rel)
    except rules.RulesProblem as e:
        raise PlanProblem("%s: %s — %s" % (rel, e, fix))
    outs = fm.get("outputs")
    if not isinstance(outs, list) or not outs:
        raise PlanProblem("%s declares no outputs (each: name, aspect, max_duration) — %s" % (rel, fix))
    seen = set()
    for o in outs:
        n = o.get("name")
        if not isinstance(n, str) or not OUTPUT_NAME.match(n) or n in seen:
            raise PlanProblem("%s: an output needs a unique usable name (%r) — %s" % (rel, n, fix))
        seen.add(n)
        if o.get("aspect") not in ASPECTS:
            raise PlanProblem("%s: output %s: aspect must be one of %s — %s" % (rel, n, ", ".join(ASPECTS), fix))
        md = o.get("max_duration")
        if md is not None and not (isinstance(md, int) and not isinstance(md, bool) and md > 0):
            raise PlanProblem("%s: output %s: max_duration must be seconds or null — %s" % (rel, n, fix))
        if o.get("layout") is not None and o.get("layout") not in LAYOUTS:
            raise PlanProblem("%s: output %s: layout must be one of %s — %s" % (rel, n, ", ".join(LAYOUTS), fix))
        if o.get("shot") is not None and o.get("shot") not in SHOTS:
            raise PlanProblem("%s: output %s: shot must be %s — %s" % (rel, n, " or ".join(SHOTS), fix))
    return outs


def _permissive(decls):
    """The declaration with the largest limit (None — no limit — is the largest)."""
    return sorted(decls, key=lambda d: (d.get("max_duration") is not None, -(d.get("max_duration") or 0)))[0]


def output_plan(repo, platforms, outputs, length=None):
    """{output: {"aspect", "layout", "shot", "max", "limits"}} for the brief's `outputs` and its `platforms` map
    ({platform: [output, …]}); `length`: the format's length_seconds ({min, max}) — `max` is then the format's upper
    bound or the smallest platform limit, and a platform limit below `min` (or too close to it for any targetDuration)
    is refused. A platform's declaration counts only for the outputs the brief maps it to: by name when its file
    declares that name, else its most permissive declaration of the output's aspect. `limits`: [(seconds, platform)]
    of the platforms whose limit applies. PlanProblem names the first problem."""
    decl = {p: declared(repo, p) for p in sorted(platforms)}
    users = {o: [p for p in sorted(platforms) if o in platforms[p]] for o in outputs}
    shape = {o: {"aspect": {}, "layout": {}, "shot": {}} for o in outputs}
    chosen = {}  # (platform, output) → the declaration that applies

    def count(o, p, d):
        chosen[(p, o)] = d
        for k in ("aspect", "layout", "shot"):
            if d.get(k) is not None:
                shape[o][k].setdefault(d[k], []).append(p)
    for o in outputs:
        for p in users[o]:
            named = [d for d in decl[p] if d["name"] == o]
            if named:
                count(o, p, named[0])
        if not shape[o]["aspect"]:
            raise PlanProblem("output %s is declared by none of the platforms the brief maps to it (%s) — map each "
                              "platform to an output name its file (or another of the output's platforms' files) "
                              "declares" % (o, ", ".join(users[o]) or "none"))
        if len(shape[o]["aspect"]) == 1:
            a = next(iter(shape[o]["aspect"]))
            for p in users[o]:
                if (p, o) in chosen:
                    continue
                same = [d for d in decl[p] if d["aspect"] == a]
                if not same:
                    raise PlanProblem("platform %s does not accept output %s (%s): platforms/%s.md declares %s"
                                      % (p, o, a, p, ", ".join("%s (%s)" % (d["name"], d["aspect"]) for d in decl[p])))
                count(o, p, _permissive(same))
    plan = {}
    for o in outputs:
        for k in ("aspect", "layout", "shot"):
            seen = shape[o][k]
            if len(seen) > 1:
                raise PlanProblem("output %s has two %ss: %s — one output is one render; use another output name for "
                                  "one of them" % (o, k, "; ".join("%s in platforms/%s.md" % (v, "/".join(ps))
                                                                  for v, ps in sorted(seen.items()))))
        plan[o] = {"aspect": next(iter(shape[o]["aspect"])), "layout": next(iter(shape[o]["layout"]), None),
                   "shot": next(iter(shape[o]["shot"]), None),
                   "limits": [(chosen[(p, o)]["max_duration"], p) for p in users[o]
                              if chosen[(p, o)].get("max_duration") is not None]}
    for o in outputs:
        lim = sorted(plan[o]["limits"])
        if length is not None:
            from ..claims.check import target_range
            low = [x for x in lim if x[0] < length["min"]]
            if low:
                raise PlanProblem("platform %s allows at most %d s for output %s, below the format's lower bound %s s "
                                  "— every output plays the whole video, so this kind cannot use %s"
                                  % (low[0][1], low[0][0], o, length["min"], low[0][1]))
            tight = [x for x in lim if x[0] < length["max"] and target_range({"min": length["min"], "max": x[0]})
                     is None]
            if tight and target_range(length) is None:
                raise PlanProblem("the format's length range %s–%s s is itself too narrow for any targetDuration "
                                  "s2v's ±15 %% check can hold — a person widens length_seconds in the format file "
                                  "(platform %s's %d s limit for output %s narrows it further)"
                                  % (length["min"], length["max"], tight[0][1], tight[0][0], o))
            if tight:
                raise PlanProblem("platform %s allows at most %d s for output %s, too close to the format's lower "
                                  "bound %s s for any targetDuration s2v's ±15 %% check can hold — every output plays "
                                  "the whole video, so this kind cannot use %s"
                                  % (tight[0][1], tight[0][0], o, length["min"], tight[0][1]))
            plan[o]["max"] = min([length["max"]] + [x[0] for x in lim])
        else:
            plan[o]["max"] = lim[0][0] if lim else None
    return plan


def output_lines(repo, kind, outputs, platforms):
    """(lines, notes): `outputs:` with each output's shape and maxDuration, then the targetDuration range — the
    format's range with its upper bound lowered to the smallest maxDuration (the whole script plays in every output).
    PlanProblem when the brief's platform files no longer give one shape per output."""
    from ..claims.check import S2V_TARGET_TOLERANCE, target_range
    crit = criteria.read(repo, kind)  # criteria.Missing: the caller stops
    ls = crit["length_seconds"]
    plan = output_plan(repo, platforms, outputs, ls)
    lines, notes = ["outputs:"], []
    for o in outputs:
        x = plan[o]
        parts = ['aspect: "%s"' % x["aspect"]]
        if x["layout"] in PLAIN_LAYOUTS:  # presenter/dialogue need character art: board's --look decides them
            parts.append("layout: %s" % x["layout"])
        if x["aspect"] in WORD_SUBTITLES:
            parts.append("subtitles: word")
        if x["shot"]:
            parts.append("shot: %s" % x["shot"])
        parts.append("maxDuration: %s" % json.dumps(x["max"]))
        lines.append("  %s: { %s }" % (o, ", ".join(parts)))
    top = min([ls["max"]] + [plan[o]["max"] for o in outputs])
    rng = target_range({"min": ls["min"], "max": top})
    fmt = os.path.relpath(criteria.path(repo, kind), repo)
    if rng is None:
        capped = top != ls["max"]
        notes.append("the %slength range %s–%s s is too narrow for s2v's ±%d %% tolerance: a person widens "
                     "length_seconds in %s%s" % ("" if capped else "format's ", ls["min"], top,
                                                 round(S2V_TARGET_TOLERANCE * 100), fmt,
                                                 " (its upper bound is an output's platform limit here)" if capped
                                                 else ""))
    else:
        lines.append("targetDuration: <%d–%d, from the brief's estimate>" % rng)
    return lines, notes
