"""K3 review r1 — regression tests for B1–B4, M1–M8 and the minors taken: role paths (P1), never
advance past a developer BLOCKED (P2), 1L in the sandbox, the base gate in `--git-hook` mode, legacy
unattended entries, the execute→test hand-over, dependency mistakes vs environment, copy_ignored on the
evidence comment, EX-ARB scope, branch-only gate-config changes, and `live_execute` end to end."""

import json
import os
import shutil
import subprocess
import unittest

import _util
from _k1 import Clock, git, repo, tmpdir
from _k3 import (FLUTTER_GREEN, FLUTTER_RED, XHarness, auditor, comment, decision, dev, finding, role, suite,
                 wt_repo, XCFG)

from guildcore import checks as CH
from guildcore.adapters.gh import FakeGh, FakeGhWrite
from guildcore.decisions import DecisionWriter
from guildcore.records import audit as AU
from guildcore.records import loopback as LB
from guildcore.records import prbody as PB
from guildcore.records import redact as RD
from guildcore.records.write import GhWriter
from guildcore.roles.runner import RoleResult
from workflows.dev import branching as BR
from workflows.dev import exec_audit as XA
from workflows.dev import handoff as HO
from workflows.dev import ports as PO
from workflows.dev import tripwire as TW
from workflows.dev import vcs as VC
from workflows.dev.stages import base as B
from workflows.dev.stages import execute as X

GREEN = suite(FLUTTER_GREEN)
TL = role("DONE")
GATE = os.path.join(_util.SKILL, "gates", "gate_precommit.py")
KEY = "-----BEGIN RSA PRIVATE KEY-----\nMIIBOgIBAAJBAKj34GkxFhD90vcNLYLInFEX6Ppy1tPf9Cnzj4p4WGeKLs1Pt8Qu\n-----END RSA PRIVATE KEY-----\n"
AKIA = "AKIAABCDEFGHIJKLMNOP"


def run_dir(case, summary=None, name="pr.md"):
    d = tmpdir(case)
    os.makedirs(os.path.join(d, "out"))
    if summary is not None:
        with open(os.path.join(d, "out", name), "w") as fh:
            fh.write(summary)
    return d


def dev_rd(rd, path="pr.md", **kw):
    r = dev(pr_summary_path=path, **kw)
    r.run_dir = rd
    return r


# ---- B1 / m3: role paths and role text --------------------------------------------------------------

class RolePaths(unittest.TestCase):
    def pr_body(self, rd, path):
        h = XHarness(self, roles=[dev_rd(rd, path), TL, auditor()], suites=[GREEN])
        X.run(h.p, "implement")
        return h.gh.fx["prs"][-1]["body"], h

    def test_reviewer_probe_absolute_path_to_gh_hosts_is_refused(self):
        secret_dir = tmpdir(self)
        hosts = os.path.join(secret_dir, "hosts.yml")
        with open(hosts, "w") as fh:
            fh.write("oauth_token: gho_%s\n%s%s\n" % ("a" * 36, KEY, AKIA))
        body, h = self.pr_body(run_dir(self), hosts)
        self.assertNotIn("gho_", body)
        self.assertNotIn("PRIVATE KEY", body)
        self.assertNotIn(AKIA, body)
        self.assertIn("(developer summary missing)", body)
        self.assertIn("role-path-refused", "\n".join(h.bodies()))

    def test_dotdot_and_symlink_refused(self):
        rd = run_dir(self)
        with open(os.path.join(os.path.dirname(rd), "outside.md"), "w") as fh:
            fh.write("OUTSIDE TEXT")
        body, _ = self.pr_body(rd, "../../outside.md")
        self.assertNotIn("OUTSIDE TEXT", body)
        rd2 = run_dir(self)
        os.symlink(os.path.join(os.path.dirname(rd), "outside.md"), os.path.join(rd2, "out", "link.md"))
        body2, _ = self.pr_body(rd2, "link.md")
        self.assertNotIn("OUTSIDE TEXT", body2)

    def test_summary_is_redacted_and_closing_keywords_defused(self):
        rd = run_dir(self, "Built it.\nkey %s\nFixes #99 and closes o/r#98\n" % AKIA)
        body, _ = self.pr_body(rd, "pr.md")
        self.assertIn("Built it.", body)
        self.assertNotIn(AKIA, body)
        self.assertIn("[REDACTED]", body)
        self.assertTrue(body.startswith("Closes #7\n"))
        import re
        self.assertEqual(re.findall(r"(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+(?:[\w.-]+/[\w.-]+)?#\d+", body),
                         ["Closes #7"])

    def test_pem_in_summary_is_redacted_whole(self):
        body, _ = self.pr_body(run_dir(self, "notes\n" + KEY), "pr.md")
        self.assertNotIn("MIIBOgIBAAJ", body)


