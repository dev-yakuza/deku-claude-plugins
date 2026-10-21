"""M0e under --full only: the real husky and lefthook, fetched with npx into a temporary npm cache inside the
test's own home (no global install, nothing outside the sandbox — m0-plan U7). Needs the network."""

import json
import os
import subprocess
import unittest

import helpers
from commit_base import CommitCase

HUSKY = "husky@9.1.7"
LEFTHOOK = "lefthook@2.2.2"


class RealManagers(CommitCase):
    install_hook = False

    def setUp(self):
        if not helpers.full_mode():
            raise unittest.SkipTest("needs npx: run with run_tests.sh --full")
        super().setUp()
        self.env.update({"npm_config_cache": os.path.join(self.tmp, "npm-cache"), "npm_config_userconfig": os.devnull,
                         "npm_config_update_notifier": "false", "npm_config_fund": "false",
                         "npm_config_audit": "false"})

    def npx(self, *args):
        out = subprocess.run(["npx", "--yes"] + list(args), cwd=self.repo, capture_output=True, text=True,
                             env=self.env, timeout=180)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        return out

    def leak_refused_and_plain_passes(self):
        self.write("studio/local/x")
        self.git("add", "-f", "studio/local/x")
        out = self.commit("leak")
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("machine-only", out.stdout + out.stderr)
        self.git("restore", "--staged", "studio/local/x")
        self.write("src/a.ts")
        self.git("add", "src/a.ts")
        out = self.commit("plain")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)

    def test_husky(self):
        self.write("package.json", json.dumps({"name": "fixture", "private": True,
                                                "devDependencies": {"husky": "9.1.7"}}))
        self.npx(HUSKY, "init")
        self.assertEqual(self.git("config", "core.hooksPath").stdout.strip(), ".husky/_")
        self.write(".husky/pre-commit", "true\n")  # husky init puts "npm test" there
        self.git("add", "package.json", ".husky/pre-commit")
        self.assertEqual(self.commit("husky").returncode, 0)  # the team's husky setup, before Studio's block
        out = self.hooks("install")
        self.assertEqual(out.returncode, 4, out.stderr)
        out = self.hooks("install", "--husky-apply")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.hooks("status").returncode, 0)
        # Studio's block in the tracked file is a harness commit (M0f): staged by check_commit, checked by the hook
        out = self.cc("--stage", "harness")
        self.assertEqual(out.returncode, 0, out.stderr + out.stdout)
        out = self.commit("studio: husky block")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.leak_refused_and_plain_passes()
        wt = os.path.join(self.tmp, "wt")
        self.git("worktree", "add", "-q", wt)
        self.write("studio/local/y", repo=wt)
        self.git("add", "-f", "studio/local/y", cwd=wt)
        # husky's generated .husky/_ is untracked: a new worktree runs no hook until husky is installed there;
        # status says so (finding, m0e-plan v2 §12.6)
        st = self.hooks("status", cwd=wt)
        self.assertNotEqual(st.returncode, 0)
        self.assertIn(".husky/_", st.stdout)
        out = subprocess.run(["npx", "--yes", HUSKY], cwd=wt, capture_output=True, text=True, env=self.env,
                             timeout=180)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.hooks("status", cwd=wt).returncode, 0)
        self.assertNotEqual(self.commit(cwd=wt).returncode, 0)

    def test_lefthook(self):
        self.write("lefthook.yml", "pre-commit:\n  commands:\n    noop:\n      run: \"true\"\n")
        self.npx(LEFTHOOK, "install")
        out = self.hooks("install")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.hooks("status").returncode, 0)
        self.git("add", "lefthook.yml")
        self.assertEqual(self.commit("lefthook").returncode, 0)
        self.leak_refused_and_plain_passes()
