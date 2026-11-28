"""U9 runner: named commands under the REAL srt in a temporary git repository (scope §5.2 O6, S14).

Green · red · timeout · dirty tree (O6) · moved HEAD · flaky · base red (S14: neither turns
red into green) · the srt empty-cwd rule · plugin check scripts · verify-gate (read-tree
temp tree, the real 0.98.7 gate, writes only in the temp tree, control-file pre-check) ·
toolchain prepare (outside srt, cache env + run_env, scrubbed env).

No LLM, no network. srt is looked up like tests/test_render.py; unlike there, a missing
srt is a FAILURE here (scope §6.2: srt is a stage-1 start condition).
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from gxengine import codes, gitops, procedure, render, repoconfig, runner
from tests.helpers.gitrepo import GitRepo
from tests.test_render import find_srt

ENGINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(ENGINE)))
FIX_AC = os.path.join(ENGINE, "tests", "fixtures", "ac")
SRT = find_srt()
ISSUE = 42

COMMANDS = {
    "setup": {"cmd": "echo setup-ran > \"$TMPDIR/setup-ran\""},
    "green": {"cmd": "true"},
    "red": {"cmd": "echo boom; exit 3"},
    "dirty": {"cmd": "echo x > new-file.txt"},
    "idea": {"cmd": "mkdir -p .idea && echo x > .idea/workspace.xml"},
    "commits": {"cmd": "git -c user.name=r -c user.email=r@x.invalid commit -q --allow-empty -m sneaky"},
    # red only where marker.txt exists (the Issue branch), green on the recorded base
    "only-here": {"cmd": "test ! -f marker.txt"},
    # red everywhere
    "base-red": {"cmd": "test -f absent-everywhere"},
    # red on the first call in this attempt's TMPDIR, green on the second; green on the base (no marker)
    "flaky": {"cmd": "[ -f marker.txt ] || exit 0; if [ -f \"$TMPDIR/seen\" ]; then exit 0; fi; "
                     "touch \"$TMPDIR/seen\"; exit 1"},
    "slow": {"cmd": "[ -f marker.txt ] || exit 0; sleep 30.137"},
    "slow-everywhere": {"cmd": "sleep 31"},
    "env": {"cmd": "printf '%s|%s|%s' \"$GLD_RUN_FLAG\" \"${GH_TOKEN:-none}\" \"$npm_config_cache\" > \"$TMPDIR/env.txt\""},
    # P3-Z decision 6: control-named files under a gitignored folder may be written by a run ...
    "unpack": {"cmd": "mkdir -p node_modules/x && printf 'rules\\n' > node_modules/x/AGENTS.md"},
    # ... but never a tracked one, nor a new one in a folder git does not ignore
    "tracked-agents": {"cmd": "printf 'x\\n' >> pkg/AGENTS.md"},
    "new-agents": {"cmd": "printf 'x\\n' > CLAUDE.md"},
    "node": {"cmd": "node -e 'console.log(\"node-ok\")'"},
    "ac-format": {"plugin": "ac-format"},
    "verify-gate": {"plugin": "verify-gate"},
    # VB6: two of these must not overlap; and one with a short limit (_ShortLimits) that is quick itself
    "order": {"cmd": "mkdir -p \"$npm_config_cache\"; echo start >> \"$npm_config_cache/order\"; sleep 0.7; "
                     "echo end >> \"$npm_config_cache/order\""},
    "slow-limit-quick": {"cmd": "true"},
}
CONFIG = {"format": 1, "commands": COMMANDS, "registry_hosts": ["registry.npmjs.org"],
          "cache_env": {"npm_config_cache": "{cache}/npm"}, "run_env": {"GLD_RUN_FLAG": "on"}}


class _ShortLimits(repoconfig.RepoConfig):
    """The schema's smallest limit is one minute; the timeout test needs seconds."""

    def command(self, name):
        c = super().command(name)
        if name.startswith("slow"):
            c["timeout_s"] = 2
        return c


def steps_procedure():
    steps = [{"id": n, "run": n} for n in COMMANDS]
    return procedure.Procedure({"format": 1, "issue": ISSUE, "revision": 1,
                                "origin": {"template": "t", "version": "1", "start": "1"}, "steps": steps})


