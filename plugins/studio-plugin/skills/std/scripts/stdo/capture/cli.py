"""capture.py — a web page through `s2v capture`, as Studio runs it (m2-plan §5.1).

    capture.py source <video>           the video's URL source
    capture.py recheck <video>          the URL source again, before the video commit
    capture.py shot <video> <name> --url <https url> [--selector <css>] [--width W] [--height H]
                                        a picture of a page (or of one element) for the board

The URL and selector rules are stdo/capture/rules.py's, the run and its result stdo/capture/run.py's. A video has no
URL source in this version: `source` and `recheck` refuse (2).

`shot` writes `<video>/assets/capture-<name>.png` and s2v's JSON as `work/captures/<name>.json`, and records the
result in `work/captures.json` (P-STATE) under `shots.<name>`: the asked URL, the selector and size, `status` (ok or
unusable) and `reason`, `idle`, the hosts s2v blocked, the files and their sha256. A run that is not usable removes the
name's earlier picture and JSON. Nothing is recorded when the run was interrupted or Studio's call was refused.

One capture.py per video at a time (exit 5). No machine lock: capture runs no model.
Exit: 0 ok · 1 not usable (recorded) or interrupted (nothing recorded) · 2 usage, setup or a Studio defect ·
3 refused by the URL rules · 4 the internal overlay is missing · 5 another capture.py works on this video."""

import hashlib
import json
import os
import re
import shutil
import sys

from .. import machine, paths, writes
from ..state import cli as scli, commands as C, schema, store
from . import rules, run as crun

SHOT_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")
SHOT_VALUES = ("--url", "--selector", "--width", "--height")
USAGE_LINE = ("capture.py source <video> | recheck <video> | shot <video> <name> --url <https url> "
              "[--selector <css>] [--width W] [--height H]")


class Usage(Exception):
    pass


def _err(msg):
    sys.stderr.write("std capture: %s\n" % msg)


def _out(msg):
    sys.stdout.write(msg + "\n")


def _opts(rest, values):
    out = {"_": []}
    it = iter(rest)
    for a in it:
        name = a.split("=", 1)[0]
        if a.startswith("--") and name in values:
            if "=" in a:
                v = a.split("=", 1)[1]
            else:
                v = next(it, None)
                if v is None:
                    raise Usage("%s needs a value" % a)
            if name in out:
                raise Usage("%s is given twice" % name)
            out[name] = v
        elif a.startswith("-"):
            raise Usage("unknown option: %s" % a)
        else:
            out["_"].append(a)
    return out


def _sha(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


def _real_dir(vdir, rel):
    """vdir/rel created as real folders (no symbolic link on the way: Studio does not write through one)."""
    cur = vdir
    for part in rel.split("/"):
        cur = os.path.join(cur, part)
        if os.path.islink(cur):
            raise Usage("%s is a symbolic link — Studio does not write through it" % cur)
        if not os.path.isdir(cur):
            os.mkdir(cur)
    return cur


def _write_json(path, data):
    tmp = "%s.tmp.%d" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, path)


def read_captures(vdir):
    p = os.path.join(vdir, "work", "captures.json")
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except OSError:
        return {"shots": {}}
    except ValueError as e:
        raise Usage("work/captures.json is not JSON (%s)" % e)
    if not isinstance(data, dict) or not isinstance(data.get("shots", {}), dict):
        raise Usage("work/captures.json is not an object with shots")
    data.setdefault("shots", {})
    return data


