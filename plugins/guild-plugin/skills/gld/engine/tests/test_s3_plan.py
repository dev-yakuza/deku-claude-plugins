"""Stage 3 flow — templates, the plan answer and the new in/ files (V2 · V3 · V4 wiring, session B2).

TY1–TY4, TC9, TM6 and TC10 from the driver's side: which templates the plan-gate request
carries, what a plan answer writes (one revision, catalog additions, model overrides), what
the evidence runs get, what the roles read. The other sessions' functions are the doubles of
tests/s3_world.py.
"""

import unittest

from gxengine import codes, driver, lifecycle, statemachine
from tests import c_world as W
from tests import s3_world as S


class Templates(S.Stage3):
    def plan_request(self, analysis, leader=None):
        ld = leader or self.leader({"plan-gate": [S.LA("escalate", recommendation={
            "answer": "escalate", "step": None, "note": ""})]})
        self.run3(ld, session=self.sess(analyze=[{"write": {f"{S.SPECS}/analysis.md": analysis}}]))
        return ld.calls[0]["request"]

    def test_ty1_bug_gets_the_bug_template_only(self):
        req = self.plan_request(S.analysis("bug"))
        self.assertEqual([t["name"] for t in req.templates], ["bug"])
        self.assertEqual(req.templates_unusable, [])
        self.assertEqual(req.plan_role_steps, ["reproduce", "fix", "review"])
        self.assertIsNone(req.origin_template)

    def test_ty2_the_safety_net_field_picks_the_refactor_template(self):
        for net, name in (("none", "refactor"), ("with-refactor", "refactor-net"), ("only", "safety-net")):
            with self.subTest(net=net):
                self.tearDown()
                self.setUp()
                req = self.plan_request(S.analysis("refactor", net))
                self.assertEqual([t["name"] for t in req.templates], [name])

    def test_ty3_docs_and_chore_have_no_template(self):
        req = self.plan_request(S.analysis("docs"))
        self.assertEqual(req.templates, [])
        self.assertEqual(req.plan_role_steps, [])

    def test_the_catalog_rows_say_what_this_repository_can_run(self):
        req = self.plan_request(S.analysis())
        rows = {c["id"]: c for c in req.catalog}
        self.assertNotIn("fix-discovery", rows)                     # the fix class is never requestable
        self.assertTrue(rows["ux-review"]["usable"])
        self.assertFalse(rows["i18n-review"]["usable"])             # no .claude/agents/i18n.md
        self.assertEqual(set(rows["ux-review"]), {"id", "role", "class", "summary", "usable"})

    def test_an_unreadable_analysis_goes_back_to_analyze_once_z6(self):
        # coordinator decision Z6 (fail-closed): a plan-gate on an analysis that is no stage-3 analysis sends the
        # start procedure back to analyze without a leader call; the second time a human decides
        ld = self.leader()
        rc = self.run3(ld, session=self.sess(analyze=[{"write": {f"{S.SPECS}/analysis.md": "type: nonsense\n"}}]))
        self.assertEqual(rc, driver.EXIT_NEEDS_HUMAN)
        self.assertEqual(ld.calls, [])
        back = [l for l in self.log("back-to") if (l.get("data") or {}).get("reason") == driver.REANALYZE_REASON]
        self.assertEqual([(l["data"]["target"], l["data"]["cause"]) for l in back], [("analyze", "plan")])
        st = self.state()
        self.assertEqual(next(s for s in st["steps"] if s["id"] == "analyze")["latest_attempt"], 2)
        self.assertEqual((st["stop"]["status"], st["stop"]["reason"]), ("needs_human", "plan-gate"))


class Unusable(S.Stage3):
    cfg = S.config(path_rules=[S.SAFETY_NET])            # no test-code rule

    def test_ty4_the_template_is_unusable_and_the_reason_is_shown(self):
        ld = self.leader({"plan-gate": [{"called": False}]})
        rc = self.run3(ld, session=self.sess(analyze=[{"write": {f"{S.SPECS}/analysis.md": S.analysis("bug")}}]))
        self.assertEqual(rc, driver.EXIT_NEEDS_HUMAN)
        req = ld.calls[0]["request"]
        self.assertEqual(req.templates, [])
        self.assertEqual([u["name"] for u in req.templates_unusable], ["bug"])
        self.assertIn("test-code", req.templates_unusable[0]["reasons"][0])
        self.assertIn("templates unusable: bug", self.state()["stop"]["note"])
        start = self.log("issue-start")[0]
        self.assertEqual(start["data"]["templates_unusable"][0]["name"], "bug")
        # a human may name another template, never the unusable one
        rc = self.run3(self.leader(), answer={"answer": "plan", "template": "bug"})
        self.assertEqual(rc, driver.EXIT_REFUSED)
        self.assertIn("cannot be used", self.w.out.getvalue())
        self.ok(self.run3(self.leader(), answer={"answer": "plan", "template": "feature"}))
        self.assertEqual(self.procedure()["origin"]["template"], "feature")


