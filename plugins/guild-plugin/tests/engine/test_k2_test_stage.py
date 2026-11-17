"""K2 — the test stage, the shared loop-back procedure and entry rules (C §2.T, §2.L; design §2.2, §3.3)."""

import unittest

from _k2 import (FLUTTER_GREEN, FLUTTER_RED, Harness, comment, decision, fixture, judge_test, role,
                 suite)
from guildcore.adapters.gh import GhWriteError
from guildcore.decisions import DecisionLog
from guildcore.judges.runner import Halted, RateLimited
from guildcore.records import loopback as LB
from guildcore.records import needs_human as NH
from workflows.dev import handoff as HO
from workflows.dev.stages import base as B
from workflows.dev.stages import loopback as LP
from workflows.dev.stages import test as T

TC = "| C1 | 제목이 보인다 |\n| C2 | 버튼이 눌린다 |\n"
TESTFILE = "void main() {\n  testWidgets('t', (tester) async {\n    expect(find.text('a'), findsOneWidget);\n  });\n}\n"
LEDGER = "<!-- guild:visual-baselines -->\nrun: yes\nP test/goldens/home.png — 색 변경\n<!-- /guild:visual-baselines -->"
EVIDENCE = "<!-- guild:test-evidence:step-1 -->\n증거\n%s\n<!-- /guild:test-evidence:step-1 -->" % LEDGER


def consumed(block):
    return block + "\nconsumed: 2026-11-15T01:00:00Z"


def covers(kind="guard"):
    return [{"test": "test/a_test.dart::t", "ac": "C1", "kind": kind},
            {"test": "test/a_test.dart::t", "ac": "C2", "kind": kind}]


def green_harness(case, unattended=True, judges=None, roles=None, labels=("guild:test",), comments=()):
    h = Harness(case, fixture(labels=labels, comments=comments), unattended=unattended,
                roles=roles or [role("DONE", covers=covers(), e2e="E2E 불요: 위젯 한정")],
                judges=judges or {"TEST": [judge_test(["C1", "C2"])]},
                suites=[suite(FLUTTER_GREEN)])
    h.write_file("docs/specs/7/test-cases.md", TC)
    h.write_file("test/a_test.dart", TESTFILE)
    return h


class Entry(unittest.TestCase):
    def test_refuses_a_pr(self):
        fx = fixture()
        fx["issues"]["7"]["url"] = "https://github.com/o/r/pull/7"
        r = T.run(Harness(self, fx).p)
        self.assertEqual((r.kind, r.fail_class), ("FAIL", "prevalidate"))

    def test_split_parent_refused_without_label_write(self):
        h = Harness(self, fixture(labels=("guild:children",)))
        r = T.run(h.p)
        self.assertIn("is a split parent (guild:children)", r.token())
        self.assertEqual(h.w.calls, [])
        self.assertEqual(h.marks, ["test"])

    def test_wrong_stage_refused_cf1(self):
        h = Harness(self, fixture(labels=("guild:analyze",)))
        r = T.run(h.p)
        self.assertEqual(r.token(), "FAIL: #7 is at guild:analyze — /gld test runs only at guild:test "
                                    "(use /gld rollback stage to move back)")
        self.assertEqual(h.labels(), ["guild:analyze"])

    def test_sprint_tracker_refused(self):
        r = T.run(Harness(self, fixture(labels=("guild:sprint",))).p)
        self.assertIn("sprint tracking Issue", r.token())

    def test_uninitialized_is_environment_level(self):
        r = T.run(Harness(self, fixture()).p, config_present=False)
        self.assertEqual(r.fail_class, "prevalidate_env")

    def test_empty_labels_get_the_stage_label(self):
        h = green_harness(self, labels=())
        r = T.run(h.p)
        self.assertEqual(r.token(), "OK ADVANCE: qa")
        self.assertEqual(h.labels(), ["guild:qa"])

    def test_child_label_survives_and_needs_human_removed(self):
        h = green_harness(self, labels=("guild:child", "guild:test", "guild:needs-human"))
        T.run(h.p)
        self.assertEqual(h.labels(), ["guild:child", "guild:qa"])

    def test_recheck_on_done_writes_only_a_note_c12(self):
        h = Harness(self, fixture(labels=("guild:done",)), suites=[suite(FLUTTER_RED, passed=False, rc=1)])
        r = T.run(h.p, only="test")
        self.assertEqual(r.kind, "DONE")
        self.assertEqual(h.labels(), ["guild:done"])
        self.assertTrue(h.bodies()[-1].startswith("<!-- guild:note -->\nrecheck test "))
        self.assertIn(": red — ", h.bodies()[-1])
        self.assertIsNone(h.body_with("test:output"))


