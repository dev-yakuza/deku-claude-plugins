"""capture.py — a web page through `s2v capture`, as Studio runs it (m2-plan §5.1).

    capture.py source <video>           the video's URL source
    capture.py recheck <video>          the URL source again, before the video commit
    capture.py shot <video> <name> --url <https url> [--selector <css>] [--width W] [--height H]
                                        a picture of a page (or of one element) for the board

The URL and selector rules are stdo/capture/rules.py's, the run and its result stdo/capture/run.py's.

`source` (a video begun with `state.py begin --url`; refused once gate ① approved its copy) writes the copy into
`work/source/`: `capture.png`, s2v's JSON `capture.json`, the page's pictures `assets/<sha256>.<ext>`, the page's text
`page.md` and readings `page-ruby.json` (stdo/source/page.py), and `capture-files.json` (stdo/capture/files.py: every
file's sha256 and what the capture said). A page that is not usable (s2v exit 1, another host, unsettled twice, no
content hash) leaves `work/source/` as it was. `state.py record-source` records the copy.

`recheck` (after record-source) captures the page again into `work/source/recheck-<n>/` — the same files, its own
`capture-files.json` and `result.json` (`reachable`, `hash` or null, the reason, `at`) — and prints the
`state.py record-recheck <video> <n>` line that records it; it never writes the state (exit 1 when the page could not
be read: the result is still written and is recorded the same way).

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
from ..source import page as cpage
from ..state import cli as scli, commands as C, schema, store
from . import files, rules, run as crun

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
            return _page(repo, cfg, vdir, state, sub, env, runner)
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


# ---------- the URL source and its recheck ----------

def _approved_1(state):
    return any(isinstance(L, dict) and L.get("status") == "active" and "1" in (L.get("approved") or {})
               for L in (state.get("langs") or {}).values())


def _page(repo, cfg, vdir, state, sub, env, runner):
    src = state.get("source") or {}
    if src.get("kind") != "url":
        raise Usage("%s has no URL source (its source is %s): capture.py %s is for a video begun with state.py begin "
                    "--url" % (state["video"], src.get("kind"), sub))
    items = rules.overlay_items(repo, cfg, env)
    problem = rules.overlay_problem(items[0], "the source page")
    if problem:
        raise problem
    url = src.get("url")
    host = rules.page_host(url, cfg, items, "the source's URL")
    allow = rules.allow_hosts(cfg, items)
    if sub == "source" and _approved_1(state):
        raise rules.CaptureError(rules.REFUSED, "the source's copy was approved at gate 1: Studio reads the page "
                                                "again with capture.py recheck %s, never a new source capture"
                                 % state["video"])
    if sub == "recheck" and not src.get("frozen_hash"):
        raise Usage("the source is not recorded yet: capture.py source %s and state.py record-source %s first"
                    % (state["video"], state["video"]))
    s2v_path = machine.s2v_path(repo)
    if s2v_path is None:
        raise Usage(machine.HINT)
    work = _real_dir(vdir, "work")
    with store.Lock(os.path.join(work, ".capture.lock"), wait=0.0):
        writes.check("a video's source copy")
        sdir = _real_dir(vdir, "work/source")
        for x in sorted(os.listdir(sdir)):  # an earlier run's temporary folder (the lock is ours)
            if x.startswith((".capture-", ".recheck-")):
                _remove(os.path.join(sdir, x))
        internal_urls = rules.source_urls(repo, cfg, env)

        def final_check(final):  # a redirect on the same host must not land on what the asked address may not name
            return rules.final_problem(final, cfg, items, internal_urls)

        run = (url, host, allow, s2v_path, env, runner, final_check)
        if sub == "source":
            stale = [x for x in os.listdir(sdir) if x.startswith((".promote-", ".prev-"))]
            if stale:
                raise Usage("an interrupted promotion left %s in work/source/: run state.py record-source %s "
                            "--from-recheck <n> again first" % (stale[0], state["video"]))
            return _source(repo, vdir, sdir, state, run)
        return _recheck(repo, vdir, sdir, state, run)


def _remove(p):
    if os.path.islink(p) or os.path.isfile(p):
        os.remove(p)
    elif os.path.isdir(p):
        shutil.rmtree(p)


def _run_page(repo, folder, run):
    """s2v capture of the source page into `folder` (made here), with page.md and page-ruby.json when usable."""
    url, host, allow, s2v_path, env, runner, final_check = run
    os.mkdir(folder)
    png = os.path.join(folder, "capture.png")
    res = crun.capture(s2v_path, url, host, png, os.path.join(folder, "capture.json"), env, repo, runner=runner,
                       assets_dir=os.path.join(folder, "assets"), allow=allow, page=True)
    if res["status"] == "ok" and not os.path.isfile(png):
        res.update(status="unusable", reason="s2v capture wrote no picture")
    if res["status"] == "ok":
        why = final_check((res["data"] or {}).get("url"))
        if why:
            res.update(status="unusable", reason=why)
    if res["status"] == "ok":
        md, ruby = cpage.render(res["data"])
        for name, text in (("page.md", md), ("page-ruby.json", ruby)):
            with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
                f.write(text)
    return res


def _meta(url, res):
    d = res["data"] or {}
    ok = res["status"] == "ok"
    return {"url": url, "final": d.get("url"), "at": schema.now(), "status": d.get("status"), "idle": d.get("idle"),
            "attempts": res["attempts"], "content_hash": d.get("contentHash") if ok else None,
            "blocked": [h for h, _r in res["blocked"]], "warnings": list(res["warnings"]),
            "opaque_in_capture": sum(1 for x in d.get("opaque") or [] if isinstance(x, dict) and x.get("inCapture")),
            "reason": res["reason"]}


def _blocked_lines(res):
    for h, why in res["blocked"]:
        _out("blocked: %s%s — ask the person whether to add it to capture.allow_hosts (/std config), then capture "
             "again" % (h, " (%s)" % why if why else ""))


LAST_ATTEMPT = "last-attempt.json"


def _source(repo, vdir, sdir, state, run):
    tmp = os.path.join(sdir, ".capture-%d" % os.getpid())
    try:
        res = _run_page(repo, tmp, run)
        if res["status"] in ("interrupted", "defect"):
            _err("%s — nothing recorded" % res["reason"])
            return C.FAIL if res["status"] == "interrupted" else C.USAGE
        _blocked_lines(res)
        attempt = os.path.join(sdir, LAST_ATTEMPT)
        if res["status"] != "ok":
            # not part of the copy (capture-files.json never lists it): why the last capture was not usable
            _write_json(attempt, {"at": schema.now(), "url": run[0], "final": (res["data"] or {}).get("url"),
                                  "reason": res["reason"]})
            _err("the page cannot be the source: %s (work/source/ is unchanged; work/source/%s says why)"
                 % (res["reason"], LAST_ATTEMPT))
            return C.FAIL
        if os.path.lexists(attempt):
            os.remove(attempt)
        files.write(tmp, _meta(run[0], res))
        # the copy's files are replaced one by one, capture-files.json first out and last in: a copy cut short has
        # no record (or one its files do not match), which record-source refuses
        rec = os.path.join(sdir, files.NAME)
        if os.path.lexists(rec):
            os.remove(rec)
        for name in files.COPY:
            dst = os.path.join(sdir, name)
            if os.path.lexists(dst):
                _remove(dst)
            if os.path.lexists(os.path.join(tmp, name)):
                os.replace(os.path.join(tmp, name), dst)
        os.replace(os.path.join(tmp, files.NAME), rec)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    data = res["data"] or {}
    for w in res["warnings"]:
        _out("warning: %s" % w)
    rel = os.path.relpath(sdir, repo).replace(os.sep, "/")
    _out("captured the source page: %s/page.md (%d text block(s), %d picture(s), %s)" % (
        rel, len(data.get("text") or []), len(data.get("images") or []), run[1]))
    _out("next: python3 .claude/studio/scripts/state.py record-source %s" % state["video"])
    return C.OK


def next_recheck(sdir, src):
    """One above every recheck recorded in the state or found in work/source/."""
    top = [r.get("n") for r in src.get("rechecks") or [] if isinstance(r, dict) and isinstance(r.get("n"), int)]
    return max(top + list(files.numbered(sdir, files.RECHECK)) + [0]) + 1


def _recheck(repo, vdir, sdir, state, run):
    src = state["source"]
    n = next_recheck(sdir, src)
    tmp = os.path.join(sdir, ".recheck-%d-%d" % (n, os.getpid()))
    try:
        res = _run_page(repo, tmp, run)
        if res["status"] in ("interrupted", "defect"):
            _err("%s — nothing recorded" % res["reason"])
            return C.FAIL if res["status"] == "interrupted" else C.USAGE
        meta = _meta(run[0], res)
        ok = res["status"] == "ok"
        _write_json(os.path.join(tmp, files.RESULT), {"n": n, "reachable": ok, "hash": meta["content_hash"],
                                                      "reason": None if ok else res["reason"], "at": meta["at"]})
        files.write(tmp, meta)
        os.rename(tmp, os.path.join(sdir, "recheck-%d" % n))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    _blocked_lines(res)
    for w in res["warnings"]:
        _out("warning: %s" % w)
    if not ok:
        _err("recheck %d: the page could not be read (%s)" % (n, res["reason"]))
    elif meta["content_hash"] == src.get("frozen_hash"):
        _out("recheck %d: the page is as the recorded copy (%s)" % (n, meta["content_hash"][:12]))
    else:
        _out("recheck %d: the page changed (%s → %s)" % (n, (src.get("frozen_hash") or "")[:12],
                                                          meta["content_hash"][:12]))
    _out("next: python3 .claude/studio/scripts/state.py record-recheck %s %d" % (state["video"], n))
    return C.OK if ok else C.FAIL


def entry():
    store.enable_writes()  # captures.json and the pictures are protected records (P-STATE)
    return main(sys.argv[1:])