# ---- B2: a developer BLOCKED never reaches the PR -------------------------------------------------------

class NeverAdvancePastBlocked(unittest.TestCase):
    def test_reviewer_probe_timeout_with_engine_green(self):
        line = "suite timed out at 600000 ms — last running: test/a_test.dart"
        h = XHarness(self, roles=[dev("BLOCKED", line), dev("BLOCKED", line)], suites=[GREEN, GREEN])
        r = X.run(h.p, "implement")
        self.assertNotEqual(r.kind, "ADVANCE")
        self.assertEqual(h.gh.fx["prs"], [])
        self.assertEqual(h.pushes, [])
        self.assertTrue(r.cause.startswith("stagnant loop-back"))           # two timeouts = same cause
        self.assertIn("role-axis: verify not-green — suite timed out", h.body_with("auditor:execute"))

    def test_needs_context_with_green_and_no_judge_stops(self):
        h = XHarness(self, roles=[dev("NEEDS_CONTEXT", "which API?")], suites=[GREEN])
        h.p.judge = None
        r = X.run(h.p, "implement")
        self.assertEqual(r.kind, "PAUSE")
        self.assertEqual(h.gh.fx["prs"], [])
        self.assertEqual([c.role for c in h.calls["roles"]], ["developer"])

    def test_invariant_refuses_an_unreviewed_advance(self):
        h = XHarness(self, roles=[dev(), TL, auditor()], suites=[GREEN])
        orig = X.arbitrate_step
        X.conformance_step, saved = (lambda p, cx, a: role("DONE")), X.conformance_step
        try:
            # a broken auditor step that "skips" the scan must not be able to open a PR
            X.auditor_step, saved_a = (lambda p, cx, a: ([], None, None, set())), X.auditor_step
            reviewed = {}
            X.arbitrate_step = lambda *a, **k: "advance"
            try:
                h.roles = [dev("BLOCKED", "suite timed out at 1 ms — last running: x")]
                with self.assertRaises(B.StageError):
                    X.run(h.p, "implement")
            finally:
                X.auditor_step = saved_a
        finally:
            X.conformance_step = saved
            X.arbitrate_step = orig
        self.assertEqual(h.gh.fx["prs"], [])


# ---- user decision 1: DONE_WITH_CONCERNS → EX-DWC ------------------------------------------------------

class DwcJudgment(unittest.TestCase):
    def test_concern_loops_back_when_judged(self):
        h = XHarness(self, roles=[dev(), role("DONE_WITH_CONCERNS", "M4 mutant not pinned"), auditor(),
                                  dev(), TL, auditor()], suites=[GREEN, GREEN],
                     judges={"EX-DWC": [decision("loop_back", {"verdict": "loop_back", "reason": "a real gap"})]})
        r = X.run(h.p, "implement")
        self.assertEqual(r.kind, "ADVANCE")
        self.assertIn("role-axis: tech-lead DWC — M4 mutant not pinned", h.body_with("auditor:execute"))
        self.assertIn("point: EX-DWC", "\n".join(h.bodies()))

    def test_concern_proceeds_and_stays_on_the_pr(self):
        h = XHarness(self, roles=[dev("DONE_WITH_CONCERNS", "naming could be better"), TL, auditor()], suites=[GREEN],
                     judges={"EX-DWC": [decision("proceed", {"verdict": "proceed", "reason": "cosmetic"})]})
        self.assertEqual(X.run(h.p, "implement").kind, "ADVANCE")
        self.assertIn("naming could be better", h.gh.fx["prs"][-1]["body"])

    def test_no_concern_no_call(self):
        h = XHarness(self, roles=[dev(), TL, auditor()], suites=[GREEN])
        X.run(h.p, "implement")
        self.assertNotIn("EX-DWC", [s.group for s in h.calls["judges"]])


