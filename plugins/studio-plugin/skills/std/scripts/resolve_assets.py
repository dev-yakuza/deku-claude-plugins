#!/usr/bin/env python3
"""The source stage (m1-plan §6). See stdo/source/cli.py."""
import os
import sys

sys.dont_write_bytecode = True  # no __pycache__ in the repository's .claude/studio/scripts

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stdo.source.cli import resolve_entry  # noqa: E402

sys.exit(resolve_entry())
