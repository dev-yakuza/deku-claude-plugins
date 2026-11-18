"""K5 review r4 — "needed before K6" (c): the §10.4 first-sprint SETTINGS follow the mode (workflows.dev.firstsprint).

* attended KICKOFF asks the interpretation-surface question (predict-first) without `attended_confirm_interpretation`;
* unattended EX-ARB BLOCKER dismiss → accept, `coerced_by: first-sprint`, `raw_choice` `F1:would-dismiss` (graded as
  EX-ARB:dismiss); after the go the `exarb.no_unattended_dismiss` valve carries it (`coerced_by: valve`) — the go
  sets that valve in the `auto` area, a person-released valve is not re-applied;
* HANDOFF shadow at every boundary (`HANDOFF-SHADOW`, cost kind monitoring) — its verdict never changes the flow, a
  failed shadow is skipped (journaled);
* a LIVE HANDOFF `ok_with_assumption` on a design artifact gap is a person's (pause), not a recorded assumption.
"""

import unittest

import _util  # noqa: F401
from _k2 import comment
from _k3 import XHarness, auditor, dev, finding
from _k4 import K4, decision, evidence, kickoff, tester_ok, techlead_ok
from test_k3_execute_stage import GREEN, TL_DONE, exarb
from test_k4_design import design_h
from test_k5_cli import Env

from guildcore import valves as VALVES
from guildcore.decisions import DecisionLog
from guildcore.journal import JournalView
from workflows.dev import grade as GR
from workflows.dev import predict as PF
from workflows.dev.stages import analyze as A
from workflows.dev.stages import design as D
from workflows.dev.stages import execute as X
from workflows.dev.stages.base import StageResult

DISMISS = dict(verdict="dismiss", reason="guarded by caller",
               evidence=[{"path": "lib/a.dart", "line": 1, "quote": "int a() => 2;"}])


def exarb_blocks(h):
    return [b for b in DecisionLog.load(h.gh.comments(7)).blocks if b.get("point") == "EX-ARB"]


def on(h):
    h.p._first_sprint = True          # the mode (predict.first_sprint) — decided once per Ports
    return h


class Interpretation(unittest.TestCase):
    def test_attended_first_sprint_asks_the_interpretation_blind(self):
        h = on(K4(self, unattended=False, roles=[evidence(self)], judges={"KICKOFF": kickoff()}))
        r = A.run(h.p)
        self.assertEqual(r.kind, StageResult.ASK)
        ask = [kw for w, kw in h.events if w == "ask"][-1]
        self.assertEqual(ask["kind"], "interpretation-surface")
        self.assertTrue(ask["predict_first"])

    def test_steady_state_does_not(self):
        h = K4(self, unattended=False, roles=[evidence(self)], judges={"KICKOFF": kickoff(), "HANDOFF": []})
        h.p._first_sprint = False
        A.run(h.p)
        self.assertFalse([kw for w, kw in h.events if w == "ask"])


class ExArb(unittest.TestCase):
    def _run(self, valves=None, first=True):
        h = XHarness(self, roles=[dev(), TL_DONE, auditor([finding()]), dev(), TL_DONE, auditor()], suites=[GREEN, GREEN],
                     judges={"EX-ARB": [exarb(**DISMISS)]})
        h.p._first_sprint = first
        h.p.valves = valves or {}
        return h, X.run(h.p, "implement")

    def test_unattended_blocker_dismiss_is_forced_to_accept(self):
        h, r = self._run()
        self.assertNotEqual(r.cause, "disputed auditor BLOCKER")
        blk = exarb_blocks(h)[0]
        self.assertEqual(blk.get("choice"), "F1:accept")
        self.assertEqual(blk.get("raw_choice"), "F1:would-dismiss")
        self.assertEqual((blk.get("coerced"), blk.get("coerced_by")), ("true", "first-sprint"))
        self.assertEqual(GR.group_of(blk), "EX-ARB:dismiss")              # graded as the dismiss it would have been

    def test_after_the_go_the_valve_carries_it(self):
        h, r = self._run(valves={"exarb.no_unattended_dismiss": True}, first=False)
        blk = exarb_blocks(h)[0]
        self.assertEqual((blk.get("choice"), blk.get("coerced_by")), ("F1:accept", "valve"))

    def test_steady_state_without_the_valve_disputes(self):
        h, r = self._run(first=False)
        self.assertEqual(r.cause, "disputed auditor BLOCKER")


