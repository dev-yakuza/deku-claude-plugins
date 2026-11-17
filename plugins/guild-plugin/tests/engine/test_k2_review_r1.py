"""K2 review r1 — regressions for every probe (review-k2-r1.md B1–B4, M1–M7, m1–m11)."""

import gzip
import json
import os
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
        oc = EFF.check_ac(h.p, CFG, "C1", [{"test": "test/a_test.dart", "ac": "C1", "kind": "guard"}], None)
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
        self.assertEqual(EFF.single_command({}, "pytest", "t/test_a.py", "T.test_x"), "python3 -m pytest t/test_a.py::T::test_x")
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
        with gzip.open(os.path.join(K2FX, "tc-shapes.json.gz")) as fh:
            shapes = json.load(fh)
        self.assertEqual(len(shapes), 233)
        zero = []
        for n, v in sorted(shapes.items()):
            t0 = time.time()
            ids = CS.case_ids(v["text"])
            self.assertLess(time.time() - t0, 1.0, n)
            self.assertEqual(ids, v["ids"], n)
            if not ids:
                zero.append(n)
        # #961, #1791: prose / bullet-only checklists — no ids by construction (ac_source: tester)
        self.assertEqual(sorted(zero), ["1791", "961"])

    def test_shapes(self):
        self.assertEqual(CS.case_ids("| ID | AC | x |\n|---|---|---|\n| T1 | AC1 | a |\n| T2 | AC2 | b |\n"), ["T1", "T2"])
        self.assertEqual(CS.case_ids("| # | 슬라이더 |\n|---|---|\n| 1 | a |\n| 2 | b |\n"), ["#1", "#2"])
        self.assertEqual(CS.case_ids("### TC-S1 (AC1) 본문\n### 케이스 2 — x\n- **C3** y\n"), ["TC-S1", "AC1", "#2", "C3"])
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
        self.assertEqual(blk.get("checks"), "C1=unverified(no base)")
        self.assertEqual(blk.get("grade"), "trigger")
        self.assertIn("effective (unverified)", h.body_with("test:output"))

    def test_runner_not_named_is_unverified(self):
        h = Harness(self, fixture())
        h.write_file("a.test.ts", "it('t', () => { expect(f()).toBe(1); });\n")
        oc = EFF.check_ac(h.p, {"commands": {"test": "turbo test"}}, "C1",
                          [{"test": "a.test.ts::t", "ac": "C1", "kind": "new"}], "abc")
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
        files, _src, bad = EFF.impl_files(r, base, [victim, "../victim_rel.txt", "gen/api.dart", "calc.py"])
        self.assertEqual(files, ["calc.py"])
        self.assertEqual(sorted(bad), sorted([victim, "../victim_rel.txt", "gen/api.dart"]))
        with self.assertRaises(ValueError):
            with EFF.TempTree(r, base, ["gen/api.dart"]):
                pass
        self.assertTrue(os.path.exists(victim))
        self.assertTrue(os.path.exists(os.path.join(r, "gen", "api.dart")))
        self.assertEqual(git(r, "worktree", "list").count("\n"), 0)      # m6: cleaned on failure

    def test_dart_tool_copied_build_fresh_others_linked(self):
        r = repo(self, {"calc.py": "x=1\n", ".gitignore": ".dart_tool/\nbuild/\nnode_modules/\n"})
        for d in (".dart_tool/hooks_runner", ".dart_tool/build", "build/native_assets", "node_modules/x"):
            os.makedirs(os.path.join(r, d))
        open(os.path.join(r, ".dart_tool", "package_config.json"), "w").write("{}")
        with EFF.TempTree(r, git(r, "rev-parse", "HEAD"), []) as t:
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
        self.assertEqual(Q.qa_signature([{"id": "D1", "line": "목록이 갱신 안 됨", "evidence": "lib/list.dart:12"}], []),
                         ["lib/list.dart"])
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
