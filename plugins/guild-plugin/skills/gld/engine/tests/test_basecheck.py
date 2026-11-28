"""VB1 basecheck (stage-4 scope §2.7 H12): TB1–TB4 and the records — the REAL srt, a temporary repository.

The free srt canary (a child `engine.py canary --srt-only`) runs for real in one test; the others replace it.
No LLM, no network.
"""

import argparse
import copy
import io
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from gxengine import basecheck, defaults, gitops, paths as pathsmod, repoconfig, runner, store
from tests.helpers.gitrepo import GitRepo
from tests.test_render import find_srt

ENGINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(ENGINE)))
SRT = find_srt()
REPO = "acme/app"
CONFIG = {"format": 1, "cache_env": {"npm_config_cache": "{cache}/npm"}, "commands": {
    "lint": {"cmd": "echo lint >> \"$npm_config_cache/order\""},
    "setup": {"cmd": "mkdir -p \"$npm_config_cache\"; echo setup >> \"$npm_config_cache/order\"; echo dep > deps.ignored"},
    "test": {"cmd": "test -f deps.ignored && echo test >> \"$npm_config_cache/order\""},
    "verify-gate": {"plugin": "verify-gate"}}}


class Base(unittest.TestCase):
    def setUp(self):
        if SRT is None:
            self.fail("srt not found (GLD_TEST_SRT / ~/.gld/srt / PATH)")
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="gx-bc-", dir="/tmp"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.repo = GitRepo.create(self.root, files={"README.md": "x\n", ".gitignore": "*.ignored\n", "src/a.txt": "a\n"})
        self.sha = self.repo.head()
        self.home = self.root + "/eng"
        self.user = self.root + "/home"
        os.makedirs(self.user + "/.claude-gx")
        self.env = dict(self.repo.env, HOME=self.user, PATH=os.environ["PATH"], CLAUDE_CONFIG_DIR=self.user + "/.claude-gx",
                        GLD_ENGINE_HOME=self.home)
        self.out = io.StringIO()
        p = mock.patch.object(basecheck, "_srt_canary")
        self.canary = p.start()
        self.addCleanup(p.stop)

    def config(self, drop=(), **cmds):
        raw = copy.deepcopy(CONFIG)
        for name in drop:
            del raw["commands"][name]
        for name, cmd in cmds.items():
            raw["commands"][name] = {"cmd": cmd}
        return raw

    def request(self, raw=None, **over):
        f = dict(repo=REPO, checkout=self.repo.path, sha=self.sha, config_text=raw if isinstance(raw, str) else json.dumps(raw or CONFIG),
                 engine_home=self.home, plugin_root=PLUGIN_ROOT, environ=self.env, srt=SRT, user_tmp=None, force=False, out=self.out)
        f.update(over)
        return basecheck.BaseCheckRequest(**f)

    def check(self, raw=None, **over):
        res = basecheck.check(self.request(raw, **over))
        self.assertNoTrace()
        return res

    def assertNoTrace(self):
        self.assertEqual(self.repo.git("worktree", "list", "--porcelain").count("worktree "), 1, "no worktree is left")
        self.assertEqual(self.repo.git("status", "--porcelain"), "")
        parent = os.path.join(self.home, "tmp", "acme", "app", basecheck.WORK_DIR)
        self.assertEqual(os.listdir(parent) if os.path.isdir(parent) else [], [])

    def rec(self, res):
        return store.read_record(pathsmod.EnginePaths(self.home, REPO, 1), res.record, "base-green")

    def order(self):
        with open(os.path.join(self.home, "cache", "acme", "app", "npm", "order")) as f:
            return f.read().split()


