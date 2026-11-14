#!/usr/bin/env python3
"""Runs guard.py's main with a short process deadline and one slow step patched in (fix-0103 §4,
test_guard_regex.HookDeadline). Test tree only: the production code has no switch for this.

    guard_deadline.py <scenario> <deadline seconds>     (the hook input on stdin, as guard.py)

Scenarios: none, g1_sleep, g1_sleep_slow_deny, big_input_slow_deny, legacy_sleep, record_sleep, swallow_once,
arm_raises. Each sleep is SLEEP seconds, longer than the deadline the tests pass."""

import importlib.util
import os
import sys
import time

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.normpath(os.path.join(HERE, "..", "..", "..", "skills", "std", "scripts"))
SLEEP = 5.0
sys.path.insert(0, SCRIPTS)

from stdo.guard import backstop, judge, limits  # noqa: E402


def load_guard():
    spec = importlib.util.spec_from_file_location("studio_guard_entry", os.path.join(SCRIPTS, "guard.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def slow(fn, before=SLEEP):
    def w(*a, **kw):
        time.sleep(before)
        return fn(*a, **kw)
    return w


def main(argv):
    scenario, deadline = argv[0], float(argv[1])
    guard = load_guard()
    limits.HOOK_DEADLINE = deadline
    if scenario in ("g1_sleep", "g1_sleep_slow_deny"):
        judge.decide_g1 = slow(judge.decide_g1)
        if scenario == "g1_sleep_slow_deny":
            guard._deny = slow(guard._deny, 0.3)  # longer than limits.HOOK_REFIRE
    elif scenario == "big_input_slow_deny":
        guard.MAX_INPUT = 8
        guard._deny = slow(guard._deny)
    elif scenario == "legacy_sleep":
        orig = backstop._legacy

        def legacy():
            lj, dec = orig()
            return [lj, slow(dec)]
        backstop._legacy = legacy
    elif scenario == "record_sleep":
        judge.record_run = slow(judge.record_run)
    elif scenario == "swallow_once":
        orig_g1 = judge.decide_g1

        def swallowing(*a, **kw):
            try:
                time.sleep(SLEEP)
            except BaseException:  # noqa: BLE001 — what a careless check might do
                sys.stderr.write("swallowed\n")
            time.sleep(2.0)  # keeps running well past one re-fire interval
            return orig_g1(*a, **kw)
        judge.decide_g1 = swallowing
    elif scenario == "arm_raises":
        def arm():
            sys.stderr.write("arm raised\n")
            raise OSError("no timer")
        limits.arm = arm
    elif scenario != "none":
        raise SystemExit("unknown scenario: %s" % scenario)
    return guard.main()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
