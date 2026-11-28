"""gates/gate_precommit.py PreToolUse mode (P3-B): a commit of a repository OUTSIDE the session's
project folder (CLAUDE_PROJECT_DIR) passes with no import, no git call and no write.

Session 2 found the escape: the hook runs outside the sandbox and, for `git -C <dir> commit`,
imports `<dir>/.claude/guild/gates/scripts/local/*.py` and runs git with `<dir>`'s config.
The 0.98.7 behaviour without CLAUDE_PROJECT_DIR is kept (tests/gate_test.sh) and shown here too.
A `git` shim on PATH logs every call (then runs the real git) to prove "no git".
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest

from tests.helpers.gitrepo import GitRepo

ENGINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GATE = os.path.join(os.path.dirname(ENGINE), "gates", "gate_precommit.py")

EVIL = """import os
open(os.environ["GLD_EVIL_MARKER"], "w").write("imported")
def check(ctx):
    return [], []
"""


class OutsideProject(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="gx-gate-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.project = GitRepo.create(self.tmp, name="project", with_remote=False)
        self.outside = GitRepo.create(self.tmp, name="outside", with_remote=False)
        self.outside.write(".claude/guild/gates/scripts/local/evil.py", EVIL)
        self.outside.write("x.txt", "x\n")
        self.outside.git("add", "-A")
        self.marker = os.path.join(self.tmp, "imported")
        real_git = shutil.which("git")
        self.git_log = os.path.join(self.tmp, "git-calls.log")
        shim = os.path.join(self.tmp, "bin")
        os.makedirs(shim)
        with open(os.path.join(shim, "git"), "w") as f:
            f.write(f"#!/bin/sh\necho \"$PWD :: $*\" >> {self.git_log}\nexec {real_git} \"$@\"\n")
        os.chmod(os.path.join(shim, "git"), 0o755)
        self.env = dict(self.project.env, PATH=shim + ":" + os.environ.get("PATH", "/usr/bin:/bin"),
                        GLD_EVIL_MARKER=self.marker)
        self.env.pop("CLAUDE_PROJECT_DIR", None)

    def hook(self, command, project=True, cwd=None):
        env = dict(self.env)
        if project:
            env["CLAUDE_PROJECT_DIR"] = self.project.path
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
        return subprocess.run(["python3", "-I", GATE], input=payload, cwd=cwd or self.project.path, env=env,
                              capture_output=True, text=True, timeout=120)

    def git_calls(self):
        if not os.path.exists(self.git_log):
            return []
        with open(self.git_log) as f:
            return [ln for ln in f.read().splitlines() if ln]

    def test_outside_repo_is_left_alone(self):
        for cmd in (f"git -C {self.outside.path} commit -m x",
                    f"git -C '{self.outside.path}' commit -m x",
                    f"cd /tmp && git -C {self.outside.path} commit -qm 'x'"):
            with self.subTest(cmd=cmd):
                r = self.hook(cmd)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertFalse(os.path.exists(self.marker), "the outside repo's local check was imported")
                self.assertEqual(self.git_calls(), [], "git ran for an outside repository")
        self.assertFalse(os.path.exists(os.path.join(self.outside.path, ".claude", "guild", "gates", "findings.json")))
        self.assertFalse(os.path.exists(os.path.join(self.outside.path, ".claude", "guild", "memory")))

    def test_without_project_dir_the_old_behaviour_imports_it(self):
        """The contrast (0.98.7 behaviour kept when CLAUDE_PROJECT_DIR is unset)."""
        r = self.hook(f"git -C {self.outside.path} commit -m x", project=False)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.exists(self.marker))

    def test_symlink_inside_the_project_pointing_out_counts_as_outside(self):
        os.symlink(self.outside.path, os.path.join(self.project.path, "link"))
        r = self.hook("git -C link commit -m x")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(self.marker))
        self.assertEqual(self.git_calls(), [])

    def test_unresolvable_token_counts_as_outside(self):
        # (a backtick command is refused earlier by the 0.98.7 text guard — exit 2 — not tested here)
        for cmd in ("git -C \"$D\" commit -m x", "git -C ${D}/x commit -m x", "git -C 'unclosed commit -m x"):
            with self.subTest(cmd=cmd):
                r = self.hook(cmd)
                self.assertEqual(r.returncode, 0)
                self.assertEqual(self.git_calls(), [])

    def test_cwd_outside_the_project_without_c(self):
        r = self.hook("git commit -m x", cwd=self.outside.path)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(self.marker))
        self.assertEqual(self.git_calls(), [])

    def test_project_commits_are_still_checked(self):
        """Inside the project the gate still runs: a staged deletion of a test is blocked (exit 2)."""
        self.project.write("tests/test_a.py", "def test_a():\n    assert True\n")
        self.project.commit("add test")
        self.project.git("rm", "-q", "tests/test_a.py")
        for cmd in ("git commit -m drop", f"git -C {self.project.path} commit -m drop", "git -C . commit -m drop"):
            with self.subTest(cmd=cmd):
                r = self.hook(cmd)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertIn("tests/test_a.py", r.stdout + r.stderr)
        self.assertNotEqual(self.git_calls(), [])


if __name__ == "__main__":
    unittest.main()