class Base(unittest.TestCase):
    def setUp(self):
        if SRT is None:
            self.fail("srt not found (GLD_TEST_SRT / ~/.gld/srt / PATH) — a stage-1 start condition (scope §6.2)")
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="gx-run-", dir="/tmp"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.repo = GitRepo.create(self.root, files={
            "README.md": "init\n", ".gitignore": ".idea/\n*.log\nnode_modules/\n", "pkg/AGENTS.md": "pkg rules\n",
            "tests/test_a.py": "def test_a():\n    assert 1 == 1\n    assert 2 == 2\n"})
        self.base = self.repo.head()
        self.ctx = gitops.create_issue_worktree(self.repo.path, os.path.join(self.root, ".gld-repo-42"),
                                                "gld/42", self.base, base_env=self.repo.env)
        self.wt = self.ctx.work_tree
        self.repo.write("marker.txt", "issue branch\n", cwd=self.wt)
        self.repo.commit("issue work", cwd=self.wt)
        home = self.root + "/home"
        eng = self.root + "/eng"
        os.makedirs(home + "/.claude-gx")
        self.records = eng + "/records"
        self.cache = eng + "/cache/acme/repo"
        for d in (self.records, self.cache):
            os.makedirs(d)
        self.srt_tmp = "/tmp/gx-s" + os.urandom(6).hex()
        self.addCleanup(shutil.rmtree, self.srt_tmp, True)
        self.home = home
        self.eng = eng
        self.procedure = steps_procedure()
        self.base_env = {"PATH": os.environ.get("PATH", render.DEFAULT_PATH), "HOME": home,
                         "LANG": "en_US.UTF-8", "GH_TOKEN": "secret-token"}

    def paths(self, step, attempt=1):
        return {
            "home": self.home, "claude_config_dir": self.home + "/.claude-gx", "worktree": self.wt,
            "main_checkout": self.repo.path, "git_common_dir": self.ctx.common_dir,
            "own_worktree": self.ctx.git_dir, "engine_records": self.records,
            "run_tmp": f"{self.eng}/tmp/acme/repo/{ISSUE}/{step}-{attempt}", "cache": self.cache,
            "plugin_root": PLUGIN_ROOT, "issue": ISSUE, "srt_tmpdir": self.srt_tmp,
            "other_worktrees": [], "other_repo_roots": [],
        }

    def attempt_dir(self, step, attempt=1):
        return f"{self.records}/acme/repo/{ISSUE}/runs/{step}/{attempt}"

    def run_step(self, name, attempt=1, config=None, **kw):
        cfg = config or repoconfig.RepoConfig(json.loads(json.dumps(CONFIG)))
        return runner.run_step(self.ctx, cfg, self.procedure, self.procedure.step(name),
                               self.attempt_dir(name, attempt), self.base_env, SRT, PLUGIN_ROOT,
                               issue=ISSUE, attempt=attempt, paths=self.paths(name, attempt), **kw)

    def log(self, name, file="run.log", attempt=1):
        with open(os.path.join(self.attempt_dir(name, attempt), file), encoding="utf-8") as f:
            return f.read()

    def worktrees(self):
        return self.repo.git("worktree", "list", "--porcelain")


