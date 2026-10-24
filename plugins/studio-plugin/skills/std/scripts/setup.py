#!/usr/bin/env python3
"""Install and maintain Studio's harness: init · config · update (m1-plan §5). Plugin-only: it runs from the plugin,
never from a repository's copy. See stdo/setup/cli.py."""
import os
import sys

sys.dont_write_bytecode = True

if sys.version_info < (3, 9):
    sys.stderr.write("std setup: Python 3.9 or newer is needed\n")
    sys.exit(2)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stdo.setup.cli import entry  # noqa: E402

sys.exit(entry())
