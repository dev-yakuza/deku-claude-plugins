"""K6 blocker — predict_first enforcement (design §2.6 `predict_first`, R5J-M4, R6J-m4, §9.5, §10.4).

* when: high-risk group (always) · `group.<g>.conservative` valve · §9.5 watch group · `config.learning.predict_first`
  for readiness / disputed-blocker / loopback · first-sprint mode (on; auto until a TRUSTED recorded go; a failed
  read keeps it on). A question with no recommendation is left alone (nothing to withhold).
* attended: the ask event carries no recommendation, the pending block only `recommended_sha` + `predict_first:
  <why>`; `dev answer` reveals `recommended` + `nonce` (sha checks) and prints it; a resume re-asks blind.
* unattended: the pause comment never names the recommendation; the nonce is journaled before the commitment; a
  member's `guild-answer` settles with the reveal.
* KICKOFF's block seals `chosen` (`chosen_sha`).
"""

import hashlib
import json
import unittest

import _util  # noqa: F401
from _k2 import comment
from test_k5_cli import Env

from guildcore import ask as ASK
from guildcore import journal as J
from guildcore.decisions import DecisionLog
from workflows.dev import cli as CLI
from workflows.dev import fsm as F
from workflows.dev import predict as PF
from workflows.dev.stages import base as B
from workflows.dev.stages.base import StageResult


def q(kind="escalation", rec="go", group=None, point=None):
    return ASK.Question(kind, "what now?", [{"token": "go", "label": "go"}, {"token": "stop", "label": "stop"}],
                        recommended=rec, recommended_by="judge:sonnet", group=group, point=point)


def blocks(e):
    return DecisionLog.load(e.h.gh.comments(7)).blocks


class When(unittest.TestCase):
    def _p(self, mode="off", **kw):
        e = Env(self, config={"version": "0.101.0", "language": "ko", "engine": {"first_sprint_mode": mode},
                              "learning": kw.pop("learning", {})}, **kw)
        e.h.p.git_dir = e.common
        e.h.p.valves = {}
        return e

    def test_high_risk_group_is_always_predict_first(self):
        e = self._p("off")
        for kind in ("readiness", "close-decided", "disputed-blocker", "leaf-split", "integration-gap", "escalation"):
            self.assertEqual(PF.forced(e.h.p, q(kind)), "high-risk", kind)

    def test_selective_group_is_not_forced_when_steady(self):
        e = self._p("off")
        self.assertIsNone(PF.forced(e.h.p, q("design-block")))
        self.assertIsNone(PF.forced(e.h.p, q("loopback", point="loopback-ask:test")))

    def test_conservative_valve_and_watch_group(self):
        e = self._p("off")
        e.h.p.valves = {"group.DE-ARB.conservative": True}
        self.assertEqual(PF.forced(e.h.p, q("design-block")), "conservative")
        from guildcore import journal as Jn
        import os
        from workflows.dev import grade as GR
        os.makedirs(Jn.engine_dir(e.common), exist_ok=True)
        J.atomic_write(GR.state_path(e.common), json.dumps({"watch": {"TEST": "D3"}, "streak": {}}))
        self.assertEqual(PF.forced(e.h.p, q("loopback", point="loopback-ask:test")), "watch")
        self.assertIsNone(PF.forced(e.h.p, q("loopback", point="loopback-ask:qa")))

    def test_learning_option_covers_its_three_kinds_only(self):
        e = self._p("off", learning={"predict_first": True})
        self.assertEqual(PF.forced(e.h.p, q("loopback", point="loopback-ask:qa")), "option")
        self.assertIsNone(PF.forced(e.h.p, q("design-block")))

    def test_first_sprint_auto_ends_only_on_a_trusted_recorded_go(self):
        e = self._p("auto")
        self.assertEqual(PF.forced(e.h.p, q("design-block")), "first-sprint")            # no go anywhere
        fx = e.h.gh.fx["issues"]
        go = comment("<!-- guild:note -->\nfirst-sprint go/no-go\nresult: go\n", 4100)
        fx["99"] = {"number": 99, "title": "sprint", "body": "", "state": "OPEN", "labels": [{"name": "guild:sprint"}],
                    "comments": [dict(go, author_association="NONE", user={"login": "stranger"})], "timeline": [],
                    "url": "https://github.com/o/r/issues/99"}
        e.h.p._first_sprint = None
        self.assertEqual(PF.forced(e.h.p, q("design-block")), "first-sprint")            # an outsider's go: no
        fx["99"]["comments"].append(go)
        e.h.p._first_sprint = None
        self.assertIsNone(PF.forced(e.h.p, q("design-block")))                           # a trusted go ends it
        self.assertTrue(PF.go_recorded(e.h.p))

    def test_first_sprint_read_failure_keeps_it_on_and_on_mode_ignores_go(self):
        e = self._p("auto")

        def boom(**k):
            raise RuntimeError("HTTP 502")
        e.h.gh.issue_rows = boom
        self.assertTrue(PF.first_sprint(e.h.p))
        e2 = self._p("on")
        self.assertTrue(PF.first_sprint(e2.h.p))

    def test_no_recommendation_is_left_alone(self):
        e = self._p("on")
        qq = PF.apply(e.h.p, q("escalation", rec=None))
        self.assertFalse(qq.predict_first)


