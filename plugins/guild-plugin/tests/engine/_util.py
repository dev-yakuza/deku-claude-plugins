"""Shared helpers for the K0 engine tests (stdlib unittest; run by tests/engine_k0_test.sh)."""

import json
import os
import shutil
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
PLUGIN = os.path.dirname(TESTS)
SKILL = os.path.join(PLUGIN, "skills", "gld")
ENGINE = os.path.join(SKILL, "engine")
FX = os.path.join(TESTS, "fixtures", "engine")
RECORDS = os.path.join(FX, "records")
GH_STATUS = os.path.join(FX, "gh", "status.json")

if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

# No test may reach GitHub: a `gh` that always fails goes first on PATH (subprocesses inherit it).
_NOGH = os.path.join(os.environ.get("TMPDIR", "/tmp"), "guild-engine-k0-nogh")
os.makedirs(_NOGH, exist_ok=True)
with open(os.path.join(_NOGH, "gh"), "w") as _fh:
    _fh.write("#!/bin/sh\necho 'gh is blocked in engine tests (use GLD_ENGINE_GH_FIXTURE)' >&2\nexit 97\n")
os.chmod(os.path.join(_NOGH, "gh"), 0o755)
if not os.environ.get("PATH", "").startswith(_NOGH + os.pathsep):
    os.environ["PATH"] = _NOGH + os.pathsep + os.environ.get("PATH", "")


def read(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return fh.read()


def record(rel):
    return read(os.path.join(RECORDS, rel))


def records_of(kind):
    """[(version, name, path)] of every golden file of one record kind."""
    out = []
    base = os.path.join(RECORDS, kind)
    for ver in sorted(os.listdir(base)):
        for fn in sorted(os.listdir(os.path.join(base, ver))):
            out.append((ver, fn, os.path.join(base, ver, fn)))
    return out


def fixture(path=GH_STATUS):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def comment(body, cid=1, at="2026-11-15T00:00:00Z", assoc="OWNER", login="owner"):
    return {"id": cid, "body": body, "created_at": at, "updated_at": at,
            "author_association": assoc, "user": {"login": login}}


JQ = shutil.which("jq")


def need_jq(case):
    """A missing jq is a skip only when GLD_ALLOW_SKIP=1 — skipping is never passing."""
    if JQ:
        return
    if os.environ.get("GLD_ALLOW_SKIP") == "1":
        raise unittest.SkipTest("jq not installed")
    case.fail("jq is required for the consumer-contract tests (GLD_ALLOW_SKIP=1 to skip)")


def jq(filter_, data, raw=True, slurp=False, extra=()):
    argv = [JQ, "-c"] + (["-r"] if raw else []) + (["-s"] if slurp else []) + list(extra) + [filter_]
    p = subprocess.run(argv, input=(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)).encode("utf-8"),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        raise AssertionError("jq failed: %s" % p.stderr.decode("utf-8", "replace"))
    return p.stdout.decode("utf-8")


def bash(script, stdin=""):
    p = subprocess.run(["bash", "-c", script], input=stdin.encode("utf-8"),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return p.returncode, p.stdout.decode("utf-8"), p.stderr.decode("utf-8")
