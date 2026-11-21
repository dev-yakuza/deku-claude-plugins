"""0.102.2 — every engine-run command in a check sandbox gets the rendered global git config.

~/.gitconfig is denyRead in the sandbox and git (and flutter/npm, which call git) abort on an unreadable global
config; 0.102.1 rendered it only for roles, local_dev and the gate, so `deps` (flutter pub get) failed with exit 6.
"""

import os
import re
import unittest

import _util  # noqa: F401

PORTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "skills", "gld", "engine", "workflows",
                     "dev", "ports.py")


class CheckEnv(unittest.TestCase):
    def setUp(self):
        with open(PORTS, encoding="utf-8") as fh:
            self.src = fh.read()

    def test_one_place_builds_a_check_env(self):
        self.assertEqual(len(re.findall(r"C\.child_env\(root_env, \{\}, role_dir=", self.src)), 1)
        helper = self.src[self.src.index("def check_env("):]
        helper = helper[:helper.index("return env")]
        self.assertIn("render_gitconfig", helper)

    def test_deps_suite_warm_net_use_it(self):
        for call in ("deps_main(worktree, rd, check_env(root_env, worktree, rd)", "suite_in_tree(worktree, base, cmds, owner, timeout_s, run_dir, check_env(root_env, worktree, run_dir)",
                     "warm_in_place(worktree, tree, run_dir, check_env(root_env, worktree, run_dir)", "check_env(root_env, worktree, rd), issue)"):
            self.assertIn(call, self.src)


if __name__ == "__main__":
    unittest.main()
