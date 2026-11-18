"""K3 — the execute stage end to end on a real temp git worktree with the fake GitHub: advance, retry
with tier bump, stagnation, cap, gate INV2, auditor mutation, violation guard, loop-back consumption
(K2 m7 contract + handoff.execute_to_test), disputes, PR splice, push problems, env halts."""

import os
import unittest

import _util  # noqa: F401
from _k3 import (FLUTTER_GREEN, FLUTTER_RED, XHarness, auditor, comment, decision, dev, finding, git, role,
                 suite, wt_repo)

from guildcore.records import audit as AU
from guildcore.records import loopback as LB
from guildcore.records import markers
from workflows.dev import handoff as HO
from workflows.dev.stages import base as B
from workflows.dev.stages import execute as X

GREEN = suite(FLUTTER_GREEN)
RED = suite(FLUTTER_RED, passed=False, rc=1)
TL_DONE = role("DONE")


def exarb(fid="F1", verdict="accept", reason="right", evidence=None, route=None, addendum=None):
    f = {"findings": [{"id": fid, "verdict": verdict, "reason": reason, "evidence": evidence or []}] if fid else [],
         "summary": "s"}
    if route:
        f["developer_route"] = route
        f["addendum"] = addendum or "the API key lives in config"
    return decision("s", f)


class Advance(unittest.TestCase):
    def test_clean_attempt_advances_with_records_in_order(self):
        h = XHarness(self, roles=[dev(), TL_DONE, auditor()], suites=[GREEN])
        r = X.run(h.p, "implement")
        self.assertEqual(r.token(), "OK ADVANCE: test")
        self.assertEqual(h.labels(), ["guild:test"])
        rec = h.audit()
        self.assertEqual(len(rec.blocks), 1)
        self.assertTrue(rec.blocks[0].findings_none)
        self.assertEqual(rec.blocks[0].head, git(h.p.root, "rev-parse", "HEAD"))
        self.assertEqual(rec.blocks[0].invocation, h.p.stage_start)
        ev = h.body_with("test-evidence:step-1")
        self.assertIn("All tests passed!", ev)
        self.assertIn("판정: green", ev)
        pr = h.gh.fx["prs"][-1]
        self.assertTrue(pr["body"].startswith("Closes #7\n"))
        self.assertEqual((pr["headRefName"], pr["baseRefName"]), ("feature/#7-x", "main"))
        self.assertNotIn("guild:auditor:pr", pr["body"])        # D-5.5: no finding → omitted
        self.assertEqual(h.pushes, ["feature/#7-x"])
        self.assertEqual([c.role for c in h.calls["roles"]], ["developer", "tech-lead", "auditor"])
        self.assertEqual(HO.execute_to_test(h.gh.comments(7), h.gh.fx["prs"], 7, h.p.config), [])

    def test_needs_context_without_design(self):
        h = XHarness(self)
        h.gh.fx["issues"]["7"]["comments"] = []
        os.remove(os.path.join(h.p.root, "docs/specs/7/skeleton.md"))
        r = X.run(h.p, "implement")
        self.assertEqual(r.token(), "NEEDS_CONTEXT: design/skeleton not found for #7")
        self.assertEqual(h.calls["roles"], [])


