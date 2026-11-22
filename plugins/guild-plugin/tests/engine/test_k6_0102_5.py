"""0.102.5 — the patch after the real word_app #1945 runs (k6-notes "0.102.5", user decision 2026-11-22 "사람 개입
최소화"): base merges on the Issue's branch are accepted, other drift asks accept/stop; a recurring blocker gets one
automatic developer retry with the cause and a fix hint; a red suite with ≤ 2 failing tests re-runs them once; an
`unsure` code check no longer turns a verdict into a gap; the effectiveness check runs the real app tests (agent
working dirs are no secrets, golden diffs are assertions, an AC's tests react together, a test that cannot run alone
runs in its file); a remote ref deleted elsewhere is no scope violation; unverified groups run and are graded after."""

import json
import os
import sys
import unittest

import _util  # noqa: F401
from _k1 import Clock, FakeSpawn, RecJournal, git, repo, stream_lines, tmpdir
from _k2 import CFG, FLUTTER_GREEN, Harness, decision, fixture, judge_test, role, suite
from _k3 import XHarness, auditor, dev, finding

from guildcore import ask as ASK
from guildcore import checks as CH
from guildcore.checks import CheckResult
from guildcore.decisions import DecisionLog
from guildcore.roles import runner as RR
from guildcore.roles import scope as SC
from guildcore.roles.runner import RoleResult
from workflows.dev import conservative as CONS
from workflows.dev import effective as EFF
from workflows.dev import flake as FL
from workflows.dev import grade as G
from workflows.dev import unverified as UV
from workflows.dev.stages import base as B
from workflows.dev.stages import execute as X
from workflows.dev.stages import test as T

DONE = ">>> RESULT <<<\nDONE: ok"


class EvJournal(RecJournal):
    def __init__(self):
        RecJournal.__init__(self)
        self.events = []

    def append(self, kind, **f):
        self.events.append(dict(f, kind=kind))


