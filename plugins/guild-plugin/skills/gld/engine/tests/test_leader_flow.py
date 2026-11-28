"""Stage 2 — the engine side of the leader (scope §2, V6: needs_leader loop, answers, caps).

Real: git (temp repo + bare remote), store, statemachine, procedure, rules, budget, lifecycle,
github + outbound, fake gh (in process). Faked: session, facts, results, runner, prbody, srt,
canary record (tests/c_world.py) and the leader — `driver.Units.leader` is c_world.FakeLeader
(the A ↔ B contract: leader.call(LeaderRequest) -> LeaderResult). No paid call.
"""

import json
import os
import tempfile
import unittest

from gxengine import budget, codes, driver, lifecycle, store
from tests import c_world as W

SPECS = W.SPECS
LA = W.leader_answer
REC = {"answer": "rerun", "step": "review", "note": "Look at the selector again."}


def steps_of(state):
    return {s["id"]: s["status"] for s in state["steps"]}


def events(log, name):
    return [l for l in log if l["event"] == name]


def plan_ok():
    return LA("plan", reason="fits-template", requirements=[{"row": "R1", "covered": True}],
              missing_requirements=[], plan={"template": "feature"}, close=None)


class Stage2(unittest.TestCase):
    world_kw = {"steps": W.stage2_steps()}      # stage 2: the done-gate right before create-pr (D19)

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.w = W.World(self._tmp.name, **self.world_kw)

    def tearDown(self):
        self._tmp.cleanup()

    def leader(self, script=None, **kw):
        base = {"plan-gate": [plan_ok()], "done-gate": [LA("approve", reason="acceptance-met")]}
        base.update(script or {})
        return W.FakeLeader(self.w, base, **kw)

    def run2(self, leader, answer=None, mode="attended", **units):
        return self.w.run(W.units(self.w, leader=leader, **units), answer=answer, stage=2, mode=mode)

    def in_file(self, step, attempt, name):
        with open(os.path.join(self.w.paths().in_dir(step, attempt), name)) as f:
            return f.read()

    def answers(self):
        return [l for l in self.w.log() if l["event"] == "answer"]


class PlanGateCall(Stage2):
    def test_n1p_the_plan_gate_is_a_leader_call_of_its_check_step(self):
        ld = self.leader()
        rc = self.run2(ld)
        self.assertEqual(rc, driver.EXIT_OK, self.w.out.getvalue())
        st = self.w.state()
        self.assertTrue(all(v == "done" for v in steps_of(st).values()), steps_of(st))
        self.assertEqual([(c["situation"], c["kind"], c["step"]) for c in ld.calls],
                         [("plan-gate", "check", "plan"), ("done-gate", "check", "done-gate")])
        call = st["leader_calls"][0]
        self.assertEqual((call["kind"], call["k"], call["sessions"], call["answer"], call["counted"]),
                         ("check", 1, [1], "plan", False))
        self.assertEqual(st["totals"]["leader_calls"], 0)          # plan-gate is not counted (D14)
        plan = next(s for s in st["steps"] if s["id"] == "plan")
        self.assertEqual(plan["latest_attempt"], 1)                 # the leader's session = attempt 1
        log = self.w.log()
        phases = [l["data"]["phase"] for l in events(log, "leader-call")]
        self.assertEqual(phases, ["start", "end", "start", "end"])         # plan-gate, done-gate
        ans = self.answers()
        self.assertEqual((ans[0]["who"], ans[0]["code"], ans[0]["data"]["answer"]), ("leader", "plan-gate", "plan"))
        self.assertTrue(any(l.get("to") == "needs_leader" for l in events(log, "stop")))
        # the request carried the driver facts (§2.0)
        req = ld.calls[0]["request"]
        self.assertEqual((req.stage, req.mode, req.kind), (2, "attended", "check"))
        self.assertIn("Please show the quiz type.", req.issue_md)
        self.assertEqual(req.leader_decision, lifecycle.NO_DECISION_TEXT)
        p = req.render_paths("check", "plan", 1)
        self.assertEqual(p["in_dir"], self.w.paths().in_dir("plan", 1))
        q = req.render_paths("leader", "review", 3)
        self.assertEqual(q["in_dir"], os.path.join(self.w.paths().issue_dir, "leader", "3", "in"))
        # the leader session cost is in the Issue cost (L25)
        self.assertGreaterEqual(st["totals"]["cost_usd"], 0.25)

    def test_d9_the_leader_had_only_escalate_no_call_needs_human(self):
        ld = self.leader({"plan-gate": [{"called": False}]})
        rc = self.run2(ld)
        self.assertEqual(rc, driver.EXIT_NEEDS_HUMAN)
        st = self.w.state()
        self.assertEqual((st["stop"]["status"], st["stop"]["reason"]), ("needs_human", "plan-gate"))
        self.assertIsNone(st["stop"]["recommendation"])
        self.assertEqual(st.get("leader_calls", []), [])
        self.assertEqual(steps_of(st)["plan"], "needs_human")
        # a human answers in the leader's seat (D17): plan goes on
        rc = self.run2(ld, answer={"answer": "plan", "note": "risk accepted"})
        self.assertEqual(rc, driver.EXIT_OK, self.w.out.getvalue())


