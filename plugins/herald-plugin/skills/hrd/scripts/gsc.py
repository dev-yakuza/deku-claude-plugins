#!/usr/bin/env python3
"""Search Console metrics (plan M5): gsc.py collect [--days 28] | gsc.py show"""
import argparse
import os
import sys

sys.dont_write_bytecode = True  # no __pycache__ in the repo's .claude/herald/scripts

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hrdlib import gsc  # noqa: E402
from hrdlib.config import Config  # noqa: E402
from hrdlib.util import HeraldError, emit, repo_root  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("action", choices=["collect", "show"])
ap.add_argument("--days", type=int, default=28)
a = ap.parse_args()
try:
    root = repo_root()
    cfg = Config.load(root)
    emit(gsc.collect(root, cfg, a.days) if a.action == "collect" else gsc.cached(root))
except HeraldError as e:
    sys.stderr.write("gsc: %s\n" % e)
    sys.exit(1)
