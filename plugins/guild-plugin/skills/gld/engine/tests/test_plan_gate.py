"""Stage 2 — the procedure written twice and the plan-gate (scope §2.1, D1–D5, V4: L1–L4, L22, L23).

Same world as test_leader_flow (fake units + c_world.FakeLeader). The leader's own checks
(narrowing D4, D5 row cover, template-mismatch) are session A's (test_leader); here the
engine side: revision 1 = start only, revision 2 written by the engine on a plan answer,
the request facts, the counters, the stage-1 state taken over, the start refusals.
"""

import json
import tempfile
import unittest

from gxengine import codes, driver, instructions, lifecycle, procedure as procmod
from tests import c_world as W
from tests.test_leader_flow import LA, Stage2, events, plan_ok, steps_of

SPECS = W.SPECS
START = ["analyze", "ac-format", "plan"]


stage2_steps = W.stage2_steps


class TwoWrites(Stage2):
    def test_l1_plan_writes_revision_2_and_the_steps_grow(self):
        ld = self.leader()
        seen = {}
        orig = ld.call

        def spy(req):
            seen.setdefault(req.situation, ([s.id for s in req.procedure.steps], req.state["revision"]))
            return orig(req)
        ld.call = spy
        rc = self.run2(ld)
        self.assertEqual(rc, driver.EXIT_OK, self.w.out.getvalue())
        self.assertEqual(seen["plan-gate"], (START, 1))              # revision 1 = start only
        st = self.w.state()
        self.assertEqual(st["revision"], 2)
        ids = [s["id"] for s in st["steps"]]
        self.assertEqual(ids, START + ["implement", "test", "review", "done-gate", "pr"])
        self.assertTrue(all(v == "done" for v in steps_of(st).values()), steps_of(st))
        # both revisions are engine commits on the Issue branch
        log = self.w.log()
        written = events(log, "procedure-written")
        self.assertEqual([w["data"]["revision"] for w in written], [1, 2])
        self.assertEqual(written[0]["data"]["origin"]["template"], "start")
        self.assertEqual(written[1]["data"]["origin"]["template"], "feature")
        self.assertEqual((written[1]["reason"], written[1]["who"]), ("fits-template", "leader"))
        rev1 = json.loads(self.w.wt_git("show", f"{written[0]['data']['commit']}:{SPECS}/procedure.yaml"))
        self.assertEqual([s["id"] for s in rev1["steps"]], START)
        head = json.loads(self.w.wt_git("show", f"HEAD:{SPECS}/procedure.yaml"))
        self.assertEqual((head["revision"], head["origin"]["template"]), (2, "feature"))
        self.assertEqual(st["procedure"]["commit"], written[1]["data"]["commit"])
        # the assumption disclosure comes after the plan answer (§7.4), once
        kinds = [l["data"]["kind"] for l in events(log, "comment")]
        self.assertEqual(kinds.count("assumptions"), 1)
        posted = [json.loads(c["stdin"])["body"] for c in self.w.gh_calls()
                  if c["stdin"] and "assumptions from the analysis" in c["stdin"]]
        self.assertIn("The existing selector sheet is reused.", posted[0])
        # the absolute attempt cap follows the current revision (8 steps × 4)
        self.assertEqual([c["situation"] for c in ld.calls], ["plan-gate", "done-gate"])

    def test_plan_gate_request_facts(self):
        body = "Please show the quiz type. Needs #7 first.\n\n<!-- guild:plan-decision -->\nclose: done in #7\n"
        gh = W.gh_rules()
        gh["rules"][1]["json"]["body"] = body
        gh["rules"].insert(2, {"args": ["api", "repos/acme/app/issues/7"],
                               "json": {"number": 7, "state": "closed", "state_reason": "completed", "labels": []}})
        self.w.set_gh(gh)
        ld = self.leader()
        self.assertEqual(self.run2(ld), driver.EXIT_OK, self.w.out.getvalue())
        req = ld.calls[0]["request"]
        self.assertEqual(req.templates, [{"name": "feature", "version": "c-test-1",
                                          "steps": ["implement", "test", "review", "done-gate", "pr"]}])
        self.assertTrue(req.decision_marker)
        self.assertEqual(req.referenced_issues, [{"number": 7, "state": "CLOSED", "state_reason": "COMPLETED"}])
        self.assertIsNone(req.origin_template)
        self.assertIn("Needs #7 first.", req.issue_md)

    def test_no_marker_from_an_outsider_comment(self):
        gh = W.gh_rules(comments_seq=[[W.collab(9001, body="<!-- guild:plan-decision -->\nx", assoc="NONE")]])
        self.w.set_gh(gh)
        ld = self.leader()
        self.assertEqual(self.run2(ld, mode="unattended"), driver.EXIT_OK, self.w.out.getvalue())
        req = ld.calls[0]["request"]
        self.assertFalse(req.decision_marker)
        self.assertEqual(req.mode, "unattended")

    def test_marker_in_a_collaborator_comment(self):
        gh = W.gh_rules(comments_seq=[[W.collab(9001, body="Decided:\n<!-- guild:plan-decision -->\nno work")]])
        self.w.set_gh(gh)
        ld = self.leader()
        self.assertEqual(self.run2(ld), driver.EXIT_OK, self.w.out.getvalue())
        self.assertTrue(ld.calls[0]["request"].decision_marker)

    def test_l2_l4_rerun_analyze_counts_and_the_leader_goes_again(self):
        ld = self.leader({"plan-gate": [LA("rerun", step="analyze", reason="analysis-gap", note="R2 missing"),
                                        LA("rerun", step="analyze", reason="analysis-gap", note="still"),
                                        plan_ok()]})
        self.assertEqual(self.run2(ld), driver.EXIT_OK, self.w.out.getvalue())
        st = self.w.state()
        self.assertEqual(st["counters"]["plan_rerun"], 2)
        self.assertEqual(st.get("totals", {}).get("leader_calls"), 0)       # not counted (D14)
        self.assertEqual(next(s for s in st["steps"] if s["id"] == "analyze")["latest_attempt"], 3)
        self.assertIn("R2 missing", lifecycle.read_leader_decision(self.w.paths()))
        # the leader input of the third call sees the counter (the enum narrowing is session A's)
        self.assertEqual(ld.calls[2]["request"].state["counters"]["plan_rerun"], 2)
        self.assertEqual([w["data"]["revision"] for w in events(self.w.log(), "procedure-written")], [1, 2])

    def test_human_plan_after_escalate_writes_revision_2_too(self):
        ld = self.leader({"plan-gate": [LA("escalate", reason="needs-human-decision",
                                           recommendation={"answer": "plan", "step": None, "note": "ok"})]})
        self.assertEqual(self.run2(ld), driver.EXIT_NEEDS_HUMAN)
        self.assertEqual(self.w.state()["revision"], 1)
        rc = self.run2(ld, answer={"answer": "plan", "note": "go"})
        self.assertEqual(rc, driver.EXIT_OK, self.w.out.getvalue())
        st = self.w.state()
        self.assertEqual(st["revision"], 2)
        written = events(self.w.log(), "procedure-written")
        self.assertEqual((written[-1]["who"], written[-1]["data"]["revision"]), ("human", 2))