class MissingRole(S.Stage3):
    templates = {"bug": [dict(S.review_step(back="review"), id="review", role="nobody")] + S.tail_steps()}

    def test_a_template_whose_role_cannot_run_is_unusable(self):
        ld = self.leader()
        self.ok(self.run3(ld))
        reasons = ld.calls[0]["request"].templates_unusable[0]
        self.assertEqual(reasons["name"], "bug")
        self.assertTrue(any("nobody" in r for r in reasons["reasons"]), reasons)


class PlanAnswer(S.Stage3):
    def test_one_revision_with_source_and_stage3_state(self):
        self.ok(self.run3(self.leader()))
        st = self.state()
        self.assertEqual(st["revision"], 2)
        written = self.log("procedure-written")
        self.assertEqual([(l["data"]["revision"], l["data"]["source"]) for l in written],
                         [(1, "start"), (2, "leader-plan")])
        self.assertFalse(written[1]["data"]["candidate"])
        self.assertTrue(all(v == "done" for v in S.steps_of(st).values()))

    def test_tc9_tc10_adjust_goes_in_with_the_plan(self):
        plan = S.plan_ok(adjust=[{"op": "add", "step": "product-review", "trigger": "scope-question", "note": "n"},
                                 {"op": "add", "step": "ux-review", "trigger": "ui-change", "note": "n"}])
        self.ok(self.run3(self.leader({"plan-gate": [plan]}), session=self.sess(
            product_review=[{"write": {f"{S.SPECS}/product.md": "p\n"}}])))
        st = self.state()
        ids = [s["id"] for s in self.procedure()["steps"]]
        self.assertEqual(ids[3:8], ["product-review", "design", "implement", "test", "ux-review"])
        self.assertEqual(st["revision"], 2)                      # one revision for the whole plan
        self.assertEqual([(a["step"], a["source"], a["from_step"], a["revision"]) for a in st["catalog_adds"]],
                         [("product-review", "leader-plan", None, 2), ("ux-review", "leader-plan", None, 2)])
        by = {s["id"]: s for s in self.procedure()["steps"]}
        for later in ("design", "implement", "ux-review", "review"):
            self.assertIn(f"{S.SPECS}/product.md", by[later]["inputs"])
        self.assertTrue(self.procedure()["new_template_candidate"])            # two adjustments
        self.assertTrue(self.log("procedure-written")[1]["data"]["candidate"])

    def test_an_adjust_the_repository_cannot_run_is_refused(self):
        bad = S.plan_ok(adjust=[{"op": "add", "step": "i18n-review", "trigger": "other", "note": ""}])
        self.assertEqual(self.run3(self.leader({"plan-gate": [bad]})), driver.EXIT_NEEDS_HUMAN)
        st = self.state()
        self.assertEqual((st["stop"]["reason"], st["stop"]["leader_failed"]["code"]), ("plan-gate", "output-format"))
        self.assertEqual(st["revision"], 1)

    def test_tm6_models_apply_from_the_first_attempt(self):
        plan = S.plan_ok(reason="high-complexity", models=[{"step": "implement", "model": "opus", "effort": "xhigh"},
                                                           {"step": "review", "model": "opus", "effort": "high"}])
        self.ok(self.run3(self.leader({"plan-gate": [plan]})))
        calls = {c["step"]: c for c in self.session.calls}
        self.assertEqual((calls["implement"]["model"], calls["implement"]["effort"]), ("opus", "xhigh"))
        self.assertEqual((calls["review"]["model"], calls["review"]["effort"]), ("opus", "high"))
        st = self.state()
        self.assertEqual(st["model_overrides"]["implement"],
                         {"model": "opus", "effort": "xhigh", "layer": "plan", "reason": "high-complexity"})
        esc = self.brief("implement", 1)["session"]["escalation"]
        self.assertEqual((esc["base"]["layer"], esc["returns"], esc["capped"]), ("plan", 0, False))

    def test_models_outside_the_template_or_the_allow_list_are_refused(self):
        for m in ({"step": "fix", "model": "opus", "effort": "high"},
                  {"step": "implement", "model": "fable", "effort": "high"}):
            with self.subTest(m=m):
                self.tearDown()
                self.setUp()
                rc = self.run3(self.leader({"plan-gate": [S.plan_ok(models=[m])]}))
                self.assertEqual(rc, driver.EXIT_NEEDS_HUMAN)
                self.assertEqual(self.state()["revision"], 1)
                self.assertNotIn("model_overrides", self.state())

    def test_human_plan_takes_the_type_template(self):
        ld = self.leader({"plan-gate": [{"called": False}]})
        self.assertEqual(self.run3(ld), driver.EXIT_NEEDS_HUMAN)
        self.ok(self.run3(ld, answer={"answer": "plan"}))
        self.assertEqual(self.procedure()["origin"]["template"], "feature")

    def test_human_plan_of_a_type_without_a_template_needs_a_name(self):
        ld = self.leader({"plan-gate": [{"called": False}]})
        s = self.sess(analyze=[{"write": {f"{S.SPECS}/analysis.md": S.analysis("chore")}}])
        self.assertEqual(self.run3(ld, session=s), driver.EXIT_NEEDS_HUMAN)
        self.assertEqual(self.run3(ld, answer={"answer": "plan"}), driver.EXIT_REFUSED)
        self.assertIn("--template", self.w.out.getvalue())
        self.assertEqual(self.state()["stop"]["reason"], "plan-gate")
        self.ok(self.run3(ld, answer={"answer": "plan", "template": "feature"}))

    def test_template_goes_with_plan_only(self):
        ld = self.leader({"plan-gate": [{"called": False}]})
        self.assertEqual(self.run3(ld), driver.EXIT_NEEDS_HUMAN)
        self.assertEqual(self.run3(ld, answer={"answer": "rerun", "template": "feature"}), driver.EXIT_REFUSED)

    def test_l22_a_second_plan_gate_writes_no_revision_and_offers_no_step(self):
        res = S.FakeResults({"review": [W.blocked, W.done]})
        ld = self.leader({"blocked": [S.LA("replan", reason="upstream-gap")]})
        self.ok(self.run3(ld, results=res))
        self.assertEqual(self.state()["revision"], 2)
        second = [c["request"] for c in ld.calls if c["situation"] == "plan-gate"][1]
        self.assertEqual(second.origin_template, "feature")
        self.assertFalse(any(c["usable"] for c in second.catalog))
        self.assertEqual(second.plan_role_steps, ["design", "implement", "review"])


