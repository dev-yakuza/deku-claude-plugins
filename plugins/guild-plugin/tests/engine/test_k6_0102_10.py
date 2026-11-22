"""0.102.10 — the review-0102-9 fixes (B1, M1, M2, m1–m4) through the real code paths (the test and analyze stages, the
effectiveness check's static part and re-run classification, the Issue-AC parser, the security gate). The reviewer's
repros (scratchpad `r0102_9/`) are here as the first tests of each class; each failed on 0.102.9 (`25152b4`) — except
where a lead decision changed what the repro asked for (noted on the test).

Lead decisions (k6-notes "0.102.10" — the simpler rule over another heuristic):
1. B1: every case keeps its own cover check after folding. An AC with no covering test is never effective (a gap → the
   normal repair / loop-back), whatever the judge said. A case without a cover inside an otherwise covered AC → a
   grading-sheet row (no loop-back). A judge's weaker answer for any case of an AC is never discarded.
2. M1: a same-file helper's assertion counts only for a helper the test calls unconditionally at its top level (no
   `if` / closure / callback), ≤ 2 helpers deep, and only for a real matcher assertion (`expect` / `expectLater` with a
   matcher argument — not a bare truthy / not-null sanity check).
3. M2/m2: AC items are `-` `*` `+` `・` `•` and numbered items (full-width digits too); any other non-empty line in the
   section that is no item or indented continuation makes the section unread (no auto-narrow, ask). A colon title ends
   at the next title; only the explicit AC title set opens a section (not a generic "criteria").
4. m1: `unchanged_since` removed — the old stagnation stop (and its capture) is the stop.
5. m3: the security TEXT trigger removed — the structured `security_concern` of every group + the security-role source.
6. m4: an AC's check is `unsure` (a grading row) only when the AC itself did not react — a still-passing regression
   guard beside a reacting test is no row.
"""
import unittest

import _util  # noqa: F401
import test_k6_0102_7 as T7
import test_k6_0102_8 as T8
import test_k6_0102_9 as T9
from _k2 import CFG, decision, judge_test, role

from workflows.dev import analysis as AN
from workflows.dev import conservative as CONS
from workflows.dev import effective as EFF
from workflows.dev import grade as G
from workflows.dev.stages import loopback as LP
from workflows.dev.stages import test as T

ALL = ["C%d" % n for n in range(1, 33)]


def _code_blocks(h, point):
    return [b for b in T9.DecisionLog.load(h.gh.comments(7)).blocks if b.get("point") == point]


# ---- B1: a folded case keeps its own cover check --------------------------------------------------------------------

class B1FoldedCaseCover(unittest.TestCase):
    def test_a_ac_with_no_cover_is_not_advanced(self):
        # r0102_9/test_r1 (a) — AC #9's cases C31, C32 have no cover; the judge says effective
        h, r = T9._stage(self, [judge_test(T9.ACS)] * 2, cases=ALL[:30], more_roles=[role("DONE", covers=[])])
        self.assertNotEqual(r.token(), "OK ADVANCE: qa", "AC #9 has no covering test at all")
        self.assertIn("AC #9", T9._tblocks(h)[-1].get("choice").split(";uncovered:")[1])
        repair = [c for c in h.calls["roles"] if c.task == "repair-mapping"]
        self.assertIn("AC #9 (cases C31, C32)", repair[0].inputs["weak-acs.txt"])

    def test_b_cases_without_cover_are_a_grading_row_not_a_loop_back(self):
        # r0102_9/test_r1 (b), adjusted to lead decision 1: the live 0.102.9 #1797 run — C18 (AC #5, the Issue's
        # '실제 출제') and C31 (AC #9) have no cover inside otherwise covered ACs → ADVANCE with a grading-sheet row
        # naming them (0.102.9: no trace anywhere)
        h, r = T9._stage(self, [judge_test(T9.ACS)] * 2, cases=[c for c in ALL if c not in ("C18", "C31")])
        self.assertEqual(r.token(), "OK ADVANCE: qa")
        rows = _code_blocks(h, "case-uncovered")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].get("case_uncovered"), "AC #5: C18; AC #9: C31")
        self.assertTrue(G.code_trigger_row(rows[0]))

    def test_c_a_case_judged_vacuous_is_not_dropped(self):
        # r0102_9/test_r1 (c)
        f = {"ac": [{"id": a, "covered_by": ["test/a_test.dart::t"], "verdict": "effective", "why": "w"}
                    for a in T9.ACS] + [{"id": "C3", "covered_by": ["test/a_test.dart::t"], "verdict": "vacuous",
                                         "why": "asserts nothing about the sheet"}],
             "visual_rows": [], "overall": "all_effective", "security_concern": False}
        h, r = T9._stage(self, [decision("all_effective", f)] * 2)
        self.assertNotEqual(r.token(), "OK ADVANCE: qa", "the judge itself called C3 (AC #2) vacuous")
        self.assertIn("AC #2", T9._tblocks(h)[-1].get("choice").split(";uncovered:")[1])

    def test_every_case_covered_is_no_row(self):
        h, r = T9._stage(self, [judge_test(T9.ACS)])
        self.assertEqual(r.token(), "OK ADVANCE: qa")
        self.assertEqual(_code_blocks(h, "case-uncovered"), [])

    def test_the_unit_verdict_is_the_weakest_answer(self):
        per = {"AC #2": {"verdict": "effective"}, "C3": {"verdict": "not_covering"}, "C4": {"verdict": "effective"}}
        self.assertEqual(T._unit_verdict("AC #2", per, {"AC #2": ["C3", "C4"]}), "not_covering")
        self.assertEqual(T._unit_verdict("AC #2", {"AC #2": {"verdict": "effective"}}, {"AC #2": ["C3", "C4"]}),
                         "effective")

    def test_a_cover_without_a_test_is_no_cover(self):
        self.assertFalse(T.covering({"ac": "C1", "test": "", "kind": "new"}))
        self.assertFalse(T.covering({"ac": "C1", "test": "t::x", "kind": "none"}))
        self.assertTrue(T.covering({"ac": "C1", "test": "t::x", "kind": "guard"}))
        self.assertEqual(T.case_without_cover(["AC #1"], {"AC #1": ["C1", "C2"]},
                                              [{"ac": "AC #1", "case": "C1", "test": "t::x"},
                                               {"ac": "AC #1", "case": "C2", "test": "", "kind": "none"}],
                                              {"AC #1": "effective"}), "AC #1: C2")


