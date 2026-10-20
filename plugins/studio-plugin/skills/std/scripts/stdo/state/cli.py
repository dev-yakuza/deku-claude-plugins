"""state.py — a video's state, hashes and the router (M0b-1; m0b1-plan §6).

    state.py next <video> [--lang l] [--enter <stage> [--output o | --platform p]] [--json]
    state.py record-brief <video> --from <brief.json> [--lang l]
    state.py loop <video> <verify|1|3|4a|copy> [--lang l]
    state.py status [<video>] [--json]
    state.py sync                     (M3b)

Exit: 0 ok · 1 failed · 2 usage/setup · 3 entry refused · 4 waiting for a person · 5 state lock busy.
"""

import json
import os
import re
import subprocess
import sys

from . import commands, schema, store
from .collect import CollectError, Providers
from .hashes import brief_core
from .router import decide, decide_without_script, precheck, section_tuple

C = commands


class Usage(Exception):
    pass


def _err(msg):
    sys.stderr.write("std state: %s\n" % msg)


def _repo(cwd):
    out = subprocess.run(["git", "-C", cwd, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if out.returncode != 0:
        raise Usage("not inside a git repository: %s" % cwd)
    repo = out.stdout.strip()
    p = os.path.join(repo, ".claude", "studio", "config.json")
    try:
        with open(p, encoding="utf-8") as f:
            cfg = json.load(f)
    except OSError:
        raise Usage("no Studio harness here (%s is missing)" % p)
    except ValueError as e:
        raise Usage("%s is not JSON: %s" % (p, e))
    return repo, cfg


def _opts(rest, flags, values):
    """Parse --flag / --name value pairs and positionals."""
    out = {"_": []}
    it = iter(rest)
    for a in it:
        if a in flags:
            out[a] = True
        elif a in values:
            v = next(it, None)
            if v is None:
                raise Usage("%s needs a value" % a)
            out[a] = v
        elif a.startswith("-"):
            raise Usage("unknown option: %s" % a)
        else:
            out["_"].append(a)
    return out


def _ctx(repo, cfg, vdir, lang):
    return {"repo": repo, "studio_root": cfg.get("studio_root") or "studio", "vdir": vdir,
            "s2v_path": (cfg.get("s2v") or {}).get("path"),
            "script": os.path.join(vdir, "script.%s.md" % lang)}


OUTPUT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def main(argv, providers=None, hooks=None, cwd=None, flock=None):
    """Writes need store.enable_writes() first: state.py's entry and the test driver call it."""
    providers = providers or Providers()
    hooks = hooks or {}
    cwd = cwd or os.getcwd()
    try:
        if not argv:
            raise Usage(__doc__.strip().splitlines()[2].strip())
        cmd, rest = argv[0], argv[1:]
        if cmd not in C.IMPLEMENTED:
            raise Usage("%s is not available in this version of state.py" % cmd)
        if cmd == "sync":
            raise Usage("sync arrives with actors (M3b)")
        repo, cfg = _repo(cwd)
        root = cfg.get("studio_root") or "studio"
        if cmd == "status":
            return _status(repo, root, _opts(rest, {"--json"}, set()))
        o = _opts(rest, {"--json"}, {"--lang", "--enter", "--output", "--platform", "--from"})
        if not o["_"]:
            raise Usage("%s needs a video id" % cmd)
        vdir = store.video_dir(repo, root, o["_"][0])
        state = store.read_state(vdir)
        lang = o.get("--lang") or state["source_lang"]
        if lang not in state["langs"]:
            raise Usage("no language %s in %s" % (lang, state["video"]))
        ctx = _ctx(repo, cfg, vdir, lang)
        if cmd == "next":
            return _next(state, lang, ctx, o, providers)
        if cmd == "record-brief":
            return _record_brief(vdir, state, lang, ctx, o, providers, hooks, flock)
        if cmd == "loop":
            return _loop(vdir, lang, o, hooks, flock)
        if cmd == "stage-done":
            return _stage_done(vdir, state, lang, ctx, o, providers, hooks, flock)
    except Usage as e:
        _err(str(e))
        return C.USAGE
    except schema.SchemaError as e:
        _err(str(e))
        return e.code
    except CollectError as e:
        _err(str(e))
        return e.code
    except store.Unsupported as e:
        _err(str(e))
        return C.USAGE
    except store.Busy as e:
        _err(str(e))
        return C.BUSY
    except store.Refused as e:
        _err(str(e))
        return e.code
    return C.FAIL


def _print(obj, as_json, line):
    sys.stdout.write((json.dumps(obj, ensure_ascii=False, sort_keys=True) if as_json else line) + "\n")


def _next(state, lang, ctx, o, providers):
    enter = o.get("--enter")
    output, platform = o.get("--output"), o.get("--platform")
    if enter:
        if enter not in schema.STAGES:
            raise Usage("unknown stage: %s" % enter)
        if enter in schema.OUTPUT_STAGES and not output:
            raise Usage("%s needs --output" % enter)
        if enter in schema.PLATFORM_STAGES and not platform:
            raise Usage("%s needs --platform" % enter)
        if output and output not in schema.current_outputs(state, lang):
            raise Usage("output %s is not in the brief" % output)
        if platform and platform not in schema.current_platforms(state, lang):
            raise Usage("platform %s is not in the brief" % platform)
    d = precheck(state, lang)  # done / held: no inspect needed
    if d is None and not os.path.exists(ctx["script"]):
        d = decide_without_script(state, lang, enter=enter)  # MJ-1: before the script exists
    elif d is None:
        cur = providers.collect(ctx, state, lang)
        d = decide(state, lang, cur, enter=enter, output=output, platform=platform)
    res = d.as_dict()
    if d.done:
        _print(res, o.get("--json"), "%s: finished" % lang)
        return C.OK
    if d.stop or d.held:
        what = d.stop["stop"] if d.stop else d.held.get("state")
        _print(res, o.get("--json"), "%s: waiting for a person (%s)" % (lang, what))
        return C.WAIT
    where = ""
    if d.redo:
        where = d.redo["stage"] + "".join(" %s=%s" % (k, d.redo[k]) for k in ("output", "platform", "mode") if k in d.redo)
    if enter:
        if d.enter == "refused":
            _print(res, o.get("--json"), "%s: not yet — start from %s" % (enter, where))
            return C.REFUSED
        if d.enter == "null-hash":
            for n in d.null_reasons:
                _err("%s cannot be computed: %s" % (n["hash"], "; ".join(n["reasons"]) or "no reason given"))
            _print(res, o.get("--json"), "%s: cannot enter (a hash is missing)" % enter)
            return C.FAIL
        _print(res, o.get("--json"), "%s: go" % enter)
        return C.OK
    _print(res, o.get("--json"), "%s: next %s" % (lang, where or "nothing to redo"))
    return C.OK


def _record_brief(vdir, state, lang, ctx, o, providers, hooks, flock):
    src = o.get("--from")
    if not src:
        raise Usage("record-brief needs --from <brief.json>")
    try:
        with open(src if os.path.isabs(src) else os.path.join(vdir, src), encoding="utf-8") as f:
            b = json.load(f)
    except (OSError, ValueError) as e:
        raise schema.SchemaError("cannot read the brief: %s" % e)
    if not isinstance(b, dict):
        raise schema.SchemaError("the brief is not an object")
    outputs, platforms = b.get("outputs"), b.get("platforms")
    claims, roles = b.get("claims") or [], b.get("roles") or []
    if not isinstance(claims, list) or not all(isinstance(x, str) for x in claims):
        raise schema.SchemaError("brief claims must be a list of claim ids")
    if not isinstance(roles, list) or not all(isinstance(r, dict) and isinstance(r.get("name"), str) for r in roles):
        raise schema.SchemaError("brief roles must be a list of {name, …}")
    if not isinstance(outputs, list) or not outputs:
        raise schema.SchemaError("the brief has no outputs (a video needs at least one; to stop it, abandon)")
    bad = [x for x in outputs if not isinstance(x, str) or not OUTPUT_NAME.match(x)]
    if bad:
        raise schema.SchemaError("not output names: %s" % ", ".join(map(str, bad)))
    if not isinstance(platforms, dict) or not platforms:
        raise schema.SchemaError("the brief has no platforms (every video kind has platform copy)")
    for p, outs in platforms.items():
        if not isinstance(outs, list) or not outs or not all(isinstance(x, str) for x in outs):
            raise schema.SchemaError("platform %s needs a list of outputs" % p)
        stray = [x for x in outs if x not in outputs]
        if stray:
            raise schema.SchemaError("platform %s uses outputs outside the brief: %s" % (p, ", ".join(stray)))
    if os.path.exists(ctx["script"]):
        # the brief comes before the script: only once a script exists are its outputs checked
        # (and `next` checks them on every call)
        names = {x.get("name") for x in (providers.inspect(ctx).get("outputs") or [])}
        unknown = [x for x in outputs if x not in names]
        if unknown:
            raise schema.SchemaError("outputs not in the script: %s" % ", ".join(unknown))
    core = brief_core(claims, roles)

    def check(s):  # under the lock (MINOR 4): approved outputs/platforms cannot be removed here
        removed_o = set(s["brief"]["outputs"]) - set(outputs)
        removed_p = set(s["brief"]["platforms"]) - set(platforms)
        for L in s["langs"].values():
            ap = L["approved"]
            if "1" not in ap:
                continue
            locked = [x for x in removed_o if x in ap.get("3", {}) or x in ap.get("4a", {})]
            locked += [x for x in removed_p if x in ap.get("4b", {})]
            if locked:
                raise store.Refused("approved outputs/platforms cannot be removed here: %s — use exclude-output"
                                    % ", ".join(sorted(locked)), C.REFUSED)

    def change(s):
        s["brief"] = {"core": core, "outputs": list(outputs), "platforms": dict(platforms)}

    store.write(vdir, {"event": "record-brief", "core": core, "outputs": outputs, "platforms": platforms},
                change, hooks=hooks, check=check, **({"flock": flock} if flock else {}))
    sys.stdout.write("brief_core %s\n" % core)
    return C.OK


def _stage_done(vdir, state, lang, ctx, o, providers, hooks, flock):
    """Record that a stage finished for its scope, with its section's current tuple. Only a stage
    `next --enter` would allow may be recorded (no skipping ahead)."""
    if len(o["_"]) < 2:
        raise Usage("stage-done needs a stage: %s" % "|".join(schema.DONE_STAGES))
    stage = o["_"][1]
    if stage not in schema.DONE_STAGES:
        raise Usage("%s is not recorded with stage-done (gates are approved; source and brief have "
                    "their own records)" % stage)
    output, platform = o.get("--output"), o.get("--platform")
    gate = schema.section_gate(stage)
    if gate in ("3", "4a") and not output:
        raise Usage("%s needs --output" % stage)
    if gate == "4b" and not platform:
        raise Usage("%s needs --platform" % stage)
    if gate in ("1", "2") and (output or platform):
        raise Usage("%s takes no --output or --platform" % stage)
    if not os.path.exists(ctx["script"]):
        raise schema.SchemaError("no script yet: %s" % ctx["script"])
    d = precheck(state, lang)
    if d:
        _err("%s is %s" % (lang, "finished" if d.done else "held"))
        return C.WAIT if d.held else C.USAGE
    cur = providers.collect(ctx, state, lang)
    o_key = output if gate in ("3", "4a") else None
    p_key = platform if gate == "4b" else None
    box = {}

    def check(s):  # judged again under the lock, on the state as it is now
        first = precheck(s, lang)
        if first:
            raise store.Refused("%s is %s" % (lang, "finished" if first.done else "held"),
                                C.WAIT if first.held else C.USAGE)
        d = decide(s, lang, cur, enter=stage, output=output, platform=platform)
        if d.stop:
            raise store.Refused("waiting for a person (%s)" % d.stop["stop"], C.WAIT)
        if d.held:
            raise store.Refused("waiting for a person (%s)" % d.held.get("state"), C.WAIT)
        if d.enter == "null-hash":
            raise store.Refused("\n".join("%s cannot be computed: %s" % (n["hash"], "; ".join(n["reasons"]) or
                                                                          "no reason given") for n in d.null_reasons),
                                C.FAIL)
        if d.enter != "allowed":
            r = d.redo or {}
            where = r.get("stage", "an earlier stage") + "".join(
                " %s=%s" % (k, r[k]) for k in ("output", "platform") if k in r)
            raise store.Refused("%s cannot be recorded yet: the work is at %s" % (stage, where), C.REFUSED)
        box["tuple"] = schema.project(stage, section_tuple(s, lang, cur, gate, output, platform))

    rec = {"stage": stage, "output": o_key, "platform": p_key, "at": schema.now()}

    def change(s):
        L = s["langs"][lang]
        L["done_stages"] = [r for r in L.get("done_stages", [])
                            if not (r["stage"] == stage and r.get("output") == o_key
                                    and r.get("platform") == p_key)] + [dict(rec, tuple=box["tuple"])]

    store.write(vdir, {"event": "stage-done", "lang": lang, "stage": stage, "output": o_key,
                       "platform": p_key}, change, hooks=hooks, check=check,
                **({"flock": flock} if flock else {}))
    sys.stdout.write("%s done\n" % stage)
    return C.OK


def _loop(vdir, lang, o, hooks, flock):
    if len(o["_"]) < 2 or o["_"][1] not in schema.LOOPS:
        raise Usage("loop needs a stage: %s" % "|".join(schema.LOOPS))
    stage = o["_"][1]
    box = {}

    def check(s):  # MINOR 1: never over an existing held state, never on a finished language
        L = s["langs"][lang]
        if L["status"] in ("done", "aborted"):
            raise store.Refused("%s is %s: nothing to loop" % (lang, L["status"]), C.USAGE)
        if L.get("held"):
            raise store.Refused("%s is held (%s): resolve it first" % (lang, L["held"].get("state")), C.WAIT)

    def change(s):
        L = s["langs"][lang]
        L["loops"][stage] += 1
        box["n"] = L["loops"][stage]
        if L["loops"][stage] >= 3:
            L["held"] = {"state": "stagnation", "detail": {"stage": stage}, "since": schema.now()}

    store.write(vdir, {"event": "loop", "lang": lang, "stage": stage}, change, hooks=hooks, check=check,
                **({"flock": flock} if flock else {}))
    if box["n"] >= 3:
        sys.stdout.write("%s: held (stagnation after %d loops at %s)\n" % (lang, box["n"], stage))
        return C.WAIT
    sys.stdout.write("%s: loop %d at %s\n" % (lang, box["n"], stage))
    return C.OK


def _status(repo, root, o):
    vids = []
    for base in (os.path.join(repo, root, "videos"), os.path.join(repo, root, "local", "videos")):
        if os.path.isdir(base):
            vids += [os.path.join(base, n) for n in sorted(os.listdir(base))]
    want = o["_"][0] if o["_"] else None
    if want and want not in [os.path.basename(v) for v in vids]:
        raise Usage("no video %s" % want)
    out = []
    for vdir in vids:
        if want and os.path.basename(vdir) != want:
            continue
        try:
            st = store.read_state(vdir)
        except schema.SchemaError as e:
            out.append({"video": os.path.basename(vdir), "error": str(e)})
            continue
        out.append({"video": st["video"], "location": st["location"],
                    "langs": {k: {"status": v["status"], "stage": v["stage"], "held": v["held"]}
                              for k, v in st["langs"].items()},
                    "incomplete_events": store.incomplete(vdir, st),
                    "unreadable_log_lines": sum(1 for e in store.read_log(vdir) if e.get("event") == "unreadable")})
    warn = _guard_ran_warning(repo)
    if o.get("--json"):
        sys.stdout.write(json.dumps({"videos": out, "warnings": [warn] if warn else []}, ensure_ascii=False,
                                    sort_keys=True) + "\n")
    else:
        for v in out:
            if "error" in v:
                sys.stdout.write("%s: %s\n" % (v["video"], v["error"]))
                continue
            for k, L in v["langs"].items():
                sys.stdout.write("%s [%s] %s %s%s\n" % (v["video"], k, L["status"], L["stage"],
                                                         " held:%s" % L["held"]["state"] if L["held"] else ""))
            if v["incomplete_events"]:
                sys.stdout.write("%s: incomplete events %s (not applied)\n" % (v["video"], v["incomplete_events"]))
            if v["unreadable_log_lines"]:
                sys.stdout.write("%s: %d unreadable line(s) in approvals.jsonl\n" % (v["video"], v["unreadable_log_lines"]))
        if warn:
            sys.stdout.write("warning: %s\n" % warn)
    return C.OK


def _guard_ran_warning(repo):
    """M0b-1: a warning only (the requirement comes with M0d-2). Session id: CLAUDE_CODE_SESSION_ID
    (m0-measure X2, A; interactive re-check B2 pending)."""
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID")
    if not sid:
        return None
    p = os.path.join(repo, ".claude", "studio", "local", "guard-ran.json")
    try:
        with open(p, encoding="utf-8") as f:
            seen = json.load(f)
    except (OSError, ValueError):
        seen = {}
    if sid not in seen:
        return "the Studio guard has not run in this session (is the plugin enabled?)"
    return None
