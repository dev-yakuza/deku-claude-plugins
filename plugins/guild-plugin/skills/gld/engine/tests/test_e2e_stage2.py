"""Stage 2 end to end (Q4): the REAL leader (`gxengine.leader.call`, session A) wired into the
REAL driver loop (session B) — driver.Units() defaults, the fake claude for every role AND
leader session, the fake gh executable, a bare remote, a temp repository and the real srt.

The leader answers at the plan-gate (plan → revision 2), at the done-gate (approve → PR,
rerun → back_to) and at needs_leader (blocked → rerun with a note; escalate → needs_human
with a recommendation, the human answers on resume). No paid call.
"""

import json
import os
import unittest

from gxengine import driver, store
from tests import c_world as W
from tests import z_world as Z

SPECS = Z.SPECS
START = ["analyze", "ac-format", "plan"]
TEMPLATE_STEPS = [s["id"] for s in Z.feature_steps(stage=2)]
FULL2 = START + TEMPLATE_STEPS


def steps_of(state):
    return {s["id"]: s["status"] for s in state["steps"]}


def events(log, name):
    return [l for l in log if l["event"] == name]


def leader_scenario(what, structured, cost=0.4, **over):
    """One fake-claude leader session (the stream of the role sessions, init from argv)."""
    scn = {"format": 1, "description": f"Q4 e2e leader: {what}", "stream": Z.STREAM, "init_from_argv": True,
           "structured_output": structured, "actions": [], "result": {"total_cost_usd": cost}}
    scn.update(over)
    return scn


def envelope(answer, reason, step=None, note="", recommendation=None, **extra):
    d = {"answer": answer, "reason": reason, "step": step, "note": note, "recommendation": recommendation}
    d.update(extra)
    return d


def plan_answer(note="The one requirement maps to AC #1; the feature template fits."):
    return envelope("plan", "fits-template", note=note,
                    requirements=[{"row": "R1", "covered": True}], missing_requirements=[],
                    plan={"template": "feature"}, close=None)


def approve_answer(evidence="tests/test_app.py asserts the quiz type flag"):
    # no discovery in these runs → the schema has no `discoveries` field (fill_enums drops it)
    return envelope("approve", "acceptance-met", note="AC #1 is met by the unit test.",
                    ac_verdicts=[{"ac": 1, "status": "met", "evidence": evidence}])


class Base(unittest.TestCase):
    cfg_extra = None

    def setUp(self):
        self.tmp = Z.new_tmp()
        self.addCleanup(Z.rmtree, self.tmp)
        self.w = Z.ZWorld(self.tmp, cfg=Z.config(self.cfg_extra), steps=Z.feature_steps(stage=2))

    def out(self):
        return self.w.out.getvalue()

    def run2(self, answer=None):
        return self.w.run(answer=answer, stage=2)

    def leader(self, what, structured, **over):
        return self.w.add(leader_scenario(what, structured, **over))


