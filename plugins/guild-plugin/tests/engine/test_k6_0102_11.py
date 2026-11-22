"""0.102.11 — the review-0102-10 fixes (B1, M1–M4, m1–m3 and the loop-back cap proposal) through the real code paths
(the test and qa stages, the case parser on the real word_app #1945 test-cases.md, the effectiveness re-run, the Issue
AC parser, the role runner's scope check, the loop-back procedure). The reviewer's repros (scratchpad `r0102_10/`) are
here as the first tests of each class; each failed on 0.102.10 (`2e0edfa`).

Lead decisions (k6-notes "0.102.11" — simple, deterministic rules):
1. B1: TEST judges the union of the analyze stage's AC list and every AC id test-cases.md names. An AC with no case
   (so no cover) is a gap unless the tester marks it untestable (`kind: none` + a reason) → a grading-sheet row.
2. M1: a cover counts only when its test file exists in the tree under test and the cited test name is in that file.
3. M2: 0.102.10's decision 6 reverted — a NEW test that still passes with the implementation reverted is vacuous: the
   AC's check is `unsure` (a grading row), whatever another test of the AC did.
4. M3: inside an AC section only a markdown heading, an AC title or a next-section title ends it; any other
   `label:` / bold line is a sub-label whose items are read.
5. M4: QA (any read-only role, in an engine worktree) never writes repository files — the engine puts its writes back
   and QA's become a fixable finding for the developer (`release notes missing: <path> — <proposed text>`).
6. Loop-back cap: per source (test ≤ 2, qa ≤ 2) under a total ceiling of 3; a gap while covers name ids the engine
   does not judge stops as an engine defect (no loop-back, the cap untouched); the cap-reached stop offers `reset`.
7. m1: the helper rule also opens a `for` over a literal collection and a `runAsync` callback (top level only).
"""
import os
import unittest

import _util  # noqa: F401
import test_k6_0102_7 as T7
import test_k6_0102_8 as T8
import test_k6_0102_9 as T9
from _k1 import FakeSpawn, RecJournal, git, repo, stream_lines, tmpdir
from _k2 import comment, fixture, judge_qa, judge_test, role

from guildcore.decisions import DecisionLog
from guildcore.records import loopback as LB
from guildcore.records import markers
from guildcore.records import outputs as OUT
from guildcore.roles import runner as RR
from guildcore.roles import scope as SC
from workflows.dev import analysis as AN
from workflows.dev import cases as CS
from workflows.dev import effective as EFF
from workflows.dev import grade as G
from workflows.dev.stages import loopback as LP
from workflows.dev.stages import qa as Q
from workflows.dev.stages import test as T

with open(os.path.join(_util.FX, "real", "word_app-1945-test-cases.md"), encoding="utf-8") as _fh:
    TC_1945 = _fh.read()            # word_app #1945's real test-cases.md (engine journal copy, read-only)
with open(os.path.join(_util.FX, "real", "word_app-1945-ac.md"), encoding="utf-8") as _fh:
    AC_1945 = _fh.read()            # the design's ac.md of that run (`003-design-tester-spec-cases/in/ac.md`)
ALL6 = ["AC #%d" % n for n in range(1, 7)]
ALL32 = ["C%d" % n for n in range(1, 33)]


def _blocks(h, point):
    return [b for b in DecisionLog.load(h.gh.comments(7)).blocks if b.get("point") == point]


def _analyze_out(acs):
    return ("<!-- guild:analyze:output -->\n## Guild analyze — #7\n\nReadiness: Goal=clear · Constraint=clear · "
            "Success=clear\nwork-type: feature\ncast: none\n\n### 수용 기준\n" +
            "".join("- %s: x%s\n" % (a, a[-1]) for a in acs) + "<!-- /guild:analyze:output -->")


def _test_stage(case, covers, test_cases, judges=None, repair=None, analyze=None, files=None):
    """The real test stage: a green suite, the tester's covers, an optional repair answer and analyze record."""
    roles = [role("DONE", covers=covers, e2e="E2E 불요: 위젯 한정")]
    if repair is not None:
        roles.append(role("DONE", covers=repair))
    comments = [comment(_analyze_out(analyze), 1)] if analyze else []
    h = T9.Harness(case, fixture(comments=comments), roles=roles,
                   judges={"TEST": judges or [judge_test(ALL6)] * 2}, suites=[T9.suite(T9.FLUTTER_GREEN)])
    h.write_file("docs/specs/7/test-cases.md", test_cases)
    for rel, text in (files or {"test/a_test.dart": T9.TESTFILE}).items():
        h.write_file(rel, text)
    return h, T.run(h.p)


