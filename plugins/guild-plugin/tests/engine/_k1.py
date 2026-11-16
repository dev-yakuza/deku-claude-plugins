"""Helpers for the K1 engine tests: temp git repos, a fake `claude` spawn, fake clocks."""

import json
import os
import shutil
import subprocess
import tempfile

import _util  # noqa: F401  (engine on sys.path, gh blocked)

from guildcore.adapters.claude import ProcResult

K1FX = os.path.join(_util.FX, "k1")


def _rm(d):
    for base, dirs, files in os.walk(d):          # exported gate copies are read-only (0555)
        try:
            os.chmod(base, 0o755)
        except OSError:
            pass
    shutil.rmtree(d, True)


def tmpdir(case):
    d = tempfile.mkdtemp(prefix="gld-k1-")
    case.addCleanup(_rm, d)
    return os.path.realpath(d)


def git(cwd, *args):
    p = subprocess.run(["git"] + list(args), cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        raise AssertionError("git %s: %s" % (" ".join(args), p.stderr.decode()))
    return p.stdout.decode().strip()


def repo(case, files=None, branch="main"):
    """A temp git repo with one commit; returns its path."""
    d = tmpdir(case)
    git(d, "init", "-q", "-b", branch)
    git(d, "config", "user.name", "t")
    git(d, "config", "user.email", "t@example.invalid")
    for rel, text in (files or {"README.md": "hi\n"}).items():
        p = os.path.join(d, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as fh:
            fh.write(text if isinstance(text, str) else json.dumps(text, indent=1))
    git(d, "add", "-A")
    git(d, "commit", "-qm", "init")
    return d


class Clock(object):
    def __init__(self, start="2026-11-16T00:00:00Z"):
        self.t = start
        self.n = 0

    def now(self):
        self.n += 1
        return "2026-11-16T00:%02d:%02dZ" % (self.n // 60, self.n % 60)


def stream_lines(session_id="s-1", texts=(), tool_uses=(), denials=(), decisions=None,
                 result=None, rate_limits=(), structured=None):
    """stream-json text for one fake session."""
    out = [{"type": "system", "subtype": "init", "session_id": session_id, "tools": ["Bash"]}]
    for rl in rate_limits:
        out.append({"type": "rate_limit_event", "rate_limit_info": rl, "session_id": session_id})
    for tu in tool_uses:
        out.append({"type": "assistant", "session_id": session_id, "message": {"content": [
            {"type": "tool_use", "id": tu["id"], "name": tu.get("name", "Bash"), "input": tu.get("input", {})}]}})
        d = [x for x in denials if x.get("tool_use_id") == tu["id"]]
        for x in d:
            out.append(dict({"type": "system", "subtype": "permission_denied", "tool_name": tu.get("name", "Bash"),
                             "session_id": session_id}, **x))
        meta = (decisions or {}).get(tu["id"])
        u = {"type": "user", "session_id": session_id, "message": {"content": [
            {"type": "tool_result", "tool_use_id": tu["id"], "is_error": bool(d),
             "content": "denied" if d else "ok"}]}}
        if meta:
            u["tool_result_meta"] = [{"id": tu["id"], "permission_decision": meta}]
        out.append(u)
    for t in texts:
        out.append({"type": "assistant", "session_id": session_id, "message": {"content": [{"type": "text", "text": t}]}})
    res = {"type": "result", "subtype": "success", "is_error": False, "session_id": session_id,
           "result": texts[-1] if texts else "", "total_cost_usd": 0.01, "num_turns": 1,
           "duration_ms": 10, "usage": {"input_tokens": 10, "output_tokens": 2,
                                        "cache_creation": {"ephemeral_5m_input_tokens": 7,
                                                           "ephemeral_1h_input_tokens": 0}},
           "modelUsage": {"m": {"costUSD": 0.01}}}
    if structured is not None:
        res["structured_output"] = structured
    res.update(result or {})
    out.append(res)
    return "\n".join(json.dumps(x, ensure_ascii=False) for x in out) + "\n"


class FakeSpawn(object):
    """Replaces adapters.claude.run_process. `sessions` = list of dicts consumed in order:
    {"stream": <text>, "rc": 0, "timed_out": False, "killed_by": None, "files": {path: text},
     "check": fn(argv, env, cwd, stdin)}."""

    def __init__(self, sessions):
        self.sessions = list(sessions)
        self.calls = []

    def __call__(self, argv, env, cwd, stdin_text, stdout_path, stderr_path, timeout_s,
                 on_start=None, halt_check=None):
        s = self.sessions.pop(0)
        self.calls.append({"argv": argv, "env": env, "cwd": cwd, "stdin": stdin_text,
                           "timeout_s": timeout_s})
        if on_start:
            on_start({"pid": 1, "pgid": 1, "start_time": "x"})
        if s.get("check"):
            s["check"](argv, env, cwd, stdin_text)
        for p, text in (s.get("files") or {}).items():
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as fh:
                fh.write(text)
        with open(stdout_path, "w") as fh:
            fh.write(s.get("stream", ""))
        with open(stderr_path, "w") as fh:
            fh.write(s.get("stderr", ""))
        return ProcResult(s.get("rc", 0), s.get("timed_out", False), 1, 1, "x", 0.1, s.get("killed_by"))


class RecJournal(object):
    """A minimal journal stand-in that records calls."""

    def __init__(self):
        self.pids, self.denials = [], []

    def record_pid(self, who, pid, pgid, start, session_id=None):
        self.pids.append((who, pid, pgid, start, session_id))

    def record_denial(self, role, command, cls, reason_type=None):
        self.denials.append((role, command, cls, reason_type))
