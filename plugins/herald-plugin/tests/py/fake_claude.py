#!/usr/bin/env python3
"""Fake `claude -p` for batch tests. Behaviour per topic from $HRD_FAKE_CLAUDE_PLAN (JSON):
{"t0001": "held:research" | "pr" | "budget" | "nothing"}."""
import json
import os
import subprocess
import sys
import time

prompt = sys.argv[-1]
plan = json.load(open(os.environ["HRD_FAKE_CLAUDE_PLAN"]))
parts = prompt.split()
tid = parts[-1] if len(parts) > 2 else None
action = plan.get(tid, "nothing") if tid else "nothing"
scripts = os.environ["HRD_SCRIPTS"]
# like write.md §0.3: a dirty tracked tree stops the child before it records anything
if subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], capture_output=True, text=True).stdout.strip():
    sys.exit(0)
if action.startswith("held:"):
    subprocess.run([sys.executable, os.path.join(scripts, "hrd.py"), "result", "--topic", tid,
                    "--status", action, "--note", "fake"], check=True)
elif action == "pr":
    st = os.environ["HRD_FAKE_GH_STATE"]
    data = json.load(open(st))
    n = 100 + len(data["prs"])
    data["prs"].append({"number": n, "state": "OPEN", "headRefName": "herald/%s--post-%s" % (tid, tid),
                        "labels": ["herald"]})
    json.dump(data, open(st, "w"))
    subprocess.run([sys.executable, os.path.join(scripts, "hrd.py"), "result", "--topic", tid,
                    "--status", "pr-open", "--pr", str(n)], check=True)
elif action == "budget":
    usage = {"input_tokens": 10_000_000, "output_tokens": 0}
    print(json.dumps({"type": "assistant", "message": {"id": "m1", "model": "sonnet", "usage": usage}}), flush=True)
    time.sleep(120)
sys.exit(0)
