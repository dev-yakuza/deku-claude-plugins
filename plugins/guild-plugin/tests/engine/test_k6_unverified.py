"""K6 item 4 — the §10.2-6 unverified groups: the conservative path until 5 counted blind answers, no wrong.

* the shipped `verification.json` lists no verified group (the held-out replay needs a paid run) → every §9.5 group
  is unverified; a verified group listed there is not;
* an unverified group not released makes `predict.conservative` true — the gate asks blind with no valve;
* release: 5 person verdicts (`ok` / `wrong`) on predict-first answers of the group, none wrong; other rows (the
  steady sheet, `unsure`) never count; a wrong keeps it unverified;
* `dev health` reports the counts.
"""

import json
import os
import unittest

import _util  # noqa: F401
from _k1 import tmpdir
import test_k5_r9 as R9
import test_k5_r10 as R10

from guildcore import valves as VALVES
from workflows.dev import grade as G
from workflows.dev import predict as PF
from workflows.dev import unverified as UV


def _row(i, group="SPLIT", gi="ok", mode="predict-first"):          # K6 r4: STAKES is asked openly
    return {"decision_id": "D%d" % i, "issue": 10 + i, "stage": "analyze", "group": group, "mode": mode,
            "choice": "low", "given_info": gi}


class Shipped(unittest.TestCase):
    def test_nothing_is_verified_before_the_paid_replay(self):
        s = UV.shipped()
        self.assertEqual(s.get("verified"), [])
        self.assertEqual(int(s.get("release_after")), 5)
        # K6 r1 M6: every §9.5 group but the EXEMPT ones (no less conservative path to gate)
        self.assertEqual(UV.unverified(), [g for g in VALVES.GROUPS if g not in UV.EXEMPT])

    def test_a_verified_group_is_not_unverified(self):
        d = tmpdir(self)
        path = os.path.join(d, "v.json")
        with open(path, "w") as fh:
            json.dump({"verified": ["QA", "EX-ARB:dismiss"], "release_after": 5}, fh)
        u = UV.unverified(path)
        self.assertNotIn("QA", u)
        self.assertNotIn("EX-ARB-dismiss", u)
        self.assertIn("STAKES", u)

    def test_no_common_dir_is_all_pending(self):
        self.assertEqual(UV.pending(None), frozenset(g for g in VALVES.GROUPS if g not in UV.EXEMPT))


class Release(unittest.TestCase):
    def setUp(self):
        self.common = tmpdir(self)

    def test_five_blind_oks_release(self):
        for i in range(4):
            res = G.apply_judgments(self.common, [_row(i)], "o/r", "predict-first")
            self.assertNotIn("unverified_released", res)
            self.assertIn("SPLIT", UV.pending(self.common))
        res = G.apply_judgments(self.common, [_row(4)], "o/r", "predict-first")
        self.assertEqual(res.get("unverified_released"), ["SPLIT"])
        self.assertNotIn("SPLIT", UV.pending(self.common))
        self.assertIn("QA", UV.pending(self.common))

    def test_a_wrong_keeps_it_unverified(self):
        G.apply_judgments(self.common, [_row(0, gi="wrong")], "o/r", "human")
        G.apply_judgments(self.common, [_row(i) for i in range(1, 9)], "o/r", "predict-first")
        self.assertIn("SPLIT", UV.pending(self.common))
        rep = dict((r["group"], r) for r in UV.report(self.common))
        self.assertEqual((rep["SPLIT"]["counted"], rep["SPLIT"]["wrong"]), (9, 1))

    def test_other_rows_never_count(self):
        rows = [_row(i, mode="first-sprint") for i in range(6)] + [_row(10 + i, gi="unsure") for i in range(6)]
        G.apply_judgments(self.common, rows, "o/r", "human")
        self.assertIn("SPLIT", UV.pending(self.common))
        self.assertEqual(dict((r["group"], r) for r in UV.report(self.common))["SPLIT"]["counted"], 0)

    def test_colon_group_spelling(self):
        G.apply_judgments(self.common, [_row(i, group="EX-ARB:dismiss") for i in range(5)], "o/r", "predict-first")
        self.assertNotIn("EX-ARB-dismiss", UV.pending(self.common))


class ConservativePath(unittest.TestCase):
    def test_predicate(self):
        class P(object):
            valves = {}
            unverified = frozenset(["QA", "EX-ARB-dismiss"])
        self.assertTrue(PF.conservative(P(), "QA"))
        self.assertTrue(PF.conservative(P(), "EX-ARB:dismiss"))
        self.assertFalse(PF.conservative(P(), "STAKES"))

    def test_gate_asks_for_an_unverified_group_without_a_valve(self):
        build, run, _f, _y, _e = R9.SCENARIOS["QA"]
        h = build(self, R9.runner_judge("QA", R10.shape_of("QA", "pass"), "pass"))
        h.p.valves = {}
        h.p.unverified = frozenset(["QA"])
        run(h)
        q = R9._open_questions(h, "QA")
        self.assertEqual(len(q), 1)
        self.assertTrue(q[0].get("recommended_sha"))                  # blind (predict-first)
        self.assertIsNone(q[0].get("predict_first_refused"))

    def test_released_group_runs_the_judge(self):
        build, run, _f, _y, _e = R9.SCENARIOS["QA"]
        h = build(self, R9.runner_judge("QA", R10.shape_of("QA", "pass"), "pass"))
        h.p.valves = {}
        h.p.unverified = frozenset(["STAKES"])
        run(h)
        self.assertEqual(R9._open_questions(h, "QA"), [])


class LivePorts(unittest.TestCase):
    def test_the_factory_sets_the_pending_set(self):
        src = open(os.path.join(os.path.dirname(UV.__file__), "ports.py"), encoding="utf-8").read()
        self.assertIn("p.unverified = UV.pending(common)", src)


if __name__ == "__main__":
    unittest.main()
