"""K5 review r11 — M1 (item 42: every gated group's conservative question stays blind — the gate's neutral wording
never names an option, and the leak check counts option mentions only outside the engine's own template), m2
(item 43, the cheap parts: the person confirms each of the judge's choices; a case that keeps asking fails the table).
"""

import unittest
from unittest import mock

import _util  # noqa: F401
import test_k5_r9 as R9
import test_k5_r10 as R10

from guildcore import ask as ASK
from workflows.dev import conservative as CONS
from workflows.dev import predict as PF
from workflows.dev.stages.base import StageResult

ADV, PAUSE, LOOP, DONE, SPLIT = (StageResult.ADVANCE, StageResult.PAUSE, StageResult.LOOPBACK, StageResult.DONE,
                                 StageResult.SPLIT)


def gated_cases():
    for group in CONS.GATED:
        for y in R10.gated_picks(group):
            yield group, y


def first_question(case, group, y):
    """The judge chose `y` (its own shape), the valve is on: the conservative question the gate raises."""
    build, run, _f, _y, _e = R9.SCENARIOS[group]
    h = build(case, R9.runner_judge(group, R10.shape_of(group, y), y))
    h.p.valves = {"group.%s.conservative" % group: True}
    run(h)
    qs = R9._open_questions(h, group)
    case.assertTrue(qs, (group, y))
    return h, qs[-1]


class M1EveryGatedGroupBlind(unittest.TestCase):
    def test_every_gated_group_has_a_case(self):
        self.assertEqual(sorted(set(g for g, _y in gated_cases())), sorted(CONS.GATED))
        self.assertEqual(len(CONS.GATED), 11)

    def test_conservative_question_is_blind(self):
        for group, y in gated_cases():
            with self.subTest(group=group, judge=y):
                h, q = first_question(self, group, y)
                self.assertIsNone(q.get("predict_first_refused"), (group, y, q.get("question")))
                self.assertTrue(q.get("recommended_sha"))
                self.assertIsNone(q.get("recommended"))
                self.assertTrue(q.get("predict_first"))
                # the neutral wording carries no group name (SPLIT is the option `split`)
                self.assertNotIn(group, str(q.get("question")))
                for c in h.gh.comments(h.n):
                    body = c.get("body") or ""
                    if "guild:needs-human" in body:
                        self.assertNotIn("group.%s.conservative" % group, body)


class _Log(object):
    blocks = []


class _P(object):
    issue = 7

    class decisions(object):
        @staticmethod
        def _log():
            return _Log()


class M1TemplateIgnored(unittest.TestCase):
    """Structural: an option token inside the engine's own template is never counted; text outside it still is."""

    def q(self):
        q = ASK.Question(CONS.KIND, "judge: split is right", [{"token": "single", "label": "single"},
                                                               {"token": "split", "label": "split"},
                                                               {"token": "stop", "label": "stop"}],
                         recommended="single", group="SPLIT", stakes="high",
                         # K6 (item 44): a registered wording — an unregistered one is no longer stripped
                         neutral=PF.neutral_text("conservative", 7, "E2.2"))
        q.predict_first = True
        return q

    def test_template_with_a_token_stays_blind(self):
        q = PF.apply(_P(), self.q(), texts=["group.SPLIT.conservative — SPLIT E2.2 결정을 사람이 정함"])
        self.assertIsNone(getattr(q, "blind_refused", None))
        self.assertTrue(q.predict_first)

    def test_non_template_text_still_counts(self):
        q = self.q()
        q.predict_first = True
        q.original, q.text, q.neutralized = q.text, q.neutral, True
        self.assertEqual(PF.leak(_P(), q, texts=[q.neutral + " / split 이 맞음"]), "text")
        self.assertIsNone(PF.leak(_P(), q, texts=[q.neutral]))

    def test_strip_template(self):
        t = PF.neutral_text("conservative", 7, "E2.2")
        self.assertEqual(PF._strip_template("a %s b %s" % (t, t), t), "a   b  ")
        self.assertEqual(PF._strip_template("a T", None), "a T")
        # K6 (r12 m1, item 44): text that is not a registered wording is never stripped
        self.assertEqual(PF._strip_template("a T b", "T"), "a T b")


