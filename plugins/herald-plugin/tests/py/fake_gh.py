#!/usr/bin/env python3
"""Minimal fake `gh` for tests. State: JSON file at $HRD_FAKE_GH_STATE = {"prs": [...]}.
Supports: pr list --label L --state S --json F --limit N ; pr edit N --add-label/--remove-label L.
"""
import json
import os
import sys

state_path = os.environ["HRD_FAKE_GH_STATE"]
state = json.load(open(state_path)) if os.path.exists(state_path) else {"prs": []}
args = sys.argv[1:]


def opt(name, default=None):
    return args[args.index(name) + 1] if name in args else default


if args[:2] == ["pr", "list"]:
    label = opt("--label")
    st = opt("--state", "open")
    out = []
    for pr in state["prs"]:
        labels = pr.get("labels", [])
        if label and label not in labels:
            continue
        s = pr.get("state", "OPEN")
        if st == "merged" and s != "MERGED":
            continue
        if st == "open" and s != "OPEN":
            continue
        rec = dict(pr)
        rec["labels"] = [{"name": l} for l in labels]
        out.append(rec)
    print(json.dumps(out))
elif args[:2] == ["pr", "edit"]:
    num = int(args[2])
    for pr in state["prs"]:
        if pr["number"] == num:
            if "--add-label" in args:
                pr.setdefault("labels", []).append(opt("--add-label"))
            if "--remove-label" in args:
                pr["labels"] = [l for l in pr.get("labels", []) if l != opt("--remove-label")]
    json.dump(state, open(state_path, "w"))
else:
    sys.stderr.write("fake gh: unsupported %s\n" % args)
    sys.exit(1)