class Retry(unittest.TestCase):
    def test_blocker_retry_bumps_tier_and_settles_fixed(self):
        def redo(call):
            with open(os.path.join(h.p.root, "lib", "a.dart"), "w") as fh:
                fh.write("int a() => 3;\n")
            git(h.p.root, "commit", "-qam", "redo")
            return dev()
        h = XHarness(self, roles=[dev(), TL_DONE, auditor([finding()]), redo, TL_DONE, auditor()],
                     suites=[GREEN, GREEN], judges={"EX-ARB": [exarb()]})
        r = X.run(h.p, "implement")
        self.assertEqual(r.kind, "ADVANCE")
        devs = [c for c in h.calls["roles"] if c.role == "developer"]
        self.assertEqual([c.model for c in devs], ["sonnet", "opus"])
        self.assertIn("auditor BLOCKER lib/a.dart:1", h.calls["roles"][3].inputs["retry.md"])
        rec = h.audit()
        self.assertEqual([[f.token for f in b.findings] for b in rec.blocks], [["looped-back"], ["fixed"]])
        self.assertIn("수정됨: BLOCKER 1", h.gh.fx["prs"][-1]["body"])
        self.assertTrue(any(c[0] == "correction" and c[2] == "auditor" for c in h.captures))
        self.assertEqual(h.calls["judges"][0].model, "opus")

    def test_same_blocker_twice_is_stagnation(self):
        h = XHarness(self, roles=[dev(), TL_DONE, auditor([finding()]), dev(), TL_DONE, auditor([finding(line=4)])],
                     suites=[GREEN, GREEN], judges={"EX-ARB": [exarb()],
                                                    "IDENT": decision("same", {"verdict": "same"})})
        r = X.run(h.p, "implement")
        self.assertEqual(r.kind, "PAUSE")
        self.assertTrue(r.cause.startswith("stagnant loop-back"))
        self.assertIn("guild:needs-human", h.labels())
        self.assertIn("guild:execute", h.labels())
        self.assertTrue(any(c[0] == "stagnation" for c in h.captures))
        self.assertEqual([[f.token for f in b.findings] for b in h.audit().blocks], [["looped-back"], ["recorded"]])

    def test_red_suite_scan_none_then_cap(self):
        h = XHarness(self, roles=[dev(), dev()], suites=[RED, suite(FLUTTER_RED.replace("widget shows title", "other"),
                                                                       passed=False, rc=1)],
                     judges={"SAMECAUSE": decision("different", {"verdict": "different"})})
        r = X.run(h.p, "implement")
        self.assertEqual(r.kind, "PAUSE")
        self.assertIn("suite red", r.cause)
        self.assertIn("execute retries exhausted", "execute retries exhausted for #7")
        blocks = h.audit().blocks
        self.assertTrue(all(b.scan_none for b in blocks))
        self.assertEqual(len(blocks), 2)
        self.assertTrue(any(c[0] == "verify-gap" for c in h.captures))      # dev said DONE, raw red

    def test_major_budget_once(self):
        h = XHarness(self, roles=[dev(), TL_DONE, auditor([finding("MAJOR")]), dev(), TL_DONE,
                                  auditor([finding("MAJOR", f="lib/b.dart", text="other")])],
                     suites=[GREEN, GREEN], judges={"EX-ARB": [exarb(), exarb("F2")]})
        r = X.run(h.p, "implement")
        self.assertEqual(r.kind, "ADVANCE")
        self.assertEqual([[f.token for f in b.findings] for b in h.audit().blocks],
                         [["looped-back"], ["fixed", "recorded"]])

    def test_developer_needs_context_reinvoked_once(self):
        h = XHarness(self, roles=[dev("NEEDS_CONTEXT", "where is the key?"), dev(), TL_DONE, auditor()],
                     suites=[GREEN, GREEN], judges={"EX-ARB": [exarb(None, route="reinvoke")]})
        r = X.run(h.p, "implement")
        self.assertEqual(r.kind, "ADVANCE")
        self.assertIn("the API key lives in config", h.calls["roles"][1].inputs["retry.md"])


