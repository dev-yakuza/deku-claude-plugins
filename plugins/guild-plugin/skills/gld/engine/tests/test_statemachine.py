"""U4 — transitions and counters (statemachine.py, design §4.4, §5, §5.1, §6, §9.2).

Fixed scenarios of scope §5.2 covered here (the state-machine half; the facts that
lead to each Outcome are U7/U8/U9's): S1 on_fail cap, S2 quota wait / stop, S3
session-limit, S4 absolute caps, S11 engine-error, R5 output-format twice, R6 blocked,
R8 I3 owner back_to, V3/V4 §4.4-3 reverify, N1 stage 1 never needs_leader.
"""

import json
import os
import unittest

from gxengine import codes, schema, store
from gxengine import procedure as PR
from gxengine import statemachine as SM
from gxengine.statemachine import Outcome

ENGINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ENGINE, "tests", "fixtures")
H0, H1, H2 = "0" * 40, "1" * 40, "2" * 40
NOW = 1_800_000_000


def load_proc():
    with open(os.path.join(FIX, "procedure", "feature-42.procedure.json"), encoding="utf-8") as f:
        return PR.parse_procedure(f.read())


class Base(unittest.TestCase):
    def setUp(self):
        self.proc = load_proc()
        self.state = store.new_state(42, 1, self.proc.step_ids, H0, totals={"attempts": 0, "cost_usd": 0.0,
                                                                              "leader_calls": 0, "warnings": 0})
        self.events = []
        self.attempts = {}

    def st(self, step_id):
        return next(s for s in self.state["steps"] if s["id"] == step_id)

    def start(self, step_id, head=H1):
        self.assertEqual(SM.next_runnable(self.state, self.proc), step_id)
        n = self.attempts.get(step_id, 0) + 1
        self.attempts[step_id] = n
        self.events += SM.mark_running(self.state, step_id, n, head)

    def finish(self, step_id, outcome, **kw):
        d = SM.apply(self.state, self.proc, step_id, outcome, now=kw.pop("now", NOW), **kw)
        self.events += d.events
        return d

    def run_ok(self, step_id):
        self.start(step_id)
        return self.finish(step_id, Outcome("done"))

    def run_until(self, step_id):
        while SM.next_runnable(self.state, self.proc) != step_id:
            self.run_ok(SM.next_runnable(self.state, self.proc))

    def tearDown(self):
        # Every state the machine leaves behind is a valid state.json; every event a valid log line.
        schema.validate(json.loads(json.dumps(self.state)), "state")
        for ev, fields in self.events:
            store.make_log_line(42, ev, **fields)


class Happy(Base):
    def test_all_steps_done_then_finish(self):
        d = None
        while True:
            nxt = SM.next_runnable(self.state, self.proc)
            if nxt is None:
                break
            d = self.run_ok(nxt)
        self.assertEqual(d.action, "finish")
        self.assertTrue(all(s["status"] == "done" for s in self.state["steps"]))
        self.assertEqual(self.state["totals"]["attempts"], len(self.proc.steps))
        self.assertEqual(self.state["last_head"], H1)

    def test_mark_running_records(self):
        self.start("analyze", head=H2)
        s = self.st("analyze")
        self.assertEqual((s["status"], s["latest_attempt"], s["start_head"]), ("running", 1, H2))
        self.assertEqual(self.events[0][0], "attempt-start")
        self.assertEqual(self.events[1], ("status", {"step": "analyze", "attempt": 1, "from": "pending", "to": "running"}))

    def test_next_is_returned(self):
        self.start("analyze")
        d = self.finish("analyze", Outcome("done"))
        self.assertEqual((d.action, d.step), ("next", "ac-format"))


