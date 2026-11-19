"""K5 review r10 — M1 (a person's AN-PO `rerate_success` never runs on the `rating` a judge echoed with `record`), m1 (a
person's TEST `gap` with a stray visual row on an Issue without visual cases), m2 (a rule that replaces a person's
choice is logged apart from it), m4 (the table: for every gated group and option X, a judge that chose ANOTHER option Y
— its own minimal output shape, never every option's fields pre-filled — and a person answering X; the expected result
of X is stated independently and tells the options apart).
"""

import copy
import os
import unittest

import _util  # noqa: F401
import test_k5_r9 as R9
from test_k4_design import SPLIT

from workflows.dev import conservative as CONS
from workflows.dev import judging as JG
from workflows.dev.stages.base import StageResult

ADV, PAUSE, LOOP, DONE = StageResult.ADVANCE, StageResult.PAUSE, StageResult.LOOPBACK, StageResult.DONE
_HIT = [{"comment": "#7", "line": "CI 실패는 무시"}]

# group → {Y: what a judge that chose Y writes} — Y's own fields only, plus the stray echoes a model naturally adds
# (AN-PO `record` echoing the current rating — review-k5-r10 M1; TEST a stray visual row on an Issue without visual
# cases — m1). Only options the gate asks about (the judge's non-conservative picks) appear.
SHAPES = {
    "TEST": {"all_effective": {"ac": [{"id": a, "covered_by": ["test/a_test.dart::t"], "verdict": "effective",
                                       "why": "w"} for a in ("C1", "C2")],
                               "visual_rows": [{"row": "V1", "verdict": "unsure"}]}},
    "VIS-ENV": {"regression": {"why": "pixels moved"}},
    "QA": {"pass": {"defects": [], "checklist": ["로그인 확인"], "quality_bar_met": "yes"}},
    "DIRECTIVE": {"applies": {"applies": copy.deepcopy(_HIT), "out_of_scope": []},
                  "none": {"applies": [], "out_of_scope": []}},
    "INTEGRATE": {"clean": {"coverage": [], "gaps": []}},
    "STAKES": {"low": {"local_reversible_reason": "local to one widget, a revert undoes it", "cites": []},
               "medium": {"local_reversible_reason": "two widgets, a revert undoes it", "cites": []}},
    "AN-PO": {"record": {"reason": "worth recording; Success stays clear", "rating": "clear"}},
    "DE-ARB": {"reinvoke": {"role": "tech-lead", "addendum": "use lib/app only"},
               "decide": {"assumption": "keep one module"},
               "escalate": {"reason": "executor_conflict", "question": "which module?", "options": []}},
    "SPLIT": {"single": {"slices": [], "reason": "one PR"},
              "split": {"slices": copy.deepcopy(SPLIT["slices"]), "reason": "two PRs"}},
    "HANDOFF": {"ok": {"reason": "fine"}, "ok_with_assumption": {"line": "evidence is in the PR"}},
    "EX-DWC": {"loop_back": {"reason": "M4 mutant not pinned"}},
}


def _blocks(h):
    return R9._blocks(h)


def _has(text):
    return lambda o: text in o["line"]


def _lacks(text):
    return lambda o: text not in o["line"]


def _labels(*want):
    return lambda o: all(w in o["labels"] for w in want)


def _no_labels(*no):
    return lambda o: not any(w in o["labels"] for w in no)


def _logged(choice, human_choice=None):
    """The group's last judgment block: `choice` ran, by the person; `human_choice` = a rule replaced the answer."""
    def ok(o):
        b = o["block"]
        return b is not None and b.get("by") == "human" and b.get("choice") == choice and \
            b.get("human_choice") == human_choice and (human_choice is None) == (b.get("coerced_to") is None)
    return ok


def _readiness(o):
    return any(b.get("kind") == "readiness" and b.get("status") == "pending-human" for b in o["all"])