# ---- M1: legacy unattended entries -----------------------------------------------------------------

class LegacyUnattended(unittest.TestCase):
    def test_legacy_lines_survive_every_splice(self):
        legacy = ["- analyze: 가정 X — 사람 확인 요", "- design: 옵션 B — 사람 확인 요"]
        body = "Closes #7\n\n" + PB.UNATTENDED_HEADING + "\n" + "\n".join(legacy) + "\n\n## 다음\nhuman\n"
        block = PB.render_unattended(["test: engine entry"])
        once = PB.splice_unattended(body, block)
        for ln in legacy:
            self.assertIn(ln, once)
        self.assertIn("- test: engine entry", once)
        self.assertIn("## 다음\nhuman", once)
        twice = PB.splice_unattended(once, PB.render_unattended(["test: engine entry", "qa: second"]))
        for ln in legacy:
            self.assertEqual(twice.count(ln), 1)
        self.assertIn("- qa: second", twice)


# ---- M2: execute → test hand-over -------------------------------------------------------------------

class HandOver(unittest.TestCase):
    def test_impl_files_reach_a_fresh_test_ports(self):
        h = XHarness(self, roles=[dev(impl_files=["lib/a.dart", "lib/b.dart"]), TL, auditor()], suites=[GREEN])
        h.p.remote_url = "https://x-access-token:SECRET@github.com/o/r.git"
        r = X.run(h.p, "implement")
        self.assertEqual(r.handoff["impl_files"], ["lib/a.dart", "lib/b.dart"])
        log = "\n".join(h.bodies())
        self.assertIn("push: https:github.com", log)
        self.assertNotIn("SECRET", log)
        fresh = B.Ports(7, h.gh, h.writer, h.decisions, h.clock, XCFG, h.p.root)
        got = HO.fill_from_execute(fresh)
        self.assertEqual(fresh.impl_files, ["lib/a.dart", "lib/b.dart"])
        self.assertEqual((fresh.base, fresh.branch), ("main", "feature/#7-x"))
        self.assertEqual(got["head"], git(h.p.root, "rev-parse", "HEAD"))


# ---- M3: dependency mistakes are the Issue's ----------------------------------------------------------

class DepsClassification(unittest.TestCase):
    def failing_deps(self):
        r = CH.CheckResult(False, 1, False, "Because x depends on y ^9.0.0 which doesn't exist, version solving failed.",
                           [], 60)
        r.proxy = {}
        return r

    def test_branch_changed_manifest_loops_back(self):
        root = wt_repo(self, files={"pubspec.yaml": "name: x\n"}, change={"pubspec.yaml": "name: x\ndependencies:\n  y: ^9.0.0\n"})
        h = XHarness(self, root=root, roles=[dev(), dev()], suites=[GREEN, GREEN],
                     judges={"SAMECAUSE": decision("same", {"verdict": "same"})})
        h.p.deps = self.failing_deps
        r = X.run(h.p, "implement")
        self.assertEqual(r.kind, "PAUSE")                     # a loop-back that stagnated, not an env halt
        self.assertNotEqual(r.fail_class, "prevalidate_env")
        self.assertIn("dependency step failed", h.body_with("auditor:execute"))

    def test_untouched_manifest_is_the_environment(self):
        root = wt_repo(self, files={"pubspec.yaml": "name: x\n"})
        h = XHarness(self, root=root, roles=[dev()], suites=[GREEN])
        h.p.deps = self.failing_deps
        r = X.run(h.p, "implement")
        self.assertEqual((r.kind, r.fail_class), ("FAIL", "prevalidate_env"))


