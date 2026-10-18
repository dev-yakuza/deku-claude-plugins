#!/usr/bin/env python3
"""Search Console metrics: gsc.py collect [--days 28] | gsc.py show [--slug S]"""
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
ap.add_argument("--slug", help="show: only this article's rows (every language)")
a = ap.parse_args()
try:
    root = repo_root()
    cfg = Config.load_checked(root)
    if a.action == "collect":
        emit(gsc.collect(root, cfg, a.days))
    else:
        data = gsc.cached(root)
        if a.slug and isinstance(data, dict):  # the data's age stays: it weighs a refresh judgment
            data = dict(data, articles=[r for r in data.get("articles") or [] if r.get("slug") == a.slug])
        emit(data)
except HeraldError as e:
    sys.stderr.write("gsc: %s\n" % e)
    sys.exit(1)
