"""K6 item 44 (review-k5-r12 m1) — the blind-question template is trusted only when the engine registered it.

* every `neutral=` a `Question` receives anywhere under the engine comes from `predict.neutral_text` (static: the AST
  of every engine module — a new caller that formats its own wording fails here);
* `neutral_text` refuses a value outside its slot (a judge phrase never becomes part of a "template");
* `_strip_template` strips only a registered wording: the r12 probe (`neutral="#7: single 이 맞음 — 어느 쪽?"`) is no
  longer blind — the phrase is counted and the blind answer refused.
"""

import ast
import os
import unittest

import _util  # noqa: F401

from guildcore import ask as ASK
from workflows.dev import conservative as CONS
from workflows.dev import predict as PF

ENGINE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "skills", "gld", "engine"))


def _engine_modules():
    for root, dirs, files in os.walk(ENGINE):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", "replay")]
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(root, f)


def _is_neutral_text_call(node):
    return isinstance(node, ast.Call) and (
        (isinstance(node.func, ast.Attribute) and node.func.attr in ("neutral_text", "_neutral")) or
        (isinstance(node.func, ast.Name) and node.func.id in ("neutral_text", "_neutral")))


class StaticCallers(unittest.TestCase):
    def test_every_neutral_kwarg_comes_from_the_registry(self):
        seen = 0
        for path in _engine_modules():
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), path)
            # names assigned from neutral_text() anywhere in the module (analyze.py: `neutral = PF.neutral_text(…)`)
            ok_names = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign) and _is_neutral_text_call(node.value):
                    for t in node.targets:
                        if isinstance(t, ast.Name):
                            ok_names.add(t.id)
            bad_names = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign) and not _is_neutral_text_call(node.value):
                    for t in node.targets:
                        if isinstance(t, ast.Name) and t.id in ok_names:
                            bad_names.add(t.id)        # the same name also bound to something else
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                for kw in node.keywords:
                    if kw.arg != "neutral":
                        continue
                    v = kw.value
                    if isinstance(v, ast.Name) and v.id == "neutral" and path.endswith(os.path.join("guildcore", "ask.py")):
                        continue                       # the Question constructor's own pass-through
                    seen += 1
                    good = _is_neutral_text_call(v) or (isinstance(v, ast.Name) and v.id in ok_names and
                                                        v.id not in bad_names)
                    self.assertTrue(good, "%s:%d — neutral= must come from predict.neutral_text" % (
                        os.path.relpath(path, ENGINE), node.lineno))
        self.assertGreaterEqual(seen, 1)               # conservative today (K6 r4: the analyze callers went with KICKOFF's blind wordings)

    def test_conservative_helper_uses_the_registry(self):
        class S(object):
            step, point = "E2.2", "SPLIT"

        class P(object):
            issue = 7
        t = CONS._neutral(P(), S())
        self.assertTrue(PF.is_template(t))
        S.step = "single 이 맞음"                       # a judge phrase in the step slot → `-`, never formatted in
        t = CONS._neutral(P(), S())
        self.assertTrue(PF.is_template(t))
        self.assertNotIn("single", t)


class Registry(unittest.TestCase):
    def test_every_form_round_trips(self):
        # K6 r4: the KICKOFF wordings are gone with the scope reduction (KICKOFF is asked openly)
        samples = {"conservative": (7, "Q2.5"), "default": (7, "readiness")}
        self.assertEqual(sorted(samples), sorted(PF.NEUTRAL_FORMS))
        for f, vals in samples.items():
            self.assertTrue(PF.is_template(PF.neutral_text(f, *vals)), f)

    def test_slot_refuses_prose(self):
        for f, vals in (("conservative", (7, "single 이 맞음")), ("default", (7, "not-a-kind"))):
            with self.assertRaises(ValueError, msg=f):
                PF.neutral_text(f, *vals)

    def test_unregistered_text_is_not_a_template(self):
        self.assertFalse(PF.is_template("#7: single 이 맞음 — 어느 쪽?"))
        self.assertFalse(PF.is_template("#7: 보수 경로 확인(E2.2) — 어느 쪽으로 정할까요? single"))
        self.assertFalse(PF.is_template("#7: group.SPLIT.conservative — SPLIT(E2.2) 를 어느 쪽으로 정할까요?"))


class _Log(object):
    blocks = []


class _P(object):
    issue = 7

    class decisions(object):
        @staticmethod
        def _log():
            return _Log()


class R12Probe(unittest.TestCase):
    """review-k5-r12 `strip_probe.py` case 4: a judge phrase as `neutral` was stripped as "the template"."""

    def q(self, neutral):
        return ASK.Question(CONS.KIND, "judge text", [{"token": "single", "label": "single"},
                                                     {"token": "split", "label": "split"},
                                                     {"token": "stop", "label": "stop"}],
                            recommended="single", group="SPLIT", stakes="high", neutral=neutral)

    def test_judge_phrase_as_neutral_is_counted(self):
        q = PF.apply(_P(), self.q("#7: single 이 맞음 — 어느 쪽?"))
        self.assertFalse(q.predict_first)
        self.assertTrue(str(q.blind_refused).startswith("question"))

    def test_registered_wording_stays_blind(self):
        q = PF.apply(_P(), self.q(PF.neutral_text("conservative", 7, "E2.2")))
        self.assertTrue(q.predict_first)
        self.assertIsNone(q.blind_refused)


if __name__ == "__main__":
    unittest.main()