# ---- M4: copy_ignored on the evidence comment ----------------------------------------------------------

class EvidenceCopyIgnored(unittest.TestCase):
    def test_structured_summary_and_exact_values(self):
        secret = "tok_live_0123456789abcdef"
        root = wt_repo(self, files={".gitignore": "lib/env.dart\n"})
        with open(os.path.join(root, "lib", "env.dart"), "w") as fh:
            fh.write('const k = "%s";\n' % secret)
        cfg = dict(XCFG, engine={"effective": {"copy_ignored": ["lib/env.dart"]}})
        raw = "00:01 +0: value is %s\n00:02 +1: All tests passed!\n" % secret
        h = XHarness(self, root=root, config=cfg, roles=[dev(red=["red with " + secret]), TL, auditor()],
                     suites=[suite(raw)])
        try:
            X.run(h.p, "implement")
            ev = h.body_with("test-evidence:step-1")
            self.assertNotIn(secret, ev)
            self.assertIn("runner: flutter", ev)
            self.assertIn("원문 비게시", ev)
            self.assertIn("[REDACTED]", RD.redact("x " + secret))
        finally:
            RD.clear_exact()


# ---- M5: EX-ARB answers only what it was asked -----------------------------------------------------------

class ExArbScope(unittest.TestCase):
    def test_unasked_id_is_ignored_and_logged(self):
        ev = [{"path": "lib/a.dart", "line": 1, "quote": "int a() => 2;"}]
        h = XHarness(self, roles=[dev(), TL, auditor([finding()]), dev(), TL,
                                  auditor([finding(), finding(f="lib/b.dart", text="null deref")])],
                     suites=[GREEN, GREEN],
                     judges={"EX-ARB": [decision("s", {"findings": [{"id": "F1", "verdict": "accept"}], "summary": "s"}),
                                        decision("s", {"findings": [
                                            {"id": "F1", "verdict": "dismiss", "reason": "r", "evidence": ev},
                                            {"id": "F2", "verdict": "accept"}], "summary": "s"})],
                             "IDENT": decision("same", {"verdict": "same"})})
        r = X.run(h.p, "implement")
        self.assertEqual(r.kind, "PAUSE")                 # cap — not an advance by the unasked dismissal of F1
        self.assertNotIn("dismissed", h.body_with("auditor:execute"))
        self.assertIn("point: ignored_verdict", "\n".join(h.bodies()))
        asked = [s for s in h.calls["judges"] if s.group == "EX-ARB"][-1]
        self.assertNotIn('"F1"', [x for k, x in asked.brief_parts if k == "findings"][0])


# ---- M6: only the branch's own gate-config changes ---------------------------------------------------------

class GateConfigBranchOnly(unittest.TestCase):
    CFG0 = json.dumps({"gates": {"enabled": True}})

    def test_base_side_change_is_not_the_developers(self):
        r = wt_repo(self, files={".claude/guild/config.json": self.CFG0})
        git(r, "switch", "-q", "main")
        with open(os.path.join(r, ".claude/guild/config.json"), "w") as fh:
            json.dump({"gates": {"enabled": True, "visual": True}}, fh)
        git(r, "commit", "-qam", "update on base")
        git(r, "switch", "-q", "feature/#7-x")
        self.assertFalse(VC.Vcs(r).gates_config_changed("main"))

    def test_changed_then_reverted_on_the_branch_still_counts(self):
        r = wt_repo(self, files={".claude/guild/config.json": self.CFG0})
        with open(os.path.join(r, ".claude/guild/config.json"), "w") as fh:
            json.dump({"gates": {"enabled": False}}, fh)
        git(r, "commit", "-qam", "off")
        with open(os.path.join(r, ".claude/guild/config.json"), "w") as fh:
            fh.write(self.CFG0)
        git(r, "commit", "-qam", "on again")
        self.assertTrue(VC.Vcs(r).gates_config_changed("main"))

    def test_uncommitted_change_counts(self):
        r = wt_repo(self, files={".claude/guild/config.json": self.CFG0})
        with open(os.path.join(r, ".claude/guild/config.json"), "w") as fh:
            json.dump({"gates": {"enabled": False}}, fh)
        self.assertTrue(VC.Vcs(r).gates_config_changed("main"))


