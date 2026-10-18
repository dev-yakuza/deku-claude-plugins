#!/usr/bin/env python3
"""Per-article tokens and dollars: measure.py [--session ID] [--file F ...] [--detail] [--transcript-dir D] [--prices JSON]"""
import argparse
import json
import os
import sys

sys.dont_write_bytecode = True  # no __pycache__ in the repo's .claude/herald/scripts

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hrdlib.config import Config  # noqa: E402
from hrdlib.measure import measure  # noqa: E402
from hrdlib.util import emit, repo_root  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--session")
ap.add_argument("--file", action="append")
ap.add_argument("--detail", action="store_true", help="where the main session's context came from, per source")
ap.add_argument("--transcript-dir", help="a project transcript directory (no repo needed)")
ap.add_argument("--prices", help='JSON, e.g. {"opus": 5, "sonnet": 3, "haiku": 1} (USD per 1M input tokens)')
a = ap.parse_args()
if a.transcript_dir:
    root, prices = None, {}
else:
    root = repo_root()
    prices = Config.load(root, required=False).get("models", "prices") or {}
if a.prices:
    prices = json.loads(a.prices)
out = measure(root, prices, session=a.session, files=a.file, detail=a.detail, transcript_dir=a.transcript_dir)
if a.detail:
    out.setdefault("detail", {})["prices"] = prices
emit(out)