class Shadow(unittest.TestCase):
    def test_analyze_shadow_is_recorded_and_never_acts(self):
        gap = decision("upstream_gap", {"verdict": "upstream_gap", "reason": "AC vague", "signature": ["AC #1"]})
        h = on(K4(self, roles=[evidence(self)], judges={"KICKOFF": kickoff(), "HANDOFF": gap}))
        r = A.run(h.p)
        self.assertEqual(r.kind, StageResult.ADVANCE)                    # an upstream_gap shadow changes nothing
        sh = h.decisions_of("HANDOFF-SHADOW")
        self.assertEqual([(b.get("choice"), b.get("boundary"), b.get("shadow")) for b in sh],
                         [("upstream_gap", "analyze→design", "true")])
        spec = [s for s in h.calls["judges"] if s.group == "HANDOFF"][0]
        self.assertEqual((spec.point, spec.kind), ("HANDOFF-SHADOW", "monitoring"))

    def test_failed_shadow_is_skipped(self):
        h = on(K4(self, roles=[evidence(self)], judges={"KICKOFF": kickoff()}))     # no HANDOFF answer: it fails
        h.p.journal = h.journal
        self.assertEqual(A.run(h.p).kind, StageResult.ADVANCE)
        self.assertFalse(h.decisions_of("HANDOFF-SHADOW"))
        self.assertTrue([x for x in JournalView.read(h.common, 7).entries if x.get("what") == "handoff-shadow-skipped"])

    def test_design_boundary_shadow(self):
        ok = decision("ok", {"verdict": "ok"})
        h = on(design_h(self, cast="", ui="false", roles=[tester_ok(self, (1, 2)), techlead_ok(self)],
                        judges={"HANDOFF": ok}))
        self.assertEqual(D.run(h.p).kind, StageResult.ADVANCE)
        self.assertEqual([b.get("boundary") for b in h.decisions_of("HANDOFF-SHADOW")], ["design→execute"])


class LiveAssumption(unittest.TestCase):
    def test_design_gap_with_an_assumption_is_a_persons_in_the_first_sprint(self):
        ok = decision("ok_with_assumption", {"verdict": "ok_with_assumption", "line": "AC 2 is covered by C1"})
        h = on(design_h(self, cast="", ui="false", roles=[tester_ok(self, (1,)), tester_ok(self, (1,)),
                                                          techlead_ok(self)], judges={"HANDOFF": ok}))
        r = D.run(h.p)
        self.assertEqual(r.kind, StageResult.PAUSE)
        self.assertIn("HANDOFF ok_with_assumption, first sprint", r.cause + (r.line or ""))


class GoInheritance(unittest.TestCase):
    def _env(self):
        e = Env(self, labels=("guild:execute",), config={"version": "0.101.0", "language": "ko",
                                                          "engine": {"first_sprint_mode": "auto"}})
        go = comment("<!-- guild:note -->\nfirst-sprint go/no-go\nresult: go\n", 4100)
        e.h.gh.fx["issues"]["99"] = {"number": 99, "title": "sprint", "body": "", "state": "OPEN",
                                    "labels": [{"name": "guild:sprint"}], "comments": [go], "timeline": [],
                                    "url": "https://github.com/o/r/issues/99"}
        p = e.h.p
        p.git_dir, p.valves, p._first_sprint = e.common, {}, None
        return e, p

    def test_go_sets_the_no_dismiss_valve(self):
        e, p = self._env()
        self.assertFalse(PF.first_sprint(p))
        self.assertTrue(VALVES.load(e.common)["auto"].get("exarb.no_unattended_dismiss"))
        self.assertTrue(p.valves.get("exarb.no_unattended_dismiss"))

    def test_released_valve_is_not_reapplied(self):
        e, p = self._env()
        VALVES.human_clear(e.common, "exarb.no_unattended_dismiss", "person", "released")
        self.assertFalse(PF.first_sprint(p))
        self.assertIsNone(VALVES.load(e.common)["auto"].get("exarb.no_unattended_dismiss"))


if __name__ == "__main__":
    unittest.main()