class Stops(unittest.TestCase):
    def test_gate_inv2_pause_and_reentry(self):
        h = XHarness(self, roles=[dev("BLOCKED", "gate INV2 — test/a_test.dart (subject removed: lib/a.dart)")],
                     suites=[])
        r = X.run(h.p, "implement")
        self.assertEqual(r.cause, "gate INV2")
        self.assertIn("defect: gate INV2 — test/a_test.dart", h.body_with("needs-human"))
        h.roles = []
        r2 = X.run(h.p, "implement")                      # no dismissal → no spawn
        self.assertEqual(r2.cause, "gate INV2")
        os.makedirs(os.path.join(h.p.root, ".claude/guild/gates"), exist_ok=True)
        with open(os.path.join(h.p.root, ".claude/guild/gates/dismissed.md"), "w") as fh:
            fh.write("- `test/a_test.dart` — renamed on purpose\n")
        h.roles = [dev(), TL_DONE, auditor()]
        h.suites = [GREEN]
        self.assertEqual(X.run(h.p, "implement").kind, "ADVANCE")

    def test_auditor_mutation_writes_a_violation_note(self):
        def mutate(call):
            with open(os.path.join(h.p.root, "lib", "a.dart"), "w") as fh:
                fh.write("int a() => 42;\n")
            return auditor()
        h = XHarness(self, roles=[dev(), TL_DONE, mutate], suites=[GREEN],
                     judges={"MUTATION": decision("mutation", {"verdict": "mutation"})})
        r = X.run(h.p, "implement")
        self.assertEqual(r.cause, "auditor violated read-only")
        note = h.body_with("auditor-violation")
        self.assertIn("lib/a.dart", note)
        self.assertFalse(AU.Violation(note).resolved)
        h.roles = []
        r2 = X.run(h.p, "implement")                       # P0.9 guard on re-entry
        self.assertEqual(r2.cause, "unresolved auditor violation")

    def test_gates_config_change_on_branch(self):
        root = wt_repo(self, files={".claude/guild/config.json": '{"gates": {"enabled": true}}'},
                       change={".claude/guild/config.json": '{"gates": {"enabled": false}}'})
        h = XHarness(self, root=root)
        r = X.run(h.p, "implement")
        self.assertIn(".claude/guild/config.json gates", r.cause)
        self.assertEqual(h.calls["roles"], [])

    def test_unattended_disputed_blocker_and_answer(self):
        h = XHarness(self, roles=[dev(), TL_DONE, auditor([finding()])], suites=[GREEN],
                     judges={"EX-ARB": [exarb(verdict="dismiss", reason="guarded by caller",
                                              evidence=[{"path": "lib/a.dart", "line": 1, "quote": "int a() => 2;"}])]})
        r = X.run(h.p, "implement")
        self.assertEqual(r.cause, "disputed auditor BLOCKER")
        self.assertEqual([f.token for f in h.audit().blocks[0].findings], ["recorded"])
        self.assertIn("guild-answer: D", h.body_with("needs-human"))

    def test_attended_blocker_dismissal_asks(self):
        h = XHarness(self, roles=[dev(), TL_DONE, auditor([finding()])], suites=[GREEN], unattended=False,
                     judges={"EX-ARB": [exarb(verdict="dismiss", reason="r",
                                              evidence=[{"path": "lib/a.dart", "line": 1, "quote": "int a() => 2;"}])]})
        r = X.run(h.p, "implement")
        self.assertEqual(r.kind, "ASK")
        self.assertIn("dismiss auditor BLOCKER F1", r.line)

    def test_push_diverged(self):
        h = XHarness(self, roles=[dev(), TL_DONE, auditor()], suites=[GREEN],
                     push_fail=("diverged", "! [rejected] non-fast-forward"))
        r = X.run(h.p, "implement")
        self.assertEqual(r.cause, "branch diverged from origin")
        self.assertEqual(h.gh.fx["prs"], [])

    def test_env_halt_build_inputs(self):
        s = suite("", passed=False, rc=None)
        s.build_inputs_changed = ["pubspec.yaml"]
        h = XHarness(self, roles=[dev()], suites=[s])
        r = X.run(h.p, "implement")
        self.assertEqual((r.kind, r.fail_class), ("FAIL", "prevalidate_env"))
        self.assertTrue(r.notes[0].startswith("halted: env build-inputs-changed"))
        self.assertIsNone(h.audit())

    def test_deps_step_runs_before_the_suite(self):
        order = []
        h = XHarness(self, roles=[dev(), TL_DONE, auditor()], suites=[GREEN])
        h.p.deps = lambda: order.append("deps") or suite("ok")
        orig = h.p.suite
        h.p.suite = lambda *a: order.append("suite") or orig(*a)
        X.run(h.p, "implement")
        self.assertEqual(order, ["deps", "suite"])


