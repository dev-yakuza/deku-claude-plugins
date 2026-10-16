#!/usr/bin/env python3
"""Deterministic content gate (plan §3.5): validate_content.py <article file> [--lang <code>]"""
import os
import sys

sys.dont_write_bytecode = True  # no __pycache__ in the repo's .claude/herald/scripts

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hrdlib.config import Config  # noqa: E402
from hrdlib.util import emit, repo_root  # noqa: E402
from hrdlib.validate import validate  # noqa: E402

args = sys.argv[1:]
lang = None
if len(args) == 3 and args[1] == "--lang":
    lang, args = args[2], args[:1]
elif len(args) == 3 and args[0] == "--lang":
    lang, args = args[1], args[2:]
if len(args) != 1 or args[0].startswith("--"):
    sys.stderr.write("usage: validate_content.py <file> [--lang <code>]\n")
    sys.exit(2)
root = repo_root()
try:
    cfg = Config.load_checked(root)
except Exception as e:  # noqa: BLE001 — a malformed translations block fails the gate closed
    sys.stderr.write("validate_content: %s\n" % e)
    sys.exit(1)
# without --lang the file's path decides (a translation path → that language), so CI and
# wrappers that pass only the file still apply the right rules (01-multilingual.md §6)
rep = validate(root, cfg, args[0], lang=lang)
rep.pop("prose", None)  # readability hints come from `hrd.py gate`; keep this CLI's output to the gate verdict
emit(rep)
sys.exit(0 if rep["ok"] else 1)