class RoleSessions(S.Stage3):
    def test_the_result_schema_lists_the_requestable_steps(self):
        self.ok(self.run3(self.leader()))
        call = next(c for c in self.session.calls if c["step"] == "implement")
        steps = call["json_schema"]["properties"]["requests"]["items"]["properties"]["step"]["enum"]
        self.assertIn("ux-review", steps)
        self.assertNotIn("fix-discovery", steps)
        self.assertEqual(call["stage"], 3)
        self.assertEqual({j["stage"] for j in self.results.judged}, {3})
        self.assertEqual(self.results.judged[0]["catalog_steps"], steps)

    def test_the_rules_get_the_stage_and_the_catalog(self):
        self.ok(self.run3(self.leader()))
        self.assertEqual({c["stage"] for c in self.rules.calls}, {3})
        self.assertIn("ux-review", self.rules.calls[0]["catalog"])


class BugFlow(S.Stage3):
    RED = {"exit_code": 0, "head": {"exit_code": 1, "timed_out": False, "log_file": "run-head.log"},
           "head_rerun": {"exit_code": 1, "timed_out": False, "log_file": "run-head-rerun.log"},
           "base_run": {"exit_code": 0, "timed_out": False, "log_file": "run-base.log"},
           "evidence": {"kind": "repro-red", "globs": ["tests/test_*.py"],
                        "scope": {"ok": True, "step": "reproduce", "attempts": [1], "outside": []},
                        "overlay": {"base_sha": "a" * 40, "head_sha": "b" * 40, "existed": [],
                                    "files": [{"path": "tests/test_bug.py", "blob": "c" * 40, "base_blob": None}]},
                        "end_tree": {"clean": True, "dirty_files": []}},
           "paths_check": None,
           "logs": {"run-head.log": "".join(f"line {n}\n" for n in range(300)) + "AssertionError: spinner\n"}}

    def run_bug(self):
        s = self.sess(analyze=[{"write": {f"{S.SPECS}/analysis.md": S.analysis("bug")}}],
                      reproduce=[{"write": {"tests/test_bug.py": "red\n"}, "commit": "test: bug"}],
                      fix=[{"write": {"src/app.py": "x = 3\n"}, "commit": "fix: bug"}])
        return self.run3(self.leader({"plan-gate": [S.plan_ok("bug")]}), session=s,
                         runner=S.FakeRunner(runs={"repro-red": [self.RED]}))

    def test_tb1_path_tokens_evidence_run_and_the_evidence_file(self):
        self.ok(self.run_bug())
        by = {s["id"]: s for s in self.procedure()["steps"]}
        self.assertEqual(by["reproduce"]["outputs"], ["tests/test_*.py"])               # the expanded globs
        s3 = {c["step"]: c for c in self.runner.s3}
        # run again before the done-gate (§4.4-3): the same author step and globs (review-q0 D1)
        self.assertEqual(set((i, tuple(g)) for i, g in self.facts.step_files_calls), {("reproduce", ("tests/test_*.py",))})
        self.assertEqual(s3["repro-red"]["step_files"]["attempts"], [1])
        self.assertEqual(s3["repro-red"]["path_globs"], {"test-code": ["tests/test_*.py"], "safety-net": ["tests/net_*.py"]})
        self.assertIsNone(s3["test"]["step_files"])
        self.assertEqual(s3["ac-format"]["plugin_args"], ["--stage", "3"])
        self.assertEqual(s3["test"]["plugin_args"], [])
        text = self.in_file("fix", 1, "repro-evidence.md")
        self.assertIn("attempt 1: passed", text)
        self.assertIn("exit code 1; again: exit code 1", text)
        self.assertIn("tests/test_bug.py", text)
        self.assertIn("AssertionError: spinner", text)
        self.assertNotIn("line 0\n", text)                                        # last 200 lines only
        self.assertIn("None.", self.in_file("fix", 1, "blocking-discoveries.md"))

    def test_vw4_o1_a_flaky_evidence_pass_is_in_the_attempt_end_line(self):
        """The driver copies facts.run.head_flaky (runner: a safety-net-proof run not green, then green) into
        the attempt-end line; nothing else gets the key."""
        s = self.sess(analyze=[{"write": {f"{S.SPECS}/analysis.md": S.analysis("bug")}}],
                      reproduce=[{"write": {"tests/test_bug.py": "red\n"}, "commit": "test: bug"}],
                      fix=[{"write": {"src/app.py": "x = 3\n"}, "commit": "fix: bug"}])
        self.ok(self.run3(self.leader({"plan-gate": [S.plan_ok("bug")]}), session=s,
                          runner=S.FakeRunner(runs={"repro-red": [self.RED], "test": [{"head_flaky": True}]})))
        ends = [(l["step"], l["data"]) for l in self.log("attempt-end")]
        self.assertEqual([d.get("flaky") for st, d in ends if st == "test"], [True])
        self.assertEqual([st for st, d in ends if "flaky" in d], ["test"])

    def test_the_bug_steps_get_the_stage3_defaults(self):
        self.ok(self.run_bug())
        calls = {c["step"]: c for c in self.session.calls}
        self.assertEqual((calls["reproduce"]["model"], calls["reproduce"]["effort"]), ("sonnet", "high"))
        self.assertEqual(calls["reproduce"]["max_budget_usd"], 15.0)