class LoopbackContract(unittest.TestCase):
    """K2 r1-m7 / notes K3-1·2: execute writes `consumed:` on the loop-back block and `loopback: <n>`
    on its audit block; handoff.execute_to_test fails on an unconsumed block."""

    def lb(self):
        blk = LB.render_block(1, "test", "2026-11-16T00:00:10Z", "feature/#7-x", "C2 not covered", "C2")
        return comment(LB.render_new_record(blk), 60)

    def test_consumed_and_audit_number(self):
        h = XHarness(self, comments=[self.lb()], roles=[dev(), TL_DONE, auditor()], suites=[GREEN])
        self.assertIn("C2 not covered", "x C2 not covered")
        r = X.run(h.p, "implement")
        self.assertEqual(r.kind, "ADVANCE")
        rec = LB.from_comments(h.gh.comments(7))
        self.assertTrue(rec.latest_active().has("consumed"))
        self.assertEqual(h.audit().blocks[0].loopback, "1")
        self.assertIn("C2 not covered", h.calls["roles"][0].inputs["loopback.md"])
        self.assertEqual(HO.execute_to_test(h.gh.comments(7), h.gh.fx["prs"], 7, h.p.config), [])

    def test_handoff_flags_not_consumed(self):
        h = XHarness(self, comments=[self.lb()])
        self.assertIn("latest loop-back block not consumed",
                      HO.execute_to_test(h.gh.comments(7), [], 7, h.p.config))

    def test_test_stage_reads_the_number_not_the_clock(self):
        from workflows.dev.stages import loopback as LP
        h = XHarness(self, comments=[self.lb()])
        early = "\n".join(["<!-- guild:auditor:execute -->",
                           AU.render_block(1, "2026-11-16T00:00:01Z", "a" * 40, loopback=1),
                           "<!-- /guild:auditor:execute -->"])
        cs = h.gh.comments(7) + [comment(early, 61)]
        self.assertIsNone(LP.interrupted(cs, "guild:test", ["guild:test"]))
        self.assertIsNotNone(LP.interrupted(h.gh.comments(7), "guild:test", ["guild:test"]))


class Pr(unittest.TestCase):
    def test_existing_pr_is_spliced_not_recreated(self):
        pr = {"number": 70, "url": "https://github.com/o/r/pull/70", "state": "OPEN", "headRefName": "feature/#7-x",
              "body": "Closes #7\n\nhuman text\n"}
        h = XHarness(self, prs=[pr], roles=[dev(), TL_DONE, auditor([finding("MINOR")])], suites=[GREEN])
        r = X.run(h.p, "implement")
        self.assertEqual(r.kind, "ADVANCE")
        self.assertEqual(len(h.gh.fx["prs"]), 1)
        body = h.gh.fx["prs"][0]["body"]
        self.assertIn("human text", body)
        self.assertIn("<!-- guild:auditor:pr -->", body)
        self.assertIn("recorded · MINOR", body)

    def test_draft_unsupported_retried_without(self):
        h = XHarness(self, roles=[dev(), TL_DONE, auditor()], suites=[GREEN])
        h.p.draft = True
        h.w.draft_unsupported = True
        self.assertEqual(X.run(h.p, "implement").kind, "ADVANCE")
        self.assertFalse(h.gh.fx["prs"][-1]["isDraft"])