# m2(a): the person confirms the judge's choice Y (X = Y) for EVERY Y the gate asks about — Y's own output shape
CONFIRM = {
    ("STAKES", "low"): (ADV, [R10._labels("guild:design")]),
    ("STAKES", "medium"): (ADV, [R10._labels("guild:design")]),
    ("SPLIT", "single"): (ADV, [R10._labels("guild:execute")]),
    ("SPLIT", "split"): (SPLIT, [R10._labels("guild:children"), R10._no_labels("guild:execute")]),
    ("INTEGRATE", "clean"): (DONE, [R10._labels("guild:done")]),
    ("TEST", "all_effective"): (ADV, [R10._labels("guild:qa")]),
    ("QA", "pass"): (DONE, [R10._labels("guild:done")]),
    ("DE-ARB", "reinvoke"): (ADV, [R10._labels("guild:execute")]),
    ("DE-ARB", "decide"): (PAUSE, [R10._has("가정으로 넘기기엔 stakes high"), R10._no_labels("guild:execute")]),
    ("DE-ARB", "escalate"): (PAUSE, [R10._has("설계 막힘(tech-lead): which module?"),
                                     R10._no_labels("guild:execute")]),
    ("AN-PO", "record"): (ADV, [R10._labels("guild:design")]),
    ("VIS-ENV", "regression"): (LOOP, [R10._labels("guild:execute")]),
    ("DIRECTIVE", "applies"): (PAUSE, [R10._has("적용 가능한 사람 지시"), R10._lacks("사람 지시 확인: 없음")]),
    ("DIRECTIVE", "none"): (PAUSE, [R10._has("사람 지시 확인: 없음"), R10._lacks("적용 가능한 사람 지시")]),
    ("HANDOFF", "ok"): (PAUSE, [R10._has("test ran"), R10._labels("guild:test"), R10._no_labels("guild:needs-human")]),
    ("HANDOFF", "ok_with_assumption"): (PAUSE, [R10._has("test ran"), R10._labels("guild:test"),
                                                R10._no_labels("guild:needs-human")]),
    ("EX-DWC", "loop_back"): (ADV, [lambda o: o["tl_calls"] >= 2]),
}


class M2ConfirmTheJudge(unittest.TestCase):
    def test_every_gated_pick_has_a_confirm_row(self):
        self.assertEqual(sorted(CONFIRM), sorted(gated_cases()))

    def test_person_confirms_judge(self):
        for group, y in gated_cases():
            with self.subTest(group=group, choice=y):
                o = R10.run_case(self, group, y, y)
                self.assertEqual(o["asked"], 1)
                kind, checks = CONFIRM[(group, y)]
                self.assertEqual(o["kind"], kind, (o["line"], o["labels"]))
                for i, c in enumerate(checks):
                    self.assertTrue(c(o), (i, o["line"], o["labels"]))
                b = o["block"]
                # the person's confirmation runs as is: logged as theirs, no rule replaced it
                self.assertEqual((b.get("by"), b.get("human_choice"), b.get("coerced_to")), ("human", None, None))
                if group != "TEST":                          # TEST logs its effect (`effective:…;uncovered:…`)
                    self.assertEqual(b.get("choice"), y)
                q = [x for x in o["all"] if x.get("kind") == CONS.KIND and x.get("status") == "pending-human"]
                self.assertTrue(q and all(x.get("recommended_sha") and not x.get("predict_first_refused") for x in q))


class M2EndlessQuestionsFail(unittest.TestCase):
    """m2(b): a case whose answer keeps raising a question fails the table (cap `QUESTION_CAP`)."""

    def test_cap(self):
        self.assertEqual(R10.QUESTION_CAP, 3)
        answered = []
        with mock.patch.object(R9, "_open_questions", lambda h, g: [type("B", (), {"id": "D9"})()]), \
                mock.patch.object(R9, "_answer", lambda h, blk, x: answered.append(x)):
            with self.assertRaises(AssertionError) as cm:
                R10.run_case(self, "QA", "block", "pass")
        self.assertIn("still asking after 3 answers", str(cm.exception))
        self.assertEqual(answered, ["block"] * 3)


if __name__ == "__main__":
    unittest.main()
