"""Stage 3 plugin runs under the REAL srt in a temporary git repository (scope §5.2 TB, TR; review-q0 D1, D10; K3).

repro-red and safety-net-proof on the overlay tree (recorded base + the HEAD blobs of the files the
authoring step owns); verification-frozen and no-production-change from git facts.
The repository `test` command is a small shell loop: it runs every test/*_test.sh.
No LLM, no network. A missing srt is a FAILURE (tests/test_runner.Base).
"""

import copy
import os
from unittest import mock

from gxengine import codes, gitops, procedure, repoconfig, results, runner, schema
from tests import test_runner as TR
from tests.helpers.defects import fixes_defect

CF = codes.CheckFailedReason
ISSUE = TR.ISSUE

RUN_TESTS = "for f in test/*_test.sh; do [ -e \"$f\" ] || continue; sh \"$f\" || exit 1; done"
CONFIG = {
    "format": 1,
    "commands": {
        "setup": {"cmd": "test ! -e test/breaks_setup_test.sh"},
        "test": {"cmd": RUN_TESTS},
        "ac-format": {"plugin": "ac-format"},
        "repro-red": {"plugin": "repro-red"},
        "safety-net-proof": {"plugin": "safety-net-proof"},
        "verification-frozen": {"plugin": "verification-frozen"},
        "no-production-change": {"plugin": "no-production-change"},
    },
    "path_rules": [
        {"kind": "test-code", "globs": ["test/**/*_test.sh"]},
        {"kind": "safety-net", "globs": ["test/**/*_net_test.sh"]},
        {"kind": "verification", "category": "test", "globs": ["test/**", "tests/**"]},
        {"kind": "verification", "category": "golden", "globs": ["goldens/**"]},
        {"kind": "verification", "category": "comparison-config", "globs": ["compare.json"]},
    ],
}
STEPS = [
    {"id": "reproduce", "role": "developer", "outputs": ["test/**/*_test.sh"], "on_fail": {"back_to": "reproduce", "max": 2}},
    {"id": "repro-red", "run": "repro-red", "on_fail": {"back_to": "reproduce", "max": 2}},
    {"id": "safety-net", "role": "developer", "outputs": ["test/**/*_net_test.sh"]},
    {"id": "safety-net-proof", "run": "safety-net-proof", "on_fail": {"back_to": "safety-net", "max": 2}},
    {"id": "fix", "role": "developer", "outputs": [], "on_fail": {"back_to": "fix", "max": 2}},
    {"id": "verification-frozen", "run": "verification-frozen"},
    {"id": "no-production-change", "run": "no-production-change"},
    {"id": "ac-format", "run": "ac-format"},
]
# red while the bug is there (src/a.txt says "bug" on the base), green after the fix
REGRESSION = "grep -q fixed src/a.txt\n"


class ShortTest(repoconfig.RepoConfig):
    """The schema's smallest limit is one minute; the timeout test needs seconds."""

    def command(self, name):
        c = super().command(name)
        if name == "test":
            c["timeout_s"] = 3
        return c


class Base(TR.Base):
    BASE_FILES = {"src/a.txt": "bug\n"}

    def setUp(self):
        super().setUp()
        # a new recorded base that holds BASE_FILES: the Issue branch starts over from it
        for rel, text in self.BASE_FILES.items():
            self.repo.write(rel, text)
        self.base = self.repo.commit("base files")
        self.repo.git("reset", "-q", "--hard", self.base, cwd=self.wt)
        self.ctx.base_sha = self.base
        self.procedure = procedure.Procedure({"format": 1, "issue": ISSUE, "revision": 1,
                                              "origin": {"template": "bug", "version": "1", "start": "1"},
                                              "steps": copy.deepcopy(STEPS)})

    def put(self, **files):
        """Write and commit files on the Issue branch (None = delete); `__` is `/`, see names below."""
        return self.put_files(files)

    def put_files(self, files, message="work"):
        for rel, text in files.items():
            if text is None:
                os.unlink(os.path.join(self.wt, rel))
            else:
                self.repo.write(rel, text, cwd=self.wt)
        return self.repo.commit(message, cwd=self.wt)

    def files_of(self, owned, outside=(), step="reproduce"):
        return {"step": step, "attempts": [1], "net": {p: [None, "a" * 40] for p in list(owned) + list(outside)},
                "owned": list(owned), "outside": list(outside)}

    def config(self, cls=repoconfig.RepoConfig, **over):
        raw = copy.deepcopy(CONFIG)
        for name, cmd in over.items():
            if cmd is None:
                del raw["commands"][name]
            else:
                raw["commands"][name] = cmd
        return cls(raw)

    def run_s3(self, name, owned=None, outside=(), attempt=1, config=None, stage=3, author=None, **kw):
        if owned is not None:
            author = author or ("reproduce" if name == "repro-red" else "safety-net")
            kw["step_files"] = self.files_of(owned, outside, author)
        r = self.run_step(name, attempt=attempt, config=config or self.config(), stage=stage, **kw)
        if r.run is not None:
            sch = schema.load_schema("facts")
            self.assertEqual(schema.errors(r.run, dict(sch["properties"]["run"]["anyOf"][1], **{"$defs": sch["$defs"]})), [])
        return r

    def assertDone(self, r):
        self.assertEqual(r.outcome, {"status": "done", "code": None, "detail": None, "stop": None},
                         (r.run, r.notes))
        self.assertEqual(r.run["exit_code"], 0)

    def assertFailed(self, r, detail):
        self.assertEqual((r.outcome["status"], r.outcome["code"], r.outcome["detail"]),
                         ("failed", "check-failed", detail.value), (r.run, r.notes))
        self.assertEqual(r.run["exit_code"], 1)

    def assertNothingLeft(self):
        self.assertNotIn("overlay-tree", self.worktrees())
        self.assertNotIn("base-tree", self.worktrees())
        self.assertTrue(gitops.tree_state(self.ctx)["clean"])