class Variants(unittest.TestCase):
    def test_debug_needs_a_red_run(self):
        h = XHarness(self, roles=[dev(), dev(red=["00:01 +0 -1: Some tests failed."]), TL_DONE, auditor()],
                     suites=[GREEN, GREEN])
        r = X.run(h.p, "debug")
        self.assertEqual(r.kind, "ADVANCE")
        self.assertIn("debug: no red run", h.audit().blocks[0].role_axis[0])
        self.assertIn("Some tests failed.", h.body_with("test-evidence:step-1"))

    def test_refactor_net_block_in_evidence_and_verified_after_conformance(self):
        root = wt_repo(self, branch="refactor/#7-x", change={"test/a_net_test.dart": "test('a', () {});\n"})
        sha = git(root, "rev-parse", "HEAD")
        with open(os.path.join(root, "lib", "a.dart"), "w") as fh:
            fh.write("int a() => 1; // reshaped\n")
        git(root, "commit", "-qam", "transform")
        h = XHarness(self, root=root, body="<!-- guild:safety-net -->", suites=[GREEN],
                     roles=[dev(safety_net=sha, net=["test/a_net_test.dart"], net_run=["test/a_net_test.dart +1"]),
                            TL_DONE, auditor()])
        h.p.branch = "refactor/#7-x"
        runs = []
        h.p.net_run = lambda rev, files: runs.append((rev, list(files))) or suite(FLUTTER_GREEN)   # K3r2-M3
        r = X.run(h.p, "refactor")
        self.assertEqual(r.kind, "ADVANCE")
        self.assertEqual(runs, [(sha, ["test/a_net_test.dart"]), ("HEAD", ["test/a_net_test.dart"])])
        ev = h.body_with("test-evidence:step-1")
        self.assertIn("engine@%s: test/a_net_test.dart — green" % sha[:12], ev)
        self.assertIn("<!-- guild:safety-net-evidence -->", ev)
        self.assertIn("sha: %s" % sha, ev)
        self.assertIn("verified: yes", ev)

    def test_refactor_net_not_proven_loops_back(self):
        root = wt_repo(self, branch="refactor/#7-x")
        sha = git(root, "rev-parse", "HEAD")                  # the proof holds lib/a.dart's change
        h = XHarness(self, root=root, body="<!-- guild:safety-net -->", suites=[GREEN, GREEN],
                     roles=[dev(safety_net=sha, net=["test/a_test.dart"], net_run=["test/a_test.dart +1"]),
                            dev(safety_net=sha, net=["test/a_test.dart"], net_run=["test/a_test.dart +1"])],
                     judges={"SAMECAUSE": decision("same", {"verdict": "same"})})
        h.p.branch = "refactor/#7-x"
        r = X.run(h.p, "refactor")
        self.assertEqual(r.kind, "PAUSE")
        self.assertIn("re-prove the net", h.audit().blocks[0].role_axis[0])
        self.assertIn("verified: no", h.body_with("test-evidence:step-1"))


if __name__ == "__main__":
    unittest.main()


class LocalAndGates(unittest.TestCase):
    def test_local_pass_is_not_an_attempt_and_sent_back_once(self):
        cfg = dict(__import__("_k3").XCFG, local_developer={"enabled": True})
        calls = []

        def ld(args):
            calls.append(args[0])
            if args[0] == "status":
                return {"state": "none"}
            if args[0] == "start":
                return {"state": "local_pass", "tree": "uncommitted", "job_id": "j1", "files": ["lib/a.dart"],
                        "attempt_count": 2, "model": "qwen"}
            return {"state": "local_pass"}
        h = XHarness(self, config=cfg, suites=[RED, GREEN],
                     roles=[dev(tests=["test/a_test.dart"], impl_files=["lib/a.dart"], red=["00:01 +0 -1: x"]),
                            dev(), TL_DONE, auditor()])
        h.p.local_dev = ld
        h.p.commit_local = lambda files, tests, variant="implement": (True, None)
        r = X.run(h.p, "implement")
        self.assertEqual(r.kind, "ADVANCE")
        self.assertEqual([c.task for c in h.calls["roles"] if c.role == "developer"], ["tests", "implement"])
        blocks = h.audit().blocks
        self.assertEqual(blocks[0].local_pass, "j1")
        self.assertEqual(h.calls["roles"][1].model, "sonnet")           # local pass is not attempt 1
        self.assertIn("note", calls)
        self.assertIn("ack", calls)

    def test_security_convened_on_keyword_and_blocked_loops(self):
        root = wt_repo(self, files={".claude/agents/security.md": "---\nmodel: sonnet\n---\n"},
                       change={"lib/auth_token.dart": "String token() => 'x';\n"})
        h = XHarness(self, root=root, suites=[GREEN, GREEN],
                     roles=[dev(), TL_DONE, auditor(), role("BLOCKED", "token logged in clear"),
                            dev(), TL_DONE, auditor(), role("DONE")],
                     judges={"SAMECAUSE": decision("different", {"verdict": "different"})})
        r = X.run(h.p, "implement")
        self.assertEqual(r.kind, "ADVANCE")
        self.assertEqual([c.role for c in h.calls["roles"]].count("security"), 2)
        self.assertIn("role-axis: security BLOCKED — token logged in clear", h.body_with("auditor:execute"))

    def test_unknown_runner_summary_pauses_env(self):
        h = XHarness(self, roles=[dev()], suites=[suite("ran some things\n")])
        r = X.run(h.p, "implement")
        self.assertEqual(r.kind, "PAUSE")
        self.assertIn("env: other", h.body_with("needs-human"))
