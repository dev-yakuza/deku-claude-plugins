"""Usage-limit verdicts for batch child logs (`claude -p --output-format stream-json`).

Pure functions: no git, no clock of their own (`now` is passed in, epoch seconds). The rules
and the measured reasons behind them are in design/herald/05-batch-rate-limit.md §2.1; the
event field names follow Guild batch's one measured limit and its fixtures, so an unknown
status counts as limited and an unknown reset time falls back to a backoff.
"""

import datetime
import json
import math
import re

FAR = "far"  # a reset beyond the single-wait ceiling (weekly wording without a dated time)
MAX_FUTURE = 30 * 86400

_LIMIT_RE = re.compile(
    r"usage limit|limit reached|hit your (?:usage )?limit|rate[ -]limit|rate_limit_error|too many requests"
    r"|\b429\b|resets? (?:at|in)\b|\bresets \d", re.I)
_STRONG_RE = re.compile(
    r"usage limit|hit your (?:usage )?limit|(?:session|5-hour|weekly|opus|sonnet|claude)[ -]limit reached"
    r"|\|\s*\d{10,13}\b", re.I)
_OVERLOADED_RE = re.compile(r"overloaded|\b529\b", re.I)
# "context limit reached", "output token limit": a context or output ceiling, not a usage limit
_NOT_USAGE_RE = re.compile(r"\b(?:context|tokens?|output)(?:[ -](?:window|tokens?))?[ -]+limit\w*(?: reached)?", re.I)
_WEEKLY_RE = re.compile(r"\b(?:weekly|week|monthly)\b", re.I)

_DAYS = {d: i for i, d in enumerate(["mon", "tue", "wed", "thu", "fri", "sat", "sun"])}
_MONTHS = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep",
                                            "oct", "nov", "dec"])}
_RESET_AT_RE = re.compile(
    r"resets?\s+(?:at\s+)?"
    r"(?:(?P<dow>mon|tue|wed|thu|fri|sat|sun)[a-z]*\.?,?\s+"
    r"|(?P<mon>jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(?P<day>\d{1,2})(?:,\s*(?P<year>\d{4}))?,?\s+)?"
    r"(?:at\s+)?(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ap>am|pm)?"
    r"(?:\s*\((?P<tz>[A-Za-z_]+(?:/[A-Za-z_+-]+)*)\))?", re.I)
_RESET_IN_RE = re.compile(r"resets?\s+in\s+(\d+(?:\.\d+)?)\s*(minute|min|hour|hr|day)s?\b", re.I)
_EPOCH_RE = re.compile(r"\|\s*(\d{10,13})\b")