class NamedCommands(Base):
    def test_green(self):
        r = self.run_step("green")
        self.assertEqual(r.outcome, {"status": "done", "code": None, "detail": None, "stop": None})
        self.assertEqual(r.run, {"name": "green", "exit_code": 0, "timed_out": False, "log_file": "run.log",
                                 "rerun": None, "base_run": None})
        self.assertTrue(r.end_tree["clean"])
        with open(os.path.join(self.attempt_dir("green"), "srt.json"), encoding="utf-8") as f:
            srt = json.load(f)
        render.check_srt_settings(srt)
        self.assertFalse(os.path.exists(self.srt_tmp), "srt's own TMPDIR is removed after the run")

    def test_red_has_both_i8_extras_and_stays_red(self):
        r = self.run_step("only-here")
        self.assertEqual(r.outcome["detail"], codes.CheckFailedReason.RUN_NONZERO.value)
        self.assertEqual(r.outcome["code"], codes.FailureCode.CHECK_FAILED.value)
        self.assertEqual(r.run["exit_code"], 1)
        self.assertEqual(r.run["rerun"], {"exit_code": 1, "timed_out": False, "log_file": "run-rerun.log"})
        self.assertEqual(r.run["base_run"], {"exit_code": 0, "timed_out": False, "log_file": "run-base.log"})
        self.assertFalse(r.flaky)
        self.assertNotIn("base-tree", self.worktrees(), "the base worktree is removed")
        # the base run installs first (`setup`) on the fresh tree
        self.assertTrue(os.path.isfile(os.path.join(self.attempt_dir("only-here"), "run-base-setup.log")))

    def test_output_goes_to_the_log(self):
        r = self.run_step("red")
        self.assertEqual(r.run["exit_code"], 3)
        self.assertIn("boom", self.log("red"))

    def test_flaky_is_marked_but_still_red(self):
        """S14: a green rerun does not make the step green (I8)."""
        r = self.run_step("flaky")
        self.assertEqual(r.run["exit_code"], 1)
        self.assertEqual(r.run["rerun"]["exit_code"], 0)
        self.assertTrue(r.flaky)
        self.assertTrue(runner.is_flaky(r.run))
        self.assertEqual(r.outcome["status"], "failed")
        self.assertEqual(r.outcome["detail"], codes.CheckFailedReason.RUN_NONZERO.value)
        self.assertTrue(any("flaky" in n for n in r.notes))

    def test_base_red_stops_for_a_human(self):
        """S14: red on the recorded base → stop base-red (needs_human), never green."""
        r = self.run_step("base-red")
        self.assertEqual(r.run["base_run"]["exit_code"], 1)
        self.assertEqual(r.outcome, {"status": "needs_human", "code": None, "detail": None,
                                     "stop": codes.StopReason.BASE_RED.value})
        args, kw = runner.to_outcome_args(r.outcome)
        self.assertEqual((args, kw), (("stop",), {"stop": "base-red"}))

    def test_timeout_kills_the_group(self):
        """Only the process groups THIS test starts are looked at (never a machine-wide pgrep, so
        another session's `sleep` neither fails nor hides anything — Q4 report): every group the
        runner spawns is recorded, its `sleep` is seen inside it while the run is going, and after
        the run neither that pid nor any process of those groups is left."""
        groups, seen, stop = [], set(), threading.Event()
        real_popen = subprocess.Popen

        def spawn(*a, **kw):
            p = real_popen(*a, **kw)
            if kw.get("start_new_session"):
                groups.append(p.pid)              # start_new_session: the child leads its own group
            return p

        def in_groups(pattern=None):
            if not groups:
                return set()
            argv = ["pgrep", "-g", ",".join(str(g) for g in groups)] + (["-f", pattern] if pattern else [])
            return {int(x) for x in subprocess.run(argv, capture_output=True, text=True).stdout.split()}

        def watch():
            while not stop.wait(0.1):
                seen.update(in_groups("sleep 30.137"))

        cfg = _ShortLimits(json.loads(json.dumps(CONFIG)))
        th = threading.Thread(target=watch, daemon=True)
        th.start()
        try:
            with mock.patch.object(runner.subprocess, "Popen", side_effect=spawn):
                r = self.run_step("slow", config=cfg)
        finally:
            stop.set()
            th.join()
        self.assertTrue(r.run["timed_out"])
        self.assertIsNone(r.run["exit_code"])
        self.assertTrue(r.run["rerun"]["timed_out"])
        self.assertEqual(r.run["base_run"]["exit_code"], 0)
        self.assertEqual(r.outcome["detail"], codes.CheckFailedReason.RUN_TIMEOUT.value)
        self.assertTrue(groups, "the runner started its runs in their own process groups")
        self.assertTrue(seen, "the sleep ran inside a group the runner started (else this test proves nothing)")
        self.assertEqual(in_groups(), set(), "no process of the run's groups is left behind")
        for pid in seen:
            with self.assertRaises(ProcessLookupError, msg=f"sleep {pid} is still alive"):
                os.kill(pid, 0)

    def test_timeout_on_the_base_too_is_base_red(self):
        cfg = _ShortLimits(json.loads(json.dumps(CONFIG)))
        r = self.run_step("slow-everywhere", config=cfg)
        self.assertTrue(r.run["base_run"]["timed_out"])
        self.assertEqual(r.outcome["stop"], codes.StopReason.BASE_RED.value)

    def test_dirty_tree_is_run_dirty_tree_without_extras(self):
        """O6: a run that leaves a new file → check-failed run-dirty-tree, the engine does not revert."""
        r = self.run_step("dirty")
        self.assertEqual(r.run["exit_code"], 0)
        self.assertEqual(r.outcome["detail"], codes.CheckFailedReason.RUN_DIRTY_TREE.value)
        self.assertEqual(r.end_tree["dirty_files"], ["new-file.txt"])
        self.assertIsNone(r.run["rerun"])
        self.assertTrue(os.path.exists(os.path.join(self.wt, "new-file.txt")), "not reverted (§4.4-2)")

    def test_a_run_that_commits_is_run_dirty_tree(self):
        start = gitops.head(self.ctx)
        r = self.run_step("commits")
        self.assertNotEqual(r.end_head, start)
        self.assertEqual(r.outcome["detail"], codes.CheckFailedReason.RUN_DIRTY_TREE.value)

    def test_srt_starts_in_an_empty_folder_so_its_builtin_denies_miss_the_worktree(self):
        """Session 5: started in the worktree, srt refuses `.idea/` writes there (pnpm unpacking)."""
        r = self.run_step("idea")
        self.assertEqual(r.run["exit_code"], 0, self.log("idea"))
        self.assertEqual(r.outcome["status"], "done")
        cwd = os.path.join(self.paths("idea")["run_tmp"], "srt-cwd-main")
        self.assertEqual(os.listdir(cwd), [])
        # the contrast: srt started IN the worktree refuses the same write
        srt_json = os.path.join(self.attempt_dir("idea"), "srt.json")
        os.makedirs(self.srt_tmp, exist_ok=True)
        env = dict(self.base_env, TMPDIR=self.srt_tmp)
        env.pop("GH_TOKEN")
        p = subprocess.run([SRT, "--settings", srt_json, "-c", "mkdir -p .idea && echo y > .idea/other.xml"],
                           cwd=self.wt, env=env, capture_output=True, text=True, timeout=120)
        self.assertNotEqual(p.returncode, 0, p.stdout + p.stderr)

    def test_env_cache_run_env_and_scrub(self):
        r = self.run_step("env")
        self.assertEqual(r.outcome["status"], "done", self.log("env"))
        with open(os.path.join(self.paths("env")["run_tmp"], "env.txt")) as f:
            self.assertEqual(f.read(), f"on|none|{self.cache}/npm")

    def test_refusals(self):
        with self.assertRaises(runner.RunnerError):        # not a named command
            runner.run_step(self.ctx, CONFIG, None, {"id": "x", "run": "nope"}, self.attempt_dir("x"),
                            self.base_env, SRT, PLUGIN_ROOT, issue=ISSUE, attempt=1, paths=self.paths("x"))
        with self.assertRaises(runner.RunnerError):        # a role step
            runner.run_step(self.ctx, CONFIG, None, {"id": "d", "role": "developer", "outputs": []},
                            self.attempt_dir("d"), self.base_env, SRT, PLUGIN_ROOT, issue=ISSUE, attempt=1,
                            paths=self.paths("d"))
        with self.assertRaises(runner.RunnerError):        # srt must be an absolute executable
            runner.run_step(self.ctx, CONFIG, self.procedure, self.procedure.step("green"),
                            self.attempt_dir("green"), self.base_env, "srt", PLUGIN_ROOT, issue=ISSUE,
                            attempt=1, paths=self.paths("green"))
        self.repo.write("stray.txt", "x\n", cwd=self.wt)
        with self.assertRaises(runner.RunnerError):        # I7: a run starts only on a clean tree
            self.run_step("green")

    def test_attempt_folder_is_never_reused(self):
        self.run_step("green")
        with self.assertRaises(runner.RunnerError):
            self.run_step("green")


