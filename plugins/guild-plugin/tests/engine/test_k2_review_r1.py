"""K2 review r1 — regressions for every probe (review-k2-r1.md B1–B4, M1–M7, m1–m11)."""

import gzip
import json
import os
import re
import shutil
import subprocess
import time
import unittest

import _util
from _k2 import (CFG, FLUTTER_GREEN, Harness, comment, decision, fixture, git, judge_qa, judge_test, repo, role,
                 suite, tmpdir)
from guildcore import checks as CH
from guildcore.decisions import DecisionLog
from guildcore.judges.runner import BriefTooLarge
from guildcore.records import followups as FU
from guildcore.records import loopback as LB
from guildcore.records import markers
from workflows.dev import cases as CS
from workflows.dev import effective as EFF
from workflows.dev import judging as JG
from workflows.dev.stages import qa as Q
from workflows.dev.stages import test as T

UCFG = {"commands": {"test": "python3 -m unittest"}}
K2FX = os.path.join(_util.FX, "k2")


def consumed(b):
    return b + "\nconsumed: 2026-11-15T01:00:00Z"


class B1AssertionScope(unittest.TestCase):
    def test_neighbour_assertion_does_not_count(self):
        src = ("import unittest\nfrom calc import add\n\nclass T(unittest.TestCase):\n    def test_smoke(self):\n"
               "        add(1, 2)          # no assertion\n\n    def test_other(self):\n        self.assertEqual(1 + 1, 2)\n")
        body = EFF.test_body(src, "T.test_smoke", "unittest")
        self.assertNotIn("test_other", body[0])
        self.assertFalse(EFF.has_assertion(body[0], "unittest")[0])

    def test_comments_unreachable_and_tautologies_do_not_count(self):
        for snip, rn in (("  // expect(total).toBe(3)\n  render(<Cart/>);", "jest"),
                         ("  // expect(find.text('3'), findsOneWidget);\n  await tester.pumpWidget(App());", "flutter"),
                         ("    # self.assertEqual(x, 3)\n    run()", "pytest"),
                         ("\tif false { t.Errorf(\"x\") }", "go"),
                         ("expect(1).toBe(1);", "jest"), ("    assert 1 == 1", "pytest"),
                         ("    self.assertEqual(True, True)", "unittest"), ("expect(1, 1);", "flutter"),
                         ("    if False:\n        self.assertEqual(add(1), 2)", "unittest"),
                         ("\tif 1 != 1 { t.Errorf(\"x\") }", "go"), ("\trequire.Equal(t, 1, 1)", "go")):
            with self.subTest(snip=snip):
                self.assertFalse(EFF.has_assertion(snip, rn)[0])
        for snip, rn in (("expect(find.text('a'), findsOneWidget);", "flutter"), ("expect(total(cart)).toBe(3);", "jest"),
                         ("    assert total(c) == 3", "pytest"), ("\tif got != 3 { t.Errorf(\"x\") }", "go")):
            with self.subTest(snip=snip):
                self.assertTrue(EFF.has_assertion(snip, rn)[0])

    def test_no_name_is_unsure_never_the_whole_file(self):
        h = Harness(self, fixture())
        h.write_file("test/a_test.dart", "void main(){ test('x', (){ expect(f(), 1); }); }\n")
        oc, _items = EFF.static_check(h.p, CFG, "C1", [{"test": "test/a_test.dart", "ac": "C1", "kind": "guard"}])
        self.assertEqual(oc.result, "unsure")

    def test_dart_group_name_resolves_own_block(self):
        src = "void main(){ group('g', (){ testWidgets('shows', (t) async { expect(find.text('a'), findsOneWidget); });\n test('b', (){ expect(1,1); }); }); }"
        self.assertTrue(EFF.has_assertion(EFF.test_body(src, "g shows", "flutter")[0], "flutter")[0])
        self.assertFalse(EFF.has_assertion(EFF.test_body(src, "b", "flutter")[0], "flutter")[0])

    def test_runtime_failures_are_not_assertions(self):
        pyt = ("    def test_x():\n>       Cart().total_with_tax()\nE       AttributeError: 'Cart' object has no attribute 'x'\n"
               "FAILED test_cart.py::test_x - AttributeError: x\n============================== 1 failed in 0.03s ===============================\n")
        jest = "FAIL src/cart.test.ts\n  ● cart › totals\n    TypeError: Cannot read properties of undefined (reading 'tax')\nTests:       1 failed, 1 total\n"
        fl = ("00:01 +0: cart totals\nThe following _TypeError was thrown running a test:\nNull check operator used on a null value\n"
              "00:01 +0 -1: cart totals [E]\n00:01 +0 -1: Some tests failed.\n")
        go = "=== RUN   TestCart\n--- FAIL: TestCart (0.00s)\npanic: runtime error: invalid memory address [recovered]\nFAIL\n"
        for raw, rn, name in ((pyt, "pytest", "test_x"), (pyt.replace("AttributeError: 'Cart' object has no attribute 'x'",
                                                                      "TypeError: total() takes 1"), "pytest", "test_x"),
                              (jest, "jest", "totals"), (fl, "flutter", "cart totals"), (go, "go", "TestCart")):
            with self.subTest(rn=rn):
                self.assertEqual(EFF.rerun_kind(raw, rn, name, False), "runtime")

    def test_assertion_signatures_attributed(self):
        fl = ("00:01 +0: cart totals\n  Expected: <3>\n    Actual: <0>\n00:01 +0 -1: cart totals [E]\n00:01 +0 -1: Some tests failed.\n")
        self.assertEqual(EFF.rerun_kind(fl, "flutter", "cart totals", False), "assertion")
        self.assertEqual(EFF.rerun_kind(fl, "flutter", "other test", False), "unknown")
        jest = "  ● cart › totals\n    expect(received).toBe(expected)\nTests:       1 failed, 1 total\n"
        self.assertEqual(EFF.rerun_kind(jest, "jest", "totals", False), "assertion")
        two = "00:01 +1 -1: a [E]\n  Expected: 1\n  Actual: 0\n00:01 +1 -1: Some tests failed.\n"
        self.assertEqual(EFF.rerun_kind(two, "flutter", "a", False), "ambiguous")      # the filter ran 2 tests

    def test_names_with_inner_quotes_survive(self):
        """real word_app #1886: a test name with backticks inside"""
        self.assertEqual(EFF.parse_test_ref("test/b_test.dart::`banner`가 `null`이면 x"),
                         ("test/b_test.dart", "`banner`가 `null`이면 x"))
        src = "void main(){ testWidgets('`banner`가 `null`이면 x', (t) async { expect(find.text('a'), findsOneWidget); }); }"
        self.assertIsNotNone(EFF.test_body(src, "`banner`가 `null`이면 x", "flutter"))

    def test_exact_filters(self):
        self.assertIn("--no-pub --name '(^| )totals$'", EFF.single_command(CFG, "flutter", "test/a_test.dart", "totals"))
        self.assertIn("-t '(^| )totals$'", EFF.single_command({}, "jest", "a.test.ts", "totals"))
        self.assertEqual(EFF.single_command({}, "pytest", "t/test_a.py", "T.test_x"), "python3 -m pytest -v -rs t/test_a.py::T::test_x")
        self.assertIsNone(EFF.single_command({}, "flutter", "a_test.dart", None))


@unittest.skipUnless(shutil.which("go"), "go not installed")
class B1GoRealRun(unittest.TestCase):
    """p_go.py: base panics, HEAD sums, the test's assertion is unreachable — must NOT pass."""

    def test_vacuous_go_test_with_panicking_base(self):
        base_impl = "package cart\n\nfunc Total(items []int) int {\n\tvar m map[string]int\n\tm[\"x\"] = 1\n\treturn 0\n}\n"
        head_impl = "package cart\n\nfunc Total(items []int) int {\n\ts := 0\n\tfor _, i := range items {\n\t\ts += i\n\t}\n\treturn s\n}\n"
        vac = "package cart\n\nimport \"testing\"\n\nfunc TestTotal(t *testing.T) {\n\tgot := Total([]int{1, 2})\n\t_ = got\n\tif false {\n\t\tt.Errorf(\"total = %d\", got)\n\t}\n}\n"
        real = vac.replace("if false {", "if got != 3 {")
        for test_src, want in ((vac, "fail"), (real, "unsure")):
            r = repo(self, {"go.mod": "module example.com/cart\n\ngo 1.22\n", "cart/cart.go": base_impl})
            base = git(r, "rev-parse", "HEAD")
            with open(os.path.join(r, "cart/cart.go"), "w") as fh:
                fh.write(head_impl)
            with open(os.path.join(r, "cart/cart_test.go"), "w") as fh:
                fh.write(test_src)
            git(r, "add", "-A")
            git(r, "commit", "-qm", "impl")
            h = Harness(self, fixture(), root=r, base=base)
            os.environ.setdefault("GOCACHE", os.path.join(tmpdir(self), "gocache"))
            out, _m = EFF.run(h.p, {"commands": {"test": "go test ./..."}}, ["C1"],
                              {"C1": [{"test": "cart/cart_test.go::TestTotal", "ac": "C1", "kind": "new"}]}, base)
            with self.subTest(want=want):
                # the vacuous one fails ①; the real one re-runs → base panics → runtime → unsure
                self.assertEqual(out["C1"].result, want, out["C1"].why)


class B2CaseIds(unittest.TestCase):
    def test_table_separator_is_linear(self):
        t0 = time.time()
        for line in ("|" + "---|" * 12, "|" + "-" * 68 + "|" * 6, "|" + "----|" * 40):
            CS.case_ids(line + "\n" + line + "\n| T1 | a |\n")
        self.assertLess(time.time() - t0, 0.5)

    def test_real_word_app_shapes(self):
        """233 real word_app test-cases (structure lines, Hangul masked except case words): every
        file < 1 s; 20 files carry a golden list checked by hand against their headings/tables
        (not the parser's output — r2-B2); the only id-less files are #961 and #1791; no file
        yields an id from a top-level `## n.` section heading."""
        with gzip.open(os.path.join(K2FX, "tc-shapes.json.gz")) as fh:
            shapes = json.load(fh)
        self.assertEqual(len(shapes), 233)
        zero, golden = [], 0
        for n, v in sorted(shapes.items()):
            t0 = time.time()
            ids = CS.case_ids(v["text"])
            self.assertLess(time.time() - t0, 1.0, n)
            if "golden" in v:
                golden += 1
                self.assertEqual(ids, v["golden"], n)
            if not ids:
                zero.append(n)
            tops = set("#" + m.group(1) for m in re.finditer(r"(?m)^## (\d+)\.", v["text"]))
            table_nums = set("#" + m.group(1) for m in re.finditer(r"(?m)^\|\s*(\d+)\s*\|", v["text"]))
            self.assertFalse((tops - table_nums) & set(ids), n)
        self.assertEqual(golden, 20)
        self.assertEqual(sorted(zero), ["1640", "1791", "961"])   # r3-m1: #1640's bullets are regex notes

    def test_section_headings_are_not_cases(self):
        self.assertEqual(CS.case_ids("## 1. 범위\n## 2. 기존 테스트 현황\n## 3. 테스트 케이스\n### 항목1 — a\n### 항목2 — b\n"),
                         ["항목1", "항목2"])
        self.assertEqual(CS.case_ids("## 1. 개요\n## 2. 공통 전제\n- V2 API 를 쓴다\n| 파일 | 내용 |\n|---|---|\n| H264 | x |\n| ES6 | y |\n"), [])
        self.assertEqual(CS.case_ids("## 2. 엣지 케이스\n### 3. x\n## 4. 기타\n### 5. y\n### 5-1. z\n"), ["#3", "#5-1"])

    def test_shapes(self):
        self.assertEqual(CS.case_ids("| ID | AC | x |\n|---|---|---|\n| T1 | AC1 | a |\n| T2 | AC2 | b |\n"), ["T1", "T2"])
        self.assertEqual(CS.case_ids("| # | 슬라이더 |\n|---|---|\n| 1 | a |\n| 2 | b |\n"), ["#1", "#2"])
        self.assertEqual(CS.case_ids("### TC-S1 (AC1) 본문\n### 케이스 2 — x\n- **C3** y\n"), ["TC-S1", "AC1", "케이스 2", "C3"])
        self.assertEqual(CS.case_ids("| 경로 | 기대 |\n|---|---|\n| a (AC4) | b |\n"), ["AC4"])

    def test_no_ids_falls_back_to_tester_covers(self):
        h = Harness(self, fixture(), roles=[role("DONE", covers=[{"test": "test/a_test.dart::t", "ac": "AC1", "kind": "guard"}],
                                                 e2e="E2E 불요: x")],
                    judges={"TEST": [judge_test(["AC1"])]}, suites=[suite(FLUTTER_GREEN)])
        h.write_file("docs/specs/7/test-cases.md", "prose only\n")
        h.write_file("test/a_test.dart", "void main(){ test('t', (){ expect(f(), 1); }); }\n")
        r = T.run(h.p)
        self.assertEqual(r.token(), "OK ADVANCE: qa")
        blk = [b for b in DecisionLog.load(h.gh.comments(7)).blocks if b.get("point") == "TEST"][0]
        self.assertEqual((blk.get("ac_source"), blk.get("grade")), ("tester", "trigger"))


