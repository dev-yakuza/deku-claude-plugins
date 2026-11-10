"""limner, the local image engine Herald calls for diagrams and OG cards
(design/herald/08-images.md §2.4, 0.17.0).

limner is optional: when it is missing or broken only the features that need it turn off
(P14). Herald runs it as an argv without a shell, in its own process group, reads one JSON line
from stdout (stderr is thrown away — its text never reaches a PR), checks `contract`, and reads
the exit code by limner's table (§2.4.3). 0.17.0 calls only `--version`, `rasterize`, `compose`
and — to show a human at init/config — `doctor --json`; `run`/`status`/`cancel` are 0.18.0.
"""

import json
import os
import shutil
import signal
import subprocess
import tempfile

from .util import HeraldError, git_ok, read_json, version_tuple

CONTRACT = 1
SUPPORTED_CONTRACTS = (1,)
MIN_VERSION = "0.1.0"
DEFAULT = {"command": ["lmn"], "state_dir": ".limner"}
CALL_TIMEOUT = 60
PROBE_TIMEOUT = 10
DOCTOR_TIMEOUT = 30
KILL_GRACE = 5
STDOUT_MAX = 1 << 20
PROBE_DIR = "herald-probe"
TRIAL_DIR = "herald-trial"
# limner's own folders under the state dir that mirror an output path (records, sanitized SVGs,
# replaced files) — cleaned for Herald's probe and trial outputs only
_MIRRORS = ("records", "sanitized", "prev")
PROBE_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 32" width="64" height="32">'
             '<rect width="64" height="32" fill="#ffffff"/>'
             '<text x="4" y="22" font-size="16" font-family="sans-serif" fill="#000000">가あA</text></svg>')

_probe_cache = {}


# --- config (§2.4.1) ------------------------------------------------------------------------

def configured(cfg):
    """limner matters only once a repo manages images or names limner itself."""
    return cfg.get("limner") is not None or isinstance(cfg.get("images"), dict)


def settings(cfg, command=None):
    blk = cfg.get("limner")
    blk = blk if isinstance(blk, dict) else {}
    return {"command": command if command is not None else blk.get("command", DEFAULT["command"]),
            "state_dir": blk.get("state_dir", DEFAULT["state_dir"])}


def limner_errors(cfg, command=None, check_ignored=True):
    """What is wrong with the `limner` block ([] when fine or not configured). Kept out of
    Config.validate and the guard (L4): an error turns diagrams and limner OG off (`config`)."""
    if command is None and not configured(cfg):
        return []
    if cfg.get("limner") is not None and not isinstance(cfg.get("limner"), dict):
        return ["limner must be an object {\"command\": [...], \"state_dir\": \".limner\"}"]
    from .shots import INLINE_FLAGS, SHORT_BUNDLE_RE, runner
    s = settings(cfg, command)
    t, errors = s["command"], []
    if not isinstance(t, list) or not all(isinstance(x, str) and x for x in t):
        errors.append("limner.command must be an array of strings (an argv — no shell)")
    elif not t:
        errors.append("limner.command is empty")
    else:
        shells = [x for x in t if runner(x)]
        if shells:
            errors.append("limner.command must not run a shell or an interpreter (%s)" % ", ".join(shells))
        flags = sorted({x for x in t if x in INLINE_FLAGS or SHORT_BUNDLE_RE.match(x)})
        if flags:
            errors.append("limner.command must not pass inline code (%s)" % ", ".join(flags))
        if any("{" in x and "}" in x for x in t):
            errors.append("limner.command takes no placeholders (Herald appends the subcommand and its arguments)")
    sd = s["state_dir"]
    if not isinstance(sd, str) or not sd.strip():
        errors.append("limner.state_dir must be a relative path")
        return errors
    parts = sd.replace("\\", "/").strip("/").split("/")
    if os.path.isabs(sd) or ".." in parts:
        errors.append("limner.state_dir must be a relative path inside the repository, without `..`")
    elif parts[0] in (".git", ".claude"):
        errors.append("limner.state_dir must not lie under .git/ or .claude/ (limner refuses to write there)")
    else:
        norm = "/".join(parts)
        inputs = cfg.get("paths", "build_inputs") or []
        inputs = inputs if isinstance(inputs, list) else [inputs]
        for d in [cfg.get("paths", "content"), cfg.get("paths", "images")] + list(inputs):
            if isinstance(d, str) and d.strip("/") and (norm == d.strip("/") or norm.startswith(d.strip("/") + "/")):
                errors.append("limner.state_dir %s lies under %s — it would be published" % (sd, d))
                break
        if check_ignored and not git_ok(cfg.root, "check-ignore", "-q", "%s/%s/x.png" % (norm, PROBE_DIR)):
            errors.append("limner.state_dir %s is not gitignored — put `%s/` into the herald block of .gitignore"
                          % (sd, norm))
    return errors


def state_dir_abs(root, cfg):
    return os.path.join(os.path.realpath(root), settings(cfg)["state_dir"].strip("/"))


# --- the runner (§2.4.3) --------------------------------------------------------------------

