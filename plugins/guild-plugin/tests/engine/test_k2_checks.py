"""K2 — the TEST `effective` code check on a real repo + runner, renderers (INV5), handoff, directives,
visual ledger, the parsers, and the static rules for workflows/dev."""

import ast
import os
import unittest

import _util
from _k2 import CFG, FLUTTER_GREEN, Harness, comment, decision, fixture, git, repo, role, suite
from guildcore import checks as CH
from guildcore.checks import visual as V
from guildcore.records import markers
from workflows.dev import directive as DR
from workflows.dev import effective as EFF
from workflows.dev import handoff as HO
from workflows.dev import judging as JG
from workflows.dev.stages import render as R

UCFG = {"commands": {"test": "python3 -m unittest"}}
IMPL_BASE = "def add(a, b):\n    return 0\n"
IMPL_HEAD = "def add(a, b):\n    return a + b\n"
TEST_OK = "import unittest\nfrom calc import add\n\nclass T(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(1, 2), 3)\n"
TEST_TRIVIAL = "import unittest\nfrom calc import add\n\nclass T(unittest.TestCase):\n    def test_add(self):\n        self.assertTrue(True)\n"
TEST_WEAK = "import unittest\nfrom calc import add\n\nclass T(unittest.TestCase):\n    def test_add(self):\n        self.assertIsNotNone(add)\n"


class Effective(unittest.TestCase):
    def mk(self, base_impl, head_test, head_impl=IMPL_HEAD):
        r = repo(self, {"calc.py": base_impl} if base_impl is not None else {"README.md": "x\n"})
        base = git(r, "rev-parse", "HEAD")
        with open(os.path.join(r, "calc.py"), "w") as fh:
            fh.write(head_impl)
        with open(os.path.join(r, "test_calc.py"), "w") as fh:
            fh.write(head_test)
        git(r, "add", "-A")
        git(r, "commit", "-qm", "impl")
        h = Harness(self, fixture(), root=r, base=base)
        return h, base

    def run_check(self, h, base, kind="new", impl=None):
        cv = {"C1": [{"test": "test_calc.py::T.test_add", "ac": "C1", "kind": kind}]}
        out, src = EFF.run(h.p, UCFG, ["C1"], cv, base, impl)
        return out["C1"], src

    def test_reacting_assertion_passes(self):
        h, base = self.mk(IMPL_BASE, TEST_OK)
        oc, meta = self.run_check(h, base)
        self.assertEqual((oc.result, meta["impl_source"]), ("pass", "derived"), oc.why)
        self.assertEqual(oc.cmd, "python3 -m unittest -v test_calc.T.test_add")
        self.assertEqual(oc.line, "test_calc.py:6")
        self.assertEqual(git(h.p.root, "worktree", "list").count("\n"), 0)     # temp tree removed

    def test_import_error_after_revert_is_unverified_not_pass(self):
        h, base = self.mk(None, TEST_OK)                                       # calc.py is new → removed
        oc, _ = self.run_check(h, base)
        self.assertEqual((oc.result, oc.kind), ("unverified", "load_error"), oc.why)

    def test_still_passing_after_revert_is_unsure(self):
        h, base = self.mk(IMPL_BASE, TEST_WEAK)
        oc, _ = self.run_check(h, base)
        self.assertEqual((oc.result, oc.kind), ("unsure", "passed"))

    def test_trivial_assertion_fails_check_one(self):
        h, base = self.mk(IMPL_BASE, TEST_TRIVIAL)
        oc, _ = self.run_check(h, base)
        self.assertEqual(oc.result, "fail")
        self.assertEqual(h.calls["checks"], [])

    def test_guard_needs_assertion_only(self):
        h, base = self.mk(IMPL_BASE, TEST_WEAK)
        oc, _ = self.run_check(h, base, kind="guard")
        self.assertEqual(oc.result, "pass")
        self.assertEqual(h.calls["checks"], [])

    def test_given_impl_files_used(self):
        h, base = self.mk(IMPL_BASE, TEST_OK)
        oc, meta = self.run_check(h, base, impl=["calc.py"])
        self.assertEqual((oc.result, meta["impl_source"]), ("pass", "result"))

    def test_ignored_build_dirs_linked_into_temp_tree(self):
        h, base = self.mk(IMPL_BASE, TEST_OK)
        with open(os.path.join(h.p.root, ".gitignore"), "w") as fh:
            fh.write("gen/\n")
        os.makedirs(os.path.join(h.p.root, "gen"))
        with EFF.TempTree(h.p.root, base, ["calc.py"]) as t:
            self.assertTrue(os.path.islink(os.path.join(t, "gen")))
            self.assertEqual(open(os.path.join(t, "calc.py")).read(), IMPL_BASE)

    def test_parse_refs_and_commands(self):
        self.assertEqual(EFF.parse_test_ref("test/a_test.dart::shows title"), ("test/a_test.dart", "shows title"))
        self.assertEqual(EFF.parse_test_ref("«shows» (test/a_test.dart)"), ("test/a_test.dart", "shows"))
        self.assertEqual(EFF.single_command(CFG, "flutter", "test/a_test.dart", "x y"),
                         "flutter test test/a_test.dart --no-pub --name '(^| )x\\ y$'")
        self.assertTrue(EFF.has_assertion("expect(find.text('a'), findsOneWidget);", "flutter")[0])
        self.assertFalse(EFF.has_assertion("expect(true, isTrue);", "flutter")[0])