class NeedsLeader(Stage2):
    def test_l6_escalate_records_the_recommendation_and_a_human_answers(self):
        res = W.FakeResults({"review": [W.blocked, W.done]})
        ld = self.leader({"blocked": [LA("escalate", reason="needs-human-decision", note="ask the owner",
                                         recommendation=REC)]})
        self.assertEqual(self.run2(ld, results=res), driver.EXIT_NEEDS_HUMAN)
        st = self.w.state()
        stop = st["stop"]
        self.assertEqual((stop["status"], stop["reason"], stop["step"]), ("needs_human", "blocked", "review"))
        self.assertEqual(stop["recommendation"], dict(REC, reason="needs-human-decision"))
        self.assertEqual(steps_of(st)["review"], "needs_human")
        self.assertEqual(st["totals"]["leader_calls"], 1)
        q = lifecycle.pending_question(st, stage=2)
        self.assertEqual(q["recommendation"]["step"], "review")
        self.assertFalse(q["leader_turn"])
        posted = [c["stdin"] for c in self.w.gh_calls() if c["stdin"] and "stopped" in c["stdin"]]
        self.assertTrue(any("leader recommendation" in json.loads(b)["body"] for b in posted))
        # the human picks another answer than recommended — the engine goes on
        rc = self.run2(ld, results=res, answer={"answer": "rerun", "step": "implement", "note": "redo"})
        self.assertEqual(rc, driver.EXIT_OK, self.w.out.getvalue())
        self.assertEqual([a["who"] for a in self.answers()], ["leader", "leader", "human", "leader"])

    def test_l7_blocked_rerun_with_a_note_reaches_the_next_attempt(self):
        res = W.FakeResults({"review": [W.blocked, W.done]})
        ld = self.leader({"blocked": [LA("rerun", step="review", reason="transient", note="Re-read the diff.")]})
        rc = self.run2(ld, results=res)
        self.assertEqual(rc, driver.EXIT_OK, self.w.out.getvalue())
        self.assertIn("Re-read the diff.", self.in_file("review", 2, "leader-decision.md"))
        st = self.w.state()
        rv = next(s for s in st["steps"] if s["id"] == "review")
        self.assertEqual(rv.get("on_fail_count", 0), 0)              # on_fail untouched
        call = [c for c in st["leader_calls"] if c["situation"] == "blocked"][0]
        self.assertEqual((call["kind"], call["k"], call["counted"], call["step"]), ("leader", 1, True, "review"))
        self.assertTrue(os.path.isfile(os.path.join(self.w.paths().issue_dir, "leader", "1", "facts.json")))
        req = [c for c in ld.calls if c["situation"] == "blocked"][0]["request"]
        self.assertIn("situation: blocked", req.failure_summary)
        self.assertIsNone(req.issue_md)                              # not ambiguous → no issue.md (§2.3)

    def test_l8_on_fail_rerun_once_then_a_second_rerun_is_refused(self):
        runner = W.FakeRunner({"test": [1]})
        ld = self.leader({"on-fail-exceeded": [LA("rerun", step="implement", reason="real-defect")]})
        rc = self.run2(ld, runner=runner)
        self.assertEqual(rc, driver.EXIT_NEEDS_HUMAN)
        st = self.w.state()
        test = next(s for s in st["steps"] if s["id"] == "test")
        self.assertEqual(test["on_fail_extra"], 1)                    # the one granted rerun
        # the second on-fail-exceeded: a rerun answer cannot be applied (once per Issue) → leader failed
        self.assertEqual(st["stop"]["reason"], "on-fail-exceeded")
        self.assertEqual(st["stop"]["leader_failed"], {"code": "output-format", "detail": None})
        self.assertEqual(st["totals"]["leader_calls"], 2)
        self.assertEqual(lifecycle.pending_question(st, stage=2)["allowed_answers"], ["replan", "escalate"])
        # Q4 × P5: the leader's failure summary of a red run carries the run.log tail too
        req = [c for c in ld.calls if c["situation"] == "on-fail-exceeded"][0]["request"]
        self.assertIn("fake run test rc=1", req.failure_summary)

    def test_l8_the_leader_gets_the_findings_of_the_failed_review(self):
        # Q7 real run (app-b #687): the summary said only "check 'diff-review' failed"
        review = {"status": "done", "outputs": [], "requests": [], "blocked_by": None, "discoveries": [], "note": "",
                  "verdict": "block", "reviewed": ["src/app.py"],
                  "checks": [{"id": "test-quality", "result": "fail", "note": "one blocker"}],
                  "findings": [{"severity": "blocker", "file": "src/app.py", "line": 93,
                                "text": "dispose() never deletes the controller"}]}
        last = dict(review, findings=[dict(review["findings"][0], text="the third attempt's finding")])
        sess = W.FakeSession(self.w, {"review": [{"structured": review}, {"structured": review},
                                                 {"structured": last}]})
        res = W.FakeResults({"review": [lambda: W.check_failed("required-check-fail", back_to="implement")]})
        ld = self.leader({"on-fail-exceeded": [LA("escalate", reason="repeated-failure", note="n",
                                                  recommendation=dict(REC, step="implement"))]})
        self.assertEqual(self.run2(ld, results=res, session=sess), driver.EXIT_NEEDS_HUMAN)
        req = [c for c in ld.calls if c["situation"] == "on-fail-exceeded"][0]["request"]
        self.assertIn("- step: review (attempt 3)", req.failure_summary)
        body = req.failure_summary.split("````json\n", 1)[1].split("\n````", 1)[0]
        self.assertEqual(json.loads(body), {k: last[k] for k in ("verdict", "checks", "findings")})

    def test_l6_the_leader_gets_blocked_by_of_the_role(self):
        by = {"kind": "ambiguous", "note": "two readings of AC #1"}
        sess = W.FakeSession(self.w, {"review": [{"structured": {"status": "blocked", "blocked_by": by}}]})
        ld = self.leader({"blocked": [LA("escalate", reason="needs-human-decision", note="n", recommendation=REC)]})
        rc = self.run2(ld, results=W.FakeResults({"review": [W.blocked]}), session=sess)
        self.assertEqual(rc, driver.EXIT_NEEDS_HUMAN)
        req = [c for c in ld.calls if c["situation"] == "blocked"][0]["request"]
        body = req.failure_summary.split("````json\n", 1)[1].split("\n````", 1)[0]
        self.assertEqual(json.loads(body), {"blocked_by": by})

    def test_l8_replan_goes_back_to_plan_and_the_plan_gate_again(self):
        runner = W.FakeRunner({"test": [1, 1, 1, 0]})
        ld = self.leader({"on-fail-exceeded": [LA("replan", reason="upstream-gap", note="plan again")]})
        rc = self.run2(ld, runner=runner)
        self.assertEqual(rc, driver.EXIT_OK, self.w.out.getvalue())
        sits = [c["situation"] for c in ld.calls]
        self.assertEqual(sits, ["plan-gate", "on-fail-exceeded", "plan-gate", "done-gate"])
        backs = [l["data"]["target"] for l in events(self.w.log(), "back-to") if l["data"].get("answer") == "replan"]
        self.assertEqual(backs, ["plan"])
        self.assertIn("plan again", lifecycle.read_leader_decision(self.w.paths()))
        self.assertEqual(self.w.state()["leader_calls"][2]["k"], 2)    # the plan step's second attempt

    def test_l9_output_format_twice_and_session_limit_call_the_leader(self):
        res = W.FakeResults({"implement": [W.output_format, W.output_format, W.done]})
        ld = self.leader({"output-format-twice": [LA("rerun", step="implement", reason="transient")]})
        self.assertEqual(self.run2(ld, results=res), driver.EXIT_OK, self.w.out.getvalue())
        self.assertIn("output-format-twice", [c["situation"] for c in ld.calls])
        req = [c for c in ld.calls if c["situation"] == "output-format-twice"][0]["request"]
        self.assertIn("no structured output", req.failure_summary)

    def test_l9_session_limit(self):
        limit = lambda: W.statemachine.Outcome("failed", code="session-limit")  # noqa: E731
        res = W.FakeResults({"implement": [limit, W.done]})
        ld = self.leader({"session-limit": [LA("rerun", step="implement", reason="transient")]})
        self.assertEqual(self.run2(ld, results=res), driver.EXIT_OK, self.w.out.getvalue())
        self.assertEqual([c["situation"] for c in ld.calls].count("session-limit"), 1)

    def test_l12_the_sixth_counted_situation_is_absolute_limit_without_a_call(self):
        res = W.FakeResults({"review": [W.blocked]})
        ld = self.leader({"blocked": [LA("rerun", step="review", reason="transient")]})
        self.assertEqual(self.run2(ld, results=res), driver.EXIT_NEEDS_HUMAN)
        st = self.w.state()
        self.assertEqual(st["stop"]["reason"], "absolute-limit")
        self.assertEqual([c["situation"] for c in ld.calls].count("blocked"), 5)
        self.assertEqual(st["totals"]["leader_calls"], 5)
        self.assertEqual(lifecycle.pending_question(st, stage=2)["allowed_answers"], ["escalate"])

    def test_l13_rule_unfillable_and_base_red_never_call(self):
        cfg = W.config({"path_rules": [{"kind": "risk", "area": "auth", "gate": "security-review",
                                        "globs": ["src/**"]}]})
        self.w = W.World(tempfile.mkdtemp(dir=self._tmp.name), cfg=cfg, steps=W.stage2_steps())
        ld = self.leader()
        self.assertEqual(self.run2(ld), driver.EXIT_NEEDS_HUMAN)
        st = self.w.state()
        self.assertEqual((st["stop"]["status"], st["stop"]["reason"]), ("needs_human", "rule-unfillable"))
        self.assertEqual([c["situation"] for c in ld.calls], ["plan-gate"])
        self.assertFalse(any(l.get("code") == "rule-unfillable" and l.get("to") == "needs_leader"
                             for l in events(self.w.log(), "stop")))

    def test_l13_base_red(self):
        res = W.FakeResults({"test": [lambda: W.stop("base-red")]})
        ld = self.leader()
        self.assertEqual(self.run2(ld, results=res), driver.EXIT_NEEDS_HUMAN)
        st = self.w.state()
        self.assertEqual((st["stop"]["status"], st["stop"]["reason"]), ("needs_human", "base-red"))
        self.assertEqual([c["situation"] for c in ld.calls], ["plan-gate"])
        self.assertEqual(lifecycle.pending_question(st, stage=2)["allowed_answers"], ["rerun", "escalate"])


