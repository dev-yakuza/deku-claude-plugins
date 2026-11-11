#!/usr/bin/env python3
"""A stand-in for limner's `lmn` (design/herald/08-images.md §5, 09-scenes.md §5): `--version`,
`doctor --json`, `rasterize`, `compose`, and the generator's `run` (with `--check`), `status` and
`cancel` with limner's result JSON, records and exit codes. What it does is read from environment
variables; every call is logged to $FAKE_LMN_DIR/calls.jsonl, and `doctor` leaves
$FAKE_LMN_DIR/doctor-called.

FAKE_LMN_VERSION (0.1.0) · FAKE_LMN_CONTRACT (1) · FAKE_LMN_FONTS=missing · FAKE_LMN_EXIT (for
rasterize/compose, never the probe) · FAKE_LMN_PROBLEMS (JSON list, with exit 4) ·
FAKE_LMN_RAW (stdout as given) · FAKE_LMN_SLEEP (seconds) · FAKE_LMN_BADSHA=1 · FAKE_LMN_ERROR.

The generator (no worker process: the "worker" moves on each `status` call; runs live in
$FAKE_LMN_DIR/runs.json, records and outputs where limner writes them):
FAKE_LMN_GEN_ENV (`run --check`/`run` exit 2 with this error — models missing, RAM) ·
FAKE_LMN_RUN_EXIT (73 busy — the attempt is kept, closed `busy`, as limner does; 70, 2, 1 — `run`
without `--check`) · FAKE_LMN_STATUS (a sequence per
run, e.g. `10,10,0`: 10 = still running, 12 = no such run, anything else = the attempt ends) ·
FAKE_LMN_PER_POLL (jobs finished per running poll, 0) · FAKE_LMN_FAIL (JSON list of
{"id", "reason", "message"} for the attempt's `failed`; consumed by the first attempt only unless
FAKE_LMN_FAIL_ALWAYS=1) · FAKE_LMN_STATE (the ended attempt's state: crashed, cancelled,
orphan_child, busy) · FAKE_LMN_RECORD (JSON merged into each record) · FAKE_LMN_LOCK (part of
job_sha: change it and finished jobs are regenerated) · FAKE_LMN_CANCEL_EXIT=10 (a cancel that
does not stop in time).
"""
import hashlib
import json
import os
import struct
import sys
import time
import zlib

D = os.environ.get("FAKE_LMN_DIR") or os.path.dirname(os.path.abspath(__file__))
args = sys.argv[1:]
with open(os.path.join(D, "calls.jsonl"), "a") as f:
    f.write(json.dumps(args) + "\n")
sys.stderr.write("SECRET-STDERR /Users/someone/private\n")
CONTRACT = int(os.environ.get("FAKE_LMN_CONTRACT", "1"))


def emit(obj, code=0):
    raw = os.environ.get("FAKE_LMN_RAW")
    sys.stdout.write(raw if raw is not None else json.dumps(obj) + "\n")
    sys.exit(code)


def opt(name):
    return args[args.index(name) + 1] if name in args else None


def png(seed):
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    px = hashlib.sha256(seed.encode()).digest()[:3]
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00" + px + px)) + chunk(b"IEND", b""))


# --- the generator (limner 01 §6): run / status / cancel ------------------------------------

LISTS = ("done", "skipped", "adopted", "regenerated", "modified", "untracked", "failed", "blocked", "accepted",
         "pending")
LIVE = ("starting", "running")
QUANT = {"name": "qwen-image-edit-2511-q4", "revision": "6f3ccc0b56e431dc6a0c2b2039706d7d26f22cb9", "bits": 4}
LORA = {"name": "qwen-image-edit-2511-lightning", "revision": "d74eba145674fd7e31b949324e148e21e7118abd",
        "file": "Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors"}