class Green(Base):
    def test_tb1_every_repository_command_setup_first_and_a_record(self):
        res = self.check()
        self.assertEqual((res.ok, res.red, res.flaky, res.problem, res.reused), (True, [], [], None, False), self.out.getvalue())
        self.assertEqual(self.order(), ["setup", "lint", "test"], "setup first, plugin checks never")
        rec = self.rec(res)
        self.assertEqual([c["name"] for c in rec["commands"]], ["setup", "lint", "test"])
        self.assertEqual(rec["plugin_version"], basecheck.plugin_version(PLUGIN_ROOT))
        self.assertEqual(os.path.basename(res.record), f"{self.sha}-{basecheck.config_sha256(json.dumps(CONFIG))[:16]}.json")
        log = os.path.join(os.path.dirname(res.record), os.path.basename(res.record)[:-5] + ".logs", rec["commands"][0]["runs"][0]["log_file"])
        self.assertTrue(os.path.isfile(log))

    def test_tb1_the_same_pair_is_not_run_again(self):
        self.check()
        res = self.check()
        self.assertEqual((res.ok, res.reused), (True, True))
        self.assertEqual(len(self.order()), 3)
        self.assertEqual(self.canary.call_count, 1)
        self.assertFalse(self.check(force=True).reused)
        self.assertEqual(len(self.order()), 6)

    def test_another_commit_or_other_settings_are_another_pair(self):
        self.check()
        self.repo.write("src/a.txt", "b\n")
        old, self.sha = self.sha, self.repo.commit("next")
        self.assertFalse(self.check().reused)
        self.sha = old
        self.assertFalse(self.check(self.config(lint="true")).reused)
        self.assertTrue(self.check().reused)

    def test_the_commit_is_checked_not_the_checkout(self):
        self.repo.write("src/a.txt", "dirty\n")
        res = basecheck.check(self.request(self.config(lint="grep -q '^a$' src/a.txt && test ! -e untracked.txt")))
        self.assertTrue(res.ok, self.out.getvalue())
        self.repo.git("checkout", "--", ".")

    def test_a_broken_record_is_run_again(self):
        res = self.check()
        with open(res.record, "w") as f:
            f.write("{}")
        self.assertFalse(self.check().reused)

    def test_worktree_prepare_copies_what_the_engine_copies(self):
        for rel in ("gen/a.ignored", "gen/CLAUDE.md", "gen/key.pem"):
            self.repo.write(rel, "x\n")
        os.symlink("a.ignored", os.path.join(self.repo.path, "gen", "link.ignored"))
        raw = self.config(lint="test -f gen/a.ignored && test ! -e gen/CLAUDE.md && test ! -e gen/key.pem && test ! -e gen/link.ignored")
        raw["worktree_prepare"] = [{"copy": "gen/**"}]
        raw["secret_paths"] = ["*.pem", "**/*.pem"]
        res = basecheck.check(self.request(raw))
        self.assertTrue(res.ok, self.out.getvalue())

    def test_the_commands_take_the_heavy_run_lock(self):
        seen, real = [], runner.run_named

        def spy(*a, heavy_lock=None, **kw):
            seen.append(heavy_lock)
            return real(*a, heavy_lock=heavy_lock, **kw)
        with mock.patch.object(runner, "run_named", spy):
            self.check()
        self.assertEqual(set(seen), {pathsmod.heavy_run_lock(self.home)})