def _write(d, rel, text):
    p = os.path.join(d, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as fh:
        fh.write(text)


# ---- 1. drift: base merges accepted, any other drift asks accept / stop ----------------------------------------

class BaseMerge(unittest.TestCase):
    # 0.102.6 (review-0102-5 M1): the base a merge may bring in is the REMOTE's (read by the engine) — the fixture has a
    # real bare `origin`; the person's flow is #1945's: `git fetch` then `git merge origin/main` in the worktree
    def setUp(self):
        self.main = repo(self, {"a.txt": "a\n", "b.txt": "b\n"})
        self.origin = os.path.join(tmpdir(self), "origin.git")
        git(self.main, "clone", "-q", "--bare", self.main, self.origin)
        git(self.main, "remote", "add", "origin", self.origin)
        git(self.main, "fetch", "-q", "origin")
        self.wt = os.path.join(tmpdir(self), "wt")
        git(self.main, "worktree", "add", "-q", "-b", "fix/1", self.wt)
        _write(self.wt, "lib/x.txt", "work\n")
        git(self.wt, "add", "-A")
        git(self.wt, "commit", "-qm", "work")
        self.base = SC.snapshot(self.wt)

    def _main_moves(self):
        _write(self.main, "a.txt", "a2\n")
        git(self.main, "commit", "-qam", "main moves")
        git(self.main, "push", "-q", "origin", "main")
        git(self.wt, "fetch", "-q", "origin")

    def test_a_merge_of_main_is_accepted(self):
        self._main_moves()
        git(self.wt, "merge", "-q", "--no-edit", "origin/main")
        now = SC.snapshot(self.wt)
        self.assertTrue({"ref refs/heads/fix/1", "HEAD"} <= set(SC.drift(self.base, now, self.wt)))
        got = SC.accept_base_merge(self.wt, self.base, now, "fix/1", "origin/main")
        self.assertEqual(got, [git(self.wt, "rev-parse", "HEAD")])
        self.assertEqual(SC.accept_base_merge(self.wt, self.base, now, "fix/1", "main"), got)   # same remote base

    def test_a_merge_carrying_a_hand_edit_is_not(self):
        self._main_moves()
        git(self.wt, "merge", "-q", "--no-commit", "--no-ff", "origin/main")
        _write(self.wt, "a.txt", "edited in the merge\n")
        git(self.wt, "add", "-A")
        git(self.wt, "commit", "-qm", "merge with an edit")
        self.assertIsNone(SC.accept_base_merge(self.wt, self.base, SC.snapshot(self.wt), "fix/1", "origin/main"))

    def test_a_plain_commit_or_a_dirty_tree_is_not(self):
        _write(self.wt, "lib/y.txt", "late\n")
        self.assertIsNone(SC.accept_base_merge(self.wt, self.base, SC.snapshot(self.wt), "fix/1", "origin/main"))
        git(self.wt, "add", "-A")
        git(self.wt, "commit", "-qm", "a person's commit")
        self.assertIsNone(SC.accept_base_merge(self.wt, self.base, SC.snapshot(self.wt), "fix/1", "origin/main"))

    def test_a_merge_of_another_branch_is_not(self):
        git(self.main, "branch", "side")
        git(self.main, "switch", "-q", "side")
        _write(self.main, "side.txt", "s\n")
        git(self.main, "add", "-A")
        git(self.main, "commit", "-qm", "side")
        git(self.main, "switch", "-q", "main")
        git(self.wt, "merge", "-q", "--no-edit", "side")
        self.assertIsNone(SC.accept_base_merge(self.wt, self.base, SC.snapshot(self.wt), "fix/1", "origin/main"))

    def _runner(self, sessions, journal):
        return RR.Runner(journal=journal, parent_env={"PATH": os.environ["PATH"]}, spawn=FakeSpawn(sessions),
                         user_settings=os.path.join(tmpdir(self), "u"), run_root_dir=os.path.join(tmpdir(self), "runs"),
                         claude="claude", clock=Clock())

    def _spec(self, role="developer", task="implement"):
        return RR.RoleSpec(role, task, "t", issue=1, stage="s", step="x", worktree=self.wt, model="sonnet",
                           base="origin/main", branch="fix/1", remote_check=False)

    def test_the_runner_accepts_a_base_merge_and_runs_the_role(self):
        j = EvJournal()
        r = self._runner([{"stream": stream_lines(texts=[DONE])}, {"stream": stream_lines(texts=[DONE])}], j)
        self.assertEqual(r.run_role(self._spec()).status, "DONE")
        self._main_moves()
        git(self.wt, "merge", "-q", "--no-edit", "origin/main")
        res = r.run_role(self._spec("reviewer", None))
        self.assertEqual(res.status, "DONE")
        self.assertEqual(len(r.spawn.calls), 2)
        self.assertTrue(any("drift accepted: base merge" in n for n in res.notes))
        self.assertEqual([e["what"] for e in j.events if e.get("what") == "drift-accepted"], ["drift-accepted"])
        self.assertEqual(r.drift_check(self.wt, 1), [])

    def test_the_runner_still_stops_any_other_drift(self):
        r = self._runner([{"stream": stream_lines(texts=[DONE])}], EvJournal())
        r.run_role(self._spec())
        _write(self.wt, "lib/late.txt", "late\n")
        res = r.run_role(self._spec("reviewer", None))
        self.assertEqual(res.status, "DRIFT")
        self.assertIn("not run", res.notes)

    def test_the_push_drift_check_accepts_it_too(self):
        r = self._runner([{"stream": stream_lines(texts=[DONE])}], EvJournal())
        r.run_role(self._spec())
        self._main_moves()
        git(self.wt, "merge", "-q", "--no-edit", "origin/main")
        self.assertNotEqual(r.drift_check(self.wt, 1), [])                       # without the branch: strict
        self.assertEqual(r.drift_check(self.wt, 1, "fix/1", "origin/main"), [])


LATE = ["late change after the previous step: ref refs/heads/fix/1", "late change after the previous step: HEAD"]


class DriftQuestion(unittest.TestCase):
    def _h(self, unattended, roles=()):
        h = Harness(self, fixture(labels=("guild:test",)), roles=list(roles), unattended=unattended)
        h.accepted = []
        h.p.accept_drift = lambda fp: h.accepted.append(fp)                    # None: accepted (0.102.6 M2)
        return h

    def _drift(self):
        return RoleResult("DRIFT", "worktree changed", violations=list(LATE), notes=["not run"],
                          extras={"drift_fp": "fp1"})

    def test_attended_asks_accept_or_stop_never_a_dead_end(self):
        h = self._h(False)
        r = B.role_outcome(h.p, "test", "tester", self._drift())
        self.assertEqual(r.kind, "ASK")
        blk = [b for b in DecisionLog.load(h.gh.comments(7)).blocks if b.get("status") == "pending-human"][-1]
        self.assertEqual((blk.get("kind"), blk.options()), ("drift", ["accept", "stop"]))
        self.assertIn("tester not started", r.line)

    def test_unattended_pauses_with_the_same_options(self):
        h = self._h(True)
        r = B.role_outcome(h.p, "test", "tester", self._drift())
        self.assertEqual(r.kind, "PAUSE")
        blk = [b for b in DecisionLog.load(h.gh.comments(7)).blocks if b.get("status") == "pending-human"][-1]
        self.assertEqual((blk.get("kind"), blk.options()), ("drift", ["accept", "stop"]))
        self.assertIn("guild:needs-human", h.labels())

    def test_accept_rebaselines_and_the_role_runs(self):
        h = self._h(False, roles=[role("DONE")])
        r = B.role_outcome(h.p, "test", "tester", self._drift())
        ASK.answer(h.decisions, h.writer, 7, r.qid, "accept")
        res = h.p.run_role(B.RoleCall("tester", "verify", "test", "T1"))
        self.assertEqual(res.status, "DONE")
        self.assertEqual(h.accepted, ["fp1"])
        applied = [b for b in DecisionLog.load(h.gh.comments(7)).blocks if b.get("point") == "applied"]
        self.assertEqual(len(applied), 1)
        h.p.__dict__.pop("_drift_read", None)
        self.assertIsNone(B.apply_drift_answer(h.p, "test"))                    # applied once

    def test_stop_holds_without_running_the_role(self):
        h = self._h(False)
        r = B.role_outcome(h.p, "test", "tester", self._drift())
        ASK.answer(h.decisions, h.writer, 7, r.qid, "stop")
        res = h.p.run_role(B.RoleCall("tester", "verify", "test", "T1"))
        self.assertEqual(h.calls["roles"], [])
        out = B.role_outcome(h.p, "test", "tester", res)
        self.assertEqual(out.kind, "PAUSE")
        self.assertIn("stopped by the human", out.cause)
        self.assertEqual(h.accepted, [])

    def test_gate_scripts_changed_is_still_a_stop(self):
        h = self._h(False)
        res = RoleResult("DRIFT", "x", violations=["gate scripts changed since export"], notes=["not run"])
        self.assertEqual(B.role_outcome(h.p, "test", "tester", res).kind, "FAIL")


# ---- 2. a recurring blocker: one automatic retry with the cause and a hint, then a person -------------------------

def _exarb():
    return decision("s", {"findings": [{"id": "F1", "verdict": "accept", "reason": "right", "evidence": []}],
                          "summary": "s"})


class StagnantRetry(unittest.TestCase):
    def test_the_developer_gets_one_more_attempt_before_a_person(self):
        tl = role("DONE")
        h = XHarness(self, roles=[dev(), tl, auditor([finding()]), dev(), tl, auditor([finding(line=4)]),
                                  dev(), tl, auditor([finding(line=5)])],
                     suites=[suite(FLUTTER_GREEN)] * 3, judges={"EX-ARB": [_exarb(), _exarb(), _exarb()],
                                                                "IDENT": decision("same", {"verdict": "same"})})
        r = X.run(h.p, "implement")
        self.assertEqual(r.kind, "PAUSE")
        self.assertTrue(r.cause.startswith("stagnant loop-back"))
        devs = [c for c in h.calls["roles"] if c.role == "developer"]
        self.assertEqual(len(devs), 3)
        self.assertIn("The same blocker came back", devs[2].inputs["retry.md"])
        self.assertIn("auditor BLOCKER lib/a.dart", devs[2].inputs["retry.md"])
        pts = [b.get("point") for b in DecisionLog.load(h.gh.comments(7)).blocks]
        self.assertEqual(pts.count("stagnant-retry"), 1)

    def test_the_baselines_hint_states_the_format(self):
        t = X.stagnant_hint("undeclared visual change: test/a/goldens/x.png")
        self.assertIn("`<A|M|D|C|P|P-withdrawn> <path> — <reason>`", t)
        self.assertIn("M test/a/goldens/x.png", t)

    def test_no_replayed_stage_calls_the_developer(self):
        # review-0102-5 m1 (0.102.6): `NEVER_REPLAYED` is gone — the developer is called only by stages that are never
        # replayed from a tape (`conservative.REPLAY_STAGES`); a new call site in a replayed stage fails here
        import re
        root = os.path.dirname(os.path.abspath(X.__file__))
        sites = []
        for f in sorted(os.listdir(root)):
            if not f.endswith(".py"):
                continue
            text = open(os.path.join(root, f), encoding="utf-8").read()
            if re.search(r'RoleCall\(\s*"developer"', text):
                sites.append(re.search(r'(?m)^STAGE = "([a-z]+)"', text).group(1))
        self.assertEqual(sorted(set(sites)), ["execute"])
        self.assertNotIn("execute", CONS.REPLAY_STAGES)
        self.assertFalse(hasattr(CONS, "NEVER_REPLAYED"))

    def test_a_resumed_execute_calls_the_developer_again(self):
        tl = role("DONE")
        h = XHarness(self, roles=[dev(), tl, auditor([finding()]), dev(), tl, auditor([finding(line=4)]),
                                  dev(), tl, auditor([finding(line=5)])],
                     suites=[suite(FLUTTER_GREEN)] * 3, judges={"EX-ARB": [_exarb()] * 4,
                                                                "IDENT": decision("same", {"verdict": "same"})})
        self.assertEqual(X.run(h.p, "implement").kind, "PAUSE")
        h.roles += [dev(), tl, auditor()]
        h.suites.append(suite(FLUTTER_GREEN))
        h.p.stage_start = "2026-11-16T01:00:00Z"                                # the next run after the answer
        h.issue()["labels"] = [{"name": "guild:execute"}]
        n0 = len([c for c in h.calls["roles"] if c.role == "developer"])
        r = X.run(h.p, "implement")
        self.assertEqual(len([c for c in h.calls["roles"] if c.role == "developer"]), n0 + 1)
        self.assertEqual(r.kind, "ADVANCE")


# ---- 3. a flaky suite --------------------------------------------------------------------------------------------

def _r(raw, passed, report=None):
    r = CheckResult(passed, 0 if passed else 1, False, raw, [], 60)
    r.report = report
    return r


def _report(fails):
    ev = [{"type": "suite", "suite": {"id": 0, "path": "/T/test/a_test.dart"}}]
    for i, (name, res) in enumerate(fails):
        ev += [{"type": "testStart", "test": {"id": i + 1, "name": name, "suiteID": 0}},
               {"type": "testDone", "testID": i + 1, "result": res, "hidden": False}]
    return "\n".join(json.dumps(e) for e in ev)


RED1 = "00:01 +5 -1: perf is fast [E]\n00:02 +9 -1: Some tests failed.\n"
ALONE_GREEN = "00:00 +0: perf is fast\n00:00 +1: All tests passed!\n"
ALONE_RED = "00:00 +0 -1: perf is fast [E]\n  Expected: <1>\n    Actual: <2>\n00:00 +0 -1: Some tests failed.\n"


class Flake(unittest.TestCase):
    def test_one_failing_test_green_alone_is_a_flake(self):
        ran = []
        note = FL.recheck(_r(RED1, False, _report([("perf is fast", "failure"), ("x", "success")])), ["flutter test"],
                          lambda c: ran.append(c) or _r(ALONE_GREEN, True),
                          lambda: ran.append("ALL") or _r(FLUTTER_GREEN, True), root="/T")
        self.assertTrue(note["green"] and note["full_rerun"])                 # 0.102.6 B1: always the whole suite
        self.assertEqual(note["tests"], ["perf is fast"])
        self.assertEqual(len(ran), 2)
        self.assertEqual(ran[1], "ALL")
        self.assertIn("test/a_test.dart", ran[0])
        self.assertIn("--name", ran[0])

    def test_a_deterministic_failure_stays_red(self):
        note = FL.recheck(_r(RED1, False, _report([("perf is fast", "failure")])), ["flutter test"],
                          lambda c: _r(ALONE_RED, False), root="/T")
        self.assertFalse(note["green"])

    def test_three_failures_or_a_compile_error_are_not_re_run(self):
        three = _report([("a", "failure"), ("b", "failure"), ("c", "error")])
        self.assertIsNone(FL.recheck(_r(RED1, False, three), ["flutter test"], lambda c: self.fail("ran")))
        self.assertIsNone(FL.recheck(_r("Compilation failed\n" + RED1, False, _report([("perf is fast", "failure")])),
                                     ["flutter test"], lambda c: self.fail("ran")))

    def test_a_fail_fast_suite_must_also_pass_whole(self):
        rep = _report([("perf is fast", "failure")])
        cmds = ["flutter test --fail-fast --concurrency=12"]
        note = FL.recheck(_r(RED1, False, rep), cmds, lambda c: _r(ALONE_GREEN, True), lambda: _r(RED1, False), root="/T")
        self.assertFalse(note["green"])
        note = FL.recheck(_r(RED1, False, rep), cmds, lambda c: _r(ALONE_GREEN, True),
                          lambda: _r(FLUTTER_GREEN, True), root="/T")
        self.assertTrue(note["green"] and note["full_rerun"])

    @unittest.skipUnless(os.path.exists(CH.SANDBOX_EXEC), "sandbox-exec only on macOS")
    def test_suite_in_tree_re_runs_in_the_same_tree(self):
        from workflows.dev import ports as PT
        py = os.path.realpath(sys.executable)
        flaky = ("import os, unittest\nclass T(unittest.TestCase):\n    def test_ok(self):\n        pass\n"
                 "    def test_flaky(self):\n        p = os.path.join(os.environ['TMPDIR'], 'n')\n"
                 "        n = int(open(p).read()) if os.path.exists(p) else 0\n        open(p, 'w').write(str(n + 1))\n"
                 "        self.assertGreater(n, 0)\n")
        stuck = "import unittest\nclass T(unittest.TestCase):\n    def test_red(self):\n        self.assertEqual(1, 2)\n"
        for text, green in ((flaky, True), (stuck, False)):
            with self.subTest(green=green):
                r = repo(self, {"test_x.py": text})
                run_dir = tmpdir(self)
                for d in ("in", "out", "tmp"):
                    os.makedirs(os.path.join(run_dir, d))
                res = PT.suite_in_tree(r, None, ["%s -m unittest -v test_x" % py], "tester", 120, run_dir,
                                       dict(os.environ), warm=False)
                self.assertFalse(res.passed)                                  # the first run is what it was
                self.assertEqual(bool(res.flake), green, res.raw[-400:])

    def test_the_test_stage_goes_on_green_with_a_flake_note(self):
        red = suite(RED1, passed=False, rc=1)
        red.flake = {"tests": ["perf is fast"], "reruns": [{"cmd": "x", "passed": True}], "full_rerun": True,
                     "green": True}
        h = Harness(self, fixture(), roles=[role("DONE", covers=[{"ac": "C1", "test": "test/a_test.dart::a"},
                                                                 {"ac": "C2", "test": "test/a_test.dart::b"}])],
                    suites=[red], judges={"TEST": judge_test(["C1", "C2"])},
                    checks=[suite(FLUTTER_GREEN)] * 4)
        h.write_file("test/a_test.dart", "void main(){ test('a', (){ expect(f(), 1); }); test('b', (){ expect(g(), 2); }); }\n")
        r = T.run(h.p)
        self.assertEqual(r.kind, "ADVANCE")
        blk = [b for b in DecisionLog.load(h.gh.comments(7)).blocks if b.get("point") == "flake"]
        self.assertEqual(len(blk), 1)
        self.assertIn("perf is fast", h.body_with("test:output"))

    def test_the_summary_line_is_the_runners_own(self):
        raw = ("00:05 +346 -1: perf is fast [E]\nPathNotFoundException: Deletion failed, path = '/x/flutter_test_1'\n"
               "00:06 +346 -1: Some tests failed.\n")
        line = T.summary_line(raw, CH.parse_summary(raw, "flutter"))
        self.assertTrue(line.startswith("00:06 +346 -1: Some tests failed."))
        self.assertIn("perf is fast", line)
        self.assertNotIn("PathNotFound", line)


# ---- 4. an `unsure` code check is recorded, never a verdict --------------------------------------------------------

class UnsureCheck(unittest.TestCase):
    def test_unsure_does_not_turn_all_effective_into_a_gap(self):
        h = Harness(self, fixture(), roles=[role("DONE", covers=[{"ac": "C1", "test": "test/a_test.dart::a", "kind": "new"},
                                                                 {"ac": "C2", "test": "test/a_test.dart::b", "kind": "new"}])],
                    suites=[suite(FLUTTER_GREEN)], judges={"TEST": judge_test(["C1", "C2"])},
                    base="main", impl_files=["lib/a.dart"])
        h.write_file("test/a_test.dart", "void main(){ test('a', (){ expect(f(), 1); }); test('b', (){ expect(g(), 2); }); }\n")
        orig = EFF.run
        EFF.run = lambda *a, **k: ({"C1": EFF.CheckOutcome("C1", "t", "unsure", "test still passes with the impl reverted"),
                                    "C2": EFF.CheckOutcome("C2", "t", "pass", "ok")}, {})
        self.addCleanup(setattr, EFF, "run", orig)
        r = T.run(h.p)
        self.assertEqual(r.kind, "ADVANCE")
        blk = [b for b in DecisionLog.load(h.gh.comments(7)).blocks if b.get("point") == "TEST"][-1]
        self.assertEqual(blk.get("choice"), "effective:C1,C2;uncovered:none")
        self.assertEqual(blk.get("check_unsure"), "C1")
        self.assertEqual(blk.get("grade"), "trigger")

    def test_a_static_fail_still_counts(self):
        h = Harness(self, fixture(), roles=[role("DONE", covers=[{"ac": "C1", "test": "test/a_test.dart::a"}]),
                                            role("DONE", covers=[])],
                    suites=[suite(FLUTTER_GREEN)], judges={"TEST": [judge_test(["C1", "C2"]), judge_test(["C1", "C2"])]})
        orig = EFF.run
        EFF.run = lambda *a, **k: ({"C1": EFF.CheckOutcome("C1", "t", "fail", "no assertion")}, {})
        self.addCleanup(setattr, EFF, "run", orig)
        h.p.unattended = False
        r = T.run(h.p)
        self.assertNotEqual(r.kind, "ADVANCE")


# ---- 5. the effectiveness check runs the real app tests ------------------------------------------------------------

GOLDEN_RAW = ("00:00 +0: x\n══╡ EXCEPTION CAUGHT BY FLUTTER TEST FRAMEWORK ╞══\nThe following assertion was thrown while running "
              "async test code:\nGolden \"goldens/a.png\": Pixel test failed, 0.64%, 2383px diff\ndetected.\n"
              "00:00 +0 -1: x [E]\n  Test failed. See exception logs above.\n00:00 +0 -1: Some tests failed.\n")
FILE_RAW = ("00:00 +0: loading t.dart\n00:00 +0: g first\n00:00 +1: g second\n"
            "══╡ EXCEPTION ╞══\nExpected: exactly one matching candidate\n  Actual: _TextWidgetFinder:<Found 0>\n"
            "00:00 +1 -1: g second [E]\n00:00 +1 -1: g third\n00:00 +2 -1: Some tests failed.\n")


class EffectiveRealTests(unittest.TestCase):
    def test_a_golden_diff_is_an_assertion(self):
        self.assertEqual(EFF.rerun_kind(GOLDEN_RAW, "flutter", "x", False), "assertion")
        missing = GOLDEN_RAW.replace("Pixel test failed, 0.64%, 2383px diff", "Could not be compared against non-existent file")
        self.assertEqual(EFF.rerun_kind(missing, "flutter", "x", False), "runtime")

    def test_a_test_read_inside_its_file(self):
        self.assertEqual(EFF.file_kind(FILE_RAW, "flutter", "g second", False), "assertion")
        self.assertEqual(EFF.file_kind(FILE_RAW, "flutter", "g first", False), "passed")
        self.assertEqual(EFF.file_kind(FILE_RAW, "flutter", "g fourth", False), "none_ran")
        self.assertEqual(EFF.file_kind("00:00 +0: g first\n", "flutter", "g first", False), "unknown")    # a crash
        self.assertEqual(EFF.file_command({}, "flutter", "test/a_test.dart"), "flutter test test/a_test.dart --no-pub")

    def test_agent_working_dirs_are_neither_copied_nor_blamed(self):
        r = repo(self, {"a.txt": "a\n", ".claude/settings.json": "{}\n", "docs/specs/1/a.md": "a\n",
                        ".gitignore": ".claude/.cc-writes/\n.claude/guild/memory/\ndocs/**/.claude/\nsecret/\n"})
        for rel in (".claude/.cc-writes/x", ".claude/guild/memory/m.md", "docs/specs/1/.claude/y", "secret/k"):
            _write(r, rel, "x\n")
        with EFF.TempTree(r, None, []) as tt:
            self.assertEqual(tt.skipped_ignored, ["secret/"])
            self.assertTrue(set([".claude/.cc-writes", "docs/specs/1/.claude"]) <= set(tt.tool_skipped))
            self.assertTrue(all(EFF.tool_path(x) for x in tt.tool_skipped))
            v = EFF._verdict_head("runtime", tt, "LateInitializationError: Local 'db' has not been initialized.\n")
            self.assertEqual(v[0], "unverified")
            self.assertNotIn("secret-required", v[1])
            self.assertIn("LateInitializationError", v[1])
            v = EFF._verdict_head("runtime", tt, "cannot open secret/k\n")
            self.assertIn("secret-required", v[1])

    def _p(self, root, outputs):
        class P(object):
            pass
        p = P()
        p.root = root
        p.read_file = lambda rel: open(os.path.join(root, rel)).read() if os.path.exists(os.path.join(root, rel)) else None
        p.ran = []

        def check(cmd, cwd, owner, timeout_s, write_dirs):
            p.ran.append(cmd)
            for key, raw, ok in outputs:
                if key(cmd, cwd):
                    return CheckResult(ok, 0 if ok else 1, False, raw, [], 60)
            raise AssertionError("unexpected check %s" % cmd)
        p.check = check
        p.warm = None
        return p

    def _repo(self):
        r = repo(self, {"lib/a.dart": "String label() => 'en';\n",
                        "test/a_test.dart": "void main(){ group('g', (){ test('ko', (){ expect(label(), 'ko'); });"
                                            " test('en', (){ expect(label(), 'en'); }); }); }\n"})
        git(r, "switch", "-q", "-c", "fix")
        _write(r, "lib/a.dart", "String label() => 'ko';\n")
        git(r, "commit", "-qam", "impl")
        return r

    def test_an_acs_cited_tests_must_each_react(self):
        # 0.102.6 (review-0102-5 M4 a): `en` still passes with the impl reverted — the AC is `unsure` naming it (and
        # that `ko` reacted); 0.102.5 called it `pass`. An unsure check never changes the verdict: graded after
        r = self._repo()

        def reverted(cwd):
            return "'en'" in open(os.path.join(cwd, "lib/a.dart")).read()
        ok = "00:00 +0: g {n}\n00:00 +1: All tests passed!\n"
        bad = "00:00 +0 -1: g ko [E]\n  Expected: 'ko'\n    Actual: 'en'\n00:00 +0 -1: Some tests failed.\n"
        p = self._p(r, [(lambda c, cwd: "'(^| )g ko$'" in c and reverted(cwd), bad, False),
                        (lambda c, cwd: "g ko" in c, ok.format(n="ko"), True),
                        (lambda c, cwd: "g en" in c, ok.format(n="en"), True)])
        cfg = {"commands": {"test": "flutter test"}}
        covers = {"AC #1": [{"kind": "new", "test": "test/a_test.dart::g en"}, {"kind": "new", "test": "test/a_test.dart::g ko"}]}
        out, _meta = EFF.run(p, cfg, ["AC #1"], covers, "main", ["lib/a.dart"])
        self.assertEqual(out["AC #1"].result, "unsure", out["AC #1"].why)
        self.assertEqual(out["AC #1"].test, "test/a_test.dart::g en")
        self.assertIn("reacted: test/a_test.dart::g ko", out["AC #1"].why)

    def test_a_test_that_fails_alone_runs_in_its_file(self):
        r = self._repo()

        def reverted(cwd):
            return "'en'" in open(os.path.join(cwd, "lib/a.dart")).read()
        alone = "00:00 +0: g ko\nLateInitializationError: Local 'db' has not been initialized.\n00:00 +0 -1: g ko [E]\n" \
                "00:00 +0 -1: Some tests failed.\n"
        file_ok = "00:00 +0: g ko\n00:00 +1: g en\n00:00 +2: All tests passed!\n"
        file_red = "00:00 +0: g ko\n  Expected: 'ko'\n    Actual: 'en'\n00:00 +0 -1: g ko [E]\n00:00 +0 -1: g en\n" \
                   "00:00 +1 -1: Some tests failed.\n"
        p = self._p(r, [(lambda c, cwd: "--name" in c, alone, False),
                        (lambda c, cwd: reverted(cwd), file_red, False),
                        (lambda c, cwd: True, file_ok, True)])
        cfg = {"commands": {"test": "flutter test"}}
        out, _meta = EFF.run(p, cfg, ["AC #1"], {"AC #1": [{"kind": "new", "test": "test/a_test.dart::g ko"}]}, "main",
                             ["lib/a.dart"])
        self.assertEqual(out["AC #1"].result, "pass", out["AC #1"].why)
        self.assertEqual(sum(1 for c in p.ran if "--name" not in c), 2)          # HEAD and the revert, whole file


# ---- 6. a remote ref deleted elsewhere is no violation -------------------------------------------------------------

class RemoteDeletion(unittest.TestCase):
    def _snap(self, remote, refs):
        return {"status": {}, "head": "h", "symref": "refs/heads/fix/1", "refs": {}, "integrity": {},
                "remote_url": "u", "remote": dict(refs)}

    def test_a_merged_prs_branch_vanishing_is_a_warning_only(self):
        wt = repo(self)
        git(wt, "switch", "-q", "-c", "fix/1")
        h = git(wt, "rev-parse", "HEAD")
        b = SC.snapshot(wt)
        a = SC.snapshot(wt)
        b["remote_url"] = a["remote_url"] = "u"
        # 0.102.6 (M3): the deleted branch is still a pull request's head on the remote (`refs/pull/1962/head`)
        b["remote"] = {"refs/heads/feature/#1956-x": "f" * 40, "refs/pull/1962/merge": "e" * 40,
                       "refs/pull/1962/head": "f" * 40, "refs/heads/fix/1": h}
        a["remote"] = {"refs/heads/fix/1": h, "refs/pull/1962/head": "f" * 40}
        v = SC.check(wt, b, a, ["tester"], branch="fix/1")
        self.assertEqual([x for x in v if "remote" in x], [])
        self.assertEqual(len(SC.remote_warnings(b, a)), 2)
        a["remote"] = {"refs/pull/1962/head": "f" * 40}
        self.assertIn("remote refs/heads/fix/1 deleted during the role", SC.check(wt, b, a, ["tester"], branch="fix/1"))

    def test_a_remote_move_to_a_commit_a_remote_already_had_is_not_a_push(self):
        wt = repo(self)
        base = git(wt, "rev-parse", "HEAD")
        git(wt, "update-ref", "refs/remotes/origin/main", base)
        git(wt, "switch", "-q", "-c", "fix/1")
        b = SC.snapshot(wt)
        a = SC.snapshot(wt)
        b["remote_url"] = a["remote_url"] = "u"
        b["remote"], a["remote"] = {"refs/pull/9/merge": "e" * 40}, {"refs/pull/9/merge": base}
        self.assertEqual([x for x in SC.check(wt, b, a, ["tester"], branch="fix/1") if "remote" in x], [])
        _write(wt, "x.txt", "x\n")
        git(wt, "add", "-A")
        git(wt, "commit", "-qm", "local only")
        own = git(wt, "rev-parse", "HEAD")
        a = SC.snapshot(wt)
        a["remote_url"], a["remote"] = "u", {"refs/heads/fix/1": own}
        self.assertTrue(any("push" in x for x in SC.check(wt, b, a, ["developer"], branch="fix/1")))


# ---- 7. unverified groups run and are graded after -----------------------------------------------------------------

class UnverifiedPostHoc(unittest.TestCase):
    def _h(self, unattended=True):
        h = Harness(self, fixture(), roles=[role("DONE", covers=[{"ac": "C1", "test": "test/a_test.dart::a"},
                                                                 {"ac": "C2", "test": "test/a_test.dart::b"}])],
                    suites=[suite(FLUTTER_GREEN)], judges={"TEST": judge_test(["C1", "C2"])},
                    checks=[suite(FLUTTER_GREEN)] * 4, unattended=unattended)
        h.write_file("test/a_test.dart", "void main(){ test('a', (){ expect(f(), 1); }); test('b', (){ expect(g(), 2); }); }\n")
        return h

    def test_an_unverified_group_runs_the_judges_decision_without_a_question(self):
        for unattended in (True, False):
            with self.subTest(unattended=unattended):
                h = self._h(unattended)
                h.p.unverified = frozenset(["TEST"])
                r = CONS.guarded(h.p, "test", lambda: T.run(h.p))
                self.assertEqual(r.kind, "ADVANCE")
                blocks = DecisionLog.load(h.gh.comments(7)).blocks
                self.assertEqual([b for b in blocks if b.get("status") == "pending-human"], [])
                tb = [b for b in blocks if b.get("point") == "TEST"][-1]
                self.assertEqual(tb.get("post_hoc"), "unverified TEST")
                self.assertEqual(tb.get("by"), "judge:sonnet")

    def test_a_valve_still_asks(self):
        h = self._h(True)
        h.p.valves = {"group.TEST.conservative": True}
        r = CONS.guarded(h.p, "test", lambda: T.run(h.p))
        self.assertEqual(r.kind, "PAUSE")

    def test_an_irreversible_or_security_decision_still_asks(self):
        class S(object):
            group = point = "STAKES"
            brief_parts = [("irreversible", "supabase/migrations")]
        p = type("P", (), {})()
        p.valves, p.unverified = {}, frozenset(["STAKES"])
        self.assertFalse(CONS.posthoc(p, "STAKES", S(), irreversible=True))
        S.brief_parts = [("question", "security: token stored in plain text")]     # 0.102.6 B2: the real part
        self.assertFalse(CONS.posthoc(p, "STAKES", S()))
        S.brief_parts = []
        self.assertTrue(CONS.posthoc(p, "STAKES", S()))
        p.valves = {"group.STAKES.conservative": True}
        self.assertFalse(CONS.posthoc(p, "STAKES", S()))

    def test_post_hoc_rows_count_and_a_wrong_sets_the_valve(self):
        h = self._h(True)
        h.p.unverified = frozenset(["TEST"])
        CONS.guarded(h.p, "test", lambda: T.run(h.p))
        blocks = DecisionLog.load(h.gh.comments(7)).blocks
        rows = G.posthoc_rows(blocks, 7)
        self.assertEqual([(r["group"], r["mode"]) for r in rows], [("TEST", "post-hoc")])
        self.assertTrue(UV.counts(dict(rows[0], given_info="ok"), "human"))
        common = tmpdir(self)
        os.makedirs(os.path.join(common, "guild", "engine"))
        res = G.apply_judgments(common, [dict(rows[0], given_info="wrong")], "o/r", "human", candidates=rows)
        self.assertEqual(res["conservative"], ["TEST"])
        st = G.load_state(common)
        self.assertEqual(st["unverified"]["TEST"]["wrong"], 1)
        self.assertEqual(st["unverified"]["TEST"]["open"], [])

    def test_select_leaves_post_hoc_blocks_to_their_own_row(self):
        h = self._h(True)
        h.p.unverified = frozenset(["TEST"])
        CONS.guarded(h.p, "test", lambda: T.run(h.p))
        blocks = DecisionLog.load(h.gh.comments(7)).blocks
        sel = G.select({7: blocks}, "o/r", True, 1.0, lambda i, b: None)
        self.assertFalse([b for _i, b, _w in sel if b.get("post_hoc")])


if __name__ == "__main__":
    unittest.main()
