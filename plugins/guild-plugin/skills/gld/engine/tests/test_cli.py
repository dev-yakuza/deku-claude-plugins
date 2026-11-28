"""U18 engine CLI: arguments, exit codes, status, resume checks, detaching (no paid call)."""

import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

from gxengine import cli, driver, lifecycle
from tests import c_world as W

ENGINE_PY = os.path.join(W.ENGINE, "engine.py")


class Parser(unittest.TestCase):
    def run_cli(self, argv, environ=None):
        out = io.StringIO()
        err = io.StringIO()
        old = sys.stderr
        sys.stderr = err
        try:
            rc = cli.main(argv, environ=environ or {"HOME": "/nonexistent", "GLD_ENGINE_HOME": "/nonexistent/gld"},
                          out=out)
        finally:
            sys.stderr = old
        return rc, out.getvalue(), err.getvalue()

    def test_usage_errors_exit_2(self):
        for argv in ([], ["dev"], ["dev", "--repo", "acme/app"], ["dev", "--repo", "acme", "--issue", "1"],
                     ["dev", "--repo", "acme/app", "--issue", "0"], ["dev", "--repo", "acme/app", "--issue", "01"],
                     ["resume", "--repo", "acme/app", "--issue", "1", "--answer", "approve-all"],
                     ["status", "--repo", "acme/app"], ["bogus"]):
            with self.subTest(argv=argv):
                self.assertEqual(self.run_cli(argv)[0], cli.EXIT_USAGE)

    def test_exit_code_contract(self):
        self.assertEqual((cli.EXIT_OK, cli.EXIT_USAGE, cli.EXIT_LOCKED, cli.EXIT_REFUSED, cli.EXIT_NEEDS_HUMAN,
                          cli.EXIT_NEEDS_LEADER), (0, 2, 3, 4, 10, 11))

    def test_canary_arguments(self):
        """P4: the canary command exists; its runs are tested in test_canaryrun (no paid call)."""
        self.assertEqual(self.run_cli(["canary", "--srt-only", "--no-srt"])[0], cli.EXIT_USAGE)
        self.assertEqual(self.run_cli(["canary", "--role-class", "leader"])[0], cli.EXIT_USAGE)
        rc, out, _ = self.run_cli(["canary", "--srt-only", "--config", "/nonexistent/config.json"])
        self.assertEqual(rc, cli.EXIT_REFUSED)
        self.assertIn("refused", out)

    def test_engine_py_entry(self):
        p = subprocess.run([sys.executable, "-I", ENGINE_PY, "status", "--repo", "acme/app", "--issue", "9"],
                           capture_output=True, text=True,
                           env={"PATH": "/usr/bin:/bin", "HOME": tempfile.gettempdir(),
                                "GLD_ENGINE_HOME": os.path.join(os.path.realpath(tempfile.mkdtemp()), "g")})
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("no engine state", p.stdout)


class WithWorld(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.w = W.World(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def cli(self, *argv, units=None, stage=1):
        # a stage-1 world (its template has no done-gate): stage 1 explicitly since the default is 2 (Q6)
        out = io.StringIO()
        rc = cli.main(list(argv), environ=self.w.environ, out=out, units=units, stage=stage)
        return rc, out.getvalue()

    def common(self):
        return ["--repo", W.REPO, "--issue", str(W.ISSUE)]

    def test_foreground_dev_status_and_resume(self):
        res = W.FakeResults({"review": [W.blocked, W.done]})
        rc, out = self.cli("dev", *self.common(), "--checkout", self.w.repo.path, "--foreground",
                           units=W.units(self.w, results=res))
        self.assertEqual(rc, cli.EXIT_NEEDS_HUMAN, out)
        rc, out = self.cli("status", *self.common())
        self.assertEqual(rc, cli.EXIT_OK)          # no detached engine → no rc file
        self.assertIn("stopped: needs_human — blocked at review", out)
        self.assertIn("answers: rerun, escalate", out)
        rc, out = self.cli("status", *self.common(), "--json")
        rep = json.loads(out)
        self.assertEqual(rep["stop"]["reason"], "blocked")
        self.assertEqual(rep["question"]["allowed_answers"], ["rerun", "escalate"])
        self.assertEqual([s["id"] for s in rep["steps"]][:3], ["analyze", "ac-format", "plan"])
        # resume checks before detaching
        rc, out = self.cli("resume", *self.common())
        self.assertEqual(rc, cli.EXIT_REFUSED)
        self.assertIn("--answer one of: rerun, escalate", out)
        rc, out = self.cli("resume", *self.common(), "--answer", "continue")
        self.assertEqual(rc, cli.EXIT_REFUSED)
        note = os.path.join(self.w.tmp, "note.txt")
        with open(note, "w", encoding="utf-8") as f:
            f.write("try once more\n")
        rc, out = self.cli("resume", *self.common(), "--answer", "rerun", "--note-file", note, "--foreground",
                           units=W.units(self.w, results=res))
        self.assertEqual(rc, cli.EXIT_OK, out)
        self.assertIn("try once more", lifecycle.read_leader_decision(self.w.paths()))
        rc, out = self.cli("status", *self.common())
        self.assertIn("pull request 77", out)

    def test_resume_refusals_without_a_stop(self):
        rc, out = self.cli("resume", *self.common(), "--answer", "rerun")
        self.assertEqual(rc, cli.EXIT_REFUSED)
        self.assertIn("no engine state", out)

    def test_detached_dev_writes_rc_and_log(self):
        self.w.set_gh(W.gh_rules(labels=["gx:qa"]))  # promote: other
        rc, out = self.cli("dev", *self.common(), "--checkout", self.w.repo.path)
        self.assertEqual(rc, cli.EXIT_OK, out)
        self.assertIn("log: ", out)
        paths = self.w.paths()
        deadline = time.time() + 60
        while lifecycle.read_rc(paths) is None and time.time() < deadline:
            time.sleep(0.2)
        self.assertEqual(lifecycle.read_rc(paths), driver.EXIT_REFUSED)
        with open(paths.engine_log) as f:
            self.assertIn("refused:", f.read())
        rc, out = self.cli("status", *self.common(), "--wait", "5")
        self.assertEqual(rc, cli.EXIT_REFUSED)
        self.assertIn("engine finished, exit 4", out)
        self.assertIsNone(lifecycle.lock_holder(paths))


if __name__ == "__main__":
    unittest.main()
