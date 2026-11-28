"""VB9: the engine runs the mutations a developer declared (stage4/interfaces.md §4) — REAL srt, a temporary repository.

killed · survived · timed-out · every refusal · control red · setup red · dirty run · crash leftovers. The tests of
the repository are shell files (tests/test_runner_stage3). No LLM, no network.
"""

import copy
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from gxengine import codes, defaults, gitops, mutation, paths as pathsmod, repoconfig, runner, schema, store
from tests import test_runner as TR
from tests.helpers.defects import fixes_defect
from tests import test_runner_stage3 as S3

APP = "src/app.sh"
TEST = "test/a_test.sh"
DECL = f"docs/specs/{TR.ISSUE}/mutations.json"
BASE = {APP: "x=1\ny=2\nhint=on\n", TEST: ". ./src/app.sh\n[ \"$x\" = 1 ]\n", "src/link-target.txt": "t\n"}


def entry(find="x=1", replace="x=9", path=APP, acs=(1,), note="n"):
    return {"acs": list(acs), "path": path, "find": find, "replace": replace, "note": note}


class Base(S3.Base):
    BASE_FILES = BASE

    def setUp(self):
        super().setUp()
        self.ep = pathsmod.EnginePaths(self.eng, "acme/repo", TR.ISSUE)
        self.lock = os.path.join(self.eng, "heavy-run.lock")

    def declare(self, *entries, raw=None, files=None):
        text = raw if raw is not None else json.dumps({"format": 1, "mutations": list(entries)})
        return self.put_files(dict(files or {}, **{DECL: text}))

    def request(self, head=None, config=None, **over):
        head = head or gitops.head(self.ctx)
        got = gitops.blob(self.ctx, head, DECL)
        f = dict(engine_paths=self.ep, ctx=self.ctx, config=config or self.config(), issue=TR.ISSUE, head=head,
                 blob=got[1] if got else "a" * 40, acs=[1, 2], render_paths=self.paths("mutation-proof"), base_env=self.base_env,
                 srt=TR.SRT, prepare_tree=None, heavy_lock=self.lock)
        f.update(over)
        return mutation.ProveRequest(**f)

    def prove(self, **over):
        rec = mutation.prove(self.request(**over))
        self.assertEqual(schema.errors(rec, schema.load_schema("mutation-record")), [])
        self.assertEqual(mutation.load(self.ep, rec["head"]), rec, "the record is on disk")
        self.assertNotIn("mutation-tree", self.worktrees())
        self.assertTrue(gitops.tree_state(self.ctx)["clean"])
        return rec

    def rows(self, rec):
        return [(r["status"], r["detail"]) for r in rec["rows"]]

    def text(self, rel):
        with open(os.path.join(self.ep.mutations_dir(gitops.head(self.ctx)), rel), encoding="utf-8") as f:
            return f.read()