class B3Unverified(unittest.TestCase):
    def test_no_base_proceeds_flagged(self):
        """p_base.py: base=None, kind new, judge effective twice → must NOT loop back."""
        h = Harness(self, fixture(), roles=[role("DONE", covers=[{"test": "test/a_test.dart::t", "ac": "C1", "kind": "new"}],
                                                 e2e="E2E 불요: x")],
                    judges={"TEST": [judge_test(["C1"])]}, suites=[suite(FLUTTER_GREEN)])
        h.write_file("docs/specs/7/test-cases.md", "| C1 | a |\n")
        h.write_file("test/a_test.dart", "void main(){ test('t', (){ expect(f(), 1); }); }\n")
        r = T.run(h.p)
        self.assertEqual(r.token(), "OK ADVANCE: qa")
        blk = [b for b in DecisionLog.load(h.gh.comments(7)).blocks if b.get("point") == "TEST"][0]
        self.assertEqual(blk.get("checks"), "C1=unverified(not a git worktree)")
        self.assertEqual(blk.get("grade"), "trigger")
        self.assertIn("effective (unverified)", h.body_with("test:output"))

    def test_runner_not_named_is_unverified(self):
        h = Harness(self, fixture())
        h.write_file("a.test.ts", "it('t', () => { expect(f()).toBe(1); });\n")
        oc, _items = EFF.static_check(h.p, {"commands": {"test": "turbo test"}}, "C1",
                                      [{"test": "a.test.ts::t", "ac": "C1", "kind": "new"}])
        self.assertEqual((oc.result, oc.why), ("unverified", "runner not drivable by the engine"))

    def test_merge_base_derived(self):
        r = repo(self, {"a.py": "x=1\n"})
        bare = tmpdir(self)
        git(bare, "init", "-q", "--bare")
        git(r, "remote", "add", "origin", bare)
        git(r, "push", "-q", "origin", "main")
        git(r, "fetch", "-q", "origin")
        base = git(r, "rev-parse", "HEAD")
        with open(os.path.join(r, "a.py"), "w") as fh:
            fh.write("x=2\n")
        git(r, "commit", "-qam", "c")
        self.assertEqual(EFF.default_base(r), base)


class B4TempTreeContainment(unittest.TestCase):
    def test_unsafe_impl_paths_rejected_and_nothing_outside_touched(self):
        d = tmpdir(self)
        victim = os.path.join(d, "victim_abs.txt")
        open(victim, "w").write("keep")
        r = repo(self, {"calc.py": "x=1\n", ".gitignore": "gen/\n"})
        os.makedirs(os.path.join(r, "gen"))
        open(os.path.join(r, "gen", "api.dart"), "w").write("generated")
        base = git(r, "rev-parse", "HEAD")
        with open(os.path.join(r, "calc.py"), "w") as fh:
            fh.write("x=2\n")
        git(r, "commit", "-qam", "impl")                 # r5-M2: the revert scope is the actual diff
        files, _src, bad = EFF.impl_files(r, base, [victim, "../victim_rel.txt", "gen/api.dart", "calc.py"])
        self.assertEqual(files, ["calc.py"])
        self.assertEqual(sorted(bad), sorted([victim, "../victim_rel.txt", "gen/api.dart"]))
        with EFF.TempTree(r, base, ["calc.py"]) as t:
            self.assertEqual(t.skipped_ignored, ["gen/"])                     # never copied/linked
            t.revert()
        self.assertTrue(os.path.exists(victim))
        self.assertTrue(os.path.exists(os.path.join(r, "gen", "api.dart")))
        self.assertEqual(git(r, "worktree", "list").count("\n"), 0)      # m6: cleaned on failure

    def test_dart_tool_copied_build_fresh_others_linked(self):
        r = repo(self, {"calc.py": "x=1\n", ".gitignore": ".dart_tool/\nbuild/\nnode_modules/\n"})
        for d in (".dart_tool/hooks_runner", ".dart_tool/build", "build/native_assets", "node_modules/x"):
            os.makedirs(os.path.join(r, d))
        open(os.path.join(r, ".dart_tool", "package_config.json"), "w").write("{}")
        with EFF.TempTree(r, git(r, "rev-parse", "HEAD"), []) as tt:
            t = tt.path
            self.assertFalse(os.path.islink(os.path.join(t, ".dart_tool")))
            self.assertTrue(os.path.exists(os.path.join(t, ".dart_tool", "package_config.json")))
            self.assertTrue(os.path.isdir(os.path.join(t, ".dart_tool", "hooks_runner")))
            self.assertFalse(os.path.exists(os.path.join(t, ".dart_tool", "build")))        # compile cache left out
            self.assertEqual(os.listdir(os.path.join(t, "build")), [])                      # fresh tool output
            self.assertTrue(os.path.islink(os.path.join(t, "node_modules")))

    def test_test_paths_m8(self):
        self.assertIsNone(EFF.TEST_PATH_RE.search("lib/test_utils.dart"))
        self.assertTrue(EFF.TEST_PATH_RE.search("test/a_test.dart"))


class M1QaSignature(unittest.TestCase):
    def test_different_defect_with_same_id_is_not_stagnant(self):
        prev = LB.render_new_record(consumed(LB.render_block(1, "qa", "t", "b", "r", "qa:deadbeef")))
        h = Harness(self, fixture(labels=("guild:qa",), comments=[comment(prev, 3)]),
                    roles=[role("DONE", plan="p", plan_summary=[], ran=[], not_run=[], human_items=[])],
                    judges={"QA": [judge_qa("block", defects=[{"id": "D1", "blocking": True, "fixable_in_code": "yes",
                                                               "line": "설정 화면 저장이 다크모드에서 깨짐"}])]})
        r = Q.run(h.p, diff_paths=[])
        self.assertEqual(r.kind, "LOOPBACK")

    def test_same_as_reuses_and_paths_are_stable(self):
        prev = [("r", {"lib/a.dart"})]
        self.assertEqual(Q.qa_signature([{"id": "D9", "line": "x", "same_as": "lib/a.dart"}], prev), ["lib/a.dart"])
        a = Q.qa_signature([{"id": "D1", "line": "목록이 갱신 안 됨", "evidence": "lib/list.dart:12"}], [])
        b = Q.qa_signature([{"id": "D2", "line": "정렬이 깨짐", "evidence": "lib/list.dart:40"}], [])
        self.assertTrue(a[0].startswith("lib/list.dart#"))
        self.assertNotEqual(a, b)                      # K2r2-m1: one screen file, two defects
        a = Q.qa_signature([{"id": "D1", "line": "Same  thing"}], [])
        self.assertEqual(a, Q.qa_signature([{"id": "D2", "line": "same thing"}], []))


class M2RepairMerge(unittest.TestCase):
    def test_partial_repair_keeps_confirmed_mappings(self):
        c1 = {"test": "test/a_test.dart::t", "ac": "C1", "kind": "guard"}
        c2 = {"test": "test/a_test.dart::u", "ac": "C2", "kind": "guard"}
        self.assertEqual(T.merge_covers([c1], [c2, dict(c1, test="x")], {"C2"}), [c1, c2])


class M3Records(unittest.TestCase):
    def test_relint_keeps_the_first_verdict(self):
        first = judge_qa("block", defects=[{"id": "D1", "blocking": True, "fixable_in_code": "no", "line": "결함"}],
                         checklist=["가능하면 확인 — 어디"])
        h = Harness(self, fixture(labels=("guild:qa",)), roles=[role("DONE", plan="p", human_items=[])],
                    judges={"QA": [first, judge_qa("pass", checklist=["확인 — 어디"])]})
        r = Q.run(h.p, diff_paths=[])
        self.assertEqual(r.kind, "PAUSE")                      # the 2nd call only rewords the checklist
        pts = [b.get("point") for b in DecisionLog.load(h.gh.comments(7)).blocks]
        self.assertIn("QA", pts)
        self.assertIn("QA:relint", pts)

    def test_every_test_judgment_recorded(self):
        h = Harness(self, fixture(), roles=[role("DONE", covers=[{"test": "test/a_test.dart::t", "ac": "C1", "kind": "guard"}],
                                                 e2e="E2E 불요: x"), role("DONE", covers=[])],
                    judges={"TEST": [judge_test(["C1"], "not_covering"), judge_test(["C1"], "not_covering")]},
                    suites=[suite(FLUTTER_GREEN)])
        h.write_file("docs/specs/7/test-cases.md", "| C1 | a |\n")
        T.run(h.p)
        pts = [b.get("point") for b in DecisionLog.load(h.gh.comments(7)).blocks]
        self.assertEqual([x for x in pts if x.startswith("TEST")], ["TEST", "TEST:repair"])

    def test_directive_decision_recorded(self):
        raw = "00:01 +1 -1: x [E]\n00:01 +1 -1: Some tests failed.\nGolden \"g.png\": Pixel test failed\n"
        h = Harness(self, fixture(comments=[dict(comment("사람: 시각 실패는 무시", 5))]), host="linux amd64",
                    roles=[role("DONE", covers=[], e2e="E2E 불요: x")],
                    judges={"DIRECTIVE": decision("out_of_scope", {"verdict": "out_of_scope", "applies": [],
                                                                    "out_of_scope": [{"comment": "#7", "line": "무시"}]})},
                    suites=[suite(raw, passed=False, rc=1)])
        h.write_file("docs/specs/7/test-cases.md", "| C1 | a |\n")
        T.run(h.p)
        self.assertIn("DIRECTIVE", [b.get("point") for b in DecisionLog.load(h.gh.comments(7)).blocks])


class M4BriefAndPush(unittest.TestCase):
    def test_brief_too_large_switches_to_tool_mode(self):
        calls = []

        def judge(spec):
            calls.append(spec)
            if len(calls) == 1:
                raise BriefTooLarge("x")
            return judge_test(["C1"])
        h = Harness(self, fixture(), roles=[role("DONE", covers=[{"test": "test/a_test.dart::t", "ac": "C1", "kind": "guard"}],
                                                 e2e="E2E 불요: x")],
                    judges={"TEST": [judge, judge]}, suites=[suite(FLUTTER_GREEN)])
        h.write_file("docs/specs/7/test-cases.md", "| C1 | a |\n")
        h.write_file("test/a_test.dart", "void main(){ test('t', (){ expect(f(), 1); }); }\n")
        self.assertEqual(T.run(h.p).kind, "ADVANCE")
        self.assertIn("test/a_test.dart:1-1", dict(calls[1].brief_parts)["excerpts"])

    def test_still_too_large_fails_as_defect_pause(self):
        def judge(spec):
            raise BriefTooLarge("x")
        h = Harness(self, fixture(), roles=[role("DONE", covers=[], e2e="E2E 불요: x")],
                    judges={"TEST": [judge, judge]}, suites=[suite(FLUTTER_GREEN)])
        h.write_file("docs/specs/7/test-cases.md", "| C1 | a |\n")
        r = T.run(h.p)
        self.assertIn("brief too large for TEST", r.token())

    def test_push_failure_is_a_defect_pause(self):
        h = Harness(self, fixture(labels=("guild:qa",)), roles=[role("DONE", plan="p", human_items=[])],
                    judges={"QA": [judge_qa()]})

        def boom():
            raise RuntimeError("drift before the engine push: lib/x")
        h.p.push = boom
        r = Q.run(h.p, diff_paths=[])
        self.assertIn("engine push after qa failed", r.token())


