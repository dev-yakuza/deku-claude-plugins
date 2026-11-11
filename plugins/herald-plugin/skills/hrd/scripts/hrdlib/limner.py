"""limner, the local image engine Herald calls for diagrams and OG cards
(design/herald/08-images.md §2.4, 0.17.0).

limner is optional: when it is missing or broken only the features that need it turn off
(P14). Herald runs it as an argv without a shell, in its own process group, reads one JSON line
from stdout (stderr is thrown away — its text never reaches a PR), checks `contract`, and reads
the exit code by limner's table (§2.4.3). 0.17.0 calls `--version`, `rasterize`, `compose` and —
to show a human at init/config — `doctor --json`. 0.18.0 adds the scene generator's long-running
commands `run` (with `--check`), `status` and `cancel` (design/herald/09-scenes.md §2.4): limner's
detached worker generates, Herald starts it and looks at it in short calls.
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
JOBS_DIR = "herald-jobs"     # scene job files (09 §2.3.1)
OUT_DIR = "herald-out"       # where limner's worker writes scenes — never the working tree (R2-2)
GEN_MODEL = "qwen-image-edit-2511"  # the job file's `model` (limner lock `generation.model`)
GEN_PROBE_TIMEOUT = 20
RECORD_MAX = 1 << 20
# limner's own folders under the state dir that mirror an output path (records, sanitized SVGs,
# replaced files) — cleaned for Herald's probe and trial outputs only
_MIRRORS = ("records", "sanitized", "prev")
PROBE_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 32" width="64" height="32">'
             '<rect width="64" height="32" fill="#ffffff"/>'
             '<text x="4" y="22" font-size="16" font-family="sans-serif" fill="#000000">가あA</text></svg>')

_probe_cache = {}
_gen_cache = {}


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

def _pgid_dir(root):
    return os.path.join(root, ".claude/herald/memory/images/tmp")


def _pgid_file(root):
    """One file per Herald process (09 §2.4.3, R1-11): a `status` call may wait nine minutes, so
    two Herald commands can run limner at once and must not kill each other's child."""
    return os.path.join(_pgid_dir(root), "limner.%d.pgid" % os.getpid())


def _owner_gone(rec, name):
    """The Herald process that wrote this record is gone (or its PID was reused). The 0.17.0
    single file `limner.pgid` has no owner: it is always an earlier, cut-off call's."""
    from .shots import _ps
    if name == "limner.pgid":
        return True
    owner = rec.get("owner") if isinstance(rec, dict) else None
    if not isinstance(owner, int):
        return True
    if owner == os.getpid():
        return True  # this process's own earlier call that did not clean up
    started = _ps(owner, "lstart")
    return not started or started != rec.get("owner_started")


def _reap_stale(root, warnings):
    """Groups earlier, cut-off calls left behind — only those whose Herald process is gone
    (another live Herald call's child is left alone); each killed only when its leader still
    matches the record (a reused PID is left alone)."""
    from .shots import _killpg, _ps
    d = _pgid_dir(root)
    try:
        names = sorted(n for n in os.listdir(d) if n.startswith("limner.") and n.endswith(".pgid"))
    except OSError:
        return
    for name in names:
        path = os.path.join(d, name)
        try:
            rec = read_json(path)
        except ValueError:
            rec = None
        if not _owner_gone(rec, name):
            continue
        pgid = rec.get("pgid") if isinstance(rec, dict) else None
        if isinstance(pgid, int) and pgid > 1:
            started = _ps(pgid, "lstart")
            if started:
                argv0 = os.path.basename(str(rec.get("argv0") or ""))
                if rec.get("started") == started and argv0 and argv0 in _ps(pgid, "command"):
                    _killpg(pgid, signal.SIGKILL)
                elif warnings is not None:
                    warnings.append("an earlier limner call's process group %d does not match its record — left alone"
                                    % pgid)
        try:
            os.remove(path)
        except OSError:
            pass


def run(root, cfg, sub, opts=(), timeout=CALL_TIMEOUT, command=None):
    """`<command> <sub…> <opts>` without a shell. `opts` are (flag, value) pairs Herald built
    (value None: the flag alone); a value never starts with `-`. Returns {"exit": int|None, "obj": dict|None, "fail": code|None}
    where `fail` is `missing`, `timeout` or `contract` (not one JSON object with a supported
    contract on stdout)."""
    from .shots import _killpg, _ps
    argv = list(settings(cfg, command)["command"]) + list(sub)
    for flag, value in opts:
        if value is None:  # a flag alone (`run --check`)
            argv.append(flag)
            continue
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
                json.dump({"pgid": proc.pid, "started": _ps(proc.pid, "lstart"), "argv0": argv[0],
                           "owner": os.getpid(), "owner_started": _ps(os.getpid(), "lstart")}, f)
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


def version_probe(root, cfg, command=None):
    """`<command> --version`: the contract and version step both probes share (08 §2.4.2 1)."""
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
    return {"ok": True, "code": None, "limner": obj.get("limner")}


def _probe(root, cfg, command):
    v = version_probe(root, cfg, command)
    if not v["ok"]:
        return v
    ver = v["limner"]
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
    _gen_cache.clear()


# --- scene generation (09-scenes.md §2.4) ---------------------------------------------------

