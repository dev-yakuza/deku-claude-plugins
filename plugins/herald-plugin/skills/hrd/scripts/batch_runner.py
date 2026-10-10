#!/usr/bin/env python3
"""`/hrd batch` runner (plan §3.2.1, §3.2.2): batch_runner.py --n N"""
import os
import sys

sys.dont_write_bytecode = True  # no __pycache__ in the repo's .claude/herald/scripts

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hrdlib.batch import main  # noqa: E402
from hrdlib.util import HeraldError  # noqa: E402

try:
    sys.exit(main(sys.argv[1:]))
except HeraldError as e:
    sys.stderr.write("batch: %s\n" % e)
    sys.exit(1)