class Parsers(unittest.TestCase):
    def test_failure_kinds(self):
        self.assertEqual(CH.failure_kind("00:01 +0 -1: a [E]\n  Expected: 3\n  Actual: 0\n00:01 +0 -1: Some tests failed.\n",
                                         "flutter"), "assertion")
        self.assertEqual(CH.failure_kind("lib/a.dart:3:5: Error: Undefined name 'x'.\n00:01 +0 -1: loading [E]\n"
                                         "  Failed to load \"test/a_test.dart\"\n00:01 +0 -1: Some tests failed.\n",
                                         "flutter"), "load_error")
        self.assertEqual(CH.failure_kind("FAIL src/a.test.ts\n  ● Test suite failed to run\nTests:       1 failed, 1 total\n",
                                         "jest"), "load_error")
        self.assertEqual(CH.failure_kind(FLUTTER_GREEN, "flutter"), "passed")
        self.assertEqual(CH.failure_kind("??", None), "unknown")

    def test_visual_ledger(self):
        b = "x\n<!-- guild:visual-baselines -->\nrun: yes\nP a.png — r\nA b.png — case: C3\nA c.png — replaces d.png — r\nR e.png -> f.png — moved, unchanged\n<!-- /guild:visual-baselines -->\ny"
        led = V.visual_ledger(b)
        self.assertEqual((led.run, led.pending), ("yes", ["a.png"]))
        self.assertEqual([(r.kind, r.case, r.replaces) for r in led.of("A")], [("A", True, False), ("A", False, True)])
        self.assertEqual(led.of("R")[0].path, "f.png")
        self.assertTrue(V.confined_to_pending(["test/a.png"], V.visual_ledger(b.replace("P a.png", "P test/a.png"))))
        self.assertFalse(V.confined_to_pending(["a.png", "z.png"], led))
        self.assertEqual(V.block_text("<!-- guild:visual-baselines --> trailing\n"), None)

    def test_env_mismatch(self):
        self.assertFalse(V.env_mismatch("macOS arm64", "macOS arm64 local"))
        self.assertTrue(V.env_mismatch("macOS arm64", "docker linux/amd64"))
        self.assertIsNone(V.env_mismatch(None, "x"))


class Render(unittest.TestCase):
    def out(self, raw, verbatim=()):
        return R.test_output(7, [("flutter test", 0, "All tests passed!")], raw, "green — x", "일치",
                             [("C1", "effective", ["t"], None)], ["flutter test"], {"e2e": "e2e"}, list(verbatim),
                             [], "E2E 불요: x")

    def test_raw_redacted_per_line(self):
        tok = "ghp_" + "a" * 36
        o = self.out("line one\ntoken=%s here\nline three\n" % tok)
        self.assertNotIn(tok, o)
        self.assertIn("line one", o)
        self.assertIn("line three", o)

    def test_private_key_blanks_the_whole_raw_block(self):
        o = self.out("ok\n-----BEGIN OPENSSH PRIVATE KEY-----\nAAAA\n-----END OPENSSH PRIVATE KEY-----\nmore\n")
        self.assertNotIn("AAAA", o)
        self.assertNotIn("more", o)
        self.assertIn("[REDACTED]", o)

    def test_raw_marker_text_neutralized_and_fence_grows(self):
        o = self.out("<!-- guild:test:output -->\n```\nx\n")
        self.assertEqual(o.count("<!-- guild:test:output -->"), 1)
        self.assertIn("````text", o)

    def test_verbatim_ledger_byte_identical(self):
        led = "<!-- guild:visual-baselines -->\nrun: no\nnone\n<!-- /guild:visual-baselines -->"
        o = self.out("ok\n", [led])
        self.assertIn("\n" + led + "\n", o)
        self.assertEqual(HO.test_to_qa([comment("<!-- guild:test-evidence:step-1 -->\n%s\n<!-- /guild:test-evidence:step-1 -->" % led, 1),
                                        comment(o, 2)]), [])

    def test_foreign_marker_refused(self):
        with self.assertRaises(ValueError):
            self.out("ok\n", ["<!-- guild:needs-human -->\nx"])

    def test_e2e_literals(self):
        self.assertEqual(R.e2e_line("E2E 불요: 위젯 한정"), ("E2E 불요: 위젯 한정", True))
        self.assertFalse(R.e2e_line("E2E 불요:")[1])
        self.assertTrue(R.e2e_line("E2E 권장")[0].startswith(R.E2E_RUN))


