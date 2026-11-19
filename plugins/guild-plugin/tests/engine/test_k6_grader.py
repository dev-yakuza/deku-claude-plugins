"""K6 item 11 — the grader's evidence, quality rules and the dual-judgment trigger (§9.4-7, §9.5).

* call ① gets the Issue's AC and (from the replay harness) the evidence part of the judge's original brief; neither
  can ground an `ok` (they are what the judge saw, not what happened after);
* grader quality: the share of the grader's `wrong`s a person confirmed (≥ 10 judged, < 50 % → alert); a grader
  revision is adoptable only when its agreement with the person on the latest 20 is ≥ the old version's;
* dual judgment: a deterministic share of judge decisions judged again by another tier (monitoring), recorded on the
  block; a disagreement triggers grading and counts in `dev health`.
"""

import json
import unittest

import _util  # noqa: F401
from _k1 import tmpdir
from _k2 import role
from test_k2_qa_stage import qa_harness

from guildcore import journal as J
from guildcore.decisions import DecisionLog
from guildcore.judges.runner import Decision
from guildcore.records.decisions import DecisionBlock
from workflows.dev import dual as DUAL
from workflows.dev import grade as G
from workflows.dev import grader as GD
from workflows.dev import health as HE
from workflows.dev.stages import qa as Q


def _block(fields, n=3):
    return DecisionBlock(n, list(fields.items()))


class Evidence(unittest.TestCase):
    def test_call_one_sees_ac_and_brief_and_they_never_ground_ok(self):
        seen = []

        def judge(spec):
            seen.append(dict(spec.brief_parts))
            if spec.choice_key == "choice":
                return Decision("all_effective", {"choice": "effective:AC #1;uncovered:none", "reason": "r",
                                                  "cited_evidence": []}, "judge:opus", "g1")
            return Decision("ok", {"given_info": "ok", "outcome": "consistent", "reason": "r",
                                   "cited_evidence": ["the judge saw: login button test asserts redirect"]},
                            "judge:opus", "g2")
        blk = _block({"point": "TEST", "stage": "test", "by": "judge:sonnet", "choice": "effective:AC #1;uncovered:none",
                      "refs": "AC #1"})
        row = GD.grade(judge, blk, 7, "TEST", "CI green", issue_text="login", ac="AC #1: 로그인 후 홈으로 이동",
                       brief="the judge saw: login button test asserts redirect")
        self.assertIn("acceptance_criteria", seen[0])
        self.assertIn("original_brief_evidence", seen[0])
        self.assertNotIn("effective:AC", seen[0]["decision"])            # never the judge's own answer in ①
        self.assertEqual(row["given_info"], "unsure")                    # the brief is not post-hoc evidence
        self.assertTrue(row["flagged"])


class SeenCitations(unittest.TestCase):
    """measured with a local model (k6-notes): citing the AC or the judge's brief demoted 9 of 10 grades — those
    citations exist verbatim; they are verified, and only an `ok` needs post-hoc grounds."""

    def _judge(self, gi, cites):
        def judge(spec):
            if spec.choice_key == "choice":
                return Decision("block", {"choice": "block", "reason": "r", "cited_evidence": cites},
                                "judge:opus", "g1")
            return Decision(gi, {"given_info": gi, "outcome": "inconsistent", "reason": "r",
                                 "cited_evidence": cites}, "judge:opus", "g2")
        return judge

    def test_wrong_citing_the_brief_and_ac_stands(self):
        blk = _block({"point": "QA", "stage": "qa", "by": "judge:sonnet", "choice": "pass"})
        row = GD.grade(self._judge("wrong", ["AC #2: 오답이 0개이면 버튼이 비활성화된다", "AC #2 not exercised on device"]),
                       blk, 7, "QA", "review: crash on empty retry", issue_text="quiz", ac="AC #2: 오답이 0개이면 버튼이 비활성화된다",
                       brief="qa report: AC #2 not exercised on device")
        self.assertEqual((row["given_info"], row["demoted"]), ("wrong", None))

    def test_ok_on_the_brief_alone_is_unsure(self):
        blk = _block({"point": "QA", "stage": "qa", "by": "judge:sonnet", "choice": "pass"})
        row = GD.grade(self._judge("ok", ["qa report: all widget tests green on the quiz screen"]), blk, 7, "QA",
                       "merged", issue_text="quiz", brief="qa report: all widget tests green on the quiz screen")
        self.assertEqual(row["given_info"], "unsure")
        self.assertIn("brief", row["demoted"])


def _grade_row(issue, did, gi, gv, kind=None):
    r = {"repo": "o/r", "issue": issue, "decision_id": did, "given_info": gi, "grader_version": gv, "group": "QA"}
    if kind:
        r.update(kind=kind, pass_=1)
    return r


