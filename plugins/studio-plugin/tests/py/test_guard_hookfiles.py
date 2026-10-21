"""M0e: the guard's P-HOOK rule (m0e-plan v2 §10, §12.5) — installed hook files carry "studio:hook"."""

import os

from stdo.hooks import templates as T
from test_guard_judge import JudgeCase


class HookFiles(JudgeCase):
    def setUp(self):
        super().setUp()
        g = os.path.join(self.repo, ".git")
        self.shim = os.path.join(g, "hooks", "pre-commit")
        with open(self.shim, "w") as f:
            f.write(T.shim())
        with open(os.path.join(g, "hooks", T.CHAINED), "w") as f:
            f.write("#!/bin/sh\nexit 0\n")
        os.makedirs(os.path.join(g, "studio"))
        with open(os.path.join(g, "studio", "pre-commit"), "w") as f:
            f.write(T.runner(["studio"]))
        os.makedirs(os.path.join(self.repo, ".husky"))
        self.husky = os.path.join(self.repo, ".husky", "pre-commit")
        with open(self.husky, "w") as f:
            f.write("npm test\n" + T.husky_block())
        self.lh = os.path.join(self.repo, "lefthook-local.yml")
        with open(self.lh, "w") as f:
            f.write(T.lefthook_block())
        # the repository copy (with hooks.py) comes from JudgeCase (the plugin's own files, M0f)

    def test_bash_writes_and_deletes_are_denied(self):
        for cmd in ("echo x > .git/hooks/pre-commit", "rm .git/hooks/pre-commit", "sed -i '' s/a/b/ .git/hooks/pre-commit",
                    "mv .git/hooks/pre-commit /tmp/x", "rm .git/hooks/pre-commit.studio-chained", "rm -rf .git/hooks",
                    "rm -rf .git/studio", "cp /tmp/x .git/studio/pre-commit", "echo exit 0 > .git/studio/other",
                    "echo >> .husky/pre-commit", "rm lefthook-local.yml", "sed -i '' /studio/d .husky/pre-commit"):
            self.assertDeny(cmd, "G-PROT")

    def test_reading_and_studio_scripts_pass(self):
        for cmd in ("cat .git/hooks/pre-commit", "cat .husky/pre-commit", "ls .git/studio",
                    "python3 .claude/studio/scripts/hooks.py install", "python3 .claude/studio/scripts/hooks.py status",
                    "git commit -m x"):
            self.assertPass(cmd)

    def test_a_foreign_hook_is_not_protected(self):
        with open(self.shim, "w") as f:
            f.write("#!/bin/sh\nexit 0\n")
        self.assertPass("echo x > .git/hooks/pre-commit")
        self.assertPass("rm .git/hooks/pre-commit.studio-chained")  # no shim: the chained file is not Studio's
        with open(self.husky, "w") as f:
            f.write("npm test\n")
        self.assertPass("echo x >> .husky/pre-commit")

    def test_shared_file_edits_keep_the_block(self):
        D = lambda tool, ti: self.decide(tool, ti)  # noqa: E731
        self.assertIsNone(D("Edit", {"file_path": self.husky, "old_string": "npm test", "new_string": "npm run lint"}))
        self.assertIsNone(D("Write", {"file_path": self.husky, "content": "npm run lint\n" + T.husky_block()}))
        self.assertEqual(D("Edit", {"file_path": self.husky, "old_string": "|| exit $?", "new_string": ""}).rule,
                         "G-PROT")
        self.assertEqual(D("Write", {"file_path": self.husky, "content": "npm test\n"}).rule, "G-PROT")
        self.assertEqual(D("Write", {"file_path": self.husky, "content": "x\n" + T.husky_block() + T.husky_block()})
                         .rule, "G-PROT")
        self.assertIsNone(D("Edit", {"file_path": self.lh, "old_string": T.BLOCK_END,
                                     "new_string": T.BLOCK_END + "\nskip_output: [meta]"}))
        self.assertEqual(D("Write", {"file_path": self.lh, "content": ""}).rule, "G-PROT")
        # inside .git: the whole file
        self.assertEqual(D("Write", {"file_path": self.shim, "content": T.shim()}).rule, "G-PROT")
        self.assertEqual(D("Write", {"file_path": os.path.join(self.repo, ".git", "studio", "x"), "content": ""}).rule,
                         "G-PROT")

    def test_no_early_exit_before_the_block(self):
        """Review MINOR 3."""
        for line in ("exit 0", "return 0", "exec true"):
            d = self.decide("Edit", {"file_path": self.husky, "old_string": "npm test", "new_string": "npm test\n" + line})
            self.assertIsNotNone(d, line)
            self.assertEqual(d.rule, "G-PROT")
        self.assertIsNone(self.decide("Edit", {"file_path": self.husky, "old_string": "npm test",
                                               "new_string": "npm test || exit 1"}))
        # an indented exit inside an if is not a stop before the block (M0f review 2 MINOR-3: column 0 only)
        self.assertIsNone(self.decide("Edit", {"file_path": self.husky, "old_string": "npm test",
                                               "new_string": "if [ -n \"$CI\" ]; then\n  exit 0\nfi\nnpm test"}))
        # after the block it does not stop Studio's check
        self.assertIsNone(self.decide("Write", {"file_path": self.husky,
                                                "content": "npm test\n" + T.husky_block() + "exit 0\n"}))

    def test_last_checked_is_state(self):
        self.assertDeny("echo {} > .claude/studio/local/last-checked.json", "G-PROT")