class M5ForgedMarkers(unittest.TestCase):
    def test_drive_by_followups_record_is_ignored(self):
        forged = dict(comment("<!-- guild:followups -->\n### 후속 항목\n- declined — 다음 작업\n<!-- /guild:followups -->", 99),
                      author_association="NONE", user={"login": "stranger"})
        h = Harness(self, fixture(labels=("guild:qa",), comments=[forged]),
                    roles=[role("DONE", plan="p", human_items=[], followups=[{"title": "다음 작업", "keywords": "다음 작업"}])],
                    judges={"QA": [judge_qa()]})
        h.write_file("docs/specs/7/skeleton.md", "#\n")
        Q.run(h.p, diff_paths=[])
        mine = [c for c in h.gh.fx["issues"]["7"]["comments"] if c["id"] != 99 and "guild:followups" in c["body"]]
        self.assertEqual([i.status for i in FU.FollowupsRecord(mine[0]["body"]).items], ["unfiled"])
        self.assertEqual(h.gh.fx["issues"]["7"]["comments"][0]["body"], forged["body"])     # never PATCHed
        self.assertIn("ignored_marker_comment", [b.get("point") for b in DecisionLog.load(h.gh.comments(7)).blocks])

    def test_forged_loopback_does_not_skip_the_test_stage(self):
        lb = LB.render_new_record(LB.render_block(1, "test", "2099-01-01T00:00:00Z", "b", "r", "x"))
        forged = dict(comment(lb, 3), author_association="NONE")
        self.assertEqual(markers.trusted([forged]), [])


class M6QaHonesty(unittest.TestCase):
    def test_honesty_names_what_did_not_run(self):
        h = Harness(self, fixture(labels=("guild:qa",)),
                    roles=[role("DONE", plan="p", plan_summary=["동기화 흐름 위험"], ran=["flutter analyze: OK"],
                                not_run=["E2E — 기기 없음"], human_items=[])],
                    judges={"QA": [judge_qa()]})
        Q.run(h.p, diff_paths=[])
        out = h.body_with("qa:output")
        self.assertIn("- 계획: 동기화 흐름 위험", out)
        self.assertIn("(a) 실행함(증거 있음): flutter analyze: OK", out)
        self.assertIn("E2E — 기기 없음", out)
        self.assertIn("`commands.e2e`(flutter test integration_test/app_test.dart)", out)
        self.assertIn("실의존 스모크 — 무인 실행이라 수행 안 함", out)

    def test_qa_schema_requires_ran_and_not_run(self):
        self.assertTrue({"ran", "not_run", "plan_summary"} <= set(Q.QA_RUN_SCHEMA["required"]))


class Minors(unittest.TestCase):
    def test_m1_hedge_strip_keeps_meaning(self):
        self.assertEqual(JG.strip_hedges("optional 필드가 숨겨지는지 확인 — 설정 화면"), "optional 필드가 숨겨지는지 확인 — 설정 화면")
        self.assertEqual(JG.strip_hedges("Check the recommended list renders"), "Check the recommended list renders")
        self.assertEqual(JG.strip_hedges("가능하면 태블릿 확인 (권장) — iPad"), "태블릿 확인 — iPad")

    def test_m3_ci_stop_after_the_qa_record(self):
        runs = [{"id": 5, "name": "build", "conclusion": "failure", "annotations": 0}]
        fx = fixture(labels=("guild:qa",), prs=[{"number": 40, "state": "OPEN", "title": "x", "body": "Closes #7",
                                                  "headRefOid": "a" * 40}])
        fx["check_runs"]["a" * 40] = runs
        h = Harness(self, fx, roles=[role("DONE", plan="p", human_items=[])], judges={"QA": [judge_qa()]},
                    config=dict(CFG, engine={"qa": {"stop_on_ci_red": True}}))
        r = Q.run(h.p, diff_paths=[])
        self.assertEqual(r.kind, "PAUSE")
        self.assertIn("PR CI: red build", h.body_with("qa:output"))

    def test_m4_visual_env_question_has_one_option(self):
        raw = "00:01 +1 -1: x [E]\n00:01 +1 -1: Some tests failed.\nGolden \"g.png\": Pixel test failed\n"
        h = Harness(self, fixture(), unattended=False, host="linux amd64",
                    roles=[role("DONE", covers=[], e2e="E2E 불요: x")], suites=[suite(raw, passed=False, rc=1)])
        h.write_file("docs/specs/7/test-cases.md", "| C1 | a |\n")
        r = T.run(h.p)
        self.assertEqual(DecisionLog.load(h.gh.comments(7)).by_id(r.qid).get("options"), "ok")

    def test_m5_answer_marked_after_the_block_and_no_twin(self):
        h = Harness(self, fixture(), unattended=False)
        out = "<!-- guild:test:output -->\nx\nloopback-reason: r\nloopback-signature: a\n<!-- /guild:test:output -->"
        h.gh.fx["issues"]["7"]["comments"].append(comment(out, 2))
        q = h.decisions.record({"point": "loopback-ask:test", "kind": "loopback", "stage": "test", "status": "pending-human",
                                "options": ["loop-back", "stop"]})
        h.decisions.resolve(q, {"kind": "loopback", "stage": "test", "by": "human", "choice": "loop-back"})
        orig = h.writer.labels_apply
        h.writer.labels_apply = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("crash"))
        with self.assertRaises(RuntimeError):
            T.run(h.p)
        h.writer.labels_apply = orig
        self.assertIsNotNone(B_pending(h))                     # not yet applied: the label never moved
        r = T.run(h.p)                                         # → interrupted loop-back, answer marked
        self.assertEqual(r.kind, "LOOPBACK")
        self.assertEqual(len(LB.from_comments(h.gh.comments(7)).numbered()), 1)
        self.assertIsNone(B_pending(h))

    def test_m9_absent_quality_bar_is_met(self):
        h = Harness(self, fixture(labels=("guild:qa",)), roles=[role("DONE", plan="p", human_items=[])],
                    judges={"QA": [judge_qa("block", bar="unsure")]})
        self.assertEqual(Q.run(h.p, diff_paths=[]).kind, "DONE")
        blk = [b for b in DecisionLog.load(h.gh.comments(7)).blocks if b.get("point") == "QA"][0]
        self.assertEqual(blk.get("quality_bar"), "absent")


def B_pending(h):
    from workflows.dev.stages import base as B
    return B.pending_answer(h.p, "test", "loopback")[1]


if __name__ == "__main__":
    unittest.main()


# ---- review r2 (review-k2-r2.md) ---------------------------------------------------------------

from guildcore.checks import CheckResult  # noqa: E402
from guildcore.checks.netproxy import AllowlistProxy  # noqa: E402


class _RawPort(object):
    def __init__(self, files, raws):
        self.files, self.raws, self.cmds = files, list(raws), []
        self.root = None

    def read_file(self, rel):
        return self.files.get(rel)

    def check(self, cmd, cwd, owner, t, wd):
        self.cmds.append(cmd)
        raw, ok = self.raws.pop(0)
        return CheckResult(ok, 0 if ok else 1, False, raw, [], t)


class _TT(object):
    path = "/nonexistent"
    skipped_ignored = []

    def revert(self, full=True):
        self.reverted = full


FL = {"commands": {"test": "flutter test"}}
PYC = {"commands": {"test": "python3 -m pytest"}}
JSC = {"commands": {"test": "npx jest"}}
HEAD_OK_FL = ("00:00 +1: adds tax\n00:00 +1: All tests passed!\n", True)


def _phase(cfg, files, ref, raws, kind="new"):
    p = _RawPort(files, raws)
    runner = EFF.runner_of(cfg)
    path, name = EFF.parse_test_ref(ref)
    o, items = EFF.static_check(p, cfg, "AC1", [{"test": ref, "ac": "AC1", "kind": kind}])
    if o is not None:
        return o, p
    out = {}
    rows = [(cv, pa, na, ln, EFF.single_command(cfg, runner, pa, na)) for cv, pa, na, ln in items]
    EFF._phases(p, runner, {"AC1": rows}, _TT(), "base", ["lib/cart.dart"], out, 60)
    return out["AC1"], p


class R2B1NothingRanAndRuntime(unittest.TestCase):
    DSKIP = "void main(){\n  test('adds tax', () {\n    final c = Cart();\n    expect(c.totalWithTax(), 110);\n  }, skip: true);\n}\n"
    PYSKIP = "import pytest\n@pytest.mark.skip(reason='later')\ndef test_tax():\n    assert Cart().total_with_tax() == 110\n"

    def test_skipped_flutter_new_and_guard_are_unsure(self):
        skipped = ("00:00 +0 ~1: adds tax (skipped)\n00:00 +0 ~1: All tests skipped.\n", True)
        for kind in ("new", "guard"):
            with self.subTest(kind=kind):
                o, _p = _phase(FL, {"test/c_test.dart": self.DSKIP}, "test/c_test.dart::adds tax", [skipped], kind)
                self.assertEqual(o.result, "unsure")
                self.assertIn("did not run at HEAD", o.why)

    def test_skipped_pytest_is_unsure(self):
        raw = ("tests/test_c.py::test_tax SKIPPED (later)\n"
               "============================== 1 skipped in 0.01s ==============================\n", True)
        o, _p = _phase(PYC, {"tests/test_c.py": self.PYSKIP}, "tests/test_c.py::test_tax", [raw])
        self.assertEqual(o.result, "unsure")

    def test_filter_matched_nothing_is_unsure(self):
        dart = "void main(){\n  test('adds tax', () {\n    expect(Cart().total(), 110);\n  });\n}\n"
        o, _p = _phase(FL, {"test/c_test.dart": dart}, "test/c_test.dart::adds tax",
                       [("00:00 +0: All tests passed!\n", True)])
        self.assertEqual(o.result, "unsure")

    def test_runtime_errors_are_unsure_not_unverified(self):
        js = "it('adds tax', () => {\n  const c = new Cart();\n  c.applyTax();\n  expect(c.items).toHaveLength(1);\n});\n"
        jhead = ("PASS src/c.test.ts\n  ✓ adds tax\nTests:       1 passed, 1 total\n", True)
        jrev = ("FAIL src/c.test.ts\n  ● adds tax\n    TypeError: c.applyTax is not a function\nTests:       1 failed, 1 total\n", False)
        py = "def test_tax():\n    c = Cart()\n    c.apply_tax()\n    assert c.items\n"
        phead = ("tests/test_c.py::test_tax PASSED\n============================== 1 passed in 0.01s ==============================\n", True)
        prev = ("tests/test_c.py::test_tax FAILED\nE   NameError: name 'TAX' is not defined\n"
                "FAILED tests/test_c.py::test_tax - NameError: name 'TAX' is not defined\n"
                "============================== 1 failed in 0.03s ==============================\n", False)
        dart = "void main(){\n  test('adds tax', () {\n    final c = Cart();\n    c.applyTax();\n    expect(c.items, isNotEmpty);\n  });\n}\n"
        frev = ("00:00 +0: adds tax\nError: tax table missing\n══╡ EXCEPTION CAUGHT BY FLUTTER TEST FRAMEWORK ╞══\nStateError\n"
                "00:00 +0 -1: adds tax [E]\n00:00 +0 -1: Some tests failed.\n", False)
        for cfg, files, ref, raws in ((JSC, {"src/c.test.ts": js}, "src/c.test.ts::adds tax", [jhead, jrev]),
                                      (PYC, {"tests/test_c.py": py}, "tests/test_c.py::test_tax", [phead, prev]),
                                      (FL, {"test/c_test.dart": dart}, "test/c_test.dart::adds tax", [HEAD_OK_FL, frev])):
            with self.subTest(ref=ref):
                o, _p = _phase(cfg, files, ref, raws)
                self.assertEqual((o.result, o.kind), ("unsure", "runtime"), o.why)

    def test_compile_error_tries_the_second_step(self):
        dart = "void main(){\n  test('adds tax', () {\n    final c = Cart();\n    c.applyTax();\n    expect(c.items, isNotEmpty);\n  });\n}\n"
        comp = ("lib/cart.dart:3:5: Error: The method 'applyTax' isn't defined for the class 'Cart'.\n"
                "00:00 +0 -1: loading test/c_test.dart [E]\n  Failed to load \"test/c_test.dart\": x\n00:00 +0 -1: Some tests failed.\n", False)
        o, p = _phase(FL, {"test/c_test.dart": dart}, "test/c_test.dart::adds tax", [HEAD_OK_FL, comp, comp])
        self.assertEqual((o.result, o.kind), ("unverified", "load_error"))
        self.assertEqual(len(p.cmds), 3)                    # HEAD, full revert, partial revert
        self.assertIn("added files kept", o.why)

    def test_assertion_in_a_string_literal_does_not_count(self):
        dstr = "test('adds tax', () {\n  final c = Cart()..applyTax();\n  debugPrint('expect(c.total, 110) checked manually');\n});"
        self.assertFalse(EFF.has_assertion(dstr, "flutter")[0])
        self.assertFalse(EFF.has_assertion('def test_x():\n    """assert result == 3 elsewhere"""\n    run()\n', "pytest")[0])

    def test_subtests_count_as_one(self):
        go = "=== RUN   TestTotal\n=== RUN   TestTotal/empty\n=== RUN   TestTotal/two\n--- PASS: TestTotal (0.00s)\nok x\n"
        self.assertEqual(EFF.counts(go, "go"), (1, 0))
        py = "t.py::test_x[1] PASSED\nt.py::test_x[2] PASSED\n===== 2 passed in 0.01s =====\n"
        self.assertEqual(EFF.counts(py, "pytest"), (1, 0))

    def test_escape_is_regex_syntax_only(self):
        self.assertEqual(EFF.rx_escape("a b (c).d"), "a b \\(c\\)\\.d")


