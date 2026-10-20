#!/usr/bin/env python3
"""A fake s2v child for lock.py process tests. Writes JSON lines to --log:
start (pid, pgid, sid, open fds, tokens, S2V_NO_OPEN, stdin read result), each signal, exit.

    fake_s2v.py --log F [--sleep S] [--exit K] [--on-signal exit128|exit:K|slow:S|ignore]
                [--grandchild S] [--ready F]
"""
import json
import os
import signal
import subprocess
import sys
import time

sys.dont_write_bytecode = True
args = sys.argv[1:]


def opt(name, default=None):
    return args[args.index(name) + 1] if name in args else default


LOG = opt("--log")
SLEEP = float(opt("--sleep", "0"))
EXIT = int(opt("--exit", "0"))
ON = opt("--on-signal", "exit128")
GRAND = opt("--grandchild")


def log(**kw):
    with open(LOG, "a") as f:
        f.write(json.dumps(kw) + "\n")


def on_signal(signum, frame):
    log(event="signal", sig=signum)
    if ON == "ignore":
        return
    if ON.startswith("slow:"):  # a graceful clean-up that takes a while (s2v stopping servers)
        time.sleep(float(ON.split(":", 1)[1]))
        log(event="graceful", sig=signum)
        os._exit(128 + signum)
    if ON.startswith("exit:"):
        os._exit(int(ON.split(":", 1)[1]))
    os._exit(128 + signum)


for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
    signal.signal(s, on_signal)
fds = sorted(int(f) for f in os.listdir("/dev/fd") if f.isdigit())
stdin = sys.stdin.read() if not sys.stdin.isatty() else None
log(event="start", pid=os.getpid(), pgid=os.getpgid(0), sid=os.getsid(0), fds=fds,
    heavy=os.environ.get("S2V_HEAVY_LOCK_TOKEN"), actor=os.environ.get("S2V_ACTOR_LOCK_TOKEN"),
    no_open=os.environ.get("S2V_NO_OPEN"), stdin=stdin)
if GRAND:
    g = subprocess.Popen([sys.executable, "-B", "-c",
                          "import signal,time; [signal.signal(s, signal.SIG_IGN) for s in (1,2,15)]; time.sleep(%s)" % GRAND],
                         stdin=subprocess.DEVNULL)
    log(event="grandchild", pid=g.pid)
if opt("--ready"):
    open(opt("--ready"), "w").close()
end = time.time() + SLEEP
while time.time() < end:
    time.sleep(0.02)
log(event="exit", code=EXIT)
sys.exit(EXIT)