class Quality(unittest.TestCase):
    def setUp(self):
        self.common = tmpdir(self)

    def _write(self, rows):
        for r in rows:
            J.fsync_append(G.grades_path(self.common), json.dumps(r))

    def test_low_confirmation_alerts(self):
        rows = [_grade_row(i, "D1", "wrong", "gA", "grader") for i in range(10)]
        rows += [_grade_row(i, "D1", "wrong" if i < 4 else "ok", "human") for i in range(10)]
        self._write(rows)
        q = G.grader_quality(self.common, "o/r", "gA")
        self.assertEqual((q["wrong_confirmation"]["judged"], q["wrong_confirmation"]["confirmed"]), (10, 4))
        self.assertTrue(q["wrong_confirmation"]["alert"])

    def test_nine_never_alert(self):
        rows = [_grade_row(i, "D1", "wrong", "gA", "grader") for i in range(9)]
        rows += [_grade_row(i, "D1", "ok", "human") for i in range(9)]
        self._write(rows)
        self.assertFalse(G.grader_quality(self.common, "o/r", "gA")["wrong_confirmation"]["alert"])

    def test_revision_gate(self):
        rows = [_grade_row(i, "D1", "ok", "human") for i in range(20)]
        rows += [_grade_row(i, "D1", "ok" if i < 15 else "wrong", "gOld", "grader") for i in range(20)]
        rows += [_grade_row(i, "D1", "ok" if i < 18 else "wrong", "gNew", "grader") for i in range(20)]
        self._write(rows)
        rev = G.grader_quality(self.common, "o/r", "gNew", "gOld")["revision"]
        self.assertEqual((rev["new_agreement"], rev["old_agreement"]), (0.9, 0.75))
        self.assertTrue(rev["adoptable"])
        rev = G.grader_quality(self.common, "o/r", "gOld", "gNew")["revision"]
        self.assertFalse(rev["adoptable"])

    def test_revision_needs_twenty(self):
        rows = [_grade_row(i, "D1", "ok", "human") for i in range(20)]
        rows += [_grade_row(i, "D1", "ok", "gOld", "grader") for i in range(20)]
        rows += [_grade_row(i, "D1", "ok", "gNew", "grader") for i in range(12)]
        self._write(rows)
        self.assertIsNone(G.grader_quality(self.common, "o/r", "gNew", "gOld")["revision"]["adoptable"])


class Dual(unittest.TestCase):
    def _h(self, rate, second="pass"):
        calls = []

        def qa_judge(spec):
            calls.append(spec.model)
            v = "pass" if len(calls) == 1 else second
            return Decision(v, {"defects": [], "checklist": [], "verdict": v, "quality_bar_met": "yes"},
                            "judge:%s" % spec.model, "dg%d" % len(calls))
        h = qa_harness(self, roles=[role("DONE", plan="qa-report.md", human_items=[], followups=[])] * 2,
                       judges={"QA": qa_judge})
        h.p.dual_rate = rate
        return h, calls

    def _qa_block(self, h):
        return [b for b in DecisionLog.load(h.gh.comments(7)).blocks if b.get("point") == "QA"][-1]

    def test_sampled_decision_is_judged_by_another_tier(self):
        h, calls = self._h(1.0, second="block")
        r = Q.run(h.p, diff_paths=[])
        self.assertEqual(r.token(), "OK DONE")                           # the flow follows the first decision
        self.assertEqual(len(calls), 2)
        self.assertNotEqual(calls[0], calls[1])
        b = self._qa_block(h)
        self.assertEqual((b.get("dual"), b.get("dual_choice")), ("disagree", "block"))
        self.assertTrue(G.triggered(b, None).startswith("dual-judge disagreement"))
        self.assertEqual(HE.metrics({7: [b]})["dual_disagree"], 1.0)

    def test_rate_zero_never_calls_twice(self):
        h, calls = self._h(0)
        Q.run(h.p, diff_paths=[])
        self.assertEqual(len(calls), 1)
        self.assertIsNone(self._qa_block(h).get("dual"))

    def test_selection_is_deterministic_and_near_the_rate(self):
        class P(object):
            issue = 7
        hits = 0
        for i in range(2000):
            s = type("S", (), {"group": "QA", "point": "QA", "stage": "qa", "step": "Q%d" % i})()
            a, b = DUAL.selected(P(), s, 0.10), DUAL.selected(P(), s, 0.10)
            self.assertEqual(a, b)
            hits += a
        self.assertTrue(150 <= hits <= 250, hits)

    def test_tiers(self):
        self.assertEqual(DUAL.other_tier("claude-opus-x"), "sonnet")
        self.assertEqual(DUAL.other_tier("sonnet"), "opus")
        self.assertEqual(DUAL.other_tier("haiku"), "sonnet")


if __name__ == "__main__":
    unittest.main()