class Budget(Stage2):
    def test_l10_soft_budget_rerun_once_then_absolute_without_the_leader(self):
        sess = W.FakeSession(self.w, {"analyze": [{"write": {f"{SPECS}/analysis.md": W.ANALYSIS}, "cost": 30.0}],
                                      "implement": [{"write": {"src/app.py": "x = 2\n"}, "commit": "f",
                                                     "cost": 30.0}],
                                      "review": [{"cost": 30.0}]})
        ld = self.leader({"soft-budget": [LA("rerun", step="test", reason="other")]})
        self.assertEqual(self.run2(ld, session=sess), driver.EXIT_NEEDS_HUMAN)
        st = self.w.state()
        self.assertEqual(st["stop"]["reason"], "absolute-limit")
        self.assertEqual([c["situation"] for c in ld.calls].count("soft-budget"), 1)
        # the leader's own costs are in the total (L25): 90 role + plan-gate + soft-budget sessions
        self.assertAlmostEqual(st["totals"]["cost_usd"], 90.5)

    def test_l25_issue_cost_sums_check_attempts_and_leader_folders(self):
        res = W.FakeResults({"review": [W.blocked, W.done]})
        ld = self.leader({"blocked": [LA("rerun", step="review", reason="transient")]}, cost=1.5)
        self.assertEqual(self.run2(ld, results=res), driver.EXIT_OK, self.w.out.getvalue())
        cost, warnings = budget.issue_cost(self.w.paths(), self.w.state())
        # role sessions: analyze, implement, review ×2 at 0.5; leader: plan-gate, blocked, done-gate at 1.5
        self.assertAlmostEqual(cost, 4 * 0.5 + 3 * 1.5)
        self.assertEqual(warnings, [])
        self.assertEqual([c["cost_usd"] for c in self.w.state()["leader_calls"]], [1.5, 1.5, 1.5])


