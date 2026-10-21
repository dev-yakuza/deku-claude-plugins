"""What Claude Code does around a Bash call, for the M0 end-to-end tests (m0f-plan §4): the call's tool_use line is
in the transcript before PreToolUse (measured X3), the real guard.py process decides, a denied call does not run, and
the result goes into the transcript. No Claude Code and no model: the test plays the person and the agent."""

import json
import os
import shlex
import subprocess
import sys

import helpers
import transcripts as TR

GUARD = os.path.join(helpers.SCRIPTS, "guard.py")


class Result(object):
    def __init__(self, decision, reason, code=None, out="", err=""):
        self.decision, self.reason, self.code, self.out, self.err = decision, reason, code, out, err

    @property
    def ran(self):
        return self.code is not None

    def __repr__(self):
        return "Result(%s, code=%s, %r, %r)" % (self.decision, self.code, (self.reason or "")[:160], self.err[-300:])


def guard(hook, env):
    out = subprocess.run([sys.executable, "-B", GUARD], input=json.dumps(hook), capture_output=True, text=True,
                         env=env, timeout=60)
    if out.returncode != 0:
        raise AssertionError("guard.py exited %d: %s" % (out.returncode, out.stderr))
    if not out.stdout.strip():
        return None, None, None
    data = json.loads(out.stdout)
    hso = data.get("hookSpecificOutput") or {}
    return hso.get("permissionDecision"), hso.get("permissionDecisionReason"), data


class Session(object):
    def __init__(self, cwd, guard_env, bash_env, sid, executor=None, mode="default"):
        self.cwd = cwd
        self.guard_env = dict(guard_env)
        self.guard_env["PYTHONDONTWRITEBYTECODE"] = "1"
        self.guard_env.pop("CLAUDE_PLUGIN_DATA", None)
        self.bash_env = dict(bash_env)
        self.bash_env["CLAUDECODE"] = "1"
        self.bash_env["CLAUDE_CODE_SESSION_ID"] = sid
        self.sid = sid
        self.mode = mode
        self.t = TR.T(session_id=sid)
        self.tpath = TR.transcript_path(self.guard_env, sid)
        self.n = 0
        self.executor = executor or self.shell
        self.t.user_prompt("시작")
        self.warnings = []

    # --- the person ---
    def say(self, text="계속해"):
        self.t.user_prompt(text)

    def ask(self, qtext, options, chosen, **kw):
        self.n += 1
        aid = "toolu_ask%03d" % self.n
        qs = [TR.question(qtext, options)]
        self.t.ask(aid, qs)
        if chosen is None:
            self.t.cancel(aid)
        else:
            self.t.answer(aid, qs, {qtext: chosen}, **kw)
        return aid

    # --- the agent ---
    def hook(self, tool, ti, extra=None):
        self.n += 1
        tid = "toolu_%03d" % self.n
        self.t.tool_use(tool, tid, ti)
        self.t.write(self.tpath)
        h = {"session_id": self.sid, "transcript_path": self.tpath, "cwd": self.cwd, "permission_mode": self.mode,
             "hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": ti, "tool_use_id": tid,
             "prompt_id": self.t.prompt}
        h.update(extra or {})
        return tid, h

    def bash(self, cmd, extra=None):
        tid, h = self.hook("Bash", {"command": cmd}, extra)
        decision, reason, data = guard(h, self.guard_env)
        if data and data.get("systemMessage"):
            self.warnings.append(data["systemMessage"])
        if decision == "deny":
            self.t.tool_result(tid, "denied: %s" % reason)
            self.t.write(self.tpath)
            return Result(decision, reason)
        code, out, err = self.executor(cmd)
        self.t.tool_result(tid, (out + err)[-2000:])
        self.t.write(self.tpath)
        return Result(decision, reason, code, out, err)

    def tool(self, name, ti, extra=None):
        """A non-Bash tool: only the guard's decision (the test does not perform the write)."""
        _tid, h = self.hook(name, ti, extra)
        return guard(h, self.guard_env)[:2]

    def shell(self, cmd):
        out = subprocess.run(["/bin/sh", "-c", cmd], cwd=self.cwd, capture_output=True, text=True, env=self.bash_env,
                             timeout=120)
        return out.returncode, out.stdout, out.stderr


def state_py_executor(case, session):
    """Run `python3 .claude/studio/scripts/state.py …` in-process with the case's injected s2v (ApproveCase),
    everything else in the shell."""
    def run(cmd):
        words = shlex.split(cmd)
        while words[:1] == ["cd"] or (len(words) > 2 and words[2] == "&&" and words[0] == "cd"):
            words = words[3:]
        if len(words) >= 2 and words[0].startswith("python") and words[1].endswith("state.py"):
            saved = dict(os.environ)
            os.environ.update({"CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": session.sid})
            try:
                code = case.cli(*words[2:])
            finally:
                os.environ.clear()
                os.environ.update(saved)
            return code, case.last_out, case.last_err
        return session.shell(cmd)
    return run