def canonical(o):
    return json.dumps(o, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def runs_path():
    return os.path.join(D, "runs.json")


def load_runs():
    try:
        return json.load(open(runs_path()))
    except (OSError, ValueError):
        return {}


def save_runs(r):
    json.dump(r, open(runs_path(), "w"))


def sha_file(p):
    try:
        return hashlib.sha256(open(p, "rb").read()).hexdigest()
    except OSError:
        return None


def job_sha(j):
    return hashlib.sha256(canonical([j["prompt"], j["width"], j["height"], j["seed"], j.get("refs") or [],
                                     os.environ.get("FAKE_LMN_LOCK", "lock1")]).encode()).hexdigest()


def new_status(run_id, attempt, state, **kw):
    st = {"contract": CONTRACT, "run_id": run_id, "attempt": attempt, "state": state, "stage": None, "stages": 1,
          "current": None}
    for k in LISTS:
        st[k] = []
    st.update({"generator": os.environ.get("FAKE_LMN_GENERATOR", "mflux"), "free_gib_at_start": 30.1,
               "warnings": [], "busy": None})
    st.update(kw)
    return st


def exit_code(st):
    """limner's result.exit_code: 70 > 2 > 73 > 11 > 5 > 0."""
    if st["state"] in LIVE:
        return 10
    failed = st.get("failed") or []
    if any(f.get("reason") == "environment" for f in failed):
        return 2
    if st["state"] == "busy":
        return 73
    if st["state"] in ("crashed", "cancelled", "orphan_child", "failed") or failed or st.get("pending"):
        return 11
    if st.get("modified") or st.get("untracked"):
        return 5
    return 0


def decide(root, sd, j):
    """limner plan.decide, read-only: generate | skipped | untracked | modified (+ reason, adoptable)."""
    out = os.path.join(root, j["out"])
    if not os.path.isfile(out):
        return "generate", None
    rp = os.path.join(sd, "records", j["out"] + ".json")
    try:
        rec = json.load(open(rp))
    except (OSError, ValueError):
        rec = None
    cur = sha_file(out)
    if rec is None:
        for name in sorted(os.listdir(os.path.join(sd, "tmp"))) if os.path.isdir(os.path.join(sd, "tmp")) else []:
            try:
                r = json.load(open(os.path.join(sd, "tmp", name)))
            except (OSError, ValueError):
                continue
            if name.endswith(".record.json") and r.get("out") == j["out"] and r.get("out_sha256") == cur:
                return ("skipped" if r.get("job_sha") == job_sha(j) else "generate"), "adopt"
        return "untracked", None
    if rec.get("kind") != "generate" or rec.get("out_sha256") != cur:
        return "modified", None
    if rec.get("job_sha") == job_sha(j):
        return "skipped", None
    return "generate", "job_changed"


def make(root, sd, j, st, reason):
    """The worker's commit: the PNG over out (the old one into prev/), then the record."""
    out = os.path.join(root, j["out"])
    rp = os.path.join(sd, "records", j["out"] + ".json")
    prev = None
    if os.path.exists(out):
        prev = os.path.join(sd, "prev", j["out"][:-4] + ".1.png")
        os.makedirs(os.path.dirname(prev), exist_ok=True)
        os.replace(out, prev)
    data = png(canonical([j["prompt"], j["width"], j["height"], j["seed"], os.environ.get("FAKE_LMN_LOCK", "lock1")]))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, "wb").write(data)
    rec = {"limner": "0.1.0", "contract": CONTRACT, "kind": "generate",
           "generator": os.environ.get("FAKE_LMN_GENERATOR", "mflux"), "mflux": "0.18.0", "mlx": "0.32.3",
           "machine": "fake", "model": dict(QUANT), "lora": dict(LORA), "model_license": "Apache-2.0", "steps": 8,
           "guidance": 1.0, "multi_ref": "picture_prefix", "skip_negative": True, "width": j["width"],
           "height": j["height"], "seed": j["seed"], "prompt": j["prompt"], "refs": [], "blank": "#E0E0E0",
           "letterbox": 1, "out_sha256": hashlib.sha256(data).hexdigest(), "job_sha": job_sha(j),
           "started_at": "2026-11-11T00:00:00Z", "seconds": 135.2, "peak_gb": 20.7,
           "out": j["out"], "prev": os.path.relpath(prev, root) if prev else None}
    rec.update(json.loads(os.environ.get("FAKE_LMN_RECORD") or "{}"))
    os.makedirs(os.path.dirname(rp), exist_ok=True)
    json.dump(rec, open(rp, "w"))
    st["done"].append({"id": j["id"], "out": j["out"], "out_sha256": hashlib.sha256(data).hexdigest(), "record": rp,
                       "seconds": 135.2})
    if reason == "job_changed":
        st["regenerated"].append({"id": j["id"], "reason": reason, "prev": os.path.relpath(prev, root) if prev else None})
    st["pending"].remove(j["id"])