class StartRefusals(Stage2):
    world_kw = {}                                 # the stage-1 template: create-pr, no done-gate

    def test_l23_a_template_without_the_done_gate_is_refused_at_start(self):
        rc = self.run2(self.leader())               # c_world template: create-pr, no done-gate
        self.assertEqual(rc, driver.EXIT_REFUSED, self.w.out.getvalue())
        self.assertIsNone(self.w.state())
        self.assertIn("done-gate", self.w.out.getvalue())

    def test_l23_a_done_gate_not_right_before_create_pr(self):
        steps = stage2_steps()
        gate = steps.pop(-2)
        steps.insert(1, gate)
        self.w = W.World(tempfile.mkdtemp(dir=self._tmp.name), steps=steps)
        self.assertEqual(self.run2(self.leader()), driver.EXIT_REFUSED)

    def test_roles_of_every_usable_template_are_checked_at_start(self):
        self.w = W.World(tempfile.mkdtemp(dir=self._tmp.name), steps=stage2_steps())
        self.w.repo.git("rm", "-q", ".claude/agents/tester.md")
        self.w.repo.commit("drop tester")
        self.assertEqual(self.run2(self.leader()), driver.EXIT_REFUSED)    # review is a template step
        self.assertIn("tester.md", self.w.out.getvalue())
        self.assertIsNone(self.w.state())


