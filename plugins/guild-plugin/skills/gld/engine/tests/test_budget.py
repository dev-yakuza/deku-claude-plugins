"""U14 budget: issue cost from attempt facts, soft / absolute budget (scope §5.2 S4 — unit part)."""

import copy
import json
import os
import tempfile
import unittest

from gxengine import budget, codes, paths as pathsmod, store

HERE = os.path.dirname(os.path.abspath(__file__))
FACTS = os.path.join(HERE, "fixtures", "contracts", "facts.example.json")
SHA = "a" * 40


def _facts(step, attempt, kind, cost):
    with open(FACTS, encoding="utf-8") as f:
        f0 = json.load(f)
    f1 = copy.deepcopy(f0)
    f1.update({"issue": 7, "step": step, "attempt": attempt, "kind": kind})
    if kind == "role":
        f1["run"] = None
        f1["session"] = {"init": {"ok": True, "mismatches": []}, "end": "completed",
                         "structured_output": True, "stream_file": "stream.jsonl", "cost_usd": cost}
    else:
        f1["session"] = None
    return f1


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = os.path.realpath(self._tmp.name)
        self.paths = pathsmod.EnginePaths(self.home, "acme/app", 7)
        self.state = store.new_state(7, 1, ["design", "test", "implement"], SHA)

    def tearDown(self):
        self._tmp.cleanup()

    def put(self, step, kind, cost, write=True):
        n = store.new_attempt(self.paths, self.state, step)
        if write:
            store.write_facts(self.paths, step, n, _facts(step, n, kind, cost))
        return n


class IssueCost(Base):
    def test_sums_role_sessions_over_every_attempt(self):
        self.put("design", "role", 1.25)
        self.put("design", "role", 2.0)
        self.put("implement", "role", 10.5)
        self.put("test", "run", None)
        cost, warnings = budget.issue_cost(self.paths, self.state)
        self.assertAlmostEqual(cost, 13.75)
        self.assertEqual(warnings, [])

    def test_missing_cost_is_a_warning_not_silent(self):
        self.put("design", "role", None)
        self.put("implement", "role", 3.0)
        cost, warnings = budget.issue_cost(self.paths, self.state)
        self.assertAlmostEqual(cost, 3.0)
        self.assertEqual(len(warnings), 1)
        self.assertIn("runs/design/1", warnings[0]["note"])

    def test_attempt_without_facts_is_a_warning(self):
        self.put("implement", "role", 0, write=False)
        cost, warnings = budget.issue_cost(self.paths, self.state)
        self.assertEqual(cost, 0.0)
        self.assertIn("no facts.json", warnings[0]["note"])

    def test_corrupt_facts_is_a_warning(self):
        n = self.put("implement", "role", 0, write=False)
        with open(self.paths.attempt_file("implement", n, "facts.json"), "w") as f:
            f.write("{not json")
        cost, warnings = budget.issue_cost(self.paths, self.state)
        self.assertEqual(cost, 0.0)
        self.assertIn("unreadable", warnings[0]["note"])

    def test_l25_leader_sessions_count_check_attempts_and_leader_folders(self):
        # stage 2 (D13): a plan-gate / done-gate session is a check attempt with a session; a
        # needs_leader call is <records>/leader/<k>/facts.json. A stage-1 check has no session.
        self.put("design", "role", 1.0)
        f = _facts("test", 1, "check", None)
        n = store.new_attempt(self.paths, self.state, "test")
        store.write_facts(self.paths, "test", n, dict(f, attempt=n))          # stage-1 check: no session
        g = _facts("test", 2, "role", 0.75)
        g["kind"] = "check"
        n = store.new_attempt(self.paths, self.state, "test")
        store.write_facts(self.paths, "test", n, dict(g, attempt=n))
        for k, cost in ((1, 0.5), (2, None)):
            d = os.path.join(self.paths.issue_dir, "leader", str(k))
            os.makedirs(d)
            h = _facts("design", k, "role", cost)
            h["kind"] = "leader"
            with open(os.path.join(d, "facts.json"), "w") as fh:
                json.dump(h, fh)
        os.makedirs(os.path.join(self.paths.issue_dir, "leader", "3"))      # a call that never finished
        cost, warnings = budget.issue_cost(self.paths, self.state)
        self.assertAlmostEqual(cost, 1.0 + 0.75 + 0.5)
        self.assertEqual(sorted(w["note"].split(":")[0] for w in warnings), ["leader/2", "leader/3"])

    def test_refresh_sets_totals(self):
        self.put("design", "role", 4.5)
        budget.refresh(self.paths, self.state)
        self.assertEqual(self.state["totals"]["cost_usd"], 4.5)


class Check(unittest.TestCase):
    def st(self, cost):
        return {"totals": {"cost_usd": cost}}

    def test_attended_thresholds(self):
        A = codes.RunMode.ATTENDED.value
        self.assertIsNone(budget.check(self.st(0.0), A))
        self.assertIsNone(budget.check(self.st(44.78), A))
        self.assertEqual(budget.check(self.st(44.79), A), codes.StopReason.SOFT_BUDGET.value)
        self.assertEqual(budget.check(self.st(89.57), A), codes.StopReason.ABSOLUTE_LIMIT.value)
        self.assertEqual(budget.check(self.st(120), A), codes.StopReason.ABSOLUTE_LIMIT.value)

    def test_soft_acknowledged_once_only_lifts_the_soft_budget(self):
        A = codes.RunMode.ATTENDED.value
        self.assertIsNone(budget.check(self.st(50), A, soft_acknowledged=True))
        self.assertEqual(budget.check(self.st(89.57), A, soft_acknowledged=True),
                         codes.StopReason.ABSOLUTE_LIMIT.value)

    def test_unattended_and_bad_inputs(self):
        U = codes.RunMode.UNATTENDED.value
        self.assertEqual(budget.check(self.st(18.44), U), codes.StopReason.SOFT_BUDGET.value)
        self.assertEqual(budget.check(self.st(36.88), U), codes.StopReason.ABSOLUTE_LIMIT.value)
        with self.assertRaises(ValueError):
            budget.check(self.st(1), "fast")
        with self.assertRaises(ValueError):
            budget.check(self.st(-1), codes.RunMode.ATTENDED.value)
        self.assertIsNone(budget.check({}, codes.RunMode.ATTENDED.value))


if __name__ == "__main__":
    unittest.main()