class HeavyEvidence(Base):
    """Stage 4 (H22): an evidence run's setup, overlay and base commands take the machine-wide lock."""

    def test_every_command_of_an_evidence_run_waits(self):
        self.put_files({"test/a_test.sh": REGRESSION})
        lock, seen, real = os.path.join(self.eng, "heavy-run.lock"), [], runner.run_named

        def spy(*a, heavy_lock=None, **kw):
            seen.append((kw.get("label"), type(heavy_lock)))
            return real(*a, heavy_lock=heavy_lock, **kw)
        with mock.patch.object(runner, "run_named", spy):
            r = self.run_s3("repro-red", ["test/a_test.sh"], stage=4, heavy_lock=lock)
        self.assertDone(r)
        self.assertEqual([n for n, _ in seen], ["overlay-setup", "overlay", "overlay-rerun", "base-setup", "base"])
        self.assertEqual({t for _, t in seen}, {runner.HeavyQueue})
        self.assertIsInstance(r.run["queue_wait_s"], float)


class ReproRed(Base):
    def test_tb1_red_twice_on_the_overlay_and_green_on_the_base(self):
        head = self.put_files({"test/a_test.sh": REGRESSION})
        r = self.run_s3("repro-red", ["test/a_test.sh"])
        self.assertDone(r)
        run = r.run
        self.assertEqual(run["head"], {"exit_code": 1, "timed_out": False, "log_file": "run-head.log"})
        self.assertEqual(run["head_rerun"], {"exit_code": 1, "timed_out": False, "log_file": "run-head-rerun.log"})
        self.assertEqual(run["base_run"], {"exit_code": 0, "timed_out": False, "log_file": "run-base.log"})
        ev = run["evidence"]
        self.assertEqual(ev["scope"], {"ok": True, "step": "reproduce", "attempts": [1], "outside": []})
        self.assertEqual((ev["overlay"]["base_sha"], ev["overlay"]["head_sha"], ev["overlay"]["existed"]),
                         (self.base, head, []))
        self.assertEqual([(f["path"], f["base_blob"]) for f in ev["overlay"]["files"]], [("test/a_test.sh", None)])
        self.assertEqual(ev["end_tree"], {"clean": True, "dirty_files": []})
        self.assertIn("[gld engine] repro-red: ok", self.log("repro-red"))
        self.assertNothingLeft()

    def test_d1_the_fix_commit_does_not_change_the_verdict(self):
        """§4.4-3 / I3 / rerun: the step runs again after the fix, on the overlay tree — same verdict."""
        self.put_files({"test/a_test.sh": REGRESSION})
        self.assertDone(self.run_s3("repro-red", ["test/a_test.sh"]))
        self.put_files({"src/a.txt": "fixed\n", "test/other_test.sh": "true\n"}, "fix")
        r = self.run_s3("repro-red", ["test/a_test.sh"], attempt=2)
        self.assertDone(r)
        self.assertEqual([f["path"] for f in r.run["evidence"]["overlay"]["files"]], ["test/a_test.sh"])

    def test_tb2_a_green_test_is_no_reproduction(self):
        self.put_files({"test/a_test.sh": "true\n"})
        r = self.run_s3("repro-red", ["test/a_test.sh"])
        self.assertFailed(r, CF.REPRO_NOT_RED)
        self.assertEqual(r.run["head"]["exit_code"], 0)
        self.assertIsNone(r.run["head_rerun"])
        self.assertIsNone(r.run["base_run"])

    def test_tb3_a_change_outside_the_globs_is_repro_scope_and_nothing_runs(self):
        self.put_files({"test/a_test.sh": REGRESSION, "src/a.txt": "other\n"})
        r = self.run_s3("repro-red", ["test/a_test.sh"], outside=["src/a.txt"])
        self.assertFailed(r, CF.REPRO_SCOPE)
        self.assertIsNone(r.run["head"])
        self.assertIsNone(r.run["evidence"]["end_tree"])
        self.assertEqual(r.run["evidence"]["scope"]["outside"], ["src/a.txt"])
        self.assertIn("src/a.txt", self.log("repro-red"))
        self.assertFalse(os.path.exists(os.path.join(self.attempt_dir("repro-red"), "run-head.log")))

    def test_d10_one_red_run_is_not_enough(self):
        self.put_files({"test/a_test.sh": "[ -f \"$TMPDIR/seen\" ] && exit 0; touch \"$TMPDIR/seen\"; exit 1\n"})
        r = self.run_s3("repro-red", ["test/a_test.sh"])
        self.assertFailed(r, CF.REPRO_NOT_RED)
        self.assertEqual((r.run["head"]["exit_code"], r.run["head_rerun"]["exit_code"]), (1, 0))

    def test_tb6_a_timeout_is_never_red(self):
        self.put_files({"test/a_test.sh": "sleep 31\n"})
        r = self.run_s3("repro-red", ["test/a_test.sh"], config=self.config(ShortTest))
        self.assertFailed(r, CF.RUN_TIMEOUT)
        self.assertTrue(r.run["head"]["timed_out"])
        self.assertIsNone(r.run["head_rerun"])
        self.assertEqual(r.run["base_run"]["exit_code"], 0)

    def test_tb6_base_red_stops(self):
        self.put_files({"test/a_test.sh": REGRESSION})
        r = self.run_s3("repro-red", ["test/a_test.sh"], config=self.config(test={"cmd": "test -f absent"}))
        self.assertEqual(r.outcome, {"status": "needs_human", "code": None, "detail": None, "stop": "base-red"})
        self.assertEqual(r.run["base_run"]["exit_code"], 1)
        self.assertTrue(any("base red" in n for n in r.notes))

    def test_a_red_run_that_leaves_files_is_run_dirty_tree(self):
        self.put_files({"test/a_test.sh": "echo x > snapshot.txt; exit 1\n"})
        r = self.run_s3("repro-red", ["test/a_test.sh"])
        self.assertFailed(r, CF.RUN_DIRTY_TREE)
        self.assertEqual(r.run["evidence"]["end_tree"], {"clean": False, "dirty_files": ["snapshot.txt"]})
        self.assertIsNone(r.run["base_run"])
        self.assertNothingLeft()

    def test_a_run_that_rewrites_an_overlay_file_is_dirty_too(self):
        self.put_files({"test/a_test.sh": "echo '# x' >> test/a_test.sh; git add -A; exit 1\n"})
        r = self.run_s3("repro-red", ["test/a_test.sh"])
        self.assertFailed(r, CF.RUN_DIRTY_TREE)
        self.assertEqual(r.run["evidence"]["end_tree"]["dirty_files"], ["test/a_test.sh"])

    def test_no_file_of_its_own_is_no_reproduction(self):
        r = self.run_s3("repro-red", [])
        self.assertFailed(r, CF.REPRO_NOT_RED)
        self.assertIsNone(r.run["head"])

    def test_a_red_setup_is_not_a_red_test(self):
        self.put_files({"test/breaks_setup_test.sh": "exit 1\n"})
        r = self.run_s3("repro-red", ["test/breaks_setup_test.sh"])
        self.assertFailed(r, CF.REPRO_NOT_RED)
        self.assertEqual(r.run["head"]["log_file"], "run-head-setup.log")
        self.assertEqual(r.run["base_run"]["exit_code"], 0)

    def test_paths_are_literal(self):
        """`[i]_test.sh` is a file name, not a pattern: i_test.sh (not owned) stays out of the overlay."""
        self.put_files({"test/[i]_test.sh": REGRESSION, "test/i_test.sh": "echo x > leak.txt; exit 1\n"})
        self.assertDone(self.run_s3("repro-red", ["test/[i]_test.sh"]))

    def test_a_link_is_never_overlaid(self):
        os.makedirs(os.path.join(self.wt, "test"))
        os.symlink("/etc/hosts", os.path.join(self.wt, "test", "a_test.sh"))
        self.repo.commit("link", cwd=self.wt)
        self.assertFailed(self.run_s3("repro-red", ["test/a_test.sh"]), CF.REPRO_SCOPE)

    def test_the_failure_log_ends_with_the_engine_lines(self):
        self.put_files({"test/a_test.sh": "echo the-runner-said; true\n"})
        self.run_s3("repro-red", ["test/a_test.sh"])
        text = self.log("repro-red")
        self.assertLess(text.index("the-runner-said"), text.index("[gld engine] repro-red: repro-not-red"))

    def test_a_worktree_that_cannot_be_made_is_infra(self):
        self.put_files({"test/a_test.sh": REGRESSION})
        with mock.patch.object(runner.gitops, "detached_worktree", side_effect=gitops.GitError("no space")):
            r = self.run_s3("repro-red", ["test/a_test.sh"])
        self.assertEqual((r.outcome["code"], r.outcome["detail"]), ("infra", "fact-collection"))

    def test_the_author_is_found_in_the_procedure(self):
        self.assertEqual(runner.evidence_author(self.procedure, "repro-red"), "reproduce")
        self.assertEqual(runner.evidence_author(self.procedure, "safety-net-proof"), "safety-net")
        with self.assertRaises(runner.RunnerError):
            runner.evidence_author(self.procedure, "reproduce")

    def test_refusals(self):
        self.put_files({"test/a_test.sh": REGRESSION})
        for kw in ({"stage": 2}, {"config": self.config(test=None)}, {"path_globs": []}, {"path_globs": {"safety-net": ["x"]}}):
            with self.subTest(kw=kw), self.assertRaises(runner.RunnerError):
                self.run_s3("repro-red", ["test/a_test.sh"], **kw)
        with self.assertRaises(runner.RunnerError):
            self.run_s3("repro-red")                                # no step_files
        raw = copy.deepcopy(CONFIG)
        raw["path_rules"] = raw["path_rules"][1:]
        with self.assertRaises(runner.RunnerError):
            self.run_s3("repro-red", ["test/a_test.sh"], config=repoconfig.RepoConfig(raw))