# ---- B1: the analyze AC list ∪ every AC test-cases.md names ---------------------------------------------------------

class B1EveryAcJudged(unittest.TestCase):
    def test_the_real_1945_test_cases_list_every_ac(self):
        # r0102_10/test_b1 — 0.102.10 judged AC #1, #2, #3, #6 only
        self.assertEqual(len([l for l in AC_1945.split("\n") if l.startswith("- AC #")]), 6)      # control
        units, members, _amap = CS.judged_units(TC_1945)
        self.assertEqual(sorted(units), ALL6)
        self.assertEqual(members["AC #5"], ["E4", "E5"])                       # `- E4 [AC #5] …` folds
        self.assertEqual(members["AC #4"], ["D1", "D2", "D3", "D4", "D6"])     # `(AC #3, #4)` names both

    def test_the_stage_does_not_advance_with_two_acs_never_judged(self):
        # r0102_10/test_b1 — the tester maps the four ACs the 0.102.10 engine listed (the real repair-mapping runs
        # 033/040/063/093); the repair answers the same → AC #4 / AC #5 are a gap, and the judge is asked about them
        covers = [{"test": "test/a_test.dart::t", "ac": a, "kind": "guard"} for a in ("AC #1", "AC #2", "AC #3", "AC #6")]
        h, r = _test_stage(self, covers, TC_1945, judges=[judge_test(["AC #1", "AC #2", "AC #3", "AC #6"])] * 2,
                           repair=covers)
        self.assertNotEqual(r.token(), "OK ADVANCE: qa", "AC #4 / AC #5 have no covering test and were never judged")
        asked = dict(h.calls["judges"][0].brief_parts)["ac"].split("Judge exactly these ids")[1]
        self.assertIn("AC #4", asked)
        self.assertIn("AC #5", asked)
        self.assertEqual(T9._tblocks(h)[-1].get("choice").split(";uncovered:")[1], "AC #4,AC #5")

    def test_an_analyze_ac_no_case_names_is_a_gap(self):
        tc = "## 케이스\n- C1 — AC #1: a\n- C2 — AC #2: b\n"
        covers = [{"test": "test/a_test.dart::t", "ac": c, "kind": "guard"} for c in ("C1", "C2")]
        h, r = _test_stage(self, covers, tc, judges=[judge_test(["AC #1", "AC #2", "AC #3"])] * 2, repair=[],
                           analyze=["AC #1", "AC #2", "AC #3"])
        self.assertEqual(r.token(), "OK LOOPBACK: execute")
        self.assertIn("AC #3", LB.from_comments(h.gh.comments(7)).latest_active().get("signature"))
        repair = [c for c in h.calls["roles"] if c.task == "repair-mapping"]
        self.assertEqual(repair[0].inputs["weak-acs.txt"], "AC #3")

    def test_an_ac_marked_untestable_with_a_reason_is_a_grading_row(self):
        tc = "## 케이스\n- C1 — AC #1: a\n- C2 — AC #2: b\n"
        covers = [{"test": "test/a_test.dart::t", "ac": c, "kind": "guard"} for c in ("C1", "C2")] + \
            [{"test": "", "ac": "AC #3", "kind": "none", "reason": "a follow-up record — no test can verify it"}]
        h, r = _test_stage(self, covers, tc, judges=[judge_test(["AC #1", "AC #2", "AC #3"])],
                           analyze=["AC #1", "AC #2", "AC #3"])
        self.assertEqual(r.token(), "OK ADVANCE: qa")
        rows = _blocks(h, "ac-untestable")
        self.assertEqual(rows[0].get("ac_untestable"), "AC #3")
        self.assertIn("a follow-up record", rows[0].get("reason"))
        self.assertTrue(G.code_trigger_row(rows[0]))
        self.assertTrue(T9._tblocks(h)[-1].get("choice").endswith(";untestable:AC #3"))

    def test_none_without_a_reason_is_still_a_gap(self):
        tc = "## 케이스\n- C1 — AC #1: a\n- C2 — AC #2: b\n"
        covers = [{"test": "test/a_test.dart::t", "ac": c, "kind": "guard"} for c in ("C1", "C2")] + \
            [{"test": "", "ac": "AC #3", "kind": "none"}]
        h, r = _test_stage(self, covers, tc, judges=[judge_test(["AC #1", "AC #2", "AC #3"])] * 2, repair=[],
                           analyze=["AC #1", "AC #2", "AC #3"])
        self.assertEqual(r.token(), "OK LOOPBACK: execute")

    def test_every_case_of_an_ac_marked_untestable(self):
        self.assertEqual(T.untestable("AC #9", {"AC #9": ["C31", "C32"]},
                                      [{"ac": "AC #9", "case": "C31", "kind": "none", "reason": "기록"},
                                       {"ac": "AC #9", "case": "C32", "kind": "none", "reason": "절차"}]),
                         "C31: 기록; C32: 절차")
        self.assertEqual(T.untestable("AC #9", {"AC #9": ["C31", "C32"]},
                                      [{"ac": "AC #9", "case": "C31", "kind": "none", "reason": "기록"}]), "")

    def test_ac_lists_and_tags(self):
        self.assertEqual(CS.ac_refs("### 모달 오류 상태 (AC #3, #4)"), ["AC #3", "AC #4"])
        self.assertEqual(CS.ac_refs("[AC #1, 엣지]"), ["AC #1"])
        self.assertEqual(CS.ac_refs("AC #1·#5 and AC2"), ["AC #1", "AC #5", "AC #2"])
        self.assertEqual(CS.ac_refs("AC #3, 2 cases"), ["AC #3"])              # a continuation needs its `#`
        self.assertEqual(CS.case_ids("## 케이스\n- E4 [AC #5] x\n"), ["E4"])


