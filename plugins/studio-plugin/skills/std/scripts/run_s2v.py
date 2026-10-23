#!/usr/bin/env python3
"""s2v's render and snapshot as Studio runs them (m1-plan §4.2). See stdo/s2vrun.py."""
import os
import sys

sys.dont_write_bytecode = True  # no __pycache__ in the repository's .claude/studio/scripts

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stdo.s2vrun import entry  # noqa: E402

sys.exit(entry())
