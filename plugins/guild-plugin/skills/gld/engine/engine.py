#!/usr/bin/env -S python3 -I
"""guild-plugin engine entry point. Run as `python3 -I <this file> <command> …` (gxengine/cli.py).

`-I` keeps the current directory and PYTHON* variables out of the import path, so this
file puts its own directory (the plugin install path) first — never the worktree.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

from gxengine import cli  # noqa: E402

if __name__ == "__main__":
    sys.exit(cli.main(sys.argv[1:]))