# ---- M1: a cover counts only when its test is in the tree ------------------------------------------------------------

MISSING = "test/never_written_test.dart::설정 선택이 실제 출제에 반영된다"


def _missing(case, missing_for):
    covers = [{"test": MISSING if c in missing_for else "test/a_test.dart::t", "ac": c,
               "kind": "new" if c in missing_for else "guard"} for c in ALL32]
    h = T9.Harness(case, T9.fixture(), roles=[T9.role("DONE", covers=covers, e2e="E2E 불요"),
                                              T9.role("DONE", covers=[c for c in covers if c["ac"] in missing_for])],
                   judges={"TEST": [judge_test(T9.ACS)] * 2}, suites=[T9.suite(T9.FLUTTER_GREEN)])
    h.write_file("docs/specs/7/test-cases.md", T9.TC_1797)
    h.write_file("test/a_test.dart", T9.TESTFILE)
    return h, T9.T.run(h.p)


class M1CoverMustExist(unittest.TestCase):
    def test_a_an_ac_whose_every_cited_test_is_missing_is_not_effective(self):
        # r0102_10/test_m1 (a)
        h, r = _missing(self, {"C31", "C32"})
        self.assertNotEqual(r.token(), "OK ADVANCE: qa", "AC #9 has no existing test at all")
        self.assertIn("cited test file not found: test/never_written_test.dart", T9._tblocks(h)[-1].get("cover_invalid"))

    def test_b_a_case_citing_a_missing_file_is_on_the_case_row(self):
        # r0102_10/test_m1 (b)
        h, r = _missing(self, {"C18"})
        self.assertEqual(r.token(), "OK ADVANCE: qa")
        rows = _blocks(h, "case-uncovered")
        self.assertTrue(rows and "C18" in (rows[0].get("case_uncovered") or ""),
                        "C18 cites a test file that does not exist — no case row (token %s)" % r.token())

    def test_a_name_not_in_the_file_is_no_cover(self):
        class P(object):
            def read_file(s, path):
                return T9.TESTFILE if path == "test/a_test.dart" else None
        self.assertIsNone(T.cover_problem(P(), "flutter", {"test": "test/a_test.dart::t"}))
        self.assertIn("name not found", T.cover_problem(P(), "flutter", {"test": "test/a_test.dart::nope"}))
        self.assertIn("file not found", T.cover_problem(P(), "flutter", {"test": "test/b_test.dart::t"}))
        self.assertIn("no test name", T.cover_problem(P(), "flutter", {"test": "test/a_test.dart"}))
        # 0.102.12 (review-0102-11 m4): exact — a group prefix counts only when it is a literal of the file
        self.assertIn("name not found", T.cover_problem(P(), "flutter", {"test": "test/a_test.dart::group t"}))
        self.assertFalse(T.covering(dict({"test": "x_test.dart::t", "kind": "new"}, invalid="file not found")))