class Guards(Base):
    def test_apply_needs_running(self):
        with self.assertRaises(SM.StateError):
            SM.apply(self.state, self.proc, "analyze", Outcome("done"))

    def test_mark_running_needs_pending(self):
        self.start("analyze")
        with self.assertRaises(SM.StateError):
            SM.mark_running(self.state, "analyze", 2, H1)

    def test_attempt_numbers_do_not_go_back(self):
        self.st("analyze")["latest_attempt"] = 3
        with self.assertRaises(SM.StateError):
            SM.mark_running(self.state, "analyze", 2, H1)

    def test_misaligned_state(self):
        self.state["steps"].pop()
        with self.assertRaises(SM.StateError):
            SM.next_runnable(self.state, self.proc)
        self.state = store.new_state(42, 2, self.proc.step_ids, H0)
        with self.assertRaises(SM.StateError):
            SM.next_runnable(self.state, self.proc)

    def test_nothing_runs_past_an_unsettled_step(self):
        self.start("analyze")
        with self.assertRaises(SM.StateError):
            SM.next_runnable(self.state, self.proc)

    def test_outcome_validation(self):
        bad = [dict(status="weird"), dict(status="failed"), dict(status="failed", code="oops"),
               dict(status="done", code="infra"), dict(status="stop"), dict(status="stop", stop="nope"),
               dict(status="done", stop="control-file"), dict(status="failed", code="infra", detail="??"),
               dict(status="failed", code="infra", back_to="developer"),
               dict(status="failed", code="check-failed", reset_at=1),
               dict(status="failed", code="infra", reset_at="soon")]
        for kw in bad:
            with self.subTest(kw=kw):
                with self.assertRaises(ValueError):
                    Outcome(**kw)
        self.state["steps"]  # tearDown still validates