# base tree only (the overlay has the regression test and is always red): red once, then green
ONCE = "[ -f \"$TMPDIR/seen\" ] && exit 0; touch \"$TMPDIR/seen\"; "


class BaseTwice(Base):
    """K8-2: a red (or timed out) base run of an evidence run is judged twice on the same base tree."""
    ON_HEAD = "[ -e test/a_test.sh ] && exit 1; [ -e test/a_net_test.sh ] && exit 1; "

    def repro(self, cmd, cls=repoconfig.RepoConfig, **over):
        self.put_files({"test/a_test.sh": REGRESSION})
        return self.run_s3("repro-red", ["test/a_test.sh"], config=self.config(cls, test={"cmd": self.ON_HEAD + cmd}, **over))

    def test_a_base_that_is_green_the_second_time_is_green(self):
        r = self.repro(ONCE + "exit 1")
        self.assertDone(r)
        self.assertEqual(r.run["base_run"], {"exit_code": 1, "timed_out": False, "log_file": "run-base.log"})
        self.assertEqual(r.run["base_rerun"], {"exit_code": 0, "timed_out": False, "log_file": "run-base-rerun.log"})
        self.assertTrue(any("base flaky" in n for n in r.notes))
        self.assertIn("`test` exit 1, again exit 0", self.log("repro-red"))
        self.assertNothingLeft()

    def test_a_base_that_is_red_twice_is_base_red(self):
        r = self.repro("exit 7")
        self.assertEqual((r.outcome["status"], r.outcome["stop"]), ("needs_human", "base-red"))
        self.assertEqual((r.run["base_run"]["exit_code"], r.run["base_rerun"]["exit_code"]), (7, 7))
        self.assertTrue(any("red on the recorded base" in n and "twice" in n for n in r.notes))
        self.assertNothingLeft()

    def test_a_green_base_runs_once(self):
        r = self.repro("exit 0")
        self.assertDone(r)
        self.assertIsNone(r.run["base_rerun"])
        self.assertFalse(os.path.exists(os.path.join(self.attempt_dir("repro-red"), "run-base-rerun.log")))

    def test_a_base_timeout_gets_the_second_run_too(self):
        r = self.repro(ONCE + "sleep 31", ShortTest)
        self.assertDone(r)
        self.assertTrue(r.run["base_run"]["timed_out"])
        self.assertEqual(r.run["base_rerun"]["exit_code"], 0)

    def test_two_base_timeouts_are_base_red(self):
        r = self.repro("sleep 31", ShortTest)
        self.assertEqual(r.outcome["stop"], "base-red")
        self.assertTrue(r.run["base_run"]["timed_out"] and r.run["base_rerun"]["timed_out"])

    def test_red_then_timeout_is_base_red(self):
        r = self.repro("[ -f \"$TMPDIR/seen\" ] && sleep 31; touch \"$TMPDIR/seen\"; exit 1", ShortTest)
        self.assertEqual(r.outcome["stop"], "base-red")
        self.assertEqual((r.run["base_run"]["timed_out"], r.run["base_rerun"]["timed_out"]), (False, True))

    def test_a_dirty_base_tree_is_not_run_again(self):
        """The second run would not judge the recorded base any more: the first red stands."""
        r = self.repro("[ -e left.txt ] && exit 0; echo x > left.txt; exit 1")
        self.assertEqual(r.outcome["stop"], "base-red")
        self.assertIsNone(r.run["base_rerun"])
        self.assertTrue(any("left the base tree dirty" in n and "left.txt" in n for n in r.notes))
        self.assertNothingLeft()

    def test_a_setup_that_is_red_once_is_part_of_the_first_run(self):
        setup = {"cmd": "[ -e test/a_test.sh ] && exit 0; " + ONCE + "exit 1"}
        r = self.repro("exit 0", setup=setup)
        self.assertDone(r)
        self.assertEqual(r.run["base_run"]["log_file"], "run-base-setup.log")
        self.assertEqual(r.run["base_rerun"], {"exit_code": 0, "timed_out": False, "log_file": "run-base-rerun.log"})
        self.assertTrue(os.path.exists(os.path.join(self.attempt_dir("repro-red"), "run-base-setup-rerun.log")))

    def test_safety_net_proof_judges_the_base_twice_too(self):
        net = "test/a_net_test.sh"
        self.put_files({net: "exit 1\n"})
        r = self.run_s3("safety-net-proof", [net], config=self.config(test={"cmd": self.ON_HEAD + ONCE + "exit 1"}))
        self.assertFailed(r, CF.NET_RED_ON_BASE)
        self.assertEqual((r.run["base_run"]["exit_code"], r.run["base_rerun"]["exit_code"]), (1, 0))
        r = self.run_s3("safety-net-proof", [net], config=self.config(test={"cmd": self.ON_HEAD + "exit 1"}), attempt=2)
        self.assertEqual(r.outcome["stop"], "base-red")

    def test_the_mark(self):
        red, green = {"exit_code": 1, "timed_out": False}, {"exit_code": 0, "timed_out": False}
        for first, second, want in ((red, None, True), (red, red, True), (red, green, False), (green, None, False),
                                    (None, None, False), (red, {"exit_code": 0, "timed_out": True}, True)):
            with self.subTest(first=first, second=second):
                run = {"base_run": first, "base_rerun": second}
                self.assertIs(runner.is_base_red(run), want)
                facts = {"run": dict(run, exit_code=1, timed_out=False), "end_tree": {"clean": True, "dirty_files": []},
                         "start_head": "a", "end_head": "a", "control_files": {"ok": True, "changed": []},
                         "ownership": {"ok": True, "violations": []}}
                self.assertEqual(results.judge_run("repro-red", facts).stop == "base-red", want)


