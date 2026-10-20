#!/usr/bin/env python3
"""Runs stdo.state.cli.main in its own process with test injections:

    state_driver.py [--kill after_log|before_replace] [--inspect FILE] -- <state.py args…>

--kill: SIGKILL this process at that point of a write (m0b1-plan R13);
--inspect: the inspect JSON to use instead of running s2v."""
import json
import os
import signal
import sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "..", "skills", "std", "scripts")))
from stdo.state import cli, store  # noqa: E402
from stdo.state.collect import Providers  # noqa: E402

argv = sys.argv[1:]
i = argv.index("--")
opts, rest = argv[:i], argv[i + 1:]
hooks = {}
if "--kill" in opts:
    at = opts[opts.index("--kill") + 1]
    hooks[at] = lambda: os.kill(os.getpid(), signal.SIGKILL)
providers = None
if "--inspect" in opts:
    with open(opts[opts.index("--inspect") + 1]) as f:
        data = json.load(f)
    providers = Providers(inspect=lambda ctx: data, source=lambda ctx, st: ("src1", ""))
store.enable_writes()
sys.exit(cli.main(rest, providers=providers, hooks=hooks))