def fake_allowed():
    """`HRD_TEST_ALLOW_FAKE_GENERATOR=1` lets limner's fake generator through — tests only
    (`atoms/_images.md` says so); real use refuses it (01-limner §6.6)."""
    return os.environ.get("HRD_TEST_ALLOW_FAKE_GENERATOR") == "1"


def rel_to_root(root, path):
    return os.path.relpath(path, os.path.realpath(root)).replace(os.sep, "/")


def gen_probe(root, cfg):
    """Can this machine generate scenes? `--version`, then `run --check` on a one-job file (64×64,
    no refs): limner checks the job, platform, RAM, mflux and the models without importing the
    generator and writes nothing. No rasterize — scenes use no fonts (Q5). Cached for this process.
    {"ok", "code", "limner", "message"}; code `limner:<…>`, `config`, `generate:env`,
    `generate:fake` or `generate:probe-<exit>`."""
    s = settings(cfg)
    key = (os.path.realpath(root), json.dumps(s, sort_keys=True))
    if key in _gen_cache:
        return dict(_gen_cache[key])
    errs = limner_errors(cfg)
    if errs:
        out = {"ok": False, "code": "config", "errors": errs}
    else:
        out = _gen_probe(root, cfg)
    _gen_cache[key] = out
    return dict(out)


def _gen_probe(root, cfg):
    v = version_probe(root, cfg)
    if not v["ok"]:
        return v
    ver = v["limner"]
    if os.environ.get("LIMNER_FAKE_GENERATOR") and not fake_allowed():
        return {"ok": False, "code": "generate:fake", "limner": ver,
                "message": "LIMNER_FAKE_GENERATOR is set — the fake generator never makes a published scene"}
    sd = state_dir_abs(root, cfg)
    made_sd = not os.path.isdir(sd)
    _clean_outputs(root, cfg, PROBE_DIR)
    d = os.path.join(sd, PROBE_DIR)
    os.makedirs(d, exist_ok=True)
    name = _stamp()
    job = os.path.join(d, name + ".json")
    with open(job, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "model": GEN_MODEL, "jobs": [
            {"id": "probe", "out": rel_to_root(root, os.path.join(d, name + ".png")), "width": 64, "height": 64,
             "prompt": "probe", "refs": [], "seed": 0}]}, f)
    try:
        res = run(root, cfg, ["run"], [("--check", None), ("--job", job), ("--root", os.path.realpath(root)),
                                       ("--state-dir", sd)], timeout=GEN_PROBE_TIMEOUT)
    finally:
        _clean_outputs(root, cfg, PROBE_DIR)
        if made_sd:
            shutil.rmtree(sd, ignore_errors=True)
    if res["fail"] == "timeout":
        return {"ok": False, "code": "generate:timeout", "limner": ver}
    if res["fail"]:
        return {"ok": False, "code": "generate:probe-%s" % res["fail"], "limner": ver}
    err = str((res["obj"] or {}).get("error") or "")[:500]
    if res["exit"] == 0:
        return {"ok": True, "code": None, "limner": ver}
    if res["exit"] == 2:
        return {"ok": False, "code": "generate:env", "limner": ver, "message": err}
    return {"ok": False, "code": "generate:probe-%s" % res["exit"], "limner": ver, "message": err}


def gen_call(root, cfg, sub, opts, timeout):
    """One `run`/`status`/`cancel` call: {"exit", "obj", "fail", "code", "message"}. `code` is
    Herald's reading of a failure that is not a generation verdict (09 §2.4.3 table): `missing`,
    `timeout`, `contract`, `env` (2), `busy` (73), `internal` (70), `not-found` (12), `crashed`
    (any other exit or signal); None when limner answered 0, 5, 10 or 11 with a status object."""
    res = run(root, cfg, [sub], opts, timeout=timeout)
    out = dict(res, code=None, message=None)
    if res["fail"]:
        out["code"] = {"missing": "limner:missing", "timeout": "timeout", "contract": "contract"}[res["fail"]]
        return out
    obj = res["obj"] or {}
    out["message"] = str(obj.get("error") or "")[:500] or None
    code = res["exit"]
    if code in (0, 5, 10, 11) and "error" not in obj:
        return out
    if code == 2:
        out["code"] = "env"
        if not out["message"]:  # a status whose job failed `environment` (the child's internal API, models)
            out["message"] = next((str(f.get("message") or "")[:500] for f in obj.get("failed") or []
                                   if isinstance(f, dict) and f.get("reason") == "environment"), None)
    elif code == 73:
        out["code"] = "busy"
        b = obj.get("busy") if isinstance(obj.get("busy"), dict) else {}
        out["message"] = str(b.get("holder") or b.get("reason") or "the machine is busy")[:300]
    elif code == 70:
        out["code"] = "internal"
    elif code == 12:
        out["code"] = "not-found"
    else:
        out["code"] = "crashed"
    return out


def read_record(root, cfg, out_rel):
    """limner's record of a generated file (`<state_dir>/records/<out>.json`), at most 1 MB, a JSON
    object — or None."""
    p = os.path.join(state_dir_abs(root, cfg), "records", out_rel + ".json")
    try:
        if os.path.getsize(p) > RECORD_MAX:
            return None
        with open(p, encoding="utf-8") as f:
            rec = json.load(f)
    except (OSError, ValueError):
        return None
    return rec if isinstance(rec, dict) else None