# ---- M2: a NEW test that does not react is vacuous ------------------------------------------------------------------

class M2NewTestNotReacting(unittest.TestCase):
    class Res(object):
        def __init__(self, passed, raw):
            self.passed, self.raw, self.timed_out = passed, raw, False

    def _oc(self):
        red = self.Res(False, "00:01 +0: c16\nExpected: <1>\n  Actual: <2>\n00:01 +0 -1: c16 [E]\n"
                              "00:01 +0 -1: Some tests failed.\n")
        green = self.Res(True, "00:01 +1: c18\n00:01 +1: All tests passed!\n")

        class Pt(object):
            def check(s, cmd, *a, **k):
                return {"c16": red, "c18": green}[cmd]

            def read_file(s, path):
                return ""

        class TT(object):
            path, file_cmds = "/t", set()
        rows = [({"test": "t.dart::c16", "kind": "new", "case": "C16"}, "t.dart", "c16", 1, "c16"),
                ({"test": "t.dart::c18", "kind": "new", "case": "C18"}, "t.dart", "c18", 2, "c18")]
        return EFF._outcome("AC #5", rows, EFF._rerun(Pt(), "flutter", TT(), rows, 60))

    def test_only_new_tests_are_rerun(self):
        # r0102_10/test_m2 — control: the premise (a guard never reaches `_rerun`)
        import inspect
        self.assertIn('news = [x for x in rows if x[0].get("kind") == "new"]', inspect.getsource(EFF._phases))
        self.assertIn("live[ac] = news", inspect.getsource(EFF._phases))

    def test_a_new_test_that_does_not_react_is_not_a_clean_pass(self):
        # r0102_10/test_m2
        oc = self._oc()
        self.assertFalse(oc.result == "pass" and "regression guard" in oc.why, (oc.result, oc.why))
        self.assertEqual(oc.result, "unsure")
        self.assertEqual(oc.test, "t.dart::c18")
        self.assertIn("(case C18)", oc.why)
        self.assertIn("reacted: t.dart::c16", oc.why)


# ---- M3: sub-labels inside an AC section ----------------------------------------------------------------------------

M3_BODY = ("## 背景\n設定から問題タイプを選べるようにする。\n\n"
           "受け入れ条件:\n- the entry point shows the type\nデータ:\n- 再起動しても選択が保持される\n")


class M3SubLabels(unittest.TestCase):
    def test_parser_reads_the_item_after_a_sub_label_or_reports_unread(self):
        # r0102_10/test_m3
        has, acs, unread = AN.issue_ac_read(M3_BODY)
        self.assertEqual((has, acs, unread), (True, ["the entry point shows the type", "再起動しても選択が保持される"], 0))

    def test_the_dropped_item_is_not_auto_narrowed(self):
        # r0102_10/test_m3
        h, r = T8._analyze(self, T7._nested({"ac": ["the entry point shows the type"]}), body=M3_BODY)
        self.assertIsNone(T8._kb(h).get("auto_narrow"), "「再起動しても選択が保持される」 dropped unasked (%s)" % r.token())

    def test_what_ends_a_section(self):
        rows = {
            "next-section label": ("受け入れ条件:\n- a\n備考:\n- not an AC\n", ["a"]),
            "bold sub-label": ("**Acceptance criteria**\n- a\n**画面**\n- b\n**Notes**\n- no\n", ["a", "b"]),
            "heading": ("受け入れ条件:\n- a\n필수:\n- b\n## 메모\n- no\n", ["a", "b"]),
            "next label in a # section": ("## 수용 기준\n- a\n비고:\n- no\n", ["a"]),
            "another AC title": ("완료 기준:\n- a\n수용 기준:\n- b\n", ["a", "b"]),
        }
        for name, (body, want) in rows.items():
            with self.subTest(case=name):
                self.assertEqual(AN.issue_ac_lines(body), want)


# ---- M4: QA never writes repository files ---------------------------------------------------------------------------