class R2B3NeverAdvanceUnjudged(unittest.TestCase):
    def test_missing_test_cases_pauses(self):
        h = Harness(self, fixture(), test_cases=None, roles=[role("DONE", covers=[], e2e="E2E 불요: x")],
                    suites=[suite(FLUTTER_GREEN)])
        r = T.run(h.p)
        self.assertEqual(r.kind, "PAUSE")
        self.assertIn("test-cases.md is missing", r.token())
        self.assertEqual(h.labels(), ["guild:needs-human", "guild:test"])

    def test_no_ids_no_covers_loops_back_after_one_repair(self):
        h = Harness(self, fixture(), test_cases="prose only\n",
                    roles=[role("DONE", covers=[], e2e="E2E 불요: x"), role("DONE", covers=[])],
                    suites=[suite(FLUTTER_GREEN)])
        r = T.run(h.p)
        self.assertEqual(r.token(), "OK LOOPBACK: execute")
        self.assertEqual(LB.from_comments(h.gh.comments(7)).latest_active().get("signature"), "ac:none")
        self.assertEqual([c.task for c in h.calls["roles"]], ["verify", "repair-mapping"])

    def test_tester_blocked_never_advances(self):
        h = Harness(self, fixture(), roles=[role("BLOCKED", "cannot read test-cases", evidence="x"),
                                            role("BLOCKED", "still cannot", evidence="x")],
                    suites=[suite(FLUTTER_GREEN)])
        r = T.run(h.p)
        self.assertEqual(r.kind, "LOOPBACK")
        self.assertEqual(len(h.calls["judges"]), 0)


class R2M1OfflineReruns(unittest.TestCase):
    def test_proxy_is_exact_host_and_443(self):
        px = AllowlistProxy(["github.com", "storage.googleapis.com"])
        handler = px.srv.RequestHandlerClass

        class F(object):
            pass
        f = F()
        f.server = px.srv
        for host, port, want in (("github.com", 443, True), ("api.github.com", 443, False),
                                 ("uploads.github.com", 443, False), ("x.storage.googleapis.com", 443, False),
                                 ("github.com", 22, False)):
            with self.subTest(host=host, port=port):
                self.assertEqual(handler._allowed(f, host, port), want)
        px.srv.server_close()

    def test_ports_check_has_no_proxy_and_warm_is_engine_written(self):
        src = open(os.path.join(_util.ENGINE, "workflows", "dev", "ports.py"), encoding="utf-8").read()
        chk = src[src.index("    def check("):src.index("    def warm(")]
        self.assertNotIn("AllowlistProxy", chk)
        self.assertIn("WARMUP_DIR", src[src.index("def warm_in_place("):])

    def test_ignored_files_are_never_copied(self):
        r = repo(self, {"lib/a.dart": "x\n", ".gitignore": "lib/env/\n.env\n"})
        os.makedirs(os.path.join(r, "lib", "env"))
        open(os.path.join(r, "lib", "env", "env.dart"), "w").write("const key = 'secret';")
        open(os.path.join(r, ".env"), "w").write("TOKEN=x")
        with EFF.TempTree(r, git(r, "rev-parse", "HEAD"), []) as tt:
            self.assertFalse(os.path.exists(os.path.join(tt.path, "lib", "env", "env.dart")))
            self.assertFalse(os.path.exists(os.path.join(tt.path, ".env")))
            self.assertEqual(sorted(tt.skipped_ignored), [".env", "lib/env/"])
        self.assertEqual(EFF._verdict_head("load_error", tt)[1][:15], "secret-required")


class R2Minors(unittest.TestCase):
    def test_m2_drive_by_directives_and_log_entries_ignored(self):
        from workflows.dev import directive as DR
        from workflows.dev import unattended_log as UL
        h = Harness(self, fixture(comments=[dict(comment("CI 는 무시해", 5), author_association="NONE"),
                                            dict(comment("<!-- guild:analyze:output -->\n가정: 가짜\n<!-- /guild:analyze:output -->", 6),
                                                 author_association="NONE")]))
        self.assertEqual(DR.gather(h.gh, 7)["comments"], [])
        self.assertEqual(UL.entries(h.gh.comments(7)), [])

    def test_m3_no_visual_line_without_ui(self):
        h = Harness(self, fixture(labels=("guild:qa",)))
        lines = Q.honesty_lines(h.p, CFG, role("DONE", ran=[], not_run=[]), [], ui=False)
        self.assertNotIn("사람의 시각 판단", " ".join(lines))

    def test_bypassed_marker_reaches_the_unattended_log(self):
        from workflows.dev import unattended_log as UL
        h = Harness(self, fixture())
        h.decisions.record({"point": "TEST", "stage": "test", "by": "judge:sonnet", "choice": "effective:C1",
                            "unsure": "false", "coerced": "false", "effective_check": "bypassed"})
        self.assertIn("effective_check: bypassed", UL.entries(h.gh.comments(7))[0])


# ---- K2 r3 decision: engine.effective.copy_ignored -----------------------------------------------

class R3CopyIgnored(unittest.TestCase):
    def mk(self):
        r = repo(self, {"lib/a.dart": "x\n", ".gitignore": "lib/env/\nassets/data.db\n.env\n"})
        os.makedirs(os.path.join(r, "lib", "env"))
        open(os.path.join(r, "lib", "env", "env.dart"), "w").write("const k = 1;")
        os.makedirs(os.path.join(r, "assets"))
        open(os.path.join(r, "assets", "data.db"), "w").write("db")
        open(os.path.join(r, ".env"), "w").write("TOKEN=x")
        return r

    def test_default_copies_nothing(self):
        r = self.mk()
        with EFF.TempTree(r, git(r, "rev-parse", "HEAD"), []) as tt:
            tt.copy_listed([])
            self.assertFalse(os.path.exists(os.path.join(tt.path, "assets", "data.db")))
            self.assertEqual(tt.copied, [])

    def test_listed_paths_copied_and_contained(self):
        r = self.mk()
        out = tmpdir(self)
        open(os.path.join(out, "secret"), "w").write("s")
        os.symlink(os.path.join(out, "secret"), os.path.join(r, "assets", "link.db"))
        with open(os.path.join(r, ".gitignore"), "a") as fh:
            fh.write("assets/link.db\n")
        with EFF.TempTree(r, git(r, "rev-parse", "HEAD"), []) as tt:
            tt.copy_listed(["assets/data.db", "lib/env/env.dart", "lib/a.dart", "../x", "/etc/hosts",
                            "lib/env/*.dart", "assets/link.db", "missing.txt"])
            self.assertEqual(tt.copied, ["assets/data.db", "lib/env/env.dart"])
            self.assertEqual(sorted(tt.refused), sorted(["lib/a.dart", "../x", "/etc/hosts", "lib/env/*.dart",
                                                         "assets/link.db", "missing.txt"]))
            self.assertTrue(os.path.exists(os.path.join(tt.path, "lib", "env", "env.dart")))
            self.assertFalse(os.path.exists(os.path.join(tt.path, ".env")))       # unlisted: still never copied

    def test_copied_only_after_the_networked_warm_up_and_logged(self):
        r = self.mk()
        with open(os.path.join(r, "calc_test.py"), "w") as fh:
            fh.write("import unittest\n\nclass T(unittest.TestCase):\n    def test_x(self):\n        self.assertEqual(f(), 1)\n")
        git(r, "add", "-A")
        git(r, "commit", "-qm", "t")
        h = Harness(self, fixture(), root=r, base=git(r, "rev-parse", "HEAD"))
        seen = []
        h.p.warm = lambda base, tree: seen.append(os.path.exists(os.path.join(tree, "assets", "data.db")))
        cfg = {"commands": {"test": "python3 -m unittest"}, "engine": {"effective": {"copy_ignored": ["assets/data.db"]}}}
        from guildcore.checks import CheckResult as CR
        h.checks = [CR(True, 0, False, "test_x (calc_test.T.test_x) ... ok\n\nRan 1 test in 0.0s\n\nOK\n", [], 60)]
        out, meta = EFF.run(h.p, cfg, ["C1"], {"C1": [{"test": "calc_test.py::T.test_x", "ac": "C1", "kind": "guard"}]},
                            h.p.base)
        self.assertEqual(seen, [False])                       # absent while the network is up
        self.assertEqual(meta["ignored_copied"], ["assets/data.db"])
        self.assertEqual(out["C1"].result, "pass")

    def test_engine_default_is_empty(self):
        from guildcore.config import ENGINE_DEFAULTS
        self.assertEqual(ENGINE_DEFAULTS["effective"], {"copy_ignored": []})

    def test_stored_rerun_output_is_redacted(self):
        src = open(os.path.join(_util.ENGINE, "workflows", "dev", "replay", "revert_subset.py"), encoding="utf-8").read()
        self.assertIn('CH.redact_lines(r.raw[-1500:])', src)
        o = EFF.CheckOutcome("C1", "t", "unverified", "secret-required: x")
        self.assertNotIn("raw", o.detail())                  # outcomes never carry run output


# ---- review r3 (review-k2-r3.md) -------------------------------------------------------------------

import base64  # noqa: E402

from guildcore.records import redact as RD  # noqa: E402


