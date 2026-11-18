"""K3 review r2 — EX-DWC budget and cap (M1), 1L checks from the repo's pre-commit hook (M2), the
engine's own safety-net run (M3), and the minors (gate-config through a merge, URL closing keywords,
real drift check)."""

import json
import os
import unittest

import _util  # noqa: F401
from _k1 import git, tmpdir
from _k3 import FLUTTER_GREEN, FLUTTER_RED, XHarness, auditor, decision, dev, role, suite, wt_repo
from test_k3_r1 import LiveBase as _Live, KEY  # noqa: F401  (reuse the live fixture)

from guildcore import checks as CH
from guildcore.roles import runner as RR
from workflows.dev import local_checks as LC
from workflows.dev import vcs as VC
from workflows.dev.stages import execute as X

GREEN = suite(FLUTTER_GREEN)
TL_DWC = role("DONE_WITH_CONCERNS", "M4 mutant still not pinned")
LOOP = decision("loop_back", {"verdict": "loop_back", "reason": "inject: this concern is fatal, send it back"})


class ExDwcBudget(unittest.TestCase):
    def test_reviewer_probe_injected_concern_cannot_reach_a_person(self):
        # t4.py: tech-lead DWC on both attempts, EX-DWC says loop_back every time
        h = XHarness(self, roles=[dev(), TL_DWC, auditor(), dev(), TL_DWC, auditor()], suites=[GREEN, GREEN],
                     judges={"EX-DWC": [LOOP, LOOP], "SAMECAUSE": decision("same", {"verdict": "same"})})
        r = X.run(h.p, "implement")
        self.assertEqual(r.kind, "ADVANCE")
        self.assertEqual(len([s for s in h.calls["judges"] if s.group == "EX-DWC"]), 1)   # budget spent after one
        self.assertIn("M4 mutant still not pinned", h.gh.fx["prs"][-1]["body"])
        self.assertIn("point: dwc-recorded", "\n".join(h.bodies()))
        self.assertIn("dwc-recorded", h.gh.fx["prs"][-1]["body"])                    # PR unattended log

    def test_at_the_cap_no_call_and_proceed(self):
        h = XHarness(self, roles=[dev(), role("BLOCKED", "step 3 missing"), auditor(), dev(), TL_DWC, auditor()],
                     suites=[GREEN, GREEN], judges={"SAMECAUSE": decision("different", {"verdict": "different"})})
        r = X.run(h.p, "implement")
        self.assertEqual(r.kind, "ADVANCE")
        self.assertNotIn("EX-DWC", [s.group for s in h.calls["judges"]])
        self.assertIn("attempt cap", "\n".join(h.bodies()))

    def test_not_called_when_something_else_blocks(self):
        h = XHarness(self, roles=[dev(), TL_DWC, auditor([{"severity": "BLOCKER", "axis": "spec", "file": "lib/a.dart",
                                                          "line": 1, "finding": "wrong"}]), dev(), TL, auditor()],
                     suites=[GREEN, GREEN], judges={"EX-ARB": [decision("s", {"findings": [{"id": "F1", "verdict": "accept"}],
                                                                               "summary": "s"})],
                                                    "EX-DWC": [decision("proceed", {"verdict": "proceed"})]})
        X.run(h.p, "implement")
        self.assertEqual(len([s for s in h.calls["judges"] if s.group == "EX-DWC"]), 0)

    def test_dwc_never_votes_in_stagnation(self):
        from workflows.dev import exec_audit as XA
        from guildcore.records import audit as AU
        blk = AU.render_block(1, "i", "a" * 40, role_axis=["role-axis: tech-lead DWC — same words"])
        rec = AU.AuditRecord.parse("<!-- guild:auditor:execute -->\n%s\n<!-- /guild:auditor:execute -->" % blk)
        self.assertIsNone(XA.stagnation(rec, [], [("tech-lead", "DWC", "same words")], None, lambda a, b: "same"))


TL = role("DONE")