class Red(Base):
    def test_tb2_red_twice(self):
        res = self.check(self.config(test="exit 3"))
        self.assertEqual((res.ok, res.red, res.problem), (False, ["test"], None))
        rec = self.rec(res)
        self.assertEqual([r["exit_code"] for r in rec["commands"][-1]["runs"]], [3, 3])
        self.assertFalse(self.check(self.config(test="exit 3")).reused, "a red record is checked again")

    def test_tb2_red_then_green_is_flaky_and_green(self):
        cmd = "test -f \"$npm_config_cache/seen\" && exit 0; touch \"$npm_config_cache/seen\"; exit 1"
        res = self.check(self.config(test=cmd))
        self.assertEqual((res.ok, res.red, res.flaky), (True, [], ["test"]))
        self.assertIn("flaky", self.out.getvalue())
        self.assertEqual(self.check(self.config(test=cmd)).flaky, ["test"], "a reused record keeps it")

    def test_tb3_a_dirty_tree_is_red_and_not_run_again(self):
        res = self.check(self.config(lint="echo x > left.txt; exit 1", test="test ! -e left.txt && test -f deps.ignored"))
        self.assertEqual(res.red, ["lint"])
        c = {x["name"]: x for x in self.rec(res)["commands"]}
        self.assertEqual((len(c["lint"]["runs"]), c["lint"]["dirty_files"]), (1, ["left.txt"]))
        self.assertTrue(c["test"]["ok"], "the tree is put back, ignored files (the dependencies) stay")

    def test_a_green_command_that_leaves_changes_is_red(self):
        res = self.check(self.config(lint="echo changed > src/a.txt"))
        self.assertEqual(res.red, ["lint"])
        self.assertEqual(self.rec(res)["commands"][1]["dirty_files"], ["src/a.txt"])

    def test_a_command_that_commits_is_red(self):
        res = self.check(self.config(lint="git -c user.name=r -c user.email=r@x.invalid commit -q --allow-empty -m x"))
        self.assertEqual((res.red, self.rec(res)["commands"][1]["dirty_files"]), (["lint"], ["HEAD moved"]))

    def test_a_red_setup_stops_there(self):
        res = self.check(self.config(setup="exit 1"))
        self.assertEqual((res.ok, res.red), (False, ["setup"]))
        rec = self.rec(res)
        self.assertEqual([(c["name"], len(c["runs"]), c["ok"]) for c in rec["commands"]],
                         [("setup", 2, False), ("lint", 0, False), ("test", 0, False)])

    def test_every_red_command_is_named(self):
        self.assertEqual(self.check(self.config(lint="false", test="false")).red, ["lint", "test"])

    def test_a_timeout_is_red(self):
        class Short(repoconfig.RepoConfig):
            def command(self, name):
                return dict(super().command(name), timeout_s=2 if name == "test" else 60)
        with mock.patch.object(basecheck.repoconfig, "RepoConfig", Short):
            res = self.check(self.config(test="sleep 31"))
        self.assertEqual(res.red, ["test"])
        self.assertTrue(self.rec(res)["commands"][-1]["runs"][0]["timed_out"])


class Problems(Base):
    def problem(self, raw=None, **over):
        res = basecheck.check(self.request(raw, **over))
        self.assertFalse(res.ok)
        self.assertEqual(res.red, [])
        self.assertEqual(self.rec(res)["problem"], res.problem)
        self.assertFalse(basecheck.check(self.request(raw, **over)).reused)
        return res.problem

    def test_settings_that_cannot_be_used(self):
        for raw in ("{", '{"format": 1}', json.dumps({"format": 1, "commands": {"verify-gate": {"plugin": "verify-gate"}}}),
                    json.dumps(dict(CONFIG, sprint={"capacity": 3}))):
            with self.subTest(raw=raw[:40]):
                self.assertEqual(self.problem(raw), "config")

    def test_tb4_no_worktree(self):
        self.assertEqual(self.problem(sha="a" * 40), "worktree")
        self.assertEqual(self.problem(checkout=self.root + "/nowhere"), "worktree")
        linked = self.repo.add_worktree(os.path.join(self.root, "linked"), "other")
        self.assertEqual(self.problem(checkout=linked if isinstance(linked, str) else os.path.join(self.root, "linked")), "worktree")
        with mock.patch.object(gitops, "detached_worktree", side_effect=gitops.GitError("no space")):
            self.assertEqual(self.problem(), "worktree")

    def test_no_srt_or_a_failing_canary(self):
        self.assertEqual(self.problem(srt=None), "srt-canary")
        self.canary.side_effect = basecheck._Problem("srt-canary", "failed")
        with mock.patch.object(runner, "run_named", side_effect=AssertionError("nothing may run")):
            self.assertEqual(self.problem(), "srt-canary")

    def test_toolchain_prepare(self):
        raw = self.config()
        raw["toolchain_prepare"] = [{"name": "warm", "cmd": "exit 1"}]
        self.assertEqual(self.problem(raw), "prepare")
        raw["toolchain_prepare"] = [{"name": "sdk", "sync": {"from": ["/nonexistent-sdk"], "to": "sdk"}}]
        self.assertEqual(self.problem(raw), "prepare")

    def test_an_engine_failure_is_never_green(self):
        with mock.patch.object(runner, "run_named", side_effect=runner.RunnerError("boom")):
            self.assertEqual(self.problem(), "engine-error")

    def test_an_unwritable_srt_is_an_engine_error(self):
        self.assertEqual(self.problem(srt="/nonexistent/srt"), "engine-error")

    def test_a_dead_checks_leftovers_are_removed(self):
        dead = os.path.join(self.home, "tmp", "acme", "app", basecheck.WORK_DIR, "999999")
        os.makedirs(dead)
        self.repo.git("worktree", "add", "-q", "--detach", os.path.join(dead, basecheck.TREE), self.sha)
        self.assertTrue(self.check().ok)
        self.assertFalse(os.path.exists(dead))


