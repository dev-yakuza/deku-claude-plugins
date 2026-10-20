#!/usr/bin/env python3
"""Studio's PreToolUse guard (hooks/hooks.json; m0d1b-plan §2). Reads the hook input on stdin and
prints a deny decision, or nothing (no decision). Never allow, ask or defer. Any failure denies."""
import json
import os
import sys

# Bytecode goes to Claude Code's per-plugin data folder (outside the plugin and any repository), which
# saves compiling the guard on every call; without that folder nothing is written.
_DATA = os.environ.get("CLAUDE_PLUGIN_DATA")
if _DATA and os.path.isabs(_DATA):
    sys.pycache_prefix = os.path.join(_DATA, "pycache")
    sys.dont_write_bytecode = False
else:
    sys.dont_write_bytecode = True  # no __pycache__ in the plugin
MAX_INPUT = 64 * 1024 * 1024


def _deny(reason):
    return json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                              "permissionDecisionReason": reason}}, ensure_ascii=False)


def main():
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from stdo.guard import judge
        from stdo.guard.messages import INV9
        if os.environ.get("STUDIO_TEST_GUARD_RAISE") == "1":
            raise RuntimeError("test: injected failure")
        data = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(data) > MAX_INPUT:
            out = _deny("Studio guard [G-LIMIT]: the tool input is too large for the guard.\n" + INV9)
        else:
            hook = json.loads(data.decode("utf-8"))
            deny, ctx = judge.decide(hook, os.environ)
            out = _deny(deny.message(len(ctx.denies) - 1)) if deny is not None else None
            try:
                judge.record_run(ctx)
            except Exception:  # noqa: BLE001 — the record never changes the decision
                pass
        if out:
            sys.stdout.write(out + "\n")
            sys.stdout.flush()
        return 0
    except BaseException as e:  # noqa: BLE001 — closed side
        try:
            sys.stdout.write(_deny("Studio guard [G-ERR]: internal guard error (%s) — tell the user; this is a bug "
                                   "in the guard.\nStop: do not reach the same effect another way (INV9). Tell the "
                                   "user what was refused and why, and ask how to proceed." % type(e).__name__) + "\n")
            sys.stdout.flush()
            return 0
        except BaseException:  # noqa: BLE001
            try:
                sys.stderr.write("Studio guard: internal error\n")
                sys.stderr.flush()
            finally:
                os._exit(2)  # exit 2 blocks the call even without onFailure (m0-measure X6)


if __name__ == "__main__":
    sys.exit(main())
