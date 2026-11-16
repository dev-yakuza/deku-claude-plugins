"""guildcore.emit — machine output, upward-compatible with the supervisor/batch log readers.

* `sentinel(name, obj)` — `>>> <NAME> <<<` then ONE JSON line, the same shape as
  `local_dev.py`'s `>>> LOCAL-DEV <<<` (§2.4 "출력").
* `stream_result(...)` — the `{"type":"result", …}` line batch/supervisor read from a
  `claude -p --output-format stream-json` child (`select(.type=="result" and .is_error==true)
  .result`, `total_cost_usd`, `usage`) — C §4.3.
* `rate_limit_event(...)` — the ONE synthetic event the engine prints before its result (§2.4):
  `resetsAt` is always present when rejected.

Engine stderr never carries `rate limit` / `overloaded` / `too many requests` (R3F-N3-3): the
supervisor fence scans wide text. `safe_stderr()` rewrites them.
"""

import json
import re
import sys

ENGINE_SENTINEL = ">>> ENGINE <<<"
_FENCE_WORDS = re.compile(r"rate[ -]?limit|overloaded|too many requests", re.I)


def dumps(obj):
    # compact, like the CLI's own stream-json: the supervisor fence matches the literal
    # `{"type":"rate_limit_event"` (sprint-supervisor.sh RL_LOST) — no space after the colon.
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def sentinel(name, obj, out=None):
    text = ">>> %s <<<\n%s\n" % (name.upper(), dumps(obj))
    (out or sys.stdout).write(text)
    return text


def engine(obj, out=None):
    return sentinel("ENGINE", obj, out)


def one_line(text):
    return " ".join((text or "").split())


def stream_result(cost_usd, is_error, line, usage=None, out=None):
    obj = {"type": "result", "is_error": bool(is_error), "result": one_line(line),
           "total_cost_usd": round(float(cost_usd or 0.0), 6), "usage": usage or {}}
    text = dumps(obj) + "\n"
    (out or sys.stdout).write(text)
    return text


def rate_limit_event(status, resets_at=None, out=None):
    if status not in ("allowed", "rejected"):
        raise ValueError("status must be allowed|rejected")
    info = {"status": status}
    if status == "rejected":
        if resets_at is None:
            raise ValueError("a rejected verdict always carries resetsAt (§2.4)")
        info["resetsAt"] = int(resets_at)
    obj = {"type": "rate_limit_event", "rate_limit_info": info}
    text = dumps(obj) + "\n"
    (out or sys.stdout).write(text)
    return text


def safe_stderr(text):
    return _FENCE_WORDS.sub("quota", text or "")


def warn(text, err=None):
    (err or sys.stderr).write(safe_stderr(text).rstrip("\n") + "\n")
