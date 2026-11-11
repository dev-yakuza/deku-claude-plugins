#!/usr/bin/env python3
"""PreToolUse hook entry (plan §3.4). Wired by init in .claude/settings.json.

0.20.0 (implementation review 24 MAJOR-1): the settings no longer ask before `gh pr merge` — the
guard does. So a guard that cannot even start (an import error, scripts half-copied by `/hrd
update`, a python3 too old for them) must not fall open on a merge: this entry catches it and
runs a stdlib-only fallback that asks (unattended: denies) before any `gh … merge` (`gh api …/merge`
too) and the configured deploy string, and — unattended — before everything, as `main` does when
it crashes. Known limit: a hook killed by its timeout (30 s in the template) decides nothing;
Claude Code then applies the settings alone, where `Bash(gh:*)` is allowed.
"""
import io
import json
import os
import re
import sys

sys.dont_write_bytecode = True  # no __pycache__ in the repo's .claude/herald/scripts

MERGE_TEXT = re.compile(r"\bgh\b[\s\S]*\bmerge\b")


def _say(kind, reason):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": kind,
                                             "permissionDecisionReason": "Herald guard (fallback): " + reason}}))
    sys.exit(0)


def _deploy(payload):
    """The configured deploy string, read with json alone (None when it cannot be)."""
    start = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
    d = os.path.abspath(start)
    while True:
        p = os.path.join(d, ".claude", "herald", "config.json")
        if os.path.isfile(p):
            try:
                with open(p, encoding="utf-8") as f:
                    v = (json.load(f).get("commands") or {}).get("deploy")
                return v.strip() if isinstance(v, str) and v.strip() else None
            except Exception:  # noqa: BLE001
                return None
        up = os.path.dirname(d)
        if up == d:
            return None
        d = up


def fallback(raw, err):
    sys.stderr.write("Herald guard could not start (%s) — fallback rules only\n" % err)
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except ValueError:
        payload = {}
    payload = payload if isinstance(payload, dict) else {}
    unattended = os.environ.get("HRD_UNATTENDED") == "1"
    if unattended:  # as `main` on a crash: never silently disabled unattended
        _say("deny", "the guard could not start (%s) — refusing while unattended" % err)
    if payload.get("tool_name") != "Bash":
        sys.exit(0)
    cmd = (payload.get("tool_input") or {}).get("command")
    cmd = cmd if isinstance(cmd, str) else ""
    if MERGE_TEXT.search(cmd):
        _say("ask", "merging a PR publishes content — the guard could not start, confirm this command.")
    deploy = _deploy(payload)
    if deploy and deploy in cmd:
        _say("ask", "running the deploy command publishes the whole base branch — the guard could not start, "
                    "confirm this command.")
    sys.exit(0)


raw = sys.stdin.read() if not sys.stdin.isatty() else ""
try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from hrdlib.guard import main  # noqa: E402
    sys.stdin = io.StringIO(raw)
    main()
except SystemExit:
    raise
except BaseException as e:  # noqa: BLE001 — anything that kept the guard from deciding
    fallback(raw, "%s: %s" % (type(e).__name__, e))