class R3M1WarmUp(unittest.TestCase):
    def test_hook_or_pubspec_change_skips_the_warm_up(self):
        r = repo(self, {"pubspec.yaml": "name: x\n", "lib/a.dart": "int f() => 1;\n",
                        "test/a_test.dart": "void main(){ test('t', (){ expect(f(), 1); }); }\n"})
        base = git(r, "rev-parse", "HEAD")
        os.makedirs(os.path.join(r, "hook"))
        with open(os.path.join(r, "hook", "build.dart"), "w") as fh:
            fh.write("void main(){}\n")
        with open(os.path.join(r, "lib", "a.dart"), "w") as fh:
            fh.write("int f() => 2;\n")
        git(r, "add", "-A")
        git(r, "commit", "-qm", "hook")
        h = Harness(self, fixture(), root=r, base=base)
        warmed = []
        h.p.warm = warmed.append
        out, meta = EFF.run(h.p, {"commands": {"test": "flutter test"}}, ["C1"],
                            {"C1": [{"test": "test/a_test.dart::t", "ac": "C1", "kind": "new"}]}, base)
        self.assertEqual(warmed, [])
        self.assertEqual(out["C1"].result, "unverified")
        self.assertTrue(out["C1"].why.startswith("build-inputs-changed: hook/build.dart"))
        self.assertEqual(EFF.hook_changes(r, base), ["hook/build.dart"])

    def test_pubspec_paths_count(self):
        for f in ("pubspec.yaml", "pubspec.lock", "pubspec_overrides.yaml", "packages/x/hook/build.dart"):
            self.assertTrue(EFF.HOOK_RE.search(f), f)
        self.assertFalse(EFF.HOOK_RE.search("lib/hooks.dart"))

    def test_warm_sandbox_cannot_touch_the_main_worktree(self):
        from workflows.dev.ports import warm_sandbox
        main = repo(self, {"a.txt": "x\n"})
        tree = repo(self, {"b.txt": "y\n"})
        run = tmpdir(self)
        sb = warm_sandbox(tree, run, main)
        real = os.path.realpath(main)
        self.assertIn(real + "/**", sb["filesystem"]["denyRead"])
        self.assertIn(real + "/**", sb["filesystem"]["denyWrite"])
        self.assertFalse([a for a in sb["filesystem"]["allowWrite"] if a.startswith(real + "/")])

    def test_harness_networked_step_has_no_secret_copies(self):
        src = open(os.path.join(_util.ENGINE, "workflows", "dev", "replay", "revert_subset.py"), encoding="utf-8").read()
        deps = src.index("CH.deps_step(")
        self.assertLess(deps, src.index("for g in GENERATED:"))       # ignored originals only after
        self.assertIn('["flutter pub get"]', src[deps:deps + 80])     # the developer tree: pub get only
        self.assertIn("warm_in_place(", src)                          # hooks run on pristine <base>


class R3M2Leakage(unittest.TestCase):
    SECRET = "AIzaSyD-not-a-real-key-0123456789"

    def setUp(self):
        RD.clear_exact()
        self.addCleanup(RD.clear_exact)

    def test_reviewer_base64_probe_and_hex(self):
        d = tmpdir(self)
        with open(os.path.join(d, "env.dart"), "w") as fh:
            fh.write('const apiKey = "%s";\nconst short = "abc";\n' % self.SECRET)
        self.assertGreater(RD.register_exact_from_files(d, ["env.dart"]), 0)
        line = 'apiKey = "%s"' % self.SECRET
        for leak in (self.SECRET, base64.b64encode(line.encode()).decode(), base64.b64encode(self.SECRET.encode()).decode(),
                     base64.urlsafe_b64encode(("ab" + self.SECRET).encode()).decode(), self.SECRET.encode().hex(),
                     self.SECRET.encode().hex().upper()):
            with self.subTest(leak=leak[:20]):
                self.assertIn("[REDACTED]", RD.redact("out: " + leak))
                self.assertTrue(RD.has_secret("out: " + leak))
        self.assertEqual(RD.redact("abc"), "abc")                    # short literals are not secrets

    def test_binary_files_are_skipped(self):
        d = tmpdir(self)
        with open(os.path.join(d, "data.db"), "wb") as fh:
            fh.write(b"SQLite format 3\0\"%s\"" % self.SECRET.encode())
        self.assertEqual(RD.register_exact_from_files(d, ["data.db"]), 0)

    def test_copy_list_posts_only_a_structured_summary(self):
        raw = ("00:01 +1: adds tax\n" + "secret line %s\n" % base64.b64encode(b"x" * 30).decode() +
               "00:02 +1 -1: rounds [E]\n00:02 +1 -1: Some tests failed.\n")
        h = Harness(self, fixture(), roles=[role("DONE", covers=[], e2e="E2E 불요: x")],
                    suites=[suite(raw, passed=False, rc=1)],
                    config=dict(CFG, engine={"effective": {"copy_ignored": ["lib/env/env.dart"]}}))
        T.run(h.p)
        out = h.body_with("test:output")
        self.assertNotIn("secret line", out)
        self.assertIn("exit: red", out)
        self.assertIn("pass: test#1", out)          # r4: names not statically cited are numbered
        self.assertIn("fail: test#2", out)
        self.assertNotIn("adds tax", out)

    def test_without_copy_list_the_tail_is_posted(self):
        raw = "00:01 +1: adds tax\nnote: hello\n00:02 +2: All tests passed!\n"
        h = Harness(self, fixture(), roles=[role("DONE", covers=[], e2e="E2E 불요: x")],
                    suites=[suite(raw, passed=False, rc=1)])
        T.run(h.p)
        self.assertIn("note: hello", h.body_with("test:output"))

    def test_checks_profile_network(self):
        from guildcore import checks as CHK
        prof = CHK.sandbox_profile({"filesystem": {}})
        self.assertIn('(allow network-outbound (remote ip "localhost:*"))', prof)
        self.assertNotIn("(allow network-outbound (remote unix-socket", prof)   # measured: flutter needs none
        self.assertIn('(deny network-outbound (remote ip "localhost:1080"))', prof)
        self.assertLess(prof.index('localhost:*'), prof.index('localhost:1080'))   # last rule wins


class R3Minors(unittest.TestCase):
    def test_m1_prose_bullets_and_non_case_tables(self):
        self.assertEqual(CS.case_ids("## 1. 개요\n## 2. 공통 전제\n- V2: API 버전\n| 코덱 | 비고 |\n|---|---|\n"
                                     "| H264 | x |\n| H265 | y |\n"), [])
        self.assertEqual(CS.case_ids("## 테스트 케이스\n- C1: a\n- C2: b\n"), ["C1", "C2"])

    def test_m3_temp_tree_prefix_is_not_fixed(self):
        r = repo(self, {"a.txt": "x\n"})
        with EFF.TempTree(r, git(r, "rev-parse", "HEAD"), []) as tt:
            self.assertNotIn("gld-eff", tt.path)
        src = open(os.path.join(_util.ENGINE, "workflows", "dev", "judges", "TEST.md"), encoding="utf-8").read()
        self.assertIn("existsSync", src)


# ---- review r4 (review-k2-r4.md) -------------------------------------------------------------------

from guildcore.checks import CheckResult as _CR  # noqa: E402


def _commit(r, files, msg="c"):
    for rel, text in files.items():
        p_ = os.path.join(r, rel)
        os.makedirs(os.path.dirname(p_), exist_ok=True)
        with open(p_, "w") as fh:
            fh.write(text)
    git(r, "add", "-A")
    git(r, "commit", "-qm", msg)
    return git(r, "rev-parse", "HEAD")


class R4M1WarmUp(unittest.TestCase):
    def test_build_inputs_cover_test_config_hooks_and_pubspec(self):
        for f in ("test/flutter_test_config.dart", "flutter_test_config.dart", "packages/x/test/flutter_test_config.dart",
                  "hook/build.dart", "pubspec.lock", "pubspec_overrides.yaml"):
            self.assertTrue(EFF.HOOK_RE.search(f), f)
        for f in ("lib/build_utils.dart", "test/a_test.dart", "build.yaml", "analysis_options.yaml"):   # r6: not inputs
            self.assertFalse(EFF.HOOK_RE.search(f), f)

    def test_test_config_change_skips_the_warm_up(self):
        r = repo(self, {"pubspec.yaml": "name: x\n", "lib/a.dart": "int f() => 1;\n",
                        "test/a_test.dart": "void main(){ test('t', (){ expect(f(), 1); }); }\n"})
        base = git(r, "rev-parse", "HEAD")
        _commit(r, {"test/flutter_test_config.dart": "Future<void> testExecutable(f) async => f();\n",
                    "lib/a.dart": "int f() => 2;\n"})
        h = Harness(self, fixture(), root=r, base=base)
        warmed = []
        h.p.warm = lambda b, t: warmed.append(b)
        out, meta = EFF.run(h.p, {"commands": {"test": "flutter test"}}, ["C1"],
                            {"C1": [{"test": "test/a_test.dart::t", "ac": "C1", "kind": "new"}]}, base)
        self.assertEqual(warmed, [])
        self.assertEqual(out["C1"].why, "build-inputs-changed: test/flutter_test_config.dart")

    def test_warm_up_runs_on_a_pristine_base_then_the_tree_moves_to_head(self):
        from workflows.dev import ports as PT
        r = repo(self, {"pubspec.yaml": "name: x\n", "lib/a.dart": "int f() => 1;\n", "lib/old.dart": "o\n",
                        "test/a_test.dart": "void main(){ test('t', (){ expect(f(), 2); }); }\n",
                        ".gitignore": "lib/env/\n.dart_tool/\nassets/data.db\n"})
        base = git(r, "rev-parse", "HEAD")
        _commit(r, {"lib/a.dart": "int f() => 2; // developer code\n", "lib/new.dart": "n\n"})
        os.remove(os.path.join(r, "lib", "old.dart"))
        git(r, "commit", "-qam", "rm")
        os.makedirs(os.path.join(r, "lib", "env"))
        open(os.path.join(r, "lib", "env", "env.dart"), "w").write("const k = 'AIzaSy-secret-value-1234567';\n")
        seen = {}
        calls = []

        def fake_deps(cmds, tree, sb, tmp, env=None, hosts=None, timeout_s=1800):
            calls.append(cmds)
            if len(calls) == 1:
                seen.update(cmds=cmds, a=open(os.path.join(tree, "lib", "a.dart")).read(),
                            git=os.path.exists(os.path.join(tree, ".git")),
                            env=os.path.exists(os.path.join(tree, "lib", "env", "env.dart")),
                            deny=sb["filesystem"]["denyRead"])
                os.makedirs(os.path.join(tree, ".dart_tool", "hooks_runner"))
                return _CR(False, 1, False, "No file or variants found for asset: assets/data.db.\n", [], 60), {"a": 1}
            seen["placeholder"] = os.path.getsize(os.path.join(tree, "assets", "data.db"))
            os.makedirs(os.path.join(tree, "build", "unit_test_assets", "assets"))     # bundle with the placeholder
            os.makedirs(os.path.join(tree, "build", "native_assets"))
            return _CR(True, 0, False, "00:00 +1: All tests passed!\n", [], 60), {"a": 1}
        orig = PT.CH.deps_step
        PT.CH.deps_step = fake_deps
        try:
            h = Harness(self, fixture(), root=r, base=base)
            run_dir = tmpdir(self)
            for d in ("in", "out", "tmp"):
                os.makedirs(os.path.join(run_dir, d))
            trees = []

            def warm(b, tree):
                self.assertEqual(b, base)
                trees.append(tree)
                res, px = PT.warm_in_place(r, tree, run_dir, dict(os.environ))
                seen["px"] = px
                return res
            h.p.warm = warm
            h.checks = [_CR(True, 0, False, "00:01 +1: t\n00:01 +1: All tests passed!\n", [], 60),
                        _CR(False, 1, False, "  Expected: <2>\n    Actual: <1>\n00:01 +0 -1: t [E]\n00:01 +0 -1: Some tests failed.\n",
                            [], 60)]
            snap = {}
            orig_check = h._check

            def check(cmd, cwd, owner, timeout_s, write_dirs):
                if not snap:
                    snap.update(a=open(os.path.join(cwd, "lib", "a.dart")).read(),
                                new=os.path.exists(os.path.join(cwd, "lib", "new.dart")),
                                old=os.path.exists(os.path.join(cwd, "lib", "old.dart")),
                                hooks=os.path.isdir(os.path.join(cwd, ".dart_tool", "hooks_runner")),
                                warmdir=os.path.exists(os.path.join(cwd, "guild_engine_warmup")),
                                db=os.path.exists(os.path.join(cwd, "assets", "data.db")),
                                bundle=os.path.exists(os.path.join(cwd, "build", "unit_test_assets")),
                                native=os.path.exists(os.path.join(cwd, "build", "native_assets")))
                return orig_check(cmd, cwd, owner, timeout_s, write_dirs)
            h.p.check = check
            out, meta = EFF.run(h.p, {"commands": {"test": "flutter test"}}, ["C1"],
                                {"C1": [{"test": "test/a_test.dart::t", "ac": "C1", "kind": "new"}]}, base)
        finally:
            PT.CH.deps_step = orig
        self.assertEqual(seen["a"], "int f() => 1;\n")                # <base>, not the developer's HEAD
        self.assertFalse(seen["git"])                                  # no link to the git dir
        self.assertFalse(seen["env"])                                  # no ignored file
        self.assertEqual(seen["cmds"][1], "flutter test --no-pub guild_engine_warmup/warmup_test.dart")
        self.assertIn(os.path.realpath(r) + "/**", seen["deny"])
        self.assertEqual(seen["placeholder"], 0)                       # an EMPTY engine-written placeholder
        self.assertEqual(seen["px"]["placeholders"], ["assets/data.db"])
        self.assertEqual(snap, {"a": "int f() => 2; // developer code\n", "new": True, "old": False, "hooks": True,
                                "warmdir": False, "db": False, "bundle": False, "native": True})   # r5: stale bundle dropped        # HEAD, warm artifacts kept, no leftovers
        self.assertEqual(out["C1"].result, "pass")

    def test_root_test_config_at_base_skips(self):
        from workflows.dev import ports as PT
        r = repo(self, {"pubspec.yaml": "name: x\n", "flutter_test_config.dart": "x\n"})
        res, px = PT.warm_in_place(r, r, tmpdir(self), dict(os.environ))
        self.assertIsNone(res)
        self.assertIn("skipped", px)