class LeaderFailures(Stage2):
    def test_l14_output_format_failure_goes_to_a_human_with_the_situation(self):
        ld = self.leader({"plan-gate": [{"failed": {"code": "output-format", "detail": "plan-with-gap"},
                                         "sessions": 3}]})
        self.assertEqual(self.run2(ld), driver.EXIT_NEEDS_HUMAN)
        st = self.w.state()
        self.assertEqual((st["stop"]["status"], st["stop"]["reason"]), ("needs_human", "plan-gate"))
        self.assertEqual(st["stop"]["leader_failed"], {"code": "output-format", "detail": "plan-with-gap"})
        call = st["leader_calls"][0]
        self.assertEqual((call["sessions"], call["answer"], call["failed"]), ([1, 2, 3], None, "output-format"))
        self.assertEqual(next(s for s in st["steps"] if s["id"] == "plan")["latest_attempt"], 3)
        q = lifecycle.pending_question(st, stage=2)
        self.assertEqual(q["leader_failed"]["detail"], "plan-with-gap")
        self.assertEqual(q["allowed_answers"], ["plan", "rerun", "close-as-decided", "escalate"])

    def test_l14_session_limit(self):
        ld = self.leader({"plan-gate": [{"failed": {"code": "session-limit", "detail": None}}]})
        self.assertEqual(self.run2(ld), driver.EXIT_NEEDS_HUMAN)
        self.assertEqual(self.w.state()["stop"]["leader_failed"]["code"], "session-limit")

    def test_l14_quota_within_4h_waits_and_calls_again(self):
        slept = []
        ld = self.leader({"plan-gate": [{"quota_reset_at": 1000.0 + 600}, plan_ok()]})
        rc = self.run2(ld, now=lambda: 1000.0, sleep=slept.append)
        self.assertEqual(rc, driver.EXIT_OK, self.w.out.getvalue())
        self.assertEqual(slept, [600.0])
        self.assertEqual([c["situation"] for c in ld.calls].count("plan-gate"), 2)
        call = self.w.state()["leader_calls"][0]
        self.assertEqual((call["sessions"], call["answer"]), ([1, 2], "plan"))   # one call, two sessions

    def test_l14_infra_stop_keeps_needs_leader_and_resume_calls_again(self):
        ld = self.leader({"plan-gate": [{"stop": "infra-stop"}, plan_ok()]})
        self.assertEqual(self.run2(ld), driver.EXIT_NEEDS_LEADER)
        st = self.w.state()
        self.assertEqual((st["stop"]["status"], st["stop"]["reason"]), ("needs_leader", "plan-gate"))
        # D24: a human answer is refused; resume without one calls the leader again
        self.assertEqual(self.run2(ld, answer={"answer": "plan"}), driver.EXIT_REFUSED)
        self.assertEqual(self.run2(ld), driver.EXIT_OK, self.w.out.getvalue())
        self.assertEqual([c["situation"] for c in ld.calls].count("plan-gate"), 2)

    def test_l14_a_control_file_change_is_a_mechanical_stop(self):
        """Was L14 init-mismatch (removed by FC decision D) — the same path with another mechanical stop."""
        ld = self.leader({"plan-gate": [{"stop": "control-file"}]})
        self.assertEqual(self.run2(ld), driver.EXIT_NEEDS_HUMAN)
        st = self.w.state()
        self.assertEqual((st["stop"]["status"], st["stop"]["reason"]), ("needs_human", "control-file"))
        self.assertEqual(lifecycle.pending_question(st, stage=2)["allowed_answers"], ["rerun", "escalate"])

    def test_l15_the_leader_wrote_a_file(self):
        ld = self.leader({"blocked": [{"stop": "judge-wrote-outside-outputs"}]})
        res = W.FakeResults({"review": [W.blocked]})
        self.assertEqual(self.run2(ld, results=res), driver.EXIT_NEEDS_HUMAN)
        st = self.w.state()
        self.assertEqual((st["stop"]["reason"], st["stop"]["step"]), ("judge-wrote-outside-outputs", "review"))
        self.assertEqual(steps_of(st)["review"], "needs_human")

    def test_canary_record_missing_stops_before_the_leader(self):
        ld = self.leader()
        u = {"canary_ok": lambda env, rc, v: (not env.state.get("stop"), "key")}   # fails at the leader turn
        self.assertEqual(self.run2(ld, **u), driver.EXIT_NEEDS_HUMAN)
        self.assertEqual(self.w.state()["stop"]["reason"], "canary-failed")
        self.assertEqual(ld.calls, [])


