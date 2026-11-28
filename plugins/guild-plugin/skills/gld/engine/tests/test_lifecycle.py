"""U13 lock, detached run, resume answers (scope §5.2 S8 — unit part; S9/S10 in test_driver)."""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

from gxengine import codes, fsafe, instructions, lifecycle, paths as pathsmod, procedure as procmod, store
from tests import c_world as W

SHA = "c" * 40
R = codes.StopReason


def _dead_pid():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


class Locks(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = os.path.realpath(self._tmp.name)
        self.paths = pathsmod.EnginePaths(self.home, "acme/app", 42)
        self.other = pathsmod.EnginePaths(self.home, "acme/app", 43)
        self.procs = []

    def tearDown(self):
        for p in self.procs:
            p.kill()
            p.wait()
        self._tmp.cleanup()

    def plant(self, path, pid, started, issue=42):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump({"format": 1, "pid": pid, "started": started, "issue": issue, "at": "x"}, f)

    def sleeper(self):
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        self.procs.append(p)
        for _ in range(50):
            st = lifecycle.process_start(p.pid)
            if st:
                return p, st
            time.sleep(0.05)
        self.fail("no start time for the sleeper")

    def test_acquire_writes_pid_and_start_time_and_release_removes(self):
        info = lifecycle.acquire_lock(self.paths)
        self.assertEqual(info["pid"], os.getpid())
        with open(self.paths.lock) as f:
            rec = json.load(f)
        self.assertEqual(rec["pid"], os.getpid())
        self.assertEqual(rec["started"], lifecycle.process_start(os.getpid()))
        self.assertTrue(os.path.exists(lifecycle.repo_lock_path(self.paths)))
        self.assertTrue(lifecycle.release_lock(self.paths))
        self.assertFalse(os.path.exists(self.paths.lock))
        self.assertFalse(os.path.exists(lifecycle.repo_lock_path(self.paths)))

    def test_s8_live_lock_is_refused(self):
        p, st = self.sleeper()
        self.plant(self.paths.lock, p.pid, st)
        with self.assertRaises(lifecycle.LockHeld) as cm:
            lifecycle.acquire_lock(self.paths)
        self.assertEqual(cm.exception.pid, p.pid)
        # the repository lock taken before the Issue lock is given back
        self.assertFalse(os.path.exists(lifecycle.repo_lock_path(self.paths)))
        self.assertEqual(lifecycle.lock_holder(self.paths)["pid"], p.pid)

    def test_s8_dead_pid_lock_is_released(self):
        self.plant(self.paths.lock, _dead_pid(), "Mon Jan  1 00:00:00 2024")
        info = lifecycle.acquire_lock(self.paths)
        self.assertEqual([r["path"] for r in info["released"]], [self.paths.lock])
        lifecycle.release_lock(self.paths)

    def test_reused_pid_with_another_start_time_is_dead(self):
        p, st = self.sleeper()
        self.plant(self.paths.lock, p.pid, "Mon Jan  1 00:00:00 2024")
        info = lifecycle.acquire_lock(self.paths)
        self.assertEqual(len(info["released"]), 1)
        lifecycle.release_lock(self.paths)

    def test_one_engine_per_repository(self):
        p, st = self.sleeper()
        self.plant(lifecycle.repo_lock_path(self.paths), p.pid, st, issue=43)
        with self.assertRaises(lifecycle.LockHeld) as cm:
            lifecycle.acquire_lock(self.paths)
        self.assertEqual(cm.exception.issue, 43)
        p.kill()
        p.wait()
        info = lifecycle.acquire_lock(self.paths)
        self.assertEqual(len(info["released"]), 1)
        with self.assertRaises(lifecycle.LockHeld):
            lifecycle.acquire_lock(self.other)        # held by this live process now
        lifecycle.release_lock(self.paths)
        lifecycle.release_lock(self.other.__class__(self.home, "acme/app", 43))

    def test_corrupt_lock_is_held_for_a_grace_period(self):
        os.makedirs(self.paths.issue_dir)
        with open(self.paths.lock, "w") as f:
            f.write("{")
        with self.assertRaises(lifecycle.LockHeld):
            lifecycle.acquire_lock(self.paths)
        old = time.time() - lifecycle.LOCK_CORRUPT_GRACE_S - 5
        os.utime(self.paths.lock, (old, old))
        info = lifecycle.acquire_lock(self.paths)
        self.assertEqual(len(info["released"]), 1)
        lifecycle.release_lock(self.paths)

    def test_linked_lock_is_unsafe(self):
        os.makedirs(self.paths.issue_dir)
        os.symlink("/etc/hosts", self.paths.lock)
        with self.assertRaises(fsafe.UnsafePath):
            lifecycle.acquire_lock(self.paths)

    def test_release_leaves_another_engines_lock(self):
        p, st = self.sleeper()
        self.plant(self.paths.lock, p.pid, st)
        self.assertFalse(lifecycle.release_lock(self.paths))
        self.assertTrue(os.path.exists(self.paths.lock))


class Detached(unittest.TestCase):
    def test_spawn_detached_writes_log_and_rc(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = os.path.realpath(tmp)
            log, rc = os.path.join(tmp, "engine.log"), os.path.join(tmp, "engine.rc")
            with open(rc, "w") as f:
                f.write("0\n")                       # a stale rc from an earlier run goes first
            pid = lifecycle.spawn_detached([sys.executable, "-c", "print('hello'); import sys; sys.exit(3)"],
                                           log, rc)
            self.assertIsInstance(pid, int)
            for _ in range(200):
                if os.path.exists(rc):
                    break
                time.sleep(0.05)
            with open(rc) as f:
                self.assertEqual(f.read().strip(), "3")
            with open(log) as f:
                self.assertIn("hello", f.read())

    def test_needs_absolute_paths(self):
        with self.assertRaises(ValueError):
            lifecycle.spawn_detached(["python3"], "/tmp/x.log", "/tmp/x.rc")
        with self.assertRaises(ValueError):
            lifecycle.spawn_detached([sys.executable], "x.log", "/tmp/x.rc")

    def test_command_pattern(self):
        self.assertEqual(lifecycle.engine_command_pattern("/p"), "python3 -I /p/skills/gld/engine/engine.py:*")
        with self.assertRaises(ValueError):
            lifecycle.engine_command_pattern("p")


def _proc():
    cfg = W.config()
    return procmod.build(instructions.load_start_procedure(stage=1), W.template(), 42, list(cfg["commands"]))


class Answers(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.paths = pathsmod.EnginePaths(os.path.realpath(self._tmp.name), "acme/app", 42)
        self.proc = _proc()
        self.state = store.new_state(42, 1, self.proc.step_ids, SHA)
        for s in self.state["steps"][:3]:            # analyze, ac-format, plan
            s["status"] = "done"

    def st(self, sid):
        return next(x for x in self.state["steps"] if x["id"] == sid)

    def tearDown(self):
        self._tmp.cleanup()

    def stop(self, reason, step, status="needs_human"):
        s = next(x for x in self.state["steps"] if x["id"] == step)
        s["status"] = status
        s["latest_attempt"] = 1
        self.state["stop"] = {"status": "needs_human", "reason": reason, "step": step, "attempt": 1,
                              "at": "2026-11-23T01:00:00Z"}

    def test_allowed_answer_table(self):
        aa = lifecycle.allowed_answers
        self.assertEqual(aa(R.PLAN_GATE.value), ["plan", "escalate"])
        self.assertEqual(aa(R.BLOCKED.value), ["rerun", "escalate"])
        self.assertEqual(aa(R.NEW_COMMENT.value), ["continue", "rerun", "escalate"])
        self.assertEqual(aa(R.DONE_GATE.value), ["rerun", "escalate"])
        self.assertEqual(aa(R.CONTROL_FILE.value), ["rerun", "escalate"])
        self.assertEqual(aa(R.INFRA_STOP.value), ["rerun", "escalate"])
        for r in (R.ABSOLUTE_LIMIT, R.FORMAT_MISMATCH, R.STABLE_LABEL, R.RULE_UNFILLABLE):
            self.assertEqual(aa(r.value), ["escalate"])
        plan_done = {"steps": [{"id": "plan", "status": "done", "latest_attempt": 1}]}
        self.assertEqual(aa(R.BLOCKED.value, plan_done, stage=2), ["rerun", "replan", "escalate"])
        # D8: replan = back_to plan — not offered while plan is not done (or unknown)
        self.assertEqual(aa(R.BLOCKED.value, stage=2), ["rerun", "escalate"])
        self.assertEqual(aa(R.SOFT_BUDGET.value, soft_answered=True), ["escalate"])
        with self.assertRaises(ValueError):
            aa("nope")

    def test_pending_question(self):
        self.assertIsNone(lifecycle.pending_question(self.state))
        self.st("implement")["status"] = "running"
        q = lifecycle.pending_question(self.state)
        self.assertTrue(q["crashed"])
        self.assertEqual(q["step"], "implement")
        self.st("implement")["status"] = "pending"
        self.stop(R.BLOCKED.value, "implement")
        q = lifecycle.pending_question(self.state)
        self.assertEqual((q["reason"], q["step"], q["allowed_answers"]), ("blocked", "implement", ["rerun", "escalate"]))

    def test_recover_crashed(self):
        self.st("implement")["status"] = "running"
        events = lifecycle.recover_crashed(self.state)
        self.assertEqual(self.st("implement")["status"], "pending")
        self.assertEqual(events[0][1]["from"], "running")

    def test_rerun_back_to_and_records(self):
        self.stop(R.BLOCKED.value, "review")
        act = lifecycle.apply_answer(self.paths, self.state, "rerun", step="implement", reason="real-defect",
                                     note="fix the selector", procedure=self.proc)
        self.assertEqual(act, "continue")
        self.assertIsNone(self.state["stop"])
        st = {s["id"]: s["status"] for s in self.state["steps"]}
        self.assertEqual((st["implement"], st["test"], st["review"], st["plan"]), ("pending", "pending", "pending", "done"))
        text = lifecycle.read_leader_decision(self.paths)
        self.assertIn("answer `rerun`", text)
        self.assertIn("fix the selector", text)
        ans = [l for l in store.read_log(self.paths) if l["event"] == "answer"]
        self.assertEqual(ans[0]["who"], "human")
        self.assertEqual(ans[0]["code"], "blocked")
        self.assertEqual(ans[0]["data"], {"answer": "rerun", "target": "implement"})

    def test_rerun_cannot_skip_forward(self):
        self.stop(R.BLOCKED.value, "implement")
        with self.assertRaises(lifecycle.AnswerRefused):
            lifecycle.apply_answer(self.paths, self.state, "rerun", step="review", procedure=self.proc)
        self.assertIsNotNone(self.state["stop"])

    def test_on_fail_exceeded_rerun_once_per_issue(self):
        self.stop(R.ON_FAIL_EXCEEDED.value, "test", status="needs_human")
        lifecycle.apply_answer(self.paths, self.state, "rerun", step="implement", procedure=self.proc)
        self.assertEqual(next(s for s in self.state["steps"] if s["id"] == "test")["on_fail_extra"], 1)
        self.stop(R.ON_FAIL_EXCEEDED.value, "test")
        self.assertEqual(lifecycle.pending_question(self.state)["allowed_answers"], ["escalate"])
        with self.assertRaises(lifecycle.AnswerRefused):
            lifecycle.apply_answer(self.paths, self.state, "rerun", procedure=self.proc)

    def test_escalate_keeps_the_stop(self):
        self.stop(R.SESSION_LIMIT.value, "implement")
        self.assertEqual(lifecycle.apply_answer(self.paths, self.state, "escalate", procedure=self.proc), "stopped")
        self.assertEqual(self.state["stop"]["reason"], "session-limit")

    def test_continue_and_plan(self):
        self.stop(R.NEW_COMMENT.value, "implement")
        lifecycle.apply_answer(self.paths, self.state, "continue", procedure=self.proc)
        self.assertIsNone(self.state["stop"])
        self.assertEqual(self.st("implement")["status"], "pending")
        self.st("plan")["status"] = "needs_human"
        self.state["stop"] = {"status": "needs_human", "reason": "plan-gate", "step": "plan", "attempt": 1,
                              "at": "2026-11-23T01:00:00Z"}
        lifecycle.apply_answer(self.paths, self.state, "plan", procedure=self.proc)
        self.assertEqual(self.st("plan")["status"], "done")

    def test_refusals_leave_the_state_unchanged(self):
        self.stop(R.PLAN_GATE.value, "plan")
        before = json.dumps(self.state, sort_keys=True)
        for ans, kw in (("rerun", {}), ("replan", {}), ("continue", {}), ("plan", {"reason": "bogus"})):
            with self.assertRaises(lifecycle.AnswerRefused):
                lifecycle.apply_answer(self.paths, self.state, ans, procedure=self.proc, **kw)
        self.assertEqual(json.dumps(self.state, sort_keys=True), before)
        self.assertEqual(lifecycle.read_leader_decision(self.paths), lifecycle.NO_DECISION_TEXT)
        self.state["stop"] = None
        with self.assertRaises(lifecycle.AnswerRefused):
            lifecycle.apply_answer(self.paths, self.state, "escalate", procedure=self.proc)

    # --- stage 2 (V6): one apply_answer for both seats ---------------------------------------

    def leader_stop(self, reason, step):
        self.stop(reason, step, status="needs_leader")
        self.state["stop"]["status"] = "needs_leader"

    def test_s2_a_human_cannot_answer_a_needs_leader_stop(self):
        self.leader_stop(R.BLOCKED.value, "review")
        q = lifecycle.pending_question(self.state, stage=2)
        self.assertTrue(q["leader_turn"])
        before = json.dumps(self.state, sort_keys=True)
        with self.assertRaises(lifecycle.AnswerRefused):
            lifecycle.apply_answer(self.paths, self.state, "rerun", procedure=self.proc, stage=2)
        self.assertEqual(json.dumps(self.state, sort_keys=True), before)
        # and the leader cannot answer a human's stop, nor any stop in stage 1
        self.stop(R.BLOCKED.value, "review")
        with self.assertRaises(lifecycle.AnswerRefused):
            lifecycle.apply_answer(self.paths, self.state, "rerun", procedure=self.proc, stage=2, who="leader")
        self.leader_stop(R.BLOCKED.value, "review")
        with self.assertRaises(lifecycle.AnswerRefused):
            lifecycle.apply_answer(self.paths, self.state, "rerun", procedure=self.proc, stage=1, who="leader")

    def test_s2_leader_rerun_is_logged_as_the_leader(self):
        self.leader_stop(R.BLOCKED.value, "review")
        act = lifecycle.apply_answer(self.paths, self.state, "rerun", step="review", reason="transient",
                                     note="again", procedure=self.proc, stage=2, who="leader")
        self.assertEqual(act, "continue")
        self.assertEqual(self.st("review")["status"], "pending")
        ans = [l for l in store.read_log(self.paths) if l["event"] == "answer"][0]
        self.assertEqual((ans["who"], ans["data"]["situation"], ans["data"]["step"]), ("leader", "blocked", "review"))
        self.assertIn("leader answer `rerun`", lifecycle.read_leader_decision(self.paths))

    def test_s2_leader_escalate_needs_a_recommendation_and_hands_over(self):
        self.leader_stop(R.BLOCKED.value, "review")
        with self.assertRaises(lifecycle.AnswerRefused):
            lifecycle.apply_answer(self.paths, self.state, "escalate", procedure=self.proc, stage=2, who="leader")
        act = lifecycle.apply_answer(self.paths, self.state, "escalate", reason="env-problem", procedure=self.proc,
                                     stage=2, who="leader",
                                     recommendation={"answer": "rerun", "step": "implement", "note": "base"})
        self.assertEqual(act, "stopped")
        stop = self.state["stop"]
        self.assertEqual((stop["status"], stop["reason"]), ("needs_human", "blocked"))
        self.assertEqual(stop["recommendation"], {"answer": "rerun", "step": "implement", "note": "base",
                                                  "reason": "env-problem"})
        self.assertEqual(self.st("review")["status"], "needs_human")
        store.save_state(self.paths, self.state)                     # schema-valid

    def test_s2_plan_gate_rerun_counts_and_replan_needs_a_done_plan(self):
        self.stop(R.PLAN_GATE.value, "plan")
        self.assertEqual(lifecycle.pending_question(self.state, stage=2)["allowed_answers"],
                         ["plan", "rerun", "close-as-decided", "escalate"])
        lifecycle.apply_answer(self.paths, self.state, "rerun", step="analyze", procedure=self.proc, stage=2)
        self.assertEqual(self.state["counters"], {"plan_rerun": 1})
        self.assertEqual(self.st("analyze")["status"], "pending")
        # replan: back_to plan, only with a done plan (D8)
        for s in self.state["steps"][:3]:
            s["status"] = "done"
        self.stop(R.BLOCKED.value, "review")
        lifecycle.apply_answer(self.paths, self.state, "replan", procedure=self.proc, stage=2)
        st = {s["id"]: s["status"] for s in self.state["steps"]}
        self.assertEqual((st["analyze"], st["plan"], st["review"]), ("done", "pending", "pending"))
        self.st("plan")["status"] = "pending"
        self.stop(R.BLOCKED.value, "review")
        self.assertNotIn("replan", lifecycle.pending_question(self.state, stage=2)["allowed_answers"])
        with self.assertRaises(lifecycle.AnswerRefused):
            lifecycle.apply_answer(self.paths, self.state, "replan", procedure=self.proc, stage=2)

    def test_s2_close_as_decided_skips_the_rest_and_approve_is_done_gate_only(self):
        self.stop(R.PLAN_GATE.value, "plan")
        with self.assertRaises(lifecycle.AnswerRefused):
            lifecycle.apply_answer(self.paths, self.state, "approve", procedure=self.proc, stage=2)
        act = lifecycle.apply_answer(self.paths, self.state, "close-as-decided", reason="already-decided",
                                     procedure=self.proc, stage=2)
        self.assertEqual(act, "closed")
        self.assertIsNone(self.state["stop"])
        self.assertEqual(self.st("plan")["status"], "done")
        for s in self.state["steps"][3:]:
            self.assertEqual((s["status"], s["reason"]), ("skipped", "closed-as-decided"))
        store.save_state(self.paths, self.state)

    def test_l19_no_answer_turns_a_review_or_a_run_into_done(self):
        # The only path to `done` in apply_answer is the stopped CHECK step (plan / approve /
        # close) — a failed review or run is never marked done by any answer of either seat.
        for reason, step in ((R.ON_FAIL_EXCEEDED.value, "review"), (R.ON_FAIL_EXCEEDED.value, "test"),
                             (R.BLOCKED.value, "review"), (R.OUTPUT_FORMAT_TWICE.value, "review")):
            for ans in codes.LeaderAnswer.values():
                for who, status in (("human", "needs_human"), ("leader", "needs_leader")):
                    self.tearDown()
                    self.setUp()
                    self.stop(reason, step, status=status)
                    self.state["stop"]["status"] = status
                    try:
                        lifecycle.apply_answer(self.paths, self.state, ans, step=None, procedure=self.proc,
                                               stage=2, who=who,
                                               recommendation={"answer": "escalate", "step": None, "note": ""})
                    except lifecycle.AnswerRefused:
                        pass
                    self.assertNotEqual(self.st(step)["status"], "done", (reason, step, ans, who))

    def test_soft_budget_rerun_is_once(self):
        self.stop(R.SOFT_BUDGET.value, "test")
        self.assertFalse(lifecycle.soft_budget_answered(self.paths))
        lifecycle.apply_answer(self.paths, self.state, "rerun", procedure=self.proc)
        self.assertTrue(lifecycle.soft_budget_answered(self.paths))


if __name__ == "__main__":
    unittest.main()
