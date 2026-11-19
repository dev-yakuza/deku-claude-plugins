"""K6 item 17 — cross-version resume: records an earlier engine wrote (K5 r1–r12) meet the K6 engine.

* a pending conservative question keyed by the judge's input digest (pre-r6 `conservative:<G>:<digest>`), answered:
  never applied to a decision point (the key is not a point) — the point is judged and asked under its own key;
* a tape written before the qa replay salt (r8 m2): the call no longer matches → the run is live, and the K6 rule
  (item 40) decides whether the answer still applies (the judge agrees) — never a replay of the old result;
* an `applied` block written AT the gate (pre-r9 `applied` timing) consumes the answer: the next entry is `:a1`;
* consumers that predate `human_choice` / `coerced_to` / `grounds` / `cons_*` (the §9.5 sheet, `dev health`, the
  grade import) read the executed `choice` and ignore the rest; the decision-log grammar round-trips unknown keys;
* an attended resume re-asks a pending block in its OLD wording (`group.<G>.conservative — …`) as it was stored —
  blind when the block is blind, the recommendation never added.
The 0.101.3 side of the downgrade (its prose reading the engine's records) is `replay/k6_downgrade_drill.py`.
"""

import unittest

import _util  # noqa: F401
from _k2 import role
from test_k2_qa_stage import qa_harness
from test_k4_fsm import driver

from guildcore import ask as ASK
from guildcore import state as ST
from guildcore.decisions import DecisionLog
from guildcore.judges.runner import Decision
from workflows.dev import conservative as CONS
from workflows.dev import grade as G
from workflows.dev import health as HE
from workflows.dev import judging as JG
from workflows.dev.stages import base as B
from workflows.dev.stages import qa as Q
from workflows.dev.stages.base import StageResult


def _blocks(h):
    return DecisionLog.load(h.gh.comments(7)).blocks


def _pending(h):
    return [b for b in _blocks(h) if b.get("kind") == CONS.KIND and b.get("status") == "pending-human"]


def _h(case, unattended=True):
    h = qa_harness(case, unattended=unattended,
                   roles=[role("DONE", plan="qa-report.md", human_items=[], followups=[])] * 6,
                   judges={"QA": lambda spec: Decision("pass", {"defects": [], "checklist": [], "verdict": "pass",
                                                                "quality_bar_met": "yes"}, "judge:sonnet", "dg")})
    h.p.valves = {"group.QA.conservative": True}
    h.p.git_dir = None
    h.p.journal = None
    CONS._MEM.clear()
    return h


def _old_block(h, refs, question="group.QA.conservative — QA Q2.5 결정을 사람이 정함", blind=True, **extra):
    f = {"point": "conservative:QA", "kind": CONS.KIND, "refs": refs, "stage": "qa", "by": "code",
         "status": "pending-human", "question": question, "options": ["block", "pass", "stop"], "stakes": "high",
         "group": "QA", "raised_by": "confirm"}
    if blind:
        f.update(recommended_sha="0" * 64, predict_first="high-risk")
    else:
        f.update(recommended="pass", recommended_by="judge:sonnet")
    f.update(extra)
    return h.decisions.record(f)


PASS = lambda s: Decision("pass", {"verdict": "pass", "quality_bar_met": "yes"}, "judge:sonnet", "dg")  # noqa: E731


class OldDigestKey(unittest.TestCase):
    def test_answered_digest_key_is_not_a_point(self):
        h = _h(self)
        did = _old_block(h, "conservative:QA:3f2a9c1d0e4b")
        ASK.answer(h.decisions, h.writer, 7, did, "block")
        CONS.begin(h.p)
        with self.assertRaises(CONS.Ask) as cm:
            CONS.gate(h.p, JG.spec(h.p, "QA", [("x", "y")], "qa", "Q2.5"), PASS)
        self.assertEqual(cm.exception.question.refs, "conservative:QA:#7:qa:Q2.5:L0")
        self.assertEqual([b for b in _blocks(h) if b.get("point") in ("applied", CONS.STALE)], [])