def main(argv, env=None, cwd=None, runner=None):
    env = dict(os.environ if env is None else env)
    cwd = cwd or os.getcwd()
    try:
        if not argv or argv[0] not in ("source", "recheck", "shot"):
            raise Usage(USAGE_LINE)
        sub = argv[0]
        o = _opts(argv[1:], SHOT_VALUES if sub == "shot" else ())
        want = 2 if sub == "shot" else 1
        if len(o["_"]) != want:
            raise Usage(USAGE_LINE)
        if crun.NO_SANDBOX in env:
            raise Usage("%s is set: Studio does not capture without the browser sandbox — unset it (a container "
                        "that needs it cannot capture through Studio)" % crun.NO_SANDBOX)
        try:
            repo, cfg = scli._repo(cwd)
        except scli.Usage as e:
            raise Usage(str(e))
        root = cfg.get("studio_root") or "studio"
        unsafe = paths.local_problem(repo, root)
        if unsafe:
            raise Usage(unsafe)
        vdir = store.video_dir(repo, root, o["_"][0])
        state = store.read_state(vdir)
        if sub != "shot":
            src = state.get("source") or {}
            raise Usage("%s has no URL source (its source is %s): capture.py %s is for URL sources, which this version "
                        "of Studio's scripts does not begin yet" % (state["video"], src.get("kind"), sub))
        name = o["_"][1]
        if not SHOT_NAME.match(name):
            raise Usage("the picture's name is lowercase letters, digits and - (at most 48 characters)")
        if not o.get("--url"):
            raise Usage("shot needs --url <https url>")
        items = rules.overlay_items(repo, cfg, env)
        problem = rules.overlay_problem(items[0], "a page")
        if problem:
            raise problem
        url, host = rules.shot_url(o["--url"], cfg, items, state.get("scope") != "internal")
        sel = rules.selector(o.get("--selector"), items)
        width, height = rules.size("--width", o.get("--width")), rules.size("--height", o.get("--height"))
        allow = rules.allow_hosts(cfg, items)
        s2v_path = machine.s2v_path(repo)
        if s2v_path is None:
            raise Usage(machine.HINT)
        work = _real_dir(vdir, "work")
        with store.Lock(os.path.join(work, ".capture.lock"), wait=0.0):
            return _shot(repo, vdir, name, url, host, sel, width, height, allow, s2v_path, env, runner)
    except Usage as e:
        _err(str(e))
        return C.USAGE
    except rules.CaptureError as e:
        _err(str(e))
        return e.code
    except schema.SchemaError as e:
        _err(str(e))
        return e.code
    except store.Busy:
        _err("another capture.py is working on this video: wait for it")
        return C.BUSY
    except store.Unsupported as e:
        _err(str(e))
        return C.USAGE
    except paths.UnsafeLocal as e:
        _err(str(e))
        return C.USAGE


def _shot(repo, vdir, name, url, host, sel, width, height, allow, s2v_path, env, runner):
    writes.check("a video's captures")
    data = read_captures(vdir)  # an unreadable record stops before the run, not after it
    caps = _real_dir(vdir, "work/captures")
    _real_dir(vdir, "assets")
    png_rel, json_rel = "assets/capture-%s.png" % name, "work/captures/%s.json" % name
    png, js = os.path.join(vdir, png_rel), os.path.join(vdir, json_rel)
    tmp = os.path.join(caps, ".tmp-%s-%d" % (name, os.getpid()))
    shutil.rmtree(tmp, ignore_errors=True)
    os.mkdir(tmp)
    try:
        t_png, t_json = os.path.join(tmp, "shot.png"), os.path.join(tmp, "shot.json")
        res = crun.capture(s2v_path, url, host, t_png, t_json, env, repo, runner=runner, selector=sel, width=width,
                           height=height, allow=allow)
        if res["status"] in ("interrupted", "defect"):
            _err("%s — nothing recorded" % res["reason"])
            return C.FAIL if res["status"] == "interrupted" else C.USAGE
        rec = {"url": url, "selector": sel, "width": width, "height": height, "status": res["status"],
               "reason": res["reason"], "idle": (res["data"] or {}).get("idle"),
               "blocked": [h for h, _r in res["blocked"]], "warnings": res["warnings"], "at": schema.now()}
        if res["status"] == "ok" and not os.path.isfile(t_png):
            rec.update(status="unusable", reason="s2v capture wrote no picture")
        for p in (png, js):
            if os.path.lexists(p) and (os.path.islink(p) or not os.path.isfile(p)):
                raise Usage("%s is not a plain file — Studio does not write over it" % os.path.relpath(p, repo))
        if rec["status"] == "ok":
            os.replace(t_png, png)
            os.replace(t_json, js)
            rec.update(png=png_rel, png_sha=_sha(png), json=json_rel, json_sha=_sha(js))
        else:
            for p in (png, js):
                if os.path.isfile(p):
                    os.remove(p)
        data["shots"][name] = rec
        _write_json(os.path.join(vdir, "work", "captures.json"), data)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    rel = os.path.relpath(vdir, repo).replace(os.sep, "/")
    for h, why in res["blocked"]:
        _out("blocked: %s%s — ask the person whether to add it to capture.allow_hosts (/std config), then capture "
             "again" % (h, " (%s)" % why if why else ""))
    if rec["status"] != "ok":
        _err("%s not usable: %s (recorded in %s/work/captures.json)" % (name, rec["reason"], rel))
        return C.FAIL
    for w in rec["warnings"]:
        _out("warning: %s" % w)
    _out("captured %s: %s/%s (%s)" % (name, rel, png_rel, host))
    return C.OK


def entry():
    store.enable_writes()  # captures.json and the pictures are protected records (P-STATE)
    return main(sys.argv[1:])
