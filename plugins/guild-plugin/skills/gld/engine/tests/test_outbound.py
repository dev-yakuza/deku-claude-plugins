"""U10 outbound: secret scan through the plugin-install-path gate (§7.6), close keywords and
full-width neutralising (§7.12 S10), the pre-push range check (S5). Scenarios E1–E4.

Secret-looking test values are assembled at run time so this file itself carries none.
"""

import os
import tempfile
import unittest

from gxengine import gitops, outbound
from tests.helpers.gitrepo import GitRepo

ENGINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN_ROOT = os.path.realpath(os.path.join(ENGINE, "..", "..", ".."))
AWS = "AKIA" + "Q" * 16
GH_PAT = "ghp_" + "a1" * 18
PRIVATE_KEY = "-----BEGIN " + "RSA PRIVATE KEY-----"


def fake_plugin(tmp, script):
    """A plugin root whose scanner is `script` (Python source)."""
    d = os.path.join(tmp, "plugin", "skills", "gld", "gates")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "gate_precommit.py"), "w", encoding="utf-8") as f:
        f.write(script)
    return os.path.join(tmp, "plugin")


class ScanText(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="gx-outbound-")
        self.tmp = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_the_real_plugin_scanner_is_used(self):
        self.assertTrue(os.path.isfile(outbound.gate_script(PLUGIN_ROOT)))
        self.assertEqual(outbound.scan_text("hello\nworld\n", PLUGIN_ROOT), [])
        self.assertEqual(outbound.scan_text(f"ok\nkey = {AWS}\nok\n{GH_PAT}\n", PLUGIN_ROOT), [2, 4])
        self.assertEqual(outbound.scan_text(f"x\n{PRIVATE_KEY}\n".encode(), PLUGIN_ROOT), [2])

    def test_binary_and_non_utf8_bytes_are_scanned(self):
        data = b"\x00\xff\xfe junk\n" + AWS.encode() + b"\x00\n"
        self.assertEqual(outbound.scan_text(data, PLUGIN_ROOT), [2])

    def test_blank_text_is_clean_without_a_call(self):
        plugin = fake_plugin(self.tmp, "import sys\nsys.exit(2)\n")
        self.assertEqual(outbound.scan_text("  \n\t\n", plugin), [])
        self.assertEqual(outbound.scan_text("", plugin), [])

    def test_a_scanner_that_cannot_judge_is_never_clean(self):
        cases = {
            "missing": None,
            "rc2": "import sys\nsys.exit(2)\n",
            "crash": "raise SystemExit(oops)\n",
            "usage": "import sys\nsys.exit(64)\n",
            "rc1-no-lines": "import sys\nsys.exit(1)\n",
            "rc0-with-hits": "print('SECRET-TEXT 1')\n",
            "garbage": "print('all good')\n",
        }
        for name, script in cases.items():
            root = os.path.join(self.tmp, name)
            plugin = fake_plugin(root, script) if script else os.path.join(root, "plugin")
            with self.subTest(name), self.assertRaises(outbound.ScanError):
                outbound.scan_text("some text\n", plugin)
        with self.assertRaises(outbound.ScanError):
            outbound.scan_text("x", "relative/plugin")
        with self.assertRaises(outbound.ScanError):
            outbound.scan_text("x", None)

    def test_scanner_runs_without_the_engine_credentials(self):
        plugin = fake_plugin(self.tmp, "import os, sys\n"
                                       "bad = [k for k in os.environ if 'TOKEN' in k or k.startswith('GH_')]\n"
                                       "sys.exit(1 if bad else 0)\n")
        old = dict(os.environ)
        os.environ["GH_TOKEN"] = "x"
        try:
            # rc 1 without a SECRET-TEXT line is "no verdict" → the env leaked
            self.assertEqual(outbound.scan_text("text\n", plugin), [])
        finally:
            os.environ.clear()
            os.environ.update(old)


class Neutralise(unittest.TestCase):
    def test_e4_mentions_refs_and_same_repo_urls(self):
        text = ("cc @alice and @org/team, see #12 and other/repo#3.\n"
                "PR https://github.com/acme/app/pull/7#issuecomment-99 and "
                "https://GitHub.com/Acme/App/issues/12.\n"
                "elsewhere: https://github.com/other/repo/issues/5 mail a@b.example\n")
        got = outbound.neutralise(text, "acme/app")
        self.assertNotIn("@", got)
        self.assertNotIn("#", got)
        self.assertIn("cc ＠alice and ＠org/team, see ＃12 and other/repo＃3.", got)
        self.assertIn("PR ＃7 and ＃12.", got)
        self.assertNotIn("acme/app/pull", got)
        self.assertNotIn("Acme/App/issues", got)
        self.assertIn("https://github.com/other/repo/issues/5", got)   # another repository: only @/# change
        self.assertIn("a＠b.example", got)

    def test_idempotent_and_repo_checked(self):
        once = outbound.neutralise("@x #1", "acme/app")
        self.assertEqual(outbound.neutralise(once, "acme/app"), once)
        with self.assertRaises(ValueError):
            outbound.neutralise("x", "acme")

    def test_e1_prepare_text_neutralises_and_scans(self):
        self.assertEqual(outbound.prepare_text("thanks @bob, fixes #3\n", "acme/app", PLUGIN_ROOT),
                         "thanks ＠bob, fixes ＃3\n")
        with self.assertRaises(outbound.SecretDetected) as cm:
            outbound.prepare_text(f"line one\ntoken {GH_PAT}\n", "acme/app", PLUGIN_ROOT)
        self.assertEqual(cm.exception.lines, [2])
        self.assertNotIn(GH_PAT, str(cm.exception))


