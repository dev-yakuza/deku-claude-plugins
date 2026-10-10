#!/usr/bin/env python3
"""PreToolUse hook entry (plan §3.4). Wired by init in .claude/settings.json."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hrdlib.guard import main  # noqa: E402

main()