# ---- M1: helper assertions — top-level unconditional calls, ≤ 2 deep, a real matcher assertion ----------------------

CODE = """Future<void> _pump(WidgetTester t) async {
  await t.pumpWidget(const App());
  expect(t.widget(find.byType(MaterialApp)), isNotNull);
}
Future<void> _shoot(WidgetTester t) async { await expectLater(find.byType(A), matchesGoldenFile('a.png')); }
Future<void> _smoke(WidgetTester t) async {
  await t.pumpWidget(const App());
  expect(find.byType(MaterialApp), findsOneWidget);
}
Future<void> _l3(WidgetTester t) async { await _shoot(t); }
Future<void> _l2(WidgetTester t) async { await _l3(t); }
void main() {
  testWidgets('smoke only', (t) async {
    await _pump(t);
    await t.tap(find.text('문제 유형'));
    await t.pumpAndSettle();
  });
  testWidgets('dead call', (t) async {
    await t.pumpWidget(const App());
    if (false) { await _shoot(t); }
  });
  testWidgets('closure never run', (t) async {
    final unused = () => _shoot(t);
    await t.pumpWidget(const App());
  });
  testWidgets('conditional call', (t) async {
    if (flag) { await _shoot(t); }
  });
  testWidgets('callback call', (t) async {
    await t.runAsync(() => _shoot(t));
  });
  testWidgets('golden', (t) async {
    await _shoot(t);
  });
  testWidgets('three deep', (t) async {
    await _l2(t);
  });
  testWidgets('matcher in a setup helper', (t) async {
    await _smoke(t);
  });
}
"""


class _P(object):
    def read_file(self, path):
        return CODE


def _helper(name):
    return EFF.helper_assertion(CODE, EFF.test_body(CODE, name, "flutter")[0], "flutter")[0]