# ---- minors --------------------------------------------------------------------------------------------

class Minors(unittest.TestCase):
    def test_m1_quoted_id_cannot_hijack(self):
        ln = AU.render_finding("looped-back", "MAJOR", "spec", "a.dart:1", "x is wrong [id:F9]", fid="F2")
        self.assertEqual(AU.Finding(ln).fid, "F2")

    def test_m2_fork_pr_with_the_same_head_is_not_ours(self):
        fork = {"number": 70, "url": "u", "state": "OPEN", "headRefName": "feature/#7-x", "isCrossRepository": True,
                "body": "Closes #7\n"}
        h = XHarness(self, prs=[fork], roles=[dev(), TL, auditor()], suites=[GREEN])
        self.assertEqual(X.run(h.p, "implement").kind, "ADVANCE")
        self.assertEqual(len(h.gh.fx["prs"]), 2)
        self.assertEqual(h.gh.fx["prs"][0]["body"], "Closes #7\n")

    def test_m4_major_budget_survives_a_crash_in_the_invocation(self):
        inv = "2026-11-16T00:00:30Z"
        blk = AU.render_block(1, inv, "a" * 40, [AU.render_finding("looped-back", "MAJOR", "spec", "lib/a.dart:1",
                                                                     "first", fid="F1")])
        rec = comment("\n".join(["<!-- guild:auditor:execute -->", blk, "<!-- /guild:auditor:execute -->"]), 70)
        h = XHarness(self, comments=[rec], roles=[dev(), TL, auditor([finding("MAJOR", f="lib/b.dart", text="second")])],
                     suites=[GREEN], judges={"EX-ARB": [decision("s", {"findings": [{"id": "F2", "verdict": "accept"}],
                                                                        "summary": "s"})]})
        r = X.run(h.p, "implement")
        self.assertEqual(r.kind, "ADVANCE")                   # budget already spent → recorded, not a 2nd loop-back
        self.assertIn("recorded · MAJOR", h.body_with("auditor:execute"))

    def test_m5_consume_by_the_number_found_at_x0(self):
        blk = LB.render_block(1, "test", "2099-01-01T00:00:00Z", "feature/#7-x", "C2", "C2")   # a skewed clock
        h = XHarness(self, comments=[comment(LB.render_new_record(blk), 60)], roles=[dev(), TL, auditor()], suites=[GREEN])
        X.run(h.p, "implement")
        self.assertTrue(LB.from_comments(h.gh.comments(7)).latest_active().has("consumed"))

    def test_m7_transient_push_retried_once(self):
        h = XHarness(self, roles=[dev(), TL, auditor()], suites=[GREEN])
        n = {"c": 0}

        def push():
            n["c"] += 1
            if n["c"] == 1:
                raise X.PushProblem("transient", "502")
            return "sha"
        h.p.push_branch = push
        self.assertEqual(X.run(h.p, "implement").kind, "ADVANCE")
        self.assertEqual(n["c"], 2)

    def test_m9_security_words_are_whole_identifier_parts(self):
        self.assertTrue(X.security_hit("final authToken = x;"))
        self.assertTrue(X.security_hit("lib/session_store.dart"))
        self.assertFalse(X.security_hit("authorName tokenizer sessionsx"))

    def test_m10_old_pgp_armor(self):
        self.assertTrue(RD.has_secret("-----BEGIN PGP SECRET KEY BLOCK-----"))

    def test_m14_head_move_is_attributed(self):
        r = repo(self, {"a.txt": "a"})
        before = TW.readings(r, "HEAD")
        git(r, "commit", "-q", "--allow-empty", "-m", "hook commit")
        self.assertEqual(TW.compare(before, TW.readings(r, before["head"]))["verdict"], "attribute")