class Measure(Base):
    def test_only_the_named_commands_and_nothing_recorded(self):
        raw = self.config(lint="true", test="exit 1")
        self.assertEqual(basecheck.measure(self.request(raw), ["test"]), [])
        self.assertEqual(basecheck.measure(self.request(raw), ["lint"]), ["lint"])
        self.assertEqual(self.order(), ["setup", "setup"])
        folder = os.path.join(self.home, "records", "acme", "app", "base-green")
        self.assertEqual([n for n in os.listdir(folder) if n.endswith(".json")], [])
        self.assertNoTrace()


class Cli(Base):
    def run_cli(self, **over):
        ns = argparse.Namespace(**dict(dict(repo=REPO, checkout=self.repo.path, sha=None, config=None, force=False, json=True), **over))
        out = io.StringIO()
        rc = basecheck.run_cli(ns, self.env, out, plugin_root=PLUGIN_ROOT, srt=SRT, user_tmp=None)
        return rc, out.getvalue()

    def test_the_committed_settings_of_head(self):
        rc, out = self.run_cli()
        self.assertEqual(rc, basecheck.EXIT_REFUSED)
        self.assertIn("not committed", out)
        self.repo.write(defaults.ENGINE_SETTINGS, json.dumps(CONFIG))
        self.repo.commit("settings")
        rc, out = self.run_cli()
        self.assertEqual(rc, 0, out)
        self.assertEqual((json.loads(out)["ok"], len(json.loads(out)["commands"])), (True, 3))

    def test_a_settings_file_and_the_exit_code(self):
        path = os.path.join(self.root, "draft.json")
        with open(path, "w") as f:
            json.dump(self.config(test="false"), f)
        rc, out = self.run_cli(config=path, sha=self.sha, json=False)
        self.assertEqual(rc, basecheck.EXIT_REFUSED)
        self.assertIn("RED: test", out)
        self.assertEqual(self.run_cli(config="/nonexistent")[0], basecheck.EXIT_REFUSED)

    def test_the_exit_codes_are_the_clis(self):
        from gxengine import cli
        self.assertEqual((basecheck.EXIT_OK, basecheck.EXIT_REFUSED), (cli.EXIT_OK, cli.EXIT_REFUSED))


class RealCanary(Base):
    """The child process: the real srt canary of exactly these settings decides."""

    def setUp(self):
        super().setUp()
        mock.patch.stopall()
        os.makedirs(self.home)

    def test_the_free_canary_runs_and_is_recorded(self):
        req = self.request()
        basecheck._srt_canary(req, pathsmod.engine_home(self.env))
        names = os.listdir(os.path.join(self.home, "canary"))
        self.assertEqual(len([n for n in names if n.endswith(".json")]), 1)
        self.assertEqual(os.listdir(os.path.join(self.home, "tmp", "base-check-canary")), [])

    def test_a_failing_child_is_a_problem(self):
        bad = os.path.join(self.root, "no-srt")
        with open(bad, "w") as f:
            f.write("#!/bin/sh\nexit 1\n")
        os.chmod(bad, 0o755)
        with self.assertRaises(basecheck._Problem) as c:
            basecheck._srt_canary(self.request(srt=bad), pathsmod.engine_home(self.env))
        self.assertEqual(c.exception.code, "srt-canary")


if __name__ == "__main__":
    unittest.main()