class SafetyNetProof(Base):
    NET = "test/a_net_test.sh"

    def test_tr5_green_on_the_base(self):
        """The net describes the behaviour of the code BEFORE the change: it is proved on the base tree."""
        self.put_files({self.NET: "grep -q bug src/a.txt\n"})
        r = self.run_s3("safety-net-proof", [self.NET])
        self.assertDone(r)
        self.assertEqual(r.run["head"]["exit_code"], 0)
        self.assertEqual((r.run["head_rerun"], r.run["base_run"]), (None, None))
        self.assertEqual(r.run["evidence"]["kind"], "safety-net-proof")
        self.assertNothingLeft()
        # the transform changes production code: proved again, the verdict stays (D1)
        self.put_files({"src/a.txt": "changed\n"}, "transform")
        self.assertDone(self.run_s3("safety-net-proof", [self.NET], attempt=2))

    def test_tr6_red_on_base(self):
        self.put_files({self.NET: "grep -q fixed src/a.txt\n"})
        r = self.run_s3("safety-net-proof", [self.NET])
        self.assertFailed(r, CF.NET_RED_ON_BASE)
        self.assertEqual(r.run["base_run"]["exit_code"], 0)          # K3: the base alone is green
        # VW4 O1: red twice on the same overlay tree before the base is asked
        self.assertEqual(r.run["head_rerun"], {"exit_code": 1, "timed_out": False, "log_file": "run-head-rerun.log"})
        self.assertIs(r.run["head_flaky"], False)

    def test_k3_a_red_base_is_not_the_nets_fault(self):
        self.put_files({self.NET: "true\n"})
        r = self.run_s3("safety-net-proof", [self.NET], config=self.config(test={"cmd": "test -f absent"}))
        self.assertEqual(r.outcome["stop"], codes.StopReason.BASE_RED.value)

    def test_tr7_a_snapshot_written_by_the_run(self):
        self.put_files({self.NET: "echo snap > test/snapshot.txt\n"})
        r = self.run_s3("safety-net-proof", [self.NET])
        self.assertFailed(r, CF.RUN_DIRTY_TREE)
        self.assertEqual(r.run["evidence"]["end_tree"]["dirty_files"], ["test/snapshot.txt"])
        self.assertIn("test/snapshot.txt", self.log("safety-net-proof"))

    def test_tr8_an_existing_test_file_changed(self):
        self.put_files({self.NET: "true\n", "tests/test_a.py": "def test_a():\n    pass\n"})
        r = self.run_s3("safety-net-proof", [self.NET], outside=["tests/test_a.py"])
        self.assertFailed(r, CF.NET_SCOPE)
        self.assertIsNone(r.run["head"])

    def test_no_net_is_not_a_proof(self):
        r = self.run_s3("safety-net-proof", [])
        self.assertFailed(r, CF.NET_SCOPE)
        self.assertIsNone(r.run["head"])

    def test_timeout(self):
        self.put_files({self.NET: "sleep 31\n"})
        r = self.run_s3("safety-net-proof", [self.NET], config=self.config(ShortTest))
        self.assertFailed(r, CF.RUN_TIMEOUT)

    def test_a_setup_broken_by_the_net(self):
        self.put_files({"test/breaks_setup_test.sh": "true\n"})
        raw = copy.deepcopy(CONFIG)
        raw["path_rules"][1]["globs"] = ["test/*_test.sh"]
        r = self.run_s3("safety-net-proof", ["test/breaks_setup_test.sh"], config=repoconfig.RepoConfig(raw))
        self.assertFailed(r, CF.NET_RED_ON_BASE)
        self.assertEqual((r.run["head"]["log_file"], r.run["head_rerun"]["log_file"]),
                         ("run-head-setup.log", "run-head-setup-rerun.log"))