# (group, X) → (the result kind, [the checks that tell X apart from the group's other options])
EXPECT = {
    ("TEST", "all_effective"): (ADV, [_labels("guild:qa")]),
    ("TEST", "gap"): (LOOP, [_labels("guild:execute"), _no_labels("guild:qa"), _logged("effective:none;uncovered:C1,C2")]),
    ("VIS-ENV", "regression"): (LOOP, [_labels("guild:execute")]),
    ("VIS-ENV", "env_suspect"): (PAUSE, [_no_labels("guild:execute"), _labels("guild:needs-human")]),
    ("QA", "pass"): (DONE, [_labels("guild:done")]),
    ("QA", "block"): (PAUSE, [_no_labels("guild:done"), _logged("block")]),
    ("DIRECTIVE", "applies"): (PAUSE, [_has("적용 가능한 사람 지시"), _logged("applies")]),
    ("DIRECTIVE", "none"): (PAUSE, [_has("사람 지시 확인: 없음"), _lacks("적용 가능한 사람 지시"), _logged("none")]),
    ("DIRECTIVE", "out_of_scope"): (PAUSE, [_has("적용 가능한 사람 지시"), _has("사람이 범위 밖 지시로 판정"),
                                            _lacks("CI 실패는 무시"), _logged("out_of_scope")]),
    ("INTEGRATE", "clean"): (DONE, [_labels("guild:done")]),
    ("INTEGRATE", "gap"): (PAUSE, [_has("사람이 통합 간극으로 판정"), _no_labels("guild:done"), _logged("gap")]),
    ("STAKES", "low"): (ADV, [_labels("guild:design"), _logged("low")]),
    ("STAKES", "medium"): (ADV, [_labels("guild:design"), _logged("medium")]),
    ("STAKES", "high"): (PAUSE, [_no_labels("guild:design"), _logged("high")]),
    ("AN-PO", "record"): (ADV, [_labels("guild:design"), _logged("record")]),
    ("AN-PO", "rerate_success"): (PAUSE, [_has("Success unclear"), _readiness, _no_labels("guild:design"),
                                          _logged("rerate_success")]),
    # a judge that chose another option wrote no role/addendum (reinvoke), assumption (decide) or escalation reason:
    # the person's choice has no grounds to run on — the same rule as the judge's own → pause, logged apart (m2)
    ("DE-ARB", "reinvoke"): (PAUSE, [_no_labels("guild:execute"), _logged("pause", "reinvoke")]),
    ("DE-ARB", "decide"): (PAUSE, [_no_labels("guild:execute"), _logged("pause", "decide")]),
    ("DE-ARB", "escalate"): (PAUSE, [_no_labels("guild:execute"), _logged("pause", "escalate")]),
    ("DE-ARB", "pause"): (PAUSE, [_no_labels("guild:execute"), _lacks("— which module?"), _logged("pause")]),
    ("SPLIT", "single"): (ADV, [_labels("guild:execute"), _logged("single")]),
    # no slices from a judge that chose single: unsure → a person (the judge's own split without slices, too)
    ("SPLIT", "split"): (PAUSE, [_has("분할 판단 불확실"), _no_labels("guild:execute"), _logged("unsure", "split")]),
    ("HANDOFF", "ok"): (PAUSE, [_has("test ran"), _labels("guild:test"), _no_labels("guild:needs-human"),
                                _logged("ok")]),
    ("HANDOFF", "ok_with_assumption"): (PAUSE, [_has("hand-over gap"), _labels("guild:needs-human"),
                                                _logged("upstream_gap", "ok_with_assumption")]),
    ("HANDOFF", "upstream_gap"): (PAUSE, [_has("hand-over gap"), _labels("guild:needs-human"),
                                          _logged("upstream_gap")]),
    ("EX-DWC", "loop_back"): (ADV, [lambda o: o["tl_calls"] >= 2, _logged("loop_back")]),
    ("EX-DWC", "proceed"): (ADV, [lambda o: o["tl_calls"] == 1, _logged("proceed")]),
}

# the judge chose Y, the person X ≠ Y, and a rule the judge's own output would meet the same way replaces X: the
# person's answer and what ran are logged apart (m2)
COERCED = {
    ("DE-ARB", "reinvoke"): "pause",               # no role / addendum
    ("SPLIT", "split"): "unsure",                  # no slices
    ("DE-ARB", "decide"): "pause",                 # no assumption (the judge wrote none: it chose another option)
    ("DE-ARB", "escalate"): "pause",               # no escalation reason
    ("HANDOFF", "ok_with_assumption"): "upstream_gap",   # no assumption line
}


