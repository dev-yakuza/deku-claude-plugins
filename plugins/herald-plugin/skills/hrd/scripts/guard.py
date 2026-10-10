#!/usr/bin/env python3
"""PreToolUse hook entry (plan §3.4). Wired by init in .claude/settings.json."""
import os
import sys

sys.dont_write_bytecode = True  # no __pycache__ in the repo's .claude/herald/scripts

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hrdlib.guard import main  # noqa: E402

main()