class M4QaWritesPutBack(unittest.TestCase):
    def _repo(self):
        d = repo(self, {"lib/a.dart": "a\n", "release_notes/en.txt": "old\n", "test/a_test.dart": "t\n"})
        return d

    def test_uncommitted_writes_outside_scope_are_reverted(self):
        d = self._repo()
        before = SC.snapshot(d)
        with open(os.path.join(d, "release_notes/en.txt"), "a") as fh:
            fh.write("Pick quiz types from Settings\n")
        with open(os.path.join(d, "release_notes/ko.txt"), "w") as fh:
            fh.write("설정에서 문제 유형 선택\n")
        with open(os.path.join(d, "test/b_test.dart"), "w") as fh:       # inside qa's scope — kept
            fh.write("b\n")
        after = SC.snapshot(d)
        viol = SC.check(d, before, after, ["qa"])
        self.assertEqual(sorted(viol), ["qa wrote release_notes/en.txt", "qa wrote release_notes/ko.txt"])
        paths = SC.revertable(d, before, after, viol, "qa")
        got = dict(SC.revert_writes(d, paths))
        self.assertEqual(got["release_notes/en.txt"], "Pick quiz types from Settings")
        self.assertEqual(got["release_notes/ko.txt"], "설정에서 문제 유형 선택")
        self.assertEqual(open(os.path.join(d, "release_notes/en.txt")).read(), "old\n")
        self.assertFalse(os.path.exists(os.path.join(d, "release_notes/ko.txt")))
        self.assertTrue(os.path.exists(os.path.join(d, "test/b_test.dart")))
        self.assertEqual(SC.check(d, before, SC.snapshot(d), ["qa"]), [])

    def test_what_is_never_reverted(self):
        d = self._repo()
        before = SC.snapshot(d)
        with open(os.path.join(d, "lib/a.dart"), "a") as fh:
            fh.write("x\n")
        git(d, "commit", "-qam", "qa commit")                              # committed → a stop as before
        after = SC.snapshot(d)
        viol = SC.check(d, before, after, ["qa"], branch="main")
        self.assertIsNone(SC.revertable(d, before, after, viol, "qa"))
        self.assertIsNone(SC.revertable(d, before, after, ["protected path .claude/settings.json changed"], "qa"))
        self.assertIsNone(SC.revertable(d, before, after, ["developer wrote lib/a.dart"], "developer"))

    def test_the_runner_puts_back_a_qa_write_in_an_engine_worktree(self):
        main = self._repo()
        wt = os.path.join(tmpdir(self), "wt")
        git(main, "worktree", "add", "-q", "-b", "feat", wt)

        def write(argv, env, cwd, stdin):
            with open(os.path.join(cwd, "release_notes", "en.txt"), "a") as fh:
                fh.write("Pick quiz types\n")
        user = os.path.join(tmpdir(self), "settings.json")
        with open(user, "w") as fh:
            fh.write("{}")
        r = RR.Runner(journal=RecJournal(), common_dir=tmpdir(self), parent_env={"PATH": os.environ["PATH"]},
                      spawn=FakeSpawn([{"stream": stream_lines(texts=[">>> RESULT <<<\nDONE: ok"]), "check": write}]),
                      user_settings=user, run_root_dir=os.path.join(tmpdir(self), "runs"), claude="claude")
        res = r.run_role(RR.RoleSpec("qa", "run", "t", issue=7, stage="qa", step="Q1", worktree=wt, model="sonnet",
                                     base="HEAD", branch="feat", remote_check=False))
        self.assertEqual(res.status, "DONE", res.line)
        self.assertEqual(res.reverted, [("release_notes/en.txt", "Pick quiz types")])
        self.assertEqual(open(os.path.join(wt, "release_notes/en.txt")).read(), "old\n")
        # the same write on the MAIN checkout stays a stop (a person may be editing beside the role)
        r2 = RR.Runner(journal=RecJournal(), common_dir=tmpdir(self), parent_env={"PATH": os.environ["PATH"]},
                       spawn=FakeSpawn([{"stream": stream_lines(texts=[">>> RESULT <<<\nDONE: ok"]), "check": write}]),
                       user_settings=user, run_root_dir=os.path.join(tmpdir(self), "runs2"), claude="claude")
        res2 = r2.run_role(RR.RoleSpec("qa", "run", "t", issue=7, stage="qa", step="Q1", worktree=main,
                                       model="sonnet", base="HEAD", branch="main", remote_check=False))
        self.assertEqual(res2.status, "SCOPE")

    def test_qa_stage_turns_the_reverted_write_into_a_fixable_finding(self):
        import test_k2_qa_stage as K2Q
        r0 = role("DONE", plan="qa-report.md", plan_summary=["릴리스 노트: 추가"])
        r0.reverted = [("release_notes/en.txt", "Pick quiz types from Settings")]
        h = K2Q.qa_harness(self, roles=[r0], judges={"QA": [judge_qa()]})
        r = Q.run(h.p, diff_paths=[])
        self.assertEqual(r.token(), "OK LOOPBACK: execute")
        b = LB.from_comments(h.gh.comments(7)).latest_active()
        self.assertEqual(b.get("from"), "qa")
        self.assertIn("release notes missing: release_notes/en.txt — Pick quiz types from Settings",
                      markers.unescape(b.get("reason")))
        self.assertIn("엔진이 되돌림", h.body_with("qa:output"))
        self.assertTrue(G.code_trigger_row(_blocks(h, "scope-reverted")[0]))

    def test_the_qa_prompt_says_never_edit(self):
        txt = open(os.path.join(os.path.dirname(Q.__file__), "..", "roles", "prompts", "qa-run.md")).read()
        self.assertIn("Never edit release notes", txt)
        self.assertIn("release notes missing: <path>: <proposed text>", txt)