class Runs(Base):
    def test_killed_and_survived(self):
        self.declare(entry(), entry("hint=on\n", "", acs=[2]))
        rec = self.prove()
        self.assertIsNone(rec["problem"])
        self.assertEqual(rec["control"]["exit_code"], 0)
        self.assertEqual(self.rows(rec), [("killed", None), ("survived", None)])
        self.assertEqual([r["id"] for r in rec["rows"]], ["M1", "M2"])
        self.assertEqual((rec["rows"][0]["run"]["exit_code"], rec["rows"][1]["run"]["exit_code"]), (1, 0))
        self.assertEqual(rec["rows"][1]["acs"], [2])
        self.assertTrue(os.path.isfile(os.path.join(self.ep.mutations_dir(rec["head"]), rec["rows"][0]["run"]["log_file"])))

    def test_each_mutation_runs_on_head_alone(self):
        """The first mutation is gone when the second runs; the Issue worktree is never touched."""
        self.declare(entry(), entry("y=2", "y=3"), entry(), files={TEST: ". ./src/app.sh\n[ \"$x$y\" = 12 ] || { echo got $x$y; exit 1; }\n"})
        rec = self.prove()
        self.assertEqual(self.rows(rec), [("killed", None)] * 3)
        self.assertEqual([r["log_tail"].strip() for r in rec["rows"]], ["got 92", "got 13", "got 92"])
        ex = rec["rows"][0]["log_excerpt"].splitlines()
        self.assertEqual(ex, [f"[gld engine] m1.log, lines 1-1 of 1: {mutation.R_NEW}", "1| got 92"],
                         "no failure word: the first line the green control did not print")

    def test_a_green_run_has_no_excerpt(self):
        self.declare(entry(), entry("hint=on\n", "", acs=[2]))
        rec = self.prove()
        self.assertEqual(rec["rows"][0]["log_excerpt"], f"[gld engine] m1.log, 0 lines: {mutation.R_NONE}",
                         "a red run that printed nothing says so")
        self.assertEqual(rec["rows"][1]["log_excerpt"], "", "survived: nothing failed")

    def test_a_removal(self):
        self.declare(entry("x=1\n", ""))
        self.assertEqual(self.rows(self.prove()), [("killed", None)])

    def test_the_branch_file_not_the_base_is_mutated(self):
        self.declare(entry("z=7", "z=8"), files={APP: "x=1\nz=7\n", TEST: ". ./src/app.sh\n[ \"$z\" = 7 ]\n"})
        self.assertEqual(self.rows(self.prove()), [("killed", None)])

    def test_a_timeout_is_never_killed(self):
        self.declare(entry(), files={TEST: ". ./src/app.sh\n[ \"$x\" = 1 ] || sleep 31\n"})
        rec = self.prove(config=self.config(S3.ShortTest))
        self.assertEqual(self.rows(rec), [("timed-out", None)])
        self.assertTrue(rec["rows"][0]["run"]["timed_out"])

    def test_the_log_tail_is_short(self):
        self.declare(entry(), files={TEST: ". ./src/app.sh\n[ \"$x\" = 1 ] && exit 0\ni=0; while [ $i -lt 100 ]; do echo line$i; i=$((i+1)); done; exit 1\n"})
        tail = self.prove()["rows"][0]["log_tail"].splitlines()
        self.assertEqual((len(tail), tail[-1]), (defaults.MUTATION_LOG_LINES, "line99"))

    def test_an_executable_stays_executable(self):
        self.repo.write("src/run.sh", "echo 1\n", cwd=self.wt)
        os.chmod(os.path.join(self.wt, "src/run.sh"), 0o755)
        self.declare(entry("echo 1", "echo 2", path="src/run.sh"), files={TEST: "[ \"$(./src/run.sh)\" = 1 ]\n"})
        rec = self.prove()
        self.assertEqual(self.rows(rec), [("killed", None)])
        self.assertNotIn("denied", rec["rows"][0]["log_tail"])

    def test_the_commands_take_the_heavy_lock_and_run_under_srt(self):
        self.declare(entry())
        seen, real = [], runner.run_named

        def spy(*a, heavy_lock=None, **kw):
            seen.append((kw["label"], heavy_lock))
            return real(*a, heavy_lock=heavy_lock, **kw)
        with mock.patch.object(runner, "run_named", spy):
            self.prove()
        self.assertEqual(seen, [("setup", self.lock), ("control", self.lock), ("m1", self.lock)])
        with open(os.path.join(self.ep.mutations_dir(gitops.head(self.ctx)), "try-1", "srt-m1.json")) as f:
            from gxengine import render
            render.check_srt_settings(json.load(f))

    def test_prepare_tree_is_called_with_the_temporary_tree(self):
        self.declare(entry())
        trees = []
        self.prove(prepare_tree=trees.append)
        self.assertEqual([os.path.basename(t) for t in trees], ["mutation-tree"])