class OnFail(Base):
    def fail_test(self):
        self.run_until("test")
        self.start("test")
        return self.finish("test", Outcome("failed", code="check-failed", detail="run-nonzero"))

    def test_back_to_resets_target_and_everything_after(self):
        d = self.fail_test()
        self.assertEqual((d.action, d.step, d.target), ("back-to", "test", "developer"))
        i = self.proc.index("developer")
        for s in self.state["steps"]:
            want = "pending" if self.proc.index(s["id"]) >= i else "done"
            self.assertEqual(s["status"], want, s["id"])
        self.assertEqual(self.st("test")["on_fail_count"], 1)
        self.assertEqual(self.st("test")["reason"], "check-failed")
        self.assertEqual(SM.next_runnable(self.state, self.proc), "developer")
        names = [e for e, _ in d.events]
        self.assertIn("back-to", names)
        self.assertEqual(self.st("developer")["latest_attempt"], 1, "attempt history is kept")

    def test_s1_cap_exceeded_needs_human(self):
        # test: on_fail max 3 → 3 rewinds, the 4th check-failed stops.
        for i in range(3):
            d = self.fail_test()
            self.assertEqual(d.action, "back-to", i)
        d = self.fail_test()
        self.assertEqual(d.action, "stop")
        self.assertEqual(d.stop, ("needs_human", "on-fail-exceeded"))
        self.assertEqual(self.st("test")["status"], "needs_human")
        self.assertEqual(self.st("test")["on_fail_count"], 4)
        stop = self.state["stop"]
        self.assertEqual((stop["status"], stop["reason"], stop["step"], stop["attempt"]),
                         ("needs_human", "on-fail-exceeded", "test", 4))
        self.assertEqual(stop["allowed_answers"], ["rerun", "replan", "escalate"])
        with self.assertRaises(SM.StateError):
            SM.next_runnable(self.state, self.proc)

    def test_counter_counts_check_failed_only_and_is_not_reset(self):
        self.fail_test()
        # an output-format failure of the same step does not touch the on_fail counter
        self.run_until("test")
        self.start("test")
        d = self.finish("test", Outcome("failed", code="output-format", detail="result-schema"))
        self.assertEqual(d.action, "retry-same")
        self.assertEqual(self.st("test")["on_fail_count"], 1)
        # a success later does not reset it either
        self.start("test")
        self.finish("test", Outcome("done"))
        self.assertEqual(self.st("test")["on_fail_count"], 1)

    def test_failed_without_on_fail_stops(self):
        self.run_until("design")
        self.start("design")
        d = self.finish("design", Outcome("failed", code="check-failed", detail="foreign-output"))
        self.assertEqual(d.stop, ("needs_human", "on-fail-exceeded"))
        self.assertEqual(self.state["stop"]["note"], "the step has no on_fail")

    def test_rerun_grant_once_per_issue(self):
        for _ in range(4):
            d = self.fail_test()
        self.assertEqual(d.action, "stop")
        self.assertEqual(SM.grant_rerun(self.state, "test"), 1)
        with self.assertRaises(SM.StateError):
            SM.grant_rerun(self.state, "review")
        # The human's rerun (§6.3 "one more try"): U13 clears the stop and rewinds. The
        # allowance covers the failure that stopped us; the next check-failed stops again.
        self.state["stop"] = None
        self.events += SM.back_to(self.state, self.proc, "developer")
        d = self.fail_test()
        self.assertEqual(d.stop, ("needs_human", "on-fail-exceeded"))
        self.assertEqual(self.state["stop"]["note"], "check-failed 5 > on_fail max 4")

    def test_r8_i3_explicit_owner(self):
        self.run_until("review")
        self.start("review")
        d = self.finish("review", Outcome("failed", code="check-failed", detail="verdict-block", back_to="design"))
        self.assertEqual((d.action, d.target), ("back-to", "design"))
        self.assertEqual(SM.next_runnable(self.state, self.proc), "design")
        self.assertEqual(self.st("review")["on_fail_count"], 1, "the failing step's counter counts")
        self.assertEqual(self.st("analyze")["status"], "done")

    def test_i3_owner_after_the_step_is_refused(self):
        self.run_until("review")
        self.start("review")
        with self.assertRaises(SM.StateError):
            SM.apply(self.state, self.proc, "review",
                     Outcome("failed", code="check-failed", detail="verdict-block", back_to="pr"))
        self.st("review")["status"] = "running"
        with self.assertRaises(SM.StateError):
            SM.apply(self.state, self.proc, "review",
                     Outcome("failed", code="check-failed", back_to="nope"))
        self.st("review")["status"] = "pending"

    def test_back_to_self(self):
        self.run_until("ac-format")
        self.start("ac-format")
        d = self.finish("ac-format", Outcome("failed", code="check-failed", detail="run-nonzero"))
        self.assertEqual(d.target, "analyze")


class OutputFormat(Base):
    def test_r5_retry_once_then_needs_human(self):
        self.run_until("design")
        self.start("design")
        d = self.finish("design", Outcome("failed", code="output-format", detail="no-structured-output",
                                          errors=["no structured output"]))
        self.assertEqual((d.action, d.step), ("retry-same", "design"))
        self.assertEqual(d.errors, ["no structured output"])
        self.assertEqual(self.st("design")["status"], "pending")
        self.start("design")
        d = self.finish("design", Outcome("failed", code="output-format", detail="no-structured-output"))
        self.assertEqual(d.stop, ("needs_human", "output-format-twice"))
        self.assertEqual(self.st("design")["status"], "needs_human")
        self.assertEqual(self.state["stop"]["attempt"], 2)

    def test_retry_allowance_comes_back_after_done(self):
        self.run_until("design")
        self.start("design")
        self.finish("design", Outcome("failed", code="output-format"))
        self.start("design")
        self.finish("design", Outcome("done"))
        self.assertEqual(self.st("design")["output_format_retries"], 0)