def sanitize(value, now):
    """resetsAt → epoch seconds, or None. Integers (seconds or milliseconds) and ISO-8601 only."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and not math.isfinite(value):  # NaN, Infinity (json.loads accepts them)
            return None
        v = int(value)
    elif isinstance(value, str) and value.strip().isdigit():
        v = int(value.strip())
    elif isinstance(value, str):
        try:
            dt = datetime.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        v = int(dt.timestamp())
    else:
        return None
    if v >= 10 ** 11:
        v //= 1000
    if v <= 0 or v > now + MAX_FUTURE:
        return None
    return v


def _zone(name):
    if not name:
        return None
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:
        return None


def extract_reset(text, now):
    """A reset time named in a message: epoch seconds, FAR, or None."""
    if not text:
        return None
    m = _EPOCH_RE.search(text)
    if m:
        return sanitize(int(m.group(1)), now)
    m = _RESET_IN_RE.search(text)
    if m:
        n, unit = float(m.group(1)), m.group(2).lower()
        secs = n * (60 if unit.startswith("min") else 3600 if unit.startswith(("hour", "hr")) else 86400)
        return sanitize(int(now + secs), now)
    weekly = bool(_WEEKLY_RE.search(text))
    for m in _RESET_AT_RE.finditer(text):
        h, mi, ap = int(m.group("h")), int(m.group("m") or 0), (m.group("ap") or "").lower()
        if not ap and not m.group("m") and not (m.group("dow") or m.group("mon")):
            continue  # a bare number ("resets 3") is not a time
        if ap == "pm" and h < 12:
            h += 12
        elif ap == "am" and h == 12:
            h = 0
        if h > 23 or mi > 59:
            continue
        tz = _zone(m.group("tz"))
        base = datetime.datetime.fromtimestamp(now, tz) if tz else datetime.datetime.fromtimestamp(now).astimezone()
        dated = bool(m.group("dow") or m.group("mon"))
        if weekly and not dated:
            return FAR
        if m.group("mon"):
            year = int(m.group("year") or base.year)
            try:
                cand = base.replace(year=year, month=_MONTHS[m.group("mon").lower()[:3]], day=int(m.group("day")),
                                    hour=h, minute=mi, second=0, microsecond=0)
            except ValueError:
                continue
            if not m.group("year") and cand.timestamp() < now - 86400:
                cand = cand.replace(year=year + 1)
            return sanitize(int(cand.timestamp()), now)
        if m.group("dow"):
            target = _DAYS[m.group("dow").lower()[:3]]
            cand = base.replace(hour=h, minute=mi, second=0, microsecond=0)
            cand += datetime.timedelta(days=(target - cand.weekday()) % 7)
            if cand.timestamp() < now - 2 * 3600:
                cand += datetime.timedelta(days=7)
            return sanitize(int(cand.timestamp()), now)
        # time only: the occurrence nearest now within [now-2h, now+22h]
        cand = base.replace(hour=h, minute=mi, second=0, microsecond=0)
        while cand.timestamp() < now - 2 * 3600:
            cand += datetime.timedelta(days=1)
        while cand.timestamp() > now + 22 * 3600:
            cand -= datetime.timedelta(days=1)
        return int(cand.timestamp())
    if weekly:
        return FAR
    return None


def _decode(line):
    """(object, whole, prefix) — `whole` is False when only the slice from the last `{"type":`
    decoded; `prefix` is what came before that slice (stderr glued to a JSON line — Guild L3)."""
    try:
        return json.loads(line), True, ""
    except ValueError:
        pass
    i = line.rfind('{"type":')
    if i > 0:
        try:
            return json.loads(line[i:]), False, line[:i]
        except ValueError:
            pass
    return None, False, ""


def _lost_event(line):
    """A line that did not decode as a whole and carries a rate-limit event whose status is not
    `allowed` (or was cut off): the limit's own bytes were damaged (Guild L4)."""
    has_field = '"rate_limit_info":' in line or '"type":"rate_limit_event"' in line
    if not has_field and not (len(line) >= 12 and '{"type":"rate_limit_event"'.startswith(line.strip())):
        return False
    i = line.rfind('"rate_limit_info":')
    if i < 0:
        return True
    tail = line[i:]
    j = tail.rfind('"status"')
    if j < 0:
        return True
    rest = tail[j + len('"status"'):].lstrip(" ").lstrip(":").lstrip(" ")
    return not rest.startswith('"allowed')


def _texts(obj):
    """(error_texts, success_result_texts) carried by one decoded stream-json object."""
    err, ok = [], []
    t = obj.get("type")
    if t == "result":
        dst = err if obj.get("is_error") else ok
        if isinstance(obj.get("result"), str):
            dst.append(obj["result"])
        for e in obj.get("errors") or []:
            if isinstance(e, str):
                dst.append(e)
            elif isinstance(e, dict):
                dst.extend(str(v) for v in e.values() if isinstance(v, str))
    elif t == "assistant" and (obj.get("isApiErrorMessage") or obj.get("error")):
        if isinstance(obj.get("error"), str):
            err.append(obj["error"])
        msg = obj.get("message") or {}
        for c in msg.get("content") or [] if isinstance(msg, dict) else []:
            if isinstance(c, dict) and isinstance(c.get("text"), str):
                err.append(c["text"])
    elif t == "system" and "error" in str(obj.get("subtype") or ""):
        err.extend(str(v) for v in obj.values() if isinstance(v, str))
    return err, ok


