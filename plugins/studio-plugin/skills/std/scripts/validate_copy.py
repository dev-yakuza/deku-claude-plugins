#!/usr/bin/env python3
"""The platform copy check (m1-plan §10). See stdo/distribute/cli.py."""
import os
import sys

sys.dont_write_bytecode = True  # no __pycache__ in the repository's .claude/studio/scripts

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stdo.distribute.cli import entry  # noqa: E402

sys.exit(entry())