# ---- the loop-back cap: per source, a total ceiling, engine-side gaps, `reset` --------------------------------------

def _blk(n, frm, sig, consumed=True):
    b = LB.render_block(n, frm, "2026-11-22T0%d:00:00Z" % n, "b", "r — %s" % sig, sig)
    return b + ("\nconsumed: 2026-11-22T0%d:30:00Z" % n if consumed else "")


def _qa_loopback(case, blocks):
    import test_k2_qa_stage as K2Q
    rec = LB.render_new_record("\n\n".join(blocks))
    defect = judge_qa("block", defects=[{"id": "D1", "blocking": True, "fixable_in_code": "yes",
                                         "line": "toggleAllQuizTypes ignores the hidden type"}])
    h = K2Q.qa_harness(case, judges={"QA": [defect]}, comments=[comment(rec, 3)])
    return h, Q.run(h.p, diff_paths=[])


class LoopbackCap(unittest.TestCase):
    def test_qas_first_loop_back_is_not_refused_by_tests_cap(self):
        # r0102_10/test_cap_engine_loopbacks — word_app #1797
        h, r = _qa_loopback(self, [_blk(1, "test", "AC #1,AC #3,AC #4,AC #9,C1,C10"), _blk(2, "test", "AC #9,C1,C10")])
        self.assertNotIn("loop-back cap reached", r.token())
        self.assertEqual(r.token(), "OK LOOPBACK: execute")

    def test_per_source_and_total(self):
        rec = LB.LoopbackRecord.parse(LB.render_new_record(_blk(1, "test", "a") + "\n\n" + _blk(2, "test", "b")))
        self.assertTrue(rec.cap_reached("test"))
        self.assertFalse(rec.cap_reached("qa"))
        rec = LB.LoopbackRecord.parse(LB.render_new_record("\n\n".join(
            [_blk(1, "test", "a"), _blk(2, "test", "b"), _blk(3, "qa", "c")])))
        self.assertTrue(rec.cap_reached("qa"))                                   # the ceiling of 3
        rec = LB.LoopbackRecord.parse(LB.render_new_record("\n\n".join(
            [_blk(1, "test", "a"), _blk(2, "test", "b"), LB.render_reset("2026-11-22T03:00:00Z")])))
        self.assertFalse(rec.cap_reached("test"))                                # a reset clears both

    def test_a_qa_cap_stop_offers_reset_and_reset_loops_back_once_more(self):
        h, r = _qa_loopback(self, [_blk(1, "qa", "x"), _blk(2, "qa", "y")])
        self.assertEqual(r.token(), "OK PAUSE: needs-human — loop-back cap reached")
        pend = [b for b in DecisionLog.load(h.gh.comments(7)).blocks
                if b.get("kind") == "loopback" and b.get("status") == "pending-human"]
        self.assertEqual(pend[-1].get("options"), "reset|stop")
        so = OUT.find(h.gh.comments(7), "qa:output")
        self.assertTrue(so.loopback_reason and so.loopback_signature)
        h.decisions.resolve(pend[-1].id, {"kind": "loopback", "stage": "qa", "by": "human", "choice": "reset"})
        h.roles = []
        r2 = Q.run(h.p, diff_paths=[])
        self.assertEqual(r2.token(), "OK LOOPBACK: execute")
        rec = LB.from_comments(h.gh.comments(7))
        self.assertEqual([LB.markers.clean(b.heading) for b in rec.blocks][-2:], ["### loopback-reset", "### loopback 3"])
        self.assertEqual(rec.latest_active().get("decided"), "human")
        # 0.102.12 (review-0102-11 m3): the reset granted exactly this one — history kept, the cap reached again
        self.assertEqual(len(rec.active()), 3)
        self.assertTrue(rec.cap_reached("qa"))

    def test_a_gap_with_covers_naming_unjudged_ids_is_an_engine_defect(self):
        # #1945's first attempt shape: covers name `E1` / `M1` the engine does not judge (here: a document whose
        # cases name no AC) — no loop-back, the cap untouched
        tc = "## 케이스\n| ID | 내용 |\n|---|---|\n| C1 | a |\n| C2 | b |\n"
        covers = [{"test": "test/a_test.dart::t", "ac": "C1", "kind": "guard"},
                  {"test": "test/a_test.dart::t", "ac": "E1", "kind": "guard"}]
        h, r = _test_stage(self, covers, tc, judges=[judge_test(["C1", "C2"])] * 2, repair=[])
        self.assertEqual(r.token(), "OK PAUSE: needs-human — covers name ids the engine does not judge")
        self.assertIsNone(LB.from_comments(h.gh.comments(7)))

    def test_the_cap_helpers(self):
        self.assertEqual((LB.CAP, LB.TOTAL_CAP), (2, 3))
        r = LP._readings(LB.LoopbackRecord.parse(LB.render_new_record(_blk(1, "test", "a"))), "qa", "z")
        self.assertEqual((r["active"], r["total"], r["cap_reached"]), (0, 1, False))


