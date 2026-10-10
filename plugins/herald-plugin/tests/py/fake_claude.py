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
def git(*args):
    subprocess.run(["git", *args], check=True, capture_output=True)


def start_branch(slug):
    """Like write.md: work/<id>/state.json is created on base, then the branch."""
    os.makedirs(".claude/herald/work/%s" % tid, exist_ok=True)
    json.dump({"topic_id": tid, "slug": slug, "stage": "draft", "stages": {}}, open(".claude/herald/work/%s/state.json" % tid, "w"))
    git("switch", "-q", "-c", "herald/%s--%s" % (tid, slug))
    os.makedirs("src/content/blog", exist_ok=True)
    open("src/content/blog/%s.md" % slug, "w").write("draft body")


if prompt.startswith("/hrd ship --auto"):
    # simulate GitHub merging the PRs (origin advances), then the child's own fast-forward sync
    st = os.environ["HRD_FAKE_GH_STATE"]
    data = json.load(open(st))
    nums = [int(n) for n in os.environ.get("HRD_AUTO_PRS", "").split()]
    other = os.environ["HRD_FAKE_OTHER_CLONE"]
    subprocess.run(["git", "-C", other, "pull", "-q"], check=True)
    open(os.path.join(other, "merged-%s.txt" % "-".join(map(str, nums))), "w").write("m")
    subprocess.run(["git", "-C", other, "add", "-A"], check=True)
    subprocess.run(["git", "-C", other, "commit", "-qm", "squash merge"], check=True)
    subprocess.run(["git", "-C", other, "push", "-q"], check=True)
    for pr in data["prs"]:
        if pr["number"] in nums:
            pr["state"], pr["mergedAt"] = "MERGED", "2099-01-01T00:00:00Z"
    json.dump(data, open(st, "w"))
    r = subprocess.run([sys.executable, os.path.join(scripts, "hrd.py"), "sync"], capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
        sys.exit(1)
    subprocess.run([sys.executable, os.path.join(scripts, "hrd.py"), "result", "--topic", "ship", "--status", "merged",
                    "--merged", *map(str, nums)], check=True)
    sys.exit(0)
if action == "branch-budget":
    start_branch("post-" + tid)
    usage = {"input_tokens": 10_000_000, "output_tokens": 0}
    print(json.dumps({"type": "assistant", "message": {"id": "m1", "model": "sonnet", "usage": usage}}), flush=True)
    time.sleep(120)
elif action == "branch-nothing":
    start_branch("post-" + tid)
elif action == "branch-rejected-sloppy":
    # a child that switches back without cleaning (untracked body follows) and deletes its branch
    start_branch("post-" + tid)
    git("switch", "-q", "main")
    git("branch", "-q", "-D", "herald/%s--post-%s" % (tid, tid))
    subprocess.run([sys.executable, os.path.join(scripts, "hrd.py"), "result", "--topic", tid,
                    "--status", "held:rejected", "--note", "fake"], check=True)
elif action.startswith("held:"):
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