def options(group):
    return R9.options(group)


def gated_picks(group):
    """The judge choices that raise the group's conservative question."""
    safe = JG.UNSURE.get(group)
    return [y for y in options(group) if y != safe]


def cases():
    for group in CONS.GATED:
        for x in options(group):
            ys = [y for y in gated_picks(group) if y != x] or [x]
            for y in ys:
                yield group, x, y


def shape_of(group, y):
    return lambda _c: copy.deepcopy(SHAPES[group][y])


def run_case(case, group, x, y):
    build, run, _f, _y, _e = R9.SCENARIOS[group]
    h = build(case, R9.runner_judge(group, shape_of(group, y), y))
    h.p.valves = {"group.%s.conservative" % group: True}
    asked, r = 0, None
    for _i in range(5):
        r = run(h)
        q = R9._open_questions(h, group)
        if not q:
            break
        asked += 1
        R9._answer(h, q[-1], x)
    blocks = _blocks(h)
    mine = [b for b in blocks if b.get("point") == group]
    line = str(getattr(r, "cause", None) or getattr(r, "line", None) or "")
    said = [c.get("body") or "" for c in h.gh.comments(h.n) if "사람 지시" in (c.get("body") or "")]
    if said:                                         # the directive line rides in the pause's needs-human comment
        line = "%s || %s" % (line, said[-1])
    return {"kind": getattr(r, "kind", r), "line": line,
            "labels": h.labels(), "block": mine[-1] if mine else None, "all": blocks, "asked": asked,
            "tl_calls": (getattr(h, "exdwc_seen", None) or {}).get("tl", 0)}


class Table(unittest.TestCase):
    def test_every_gated_option_has_an_expectation(self):
        self.assertEqual(sorted(SHAPES), sorted(CONS.GATED))
        for group in CONS.GATED:
            for x in options(group):
                self.assertIn((group, x), EXPECT)
            for y in gated_picks(group):
                self.assertIn(y, SHAPES[group], (group, y))

    def test_answer_x_over_a_judges_y(self):
        got = {}
        for group, x, y in cases():
            with self.subTest(group=group, option=x, judge=y):
                o = run_case(self, group, x, y)
                if os.environ.get("K5R10_PROBE"):
                    b = o["block"] or {}
                    print("\n%s X=%s Y=%s -> %s | %s | %s | %s/%s/%s | asked %d tl %d" % (
                        group, x, y, o["kind"], o["line"][:110], o["labels"], b.get("choice"), b.get("by"),
                        b.get("human_choice"), o["asked"], o["tl_calls"]))
                self.assertGreaterEqual(o["asked"], 1)
                kind, checks = EXPECT[(group, x)]
                self.assertEqual(o["kind"], kind, (o["line"], o["labels"]))
                for i, c in enumerate(checks):
                    self.assertTrue(c(o), (i, o["line"], o["labels"], repr(o["block"])))
                want = COERCED.get((group, x))
                if want:
                    self.assertEqual((o["block"].get("choice"), o["block"].get("by"), o["block"].get("human_choice")),
                                     (want, "human", x))
                    self.assertTrue(str(o["block"].get("coerced_to") or "").startswith("%s by rule " % want))
                got.setdefault((group, x), []).append(o)
        # m4: the expectations tell the options apart — no option's outcome meets another option's expectation
        # (HANDOFF / DIRECTIVE / EX-DWC included)
        for (group, x), outs in got.items():
            for x2 in options(group):
                if x2 == x:
                    continue
                kind, checks = EXPECT[(group, x2)]
                for o in outs:
                    with self.subTest(group=group, option=x, against=x2):
                        self.assertFalse(o["kind"] == kind and all(c(o) for c in checks))