class R4M2Unreachable(unittest.TestCase):
    def test_tree_sandbox_denies_every_checkout_and_the_common_dir(self):
        from workflows.dev.ports import tree_sandbox
        main = repo(self, {"a.txt": "x\n", ".gitignore": "node_modules/\n"})
        linked = os.path.join(tmpdir(self), "wt")
        git(main, "worktree", "add", "-q", "--detach", linked)
        os.makedirs(os.path.join(main, "node_modules", "dep"))
        with EFF.TempTree(main, None, []) as tt:
            sb = tree_sandbox(tt.path, tmpdir(self), linked)          # the engine running in a LINKED worktree
            fs = sb["filesystem"]
            for root in (main, linked, os.path.join(main, ".git")):
                self.assertIn(os.path.realpath(root) + "/**", fs["denyRead"], root)
                self.assertIn(os.path.realpath(root) + "/**", fs["denyWrite"], root)
            self.assertFalse([a for a in fs["allowWrite"] if a.startswith(os.path.realpath(main) + "/")])
            self.assertIn(os.path.realpath(tt.path) + "/**", fs["allowWrite"])
            self.assertEqual(fs["allowRead"], [os.path.realpath(os.path.join(main, "node_modules")) + "/**"])
            self.assertFalse(os.path.exists(os.path.join(tt.path, ".git")))
        with self.assertRaises(ValueError):
            tree_sandbox(os.path.join(main, "sub"), tmpdir(self), main)

    def test_suite_tree_overlays_uncommitted_non_ignored_files_only(self):
        r = repo(self, {"a.dart": "1\n", "gone.dart": "x\n", ".gitignore": ".env\n"})
        open(os.path.join(r, "a.dart"), "w").write("2\n")             # uncommitted edit
        open(os.path.join(r, "new_test.dart"), "w").write("t\n")      # untracked, not ignored
        open(os.path.join(r, ".env"), "w").write("SECRET=1\n")        # ignored
        os.remove(os.path.join(r, "gone.dart"))
        with EFF.TempTree(r, None, [], overlay=True) as tt:
            self.assertEqual(open(os.path.join(tt.path, "a.dart")).read(), "2\n")
            self.assertTrue(os.path.exists(os.path.join(tt.path, "new_test.dart")))
            self.assertFalse(os.path.exists(os.path.join(tt.path, ".env")))
            self.assertFalse(os.path.exists(os.path.join(tt.path, "gone.dart")))
            self.assertEqual(tt.skipped_ignored, [".env"])

    def test_profile_denies_launchservices_open_and_listening_ports(self):
        prof = CH.sandbox_profile({}, deny_ports=[45678, 3128], allow_ports=[3128])
        self.assertIn("(deny appleevent-send)", prof)
        self.assertIn("(deny mach-lookup (global-name-regex", prof)
        self.assertIn("launchservicesd", prof)
        self.assertIn('(literal "/usr/bin/open")', prof)
        for port in (45678, 8080, 9090, 2375, 2376, 5432, 6379, 3306, 27017, 11434, 10808, 6152):
            self.assertIn('(deny network-outbound (remote ip "localhost:%d"))' % port, prof)
        self.assertNotIn('"localhost:3128"))', prof.split("(allow network-outbound")[1].replace(
            '(deny network-outbound (remote ip "localhost:3128"))', ""))   # the engine's own proxy port stays open
        self.assertNotIn("(deny network-outbound)\n", prof)              # the inert filter-less form (measured)

    @unittest.skipUnless(os.path.exists(CH.SANDBOX_EXEC), "sandbox-exec only on macOS")
    def test_live_probe_lsappinfo_open_and_a_listening_port(self):
        import socket
        d = tmpdir(self)
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen()
        self.addCleanup(srv.close)
        port = srv.getsockname()[1]
        prof = os.path.join(d, "p.sb")
        with open(prof, "w") as fh:
            fh.write(CH.sandbox_profile({}, deny_ports=CH.listening_ports()))
        run = lambda *a: subprocess.run([CH.SANDBOX_EXEC, "-f", prof] + list(a), stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, timeout=60)
        p1 = run("/usr/bin/lsappinfo", "info", "-only", "name", "Finder")      # the reviewer's probe
        self.assertNotEqual(p1.returncode, 0)
        self.assertNotIn(b"LSDisplayName", p1.stdout)
        shutil.copy("/usr/bin/lsappinfo", os.path.join(d, "lsa"))              # a copy: the mach deny holds
        p2 = run(os.path.join(d, "lsa"), "info", "-only", "name", "Finder")
        self.assertNotIn(b"LSDisplayName", p2.stdout)
        self.assertNotEqual(run("/usr/bin/open", "-g", "x-guild-probe://x").returncode, 0)
        code = ("import socket,sys\n"
                "try:\n socket.create_connection(('127.0.0.1',%d),timeout=3);print('LISTENER-REACHED')\n"
                "except OSError: print('blocked')\n"
                "s=socket.socket();s.bind(('127.0.0.1',0));s.listen();socket.create_connection(s.getsockname());"
                "print('own-port-ok')\n" % port)
        p3 = run(sys_exe(), "-c", code)
        self.assertIn(b"blocked", p3.stdout)
        self.assertIn(b"own-port-ok", p3.stdout)                               # flutter's own ports keep working

    def test_summary_prints_only_statically_cited_names(self):
        raw = ("00:01 +1: A\n00:01 +2: I\n00:01 +3: z\n00:01 +4: ko 본문에 버튼 역할어가 없다\n00:02 +4: All tests passed!\n")
        r = _CR(True, 0, False, raw, [], 60)
        out = T.structured_summary(r, CH.parse_summary(raw, "flutter"), "flutter", ["본문에 버튼 역할어가 없다"])
        self.assertIn("pass: 본문에 버튼 역할어가 없다", out)
        self.assertNotIn("ko ", out)                                           # the dynamic group prefix is dropped
        for i, ch in ((1, "A"), (2, "I"), (3, "z")):
            self.assertIn("pass: test#%d" % i, out)
            self.assertNotIn(": %s\n" % ch, out + "\n")

    def test_cited_literals_require_the_name_in_source(self):
        h = Harness(self, fixture())
        h.write_file("test/a_test.dart", "void main(){ test('real name', (){}); for (final c in k.split('')) test(c, (){}); }\n")
        got = T.cited_literals(h.p, [{"test": "test/a_test.dart::real name"}, {"test": "test/a_test.dart::AIza"}])
        self.assertEqual(got, ["real name"])

    def test_exact_values_are_scoped_to_the_run(self):
        RD.clear_exact()
        d = tmpdir(self)
        open(os.path.join(d, "e.dart"), "w").write('const k = "previous-repo-secret-0123456789";\n')
        RD.register_exact_from_files(d, ["e.dart"])
        self.assertIn("[REDACTED]", RD.redact("previous-repo-secret-0123456789"))
        h = Harness(self, fixture(), roles=[role("DONE", covers=[], e2e="E2E 불요: x")],
                    suites=[suite("00:01 +0 -1: x [E]\n00:01 +0 -1: Some tests failed.\n", passed=False, rc=1)])
        T.run(h.p)
        self.assertEqual(RD.redact("previous-repo-secret-0123456789"), "previous-repo-secret-0123456789")


def sys_exe():
    import sys
    return sys.executable


class R4M3TestOnly(unittest.TestCase):
    TEST = "void main(){ test('원격이 비어 있으면 업로드한다', (){ expect(sync(), 1); }); }\n"

    def _issue(self, files):
        r = repo(self, {"lib/sync.dart": "int sync() => 1;\n", "test/old_test.dart": "void main(){}\n"})
        base = git(r, "rev-parse", "HEAD")
        _commit(r, files, "test: (#1891)")
        return r, base

    def test_impl_excludes_docs_and_tests(self):
        r, base = self._issue({"test/sync_test.dart": self.TEST, "docs/specs/1891/test-cases.md": "| C1 | a |\n",
                               "design/notes.md": "x\n", "README.md": "y\n"})
        files, src, bad = EFF.impl_files(r, base)
        self.assertEqual((files, src, bad), ([], "derived", []))
        files, src, _bad = EFF.impl_files(r, base, ["docs/specs/1891/test-cases.md", "test/sync_test.dart"])
        self.assertEqual((files, src), ([], "result"))                 # the developer's list is filtered too
        self.assertTrue(EFF.is_impl("lib/sync.dart"))

    def _run(self, files, given=None):
        r, base = self._issue(files)
        h = Harness(self, fixture(), root=r, base=base, impl_files=given)
        h.checks = [_CR(True, 0, False, "00:01 +1: 원격이 비어 있으면 업로드한다\n00:01 +1: All tests passed!\n", [], 60)]
        return h, EFF.run(h.p, {"commands": {"test": "flutter test"}}, ["C1"],
                          {"C1": [{"test": "test/sync_test.dart::원격이 비어 있으면 업로드한다", "ac": "C1", "kind": "new"}]},
                          base, given)

    def test_1891_shape_is_na_test_only(self):
        h, (out, meta) = self._run({"test/sync_test.dart": self.TEST, "docs/specs/1891/test-cases.md": "| C1 | a |\n"})
        self.assertEqual((out["C1"].result, out["C1"].why), ("n/a", "test-only"))
        self.assertEqual(out["C1"].as_field(), "C1=n/a(test-only)")
        self.assertTrue(meta["test_only"])
        self.assertEqual(len(h.calls["checks"]), 1)                    # the HEAD run only — nothing reverted

    def test_1895_shape_two_tests_and_docs_listed_by_the_developer(self):
        _h, (out, meta) = self._run({"test/sync_test.dart": self.TEST, "test/lang_test.dart": "void main(){}\n",
                                     "docs/specs/1895/design.md": "x\n"},
                                    given=["docs/specs/1895/design.md", "test/lang_test.dart"])
        self.assertEqual(out["C1"].result, "n/a")
        self.assertEqual(meta["impl_source"], "result")

    def test_stage_advances_and_records_na(self):
        r, base = self._issue({"test/sync_test.dart": self.TEST, "docs/specs/7/test-cases.md": "| C1 | a |\n"})
        covers = [{"test": "test/sync_test.dart::원격이 비어 있으면 업로드한다", "ac": "C1", "kind": "new"}]
        h = Harness(self, fixture(), root=r, base=base, roles=[role("DONE", covers=covers, e2e="E2E 불요: x")],
                    judges={"TEST": [judge_test(["C1"])]}, suites=[suite(FLUTTER_GREEN)])
        h.checks = [_CR(True, 0, False, "00:01 +1: 원격이 비어 있으면 업로드한다\n00:01 +1: All tests passed!\n", [], 60)]
        res = T.run(h.p)
        self.assertEqual(res.token(), "OK ADVANCE: qa")
        blk = [b for b in DecisionLog.load(h.gh.comments(7)).blocks if b.get("point") == "TEST"][0]
        self.assertEqual(blk.get("checks"), "C1=n/a(test-only)")
        self.assertEqual(blk.get("effective_check"), "n/a(test-only)")
        self.assertIsNone(blk.get("grade"))
        self.assertIn("effective (n/a: test-only)", h.body_with("test:output"))