def adopt(root, sd, j):
    tdir = os.path.join(sd, "tmp")
    for name in sorted(os.listdir(tdir)) if os.path.isdir(tdir) else []:
        p = os.path.join(tdir, name)
        try:
            r = json.load(open(p))
        except (OSError, ValueError):
            continue
        if name.endswith(".record.json") and r.get("out") == j["out"]:
            rp = os.path.join(sd, "records", j["out"] + ".json")
            os.makedirs(os.path.dirname(rp), exist_ok=True)
            os.replace(p, rp)
            return True
    return False


def advance(run, final):
    """The worker moves on: running polls finish FAKE_LMN_PER_POLL jobs, the final one the rest."""
    st, root, sd = run["status"], run["root"], run["state_dir"]
    jobs = {j["id"]: j for j in run["jobs"]}
    if st["state"] == "starting":
        st["state"] = "running"
        st["stage"] = 1
        for jid in list(st["pending"]):  # stage start: judge every job (adoption included)
            d, why = decide(root, sd, jobs[jid])
            if why == "adopt":
                adopt(root, sd, jobs[jid])
                st["adopted"].append(jid)
                d, why = decide(root, sd, jobs[jid])
            if d != "generate":
                st[d].append(jid)
                st["pending"].remove(jid)
            else:
                run.setdefault("why", {})[jid] = why
    todo = [jid for jid in st["pending"]]
    n = len(todo) if final else int(os.environ.get("FAKE_LMN_PER_POLL", "0"))
    fail = {f["id"]: f for f in json.loads(os.environ.get("FAKE_LMN_FAIL") or "[]")} if run.get("fail") else {}
    if final and (None in fail or os.environ.get("FAKE_LMN_STATE")):
        n = 0  # the attempt stopped before the work (environment, crash, cancel, busy)
    for jid in todo[:n]:
        if jid in fail:
            st["failed"].append({"id": jid, "reason": fail[jid].get("reason", "error"),
                                 "message": fail[jid].get("message", "boom")})
            st["pending"].remove(jid)
            continue
        make(root, sd, jobs[jid], st, (run.get("why") or {}).get(jid))
    if None in fail and final:
        st["failed"].append({"id": None, "reason": fail[None].get("reason"), "message": fail[None].get("message")})
    if final:
        state = os.environ.get("FAKE_LMN_STATE")
        if state:
            st["state"] = state
            if state == "busy":
                st["busy"] = {"reason": "lock", "holder": "s2v tts server (pid 4242)"}
        else:
            st["state"] = "failed" if any(f.get("id") is None for f in st["failed"]) else "done"
        st["current"] = None
    else:
        st["current"] = st["pending"][0] if st["pending"] else None