class TestPass(unittest.TestCase):
    def test_green_effective_advances_with_output_first(self):
        h = green_harness(self)
        r = T.run(h.p)
        self.assertEqual(r.token(), "OK ADVANCE: qa")
        out = h.body_with("test:output")
        self.assertTrue(out.endswith("<!-- /guild:test:output -->"))
        self.assertIn("- (d) E2E 불요: 위젯 한정", out)
        self.assertIn("### 검증 범위", out)
        self.assertEqual(HO.test_to_qa([comment(out, 1)]), [])
        ops = [c[0] for c in h.w.calls]
        self.assertLess(ops.index("create_comment"), max(i for i, o in enumerate(ops) if o == "edit_labels"))
        blk = [b for b in DecisionLog.load(h.gh.comments(7)).blocks if b.get("point") == "TEST"][0]
        self.assertEqual(blk.get("choice"), "effective:C1,C2;uncovered:none")
        self.assertEqual(blk.get("checks"), "C1=unverified(not a git worktree),C2=unverified(not a git worktree)")
        self.assertEqual(h.captures, [])

    def test_hedged_e2e_becomes_run_needed(self):
        h = green_harness(self, roles=[role("DONE", covers=covers(), e2e="E2E 권장 (가능하면)")])
        T.run(h.p)
        self.assertIn("- (d) E2E 회귀 실행 필요:", h.body_with("test:output"))

    def test_test_output_replaced_in_place(self):
        old = comment("<!-- guild:test:output -->\nold\n<!-- /guild:test:output -->", 5)
        h = green_harness(self, comments=[old])
        T.run(h.p)
        outs = [b for b in h.bodies() if b.startswith("<!-- guild:test:output -->")]
        self.assertEqual(len(outs), 1)
        self.assertNotIn("old", outs[0])


