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
if isinstance(action, list):  # one action per attempt of this topic (a usage-limit restart, the retry)
    counter = os.environ["HRD_FAKE_CLAUDE_PLAN"] + ".%s.n" % tid
    k = int(open(counter).read()) if os.path.exists(counter) else 0
    open(counter, "w").write(str(k + 1))
    action = action[min(k, len(action) - 1)]
if os.environ.get("HRD_FAKE_CALLS"):
    with open(os.environ["HRD_FAKE_CALLS"], "a") as f:
        f.write(json.dumps({"prompt": prompt, "action": action,
                            "resume_limited": os.environ.get("HRD_RESUME_LIMITED"),
                            "clock": os.environ.get("HRD_BATCH_TEST_CLOCK"),
                            "branch": subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True,
                                                     text=True).stdout.strip()}) + "\n")
scripts = os.environ["HRD_SCRIPTS"]
# like write.md §0.3: a dirty tracked tree stops the child before it records anything
if subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], capture_output=True, text=True).stdout.strip():
    sys.exit(0)
def git(*args):
    subprocess.run(["git", *args], check=True, capture_output=True)


def start_branch(slug):
    """Like write.md: work/<id>/state.json is created on base, then the branch (resume: switch to it)."""
    if subprocess.run(["git", "rev-parse", "--verify", "-q", "herald/%s--%s" % (tid, slug)],
                      capture_output=True).returncode == 0:
        git("switch", "-q", "herald/%s--%s" % (tid, slug))
        open("src/content/blog/%s.md" % slug, "a").write(" more")
        return
    os.makedirs(".claude/herald/work/%s" % tid, exist_ok=True)
    json.dump({"topic_id": tid, "slug": slug, "stage": "draft", "stages": {}}, open(".claude/herald/work/%s/state.json" % tid, "w"))
    git("switch", "-q", "-c", "herald/%s--%s" % (tid, slug))
    os.makedirs("src/content/blog", exist_ok=True)
    open("src/content/blog/%s.md" % slug, "w").write("draft body")


def limit_out(text="Claude AI usage limit reached", status="rejected", reset=None):
    reset = reset if reset is not None else os.environ.get("HRD_FAKE_RESET_AT")
    info = {"status": status}
    if reset:
        info["resetsAt"] = int(reset)
    print(json.dumps({"type": "rate_limit_event", "rate_limit_info": info}), flush=True)
    print(json.dumps({"type": "result", "subtype": "success", "is_error": False,
                      "result": text + ("|%s" % reset if reset else "")}), flush=True)


if os.environ.get("HRD_FAKE_SPEND"):
    print(json.dumps({"type": "assistant", "message": {"id": "spend-%s" % time.time(), "model": "sonnet",
                                                       "usage": {"input_tokens": 1000, "output_tokens": 0}}}), flush=True)
if prompt.startswith("/hrd ship --auto") and os.environ.get("HRD_FAKE_SHIP_LIMIT"):
    limit_out()
    sys.exit(0)
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
if action == "limit-exit0":
    limit_out()
    sys.exit(0)
elif action == "limit-exit1":
    limit_out()
    sys.exit(1)
elif action == "branch-limit":
    start_branch("post-" + tid)
    limit_out()
    sys.exit(0)
elif action == "branch-limit-far":
    start_branch("post-" + tid)
    print(json.dumps({"type": "result", "subtype": "error_during_execution", "is_error": True,
                      "result": "Weekly limit reached · resets 3pm"}), flush=True)
    sys.exit(1)
elif action == "branch-limit-unknown":
    start_branch("post-" + tid)
    print(json.dumps({"type": "result", "subtype": "error_during_execution", "is_error": True,
                      "result": "Claude AI usage limit reached"}), flush=True)
    sys.exit(1)
elif action == "branch-h9":
    start_branch("post-" + tid)
    subprocess.run([sys.executable, os.path.join(scripts, "hrd.py"), "result", "--topic", tid,
                    "--status", "held:needs-human", "--note", "tooling: rate limited: usage limit reached"], check=True)
    sys.exit(0)
elif action == "branch-overloaded":
    start_branch("post-" + tid)
    print(json.dumps({"type": "result", "subtype": "error_during_execution", "is_error": True,
                      "result": "API Error: 529 Overloaded"}), flush=True)
    sys.exit(1)
elif action == "branch-h9-past":
    start_branch("post-" + tid)
    subprocess.run([sys.executable, os.path.join(scripts, "hrd.py"), "result", "--topic", tid,
                    "--status", "held:needs-human", "--note",
                    "tooling: rate limited: usage limit reached|%s" % os.environ["HRD_FAKE_PAST"]], check=True)
    sys.exit(0)
elif action == "pr-and-requeue-elsewhere":  # the PR opens while another machine requeues the topic
    other = os.environ["HRD_FAKE_OTHER_CLONE"]
    subprocess.run(["git", "-C", other, "pull", "-q"], check=True)
    tp = os.path.join(other, ".claude/herald/topics.json")
    data = json.load(open(tp))
    for t in data["topics"]:
        if t["id"] == tid:
            t["state"] = "queued"
            t.setdefault("history", []).append({"at": "2099-01-01T00:00:00+00:00", "state": "queued",
                                                "reason": None, "note": "requeued elsewhere"})
    json.dump(data, open(tp, "w"))
    subprocess.run(["git", "-C", other, "commit", "-qam", "chore(herald): requeue elsewhere"], check=True)
    subprocess.run(["git", "-C", other, "push", "-q"], check=True)
    action = "pr"
elif action == "overloaded":
    print(json.dumps({"type": "result", "subtype": "error_during_execution", "is_error": True,
                      "result": "API Error: 529 Overloaded"}), flush=True)
    sys.exit(1)
elif action == "pr-nores":  # cut off between `gh pr create` and `HRD result`
    start_branch("post-" + tid)
    st = os.environ["HRD_FAKE_GH_STATE"]
    data = json.load(open(st))
    data["prs"].append({"number": 100 + len(data["prs"]), "state": "OPEN",
                        "headRefName": "herald/%s--post-%s" % (tid, tid), "labels": ["herald"]})
    json.dump(data, open(st, "w"))
    sys.exit(1)
elif action == "pr-with-limit":
    limit_out()
    action = "pr"
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
elif action == "version-gate-branch":
    # stopped at the re-check right after `HRD branch` (origin carried other scripts)
    start_branch("post-" + tid)
    subprocess.run([sys.executable, os.path.join(scripts, "hrd.py"), "result", "--topic", tid,
                    "--status", "held:needs-human", "--note", "tooling: herald version mismatch on branch"], check=True)
elif action == "version-gate":
    # stopped at the SKILL.md version gate before doing anything
    subprocess.run([sys.executable, os.path.join(scripts, "hrd.py"), "result", "--topic", tid,
                    "--status", "held:needs-human", "--note", "tooling: herald version mismatch"], check=True)
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