class R4LoopFamilies(unittest.TestCase):
    def test_group_per_language_family_counts_as_one(self):
        green = ("00:01 +0: ko 세 키가 모두 있다\n00:01 +1: ja 세 키가 모두 있다\n00:01 +2: en 세 키가 모두 있다\n"
                 "00:01 +3: All tests passed!\n")
        self.assertEqual(EFF.rerun_kind(green, "flutter", "세 키가 모두 있다", True), "passed")
        red = ("00:01 +0: ko 세 키가 모두 있다\n00:01 +1: ja 세 키가 모두 있다\n  Expected: 'x'\n    Actual: <null>\n"
               "00:01 +1 -1: ja 세 키가 모두 있다 [E]\n00:01 +2 -1: en 세 키가 모두 있다\n00:01 +2 -1: Some tests failed.\n")
        self.assertEqual(EFF.rerun_kind(red, "flutter", "세 키가 모두 있다", False), "assertion")

    def test_identical_names_across_iterations(self):
        raw = ("00:01 +0: signout 상한을 넘겨 정리 부채가 남는다\n00:01 +1: signout 상한을 넘겨 정리 부채가 남는다\n"
               "00:01 +2: All tests passed!\n")
        self.assertEqual(EFF.rerun_kind(raw, "flutter", "상한을 넘겨 정리 부채가 남는다", True), "passed")

    def test_other_tests_in_the_run_stay_ambiguous(self):
        raw = "00:01 +0: ko 세 키\n00:01 +1: 다른 테스트\n00:01 +2: All tests passed!\n"
        self.assertEqual(EFF.rerun_kind(raw, "flutter", "세 키", True), "ambiguous")


# ---- review r5 (review-k2-r5.md) -------------------------------------------------------------------

from workflows.dev import preflight as PF  # noqa: E402
from workflows.dev.stages import base as SB  # noqa: E402


class R5M2ImplFromDiff(unittest.TestCase):
    def _repo(self):
        r = repo(self, {"calc.py": "x=1\n", "README.md": "a\n", "test_calc.py": "t\n"})
        base = git(r, "rev-parse", "HEAD")
        _commit(r, {"calc.py": "x=2\n", "README.md": "b\n"})
        return r, base

    def test_docs_only_impl_files_do_not_switch_the_check_off(self):
        r, base = self._repo()
        d = EFF.impl_detail(r, base, ["README.md"])          # the reviewer's probe
        self.assertEqual(d["files"], ["calc.py"])
        self.assertEqual(d["mismatch"], {"given_only": [], "diff_only": ["calc.py"]})
        self.assertEqual(d["source"], "derived(impl_files mismatch)")
        h = Harness(self, fixture(), root=r, base=base)
        h.checks = [_CR(True, 0, False, "test_x (test_calc.T.test_x) ... ok\n\nRan 1 test in 0.0s\n\nOK\n", [], 60),
                    _CR(True, 0, False, "test_x (test_calc.T.test_x) ... ok\n\nRan 1 test in 0.0s\n\nOK\n", [], 60)]
        h.write_file("test_calc.py", "import unittest\n\nclass T(unittest.TestCase):\n    def test_x(self):\n        self.assertEqual(f(), 2)\n")
        out, meta = EFF.run(h.p, {"commands": {"test": "python3 -m unittest"}}, ["C1"],
                            {"C1": [{"test": "test_calc.py::T.test_x", "ac": "C1", "kind": "new"}]}, base, ["README.md"])
        self.assertFalse(meta["test_only"])
        self.assertNotEqual(out["C1"].result, "n/a")
        self.assertEqual(out["C1"].result, "unsure")               # reverted calc.py, still passes
        self.assertEqual(meta["impl_given_mismatch"]["diff_only"], ["calc.py"])

    def test_agreeing_list_is_the_result(self):
        r, base = self._repo()
        self.assertEqual(EFF.impl_detail(r, base, ["calc.py", "README.md"])["source"], "result")
        self.assertIsNone(EFF.impl_detail(r, base, ["calc.py"])["mismatch"])

    def test_mismatch_field(self):
        self.assertEqual(T._mismatch_field({"given_only": ["a.py"], "diff_only": []}), "given_only=a.py;diff_only=none")
        self.assertIsNone(T._mismatch_field(None))


class R5M1AllListeners(unittest.TestCase):
    NETSTAT = ("Active Internet connections (including servers)\n"
               "Proto Recv-Q Send-Q  Local Address          Foreign Address        (state)      rhiwat\n"
               "tcp4       0      0  127.0.0.1.8021         *.*                    LISTEN       0 0 131072 131072 x:1\n"
               "tcp6       0      0  ::1.8021               *.*                    LISTEN       0 0 131072 131072 x:1\n"
               "tcp46      0      0  *.21300                *.*                    LISTEN       0 0 131072 131072 y:2\n"
               "tcp4       0      0  127.0.0.1.31026        *.*                    LISTEN       0 0 131072 131072 z:3\n"
               "tcp4       0      0  127.0.0.1.50000        127.0.0.1.31027        ESTABLISHED  0 0 1 1 q:4\n")

    def test_netstat_parser(self):
        self.assertEqual(sorted(CH.parse_netstat(self.NETSTAT)), [8021, 21300, 31026])

    def test_union_and_fail_closed(self):
        orig = CH._cmd
        try:
            CH._cmd = lambda argv: self.NETSTAT if "netstat" in argv[0] else "p1\nf3\nn127.0.0.1:16105\n"
            self.assertEqual(CH.listening_ports(), [8021, 16105, 21300, 31026])
            CH._cmd = lambda argv: None
            with self.assertRaises(CH.PortsUnreadable):
                CH.listening_ports()
        finally:
            CH._cmd = orig

    def test_live_ports_include_other_users_listeners(self):
        if not os.path.exists("/usr/sbin/netstat"):
            self.skipTest("netstat")
        ns = CH.parse_netstat(CH._cmd(["/usr/sbin/netstat", "-anv", "-p", "tcp"]))
        self.assertTrue(ns <= set(CH.listening_ports()))


class R5B1Suite(unittest.TestCase):
    def _dart_repo(self):
        return repo(self, {"pubspec.yaml": "name: app\nflutter:\n  assets:\n    - assets/data.db\n    - assets/images/\n",
                           ".gitignore": "lib/env/\nassets/data.db\nlib/fb.dart\n",
                           "lib/a.dart": "import 'package:app/env/env.dart';\nint f() => k;\n",
                           "lib/main.dart": "import 'fb.dart';\nimport 'a.dart';\n",
                           "test/a_test.dart": "import 'package:app/a.dart';\nvoid main(){}\n",
                           "integration_test/app_test.dart": "import 'package:app/main.dart';\n",
                           "assets/images/x.png": "p"})

    def test_preflight_finds_what_the_tests_need(self):
        r = self._dart_repo()
        self.assertEqual(PF.ignored_needed(r), ["assets/data.db", "lib/env/env.dart"])   # not lib/fb.dart (main/e2e only)
        self.assertEqual(PF.ignored_needed(r, ["lib/env", "assets/data.db"]), [])
        self.assertEqual(PF.ignored_needed(repo(self, {"a.py": "x\n"})), [])

    def test_stage_halts_at_preflight_without_running_anything(self):
        r = self._dart_repo()
        h = Harness(self, fixture(), root=r, roles=[], suites=[])
        h.write_file("docs/specs/7/test-cases.md", "| C1 | a |\n")
        res = T.run(h.p)
        self.assertEqual(res.kind, res.FAIL)
        self.assertEqual(res.fail_class, "prevalidate_env")
        self.assertTrue(res.notes[0].startswith("halted: env ignored-missing — assets/data.db, lib/env/env.dart"))
        self.assertIn("engine.effective.copy_ignored", res.line)
        self.assertEqual(h.calls["suites"], [])
        self.assertNotIn("guild:needs-human", h.labels())
        self.assertIn("ignored-missing", SB.ENV_HALT_REASONS)

    def test_red_suite_naming_an_ignored_path_halts_not_loops(self):
        red = suite("00:01 +0: loading x\nlib/a.dart:1:8: Error: Error when reading 'lib/env/env.dart': No such file\n"
                    "00:01 +0 -1: Some tests failed.\n", passed=False, rc=1)
        red.missing_ignored = ["lib/env/env.dart"]
        h = Harness(self, fixture(), roles=[], suites=[red])
        res = T.run(h.p)
        self.assertEqual((res.kind, res.fail_class), (res.FAIL, "prevalidate_env"))
        self.assertIn("halted: env ignored-missing — lib/env/env.dart", res.notes[0])
        self.assertIsNone(h.body_with("test:output"))
        self.assertNotIn("guild:needs-human", h.labels())

    def test_missing_ignored_classifier(self):
        r = self._dart_repo()
        raw = ("/tmp/T/lib/a.dart:1:8: Error: Error when reading '/tmp/T/lib/env/env.dart': No such file or directory\n"
               "No file or variants found for asset: assets/data.db.\nlib/real.dart:3: Error: x\n")
        self.assertEqual(PF.missing_ignored(raw, r, [], "/tmp/T"), ["assets/data.db", "lib/env/env.dart"])
        self.assertEqual(PF.missing_ignored("Expected: 1\n  Actual: 2\n", r, ["lib/env/"], "/tmp/T"), [])
        self.assertEqual(PF.missing_ignored("cannot open 'lib/env/env.dart'", r, ["lib/env/"], None), ["lib/env"])
        self.assertEqual(PF.missing_ignored("environment ok", r, [".env"], None), [])

    @unittest.skipUnless(os.path.exists(CH.SANDBOX_EXEC), "sandbox-exec only on macOS")
    def test_suite_in_tree_cannot_read_the_checkout(self):
        from workflows.dev import ports as PT
        r = repo(self, {"a.txt": "tracked\n", ".gitignore": ".env\n"})
        open(os.path.join(r, ".env"), "w").write("SECRET=AIzaSy-very-secret-000\n")
        open(os.path.join(r, "b.txt"), "w").write("untracked\n")
        run_dir = tmpdir(self)
        for d in ("in", "out", "tmp"):
            os.makedirs(os.path.join(run_dir, d))
        res = PT.suite_in_tree(r, None, ["pwd; cat a.txt b.txt; cat %s/.env; cat .env" % r], "tester", 60, run_dir,
                               dict(os.environ))
        self.assertFalse(res.passed)
        self.assertIn("tracked", res.raw)
        self.assertIn("untracked", res.raw)                                # the overlay
        self.assertNotIn("AIzaSy", res.raw)                                # neither the tree copy nor the original
        self.assertIn(".env", res.missing_ignored)
        self.assertEqual(res.warm, "skipped(no base)")
        self.assertIn(r, res.raw)                                          # temp paths shown as the worktree