def generator(cmd):
    runs = load_runs()
    root, sd = opt("--root"), opt("--state-dir")
    if cmd == "run":
        try:
            spec = json.load(open(opt("--job") if os.path.isabs(opt("--job")) else os.path.join(root, opt("--job"))))
        except (OSError, ValueError) as e:
            emit({"contract": CONTRACT, "error": "job file: %s" % e}, 2)
        if spec.get("model") != "qwen-image-edit-2511" or not spec.get("jobs"):
            emit({"contract": CONTRACT, "error": "job file: model must be 'qwen-image-edit-2511'"}, 2)
        for j in spec["jobs"]:
            if not (64 <= j["width"] <= 1024 and j["width"] % 16 == 0 and 64 <= j["height"] <= 1024
                    and j["height"] % 16 == 0 and 1 <= len(j["prompt"]) <= 1500):
                emit({"contract": CONTRACT, "error": "job %s: bad size or prompt" % j["id"]}, 2)
        if os.environ.get("FAKE_LMN_GEN_ENV"):
            emit({"contract": CONTRACT, "error": os.environ["FAKE_LMN_GEN_ENV"]}, 2)
        run_id = hashlib.sha256(canonical({"job": spec, "force": [], "accept": []}).encode()).hexdigest()[:16]
        if "--check" in args:
            emit({"contract": CONTRACT, "check": "ok", "run_id": run_id, "jobs": len(spec["jobs"]), "stages": 1})
        code = int(os.environ.get("FAKE_LMN_RUN_EXIT", "0"))
        if code and code != 73:
            emit({"contract": CONTRACT, "error": os.environ.get("FAKE_LMN_ERROR", "run failed")}, code)
        cur = runs.get(run_id)
        if cur and cur["status"]["state"] in LIVE:
            emit(cur["status"], 0)  # another `run` of this run_id is going: its attempt
        verdicts, work = {k: [] for k in LISTS}, False
        for j in spec["jobs"]:
            d, why = decide(root, sd, j)
            if d == "generate" or why == "adopt":
                work = True
            else:
                verdicts[d].append(j["id"])
        if not work:
            st = new_status(run_id, None, "done")
            st.update(verdicts)
            emit(st, exit_code(st))
        attempt = hashlib.sha256((run_id + str(len(runs)) + str(time.time())).encode()).hexdigest()[:16]
        sf = os.path.join(sd, "runs", run_id, "attempts", attempt, "status.json")
        os.makedirs(os.path.dirname(sf), exist_ok=True)
        if code == 73:  # the machine stays busy for --wait: limner closes the attempt `busy`, and it
            # stays the run's current attempt (a later cancel of this run answers 73)
            st = new_status(run_id, attempt, "busy", busy={"reason": "lock", "holder": "s2v tts server (pid 4242)"},
                            status_file=sf)
            st["pending"] = [j["id"] for j in spec["jobs"]]
            runs[run_id] = {"status": st, "jobs": spec["jobs"], "root": root, "state_dir": sd, "polls": 0,
                            "fail": False, "fail_used": True}
            save_runs(runs)
            emit(st, 73)
        st = new_status(run_id, attempt, "starting", status_file=sf)
        st["pending"] = [j["id"] for j in spec["jobs"]]
        first = not any(r.get("fail_used") for r in runs.values())
        runs[run_id] = {"status": st, "jobs": spec["jobs"], "root": root, "state_dir": sd, "polls": 0,
                        "fail": first or os.environ.get("FAKE_LMN_FAIL_ALWAYS") == "1", "fail_used": True}
        save_runs(runs)
        emit({"contract": CONTRACT, "run_id": run_id, "attempt": attempt, "state": "starting", "status_file": sf}, 0)
    rid = opt("--run-id")
    run = runs.get(rid)
    if cmd == "status":
        seq = (os.environ.get("FAKE_LMN_STATUS") or "0").split(",")
        n = run["polls"] if run else int(open(os.path.join(D, "polls-%s" % rid)).read()) \
            if os.path.exists(os.path.join(D, "polls-%s" % rid)) else 0
        step = seq[min(n, len(seq) - 1)].strip()
        if run:
            run["polls"] = n + 1
        else:
            open(os.path.join(D, "polls-%s" % rid), "w").write(str(n + 1))
        if step == "12" or not run:
            save_runs(runs)
            emit({"contract": CONTRACT, "error": "no run %s under %s" % (rid, sd)}, 12)
        if run["status"]["state"] in LIVE:
            advance(run, final=step != "10")
        save_runs(runs)
        emit(run["status"], exit_code(run["status"]))
    if cmd == "cancel":
        if not run:
            emit({"contract": CONTRACT, "error": "no run %s under %s" % (rid, sd)}, 12)
        st = run["status"]
        if st["state"] in LIVE:
            if os.environ.get("FAKE_LMN_CANCEL_EXIT") == "10":
                emit(st, 10)
            st["state"] = "cancelled"
            st["current"] = None
            save_runs(runs)
            emit(st, 0)
        emit(st, 0 if st["state"] == "cancelled" else exit_code(st))


