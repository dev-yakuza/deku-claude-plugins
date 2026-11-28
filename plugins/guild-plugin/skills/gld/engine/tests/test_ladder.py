"""Stage 3 V11: model / effort layers, the retry raise and the return record (E26–E29, R1-38; TM1–TM8)."""

import copy
import unittest
from unittest import mock

from gxengine import codes, defaults, ladder, procedure, schema

ML = codes.ModelLayer
M, E = defaults.ALLOWED_MODELS, defaults.ALLOWED_EFFORTS


def step(**raw):
    return procedure.Step(raw)


def base(model="sonnet", effort="high", layer="plugin-default"):
    return {"model": model, "effort": effort, "layer": layer}


class Ladders(unittest.TestCase):
    def test_allow_lists_are_the_ladder_in_ladder_order(self):
        self.assertEqual(ladder.effort_ladder(E), ("low", "medium", "high", "xhigh"))
        self.assertEqual(ladder.model_ladder(M), ("haiku", "sonnet", "opus"))
        self.assertEqual(ladder.effort_ladder(["max", "low"]), ("low", "max"))
        self.assertEqual(ladder.model_ladder(["fable", "opus"]), ("opus", "fable"))

    def test_an_unknown_name_is_refused(self):
        with self.assertRaises(ladder.LadderError):
            ladder.effort_ladder(["high", "ultra"])
        with self.assertRaises(ladder.LadderError):
            ladder.model_ladder(["gpt"])


class Raisable(unittest.TestCase):
    def test_e26_2(self):
        self.assertTrue(ladder.raisable(step(id="implement", role="developer", outputs=[])))
        self.assertTrue(ladder.raisable(step(id="analyze", role="requirements-engineer", outputs=["a.md"])))
        self.assertFalse(ladder.raisable(step(id="r", role="auditor", outputs=[], checks=["diff-review"])))   # TM3
        self.assertFalse(ladder.raisable(step(id="t", run="test")))
        self.assertFalse(ladder.raisable(step(id="g", check="done-gate")))
        self.assertFalse(ladder.raisable(step(id="p", op="create-pr")))


class BaseChoice(unittest.TestCase):
    def test_layer_1_of_the_stage(self):
        rev = step(id="review-x", role="tech-lead", outputs=[], checks=["c"])
        want = defaults.model_effort_table(3)["tech-lead/review"]
        self.assertEqual(ladder.base_choice(rev, 3, {}), base(*want))
        d = step(id="diagnose", role="tech-lead", outputs=["d.md"])
        self.assertEqual(ladder.base_choice(d, 3, None), base(*defaults.model_effort_table(3)["tech-lead/diagnose"]))
        with self.assertRaises(ladder.LadderError):          # E17 is a stage-3 key
            ladder.base_choice(d, 2, {})
        with self.assertRaises(ladder.LadderError):
            ladder.base_choice(step(id="x", role="nobody", outputs=[]), 3, {})
        with self.assertRaises(ladder.LadderError):
            ladder.base_choice(step(id="t", run="test"), 3, {})

    def test_tm6_tm7_an_override_wins(self):
        st = step(id="implement", role="developer", outputs=[])
        ov = {"implement": {"model": "opus", "effort": "xhigh", "layer": "plan", "reason": "high-complexity"}}
        self.assertEqual(ladder.base_choice(st, 3, ov), base("opus", "xhigh", "plan"))
        ov["implement"]["layer"] = "leader"
        self.assertEqual(ladder.base_choice(st, 3, ov)["layer"], ML.LEADER.value)
        ov["implement"]["layer"] = "plugin-default"
        with self.assertRaises(ladder.LadderError):
            ladder.base_choice(st, 3, ov)