class R5Minors(unittest.TestCase):
    def test_family_needs_one_call_site_inside_a_loop(self):
        loop = "void main(){ for (final l in ['ko','ja']) { group(l, () { test('세 키', () { expect(1, 2); }); }); } }"
        two = "void main(){ group('a', (){ test('세 키', (){}); }); group('b', (){ test('세 키', (){ expect(1, 2); }); }); }"
        cfor = "void main(){ for (var i = 0; i < 2; i++) { test('n', (){}); } }"
        self.assertTrue(EFF.loop_site(loop, "세 키"))
        self.assertFalse(EFF.loop_site(two, "세 키"))
        self.assertTrue(EFF.loop_site(cfor, "n"))
        self.assertFalse(EFF.loop_site("x.forEach(print); group('a', (){ test('n', (){}); });", "n"))
        raw = "00:01 +0: a 세 키\n00:01 +1: b 세 키\n00:01 +2: All tests passed!\n"
        self.assertEqual(EFF.rerun_kind(raw, "flutter", "세 키", True, family=False), "ambiguous")
        self.assertEqual(EFF.rerun_kind(raw, "flutter", "세 키", True, family=True), "passed")

    def test_warm_status_and_warm_failed_reason(self):
        self.assertEqual(EFF.warm_status(None)[:7], "skipped")
        self.assertEqual(EFF.warm_status(_CR(True, 0, False, "", [], 60)), "ok")
        self.assertTrue(EFF.warm_status(_CR(False, 1, False, "x\nBuilding native assets failed.\n", [], 60))
                        .startswith("failed(Building native assets failed."))
        r = repo(self, {"pubspec.yaml": "name: x\n", "lib/a.dart": "int f() => 1;\n",
                        "test/a_test.dart": "void main(){ test('t', (){ expect(f(), 2); }); }\n"})
        base = git(r, "rev-parse", "HEAD")
        _commit(r, {"lib/a.dart": "int f() => 2;\n"})
        h = Harness(self, fixture(), root=r, base=base)
        h.p.warm = lambda b, t: _CR(False, 1, False, "Building native assets failed.\n", [], 60)
        h.checks = [_CR(False, 1, False, "Building native assets failed.\n00:01 +0 -1: Some tests failed.\n", [], 60)]
        out, meta = EFF.run(h.p, {"commands": {"test": "flutter test"}}, ["C1"],
                            {"C1": [{"test": "test/a_test.dart::t", "ac": "C1", "kind": "new"}]}, base)
        self.assertTrue(meta["warm"].startswith("failed("))
        self.assertEqual(out["C1"].why, "warm-up failed: Building native assets failed.")


class R5OfflineSuiteCommand(unittest.TestCase):
    def test_flutter_test_gets_no_pub(self):
        from workflows.dev.ports import offline_cmd
        self.assertEqual(offline_cmd("flutter test --fail-fast --concurrency=12"),
                         "flutter test --no-pub --fail-fast --concurrency=12")
        self.assertEqual(offline_cmd("fvm flutter test"), "fvm flutter test --no-pub")
        for same in ("flutter test --no-pub x", "scripts/verify_test_coverage.sh r.json", "npm test", "flutter testx"):
            self.assertEqual(offline_cmd(same), same)


# ---- review r6 (review-k2-r6.md) -------------------------------------------------------------------

PUB = "name: app\ndependencies:\n  flutter:\n    sdk: flutter\n  sqlite3: ^2.0.0\n"
LOCK = "packages:\n  sqlite3:\n    dependency: direct main\n    source: hosted\n    version: \"2.0.0\"\n"


class R6BuildInputs(unittest.TestCase):
    def _repo(self, extra=None):
        files = {"pubspec.yaml": PUB, "pubspec.lock": LOCK, "lib/a.dart": "int f() => 1;\n",
                 "test/a_test.dart": "void main(){ test('t', (){ expect(f(), 2); }); }\n"}
        files.update(extra or {})
        r = repo(self, files)
        return r, git(r, "rev-parse", "HEAD")

    def test_analysis_options_only_warms_base(self):
        r, base = self._repo({"analysis_options.yaml": "a\n"})
        _commit(r, {"analysis_options.yaml": "b\n", "build.yaml": "x\n"})
        self.assertEqual(EFF.build_inputs(r, base), ("none", []))

    def test_hosted_dependency_add_warms_the_head_copy(self):
        r, base = self._repo()
        _commit(r, {"pubspec.yaml": PUB + "  http: ^1.2.0\n",
                    "pubspec.lock": LOCK + "  http:\n    dependency: direct main\n    source: hosted\n    version: \"1.2.0\"\n",
                    "lib/a.dart": "int f() => 2;\n"})
        self.assertEqual(EFF.build_inputs(r, base), ("hosted-deps", ["pubspec.lock", "pubspec.yaml"]))
        h = Harness(self, fixture(), root=r, base=base)
        seen = []

        def warm(rev, tree):
            seen.append((rev, open(os.path.join(tree, "pubspec.yaml")).read().count("http"),
                         open(os.path.join(tree, "lib", "a.dart")).read()))
            return _CR(True, 0, False, "", [], 60)
        h.p.warm = warm
        h.checks = [_CR(True, 0, False, "00:01 +1: t\n00:01 +1: All tests passed!\n", [], 60),
                    _CR(False, 1, False, "  Expected: <2>\n    Actual: <1>\n00:01 +0 -1: t [E]\n00:01 +0 -1: Some tests failed.\n",
                        [], 60)]
        out, meta = EFF.run(h.p, {"commands": {"test": "flutter test"}}, ["C1"],
                            {"C1": [{"test": "test/a_test.dart::t", "ac": "C1", "kind": "new"}]}, base)
        self.assertEqual(seen, [("HEAD", 1, "int f() => 2;\n")])
        self.assertEqual(meta["warm"], "ok")
        self.assertEqual(out["C1"].result, "pass")

    def test_non_hosted_changes_are_other(self):
        cases = [
            ({"pubspec.yaml": PUB + "  mine:\n    path: ../mine\n"}, None),
            ({"pubspec.yaml": PUB + "  g:\n    git: https://x/y.git\n"}, None),
            ({"pubspec.yaml": PUB + "dependency_overrides:\n  sqlite3: 2.1.0\n"}, None),
            ({"pubspec.yaml": PUB + "hooks:\n  user_defines:\n    sqlite3:\n      source: system\n"}, None),
            ({"pubspec_overrides.yaml": "x\n"}, None),
            ({"hook/build.dart": "void main(){}\n"}, None),
            ({"test/flutter_test_config.dart": "x\n"}, None),
            ({"pubspec.yaml": PUB + "  http: ^1.2.0\n"}, {"hook/build.dart": "void main(){}\n"}),   # own hook at HEAD
            ({"pubspec.yaml": PUB + "  http: ^1.2.0\n"}, {"flutter_test_config.dart": "x\n"}),   # root test config
        ]
        for change, base_extra in cases:
            with self.subTest(change=sorted(change)):
                r, base = self._repo(base_extra)
                _commit(r, change)
                self.assertEqual(EFF.build_inputs(r, base)[0], "other")
        self.assertEqual(EFF.build_inputs(repo(self, {"a": "x"}), None)[0], "other")     # unknown base: fail closed
        self.assertEqual(EFF.hook_changes(repo(self, {"pubspec.yaml": "x"}), None), ["(no base)"])

    def test_other_halts_the_suite_and_nothing_runs(self):
        from workflows.dev import ports as PT
        r, base = self._repo()
        _commit(r, {"pubspec.yaml": PUB + "  mine:\n    path: ../mine\n"})
        ran = []
        orig = PT.CH.run_command
        PT.CH.run_command = lambda *a, **k: ran.append(a) or _CR(True, 0, False, "", [], 60)
        try:
            res = PT.suite_in_tree(r, base, ["flutter test"], "tester", 60, tmpdir(self), dict(os.environ))
        finally:
            PT.CH.run_command = orig
        self.assertEqual(ran, [])
        self.assertFalse(res.passed)
        self.assertEqual(res.build_inputs_changed, ["pubspec.yaml"])
        self.assertTrue(res.warm.startswith("skipped(build-inputs-changed"))

    def test_stage_env_halts_on_build_inputs_and_on_dependency_signatures(self):
        for raw, flag in (("", ["pubspec.yaml"]),
                          ("Building native assets failed. See the logs for more details.\n", ["(dependency state)"])):
            with self.subTest(flag=flag):
                red = suite(raw + "00:01 +0 -1: Some tests failed.\n", passed=False, rc=1)
                red.build_inputs_changed = flag
                h = Harness(self, fixture(), roles=[], suites=[red])
                res = T.run(h.p)
                self.assertEqual((res.kind, res.fail_class), (res.FAIL, "prevalidate_env"))
                self.assertTrue(res.notes[0].startswith("halted: env build-inputs-changed — %s" % flag[0]))
                self.assertNotIn("guild:needs-human", h.labels())
                self.assertIsNone(h.body_with("test:output"))
        self.assertIn("build-inputs-changed", SB.ENV_HALT_REASONS)

    def test_dependency_signatures(self):
        for raw in ("ClientException with SocketException: Failed host lookup: 'pub.dev' (OS Error: nodename nor servname)",
                    "Building native assets failed. See the logs for more details.",
                    "Error: Couldn't resolve the package 'http' in 'package:http/http.dart'.",
                    "Because app depends on foo ^9.0.0 which doesn't match any versions, version solving failed."):
            self.assertTrue(PF.dependency_failure(raw), raw)
        for raw in ("Expected: <1>\n  Actual: <2>", "Some tests failed.", "SocketException: closed by test"):
            self.assertFalse(PF.dependency_failure(raw), raw)

    def test_warm_up_test_imports_nothing_from_the_repo(self):
        from workflows.dev.ports import WARMUP_DART, WARMUP_DIR
        imports = re.findall(r"^import '([^']+)'", WARMUP_DART, re.M)
        self.assertEqual(imports, ["package:flutter_test/flutter_test.dart"])
        self.assertNotIn("test", WARMUP_DIR.split("/"))

    def test_bundle_always_dropped_after_the_warm_up(self):
        from workflows.dev import ports as PT
        r = repo(self, {"pubspec.yaml": "name: x\n"})
        tree = tmpdir(self)
        open(os.path.join(tree, "pubspec.yaml"), "w").write("name: x\n")

        def fake(cmds, t, sb, tmp, env=None, hosts=None, timeout_s=1800):
            os.makedirs(os.path.join(t, "build", "unit_test_assets"), exist_ok=True)
            return _CR(True, 0, False, "", [], 60), {}
        orig = PT.CH.deps_step
        PT.CH.deps_step = fake
        try:
            run_dir = tmpdir(self)
            os.makedirs(os.path.join(run_dir, "tmp"))
            res, px = PT.warm_in_place(r, tree, run_dir, dict(os.environ))
        finally:
            PT.CH.deps_step = orig
        self.assertTrue(res.passed)
        self.assertNotIn("placeholders", px)
        self.assertFalse(os.path.exists(os.path.join(tree, "build", "unit_test_assets")))

    def test_preflight_skipped_when_the_test_command_generates_files(self):
        r = repo(self, {"pubspec.yaml": "name: app\n", ".gitignore": "*.g.dart\n",
                        "test/a_test.dart": "import 'package:app/m.g.dart';\n"})
        self.assertEqual(PF.ignored_needed(r), ["lib/m.g.dart"])
        cfg = dict(CFG, commands={"test": ["dart run build_runner build -d", "flutter test"]})
        h = Harness(self, fixture(), root=r, config=cfg, roles=[role("DONE", covers=[], e2e="E2E 불요: x")],
                    suites=[suite("00:01 +0 -1: x [E]\n00:01 +0 -1: Some tests failed.\n", passed=False, rc=1)])
        h.write_file("docs/specs/7/test-cases.md", "| C1 | a |\n")
        res = T.run(h.p)
        self.assertNotEqual(res.fail_class, "prevalidate_env")          # no preflight halt — the suite ran
        self.assertEqual(len(h.calls["suites"]), 1)
