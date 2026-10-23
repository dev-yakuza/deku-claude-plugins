#!/usr/bin/env python3
"""Studio's commit checks (plan §3.4–3.5; m0e-plan). See stdo/commit/cli.py for the modes."""
import os
import sys

sys.dont_write_bytecode = True  # no __pycache__ in the repository's .claude/studio/scripts

if sys.version_info < (3, 9):
    sys.stderr.write("std check_commit: Python 3.9 or newer is needed\n")
    sys.exit(2)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stdo import writes  # noqa: E402
from stdo.commit.cli import main  # noqa: E402

writes.enable()  # commit-ok.json and the used-answer record (the hook) are written from this entry only

sys.exit(main(sys.argv[1:]))