class SafetyNetFlaky(Base):
    """VW4 O1 (K8-2's rule, as E1's control): a net run that is not green is run once more on the same
    overlay tree; green the second time passes with the mark, anything else takes the old path."""
    NET = "test/a_net_test.sh"
    # the net is green; another test of the repository fails once (a performance assertion, #1938)
    OTHER = "test/perf_test.sh"

    def flaky_repo(self, other, cls=repoconfig.RepoConfig):
        """`other` is a test on the recorded base (green there alone); the net is new and green."""
        # it only fails beside the net (the base alone is green, so a red overlay is the net's: K3)
        self.repo.write(self.OTHER, "[ -e test/a_net_test.sh ] || exit 0\n" + other)
        self.base = self.repo.commit("perf test")
        self.repo.git("reset", "-q", "--hard", self.base, cwd=self.wt)
        self.ctx.base_sha = self.base
        self.put_files({self.NET: "grep -q bug src/a.txt\n"})
        return self.run_s3("safety-net-proof", [self.NET], config=self.config(cls))

    @fixes_defect("O1", "silent @ runner._overlay_runs")
    def test_red_then_green_passes_with_the_mark(self):
        r = self.flaky_repo(ONCE + "echo perf-too-slow; exit 1\n")
        self.assertDone(r)
        run = r.run
        self.assertEqual(run["head"], {"exit_code": 1, "timed_out": False, "log_file": "run-head.log"})
        self.assertEqual(run["head_rerun"], {"exit_code": 0, "timed_out": False, "log_file": "run-head-rerun.log"})
        self.assertIs(run["head_flaky"], True)
        self.assertIs(run["timed_out"], False)
        self.assertEqual((run["base_run"], run["base_rerun"]), (None, None))   # green: the base is not asked
        self.assertTrue(any("safety net flaky" in n and "red (exit 1)" in n and "run-head.log" in n for n in r.notes))
        text = self.log("safety-net-proof")
        self.assertIn("[gld engine] safety-net-proof: ok", text)
        self.assertIn("`test` exit 1, `test again` exit 0", text)
        self.assertIn("flaky: not green, then green on the same overlay tree", text)
        self.assertIn("first run's log is run-head.log", text)
        self.assertLess(text.index("perf-too-slow"), text.index("[gld engine]"))    # the first run's tail
        self.assertNothingLeft()

    def test_a_timeout_then_green_passes_too(self):
        """E1 / K8-2: a timeout gets the second run like a red."""
        r = self.flaky_repo(ONCE + "sleep 31\n", ShortTest)
        self.assertDone(r)
        self.assertTrue(r.run["head"]["timed_out"])
        self.assertEqual(r.run["head_rerun"]["exit_code"], 0)
        self.assertIs(r.run["head_flaky"], True)
        self.assertIs(r.run["timed_out"], False)
        self.assertTrue(any("safety net flaky" in n and "timed out" in n for n in r.notes))

    def test_red_twice_is_still_red(self):
        r = self.flaky_repo("exit 1\n")
        self.assertFailed(r, CF.NET_RED_ON_BASE)
        self.assertEqual((r.run["head"]["exit_code"], r.run["head_rerun"]["exit_code"]), (1, 1))
        self.assertIs(r.run["head_flaky"], False)
        self.assertFalse(any("safety net flaky" in n for n in r.notes))

    def test_red_then_timeout_is_still_not_a_pass(self):
        r = self.flaky_repo("[ -f \"$TMPDIR/seen\" ] && sleep 31; touch \"$TMPDIR/seen\"; exit 1\n", ShortTest)
        self.assertFailed(r, CF.RUN_TIMEOUT)
        self.assertEqual((r.run["head"]["timed_out"], r.run["head_rerun"]["timed_out"]), (False, True))
        self.assertIs(r.run["head_flaky"], False)
        self.assertIs(r.run["timed_out"], True)

    def test_two_timeouts_are_a_timeout(self):
        r = self.flaky_repo("sleep 31\n", ShortTest)
        self.assertFailed(r, CF.RUN_TIMEOUT)
        self.assertTrue(r.run["head"]["timed_out"] and r.run["head_rerun"]["timed_out"])
        self.assertIs(r.run["head_flaky"], False)

    def test_a_red_run_that_leaves_the_tree_dirty_is_not_run_again(self):
        """The second run would not judge base + net any more: the first red stands (as K8-2's base)."""
        r = self.flaky_repo("[ -e left.txt ] && exit 0; echo x > left.txt; exit 1\n")
        self.assertFailed(r, CF.RUN_DIRTY_TREE)
        self.assertIsNone(r.run["head_rerun"])
        self.assertIs(r.run["head_flaky"], False)
        self.assertEqual(r.run["evidence"]["end_tree"]["dirty_files"], ["left.txt"])
        self.assertTrue(any("left the overlay tree dirty" in n for n in r.notes))
        self.assertFalse(os.path.exists(os.path.join(self.attempt_dir("safety-net-proof"), "run-head-rerun.log")))
        self.assertNothingLeft()

    def test_green_then_dirty_is_dirty(self):
        """A second run that writes a file does not pass, even green."""
        r = self.flaky_repo("[ -f \"$TMPDIR/seen\" ] && { echo x > left.txt; exit 0; }; touch \"$TMPDIR/seen\"; exit 1\n")
        self.assertFailed(r, CF.RUN_DIRTY_TREE)
        self.assertEqual(r.run["head_rerun"]["exit_code"], 0)
        self.assertEqual(r.run["evidence"]["end_tree"]["dirty_files"], ["left.txt"])

    def test_a_setup_red_once_is_run_again_with_the_tests(self):
        setup = {"cmd": "[ -e test/a_net_test.sh ] || exit 0; " + ONCE + "exit 1"}
        self.put_files({self.NET: "grep -q bug src/a.txt\n"})
        r = self.run_s3("safety-net-proof", [self.NET], config=self.config(setup=setup))
        self.assertDone(r)
        self.assertEqual(r.run["head"]["log_file"], "run-head-setup.log")
        self.assertEqual(r.run["head_rerun"], {"exit_code": 0, "timed_out": False, "log_file": "run-head-rerun.log"})
        self.assertIs(r.run["head_flaky"], True)
        self.assertTrue(os.path.exists(os.path.join(self.attempt_dir("safety-net-proof"), "run-head-setup-rerun.log")))

    def test_repro_red_is_unchanged(self):
        """D10: repro-red never runs a timeout or a red setup again, and never has the mark."""
        self.put_files({"test/a_test.sh": "sleep 31\n"})
        r = self.run_s3("repro-red", ["test/a_test.sh"], config=self.config(ShortTest))
        self.assertIsNone(r.run["head_rerun"])
        self.assertIs(r.run["head_flaky"], False)

    def test_the_lock_takes_the_second_run_too(self):
        lock, seen, real = os.path.join(self.eng, "heavy-run.lock"), [], runner.run_named

        def spy(*a, heavy_lock=None, **kw):
            seen.append(kw.get("label"))
            return real(*a, heavy_lock=heavy_lock, **kw)
        self.repo.write(self.OTHER, ONCE + "exit 1\n")
        self.base = self.repo.commit("perf test")
        self.repo.git("reset", "-q", "--hard", self.base, cwd=self.wt)
        self.ctx.base_sha = self.base
        self.put_files({self.NET: "true\n"})
        with mock.patch.object(runner, "run_named", spy):
            r = self.run_s3("safety-net-proof", [self.NET], stage=4, heavy_lock=lock)
        self.assertDone(r)
        self.assertEqual(seen, ["overlay-setup", "overlay", "overlay-rerun"])