class Crash(Stage2):
    def test_l21_a_crash_during_the_call_resumes_with_the_leader(self):
        res = W.FakeResults({"review": [W.blocked, W.done]})
        ld = self.leader({"blocked": [{"raise": KeyboardInterrupt()},
                                      LA("rerun", step="review", reason="transient")]})
        with self.assertRaises(KeyboardInterrupt):
            self.run2(ld, results=res)
        st = self.w.state()
        self.assertEqual((st["stop"]["status"], st["stop"]["reason"]), ("needs_leader", "blocked"))
        self.assertIsNone(lifecycle.lock_holder(self.w.paths()))
        self.assertEqual(self.run2(ld, results=res), driver.EXIT_OK, self.w.out.getvalue())
        self.assertEqual([c["situation"] for c in ld.calls].count("blocked"), 2)

    def test_l21_the_kill_after_a_session_lands_in_the_next_leader_folder(self):
        res = W.FakeResults({"review": [W.blocked, W.done]})
        ld = self.leader({"blocked": [{"stop": "infra-stop"}, LA("rerun", step="review", reason="transient")]})
        self.assertEqual(self.run2(ld, results=res), driver.EXIT_NEEDS_LEADER)
        self.assertEqual(self.run2(ld, results=res), driver.EXIT_OK, self.w.out.getvalue())
        ks = [c["k"] for c in self.w.state()["leader_calls"] if c["situation"] == "blocked"]
        self.assertEqual(ks, [1, 2])


class StageOneUntouched(Stage2):
    world_kw = {}                                 # the stage-1 template (stage 1 refuses a done-gate)

    def test_n2p_stage_1_never_calls_the_leader(self):
        ld = self.leader()
        res = W.FakeResults({"review": [W.blocked]})
        rc = self.w.run(W.units(self.w, leader=ld, results=res))
        self.assertEqual(rc, driver.EXIT_NEEDS_HUMAN)
        self.assertEqual(ld.calls, [])
        self.assertFalse(any(l.get("to") == "needs_leader" for l in self.w.log()))
        self.assertEqual(self.w.state()["stop"]["allowed_answers"], ["rerun", "replan", "escalate"])


if __name__ == "__main__":
    unittest.main()