class PlanGateDoneGateToPr(Base):
    def test_real_leader_plans_and_approves_through_the_driver(self):
        # a private repository (D27): the review's security discovery may go into the PR body
        rules = W.gh_rules()
        rules["rules"].insert(0, {"args": ["repo", "view", Z.REPO, "--json", "isPrivate"], "json": {"isPrivate": True}})
        self.w.set_gh(rules)
        audit = Z.role_scenario("review-audit")
        audit["structured_output"]["discoveries"] = [
            {"kind": "security", "where": "src/legacy.py", "note": "token compared with ==", "blocks_current_ac": False}]
        self.w.add(Z.role_scenario("analyze"))
        self.leader("plan-gate", plan_answer())
        for st in Z.ROLE_STEPS[1:]:
            self.w.add(audit if st == "review-audit" else Z.role_scenario(st))
        self.leader("done-gate", dict(approve_answer(), discoveries=[{"id": "D1", "disposition": "followup"}]))
        rc = self.run2()
        self.assertEqual(rc, driver.EXIT_OK, self.out())
        st = self.w.state()
        self.assertEqual([s["id"] for s in st["steps"]], FULL2)
        self.assertTrue(all(v == "done" for v in steps_of(st).values()), steps_of(st))
        self.assertIsNone(st["stop"])
        self.assertEqual(st["revision"], 2)
        # both leader sessions were the fake CLI as a judge: the leader schema, no write tools
        calls = self.w.claude_calls()
        self.assertEqual(len(calls), len(Z.ROLE_STEPS) + 2)
        for i in (1, len(calls) - 1):
            argv = calls[i]["argv"]
            self.assertIn("--json-schema", argv)
            instr = argv[argv.index("-p") + 1]
            self.assertIn("Leader instruction — fixed rules", instr)       # session C's frame
            self.assertIn("leader-input.json", instr)
        self.assertIn("situation `plan-gate`", calls[1]["argv"][calls[1]["argv"].index("-p") + 1])
        self.assertIn("situation `done-gate`", calls[-1]["argv"][calls[-1]["argv"].index("-p") + 1])
        # the leader sessions are the check steps' attempts (D13), with brief / facts / in/
        for sid, sit in (("plan", "plan-gate"), ("done-gate", "done-gate")):
            d = self.w.paths().attempt_dir(sid, 1)
            with open(os.path.join(d, "brief.json")) as f:
                brief = json.load(f)
            self.assertEqual((brief["kind"], brief["role"], brief["leader"]["situation"]), ("check", "leader", sit))
            fx = store.read_facts(self.w.paths(), sid, 1)
            self.assertEqual((fx["kind"], fx["outcome"]["status"]), ("check", "done"))
            with open(os.path.join(d, "in", "leader-input.json")) as f:
                inp = json.load(f)
            self.assertEqual(inp["situation"], sit)
        with open(os.path.join(self.w.paths().attempt_dir("plan", 1), "in", "leader-input.json")) as f:
            self.assertEqual([r["row"] for r in json.load(f)["plan_gate"]["requirement_rows"]], ["R1"])
        self.assertTrue(os.path.isfile(os.path.join(self.w.paths().attempt_dir("done-gate", 1), "in", "review.diff")))
        # state.leader_calls: the two check calls, not counted against the cap (D14)
        calls = st["leader_calls"]
        self.assertEqual([(c["situation"], c["answer"], c["counted"]) for c in calls],
                         [("plan-gate", "plan", False), ("done-gate", "approve", False)])
        self.assertEqual((st.get("totals") or {}).get("leader_calls", 0), 0)
        # the leader sessions' cost is in the Issue cost (L25): 8 role sessions × $1 + 2 × $0.4
        self.assertAlmostEqual(st["totals"]["cost_usd"], len(Z.ROLE_STEPS) * 1.0 + 0.8, places=4)
        # revision 2 is an engine commit; the answers went through apply_answer as the leader
        log = self.w.log()
        self.assertEqual([e["data"]["revision"] for e in events(log, "procedure-written")], [1, 2])
        answers = [e for e in events(log, "answer") if e.get("who") == "leader"]
        self.assertEqual([e["data"]["answer"] for e in answers], ["plan", "approve"])
        # the PR body carries the leader's AC verdict table and decision list (V11)
        prs = [c for c in self.w.gh_calls() if c["argv"][:4] == ["api", "-X", "POST", "repos/acme/app/pulls"]]
        self.assertEqual(len(prs), 1)
        body = json.loads(prs[0]["stdin"])["body"]
        self.assertIn("asserts the quiz type flag", body)
        self.assertIn("acceptance-met", body)
        self.assertIn("token compared with ==", body)                  # D1, followup, private repository
        self.assertIn("후속 이슈 후보", body)
        self.assertEqual(len([c for c in self.w.gh_calls() if c["argv"][-1] == "isPrivate"]), 1)
        self.assertTrue(body.rstrip().endswith("Closes #42"))
        self.assertEqual(st["github"]["pr_number"], 77)


class NeedsLeaderBlockedRerun(Base):
    def test_blocked_review_leader_reruns_with_a_note_then_pr(self):
        blocked = Z.role_scenario("review-audit")
        blocked["structured_output"] = dict(Z.review_result(["diff-review"]), status="blocked",
                                            blocked_by={"kind": "missing-input", "note": "the skeleton is stale"})
        self.w.add(Z.role_scenario("analyze"))
        self.leader("plan-gate", plan_answer())
        for st in ["test-cases", "design", "implement", "review-design", "review-tests"]:
            self.w.add(Z.role_scenario(st))
        self.w.add(blocked)
        self.leader("blocked", envelope("rerun", "transient", step="review-audit",
                                        note="Read skeleton.md again; it is current."))
        for st in ["review-audit", "qa"]:
            self.w.add(Z.role_scenario(st))
        self.leader("done-gate", approve_answer())
        rc = self.run2()
        self.assertEqual(rc, driver.EXIT_OK, self.out())
        st = self.w.state()
        self.assertTrue(all(v == "done" for v in steps_of(st).values()), steps_of(st))
        # the needs_leader call is leader/1/ (D13) and counts against the cap (D14)
        k1 = self.w.paths().leader_dir(1)
        with open(os.path.join(k1, "brief.json")) as f:
            brief = json.load(f)
        self.assertEqual((brief["kind"], brief["step"], brief["leader"]["situation"]),
                         ("leader", "review-audit", "blocked"))
        self.assertTrue(os.path.isfile(os.path.join(k1, "in", "failure-summary.md")))
        with open(os.path.join(k1, "in", "leader-input.json")) as f:
            inp = json.load(f)
        self.assertEqual(inp["stopped"]["blocked"]["kind"], "missing-input")
        self.assertIn("review-audit", inp["allowed"]["rerun_steps"])
        self.assertEqual(st["totals"]["leader_calls"], 1)
        self.assertEqual([(c["situation"], c["answer"], c["step"]) for c in st["leader_calls"]],
                         [("plan-gate", "plan", None), ("blocked", "rerun", "review-audit"),
                          ("done-gate", "approve", None)])
        # the note reached the next review-audit attempt as in/leader-decision.md (L7)
        with open(os.path.join(self.w.paths().in_dir("review-audit", 2), "leader-decision.md")) as f:
            self.assertIn("Read skeleton.md again; it is current.", f.read())
        ra = next(s for s in st["steps"] if s["id"] == "review-audit")
        self.assertEqual(ra.get("on_fail_count", 0), 0)
        self.assertEqual(st["github"]["pr_number"], 77)


