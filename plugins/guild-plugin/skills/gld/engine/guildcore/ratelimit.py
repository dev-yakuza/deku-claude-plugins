"""guildcore.ratelimit — rate-limit verdicts per session and the ONE synthetic final event (§2.4, §5.6).

Each `claude -p` session's stream carries `rate_limit_event`s (`rate_limit_info.status` =
allowed | allowed_warning | rejected, `resetsAt` epoch seconds) and, when the API refuses, a
`result` with `is_error` and `api_error_status` 429. The engine judges EACH session by its LAST
event (`observe`), then the run (`verdict`): if any session ended `rejected` and stopped work,
the run is `rejected` with the latest `resetsAt` seen — or now + 15 min when none was given
(the supervisor needs `resetsAt` always, §2.4). The engine prints only `final_event(verdict)`
on stdout — never a session's own events (CR-M4/FR-F6) — and exits 75 when rejected.
Attended: wait in place when the reset is ≤ 30 min away, else `terminal{paused: rate_limit}`.
"""

import time

from guildcore import emit

EXIT_RATE_LIMIT = 75
DEFAULT_WAIT_S = 15 * 60
ATTENDED_MAX_WAIT_S = 30 * 60


class SessionRL(object):
    def __init__(self, status, resets_at=None, http_429=False):
        self.status = status            # allowed | allowed_warning | rejected | unknown
        self.resets_at = resets_at
        self.http_429 = http_429

    def rejected(self):
        return self.status == "rejected"

    def as_dict(self):
        return {"status": self.status, "resetsAt": self.resets_at, "http_429": self.http_429}


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def observe(stream):
    """SessionRL from a parsed `adapters.claude.Stream` (or anything with `.rate_limit_events`
    and `.result`)."""
    evs = list(getattr(stream, "rate_limit_events", []) or [])
    res = getattr(stream, "result", None) or {}
    http_429 = res.get("api_error_status") == 429 or (
        bool(res.get("is_error")) and "rate_limit" in str(res.get("result") or "").lower())
    if evs:
        last = evs[-1]
        status = last.get("status") or "unknown"
        resets = _int(last.get("resetsAt"))
        if http_429 and status != "rejected":
            status = "rejected"
        if resets is None:
            resets = max([_int(e.get("resetsAt")) or 0 for e in evs]) or None
        return SessionRL(status, resets, http_429)
    if http_429:
        return SessionRL("rejected", None, True)
    return SessionRL("unknown" if not res else "allowed", None, False)


class Verdict(object):
    def __init__(self, status, resets_at=None):
        self.status = status
        self.resets_at = resets_at

    def rejected(self):
        return self.status == "rejected"


def verdict(sessions, now=None):
    now = int(time.time() if now is None else now)
    rej = [s for s in sessions if s.rejected()]
    if not rej:
        return Verdict("allowed")
    resets = [s.resets_at for s in rej if s.resets_at]
    return Verdict("rejected", max(resets) if resets else now + DEFAULT_WAIT_S)


def attended_action(v, now=None):
    """'continue' | 'wait' (≤30 min) | 'pause'."""
    if not v.rejected():
        return "continue"
    now = int(time.time() if now is None else now)
    return "wait" if v.resets_at - now <= ATTENDED_MAX_WAIT_S else "pause"


def wait_until(resets_at, sleep=time.sleep, now=time.time, slack_s=5):
    delay = max(0, int(resets_at) - int(now())) + slack_s
    sleep(delay)
    return delay


def final_event(v, out=None):
    """The one machine event before the engine's result line (compact JSON, §2.4)."""
    if v.rejected():
        return emit.rate_limit_event("rejected", v.resets_at, out=out)
    return emit.rate_limit_event("allowed", out=out)


EXIT_GH_AUTH = 3
EXIT_ENV_HALT = 6


def exit_code_for(exc):
    """The engine exit code for a terminal exception (§2.4): a GitHub rate limit (incl. the
    secondary-limit 403) or a rate-limited judge → 75; gh auth → 3; env halt → 6 (K1-B6)."""
    kind = getattr(exc, "kind", None)
    if kind == "ratelimit" or type(exc).__name__ == "RateLimited":
        return EXIT_RATE_LIMIT
    if kind == "auth":
        return EXIT_GH_AUTH
    if type(exc).__name__ == "EnvHalt":
        return EXIT_ENV_HALT
    return 1


def verdict_for_gh(exc, now=None):
    """A rejected verdict for a GitHub rate limit (Retry-After unknown → now + 15 min)."""
    now = int(time.time() if now is None else now)
    return Verdict("rejected", now + DEFAULT_WAIT_S)
