#!/usr/bin/env python3
"""The script and verify checks (m1-plan §7.3 · §7.4). See stdo/claims/cli.py."""
import os
import sys

sys.dont_write_bytecode = True  # no __pycache__ in the repository's .claude/studio/scripts

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stdo.claims.cli import entry  # noqa: E402

sys.exit(entry())