class TestFail(unittest.TestCase):
    def red(self, unattended=True, comments=(), labels=("guild:test",)):
        h = Harness(self, fixture(labels=labels, comments=comments), unattended=unattended,
                    roles=[role("DONE", covers=covers(), e2e="E2E 불요: x")],
                    suites=[suite(FLUTTER_RED, passed=False, rc=1)])
        h.write_file("docs/specs/7/test-cases.md", TC)
        return h

    def test_unattended_red_loops_back_with_names_signature(self):
        h = self.red()
        r = T.run(h.p)
        self.assertEqual(r.token(), "OK LOOPBACK: execute")
        rec = LB.from_comments(h.gh.comments(7))
        b = rec.latest_active()
        self.assertEqual(b.get("from"), "test")
        self.assertEqual(b.get("signature"), "widget shows title")
        self.assertEqual(b.get("branch"), "feature/7-x")
        self.assertEqual(h.labels(), ["guild:execute"])
        kinds = [c[0] for c in h.captures]
        self.assertIn("verify-gap", kinds)            # claimed pass, raw red
        self.assertTrue(any(c[4] for c in h.captures))  # surprise on the claim mismatch

    def test_cap_reached_pauses_without_moving_label(self):
        rec = LB.render_new_record(consumed(LB.render_block(1, "test", "2026-11-15T00:00:00Z", "b", "r", "x")) + "\n" +
                                   consumed(LB.render_block(2, "qa", "2026-11-15T00:00:01Z", "b", "r", "y")))
        h = self.red(comments=[comment(rec, 3)])
        r = T.run(h.p)
        self.assertEqual(r.token(), "OK PAUSE: needs-human — loop-back cap reached")
        self.assertEqual(h.labels(), ["guild:needs-human", "guild:test"])
        p = NH.from_comments(h.gh.comments(7))[-1]
        self.assertTrue(p.cause_check_ok())
        self.assertTrue(p.cause_line.startswith("defect: loop-back cap reached — "))

    def test_stagnant_pauses_and_captures(self):
        rec = LB.render_new_record(consumed(LB.render_block(1, "test", "2026-11-15T00:00:00Z", "b", "r",
                                                            "widget shows title,zzz")))
        h = self.red(comments=[comment(rec, 3)])
        r = T.run(h.p)
        self.assertTrue(r.token().startswith("OK PAUSE: needs-human — stagnant loop-back — "))
        self.assertIn("stagnation", [c[0] for c in h.captures])

    def test_attended_red_asks_and_writes_loopback_lines(self):
        self._attended()

    def _attended(self):
        h = self.red(unattended=False)
        r = T.run(h.p)
        self.assertEqual(r.kind, "ASK")
        self.assertTrue(r.line.startswith("tests not green / AC gap — tests not green — "))
        self.assertIn("; loop back to execute? (loop-backs so far: 0/2)", r.line)
        out = h.body_with("test:output")
        self.assertIn("\nloopback-signature: widget shows title\n", out)
        self.assertEqual(h.labels(), ["guild:test"])
        blk = DecisionLog.load(h.gh.comments(7)).by_id(r.qid)
        self.assertEqual((blk.get("kind"), blk.get("status"), blk.get("options")),
                         ("loopback", "pending-human", "loop-back|stop"))
        return h, r

    def test_attended_answer_loops_back_once_decided_human(self):
        h, r = self._attended()
        h.decisions.resolve(r.qid, {"point": "loopback-ask:test", "kind": "loopback", "stage": "test",
                                    "by": "human", "choice": "loop-back"})
        h.roles = []
        r2 = T.run(h.p)
        self.assertEqual(r2.token(), "OK LOOPBACK: execute")
        b = LB.from_comments(h.gh.comments(7)).latest_active()
        self.assertEqual((b.get("decided"), b.get("override")), ("human", None))
        self.assertEqual(h.calls["suites"].__len__(), 1)      # the re-run ran no tests
        self.assertEqual(B.pending_answer(h.p, "test", "loopback"), (None, None))

    def test_attended_stop_is_a_pause_without_writes(self):
        h, r = self._attended()
        h.decisions.resolve(r.qid, {"kind": "loopback", "stage": "test", "by": "human", "choice": "stop"})
        n_before = len(h.w.calls)
        r2 = T.run(h.p)
        self.assertEqual(r2.kind, "PAUSE")
        self.assertIsNone(LB.from_comments(h.gh.comments(7)))
        self.assertEqual([c for c in h.w.calls[n_before:] if c[0] == "edit_labels"], [])

    def test_timeout_signature_names_last_running(self):
        h = Harness(self, fixture(), roles=[role("FAIL", "suite killed", covers=[], e2e="E2E 불요: x")],
                    suites=[suite("00:01 +1: slow test\n", passed=False, rc=-9, timed_out=True)])
        h.write_file("docs/specs/7/test-cases.md", TC)
        r = T.run(h.p)
        self.assertEqual(r.kind, "LOOPBACK")
        self.assertEqual(LB.from_comments(h.gh.comments(7)).latest_active().get("signature"), "timeout:x")

    def test_record_write_failure_does_not_move_label(self):
        h = self.red()
        orig = h.writer.append_block

        def boom(*a, **k):
            raise GhWriteError("comment:append", "HTTP 422", "terminal")
        h.writer.append_block = boom
        r = T.run(h.p)
        self.assertEqual(r.kind, "PAUSE")
        self.assertIn("engine FAIL — loop-back record not written", r.token())
        self.assertNotIn("guild:execute", h.labels())
        h.writer.append_block = orig


class Coverage(unittest.TestCase):
    def test_not_covering_repairs_mapping_once_then_uncovered(self):
        h = green_harness(self, roles=[role("DONE", covers=covers(), e2e="E2E 불요: x"),
                                       role("DONE", covers=covers())],
                          judges={"TEST": [judge_test(["C1", "C2"], "not_covering"),
                                           judge_test(["C1", "C2"], "not_covering")]})
        r = T.run(h.p)
        self.assertEqual(r.kind, "LOOPBACK")
        self.assertEqual([c.task for c in h.calls["roles"]], ["verify", "repair-mapping"])
        self.assertEqual(len(h.calls["judges"]), 2)
        self.assertEqual(LB.from_comments(h.gh.comments(7)).latest_active().get("signature"), "C1,C2")

    def test_vacuous_loops_back_with_capture(self):
        h = green_harness(self, judges={"TEST": [judge_test(["C1", "C2"], "vacuous")]})
        r = T.run(h.p)
        self.assertEqual(r.kind, "LOOPBACK")
        self.assertIn("verify-gap", [c[0] for c in h.captures])

    def test_effective_without_assertion_is_unsure_no_capture(self):
        h = green_harness(self)
        h.write_file("test/a_test.dart", "void main() { testWidgets('t', (t) async { print('x'); }); }\n")
        h.roles.append(role("DONE", covers=covers()))
        h.judges["TEST"].append(judge_test(["C1", "C2"]))
        r = T.run(h.p)
        self.assertEqual(r.kind, "LOOPBACK")
        self.assertEqual(h.captures, [])                       # unsure-derived uncovered: no capture
        out = h.body_with("test:output")
        self.assertIn("no reachable non-trivial assertion", out)

    def test_no_ac_ids_uses_tester_covers_not_a_pause(self):
        h = green_harness(self)
        h.write_file("docs/specs/7/test-cases.md", "nothing here\n")
        r = T.run(h.p)
        self.assertEqual(r.kind, "ADVANCE")

    def test_case_ids(self):
        self.assertEqual(T.case_ids("| C1 | a |\n- **C2** b\n### AC #3 x\n| TC-4 | y\n| foo |\n"),
                         ["C1", "C2", "AC #3", "TC-4"])


