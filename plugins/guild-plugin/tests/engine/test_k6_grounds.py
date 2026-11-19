"""K6 item 39 (review-k5-r10 m2 / r11 m1) — a person's option that cannot run for lack of grounds.

The options stay in the question (taking one out would reveal the blind recommendation — r11). After the answer:
(i) the judgment block (`grounds`) and the pause it leads to say which field the option lacked and how to give it;
(iv) the same answer at the next entry of the point, again without grounds, stops for the grounds instead of asking
the same question once more. (ii) SPLIT slices from a person and (iii) a DE-ARB re-invocation without an addendum stay
on the coercion (→ a person) — see k6-notes.
"""

import unittest

import _util  # noqa: F401
import test_k5_r9 as R9
import test_k5_r10 as R10
from _k2 import decision
from _k4 import out_role, techlead_ok, tester_ok
from test_k4_design import design_h

from workflows.dev import conservative as CONS
from workflows.dev.stages.base import StageResult


def _judgment(h, group):
    return [b for b in R10._blocks(h) if b.get("point") == group][-1]


def _comments(h):
    return "\n".join(c.get("body") or "" for c in h.gh.comments(h.n))


def _unlabel(h):
    iss = h.issue()
    iss["labels"] = [lb for lb in iss["labels"] if (lb.get("name") if isinstance(lb, dict) else lb)
                     != "guild:needs-human"]


def _dearb_rerun_h(case, judge):
    """R9's DE-ARB scenario with enough live role results for three entries of the point (each new entry runs the
    tester and the blocked tech-lead live; an answered run replays them)."""
    blocked = lambda: out_role(case, "BLOCKED", "which module?", evidence="none")    # noqa: E731
    roles = [tester_ok(case, (1, 2)), blocked(), tester_ok(case, (1, 2)), blocked(), tester_ok(case, (1, 2)),
             blocked(), techlead_ok(case), techlead_ok(case), techlead_ok(case)]
    h = design_h(case, cast="", ui="false", roles=roles,
                 judges={"DE-ARB": judge, "STAKES": decision("high", {"level": "high"})})
    h.p.journal = h.journal
    return h


class Grounds(unittest.TestCase):
    def _h(self, group, y):
        build, run, _f, _y, _e = R9.SCENARIOS[group]
        if group == "DE-ARB":
            build = _dearb_rerun_h
        h = build(self, R9.runner_judge(group, R10.shape_of(group, y), y))
        h.p.valves = {"group.%s.conservative" % group: True}
        return h, run

    def _answer_once(self, group, y, x):
        h, run = self._h(group, y)
        run(h)
        q = R9._open_questions(h, group)
        self.assertTrue(q)
        R9._answer(h, q[-1], x)
        return h, run, run(h)

    def test_dearb_decide_names_the_missing_assumption(self):
        h, _run, r = self._answer_once("DE-ARB", "reinvoke", "decide")
        b = _judgment(h, "DE-ARB")
        self.assertEqual((b.get("human_choice"), b.get("choice")), ("decide", "pause"))
        self.assertIn("`assumption`", str(b.get("grounds")))
        self.assertIn("dev note", str(b.get("grounds")))
        if h.p.unattended:
            self.assertEqual(r.kind, StageResult.PAUSE)
            self.assertIn("`assumption` 없음", _comments(h))

    def test_handoff_ok_with_assumption_names_the_missing_line(self):
        h, _run, _r = self._answer_once("HANDOFF", "ok", "ok_with_assumption")
        b = _judgment(h, "HANDOFF")
        self.assertEqual(b.get("human_choice"), "ok_with_assumption")
        self.assertIn("`line`", str(b.get("grounds")))

    def test_a_choice_that_stands_has_no_grounds_line(self):
        h, _run, _r = self._answer_once("QA", "pass", "pass")
        self.assertIsNone(_judgment(h, "QA").get("grounds"))

    def test_same_answer_twice_stops_for_grounds(self):
        h, run, r = self._answer_once("DE-ARB", "reinvoke", "decide")
        _unlabel(h)
        run(h)                                                          # judged again → asked again (a1)
        q = R9._open_questions(h, "DE-ARB")
        self.assertTrue(q)
        self.assertTrue(str(q[-1].get("refs")).endswith(":a1"))
        R9._answer(h, q[-1], "decide")
        r = run(h)
        self.assertIn(r.kind, (StageResult.PAUSE, StageResult.HOLD))
        said = str(getattr(r, "cause", None) or getattr(r, "line", None) or "")
        self.assertIn("같은 답이 두 번", said)
        self.assertNotIn("guild:execute", h.labels())
        # the answer is consumed: the next entry is a new point, judged again — never the same question looping
        _unlabel(h)
        run(h)
        q = R9._open_questions(h, "DE-ARB")
        self.assertTrue(str(q[-1].get("refs")).endswith(":a2"))

    def test_a_different_answer_the_second_time_runs(self):
        h, run, r = self._answer_once("DE-ARB", "reinvoke", "decide")
        _unlabel(h)
        run(h)
        R9._answer(h, R9._open_questions(h, "DE-ARB")[-1], "reinvoke")
        r = run(h)
        said = str(getattr(r, "cause", None) or getattr(r, "line", None) or "")
        self.assertNotIn("같은 답이 두 번", said)
        b = _judgment(h, "DE-ARB")
        self.assertEqual((b.get("choice"), b.get("by")), ("reinvoke", "human"))
        self.assertIsNone(b.get("grounds"))

    def test_previous_epoch(self):
        self.assertIsNone(CONS._previous_epoch("conservative:QA:#7:qa:Q2.5:L0"))
        self.assertEqual(CONS._previous_epoch("conservative:QA:#7:qa:Q2.5:L0:a1"), "conservative:QA:#7:qa:Q2.5:L0")
        self.assertEqual(CONS._previous_epoch("conservative:QA:#7:qa:Q2.5:L0:a3"),
                         "conservative:QA:#7:qa:Q2.5:L0:a2")


if __name__ == "__main__":
    unittest.main()