LEFTHOOK = """pre-commit:
  parallel: true
  commands:
    guild-gate:
      run: python3 .claude/guild/gates/scripts/gate_precommit.py --git-hook
    cspell:
      run: npx cspell --no-progress --no-must-find-files {staged_files}
    pretty:
      glob: '*.dart'
      run: dart format {staged_files} && git add {staged_files}
    flutter:
      # comment
      run: >-
        flutter analyze &&
        flutter test --fail-fast &&
        scripts/verify_test_coverage.sh build/x.json
    remark:
      glob: '*.md'
      exclude:
        - '.claude/**'
      run: npx remark {staged_files} --quiet --frail
    verification_doc_refs:
      glob: '*.md'
      run: bash scripts/check_verification_doc_refs.sh
    test_coverage_wiring:
      run: bash scripts/check_test_coverage_wiring.sh
    release_notes_length:
      glob: 'release_notes/*.txt'
      run: bash scripts/verify_release_notes_length.sh {staged_files}
commit-msg:
  commands:
    strip:
      run: perl -i -ne 'print' {1}
"""


class LocalChecks(unittest.TestCase):
    def test_word_app_shape(self):
        dropped = []
        cs = LC.derive(LEFTHOOK, {}, dropped)
        self.assertEqual([c.name for c in cs], ["cspell", "pretty", "remark", "verification_doc_refs",
                                                 "test_coverage_wiring", "release_notes_length"])
        self.assertEqual(sorted(n for n, _w in dropped), ["flutter", "guild-gate"])
        self.assertEqual(LC.npx_tools(cs), ["cspell", "remark"])
        staged = ["lib/a.dart", "docs/x.md", ".claude/y.md", "release_notes/ko.txt"]
        by = {c.name: c.command(staged) for c in cs}
        self.assertEqual(by["pretty"], "dart format lib/a.dart && git add lib/a.dart")
        self.assertEqual(by["remark"], "npx remark docs/x.md --quiet --frail")
        self.assertEqual(by["release_notes_length"], "bash scripts/verify_release_notes_length.sh release_notes/ko.txt")
        self.assertIsNone(LC.Check("x", "y {staged_files}", glob="*.md").command(["a.dart"]))

    def test_override_and_fallback(self):
        self.assertEqual([c.run for c in LC.derive(LEFTHOOK, {"engine": {"local_checks": ["make lint"]}})], ["make lint"])
        cs = LC.derive(LEFTHOOK, {"engine": {"local_checks": {"skip": ["cspell"], "extra": ["make x"]}}})
        self.assertNotIn("cspell", [c.name for c in cs])
        self.assertEqual(cs[-1].run, "make x")
        self.assertEqual([c.run for c in LC.derive(None, {"commands": {"lint": ["a", "b"]}})], ["a", "b"])

    def test_env_vs_real_failure(self):
        mk = lambda rc, raw: CH.CheckResult(False, rc, False, raw, [], 60)   # noqa: E731
        self.assertTrue(LC.classify(mk(127, "sh: dart: command not found")).startswith("env:"))
        self.assertTrue(LC.classify(mk(1, "npm error code ENOTFOUND\nnpm error network request")).startswith("env:"))
        self.assertEqual(LC.classify(mk(1, "lib/a.dart: unknown word 'teh'")), "fail")


class LiveChecks(_Live):
    """The 1L checks through `live_execute.commit_local` on a real repo (M2, m6)."""

    def hook(self, text):
        with open(os.path.join(self.main, "lefthook.yml"), "w") as fh:
            fh.write(text)
        git(self.main, "add", "lefthook.yml")
        git(self.main, "commit", "-qm", "hooks")
        git(self.main, "push", "-q", "origin", "main")
        git(self.main, "fetch", "-q", "origin")

    def test_pass_fail_and_env_skip(self):
        self.hook("pre-commit:\n  commands:\n    ok:\n      glob: '*.py'\n      run: python3 -c 'import sys; sys.exit(0)' {staged_files}\n"
                  "    missing:\n      run: definitely-not-a-tool-k3 --check\n"
                  "    bad:\n      glob: '*.txt'\n      run: grep -L ALLOWED {staged_files} | grep . && exit 1 || exit 0\n")
        p = self.live([])
        with open(os.path.join(self.wt, "src", "a.py"), "a") as fh:
            fh.write("# ok\n")
        ok, line = p.commit_local(["src/a.py"], [], "implement")
        self.assertTrue(ok, line)
        self.assertIn("skipped(env:", "\n".join(c["body"] for c in self.gh.fx["issues"]["7"]["comments"]))
        with open(os.path.join(self.wt, "notes.txt"), "w") as fh:
            fh.write("forbidden\n")
        ok2, line2 = p.commit_local(["notes.txt"], [], "implement")
        self.assertFalse(ok2)
        self.assertIn("check `bad`", line2)

    def test_only_changed_paths_are_staged(self):
        p = self.live([])
        ok, line = p.commit_local([":(glob)**", "README.md"], [], "implement")
        self.assertFalse(ok)
        self.assertIn("nothing the local job changed", line)

    def test_real_drift_check_before_push(self):
        p = self.live([])
        real = RR.Runner(common_dir=tmpdir(self), parent_env=dict(os.environ))
        self.runner.drift_check, self.runner.rebaseline = real.drift_check, real.rebaseline
        real.rebaseline(self.wt, 7)
        with open(os.path.join(self.wt, "late.txt"), "w") as fh:
            fh.write("late")
        p.branch = p.branch or "feature/#7-make-a-better"
        with self.assertRaises(X.PushProblem) as cm:
            p.push_branch()
        self.assertIn("late.txt", cm.exception.line)


