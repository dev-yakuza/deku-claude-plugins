"""K3 review r4 — the 1L check tools come from <base>'s manifests (M1: the reviewer's `github:` and
alias/`file:` probes), cached and locked (m5); net `env` from engine-side signals only (m1); the
check config files are <base>'s (m3); every command of a step is checked (m4)."""

import json
import os
import threading
import time
import unittest

import _util  # noqa: F401
from _k1 import git, repo, tmpdir

from guildcore import checks as CH
from workflows.dev import local_checks as LC
from workflows.dev import ports as PO

BASE_PKG = {"name": "x", "private": True, "devDependencies": {"remark-cli": "^12.0.1"}}
BRANCH_PKG = {"name": "x", "private": True, "devDependencies": {
    "remark-cli": "npm:left-pad@1.3.0",                     # alias substitution
    "cspell": "file:../../../../tmp/evil",                  # file: substitution
    "broken": "github:o/r"}}                                # unreachable through the proxy


class FakeInstall(object):
    def __init__(self, delay=0):
        self.calls, self.delay = [], delay

    def __call__(self, cmds, cwd, sb, tmp, env=None, hosts=None, timeout_s=1800):
        with open(os.path.join(cwd, "package.json")) as fh:
            self.calls.append((list(cmds), json.load(fh)))
        time.sleep(self.delay)
        os.makedirs(os.path.join(cwd, "node_modules", ".bin"), exist_ok=True)
        for t in ("remark", "cspell"):
            open(os.path.join(cwd, "node_modules", ".bin", t), "w").close()
        return CH.CheckResult(True, 0, False, "added 3 packages", [], 60), {}


class BaseTools(unittest.TestCase):
    def setUp(self):
        self.r = repo(self, {"package.json": json.dumps(BASE_PKG), "README.md": "x"})
        git(self.r, "switch", "-q", "-c", "feature/#7-x")
        with open(os.path.join(self.r, "package.json"), "w") as fh:
            json.dump(BRANCH_PKG, fh)
        git(self.r, "commit", "-qam", "branch manifests")
        self.saved = CH.deps_step
        self.addCleanup(setattr, CH, "deps_step", self.saved)
        self.env = {"GLD_ENGINE_RUNS": tmpdir(self)}
        os.environ["GLD_ENGINE_RUNS"] = self.env["GLD_ENGINE_RUNS"]
        self.addCleanup(os.environ.pop, "GLD_ENGINE_RUNS", None)

    def test_tools_install_from_base_never_the_branch(self):
        fake = FakeInstall()
        CH.deps_step = fake
        d = PO.deps_main(self.r, tmpdir(self), dict(os.environ), tools=["cspell", "remark"], base="main")
        self.assertEqual(len(fake.calls), 2)                             # K3r5-M1: suite (branch) + tools (base)
        self.assertEqual(fake.calls[0][1], BRANCH_PKG)                   # the suite/roles get the branch's deps
        cmds, pkg = fake.calls[1]
        self.assertEqual(pkg, BASE_PKG)                                  # the TOOLS: no github:, no alias, no file:
        self.assertIn("--no-save cspell remark", cmds[-1])
        self.assertEqual(os.path.realpath(os.path.join(self.r, "node_modules")),
                         os.path.realpath(os.path.join(d.suite_node, "node_modules")))   # the worktree = branch install
        self.assertNotEqual(os.path.dirname(os.path.dirname(d.node_bin)), d.suite_node)
        self.assertTrue(os.path.exists(os.path.join(d.node_bin, "remark")))
        self.assertEqual(LC.prepare("npx remark a.md", lambda x: False, None, d.node_bin, lambda n: None)[1], None)

    def test_cached_by_the_base_manifest_hash_and_locked(self):
        fake = FakeInstall(delay=0.3)
        CH.deps_step = fake
        ths = [threading.Thread(target=PO.deps_main, args=(self.r, tmpdir(self), dict(os.environ)),
                                kwargs={"tools": ["cspell"], "base": "main"}) for _ in range(2)]
        for t in ths:
            t.start()
        for t in ths:
            t.join()
        self.assertEqual(len(fake.calls), 2)                             # one per kind; the other thread reused both

    def test_branch_manifest_change_does_not_change_the_tool_dir(self):
        mans = PO.base_manifests(self.r, "main")
        self.assertEqual(json.loads(mans["package.json"]), BASE_PKG)
        self.assertEqual(PO.node_dir(self.r, mans, ["cspell"]), PO.node_dir(self.r, PO.base_manifests(self.r, "main"), ["cspell"]))


class NetEnv(unittest.TestCase):
    def test_only_engine_side_signals(self):
        red = CH.CheckResult(False, 1, False, "loading x [E]\nCouldn't resolve the package 'foo'", [], 60)
        self.assertIsNone(PO.net_env({"warm": "ok"}, red))                # a role-written loader error = RED
        self.assertTrue(PO.net_env({"warm": "failed(pub get)"}, red).startswith("warm-up failed"))
        self.assertIsNone(PO.net_env({"warm": "failed(x)"}, CH.CheckResult(True, 0, False, "", [], 60)))