class NotRun(Base):
    def assertNotRun(self, rec, why, control="absent"):
        self.assertEqual(self.rows(rec), [("not-run", None)] * len(rec["rows"]))
        self.assertIn(why, rec["rows"][0]["log_tail"])
        if control != "absent":
            self.assertEqual(rec["control"] and rec["control"]["exit_code"], control)

    def test_a_red_control_proves_nothing(self):
        self.declare(entry(), entry("y=2", ""), files={TEST: "exit 1\n"})
        self.assertNotRun(self.prove(), "control", control=1)

    def test_a_control_that_dirties_the_tree(self):
        self.declare(entry(), files={TEST: "echo x > left.txt\n"})
        self.assertNotRun(self.prove(), "control", control=0)

    def test_a_red_setup(self):
        self.declare(entry(), files={"test/breaks_setup_test.sh": "true\n"})
        self.assertNotRun(self.prove(), "setup", control=None)

    def test_no_test_command(self):
        self.declare(entry())
        self.assertNotRun(self.prove(config=self.config(test=None)), "test", control=None)

    def test_a_mutated_run_that_leaves_other_changes(self):
        self.declare(entry(), entry("y=2", "y=3"),
                     files={TEST: ". ./src/app.sh\n[ \"$x\" = 1 ] || { echo x > left.txt; exit 1; }\n[ $y = 2 ]\n"})
        rec = self.prove()
        self.assertEqual(self.rows(rec), [("not-run", None), ("killed", None)], "the tree is restored for the next one")
        self.assertEqual(rec["rows"][0]["run"]["exit_code"], 1)
        self.assertIn("left.txt", rec["rows"][0]["log_tail"])

    def test_a_tree_that_cannot_be_made(self):
        self.declare(entry())
        with mock.patch.object(gitops, "detached_worktree", side_effect=gitops.GitError("no tree")):
            rec = mutation.prove(self.request())
        self.assertNotRun(rec, "no tree", control=None)

    def test_a_run_that_cannot_be_started(self):
        self.declare(entry())
        self.assertNotRun(self.prove(srt="/nonexistent/srt"), "srt")

    def test_after_an_engine_death_the_leftovers_do_not_matter(self):
        self.declare(entry())
        p = self.paths("mutation-proof")
        os.makedirs(p["run_tmp"])
        gitops.detached_worktree(self.ctx, os.path.join(p["run_tmp"], mutation.TREE), gitops.head(self.ctx))
        os.makedirs(os.path.join(self.ep.mutations_dir(gitops.head(self.ctx)), "try-1"))
        rec = self.prove()
        self.assertEqual(self.rows(rec), [("killed", None)])
        self.assertEqual(rec["rows"][0]["run"]["log_file"], "try-2/m1.log")


def counted(*fail):
    """A test script that counts its runs in $TMPDIR (the proof's tmp, kept across its runs) and on run n
    prints fail[n] and exits 1; None = the real test (x must be 1). Run numbers start at 1 (the control)."""
    cases = "".join(f"[ $n = {i} ] && {{ echo '{msg}'; exit 1; }}\n" for i, msg in enumerate(fail, 1) if msg is not None)
    return ("n=$(cat \"$TMPDIR/n\" 2>/dev/null || echo 0); n=$((n+1)); echo $n > \"$TMPDIR/n\"\n" + cases
            + ". ./src/app.sh\n[ \"$x\" = 1 ] || { echo \"assertion: x is $x\"; exit 1; }\n")


PERF = "01:15 +4440 -1: perf: build median is under 50ms [E]"


