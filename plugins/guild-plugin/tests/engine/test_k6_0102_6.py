"""0.102.6 — the fixes of the post-release review of 0.102.5 (review-0102-5: B1 B2, M1–M5, m1–m4; k6-notes "0.102.6").
The reviewer's repros (scratchpad r0102_5/) live here, each through the engine's real code paths:

B1  a flake needs, besides the failing tests green alone, ONE green re-run of the whole suite (every command); pytest
    ERROR rows and flutter hidden-test failures count; an order-dependent failure stays red;
B2  the security exception is reached from the real briefs (DE-ARB over the security role, the STAKES after it, QA with
    a reported security issue, EX-ARB with the security role's finding) — a table over the real call sites;
M1  a base merge is accepted only against the base the engine vouches for (recorded before the Issue's first role, or
    the remote's tip read by the engine), and only when the merge is git's own clean merge keeping the branch's work;
M2  a person's drift `accept` applies only to the drift the question showed (its fingerprint), re-checked at resume;
M3  a force-push rewinding a remote branch and the deletion of a remote branch that is no pull request's head are
    violations again (0.102.4), a merged PR's branch deleted by GitHub is not;
M4  each cited test of an AC must react; the whole-file fallback matches a test's full name exactly;
M5  `check_unsure` / `grade: trigger` blocks and the code's flake notes are grading-sheet rows (a wrong flake → valve);
m1  `NEVER_REPLAYED` removed (test_k6_0102_5 pins that no replayed stage calls the developer); m2 a plain Dart test's
    expectation after its `[E]` line is an assertion; m3 an irreversible KICKOFF says so on its block (the centre pauses
    it); m4 the stagnation retry's hint survives a crash-resume."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import _util  # noqa: F401
from _k1 import Clock, FakeSpawn, RecJournal, git, repo, stream_lines, tmpdir
from _k2 import FLUTTER_GREEN, Harness, decision, fixture, judge_test, role, suite
from _k3 import XHarness, auditor, dev, finding
from _k4 import K4, evidence, kickoff

from guildcore import ask as ASK
from guildcore import checks as CH
from guildcore.checks import CheckResult
from guildcore.decisions import DecisionLog
from guildcore.roles import runner as RR
from guildcore.roles import scope as SC
from guildcore.roles.runner import RoleResult
from workflows.dev import arbitration as ARB
from workflows.dev import centre as CEN
from workflows.dev import conservative as CONS
from workflows.dev import effective as EFF
from workflows.dev import flake as FL
from workflows.dev import grade as G
from workflows.dev.stages import analyze as A
from workflows.dev.stages import base as B
from workflows.dev.stages import execute as X
from workflows.dev.stages import qa as Q
from workflows.dev.stages import test as T

DONE = ">>> RESULT <<<\nDONE: ok"


def _w(d, rel, t):
    p = os.path.join(d, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as fh:
        fh.write(t)


def _blocks(h):
    return DecisionLog.load(h.gh.comments(7)).blocks


class EvJournal(RecJournal):
    def __init__(self):
        RecJournal.__init__(self)
        self.events = []

    def append(self, kind, **f):
        self.events.append(dict(f, kind=kind))


# ---- B1 the flake rule ---------------------------------------------------------------------------------------------

class R(object):
    def __init__(self, passed, raw, timed_out=False, report=None):
        self.passed, self.raw, self.timed_out, self.report = passed, raw, timed_out, report


UNITTEST_OK = "test_a (t.T.test_a) ... ok\n\n----------------------------------------------------------------------\n" \
              "Ran 1 test in 0.001s\n\nOK\n"


class B1Flake(unittest.TestCase):
    def test_a_second_command_that_never_ran_is_not_masked(self):
        # commands.test = [unit tests, a coverage verifier]; run_command stopped at the first red command
        cmds = ["python3 -m unittest discover -v", "scripts/verify_coverage.sh"]
        raw = ("test_a (t.T.test_a) ... FAIL\n\n======================================================================\n"
               "FAIL: test_a (t.T.test_a)\n----------------------------------------------------------------------\n"
               "AssertionError: 1 != 2\n\nRan 40 tests in 0.1s\n\nFAILED (failures=1)\n")
        ran = []
        note = FL.recheck(R(False, raw), cmds, lambda c: (ran.append(c), R(True, UNITTEST_OK))[1],
                          lambda: (ran.append("ALL"), R(False, "verify_coverage: AC #3 has no test\n"))[1])
        self.assertFalse(note and note.get("green"), "green although %s never ran (%s)" % (cmds[1], ran))
        self.assertEqual(ran[-1], "ALL")                       # the whole suite ran — every command

    def test_pytest_setup_errors_are_not_masked(self):
        cmds = ["python3 -m pytest -q"]
        raw = ("FAILED tests/test_x.py::test_flaky - assert 0\n"
               "ERROR tests/test_y.py::test_one - RuntimeError: db fixture broken\n"
               "ERROR tests/test_y.py::test_two - RuntimeError: db fixture broken\n"
               "ERROR tests/test_y.py::test_three - RuntimeError: db fixture broken\n"
               "========= 1 failed, 50 passed, 3 errors in 2.0s =========\n")
        ok = "tests/test_x.py::test_flaky PASSED\n========= 1 passed in 0.1s =========\n"
        note = FL.recheck(R(False, raw), cmds, lambda c: R(True, ok), lambda: R(False, raw))
        self.assertFalse(note and note.get("green"), "green with 3 deterministic setup ERRORs: %s" % note)
        self.assertIsNone(note)                                # 4 failures named: over the limit, never re-run

    def test_an_error_row_is_a_named_failure(self):
        raw = "ERROR tests/test_y.py::test_one - RuntimeError: x\n========= 50 passed, 1 error in 2.0s =========\n"
        self.assertEqual(FL.failing(R(False, raw), "pytest"), [("tests/test_y.py", "test_one")])

    def test_a_failure_the_names_miss_is_not_eligible(self):
        # the summary counts 3 (failures=1, errors=2) but one test is named — a failure the rule cannot see
        raw = ("FAIL: test_a (t.T.test_a)\nAssertionError\n\nRan 9 tests in 0.1s\n\nFAILED (failures=1, errors=2)\n")
        self.assertIsNone(FL.recheck(R(False, raw), ["python3 -m unittest"], lambda c: self.fail("ran"),
                                     lambda: self.fail("ran")))

    def test_a_flutter_hidden_setup_failure_is_not_eligible(self):
        ev = [{"type": "suite", "suite": {"id": 0, "path": "/T/test/a_test.dart"}},
              {"type": "testStart", "test": {"id": 1, "name": "perf", "suiteID": 0}},
              {"type": "testDone", "testID": 1, "result": "failure", "hidden": False},
              {"type": "testStart", "test": {"id": 2, "name": "(setUpAll)", "suiteID": 0}},
              {"type": "testDone", "testID": 2, "result": "error", "hidden": True}]
        rep = "\n".join(json.dumps(e) for e in ev)
        raw = "00:01 +5 -1: perf [E]\n00:02 +9 -1: Some tests failed.\n"
        self.assertIsNone(FL.recheck(R(False, raw, report=rep), ["flutter test"], lambda c: self.fail("ran"),
                                     lambda: self.fail("ran"), root="/T"))

    def test_without_a_whole_suite_re_run_it_is_never_green(self):
        raw = "00:01 +5 -1: perf [E]\n00:02 +9 -1: Some tests failed.\n"
        rep = "\n".join(json.dumps(e) for e in [
            {"type": "suite", "suite": {"id": 0, "path": "/T/test/a_test.dart"}},
            {"type": "testStart", "test": {"id": 1, "name": "perf", "suiteID": 0}},
            {"type": "testDone", "testID": 1, "result": "failure", "hidden": False}])
        alone = "00:00 +0: perf\n00:00 +1: All tests passed!\n"
        note = FL.recheck(R(False, raw, report=rep), ["flutter test"], lambda c: R(True, alone), None, root="/T")
        self.assertFalse(note["green"])

    def test_a_deterministic_order_dependent_failure_is_not_a_flake(self):
        d = tempfile.mkdtemp(prefix="r0102-6-")
        self.addCleanup(shutil.rmtree, d, True)
        with open(os.path.join(d, "test_state.py"), "w") as fh:
            fh.write("import unittest\nSTATE = []\n\n"
                     "class T(unittest.TestCase):\n"
                     "    def test_1_writer(self):\n        STATE.append(1)\n\n"
                     "    def test_2_reader(self):\n        self.assertEqual(STATE, [])\n")
        cmds = ["%s -m unittest discover -v -p 'test_*.py'" % sys.executable]

        def run(c):
            return CH.run_command([c], 60, cwd=d)
        r = run(cmds[0])
        self.assertFalse(r.passed)
        for _ in range(3):
            self.assertFalse(run(cmds[0]).passed)                # red every time in the suite
        note = FL.recheck(r, cmds, run, lambda: CH.run_command(list(cmds), 60, cwd=d), root=d)
        self.assertTrue(note["reruns"] and note["reruns"][0]["passed"])     # green alone …
        self.assertFalse(note["green"])                                    # … red in the suite: not a flake

    @unittest.skipUnless(os.path.exists(CH.SANDBOX_EXEC), "sandbox-exec only on macOS")
    def test_suite_in_tree_runs_every_command_again(self):
        from workflows.dev import ports as PT
        py = os.path.realpath(sys.executable)
        flaky = ("import os, unittest\nclass T(unittest.TestCase):\n    def test_ok(self):\n        pass\n"
                 "    def test_flaky(self):\n        p = os.path.join(os.environ['TMPDIR'], 'n')\n"
                 "        n = int(open(p).read()) if os.path.exists(p) else 0\n        open(p, 'w').write(str(n + 1))\n"
                 "        self.assertGreater(n, 0)\n")
        for second, green in (("%s -c 'import sys; sys.exit(0)'" % py, True),
                              ("%s -c 'import sys; print(\"coverage: AC 3 has no test\"); sys.exit(1)'" % py, False)):
            with self.subTest(green=green):
                r = repo(self, {"test_x.py": flaky})
                run_dir = tmpdir(self)
                for d in ("in", "out", "tmp"):
                    os.makedirs(os.path.join(run_dir, d))
                res = PT.suite_in_tree(r, None, ["%s -m unittest -v test_x" % py, second], "tester", 120, run_dir,
                                       dict(os.environ), warm=False)
                self.assertFalse(res.passed)
                self.assertEqual(bool(res.flake), green, (res.raw[-400:], getattr(res, "flake_tried", None)))
                self.assertTrue(res.flake_tried["full_rerun"])

    def test_a_wrong_flake_verdict_turns_the_rule_off(self):
        red = suite("00:01 +5 -1: perf is fast [E]\n00:02 +9 -1: Some tests failed.\n", passed=False, rc=1)
        red.flake = {"tests": ["perf is fast"], "reruns": [{"cmd": "x", "passed": True}], "full_rerun": True,
                     "green": True}
        for valve, adv in ((False, True), (True, False)):
            with self.subTest(valve=valve):
                h = Harness(self, fixture(), roles=[role("DONE", covers=[{"ac": "C1", "test": "test/a_test.dart::a"},
                                                                         {"ac": "C2", "test": "test/a_test.dart::b"}])] * 3,
                            suites=[red], judges={"TEST": judge_test(["C1", "C2"])}, checks=[suite(FLUTTER_GREEN)] * 4)
                h.write_file("test/a_test.dart",
                             "void main(){ test('a', (){ expect(f(), 1); }); test('b', (){ expect(g(), 2); }); }\n")
                if valve:
                    h.p.valves = {FL.VALVE: True}
                r = T.run(h.p)
                self.assertEqual(r.kind == "ADVANCE", adv, r.kind)
                self.assertEqual(bool([b for b in _blocks(h) if b.get("point") == "flake"]), adv)


# ---- B2 security decisions still ask -------------------------------------------------------------------------------

class P(object):
    valves = {}
    unverified = frozenset(["DE-ARB", "QA", "STAKES", "EX-ARB-dismiss"])


class S(object):
    def __init__(self, group, parts, point=None):
        self.group, self.brief_parts, self.point = group, parts, point or group


SEC_LINE = "storing the refresh token in SharedPreferences leaks it — use the keychain"
QA_SEC = "QA report:\nRESULT: DONE_WITH_CONCERNS\n{\"human_items\": [\"API key is logged in plain text (security)\"]}"


class B2Security(unittest.TestCase):
    def test_de_arb_over_a_blocked_security_role_still_asks(self):
        spec = S("DE-ARB", [("role", "security returned BLOCKED"), ("line", SEC_LINE)])
        self.assertFalse(CONS.posthoc(P(), "DE-ARB", spec))

    def test_qa_pass_over_a_security_finding_still_asks(self):
        self.assertFalse(CONS.posthoc(P(), "QA", S("QA", [("qa", QA_SEC), ("bar", "-")])))

    def _captured(self, group, build):
        """The spec the REAL call site builds (a judge that records it)."""
        seen = []

        def judge(spec):
            seen.append(spec)
            return decision(CONS.JG.UNSURE.get(group) or "pause", {})
        try:
            build(judge)
        except Exception:                                    # noqa: BLE001 — only the brief is read here
            pass
        self.assertTrue(seen, group)
        return seen[-1]

    def _dearb(self, role_name, line):
        def build(judge):
            h = Harness(self, fixture(labels=("guild:design",)), judges={"DE-ARB": judge, "STAKES": judge})
            ARB.blocked(h.p, "design", role_name, RoleResult("BLOCKED", line), [("analysis", "{}")], set(),
                        lambda add: RoleResult("DONE"))
        return self._captured("DE-ARB", build)

    def _stakes(self, role_name, line):
        def build(judge):
            h = Harness(self, fixture(labels=("guild:design",)), judges={"STAKES": judge})
            ARB.stakes(h.p, "design", "J-DE-03", "%s: %s" % (role_name, line), [], "keep the token as is", "body",
                       [], [], "E2.1")
        return self._captured("STAKES", build)

    def _qa(self, items):
        def build(judge):
            from test_k2_qa_stage import qa_harness
            h = qa_harness(self, judges={"QA": judge})
            qres = RoleResult("DONE_WITH_CONCERNS", "concerns", {"human_items": list(items)})
            Q._judge(h.p, {}, qres, None, None, "Issue body", ["lib/a.dart"])
        return self._captured("QA", build)

    def _exarb(self, triggers, findings):
        def build(judge):
            h = XHarness(self, judges={"EX-ARB": judge})
            cx = type("Cx", (), {})()
            X.ex_arb(h.p, cx, [("F1", f) for f in findings], None, list(triggers), [])
        return self._captured("EX-ARB", build)

    def test_the_real_call_sites_table(self):
        from workflows.dev import exec_audit as XA
        sec_f = XA.Cur("BLOCKER", "spec", "lib/a.dart", 1, "the API key is written to the log in plain text")
        plain_f = XA.Cur("MAJOR", "spec", "lib/a.dart", 2, "the counter label is misaligned")
        rows = [
            ("DE-ARB security role", lambda: self._dearb("security", "which module?"), True),
            ("DE-ARB security issue named by another role", lambda: self._dearb("tech-lead", SEC_LINE), True),
            ("DE-ARB plain", lambda: self._dearb("tech-lead", "which module?"), False),
            ("DE-ARB a role named security-ish", lambda: self._dearb("security-reviewer", "which module?"), False),
            ("STAKES after the security role", lambda: self._stakes("security", "which module?"), True),
            ("STAKES plain", lambda: self._stakes("tech-lead", "which module?"), False),
            ("QA security issue", lambda: self._qa(["API key is logged in plain text (security)"]), True),
            ("QA plain", lambda: self._qa(["실기기 확인 — iPhone"]), False),
            ("EX-ARB security role BLOCKED", lambda: self._exarb([("security", "BLOCKED", "token in a log")], []), True),
            ("EX-ARB security finding", lambda: self._exarb([], [sec_f]), True),
            ("EX-ARB plain", lambda: self._exarb([("tech-lead", "BLOCKED", "naming")], [plain_f]), False),
        ]
        for name, make, want in rows:
            with self.subTest(case=name):
                spec = make()
                self.assertEqual(CONS.security(spec), want, spec.brief_parts)
                if spec.group in CONS.GATED:
                    self.assertEqual(CONS.posthoc(P(), spec.group, spec), not want)

    def test_every_table_part_is_a_part_a_call_site_builds(self):
        names = {"DE-ARB": [n for n, _t in self._dearb("security", "x").brief_parts],
                 "STAKES": [n for n, _t in self._stakes("security", "x").brief_parts],
                 "QA": [n for n, _t in self._qa(["x"]).brief_parts],
                 "EX-ARB": [n for n, _t in self._exarb([], []).brief_parts]}
        for g, want in CONS.SECURITY_INPUTS.items():
            for part in want["role"] + want["text"]:
                with self.subTest(group=g, part=part):
                    self.assertIn(part, names[g])

    def test_a_blocked_security_role_asks_through_the_gate(self):
        # the real DE-ARB call site + the gate: an unverified DE-ARB `decide` over the security role is asked (a pause,
        # unattended); over another role it runs post-hoc
        for role_name, asks in (("security", True), ("designer", False)):
            with self.subTest(role=role_name):
                h = Harness(self, fixture(labels=("guild:design",)),
                            judges={"DE-ARB": decision("decide", {"action": "decide", "assumption": "keep it"}),
                                    "STAKES": decision("low", {"level": "low", "local_reversible_reason": "a revert"})})
                h.p.unverified = frozenset(["DE-ARB", "STAKES"])

                def go():
                    return ARB.blocked(h.p, "design", role_name, RoleResult("BLOCKED", "which store?"), [], set(),
                                       lambda add: RoleResult("DONE"))
                if asks:
                    with self.assertRaises(CONS.Ask):                   # the gate asks (the FSM: ask / pause)
                        go()
                    self.assertEqual(CONS.guarded(h.p, "design", go).kind, "PAUSE")
                    self.assertTrue([b for b in _blocks(h) if b.get("status") == "pending-human"])
                else:
                    self.assertEqual(go(), ("decided", "keep it"))
                    self.assertTrue([b for b in _blocks(h) if b.get("post_hoc")])

    def test_an_unverified_ex_arb_never_dismisses_a_security_finding(self):
        from workflows.dev import firstsprint as FS
        p = type("P", (), {})()
        p.valves, p.unverified = {}, frozenset(["EX-ARB-dismiss"])
        p.engine_cfg = lambda k, d=None: d
        self.assertEqual(FS.no_dismiss(p, attended=True), "conservative")


# ---- M1 base merges ------------------------------------------------------------------------------------------------

class M1BaseMerge(unittest.TestCase):
    def setUp(self):
        self.main = repo(self, {"a.txt": "a\n", "lib/core.txt": "real\n"})
        self.wt = os.path.join(tmpdir(self), "wt")
        git(self.main, "worktree", "add", "-q", "-b", "fix/1", self.wt)
        _w(self.wt, "test/issue_test.txt", "the tester's failing test\n")
        git(self.wt, "add", "-A")
        git(self.wt, "commit", "-qm", "work")
        self.base = SC.snapshot(self.wt)

    def _origin(self):
        origin = os.path.join(tmpdir(self), "origin.git")
        git(self.main, "clone", "-q", "--bare", self.main, origin)
        git(self.main, "remote", "add", "origin", origin)
        git(self.main, "fetch", "-q", "origin")
        return origin

    def _forge_local_main(self):
        main_tip = git(self.wt, "rev-parse", "main")
        b = subprocess.run(["git", "hash-object", "-w", "--stdin"], cwd=self.wt, input=b"tampered\n",
                           stdout=subprocess.PIPE).stdout.decode().strip()
        env = dict(os.environ, GIT_INDEX_FILE=os.path.join(tmpdir(self), "idx"))
        subprocess.run(["git", "read-tree", main_tip], cwd=self.wt, env=env, check=True)
        subprocess.run(["git", "update-index", "--cacheinfo", "100644,%s,lib/core.txt" % b], cwd=self.wt, env=env,
                       check=True)
        t = subprocess.run(["git", "write-tree"], cwd=self.wt, env=env, stdout=subprocess.PIPE).stdout.decode().strip()
        forged = git(self.wt, "commit-tree", t, "-p", main_tip, "-m", "chore")
        git(self.wt, "update-ref", "refs/heads/main", forged)
        return forged

    def test_forged_local_base_commit_is_not_a_base_merge(self):
        self._origin()
        self._forge_local_main()
        git(self.wt, "merge", "-q", "--no-edit", "main")
        self.assertEqual(open(os.path.join(self.wt, "lib/core.txt")).read(), "tampered\n")
        for base in ("origin/main", "main"):
            with self.subTest(base=base):
                self.assertIsNone(SC.accept_base_merge(self.wt, self.base, SC.snapshot(self.wt), "fix/1", base))

    def test_merge_deleting_the_branchs_own_test_is_not_a_base_merge(self):
        self._origin()
        _w(self.main, "a.txt", "a2\n")
        git(self.main, "commit", "-qam", "main moves")
        git(self.main, "push", "-q", "origin", "main")
        git(self.wt, "fetch", "-q", "origin")
        git(self.wt, "merge", "-q", "--no-commit", "--no-ff", "origin/main")
        git(self.wt, "rm", "-q", "test/issue_test.txt")
        git(self.wt, "commit", "-qm", "Merge branch 'main'")
        self.assertIsNone(SC.accept_base_merge(self.wt, self.base, SC.snapshot(self.wt), "fix/1", "origin/main"))

    def test_reverting_branch_work_in_a_merge_is_not_a_base_merge(self):
        self._origin()
        _w(self.wt, "lib/core.txt", "fixed\n")
        git(self.wt, "commit", "-qam", "fix")
        base = SC.snapshot(self.wt)
        _w(self.main, "a.txt", "a2\n")
        git(self.main, "commit", "-qam", "main moves")
        git(self.main, "push", "-q", "origin", "main")
        git(self.wt, "fetch", "-q", "origin")
        git(self.wt, "merge", "-q", "--no-commit", "--no-ff", "origin/main")
        git(self.wt, "checkout", "origin/main", "--", "lib/core.txt")
        git(self.wt, "commit", "-qm", "Merge branch 'main'")
        self.assertIsNone(SC.accept_base_merge(self.wt, base, SC.snapshot(self.wt), "fix/1", "origin/main"))

    def test_a_clean_merge_of_the_remote_base_keeps_working(self):
        self._origin()
        _w(self.wt, "lib/core.txt", "fixed\n")
        git(self.wt, "commit", "-qam", "fix")
        base = SC.snapshot(self.wt)
        _w(self.main, "a.txt", "a2\n")
        git(self.main, "commit", "-qam", "main moves")
        git(self.main, "push", "-q", "origin", "main")
        git(self.wt, "fetch", "-q", "origin")
        git(self.wt, "merge", "-q", "--no-edit", "origin/main")
        got = SC.accept_base_merge(self.wt, base, SC.snapshot(self.wt), "fix/1", "origin/main")
        self.assertEqual(got, [git(self.wt, "rev-parse", "HEAD")])

    def test_a_tester_planting_lib_code_on_local_main_is_caught_somewhere(self):
        self._origin()
        before = SC.snapshot(self.wt)
        self._forge_local_main()
        v = SC.check(self.wt, before, SC.snapshot(self.wt), ["tester"], branch="fix/1")
        git(self.wt, "merge", "-q", "--no-edit", "main")
        got = SC.accept_base_merge(self.wt, self.base, SC.snapshot(self.wt), "fix/1", "main")
        self.assertTrue(v or got is None, (v, got))

    def test_without_a_remote_only_the_tips_recorded_before_the_first_role_count(self):
        # no remote: the runner records the base before the Issue's first role — a later merge of a NEWER local base
        # (or a forged one) is a person's to accept; a merge of the recorded base is accepted
        j = EvJournal()
        r = RR.Runner(journal=j, parent_env={"PATH": os.environ["PATH"]},
                      spawn=FakeSpawn([{"stream": stream_lines(texts=[DONE])}] * 3),
                      user_settings=os.path.join(tmpdir(self), "u"), run_root_dir=os.path.join(tmpdir(self), "runs"),
                      claude="claude", clock=Clock())
        _w(self.main, "a.txt", "a2\n")
        git(self.main, "commit", "-qam", "main moves before the run")
        recorded = git(self.main, "rev-parse", "main")

        def spec(role_name="developer", task="implement"):
            return RR.RoleSpec(role_name, task, "t", issue=1, stage="s", step="x", worktree=self.wt, model="sonnet",
                               base="main", branch="fix/1", remote_check=False)
        self.assertEqual(r.run_role(spec()).status, "DONE")
        self.assertEqual(r._get_baseline(self.wt, 1)["base_tips"], [recorded])
        git(self.wt, "merge", "-q", "--no-edit", "main")
        self.assertEqual(r.drift_check(self.wt, 1, "fix/1", "main"), [])        # the recorded base: accepted
        self.assertEqual(r._get_baseline(self.wt, 1)["base_tips"], [recorded])  # carried, never re-read
        self._forge_local_main()
        git(self.wt, "merge", "-q", "--no-edit", "main")
        self.assertNotEqual(r.drift_check(self.wt, 1, "fix/1", "main"), [])     # forged after the record: asked


# ---- M2 drift accept bound to what was shown -----------------------------------------------------------------------

class M2DriftAccept(unittest.TestCase):
    def test_the_question_carries_every_change_and_its_fingerprint(self):
        h = Harness(self, fixture(labels=("guild:test",)), roles=[role("DONE")], unattended=False)
        viol = [B.LATE + "path lib/f%d.dart" % i for i in range(7)]
        r = B.role_outcome(h.p, "test", "tester", RoleResult("DRIFT", "x", violations=viol, notes=["not run"],
                                                             extras={"drift_fp": "fp-q"}))
        q = [b for b in _blocks(h) if b.get("status") == "pending-human"][-1]
        self.assertIn("7 late change(s)", q.get("question") or r.line)
        self.assertIn("+2 more", r.line)
        self.assertIn("lib/f6.dart", q.get("drift_items"))
        self.assertEqual((q.get("drift_n"), q.get("drift_fp")), ("7", "fp-q"))

    def test_accept_is_bound_to_the_drift_that_was_shown(self):
        # the reviewer's repro: the worktree changes after the question → accept is not applied, the question returns
        h = Harness(self, fixture(labels=("guild:test",)), roles=[role("DONE")], unattended=False)
        seen = {"fp": "fp-shown"}
        accepted = []

        def accept(fp):
            if fp == seen["fp"]:
                accepted.append(fp)
                return None
            return (["path lib/a.dart", "path lib/b.dart"], seen["fp"])
        h.p.accept_drift = accept
        viol = [B.LATE + "path lib/f%d.dart" % i for i in range(7)]
        r = B.role_outcome(h.p, "test", "tester", RoleResult("DRIFT", "x", violations=viol, notes=["not run"],
                                                             extras={"drift_fp": "fp-shown"}))
        seen["fp"] = "fp-after"                                  # written after the question
        ASK.answer(h.decisions, h.writer, 7, r.qid, "accept")
        res = h.p.run_role(B.RoleCall("tester", "verify", "test", "T1"))
        self.assertEqual(accepted, [])
        self.assertEqual(res.status, "DRIFT")
        self.assertEqual(h.calls["roles"], [])
        again = B.role_outcome(h.p, "test", "tester", res)
        self.assertEqual(again.kind, "ASK")
        q2 = [b for b in _blocks(h) if b.get("status") == "pending-human"][-1]
        self.assertEqual(q2.get("drift_fp"), "fp-after")
        self.assertIn("lib/b.dart", q2.get("drift_items"))

    def _runner(self, wt):
        return RR.Runner(journal=EvJournal(), parent_env={"PATH": os.environ["PATH"]},
                         spawn=FakeSpawn([{"stream": stream_lines(texts=[DONE])}] * 3),
                         user_settings=os.path.join(tmpdir(self), "u"), run_root_dir=os.path.join(tmpdir(self), "runs"),
                         claude="claude", clock=Clock())

    def test_the_runner_accepts_only_the_fingerprint_it_showed(self):
        wt = repo(self, {"lib/a.dart": "a\n"})
        git(wt, "switch", "-q", "-c", "fix/1")
        r = self._runner(wt)

        def spec(role_name="developer", task="implement"):
            return RR.RoleSpec(role_name, task, "t", issue=1, stage="s", step="x", worktree=wt, model="sonnet",
                               base="main", branch="fix/1", remote_check=False)
        self.assertEqual(r.run_role(spec()).status, "DONE")
        _w(wt, "lib/a.dart", "a person's edit\n")
        res = r.run_role(spec("reviewer", None))
        self.assertEqual(res.status, "DRIFT")
        fp = res.extras["drift_fp"]
        _w(wt, "lib/a.dart", "written again after the question\n")           # the same path, new content
        again = r.accept_drift(wt, 1, fp)
        self.assertTrue(again and again[0] == ["path lib/a.dart"] and again[1] != fp)
        self.assertNotEqual(r.drift_check(wt, 1), [])                         # nothing accepted
        self.assertIsNone(r.accept_drift(wt, 1, again[1]))                    # the one shown now: accepted
        self.assertEqual(r.drift_check(wt, 1), [])
        self.assertEqual(r.run_role(spec("reviewer", None)).status, "DONE")


# ---- M3 the remote tripwire ----------------------------------------------------------------------------------------

class M3Remote(unittest.TestCase):
    def setUp(self):
        self.wt = repo(self)
        self.old = git(self.wt, "rev-parse", "HEAD")
        _w(self.wt, "b.txt", "b\n")
        git(self.wt, "add", "-A")
        git(self.wt, "commit", "-qm", "main 2")
        self.tip = git(self.wt, "rev-parse", "HEAD")
        git(self.wt, "update-ref", "refs/remotes/origin/main", self.tip)
        git(self.wt, "switch", "-q", "-c", "fix/1")

    def _snaps(self, rb, ra):
        b, a = SC.snapshot(self.wt), SC.snapshot(self.wt)
        b["remote_url"] = a["remote_url"] = "u"
        b["remote"], a["remote"] = rb, ra
        return b, a

    def _remote_viol(self, rb, ra):
        b, a = self._snaps(rb, ra)
        return [x for x in SC.check(self.wt, b, a, ["developer"], branch="fix/1") if "remote" in x]

    def test_force_push_rewinding_remote_main_is_a_violation(self):
        self.assertTrue(self._remote_viol({"refs/heads/main": self.tip}, {"refs/heads/main": self.old}))

    def test_deleting_another_remote_branch_is_a_violation(self):
        self.assertTrue(self._remote_viol({"refs/heads/main": self.tip, "refs/heads/release": self.tip},
                                          {"refs/heads/main": self.tip}))

    def test_a_tag_or_the_base_deleted_is_a_violation(self):
        self.assertTrue(self._remote_viol({"refs/heads/main": self.tip, "refs/tags/v1": self.tip}, {"refs/heads/main": self.tip}))
        self.assertTrue(self._remote_viol({"refs/heads/main": self.tip}, {}))

    def test_a_merged_prs_branch_deleted_by_the_host_is_not(self):
        pr = {"refs/pull/1962/head": "f" * 40}
        self.assertEqual(self._remote_viol(dict(pr, **{"refs/heads/feature/#1956-x": "f" * 40,
                                                       "refs/pull/1962/merge": "e" * 40}), dict(pr)), [])
        # … unless it is this Issue's own branch
        self.assertTrue(self._remote_viol(dict(pr, **{"refs/heads/fix/1": "f" * 40}), dict(pr)))

    def test_a_fast_forward_to_a_commit_a_remote_had_is_still_no_push(self):
        self.assertEqual(self._remote_viol({"refs/heads/main": self.old}, {"refs/heads/main": self.tip}), [])

    def test_the_0102_4_scope_agrees_on_the_rewind(self):
        # review-0102-5 M3: 0.102.4 (scope_0102_4.py of the review) caught both — so does 0.102.6
        b, a = self._snaps({"refs/heads/main": self.tip, "refs/heads/release": self.tip}, {"refs/heads/main": self.old})
        v = SC.check(self.wt, b, a, ["developer"], branch="fix/1")
        self.assertTrue(any("rewound" in x for x in v), v)
        self.assertTrue(any("release deleted" in x for x in v), v)


# ---- M4 effectiveness ----------------------------------------------------------------------------------------------

class M4Effective(unittest.TestCase):
    def test_another_tests_failure_is_not_the_cited_tests(self):
        raw = "\n".join([
            "00:01 +0: loading /t/x_test.dart",
            "00:01 +0: returns empty",
            "00:01 +1: list returns empty",
            "══╡ EXCEPTION CAUGHT BY FLUTTER TEST FRAMEWORK ╞════",
            "Expected: <0>",
            "  Actual: <3>",
            "00:01 +1 -1: list returns empty [E]",
            "  Test failed. See exception logs above.",
            "00:01 +1 -1: Some tests failed.",
        ])
        self.assertEqual(EFF.file_kind(raw, "flutter", "returns empty", False), "passed")
        self.assertEqual(EFF.file_kind(raw, "flutter", "list returns empty", False), "assertion")

    def test_the_full_name_with_its_group_and_a_file_prefix(self):
        raw = ("00:01 +0: /t/x_test.dart: repo returns empty\n  Expected: <0>\n    Actual: <3>\n"
               "00:01 +0 -1: /t/x_test.dart: repo returns empty [E]\n00:01 +0 -1: Some tests failed.\n")
        self.assertEqual(EFF.file_kind(raw, "flutter", "repo › returns empty", False), "assertion")
        self.assertEqual(EFF.file_kind(raw, "flutter", "returns empty", False), "none_ran")   # never a suffix

    def test_a_plain_dart_test_expectation_after_the_E_line_is_an_assertion(self):
        raw = "\n".join([
            "00:01 +0: parses the header",
            "00:01 +0 -1: parses the header [E]",
            "  Expected: 'A'",
            "    Actual: 'B'",
            "     Which: is different.",
            "00:01 +0 -1: Some tests failed.",
        ])
        self.assertEqual(EFF.file_kind(raw, "dart", "parses the header", False), "assertion")

    def test_the_block_after_E_stops_at_the_next_test(self):
        raw = "\n".join([
            "00:01 +0: a",
            "StateError: boom",
            "00:01 +0 -1: a [E]",
            "00:01 +0 -1: b",
            "  Expected: 'A'",
            "    Actual: 'B'",
            "00:01 +0 -2: b [E]",
        ])
        self.assertEqual(EFF.file_kind(raw, "dart", "a", False), "runtime")

    def test_a_vacuous_cited_test_is_not_hidden_by_another_ones_reaction(self):
        class Res(object):
            def __init__(s, passed, raw):
                s.passed, s.raw, s.timed_out = passed, raw, False

        out = {"vacuous": Res(True, "00:01 +1: vacuous\n00:01 +1: All tests passed!\n"),
               "other": Res(False, "00:01 +0: other\nExpected: <1>\n  Actual: <2>\n00:01 +0 -1: other [E]\n"
                                   "00:01 +0 -1: Some tests failed.\n")}

        class Pt(object):
            def check(s, cmd, *a, **k):
                return out[cmd]

            def read_file(s, path):
                return ""

        class TT(object):
            path, file_cmds = "/t", set()
        rows = [({"test": "t.dart::vacuous", "kind": "new"}, "t.dart", "vacuous", 1, "vacuous"),
                ({"test": "t.dart::other", "kind": "new"}, "t.dart", "other", 2, "other")]
        oc = EFF._outcome("AC1", rows, EFF._rerun(Pt(), "flutter", TT(), rows, 60))
        self.assertEqual(oc.result, "unsure")
        self.assertEqual(oc.test, "t.dart::vacuous")
        self.assertIn("reacted: t.dart::other", oc.why)
        out["vacuous"] = Res(False, "00:01 +0: vacuous\nExpected: <1>\n  Actual: <2>\n00:01 +0 -1: vacuous [E]\n"
                                    "00:01 +0 -1: Some tests failed.\n")
        oc = EFF._outcome("AC1", rows, EFF._rerun(Pt(), "flutter", TT(), rows, 60))
        self.assertEqual(oc.result, "pass")


# ---- M5 graded after: the sheet rows exist -------------------------------------------------------------------------

class Blk(dict):
    def __init__(self, i, **f):
        dict.__init__(self, **f)
        self.id, self.n = "D%d" % i, i


class M5Trigger(unittest.TestCase):
    def test_check_unsure_on_a_released_TEST_decision_is_graded(self):
        b = Blk(1, point="TEST", stage="test", by="judge:sonnet", choice="effective:AC1;uncovered:none",
                check_unsure="AC1", grade="trigger", unsure="false")
        sel = G.select({7: [b]}, "o/r", False, 0.0, lambda i, x: None)
        self.assertTrue(any(x[1] is b and x[2].startswith("triggered") for x in sel), sel)

    def test_a_flake_note_reaches_the_sheet(self):
        b = Blk(2, point="flake", stage="test", by="code", choice="green-on-rerun", grade="trigger", reason="r")
        sel = G.select({7: [b]}, "o/r", False, 0.0, lambda i, x: None)
        self.assertEqual([(x[1].id, x[2].split(" —")[0]) for x in sel], [("D2", "triggered: flake")])
        rows = G.sheet_rows(sel, "triggered", lambda i: "-")
        self.assertEqual(rows[0]["group"], "flake")

    def test_the_real_stage_flake_block_is_a_row_and_a_wrong_sets_the_valve(self):
        red = suite("00:01 +5 -1: perf is fast [E]\n00:02 +9 -1: Some tests failed.\n", passed=False, rc=1)
        red.flake = {"tests": ["perf is fast"], "reruns": [{"cmd": "x", "passed": True}], "full_rerun": True,
                     "green": True}
        h = Harness(self, fixture(), roles=[role("DONE", covers=[{"ac": "C1", "test": "test/a_test.dart::a"},
                                                                 {"ac": "C2", "test": "test/a_test.dart::b"}])],
                    suites=[red], judges={"TEST": judge_test(["C1", "C2"])}, checks=[suite(FLUTTER_GREEN)] * 4)
        h.write_file("test/a_test.dart", "void main(){ test('a', (){ expect(f(), 1); }); test('b', (){ expect(g(), 2); }); }\n")
        T.run(h.p)
        blocks = _blocks(h)
        sel = G.select({7: blocks}, "o/r", False, 0.0, lambda i, x: None)
        fl = [x for x in sel if x[1].get("point") == "flake"]
        self.assertEqual(len(fl), 1)
        row = G.sheet_rows(fl, "triggered", lambda i: "-")[0]
        fixed, rej = G.verify_rows([dict(row, given_info="wrong")], lambda n: blocks)
        self.assertEqual(rej, [])
        common = tmpdir(self)
        os.makedirs(os.path.join(common, "guild", "engine"))
        res = G.apply_judgments(common, fixed, "o/r", "human")
        self.assertEqual(res["conservative"], ["flake"])
        from guildcore import valves as VALVES
        self.assertTrue(VALVES.effective(common, {}).get(FL.VALVE))

    def test_the_real_test_stage_check_unsure_is_triggered(self):
        h = Harness(self, fixture(), roles=[role("DONE", covers=[{"ac": "C1", "test": "test/a_test.dart::a", "kind": "new"},
                                                                 {"ac": "C2", "test": "test/a_test.dart::b", "kind": "new"}])],
                    suites=[suite(FLUTTER_GREEN)], judges={"TEST": judge_test(["C1", "C2"])},
                    checks=[suite(FLUTTER_GREEN)] * 4)
        h.write_file("test/a_test.dart", "void main(){ test('a', (){ expect(f(), 1); }); test('b', (){ expect(g(), 2); }); }\n")
        orig = EFF.run
        EFF.run = lambda *a, **k: ({"C1": EFF.CheckOutcome("C1", "t", "unsure", "still passes"),
                                    "C2": EFF.CheckOutcome("C2", "t", "pass", "reacts")}, {})
        self.addCleanup(setattr, EFF, "run", orig)
        self.assertEqual(T.run(h.p).kind, "ADVANCE")
        tb = [b for b in _blocks(h) if b.get("point") == "TEST"][-1]
        self.assertEqual(tb.get("check_unsure"), "C1")
        self.assertTrue(G.triggered(tb, None).startswith("effectiveness check unsure"))


# ---- minors --------------------------------------------------------------------------------------------------------

class M3KickoffIrreversible(unittest.TestCase):
    def test_an_irreversible_kickoff_says_so_and_the_centre_pauses_it(self):
        from test_k6_r3 import EXTRA
        k = kickoff(areas=("lib/db",))
        h = K4(self, unattended=True, roles=[evidence(self, areas=("lib/db",))] * 2, judges={"KICKOFF": k},
               extra_files=EXTRA)
        h.p.unverified = frozenset(["KICKOFF"])
        A.run(h.p)
        kb = [b for b in _blocks(h) if b.get("point") == "KICKOFF"][-1]
        self.assertEqual(kb.get("irreversible"), "true")
        self.assertFalse(kb.get("post_hoc"))
        view, _expl = CEN.first_sprint_view({7: [dict((k, kb.get(k)) for k in ("point", "by", "choice", "irreversible",
                                                                              "stage"))]},
                                            unattended=True, unverified=("KICKOFF",))
        self.assertFalse([b for b in view[7] if b.get("post_hoc")])
        view, _expl = CEN.first_sprint_view({7: [{"point": "KICKOFF", "by": "judge:opus", "choice": "x"}]},
                                            unattended=True, unverified=("KICKOFF",))
        self.assertTrue([b for b in view[7] if b.get("post_hoc")])           # without the mark: post-hoc (0.102.5)


def _exarb():
    return decision("s", {"findings": [{"id": "F1", "verdict": "accept", "reason": "right", "evidence": []}],
                          "summary": "s"})


class M4StagnantHint(unittest.TestCase):
    def test_the_retry_hint_survives_a_crash_resume(self):
        tl = role("DONE")

        class Crash(Exception):
            pass

        def crash(call):
            raise Crash("the worker died in the retried developer call")
        h = XHarness(self, roles=[dev(), tl, auditor([finding()]), dev(), tl, auditor([finding(line=4)]), crash],
                     suites=[suite(FLUTTER_GREEN)] * 3, judges={"EX-ARB": [_exarb()] * 4,
                                                                "IDENT": decision("same", {"verdict": "same"})})
        with self.assertRaises(Crash):
            X.run(h.p, "implement")
        devs = [c for c in h.calls["roles"] if c.role == "developer"]
        self.assertEqual(len(devs), 3)
        self.assertIn("The same blocker came back", devs[2].inputs["retry.md"])
        # the resumed run (same invocation): the retry is spent, and the developer call it makes carries the hint
        h.roles = [dev(), tl, auditor()]
        h.suites.append(suite(FLUTTER_GREEN))
        n0 = len(h.calls["roles"])
        r = X.run(h.p, "implement")
        d2 = [c for c in h.calls["roles"][n0:] if c.role == "developer"]
        self.assertEqual(len(d2), 1)
        self.assertIn("The same blocker came back", d2[0].inputs["retry.md"])
        self.assertIn("auditor BLOCKER lib/a.dart", d2[0].inputs["retry.md"])
        self.assertEqual([b.get("point") for b in _blocks(h)].count("stagnant-retry"), 1)
        self.assertEqual(r.kind, "ADVANCE")


if __name__ == "__main__":
    unittest.main()