class PluginCommands(Base):
    def test_ac_format_runs_the_install_path_script(self):
        r = self.run_step("ac-format")
        self.assertEqual(r.run["exit_code"], 1, self.log("ac-format"))   # no analysis.md yet → fail
        self.assertIsNone(r.run["rerun"], "no I8 extras for plugin check scripts")
        self.assertEqual(r.outcome["detail"], codes.CheckFailedReason.RUN_NONZERO.value)
        with open(os.path.join(FIX_AC, "analysis-ok.md"), encoding="utf-8") as f:
            self.repo.write(f"docs/specs/{ISSUE}/analysis.md", f.read(), cwd=self.wt)
        self.repo.commit("analysis", cwd=self.wt)
        r = self.run_step("ac-format", attempt=2)
        self.assertEqual(r.outcome["status"], "done", self.log("ac-format", attempt=2))

    def test_plugin_line_refuses_unknown_names(self):
        with self.assertRaises(runner.RunnerError):
            runner.plugin_command_line("rm-rf", PLUGIN_ROOT, ISSUE)
        with self.assertRaises(runner.RunnerError):
            runner.plugin_command_line("ac-format", "/nonexistent/plugin", ISSUE)


class VerifyGate(Base):
    def ok_check(self, head):
        self.checked = head
        return {"ok": True, "changed": []}

    def test_clean_range_passes(self):
        self.repo.write("README.md", "init\nmore\n", cwd=self.wt)
        head = self.repo.commit("docs", cwd=self.wt)
        r = self.run_step("verify-gate", control_check=self.ok_check)
        self.assertEqual(self.checked, head, "the control-file check runs on the HEAD the gate judges")
        self.assertEqual(r.outcome["status"], "done", self.log("verify-gate"))
        self.assertNotIn("gate-tree", self.worktrees(), "the temp tree is thrown away")
        self.assertTrue(r.end_tree["clean"])

    def test_deleted_test_is_blocked_by_the_real_gate(self):
        self.repo.git("rm", "-q", "tests/test_a.py", cwd=self.wt)
        self.repo.commit("drop the test", cwd=self.wt)
        r = self.run_step("verify-gate", control_check=self.ok_check)
        self.assertEqual(r.run["exit_code"], 1, self.log("verify-gate"))
        self.assertIn("tests/test_a.py", self.log("verify-gate"))
        self.assertEqual(r.outcome["detail"], codes.CheckFailedReason.RUN_NONZERO.value)
        self.assertIsNone(r.run["rerun"])
        self.assertTrue(r.end_tree["clean"], "the gate wrote nothing into the Issue worktree")
        self.assertNotIn("gate-tree", self.worktrees())

    def test_writes_are_narrowed_to_the_temp_tree(self):
        self.run_step("verify-gate", control_check=self.ok_check)
        with open(os.path.join(self.attempt_dir("verify-gate"), "srt.json"), encoding="utf-8") as f:
            srt = json.load(f)
        tmp = self.paths("verify-gate")["run_tmp"]
        aw = srt["filesystem"]["allowWrite"]
        self.assertEqual(len(aw), 3, aw)
        self.assertTrue(all(p.startswith(tmp + "/") or "/worktrees/gate-tree" in p for p in aw), aw)
        self.assertNotIn(self.wt, aw)
        self.assertNotIn(self.cache, aw)

    def test_control_check_is_required_and_decides(self):
        with self.assertRaises(runner.RunnerError):
            self.run_step("verify-gate")
        r = self.run_step("verify-gate", attempt=2,
                          control_check=lambda h: {"ok": False, "changed": [".claude/x.md"]})
        self.assertIsNone(r.run)
        self.assertEqual(r.outcome["stop"], codes.StopReason.CONTROL_FILE.value)
        self.assertEqual(r.control_files, {"ok": False, "changed": [".claude/x.md"]})
        self.assertFalse(os.path.exists(os.path.join(self.attempt_dir("verify-gate", 2), "run.log")))