# ---- M8: exits on the stage ------------------------------------------------------------------------------

class Exits(unittest.TestCase):
    def test_safety_net_evidence_missing_on_open_pr(self):
        root = wt_repo(self, branch="refactor/#7-x")
        pr = {"number": 70, "url": "u", "state": "OPEN", "headRefName": "refactor/#7-x", "body": "Closes #7\n"}
        h = XHarness(self, root=root, prs=[pr], body="<!-- guild:safety-net -->")
        h.p.branch = "refactor/#7-x"
        self.assertEqual(X.run(h.p, "refactor").cause, "safety net evidence missing")

    def test_auditor_unusable_twice(self):
        bad = role("DONE", None, findings=[{"severity": "HUGE"}])
        h = XHarness(self, roles=[dev(), TL, bad, bad], suites=[GREEN])
        self.assertEqual(X.run(h.p, "implement").cause, "auditor scan failed")

    def test_mutation_judged_formatter_proceeds(self):
        def fmt(call):
            with open(os.path.join(h.p.root, "lib", "a.dart"), "w") as fh:
                fh.write("int a() => 9;\n")
            return auditor()
        h = XHarness(self, roles=[dev(), TL, fmt], suites=[GREEN],
                     judges={"MUTATION": decision("formatter", {"verdict": "formatter"})})
        self.assertEqual(X.run(h.p, "implement").kind, "ADVANCE")
        self.assertIn("point: tripwire", "\n".join(h.bodies()))

    def test_consume_write_failure_is_a_defect_pause(self):
        blk = LB.render_block(1, "test", "2026-11-16T00:00:10Z", "feature/#7-x", "C2", "C2")
        h = XHarness(self, comments=[comment(LB.render_new_record(blk), 60)], roles=[dev(), TL, auditor()], suites=[GREEN])
        orig = h.writer.append_block

        def flaky(issue, name, **kw):
            if name == LB.NAME:
                from guildcore.adapters.gh import GhWriteError
                raise GhWriteError("comment:append", "boom", "terminal")
            return orig(issue, name, **kw)
        h.writer.append_block = flaky
        self.assertEqual(X.run(h.p, "implement").cause, "loop-back record not updated")

    def local_h(self, ld):
        cfg = dict(XCFG, local_developer={"enabled": True})
        h = XHarness(self, config=cfg, roles=[dev(tests=["test/a_test.dart"], impl_files=["lib/a.dart"])], suites=[])
        h.p.local_dev = ld
        return h

    def test_1l_restore_failed(self):
        def ld(args):
            return {"state": "none"} if args[0] == "status" else \
                {"state": "fallback", "reason": "restore_failed", "files": ["lib/a.dart"]}
        h = self.local_h(ld)
        self.assertEqual(X.run(h.p, "implement").cause, "local developer left files to check")

    def test_1l_commit_refused_falls_back_to_the_developer(self):
        calls = []

        def ld(args):
            calls.append(args[0])
            if args[0] == "status":
                return {"state": "none"}
            if args[0] == "start":
                return {"state": "local_pass", "tree": "uncommitted", "job_id": "j", "files": ["lib/a.dart"]}
            return {"state": "fallback"}
        h = self.local_h(ld)
        h.p.commit_local = lambda f, t, v="implement": (False, "gate: 인라인 시크릿 추정")
        h.roles += [dev(), TL, auditor()]
        h.suites = [GREEN]
        self.assertEqual(X.run(h.p, "implement").kind, "ADVANCE")
        self.assertIn("revert", calls)
        self.assertIn("note", calls)


# ---- M8 + B3 + B4: live_execute end to end ------------------------------------------------------------

class FakeRunner(object):
    def __init__(self, case, script, drift=None):
        self.case, self.script, self.drift = case, list(script), drift
        self.parent_env = dict(os.environ, GH_TOKEN="ghp_should_never_reach_a_check")
        self.specs, self.rebased = [], 0

    def run_role(self, spec):
        self.specs.append(spec)
        act = self.script.pop(0)
        return act(spec) if callable(act) else act

    def drift_check(self, wt, issue):
        return self.drift

    def rebaseline(self, wt, issue):
        self.rebased += 1