class SafetyNetExisting(Base):
    BASE_FILES = {"src/a.txt": "bug\n", "test/old_net_test.sh": "true\n"}

    def test_d1_a_net_file_that_existed_on_base(self):
        """D3: the name fits the rule, but only files base did not have count."""
        self.put_files({"test/old_net_test.sh": "true # weaker\n"})
        r = self.run_s3("safety-net-proof", ["test/old_net_test.sh"])
        self.assertFailed(r, CF.NET_SCOPE)
        self.assertEqual(r.run["evidence"]["overlay"]["existed"], ["test/old_net_test.sh"])
        self.assertIsNone(r.run["head"])

    def test_deleting_one_is_net_scope_too(self):
        self.put_files({"test/old_net_test.sh": None})
        r = self.run_s3("safety-net-proof", ["test/old_net_test.sh"])
        self.assertFailed(r, CF.NET_SCOPE)


class Frozen(Base):
    BASE_FILES = {"src/a.txt": "bug\n", "test/one_test.sh": "one\n", "test/two_test.sh": "two\n",
                  "test/same_test.sh": "one\n", "goldens/a.png": "img\n", "compare.json": "{}\n"}

    def frozen(self, attempt=1):
        return self.run_s3("verification-frozen", attempt=attempt)

    def violations(self, r):
        self.assertFailed(r, CF.VERIFICATION_CHANGED)
        self.assertFalse(r.run["paths_check"]["ok"])
        for v in r.run["paths_check"]["violations"]:
            self.assertIn(v["path"], self.log("verification-frozen"))
        return [(v["change"], v["path"], v["from"]) for v in r.run["paths_check"]["violations"]]

    def test_tr1_production_changes_and_new_tests_pass(self):
        self.put_files({"src/a.txt": "refactored\n", "test/new_test.sh": "new\n", "goldens/b.png": "b\n"})
        r = self.frozen()
        self.assertDone(r)
        self.assertEqual(r.run["paths_check"], {"ok": True, "violations": []})
        self.assertIn("verification-frozen: ok", self.log("verification-frozen"))

    def test_tr2_an_existing_test_changed(self):
        self.put_files({"test/one_test.sh": "weaker\n"})
        self.assertEqual(self.violations(self.frozen()), [("modified", "test/one_test.sh", None)])

    def test_tr3_tg4_golden_and_comparison_config(self):
        self.put_files({"goldens/a.png": "other\n", "compare.json": "{\"tolerance\": 1}\n"})
        self.assertEqual(self.violations(self.frozen()),
                         [("modified", "compare.json", None), ("modified", "goldens/a.png", None)])

    def test_tr4_an_exact_rename_passes(self):
        self.put_files({"test/two_test.sh": None, "test/sub/two_test.sh": "two\n"})
        self.assertDone(self.frozen())

    def test_tr4_a_rename_with_changes_fails(self):
        long = "".join(f"line {i}\n" for i in range(30))
        self.repo.write("test/two_test.sh", long)
        self.ctx.base_sha = self.repo.commit("longer")
        self.repo.git("reset", "-q", "--hard", self.ctx.base_sha, cwd=self.wt)
        self.put_files({"test/two_test.sh": None, "test/moved_test.sh": long + "one more\n"})
        self.assertEqual(self.violations(self.frozen()), [("renamed", "test/moved_test.sh", "test/two_test.sh")])

    def test_a_rename_out_of_the_rule_is_a_deletion(self):
        self.put_files({"test/two_test.sh": None, "src/two.sh": "two\n"})
        self.assertEqual([v[0] for v in self.violations(self.frozen())], ["renamed"])

    def test_a_copy_that_was_there_already_is_no_rename(self):
        """same_test.sh holds the same bytes on the base: it cannot stand in for the deleted one."""
        self.put_files({"test/one_test.sh": None})
        self.assertEqual(self.violations(self.frozen()), [("deleted", "test/one_test.sh", None)])

    def test_one_new_file_stands_in_for_one_old_file(self):
        self.put_files({"test/one_test.sh": None, "test/same_test.sh": None, "test/kept_test.sh": "one\n"})
        self.assertEqual(len(self.violations(self.frozen())), 1)

    def test_a_mode_or_type_change(self):
        os.chmod(os.path.join(self.wt, "test", "one_test.sh"), 0o755)
        os.unlink(os.path.join(self.wt, "test", "two_test.sh"))
        os.symlink("one_test.sh", os.path.join(self.wt, "test", "two_test.sh"))
        self.repo.commit("mode and type", cwd=self.wt)
        self.assertEqual(self.violations(self.frozen()),
                         [("modified", "test/one_test.sh", None), ("type-changed", "test/two_test.sh", None)])

    def test_put_back_passes(self):
        self.put_files({"test/one_test.sh": "weaker\n"})
        self.put_files({"test/one_test.sh": "one\n"})
        self.assertDone(self.frozen())

    def test_refusals(self):
        raw = copy.deepcopy(CONFIG)
        raw["path_rules"] = raw["path_rules"][:2]
        with self.assertRaises(runner.RunnerError):            # nothing to freeze is not a pass
            self.run_s3("verification-frozen", config=repoconfig.RepoConfig(raw))
        with self.assertRaises(runner.RunnerError):
            self.run_s3("verification-frozen", stage=2)

    def test_a_git_failure_is_infra(self):
        with mock.patch.object(runner.gitops, "changed_files", side_effect=gitops.GitError("boom")):
            r = self.frozen()
        self.assertEqual((r.outcome["code"], r.outcome["detail"]), ("infra", "fact-collection"))


