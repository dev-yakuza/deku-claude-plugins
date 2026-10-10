#!/usr/bin/env python3
"""Per-article tokens and dollars (plan §3.7): measure.py [--session ID] [--file F ...]"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hrdlib.config import Config  # noqa: E402
from hrdlib.measure import measure  # noqa: E402
from hrdlib.util import emit, repo_root  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--session")
ap.add_argument("--file", action="append")
a = ap.parse_args()
root = repo_root()
cfg = Config.load(root, required=False)
emit(measure(root, cfg.get("models", "prices") or {}, session=a.session, files=a.file))