class OutputThroughAPipe(Base):
    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_node_starts_although_the_log_is_in_the_read_denied_records(self):
        # P3-Z base-green finding: with stdout = a file in the (read-denied) engine records, node
        # cannot fstat its stdio under srt and aborts at start-up; the runner pipes the output
        r = self.run_step("node")
        self.assertEqual(r.run["exit_code"], 0, self.log("node"))
        self.assertIn("node-ok", self.log("node"))


class ControlFilesInRuns(Base):
    """P3-Z decision 6, real srt: the run's deny is per folder git does not ignore."""

    def test_gitignored_agents_md_may_be_unpacked(self):
        r = self.run_step("unpack")
        self.assertEqual(r.outcome["status"], "done", self.log("unpack"))
        self.assertTrue(os.path.isfile(os.path.join(self.wt, "node_modules", "x", "AGENTS.md")))
        self.assertTrue(r.end_tree["clean"])

    def test_tracked_agents_md_is_refused(self):
        r = self.run_step("tracked-agents")
        self.assertNotEqual(r.run["exit_code"], 0, self.log("tracked-agents"))
        with open(os.path.join(self.wt, "pkg", "AGENTS.md")) as f:
            self.assertEqual(f.read(), "pkg rules\n")

    def test_new_claude_md_in_a_tracked_folder_is_refused(self):
        r = self.run_step("new-agents")
        self.assertNotEqual(r.run["exit_code"], 0, self.log("new-agents"))
        self.assertFalse(os.path.exists(os.path.join(self.wt, "CLAUDE.md")))

    def test_rendered_denies_name_the_tracked_folders(self):
        self.run_step("green")
        with open(os.path.join(self.attempt_dir("green"), "srt.json"), encoding="utf-8") as f:
            deny = json.load(f)["filesystem"]["denyWrite"]
        for d in (self.wt, self.wt + "/pkg", self.wt + "/tests"):
            self.assertIn(d + "/AGENTS.md", deny)
            self.assertIn(d + "/CLAUDE.md", deny)
        self.assertNotIn(self.wt + "/**/AGENTS.md", deny)
        self.assertIn(self.wt + "/**/.claude", deny)                  # .claude stays denied everywhere
        self.assertIn(self.repo.path + "/**/AGENTS.md", deny)         # the main checkout keeps the glob