class Visual(unittest.TestCase):
    def test_pending_regeneration_moves_label_with_needs_human(self):
        raw = FLUTTER_RED + '══╡ Golden "test/goldens/home.png": Pixel test failed, 2.1% diff\n'
        h = Harness(self, fixture(comments=[comment(EVIDENCE, 2)]),
                    roles=[role("DONE_WITH_CONCERNS", "golden red", covers=covers(), e2e="E2E 불요: x")],
                    suites=[suite(raw, passed=False, rc=1)])
        h.write_file("docs/specs/7/test-cases.md", TC)
        r = T.run(h.p)
        self.assertEqual(r.token(), "OK PAUSE: needs-human — pending regeneration")
        self.assertEqual(h.labels(), ["guild:execute", "guild:needs-human"])
        self.assertIsNone(LB.from_comments(h.gh.comments(7)))
        self.assertIn(LEDGER, h.body_with("test:output"))          # verbatim copy (L.3)

    def test_environment_suspect_host_mismatch_pauses(self):
        raw = FLUTTER_RED + 'Golden "test/goldens/other.png": Pixel test failed\n'
        h = Harness(self, fixture(comments=[comment(EVIDENCE, 2)]), host="linux amd64",
                    roles=[role("DONE", covers=covers(), e2e="E2E 불요: x")],
                    suites=[suite(raw, passed=False, rc=1)])
        h.write_file("docs/specs/7/test-cases.md", TC)
        r = T.run(h.p)
        self.assertEqual(r.token(), "OK PAUSE: needs-human — visual environment")
        p = NH.from_comments(h.gh.comments(7))[-1]
        self.assertTrue(p.cause_line.startswith("env: other — visual failures look environmental"))
        self.assertTrue(p.directive_line.startswith("사람 지시 확인: 없음 — 읽음: #7"))

    def test_vis_env_judge_regression_is_red(self):
        raw = FLUTTER_RED + 'Golden "test/goldens/other.png": Pixel test failed\n'
        h = Harness(self, fixture(comments=[comment(EVIDENCE, 2)]),
                    roles=[role("DONE", covers=covers(), e2e="E2E 불요: x")],
                    judges={"VIS-ENV": decision("regression", {"verdict": "regression"})},
                    suites=[suite(raw, passed=False, rc=1)])
        h.write_file("docs/specs/7/test-cases.md", TC)
        r = T.run(h.p)
        self.assertEqual(r.kind, "LOOPBACK")


class RunnerAndRoles(unittest.TestCase):
    def test_unknown_summary_runner_unsure_pauses_env(self):
        h = Harness(self, fixture(), judges={"RUNNER": decision("unsure", {"verdict": "unsure"})},
                    suites=[suite("weird output\n")])
        r = T.run(h.p)
        self.assertEqual(r.token(), "OK PAUSE: needs-human — test summary unreadable")
        self.assertEqual(NH.from_comments(h.gh.comments(7))[-1].cause_line,
                         "env: other — 테스트 요약 형식을 읽지 못함 — commands.test_summary 를 설정하세요")

    def test_invalid_result_pauses_defect(self):
        h = Harness(self, fixture(), roles=[role("INVALID")], suites=[suite(FLUTTER_GREEN)])
        r = T.run(h.p)
        self.assertEqual(r.token(), "OK PAUSE: needs-human — tester returned no valid RESULT line")
        blk = DecisionLog.load(h.gh.comments(7)).pending_human()
        self.assertEqual(blk[0].get("kind"), "role-result-invalid")

    def test_permission_pauses_env_other(self):
        res = role("PERMISSION")
        res.denials = [{"command": "flutter pub get"}]
        h = Harness(self, fixture(), roles=[res], suites=[suite(FLUTTER_GREEN)])
        r = T.run(h.p)
        self.assertEqual(NH.from_comments(h.gh.comments(7))[-1].cause_line,
                         "env: other — 역할 권한 거부: flutter pub get")
        self.assertIn("역할 권한 거부", r.token())

    def test_halt_and_rate_limit_propagate(self):
        for st, exc in (("HALTED", Halted), ("RATE_LIMITED", RateLimited)):
            h = Harness(self, fixture(), roles=[role(st)], suites=[suite(FLUTTER_GREEN)])
            with self.assertRaises(exc):
                T.run(h.p)

    def test_scope_violation_pauses(self):
        res = role("SCOPE")
        res.violations = ["lib/a.dart"]
        h = Harness(self, fixture(), roles=[res], suites=[suite(FLUTTER_GREEN)])
        r = T.run(h.p)
        self.assertEqual(r.token(), "OK PAUSE: needs-human — tester wrote outside its scope — lib/a.dart")