def _pgid_file(root):
    return os.path.join(root, ".claude/herald/memory/images/tmp/limner.pgid")


def _reap_stale(root, warnings):
    """A group an earlier, cut-off call left behind (killed only when its leader still matches
    the record — a reused PID is left alone)."""
    from .shots import _killpg, _ps
    path = _pgid_file(root)
    rec = read_json(path) if os.path.isfile(path) else None
    pgid = rec.get("pgid") if isinstance(rec, dict) else None
    if isinstance(pgid, int) and pgid > 1:
        started = _ps(pgid, "lstart")
        if started:
            argv0 = os.path.basename(str(rec.get("argv0") or ""))
            if rec.get("started") == started and argv0 and argv0 in _ps(pgid, "command"):
                _killpg(pgid, signal.SIGKILL)
            elif warnings is not None:
                warnings.append("an earlier limner call's process group %d does not match its record — left alone" % pgid)
    try:
        os.remove(path)
    except OSError:
        pass


def run(root, cfg, sub, opts=(), timeout=CALL_TIMEOUT, command=None):
    """`<command> <sub…> <opts>` without a shell. `opts` are (flag, value) pairs Herald built;
    a value never starts with `-`. Returns {"exit": int|None, "obj": dict|None, "fail": code|None}
    where `fail` is `missing`, `timeout` or `contract` (not one JSON object with a supported
    contract on stdout)."""
    from .shots import _killpg, _ps
    argv = list(settings(cfg, command)["command"]) + list(sub)
    for flag, value in opts:
        value = str(value)
        if value.startswith("-"):
            raise HeraldError("limner argument %s %r starts with `-`" % (flag, value))
        argv += [flag, value]
    _reap_stale(root, None)
    pgid = _pgid_file(root)
    with tempfile.TemporaryFile() as out:
        try:
            proc = subprocess.Popen(argv, cwd=root, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.DEVNULL,
                                    start_new_session=True)
        except (FileNotFoundError, PermissionError, NotADirectoryError):
            return {"exit": None, "obj": None, "fail": "missing"}
        except OSError:
            return {"exit": None, "obj": None, "fail": "missing"}
        try:
            os.makedirs(os.path.dirname(pgid), exist_ok=True)
            with open(pgid, "w", encoding="utf-8") as f:
                json.dump({"pgid": proc.pid, "started": _ps(proc.pid, "lstart"), "argv0": argv[0]}, f)
        except OSError:
            pass
        fail = None
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            fail = "timeout"
            _killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=KILL_GRACE)
            except subprocess.TimeoutExpired:
                _killpg(proc.pid, signal.SIGKILL)
                proc.wait()
        _killpg(proc.pid, signal.SIGKILL)
        try:
            os.remove(pgid)
        except OSError:
            pass
        if fail:
            return {"exit": None, "obj": None, "fail": fail}
        out.seek(0)
        data = out.read(STDOUT_MAX + 1)
    obj = None
    if len(data) <= STDOUT_MAX:
        lines = [x for x in data.decode("utf-8", "replace").splitlines() if x.strip()]
        if len(lines) == 1:
            try:
                obj = json.loads(lines[0])
            except ValueError:
                obj = None
    if not isinstance(obj, dict) or obj.get("contract") not in SUPPORTED_CONTRACTS:
        return {"exit": proc.returncode, "obj": obj if isinstance(obj, dict) else None, "fail": "contract"}
    return {"exit": proc.returncode, "obj": obj, "fail": None}


def classify(res):
    """(problems, failure) by the exit-code table. failure = {"code", "class", "message"} or None;
    problems: limner's `problems` on exit 4 (class content)."""
    def failure(code, klass, message=None):
        return {"code": code, "class": klass, "message": message}
    if res["fail"] == "missing":
        return [], failure("limner:missing", "env", "limner is not installed (limner.command did not start)")
    if res["fail"] == "timeout":
        return [], failure("timeout", "env", "limner did not finish in time")
    if res["fail"] == "contract":
        return [], failure("contract", "env", "limner did not answer with one JSON line of a supported contract")
    code, obj = res["exit"], res["obj"] or {}
    err = str(obj.get("error") or "")[:500]
    if code == 0:
        return [], None
    if code == 4:
        probs = [p for p in obj.get("problems") or [] if isinstance(p, dict)]
        return probs or [{"code": "unknown"}], None
    if code == 2:
        if "font" in err.lower():
            return [], failure("limner:fonts", "env", "limner's fonts are missing — `lmn fonts install`")
        return [], failure("input", "content", err)
    if code == 70:
        return [], failure("internal", "env", err or "limner internal error")
    if code in (5, 10, 11, 12, 73):
        return [], failure("unexpected-%d" % code, "env", err)
    return [], failure("crashed", "env", err)


# --- probe (§2.4.2) -------------------------------------------------------------------------