class Attended(unittest.TestCase):
    def test_ask_hides_answer_reveals_and_resume_reasks_blind(self):
        e = Env(self, labels=("guild:execute",), unattended=False)
        p = e.h.p
        p.git_dir = e.common
        r = B.ask(p, "execute", q("escalation"), "what now?")
        ev = [kw for what, kw in e.h.events if what == "ask"][-1]
        self.assertTrue(ev["predict_first"])
        self.assertNotIn("recommended", ev)
        pend = [b for b in blocks(e) if b.id == r.qid][0]
        self.assertIsNone(pend.get("recommended"))
        self.assertEqual(pend.get("predict_first"), "high-risk")
        # the session ends; /gld resume re-asks the SAME question blind
        e.h.events[:] = []
        out = F.Driver(lambda n, s, v=None: p, unattended=False).run(7)
        self.assertEqual(out.result.qid, r.qid)
        ev2 = [kw for what, kw in e.h.events if what == "ask"][-1]
        self.assertTrue(ev2["predict_first"])
        self.assertNotIn("recommended", ev2)
        # dev answer reveals it, after the answer, and the commitment checks
        self.assertEqual(CLI.main(["answer", "--issue", "7", "--qid", r.qid, "--choice", "stop"], e.d), 0)
        msg = json.loads(e.lines()[-1].split(">>> ENGINE <<<")[-1]) if ">>> ENGINE <<<" in e.lines()[-1] \
            else json.loads(e.lines()[-1])
        self.assertEqual(msg["revealed"]["recommended"], "go")
        res = [b for b in blocks(e) if b.get("resolves") == r.qid][0]
        self.assertEqual(hashlib.sha256(("go" + res.get("nonce")).encode()).hexdigest(), pend.get("recommended_sha"))


class Unattended(unittest.TestCase):
    def test_pause_never_names_it_and_a_member_answer_reveals_it(self):
        e = Env(self, labels=("guild:execute",))
        p = e.h.p
        p.git_dir = e.common
        r = B.ask(p, "execute", q("escalation", rec="go"), "what now?",
                  {"cause_kind": "ambiguity", "line": "what now?", "token_cause": "ambiguity: what now?"})
        self.assertEqual(r.kind, StageResult.PAUSE)
        pend = [b for b in blocks(e) if b.id == r.qid][0]
        self.assertIsNone(pend.get("recommended"))
        self.assertTrue(pend.get("recommended_sha"))
        nh = e.h.body_with("needs-human")
        self.assertNotIn("recommended", nh)
        self.assertNotIn("권장", nh)
        # the nonce was journaled BEFORE the block
        evs = [x for x in J.Journal(e.h.common, 7).entries if x.get("what", "").startswith("predict-first")]
        self.assertEqual([x["what"] for x in evs], ["predict-first-nonce", "predict-first-qid"])
        it = e.h.issue()
        it["comments"].append(dict(comment("guild-answer: %s stop" % r.qid, 990, at="2099-01-01T00:00:00Z")))
        it["labels"] = [lb for lb in it["labels"] if lb["name"] != "guild:needs-human"]
        it["timeline"].append({"id": 991, "event": "unlabeled", "label": {"name": "guild:needs-human"},
                               "created_at": "2099-01-01T00:00:01Z", "actor": {"login": "owner"}})
        F.Driver(lambda n, s, v=None: p, unattended=True,
                 stages={"execute": lambda p_, v=None: StageResult(StageResult.PAUSE, cause="x")}).run(7)
        res = [b for b in blocks(e) if b.get("resolves") == r.qid][0]
        self.assertEqual((res.get("by"), res.get("choice"), res.get("recommended")), ("human", "stop", "go"))
        self.assertEqual(hashlib.sha256(("go" + res.get("nonce")).encode()).hexdigest(), pend.get("recommended_sha"))


if __name__ == "__main__":
    unittest.main()
