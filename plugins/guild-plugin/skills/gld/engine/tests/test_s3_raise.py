"""Stage 3 flow — the retry raise, the model layers, what a return hands over (V11, session B2).

TM1–TM5, TM7, TM8 from the driver's side (the ladder itself is session C's: s3_world.FakeLadder)
and the Q8 carry-over 2 / review-q0 D8: which findings reach the step a rerun names.
"""

import unittest

from gxengine import driver
from tests import c_world as W
from tests import s3_world as S

FAIL = W.check_failed


def findings(*items):
    return S.result(verdict="block", checks=[{"id": "test-quality", "result": "fail", "note": "n"}],
                    findings=[{"severity": sev, "file": "src/app.py", "line": None, "text": text}
                              for sev, text in items])


class Raise(S.Stage3):
    def choices(self, step="implement"):
        return [(c["model"], c["effort"], c["resume"]) for c in self.session.calls if c["step"] == step]

    def test_tm1_tm3_tm4_tm5_two_returns_raise_the_effort_three_the_model(self):
        # review blocks twice, the test run is red once: three returns of implement (one per target)
        res = S.FakeResults({"review": [FAIL, FAIL, W.output_format, W.done]})
        runner = S.FakeRunner({"test": [0, 0, 1, 0]})
        self.ok(self.run3(self.leader(), results=res, runner=runner))
        self.assertEqual(self.choices(), [
            ("sonnet", "high", None), ("sonnet", "high", "sess-implement"),
            ("sonnet", "xhigh", "sess-implement"),              # effort changed → --resume stays (Z3, E27)
            ("opus", "xhigh", None)])                           # model changed → always a new session
        s = self.sstep("implement")
        self.assertEqual(s["returns"], 3)
        self.assertNotIn("return_sources", s)                   # worked off
        raised = self.log("model-raised")
        self.assertEqual([(l["step"], l["attempt"]) for l in raised], [("implement", 3), ("implement", 4)])
        self.assertEqual(raised[1]["data"]["raised"], {"effort": ["high", "xhigh"], "model": ["sonnet", "opus"]})
        self.assertEqual(self.brief("implement", 4)["session"]["escalation"], raised[1]["data"])
        from gxengine import store
        self.assertEqual(store.read_facts(self.w.paths(), "implement", 4)["session"]["escalation"], raised[1]["data"])
        # the review ran again and again (retry included): never raised, no return
        self.assertEqual({c[:2] for c in self.choices("review")}, {("sonnet", "medium")})
        self.assertNotIn("returns", self.sstep("review"))
        self.assertNotIn("returns", self.sstep("test"))
        self.assertNotIn("returns", self.sstep("ac-format"))     # §4.4-3 is no return

    def test_tm2_the_top_of_the_ladder_goes_on_capped(self):
        plan = S.plan_ok(reason="high-complexity", models=[{"step": "implement", "model": "opus", "effort": "xhigh"}])
        res = S.FakeResults({"review": [FAIL, FAIL, W.done]})
        self.ok(self.run3(self.leader({"plan-gate": [plan]}), results=res))
        self.assertEqual([c[:2] for c in self.choices()], [("opus", "xhigh")] * 3)
        esc = self.log("model-raised")[0]["data"]
        self.assertEqual((esc["capped"], esc["raised"], esc["returns"]), (True, {"effort": None, "model": None}, 2))
        self.assertEqual(esc["base"], {"model": "opus", "effort": "xhigh", "layer": "plan"})

    def test_tm5_effort_only_keeps_the_session_when_the_ladder_allows_it(self):
        self.ladder = S.FakeLadder(resume_effort_change=True)
        res = S.FakeResults({"review": [FAIL, FAIL, W.done]})
        self.ok(self.run3(self.leader(), results=res))
        self.assertEqual(self.choices(), [("sonnet", "high", None), ("sonnet", "high", "sess-implement"),
                                          ("sonnet", "xhigh", "sess-implement")])

    def test_tm5_without_z3_an_effort_change_is_a_new_session(self):
        self.ladder = S.FakeLadder(resume_effort_change=False)
        res = S.FakeResults({"review": [FAIL, FAIL, W.done]})
        self.ok(self.run3(self.leader(), results=res))
        self.assertEqual(self.choices(), [("sonnet", "high", None), ("sonnet", "high", "sess-implement"),
                                          ("sonnet", "xhigh", None)])

    def test_tm7_rerun_session_is_the_new_base(self):
        res = S.FakeResults({"implement": [W.blocked, W.done]})
        ld = self.leader({"blocked": [S.LA("rerun", step="implement", reason="high-complexity", defer=None,
                                          session={"model": "opus", "effort": "high"})]})
        self.ok(self.run3(ld, results=res))
        self.assertEqual([c[:2] for c in self.choices()], [("sonnet", "high"), ("opus", "high")])
        st = self.state()
        self.assertEqual(st["model_overrides"]["implement"],
                         {"model": "opus", "effort": "high", "layer": "leader", "reason": "high-complexity"})
        self.assertEqual(self.sstep("implement")["returns"], 1)
        ans = [l for l in self.log("answer") if l["code"] == "blocked"][0]
        self.assertEqual(ans["data"]["session"], {"model": "opus", "effort": "high"})

    def test_a_session_the_engine_cannot_use_is_no_answer(self):
        for kw in ({"reason": "transient"}, {"step": "test"}, {"session": {"model": "fable", "effort": "high"}}):
            with self.subTest(**kw):
                self.tearDown()
                self.setUp()
                a = dict({"step": "implement", "reason": "other", "session": {"model": "opus", "effort": "high"}}, **kw)
                ld = self.leader({"blocked": [S.LA("rerun", defer=None, **a)]})
                rc = self.run3(ld, results=S.FakeResults({"review": [W.blocked, W.done]}))
                self.assertEqual(rc, driver.EXIT_NEEDS_HUMAN)
                st = self.state()
                self.assertEqual((st["stop"]["reason"], st["stop"]["leader_failed"]["code"]), ("blocked", "output-format"))
                self.assertNotIn("model_overrides", st)


