"""K6 items 33 + 40 — a conservative answer belongs to the stage run that asked.

40 (review-k5-r10 m3, `crash_then_rollback.py`): an answer whose run crashed after the gate and was then reworked
(another diff / Issue text before the gate) is not applied to the new run on its own: the point is judged again and
the answer applies only when the judge chooses what the person was asked about; otherwise it is retired (`stale`).
33 (review-k5-r8 m1): the stage run's identity (`cons_run`, `cons_brief`) and the answers it already applied
(`cons_used`) ride on the GitHub pending block — a clone without the local tape reuses them while the run's role calls
match (one question per point, never 2ⁿ−1).
"""

import unittest

import _util  # noqa: F401
from _k2 import role
from test_k2_qa_stage import qa_harness

from guildcore import ask as ASK
from guildcore.decisions import DecisionLog
from guildcore.judges.runner import Decision
from workflows.dev import conservative as CONS
from workflows.dev import judging as JG
from workflows.dev.stages import base as B
from workflows.dev.stages import qa as Q
from workflows.dev.stages.base import StageResult


def _blocks(h):
    return DecisionLog.load(h.gh.comments(7)).blocks


def _pending(h):
    return [b for b in _blocks(h) if b.get("kind") == CONS.KIND and b.get("status") == "pending-human"]


def _unlabel(h, *names):
    iss = h.gh.fx["issues"]["7"]
    drop = set(names or ("guild:needs-human",))
    iss["labels"] = [lb for lb in iss["labels"] if (lb.get("name") if isinstance(lb, dict) else lb) not in drop]


def _qa_judge(calls, verdicts):
    def j(spec):
        v = verdicts[min(len(calls), len(verdicts) - 1)]
        calls.append(v)
        return Decision(v, {"defects": [] if v == "pass" else [{"id": "F1", "blocking": True, "line": "crash"}],
                            "checklist": [], "quality_bar_met": "yes" if v == "pass" else "no", "verdict": v},
                        "judge:sonnet", "dg%d" % len(calls))
    return j


class CrashThenRework(unittest.TestCase):
    """review-k5-r10 m3: QA `pass` answered; the run that applies it crashes after the gate; the person reworks
    (`/gld rollback`, new diff) and qa runs again."""

    def _crashed(self, verdicts):
        calls = []
        h = qa_harness(self, unattended=False, roles=[role("DONE", plan="qa-report.md", human_items=[],
                                                           followups=[])] * 8, judges={"QA": _qa_judge(calls, verdicts)})
        h.p.valves = {"group.QA.conservative": True}
        h.p.git_dir = None
        g = lambda paths: CONS.guarded(h.p, "qa", lambda: Q.run(h.p, diff_paths=paths))  # noqa: E731
        self.assertEqual(g([]).kind, StageResult.ASK)
        ASK.answer(h.decisions, h.writer, 7, _pending(h)[-1].id, "pass")
        orig = h.writer.upsert_comment
        state = {"n": 0}

        def flaky(issue, name, body, *a, **k):
            if name == Q.R.QA and state["n"] == 0:
                state["n"] += 1
                raise RuntimeError("HTTP 502 from GitHub")
            return orig(issue, name, body, *a, **k)
        h.writer.upsert_comment = flaky
        with self.assertRaises(RuntimeError):
            g([])
        self.assertEqual([b for b in _blocks(h) if b.get("point") == "applied"], [])
        return h, calls, g

    def test_judge_now_blocks_the_old_pass_never_applies(self):
        h, calls, g = self._crashed(["pass", "block"])
        n0 = len(calls)
        r = g(["lib/login.dart"])                                         # reworked code: another brief
        self.assertEqual(len(calls) - n0, 1)                             # judged again on the new run
        self.assertNotEqual(r.kind, StageResult.DONE)
        self.assertNotIn("guild:done", h.labels())
        stale = [b for b in _blocks(h) if b.get("point") == CONS.STALE]
        self.assertEqual(len(stale), 1)
        self.assertEqual(stale[0].get("choice"), "pass")
        last = [b for b in _blocks(h) if b.get("point") == "QA"][-1]
        self.assertEqual((last.get("choice"), last.get("by")), ("block", "judge:sonnet"))

    def test_judge_now_agrees_the_answer_applies(self):
        h, calls, g = self._crashed(["pass"])
        n0 = len(calls)
        self.assertEqual(g(["lib/login.dart"]).kind, StageResult.DONE)
        self.assertEqual(len(calls) - n0, 1)                             # one check, no new question
        self.assertEqual(len(_pending(h)), 1)
        self.assertEqual([b for b in _blocks(h) if b.get("point") == CONS.STALE], [])

    def test_same_run_applies_without_a_new_judge_call(self):
        h, calls, g = self._crashed(["pass", "block"])
        n0 = len(calls)
        self.assertEqual(g([]).kind, StageResult.DONE)                    # nothing changed: the same run
        self.assertEqual(len(calls) - n0, 0)