class M1HelperAssertion(unittest.TestCase):
    def test_unreachable_or_unrun_helper_call_is_no_assertion(self):
        # r0102_9/test_r2
        for n in ("dead call", "closure never run", "conditional call", "callback call"):
            with self.subTest(test=n):
                self.assertFalse(_helper(n))

    def test_a_setup_helpers_sanity_expect_is_not_the_tests_assertion(self):
        # r0102_9/test_r2, adjusted to lead decision 2: the setup helper's check is a bare not-null sanity check (the
        # repro's `findsOneWidget` is a matcher argument — it counts under the decision, see the control below)
        o, _items = EFF.static_check(_P(), CFG, "AC #2", [{"test": "test/a_test.dart::smoke only", "ac": "AC #2",
                                                            "kind": "new"}])
        self.assertIsNotNone(o, "static check passed a test whose body asserts nothing (only _pump's sanity expect)")
        self.assertEqual(o.result, "fail")

    def test_a_top_level_golden_helper_counts_two_deep_at_most(self):
        self.assertTrue(_helper("golden"))
        self.assertFalse(_helper("three deep"))
        self.assertTrue(_helper("matcher in a setup helper"))          # a matcher argument: lead decision 2

    def test_the_real_1797_golden_tests_still_count(self):
        for n in ("요약이 유형 1개 이름이다", "요약이 N개 선택이다", "요약이 전체이다"):
            with self.subTest(test=n):
                body = EFF.test_body(T9.GOLDEN_1797, "문제 유형 항목 기준 이미지 " + n, "flutter")[0]
                self.assertTrue(EFF.helper_assertion(T9.GOLDEN_1797, body, "flutter")[0])

    def test_matcher_assertions(self):
        for st, want in (("expect(x, equals(2))", True), ("await expectLater(f, matchesGoldenFile('a'))", True),
                         ("expect(x, isNotNull)", False), ("expect(x, isTrue)", False), ("expect(1, 1)", False),
                         ("expect(x)", False), ("fail('x')", False)):
            with self.subTest(st=st):
                self.assertEqual(EFF.matcher_assertion(st, "flutter"), want)
        for st, want in (("expect(a).toBe(2)", True), ("expect(a).toBeTruthy()", False),
                         ("expect(a).not.toBeNull()", False), ("expect(a)", False)):
            with self.subTest(st=st):
                self.assertEqual(EFF.matcher_assertion(st, "jest"), want)


# ---- m1: `unchanged_since` removed — the stagnation stop keeps its capture ------------------------------------------

class m1NoUnchangedSince(unittest.TestCase):
    def test_the_stagnation_capture_is_kept(self):
        # r0102_9/test_r3
        t = T9.R1797dLoopBackWithoutTestChange("test_a_new_loop_back_records_its_head")
        h, r = t._red(True, extra_commit="lib/b.dart")
        self.assertIn("stagnation", [c[0] for c in h.captures], "token %s — the stagnation capture is gone" % r.token())
        self.assertTrue(r.token().startswith("OK PAUSE: needs-human — stagnant loop-back — "), r.token())

    def test_the_early_stop_is_gone(self):
        self.assertFalse(hasattr(LP, "unchanged_since"))
        self.assertFalse(hasattr(T, "is_test_path"))


# ---- M2 / m2: the AC section read whole or not at all ---------------------------------------------------------------

BODY = "## 背景\n設定から問題タイプを選べるようにする。\n\n## 受け入れ条件\n- 項目が表示される\n・再起動しても選択が保持される\n"


class M2IssueAcRead(unittest.TestCase):
    def test_parser_does_not_take_a_partial_read_as_complete(self):
        # r0102_9/test_r4
        has, acs = AN.issue_ac_section(BODY)
        self.assertTrue(len(acs) == 2 or not acs, "read %r of a 2-AC section and called it complete" % acs)

    def test_a_dropped_unparsed_ac_is_not_auto_narrowed(self):
        # r0102_9/test_r4
        h, r = T8._analyze(self, T7._nested({"ac": ["項目が表示される"]}), body=BODY)
        self.assertIsNone(T8._kb(h).get("auto_narrow"), "「再起動しても選択が保持される」 dropped unasked")

    def test_bullets_and_numbering(self):
        for body, want in (
                ("## 受け入れ条件\n・項目が表示される\n・選択が保持される\n", ["項目が表示される", "選択が保持される"]),
                ("## 受け入れ条件\n• a shows\n• b keeps\n", ["a shows", "b keeps"]),
                ("## 受け入れ条件\n１．項目が表示される\n２．選択が保持される\n", ["項目が表示される", "選択が保持される"]),
                ("## 受け入れ条件\n1、項目が表示される\n2) 選択が保持される\n", ["項目が表示される", "選択が保持される"]),
                ("## 인수 기준\n+ a shows\n* b keeps\n", ["a shows", "b keeps"])):
            with self.subTest(body=body):
                has, acs, unread = AN.issue_ac_read(body)
                self.assertEqual((has, acs, unread), (True, want, 0))

    def test_an_unrecognised_line_makes_the_section_unread(self):
        for body in ("## 受け入れ条件\n- a shows\n| b | keeps |\n", "## AC\n- a shows\nb keeps across restarts\n",
                     "## 受け入れ条件\n- a shows\n① b keeps\n"):
            with self.subTest(body=body):
                has, acs, unread = AN.issue_ac_read(body)
                self.assertTrue(has and acs and unread > 0, (has, acs, unread))
        # an indented continuation, a nested item, a comment and a rule are read
        has, acs, unread = AN.issue_ac_read("## AC\n- a shows\n  on the settings screen\n  - nested note\n"
                                            "<!-- example -->\n---\n- b keeps\n")
        self.assertEqual((acs, unread), (["a shows", "b keeps"], 0))

    def test_a_partial_read_is_on_the_unverified_row(self):
        self.assertIn("read only in part", AN.issue_ac_check(["a"], ["a"], unread=1))

    def test_a_colon_title_ends_at_the_next_title(self):
        has, acs, unread = AN.issue_ac_read("受け入れ条件:\n- 項目が表示される\n備考:\n- メモ\n")
        self.assertEqual((has, acs, unread), (True, ["項目が表示される"], 0))

    def test_only_the_explicit_ac_titles_open_a_section(self):
        self.assertEqual(AN.issue_ac_read("## Search criteria UI\n- a filter chip\n"), (False, [], 0))
        self.assertEqual(AN.issue_ac_read("## Acceptance criteria\n- a shows\n"), (True, ["a shows"], 0))

    def test_the_real_1797_body_is_still_read_whole(self):
        has, acs, unread = AN.issue_ac_read(T9.BODY_1797_REAL)
        self.assertEqual((has, len(acs), unread), (True, 5, 0))


