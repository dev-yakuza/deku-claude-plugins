"""K5 review r4 — the answer paths: `dev answer` under the Issue lock (m3), the qualified `guild-answer:` (m4).

m3  `dev answer` holds the target's IssueLock while it writes; a live run holding it → busy (4), nothing written.
m4  `guild-answer: #7/D<k> <tok>` is accepted on #7, rejected (`answer names Issue #8`) when it names another Issue.
"""

import json
import unittest

import _util  # noqa: F401
from _k4 import K4, comment, decision, evidence, kickoff, out_role
from test_k4_fsm import driver
from test_k5_r4 import _env

from guildcore import ask as ASK
from guildcore import worker as W
from guildcore.decisions import DecisionLog
from workflows.dev import cli as CLI
from workflows.dev.stages import analyze as A
from workflows.dev.stages import base as B
from workflows.dev.stages.base import StageResult


class M3AnswerLock(unittest.TestCase):
    def test_answer_refused_while_a_run_holds_the_issue(self):
        e, p = _env(self)
        q = ASK.Question("escalation", "which way?", [{"token": "go", "label": "go"}, {"token": "stop", "label": "stop"}])
        r = B.ask(p, "analyze", q, "which way?")
        lk = W.IssueLock(e.common, 7)
        lk.acquire("unattended")
        try:
            self.assertEqual(CLI.main(["answer", "--issue", "7", "--qid", r.qid, "--choice", "go"], e.d), CLI.EXIT_BUSY)
            msg = json.loads(e.lines()[-1].split(">>> ENGINE <<<")[-1])
            self.assertTrue(msg.get("busy"))
            self.assertIn("unattended", msg["error"])
            self.assertFalse([b for b in DecisionLog.load(e.h.gh.comments(7)).blocks if b.get("resolves") == r.qid])
        finally:
            lk.release()
        self.assertEqual(CLI.main(["answer", "--issue", "7", "--qid", r.qid, "--choice", "go"], e.d), 0)
        self.assertTrue([b for b in DecisionLog.load(e.h.gh.comments(7)).blocks if b.get("resolves") == r.qid])
        # the answer released the lock it took
        self.assertFalse(W.IssueLock(e.common, 7).held_by_other())


class M4QualifiedAnswer(unittest.TestCase):
    def _paused(self):
        h = K4(self, roles=[evidence(self)], judges={"KICKOFF": kickoff(goal="unclear"),
                                                     "STAKES": decision("high", {"level": "high"})})
        return h, A.run(h.p)

    def _answer(self, h, line):
        it = h.issue()
        it["comments"].append(comment(line, 900, at="2026-11-16T01:00:00Z"))
        it["labels"] = [lb for lb in it["labels"] if lb["name"] != "guild:needs-human"]
        it["timeline"].append({"id": 5, "event": "unlabeled", "label": {"name": "guild:needs-human"},
                               "created_at": "2026-11-16T01:00:01Z", "actor": {"login": "owner"}})

    def test_same_issue_qualified_answer_resumes(self):
        h, r = self._paused()
        self._answer(h, "guild-answer: #7/%s i1" % r.qid)
        h.roles += [evidence(self), out_role(self, "DONE", ac_patch=[])]
        h.judges["KICKOFF"] = kickoff(goal="unclear")
        driver(h, {"design": lambda p, **k: StageResult(StageResult.PAUSE, cause="design stub")}).run(7)
        self.assertIn("guild:design", h.labels())
        self.assertIn("- (선택) i1: hide the count", h.body_with("analyze:output"))

    def test_other_issue_qualified_answer_is_rejected(self):
        h, r = self._paused()
        self._answer(h, "guild-answer: #8/%s i1" % r.qid)
        out = driver(h).run(7)
        self.assertNotIn("guild:design", h.labels())
        rej = h.decisions_of("rejected-answer")
        self.assertTrue(rej and rej[-1].get("reason") == "answer names Issue #8", [b.get("reason") for b in rej])
        self.assertNotEqual(out.result.kind, StageResult.ADVANCE)


if __name__ == "__main__":
    unittest.main()