class Procedure(unittest.TestCase):
    def test_interrupted_loopback_finishes_steps_6_7_only(self):
        rec = LB.render_new_record(LB.render_block(1, "test", "2026-11-15T00:00:09Z", "b", "r", "x",
                                                   decided="human"))
        h = Harness(self, fixture(labels=("guild:test", "guild:needs-human"), comments=[comment(rec, 3)]))
        r = T.run(h.p)
        self.assertEqual(r.token(), "OK LOOPBACK: execute")
        self.assertEqual(h.labels(), ["guild:execute"])
        self.assertEqual(h.calls["roles"], [])

    def test_not_interrupted_when_execute_ran_since(self):
        rec = LB.render_new_record(LB.render_block(1, "test", "2026-11-15T00:00:09Z", "b", "r", "x"))
        aud = "<!-- guild:auditor:execute -->\n### audit-record 1\ninvocation: 2026-11-15T00:00:09Z\n<!-- /guild:auditor:execute -->"
        self.assertIsNone(LP.interrupted([comment(rec, 3), comment(aud, 4)], "guild:test", ["guild:test"]))
        self.assertIsNotNone(LP.interrupted([comment(rec, 3)], "guild:test", ["guild:test"]))
        self.assertIsNone(LP.interrupted([comment(rec, 3)], "guild:test", ["guild:execute"]))

    def test_override_when_human_loops_past_cap(self):
        rec = LB.render_new_record(consumed(LB.render_block(1, "test", "a", "b", "r", "x")) + "\n" +
                                   consumed(LB.render_block(2, "test", "a", "b", "r", "y")))
        h = Harness(self, fixture(comments=[comment(rec, 3)]))
        r = LP.run(h.p, "test", "test", "again", ["z"], decided_human=True)
        self.assertEqual(r.kind, "LOOPBACK")
        b = LB.from_comments(h.gh.comments(7)).latest_active()
        self.assertEqual((b.get("decided"), b.get("override")), ("human", "human"))
        self.assertEqual(b.heading, "### loopback 3")

    def test_empty_signature_refused(self):
        h = Harness(self, fixture())
        with self.assertRaises(ValueError):
            LP.run(h.p, "test", "test", "r", [])

    def test_ask_suffixes(self):
        line = LP.ask_line("x", {"active": 2, "cap": 2, "cap_reached": True, "stagnant_n": 1})
        self.assertEqual(line, "x; loop back to execute? (loop-backs so far: 2/2) — cap reached; yes overrides "
                               "it — same failure as loop-back 1; yes tries again anyway")


class Fail(unittest.TestCase):
    def test_unattended_defect_fail_pauses_cf6(self):
        h = Harness(self, fixture())
        r = B.fail(h.p, "test", "boom")
        self.assertEqual(r.kind, "PAUSE")
        self.assertEqual(NH.from_comments(h.gh.comments(7))[-1].cause_line, "defect: engine FAIL — boom")
        self.assertIn("guild:needs-human", h.labels())

    def test_gh_auth_writes_nothing(self):
        h = Harness(self, fixture())
        r = B.fail(h.p, "test", "401", "gh_auth")
        self.assertEqual((r.kind, r.fail_class), ("FAIL", "gh_auth"))
        self.assertEqual(h.w.calls, [])

    def test_transient_is_env_service(self):
        h = Harness(self, fixture())
        B.fail(h.p, "test", "502 x3", "transient")
        self.assertTrue(NH.from_comments(h.gh.comments(7))[-1].cause_line.startswith("env: service — "))


if __name__ == "__main__":
    unittest.main()