def _clean_outputs(root, cfg, folder):
    """Remove Herald's own probe/trial folder and what limner mirrored of it (records,
    sanitized SVGs, replaced files). The folder is Herald's alone, so nothing else goes."""
    sd = state_dir_abs(root, cfg)
    rel = os.path.relpath(os.path.join(sd, folder), os.path.realpath(root))
    for d in [os.path.join(sd, folder)] + [os.path.join(sd, m, rel) for m in _MIRRORS]:
        shutil.rmtree(d, ignore_errors=True)
    for m in _MIRRORS:  # empty parents limner made for the mirror
        d = os.path.dirname(os.path.join(sd, m, rel))
        while d.startswith(sd) and d != sd:
            try:
                os.rmdir(d)
            except OSError:
                break
            d = os.path.dirname(d)


def _stamp():
    import datetime
    return "%d-%s" % (os.getpid(), datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))


def probe(root, cfg, command=None, check_ignored=True):
    """Can this machine draw what 0.17.0 asks for? `--version` (contract, version) and one small
    `rasterize` (fonts). Cached for this process only. {"ok", "code", "contract", "limner"}."""
    s = settings(cfg, command)
    key = (os.path.realpath(root), json.dumps(s, sort_keys=True), check_ignored)
    if key in _probe_cache:
        return dict(_probe_cache[key])
    errs = limner_errors(cfg, command=command, check_ignored=check_ignored)
    if errs:
        out = {"ok": False, "code": "config", "errors": errs}
    else:
        out = _probe(root, cfg, command)
    _probe_cache[key] = out
    return dict(out)


def _probe(root, cfg, command):
    res = run(root, cfg, ["--version"], timeout=PROBE_TIMEOUT, command=command)
    if res["fail"] == "missing":
        return {"ok": False, "code": "limner:missing"}
    if res["fail"] == "timeout":
        return {"ok": False, "code": "limner:timeout"}
    obj = res["obj"]
    if obj is None:
        return {"ok": False, "code": "limner:output"}
    if obj.get("contract") not in SUPPORTED_CONTRACTS:
        return {"ok": False, "code": "limner:contract-%s" % obj.get("contract")}
    try:
        if version_tuple(obj.get("limner")) < version_tuple(MIN_VERSION):
            return {"ok": False, "code": "limner:version-%s" % obj.get("limner")}
    except HeraldError:
        return {"ok": False, "code": "limner:output"}
    ver = obj.get("limner")
    sd = state_dir_abs(root, cfg)
    made_sd = not os.path.isdir(sd)  # init's read-only analysis: a state dir only the probe made goes again
    _clean_outputs(root, cfg, PROBE_DIR)  # what a cut-off probe left
    d = os.path.join(sd, PROBE_DIR)
    os.makedirs(d, exist_ok=True)
    name = _stamp()
    svg = os.path.join(d, name + ".svg")
    with open(svg, "w", encoding="utf-8") as f:
        f.write(PROBE_SVG)
    try:
        res = run(root, cfg, ["rasterize"], [("--svg", svg), ("--root", os.path.realpath(root)), ("--state-dir", sd),
                                             ("--out", os.path.join(d, name + ".png"))],
                  timeout=PROBE_TIMEOUT, command=command)
    finally:
        _clean_outputs(root, cfg, PROBE_DIR)
        if made_sd:
            shutil.rmtree(sd, ignore_errors=True)
    if res["fail"] == "timeout":
        return {"ok": False, "code": "limner:timeout", "limner": ver}
    if res["fail"]:
        return {"ok": False, "code": "limner:probe-%s" % res["fail"], "limner": ver}
    if res["exit"] == 0:
        return {"ok": True, "code": None, "contract": CONTRACT, "limner": ver}
    if res["exit"] == 2 and "font" in str((res["obj"] or {}).get("error") or "").lower():
        return {"ok": False, "code": "limner:fonts", "limner": ver}
    return {"ok": False, "code": "limner:probe-%s" % res["exit"], "limner": ver}


def doctor(root, cfg, command=None):
    """`HRD image doctor`: the probe plus a summary of `lmn doctor --json` — for a human at init
    and config only (it imports the generator stack and is slow)."""
    cmd = command
    if isinstance(command, str):
        import shlex
        cmd = shlex.split(command)  # a quoted path with spaces stays one element (review m12)
    p = probe(root, cfg, command=cmd, check_ignored=cmd is None)
    out = {"ok": p["ok"], "command": settings(cfg, cmd)["command"], "contract": p.get("contract"),
           "limner": p.get("limner"), "fonts": {}, "errors": list(p.get("errors") or [])}
    if p.get("code"):
        out["errors"].append(p["code"])
    if p.get("code") in ("config", "limner:missing"):
        return out
    res = run(root, cfg, ["doctor", "--json"], timeout=DOCTOR_TIMEOUT, command=cmd)
    obj = res.get("obj") or {}
    fonts = obj.get("fonts")
    if isinstance(fonts, dict):
        out["fonts"] = {str(k): v for k, v in fonts.items()}
    elif isinstance(fonts, list):
        out["fonts"] = {str(f.get("name") or f.get("file")): f.get("installed", f.get("ok"))
                        for f in fonts if isinstance(f, dict)}
    if res["fail"]:
        out["errors"].append("doctor:%s" % res["fail"])
    return out


def reset_cache():
    _probe_cache.clear()
