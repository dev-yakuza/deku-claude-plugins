"""The guard's evidence of a person's answer (`.claude/studio/local/pending-approval.json`) and
its one-use consumption record (m0b2-plan §1). The record and its lock live in the git common dir
(`<common>/studio/consumed-answers.{jsonl,lock}`, m1-plan §3.2): an answer is used once in the whole
repository, whichever worktree used it. The pending file stays per worktree.

Lock order (the only one): consumption lock (this module) -> the video's lock (store.write).
Commands that take only the video lock never take the consumption lock."""

import calendar
import json
import os
import time

from .. import paths, writes
from . import schema
from .argv import argv_sha

TTL = 600
SKEW = 60
SCHEMA = 1


class Missing(Exception):
    """No usable evidence (exit 6)."""


def local_dir(repo):
    return os.path.join(repo, ".claude", "studio", "local")


def pending_path(repo):
    return os.path.join(local_dir(repo), "pending-approval.json")


def consumed_path(repo):
    return paths.consumed_log(repo)


class ConsumptionLock(object):
    def __init__(self, repo, wait=2.0):
        self.path = paths.consumed_lock(repo)
        self.wait = wait
        self.fd = None

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        from .store import Lock  # same flock rules (busy -> 5, unsupported -> 2)
        self._lock = Lock(self.path, wait=self.wait)
        self._lock.__enter__()
        return self

    def __exit__(self, *exc):
        self._lock.__exit__(*exc)


def _epoch(stamp):
    try:
        return calendar.timegm(time.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ"))
    except (TypeError, ValueError):
        return None


def consumed_keys(repo, log=None):
    keys = set()
    try:
        with open(log or consumed_path(repo), encoding="utf-8") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                keys.add((e.get("session_id"), e.get("tool_use_id"), e.get("question_index")))
    except OSError:
        pass
    return keys


def check(repo, argv, label, proxy, now=None):
    """Checks 1-6 of m0b2-plan §1; returns the evidence or raises Missing."""
    now = time.time() if now is None else now
    try:
        raw = paths.read_local(repo, "pending-approval.json")
    except paths.UnsafeLocal as e:
        raise Missing(str(e))
    except OSError:
        raw = None
    if raw is None:
        raise Missing("no evidence of a person's answer: ask with AskUserQuestion first")
    try:
        ev = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise Missing("the evidence file is not JSON")
    if not isinstance(ev, dict) or ev.get("schema") != SCHEMA:
        raise Missing("the evidence file has another schema")
    for k in ("session_id", "tool_use_id", "answer", "argv_sha", "written_at"):
        if not isinstance(ev.get(k), str) or not ev.get(k):
            raise Missing("the evidence lacks %s" % k)
    qi = ev.get("question_index")
    if isinstance(qi, bool) or not isinstance(qi, int) or qi < 0:
        raise Missing("the evidence's question_index is not a whole number")
    t = _epoch(ev.get("written_at"))
    if t is None or now - t > TTL or t - now > SKEW:
        raise Missing("the evidence is too old (or from the future): ask again")
    if ev.get("argv_sha") != argv_sha(argv):
        raise Missing("the evidence is for another command")
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID")
    if not sid or ev.get("session_id") != sid:
        raise Missing("the evidence is from another session")
    key = (ev.get("session_id"), ev.get("tool_use_id"), ev.get("question_index"))
    if key in consumed_keys(repo):
        raise Missing("this answer was used already: ask again")
    if ev.get("answer") != label:
        raise Missing("the answer is not the approval label %r" % label)
    if (ev.get("mode") == "proxy") != bool(proxy):
        raise Missing("--proxy and the evidence's mode do not match")
    if ev.get("mode") not in ("human", "proxy"):
        raise Missing("unknown evidence mode")
    return ev


def consume(repo, ev, video, cmd, log=None):
    """Append the consumption record and fsync (before the video's state is written)."""
    writes.check("the used-answer record")
    line = {"session_id": ev["session_id"], "tool_use_id": ev["tool_use_id"],
            "question_index": ev["question_index"], "video": video, "cmd": cmd, "at": schema.now()}
    p = log or consumed_path(repo)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n")
        f.flush()
        os.fsync(f.fileno())


def remove_pending(repo):
    if paths.local_problem(repo):
        return False
    try:
        os.remove(pending_path(repo))
    except OSError:
        return False
    return True


def answer_of(ev):
    out = {"tool_use_id": ev.get("tool_use_id"), "question_index": ev.get("question_index"),
           "answer": ev.get("answer")}
    if ev.get("reason"):
        out["reason"] = ev["reason"]
    return out
