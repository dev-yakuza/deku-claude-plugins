#!/usr/bin/env python3
"""Lock race driver (Python side): race_py.py LOCK BARRIER LOG LOOPS HOLD_MS
Waits for the barrier file, then LOOPS times: take the lock (retry every 25 ms, 60 s budget),
log `enter`, hold, log `exit … stillmine=…`, release; `result <status>` each time."""
import os
import sys
import time

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "..", "skills", "std", "scripts")))
from stdo import dirlock  # noqa: E402

lock, barrier, log, loops, hold = sys.argv[1:6]
start = dirlock.proc_start(os.getpid())


def note(line):
    with open(log, "a") as f:
        f.write(line + "\n")


note("ready py%d" % os.getpid())
while not os.path.exists(barrier):
    time.sleep(0.002)
deadline = time.time() + 60
for _ in range(int(loops)):
    while True:
        r = dirlock.acquire(lock, {"kind": "tts", "pid": os.getpid(), "pid_start": start, "holder": "race-py"})
        if int(loops) == 1 or r.status == "acquired" or time.time() > deadline:
            break
        time.sleep(0.025)
    if r.status == "acquired":
        note("enter py%d" % os.getpid())
        time.sleep(int(hold) / 1000.0)
        o = dirlock.read_owner(lock)
        note("exit py%d stillmine=%s" % (os.getpid(), bool(o and o.get("token") == r.token)))
        dirlock.release(lock, r.token)
    note("result py%d %s" % (os.getpid(), r.status))