class OpenLadder(S.Stage3):
    cfg = S.config(allowed_efforts=["low", "medium", "high", "xhigh", "max"])

    def test_tm8_the_repository_opens_max(self):
        plan = S.plan_ok(models=[{"step": "implement", "model": "sonnet", "effort": "xhigh"}])
        res = S.FakeResults({"review": [FAIL, FAIL, W.done]})
        self.ok(self.run3(self.leader({"plan-gate": [plan]}), results=res))
        self.assertEqual([c["effort"] for c in self.session.calls if c["step"] == "implement"], ["xhigh", "xhigh", "max"])


class Returned(S.Stage3):
    """What the returning step reads (in/failure-summary.md) and its brief records."""

    templates = {"feature": [s for s in S.feature_steps()[:4]] + [S.review_step("review-audit", "tester")]
                 + S.tail_steps()}

    def test_done_gate_rerun_hands_over_every_review_blockers_first(self):
        sess = self.sess(review=[{"structured": findings(("minor", "a nit"))}],
                         review_audit=[{"structured": findings(("major", "weak name"), ("blocker", "data is lost"))}])
        ld = self.leader({"done-gate": [S.LA("rerun", step="design", reason="upstream-gap", note="see the audit",
                                            included_fixes=[], discoveries=[]), S.approve()]})
        self.ok(self.run3(ld, session=sess))
        text = self.in_file("design", 2, "failure-summary.md")
        self.assertIn("from step: done-gate (attempt 1)", text)
        self.assertIn("code: none", text)
        self.assertLess(text.index("data is lost"), text.index("weak name"))
        self.assertLess(text.index("weak name"), text.index("a nit"))
        r = self.brief("design", 2)["returned"]
        self.assertEqual((r["from_step"], r["code"]), ("done-gate", None))
        self.assertEqual(r["sources"], [{"step": "review", "attempt": 1, "cause": "leader-rerun"},
                                        {"step": "review-audit", "attempt": 1, "cause": "leader-rerun"}])
        self.assertEqual(self.sstep("design")["returns"], 1)
        # the steps reset along with it got nothing
        self.assertIn("No failure sent this step back", self.in_file("implement", 2, "failure-summary.md"))

    def test_a_stopped_review_reaches_an_earlier_step_even_after_a_restart(self):
        sess = self.sess(review=[{"structured": findings(("blocker", "wrong layer"))}])
        res = S.FakeResults({"review": [W.blocked, W.done]})
        ld = self.leader({"blocked": [S.LA("escalate", reason="needs-human-decision", recommendation={
            "answer": "rerun", "step": "design", "note": ""})]})
        self.assertEqual(self.run3(ld, session=sess, results=res), driver.EXIT_NEEDS_HUMAN)
        self.ok(self.run3(ld, results=res, answer={"answer": "rerun", "step": "design"}))     # a new engine process
        self.assertIn("wrong layer", self.in_file("design", 2, "failure-summary.md"))
        self.assertEqual(self.brief("design", 2)["returned"]["sources"],
                         [{"step": "review", "attempt": 1, "cause": "human-rerun"}])

    def test_the_findings_of_many_reviews_stay_under_the_cap(self):
        big = findings(*[("major", "x" * 600 + str(n)) for n in range(100)])
        sess = self.sess(review=[{"structured": big}], review_audit=[{"structured": big}])
        ld = self.leader({"done-gate": [S.LA("rerun", step="design", reason="upstream-gap", included_fixes=[],
                                            discoveries=[]), S.approve()]})
        self.ok(self.run3(ld, session=sess))
        text = self.in_file("design", 2, "failure-summary.md")
        self.assertLess(len(text), driver.RUN_LOG_TAIL_BYTES + 2000)
        self.assertIn(driver.ROLE_FINDINGS_CUT, text)

    def test_going_on_after_a_new_comment_is_no_return(self):
        self.w.set_gh(W.gh_rules(comments_seq=[[], [], [], [], [W.collab(901)]]))
        ld = self.leader({"new-collaborator-comment": [S.LA("rerun", step="design", reason="assumption-corrected",
                                                            comments=[{"id": 901, "effect": "instruction"}])]})
        self.ok(self.run3(ld))
        stopped = [l for l in self.log("stop") if l["code"] == "new-collaborator-comment"][0]["step"]
        returns = self.sstep("design").get("returns", 0)
        self.assertEqual(returns, 0 if stopped == "design" else 1)


if __name__ == "__main__":
    unittest.main()