def _calls_model(obj):
    if obj.get("type") != "assistant" or obj.get("isApiErrorMessage"):
        return False
    usage = (obj.get("message") or {}).get("usage") if isinstance(obj.get("message"), dict) else None
    if not isinstance(usage, dict):
        return False
    return any(isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0
               for k, v in usage.items() if k.endswith("tokens"))


def verdict(limited=False, kind=None, reset_at=None, source=None, info=None, detail="", demoted=False):
    return {"limited": limited, "kind": kind, "reset_at": reset_at, "source": source, "info": info,
            "detail": detail, "demoted": demoted}


def _past(v, returncode, now):
    """R7: rc 0 with a numeric reset already past — a limit the CLI already waited out."""
    if returncode == 0 and isinstance(v["reset_at"], int) and v["reset_at"] <= now:
        return verdict(source=v["source"], info=v["info"], detail="reset already passed: " + v["detail"],
                       demoted=True)
    return v


def scan(log_path, returncode, now):
    """The verdict for one child log (§2.1). Never raises: an unreadable log is no verdict, an
    internal error is a limit with no reset (the runner then backs off rather than crashing)."""
    try:
        return _scan(log_path, returncode, now)
    except Exception as e:  # noqa: BLE001 — a verdict must never take the runner down
        return verdict(True, "limit", None, "scan-error", None, "scan failed: %s" % e)


def _scan(log_path, returncode, now):
    objs = []          # (line_no, obj)
    broken = []        # (line_no, raw line) of lines that did not decode as a whole
    stderr = []
    last_event = None  # (line_no, rate_limit_info)
    try:
        f = open(log_path, encoding="utf-8", errors="replace")
    except OSError:
        return verdict(detail="no log")
    with f:
        for n, raw in enumerate(f):
            line = raw.rstrip("\n")
            if not line.strip():
                continue
            obj, whole, prefix = _decode(line)
            if not whole:
                broken.append((n, line))
            if prefix.strip():
                stderr.append(prefix)
            if isinstance(obj, dict):
                objs.append((n, obj))
                if obj.get("type") == "rate_limit_event" and isinstance(obj.get("rate_limit_info"), dict):
                    last_event = (n, obj["rate_limit_info"])
            elif obj is None and not line.lstrip().startswith("{"):
                stderr.append(line)
    # 1. the last event
    if last_event:
        n_e, info = last_event
        status = str(info.get("status"))
        if not status.startswith("allowed"):
            overage = str(info.get("overageStatus") or "").startswith("allowed") or info.get("isUsingOverage") is True
            kept_calling = any(_calls_model(o) for n, o in objs if n > n_e)
            if not overage and not kept_calling:
                v = verdict(True, "limit", sanitize(info.get("resetsAt"), now), "event", info,
                            "rate_limit_event status=%s" % status)
                return _past(v, returncode, now)
    # 2. a damaged event after the last decoded one
    after = last_event[0] if last_event else -1
    for n, line in broken:
        if n > after and _lost_event(line):
            return verdict(True, "limit", None, "lost-event", None, "undecodable rate-limit event line %d" % (n + 1))
    # 3. wording in error and result texts (stderr only when the child failed)
    err, ok = [], []
    for _, o in objs:
        e, s = _texts(o)
        err += e
        ok += s
    if returncode != 0:
        err += stderr
    for text in err:
        clean = _NOT_USAGE_RE.sub(" ", text)
        if _LIMIT_RE.search(clean):
            v = verdict(True, "limit", extract_reset(clean, now), "text", None, clean.strip()[:200])
            return _past(v, returncode, now)
    for text in ok:
        clean = _NOT_USAGE_RE.sub(" ", text)
        if _STRONG_RE.search(clean):
            v = verdict(True, "limit", extract_reset(clean, now), "text", None, clean.strip()[:200])
            return _past(v, returncode, now)
    for text in err:
        if _OVERLOADED_RE.search(text):
            return verdict(True, "overloaded", None, "text", None, text.strip()[:200])
    return verdict()
