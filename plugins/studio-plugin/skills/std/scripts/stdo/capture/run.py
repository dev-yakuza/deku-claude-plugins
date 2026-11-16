"""Running `s2v capture` as capture.py does (m2-plan §5.1) and judging its result.

The command line is built here, like run_s2v.py's (`node <machine.json's s2v>/packages/cli/dist/main.js capture <url>
--out … --text … [--assets-dir …] --timeout 30 [--allow-host h]…`); the agent chooses no path. The child's environment
is the caller's without S2V_CAPTURE_NO_SANDBOX (capture.py refuses to start when it is set: the browser sandbox is
never turned off through Studio).

Results (`judge`): s2v exit 0 with the page's final address on the asked host → ok; exit 1 (no load, a non-2xx status,
the selector missing, a host that may not be reached) → unusable with the reason; the final address on another host,
`example.com` → `www.example.com` included, → unusable ("capture the final address"); a signal (128+n, or a negative
code) → interrupted, nothing is recorded; exit 2 or anything else → a Studio defect. A page (`page=True`, the source
and its recheck) that did not settle (`idle: false`) is captured once more with --timeout 60; unsettled again, or
without a contentHash, it is unreachable. A board picture that did not settle is kept with a warning.

Studio reads only JSON_KEYS of s2v's JSON (packages/cli/src/capture/extract.ts `CaptureJson`) and ignores the rest."""

import json
import os
import subprocess
from urllib.parse import urlsplit

NO_SANDBOX = "S2V_CAPTURE_NO_SANDBOX"
TIMEOUT, RETRY_TIMEOUT = 30, 60
PROC_TIMEOUT = 1800  # the first capture on a machine may download s2v's browser (about 100 MB)
JSON_KEYS = ("url", "status", "title", "lang", "idle", "text", "images", "opaque", "notShown", "blocked", "websockets",
             "contentHash")
REASON_MAX = 300


def argv_for(s2v_path, url, out_png, text_json, assets_dir=None, selector=None, width=None, height=None,
             timeout=TIMEOUT, allow=()):
    args = ["node", os.path.join(s2v_path, "packages", "cli", "dist", "main.js"), "capture", url, "--out", out_png,
            "--text", text_json]
    if assets_dir:
        args += ["--assets-dir", assets_dir]
    if selector is not None:
        args += ["--selector=" + selector]  # one word: a value is never read as a flag
    if width is not None:
        args += ["--width", str(width)]
    if height is not None:
        args += ["--height", str(height)]
    args += ["--timeout", str(timeout)]
    for h in allow:
        args += ["--allow-host", h]
    return args


def child_env(env):
    e = dict(env)
    e.pop(NO_SANDBOX, None)
    return e


def run(argv, env, cwd):
    try:
        p = subprocess.run(argv, cwd=cwd, env=child_env(env), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=PROC_TIMEOUT)
    except subprocess.TimeoutExpired:
        return -9, "", "s2v capture ran longer than %d s and was stopped" % PROC_TIMEOUT
    except OSError as e:
        return 127, "", "cannot run s2v: %s" % e
    return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


def read_json(path):
    """The keys Studio reads of s2v's JSON (None when it is absent or not an object)."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return {k: data[k] for k in JSON_KEYS if k in data}


def _last_line(stderr):
    lines = [x.strip() for x in (stderr or "").splitlines() if x.strip()]
    return lines[-1][:REASON_MAX] if lines else None


def blocked_hosts(data):
    """[(host, reason)] of the requests s2v blocked (each host once)."""
    out, seen = [], set()
    for b in (data or {}).get("blocked") or []:
        if not isinstance(b, dict) or not isinstance(b.get("url"), str):
            continue
        try:
            h = (urlsplit(b["url"]).hostname or "").lower()
        except ValueError:
            h = ""
        if h and h not in seen:
            seen.add(h)
            out.append((h, str(b.get("reason") or "")[:80]))
    return out


def judge(host, code, data, stderr):
    """{"status": ok | unusable | interrupted | defect, "reason"} of one run."""
    if code < 0 or code >= 128:
        return {"status": "interrupted", "reason": "s2v capture was interrupted (%s)" % (
            "signal %d" % -code if code < 0 else "exit %d" % code)}
    if code == 1:
        return {"status": "unusable", "reason": _last_line(stderr) or "s2v capture could not capture the page"}
    if code != 0:
        return {"status": "defect", "reason": "s2v capture refused Studio's call (exit %d: %s) — a Studio defect, "
                                              "report it" % (code, _last_line(stderr) or "no message")}
    if data is None or not isinstance(data.get("url"), str):
        return {"status": "defect", "reason": "s2v capture wrote no readable JSON — a Studio defect, report it"}
    try:
        u = urlsplit(data["url"])
        final = (u.hostname or "").lower()
        plain = u.port is None and u.username is None and u.password is None
    except ValueError:
        u, final, plain = None, "", False
    if u is None or u.scheme != "https" or final != host or not plain:
        return {"status": "unusable", "reason": "the page moved to %s (another address than the asked host %s) — "
                                                "capture the final address" % (final or "an unreadable address", host)}
    return {"status": "ok", "reason": None}


def capture(s2v_path, url, host, out_png, text_json, env, cwd, runner=None, assets_dir=None, selector=None,
            width=None, height=None, allow=(), page=False):
    """Run s2v capture (twice at most for a page) and judge it: a dict with `status`, `reason`, `data` (JSON_KEYS of
    the last run), `attempts`, `warnings`, `blocked` [(host, reason)]."""
    runner = runner or run
    attempts, timeout = 0, TIMEOUT
    while True:
        attempts += 1
        argv = argv_for(s2v_path, url, out_png, text_json, assets_dir, selector, width, height, timeout, allow)
        code, _out, err = runner(argv, env, cwd)
        data = read_json(text_json)
        res = judge(host, code, data, err)
        res.update(data=data, attempts=attempts, warnings=[], blocked=blocked_hosts(data))
        if res["status"] != "ok":
            return res
        if data.get("idle") is not False:
            break
        if not page:
            res["warnings"].append("the page did not settle within %d s (idle: false): look at the picture before "
                                   "it is used" % timeout)
            return res
        if timeout == RETRY_TIMEOUT:
            res.update(status="unusable", reason="the page did not settle within %d s twice (idle: false): "
                                                 "unreachable" % RETRY_TIMEOUT)
            return res
        timeout = RETRY_TIMEOUT
    if page and not data.get("contentHash"):
        res.update(status="unusable", reason="s2v found no content to hash (contentHash: null): unreachable")
    return res