class BaseConfigs(unittest.TestCase):
    def test_branch_configs_swapped_for_base_during_checks_only(self):
        r = repo(self, {"cspell.json": '{"words": []}', "analysis_options.yaml": "a: 1\n"})
        base = git(r, "rev-parse", "HEAD")
        with open(os.path.join(r, "cspell.json"), "w") as fh:
            fh.write('{"ignorePaths": ["**"]}')                           # the branch silences cspell
        with open(os.path.join(r, ".remarkrc"), "w") as fh:
            fh.write("{}")                                                # a branch-added config
        restore = PO.base_check_configs(r, base)
        self.assertEqual(json.load(open(os.path.join(r, "cspell.json"))), {"words": []})
        self.assertFalse(os.path.exists(os.path.join(r, ".remarkrc")))
        restore()
        self.assertEqual(open(os.path.join(r, "cspell.json")).read(), '{"ignorePaths": ["**"]}')
        self.assertTrue(os.path.exists(os.path.join(r, ".remarkrc")))


class EveryCommand(unittest.TestCase):
    def test_pipes_and_or_are_each_rewritten(self):
        has = {"scripts/x.sh", "scripts/y.sh"}.__contains__
        exp = lambda p: "/base/" + p                                      # noqa: E731
        which = {"bash": "/bin/bash", "grep": "/usr/bin/grep"}.get
        out, why = LC.prepare("bash scripts/x.sh | bash scripts/y.sh || bash scripts/y.sh", has, exp, None, which)
        self.assertIsNone(why)
        self.assertEqual(out.count("/base/scripts/"), 3)
        self.assertIn("not at <base>", LC.prepare("grep a | bash scripts/gone.sh", has, exp, None, which)[1])
        self.assertIn("unverifiable", LC.prepare("bash scripts/x.sh $(cat f)", has, exp, None, which)[1])


if __name__ == "__main__":
    unittest.main()


class K3r5(unittest.TestCase):
    def test_branch_npm_dependency_reaches_the_suite(self):
        r = repo(self, {"package.json": json.dumps(BASE_PKG)})
        git(r, "switch", "-q", "-c", "feat")
        pkg = dict(BASE_PKG, dependencies={"lodash": "^4.17.21"})
        with open(os.path.join(r, "package.json"), "w") as fh:
            json.dump(pkg, fh)
        os.environ["GLD_ENGINE_RUNS"] = tmpdir(self)
        self.addCleanup(os.environ.pop, "GLD_ENGINE_RUNS", None)
        saved = CH.deps_step
        self.addCleanup(setattr, CH, "deps_step", saved)
        fake = FakeInstall()

        def install(cmds, cwd, *a, **k):
            res = fake(cmds, cwd, *a, **k)
            if "lodash" in json.dumps(fake.calls[-1][1]):
                os.makedirs(os.path.join(cwd, "node_modules", "lodash"))
            return res
        CH.deps_step = install
        PO.deps_main(r, tmpdir(self), dict(os.environ), tools=["cspell"], base="main")
        self.assertTrue(os.path.isdir(os.path.join(r, "node_modules", "lodash")))      # what the suite resolves

    def test_cspell_keeps_only_added_words(self):
        base = json.dumps({"words": ["alpha"], "ignorePaths": ["build/**"], "language": "en"}).encode()
        branch = json.dumps({"words": ["alpha", "kanjiyomi"], "ignorePaths": ["**"], "enabled": False,
                             "ignoreRegExpList": [".*"], "language": "xx"}).encode()
        out, added = PO.merge_cspell(base, branch)
        self.assertEqual(added, ["kanjiyomi"])
        self.assertEqual(json.loads(out), {"words": ["alpha", "kanjiyomi"], "ignorePaths": ["build/**"], "language": "en"})

    def test_word_list_file_additions_only(self):
        r = repo(self, {"cspell.json": json.dumps({"dictionaryDefinitions": [{"name": "p", "path": "./words.txt"}]}),
                        "words.txt": "alpha\n"})
        base = git(r, "rev-parse", "HEAD")
        with open(os.path.join(r, "words.txt"), "w") as fh:
            fh.write("kanjiyomi\n")                                    # the branch dropped alpha, added a word
        restore = PO.base_check_configs(r, base)
        self.assertEqual(open(os.path.join(r, "words.txt")).read(), "alpha\nkanjiyomi\n")
        restore()
        self.assertEqual(open(os.path.join(r, "words.txt")).read(), "kanjiyomi\n")

    def test_crash_during_checks_is_repaired(self):
        r = repo(self, {"analysis_options.yaml": "a: 1\n"})
        base = git(r, "rev-parse", "HEAD")
        with open(os.path.join(r, "analysis_options.yaml"), "w") as fh:
            fh.write("a: 2\n")
        os.environ["GLD_ENGINE_RUNS"] = tmpdir(self)
        self.addCleanup(os.environ.pop, "GLD_ENGINE_RUNS", None)
        PO.base_check_configs(r, base)                                    # … and the engine dies here
        self.assertEqual(open(os.path.join(r, "analysis_options.yaml")).read(), "a: 1\n")
        self.assertEqual(PO.recover_check_backup(r), ["analysis_options.yaml"])
        self.assertEqual(open(os.path.join(r, "analysis_options.yaml")).read(), "a: 2\n")
        self.assertEqual(PO.recover_check_backup(r), [])

    def test_skipped_warmup_is_env(self):
        red = CH.CheckResult(False, 1, False, "Building native assets failed", [], 60)
        self.assertTrue(PO.net_env({"warm": "skipped(root flutter_test_config.dart)"}, red).startswith("warm-up skipped"))
