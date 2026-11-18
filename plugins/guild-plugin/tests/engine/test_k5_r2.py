"""K5 review r2 — regressions for M1 and the minors (review-k5-r2.md).

M1  an engine-level question (the per-Issue budget) has the ENGINE scope: `decisions.live` never supersedes it by a
    stage mismatch, so the §2.5 resume reaches the answer channel. Every case runs the REAL resume path
    (`dev run` → restart check → `Driver.run` → `Driver.resume` → boundary), never the boundary alone:
    unattended member answer → one raise, the stage runs · attended session end → resume asks the SAME D-id →
    `dev answer` → the stage runs · an outsider's answer is rejected · a stale stage question's answer is named
    in its superseded block · the pending-regeneration question waits at execute
"""

import json
import os
import unittest

import _util  # noqa: F401
from _k2 import CFG, comment
from test_k5_cli import Env

from guildcore import cost as COST
from guildcore import decisions as D
from guildcore.decisions import DecisionLog
from workflows.dev import cli as CLI
from workflows.dev import fsm as F
from workflows.dev.stages.base import StageResult

BUDGET_CFG = dict(CFG, engine={"budget_usd_per_issue": 35.0})


def blocks(e):
    return DecisionLog.load(e.h.gh.comments(7)).blocks


class M1EngineScope(unittest.TestCase):
    """The real CLI → Driver path with stub stage functions (the stages are not under test)."""

    def _env(self, unattended=True, labels=("guild:execute",)):
        e = Env(self, labels=labels, unattended=unattended, config=BUDGET_CFG)
        self.ran = []
        stages = {"execute": lambda p, v=None: (self.ran.append(p.issue),
                                                StageResult(StageResult.PAUSE, cause="execute stub"))[1]}

        def driver(ports_for, unattended=True, plugin=None, events=None, boundary=None):
            return F.Driver(ports_for, unattended=unattended, plugin=plugin, stages=stages, events=events,
                            boundary=boundary)
        e.d.driver_cls = driver
        COST.record(e.common, {"issue": 7, "total_cost_usd": 36.0, "kind": "score", "who": "developer"})
        return e

    def _answer_line(self, e, qid, token, login="owner", assoc="OWNER", cid=990, remover="owner"):
        it = e.h.issue()
        c = comment("guild-answer: %s %s" % (qid, token), cid, at="2099-01-01T00:00:00Z")
        c.update(user={"login": login}, author_association=assoc)
        it["comments"].append(c)
        it["labels"] = [lb for lb in it["labels"] if lb["name"] != "guild:needs-human"]
        it["timeline"].append({"id": cid + 1, "event": "unlabeled", "label": {"name": "guild:needs-human"},
                               "created_at": "2099-01-01T00:00:01Z", "actor": {"login": remover}})

    def _budget_q(self, e):
        return [b for b in blocks(e) if b.get("kind") == "budget" and b.get("status") == "pending-human"]

    def test_budget_question_has_the_engine_scope_and_live_keeps_it(self):
        e = self._env()
        self.assertEqual(e.run("--unattended"), 0)
        q = self._budget_q(e)[0]
        self.assertEqual(q.get("stage"), D.ENGINE_SCOPE)
        from guildcore import state as ST
        for label in ("guild:execute", "guild:design", "guild:test"):
            alive, why = D.live(q, ST.derive([label]), [{"id": 1, "event": "labeled", "label": {"name": label},
                                                         "created_at": "2099-01-01T00:00:00Z"}])
            self.assertTrue(alive, why)                              # no stage move ever makes it stale

    def test_unattended_member_answer_is_settled_raised_once_and_the_stage_runs(self):
        e = self._env()
        self.assertEqual(e.run("--unattended"), 0)
        self.assertEqual(self.ran, [])                               # stopped at the boundary
        qid = self._budget_q(e)[0].id
        self.assertIn("guild:needs-human", e.h.labels())
        self._answer_line(e, qid, "continue")
        self.assertEqual(e.run("--unattended"), 0)
        self.assertEqual(self.ran, [7])                              # the rerun went on
        bl = blocks(e)
        self.assertFalse([b for b in bl if b.get("status") == "superseded"])
        ans = [b for b in bl if b.get("resolves") == qid]
        self.assertEqual([(b.get("by"), b.get("choice"), b.get("answered_by")) for b in ans],
                         [("human", "continue", "owner")])
        raises = [(b.get("budget_from"), b.get("budget_to")) for b in bl if b.get("point") == "budget"]
        self.assertEqual(raises, [("35.00", "70.00")])
        self.assertEqual(e.run("--unattended"), 0)                   # a third run: never raised twice
        self.assertEqual(len([b for b in blocks(e) if b.get("point") == "budget"]), 1)

    def test_unattended_label_still_on_waits_without_a_new_question(self):
        e = self._env()
        e.run("--unattended")
        n0 = len(blocks(e))
        self.assertEqual(e.run("--unattended"), 0)
        self.assertEqual(len(blocks(e)), n0)                         # nothing written, nothing superseded
        self.assertEqual(self.ran, [])
        res = json.loads(e.lines()[-1])
        self.assertIn("waiting for a human answer", res["result"])

    def test_unattended_outsider_answer_is_rejected_and_asked_again(self):
        e = self._env()
        e.run("--unattended")
        qid = self._budget_q(e)[0].id
        self._answer_line(e, qid, "continue", login="stranger", assoc="NONE", remover="stranger")
        self.assertEqual(e.run("--unattended"), 0)
        self.assertEqual(self.ran, [])
        bl = blocks(e)
        self.assertTrue([b for b in bl if b.get("point") == "rejected-answer" and b.get("refs") == qid])
        self.assertFalse([b for b in bl if b.get("point") == "budget"])           # no raise
        open_q = [b for b in self._budget_q(e) if b.id not in DecisionLog.load(e.h.gh.comments(7)).resolved_ids()]
        self.assertEqual(len(open_q), 1)                             # rule 3 re-judged → asked anew, still paused
        self.assertNotEqual(open_q[0].id, qid)
        self.assertIn("guild:needs-human", e.h.labels())

    def test_attended_session_end_resume_asks_same_qid_then_answer_proceeds(self):
        e = self._env(unattended=False)
        self.assertEqual(e.run("--attended", "--worker"), 0)
        qid = self._budget_q(e)[0].id
        e.h.events[:] = []
        self.assertEqual(e.run("--attended", "--worker"), 0)         # the session ended; /gld resume 7
        asks = [kw for what, kw in e.h.events if what == "ask"]
        evs = [ev for ev in __import__("guildcore.worker", fromlist=["Events"]).Events(e.common, 7).read()
               if ev.get("type") == "ask"]
        self.assertEqual([a["qid"] for a in asks + evs][-1], qid)     # the SAME question, not a hold
        self.assertEqual(self.ran, [])
        self.assertFalse([b for b in blocks(e) if b.get("status") == "superseded"])
        rc = CLI.main(["answer", "--issue", "7", "--qid", qid, "--choice", "continue"], e.d)
        self.assertEqual(rc, 0, e.out.getvalue())
        self.assertEqual(e.run("--attended", "--worker"), 0)
        self.assertEqual(self.ran, [7])
        self.assertEqual([(b.get("budget_from"), b.get("budget_to")) for b in blocks(e) if b.get("point") == "budget"],
                         [("35.00", "70.00")])

    def test_stale_stage_question_names_the_read_answer_in_its_superseded_block(self):
        e = Env(self, labels=("guild:execute",))
        from guildcore import ask as ASK
        q = ASK.Question("design-block", "q", [{"token": "stop", "label": "stop"}])
        did = e.h.decisions.record(q.pending_fields(stage="design"))
        e.h.decisions.stamp_server_time(did)
        self._answer_line(e, did, "stop")
        drv = F.Driver(lambda n, s, v=None: e.h.p, unattended=True,
                       stages={"execute": lambda p, v=None: StageResult(StageResult.PAUSE, cause="x")})
        drv.run(7)
        sup = [b for b in blocks(e) if b.get("resolves") == did]
        self.assertEqual(len(sup), 1)
        self.assertEqual(sup[0].get("status"), "superseded")
        self.assertEqual(sup[0].get("by"), "code")                   # never applied as a human answer
        self.assertIn("answer `stop` by owner read, not applied", sup[0].get("reason"))
        self.assertEqual(str(sup[0].get("answer_comment")), "990")

    def test_pending_regeneration_waits_at_execute(self):
        from guildcore import ask as ASK
        from guildcore import state as ST
        q = ASK.Question("pending-regeneration", "t", [{"token": "ok", "label": "ok"}], waits_at="execute")
        f = q.pending_fields(stage="test")
        self.assertEqual(f["waits_at"], "execute")
        from guildcore.records import decisions as fmt
        blk = fmt.DecisionComment(fmt.render_comment([fmt.render_block(3, dict(f, id="D3"))])).blocks[0]
        self.assertTrue(D.live(blk, ST.derive(["guild:execute"]), [])[0])
        self.assertFalse(D.live(blk, ST.derive(["guild:test"]), [])[0])


if __name__ == "__main__":
    unittest.main()