# ---- m3: the structured field is the only security signal (no text trigger) -----------------------------------------

FN = ["로그인 유지 토글을 켜면 비밀번호가 평문으로 저장된다",
      "The password is stored in plain text when the remember-me toggle is on",
      "「ログイン状態を保持」トグルをオンにするとパスワードが平文で保存される",
      "토큰이 테마 설정과 함께 로그에 출력된다",
      "token is logged together with the font settings"]
FP = ["the token of the lexer is logged in debug mode"]


class m3StructuredFieldOnly(unittest.TestCase):
    def _spec(self, t):
        return T8._S("QA", [("qa", "QA report: " + t), ("candidates", "-")])

    def test_fn(self):
        # r0102_9/test_r5, adjusted to lead decision 5: the judge's `security_concern: true` asks for each sentence
        for s in FN:
            with self.subTest(s=s):
                self.assertTrue(CONS.security(self._spec(s), decision("pass", {CONS.SECURITY_FIELD: True})))
                self.assertFalse(CONS.posthoc(T8._P(), "QA", self._spec(s), decision=decision(
                    "pass", {CONS.SECURITY_FIELD: True})))

    def test_fp(self):
        # r0102_9/test_r5, adjusted: the judge's `false` is never overruled by the brief's words
        for s in FP + FN:
            with self.subTest(s=s):
                self.assertFalse(CONS.security(self._spec(s), decision("pass", {CONS.SECURITY_FIELD: False})))

    def test_the_text_trigger_is_gone(self):
        self.assertFalse(hasattr(CONS, "security_text"))
        self.assertEqual(set(k for v in CONS.SECURITY_INPUTS.values() for k in v), {"role"})
        # the security role as the source still asks without a decision
        self.assertTrue(CONS.security(T8._S("DE-ARB", [("role", "security returned BLOCKED"), ("line", "x")])))


# ---- m4: a mixed AC (a regression guard beside a reacting test) is no grading row -----------------------------------

class m4RegressionGuard(unittest.TestCase):
    class Res(object):
        def __init__(self, passed, raw):
            self.passed, self.raw, self.timed_out = passed, raw, False

    def _rows(self, out):
        class Pt(object):
            def check(s, cmd, *a, **k):
                return out[cmd]

            def read_file(s, path):
                return ""

        class TT(object):
            path, file_cmds = "/t", set()
        rows = [({"test": "t.dart::guard", "kind": "new", "case": "C25"}, "t.dart", "guard", 1, "guard"),
                ({"test": "t.dart::new", "kind": "new", "case": "C24"}, "t.dart", "new", 2, "new")]
        return EFF._outcome("AC #6", rows, EFF._rerun(Pt(), "flutter", TT(), rows, 60))

    def test_a_guard_beside_a_reacting_test_passes(self):
        red = self.Res(False, "00:01 +0: new\nExpected: <1>\n  Actual: <2>\n00:01 +0 -1: new [E]\n"
                              "00:01 +0 -1: Some tests failed.\n")
        green = self.Res(True, "00:01 +1: guard\n00:01 +1: All tests passed!\n")
        oc = self._rows({"guard": green, "new": red})
        self.assertEqual(oc.result, "pass")
        self.assertIn("regression guard: t.dart::guard", oc.why)
        oc = self._rows({"guard": green, "new": self.Res(True, "00:01 +1: new\n00:01 +1: All tests passed!\n")})
        self.assertEqual(oc.result, "unsure")                  # the AC itself did not react


if __name__ == "__main__":
    unittest.main()
