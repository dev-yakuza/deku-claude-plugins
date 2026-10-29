#!/usr/bin/env python3
"""The voice section's checks (m1-plan §8). See stdo/voice/cli.py."""
import os
import sys

sys.dont_write_bytecode = True  # no __pycache__ in the repository's .claude/studio/scripts

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stdo.voice.cli import audition_entry  # noqa: E402

sys.exit(audition_entry())