class Raised(unittest.TestCase):
    def up(self, b, n, models=M, efforts=E):
        r = ladder.raised(b, n, models, efforts)
        sch = schema.load_schema("facts")["properties"]["session"]["anyOf"][1]["properties"]["escalation"]
        self.assertEqual(schema.errors(r["escalation"], dict(sch, **{"$defs": {}})), [])
        return (r["model"], r["effort"], r["escalation"]["raised"], r["escalation"]["capped"])

    def test_tm1_steps(self):
        none = {"effort": None, "model": None}
        self.assertEqual(self.up(base(), 0), ("sonnet", "high", none, False))
        self.assertEqual(self.up(base(), 1), ("sonnet", "high", none, False))
        self.assertEqual(self.up(base(), 2), ("sonnet", "xhigh", {"effort": ["high", "xhigh"], "model": None}, False))
        want = ("opus", "xhigh", {"effort": ["high", "xhigh"], "model": ["sonnet", "opus"]}, False)
        self.assertEqual(self.up(base(), 3), want)
        self.assertEqual(self.up(base(), 9), want)               # never more than these two rungs

    def test_tm2_capped_goes_on(self):
        self.assertEqual(self.up(base("opus", "xhigh"), 2), ("opus", "xhigh", {"effort": None, "model": None}, True))
        self.assertEqual(self.up(base("opus", "high"), 3),
                         ("opus", "xhigh", {"effort": ["high", "xhigh"], "model": None}, True))
        self.assertEqual(self.up(base("opus", "xhigh"), 1)[3], False)      # nothing was due

    def test_tm8_the_settings_open_max_and_fable(self):
        self.assertEqual(self.up(base("opus", "xhigh"), 3, list(M) + ["fable"], list(E) + ["max"])[:2], ("fable", "max"))
        self.assertEqual(self.up(base("sonnet", "low"), 2, M, ["low", "high"])[1], "high")   # a closed rung is skipped

    def test_a_base_outside_the_allow_list(self):
        for b in (base("fable"), base(effort="max")):
            for n in (0, 3):
                with self.subTest(b=b, n=n), self.assertRaises(ladder.LadderError):
                    ladder.raised(b, n, M, E)

    def test_bad_counts(self):
        for n in (-1, True, "2", None):
            with self.subTest(n=n), self.assertRaises(ValueError):
                ladder.raised(base(), n, M, E)

    def test_tm7_the_raise_starts_from_the_leader_base(self):
        r = ladder.raised(base("haiku", "low", "leader"), 3, M, E)
        self.assertEqual((r["model"], r["effort"]), ("sonnet", "medium"))
        self.assertEqual(r["escalation"]["base"], base("haiku", "low", "leader"))


class Returns(unittest.TestCase):
    def test_count_and_sources(self):
        s = {"id": "fix", "status": "pending", "latest_attempt": 1}
        ladder.count_return(s, codes.ReturnCause.ON_FAIL, [("test", 1)])
        self.assertEqual(s["returns"], 1)
        self.assertEqual(s["return_sources"], [{"step": "test", "attempt": 1, "cause": "on-fail"}])
        ladder.count_return(s, "leader-rerun", [("review-audit", 2), ("review-tests", 1)])
        self.assertEqual(s["returns"], 2)
        self.assertEqual([x["step"] for x in s["return_sources"]], ["review-audit", "review-tests"])
        ladder.count_return(s, "human-rerun")
        self.assertEqual((s["returns"], s["return_sources"]), (3, []))

    def test_the_state_schema_takes_it(self):
        state = {"format": 1, "issue": 42, "revision": 2, "last_head": "a" * 40,
                 "steps": [{"id": "fix", "status": "pending", "latest_attempt": 1}]}
        ladder.count_return(state["steps"][0], codes.ReturnCause.LEADER_RERUN, [("review-audit", 2)])
        schema.validate(state, "state")

    def test_refusals_change_nothing(self):
        for cause, src in (("reverify", []), ("output-format", []), ("on-fail", [("x", 0)]), ("on-fail", [("", 1)]),
                           ("on-fail", [("x", True)])):
            s = {"id": "fix"}
            with self.subTest(cause=cause, src=src), self.assertRaises(ValueError):
                ladder.count_return(s, cause, src)
            self.assertEqual(s, {"id": "fix"})


class Resume(unittest.TestCase):
    def test_tm5(self):
        a, same = base(), copy.deepcopy(base())
        self.assertTrue(ladder.may_resume(a, same))
        self.assertFalse(ladder.may_resume(a, base(model="opus")))
        self.assertFalse(ladder.may_resume(a, base(model="opus", effort="xhigh")))
        self.assertFalse(ladder.may_resume(None, a))
        self.assertFalse(ladder.may_resume({"model": "sonnet", "effort": None}, a))

    def test_effort_only_change_keeps_the_resume_z3(self):
        # coordinator decision Z3 (V18 §5): an effort-only raise keeps --resume, a model change never does
        self.assertIs(ladder.EFFORT_CHANGE_RESUMES, True)
        self.assertTrue(ladder.may_resume(base(), base(effort="xhigh")))
        self.assertFalse(ladder.may_resume(base(), base(model="opus", effort="xhigh")))
        with mock.patch.object(ladder, "EFFORT_CHANGE_RESUMES", False):
            self.assertFalse(ladder.may_resume(base(), base(effort="xhigh")))


if __name__ == "__main__":
    unittest.main()