class DoneGateRerunThenApprove(Base):
    def test_done_gate_rerun_implement_then_approve(self):
        self.w.add(Z.role_scenario("analyze"))
        self.leader("plan-gate", plan_answer())
        for st in Z.ROLE_STEPS[1:]:
            self.w.add(Z.role_scenario(st))
        self.leader("done-gate", envelope("rerun", "real-defect", step="implement", note="Keep x an int.",
                                          ac_verdicts=[{"ac": 1, "status": "unmet", "evidence": "x is 2"}]))
        fix = Z.role_scenario("implement")
        fix["actions"] = [{"op": "write", "path": "src/app.py", "content": "x = 2  # int\n"},
                          {"op": "git", "args": ["commit", "-qam", "fix: keep x an int"]}]
        self.w.add(fix)
        for st in ["review-design", "review-tests", "review-audit", "qa"]:
            self.w.add(Z.role_scenario(st))
        self.leader("done-gate again", approve_answer())
        rc = self.run2()
        self.assertEqual(rc, driver.EXIT_OK, self.out())
        st = self.w.state()
        self.assertTrue(all(v == "done" for v in steps_of(st).values()), steps_of(st))
        self.assertEqual(st["counters"]["done_rerun"], 1)
        dg = next(s for s in st["steps"] if s["id"] == "done-gate")
        self.assertEqual(dg["latest_attempt"], 2)
        imp = next(s for s in st["steps"] if s["id"] == "implement")
        self.assertEqual(imp["latest_attempt"], 2)
        with open(os.path.join(self.w.paths().in_dir("implement", 2), "leader-decision.md")) as f:
            self.assertIn("Keep x an int.", f.read())
        self.assertEqual(st["github"]["pr_number"], 77)


class PlanGateEscalateThenHuman(Base):
    def test_escalate_records_the_recommendation_and_the_human_plans_on_resume(self):
        self.w.add(Z.role_scenario("analyze"))
        rec = {"answer": "plan", "step": None, "note": "The template fits once the owner confirms the scope."}
        self.leader("plan-gate", envelope("escalate", "needs-human-decision", note="Scope needs the owner.",
                                          recommendation=rec, requirements=[{"row": "R1", "covered": True}],
                                          missing_requirements=[], plan=None, close=None))
        rc = self.run2()
        self.assertEqual(rc, driver.EXIT_NEEDS_HUMAN, self.out())
        st = self.w.state()
        self.assertEqual((st["stop"]["status"], st["stop"]["reason"]), ("needs_human", "plan-gate"))
        self.assertEqual(st["stop"]["recommendation"]["answer"], "plan")
        self.assertEqual(st["revision"], 1)
        # the stop comment carries the recommendation (L6)
        posted = [json.loads(c["stdin"])["body"] for c in self.w.gh_calls()
                  if c["stdin"] and "needs-human" in c["stdin"]]
        self.assertTrue(any("plan" in p and "recommend" in p.lower() for p in posted), posted)
        # the human answers plan on resume: revision 2 and the template run to the PR
        for s in Z.ROLE_STEPS[1:]:
            self.w.add(Z.role_scenario(s))
        self.leader("done-gate", approve_answer())
        rc = self.run2(answer={"answer": "plan", "step": None, "reason": None, "note": "go"})
        self.assertEqual(rc, driver.EXIT_OK, self.out())
        st = self.w.state()
        self.assertEqual(st["revision"], 2)
        self.assertTrue(all(v == "done" for v in steps_of(st).values()), steps_of(st))
        self.assertEqual([(c["situation"], c["answer"]) for c in st["leader_calls"]],
                         [("plan-gate", "escalate"), ("done-gate", "approve")])


if __name__ == "__main__":
    unittest.main()