class M1AnPoRerate(unittest.TestCase):
    """review-k5-r10 anpo_rerate_noop.py — the judge says `record` and echoes `rating: clear`."""

    def go(self, shape):
        build, run, _f, _y, _e = R9.SCENARIOS["AN-PO"]
        h = build(self, R9.runner_judge("AN-PO", lambda _c: dict(shape), "record"))
        h.p.valves = {"group.AN-PO.conservative": True}
        run(h)
        R9._answer(h, R9._open_questions(h, "AN-PO")[-1], "rerate_success")
        r = run(h)
        self.assertEqual(r.kind, PAUSE)
        self.assertIn("Success unclear", r.cause)
        self.assertNotIn("guild:design", h.labels())
        self.assertTrue([b for b in _blocks(h) if b.get("kind") == "readiness" and b.get("status") == "pending-human"])

    def test_rating_absent(self):
        self.go({"reason": "worth recording"})

    def test_rating_clear_echoed(self):
        self.go({"reason": "worth recording; Success stays clear", "rating": "clear"})

    def test_rating_partial_with_anchor_echoed(self):
        self.go({"reason": "r", "rating": "partial", "anchor": {"cite": "lib/app/home.dart:3", "quote": "x"}})

    def test_the_judges_own_rerate_is_never_clear(self):
        f, by = JG.coerce_an_po({"action": "rerate_success", "rating": "clear"})
        self.assertEqual((f["rating"], by), ("unclear", "rule"))

    def test_own_fields(self):
        f = JG.own_fields("AN-PO", "rerate_success", "record", {"rating": "clear", "anchor": {"cite": "a"},
                                                                 "reason": "r"}, "D3")
        self.assertEqual(f, {"rating": "unclear", "anchor": None, "reason": "r"})
        f = JG.own_fields("DE-ARB", "pause", "escalate", {"reason": "executor_conflict", "question": "q",
                                                          "options": ["a"], "role": "x"}, "D3")
        self.assertEqual(f, {"options": ["a"]})                     # shared by pause and escalate
        f = JG.own_fields("STAKES", "medium", "low", {"local_reversible_reason": "why", "cites": []}, "D3")
        self.assertEqual(f["local_reversible_reason"], "why")      # shared by low and medium
        f = JG.own_fields("HANDOFF", "upstream_gap", "ok_with_assumption", {"line": "l", "signature": ["s"]}, "D3")
        self.assertEqual(f, {"fixable_by_execute": False})


class M1TestStrayRow(unittest.TestCase):
    """review-k5-r10 test_gap_row.py — judge all_effective + a stray visual row on an Issue without visual cases."""

    def test_person_gap(self):
        o = run_case(self, "TEST", "gap", "all_effective")
        self.assertNotEqual(o["kind"], ADV)
        self.assertNotIn("guild:qa", o["labels"])

    def test_judges_own_gap(self):
        build, run, _f, _y, _e = R9.SCENARIOS["TEST"]
        shape = dict(copy.deepcopy(SHAPES["TEST"]["all_effective"]))
        h = build(self, R9.runner_judge("TEST", lambda _c: copy.deepcopy(shape), "gap"))
        r = run(h)
        self.assertNotEqual(r.kind, ADV)
        self.assertNotIn("guild:qa", h.labels())


class M2CoercedLogged(unittest.TestCase):
    """review-k5-r10 coerce_override.py — the person's choice and the rule's result, apart."""

    def test_dearb_decide(self):
        o = run_case(self, "DE-ARB", "decide", "reinvoke")
        b = o["block"]
        self.assertEqual((b.get("choice"), b.get("by"), b.get("human_choice")), ("pause", "human", "decide"))
        self.assertEqual(b.get("coerced_to"), "pause by rule coerce_de_arb")

    def test_handoff_ok_with_assumption(self):
        o = run_case(self, "HANDOFF", "ok_with_assumption", "ok")
        b = o["block"]
        self.assertEqual((b.get("choice"), b.get("human_choice"), b.get("coerced_to")),
                         ("upstream_gap", "ok_with_assumption", "upstream_gap by rule coerce_handoff"))

    def test_a_choice_that_stands_has_no_coercion_fields(self):
        o = run_case(self, "QA", "block", "pass")
        self.assertIsNone(o["block"].get("human_choice"))
        self.assertIsNone(o["block"].get("coerced_to"))


if __name__ == "__main__":
    unittest.main()