class Flaky(Base):
    """VW2 E1: the control is run again when red (K8-2); after a flaky control a red mutation must be red twice,
    each time with a failure line no control run showed."""

    def labels(self, **over):
        seen, real = [], runner.run_named

        def spy(*a, **kw):
            seen.append(kw["label"])
            return real(*a, **kw)
        with mock.patch.object(runner, "run_named", spy):
            rec = self.prove(**over)
        return rec, seen

    @fixes_defect("E1", "escalate:env-problem @ done-gate")
    def test_a_control_red_once_is_run_again_and_the_proof_goes_on(self):
        self.declare(entry(), files={TEST: counted(PERF)})
        rec, seen = self.labels()
        self.assertEqual(seen, ["setup", "control", "control.rerun", "m1", "m1.rerun"])
        c = rec["control"]
        self.assertEqual((c["exit_code"], c["again"]["exit_code"], c["flaky"]), (1, 0, True))
        self.assertEqual(c["again"]["log_file"], "try-1/control.rerun.log")
        self.assertEqual(self.rows(rec), [("killed", None)])
        row = rec["rows"][0]
        self.assertEqual((row["run"]["exit_code"], row["again"]["exit_code"]), (1, 1))
        self.assertIn("assertion: x is 9", row["log_tail"])
        ex = row["log_excerpt"].splitlines()
        self.assertEqual(ex[0], f"[gld engine] m1.rerun.log, lines 1-1 of 1: {mutation.R_LINE}{mutation.R_FRESH}",
                         "the same run as log_tail; compared with the GREEN control run, not the red one")
        self.assertEqual(ex[1], "1| assertion: x is 9")

    def test_a_control_red_twice_proves_nothing(self):
        self.declare(entry(), files={TEST: counted(PERF, PERF)})
        rec, seen = self.labels()
        self.assertEqual(seen, ["setup", "control", "control.rerun"])
        self.assertEqual((rec["control"]["again"]["exit_code"], rec["control"]["flaky"]), (1, False))
        self.assertEqual(self.rows(rec), [("not-run", None)])
        self.assertIn("twice", rec["rows"][0]["log_tail"])
        self.assertTrue(mutation.retryable(rec))

    def test_a_red_control_that_changed_the_tree_is_not_run_again(self):
        self.declare(entry(), files={TEST: "echo x > left.txt; exit 1\n"})
        rec, seen = self.labels()
        self.assertEqual(seen, ["setup", "control"])
        self.assertIsNone(rec["control"]["again"])
        self.assertIn("not run again", rec["rows"][0]["log_tail"])

    def test_a_green_control_keeps_one_run_per_mutation(self):
        self.declare(entry(), entry("hint=on\n", "", acs=[2]))
        rec, seen = self.labels()
        self.assertEqual(seen, ["setup", "control", "m1", "m2"])
        self.assertEqual((rec["control"]["again"], rec["control"]["flaky"]), (None, False))
        self.assertEqual([r["again"] for r in rec["rows"]], [None, None])

    def test_a_red_that_only_repeats_the_control_failure_is_no_kill(self):
        """The flaky failure again under a mutation the tests do not even look at: not killed, not run again."""
        self.declare(entry("y=2", "y=3"), files={TEST: counted(PERF.replace("50", "51"), None, PERF)})
        rec, seen = self.labels()
        self.assertEqual(seen, ["setup", "control", "control.rerun", "m1"])
        self.assertEqual(self.rows(rec), [("not-run", None)])
        self.assertEqual(rec["rows"][0]["run"]["exit_code"], 1)
        self.assertIn(mutation.SAME_RED, rec["rows"][0]["log_tail"])
        self.assertTrue(mutation.retryable(rec), "no row was decided by a run: a person may rerun it")

    def test_red_then_green_with_the_mutation_is_no_kill(self):
        self.declare(entry("y=2", "y=3"), files={TEST: counted(PERF, None, "another flaky test failed")})
        rec, seen = self.labels()
        self.assertEqual(seen, ["setup", "control", "control.rerun", "m1", "m1.rerun"])
        self.assertEqual(self.rows(rec), [("not-run", None)])
        self.assertEqual(rec["rows"][0]["again"]["exit_code"], 0)
        self.assertIn("red, then green", rec["rows"][0]["log_tail"])

    def test_a_second_red_with_only_the_control_failure_is_no_kill(self):
        self.declare(entry("y=2", "y=3"), files={TEST: counted(PERF, None, "something new", PERF)})
        rec = self.prove()
        self.assertEqual(self.rows(rec), [("not-run", None)])
        self.assertIn("second run", rec["rows"][0]["log_tail"])

    def test_a_second_run_that_times_out_is_timed_out(self):
        script = counted(PERF).replace(". ./src/app.sh", "[ $n = 4 ] && sleep 31\n. ./src/app.sh")
        self.declare(entry(), files={TEST: script})
        rec = self.prove(config=self.config(S3.ShortTest))
        self.assertEqual(self.rows(rec), [("timed-out", None)])
        self.assertTrue(rec["rows"][0]["again"]["timed_out"])

    def test_the_line_comparison(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)

        def log(name, text):
            p = os.path.join(d, name)
            with open(p, "w", encoding="utf-8") as f:
                f.write(text)
            return p
        red = log("red", "\x1b[31m01:15 +4440 -1: perf [E]\x1b[0m\nSome tests failed.\n")
        green = log("green", "01:20 +9419: All tests passed!\n")
        sigs = [mutation._signature(red), mutation._signature(green)]
        self.assertFalse(mutation._new_failure(log("same", "01:16 +12 -1: perf [E]\n\nSome tests failed.\n"), sigs),
                         "times, counters and colours never make a line new")
        self.assertTrue(mutation._new_failure(log("new", "01:16 +12 -1: loads [E]\nSome tests failed.\n"), sigs))
        self.assertFalse(mutation._new_failure(os.path.join(d, "missing"), sigs), "unreadable = no proof")
        self.assertFalse(mutation._new_failure(log("n2", "loads [E]\n"), [sigs[0], None]))
        with mock.patch.object(mutation, "SIGNATURE_MAX_BYTES", 3):
            self.assertIsNone(mutation._signature(red))