# ---- m1: helper calls in a literal `for` and a `runAsync` callback ---------------------------------------------------

M1_CODE = """Future<void> _shoot(WidgetTester t, String n) async {
  await t.pumpWidget(App(locale: n));
  await expectLater(find.byType(A), matchesGoldenFile('goldens/$n.png'));
}
void main() {
  testWidgets('loop', (t) async {
    for (final l in ['ko', 'ja', 'en']) {
      await _shoot(t, l);
    }
  });
  testWidgets('runAsync', (t) async {
    await t.runAsync(() async {
      await _shoot(t, 'ko');
    });
  });
  testWidgets('dead', (t) async {
    return;
    await _shoot(t, 'ko');
  });
  testWidgets('loop over a variable', (t) async {
    for (final l in locales) {
      await _shoot(t, l);
    }
  });
  testWidgets('conditional per locale', (t) async {
    for (final l in ['ko']) {
      if (flag) { await _shoot(t, l); }
    }
  });
  testWidgets('a user callback', (t) async {
    await each(() async { await _shoot(t, 'ko'); });
  });
}
"""


def _ok(name):
    body = EFF.test_body(M1_CODE, name, "flutter")[0]
    return EFF.has_assertion(body, "flutter")[0] or EFF.helper_assertion(M1_CODE, body, "flutter")[0]


class m1HelperShapes(unittest.TestCase):
    def test_a_helper_called_for_each_locale_counts(self):
        # r0102_10/test_mi_helper_in_loop
        self.assertTrue(_ok("loop"))

    def test_a_helper_called_inside_run_async_counts(self):
        # r0102_10/test_mi_helper_in_loop
        self.assertTrue(_ok("runAsync"))

    def test_a_helper_call_after_return_does_not_count(self):
        # r0102_10/test_mi_helper_in_loop
        self.assertFalse(_ok("dead"))

    def test_the_rest_stays_excluded(self):
        for n in ("loop over a variable", "conditional per locale", "a user callback"):
            with self.subTest(test=n):
                self.assertFalse(_ok(n))


# ---- m3: the tester prompts teach `kind: none` + a reason -----------------------------------------------------------

class m3UntestablePrompt(unittest.TestCase):
    def test_the_prompts(self):
        d = os.path.join(os.path.dirname(Q.__file__), "..", "roles", "prompts")
        for f in ("tester-verify.md", "tester-repair-mapping.md"):
            with self.subTest(prompt=f):
                txt = open(os.path.join(d, f)).read()
                self.assertIn('kind: "none"', txt)
                self.assertIn("reason", txt)


if __name__ == "__main__":
    unittest.main()