class ToolchainPrepare(Base):
    """P3-Z decision 4: outside srt only a file copy from a trusted source; commands run in srt."""

    def setUp(self):
        super().setUp()
        self.src = self.root + "/sdk-src"
        os.makedirs(self.src + "/bin")
        os.makedirs(self.src + "/lib/deep")
        self._w(self.src + "/bin/tool", "#!/bin/sh\necho tool-ran > \"$TMPDIR/tool-ran\"\n", 0o755)
        self._w(self.src + "/lib/a.txt", "a\n")
        self._w(self.src + "/lib/deep/b.txt", "b\n")
        os.symlink("lib/a.txt", self.src + "/link")
        self.elsewhere = self.root + "/elsewhere"
        os.makedirs(self.elsewhere)
        self._w(self.elsewhere + "/keep.txt", "keep\n")
        # the temp-area rule would refuse a source under /tmp (this test's root): lifted for the test
        patcher = mock.patch.object(repoconfig, "TEMP_AREAS", ())
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def _w(path, text, mode=0o644):
        with open(path, "w") as f:
            f.write(text)
        os.chmod(path, mode)

    def cfg(self, entries):
        raw = json.loads(json.dumps(CONFIG))
        raw["toolchain_prepare"] = entries
        raw["cache_env"]["GLD_SDK"] = "{cache}/sdk"
        return repoconfig.RepoConfig(raw)

    def prepare(self, cfg, attempt=1):
        return runner.toolchain_prepare(self.ctx, cfg, self.base_env, SRT, paths=self.paths("prep", attempt),
                                        attempt_dir=self.attempt_dir("prep", attempt), step_id="prep",
                                        attempt=attempt, issue=ISSUE)

    def tree(self, root):
        out = {}
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            for n in dirnames + filenames:
                full = os.path.join(dirpath, n)
                rel = os.path.relpath(full, root)
                if os.path.islink(full):
                    out[rel] = ("link", os.readlink(full))
                elif os.path.isdir(full):
                    out[rel] = ("dir", None)
                else:
                    with open(full, "rb") as f:
                        out[rel] = ("file", f.read(), os.stat(full).st_mode & 0o777)
        return out

    def test_copy_then_command_in_srt_and_nothing_runs_outside(self):
        cfg = self.cfg([{"name": "sdk", "sync": {"from": ["/nonexistent-sdk", self.src], "to": "sdk"}},
                        {"name": "precache", "cmd": "\"$GLD_SDK/bin/tool\""}])
        spawned = []
        real_popen = subprocess.Popen

        def spy(argv, *a, **kw):
            spawned.append(list(argv))
            return real_popen(argv, *a, **kw)
        with mock.patch.object(subprocess, "Popen", spy):
            got = self.prepare(cfg)
        self.assertEqual([(r["name"], r["kind"], r["ok"]) for r in got], [("sdk", "sync", True), ("precache", "cmd", True)])
        self.assertEqual(self.tree(self.cache + "/sdk"), self.tree(self.src))
        self.assertTrue(os.path.isfile(self.paths("prep")["run_tmp"] + "/tool-ran"), "the command ran (inside srt)")
        for argv in spawned:                     # only git (the engine's) and srt; never a cache file
            self.assertIn(os.path.basename(argv[0]), ("git", "srt"), argv)
            self.assertFalse(any(str(x).startswith(self.cache) for x in argv[:1]), argv)
        self.assertEqual([a[0] for a in spawned if os.path.basename(a[0]) == "srt"], [SRT])

    def test_a_tampered_copy_is_restored_before_anything_runs(self):
        cfg = self.cfg([{"name": "sdk", "sync": {"from": [self.src], "to": "sdk"}},
                        {"name": "precache", "cmd": "\"$GLD_SDK/bin/tool\""}])
        self.prepare(cfg)
        dst = self.cache + "/sdk"
        # an earlier Issue's role / run (the cache is writable for them) plants things
        self._w(dst + "/bin/tool", "#!/bin/sh\ntouch " + self.root + "/planted\n", 0o755)
        self._w(dst + "/extra.sh", "#!/bin/sh\n", 0o755)
        os.unlink(dst + "/link")
        os.symlink(self.elsewhere + "/keep.txt", dst + "/link")
        shutil.rmtree(dst + "/lib")
        os.symlink(self.elsewhere, dst + "/lib")                       # a folder swapped for a link
        os.chmod(dst + "/bin", 0o555)
        got = self.prepare(cfg, attempt=2)
        self.assertTrue(all(r["ok"] for r in got), got)
        self.assertEqual(self.tree(dst), self.tree(self.src))
        self.assertFalse(os.path.exists(self.root + "/planted"), "the planted binary never ran")
        self.assertEqual(self.tree(self.elsewhere), {"keep.txt": ("file", b"keep\n", 0o644)}, "links were not followed")

    def test_a_command_is_confined_and_stops_the_rest(self):
        cfg = self.cfg([{"name": "escape", "cmd": f"touch {self.root}/outside"},
                        {"name": "never", "cmd": f"touch {self.cache}/never"}])
        got = self.prepare(cfg)
        self.assertEqual([(r["name"], r["ok"]) for r in got], [("escape", False)])
        self.assertFalse(os.path.exists(self.root + "/outside"), "srt refused the write outside the run boundary")
        self.assertFalse(os.path.exists(self.cache + "/never"))

    def test_sources_inside_writable_folders_or_missing(self):
        for src in (self.cache, self.wt + "/tests", self.eng, self.records):
            with self.subTest(src=src), self.assertRaises(runner.RunnerError):
                self.prepare(self.cfg([{"name": "sdk", "sync": {"from": [src], "to": "sdk"}}]))
        got = self.prepare(self.cfg([{"name": "sdk", "sync": {"from": ["/nonexistent-a", "/nonexistent-b"], "to": "sdk"}}]))
        self.assertEqual([(r["name"], r["ok"]) for r in got], [("sdk", False)])
        self.assertIn("no source folder", got[0]["note"])


# The group leader forks a child that leaves the run's process group (setsid) and keeps the
# output pipe open until `stop` exists (bounded at 60 s). The leader waits until the child has
# left the group and written its line, then ends (argv[3] = "exit") or sleeps past the time
# limit ("sleep"). No machine-wide process search: the child's pid comes back in a file.
_ESCAPE = r"""
import os, sys, time
stop, pid_file, mode = sys.argv[1], sys.argv[2], sys.argv[3]
os.write(1, b"leader-out\n")
r, w = os.pipe()
if os.fork() == 0:
    os.close(r)
    os.setsid()
    os.write(1, b"escaped-before-cut\n")
    with open(pid_file, "w") as f:
        f.write(str(os.getpid()))
    os.write(w, b"x")
    os.close(w)
    end = time.monotonic() + 60
    while time.monotonic() < end and not os.path.exists(stop):
        time.sleep(0.05)
    os._exit(0)
os.close(w)
os.read(r, 1)
if mode == "sleep":
    time.sleep(30)
os._exit(0)
"""