class SaltlessTape(unittest.TestCase):
    def _asked_with_old_tape(self, judge):
        h = _h(self, unattended=False)
        h.p.valves = {"group.QA.conservative": True}
        r = CONS.guarded(h.p, "qa", lambda: Q.run(h.p, diff_paths=[]))
        self.assertEqual(r.kind, StageResult.ASK)
        tape = CONS._MEM[(h.p.root, 7)][-1]
        for e in tape["roles"]:                                           # what an r7 tape looked like
            e["sig"][4] = "0123456789abcdef"
            e.pop("sig_after", None)
        tape.pop("brief", None)
        ASK.answer(h.decisions, h.writer, 7, _pending(h)[-1].id, "block")
        return h

    def test_live_and_applied_when_the_judge_agrees(self):
        h = self._asked_with_old_tape(None)
        r = CONS.guarded(h.p, "qa", lambda: Q.run(h.p, diff_paths=[]))
        qa = [b for b in _blocks(h) if b.get("point") == "QA"][-1]
        self.assertEqual((qa.get("choice"), qa.get("by")), ("block", "human"))
        self.assertNotEqual(r.kind, StageResult.DONE)


class EarlyApplied(unittest.TestCase):
    def test_applied_at_the_gate_consumes(self):
        h = _h(self)
        did = _old_block(h, "conservative:QA:#7:qa:Q2.5:L0")
        res = ASK.answer(h.decisions, h.writer, 7, did, "pass")
        B.record_code(h.p, "qa", "applied", "pass", refs=res)              # pre-r9: written before the effect
        CONS.begin(h.p)
        with self.assertRaises(CONS.Ask) as cm:
            CONS.gate(h.p, JG.spec(h.p, "QA", [("x", "y")], "qa", "Q2.5"), PASS)
        self.assertEqual(cm.exception.question.refs, "conservative:QA:#7:qa:Q2.5:L0:a1")


class OldConsumers(unittest.TestCase):
    BLOCK = {"point": "DE-ARB", "stage": "design", "by": "human", "choice": "pause", "inputs": "abc",
             "unsure": "false", "coerced": "true", "coerced_by": "conservative", "raw_choice": "reinvoke",
             "human_choice": "decide", "coerced_to": "pause by rule coerce_de_arb",
             "grounds": "사람 `decide` — `assumption` 없음", "cons_run": "a1b2c3d4e5f6", "future_key": "x"}

    def test_grammar_round_trips_unknown_keys(self):
        h = _h(self)
        did = h.decisions.record(dict(self.BLOCK))
        b = DecisionLog.load(h.gh.comments(7)).by_id(did)
        for k, v in self.BLOCK.items():
            self.assertEqual(b.get(k), v, k)

    def test_current_readers_tolerate_the_new_keys(self):
        """K6 r1 m9: the CURRENT parser / `dev health` / the sheet on a block with the K6 keys — not an old (0.101.3)
        parser: 0.101.3 never reads engine decision blocks (its H§M skips every `<!-- guild:` marker)."""
        h = _h(self)
        h.decisions.record(dict(self.BLOCK))
        h.decisions.record(dict(self.BLOCK, by="judge:sonnet", coerced_by="rule"))   # a judged, rule-coerced twin
        blocks = _blocks(h)
        m = HE.metrics({7: blocks})
        self.assertEqual(m["issues"], 1)
        # the person's block is no judged decision; the judged twin's executed choice `pause` is no dismiss / unsure,
        # and its rule coercion counts (the K6 keys human_choice / coerced_to / grounds change nothing)
        self.assertEqual((m["coercion"], m["unsure"]), (1.0, 0.0))
        ok, cands = G.predict_first_judgments(blocks, 7)
        self.assertEqual((ok, cands), ([], []))


class OldWordingReask(unittest.TestCase):
    def _resume(self, blind):
        h = _h(self, unattended=False)
        did = _old_block(h, "conservative:QA:#7:qa:Q2.5:L0", blind=blind)
        events = []

        class Ev(object):
            def emit(self, *a, **f):
                events.append((a[0], f))
        h.p.events = Ev()
        drv = driver(h, unattended=False)
        st = ST.derive(h.gh.issue(7).get("labels"))
        out = drv.resume(h.p, 7, st)
        return did, out, events

    def test_blind_block_is_asked_again_blind(self):
        did, out, events = self._resume(True)
        self.assertEqual(out.result.kind, StageResult.ASK)
        self.assertEqual(out.result.qid, did)
        kind, f = events[-1]
        self.assertEqual(kind, "ask")
        self.assertTrue(f["predict_first"])
        self.assertNotIn("recommended", f)
        self.assertIn("group.QA.conservative", f["question"])          # the stored wording, as it was

    def test_open_block_keeps_its_open_recommendation(self):
        _did, _out, events = self._resume(False)
        self.assertEqual(events[-1][1].get("recommended"), "pass")


if __name__ == "__main__":
    unittest.main()