class FakeJudges(object):
    def __init__(self, table=None):
        self.table = table or {}

    def judge(self, spec):
        return self.table[spec.group]


@unittest.skipUnless(os.path.exists(CH.SANDBOX_EXEC), "no sandbox-exec")
class LiveBase(unittest.TestCase):
    def setUp(self):
        self.remote = tmpdir(self)
        git(self.remote, "init", "-q", "--bare", "-b", "main")
        gate_dir = ".claude/guild/gates/scripts/gate_precommit.py"
        self.main = repo(self, {"README.md": "hi\n", "src/a.py": "def a():\n    return 1\n",
                                "tests/test_a.py": "import unittest\nimport sys\nsys.path.insert(0, 'src')\nimport a\n\n"
                                                   "class T(unittest.TestCase):\n    def test_a(self):\n"
                                                   "        self.assertTrue(a.a())\n",
                                "docs/specs/7/skeleton.md": "# s\n", "docs/specs/7/test-cases.md": "| C1 | a |\n",
                                ".claude/guild/config.json": json.dumps({"gates": {"enabled": True}}),
                                gate_dir: open(GATE, encoding="utf-8").read()})
        git(self.main, "remote", "add", "origin", self.remote)
        git(self.main, "push", "-q", "origin", "main")
        git(self.main, "fetch", "-q", "origin")
        git(self.main, "remote", "set-head", "origin", "main")
        self.wt = os.path.join(tmpdir(self), "wt")
        saved = BR.assert_outside_tmp
        BR.assert_outside_tmp = lambda p: None               # the test's temp root stands in for ~/projects
        self.addCleanup(setattr, BR, "assert_outside_tmp", saved)
        self.cfg = {"language": "ko", "commands": {"test": "python3 -m unittest discover -s tests -v"},
                    "visual": {}}
        fx = {"repo": "o/r", "issues": {"7": {"number": 7, "title": "make a better", "body": "b", "state": "OPEN",
                                               "labels": [{"name": "guild:execute"}],
                                               "comments": [comment("<!-- guild:design:output -->\nd\n<!-- /guild:design:output -->", 50)],
                                               "timeline": []}}, "prs": []}
        self.gh = FakeGh(fx)
        self.clock = Clock()
        self.writer = GhWriter(self.gh, FakeGhWrite(self.gh, self.clock), sleep=lambda s: None)
        self.decisions = DecisionWriter(self.writer, 7, self.clock)

    def developer(self, summary="Made a better.\n"):
        def act(spec):
            with open(os.path.join(spec.worktree, "src", "a.py"), "w") as fh:
                fh.write("def a():\n    return 2\n")
            git(spec.worktree, "add", "-A")
            git(spec.worktree, "-c", "core.hooksPath=/dev/null", "commit", "-qm", "feat: a")
            rd = run_dir(self, summary)
            return RoleResult("DONE", None, {"tests": [], "impl_files": ["src/a.py"], "baselines": ["none"],
                                             "branch": spec.branch, "pr_summary_path": "pr.md"}, run_dir=rd)
        return act

    def live(self, script, drift=None, env=None, judges=None, ld=None):
        self.runner = FakeRunner(self, script, drift)
        p = PO.live_execute(7, self.main, "implement", self.cfg, self.clock, self.gh, self.writer, self.decisions,
                            self.runner, FakeJudges(judges), push_url=self.remote, env=env or {},
                            local_dev_py=ld, worktree_path=self.wt)
        p.stage_start = "2026-11-16T00:00:30Z"
        return p