class OutputPipeHeldOutsideTheGroup(unittest.TestCase):
    """Q5 measured, Q6 fixed: a process outside the run's group that holds the output pipe
    no longer keeps `_spawn_group` waiting past DRAIN_S; the log keeps what was read and is
    marked as cut."""

    def setUp(self):
        self.dir = os.path.realpath(tempfile.mkdtemp(prefix="gx-drain-"))
        self.stop = os.path.join(self.dir, "stop")
        self.pid_file = os.path.join(self.dir, "escaped.pid")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.addCleanup(lambda: open(self.stop, "w").close())   # lets the escaped child end

    def spawn(self, mode, timeout_s=30):
        argv = [sys.executable, "-I", "-c", _ESCAPE, self.stop, self.pid_file, mode]
        log = os.path.join(self.dir, "run.log")
        with mock.patch.object(runner, "DRAIN_S", 0.5):
            t = time.monotonic()
            rc, timed_out, secs = runner._spawn_group(argv, self.dir, dict(os.environ), timeout_s, log, self.dir)
            elapsed = time.monotonic() - t
        with open(log, "rb") as f:
            return rc, timed_out, elapsed, f.read().decode()

    def assert_escaped_child_still_running(self):
        with open(self.pid_file) as f:
            pid = int(f.read())
        os.kill(pid, 0)          # still alive (it waits for `stop`): the pipe really was held open

    def assert_cut_log(self, text):
        mark = runner.OUTPUT_CUT_MARK.format(s=0.5)
        self.assertIn("leader-out\n", text)
        self.assertIn("escaped-before-cut\n", text)
        self.assertTrue(text.endswith(mark), text)
        self.assertEqual(text.count(mark), 1)

    def test_returns_after_drain_when_the_leader_exits(self):
        rc, timed_out, elapsed, text = self.spawn("exit")
        self.assertEqual((rc, timed_out), (0, False))
        self.assertLess(elapsed, 8.0, "waited for the escaped child instead of DRAIN_S")
        self.assert_escaped_child_still_running()
        self.assert_cut_log(text)

    def test_returns_after_the_time_limit_and_drain(self):
        rc, timed_out, elapsed, text = self.spawn("sleep", timeout_s=1)
        self.assertEqual((rc, timed_out), (None, True))
        self.assertLess(elapsed, 9.0, "waited for the escaped child instead of the limit + DRAIN_S")
        self.assert_escaped_child_still_running()
        self.assert_cut_log(text)

    def test_a_closed_pipe_leaves_the_log_unmarked(self):
        argv = [sys.executable, "-I", "-c", "import sys; sys.stdout.write('a\\n'); sys.stderr.write('b\\n')"]
        log = os.path.join(self.dir, "run.log")
        rc, timed_out, _ = runner._spawn_group(argv, self.dir, dict(os.environ), 30, log, self.dir)
        self.assertEqual((rc, timed_out), (0, False))
        with open(log) as f:
            self.assertEqual(sorted(f.read().splitlines()), ["a", "b"])


HOLDER = ("import fcntl, os, sys\n"
          "fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o600)\n"
          "fcntl.flock(fd, fcntl.LOCK_EX)\n"
          "print('held', flush=True)\n"
          "sys.stdin.read()\n")


