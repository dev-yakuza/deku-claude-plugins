"""U2 — engine record layout (paths.py, design §4.3, §7.3, §7.12 S7, M6)."""

import os
import shutil
import tempfile
import unittest

from gxengine import paths as P


class Layout(unittest.TestCase):
    def setUp(self):
        self.ep = P.EnginePaths("/home/u/.gld", "acme/app", 42)

    def test_attributes(self):
        ep = self.ep
        issue = "/home/u/.gld/records/acme/app/42"
        self.assertEqual(ep.engine_home, "/home/u/.gld")
        self.assertEqual(ep.issue_dir, issue)
        self.assertEqual(ep.state, issue + "/state.json")
        self.assertEqual(ep.log, issue + "/log.jsonl")
        self.assertEqual(ep.engine_log, issue + "/engine.log")
        self.assertEqual(ep.engine_rc, issue + "/engine.rc")
        self.assertEqual(ep.lock, issue + "/lock")
        self.assertEqual(ep.runs, issue + "/runs")
        self.assertEqual(ep.cache, "/home/u/.gld/cache/acme/app")
        self.assertEqual(ep.srt_home, "/home/u/.gld/srt")
        self.assertEqual(ep.canary_dir, "/home/u/.gld/canary")
        self.assertEqual((ep.repo, ep.owner, ep.name, ep.issue), ("acme/app", "acme", "app", 42))

    def test_attempt_paths(self):
        ep = self.ep
        self.assertEqual(ep.attempt_dir("test", 2), ep.runs + "/test/2")
        self.assertEqual(ep.in_dir("test", 2), ep.runs + "/test/2/in")
        self.assertEqual(ep.attempt_file("test", 2, "facts.json"), ep.runs + "/test/2/facts.json")
        self.assertEqual(ep.run_tmp("test", 2), "/home/u/.gld/tmp/acme/app/42/test-2")

    def test_in_dir_is_not_inside_another_attempt(self):
        # S7: the role may read its own in/ only; no attempt's in/ is a prefix of another's.
        a, b = self.ep.in_dir("test", 1), self.ep.in_dir("test", 10)
        self.assertFalse(b.startswith(a + "/") or a.startswith(b + "/"))

    def test_records_and_role_writable_dirs_are_disjoint(self):
        ep = self.ep
        for w in (ep.cache, ep.run_tmp("dev", 1)):
            self.assertFalse(w.startswith(ep.records + "/"), w)

    def test_unsafe_names_refused(self):
        for repo in ("acme", "a/b/c", "../app", "acme/..", "acme/.", "acme/a b", "", "acme/", "/app", None):
            with self.subTest(repo=repo):
                with self.assertRaises(ValueError):
                    P.EnginePaths("/h", repo, 1)
        for issue in (0, -1, "1", True, 1.0):
            with self.subTest(issue=issue):
                with self.assertRaises(ValueError):
                    P.EnginePaths("/h", "a/b", issue)
        with self.assertRaises(ValueError):
            P.EnginePaths("rel/home", "a/b", 1)
        for step in ("../x", "A", "a/b", "", "a_b", "-a", "x" * 65):
            with self.subTest(step=step):
                with self.assertRaises(ValueError):
                    self.ep.attempt_dir(step, 1)
        for att in (0, -1, "1", True):
            with self.subTest(att=att):
                with self.assertRaises(ValueError):
                    self.ep.attempt_dir("test", att)
        for name in ("../state.json", "a/b", "in", "", ".hidden", ".."):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    self.ep.attempt_file("test", 1, name)

    def test_dotted_repo_names_allowed(self):
        ep = P.EnginePaths("/h", "my.org/app.js", 3)
        self.assertTrue(ep.issue_dir.endswith("/records/my.org/app.js/3"))

    def test_home_under_sandbox_tmp_refused(self):
        for h in ("/tmp/claude-502", "/tmp/claude-502/x", "/private/tmp/claude-1/gx"):
            with self.subTest(h=h):
                with self.assertRaises(ValueError):
                    P.EnginePaths(h, "a/b", 1)


class Stage3Files(unittest.TestCase):
    def test_local_records_sit_in_the_issue_folder(self):
        p = P.EnginePaths("/h/.gld", "acme/app", 42)
        self.assertEqual(p.followups_dry_run, "/h/.gld/records/acme/app/42/followups-dry-run.jsonl")
        self.assertEqual(p.security_findings, "/h/.gld/records/acme/app/42/security-findings.md")


class EngineHome(unittest.TestCase):
    def test_default_and_env(self):
        tmp = os.path.realpath(tempfile.mkdtemp(prefix="gx-home-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        self.assertEqual(P.engine_home({"HOME": tmp}), os.path.join(tmp, ".gld"))
        self.assertEqual(P.engine_home({"HOME": "/x", "GLD_ENGINE_HOME": tmp + "/e"}), tmp + "/e")
        self.assertEqual(P.engine_home({"HOME": tmp, "GLD_ENGINE_HOME": "~/eh"}), tmp + "/eh")

    def test_resolves_links_once(self):
        tmp = os.path.realpath(tempfile.mkdtemp(prefix="gx-home-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        os.mkdir(os.path.join(tmp, "real"))
        os.symlink(os.path.join(tmp, "real"), os.path.join(tmp, "ln"))
        self.assertEqual(P.engine_home({"GLD_ENGINE_HOME": tmp + "/ln"}), tmp + "/real")

    def test_refusals(self):
        for env in ({"GLD_ENGINE_HOME": "rel"}, {"HOME": ""}, {},
                    {"GLD_ENGINE_HOME": "/tmp/claude-502/gx"}, {"GLD_ENGINE_HOME": "/private/tmp/claude-502"}):
            with self.subTest(env=env):
                with self.assertRaises(ValueError):
                    P.engine_home(env)

    def test_link_into_sandbox_tmp_refused(self):
        tmp = os.path.realpath(tempfile.mkdtemp(prefix="gx-home-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        os.symlink("/tmp/claude-99999/x", os.path.join(tmp, "ln"))
        with self.assertRaises(ValueError):
            P.engine_home({"GLD_ENGINE_HOME": tmp + "/ln"})


class Helpers(unittest.TestCase):
    def test_issue_worktree(self):
        self.assertEqual(P.issue_worktree("/Users/u/projects/app", "app", 42), "/Users/u/projects/.gld-app-42")
        self.assertEqual(P.issue_worktree("/Users/u/projects/app/", "app", 42), "/Users/u/projects/.gld-app-42")
        with self.assertRaises(ValueError):
            P.issue_worktree("rel", "app", 1)
        with self.assertRaises(ValueError):
            P.issue_worktree("/a/b", "../x", 1)

    def test_specs(self):
        self.assertEqual(P.specs_dir(42), "docs/specs/42")
        self.assertEqual(P.procedure_path(42), "docs/specs/42/procedure.yaml")
        with self.assertRaises(ValueError):
            P.specs_dir(0)

    def test_srt_tmpdir(self):
        self.assertEqual(P.srt_tmpdir("ab12"), "/tmp/gx-ab12")
        for bad in ("", "a/b", "../x", "x" * 25, None):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    P.srt_tmpdir(bad)


if __name__ == "__main__":
    unittest.main()
