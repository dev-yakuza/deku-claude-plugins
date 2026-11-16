#!/usr/bin/env python3
"""A web page through s2v capture, as Studio runs it (m2-plan §5.1). See stdo/capture/cli.py."""
import os
import sys

sys.dont_write_bytecode = True  # no __pycache__ in the repository's .claude/studio/scripts

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stdo.capture.cli import entry  # noqa: E402

sys.exit(entry())