class HeavyRuns(Base):
    """Stage 4 (H22, VB6): one repository command at a time on this machine — TH1–TH4."""

    def setUp(self):
        super().setUp()
        self.lock = os.path.join(self.eng, "heavy-run.lock")
        self.done = []

    def hold(self):
        """Another engine's process that holds the lock until its stdin closes."""
        p = subprocess.Popen([sys.executable, "-I", "-c", HOLDER, self.lock], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, text=True)
        self.addCleanup(self.end, p)
        self.assertEqual(p.stdout.readline(), "held\n")
        return p

    def end(self, p, kill=False):
        if p.poll() is None and kill:
            p.kill()
        if not p.stdin.closed:
            p.stdin.close()
        p.wait()
        p.stdout.close()

    def start(self, name, **kw):
        out = []
        th = threading.Thread(target=lambda: out.append(self.run_step(name, heavy_lock=self.lock, stage=4, **kw)))
        th.start()
        self.addCleanup(th.join)
        return th, out

    def test_th1_a_command_waits_for_the_other_engine(self):
        p = self.hold()
        th, out = self.start("green")
        time.sleep(1.5)
        self.assertTrue(th.is_alive(), "it must not start while the other engine holds the lock")
        self.assertFalse(os.path.exists(os.path.join(self.attempt_dir("green"), "run.log")))
        self.end(p)
        th.join(60)
        self.assertEqual(out[0].outcome["status"], "done")
        self.assertGreater(out[0].run["queue_wait_s"], 0.8)

    def test_th1_two_commands_never_overlap(self):
        cfg = repoconfig.RepoConfig(json.loads(json.dumps(CONFIG)))
        res = []

        def one(n):
            paths = dict(self.paths("order", n), srt_tmpdir=self.srt_tmp + str(n))
            inp = runner._run_input(cfg.raw, "order", n, ISSUE, runner._with_dirs(paths, self.ctx), COMMANDS["order"]["cmd"], 60)
            res.append(runner.run_named(inp, self.attempt_dir("order", n), self.base_env, SRT, 60, heavy_lock=self.lock))
        ths = [threading.Thread(target=one, args=(n,)) for n in (1, 2, 3)]
        for t in ths:
            t.start()
        for t in ths:
            t.join()
        self.assertEqual([r.exit_code for r in res], [0, 0, 0])
        with open(os.path.join(self.cache, "npm", "order")) as f:
            self.assertEqual(f.read().split(), ["start", "end"] * 3)

    def test_th2_the_wait_is_not_in_the_time_limit(self):
        p = self.hold()
        th, out = self.start("slow-limit-quick", config=_ShortLimits(json.loads(json.dumps(CONFIG))))    # limit: 2 s
        time.sleep(3.5)
        self.end(p)
        th.join(60)
        self.assertEqual((out[0].outcome["status"], out[0].run["timed_out"]), ("done", False))
        self.assertGreater(out[0].run["queue_wait_s"], 2)
        self.assertLess(out[0].duration_s, out[0].run["queue_wait_s"], "the duration is the command's own")

    def test_th3_a_dead_holder_frees_the_lock(self):
        p = self.hold()
        th, out = self.start("green")
        time.sleep(0.5)
        self.end(p, kill=True)
        th.join(60)
        self.assertEqual(out[0].outcome["status"], "done")

    def test_th4_a_plugin_check_does_not_wait(self):
        p = self.hold()
        th, out = self.start("ac-format")
        th.join(60)
        self.assertFalse(th.is_alive())
        self.assertIsNotNone(out[0].run)
        self.assertNotIn("queue_wait_s", out[0].run)
        self.assertIsNone(p.poll(), "the other engine still holds the lock")

    def test_the_i8_extras_wait_too_and_every_wait_is_summed(self):
        seen = []
        real = runner.run_named

        def spy(*a, heavy_lock=None, **kw):
            seen.append((kw.get("label", "main"), heavy_lock))
            return real(*a, heavy_lock=heavy_lock, **kw)
        with mock.patch.object(runner, "run_named", spy):
            r = self.run_step("only-here", heavy_lock=self.lock, stage=4)
        self.assertEqual([n for n, _ in seen], ["main", "rerun", "base-setup", "base"])
        self.assertEqual(len({id(q) for _, q in seen}), 1)
        self.assertIsInstance(seen[0][1], runner.HeavyQueue)
        self.assertEqual(r.run["queue_wait_s"], round(seen[0][1].waited, 3))

    def test_without_a_lock_nothing_changes(self):
        r = self.run_step("green")
        self.assertNotIn("queue_wait_s", r.run)
        self.assertFalse(os.path.exists(self.lock))

    def test_a_lock_that_is_no_plain_file_is_refused(self):
        os.symlink(self.root + "/elsewhere.lock", self.lock)
        with self.assertRaises(runner.RunnerError):
            self.run_step("green", heavy_lock=self.lock, stage=4)
        self.assertFalse(os.path.exists(self.root + "/elsewhere.lock"))

    def test_the_toolchain_commands_wait(self):
        raw = json.loads(json.dumps(CONFIG))
        raw["toolchain_prepare"] = [{"name": "warm", "cmd": "true"}]
        p = self.hold()
        out = []
        th = threading.Thread(target=lambda: out.append(runner.toolchain_prepare(
            self.ctx, repoconfig.RepoConfig(raw), self.base_env, SRT, paths=self.paths("prep"), attempt_dir=self.attempt_dir("prep"),
            step_id="prep", attempt=1, issue=ISSUE, heavy_lock=self.lock)))
        th.start()
        time.sleep(1.0)
        self.assertTrue(th.is_alive())
        self.end(p)
        th.join(60)
        self.assertEqual([e["ok"] for e in out[0]], [True])


class Judgment(unittest.TestCase):
    def test_outcome_precedence(self):
        clean, dirty = {"clean": True, "dirty_files": []}, {"clean": False, "dirty_files": ["x"]}
        red = {"exit_code": 1, "timed_out": False}
        run = dict(name="t", exit_code=1, timed_out=False, log_file="run.log", rerun=red, base_run=red)
        self.assertEqual(runner.outcome_of(run, dirty)["stop"], "base-red")
        run["base_run"] = {"exit_code": 0, "timed_out": False}
        self.assertEqual(runner.outcome_of(run, dirty)["detail"], "run-dirty-tree")
        self.assertEqual(runner.outcome_of(run, clean, head_moved=True)["detail"], "run-dirty-tree")
        self.assertEqual(runner.outcome_of(dict(run, timed_out=True, exit_code=None), clean)["detail"], "run-timeout")
        self.assertEqual(runner.outcome_of(run, clean)["detail"], "run-nonzero")
        green = dict(run, exit_code=0, rerun=None, base_run=None)
        self.assertEqual(runner.outcome_of(green, clean)["status"], "done")
        self.assertTrue(runner.is_red({"exit_code": 0, "timed_out": True}))

    def test_outcome_args_build_a_statemachine_outcome(self):
        from gxengine import statemachine
        for o in ({"status": "done", "code": None, "detail": None, "stop": None},
                  {"status": "failed", "code": "check-failed", "detail": "run-timeout", "stop": None},
                  {"status": "needs_human", "code": None, "detail": None, "stop": "base-red"}):
            args, kw = runner.to_outcome_args(o)
            statemachine.Outcome(*args, **kw)


if __name__ == "__main__":
    unittest.main()