class EvidenceFile(S.Stage3):
    templates = {"feature": [dict(s, inputs=["in:repro-evidence.md", "in:pr-review.md"]) if s["id"] == "implement" else s
                             for s in S.feature_steps()]}

    def test_without_a_run_or_a_review_the_files_say_so(self):
        self.ok(self.run3(self.leader()))
        self.assertIn("No repro-red run", self.in_file("implement", 1, "repro-evidence.md"))
        self.assertIn("No pull request review", self.in_file("implement", 1, "pr-review.md"))


class StageTables(unittest.TestCase):
    def test_stop_status_follows_the_stage(self):
        for r in ("step-add-limit", "step-removal-request", "pr-review"):
            self.assertEqual(statemachine.stop_status(r, 3), "needs_leader")
            self.assertEqual(statemachine.stop_status(r, 2), "needs_human")
        self.assertEqual(statemachine.stop_status("irreversible-change", 3), "needs_human")
        for r in ("rule-unfillable", "base-red"):
            self.assertEqual(statemachine.stop_status(r, 3), "needs_human")
        self.assertFalse(statemachine.escalate_only("step-add-limit", 3))

    def test_the_human_rows(self):
        self.assertEqual(lifecycle.allowed_answers("irreversible-change", stage=3), ["continue", "rerun"])
        self.assertEqual(lifecycle.allowed_answers("step-add-limit", stage=3), ["continue", "escalate"])
        self.assertEqual(lifecycle.allowed_answers("step-removal-request", stage=3), ["skip", "continue", "escalate"])
        self.assertEqual(lifecycle.allowed_answers("pr-review", stage=3), ["continue", "rerun", "escalate"])
        self.assertEqual(codes.allowed_answers_table(2).get("pr-review"), None)


if __name__ == "__main__":
    unittest.main()
