"""A synthetic harness repository (drivers/make_harness.py) with the hook installed, for the M0f tests."""

import json
import os
import subprocess
import sys

from helpers import StudioTestCase
from stdo.commit import okfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "drivers"))
import make_harness  # noqa: E402

SID = "sess-m0f"


class HarnessCase(StudioTestCase):
    husky = False

    def setUp(self):
        super().setUp()
        self.pybin = os.path.join(self.tmp, "pybin")
        os.makedirs(self.pybin)
        os.symlink(sys.executable, os.path.join(self.pybin, "python3"))
        self.env = dict(os.environ)
        self.env["PATH"] = self.pybin + os.pathsep + self.env.get("PATH", "")
        self.repo = make_harness.make(os.path.join(self.tmp, "repo"), env=self.env, husky=self.husky)

    # --- running ---
    def git(self, *args, check=True, env=None):
        out = subprocess.run(["git", "-C", self.repo] + list(args), capture_output=True, text=True,
                             env=env or self.env)
        if check and out.returncode != 0:
            raise AssertionError("git %s: %s%s" % (" ".join(args), out.stdout, out.stderr))
        return out

    def script(self, name, *args, env=None):
        return subprocess.run([sys.executable, "-B", os.path.join(self.repo, ".claude", "studio", "scripts", name)]
                              + list(args), cwd=self.repo, capture_output=True, text=True, env=env or self.env)

    def stage(self, env=None):
        return self.script("check_commit.py", "--stage", "harness", env=env)

    def claude_env(self, sid=SID):
        e = dict(self.env)
        e["CLAUDECODE"] = "1"
        e["CLAUDE_CODE_SESSION_ID"] = sid
        return e

    def guard_ran(self, sid=SID):
        p = os.path.join(self.repo, ".claude", "studio", "local", "guard-ran.json")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            json.dump({"schema": 1, "sessions": {sid: "2026-10-21T00:00:00Z"}}, f)

    def approve_as_guard(self, sid=SID, mode="human"):
        ok, _ = okfile.read(self.repo)
        # each approval is a new answer (an answer is used once in the repository, m1-plan §3.2)
        self._answers = getattr(self, "_answers", 0) + 1
        okfile.set_approval(self.repo, {"mode": mode, "tree": ok["tree"], "head": ok["head"], "session_id": sid,
                                        "answer": ok["label"], "summary": ok.get("summary"),
                                        "values": ok.get("values_shown") or None,
                                        "tool_use_id": "t%d" % self._answers, "question_index": 0,
                                        "at": "2026-10-21T00:00:00Z"})

    def commit(self, msg="harness", env=None, *extra):
        return self.git("commit", "-q", "-m", msg, *extra, check=False, env=env)

    # --- files ---
    def write(self, rel, text="x\n"):
        p = os.path.join(self.repo, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(text)
        return p

    def read(self, rel):
        with open(os.path.join(self.repo, rel)) as f:
            return f.read()

    def config(self, **changes):
        p = os.path.join(self.repo, ".claude", "studio", "config.json")
        with open(p) as f:
            cfg = json.load(f)
        cfg.update(changes)
        with open(p, "w") as f:
            json.dump(cfg, f, indent=2)
            f.write("\n")