class Stops(Base):
    def test_s3_session_limit(self):
        self.start("analyze")
        d = self.finish("analyze", Outcome("failed", code="session-limit"))
        self.assertEqual(d.stop, ("needs_human", "session-limit"))
        self.assertEqual(self.st("analyze")["status"], "needs_human")

    def test_r6_blocked(self):
        self.start("analyze")
        d = self.finish("analyze", Outcome("blocked"))
        self.assertEqual(d.stop, ("needs_human", "blocked"))
        self.assertEqual(self.state["stop"]["allowed_answers"], ["rerun", "replan", "escalate"])

    def test_security_boundary_stop(self):
        for reason in ("control-file", "judge-wrote-outside-outputs", "secret-detected", "unsafe-path"):
            with self.subTest(reason=reason):
                self.setUp()
                self.start("analyze")
                d = self.finish("analyze", Outcome("stop", stop=reason))
                self.assertEqual(d.stop, ("needs_human", reason))
                self.assertEqual(self.st("analyze")["status"], "needs_human")
                self.assertNotIn("allowed_answers", self.state["stop"])
                self.tearDown()

    def test_s11_engine_error_leaves_steps_untouched(self):
        self.start("analyze")
        before = json.dumps(self.state["steps"])
        d = self.finish("analyze", Outcome("failed", code="engine-error"))
        self.assertEqual(d.stop, ("needs_human", "engine-error"))
        self.assertEqual(json.dumps(self.state["steps"]), before)
        self.assertEqual(self.state["stop"]["reason"], "engine-error")

    def test_engine_error_outside_a_step(self):
        before = json.dumps(self.state["steps"])
        d = SM.engine_error(self.state, None, now=NOW, note="Traceback …")
        self.events += d.events
        self.assertEqual(d.stop, ("needs_human", "engine-error"))
        self.assertEqual(json.dumps(self.state["steps"]), before)
        self.assertIsNone(self.state["stop"]["step"])

    def test_stop_at_timestamp(self):
        self.start("analyze")
        self.finish("analyze", Outcome("blocked"), now=0)
        self.assertEqual(self.state["stop"]["at"], "1970-01-01T00:00:00Z")


class Infra(Base):
    def test_s2_quota_within_4h_waits_then_same_step(self):
        self.run_until("developer")
        self.start("developer")
        d = self.finish("developer", Outcome("failed", code="infra", detail="quota", reset_at=NOW + 3600))
        self.assertEqual((d.action, d.step, d.wait_s), ("wait", "developer", 3600))
        self.assertEqual(SM.next_runnable(self.state, self.proc), "developer")
        self.assertIn("wait", [e for e, _ in d.events])
        self.assertNotIn("on_fail_count", self.st("developer"))

    def test_s2_exactly_4h_waits_past_4h_stops(self):
        self.start("analyze")
        d = self.finish("analyze", Outcome("failed", code="infra", detail="quota", reset_at=NOW + 4 * 3600))
        self.assertEqual(d.action, "wait")
        self.start("analyze")
        d = self.finish("analyze", Outcome("failed", code="infra", detail="quota", reset_at=NOW + 4 * 3600 + 1))
        self.assertEqual(d.stop, ("needs_human", "infra-stop"))
        self.assertEqual(self.st("analyze")["status"], "running", "state kept for resume")

    def test_reset_in_the_past_waits_zero(self):
        self.start("analyze")
        d = self.finish("analyze", Outcome("failed", code="infra", detail="quota", reset_at=NOW - 10))
        self.assertEqual((d.action, d.wait_s), ("wait", 0))

    def test_infra_without_reset_stops(self):
        for detail in ("api", "auth", "op-failed", "fact-collection", "wall-clock", "no-output"):
            with self.subTest(detail=detail):
                self.setUp()
                self.start("analyze")
                d = self.finish("analyze", Outcome("failed", code="infra", detail=detail))
                self.assertEqual(d.stop, ("needs_human", "infra-stop"))
                self.assertEqual(self.state["stop"]["note"], detail)
                self.tearDown()