if args == ["--version"]:
    emit({"contract": CONTRACT, "limner": os.environ.get("FAKE_LMN_VERSION", "0.1.0")})
if args[:1] == ["doctor"]:
    open(os.path.join(D, "doctor-called"), "w").write("1")
    emit({"contract": CONTRACT, "versions": {"limner": "0.1.0"},
          "fonts": {"pretendard": os.environ.get("FAKE_LMN_FONTS") != "missing"}})
cmd = args[0] if args else ""
if cmd in ("run", "status", "cancel"):
    generator(cmd)
if cmd not in ("rasterize", "compose"):
    emit({"contract": CONTRACT, "error": "unknown command"}, 2)
if os.environ.get("FAKE_LMN_FONTS") == "missing":
    emit({"contract": CONTRACT, "error": "fonts are missing — run `lmn fonts install`"}, 2)
out, root, sd = opt("--out"), opt("--root"), opt("--state-dir")
probe = "herald-probe" in out
if not probe and os.environ.get("FAKE_LMN_SLEEP"):
    time.sleep(float(os.environ["FAKE_LMN_SLEEP"]))
code = int(os.environ.get("FAKE_LMN_EXIT", "0")) if not probe else 0
if code not in (0, 4):
    emit({"contract": CONTRACT, "error": os.environ.get("FAKE_LMN_ERROR", "bad input")}, code)
if cmd == "rasterize":
    src = open(opt("--svg"), "rb").read()
    seed = hashlib.sha256(src).hexdigest() + str(opt("--width")) + str(opt("--background"))
else:
    seed = open(opt("--data"), encoding="utf-8").read()
data = png(seed)
rel = os.path.relpath(out, root)
rec_path = os.path.join(sd, "records", rel + ".json")
if os.path.exists(out) and os.path.exists(rec_path):
    prev = os.path.join(sd, "prev", rel)
    os.makedirs(os.path.dirname(prev), exist_ok=True)
    os.replace(out, prev)
os.makedirs(os.path.dirname(out), exist_ok=True)
open(out, "wb").write(data)
os.makedirs(os.path.dirname(rec_path), exist_ok=True)
json.dump({"kind": cmd, "out": rel}, open(rec_path, "w"))
if cmd == "rasterize":
    san = os.path.join(sd, "sanitized", rel[:-4] + ".svg")
    os.makedirs(os.path.dirname(san), exist_ok=True)
    open(san, "wb").write(src)
sha = hashlib.sha256(data).hexdigest()
if os.environ.get("FAKE_LMN_BADSHA") and not probe:
    sha = "0" * 64
problems = json.loads(os.environ.get("FAKE_LMN_PROBLEMS") or "[]") if code == 4 else []
emit({"contract": CONTRACT, "out": rel, "out_sha256": sha, "record": os.path.relpath(rec_path, root),
      "problems": problems}, 4 if problems else 0)
