"""The sandbox proxy mode (00-plan §3.4 "대행 모드", m0d2-plan §7.1): only when the process's own environment has
STUDIO_SANDBOX=1 (set by the person who started Claude Code; a command that sets it is denied by the guard) and the
repository lies under `sandbox_root` of the per-user `studio-sandbox.json`. Shared by the guard (`stdo/guard/proxy.py`)
and the scripts copied into a repository (run_s2v.py's watermark, m1-plan §4.2 v4 R5): one rule."""

import json
import os

from . import paths


def active(env, worktree):
    if env.get("STUDIO_SANDBOX") != "1" or not worktree:
        return False
    try:
        f = paths.sandbox_file(env)
    except ValueError:
        return False
    try:
        with open(f, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return False
    root = data.get("sandbox_root") if isinstance(data, dict) else None
    if not isinstance(root, str) or not os.path.isabs(root):
        return False
    real_root = os.path.realpath(root)
    real_wt = os.path.realpath(worktree)
    real_file = os.path.realpath(f)
    if real_file == real_wt or real_file.startswith(real_wt.rstrip("/") + "/"):
        return False  # the settings file inside the repository is not the person's
    return real_wt == real_root or real_wt.startswith(real_root.rstrip("/") + "/")