class NoProductionChange(Base):
    BASE_FILES = {"src/a.txt": "bug\n", "test/old_net_test.sh": "true\n"}
    NET = "test/a_net_test.sh"

    def check(self):
        return self.run_s3("no-production-change")

    def violations(self, r):
        self.assertFailed(r, CF.PRODUCTION_CHANGED)
        return [(v["change"], v["path"]) for v in r.run["paths_check"]["violations"]]

    def test_only_new_net_files_and_specs(self):
        self.put_files({self.NET: "true\n", "docs/specs/42/analysis.md": "x\n"})
        self.assertDone(self.check())

    def test_tr9_production(self):
        self.put_files({self.NET: "true\n", "src/a.txt": "changed\n", "src/new.txt": "n\n"})
        self.assertEqual(self.violations(self.check()), [("modified", "src/a.txt"), ("added", "src/new.txt")])

    def test_an_existing_net_file_and_another_issues_specs(self):
        self.put_files({"test/old_net_test.sh": "weaker\n", "docs/specs/7/x.md": "x\n"})
        self.assertEqual(self.violations(self.check()), [("added", "docs/specs/7/x.md"), ("modified", "test/old_net_test.sh")])

    def test_a_link_is_not_a_net_file(self):
        os.symlink("old_net_test.sh", os.path.join(self.wt, self.NET))
        self.repo.commit("link", cwd=self.wt)
        self.assertEqual(self.violations(self.check()), [("added", self.NET)])

    def test_a_production_file_moved_into_the_specs_folder(self):
        self.put_files({"src/a.txt": None, "docs/specs/42/a.txt": "bug\n"})
        self.assertIn("docs/specs/42/a.txt", [p for _, p in self.violations(self.check())])

    def test_without_a_rule(self):
        raw = copy.deepcopy(CONFIG)
        raw["path_rules"] = raw["path_rules"][:1]
        with self.assertRaises(runner.RunnerError):
            self.run_s3("no-production-change", config=repoconfig.RepoConfig(raw))