class StageTwo(Base):
    def test_open_check_stops_at_needs_leader_without_an_attempt(self):
        self.run_until("plan")
        with self.assertRaises(SM.StateError):
            SM.open_check(self.state, self.proc, "plan", H1, stage=1)
        d = SM.open_check(self.state, self.proc, "plan", H1, stage=2, now=NOW)
        self.events += d.events
        self.assertEqual(d.action, "stop")
        self.assertEqual(self.st("plan")["status"], "needs_leader")
        self.assertIsNone(self.st("plan")["latest_attempt"])
        self.assertEqual(self.state["stop"]["allowed_answers"], ["plan", "rerun", "close-as-decided", "escalate"])
        self.assertEqual(self.state["totals"]["attempts"], 2)       # analyze, ac-format — the check made none

    def test_open_check_refuses_a_role_step_or_a_later_step(self):
        self.run_until("plan")
        for sid in ("analyze", "design"):
            with self.assertRaises(SM.StateError):
                SM.open_check(self.state, self.proc, sid, H1, stage=2)

    def test_to_human_keeps_the_situation_or_replaces_it(self):
        self.run_until("plan")
        self.events += SM.open_check(self.state, self.proc, "plan", H1, stage=2, now=NOW).events
        self.events += SM.to_human(self.state, 2, now=NOW, leader_failed={"code": "output-format",
                                                                         "detail": "plan-with-gap"})
        self.assertEqual((self.state["stop"]["status"], self.state["stop"]["reason"]), ("needs_human", "plan-gate"))
        self.assertEqual(self.st("plan")["status"], "needs_human")
        with self.assertRaises(SM.StateError):          # only a needs_leader stop is handed over
            SM.to_human(self.state, 2)
        self.state["stop"]["status"] = "needs_leader"
        self.st("plan")["status"] = "needs_leader"
        self.events += SM.to_human(self.state, 2, reason="control-file")
        self.assertEqual(self.state["stop"]["reason"], "control-file")
        self.assertNotIn("allowed_answers", self.state["stop"])

    def test_insert_steps(self):
        SM.insert_steps(self.state, 3, ["extra-a", "extra-b"], 2)
        self.assertEqual([s["id"] for s in self.state["steps"]][2:6], ["plan", "extra-a", "extra-b", "design"])
        self.assertEqual(self.state["revision"], 2)
        for bad in ([], ["plan"], ["x", "x"]):
            with self.assertRaises(SM.StateError):
                SM.insert_steps(self.state, 0, bad, 3)
        self.state["steps"] = self.state["steps"][:3] + self.state["steps"][5:]
        self.state["revision"] = 1

    def test_d9_static_escalate_only(self):
        self.assertTrue(SM.escalate_only("rule-unfillable"))
        self.assertTrue(SM.escalate_only("base-red"))
        self.assertFalse(SM.escalate_only("blocked"))
        self.assertEqual(SM.leader_static_answers("base-red"), ("escalate",))
        self.assertEqual(SM.leader_static_answers("control-file"), ())


class StageOne(Base):
    def test_n1_no_needs_leader_in_stage_1(self):
        for reason in codes.StopReason.values():
            with self.subTest(reason=reason):
                self.assertEqual(SM.stop_status(reason, stage=1), "needs_human")

    def test_stage_2_leader_situations(self):
        for reason in codes.StopReason.values():
            # D9: rule-unfillable / base-red leave the leader only escalate → needs_human at once
            want = "needs_leader" if reason in codes.LEADER_SITUATIONS and reason not in (
                "rule-unfillable", "base-red") else "needs_human"
            self.assertEqual(SM.stop_status(reason, stage=2), want)
        with self.assertRaises(ValueError):
            SM.stop_status("not-a-reason")
        with self.assertRaises(ValueError):
            SM.stop_status("blocked", stage=0)

    def test_n1_every_path_of_apply_in_stage_1(self):
        outcomes = [Outcome("blocked"), Outcome("failed", code="session-limit"),
                    Outcome("failed", code="check-failed"), Outcome("failed", code="infra")]
        for o in outcomes:
            self.setUp()
            self.run_until("design")
            self.start("design")
            d = self.finish("design", o)
            self.assertEqual(d.stop[0], "needs_human")
            self.assertNotIn("needs_leader", json.dumps(self.state))
            self.assertNotIn("needs_leader", json.dumps(self.events))
            self.tearDown()