@unittest.skipUnless(os.path.exists(CH.SANDBOX_EXEC), "no sandbox-exec")
class LiveExecute(LiveBase):
    def test_end_to_end_advance(self):
        p = self.live([self.developer(), RoleResult("DONE"), RoleResult("DONE", None, {"findings": []})])
        r = X.run(p, "implement")
        self.assertEqual(r.token(), "OK ADVANCE: test", [s for s in self.gh.fx["issues"]["7"]["comments"]][-1:])
        head = git(self.wt, "rev-parse", "HEAD")
        self.assertEqual(git(self.remote, "rev-parse", "feature/#7-make-a-better"), head)
        pr = self.gh.fx["prs"][-1]
        self.assertTrue(pr["body"].startswith("Closes #7\n"))
        self.assertIn("Made a better.", pr["body"])
        self.assertEqual(pr["baseRefName"], "main")
        self.assertEqual(r.handoff["impl_files"], ["src/a.py"])
        self.assertGreaterEqual(self.runner.rebased, 2)
        self.assertEqual([s.role for s in self.runner.specs], ["developer", "tech-lead", "auditor"])

    def test_drift_before_push_stops(self):
        p = self.live([self.developer(), RoleResult("DONE"), RoleResult("DONE", None, {"findings": []})],
                      drift="path lib/late.txt")
        r = X.run(p, "implement")
        self.assertEqual(r.kind, "PAUSE")
        self.assertIn("drift before the engine push", r.cause)
        self.assertEqual(self.gh.fx["prs"], [])
        self.assertEqual(subprocess.run(["git", "rev-parse", "--verify", "-q", "feature/#7-make-a-better"],
                                        cwd=self.remote, stdout=subprocess.PIPE).returncode, 1)

    def test_base_unusable_and_ambiguous_branch(self):
        r = X.run(self.live([], env={"GLD_SPRINT_BASE": "release/9.9"}), "implement")
        self.assertIn("injected base release/9.9 is not usable", r.cause)
        for b in ("feature/#7-a", "fix/#7-b"):
            git(self.main, "switch", "-q", "-c", b, "main")
            git(self.main, "commit", "-q", "--allow-empty", "-m", "#7 work")
        git(self.main, "switch", "-q", "main")
        from _k3 import decision as dcs
        r2 = X.run(self.live([], judges={"BRANCH": dcs("related", {"verdict": "related"})}), "implement")
        self.assertEqual(r2.cause, "ambiguous branch for #7")

    def test_b3_local_dev_runs_sandboxed_with_a_scrubbed_env(self):
        fake = os.path.join(tmpdir(self), "local_dev.py")
        probe = os.path.expanduser("~/.guild-k3r1-probe-%d" % os.getpid())
        with open(fake, "w") as fh:
            fh.write("import json, os\nwrote = True\ntry:\n    open(%r, 'w').write('x')\nexcept OSError:\n"
                     "    wrote = False\nprint('>>> LOCAL-DEV <<<')\nprint(json.dumps({'state': 'none', "
                     "'gh': bool(os.environ.get('GH_TOKEN')), 'wrote_outside': wrote}))\n" % probe)
        p = self.live([], ld=fake)
        try:
            got = p.local_dev(["status", "--issue", "7"])
        finally:
            if os.path.exists(probe):
                os.remove(probe)
        self.assertEqual((got["gh"], got["wrote_outside"]), (False, False))

    def test_b4_commit_local_runs_the_base_gate_in_git_hook_mode(self):
        p = self.live([])
        with open(os.path.join(self.wt, "src", "key.txt"), "w") as fh:
            fh.write(KEY)
        ok, line = p.commit_local(["src/key.txt"], [], "debug")
        self.assertFalse(ok)
        self.assertTrue(line.startswith("gate:"), line)
        git(self.wt, "restore", "--staged", "src/key.txt")
        os.remove(os.path.join(self.wt, "src", "key.txt"))
        with open(os.path.join(self.wt, "src", "a.py"), "a") as fh:
            fh.write("# fine\n")
        ok2, _ = p.commit_local(["src/a.py"], [], "debug")
        self.assertTrue(ok2)
        self.assertTrue(git(self.wt, "log", "-1", "--format=%s").startswith("fix(#7):"))


if __name__ == "__main__":
    unittest.main()