class AcFormatArgs(Base):
    def line(self, stage, **kw):
        """The command line run_step builds (the script itself is session B1's)."""
        seen = []

        def fake(name, inp, attempt_dir, base_env, srt_bin, timeout_s, plugin_root, args=(), **k):
            seen.append(runner.plugin_command_line(name, plugin_root, inp.issue, args))
            return runner.RunResult(0, False, os.path.join(attempt_dir, "run.log"), 0.1)

        with mock.patch.object(runner, "run_plugin_command", side_effect=fake):
            self.run_s3("ac-format", stage=stage, **kw)
        return seen[0].split("ac_format.py ", 1)[1]

    def test_e3_the_stage_reaches_the_script_from_stage_3(self):
        self.assertEqual(self.line(2), "--issue 42")
        self.assertEqual(self.line(3), "--issue 42 --stage 3")
        self.assertEqual(runner.plugin_args_for("ac-coverage", 3), [])

    def test_e30_deferred_rows(self):
        self.assertEqual(self.line(3, plugin_args=("--deferred", "R3,R5")), "--issue 42 --stage 3 --deferred R3,R5")
        self.assertEqual(self.line(3, plugin_args=("--stage", "3"), attempt=2), "--issue 42 --stage 3")

    def test_plugin_args_are_plain_tokens_of_ac_format_only(self):
        for stage, name, args in ((2, "ac-format", ("--deferred", "R3")), (3, "repro-red", ("--x",)), (3, "verification-frozen", ("--x",)),
                                  (3, "ac-format", ("; rm -rf /",)), (3, "ac-format", ("$(x)",)), (3, "ac-format", (3,)),
                                  (3, "ac-format", ("../x",))):
            with self.subTest(name=name, args=args), self.assertRaises(runner.RunnerError):
                self.run_s3(name, stage=stage, plugin_args=args)