VW3 = os.path.join(os.path.dirname(__file__), "fixtures", "mutation", "vw3_1938")
"""#1938 VW3 (mutations/27dffac…/try-1): m1.log lines 1-12, 140-150, 236-250, 2710-2725, 3925-4010 and control.log
lines 1-12, 138-152, 185-196, 2685-2700, 9910-9930, the home path made neutral. Kept: progress lines the control
printed too, two progress lines whose test NAME has a failure word (m1 241 / 247), the TTS error lines both runs
printed, and the end of the --fail-fast run — its one assertion (Expected: <1>, Actual: <2>, test line 105) more
than 40 lines above the end, then the clean-up of the tests it closed."""
VW3_TREE = "/home/u/.gld/tmp/owner/app_a/1938/mutation-proof-1/mutation-tree"


class Excerpt(unittest.TestCase):
    """VW3 E2: the leader reads where a red run FIRST failed (`log_excerpt`), not only its end."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d)

    def log(self, name, text):
        p = os.path.join(self.d, name)
        with open(p, "wb") as f:
            f.write(text.encode("utf-8") if isinstance(text, str) else text)
        return p

    def vw3(self, **kw):
        base = kw.pop("baseline", mutation._signature(os.path.join(VW3, "control.log")))
        return mutation._excerpt(os.path.join(VW3, "m1.log"), base, tree=kw.pop("tree", VW3_TREE), **kw)

    def assertDecisive(self, ex):
        self.assertIn("| Expected: <1>", ex)
        self.assertIn("|   Actual: <2>", ex)
        self.assertIn("<tree>/test/features/kanji_detail_modal/widgets/kanji_strokes_section_probe_safety_net_test.dart:105:5", ex)
        self.assertLess(ex.index("Expected: <1>"), ex.index("ClosedException") if "ClosedException" in ex else len(ex))
        self.assertLessEqual(len(ex), defaults.MUTATION_EXCERPT_MAX)

    @fixes_defect("E2", "escalate:env-problem @ done-gate")
    def test_vw3_the_assertion_reaches_the_excerpt_not_only_the_tail(self):
        tail = mutation._tail(os.path.join(VW3, "m1.log"))
        self.assertNotIn("Expected: <1>", tail, "the E2 reproduction: the end of the log is the clean-up only")
        self.assertIn("did not complete", tail)
        ex = self.vw3()
        lines = ex.splitlines()
        self.assertEqual(lines[0], f"[gld engine] m1.log, lines 66-97 of 140: {mutation.R_BLOCK}")
        self.assertDecisive(ex)
        self.assertNotIn(VW3_TREE, ex, "the temporary tree is written <tree>")
        self.assertTrue(lines[-1].startswith("[gld engine] other failure-mark lines: 29, 35, "), lines[-1])
        self.assertNotIn("TTS speak error", ex, "lines the green control printed too are no failure")

    def test_vw3_without_a_comparable_control(self):
        ex = self.vw3(baseline=None)
        self.assertTrue(ex.splitlines()[0].endswith(mutation.R_BLOCK + mutation.NO_BASE))
        self.assertDecisive(ex)

    def test_vw3_the_leader_input_holds_it(self):
        from gxengine import leader as leadermod

        class R:
            mutations = {"problem": None, "control": {"flaky": False}, "rows": [
                {"id": "M1", "acs": [6], "path": "lib/a.dart", "find": "f", "replace": "", "note": "", "status": "killed",
                 "detail": None, "run": {"exit_code": 1}, "log_tail": mutation._tail(os.path.join(VW3, "m1.log")),
                 "log_excerpt": self.vw3()}]}
        row = leadermod._mutations(R)["rows"][0]
        self.assertDecisive(row["log_excerpt"])
        self.assertNotIn(defaults.LEADER_INPUT_TRUNCATION_MARK, row["log_excerpt"])
        self.assertTrue(row["log_tail"].endswith("... and 7 more"), "the end of the log stays")

    def test_flaky_a_block_the_red_control_printed_whole_is_skipped(self):
        """The mutated run fails first like the red control did (its flaky test), then on the assertion."""
        flaky = ("══╡ EXCEPTION CAUGHT BY FLUTTER TEST FRAMEWORK ╞══\nThe following TestFailure was thrown running a test:\n"
                 "Expected: a value less than <50>\n  Actual: <81>\n\nWhen the exception was thrown, this was the stack:\n"
                 "00:12 +40 -1: perf_test.dart: build median [E]\n")
        red = self.log("control.log", "00:01 +1: a\n" + flaky + "Some tests failed.\n")
        green = self.log("control.rerun.log", "00:01 +1: a\n00:02 +2: All tests passed!\n")
        m1 = self.log("m1.rerun.log", "00:01 +1: a\n" + flaky.replace("50", "51").replace("81", "93")
                      + "00:13 +40 -2: probe_test.dart: reads once\n" + "x\n" * 20
                      + "══╡ EXCEPTION CAUGHT BY FLUTTER TEST FRAMEWORK ╞══\nThe following TestFailure was thrown running a test:\n"
                      "Expected: <1>\n  Actual: <2>\n#4 main (probe_test.dart:105:5)\n")
        ex = mutation._excerpt(m1, mutation._signature(green), red=mutation._signature(red))
        self.assertEqual(ex.splitlines()[0], f"[gld engine] m1.rerun.log, lines 24-34 of 34: {mutation.R_BLOCK}{mutation.R_FRESH}")
        self.assertIn("33|   Actual: <2>", ex)
        self.assertNotIn("a value less than", ex.split("other failure-mark lines")[0])
        same = self.log("m2.log", "00:01 +1: a\n" + flaky)
        self.assertTrue(mutation._excerpt(same, mutation._signature(green), red=mutation._signature(red))
                        .splitlines()[0].endswith(mutation.R_STALE), "only the flaky failure: said so, shown anyway")

    def test_a_large_log_is_cut_and_says_so(self):
        noise = "".join(f"00:{i % 60:02d} +{i}: test/t{i}_test.dart: case {i}\n" for i in range(5000))
        block = "FAIL test/x_test.py::test_flag\n" + "".join(f"E   AssertionError: line {i} " + "y" * 400 + "\n"
                                                           for i in range(60))
        green = self.log("green", noise)
        red = self.log("m1.log", noise + block + "1 failed\n")
        ex = mutation._excerpt(red, mutation._signature(green))
        lines = ex.splitlines()
        self.assertTrue(lines[0].startswith("[gld engine] m1.log, lines 4995-5062 of 5062:"), lines[0])
        self.assertLessEqual(len(ex), defaults.MUTATION_EXCERPT_MAX)
        self.assertIn("5001| FAIL test/x_test.py::test_flag", ex)
        self.assertTrue(any(x.endswith("y…") and len(x) == len("5002| ") + mutation.EXCERPT_LINE_MAX + 1 for x in lines),
                        "a long line is cut")
        cut = [x for x in lines if x.startswith(defaults.LEADER_INPUT_TRUNCATION_MARK)]
        self.assertEqual(len(cut), 1)
        self.assertRegex(cut[0], r"lines \d+-5062 not shown$")
        self.assertTrue(lines[-1].startswith("[gld engine] other failure-mark lines: "))
        with mock.patch.object(mutation, "SIGNATURE_MAX_BYTES", 2000):
            self.assertIn("(only the first 2000 bytes read)", mutation._excerpt(red, None).splitlines()[0])

    def test_without_a_failure_word(self):
        green = mutation._signature(self.log("green", "00:01 +1: a\n00:02 +2: b\nok\n"))
        ex = mutation._excerpt(self.log("m1.log", "00:01 +1: a\n00:03 +2: b\n  x got 3 want 4\nbad\n"), green)
        self.assertEqual(ex.splitlines(), [f"[gld engine] m1.log, lines 1-4 of 4: {mutation.R_NEW}",
                                           "1| 00:01 +1: a", "2| 00:03 +2: b", "3|   x got 3 want 4", "4| bad"])
        self.assertEqual(mutation._excerpt(self.log("m2.log", "00:09 +1: a\n\x1b[31mok\x1b[0m\n"), green),
                         f"[gld engine] m2.log, 2 lines: {mutation.R_NONE}", "times and colours make no line new")
        self.assertEqual(mutation._excerpt(self.log("m3.log", "x got 3\n"), None),
                         f"[gld engine] m3.log, 1 lines: {mutation.R_NONE}{mutation.NO_BASE}", "no control to compare and no mark")

    def test_a_test_name_with_a_failure_word_is_no_block(self):
        green = mutation._signature(self.log("green", "ok\n"))
        ex = mutation._excerpt(self.log("m1.log", "00:01 +1: shows the error page\n" + "x\n" * 10
                                        + "Error: boom\n  at f (a.js:3)\nAssertionError: x\n"), green)
        self.assertEqual(ex.splitlines()[0], f"[gld engine] m1.log, lines 6-14 of 14: {mutation.R_BLOCK}")
        self.assertEqual(ex.splitlines()[-1], "[gld engine] other failure-mark lines: 1")
        one = mutation._excerpt(self.log("m2.log", "x\npanic: nil map\n"), green)
        self.assertEqual(one.splitlines()[0], f"[gld engine] m2.log, lines 1-2 of 2: {mutation.R_LINE}")

    def test_the_marks(self):
        for yes in ("FAIL: TestX", "--- FAIL: TestX (0.00s)", "Error: x", "TypeError: y", "ClosedException", "assert x == 1",
                    "AssertionError", "Expected: <1>", "panic: x", "Traceback (most recent call last):", "not ok 3 - x",
                    "✗ x", "✕ y", "1 failed", "did not complete [E]", "fatal: z", "TestFailure was thrown"):
            with self.subTest(yes=yes):
                self.assertIsNotNone(mutation.FAIL_MARK.search(yes.encode()))
        for no in ("error_view_test.dart: shows", "00:01 +3: ok", "expectLater(x)", "+3 ~1: loading", "terror", "Errors_x"):
            with self.subTest(no=no):
                self.assertIsNone(mutation.FAIL_MARK.search(no.encode()))

    def test_an_unreadable_log(self):
        self.assertEqual(mutation._excerpt(os.path.join(self.d, "missing.log"), set()), "")


class Supersede(Base):
    """VW2 E1: a human rerun may replace a record without any run fact — never one with a fact."""

    def test_a_record_without_a_run_fact_is_moved_aside_and_proved_again(self):
        head = self.declare(entry(), files={TEST: counted(PERF, PERF)})
        first = self.prove()
        self.assertEqual(mutation.supersede(self.ep, head), "superseded-1.json")
        self.assertIsNone(mutation.load(self.ep, head))
        with open(os.path.join(self.ep.mutations_dir(head), "superseded-1.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f), first, "kept as it was")
        second = self.prove()                    # the proof's $TMPDIR is kept: run 3 is the real test
        self.assertEqual(second["control"]["log_file"], "try-2/control.log")
        self.assertEqual(self.rows(second), [("killed", None)])
        self.assertIsNone(mutation.supersede(self.ep, head), "a record with a kill is never replaced")
        self.assertIsNone(mutation.supersede(self.ep, "c" * 40), "no record")

    def test_what_is_retryable(self):
        def rec(*statuses):
            return {"rows": [{"status": s} for s in statuses]}
        self.assertTrue(mutation.retryable(rec("not-run")))
        self.assertTrue(mutation.retryable(rec("not-run", "refused")))
        for no in (rec(), rec("refused"), rec("not-run", "killed"), rec("not-run", "survived"), rec("timed-out", "not-run")):
            with self.subTest(rows=no["rows"]):
                self.assertFalse(mutation.retryable(no))


class Refused(Base):
    def one(self, e, files=None, **over):
        self.declare(e, files=files)
        with mock.patch.object(runner, "run_named", side_effect=AssertionError("nothing may run")):
            rec = self.prove(**over)
        self.assertIsNone(rec["control"])
        self.assertEqual(rec["rows"][0]["status"], "refused")
        return rec["rows"][0]["detail"]

    def test_every_refusal_of_a_row(self):
        M = codes.MutationRefusal
        for e, want in ((entry(acs=[3]), M.UNKNOWN_AC), (entry(acs=[1, 3]), M.UNKNOWN_AC),
                        (entry(path="src/none.sh"), M.BAD_PATH), (entry(path="src"), M.BAD_PATH),
                        (entry(path="CLAUDE.md"), M.BAD_PATH), (entry(path="pkg/AGENTS.md", find="pkg", replace=""), M.BAD_PATH),
                        (entry(path=".claude/settings.json"), M.BAD_PATH), (entry(path=".git/config"), M.BAD_PATH),
                        (entry(path=DECL, find="format", replace=""), M.BAD_PATH), (entry(path="docs/specs/7/x.md"), M.BAD_PATH),
                        (entry(path=TEST, find="exit", replace=""), M.VERIFICATION_PATH),
                        (entry(path="TEST/a_test.sh"), M.BAD_PATH),
                        (entry(find="nowhere"), M.NOT_UNIQUE), (entry(find="=", replace=""), M.NOT_UNIQUE),
                        (entry(find="x=1", replace="x=1"), M.NO_CHANGE)):
            with self.subTest(path=e["path"], find=e["find"], acs=e["acs"]):
                self.assertEqual(self.one(dict(e, note=want.value + e["path"] + e["find"])), want.value)

    def test_overlapping_occurrences_are_not_unique(self):
        self.assertEqual(self.one(entry(find="aa", replace="b"), files={APP: "aaa\n"}), "not-unique")

    def test_a_link_is_no_file_to_change(self):
        os.symlink("link-target.txt", os.path.join(self.wt, "src", "link.txt"))
        self.assertEqual(self.one(entry(path="src/link.txt", find="link", replace="")), "bad-path")

    def test_test_code_and_safety_net_rules_count_too(self):
        raw = copy.deepcopy(S3.CONFIG)
        raw["path_rules"] = [{"kind": "test-code", "globs": ["spec/**"]}]
        cfg = repoconfig.RepoConfig(raw)
        self.assertEqual(self.one(entry(path="spec/a.sh", find="a", replace="b"), files={"spec/a.sh": "a\n"}, config=cfg),
                         "verification-path")

    def test_without_any_rule_nothing_is_production_code(self):
        raw = copy.deepcopy(S3.CONFIG)
        raw["path_rules"] = []
        self.assertEqual(self.one(entry(), config=repoconfig.RepoConfig(raw)), "verification-path")

    def test_a_refused_row_does_not_stop_the_others(self):
        self.declare(entry(path=TEST, find="=", replace=""), entry())
        rec = self.prove()
        self.assertEqual(self.rows(rec), [("refused", "verification-path"), ("killed", None)])

    def test_a_file_that_is_no_declaration(self):
        many = json.dumps({"format": 1, "mutations": [entry()] * (defaults.MUTATIONS_MAX + 1)})
        for raw in ("not json", "{}", '{"format": 1, "mutations": []}', '{"format": 1, "format": 1, "mutations": []}', many,
                    json.dumps({"format": 1, "mutations": [dict(entry(), cmd="rm -rf /")]}),
                    json.dumps({"format": 1, "mutations": [dict(entry(), result="killed")]}),
                    json.dumps({"format": 1, "mutations": [entry(find="\ud800")]})):
            with self.subTest(raw=raw[:60]), mock.patch.object(runner, "run_named", side_effect=AssertionError):
                self.declare(raw=raw)
                rec = self.prove()
                self.assertEqual((rec["problem"], rec["rows"], rec["control"]), ("bad-file", [], None))

    def test_a_link_or_another_blob_is_no_declaration(self):
        head = self.declare(entry())
        rec = mutation.prove(self.request(blob="b" * 40))
        self.assertEqual(rec["problem"], "bad-file")
        os.unlink(self.ep.mutation_record(head))
        os.unlink(os.path.join(self.wt, DECL))
        os.symlink("../../../README.md", os.path.join(self.wt, DECL))
        self.repo.commit("link", cwd=self.wt)
        self.assertEqual(mutation.prove(self.request())["problem"], "bad-file")


class Unsafe(Base):
    def test_a_moved_git_link_stops(self):
        self.declare(entry())
        r = self.request()
        with open(os.path.join(self.wt, ".git"), "w") as f:
            f.write("gitdir: /tmp\n")
        with self.assertRaises(gitops.UnsafePath):
            mutation.prove(r)
        self.assertIsNone(store.read_record(self.ep, self.ep.mutation_record(r.head), "mutation-record"))


if __name__ == "__main__":
    unittest.main()
