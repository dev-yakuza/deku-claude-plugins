#!/usr/bin/env python3
"""Studio's pre-commit hook: install and check (plan §3.4; m0e-plan §3). See stdo/hooks/cli.py."""
import os
import sys

sys.dont_write_bytecode = True  # no __pycache__ in the repository's .claude/studio/scripts

if sys.version_info < (3, 9):
    sys.stderr.write("std hooks: Python 3.9 or newer is needed\n")
    sys.exit(2)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stdo.hooks.cli import main  # noqa: E402

sys.exit(main(sys.argv[1:]))
