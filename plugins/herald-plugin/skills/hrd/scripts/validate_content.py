#!/usr/bin/env python3
"""Deterministic content gate (plan §3.5): validate_content.py <article file>"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hrdlib.config import Config  # noqa: E402
from hrdlib.util import emit, repo_root  # noqa: E402
from hrdlib.validate import validate  # noqa: E402

if len(sys.argv) != 2:
    sys.stderr.write("usage: validate_content.py <file>\n")
    sys.exit(2)
root = repo_root()
rep = validate(root, Config.load(root), sys.argv[1])
emit(rep)
sys.exit(0 if rep["ok"] else 1)
