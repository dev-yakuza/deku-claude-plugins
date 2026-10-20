#!/usr/bin/env python3
"""Runs stdo.lockcli.main in its own process with test injections (no flag file, no env switch):

    lock_driver.py --as tts|gen|actor [--hook after-acquire|after-spawn] [--drop-got] -- <lock.py args…>

--as: the lock kind the (fake) child is taken to need; --hook: send SIGTERM to this process at
that point (the signal windows of m0c-plan §14 m5)."""
import os
import signal
import sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "..", "skills", "std", "scripts")))
from stdo import lockcli  # noqa: E402

argv = sys.argv[1:]
i = argv.index("--")
opts, rest = argv[:i], argv[i + 1:]
kind = opts[opts.index("--as") + 1]
hook = opts[opts.index("--hook") + 1] if "--hook" in opts else None
hooks = {}
term_self = lambda: os.kill(os.getpid(), signal.SIGTERM)  # noqa: E731
if hook == "after-acquire":
    hooks["after_acquire"] = term_self
elif hook == "after-spawn":
    hooks["after_spawn"] = lambda pgid: term_self()
if "--drop-got" in opts:
    hooks["keep_status"] = lambda line: not line.startswith("got ")
seen = []
hooks["status_line"] = seen.append
code = lockcli.main(rest, child_kind=lambda a, p, c: kind, hooks=hooks)
sys.stderr.write("driver-status: %s\n" % "|".join(seen))
sys.exit(code)