class StageOneTakeOver(Stage2):
    world_kw = {}                                 # a state the stage-1 engine wrote

    def test_l22_a_stage_1_state_continues_without_a_new_revision(self):
        high = W.ANALYSIS.replace("risk: low", "risk: high")
        sess = W.FakeSession(self.w, {"analyze": [{"write": {f"{SPECS}/analysis.md": high}}]})
        ld = self.leader()
        # stage 1: the whole procedure at once, the I1 rule stops at plan
        rc = self.w.run(W.units(self.w, session=sess, leader=ld))
        self.assertEqual(rc, driver.EXIT_NEEDS_HUMAN)
        before = self.w.state()
        self.assertEqual((before["stop"]["reason"], before["revision"]), ("plan-gate", 1))
        # the stage-2 engine takes the state over: a human rerun of plan → the leader plan-gate
        rc = self.run2(ld, answer={"answer": "rerun", "step": "plan"}, session=sess)
        self.assertEqual(rc, driver.EXIT_OK, self.w.out.getvalue())
        req = ld.calls[0]["request"]
        self.assertEqual(req.origin_template, "feature")
        self.assertEqual(req.templates, [{"name": "feature", "version": "c-test-1",
                                          "steps": ["implement", "test", "review", "pr"]}])
        st = self.w.state()
        self.assertEqual(st["revision"], 1)
        self.assertEqual(st["procedure"]["commit"], before["procedure"]["commit"])
        self.assertEqual(len(events(self.w.log(), "procedure-written")), 1)


class Grammar(unittest.TestCase):
    """procedure.py stage-2 grammar (D1, D19, STAGE2_OPS)."""

    def setUp(self):
        self.start = instructions.load_start_procedure(stage=2)
        self.cmds = list(W.config()["commands"])
        self.tpl = W.template(stage2_steps())

    def test_build_start_and_attach(self):
        p1 = procmod.build_start(self.start, 42, self.cmds, stage=2)
        self.assertEqual((p1.revision, p1.step_ids, p1.origin["template"]), (1, START, "start"))
        p2 = procmod.attach_template(p1, self.tpl, self.cmds, stage=2)
        self.assertEqual(p2.revision, 2)
        self.assertEqual(p2.step_ids[:3], START)
        self.assertEqual(p2.origin, {"template": "feature", "version": "c-test-1", "start": self.start["version"]})
        self.assertEqual(p2.step("implement").inputs[0], "docs/specs/42/analysis.md")
        with self.assertRaises(procmod.ProcedureError):
            procmod.attach_template(p2, self.tpl, self.cmds, stage=2)          # already attached
        with self.assertRaises(procmod.ProcedureError):
            procmod.build_start(self.start, 42, self.cmds, stage=1)

    def test_d19_template_rules(self):
        self.assertEqual(procmod.template_errors(self.tpl, 2), [])
        self.assertEqual(procmod.template_errors(W.template(), 1), [])
        self.assertTrue(procmod.template_errors(W.template(), 2))             # create-pr without done-gate
        two = stage2_steps()
        two.insert(0, {"id": "gate-0", "check": "done-gate"})
        self.assertTrue(procmod.template_errors(W.template(two), 2))
        plan = stage2_steps()
        plan.insert(0, {"id": "plan-2", "check": "plan-gate"})
        self.assertTrue(procmod.template_errors(W.template(plan), 2))          # plan-gate is the start's

    def test_stage_2_ops_and_done_gate_in_a_procedure(self):
        p2 = procmod.attach_template(procmod.build_start(self.start, 42, self.cmds, stage=2), self.tpl, self.cmds,
                                     stage=2)
        raw = p2.to_json()
        raw["steps"][-1]["op"] = codes.OpKind.RUN_CHILDREN.value
        self.assertTrue(any("not available in stage 2" in e for e in procmod.check(raw, self.cmds, stage=2)))
        raw = p2.to_json()
        gate = raw["steps"].pop(-2)
        raw["steps"].insert(4, gate)
        self.assertTrue(any("done-gate" in e for e in procmod.check(raw, self.cmds, stage=2)))
        # a stage-1 procedure (no done-gate) is still readable by the stage-2 engine (L22)
        p1 = procmod.build(self.start, W.template(), 42, self.cmds)
        self.assertEqual(procmod.check(p1, self.cmds, stage=2), [])


if __name__ == "__main__":
    unittest.main()