class TwoPointsAcrossClones(unittest.TestCase):
    """review-k5-r8 m1: a stage with n conservative points asked 2ⁿ−1 times when the local tape was gone."""

    def _h(self):
        h = qa_harness(self, roles=[role("DONE", plan="qa-report.md", human_items=[], followups=[])] * 6)
        h.p.valves = {"group.QA.conservative": True, "group.TEST.conservative": True}
        h.p.git_dir = None
        h.p.journal = None
        return h

    def _stage_run(self, h, judged, issue="login"):
        CONS.begin(h.p)
        CONS.role(h.p, B.RoleCall("qa", "run", "qa", "Q1", inputs={"issue.md": issue}),
                  lambda c: role("DONE", line="qa: green", plan="qa-report.md", human_items=[], followups=[]))

        def qa_judge(spec):
            judged.append("QA")
            return Decision("pass", {"verdict": "pass", "quality_bar_met": "yes"}, "judge:sonnet", "dgQ")

        def test_judge(spec):
            judged.append("TEST")
            return Decision("all_effective", {"overall": "all_effective"}, "judge:sonnet", "dgT")
        a = CONS.gate(h.p, JG.spec(h.p, "QA", [("x", "y")], "qa", "Q2.5"), qa_judge)
        t = CONS.gate(h.p, JG.spec(h.p, "TEST", [("x", "y")], "qa", "Q2.6"), test_judge)
        return a, t

    def _two_answers(self, h, judged, lose_tape):
        for choice in ("pass", "all_effective"):
            if lose_tape:
                CONS._MEM.clear()                                         # another clone / a lost journal
            try:
                self._stage_run(h, judged)
                self.fail("expected a question")
            except CONS.Ask as a:
                CONS.surface(h.p, "qa", a)
            ASK.answer(h.decisions, h.writer, 7, _pending(h)[-1].id, choice)

    def test_the_block_carries_the_runs_identity(self):
        h, judged = self._h(), []
        self._two_answers(h, judged, lose_tape=False)
        qa_b, test_b = _pending(h)
        self.assertEqual(qa_b.get("cons_used"), None)                   # nothing applied before the first point
        self.assertEqual(test_b.get("cons_used"), "conservative:QA:#7:qa:Q2.5:L0")
        for b in (qa_b, test_b):
            self.assertRegex(str(b.get("cons_run")), r"^[0-9a-f]{12}(/[0-9a-f]{12})?$")
            self.assertRegex(str(b.get("cons_brief")), r"^[0-9a-f]{12}$")
            self.assertNotIn("login", "%s %s" % (b.get("cons_run"), b.get("cons_brief")))   # hashes, never inputs

    def test_without_the_tape_each_point_is_asked_once(self):
        h, judged = self._h(), []
        self._two_answers(h, judged, lose_tape=True)
        CONS._MEM.clear()
        a, t = self._stage_run(h, judged)
        CONS.flush(h.p)
        self.assertEqual((a.choice, a.by), ("pass", "human"))
        self.assertEqual((t.choice, t.by), ("all_effective", "human"))
        self.assertEqual(len(_pending(h)), 2)                             # QA once, TEST once — never QA again
        self.assertEqual([b.get("refs") for b in _pending(h)],
                         ["conservative:QA:#7:qa:Q2.5:L0", "conservative:TEST:#7:qa:Q2.6:L0"])

    def test_without_the_tape_a_changed_run_is_judged_again(self):
        h, judged = self._h(), []
        self._two_answers(h, judged, lose_tape=True)
        CONS._MEM.clear()
        n0 = len(judged)
        try:
            self._stage_run(h, judged, issue="login — edited")            # the role's inputs changed
            asked = None
        except CONS.Ask as a:
            asked = a.question.refs
        # the run is not the one that asked: QA's earlier answer is not reused (its point is a new one) …
        self.assertEqual(judged[n0], "QA")
        self.assertEqual(asked, "conservative:QA:#7:qa:Q2.5:L0:a1")


class PreK6Blocks(unittest.TestCase):
    """item 17 overlap: a pending block written before K6 (no `cons_run` / `cons_brief`) and no local tape — the
    answer applies to the judge's decision now, as before (no stale retirement without evidence of another run)."""

    def test_old_block_answer_applies(self):
        h = qa_harness(self, roles=[role("DONE", plan="qa-report.md", human_items=[], followups=[])] * 6)
        h.p.valves = {"group.QA.conservative": True}
        h.p.git_dir = None
        h.p.journal = None
        h.decisions.record({"point": "conservative:QA", "kind": CONS.KIND, "refs": "conservative:QA:#7:qa:Q2.5:L0",
                            "stage": "qa", "by": "code", "status": "pending-human", "question": "old wording",
                            "options": ["block", "pass", "stop"], "stakes": "high", "group": "QA",
                            "recommended_sha": "0" * 64, "predict_first": "high-risk"})
        ASK.answer(h.decisions, h.writer, 7, _pending(h)[-1].id, "block")
        CONS._MEM.clear()
        CONS.begin(h.p)
        d = CONS.gate(h.p, JG.spec(h.p, "QA", [("x", "y")], "qa", "Q2.5"),
                      lambda s: Decision("pass", {"verdict": "pass", "quality_bar_met": "yes"}, "judge:sonnet", "dg"))
        self.assertEqual((d.choice, d.by), ("block", "human"))
        self.assertEqual([b for b in _blocks(h) if b.get("point") == CONS.STALE], [])


if __name__ == "__main__":
    unittest.main()
