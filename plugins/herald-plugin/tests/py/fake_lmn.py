#!/usr/bin/env python3
"""A stand-in for limner's `lmn` (design/herald/08-images.md §5): `--version`, `doctor --json`,
`rasterize` and `compose` with limner's result JSON and exit codes. What it does is read from
environment variables; every call is logged to $FAKE_LMN_DIR/calls.jsonl, and `doctor` leaves
$FAKE_LMN_DIR/doctor-called.

FAKE_LMN_VERSION (0.1.0) · FAKE_LMN_CONTRACT (1) · FAKE_LMN_FONTS=missing · FAKE_LMN_EXIT (for
rasterize/compose, never the probe) · FAKE_LMN_PROBLEMS (JSON list, with exit 4) ·
FAKE_LMN_RAW (stdout as given) · FAKE_LMN_SLEEP (seconds) · FAKE_LMN_BADSHA=1 · FAKE_LMN_ERROR.
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


if args == ["--version"]:
    emit({"contract": CONTRACT, "limner": os.environ.get("FAKE_LMN_VERSION", "0.1.0")})
if args[:1] == ["doctor"]:
    open(os.path.join(D, "doctor-called"), "w").write("1")
    emit({"contract": CONTRACT, "versions": {"limner": "0.1.0"},
          "fonts": {"pretendard": os.environ.get("FAKE_LMN_FONTS") != "missing"}})
cmd = args[0] if args else ""
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