class Handoff(unittest.TestCase):
    def test_execute_to_test(self):
        ev = comment("<!-- guild:test-evidence:step-1 -->\nok\n<!-- /guild:test-evidence:step-1 -->", 1)
        aud = comment("<!-- guild:auditor:execute -->\n### audit-record 1\ninvocation: t\n<!-- /guild:auditor:execute -->", 2)
        prs = [{"number": 9, "state": "OPEN", "body": "Closes #7"}]
        self.assertEqual(HO.execute_to_test([ev, aud], prs, 7, {}), [])
        bad = HO.execute_to_test([ev], [], 7, CFG)
        self.assertEqual(bad, ["no open PR closes #7", "no audit-record block",
                               "execute evidence has no visual-baselines ledger"])

    def test_test_to_qa_missing_parts(self):
        bad = HO.test_to_qa([comment("<!-- guild:test:output -->\n- (d) maybe\n<!-- /guild:test:output -->", 1)])
        self.assertIn("no 검증 범위 block", bad)
        self.assertIn("(d) is not one of the two E2E literals", bad)


class Directives(unittest.TestCase):
    def test_reads_issue_parent_and_open_trackers(self):
        fx = fixture(body="Parent Issue: #3\n", comments=[comment("사람 지시: CI 무시", 11)],
                     extra_issues={3: {"number": 3, "body": "Sprint: #50\nSprint: #51\n", "labels": [],
                                       "comments": [comment("<!-- guild:note -->\nx", 12)]},
                                   50: {"number": 50, "state": "OPEN", "labels": [], "comments": []},
                                   51: {"number": 51, "state": "CLOSED", "labels": [],
                                        "comments": [comment("ignored", 13)]}})
        h = Harness(self, fx)
        g = DR.gather(h.gh, 7)
        self.assertEqual((g["parent"], g["trackers"], len(g["comments"])), (3, [50], 1))
        h.judges["DIRECTIVE"] = decision("out_of_scope", {"verdict": "out_of_scope", "applies": [],
                                                           "out_of_scope": [{"comment": "#7", "line": "CI 무시"}]})
        kind, line, _ = DR.judge(h.p, "qa", g, "PR CI red", "Q2.3")
        self.assertEqual(kind, "out_of_scope")
        self.assertTrue(line.startswith('적용 가능한 사람 지시: #7 "CI 무시"'))
        self.assertEqual(h.calls["judges"][0].no_elide, {"comments"})

    def test_none_line(self):
        self.assertEqual(DR.none_line({"issue": 7, "trackers": [50], "parent": 3, "comments": []}),
                         "사람 지시 확인: 없음 — 읽음: #7 · 트래커 #50 · 부모 #3 (마커 없는 댓글 0개, 전문)")


class JudgeSpecs(unittest.TestCase):
    def test_groups_build_valid_specs(self):
        h = Harness(self, fixture())
        for g in JG.TIERS:
            sp = JG.spec(h.p, g, [("x", "y")], "test", "s")
            self.assertEqual(sp.model, JG.TIERS[g])
        self.assertEqual(JG.spec(h.p, "TEST", [], "test", "s", cwd="/r").tools, "Read,Grep")
        self.assertEqual(JG.spec(h.p, "RUNNER", [], "test", "s").cap_chars, 6000)


class Static(unittest.TestCase):
    MUTATING = ("commit", "push", "add", "reset", "switch", "checkout", "stash", "update-ref", "tag", "merge",
                "rebase", "fetch", "pull", "am", "apply", "cherry-pick", "revert", "rm", "mv", "worktree",
                "branch", "gc", "clean", "restore", "notes")

    def test_workflows_dev_never_spawns_git_or_gh_directly(self):
        bad = []
        for base, _d, files in os.walk(os.path.join(_util.ENGINE, "workflows", "dev")):
            for f in files:
                if not f.endswith(".py"):
                    continue
                tree = ast.parse(open(os.path.join(base, f), encoding="utf-8").read())
                for node in ast.walk(tree):
                    if isinstance(node, ast.List) and node.elts and isinstance(node.elts[0], ast.Constant) \
                            and node.elts[0].value in ("git", "gh"):
                        bad.append((f, node.elts[0].value))
        self.assertEqual([b for b in bad if not b[0].startswith(("smoke", "calibrate", "permissions_check",
                                                                  "extract_results", "proxy", "procedure"))], [])

    def test_stage_bodies_start_with_markers(self):
        o = R.qa_output(7, ["a"], "ui", ["h"], "PR CI: green", "2026-11-16T00:00:00Z", [], 9)
        self.assertEqual(markers.first_line_marker(o), "qa:output")


if __name__ == "__main__":
    unittest.main()
