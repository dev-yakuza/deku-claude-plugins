#!/usr/bin/env python3
"""A video's state, hashes and the router (plan §3.2). See stdo/state/cli.py for the commands."""
import os
import sys

sys.dont_write_bytecode = True  # no __pycache__ in the repository's .claude/studio/scripts

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stdo.state import store  # noqa: E402
from stdo.state.cli import main  # noqa: E402

store.enable_writes()  # writes run only from this entry point (and the test driver)
sys.exit(main(sys.argv[1:]))