class CloseKeywords(unittest.TestCase):
    def test_hits(self):
        for line in ("Fixes #12", "closes acme/app#3", "Resolved: GH-4", "fix(parser): null (#42)",
                     "Close https://github.com/a/b/issues/9", "FIXED #1 for real", "resolve the bug in #8",
                     "chore: x\tCLOSES   #77"):
            with self.subTest(line):
                self.assertEqual(outbound.find_close_keywords("subject\n\n" + line + "\n"), [line])

    def test_misses(self):
        for line in ("prefix #12", "fixture for #12", "Fix parser", "see #12", "hotfix #3", "bugfix #3",
                     "closer look at #4", "resolver ＃5", "fix ＃5", "closes nothing here"):
            with self.subTest(line):
                self.assertEqual(outbound.find_close_keywords(line), [])

    def test_keyword_list_is_the_documented_family(self):
        self.assertEqual(set(outbound.CLOSE_KEYWORDS),
                         {"close", "closes", "closed", "fix", "fixes", "fixed", "resolve", "resolves", "resolved"})


class PushRange(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="gx-outbound-git-")
        tmp = os.path.realpath(self._tmp.name)
        self.repo = GitRepo.create(tmp, files={"README.md": "init\n"})
        self.base = self.repo.head()
        self.ctx = gitops.create_issue_worktree(self.repo.path, os.path.join(tmp, ".gld-repo-1"), "gld/1",
                                                self.base, base_env=self.repo.env)
        self.wt = self.ctx.work_tree

    def tearDown(self):
        self._tmp.cleanup()

    def commit(self, rel, text, message):
        self.repo.write(rel, text, cwd=self.wt)
        return self.repo.commit(message, cwd=self.wt)

    def test_clean_range_passes(self):
        head = self.commit("src/a.py", "a = 1\n", "feat: add a\n\nRefs the plan.")
        self.assertIsNone(outbound.check_push_range(self.ctx, head, PLUGIN_ROOT))

    def test_e3_close_keyword_in_a_commit_message_names_the_commit(self):
        first = self.commit("a.txt", "a\n", "feat: a")
        bad = self.commit("b.txt", "b\n", "feat: b\n\nFixes #1")
        self.commit("c.txt", "c\n", "feat: c")
        with self.assertRaises(outbound.CloseKeyword) as cm:
            outbound.check_push_range(self.ctx, self.repo.head(cwd=self.wt), PLUGIN_ROOT)
        self.assertEqual(cm.exception.commit, bad)
        self.assertEqual(cm.exception.line, "Fixes #1")
        self.assertNotEqual(first, bad)

    def test_e2_secret_in_the_diff(self):
        head = self.commit("config/prod.txt", f"x = 1\nkey = {AWS}\n", "chore: config")
        with self.assertRaises(outbound.SecretDetected) as cm:
            outbound.check_push_range(self.ctx, head, PLUGIN_ROOT)
        self.assertEqual(cm.exception.source, "diff")

    def test_e2_secret_in_a_binary_file(self):
        with open(os.path.join(self.wt, "blob.bin"), "wb") as f:
            f.write(b"\x00\x01" + GH_PAT.encode() + b"\x00\n")
        head = self.repo.commit("add blob", cwd=self.wt)
        with self.assertRaises(outbound.SecretDetected) as cm:
            outbound.check_push_range(self.ctx, head, PLUGIN_ROOT)
        self.assertEqual(cm.exception.source, "diff")

    def test_e2_secret_in_a_commit_message(self):
        head = self.commit("a.txt", "a\n", f"feat: a\n\ndebug {GH_PAT}")
        with self.assertRaises(outbound.SecretDetected) as cm:
            outbound.check_push_range(self.ctx, head, PLUGIN_ROOT)
        self.assertEqual(cm.exception.source, "log")

    def test_s5_range_ignores_what_landed_on_main_after_the_recorded_base(self):
        self.repo.write("old.txt", f"{AWS}\n")
        moved = self.repo.commit("secret lands on main later")   # main moves; the recorded base does not
        head = self.commit("a.txt", "a\n", "feat: a")
        self.assertNotEqual(moved, self.base)
        self.assertIsNone(outbound.check_push_range(self.ctx, head, PLUGIN_ROOT))

    def test_scanner_failure_stops_the_push_check(self):
        head = self.commit("a.txt", "a\n", "feat: a")
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(outbound.ScanError):
                outbound.check_push_range(self.ctx, head, fake_plugin(t, "import sys\nsys.exit(2)\n"))


if __name__ == "__main__":
    unittest.main()
