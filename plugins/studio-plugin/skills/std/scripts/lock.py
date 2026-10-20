#!/usr/bin/env python3
"""Run an s2v command under the machine lock or characters' work locks (plan §3.2b, §3.2c).

    python3 .claude/studio/scripts/lock.py run --kind tts|gen [--holder <text>] -- <s2v argv…>
    python3 .claude/studio/scripts/lock.py actor-op <id> [<id>…] -- <s2v argv…>
    python3 .claude/studio/scripts/lock.py status [--actor <id>]… [--json]
"""
import os
import sys

sys.dont_write_bytecode = True  # no __pycache__ in the repository's .claude/studio/scripts

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stdo.lockcli import main  # noqa: E402

sys.exit(main(sys.argv[1:]))