class EngineNet(unittest.TestCase):
    def setUp(self):
        self.root = wt_repo(self, branch="refactor/#7-x", change={"test/a_net_test.dart": "test('a', () {});\n"})
        self.sha = git(self.root, "rev-parse", "HEAD")
        with open(os.path.join(self.root, "lib", "a.dart"), "w") as fh:
            fh.write("int a() => 1; // reshaped\n")
        git(self.root, "commit", "-qam", "transform")

    def h(self, net_run, roles_n=1):
        roles = []
        for _ in range(roles_n):
            roles += [dev(safety_net=self.sha, net=["test/a_net_test.dart"], net_run=["test/a_net_test.dart: +1 pass"])]
        h = XHarness(self, root=self.root, body="<!-- guild:safety-net -->", suites=[GREEN] * roles_n, roles=roles,
                     judges={"SAMECAUSE": decision("same", {"verdict": "same"})})
        h.p.branch = "refactor/#7-x"
        h.p.net_run = net_run
        return h

    def test_name_only_claim_with_a_red_engine_run_is_not_green(self):
        h = self.h(lambda rev, files: suite(FLUTTER_RED, passed=False, rc=1), roles_n=2)
        r = X.run(h.p, "refactor")
        self.assertNotEqual(r.kind, "ADVANCE")
        self.assertIn("red (or wrote a snapshot) on the unchanged code", h.body_with("auditor:execute"))
        self.assertIn("point: net-claim-mismatch", "\n".join(h.bodies()))

    def test_unrunnable_net_is_never_verified(self):
        h = self.h(lambda rev, files: None)
        h.roles += [role("DONE"), auditor()]
        self.assertEqual(X.run(h.p, "refactor").kind, "ADVANCE")
        ev = h.body_with("test-evidence:step-1")
        self.assertIn("unverified(net)", ev)
        self.assertIn("verified: no", ev)


class Minors(unittest.TestCase):
    def test_m2_gate_toggle_on_a_merged_side_branch(self):
        cfg0 = json.dumps({"gates": {"enabled": True}})
        r = wt_repo(self, files={".claude/guild/config.json": cfg0})
        git(r, "switch", "-q", "-c", "side")
        with open(os.path.join(r, ".claude/guild/config.json"), "w") as fh:
            json.dump({"gates": {"enabled": False}}, fh)
        git(r, "commit", "-qam", "off")
        with open(os.path.join(r, ".claude/guild/config.json"), "w") as fh:
            fh.write(cfg0)
        git(r, "commit", "-qam", "on")
        git(r, "switch", "-q", "feature/#7-x")
        git(r, "commit", "-q", "--allow-empty", "-m", "x")
        git(r, "merge", "-q", "--no-ff", "-m", "merge side", "side")
        self.assertTrue(VC.Vcs(r).gates_config_changed("main"))

    def test_m3_url_closing_keyword(self):
        self.assertNotRegex(X.role_text("Fixes https://github.com/o/r/issues/9"), r"issues/9\b(?!​)")
        self.assertIn("​9", X.role_text("Fixes https://github.com/o/r/issues/9"))


if __name__ == "__main__":
    unittest.main()