class Reverify(Base):
    def all_done(self):
        while SM.next_runnable(self.state, self.proc) != "pr":
            self.run_ok(SM.next_runnable(self.state, self.proc))

    def changed(self, paths, **override):
        out = {s.id: list(paths) for s in self.proc.steps}
        out.update(override)
        return out

    def test_v3_code_change_resets_reviews_and_runs(self):
        self.all_done()
        reset = SM.reverify(self.state, self.proc, self.changed(["src/a.py"]))
        self.assertEqual(reset, ["ac-format", "setup", "test", "review", "review-tests", "verify-gate"])
        for sid in ("design", "test-cases", "developer", "analyze", "plan"):
            self.assertEqual(self.st(sid)["status"], "done", sid)
        self.assertEqual(SM.next_runnable(self.state, self.proc), "ac-format")

    def test_v4_judge_documents_are_exempt(self):
        self.all_done()
        reset = SM.reverify(self.state, self.proc, self.changed(
            ["docs/specs/42/review-auditor.md", "docs/specs/42/design.md"]))
        self.assertEqual(reset, [])

    def test_v4_other_specs_paths_are_not_exempt(self):
        self.all_done()
        for path in ("docs/specs/42/procedure.yaml", "docs/specs/42/notes.md", "docs/specs/43/design.md"):
            with self.subTest(path=path):
                self.setUp()
                self.all_done()
                reset = SM.reverify(self.state, self.proc, self.changed([path]))
                self.assertIn("review", reset)
                self.tearDown()

    def test_only_steps_with_changes_after_their_head(self):
        self.all_done()
        ch = self.changed([], **{"review-tests": ["src/a.py"], "verify-gate": ["src/a.py"]})
        self.assertEqual(SM.reverify(self.state, self.proc, ch), ["review-tests", "verify-gate"])
        self.assertEqual(SM.next_runnable(self.state, self.proc), "review-tests")

    def test_missing_fact_resets(self):
        self.all_done()
        ch = self.changed([])
        del ch["test"]
        self.assertEqual(SM.reverify(self.state, self.proc, ch), ["test"])

    def test_pending_steps_are_ignored(self):
        self.run_until("test")
        self.assertEqual(SM.reverify(self.state, self.proc, self.changed(["src/a.py"])), ["ac-format", "setup"])


class AbsoluteLimits(Base):
    def test_s4_caps(self):
        t = self.state["totals"]
        self.assertIsNone(SM.check_absolute_limits(self.state, {"attempts": None, "budget_usd": None}))
        t.update(attempts=9, cost_usd=89.0, leader_calls=4)
        self.assertIsNone(SM.check_absolute_limits(self.state, {"attempts": 10, "budget_usd": 89.57, "leader_calls": 5}))
        for key, val in (("attempts", 10), ("cost_usd", 89.57), ("leader_calls", 5)):
            with self.subTest(key=key):
                saved = dict(t)
                t[key] = val
                self.assertEqual(SM.check_absolute_limits(
                    self.state, {"attempts": 10, "budget_usd": 89.57, "leader_calls": 5}), "absolute-limit")
                t.clear()
                t.update(saved)

    def test_bad_limits(self):
        with self.assertRaises(ValueError):
            SM.check_absolute_limits(self.state, {"budget": 1})
        with self.assertRaises(ValueError):
            SM.check_absolute_limits(self.state, {"attempts": -1})
        with self.assertRaises(ValueError):
            SM.check_absolute_limits(self.state, {"attempts": True})

    def test_missing_totals_count_as_zero(self):
        del self.state["totals"]
        self.assertIsNone(SM.check_absolute_limits(self.state, {"attempts": 1}))
        self.state["totals"] = {"attempts": 0}


if __name__ == "__main__":
    unittest.main()
